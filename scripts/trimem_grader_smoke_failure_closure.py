"""Build the P0.1.5 exec-005 failure closure from restricted evidence.

The P0.1.4 receipt is an immutable historical artifact.  This module owns a
different namespace and never reads from or writes to the historical paths.
It derives lifecycle, accounting, and failure taxonomy from the actual
terminal JSON and image-lifecycle bytes before the restricted tree is
encrypted and removed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from trimem_grader_smoke import (  # noqa: E402
    FAILURE_TAXONOMY_FIELDS,
    SMOKE_ACCOUNTING_FIELDS,
    TERMINAL_CELL_FIELDS,
    TERMINAL_CELL_SCHEMA,
    failure_taxonomy,
    summarize_terminal_records,
)
from trimem_grader_smoke_trigger_preflight import (  # noqa: E402
    REQUEST_ID,
    REQUEST_SCHEMA,
    SENTINEL_PATH as EXEC_REQUEST_PATH,
)
from trimem_grader_smoke_stage_evidence import (  # noqa: E402
    RELATIVE_PATH as PRE_CELL_EVIDENCE_PATH,
    SCHEMA as PRE_CELL_EVIDENCE_SCHEMA,
    STAGE_FAILURE_IDENTITY,
    STAGE_TAXONOMY,
    ZERO_EXECUTION as PRE_CELL_ZERO_EXECUTION,
    validate_pre_cell_failure_evidence,
)
from trimem_grader_smoke_authority import (  # noqa: E402
    CAUSE_TAXONOMY as AUTHORITY_ROLLBACK_TAXONOMY,
    DEFAULT_EVIDENCE_RELATIVE_PATH as AUTHORITY_ROLLBACK_RELATIVE_PATH,
    DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH as AUTHORITY_RECOVERY_RELATIVE_PATH,
    EXPECTED_TERMINAL_RECORD_COUNT as AUTHORITY_ROLLBACK_RECORD_COUNT,
    RECOVERY_EVIDENCE_SCHEMA,
    ROLLBACK_EVIDENCE_SCHEMA,
    validate_authority_recovery_evidence,
    validate_authority_rollback_evidence,
)
from trimem_grader_smoke_finalization import (  # noqa: E402
    RELATIVE_PATH as FINALIZATION_JOURNAL_RELATIVE_PATH,
    SCIENTIFIC_AGGREGATE_REJECTED,
    validate_finalization_journal,
)
from trimem_atomic_evidence import atomic_write_bytes  # noqa: E402


FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/failure-receipt.json"
)
EVIDENCE_INVENTORY_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/evidence-inventory.json"
)
SCHEMA = "trimem/grader-smoke-failure-closure/2.0"
INVENTORY_SCHEMA = "trimem/restricted-evidence-inventory/1.0"
ADAPTER_ENDPOINT = "TRIMEM_GRADER_SMOKE_ADAPTER_CONTRACT_NOT_READY"
SCIENTIFIC_ENDPOINT = "TRIMEM_V1_GRADER_SMOKE_FAIL"
INCOMPLETE_ENDPOINT = "TRIMEM_V1_GRADER_SMOKE_INCOMPLETE"
ENDPOINTS = frozenset({ADAPTER_ENDPOINT, SCIENTIFIC_ENDPOINT, INCOMPLETE_ENDPOINT})
EXPECTED_CELL_COUNT = 12

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")
SAFE_TARGET = re.compile(r"[^A-Za-z0-9_.-]")

APPROVAL_FIELDS = frozenset({
    "approval_artifact_sha256",
    "approved_request_sha256",
    "approved_workflow_run_id",
    "approved_workflow_run_attempt",
    "freeze_sha256",
    "git_head",
    "phase",
})
REQUEST_BINDING_FIELDS = frozenset({
    "path",
    "request_id",
    "schema",
    "raw_sha256",
    "source_head",
    "matrix_order_sha256",
})
SUMMARY_FIELDS = frozenset({
    "attempted_cell_count",
    "terminal_record_count",
    "official_execution_count",
    "complete_execution_evidence_count",
    "adapter_normalized_count",
    "authoritative_cell_count",
    "unattempted_cell_count",
})
ACTUAL_EXECUTION_FIELDS = frozenset({
    "api_calls",
    "grader_containers",
    "input_tokens",
    "model_calls",
    "model_gateway_calls",
    "official_grader_runs",
    "output_tokens",
    "paid_model_calls",
    "support_image_pulls",
    "target_image_pulls",
    "task_arm_runs",
    "total_usd",
})
ZERO_ACCOUNTING_FIELDS = frozenset({
    "api_calls",
    "cached_input_tokens",
    "decomposition_calls",
    "extraction_calls",
    "input_tokens",
    "model_calls",
    "model_gateway_calls",
    "output_tokens",
    "paid_model_calls",
    "reasoning_tokens",
    "solve_calls",
    "task_arm_runs",
    "total_usd",
})
EXECUTION_EVIDENCE_FIELDS = frozenset({
    "patch_applied",
    "tests_executed",
    "digest_match",
    "submitted_patch_identity",
    "host_prepare_sh_access_count",
    "source_image_build_count",
    "api_calls",
    "container_exit_status_code",
    "container_exit_acceptance",
    "container_exit_status_sha256",
})
LIFECYCLE_BOOL_FIELDS = frozenset({
    "grader_invoked",
    "container_started",
    "harness_completed",
    "final_report_generated",
    "official_tests_executed",
    "raw_test_evidence_captured",
    "submitted_patch_identity_verified",
    "digest_verified",
    "adapter_normalized",
    "authoritative_cell",
})
TERMINAL_PROJECTION_FIELDS = frozenset({
    "schema",
    "target_id",
    "order_index",
    "probe",
    *LIFECYCLE_BOOL_FIELDS,
    "official_final_report_resolved",
    "scientific_resolved",
    "primary_failure_summary",
    "secondary_evidence_failure_summary",
    "execution_status",
    "actual_accounting",
    "execution_evidence",
    "primary_failure_taxonomy",
    "restricted_terminal_record",
})
LIFECYCLE_PROJECTION_FIELDS = frozenset({
    "status",
    "target_image_pulls",
    "support_image_pulls",
    "target_image_materialized_count",
    "support_image_materialized_count",
    "exact_image_removals",
    "max_resident_target_images",
    "max_resident_support_images",
    "resident_target_images",
    "resident_support_images",
    "failure_summary",
    "pull_attempts",
    "restricted_report",
})
PULL_ATTEMPT_FIELDS = frozenset({
    "action",
    "image",
    "outcome",
    "image_materialized",
    "pull_status",
    "pull_returncode",
    "restricted_pull_stage",
    "inspect_status",
    "inspect_returncode",
    "restricted_inspect_stage",
})
PULL_OUTCOMES = frozenset({
    "SUCCESS",
    "PULL_NONZERO",
    "PULL_TIMEOUT",
    "PULL_LAUNCH_FAILURE",
    "INSPECT_NONZERO",
    "INSPECT_TIMEOUT",
    "INSPECT_LAUNCH_FAILURE",
    "INSPECT_OUTPUT_INVALID",
    "DIGEST_MISMATCH",
})
AUTHORITY_ROLLBACK_PATH = (
    "results/" + AUTHORITY_ROLLBACK_RELATIVE_PATH.as_posix()
)
AUTHORITY_RECOVERY_PATH = (
    "results/" + AUTHORITY_RECOVERY_RELATIVE_PATH.as_posix()
)
AUTHORITY_ROLLBACK_PROJECTION_FIELDS = frozenset({
    "schema",
    "status",
    "cause_stage",
    "failure_taxonomy",
    "reason_summary",
    "terminal_record_count",
    "authority_transition",
    "records",
    "payload_sha256",
    "restricted_record",
})
AUTHORITY_RECOVERY_PROJECTION_FIELDS = frozenset({
    "schema",
    "status",
    "cause_stage",
    "failure_taxonomy",
    "reason_summary",
    "terminal_record_count",
    "canonical_state_before",
    "canonical_state_after",
    "recovery_source",
    "promotion_transaction_count",
    "rollback_transaction_count",
    "finalization_journal",
    "records",
    "payload_sha256",
    "restricted_record",
})
RECEIPT_FIELDS = frozenset({
    "schema",
    "status",
    "endpoint",
    "development_approval_allowed",
    "scientific_result",
    "request_binding",
    "approval_binding",
    "workflow_run",
    "terminal_summary",
    "terminal_records",
    "failure_taxonomy",
    "actual_execution",
    "image_lifecycle",
    "pre_cell_failure_evidence",
    "authority_rollback",
    "evidence_inventory",
    "receipt_payload_sha256",
})


class FailureClosureError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FailureClosureError(message)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


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


def _strict_json(raw: bytes, *, label: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise FailureClosureError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FailureClosureError(f"invalid JSON in {label}") from exc


def _reference(path: str, raw: bytes) -> dict[str, Any]:
    return {
        "bytes": len(raw),
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def validate_inventory(
    raw: bytes,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    value = _strict_json(raw, label=EVIDENCE_INVENTORY_PATH)
    _require(isinstance(value, dict), "exec-005 inventory root is not an object")
    _require(
        _canonical(value) + b"\n" == raw,
        "exec-005 inventory bytes are not canonical",
    )
    _require(
        set(value)
        == {"files", "inventory_sha256", "root", "schema", "total_bytes", "total_files"}
        and value.get("schema") == INVENTORY_SCHEMA
        and value.get("root") == "grader_smoke_exec",
        "exec-005 inventory identity differs",
    )
    files = value.get("files")
    _require(isinstance(files, list) and files, "exec-005 inventory is empty")
    indexed: dict[str, dict[str, Any]] = {}
    for row in files:
        _require(
            isinstance(row, dict) and set(row) == {"bytes", "path", "sha256"},
            "exec-005 inventory row fields differ",
        )
        path = row.get("path")
        digest = row.get("sha256")
        size = row.get("bytes")
        _require(
            isinstance(path, str)
            and path
            and "\\" not in path
            and not Path(path).is_absolute()
            and ".." not in Path(path).parts
            and path not in indexed
            and isinstance(digest, str)
            and HEX64.fullmatch(digest) is not None
            and type(size) is int
            and size >= 0,
            "exec-005 inventory row is malformed or duplicated",
        )
        indexed[path] = dict(row)
    _require(
        [row["path"] for row in files] == sorted(indexed),
        "exec-005 inventory rows are not path sorted",
    )
    payload = {
        "files": files,
        "root": value["root"],
        "schema": value["schema"],
        "total_bytes": sum(row["bytes"] for row in files),
        "total_files": len(files),
    }
    _require(
        value.get("total_files") == len(files)
        and value.get("total_bytes") == payload["total_bytes"]
        and value.get("inventory_sha256")
        == hashlib.sha256(_canonical(payload)).hexdigest(),
        "exec-005 inventory totals or seal differ",
    )
    return value, indexed


def _inventory_bytes(
    restricted_root: Path,
    row: Mapping[str, Any],
    *,
    label: str,
) -> bytes:
    relative = row.get("path")
    _require(isinstance(relative, str), f"{label} inventory path is invalid")
    root = restricted_root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=True)
    _require(
        root in candidate.parents and candidate.is_file() and not candidate.is_symlink(),
        f"{label} inventory path escapes or is not a regular file",
    )
    raw = candidate.read_bytes()
    _require(
        row == _reference(relative, raw),
        f"{label} bytes differ from the restricted inventory",
    )
    return raw


def _terminal_evidence_bytes(
    *,
    restricted_root: Path,
    inventory_rows: Mapping[str, Mapping[str, Any]],
    terminal_path: str,
    record: Mapping[str, Any],
) -> None:
    """Bind one failure terminal's evidence references to retained raw bytes.

    A terminal JSON is produced by the same process whose failure is being
    closed, so its lifecycle booleans cannot be treated as independent proof.
    This validator starts from the sealed inventory, dereferences every
    terminal reference, and requires the terminal's restricted-evidence list
    to cover the exact grader-private byte set for that cell.
    """

    task_prefix, separator, _name = terminal_path.rpartition("/")
    _require(bool(separator) and bool(task_prefix), "exec-005 terminal path is malformed")
    evidence = record.get("evidence")
    _require(isinstance(evidence, dict), "exec-005 terminal evidence root is missing")

    def referenced_bytes(
        reference: Any,
        *,
        prefix: str,
        label: str,
        restricted: bool = False,
    ) -> bytes:
        expected_fields = {"bytes", "path", "sha256", "access"} if restricted else {
            "bytes", "path", "sha256"
        }
        relative = reference.get("path") if isinstance(reference, dict) else None
        _require(
            isinstance(reference, dict)
            and set(reference) == expected_fields
            and isinstance(relative, str)
            and bool(relative)
            and "\\" not in relative
            and not Path(relative).is_absolute()
            and ".." not in Path(relative).parts
            and (
                not restricted
                or reference.get("access") == "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS"
            ),
            f"exec-005 {label} reference is malformed",
        )
        global_path = prefix + "/" + relative
        inventory_reference = {
            "bytes": reference["bytes"],
            "path": global_path,
            "sha256": reference["sha256"],
        }
        _require(
            inventory_rows.get(global_path) == inventory_reference,
            f"exec-005 {label} reference is not inventory-bound",
        )
        return _inventory_bytes(
            restricted_root,
            inventory_reference,
            label=label,
        )

    direct_raw: dict[str, bytes] = {}
    restricted_references = evidence.get("restricted_grader_raw")
    _require(
        isinstance(restricted_references, list),
        "exec-005 terminal restricted grader evidence list is missing",
    )
    for name, reference in evidence.items():
        if name == "restricted_grader_raw":
            continue
        direct_raw[name] = referenced_bytes(
            reference,
            prefix=task_prefix,
            label=f"terminal {name}",
        )
    _require(
        "applied_patch" in direct_raw,
        "exec-005 terminal applied-patch evidence is missing",
    )

    primary = record.get("primary_failure")
    provisional = (
        isinstance(primary, dict)
        and primary.get("stage") == "official_grader_invocation"
        and primary.get("status") == "grader_invocation_incomplete"
        and record.get("grader_invoked") is True
        and all(
            record.get(field) is False
            for field in (
                "container_started",
                "harness_completed",
                "final_report_generated",
                "official_tests_executed",
                "raw_test_evidence_captured",
                "submitted_patch_identity_verified",
                "digest_verified",
                "adapter_normalized",
                "authoritative_cell",
            )
        )
        and record.get("official_final_report_resolved") is None
        and record.get("scientific_resolved") is None
        and set(evidence) == {"applied_patch", "restricted_grader_raw"}
        and restricted_references == []
    )

    observed_restricted_paths: list[str] = []
    for index, reference in enumerate(restricted_references):
        referenced_bytes(
            reference,
            prefix=task_prefix,
            label=f"terminal restricted grader evidence {index}",
        )
        relative = str(reference["path"])
        _require(
            relative.startswith("official-grader/restricted-evidence/")
            and relative.endswith(".bin")
            and relative not in observed_restricted_paths,
            "exec-005 terminal restricted grader reference set differs",
        )
        observed_restricted_paths.append(relative)
    expected_restricted_paths = sorted(
        path.removeprefix(task_prefix + "/")
        for path in inventory_rows
        if path.startswith(task_prefix + "/official-grader/restricted-evidence/")
        and path.endswith(".bin")
    )
    if provisional:
        # The immutable pre-call terminal intentionally cannot predict which
        # private blobs a killed invocation may create.  Validate every actual
        # task-local retained byte from the sealed inventory while keeping all
        # lifecycle/outcome claims false.
        for path, row in inventory_rows.items():
            if path.startswith(task_prefix + "/") and path != terminal_path:
                _inventory_bytes(
                    restricted_root,
                    row,
                    label="provisional terminal retained evidence",
                )
    else:
        _require(
            observed_restricted_paths == expected_restricted_paths,
            "exec-005 terminal restricted grader evidence is not the exact inventory set",
        )

    report_raw = direct_raw.get("report")
    if report_raw is None:
        _require(
            record.get("final_report_generated") is False
            and record.get("raw_test_evidence_captured") is False
            and record.get("adapter_normalized") is False,
            "exec-005 terminal lifecycle claims require retained report evidence",
        )
        return
    report = _strict_json(report_raw, label=f"{terminal_path} report evidence")
    trimem = report.get("_trimem") if isinstance(report, dict) else None
    _require(
        isinstance(trimem, dict),
        "exec-005 terminal report has no TriMem evidence envelope",
    )

    nested_paths: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            path = value.get("path")
            if isinstance(path, str) and path.startswith("restricted-evidence/"):
                referenced_bytes(
                    value,
                    prefix=task_prefix + "/official-grader",
                    label="terminal canonical envelope",
                    restricted=True,
                )
                _require(
                    path not in nested_paths,
                    "exec-005 terminal canonical restricted reference is reused",
                )
                nested_paths.add(path)
                return
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(trimem)
    observed_nested = {
        path.removeprefix("official-grader/") for path in observed_restricted_paths
    }
    _require(
        nested_paths <= observed_nested,
        "exec-005 terminal canonical references escape its restricted evidence list",
    )
    if record.get("final_report_generated") is True:
        _require(
            isinstance(trimem.get("restricted_raw_report"), dict),
            "exec-005 final-report lifecycle claim lacks retained raw report",
        )
    if record.get("raw_test_evidence_captured") is True:
        _require(
            all(
                isinstance(trimem.get(name), dict)
                for name in ("test_output", "official_test_status")
            ),
            "exec-005 raw-test lifecycle claim lacks retained test evidence",
        )


def _request(raw: bytes) -> tuple[dict[str, Any], list[str]]:
    value = _strict_json(raw, label=EXEC_REQUEST_PATH)
    _require(isinstance(value, dict), "exec-005 request root is not an object")
    order = value.get("matrix_order")
    _require(
        value.get("schema") == REQUEST_SCHEMA
        and value.get("request_id") == REQUEST_ID
        and isinstance(value.get("source_head"), str)
        and HEX40.fullmatch(value["source_head"]) is not None
        and isinstance(order, list)
        and len(order) == EXPECTED_CELL_COUNT
        and len(set(order)) == EXPECTED_CELL_COUNT
        and all(isinstance(item, str) and item for item in order),
        "exec-005 request identity or matrix differs",
    )
    return value, list(order)


def _request_binding(value: Mapping[str, Any], raw: bytes) -> dict[str, Any]:
    order = value["matrix_order"]
    return {
        "path": EXEC_REQUEST_PATH,
        "request_id": value["request_id"],
        "schema": value["schema"],
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "source_head": value["source_head"],
        "matrix_order_sha256": hashlib.sha256(_canonical(order)).hexdigest(),
    }


def _validated_approval(
    value: Mapping[str, Any], *, request_raw: bytes
) -> dict[str, str]:
    _require(set(value) == set(APPROVAL_FIELDS), "exec-005 approval field set differs")
    result = {field: str(value.get(field, "")) for field in APPROVAL_FIELDS}
    _require(
        result["phase"] == "GRADER_SMOKE"
        and HEX64.fullmatch(result["approval_artifact_sha256"]) is not None
        and HEX64.fullmatch(result["approved_request_sha256"]) is not None
        and result["approved_request_sha256"] == hashlib.sha256(request_raw).hexdigest()
        and POSITIVE_INTEGER.fullmatch(result["approved_workflow_run_id"]) is not None
        and result["approved_workflow_run_attempt"] == "1"
        and HEX64.fullmatch(result["freeze_sha256"]) is not None
        and HEX40.fullmatch(result["git_head"]) is not None,
        "exec-005 approval binding differs",
    )
    return result


def _validated_workflow(
    value: Mapping[str, Any], approval: Mapping[str, str]
) -> dict[str, Any]:
    _require(
        set(value) == {"id", "run_attempt", "head_sha", "conclusion"}
        and str(value.get("id")) == approval["approved_workflow_run_id"]
        and value.get("run_attempt") == 1
        and value.get("head_sha") == approval["git_head"]
        and value.get("conclusion") in {"failure", "cancelled", "timed_out"},
        "exec-005 workflow binding differs",
    )
    return dict(value)


def _primary_failure(value: Any, *, label: str) -> dict[str, str] | None:
    if value is None:
        return None
    _require(
        isinstance(value, dict)
        and set(value) == {"stage", "status", "reason"}
        and all(isinstance(value.get(field), str) and value[field] for field in value),
        f"{label} primary failure is malformed",
    )
    return {field: value[field] for field in ("stage", "status", "reason")}


def _text_summary(value: str) -> dict[str, Any]:
    raw = value.encode("utf-8")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _primary_failure_summary(
    value: Mapping[str, str] | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "stage": value["stage"],
        "status": value["status"],
        "reason": _text_summary(value["reason"]),
    }


def _secondary_failure_summary(values: list[str]) -> dict[str, Any]:
    return {
        "count": len(values),
        "items": [_text_summary(value) for value in values],
        "canonical_sha256": hashlib.sha256(_canonical(values)).hexdigest(),
    }


def _opaque_json_summary(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {"present": False, "bytes": 0, "sha256": None}
    raw = _canonical(value)
    return {
        "present": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _validate_text_summary(value: Any, *, label: str) -> dict[str, Any]:
    _require(
        isinstance(value, dict)
        and set(value) == {"bytes", "sha256"}
        and type(value.get("bytes")) is int
        and value["bytes"] > 0
        and isinstance(value.get("sha256"), str)
        and HEX64.fullmatch(value["sha256"]) is not None,
        f"{label} digest summary differs",
    )
    return dict(value)


def _validate_primary_failure_summary(
    value: Any, *, label: str
) -> dict[str, Any] | None:
    if value is None:
        return None
    _require(
        isinstance(value, dict)
        and set(value) == {"stage", "status", "reason"}
        and isinstance(value.get("stage"), str)
        and bool(value["stage"])
        and isinstance(value.get("status"), str)
        and bool(value["status"]),
        f"{label} primary summary differs",
    )
    reason = _validate_text_summary(value.get("reason"), label=f"{label} reason")
    return {"stage": value["stage"], "status": value["status"], "reason": reason}


def _validate_secondary_failure_summary(value: Any, *, label: str) -> dict[str, Any]:
    _require(
        isinstance(value, dict)
        and set(value) == {"count", "items", "canonical_sha256"}
        and type(value.get("count")) is int
        and value["count"] >= 0
        and isinstance(value.get("items"), list)
        and len(value["items"]) == value["count"]
        and isinstance(value.get("canonical_sha256"), str)
        and HEX64.fullmatch(value["canonical_sha256"]) is not None,
        f"{label} secondary summary differs",
    )
    items = [
        _validate_text_summary(item, label=f"{label} item")
        for item in value["items"]
    ]
    return {
        "count": value["count"],
        "items": items,
        "canonical_sha256": value["canonical_sha256"],
    }


def _terminal_record(value: Any, *, index: int, target_id: str) -> dict[str, Any]:
    label = f"exec-005 terminal record {index}"
    _require(
        isinstance(value, dict)
        and TERMINAL_CELL_FIELDS.issubset(value)
        and value.get("schema") == TERMINAL_CELL_SCHEMA,
        f"{label} schema/field set differs",
    )
    expected_probe = "GOLD" if index % 2 == 0 else "NOOP_BASELINE"
    _require(
        value.get("target_id") == target_id
        and value.get("order_index") == index
        and value.get("probe") == expected_probe
        and all(type(value.get(field)) is bool for field in LIFECYCLE_BOOL_FIELDS),
        f"{label} identity or lifecycle differs",
    )
    primary = _primary_failure(value.get("primary_failure"), label=label)
    secondary = value.get("secondary_evidence_failures")
    scientific_resolved = value.get("scientific_resolved")
    official_resolved = value.get("official_final_report_resolved")
    scientific_mismatch = (
        primary is not None
        and primary["stage"] == "scientific_outcome"
        and value.get("adapter_normalized") is True
        and value.get("authoritative_cell") is False
        and value.get("execution_status") == "FAILURE"
        and type(official_resolved) is bool
        and type(scientific_resolved) is bool
        and scientific_resolved is official_resolved
    )
    _require(
        isinstance(secondary, list)
        and all(isinstance(item, str) and item for item in secondary)
        and isinstance(value.get("execution_status"), str)
        and bool(value["execution_status"])
        and type(official_resolved) in {bool, type(None)}
        and type(scientific_resolved) in {bool, type(None)}
        and (
            primary is None
            or scientific_resolved is None
            or scientific_mismatch
        ),
        f"{label} outcome/failure fields differ",
    )
    accounting = value.get("actual_accounting")
    _require(
        isinstance(accounting, dict)
        and set(accounting) == set(SMOKE_ACCOUNTING_FIELDS)
        and all(type(item) is int and item >= 0 for item in accounting.values())
        and all(accounting[field] == 0 for field in ZERO_ACCOUNTING_FIELDS)
        and accounting["grader_calls"] == int(value["grader_invoked"])
        and accounting["grader_containers"] == int(value["container_started"])
        and accounting["official_grader_runs"] == int(value["container_started"]),
        f"{label} actual accounting differs from lifecycle",
    )
    execution = value.get("execution_evidence")
    _require(
        isinstance(execution, dict)
        and set(execution) == set(EXECUTION_EVIDENCE_FIELDS)
        and all(
            type(execution.get(field)) is bool
            for field in (
                "patch_applied",
                "tests_executed",
                "digest_match",
                "submitted_patch_identity",
            )
        )
        and all(
            type(execution.get(field)) is int and execution[field] >= 0
            for field in (
                "host_prepare_sh_access_count",
                "source_image_build_count",
                "api_calls",
            )
        )
        and (
            value.get("adapter_normalized") is True
            or (
                execution.get("patch_applied") is False
                and execution.get("tests_executed") is False
            )
        ),
        f"{label} execution evidence differs",
    )
    return dict(value)


def _taxonomy_name(record: Mapping[str, Any]) -> str | None:
    counts = failure_taxonomy([record])
    names = [name for name, count in counts.items() if count]
    _require(len(names) <= 1, "terminal primary failure has ambiguous taxonomy")
    return names[0] if names else None


def _terminal_projection(
    record: Mapping[str, Any], reference: Mapping[str, Any]
) -> dict[str, Any]:
    projected = {
        field: record[field]
        for field in TERMINAL_CELL_FIELDS
        if field not in {"evidence", "primary_failure", "secondary_evidence_failures"}
    }
    projected["primary_failure_summary"] = _primary_failure_summary(
        record["primary_failure"]
    )
    projected["secondary_evidence_failure_summary"] = _secondary_failure_summary(
        record["secondary_evidence_failures"]
    )
    projected["primary_failure_taxonomy"] = _taxonomy_name(record)
    projected["restricted_terminal_record"] = dict(reference)
    _require(
        set(projected) == set(TERMINAL_PROJECTION_FIELDS),
        "terminal public projection field drift",
    )
    return projected


def _projection_record(value: Any, *, index: int, target_id: str) -> dict[str, Any]:
    _require(
        isinstance(value, dict) and set(value) == set(TERMINAL_PROJECTION_FIELDS),
        f"exec-005 terminal projection {index} fields differ",
    )
    record = {
        field: value[field]
        for field in TERMINAL_CELL_FIELDS
        if field not in {"evidence", "primary_failure", "secondary_evidence_failures"}
    }
    primary_summary = _validate_primary_failure_summary(
        value.get("primary_failure_summary"),
        label=f"exec-005 terminal projection {index}",
    )
    secondary_summary = _validate_secondary_failure_summary(
        value.get("secondary_evidence_failure_summary"),
        label=f"exec-005 terminal projection {index}",
    )
    record["primary_failure"] = (
        None
        if primary_summary is None
        else {
            "stage": primary_summary["stage"],
            "status": primary_summary["status"],
            "reason": "RESTRICTED_REASON_SHA256:" + primary_summary["reason"]["sha256"],
        }
    )
    record["secondary_evidence_failures"] = [
        "RESTRICTED_SECONDARY_SHA256:" + item["sha256"]
        for item in secondary_summary["items"]
    ]
    record["evidence"] = {}
    record = _terminal_record(record, index=index, target_id=target_id)
    _require(
        value.get("primary_failure_taxonomy") == _taxonomy_name(record),
        f"exec-005 terminal projection {index} taxonomy differs",
    )
    reference = value.get("restricted_terminal_record")
    _require(
        isinstance(reference, dict)
        and set(reference) == {"bytes", "path", "sha256"},
        f"exec-005 terminal projection {index} reference differs",
    )
    return record


def _image_stage(
    *,
    restricted_root: Path,
    inventory_rows: Mapping[str, Mapping[str, Any]],
    operation: str,
    stage_name: str,
    image: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    path = f"image-materialization/{operation}-{stage_name}/stage.json"
    reference = inventory_rows.get(path)
    _require(
        isinstance(reference, dict),
        f"exec-005 image {stage_name} stage is absent",
    )
    raw = _inventory_bytes(
        restricted_root, reference, label=f"image {stage_name} stage {operation}"
    )
    stage = _strict_json(raw, label=path)
    expected_argv = (
        ["docker", "pull", image]
        if stage_name == "pull"
        else [
            "docker", "image", "inspect", "--format",
            "{{json .RepoDigests}}", image,
        ]
    )
    _require(
        isinstance(stage, dict)
        and set(stage)
        == {"argv", "returncode", "stage", "status", "stdout", "stderr"}
        and stage.get("stage") == stage_name
        and stage.get("argv") == expected_argv
        and stage.get("status")
        in {"PASS", "NONZERO", "TIMEOUT", "LAUNCH_FAILURE"}
        and type(stage.get("returncode")) in {int, type(None)}
        and (
            (stage["status"] == "PASS" and stage["returncode"] == 0)
            or (
                stage["status"] == "NONZERO"
                and type(stage["returncode"]) is int
                and stage["returncode"] != 0
            )
            or (
                stage["status"] in {"TIMEOUT", "LAUNCH_FAILURE"}
                and stage["returncode"] is None
            )
        ),
        f"exec-005 image {stage_name} stage is malformed",
    )
    streams: dict[str, bytes] = {}
    for stream_name in ("stdout", "stderr"):
        stream_reference = stage[stream_name]
        expected_relative = f"{operation}-{stage_name}/{stream_name}.txt"
        global_stream_reference = (
            {
                **stream_reference,
                "path": "image-materialization/" + str(stream_reference.get("path")),
            }
            if isinstance(stream_reference, dict)
            else None
        )
        _require(
            isinstance(stream_reference, dict)
            and set(stream_reference) == {"bytes", "path", "sha256"}
            and stream_reference.get("path") == expected_relative
            and isinstance(global_stream_reference, dict)
            and inventory_rows.get(global_stream_reference.get("path"))
            == global_stream_reference,
            f"exec-005 image {stage_name} {stream_name} is not inventory-bound",
        )
        streams[stream_name] = _inventory_bytes(
            restricted_root,
            global_stream_reference,
            label=f"image {stage_name} {operation} {stream_name}",
        )
    return stage, dict(reference), streams


def _inspect_pass_outcome(raw: bytes, *, image: str) -> str:
    try:
        repo_digests = _strict_json(raw, label="Docker image inspect stdout")
    except FailureClosureError:
        return "INSPECT_OUTPUT_INVALID"
    if (
        not isinstance(repo_digests, list)
        or not repo_digests
        or any(
            type(value) is not str
            or not value
            or "@sha256:" not in value
            for value in repo_digests
        )
        or len(repo_digests) != len(set(repo_digests))
    ):
        return "INSPECT_OUTPUT_INVALID"
    expected = image.rsplit("@", 1)[1]
    observed = {value.rsplit("@", 1)[-1] for value in repo_digests}
    return "SUCCESS" if expected in observed else "DIGEST_MISMATCH"


def _pull_attempt_projections(
    restricted_root: Path,
    inventory_rows: Mapping[str, Mapping[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    path_pattern = re.compile(
        r"image-materialization/(?P<operation>[0-9]{3})-pull/stage\.json"
    )
    paths = sorted(path for path in inventory_rows if path_pattern.fullmatch(path))
    pull_evidence_paths = {
        path
        for path in inventory_rows
        if re.fullmatch(
            r"image-materialization/[0-9]{3}-pull/(?:stage\.json|stdout\.txt|stderr\.txt)",
            path,
        )
    }
    inspect_paths = {
        path
        for path in inventory_rows
        if re.fullmatch(
            r"image-materialization/[0-9]{3}-inspect/stage\.json", path
        )
    }
    inspect_evidence_paths = {
        path
        for path in inventory_rows
        if re.fullmatch(
            r"image-materialization/[0-9]{3}-inspect/(?:stage\.json|stdout\.txt|stderr\.txt)",
            path,
        )
    }
    pull_events = [
        event
        for event in events
        if event.get("action")
        in {"PULL_TARGET", "PULL_TARGET_FAILED", "PULL_SUPPORT", "PULL_SUPPORT_FAILED"}
    ]
    _require(
        len(paths) == len(pull_events),
        "exec-005 pull stage/event count differs",
    )
    consumed_inspect_paths: set[str] = set()
    consumed_pull_evidence_paths: set[str] = set()
    consumed_inspect_evidence_paths: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, (path, event) in enumerate(zip(paths, pull_events, strict=True)):
        match = path_pattern.fullmatch(path)
        if match is None:  # pragma: no cover - guarded by the comprehension
            raise AssertionError("pull path escaped its exact pattern")
        operation = match.group("operation")
        action = str(event["action"])
        failed = action.endswith("_FAILED")
        record = event.get("record")
        image = (
            event.get("image")
            if failed
            else record.get("image") if isinstance(record, dict) else None
        )
        _require(
            isinstance(image, str) and "@sha256:" in image,
            "exec-005 image pull lifecycle event has no frozen image",
        )
        pull, pull_reference, _pull_streams = _image_stage(
            restricted_root=restricted_root,
            inventory_rows=inventory_rows,
            operation=operation,
            stage_name="pull",
            image=image,
        )
        consumed_pull_evidence_paths.update({
            f"image-materialization/{operation}-pull/stage.json",
            f"image-materialization/{operation}-pull/stdout.txt",
            f"image-materialization/{operation}-pull/stderr.txt",
        })
        image_materialized = pull["status"] == "PASS"
        inspect: dict[str, Any] | None = None
        inspect_reference: dict[str, Any] | None = None
        inspect_outcome: str | None = None
        inspect_path = f"image-materialization/{operation}-inspect/stage.json"
        if image_materialized:
            inspect, inspect_reference, inspect_streams = _image_stage(
                restricted_root=restricted_root,
                inventory_rows=inventory_rows,
                operation=operation,
                stage_name="inspect",
                image=image,
            )
            consumed_inspect_paths.add(inspect_path)
            consumed_inspect_evidence_paths.update({
                f"image-materialization/{operation}-inspect/stage.json",
                f"image-materialization/{operation}-inspect/stdout.txt",
                f"image-materialization/{operation}-inspect/stderr.txt",
            })
            inspect_outcome = (
                _inspect_pass_outcome(inspect_streams["stdout"], image=image)
                if inspect["status"] == "PASS"
                else "INSPECT_" + inspect["status"]
            )
            outcome = inspect_outcome
        else:
            _require(
                inspect_path not in inspect_paths,
                "exec-005 image inspect ran after a failed pull",
            )
            outcome = "PULL_" + pull["status"]

        if outcome == "SUCCESS":
            expected_failure_stage = None
        elif outcome.startswith("PULL_"):
            expected_failure_stage = "PULL"
        elif outcome in {
            "INSPECT_NONZERO", "INSPECT_TIMEOUT", "INSPECT_LAUNCH_FAILURE"
        }:
            expected_failure_stage = "INSPECT"
        elif outcome == "INSPECT_OUTPUT_INVALID":
            expected_failure_stage = "INSPECT_OUTPUT"
        else:
            expected_failure_stage = "DIGEST_VERIFICATION"
        if failed:
            _require(
                set(event)
                == {
                    "action", "identity", "image", "pull_materialized",
                    "failure_stage", "error_type", "error",
                }
                and outcome != "SUCCESS"
                and event.get("pull_materialized") is image_materialized
                and event.get("failure_stage") == expected_failure_stage
                and isinstance(event.get("identity"), str)
                and bool(event["identity"])
                and isinstance(event.get("error_type"), str)
                and bool(event["error_type"])
                and isinstance(event.get("error"), str)
                and bool(event["error"]),
                "exec-005 failed image lifecycle event differs from stage evidence",
            )
        else:
            _require(
                set(event) == {"action", "identity", "record"}
                and outcome == "SUCCESS"
                and isinstance(record, dict)
                and set(record)
                == {
                    "image", "expected_digest", "observed_digests", "pull", "inspect"
                }
                and record.get("expected_digest") == image.rsplit("@", 1)[1]
                and isinstance(record.get("observed_digests"), list)
                and record["observed_digests"]
                == sorted(set(record["observed_digests"]))
                and record["expected_digest"] in record["observed_digests"]
                and record.get("pull")
                == {"stdout": pull["stdout"], "stderr": pull["stderr"]}
                and record.get("inspect")
                == {"stdout": inspect["stdout"], "stderr": inspect["stderr"]},
                "exec-005 successful image lifecycle event differs from stage evidence",
            )
        result.append({
            "action": action.removesuffix("_FAILED"),
            "image": image,
            "outcome": outcome,
            "image_materialized": image_materialized,
            "pull_status": pull["status"],
            "pull_returncode": pull["returncode"],
            "restricted_pull_stage": pull_reference,
            "inspect_status": None if inspect is None else inspect["status"],
            "inspect_returncode": None if inspect is None else inspect["returncode"],
            "restricted_inspect_stage": inspect_reference,
        })
    _require(
        consumed_inspect_paths == inspect_paths,
        "exec-005 image inspect stage set differs from successful pull stages",
    )
    _require(
        consumed_pull_evidence_paths == pull_evidence_paths
        and consumed_inspect_evidence_paths == inspect_evidence_paths,
        "exec-005 image pull/inspect raw evidence set contains an orphan",
    )
    return result


def _lifecycle_projection(
    raw: bytes,
    *,
    reference: Mapping[str, Any],
    approval: Mapping[str, str],
    restricted_root: Path,
    inventory_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    value = _strict_json(raw, label=str(reference.get("path")))
    _require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema",
            "status",
            "phase",
            "approval_artifact_sha256",
            "git_head",
            "expected",
            "actual",
            "failure",
            "events",
        }
        and value.get("schema") == "trimem/grader-smoke-image-lifecycle/1.0"
        and value.get("phase") == "GRADER_SMOKE"
        and value.get("approval_artifact_sha256")
        == approval["approval_artifact_sha256"]
        and value.get("git_head") == approval["git_head"]
        and value.get("status")
        in {"IN_PROGRESS", "FAILED", "CLEANUP_FAILED", "PASS"},
        "exec-005 image lifecycle identity differs",
    )
    actual = value.get("actual")
    expected = value.get("expected")
    events = value.get("events")
    actual_fields = {
        "target_image_pulls",
        "support_image_pulls",
        "exact_image_removals",
        "max_resident_target_images",
        "max_resident_support_images",
        "resident_target_images",
        "resident_support_images",
    }
    _require(
        isinstance(actual, dict)
        and set(actual) == actual_fields
        and all(type(item) is int and item >= 0 for item in actual.values())
        and isinstance(expected, dict)
        and set(expected)
        == {
            "target_image_pulls",
            "support_image_pulls",
            "exact_image_removals",
            "max_resident_target_images",
            "max_resident_support_images",
        }
        and expected
        == {
            "target_image_pulls": 6,
            "support_image_pulls": 1,
            "exact_image_removals": 7,
            "max_resident_target_images": 1,
            "max_resident_support_images": 1,
        }
        and isinstance(events, list)
        and all(isinstance(event, dict) for event in events),
        "exec-005 image lifecycle counters differ",
    )
    _require(
        actual["target_image_pulls"]
        == sum(
            event.get("action") == "PULL_TARGET"
            or (
                event.get("action") == "PULL_TARGET_FAILED"
                and event.get("pull_materialized") is True
            )
            for event in events
        )
        and actual["support_image_pulls"]
        == sum(
            event.get("action") == "PULL_SUPPORT"
            or (
                event.get("action") == "PULL_SUPPORT_FAILED"
                and event.get("pull_materialized") is True
            )
            for event in events
        )
        and actual["exact_image_removals"]
        == sum(
            event.get("action") in {"REMOVE_TARGET", "REMOVE_SUPPORT"}
            for event in events
        )
        and actual["target_image_pulls"] <= 6
        and actual["support_image_pulls"] <= 1
        and actual["max_resident_target_images"] <= 1
        and actual["max_resident_support_images"] <= 1
        and actual["resident_target_images"] <= 1
        and actual["resident_support_images"] <= 1,
        "exec-005 image lifecycle values are not event-derived",
    )
    failure = value.get("failure")
    _require(
        failure is None or isinstance(failure, dict),
        "exec-005 image lifecycle failure is malformed",
    )
    if value["status"] == "PASS":
        _require(
            actual
            == {
                **expected,
                "resident_target_images": 0,
                "resident_support_images": 0,
            }
            and failure is None,
            "exec-005 passed image lifecycle is not complete and clean",
        )
    pull_attempts = _pull_attempt_projections(
        restricted_root, inventory_rows, events
    )
    target_attempts = sum(row["action"] == "PULL_TARGET" for row in pull_attempts)
    support_attempts = sum(row["action"] == "PULL_SUPPORT" for row in pull_attempts)
    _require(
        actual["target_image_pulls"]
        == sum(
            row["action"] == "PULL_TARGET" and row["image_materialized"] is True
            for row in pull_attempts
        )
        and actual["support_image_pulls"]
        == sum(
            row["action"] == "PULL_SUPPORT" and row["image_materialized"] is True
            for row in pull_attempts
        ),
        "exec-005 materialized image count differs from pull stages",
    )
    _require(
        target_attempts <= 6 and support_attempts <= 1,
        "exec-005 image pull attempts exceed the frozen campaign",
    )
    result = {
        "status": value["status"],
        "target_image_pulls": target_attempts,
        "support_image_pulls": support_attempts,
        "target_image_materialized_count": actual["target_image_pulls"],
        "support_image_materialized_count": actual["support_image_pulls"],
        **{
            field: actual[field]
            for field in (
                "exact_image_removals",
                "max_resident_target_images",
                "max_resident_support_images",
                "resident_target_images",
                "resident_support_images",
            )
        },
        "failure_summary": _opaque_json_summary(failure),
        "pull_attempts": pull_attempts,
        "restricted_report": dict(reference),
    }
    _require(
        set(result) == set(LIFECYCLE_PROJECTION_FIELDS),
        "image lifecycle public projection field drift",
    )
    return result


def _valid_stage_status(status: Any, returncode: Any) -> bool:
    return (
        status in {"PASS", "NONZERO", "TIMEOUT", "LAUNCH_FAILURE"}
        and type(returncode) in {int, type(None)}
        and (
            (status == "PASS" and returncode == 0)
            or (status == "NONZERO" and type(returncode) is int and returncode != 0)
            or (
                status in {"TIMEOUT", "LAUNCH_FAILURE"}
                and returncode is None
            )
        )
    )


def _valid_pull_attempt_projection(row: Any) -> bool:
    if (
        not isinstance(row, dict)
        or set(row) != set(PULL_ATTEMPT_FIELDS)
        or row.get("action") not in {"PULL_TARGET", "PULL_SUPPORT"}
        or not isinstance(row.get("image"), str)
        or "@sha256:" not in row["image"]
        or row.get("outcome") not in PULL_OUTCOMES
        or type(row.get("image_materialized")) is not bool
        or not _valid_stage_status(
            row.get("pull_status"), row.get("pull_returncode")
        )
        or not isinstance(row.get("restricted_pull_stage"), dict)
        or set(row["restricted_pull_stage"]) != {"bytes", "path", "sha256"}
    ):
        return False
    pull_passed = row["pull_status"] == "PASS"
    if row["image_materialized"] is not pull_passed:
        return False
    if not pull_passed:
        return (
            row["outcome"] == "PULL_" + row["pull_status"]
            and row.get("inspect_status") is None
            and row.get("inspect_returncode") is None
            and row.get("restricted_inspect_stage") is None
        )
    if (
        not _valid_stage_status(
            row.get("inspect_status"), row.get("inspect_returncode")
        )
        or not isinstance(row.get("restricted_inspect_stage"), dict)
        or set(row["restricted_inspect_stage"]) != {"bytes", "path", "sha256"}
    ):
        return False
    if row["inspect_status"] != "PASS":
        return row["outcome"] == "INSPECT_" + row["inspect_status"]
    return row["outcome"] in {
        "SUCCESS", "INSPECT_OUTPUT_INVALID", "DIGEST_MISMATCH"
    }


def _validate_lifecycle_projection(value: Any) -> dict[str, Any]:
    _require(
        isinstance(value, dict) and set(value) == set(LIFECYCLE_PROJECTION_FIELDS),
        "exec-005 image lifecycle projection fields differ",
    )
    for field in (
        "target_image_pulls",
        "support_image_pulls",
        "target_image_materialized_count",
        "support_image_materialized_count",
        "exact_image_removals",
        "max_resident_target_images",
        "max_resident_support_images",
        "resident_target_images",
        "resident_support_images",
    ):
        _require(
            type(value.get(field)) is int and value[field] >= 0,
            "exec-005 image lifecycle projection counter differs",
        )
    attempts = value.get("pull_attempts")
    _require(
        isinstance(attempts, list)
        and all(_valid_pull_attempt_projection(row) for row in attempts)
        and value["target_image_pulls"]
        == sum(row["action"] == "PULL_TARGET" for row in attempts)
        and value["support_image_pulls"]
        == sum(row["action"] == "PULL_SUPPORT" for row in attempts)
        and value["target_image_pulls"] <= 6
        and value["support_image_pulls"] <= 1
        and value["target_image_materialized_count"]
        == sum(
            row["action"] == "PULL_TARGET" and row["image_materialized"] is True
            for row in attempts
        )
        and value["support_image_materialized_count"]
        == sum(
            row["action"] == "PULL_SUPPORT" and row["image_materialized"] is True
            for row in attempts
        ),
        "exec-005 image pull projection is not stage-derived",
    )
    failure_summary = value.get("failure_summary")
    _require(
        isinstance(failure_summary, dict)
        and set(failure_summary) == {"present", "bytes", "sha256"}
        and type(failure_summary.get("present")) is bool
        and type(failure_summary.get("bytes")) is int
        and failure_summary["bytes"] >= 0
        and (
            (
                failure_summary["present"]
                and failure_summary["bytes"] > 0
                and isinstance(failure_summary.get("sha256"), str)
                and HEX64.fullmatch(failure_summary["sha256"]) is not None
            )
            or (
                not failure_summary["present"]
                and failure_summary["bytes"] == 0
                and failure_summary.get("sha256") is None
            )
        ),
        "exec-005 image lifecycle failure summary differs",
    )
    reference = value.get("restricted_report")
    not_started = value.get("status") == "NOT_STARTED"
    _require(
        value.get("status")
        in {"NOT_STARTED", "IN_PROGRESS", "FAILED", "CLEANUP_FAILED", "PASS"}
        and (
            (not_started and reference is None)
            or (
                not not_started
                and isinstance(reference, dict)
                and set(reference) == {"bytes", "path", "sha256"}
            )
        )
        and (
            not not_started
            or all(
                value[field] == 0
                for field in (
                    "target_image_pulls",
                    "support_image_pulls",
                    "target_image_materialized_count",
                    "support_image_materialized_count",
                    "exact_image_removals",
                    "max_resident_target_images",
                    "max_resident_support_images",
                    "resident_target_images",
                    "resident_support_images",
                )
            )
            and not attempts
        ),
        "exec-005 image lifecycle projection state differs",
    )
    if value["status"] == "PASS":
        _require(
            value["target_image_pulls"] == 6
            and value["support_image_pulls"] == 1
            and value["target_image_materialized_count"] == 6
            and value["support_image_materialized_count"] == 1
            and value["exact_image_removals"] == 7
            and value["resident_target_images"] == 0
            and value["resident_support_images"] == 0
            and failure_summary
            == {"present": False, "bytes": 0, "sha256": None},
            "exec-005 public passed image lifecycle is incomplete",
        )
    return dict(value)


def _pre_cell_projection(
    raw: bytes,
    *,
    reference: Mapping[str, Any],
    approval: Mapping[str, str],
) -> dict[str, Any]:
    value = _strict_json(raw, label=str(reference.get("path")))
    _require(
        isinstance(value, dict) and _pretty(value) == raw,
        "exec-005 pre-cell evidence bytes are not canonical",
    )
    try:
        validated = validate_pre_cell_failure_evidence(value)
    except ValueError as exc:
        raise FailureClosureError(
            f"exec-005 pre-cell failure evidence did not validate: {exc}"
        ) from exc
    _require(
        validated["approval_binding"] == approval,
        "exec-005 pre-cell approval binding differs",
    )
    return {
        "schema": validated["schema"],
        "status": validated["status"],
        "stage": validated["stage"],
        "failure_taxonomy": validated["failure_taxonomy"],
        "primary_failure_summary": _primary_failure_summary(
            validated["primary_failure"]
        ),
        "actual_execution": validated["actual_execution"],
        "payload_sha256": validated["payload_sha256"],
        "restricted_record": dict(reference),
    }


def _validate_pre_cell_projection(
    value: Any,
    *,
    approval: Mapping[str, str],
) -> dict[str, Any] | None:
    if value is None:
        return None
    _require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema",
            "status",
            "stage",
            "failure_taxonomy",
            "primary_failure_summary",
            "actual_execution",
            "payload_sha256",
            "restricted_record",
        },
        "exec-005 pre-cell public projection fields differ",
    )
    stage = value.get("stage")
    primary = _validate_primary_failure_summary(
        value.get("primary_failure_summary"), label="exec-005 pre-cell"
    )
    expected_failure_stage, expected_failure_status = STAGE_FAILURE_IDENTITY.get(
        str(stage), (None, None)
    )
    _require(
        value.get("schema") == PRE_CELL_EVIDENCE_SCHEMA
        and value.get("status") == "FAIL"
        and stage in STAGE_TAXONOMY
        and value.get("failure_taxonomy") == STAGE_TAXONOMY[stage]
        and value.get("actual_execution") == PRE_CELL_ZERO_EXECUTION
        and isinstance(value.get("payload_sha256"), str)
        and HEX64.fullmatch(value["payload_sha256"]) is not None
        and primary is not None
        and primary["stage"] == expected_failure_stage
        and primary["status"] == expected_failure_status,
        "exec-005 pre-cell public stage contract differs",
    )
    reference = value.get("restricted_record")
    _require(
        isinstance(reference, dict)
        and set(reference) == {"bytes", "path", "sha256"}
        and reference.get("path") == PRE_CELL_EVIDENCE_PATH,
        "exec-005 pre-cell public reference differs",
    )
    return dict(value)


def _authority_rollback_projection(
    raw: bytes,
    *,
    reference: Mapping[str, Any],
    inventory_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    value = _strict_json(raw, label=AUTHORITY_ROLLBACK_PATH)
    try:
        validated = validate_authority_rollback_evidence(value)
    except (ValueError, RuntimeError) as exc:
        raise FailureClosureError(
            f"exec-005 authority rollback evidence did not validate: {exc}"
        ) from exc
    _require(
        raw == _canonical(validated) + b"\n",
        "exec-005 authority rollback evidence bytes are noncanonical",
    )
    cause = validated["cause"]
    records = validated["records"]
    _require(
        validated["terminal_record_count"] == AUTHORITY_ROLLBACK_RECORD_COUNT,
        "exec-005 authority rollback record count differs",
    )
    for index, binding in enumerate(records):
        terminal_path = "results/" + binding["relative_path"]
        terminal_reference = inventory_rows.get(terminal_path)
        _require(
            isinstance(terminal_reference, Mapping)
            and terminal_reference.get("sha256") == binding["after_raw_sha256"]
            and terminal_reference.get("bytes") == binding["after_raw_bytes"],
            f"exec-005 authority rollback terminal binding differs: {index}",
        )
    projection = {
        "schema": validated["schema"],
        "status": validated["status"],
        "cause_stage": cause["stage"],
        "failure_taxonomy": cause["failure_taxonomy"],
        "reason_summary": _text_summary(cause["reason"]),
        "terminal_record_count": validated["terminal_record_count"],
        "authority_transition": validated["authority_transition"],
        "records": records,
        "payload_sha256": validated["payload_sha256"],
        "restricted_record": dict(reference),
    }
    _require(
        set(projection) == set(AUTHORITY_ROLLBACK_PROJECTION_FIELDS),
        "exec-005 authority rollback projection field drift",
    )
    return projection


def _validate_authority_rollback_projection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    _require(
        isinstance(value, dict)
        and set(value) == set(AUTHORITY_ROLLBACK_PROJECTION_FIELDS),
        "exec-005 authority rollback public projection fields differ",
    )
    cause_stage = value.get("cause_stage")
    taxonomy = value.get("failure_taxonomy")
    records = value.get("records")
    _require(
        value.get("schema") == ROLLBACK_EVIDENCE_SCHEMA
        and value.get("status") == "AUTHORITY_REVOKED"
        and cause_stage in AUTHORITY_ROLLBACK_TAXONOMY
        and taxonomy == AUTHORITY_ROLLBACK_TAXONOMY[cause_stage]
        and value.get("terminal_record_count") == AUTHORITY_ROLLBACK_RECORD_COUNT
        and value.get("authority_transition") == {"before": True, "after": False}
        and isinstance(records, list)
        and len(records) == AUTHORITY_ROLLBACK_RECORD_COUNT
        and isinstance(value.get("payload_sha256"), str)
        and HEX64.fullmatch(value["payload_sha256"]) is not None,
        "exec-005 authority rollback public state differs",
    )
    _validate_text_summary(
        value.get("reason_summary"), label="exec-005 authority rollback reason"
    )
    expected_record_fields = {
        "order_index",
        "target_id",
        "relative_path",
        "before_raw_bytes",
        "before_raw_sha256",
        "after_raw_bytes",
        "after_raw_sha256",
    }
    for index, binding in enumerate(records):
        _require(
            isinstance(binding, dict)
            and set(binding) == expected_record_fields
            and binding.get("order_index") == index
            and isinstance(binding.get("target_id"), str)
            and bool(binding["target_id"])
            and isinstance(binding.get("relative_path"), str)
            and bool(binding["relative_path"])
            and all(
                type(binding.get(field)) is int and binding[field] > 0
                for field in ("before_raw_bytes", "after_raw_bytes")
            )
            and all(
                isinstance(binding.get(field), str)
                and HEX64.fullmatch(binding[field]) is not None
                for field in ("before_raw_sha256", "after_raw_sha256")
            ),
            f"exec-005 authority rollback public record differs: {index}",
        )
    reference = value.get("restricted_record")
    _require(
        isinstance(reference, dict)
        and set(reference) == {"bytes", "path", "sha256"}
        and reference.get("path") == AUTHORITY_ROLLBACK_PATH,
        "exec-005 authority rollback public reference differs",
    )
    return dict(value)


def _authority_recovery_projection(
    raw: bytes,
    *,
    reference: Mapping[str, Any],
    inventory_rows: Mapping[str, Mapping[str, Any]],
    restricted_root: Path,
) -> dict[str, Any]:
    value = _strict_json(raw, label=AUTHORITY_RECOVERY_PATH)
    try:
        validated = validate_authority_recovery_evidence(value)
    except (ValueError, RuntimeError) as exc:
        raise FailureClosureError(
            f"exec-005 authority recovery evidence did not validate: {exc}"
        ) from exc
    _require(
        raw == _canonical(validated) + b"\n",
        "exec-005 authority recovery evidence bytes are noncanonical",
    )
    cause = validated["cause"]
    records = validated["records"]
    _require(
        validated["terminal_record_count"] == AUTHORITY_ROLLBACK_RECORD_COUNT,
        "exec-005 authority recovery record count differs",
    )
    for index, binding in enumerate(records):
        terminal_path = "results/" + binding["relative_path"]
        terminal_reference = inventory_rows.get(terminal_path)
        _require(
            isinstance(terminal_reference, Mapping)
            and terminal_reference.get("sha256") == binding["raw_sha256"]
            and terminal_reference.get("bytes") == binding["raw_bytes"],
            f"exec-005 authority recovery terminal binding differs: {index}",
        )
    journal_binding = validated["finalization_journal"]
    public_journal_binding: dict[str, Any] | None = None
    if journal_binding is not None:
        journal_path = "results/" + journal_binding["path"]
        journal_reference = inventory_rows.get(journal_path)
        _require(
            isinstance(journal_reference, Mapping)
            and journal_reference.get("bytes") == journal_binding["bytes"]
            and journal_reference.get("sha256") == journal_binding["sha256"],
            "exec-005 finalization journal is not inventory-bound",
        )
        journal_raw = _inventory_bytes(
            restricted_root,
            journal_reference,
            label="campaign finalization journal",
        )
        journal_value = _strict_json(journal_raw, label=journal_path)
        try:
            validated_journal = validate_finalization_journal(
                journal_value,
                output_root=restricted_root / "results",
            )
        except (ValueError, RuntimeError) as exc:
            raise FailureClosureError(
                f"exec-005 finalization journal did not validate: {exc}"
            ) from exc
        _require(
            journal_raw == _canonical(validated_journal) + b"\n"
            and validated_journal["status"] == journal_binding["status"]
            and validated_journal["payload_sha256"]
            == journal_binding["payload_sha256"],
            "exec-005 finalization journal binding differs",
        )
        public_journal_binding = {
            **journal_binding,
            "path": journal_path,
        }
    projection = {
        "schema": validated["schema"],
        "status": validated["status"],
        "cause_stage": cause["stage"],
        "failure_taxonomy": cause["failure_taxonomy"],
        "reason_summary": _text_summary(cause["reason"]),
        "terminal_record_count": validated["terminal_record_count"],
        "canonical_state_before": validated["canonical_state_before"],
        "canonical_state_after": validated["canonical_state_after"],
        "recovery_source": validated["recovery_source"],
        "promotion_transaction_count": validated["promotion_transaction_count"],
        "rollback_transaction_count": validated["rollback_transaction_count"],
        "finalization_journal": public_journal_binding,
        "records": records,
        "payload_sha256": validated["payload_sha256"],
        "restricted_record": dict(reference),
    }
    _require(
        set(projection) == set(AUTHORITY_RECOVERY_PROJECTION_FIELDS),
        "exec-005 authority recovery projection field drift",
    )
    return projection


def _validate_authority_recovery_projection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    _require(
        isinstance(value, dict)
        and set(value) == set(AUTHORITY_RECOVERY_PROJECTION_FIELDS),
        "exec-005 authority recovery public projection fields differ",
    )
    cause_stage = value.get("cause_stage")
    taxonomy = value.get("failure_taxonomy")
    records = value.get("records")
    _require(
        value.get("schema") == RECOVERY_EVIDENCE_SCHEMA
        and value.get("status") == "FALSE_AUTHORITY_RESTORED"
        and cause_stage in AUTHORITY_ROLLBACK_TAXONOMY
        and taxonomy == AUTHORITY_ROLLBACK_TAXONOMY[cause_stage]
        and value.get("terminal_record_count") == AUTHORITY_ROLLBACK_RECORD_COUNT
        and value.get("canonical_state_before")
        in {"ABSENT", "FALSE", "INCOMPLETE", "MIXED", "TRUE"}
        and value.get("canonical_state_after") == "FALSE"
        and value.get("recovery_source")
        in {"canonical_false", "promotion_original", "rollback_replacement"}
        and type(value.get("promotion_transaction_count")) is int
        and value["promotion_transaction_count"] in {0, 1}
        and type(value.get("rollback_transaction_count")) is int
        and value["rollback_transaction_count"] in {0, 1}
        and value["promotion_transaction_count"]
        + value["rollback_transaction_count"]
        <= 1
        and isinstance(records, list)
        and len(records) == AUTHORITY_ROLLBACK_RECORD_COUNT
        and isinstance(value.get("payload_sha256"), str)
        and HEX64.fullmatch(value["payload_sha256"]) is not None,
        "exec-005 authority recovery public state differs",
    )
    _validate_text_summary(
        value.get("reason_summary"), label="exec-005 authority recovery reason"
    )
    finalization_journal = value.get("finalization_journal")
    if finalization_journal is not None:
        _require(
            isinstance(finalization_journal, dict)
            and set(finalization_journal)
            == {"bytes", "path", "payload_sha256", "sha256", "status"}
            and finalization_journal.get("path")
            == "results/" + FINALIZATION_JOURNAL_RELATIVE_PATH.as_posix()
            and type(finalization_journal.get("bytes")) is int
            and finalization_journal["bytes"] > 0
            and isinstance(finalization_journal.get("sha256"), str)
            and HEX64.fullmatch(finalization_journal["sha256"]) is not None
            and isinstance(finalization_journal.get("payload_sha256"), str)
            and HEX64.fullmatch(finalization_journal["payload_sha256"]) is not None
            and isinstance(finalization_journal.get("status"), str),
            "exec-005 authority recovery journal projection differs",
        )
    _require(
        cause_stage != "scientific_aggregate"
        or (
            isinstance(finalization_journal, dict)
            and finalization_journal.get("status")
            == SCIENTIFIC_AGGREGATE_REJECTED
        ),
        "exec-005 scientific authority recovery journal is absent",
    )
    record_fields = {
        "order_index",
        "target_id",
        "relative_path",
        "raw_bytes",
        "raw_sha256",
    }
    for index, binding in enumerate(records):
        _require(
            isinstance(binding, dict)
            and set(binding) == record_fields
            and binding.get("order_index") == index
            and isinstance(binding.get("target_id"), str)
            and bool(binding["target_id"])
            and isinstance(binding.get("relative_path"), str)
            and bool(binding["relative_path"])
            and type(binding.get("raw_bytes")) is int
            and binding["raw_bytes"] > 0
            and isinstance(binding.get("raw_sha256"), str)
            and HEX64.fullmatch(binding["raw_sha256"]) is not None,
            f"exec-005 authority recovery public record differs: {index}",
        )
    reference = value.get("restricted_record")
    _require(
        isinstance(reference, dict)
        and set(reference) == {"bytes", "path", "sha256"}
        and reference.get("path") == AUTHORITY_RECOVERY_PATH,
        "exec-005 authority recovery public reference differs",
    )
    return dict(value)


def _validate_authority_resolution_projection(
    value: Any,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict) and value.get("schema") == RECOVERY_EVIDENCE_SCHEMA:
        return _validate_authority_recovery_projection(value)
    return _validate_authority_rollback_projection(value)


def _derive(
    records: list[dict[str, Any]],
    lifecycle: Mapping[str, Any],
    pre_cell: Mapping[str, Any] | None,
    authority_rollback: Mapping[str, Any] | None,
) -> tuple[dict[str, int], dict[str, int], dict[str, int], str, str]:
    try:
        combined = summarize_terminal_records(records, expected_count=EXPECTED_CELL_COUNT)
    except Exception as exc:
        raise FailureClosureError(f"exec-005 terminal summary failed: {exc}") from exc
    summary = {field: int(combined[field]) for field in SUMMARY_FIELDS}
    _require(
        summary["authoritative_cell_count"] == 0,
        "failed exec-005 campaign contains authoritative terminal cells",
    )
    taxonomy = {field: int(combined[field]) for field in FAILURE_TAXONOMY_FIELDS}
    if pre_cell is not None:
        _require(
            not records
            and lifecycle.get("status") == "NOT_STARTED"
            and pre_cell.get("actual_execution") == PRE_CELL_ZERO_EXECUTION,
            "pre-cell failure evidence is inconsistent with attempted execution",
        )
        taxonomy[str(pre_cell["failure_taxonomy"])] = 1

    if authority_rollback is not None:
        _require(
            pre_cell is None
            and len(records) == EXPECTED_CELL_COUNT
            and all(record["primary_failure"] is None for record in records)
            and not any(taxonomy.values()),
            "authority rollback conflicts with an earlier campaign failure",
        )
        taxonomy[str(authority_rollback["failure_taxonomy"])] = 1

    aggregate_failure = False
    if len(records) == EXPECTED_CELL_COUNT and not any(
        record["primary_failure"] is not None for record in records
    ):
        for record in records:
            execution = record["execution_evidence"]
            expected_resolved = record["probe"] == "GOLD"
            complete = (
                record["grader_invoked"]
                and record["container_started"]
                and record["harness_completed"]
                and record["final_report_generated"]
                and record["official_tests_executed"]
                and record["raw_test_evidence_captured"]
                and record["submitted_patch_identity_verified"]
                and record["digest_verified"]
                and record["adapter_normalized"]
                and type(record["scientific_resolved"]) is bool
                and record["scientific_resolved"] is expected_resolved
                and all(
                    execution[field] is True
                    for field in (
                        "patch_applied",
                        "tests_executed",
                        "digest_match",
                        "submitted_patch_identity",
                    )
                )
                and execution["host_prepare_sh_access_count"] == 0
                and execution["source_image_build_count"] == 0
                and execution["api_calls"] == 0
            )
            if not complete:
                aggregate_failure = True
                break
    if aggregate_failure:
        _require(
            authority_rollback is None,
            "authority rollback cannot replace a scientific mismatch",
        )
        taxonomy["aggregate_failures"] = 1
    nonaggregate_total = sum(
        taxonomy[field] for field in FAILURE_TAXONOMY_FIELDS
        if field != "aggregate_failures"
    )
    if (
        nonaggregate_total == 0
        and taxonomy["aggregate_failures"] == 0
        and lifecycle.get("status") in {"FAILED", "CLEANUP_FAILED"}
        and pre_cell is None
    ):
        taxonomy["image_lifecycle_failures"] = 1
    if not any(taxonomy.values()):
        # A failure receipt may never be taxonomy-empty.  At this point there
        # is no terminal, pre-cell, scientific aggregate, lifecycle, or
        # authority-resolution primary.  The remaining evidence-derived case
        # is an interrupted workflow/finalization boundary.
        taxonomy["infrastructure_failures"] = 1
    _require(
        sum(taxonomy.values()) == 1,
        "exec-005 failure closure does not contain exactly one primary failure layer",
    )
    if taxonomy["adapter_contract_failures"]:
        endpoint = ADAPTER_ENDPOINT
    elif taxonomy["aggregate_failures"] and authority_rollback is None:
        endpoint = SCIENTIFIC_ENDPOINT
    else:
        endpoint = INCOMPLETE_ENDPOINT
    scientific_result = (
        "FAIL" if endpoint == SCIENTIFIC_ENDPOINT else "NOT_AGGREGATED"
    )

    totals = {
        field: sum(record["actual_accounting"][field] for record in records)
        for field in SMOKE_ACCOUNTING_FIELDS
    }
    _require(
        all(totals[field] == 0 for field in ZERO_ACCOUNTING_FIELDS),
        "exec-005 failure closure contains model/API/token/task/USD activity",
    )
    actual = {
        "api_calls": totals["api_calls"],
        "grader_containers": totals["grader_containers"],
        "input_tokens": totals["input_tokens"],
        "model_calls": totals["model_calls"],
        "model_gateway_calls": totals["model_gateway_calls"],
        "official_grader_runs": totals["official_grader_runs"],
        "output_tokens": totals["output_tokens"],
        "paid_model_calls": totals["paid_model_calls"],
        "support_image_pulls": int(lifecycle["support_image_pulls"]),
        "target_image_pulls": int(lifecycle["target_image_pulls"]),
        "task_arm_runs": totals["task_arm_runs"],
        "total_usd": totals["total_usd"],
    }
    _require(
        set(actual) == set(ACTUAL_EXECUTION_FIELDS)
        and actual["grader_containers"] == summary["official_execution_count"]
        and actual["official_grader_runs"] == summary["official_execution_count"]
        and (
            pre_cell is None
            or actual == pre_cell.get("actual_execution")
        ),
        "exec-005 official execution accounting differs from container lifecycle",
    )
    return summary, taxonomy, actual, endpoint, scientific_result


def _inventory_binding(inventory: Mapping[str, Any], raw: bytes) -> dict[str, Any]:
    return {
        "path": EVIDENCE_INVENTORY_PATH,
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "inventory_sha256": inventory["inventory_sha256"],
        "total_files": inventory["total_files"],
        "total_bytes": inventory["total_bytes"],
    }


def build_failure_closure(
    *,
    restricted_root: Path,
    inventory_raw: bytes,
    request_raw: bytes,
    approval_binding: Mapping[str, Any],
    workflow_run: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive one sanitized closure from actual restricted bytes."""

    request, matrix_order = _request(request_raw)
    approval = _validated_approval(approval_binding, request_raw=request_raw)
    workflow = _validated_workflow(workflow_run, approval)
    inventory, rows = validate_inventory(inventory_raw)
    terminal_paths = sorted(
        path
        for path in rows
        if re.fullmatch(r"results/[0-9]{3}-[^/]+/[^/]+\.result\.json", path)
    )
    _require(
        len(terminal_paths) <= EXPECTED_CELL_COUNT,
        "exec-005 inventory contains too many terminal records",
    )
    projections: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, path in enumerate(terminal_paths):
        target_id = matrix_order[index]
        safe = SAFE_TARGET.sub("_", target_id)
        expected_path = f"results/{index:03d}-{safe}/{safe}.result.json"
        _require(path == expected_path, "exec-005 terminal result set is not a matrix prefix")
        raw = _inventory_bytes(restricted_root, rows[path], label=f"terminal {index}")
        value = _strict_json(raw, label=path)
        record = _terminal_record(value, index=index, target_id=target_id)
        _terminal_evidence_bytes(
            restricted_root=restricted_root,
            inventory_rows=rows,
            terminal_path=path,
            record=record,
        )
        records.append(record)
        projections.append(_terminal_projection(record, rows[path]))

    lifecycle_path = "image-materialization/image-lifecycle-report.json"
    lifecycle_row = rows.get(lifecycle_path)
    pre_cell_row = rows.get(PRE_CELL_EVIDENCE_PATH)
    _require(
        (lifecycle_row is None) != (pre_cell_row is None),
        "exec-005 failure must have exactly one lifecycle or pre-cell record",
    )
    pre_cell_projection: dict[str, Any] | None = None
    pre_cell_record: dict[str, Any] | None = None
    if lifecycle_row is not None:
        lifecycle_raw = _inventory_bytes(
            restricted_root, lifecycle_row, label="image lifecycle"
        )
        lifecycle = _lifecycle_projection(
            lifecycle_raw,
            reference=lifecycle_row,
            approval=approval,
            restricted_root=restricted_root,
            inventory_rows=rows,
        )
    else:
        _require(not records, "pre-cell failure contains terminal records")
        pre_cell_raw = _inventory_bytes(
            restricted_root, pre_cell_row, label="pre-cell failure"
        )
        pre_cell_projection = _pre_cell_projection(
            pre_cell_raw,
            reference=pre_cell_row,
            approval=approval,
        )
        pre_cell_record = {
            "failure_taxonomy": pre_cell_projection["failure_taxonomy"],
            "actual_execution": pre_cell_projection["actual_execution"],
        }
        pre_cell_raw_value = _strict_json(pre_cell_raw, label=PRE_CELL_EVIDENCE_PATH)
        lifecycle = {
            "status": "NOT_STARTED",
            "target_image_pulls": 0,
            "support_image_pulls": 0,
            "target_image_materialized_count": 0,
            "support_image_materialized_count": 0,
            "exact_image_removals": 0,
            "max_resident_target_images": 0,
            "max_resident_support_images": 0,
            "resident_target_images": 0,
            "resident_support_images": 0,
            "failure_summary": _opaque_json_summary(
                pre_cell_raw_value["primary_failure"]
            ),
            "pull_attempts": [],
            "restricted_report": None,
        }
    public_approval_path = "results/external-approval-evidence.json"
    public_approval_row = rows.get(public_approval_path)
    if public_approval_row is not None:
        public_approval_raw = _inventory_bytes(
            restricted_root, public_approval_row, label="public approval"
        )
        _require(
            _strict_json(public_approval_raw, label=public_approval_path) == approval,
            "exec-005 public approval evidence differs",
        )
    else:
        _require(
            pre_cell_record is not None,
            "exec-005 public approval evidence is absent after lifecycle start",
        )
    rollback_row = rows.get(AUTHORITY_ROLLBACK_PATH)
    recovery_row = rows.get(AUTHORITY_RECOVERY_PATH)
    _require(
        not (rollback_row is not None and recovery_row is not None),
        "exec-005 contains both authority rollback and recovery evidence",
    )
    authority_rollback = (
        _authority_rollback_projection(
            _inventory_bytes(
                restricted_root,
                rollback_row,
                label="authority rollback",
            ),
            reference=rollback_row,
            inventory_rows=rows,
        )
        if rollback_row is not None
        else _authority_recovery_projection(
            _inventory_bytes(
                restricted_root,
                recovery_row,
                label="authority recovery",
            ),
            reference=recovery_row,
            inventory_rows=rows,
            restricted_root=restricted_root,
        )
        if recovery_row is not None
        else None
    )
    summary, taxonomy, actual, endpoint, scientific_result = _derive(
        records, lifecycle, pre_cell_record, authority_rollback
    )
    payload = {
        "schema": SCHEMA,
        "status": "FAIL",
        "endpoint": endpoint,
        "development_approval_allowed": False,
        "scientific_result": scientific_result,
        "request_binding": _request_binding(request, request_raw),
        "approval_binding": approval,
        "workflow_run": workflow,
        "terminal_summary": summary,
        "terminal_records": projections,
        "failure_taxonomy": taxonomy,
        "actual_execution": actual,
        "image_lifecycle": lifecycle,
        "pre_cell_failure_evidence": pre_cell_projection,
        "authority_rollback": authority_rollback,
        "evidence_inventory": _inventory_binding(inventory, inventory_raw),
    }
    return {
        **payload,
        "receipt_payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
    }


def validate_failure_closure(
    receipt_raw: bytes,
    inventory_raw: bytes,
    *,
    request_raw: bytes,
    restricted_root: Path | None = None,
) -> dict[str, Any]:
    """Validate a committed receipt, optionally against available restricted bytes."""

    receipt = _strict_json(receipt_raw, label=FAILURE_RECEIPT_PATH)
    _require(
        isinstance(receipt, dict)
        and set(receipt) == set(RECEIPT_FIELDS)
        and _pretty(receipt) == receipt_raw,
        "exec-005 failure receipt field set or bytes differ",
    )
    payload = {
        key: value for key, value in receipt.items() if key != "receipt_payload_sha256"
    }
    _require(
        isinstance(receipt.get("receipt_payload_sha256"), str)
        and receipt["receipt_payload_sha256"]
        == hashlib.sha256(_canonical(payload)).hexdigest()
        and receipt.get("schema") == SCHEMA
        and receipt.get("status") == "FAIL"
        and receipt.get("endpoint") in ENDPOINTS
        and receipt.get("development_approval_allowed") is False,
        "exec-005 failure receipt state or seal differs",
    )
    request, matrix_order = _request(request_raw)
    _require(
        receipt.get("request_binding") == _request_binding(request, request_raw),
        "exec-005 failure request binding differs",
    )
    approval_value = receipt.get("approval_binding")
    _require(isinstance(approval_value, dict), "exec-005 approval binding is absent")
    approval = _validated_approval(approval_value, request_raw=request_raw)
    workflow_value = receipt.get("workflow_run")
    _require(isinstance(workflow_value, dict), "exec-005 workflow binding is absent")
    workflow = _validated_workflow(workflow_value, approval)
    inventory, rows = validate_inventory(inventory_raw)
    _require(
        receipt.get("evidence_inventory") == _inventory_binding(inventory, inventory_raw),
        "exec-005 failure inventory binding differs",
    )
    projections = receipt.get("terminal_records")
    _require(
        isinstance(projections, list) and len(projections) <= EXPECTED_CELL_COUNT,
        "exec-005 terminal projection set differs",
    )
    records: list[dict[str, Any]] = []
    for index, projection in enumerate(projections):
        record = _projection_record(
            projection, index=index, target_id=matrix_order[index]
        )
        reference = projection["restricted_terminal_record"]
        _require(
            rows.get(reference.get("path")) == reference,
            f"exec-005 terminal projection {index} is not inventory-bound",
        )
        records.append(record)
    pre_cell = _validate_pre_cell_projection(
        receipt.get("pre_cell_failure_evidence"), approval=approval
    )
    if pre_cell is not None:
        pre_cell_reference = pre_cell["restricted_record"]
        _require(
            rows.get(pre_cell_reference.get("path")) == pre_cell_reference,
            "exec-005 pre-cell projection is not inventory-bound",
        )
    lifecycle = _validate_lifecycle_projection(receipt.get("image_lifecycle"))
    for index, attempt in enumerate(lifecycle["pull_attempts"]):
        stage_reference = attempt["restricted_pull_stage"]
        _require(
            rows.get(stage_reference.get("path")) == stage_reference,
            f"exec-005 pull projection {index} is not inventory-bound",
        )
        inspect_reference = attempt["restricted_inspect_stage"]
        _require(
            inspect_reference is None
            or rows.get(inspect_reference.get("path")) == inspect_reference,
            f"exec-005 inspect projection {index} is not inventory-bound",
        )
    lifecycle_reference = lifecycle["restricted_report"]
    _require(
        (
            lifecycle_reference is None
            and pre_cell is not None
            and lifecycle.get("status") == "NOT_STARTED"
        )
        or (
            isinstance(lifecycle_reference, dict)
            and rows.get(lifecycle_reference.get("path")) == lifecycle_reference
            and pre_cell is None
        ),
        "exec-005 image lifecycle projection is not inventory-bound",
    )
    authority_rollback = _validate_authority_resolution_projection(
        receipt.get("authority_rollback")
    )
    if authority_rollback is not None:
        rollback_reference = authority_rollback["restricted_record"]
        _require(
            rows.get(rollback_reference.get("path")) == rollback_reference,
            "exec-005 authority resolution projection is not inventory-bound",
        )
        journal_reference = authority_rollback.get("finalization_journal")
        _require(
            journal_reference is None
            or rows.get(journal_reference.get("path"))
            == {
                "bytes": journal_reference.get("bytes"),
                "path": journal_reference.get("path"),
                "sha256": journal_reference.get("sha256"),
            },
            "exec-005 authority finalization journal is not inventory-bound",
        )
    summary, taxonomy, actual, endpoint, scientific_result = _derive(
        records,
        lifecycle,
        pre_cell,
        authority_rollback,
    )
    _require(
        receipt.get("terminal_summary") == summary
        and receipt.get("failure_taxonomy") == taxonomy
        and receipt.get("actual_execution") == actual
        and receipt.get("endpoint") == endpoint
        and receipt.get("scientific_result") == scientific_result,
        "exec-005 failure closure is not evidence-derived",
    )
    if restricted_root is not None:
        rebuilt = build_failure_closure(
            restricted_root=restricted_root,
            inventory_raw=inventory_raw,
            request_raw=request_raw,
            approval_binding=approval,
            workflow_run=workflow,
        )
        _require(rebuilt == receipt, "exec-005 restricted evidence/receipt differ")
    return dict(receipt)


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    raw = _pretty(value)
    try:
        atomic_write_bytes(path, raw)
    except FileExistsError as exc:
        raise FailureClosureError("refusing to overwrite exec-005 failure receipt") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restricted-root", type=Path, required=True)
    parser.add_argument("--evidence-inventory", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workflow-conclusion",
        choices=("failure", "cancelled", "timed_out"),
        default="failure",
    )
    args = parser.parse_args()
    try:
        from trimem_benchmark_run import validate_exec_approval

        context = validate_exec_approval("grader-smoke", args.approval_file)
        approval = {
            field: context[field]
            for field in APPROVAL_FIELDS
        }
        workflow = {
            "id": context["approved_workflow_run_id"],
            "run_attempt": int(context["approved_workflow_run_attempt"]),
            "head_sha": context["git_head"],
            "conclusion": args.workflow_conclusion,
        }
        receipt = build_failure_closure(
            restricted_root=args.restricted_root,
            inventory_raw=args.evidence_inventory.read_bytes(),
            request_raw=args.request.read_bytes(),
            approval_binding=approval,
            workflow_run=workflow,
        )
        _write_exclusive(args.output, receipt)
    except (OSError, FailureClosureError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL_CLOSED"}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "endpoint": receipt["endpoint"],
                "receipt_payload_sha256": receipt["receipt_payload_sha256"],
                "status": "PASS",
                "terminal_record_count": receipt["terminal_summary"][
                    "terminal_record_count"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
