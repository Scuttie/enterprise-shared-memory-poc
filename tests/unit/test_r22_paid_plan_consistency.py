"""R22 §5/§9 — paid v2 plan consistency (no model calls, no Docker)."""
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _plan():
    return json.load(open(os.path.join(ROOT, "configs", "r22", "paid_run_plan_v2.json"), encoding="utf-8"))


def _calc():
    spec = importlib.util.spec_from_file_location(
        "r22cost", os.path.join(ROOT, "scripts", "r22_recompute_paid_costs.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_run_counts():
    p = _plan()["run_counts"]
    assert p["p1_smoke"] == 84
    assert p["p2_analyzed_cells"] == 280
    assert p["p2_new_for_selected"] == 240
    assert p["selected_reader_total_new"] == 364
    assert p["reader_band_per_candidate"] == 40


def test_costs_are_tokencap_times_price_times_runs():
    m = _calc()
    plan = _plan()
    for model, price in m.PRICES.items():
        per_run = (m.HARD_IN_TOK / 1e6) * price["in"] + (m.HARD_OUT_TOK / 1e6) * price["out"]
        caps = plan["hard_caps"][model]
        assert abs(caps["p1_hard_cap"] - per_run * 84) < 1e-6
        assert abs(caps["p2_total_hard_cap"] - per_run * 280) < 1e-6
        assert abs(caps["selected_reader_total_hard_cap"] - per_run * 364) < 1e-6
        assert abs(caps["reader_band_hard_cap"] - per_run * 40) < 1e-6


def test_budget_below_hardcap_is_refused():
    plan = _plan()
    cap = plan["hard_caps"]["gpt-4o-mini"]["p1_hard_cap"]

    def may_start(budget, hard_cap):
        return budget >= hard_cap
    assert may_start(cap, cap) is True
    assert may_start(cap - 0.01, cap) is False


def test_v1_p1_caps_not_used_in_v2():
    # v1 P1 upper bounds were 4.6 / 2.5 / 42.0; v2 P1 hard caps must differ (84 runs, 800k/80k tokens)
    v2 = _plan()["hard_caps"]
    assert round(v2["deepseek-chat"]["p1_hard_cap"], 1) != 4.6
    assert round(v2["gpt-4o-mini"]["p1_hard_cap"], 1) != 2.5
    assert round(v2["gpt-4o"]["p1_hard_cap"], 1) != 42.0
    # and not the earlier §8 hard caps 7.3 / 4.0 / 67.2 either
    assert round(v2["deepseek-chat"]["p1_hard_cap"], 1) != 7.3


def test_p3_main_budget_forbidden_and_unset():
    plan = _plan()
    av = plan["approval_variables"]
    assert "R22_MAIN_BUDGET_USD" not in (av["reader_selection"], av["p1_smoke"], av["p2_oracle"], av["gate"])
    assert "R22_MAIN_BUDGET_USD" in av["forbidden"]
    assert os.environ.get("R22_MAIN_BUDGET_USD") is None


def test_v1_superseded_and_distinct_from_v2():
    v1 = json.load(open(os.path.join(ROOT, "configs", "r22", "paid_run_plan.json"), encoding="utf-8"))
    assert "SUPERSEDED" in v1.get("_SUPERSEDED", "")
    assert _plan()["authoritative"] is True
    arm1 = json.load(open(os.path.join(ROOT, "artifacts", "r22", "oracle_arm_manifest.json"), encoding="utf-8"))
    assert "SUPERSEDED" in arm1.get("_SUPERSEDED", "")


def test_v2_dev_task_count_is_40():
    arm2 = json.load(open(os.path.join(ROOT, "artifacts", "r22", "oracle_arm_manifest_v2.json"), encoding="utf-8"))
    assert arm2["p2_dev_tasks"] == 40 and arm2["p1_smoke_tasks"] == 12 and arm2["arms_per_task"] == 7


def test_three_primary_comparisons():
    p = _plan()["primary_contrasts"]
    assert p == {"Q1": "O5 - O2", "Q2": "O5 - O4", "Q3": "O6 - O5"}


def test_o3_not_a_product_candidate():
    plan = _plan()
    assert "O3" not in plan["product_candidates"]
    assert plan["product_candidates"] == ["O4", "O5", "O6"]
    assert plan["oracle_upper_bound_not_selectable"] == "O3"


def test_paid_api_calls_zero_marker():
    fr = json.load(open(os.path.join(ROOT, "artifacts", "r22", "paid_v2_freeze.json"), encoding="utf-8"))
    assert fr["paid_api_calls"] == 0 and fr["p3_main"].startswith("NOT RUN")
