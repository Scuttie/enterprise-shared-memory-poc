"""Pure fail-closed validation for protected external benchmark approvals."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

from enterprise_memory.providers.openai_credential import compute_openai_key_commitment


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
LEGACY_DEVELOPMENT_APPROVAL_FIELDS = (
    "approved_git_commit",
    "approved_source_git_commit",
    *APPROVAL_FIELDS[1:],
)
DEVELOPMENT_APPROVAL_FIELDS = (
    *LEGACY_DEVELOPMENT_APPROVAL_FIELDS,
    "approval_nonce",
    "approved_openai_key_commitment",
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
    source_head: str | None = None,
    workflow_run_id: str,
    workflow_run_attempt: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate every approval field, value, and scalar type exactly."""

    _require(set(document) == TOP_LEVEL_FIELDS, "external approval field set differs")
    development_request = phase == "DEVELOPMENT_TUNING"
    request_phase = request.get("phase")
    if development_request:
        _require(
            request_phase == phase,
            (
                "DEVELOPMENT_TUNING requires its exact phase-bearing request"
                if request_phase is None
                else "phase-bearing request cannot authorize a different phase"
            ),
        )
    else:
        _require(
            request_phase is None or request_phase == phase,
            "phase-bearing request cannot authorize a different phase",
        )
    required = (
        request.get("required_external_approval_fields")
        if development_request
        else policy_request.get("required_approval_fields")
    )
    new_development_contract = (
        development_request and tuple(required or ()) == DEVELOPMENT_APPROVAL_FIELDS
    )
    expected_schema = (
        "trimem/external-exec-approval/1.2"
        if new_development_contract
        else "trimem/external-exec-approval/1.1"
        if development_request
        else "trimem/external-exec-approval/1.0"
    )
    _require(
        document.get("schema") == expected_schema,
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
    expected_approval_fields = (
        DEVELOPMENT_APPROVAL_FIELDS
        if new_development_contract
        else LEGACY_DEVELOPMENT_APPROVAL_FIELDS
        if development_request
        else APPROVAL_FIELDS
    )
    _require(
        isinstance(required, list)
        and tuple(required) == expected_approval_fields,
        "frozen required approval field contract differs",
    )
    approval = document.get("approval")
    _require(isinstance(approval, dict), "external approval binding is missing")
    _require(
        set(approval) == set(expected_approval_fields),
        "approval binding field set differs",
    )
    _require(
        isinstance(git_head, str)
        and HEX40.fullmatch(git_head) is not None
        and approval.get("approved_git_commit") == git_head,
        "approval Git commit differs from execution HEAD",
    )
    if development_request:
        _require(
            isinstance(source_head, str)
            and HEX40.fullmatch(source_head) is not None
            and request.get("source_head") == source_head
            and approval.get("approved_source_git_commit") == source_head,
            "approval source Git commit differs from the DEV sentinel parent",
        )
        if new_development_contract:
            _require(
                isinstance(approval.get("approval_nonce"), str)
                and 16 <= len(approval["approval_nonce"]) <= 256
                and approval["approval_nonce"].isascii()
                and approval["approval_nonce"].isprintable()
                and approval["approval_nonce"].strip()
                == approval["approval_nonce"],
                "approval nonce is missing or noncanonical",
            )
            _require(
                isinstance(approval.get("approved_openai_key_commitment"), str)
                and SHA256.fullmatch(approval["approved_openai_key_commitment"])
                is not None,
                "approved OpenAI key commitment is invalid",
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
        phase not in {"GRADER_SMOKE", "DEVELOPMENT_TUNING"}
        or workflow_run_attempt == "1",
        "one-time phase execution requires workflow run attempt 1",
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


def build_external_approval_document(
    *,
    request_id: str,
    request_sha256: str,
    git_commit: str,
    freeze_sha256: str,
    phase: str,
    task_arm_runs: int,
    paid_model_call_cap: int,
    input_token_cap: int,
    output_token_cap: int,
    currency_hard_cap: float,
    grader_containers: int,
    workflow_run_id: int,
    workflow_run_attempt: int,
    legal_terms_acceptance: bool,
    approval_actor: str,
    approval_timestamp: str,
    source_git_commit: str | None = None,
    openai_api_key: object | None = None,
    approval_nonce: str | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    """Build canonical approval data; callers still validate before installation."""

    approval: dict[str, Any] = {
        "approved_git_commit": git_commit,
        "approved_freeze_sha256": freeze_sha256,
        "approved_phase": phase,
        "approved_task_arm_runs": task_arm_runs,
        "approved_paid_model_call_cap": paid_model_call_cap,
        "approved_input_token_cap": input_token_cap,
        "approved_output_token_cap": output_token_cap,
        "approved_currency_hard_cap": currency_hard_cap,
        "approved_grader_containers": grader_containers,
        "approved_workflow_run_id": workflow_run_id,
        "approved_workflow_run_attempt": workflow_run_attempt,
        "approved_legal_terms_acceptance": legal_terms_acceptance,
        "approval_actor": approval_actor,
        "approval_timestamp": approval_timestamp,
    }
    schema = "trimem/external-exec-approval/1.0"
    if source_git_commit is not None:
        approval["approved_source_git_commit"] = source_git_commit
        schema = "trimem/external-exec-approval/1.1"
        if openai_api_key is not None or approval_nonce is not None or model_id is not None:
            if not (
                openai_api_key is not None
                and isinstance(approval_nonce, str)
                and approval_nonce
                and isinstance(model_id, str)
                and model_id
            ):
                raise ApprovalValidationError(
                    "development credential commitment inputs are incomplete"
                )
            binding = {
                "request_id": request_id,
                "execution_head": git_commit,
                "source_head": source_git_commit,
                "workflow_run_id": str(workflow_run_id),
                "workflow_run_attempt": str(workflow_run_attempt),
                "model_id": model_id,
                "approval_nonce": approval_nonce,
            }
            approval["approval_nonce"] = approval_nonce
            approval["approved_openai_key_commitment"] = (
                compute_openai_key_commitment(openai_api_key, binding)
            )
            schema = "trimem/external-exec-approval/1.2"
    return {
        "approval": approval,
        "approved_request_sha256": request_sha256,
        "request_id": request_id,
        "schema": schema,
    }


__all__ = [
    "APPROVAL_FIELDS", "DEVELOPMENT_APPROVAL_FIELDS",
    "LEGACY_DEVELOPMENT_APPROVAL_FIELDS", "ApprovalValidationError",
    "build_external_approval_document",
    "validate_external_approval_document",
]
