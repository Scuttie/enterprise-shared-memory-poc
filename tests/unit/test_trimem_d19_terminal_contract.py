"""D1.9 request-free contained-cell and terminal denominator contract."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.scientific_terminal import (  # noqa: E402
    ScientificTerminalContractError,
    canonical_scientific_failure_class,
    validate_result_request_statuses,
    validate_scientific_role_call_accounting,
    validate_scientific_terminal_result,
)
import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402


PRICING = {
    "cached_input_per_million_tokens_usd": 0.075,
    "input_per_million_tokens_usd": 0.75,
    "model_id": "gpt-5.4-mini-2026-03-17",
    "output_per_million_tokens_usd": 4.5,
    "source_url": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
}


def _accounting(
    *, decompose: int, solve: int, extract: int
) -> dict[str, int]:
    value = {
        field: 0 for field in public_artifact.SCIENTIFIC_ACCOUNTING_FIELDS
    }
    calls = decompose + solve + extract
    value.update(
        {
            "decomposition_calls": decompose,
            "solve_calls": solve,
            "extraction_calls": extract,
            "solve_output_pool_capacity": 49_152,
            "remaining_solve_output_tokens": 49_152,
            "model_gateway_calls": calls,
            "paid_model_calls": calls,
            "grader_calls": 1,
            "grader_containers": 1,
            "official_grader_runs": 1,
        }
    )
    return value


def _provider(call_count: int, *, failed_unknown: bool = False) -> dict[str, Any]:
    distribution: dict[str, int] = {}
    if call_count:
        successful = call_count - int(failed_unknown)
        if successful:
            distribution["SUCCESS"] = successful
        if failed_unknown:
            distribution["MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN"] = 1
    return {
        "provider_status_distribution": distribution,
        "incomplete_count": 0,
        "refusal_count": 0,
        "structured_output_schema_failure_count": 0,
        "provider_reported_usage": {
            "available_calls": call_count - int(failed_unknown),
            "unavailable_calls": int(failed_unknown),
            "complete": not failed_unknown,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
        },
        "ledger_reservation": {
            "calls": call_count,
            "input_upper_bound": 0,
            "output_cap": 0,
            "conservatively_charged_calls": int(failed_unknown),
        },
    }


def _failure_metadata(
    *,
    stage: str,
    call_kind: str,
    provider_started: bool = False,
    reservation_created: bool = False,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "call_kind": call_kind,
        "provider_request_started": provider_started,
        "ledger_reservation_created": reservation_created,
    }


def _record(
    failure_class: str,
    metadata: dict[str, Any] | None,
    accounting: dict[str, int],
    *,
    provider: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = {
        "agent_completed": False,
        "arm": "M0",
        "cell_status": "CELL_SCIENTIFIC_FAILURE",
        "container_started": True,
        "execution_status": "CELL_TERMINAL",
        "extraction_status": "SUCCESS",
        "grader_exit_code": 0,
        "grader_patch_source": "CANONICAL_FAILED_CELL_NOOP",
        "grader_status": "success",
        "model_failure_class": failure_class,
        "official_grader": True,
        "resolved": False,
        "runtime_arm": "M0",
        "target_id": "target-001",
        "actual_accounting": accounting,
        "provider_outcomes": provider or _provider(
            accounting["model_gateway_calls"]
        ),
    }
    if metadata is not None:
        value["failure_metadata"] = metadata
    return value


@pytest.mark.parametrize(
    ("classification", "stage"),
    (
        ("TASK_INPUT_CONTEXT_BUDGET_EXCEEDED", "PRE_PROMPT_PROJECTION"),
        ("TASK_INPUT_CONTEXT_BUDGET_EXCEEDED", "PREFLIGHT"),
        ("TASK_TOOL_RESULT_PROJECTION_FAILURE", "PRE_PROMPT_PROJECTION"),
        ("TASK_ARM_INPUT_POOL_EXHAUSTED", "PREFLIGHT"),
        ("TASK_ARM_MODEL_CALL_POOL_EXHAUSTED", "PREFLIGHT"),
        ("TASK_ROLE_OUTPUT_POOL_EXHAUSTED", "PREFLIGHT"),
        ("TASK_TOTAL_OUTPUT_POOL_EXHAUSTED", "PREFLIGHT"),
    ),
)
def test_request_free_d19_failure_is_a_terminal_denominator_cell(
    classification: str, stage: str
) -> None:
    accounting = _accounting(decompose=0, solve=0, extract=0)
    record = _record(
        classification,
        _failure_metadata(stage=stage, call_kind="decompose"),
        accounting,
    )
    assert validate_scientific_terminal_result(record)["execution_status"] == (
        "CELL_TERMINAL"
    )
    assert validate_scientific_role_call_accounting(record) == {
        "decomposition_calls": 0,
        "solve_calls": 0,
        "extraction_calls": 0,
        "model_gateway_calls": 0,
        "paid_model_calls": 0,
    }
    validate_result_request_statuses(record, [])
    summary = benchmark_matrix.scientific_terminal_summary([record])
    assert summary["terminal_result_count"] == 1
    assert summary["unresolved_count"] == 1
    assert summary["contained_failure_count"] == 1


def test_d19_failure_requires_exact_sanitized_metadata() -> None:
    accounting = _accounting(decompose=0, solve=0, extract=0)
    missing = _record("TASK_ARM_INPUT_POOL_EXHAUSTED", None, accounting)
    with pytest.raises(
        ScientificTerminalContractError, match="metadata is absent or malformed"
    ):
        validate_scientific_terminal_result(missing)

    wrong_stage = _record(
        "TASK_ARM_INPUT_POOL_EXHAUSTED",
        _failure_metadata(stage="PRE_PROMPT_PROJECTION", call_kind="decompose"),
        accounting,
    )
    with pytest.raises(ScientificTerminalContractError, match="stage contradicts"):
        validate_scientific_terminal_result(wrong_stage)

    false_preflight = _record(
        "TASK_ARM_INPUT_POOL_EXHAUSTED",
        _failure_metadata(
            stage="PREFLIGHT",
            call_kind="decompose",
            provider_started=True,
        ),
        accounting,
    )
    with pytest.raises(ScientificTerminalContractError, match="pre-provider"):
        validate_scientific_terminal_result(false_preflight)


def test_solve_preflight_can_omit_solve_and_extraction_calls() -> None:
    accounting = _accounting(decompose=1, solve=0, extract=0)
    record = _record(
        "TASK_ARM_MODEL_CALL_POOL_EXHAUSTED",
        _failure_metadata(stage="PREFLIGHT", call_kind="solve"),
        accounting,
    )
    requests = [{"call_kind": "decompose", "status": "SUCCESS"}]
    validate_result_request_statuses(record, requests)


def test_extraction_projection_failure_proves_zero_extraction_call() -> None:
    accounting = _accounting(decompose=1, solve=1, extract=0)
    record = _record(
        "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
        _failure_metadata(
            stage="PRE_PROMPT_PROJECTION", call_kind="extract"
        ),
        accounting,
    )
    record.update(
        {
            "agent_completed": True,
            "grader_patch_source": "MODEL_PATCH",
            "extraction_status": "MEMORY_EXTRACTION_FAILED",
        }
    )
    requests = [
        {"call_kind": "decompose", "status": "SUCCESS"},
        {"call_kind": "solve", "status": "SUCCESS"},
    ]
    validate_result_request_statuses(record, requests)

    drift = dict(accounting)
    drift["extraction_calls"] = 1
    drift["model_gateway_calls"] = 3
    drift["paid_model_calls"] = 3
    with pytest.raises(ScientificTerminalContractError, match="extraction failure"):
        validate_scientific_role_call_accounting(record, drift)

    wrong_status = dict(record)
    wrong_status["cell_status"] = "MEMORY_EXTRACTION_FAILED"
    with pytest.raises(
        ScientificTerminalContractError, match="impossible|CELL_SCIENTIFIC_FAILURE"
    ):
        validate_scientific_terminal_result(wrong_status)


def test_request_only_unknown_without_reservation_is_not_a_second_call() -> None:
    accounting = _accounting(decompose=1, solve=2, extract=0)
    record = _record(
        "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN",
        _failure_metadata(
            stage="PROVIDER_LIFECYCLE",
            call_kind="solve",
            provider_started=True,
            reservation_created=False,
        ),
        accounting,
    )
    requests = [
        {"call_kind": "decompose", "status": "SUCCESS"},
        {"call_kind": "solve", "status": "SUCCESS"},
        {"call_kind": "solve", "status": "SUCCESS"},
    ]
    validate_result_request_statuses(record, requests)


def test_unknown_with_reservation_is_conservatively_terminalized_once() -> None:
    accounting = _accounting(decompose=1, solve=1, extract=0)
    provider = _provider(2, failed_unknown=True)
    record = _record(
        "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN",
        _failure_metadata(
            stage="PROVIDER_LIFECYCLE",
            call_kind="solve",
            provider_started=True,
            reservation_created=True,
        ),
        accounting,
        provider=provider,
    )
    requests = [
        {"call_kind": "decompose", "status": "SUCCESS"},
        {"call_kind": "solve", "status": "PROVIDER_FAILURE_CONSERVATIVE"},
    ]
    validate_result_request_statuses(record, requests)
    assert canonical_scientific_failure_class(
        record["model_failure_class"]
    ) == "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN"


def test_legacy_terminal_still_requires_both_common_role_calls() -> None:
    accounting = _accounting(decompose=0, solve=0, extract=0)
    record = _record("DAG has no ready node", None, accounting)
    with pytest.raises(ScientificTerminalContractError, match="exactly once"):
        validate_scientific_role_call_accounting(record)
    with pytest.raises(ScientificTerminalContractError, match="no terminal model"):
        validate_result_request_statuses(record, [])


def test_public_accounting_accepts_verified_bounded_role_totals() -> None:
    accounting = _accounting(decompose=0, solve=0, extract=0)
    assert public_artifact._validate_scientific_accounting(
        accounting, task_count=1, arm="M0"
    ) == accounting
    assert public_artifact._validate_provider_outcomes(
        _provider(0), accounting=accounting
    )["provider_status_distribution"] == {}


def test_public_round_trip_keeps_zero_call_failure_in_denominator() -> None:
    accounting = _accounting(decompose=0, solve=0, extract=0)
    provider = _provider(0)
    memory = {
        field: 0 for field in public_artifact.SCIENTIFIC_MEMORY_FIELDS
    }
    outcome = {
        "arm": "M0",
        "benchmark_id": "swebench_verified",
        "benchmark_role": "PRIMARY",
        "resolved": False,
        "target_id": "target-001",
        "actual_accounting": accounting,
        "actual_memory_metrics": memory,
        "provider_outcomes": provider,
        "actual_usd": "0.000000000000",
    }
    terminal = {
        "terminal_result_count": 1,
        "resolved_count": 0,
        "unresolved_count": 1,
        "contained_failure_count": 1,
        "cell_status_counts": {"CELL_SCIENTIFIC_FAILURE": 1},
        "model_failure_class_counts": {"TASK_ARM_INPUT_POOL_EXHAUSTED": 1},
        "model_partial_patch_count": 0,
        "canonical_failed_cell_noop_count": 1,
        "extraction_failure_count": 0,
    }
    stream = {
        "arm": "M0",
        "actual_accounting": dict(accounting),
        "actual_memory_metrics": dict(memory),
        "provider_outcomes": dict(provider),
        "actual_usd": "0.000000000000",
        "identity_seed_digest": "sha256:" + "a" * 64,
        "reporting_scope": "DESCRIPTIVE_POOLED_ALL_BENCHMARKS",
        "resolved_count": 0,
        "terminal_result_count": 1,
        "cell_status_counts": {"CELL_SCIENTIFIC_FAILURE": 1},
        "contained_failure_count": 1,
        "model_failure_class_counts": {"TASK_ARM_INPUT_POOL_EXHAUSTED": 1},
        "model_partial_patch_count": 0,
        "canonical_failed_cell_noop_count": 1,
        "extraction_failure_count": 0,
    }
    phase = {
        "schema": "trimem/verified-phase-budget/1.0",
        "actual_accounting": dict(accounting),
        "model_calls": 0,
        "task_arm_runs": 1,
        "total_usd": "0.000000000000",
        "uncached_token_cost_usd": "0.000000000000",
        "hard_cap": {},
        "status": "PASS",
    }
    validated_terminal = (
        public_artifact.validate_public_scientific_terminal_summary(
            terminal, outcomes=[outcome]
        )
    )
    projected = public_artifact.validate_public_scientific_stream_totals(
        [stream],
        outcomes=[outcome],
        arms=["M0"],
        terminal_summary=validated_terminal,
        pricing=PRICING,
        phase_budget=phase,
        global_provider_outcomes=provider,
    )
    assert projected[0]["terminal_result_count"] == 1
    assert projected[0]["contained_failure_count"] == 1


def test_phase_budget_treats_role_counts_as_caps_not_required_spend() -> None:
    accounting = _accounting(decompose=0, solve=0, extract=0)
    hard_cap = {
        "benchmark_grader_containers": 1,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "input_tokens": 1_000,
        "max_input_tokens_per_task_arm": 1_000,
        "max_model_calls_per_task_arm": 26,
        "model_calls": 26,
        "output_tokens": 65_536,
        "paid_model_calls": 26,
        "solve_calls": 24,
        "task_arm_runs": 1,
        "total_usd": 1.0,
        "uncached_token_cost_ceiling_usd": float(
            (
                Decimal(1_000) * Decimal("0.75")
                + Decimal(65_536) * Decimal("4.5")
            )
            / Decimal(1_000_000)
        ),
    }
    phase = benchmark_matrix._validate_phase_budget(
        [{"actual_accounting": accounting}],
        pricing=PRICING,
        hard_cap=hard_cap,
    )
    assert phase["task_arm_runs"] == 1
    assert phase["actual_accounting"]["decomposition_calls"] == 0
    assert phase["actual_accounting"]["extraction_calls"] == 0
