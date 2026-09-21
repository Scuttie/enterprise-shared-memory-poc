"""Successor experiment binding and retained budget enforcement."""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import trimem_benchmark_run as benchmark
import trimem_skhynix_exploration as live
import trimem_skhynix_live as prior


def new_plan():
    value = deepcopy(live.read_json(ROOT / "artifacts/skhynix_v1/live_001/plan.json"))
    value.update(experiment_id=live.EXPERIMENT_ID,
                 exploration_policy=live.exploration_policy().manifest(),
                 previous_run=live.prior_evidence())
    return value


def test_larger_exploration_budget_keeps_model_output_memory_and_tools_constant():
    before, after = prior.runtime_lock(), live.runtime_lock()
    changed = {key for key, value in asdict(after.limits).items()
               if value != asdict(before.limits)[key]}
    assert changed == {"max_steps_per_subtask", "max_solve_calls", "max_agent_steps"}
    assert after.limits.max_steps_per_subtask == 24
    assert after.limits.max_solve_calls == after.limits.max_agent_steps == 48
    assert not after.adaptive_horizon.enabled
    assert before.prompt_hashes == after.prompt_hashes
    assert before.function_tools_sha256 == after.function_tools_sha256
    assert live.MODEL == prior.MODEL and live.PRICING == prior.PRICING


def test_new_caps_cover_48_solve_calls_and_same_output_pool():
    caps = live.budget_caps(36, 5)
    assert caps["solve_calls"] == 1728
    assert caps["paid_model_calls"] == caps["model_calls"] == 1800
    assert caps["decomposition_calls"] == caps["extraction_calls"] == 36
    assert caps["output_tokens"] == prior.budget_caps(36, 5)["output_tokens"]
    assert caps["max_model_calls_per_task_arm"] == 50


@pytest.mark.parametrize("cap", [0, -1, 10.01, float("inf"), float("nan")])
def test_invalid_cap_is_rejected(cap):
    with pytest.raises(ValueError):
        live.budget_caps(36, cap)


def test_successor_is_bound_to_unmodified_prior_public_evidence():
    value = new_plan()
    live.verify_exploration_plan(value)
    assert value["previous_run"]["report_file_sha256"] == live.PREVIOUS_REPORT_SHA256
    assert value["previous_run"]["plan_sha256"] == live.PREVIOUS_PLAN_SHA256
    assert value["experiment_id"] != prior.read_json(ROOT / "artifacts/skhynix_v1/live_001/plan.json")["experiment_id"]


def test_new_plan_cannot_reuse_an_old_or_contaminated_workspace(tmp_path):
    output, workspace = tmp_path / "output", tmp_path / "workspace"
    live.require_fresh_roots(output, workspace)
    workspace.mkdir()
    (workspace / "previous-patch").write_text("old experiment state")
    with pytest.raises(ValueError, match="empty"):
        live.require_fresh_roots(output, workspace)
    assert not output.exists()


def test_new_plan_cannot_overlay_existing_output(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "public-result.json").write_text("retained")
    with pytest.raises(ValueError, match="empty"):
        live.require_fresh_roots(output, tmp_path / "workspace")
    assert (output / "public-result.json").read_text() == "retained"


@pytest.mark.parametrize("field", ["experiment_id", "exploration_policy", "previous_run",
                                    "targets", "model_lock", "pricing", "source_bank_file_sha256"])
def test_mismatched_policy_history_or_comparison_conditions_are_rejected(field):
    value = new_plan()
    value[field] = None
    with pytest.raises(ValueError):
        live.verify_exploration_plan(value)


def test_reopening_budget_retains_reservations_and_rejects_changed_cap(tmp_path):
    caps = live.budget_caps(36, 5)
    path = tmp_path / "ledger.json"
    ledger = benchmark.AtomicBudgetLedger(path, approval_digest="a" * 64, caps=caps, pricing=live.PRICING)
    key = "successor:M0:target"
    ledger.reserve_task_arm(key)
    before = path.read_bytes()
    reopened = benchmark.AtomicBudgetLedger(path, approval_digest="a" * 64, caps=caps, pricing=live.PRICING)
    assert reopened.task_arm_status(key) == "RESERVED"
    assert path.read_bytes() == before
    with pytest.raises(benchmark.BenchmarkExecutionError):
        benchmark.AtomicBudgetLedger(path, approval_digest="a" * 64,
                                     caps={**caps, "total_usd": 10}, pricing=live.PRICING)._read()
    assert path.read_bytes() == before


def test_low_budget_stops_before_any_paid_call(tmp_path):
    ledger = benchmark.AtomicBudgetLedger(tmp_path / "ledger.json", approval_digest="b" * 64,
                                         caps=live.budget_caps(36, 0.001), pricing=live.PRICING)
    key = "successor:M0:target"
    ledger.reserve_task_arm(key)
    with pytest.raises(benchmark.ModelPreflightFailure) as exc:
        ledger.preview_reservation("successor:solve:0001", request_sha256="c" * 64,
                                   task_arm_key=key, call_kind="solve",
                                   input_upper_bound=1000, output_cap=16384)
    assert exc.value.classification == "PHASE_USD_CAP_EXHAUSTED"
    assert Decimal(str(ledger._read()["actual"]["total_usd"])) == 0
    assert ledger._read()["actual"]["paid_model_calls"] == 0


def test_unmatched_success_is_excluded_from_new_paired_rate():
    plan = {"targets": [{"target_id": "one"}, {"target_id": "two"}]}
    cells = [dict(arm=arm, target_id="one", resolved=False, official=True,
                  status="CELL_SCIENTIFIC_FAILURE", accounting={"paid_model_calls": 1,
                  "input_tokens": 100, "output_tokens": 50}, usd="0.001", injections=0)
             for arm in live.ARMS]
    cells.append({**cells[0], "target_id": "two", "resolved": True})
    report = live.aggregate(plan, cells, status="INCOMPLETE")
    assert report["fully_paired_target_ids"] == ["one"]
    assert report["arms"]["NO_MEMORY"]["completed_resolved"] == 1
    assert report["arms"]["NO_MEMORY"]["paired_solve_rate"] == 0
