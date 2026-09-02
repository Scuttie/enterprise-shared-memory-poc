"""Pure fail-closed validation for protected external benchmark approvals."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping


SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")
APPROVAL_FIELDS = (
    "approved_git_commit",
    "approved_freeze_sha256",
    "approved_phase",
    "approved_task_arm_runs",
    "approved_paid_model_call_cap",
    "approved_input_token_cap",
    "approved_output_token_cap",
    "approved_currency_hard_cap",
    "approved_grader_containers",
    "approved_workflow_run_id",
    "approved_workflow_run_attempt",
    "approved_legal_terms_acceptance",
    "approval_actor",
    "approval_timestamp",
)
TOP_LEVEL_FIELDS = {
    "schema", "request_id", "approved_request_sha256", "approval",
}
CAP_BINDINGS = {
    "approved_task_arm_runs": "task_arm_runs",
    "approved_paid_model_call_cap": "paid_model_calls",
    "approved_input_token_cap": "input_tokens",
    "approved_output_token_cap": "output_tokens",
    "approved_currency_hard_cap": "total_usd",
    "approved_grader_containers": "benchmark_grader_containers",
}


class ApprovalValidationError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ApprovalValidationError(message)


def _bare_sha256(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("sha256:"):
        value = value.removeprefix("sha256:")
    return value if isinstance(value, str) and SHA256.fullmatch(value) else None


def _utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def validate_external_approval_document(
    document: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    policy_request: Mapping[str, Any],
    phase: str,
    hard_cap: Mapping[str, Any],
    request_sha256: str,
    freeze_sha256: str,
    git_head: str,
    workflow_run_id: str,
    workflow_run_attempt: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate every approval field, value, and scalar type exactly."""

    _require(set(document) == TOP_LEVEL_FIELDS, "external approval field set differs")
    _require(
        document.get("schema") == "trimem/external-exec-approval/1.0",
        "external EXEC approval schema mismatch",
    )
    _require(
        document.get("request_id") == request.get("request_id"),
        "external approval request identity mismatch",
    )
    _require(
        _bare_sha256(document.get("approved_request_sha256")) == request_sha256,
        "external approval does not bind the committed request bytes",
    )
    required = policy_request.get("required_approval_fields")
    _require(
        isinstance(required, list)
        and tuple(required) == APPROVAL_FIELDS,
        "frozen required approval field contract differs",
    )
    approval = document.get("approval")
    _require(isinstance(approval, dict), "external approval binding is missing")
    _require(set(approval) == set(APPROVAL_FIELDS), "approval binding field set differs")
    _require(
        isinstance(git_head, str)
        and HEX40.fullmatch(git_head) is not None
        and approval.get("approved_git_commit") == git_head,
        "approval Git commit differs from execution HEAD",
    )
    _require(
        _bare_sha256(approval.get("approved_freeze_sha256")) == freeze_sha256,
        "approval freeze digest differs from committed freeze",
    )
    _require(approval.get("approved_phase") == phase, "approval phase mismatch")
    _require(
        {
            "task_arm_runs", "paid_model_calls", "input_tokens", "output_tokens",
            "total_usd", "benchmark_grader_containers",
        }
        <= set(hard_cap),
        "frozen phase hard-cap fields are incomplete",
    )
    for approval_field, hard_field in CAP_BINDINGS.items():
        expected = hard_cap[hard_field]
        observed = approval.get(approval_field)
        _require(
            type(observed) is type(expected) and observed == expected,
            f"approval cap does not equal frozen proposed cap: {approval_field}",
        )
    _require(
        POSITIVE_INTEGER.fullmatch(workflow_run_id) is not None
        and POSITIVE_INTEGER.fullmatch(workflow_run_attempt) is not None,
        "exact positive workflow run ID/attempt is required",
    )
    _require(
        phase != "GRADER_SMOKE" or workflow_run_attempt == "1",
        "grader-smoke one-time recovery requires workflow run attempt 1",
    )
    _require(
        str(approval.get("approved_workflow_run_id")) == workflow_run_id,
        "approval workflow run ID differs from this dispatch",
    )
    _require(
        str(approval.get("approved_workflow_run_attempt")) == workflow_run_attempt,
        "approval workflow run attempt differs from this attempt",
    )
    _require(
        type(approval.get("approved_legal_terms_acceptance")) is bool
        and approval["approved_legal_terms_acceptance"] is True,
        "approval actor did not accept applicable benchmark/source-project terms",
    )
    _require(
        isinstance(approval.get("approval_actor"), str)
        and approval["approval_actor"].strip() == approval["approval_actor"]
        and bool(approval["approval_actor"]),
        "approval actor is missing or noncanonical",
    )
    approved_at = _utc_timestamp(approval.get("approval_timestamp"))
    _require(approved_at is not None, "approval timestamp is not an exact UTC timestamp")
    current = datetime.now(timezone.utc) if now is None else now
    _require(current.tzinfo is not None, "approval comparison time is not timezone-aware")
    _require(approved_at <= current, "approval timestamp is in the future")
    return dict(approval)


__all__ = [
    "APPROVAL_FIELDS", "ApprovalValidationError",
    "validate_external_approval_document",
]
