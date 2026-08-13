"""P5.2 §4 — new coding instrument audit. Strata (prior_aligned / context_inferable / prior_conflict) with a
nonzero-M0-baseline structure: the memory-less prior baseline passes exactly the prior_aligned families and
fails every non-aligned one; >=12/16 calibration families differ from the common prior. Pure Python."""
import pytest
from benchmarks.p5_2_static import audit, generate, generation_hash, STRATA
from enterprise_memory.service.task_adapter import FrozenExecutableBenchmarkAdapterP52


def test_generator_audit_ok():
    r = audit.audit()
    assert r["ok"], r
    for name, s in r["splits"].items():
        assert s["strata_proportions_ok"]
        assert s["gold_pass_rate"] == 1.0
        assert s["prior_passes_all_prior_aligned"] and s["prior_passes_zero_non_aligned"]
        assert s["prior_public_pass_rate"] == 1.0
        assert s["source_target_task_overlap"] == 0 and s["source_target_repo_overlap"] == 0
        assert s["target_answer_leakage"] == 0 and s["hidden_test_leakage"] == 0
        assert s["exact_signature_rate"] == 1.0
    assert r["cross_split"]["family_overlap"] == 0 and r["cross_split"]["task_overlap"] == 0


def test_nonzero_baseline_structure():
    # exactly 4/16 calibration families are prior_aligned (memory-less-solvable) -> M0 baseline > 0 possible;
    # 12/16 differ from the common prior.
    cal = generate("calibration", 4)
    assert sum(f.stratum == "prior_aligned" for f in cal) == 4
    assert sum(f.stratum != "prior_aligned" for f in cal) == 12


def test_splits_and_determinism():
    assert len(generate("instrument_dev", 2)) == 8
    assert len(generate("calibration", 4)) == 16
    assert len(generate("main", 8)) == 32
    assert generation_hash("calibration", 4) == generation_hash("calibration", 4)
    assert generation_hash("calibration", 4) != generation_hash("main", 8)


def test_public_test_hides_edge():
    # the public test must only exercise the core inputs, never the edge input
    for f in generate("calibration", 4):
        t = f.target
        assert ("(%d)" % t.edge_input) not in t.public_test           # edge input not in public test
        assert ("(%d)" % t.edge_input) in t.hidden_test               # edge input in hidden test


def test_adapter_snapshot_excludes_hidden():
    a = FrozenExecutableBenchmarkAdapterP52()
    rid = next(iter(a._by_repo))
    snap = a.snapshot(rid, a.resolve_commit(rid, "main"), "x")
    assert a.hidden_test(rid) not in "\n".join(snap.values())
