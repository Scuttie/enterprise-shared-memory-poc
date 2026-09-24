"""Fail-closed one-time DEVELOPMENT_TUNING `_009` terminal-contract trigger.

The correction source is deliberately validated before the sentinel exists.
Only a later, single-file commit may add the zero-authority `_009` request and
activate the protected workflow.  Historical `_008` parsing remains owned by
``trimem_development_trigger_d15.py`` and is never selected by this reader.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trimem_development_trigger_preflight import collect_remote_gate_evidence


EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_REF = "refs/heads/codex/trimem-coder-v1"
EXPECTED_WORKFLOW_REF = (
    "Scuttie/enterprise-shared-memory-poc/.github/workflows/"
    "trimem-benchmark.yml@refs/heads/codex/trimem-coder-v1"
)
EXPECTED_PHASE = "DEVELOPMENT_TUNING"
REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_009"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.8"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_009.json"
)
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_008.json"
)
PREVIOUS_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-008/"
    "terminal-status-contract-mismatch-receipt.json"
)
PREVIOUS_REPORT_PATH = (
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_008_"
    "TERMINAL_STATUS_CONTRACT_MISMATCH.md"
)
AMENDMENT_PATH = "artifacts/trimem_v1/development_terminal_contract_amendment.json"
AMENDMENT_SCHEMA = "trimem/development-terminal-contract-amendment/1.0"
AMENDMENT_CLASSIFICATION = "NON_SEMANTIC_SCIENTIFIC_TERMINAL_CONTRACT_FIX"
AMENDMENT_STATUS = "FROZEN_PRE_RESULT_PENDING_FRESH_EXECUTION"
INVENTORY_PATH = "artifacts/trimem_v1/development_terminal_contract_inventory.json"
INVENTORY_SCHEMA = "trimem/development-terminal-contract-inventory/1.0"
INVENTORY_STATUS = "FROZEN_PRE_RESULT_PENDING_FRESH_EXECUTION"
INVENTORY_CONTRACT_TABLE_SHA256 = (
    "2f74cf1799852469ab160ff3ac2b444b8a80057bdeb85c575125a869cdd90bd8"
)
INVENTORY_CONTRACT_FIELDS = {
    "execution_status",
    "cell_status",
    "task-arm ledger status",
    "model-request ledger status",
    "grader_status",
    "grader_exit_code",
    "official_grader",
    "resolved",
    "container_started",
    "grader_patch_source",
    "extraction_status",
    "model_failure_class",
    "agent_completed",
    "task-arm identity",
    "actual_accounting projection",
    "scientific_terminal_contract projection",
    "grader-smoke execution_status",
}
FINALIZATION_EXTERNAL_BINDINGS = {
    "final_correction_source_head": "BOUND_EXTERNALLY_AS_009_SOURCE_HEAD",
    "final_research_freeze_sha256": "BOUND_EXTERNALLY_BY_009_FREEZE_SHA256",
    "development_tuning_exec_request_009_sha256": (
        "NOT_CREATED_UNTIL_EXACT_HEAD_REMOTE_GATES_PASS"
    ),
    "exact_head_remote_ci_evidence": "BOUND_EXTERNALLY_IN_009_REMOTE_GATE_EVIDENCE",
}
FINALIZATION_SAFE_HASH_PATHS = {
    "final_terminal_contract_sha256": (
        "src/enterprise_memory/trimem/scientific_terminal.py"
    ),
    "final_runner_sha256": "scripts/trimem_benchmark_run.py",
    "final_aggregate_sha256": "scripts/trimem_benchmark_matrix.py",
    "final_workflow_sha256": ".github/workflows/trimem-benchmark.yml",
    "final_d1_8_integration_test_sha256": (
        "tests/unit/test_trimem_d18_terminal_contract_integration.py"
    ),
    "final_credential_free_e2e_bundle_sha256": (
        "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
    ),
    "final_company_handoff_inventory_sha256": "COMPANY_HANDOFF_MANIFEST.json",
}
REQUIRED_SEMANTIC_SCOPE_LOCKS = {
    "model",
    "reasoning_effort",
    "prompt_text",
    "native_function_tools",
    "tool_schemas",
    "tool_choice",
    "parallel_tool_calls",
    "parser_behavior",
    "output_token_limits",
    "cell_containment_policy",
    "canonical_noop_patch",
    "partial_patch_grading",
    "task_order",
    "target_identities",
    "benchmark_roles",
    "m2_candidates",
    "selection_rule",
    "memory_retrieval_ppr_dqn_parameters",
    "grader_implementation",
    "image_digests",
    "phase_hard_cap_values",
}
PROTECTED_OFFICIAL_GRADER_STATUSES = {
    "adapter_contract_failed",
    "adapter_evidence_capture_failed",
    "adapter_evidence_finalization_failed",
    "harness_exit_nonzero",
    "harness_launch_failed",
    "harness_timeout",
    "image_digest_mismatch",
    "image_inspect_failed",
    "image_inspect_invalid",
    "image_inspect_launch_failed",
    "image_inspect_timeout",
    "image_stream_capture_failed",
    "image_tag_failed",
    "image_tag_launch_failed",
    "image_tag_timeout",
    "input_materialization_failed",
    "invalid_report",
    "materialized_patch_invalid",
    "missing_report",
    "private_input_purge_failed",
    "report_exit_nonzero",
    "report_launch_failed",
    "report_schema_mismatch",
    "report_timeout",
    "stale_test_evidence",
    "success",
    "test_evidence_invalid",
}
ALL_GRADE_RESULT_STATUSES = PROTECTED_OFFICIAL_GRADER_STATUSES | {
    "container_exit_nonzero",
    "container_launch_failed",
    "container_timeout",
}
PREVIOUS_SENTINEL_SHA256 = (
    "2eac68069e9a2cc760138eca5b9e6ae1d5438a97cd9e4918a496ab920cc584b7"
)
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "dc28e4b9c33eb5c16fe85d3750e29e3253e71ea40cfde375133b9e589f68d0f7"
)
PREVIOUS_SOURCE_HEAD = "f5f6b8d0c6bef4aa704e25d8e67c526d437e967b"
PREVIOUS_EXECUTION_HEAD = "8002847d0db8975dfd957a1322d31a7768fc098f"
PREVIOUS_RUN_ID = 33_944_405_409
PREVIOUS_FAILURE_SUBTYPE = (
    "TRIMEM_DEV_RUNNER_AGGREGATE_TERMINAL_STATUS_CONTRACT_MISMATCH"
)
FAILED_CORRECTION_SOURCE_GATE_EVIDENCE = {
    "classification": "NON_SCIENTIFIC_PRE_EXECUTION_SOURCE_GATE_FAILURE",
    "conclusion": "failure",
    "docker_calls": 0,
    "failure_label": "local validator historical/current compatibility",
    "failure_stage": "Verify required Git blobs and pinned control flow",
    "grader_runs": 0,
    "image_pulls": 0,
    "model_api_calls": 0,
    "paid_model_calls": 0,
    "performance_measured": False,
    "scientific_cells": 0,
    "scientific_result": False,
    "source_head": "ac290512ed9a097f61f170f241771d3f213f667d",
    "usd": 0,
    "workflow_path": ".github/workflows/ci-trimem-multi-swe-contract.yml",
    "workflow_run_attempt": 1,
    "workflow_run_id": 33_976_624_278,
}
MODEL_ID = "gpt-5.4-mini-2026-03-17"
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_TERMINAL_CONTRACT_RECOVERY_EXEC_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-009"
PREVIOUS_EXECUTION_ACCOUNTING = {
    "exact_model_metadata_control_plane_requests": 1,
    "canary_generation_calls": 1,
    "canary_model_generations": 1,
    "canary_paid_model_calls": 1,
    "canary_input_tokens": 880,
    "canary_cached_input_tokens": 0,
    "canary_output_tokens": 14,
    "canary_reasoning_tokens": 0,
    "canary_total_usd": "0.000723000000",
    "scientific_model_calls": 0,
    "scientific_task_arm_cells": 0,
    "scientific_terminal_cells": 0,
    "scientific_planned_cells": 72,
    "official_grader_runs": 0,
    "grader_containers": 0,
    "target_image_pulls": 12,
    "support_image_pulls": 1,
    "total_docker_image_pulls": 13,
    "model_id": MODEL_ID,
    "reasoning_effort": "medium",
}
REQUIRED_REMOTE_GATE_WORKFLOWS = (
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
)
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
    "approval_nonce",
    "approved_openai_key_commitment",
]

# These inputs are scientific-policy locks, not D1.8 implementation material.
# The correction source must preserve their exact pre-result values.
PRESERVED_SHA256 = {
    "artifacts/trimem_v1/grader_image_lock.json": (
        "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb"
    ),
    "configs/trimem_v1/arms.json": (
        "7ecc15277cc9a9041befd4ae32f99b65da63009383b22701e0aecb407fe3906c"
    ),
    "configs/trimem_v1/cost_plan.json": (
        "691489139bcd8d862d274a92fc9ffd26c605c54494cbed61f00ae940c05940f6"
    ),
    "configs/trimem_v1/development_manifest.json": (
        "44e52137dad68618396c15d6b3c2221a683f89988e361efb2966e244ba230900"
    ),
    "configs/trimem_v1/heldout_manifest.json": (
        "951371ed84931b37e27929e2669aff5d06e32215d1a300e3343ba7f1bdd84fda"
    ),
    "configs/trimem_v1/grader_lock.json": (
        "853d42e86c2caf1449f28bba9143741e3ccff5e75bbe790115a0d9c746014fbb"
    ),
    "configs/trimem_v1/m2_candidate_bundles.json": (
        "9383f70c021730a2901bd1de8e69b98082895bdaad25fe6483bfdc58a8047e68"
    ),
    "configs/trimem_v1/model_lock.json": (
        "a0a4811590d396c2bea4f0454c18c912d11579858947540a355407009a975922"
    ),
    "configs/trimem_v1/provider_output_schemas.json": (
        "2cdb1d62972776b492ee178801a91610bccadb97d9e67eb53c014ed1025562d1"
    ),
    "configs/trimem_v1/selection_plan.json": (
        "dddc421120d16f241a2941afbd67190df4b3be6cefeab99e37437abf7133dcf4"
    ),
    "configs/trimem_v1/tool_environment_lock.json": (
        "4d0ef738d99bbfab5c4a54abba61dd6e3b50ebf2953009cfd84a5e45c7a88a4e"
    ),
    "configs/trimem_v1/benchmark_environment_lock.json": (
        "6636350aca389c16eb64f92465f7529ae06208ed5a8c2ceaf1c9545a1c7e6e02"
    ),
    "configs/trimem_v1/benchmark_environment.lock": (
        "359b39abbc0dc07fa540b520c8ac1c6698bf3888a0f11f5eb59ee1f28f58691f"
    ),
    "configs/trimem_v1/m2_candidates/baseline.json": (
        "f18fcc305e4d936d2337c6eca08ba1bfbb07e5ae6200f10737c11a7d5d2bc6dd"
    ),
    "configs/trimem_v1/m2_candidates/precision.json": (
        "1c9ea64e16986e1c93a26a5a62428dbc7fd3497d179d84fb194ff90af2eb26b5"
    ),
    "configs/trimem_v1/m2_candidates/recall.json": (
        "1985ca2cceaa6ebdc02d4bd320b318a47a8144f64bde5ad0da8367c777d3d85c"
    ),
    "configs/trimem_v1/m2_candidates/balanced.json": (
        "e0474d88505c0a75ff21914f552b71f9796274bd4939e92b299aaf75d0ab4b2d"
    ),
    "artifacts/trimem_v1/provider_output_schema_lock.json": (
        "fbc63a5a508fc30a6bd2e30ba1a6389cc456d5f37f30f95ff61dd1e5d93b4589"
    ),
    "artifacts/trimem_v1/solve_output_budget_contract_lock.json": (
        "81242a4a1aac4f8e74a1ca887718e976da1cc8bea5e0a7cf773ea21800364949"
    ),
    "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json": (
        "ccd0fe37f7813a5316f2c963cfa5796c7e25a3b7534ca941f6a90db5613ecad5"
    ),
    "artifacts/trimem_v1/multi_swe_report_semantics_lock.json": (
        "620618f967ef5e33037fccc123fcf004f63bbe656efeb61c46e85f764ef9c80e"
    ),
    "scripts/trimem_action_canary.py": (
        "542158dccbfb523063dc939eb44be217994cb8735a93bff6c5f510fe7f669320"
    ),
    "scripts/trimem_official_grader.py": (
        "fbd15718a88b4d733b313af83889aae8ef6ac7837529bba52f0bb4072f57b886"
    ),
    "scripts/trimem_exec_approval.py": (
        "76a7b77603aba83e0d7f39c300fd04c40a568442b1a1d294642066b2f085e3d4"
    ),
    "scripts/trimem_harness_lock.py": (
        "0667d68151f8d0ec82d06358132f0221d336769d057aa63dc6612baed2af6d0a"
    ),
    "scripts/trimem_m2_candidates.py": (
        "b5fd61cc320f129b2ee1eb8dc7de632bafe01f5ee539e673f0966ac35c1e860a"
    ),
    "scripts/trimem_run_with_resume.py": (
        "59f0d0a1dcfa72adfa96cd143d704fde9e8c74ad3cea49fbbe16c44c9d6b4a6d"
    ),
    "src/enterprise_memory/providers/base.py": (
        "657c1d76dcebb1b9bad8489e06a69d8bbb8bea3786b55a3f5b2b3c3c018c4f51"
    ),
    "src/enterprise_memory/providers/openai_responses.py": (
        "417693dd05414ecb98ba6d13dc1d03e2a9abc312befc9e5ebb211babf54ff34e"
    ),
    "src/enterprise_memory/trimem/function_tools.py": (
        "2776fc926e7e6995c2002849ec51ba27b784fe62346dc7b76a57ac6d6e910ae6"
    ),
    "src/enterprise_memory/trimem/grader.py": (
        "4746bac3f6530f7c82dd18c0433c1acc206c6d5732a216007ded732cc0359719"
    ),
    "src/enterprise_memory/trimem/arms.py": (
        "7fa3285fa52d3ad76c4ebaa19ce333f39921593597c315c815a7db0c01a88ce3"
    ),
    "src/enterprise_memory/trimem/gateway.py": (
        "aa3f65d52730239786b6047305bc7a5a4170a9becb5cf11e2a22621931c799eb"
    ),
    "src/enterprise_memory/trimem/git_workspace.py": (
        "f4e91c3ceddb4d2b149b0467351a97cafca88b71fcf903580c72c1788096b949"
    ),
    "src/enterprise_memory/trimem/provider_output_contracts.py": (
        "6b2e5711ae78057b7a29ce7424ad88e0c63e03e0051ac452dc96e67e4885f906"
    ),
    "src/enterprise_memory/trimem/agent_runtime.py": (
        "4098d7ac89efc82f3eff9e761f1dca234b176e074c6c4a692d6a899ab1ef66b8"
    ),
    "src/enterprise_memory/trimem/runtime_lock.py": (
        "c31bddb29153a79cfea46f05908150834dd178b3b0e29767c04c2755d29f505e"
    ),
    "src/enterprise_memory/trimem/workspace.py": (
        "d9048da6bf7ef31fdf6f646d3e4ace85133dc545eda3701d52caeabb8438630f"
    ),
}
HISTORICAL_D16_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_action_protocol_amendment.json"
)
HISTORICAL_D16_AMENDMENT_SHA256 = (
    "cadfc835138ddc8c76a870a45d10e7a6f1ed7bf386e0e7a9bad42c7a7745489e"
)
HISTORICAL_D17_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_approval_consumer_contract_fix.json"
)
HISTORICAL_D17_AMENDMENT_SHA256 = (
    "19964be25157269827e792a3144aaa52aae3267178a20a56adfe5373765d745a"
)

# The amendment may bind additional supporting files, but omitting any of
# these production/rehearsal paths is a fail-closed source error.
D18_REQUIRED_IMPLEMENTATION_PATHS = {
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/readiness_requirements.json",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_development_trigger_d18.py",
    "scripts/trimem_development_trigger_preflight.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_multi_swe_contract.py",
    "scripts/trimem_public_artifact.py",
    "scripts/trimem_verify_ready.py",
    "src/enterprise_memory/trimem/scientific_terminal.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_d16_native_action.py",
    "tests/unit/test_trimem_d17_approval_cap_integration.py",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_d18_terminal_contract_integration.py",
    "tests/unit/test_trimem_d18_public_artifact_hardening.py",
}

BOUND_PATHS = {
    "action_protocol_amendment_sha256": HISTORICAL_D16_AMENDMENT_PATH,
    "approval_consumer_contract_sha256": HISTORICAL_D17_AMENDMENT_PATH,
    "approval_schema_sha256": "scripts/trimem_exec_approval.py",
    "arms_sha256": "configs/trimem_v1/arms.json",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": ".github/workflows/trimem-benchmark.yml",
    "credential_free_static_workflow_sha256": ".github/workflows/ci-trimem.yml",
    "credential_free_toolchain_workflow_sha256": (
        ".github/workflows/ci-trimem-dev-toolchain.yml"
    ),
    "cost_plan_sha256": "configs/trimem_v1/cost_plan.json",
    "development_manifest_sha256": "configs/trimem_v1/development_manifest.json",
    "freeze_sha256": "artifacts/trimem_v1/freeze.json",
    "grader_lock_sha256": "configs/trimem_v1/grader_lock.json",
    "image_lock_sha256": "artifacts/trimem_v1/grader_image_lock.json",
    "m2_candidate_manifest_sha256": "configs/trimem_v1/m2_candidate_bundles.json",
    "model_lock_sha256": "configs/trimem_v1/model_lock.json",
    "previous_dev_receipt_sha256": PREVIOUS_RECEIPT_PATH,
    "previous_dev_report_sha256": PREVIOUS_REPORT_PATH,
    "previous_dev_request_sha256": PREVIOUS_SENTINEL_PATH,
    "public_artifact_sha256": "scripts/trimem_public_artifact.py",
    "readiness_requirements_sha256": (
        "artifacts/trimem_v1/readiness_requirements.json"
    ),
    "runner_agent_runtime_sha256": "src/enterprise_memory/trimem/agent_runtime.py",
    "scientific_terminal_contract_sha256": (
        "src/enterprise_memory/trimem/scientific_terminal.py"
    ),
    "selection_plan_sha256": "configs/trimem_v1/selection_plan.json",
    "terminal_contract_amendment_sha256": AMENDMENT_PATH,
    "terminal_contract_inventory_sha256": INVENTORY_PATH,
    "tool_environment_lock_sha256": "configs/trimem_v1/tool_environment_lock.json",
    "trigger_reader_sha256": "scripts/trimem_development_trigger_d18.py",
    "trigger_legacy_compatibility_sha256": (
        "scripts/trimem_development_trigger_preflight.py"
    ),
}
FREEZE_MEMBERSHIP_EXEMPT_PATHS = {
    "artifacts/trimem_v1/freeze.json",
    PREVIOUS_SENTINEL_PATH,
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class DevelopmentTriggerD18Error(ValueError):
    pass


# Stable consumer name used by the benchmark runner and aggregate.
DevelopmentTriggerError = DevelopmentTriggerD18Error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DevelopmentTriggerD18Error(message)


def canonical_bytes(value: Any, *, trailing_lf: bool = False) -> bytes:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return raw + (b"\n" if trailing_lf else b"")


def strict_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8", errors="strict"), object_pairs_hook=reject_duplicates
    )
    require(isinstance(value, dict), "JSON root is not an object")
    return value


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode:
        raise DevelopmentTriggerD18Error("git operation failed")
    return completed.stdout


def commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise DevelopmentTriggerD18Error(f"missing committed material: {path}")
    return completed.stdout


def _sha256_at(repository: Path, commit: str, path: str) -> str:
    return hashlib.sha256(commit_bytes(repository, commit, path)).hexdigest()


def _validate_historical_receipt(receipt: Mapping[str, Any]) -> None:
    workflow = receipt.get("workflow_run")
    accounting = receipt.get("execution_accounting")
    custody = receipt.get("custody")
    interpretation = receipt.get("interpretation")
    require(isinstance(workflow, Mapping), "historical _008 workflow identity missing")
    require(
        workflow.get("id") == PREVIOUS_RUN_ID
        and workflow.get("attempt") == 1
        and workflow.get("head_sha") == PREVIOUS_EXECUTION_HEAD
        and workflow.get("source_head_sha") == PREVIOUS_SOURCE_HEAD
        and workflow.get("conclusion") == "cancelled",
        "historical _008 workflow identity differs",
    )
    require(
        receipt.get("schema")
        == "trimem/development-terminal-contract-mismatch-receipt/1.0"
        and receipt.get("status") == "TERMINAL_PRESERVED"
        and receipt.get("endpoint") == "TRIMEM_V1_DEV_INCOMPLETE"
        and receipt.get("classification") == AMENDMENT_CLASSIFICATION
        and receipt.get("scientific_status") == "NOT_STARTED"
        and receipt.get("failure_subtype") == PREVIOUS_FAILURE_SUBTYPE,
        "historical _008 terminal classification differs",
    )
    require(
        isinstance(accounting, Mapping)
        and dict(accounting) == PREVIOUS_EXECUTION_ACCOUNTING,
        "historical _008 execution accounting differs",
    )
    require(
        isinstance(custody, Mapping)
        and custody.get("local_encrypted_custody") == "PASS"
        and custody.get("remote_github_artifact_custody")
        == "UNAVAILABLE_AFTER_FORCE_CANCEL",
        "historical _008 evidence-custody boundary differs",
    )
    require(
        isinstance(interpretation, Mapping)
        and interpretation.get("scientific_result") is False
        and interpretation.get("performance_measured") is False,
        "historical _008 result boundary differs",
    )


def validate_previous_execution_receipt(raw: bytes) -> dict[str, Any]:
    """Validate and return the immutable public `_008` terminal receipt."""

    receipt = strict_json(raw)
    _validate_historical_receipt(receipt)
    return receipt


def _validate_amendment(
    repository: Path, source_head: str, amendment: Mapping[str, Any]
) -> None:
    implementation = amendment.get("implementation_sha256")
    preserved = amendment.get("preserved_sha256")
    historical = amendment.get("historical_run")
    scope_inventory = amendment.get("scope_lock_inventory")
    semantic_scope = amendment.get("semantic_scope_lock")
    finalization = amendment.get("finalization_placeholders")
    pre_execution = amendment.get("pre_execution_gate_evidence")
    require(
        amendment.get("schema") == AMENDMENT_SCHEMA
        and amendment.get("status") == AMENDMENT_STATUS
        and amendment.get("classification") == AMENDMENT_CLASSIFICATION
        and isinstance(implementation, Mapping)
        and set(implementation) == D18_REQUIRED_IMPLEMENTATION_PATHS
        and isinstance(preserved, Mapping)
        and dict(preserved) == PRESERVED_SHA256
        and isinstance(historical, Mapping)
        and isinstance(scope_inventory, Mapping)
        and isinstance(semantic_scope, Mapping)
        and isinstance(finalization, Mapping),
        "D1.8 terminal-contract amendment differs",
    )
    failed_source_gate = (
        pre_execution.get("failed_correction_source_gate")
        if isinstance(pre_execution, Mapping)
        else None
    )
    require(
        isinstance(failed_source_gate, Mapping)
        and canonical_bytes(dict(failed_source_gate))
        == canonical_bytes(FAILED_CORRECTION_SOURCE_GATE_EVIDENCE),
        "D1.8 failed correction-source gate provenance differs",
    )
    require(
        historical.get("id") == PREVIOUS_RUN_ID
        and historical.get("attempt") == 1
        and historical.get("source_head") == PREVIOUS_SOURCE_HEAD
        and historical.get("head_sha") == PREVIOUS_EXECUTION_HEAD
        and historical.get("request_path") == PREVIOUS_SENTINEL_PATH
        and historical.get("request_raw_sha256") == PREVIOUS_SENTINEL_SHA256
        and historical.get("failure_subtype") == PREVIOUS_FAILURE_SUBTYPE
        and historical.get("performance_measured") is False,
        "D1.8 historical-run binding differs",
    )
    for path, expected in implementation.items():
        require(
            isinstance(path, str)
            and isinstance(expected, str)
            and HEX64.fullmatch(expected) is not None
            and _sha256_at(repository, source_head, path) == expected,
            f"D1.8 implementation seal differs: {path}",
        )
    changed_rows = scope_inventory.get("changed_or_added_contract_surfaces")
    preserved_rows = scope_inventory.get("preserved_scientific_locks")
    require(
        scope_inventory.get("snapshot_kind") == "FINAL_CONTENT_SEAL_PRE_COMMIT"
        and scope_inventory.get("before_source")
        == f"git show {PREVIOUS_EXECUTION_HEAD}:<path>"
        and scope_inventory.get("after_source")
        == "correction-source commit bytes before the sentinel-only _009 commit"
        and scope_inventory.get("hash_algorithm") == "SHA-256"
        and isinstance(changed_rows, list)
        and isinstance(preserved_rows, list),
        "D1.8 scope-lock inventory metadata differs",
    )
    changed_by_path = {
        row.get("path"): row
        for row in changed_rows
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }
    require(
        len(changed_by_path) == len(changed_rows)
        and set(changed_by_path) == D18_REQUIRED_IMPLEMENTATION_PATHS,
        "D1.8 changed-surface inventory differs",
    )
    for path, row in changed_by_path.items():
        after = row.get("after")
        raw = commit_bytes(repository, source_head, path)
        require(
            isinstance(row.get("change_role"), str)
            and bool(row["change_role"])
            and isinstance(after, Mapping)
            and after.get("bytes") == len(raw)
            and after.get("sha256") == hashlib.sha256(raw).hexdigest(),
            f"D1.8 changed-surface after binding differs: {path}",
        )
        baseline = subprocess.run(
            ["git", "show", f"{PREVIOUS_EXECUTION_HEAD}:{path}"],
            cwd=repository,
            capture_output=True,
            check=False,
        )
        before = row.get("before")
        require(isinstance(before, Mapping), f"D1.8 before binding missing: {path}")
        if baseline.returncode == 0:
            require(
                before.get("bytes") == len(baseline.stdout)
                and before.get("sha256")
                == hashlib.sha256(baseline.stdout).hexdigest(),
                f"D1.8 changed-surface before binding differs: {path}",
            )
        else:
            require(
                before.get("bytes") is None and before.get("sha256") is None,
                f"D1.8 new-surface before binding differs: {path}",
            )
    preserved_by_path = {
        row.get("path"): row
        for row in preserved_rows
        if isinstance(row, Mapping) and isinstance(row.get("path"), str)
    }
    require(
        len(preserved_by_path) == len(preserved_rows)
        and set(preserved_by_path) == set(PRESERVED_SHA256),
        "D1.8 preserved-lock inventory differs",
    )
    for path, expected in PRESERVED_SHA256.items():
        raw = commit_bytes(repository, source_head, path)
        row = preserved_by_path[path]
        require(
            row.get("before_sha256") == expected
            and row.get("after_sha256") == expected
            and row.get("bytes") == len(raw),
            f"D1.8 preserved-lock row differs: {path}",
        )
    require(
        set(semantic_scope) == REQUIRED_SEMANTIC_SCOPE_LOCKS
        and all(value == "PRESERVED" for value in semantic_scope.values()),
        "D1.8 semantic scope lock differs",
    )
    require(
        set(finalization)
        == set(FINALIZATION_SAFE_HASH_PATHS)
        | set(FINALIZATION_EXTERNAL_BINDINGS)
        | {"reason"},
        "D1.8 finalization field set differs",
    )
    for field, path in FINALIZATION_SAFE_HASH_PATHS.items():
        require(
            isinstance(finalization.get(field), str)
            and HEX64.fullmatch(finalization[field]) is not None,
            f"D1.8 final safe hash differs: {field}",
        )
        require(
            _sha256_at(repository, source_head, path) == finalization[field],
            f"D1.8 final safe hash does not bind source bytes: {field}",
        )
    for field, marker in FINALIZATION_EXTERNAL_BINDINGS.items():
        require(
            finalization.get(field) == marker,
            f"D1.8 external finalization binding differs: {field}",
        )
    require(
        isinstance(finalization.get("reason"), str)
        and "self-reference" in finalization["reason"],
        "D1.8 anti-recursion explanation missing",
    )


def _validate_contract_inventory(
    repository: Path, source_head: str, inventory: Mapping[str, Any]
) -> None:
    shared = inventory.get("shared_contract")
    contract_table = inventory.get("contract_table")
    components = inventory.get("components")
    regression = inventory.get("production_shaped_regression")
    finalization = inventory.get("finalization_placeholders")
    require(
        inventory.get("schema") == INVENTORY_SCHEMA
        and inventory.get("status") == INVENTORY_STATUS
        and inventory.get("classification") == AMENDMENT_CLASSIFICATION
        and inventory.get("baseline_head") == PREVIOUS_EXECUTION_HEAD
        and isinstance(shared, Mapping)
        and isinstance(contract_table, list)
        and isinstance(components, Mapping)
        and isinstance(regression, Mapping)
        and isinstance(finalization, Mapping),
        "D1.8 terminal-contract inventory differs",
    )
    contract_sha256 = _sha256_at(
        repository,
        source_head,
        "src/enterprise_memory/trimem/scientific_terminal.py",
    )
    require(
        shared.get("path")
        == "src/enterprise_memory/trimem/scientific_terminal.py"
        and shared.get("working_tree_sha256") == contract_sha256
        and shared.get("final_resealed_sha256") == contract_sha256
        and shared.get("execution_status") == "CELL_TERMINAL"
        and shared.get("ledger_terminal_status") == "CELL_TERMINAL"
        and shared.get("pure") is True,
        "D1.8 shared terminal-contract inventory differs",
    )
    rows = {
        row.get("field"): row
        for row in contract_table
        if isinstance(row, Mapping) and isinstance(row.get("field"), str)
    }
    require(
        len(rows) == len(contract_table)
        and set(rows) == INVENTORY_CONTRACT_FIELDS
        and hashlib.sha256(canonical_bytes(contract_table)).hexdigest()
        == INVENTORY_CONTRACT_TABLE_SHA256,
        "D1.8 producer/consumer contract table is incomplete",
    )
    for field, row in rows.items():
        expected_keys = {
            "field",
            "producer",
            "produced_values",
            "consumer",
            "accepted_values",
            "notes",
        }
        if field == "grader_status":
            expected_keys.add("protected_produced_values")
        require(
            set(row) == expected_keys
            and isinstance(row.get("producer"), list)
            and bool(row["producer"])
            and all(isinstance(item, str) and item for item in row["producer"])
            and isinstance(row.get("produced_values"), list)
            and bool(row["produced_values"])
            and isinstance(row.get("consumer"), list)
            and bool(row["consumer"])
            and all(isinstance(item, str) and item for item in row["consumer"])
            and isinstance(row.get("accepted_values"), list)
            and bool(row["accepted_values"])
            and isinstance(row.get("notes"), str)
            and bool(row["notes"]),
            f"D1.8 contract-table row shape differs: {field}",
        )
    exact_status_contracts = {
        "task-arm ledger status": (
            {"RESERVED", "CELL_TERMINAL", "OFFICIAL_GRADER_FAILURE"},
            {"CELL_TERMINAL"},
        ),
        "model-request ledger status": (
            {
                "RESERVED",
                "SUCCESS",
                "SUCCESS_CONSERVATIVE_USAGE",
                "PROVIDER_FAILURE",
                "PROVIDER_FAILURE_CONSERVATIVE",
                "UNKNOWN_FAILURE_CONSERVATIVE",
                "INVALID_UNPAID_RESPONSE_CONSERVATIVE",
            },
            {
                "SUCCESS",
                "SUCCESS_CONSERVATIVE_USAGE",
                "PROVIDER_FAILURE",
                "PROVIDER_FAILURE_CONSERVATIVE",
            },
        ),
        "grader_status": (
            ALL_GRADE_RESULT_STATUSES,
            {"success"},
        ),
        "grader_exit_code": ({0, "nonzero integer including -1"}, {0}),
        "official_grader": ({True, False}, {True}),
        "container_started": ({True, False}, {True}),
    }
    for field, (produced, accepted) in exact_status_contracts.items():
        row = rows[field]
        require(
            set(row.get("produced_values", ())) == produced
            and set(row.get("accepted_values", ())) == accepted,
            f"D1.8 {field} producer/consumer values differ",
        )
    require(
        set(rows["grader_status"].get("protected_produced_values", ()))
        == PROTECTED_OFFICIAL_GRADER_STATUSES,
        "D1.8 protected official grader status inventory differs",
    )
    required_calls = {
        "validate_scientific_terminal_result",
        "validate_result_ledger_pair",
        "validate_result_request_statuses",
    }
    for component in ("runner", "matrix"):
        value = components.get(component)
        require(
            isinstance(value, Mapping)
            and required_calls <= set(value.get("shared_contract_calls", ())),
            f"D1.8 {component} contract-consumer inventory differs",
        )
    require(
        regression.get("status") == "PASS"
        and regression.get("targets") == 12
        and regression.get("streams")
        == [
            "M2-baseline",
            "M2-precision",
            "M2-recall",
            "M2-balanced",
            "M0",
            "M1",
        ]
        and regression.get("terminal_records") == 72
        and regression.get("terminal_ledger_rows") == 72
        and regression.get("real_provider_requests") == 0
        and regression.get("real_image_pulls") == 0
        and regression.get("real_grader_processes") == 0
        and regression.get("usd") == 0,
        "D1.8 production-shaped regression inventory differs",
    )
    require(
        finalization
        == {
            "final_source_head": "BOUND_EXTERNALLY_AS_009_SOURCE_HEAD",
            "final_shared_contract_sha256": contract_sha256,
            "final_inventory_sha256_binding": (
                "RECORD_EXTERNALLY_IN_RESEARCH_FREEZE_TO_AVOID_SELF_HASH_RECURSION"
            ),
            "remote_exact_head_gate_evidence": (
                "BOUND_EXTERNALLY_IN_009_REMOTE_GATE_EVIDENCE"
            ),
            "research_freeze_sha256": (
                "BOUND_EXTERNALLY_BY_009_FREEZE_SHA256"
            ),
        },
        "D1.8 inventory anti-recursion bindings differ",
    )


def _validate_source(repository: Path, source_head: str) -> dict[str, str]:
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    require(
        git(repository, "cat-file", "-t", source_head).strip() == "commit",
        "source HEAD is not a commit",
    )
    for path, expected in PRESERVED_SHA256.items():
        require(
            _sha256_at(repository, source_head, path) == expected,
            f"frozen scientific input changed: {path}",
        )
    require(
        _sha256_at(repository, source_head, HISTORICAL_D16_AMENDMENT_PATH)
        == HISTORICAL_D16_AMENDMENT_SHA256,
        "historical D1.6 amendment changed",
    )
    require(
        _sha256_at(repository, source_head, HISTORICAL_D17_AMENDMENT_PATH)
        == HISTORICAL_D17_AMENDMENT_SHA256,
        "historical D1.7 amendment changed",
    )
    previous_raw = commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH)
    require(
        hashlib.sha256(previous_raw).hexdigest() == PREVIOUS_SENTINEL_SHA256,
        "historical _008 sentinel changed",
    )
    previous_request = strict_json(previous_raw)
    require(
        previous_request.get("request_sha256")
        == "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
        and previous_request.get("source_head") == PREVIOUS_SOURCE_HEAD,
        "historical _008 request binding differs",
    )
    require(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", PREVIOUS_EXECUTION_HEAD, source_head],
            cwd=repository,
            capture_output=True,
            check=False,
        ).returncode
        == 0,
        "source does not descend from immutable _008 execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_009 already exists in source history",
    )

    validate_previous_execution_receipt(
        commit_bytes(repository, source_head, PREVIOUS_RECEIPT_PATH)
    )
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    _validate_amendment(repository, source_head, amendment)
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    _validate_contract_inventory(repository, source_head, inventory)

    freeze = strict_json(
        commit_bytes(repository, source_head, "artifacts/trimem_v1/freeze.json")
    )
    files = freeze.get("files")
    require(isinstance(files, Mapping), "research freeze inventory is missing")
    require(SENTINEL_PATH not in files, "_009 entered the correction-source freeze")
    bindings: dict[str, str] = {}
    for name, path in BOUND_PATHS.items():
        raw = commit_bytes(repository, source_head, path)
        digest = hashlib.sha256(raw).hexdigest()
        require(
            path in FREEZE_MEMBERSHIP_EXEMPT_PATHS
            or files.get(path) == {"bytes": len(raw), "sha256": digest},
            f"research freeze does not bind {path}",
        )
        bindings[name] = "sha256:" + digest
    return bindings


def validate_correction_source(
    repository: Path,
    source_head: str | None = None,
    *,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    """Validate the clean pre-trigger correction commit without requiring `_009`."""

    repository = repository.resolve(strict=True)
    checked_out = git(repository, "rev-parse", "HEAD").strip()
    selected = checked_out if source_head is None else source_head
    if require_checked_out_head:
        require(selected == checked_out, "source HEAD differs from checked-out HEAD")
    bindings = _validate_source(repository, selected)
    return {
        "status": "PASS",
        "request_id": REQUEST_ID,
        "source_head": selected,
        "sentinel_path": SENTINEL_PATH,
        "sentinel_present": False,
        "bindings": bindings,
        "model_calls": 0,
        "paid_model_calls": 0,
        "task_arm_runs": 0,
        "grader_containers": 0,
        "total_usd": 0.0,
    }


def _remote_gates(value: Mapping[str, Any], source_head: str) -> dict[str, Any]:
    require(value.get("source_head") == source_head, "remote gates source differs")
    require(value.get("all_required_workflows_passed") is True, "remote gates not green")
    rows = value.get("workflows")
    require(isinstance(rows, list), "remote gate workflow rows missing")
    require(
        tuple(row.get("workflow_path") for row in rows)
        == REQUIRED_REMOTE_GATE_WORKFLOWS,
        "remote gate workflow set/order differs",
    )
    for row in rows:
        require(
            row.get("head_sha") == source_head
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
            and row.get("run_attempt") == 1,
            "remote gate row is not exact-head success",
        )
    require(
        value.get("scientific_execution")
        == {
            "api_calls": 0,
            "grader_runs": 0,
            "model_calls": 0,
            "paid_model_calls": 0,
            "target_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "remote gates performed scientific work",
    )
    return dict(value)


def build_request(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    bindings = _validate_source(repository, source_head)
    gates = _remote_gates(remote_gate_evidence, source_head)
    development = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/development_manifest.json")
    )
    cost = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/cost_plan.json")
    )
    targets = [row["instance_id"] for row in development["targets"]]
    hard = cost["phase_hard_caps"][EXPECTED_PHASE]
    payload = {
        "actual_execution_authorized": False,
        "amendment_classification": AMENDMENT_CLASSIFICATION,
        "authorization_semantics": (
            "The sentinel creates one run but protected execution requires a distinct "
            "run-bound external approval and matching OpenAI key commitment."
        ),
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "control_plane": {
            "exact_model_metadata_requests": 1,
            "protocol_canary_generation_requests": 1,
            "scientific_generation_request_cap": 1872,
            "precedes_benchmark_image_pull": True,
        },
        "exact_model": {
            "base_url": "https://api.openai.com/v1",
            "model_id": MODEL_ID,
            "reasoning_effort": "medium",
        },
        "hard_caps": hard,
        "phase": EXPECTED_PHASE,
        "pre_execution_actuals": {
            "completed_task_arm_runs": 0,
            "exact_model_metadata_requests": 0,
            "protocol_canary_generation_calls": 0,
            "provider_generation_calls": 0,
            "model_generation_calls": 0,
            "scientific_model_calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "official_grader_runs": 0,
            "grader_containers": 0,
            "benchmark_target_image_pulls": 0,
            "support_image_pulls": 0,
            "total_usd": 0.0,
        },
        "prohibited_actions": [
            "DEVELOPMENT_TUNING_EXEC_REQUEST_008_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_010",
            "HELDOUT_BENCHMARK",
            "component_ablation",
            "grader_smoke_rerun",
            "merge_tag_or_release",
            "model_or_reasoning_change",
            "target_or_candidate_change",
        ],
        "recovery_provenance": {
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": 1,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_008",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "performance_measured": False,
        },
        "remote_gate_evidence": gates,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "required_external_approval_fields": DEVELOPMENT_APPROVAL_FIELDS,
        "required_external_authorization": REQUIRED_EXTERNAL_AUTHORIZATION,
        "requires_external_approval": True,
        "schema": REQUEST_SCHEMA,
        "scientific_workload": {
            "grader_containers": 72,
            "protocol_canary_generation_calls": 1,
            "scientific_generation_call_cap": 1872,
            "m2_candidate_streams": 4,
            "stream_order": [
                "M2-baseline",
                "M2-precision",
                "M2-recall",
                "M2-balanced",
                "M0",
                "M1",
            ],
            "target_order": targets,
            "task_arm_runs": 72,
        },
        "source_head": source_head,
        "workflow_path": ".github/workflows/trimem-benchmark.yml",
    }
    return {
        **payload,
        "request_sha256": "sha256:"
        + hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def validate_request(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    value = strict_json(raw)
    gates = _remote_gates(value.get("remote_gate_evidence", {}), source_head)
    expected = build_request(
        repository, source_head=source_head, remote_gate_evidence=gates
    )
    require(value == expected, "_009 request content differs")
    require(raw == canonical_bytes(expected, trailing_lf=True), "_009 bytes differ")
    return value


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    require(HEX40.fullmatch(after) is not None, "trigger commit SHA is invalid")
    if require_checked_out_head:
        require(git(repository, "rev-parse", "HEAD").strip() == after, "HEAD differs")
    parents = git(repository, "rev-list", "--parents", "-n", "1", after).split()
    require(len(parents) == 2, "trigger must have one parent")
    parent = parents[1]
    if expected_parent is not None:
        require(parent == expected_parent, "trigger parent differs")
    changes = git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        after,
    ).splitlines()
    require(changes == [f"A\t{SENTINEL_PATH}"], "trigger commit is not sentinel-only")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_009 already exists in history",
    )
    return validate_request(
        repository,
        commit_bytes(repository, after, SENTINEL_PATH),
        source_head=parent,
    )


def validate_branch_trigger(
    repository: Path, event_path: Path, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    event = strict_json(event_path.read_bytes())
    require(environment.get("GITHUB_EVENT_NAME") == "push", "event is not push")
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "attempt must be one")
    require(environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY, "repository differs")
    require(environment.get("GITHUB_REF") == EXPECTED_REF, "ref differs")
    require(environment.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF, "workflow differs")
    require(event.get("forced") is False, "forced push forbidden")
    before, after = event.get("before"), event.get("after")
    require(environment.get("GITHUB_SHA") == after, "event after differs")
    require(environment.get("GITHUB_WORKFLOW_SHA") == after, "workflow SHA differs")
    request = validate_sentinel_commit(repository, after, expected_parent=before)
    live = collect_remote_gate_evidence(before)
    require(
        request["remote_gate_evidence"]["workflows"] == live["workflows"],
        "embedded remote gates differ from live runs",
    )
    return {
        "status": "PASS",
        "request_id": REQUEST_ID,
        "source_head": before,
        "trigger_commit": after,
        "model_calls": 0,
        "paid_model_calls": 0,
        "task_arm_runs": 0,
        "grader_containers": 0,
        "total_usd": 0.0,
    }


def write_request(repository: Path) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    require(
        git(repository, "symbolic-ref", "--quiet", "HEAD").strip() == EXPECTED_REF,
        "wrong branch",
    )
    require(
        not git(repository, "status", "--porcelain=v1", "--untracked-files=all").strip(),
        "request rendering requires a clean worktree",
    )
    source_head = git(repository, "rev-parse", "HEAD").strip()
    target = repository / SENTINEL_PATH
    require(not target.exists(), "_009 already exists")
    _validate_source(repository, source_head)
    gates = collect_remote_gate_evidence(source_head)
    document = build_request(
        repository, source_head=source_head, remote_gate_evidence=gates
    )
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
        "path": SENTINEL_PATH,
        "source_head": source_head,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-head")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--event-path", type=Path)
    group.add_argument("--write-request", action="store_true")
    group.add_argument("--validate-source", action="store_true")
    args = parser.parse_args()
    if args.source_head is not None and not args.validate_source:
        parser.error("--source-head requires --validate-source")
    try:
        if args.write_request:
            result = write_request(args.repository)
        elif args.validate_source:
            result = validate_correction_source(
                args.repository,
                args.source_head,
                require_checked_out_head=True,
            )
        else:
            result = validate_branch_trigger(args.repository, args.event_path)
    except (DevelopmentTriggerD18Error, OSError, ValueError) as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
