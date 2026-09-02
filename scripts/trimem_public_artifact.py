"""Publish only fields already verified and sealed by the fail-closed aggregate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from trimem_multi_swe_report_semantics import (
    MultiSWEReportSemanticsError,
    PUBLIC_SUMMARY_FIELDS,
    validate_public_semantics_summary,
)


FORBIDDEN_KEYS = {
    "patch", "gold_patch", "fix_patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS",
    "source_row", "repository_files", "raw_report", "restricted_raw_report",
}
RAW_MULTI_SWE_KEYS = frozenset({
    "error_msg",
    "fixed_tests",
    "passed_tests",
    "failed_tests",
    "skipped_tests",
    "p2p_tests",
    "f2p_tests",
    "s2p_tests",
    "n2p_tests",
    "run_result",
    "test_patch_result",
    "fix_patch_result",
    "valid",
})
PRIVATE_FAILURE_KEYS = frozenset({
    "adapter_primary_error",
    "adapter_secondary_evidence_failures",
    "exception",
    "failure_reason",
    "failure_reasons",
    "primary_failure",
    "reason",
    "secondary_evidence_failures",
    "traceback",
})
SMOKE_OUTCOME_FIELDS = (
    "target_id",
    "benchmark_id",
    "order_index",
    "probe",
    "resolved",
    "applied_patch_sha256",
    "official_test_output_sha256",
    "official_test_status_sha256",
    "container_exit_status_sha256",
    "execution_contract_sha256",
    "execution_control_sha256",
    "submitted_patch_identity_sha256",
    "semantic_normalization",
    "patch_applied",
    "tests_executed",
    "digest_match",
    "submitted_patch_identity",
    "host_prepare_sh_access_count",
    "source_image_build_count",
    "api_calls",
    "container_exit_status_code",
    "container_exit_acceptance",
)
BENCHMARK_OUTCOME_FIELDS = (
    "arm",
    "benchmark_id",
    "benchmark_role",
    "resolved",
    "target_id",
    "actual_accounting",
    "actual_memory_metrics",
    "actual_usd",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SMOKE_ACCOUNTING_FIELDS = (
    "api_calls",
    "cached_input_tokens",
    "decomposition_calls",
    "extraction_calls",
    "grader_calls",
    "grader_containers",
    "input_tokens",
    "model_calls",
    "model_gateway_calls",
    "official_grader_runs",
    "output_tokens",
    "paid_model_calls",
    "reasoning_tokens",
    "solve_calls",
    "task_arm_runs",
    "total_usd",
)
SMOKE_FAILURE_TAXONOMY_FIELDS = (
    "environment_failures",
    "infrastructure_failures",
    "image_lifecycle_failures",
    "official_harness_failures",
    "official_report_failures",
    "adapter_contract_failures",
    "aggregate_failures",
)
SMOKE_IMAGE_LIFECYCLE_ACTUAL = {
    "target_image_pulls": 6,
    "support_image_pulls": 1,
    "exact_image_removals": 7,
    "max_resident_target_images": 1,
    "max_resident_support_images": 1,
    "resident_target_images": 0,
    "resident_support_images": 0,
}


class PublicArtifactError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise PublicArtifactError(f"duplicate JSON key in {path}: {key}")
            value[key] = child
        return value
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(value, dict):
        raise PublicArtifactError(f"JSON root is not an object: {path}")
    return value


def _is_forbidden_public_key(value: object) -> bool:
    if not isinstance(value, str):
        return True
    folded = value.casefold()
    if folded in {key.casefold() for key in FORBIDDEN_KEYS}:
        return True
    if folded in RAW_MULTI_SWE_KEYS:
        return True
    # These exact count/digest/boolean fields are the sole name-free category
    # projection emitted by the shared semantics helper.
    if folded in PUBLIC_SUMMARY_FIELDS:
        return False
    if folded in PRIVATE_FAILURE_KEYS or folded.endswith("_failure_reason"):
        return True
    if any(category in folded for category in ("p2p", "f2p", "s2p", "n2p")):
        return True
    if "test_name" in folded or folded.endswith("_test_ids"):
        return True
    if folded.startswith("missing_") and any(
        token in folded for token in ("test", "name", "transition")
    ):
        return True
    return False


def _reject_forbidden(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(
            str(key)
            for key, child in value.items()
            if _is_forbidden_public_key(key)
            and not (
                path == ("evidence_counts",)
                and key == "patch"
                and type(child) is int
                and child >= 0
            )
        )
        if forbidden:
            raise PublicArtifactError(
                f"public artifact contains forbidden keys: {forbidden}"
            )
        for key, child in value.items():
            _reject_forbidden(child, path=(*path, str(key)))
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden(child, path=path)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _valid_multi_swe_semantic_summary(
    value: Any, *, resolved: object
) -> bool:
    """Validate through the one shared name-free semantics implementation."""

    if not isinstance(value, Mapping):
        return False
    try:
        summary = validate_public_semantics_summary(value)
    except MultiSWEReportSemanticsError:
        return False
    return summary["computed_resolved"] is resolved


def _valid_smoke_image_lifecycle(value: Any) -> bool:
    """Accept only the aggregate's fixed, name-free lifecycle projection."""

    return (
        isinstance(value, Mapping)
        and set(value)
        == {"actual", "event_count", "report_bytes", "report_sha256", "status"}
        and value.get("actual") == SMOKE_IMAGE_LIFECYCLE_ACTUAL
        and type(value.get("event_count")) is int
        and value["event_count"] == 14
        and type(value.get("report_bytes")) is int
        and value["report_bytes"] > 0
        and isinstance(value.get("report_sha256"), str)
        and SHA256.fullmatch(value["report_sha256"]) is not None
        and value.get("status") == "PASS"
    )


def _public_outcome_projection(
    outcomes: list[Any], *, manifest: str
) -> list[dict[str, Any]]:
    """Validate and reconstruct only the frozen public outcome shape."""

    fields = (
        SMOKE_OUTCOME_FIELDS
        if manifest == "grader-smoke"
        else BENCHMARK_OUTCOME_FIELDS
    )
    expected = set(fields)
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(outcomes):
        if not isinstance(row, Mapping) or set(row) != expected:
            raise PublicArtifactError(
                f"aggregate outcome {index} public field set differs"
            )
        projected.append({field: row[field] for field in fields})
    _reject_forbidden(projected)
    return projected


def _verified_aggregate(aggregate_path: Path) -> dict[str, Any]:
    aggregate = read_json(aggregate_path)
    digest = aggregate.get("aggregate_sha256")
    body = {key: value for key, value in aggregate.items() if key != "aggregate_sha256"}
    if (
        aggregate.get("schema") != "trimem/verified-aggregate/1.0"
        or aggregate.get("status") != "PASS"
        or not isinstance(digest, str)
        or not SHA256.fullmatch(digest)
        or hashlib.sha256(_canonical(body)).hexdigest() != digest
    ):
        raise PublicArtifactError("aggregate seal is invalid or has not passed")
    if aggregate.get("manifest") not in {"grader-smoke", "development", "heldout"}:
        raise PublicArtifactError("aggregate manifest is invalid")
    outcomes = aggregate.get("outcomes")
    totals = aggregate.get("stream_totals", [])
    approval = aggregate.get("approval_binding")
    if not isinstance(outcomes, list) or not isinstance(totals, list):
        raise PublicArtifactError("aggregate public outcomes/totals are malformed")
    _public_outcome_projection(outcomes, manifest=aggregate["manifest"])
    if aggregate.get("manifest") in {"development", "heldout"}:
        benchmark_totals = aggregate.get("benchmark_totals")
        primary = aggregate.get("primary_endpoints")
        secondary = aggregate.get("secondary_endpoints")
        roles = aggregate.get("benchmark_roles")
        if not all(isinstance(value, list) for value in (
            benchmark_totals, primary, secondary, roles
        )):
            raise PublicArtifactError("aggregate benchmark endpoints are missing")
        if primary != [
            row for row in benchmark_totals
            if isinstance(row, dict) and row.get("reporting_role") == "PRIMARY"
        ] or secondary != [
            row for row in benchmark_totals
            if isinstance(row, dict) and row.get("reporting_role") == "SECONDARY"
        ]:
            raise PublicArtifactError("aggregate benchmark endpoint roles are inconsistent")
        if {row.get("benchmark_id") for row in primary if isinstance(row, dict)} != {
            "swebench_verified"
        }:
            raise PublicArtifactError("aggregate primary endpoint is not SWE-bench Verified")
    else:
        if totals != [] or any(
            field in aggregate
            for field in (
                "benchmark_roles",
                "benchmark_totals",
                "primary_endpoints",
                "secondary_endpoints",
            )
        ):
            raise PublicArtifactError(
                "grader-smoke aggregate contains non-smoke public projections"
            )
        expected_evidence_counts = {
            name: 12
            for name in (
                "patch",
                "tests",
                "container",
                "evaluator",
                "report",
                "digest",
                "execution_contract",
                "execution_control",
                "submitted_patch_identity",
                "applied_patch",
                "test_output",
                "official_test_status",
            )
        }
        expected_evidence_counts["container_exit_status"] = 8
        smoke_target_ids = [
            row.get("target_id") for row in outcomes if isinstance(row, dict)
        ]
        smoke_outcomes_valid = (
            len(outcomes) == 12
            and len(smoke_target_ids) == 12
            and all(isinstance(target_id, str) and target_id for target_id in smoke_target_ids)
            and len(set(smoke_target_ids)) == 12
            and all(
                isinstance(row, dict)
                and row.get("patch_applied") is True
                and row.get("tests_executed") is True
                and row.get("digest_match") is True
                and row.get("submitted_patch_identity") is True
                and type(row.get("host_prepare_sh_access_count")) is int
                and row["host_prepare_sh_access_count"] == 0
                and type(row.get("source_image_build_count")) is int
                and row["source_image_build_count"] == 0
                and type(row.get("api_calls")) is int
                and row["api_calls"] == 0
                and isinstance(row.get("execution_contract_sha256"), str)
                and SHA256.fullmatch(row["execution_contract_sha256"]) is not None
                and isinstance(row.get("execution_control_sha256"), str)
                and SHA256.fullmatch(row["execution_control_sha256"]) is not None
                and isinstance(row.get("submitted_patch_identity_sha256"), str)
                and SHA256.fullmatch(row["submitted_patch_identity_sha256"])
                is not None
                and (
                    (
                        row.get("benchmark_id") == "swebench_verified"
                        and row.get("semantic_normalization") is None
                    )
                    or (
                        row.get("benchmark_id")
                        in {"multi_swe_bench_mini", "multi_swe_bench_flash"}
                        and _valid_multi_swe_semantic_summary(
                            row.get("semantic_normalization"),
                            resolved=row.get("resolved"),
                        )
                    )
                )
                and (
                    (
                        row.get("benchmark_id") == "swebench_verified"
                        and row.get("container_exit_status_code") is None
                        and row.get("container_exit_status_sha256") is None
                        and row.get("container_exit_acceptance") is None
                    )
                    or (
                        row.get("benchmark_id")
                        in {"multi_swe_bench_mini", "multi_swe_bench_flash"}
                        and type(row.get("container_exit_status_code")) is int
                        and 0 <= row["container_exit_status_code"] <= 255
                        and isinstance(row.get("container_exit_status_sha256"), str)
                        and SHA256.fullmatch(row["container_exit_status_sha256"])
                        is not None
                        and row.get("container_exit_acceptance")
                        in {
                            "ZERO_EXIT",
                            "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION",
                        }
                        and (
                            row.get("resolved") is not True
                            or row["container_exit_status_code"] == 0
                        )
                    )
                )
                for row in outcomes
            )
        )
        if (
            aggregate.get("probe_counts") != {"GOLD": 6, "NOOP_BASELINE": 6}
            or aggregate.get("resolved_counts") != {"GOLD": 6, "NOOP_BASELINE": 0}
            or aggregate.get("unresolved_counts") != {"GOLD": 0, "NOOP_BASELINE": 6}
            or type(aggregate.get("patch_applied_count")) is not int
            or aggregate["patch_applied_count"] != 12
            or type(aggregate.get("tests_executed_count")) is not int
            or aggregate["tests_executed_count"] != 12
            or type(aggregate.get("digest_match_count")) is not int
            or aggregate["digest_match_count"] != 12
            or type(aggregate.get("submitted_patch_identity_count")) is not int
            or aggregate["submitted_patch_identity_count"] != 12
            or type(aggregate.get("host_prepare_sh_access_count")) is not int
            or aggregate["host_prepare_sh_access_count"] != 0
            or type(aggregate.get("source_image_build_count")) is not int
            or aggregate["source_image_build_count"] != 0
            or type(aggregate.get("container_exit_status_captured_count")) is not int
            or aggregate["container_exit_status_captured_count"] != 8
            or type(aggregate.get("container_exit_status_validated_count")) is not int
            or aggregate["container_exit_status_validated_count"] != 8
            or type(aggregate.get("resolved_container_zero_exit_count")) is not int
            or aggregate["resolved_container_zero_exit_count"] != 4
            or type(aggregate.get("attempted_cell_count")) is not int
            or aggregate["attempted_cell_count"] != 12
            or type(aggregate.get("terminal_record_count")) is not int
            or aggregate["terminal_record_count"] != 12
            or type(aggregate.get("official_execution_count")) is not int
            or aggregate["official_execution_count"] != 12
            or type(aggregate.get("complete_execution_evidence_count")) is not int
            or aggregate["complete_execution_evidence_count"] != 12
            or type(aggregate.get("adapter_normalized_count")) is not int
            or aggregate["adapter_normalized_count"] != 12
            or type(aggregate.get("authoritative_cell_count")) is not int
            or aggregate["authoritative_cell_count"] != 12
            or type(aggregate.get("unattempted_cell_count")) is not int
            or aggregate["unattempted_cell_count"] != 0
            or type(aggregate.get("api_calls")) is not int
            or aggregate["api_calls"] != 0
            or any(
                type(aggregate.get(field)) is not int
                or aggregate[field] != 0
                for field in SMOKE_FAILURE_TAXONOMY_FIELDS
            )
            or aggregate.get("empty_patch_ids") != []
            or _canonical(aggregate.get("evidence_counts"))
            != _canonical(expected_evidence_counts)
            or not smoke_outcomes_valid
            or _canonical(aggregate.get("actual_accounting"))
            != _canonical({
                field: 12
                if field in {
                    "grader_calls", "grader_containers", "official_grader_runs"
                }
                else 0
                for field in SMOKE_ACCOUNTING_FIELDS
            })
            or not _valid_smoke_image_lifecycle(aggregate.get("image_lifecycle"))
        ):
            raise PublicArtifactError("grader-smoke exact execution summary differs")
    required_approval = {
        "approval_artifact_sha256",
        "approved_request_sha256",
        "approved_workflow_run_id",
        "approved_workflow_run_attempt",
        "freeze_sha256",
        "git_head",
        "phase",
    }
    if not isinstance(approval, dict) or set(approval) != required_approval:
        raise PublicArtifactError("aggregate approval binding is malformed")
    for field in (
        "approval_artifact_sha256",
        "approved_request_sha256",
        "freeze_sha256",
    ):
        if not isinstance(approval[field], str) or not SHA256.fullmatch(approval[field]):
            raise PublicArtifactError(f"aggregate approval binding has invalid {field}")
    return aggregate


def package(aggregate_path: Path, output: Path) -> dict[str, Any]:
    aggregate = _verified_aggregate(aggregate_path)
    outcomes = _public_outcome_projection(
        aggregate["outcomes"], manifest=aggregate["manifest"]
    )
    result = {
        "schema": "trimem/public-benchmark-artifact/1.0",
        "status": "PASS",
        "verified_aggregate_sha256": aggregate["aggregate_sha256"],
        "manifest": aggregate["manifest"],
        "outcomes": outcomes,
        "stream_totals": aggregate.get("stream_totals", []),
        "approval_binding": aggregate["approval_binding"],
        "restricted_evidence": "ENCRYPTED_SEPARATE_ARTIFACT_NOT_PUBLIC",
        "dataset_rows_or_gold_test_payloads": "EXCLUDED_AND_EPHEMERAL_INPUTS_PURGED",
    }
    for field in (
        "benchmark_roles", "benchmark_totals", "primary_endpoints", "secondary_endpoints"
    ):
        if field in aggregate:
            result[field] = aggregate[field]
    if aggregate["manifest"] == "grader-smoke":
        for field in (
            "actual_accounting", "api_calls", "digest_match_count", "empty_patch_ids",
            "container_exit_status_captured_count",
            "container_exit_status_validated_count",
            "evidence_counts", "expected_target_count", "image_lifecycle",
            "host_prepare_sh_access_count",
            "attempted_cell_count", "terminal_record_count",
            "official_execution_count",
            "complete_execution_evidence_count", "adapter_normalized_count",
            "authoritative_cell_count", "unattempted_cell_count",
            *SMOKE_FAILURE_TAXONOMY_FIELDS, "observed_target_count",
            "patch_applied_count", "probe_counts", "resolved_counts",
            "resolved_container_zero_exit_count",
            "source_image_build_count", "submitted_patch_identity_count",
            "tests_executed_count", "unresolved_counts",
        ):
            result[field] = aggregate[field]
    _reject_forbidden(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    output.write_bytes(raw)
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "records": len(aggregate["outcomes"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    # Retained temporarily for workflow/CLI compatibility. It is deliberately
    # never opened: public material is derived only from the sealed aggregate.
    parser.add_argument("--source", type=Path)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = package(args.aggregate.resolve(), args.output.resolve())
        print(json.dumps({**summary, "status": "PASS"}, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
