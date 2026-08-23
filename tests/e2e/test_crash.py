"""Worker crash-recovery E2E (P5 §12). A durable job whose worker A 'crashed' (expired lease) is reclaimed
by an independent worker (the running background worker B) and completed exactly once — real PostgreSQL lease
recovery, not an in-memory state machine."""
import json
import uuid
import pytest
from sqlalchemy import text
from conftest import run, su, poll_job
from enterprise_memory.persistence.database import make_engine
from enterprise_memory.service.p5deps import OfflineRepositoryProvider
from enterprise_memory.service import durable as D


async def _plant_crashed_job(s):
    """Insert a job already in RETRIEVING with an EXPIRED lease held by 'wA' (a crashed worker) + attempt 1."""
    org, user, repo = s["org"], s["user"], s["repo"]
    rp = OfflineRepositoryProvider()
    commit = rp.resolve_commit(repo, "refs/heads/main")
    tree = rp.resolve_tree(commit)
    spec = {"repository_id": repo, "task_id": "fix-return", "instruction": "make f return 1",
            "desired_ref": "refs/heads/main", "commit_sha": commit, "tree_sha": tree,
            "target_path": "src/app.py", "editable_paths": ["src/**"], "target_symbol": "f",
            "exact_signature": "def f()", "maximum_changed_lines": 12}
    jid = str(uuid.uuid4())
    e = su()
    async with e.begin() as c:
        await c.execute(text(
            "INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,"
            "idempotency_key,state,spec_json,attempts,max_attempts,lease_owner,lease_expires_at,heartbeat_at,"
            "requested_ref,resolved_commit_sha,resolved_tree_sha,backend_type,identity_snapshot) VALUES"
            "(:i,:o,:u,:r,:lrq,:k,'RETRIEVING',cast(:s as jsonb),1,3,'wA',now()-interval '1 hour',"
            "now()-interval '1 hour',:ref,:cs,:ts,'fake',cast(:idn as jsonb))"),
            {"i": jid, "o": org, "u": user, "r": repo, "lrq": "crash-%s" % jid, "k": "crash-%s" % jid,
             "s": json.dumps(spec), "ref": "refs/heads/main", "cs": commit, "ts": tree,
             "idn": json.dumps({"sub": user, "org": org})})
        await c.execute(text("INSERT INTO solve_attempts(org_id,job_id,attempt_number,worker_id,state)"
                             " VALUES(:o,:j,1,'wA','RETRIEVING')"), {"o": org, "j": jid})
    await e.dispose()
    return jid


async def _attempts(job_id):
    e = su()
    async with e.connect() as c:
        n = (await c.execute(text("SELECT count(*) FROM solve_attempts WHERE job_id=:j"), {"j": job_id})).scalar()
        st = (await c.execute(text("SELECT state FROM solve_jobs WHERE id=:i"), {"i": job_id})).scalar()
        cand = (await c.execute(text("SELECT count(*) FROM outbox_events WHERE event_type='CONTRACT_CANDIDATE'"
                                     " AND payload_json->>'job_id'=:j"), {"j": job_id})).scalar()
    await e.dispose()
    return n, st, cand


def test_crash_recovery(seed, keyring, client):
    s = seed()
    job_id = run(_plant_crashed_job(s))
    token = keyring(s["user"], s["org"], ["solve:read"])

    final = poll_job(client, token, job_id)               # background worker B reclaims + completes
    assert final["state"] == "SUCCEEDED", final

    n, st, cand = run(_attempts(job_id))
    assert st == "SUCCEEDED"
    assert n == 2                                         # attempt 1 (crashed wA) + attempt 2 (worker B)
    assert cand == 1                                      # exactly one candidate-extraction event

    # the crashed worker A cannot finalize afterward (lease no longer his)
    we = make_engine("worker_service", "worker_pw")
    with pytest.raises(PermissionError):
        run(D.finalize_success(we, s["org"], job_id, "wA", 0, 99))
    run(we.dispose())
