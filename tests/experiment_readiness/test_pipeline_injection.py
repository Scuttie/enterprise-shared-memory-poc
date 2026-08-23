"""P5.1 §2/§3/§4 — real worker pipeline against PostgreSQL + Qdrant. Proves: the DB `injected` flag equals
the actual backend payload byte-for-byte (via a recording backend); a private view is really compiled into
the payload; an adversarial cross-user private candidate (tampered index owner) is rejected and recorded and
never reaches the payload; the worker aborts on lease loss / cancellation without a terminal write.

Each test runs ALL of its async work inside ONE event loop (build container -> seed -> process_job -> read),
because AsyncEngine connection pools are not safe to reuse across separate asyncio.run() loops."""
import hashlib
from conftest import (run, plant_job, seed_private_episode, seed_shared_contract, steal_lease,
                      retrieval_rows, job_state, add_user, grant_repo_read)
from enterprise_memory.service import solve_worker as W
from enterprise_memory.service.ci_container import build_container
from enterprise_memory.service.execution import FakeExecutionBackend


class RecordingBackend(FakeExecutionBackend):
    """Wraps the fake backend and captures the exact memory_views placed in the payload."""
    def __init__(self):
        super().__init__()
        self.seen_views = None

    async def execute(self, task_context, repository_snapshot, memory_views, *, logical_request_id, org_id):
        self.seen_views = list(memory_views)
        return await super().execute(task_context, repository_snapshot, memory_views,
                                     logical_request_id=logical_request_id, org_id=org_id)


def _sha(s):
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


async def _drive(flow, worker="wP"):
    """Build a container, run `flow(container, run_job)` in this loop, always close the container."""
    container = build_container("ci")
    await container.ensure_ready()
    rec = RecordingBackend()
    container.backend = rec

    async def run_job(ev, w=worker):
        return await W.process_job(container, w, ev)

    try:
        return await flow(container, run_job, rec)
    finally:
        await container.aclose()


def test_injected_flag_equals_payload(seed):
    s = seed()

    async def flow(container, run_job, rec):
        await seed_shared_contract(s["org"], s["repo"])
        jid, ev = await plant_job(s, worker="wP")
        result = await run_job(ev)
        rows = await retrieval_rows(jid)
        return result, rec.seen_views, rows
    result, seen, rows = run(_drive(flow))
    assert result["status"] == "SUCCEEDED", result
    assert result["cross_user"] == 0
    injected = [r for r in rows if r["injected"]]
    payload_hashes = sorted(_sha(v) for v in seen)
    db_hashes = sorted(r["injected_view_hash"] for r in injected)
    assert db_hashes == payload_hashes and len(db_hashes) >= 1
    assert sorted(r["injected_position"] for r in injected) == list(range(len(injected)))


def test_private_view_actually_injected(seed):
    s = seed()

    async def flow(container, run_job, rec):
        await seed_private_episode(s["org"], s["user"], s["repo"],
                                   "prefer a retry multiplier of three under load")
        jid, ev = await plant_job(s, worker="wP")
        result = await run_job(ev)
        rows = await retrieval_rows(jid)
        return result, rec.seen_views, rows, jid
    result, seen, rows, jid = run(_drive(flow))
    assert result["status"] == "SUCCEEDED", result
    priv_inj = [r for r in rows if r["scope"] == "private" and r["injected"]]
    assert len(priv_inj) == 1
    assert priv_inj[0]["injected_view_hash"] in [_sha(v) for v in seen]
    joined = "\n".join(seen)
    assert s["user"] not in joined and jid not in joined    # provenance never in the payload
    assert result["cross_user"] == 0


def test_adversarial_cross_user_rejected(seed):
    s = seed()

    async def flow(container, run_job, rec):
        await seed_shared_contract(s["org"], s["repo"])
        bob = await add_user(s["org"])
        await grant_repo_read(s["org"], s["repo"], bob)
        # Bob owns a private episode; the index payload is TAMPERED to claim alice (s['user']) as owner
        await seed_private_episode(s["org"], bob, s["repo"], "bob secret rule value 7",
                                   index_owner=s["user"])
        jid, ev = await plant_job(s, worker="wP")           # alice submits
        result = await run_job(ev)
        rows = await retrieval_rows(jid)
        return result, rec.seen_views, rows
    result, seen, rows = run(_drive(flow))
    assert result["status"] == "SUCCEEDED", result
    assert result["cross_user"] == 0
    priv = [r for r in rows if r["scope"] == "private"]
    assert priv and all(not r["injected"] for r in priv)
    assert any((not r["accepted"]) and r["rejection_reason"] for r in priv)
    assert "bob secret rule value 7" not in "\n".join(seen)


def test_cancel_before_stages_no_terminal(seed):
    s = seed()

    async def flow(container, run_job, rec):
        jid, ev = await plant_job(s, worker="wP", cancel=True)
        result = await run_job(ev)
        st = await job_state(jid)
        return result, st
    result, st = run(_drive(flow))
    assert result["status"] == "CANCELLED", result
    assert st["state"] == "CANCELLED" and st["outcome"] == 0


def test_lease_stolen_aborts_no_terminal(seed):
    s = seed()

    async def flow(container, run_job, rec):
        jid, ev = await plant_job(s, worker="wP")
        await steal_lease(jid, "wOther")                    # another worker reclaimed the lease
        result = await run_job(ev)
        st = await job_state(jid)
        return result, st
    result, st = run(_drive(flow))
    assert result["status"] == "LEASE_LOST", result
    assert st["state"] == "RETRIEVING" and st["outcome"] == 0
