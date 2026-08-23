"""P5.1 §4.3 — atomic terminal finalisation + idempotent terminal evidence, against real PostgreSQL.
Proves: a stale worker writes no terminal state/event; finalisation is fail-closed on missing evidence; a
successful finalisation writes exactly one outcome/episode/candidate/audit bundle in one transaction; two
workers racing to finalise produce exactly one SUCCEEDED; a retry is idempotent."""
import asyncio
import pytest
from conftest import run, worker_engine, plant_job, seed_evidence, job_state
from enterprise_memory.service import durable as D
from enterprise_memory.service.durable import TerminalEvidenceMissing

OUTCOME = {"pass1": 1, "exec1": 1, "pass2": 1, "injected": [], "content_hash": "h0"}


def _episode(repo):
    return {"task_id": "fix-return", "repo_id": repo, "commit": "c0", "outcome": "success",
            "injected_memory_ids": []}


async def _finalize(worker, jid, org, user, repo, seq=6):
    we = worker_engine()
    try:
        return await D.finalize_success_atomic(we, org, jid, worker, cross_user_count=0, seq=seq,
                                               outcome=OUTCOME, episode_canonical=_episode(repo),
                                               user_id=user, repo_id=repo)
    finally:
        await we.dispose()


def test_stale_worker_mark_failed_writes_nothing(seed):
    s = seed()
    jid, _ = run(plant_job(s, worker="wB"))

    async def go():
        we = worker_engine()
        ok = await D.mark_failed(we, s["org"], jid, "wA", "boom", 9)   # wA is NOT the owner
        await we.dispose()
        return ok
    assert run(go()) is False
    st = run(job_state(jid))
    assert st["state"] == "RETRIEVING" and st["terminal_events"] == 0    # no terminal state, no terminal event


def test_mark_cancelled_guarded(seed):
    s = seed()
    jid, _ = run(plant_job(s, worker="wB"))

    async def wrong():
        we = worker_engine(); ok = await D.mark_cancelled(we, s["org"], jid, "wA", 9); await we.dispose(); return ok
    assert run(wrong()) is False
    assert run(job_state(jid))["state"] == "RETRIEVING"

    async def right():
        we = worker_engine(); ok = await D.mark_cancelled(we, s["org"], jid, "wB", 9); await we.dispose(); return ok
    assert run(right()) is True
    assert run(job_state(jid))["state"] == "CANCELLED"


def test_finalise_fail_closed_on_missing_evidence(seed):
    s = seed()
    jid, _ = run(plant_job(s, worker="wX"))          # no evidence seeded
    with pytest.raises(TerminalEvidenceMissing):
        run(_finalize("wX", jid, s["org"], s["user"], s["repo"]))
    st = run(job_state(jid))
    assert st["state"] == "RETRIEVING" and st["outcome"] == 0        # transaction rolled back


def test_finalise_happy_single_bundle(seed):
    s = seed()
    jid, _ = run(plant_job(s, worker="wX"))
    run(seed_evidence(jid, s["org"], s["user"]))
    ep = run(_finalize("wX", jid, s["org"], s["user"], s["repo"]))
    assert ep
    st = run(job_state(jid))
    assert st["state"] == "SUCCEEDED"
    assert st["outcome"] == 1 and st["episode"] == 1 and st["candidate"] == 1 and st["audit"] == 1


def test_finalise_stale_worker_permission_error(seed):
    s = seed()
    jid, _ = run(plant_job(s, worker="wX"))
    run(seed_evidence(jid, s["org"], s["user"]))
    with pytest.raises(PermissionError):
        run(_finalize("wY", jid, s["org"], s["user"], s["repo"]))   # wY not the owner
    assert run(job_state(jid))["state"] == "RETRIEVING"


def test_two_workers_race_one_wins(seed):
    # wB owns the (reclaimed) lease; wA is the worker that lost it. Both try to finalise concurrently.
    s = seed()
    jid, _ = run(plant_job(s, worker="wB"))
    run(seed_evidence(jid, s["org"], s["user"]))

    async def race():
        return await asyncio.gather(
            _finalize("wA", jid, s["org"], s["user"], s["repo"]),
            _finalize("wB", jid, s["org"], s["user"], s["repo"]),
            return_exceptions=True)
    results = run(race())
    perms = [r for r in results if isinstance(r, PermissionError)]
    oks = [r for r in results if isinstance(r, str)]
    assert len(perms) == 1 and len(oks) == 1                          # exactly one winner
    st = run(job_state(jid))
    assert st["state"] == "SUCCEEDED" and st["outcome"] == 1 and st["candidate"] == 1


def test_idempotent_retry(seed):
    s = seed()
    jid, _ = run(plant_job(s, worker="wX"))
    run(seed_evidence(jid, s["org"], s["user"]))
    run(_finalize("wX", jid, s["org"], s["user"], s["repo"]))
    with pytest.raises(PermissionError):                             # already terminal
        run(_finalize("wX", jid, s["org"], s["user"], s["repo"]))
    st = run(job_state(jid))
    assert st["outcome"] == 1 and st["candidate"] == 1 and st["episode"] == 1
