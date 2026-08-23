"""Outbox index worker (P2 / P2.1). Drains the transactional outbox and projects canonical PostgreSQL
state onto the Qdrant index. It claims an event through the SECURITY DEFINER dispatcher (lease token),
performs the index mutation, and only then completes the lease. If the index is UNAVAILABLE the event is
retried (stays PENDING with backoff) and is NEVER marked processed — an outage is a replayable backlog, not
data loss.

Event ordering: an index event is resolved against the CURRENT canonical version, so a stale/reordered
CONTRACT_INDEX for a superseded version never overwrites the live point — it deletes that version's point
instead. Every processed/retried event is recorded in the append-only index_audit_events table.

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
from ..persistence.postgres import (claim_outbox_event, mark_processed, mark_retry, redact,
                                     heartbeat_outbox, emit_index_audit)
from . import canonical_loaders as cl
from .projection import build_record
from .models import PRIVATE, SHARED, ObjectType, point_id

PRIVATE_INDEX = "PRIVATE_INDEX"
PRIVATE_DELETE = "PRIVATE_DELETE"
CONTRACT_INDEX = "CONTRACT_INDEX"
CONTRACT_DEPRECATE = "CONTRACT_DEPRECATE"
CONTRACT_DELETE = "CONTRACT_DELETE"
CONTRACT_SUPERSEDE = "CONTRACT_SUPERSEDE"


def _record(scope, row, embedder):
    rec = build_record(scope, row)
    return rec, embedder.embed([rec.text])[0]


async def load_outbox_payload(engine, org_id, event_id) -> dict:
    async with tenant_tx(engine, org_id) as c:
        r = (await c.execute(text("SELECT payload_json FROM outbox_events WHERE id=:e"),
                             {"e": event_id})).scalar()
    if r is None:
        return {}
    return r if isinstance(r, dict) else json.loads(r)


async def process_event(engine, index, embedder, event, payload) -> dict:
    """Apply one event to the index. Returns an info dict (for audit). Raises on index/store errors."""
    et = event["event_type"]
    oid = event["aggregate_id"]
    org = event["org_id"]

    if et in (PRIVATE_INDEX, PRIVATE_DELETE):
        kind, scope = ObjectType.PRIVATE_EPISODE.value, PRIVATE
    else:
        kind, scope = ObjectType.CONTRACT_VERSION.value, SHARED
    info = {"object_kind": kind, "canonical_version_id": oid, "canonical_version_number": 1,
            "content_hash": None, "canonical_id": None, "collection": index.alias_for(scope),
            "qdrant_operation": "noop", "point_id": None}

    if et == PRIVATE_INDEX:
        row = await cl.load_private_episode(engine, org, payload.get("owner_user_id"), oid)
        if row is None:                                  # vanished -> idempotent delete
            pid = point_id(kind, oid, 1)
            await index.delete(PRIVATE, [pid])
            info.update(action="PRIVATE_INDEX:missing_deleted", qdrant_operation="delete", point_id=pid)
            return info
        rec, vec = _record(PRIVATE, row, embedder)
        await index.upsert([rec], [vec])
        info.update(action="PRIVATE_INDEX:upserted", qdrant_operation="upsert", point_id=rec.pid,
                    content_hash=row["content_hash"], canonical_id=row["object_id"])
        return info

    if et == PRIVATE_DELETE:
        v = int(payload.get("version_number", 1))
        pid = point_id(kind, oid, v)
        await index.delete(PRIVATE, [pid])
        info.update(action="PRIVATE_DELETE:deleted", qdrant_operation="delete", point_id=pid,
                    canonical_version_number=v)
        return info

    if et == CONTRACT_INDEX:
        row = await cl.load_contract_version(engine, org, oid)
        if row is None or not row["is_current"] or row["governance_state"] != "promoted":
            v = int(row["version_number"]) if row else int(event.get("aggregate_version", 1))
            pid = point_id(kind, oid, v)
            await index.delete(SHARED, [pid])            # stale/non-current -> never overwrites the live point
            info.update(action="CONTRACT_INDEX:not_current_deleted", qdrant_operation="delete",
                        point_id=pid, canonical_version_number=v)
            return info
        rec, vec = _record(SHARED, row, embedder)
        await index.upsert([rec], [vec])
        info.update(action="CONTRACT_INDEX:upserted", qdrant_operation="upsert", point_id=rec.pid,
                    content_hash=row["content_hash"], canonical_id=row["contract_id"],
                    canonical_version_number=row["version_number"])
        return info

    if et in (CONTRACT_DEPRECATE, CONTRACT_DELETE):
        v = int(payload.get("version_number", event.get("aggregate_version", 1)))
        pid = point_id(kind, oid, v)
        await index.delete(SHARED, [pid])
        info.update(action=et + ":deleted", qdrant_operation="delete", point_id=pid,
                    canonical_version_number=v)
        return info

    if et == CONTRACT_SUPERSEDE:
        old_id = payload.get("old_version_id")
        old_v = int(payload.get("old_version_number", 1))
        if old_id:
            await index.delete(SHARED, [point_id(kind, old_id, old_v)])
        row = await cl.load_contract_version(engine, org, oid)   # oid = new version id
        if row is not None and row["is_current"] and row["governance_state"] == "promoted":
            rec, vec = _record(SHARED, row, embedder)
            await index.upsert([rec], [vec])
            info.update(action="CONTRACT_SUPERSEDE:swapped", qdrant_operation="swap", point_id=rec.pid,
                        content_hash=row["content_hash"], canonical_id=row["contract_id"],
                        canonical_version_number=row["version_number"])
            return info
        info.update(action="CONTRACT_SUPERSEDE:old_removed", qdrant_operation="delete")
        return info

    raise ValueError("unknown event_type %r" % (et,))


async def heartbeat(engine, event_id, worker_id, lease_token, lease_seconds=30):
    """Extend the outbox lease during a long index/rebuild operation."""
    await heartbeat_outbox(engine, event_id, worker_id, lease_token, lease_seconds)


async def run_once(engine, index, embedder, worker_id, lease_seconds=30):
    ev = await claim_outbox_event(engine, worker_id, lease_seconds=lease_seconds)
    if ev is None:
        return None
    try:
        payload = await load_outbox_payload(engine, ev["org_id"], ev["id"])
        info = await process_event(engine, index, embedder, ev, payload)
    except Exception as e:                               # index/store failure -> replayable, never lost
        status = await mark_retry(engine, ev["id"], worker_id, ev["lease_token"], str(e), backoff_seconds=0)
        try:
            await emit_index_audit(engine, ev["org_id"], result=(status or "RETRY"), outbox_event_id=ev["id"],
                                   worker_id=worker_id, lease_token=ev["lease_token"],
                                   object_kind=("contract_version" if ev["event_type"].startswith("CONTRACT")
                                                else "private_episode"),
                                   canonical_version_id=ev["aggregate_id"], qdrant_operation="failed",
                                   detail={"error": redact(str(e))})
        except Exception:
            pass
        return {"event_id": ev["id"], "event_type": ev["event_type"], "status": status or "RETRY",
                "error": redact(str(e))}
    await mark_processed(engine, ev["id"], worker_id, ev["lease_token"])
    await emit_index_audit(engine, ev["org_id"], result=info["action"], outbox_event_id=ev["id"],
                           worker_id=worker_id, lease_token=ev["lease_token"], object_kind=info.get("object_kind"),
                           canonical_id=info.get("canonical_id"), canonical_version_id=info.get("canonical_version_id"),
                           canonical_version_number=info.get("canonical_version_number"),
                           content_hash=info.get("content_hash"), qdrant_operation=info.get("qdrant_operation"),
                           point_id=info.get("point_id"), collection=info.get("collection"))
    return {"event_id": ev["id"], "event_type": ev["event_type"], "status": "PROCESSED", "action": info["action"]}


async def drain(engine, index, embedder, worker_id, max_events=100, lease_seconds=30):
    out = []
    for _ in range(max_events):
        r = await run_once(engine, index, embedder, worker_id, lease_seconds=lease_seconds)
        if r is None:
            break
        out.append(r)
    return out
