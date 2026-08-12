"""Outbox index worker (P2). Drains the transactional outbox and projects canonical PostgreSQL state onto
the Qdrant index. It claims an event through the SECURITY DEFINER dispatcher (lease token), performs the
index mutation, and only then completes the lease. If the index is UNAVAILABLE the event is retried (stays
PENDING with backoff) and is NEVER marked processed — so a Qdrant outage is a replayable backlog, not data
loss. Event semantics: index / deprecate / delete / supersede.

Outbox conventions (aggregate_type = 'private_episode' | 'contract_version'):
  PRIVATE_INDEX      aggregate_id = episode_id      payload: {owner_user_id}
  PRIVATE_DELETE     aggregate_id = episode_id      payload: {owner_user_id, version_number?}
  CONTRACT_INDEX     aggregate_id = version_id      payload: {}
  CONTRACT_DEPRECATE aggregate_id = version_id      payload: {version_number}
  CONTRACT_DELETE    aggregate_id = version_id      payload: {version_number}
  CONTRACT_SUPERSEDE aggregate_id = new_version_id  payload: {old_version_id, old_version_number}
"""
from __future__ import annotations
import json
from sqlalchemy import text
from ..persistence.tenant_context import tenant_tx
from ..persistence.postgres import claim_outbox_event, mark_processed, mark_retry, redact
from . import canonical_loaders as cl
from .models import PRIVATE, SHARED, ObjectType, IndexRecord, point_id

PRIVATE_INDEX = "PRIVATE_INDEX"
PRIVATE_DELETE = "PRIVATE_DELETE"
CONTRACT_INDEX = "CONTRACT_INDEX"
CONTRACT_DEPRECATE = "CONTRACT_DEPRECATE"
CONTRACT_DELETE = "CONTRACT_DELETE"
CONTRACT_SUPERSEDE = "CONTRACT_SUPERSEDE"


def _private_record(row, embedder) -> tuple:
    txt = cl.embed_text(row["canonical"])
    rec = IndexRecord(scope=PRIVATE, object_type=ObjectType.PRIVATE_EPISODE.value,
                      object_id=row["object_id"], org_id=row["org_id"], content_hash=row["content_hash"],
                      text=txt, owner_user_id=row["owner_user_id"], repository_id=row.get("repository_id"),
                      version_number=1)
    return rec, embedder.embed([txt])[0]


def _contract_record(row, embedder) -> tuple:
    txt = cl.embed_text(row["canonical"])
    rec = IndexRecord(scope=SHARED, object_type=ObjectType.CONTRACT_VERSION.value,
                      object_id=row["object_id"], org_id=row["org_id"], content_hash=row["content_hash"],
                      text=txt, repository_id=row.get("repository_id"), contract_id=row.get("contract_id"),
                      version_number=row["version_number"])
    return rec, embedder.embed([txt])[0]


async def load_outbox_payload(engine, org_id, event_id) -> dict:
    async with tenant_tx(engine, org_id) as c:
        r = (await c.execute(text("SELECT payload_json FROM outbox_events WHERE id=:e"),
                             {"e": event_id})).scalar()
    if r is None:
        return {}
    return r if isinstance(r, dict) else json.loads(r)


async def process_event(engine, index, embedder, event, payload) -> str:
    """Apply one event to the index. Returns an action tag. Raises on index/store errors (-> retry)."""
    et = event["event_type"]
    oid = event["aggregate_id"]
    org = event["org_id"]

    if et == PRIVATE_INDEX:
        owner = payload.get("owner_user_id")
        row = await cl.load_private_episode(engine, org, owner, oid)
        if row is None:                                  # vanished -> idempotent delete
            await index.delete(PRIVATE, [point_id(ObjectType.PRIVATE_EPISODE.value, oid, 1)])
            return "PRIVATE_INDEX:missing_deleted"
        rec, vec = _private_record(row, embedder)
        await index.upsert([rec], [vec])
        return "PRIVATE_INDEX:upserted"

    if et == PRIVATE_DELETE:
        v = int(payload.get("version_number", 1))
        await index.delete(PRIVATE, [point_id(ObjectType.PRIVATE_EPISODE.value, oid, v)])
        return "PRIVATE_DELETE:deleted"

    if et == CONTRACT_INDEX:
        row = await cl.load_contract_version(engine, org, oid)
        if row is None or not row["is_current"] or row["governance_state"] != "promoted":
            v = int(row["version_number"]) if row else int(event.get("aggregate_version", 1))
            await index.delete(SHARED, [point_id(ObjectType.CONTRACT_VERSION.value, oid, v)])
            return "CONTRACT_INDEX:not_current_deleted"
        rec, vec = _contract_record(row, embedder)
        await index.upsert([rec], [vec])
        return "CONTRACT_INDEX:upserted"

    if et in (CONTRACT_DEPRECATE, CONTRACT_DELETE):
        v = int(payload.get("version_number", event.get("aggregate_version", 1)))
        await index.delete(SHARED, [point_id(ObjectType.CONTRACT_VERSION.value, oid, v)])
        return et + ":deleted"

    if et == CONTRACT_SUPERSEDE:
        old_id = payload.get("old_version_id")
        old_v = int(payload.get("old_version_number", 1))
        if old_id:
            await index.delete(SHARED, [point_id(ObjectType.CONTRACT_VERSION.value, old_id, old_v)])
        row = await cl.load_contract_version(engine, org, oid)   # oid = new version id
        if row is not None and row["is_current"] and row["governance_state"] == "promoted":
            rec, vec = _contract_record(row, embedder)
            await index.upsert([rec], [vec])
            return "CONTRACT_SUPERSEDE:swapped"
        return "CONTRACT_SUPERSEDE:old_removed"

    raise ValueError("unknown event_type %r" % (et,))


async def run_once(engine, index, embedder, worker_id, lease_seconds=30):
    ev = await claim_outbox_event(engine, worker_id, lease_seconds=lease_seconds)
    if ev is None:
        return None
    try:
        payload = await load_outbox_payload(engine, ev["org_id"], ev["id"])
        action = await process_event(engine, index, embedder, ev, payload)
    except Exception as e:                               # index/store failure -> replayable, never lost
        status = await mark_retry(engine, ev["id"], worker_id, ev["lease_token"], str(e), backoff_seconds=0)
        return {"event_id": ev["id"], "event_type": ev["event_type"], "status": status or "RETRY",
                "error": redact(str(e))}
    await mark_processed(engine, ev["id"], worker_id, ev["lease_token"])
    return {"event_id": ev["id"], "event_type": ev["event_type"], "status": "PROCESSED", "action": action}


async def drain(engine, index, embedder, worker_id, max_events=100, lease_seconds=30):
    out = []
    for _ in range(max_events):
        r = await run_once(engine, index, embedder, worker_id, lease_seconds=lease_seconds)
        if r is None:
            break
        out.append(r)
    return out
