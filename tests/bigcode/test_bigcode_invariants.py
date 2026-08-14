"""BIGCODE-R2 pure-logic invariants (§19). No benchmark/DB/network — validates arms, selection, analysis,
multi-user assignment, and renderers so bugs are caught before the paid eval-image runs."""
from experiments.bigcode_r2 import main_arms as MA, analysis as AN, discovery as DISC, users as U, render as R


# ---- arms (§10) ----
def test_arms_full_set_and_dedup():
    assert [a["code"] for a in MA.physical_arms("F2_API_CARD")] == ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7"]
    # selected plain -> M6 aliases M2 (one physical arm)
    codes_plain = [a["code"] for a in MA.physical_arms("F1_PLAIN_LESSON")]
    assert "M6" not in codes_plain and "M2" in codes_plain
    codes_gov = [a["code"] for a in MA.physical_arms("F3_GOVERNED_COMPACT")]
    assert "M7" not in codes_gov


def test_m6_m7_same_source_kind_as_m2():
    A = {a["code"]: a for a in MA.arms("F2_API_CARD")}
    assert A["M6"]["source_kind"] == A["M7"]["source_kind"] == A["M2"]["source_kind"] == "relevant"
    assert A["M6"]["format"] == "F1_PLAIN_LESSON" and A["M7"]["format"] == "F3_GOVERNED_COMPACT"


# ---- selection rule (§8) ----
def test_selection_hard_safety_blocks():
    p1 = {f + "@P0": 0.5 for f in DISC.FORMATS}
    p1.update({f + "@P4": 0.3 for f in DISC.FORMATS})
    r = DISC.select_policy(p1, {c: 0.0 for c in p1}, {c: 100 for c in p1},
                           {"target_test_leakage": 1, "cross_user_leakage": 0, "invalid_injection": 0})
    assert r["selected"] is None and r["hard_safety_pass"] is False


def test_selection_maximises_relevance_effect_then_tiebreaks():
    p1 = {f + "@P0": 0.30 for f in DISC.FORMATS}
    p1.update({f + "@P4": 0.30 for f in DISC.FORMATS})
    p1["F2_API_CARD@P0"] = 0.45          # best relevance effect for F2
    r = DISC.select_policy(p1, {c: 0.05 for c in p1}, {c: 100 for c in p1},
                           {"target_test_leakage": 0, "cross_user_leakage": 0, "invalid_injection": 0})
    assert r["selected"]["format"] == "F2_API_CARD"


# ---- analysis (§11/§12) ----
def test_paired_and_mcnemar():
    a = {"t%d" % i: (1 if i < 7 else 0) for i in range(10)}     # a passes 7
    b = {"t%d" % i: (1 if i < 4 else 0) for i in range(10)}     # b passes 4, subset of a
    res = AN.paired(a, b, list(a))
    assert round(res["diff"], 3) == 0.3
    assert res["mcnemar"]["b"] == 3 and res["mcnemar"]["c"] == 0


def test_holm_monotone():
    out = AN.holm({"a": 0.001, "b": 0.02, "c": 0.30, "d": 0.6})
    assert out["a"]["reject"] is True
    # once one fails, all larger p fail
    assert out["c"]["reject"] is False and out["d"]["reject"] is False


# ---- multi-user (§5) ----
def test_users_source_target_pools_disjoint():
    a = U.build_assignment(["s%d" % i for i in range(30)], ["t%d" % i for i in range(50)])
    assert a["n_source_users"] == 24 and a["n_target_users"] == 24
    assert set(a["source_of"].values()) <= set(range(24))
    assert set(a["target_of"].values()) <= set(range(24))
    # private own-source is always a source task
    assert all(v.startswith("s") for v in a["private_source_of"].values())


# ---- renderers (§7) ----
def test_renderers_distinct_and_nonempty():
    fact = {"source_task": "BigCodeBench/1", "entry_point": "task_func", "summary": "do a thing",
            "verified_code": "def task_func():\n    return 1\n", "imports": ["os"], "apis": ["listdir"],
            "operations": ["sorted"], "control_flow": ["for_loop"], "pitfall": "empty input"}
    outs = {f: R.render(f, fact) for f in R.FORMATS}
    assert all(outs.values())                                   # all non-empty
    assert len(set(outs.values())) == len(outs)                # all distinct
    assert "listdir" in outs["F2_API_CARD"] and "applies-when" in outs["F3_GOVERNED_COMPACT"]
    assert fact["verified_code"].strip() in outs["F4_RAW_VERIFIED_TRACE"]
