#!/usr/bin/env python3
"""Build/check the R23 reproduction cost grid from the frozen R0 budget contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUDGET_PATH = ROOT / "artifacts" / "r23" / "r0_budget_lock.json"
GRID_PATH = ROOT / "artifacts" / "r23" / "reproduction_cost_grid.json"

# This is the inherited B0 planning-rate snapshot, not a current-price claim.
PRICES_PER_MTOK = {
    "cheapest_gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "middle_gpt-4o": {"input": 2.50, "output": 10.00},
    "stronger_claude-sonnet": {"input": 3.00, "output": 15.00},
}
PLANS = {
    "EXACT_PAPER_SCALE_PRIMARY": {"unique_task_n": 500, "stream_orders": 3, "arms": ["AR0", "AR2", "AR3"]},
    "EXACT_PAPER_SCALE_FULL_ABLATION": {
        "unique_task_n": 500,
        "stream_orders": 3,
        "arms": ["AR0", "AR1", "AR2", "AR3", "AR4", "AR5"],
    },
    "SCALED_PROTOCOL_REPLICATION": {"unique_task_n": 120, "stream_orders": 1, "arms": ["AR0", "AR2", "AR3"]},
}


def _cost(input_tokens: int, output_tokens: int, price: dict) -> float:
    return round(input_tokens / 1_000_000 * price["input"] + output_tokens / 1_000_000 * price["output"], 6)


def _empty_counts() -> dict:
    return {
        "solver_calls": 0,
        "extraction_calls": 0,
        "solver_input_tokens": 0,
        "solver_output_tokens": 0,
        "extraction_input_tokens": 0,
        "extraction_output_tokens": 0,
    }


def _aggregate_plan(plan: dict, budget: dict) -> dict:
    per_arm_runs = plan["unique_task_n"] * plan["stream_orders"]
    task_runs = per_arm_runs * len(plan["arms"])
    expected, hard = _empty_counts(), _empty_counts()
    arm_task_runs = {}
    for arm in plan["arms"]:
        arm_task_runs[arm] = per_arm_runs
        row = budget["arms"][arm]
        for phase in ("solver", "extraction"):
            expected[f"{phase}_calls"] += per_arm_runs * row[f"{phase}_calls_expected"]
            hard[f"{phase}_calls"] += per_arm_runs * row[f"{phase}_calls_hard_cap"]
            expected[f"{phase}_input_tokens"] += per_arm_runs * row[f"{phase}_input_tokens_expected"]
            expected[f"{phase}_output_tokens"] += per_arm_runs * row[f"{phase}_output_tokens_expected"]
            hard[f"{phase}_input_tokens"] += per_arm_runs * row[f"{phase}_input_tokens_hard_cap"]
            hard[f"{phase}_output_tokens"] += per_arm_runs * row[f"{phase}_output_tokens_hard_cap"]

    def finish(counts: dict) -> dict:
        return {
            **counts,
            "total_model_calls": counts["solver_calls"] + counts["extraction_calls"],
            "total_input_tokens": counts["solver_input_tokens"] + counts["extraction_input_tokens"],
            "total_output_tokens": counts["solver_output_tokens"] + counts["extraction_output_tokens"],
        }

    expected, hard = finish(expected), finish(hard)
    costs = {"expected": {}, "enforced_spendable_hard_cap": {}}
    for label, counts in (("expected", expected), ("enforced_spendable_hard_cap", hard)):
        for model, price in PRICES_PER_MTOK.items():
            solving = _cost(counts["solver_input_tokens"], counts["solver_output_tokens"], price)
            extraction = _cost(counts["extraction_input_tokens"], counts["extraction_output_tokens"], price)
            costs[label][model] = {
                "solving": solving,
                "extraction": extraction,
                "total": round(solving + extraction, 6),
            }
    common = budget["common_hard_envelope"]
    return {
        "statistical_unique_task_n": plan["unique_task_n"],
        "stream_order_repeats": plan["stream_orders"],
        "stream_orders_are_independent_task_n": False,
        "arms": plan["arms"],
        "task_runs": task_runs,
        "task_runs_by_arm": arm_task_runs,
        "grader_containers_planned": task_runs,
        "model_calls": {
            "expected": {
                "solving": expected["solver_calls"],
                "extraction": expected["extraction_calls"],
                "total": expected["total_model_calls"],
            },
            "enforced_spendable_hard_cap": {
                "solving": hard["solver_calls"],
                "extraction": hard["extraction_calls"],
                "total": hard["total_model_calls"],
            },
            "common_equal_envelope_slots": task_runs * common["total_model_calls"],
        },
        "tokens": {"expected": expected, "enforced_spendable_hard_cap": hard},
        "cost_usd": costs,
    }


def build() -> dict:
    budget = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    return {
        "schema_version": "r23/reproduction_cost_grid/2.0.0",
        "date": "2026-08-31",
        "rate_snapshot_status": "INHERITED_B0_PLANNING_RATES_REVERIFY_BEFORE_ANY_PAID_APPROVAL",
        "prices_per_million_tokens_usd": PRICES_PER_MTOK,
        "expected_vs_hard_cap": {
            "expected": "planning estimate from r0_budget_lock expected_basis; not a limit",
            "hard_cap": "maximum spendable under per-arm fail-closed call/token ledgers",
            "common_equal_envelope": "same reserved envelope for every arm; unused extraction capacity is not spendable by solver",
        },
        "plans": {name: _aggregate_plan(plan, budget) for name, plan in PLANS.items()},
        "official_grader_smoke": {
            "frozen_targets": 12,
            "conditions_per_target": ["GOLD", "NOOP"],
            "task_condition_grades_planned": 24,
            "grader_containers_executed": 0,
            "status": "PENDING_SEPARATE_EXEC_APPROVAL",
        },
        "statistical_note": "Three frozen stream orders are repeated measurements/order sensitivity over the same tasks; full-scale paired task N is 500, not 1500.",
        "paid_model_calls_at_generation": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")
    value = build()
    if args.check:
        old = json.loads(GRID_PATH.read_text(encoding="utf-8"))
        if old != value:
            print("R23 reproduction cost grid stale")
            return 1
        print("R23 reproduction cost grid current")
        return 0
    if args.write:
        GRID_PATH.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("wrote R23 reproduction cost grid")
        return 0
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
