"""Build the credential-free D1.9 amendment, inventories, and research seal.

This is a local-only generator.  It performs no network access, model request,
image pull, or grader execution.  The generated amendment intentionally uses
external finalization placeholders for the correction-source commit and the
later sentinel-only ``_010`` commit, avoiding recursive self-hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d19 as trigger  # noqa: E402
import trimem_freeze  # noqa: E402
import trimem_m2_candidates  # noqa: E402
import trimem_verify_credential_free  # noqa: E402
from enterprise_memory.trimem.context_projection import (  # noqa: E402
    MAX_EXTRACTION_PROMPT_UTF8_BYTES,
    MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
    MAX_ORDINARY_INPUT_BOUND,
    MAX_SOLVE_PROMPT_UTF8_BYTES,
    MODEL_VISIBLE_OBSERVATION_PROJECTION_SHA256,
    PROMPT_CONTEXT_CONTRACT_SHA256,
    model_visible_observation_projection_contract,
    prompt_context_contract,
)
from enterprise_memory.trimem.credential_free import run_credential_free_e2e  # noqa: E402
from enterprise_memory.trimem.function_tools import (  # noqa: E402
    FUNCTION_TOOLS,
    FUNCTION_TOOLS_SHA256,
)
from enterprise_memory.trimem.gateway import (  # noqa: E402
    REQUEST_LIFECYCLE_CONTRACT,
    REQUEST_LIFECYCLE_CONTRACT_SHA256,
    RESUME_AUTOMATON,
    RESUME_AUTOMATON_SHA256,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from enterprise_memory.trimem.workspace import (  # noqa: E402
    LIST_FILES_MAX_LIMIT,
    LIST_FILES_MAX_RESPONSE_BYTES,
    LIST_FILES_PAGINATION_CONTRACT,
    LIST_FILES_PAGINATION_CONTRACT_SHA256,
)


AMENDMENT_PATH = ROOT / trigger.AMENDMENT_PATH
INVENTORY_PATH = ROOT / trigger.INVENTORY_PATH
READINESS_PATH = ROOT / "artifacts/trimem_v1/readiness_requirements.json"
TOOL_LOCK_PATH = ROOT / "configs/trimem_v1/tool_environment_lock.json"
CREDENTIAL_FREE_PATH = ROOT / "artifacts/trimem_v1/credential_free_e2e"
COMPANY_MANIFEST_PATH = ROOT / "COMPANY_HANDOFF_MANIFEST.json"
REQUEST_ONLY_FIXTURE_RELATIVE = (
    "artifacts/trimem_v1/development_tuning_exec/exec-009/"
    "request-only-boundary-fixture.json"
)

TOOL_LOCK_SOURCE_PATHS = (
    "src/enterprise_memory/trimem/runtime_lock.py",
    "src/enterprise_memory/trimem/accounting.py",
    "src/enterprise_memory/trimem/agent_runtime.py",
    "src/enterprise_memory/trimem/checkpoint.py",
    "src/enterprise_memory/trimem/context_projection.py",
    "src/enterprise_memory/trimem/credential_free.py",
    "src/enterprise_memory/trimem/function_tools.py",
    "src/enterprise_memory/trimem/gateway.py",
    "src/enterprise_memory/trimem/git_workspace.py",
    "src/enterprise_memory/trimem/production_runtime.py",
    "src/enterprise_memory/trimem/workspace.py",
)

# Explicit and reviewable: no working-tree walk determines research authority.
IMPLEMENTATION_PATHS = (
    ".gitattributes",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json",
    (
        "artifacts/trimem_v1/development_tuning_exec/exec-009/"
        "bounded-short-term-context-failure-receipt.json"
    ),
    "artifacts/trimem_v1/development_tuning_exec/exec-009/request-only-boundary-fixture.json",
    "artifacts/trimem_v1/readiness_requirements.json",
    "configs/trimem_v1/m2_candidate_bundles.json",
    "configs/trimem_v1/tool_environment_lock.json",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_009_BOUNDED_CONTEXT_FAILURE.md",
    "scripts/trimem_action_canary.py",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_context_roundtrip.py",
    "scripts/trimem_d19_reseal.py",
    "scripts/trimem_development_trigger_d19.py",
    "scripts/trimem_development_trigger_preflight.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_public_artifact.py",
    "scripts/trimem_verify_ready.py",
    "src/enterprise_memory/trimem/accounting.py",
    "src/enterprise_memory/trimem/agent_runtime.py",
    "src/enterprise_memory/trimem/checkpoint.py",
    "src/enterprise_memory/trimem/context_projection.py",
    "src/enterprise_memory/trimem/credential_free.py",
    "src/enterprise_memory/trimem/function_tools.py",
    "src/enterprise_memory/trimem/gateway.py",
    "src/enterprise_memory/trimem/git_workspace.py",
    "src/enterprise_memory/trimem/production_runtime.py",
    "src/enterprise_memory/trimem/runtime_lock.py",
    "src/enterprise_memory/trimem/scientific_terminal.py",
    "src/enterprise_memory/trimem/workspace.py",
    "tests/openai/test_openai_response_outcomes.py",
    "tests/trimem/e2e/test_full_replay.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_d16_native_action.py",
    "tests/unit/test_trimem_d17_approval_cap_integration.py",
    "tests/unit/test_trimem_d18_terminal_contract_integration.py",
    "tests/unit/test_trimem_d19_bounded_short_term_context.py",
    "tests/unit/test_trimem_d19_failed_cell_resume.py",
    "tests/unit/test_trimem_d19_list_files_pagination.py",
    "tests/unit/test_trimem_d19_model_preflight.py",
    "tests/unit/test_trimem_d19_request_only_resume.py",
    "tests/unit/test_trimem_d19_terminal_contract.py",
    "tests/unit/test_trimem_d19_trigger.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_git_workspace.py",
    "tests/unit/test_trimem_production_runtime.py",
    "tests/unit/test_trimem_runtime_boundaries.py",
)


class D19ResealError(ValueError):
    """A D1.9 local reseal invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def pretty_bytes(value: Any) -> bytes:
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


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_bytes(relative: str) -> bytes:
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise D19ResealError(f"required regular source file is missing: {relative}")
    return path.read_bytes()


def source_record(relative: str) -> dict[str, Any]:
    raw = source_bytes(relative)
    return {"bytes": len(raw), "sha256": sha256(raw)}


def read_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise D19ResealError(f"duplicate JSON key: {path}:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_bytes().decode("utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D19ResealError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise D19ResealError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pretty_bytes(value))


def git_blob(commit: str, relative: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise D19ResealError(f"missing immutable Git blob: {commit}:{relative}")
    return completed.stdout


def verify_tracked_hygiene() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    forbidden: list[str] = []
    for token in completed.stdout.split(b"\0"):
        if not token:
            continue
        try:
            relative = token.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise D19ResealError("tracked path is not UTF-8") from exc
        parts = relative.split("/")
        if (
            relative.endswith((".pyc", ".pyo"))
            or any(part == "__pycache__" for part in parts)
            or any(part in {"build", "dist"} for part in parts)
            or any(part.endswith(".egg-info") for part in parts)
        ):
            forbidden.append(relative)
    if forbidden:
        raise D19ResealError(f"tracked build artifacts are forbidden: {forbidden}")


def verify_historical_boundaries() -> dict[str, str]:
    verify_tracked_hygiene()
    if (ROOT / trigger.SENTINEL_PATH).exists():
        raise D19ResealError("_010 must not exist in the D1.9 correction source")
    for relative, expected in trigger.HISTORICAL_REQUEST_SHA256.items():
        observed = sha256(source_bytes(relative))
        if observed != expected:
            raise D19ResealError(f"historical request changed: {relative}")
    if source_bytes("COMPANY_HANDOFF_MANIFEST.json") != git_blob(
        trigger.PREVIOUS_EXECUTION_HEAD, "COMPANY_HANDOFF_MANIFEST.json"
    ):
        raise D19ResealError("product COMPANY_HANDOFF_MANIFEST.json was rewritten")
    preserved: dict[str, str] = {}
    for relative in trigger.PRESERVED_PATHS:
        raw = source_bytes(relative)
        if raw != git_blob(trigger.PREVIOUS_EXECUTION_HEAD, relative):
            raise D19ResealError(f"frozen scientific input changed: {relative}")
        preserved[relative] = sha256(raw)
    return preserved


def refresh_tool_environment_lock() -> None:
    value = read_json(TOOL_LOCK_PATH)
    lock = RuntimeLock()
    value["runtime_lock_manifest"] = lock.to_manifest()
    value["runtime_lock_content_hash"] = lock.content_hash
    value["source_files"] = {
        relative: source_record(relative) for relative in TOOL_LOCK_SOURCE_PATHS
    }
    write_json(TOOL_LOCK_PATH, value)


def refresh_credential_free_bundle() -> None:
    """Generate first, then exactly replace the validated canonical directory."""

    repository_root = ROOT.resolve(strict=True)
    expected = repository_root / "artifacts/trimem_v1/credential_free_e2e"
    destination = CREDENTIAL_FREE_PATH.resolve()
    if (
        CREDENTIAL_FREE_PATH.is_symlink()
        or destination != expected
        or repository_root not in destination.parents
    ):
        raise D19ResealError("credential-free replacement target is not canonical")
    temporary = Path(
        tempfile.mkdtemp(
            prefix=".trimem-d19-credential-free-",
            dir=CREDENTIAL_FREE_PATH.parent,
        )
    ).resolve()
    if temporary.parent != destination.parent or temporary == destination:
        raise D19ResealError("credential-free temporary directory is unsafe")
    try:
        report = run_credential_free_e2e(temporary)
        if (
            report.get("status") != "PASS"
            or report.get("paid_model_calls") != 0
            or report.get("official_grader_execution") is not False
        ):
            raise D19ResealError("credential-free E2E did not remain zero-cost")
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists() or destination.is_symlink():
            raise D19ResealError("canonical credential-free target is not a directory")
        shutil.move(str(temporary), str(destination))
    finally:
        if temporary.is_dir():
            shutil.rmtree(temporary)


def semantic_contract_preimages() -> dict[str, Any]:
    return {
        "function_tool_schema_sha256": list(FUNCTION_TOOLS),
        "list_files_pagination_contract_sha256": LIST_FILES_PAGINATION_CONTRACT,
        "model_visible_observation_projection_sha256": (
            model_visible_observation_projection_contract()
        ),
        "prompt_context_contract_sha256": prompt_context_contract(),
        "request_lifecycle_contract_sha256": REQUEST_LIFECYCLE_CONTRACT,
        "resume_automaton_sha256": RESUME_AUTOMATON,
    }


def build_contracts() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    contracts = {
        "function_tool_schema_sha256": FUNCTION_TOOLS_SHA256,
        "list_files_pagination_contract_sha256": (
            LIST_FILES_PAGINATION_CONTRACT_SHA256
        ),
        "model_visible_observation_projection_sha256": (
            MODEL_VISIBLE_OBSERVATION_PROJECTION_SHA256
        ),
        "prompt_context_contract_sha256": PROMPT_CONTEXT_CONTRACT_SHA256,
        "request_lifecycle_contract_sha256": REQUEST_LIFECYCLE_CONTRACT_SHA256,
        "resume_automaton_sha256": RESUME_AUTOMATON_SHA256,
        "runner_sha256": sha256(source_bytes("scripts/trimem_benchmark_run.py")),
        "workflow_sha256": sha256(
            source_bytes(".github/workflows/trimem-benchmark.yml")
        ),
        "credential_free_bundle_sha256": sha256(
            source_bytes(
                "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
            )
        ),
    }
    preimages = semantic_contract_preimages()
    documents: dict[str, dict[str, Any]] = {}
    for name in trigger.CONTRACT_FIELDS:
        if name in trigger.SEMANTIC_CONTRACT_SOURCE_PATHS:
            paths = trigger.SEMANTIC_CONTRACT_SOURCE_PATHS[name]
            preimage = preimages[name]
            if sha256(canonical_bytes(preimage)) != contracts[name]:
                raise D19ResealError(f"semantic contract hash drift: {name}")
            kind = "canonical-json"
        else:
            paths = (trigger.RAW_FILE_CONTRACT_PATHS[name],)
            preimage = None
            kind = "raw-file-bytes"
        documents[name] = {
            "algorithm": "sha256",
            "canonical_preimage": preimage,
            "preimage_kind": kind,
            "sha256": contracts[name],
            "source_paths": list(paths),
            "source_sha256": {
                relative: sha256(source_bytes(relative)) for relative in paths
            },
        }
    return contracts, documents


def validate_readiness() -> None:
    readiness = read_json(READINESS_PATH)
    current = read_json(ROOT / trigger.PREVIOUS_RECEIPT_PATH)
    authority = readiness.get("development_authorization_boundary")
    status = readiness.get("current_status")
    if readiness.get("current_development_execution_failure") != current:
        raise D19ResealError("readiness does not embed the exact _009 receipt")
    if not (
        isinstance(status, Mapping)
        and status.get("DEV_SCIENTIFIC_STATUS")
        == "INTERRUPTED_BEFORE_FIRST_TERMINAL_CELL"
        and status.get("FAILURE_SUBTYPE") == trigger.PREVIOUS_FAILURE_SUBTYPE
        and status.get("PERFORMANCE") == "NOT_MEASURED"
        and isinstance(authority, Mapping)
        and authority.get("amendment_classification")
        == trigger.AMENDMENT_CLASSIFICATION
        and authority.get("recovery_request_id") == trigger.REQUEST_ID
        and authority.get("request_009_attempt_one_consumed") is True
        and authority.get("request_010_allowed_after_exact_remote_gates") is True
        and authority.get("request_010_attempt_one_consumed") is False
    ):
        raise D19ResealError("readiness D1.9 status/authority boundary differs")


def build_amendment(
    *,
    preserved: Mapping[str, str],
    implementation: Mapping[str, str],
    contracts: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema": trigger.AMENDMENT_SCHEMA,
        "status": trigger.AMENDMENT_STATUS,
        "classification": trigger.AMENDMENT_CLASSIFICATION,
        "endpoint_before_fresh_execution": "TRIMEM_V1_DEV_INCOMPLETE",
        "completed_scientific_cells_before_correction": 0,
        "performance_result_existed_before_correction": False,
        "primary_failure": trigger.PREVIOUS_FAILURE_SUBTYPE,
        "contributing_factors": [
            "UNPAGINATED_LIST_FILES",
            "EXACT_TOOL_RESULT_REINJECTED_IN_FULL",
            "ALL_PRIOR_TOOL_HISTORY_REINJECTED_EVERY_TURN",
            "TEXTUAL_TOOL_SCHEMA_DUPLICATES_NATIVE_FUNCTION_SCHEMA",
            "REQUEST_EVENT_WRITTEN_BEFORE_LOCAL_BUDGET_PREFLIGHT",
            "SOLVE_REQUEST_ONLY_SUFFIX_NOT_RECOVERABLE",
        ],
        "historical_run": {
            "id": trigger.PREVIOUS_RUN_ID,
            "attempt": 1,
            "source_head": trigger.PREVIOUS_SOURCE_HEAD,
            "head_sha": trigger.PREVIOUS_EXECUTION_HEAD,
            "request_path": trigger.PREVIOUS_SENTINEL_PATH,
            "request_raw_sha256": trigger.PREVIOUS_SENTINEL_SHA256,
            "failure_receipt_path": trigger.PREVIOUS_RECEIPT_PATH,
            "failure_receipt_raw_sha256": sha256(
                source_bytes(trigger.PREVIOUS_RECEIPT_PATH)
            ),
            "failure_report_path": trigger.PREVIOUS_REPORT_PATH,
            "failure_report_raw_sha256": sha256(
                source_bytes(trigger.PREVIOUS_REPORT_PATH)
            ),
            "request_only_fixture_path": REQUEST_ONLY_FIXTURE_RELATIVE,
            "request_only_fixture_raw_sha256": sha256(
                source_bytes(REQUEST_ONLY_FIXTURE_RELATIVE)
            ),
            "evidence_artifacts": read_json(
                ROOT / trigger.PREVIOUS_RECEIPT_PATH
            ).get("evidence_artifacts"),
            "stream": "M2-baseline",
            "target": "swebench_verified--django__django-16100",
            "terminal_cells": 0,
            "planned_cells": 72,
            "official_grader_runs": 0,
            "performance_measured": False,
            "scientific_usage": {
                "decomposition_calls": 1,
                "solve_calls": 7,
                "extraction_calls": 0,
                "paid_model_calls": 8,
                "input_tokens": 60_546,
                "cached_input_tokens": 0,
                "output_tokens": 7_448,
                "reasoning_tokens": 1_597,
                "total_usd": "0.078925500000",
            },
            "canary_usage": {
                "paid_model_calls": 1,
                "input_tokens": 880,
                "cached_input_tokens": 0,
                "output_tokens": 51,
                "reasoning_tokens": 35,
                "total_usd": "0.000889500000",
            },
            "request_only_resume": {
                "step": 8,
                "provider_response_present": False,
                "paid_call_for_step": False,
                "ledger_reservation_for_step": False,
            },
        },
        "context_limits": {
            "list_files_max_limit": LIST_FILES_MAX_LIMIT,
            "list_files_max_response_bytes": LIST_FILES_MAX_RESPONSE_BYTES,
            "max_model_visible_tool_history_bytes": (
                MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES
            ),
            "max_solve_prompt_utf8_bytes": MAX_SOLVE_PROMPT_UTF8_BYTES,
            "max_extraction_prompt_utf8_bytes": (
                MAX_EXTRACTION_PROMPT_UTF8_BYTES
            ),
            "max_ordinary_input_bound": MAX_ORDINARY_INPUT_BOUND,
            "frozen_per_call_conservative_bound": 262_000,
            "task_arm_input_cap": 500_000,
        },
        "pre_send_budget_preflight": {
            "ordering": [
                "construct_exact_request",
                "deterministic_prompt_projection",
                "read_only_budget_preflight",
                "append_model_request",
                "create_invocation_journal",
                "atomic_reservation_recheck",
                "provider_send_started",
                "provider_request",
            ],
            "cell_scoped": [
                "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
                "TASK_ARM_INPUT_POOL_EXHAUSTED",
                "TASK_ARM_MODEL_CALL_POOL_EXHAUSTED",
                "TASK_ROLE_OUTPUT_POOL_EXHAUSTED",
                "TASK_TOTAL_OUTPUT_POOL_EXHAUSTED",
            ],
            "global": [
                "PHASE_MODEL_CALL_CAP_EXHAUSTED",
                "PHASE_INPUT_CAP_EXHAUSTED",
                "PHASE_OUTPUT_CAP_EXHAUSTED",
                "PHASE_USD_CAP_EXHAUSTED",
                "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
            ],
            "preflight_failure_charge": {
                "calls": 0,
                "tokens": 0,
                "total_usd": 0,
            },
        },
        "request_resume": {
            "checkpoint_phases": {
                "decompose": "DECOMPOSE_PREPARED",
                "solve": "RECALL_PREPARED",
                "extract": "GRADED_OR_CELL_FAILURE_GRADED_REQUEST_SUFFIX",
            },
            "covered_call_kinds": ["decompose", "solve", "extract"],
            "contract_sha256": contracts["request_lifecycle_contract_sha256"],
            "automaton_sha256": contracts["resume_automaton_sha256"],
            "request_only_not_sent": "SEND_EXACTLY_ONCE_NO_DUPLICATE_EVENT",
            "send_started_without_terminal": (
                "DO_NOT_RETRY_SETTLE_CONSERVATIVELY_AND_CONTAIN_CELL"
            ),
            "terminal_journal": "REPLAY_WITH_ZERO_PROVIDER_CALLS",
        },
        "cell_containment": {
            "context_failure_status": "CELL_SCIENTIFIC_FAILURE",
            "partial_patch_preferred": True,
            "canonical_failed_cell_noop_fallback": True,
            "official_grader_required": True,
            "denominator_retained": True,
            "continue_next_cell": True,
            "phase_integrity_failures_global": True,
        },
        "causal_boundary": {
            "correction_kind": "DETERMINISTIC_LOCAL_RUNTIME_CONTRACT",
            "same_policy_all_streams": True,
            "long_term_memory_policy_changed": False,
            "model_or_reasoning_changed": False,
            "scientific_result_available": False,
        },
        "scientific_scope_lock": {
            "model_id": "gpt-5.4-mini-2026-03-17",
            "reasoning_effort": "medium",
            "development_targets": 12,
            "heldout_targets": 27,
            "streams": [
                "M2-baseline",
                "M2-precision",
                "M2-recall",
                "M2-balanced",
                "M0",
                "M1",
            ],
            "task_arm_runs": 72,
            "official_graders": 72,
            "max_model_calls_per_task_arm": 26,
            "solve_per_call_output_cap": 16_384,
            "solve_task_output_pool": 49_152,
            "total_task_output_pool": 65_536,
            "phase_model_call_cap": 1_873,
            "phase_input_token_cap": 36_004_096,
            "phase_output_token_cap": 4_720_640,
            "phase_total_usd_cap": 50.0,
            "budget_increased": False,
        },
        "preserved_sha256": dict(sorted(preserved.items())),
        "implementation_sha256": dict(sorted(implementation.items())),
        "contracts": dict(contracts),
        "finalization_placeholders": {
            "final_correction_source_head": "BOUND_EXTERNALLY_AS_010_SOURCE_HEAD",
            "final_research_freeze_sha256": "BOUND_EXTERNALLY_BY_010_FREEZE_SHA256",
            "development_tuning_exec_request_010_sha256": (
                "NOT_CREATED_UNTIL_EXACT_HEAD_REMOTE_GATES_PASS"
            ),
            "exact_head_remote_ci_evidence": (
                "BOUND_EXTERNALLY_IN_010_REMOTE_GATE_EVIDENCE"
            ),
        },
    }


def build_inventory(
    *,
    implementation: Mapping[str, str],
    contracts: Mapping[str, str],
    contract_documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    company_raw = source_bytes("COMPANY_HANDOFF_MANIFEST.json")
    company_manifest = read_json(COMPANY_MANIFEST_PATH)
    request_only_fixture = read_json(ROOT / REQUEST_ONLY_FIXTURE_RELATIVE)
    return {
        "schema": trigger.INVENTORY_SCHEMA,
        "status": trigger.AMENDMENT_STATUS,
        "classification": trigger.AMENDMENT_CLASSIFICATION,
        "implementation_sha256": dict(sorted(implementation.items())),
        "contracts": dict(contracts),
        "contract_documents": dict(contract_documents),
        "historical_request_raw_sha256": dict(
            trigger.HISTORICAL_REQUEST_SHA256
        ),
        "historical_request_only_fixture": {
            "path": REQUEST_ONLY_FIXTURE_RELATIVE,
            **source_record(REQUEST_ONLY_FIXTURE_RELATIVE),
            "schema": request_only_fixture.get("schema"),
            "status": request_only_fixture.get("status"),
            "restricted_payload_committed": request_only_fixture.get(
                "custody", {}
            ).get("restricted_payload_committed"),
            "prompt_content_policy": request_only_fixture.get(
                "replay_contract", {}
            ).get("prompt_content_policy"),
            "historical_function_tools_sha256": request_only_fixture.get(
                "replay_contract", {}
            ).get("function_tools_sha256"),
            "live_function_tools_sha256": contracts[
                "function_tool_schema_sha256"
            ],
            "compatibility_path": "EXPLICIT_LEGACY_REPLAY_ONLY",
        },
        "company_handoff_separation": {
            "manifest_rewritten": False,
            "manifest_bytes": len(company_raw),
            "manifest_raw_sha256": sha256(company_raw),
            "product_manifest_authority": company_manifest.get("manifest_scope"),
            "product_hash_basis": company_manifest.get("hash_basis"),
            "rejected_if_tracked": company_manifest.get("rejected_if_tracked"),
            "research_state_authority": "artifacts/trimem_v1/freeze.json",
            "hash_basis": "explicit research allowlist; no live tree walk",
        },
        "credential_free_gate": {
            "context_roundtrip_required": True,
            "credential_free_replay_required": True,
            "real_provider_calls": 0,
            "paid_model_calls": 0,
            "official_graders": 0,
            "benchmark_images": 0,
            "total_usd": 0,
        },
        "authority_boundary": {
            "request_009_rerun_allowed": False,
            "request_009_attempt_2_allowed": False,
            "request_010_created": False,
            "request_011_authorized": False,
            "heldout_authorized": False,
            "ablation_authorized": False,
            "merge_tag_release_authorized": False,
        },
    }


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    preserved = verify_historical_boundaries()
    validate_readiness()
    implementation = {
        relative: sha256(source_bytes(relative)) for relative in IMPLEMENTATION_PATHS
    }
    contracts, documents = build_contracts()
    amendment = build_amendment(
        preserved=preserved,
        implementation=implementation,
        contracts=contracts,
    )
    inventory = build_inventory(
        implementation=implementation,
        contracts=contracts,
        contract_documents=documents,
    )
    return amendment, inventory


def write_all() -> None:
    verify_historical_boundaries()
    trimem_m2_candidates.generate()
    refresh_tool_environment_lock()
    refresh_credential_free_bundle()
    amendment, inventory = build_artifacts()
    write_json(AMENDMENT_PATH, amendment)
    write_json(INVENTORY_PATH, inventory)
    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    amendment, inventory = build_artifacts()
    if read_json(AMENDMENT_PATH) != amendment:
        raise D19ResealError("D1.9 bounded-context amendment is stale")
    if read_json(INVENTORY_PATH) != inventory:
        raise D19ResealError("D1.9 bounded-context inventory is stale")
    trimem_m2_candidates.load_bundle()
    tool = read_json(TOOL_LOCK_PATH)
    lock = RuntimeLock()
    if not (
        tool.get("runtime_lock_manifest") == lock.to_manifest()
        and tool.get("runtime_lock_content_hash") == lock.content_hash
        and tool.get("source_files")
        == {
            relative: source_record(relative)
            for relative in TOOL_LOCK_SOURCE_PATHS
        }
    ):
        raise D19ResealError("tool-environment RuntimeLock is stale")
    verified_bundle = trimem_verify_credential_free.verify_bundle(
        CREDENTIAL_FREE_PATH
    )
    if not (
        verified_bundle.get("status") == "PASS"
        and verified_bundle.get("paid_model_calls") == 0
        and verified_bundle.get("official_grader_execution") is False
    ):
        raise D19ResealError("credential-free bundle verification differs")
    trimem_freeze.check_freeze(ROOT)
    return {
        "status": "PASS",
        "d1_9_classification": trigger.AMENDMENT_CLASSIFICATION,
        "historical_requests": len(trigger.HISTORICAL_REQUEST_SHA256),
        "paid_model_calls": 0,
        "official_graders": 0,
        "benchmark_images": 0,
        "total_usd": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.write:
            write_all()
            result = check_all()
        else:
            result = check_all()
    except (D19ResealError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
