from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_public_artifact as public_artifact  # noqa: E402


PRICING = {
    "cached_input_per_million_tokens_usd": 0.075,
    "input_per_million_tokens_usd": 0.75,
    "model_id": "gpt-5.4-mini-2026-03-17",
    "output_per_million_tokens_usd": 4.5,
    "source_url": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
}


def _accounting() -> dict[str, int]:
    value = {field: 0 for field in public_artifact.SCIENTIFIC_ACCOUNTING_FIELDS}
    value.update(
        {
            "solve_calls": 1,
            "decomposition_calls": 1,
            "extraction_calls": 1,
            "input_tokens": 31,
            "cached_input_tokens": 3,
            "output_tokens": 9,
            "reasoning_tokens": 1,
            "actual_decomposition_output_tokens": 2,
            "actual_solve_output_tokens": 3,
            "actual_extraction_output_tokens": 4,
            "solve_output_pool_capacity": 49_152,
            "remaining_solve_output_tokens": 49_149,
            "model_gateway_calls": 3,
            "paid_model_calls": 3,
            "grader_calls": 1,
            "grader_containers": 1,
            "official_grader_runs": 1,
        }
    )
    return value


def _memory() -> dict[str, int]:
    return {field: 0 for field in public_artifact.SCIENTIFIC_MEMORY_FIELDS}


def _provider(accounting: dict[str, int]) -> dict[str, Any]:
    return {
        "provider_status_distribution": {"SUCCESS": 3},
        "incomplete_count": 0,
        "refusal_count": 0,
        "structured_output_schema_failure_count": 0,
        "provider_reported_usage": {
            "available_calls": 3,
            "unavailable_calls": 0,
            "input_tokens": accounting["input_tokens"],
            "cached_input_tokens": accounting["cached_input_tokens"],
            "output_tokens": accounting["output_tokens"],
            "reasoning_tokens": accounting["reasoning_tokens"],
            "complete": True,
        },
        "ledger_reservation": {
            "calls": 3,
            "input_upper_bound": 46,
            "output_cap": 32_768,
            "conservatively_charged_calls": 0,
        },
    }


def _terminal_summary() -> dict[str, Any]:
    return {
        "terminal_result_count": 1,
        "resolved_count": 0,
        "unresolved_count": 1,
        "contained_failure_count": 0,
        "cell_status_counts": {"AGENT_COMPLETED": 1},
        "model_failure_class_counts": {"NONE": 1},
        "model_partial_patch_count": 0,
        "canonical_failed_cell_noop_count": 0,
        "extraction_failure_count": 0,
    }


def _scientific_projection() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], dict[str, Any]
]:
    accounting = _accounting()
    memory = _memory()
    provider = _provider(accounting)
    actual_usd = public_artifact._scientific_usd(accounting, PRICING)
    outcome = {
        "arm": "M0",
        "benchmark_id": "swebench_verified",
        "benchmark_role": "PRIMARY",
        "resolved": False,
        "target_id": "target-001",
        "actual_accounting": accounting,
        "actual_memory_metrics": memory,
        "provider_outcomes": provider,
        "actual_usd": actual_usd,
    }
    terminal = _terminal_summary()
    stream = {
        "arm": "M0",
        "actual_accounting": deepcopy(accounting),
        "actual_memory_metrics": deepcopy(memory),
        "provider_outcomes": deepcopy(provider),
        "actual_usd": actual_usd,
        "identity_seed_digest": "sha256:" + "a" * 64,
        "reporting_scope": "DESCRIPTIVE_POOLED_ALL_BENCHMARKS",
        "resolved_count": 0,
        **terminal,
    }
    stream.pop("resolved_count")
    stream.pop("unresolved_count")
    stream["resolved_count"] = 0
    phase = {
        "schema": "trimem/verified-phase-budget/1.0",
        "actual_accounting": deepcopy(accounting),
        "model_calls": accounting["model_gateway_calls"],
        "task_arm_runs": 1,
        "total_usd": actual_usd,
        "uncached_token_cost_usd": public_artifact._scientific_usd(
            accounting, PRICING, uncached=True
        ),
        "hard_cap": {},
        "status": "PASS",
    }
    return [outcome], [stream], terminal, phase


def _validate(
    outcomes: list[dict[str, Any]],
    streams: list[dict[str, Any]],
    terminal: dict[str, Any],
    phase: dict[str, Any],
    *,
    global_provider: dict[str, Any] | None = None,
) -> None:
    validated_terminal = public_artifact.validate_public_scientific_terminal_summary(
        terminal, outcomes=outcomes
    )
    public_artifact.validate_public_scientific_stream_totals(
        streams,
        outcomes=outcomes,
        arms=["M0"],
        terminal_summary=validated_terminal,
        pricing=PRICING,
        phase_budget=phase,
        global_provider_outcomes=(
            global_provider
            if global_provider is not None
            else deepcopy(outcomes[0]["provider_outcomes"])
        ),
    )


def test_public_scientific_accounting_provider_memory_and_usd_round_trip() -> None:
    _validate(*_scientific_projection())


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda outcomes, _streams, _terminal, _phase: outcomes[0][
                "actual_accounting"
            ].pop("input_tokens"),
            "accounting schema",
        ),
        (
            lambda outcomes, _streams, _terminal, _phase: outcomes[0][
                "actual_accounting"
            ].__setitem__("input_tokens", True),
            "accounting schema",
        ),
        (
            lambda _outcomes, streams, _terminal, _phase: streams[0][
                "actual_accounting"
            ].__setitem__("input_tokens", 32),
            "provider usage differs|accounting, provider, memory, or USD totals",
        ),
        (
            lambda outcomes, _streams, _terminal, _phase: outcomes[0][
                "provider_outcomes"
            ].__setitem__("refusal_count", 1),
            "provider outcome arithmetic",
        ),
        (
            lambda outcomes, _streams, _terminal, _phase: outcomes[0].__setitem__(
                "actual_usd", "1.000000000000"
            ),
            "USD differs",
        ),
        (
            lambda _outcomes, _streams, _terminal, phase: phase.__setitem__(
                "total_usd", "1.000000000000"
            ),
            "stream/global accounting, provider, or USD totals",
        ),
    ),
)
def test_public_scientific_numeric_projections_fail_closed(
    mutation: Any, message: str
) -> None:
    values = _scientific_projection()
    mutation(*values)
    with pytest.raises(public_artifact.PublicArtifactError, match=message):
        _validate(*values)


def test_public_scientific_global_provider_projection_is_recomputed() -> None:
    values = _scientific_projection()
    global_provider = deepcopy(values[0][0]["provider_outcomes"])
    global_provider["provider_status_distribution"] = {"SUCCESS": 2, "RESPONSE_REFUSAL": 1}
    global_provider["refusal_count"] = 1
    with pytest.raises(
        public_artifact.PublicArtifactError,
        match="stream/global accounting, provider, or USD totals",
    ):
        _validate(*values, global_provider=global_provider)


def test_public_scientific_provider_status_uses_shared_finite_contract() -> None:
    accounting = _accounting()
    provider = _provider(accounting)
    provider["provider_status_distribution"] = {"EVIL": 3}
    with pytest.raises(
        public_artifact.PublicArtifactError,
        match="provider outcome schema",
    ):
        public_artifact._validate_provider_outcomes(provider, accounting=accounting)


@pytest.mark.parametrize(
    "terminal",
    (
        {
            **_terminal_summary(),
            "model_failure_class_counts": {"DAG_NO_READY_NODE": 1},
        },
        {
            **_terminal_summary(),
            "contained_failure_count": 1,
            "cell_status_counts": {"MEMORY_EXTRACTION_FAILED": 1},
            "model_failure_class_counts": {"MEMORY_EXTRACTION_SCHEMA_FAILURE": 1},
            "extraction_failure_count": 0,
        },
        {
            **_terminal_summary(),
            "contained_failure_count": 1,
            "cell_status_counts": {"MEMORY_EXTRACTION_FAILED": 1},
            "model_failure_class_counts": {"MEMORY_EXTRACTION_SCHEMA_FAILURE": 1},
            "model_partial_patch_count": 1,
            "extraction_failure_count": 1,
        },
        {
            **_terminal_summary(),
            "contained_failure_count": 1,
            "cell_status_counts": {"CELL_SCIENTIFIC_FAILURE": 1},
            "model_failure_class_counts": {"DAG_NO_READY_NODE": 1},
        },
    ),
)
def test_public_scientific_semantic_distributions_fail_closed(
    terminal: dict[str, Any],
) -> None:
    with pytest.raises(
        public_artifact.PublicArtifactError, match="semantic distributions"
    ):
        public_artifact.validate_public_scientific_terminal_summary(
            terminal,
            outcomes=[{"resolved": False}],
        )


def test_uncached_usd_recomputation_uses_full_input_rate() -> None:
    accounting = _accounting()
    expected = (
        Decimal(accounting["input_tokens"]) * Decimal("0.75")
        + Decimal(accounting["output_tokens"]) * Decimal("4.5")
    ) / Decimal(1_000_000)
    assert public_artifact._scientific_usd(
        accounting, PRICING, uncached=True
    ) == format(expected, ".12f")
