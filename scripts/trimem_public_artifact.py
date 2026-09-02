"""Publish only fields already verified and sealed by the fail-closed aggregate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


FORBIDDEN_KEYS = {
    "patch", "gold_patch", "fix_patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS",
    "source_row", "repository_files", "raw_report", "restricted_raw_report",
}
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


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, Mapping):
        overlap = FORBIDDEN_KEYS & set(value)
        if overlap:
            raise PublicArtifactError(f"public artifact contains forbidden keys: {sorted(overlap)}")
        for child in value.values():
            _reject_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden(child)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


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
            or type(aggregate.get("api_calls")) is not int
            or aggregate["api_calls"] != 0
            or type(aggregate.get("infrastructure_failure_count")) is not int
            or aggregate["infrastructure_failure_count"] != 0
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
            or aggregate.get("image_lifecycle", {}).get("status") != "PASS"
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
    result = {
        "schema": "trimem/public-benchmark-artifact/1.0",
        "status": "PASS",
        "verified_aggregate_sha256": aggregate["aggregate_sha256"],
        "manifest": aggregate["manifest"],
        "outcomes": aggregate["outcomes"],
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
            "infrastructure_failure_count", "observed_target_count",
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
