"""Async PostgreSQL adapter functions (P1/P1.1/P2-0). RLS + transaction-local context isolate tenants;
the worker claims jobs through the hardened SECURITY DEFINER claim_next_job (owned by a dedicated NOLOGIN
NOSUPERUSER BYPASSRLS role). Outbox completion/retry enforce lease ownership. Persisted error details are
redacted deterministically (never raw exception strings)."""
from __future__ import annotations
import json
import re
from sqlalchemy import text
from ..tenant_context import tenant_tx

_TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED", "DEAD_LETTER")
_ALLOWED = {"QUEUED": {"RETRIEVING", "CANCELLED"}, "RETRIEVING": {"GENERATING", "FAILED", "QUEUED", "CANCELLED"},
            "GENERATING": {"TESTING", "FAILED", "QUEUED", "CANCELLED"},
            "TESTING": {"REPAIRING", "SUCCEEDED", "FAILED", "QUEUED", "CANCELLED"},
            "REPAIRING": {"TESTING", "SUCCEEDED", "FAILED", "CANCELLED"},
            "SUCCEEDED": set(), "FAILED": {"QUEUED", "DEAD_LETTER"}, "CANCELLED": set(), "DEAD_LETTER": set()}

_SECRET_RE = re.compile(r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}"
                        r"|-----BEGIN[ A-Z]+PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
                        r"|[A-Za-z0-9+/]{40,})")


def redact(error) -> str:
    """Deterministic redactor: replace secret-shaped substrings, cap length. Never store raw exceptions."""
    s = _SECRET_RE.sub("[REDACTED]", str(error))
    return s[:200]


async def create_job(engine, org_id, user_id, repo_id, spec, idempotency_key, logical_request_id):
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
        row = (await c.execute(text("SELECT job_id, org_id, submitter_user_id, task_policy_id, spec_json, attempt_number"
                                    " FROM claim_next_job(:w,:l)"), {"w": worker_id, "l": lease_seconds})).first()
        return None if row is None else {"job_id": str(row[0]), "org_id": str(row[1]),
                                         "submitter": (str(row[2]) if row[2] else None), "attempt": row[5]}


async def heartbeat(engine, org_id, job_id, worker_id, lease_seconds=30):
    if not (1 <= lease_seconds <= 3600):                 # §2.5 same lease bounds as initial claim
        raise ValueError("lease seconds out of bounds")
    async with tenant_tx(engine, org_id) as c:
        r = await c.execute(text("UPDATE solve_jobs SET heartbeat_at=now(),"
                                 " lease_expires_at=now()+make_interval(secs=>:l)"
                                 " WHERE id=:j AND lease_owner=:w AND state <> ALL(:term) AND lease_expires_at IS NOT NULL AND lease_expires_at > now()"),
                            {"l": lease_seconds, "j": job_id, "w": worker_id, "term": list(_TERMINAL)})
        if r.rowcount != 1:
            raise PermissionError("not_lease_owner_or_terminal")


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
        term = to_state in _TERMINAL
        await c.execute(text("UPDATE solve_jobs SET state=:s, updated_at=now(), error_detail_sanitized=:d,"
                             " lease_owner = CASE WHEN :t THEN NULL ELSE lease_owner END,"
                             " lease_expires_at = CASE WHEN :t THEN NULL ELSE lease_expires_at END,"
                             " heartbeat_at = CASE WHEN :t THEN NULL ELSE heartbeat_at END WHERE id=:j"),
                        {"s": to_state, "d": (redact(detail) if detail else None), "t": term, "j": job_id})
        return to_state


async def request_cancel(engine, org_id, job_id):
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text("UPDATE solve_jobs SET cancel_requested_at=now() WHERE id=:j"), {"j": job_id})


async def list_job_events(engine, org_id, job_id):
    async with tenant_tx(engine, org_id) as c:
        rows = (await c.execute(text("SELECT attempt_number, state FROM solve_attempts WHERE job_id=:j ORDER BY attempt_number"),
                                {"j": job_id})).fetchall()
        return [{"attempt": r[0], "state": r[1]} for r in rows]


# ---------------------------------------------------------------- outbox (lease-owner enforced)
async def publish_outbox(conn, org_id, event_type, aggregate_type, aggregate_id, aggregate_version, payload):
    await conn.execute(text(
        "INSERT INTO outbox_events(org_id,event_type,aggregate_type,aggregate_id,aggregate_version,payload_json)"
        " VALUES(:o,:t,:a,:i,:v,cast(:p as jsonb)) ON CONFLICT (event_type,aggregate_type,aggregate_id,aggregate_version) DO NOTHING"),
        {"o": org_id, "t": event_type, "a": aggregate_type, "i": aggregate_id, "v": aggregate_version, "p": json.dumps(payload)})


async def claim_outbox_event(engine, worker_id, lease_seconds=30):
    """Cross-tenant claim via the SECURITY DEFINER dispatcher (index_worker_service only). Returns a fresh
    lease_token that must be presented to complete/retry."""
    async with engine.begin() as c:
        row = (await c.execute(text("SELECT event_id, org_id, event_type, aggregate_type, aggregate_id,"
                                    " aggregate_version, lease_token, lease_expires_at FROM claim_next_outbox_event(:w,:l)"),
                               {"w": worker_id, "l": lease_seconds})).first()
        return None if row is None else {"id": str(row[0]), "org_id": str(row[1]), "event_type": row[2],
                                         "aggregate_id": str(row[4]), "aggregate_version": row[5],
                                         "lease_token": str(row[6])}


async def mark_processed(engine, event_id, worker_id, lease_token):
    async with engine.begin() as c:
        try:
            await c.execute(text("SELECT complete_outbox_event(:e,:w,cast(:t as uuid))"),
                            {"e": event_id, "w": worker_id, "t": lease_token})
        except Exception as ex:
            if "invalid or expired lease" in str(ex):
                raise PermissionError("invalid_or_expired_lease")
            raise


async def mark_retry(engine, event_id, worker_id, lease_token, error, backoff_seconds=2):
    async with engine.begin() as c:
        try:
            return (await c.execute(text("SELECT retry_outbox_event(:e,:w,cast(:t as uuid),:err,:b)"),
                                    {"e": event_id, "w": worker_id, "t": lease_token, "err": redact(error), "b": backoff_seconds})).scalar()
        except Exception as ex:
            if "invalid or expired lease" in str(ex):
                raise PermissionError("invalid_or_expired_lease")
            raise


async def heartbeat_outbox(engine, event_id, worker_id, lease_token, lease_seconds=30):
    """Extend a live outbox lease held by this worker+token (for long rebuild/index operations)."""
    async with engine.begin() as c:
        try:
            await c.execute(text("SELECT heartbeat_outbox_event(:e,:w,cast(:t as uuid),:l)"),
                            {"e": event_id, "w": worker_id, "t": lease_token, "l": lease_seconds})
        except Exception as ex:
            if "invalid or expired lease" in str(ex):
                raise PermissionError("invalid_or_expired_lease")
            raise


async def emit_index_audit(engine, org_id, *, result, outbox_event_id=None, worker_id=None, lease_token=None,
                           object_kind=None, canonical_id=None, canonical_version_id=None,
                           canonical_version_number=None, content_hash=None, qdrant_operation=None,
                           point_id=None, collection=None, detail=None):
    """Append-only audit of one index operation (org-scoped, RLS-enforced)."""
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text(
            "INSERT INTO index_audit_events(org_id,outbox_event_id,worker_id,lease_token,object_kind,"
            "canonical_id,canonical_version_id,canonical_version_number,content_hash,qdrant_operation,"
            "point_id,collection,result,detail_json) VALUES(:o,cast(:e as uuid),:w,cast(:t as uuid),:k,"
            "cast(:ci as uuid),cast(:cv as uuid),:cn,:h,:op,:pid,:col,:res,cast(:d as jsonb))"),
            {"o": org_id, "e": outbox_event_id, "w": worker_id, "t": lease_token, "k": object_kind,
             "ci": canonical_id, "cv": canonical_version_id, "cn": canonical_version_number,
             "h": content_hash, "op": qdrant_operation, "pid": point_id, "col": collection,
             "res": result, "d": json.dumps(detail or {})})


async def emit_audit(conn, org_id, event_type, subject_type, subject_id, detail, prev_hash, event_hash):
    await conn.execute(text(
        "INSERT INTO audit_events(org_id,event_type,subject_type,subject_id,detail_json,previous_hash,event_hash)"
        " VALUES(:o,:t,:st,:si,cast(:d as jsonb),:p,:h)"),
        {"o": org_id, "t": event_type, "st": subject_type, "si": subject_id, "d": json.dumps(detail), "p": prev_hash, "h": event_hash})
