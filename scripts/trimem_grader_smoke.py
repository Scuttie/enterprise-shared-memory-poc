"""Run the frozen 6-instance/12-target official grader smoke after approval."""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


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
from enterprise_memory.trimem.accounting import strict_json_loads  # noqa: E402
from trimem_select_targets import canonical_bytes, instance_id, load_sources, row_hash  # noqa: E402
from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_CONTENT,
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATCH,
    NOOP_BASELINE_PATH,
    SmokeProtocolError,
    validate_serial_targets,
)
from trimem_grader_smoke_stage_evidence import (  # noqa: E402
    write_pre_cell_failure_evidence,
)
from trimem_grader_smoke_finalization import (  # noqa: E402
    AUTHORITY_PROMOTION_COMMITTED,
    AUTHORITY_PROMOTION_STARTED,
    SCIENTIFIC_AGGREGATE_REJECTED,
    write_finalization_journal,
)
from trimem_pull_locked_images import (  # noqa: E402
    pull_and_observe_image,
    remove_materialized_image,
)
from trimem_official_grader import (  # noqa: E402
    FrozenOfficialTarget,
    MULTI_FIX_PATCH_RUN_COMMAND,
    MULTI_HARNESS_REVISION,
    OFFICIAL_EVIDENCE_FIELDS,
    OFFICIAL_EVIDENCE_SCHEMA,
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
FAILURE_TAXONOMY_FIELDS = (
    "environment_failures",
    "infrastructure_failures",
    "image_lifecycle_failures",
    "official_harness_failures",
    "official_report_failures",
    "adapter_contract_failures",
    "aggregate_failures",
)
FAILURE_TAXONOMY_RULES = (
    {
        "counter": "image_lifecycle_failures",
        "exact_stages": (),
        "stage_prefixes": ("image_",),
        "fallback": False,
    },
    {
        "counter": "official_harness_failures",
        "exact_stages": ("official_harness",),
        "stage_prefixes": (),
        "fallback": False,
    },
    {
        "counter": "official_report_failures",
        "exact_stages": ("official_report",),
        "stage_prefixes": (),
        "fallback": False,
    },
    {
        "counter": "environment_failures",
        "exact_stages": (
            "approval_materialization",
            "benchmark_environment",
            "exec_gate",
            "protected_environment",
            "workflow_environment",
        ),
        "stage_prefixes": ("environment_",),
        "fallback": False,
    },
    {
        "counter": "infrastructure_failures",
        "exact_stages": (
            "official_grader_invocation",
            "terminal_evidence_persistence",
            "workflow_runner",
            "harness_preparation",
        ),
        "stage_prefixes": ("infrastructure_",),
        "fallback": False,
    },
    {
        "counter": "aggregate_failures",
        "exact_stages": (
            "aggregate",
            "scientific_aggregate",
            "scientific_outcome",
            "public_artifact",
            "attestation",
        ),
        "stage_prefixes": ("aggregate_",),
        "fallback": False,
    },
    {
        "counter": "adapter_contract_failures",
        "exact_stages": (),
        "stage_prefixes": (),
        "fallback": True,
    },
)
TERMINAL_CELL_SCHEMA = "trimem/grader-smoke-terminal-cell/2.0"
INVOCATION_INCOMPLETE_STATUS = "grader_invocation_incomplete"
TERMINAL_LIFECYCLE_FIELDS = (
    "target_id",
    "order_index",
    "probe",
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
    "official_final_report_resolved",
    "scientific_resolved",
    "primary_failure",
    "secondary_evidence_failures",
)
TERMINAL_CELL_FIELDS = frozenset({
    "schema",
    "target_id",
    "order_index",
    "probe",
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
    "official_final_report_resolved",
    "scientific_resolved",
    "primary_failure",
    "secondary_evidence_failures",
    "execution_status",
    "actual_accounting",
    "execution_evidence",
    "evidence",
})

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
        # The v2 adapter envelope is total, so SWE rows carry this key with a
        # canonical null value.  Only an actual materialized-patch claim is a
        # route contradiction.
        if materialized is not None:
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


def validate_adapter_evidence_envelope(
    grade: GradeResult,
    *,
    target: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the total success/failure envelope without success assumptions."""

    report = grade.report
    if not isinstance(report, Mapping):
        raise BenchmarkExecutionError("official grader report is not an object")
    allowed_top_level = {"task_id", "status", "failure_stage", "reason", "_trimem"}
    if set(report) != allowed_top_level:
        raise BenchmarkExecutionError("official grader public report field set drift")
    if report.get("task_id") != target.get("target_id") or grade.task_id != target.get(
        "target_id"
    ):
        raise BenchmarkExecutionError("official grader public report identity drift")
    trimem = report.get("_trimem")
    if not isinstance(trimem, Mapping) or set(trimem) != set(OFFICIAL_EVIDENCE_FIELDS):
        raise BenchmarkExecutionError("official grader total evidence envelope field set drift")
    envelope = dict(trimem)
    container_start_proven = any(
        envelope.get(name) is not None
        for name in ("container_exit_status", "test_output", "official_test_status")
    )
    if (
        envelope.get("schema") != OFFICIAL_EVIDENCE_SCHEMA
        or envelope.get("benchmark_id") != target.get("benchmark_id")
        or envelope.get("dataset_revision") != target.get("dataset_revision")
        or envelope.get("harness_revision")
        != (
            SWE_HARNESS_REVISION
            if target.get("benchmark_id") == "swebench_verified"
            else MULTI_HARNESS_REVISION
        )
        or envelope.get("source_row_sha256") != target.get("source_row_sha256")
        or type(grade.resolved) is not bool
        or type(envelope.get("adapter_normalized")) is not bool
        or (
            envelope.get("official_final_report_resolved") is not None
            and type(envelope.get("official_final_report_resolved")) is not bool
        )
        or (
            envelope.get("scientific_resolved") is not None
            and type(envelope.get("scientific_resolved")) is not bool
        )
        or not isinstance(envelope.get("adapter_secondary_evidence_failures"), list)
        or any(
            not isinstance(value, str) or not value
            for value in envelope.get("adapter_secondary_evidence_failures", [])
        )
        or envelope.get("harness_invocation_status")
        not in {"NOT_REACHED", "LAUNCH_FAILED", "TIMEOUT", "EXIT_NONZERO", "SUCCESS"}
        or envelope.get("report_invocation_status")
        not in {
            "NOT_REACHED",
            "NOT_RUN",
            "NOT_APPLICABLE",
            "LAUNCH_FAILED",
            "TIMEOUT",
            "EXIT_NONZERO",
            "SUCCESS",
        }
        or (grade.container_started is True) is not container_start_proven
    ):
        raise BenchmarkExecutionError("official grader total evidence envelope identity drift")
    if envelope["adapter_status"] == "SUCCESS":
        if (
            grade.status != "success"
            or report.get("status") != "success"
            or report.get("failure_stage") is not None
            or report.get("reason") is not None
            or envelope["adapter_failure_stage"] is not None
            or envelope["adapter_primary_error"] is not None
            or envelope["adapter_secondary_evidence_failures"] != []
            or envelope["adapter_normalized"] is not True
            or envelope["official_final_report_resolved"] is not grade.resolved
            or envelope["scientific_resolved"] is not grade.resolved
            or envelope["harness_invocation_status"] != "SUCCESS"
            or (
                target.get("benchmark_id") == "swebench_verified"
                and envelope["report_invocation_status"] != "NOT_APPLICABLE"
            )
            or (
                target.get("benchmark_id") != "swebench_verified"
                and envelope["report_invocation_status"] != "SUCCESS"
            )
        ):
            raise BenchmarkExecutionError("official grader success envelope is inconsistent")
    elif envelope["adapter_status"] == "FAILURE":
        primary = envelope.get("adapter_primary_error")
        if (
            grade.resolved is not False
            or envelope["adapter_normalized"] is not False
            or envelope["scientific_resolved"] is not None
            or not isinstance(primary, Mapping)
            or set(primary) != {"stage", "status", "reason"}
            or any(not isinstance(primary.get(name), str) or not primary[name] for name in primary)
            or primary.get("stage") != envelope.get("adapter_failure_stage")
            or report.get("failure_stage") != primary.get("stage")
            or report.get("reason") != primary.get("reason")
            or report.get("status") != primary.get("status")
            or grade.status != primary.get("status")
        ):
            raise BenchmarkExecutionError("official grader failure envelope is inconsistent")
    else:
        raise BenchmarkExecutionError("official grader adapter status is invalid")
    return envelope


def _failure_taxonomy_key(primary: Mapping[str, Any]) -> str:
    stage = str(primary.get("stage", ""))
    for rule in FAILURE_TAXONOMY_RULES:
        if (
            stage in rule["exact_stages"]
            or any(stage.startswith(prefix) for prefix in rule["stage_prefixes"])
            or rule["fallback"] is True
        ):
            return str(rule["counter"])
    raise AssertionError("failure taxonomy has no fail-closed fallback")


def failure_taxonomy(records: list[Mapping[str, Any]]) -> dict[str, int]:
    result = {name: 0 for name in FAILURE_TAXONOMY_FIELDS}
    for record in records:
        primary = record.get("primary_failure")
        if primary is None:
            continue
        if not isinstance(primary, Mapping):
            raise BenchmarkExecutionError("terminal primary failure is malformed")
        result[_failure_taxonomy_key(primary)] += 1
    return result


def build_terminal_cell_record(
    *,
    target: Mapping[str, Any],
    grade: GradeResult,
    envelope: Mapping[str, Any],
    execution_status: str,
    primary_failure: Mapping[str, Any] | None,
    secondary_evidence_failures: list[str],
    submitted_patch_identity_verified: bool,
    digest_verified: bool,
    evidence: Mapping[str, Any],
    execution_evidence: Mapping[str, Any],
    actual_accounting: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Production terminal builder: exactly one explicit lifecycle record per call."""

    adapter_normalized = envelope.get("adapter_normalized") is True
    official_outcome = envelope.get("official_final_report_resolved")
    scientific = envelope.get("scientific_resolved")
    primary_stage = (
        primary_failure.get("stage")
        if isinstance(primary_failure, Mapping)
        else None
    )
    scientific_mismatch = primary_stage == "scientific_outcome"
    record = {
        "schema": TERMINAL_CELL_SCHEMA,
        "target_id": target["target_id"],
        "order_index": target["order_index"],
        "probe": target["probe"],
        "grader_invoked": True,
        "container_started": grade.container_started is True,
        "harness_completed": envelope.get("harness_invocation_status")
        in {"SUCCESS", "EXIT_NONZERO"},
        # Report materialization and report interpretation are deliberately
        # separate lifecycle facts.  A malformed/unclassifiable raw report was
        # still generated and must remain visible as such.
        "final_report_generated": envelope.get("restricted_raw_report") is not None,
        "official_tests_executed": (
            envelope.get("container_exit_status") is not None
            or (
                envelope.get("harness_invocation_status")
                in {"SUCCESS", "EXIT_NONZERO"}
                and (
                    envelope.get("test_output") is not None
                    or envelope.get("official_test_status") is not None
                )
            )
        ),
        "raw_test_evidence_captured": (
            envelope.get("test_output") is not None
            and envelope.get("official_test_status") is not None
        ),
        "submitted_patch_identity_verified": submitted_patch_identity_verified,
        "digest_verified": digest_verified,
        "adapter_normalized": adapter_normalized,
        "authoritative_cell": False,
        "official_final_report_resolved": official_outcome,
        "scientific_resolved": (
            scientific
            if adapter_normalized
            and (primary_failure is None or scientific_mismatch)
            else None
        ),
        "primary_failure": dict(primary_failure) if primary_failure is not None else None,
        "secondary_evidence_failures": list(secondary_evidence_failures),
        "execution_status": execution_status,
        "actual_accounting": dict(actual_accounting),
        "execution_evidence": dict(execution_evidence),
        "evidence": dict(evidence),
    }
    if set(record) != set(TERMINAL_CELL_FIELDS):
        raise AssertionError("terminal cell base field drift")
    record.update(dict(extra or {}))
    if primary_failure is None:
        if not adapter_normalized or scientific is not grade.resolved:
            raise BenchmarkExecutionError("normalized terminal cell is internally inconsistent")
    elif scientific_mismatch:
        if (
            not adapter_normalized
            or execution_status != "FAILURE"
            or type(record["scientific_resolved"]) is not bool
            or record["scientific_resolved"] is not official_outcome
            or record["authoritative_cell"] is not False
        ):
            raise BenchmarkExecutionError(
                "scientific-mismatch terminal cell is internally inconsistent"
            )
    elif record["scientific_resolved"] is not None:
        raise BenchmarkExecutionError("failed terminal cell retained a scientific outcome")
    return record


def summarize_terminal_records(
    records: list[Mapping[str, Any]], *, expected_count: int
) -> dict[str, Any]:
    target_ids = [row.get("target_id") for row in records]
    lifecycle_flags = {
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
    }
    if (
        type(expected_count) is not int
        or expected_count < 0
        or len(records) > expected_count
        or any(not isinstance(value, str) or not value for value in target_ids)
        or len(target_ids) != len(set(target_ids))
        or any(
            row.get("schema") != TERMINAL_CELL_SCHEMA
            or not TERMINAL_CELL_FIELDS.issubset(row)
            or any(type(row.get(field)) is not bool for field in lifecycle_flags)
            for row in records
        )
    ):
        raise BenchmarkExecutionError("terminal record set is invalid or duplicated")
    for row in records:
        if row.get("authoritative_cell") is True and (
            row.get("execution_status") != "SUCCESS"
            or row.get("primary_failure") is not None
            or type(row.get("scientific_resolved")) is not bool
            or row.get("scientific_resolved")
            is not row.get("official_final_report_resolved")
            or any(row.get(field) is not True for field in lifecycle_flags - {"authoritative_cell"})
        ):
            raise BenchmarkExecutionError(
                "authoritative terminal cell lacks complete successful lifecycle evidence"
            )
    attempted = len(records)
    normalized = sum(row.get("adapter_normalized") is True for row in records)
    execution_evidence = sum(
        row.get("official_tests_executed") is True
        and row.get("raw_test_evidence_captured") is True
        for row in records
    )
    return {
        "attempted_cell_count": attempted,
        "terminal_record_count": attempted,
        # A runner-side invocation can fail before an official container starts.
        # Keep attempted calls and actual official executions as distinct facts.
        "official_execution_count": sum(
            row.get("container_started") is True for row in records
        ),
        "complete_execution_evidence_count": execution_evidence,
        "adapter_normalized_count": normalized,
        # Authority is a committed lifecycle fact written only after the whole
        # campaign (including exact image cleanup) succeeds.  Never infer it
        # from attempted/normalized counts.
        "authoritative_cell_count": sum(
            row.get("authoritative_cell") is True for row in records
        ),
        "unattempted_cell_count": max(0, expected_count - attempted),
        **failure_taxonomy(records),
    }


def _primary_failure_from_grade(
    grade: GradeResult,
    override: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    report = grade.report if isinstance(grade.report, Mapping) else {}
    raw_envelope = report.get("_trimem") if isinstance(report, Mapping) else None
    primary_raw = (
        raw_envelope.get("adapter_primary_error")
        if isinstance(raw_envelope, Mapping)
        else None
    )
    if override is not None:
        primary_raw = override
    if isinstance(primary_raw, Mapping) and set(primary_raw) == {
        "stage", "status", "reason"
    } and all(
        isinstance(primary_raw.get(name), str) and primary_raw[name]
        for name in ("stage", "status", "reason")
    ):
        return {
            name: str(primary_raw[name]) for name in ("stage", "status", "reason")
        }
    if override is not None:
        raise BenchmarkExecutionError("terminal primary-failure override is malformed")
    return {
        "stage": str(report.get("failure_stage") or "adapter_evidence"),
        "status": str(report.get("status") or grade.status or "adapter_contract_failed"),
        "reason": str(report.get("reason") or "official grader adapter failure"),
    }


def _adapter_primary_process_error(
    grade: GradeResult, secondary: BaseException
) -> BenchmarkExecutionError:
    primary = _primary_failure_from_grade(grade)
    return BenchmarkExecutionError(
        f"{primary['reason']}; secondary_evidence_failures="
        f"[{type(secondary).__name__}: {secondary}]"
    )


def _is_invocation_provisional(record: Mapping[str, Any]) -> bool:
    """Recognize the durable, deliberately conservative pre-call terminal."""

    primary = record.get("primary_failure")
    accounting = record.get("actual_accounting")
    evidence = record.get("evidence")
    return (
        record.get("schema") == TERMINAL_CELL_SCHEMA
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
        and record.get("execution_status") == "FAILURE"
        and isinstance(primary, Mapping)
        and primary.get("stage") == "official_grader_invocation"
        and primary.get("status") == INVOCATION_INCOMPLETE_STATUS
        and isinstance(accounting, Mapping)
        and accounting.get("grader_calls") == 1
        and accounting.get("grader_containers") == 0
        and accounting.get("official_grader_runs") == 0
        and isinstance(evidence, Mapping)
        and "applied_patch" in evidence
        and evidence.get("restricted_grader_raw") == []
    )


def _validate_terminal_evidence_bindings(
    *,
    task_dir: Path,
    grader_root: Path,
    record: Mapping[str, Any],
) -> None:
    """Re-read every terminal evidence reference before accepting it as final."""

    evidence = record.get("evidence")
    if not isinstance(evidence, Mapping):
        raise BenchmarkExecutionError("terminal evidence root is malformed")
    if "applied_patch" not in evidence:
        raise BenchmarkExecutionError("terminal applied-patch evidence is missing")

    root = task_dir.resolve(strict=True)

    def validate_reference(reference: Any, *, label: str) -> dict[str, Any]:
        if not isinstance(reference, Mapping) or set(reference) != {
            "path", "sha256", "bytes"
        }:
            raise BenchmarkExecutionError(f"{label} evidence reference is malformed")
        relative = reference.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or "\\" in relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or type(reference.get("bytes")) is not int
            or reference["bytes"] < 0
            or not isinstance(reference.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None
        ):
            raise BenchmarkExecutionError(f"{label} evidence reference is malformed")
        unresolved = task_dir / relative
        if unresolved.is_symlink():
            raise BenchmarkExecutionError(f"{label} evidence must not be a symlink")
        try:
            path = unresolved.resolve(strict=True)
        except OSError as exc:
            raise BenchmarkExecutionError(f"{label} evidence file is missing") from exc
        if root not in path.parents or not path.is_file():
            raise BenchmarkExecutionError(f"{label} evidence path escapes its task")
        try:
            observed = evidence_reference(task_dir, path)
        except OSError as exc:
            raise BenchmarkExecutionError(f"{label} evidence cannot be read") from exc
        expected = dict(reference)
        if observed != expected:
            raise BenchmarkExecutionError(f"{label} evidence bytes differ")
        return expected

    restricted = evidence.get("restricted_grader_raw")
    if not isinstance(restricted, list):
        raise BenchmarkExecutionError("terminal restricted grader evidence is malformed")
    for name, reference in evidence.items():
        if name == "restricted_grader_raw":
            continue
        validate_reference(reference, label=f"terminal {name}")
    observed_restricted = [
        validate_reference(reference, label="terminal restricted grader raw")
        for reference in restricted
    ]
    if len({row["path"] for row in observed_restricted}) != len(observed_restricted):
        raise BenchmarkExecutionError("terminal restricted grader evidence is duplicated")
    if not _is_invocation_provisional(record):
        try:
            expected_restricted = restricted_evidence_references(task_dir, grader_root)
        except OSError as exc:
            raise BenchmarkExecutionError(
                "terminal restricted grader evidence cannot be enumerated"
            ) from exc
        if observed_restricted != expected_restricted:
            raise BenchmarkExecutionError(
                "terminal restricted grader evidence is not the exact retained set"
            )
    if "report" not in evidence and (
        record.get("final_report_generated") is True
        or record.get("raw_test_evidence_captured") is True
        or record.get("adapter_normalized") is True
    ):
        raise BenchmarkExecutionError(
            "terminal lifecycle claims require retained report evidence"
        )


def _invocation_provisional_terminal(
    context: Mapping[str, Any],
) -> tuple[GradeResult, dict[str, Any]]:
    """Build the immutable terminal committed before gateway dispatch."""

    target = context["target"]
    if not isinstance(target, Mapping):
        raise BenchmarkExecutionError("provisional terminal target is malformed")
    error = BenchmarkExecutionError(
        "official grader invocation did not durably return a GradeResult"
    )
    grade = _unexpected_invocation_failure_grade(
        target, error, status=INVOCATION_INCOMPLETE_STATUS
    )
    raw_envelope = grade.report.get("_trimem")
    if not isinstance(raw_envelope, Mapping):
        raise AssertionError("runner provisional envelope is missing")
    envelope = dict(raw_envelope)
    actual_accounting = {
        field: int(field == "grader_calls") for field in SMOKE_ACCOUNTING_FIELDS
    }
    execution_evidence = {
        "patch_applied": False,
        "tests_executed": False,
        "digest_match": False,
        "submitted_patch_identity": False,
        "host_prepare_sh_access_count": 0,
        "source_image_build_count": 0,
        "api_calls": 0,
        "container_exit_status_code": None,
        "container_exit_acceptance": None,
        "container_exit_status_sha256": None,
    }
    primary = _primary_failure_from_grade(grade)
    terminal = build_terminal_cell_record(
        target=target,
        grade=grade,
        envelope=envelope,
        execution_status="FAILURE",
        primary_failure=primary,
        secondary_evidence_failures=[],
        submitted_patch_identity_verified=False,
        digest_verified=False,
        evidence={
            "applied_patch": dict(context["applied_patch_ref"]),
            "restricted_grader_raw": [],
        },
        execution_evidence=execution_evidence,
        actual_accounting=actual_accounting,
        extra={
            "benchmark_id": target["benchmark_id"],
            "arm": target["probe"],
            "grader_exit_code": grade.exit_code,
            "grader_id": grade.grader_id,
            "grader_status": grade.status,
            "grader_container_digest": grade.container_digest,
            "official_grader": grade.official,
            "resolved": False,
            "expected_image_digest": context["expected_image_digest"],
            "observed_image_digest": "UNPROVEN",
        },
    )
    return grade, terminal


def _persist_invocation_provisional(context: dict[str, Any]) -> dict[str, Any]:
    """Atomically commit and read back the logical invocation-start record."""

    result_path = context.get("result_path")
    task_dir = context.get("task_dir")
    grader_root = context.get("grader_root")
    if not all(isinstance(path, Path) for path in (result_path, task_dir, grader_root)):
        raise BenchmarkExecutionError("provisional terminal paths are malformed")
    grade, terminal = _invocation_provisional_terminal(context)
    write_json(result_path, terminal)
    try:
        persisted = strict_json_loads(result_path.read_bytes())
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise BenchmarkExecutionError(
            "provisional terminal read-back failed"
        ) from exc
    if persisted != terminal:
        raise BenchmarkExecutionError("provisional terminal read-back differs")
    summarize_terminal_records([persisted], expected_count=12)
    _validate_terminal_evidence_bindings(
        task_dir=task_dir,
        grader_root=grader_root,
        record=persisted,
    )
    context["grade"] = grade
    context["preserve_grade_primary"] = True
    return terminal


def _validated_grade_candidate(
    candidate: Any, *, target: Mapping[str, Any]
) -> GradeResult:
    if not isinstance(candidate, GradeResult):
        raise BenchmarkExecutionError(
            "official grader gateway returned a non-GradeResult value"
        )
    if candidate.task_id != target.get("target_id"):
        raise BenchmarkExecutionError("official grader gateway returned the wrong task identity")
    if type(candidate.resolved) is not bool:
        raise BenchmarkExecutionError(
            "official grader gateway returned a non-boolean resolved state"
        )
    if type(candidate.container_started) is not bool:
        raise BenchmarkExecutionError(
            "official grader gateway returned a non-boolean container-start state"
        )
    if candidate.status != "success" and candidate.resolved is not False:
        raise BenchmarkExecutionError(
            "non-success official grader result cannot claim resolved"
        )
    return candidate


def _failure_terminal_record(
    *,
    target: Mapping[str, Any],
    grade: GradeResult,
    patch_raw: bytes,
    task_dir: Path,
    grader_root: Path,
    applied_patch_ref: Mapping[str, Any],
    stdout_path: Path,
    stderr_path: Path,
    report_path: Path,
    expected_image_digest: str,
    primary_failure_override: Mapping[str, Any] | None = None,
    secondary_evidence_failures_extra: Sequence[str] = (),
) -> dict[str, Any]:
    """Preserve the primary adapter error while validating available evidence."""

    report = grade.report if isinstance(grade.report, Mapping) else {}
    raw_envelope = report.get("_trimem") if isinstance(report, Mapping) else None
    primary = _primary_failure_from_grade(grade, primary_failure_override)
    secondary: list[str] = list(secondary_evidence_failures_extra)
    if isinstance(raw_envelope, Mapping):
        adapter_secondary = raw_envelope.get("adapter_secondary_evidence_failures")
        if isinstance(adapter_secondary, list) and all(
            isinstance(value, str) and value for value in adapter_secondary
        ):
            secondary.extend(adapter_secondary)
    try:
        envelope = validate_adapter_evidence_envelope(grade, target=target)
    except BenchmarkExecutionError as exc:
        secondary.append(str(exc))
        envelope = dict(raw_envelope) if isinstance(raw_envelope, Mapping) else {}
        # A malformed secondary envelope must never promote a failed adapter
        # into a normalized/scientific result or mask the primary error.  Keep
        # the independently useful underlying official boolean when present.
        official_outcome = envelope.get("official_final_report_resolved")
        envelope["official_final_report_resolved"] = (
            official_outcome if type(official_outcome) is bool else None
        )
        envelope["adapter_normalized"] = False
        envelope["scientific_resolved"] = None

    contract: dict[str, Any] | None = None
    control: dict[str, Any] | None = None
    submitted_identity = False
    digest_verified = False
    try:
        contract = _validated_execution_contract(grade, target=target, patch_raw=patch_raw)
    except BenchmarkExecutionError as exc:
        secondary.append(str(exc))
    if contract is not None:
        try:
            control = _validated_execution_control(
                grade, target=target, execution_contract=contract
            )
        except BenchmarkExecutionError as exc:
            secondary.append(str(exc))
    try:
        _validated_submitted_patch_identity(
            grade,
            target=target,
            patch_raw=patch_raw,
            grader_root=grader_root,
            restricted_submitted_patch=applied_patch_ref,
        )
        submitted_identity = True
    except BenchmarkExecutionError as exc:
        secondary.append(str(exc))
    try:
        observed = observed_target_digest(grade)
        digest_verified = observed == expected_image_digest
        if not digest_verified:
            secondary.append("official grader image digest differs")
    except BenchmarkExecutionError as exc:
        observed = "UNPROVEN"
        secondary.append(str(exc))

    # A failed adapter has not completed the raw semantic/exit-status proof
    # required to assert these execution phases.  Submitted-patch identity only
    # proves which bytes were transported; it does not prove ``git apply`` ran.
    execution_evidence = {
        "patch_applied": False,
        "tests_executed": False,
        "digest_match": digest_verified,
        "submitted_patch_identity": submitted_identity,
        "host_prepare_sh_access_count": (
            control.get("host_prepare_script_reads", 0) if control is not None else 0
        ),
        "source_image_build_count": (
            control.get("source_image_build_calls", 0) if control is not None else 0
        ),
        "api_calls": contract.get("api_calls", 0) if contract is not None else 0,
        "container_exit_status_code": None,
        "container_exit_acceptance": None,
        "container_exit_status_sha256": None,
    }
    actual_accounting = {
        field: (
            1
            if field == "grader_calls"
            or (
                field in {"grader_containers", "official_grader_runs"}
                and grade.container_started is True
            )
            else 0
        )
        for field in SMOKE_ACCOUNTING_FIELDS
    }
    evidence: dict[str, Any] = {
        "applied_patch": dict(applied_patch_ref),
        "restricted_grader_raw": [],
    }
    for name, path in (
        ("stdout", stdout_path),
        ("stderr", stderr_path),
        ("report", report_path),
    ):
        try:
            evidence[name] = evidence_reference(task_dir, path)
        except (OSError, TypeError, ValueError, BenchmarkExecutionError) as exc:
            secondary.append(
                f"{name} evidence is unavailable: {type(exc).__name__}: {exc}"
            )
    restricted_root = grader_root / "restricted-evidence"
    if restricted_root.exists():
        for path in sorted(restricted_root.glob("*.bin")):
            try:
                evidence["restricted_grader_raw"].append(
                    evidence_reference(task_dir, path)
                )
            except (OSError, TypeError, ValueError, BenchmarkExecutionError) as exc:
                secondary.append(
                    "restricted grader evidence is unavailable: "
                    f"{type(exc).__name__}: {exc}"
                )

    terminal_grade = grade
    if "report" not in evidence:
        # Without the retained carrier there is no independently auditable map
        # from anonymous raw blobs to lifecycle/outcome fields.  Keep the
        # adapter's primary error, but clear all unprovable scientific claims.
        envelope = dict(envelope)
        envelope.update({
            "harness_invocation_status": "NOT_REACHED",
            "restricted_raw_report": None,
            "test_output": None,
            "official_test_status": None,
            "container_exit_status": None,
            "container_exit_summary": None,
            "semantic_normalization": None,
            "official_final_report_resolved": None,
            "adapter_normalized": False,
            "scientific_resolved": None,
        })
        terminal_grade = replace(grade, container_started=False)
        actual_accounting["grader_containers"] = 0
        actual_accounting["official_grader_runs"] = 0
        digest_verified = False
        observed = "UNPROVEN"
        secondary.append(
            "report evidence is unavailable; lifecycle and outcome claims were "
            "conservatively cleared"
        )
    return build_terminal_cell_record(
        target=target,
        grade=terminal_grade,
        envelope=envelope,
        execution_status="FAILURE",
        primary_failure=primary,
        secondary_evidence_failures=secondary,
        submitted_patch_identity_verified=submitted_identity,
        digest_verified=digest_verified,
        evidence=evidence,
        execution_evidence=execution_evidence,
        actual_accounting=actual_accounting,
        extra={
            "benchmark_id": target["benchmark_id"],
            "arm": target["probe"],
            "grader_exit_code": grade.exit_code,
            "grader_id": grade.grader_id,
            "grader_status": grade.status,
            "grader_container_digest": grade.container_digest,
            "official_grader": grade.official,
            "resolved": False,
            "expected_image_digest": expected_image_digest,
            "observed_image_digest": observed,
        },
    )


def _write_post_adapter_failure_terminal(
    context: Mapping[str, Any], error: BaseException
) -> dict[str, Any] | None:
    """Materialize one terminal record for a failure after ``grade`` returned.

    This path is intentionally best-effort at the ``run_smoke`` boundary.  The
    caller keeps and re-raises ``error`` even if secondary evidence validation
    or terminal serialization also fails.
    """

    result_path = context["result_path"]
    if not isinstance(result_path, Path):
        raise BenchmarkExecutionError("post-adapter terminal result path is malformed")
    grade = context.get("grade")
    if not isinstance(grade, GradeResult):
        raise BenchmarkExecutionError("post-adapter terminal grade result is missing")
    persistence_failures: list[str] = []
    if result_path.exists():
        try:
            existing = read_json(result_path)
            target = context["target"]
            expected_primary = context.get("primary_failure_override")
            if context.get("preserve_grade_primary") is True:
                expected_primary = _primary_failure_from_grade(grade)
            summarize_terminal_records([existing], expected_count=12)
            task_dir = context.get("task_dir")
            grader_root = context.get("grader_root")
            if not isinstance(task_dir, Path) or not isinstance(grader_root, Path):
                raise BenchmarkExecutionError(
                    "existing terminal evidence roots are malformed"
                )
            _validate_terminal_evidence_bindings(
                task_dir=task_dir,
                grader_root=grader_root,
                record=existing,
            )
            existing_is_provisional = _is_invocation_provisional(existing)
            report_path = context.get("report_path")
            current_report_reference = (
                evidence_reference(task_dir, report_path)
                if isinstance(task_dir, Path)
                and isinstance(report_path, Path)
                and report_path.is_file()
                else None
            )
            if (
                not isinstance(target, Mapping)
                or existing.get("target_id") != target.get("target_id")
                or existing.get("order_index") != target.get("order_index")
                or existing.get("probe") != target.get("probe")
                or existing.get("grader_invoked") is not True
                or existing.get("authoritative_cell") is not False
                or (
                    not existing_is_provisional
                    and isinstance(expected_primary, Mapping)
                    and existing.get("primary_failure") != dict(expected_primary)
                )
                or (
                    not existing_is_provisional
                    and current_report_reference is not None
                    and existing.get("evidence", {}).get("report")
                    != current_report_reference
                )
            ):
                raise BenchmarkExecutionError(
                    "existing terminal is not bound to the current invocation"
                )
            if not existing_is_provisional:
                return None
        except (OSError, ValueError, TypeError, BenchmarkExecutionError) as exc:
            persistence_failures.append(
                "existing terminal validation failed: "
                f"{type(exc).__name__}: {exc}"
            )
    for name, path, value, is_json in (
        ("stdout", context["stdout_path"], grade.stdout, False),
        ("stderr", context["stderr_path"], grade.stderr, False),
        ("report", context["report_path"], grade.report, True),
    ):
        if not isinstance(path, Path):
            persistence_failures.append(f"{name} evidence path is malformed")
            continue
        if path.exists():
            continue
        try:
            if is_json:
                write_json(path, value)
            else:
                path.write_text(str(value), encoding="utf-8", newline="\n")
        except (OSError, TypeError, ValueError) as exc:
            persistence_failures.append(
                f"{name} evidence persistence failed: {type(exc).__name__}: {exc}"
            )
    reason = str(error) or type(error).__name__
    preserve_grade_primary = context.get("preserve_grade_primary") is True
    primary_override = context.get("primary_failure_override")
    if primary_override is not None and not isinstance(primary_override, Mapping):
        raise BenchmarkExecutionError(
            "post-adapter terminal primary override is malformed"
        )
    post_adapter_stage = context.get("post_adapter_failure_stage")
    if not isinstance(post_adapter_stage, str) or not post_adapter_stage:
        post_adapter_stage = "smoke_post_adapter_validation"
    post_adapter_status = (
        "post_adapter_validation_failed"
        if post_adapter_stage == "smoke_post_adapter_validation"
        else post_adapter_stage + "_failed"
    )
    terminal = _failure_terminal_record(
        target=context["target"],
        grade=grade,
        patch_raw=context["patch_raw"],
        task_dir=context["task_dir"],
        grader_root=context["grader_root"],
        applied_patch_ref=context["applied_patch_ref"],
        stdout_path=context["stdout_path"],
        stderr_path=context["stderr_path"],
        report_path=context["report_path"],
        expected_image_digest=context["expected_image_digest"],
        primary_failure_override=(
            dict(primary_override)
            if isinstance(primary_override, Mapping)
            else None
            if preserve_grade_primary
            else {
                "stage": post_adapter_stage,
                "status": post_adapter_status,
                "reason": reason,
            }
        ),
        secondary_evidence_failures_extra=[
            *persistence_failures,
            *(
                ["post-invocation terminalization trigger: " + reason]
                if preserve_grade_primary or primary_override is not None
                else []
            ),
        ],
    )
    write_json(result_path, terminal)
    return terminal


def _unexpected_invocation_failure_grade(
    target: Mapping[str, Any],
    error: BaseException,
    *,
    status: str = "grader_invocation_unhandled",
) -> GradeResult:
    """Create a non-authoritative carrier when the gateway violates its API.

    The carrier is intentionally not a normalized adapter result.  It exists so
    that the runner can still write the one required terminal record and retain
    the original exception as the primary failure.
    """

    reason = str(error) or type(error).__name__
    if not status:
        raise BenchmarkExecutionError("runner fallback status must be non-empty")
    primary = {
        "stage": "official_grader_invocation",
        "status": status,
        "reason": reason,
    }
    envelope = {
        "schema": OFFICIAL_EVIDENCE_SCHEMA,
        "benchmark_id": target.get("benchmark_id"),
        "dataset_revision": target.get("dataset_revision"),
        "harness_revision": (
            SWE_HARNESS_REVISION
            if target.get("benchmark_id") == "swebench_verified"
            else MULTI_HARNESS_REVISION
        ),
        "source_row_sha256": target.get("source_row_sha256"),
        "execution_contract": None,
        "execution_control_evidence": None,
        "image_evidence": [],
        "invocation_argv": [],
        "harness_invocation_status": "NOT_REACHED",
        "report_invocation_argv": [],
        "report_invocation_status": "NOT_REACHED",
        "harness_restricted_raw_streams": None,
        "report_restricted_raw_streams": None,
        "materialized_private_inputs": [],
        "materialized_patch_evidence": None,
        "restricted_raw_report": None,
        "test_output": None,
        "official_test_status": None,
        "container_exit_status": None,
        "container_exit_summary": None,
        "semantic_normalization": None,
        "adapter_status": "FAILURE",
        "adapter_failure_stage": primary["stage"],
        "adapter_primary_error": primary,
        "adapter_secondary_evidence_failures": [],
        "official_final_report_resolved": None,
        "adapter_normalized": False,
        "scientific_resolved": None,
    }
    if set(envelope) != set(OFFICIAL_EVIDENCE_FIELDS):
        raise AssertionError("runner fallback evidence envelope field drift")
    return GradeResult(
        task_id=str(target["target_id"]),
        resolved=False,
        exit_code=-1,
        stdout="",
        stderr="",
        report={
            "task_id": target["target_id"],
            "status": status,
            "failure_stage": primary["stage"],
            "reason": reason,
            "_trimem": envelope,
        },
        grader_id="official-grader-unhandled-failure",
        container_digest=str(target.get("image", "UNPROVEN")),
        official=True,
        wall_time_ms=0,
        container_started=False,
        status=status,
    )


def _smoke_execution_summary(
    targets: list[dict[str, Any]],
    cell_evidence: list[dict[str, Any]],
    *,
    failures: list[str],
    terminal_records: list[Mapping[str, Any]] | None = None,
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
    terminal_summary = summarize_terminal_records(
        list(terminal_records or []), expected_count=expected_count
    )
    for field in (
        "attempted_cell_count",
        "terminal_record_count",
        "official_execution_count",
        "complete_execution_evidence_count",
        "adapter_normalized_count",
        "authoritative_cell_count",
    ):
        if terminal_summary[field] != expected_count:
            summary_failures.append(field.upper())
    if terminal_summary["unattempted_cell_count"] != 0:
        summary_failures.append("UNATTEMPTED_CELL_COUNT")
    for field in FAILURE_TAXONOMY_FIELDS:
        if terminal_summary[field] != 0:
            summary_failures.append(field.upper())
    distinct_failures = sorted(set(summary_failures))
    return {
        "schema": "trimem/grader-smoke-execution/2.0",
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
        **terminal_summary,
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
        if self.evidence_root.exists():
            if not self.evidence_root.is_dir() or any(self.evidence_root.iterdir()):
                raise BenchmarkExecutionError(
                    "grader-smoke image evidence root is not fresh"
                )
        else:
            self.evidence_root.mkdir(parents=True, exist_ok=False)

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
            event["action"] == "PULL_TARGET"
            or (
                event["action"] == "PULL_TARGET_FAILED"
                and event.get("pull_materialized") is True
            )
            for event in self.events
        )
        support_pulls = sum(
            event["action"] == "PULL_SUPPORT"
            or (
                event["action"] == "PULL_SUPPORT_FAILED"
                and event.get("pull_materialized") is True
            )
            for event in self.events
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

    def _stage_record(self, *, stage: str, image: str) -> dict[str, Any] | None:
        """Read this operation's own stage record for truthful failure metadata.

        This is runtime bookkeeping only.  The failure-closure builder later
        revalidates the same bytes and their raw-stream references against the
        immutable evidence inventory.
        """

        stage_root = self.evidence_root / f"{self.operation_index:03d}-{stage}"
        stage_path = stage_root / "stage.json"
        try:
            record = read_json(stage_path)
        except (BenchmarkExecutionError, OSError, UnicodeDecodeError, ValueError):
            return None
        expected_argv = (
            ["docker", "pull", image]
            if stage == "pull"
            else [
                "docker", "image", "inspect", "--format",
                "{{json .RepoDigests}}", image,
            ]
        )
        status = record.get("status")
        returncode = record.get("returncode")
        if (
            set(record)
            != {"argv", "returncode", "stage", "status", "stdout", "stderr"}
            or record.get("stage") != stage
            or record.get("argv") != expected_argv
            or status not in {"PASS", "NONZERO", "TIMEOUT", "LAUNCH_FAILURE"}
            or type(returncode) not in {int, type(None)}
            or not (
                (status == "PASS" and returncode == 0)
                or (status == "NONZERO" and type(returncode) is int and returncode != 0)
                or (
                    status in {"TIMEOUT", "LAUNCH_FAILURE"}
                    and returncode is None
                )
            )
        ):
            return None
        return record

    def _failure_stage(self, *, image: str) -> tuple[bool, str]:
        pull = self._stage_record(stage="pull", image=image)
        if pull is None:
            return False, "PULL_EVIDENCE"
        if pull["status"] != "PASS":
            return False, "PULL"

        inspect = self._stage_record(stage="inspect", image=image)
        if inspect is None:
            return True, "INSPECT_EVIDENCE"
        if inspect["status"] != "PASS":
            return True, "INSPECT"

        stdout = inspect.get("stdout")
        expected_path = f"{self.operation_index:03d}-inspect/stdout.txt"
        if (
            not isinstance(stdout, dict)
            or set(stdout) != {"bytes", "path", "sha256"}
            or stdout.get("path") != expected_path
        ):
            return True, "INSPECT_EVIDENCE"
        stdout_path = self.evidence_root / expected_path
        try:
            raw = stdout_path.read_bytes()
        except OSError:
            return True, "INSPECT_EVIDENCE"
        if (
            stdout.get("bytes") != len(raw)
            or stdout.get("sha256") != sha256_bytes(raw)
        ):
            return True, "INSPECT_EVIDENCE"
        try:
            repo_digests = strict_json_loads(raw)
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
                raise ValueError("RepoDigests is not an exact nonempty string list")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            return True, "INSPECT_OUTPUT"
        expected = image.rsplit("@", 1)[1]
        observed = {value.rsplit("@", 1)[-1] for value in repo_digests}
        if expected not in observed:
            return True, "DIGEST_VERIFICATION"
        return True, "UNEXPECTED_POST_INSPECT"

    def _pull(self, *, action: str, image: str, identity: str) -> None:
        try:
            record = pull_and_observe_image(
                image, self.evidence_root, self.operation_index
            )
        except BaseException as exc:
            pull_materialized, failure_stage = self._failure_stage(image=image)
            self.events.append({
                "action": action + "_FAILED",
                "identity": identity,
                "image": image,
                "pull_materialized": pull_materialized,
                "failure_stage": failure_stage,
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
    if not isinstance(trimem, Mapping):
        raise BenchmarkExecutionError("official grader returned no actual test evidence")
    result = []
    raw_evidence: dict[str, bytes] = {}
    for name in ("test_output", "official_test_status"):
        source_reference = trimem.get(name)
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
    summary = trimem.get("semantic_normalization")
    if not isinstance(summary, Mapping):
        raise BenchmarkExecutionError("official grader returned no test-status summary")
    raw_report_reference = trimem.get("restricted_raw_report")
    if not isinstance(raw_report_reference, Mapping):
        raise BenchmarkExecutionError("official grader returned no restricted final-report reference")
    report_relative = raw_report_reference.get("path")
    if (
        not isinstance(report_relative, str)
        or Path(report_relative).is_absolute()
        or ".." in Path(report_relative).parts
    ):
        raise BenchmarkExecutionError("official grader returned unsafe final-report reference")
    raw_report_path = (grader_root / report_relative).resolve()
    if grader_root.resolve() not in raw_report_path.parents or not raw_report_path.is_file():
        raise BenchmarkExecutionError("official grader restricted final report is missing")
    raw_report = raw_report_path.read_bytes()
    if (
        hashlib.sha256(raw_report).hexdigest() != raw_report_reference.get("sha256")
        or len(raw_report) != raw_report_reference.get("bytes")
    ):
        raise BenchmarkExecutionError("official grader final-report reference differs")
    try:
        final_report = read_json(raw_report_path)
    except (UnicodeDecodeError, json.JSONDecodeError, BenchmarkExecutionError) as exc:
        raise BenchmarkExecutionError("official grader final report is invalid JSON") from exc
    try:
        report_resolved = parse_official_report(target, final_report)
        validated_summary = validate_official_test_evidence(
            target,
            source_row=source_row,
            test_output_raw=raw_evidence["test_output"],
            test_status_raw=raw_evidence["official_test_status"],
            resolved=grade.resolved,
            final_report=final_report,
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
        source_reference = trimem.get("container_exit_status")
        source_summary = trimem.get("container_exit_summary")
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
    elif trimem.get("container_exit_status") is not None or trimem.get("container_exit_summary") is not None:
        raise BenchmarkExecutionError("SWE-bench unexpectedly returned Multi-SWE exit evidence")
    return (
        result[0],
        result[1],
        validated_summary,
        {"patch_applied": True, "tests_executed": True},
        container_exit_ref,
        validated_exit_summary,
    )


def _commit_authoritative_campaign(
    *,
    output_root: Path,
    terminal_records: list[tuple[Path, dict[str, Any]]],
    authority_candidates: list[dict[str, Any]],
    report: Mapping[str, Any],
) -> None:
    """Atomically replace the complete result tree with its authority=true view."""

    if len(terminal_records) != len(authority_candidates):
        raise BenchmarkExecutionError("authority candidate count differs")
    original_bindings: list[tuple[Path, bytes]] = []
    relatives: list[Path] = []
    for result_path, _record in terminal_records:
        resolved = result_path.resolve()
        if output_root.resolve() not in resolved.parents or not resolved.is_file():
            raise BenchmarkExecutionError("authority candidate path escaped result root")
        relative = resolved.relative_to(output_root.resolve())
        if relative in relatives:
            raise BenchmarkExecutionError("authority candidate path is duplicated")
        relatives.append(relative)
        original_bindings.append((resolved, resolved.read_bytes()))

    transaction_parent = Path(
        tempfile.mkdtemp(
            prefix=f".{output_root.name}.authority-promotion.",
            dir=output_root.parent,
        )
    )
    staged_root = transaction_parent / "replacement"
    backup_root = transaction_parent / "original"
    recovery_required = False
    try:
        shutil.copytree(output_root, staged_root, symlinks=True, copy_function=os.link)
        for relative, candidate in zip(relatives, authority_candidates, strict=True):
            staged_path = staged_root / relative
            staged_path.unlink()
            write_json(staged_path, candidate)
        write_json(staged_root / "smoke-execution-summary.json", dict(report))

        # Validate staged bytes and prove the live false-authority tree did not
        # change while hardlinked staging files were detached and rewritten.
        for (source_path, original_raw), relative, candidate in zip(
            original_bindings, relatives, authority_candidates, strict=True
        ):
            if source_path.read_bytes() != original_raw:
                raise BenchmarkExecutionError(
                    "terminal record changed during authority promotion staging"
                )
            if read_json(staged_root / relative) != candidate:
                raise BenchmarkExecutionError(
                    "staged authoritative terminal record differs"
                )
        if read_json(staged_root / "smoke-execution-summary.json") != dict(report):
            raise BenchmarkExecutionError("staged authoritative summary differs")

        os.replace(output_root, backup_root)
        try:
            os.replace(staged_root, output_root)
        except BaseException as promotion_exc:
            try:
                os.replace(backup_root, output_root)
            except BaseException as restoration_exc:
                recovery_required = True
                if hasattr(promotion_exc, "add_note"):
                    promotion_exc.add_note(
                        "authority-promotion backup restoration also failed; "
                        "private recovery tree retained: "
                        f"{type(restoration_exc).__name__}: {restoration_exc}"
                    )
            raise
    except (OSError, ValueError, BenchmarkExecutionError) as exc:
        raise BenchmarkExecutionError("atomic terminal authority promotion failed") from exc
    finally:
        if not recovery_required:
            try:
                shutil.rmtree(transaction_parent)
            except OSError:
                # A private sibling transaction tree is not part of the
                # canonical result root. The enclosing workflow inventories
                # and deletes the whole grader-smoke workspace before any
                # run-level attestation.
                pass


def _finalize_smoke_campaign(
    *,
    targets: list[dict[str, Any]],
    cell_evidence: list[dict[str, Any]],
    failures: list[str],
    terminal_records: list[tuple[Path, dict[str, Any]]],
    output_root: Path,
) -> dict[str, Any]:
    """Validate the whole campaign before committing per-cell authority."""

    authority_candidates = [
        {**record, "authoritative_cell": True}
        for _, record in terminal_records
    ]
    candidate_report = _smoke_execution_summary(
        targets,
        cell_evidence,
        failures=failures,
        terminal_records=authority_candidates,
    )
    if candidate_report["failures"]:
        write_finalization_journal(
            output_root,
            status=SCIENTIFIC_AGGREGATE_REJECTED,
            failures=candidate_report["failures"],
        )
        report = _smoke_execution_summary(
            targets,
            cell_evidence,
            failures=failures,
            terminal_records=[record for _, record in terminal_records],
        )
        write_json(output_root / "smoke-execution-summary.json", report)
        raise BenchmarkExecutionError(
            f"grader smoke failed closed: {candidate_report['failures']}"
        )
    report = candidate_report
    write_finalization_journal(
        output_root,
        status=AUTHORITY_PROMOTION_STARTED,
    )
    _commit_authoritative_campaign(
        output_root=output_root,
        terminal_records=terminal_records,
        authority_candidates=authority_candidates,
        report=report,
    )
    write_finalization_journal(
        output_root,
        status=AUTHORITY_PROMOTION_COMMITTED,
    )
    for (_result_path, record), candidate in zip(
        terminal_records, authority_candidates, strict=True
    ):
        record.clear()
        record.update(candidate)
    return report


def _run_smoke_impl(
    approval_path: Path,
    output_root: Path,
    image_evidence_root: Path,
    lifecycle_holder: list[_SerialImageLifecycle],
    terminal_failure_holder: list[dict[str, Any]],
) -> dict[str, Any]:
    approval_raw = approval_path.read_bytes()
    approval = validate_exec_approval("grader-smoke", approval_path)
    if sha256_bytes(approval_raw) != approval.get("approval_artifact_sha256"):
        raise BenchmarkExecutionError("exact external approval bytes/hash mismatch")
    # The protected workflow cleans this scoped path before execution.  A
    # pre-existing root is therefore stale evidence and must never be reused.
    output_root.mkdir(parents=True, exist_ok=False)
    approval_binding = {
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "approved_request_sha256": approval["approved_request_sha256"],
        "approved_workflow_run_id": approval["approved_workflow_run_id"],
        "approved_workflow_run_attempt": approval["approved_workflow_run_attempt"],
        "freeze_sha256": approval["freeze_sha256"],
        "git_head": approval["git_head"],
        "phase": approval["phase"],
    }

    def record_pre_cell_failure(stage: str, error: BaseException) -> None:
        reason = str(error).strip() or type(error).__name__
        try:
            write_pre_cell_failure_evidence(
                output_root,
                approval_binding=approval_binding,
                stage=stage,
                reason=reason,
            )
        except BaseException as evidence_error:
            if hasattr(error, "add_note"):
                error.add_note(
                    "pre-cell failure evidence also failed: "
                    f"{type(evidence_error).__name__}: {evidence_error}"
                )

    try:
        validate_benchmark_environment()
        manifest = read_json(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
        targets = _smoke_targets(manifest)
        rows = _rows_for_targets(targets, ROOT / ".trimem-exec/datasets")
        images, support = image_entries(require_benchmark=False)
    except BaseException as exc:
        record_pre_cell_failure("BENCHMARK_ENVIRONMENT_VALIDATION", exc)
        raise
    try:
        harnesses = prepare_harnesses(ROOT / ".trimem-exec/harnesses")
    except BaseException as exc:
        record_pre_cell_failure("HARNESS_PREPARATION", exc)
        raise
    try:
        restricted_approval_path = output_root / "restricted-external-approval.json"
        restricted_approval_path.write_bytes(approval_raw)
        try:
            restricted_approval_path.chmod(0o600)
        except OSError:
            pass
        write_json(output_root / "external-approval-evidence.json", approval_binding)

        # Prepare every deterministic cell before any image is pulled.  This
        # removes the prior gap where a patch/file/grader-constructor failure
        # after a successful pull had neither a terminal nor a truthful
        # pre-cell stage record.
        prepared_cells: list[dict[str, Any]] = []
        for index, target in enumerate(targets):
            source = rows[(target["benchmark_id"], target["instance_id"])]
            patch = _patch_for_target(target, source, manifest)
            patch_raw = patch.encode("utf-8")
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target["target_id"])
            task_dir = output_root / f"{index:03d}-{safe}"
            task_dir.mkdir(parents=True, exist_ok=False)
            restricted_patch_path = task_dir / "restricted-input" / "applied.patch"
            restricted_patch_path.parent.mkdir(parents=True, exist_ok=False)
            restricted_patch_path.write_bytes(patch_raw)
            try:
                restricted_patch_path.chmod(0o600)
            except OSError:
                pass
            applied_patch_ref = evidence_reference(task_dir, restricted_patch_path)
            grader = grader_factory(
                target,
                source,
                images[target["instance_id"]],
                harnesses,
                task_dir / "official-grader",
                f"smoke-{target['probe'].lower()}",
                support,
            )
            request = GradeRequest(
                task_id=target["target_id"],
                repository=target["repository"],
                base_commit=target["base_commit"],
                patch=patch,
                workspace=WorkspaceGraderContext(
                    kind="official-grader-smoke-private-patch",
                    repository_files={},
                    base_commit=target["base_commit"],
                ),
            )
            prepared_cells.append({
                "index": index,
                "target": target,
                "source": source,
                "patch": patch,
                "patch_raw": patch_raw,
                "patch_sha256": sha256_bytes(patch_raw),
                "safe": safe,
                "task_dir": task_dir,
                "applied_patch_ref": applied_patch_ref,
                "grader": grader,
                "request": request,
            })
    except BaseException as exc:
        record_pre_cell_failure("CELL_PREPARATION", exc)
        raise
    try:
        lifecycle = _SerialImageLifecycle(
            approval=approval,
            evidence_root=image_evidence_root,
            targets=targets,
            images=images,
            support=support,
        )
    except BaseException as exc:
        record_pre_cell_failure("IMAGE_LIFECYCLE_INITIALIZATION", exc)
        raise
    lifecycle_holder.append(lifecycle)
    failures: list[str] = []
    cell_evidence: list[dict[str, Any]] = []
    terminal_records: list[tuple[Path, dict[str, Any]]] = []
    for prepared in prepared_cells:
        index = prepared["index"]
        target = prepared["target"]
        source = prepared["source"]
        patch = prepared["patch"]
        patch_raw = prepared["patch_raw"]
        patch_sha256 = prepared["patch_sha256"]
        safe = prepared["safe"]
        task_dir = prepared["task_dir"]
        applied_patch_ref = prepared["applied_patch_ref"]
        grader = prepared["grader"]
        request = prepared["request"]
        terminal_failure_holder.clear()
        lifecycle.before_target(index, target)
        stdout_path, stderr_path, report_path = (
            task_dir / "stdout.txt", task_dir / "stderr.txt", task_dir / "report.json"
        )
        grader_root = task_dir / "official-grader"
        result_path = task_dir / f"{safe}.result.json"
        # Commit the conservative terminal before dispatch.  Its atomic durable
        # write defines logical invocation start, so abrupt process death during
        # the gateway call still leaves exactly one non-authoritative record.
        terminal_context: dict[str, Any] = {
            "target": target,
            "grade": None,
            "patch_raw": patch_raw,
            "task_dir": task_dir,
            "grader_root": grader_root,
            "applied_patch_ref": applied_patch_ref,
            "stdout_path": stdout_path,
            "stderr_path": stderr_path,
            "report_path": report_path,
            "expected_image_digest": images[target["instance_id"]][
                "expected_digest"
            ],
            "result_path": result_path,
            "preserve_grade_primary": False,
            "post_adapter_failure_stage": "terminal_evidence_persistence",
        }
        _persist_invocation_provisional(terminal_context)
        terminal_failure_holder.append(terminal_context)
        try:
            candidate = grader.grade(request)
            execution_status = "SUCCESS"
        except GraderInvocationFailure as exc:
            candidate = exc.result
            execution_status = "FAILURE"
        except BaseException as exc:
            grade = _unexpected_invocation_failure_grade(target, exc)
            terminal_context["grade"] = grade
            terminal_context["preserve_grade_primary"] = True
            raise
        try:
            grade = _validated_grade_candidate(candidate, target=target)
        except BaseException as exc:
            grade = _unexpected_invocation_failure_grade(target, exc)
            terminal_context["grade"] = grade
            terminal_context["preserve_grade_primary"] = True
            raise
        terminal_context["grade"] = grade
        terminal_context["preserve_grade_primary"] = execution_status == "FAILURE"
        if execution_status == "FAILURE":
            try:
                stdout_path.write_text(grade.stdout, encoding="utf-8", newline="\n")
                stderr_path.write_text(grade.stderr, encoding="utf-8", newline="\n")
                write_json(report_path, grade.report)
                grader_target = getattr(grader, "target", None)
                if not isinstance(grader_target, FrozenOfficialTarget):
                    raise BenchmarkExecutionError(
                        "official grader gateway did not retain its frozen target"
                    )
                terminal = _failure_terminal_record(
                    target=target,
                    grade=grade,
                    patch_raw=patch_raw,
                    task_dir=task_dir,
                    grader_root=grader_root,
                    applied_patch_ref=applied_patch_ref,
                    stdout_path=stdout_path,
                    stderr_path=stderr_path,
                    report_path=report_path,
                    expected_image_digest=images[target["instance_id"]][
                        "expected_digest"
                    ],
                )
                write_json(result_path, terminal)
            except BaseException as secondary:
                raise _adapter_primary_process_error(grade, secondary) from None
            primary = terminal["primary_failure"]
            secondary = terminal["secondary_evidence_failures"]
            raise BenchmarkExecutionError(
                f"{primary['reason']}; secondary_evidence_failures={secondary}"
            )
        stdout_path.write_text(grade.stdout, encoding="utf-8", newline="\n")
        stderr_path.write_text(grade.stderr, encoding="utf-8", newline="\n")
        write_json(report_path, grade.report)
        terminal_context["post_adapter_failure_stage"] = "adapter_evidence_validation"
        grader_target = getattr(grader, "target", None)
        if not isinstance(grader_target, FrozenOfficialTarget):
            raise BenchmarkExecutionError(
                "official grader gateway did not retain its frozen target"
            )
        if not (
            grade.exit_code == 0
            and grade.official is True
            and grade.container_started is True
            and grade.status == "success"
        ):
            raise BenchmarkExecutionError(
                "successful adapter result has invalid official execution status"
            )
        envelope = validate_adapter_evidence_envelope(grade, target=target)
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
        terminal_context["post_adapter_failure_stage"] = "image_digest_validation"
        observed = observed_target_digest(grade)
        if observed != images[target["instance_id"]]["expected_digest"]:
            raise BenchmarkExecutionError("official grader image digest differs")
        terminal_context["post_adapter_failure_stage"] = (
            "adapter_semantic_normalization"
        )
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
        terminal_context["post_adapter_failure_stage"] = "terminal_evidence_persistence"
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
        record_evidence = {
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
        }
        scientific_mismatch = grade.resolved is not target["expected_resolved"]
        scientific_primary = (
            {
                "stage": "scientific_outcome",
                "status": "expected_outcome_mismatch",
                "reason": (
                    "official final outcome differs from the frozen GOLD/NOOP expectation"
                ),
            }
            if scientific_mismatch
            else None
        )
        if scientific_primary is not None:
            # Freeze the already-known scientific primary before the first
            # terminal write.  A one-time persistence error must not replace
            # the official GOLD/NOOP mismatch at the outer terminal guard.
            terminal_context["primary_failure_override"] = scientific_primary
        record = build_terminal_cell_record(
            target=target,
            grade=grade,
            envelope=envelope,
            execution_status=("FAILURE" if scientific_mismatch else execution_status),
            primary_failure=scientific_primary,
            secondary_evidence_failures=[],
            submitted_patch_identity_verified=True,
            digest_verified=observed == images[target["instance_id"]]["expected_digest"],
            evidence=record_evidence,
            execution_evidence=row_execution_evidence,
            actual_accounting=actual_accounting,
            extra={
                "benchmark_id": target["benchmark_id"],
                "arm": target["probe"],
                "grader_exit_code": grade.exit_code,
                "grader_id": grade.grader_id,
                "grader_status": grade.status,
                "grader_container_digest": grade.container_digest,
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
            },
        )
        write_json(result_path, record)
        terminal_failure_holder.clear()
        terminal_records.append((result_path, record))
        cell_evidence.append({
            "target_id": target["target_id"],
            **row_execution_evidence,
            "actual_accounting": actual_accounting,
        })
        if scientific_mismatch:
            failures.append(target["target_id"])
            primary_message = (
                "TRIMEM_V1_GRADER_SMOKE_FAIL: frozen GOLD/NOOP outcome mismatch: "
                + target["target_id"]
            )
            post_mismatch_secondary: list[str] = []
            try:
                lifecycle.after_target(index, target)
            except BaseException as cleanup_exc:
                post_mismatch_secondary.append(
                    "post-mismatch image cleanup also failed: "
                    f"{type(cleanup_exc).__name__}: {cleanup_exc}"
                )
            try:
                failure_report = _smoke_execution_summary(
                    targets,
                    cell_evidence,
                    failures=failures,
                    terminal_records=[row for _, row in terminal_records],
                )
                write_json(
                    output_root / "smoke-execution-summary.json",
                    failure_report,
                )
            except BaseException as summary_exc:
                post_mismatch_secondary.append(
                    "post-mismatch summary materialization also failed: "
                    f"{type(summary_exc).__name__}: {summary_exc}"
                )
            if post_mismatch_secondary:
                record["secondary_evidence_failures"].extend(
                    post_mismatch_secondary
                )
                try:
                    write_json(result_path, record)
                except BaseException as persistence_exc:
                    post_mismatch_secondary.append(
                        "post-mismatch secondary evidence persistence also failed: "
                        f"{type(persistence_exc).__name__}: {persistence_exc}"
                    )
            primary_error = BenchmarkExecutionError(
                primary_message
                + (
                    "; secondary_evidence_failures="
                    + repr(post_mismatch_secondary)
                    if post_mismatch_secondary
                    else ""
                )
            )
            for note in post_mismatch_secondary:
                if hasattr(primary_error, "add_note"):
                    primary_error.add_note(note)
            raise primary_error
        lifecycle.after_target(index, target)
    if len(terminal_records) != len(targets):
        raise BenchmarkExecutionError("grader smoke terminal-record coverage is incomplete")
    lifecycle.finish()
    return _finalize_smoke_campaign(
        targets=targets,
        cell_evidence=cell_evidence,
        failures=failures,
        terminal_records=terminal_records,
        output_root=output_root,
    )


def run_smoke(
    approval_path: Path, output_root: Path, image_evidence_root: Path
) -> dict[str, Any]:
    lifecycle_holder: list[_SerialImageLifecycle] = []
    terminal_failure_holder: list[dict[str, Any]] = []
    try:
        return _run_smoke_impl(
            approval_path,
            output_root,
            image_evidence_root,
            lifecycle_holder,
            terminal_failure_holder,
        )
    except BaseException as exc:
        if terminal_failure_holder:
            try:
                _write_post_adapter_failure_terminal(
                    terminal_failure_holder[0], exc
                )
            except BaseException as terminal_exc:
                if hasattr(exc, "add_note"):
                    exc.add_note(
                        "grader-smoke post-adapter terminal materialization also failed: "
                        f"{type(terminal_exc).__name__}: {terminal_exc}"
                    )
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
