"""Credential-free checks for separated R23 task/call/container cost accounting."""
from __future__ import annotations

import importlib.util
import os


ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _module():
    path = os.path.join(ROOT, "scripts", "r23_reproduction_cost.py")
    spec = importlib.util.spec_from_file_location("r23_reproduction_cost", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_primary_cost_separates_units_and_repeated_orders():
    grid = _module().build()
    primary = grid["plans"]["EXACT_PAPER_SCALE_PRIMARY"]
    assert primary["statistical_unique_task_n"] == 500
    assert primary["stream_order_repeats"] == 3
    assert primary["stream_orders_are_independent_task_n"] is False
    assert primary["task_runs"] == primary["grader_containers_planned"] == 4500
    assert primary["model_calls"]["expected"] == {
        "solving": 180000,
        "extraction": 7500,
        "total": 187500,
    }
    assert primary["model_calls"]["enforced_spendable_hard_cap"]["total"] == 1132500


def test_expected_and_hard_cost_are_distinct_and_extraction_is_explicit():
    primary = _module().build()["plans"]["EXACT_PAPER_SCALE_PRIMARY"]
    mini_expected = primary["cost_usd"]["expected"]["cheapest_gpt-4o-mini"]
    mini_hard = primary["cost_usd"]["enforced_spendable_hard_cap"]["cheapest_gpt-4o-mini"]
    assert mini_expected == {"solving": 236.25, "extraction": 18.108, "total": 254.358}
    assert mini_hard["total"] == 972.216
    assert mini_hard["total"] > mini_expected["total"]


def test_official_smoke_is_costed_but_not_executed():
    smoke = _module().build()["official_grader_smoke"]
    assert smoke["frozen_targets"] == 12
    assert smoke["task_condition_grades_planned"] == 24
    assert smoke["grader_containers_executed"] == 0
