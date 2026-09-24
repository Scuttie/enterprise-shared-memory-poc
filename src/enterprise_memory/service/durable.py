"""Durable Postgres persistence for the P5 API + worker (RLS-scoped). Everything a caller sees is
authoritative PostgreSQL state; identity/permissions/patch/test-results are never taken from request input."""
from __future__ import annotations
import hashlib
import json
import uuid
from sqlalchemy import text
from ..persistence.tenant_context import tenant_tx

# deterministic namespace: one job -> one private episode id, so a reclaimed attempt / retry is idempotent
_JOB_NS = uuid.UUID("2f1e6a4c-5b3d-4e2a-9c8b-7a6d5e4f3c2b")

# required AVAILABLE artifacts before a job may enter SUCCEEDED (snapshot, sanitized model req + resp,
# parsed patch, applied patch, sandbox result)
REQUIRED_ARTIFACTS = 5


class TerminalEvidenceMissing(Exception):
    """A required evidence row (model call / artifacts / retrieval event) is absent at finalisation. The
    terminal transaction rolls back and the job does NOT enter SUCCEEDED."""


def sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def episode_id_for_job(job_id: str) -> str:
    return str(uuid.uuid5(_JOB_NS, "episode:%s" % job_id))


async def persist_private_episode_candidate(
    connection,
    *,
    org_id,
    user_id,
    repo_id,
    job_id,
    episode_canonical,
) -> tuple[str, str]:
    """Append the live-v0.3 private episode and candidate event atomically.

    ``connection`` must be an already-open tenant transaction.  Keeping this
    helper connection-level is intentional: callers cannot accidentally commit
    the episode separately from its ``CONTRACT_CANDIDATE`` outbox event.
    """
    from ..persistence.postgres import publish_outbox

    episode_id = episode_id_for_job(str(job_id))
    content_hash = "sha256:" + sha(
        json.dumps(episode_canonical, sort_keys=True)
    )[:32]
    await connection.execute(text(
        "INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,canonical_json,content_hash,"
        "state) VALUES(cast(:i as uuid),:o,:u,:r,cast(:j as jsonb),:h,'success') "
        "ON CONFLICT (id) DO NOTHING"),
        {"i": episode_id, "o": org_id, "u": user_id, "r": repo_id,
         "j": json.dumps(episode_canonical), "h": content_hash})
    await publish_outbox(
        connection,
        org_id,
        "CONTRACT_CANDIDATE",
        "private_episode",
        episode_id,
        1,
        {"job_id": str(job_id)},
    )
    return episode_id, content_hash


# ---------------------------------------------------------------- submission (API, api_service role)
async def create_solve_job(engine, *, org_id, user_id, repo_id, task_policy_id, task_policy_version,
                           installation_id, requested_ref, commit_sha, tree_sha, instruction,
                           idempotency_key, backend_type, spec, experiment_id=None, experiment_arm=None) -> tuple:
    ihash = sha(instruction)
    async with tenant_tx(engine, org_id, user_id) as c:
        row = (await c.execute(text(
            "INSERT INTO solve_jobs(org_id,submitter_user_id,repository_id,task_policy_id,logical_request_id,"
            "idempotency_key,spec_json,installation_id,requested_ref,resolved_commit_sha,resolved_tree_sha,"
            "task_policy_version,instruction_hash,identity_snapshot,backend_type,experiment_id,experiment_arm)"
            " VALUES(:o,:u,:r,:tp,:lrq,:k,cast(:s as jsonb),:inst,:ref,:cs,:ts,:tpv,:ih,cast(:idn as jsonb),"
            ":bt,:eid,:earm) ON CONFLICT (org_id,idempotency_key) DO UPDATE SET updated_at=now()"
            " RETURNING id,(xmax=0) AS created"),
            {"o": org_id, "u": user_id, "r": repo_id, "tp": task_policy_id, "lrq": idempotency_key,
             "k": idempotency_key, "s": json.dumps(spec), "inst": installation_id, "ref": requested_ref,
             "cs": commit_sha, "ts": tree_sha, "tpv": task_policy_version, "ih": ihash,
             "idn": json.dumps({"sub": str(user_id), "org": str(org_id)}), "bt": backend_type,
             "eid": experiment_id, "earm": experiment_arm})).first()
        jid, created = str(row[0]), bool(row[1])
        if created:
            await _event(c, org_id, jid, 0, "QUEUED", "submitted", {"ref": requested_ref, "commit": commit_sha})
    return jid, created


async def _event(conn, org_id, job_id, seq, state, event_type, detail):
    await conn.execute(text(
        "INSERT INTO job_events(org_id,job_id,seq,state,event_type,detail_json)"
        " VALUES(:o,:j,:seq,:st,:et,cast(:d as jsonb)) ON CONFLICT (job_id,seq) DO NOTHING"),
        {"o": org_id, "j": job_id, "seq": seq, "st": state, "et": event_type, "d": json.dumps(detail or {})})


async def add_event(engine, org_id, job_id, seq, state, event_type, detail=None):
    async with tenant_tx(engine, org_id) as c:
        await _event(c, org_id, job_id, seq, state, event_type, detail)


# ---------------------------------------------------------------- reads (API)
async def get_job(engine, org_id, job_id):
    async with tenant_tx(engine, org_id) as c:
        r = (await c.execute(text(
            "SELECT id,state,submitter_user_id,repository_id,resolved_commit_sha,resolved_tree_sha,"
            "backend_type,cross_user_private_injection_count,created_at,updated_at FROM solve_jobs"
            " WHERE id=:i"), {"i": job_id})).first()
    if r is None:
        return None
    return {"job_id": str(r[0]), "state": r[1], "submitter": str(r[2]), "repository_id": str(r[3]),
            "commit_sha": r[4], "tree_sha": r[5], "backend_type": r[6],
            "cross_user_private_injection_count": r[7],
            "created_at": (r[8].isoformat() if r[8] else None),
            "updated_at": (r[9].isoformat() if r[9] else None)}


async def list_events(engine, org_id, job_id):
    async with tenant_tx(engine, org_id) as c:
        rows = (await c.execute(text("SELECT seq,state,event_type,detail_json,created_at FROM job_events"
                                     " WHERE job_id=:j ORDER BY seq"), {"j": job_id})).fetchall()
    return [{"seq": r[0], "state": r[1], "event_type": r[2],
             "detail": (r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}")),
             "created_at": (r[4].isoformat() if r[4] else None)} for r in rows]


async def request_cancel(engine, org_id, job_id) -> bool:
    async with tenant_tx(engine, org_id) as c:
        n = (await c.execute(text(
            "UPDATE solve_jobs SET cancel_requested_at=now() WHERE id=:i"
            " AND state <> ALL(ARRAY['SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'])"),
            {"i": job_id})).rowcount
    return n == 1


# ---------------------------------------------------------------- worker persistence (worker_service role)
async def persist_model_call(engine, org_id, job_id, record: dict):
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text(
            "INSERT INTO model_calls(org_id,job_id,logical_request_id,backend_type,requested_model,"
            "returned_model,attempts,input_tokens,output_tokens,total_tokens,total_latency,final_status,"
            "redaction_status,detail_json) VALUES(:o,:j,:lrq,:bt,:rm,:rtm,:att,:it,:ot,:tt,:lat,:fs,:rs,"
            "cast(:d as jsonb))"),
            {"o": org_id, "j": job_id, "lrq": record.get("logical_request_id"),
             "bt": record.get("backend_type", "fake"), "rm": record.get("requested_model"),
             "rtm": record.get("returned_model"), "att": int(record.get("attempts", 1)),
             "it": record.get("input_tokens"), "ot": record.get("output_tokens"),
             "tt": record.get("total_tokens"), "lat": record.get("total_latency"),
             "fs": record.get("final_status", "success"), "rs": record.get("redaction_status", "clean"),
             "d": json.dumps({k: record.get(k) for k in ("prompt_hash", "response_hash")})})


async def persist_retrieval_candidate(engine, org_id, job_id, *, scope, canonical_id, canonical_version_id,
                                      content_hash, private_owner_id, accepted, rejection_reason, injected,
                                      index_owner_id=None, canonical_owner_id=None, injected_view_hash=None,
                                      injected_position=None):
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text(
            "INSERT INTO retrieval_candidates(org_id,job_id,scope,canonical_id,canonical_version_id,"
            "content_hash,private_owner_id,accepted,rejection_reason,injected,index_owner_id,"
            "canonical_owner_id,injected_view_hash,injected_position) VALUES(:o,:j,:sc,:ci,:cv,:h,"
            "cast(:po as uuid),:acc,:rr,:inj,cast(:io as uuid),cast(:co as uuid),:ivh,:ipos)"),
            {"o": org_id, "j": job_id, "sc": scope, "ci": canonical_id, "cv": canonical_version_id,
             "h": content_hash, "po": private_owner_id, "acc": accepted, "rr": rejection_reason,
             "inj": injected, "io": index_owner_id, "co": canonical_owner_id, "ivh": injected_view_hash,
             "ipos": injected_position})


async def persist_patches(engine, org_id, job_id, *, raw_patch, applied_patch):
    """Durably record the raw model patch + the applied file for an experiment job (P5.2 G7 adoption audit)."""
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text(
            "INSERT INTO job_patches(org_id,job_id,raw_patch,applied_patch) VALUES(:o,:j,:rp,:ap)"
            " ON CONFLICT (org_id,job_id) DO NOTHING"),
            {"o": org_id, "j": job_id, "rp": (raw_patch or "")[:20000], "ap": (applied_patch or "")[:20000]})


async def persist_outcome(engine, org_id, job_id, *, pass1, exec1, pass2, injected, content_hash):
    async with tenant_tx(engine, org_id) as c:
        await c.execute(text(
            "INSERT INTO outcome_observations(org_id,job_id,pass1,exec1,pass2,injected_memories,content_hash)"
            " VALUES(:o,:j,:p1,:e1,:p2,cast(:im as jsonb),:h)"),
            {"o": org_id, "j": job_id, "p1": pass1, "e1": exec1, "p2": pass2,
             "im": json.dumps(injected), "h": content_hash})


async def persist_private_episode(engine, org_id, user_id, repo_id, canonical: dict) -> str:
    h = "sha256:" + sha(json.dumps(canonical, sort_keys=True))[:32]
    eid = str(uuid.uuid4())
    async with tenant_tx(engine, org_id, user_id) as c:
        await c.execute(text(
            "INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,canonical_json,content_hash,"
            "state) VALUES(:i,:o,:u,:r,cast(:j as jsonb),:h,'success')"),
            {"i": eid, "o": org_id, "u": user_id, "r": repo_id, "j": json.dumps(canonical), "h": h})
    return eid


async def finalize_success(engine, org_id, job_id, worker_id, cross_user_count, seq):
    """Terminal transition enforcing lease ownership; sets the computed injection count; records the event."""
    async with tenant_tx(engine, org_id) as c:
        n = (await c.execute(text(
            "UPDATE solve_jobs SET state='SUCCEEDED', updated_at=now(), lease_owner=NULL,"
            " lease_expires_at=NULL, heartbeat_at=NULL, cross_user_private_injection_count=:x"
            " WHERE id=:i AND lease_owner=:w AND state <> ALL(ARRAY['SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'])"),
            {"x": cross_user_count, "i": job_id, "w": worker_id})).rowcount
        if n != 1:
            raise PermissionError("not_lease_owner_or_terminal")
        await _event(c, org_id, job_id, seq, "SUCCEEDED", "completed",
                     {"cross_user_private_injection_count": cross_user_count})


async def mark_failed(engine, org_id, job_id, worker_id, reason, seq):
    """Guarded FAILED transition. A stale worker (no longer the lease owner) writes NOTHING — not even the
    FAILED job_event — so it cannot append a terminal event to a job it no longer owns."""
    from ..persistence.postgres import redact
    async with tenant_tx(engine, org_id) as c:
        n = (await c.execute(text(
            "UPDATE solve_jobs SET state='FAILED', updated_at=now(), lease_owner=NULL, lease_expires_at=NULL,"
            " error_detail_sanitized=:d WHERE id=:i AND lease_owner=:w AND state <> ALL(ARRAY['SUCCEEDED',"
            "'FAILED','CANCELLED','DEAD_LETTER'])"), {"d": redact(reason), "i": job_id, "w": worker_id})).rowcount
        if n == 1:                                          # only the true lease owner appends the terminal event
            await _event(c, org_id, job_id, seq, "FAILED", "failed", {"reason": redact(reason)})
    return n == 1


async def mark_cancelled(engine, org_id, job_id, worker_id, seq):
    """Guarded CANCELLED transition (used when a cancel was requested and this worker still owns the lease)."""
    async with tenant_tx(engine, org_id) as c:
        n = (await c.execute(text(
            "UPDATE solve_jobs SET state='CANCELLED', updated_at=now(), lease_owner=NULL, lease_expires_at=NULL,"
            " heartbeat_at=NULL WHERE id=:i AND lease_owner=:w AND state <> ALL(ARRAY['SUCCEEDED','FAILED',"
            "'CANCELLED','DEAD_LETTER'])"), {"i": job_id, "w": worker_id})).rowcount
        if n == 1:
            await _event(c, org_id, job_id, seq, "CANCELLED", "cancelled", {})
    return n == 1


async def finalize_success_atomic(engine, org_id, job_id, worker_id, *, cross_user_count, seq, outcome,
                                  episode_canonical, user_id, repo_id):
    """One authoritative terminal transaction (P5.1 §4.3). In a single tenant transaction: take the terminal
    transition ONLY if this worker still owns the live lease (single winner), verify the required durable
    evidence exists (fail-closed rollback otherwise), then write the terminal OutcomeObservation (one per job),
    the single deterministic PrivateEpisode, the single candidate-extraction outbox event, the terminal audit,
    the computed leakage count and the SUCCEEDED transition + event — together. Object-store bytes were already
    persisted through the artifact state machine; here we only verify they are AVAILABLE.

    Idempotent by job: the outcome has a UNIQUE(org_id,job_id); the episode id is deterministic per job (ON
    CONFLICT DO NOTHING); the candidate outbox event is idempotent by its unique key. Returns the episode id."""
    from ..persistence.postgres import emit_audit
    ep_id = episode_id_for_job(job_id)
    async with tenant_tx(engine, org_id, user_id) as c:
        # 1 lease-owned terminal transition — exactly one worker wins; a stale worker gets rowcount 0
        n = (await c.execute(text(
            "UPDATE solve_jobs SET state='SUCCEEDED', updated_at=now(), lease_owner=NULL, lease_expires_at=NULL,"
            " heartbeat_at=NULL, cross_user_private_injection_count=:x WHERE id=:i AND lease_owner=:w"
            " AND state <> ALL(ARRAY['SUCCEEDED','FAILED','CANCELLED','DEAD_LETTER'])"),
            {"x": cross_user_count, "i": job_id, "w": worker_id})).rowcount
        if n != 1:
            raise PermissionError("not_lease_owner_or_terminal")
        # 2 required-evidence gate (fail-closed: rollback -> job does NOT become SUCCEEDED)
        mc = (await c.execute(text("SELECT count(*) FROM model_calls WHERE job_id=:j"), {"j": job_id})).scalar()
        art = (await c.execute(text("SELECT count(*) FROM artifacts WHERE job_id=:j"
                                    " AND deletion_state='AVAILABLE'"), {"j": job_id})).scalar()
        retrieved = (await c.execute(text("SELECT count(*) FROM job_events WHERE job_id=:j"
                                          " AND event_type='retrieved'"), {"j": job_id})).scalar()
        att = (await c.execute(text("SELECT count(*) FROM solve_attempts WHERE job_id=:j"), {"j": job_id})).scalar()
        if int(mc or 0) < 1 or int(art or 0) < REQUIRED_ARTIFACTS or int(retrieved or 0) < 1 or int(att or 0) < 1:
            raise TerminalEvidenceMissing("evidence: model_calls=%s artifacts=%s retrieved=%s attempts=%s"
                                          % (mc, art, retrieved, att))
        # 3 terminal outcome (one per job)
        await c.execute(text(
            "INSERT INTO outcome_observations(org_id,job_id,pass1,exec1,pass2,injected_memories,content_hash)"
            " VALUES(:o,:j,:p1,:e1,:p2,cast(:im as jsonb),:h) ON CONFLICT (org_id,job_id) DO NOTHING"),
            {"o": org_id, "j": job_id, "p1": outcome["pass1"], "e1": outcome["exec1"], "p2": outcome["pass2"],
             "im": json.dumps(outcome.get("injected", [])), "h": outcome.get("content_hash")})
        # 4 + 5 one connection-level private-episode/candidate append.  The
        # surrounding tenant transaction is the sole commit boundary.
        appended_id, _ = await persist_private_episode_candidate(
            c,
            org_id=org_id,
            user_id=user_id,
            repo_id=repo_id,
            job_id=job_id,
            episode_canonical=episode_canonical,
        )
        if appended_id != ep_id:
            raise RuntimeError("private episode identity changed during finalisation")
        # 6 terminal audit + 7 terminal job_event
        await emit_audit(c, org_id, "solve_succeeded", "job", job_id,
                         {"episode_id": ep_id, "cross_user_private_injection_count": cross_user_count},
                         "", sha("%s|succeeded" % job_id))
        await _event(c, org_id, job_id, seq, "SUCCEEDED", "completed",
                     {"cross_user_private_injection_count": cross_user_count, "episode_id": ep_id})
    return ep_id
