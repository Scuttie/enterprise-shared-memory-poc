"""P5.1 §2/§3/§4 — real worker pipeline against PostgreSQL + Qdrant. Proves: the DB `injected` flag equals
the actual backend payload byte-for-byte (via a recording backend); a private view is really compiled into
the payload; an adversarial cross-user private candidate (tampered index owner) is rejected and recorded and
never reaches the payload; the worker aborts on lease loss / cancellation without a terminal write."""
import hashlib
import pytest
from conftest import (run, plant_job, seed_private_episode, seed_shared_contract, steal_lease,
                      retrieval_rows, job_state, add_user, grant_repo_read)
from enterprise_memory.service import solve_worker as W
from enterprise_memory.service.ci_container import build_container
from enterprise_memory.service.execution import FakeExecutionBackend, ExecutionResult


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


@pytest.fixture(scope="module")
def container():
    c = build_container("ci")
    run(c.ensure_ready())
    yield c
    run(c.aclose())


def _run_job(container, ev, worker="wP"):
    rec = RecordingBackend()
    container.backend = rec
    result = run(W.process_job(container, worker, ev))
    return result, rec


def test_injected_flag_equals_payload(seed, container):
    s = seed()
    run(seed_shared_contract(s["org"], s["repo"]))
    jid, ev = run(plant_job(s, worker="wP"))
    result, rec = _run_job(container, ev)
    assert result["status"] == "SUCCEEDED", result
    assert result["cross_user"] == 0
    rows = run(retrieval_rows(jid))
    injected = [r for r in rows if r["injected"]]
    # every injected DB row's view hash is present in the ACTUAL backend payload, and counts match
    payload_hashes = sorted(_sha(v) for v in rec.seen_views)
    db_hashes = sorted(r["injected_view_hash"] for r in injected)
    assert db_hashes == payload_hashes and len(db_hashes) >= 1
    # positions are 0..n-1
    assert sorted(r["injected_position"] for r in injected) == list(range(len(injected)))


def test_private_view_actually_injected(seed, container):
    s = seed()
    run(seed_private_episode(s["org"], s["user"], s["repo"], "prefer a retry multiplier of three under load"))
    jid, ev = run(plant_job(s, worker="wP"))
    result, rec = _run_job(container, ev)
    assert result["status"] == "SUCCEEDED", result
    rows = run(retrieval_rows(jid))
    priv_inj = [r for r in rows if r["scope"] == "private" and r["injected"]]
    assert len(priv_inj) == 1
    # the compiled private view is byte-for-byte in the payload; provenance (episode id/owner) is NOT
    assert priv_inj[0]["injected_view_hash"] in [_sha(v) for v in rec.seen_views]
    joined = "\n".join(rec.seen_views)
    assert s["user"] not in joined and jid not in joined
    assert result["cross_user"] == 0


def test_adversarial_cross_user_rejected(seed, container):
    s = seed()
    run(seed_shared_contract(s["org"], s["repo"]))
    bob = run(add_user(s["org"]))
    run(grant_repo_read(s["org"], s["repo"], bob))
    # Bob owns a private episode, but the index payload is TAMPERED to claim alice (s['user']) as owner
    run(seed_private_episode(s["org"], bob, s["repo"], "bob secret rule value 7", index_owner=s["user"]))
    jid, ev = run(plant_job(s, worker="wP"))     # alice submits
    result, rec = _run_job(container, ev)
    assert result["status"] == "SUCCEEDED", result
    assert result["cross_user"] == 0
    rows = run(retrieval_rows(jid))
    # a private candidate was examined and REJECTED (never injected); its rejection is recorded
    priv = [r for r in rows if r["scope"] == "private"]
    assert priv and all(not r["injected"] for r in priv)
    assert any((not r["accepted"]) and r["rejection_reason"] for r in priv)
    # no cross-user private text reached the backend payload
    assert "bob secret rule value 7" not in "\n".join(rec.seen_views)


def test_cancel_before_stages_no_terminal(seed, container):
    s = seed()
    jid, ev = run(plant_job(s, worker="wP", cancel=True))
    result, _ = _run_job(container, ev)
    assert result["status"] == "CANCELLED", result
    st = run(job_state(jid))
    assert st["state"] == "CANCELLED" and st["outcome"] == 0     # no SUCCEEDED, no terminal outcome


def test_lease_stolen_aborts_no_terminal(seed, container):
    s = seed()
    jid, ev = run(plant_job(s, worker="wP"))
    run(steal_lease(jid, "wOther"))                              # another worker reclaimed the lease
    result, _ = _run_job(container, ev, worker="wP")
    assert result["status"] == "LEASE_LOST", result
    st = run(job_state(jid))
    assert st["state"] == "RETRIEVING" and st["outcome"] == 0    # stale worker wrote nothing terminal
