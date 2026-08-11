"""Async PostgreSQL adapter functions (P1). Tenant isolation is enforced by RLS + transaction-local
context; the worker claims jobs through the SECURITY DEFINER claim_next_job function (§12)."""
from __future__ import annotations
import json
from sqlalchemy import text
from ..tenant_context import tenant_tx


async def create_job(engine, org_id, user_id, repo_id, spec: dict, idempotency_key: str, logical_request_id: str):
    """Idempotent create: duplicate (org, idempotency_key) returns the existing job. Returns (job_id, created)."""
    async with tenant_tx(engine, org_id, user_id) as c:
        row = (await c.execute(text(
            "INSERT INTO solve_jobs(org_id,submitter_user_id,repository_id,logical_request_id,idempotency_key,spec_json)"
            " VALUES(:o,:u,:r,:l,:k,cast(:s as jsonb)) ON CONFLICT (org_id,idempotency_key) DO NOTHING RETURNING id"),
            {"o": org_id, "u": user_id, "r": repo_id, "l": logical_request_id, "k": idempotency_key, "s": json.dumps(spec)})).first()
        if row is not None:
            return str(row[0]), True
        existing = (await c.execute(text("SELECT id FROM solve_jobs WHERE org_id=:o AND idempotency_key=:k"),
                                    {"o": org_id, "k": idempotency_key})).scalar()
        return str(existing), False


async def claim_job(engine, worker_id: str, lease_seconds: int = 30):
    """Worker claims one job via the SECURITY DEFINER function (cross-tenant-safe entry point)."""
    async with engine.begin() as c:
        row = (await c.execute(text("SELECT job_id, org_id, task_policy_id, attempt_number FROM claim_next_job(:w,:l)"),
                               {"w": worker_id, "l": lease_seconds})).first()
        return None if row is None else {"job_id": str(row[0]), "org_id": str(row[1]), "attempt": row[3]}


async def publish_outbox(conn, org_id, event_type, aggregate_type, aggregate_id, aggregate_version, payload: dict):
    """Publish in the SAME transaction as the canonical change (conn is an open tenant transaction)."""
    await conn.execute(text(
        "INSERT INTO outbox_events(org_id,event_type,aggregate_type,aggregate_id,aggregate_version,payload_json)"
        " VALUES(:o,:t,:a,:i,:v,cast(:p as jsonb)) ON CONFLICT (event_type,aggregate_type,aggregate_id,aggregate_version) DO NOTHING"),
        {"o": org_id, "t": event_type, "a": aggregate_type, "i": aggregate_id, "v": aggregate_version, "p": json.dumps(payload)})


async def emit_audit(conn, org_id, event_type, subject_type, subject_id, detail: dict, prev_hash, event_hash):
    await conn.execute(text(
        "INSERT INTO audit_events(org_id,event_type,subject_type,subject_id,detail_json,previous_hash,event_hash)"
        " VALUES(:o,:t,:st,:si,cast(:d as jsonb),:p,:h)"),
        {"o": org_id, "t": event_type, "st": subject_type, "si": subject_id, "d": json.dumps(detail), "p": prev_hash, "h": event_hash})
