"""Async PostgreSQL adapter functions (P1/P1.1). RLS + transaction-local context isolate tenants; the
worker claims jobs through the SECURITY DEFINER claim_next_job (owned by a dedicated NOLOGIN BYPASSRLS
role). create_job upserts so concurrent same-key submissions all return the one job id."""
from __future__ import annotations
import json
from sqlalchemy import text
from ..tenant_context import tenant_tx

_ALLOWED = {"QUEUED": {"RETRIEVING", "CANCELLED"}, "RETRIEVING": {"GENERATING", "FAILED", "QUEUED", "CANCELLED"},
            "GENERATING": {"TESTING", "FAILED", "QUEUED", "CANCELLED"},
            "TESTING": {"REPAIRING", "SUCCEEDED", "FAILED", "QUEUED", "CANCELLED"},
            "REPAIRING": {"TESTING", "SUCCEEDED", "FAILED", "CANCELLED"},
            "SUCCEEDED": set(), "FAILED": {"QUEUED", "DEAD_LETTER"}, "CANCELLED": set(), "DEAD_LETTER": set()}


async def create_job(engine, org_id, user_id, repo_id, spec, idempotency_key, logical_request_id):
    """Idempotent create (concurrency-safe upsert): duplicate (org, key) returns the SAME job -> (job_id, created)."""
    async with tenant_tx(engine, org_id, user_id) as c:
        row = (await c.execute(text(
            "INSERT INTO solve_jobs(org_id,submitter_user_id,repository_id,logical_request_id,idempotency_key,spec_json)"
            " VALUES(:o,:u,:r,:l,:k,cast(:s as jsonb))"
            " ON CONFLICT (org_id,idempotency_key) DO UPDATE SET updated_at = now()"
            " RETURNING id, (xmax = 0) AS created"),
            {"o": org_id, "u": user_id, "r": repo_id, "l": logical_request_id, "k": idempotency_key, "s": json.dumps(spec)})).first()
        return str(row[0]), bool(row[1])


async def claim_job(engine, worker_id, lease_seconds=30):
    async with engine.begin() as c:
        row = (await c.execute(text("SELECT job_id, org_id, task_policy_id, attempt_number FROM claim_next_job(:w,:l)"),
                               {"w": worker_id, "l": lease_seconds})).first()
        return None if row is None else {"job_id": str(row[0]), "org_id": str(row[1]), "attempt": row[3]}


async def heartbeat(engine, org_id, job_id, worker_id, lease_seconds=30):
    async with tenant_tx(engine, org_id) as c:
        r = await c.execute(text("UPDATE solve_jobs SET heartbeat_at=now(),"
                                 " lease_expires_at=now()+make_interval(secs=>:l) WHERE id=:j AND lease_owner=:w"),
                            {"l": lease_seconds, "j": job_id, "w": worker_id})
        if r.rowcount != 1:
            raise PermissionError("not_lease_owner")


async def transition(engine, org_id, job_id, worker_id, to_state, detail=None):
    async with tenant_tx(engine, org_id) as c:
        cur = (await c.execute(text("SELECT state, lease_owner, attempts, max_attempts FROM solve_jobs WHERE id=:j FOR UPDATE"),
                               {"j": job_id})).first()
        if cur is None:
            raise KeyError(job_id)
        state, owner, attempts, maxa = cur
        if owner != worker_id:
            raise PermissionError("not_lease_owner")
        if to_state == "FAILED" and attempts >= maxa:
            to_state = "DEAD_LETTER"
        if to_state not in _ALLOWED.get(state, set()):
            raise ValueError("illegal transition %s -> %s" % (state, to_state))
        await c.execute(text("UPDATE solve_jobs SET state=:s, updated_at=now(), error_detail_sanitized=:d WHERE id=:j"),
                        {"s": to_state, "d": (detail or None), "j": job_id})
        return to_state


async def request_cancel(engine, org_id, job_id):
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text("UPDATE solve_jobs SET cancel_requested_at=now() WHERE id=:j"), {"j": job_id})


async def list_job_events(engine, org_id, job_id):
    async with tenant_tx(engine, org_id) as c:
        rows = (await c.execute(text("SELECT attempt_number, state FROM solve_attempts WHERE job_id=:j ORDER BY attempt_number"),
                                {"j": job_id})).fetchall()
        return [{"attempt": r[0], "state": r[1]} for r in rows]


async def publish_outbox(conn, org_id, event_type, aggregate_type, aggregate_id, aggregate_version, payload):
    await conn.execute(text(
        "INSERT INTO outbox_events(org_id,event_type,aggregate_type,aggregate_id,aggregate_version,payload_json)"
        " VALUES(:o,:t,:a,:i,:v,cast(:p as jsonb)) ON CONFLICT (event_type,aggregate_type,aggregate_id,aggregate_version) DO NOTHING"),
        {"o": org_id, "t": event_type, "a": aggregate_type, "i": aggregate_id, "v": aggregate_version, "p": json.dumps(payload)})


async def claim_outbox_event(engine, org_id, worker_id, lease_seconds=30):
    async with tenant_tx(engine, org_id) as c:
        row = (await c.execute(text(
            "UPDATE outbox_events SET status='PROCESSING', lease_owner=:w,"
            " lease_expires_at=now()+make_interval(secs=>:l), attempts=attempts+1"
            " WHERE id = (SELECT id FROM outbox_events WHERE org_id=:o AND status IN ('PENDING','PROCESSING')"
            "   AND (lease_expires_at IS NULL OR lease_expires_at < now()) AND next_attempt_at<=now()"
            "   ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id, event_type, aggregate_id"),
            {"w": worker_id, "l": lease_seconds, "o": org_id})).first()
        return None if row is None else {"id": str(row[0]), "event_type": row[1], "aggregate_id": str(row[2])}


async def mark_processed(engine, org_id, event_id):
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text("UPDATE outbox_events SET status='PROCESSED', processed_at=now() WHERE id=:i"), {"i": event_id})


async def mark_retry(engine, org_id, event_id, error, backoff_seconds=2):
    async with tenant_tx(engine, org_id) as c:
        row = (await c.execute(text("SELECT attempts, max_attempts FROM outbox_events WHERE id=:i"), {"i": event_id})).first()
        if row and row[0] >= row[1]:
            await c.execute(text("UPDATE outbox_events SET status='QUARANTINED', error_detail_sanitized=:e WHERE id=:i"),
                            {"e": str(error)[:200], "i": event_id})
            return "QUARANTINED"
        await c.execute(text("UPDATE outbox_events SET status='PENDING', lease_owner=NULL, lease_expires_at=NULL,"
                             " next_attempt_at=now()+make_interval(secs=>:b), error_detail_sanitized=:e WHERE id=:i"),
                        {"b": backoff_seconds, "e": str(error)[:200], "i": event_id})
        return "PENDING"


async def emit_audit(conn, org_id, event_type, subject_type, subject_id, detail, prev_hash, event_hash):
    await conn.execute(text(
        "INSERT INTO audit_events(org_id,event_type,subject_type,subject_id,detail_json,previous_hash,event_hash)"
        " VALUES(:o,:t,:st,:si,cast(:d as jsonb),:p,:h)"),
        {"o": org_id, "t": event_type, "st": subject_type, "si": subject_id, "d": json.dumps(detail), "p": prev_hash, "h": event_hash})
