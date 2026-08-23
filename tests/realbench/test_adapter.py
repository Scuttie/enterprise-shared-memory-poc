"""REALBENCH-R1 §5/§11 — adapter mapping is cross-platform (reads the official dataset). The model-visible
snapshot exposes ONLY the official prompt; the canonical solution, augmented tests, and expected outputs never
appear in it. Grading itself is Linux-only (see test_grader)."""
import pytest
evalplus = pytest.importorskip("evalplus")
from experiments.realbench_r1.adapter import EvalPlusMBPPTaskAdapter, fixture_id, GRADER_MARKER
from experiments.realbench_r1 import grader as G


def _some_ids():
    return G.all_task_ids()[:20]


def test_fixture_id_mapping():
    assert fixture_id("Mbpp/2") == "mbpp_2"
    a = EvalPlusMBPPTaskAdapter(_some_ids())
    rid = fixture_id("Mbpp/2")
    assert a.entry_point(rid) == G.task("Mbpp/2")["entry_point"]


def test_snapshot_only_prompt_no_leakage():
    ids = _some_ids()
    a = EvalPlusMBPPTaskAdapter(ids)
    for tid in ids:
        rid = fixture_id(tid)
        snap = a.snapshot(rid, a.resolve_commit(rid, "main"), "x")
        assert set(snap) == {"src/solution.py"}
        blob = snap["src/solution.py"]
        t = G.task(tid)
        assert blob == t["prompt"]
        # no canonical solution / augmented tests / expected outputs in the model-visible snapshot
        assert t["canonical_solution"].strip() not in blob
        assert "plus_input" not in blob and "canonical_solution" not in blob


def test_hidden_test_is_server_side_marker():
    a = EvalPlusMBPPTaskAdapter(_some_ids())
    rid = fixture_id("Mbpp/2")
    assert a.hidden_test(rid) == GRADER_MARKER + "Mbpp/2"
