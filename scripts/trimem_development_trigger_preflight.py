"""Fail closed before the one-time branch-local DEVELOPMENT_TUNING run.

The committed request is a zero-authority sentinel.  It may create exactly one
GitHub Actions run, but the protected job cannot execute until a separate
external approval binds that run, its first attempt, the execution commit, the
sentinel's source commit, the research freeze, and the exact phase caps.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trimem_install_pinned_gh import load_gh_cli_lock, verify_installed_gh


EXPECTED_EVENT = "push"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_REF = "refs/heads/codex/trimem-coder-v1"
EXPECTED_WORKFLOW_REF = (
    "Scuttie/enterprise-shared-memory-poc/.github/workflows/"
    "trimem-benchmark.yml@refs/heads/codex/trimem-coder-v1"
)
EXPECTED_PHASE = "DEVELOPMENT_TUNING"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_004"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.3"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/"
    "DEVELOPMENT_TUNING_EXEC_REQUEST_004.json"
)
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/"
    "DEVELOPMENT_TUNING_EXEC_REQUEST_003.json"
)
RECOVERY_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-003/"
    "model-parser-failure-receipt.json"
)
MIDDLE_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/"
    "DEVELOPMENT_TUNING_EXEC_REQUEST_002.json"
)
MIDDLE_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-002/"
    "protected-exec-gate-failure-receipt.json"
)
EARLIER_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/"
    "DEVELOPMENT_TUNING_EXEC_REQUEST_001.json"
)
EARLIER_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-001/"
    "preflight-failure-receipt.json"
)
EARLIER_SOURCE_HEAD = "0fe4cd70604d381f5a8d7d0a384724817c6e3a42"
EARLIER_EXECUTION_HEAD = "6eba1b0f9462c3b29323a9ade290470551bfd0ed"
MIDDLE_SOURCE_HEAD = "98dd37fec7c826f6ed5b3b8734f2ca8dcab96e4a"
MIDDLE_EXECUTION_HEAD = "c2738cae074351927dde117b628c601b1e296cf2"
PREVIOUS_SOURCE_HEAD = "763cec6c399714151860aebabc93bdbeac2e1cff"
PREVIOUS_EXECUTION_HEAD = "bc70e1979c2987cd52347b2ef2fd7c43dc3014df"
WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"
TOOLCHAIN_WORKFLOW_PATH = ".github/workflows/ci-trimem-dev-toolchain.yml"
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-004"
FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
GH_CLI_LOCK_PATH = "configs/trimem_v1/gh_cli_lock.json"
MODEL_LOCK_PATH = "configs/trimem_v1/model_lock.json"
COST_PLAN_PATH = "configs/trimem_v1/cost_plan.json"
POLICY_REQUEST_PATH = "configs/trimem_v1/benchmark_exec_request.json"
DEVELOPMENT_MANIFEST_PATH = "configs/trimem_v1/development_manifest.json"
M2_CANDIDATE_MANIFEST_PATH = "configs/trimem_v1/m2_candidate_bundles.json"
SELECTION_PLAN_PATH = "configs/trimem_v1/selection_plan.json"
GRADER_LOCK_PATH = "configs/trimem_v1/grader_lock.json"
IMAGE_LOCK_PATH = "artifacts/trimem_v1/grader_image_lock.json"
MODEL_PRICING_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_model_pricing_amendment.json"
)
BENCHMARK_ENVIRONMENT_PROTECTION_PATH = (
    "artifacts/trimem_v1/benchmark_environment_protection.json"
)
TOOLCHAIN_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_runner_toolchain_amendment.json"
)
CREDENTIAL_FREE_BUNDLE_PATH = (
    "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
)
RESPONSE_CONTRACT_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_response_contract_amendment.json"
)
PROVIDER_OUTPUT_SCHEMA_LOCK_PATH = (
    "artifacts/trimem_v1/provider_output_schema_lock.json"
)
PROVIDER_OUTPUT_SCHEMAS_PATH = "configs/trimem_v1/provider_output_schemas.json"
PREFLIGHT_PATH = "scripts/trimem_development_trigger_preflight.py"
GH_INSTALLER_PATH = "scripts/trimem_install_pinned_gh.py"
GH_VERIFIER_PATH = "scripts/trimem_verify_gh_lock.py"
READINESS_VERIFIER_PATH = "scripts/trimem_verify_ready.py"
BENCHMARK_RUNNER_PATH = "scripts/trimem_benchmark_run.py"
APPROVAL_VALIDATOR_PATH = "scripts/trimem_exec_approval.py"
APPROVED_PHASE_PATH = "scripts/trimem_approved_phase.py"
FREEZE_SCRIPT_PATH = "scripts/trimem_freeze.py"
CLEANUP_SCRIPT_PATH = "scripts/trimem_cleanup_exec.py"
TRIGGER_TEST_PATH = "tests/unit/test_trimem_development_trigger.py"
MATRIX_PATH = "scripts/trimem_benchmark_matrix.py"
PUBLIC_ARTIFACT_PATH = "scripts/trimem_public_artifact.py"
RESUME_DRIVER_PATH = "scripts/trimem_run_with_resume.py"
REQUIRED_REMOTE_GATE_WORKFLOWS = (
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem-multi-swe-contract.yml",
    TOOLCHAIN_WORKFLOW_PATH,
)
REMOTE_GATE_SCHEMA = "trimem/development-remote-gate-evidence/1.0"

AUTHORIZATION_SEMANTICS = (
    "The sentinel creates one run but does not authorize protected execution."
)
RECOVERY_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_RESPONSE_CONTRACT_RECOVERY_EXEC_APPROVED_ONCE"
)
REQUIRED_EXTERNAL_AUTHORIZATION = RECOVERY_AUTHORIZATION
D12_RECOVERY_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_GH_RECOVERY_EXEC_APPROVED_ONCE"
)
EXACT_MODEL = {
    "cached_input_price_per_million_tokens_usd": 0.075,
    "endpoint": "https://api.openai.com/v1/responses",
    "exact_returned_model_required": "gpt-5.4-mini-2026-03-17",
    "input_price_per_million_tokens_usd": 0.75,
    "model_id": "gpt-5.4-mini-2026-03-17",
    "nano_mixing_allowed": False,
    "output_price_per_million_tokens_usd": 4.5,
    "provider": "openai",
    "reasoning_effort": "medium",
    "request_schema_sha256": "480aedd6d1e33036d1f6564dcddb936fac02566bf3c1f2b47082b15ca1b1da6a",
    "temperature": "OMITTED",
    "top_p": "OMITTED",
    "roles": {
        "decomposition": "gpt-5.4-mini-2026-03-17",
        "experience_extraction": "gpt-5.4-mini-2026-03-17",
        "solve": "gpt-5.4-mini-2026-03-17",
    },
}
SCIENTIFIC_WORKLOAD = {
    "grader_containers": 72,
    "m0_task_arm_runs": 12,
    "m1_task_arm_runs": 12,
    "m2_candidate_streams": 4,
    "m2_task_arm_runs": 48,
    "task_arm_runs": 72,
    "unique_development_targets": 12,
}
HARD_CAPS = {
    "benchmark_grader_containers": 72,
    "decomposition_calls": 72,
    "extraction_calls": 72,
    "input_tokens": 36_000_000,
    "max_input_tokens_per_task_arm": 500_000,
    "max_model_calls_per_task_arm": 26,
    "model_calls": 1_872,
    "output_tokens": 4_718_592,
    "paid_model_calls": 1_872,
    "solve_calls": 1_728,
    "task_arm_runs": 72,
    "total_usd": 50.0,
    "uncached_token_cost_ceiling_usd": 48.233664,
}
EXPECTED_EXPENDITURE = {
    "cached_input_tokens": 0,
    "decomposition_calls": 72,
    "extraction_calls": 72,
    "input_tokens": 11_808_000,
    "model_calls": 1_008,
    "output_tokens": 432_000,
    "solve_calls": 864,
    "status": "PLANNING_ESTIMATE_NOT_REQUIRED_EXPENDITURE",
    "task_arm_runs": 72,
    "total_usd": 10.8,
}
PRE_EXECUTION_ACTUALS = {
    "api_calls": 1,
    "cached_input_tokens": None,
    "decomposition_calls": 1,
    "extraction_calls": 0,
    "grader_calls": 0,
    "grader_containers": 0,
    "input_tokens": None,
    "model_calls": 1,
    "model_gateway_calls": 1,
    "official_grader_runs": 0,
    "output_tokens": None,
    "paid_model_calls": 1,
    "provider_reported_usage": "UNAVAILABLE_DUE_TO_ADAPTER_OBSERVABILITY_GAP",
    "reasoning_tokens": None,
    "ledger_reservation": {
        "input_tokens": 5069,
        "output_tokens": 2048,
        "total_usd": 0.01301775,
    },
    "scope": "D1.3_RESPONSE_CONTRACT_RECOVERY_004_BEFORE_FRESH_EXECUTION",
    "solve_calls": 0,
    "target_image_pulls": 0,
    "task_arm_runs": 0,
    "total_usd": 0.01301775,
}
RECOVERY_PROVENANCE = {
    "failed_endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
    "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
    "failed_run_attempt": 1,
    "failed_run_id": 33_788_493_773,
    "failure_label": "TRIMEM_DEV_FIRST_DECOMPOSITION_EMPTY_EXTRACTED_TEXT",
    "grader_containers": 0,
    "input_tokens": 0,
    "model_calls": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_003",
    "previous_request_path": PREVIOUS_SENTINEL_PATH,
    "previous_request_raw_sha256": (
        "sha256:3d6b4291f7a1ab8b72203e4756a2f7e4614c1139c9f6e0da74a3a949fa78ca56"
    ),
    "protected_execution_authorization_required": REQUIRED_EXTERNAL_AUTHORIZATION,
    "approval_materialization_reached": True,
    "protected_environment_reached": True,
    "protected_execution_reached": True,
    "received_recovery_authorization": RECOVERY_AUTHORIZATION,
    "raw_provider_outcome_class": "UNAVAILABLE_DUE_TO_ADAPTER_OBSERVABILITY_GAP",
    "historical_api_calls": 1,
    "historical_completed_task_arm_runs": 0,
    "scientific_task_arm_runs": 0,
    "total_usd": 0.0,
}
PROHIBITED_ACTIONS = [
    "DEVELOPMENT_TUNING_EXEC_REQUEST_003_rerun_or_attempt_2",
    "DEVELOPMENT_TUNING_EXEC_REQUEST_005",
    "HELDOUT_BENCHMARK",
    "additional_development_targets",
    "automatic_next_phase_execution",
    "candidate_addition",
    "component_ablation",
    "grader_smoke_rerun",
    "fifth_M2_candidate",
    "merge_tag_or_release",
    "model_replacement",
    "additional_development_dispatch_or_rerun_after_recovery_004",
    "target_replacement",
]
EXPECTED_TARGET_SET_SHA256 = (
    "e7da59b3c2638c89da4e333a7391851e992c122acac11bc9edf60619cfd5eff2"
)
EXPECTED_EXECUTION_SEQUENCE_SHA256 = (
    "89d222638aa603221c1a18b8ab788ae49d51708375b1fe5ec03d1102196289dd"
)
EXPECTED_FROZEN_INPUT_SHA256 = {
    MODEL_LOCK_PATH: "aae9d9ddcbf0fcd12a519c388ecc468e029bc3c9de59e2471af8389c08cd7d72",
    COST_PLAN_PATH: "bd2ef2896728597cd4f55245544ef43ffb07c63a27d5b86e5a9c577b34175910",
    POLICY_REQUEST_PATH: "05e19aeec6630f2362c481a86eb66d0e630041794866a638c3ebbf07e5ccbba4",
    DEVELOPMENT_MANIFEST_PATH: "44e52137dad68618396c15d6b3c2221a683f89988e361efb2966e244ba230900",
    M2_CANDIDATE_MANIFEST_PATH: "b564ccbee8b5b9ee584835b2d7c00079e4fc23312fcfd6df286d808ee8642dcd",
    SELECTION_PLAN_PATH: "dddc421120d16f241a2941afbd67190df4b3be6cefeab99e37437abf7133dcf4",
    GRADER_LOCK_PATH: "853d42e86c2caf1449f28bba9143741e3ccff5e75bbe790115a0d9c746014fbb",
    IMAGE_LOCK_PATH: "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb",
    MODEL_PRICING_AMENDMENT_PATH: "19caede5a601f8d0ebc1267dbb393b9b707aae37e144a31a9346087d2c320cee",
}
EXPECTED_RECOVERY_INPUT_SHA256 = {
    EARLIER_SENTINEL_PATH: "7501c630a05ab0b87b9b510a72a5389f6ea7046dee6153b583e2833fa8e7e1db",
    EARLIER_FAILURE_RECEIPT_PATH: "16bda3012e29d6a3659d5a96537615db7ed72fa817e541e16db2c4d5d5d79868",
    MIDDLE_SENTINEL_PATH: "c81c57a5c93d4be9efdc971147191d8bc2e1bc2f06fe241e38ce36b6a4ee3f98",
    MIDDLE_FAILURE_RECEIPT_PATH: "8c9d4a8fea70e0088b7af9bb011e1e75081f4e9ddee9f7162cf05ff85c9f9d1a",
    PREVIOUS_SENTINEL_PATH: "3d6b4291f7a1ab8b72203e4756a2f7e4614c1139c9f6e0da74a3a949fa78ca56",
    RECOVERY_FAILURE_RECEIPT_PATH: "6fbfbf4bf169e6365439f25bb7ea14bcac114e30fde9df1f814c93ba8ebc75be",
}
D13_MUTABLE_PRESERVED_CONTRACT_PATHS = {
    "configs/trimem_v1/arms.json",
    "configs/trimem_v1/cost_plan.json",
    "configs/trimem_v1/m2_candidate_bundles.json",
    "configs/trimem_v1/model_lock.json",
    "configs/trimem_v1/selected_m2.json",
    "configs/trimem_v1/tool_environment_lock.json",
    "src/enterprise_memory/trimem/runtime_lock.py",
}
EXPECTED_D12_PRESERVED_SHA256 = {
    "artifacts/trimem_v1/development_model_pricing_amendment.json": "19caede5a601f8d0ebc1267dbb393b9b707aae37e144a31a9346087d2c320cee",
    "artifacts/trimem_v1/grader_image_lock.json": "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb",
    "artifacts/trimem_v1/grader_smoke_official/exec-005/attestation-bundle.json": "c1cc04284b8f1be1cde006fa2309f6af918e8478485002b4556df7fcb165335e",
    "artifacts/trimem_v1/grader_smoke_official/exec-005/attestation-subject.json": "647d9d3eaddaf2917bfaaa8fc47c0c54f814a50ddf5e900c3176d3c895513846",
    "artifacts/trimem_v1/grader_smoke_official/exec-005/evidence-inventory.json": "b1c3ba191c4d037f4f8ee70cf8a4821592b5b25a65700d7ce3faa2d0024add8e",
    "artifacts/trimem_v1/grader_smoke_official/exec-005/public-results.json": "4a1253e69a95b3058b9433fbfe51ef3f8bee538c90b5faf29c996a841224faa4",
    "configs/trimem_v1/arms.json": "88cbe12d47780509216498816fa13349f0027f239937c5f8cb54d90a17c93cb1",
    "configs/trimem_v1/cost_plan.json": "d54b70e8c700cedff987efa713aeddf724059b7320bbe8fc1970ca9c0f69a86e",
    "configs/trimem_v1/development_manifest.json": "44e52137dad68618396c15d6b3c2221a683f89988e361efb2966e244ba230900",
    "configs/trimem_v1/grader_lock.json": "853d42e86c2caf1449f28bba9143741e3ccff5e75bbe790115a0d9c746014fbb",
    "configs/trimem_v1/grader_smoke_manifest.json": "cf9a841a5509133d501dc83e7b69ddbd85770c371ab3ed9cda008f598349d409",
    "configs/trimem_v1/heldout_manifest.json": "951371ed84931b37e27929e2669aff5d06e32215d1a300e3343ba7f1bdd84fda",
    "configs/trimem_v1/m2_candidate_bundles.json": "3248b15e3f9f7293cacfea1f13fcfd354dbb804d34a1ea40dce6d8c1b881a6de",
    "configs/trimem_v1/model_lock.json": "f5e932696d31d1cb7185b32b67c38e4c9cbbfedd79783adfb8faddc7b90abfe0",
    "configs/trimem_v1/selected_m2.json": "1b9a1777515475dddaf303c2ad85e3be67eac7cfb7a1bc1918a208c740f4a8fc",
    "configs/trimem_v1/selection_plan.json": "dddc421120d16f241a2941afbd67190df4b3be6cefeab99e37437abf7133dcf4",
    "configs/trimem_v1/sigstore_trusted_root.jsonl": "65ca537f6ed8a47fd0e560c421baa1f6c1efb8b25fc200d8c5c02c0e92eb2b9c",
    "configs/trimem_v1/tool_environment_lock.json": "7b4bafe0a5366fdb9277a49ebb70fe6197f3bb27fa253f75ffe686a7a44f7c6c",
    "src/enterprise_memory/trimem/runtime_lock.py": "053de00adb66a13fb0cb3b039b008e9fdc028121dc5fc060cfddc2c371a32aed",
}
DEVELOPMENT_APPROVAL_FIELDS = [
    "approved_git_commit",
    "approved_source_git_commit",
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
]
BOUND_PATHS = {
    "benchmark_exec_request_sha256": POLICY_REQUEST_PATH,
    "benchmark_workflow_sha256": WORKFLOW_PATH,
    "cost_plan_sha256": COST_PLAN_PATH,
    "credential_free_bundle_sha256": CREDENTIAL_FREE_BUNDLE_PATH,
    "development_manifest_sha256": DEVELOPMENT_MANIFEST_PATH,
    "freeze_sha256": FREEZE_PATH,
    "grader_lock_sha256": GRADER_LOCK_PATH,
    "gh_cli_lock_sha256": GH_CLI_LOCK_PATH,
    "gh_installer_sha256": GH_INSTALLER_PATH,
    "gh_verifier_sha256": GH_VERIFIER_PATH,
    "image_lock_sha256": IMAGE_LOCK_PATH,
    "m2_candidate_manifest_sha256": M2_CANDIDATE_MANIFEST_PATH,
    "model_lock_sha256": MODEL_LOCK_PATH,
    "model_pricing_amendment_sha256": MODEL_PRICING_AMENDMENT_PATH,
    "previous_dev_request_sha256": PREVIOUS_SENTINEL_PATH,
    "provider_output_schema_lock_sha256": PROVIDER_OUTPUT_SCHEMA_LOCK_PATH,
    "provider_output_schemas_sha256": PROVIDER_OUTPUT_SCHEMAS_PATH,
    "recovery_failure_receipt_sha256": RECOVERY_FAILURE_RECEIPT_PATH,
    "response_contract_amendment_sha256": RESPONSE_CONTRACT_AMENDMENT_PATH,
    "runner_toolchain_amendment_sha256": TOOLCHAIN_AMENDMENT_PATH,
    "selection_plan_sha256": SELECTION_PLAN_PATH,
    "toolchain_workflow_sha256": TOOLCHAIN_WORKFLOW_PATH,
}
FREEZE_CLOSURE_PATHS = (
    WORKFLOW_PATH,
    TOOLCHAIN_WORKFLOW_PATH,
    GH_CLI_LOCK_PATH,
    MODEL_LOCK_PATH,
    COST_PLAN_PATH,
    POLICY_REQUEST_PATH,
    DEVELOPMENT_MANIFEST_PATH,
    M2_CANDIDATE_MANIFEST_PATH,
    SELECTION_PLAN_PATH,
    GRADER_LOCK_PATH,
    IMAGE_LOCK_PATH,
    BENCHMARK_ENVIRONMENT_PROTECTION_PATH,
    TOOLCHAIN_AMENDMENT_PATH,
    CREDENTIAL_FREE_BUNDLE_PATH,
    RESPONSE_CONTRACT_AMENDMENT_PATH,
    PROVIDER_OUTPUT_SCHEMA_LOCK_PATH,
    PROVIDER_OUTPUT_SCHEMAS_PATH,
    PREFLIGHT_PATH,
    GH_INSTALLER_PATH,
    GH_VERIFIER_PATH,
    READINESS_VERIFIER_PATH,
    BENCHMARK_RUNNER_PATH,
    APPROVAL_VALIDATOR_PATH,
    APPROVED_PHASE_PATH,
    FREEZE_SCRIPT_PATH,
    CLEANUP_SCRIPT_PATH,
    TRIGGER_TEST_PATH,
    MATRIX_PATH,
    PUBLIC_ARTIFACT_PATH,
    RESUME_DRIVER_PATH,
    PREVIOUS_SENTINEL_PATH,
    RECOVERY_FAILURE_RECEIPT_PATH,
    EARLIER_SENTINEL_PATH,
    EARLIER_FAILURE_RECEIPT_PATH,
)
REQUEST_FIELDS = frozenset(
    {
        "actual_execution_authorized",
        "amendment_classification",
        "authorization_semantics",
        "bindings",
        "branch_ref",
        "exact_model",
        "expected_expenditure",
        "hard_caps",
        "heldout_execution_authorized",
        "grader_smoke_rerun_authorized",
        "model_secret_required",
        "one_time_workflow_run_attempt",
        "phase",
        "pre_execution_actuals",
        "prohibited_actions",
        "recovery_provenance",
        "remote_gate_evidence",
        "request_id",
        "request_path",
        "request_sha256",
        "required_external_approval_fields",
        "required_external_authorization",
        "requires_external_approval",
        "schema",
        "scientific_workload",
        "source_head",
        "workflow_path",
    }
)
FORBIDDEN_PREFLIGHT_SECRETS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GOOGLE_API_KEY",
        "MODEL_API_KEY",
        "OPENAI_API_KEY",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "TRIMEM_EXEC_APPROVAL_B64",
        "UPSTAGE_API_KEY",
    }
)
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


class DevelopmentTriggerError(ValueError):
    """The branch-local request differs from the frozen one-time contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DevelopmentTriggerError(message)


def _reject_constant(value: str) -> None:
    raise DevelopmentTriggerError(f"non-finite JSON number is forbidden: {value}")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DevelopmentTriggerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DevelopmentTriggerError("request is not strict UTF-8 JSON") from exc
    _require(isinstance(value, dict), "request must be a JSON object")
    return value


def canonical_bytes(value: Any, *, trailing_lf: bool = False) -> bytes:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DevelopmentTriggerError("request is not canonical JSON") from exc
    return raw + (b"\n" if trailing_lf else b"")


def sha256_prefixed(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _validate_remote_gate_evidence(
    evidence: Any, *, source_head: str
) -> dict[str, Any]:
    _require(isinstance(evidence, dict), "remote gate evidence is missing")
    _require(
        set(evidence)
        == {
            "all_required_workflows_passed",
            "observed_at_utc",
            "repository",
            "schema",
            "scientific_execution",
            "source_head",
            "source_ref",
            "workflows",
        },
        "remote gate evidence field set differs",
    )
    _require(evidence.get("schema") == REMOTE_GATE_SCHEMA, "remote gate schema differs")
    _require(
        evidence.get("repository") == EXPECTED_REPOSITORY
        and evidence.get("source_head") == source_head
        and evidence.get("source_ref") == EXPECTED_REF
        and evidence.get("all_required_workflows_passed") is True,
        "remote gate source or aggregate status differs",
    )
    observed_at = evidence.get("observed_at_utc")
    _require(
        isinstance(observed_at, str) and observed_at.endswith("Z"),
        "remote gate observation timestamp is not UTC",
    )
    try:
        parsed_observed_at = datetime.fromisoformat(observed_at[:-1] + "+00:00")
    except ValueError as exc:
        raise DevelopmentTriggerError(
            "remote gate observation timestamp is invalid"
        ) from exc
    _require(
        parsed_observed_at.tzinfo == timezone.utc,
        "remote gate observation timestamp is not timezone-aware",
    )
    scientific_execution = evidence.get("scientific_execution")
    expected_zero = {
        "api_calls": 0,
        "grader_runs": 0,
        "model_calls": 0,
        "paid_model_calls": 0,
        "target_image_pulls": 0,
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }
    _require(
        scientific_execution == expected_zero,
        "remote credential-free gates contain scientific execution",
    )
    workflows = evidence.get("workflows")
    _require(
        isinstance(workflows, list)
        and len(workflows) == len(REQUIRED_REMOTE_GATE_WORKFLOWS),
        "remote gate workflow count differs",
    )
    for expected_path, row in zip(
        REQUIRED_REMOTE_GATE_WORKFLOWS, workflows, strict=True
    ):
        _require(
            isinstance(row, dict)
            and set(row)
            == {
                "conclusion",
                "event",
                "head_branch",
                "head_sha",
                "html_url",
                "run_attempt",
                "run_id",
                "status",
                "workflow_path",
            },
            f"remote gate row shape differs: {expected_path}",
        )
        _require(
            row.get("workflow_path") == expected_path
            and row.get("head_sha") == source_head
            and row.get("head_branch") == EXPECTED_BRANCH
            and row.get("event") == "push"
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
            and type(row.get("run_id")) is int
            and row["run_id"] > 0
            and type(row.get("run_attempt")) is int
            and row.get("run_attempt") == 1
            and isinstance(row.get("html_url"), str)
            and row["html_url"]
            == (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                f"actions/runs/{row['run_id']}"
            ),
            f"remote gate is missing, red, rerun, or bound to another HEAD: {expected_path}",
        )
    return deepcopy(evidence)


def collect_remote_gate_evidence(source_head: str) -> dict[str, Any]:
    """Read all exact-head credential-free workflow conclusions via GitHub CLI."""

    _require(HEX40.fullmatch(source_head) is not None, "source_head is not a commit SHA")
    gh = shutil.which("gh")
    _require(gh is not None, "gh CLI is required to verify remote gates")
    try:
        gh_lock = load_gh_cli_lock(Path(__file__).resolve().parents[1] / GH_CLI_LOCK_PATH)
        gh_verification = verify_installed_gh(gh_lock, Path(gh))
    except (OSError, ValueError) as exc:
        raise DevelopmentTriggerError(
            "remote gate observer does not match the pinned gh byte lock"
        ) from exc
    _require(
        gh_verification.get("first_version_line")
        == "gh version 2.97.0 (2026-07-31)",
        "remote gate observer is not exact gh 2.97.0",
    )
    safe_environment = {
        key: value
        for key, value in os.environ.items()
        if key not in FORBIDDEN_PREFLIGHT_SECRETS
    }
    try:
        query = subprocess.run(
            [
                gh,
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                f"repos/{EXPECTED_REPOSITORY}/actions/runs",
                "-f",
                f"head_sha={source_head}",
                "-f",
                "event=push",
                "-f",
                "per_page=100",
            ],
            capture_output=True,
            text=False,
            check=False,
            timeout=60,
            env=safe_environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerError("GitHub remote gate query failed") from exc
    _require(query.returncode == 0, "GitHub remote gate query failed")
    response = strict_json_object(query.stdout)
    runs = response.get("workflow_runs")
    _require(isinstance(runs, list), "GitHub remote gate response has no workflow runs")
    rows: list[dict[str, Any]] = []
    for expected_path in REQUIRED_REMOTE_GATE_WORKFLOWS:
        matches = [
            row
            for row in runs
            if isinstance(row, dict)
            and row.get("path") == expected_path
            and row.get("head_sha") == source_head
            and row.get("event") == "push"
        ]
        _require(
            len(matches) == 1,
            f"exactly one exact-head attempt-1 run is required: {expected_path}",
        )
        run = matches[0]
        rows.append(
            {
                "conclusion": run.get("conclusion"),
                "event": run.get("event"),
                "head_branch": run.get("head_branch"),
                "head_sha": run.get("head_sha"),
                "html_url": run.get("html_url"),
                "run_attempt": run.get("run_attempt"),
                "run_id": run.get("id"),
                "status": run.get("status"),
                "workflow_path": run.get("path"),
            }
        )
    evidence = {
        "all_required_workflows_passed": True,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "repository": EXPECTED_REPOSITORY,
        "schema": REMOTE_GATE_SCHEMA,
        "scientific_execution": {
            "api_calls": 0,
            "grader_runs": 0,
            "model_calls": 0,
            "paid_model_calls": 0,
            "target_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "source_head": source_head,
        "source_ref": EXPECTED_REF,
        "workflows": rows,
    }
    return _validate_remote_gate_evidence(evidence, source_head=source_head)


def _run_git(repository: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repository,
        capture_output=True,
        text=text,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr if text else result.stderr.decode("utf-8", "replace")
        raise DevelopmentTriggerError(
            "git verification failed: %s" % stderr.strip()
        )
    return result.stdout


def _commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    raw = _run_git(repository, "show", f"{commit}:{path}", text=False)
    assert isinstance(raw, bytes)
    return raw


def _validate_historical_sentinel(
    repository: Path,
    material_commit: str,
    *,
    execution_head: str,
    source_head: str,
    sentinel_path: str,
    label: str,
) -> None:
    resolved = str(
        _run_git(
            repository,
            "rev-parse",
            "--verify",
            f"{execution_head}^{{commit}}",
        )
    ).strip()
    _require(resolved == execution_head, f"historical {label} execution commit identity differs")
    parents = str(
        _run_git(
            repository,
            "rev-list",
            "--parents",
            "-n",
            "1",
            execution_head,
        )
    ).strip().split()
    _require(
        parents == [execution_head, source_head],
        f"historical {label} parent identity differs",
    )
    ancestry = subprocess.run(
        [
            "git",
            "-c",
            "core.quotepath=false",
            "merge-base",
            "--is-ancestor",
            execution_head,
            material_commit,
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    _require(
        ancestry.returncode == 0 and material_commit != execution_head,
        f"material commit does not descend from immutable {label} history",
    )
    changes = str(
        _run_git(
            repository,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            execution_head,
        )
    ).splitlines()
    _require(
        changes == [f"A\t{sentinel_path}"],
        f"historical {label} commit was not sentinel-only",
    )
    tree = str(
        _run_git(repository, "ls-tree", execution_head, "--", sentinel_path)
    ).strip()
    _require(
        re.fullmatch(
            rf"100644 blob [0-9a-f]{{40}}\t{re.escape(sentinel_path)}", tree
        )
        is not None,
        f"historical {label} sentinel is not the exact regular Git blob",
    )
    _require(
        hashlib.sha256(_commit_bytes(repository, execution_head, sentinel_path)).hexdigest()
        == EXPECTED_RECOVERY_INPUT_SHA256[sentinel_path],
        f"historical {label} Git blob bytes differ",
    )


def _validate_historical_recovery_graph(repository: Path, commit: str) -> None:
    """Bind D1.3 recovery material to immutable _001 through _003 ancestry."""

    _require(HEX40.fullmatch(commit) is not None, "material commit is not a commit SHA")
    _validate_historical_sentinel(
        repository,
        commit,
        execution_head=EARLIER_EXECUTION_HEAD,
        source_head=EARLIER_SOURCE_HEAD,
        sentinel_path=EARLIER_SENTINEL_PATH,
        label="_001",
    )
    _validate_historical_sentinel(
        repository,
        commit,
        execution_head=MIDDLE_EXECUTION_HEAD,
        source_head=MIDDLE_SOURCE_HEAD,
        sentinel_path=MIDDLE_SENTINEL_PATH,
        label="_002",
    )
    _validate_historical_sentinel(
        repository,
        commit,
        execution_head=PREVIOUS_EXECUTION_HEAD,
        source_head=PREVIOUS_SOURCE_HEAD,
        sentinel_path=PREVIOUS_SENTINEL_PATH,
        label="_003",
    )


def _material(repository: Path, commit: str) -> dict[str, bytes]:
    paths = (
        set(BOUND_PATHS.values())
        | set(FREEZE_CLOSURE_PATHS)
        | set(EXPECTED_RECOVERY_INPUT_SHA256)
    )
    return {path: _commit_bytes(repository, commit, path) for path in paths}


def _json_material(raw: Mapping[str, bytes], path: str) -> dict[str, Any]:
    try:
        return strict_json_object(raw[path])
    except DevelopmentTriggerError as exc:
        raise DevelopmentTriggerError(f"invalid committed JSON at {path}: {exc}") from exc


def _validate_frozen_material(
    repository: Path, commit: str
) -> tuple[dict[str, bytes], dict[str, str], dict[str, Any]]:
    _validate_historical_recovery_graph(repository, commit)
    raw = _material(repository, commit)
    for path, expected_sha256 in EXPECTED_FROZEN_INPUT_SHA256.items():
        _require(
            hashlib.sha256(raw[path]).hexdigest() == expected_sha256,
            f"frozen scientific or model/pricing input changed: {path}",
        )
    for path, expected_sha256 in EXPECTED_RECOVERY_INPUT_SHA256.items():
        _require(
            hashlib.sha256(raw[path]).hexdigest() == expected_sha256,
            f"immutable DEV recovery input changed: {path}",
        )
    previous_request = _json_material(raw, PREVIOUS_SENTINEL_PATH)
    failure_receipt = _json_material(raw, RECOVERY_FAILURE_RECEIPT_PATH)
    _require(
        previous_request.get("request_id")
        == RECOVERY_PROVENANCE["previous_request_id"]
        and previous_request.get("request_path") == PREVIOUS_SENTINEL_PATH
        and previous_request.get("source_head")
        == PREVIOUS_SOURCE_HEAD
        and previous_request.get("one_time_workflow_run_attempt") == 1,
        "historical _003 DEV request identity differs",
    )
    _require(
        failure_receipt.get("schema")
        == "trimem/development-model-parser-failure-receipt/1.0"
        and failure_receipt.get("endpoint")
        == RECOVERY_PROVENANCE["failed_endpoint"]
        and failure_receipt.get("workflow_run", {}).get("id")
        == RECOVERY_PROVENANCE["failed_run_id"]
        and failure_receipt.get("workflow_run", {}).get("run_attempt")
        == RECOVERY_PROVENANCE["failed_run_attempt"]
        and failure_receipt.get("workflow_run", {}).get("head_sha")
        == RECOVERY_PROVENANCE["failed_execution_head"]
        and failure_receipt.get("sentinel", {}).get("raw_sha256")
        == RECOVERY_PROVENANCE["previous_request_raw_sha256"],
        "historical _003 first-decomposition failure receipt differs",
    )
    approval = failure_receipt.get("approval", {})
    control_plane = failure_receipt.get("control_plane", {})
    _require(
        approval.get("materialization_status") == "PASS"
        and approval.get("phase_and_event_checks_status") == "PASS"
        and approval.get("approved_git_commit") == PREVIOUS_EXECUTION_HEAD
        and approval.get("approved_source_git_commit") == PREVIOUS_SOURCE_HEAD
        and approval.get("approved_workflow_run_id")
        == RECOVERY_PROVENANCE["failed_run_id"]
        and approval.get("approved_workflow_run_attempt")
        == RECOVERY_PROVENANCE["failed_run_attempt"]
        and control_plane.get("protected_environment_worked") is True
        and control_plane.get("protected_environment_approval_count") == 1
        and control_plane.get("exec_gate_status") == "PASS",
        "historical _003 approval/environment boundary differs",
    )
    receipt_accounting = failure_receipt.get("execution_accounting")
    _require(
        isinstance(receipt_accounting, dict)
        and receipt_accounting.get("completed_task_arm_runs") == 0
        and receipt_accounting.get("model_calls") == 1
        and receipt_accounting.get("paid_model_calls") == 1
        and receipt_accounting.get("api_calls") == 1
        and receipt_accounting.get("grader_containers") == 0
        and receipt_accounting.get("provider_reported_usage_available_on_failure")
        is False,
        "historical _003 execution-accounting boundary differs",
    )
    model = _json_material(raw, MODEL_LOCK_PATH)
    cost = _json_material(raw, COST_PLAN_PATH)
    policy = _json_material(raw, POLICY_REQUEST_PATH)
    manifest = _json_material(raw, DEVELOPMENT_MANIFEST_PATH)
    candidates = _json_material(raw, M2_CANDIDATE_MANIFEST_PATH)
    selection = _json_material(raw, SELECTION_PLAN_PATH)
    grader = _json_material(raw, GRADER_LOCK_PATH)
    gh_lock = _json_material(raw, GH_CLI_LOCK_PATH)
    images = _json_material(raw, IMAGE_LOCK_PATH)
    freeze = _json_material(raw, FREEZE_PATH)
    amendment = _json_material(raw, MODEL_PRICING_AMENDMENT_PATH)
    environment = _json_material(raw, BENCHMARK_ENVIRONMENT_PROTECTION_PATH)
    toolchain_amendment = _json_material(raw, TOOLCHAIN_AMENDMENT_PATH)
    response_amendment = _json_material(raw, RESPONSE_CONTRACT_AMENDMENT_PATH)
    schema_lock = _json_material(raw, PROVIDER_OUTPUT_SCHEMA_LOCK_PATH)
    output_schemas = _json_material(raw, PROVIDER_OUTPUT_SCHEMAS_PATH)

    _require(
        response_amendment.get("classification")
        == "PRE_RESULT_PROVIDER_OUTPUT_CONTRACT_AMENDMENT"
        and response_amendment.get("causal_boundary", {}).get(
            "historical_run_id"
        )
        == RECOVERY_PROVENANCE["failed_run_id"]
        and response_amendment.get("causal_boundary", {}).get(
            "historical_completed_task_arm_runs"
        )
        == 0
        and response_amendment.get("execution_boundary", {}).get(
            "fresh_request_id"
        )
        == REQUEST_ID
        and response_amendment.get("execution_boundary", {}).get(
            "required_authorization"
        )
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.3 response-contract amendment identity differs",
    )
    _require(
        output_schemas.get("schema") == "trimem/provider-output-schemas/1.0"
        and schema_lock.get("schema") == "trimem/provider-output-schema-lock/1.0"
        and schema_lock.get("config_sha256")
        == hashlib.sha256(raw[PROVIDER_OUTPUT_SCHEMAS_PATH]).hexdigest(),
        "D1.3 provider output schema lock differs",
    )

    _require(
        gh_lock.get("schema") == "trimem/gh-cli-lock/1.0"
        and gh_lock.get("version") == "2.97.0"
        and gh_lock.get("platform") == "linux_amd64"
        and gh_lock.get("expected_first_version_line")
        == "gh version 2.97.0 (2026-07-31)"
        and gh_lock.get("archive_sha256")
        == "a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112"
        and gh_lock.get("extracted_gh_binary_sha256")
        == "141507c337e8b202ad398550c3b73d72f5af92e86f71665214538a81efd4c409",
        "D1.2 pinned GitHub CLI lock differs",
    )

    _require(
        toolchain_amendment.get("schema")
        == "trimem/development-runner-toolchain-amendment/1.0"
        and toolchain_amendment.get("status")
        == "AUTHORIZED_CONDITIONAL_ON_EXACT_REMOTE_GATES"
        and toolchain_amendment.get("amendment", {}).get("classification")
        == "NON_SEMANTIC_RUNNER_TOOLCHAIN_DEPENDENCY_FIX"
        and toolchain_amendment.get("amendment", {}).get("method_amendment")
        is False
        and toolchain_amendment.get("source_git_head")
        == "c0b8b862ee50515a9a83506233646f6362f0c091"
        and toolchain_amendment.get("source_freeze_raw_sha256")
        == "e6d343266d58ecca6a85c28f8d0d3bc089fb793ce5e8f76dca7a04dc03b29d90",
        "D1.2 runner-toolchain amendment identity differs",
    )
    recovery_boundary = toolchain_amendment.get("authorization_boundary", {})
    _require(
        recovery_boundary.get("authorization") == D12_RECOVERY_AUTHORIZATION
        and recovery_boundary.get("prior_request_final")
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_002"
        and recovery_boundary.get("prior_run_attempt_final") == "33739545314/1"
        and recovery_boundary.get("prior_run_rerun_allowed") is False
        and recovery_boundary.get("new_request_allowed_after_conditions")
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_003",
        "D1.2 conditional recovery authority differs",
    )
    causal_boundary = toolchain_amendment.get("causal_boundary", {})
    _require(
        causal_boundary.get("scientific_status") == "NOT_STARTED"
        and causal_boundary.get("benchmark_model_results_observed") is False
        and all(
            causal_boundary.get(field) == 0
            for field in (
                "api_calls",
                "grader_containers",
                "input_tokens",
                "model_calls",
                "official_grader_runs",
                "output_tokens",
                "paid_model_calls",
                "target_image_pulls",
                "task_arm_runs",
                "total_usd",
            )
        ),
        "D1.2 causal boundary is not zero before scientific execution",
    )
    d12_preserved = toolchain_amendment.get("preserved_contracts", {}).get(
        "path_sha256"
    )
    _require(
        d12_preserved == EXPECTED_D12_PRESERVED_SHA256,
        "D1.2 preserved-contract map differs",
    )
    for path, expected_sha256 in d12_preserved.items():
        _require(
            isinstance(path, str)
            and isinstance(expected_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
            "D1.2 preserved-contract map is malformed",
        )
        if path not in D13_MUTABLE_PRESERVED_CONTRACT_PATHS:
            _require(
                hashlib.sha256(_commit_bytes(repository, commit, path)).hexdigest()
                == expected_sha256,
                f"D1.3 changed a contract outside its authorized scope: {path}",
            )

    _require(
        environment
        == {
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
            "repository": EXPECTED_REPOSITORY,
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
        },
        "benchmark protected environment snapshot differs",
    )

    _require(
        amendment.get("schema") == "trimem/development-model-pricing-amendment/1.0"
        and amendment.get("status")
        == "FROZEN_PRE_EXECUTION_PENDING_SEPARATE_DEVELOPMENT_APPROVAL",
        "Mini model/pricing amendment is not frozen pre-execution",
    )
    _require(
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
        "Mini amendment causal boundary drifted",
    )
    preserved = amendment.get("preserved_contracts", {}).get("path_sha256")
    _require(isinstance(preserved, dict) and bool(preserved), "preserved contract map is missing")
    for path, expected_sha256 in preserved.items():
        _require(
            isinstance(path, str)
            and isinstance(expected_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
            "preserved contract map is malformed",
        )
        if path not in D13_MUTABLE_PRESERVED_CONTRACT_PATHS:
            committed = _commit_bytes(repository, commit, path)
            _require(
                hashlib.sha256(committed).hexdigest() == expected_sha256,
                f"D1.3 changed a contract outside its authorized scope: {path}",
            )

    primary = model.get("primary_model")
    roles = model.get("model_roles")
    decoding = model.get("decoding_contract")
    _require(isinstance(primary, dict), "primary model lock is missing")
    _require(isinstance(roles, dict), "model role lock is missing")
    _require(isinstance(decoding, dict), "model decoding lock is missing")
    _require(primary.get("provider") == "openai", "DEV provider is not OpenAI")
    _require(
        primary.get("model_id") == EXACT_MODEL["model_id"],
        "DEV exact model ID drifted",
    )
    _require(
        primary.get("input_price_per_million_tokens_usd") == 0.75
        and primary.get("cached_input_price_per_million_tokens_usd") == 0.075
        and primary.get("output_price_per_million_tokens_usd") == 4.5,
        "DEV model pricing drifted",
    )
    _require(
        cost.get("model_pricing", {}).get("model_id") == EXACT_MODEL["model_id"]
        and cost.get("model_pricing", {}).get("input_per_million_tokens_usd") == 0.75
        and cost.get("model_pricing", {}).get("cached_input_per_million_tokens_usd") == 0.075
        and cost.get("model_pricing", {}).get("output_per_million_tokens_usd") == 4.5,
        "DEV cost-plan model or pricing drifted",
    )
    _require(
        decoding.get("reasoning_effort") == "medium"
        and decoding.get("temperature") == "OMITTED_FOR_REASONING_MODEL"
        and decoding.get("top_p") == "OMITTED_FOR_REASONING_MODEL",
        "DEV decoding contract drifted",
    )
    _require(
        set(roles) == {"decomposition", "solve", "experience_extraction"}
        and all(
            isinstance(roles.get(role), dict)
            and roles[role].get("model_id") == EXACT_MODEL["model_id"]
            for role in ("decomposition", "solve", "experience_extraction")
        ),
        "decomposition, solve, and extraction must share the exact Mini snapshot",
    )
    _require(
        model.get("request_schema_sha256")
        == EXACT_MODEL["request_schema_sha256"]
        and model.get("request_schema", {}).get("body", {}).get("model")
        == EXACT_MODEL["model_id"]
        and model.get("provider_bridge", {}).get("exact_returned_model_required")
        == EXACT_MODEL["model_id"],
        "DEV model request or returned-model gate drifted",
    )

    hard = cost.get("phase_hard_caps", {}).get(EXPECTED_PHASE)
    expected = cost.get("expected_cost", {}).get("phase_totals", {}).get(EXPECTED_PHASE)
    _require(isinstance(hard, dict), "DEV hard-cap material is missing")
    _require(isinstance(expected, dict), "DEV expected-cost material is missing")
    _require(hard == HARD_CAPS, "DEV hard-cap dictionary drifted")
    for field in ("input_tokens", "model_calls", "output_tokens", "task_arm_runs", "total_usd"):
        expected_value = EXPECTED_EXPENDITURE.get(field, SCIENTIFIC_WORKLOAD.get(field))
        _require(expected.get(field) == expected_value, f"DEV expected cost drifted: {field}")
    counts = cost.get("run_counts")
    _require(
        isinstance(counts, dict)
        and counts.get("development_unique_instances") == 12
        and counts.get("development_m2_candidate_runs") == 48
        and counts.get("development_m0_m1_runs_after_selection") == 24
        and counts.get("development_physical_task_arm_runs") == 72,
        "DEV run-count contract drifted",
    )
    actual = cost.get("actual_to_date")
    _require(isinstance(actual, dict), "historical accounting is missing")
    _require(
        actual.get("api_calls") == 1
        and actual.get("decomposition_calls") == 1
        and actual.get("model_calls") == 1
        and actual.get("model_gateway_calls") == 1
        and actual.get("paid_model_calls") == 1
        and actual.get("input_tokens") is None
        and actual.get("output_tokens") is None
        and actual.get("reasoning_tokens") is None
        and actual.get("provider_reported_usage")
        == "UNAVAILABLE_DUE_TO_ADAPTER_OBSERVABILITY_GAP"
        and actual.get("ledger_reservation")
        == {
            "input_tokens": 5069,
            "output_tokens": 2048,
            "total_usd": 0.01301775,
        },
        "historical DEV provider usage/reservation boundary drifted",
    )
    for field in ("extraction_calls", "solve_calls", "task_arm_runs"):
        _require(actual.get(field) == 0, f"pre-fresh-DEV actual {field} is not zero")
    _require(
        actual.get("grader_containers") == 18
        and actual.get("official_grader_runs") == 18,
        "immutable grader-smoke execution history drifted",
    )

    phases = {
        row.get("phase"): row
        for row in policy.get("phases", ())
        if isinstance(row, dict)
    }
    _require(
        policy.get("approval_state") == "PENDING_EXEC_APPROVAL"
        and phases.get(EXPECTED_PHASE)
        == {
            "phase": EXPECTED_PHASE,
            "status": "PENDING_EXEC_APPROVAL",
            "workflow": WORKFLOW_PATH,
        },
        "DEV policy request is not exact and pending",
    )

    targets = manifest.get("targets")
    _require(
        manifest.get("schema") == "trimem/development-manifest/1.0"
        and manifest.get("status") == "FROZEN"
        and manifest.get("ordered_stream") is True
        and isinstance(targets, list)
        and len(targets) == 12,
        "development manifest is not the frozen ordered 12-target set",
    )
    target_ids = [row.get("target_id") for row in targets if isinstance(row, dict)]
    _require(
        len(target_ids) == 12
        and len(set(target_ids)) == 12
        and [row.get("order_index") for row in targets] == list(range(12)),
        "development target identities or order drifted",
    )
    target_set_sha256 = hashlib.sha256(canonical_bytes(targets)).hexdigest()
    _require(
        manifest.get("target_set_sha256")
        == target_set_sha256
        == EXPECTED_TARGET_SET_SHA256,
        "development target-set hash drifted",
    )
    sequence_rows = [
        {
            key: row[key]
            for key in (
                "target_id",
                "instance_id",
                "benchmark_id",
                "dataset_revision",
                "source_row_sha256",
                "base_commit",
                "order_index",
            )
        }
        for row in targets
    ]
    execution_sequence_sha256 = hashlib.sha256(
        canonical_bytes(sequence_rows)
    ).hexdigest()
    _require(
        execution_sequence_sha256 == EXPECTED_EXECUTION_SEQUENCE_SHA256,
        "development execution sequence drifted",
    )
    benchmark_counts = {
        name: sum(row.get("benchmark_id") == name for row in targets)
        for name in (
            "swebench_verified",
            "multi_swe_bench_mini",
            "multi_swe_bench_flash",
        )
    }
    _require(
        benchmark_counts == {
            "swebench_verified": 4,
            "multi_swe_bench_mini": 4,
            "multi_swe_bench_flash": 4,
        },
        "development repository-stratified benchmark counts drifted",
    )

    candidate_rows = candidates.get("candidates")
    _require(
        candidates.get("status") == "FROZEN_BEFORE_DEVELOPMENT_RESULTS"
        and candidates.get("candidate_order")
        == ["baseline", "precision", "recall", "balanced"]
        and isinstance(candidate_rows, list)
        and [row.get("candidate_id") for row in candidate_rows]
        == ["baseline", "precision", "recall", "balanced"],
        "four frozen M2 candidate bundles drifted",
    )
    policy_references = [
        (candidates.get("base_policy_path"), candidates.get("base_policy_file_sha256")),
        *[
            (row.get("full_policy_path"), row.get("full_policy_file_sha256"))
            for row in candidate_rows
        ],
    ]
    for path, expected_sha256 in policy_references:
        _require(
            isinstance(path, str)
            and isinstance(expected_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is not None,
            "M2 policy reference is malformed",
        )
        _require(
            hashlib.sha256(_commit_bytes(repository, commit, path)).hexdigest()
            == expected_sha256,
            f"M2 policy file differs from its frozen manifest: {path}",
        )
    selection_order = candidates.get("development_contract", {}).get(
        "selection_order"
    )
    _require(
        selection_order
        == [
            "resolved_count descending",
            "actual_total_tokens ascending",
            "actual_usd ascending",
            "candidate_id ascending",
        ],
        "M2 deterministic selection order drifted",
    )
    development_rule = selection.get("development_rule")
    _require(
        selection.get("status") == "FROZEN_BEFORE_MODEL_OR_GRADER_RESULTS"
        and isinstance(development_rule, dict)
        and development_rule.get("count_per_benchmark")
        == {
            "swebench_verified": 4,
            "multi_swe_bench_mini": 4,
            "multi_swe_bench_flash": 4,
        },
        "development selection plan drifted",
    )
    _require(
        grader.get("status") == "FROZEN_PRE_EXEC_EXECUTION_PENDING_APPROVAL"
        and grader.get("official_grader_execution") == "PENDING_EXEC_APPROVAL",
        "official grader lock is not frozen and pending",
    )
    locked_targets = images.get("benchmark_target_images", {}).get("targets")
    locked_ids = {
        row.get("target_id") for row in locked_targets or () if isinstance(row, dict)
    }
    _require(
        images.get("status") == "FROZEN"
        and images.get("official_grader_execution") == "PENDING_EXEC_APPROVAL"
        and set(target_ids) <= locked_ids,
        "development image lock is incomplete or not pending",
    )

    freeze_files = freeze.get("files")
    _require(
        freeze.get("schema") == "trimem/freeze/1.0"
        and freeze.get("hash_algorithm") == "sha256"
        and freeze.get("path_policy")
        == (
            "explicit_allowlist_plus_hash_bound_event_blob_references_plus_"
            "conditional_probe_evidence_triad_no_tree_walk"
        )
        and isinstance(freeze_files, dict),
        "research freeze is malformed",
    )
    _require(SENTINEL_PATH not in freeze_files, "post-freeze DEV sentinel entered the source freeze")
    for path, entry in freeze_files.items():
        _require(
            isinstance(path, str)
            and path
            and not Path(path).is_absolute()
            and ".." not in Path(path).parts,
            "research freeze contains an unsafe path",
        )
        committed = _commit_bytes(repository, commit, path)
        _require(
            entry
            == {"bytes": len(committed), "sha256": hashlib.sha256(committed).hexdigest()},
            f"research freeze full inventory mismatch: {path}",
        )
    for path in FREEZE_CLOSURE_PATHS:
        committed = raw[path]
        _require(
            freeze_files.get(path)
            == {"bytes": len(committed), "sha256": hashlib.sha256(committed).hexdigest()},
            f"research freeze closure mismatch: {path}",
        )
    bindings = {
        field: sha256_prefixed(raw[path]) for field, path in BOUND_PATHS.items()
    }
    workload = {
        **SCIENTIFIC_WORKLOAD,
        "candidate_selection_order": selection_order,
        "execution_sequence_sha256": execution_sequence_sha256,
        "stream_order": [
            "M2-baseline",
            "M2-precision",
            "M2-recall",
            "M2-balanced",
            "M0",
            "M1",
        ],
        "target_order": target_ids,
        "target_set_sha256": target_set_sha256,
    }
    return raw, bindings, workload


def build_request_document(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    material_commit: str | None = None,
) -> dict[str, Any]:
    _require(HEX40.fullmatch(source_head) is not None, "source_head is not a commit SHA")
    commit = source_head if material_commit is None else material_commit
    _require(HEX40.fullmatch(commit) is not None, "material commit is not a commit SHA")
    _raw, bindings, workload = _validate_frozen_material(repository, commit)
    verified_remote_gates = _validate_remote_gate_evidence(
        remote_gate_evidence, source_head=source_head
    )
    payload: dict[str, Any] = {
        "actual_execution_authorized": False,
        "amendment_classification": "PRE_RESULT_PROVIDER_OUTPUT_CONTRACT_AMENDMENT",
        "authorization_semantics": AUTHORIZATION_SEMANTICS,
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "exact_model": deepcopy(EXACT_MODEL),
        "expected_expenditure": deepcopy(EXPECTED_EXPENDITURE),
        "grader_smoke_rerun_authorized": False,
        "hard_caps": deepcopy(HARD_CAPS),
        "heldout_execution_authorized": False,
        "model_secret_required": True,
        "one_time_workflow_run_attempt": 1,
        "phase": EXPECTED_PHASE,
        "pre_execution_actuals": deepcopy(PRE_EXECUTION_ACTUALS),
        "prohibited_actions": list(PROHIBITED_ACTIONS),
        "recovery_provenance": deepcopy(RECOVERY_PROVENANCE),
        "remote_gate_evidence": verified_remote_gates,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "required_external_approval_fields": list(DEVELOPMENT_APPROVAL_FIELDS),
        "required_external_authorization": REQUIRED_EXTERNAL_AUTHORIZATION,
        "requires_external_approval": True,
        "schema": REQUEST_SCHEMA,
        "scientific_workload": workload,
        "source_head": source_head,
        "workflow_path": WORKFLOW_PATH,
    }
    return {
        **payload,
        "request_sha256": sha256_prefixed(canonical_bytes(payload)),
    }


def validate_request_document(
    repository: Path,
    raw: bytes,
    *,
    expected_source_head: str,
    material_commit: str | None = None,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    value = strict_json_object(raw)
    _require(set(value) == REQUEST_FIELDS, "DEV request field set is not exact")
    _require(value.get("schema") == REQUEST_SCHEMA, "DEV request schema mismatch")
    _require(value.get("request_id") == REQUEST_ID, "DEV request identity mismatch")
    _require(value.get("phase") == EXPECTED_PHASE, "request phase is not DEVELOPMENT_TUNING")
    _require(value.get("source_head") == expected_source_head, "DEV request source_head mismatch")
    _require(value.get("request_path") == SENTINEL_PATH, "DEV request path mismatch")
    _require(value.get("branch_ref") == EXPECTED_REF, "DEV request branch mismatch")
    _require(value.get("workflow_path") == WORKFLOW_PATH, "DEV workflow path mismatch")
    _require(value.get("requires_external_approval") is True, "DEV request must require external approval")
    _require(value.get("actual_execution_authorized") is False, "sentinel alone must have zero execution authority")
    expected = build_request_document(
        repository,
        source_head=expected_source_head,
        remote_gate_evidence=_validate_remote_gate_evidence(
            value.get("remote_gate_evidence"), source_head=expected_source_head
        ),
        material_commit=material_commit,
    )
    _require(value == expected, "DEV request content differs from the frozen contract")
    _require(
        isinstance(value.get("request_sha256"), str)
        and SHA256.fullmatch(value["request_sha256"]) is not None,
        "DEV request payload hash is invalid",
    )
    _require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "DEV request bytes or scalar types differ from the exact canonical contract",
    )
    return value


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    _require(HEX40.fullmatch(after) is not None, "trigger commit SHA is invalid")
    top = str(_run_git(repository, "rev-parse", "--show-toplevel")).strip()
    _require(Path(top).resolve() == repository, "repository is not the Git top level")
    if require_checked_out_head:
        head = str(_run_git(repository, "rev-parse", "HEAD")).strip()
        _require(head == after, "checked-out HEAD differs from the trigger commit")
    parents = str(
        _run_git(repository, "rev-list", "--parents", "-n", "1", after)
    ).strip().split()
    _require(len(parents) == 2 and parents[0] == after, "trigger must have exactly one parent")
    parent = parents[1]
    if expected_parent is not None:
        _require(parent == expected_parent, "trigger parent differs from push before SHA")
    changes = str(
        _run_git(
            repository,
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            after,
        )
    ).splitlines()
    _require(changes == [f"A\t{SENTINEL_PATH}"], "trigger commit must add only the exact DEV sentinel")
    history = str(
        _run_git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH)
    ).strip()
    _require(not history, "DEV sentinel already exists in branch history")
    tree = str(_run_git(repository, "ls-tree", after, "--", SENTINEL_PATH)).strip()
    _require(
        re.fullmatch(rf"100644 blob [0-9a-f]{{40}}\t{re.escape(SENTINEL_PATH)}", tree)
        is not None,
        "DEV sentinel must be a regular non-executable Git blob",
    )
    request_raw = _commit_bytes(repository, after, SENTINEL_PATH)
    request = strict_json_object(request_raw)
    _require(request.get("source_head") == parent, "sentinel source_head is not its sole parent")
    return validate_request_document(
        repository,
        request_raw,
        expected_source_head=parent,
        material_commit=after,
    )


def _validate_event_shape(
    event: Mapping[str, Any], environ: Mapping[str, str]
) -> tuple[str, str]:
    _require(environ.get("GITHUB_EVENT_NAME") == EXPECTED_EVENT, "event is not push")
    _require(
        environ.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY,
        "GITHUB_REPOSITORY is not the frozen repository",
    )
    _require(environ.get("GITHUB_RUN_ATTEMPT") == "1", "DEV trigger forbids a rerun attempt")
    _require(environ.get("GITHUB_REF") == EXPECTED_REF, "GITHUB_REF is not the frozen branch")
    _require(event.get("ref") == EXPECTED_REF, "push ref is not the frozen branch")
    _require(
        isinstance(event.get("repository"), dict)
        and event["repository"].get("full_name") == EXPECTED_REPOSITORY,
        "push repository identity differs",
    )
    _require(event.get("created") is False, "branch-creation pushes are forbidden")
    _require(event.get("deleted") is False, "branch-deletion pushes are forbidden")
    _require(event.get("forced") is False, "forced pushes are forbidden")
    before, after = event.get("before"), event.get("after")
    _require(isinstance(before, str) and HEX40.fullmatch(before) is not None, "push before SHA is invalid")
    _require(isinstance(after, str) and HEX40.fullmatch(after) is not None, "push after SHA is invalid")
    _require(environ.get("GITHUB_SHA") == after, "GITHUB_SHA differs from push after SHA")
    _require(
        environ.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF,
        "GITHUB_WORKFLOW_REF is not the exact branch-local benchmark workflow",
    )
    _require(
        environ.get("GITHUB_WORKFLOW_SHA") == after,
        "GITHUB_WORKFLOW_SHA differs from the trigger commit",
    )
    _require(before != after, "push before and after SHAs must differ")
    return before, after


def _validate_secret_free_preflight(
    repository: Path, commit: str, environ: Mapping[str, str]
) -> None:
    exposed = sorted(name for name in FORBIDDEN_PREFLIGHT_SECRETS if name in environ)
    _require(not exposed, f"execution secret is exposed to DEV preflight: {exposed}")
    try:
        workflow = _commit_bytes(repository, commit, WORKFLOW_PATH).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError("benchmark workflow is not UTF-8") from exc
    trigger_start = workflow.find("on:\n")
    concurrency_start = workflow.find("\nconcurrency:", trigger_start + 3)
    _require(
        trigger_start >= 0 and concurrency_start > trigger_start,
        "benchmark workflow has no bounded trigger block",
    )
    trigger_block = workflow[trigger_start + len("on:\n") : concurrency_start]
    expected_trigger_block = (
        "  workflow_dispatch:\n"
        "  push:\n"
        "    branches:\n"
        "      - codex/trimem-coder-v1\n"
        "    paths:\n"
        f"      - {SENTINEL_PATH}\n"
    )
    _require(
        trigger_block == expected_trigger_block
        and f"group: {EXPECTED_CONCURRENCY_GROUP}" in workflow
        and "group: trimem-v1-development-tuning-exec-001" not in workflow
        and "group: trimem-v1-development-tuning-exec-002" not in workflow
        and "cancel-in-progress: false" in workflow,
        "benchmark workflow trigger or recovery concurrency identity differs",
    )
    start = workflow.find("  branch-trigger-preflight:")
    end = workflow.find("  frozen-serial-phase:")
    _require(0 <= start < end, "workflow has no isolated branch preflight job")
    preflight = workflow[start:end]
    _require(
        preflight.count(
            "python -I -S scripts/trimem_freeze.py --check --require-git-tracked"
        )
        == 1
        and preflight.count(
            "python -I -S scripts/trimem_development_trigger_preflight.py"
        )
        == 1,
        "branch preflight is not the exact isolated base-Python pair",
    )
    forbidden = (
        "secrets.",
        "environment:",
        "OPENAI_API_KEY",
        "TRIMEM_EXEC_APPROVAL_B64",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "services:",
        "container:",
        "docker ",
        "trimem_benchmark_run.py",
        "trimem_official_grader",
        "trimem_pull_locked_images.py",
        "api.openai.com",
    )
    _require(
        not any(token in preflight for token in forbidden),
        "branch preflight references a secret, environment, or Docker",
    )


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    event = strict_json_object(event_path.resolve(strict=True).read_bytes())
    environment = os.environ if environ is None else environ
    before, after = _validate_event_shape(event, environment)
    _validate_secret_free_preflight(repository, after, environment)
    request = validate_sentinel_commit(
        repository,
        after,
        expected_parent=before,
    )
    live_remote_gates = collect_remote_gate_evidence(before)
    _require(
        request["remote_gate_evidence"]["workflows"]
        == live_remote_gates["workflows"],
        "embedded remote gates differ from the live exact-head GitHub runs",
    )
    request_raw = _commit_bytes(repository, after, SENTINEL_PATH)
    return {
        "actual_execution_authorized": False,
        "approved_freeze_sha256": request["bindings"]["freeze_sha256"],
        "approved_request_raw_sha256": sha256_prefixed(request_raw),
        "approved_grader_container_cap": 72,
        "approved_task_arm_run_count": 72,
        "grader_containers": 0,
        "model_calls": 0,
        "paid_model_calls": 0,
        "phase": EXPECTED_PHASE,
        "request_id": REQUEST_ID,
        "request_payload_sha256": request["request_sha256"],
        "remote_gate_evidence_sha256": sha256_prefixed(
            canonical_bytes(request["remote_gate_evidence"])
        ),
        "remote_gate_workflow_runs": {
            row["workflow_path"]: row["run_id"]
            for row in request["remote_gate_evidence"]["workflows"]
        },
        "requires_external_approval": True,
        "source_head": before,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
        "trigger_commit": after,
    }


def write_request(repository: Path) -> dict[str, Any]:
    """Create the one sentinel exclusively from a clean, committed source HEAD."""

    repository = repository.resolve(strict=True)
    top = str(_run_git(repository, "rev-parse", "--show-toplevel")).strip()
    _require(Path(top).resolve() == repository, "repository is not the Git top level")
    ref = str(_run_git(repository, "symbolic-ref", "--quiet", "HEAD")).strip()
    _require(ref == EXPECTED_REF, "DEV request may be written only on the frozen branch")
    source_head = str(_run_git(repository, "rev-parse", "HEAD")).strip()
    status = str(
        _run_git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    )
    _require(not status, "DEV request rendering requires a clean worktree")
    history = str(
        _run_git(repository, "log", "--format=%H", "HEAD", "--", SENTINEL_PATH)
    ).strip()
    _require(not history, "DEV sentinel already exists in branch history")
    target = repository / SENTINEL_PATH
    _require(not target.exists() and not target.is_symlink(), "DEV sentinel path already exists")
    remote_gate_evidence = collect_remote_gate_evidence(source_head)
    document = build_request_document(
        repository,
        source_head=source_head,
        remote_gate_evidence=remote_gate_evidence,
    )
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise DevelopmentTriggerError("refusing to overwrite the DEV sentinel") from exc
    return {
        "bytes": len(raw),
        "path": SENTINEL_PATH,
        "request_id": REQUEST_ID,
        "remote_gate_evidence_sha256": sha256_prefixed(
            canonical_bytes(remote_gate_evidence)
        ),
        "remote_gate_workflow_runs": {
            row["workflow_path"]: row["run_id"]
            for row in remote_gate_evidence["workflows"]
        },
        "sentinel_bytes_sha256": sha256_prefixed(raw),
        "source_head": source_head,
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--event-path", type=Path)
    mode.add_argument("--write-request", action="store_true")
    args = parser.parse_args()
    try:
        if args.write_request:
            report = write_request(args.repository)
        else:
            assert args.event_path is not None
            report = validate_branch_trigger(args.repository, args.event_path)
    except (OSError, DevelopmentTriggerError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL_CLOSED"}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
