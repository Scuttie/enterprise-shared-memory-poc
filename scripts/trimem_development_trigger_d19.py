"""Fail-closed one-time DEVELOPMENT_TUNING ``_010`` context-recovery trigger.

The D1.9 correction source is validated before the sentinel exists.  A later
single-file commit may add the zero-authority ``_010`` request only after the
five exact-head credential-free workflows pass.  Historical ``_001`` through
``_009`` requests are read as immutable Git blobs and are never rewritten by
this module.
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
from trimem_development_trigger_preflight import (
    _validate_secret_free_preflight as validate_secret_free_preflight,
    collect_remote_gate_evidence,
)
import trimem_development_trigger_d18 as historical_d18


EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_REF = "refs/heads/codex/trimem-coder-v1"
EXPECTED_WORKFLOW_REF = (
    "Scuttie/enterprise-shared-memory-poc/.github/workflows/"
    "trimem-benchmark.yml@refs/heads/codex/trimem-coder-v1"
)
EXPECTED_PHASE = "DEVELOPMENT_TUNING"
REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_010"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.9"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_010.json"
)
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_009.json"
)
PREVIOUS_SOURCE_HEAD = "ef10493a7352bd6cf914e5e465a9580be6462eb0"
PREVIOUS_EXECUTION_HEAD = "db548919f29fd044cce1e066c74d2a7040a28f49"
PREVIOUS_RUN_ID = 33_979_936_824
PREVIOUS_SENTINEL_SHA256 = (
    "3bf60d8b60ce2c902875593a0c10261c32bb6ed4961cd83703d926c33c5f968f"
)
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "8a97f8d3f91906ab549c210181219ee5782fc9eeaea45dba79cf99553652e85e"
)
PREVIOUS_FAILURE_SUBTYPE = "UNBOUNDED_MODEL_VISIBLE_TOOL_HISTORY"

AMENDMENT_PATH = "artifacts/trimem_v1/development_bounded_context_amendment.json"
AMENDMENT_SCHEMA = "trimem/development-bounded-context-amendment/1.0"
INVENTORY_PATH = "artifacts/trimem_v1/development_bounded_context_inventory.json"
INVENTORY_SCHEMA = "trimem/development-bounded-context-inventory/1.0"
PREVIOUS_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-009/"
    "bounded-short-term-context-failure-receipt.json"
)
PREVIOUS_RECEIPT_SCHEMA = (
    "trimem/development-bounded-context-failure-receipt/1.0"
)
PREVIOUS_REPORT_PATH = (
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_009_BOUNDED_CONTEXT_FAILURE.md"
)
AMENDMENT_CLASSIFICATION = (
    "PRE_RESULT_BOUNDED_SHORT_TERM_CONTEXT_AND_PREFLIGHT_FIX"
)
AMENDMENT_STATUS = "FROZEN_PRE_RESULT_PENDING_FRESH_EXECUTION"
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_CONTEXT_RECOVERY_EXEC_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-010"
MODEL_ID = "gpt-5.4-mini-2026-03-17"

REQUIRED_REMOTE_GATE_WORKFLOWS = (
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
)
DEVELOPMENT_APPROVAL_FIELDS = list(historical_d18.DEVELOPMENT_APPROVAL_FIELDS)

HISTORICAL_REQUEST_SHA256 = {
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_001.json": "7501c630a05ab0b87b9b510a72a5389f6ea7046dee6153b583e2833fa8e7e1db",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_002.json": "c81c57a5c93d4be9efdc971147191d8bc2e1bc2f06fe241e38ce36b6a4ee3f98",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_003.json": "3d6b4291f7a1ab8b72203e4756a2f7e4614c1139c9f6e0da74a3a949fa78ca56",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_004.json": "20bccf63d7f09e4130e7297bc0b1c07b4d97f15baefa77099b582e105874dd80",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_005.json": "97e2ce227418ace0db1edbf816391cdf0fda4f8d29359da4a3f81687f1aa19de",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_006.json": "9eb67d9b9ca5382a5f120108e12f767cdd51f421e1123f8cc74e18ec309cf01c",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_007.json": "90b7cbcc43a7b1a8ce5df8413ab48d386c500aaee3f167fa3cebc064eaa33ab7",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_008.json": "2eac68069e9a2cc760138eca5b9e6ae1d5438a97cd9e4918a496ab920cc584b7",
    PREVIOUS_SENTINEL_PATH: PREVIOUS_SENTINEL_SHA256,
}

# These are the scientific inputs that D1.9 is not permitted to change.  The
# current source bytes are compared directly with immutable ``_009`` Git blobs;
# generated runtime-lock projections are intentionally not in this set.
PRESERVED_PATHS = (
    "artifacts/trimem_v1/adapter_failure_envelope_contract.json",
    "artifacts/trimem_v1/grader_image_lock.json",
    "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json",
    "artifacts/trimem_v1/multi_swe_report_semantics_lock.json",
    "artifacts/trimem_v1/provider_output_schema_lock.json",
    "artifacts/trimem_v1/solve_output_budget_contract_lock.json",
    "configs/trimem_v1/arms.json",
    "configs/trimem_v1/benchmark_environment.lock",
    "configs/trimem_v1/benchmark_environment_lock.json",
    "configs/trimem_v1/cost_plan.json",
    "configs/trimem_v1/development_manifest.json",
    "configs/trimem_v1/grader_lock.json",
    "configs/trimem_v1/heldout_manifest.json",
    "configs/trimem_v1/m2_candidates/balanced.json",
    "configs/trimem_v1/m2_candidates/baseline.json",
    "configs/trimem_v1/m2_candidates/precision.json",
    "configs/trimem_v1/m2_candidates/recall.json",
    "configs/trimem_v1/m2_policy.json",
    "configs/trimem_v1/model_lock.json",
    "configs/trimem_v1/provider_output_schemas.json",
    "configs/trimem_v1/selection_plan.json",
    "configs/trimem_v1/solve_output_budget_contract.json",
    "scripts/trimem_exec_approval.py",
    "scripts/trimem_harness_lock.py",
    "scripts/trimem_official_grader.py",
    "scripts/trimem_run_with_resume.py",
    "src/enterprise_memory/providers/base.py",
    "src/enterprise_memory/providers/openai_responses.py",
    "src/enterprise_memory/trimem/arms.py",
    "src/enterprise_memory/trimem/grader.py",
    "src/enterprise_memory/trimem/policy.py",
    "src/enterprise_memory/trimem/ppr.py",
    "src/enterprise_memory/trimem/provider_output_contracts.py",
    "src/enterprise_memory/trimem/retrieval.py",
)

CONTRACT_FIELDS = (
    "function_tool_schema_sha256",
    "list_files_pagination_contract_sha256",
    "model_visible_observation_projection_sha256",
    "prompt_context_contract_sha256",
    "request_lifecycle_contract_sha256",
    "resume_automaton_sha256",
    "runner_sha256",
    "workflow_sha256",
    "credential_free_bundle_sha256",
)
SEMANTIC_CONTRACT_SOURCE_PATHS = {
    "function_tool_schema_sha256": (
        "src/enterprise_memory/trimem/function_tools.py",
    ),
    "list_files_pagination_contract_sha256": (
        "src/enterprise_memory/trimem/workspace.py",
    ),
    "model_visible_observation_projection_sha256": (
        "src/enterprise_memory/trimem/context_projection.py",
    ),
    "prompt_context_contract_sha256": (
        "src/enterprise_memory/trimem/context_projection.py",
    ),
    "request_lifecycle_contract_sha256": (
        "src/enterprise_memory/trimem/gateway.py",
    ),
    "resume_automaton_sha256": (
        "src/enterprise_memory/trimem/gateway.py",
    ),
}
RAW_FILE_CONTRACT_PATHS = {
    "runner_sha256": "scripts/trimem_benchmark_run.py",
    "workflow_sha256": ".github/workflows/trimem-benchmark.yml",
    "credential_free_bundle_sha256": (
        "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
    ),
}

BOUND_PATHS = {
    "arms_sha256": "configs/trimem_v1/arms.json",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": ".github/workflows/trimem-benchmark.yml",
    "bounded_context_amendment_sha256": AMENDMENT_PATH,
    "bounded_context_inventory_sha256": INVENTORY_PATH,
    "context_roundtrip_sha256": "scripts/trimem_context_roundtrip.py",
    "credential_free_bundle_sha256": (
        "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
    ),
    "credential_free_static_workflow_sha256": ".github/workflows/ci-trimem.yml",
    "credential_free_toolchain_workflow_sha256": (
        ".github/workflows/ci-trimem-dev-toolchain.yml"
    ),
    "development_manifest_sha256": "configs/trimem_v1/development_manifest.json",
    "freeze_sha256": "artifacts/trimem_v1/freeze.json",
    "grader_lock_sha256": "configs/trimem_v1/grader_lock.json",
    "image_lock_sha256": "artifacts/trimem_v1/grader_image_lock.json",
    "m2_candidate_manifest_sha256": "configs/trimem_v1/m2_candidate_bundles.json",
    "model_lock_sha256": "configs/trimem_v1/model_lock.json",
    "previous_dev_receipt_sha256": PREVIOUS_RECEIPT_PATH,
    "previous_dev_report_sha256": PREVIOUS_REPORT_PATH,
    "previous_dev_request_sha256": PREVIOUS_SENTINEL_PATH,
    "readiness_requirements_sha256": "artifacts/trimem_v1/readiness_requirements.json",
    "selection_plan_sha256": "configs/trimem_v1/selection_plan.json",
    "tool_environment_lock_sha256": "configs/trimem_v1/tool_environment_lock.json",
    "trigger_reader_sha256": "scripts/trimem_development_trigger_d19.py",
}
FREEZE_MEMBERSHIP_EXEMPT_PATHS = {
    "artifacts/trimem_v1/freeze.json",
    PREVIOUS_SENTINEL_PATH,
}

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class DevelopmentTriggerD19Error(ValueError):
    """D1.9 source/request/trigger validation failed closed."""


# Stable consumer name used by the benchmark runner and aggregate after D1.9.
DevelopmentTriggerError = DevelopmentTriggerD19Error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DevelopmentTriggerD19Error(message)


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
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DevelopmentTriggerD19Error(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DevelopmentTriggerD19Error("invalid UTF-8 JSON") from exc
    require(isinstance(value, dict), "JSON root must be an object")
    return value


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        raise DevelopmentTriggerD19Error(completed.stderr.strip() or "git command failed")
    return completed.stdout


def commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    require(
        not Path(path).is_absolute() and ".." not in Path(path).parts,
        "unsafe Git path",
    )
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DevelopmentTriggerD19Error(f"required Git blob is missing: {path}")
    return completed.stdout


def _sha256_at(repository: Path, commit: str, path: str) -> str:
    return hashlib.sha256(commit_bytes(repository, commit, path)).hexdigest()


def _validate_historical_requests(repository: Path, source_head: str) -> None:
    for path, expected in HISTORICAL_REQUEST_SHA256.items():
        require(
            _sha256_at(repository, source_head, path) == expected,
            f"historical development request changed: {path}",
        )
    previous = strict_json(commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH))
    require(
        previous.get("request_id") == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_009"
        and previous.get("source_head") == PREVIOUS_SOURCE_HEAD
        and previous.get("request_sha256")
        == "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "historical _009 request identity differs",
    )
    require(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", PREVIOUS_EXECUTION_HEAD, source_head],
            cwd=repository,
            capture_output=True,
            check=False,
        ).returncode
        == 0,
        "D1.9 source does not descend from immutable _009 execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_010 already exists in source history",
    )


def _validate_preserved_inputs(repository: Path, source_head: str) -> dict[str, str]:
    preserved: dict[str, str] = {}
    for path in PRESERVED_PATHS:
        historical = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path)
        current = commit_bytes(repository, source_head, path)
        require(current == historical, f"frozen scientific input changed: {path}")
        preserved[path] = hashlib.sha256(current).hexdigest()
    return preserved


def validate_previous_execution_receipt(raw: bytes) -> dict[str, Any]:
    value = strict_json(raw)
    scientific = value.get("scientific_usage")
    canary = value.get("canary_usage")
    totals = value.get("total_usage")
    require(
        value.get("schema") == PREVIOUS_RECEIPT_SCHEMA
        and value.get("status") == "TERMINAL_PRESERVED"
        and value.get("endpoint") == "TRIMEM_V1_DEV_INCOMPLETE"
        and value.get("primary_failure") == PREVIOUS_FAILURE_SUBTYPE
        and value.get("classification") == AMENDMENT_CLASSIFICATION
        and value.get("scientific_status") == "INTERRUPTED_BEFORE_FIRST_TERMINAL_CELL",
        "D1.9 historical _009 failure receipt identity differs",
    )
    run = value.get("workflow_run")
    require(
        isinstance(run, Mapping)
        and run.get("id") == PREVIOUS_RUN_ID
        and run.get("attempt") == 1
        and run.get("head_sha") == PREVIOUS_EXECUTION_HEAD
        and run.get("source_head_sha") == PREVIOUS_SOURCE_HEAD
        and run.get("conclusion") == "failure",
        "D1.9 historical _009 workflow identity differs",
    )
    require(
        scientific
        == {
            "decomposition_calls": 1,
            "solve_calls": 7,
            "extraction_calls": 0,
            "paid_model_calls": 8,
            "input_tokens": 60_546,
            "cached_input_tokens": 0,
            "output_tokens": 7_448,
            "reasoning_tokens": 1_597,
            "total_usd": "0.078925500000",
        }
        and canary
        == {
            "paid_model_calls": 1,
            "input_tokens": 880,
            "cached_input_tokens": 0,
            "output_tokens": 51,
            "reasoning_tokens": 35,
            "total_usd": "0.000889500000",
        }
        and totals
        == {
            "paid_model_calls": 9,
            "input_tokens": 61_426,
            "cached_input_tokens": 0,
            "output_tokens": 7_499,
            "reasoning_tokens": 1_632,
            "total_usd": "0.079815000000",
        },
        "D1.9 historical _009 usage accounting differs",
    )
    require(
        value.get("terminal_cells") == 0
        and value.get("planned_cells") == 72
        and value.get("official_grader_runs") == 0
        and value.get("performance_measured") is False,
        "D1.9 historical _009 scientific boundary differs",
    )
    return value


def _hex_contracts(value: object) -> dict[str, str]:
    require(isinstance(value, Mapping), "D1.9 context contract inventory is missing")
    require(set(value) == set(CONTRACT_FIELDS), "D1.9 context contract field set differs")
    result = {str(key): str(child) for key, child in value.items()}
    for key, digest in result.items():
        require(HEX64.fullmatch(digest) is not None, f"D1.9 contract digest is invalid: {key}")
    return result


def _validate_contract_documents(
    repository: Path,
    source_head: str,
    value: object,
    contracts: Mapping[str, str],
) -> None:
    require(isinstance(value, Mapping), "D1.9 contract documents are missing")
    require(set(value) == set(CONTRACT_FIELDS), "D1.9 contract document field set differs")
    for name in CONTRACT_FIELDS:
        document = value.get(name)
        require(
            isinstance(document, Mapping)
            and set(document)
            == {
                "algorithm",
                "canonical_preimage",
                "preimage_kind",
                "sha256",
                "source_paths",
                "source_sha256",
            }
            and document.get("algorithm") == "sha256"
            and document.get("sha256") == contracts[name],
            f"D1.9 contract document shape differs: {name}",
        )
        expected_paths = (
            SEMANTIC_CONTRACT_SOURCE_PATHS[name]
            if name in SEMANTIC_CONTRACT_SOURCE_PATHS
            else (RAW_FILE_CONTRACT_PATHS[name],)
        )
        source_paths = document.get("source_paths")
        source_sha256 = document.get("source_sha256")
        require(
            source_paths == list(expected_paths)
            and isinstance(source_sha256, Mapping)
            and set(source_sha256) == set(expected_paths),
            f"D1.9 contract source set differs: {name}",
        )
        for path in expected_paths:
            require(
                source_sha256.get(path) == _sha256_at(repository, source_head, path),
                f"D1.9 contract source hash differs: {name}:{path}",
            )
        if name in SEMANTIC_CONTRACT_SOURCE_PATHS:
            preimage = document.get("canonical_preimage")
            require(
                document.get("preimage_kind") == "canonical-json"
                and isinstance(preimage, (Mapping, list))
                and hashlib.sha256(canonical_bytes(preimage)).hexdigest()
                == contracts[name],
                f"D1.9 semantic contract preimage differs: {name}",
            )
        else:
            path = RAW_FILE_CONTRACT_PATHS[name]
            require(
                document.get("preimage_kind") == "raw-file-bytes"
                and document.get("canonical_preimage") is None
                and _sha256_at(repository, source_head, path) == contracts[name],
                f"D1.9 raw-file contract preimage differs: {name}",
            )


def _validate_amendment(
    repository: Path, source_head: str, value: Mapping[str, Any], preserved: Mapping[str, str]
) -> tuple[dict[str, str], dict[str, str]]:
    require(
        value.get("schema") == AMENDMENT_SCHEMA
        and value.get("status") == AMENDMENT_STATUS
        and value.get("classification") == AMENDMENT_CLASSIFICATION
        and value.get("endpoint_before_fresh_execution") == "TRIMEM_V1_DEV_INCOMPLETE"
        and value.get("completed_scientific_cells_before_correction") == 0
        and value.get("performance_result_existed_before_correction") is False,
        "D1.9 bounded-context amendment identity differs",
    )
    require(
        value.get("primary_failure") == PREVIOUS_FAILURE_SUBTYPE
        and value.get("contributing_factors")
        == [
            "UNPAGINATED_LIST_FILES",
            "EXACT_TOOL_RESULT_REINJECTED_IN_FULL",
            "ALL_PRIOR_TOOL_HISTORY_REINJECTED_EVERY_TURN",
            "TEXTUAL_TOOL_SCHEMA_DUPLICATES_NATIVE_FUNCTION_SCHEMA",
            "REQUEST_EVENT_WRITTEN_BEFORE_LOCAL_BUDGET_PREFLIGHT",
            "SOLVE_REQUEST_ONLY_SUFFIX_NOT_RECOVERABLE",
        ],
        "D1.9 root-cause classification differs",
    )
    historical = value.get("historical_run")
    require(
        isinstance(historical, Mapping)
        and historical.get("id") == PREVIOUS_RUN_ID
        and historical.get("attempt") == 1
        and historical.get("source_head") == PREVIOUS_SOURCE_HEAD
        and historical.get("head_sha") == PREVIOUS_EXECUTION_HEAD
        and historical.get("request_path") == PREVIOUS_SENTINEL_PATH
        and historical.get("request_raw_sha256") == PREVIOUS_SENTINEL_SHA256,
        "D1.9 amendment historical-run binding differs",
    )
    require(value.get("preserved_sha256") == dict(preserved), "D1.9 preserved-input inventory differs")
    implementation = value.get("implementation_sha256")
    require(isinstance(implementation, Mapping) and implementation, "D1.9 implementation seal is empty")
    implementation_hashes = {str(path): str(digest) for path, digest in implementation.items()}
    for path, digest in implementation_hashes.items():
        require(
            path not in {AMENDMENT_PATH, INVENTORY_PATH, "artifacts/trimem_v1/freeze.json"}
            and HEX64.fullmatch(digest) is not None
            and _sha256_at(repository, source_head, path) == digest,
            f"D1.9 implementation seal differs: {path}",
        )
    required = {
        ".gitattributes",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/trimem-benchmark.yml",
        "scripts/trimem_context_roundtrip.py",
        "scripts/trimem_development_trigger_d19.py",
        "scripts/trimem_development_trigger_preflight.py",
        "scripts/trimem_action_canary.py",
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_public_artifact.py",
        "scripts/trimem_verify_ready.py",
        "src/enterprise_memory/trimem/accounting.py",
        "src/enterprise_memory/trimem/agent_runtime.py",
        "src/enterprise_memory/trimem/checkpoint.py",
        "src/enterprise_memory/trimem/context_projection.py",
        "src/enterprise_memory/trimem/function_tools.py",
        "src/enterprise_memory/trimem/gateway.py",
        "src/enterprise_memory/trimem/git_workspace.py",
        "src/enterprise_memory/trimem/production_runtime.py",
        "src/enterprise_memory/trimem/runtime_lock.py",
        "src/enterprise_memory/trimem/scientific_terminal.py",
        "src/enterprise_memory/trimem/workspace.py",
        "tests/openai/test_openai_response_outcomes.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d17_approval_cap_integration.py",
        "tests/unit/test_trimem_d19_bounded_short_term_context.py",
        "tests/unit/test_trimem_d19_list_files_pagination.py",
        "tests/unit/test_trimem_d19_model_preflight.py",
        "tests/unit/test_trimem_d19_request_only_resume.py",
        "tests/unit/test_trimem_d19_terminal_contract.py",
        "tests/unit/test_trimem_d19_trigger.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_git_workspace.py",
        "tests/unit/test_trimem_runtime_boundaries.py",
    }
    require(required <= set(implementation_hashes), "D1.9 implementation seal omits required paths")
    contracts = _hex_contracts(value.get("contracts"))
    placeholders = value.get("finalization_placeholders")
    require(
        placeholders
        == {
            "final_correction_source_head": "BOUND_EXTERNALLY_AS_010_SOURCE_HEAD",
            "final_research_freeze_sha256": "BOUND_EXTERNALLY_BY_010_FREEZE_SHA256",
            "development_tuning_exec_request_010_sha256": (
                "NOT_CREATED_UNTIL_EXACT_HEAD_REMOTE_GATES_PASS"
            ),
            "exact_head_remote_ci_evidence": (
                "BOUND_EXTERNALLY_IN_010_REMOTE_GATE_EVIDENCE"
            ),
        },
        "D1.9 anti-recursion finalization placeholders differ",
    )
    return implementation_hashes, contracts


def _validate_inventory(
    repository: Path,
    source_head: str,
    value: Mapping[str, Any],
    implementation: Mapping[str, str],
    contracts: Mapping[str, str],
) -> None:
    require(
        value.get("schema") == INVENTORY_SCHEMA
        and value.get("status") == AMENDMENT_STATUS
        and value.get("classification") == AMENDMENT_CLASSIFICATION
        and value.get("implementation_sha256") == dict(implementation)
        and value.get("contracts") == dict(contracts),
        "D1.9 bounded-context inventory identity differs",
    )
    _validate_contract_documents(
        repository,
        source_head,
        value.get("contract_documents"),
        contracts,
    )
    require(
        value.get("historical_request_raw_sha256") == HISTORICAL_REQUEST_SHA256,
        "D1.9 historical request inventory differs",
    )
    company = value.get("company_handoff_separation")
    company_raw = commit_bytes(repository, source_head, "COMPANY_HANDOFF_MANIFEST.json")
    require(
        isinstance(company, Mapping)
        and company.get("manifest_rewritten") is False
        and company.get("research_state_authority") == "artifacts/trimem_v1/freeze.json"
        and company.get("manifest_raw_sha256") == hashlib.sha256(company_raw).hexdigest()
        and company_raw
        == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, "COMPANY_HANDOFF_MANIFEST.json"),
        "D1.9 company handoff/research-seal separation differs",
    )


def _validate_source(repository: Path, source_head: str) -> dict[str, str]:
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    require(git(repository, "cat-file", "-t", source_head).strip() == "commit", "source HEAD is not a commit")
    _validate_historical_requests(repository, source_head)
    _validate_preserved_inputs(repository, source_head)

    # D1.8 remains immutable evidence.  Validate it at its own source commit,
    # never against the legitimately changed D1.9 working tree.
    try:
        historical_d18._validate_source(repository, PREVIOUS_SOURCE_HEAD)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerD19Error(f"historical D1.8 source is invalid: {exc}") from exc

    receipt_raw = commit_bytes(repository, source_head, PREVIOUS_RECEIPT_PATH)
    validate_previous_execution_receipt(receipt_raw)
    report_raw = commit_bytes(repository, source_head, PREVIOUS_REPORT_PATH)
    require(
        b"UNBOUNDED_MODEL_VISIBLE_TOOL_HISTORY" in report_raw
        and b"TRIMEM_V1_DEV_INCOMPLETE" in report_raw,
        "D1.9 _009 failure report lacks the exact endpoint/root cause",
    )
    preserved = _validate_preserved_inputs(repository, source_head)
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    implementation, contracts = _validate_amendment(
        repository, source_head, amendment, preserved
    )
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    _validate_inventory(repository, source_head, inventory, implementation, contracts)

    expected_contract_bindings = {
        "runner_sha256": hashlib.sha256(
            commit_bytes(repository, source_head, BOUND_PATHS["benchmark_runner_sha256"])
        ).hexdigest(),
        "workflow_sha256": hashlib.sha256(
            commit_bytes(repository, source_head, BOUND_PATHS["benchmark_workflow_sha256"])
        ).hexdigest(),
        "credential_free_bundle_sha256": hashlib.sha256(
            commit_bytes(repository, source_head, BOUND_PATHS["credential_free_bundle_sha256"])
        ).hexdigest(),
    }
    require(
        all(contracts.get(name) == digest for name, digest in expected_contract_bindings.items()),
        "D1.9 derived file contract binding differs",
    )

    freeze_raw = commit_bytes(repository, source_head, "artifacts/trimem_v1/freeze.json")
    freeze = strict_json(freeze_raw)
    files = freeze.get("files")
    require(
        freeze.get("schema") == "trimem/freeze/1.0" and isinstance(files, Mapping),
        "research freeze is malformed",
    )
    require(SENTINEL_PATH not in files, "_010 entered the correction-source freeze")
    bindings: dict[str, str] = {}
    for name, path in BOUND_PATHS.items():
        raw = freeze_raw if path == "artifacts/trimem_v1/freeze.json" else commit_bytes(repository, source_head, path)
        digest = hashlib.sha256(raw).hexdigest()
        require(
            path in FREEZE_MEMBERSHIP_EXEMPT_PATHS
            or files.get(path) == {"bytes": len(raw), "sha256": digest},
            f"research freeze does not bind D1.9 path: {path}",
        )
        bindings[name] = "sha256:" + digest
    for path in implementation:
        raw = commit_bytes(repository, source_head, path)
        require(
            files.get(path)
            == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            f"research freeze omits D1.9 implementation: {path}",
        )
    for name, digest in contracts.items():
        bindings[name] = "sha256:" + digest
    return bindings


def validate_correction_source(
    repository: Path,
    source_head: str | None = None,
    *,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
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
        tuple(row.get("workflow_path") for row in rows) == REQUIRED_REMOTE_GATE_WORKFLOWS,
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
    cost = strict_json(commit_bytes(repository, source_head, "configs/trimem_v1/cost_plan.json"))
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
            "context_roundtrip_paid_calls": 0,
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
            "benchmark_target_image_pulls": 0,
            "cached_input_tokens": 0,
            "completed_task_arm_runs": 0,
            "exact_model_metadata_requests": 0,
            "grader_containers": 0,
            "input_tokens": 0,
            "model_generation_calls": 0,
            "official_grader_runs": 0,
            "output_tokens": 0,
            "paid_model_calls": 0,
            "protocol_canary_generation_calls": 0,
            "provider_generation_calls": 0,
            "reasoning_tokens": 0,
            "scientific_model_calls": 0,
            "support_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "prohibited_actions": [
            "DEVELOPMENT_TUNING_EXEC_REQUEST_009_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_011",
            "HELDOUT_BENCHMARK",
            "component_ablation",
            "grader_smoke_rerun",
            "merge_tag_or_release",
            "model_or_reasoning_change",
            "target_arm_candidate_or_memory_change",
        ],
        "recovery_provenance": {
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": 1,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_009",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "completed_terminal_cells": 0,
            "official_grader_runs": 0,
            "performance_measured": False,
            "paid_model_calls": 9,
            "total_usd": 0.079815,
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
        "request_sha256": "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def validate_request(repository: Path, raw: bytes, *, source_head: str) -> dict[str, Any]:
    value = strict_json(raw)
    gates = _remote_gates(value.get("remote_gate_evidence", {}), source_head)
    expected = build_request(repository, source_head=source_head, remote_gate_evidence=gates)
    require(value == expected, "_010 request content differs")
    require(raw == canonical_bytes(expected, trailing_lf=True), "_010 bytes differ")
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
        "_010 already exists in history",
    )
    return validate_request(
        repository,
        commit_bytes(repository, after, SENTINEL_PATH),
        source_head=parent,
    )


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
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
    validate_secret_free_preflight(repository, after, environment)
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
    require(not target.exists(), "_010 already exists")
    _validate_source(repository, source_head)
    gates = collect_remote_gate_evidence(source_head)
    document = build_request(repository, source_head=source_head, remote_gate_evidence=gates)
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
                args.repository, args.source_head, require_checked_out_head=True
            )
        else:
            result = validate_branch_trigger(args.repository, args.event_path)
    except (DevelopmentTriggerD19Error, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
