"""Fail closed before the one-time branch-local DEVELOPMENT_TUNING run.

The committed request is a zero-authority sentinel.  It may create exactly one
GitHub Actions run, but the protected job cannot execute until a separate
external approval binds that run, its first attempt, the execution commit, the
sentinel's source commit, the research freeze, and the exact phase caps.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping


EXPECTED_EVENT = "push"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_REF = "refs/heads/codex/trimem-coder-v1"
EXPECTED_WORKFLOW_REF = (
    "Scuttie/enterprise-shared-memory-poc/.github/workflows/"
    "trimem-benchmark.yml@refs/heads/codex/trimem-coder-v1"
)
EXPECTED_PHASE = "DEVELOPMENT_TUNING"
REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_001"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.0"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/"
    "DEVELOPMENT_TUNING_EXEC_REQUEST_001.json"
)
WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"
FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
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
PREFLIGHT_PATH = "scripts/trimem_development_trigger_preflight.py"
BENCHMARK_RUNNER_PATH = "scripts/trimem_benchmark_run.py"
APPROVAL_VALIDATOR_PATH = "scripts/trimem_exec_approval.py"
APPROVED_PHASE_PATH = "scripts/trimem_approved_phase.py"
FREEZE_SCRIPT_PATH = "scripts/trimem_freeze.py"
CLEANUP_SCRIPT_PATH = "scripts/trimem_cleanup_exec.py"
TRIGGER_TEST_PATH = "tests/unit/test_trimem_development_trigger.py"
MATRIX_PATH = "scripts/trimem_benchmark_matrix.py"
PUBLIC_ARTIFACT_PATH = "scripts/trimem_public_artifact.py"
RESUME_DRIVER_PATH = "scripts/trimem_run_with_resume.py"

AUTHORIZATION_SEMANTICS = (
    "The sentinel creates one run but does not authorize protected execution."
)
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_APPROVED_ONCE"
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
    "request_schema_sha256": "ef820f9e7b0e414a3214a0dc53b96bbdb68e021016c8d0e22a133efa6c54f61c",
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
    "output_tokens": 3_796_992,
    "paid_model_calls": 1_872,
    "solve_calls": 1_728,
    "task_arm_runs": 72,
    "total_usd": 50.0,
    "uncached_token_cost_ceiling_usd": 44.086464,
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
    "scope": "D1.1_BEFORE_DEVELOPMENT_EXECUTION",
    "solve_calls": 0,
    "target_image_pulls": 0,
    "task_arm_runs": 0,
    "total_usd": 0.0,
}
PROHIBITED_ACTIONS = [
    "HELDOUT_BENCHMARK",
    "additional_development_targets",
    "automatic_next_phase_execution",
    "candidate_addition",
    "component_ablation",
    "grader_smoke_rerun",
    "merge_tag_or_release",
    "model_replacement",
    "second_development_dispatch_or_rerun",
    "target_replacement",
]
EXPECTED_TARGET_SET_SHA256 = (
    "e7da59b3c2638c89da4e333a7391851e992c122acac11bc9edf60619cfd5eff2"
)
EXPECTED_EXECUTION_SEQUENCE_SHA256 = (
    "89d222638aa603221c1a18b8ab788ae49d51708375b1fe5ec03d1102196289dd"
)
EXPECTED_FROZEN_INPUT_SHA256 = {
    MODEL_LOCK_PATH: "f5e932696d31d1cb7185b32b67c38e4c9cbbfedd79783adfb8faddc7b90abfe0",
    COST_PLAN_PATH: "d54b70e8c700cedff987efa713aeddf724059b7320bbe8fc1970ca9c0f69a86e",
    POLICY_REQUEST_PATH: "05e19aeec6630f2362c481a86eb66d0e630041794866a638c3ebbf07e5ccbba4",
    DEVELOPMENT_MANIFEST_PATH: "44e52137dad68618396c15d6b3c2221a683f89988e361efb2966e244ba230900",
    M2_CANDIDATE_MANIFEST_PATH: "3248b15e3f9f7293cacfea1f13fcfd354dbb804d34a1ea40dce6d8c1b881a6de",
    SELECTION_PLAN_PATH: "dddc421120d16f241a2941afbd67190df4b3be6cefeab99e37437abf7133dcf4",
    GRADER_LOCK_PATH: "853d42e86c2caf1449f28bba9143741e3ccff5e75bbe790115a0d9c746014fbb",
    IMAGE_LOCK_PATH: "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb",
    MODEL_PRICING_AMENDMENT_PATH: "19caede5a601f8d0ebc1267dbb393b9b707aae37e144a31a9346087d2c320cee",
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
    "cost_plan_sha256": COST_PLAN_PATH,
    "development_manifest_sha256": DEVELOPMENT_MANIFEST_PATH,
    "freeze_sha256": FREEZE_PATH,
    "grader_lock_sha256": GRADER_LOCK_PATH,
    "image_lock_sha256": IMAGE_LOCK_PATH,
    "m2_candidate_manifest_sha256": M2_CANDIDATE_MANIFEST_PATH,
    "model_lock_sha256": MODEL_LOCK_PATH,
    "model_pricing_amendment_sha256": MODEL_PRICING_AMENDMENT_PATH,
    "selection_plan_sha256": SELECTION_PLAN_PATH,
}
FREEZE_CLOSURE_PATHS = (
    WORKFLOW_PATH,
    MODEL_LOCK_PATH,
    COST_PLAN_PATH,
    POLICY_REQUEST_PATH,
    DEVELOPMENT_MANIFEST_PATH,
    M2_CANDIDATE_MANIFEST_PATH,
    SELECTION_PLAN_PATH,
    GRADER_LOCK_PATH,
    IMAGE_LOCK_PATH,
    BENCHMARK_ENVIRONMENT_PROTECTION_PATH,
    PREFLIGHT_PATH,
    BENCHMARK_RUNNER_PATH,
    APPROVAL_VALIDATOR_PATH,
    APPROVED_PHASE_PATH,
    FREEZE_SCRIPT_PATH,
    CLEANUP_SCRIPT_PATH,
    TRIGGER_TEST_PATH,
    MATRIX_PATH,
    PUBLIC_ARTIFACT_PATH,
    RESUME_DRIVER_PATH,
)
REQUEST_FIELDS = frozenset(
    {
        "actual_execution_authorized",
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


def _material(repository: Path, commit: str) -> dict[str, bytes]:
    paths = set(BOUND_PATHS.values()) | set(FREEZE_CLOSURE_PATHS)
    return {path: _commit_bytes(repository, commit, path) for path in paths}


def _json_material(raw: Mapping[str, bytes], path: str) -> dict[str, Any]:
    try:
        return strict_json_object(raw[path])
    except DevelopmentTriggerError as exc:
        raise DevelopmentTriggerError(f"invalid committed JSON at {path}: {exc}") from exc


def _validate_frozen_material(
    repository: Path, commit: str
) -> tuple[dict[str, bytes], dict[str, str], dict[str, Any]]:
    raw = _material(repository, commit)
    for path, expected_sha256 in EXPECTED_FROZEN_INPUT_SHA256.items():
        _require(
            hashlib.sha256(raw[path]).hexdigest() == expected_sha256,
            f"frozen scientific or model/pricing input changed: {path}",
        )
    model = _json_material(raw, MODEL_LOCK_PATH)
    cost = _json_material(raw, COST_PLAN_PATH)
    policy = _json_material(raw, POLICY_REQUEST_PATH)
    manifest = _json_material(raw, DEVELOPMENT_MANIFEST_PATH)
    candidates = _json_material(raw, M2_CANDIDATE_MANIFEST_PATH)
    selection = _json_material(raw, SELECTION_PLAN_PATH)
    grader = _json_material(raw, GRADER_LOCK_PATH)
    images = _json_material(raw, IMAGE_LOCK_PATH)
    freeze = _json_material(raw, FREEZE_PATH)
    amendment = _json_material(raw, MODEL_PRICING_AMENDMENT_PATH)
    environment = _json_material(raw, BENCHMARK_ENVIRONMENT_PROTECTION_PATH)

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
        committed = _commit_bytes(repository, commit, path)
        _require(
            hashlib.sha256(committed).hexdigest() == expected_sha256,
            f"pre-amendment scientific contract changed: {path}",
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
        == "ef820f9e7b0e414a3214a0dc53b96bbdb68e021016c8d0e22a133efa6c54f61c"
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
    for field in (
        "api_calls",
        "decomposition_calls",
        "extraction_calls",
        "input_tokens",
        "model_calls",
        "model_gateway_calls",
        "output_tokens",
        "paid_model_calls",
        "solve_calls",
        "task_arm_runs",
        "total_usd",
    ):
        _require(actual.get(field) == 0, f"pre-DEV actual {field} is not zero")
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
    repository: Path, *, source_head: str, material_commit: str | None = None
) -> dict[str, Any]:
    _require(HEX40.fullmatch(source_head) is not None, "source_head is not a commit SHA")
    commit = source_head if material_commit is None else material_commit
    _require(HEX40.fullmatch(commit) is not None, "material commit is not a commit SHA")
    _raw, bindings, workload = _validate_frozen_material(repository, commit)
    payload: dict[str, Any] = {
        "actual_execution_authorized": False,
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
    workflow = _commit_bytes(repository, commit, WORKFLOW_PATH).decode("utf-8")
    start = workflow.find("  branch-trigger-preflight:")
    end = workflow.find("  frozen-serial-phase:")
    _require(0 <= start < end, "workflow has no isolated branch preflight job")
    preflight = workflow[start:end]
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
    document = build_request_document(repository, source_head=source_head)
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
