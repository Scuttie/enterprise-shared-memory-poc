"""Run the frozen 6-instance/12-target official grader smoke after approval."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.grader import GradeRequest, GradeResult, GraderInvocationFailure  # noqa: E402
from enterprise_memory.trimem.workspace import WorkspaceGraderContext  # noqa: E402
from trimem_benchmark_run import (  # noqa: E402
    BenchmarkExecutionError,
    evidence_reference,
    grader_factory,
    image_entries,
    observed_target_digest,
    prepare_harnesses,
    read_json,
    restricted_evidence_references,
    sha256_bytes,
    validate_benchmark_environment,
    validate_exec_approval,
    write_json,
)
from trimem_select_targets import canonical_bytes, instance_id, load_sources, row_hash  # noqa: E402
from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_CONTENT,
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATCH,
    NOOP_BASELINE_PATH,
    SmokeProtocolError,
    validate_serial_targets,
)
from trimem_pull_locked_images import (  # noqa: E402
    pull_and_observe_image,
    remove_materialized_image,
)
from trimem_official_grader import (  # noqa: E402
    FrozenOfficialTarget,
    MULTI_FIX_PATCH_RUN_COMMAND,
    MULTI_HARNESS_REVISION,
    SWE_HARNESS_REVISION,
    OfficialGraderError,
    parse_official_report,
    validate_multi_swe_container_exit_status,
    validate_official_test_evidence,
)


EMPTY_PATCH_SHA256 = sha256_bytes(b"")
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

_EXECUTION_CONTRACT_FIELDS = {
    "schema",
    "profile",
    "execution_mode",
    "human_mode",
    "force_build",
    "need_clone",
    "report_module",
    "report_mode",
    "source_image_build_calls",
    "host_prepare_script_reads",
    "submitted_patch_bytes",
    "submitted_patch_sha256",
    "patch_transport",
    "api_calls",
}


def _expected_execution_contract(
    target: Mapping[str, Any], patch_raw: bytes
) -> dict[str, Any]:
    common = {
        "schema": "trimem/official-grader-execution-contract/1.0",
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
        "submitted_patch_bytes": len(patch_raw),
        "submitted_patch_sha256": sha256_bytes(patch_raw),
        "api_calls": 0,
    }
    if target.get("benchmark_id") == "swebench_verified":
        return {
            **common,
            "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
            "execution_mode": "evaluation",
            "human_mode": None,
            "force_build": None,
            "need_clone": None,
            "report_module": "swebench.harness.run_evaluation",
            "report_mode": "inline",
            "patch_transport": {
                "host_source": "prediction.jsonl.model_patch",
                "container_destination": None,
                "mode": None,
            },
        }
    if str(target.get("benchmark_id", "")).startswith("multi_swe_bench_"):
        return {
            **common,
            "profile": "MULTI_SWE_PREBUILT_EVALUATION",
            "execution_mode": "instance_only",
            "human_mode": True,
            "force_build": False,
            "need_clone": False,
            "fix_patch_run_cmd": MULTI_FIX_PATCH_RUN_COMMAND,
            "container_image_execution": "IMMUTABLE_DIGEST",
            "tag_digest_same_image_id_required": True,
            "docker_pull_fallback_allowed": False,
            "container_exit_status": "CAPTURED_AND_FULL_DOMAIN_VALIDATED",
            "report_module": "multi_swe_bench.harness.gen_report",
            "report_mode": "evaluation",
            "patch_transport": {
                "host_source": "evaluation_instance_fix.patch",
                "container_destination": "/home/fix.patch",
                "mode": "rw",
            },
        }
    raise BenchmarkExecutionError("official grader execution contract benchmark is unsupported")


def _validated_execution_contract(
    grade: GradeResult, *, target: Mapping[str, Any], patch_raw: bytes
) -> dict[str, Any]:
    """Require the adapter's exact, patch-bound execution-contract evidence."""

    trimem = grade.report.get("_trimem") if isinstance(grade.report, Mapping) else None
    raw_contract = trimem.get("execution_contract") if isinstance(trimem, Mapping) else None
    expected = _expected_execution_contract(target, patch_raw)
    if not isinstance(raw_contract, Mapping) or set(raw_contract) != set(expected):
        raise BenchmarkExecutionError(
            "official grader report has no exact execution-contract evidence"
        )
    contract = dict(raw_contract)
    try:
        equal = canonical_bytes(contract) == canonical_bytes(expected)
    except (TypeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "official grader execution-contract evidence is not canonical JSON"
        ) from exc
    if not equal:
        raise BenchmarkExecutionError(
            "official grader execution-contract evidence drifted from the submitted patch"
        )
    return contract


def _expected_execution_control(target: Mapping[str, Any]) -> dict[str, Any]:
    benchmark_id = str(target.get("benchmark_id", ""))
    common = {
        "schema": "trimem/official-grader-execution-control/1.0",
        "harness_revision": (
            SWE_HARNESS_REVISION
            if benchmark_id == "swebench_verified"
            else MULTI_HARNESS_REVISION
        ),
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
    }
    if benchmark_id == "swebench_verified":
        return {
            **common,
            "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
            "proof_basis": "PINNED_CONTROL_FLOW_AND_FIXED_ARGV",
            "dispatch": "main(task_repo=None,rewrite_reports=False)->run_instances",
            "source_build_guard": {
                "expression": "task_repo and not rewrite_reports",
                "task_repo_argv_present": False,
                "rewrite_reports_argv_present": False,
                "evaluates": False,
            },
            "structurally_excluded_calls": ["_build_before_eval"],
        }
    if benchmark_id.startswith("multi_swe_bench_"):
        return {
            **common,
            "profile": "MULTI_SWE_PREBUILT_EVALUATION",
            "proof_basis": "PINNED_CONTROL_FLOW_AND_ADAPTER_CONSTRUCTION_INVARIANT",
            "dispatch": (
                "trimem_multi_swe_entrypoint.execute_pinned_instance_only"
                "->CliArgs.run(instance_only)->run_mode_instance_only"
            ),
            "support_container_bootstrap_calls": 0,
            "upstream_module_main_executed": False,
            "structurally_excluded_calls": [
                "run_evaluation.__main__.nix_swe_bootstrap",
                "run_mode_image",
                "check_commit_hashes",
                "build_image",
                "run_and_save_logs",
            ],
        }
    raise BenchmarkExecutionError("official grader execution-control benchmark is unsupported")


def _validated_execution_control(
    grade: GradeResult,
    *,
    target: Mapping[str, Any],
    execution_contract: Mapping[str, Any],
) -> dict[str, Any]:
    trimem = grade.report.get("_trimem") if isinstance(grade.report, Mapping) else None
    raw_control = (
        trimem.get("execution_control_evidence")
        if isinstance(trimem, Mapping)
        else None
    )
    if not isinstance(raw_control, Mapping):
        raise BenchmarkExecutionError(
            "official grader report has no execution-control evidence"
        )
    control = dict(raw_control)
    expected = _expected_execution_control(target)
    try:
        equal = canonical_bytes(control) == canonical_bytes(expected)
    except (TypeError, ValueError) as exc:
        raise BenchmarkExecutionError(
            "official grader execution-control evidence is not canonical JSON"
        ) from exc
    if not equal:
        raise BenchmarkExecutionError("official grader execution-control evidence drift")
    if (
        control["source_image_build_calls"]
        != execution_contract.get("source_image_build_calls")
        or control["host_prepare_script_reads"]
        != execution_contract.get("host_prepare_script_reads")
        or control["profile"] != execution_contract.get("profile")
    ):
        raise BenchmarkExecutionError(
            "execution-control evidence differs from the declared execution contract"
        )
    return control


def _prediction_input_bytes(
    target: Mapping[str, Any], patch_raw: bytes
) -> bytes:
    patch = patch_raw.decode("utf-8")
    if target.get("benchmark_id") == "swebench_verified":
        value = {
            "instance_id": target["instance_id"],
            "model_patch": patch,
            "model_name_or_path": f"trimem-v1-smoke-{str(target['probe']).lower()}",
        }
    else:
        repository, number = str(target["instance_id"]).rsplit("-", 1)
        org, repo = repository.split("__", 1)
        value = {
            "org": org,
            "repo": repo,
            "number": number,
            "fix_patch": patch,
        }
    return canonical_bytes(value) + b"\n"


def _validated_submitted_patch_identity(
    grade: GradeResult,
    *,
    target: Mapping[str, Any],
    patch_raw: bytes,
    grader_root: Path,
    restricted_submitted_patch: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the exact prediction route and, for Multi, its mounted host patch."""

    trimem = grade.report.get("_trimem") if isinstance(grade.report, Mapping) else None
    private_inputs = (
        trimem.get("materialized_private_inputs")
        if isinstance(trimem, Mapping)
        else None
    )
    expected_names = (
        ["dataset.json", "prediction.jsonl"]
        if target.get("benchmark_id") == "swebench_verified"
        else ["dataset.jsonl", "prediction.jsonl", "config.json"]
    )
    if not isinstance(private_inputs, list) or len(private_inputs) != len(expected_names):
        raise BenchmarkExecutionError("official grader private-input identity set differs")
    normalized_inputs: list[dict[str, Any]] = []
    task_relative = str(target["target_id"]).replace("/", "_")
    task_root = (grader_root / task_relative).resolve()
    if grader_root.resolve() not in task_root.parents:
        raise BenchmarkExecutionError("official grader task input path escaped grader root")
    for expected_name, raw_row in zip(expected_names, private_inputs, strict=True):
        if not isinstance(raw_row, Mapping) or set(raw_row) != {
            "name", "sha256", "bytes", "retention"
        }:
            raise BenchmarkExecutionError("official grader private-input evidence field set differs")
        row = dict(raw_row)
        if (
            row.get("name") != expected_name
            or not isinstance(row.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
            or type(row.get("bytes")) is not int
            or row["bytes"] <= 0
            or row.get("retention") != "PURGED_AFTER_HASH_BOUND_GRADING"
        ):
            raise BenchmarkExecutionError("official grader private-input identity drift")
        host_path = task_root / expected_name
        if host_path.exists() or host_path.is_symlink():
            raise BenchmarkExecutionError("official grader private input was not purged")
        normalized_inputs.append({
            **row,
            "host_path": host_path.relative_to(grader_root.resolve()).as_posix(),
            "purged_after_capture": True,
        })

    prediction_raw = _prediction_input_bytes(target, patch_raw)
    prediction = normalized_inputs[expected_names.index("prediction.jsonl")]
    if (
        prediction["bytes"] != len(prediction_raw)
        or prediction["sha256"] != sha256_bytes(prediction_raw)
    ):
        raise BenchmarkExecutionError(
            "official prediction input does not contain the exact submitted patch identity"
        )

    patch_sha256 = sha256_bytes(patch_raw)
    if restricted_submitted_patch != {
        "path": "restricted-input/applied.patch",
        "sha256": patch_sha256,
        "bytes": len(patch_raw),
    }:
        raise BenchmarkExecutionError("restricted submitted-patch reference drift")

    materialized = (
        trimem.get("materialized_patch_evidence")
        if isinstance(trimem, Mapping)
        else None
    )
    if target.get("benchmark_id") == "swebench_verified":
        if materialized is not None or (
            isinstance(trimem, Mapping) and "materialized_patch_evidence" in trimem
        ):
            raise BenchmarkExecutionError(
                "SWE prediction route unexpectedly claims a materialized host patch"
            )
        route = "SWE_BENCH_PREDICTION_JSONL"
        normalized_materialized = None
    else:
        if not isinstance(materialized, Mapping) or set(materialized) != {
            "schema",
            "host_path",
            "container_destination",
            "mode",
            "bytes",
            "sha256",
            "request_identity_match",
            "restricted_materialized_patch",
            "purged_after_capture",
        }:
            raise BenchmarkExecutionError(
                "Multi-SWE materialized submitted-patch evidence is missing"
            )
        repository, number = str(target["instance_id"]).rsplit("-", 1)
        org, repo = repository.split("__", 1)
        expected_host_path = (
            f"{task_relative}/work/{org}/{repo}/evals/pr-{number}/fix.patch"
        )
        restricted = materialized.get("restricted_materialized_patch")
        expected_restricted_path = (
            "restricted-evidence/submitted-patch-materialized-"
            f"{patch_sha256}.bin"
        )
        if (
            materialized.get("schema")
            != "trimem/materialized-submitted-patch-evidence/1.0"
            or materialized.get("host_path") != expected_host_path
            or materialized.get("container_destination") != "/home/fix.patch"
            or materialized.get("mode") != "rw"
            or type(materialized.get("bytes")) is not int
            or materialized["bytes"] != len(patch_raw)
            or materialized.get("sha256") != patch_sha256
            or materialized.get("request_identity_match") is not True
            or materialized.get("purged_after_capture") is not True
            or not isinstance(restricted, Mapping)
            or set(restricted) != {"path", "sha256", "bytes", "access"}
            or restricted.get("path") != expected_restricted_path
            or restricted.get("sha256") != patch_sha256
            or type(restricted.get("bytes")) is not int
            or restricted["bytes"] != len(patch_raw)
            or restricted.get("access") != "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS"
        ):
            raise BenchmarkExecutionError(
                "Multi-SWE materialized submitted-patch identity drift"
            )
        restricted_path = (grader_root / expected_restricted_path).resolve()
        if (
            grader_root.resolve() not in restricted_path.parents
            or not restricted_path.is_file()
            or restricted_path.is_symlink()
            or restricted_path.read_bytes() != patch_raw
        ):
            raise BenchmarkExecutionError(
                "Multi-SWE restricted materialized patch bytes are missing or drifted"
            )
        materialized_path = (grader_root / expected_host_path).resolve()
        if materialized_path.exists() or materialized_path.is_symlink():
            raise BenchmarkExecutionError(
                "Multi-SWE materialized submitted patch was not purged"
            )
        route = "MULTI_SWE_MATERIALIZED_FIX_PATCH"
        normalized_materialized = dict(materialized)

    return {
        "schema": "trimem/grader-smoke-submitted-patch-identity-evidence/1.0",
        "target_id": target["target_id"],
        "benchmark_id": target["benchmark_id"],
        "route": route,
        "submitted_patch_bytes": len(patch_raw),
        "submitted_patch_sha256": patch_sha256,
        "restricted_submitted_patch": dict(restricted_submitted_patch),
        "prediction_input_identity": prediction,
        "private_input_identities": normalized_inputs,
        "materialized_patch_evidence": normalized_materialized,
        "submitted_patch_identity": True,
    }


def _smoke_execution_summary(
    targets: list[dict[str, Any]],
    cell_evidence: list[dict[str, Any]],
    *,
    failures: list[str],
    infrastructure_failures: list[str],
) -> dict[str, Any]:
    """Summarize explicit per-cell proofs; absence of failures is not evidence."""

    expected_cell_fields = {
        "target_id",
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
        "actual_accounting",
    }
    accounting_fields = set(SMOKE_ACCOUNTING_FIELDS)
    target_ids = [str(target.get("target_id")) for target in targets]
    evidence_ids = [row.get("target_id") for row in cell_evidence]
    targets_by_id = {
        str(target.get("target_id")): target
        for target in targets
        if isinstance(target.get("target_id"), str)
    }

    def invalid_container_exit(row: Mapping[str, Any]) -> bool:
        target = targets_by_id.get(str(row.get("target_id")))
        if target is None:
            return True
        status_code = row.get("container_exit_status_code")
        acceptance = row.get("container_exit_acceptance")
        status_sha256 = row.get("container_exit_status_sha256")
        if target.get("benchmark_id") == "swebench_verified":
            return any(
                value is not None
                for value in (status_code, acceptance, status_sha256)
            )
        return (
            type(status_code) is not int
            or not 0 <= status_code <= 255
            or acceptance
            not in {
                "ZERO_EXIT",
                "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION",
            }
            or not isinstance(status_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", status_sha256) is None
            or (target.get("expected_resolved") is True and status_code != 0)
        )

    malformed = [
        str(row.get("target_id"))
        for row in cell_evidence
        if set(row) != expected_cell_fields
        or any(
            type(row.get(field)) is not bool
            for field in (
                "patch_applied",
                "tests_executed",
                "digest_match",
                "submitted_patch_identity",
            )
        )
        or any(
            type(row.get(field)) is not int or row[field] < 0
            for field in (
                "host_prepare_sh_access_count",
                "source_image_build_count",
                "api_calls",
            )
        )
        or invalid_container_exit(row)
        or not isinstance(row.get("actual_accounting"), Mapping)
        or set(row.get("actual_accounting", {})) != accounting_fields
        or any(
            type(value) is not int or value < 0
            for value in row.get("actual_accounting", {}).values()
        )
        or row.get("actual_accounting", {}).get("api_calls")
        != row.get("api_calls")
    ]
    summary_failures = list(failures)
    if malformed or evidence_ids != target_ids:
        summary_failures.append("CELL_EXECUTION_EVIDENCE_SET")

    def true_count(field: str) -> int:
        return sum(row.get(field) is True for row in cell_evidence)

    def integer_total(field: str) -> int:
        return sum(
            row.get(field, 0)
            for row in cell_evidence
            if type(row.get(field, 0)) is int
        )

    counts = {
        "patch_applied_count": true_count("patch_applied"),
        "tests_executed_count": true_count("tests_executed"),
        "digest_match_count": true_count("digest_match"),
        "submitted_patch_identity_count": true_count("submitted_patch_identity"),
        "host_prepare_sh_access_count": integer_total("host_prepare_sh_access_count"),
        "source_image_build_count": integer_total("source_image_build_count"),
        "container_exit_status_captured_count": sum(
            row.get("container_exit_status_sha256") is not None
            for row in cell_evidence
        ),
        "container_exit_status_validated_count": sum(
            row.get("container_exit_acceptance")
            in {
                "ZERO_EXIT",
                "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION",
            }
            for row in cell_evidence
        ),
        "resolved_container_zero_exit_count": sum(
            targets_by_id.get(str(row.get("target_id")), {}).get(
                "expected_resolved"
            )
            is True
            and targets_by_id.get(str(row.get("target_id")), {}).get(
                "benchmark_id"
            )
            != "swebench_verified"
            and row.get("container_exit_status_code") == 0
            for row in cell_evidence
        ),
        "api_calls": integer_total("api_calls"),
    }
    expected_count = len(targets)
    accounting_totals = {
        field: sum(
            row.get("actual_accounting", {}).get(field, 0)
            for row in cell_evidence
            if type(row.get("actual_accounting", {}).get(field, 0)) is int
        )
        for field in SMOKE_ACCOUNTING_FIELDS
    }
    expected_accounting = {
        field: expected_count
        if field in {"grader_calls", "grader_containers", "official_grader_runs"}
        else 0
        for field in SMOKE_ACCOUNTING_FIELDS
    }
    for field in (
        "patch_applied_count",
        "tests_executed_count",
        "digest_match_count",
        "submitted_patch_identity_count",
    ):
        if counts[field] != expected_count:
            summary_failures.append(field.upper())
    for field in (
        "host_prepare_sh_access_count",
        "source_image_build_count",
        "api_calls",
    ):
        if counts[field] != 0:
            summary_failures.append(field.upper())
    expected_multi_count = sum(
        target.get("benchmark_id") != "swebench_verified" for target in targets
    )
    expected_resolved_multi_count = sum(
        target.get("benchmark_id") != "swebench_verified"
        and target.get("expected_resolved") is True
        for target in targets
    )
    for field in (
        "container_exit_status_captured_count",
        "container_exit_status_validated_count",
    ):
        if counts[field] != expected_multi_count:
            summary_failures.append(field.upper())
    if counts["resolved_container_zero_exit_count"] != expected_resolved_multi_count:
        summary_failures.append("RESOLVED_CONTAINER_ZERO_EXIT_COUNT")
    if accounting_totals != expected_accounting:
        summary_failures.append("ACTUAL_ACCOUNTING")
    distinct_failures = sorted(set(summary_failures))
    distinct_infrastructure = sorted(set(infrastructure_failures))
    return {
        "schema": "trimem/grader-smoke-execution/1.0",
        "expected_target_count": expected_count,
        "observed_target_count": len(cell_evidence),
        "probe_counts": {
            probe: sum(target["probe"] == probe for target in targets)
            for probe in ("GOLD", "NOOP_BASELINE")
        },
        "empty_patch_ids": [],
        "failures": distinct_failures,
        **accounting_totals,
        **counts,
        "infrastructure_failure_count": len(distinct_infrastructure),
        "status": "PASS" if not distinct_failures else "FAIL",
    }


class _SerialImageLifecycle:
    """Keep at most one target image plus one Multi harness image resident."""

    def __init__(
        self,
        *,
        approval: Mapping[str, Any],
        evidence_root: Path,
        targets: list[dict[str, Any]],
        images: Mapping[str, Mapping[str, Any]],
        support: list[tuple[str, str]],
    ) -> None:
        self.approval = approval
        self.evidence_root = evidence_root
        self.targets = targets
        self.images = images
        self.support = support
        self.events: list[dict[str, Any]] = []
        self.operation_index = 0
        self.current_instance: str | None = None
        self.support_resident = False
        self.max_resident_target_images = 0
        self.max_resident_support_images = 0
        self.status = "IN_PROGRESS"
        self.failure: dict[str, Any] | None = None
        self.evidence_root.mkdir(parents=True, exist_ok=True)

        multi_pairs = [
            pair_index
            for pair_index, target in enumerate(targets[0::2])
            if str(target["benchmark_id"]).startswith("multi_swe_bench")
        ]
        if not multi_pairs or len(support) != 1:
            raise BenchmarkExecutionError(
                "grader-smoke Multi rows require exactly one frozen support image"
            )
        if multi_pairs != list(range(multi_pairs[0], multi_pairs[-1] + 1)):
            raise BenchmarkExecutionError(
                "grader-smoke Multi identities must form one contiguous serial region"
            )
        self.last_multi_target_index = (multi_pairs[-1] * 2) + 1
        self._write_report()

    def _write_report(self) -> None:
        target_pulls = sum(
            event["action"] == "PULL_TARGET" for event in self.events
        )
        support_pulls = sum(
            event["action"] == "PULL_SUPPORT" for event in self.events
        )
        removals = sum(
            event["action"] in {"REMOVE_TARGET", "REMOVE_SUPPORT"}
            for event in self.events
        )
        write_json(self.evidence_root / "image-lifecycle-report.json", {
            "schema": "trimem/grader-smoke-image-lifecycle/1.0",
            "status": self.status,
            "phase": self.approval["phase"],
            "approval_artifact_sha256": self.approval["approval_artifact_sha256"],
            "git_head": self.approval["git_head"],
            "expected": {
                "target_image_pulls": 6,
                "support_image_pulls": 1,
                "exact_image_removals": 7,
                "max_resident_target_images": 1,
                "max_resident_support_images": 1,
            },
            "actual": {
                "target_image_pulls": target_pulls,
                "support_image_pulls": support_pulls,
                "exact_image_removals": removals,
                "max_resident_target_images": self.max_resident_target_images,
                "max_resident_support_images": self.max_resident_support_images,
                "resident_target_images": int(self.current_instance is not None),
                "resident_support_images": int(self.support_resident),
            },
            "failure": self.failure,
            "events": self.events,
        })

    def _pull(self, *, action: str, image: str, identity: str) -> None:
        try:
            record = pull_and_observe_image(
                image, self.evidence_root, self.operation_index
            )
        except BaseException as exc:
            self.events.append({
                "action": action + "_FAILED",
                "identity": identity,
                "image": image,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            self.operation_index += 1
            self.status = "FAILED"
            self._write_report()
            raise
        self.operation_index += 1
        self.events.append({"action": action, "identity": identity, "record": record})

    def _remove(
        self, *, action: str, image: str, tag: str, identity: str
    ) -> None:
        try:
            record = remove_materialized_image(
                image, [tag], self.evidence_root, self.operation_index
            )
        except BaseException as exc:
            self.events.append({
                "action": action + "_FAILED",
                "identity": identity,
                "image": image,
                "tag": tag,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
            self.operation_index += 1
            self.status = "CLEANUP_FAILED"
            self._write_report()
            raise
        self.operation_index += 1
        self.events.append({"action": action, "identity": identity, "record": record})

    def before_target(self, index: int, target: Mapping[str, Any]) -> None:
        instance = str(target["instance_id"])
        probe = target["probe"]
        if probe == "GOLD":
            if self.current_instance is not None:
                raise BenchmarkExecutionError(
                    "next smoke identity started before exact target image removal"
                )
            if str(target["benchmark_id"]).startswith("multi_swe_bench"):
                if not self.support_resident:
                    support_image, _ = self.support[0]
                    self.support_resident = True
                    self.max_resident_support_images = 1
                    self._write_report()
                    self._pull(
                        action="PULL_SUPPORT",
                        image=support_image,
                        identity="multi_swe_bench_support",
                    )
            entry = self.images[instance]
            self.current_instance = instance
            self.max_resident_target_images = 1
            self._write_report()
            self._pull(
                action="PULL_TARGET", image=str(entry["image"]), identity=instance
            )
        elif probe == "NOOP_BASELINE":
            if self.current_instance != instance:
                raise BenchmarkExecutionError(
                    "NOOP_BASELINE did not reuse its immediately preceding GOLD image"
                )
        else:
            raise BenchmarkExecutionError(f"unsupported smoke probe at index {index}")
        self._write_report()

    def after_target(self, index: int, target: Mapping[str, Any]) -> None:
        if target["probe"] != "NOOP_BASELINE":
            return
        instance = str(target["instance_id"])
        if self.current_instance != instance:
            raise BenchmarkExecutionError("smoke image lifecycle identity drift")
        entry = self.images[instance]
        self._remove(
            action="REMOVE_TARGET",
            image=str(entry["image"]),
            tag=str(entry["harness_image_tag"]),
            identity=instance,
        )
        self.current_instance = None
        if index == self.last_multi_target_index:
            support_image, support_tag = self.support[0]
            self._remove(
                action="REMOVE_SUPPORT",
                image=support_image,
                tag=support_tag,
                identity="multi_swe_bench_support",
            )
            self.support_resident = False
        self._write_report()

    def finish(self) -> None:
        actual = {
            "target_pulls": sum(
                event["action"] == "PULL_TARGET" for event in self.events
            ),
            "support_pulls": sum(
                event["action"] == "PULL_SUPPORT" for event in self.events
            ),
            "removals": sum(
                event["action"] in {"REMOVE_TARGET", "REMOVE_SUPPORT"}
                for event in self.events
            ),
        }
        if (
            actual != {"target_pulls": 6, "support_pulls": 1, "removals": 7}
            or self.current_instance is not None
            or self.support_resident
            or self.max_resident_target_images != 1
            or self.max_resident_support_images != 1
        ):
            raise BenchmarkExecutionError(
                f"grader-smoke image lifecycle failed closed: {actual}"
            )
        self.status = "PASS"
        self._write_report()

    def abort(self, exc: BaseException) -> None:
        """Best-effort exact cleanup while preserving the original failure."""

        if self.status == "PASS":
            return
        self.failure = {"error_type": type(exc).__name__, "error": str(exc)}
        cleanup_failures: list[dict[str, str]] = []
        if self.current_instance is not None:
            instance = self.current_instance
            entry = self.images[instance]
            try:
                self._remove(
                    action="REMOVE_TARGET",
                    image=str(entry["image"]),
                    tag=str(entry["harness_image_tag"]),
                    identity=instance,
                )
                self.current_instance = None
            except BaseException as cleanup_exc:
                cleanup_failures.append({
                    "identity": instance,
                    "error_type": type(cleanup_exc).__name__,
                    "error": str(cleanup_exc),
                })
        if self.support_resident:
            support_image, support_tag = self.support[0]
            try:
                self._remove(
                    action="REMOVE_SUPPORT",
                    image=support_image,
                    tag=support_tag,
                    identity="multi_swe_bench_support",
                )
                self.support_resident = False
            except BaseException as cleanup_exc:
                cleanup_failures.append({
                    "identity": "multi_swe_bench_support",
                    "error_type": type(cleanup_exc).__name__,
                    "error": str(cleanup_exc),
                })
        if cleanup_failures:
            self.status = "CLEANUP_FAILED"
            self.failure["cleanup_failures"] = cleanup_failures
        else:
            self.status = "FAILED"
        self._write_report()


def _smoke_targets(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise BenchmarkExecutionError("grader-smoke targets are missing")
    try:
        validate_serial_targets(
            matrix_kind=manifest.get("matrix_kind"),
            noop_baseline=manifest.get("noop_baseline"),
            targets=targets,
        )
    except SmokeProtocolError as exc:
        raise BenchmarkExecutionError(str(exc)) from exc
    if sha256_bytes(canonical_bytes(targets)) != manifest.get("target_set_sha256"):
        raise BenchmarkExecutionError("grader-smoke target-set digest mismatch")
    return [dict(target) for target in targets]


def _gold_patch(benchmark_id: str, row: Mapping[str, Any]) -> str:
    field = "patch" if benchmark_id == "swebench_verified" else "fix_patch"
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkExecutionError(f"frozen GOLD row lacks {field}")
    return value


def _patch_for_target(
    target: Mapping[str, Any], source: Mapping[str, Any], manifest: Mapping[str, Any]
) -> str:
    probe = target.get("probe")
    if probe == "GOLD":
        patch = _gold_patch(str(target.get("benchmark_id")), source)
    elif probe == "NOOP_BASELINE":
        if manifest.get("noop_baseline") != NOOP_BASELINE_LOCK:
            raise BenchmarkExecutionError("NOOP_BASELINE patch is not bound to the frozen manifest")
        patch = NOOP_BASELINE_PATCH.decode("utf-8")
    else:
        raise BenchmarkExecutionError(f"unsupported grader-smoke probe: {probe}")
    raw = patch.encode("utf-8")
    if not patch.strip() or not raw or sha256_bytes(raw) == EMPTY_PATCH_SHA256:
        raise BenchmarkExecutionError(f"grader-smoke refuses empty patch before evaluator: {target.get('target_id')}")
    return patch


def _rows_for_targets(targets: list[dict[str, Any]], cache: Path) -> dict[tuple[str, str], dict[str, Any]]:
    sources, _ = load_sources(cache)
    wanted = {(row["benchmark_id"], row["instance_id"]) for row in targets}
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for benchmark_id, rows in sources.items():
        for row in rows:
            key = (benchmark_id, instance_id(row))
            if key in wanted:
                if key in result:
                    raise BenchmarkExecutionError(f"duplicate official source row: {key}")
                result[key] = dict(row)
    if set(result) != wanted:
        raise BenchmarkExecutionError("official smoke source rows are missing")
    for target in targets:
        source = result[(target["benchmark_id"], target["instance_id"])]
        if row_hash(source) != target["source_row_sha256"]:
            raise BenchmarkExecutionError(f"official smoke source-row hash drift: {target['target_id']}")
    return result


def _run_git(
    args: list[str], *, cwd: Path | None = None, check: bool = True,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=120,
        env=dict(env) if env is not None else None,
    )
    if check and completed.returncode != 0:
        raise BenchmarkExecutionError(
            f"credential-free NOOP_BASELINE git audit failed: {' '.join(args[:3])}: "
            f"{completed.stderr.strip()}"
        )
    return completed


def _run_git_bytes(
    args: list[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=False, check=False, timeout=120,
        env=dict(env) if env is not None else None,
    )
    if completed.returncode != 0:
        raise BenchmarkExecutionError(
            f"credential-free NOOP_BASELINE git audit failed: {' '.join(args[:3])}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed


def audit_noop_baseline_checkouts(checkout_map_path: Path, output_path: Path) -> dict[str, Any]:
    """Prove the one frozen marker patch against six local exact-commit repositories."""

    manifest = read_json(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    targets = _smoke_targets(manifest)
    identity_targets = targets[0::2]
    mapping_document = read_json(checkout_map_path)
    repositories = mapping_document.get("repositories")
    expected_repositories = {target["repository"] for target in identity_targets}
    if (
        mapping_document.get("schema") != "trimem/noop-baseline-checkout-map/1.0"
        or not isinstance(repositories, dict)
        or set(repositories) != expected_repositories
        or any(not isinstance(path, str) or not path for path in repositories.values())
    ):
        raise BenchmarkExecutionError("NOOP_BASELINE checkout map must bind exactly six repositories")

    rows = []
    for target in identity_targets:
        source = Path(repositories[target["repository"]]).resolve()
        if not source.is_dir():
            raise BenchmarkExecutionError(f"NOOP_BASELINE source checkout is missing: {target['repository']}")
        commit = target["base_commit"]
        _run_git(["-C", str(source), "cat-file", "-e", f"{commit}^{{commit}}"])
        absent = _run_git(
            ["-C", str(source), "cat-file", "-e", f"{commit}:{NOOP_BASELINE_PATH}"],
            check=False,
        )
        if absent.returncode == 0:
            raise BenchmarkExecutionError(
                f"NOOP_BASELINE marker already exists at base commit: {target['instance_id']}"
            )
        base_tree = _run_git(
            ["-C", str(source), "rev-parse", f"{commit}^{{tree}}"]
        ).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="trimem-noop-baseline-audit-") as raw_temp:
            temp = Path(raw_temp)
            audit_env = {**os.environ, "GIT_INDEX_FILE": str(temp / "audit.index")}
            _run_git(["-C", str(source), "read-tree", commit], env=audit_env)
            patch_path = temp / "noop-baseline.patch"
            patch_path.write_bytes(NOOP_BASELINE_PATCH)
            _run_git(
                ["-C", str(source), "apply", "--cached", "--check", str(patch_path)],
                env=audit_env,
            )
            _run_git(
                ["-C", str(source), "apply", "--cached", str(patch_path)], env=audit_env,
            )
            changed = _run_git([
                "-C", str(source), "diff", "--cached", "--no-renames", "--name-status", commit,
            ], env=audit_env).stdout.splitlines()
            if changed != [f"A\t{NOOP_BASELINE_PATH}"]:
                raise BenchmarkExecutionError(
                    f"NOOP_BASELINE touched unexpected paths for {target['instance_id']}: {changed}"
                )
            marker = _run_git_bytes(
                ["-C", str(source), "show", f":0:{NOOP_BASELINE_PATH}"], env=audit_env,
            ).stdout
            if marker != NOOP_BASELINE_CONTENT:
                raise BenchmarkExecutionError(
                    f"NOOP_BASELINE marker bytes differ for {target['instance_id']}"
                )
        rows.append({
            "base_commit": commit,
            "base_tree": base_tree,
            "changed_paths": [NOOP_BASELINE_PATH],
            "forbidden_source_test_build_or_package_paths_touched": [],
            "isolated_temporary_index": True,
            "instance_id": target["instance_id"],
            "patch_applies_cached": True,
            "repository": target["repository"],
            "root_marker_absent_at_base": True,
            "staged_marker_sha256": sha256_bytes(marker),
        })
    body = {
        "schema": "trimem/noop-baseline-six-commit-audit/1.0",
        "manifest_target_set_sha256": manifest["target_set_sha256"],
        "noop_baseline": NOOP_BASELINE_LOCK,
        "rows": rows,
        "status": "PASS",
    }
    report = {**body, "audit_sha256": sha256_bytes(canonical_bytes(body))}
    write_json(output_path, report)
    return report


def _grader_test_evidence(
    grade: GradeResult,
    *,
    task_dir: Path,
    grader_root: Path,
    target: FrozenOfficialTarget,
    source_row: Mapping[str, Any],
    patch_raw: bytes,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, bool],
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    trimem = grade.report.get("_trimem") if isinstance(grade.report, Mapping) else None
    test_evidence = trimem.get("test_evidence") if isinstance(trimem, Mapping) else None
    if not isinstance(test_evidence, Mapping):
        raise BenchmarkExecutionError("official grader returned no actual test evidence")
    result = []
    raw_evidence: dict[str, bytes] = {}
    for name in ("test_output", "official_test_status"):
        source_reference = test_evidence.get(name)
        if not isinstance(source_reference, Mapping):
            raise BenchmarkExecutionError(f"official grader returned no {name} reference")
        relative = source_reference.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise BenchmarkExecutionError(f"official grader returned unsafe {name} reference")
        source = (grader_root / relative).resolve()
        if grader_root.resolve() not in source.parents or not source.is_file():
            raise BenchmarkExecutionError(f"official grader {name} evidence is missing")
        reference = evidence_reference(task_dir, source)
        if (
            reference.get("sha256") != source_reference.get("sha256")
            or reference.get("bytes") != source_reference.get("bytes")
            or reference.get("bytes", 0) <= 0
            or not source.read_bytes().strip()
        ):
            raise BenchmarkExecutionError(f"official grader {name} evidence digest/size mismatch")
        result.append(reference)
        raw_evidence[name] = source.read_bytes()
    summary = test_evidence.get("summary")
    if not isinstance(summary, Mapping):
        raise BenchmarkExecutionError("official grader returned no test-status summary")
    try:
        report_resolved = parse_official_report(target, grade.report)
        validated_summary = validate_official_test_evidence(
            target,
            source_row=source_row,
            test_output_raw=raw_evidence["test_output"],
            test_status_raw=raw_evidence["official_test_status"],
            resolved=grade.resolved,
        )
    except OfficialGraderError as exc:
        raise BenchmarkExecutionError(
            f"official grader test status/report did not validate: {exc}"
        ) from exc
    if (
        report_resolved is not grade.resolved
        or canonical_bytes(dict(summary)) != canonical_bytes(validated_summary)
    ):
        raise BenchmarkExecutionError(
            "official grader test status/report summary binding drift"
        )
    container_exit_ref: dict[str, Any] | None = None
    validated_exit_summary: dict[str, Any] | None = None
    if target.benchmark_id != "swebench_verified":
        source_reference = test_evidence.get("container_exit_status")
        source_summary = test_evidence.get("container_exit_summary")
        if not isinstance(source_reference, Mapping) or not isinstance(source_summary, Mapping):
            raise BenchmarkExecutionError(
                "official grader returned no Multi-SWE container exit evidence"
            )
        relative = source_reference.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise BenchmarkExecutionError(
                "official grader returned unsafe Multi-SWE container exit reference"
            )
        source = (grader_root / relative).resolve()
        if grader_root.resolve() not in source.parents or not source.is_file():
            raise BenchmarkExecutionError("official grader container exit evidence is missing")
        container_exit_ref = evidence_reference(task_dir, source)
        exit_raw = source.read_bytes()
        if (
            container_exit_ref.get("sha256") != source_reference.get("sha256")
            or container_exit_ref.get("bytes") != source_reference.get("bytes")
            or container_exit_ref.get("bytes", 0) <= 0
            or not exit_raw.strip()
        ):
            raise BenchmarkExecutionError(
                "official grader container exit evidence digest/size mismatch"
            )
        try:
            validated_exit_summary = validate_multi_swe_container_exit_status(
                target,
                raw=exit_raw,
                resolved=grade.resolved,
                test_summary=validated_summary,
                expected_patch=patch_raw.decode("utf-8"),
            )
        except (UnicodeDecodeError, OfficialGraderError) as exc:
            raise BenchmarkExecutionError(
                f"official grader container exit evidence did not validate: {exc}"
            ) from exc
        if canonical_bytes(dict(source_summary)) != canonical_bytes(validated_exit_summary):
            raise BenchmarkExecutionError(
                "official grader container exit summary binding drift"
            )
    elif "container_exit_status" in test_evidence or "container_exit_summary" in test_evidence:
        raise BenchmarkExecutionError("SWE-bench unexpectedly returned Multi-SWE exit evidence")
    return (
        result[0],
        result[1],
        validated_summary,
        {"patch_applied": True, "tests_executed": True},
        container_exit_ref,
        validated_exit_summary,
    )


def _run_smoke_impl(
    approval_path: Path,
    output_root: Path,
    image_evidence_root: Path,
    lifecycle_holder: list[_SerialImageLifecycle],
) -> dict[str, Any]:
    validate_benchmark_environment()
    approval_raw = approval_path.read_bytes()
    approval = validate_exec_approval("grader-smoke", approval_path)
    if sha256_bytes(approval_raw) != approval.get("approval_artifact_sha256"):
        raise BenchmarkExecutionError("exact external approval bytes/hash mismatch")
    manifest = read_json(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    targets = _smoke_targets(manifest)
    rows = _rows_for_targets(targets, ROOT / ".trimem-exec/datasets")
    images, support = image_entries(require_benchmark=False)
    harnesses = prepare_harnesses(ROOT / ".trimem-exec/harnesses")
    output_root.mkdir(parents=True, exist_ok=True)
    lifecycle = _SerialImageLifecycle(
        approval=approval,
        evidence_root=image_evidence_root,
        targets=targets,
        images=images,
        support=support,
    )
    lifecycle_holder.append(lifecycle)
    restricted_approval_path = output_root / "restricted-external-approval.json"
    restricted_approval_path.write_bytes(approval_raw)
    try:
        restricted_approval_path.chmod(0o600)
    except OSError:
        pass
    write_json(output_root / "external-approval-evidence.json", {
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "approved_request_sha256": approval["approved_request_sha256"],
        "approved_workflow_run_id": approval["approved_workflow_run_id"],
        "approved_workflow_run_attempt": approval["approved_workflow_run_attempt"],
        "freeze_sha256": approval["freeze_sha256"],
        "git_head": approval["git_head"],
        "phase": approval["phase"],
    })
    failures: list[str] = []
    infrastructure_failures: list[str] = []
    cell_evidence: list[dict[str, Any]] = []
    for index, target in enumerate(targets):
        lifecycle.before_target(index, target)
        source = rows[(target["benchmark_id"], target["instance_id"])]
        patch = _patch_for_target(target, source, manifest)
        patch_raw = patch.encode("utf-8")
        patch_sha256 = sha256_bytes(patch_raw)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target["target_id"])
        task_dir = output_root / f"{index:03d}-{safe}"
        task_dir.mkdir(parents=True, exist_ok=True)
        restricted_patch_path = task_dir / "restricted-input" / "applied.patch"
        restricted_patch_path.parent.mkdir(parents=True, exist_ok=True)
        restricted_patch_path.write_bytes(patch_raw)
        try:
            restricted_patch_path.chmod(0o600)
        except OSError:
            pass
        applied_patch_ref = evidence_reference(task_dir, restricted_patch_path)
        grader = grader_factory(
            target, source, images[target["instance_id"]], harnesses,
            task_dir / "official-grader", f"smoke-{target['probe'].lower()}", support,
        )
        request = GradeRequest(
            task_id=target["target_id"], repository=target["repository"],
            base_commit=target["base_commit"], patch=patch,
            workspace=WorkspaceGraderContext(
                kind="official-grader-smoke-private-patch",
                repository_files={}, base_commit=target["base_commit"],
            ),
        )
        try:
            grade = grader.grade(request)
            execution_status = "SUCCESS"
        except GraderInvocationFailure as exc:
            grade = exc.result
            execution_status = "FAILURE"
            failures.append(target["target_id"])
            infrastructure_failures.append(target["target_id"])
        if not (
            execution_status == "SUCCESS"
            and grade.exit_code == 0
            and grade.official is True
            and grade.container_started is True
            and grade.status == "success"
        ):
            failures.append(target["target_id"])
            infrastructure_failures.append(target["target_id"])
        stdout_path, stderr_path, report_path = (
            task_dir / "stdout.txt", task_dir / "stderr.txt", task_dir / "report.json"
        )
        stdout_path.write_text(grade.stdout, encoding="utf-8", newline="\n")
        stderr_path.write_text(grade.stderr, encoding="utf-8", newline="\n")
        write_json(report_path, grade.report)
        grader_root = task_dir / "official-grader"
        grader_target = getattr(grader, "target", None)
        if not isinstance(grader_target, FrozenOfficialTarget):
            raise BenchmarkExecutionError(
                "official grader gateway did not retain its frozen target"
            )
        execution_contract = _validated_execution_contract(
            grade, target=target, patch_raw=patch_raw
        )
        execution_contract_sha256 = sha256_bytes(canonical_bytes(execution_contract))
        execution_contract_path = task_dir / "execution-contract-evidence.json"
        write_json(execution_contract_path, {
            "schema": "trimem/grader-smoke-execution-contract-evidence/1.0",
            "target_id": target["target_id"],
            "execution_contract_sha256": execution_contract_sha256,
            "execution_contract": execution_contract,
        })
        execution_control = _validated_execution_control(
            grade, target=target, execution_contract=execution_contract
        )
        execution_control_sha256 = sha256_bytes(canonical_bytes(execution_control))
        execution_control_path = task_dir / "execution-control-evidence.json"
        write_json(execution_control_path, {
            "schema": "trimem/grader-smoke-execution-control-evidence/1.0",
            "target_id": target["target_id"],
            "execution_control_sha256": execution_control_sha256,
            "execution_control": execution_control,
        })
        submitted_patch_identity = _validated_submitted_patch_identity(
            grade,
            target=target,
            patch_raw=patch_raw,
            grader_root=grader_root,
            restricted_submitted_patch=applied_patch_ref,
        )
        submitted_patch_identity_sha256 = sha256_bytes(
            canonical_bytes(submitted_patch_identity)
        )
        submitted_patch_identity_path = (
            task_dir / "submitted-patch-identity-evidence.json"
        )
        write_json(submitted_patch_identity_path, {
            **submitted_patch_identity,
            "identity_evidence_sha256": submitted_patch_identity_sha256,
        })
        patch_path = task_dir / "patch-evidence.json"
        write_json(patch_path, {
            "schema": "trimem/grader-smoke-patch-evidence/1.0",
            "mode": "OFFICIAL_GRADER_SMOKE_PRIVATE_PATCH",
            "probe": target["probe"],
            "patch_bytes": len(patch_raw),
            "patch_nonempty": True,
            "patch_sha256": patch_sha256,
            "restricted_applied_patch": applied_patch_ref,
            "noop_baseline_changed_paths": (
                [NOOP_BASELINE_PATH] if target["probe"] == "NOOP_BASELINE" else None
            ),
            "source_row_sha256": target["source_row_sha256"],
            "applied_patch_bytes_retained": "RESTRICTED_EVIDENCE_ONLY",
            "gold_or_test_bytes_public": False,
        })
        try:
            observed = observed_target_digest(grade)
        except BenchmarkExecutionError:
            observed = "UNPROVEN"
            failures.append(target["target_id"])
            infrastructure_failures.append(target["target_id"])
        (
            test_output_ref,
            test_status_ref,
            test_summary,
            test_execution,
            container_exit_ref,
            container_exit_summary,
        ) = (
            _grader_test_evidence(
                grade,
                task_dir=task_dir,
                grader_root=grader_root,
                target=grader_target,
                source_row=source,
                patch_raw=patch_raw,
            )
        )
        trimem_report = grade.report.get("_trimem") if isinstance(grade.report, Mapping) else None
        if not isinstance(trimem_report, Mapping):
            raise BenchmarkExecutionError("official grader report has no evaluator evidence")
        tests_path = task_dir / "tests-evidence.json"
        write_json(tests_path, {
            "schema": "trimem/grader-smoke-tests-evidence/1.0",
            "official_test_status": {
                "bytes": test_status_ref["bytes"], "sha256": test_status_ref["sha256"],
            },
            "container_exit_status": (
                {
                    "bytes": container_exit_ref["bytes"],
                    "sha256": container_exit_ref["sha256"],
                }
                if container_exit_ref is not None
                else None
            ),
            "container_exit_summary": container_exit_summary,
            "probe": target["probe"],
            "summary": test_summary,
            "target_id": target["target_id"],
            "test_output": {
                "bytes": test_output_ref["bytes"], "sha256": test_output_ref["sha256"],
            },
        })
        container_path = task_dir / "container-evidence.json"
        write_json(container_path, {
            "schema": "trimem/grader-smoke-container-evidence/1.0",
            "container_digest": grade.container_digest,
            "container_started": grade.container_started,
            "container_exit_status_code": (
                container_exit_summary["status_code"]
                if container_exit_summary is not None
                else None
            ),
            "container_exit_status_sha256": (
                container_exit_ref["sha256"] if container_exit_ref is not None else None
            ),
            "exit_code": grade.exit_code,
            "official": grade.official,
            "status": grade.status,
            "target_id": target["target_id"],
        })
        evaluator_path = task_dir / "evaluator-evidence.json"
        write_json(evaluator_path, {
            "schema": "trimem/grader-smoke-evaluator-evidence/1.0",
            "benchmark_id": trimem_report.get("benchmark_id"),
            "dataset_revision": trimem_report.get("dataset_revision"),
            "grader_id": grade.grader_id,
            "harness_revision": trimem_report.get("harness_revision"),
            "source_row_sha256": trimem_report.get("source_row_sha256"),
            "target_id": target["target_id"],
        })
        digest_path = task_dir / "digest-evidence.json"
        write_json(digest_path, {
            "schema": "trimem/grader-smoke-digest-evidence/1.0",
            "container_digest": grade.container_digest,
            "expected_image_digest": images[target["instance_id"]]["expected_digest"],
            "observed_image_digest": observed,
            "target_id": target["target_id"],
        })
        expected_digest = images[target["instance_id"]]["expected_digest"]
        row_execution_evidence = {
            "patch_applied": test_execution["patch_applied"],
            "tests_executed": test_execution["tests_executed"],
            "digest_match": observed == expected_digest,
            "submitted_patch_identity": submitted_patch_identity[
                "submitted_patch_identity"
            ],
            "host_prepare_sh_access_count": execution_control[
                "host_prepare_script_reads"
            ],
            "source_image_build_count": execution_control[
                "source_image_build_calls"
            ],
            "api_calls": execution_contract["api_calls"],
            "container_exit_status_code": (
                container_exit_summary["status_code"]
                if container_exit_summary is not None
                else None
            ),
            "container_exit_acceptance": (
                container_exit_summary["acceptance"]
                if container_exit_summary is not None
                else None
            ),
            "container_exit_status_sha256": (
                container_exit_ref["sha256"]
                if container_exit_ref is not None
                else None
            ),
        }
        actual_accounting = {
            "api_calls": 0,
            "cached_input_tokens": 0,
            "decomposition_calls": 0,
            "extraction_calls": 0,
            "grader_calls": 1,
            "grader_containers": int(grade.container_started),
            "input_tokens": 0,
            "model_calls": 0,
            "model_gateway_calls": 0,
            "official_grader_runs": int(grade.official and grade.container_started),
            "output_tokens": 0,
            "paid_model_calls": 0,
            "reasoning_tokens": 0,
            "solve_calls": 0,
            "task_arm_runs": 0,
            "total_usd": 0,
        }
        record = {
            "target_id": target["target_id"],
            "benchmark_id": target["benchmark_id"],
            "order_index": target["order_index"],
            "arm": target["probe"],
            "probe": target["probe"],
            "execution_status": execution_status,
            "grader_exit_code": grade.exit_code,
            "grader_id": grade.grader_id,
            "grader_status": grade.status,
            "grader_container_digest": grade.container_digest,
            "container_started": grade.container_started,
            "container_exit_status_code": (
                container_exit_summary["status_code"]
                if container_exit_summary is not None
                else None
            ),
            "container_exit_status_sha256": (
                container_exit_ref["sha256"] if container_exit_ref is not None else None
            ),
            "official_grader": grade.official,
            "resolved": grade.resolved,
            "patch_bytes": len(patch_raw),
            "patch_sha256": patch_sha256,
            "expected_image_digest": images[target["instance_id"]]["expected_digest"],
            "observed_image_digest": observed,
            "execution_contract_sha256": execution_contract_sha256,
            "execution_control_sha256": execution_control_sha256,
            "submitted_patch_identity_sha256": submitted_patch_identity_sha256,
            "execution_evidence": row_execution_evidence,
            "actual_accounting": actual_accounting,
            "evidence": {
                "patch": evidence_reference(task_dir, patch_path),
                "tests": evidence_reference(task_dir, tests_path),
                "container": evidence_reference(task_dir, container_path),
                "evaluator": evidence_reference(task_dir, evaluator_path),
                "stdout": evidence_reference(task_dir, stdout_path),
                "stderr": evidence_reference(task_dir, stderr_path),
                "report": evidence_reference(task_dir, report_path),
                "digest": evidence_reference(task_dir, digest_path),
                "execution_contract": evidence_reference(
                    task_dir, execution_contract_path
                ),
                "execution_control": evidence_reference(
                    task_dir, execution_control_path
                ),
                "submitted_patch_identity": evidence_reference(
                    task_dir, submitted_patch_identity_path
                ),
                "applied_patch": applied_patch_ref,
                "test_output": test_output_ref,
                "official_test_status": test_status_ref,
                **(
                    {"container_exit_status": container_exit_ref}
                    if container_exit_ref is not None
                    else {}
                ),
                "restricted_grader_raw": restricted_evidence_references(
                    task_dir, grader_root
                ),
            },
        }
        write_json(task_dir / f"{safe}.result.json", record)
        cell_evidence.append({
            "target_id": target["target_id"],
            **row_execution_evidence,
            "actual_accounting": actual_accounting,
        })
        if grade.resolved is not target["expected_resolved"]:
            failures.append(target["target_id"])
        lifecycle.after_target(index, target)
    lifecycle.finish()
    report = _smoke_execution_summary(
        targets,
        cell_evidence,
        failures=failures,
        infrastructure_failures=infrastructure_failures,
    )
    write_json(output_root / "smoke-execution-summary.json", report)
    if report["failures"]:
        raise BenchmarkExecutionError(
            f"grader smoke failed closed: {report['failures']}"
        )
    return report


def run_smoke(
    approval_path: Path, output_root: Path, image_evidence_root: Path
) -> dict[str, Any]:
    lifecycle_holder: list[_SerialImageLifecycle] = []
    try:
        return _run_smoke_impl(
            approval_path, output_root, image_evidence_root, lifecycle_holder
        )
    except BaseException as exc:
        if lifecycle_holder:
            try:
                lifecycle_holder[0].abort(exc)
            except BaseException as cleanup_exc:
                if hasattr(exc, "add_note"):
                    exc.add_note(
                        "grader-smoke exact image cleanup/reporting also failed: "
                        f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                    )
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--image-evidence-dir", type=Path)
    parser.add_argument("--audit-checkout-map", type=Path)
    parser.add_argument("--audit-output", type=Path)
    args = parser.parse_args()
    try:
        audit_mode = args.audit_checkout_map is not None or args.audit_output is not None
        if audit_mode:
            if (
                args.audit_checkout_map is None
                or args.audit_output is None
                or args.approval_file is not None
                or args.output_dir is not None
                or args.image_evidence_dir is not None
            ):
                raise BenchmarkExecutionError(
                    "checkout audit requires only --audit-checkout-map and --audit-output"
                )
            report = audit_noop_baseline_checkouts(
                args.audit_checkout_map.resolve(), args.audit_output.resolve()
            )
        else:
            if (
                args.approval_file is None
                or args.output_dir is None
                or args.image_evidence_dir is None
            ):
                raise BenchmarkExecutionError(
                    "official smoke requires --approval-file, --output-dir, and "
                    "--image-evidence-dir"
                )
            report = run_smoke(
                args.approval_file.resolve(),
                args.output_dir.resolve(),
                args.image_evidence_dir.resolve(),
            )
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
