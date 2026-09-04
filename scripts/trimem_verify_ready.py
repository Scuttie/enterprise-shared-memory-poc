"""Fail-closed TriMem V1 readiness and external EXEC gate verifier.

The authoritative grader-smoke PASS remains historical viability evidence.
The one approved DEVELOPMENT_TUNING attempt later failed at its protected EXEC
gate before scientific execution, so that request/run is final and consumed;
no retry, replacement request, or later benchmark phase is authorized.
"""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter
from datetime import datetime
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.trimem.agent_runtime import TriMemAgentRuntime  # noqa: E402
from enterprise_memory.trimem.benchmark_seed import seed_benchmark_identities  # noqa: E402
from enterprise_memory.trimem.git_workspace import DockerSandboxCommandRunner, GitCheckoutWorkspaceFactory  # noqa: E402
from enterprise_memory.trimem.arms import CurrentV03MemoryController  # noqa: E402
from enterprise_memory.trimem.postgres_retrieval import production_v03_controller_factory  # noqa: E402
from enterprise_memory.trimem.production_runtime import BenchmarkArmSession, open_benchmark_arm  # noqa: E402
from enterprise_memory.trimem.production_v03_lifecycle import (  # noqa: E402
    LIVE_V03_IMPLEMENTATION_HASH,
    LIVE_V03_IMPLEMENTATION_MANIFEST,
    LiveV03Runtime,
    PostgresV03ExperienceLifecycle,
    production_v03_lifecycle_factory,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from trimem_benchmark_run import (  # noqa: E402
    AtomicBudgetLedger, BenchmarkExecutionError, BudgetedModelGateway, JournaledGraderGateway,
    JournaledModelGateway, validate_exec_approval,
)
from trimem_freeze import (  # noqa: E402
    FROZEN_PATHS,
    OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
    OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
    OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
    OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
    OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
    check_freeze,
)
from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_CONTENT,
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATH,
)
from trimem_grader_smoke_failure_evidence import (  # noqa: E402
    ENDPOINT as SMOKE_FAILURE_ENDPOINT,
    EVIDENCE_INVENTORY_PATH as P014_FAILURE_INVENTORY_PATH,
    FAILURE_RECEIPT_PATH as P014_FAILURE_RECEIPT_PATH,
    validate_committed_failure_evidence,
)
from trimem_grader_smoke_failure_closure import (  # noqa: E402
    ADAPTER_ENDPOINT as P015_ADAPTER_FAILURE_ENDPOINT,
    ENDPOINTS as P015_FAILURE_ENDPOINTS,
    FailureClosureError,
    INCOMPLETE_ENDPOINT as P015_INCOMPLETE_ENDPOINT,
    SCHEMA as P015_FAILURE_CLOSURE_SCHEMA,
    SCIENTIFIC_ENDPOINT as P015_SCIENTIFIC_FAILURE_ENDPOINT,
    validate_failure_closure,
)
from trimem_grader_smoke_authority import (  # noqa: E402
    CAUSE_TAXONOMY as AUTHORITY_ROLLBACK_CAUSE_TAXONOMY,
    PROMOTION_TRANSACTION_MARKER as AUTHORITY_PROMOTION_TRANSACTION_MARKER,
    RECOVERY_EVIDENCE_SCHEMA as AUTHORITY_RECOVERY_EVIDENCE_SCHEMA,
    ROLLBACK_TRANSACTION_MARKER as AUTHORITY_ROLLBACK_TRANSACTION_MARKER,
    ROLLBACK_EVIDENCE_SCHEMA as AUTHORITY_ROLLBACK_EVIDENCE_SCHEMA,
)
from trimem_grader_smoke_finalization import (  # noqa: E402
    AUTHORITY_PROMOTION_COMMITTED as FINALIZATION_AUTHORITY_COMMITTED,
    AUTHORITY_PROMOTION_STARTED as FINALIZATION_AUTHORITY_STARTED,
    EXPECTED_TERMINAL_RECORD_COUNT as FINALIZATION_TERMINAL_COUNT,
    RELATIVE_PATH as FINALIZATION_JOURNAL_RELATIVE_PATH,
    SCHEMA as FINALIZATION_JOURNAL_SCHEMA,
    SCIENTIFIC_AGGREGATE_REJECTED as FINALIZATION_SCIENTIFIC_REJECTED,
)
from trimem_grader_smoke_stage_evidence import (  # noqa: E402
    SCHEMA as PRE_CELL_FAILURE_SCHEMA,
    STAGE_TAXONOMY as PRE_CELL_STAGE_TAXONOMY,
    ZERO_EXECUTION as PRE_CELL_ZERO_EXECUTION,
    write_pre_cell_failure_evidence,
)
from trimem_grader_smoke_trigger_preflight import (  # noqa: E402
    BASELINE_CREDENTIAL_FREE_BUNDLE_SHA256,
    BASELINE_FROZEN_REQUEST_SHA256,
    BASELINE_IMAGE_LOCK_SHA256,
    BASELINE_PROTOCOL_SHA256,
    BASELINE_TARGET_SET_SHA256,
    CREDENTIAL_FREE_BUNDLE_PATH as GRADER_SMOKE_CREDENTIAL_BUNDLE_PATH,
    EXECUTION_CONTROL_AMENDMENT,
    FROZEN_REQUEST_PATH as GRADER_SMOKE_FROZEN_REQUEST_PATH,
    HISTORICAL_SENTINELS,
    IMAGE_LOCK_PATH as GRADER_SMOKE_IMAGE_LOCK_PATH,
    MULTI_SWE_PREBUILT_EVALUATION_CONTRACT_AMENDMENT,
    PROTOCOL_PATH as GRADER_SMOKE_PROTOCOL_PATH,
    REQUEST_ID as GRADER_SMOKE_REQUEST_ID,
    REQUEST_SCHEMA as GRADER_SMOKE_REQUEST_SCHEMA,
    SENTINEL_PATH as GRADER_SMOKE_SENTINEL_PATH,
    TriggerPreflightError,
    validate_request_document,
)
from trimem_development_trigger_preflight import (  # noqa: E402
    EARLIER_FAILURE_RECEIPT_PATH as DEVELOPMENT_EXEC_001_FAILURE_RECEIPT_PATH,
    EARLIER_SENTINEL_PATH as DEVELOPMENT_EXEC_001_SENTINEL_PATH,
    EXPECTED_RECOVERY_INPUT_SHA256 as DEVELOPMENT_RECOVERY_INPUT_SHA256,
    MIDDLE_SENTINEL_PATH as DEVELOPMENT_EXEC_002_SENTINEL_PATH,
    D12_SENTINEL_PATH as DEVELOPMENT_EXEC_003_SENTINEL_PATH,
    PREVIOUS_SENTINEL_PATH as DEVELOPMENT_EXEC_004_SENTINEL_PATH,
    RECOVERY_PROVENANCE as DEVELOPMENT_RECOVERY_PROVENANCE,
    RECOVERY_AUTHORIZATION as DEVELOPMENT_RECOVERY_AUTHORIZATION,
    REQUEST_ID as DEVELOPMENT_EXEC_005_REQUEST_ID,
    REQUIRED_EXTERNAL_AUTHORIZATION as DEVELOPMENT_EXEC_005_AUTHORIZATION,
    SENTINEL_PATH as DEVELOPMENT_EXEC_005_SENTINEL_PATH,
)
from trimem_development_trigger_d15 import (  # noqa: E402
    REQUEST_ID as DEVELOPMENT_REQUEST_ID,
    REQUIRED_EXTERNAL_AUTHORIZATION as DEVELOPMENT_EXECUTION_AUTHORIZATION,
    SENTINEL_PATH as DEVELOPMENT_SENTINEL_PATH,
    validate_sentinel_commit as validate_development_sentinel_commit,
)
from trimem_harness_lock import (  # noqa: E402
    HASH_BASIS as HARNESS_DEPENDENCY_HASH_BASIS,
    validate_harness_lock_configuration,
)
from trimem_install_pinned_gh import load_gh_cli_lock  # noqa: E402
from trimem_multi_swe_contract import validate_report_semantics_lock  # noqa: E402
from trimem_multi_swe_report_semantics import validate_public_summary  # noqa: E402
from trimem_official_grader import adapter_evidence_envelope_contract  # noqa: E402
from trimem_grader_smoke import (  # noqa: E402
    FAILURE_TAXONOMY_RULES as GRADER_SMOKE_FAILURE_TAXONOMY_RULES,
    FAILURE_TAXONOMY_FIELDS as GRADER_SMOKE_FAILURE_TAXONOMY_FIELDS,
    TERMINAL_CELL_FIELDS,
    TERMINAL_LIFECYCLE_FIELDS,
    TERMINAL_CELL_SCHEMA,
)
from trimem_public_artifact import SMOKE_OUTCOME_FIELDS  # noqa: E402
from trimem_smoke_attestation import (  # noqa: E402
    EXPECTED_REPOSITORY as SMOKE_ATTESTATION_REPOSITORY,
    HOSTED_RUNNER as SMOKE_ATTESTATION_RUNNER,
    SCHEMA as SMOKE_ATTESTATION_SCHEMA,
    SIGNER_WORKFLOW_PATH as SMOKE_ATTESTATION_WORKFLOW,
    SOURCE_REF_BY_EVENT as SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT,
)
from trimem_m2_candidates import CANDIDATE_IDS, load_bundle, validate_selected_m2  # noqa: E402
from trimem_verify_credential_free import verify_bundle  # noqa: E402


CONFIG = ROOT / "configs/trimem_v1"
ARTIFACT = ROOT / "artifacts/trimem_v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DIGEST_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")

SMOKE_RESULT_COMMON_FIELDS = {
    "schema", "status", "trimem_system_implementation", "grader_exec_package",
    "official_grader_viability", "performance", "expected_unique_instances",
    "expected_target_count", "expected_condition_rows", "actual_execution",
}
SMOKE_AGGREGATE_BODY_FIELDS = {
    "actual_accounting", "api_calls", "approval_binding",
    "adapter_normalized_count", "attempted_cell_count",
    "authoritative_cell_count",
    "complete_execution_evidence_count",
    "container_exit_status_captured_count",
    "container_exit_status_validated_count", "digest_match_count",
    "empty_patch_ids", "evidence_counts", "expected_target_count",
    "host_prepare_sh_access_count", "image_lifecycle",
    "manifest",
    "observed_target_count", "outcomes", "patch_applied_count",
    "official_execution_count", "probe_counts",
    "resolved_container_zero_exit_count", "resolved_counts",
    "source_image_build_count", "status", "submitted_patch_identity_count",
    "terminal_record_count", "tests_executed_count", "unattempted_cell_count",
    "unresolved_counts", *GRADER_SMOKE_FAILURE_TAXONOMY_FIELDS,
}
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
SMOKE_PUBLIC_ONLY_FIELDS = {
    "dataset_rows_or_gold_test_payloads", "restricted_evidence", "stream_totals",
    "verified_aggregate_sha256",
}
SMOKE_APPROVAL_FIELDS = {
    "approval_artifact_sha256", "approved_request_sha256",
    "approved_workflow_run_id", "approved_workflow_run_attempt", "freeze_sha256",
    "git_head", "phase",
}
SMOKE_EVIDENCE_FIELDS = {
    "public_result_path", "public_result_raw_sha256",
    "evidence_inventory_path", "evidence_inventory_raw_sha256",
    "verified_aggregate_sha256", "aggregate_raw_sha256", "approval_binding",
    "attestation_subject_path", "attestation_subject_raw_sha256",
    "attestation_bundle_path", "attestation_bundle_raw_sha256",
}
SMOKE_FAILURE_EVIDENCE_FIELDS = {
    "failure_receipt_path", "failure_receipt_raw_sha256",
    "evidence_inventory_path", "evidence_inventory_raw_sha256",
    "approval_binding",
}
SMOKE_RECOVERY_STATUS = "CORRECTION_READY_FOR_EXECUTION"
SMOKE_RECOVERY_ENDPOINT = (
    "TRIMEM_GRADER_SMOKE_REPORT_SEMANTICS_RECOVERY_READY"
)
SMOKE_RECOVERY_SCOPE = "P0.1.5_CORRECTION_BEFORE_EXEC_005"
SMOKE_RECOVERY_ACTUAL_EXECUTION = {
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
SMOKE_PASS_ENDPOINT = (
    "TRIMEM_V1_GRADER_SMOKE_PASS_READY_FOR_DEVELOPMENT_APPROVAL"
)
DEVELOPMENT_INCOMPLETE_ENDPOINT = "TRIMEM_V1_DEV_INCOMPLETE"
DEVELOPMENT_EXEC_001_FAILURE_RECEIPT_RAW_SHA256 = (
    "16bda3012e29d6a3659d5a96537615db7ed72fa817e541e16db2c4d5d5d79868"
)
DEVELOPMENT_EXEC_001_REQUEST_RAW_SHA256 = (
    "7501c630a05ab0b87b9b510a72a5389f6ea7046dee6153b583e2833fa8e7e1db"
)
DEVELOPMENT_EXEC_001_HEAD = "6eba1b0f9462c3b29323a9ade290470551bfd0ed"
DEVELOPMENT_EXEC_001_RUN_ID = 33_727_051_040
DEVELOPMENT_EXEC_001_RUN_ATTEMPT = 1
DEVELOPMENT_EXEC_001_FAILURE_LABEL = (
    "TRIMEM_DEV_TRIGGER_PREFLIGHT_DEPENDENCY_IMPORT_FAILURE"
)
DEVELOPMENT_EXEC_001_RECOVERY_AUTHORIZATION = (
    "TRIMEM_V1_DEV_PREFLIGHT_RECOVERY_002_APPROVED_ONCE"
)
DEVELOPMENT_EXEC_001_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_APPROVED_ONCE"
)
DEVELOPMENT_EXEC_002_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_002"
DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-002/"
    "protected-exec-gate-failure-receipt.json"
)
DEVELOPMENT_EXEC_002_FAILURE_REPORT_PATH = (
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_002_PROTECTED_GATE_FAILURE.md"
)
DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_RAW_SHA256 = (
    "8c9d4a8fea70e0088b7af9bb011e1e75081f4e9ddee9f7162cf05ff85c9f9d1a"
)
DEVELOPMENT_EXEC_002_FAILURE_REPORT_RAW_SHA256 = (
    "cd6b5d53493854510b931625ea3bde6296351ed6b72f1274c8933b8915520719"
)
DEVELOPMENT_EXEC_002_HEAD = "c2738cae074351927dde117b628c601b1e296cf2"
DEVELOPMENT_EXEC_002_SOURCE_HEAD = "98dd37fec7c826f6ed5b3b8734f2ca8dcab96e4a"
DEVELOPMENT_EXEC_002_RUN_ID = 33_739_545_314
DEVELOPMENT_EXEC_002_RUN_ATTEMPT = 1
DEVELOPMENT_EXEC_002_COUNTER_SCOPE = (
    "DEVELOPMENT_TUNING_EXEC_002_RUN_33739545314_ATTEMPT_1"
)
DEVELOPMENT_EXEC_002_REQUEST_RAW_SHA256 = (
    "c81c57a5c93d4be9efdc971147191d8bc2e1bc2f06fe241e38ce36b6a4ee3f98"
)
DEVELOPMENT_EXEC_002_FAILURE_LABEL = "TRIMEM_DEV_EXEC_GATE_GH_CLI_MISSING"
DEVELOPMENT_EXEC_002_ACCOUNTING = {
    "api_calls": 0,
    "cached_input_tokens": 0,
    "decomposition_calls": 0,
    "extraction_calls": 0,
    "grader_calls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "model_calls": 0,
    "model_gateway_calls": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "reasoning_tokens": 0,
    "solve_calls": 0,
    "support_service_containers": 2,
    "support_service_image_pulls": 2,
    "target_image_pulls": 0,
    "task_arm_runs": 0,
    "total_usd": 0.0,
}
DEVELOPMENT_EXEC_003_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_003"
DEVELOPMENT_EXEC_003_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-003/"
    "model-parser-failure-receipt.json"
)
DEVELOPMENT_EXEC_003_REQUEST_RAW_SHA256 = (
    "3d6b4291f7a1ab8b72203e4756a2f7e4614c1139c9f6e0da74a3a949fa78ca56"
)
DEVELOPMENT_EXEC_003_FAILURE_RECEIPT_RAW_SHA256 = (
    "6fbfbf4bf169e6365439f25bb7ea14bcac114e30fde9df1f814c93ba8ebc75be"
)
DEVELOPMENT_EXEC_003_HEAD = "bc70e1979c2987cd52347b2ef2fd7c43dc3014df"
DEVELOPMENT_EXEC_003_SOURCE_HEAD = "763cec6c399714151860aebabc93bdbeac2e1cff"
DEVELOPMENT_EXEC_003_RUN_ID = 33_788_493_773
DEVELOPMENT_EXEC_003_RUN_ATTEMPT = 1
DEVELOPMENT_EXEC_003_FAILURE_SUBTYPE = (
    "TRIMEM_DEV_FIRST_DECOMPOSITION_EMPTY_EXTRACTED_TEXT"
)
DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-004/"
    "provider-incomplete-max-output-tokens-receipt.json"
)
DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_RAW_SHA256 = (
    "393bff5c1a518ea2ea487ff1c940152bc9d2e618ab300fd05fadacc179c933fc"
)
DEVELOPMENT_EXEC_004_REQUEST_RAW_SHA256 = (
    "20bccf63d7f09e4130e7297bc0b1c07b4d97f15baefa77099b582e105874dd80"
)
DEVELOPMENT_EXEC_004_HEAD = "795c589c7da0b815bbe4f6188191fd0165f85649"
DEVELOPMENT_EXEC_004_SOURCE_HEAD = "ded36427f03b60256305a32266fd0537f3602798"
DEVELOPMENT_EXEC_004_RUN_ID = 33_840_007_588
DEVELOPMENT_EXEC_004_RUN_ATTEMPT = 1
DEVELOPMENT_EXEC_004_FAILURE_SUBTYPE = (
    "TRIMEM_DEV_FIRST_TASK_SOLVE_RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"
)
DEVELOPMENT_EXEC_005_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-005/"
    "http-auth-error-receipt.json"
)
DEVELOPMENT_EXEC_005_FAILURE_RECEIPT_RAW_SHA256 = (
    "951f99472bdca153878f48ce1b18b11990e8125c15b47d529df508760939d42d"
)
DEVELOPMENT_EXEC_005_REQUEST_RAW_SHA256 = (
    "97e2ce227418ace0db1edbf816391cdf0fda4f8d29359da4a3f81687f1aa19de"
)
DEVELOPMENT_EXEC_005_HEAD = "57db1a21fca3b036a64629c439ca196fb1606638"
DEVELOPMENT_EXEC_005_SOURCE_HEAD = "5e80da790db0aa5b7cf1a8ce29020fedad7f6254"
DEVELOPMENT_EXEC_005_RUN_ID = 33_859_839_836
DEVELOPMENT_EXEC_005_RUN_ATTEMPT = 1
DEVELOPMENT_EXEC_005_FAILURE_SUBTYPE = (
    "TRIMEM_DEV_FIRST_DECOMPOSITION_HTTP_AUTH_ERROR"
)
SMOKE_PASS_READINESS_SCOPE = "P0.1.5_EXEC_005_AUTHORITATIVE_PASS"
SMOKE_PASS_SCIENTIFIC_RESULT = (
    "GOLD_RESOLVED_6_OF_6_AND_NOOP_UNRESOLVED_6_OF_6"
)
SMOKE_PASS_SUCCESS_EVIDENCE_SCHEMA = (
    "trimem/grader-smoke-readiness-success-evidence/1.0"
)
SMOKE_PASS_FAILURE_CLOSURE_STATUS_SCHEMA = (
    "trimem/grader-smoke-failure-closure-status/1.0"
)
SMOKE_PASS_RUN_ID = "33674784590"
SMOKE_PASS_RUN_ATTEMPT = "1"
SMOKE_PASS_EXECUTION_HEAD = "cc001245b8c26373b5467a0dbdcbbbda0a9542be"
P015_FAILURE_RESULT_SCHEMA = "trimem/grader-smoke-result/1.2"
P014_FAILURE_RECEIPT_RAW_SHA256 = (
    "fe9f98a07be06d7c5ee56110b0bc2058e9271f26ef0086b2232332aa7da42978"
)
P014_EVIDENCE_INVENTORY_RAW_SHA256 = (
    "c61ffdff2ab8857e8ebd212df9d8190b9424ebafd0c3a092b91de3a311108004"
)
SMOKE_ATTESTATION_POLICY_PATH = "configs/trimem_v1/smoke_attestation_policy.json"
SMOKE_TRUSTED_ROOT_PATH = "configs/trimem_v1/sigstore_trusted_root.jsonl"
SMOKE_GH_CLI_LOCK_PATH = "configs/trimem_v1/gh_cli_lock.json"
SMOKE_ATTESTATION_ACTION = (
    "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6"
)
SMOKE_PROTECTED_ENVIRONMENT_OID = "1.3.6.1.4.1.57264.1.23"
SMOKE_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
SMOKE_GH_VERSION_LINE = load_gh_cli_lock(
    ROOT / SMOKE_GH_CLI_LOCK_PATH
)["expected_first_version_line"]
SMOKE_GITHUB_API_ACCEPT = "application/vnd.github+json"
SMOKE_GITHUB_API_VERSION = "2022-11-28"
SMOKE_RUN_API_ROUTE_TEMPLATE = (
    "repos/{repository}/actions/runs/{run_id}/attempts/{run_attempt}"
)
SMOKE_RUN_API_JSON_PROJECTION = (
    "{id,run_attempt,event,status,conclusion,head_sha,head_branch,path,"
    "workflow_id,repository_full_name:.repository.full_name}"
)
ATTESTATION_ONLY_EXECUTION = {
    "api_calls": 0,
    "database_operations": 0,
    "decomposition_calls": 0,
    "docker_image_pulls": 0,
    "extraction_calls": 0,
    "grader_calls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "model_calls": 0,
    "model_gateway_calls": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "reasoning_tokens": 0,
    "solve_calls": 0,
    "support_service_containers": 0,
    "support_service_image_pulls": 0,
    "target_image_pulls": 0,
    "task_arm_runs": 0,
    "total_usd": 0,
}


def _smoke_cert_identity(source_ref: str) -> str:
    return (
        f"https://github.com/{SMOKE_ATTESTATION_REPOSITORY}/"
        f"{SMOKE_ATTESTATION_WORKFLOW}@{source_ref}"
    )


class ReadinessError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid UTF-8 JSON: {path.relative_to(ROOT).as_posix()}") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"JSON root is not an object: {path.relative_to(ROOT).as_posix()}")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessError(message)


def _pretty_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _strict_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ReadinessError(f"duplicate JSON key in {label}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=strict_object,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ReadinessError(f"non-finite JSON number in {label}: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid UTF-8 JSON: {label}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {label}")
    return value


def _historical_git_file(commit: str, relative: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(
        completed.returncode == 0,
        f"official smoke execution commit lacks {relative}",
    )
    return completed.stdout


def _execution_head_is_ancestor(commit: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _validate_historical_smoke_request(
    execution_head: str, raw: bytes
) -> dict[str, Any]:
    request = _strict_json_bytes(raw, label="historical grader-smoke request")
    source_head = request.get("source_head")
    require(
        isinstance(source_head, str) and HEX40.fullmatch(source_head) is not None,
        "historical grader-smoke request source_head is invalid",
    )
    try:
        return validate_request_document(
            ROOT,
            raw,
            expected_source_head=source_head,
            material_commit=execution_head,
        )
    except (OSError, TriggerPreflightError) as exc:
        raise ReadinessError(
            f"historical grader-smoke sentinel validation failed: {exc}"
        ) from None


def _inventory_rows(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require(
        set(inventory)
        == {"schema", "root", "files", "total_bytes", "total_files", "inventory_sha256"},
        "official smoke evidence inventory field set differs",
    )
    files = inventory.get("files")
    require(isinstance(files, list) and bool(files), "official smoke evidence inventory is empty")
    rows: dict[str, dict[str, Any]] = {}
    for row in files:
        require(
            isinstance(row, dict)
            and set(row) == {"path", "sha256", "bytes"}
            and isinstance(row.get("path"), str)
            and bool(row["path"])
            and not Path(row["path"]).is_absolute()
            and ".." not in Path(row["path"]).parts
            and isinstance(row.get("sha256"), str)
            and HEX64.fullmatch(row["sha256"]) is not None
            and type(row.get("bytes")) is int
            and row["bytes"] >= 0,
            "official smoke evidence inventory row is malformed",
        )
        require(row["path"] not in rows, "official smoke evidence inventory has duplicate paths")
        rows[row["path"]] = row
    require(
        list(rows) == sorted(rows),
        "official smoke evidence inventory path order differs",
    )
    payload = {
        "files": files,
        "root": inventory.get("root"),
        "schema": inventory.get("schema"),
        "total_bytes": inventory.get("total_bytes"),
        "total_files": inventory.get("total_files"),
    }
    require(
        inventory.get("schema") == "trimem/restricted-evidence-inventory/1.0"
        and inventory.get("root") == "grader_smoke_exec"
        and type(inventory.get("total_files")) is int
        and inventory["total_files"] == len(files)
        and type(inventory.get("total_bytes")) is int
        and inventory["total_bytes"] == sum(row["bytes"] for row in files)
        and inventory.get("inventory_sha256")
        == hashlib.sha256(canonical(payload)).hexdigest(),
        "official smoke evidence inventory seal/counts differ",
    )
    return rows


def _require_inventory_raw(
    rows: Mapping[str, Mapping[str, Any]], path: str, raw: bytes, *, label: str
) -> None:
    row = rows.get(path)
    require(
        isinstance(row, Mapping)
        and row.get("sha256") == hashlib.sha256(raw).hexdigest()
        and row.get("bytes") == len(raw),
        f"official smoke inventory {label} raw binding differs",
    )


def validate_smoke_attestation_policy() -> dict[str, Any]:
    """Validate the pre-execution trust root and verification policy bytes."""

    policy = read_json(ROOT / SMOKE_ATTESTATION_POLICY_PATH)
    require(
        set(policy)
        == {
            "attestation_action", "certificate_policy", "expected_repository",
            "schema", "signer_workflow", "source_ref_by_event", "trusted_root",
            "verification",
        },
        "smoke attestation policy field set differs",
    )
    require(
        policy.get("schema") == "trimem/smoke-attestation-policy/1.0"
        and policy.get("expected_repository") == SMOKE_ATTESTATION_REPOSITORY
        and policy.get("source_ref_by_event") == SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT
        and policy.get("signer_workflow") == SMOKE_ATTESTATION_WORKFLOW
        and policy.get("attestation_action")
        == {
            "exact_uses": SMOKE_ATTESTATION_ACTION,
            "inputs": {
                "create-storage-record": False,
                "push-to-registry": False,
                "subject-path": "${{ runner.temp }}/attestation-subject.json",
            },
        },
        "smoke attestation identity/action policy differs",
    )
    certificate_policy = policy.get("certificate_policy")
    require(
        certificate_policy
        == {
            "oidc_issuer": SMOKE_OIDC_ISSUER,
            "protected_environment": "trimem-grader-smoke-exec",
            "protected_environment_oid": SMOKE_PROTECTED_ENVIRONMENT_OID,
            "runner_environment": SMOKE_ATTESTATION_RUNNER,
            "runner_invocation_uri_template": (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                "actions/runs/{run_id}/attempts/{run_attempt}"
            ),
        },
        "smoke attestation certificate policy differs",
    )
    verification = policy.get("verification")
    required_flags = [
        "--bundle", "--cert-identity", "--cert-oidc-issuer",
        "--custom-trusted-root", "--digest-alg=sha256",
        "--deny-self-hosted-runners", "--format=json",
        "--predicate-type=https://slsa.dev/provenance/v1", "--repo",
        "--signer-digest", "--source-digest", "--source-ref",
    ]
    require(
        isinstance(verification, dict)
        and set(verification)
        == {
            "cryptographic_gate_phases", "gh_cli_tcb", "live_run_attempt",
            "required_cli_flags", "static_scope", "trusted_root_mutation_after_smoke",
        }
        and verification.get("cryptographic_gate_phases")
        == ["DEVELOPMENT_TUNING", "HELDOUT_BENCHMARK"]
        and verification.get("gh_cli_tcb")
        == {
            "exact_version_first_line": SMOKE_GH_VERSION_LINE,
            "trust_boundary": (
                "trusted host/runner installation plus exact version; executable "
                "bytes are neither vendored nor byte-pinned"
            ),
        }
        and verification.get("live_run_attempt")
        == {
            "accept": SMOKE_GITHUB_API_ACCEPT,
            "api_version": SMOKE_GITHUB_API_VERSION,
            "api_route_template": SMOKE_RUN_API_ROUTE_TEMPLATE,
            "authentication": (
                "GH_TOKEN from github.token scoped to the benchmark EXEC gate step only"
            ),
            "exact_conclusion": "success",
            "exact_status": "completed",
            "json_projection": SMOKE_RUN_API_JSON_PROJECTION,
            "transport": "gh api --hostname github.com",
        }
        and verification.get("required_cli_flags") == required_flags
        and verification.get("trusted_root_mutation_after_smoke") == "PROHIBITED"
        and isinstance(verification.get("static_scope"), str)
        and "no cryptographic viability claim" in verification["static_scope"],
        "smoke attestation verification policy differs",
    )

    trusted = policy.get("trusted_root")
    trusted_path = ROOT / SMOKE_TRUSTED_ROOT_PATH
    trusted_raw = trusted_path.read_bytes()
    require(
        isinstance(trusted, dict)
        and set(trusted)
        == {
            "bytes", "generated_at_utc", "generated_by", "generator", "line_count",
            "path", "raw_sha256", "source",
        }
        and trusted.get("path") == SMOKE_TRUSTED_ROOT_PATH
        and trusted.get("generated_by") == "gh attestation trusted-root"
        and trusted.get("generator") == "gh version 2.97.0 (2026-07-31)"
        and trusted.get("source")
        == "https://cli.github.com/manual/gh_attestation_trusted-root"
        and trusted.get("bytes") == len(trusted_raw)
        and trusted.get("raw_sha256") == hashlib.sha256(trusted_raw).hexdigest()
        and trusted.get("line_count") == 2
        and isinstance(trusted.get("generated_at_utc"), str)
        and trusted["generated_at_utc"].endswith("Z"),
        "pre-frozen Sigstore trusted-root provenance/hash differs",
    )
    require(
        trusted_raw.endswith(b"\n") and b"\r" not in trusted_raw,
        "pre-frozen Sigstore trusted-root is not exact LF JSONL",
    )
    lines = trusted_raw.splitlines()
    require(len(lines) == 2 and all(lines), "Sigstore trusted-root line set differs")
    for index, raw in enumerate(lines):
        root = _strict_json_bytes(raw, label=f"{SMOKE_TRUSTED_ROOT_PATH}:{index + 1}")
        require(
            root.get("mediaType")
            == "application/vnd.dev.sigstore.trustedroot+json;version=0.1"
            and isinstance(root.get("certificateAuthorities"), list)
            and bool(root["certificateAuthorities"]),
            f"Sigstore trusted-root line {index + 1} is malformed",
        )
    return policy


def _decode_utf8_extension(raw: bytes, *, oid: str) -> str:
    """Decode Fulcio's DER UTF8String extension (legacy raw UTF-8 is rejected)."""

    require(len(raw) >= 2 and raw[0] == 0x0C, f"certificate OID {oid} is not DER UTF8String")
    first_length = raw[1]
    if first_length < 0x80:
        length, offset = first_length, 2
    elif first_length == 0x81:
        require(
            len(raw) >= 3 and raw[2] >= 0x80,
            f"certificate OID {oid} DER length is nonminimal",
        )
        length, offset = raw[2], 3
    elif first_length == 0x82:
        require(
            len(raw) >= 4 and raw[2] != 0,
            f"certificate OID {oid} DER length is nonminimal",
        )
        length = int.from_bytes(raw[2:4], "big")
        require(length >= 0x100, f"certificate OID {oid} DER length is nonminimal")
        offset = 4
    else:
        raise ReadinessError(f"certificate OID {oid} DER length form is invalid")
    require(
        offset + length == len(raw),
        f"certificate OID {oid} DER payload length differs",
    )
    try:
        return raw[offset:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReadinessError(f"certificate OID {oid} is not UTF-8") from exc


def _bundle_statement(bundle: Mapping[str, Any]) -> dict[str, Any]:
    envelope = bundle.get("dsseEnvelope")
    require(
        isinstance(envelope, Mapping)
        and set(envelope) == {"payload", "payloadType", "signatures"}
        and envelope.get("payloadType") == "application/vnd.in-toto+json"
        and isinstance(envelope.get("signatures"), list)
        and len(envelope["signatures"]) == 1
        and isinstance(envelope["signatures"][0], Mapping)
        and isinstance(envelope["signatures"][0].get("sig"), str)
        and bool(envelope["signatures"][0]["sig"]),
        "official smoke attestation DSSE envelope differs",
    )
    try:
        payload = base64.b64decode(str(envelope.get("payload", "")), validate=True)
    except ValueError as exc:
        raise ReadinessError("official smoke attestation DSSE payload is invalid base64") from exc
    return _strict_json_bytes(payload, label="official smoke attestation DSSE statement")


def _bundle_certificate_bindings(bundle: Mapping[str, Any]) -> dict[str, str]:
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID, ObjectIdentifier
    except ImportError as exc:
        raise ReadinessError("cryptography is required to inspect the attestation certificate") from exc

    verification = bundle.get("verificationMaterial")
    require(isinstance(verification, Mapping), "attestation verification material is missing")
    certificate = verification.get("certificate")
    require(
        isinstance(certificate, Mapping)
        and set(certificate) == {"rawBytes"}
        and isinstance(certificate.get("rawBytes"), str),
        "attestation leaf certificate field set differs",
    )
    try:
        der = base64.b64decode(certificate["rawBytes"], validate=True)
        leaf = x509.load_der_x509_certificate(der)
    except (ValueError, TypeError) as exc:
        raise ReadinessError("attestation leaf certificate is invalid DER/base64") from exc
    try:
        names = leaf.extensions.get_extension_for_oid(
            ExtensionOID.SUBJECT_ALTERNATIVE_NAME
        ).value.get_values_for_type(x509.UniformResourceIdentifier)
    except x509.ExtensionNotFound as exc:
        raise ReadinessError("attestation certificate lacks URI SAN") from exc
    require(
        len(names) == 1 and isinstance(names[0], str) and bool(names[0]),
        "attestation certificate URI SAN cardinality differs",
    )

    oid_names = {
        "issuer": "1.3.6.1.4.1.57264.1.8",
        "buildSignerURI": "1.3.6.1.4.1.57264.1.9",
        "buildSignerDigest": "1.3.6.1.4.1.57264.1.10",
        "runnerEnvironment": "1.3.6.1.4.1.57264.1.11",
        "sourceRepositoryURI": "1.3.6.1.4.1.57264.1.12",
        "sourceRepositoryDigest": "1.3.6.1.4.1.57264.1.13",
        "sourceRepositoryRef": "1.3.6.1.4.1.57264.1.14",
        "buildConfigURI": "1.3.6.1.4.1.57264.1.18",
        "buildConfigDigest": "1.3.6.1.4.1.57264.1.19",
        "buildTrigger": "1.3.6.1.4.1.57264.1.20",
        "runInvocationURI": "1.3.6.1.4.1.57264.1.21",
        "sourceRepositoryVisibilityAtSigning": "1.3.6.1.4.1.57264.1.22",
        "protectedEnvironment": SMOKE_PROTECTED_ENVIRONMENT_OID,
    }
    result = {"subjectAlternativeName": names[0]}
    for name, oid in oid_names.items():
        try:
            value = leaf.extensions.get_extension_for_oid(
                ObjectIdentifier(oid)
            ).value.value
        except x509.ExtensionNotFound as exc:
            raise ReadinessError(f"attestation certificate lacks required OID {oid}") from exc
        require(isinstance(value, bytes), f"attestation certificate OID {oid} has invalid value")
        result[name] = _decode_utf8_extension(value, oid=oid)
    return result


def _expected_certificate_bindings(subject: Mapping[str, Any]) -> dict[str, str]:
    execution = subject["execution"]
    cert_identity = _smoke_cert_identity(execution["source_ref"])
    run_uri = (
        f"https://github.com/{SMOKE_ATTESTATION_REPOSITORY}/actions/runs/"
        f"{execution['workflow_run_id']}/attempts/{execution['workflow_run_attempt']}"
    )
    return {
        "subjectAlternativeName": cert_identity,
        "issuer": SMOKE_OIDC_ISSUER,
        "buildSignerURI": cert_identity,
        "buildSignerDigest": execution["source_digest"],
        "runnerEnvironment": SMOKE_ATTESTATION_RUNNER,
        "sourceRepositoryURI": f"https://github.com/{SMOKE_ATTESTATION_REPOSITORY}",
        "sourceRepositoryDigest": execution["source_digest"],
        "sourceRepositoryRef": execution["source_ref"],
        "buildConfigURI": cert_identity,
        "buildConfigDigest": execution["source_digest"],
        "buildTrigger": execution["event_name"],
        "runInvocationURI": run_uri,
        "sourceRepositoryVisibilityAtSigning": "public",
        "protectedEnvironment": "trimem-grader-smoke-exec",
    }


def _validate_attestation_artifacts(
    *,
    subject_raw: bytes,
    bundle_raw: bytes,
    public_raw: bytes,
    inventory_raw: bytes,
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    subject = _strict_json_bytes(
        subject_raw, label=OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
    )
    require(
        set(subject) == {"approval_binding", "artifacts", "execution", "schema"}
        and subject.get("schema") == SMOKE_ATTESTATION_SCHEMA
        and subject_raw == _pretty_json(subject)
        and subject.get("approval_binding") == approval,
        "official smoke deterministic attestation subject differs",
    )
    execution = subject.get("execution")
    require(
        isinstance(execution, dict)
        and set(execution)
        == {
            "event_name", "repository", "runner_environment", "signer_workflow",
            "source_digest", "source_ref", "workflow_run_attempt", "workflow_run_id",
        }
        and execution.get("repository") == SMOKE_ATTESTATION_REPOSITORY
        and execution.get("runner_environment") == SMOKE_ATTESTATION_RUNNER
        and execution.get("signer_workflow") == SMOKE_ATTESTATION_WORKFLOW
        and execution.get("source_digest") == approval.get("git_head")
        and SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT.get(execution.get("event_name"))
        == execution.get("source_ref")
        and execution.get("workflow_run_id")
        == approval.get("approved_workflow_run_id")
        and execution.get("workflow_run_attempt")
        == approval.get("approved_workflow_run_attempt"),
        "official smoke attestation execution/approval identity differs",
    )
    artifacts = subject.get("artifacts")
    require(
        isinstance(artifacts, dict)
        and set(artifacts)
        == {
            "encrypted_restricted_evidence", "evidence_inventory", "public_results",
        },
        "official smoke attestation artifact set differs",
    )
    expected_artifacts = {
        "public_results": ("public-results.json", public_raw),
        "evidence_inventory": ("evidence-inventory.json", inventory_raw),
    }
    for key, (name, raw) in expected_artifacts.items():
        require(
            artifacts.get(key)
            == {
                "bytes": len(raw),
                "name": name,
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            f"official smoke attestation {key} exact bytes/hash differs",
        )
    encrypted = artifacts.get("encrypted_restricted_evidence")
    require(
        isinstance(encrypted, dict)
        and set(encrypted) == {"bytes", "name", "sha256"}
        and encrypted.get("name") == "trimem-grader-smoke-restricted.tar.enc"
        and type(encrypted.get("bytes")) is int
        and encrypted["bytes"] > 0
        and isinstance(encrypted.get("sha256"), str)
        and HEX64.fullmatch(encrypted["sha256"]) is not None,
        "official smoke encrypted evidence subject binding differs",
    )

    bundle = _strict_json_bytes(
        bundle_raw, label=OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH
    )
    require(
        set(bundle) == {"dsseEnvelope", "mediaType", "verificationMaterial"}
        and bundle.get("mediaType")
        == "application/vnd.dev.sigstore.bundle.v0.3+json",
        "official smoke attestation bundle field/media type differs",
    )
    statement = _bundle_statement(bundle)
    require(
        statement.get("_type") == "https://in-toto.io/Statement/v1"
        and statement.get("predicateType") == "https://slsa.dev/provenance/v1"
        and statement.get("subject")
        == [{
            "name": "attestation-subject.json",
            "digest": {"sha256": hashlib.sha256(subject_raw).hexdigest()},
        }],
        "official smoke attestation statement subject/predicate differs",
    )
    certificate = _bundle_certificate_bindings(bundle)
    require(
        certificate == _expected_certificate_bindings(subject),
        "official smoke attestation certificate identity/run/environment differs",
    )
    return subject


def _strict_json_array(raw: bytes, *, label: str) -> list[Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ReadinessError(f"duplicate JSON key in {label}: {key}")
            value[key] = child
        return value
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=strict_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid JSON output from {label}") from exc
    require(isinstance(value, list), f"{label} root is not an array")
    return value


def _validate_gh_attestation_output(
    raw: bytes, subject: Mapping[str, Any], bundle: Mapping[str, Any]
) -> None:
    results = _strict_json_array(raw, label="gh attestation verify")
    cert_identity = _smoke_cert_identity(subject["execution"]["source_ref"])
    require(len(results) == 1 and isinstance(results[0], dict), "gh verified attestation count differs")
    row = results[0]
    require(
        set(row) == {"attestation", "verificationResult"},
        "gh attestation result field set differs",
    )
    attestation = row.get("attestation")
    require(
        attestation
        == {"bundle": bundle, "bundle_url": "", "initiator": ""},
        "gh verified attestation bundle bytes/field set differs",
    )
    verified_bundle = attestation["bundle"]
    require(
        _bundle_certificate_bindings(verified_bundle)
        == _expected_certificate_bindings(subject),
        "gh verified bundle leaf certificate binding differs",
    )
    result = row.get("verificationResult")
    require(
        isinstance(result, dict)
        and set(result)
        == {
            "mediaType", "signature", "statement", "verifiedIdentity",
            "verifiedTimestamps",
        }
        and result.get("mediaType")
        == "application/vnd.dev.sigstore.verificationresult+json;version=0.1"
        and isinstance(result.get("verifiedTimestamps"), list)
        and bool(result["verifiedTimestamps"]),
        "gh attestation cryptographic verification result differs",
    )
    require(
        result.get("verifiedIdentity")
        == {
            "issuer": {"issuer": "", "regexp": ".*"},
            "runnerEnvironment": SMOKE_ATTESTATION_RUNNER,
            "subjectAlternativeName": {
                "subjectAlternativeName": cert_identity,
            },
        },
        "gh verified identity policy differs",
    )
    signature = result.get("signature")
    certificate = signature.get("certificate") if isinstance(signature, dict) else None
    expected = _expected_certificate_bindings(subject)
    require(isinstance(certificate, dict), "gh verified certificate summary is missing")
    for field, value in expected.items():
        if field == "protectedEnvironment":
            continue
        require(
            certificate.get(field) == value,
            f"gh verified certificate {field} differs",
        )
    statement = result.get("statement")
    require(
        isinstance(statement, dict)
        and statement.get("_type") == "https://in-toto.io/Statement/v1"
        and statement.get("predicateType") == "https://slsa.dev/provenance/v1"
        and statement.get("subject")
        == [{
            "name": "attestation-subject.json",
            "digest": {"sha256": hashlib.sha256(_pretty_json(dict(subject))).hexdigest()},
        }],
        "gh verified statement subject differs",
    )


def _validate_live_workflow_run_attempt(
    raw: bytes, subject: Mapping[str, Any]
) -> None:
    """Bind the signature to the completed, successful GitHub run attempt.

    A Sigstore attestation can already exist when a later artifact upload or
    cleanup step makes its workflow run fail.  The exact attempt endpoint is
    therefore part of the paid-phase gate rather than an informational check.
    """

    execution = subject["execution"]
    row = _strict_json_bytes(raw, label="GitHub workflow run-attempt API")
    require(
        set(row)
        == {
            "conclusion", "event", "head_branch", "head_sha", "id", "path",
            "repository_full_name", "run_attempt", "status", "workflow_id",
        },
        "GitHub workflow run-attempt field set differs",
    )
    run_id = execution.get("workflow_run_id")
    run_attempt = execution.get("workflow_run_attempt")
    source_ref = execution.get("source_ref")
    require(
        isinstance(run_id, str)
        and POSITIVE_INTEGER.fullmatch(run_id) is not None
        and isinstance(run_attempt, str)
        and POSITIVE_INTEGER.fullmatch(run_attempt) is not None
        and isinstance(source_ref, str)
        and source_ref.startswith("refs/heads/")
        and len(source_ref) > len("refs/heads/"),
        "official smoke subject has invalid live run identity",
    )
    require(
        type(row.get("id")) is int
        and row["id"] == int(run_id)
        and type(row.get("run_attempt")) is int
        and row["run_attempt"] == int(run_attempt)
        and row.get("event") == execution.get("event_name")
        and row.get("status") == "completed"
        and row.get("conclusion") == "success"
        and row.get("head_sha") == execution.get("source_digest")
        and row.get("head_branch") == source_ref.removeprefix("refs/heads/")
        and row.get("path") == SMOKE_ATTESTATION_WORKFLOW
        and type(row.get("workflow_id")) is int
        and row["workflow_id"] > 0
        and row.get("repository_full_name") == SMOKE_ATTESTATION_REPOSITORY,
        "official smoke live run attempt is not the exact completed successful execution",
    )


def verify_official_smoke_attestation_cryptographically() -> None:
    """Cryptographically enforce the official-smoke trust anchor before paid phases."""

    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    evidence = smoke.get("official_execution_evidence")
    require(isinstance(evidence, dict), "official smoke execution evidence is missing")
    subject_path = ROOT / OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
    bundle_path = ROOT / OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH
    subject_raw, bundle_raw = subject_path.read_bytes(), bundle_path.read_bytes()
    subject = _strict_json_bytes(
        subject_raw, label=OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
    )
    certificate = _bundle_certificate_bindings(
        _strict_json_bytes(bundle_raw, label=OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH)
    )
    require(
        certificate == _expected_certificate_bindings(subject),
        "official smoke bundle certificate binding differs before gh verification",
    )
    gh = shutil.which("gh")
    require(gh is not None, "gh CLI is required for cryptographic smoke attestation verification")
    require(
        bool(os.environ.get("GH_TOKEN")),
        "GH_TOKEN is required for exact official smoke run-attempt verification",
    )
    version = subprocess.run(
        [gh, "--version"], cwd=ROOT, capture_output=True, check=False
    )
    require(
        version.returncode == 0
        and version.stdout.splitlines()
        and version.stdout.splitlines()[0]
        == SMOKE_GH_VERSION_LINE.encode("ascii"),
        "gh CLI version differs from the pre-frozen attestation verifier",
    )
    execution = subject["execution"]
    cert_identity = _smoke_cert_identity(execution["source_ref"])
    command = [
        gh, "attestation", "verify", str(subject_path),
        "--bundle", str(bundle_path),
        "--custom-trusted-root", str(ROOT / SMOKE_TRUSTED_ROOT_PATH),
        "--repo", SMOKE_ATTESTATION_REPOSITORY,
        "--cert-identity", cert_identity,
        "--cert-oidc-issuer", SMOKE_OIDC_ISSUER,
        "--deny-self-hosted-runners",
        "--signer-digest", execution["source_digest"],
        "--source-digest", execution["source_digest"],
        "--source-ref", execution["source_ref"],
        "--predicate-type=https://slsa.dev/provenance/v1",
        "--digest-alg=sha256",
        "--format=json",
    ]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, check=False
    )
    require(
        completed.returncode == 0,
        "gh cryptographic smoke attestation verification failed",
    )
    bundle = _strict_json_bytes(
        bundle_raw, label=OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH
    )
    _validate_gh_attestation_output(completed.stdout, subject, bundle)
    route = SMOKE_RUN_API_ROUTE_TEMPLATE.format(
        repository=SMOKE_ATTESTATION_REPOSITORY,
        run_id=execution["workflow_run_id"],
        run_attempt=execution["workflow_run_attempt"],
    )
    live_command = [
        gh, "api", "--hostname", "github.com", route,
        "--method", "GET",
        "-H", f"Accept: {SMOKE_GITHUB_API_ACCEPT}",
        "-H", f"X-GitHub-Api-Version: {SMOKE_GITHUB_API_VERSION}",
        "--jq", SMOKE_RUN_API_JSON_PROJECTION,
    ]
    live = subprocess.run(
        live_command, cwd=ROOT, capture_output=True, check=False
    )
    require(
        live.returncode == 0,
        "GitHub official smoke run-attempt verification failed",
    )
    _validate_live_workflow_run_attempt(live.stdout, subject)


def verify_smoke_attestation_only() -> dict[str, Any]:
    """Run the paid-phase smoke attestation gate without a paid phase.

    This wrapper adds only immutable-byte observations and a zero-scientific-
    execution receipt.  Cryptographic and live-run semantics remain owned by
    ``verify_official_smoke_attestation_cryptographically``, which is also the
    function called from the benchmark execution gate.
    """

    gh_lock_path = ROOT / SMOKE_GH_CLI_LOCK_PATH
    gh_lock_raw = gh_lock_path.read_bytes()
    gh_lock = load_gh_cli_lock(gh_lock_path)
    require(
        gh_lock["expected_first_version_line"] == SMOKE_GH_VERSION_LINE,
        "smoke attestation verifier and pinned gh lock version differ",
    )
    policy = validate_smoke_attestation_policy()
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    evidence = smoke.get("official_execution_evidence")
    require(isinstance(evidence, dict), "official smoke execution evidence is missing")

    paths = {
        "trusted_root": ROOT / SMOKE_TRUSTED_ROOT_PATH,
        "attestation_subject": ROOT / OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
        "attestation_bundle": ROOT / OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
        "evidence_inventory": ROOT / OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
        "public_result": ROOT / OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
    }
    before = {name: path.read_bytes() for name, path in paths.items()}
    expected_hashes = {
        "trusted_root": policy["trusted_root"]["raw_sha256"],
        "attestation_subject": evidence.get("attestation_subject_raw_sha256"),
        "attestation_bundle": evidence.get("attestation_bundle_raw_sha256"),
        "evidence_inventory": evidence.get("evidence_inventory_raw_sha256"),
        "public_result": evidence.get("public_result_raw_sha256"),
    }
    for name, raw in before.items():
        require(
            hashlib.sha256(raw).hexdigest() == expected_hashes[name],
            f"{name.replace('_', ' ')} differs before attestation-only verification",
        )

    # This exact function is the sole cryptographic interpretation shared with
    # the benchmark execution gate.  Do not replace it with a rehearsal mock or
    # a second verifier implementation.
    verify_official_smoke_attestation_cryptographically()

    after = {name: path.read_bytes() for name, path in paths.items()}
    require(
        before == after,
        "trusted root or official smoke attestation bytes changed during verification",
    )
    subject = _strict_json_bytes(
        before["attestation_subject"],
        label=OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
    )
    execution = subject.get("execution")
    require(isinstance(execution, dict), "official smoke attestation execution is missing")
    certificate_policy = policy["certificate_policy"]
    return {
        "status": "PASS",
        "shared_verifier": "verify_official_smoke_attestation_cryptographically",
        "gh_cli_lock": {
            "path": SMOKE_GH_CLI_LOCK_PATH,
            "raw_sha256": hashlib.sha256(gh_lock_raw).hexdigest(),
            "version": gh_lock["version"],
            "expected_first_version_line": gh_lock["expected_first_version_line"],
            "extracted_gh_binary_sha256": gh_lock["extracted_gh_binary_sha256"],
        },
        "signer": {
            "repository": execution.get("repository"),
            "workflow": execution.get("signer_workflow"),
            "source_digest": execution.get("source_digest"),
            "source_ref": execution.get("source_ref"),
            "certificate_identity": _smoke_cert_identity(
                str(execution.get("source_ref"))
            ),
            "protected_environment": certificate_policy["protected_environment"],
        },
        "workflow_run_id": execution.get("workflow_run_id"),
        "workflow_run_attempt": execution.get("workflow_run_attempt"),
        "live_run_attempt_query_count": 1,
        "immutable_files": {
            name: {
                "bytes": len(raw),
                "path": paths[name].relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            for name, raw in before.items()
        },
    }


def _validate_official_smoke_pass(
    smoke: dict[str, Any], *, public_raw: bytes, inventory_raw: bytes,
    subject_raw: bytes, bundle_raw: bytes,
) -> None:
    evidence = smoke.get("official_execution_evidence")
    require(
        isinstance(evidence, dict) and set(evidence) == SMOKE_EVIDENCE_FIELDS,
        "passed grader smoke official evidence field set differs",
    )
    require(
        evidence.get("public_result_path") == OFFICIAL_SMOKE_PUBLIC_RESULT_PATH
        and evidence.get("evidence_inventory_path")
        == OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
        "passed grader smoke official evidence paths differ",
    )
    require(
        evidence.get("attestation_subject_path")
        == OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH
        and evidence.get("attestation_bundle_path")
        == OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
        "passed grader smoke attestation evidence paths differ",
    )
    for field, raw in (
        ("public_result_raw_sha256", public_raw),
        ("evidence_inventory_raw_sha256", inventory_raw),
        ("attestation_subject_raw_sha256", subject_raw),
        ("attestation_bundle_raw_sha256", bundle_raw),
    ):
        require(
            isinstance(evidence.get(field), str)
            and HEX64.fullmatch(evidence[field]) is not None
            and evidence[field] == hashlib.sha256(raw).hexdigest(),
            f"passed grader smoke {field} differs from committed bytes",
        )

    public = _strict_json_bytes(public_raw, label=OFFICIAL_SMOKE_PUBLIC_RESULT_PATH)
    inventory = _strict_json_bytes(
        inventory_raw, label=OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
    )
    expected_public_fields = {
        "schema", *SMOKE_AGGREGATE_BODY_FIELDS, *SMOKE_PUBLIC_ONLY_FIELDS,
    }
    require(set(public) == expected_public_fields, "official public smoke field set differs")
    require(
        public.get("schema") == "trimem/public-benchmark-artifact/1.0"
        and public.get("status") == "PASS"
        and public.get("manifest") == "grader-smoke"
        and public.get("stream_totals") == []
        and public.get("restricted_evidence")
        == "ENCRYPTED_SEPARATE_ARTIFACT_NOT_PUBLIC"
        and public.get("dataset_rows_or_gold_test_payloads")
        == "EXCLUDED_AND_EPHEMERAL_INPUTS_PURGED",
        "official public smoke identity/privacy contract differs",
    )

    actual_accounting = {
        field: 12
        if field in {"grader_calls", "grader_containers", "official_grader_runs"}
        else 0
        for field in SMOKE_ACCOUNTING_FIELDS
    }
    evidence_counts = {
        name: 12
        for name in (
            "patch", "tests", "container", "evaluator", "report", "digest",
            "execution_contract", "execution_control",
            "submitted_patch_identity", "applied_patch", "test_output",
            "official_test_status",
        )
    }
    evidence_counts["container_exit_status"] = 8
    lifecycle_actual = {
        "target_image_pulls": 6,
        "support_image_pulls": 1,
        "exact_image_removals": 7,
        "max_resident_target_images": 1,
        "max_resident_support_images": 1,
        "resident_target_images": 0,
        "resident_support_images": 0,
    }
    lifecycle = public.get("image_lifecycle")
    require(
        public.get("actual_accounting") == actual_accounting
        and public.get("probe_counts") == {"GOLD": 6, "NOOP_BASELINE": 6}
        and public.get("resolved_counts") == {"GOLD": 6, "NOOP_BASELINE": 0}
        and public.get("unresolved_counts") == {"GOLD": 0, "NOOP_BASELINE": 6}
        and public.get("evidence_counts") == evidence_counts
        and public.get("empty_patch_ids") == []
        and type(public.get("expected_target_count")) is int
        and public["expected_target_count"] == 12
        and type(public.get("observed_target_count")) is int
        and public["observed_target_count"] == 12
        and type(public.get("patch_applied_count")) is int
        and public["patch_applied_count"] == 12
        and type(public.get("tests_executed_count")) is int
        and public["tests_executed_count"] == 12
        and type(public.get("digest_match_count")) is int
        and public["digest_match_count"] == 12
        and type(public.get("submitted_patch_identity_count")) is int
        and public["submitted_patch_identity_count"] == 12
        and type(public.get("host_prepare_sh_access_count")) is int
        and public["host_prepare_sh_access_count"] == 0
        and type(public.get("source_image_build_count")) is int
        and public["source_image_build_count"] == 0
        and type(public.get("container_exit_status_captured_count")) is int
        and public["container_exit_status_captured_count"] == 8
        and type(public.get("container_exit_status_validated_count")) is int
        and public["container_exit_status_validated_count"] == 8
        and type(public.get("resolved_container_zero_exit_count")) is int
        and public["resolved_container_zero_exit_count"] == 4
        and type(public.get("api_calls")) is int
        and public["api_calls"] == 0
        and all(
            type(public.get(field)) is int and public[field] == 12
            for field in (
                "adapter_normalized_count",
                "attempted_cell_count",
                "authoritative_cell_count",
                "complete_execution_evidence_count",
                "official_execution_count",
                "terminal_record_count",
            )
        )
        and type(public.get("unattempted_cell_count")) is int
        and public["unattempted_cell_count"] == 0
        and all(
            type(public.get(field)) is int and public[field] == 0
            for field in GRADER_SMOKE_FAILURE_TAXONOMY_FIELDS
        )
        and isinstance(lifecycle, dict)
        and set(lifecycle)
        == {"actual", "event_count", "report_bytes", "report_sha256", "status"}
        and lifecycle.get("actual") == lifecycle_actual
        and type(lifecycle.get("event_count")) is int
        and lifecycle["event_count"] == 14
        and type(lifecycle.get("report_bytes")) is int
        and lifecycle["report_bytes"] > 0
        and isinstance(lifecycle.get("report_sha256"), str)
        and HEX64.fullmatch(lifecycle["report_sha256"]) is not None
        and lifecycle.get("status") == "PASS",
        "official public smoke scientific/lifecycle counters differ",
    )

    manifest = read_json(CONFIG / "grader_smoke_manifest.json")
    targets = manifest.get("targets")
    outcomes = public.get("outcomes")
    require(
        isinstance(targets, list)
        and isinstance(outcomes, list)
        and len(targets) == len(outcomes) == 12,
        "official public smoke outcome coverage differs",
    )
    outcome_fields = {
        "benchmark_id", "order_index", "probe", "resolved", "target_id",
        "applied_patch_sha256", "official_test_output_sha256",
        "official_test_status_sha256", "container_exit_status_sha256",
        "execution_contract_sha256", "execution_control_sha256",
        "submitted_patch_identity_sha256", "patch_applied", "tests_executed",
        "digest_match", "submitted_patch_identity",
        "host_prepare_sh_access_count", "source_image_build_count", "api_calls",
        "container_exit_status_code", "container_exit_acceptance",
        "semantic_normalization",
    }
    for index, (target, outcome) in enumerate(zip(targets, outcomes)):
        if not isinstance(target, dict) or not isinstance(outcome, dict):
            container_exit_valid = False
            semantic_normalization_valid = False
        elif target.get("benchmark_id") == "swebench_verified":
            container_exit_valid = (
                outcome.get("container_exit_status_code") is None
                and outcome.get("container_exit_acceptance") is None
                and outcome.get("container_exit_status_sha256") is None
            )
            semantic_normalization_valid = (
                outcome.get("semantic_normalization") is None
            )
        else:
            container_exit_valid = (
                target.get("benchmark_id")
                in {"multi_swe_bench_mini", "multi_swe_bench_flash"}
                and type(outcome.get("container_exit_status_code")) is int
                and 0 <= outcome["container_exit_status_code"] <= 255
                and outcome.get("container_exit_acceptance")
                in {
                    "ZERO_EXIT",
                    "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION",
                }
                and isinstance(outcome.get("container_exit_status_sha256"), str)
                and HEX64.fullmatch(outcome["container_exit_status_sha256"])
                is not None
                and (
                    target.get("expected_resolved") is not True
                    or outcome["container_exit_status_code"] == 0
                )
            )
            semantic_summary = validate_public_summary(
                outcome.get("semantic_normalization")
            )
            semantic_normalization_valid = (
                semantic_summary["computed_resolved"]
                is outcome.get("resolved")
                and semantic_summary["official_final_report_resolved"]
                is outcome.get("resolved")
                and semantic_summary["final_report_match"] is True
            )
        require(
            isinstance(target, dict)
            and isinstance(outcome, dict)
            and set(outcome) == outcome_fields
            and outcome.get("target_id") == target.get("target_id")
            and outcome.get("benchmark_id") == target.get("benchmark_id")
            and type(outcome.get("order_index")) is int
            and outcome["order_index"] == index == target.get("order_index")
            and outcome.get("probe") == target.get("probe")
            and type(outcome.get("resolved")) is bool
            and outcome["resolved"] is target.get("expected_resolved")
            and all(
                isinstance(outcome.get(field), str)
                and HEX64.fullmatch(outcome[field]) is not None
                for field in (
                    "applied_patch_sha256", "official_test_output_sha256",
                    "official_test_status_sha256", "execution_contract_sha256",
                    "execution_control_sha256", "submitted_patch_identity_sha256",
                )
            )
            and all(
                outcome.get(field) is True
                for field in (
                    "patch_applied", "tests_executed", "digest_match",
                    "submitted_patch_identity",
                )
            )
            and all(
                type(outcome.get(field)) is int and outcome[field] == 0
                for field in (
                    "host_prepare_sh_access_count", "source_image_build_count",
                    "api_calls",
                )
            )
            and container_exit_valid
            and semantic_normalization_valid,
            f"official public smoke outcome {index} differs from frozen target",
        )

    approval = public.get("approval_binding")
    require(
        isinstance(approval, dict)
        and set(approval) == SMOKE_APPROVAL_FIELDS
        and approval.get("phase") == "GRADER_SMOKE"
        and isinstance(approval.get("git_head"), str)
        and HEX40.fullmatch(approval["git_head"]) is not None
        and all(
            isinstance(approval.get(field), str)
            and HEX64.fullmatch(approval[field]) is not None
            for field in (
                "approval_artifact_sha256", "approved_request_sha256", "freeze_sha256"
            )
        )
        and all(
            isinstance(approval.get(field), str)
            and POSITIVE_INTEGER.fullmatch(approval[field]) is not None
            for field in ("approved_workflow_run_id", "approved_workflow_run_attempt")
        ),
        "official public smoke approval binding differs",
    )
    require(
        evidence.get("approval_binding") == approval,
        "grader smoke result/public approval binding differs",
    )
    _validate_attestation_artifacts(
        subject_raw=subject_raw,
        bundle_raw=bundle_raw,
        public_raw=public_raw,
        inventory_raw=inventory_raw,
        approval=approval,
    )
    execution_head = approval["git_head"]
    require(
        _execution_head_is_ancestor(execution_head),
        "official smoke execution HEAD is not an ancestor of the result commit",
    )
    historical_freeze = _historical_git_file(
        execution_head, "artifacts/trimem_v1/freeze.json"
    )
    historical_request = _historical_git_file(
        execution_head,
        GRADER_SMOKE_SENTINEL_PATH,
    )
    request = _validate_historical_smoke_request(execution_head, historical_request)
    require(
        hashlib.sha256(historical_freeze).hexdigest() == approval["freeze_sha256"]
        and hashlib.sha256(historical_request).hexdigest()
        == approval["approved_request_sha256"]
        and request.get("schema") == GRADER_SMOKE_REQUEST_SCHEMA
        and request.get("phase") == "GRADER_SMOKE"
        and request.get("actual_execution_authorized") is False
        and request.get("requires_external_approval") is True
        and request.get("freeze_sha256") == "sha256:" + approval["freeze_sha256"],
        "official smoke historical HEAD/freeze/request binding differs",
    )
    historical_freeze_value = _strict_json_bytes(
        historical_freeze, label="historical official-smoke freeze"
    )
    historical_files = historical_freeze_value.get("files")
    require(isinstance(historical_files, dict), "historical smoke freeze file inventory is missing")
    for relative in (SMOKE_TRUSTED_ROOT_PATH, SMOKE_ATTESTATION_POLICY_PATH):
        historical_raw = _historical_git_file(execution_head, relative)
        current_raw = (ROOT / relative).read_bytes()
        require(
            historical_raw == current_raw,
            f"post-smoke mutation of pre-frozen trust anchor is prohibited: {relative}",
        )
        require(
            historical_files.get(relative)
            == {
                "bytes": len(historical_raw),
                "sha256": hashlib.sha256(historical_raw).hexdigest(),
            },
            f"historical smoke freeze does not seal trust anchor: {relative}",
        )

    aggregate_body = {
        field: public[field] for field in SMOKE_AGGREGATE_BODY_FIELDS
    }
    aggregate_body["schema"] = "trimem/verified-aggregate/1.0"
    aggregate_sha = hashlib.sha256(canonical(aggregate_body)).hexdigest()
    require(
        public.get("verified_aggregate_sha256") == aggregate_sha
        and evidence.get("verified_aggregate_sha256") == aggregate_sha,
        "official public smoke does not reproduce its verified aggregate seal",
    )
    aggregate_raw = _pretty_json({**aggregate_body, "aggregate_sha256": aggregate_sha})
    require(
        isinstance(evidence.get("aggregate_raw_sha256"), str)
        and HEX64.fullmatch(evidence["aggregate_raw_sha256"]) is not None
        and evidence["aggregate_raw_sha256"]
        == hashlib.sha256(aggregate_raw).hexdigest(),
        "grader smoke result aggregate raw SHA differs",
    )
    rows = _inventory_rows(inventory)
    _require_inventory_raw(rows, "aggregate.json", aggregate_raw, label="aggregate")
    _require_inventory_raw(rows, "public-results.json", public_raw, label="public result")
    public_approval_raw = _pretty_json(approval)
    _require_inventory_raw(
        rows,
        "results/external-approval-evidence.json",
        public_approval_raw,
        label="public approval subset",
    )
    restricted_approval = rows.get("results/restricted-external-approval.json")
    require(
        isinstance(restricted_approval, Mapping)
        and restricted_approval.get("sha256") == approval["approval_artifact_sha256"]
        and type(restricted_approval.get("bytes")) is int
        and restricted_approval["bytes"] > 0,
        "official smoke restricted approval inventory binding differs",
    )
    lifecycle_row = rows.get("image-materialization/image-lifecycle-report.json")
    require(
        isinstance(lifecycle_row, Mapping)
        and lifecycle_row.get("sha256") == lifecycle["report_sha256"]
        and lifecycle_row.get("bytes") == lifecycle["report_bytes"],
        "official smoke lifecycle report inventory binding differs",
    )
    summary = {
        "schema": "trimem/grader-smoke-execution/2.0",
        "expected_target_count": 12,
        "observed_target_count": 12,
        "probe_counts": {"GOLD": 6, "NOOP_BASELINE": 6},
        "empty_patch_ids": [],
        "failures": [],
        "api_calls": 0,
        "cached_input_tokens": 0,
        "decomposition_calls": 0,
        "extraction_calls": 0,
        "grader_calls": 12,
        "grader_containers": 12,
        "input_tokens": 0,
        "model_calls": 0,
        "model_gateway_calls": 0,
        "official_grader_runs": 12,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "reasoning_tokens": 0,
        "solve_calls": 0,
        "task_arm_runs": 0,
        "total_usd": 0,
        "patch_applied_count": 12,
        "tests_executed_count": 12,
        "digest_match_count": 12,
        "submitted_patch_identity_count": 12,
        "host_prepare_sh_access_count": 0,
        "source_image_build_count": 0,
        "container_exit_status_captured_count": 8,
        "container_exit_status_validated_count": 8,
        "resolved_container_zero_exit_count": 4,
        "attempted_cell_count": 12,
        "terminal_record_count": 12,
        "official_execution_count": 12,
        "complete_execution_evidence_count": 12,
        "adapter_normalized_count": 12,
        "authoritative_cell_count": 12,
        "unattempted_cell_count": 0,
        "environment_failures": 0,
        "infrastructure_failures": 0,
        "image_lifecycle_failures": 0,
        "official_harness_failures": 0,
        "official_report_failures": 0,
        "adapter_contract_failures": 0,
        "aggregate_failures": 0,
        "status": "PASS",
    }
    _require_inventory_raw(
        rows,
        "results/smoke-execution-summary.json",
        _pretty_json(summary),
        label="execution summary",
    )
    expected_result_paths = set()
    for index, target in enumerate(targets):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(target["target_id"]))
        expected_result_paths.add(f"results/{index:03d}-{safe}/{safe}.result.json")
    observed_result_paths = {
        path for path in rows
        if re.fullmatch(r"results/[0-9]{3}-[^/]+/[^/]+\.result\.json", path)
    }
    require(
        observed_result_paths == expected_result_paths,
        "official smoke inventory task-result exact set differs",
    )


def _validated_p015_failure_inventory(
    raw: bytes,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Validate a fresh exec-005 restricted-evidence inventory by derivation."""

    inventory = _strict_json_bytes(
        raw, label=OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
    )
    require(
        canonical(inventory) + b"\n" == raw,
        "exec-005 failure inventory bytes are not canonical",
    )
    require(
        set(inventory)
        == {
            "files",
            "inventory_sha256",
            "root",
            "schema",
            "total_bytes",
            "total_files",
        }
        and inventory.get("schema")
        == "trimem/restricted-evidence-inventory/1.0"
        and inventory.get("root") == "grader_smoke_exec",
        "exec-005 failure inventory identity differs",
    )
    rows = inventory.get("files")
    require(isinstance(rows, list) and rows, "exec-005 failure inventory is empty")
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        require(
            isinstance(row, dict)
            and set(row) == {"bytes", "path", "sha256"},
            "exec-005 failure inventory row fields differ",
        )
        path = row.get("path")
        digest = row.get("sha256")
        size = row.get("bytes")
        require(
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
            "exec-005 failure inventory row is malformed or duplicated",
        )
        indexed[path] = row
    payload = {
        "files": rows,
        "root": inventory["root"],
        "schema": inventory["schema"],
        "total_bytes": sum(row["bytes"] for row in rows),
        "total_files": len(rows),
    }
    require(
        inventory.get("total_files") == len(rows)
        and inventory.get("total_bytes") == payload["total_bytes"]
        and inventory.get("inventory_sha256")
        == hashlib.sha256(canonical(payload)).hexdigest(),
        "exec-005 failure inventory totals or seal differ",
    )
    return inventory, indexed


def _validated_p015_failure_closure(
    receipt_raw: bytes, inventory_raw: bytes
) -> dict[str, Any]:
    """Validate one namespaced, evidence-derived exec-005 failure closure."""

    request_path = ROOT / GRADER_SMOKE_SENTINEL_PATH
    request_raw = request_path.read_bytes()
    request = _strict_json_bytes(request_raw, label=GRADER_SMOKE_SENTINEL_PATH)
    request_source_head = request.get("source_head")
    require(
        isinstance(request_source_head, str)
        and HEX40.fullmatch(request_source_head) is not None,
        "exec-005 failure request source head differs",
    )
    try:
        validate_request_document(
            ROOT,
            request_raw,
            expected_source_head=request_source_head,
            material_commit=request_source_head,
        )
        return validate_failure_closure(
            receipt_raw,
            inventory_raw,
            request_raw=request_raw,
        )
    except (OSError, ValueError, TriggerPreflightError, FailureClosureError) as exc:
        raise ReadinessError(f"exec-005 failure closure did not validate: {exc}") from exc


def _validated_p014_historical_execution() -> dict[str, Any]:
    """Return the one exact, immutable P0.1.4 diagnostic execution record."""

    receipt_path = ROOT / P014_FAILURE_RECEIPT_PATH
    inventory_path = ROOT / P014_FAILURE_INVENTORY_PATH
    receipt_raw = receipt_path.read_bytes()
    inventory_raw = inventory_path.read_bytes()
    require(
        hashlib.sha256(receipt_raw).hexdigest()
        == P014_FAILURE_RECEIPT_RAW_SHA256
        and hashlib.sha256(inventory_raw).hexdigest()
        == P014_EVIDENCE_INVENTORY_RAW_SHA256,
        "P0.1.4 historical failure evidence bytes differ",
    )
    receipt = validate_committed_failure_evidence(ROOT)
    accounting = receipt.get("execution_accounting")
    require(
        accounting
        == {
            "api_calls": 0,
            "cached_input_tokens": 0,
            "decomposition_calls": 0,
            "docker_pulls": 4,
            "extraction_calls": 0,
            "grader_calls": 6,
            "grader_containers": 6,
            "input_tokens": 0,
            "model_calls": 0,
            "model_gateway_calls": 0,
            "official_grader_runs": 6,
            "output_tokens": 0,
            "paid_model_calls": 0,
            "reasoning_tokens": 0,
            "solve_calls": 0,
            "task_arm_runs": 0,
            "total_usd": 0,
        },
        "P0.1.4 historical execution accounting differs",
    )
    campaign = receipt.get("authoritative_campaign")
    diagnostic = receipt.get("diagnostic_progress")
    forensic = (
        diagnostic.get("evidence_counts", {}).get("forensic_executed_outcomes")
        if isinstance(diagnostic, dict)
        else None
    )
    require(
        isinstance(campaign, dict)
        and campaign.get("expected_cells") == 12
        and campaign.get("forensic_executed_outcomes") == 6
        and campaign.get("formal_result_rows") == 5
        and campaign.get("authoritative_result_rows") == 0
        and campaign.get("scientific_result") == "NOT_AGGREGATED"
        and isinstance(forensic, dict)
        and forensic.get("patch_applied") == 6
        and forensic.get("tests_executed") == 6
        and forensic.get("digest_match") == 6
        and forensic.get("submitted_patch_identity") == 6,
        "P0.1.4 historical campaign/evidence accounting differs",
    )
    analysis = receipt.get("failure_analysis")
    require(
        isinstance(analysis, dict)
        and analysis.get("classification") == "ADAPTER_EVIDENCE_CONTRACT_FAILURE"
        and analysis.get("primary", {}).get("code")
        == "MULTI_SWE_VALID_RESOLVED_CONFLATION"
        and analysis.get("secondary", {}).get("code")
        == "FAILURE_REPORT_IDENTITY_LOCATION_MASKING",
        "P0.1.4 historical failure classification differs",
    )
    lifecycle = receipt.get("image_lifecycle")
    require(
        isinstance(lifecycle, dict)
        and lifecycle.get("support_image_pulls") == 1
        and lifecycle.get("target_image_pulls") == 3
        and lifecycle.get("host_prepare_sh_access_count", 0) == 0,
        "P0.1.4 historical image accounting differs",
    )
    taxonomy = {
        "adapter_contract_failures": 1,
        "aggregate_failures": 0,
        "environment_failures": 0,
        "image_lifecycle_failures": 0,
        "infrastructure_failures": 0,
        "official_harness_failures": 0,
        "official_report_failures": 0,
    }
    require(
        set(taxonomy) == set(GRADER_SMOKE_FAILURE_TAXONOMY_FIELDS),
        "P0.1.4 historical failure taxonomy field set differs",
    )
    approval = receipt.get("approval_binding")
    workflow = receipt.get("workflow_run")
    require(
        isinstance(approval, dict)
        and isinstance(workflow, dict)
        and workflow.get("id") == 33630256522
        and workflow.get("run_attempt") == 1
        and approval.get("git_head") == "0e9ed55196da922dcebf1fb33b73940873007180",
        "P0.1.4 historical workflow identity differs",
    )
    return {
        "approval_binding": approval,
        "campaign": {
            "adapter_normalized_cell_count": 5,
            "attempted_cell_count": 6,
            "authoritative_cell_count": 0,
            "complete_execution_evidence_count": 6,
            "official_execution_count": 6,
            "required_cell_count": 12,
            "unattempted_cell_count": 6,
        },
        "endpoint": SMOKE_FAILURE_ENDPOINT,
        "evidence": {
            "evidence_inventory_path": P014_FAILURE_INVENTORY_PATH,
            "evidence_inventory_raw_sha256": P014_EVIDENCE_INVENTORY_RAW_SHA256,
            "failure_receipt_path": P014_FAILURE_RECEIPT_PATH,
            "failure_receipt_raw_sha256": P014_FAILURE_RECEIPT_RAW_SHA256,
        },
        "execution_accounting": accounting,
        "failure_taxonomy": taxonomy,
        "git_head": approval["git_head"],
        "image_lifecycle": {
            "host_prepare_sh_access_count": 0,
            "source_image_build_count": 0,
            "support_image_pulls": 1,
            "target_image_pulls": 3,
        },
        "scientific_result": "NOT_AGGREGATED",
        "status": "DIAGNOSTIC_HISTORY_ONLY",
        "workflow_run_attempt": 1,
        "workflow_run_id": 33630256522,
    }


def validate_grader_smoke_result(smoke: dict[str, Any]) -> dict[str, int]:
    status = smoke.get("status")
    recovery_ready = status == SMOKE_RECOVERY_STATUS
    failed = status == "FAIL"
    passed = status == "PASS"
    require(
        recovery_ready or failed or passed,
        "grader smoke result status is unknown",
    )
    if recovery_ready:
        expected_fields = {
            *SMOKE_RESULT_COMMON_FIELDS,
            "actual_execution_scope",
            "endpoint",
            "historical_execution",
        }
    elif failed:
        expected_fields = {
            *SMOKE_RESULT_COMMON_FIELDS,
            "endpoint",
            "historical_execution",
            "official_execution_failure_evidence",
        }
    else:
        expected_fields = {
            *SMOKE_RESULT_COMMON_FIELDS, "official_execution_evidence",
        }
    require(set(smoke) == expected_fields, "grader smoke result field set differs")
    require(
        smoke.get("schema")
        == (
            P015_FAILURE_RESULT_SCHEMA
            if recovery_ready or failed
            else (
                "trimem/grader-smoke-result/1.0"
            )
        )
        and smoke.get("trimem_system_implementation") == "CREDENTIAL_FREE_GREEN"
        and smoke.get("performance") == "NOT_MEASURED"
        and smoke.get("expected_unique_instances") == 6
        and smoke.get("expected_target_count") == 12
        and smoke.get("expected_condition_rows")
        == {"GOLD": 6, "NOOP_BASELINE": 6},
        "grader smoke result static contract differs",
    )
    legacy_pre_smoke_actual = {
        "docker_pulls": 0,
        "grader_containers": 0,
        "input_tokens": 0,
        "model_calls": 0,
        "official_grader_runs": 0,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "total_usd": 0,
    }
    passed_smoke_actual = {
        **legacy_pre_smoke_actual,
        "docker_pulls": 7,
        "grader_containers": 12,
        "official_grader_runs": 12,
    }
    actual = smoke.get("actual_execution")
    require(
        isinstance(actual, dict) and all(type(value) is int for value in actual.values()),
        "grader smoke execution counter types differ",
    )
    state = (
        smoke.get("status"), smoke.get("grader_exec_package"),
        smoke.get("official_grader_viability"),
    )
    if recovery_ready:
        require(
            state
            == (
                SMOKE_RECOVERY_STATUS, SMOKE_RECOVERY_STATUS,
                "NOT_YET_ESTABLISHED",
            )
            and smoke.get("endpoint") == SMOKE_RECOVERY_ENDPOINT
            and smoke.get("actual_execution_scope") == SMOKE_RECOVERY_SCOPE
            and actual == SMOKE_RECOVERY_ACTUAL_EXECUTION,
            "P0.1.5 recovery-ready state/correction-delta contract is invalid",
        )
        require(
            smoke.get("historical_execution")
            == _validated_p014_historical_execution(),
            "P0.1.4 diagnostic history binding differs",
        )
    elif failed:
        require(
            state == ("FAIL", "FAIL", "NOT_YET_ESTABLISHED")
            and smoke.get("endpoint") in P015_FAILURE_ENDPOINTS,
            "failed grader smoke state/counter contract is invalid",
        )
        require(
            smoke.get("historical_execution")
            == _validated_p014_historical_execution(),
            "P0.1.4 diagnostic history binding differs after exec-005 failure",
        )
        evidence = smoke.get("official_execution_failure_evidence")
        require(
            isinstance(evidence, dict)
            and set(evidence) == SMOKE_FAILURE_EVIDENCE_FIELDS,
            "failed grader smoke evidence field set differs",
        )
        receipt_path = ROOT / OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
        inventory_path = ROOT / OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
        receipt_raw = receipt_path.read_bytes()
        inventory_raw = inventory_path.read_bytes()
        require(
            evidence.get("failure_receipt_path")
            == OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
            and evidence.get("failure_receipt_raw_sha256")
            == hashlib.sha256(receipt_raw).hexdigest()
            and evidence.get("evidence_inventory_path")
            == OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
            and evidence.get("evidence_inventory_raw_sha256")
            == hashlib.sha256(inventory_raw).hexdigest(),
            "failed grader smoke evidence path/raw hash binding differs",
        )
        receipt = _validated_p015_failure_closure(receipt_raw, inventory_raw)
        require(
            evidence.get("approval_binding") == receipt.get("approval_binding")
            and smoke.get("endpoint") == receipt.get("endpoint"),
            "failed grader smoke approval binding differs",
        )
        require(
            actual == receipt.get("actual_execution"),
            "failed grader smoke receipt accounting differs",
        )
    else:
        require(
            state == ("PASS", "PASS", "ESTABLISHED")
            and actual == passed_smoke_actual,
            "passed grader smoke state/counter contract is invalid",
        )
        public_raw = (ROOT / OFFICIAL_SMOKE_PUBLIC_RESULT_PATH).read_bytes()
        inventory_raw = (ROOT / OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH).read_bytes()
        subject_raw = (ROOT / OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH).read_bytes()
        bundle_raw = (ROOT / OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH).read_bytes()
        _validate_official_smoke_pass(
            smoke, public_raw=public_raw, inventory_raw=inventory_raw,
            subject_raw=subject_raw, bundle_raw=bundle_raw,
        )
    return actual


def exact_hash(value: Any, message: str, length: int = 64) -> str:
    pattern = HEX64 if length == 64 else HEX40
    require(isinstance(value, str) and pattern.fullmatch(value) is not None, message)
    require(len(set(value)) > 2, message + " (placeholder-like)")
    return value


def strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def validate_sources() -> None:
    audit = read_json(ARTIFACT / "upstream_source_audit.json")
    require(audit.get("official_primary_sources_only") is True, "source audit is not official-primary-only")
    expected = {
        "swebench_verified": ("78f471bf655a3137b2e8a75af1501690ec009ec3", "030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"),
        "multi_swe_bench_mini": ("d0fab3ccc7dff232fcaac234cf8af9a2efeaccf6", "6644b9c9ebaf5e5b37cb9d81c4dce688c101f07436aed9d50fc55c85b164c3b2"),
        "multi_swe_bench_flash": ("b0485dbebaf8a1317ebf140e80e6fc6c02d3502b", "48d6d02cc976a71a06b494cc60581d92e82c06c2793c0d412c52c63e6956bebe"),
    }
    rows = {row.get("benchmark_id"): row for row in audit.get("benchmarks", ()) if isinstance(row, Mapping)}
    require(set(rows) == set(expected), "official benchmark source set mismatch")
    for name, (revision, data_hash) in expected.items():
        dataset, harness = rows[name].get("dataset", {}), rows[name].get("harness", {})
        require(dataset.get("revision") == revision, f"dataset revision drift: {name}")
        require(dataset.get("data_file", {}).get("lfs_oid_sha256") == data_hash, f"dataset file digest drift: {name}")
        exact_hash(harness.get("revision"), f"harness revision is not exact: {name}", 40)
    grader = read_json(CONFIG / "grader_lock.json")
    terms = grader.get("dataset_terms_boundary", {})
    require(terms.get("no_dataset_redistribution") is True, "dataset no-redistribution boundary is missing")
    require("DATASET_LICENSE_NOT_DECLARED" in str(terms.get("swebench_verified")), "SWE license absence is overstated")
    require("not legal clearance" in str(terms.get("execution_approval_requirement")), "legal approval boundary is missing")


def validate_targets() -> dict[str, list[dict[str, Any]]]:
    plan = read_json(CONFIG / "selection_plan.json")
    require(plan.get("schema") == "trimem/selection-plan/3.0", "selector v3 is not frozen")
    require(plan.get("row_score") == "sha256(seed|trimem-selector-v3|split|benchmark_id|instance_id), ascending lowercase bytes", "selector score is not public-identity-only")
    require(plan.get("source_policy", {}).get("per_slot_nonce_or_override_allowed") is False, "selector permits per-slot override")
    forbidden_text = " ".join(strings(plan)).lower()
    require("salt" not in forbidden_text and "nonce" not in forbidden_text.replace("per_slot_nonce_or_override_allowed", ""), "selector contains a salt/nonce escape hatch")
    manifests = {
        name: read_json(CONFIG / f"{name}_manifest.json")
        for name in ("development", "heldout")
    }
    smoke = read_json(CONFIG / "grader_smoke_manifest.json")
    manifests["grader-smoke"] = smoke
    require(
        "pooled resolved_count" in str(
            manifests["development"].get("tuning_selection_objective", "")
        )
        and "not the held-out primary endpoint" in str(
            manifests["development"].get("tuning_selection_objective", "")
        ),
        "development joint-tuning objective is not separated from held-out primary reporting",
    )
    expected_counts = {"development": 12, "heldout": 27, "grader-smoke": 12}
    result: dict[str, list[dict[str, Any]]] = {}
    for name, manifest in manifests.items():
        targets = manifest.get("targets")
        require(isinstance(targets, list) and len(targets) == expected_counts[name], f"{name} target count mismatch")
        require(manifest.get("status") in {"FROZEN", "FROZEN_TARGET_SET_EXECUTION_PENDING"}, f"{name} target set is not frozen")
        target_ids = [row.get("target_id") for row in targets]
        require(len(set(target_ids)) == len(target_ids), f"{name} target IDs are duplicated")
        require(
            hashlib.sha256(canonical(targets)).hexdigest() == manifest.get("target_set_sha256"),
            f"{name} canonical target-set digest mismatch",
        )
        for index, row in enumerate(targets):
            exact_hash(row.get("dataset_revision"), f"{name} dataset revision missing", 40)
            exact_hash(row.get("source_row_sha256"), f"{name} source row hash missing")
            exact_hash(row.get("base_commit"), f"{name} base commit missing", 40)
            if name != "grader-smoke":
                require(row.get("order_index") == index, f"{name} frozen order mismatch")
        if name != "grader-smoke":
            roles = manifest.get("benchmark_roles")
            require(isinstance(roles, list) and len(roles) == 3, f"{name} benchmark roles are missing")
            role_ids = [row.get("benchmark_id") for row in roles]
            require(len(set(role_ids)) == len(roles), f"{name} benchmark roles are duplicated")
            counts = Counter(row.get("benchmark_id") for row in targets)
            revisions = {
                benchmark_id: {row.get("dataset_revision") for row in targets if row.get("benchmark_id") == benchmark_id}
                for benchmark_id in counts
            }
            for role in roles:
                benchmark_id = role.get("benchmark_id")
                require(
                    set(role) == {"benchmark_id", "dataset_id", "dataset_revision", "role", "target_count"}
                    and counts.get(benchmark_id) == role.get("target_count")
                    and revisions.get(benchmark_id) == {role.get("dataset_revision")}
                    and role.get("role") in {"PRIMARY", "SECONDARY"},
                    f"{name} benchmark role/count/revision drift",
                )
            require(
                [row.get("benchmark_id") for row in roles if row.get("role") == "PRIMARY"]
                == ["swebench_verified"]
                and all(
                    row.get("role") == "SECONDARY"
                    for row in roles
                    if str(row.get("benchmark_id", "")).startswith("multi_swe_bench_")
                ),
                f"{name} primary/secondary endpoint roles drift",
            )
        result[name] = targets
    smoke_manifest = manifests["grader-smoke"]
    require(
        smoke_manifest.get("execution_control_amendment")
        == EXECUTION_CONTROL_AMENDMENT,
        "P0.1.1 non-semantic execution-control amendment differs",
    )
    require(
        smoke_manifest.get("multi_swe_prebuilt_evaluation_contract_amendment")
        == MULTI_SWE_PREBUILT_EVALUATION_CONTRACT_AMENDMENT,
        "P0.1.4 non-semantic Multi-SWE evaluation-contract amendment differs",
    )
    require(
        smoke_manifest.get("target_set_sha256") == BASELINE_TARGET_SET_SHA256,
        "P0.1.1 changed the frozen grader-smoke target set",
    )
    for relative, expected_sha256 in (
        *HISTORICAL_SENTINELS,
        (GRADER_SMOKE_FROZEN_REQUEST_PATH, BASELINE_FROZEN_REQUEST_SHA256),
        (GRADER_SMOKE_IMAGE_LOCK_PATH, BASELINE_IMAGE_LOCK_SHA256),
        (GRADER_SMOKE_PROTOCOL_PATH, BASELINE_PROTOCOL_SHA256),
    ):
        require(
            hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            == expected_sha256,
            f"P0.1.1 changed frozen scientific/control material: {relative}",
        )
    require(
        smoke_manifest.get("matrix_kind")
        == "single_serial_six_instance_gold_noop_campaign",
        "smoke manifest does not describe the single serial campaign",
    )
    pairs = Counter(
        (row["benchmark_id"], row["instance_id"])
        for row in result["grader-smoke"]
    )
    require(
        len(pairs) == 6 and set(pairs.values()) == {2},
        "smoke is not six GOLD/NOOP_BASELINE pairs",
    )
    for offset in range(0, len(result["grader-smoke"]), 2):
        gold, noop = result["grader-smoke"][offset : offset + 2]
        require(
            (gold.get("benchmark_id"), gold.get("instance_id"))
            == (noop.get("benchmark_id"), noop.get("instance_id"))
            and [gold.get("probe"), noop.get("probe")]
            == ["GOLD", "NOOP_BASELINE"],
            "smoke execution order is not deterministic GOLD then NOOP_BASELINE",
        )
    smoke_ids = {instance for _, instance in pairs}
    development_ids = {row["instance_id"] for row in result["development"]}
    heldout_ids = {row["instance_id"] for row in result["heldout"]}
    require(not (smoke_ids & development_ids or smoke_ids & heldout_ids or development_ids & heldout_ids), "target set instance overlap is nonzero")
    return result


def validate_images(targets: Mapping[str, list[dict[str, Any]]]) -> None:
    lock = read_json(ARTIFACT / "grader_image_lock.json")
    require(lock.get("status") == lock.get("smoke_status") == "FROZEN", "smoke image digests are not frozen")
    benchmark = lock.get("benchmark_target_images", {})
    require(benchmark.get("status") == "FROZEN" and benchmark.get("target_count") == 39, "all 39 benchmark images are not frozen")
    smoke_rows, benchmark_rows = lock.get("targets"), benchmark.get("targets")
    support_rows = lock.get("support_images")
    require(isinstance(smoke_rows, list) and len(smoke_rows) == 6, "smoke image lock count mismatch")
    require(isinstance(benchmark_rows, list) and len(benchmark_rows) == 39, "benchmark image lock count mismatch")
    require(isinstance(support_rows, list) and len(support_rows) == 1, "support image lock mismatch")
    expected_smoke = {row["instance_id"] for row in targets["grader-smoke"]}
    expected_benchmark = {row["instance_id"] for name in ("development", "heldout") for row in targets[name]}
    require({row.get("instance_id") for row in smoke_rows} == expected_smoke, "smoke image set drift")
    require({row.get("instance_id") for row in benchmark_rows} == expected_benchmark, "benchmark image set drift")
    for row in [*smoke_rows, *benchmark_rows, *support_rows]:
        image = row.get("image")
        require(isinstance(image, str) and DIGEST_IMAGE.fullmatch(image) is not None, "grader image is not digest-pinned")
        require(row.get("expected_digest") == image.rsplit("@", 1)[1], "image expected digest mismatch")
        exact_hash(row.get("registry_response_sha256"), "registry response provenance hash missing")
        require(str(row.get("registry_evidence_url", "")).startswith("https://hub.docker.com/v2/repositories/"), "image provenance is not official registry metadata")
    observation = lock.get("digest_observation", {})
    require(observation.get("docker_pull_or_run_performed") is False, "pre-EXEC image lock claims a Docker pull/run")
    started, completed = observation.get("query_started_at_utc"), observation.get("query_completed_at_utc")
    try:
        started_at = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        completed_at = datetime.fromisoformat(str(completed).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReadinessError("registry query timestamps are not exact") from exc
    require(started_at <= completed_at and "T00:00:00Z" not in str(started), "registry query timestamp is placeholder-like")
    material = "\n".join("|".join(str(row.get(key, "")) for key in (
        "benchmark_id", "instance_id", "registry_evidence_url", "expected_digest",
        "registry_last_updated_utc", "registry_response_sha256",
    )) for row in [*smoke_rows, *benchmark_rows, *support_rows])
    require(hashlib.sha256(material.encode("utf-8")).hexdigest() == observation.get("metadata_snapshot_sha256"), "registry metadata snapshot hash mismatch")


def validate_noop_baseline_audit(
    targets: Mapping[str, list[dict[str, Any]]]
) -> None:
    audit = read_json(ARTIFACT / "noop_baseline_six_commit_audit.json")
    body = {key: value for key, value in audit.items() if key != "audit_sha256"}
    require(
        audit.get("schema") == "trimem/noop-baseline-six-commit-audit/1.0"
        and audit.get("status") == "PASS"
        and audit.get("noop_baseline") == NOOP_BASELINE_LOCK
        and audit.get("manifest_target_set_sha256")
        == hashlib.sha256(canonical(targets["grader-smoke"])).hexdigest()
        and audit.get("audit_sha256")
        == hashlib.sha256(canonical(body)).hexdigest(),
        "NOOP_BASELINE six-base audit seal is invalid",
    )
    expected = {
        (row["repository"], row["instance_id"], row["base_commit"])
        for row in targets["grader-smoke"]
        if row.get("probe") == "GOLD"
    }
    rows = audit.get("rows")
    require(
        isinstance(rows, list) and len(rows) == 6,
        "NOOP_BASELINE audit row count is not six",
    )
    observed = set()
    for row in rows:
        require(isinstance(row, dict), "NOOP_BASELINE audit row is malformed")
        observed.add(
            (row.get("repository"), row.get("instance_id"), row.get("base_commit"))
        )
        require(
            row.get("root_marker_absent_at_base") is True
            and row.get("patch_applies_cached") is True
            and row.get("isolated_temporary_index") is True
            and row.get("changed_paths") == [NOOP_BASELINE_PATH]
            and row.get("forbidden_source_test_build_or_package_paths_touched") == []
            and row.get("staged_marker_sha256")
            == hashlib.sha256(NOOP_BASELINE_CONTENT).hexdigest()
            and isinstance(row.get("base_tree"), str)
            and HEX40.fullmatch(row["base_tree"]) is not None,
            "NOOP_BASELINE audit does not prove one safe new-file-only patch",
        )
    require(
        observed == expected,
        "NOOP_BASELINE audit target set differs from the smoke manifest",
    )


def validate_model_cost_environment() -> None:
    model = read_json(CONFIG / "model_lock.json")
    primary = model.get("primary_model", {})
    require(
        model.get("status")
        == "FROZEN_PRE_RESULT_SOLVE_EXECUTION_CONTRACT_AMENDMENT_PENDING_APPROVAL",
        "model lock status is overstated",
    )
    require(model.get("schema") == "trimem/model-lock/1.2", "model lock schema is stale")
    require(primary.get("model_id") == "gpt-5.4-mini-2026-03-17" and primary.get("status") == "FROZEN", "dated Mini model snapshot is not frozen")
    require((primary.get("input_price_per_million_tokens_usd"), primary.get("cached_input_price_per_million_tokens_usd"), primary.get("output_price_per_million_tokens_usd")) == (0.75, 0.075, 4.5), "official Mini model pricing drift")
    roles = model.get("model_roles", {})
    require(
        set(roles) == {"decomposition", "solve", "experience_extraction"}
        and all(
            isinstance(roles.get(role), dict)
            and roles[role].get("model_id") == "gpt-5.4-mini-2026-03-17"
            and roles[role].get("status") == "FROZEN_EXECUTION_PENDING_APPROVAL"
            for role in roles
        ),
        "decomposition, solving, and extraction are not locked to one Mini snapshot",
    )
    require("gpt-5.4-nano" not in " ".join(strings(model)).lower(), "Nano is mixed into the Mini model lock")
    require("gpt-5.6" not in " ".join(strings(model)), "unselected floating performance alternative remains")
    schema = model.get("request_schema")
    require(hashlib.sha256(canonical(schema)).hexdigest() == model.get("request_schema_sha256"), "request schema hash mismatch")
    require(
        schema.get("body", {}).get("model") == "gpt-5.4-mini-2026-03-17"
        and model.get("provider_bridge", {}).get("exact_returned_model_required")
        == "gpt-5.4-mini-2026-03-17",
        "request or returned-model lock differs from the Mini snapshot",
    )
    guard = model.get("conservative_input_guard", {})
    require(
        guard.get("documented_model_context_window_tokens") == 400000
        and guard.get("maximum_reserved_input_tokens_per_call") == 262000
        and guard.get("contract") == "PRESERVED_CONSERVATIVE_INPUT_CEILING",
        "preserved conservative input ceiling drift",
    )
    embedder = model.get("retrieval_embedding", {}).get("production", {})
    require((embedder.get("model_id"), embedder.get("revision"), embedder.get("dimension"), embedder.get("license")) == (
        "sentence-transformers/all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41", 384, "Apache-2.0"
    ), "production embedder lock drift")
    require(model.get("retrieval_embedding", {}).get("credential_free_fixture", {}).get("benchmark_execution_allowed") is False, "hash embedder is allowed in benchmark")
    require(
        model.get("actual_execution")
        == {
            "model_gateway_calls": 7,
            "paid_model_calls": 7,
            "provider_reported_usage": "MIXED_ONE_HISTORICAL_UNAVAILABLE_SIX_AVAILABLE",
            "completed_task_arm_runs": 0,
        },
        "historical DEV execution boundary differs",
    )
    output_schemas_path = CONFIG / "provider_output_schemas.json"
    output_schemas = read_json(output_schemas_path)
    schema_lock = read_json(ARTIFACT / "provider_output_schema_lock.json")
    require(
        output_schemas.get("schema") == "trimem/provider-output-schemas/1.0"
        and output_schemas.get("role_bindings")
        == {
            "decompose": "trimem_decomposition_v1",
            "extract": "trimem_experience_extraction_v1",
            "solve": None,
        }
        and schema_lock.get("schema") == "trimem/provider-output-schema-lock/1.0"
        and schema_lock.get("config_sha256")
        == hashlib.sha256(output_schemas_path.read_bytes()).hexdigest()
        and schema_lock.get("classification")
        == "PRE_RESULT_PROVIDER_OUTPUT_CONTRACT_AMENDMENT",
        "provider-native structured output schema lock differs",
    )
    response_amendment = read_json(
        ARTIFACT / "development_response_contract_amendment.json"
    )
    require(
        response_amendment.get("classification")
        == "PRE_RESULT_PROVIDER_OUTPUT_CONTRACT_AMENDMENT"
        and response_amendment.get("causal_boundary", {}).get(
            "historical_run_id"
        )
        == DEVELOPMENT_EXEC_003_RUN_ID
        and response_amendment.get("causal_boundary", {}).get(
            "historical_completed_task_arm_runs"
        )
        == 0
        and response_amendment.get("execution_boundary", {}).get(
            "fresh_request_id"
        )
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_004"
        and response_amendment.get("execution_boundary", {}).get(
            "required_authorization"
        )
        == "TRIMEM_V1_DEVELOPMENT_TUNING_RESPONSE_CONTRACT_RECOVERY_EXEC_APPROVED_ONCE",
        "D1.3 response-contract amendment differs",
    )
    solve_forensic_path = (
        ARTIFACT
        / "development_tuning_exec/exec-004/solve-0005-output-shape-forensics.json"
    )
    solve_forensic = read_json(solve_forensic_path)
    solve_budget_path = CONFIG / "solve_output_budget_contract.json"
    solve_budget = read_json(solve_budget_path)
    solve_budget_lock_path = ARTIFACT / "solve_output_budget_contract_lock.json"
    solve_budget_lock = read_json(solve_budget_lock_path)
    solve_amendment = read_json(
        ARTIFACT / "development_solve_execution_contract_amendment.json"
    )
    runtime = RuntimeLock()
    require(
        solve_forensic.get("forensic_status") == "CLASSIFIED_A"
        and solve_forensic.get("classification")
        == "SOLVE_TRUNCATED_WRITE_FILE_CONTENT"
        and solve_forensic.get("source", {}).get("run_id")
        == DEVELOPMENT_EXEC_004_RUN_ID
        and solve_forensic.get("provider_terminal", {}).get("api_terminal_cause")
        == "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"
        and solve_forensic.get("scientific_state", {}).get(
            "paid_model_calls_for_forensic"
        )
        == 0,
        "D1.4 sanitized solve forensic differs",
    )
    require(
        solve_budget.get("schema") == "trimem/solve-output-budget-contract/1.0"
        and solve_budget.get("task_arm_role_pools")
        == {"decomposition": 8192, "solve": 49152, "extraction": 8192, "total": 65536}
        and solve_budget.get("per_call_output_caps")
        == {"decomposition": 8192, "solve_maximum": 16384, "extraction": 8192}
        and solve_budget.get("development_phase", {}).get("output_tokens")
        == 4_718_592
        and solve_budget.get("development_phase", {}).get(
            "uncached_token_cost_ceiling_usd"
        )
        == 48.233664,
        "D1.4 solve-output budget contract differs",
    )
    implementation_lock = solve_budget_lock.get("implementation_sha256")
    require(
        solve_budget_lock.get("schema")
        == "trimem/solve-output-budget-contract-lock/1.0"
        and isinstance(implementation_lock, dict)
        and bool(implementation_lock)
        and solve_budget_lock.get("contract_sha256")
        == hashlib.sha256(solve_budget_path.read_bytes()).hexdigest()
        and all(
            relative in {
                "scripts/trimem_benchmark_run.py",
                "scripts/trimem_benchmark_matrix.py",
            }
            or hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
            for relative, digest in implementation_lock.items()
        ),
        "D1.4 solve-output implementation lock differs",
    )
    require(
        solve_amendment.get("classification")
        == "PRE_RESULT_SOLVE_EXECUTION_CONTRACT_AMENDMENT"
        and solve_amendment.get("edit_surface_classification")
        == "PRE_RESULT_SOLVE_EDIT_SURFACE_AMENDMENT"
        and solve_amendment.get("causal_boundary", {}).get("forensic_class")
        == "SOLVE_TRUNCATED_WRITE_FILE_CONTENT"
        and solve_amendment.get("execution_boundary", {}).get("fresh_request_id")
        == DEVELOPMENT_EXEC_005_REQUEST_ID
        and solve_amendment.get("execution_boundary", {}).get(
            "required_authorization"
        )
        == DEVELOPMENT_RECOVERY_AUTHORIZATION
        and solve_amendment.get("bindings")
        == {
            "historical_failure_receipt_sha256": DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_RAW_SHA256,
            "runtime_lock_content_sha256": runtime.content_hash,
            "sanitized_forensic_sha256": hashlib.sha256(
                solve_forensic_path.read_bytes()
            ).hexdigest(),
            "solve_output_budget_contract_lock_sha256": hashlib.sha256(
                solve_budget_lock_path.read_bytes()
            ).hexdigest(),
            "solve_prompt_sha256": runtime.prompt_hashes["solve_prompt"],
            "tool_schema_sha256": runtime.tool_hash,
        },
        "D1.4 solve-execution amendment differs",
    )
    require(
        (
            runtime.limits.max_output_tokens_decomposition,
            runtime.limits.max_output_tokens_per_solve,
            runtime.limits.max_total_solve_output_tokens_per_task_arm,
            runtime.limits.max_output_tokens_extraction,
            runtime.limits.max_total_output_tokens_per_task_arm,
        )
        == (8192, 16384, 49152, 8192, 65536)
        and any(row.get("name") == "replace_text" for row in runtime.tool_schema),
        "D1.4 runtime output pools or bounded edit tool differ",
    )

    cost = read_json(CONFIG / "cost_plan.json")
    require(cost.get("schema") == "trimem/cost-plan/1.4", "cost plan schema is stale")
    pricing = cost.get("model_pricing", {})
    require(
        (
            pricing.get("model_id"),
            pricing.get("input_per_million_tokens_usd"),
            pricing.get("cached_input_per_million_tokens_usd"),
            pricing.get("output_per_million_tokens_usd"),
        )
        == ("gpt-5.4-mini-2026-03-17", 0.75, 0.075, 4.5),
        "cost-plan Mini model or prices drift",
    )
    counts = cost.get("run_counts", {})
    require((counts.get("development_physical_task_arm_runs"), counts.get("heldout_physical_task_arm_runs"), counts.get("total_physical_task_arm_runs")) == (72, 81, 153), "physical run counts do not include four-candidate tuning")
    expected, hard = cost.get("expected_cost", {}), cost.get("proposed_hard_cap", {})
    require((expected.get("model_calls"), expected.get("input_tokens"), expected.get("output_tokens"), expected.get("total_usd")) == (2142, 25092000, 918000, 22.95), "expected cost arithmetic drift")
    require((hard.get("model_calls"), hard.get("input_tokens"), hard.get("output_tokens"), hard.get("total_usd"), hard.get("uncached_token_cost_ceiling_usd")) == (3978, 76500000, 10027008, 220.0, 102.496536), "proposed hard-cap arithmetic drift")
    phases = cost.get("phase_hard_caps", {})
    require(phases.get("DEVELOPMENT_TUNING", {}).get("task_arm_runs") == 72 and phases.get("HELDOUT_BENCHMARK", {}).get("task_arm_runs") == 81 and phases.get("GRADER_SMOKE", {}).get("benchmark_grader_containers") == 12, "phase hard caps are incomplete")
    expected_phases = expected.get("phase_totals", {})
    require(
        (
            expected_phases.get("DEVELOPMENT_TUNING", {}).get("task_arm_runs"),
            expected_phases.get("DEVELOPMENT_TUNING", {}).get("model_calls"),
            expected_phases.get("DEVELOPMENT_TUNING", {}).get("input_tokens"),
            expected_phases.get("DEVELOPMENT_TUNING", {}).get("output_tokens"),
            expected_phases.get("DEVELOPMENT_TUNING", {}).get("total_usd"),
        )
        == (72, 1008, 11808000, 432000, 10.8)
        and expected_phases.get("GRADER_SMOKE", {}).get("total_usd") == 0.0
        and expected_phases.get("HELDOUT_BENCHMARK", {}).get("total_usd") == 12.15,
        "phase expected-cost arithmetic drift",
    )
    require(
        (
            phases.get("DEVELOPMENT_TUNING", {}).get("total_usd"),
            phases.get("DEVELOPMENT_TUNING", {}).get("uncached_token_cost_ceiling_usd"),
            phases.get("HELDOUT_BENCHMARK", {}).get("total_usd"),
            phases.get("HELDOUT_BENCHMARK", {}).get("uncached_token_cost_ceiling_usd"),
        )
        == (50.0, 48.233664, 170.0, 54.262872),
        "phase hard-cap or pricing ceiling drift",
    )

    amendment = read_json(ARTIFACT / "development_model_pricing_amendment.json")
    require(
        amendment.get("schema") == "trimem/development-model-pricing-amendment/1.0"
        and amendment.get("status")
        == "FROZEN_PRE_EXECUTION_PENDING_SEPARATE_DEVELOPMENT_APPROVAL",
        "development model/pricing amendment is not frozen pre-execution",
    )
    amendment_body = amendment.get("amendment", {})
    require(
        amendment_body.get("classification") == "PRE_EXECUTION_COST_PERFORMANCE_AMENDMENT"
        and amendment_body.get("source_git_head")
        == "e40a549fcf92f270c86aaf97b3a9691c99b19fef"
        and amendment_body.get("source_freeze_raw_sha256")
        == "971ffcd9ad25a3904f0cfa8fb82631fb3bd162bcf91c918f4f63ef9e496b90fc"
        and amendment_body.get("after")
        == {
            "model_id": "gpt-5.4-mini-2026-03-17",
            "input_price_per_million_tokens_usd": 0.75,
            "cached_input_price_per_million_tokens_usd": 0.075,
            "output_price_per_million_tokens_usd": 4.5,
        }
        and amendment_body.get("before")
        == {
            "model_id": "gpt-5.4-2026-03-05",
            "input_price_per_million_tokens_usd": 2.5,
            "cached_input_price_per_million_tokens_usd": 0.25,
            "output_price_per_million_tokens_usd": 15.0,
        },
        "development model/pricing amendment identity drift",
    )
    require(
        amendment.get("causal_boundary")
        == {
            "benchmark_model_results_observed_before_amendment": False,
            "input_tokens_before_amendment": 0,
            "model_gateway_calls_before_amendment": 0,
            "output_tokens_before_amendment": 0,
            "paid_model_calls_before_amendment": 0,
            "task_arm_runs_before_amendment": 0,
            "total_usd_before_amendment": 0,
        },
        "pre-execution causal boundary is not zero-result",
    )
    require(
        amendment.get("role_lock")
        == {
            "decomposition": "gpt-5.4-mini-2026-03-17",
            "experience_extraction": "gpt-5.4-mini-2026-03-17",
            "mixed_nano_model": False,
            "solve": "gpt-5.4-mini-2026-03-17",
        },
        "amendment role lock is not all-Mini",
    )
    require(
        amendment.get("planning_consequences", {}).get("heldout_expected_total_usd") == 12.15
        and amendment.get("planning_consequences", {}).get("heldout_hard_cap_total_usd") == 170.0
        and amendment.get("planning_consequences", {}).get("global_expected_total_usd") == 22.95
        and amendment.get("planning_consequences", {}).get("global_hard_cap_total_usd") == 220.0,
        "amendment planning consequences drift",
    )
    development_contract = amendment.get("development_contract", {})
    require(
        (
            development_contract.get("targets"),
            development_contract.get("m2_joint_candidates"),
            development_contract.get("task_arm_runs"),
            development_contract.get("benchmark_grader_containers"),
            development_contract.get("expected_model_calls"),
            development_contract.get("expected_input_tokens"),
            development_contract.get("expected_output_tokens"),
            development_contract.get("expected_total_usd"),
            development_contract.get("hard_cap_paid_model_calls"),
            development_contract.get("hard_cap_input_tokens"),
            development_contract.get("hard_cap_output_tokens"),
            development_contract.get("hard_cap_total_usd"),
        )
        == (12, 4, 72, 72, 1008, 11808000, 432000, 10.8, 1872, 36000000, 3796992, 50.0),
        "development amendment workload or cost boundary drift",
    )
    execution_boundary = amendment.get("execution_boundary", {})
    require(
        execution_boundary.get("active_development_approval") is False
        and execution_boundary.get("development_execution_authorized") is False
        and execution_boundary.get("grader_smoke_rerun_authorized") is False
        and execution_boundary.get("heldout_execution_authorized") is False
        and execution_boundary.get("new_freeze_required_before_approval") is True
        and execution_boundary.get("separate_external_development_approval_required") is True,
        "amendment overstates execution authority",
    )
    preserved = amendment.get("preserved_contracts", {}).get("path_sha256")
    expected_preserved_paths = {
        "artifacts/trimem_v1/grader_image_lock.json",
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/grader_smoke_manifest.json",
        "configs/trimem_v1/heldout_manifest.json",
        "configs/trimem_v1/m2_candidate_bundles.json",
        "configs/trimem_v1/selected_m2.json",
        "configs/trimem_v1/selection_plan.json",
        "configs/trimem_v1/tool_environment_lock.json",
        "src/enterprise_memory/trimem/runtime_lock.py",
    }
    require(isinstance(preserved, dict) and set(preserved) == expected_preserved_paths, "preserved amendment path set drift")
    d13_mutable = {
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/m2_candidate_bundles.json",
        "configs/trimem_v1/selected_m2.json",
        "configs/trimem_v1/tool_environment_lock.json",
        "src/enterprise_memory/trimem/runtime_lock.py",
    }
    for relative, expected_sha256 in preserved.items():
        if relative not in d13_mutable:
            require(
                hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected_sha256,
                f"D1.3 changed a contract outside its authorized scope: {relative}",
            )
    counter_fields = {
        "api_calls", "cached_input_tokens", "decomposition_calls",
        "docker_pulls", "extraction_calls", "grader_calls",
        "grader_containers", "input_tokens", "model_calls",
        "model_gateway_calls", "official_grader_runs", "output_tokens",
        "paid_model_calls", "reasoning_tokens", "solve_calls",
        "support_image_pulls", "target_image_pulls", "task_arm_runs",
        "total_usd",
    }
    historical = _validated_p014_historical_execution()
    historical_accounting = historical["execution_accounting"]
    historical_lifecycle = historical["image_lifecycle"]
    p014_actual = {
        **historical_accounting,
        "support_image_pulls": historical_lifecycle["support_image_pulls"],
        "target_image_pulls": historical_lifecycle["target_image_pulls"],
    }
    post_smoke = _validated_post_smoke_readiness_state()
    p015_actual = post_smoke["execution_counters"]
    require(
        set(p014_actual) == counter_fields
        and set(p015_actual) == counter_fields,
        "grader-smoke accounting window counter fields differ",
    )
    cumulative = {
        field: p014_actual[field] + p015_actual[field]
        for field in counter_fields
    }
    require(
        cumulative
        == {
            "api_calls": 0,
            "cached_input_tokens": 0,
            "decomposition_calls": 0,
            "docker_pulls": 11,
            "extraction_calls": 0,
            "grader_calls": 18,
            "grader_containers": 18,
            "input_tokens": 0,
            "model_calls": 0,
            "model_gateway_calls": 0,
            "official_grader_runs": 18,
            "output_tokens": 0,
            "paid_model_calls": 0,
            "reasoning_tokens": 0,
            "solve_calls": 0,
            "support_image_pulls": 2,
            "target_image_pulls": 9,
            "task_arm_runs": 0,
            "total_usd": 0,
        },
        "cumulative grader-smoke actual accounting differs",
    )
    actual_to_date = cost.get("actual_to_date", {})
    require(
        isinstance(actual_to_date, dict)
        and actual_to_date.get("api_calls") == 7
        and actual_to_date.get("decomposition_calls") == 2
        and actual_to_date.get("solve_calls") == 5
        and actual_to_date.get("model_calls") == 7
        and actual_to_date.get("model_gateway_calls") == 7
        and actual_to_date.get("paid_model_calls") == 7
        and actual_to_date.get("provider_reported_usage")
        == "MIXED_ONE_HISTORICAL_UNAVAILABLE_SIX_AVAILABLE"
        and actual_to_date.get("input_tokens") is None
        and actual_to_date.get("output_tokens") is None
        and actual_to_date.get("reasoning_tokens") is None
        and actual_to_date.get("known_provider_input_tokens") == 54_620
        and actual_to_date.get("known_provider_cached_input_tokens") == 17_664
        and actual_to_date.get("known_provider_output_tokens") == 4_203
        and actual_to_date.get("known_provider_reasoning_tokens") == 1_485
        and actual_to_date.get("ledger_reservation")
        == {"input_tokens": 5069, "output_tokens": 2048, "total_usd": 0.01301775}
        and actual_to_date.get("docker_pulls") == 24
        and actual_to_date.get("extraction_calls") == 0
        and actual_to_date.get("grader_calls") == 18
        and actual_to_date.get("grader_containers") == 18
        and actual_to_date.get("official_grader_runs") == 18
        and actual_to_date.get("support_image_pulls") == 3
        and actual_to_date.get("target_image_pulls") == 21
        and actual_to_date.get("task_arm_runs") == 0
        and actual_to_date.get("total_usd") == 0.06097305,
        "cumulative historical DEV usage/reservation accounting differs",
    )
    accounting_windows = cost.get("accounting_windows", {})
    require(
        cost.get("actual_to_date_scope")
        == "CUMULATIVE_INCLUDES_GRADER_HISTORY_AND_DEV_RUNS_33788493773_33840007588_ATTEMPT_1"
        and set(accounting_windows)
        == {
            "d13_historical_dev_exec_003",
            "d13_historical_dev_exec_004",
            "p014_diagnostic_history",
            "p015_correction_pre_exec_005",
            "p015_authoritative_exec_005",
        }
        and accounting_windows["d13_historical_dev_exec_003"].get("api_calls") == 1
        and accounting_windows["d13_historical_dev_exec_003"].get(
            "provider_reported_usage"
        )
        == "UNAVAILABLE_DUE_TO_ADAPTER_OBSERVABILITY_GAP"
        and accounting_windows["d13_historical_dev_exec_003"].get(
            "completed_task_arm_runs"
        )
        == 0
        and accounting_windows["d13_historical_dev_exec_004"]
        == {
            "api_calls": 6,
            "cached_input_tokens": 17664,
            "completed_task_arm_runs": 0,
            "decomposition_calls": 1,
            "extraction_calls": 0,
            "git_head": DEVELOPMENT_EXEC_004_HEAD,
            "grader_containers": 0,
            "input_tokens": 54620,
            "model_calls": 6,
            "model_gateway_calls": 6,
            "official_grader_runs": 0,
            "output_tokens": 4203,
            "paid_model_calls": 6,
            "provider_reported_usage": "AVAILABLE_FOR_ALL_CALLS",
            "reasoning_tokens": 1485,
            "scope": "IMMUTABLE_HISTORICAL_DEV_EXECUTION",
            "solve_calls": 5,
            "started_task_arm_runs": 1,
            "support_image_pulls": 1,
            "target_image_pulls": 12,
            "task_arm_runs": 0,
            "total_usd": 0.0479553,
            "workflow_run_attempt": 1,
            "workflow_run_id": DEVELOPMENT_EXEC_004_RUN_ID,
        },
        "grader/DEV accounting windows differ",
    )

    environment = read_json(CONFIG / "benchmark_environment_lock.json")
    dependency = environment.get("dependency_lock", {})
    for field, path in (("input_sha256", CONFIG / "benchmark_environment.in"), ("lock_sha256", CONFIG / "benchmark_environment.lock")):
        require(hashlib.sha256(path.read_bytes()).hexdigest() == dependency.get(field), f"benchmark environment {field} mismatch")
    runner = environment.get("runner", {})
    require(runner.get("benchmark_exec_runner_labels") == ["self-hosted", "linux", "x64", "ubuntu-24.04", "trimem-benchmark"] and runner.get("benchmark_exec_max_job_minutes") == 7200, "long-running protected benchmark runner is not frozen")
    harness_lock = validate_harness_lock_configuration()
    require(
        harness_lock
        == {
            "benchmark_ids": [
                "multi_swe_bench_flash",
                "multi_swe_bench_mini",
                "swebench_verified",
            ],
            "dependency_count": 3,
            "hash_basis": HARNESS_DEPENDENCY_HASH_BASIS,
            "portable_projection_sha256": "042c8cfb2478f5515541a387575c7124312095df7e82d4e30798c7d82926df39",
        },
        "pinned harness Git-blob dependency lock is not exact",
    )
    require(environment.get("embedding_execution", {}).get("benchmark_hash_embedder_allowed") is False, "benchmark environment allows the fixture embedder")


def validate_p015_semantics_and_envelope_contracts() -> dict[str, Any]:
    """Bind readiness to the production semantic/envelope implementations."""

    semantics = validate_report_semantics_lock(ROOT)
    require(
        semantics.get("schema")
        == "trimem/multi-swe-report-semantics-lock-validation/1.0"
        and semantics.get("status") == "PASS"
        and semantics.get("source_blobs") == 5,
        "Multi-SWE report-semantics production lock validation differs",
    )

    contract = read_json(ARTIFACT / "adapter_failure_envelope_contract.json")
    require(
        set(contract)
        == {
            "adapter_evidence",
            "authority_recovery",
            "authority_rollback",
            "campaign_finalization_journal",
            "failure_contract",
            "failure_taxonomy_fields",
            "failure_taxonomy_rules",
            "historical_p014_classification",
            "official_outcome_contract",
            "pre_cell_failure",
            "public_privacy",
            "scope",
            "schema",
            "status",
            "terminal_accounting",
            "terminal_cell",
        }
        and contract.get("schema")
        == "trimem/adapter-failure-envelope-contract/1.0"
        and contract.get("status") == "FROZEN_PRE_EXEC"
        and contract.get("scope")
        == {
            "docker_calls": 0,
            "grader_calls": 0,
            "model_api_calls": 0,
            "paid_model_calls": 0,
        },
        "adapter failure-envelope outer contract differs",
    )
    production = adapter_evidence_envelope_contract()
    adapter = contract.get("adapter_evidence")
    require(
        isinstance(adapter, dict)
        and adapter.get("canonical_root") == production["canonical_root"]
        and adapter.get("compatibility_aliases")
        == production["compatibility_aliases"]
        and adapter.get("evidence_schema") == production["schema"]
        and set(adapter.get("evidence_fields", ()))
        == set(production["trimem_fields"])
        and set(adapter.get("top_level_fields", ()))
        == set(production["top_level_fields"])
        and adapter.get("top_level_policy")
        == "NON_TRIMEM_TOP_LEVEL_IS_PUBLIC_SUMMARY; _trimem_IS_RESTRICTED_ADAPTER_EVIDENCE",
        "adapter evidence artifact differs from production envelope projection",
    )
    failure = contract.get("failure_contract")
    require(
        isinstance(failure, dict)
        and failure.get("original_primary_error_preserved") is True
        and failure.get("secondary_evidence_failures")
        == "SEPARATE_ORDERED_LIST_NEVER_REPLACES_PRIMARY"
        and failure.get("evidence_preservation_pipeline")
        == {
            "encrypted_upload": "ALWAYS_WHEN_ENCRYPTION_SUCCEEDS",
            "encryption": (
                "ALWAYS_AFTER_APPROVAL_MATERIALIZATION; "
                "INCLUDES_INVENTORY_WHEN_AVAILABLE"
            ),
            "failure_closure": (
                "REQUIRES_INVENTORY_SUCCESS_AND_AUTHORITY_RECOVERY_SUCCESS_OR_SKIP"
            ),
            "failure_closure_upload": "ALWAYS_WHEN_FAILURE_CLOSURE_SUCCEEDS",
            "inventory": (
                "ALWAYS_AFTER_APPROVAL_MATERIALIZATION; "
                "INDEPENDENT_OF_AUTHORITY_RECOVERY_OUTCOME"
            ),
            "inventory_upload": "ALWAYS_WHEN_INVENTORY_SUCCEEDS",
            "plaintext_cleanup": (
                "REQUIRES_ENCRYPTED_UPLOAD_SUCCESS; "
                "OTHERWISE_PRESERVE_PLAINTEXT_AND_CIPHERTEXT_AND_FAIL"
            ),
        }
        and production.get("primary_error_policy")
        == "PRIMARY_PRESERVED_SECONDARY_EVIDENCE_ERRORS_SEPARATE"
        and failure.get("adapter_failure", {}).get("adapter_normalized") is False
        and failure.get("adapter_failure", {}).get("scientific_resolved") is None
        and production.get("failure_outcome_policy", {}).get(
            "grade_result_resolved_authoritative"
        )
        is False,
        "adapter failure/error-preservation contract differs from production",
    )
    official_outcome = contract.get("official_outcome_contract")
    require(
        isinstance(official_outcome, dict)
        and official_outcome
        == {
            "adapter_failure_after_final_report": {
                "adapter_normalized": False,
                "official_final_report_resolved": "PRESERVE_OBSERVED_BOOLEAN",
                "scientific_resolved": None,
            },
            "aggregate_authority_predicate": (
                "status == success AND adapter_normalized == true"
            ),
            "success": {
                "adapter_normalized": True,
                "official_final_report_resolved": "EQUALS_SCIENTIFIC_RESOLVED",
                "scientific_resolved": "BOOLEAN",
            },
        },
        "underlying official-outcome authority contract differs",
    )
    terminal = contract.get("terminal_cell")
    require(
        isinstance(terminal, dict)
        and terminal.get("schema") == TERMINAL_CELL_SCHEMA
        and terminal.get("exactly_one_per_attempted_cell") is True
        and set(terminal.get("required_lifecycle_fields", ()))
        == set(TERMINAL_LIFECYCLE_FIELDS)
        and set(terminal.get("record_fields", ())) == set(TERMINAL_CELL_FIELDS)
        and set(contract.get("failure_taxonomy_fields", ()))
        == set(GRADER_SMOKE_FAILURE_TAXONOMY_FIELDS),
        "terminal-cell/failure-taxonomy artifact differs from production",
    )
    taxonomy_projection = [
        {
            "counter": rule["counter"],
            "exact_stages": list(rule["exact_stages"]),
            "fallback": rule["fallback"],
            "stage_prefixes": list(rule["stage_prefixes"]),
        }
        for rule in GRADER_SMOKE_FAILURE_TAXONOMY_RULES
    ]
    require(
        contract.get("failure_taxonomy_rules") == taxonomy_projection
        and [rule["counter"] for rule in taxonomy_projection]
        == [
            "image_lifecycle_failures",
            "official_harness_failures",
            "official_report_failures",
            "environment_failures",
            "infrastructure_failures",
            "aggregate_failures",
            "adapter_contract_failures",
        ]
        and taxonomy_projection[-1]["fallback"] is True
        and all(rule["fallback"] is False for rule in taxonomy_projection[:-1]),
        "ordered failure-taxonomy production rules differ",
    )
    pre_cell = contract.get("pre_cell_failure")
    require(
        pre_cell
        == {
            "actual_execution": PRE_CELL_ZERO_EXECUTION,
            "schema": PRE_CELL_FAILURE_SCHEMA,
            "stage_taxonomy": PRE_CELL_STAGE_TAXONOMY,
            "terminal_record_count": 0,
        },
        "pre-cell failure contract differs from production",
    )
    authority = contract.get("authority_rollback")
    require(
        authority
        == {
            "cause_taxonomy": AUTHORITY_ROLLBACK_CAUSE_TAXONOMY,
            "grant_capability": False,
            "release_authority_additional_requirements": [
                "exact successful GitHub workflow run attempt",
                "restricted evidence inventory and encrypted upload",
                "cleaned plaintext",
                "verified attestation subject and bundle",
            ],
            "schema": AUTHORITY_ROLLBACK_EVIDENCE_SCHEMA,
            "scientific_authority_scope": (
                "authoritative_cell is cell-level scientific authority; final campaign "
                "eligibility additionally requires the exact successful signed workflow attempt"
            ),
            "transition": {"after": False, "before": True},
        },
        "authority rollback/release contract differs from production",
    )
    authority_recovery = contract.get("authority_recovery")
    require(
        authority_recovery
        == {
            "canonical_state_after": "FALSE",
            "canonical_states_before": [
                "ABSENT",
                "FALSE",
                "INCOMPLETE",
                "MIXED",
                "TRUE",
            ],
            "cause_taxonomy": AUTHORITY_ROLLBACK_CAUSE_TAXONOMY,
            "failure_closure_requires_recovery_success_or_skip": True,
            "finalization_journal_required_for_run_smoke_authority_qualification": True,
            "grant_capability": False,
            "recovery_sources": [
                "canonical_false",
                "promotion_original",
                "rollback_replacement",
            ],
            "schema": AUTHORITY_RECOVERY_EVIDENCE_SCHEMA,
            "transaction_markers": [
                AUTHORITY_PROMOTION_TRANSACTION_MARKER,
                AUTHORITY_ROLLBACK_TRANSACTION_MARKER,
            ],
        },
        "authority interrupted-transaction recovery contract differs from production",
    )
    finalization_journal = contract.get("campaign_finalization_journal")
    require(
        finalization_journal
        == {
            "expected_terminal_record_count": FINALIZATION_TERMINAL_COUNT,
            "path": FINALIZATION_JOURNAL_RELATIVE_PATH.as_posix(),
            "schema": FINALIZATION_JOURNAL_SCHEMA,
            "status_taxonomy": {
                FINALIZATION_AUTHORITY_COMMITTED: None,
                FINALIZATION_AUTHORITY_STARTED: "infrastructure_failures",
                FINALIZATION_SCIENTIFIC_REJECTED: "aggregate_failures",
            },
            "required_before_authority_promotion": True,
            "required_for_scientific_aggregate_rejection": True,
            "required_to_qualify_false_tree_run_smoke_failure": True,
            "terminal_bytes_content_bound": True,
            "transition": [
                FINALIZATION_AUTHORITY_STARTED,
                FINALIZATION_AUTHORITY_COMMITTED,
            ],
        },
        "campaign-finalization journal contract differs from production",
    )
    privacy = contract.get("public_privacy")
    require(
        privacy
        == {
            "adapter_trimem_root": "RESTRICTED_EVIDENCE_NOT_THE_PUBLIC_ARTIFACT",
            "private_failure_reasons": (
                "DIGEST_AND_BYTE_COUNT_ONLY_IN_PUBLIC_FAILURE_CLOSURE"
            ),
            "public_outcome_fields": list(SMOKE_OUTCOME_FIELDS),
            "raw_test_names_published": False,
        },
        "public adapter/failure evidence privacy contract differs",
    )
    historical = contract.get("historical_p014_classification")
    expected_historical = _validated_p014_historical_execution()
    require(
        isinstance(historical, dict)
        and historical.get("run_id") == expected_historical["workflow_run_id"]
        and historical.get("run_attempt")
        == expected_historical["workflow_run_attempt"]
        and {
            key: historical.get(key)
            for key in GRADER_SMOKE_FAILURE_TAXONOMY_FIELDS
        }
        == expected_historical["failure_taxonomy"],
        "adapter contract P0.1.4 failure taxonomy differs",
    )
    terminal_accounting = contract.get("terminal_accounting")
    require(
        terminal_accounting
        == {
            "adapter_normalized_count": "sum(adapter_normalized is true)",
            "attempted_cell_count": "count(exact terminal records)",
            "authoritative_cell_count": "sum(authoritative_cell is true)",
            "complete_execution_evidence_count": (
                "sum(complete execution lifecycle evidence is true)"
            ),
            "historical_six_five_fixture": expected_historical["campaign"],
            "official_execution_count": "sum(container_started is true)",
            "terminal_record_count": "count(exact terminal records)",
            "unattempted_cell_count": (
                "max(0, expected_cell_count - attempted_cell_count)"
            ),
        },
        "terminal accounting formulas/fixture differ from production evidence",
    )
    return {
        **semantics,
        "adapter_failure_envelope_contract_sha256": hashlib.sha256(
            (ARTIFACT / "adapter_failure_envelope_contract.json").read_bytes()
        ).hexdigest(),
    }


def _validated_post_smoke_readiness_state() -> dict[str, Any]:
    """Derive the post-smoke readiness closure from authoritative PASS evidence."""

    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    smoke_actual = validate_grader_smoke_result(smoke)
    require(smoke.get("status") == "PASS", "readiness requires authoritative exec-005 PASS")
    evidence = smoke.get("official_execution_evidence")
    require(isinstance(evidence, dict), "readiness success evidence is missing")

    public_raw = (ROOT / OFFICIAL_SMOKE_PUBLIC_RESULT_PATH).read_bytes()
    require(
        evidence.get("public_result_raw_sha256")
        == hashlib.sha256(public_raw).hexdigest(),
        "readiness public result changed after smoke validation",
    )
    public = _strict_json_bytes(
        public_raw, label=OFFICIAL_SMOKE_PUBLIC_RESULT_PATH
    )
    approval = evidence.get("approval_binding")
    require(
        isinstance(approval, dict)
        and approval.get("approved_workflow_run_id") == SMOKE_PASS_RUN_ID
        and approval.get("approved_workflow_run_attempt") == SMOKE_PASS_RUN_ATTEMPT
        and approval.get("git_head") == SMOKE_PASS_EXECUTION_HEAD,
        "readiness exec-005 workflow identity differs",
    )

    probe_counts = public.get("probe_counts")
    resolved_counts = public.get("resolved_counts")
    unresolved_counts = public.get("unresolved_counts")
    scientific_result = {
        "gold_resolved": resolved_counts.get("GOLD")
        if isinstance(resolved_counts, dict)
        else None,
        "gold_total": probe_counts.get("GOLD")
        if isinstance(probe_counts, dict)
        else None,
        "noop_unresolved": unresolved_counts.get("NOOP_BASELINE")
        if isinstance(unresolved_counts, dict)
        else None,
        "noop_total": probe_counts.get("NOOP_BASELINE")
        if isinstance(probe_counts, dict)
        else None,
        "status": public.get("status"),
    }
    require(
        scientific_result
        == {
            "gold_resolved": 6,
            "gold_total": 6,
            "noop_unresolved": 6,
            "noop_total": 6,
            "status": "PASS",
        },
        "readiness scientific GOLD/NOOP result differs",
    )

    accounting = public.get("actual_accounting")
    lifecycle = public.get("image_lifecycle")
    lifecycle_actual = lifecycle.get("actual") if isinstance(lifecycle, dict) else None
    require(
        isinstance(accounting, dict) and isinstance(lifecycle_actual, dict),
        "readiness execution accounting evidence is missing",
    )
    execution_counters = {
        "api_calls": accounting.get("api_calls"),
        "cached_input_tokens": accounting.get("cached_input_tokens"),
        "decomposition_calls": accounting.get("decomposition_calls"),
        "docker_pulls": smoke_actual.get("docker_pulls"),
        "extraction_calls": accounting.get("extraction_calls"),
        "grader_calls": accounting.get("grader_calls"),
        "grader_containers": accounting.get("grader_containers"),
        "input_tokens": accounting.get("input_tokens"),
        "model_calls": accounting.get("model_calls"),
        "model_gateway_calls": accounting.get("model_gateway_calls"),
        "official_grader_runs": accounting.get("official_grader_runs"),
        "output_tokens": accounting.get("output_tokens"),
        "paid_model_calls": accounting.get("paid_model_calls"),
        "reasoning_tokens": accounting.get("reasoning_tokens"),
        "solve_calls": accounting.get("solve_calls"),
        "support_image_pulls": lifecycle_actual.get("support_image_pulls"),
        "target_image_pulls": lifecycle_actual.get("target_image_pulls"),
        "task_arm_runs": accounting.get("task_arm_runs"),
        "total_usd": accounting.get("total_usd"),
    }
    require(
        execution_counters
        == {
            "api_calls": 0,
            "cached_input_tokens": 0,
            "decomposition_calls": 0,
            "docker_pulls": 7,
            "extraction_calls": 0,
            "grader_calls": 12,
            "grader_containers": 12,
            "input_tokens": 0,
            "model_calls": 0,
            "model_gateway_calls": 0,
            "official_grader_runs": 12,
            "output_tokens": 0,
            "paid_model_calls": 0,
            "reasoning_tokens": 0,
            "solve_calls": 0,
            "support_image_pulls": 1,
            "target_image_pulls": 6,
            "task_arm_runs": 0,
            "total_usd": 0,
        }
        and execution_counters["docker_pulls"]
        == execution_counters["support_image_pulls"]
        + execution_counters["target_image_pulls"],
        "readiness exec-005 accounting differs",
    )

    failure_receipt = ROOT / OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
    require(
        not failure_receipt.exists(),
        "passed exec-005 must not carry a failure-closure receipt",
    )
    return {
        "current_status": {
            "DEV_APPROVAL_ALLOWED": "YES",
            "DEV_EXECUTION_ALLOWED": "NO",
            "ENDPOINT": SMOKE_PASS_ENDPOINT,
            "GRADER_EXEC_PACKAGE": "PASS",
            "OFFICIAL_GRADER_VIABILITY": "ESTABLISHED",
            "PERFORMANCE": "NOT_MEASURED",
            "SCIENTIFIC_RESULT": SMOKE_PASS_SCIENTIFIC_RESULT,
            "TRIMEM_SYSTEM_IMPLEMENTATION": "CREDENTIAL_FREE_GREEN",
        },
        "execution_counter_scope": SMOKE_PASS_READINESS_SCOPE,
        "execution_counters": execution_counters,
        "failure_closure": {
            "failure_receipt_path": OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
            "failure_receipt_present": False,
            "historical_p014_paths_reused": False,
            "schema": SMOKE_PASS_FAILURE_CLOSURE_STATUS_SCHEMA,
            "status": "NOT_APPLICABLE_PASS",
        },
        "scientific_result": scientific_result,
        "success_evidence": {
            "schema": SMOKE_PASS_SUCCESS_EVIDENCE_SCHEMA,
            "status": "PASS",
            **evidence,
        },
    }


def _validated_development_preflight_failure() -> dict[str, Any]:
    receipt_path = ROOT / DEVELOPMENT_EXEC_001_FAILURE_RECEIPT_PATH
    receipt_raw = receipt_path.read_bytes()
    require(
        hashlib.sha256(receipt_raw).hexdigest()
        == DEVELOPMENT_EXEC_001_FAILURE_RECEIPT_RAW_SHA256
        == DEVELOPMENT_RECOVERY_INPUT_SHA256[
            DEVELOPMENT_EXEC_001_FAILURE_RECEIPT_PATH
        ],
        "DEV _001 preflight-failure receipt bytes differ",
    )
    receipt = read_json(receipt_path)
    expected_accounting = {
        "api_calls": 0,
        "cached_input_tokens": 0,
        "decomposition_calls": 0,
        "extraction_calls": 0,
        "grader_calls": 0,
        "grader_containers": 0,
        "input_tokens": 0,
        "model_calls": 0,
        "model_gateway_calls": 0,
        "official_grader_runs": 0,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "reasoning_tokens": 0,
        "solve_calls": 0,
        "support_image_pulls": 0,
        "target_image_pulls": 0,
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }
    require(
        receipt.get("schema")
        == "trimem/development-trigger-preflight-failure-receipt/1.0"
        and receipt.get("endpoint") == DEVELOPMENT_INCOMPLETE_ENDPOINT
        and receipt.get("failure_label")
        == DEVELOPMENT_EXEC_001_FAILURE_LABEL
        and receipt.get("execution_accounting") == expected_accounting,
        "DEV _001 failure receipt status or zero-execution accounting differs",
    )
    sentinel = receipt.get("sentinel", {})
    workflow = receipt.get("workflow_run", {})
    jobs = receipt.get("jobs", {})
    control = receipt.get("control_plane", {})
    recovery_contract = receipt.get("recovery_contract", {})
    require(
        sentinel.get("path") == DEVELOPMENT_EXEC_001_SENTINEL_PATH
        and sentinel.get("raw_sha256")
        == "sha256:" + DEVELOPMENT_EXEC_001_REQUEST_RAW_SHA256
        and workflow.get("id") == DEVELOPMENT_EXEC_001_RUN_ID
        and workflow.get("run_attempt") == DEVELOPMENT_EXEC_001_RUN_ATTEMPT
        and workflow.get("head_sha") == DEVELOPMENT_EXEC_001_HEAD
        and jobs.get("hosted_preflight", {}).get("conclusion") == "failure"
        and jobs.get("protected_execution", {}).get("conclusion") == "skipped"
        and jobs.get("protected_execution", {}).get("steps") == 0
        and control.get("approval_materialization_reached") is False
        and control.get("matching_protected_deployments") == 0
        and control.get("run_artifacts") == 0
        and control.get("environment_secret_count_after_cleanup") == 0,
        "DEV _001 immutable run/control-plane evidence differs",
    )
    require(
        recovery_contract.get("received_recovery_authorization")
        == DEVELOPMENT_EXEC_001_RECOVERY_AUTHORIZATION
        and recovery_contract.get("protected_execution_authorization_required")
        == DEVELOPMENT_EXEC_001_EXTERNAL_AUTHORIZATION,
        "DEV recovery and protected-execution authorities are conflated",
    )
    return {
        "endpoint": DEVELOPMENT_INCOMPLETE_ENDPOINT,
        "evidence": {
            "failure_receipt_path": DEVELOPMENT_EXEC_001_FAILURE_RECEIPT_PATH,
            "failure_receipt_raw_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "previous_request_path": DEVELOPMENT_EXEC_001_SENTINEL_PATH,
            "previous_request_raw_sha256": DEVELOPMENT_EXEC_001_REQUEST_RAW_SHA256,
        },
        "execution_accounting": expected_accounting,
        "failure_label": DEVELOPMENT_EXEC_001_FAILURE_LABEL,
        "recovery": {
            "attempt_two_allowed": False,
            "protected_execution_authorization_required": (
                DEVELOPMENT_EXEC_001_EXTERNAL_AUTHORIZATION
            ),
            "received_recovery_authorization": (
                DEVELOPMENT_EXEC_001_RECOVERY_AUTHORIZATION
            ),
            "request_id": DEVELOPMENT_EXEC_002_REQUEST_ID,
            "request_path": DEVELOPMENT_EXEC_002_SENTINEL_PATH,
            "single_new_attempt_one_run_allowed": True,
        },
        "schema": "trimem/development-preflight-failure-status/1.0",
        "status": "RECOVERY_002_APPROVED_PENDING_SENTINEL",
        "workflow_run": {
            "head_sha": workflow["head_sha"],
            "id": workflow["id"],
            "run_attempt": workflow["run_attempt"],
        },
    }


def _validated_development_exec_002_failure() -> dict[str, Any]:
    """Validate the immutable, final `_002` pre-scientific failure."""

    receipt_path = ROOT / DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_PATH
    report_path = ROOT / DEVELOPMENT_EXEC_002_FAILURE_REPORT_PATH
    receipt_raw = receipt_path.read_bytes()
    report_raw = report_path.read_bytes()
    require(
        hashlib.sha256(receipt_raw).hexdigest()
        == DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_RAW_SHA256,
        "DEV _002 protected-gate failure receipt bytes differ",
    )
    require(
        hashlib.sha256(report_raw).hexdigest()
        == DEVELOPMENT_EXEC_002_FAILURE_REPORT_RAW_SHA256,
        "DEV _002 protected-gate failure report bytes differ",
    )
    receipt = _strict_json_bytes(
        receipt_raw, label=DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_PATH
    )
    require(
        receipt.get("schema")
        == "trimem/development-protected-exec-gate-failure-receipt/1.0"
        and receipt.get("status")
        == "FAILED_AT_PROTECTED_EXEC_GATE_BEFORE_SCIENTIFIC_EXECUTION"
        and receipt.get("endpoint") == DEVELOPMENT_INCOMPLETE_ENDPOINT
        and receipt.get("failure_label") == DEVELOPMENT_EXEC_002_FAILURE_LABEL
        and receipt.get("performance") == "NOT_MEASURED"
        and receipt.get("scientific_run") is False,
        "DEV _002 protected-gate failure classification differs",
    )
    require(
        receipt.get("execution_accounting") == DEVELOPMENT_EXEC_002_ACCOUNTING,
        "DEV _002 current-attempt accounting differs",
    )

    sentinel = receipt.get("sentinel", {})
    expected_sentinel = {
        "execution_head": DEVELOPMENT_EXEC_002_HEAD,
        "immutable": True,
        "path": DEVELOPMENT_EXEC_002_SENTINEL_PATH,
        "raw_sha256": "sha256:" + DEVELOPMENT_EXEC_002_REQUEST_RAW_SHA256,
        "request_id": DEVELOPMENT_EXEC_002_REQUEST_ID,
        "sole_change": f"A\t{DEVELOPMENT_EXEC_002_SENTINEL_PATH}",
        "source_head": DEVELOPMENT_EXEC_002_SOURCE_HEAD,
    }
    require(sentinel == expected_sentinel, "DEV _002 sentinel identity differs")
    sentinel_raw = (ROOT / DEVELOPMENT_EXEC_002_SENTINEL_PATH).read_bytes()
    require(
        hashlib.sha256(sentinel_raw).hexdigest()
        == DEVELOPMENT_EXEC_002_REQUEST_RAW_SHA256,
        "DEV _002 committed sentinel bytes differ",
    )
    require(
        _historical_git_file(
            DEVELOPMENT_EXEC_002_HEAD, DEVELOPMENT_EXEC_002_SENTINEL_PATH
        )
        == sentinel_raw,
        "DEV _002 historical sentinel blob differs",
    )
    parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", DEVELOPMENT_EXEC_002_HEAD],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    require(
        parents.returncode == 0
        and parents.stdout.strip().split()
        == [DEVELOPMENT_EXEC_002_HEAD, DEVELOPMENT_EXEC_002_SOURCE_HEAD],
        "DEV _002 historical parent identity differs",
    )
    changes = subprocess.run(
        [
            "git",
            "-c",
            "core.quotepath=false",
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            DEVELOPMENT_EXEC_002_HEAD,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    require(
        changes.returncode == 0
        and changes.stdout.splitlines()
        == [f"A\t{DEVELOPMENT_EXEC_002_SENTINEL_PATH}"],
        "DEV _002 historical commit was not sentinel-only",
    )

    workflow = receipt.get("workflow_run", {})
    jobs = receipt.get("jobs", {})
    protected = jobs.get("protected_execution", {})
    require(
        workflow.get("id") == DEVELOPMENT_EXEC_002_RUN_ID
        and workflow.get("run_attempt") == DEVELOPMENT_EXEC_002_RUN_ATTEMPT
        and workflow.get("head_sha") == DEVELOPMENT_EXEC_002_HEAD
        and workflow.get("event") == "push"
        and workflow.get("conclusion") == "failure"
        and workflow.get("status") == "completed"
        and jobs.get("hosted_preflight", {}).get("conclusion") == "success"
        and protected.get("conclusion") == "failure"
        and protected.get("failed_step")
        == {
            "conclusion": "failure",
            "name": "Verify exact phase EXEC gate",
            "number": 10,
        },
        "DEV _002 workflow or protected-gate identity differs",
    )
    require(
        protected.get("skipped_before_scientific_execution")
        == [
            {
                "conclusion": "skipped",
                "name": "Verify required protected runtime secrets before paid work",
                "number": 11,
            },
            {
                "conclusion": "skipped",
                "name": "Apply exact migration head",
                "number": 12,
            },
            {
                "conclusion": "skipped",
                "name": "Pull committed images by digest and verify local observations",
                "number": 13,
            },
            {
                "conclusion": "skipped",
                "name": "Execute frozen serial streams with one atomic phase ledger",
                "number": 14,
            },
            {
                "conclusion": "skipped",
                "name": "Aggregate exact stream and target set fail closed",
                "number": 15,
            },
            {
                "conclusion": "skipped",
                "name": "Build public allowlisted result",
                "number": 16,
            },
        ],
        "DEV _002 pre-scientific skipped-step boundary differs",
    )

    root_cause = receipt.get("root_cause", {})
    require(
        root_cause
        == {
            "blocker": (
                "official grader smoke attestation verification failed: gh CLI "
                "is required for cryptographic smoke attestation verification"
            ),
            "failure_stage": "PROTECTED_EXEC_GATE_BEFORE_RUNTIME_SECRET_CHECK",
            "interpretation": (
                "The protected environment, external approval materialization, "
                "and event/phase checks succeeded. The fail-closed EXEC gate then "
                "required the GitHub CLI for cryptographic official-grader-smoke "
                "attestation verification, but gh was unavailable on the ephemeral "
                "runner. Runtime-secret validation and every scientific step "
                "remained unreached."
            ),
        },
        "DEV _002 protected-gate root cause differs",
    )
    approval = receipt.get("approval", {})
    require(
        approval.get("materialization_status") == "PASS"
        and approval.get("phase_and_event_checks_status") == "PASS"
        and approval.get("approved_git_commit") == DEVELOPMENT_EXEC_002_HEAD
        and approval.get("approved_source_git_commit")
        == DEVELOPMENT_EXEC_002_SOURCE_HEAD
        and approval.get("approved_workflow_run_id")
        == DEVELOPMENT_EXEC_002_RUN_ID
        and approval.get("approved_workflow_run_attempt")
        == DEVELOPMENT_EXEC_002_RUN_ATTEMPT
        and approval.get("approved_request_sha256")
        == "sha256:" + DEVELOPMENT_EXEC_002_REQUEST_RAW_SHA256
        and approval.get("approved_phase") == "DEVELOPMENT_TUNING"
        and approval.get("approved_task_arm_runs") == 72
        and approval.get("approved_grader_containers") == 72
        and approval.get("approved_paid_model_call_cap") == 1_872
        and approval.get("approved_input_token_cap") == 36_000_000
        and approval.get("approved_output_token_cap") == 3_796_992
        and approval.get("approved_currency_hard_cap_usd") == 50.0,
        "DEV _002 consumed approval binding differs",
    )
    control = receipt.get("control_plane", {})
    cleanup = receipt.get("cleanup", {})
    require(
        control.get("protected_environment_worked") is True
        and control.get("protected_environment_approval_reached") is True
        and control.get("public_benchmark_artifact_count") == 0
        and cleanup.get("environment_secret_count_after_cleanup") == 0
        and cleanup.get("repository_runner_count_after_cleanup") == 0,
        "DEV _002 protected-environment or cleanup boundary differs",
    )
    expected_support_services = [
        {
            "container_count": 1,
            "image": (
                "postgres@sha256:"
                "e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412"
            ),
            "image_pull_count": 1,
            "role": "postgres",
        },
        {
            "container_count": 1,
            "image": (
                "qdrant/qdrant@sha256:"
                "241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636"
            ),
            "image_pull_count": 1,
            "role": "qdrant",
        },
    ]
    require(
        receipt.get("support_services") == expected_support_services,
        "DEV _002 support-service accounting differs",
    )
    recovery = receipt.get("recovery_boundary", {})
    require(
        recovery
        == {
            "attempt_two_created": False,
            "future_recovery_authority_received": False,
            "prohibited_without_new_explicit_authority": [
                "attempt_2_or_rerun",
                "DEVELOPMENT_TUNING_EXEC_REQUEST_003",
                "HELDOUT_BENCHMARK",
                "component_ablation",
                "merge",
                "tag",
                "release",
            ],
            "request_002_and_run_33739545314_attempt_1_immutable": True,
            "request_003_created": False,
            "rerun_performed": False,
        },
        "DEV _002 final consumed authority boundary differs",
    )
    secret_scan = receipt.get("evidence", {}).get("full_workflow_logs", {}).get(
        "secret_scan", {}
    )
    require(
        secret_scan
        == {
            "exact_secret_hits": 0,
            "scanned_secret_classes": [
                "OPENAI_API_KEY",
                "TRIMEM_EXEC_APPROVAL_B64",
                "TRIMEM_EVIDENCE_PASSPHRASE",
            ],
            "status": "PASS",
        },
        "DEV _002 workflow-log secret scan differs",
    )
    return {
        "authority": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "fresh_attempt_one_request": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_003",
            "future_recovery_authority_received": True,
            "request_002_final": True,
            "request_003_allowed_after_exact_remote_gates": True,
            "rerun_allowed": False,
        },
        "endpoint": DEVELOPMENT_INCOMPLETE_ENDPOINT,
        "evidence": {
            "failure_receipt_path": DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_PATH,
            "failure_receipt_raw_sha256": (
                DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_RAW_SHA256
            ),
            "failure_report_path": DEVELOPMENT_EXEC_002_FAILURE_REPORT_PATH,
            "failure_report_raw_sha256": DEVELOPMENT_EXEC_002_FAILURE_REPORT_RAW_SHA256,
            "request_path": DEVELOPMENT_EXEC_002_SENTINEL_PATH,
            "request_raw_sha256": DEVELOPMENT_EXEC_002_REQUEST_RAW_SHA256,
        },
        "execution_accounting": dict(DEVELOPMENT_EXEC_002_ACCOUNTING),
        "failure_label": DEVELOPMENT_EXEC_002_FAILURE_LABEL,
        "performance": "NOT_MEASURED",
        "schema": "trimem/development-protected-exec-gate-failure-status/1.0",
        "scientific_run": False,
        "status": "FINAL_CONSUMED_BEFORE_SCIENTIFIC_EXECUTION",
        "support_services": expected_support_services,
        "workflow_run": {
            "conclusion": "failure",
            "head_sha": DEVELOPMENT_EXEC_002_HEAD,
            "id": DEVELOPMENT_EXEC_002_RUN_ID,
            "run_attempt": DEVELOPMENT_EXEC_002_RUN_ATTEMPT,
        },
    }


def _validated_development_exec_003_failure() -> dict[str, Any]:
    receipt_path = ROOT / DEVELOPMENT_EXEC_003_FAILURE_RECEIPT_PATH
    sentinel_path = ROOT / DEVELOPMENT_EXEC_003_SENTINEL_PATH
    receipt_raw = receipt_path.read_bytes()
    sentinel_raw = sentinel_path.read_bytes()
    require(
        hashlib.sha256(receipt_raw).hexdigest()
        == DEVELOPMENT_EXEC_003_FAILURE_RECEIPT_RAW_SHA256
        and hashlib.sha256(sentinel_raw).hexdigest()
        == DEVELOPMENT_EXEC_003_REQUEST_RAW_SHA256,
        "DEV _003 immutable evidence bytes differ",
    )
    receipt = _strict_json_bytes(
        receipt_raw, label=DEVELOPMENT_EXEC_003_FAILURE_RECEIPT_PATH
    )
    workflow = receipt.get("workflow_run", {})
    accounting = receipt.get("execution_accounting", {})
    require(
        workflow.get("id") == DEVELOPMENT_EXEC_003_RUN_ID
        and workflow.get("run_attempt") == DEVELOPMENT_EXEC_003_RUN_ATTEMPT
        and workflow.get("head_sha") == DEVELOPMENT_EXEC_003_HEAD
        and receipt.get("endpoint") == DEVELOPMENT_INCOMPLETE_ENDPOINT
        and accounting.get("api_calls") == 1
        and accounting.get("model_calls") == 1
        and accounting.get("paid_model_calls") == 1
        and accounting.get("completed_task_arm_runs") == 0
        and accounting.get("grader_containers") == 0
        and accounting.get("provider_reported_usage_available_on_failure") is False,
        "DEV _003 historical execution boundary differs",
    )
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", DEVELOPMENT_EXEC_003_HEAD, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(ancestry.returncode == 0, "DEV _003 execution is not immutable branch history")
    amendment = read_json(
        ROOT
        / "artifacts/trimem_v1/development_tuning_exec/exec-003/"
        "provider-observability-terminology-amendment.json"
    )
    require(
        amendment.get("historical_endpoint") == DEVELOPMENT_INCOMPLETE_ENDPOINT
        and amendment.get("refined_subtype") == DEVELOPMENT_EXEC_003_FAILURE_SUBTYPE
        and amendment.get("raw_provider_outcome_class")
        == "UNAVAILABLE_DUE_TO_ADAPTER_OBSERVABILITY_GAP"
        and amendment.get("immutable_historical_receipt", {}).get("sha256")
        == DEVELOPMENT_EXEC_003_FAILURE_RECEIPT_RAW_SHA256
        and amendment.get("immutable_historical_receipt", {}).get(
            "modified_by_this_amendment"
        )
        is False,
        "DEV _003 terminology amendment differs",
    )
    return {
        "schema": "trimem/development-provider-output-contract-failure-status/1.0",
        "endpoint": DEVELOPMENT_INCOMPLETE_ENDPOINT,
        "failure_subtype": DEVELOPMENT_EXEC_003_FAILURE_SUBTYPE,
        "raw_provider_outcome_class": "UNAVAILABLE_DUE_TO_ADAPTER_OBSERVABILITY_GAP",
        "performance": "NOT_MEASURED",
        "dev_scientific_status": "STARTED_NO_COMPLETED_CELL",
        "workflow_run": {
            "id": DEVELOPMENT_EXEC_003_RUN_ID,
            "run_attempt": DEVELOPMENT_EXEC_003_RUN_ATTEMPT,
            "head_sha": DEVELOPMENT_EXEC_003_HEAD,
            "conclusion": "failure",
        },
        "execution_accounting": {
            "api_calls": 1,
            "model_calls": 1,
            "paid_model_calls": 1,
            "completed_task_arm_runs": 0,
            "grader_containers": 0,
            "provider_reported_usage": "UNAVAILABLE_DUE_TO_ADAPTER_OBSERVABILITY_GAP",
        },
        "historical_run_rerun_allowed": False,
        "attempt_two_allowed": False,
        "fresh_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_004",
    }


def _validated_development_exec_004_failure() -> dict[str, Any]:
    receipt_path = ROOT / DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_PATH
    sentinel_path = ROOT / DEVELOPMENT_EXEC_004_SENTINEL_PATH
    receipt_raw = receipt_path.read_bytes()
    sentinel_raw = sentinel_path.read_bytes()
    require(
        hashlib.sha256(receipt_raw).hexdigest()
        == DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_RAW_SHA256
        and hashlib.sha256(sentinel_raw).hexdigest()
        == DEVELOPMENT_EXEC_004_REQUEST_RAW_SHA256,
        "DEV _004 immutable evidence bytes differ",
    )
    receipt = _strict_json_bytes(
        receipt_raw, label=DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_PATH
    )
    workflow = receipt.get("workflow_run", {})
    accounting = receipt.get("execution_accounting", {})
    root_cause = receipt.get("root_cause", {})
    terminal = receipt.get("terminal_boundary", {})
    require(
        workflow.get("id") == DEVELOPMENT_EXEC_004_RUN_ID
        and workflow.get("run_attempt") == DEVELOPMENT_EXEC_004_RUN_ATTEMPT
        and workflow.get("head_sha") == DEVELOPMENT_EXEC_004_HEAD
        and receipt.get("endpoint") == DEVELOPMENT_INCOMPLETE_ENDPOINT
        and receipt.get("scientific_status") == "STARTED_NO_COMPLETED_CELL"
        and receipt.get("performance") == "NOT_MEASURED"
        and receipt.get("failure_label") == DEVELOPMENT_EXEC_004_FAILURE_SUBTYPE
        and root_cause.get("terminal_classification")
        == "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"
        and root_cause.get("incomplete_reason") == "max_output_tokens"
        and accounting.get("api_calls") == 6
        and accounting.get("model_calls") == 6
        and accounting.get("paid_model_calls") == 6
        and accounting.get("decomposition_calls") == 1
        and accounting.get("solve_calls") == 5
        and accounting.get("extraction_calls") == 0
        and accounting.get("input_tokens") == 54620
        and accounting.get("cached_input_tokens") == 17664
        and accounting.get("output_tokens") == 4203
        and accounting.get("reasoning_tokens") == 1485
        and accounting.get("completed_task_arm_runs") == 0
        and accounting.get("grader_containers") == 0
        and accounting.get("official_grader_runs") == 0
        and accounting.get("total_usd") == 0.0479553
        and terminal.get("run_33788493773_rerun_performed") is False
        and terminal.get("run_33840007588_rerun_performed") is False
        and terminal.get("github_actions_attempt_2_created") is False
        and terminal.get("development_request_005_created") is False
        and terminal.get("further_execution_authorized") is False,
        "DEV _004 terminal failure boundary differs",
    )
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", DEVELOPMENT_EXEC_004_HEAD, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(ancestry.returncode == 0, "DEV _004 execution is not immutable branch history")
    return {
        "schema": "trimem/development-provider-terminal-failure-status/1.0",
        "endpoint": DEVELOPMENT_INCOMPLETE_ENDPOINT,
        "failure_subtype": DEVELOPMENT_EXEC_004_FAILURE_SUBTYPE,
        "raw_provider_outcome_class": "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS",
        "performance": "NOT_MEASURED",
        "dev_scientific_status": "STARTED_NO_COMPLETED_CELL",
        "workflow_run": {
            "id": DEVELOPMENT_EXEC_004_RUN_ID,
            "run_attempt": DEVELOPMENT_EXEC_004_RUN_ATTEMPT,
            "head_sha": DEVELOPMENT_EXEC_004_HEAD,
            "conclusion": "failure",
        },
        "execution_accounting": {
            "api_calls": 6,
            "model_calls": 6,
            "paid_model_calls": 6,
            "decomposition_calls": 1,
            "solve_calls": 5,
            "extraction_calls": 0,
            "input_tokens": 54620,
            "cached_input_tokens": 17664,
            "output_tokens": 4203,
            "reasoning_tokens": 1485,
            "completed_task_arm_runs": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
            "total_usd": 0.0479553,
        },
        "provider_status_distribution": {
            "SUCCESS": 5,
            "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS": 1,
        },
        "failure_receipt_path": DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_PATH,
        "failure_receipt_raw_sha256": DEVELOPMENT_EXEC_004_FAILURE_RECEIPT_RAW_SHA256,
        "historical_run_rerun_allowed": False,
        "current_run_rerun_allowed": False,
        "attempt_two_allowed": False,
        "further_execution_authorized": False,
    }


def _validated_development_exec_005_failure() -> dict[str, Any]:
    receipt_path = ROOT / DEVELOPMENT_EXEC_005_FAILURE_RECEIPT_PATH
    sentinel_path = ROOT / DEVELOPMENT_EXEC_005_SENTINEL_PATH
    receipt_raw = receipt_path.read_bytes()
    sentinel_raw = sentinel_path.read_bytes()
    require(
        hashlib.sha256(receipt_raw).hexdigest()
        == DEVELOPMENT_EXEC_005_FAILURE_RECEIPT_RAW_SHA256
        and hashlib.sha256(sentinel_raw).hexdigest()
        == DEVELOPMENT_EXEC_005_REQUEST_RAW_SHA256,
        "DEV _005 immutable terminal evidence bytes differ",
    )
    receipt = _strict_json_bytes(
        receipt_raw, label=DEVELOPMENT_EXEC_005_FAILURE_RECEIPT_PATH
    )
    workflow = receipt.get("workflow_run", {})
    accounting = receipt.get("execution_accounting", {})
    root_cause = receipt.get("root_cause", {})
    process_resume = receipt.get("process_resume", {})
    terminal = receipt.get("terminal_boundary", {})
    evidence = receipt.get("evidence", {})
    artifact = evidence.get("encrypted_restricted_artifact", {})
    restricted_inventory = evidence.get("restricted_inventory", {})
    require(
        workflow.get("id") == DEVELOPMENT_EXEC_005_RUN_ID
        and workflow.get("run_attempt") == DEVELOPMENT_EXEC_005_RUN_ATTEMPT
        and workflow.get("head_sha") == DEVELOPMENT_EXEC_005_HEAD
        and receipt.get("endpoint") == DEVELOPMENT_INCOMPLETE_ENDPOINT
        and receipt.get("scientific_status") == "STARTED_NO_COMPLETED_CELL"
        and receipt.get("performance") == "NOT_MEASURED"
        and receipt.get("failure_label") == DEVELOPMENT_EXEC_005_FAILURE_SUBTYPE
        and root_cause.get("terminal_classification") == "HTTP_AUTH_ERROR"
        and root_cause.get("logical_call_id")
        == "swebench_verified--django__django-16100:M2:decompose:0001"
        and root_cause.get("provider_reported_usage_available") is False
        and accounting.get("api_calls") == 1
        and accounting.get("model_calls") == 1
        and accounting.get("paid_model_calls") == 1
        and accounting.get("decomposition_calls") == 1
        and accounting.get("solve_calls") == 0
        and accounting.get("extraction_calls") == 0
        and accounting.get("input_tokens") is None
        and accounting.get("output_tokens") is None
        and accounting.get("reasoning_tokens") is None
        and accounting.get("provider_reported_usage")
        == "UNAVAILABLE_HTTP_AUTH_ERROR"
        and accounting.get("ledger_conservative_reservation")
        == {"input_tokens": 5069, "output_tokens": 8192,
            "total_usd": 0.04066575,
            "derivation": "(5069 * 0.75 + 8192 * 4.50) / 1000000"}
        and accounting.get("completed_task_arm_runs") == 0
        and accounting.get("grader_containers") == 0
        and accounting.get("official_grader_runs") == 0
        and process_resume.get("bounded_resume_attempts") == 1
        and process_resume.get("additional_provider_calls") == 0
        and process_resume.get("outcome") == "REPLAYED_ORIGINAL_HTTP_AUTH_ERROR"
        and artifact.get("id") == 9_931_958_997
        and artifact.get("archive_digest")
        == "sha256:a7bdb0a02d3725b3d15d43048a03320ec4ecaff4e3deadcc9eb7f74e3476b1c2"
        and artifact.get("ciphertext_raw_sha256")
        == "sha256:2858db3dd128ce136a316d7622ef4039b39cc89d58ccca03f4a6513c7da74c83"
        and restricted_inventory.get("status") == "NOT_RECONSTRUCTED"
        and terminal.get("run_33859839836_rerun_performed") is False
        and terminal.get("github_actions_attempt_2_created") is False
        and terminal.get("development_request_006_created") is False
        and terminal.get("further_execution_authorized") is False,
        "DEV _005 terminal authentication failure boundary differs",
    )
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", DEVELOPMENT_EXEC_005_HEAD, "HEAD"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(ancestry.returncode == 0, "DEV _005 execution is not immutable branch history")
    return {
        "schema": "trimem/development-provider-terminal-failure-status/1.1",
        "endpoint": DEVELOPMENT_INCOMPLETE_ENDPOINT,
        "failure_subtype": DEVELOPMENT_EXEC_005_FAILURE_SUBTYPE,
        "raw_provider_outcome_class": "HTTP_AUTH_ERROR",
        "performance": "NOT_MEASURED",
        "dev_scientific_status": "STARTED_NO_COMPLETED_CELL",
        "workflow_run": {
            "id": DEVELOPMENT_EXEC_005_RUN_ID,
            "run_attempt": DEVELOPMENT_EXEC_005_RUN_ATTEMPT,
            "head_sha": DEVELOPMENT_EXEC_005_HEAD,
            "conclusion": "failure",
        },
        "execution_accounting": {
            "api_calls": 1,
            "model_calls": 1,
            "paid_model_calls": 1,
            "decomposition_calls": 1,
            "solve_calls": 0,
            "extraction_calls": 0,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "provider_reported_usage": "UNAVAILABLE_HTTP_AUTH_ERROR",
            "ledger_conservative_reservation": {
                "input_tokens": 5069,
                "output_tokens": 8192,
                "total_usd": 0.04066575,
            },
            "completed_task_arm_runs": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
        },
        "provider_status_distribution": {"HTTP_AUTH_ERROR": 1},
        "failure_receipt_path": DEVELOPMENT_EXEC_005_FAILURE_RECEIPT_PATH,
        "failure_receipt_raw_sha256": DEVELOPMENT_EXEC_005_FAILURE_RECEIPT_RAW_SHA256,
        "historical_run_rerun_allowed": False,
        "current_run_rerun_allowed": False,
        "attempt_two_allowed": False,
        "further_execution_authorized": False,
    }


def validate_readiness_plan(
    targets: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    plan = read_json(ARTIFACT / "readiness_requirements.json")
    require(plan.get("schema") == "trimem/readiness-requirements/2.0", "readiness requirements are stale")
    derived = _validated_post_smoke_readiness_state()
    historical_development_failure = _validated_development_preflight_failure()
    protected_gate_failure = _validated_development_exec_002_failure()
    historical_provider_failure = _validated_development_exec_003_failure()
    historical_exec_004_failure = _validated_development_exec_004_failure()
    development_failure = _validated_development_exec_005_failure()
    derived["current_status"]["DEV_APPROVAL_ALLOWED"] = "NO"
    derived["current_status"]["DEV_EXECUTION_ALLOWED"] = "NO"
    derived["current_status"]["DEV_SCIENTIFIC_STATUS"] = "STARTED_NO_COMPLETED_CELL"
    derived["current_status"]["ENDPOINT"] = DEVELOPMENT_INCOMPLETE_ENDPOINT
    derived["current_status"]["FAILURE_SUBTYPE"] = (
        DEVELOPMENT_EXEC_005_FAILURE_SUBTYPE
    )
    derived["current_status"]["PERFORMANCE"] = "NOT_MEASURED"
    derived["current_status"]["SCIENTIFIC_RESULT"] = (
        "NO_DEVELOPMENT_SCIENTIFIC_RESULT"
    )
    derived["development_execution_failure"] = development_failure
    derived["historical_development_exec_004_failure"] = (
        historical_exec_004_failure
    )
    derived["historical_development_provider_failure"] = historical_provider_failure
    derived["historical_development_exec_gate_failure"] = protected_gate_failure
    derived["historical_development_preflight_failure"] = (
        historical_development_failure
    )
    service_boundary = str(plan.get("credential_free_service_ci_boundary", ""))
    require(
        "ALLOWED_PRE_EXEC" in service_boundary
        and "digest-pinned PostgreSQL and Qdrant support services" in service_boundary
        and "official grader/benchmark target images" in service_boundary,
        "credential-free support-service/official-target execution boundary is absent",
    )
    m1_boundary = str(plan.get("m1_current_v03_boundary", ""))
    require(
        "CONTRACT_CANDIDATE" in m1_boundary
        and "no direct Qdrant write" in m1_boundary
        and "no immediate fresh-solve carryover" in m1_boundary,
        "M1 current-v0.3 atomic-outbox/no-immediate-carryover boundary is absent",
    )
    require(
        any(
            "per-arm/per-benchmark" in str(item)
            and "pooled totals descriptive only" in str(item)
            for item in plan.get("benchmark_approval_requires", ())
        ),
        "primary/secondary per-benchmark aggregation readiness requirement is absent",
    )
    require(
        any(
            "exact gpt-5.4-mini-2026-03-17 pricing and request schema" in str(item)
            for item in plan.get("benchmark_approval_requires", ())
        ),
        "Mini snapshot and pricing readiness requirement is absent",
    )
    authorization = plan.get("development_authorization_boundary", {})
    require(
        isinstance(authorization, dict)
        and authorization.get("active_development_approval") is False
        and authorization.get("amendment_classification")
        == "NON_SEMANTIC_CREDENTIAL_CONTROL_PLANE_FIX"
        and authorization.get("amendment_evidence_path")
        == "artifacts/trimem_v1/development_credential_control_plane_amendment.json"
        and authorization.get("approval_request_eligible") is False
        and authorization.get("attempt_two_allowed") is False
        and authorization.get("development_execution_authorized") is False
        and authorization.get("expected_total_usd") == 10.8
        and authorization.get("grader_smoke_rerun_authorized") is False
        and authorization.get("hard_cap_total_usd") == 50.0
        and authorization.get("heldout_execution_authorized") is False
        and authorization.get("future_recovery_authority_received") is True
        and authorization.get("model_id") == "gpt-5.4-mini-2026-03-17"
        and authorization.get("prior_failed_run_reusable") is False
        and authorization.get("recovery_authorization")
        == DEVELOPMENT_EXECUTION_AUTHORIZATION
        and authorization.get("recovery_request_id") == DEVELOPMENT_REQUEST_ID
        and authorization.get("recovery_request_path") == DEVELOPMENT_SENTINEL_PATH
        and authorization.get("request_004_allowed_after_exact_remote_gates") is False
        and authorization.get("request_004_attempt_one_consumed") is True
        and authorization.get("request_005_allowed_after_exact_remote_gates") is False
        and authorization.get("request_005_attempt_one_consumed") is True
        and authorization.get("request_006_allowed_after_exact_remote_gates") is True
        and authorization.get("request_006_attempt_one_consumed") is False
        and authorization.get(
            "solve_execution_contract_rehearsal_required_before_request_005"
        )
        is False
        and authorization.get("rerun_allowed") is False,
        "D1.5 development authorization boundary differs",
    )
    counts = plan.get("frozen_counts", {})
    require((counts.get("development_physical_task_arm_runs"), counts.get("heldout_physical_task_arm_runs"), counts.get("total_benchmark_physical_task_arm_runs")) == (72, 81, 153), "readiness physical-run counts drift")
    digests = plan.get("target_set_sha256", {})
    for name, key in (("development", "development"), ("heldout", "heldout"), ("grader-smoke", "grader_smoke")):
        expected = hashlib.sha256(canonical(targets[name])).hexdigest()
        require(digests.get(key) == expected, f"readiness target-set binding drift: {name}")
    require(
        plan.get("current_status") == derived["current_status"],
        "readiness authoritative PASS status differs",
    )
    require(
        plan.get("execution_counter_scope") == derived["execution_counter_scope"]
        and plan.get("execution_counters") == derived["execution_counters"],
        "readiness authoritative exec-005 counters differ",
    )
    require(
        plan.get("grader_smoke_scientific_result") == derived["scientific_result"],
        "readiness scientific result is not evidence-derived",
    )
    require(
        plan.get("grader_smoke_exec_005_success_evidence")
        == derived["success_evidence"],
        "readiness exec-005 success evidence differs",
    )
    require(
        plan.get("grader_smoke_exec_005_failure_closure")
        == derived["failure_closure"],
        "readiness exec-005 failure-closure PASS status differs",
    )
    require(
        plan.get("historical_grader_smoke_execution")
        == _validated_p014_historical_execution(),
        "readiness P0.1.4 immutable diagnostic history differs",
    )
    require(
        plan.get("historical_development_preflight_failure")
        == historical_development_failure,
        "readiness DEV _001 immutable preflight-failure history differs",
    )
    require(
        plan.get("development_execution_failure") == development_failure,
        "readiness DEV _005 terminal authentication failure differs",
    )
    require(
        plan.get("historical_development_exec_004_failure")
        == historical_exec_004_failure,
        "readiness DEV _004 historical provider-output failure differs",
    )
    require(
        plan.get("historical_development_provider_failure")
        == historical_provider_failure,
        "readiness DEV _003 historical provider-output failure differs",
    )
    require(
        plan.get("historical_development_exec_gate_failure")
        == protected_gate_failure,
        "readiness DEV _002 protected-gate history differs",
    )
    static_meaning = str(plan.get("static_ci_meaning", ""))
    require(
        "grader-smoke PASS evidence" in static_meaning
        and "D1.5" in static_meaning
        and "performance remains NOT_MEASURED" in static_meaning,
        "post-smoke static-CI evidence boundary differs",
    )
    remaining = plan.get("post_approval_gates")
    require(
        isinstance(remaining, list)
        and remaining
        and any("_005" in str(item) and "final" in str(item) for item in remaining),
        "post-smoke remaining phase gates differ",
    )
    return derived


def validate_d15_credential_control_amendment() -> None:
    path = ARTIFACT / "development_credential_control_plane_amendment.json"
    amendment = read_json(path)
    implementation = amendment.get("implementation_sha256")
    required_paths = {
        ".github/workflows/trimem-benchmark.yml",
        "scripts/trimem_audit_encrypted_evidence.py",
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_development_trigger_d15.py",
        "scripts/trimem_exec_approval.py",
        "scripts/trimem_openai_model_access_check.py",
        "scripts/trimem_validate_openai_credential.py",
        "scripts/trimem_verify_openai_key_binding.py",
        "src/enterprise_memory/providers/base.py",
        "src/enterprise_memory/providers/openai_credential.py",
        "src/enterprise_memory/providers/openai_responses.py",
    }
    require(
        amendment.get("schema")
        == "trimem/development-credential-control-plane-amendment/1.0"
        and amendment.get("classification")
        == "NON_SEMANTIC_CREDENTIAL_CONTROL_PLANE_FIX"
        and amendment.get("causal_boundary", {}).get(
            "historical_completed_task_arm_runs"
        )
        == 0
        and amendment.get("causal_boundary", {}).get(
            "performance_result_existed_before_amendment"
        )
        is False
        and isinstance(implementation, dict)
        and set(implementation) == required_paths,
        "D1.5 credential-control amendment identity differs",
    )
    for relative, expected in implementation.items():
        require(
            isinstance(expected, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
            and hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            == expected,
            f"D1.5 implementation seal differs: {relative}",
        )
    require(
        amendment.get("preserved")
        == {
            "model_id": "gpt-5.4-mini-2026-03-17",
            "reasoning_effort": "medium",
            "prompts_and_structured_schemas": True,
            "replace_text_and_write_file_policy": True,
            "task_level_output_pools": True,
            "m0_m1_m2_and_four_candidates": True,
            "target_identities_and_order": True,
            "memory_and_dqn_parameters": True,
            "grader_and_image_locks": True,
            "selection_rule": True,
            "development_usd_hard_cap": 50.0,
        },
        "D1.5 frozen scientific-preservation boundary differs",
    )
    custody = amendment.get("evidence_custody_contract", {})
    require(
        custody.get("artifact_zip_digest_verified") is True
        and custody.get("plaintext_persisted_during_audit") is False
        and custody.get("file_path_type_size_sha256_verified") is True
        and custody.get("provider_envelope_verified") is True
        and custody.get("public_and_log_secret_scan_required") is True
        and custody.get("delete_secrets_only_after_external_audit") is True
        and custody.get("failure_endpoint") == "EVIDENCE_CUSTODY_INCOMPLETE",
        "D1.5 evidence-custody boundary differs",
    )


def validate_runtime_and_candidates() -> None:
    validate_d15_credential_control_amendment()
    bundle = load_bundle()
    require(bundle.get("candidate_order") == list(CANDIDATE_IDS), "M2 candidate order drift")
    require(bundle.get("development_contract", {}).get("candidate_task_arm_runs") == 48, "M2 candidate run count drift")
    require(bundle.get("development_contract", {}).get("component_ablation_claim") == "PROHIBITED", "candidate runs may be mislabeled ablations")
    selected = validate_selected_m2(require_frozen=False)
    require(selected.get("status") in {"PRE_DEVELOPMENT", "FROZEN_AFTER_DEVELOPMENT"}, "selected M2 state is invalid")
    arms = read_json(CONFIG / "arms.json")
    require(arms.get("development_streams") == ["M2-baseline", "M2-precision", "M2-recall", "M2-balanced", "M0", "M1"], "development stream contract drift")
    require(arms.get("runtime_ceiling") == RuntimeLock().to_manifest()["limits"], "runtime ceiling differs from source")
    m1_rows = [row for row in arms.get("arms", []) if row.get("arm_id") == "M1"]
    require(len(m1_rows) == 1, "M1 arm contract is missing or duplicated")
    m1 = m1_rows[0]
    baseline_commit = LIVE_V03_IMPLEMENTATION_MANIFEST["source_commit"]
    baseline_path = "src/enterprise_memory/service/durable.py"
    baseline_spec = f"{baseline_commit}:{baseline_path}"
    blob_id = subprocess.run(
        ["git", "rev-parse", baseline_spec],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    blob = subprocess.run(
        ["git", "show", baseline_spec],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    require(blob_id.returncode == 0 and blob.returncode == 0, "M1 baseline durable git object is unavailable")
    try:
        baseline_source = blob.stdout.decode("utf-8")
        module = ast.parse(baseline_source)
        finalizer_node = next(
            node for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "finalize_success_atomic"
        )
    except (UnicodeDecodeError, SyntaxError, StopIteration) as exc:
        raise ReadinessError("M1 baseline finalizer source cannot be verified") from exc
    finalizer_source = "".join(
        baseline_source.splitlines(keepends=True)[
            finalizer_node.lineno - 1: finalizer_node.end_lineno
        ]
    ).encode("utf-8")
    require(
        LIVE_V03_IMPLEMENTATION_MANIFEST.get("baseline_durable_git_blob_sha1")
        == blob_id.stdout.strip()
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("baseline_durable_blob_sha256")
        == hashlib.sha256(blob.stdout).hexdigest()
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get(
            "baseline_finalize_success_atomic_ast_sha256"
        ) == hashlib.sha256(finalizer_source).hexdigest(),
        "M1 baseline durable/finalizer git provenance drift",
    )
    current_finalizer_source = inspect.getsource(
        __import__(
            "enterprise_memory.service.durable", fromlist=["finalize_success_atomic"]
        ).finalize_success_atomic
    )
    require(
        current_finalizer_source.count("persist_private_episode_candidate(") == 1
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("retention_path")
        == "service.durable.persist_private_episode_candidate(connection)"
        and LIVE_V03_IMPLEMENTATION_MANIFEST.get("fresh_solve_immediate_carryover") is False,
        "M1 behavior-preserving shared-helper/no-immediate-carryover lock drift",
    )
    require(
        m1.get("description") == "CURRENT_V03_MEMORY"
        and m1.get("baseline_git_commit") == LIVE_V03_IMPLEMENTATION_MANIFEST["source_commit"]
        and m1.get("live_implementation_hash") == LIVE_V03_IMPLEMENTATION_HASH
        and m1.get("production_lifecycle_configuration_hash")
        == PostgresV03ExperienceLifecycle.configuration_hash,
        "M1 live-v0.3 implementation/configuration lock drift",
    )
    require(
        m1.get("retained_episode_shape")
        == ["task_id", "repo_id", "commit", "outcome", "injected_memory_ids"]
        and m1.get("fresh_solve_episode_private_view")
        == "NOT_INDEXED_BY_CURRENT_SOLVE_PATH"
        and m1.get("fresh_solve_immediate_carryover") is False
        and m1.get("candidate_outbox_event_type") == "CONTRACT_CANDIDATE"
        and "no direct Qdrant indexing" in str(m1.get("retention_path"))
        and m1.get("extractor_output_changes_retention") is False
        and m1.get("benchmark_grade_changes_retention") is False
        and m1.get("shared_publication") is False,
        "M1 solve-worker retention/private-view fidelity contract drift",
    )
    m1_lifecycle_source = inspect.getsource(production_v03_lifecycle_factory)
    m1_controller_source = inspect.getsource(production_v03_controller_factory)
    require(
        "LiveV03Runtime" in m1_lifecycle_source
        and "CurrentV03MemoryController" in m1_controller_source
        and "runtime.recall_plan" in m1_controller_source
        and all(
            callable(getattr(LiveV03Runtime, name, None))
            for name in (
                "retention_descriptor", "retain_episode", "recall_plan",
                "verify_pending_retention",
            )
        )
        and callable(
            getattr(PostgresV03ExperienceLifecycle, "verify_inflight_external_state", None)
        )
        and CurrentV03MemoryController.__name__ == "CurrentV03MemoryController",
        "M1 live validated-search/injection/recovery route is incomplete",
    )

    tool = read_json(CONFIG / "tool_environment_lock.json")
    require(tool.get("status") == "FROZEN", "tool environment lock is not frozen")
    require(tool.get("runtime_lock_manifest") == RuntimeLock().to_manifest() and tool.get("runtime_lock_content_hash") == RuntimeLock().content_hash, "tool/runtime lock drift")
    for relative, expected in tool.get("source_files", {}).items():
        path = ROOT / relative
        require(path.is_file() and len(path.read_bytes()) == expected.get("bytes") and hashlib.sha256(path.read_bytes()).hexdigest() == expected.get("sha256"), f"tool source lock drift: {relative}")
    docker = tool.get("docker_command_runner", {})
    require((docker.get("container_workspace"), docker.get("pull"), docker.get("network"), docker.get("root_filesystem"), docker.get("host_environment_forwarded_to_container")) == ("/testbed", "never", "none", "read-only", False), "production command sandbox lock drift")
    require(tool.get("benchmark_workspace", {}).get("all_tasks_require_digest_bound_command_runner") is True, "production workspace can omit command runner")

    required_methods = ("after_task_and_checkpoint", "resume_canonical_stream", "finalize_development", "run_coroutine")
    require(all(callable(getattr(BenchmarkArmSession, name, None)) for name in required_methods), "production session lifecycle/resume surface is incomplete")
    require(callable(open_benchmark_arm), "production benchmark factory is missing")
    require(
        DockerSandboxCommandRunner.__name__ == "DockerSandboxCommandRunner"
        and getattr(GitCheckoutWorkspaceFactory, "production_capable", None)
        is not True,
        "workspace factory production capability must be instance-bound to complete runners",
    )
    runtime_source = inspect.getsource(TriMemAgentRuntime.run)
    require(all(state in runtime_source for state in ("PATCH_FINALIZED", "GRADED", "EXTRACTED", "LIFECYCLE_STORED", "LIFECYCLE_CREDITED", "DONE")), "terminal checkpoint phase set is incomplete")
    require(all(item is not None for item in (AtomicBudgetLedger, BudgetedModelGateway, JournaledModelGateway, JournaledGraderGateway)), "budget/journal execution boundary is missing")
    benchmark_source = (ROOT / "scripts/trimem_benchmark_run.py").read_text(encoding="utf-8")
    aggregate_source = (ROOT / "scripts/trimem_benchmark_matrix.py").read_text(encoding="utf-8")
    require(callable(seed_benchmark_identities) and "os.environ.pop(\"TRIMEM_ADMIN_DATABASE_URL\"" in benchmark_source and "identity_seed_evidence=" in benchmark_source, "admin-only deterministic benchmark identity seed boundary is missing")
    require(
        '\"benchmark_id\": target[\"benchmark_id\"]' in benchmark_source
        and "_benchmark_endpoint_totals" in aggregate_source
        and "DESCRIPTIVE_POOLED_ALL_BENCHMARKS" in aggregate_source,
        "per-benchmark primary/secondary endpoint aggregation is not frozen",
    )


def validate_smoke_environment_protection(environment: Mapping[str, Any]) -> None:
    """Require the exact protected-environment snapshot for both smoke routes."""

    push_branch = SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT["push"].removeprefix(
        "refs/heads/"
    )
    dispatch_branch = SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT[
        "workflow_dispatch"
    ].removeprefix("refs/heads/")
    expected = {
        "branch_policies": {
            "branch_policies": [
                {"id": 58766765, "name": push_branch, "type": "branch"},
                {"id": 58775497, "name": dispatch_branch, "type": "branch"},
            ],
            "total_count": 2,
        },
        "configured_before_sentinel": True,
        "deployment_branch_policy": {
            "custom_branch_policies": True,
            "protected_branches": False,
        },
        "environment": {
            "can_admins_bypass": False,
            "id": 20971935382,
            "name": "trimem-grader-smoke-exec",
        },
        "observed_at_utc": "2026-09-01T04:18:06Z",
        "protection_rule": {
            "id": 64238011,
            "prevent_self_review": False,
            "reviewers": [{"id": 95427459, "login": "Scuttie", "type": "User"}],
            "type": "required_reviewers",
        },
        "repository": SMOKE_ATTESTATION_REPOSITORY,
        "schema": "trimem/grader-smoke-environment-protection/1.1",
        "secret_state_before_sentinel": {
            "installed_secret_names": [],
            "required_later": [
                "TRIMEM_EVIDENCE_PASSPHRASE",
                "TRIMEM_EXEC_APPROVAL_B64",
            ],
            "total_count": 0,
        },
        "source_api_paths": [
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-grader-smoke-exec"
            ),
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-grader-smoke-exec/deployment-branch-policies"
            ),
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-grader-smoke-exec/secrets"
            ),
        ],
        "status": "CONFIGURED",
    }
    require(
        dict(environment) == expected,
        "grader-smoke protected environment snapshot/route policy set differs",
    )


def validate_benchmark_environment_protection(environment: Mapping[str, Any]) -> None:
    """Require the exact zero-secret DEV/HELDOUT environment created pre-sentinel."""

    expected = {
        "branch_policies": {
            "branch_policies": [
                {
                    "id": 58983771,
                    "name": "codex/trimem-coder-v1",
                    "type": "branch",
                },
                {"id": 58983776, "name": "main", "type": "branch"},
            ],
            "total_count": 2,
        },
        "configured_before_sentinel": True,
        "deployment_branch_policy": {
            "custom_branch_policies": True,
            "protected_branches": False,
        },
        "environment": {
            "can_admins_bypass": False,
            "id": 21138935165,
            "name": "trimem-benchmark-exec",
        },
        "observed_at_utc": "2026-09-03T04:42:36Z",
        "protection_rule": {
            "id": 64484014,
            "prevent_self_review": False,
            "reviewers": [
                {"id": 95427459, "login": "Scuttie", "type": "User"}
            ],
            "type": "required_reviewers",
        },
        "repository": "Scuttie/enterprise-shared-memory-poc",
        "schema": "trimem/benchmark-environment-protection/1.0",
        "secret_state_before_sentinel": {
            "installed_secret_names": [],
            "required_later": [
                "OPENAI_API_KEY",
                "TRIMEM_EVIDENCE_PASSPHRASE",
                "TRIMEM_EXEC_APPROVAL_B64",
            ],
            "total_count": 0,
        },
        "source_api_paths": [
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-benchmark-exec"
            ),
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-benchmark-exec/deployment-branch-policies"
            ),
            (
                "repos/Scuttie/enterprise-shared-memory-poc/environments/"
                "trimem-benchmark-exec/secrets"
            ),
        ],
        "status": "CONFIGURED",
    }
    require(
        dict(environment) == expected,
        "benchmark protected environment snapshot/route policy set differs",
    )


def validate_workflows() -> None:
    automatic = [
        ROOT / ".github/workflows/ci-trimem.yml",
        ROOT / ".github/workflows/ci-trimem-e2e.yml",
        ROOT / ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ]
    portability = ROOT / ".github/workflows/ci-trimem-harness-lock.yml"
    smoke_workflow = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    benchmark_workflow = ROOT / ".github/workflows/trimem-benchmark.yml"
    manual = [smoke_workflow, benchmark_workflow]
    for path in [*automatic, portability, *manual]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ("continue-on-error", "|| true", ":latest"):
            require(forbidden not in text, f"forbidden workflow construct {forbidden}: {path.name}")
        require("inputs:" not in text, f"workflow has free-form inputs: {path.name}")
        for match in re.finditer(r"uses:\s*([^\s]+)", text):
            require(re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", match.group(1)) is not None, f"workflow action is not commit-pinned: {path.name}")
    for path in automatic:
        text = path.read_text(encoding="utf-8")
        require("pull_request:" in text and "trimem_pytest_no_skip.py" in text, f"automatic no-skip PR CI missing: {path.name}")
    static = automatic[0].read_text(encoding="utf-8")
    require("tests/unit/test_trimem_*.py" in static and "tests/trimem/e2e/test_full_replay.py" in static, "static CI does not discover all TriMem units/full replay")
    stdlib_freeze_rehearsal = (
        "python -I -S scripts/trimem_freeze.py --check --require-git-tracked"
    )
    stdlib_preflight_rehearsal = (
        "python -I -S scripts/trimem_development_trigger_d15.py --help"
    )
    require(
        static.count(stdlib_freeze_rehearsal) == 1
        and static.count(stdlib_preflight_rehearsal) == 1
        and static.index(stdlib_freeze_rehearsal)
        < static.index("python -m pip install --require-hashes")
        and static.index(stdlib_preflight_rehearsal)
        < static.index("python -m pip install --require-hashes"),
        "static CI lacks the dependency-free DEV preflight import rehearsal",
    )
    service = automatic[1].read_text(encoding="utf-8")
    require("test_real_services_e2e.py" in service and "postgres@sha256:" in service and "qdrant/qdrant@sha256:" in service, "real PostgreSQL/Qdrant CI is absent")
    require("postgres_bootstrap.py" in service and "TRIMEM_TEST_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in service and "TRIMEM_TEST_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in service, "real-service role/RLS boundary is not wired")
    multi_swe_contract = automatic[2].read_text(encoding="utf-8")
    multi_swe_probe_gate = (
        ROOT / "scripts/trimem_multi_swe_probe_request.py"
    ).read_text(encoding="utf-8")
    require(
        "scripts/trimem_multi_swe_contract.py" in multi_swe_contract
        and "tests/unit/test_trimem_multi_*.py" in multi_swe_contract
        and "24f493f8a103e72312ded4f6b9c89f081d69cb09" in multi_swe_contract,
        "Multi-SWE pinned-contract live verifier/production-config rehearsal is absent",
    )
    require(
        "environment:" not in multi_swe_contract
        and "secrets." not in multi_swe_contract
        and "trimem_grader_smoke.py" not in multi_swe_contract,
        "Multi-SWE preexec/probe workflow is not credential-free and non-scientific",
    )
    require(
        "workflow_dispatch:" not in multi_swe_contract
        and "github.event_name == 'push'" in multi_swe_contract
        and "github.ref == 'refs/heads/codex/trimem-coder-v1'"
        in multi_swe_contract
        and "github.event.head_commit.added" not in multi_swe_contract
        and "contains(github.event" not in multi_swe_contract
        and "scripts/trimem_multi_swe_probe_request.py" in multi_swe_contract
        and '--event-path "$GITHUB_EVENT_PATH"' in multi_swe_contract
        and "scripts/trimem_multi_swe_image_probe.py" in multi_swe_contract
        and "always() && steps.image_probe.outcome != 'skipped'"
        in multi_swe_contract
        and 'test "$IMAGE_PROBE_OUTCOME" = "success"' in multi_swe_contract
        and "persist-credentials: false" in multi_swe_contract,
        "exact Vue image probe lacks the one-time marker-only branch-push contract",
    )
    require(
        'environment.get("GITHUB_RUN_ATTEMPT") == "1"' in multi_swe_probe_gate
        and "artifacts/trimem_v1/probe_requests/" in multi_swe_probe_gate
        and "MULTI_SWE_VUE_IMAGE_PROBE_REQUEST_001.json" in multi_swe_probe_gate,
        "checked-out Git probe gate lacks the exact marker/rerun contract",
    )
    portable = portability.read_text(encoding="utf-8")
    require(
        "pull_request:" in portable
        and "runner: ubuntu-24.04" in portable
        and "runner: windows-2025" in portable
        and "core_autocrlf: input" in portable
        and 'core_autocrlf: "true"' in portable
        and "python_version: 3.11.10" in portable
        and "python_version: 3.11.9" in portable
        and "rehearsal_arg: --blob-only" in portable
        and "trimem_harness_lock.py" in portable
        and "environment:" not in portable
        and "secrets." not in portable,
        "cross-platform credential-free harness-lock rehearsal differs",
    )
    smoke = smoke_workflow.read_text(encoding="utf-8")
    require("workflow_dispatch:" in smoke and "pull_request:" not in smoke and "schedule:" not in smoke, "smoke workflow has an unauthorized trigger")
    require(
        "push:" in smoke
        and "      - codex/trimem-coder-v1" in smoke
        and f"      - {GRADER_SMOKE_SENTINEL_PATH}" in smoke
        and all(f"      - {path}" not in smoke for path, _ in HISTORICAL_SENTINELS),
        "smoke workflow exact branch-local sentinel trigger is absent",
    )
    require(
        "branch-trigger-preflight:" in smoke
        and "needs: branch-trigger-preflight" in smoke
        and "trimem_grader_smoke_trigger_preflight.py" in smoke,
        "smoke branch trigger is not fail-closed before the protected job",
    )
    require(
        "concurrency:\n  group: trimem-v1-grader-smoke-exec-005\n"
        "  cancel-in-progress: false" in smoke,
        "smoke recovery concurrency contract differs",
    )
    require(
        "environment: trimem-grader-smoke-exec" in smoke,
        "smoke job is not held by the protected environment",
    )
    require(
        "github.ref == 'refs/heads/main'" in smoke
        and smoke.count(SMOKE_ATTESTATION_ACTION) == 1
        and "permissions:\n      attestations: write\n      contents: read\n      id-token: write"
        in smoke
        and "create-storage-record: false" in smoke
        and "push-to-registry: false" in smoke
        and "subject-path: ${{ runner.temp }}/attestation-subject.json"
        in smoke
        and "trimem_smoke_attestation.py" in smoke
        and "trimem-grader-smoke-attestation-bundle.json" in smoke
        and "name: trimem-grader-smoke-exec-005-attestation-bundle" in smoke
        and "name: trimem-grader-smoke-exec-005-public" in smoke
        and "name: trimem-grader-smoke-exec-005-failure-closure" in smoke
        and "name: trimem-grader-smoke-exec-005-evidence-inventory" in smoke
        and "name: trimem-grader-smoke-exec-005-restricted-encrypted" in smoke
        and "trimem_grader_smoke_failure_closure.py" in smoke
        and "--request artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_005.json"
        in smoke
        and "$RUNNER_TEMP/trimem-grader-smoke-exec-005-failure-receipt.json"
        in smoke,
        "smoke GitHub-hosted attestation action/permissions/artifact path differs",
    )
    smoke_step_labels = (
        "Remove only frozen smoke image references",
        "Recover or revoke terminal authority after any campaign failure",
        "Inventory every restricted evidence file",
        "Build namespaced exec-005 campaign failure closure",
        "Encrypt complete restricted evidence",
        "Build deterministic official smoke attestation subject",
        "Upload namespaced exec-005 failure closure",
        "Upload non-sensitive restricted evidence inventory",
        "Upload encrypted restricted evidence",
        "Remove plaintext and temporary EXEC material before signing",
        "Attest exact uploaded and cleaned official smoke subject",
        "Materialize fixed attestation bundle name",
        "Upload public smoke result",
        "Upload official smoke attestation bundle",
        "Remove staged attestation material",
    )
    smoke_step_positions: dict[str, int] = {}
    for label in smoke_step_labels:
        marker = f"- name: {label}"
        require(
            smoke.count(marker) == 1,
            f"smoke workflow requires exactly one {label!r} step",
        )
        smoke_step_positions[label] = smoke.index(marker)

    image_cleanup = smoke_step_positions[smoke_step_labels[0]]
    revoke_authority = smoke_step_positions[smoke_step_labels[1]]
    evidence_inventory = smoke_step_positions[smoke_step_labels[2]]
    build_failure = smoke_step_positions[smoke_step_labels[3]]
    encrypt_evidence = smoke_step_positions[smoke_step_labels[4]]
    build_attestation_subject = smoke_step_positions[smoke_step_labels[5]]
    upload_failure = smoke_step_positions[smoke_step_labels[6]]
    upload_inventory = smoke_step_positions[smoke_step_labels[7]]
    upload_encrypted = smoke_step_positions[smoke_step_labels[8]]
    cleanup_before_signing = smoke_step_positions[smoke_step_labels[9]]
    attest = smoke_step_positions[smoke_step_labels[10]]
    materialize_bundle = smoke_step_positions[smoke_step_labels[11]]
    upload_public = smoke_step_positions[smoke_step_labels[12]]
    upload_bundle = smoke_step_positions[smoke_step_labels[13]]
    cleanup_staged_attestation = smoke_step_positions[smoke_step_labels[14]]
    require(
        image_cleanup
        < revoke_authority
        < evidence_inventory
        < build_failure
        < encrypt_evidence
        < build_attestation_subject
        < upload_failure
        < upload_inventory
        < upload_encrypted
        < cleanup_before_signing
        < attest
        < materialize_bundle
        < upload_public
        < upload_bundle
        < cleanup_staged_attestation,
        "smoke cleanup/rollback/inventory/encryption/upload/signing order differs",
    )
    authority_resolution_block = smoke[revoke_authority:evidence_inventory]
    require(
        "steps.exec_gate.outcome == 'success'" in authority_resolution_block
        and "steps.run_smoke.outcome != 'skipped'" in authority_resolution_block
        and "steps.run_smoke.outcome != 'success'" in authority_resolution_block
        and "steps.aggregate.outcome != 'success'" in authority_resolution_block
        and "steps.public_result.outcome != 'success'" in authority_resolution_block
        and "steps.workflow_image_cleanup.outcome != 'success'"
        in authority_resolution_block
        and "--recover-interrupted" in authority_resolution_block
        and 'cause_stage="authority_finalization"' in authority_resolution_block
        and 'failure_taxonomy="infrastructure_failures"'
        in authority_resolution_block,
        "smoke authority recovery is not total over run/downstream failure",
    )
    inventory_block = smoke[evidence_inventory:build_failure]
    require(
        "if: >-" in inventory_block
        and "always() &&" in inventory_block
        and "steps.approval_materialization.outcome != 'skipped'"
        in inventory_block
        and "campaign_authority_rollback" not in inventory_block,
        "restricted inventory is not independent of authority recovery",
    )
    failure_closure_block = smoke[build_failure:encrypt_evidence]
    require(
        "steps.evidence_inventory.outcome == 'success'"
        in failure_closure_block
        and "steps.campaign_authority_rollback.outcome == 'success'"
        in failure_closure_block
        and "steps.campaign_authority_rollback.outcome == 'skipped'"
        in failure_closure_block,
        "failure closure is not gated on stable authority and inventory evidence",
    )
    encryption_block = smoke[encrypt_evidence:build_attestation_subject]
    require(
        "always() &&" in encryption_block
        and "steps.approval_materialization.outcome != 'skipped'"
        in encryption_block
        and 'inventory_args=()' in encryption_block
        and '"${inventory_args[@]}"' in encryption_block,
        "restricted encryption is not independent of optional inventory evidence",
    )
    failure_upload_block = smoke[upload_failure:upload_inventory]
    inventory_upload_block = smoke[upload_inventory:upload_encrypted]
    encrypted_upload_block = smoke[upload_encrypted:cleanup_before_signing]
    public_upload_block = smoke[upload_public:upload_bundle]
    bundle_upload_block = smoke[upload_bundle:cleanup_staged_attestation]
    cleanup_block = smoke[cleanup_before_signing:attest]
    require(
        "if: always() && steps.failure_closure.outcome == 'success'"
        in failure_upload_block
        and "if: always() && steps.evidence_inventory.outcome == 'success'"
        in inventory_upload_block
        and "if: always() && steps.encrypt_evidence.outcome == 'success'"
        in encrypted_upload_block
        and "if: success()" in public_upload_block
        and "if: success()" in bundle_upload_block
        and "RESTRICTED_UPLOAD_OUTCOME: ${{ steps.restricted_upload.outcome }}"
        in cleanup_block
        and 'if [ "$RESTRICTED_UPLOAD_OUTCOME" != "success" ]; then'
        in cleanup_block
        and "preserving plaintext and ciphertext" in cleanup_block
        and "if: always()" not in smoke[attest:cleanup_staged_attestation]
        and ">(tee" not in smoke
        and "workflow-stages/run-smoke/stdout.txt" in smoke
        and "workflow-stages/run-smoke/stderr.txt" in smoke
        and "workflow-stages/authority-rollback/stdout.txt" in smoke
        and "workflow-stages/authority-rollback/stderr.txt" in smoke,
        "smoke uploads/signing are not outcome-gated after evidence preservation",
    )
    restricted_root = "artifacts/trimem_v1/grader_smoke_exec"
    immutable_phase = smoke[build_failure:cleanup_before_signing]
    immutable_root_lines = [
        line.strip()
        for line in immutable_phase.splitlines()
        if restricted_root in line
    ]
    expected_read_only_root_lines = [
        f"--restricted-root {restricted_root} \\",
        f"-C {restricted_root} . \\",
        f"--public-result {restricted_root}/public-results.json \\",
        (
            'python -c "import os,pathlib,shutil; '
            f"source=pathlib.Path('{restricted_root}/public-results.json'); "
            "target=pathlib.Path(os.environ['RUNNER_TEMP'],"
            "'trimem-grader-smoke-public-results.json'); "
            "assert source.is_file() and not target.exists(); "
            "shutil.copyfile(source,target); "
            'assert source.read_bytes() == target.read_bytes()"'
        ),
    ]
    require(
        immutable_root_lines == expected_read_only_root_lines,
        "restricted evidence root is not immutable between inventory and deletion",
    )
    require(
        smoke.count("python scripts/trimem_evidence_inventory.py") == 1
        and smoke.count("openssl enc -aes-256-cbc") == 1
        and smoke.count("python scripts/trimem_grader_smoke_authority.py") == 1
        and smoke.count("python scripts/trimem_grader_smoke_failure_closure.py") == 1
        and smoke.count("python scripts/trimem_cleanup_exec.py --phase grader-smoke") == 1
        and smoke.count("id: evidence_inventory") == 1
        and smoke.count("id: failure_closure") == 1
        and smoke.count("id: encrypt_evidence") == 1
        and smoke.count("id: smoke-attestation") == 1
        and "delivery_authority_rollback" not in smoke
        and "--pre-cell-failure-output "
        "artifacts/trimem_v1/grader_smoke_exec/results" in smoke
        and "workflow-stages/exec-gate/stdout.txt" in smoke
        and "workflow-stages/exec-gate/stderr.txt" in smoke,
        "smoke single-inventory/rollback and EXEC-gate evidence contract differs",
    )
    smoke_secrets = set(
        re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", smoke)
    )
    require(
        smoke_secrets
        == {"TRIMEM_EXEC_APPROVAL_B64", "TRIMEM_EVIDENCE_PASSPHRASE"},
        "smoke workflow secret surface is not the exact control/evidence pair",
    )
    benchmark_text = benchmark_workflow.read_text(encoding="utf-8")
    require(
        "workflow_dispatch:" in benchmark_text
        and "pull_request:" not in benchmark_text
        and "schedule:" not in benchmark_text
        and "push:" in benchmark_text
        and "      - codex/trimem-coder-v1" in benchmark_text
        and f"      - {DEVELOPMENT_SENTINEL_PATH}" in benchmark_text
        and "group: trimem-v1-development-tuning-exec-006" in benchmark_text
        and "group: trimem-v1-development-tuning-exec-004" not in benchmark_text
        and "group: trimem-v1-development-tuning-exec-003" not in benchmark_text
        and "group: trimem-v1-development-tuning-exec-002" not in benchmark_text
        and "group: trimem-v1-development-tuning-exec-001" not in benchmark_text
        and "cancel-in-progress: false" in benchmark_text
        and "branch-trigger-preflight:" in benchmark_text
        and "needs: branch-trigger-preflight" in benchmark_text
        and "trimem_development_trigger_d15.py" in benchmark_text
        and "github.ref == 'refs/heads/main'" in benchmark_text
        and "github.ref == 'refs/heads/codex/trimem-coder-v1'" in benchmark_text,
        "benchmark EXEC workflow lacks the exact DEV sentinel/manual-main trigger boundary",
    )
    benchmark_preflight = benchmark_text.split(
        "  branch-trigger-preflight:", 1
    )[1].split("  frozen-serial-phase:", 1)[0]
    require(
        "runs-on: ubuntu-24.04" in benchmark_preflight
        and "fetch-depth: 0" in benchmark_preflight
        and "persist-credentials: false" in benchmark_preflight
        and "python -I -S scripts/trimem_freeze.py --check --require-git-tracked"
        in benchmark_preflight
        and "python -I -S scripts/trimem_development_trigger_d15.py"
        in benchmark_preflight
        and "GH_TOKEN: ${{ github.token }}" in benchmark_preflight
        and "secrets." not in benchmark_preflight
        and "environment:" not in benchmark_preflight
        and "services:" not in benchmark_preflight
        and "container:" not in benchmark_preflight
        and "trimem_benchmark_run.py" not in benchmark_preflight
        and "trimem_official_grader" not in benchmark_preflight
        and "trimem_pull_locked_images.py" not in benchmark_preflight
        and "docker " not in benchmark_preflight.lower(),
        "DEV branch preflight is not credential-free and non-protected",
    )
    benchmark_protected = benchmark_text.split("  frozen-serial-phase:", 1)[1]
    public_upload = benchmark_protected.split(
        "      - name: Upload public benchmark result", 1
    )[1].split("      - name: Inventory complete restricted benchmark evidence", 1)[0]
    benchmark_secrets = set(
        re.findall(r"\bsecrets\.([A-Za-z_][A-Za-z0-9_]*)", benchmark_protected)
    )
    require(
        "environment: trimem-benchmark-exec" in benchmark_protected
        and "needs: branch-trigger-preflight" in benchmark_text
        and "needs.branch-trigger-preflight.result == 'success'" in benchmark_text
        and "github.run_attempt == 1" in benchmark_protected
        and "persist-credentials: false" in benchmark_protected
        and "ref: ${{ github.sha }}" in benchmark_protected
        and "event == 'push' and split == 'development'" in benchmark_protected
        and "event == 'workflow_dispatch' and split == 'heldout'"
        in benchmark_protected
        and 'test -n "$OPENAI_API_KEY"' in benchmark_protected
        and 'test -n "$TRIMEM_EVIDENCE_PASSPHRASE"' in benchmark_protected,
        "protected benchmark job lacks exact event/attempt/checkout routing",
    )
    require(
        benchmark_secrets
        == {
            "OPENAI_API_KEY",
            "TRIMEM_EVIDENCE_PASSPHRASE",
            "TRIMEM_EXEC_APPROVAL_B64",
        },
        "benchmark workflow secret surface differs from the approved three values",
    )
    require(
        "artifacts/trimem_v1/benchmark_exec/*/public-results.json" in public_upload
        and "development_selection/" not in public_upload
        and "benchmark_exec/control/restricted-external-approval.json"
        in benchmark_protected
        and "cmp --silent" in benchmark_protected
        and "umask 077" in benchmark_protected
        and "trap cleanup_partial_approval EXIT" in benchmark_protected
        and 'rm -f -- "$approval_tmp" "$restricted_approval"'
        in benchmark_protected
        and "trap - EXIT" in benchmark_protected
        and "steps.approval_materialization.outcome == 'success'"
        in benchmark_protected
        and "evidence_paths=(benchmark_exec)" in benchmark_protected
        and "evidence_paths+=(development_selection)" in benchmark_protected
        and "python scripts/trimem_evidence_inventory.py" in benchmark_protected
        and "--root-label benchmark_exec" in benchmark_protected
        and "--root-label development_selection" in benchmark_protected
        and "steps.benchmark_evidence_inventory.outcome == 'success'"
        in benchmark_protected
        and "steps.encrypt_evidence.outcome == 'success'" in benchmark_protected
        and "Upload non-sensitive benchmark evidence inventories"
        in benchmark_protected
        and "trimem-benchmark-evidence-inventories" in benchmark_protected
        and "Remove plaintext external approval after encryption attempt"
        in benchmark_protected
        and benchmark_protected.count(
            "artifacts/trimem_v1/benchmark_exec/control/restricted-external-approval.json"
        ) >= 3
        and 'test ! -e "$RUNNER_TEMP/trimem-exec-approval.json"'
        in benchmark_protected
        and "RESTRICTED_UPLOAD_OUTCOME" in benchmark_protected
        and "INVENTORY_UPLOAD_OUTCOME" in benchmark_protected
        and '[ "$RESTRICTED_UPLOAD_OUTCOME" != "success" ] || [ "$INVENTORY_UPLOAD_OUTCOME" != "success" ]'
        in benchmark_protected
        and "preserving plaintext and ciphertext" in benchmark_protected
        and "test ! -e artifacts/trimem_v1/benchmark_exec" in benchmark_protected
        and "test ! -e artifacts/trimem_v1/development_selection"
        in benchmark_protected,
        "benchmark public/restricted evidence and fail-closed cleanup contract differs",
    )
    gate_start = benchmark_text.find("- name: Verify exact phase EXEC gate")
    credential_format = benchmark_text.find(
        "- name: Validate exact OpenAI credential format before network access"
    )
    credential_binding = benchmark_text.find(
        "- name: Verify run-bound OpenAI credential commitment"
    )
    model_access = benchmark_text.find(
        "- name: Retrieve exact model metadata before image materialization"
    )
    evidence_secret = benchmark_text.find(
        "- name: Verify evidence passphrase before scientific work"
    )
    migration = benchmark_text.find("- name: Apply exact migration head")
    image_pull = benchmark_text.find(
        "- name: Pull committed images by digest and verify local observations"
    )
    require(
        "permissions:\n  actions: read\n  contents: read" in benchmark_text
        and benchmark_text.count("GH_TOKEN: ${{ github.token }}") == 2
        and 0 <= gate_start < credential_format < credential_binding
        < model_access < evidence_secret < migration < image_pull
        and "python scripts/trimem_validate_openai_credential.py"
        in benchmark_text[credential_format:credential_binding]
        and "python scripts/trimem_verify_openai_key_binding.py"
        in benchmark_text[credential_binding:model_access]
        and "python scripts/trimem_openai_model_access_check.py"
        in benchmark_text[model_access:evidence_secret]
        and "--approval-file \"$RUNNER_TEMP/trimem-exec-approval.json\""
        in benchmark_text[credential_binding:evidence_secret]
        and 'test -n "$TRIMEM_EVIDENCE_PASSPHRASE"'
        in benchmark_text[evidence_secret:migration]
        and "GH_TOKEN: ${{ github.token }}"
        in benchmark_text[gate_start:credential_format],
        "benchmark credential/model-access ordering or least-privilege scope differs",
    )
    for path in manual:
        text = path.read_text(encoding="utf-8")
        require("trimem_public_artifact.py" in text and "openssl enc -aes-256-cbc" in text, f"EXEC evidence protection path incomplete: {path.name}")
        require("if: always()" in text and "trimem_cleanup_exec.py" in text, f"EXEC plaintext cleanup path is absent: {path.name}")
    require(
        "bounded-disk exact GOLD and NOOP_BASELINE pairs" in smoke
        and smoke.count(
            "--image-evidence-dir artifacts/trimem_v1/grader_smoke_exec/image-materialization"
        ) == 2
        and "--cleanup-grader-smoke" in smoke
        and "Remove only frozen smoke image references" in smoke,
        "smoke workflow does not use bounded-disk serial image materialization",
    )
    benchmark = manual[1].read_text(encoding="utf-8")
    require("trimem_pull_locked_images.py" in benchmark, "benchmark digest-only image pull is absent")
    require("runs-on: [self-hosted, linux, x64, ubuntu-24.04, trimem-benchmark]" in benchmark and "timeout-minutes: 7200" in benchmark, "long serial benchmark is not on protected 5-day runner")
    require("matrix:" not in benchmark, "online benchmark is incorrectly task/arm sharded")
    require("trimem_run_with_resume.py" in benchmark and "trimem_benchmark_run.py\n" not in benchmark, "same-attempt benchmark recovery wrapper is not the workflow entrypoint")
    require("postgres_bootstrap.py" in benchmark and "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in benchmark and "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in benchmark, "benchmark admin/runtime RLS identities are not separated")
    environment = read_json(
        ARTIFACT / "grader_smoke_environment_protection.json"
    )
    validate_smoke_environment_protection(environment)
    benchmark_environment = read_json(
        ARTIFACT / "benchmark_environment_protection.json"
    )
    validate_benchmark_environment_protection(benchmark_environment)


def validate_eol_policy() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    require(
        "scripts/trimem_*.py text eol=lf" in attributes
        and "configs/trimem_v1/** text eol=lf" in attributes
        and "/COMPANY_HANDOFF_MANIFEST.json text eol=lf" in attributes,
        "cross-platform LF freeze/product-manifest policy is absent",
    )
    representative = (
        ".gitattributes", ".gitignore", "alembic.ini", "DEPENDENCY_PROVENANCE.json",
        "COMPANY_HANDOFF_MANIFEST.json", "requirements.lock",
        "pyproject.toml", "configs/trimem_v1/model_lock.json", "scripts/trimem_freeze.py",
        "scripts/check_migration_head.py", "docs/TRIMEM_V1_SYSTEM.md",
        "reports/TRIMEM_GRADER_SMOKE_EXEC_004_FAILURE.md",
        ".github/workflows/ci-trimem.yml", "migrations/env.py",
        "migrations/sql/0001_up.sql", "migrations/versions/0001_initial_production_schema.py",
        "src/enterprise_memory/providers/openai_responses.py",
        "src/enterprise_memory/providers/base.py",
        "src/enterprise_memory/providers/redaction.py",
        "src/enterprise_memory/indexing/embeddings.py",
        "src/enterprise_memory/indexing/validated_search.py",
        "src/enterprise_memory/service/injection.py",
        "src/enterprise_memory/service/app.py", "src/enterprise_memory/trimem/agent_runtime.py",
        "tests/openai/test_openai_provider.py", "tests/unit/test_release_hygiene.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
    )
    completed = subprocess.run(
        ["git", "check-attr", "eol", "--", *representative],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    require(completed.returncode == 0 and completed.stdout.count("eol: lf") == len(representative), "git LF attributes do not cover frozen text")
    blobs = sorted((ARTIFACT / "credential_free_e2e").glob("*/evidence/blobs/*"))
    require(bool(blobs), "credential-free content-addressed evidence blobs are missing")
    blob_relative = blobs[0].relative_to(ROOT).as_posix()
    blob_attr = subprocess.run(
        ["git", "check-attr", "text", "--", blob_relative], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    require(blob_attr.returncode == 0 and "text: unset" in blob_attr.stdout, "content-addressed evidence blobs are not binary-stable")


def validate_static(require_git_tracked: bool) -> dict[str, Any]:
    check_freeze(ROOT, require_git_tracked=require_git_tracked)
    validate_smoke_attestation_policy()
    validate_eol_policy()
    validate_sources()
    targets = validate_targets()
    readiness_state = validate_readiness_plan(targets)
    validate_images(targets)
    validate_noop_baseline_audit(targets)
    validate_model_cost_environment()
    contracts = validate_p015_semantics_and_envelope_contracts()
    validate_runtime_and_candidates()
    validate_workflows()
    credential = verify_bundle(ARTIFACT / "credential_free_e2e")
    request = read_json(CONFIG / "benchmark_exec_request.json")
    require(request.get("approval_state") == "PENDING_EXEC_APPROVAL", "committed request must stay pending")
    request_actual = request.get("actual_execution")
    require(
        isinstance(request_actual, dict)
        and all(type(value) is int for value in request_actual.values())
        and request_actual == {
            "benchmark_target_image_pulls": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "task_arm_runs": 0,
        },
        "committed preapproval execution counter schema/value differs",
    )
    prohibited = request.get("prohibited_before_approval", [])
    require(
        "official grader/benchmark target image pull or run" in prohibited
        and "Docker image pull or run" not in prohibited,
        "pre-EXEC prohibition incorrectly blocks credential-free support-service CI",
    )
    required = set(request.get("required_approval_fields", ()))
    require({"approved_workflow_run_id", "approved_workflow_run_attempt"} <= required, "single-dispatch EXEC approval binding is absent")
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    smoke_actual = validate_grader_smoke_result(smoke)
    development_failure = readiness_state["development_execution_failure"]
    development_accounting = development_failure["execution_accounting"]
    require(
        development_accounting
        == {
            "api_calls": 1,
            "model_calls": 1,
            "paid_model_calls": 1,
            "decomposition_calls": 1,
            "solve_calls": 0,
            "extraction_calls": 0,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "provider_reported_usage": "UNAVAILABLE_HTTP_AUTH_ERROR",
            "ledger_conservative_reservation": {
                "input_tokens": 5069,
                "output_tokens": 8192,
                "total_usd": 0.04066575,
            },
            "completed_task_arm_runs": 0,
            "grader_containers": 0,
            "official_grader_runs": 0,
        },
        "DEV _005 current execution accounting differs at readiness output",
    )
    smoke_counters = readiness_state["execution_counters"]
    require(
        all(smoke_counters.get(key) == value for key, value in smoke_actual.items()),
        "historical grader-smoke counters differ at readiness output",
    )
    return {
        "credential_free_bundle_hash": credential["bundle_hash"],
        "development_task_arm_runs_planned": 72,
        "heldout_task_arm_runs_planned": 81,
        "support_image_digests_frozen": 1,
        "target_image_digests_frozen": 45,
        "execution_counter_scope": "DEVELOPMENT_TUNING_EXEC_005_RUN_33859839836_ATTEMPT_1",
        "task_arm_runs": development_accounting["completed_task_arm_runs"],
        "model_calls": development_accounting["model_calls"],
        "official_grader_runs": 0,
        "paid_model_calls": development_accounting["paid_model_calls"],
        "development_execution_accounting": development_accounting,
        "grader_smoke_history": {
            "execution_counter_scope": readiness_state["execution_counter_scope"],
            "execution_counters": smoke_counters,
            "scientific_result": readiness_state["scientific_result"],
        },
        "grader_exec_package": smoke["grader_exec_package"],
        "endpoint": readiness_state["current_status"]["ENDPOINT"],
        "dev_approval_allowed": (
            readiness_state["current_status"]["DEV_APPROVAL_ALLOWED"] == "YES"
        ),
        "dev_execution_allowed": False,
        "scientific_result": readiness_state["current_status"][
            "SCIENTIFIC_RESULT"
        ],
        "official_grader_viability": smoke["official_grader_viability"],
        "performance": smoke["performance"],
        "multi_swe_report_semantics_sha256": contracts["module_sha256"],
        "multi_swe_report_semantics_lock_sha256": contracts["lock_sha256"],
        "adapter_failure_envelope_contract_sha256": contracts[
            "adapter_failure_envelope_contract_sha256"
        ],
    }


def preapproval_blockers() -> list[str]:
    _validated_development_exec_002_failure()
    _validated_development_exec_003_failure()
    _validated_development_exec_004_failure()
    _validated_development_exec_005_failure()
    sentinel = ROOT / DEVELOPMENT_SENTINEL_PATH
    if not sentinel.is_file():
        return [
            "DEV _006 sentinel and exact-head remote gates are required before approval"
        ]
    try:
        validate_development_sentinel_commit(ROOT, git_head())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return [f"DEV _006 sentinel validation failed: {exc}"]
    return []


def execution_blockers(approval_file: Path) -> tuple[list[str], str | None]:
    try:
        document = read_json(approval_file)
        phase = document.get("approval", {}).get("approved_phase")
        name = {"GRADER_SMOKE": "grader-smoke", "DEVELOPMENT_TUNING": "development", "HELDOUT_BENCHMARK": "heldout"}.get(phase)
        if name is None:
            return ["external approval phase is unknown"], None
        if name == "heldout":
            _validated_development_exec_005_failure()
            return ["HELDOUT_BENCHMARK is not authorized after terminal DEV _005"], name
        if name == "development":
            _validated_development_exec_005_failure()
        validate_exec_approval(name, approval_file)
    except (OSError, ValueError, BenchmarkExecutionError) as exc:
        return [str(exc)], None
    smoke = read_json(ARTIFACT / "grader_smoke_result.json")
    try:
        validate_grader_smoke_result(smoke)
    except (OSError, ValueError) as exc:
        return [f"official grader smoke evidence is invalid: {exc}"], name
    if smoke.get("status") == "FAIL":
        return [
            "terminal grader-smoke adapter-contract failure; rerun, DEV, and "
            "HELDOUT execution are not authorized"
        ], name
    if name == "grader-smoke" and smoke.get("status") != SMOKE_RECOVERY_STATUS:
        return [
            "fresh grader-smoke execution requires the exact P0.1.5 "
            "recovery-ready state"
        ], name
    if name in {"development", "heldout"}:
        if smoke.get("status") != "PASS":
            return ["official GOLD+NOOP_BASELINE smoke PASS is required before benchmark execution"], name
        try:
            verify_official_smoke_attestation_cryptographically()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return [f"official grader smoke attestation verification failed: {exc}"], name
    selected = validate_selected_m2(require_frozen=False)
    if name == "development" and selected.get("status") != "PRE_DEVELOPMENT":
        return ["development requires the exact PRE_DEVELOPMENT selection state"], name
    if name == "heldout":
        try:
            validate_selected_m2(require_frozen=True)
        except ValueError as exc:
            return [str(exc)], name
    return [], name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--level",
        choices=(
            "static",
            "benchmark-approval",
            "grader-smoke-exec",
            "benchmark-exec",
            "smoke-attestation-only",
        ),
        default="static",
    )
    parser.add_argument("--require-git-tracked", action="store_true")
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--pre-cell-failure-output", type=Path)
    args = parser.parse_args()
    if args.pre_cell_failure_output is not None and (
        args.level != "grader-smoke-exec" or args.approval_file is None
    ):
        parser.error(
            "--pre-cell-failure-output requires grader-smoke-exec and --approval-file"
        )
    validated_approval_binding: dict[str, Any] | None = None
    attestation_verification: dict[str, Any] | None = None

    def record_exec_gate_failure(reason: str) -> None:
        if (
            args.pre_cell_failure_output is None
            or validated_approval_binding is None
        ):
            return
        try:
            write_pre_cell_failure_evidence(
                args.pre_cell_failure_output.resolve(),
                approval_binding={
                    name: validated_approval_binding[name]
                    for name in (
                        "approval_artifact_sha256",
                        "approved_request_sha256",
                        "approved_workflow_run_id",
                        "approved_workflow_run_attempt",
                        "freeze_sha256",
                        "git_head",
                        "phase",
                    )
                },
                stage="EXEC_GATE",
                reason=reason.strip(),
            )
        except (OSError, ValueError):
            # Evidence persistence is secondary to the original gate failure.
            # The workflow still retains the gate's direct raw streams.
            return

    try:
        # Establish the approval binding before the broader static gate.  A
        # malformed/unbound secret never earns an approval-bound failure
        # record; any later gate failure does.
        if args.pre_cell_failure_output is not None:
            try:
                validated_approval_binding = validate_exec_approval(
                    "grader-smoke", args.approval_file.resolve()
                )
            except (OSError, ValueError):
                validated_approval_binding = None
        # Every approval or execution endpoint must prove that the entire
        # frozen closure is committed.  The flag remains useful for strict
        # local static checks, but cannot weaken an approval-level gate when
        # omitted by a caller.
        require_git_tracked = args.require_git_tracked or args.level != "static"
        evidence = validate_static(require_git_tracked)
        blockers: list[str] = []
        phase = None
        if args.level == "benchmark-approval":
            blockers = preapproval_blockers()
        elif args.level == "benchmark-exec":
            if args.approval_file is None:
                blockers = ["external immutable approval file is required"]
            else:
                blockers, phase = execution_blockers(args.approval_file.resolve())
            if phase not in {None, "development", "heldout"}:
                blockers.append("benchmark gate received a non-benchmark approval")
        elif args.level == "smoke-attestation-only":
            attestation_verification = verify_smoke_attestation_only()
        elif args.level == "grader-smoke-exec":
            if args.approval_file is None:
                blockers = ["external immutable approval file is required"]
            else:
                blockers, phase = execution_blockers(args.approval_file.resolve())
            if phase not in {None, "grader-smoke"}:
                blockers.append("grader-smoke gate received a non-smoke approval")
        committed_package = evidence.get(
            "grader_exec_package", "CORRECTION_IN_PROGRESS"
        )
        committed_viability = evidence.get(
            "official_grader_viability", "NOT_YET_ESTABLISHED"
        )
        report = {
            **evidence,
            "blockers": blockers,
            "level": args.level,
            "approved_phase": phase,
            "git_tracked_freeze_required": require_git_tracked,
            "grader_exec_package": committed_package,
            "official_grader_viability": committed_viability,
            "performance": evidence.get("performance", "NOT_MEASURED"),
            "status": "PASS" if not blockers else "FAIL_CLOSED",
            "trimem_system_implementation": "CREDENTIAL_FREE_GREEN",
        }
        if (
            args.level == "benchmark-exec"
            and phase == "development"
            and not blockers
        ):
            report["dev_approval_allowed"] = True
            report["dev_execution_allowed"] = True
        if attestation_verification is not None:
            report["attestation_verification"] = attestation_verification
            report["attestation_only_execution"] = dict(
                ATTESTATION_ONLY_EXECUTION
            )
        if blockers:
            record_exec_gate_failure("; ".join(blockers))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if not blockers else 1
    except (
        OSError,
        ValueError,
        BenchmarkExecutionError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        record_exec_gate_failure(str(exc).strip() or type(exc).__name__)
        print(json.dumps({"error": str(exc), "level": args.level, "status": "FAIL"}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
