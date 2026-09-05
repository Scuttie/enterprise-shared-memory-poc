"""Shared fail-closed contract for officially graded scientific cells.

``CELL_TERMINAL`` means that one task/arm cell reached the end of the
scientific execution envelope and has an accepted official grader result.  It
does not mean that the task was resolved or that the coding agent completed
without a contained failure.  Those meanings belong to ``resolved`` and
``cell_status`` respectively.

This module is deliberately pure: importing and calling it performs no file,
network, provider, image, database, or grader operation.
"""
from __future__ import annotations

import re
from typing import Any, Mapping


SCIENTIFIC_EXECUTION_STATUS = "CELL_TERMINAL"
SCIENTIFIC_LEDGER_TERMINAL_STATUS = "CELL_TERMINAL"

SCIENTIFIC_CELL_STATUSES = frozenset(
    {
        "AGENT_COMPLETED",
        "CELL_SCIENTIFIC_FAILURE",
        "MEMORY_EXTRACTION_FAILED",
    }
)
SCIENTIFIC_GRADER_STATUSES = frozenset({"success"})
SCIENTIFIC_ACCEPTED_GRADER_EXIT_CODES = frozenset({0})
SCIENTIFIC_GRADER_PATCH_SOURCES = frozenset(
    {
        "MODEL_PATCH",
        "MODEL_PARTIAL_PATCH",
        "CANONICAL_FAILED_CELL_NOOP",
    }
)
SCIENTIFIC_EXTRACTION_STATUSES = frozenset(
    {"SUCCESS", "MEMORY_EXTRACTION_FAILED"}
)
SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES = frozenset(
    {
        "SUCCESS",
        "SUCCESS_CONSERVATIVE_USAGE",
        "PROVIDER_FAILURE",
        "PROVIDER_FAILURE_CONSERVATIVE",
    }
)

_RESULT_REQUIRED_FIELDS = frozenset(
    {
        "agent_completed",
        "arm",
        "cell_status",
        "container_started",
        "execution_status",
        "extraction_status",
        "grader_exit_code",
        "grader_patch_source",
        "grader_status",
        "model_failure_class",
        "official_grader",
        "resolved",
        "runtime_arm",
        "target_id",
    }
)
_LEDGER_ZERO_FIELDS = (
    "outstanding_input_tokens",
    "outstanding_model_calls",
    "outstanding_output_tokens",
)
_LEDGER_NONNEGATIVE_FIELDS = (
    "actual_input_tokens",
    "actual_model_calls",
    "actual_output_tokens",
    "actual_decomposition_output_tokens",
    "actual_solve_output_tokens",
    "actual_extraction_output_tokens",
    "remaining_decomposition_output_tokens",
    "remaining_solve_output_tokens",
    "remaining_extraction_output_tokens",
)
_ROLE_OUTPUT_POOLS = {
    "decomposition": 8_192,
    "solve": 49_152,
    "extraction": 8_192,
}
_CELL_GATEWAY_FAILURE_PREFIXES = (
    "RESPONSE_",
    "SOLVE_",
    "STRUCTURED_OUTPUT_",
)
_CELL_GATEWAY_FAILURE_EXACT = frozenset({"HTTP_200_INVALID_JSON"})
_CELL_FAILURE_CLASS_EXACT = frozenset({"MEMORY_EXTRACTION_SCHEMA_FAILURE"})
_LOCAL_POST_RESPONSE_SOLVE_FAILURES = frozenset(
    {
        # These five checks are repeated at the runtime boundary after a
        # successful gateway return.  The provider adapter normally enforces
        # them first, but a successful request ledger row is still coherent
        # when the defense-in-depth parser is the component that rejects it.
        "SOLVE_EXPECTED_FUNCTION_CALL",
        "SOLVE_FUNCTION_CALL_ID_MISSING",
        "SOLVE_UNKNOWN_FUNCTION",
        "SOLVE_FUNCTION_ARGUMENT_INVALID_JSON",
        "SOLVE_FUNCTION_ARGUMENT_SCHEMA_FAILURE",
    }
)
_PROVIDER_OUTCOME_FIELDS = frozenset(
    {
        "provider_status_distribution",
        "incomplete_count",
        "refusal_count",
        "structured_output_schema_failure_count",
        "provider_reported_usage",
        "ledger_reservation",
    }
)
_PROVIDER_USAGE_FIELDS = frozenset(
    {
        "available_calls",
        "unavailable_calls",
        "complete",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_tokens",
    }
)
_PROVIDER_RESERVATION_FIELDS = frozenset(
    {
        "calls",
        "input_upper_bound",
        "output_cap",
        "conservatively_charged_calls",
    }
)
_PRE_AGENT_RUNTIME_FAILURE_FRAGMENTS = (
    "TASK_SOLVE_OUTPUT_POOL_EXHAUSTED",
    "solve-call or global step cap reached",
    "per-subtask step cap reached",
    "DAG has no ready node",
    "decomposer must return",
    "invalid semantic subtask",
    "unknown semantic subtask field",
    "subtask IDs must be unique",
)
_POST_AGENT_EXTRACTION_FAILURE_FRAGMENTS = (
    "durable extraction model failure",
    "invalid extraction response",
    "semantic_candidate must be object or null",
    "failed source attempted to enter semantic bank",
    "episode extraction is incomplete",
    "extractor outcome contradicts grader",
)
_CELL_RUNTIME_FAILURE_FRAGMENTS = (
    *_PRE_AGENT_RUNTIME_FAILURE_FRAGMENTS,
    *_POST_AGENT_EXTRACTION_FAILURE_FRAGMENTS,
)
_CELL_RUNTIME_FAILURE_CLASSES = (
    ("TASK_SOLVE_OUTPUT_POOL_EXHAUSTED", "TASK_SOLVE_OUTPUT_POOL_EXHAUSTED"),
    ("solve-call or global step cap reached", "SOLVE_OR_GLOBAL_STEP_CAP_REACHED"),
    ("per-subtask step cap reached", "PER_SUBTASK_STEP_CAP_REACHED"),
    ("DAG has no ready node", "DAG_NO_READY_NODE"),
    ("decomposer must return", "DECOMPOSITION_CONTRACT_FAILURE"),
    ("invalid semantic subtask", "INVALID_SEMANTIC_SUBTASK"),
    ("unknown semantic subtask field", "UNKNOWN_SEMANTIC_SUBTASK_FIELD"),
    ("subtask IDs must be unique", "DUPLICATE_SEMANTIC_SUBTASK_ID"),
    ("durable extraction model failure", "DURABLE_EXTRACTION_MODEL_FAILURE"),
    ("invalid extraction response", "INVALID_EXTRACTION_RESPONSE"),
    ("semantic_candidate must be object or null", "INVALID_SEMANTIC_CANDIDATE"),
    ("failed source attempted to enter semantic bank", "FAILED_SOURCE_SEMANTIC_BANK_ATTEMPT"),
    ("episode extraction is incomplete", "INCOMPLETE_EPISODE_EXTRACTION"),
    ("extractor outcome contradicts grader", "EXTRACTOR_GRADER_OUTCOME_CONTRADICTION"),
)
_SAFE_GATEWAY_FAILURE_CLASS = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


class ScientificTerminalContractError(ValueError):
    """A result or ledger row cannot represent a valid scientific terminal."""


def scientific_task_arm_key(record: Mapping[str, Any]) -> str:
    """Return the canonical stream/runtime-arm/target identity for a result."""

    values = tuple(record.get(field) for field in ("arm", "runtime_arm", "target_id"))
    if any(not isinstance(value, str) or not value for value in values):
        raise ScientificTerminalContractError(
            "scientific result task-arm identity is malformed"
        )
    return ":".join(values)


def is_scientific_gateway_failure(value: object) -> bool:
    return isinstance(value, str) and (
        value.startswith(_CELL_GATEWAY_FAILURE_PREFIXES)
        or value in _CELL_GATEWAY_FAILURE_EXACT
    )


def is_scientific_runtime_failure(value: object) -> bool:
    return isinstance(value, str) and any(
        fragment in value for fragment in _CELL_RUNTIME_FAILURE_FRAGMENTS
    )


def is_pre_agent_runtime_failure(value: object) -> bool:
    """Return whether a contained runtime failure necessarily precedes completion."""

    return isinstance(value, str) and any(
        fragment in value for fragment in _PRE_AGENT_RUNTIME_FAILURE_FRAGMENTS
    )


def is_post_agent_extraction_failure(value: object) -> bool:
    """Return whether a contained runtime failure can only occur in extraction."""

    return value in _CELL_FAILURE_CLASS_EXACT or (
        isinstance(value, str)
        and any(
            fragment in value
            for fragment in _POST_AGENT_EXTRACTION_FAILURE_FRAGMENTS
        )
    )


def is_scientific_failure_class(value: object) -> bool:
    return (
        is_scientific_gateway_failure(value)
        or is_scientific_runtime_failure(value)
        or value in _CELL_FAILURE_CLASS_EXACT
    )


def canonical_scientific_failure_class(value: object) -> str:
    """Project a recognized possibly detailed failure into a safe finite class."""

    if not is_scientific_failure_class(value):
        raise ScientificTerminalContractError(
            "scientific model failure class is absent or unrecognized"
        )
    assert isinstance(value, str)
    if value in _CELL_FAILURE_CLASS_EXACT:
        return value
    if is_scientific_gateway_failure(value):
        if _SAFE_GATEWAY_FAILURE_CLASS.fullmatch(value):
            return value
        if value.startswith("RESPONSE_"):
            return "RESPONSE_OTHER"
        if value.startswith("SOLVE_"):
            return "SOLVE_OTHER"
        if value.startswith("STRUCTURED_OUTPUT_"):
            return "STRUCTURED_OUTPUT_OTHER"
        return "HTTP_200_INVALID_JSON"
    for fragment, category in _CELL_RUNTIME_FAILURE_CLASSES:
        if fragment in value:
            return category
    raise AssertionError("recognized runtime failure lacks a canonical class")


def _require_nonempty_failure(value: object) -> None:
    if not is_scientific_failure_class(value):
        raise ScientificTerminalContractError(
            "contained scientific cell has an absent or unrecognized model failure classification"
        )


def validate_scientific_terminal_result(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the terminal semantics of one current scientific result.

    Additional evidence/accounting fields are intentionally allowed here and
    are validated by the runner and aggregate at their respective boundaries.
    Legacy ``SUCCESS`` execution records are not accepted by this current
    contract.
    """

    if not isinstance(record, Mapping):
        raise ScientificTerminalContractError("scientific result is not an object")
    missing = sorted(_RESULT_REQUIRED_FIELDS - set(record))
    if missing:
        raise ScientificTerminalContractError(
            f"scientific result fields are missing: {missing}"
        )
    scientific_task_arm_key(record)
    if record.get("execution_status") != SCIENTIFIC_EXECUTION_STATUS:
        raise ScientificTerminalContractError(
            "scientific result execution status is not CELL_TERMINAL"
        )
    cell_status = record.get("cell_status")
    if cell_status not in SCIENTIFIC_CELL_STATUSES:
        raise ScientificTerminalContractError(
            "scientific result cell status is unknown or malformed"
        )
    if record.get("grader_status") not in SCIENTIFIC_GRADER_STATUSES:
        raise ScientificTerminalContractError(
            "scientific result has no accepted completed grader status"
        )
    grader_exit_code = record.get("grader_exit_code")
    if (
        type(grader_exit_code) is not int
        or grader_exit_code not in SCIENTIFIC_ACCEPTED_GRADER_EXIT_CODES
    ):
        raise ScientificTerminalContractError(
            "scientific result has an unaccepted grader exit code"
        )
    if record.get("official_grader") is not True:
        raise ScientificTerminalContractError(
            "scientific result has no official grader result"
        )
    if record.get("container_started") is not True:
        raise ScientificTerminalContractError(
            "scientific result has no started grader container"
        )
    if type(record.get("resolved")) is not bool:
        raise ScientificTerminalContractError(
            "scientific result resolved value is not boolean"
        )
    if type(record.get("agent_completed")) is not bool:
        raise ScientificTerminalContractError(
            "scientific result agent completion value is not boolean"
        )
    patch_source = record.get("grader_patch_source")
    if patch_source not in SCIENTIFIC_GRADER_PATCH_SOURCES:
        raise ScientificTerminalContractError(
            "scientific result grader patch source is unknown or malformed"
        )
    extraction_status = record.get("extraction_status")
    if extraction_status not in SCIENTIFIC_EXTRACTION_STATUSES:
        raise ScientificTerminalContractError(
            "scientific result extraction status is unknown or malformed"
        )
    failure_class = record.get("model_failure_class")

    if cell_status == "AGENT_COMPLETED":
        if (
            record["agent_completed"] is not True
            or failure_class is not None
            or patch_source != "MODEL_PATCH"
            or extraction_status != "SUCCESS"
        ):
            raise ScientificTerminalContractError(
                "AGENT_COMPLETED result has an impossible terminal-field combination"
            )
    elif cell_status == "MEMORY_EXTRACTION_FAILED":
        _require_nonempty_failure(failure_class)
        if (
            record["agent_completed"] is not True
            or patch_source not in {"MODEL_PATCH", "CANONICAL_FAILED_CELL_NOOP"}
            or extraction_status != "MEMORY_EXTRACTION_FAILED"
            or is_pre_agent_runtime_failure(failure_class)
        ):
            raise ScientificTerminalContractError(
                "MEMORY_EXTRACTION_FAILED result has an impossible terminal-field combination"
            )
    else:
        _require_nonempty_failure(failure_class)
        if (
            record["agent_completed"] is not False
            or patch_source not in {
                "MODEL_PARTIAL_PATCH", "CANONICAL_FAILED_CELL_NOOP"
            }
            or is_post_agent_extraction_failure(failure_class)
        ):
            raise ScientificTerminalContractError(
                "CELL_SCIENTIFIC_FAILURE result has an impossible terminal-field combination"
            )

    return dict(record)


def validate_scientific_terminal_ledger_row(
    row: Mapping[str, Any],
    *,
    task_arm_key: str | None = None,
) -> dict[str, Any]:
    """Validate one reconciled current scientific task-arm ledger row."""

    if not isinstance(row, Mapping):
        raise ScientificTerminalContractError(
            "scientific task-arm ledger row is not an object"
        )
    if task_arm_key is not None and (
        not isinstance(task_arm_key, str) or not task_arm_key
    ):
        raise ScientificTerminalContractError(
            "scientific task-arm ledger identity is malformed"
        )
    if row.get("status") != SCIENTIFIC_LEDGER_TERMINAL_STATUS:
        raise ScientificTerminalContractError(
            "scientific task-arm ledger status is not CELL_TERMINAL"
        )
    if row.get("container_started") is not True:
        raise ScientificTerminalContractError(
            "scientific task-arm ledger has no started grader container"
        )
    for field in _LEDGER_ZERO_FIELDS:
        if type(row.get(field)) is not int or row[field] != 0:
            raise ScientificTerminalContractError(
                f"scientific task-arm ledger has outstanding {field}"
            )
    for field in _LEDGER_NONNEGATIVE_FIELDS:
        if type(row.get(field)) is not int or row[field] < 0:
            raise ScientificTerminalContractError(
                f"scientific task-arm ledger {field} is malformed"
            )
    if row["actual_output_tokens"] != sum(
        row[f"actual_{role}_output_tokens"] for role in _ROLE_OUTPUT_POOLS
    ):
        raise ScientificTerminalContractError(
            "scientific task-arm ledger role output totals differ"
        )
    for role, pool in _ROLE_OUTPUT_POOLS.items():
        if (
            row[f"actual_{role}_output_tokens"]
            + row[f"remaining_{role}_output_tokens"]
            != pool
        ):
            raise ScientificTerminalContractError(
                f"scientific task-arm ledger {role} output pool differs"
            )
    return dict(row)


def validate_result_ledger_pair(
    record: Mapping[str, Any],
    row: Mapping[str, Any],
    *,
    ledger_task_arm_key: str,
) -> None:
    """Validate result/ledger identity and accounting as one terminal cell."""

    validate_scientific_terminal_result(record)
    validate_scientific_terminal_ledger_row(
        row, task_arm_key=ledger_task_arm_key
    )
    expected_key = scientific_task_arm_key(record)
    if ledger_task_arm_key != expected_key:
        raise ScientificTerminalContractError(
            "scientific result/ledger task-arm identity mismatch"
        )
    accounting = record.get("actual_accounting")
    if not isinstance(accounting, Mapping):
        raise ScientificTerminalContractError(
            "scientific result accounting is absent"
        )
    expected = {
        "actual_input_tokens": accounting.get("input_tokens"),
        "actual_model_calls": accounting.get("model_gateway_calls"),
        "actual_output_tokens": accounting.get("output_tokens"),
        "actual_decomposition_output_tokens": accounting.get(
            "actual_decomposition_output_tokens"
        ),
        "actual_solve_output_tokens": accounting.get(
            "actual_solve_output_tokens"
        ),
        "actual_extraction_output_tokens": accounting.get(
            "actual_extraction_output_tokens"
        ),
    }
    if any(type(value) is not int or value < 0 for value in expected.values()):
        raise ScientificTerminalContractError(
            "scientific result accounting projection is malformed"
        )
    if any(row.get(field) != value for field, value in expected.items()):
        raise ScientificTerminalContractError(
            "scientific result/ledger accounting projection mismatch"
        )


def validate_result_request_statuses(
    record: Mapping[str, Any],
    requests: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> None:
    """Reconcile per-request terminal outcomes with one result's semantics.

    Request accounting remains the responsibility of the ledger boundaries;
    this pure check prevents a producer-failure request from being paired with
    a clean scientific result or a successful extraction classification.
    """

    validate_scientific_terminal_result(record)
    if not isinstance(requests, (list, tuple)) or not requests:
        raise ScientificTerminalContractError(
            "scientific result has no terminal model request projection"
        )
    failed_role_counts = {"decompose": 0, "solve": 0, "extract": 0}
    role_counts = {"decompose": 0, "solve": 0, "extract": 0}
    for request in requests:
        if not isinstance(request, Mapping):
            raise ScientificTerminalContractError(
                "scientific model request projection is malformed"
            )
        status = request.get("status")
        call_kind = request.get("call_kind")
        if status not in SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES:
            raise ScientificTerminalContractError(
                "scientific model request status is nonterminal"
            )
        if call_kind not in {"decompose", "solve", "extract"}:
            raise ScientificTerminalContractError(
                "scientific model request role is malformed"
            )
        role_counts[str(call_kind)] += 1
        if status in {"PROVIDER_FAILURE", "PROVIDER_FAILURE_CONSERVATIVE"}:
            failed_role_counts[str(call_kind)] += 1

    if any(count > 1 for count in failed_role_counts.values()):
        raise ScientificTerminalContractError(
            "scientific model request role has multiple provider failures"
        )

    minimum_solve_calls = 1 if record.get("agent_completed") is True else 0
    if (
        role_counts["decompose"] != 1
        or role_counts["extract"] != 1
        or not minimum_solve_calls <= role_counts["solve"] <= 24
    ):
        raise ScientificTerminalContractError(
            "scientific model request roles contradict result completion"
        )

    if failed_role_counts["decompose"] and role_counts["solve"]:
        raise ScientificTerminalContractError(
            "decomposition request failure is followed by an impossible solve request"
        )

    provider_outcomes = record.get("provider_outcomes")
    if not isinstance(provider_outcomes, Mapping) or set(
        provider_outcomes
    ) != _PROVIDER_OUTCOME_FIELDS:
        raise ScientificTerminalContractError(
            "scientific provider outcome projection is missing or malformed"
        )
    distribution = provider_outcomes.get("provider_status_distribution")
    usage = provider_outcomes.get("provider_reported_usage")
    reservation = provider_outcomes.get("ledger_reservation")
    if (
        not isinstance(distribution, Mapping)
        or not distribution
        or not isinstance(usage, Mapping)
        or set(usage) != _PROVIDER_USAGE_FIELDS
        or not isinstance(reservation, Mapping)
        or set(reservation) != _PROVIDER_RESERVATION_FIELDS
    ):
        raise ScientificTerminalContractError(
            "scientific provider outcome projection is malformed"
        )
    for status, count in distribution.items():
        if (
            not isinstance(status, str)
            or not status
            or type(count) is not int
            or count <= 0
            or (status != "SUCCESS" and not is_scientific_gateway_failure(status))
        ):
            raise ScientificTerminalContractError(
                "scientific provider status distribution is malformed"
            )
    numeric_usage_fields = _PROVIDER_USAGE_FIELDS - {"complete"}
    if any(
        type(usage.get(field)) is not int or usage[field] < 0
        for field in numeric_usage_fields
    ) or type(usage.get("complete")) is not bool:
        raise ScientificTerminalContractError(
            "scientific provider usage projection is malformed"
        )
    if any(
        type(reservation.get(field)) is not int or reservation[field] < 0
        for field in _PROVIDER_RESERVATION_FIELDS
    ):
        raise ScientificTerminalContractError(
            "scientific provider reservation projection is malformed"
        )
    if (
        any(
            type(provider_outcomes.get(field)) is not int
            or provider_outcomes[field] < 0
            for field in (
                "incomplete_count",
                "refusal_count",
                "structured_output_schema_failure_count",
            )
        )
        or usage["cached_input_tokens"] > usage["input_tokens"]
        or usage["reasoning_tokens"] > usage["output_tokens"]
        or reservation["conservatively_charged_calls"] > reservation["calls"]
    ):
        raise ScientificTerminalContractError(
            "scientific provider derived accounting is malformed"
        )

    request_count = len(requests)
    provider_failure_count = sum(
        count
        for status, count in distribution.items()
        if is_scientific_gateway_failure(status)
    )
    failed_request_count = sum(failed_role_counts.values())
    conservative_count = sum(
        request.get("status")
        in {"SUCCESS_CONSERVATIVE_USAGE", "PROVIDER_FAILURE_CONSERVATIVE"}
        for request in requests
    )
    if (
        sum(distribution.values()) != request_count
        or usage["available_calls"] + usage["unavailable_calls"] != request_count
        or usage["complete"] is not (usage["unavailable_calls"] == 0)
        or reservation["calls"] != request_count
        or reservation["conservatively_charged_calls"] != conservative_count
        or provider_failure_count != failed_request_count
        or provider_outcomes.get("incomplete_count")
        != sum(
            count
            for status, count in distribution.items()
            if status.startswith("RESPONSE_INCOMPLETE")
        )
        or provider_outcomes.get("refusal_count")
        != distribution.get("RESPONSE_REFUSAL", 0)
        or provider_outcomes.get("structured_output_schema_failure_count")
        != distribution.get("STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0)
    ):
        raise ScientificTerminalContractError(
            "scientific provider outcomes contradict terminal requests"
        )
    accounting = record.get("actual_accounting")
    if usage["complete"] is True:
        if not isinstance(accounting, Mapping) or any(
            type(accounting.get(field)) is not int
            or accounting[field] != usage[provider_field]
            for field, provider_field in (
                ("input_tokens", "input_tokens"),
                ("cached_input_tokens", "cached_input_tokens"),
                ("output_tokens", "output_tokens"),
                ("reasoning_tokens", "reasoning_tokens"),
            )
        ):
            raise ScientificTerminalContractError(
                "scientific provider usage contradicts result accounting"
            )

    failed_roles = {role for role, count in failed_role_counts.items() if count}
    if failed_roles and record.get("cell_status") == "AGENT_COMPLETED":
        raise ScientificTerminalContractError(
            "clean scientific result has a failed model request"
        )
    if failed_roles & {"decompose", "solve"} and (
        record.get("cell_status") != "CELL_SCIENTIFIC_FAILURE"
        or record.get("agent_completed") is not False
    ):
        raise ScientificTerminalContractError(
            "pre-completion model request failure contradicts result semantics"
        )
    if "extract" in failed_roles and record.get(
        "extraction_status"
    ) != "MEMORY_EXTRACTION_FAILED":
        raise ScientificTerminalContractError(
            "extraction model request failure contradicts result semantics"
        )

    failure_class = record.get("model_failure_class")
    pre_agent_failed_roles = failed_roles & {"decompose", "solve"}
    if record.get("cell_status") == "CELL_SCIENTIFIC_FAILURE":
        if is_scientific_gateway_failure(failure_class):
            locally_derivable = failure_class in _LOCAL_POST_RESPONSE_SOLVE_FAILURES
            if (
                (not locally_derivable and len(pre_agent_failed_roles) != 1)
                or (locally_derivable and len(pre_agent_failed_roles) > 1)
                or (
                    pre_agent_failed_roles
                    and distribution.get(str(failure_class), 0) < 1
                )
                or (
                    isinstance(failure_class, str)
                    and failure_class.startswith("SOLVE_")
                    and pre_agent_failed_roles
                    and pre_agent_failed_roles != {"solve"}
                )
                or (
                    isinstance(failure_class, str)
                    and failure_class.startswith("STRUCTURED_OUTPUT_")
                    and pre_agent_failed_roles
                    and pre_agent_failed_roles != {"decompose"}
                )
            ):
                raise ScientificTerminalContractError(
                    "scientific gateway failure class contradicts request outcomes"
                )
        elif pre_agent_failed_roles:
            raise ScientificTerminalContractError(
                "runtime failure class contradicts a failed provider request"
            )
    elif record.get("cell_status") == "MEMORY_EXTRACTION_FAILED":
        if pre_agent_failed_roles:
            raise ScientificTerminalContractError(
                "post-agent extraction result has a pre-agent provider failure"
            )
        if is_scientific_gateway_failure(failure_class):
            if (
                failed_roles != {"extract"}
                or distribution.get(str(failure_class), 0) < 1
                or (
                    isinstance(failure_class, str)
                    and failure_class.startswith("SOLVE_")
                )
            ):
                raise ScientificTerminalContractError(
                    "extraction gateway failure class contradicts request outcomes"
                )
        elif isinstance(failure_class, str) and failure_class.startswith(
            "durable extraction model failure"
        ):
            if failed_roles != {"extract"}:
                raise ScientificTerminalContractError(
                    "durable extraction failure lacks a failed extraction request"
                )
        elif failed_roles:
            raise ScientificTerminalContractError(
                "local extraction failure contradicts a failed provider request"
            )


__all__ = [
    "SCIENTIFIC_ACCEPTED_GRADER_EXIT_CODES",
    "SCIENTIFIC_CELL_STATUSES",
    "SCIENTIFIC_EXECUTION_STATUS",
    "SCIENTIFIC_EXTRACTION_STATUSES",
    "SCIENTIFIC_GRADER_PATCH_SOURCES",
    "SCIENTIFIC_GRADER_STATUSES",
    "SCIENTIFIC_LEDGER_TERMINAL_STATUS",
    "SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES",
    "ScientificTerminalContractError",
    "canonical_scientific_failure_class",
    "is_scientific_failure_class",
    "is_scientific_gateway_failure",
    "is_post_agent_extraction_failure",
    "is_pre_agent_runtime_failure",
    "is_scientific_runtime_failure",
    "scientific_task_arm_key",
    "validate_result_ledger_pair",
    "validate_result_request_statuses",
    "validate_scientific_terminal_ledger_row",
    "validate_scientific_terminal_result",
]
