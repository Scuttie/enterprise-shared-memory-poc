"""Dependency-free evidence for failures before a grader-smoke cell starts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from trimem_atomic_evidence import atomic_write_bytes


SCHEMA = "trimem/grader-smoke-pre-cell-failure/1.0"
RELATIVE_PATH = "results/pre-cell-failure-evidence.json"
STAGE_TAXONOMY = {
    "EXEC_GATE": "environment_failures",
    "BENCHMARK_ENVIRONMENT_VALIDATION": "environment_failures",
    "HARNESS_PREPARATION": "infrastructure_failures",
    "CELL_PREPARATION": "infrastructure_failures",
    "IMAGE_LIFECYCLE_INITIALIZATION": "image_lifecycle_failures",
}
STAGE_FAILURE_IDENTITY = {
    "EXEC_GATE": (
        "exec_gate",
        "exec_gate_failed",
    ),
    "BENCHMARK_ENVIRONMENT_VALIDATION": (
        "benchmark_environment",
        "environment_validation_failed",
    ),
    "HARNESS_PREPARATION": (
        "harness_preparation",
        "harness_preparation_failed",
    ),
    "CELL_PREPARATION": (
        "cell_preparation",
        "cell_preparation_failed",
    ),
    "IMAGE_LIFECYCLE_INITIALIZATION": (
        "image_lifecycle_initialization",
        "image_lifecycle_initialization_failed",
    ),
}
APPROVAL_FIELDS = frozenset({
    "approval_artifact_sha256",
    "approved_request_sha256",
    "approved_workflow_run_id",
    "approved_workflow_run_attempt",
    "freeze_sha256",
    "git_head",
    "phase",
})
ZERO_EXECUTION = {
    "api_calls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "model_calls": 0,
    "model_gateway_calls": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "support_image_pulls": 0,
    "target_image_pulls": 0,
    "task_arm_runs": 0,
    "total_usd": 0,
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")


class StageEvidenceError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise StageEvidenceError(message)


def _pretty(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _validated_approval(value: Any) -> dict[str, str]:
    _require(
        isinstance(value, Mapping) and set(value) == set(APPROVAL_FIELDS),
        "pre-cell approval field set differs",
    )
    result = {field: str(value[field]) for field in APPROVAL_FIELDS}
    _require(
        result["phase"] == "GRADER_SMOKE"
        and HEX64.fullmatch(result["approval_artifact_sha256"]) is not None
        and HEX64.fullmatch(result["approved_request_sha256"]) is not None
        and POSITIVE_INTEGER.fullmatch(result["approved_workflow_run_id"]) is not None
        and result["approved_workflow_run_attempt"] == "1"
        and HEX64.fullmatch(result["freeze_sha256"]) is not None
        and HEX40.fullmatch(result["git_head"]) is not None,
        "pre-cell approval binding differs",
    )
    return result


def build_pre_cell_failure_evidence(
    *,
    approval_binding: Mapping[str, Any],
    stage: str,
    reason: str,
) -> dict[str, Any]:
    """Build a total zero-execution record at one exact caught stage boundary."""

    approval = _validated_approval(approval_binding)
    _require(stage in STAGE_TAXONOMY, "unknown pre-cell failure stage")
    _require(
        isinstance(reason, str) and reason and reason.strip() == reason,
        "pre-cell failure reason is missing or noncanonical",
    )
    failure_stage, failure_status = STAGE_FAILURE_IDENTITY[stage]
    payload = {
        "schema": SCHEMA,
        "status": "FAIL",
        "stage": stage,
        "failure_taxonomy": STAGE_TAXONOMY[stage],
        "primary_failure": {
            "stage": failure_stage,
            "status": failure_status,
            "reason": reason,
        },
        "approval_binding": approval,
        "actual_execution": dict(ZERO_EXECUTION),
    }
    return {
        **payload,
        "payload_sha256": hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    }


def validate_pre_cell_failure_evidence(value: Any) -> dict[str, Any]:
    _require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema",
            "status",
            "stage",
            "failure_taxonomy",
            "primary_failure",
            "approval_binding",
            "actual_execution",
            "payload_sha256",
        },
        "pre-cell failure evidence fields differ",
    )
    approval = _validated_approval(value.get("approval_binding"))
    stage = value.get("stage")
    _require(
        value.get("schema") == SCHEMA
        and value.get("status") == "FAIL"
        and stage in STAGE_TAXONOMY
        and value.get("failure_taxonomy") == STAGE_TAXONOMY[stage]
        and value.get("actual_execution") == ZERO_EXECUTION,
        "pre-cell failure evidence state differs",
    )
    expected_stage, expected_status = STAGE_FAILURE_IDENTITY[stage]
    primary = value.get("primary_failure")
    _require(
        isinstance(primary, dict)
        and set(primary) == {"stage", "status", "reason"}
        and primary.get("stage") == expected_stage
        and primary.get("status") == expected_status
        and isinstance(primary.get("reason"), str)
        and bool(primary["reason"])
        and primary["reason"].strip() == primary["reason"],
        "pre-cell primary failure differs from its caught stage",
    )
    payload = {
        key: child for key, child in value.items() if key != "payload_sha256"
    }
    expected_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    _require(
        isinstance(value.get("payload_sha256"), str)
        and value["payload_sha256"] == expected_hash,
        "pre-cell failure evidence seal differs",
    )
    return {**value, "approval_binding": approval}


def write_pre_cell_failure_evidence(
    output_root: Path,
    *,
    approval_binding: Mapping[str, Any],
    stage: str,
    reason: str,
) -> dict[str, Any]:
    value = build_pre_cell_failure_evidence(
        approval_binding=approval_binding,
        stage=stage,
        reason=reason,
    )
    path = output_root / "pre-cell-failure-evidence.json"
    try:
        atomic_write_bytes(path, _pretty(value))
    except FileExistsError as exc:
        raise StageEvidenceError("refusing to overwrite pre-cell failure evidence") from exc
    return value


__all__ = [
    "APPROVAL_FIELDS",
    "RELATIVE_PATH",
    "SCHEMA",
    "STAGE_TAXONOMY",
    "StageEvidenceError",
    "ZERO_EXECUTION",
    "build_pre_cell_failure_evidence",
    "validate_pre_cell_failure_evidence",
    "write_pre_cell_failure_evidence",
]
