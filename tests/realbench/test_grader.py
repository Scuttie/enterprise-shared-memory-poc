"""REALBENCH-R1 §11 grader validation — LINUX ONLY (the official evalplus unsafe_execute imports the Unix
`resource` module). Grades the official canonical solution (must pass base+plus for every task) and a
deliberately wrong solution (must fail), proving the service-side grader reproduces the official evaluator."""
import pytest
pytest.importorskip("evalplus")
try:
    import resource  # noqa
except Exception:
    pytest.skip("official evalplus grader is Linux-only (needs `resource`)", allow_module_level=True)

from experiments.realbench_r1 import grader as G

N = 20


def test_canonical_passes_and_wrong_fails():
    ids = G.all_task_ids()[:N]
    canon_pass = wrong_fail = 0
    for tid in ids:
        p = G.task(tid)
        r_ok = G.grade(tid, p["prompt"] + "\n" + p["canonical_solution"])
        r_bad = G.grade(tid, "%sdef %s(*a, **k):\n    return 999999999\n" % (p["prompt"], p["entry_point"]))
        canon_pass += r_ok["mbpp_plus_pass"]
        wrong_fail += (not r_bad["mbpp_plus_pass"])
    assert canon_pass == N, "official canonical solution must pass MBPP+ for all %d tasks (%d)" % (N, canon_pass)
    assert wrong_fail == N, "a wrong solution must fail for all %d tasks (%d)" % (N, wrong_fail)


def test_dataset_content_hash_pinned():
    # platform-independent content anchor (get_mbpp_plus_hash is line-ending sensitive across OSes)
    assert G.content_hash() == "bbaa3bec889558881f14ad8e2cc9ea9d7b9bed2c283484e823cebf5ce86a777c"
    assert len(G.all_task_ids()) == 378
