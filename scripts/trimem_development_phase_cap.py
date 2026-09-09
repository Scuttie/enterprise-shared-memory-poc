"""Single-source DEVELOPMENT_TUNING phase-cap validation.

The cap material itself is loaded from the committed cost plan by the caller.
This module only validates the complete field set and the frozen arithmetic; it
does not read an approval document or provide a fallback budget.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping


PROTOCOL_CANARY_CALLS = 1
PROTOCOL_CANARY_INPUT_RESERVATION = 4_096
PROTOCOL_CANARY_OUTPUT_RESERVATION = 2_048
SCIENTIFIC_TASK_ARM_RUNS = 72
SCIENTIFIC_GRADER_CONTAINERS = 72
SCIENTIFIC_DECOMPOSITION_CALLS = 72
SCIENTIFIC_EXTRACTION_CALLS = 72
SCIENTIFIC_SOLVE_CALLS = 1_728
SCIENTIFIC_GENERATION_CALLS = 1_872
SCIENTIFIC_INPUT_TOKENS = 36_000_000
SCIENTIFIC_OUTPUT_TOKENS = 4_718_592
DEVELOPMENT_MODEL_CALLS = 1_873
DEVELOPMENT_INPUT_TOKENS = 36_004_096
DEVELOPMENT_OUTPUT_TOKENS = 4_720_640
DEVELOPMENT_TOTAL_USD = Decimal("50.0")
DEVELOPMENT_UNCACHED_TOKEN_COST_CEILING_USD = Decimal("48.245952")
SCIENTIFIC_UNCACHED_TOKEN_COST_CEILING_USD = Decimal("48.233664")
MAX_INPUT_TOKENS_PER_TASK_ARM = 500_000
MAX_MODEL_CALLS_PER_TASK_ARM = 26
TASK_OUTPUT_TOKEN_POOL = 65_536
MINI_INPUT_PRICE_PER_MILLION_USD = Decimal("0.75")
MINI_OUTPUT_PRICE_PER_MILLION_USD = Decimal("4.50")
PROTOCOL_CANARY_UNCACHED_COST_CEILING_USD = Decimal("0.012288")
EXACT_MODEL = "gpt-5.4-mini-2026-03-17"
SHA256 = re.compile(r"^[0-9a-f]{64}$")

DEVELOPMENT_PHASE_HARD_CAP_FIELDS = frozenset({
    "benchmark_grader_containers",
    "decomposition_calls",
    "extraction_calls",
    "input_tokens",
    "max_input_tokens_per_task_arm",
    "max_model_calls_per_task_arm",
    "model_calls",
    "output_tokens",
    "paid_model_calls",
    "protocol_canary_calls",
    "scientific_generation_calls",
    "solve_calls",
    "task_arm_runs",
    "total_usd",
    "uncached_token_cost_ceiling_usd",
})


class DevelopmentPhaseCapError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DevelopmentPhaseCapError(message)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        observed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DevelopmentPhaseCapError(
            f"DEVELOPMENT_TUNING {field} is not a finite decimal"
        ) from exc
    _require(observed.is_finite(), f"DEVELOPMENT_TUNING {field} is not finite")
    return observed


def validate_development_phase_hard_cap(
    phase_cap: Mapping[str, Any],
    *,
    protocol_canary_input_reservation: int = PROTOCOL_CANARY_INPUT_RESERVATION,
    protocol_canary_output_reservation: int = PROTOCOL_CANARY_OUTPUT_RESERVATION,
) -> dict[str, Any]:
    """Validate the complete frozen DEVELOPMENT_TUNING cap and arithmetic."""

    _require(isinstance(phase_cap, Mapping), "DEVELOPMENT_TUNING hard cap is missing")
    _require(
        set(phase_cap) == DEVELOPMENT_PHASE_HARD_CAP_FIELDS,
        "DEVELOPMENT_TUNING hard-cap field set differs",
    )
    _require(
        protocol_canary_input_reservation == PROTOCOL_CANARY_INPUT_RESERVATION
        and protocol_canary_output_reservation == PROTOCOL_CANARY_OUTPUT_RESERVATION,
        "DEV protocol-canary token reservation differs",
    )
    integer_fields = DEVELOPMENT_PHASE_HARD_CAP_FIELDS - {
        "total_usd", "uncached_token_cost_ceiling_usd"
    }
    _require(
        all(type(phase_cap[field]) is int and phase_cap[field] >= 0 for field in integer_fields),
        "DEVELOPMENT_TUNING integer hard-cap field is invalid",
    )
    _require(
        type(phase_cap["total_usd"]) is float
        and type(phase_cap["uncached_token_cost_ceiling_usd"]) is float,
        "DEVELOPMENT_TUNING monetary hard-cap scalar type differs",
    )

    task_arms = phase_cap["task_arm_runs"]
    _require(task_arms == SCIENTIFIC_TASK_ARM_RUNS, "DEV task-arm cap differs")
    _require(
        phase_cap["benchmark_grader_containers"]
        == SCIENTIFIC_GRADER_CONTAINERS
        == task_arms,
        "DEV grader/task-arm caps differ",
    )
    _require(
        phase_cap["decomposition_calls"] == SCIENTIFIC_DECOMPOSITION_CALLS == task_arms
        and phase_cap["extraction_calls"] == SCIENTIFIC_EXTRACTION_CALLS == task_arms,
        "DEV decomposition/extraction caps differ",
    )
    _require(
        phase_cap["solve_calls"] == SCIENTIFIC_SOLVE_CALLS == task_arms * 24,
        "DEV solve-call cap differs",
    )
    _require(
        phase_cap["max_model_calls_per_task_arm"] == MAX_MODEL_CALLS_PER_TASK_ARM,
        "DEV per-task model-call cap differs",
    )
    _require(
        phase_cap["scientific_generation_calls"]
        == SCIENTIFIC_GENERATION_CALLS
        == (
            phase_cap["decomposition_calls"]
            + phase_cap["solve_calls"]
            + phase_cap["extraction_calls"]
        )
        == task_arms * phase_cap["max_model_calls_per_task_arm"],
        "DEV scientific generation-call cap differs",
    )
    _require(
        phase_cap["protocol_canary_calls"] == PROTOCOL_CANARY_CALLS,
        "DEV protocol-canary call cap differs",
    )
    _require(
        phase_cap["model_calls"]
        == phase_cap["paid_model_calls"]
        == DEVELOPMENT_MODEL_CALLS
        == phase_cap["protocol_canary_calls"]
        + phase_cap["scientific_generation_calls"],
        "DEV global model-call arithmetic differs",
    )
    _require(
        phase_cap["max_input_tokens_per_task_arm"] == MAX_INPUT_TOKENS_PER_TASK_ARM,
        "DEV per-task input-token cap differs",
    )
    _require(
        phase_cap["input_tokens"]
        == DEVELOPMENT_INPUT_TOKENS
        == task_arms * phase_cap["max_input_tokens_per_task_arm"]
        + PROTOCOL_CANARY_INPUT_RESERVATION,
        "DEV global input-token arithmetic differs",
    )
    _require(
        phase_cap["output_tokens"]
        == DEVELOPMENT_OUTPUT_TOKENS
        == task_arms * TASK_OUTPUT_TOKEN_POOL + PROTOCOL_CANARY_OUTPUT_RESERVATION,
        "DEV global output-token arithmetic differs",
    )
    _require(
        _decimal(phase_cap["total_usd"], "total_usd") == DEVELOPMENT_TOTAL_USD,
        "DEV USD hard cap differs",
    )
    calculated_ceiling = (
        Decimal(phase_cap["input_tokens"]) * MINI_INPUT_PRICE_PER_MILLION_USD
        + Decimal(phase_cap["output_tokens"]) * MINI_OUTPUT_PRICE_PER_MILLION_USD
    ) / Decimal(1_000_000)
    _require(
        _decimal(
            phase_cap["uncached_token_cost_ceiling_usd"],
            "uncached_token_cost_ceiling_usd",
        )
        == DEVELOPMENT_UNCACHED_TOKEN_COST_CEILING_USD
        == calculated_ceiling,
        "DEV uncached token-cost ceiling differs",
    )
    return dict(phase_cap)


def scientific_cap_after_protocol_canary(
    phase_cap: Mapping[str, Any],
    canary: Mapping[str, Any],
    *,
    expected_approval_sha256: str,
) -> dict[str, Any]:
    """Validate a bound PASS canary and derive the exact scientific remainder."""

    validated = validate_development_phase_hard_cap(phase_cap)
    _require(
        isinstance(expected_approval_sha256, str)
        and SHA256.fullmatch(expected_approval_sha256) is not None
        and canary.get("approval_sha256") == expected_approval_sha256,
        "protocol canary approval binding differs",
    )
    required = {
        "status": "PASS",
        "scientific_result": False,
        "generation_calls": PROTOCOL_CANARY_CALLS,
        "input_token_cap": PROTOCOL_CANARY_INPUT_RESERVATION,
        "output_token_cap": PROTOCOL_CANARY_OUTPUT_RESERVATION,
        "model": EXACT_MODEL,
    }
    _require(
        all(canary.get(field) == expected for field, expected in required.items()),
        "protocol canary identity/status differs",
    )
    token_fields = ("input_tokens", "cached_input_tokens", "output_tokens")
    _require(
        all(type(canary.get(field)) is int and canary[field] >= 0 for field in token_fields),
        "protocol canary usage is invalid",
    )
    _require(
        canary["cached_input_tokens"] <= canary["input_tokens"]
        and canary["input_tokens"] <= PROTOCOL_CANARY_INPUT_RESERVATION
        and canary["output_tokens"] <= PROTOCOL_CANARY_OUTPUT_RESERVATION,
        "protocol canary exceeded its reservation",
    )
    canary_usd = _decimal(canary.get("actual_usd"), "protocol canary actual_usd")
    _require(
        Decimal("0") <= canary_usd <= PROTOCOL_CANARY_UNCACHED_COST_CEILING_USD,
        "protocol canary USD is outside its reservation",
    )

    scientific = dict(validated)
    scientific.pop("protocol_canary_calls")
    scientific.pop("scientific_generation_calls")
    scientific.update({
        "model_calls": validated["scientific_generation_calls"],
        "paid_model_calls": validated["scientific_generation_calls"],
        "input_tokens": validated["input_tokens"] - PROTOCOL_CANARY_INPUT_RESERVATION,
        "output_tokens": validated["output_tokens"] - PROTOCOL_CANARY_OUTPUT_RESERVATION,
        "total_usd": float(_decimal(validated["total_usd"], "total_usd") - canary_usd),
        "uncached_token_cost_ceiling_usd": float(
            _decimal(
                validated["uncached_token_cost_ceiling_usd"],
                "uncached_token_cost_ceiling_usd",
            )
            - PROTOCOL_CANARY_UNCACHED_COST_CEILING_USD
        ),
    })
    _require(
        scientific["model_calls"] == SCIENTIFIC_GENERATION_CALLS
        and scientific["input_tokens"] == SCIENTIFIC_INPUT_TOKENS
        and scientific["output_tokens"] == SCIENTIFIC_OUTPUT_TOKENS
        and _decimal(
            scientific["uncached_token_cost_ceiling_usd"],
            "scientific uncached_token_cost_ceiling_usd",
        )
        == SCIENTIFIC_UNCACHED_TOKEN_COST_CEILING_USD,
        "DEV scientific remainder differs",
    )
    return scientific


__all__ = [
    "DEVELOPMENT_INPUT_TOKENS",
    "DEVELOPMENT_MODEL_CALLS",
    "DEVELOPMENT_OUTPUT_TOKENS",
    "DEVELOPMENT_TOTAL_USD",
    "DEVELOPMENT_UNCACHED_TOKEN_COST_CEILING_USD",
    "DevelopmentPhaseCapError",
    "EXACT_MODEL",
    "PROTOCOL_CANARY_CALLS",
    "PROTOCOL_CANARY_INPUT_RESERVATION",
    "PROTOCOL_CANARY_OUTPUT_RESERVATION",
    "PROTOCOL_CANARY_UNCACHED_COST_CEILING_USD",
    "SCIENTIFIC_GENERATION_CALLS",
    "SCIENTIFIC_GRADER_CONTAINERS",
    "SCIENTIFIC_INPUT_TOKENS",
    "SCIENTIFIC_OUTPUT_TOKENS",
    "SCIENTIFIC_TASK_ARM_RUNS",
    "SCIENTIFIC_UNCACHED_TOKEN_COST_CEILING_USD",
    "scientific_cap_after_protocol_canary",
    "validate_development_phase_hard_cap",
]
