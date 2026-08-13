"""P5.1 §6 — frozen executable coding bank generator audit + task-adapter contract. Pure Python (runs in
`ci`): zero source/target overlap, zero target-answer/hidden-test leakage, gold passes 100%, wrong-world
fails where required, exact-signature coverage 100%, deterministic regeneration; the adapter never ships the
hidden test; the company adapter fails closed until configured."""
import pytest
from benchmarks.p5_1_static import audit, generate, generation_hash
from enterprise_memory.service.task_adapter import (FrozenExecutableBenchmarkAdapter,
                                                    CompanyRepositoryAdapter, CompanyAdapterNotConfigured)


def test_generator_audit_ok():
    r = audit.audit()
    assert r["ok"], r
    for name, s in r["splits"].items():
        assert s["source_target_task_overlap"] == 0
        assert s["source_target_repo_overlap"] == 0
        assert s["target_answer_leakage"] == 0
        assert s["hidden_test_leakage"] == 0
        assert s["gold_pass_rate"] == 1.0
        assert s["wrong_world_fail_rate"] == 1.0
        assert s["exact_signature_rate"] == 1.0
    assert r["cross_split"]["family_overlap"] == 0 and r["cross_split"]["task_overlap"] == 0


def test_counts():
    assert len(generate("calibration", 4)) == 16       # 4 domains x 4
    assert len(generate("main", 8)) == 32              # 4 domains x 8


def test_deterministic_regeneration():
    assert generation_hash("calibration", 4) == generation_hash("calibration", 4)
    assert generation_hash("main", 8) == generation_hash("main", 8)
    assert generation_hash("calibration", 4) != generation_hash("main", 8)


def test_adapter_snapshot_excludes_hidden():
    a = FrozenExecutableBenchmarkAdapter()
    rid = next(iter(a._by_repo))
    snap = a.snapshot(rid, a.resolve_commit(rid, "main"), "x")
    assert any(p.startswith("src/") for p in snap) and any(p.startswith("tests/") for p in snap)
    hidden = a.hidden_test(rid)
    assert hidden and hidden not in "\n".join(snap.values())     # hidden test never ships
    assert a.snapshot_hash(rid, "c", "x") == a.snapshot_hash(rid, "c", "x")


def test_company_adapter_fails_closed():
    a = CompanyRepositoryAdapter()          # unconfigured
    for call in (lambda: a.snapshot("r", "c", "x"), lambda: a.resolve_commit("r", "main"),
                 lambda: a.hidden_test("r"), lambda: a.installation_for("o")):
        with pytest.raises(CompanyAdapterNotConfigured):
            call()
