"""P5.1 §8/§17 — experiment-arm retrieval plumbing against real PostgreSQL + Qdrant (no Solar). Proves per
seeded arm that governed retrieval returns exactly the arm's memory: M0 retrieves nothing; M1 returns the
target user's own private note; M3 returns the governed contract; the expired (S2) and out-of-scope (S3)
controls are rejected by the governance gates and never injected. Also: the client cannot set an arm."""
import pytest
from conftest import run, su, worker_engine
from benchmarks.p5_1_static import generate
from experiments.p5_1 import plan as PLAN
from experiments.p5_1.seeding import seed_cell
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder
from enterprise_memory.indexing.validated_search import validated_search
from enterprise_memory.indexing.models import PRIVATE, SHARED
from enterprise_memory.service.injection import plan_injection

DIM = 64
_FAMS = {f.family_id: f for f in generate("calibration", 4)}
_CELLS = {c["arm"] + "|" + c["family_id"]: c
          for c in PLAN.build_plan("EXP_P5_1_CAL", PLAN.CALIBRATION, include_safety=True)["cells"]}


def _cell(arm):
    fam_id = next(iter(_FAMS))
    return _CELLS[arm + "|" + fam_id], _FAMS[fam_id]


async def _seed_and_search(arm, scope, requested_path=None):
    cell, fam = _cell(arm)
    idx = QdrantIndex.from_env(DIM); await idx.ensure_ready()
    emb = DeterministicTestEmbedder(DIM)
    sue = su()
    try:
        sub = await seed_cell(sue, idx, emb, cell, fam)
    finally:
        await sue.dispose()
    we = worker_engine()
    try:
        res = await validated_search(we, idx, emb, scope, sub["org"], fam.technique_note,
                                     user_id=sub["target_user"], requested_path=requested_path, limit=5)
        plan = plan_injection(res.hits if scope == PRIVATE else [],
                              res.hits if scope == SHARED else [], requester_id=sub["target_user"],
                              repo_id=sub["repo"], max_injected=1)
    finally:
        await we.dispose()
        await idx.close()
    return res, plan, sub


def test_m0_retrieves_nothing():
    res_s, _, _ = run(_seed_and_search("M0", SHARED))
    res_p, _, _ = run(_seed_and_search("M0", PRIVATE))
    assert res_s.hits == [] and res_p.hits == []


def test_m1_private_own_owner():
    res, plan, sub = run(_seed_and_search("M1", PRIVATE))
    assert len(res.hits) == 1 and res.hits[0].owner_user_id == sub["target_user"]
    assert len(plan.memory_views) == 1 and plan.cross_user_private_injection_count == 0


def test_m3_governed_injected():
    res, plan, sub = run(_seed_and_search("M3", SHARED))
    assert len(res.hits) == 1 and len(plan.memory_views) == 1


def test_s2_expired_rejected():
    res, plan, _ = run(_seed_and_search("S2", SHARED))
    assert res.hits == [] and plan.memory_views == []
    assert any(a.get("rejection_reason") == "expired" for a in res.audit)


def test_s3_out_of_scope_rejected():
    cell, fam = _cell("S3")
    res, _, _ = run(_seed_and_search("S3", SHARED, requested_path=fam.target.target_path))
    assert res.hits == []


def test_client_cannot_set_arm():
    from enterprise_memory.service.app import SolveRequest
    with pytest.raises(Exception):
        SolveRequest(repository_id="r", task_id="t", instruction="i", desired_ref="main", arm="M3")
