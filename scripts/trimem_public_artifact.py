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
        if (
            aggregate.get("probe_counts") != {"GOLD": 6, "NOOP_BASELINE": 6}
            or aggregate.get("resolved_counts") != {"GOLD": 6, "NOOP_BASELINE": 0}
            or aggregate.get("unresolved_counts") != {"GOLD": 0, "NOOP_BASELINE": 6}
            or aggregate.get("patch_applied_count") != 12
            or aggregate.get("tests_executed_count") != 12
            or aggregate.get("digest_match_count") != 12
            or aggregate.get("infrastructure_failure_count") != 0
            or aggregate.get("empty_patch_ids") != []
            or aggregate.get("actual_accounting")
            != {
                "grader_calls": 12,
                "grader_containers": 12,
                "model_gateway_calls": 0,
                "official_grader_runs": 12,
                "paid_model_calls": 0,
            }
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
            "actual_accounting", "digest_match_count", "empty_patch_ids",
            "evidence_counts", "expected_target_count", "image_lifecycle",
            "infrastructure_failure_count", "observed_target_count",
            "patch_applied_count", "probe_counts", "resolved_counts",
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
