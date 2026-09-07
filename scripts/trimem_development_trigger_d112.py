"""Fail-closed one-time DEVELOPMENT_TUNING ``_012`` activation trigger.

The D1.12 activation source is a credential-free strict descendant of the
immutable D1.11 correction source.  This module creates a zero-authority
request only after the mixed-event exact-head gate set succeeds.  The
subsequent protected workflow still requires a distinct, fresh, run-bound
external approval for attempt 1.  Request-creation authority is never treated
as execution authority.

This module is deliberately self-contained.  In particular, it does not
import the benchmark runner, matrix, readiness validator, or D1.12 resealer;
all four import this module during normal validation.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from trimem_install_pinned_gh import load_gh_cli_lock, verify_installed_gh


EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_REF = f"refs/heads/{EXPECTED_BRANCH}"
EXPECTED_WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"
EXPECTED_WORKFLOW_REF = (
    "Scuttie/enterprise-shared-memory-poc/.github/workflows/"
    "trimem-benchmark.yml@refs/heads/codex/trimem-coder-v1"
)
EXPECTED_PHASE = "DEVELOPMENT_TUNING"
PULL_REQUEST_NUMBER = 18
EXPECTED_BASE_BRANCH = "main"
EXPECTED_BASE_HEAD = "ce10ab49586db7a859fbe5cca93051b93f9f5b55"

STARTING_SOURCE_HEAD = "fa1af529a2af4f8ba606b01410434412881f3d27"
STARTING_FREEZE_SHA256 = (
    "e2964255c9c214f29c04bc8df2a5fe275601d43a40f8cad6b1fc926b8cf73739"
)
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.12"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_012.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_011.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "75acaaa8f1f2f0dc138530dfc533df440e2c70f4ee885732b8297a8150de2fa0"
)
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "98cee4e48996d6027b0441649d41de726bb5f83eed9f52fbe888a00772f8b8b9"
)
PREVIOUS_SOURCE_HEAD = "155fe314631ef74828ea98b562036bdb0adca495"
PREVIOUS_EXECUTION_HEAD = "e54d04b0af9e738d311c389dc89cfd510fd7065b"
PREVIOUS_RUN_ID = 34_047_573_548
PREVIOUS_FAILURE_SUBTYPE = "MUTABLE_HISTORICAL_PULL_REQUEST_ASSOCIATION"
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-012"
CHECKOUT_ACTION_SHA = "11bd71901bbe5b1630ceea73d27597364c9af683"
SETUP_PYTHON_ACTION_SHA = "a26af69be951a213d495a4c3e4e4022e16d87065"
CODEQL_ACTION_SHA = "6f5948dfacef28e207b48d0905cf90c03365536d"

MODEL_ID = "gpt-5.4-mini-2026-03-17"
REASONING_EFFORT = "medium"
AMENDMENT_PATH = "artifacts/trimem_v1/development_exec_012_activation_amendment.json"
AMENDMENT_SCHEMA = "trimem/development-exec-012-activation-amendment/1.0"
INVENTORY_PATH = "artifacts/trimem_v1/development_exec_012_activation_inventory.json"
INVENTORY_SCHEMA = "trimem/development-exec-012-activation-inventory/1.0"
AMENDMENT_CLASSIFICATION = "PRE_EXEC_012_ZERO_AUTHORITY_ACTIVATION"
AMENDMENT_STATUS = "FROZEN_CREDENTIAL_FREE_READY_FOR_EXEC_012_REQUEST"
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_012_REQUEST"
FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
FREEZE_SCHEMA = "trimem/freeze/1.0"
GH_CLI_LOCK_PATH = "configs/trimem_v1/gh_cli_lock.json"

REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.12"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.12"
RUNNER_DISTRIBUTION = "TriMemRunner2404"
RUNNER_NAMES = ("trimem-d112-exec", "trimem-d112-preflight")
RUNNER_ROOTS = (
    "/opt/trimem-d112-runners/exec",
    "/opt/trimem-d112-runners/preflight",
)
RUNNER_TOOL_CACHE = "/opt/trimem-runner-cache/work-ci/_tool"
EXACT_PYTHON_ROOT = f"{RUNNER_TOOL_CACHE}/Python/3.11.10/x64"
MINIMUM_RUNNER_DISK_BYTES = 500 * 1024 * 1024 * 1024
MAXIMUM_RUNNER_READINESS_AGE_SECONDS = 60 * 60
MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS = 5 * 60
REQUIRED_RUNNER_LABELS = (
    "self-hosted",
    "linux",
    "x64",
    "trimem-ubuntu-24.04",
    "trimem-benchmark",
)
STALE_RUNNER_ROOTS = (
    "/opt/actions-runner",
    "/opt/actions-runner-final",
    "/opt/trimem-actions-runner-d16-exec007",
    "/opt/trimem-d19-runners",
    "/opt/trimem-d110-runners",
)
REMOTE_GATE_SPECS = (
    (".github/workflows/ci-trimem.yml", "push", None),
    (".github/workflows/ci-trimem-grader-loader.yml", "push", None),
    (".github/workflows/ci-trimem-harness-lock.yml", "push", None),
    (".github/workflows/ci-trimem-multi-swe-contract.yml", "push", None),
    (".github/workflows/ci-trimem-e2e.yml", "push", None),
    (".github/workflows/ci-trimem-dev-toolchain.yml", "push", None),
    (".github/workflows/ci.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/codeql.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-docs.yml", "pull_request", PULL_REQUEST_NUMBER),
    (
        ".github/workflows/ci-company-package.yml",
        "pull_request",
        PULL_REQUEST_NUMBER,
    ),
    (
        ".github/workflows/ci-company-harness.yml",
        "pull_request",
        PULL_REQUEST_NUMBER,
    ),
    (
        ".github/workflows/ci-company-demo.yml",
        "pull_request",
        PULL_REQUEST_NUMBER,
    ),
)
REQUIRED_REMOTE_GATE_WORKFLOWS = tuple(spec[0] for spec in REMOTE_GATE_SPECS)

ACTIVATION_ZERO_COUNTERS = {
    "benchmark_image_pulls": 0,
    "model_generation_calls": 0,
    "model_metadata_requests": 0,
    "official_grader_runs": 0,
    "paid_calls": 0,
    "task_arm_runs": 0,
    "total_usd": 0.0,
}

DEVELOPMENT_APPROVAL_FIELDS = (
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
)

EXPECTED_STREAM_ORDER = (
    "M2-baseline",
    "M2-precision",
    "M2-recall",
    "M2-balanced",
    "M0",
    "M1",
)
EXPECTED_TARGET_ORDER = (
    "django__django-16100",
    "sympy__sympy-23262",
    "sphinx-doc__sphinx-11445",
    "matplotlib__matplotlib-25311",
    "mui__material-ui-29880",
    "ponylang__ponyc-1981",
    "clap-rs__clap-3960",
    "facebook__zstd-938",
    "sharkdp__bat-1276",
    "catchorg__Catch2-1616",
    "clap-rs__clap-3394",
    "cli__cli-869",
)
EXPECTED_DEVELOPMENT_HARD_CAP = {
    "benchmark_grader_containers": 72,
    "decomposition_calls": 72,
    "extraction_calls": 72,
    "input_tokens": 36_004_096,
    "max_input_tokens_per_task_arm": 500_000,
    "max_model_calls_per_task_arm": 26,
    "model_calls": 1_873,
    "output_tokens": 4_720_640,
    "paid_model_calls": 1_873,
    "protocol_canary_calls": 1,
    "scientific_generation_calls": 1_872,
    "solve_calls": 1_728,
    "task_arm_runs": 72,
    "total_usd": 50.0,
    "uncached_token_cost_ceiling_usd": 48.245952,
}

# File-level scope is intentionally explicit. D1.12 is an activation/control
# correction only; no frozen scientific input is permitted in this set.
ALLOWED_ACTIVATION_PATHS = frozenset(
    {
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/trimem-benchmark.yml",
        AMENDMENT_PATH,
        INVENTORY_PATH,
        "artifacts/trimem_v1/readiness_requirements.json",
        FREEZE_PATH,
        "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md",
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_d112_reseal.py",
        "scripts/trimem_development_trigger_d112.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_d112_e1_trigger.py",
        "tests/unit/test_trimem_d112_status_and_reseal.py",
        "tests/unit/test_trimem_development_trigger.py",
    }
)
REQUIRED_ACTIVATION_CHANGES = {
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    FREEZE_PATH: "M",
    "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md": "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_d112_reseal.py": "A",
    "scripts/trimem_development_trigger_d112.py": "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d112_e1_trigger.py": "A",
    "tests/unit/test_trimem_d112_status_and_reseal.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
}
EXPECTED_ACTIVATION_CRITICAL_SHA256: dict[str, str] = {}

PRESERVED_SCIENTIFIC_PATHS = (
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
    "configs/trimem_v1/m2_candidate_bundles.json",
    "configs/trimem_v1/m2_candidates/balanced.json",
    "configs/trimem_v1/m2_candidates/baseline.json",
    "configs/trimem_v1/m2_candidates/precision.json",
    "configs/trimem_v1/m2_candidates/recall.json",
    "configs/trimem_v1/m2_policy.json",
    "configs/trimem_v1/model_lock.json",
    "configs/trimem_v1/provider_output_schemas.json",
    "configs/trimem_v1/selection_plan.json",
    "configs/trimem_v1/solve_output_budget_contract.json",
    "configs/trimem_v1/tool_environment_lock.json",
    "artifacts/trimem_v1/credential_free_e2e/dqn_frozen_checkpoint.json",
)

SCIENCE_BINDING_PATHS = {
    "arms_sha256": "configs/trimem_v1/arms.json",
    "cost_plan_sha256": "configs/trimem_v1/cost_plan.json",
    "development_manifest_sha256": "configs/trimem_v1/development_manifest.json",
    "dqn_checkpoint_sha256": (
        "artifacts/trimem_v1/credential_free_e2e/dqn_frozen_checkpoint.json"
    ),
    "grader_lock_sha256": "configs/trimem_v1/grader_lock.json",
    "heldout_manifest_sha256": "configs/trimem_v1/heldout_manifest.json",
    "image_lock_sha256": "artifacts/trimem_v1/grader_image_lock.json",
    "m2_candidate_manifest_sha256": "configs/trimem_v1/m2_candidate_bundles.json",
    "m2_policy_sha256": "configs/trimem_v1/m2_policy.json",
    "model_lock_sha256": "configs/trimem_v1/model_lock.json",
    "selection_plan_sha256": "configs/trimem_v1/selection_plan.json",
    "tool_environment_lock_sha256": "configs/trimem_v1/tool_environment_lock.json",
}
ACTIVATION_BINDING_PATHS = {
    "approval_consumer_sha256": "scripts/trimem_exec_approval.py",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "d112_amendment_sha256": AMENDMENT_PATH,
    "d112_inventory_sha256": INVENTORY_PATH,
    "readiness_requirements_sha256": (
        "artifacts/trimem_v1/readiness_requirements.json"
    ),
    "trigger_reader_sha256": "scripts/trimem_development_trigger_d112.py",
}
EXECUTION_CONTRACT_PATHS = {
    "loader_environment_contract_sha256": (
        "scripts/trimem_official_harness_loader.py"
    ),
    "loader_preflight_sha256": (
        "scripts/trimem_official_harness_loader_preflight.py"
    ),
    "grader_lifecycle_sha256": "scripts/trimem_benchmark_run.py",
    "cell_commit_journal_sha256": "scripts/trimem_benchmark_run.py",
    "resume_disposition_sha256": "scripts/trimem_run_with_resume.py",
}
# Historical names remain local aliases only so the copied low-level
# validators cannot silently select a different contract set.
D110_CONTRACT_PATHS = EXECUTION_CONTRACT_PATHS
EXPECTED_D110_IMPLEMENTATION_PATHS = frozenset(
    {
        ".gitattributes",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
        ".github/workflows/ci-docs.yml",
        ".github/workflows/ci-company-package.yml",
        ".github/workflows/ci-company-harness.yml",
        ".github/workflows/ci-company-demo.yml",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem-grader-loader.yml",
        ".github/workflows/ci-trimem-harness-lock.yml",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/trimem-benchmark.yml",
        "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json",
        "artifacts/trimem_v1/readiness_requirements.json",
        "configs/trimem_v1/tool_environment_lock.json",
        "docs/TRIMEM_V1_SYSTEM.md",
        "reports/TRIMEM_D110_GRADER_LAUNCH_STREAM_COMMIT_CORRECTION.md",
        "scripts/make_handoff_manifest.py",
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_d110_reseal.py",
        "scripts/trimem_development_trigger_d110.py",
        "scripts/trimem_development_trigger_preflight.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_grader_smoke.py",
        "scripts/trimem_harness_lock.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_multi_swe_entrypoint.py",
        "scripts/trimem_official_grader.py",
        "scripts/trimem_official_harness_loader.py",
        "scripts/trimem_official_harness_loader_preflight.py",
        "scripts/trimem_run_with_resume.py",
        "scripts/trimem_verify_ready.py",
        "scripts/trimem_verify_remote_custody.py",
        "src/enterprise_memory/trimem/git_workspace.py",
        "src/enterprise_memory/trimem/production_runtime.py",
        "tests/fixtures/trimem_d110/exec_010_sanitized.json",
        "tests/unit/test_company_handoff_manifest.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_d19_trigger.py",
        "tests/unit/test_trimem_d110_official_harness_loader.py",
        "tests/unit/test_trimem_d110_resume_fail_closed.py",
        "tests/unit/test_trimem_d110_atomic_resume.py",
        "tests/unit/test_trimem_d110_checkout_custody.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d110_e1_trigger.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_grader_smoke_trigger.py",
        "tests/unit/test_trimem_grader_terminal_evidence.py",
        "tests/unit/test_trimem_harness_lock.py",
        "tests/unit/test_trimem_multi_prebuilt_evaluation.py",
        "tests/unit/test_trimem_multi_swe_probe_request.py",
        "tests/unit/test_trimem_multi_swe_preexec.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
        "tests/unit/test_trimem_production_runtime.py",
        "tests/unit/test_trimem_remote_custody.py",
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
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class DevelopmentTriggerError(ValueError):
    """The D1.12 source, request, remote gates, or branch event differs."""


# Kept as an explicit alias for diagnostics without changing the stable name
# consumed by the runner and matrix.
DevelopmentTriggerD112Error = DevelopmentTriggerError


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DevelopmentTriggerError(message)


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
                raise DevelopmentTriggerError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise DevelopmentTriggerError(f"invalid JSON constant: {value}")

    try:
        decoded = raw.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except DevelopmentTriggerError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DevelopmentTriggerError("invalid UTF-8 JSON") from exc
    require(isinstance(value, dict), "JSON root must be an object")
    return value


def strict_runner_config_json(raw: bytes) -> dict[str, Any]:
    """Parse the Actions runner's JSON config without relaxing contract JSON.

    Actions Runner 2.337.0 writes ``.runner`` with a single UTF-8 BOM.  Only
    that runner-owned file format gets this narrowly scoped normalization;
    approval, request, and evidence documents continue to use ``strict_json``
    directly and therefore continue to reject a BOM.
    """

    utf8_bom = b"\xef\xbb\xbf"
    if raw.startswith(utf8_bom):
        raw = raw[len(utf8_bom) :]
    return strict_json(raw)


def _safe_git_path(path: str) -> str:
    candidate = PurePosixPath(path)
    require(
        bool(path)
        and "\\" not in path
        and not candidate.is_absolute()
        and candidate.as_posix() == path
        and all(part not in {"", ".", ".."} for part in candidate.parts),
        "unsafe Git path",
    )
    return path


def _hermetic_git_environment() -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in (
            "COMSPEC",
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "WINDIR",
        )
        if key in os.environ
    }
    environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "LANG": "C",
            "LC_ALL": "C",
        }
    )
    return environment


def _git_prefix() -> list[str]:
    return [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.quotepath=false",
    ]


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        [*_git_prefix(), *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=_hermetic_git_environment(),
    )
    if completed.returncode != 0:
        raise DevelopmentTriggerError(
            completed.stderr.strip() or "git command failed"
        )
    return completed.stdout


def commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    path = _safe_git_path(path)
    completed = subprocess.run(
        [*_git_prefix(), "cat-file", "blob", f"{commit}:{path}"],
        cwd=repository,
        capture_output=True,
        check=False,
        env=_hermetic_git_environment(),
    )
    if completed.returncode != 0:
        raise DevelopmentTriggerError(f"required Git blob is missing: {path}")
    return completed.stdout


def _sha256_at(repository: Path, commit: str, path: str) -> str:
    return hashlib.sha256(commit_bytes(repository, commit, path)).hexdigest()


def _is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        [*_git_prefix(), "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=repository,
        capture_output=True,
        check=False,
        env=_hermetic_git_environment(),
    )
    return completed.returncode == 0


def _validate_starting_source(repository: Path) -> None:
    require(
        git(repository, "cat-file", "-t", STARTING_SOURCE_HEAD).strip()
        == "commit",
        "immutable D1.11 starting source is unavailable",
    )
    require(
        _sha256_at(repository, STARTING_SOURCE_HEAD, FREEZE_PATH)
        == STARTING_FREEZE_SHA256,
        "immutable D1.11 starting freeze differs",
    )


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, STARTING_SOURCE_HEAD, path),
            f"frozen scientific input changed during activation: {path}",
        )


def _validate_remote_gate_workflow_contracts(
    repository: Path, source_head: str
) -> None:
    """Prove that every accepted gate observes exact source bytes without secrets."""

    pull_request_paths = {
        path for path, event, _pr in REMOTE_GATE_SPECS if event == "pull_request"
    }
    for path in REQUIRED_REMOTE_GATE_WORKFLOWS:
        try:
            workflow = commit_bytes(repository, source_head, path).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DevelopmentTriggerError(
                f"remote gate workflow is not UTF-8: {path}"
            ) from exc
        require("secrets." not in workflow, f"remote gate exposes a secret: {path}")
        require(
            f"actions/checkout@{CHECKOUT_ACTION_SHA}" in workflow
            and "actions/checkout@v" not in workflow,
            f"remote gate checkout action is mutable or unpinned: {path}",
        )
        require(
            "actions/setup-python@v" not in workflow,
            f"remote gate Python setup action is mutable: {path}",
        )
        if "actions/setup-python@" in workflow:
            require(
                f"actions/setup-python@{SETUP_PYTHON_ACTION_SHA}" in workflow,
                f"remote gate Python setup action differs: {path}",
            )
        if path in pull_request_paths:
            require(
                "ref: ${{ github.event.pull_request.head.sha || github.sha }}"
                in workflow
                and "fetch-depth: 0" in workflow
                and "persist-credentials: false" in workflow,
                f"PR gate does not checkout the exact PR head: {path}",
            )
    codeql = commit_bytes(
        repository, source_head, ".github/workflows/codeql.yml"
    ).decode("utf-8")
    for action in ("init", "autobuild", "analyze"):
        require(
            codeql.count(f"github/codeql-action/{action}@{CODEQL_ACTION_SHA}") == 1
            and f"github/codeql-action/{action}@v" not in codeql,
            f"CodeQL action is mutable or differs: {action}",
        )


def _validate_contract_documents(
    repository: Path,
    source_head: str,
    inventory: Mapping[str, Any],
    contracts: Mapping[str, Any],
) -> None:
    documents = inventory.get("contract_documents")
    require(isinstance(documents, Mapping), "D1.10 contract documents are missing")
    for name, expected_path in D110_CONTRACT_PATHS.items():
        digest = contracts.get(name)
        document = documents.get(name)
        require(
            isinstance(digest, str)
            and HEX64.fullmatch(digest) is not None
            and isinstance(document, Mapping)
            and document.get("algorithm") == "sha256"
            and document.get("preimage_kind") == "raw-file-bytes"
            and document.get("source_path") == expected_path
            and document.get("sha256") == digest,
            f"D1.10 contract document differs: {name}",
        )
        raw = commit_bytes(repository, source_head, expected_path)
        require(
            document.get("bytes") == len(raw)
            and hashlib.sha256(raw).hexdigest() == digest,
            f"D1.10 contract bytes differ: {name}",
        )


def _validate_d110_seal(
    repository: Path, source_head: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    require(
        amendment.get("schema") == AMENDMENT_SCHEMA
        and inventory.get("schema") == INVENTORY_SCHEMA
        and amendment.get("classification") == AMENDMENT_CLASSIFICATION
        and inventory.get("classification") == AMENDMENT_CLASSIFICATION
        and amendment.get("status") == AMENDMENT_STATUS
        and inventory.get("status") == AMENDMENT_STATUS
        and amendment.get("endpoint") == AMENDMENT_ENDPOINT
        and inventory.get("endpoint") == AMENDMENT_ENDPOINT,
        "current D1.10 amendment/inventory identity differs",
    )
    contracts = amendment.get("contracts")
    implementation = amendment.get("implementation_sha256")
    require(
        isinstance(contracts, Mapping)
        and contracts == inventory.get("contracts")
        and isinstance(implementation, Mapping)
        and implementation == inventory.get("implementation_sha256"),
        "D1.10 amendment/inventory hashes disagree",
    )
    require(
        set(implementation) == EXPECTED_D110_IMPLEMENTATION_PATHS,
        "D1.10 implementation inventory path set differs",
    )
    _validate_contract_documents(repository, source_head, inventory, contracts)
    for path, digest in implementation.items():
        require(
            isinstance(path, str)
            and isinstance(digest, str)
            and HEX64.fullmatch(digest) is not None
            and _sha256_at(repository, source_head, path) == digest,
            f"D1.10 implementation inventory differs: {path}",
        )

    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("dev_execution_authorized") is False
        and authority.get("heldout_authorized") is False
        and authority.get("ablation_authorized") is False
        and authority.get("merge_tag_release_authorized") is False
        and authority.get("request_010_rerun_allowed") is False
        and authority.get("request_010_attempt_two_allowed") is False
        and authority.get("request_011_created") is False
        and authority.get("historical_failed_request_id")
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_010"
        and authority.get("historical_failed_request_path")
        == PREVIOUS_SENTINEL_PATH
        and authority.get("fresh_execution_request")
        == "REQUEST_011_AUTHORIZED_PENDING_EXACT_REMOTE_GATES"
        and authority.get("fresh_execution_request_creation_authorized") is True
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.10 activation authority boundary differs",
    )
    historical = amendment.get("historical_execution")
    run = historical.get("workflow_run") if isinstance(historical, Mapping) else None
    failure = historical.get("failure_boundary") if isinstance(historical, Mapping) else None
    usage = historical.get("observed_usage") if isinstance(historical, Mapping) else None
    previous_request = historical.get("request") if isinstance(historical, Mapping) else None
    require(
        isinstance(run, Mapping)
        and run.get("id") == PREVIOUS_RUN_ID
        and run.get("attempt") == 1
        and run.get("head_sha") == PREVIOUS_EXECUTION_HEAD
        and run.get("conclusion") == "failure"
        and isinstance(failure, Mapping)
        and failure.get("stderr_class") == "LIBPYTHON3_11_SO_1_0_UNAVAILABLE"
        and failure.get("cell_terminal_records") == 0
        and failure.get("container_started") is False
        and failure.get("official_grader_runs") == 0
        and historical.get("grader_state")
        == "GRADER_INFRA_FAILURE_BEFORE_CONTAINER"
        and historical.get("performance_measured") is False
        and isinstance(previous_request, Mapping)
        and previous_request.get("raw_sha256") == PREVIOUS_SENTINEL_SHA256
        and previous_request.get("attempt_one_consumed") is True
        and previous_request.get("attempt_two_allowed") is False
        and previous_request.get("rerun_allowed") is False
        and isinstance(usage, Mapping)
        and usage.get("paid_model_calls") == 10
        and usage.get("terminal_task_arm_runs") == 0
        and usage.get("official_grader_runs") == 0
        and usage.get("total_usd") == "0.051215550000",
        "immutable _010 execution provenance differs",
    )
    scope = amendment.get("scientific_scope_lock")
    require(
        isinstance(scope, Mapping)
        and scope.get("model_id") == MODEL_ID
        and scope.get("reasoning_effort") == REASONING_EFFORT
        and scope.get("development_targets") == 12
        and scope.get("heldout_targets") == 27
        and scope.get("task_arm_runs") == 72
        and tuple(scope.get("streams", ())) == EXPECTED_STREAM_ORDER
        and scope.get("development_hard_caps_changed") is False
        and scope.get("grader_or_image_revision_changed") is False
        and scope.get("m2_selection_rule_changed") is False
        and scope.get("memory_parameters_changed") is False
        and scope.get("output_token_pools_changed") is False
        and scope.get("prompt_tool_parser_or_limits_changed") is False
        and scope.get("runtime_lock_manifest_changed") is False,
        "D1.10 frozen scientific scope differs",
    )
    return amendment, inventory, {str(k): str(v) for k, v in contracts.items()}


def _validate_frozen_science_documents(
    repository: Path, source_head: str
) -> tuple[list[str], dict[str, Any]]:
    development = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/development_manifest.json")
    )
    targets = development.get("targets")
    require(
        development.get("schema") == "trimem/development-manifest/1.0"
        and development.get("status") == "FROZEN"
        and isinstance(targets, list)
        and len(targets) == 12,
        "frozen DEV manifest differs",
    )
    require(
        all(isinstance(row, Mapping) for row in targets),
        "frozen DEV target row is malformed",
    )
    target_order = [row.get("instance_id") for row in targets]
    require(
        tuple(target_order) == EXPECTED_TARGET_ORDER
        and [row.get("order_index") for row in targets] == list(range(12)),
        "frozen DEV target order differs",
    )
    arms = strict_json(commit_bytes(repository, source_head, "configs/trimem_v1/arms.json"))
    require(
        tuple(arms.get("development_streams", ())) == EXPECTED_STREAM_ORDER,
        "frozen six-stream order differs",
    )
    model = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/model_lock.json")
    )
    roles = model.get("model_roles")
    require(
        model.get("primary_model", {}).get("model_id") == MODEL_ID
        and model.get("decoding_contract", {}).get("reasoning_effort")
        == REASONING_EFFORT
        and isinstance(roles, Mapping)
        and all(
            roles.get(role, {}).get("model_id") == MODEL_ID
            for role in ("decomposition", "solve", "experience_extraction")
        ),
        "exact frozen model/reasoning role contract differs",
    )
    cost = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/cost_plan.json")
    )
    hard = cost.get("phase_hard_caps", {}).get(EXPECTED_PHASE)
    require(
        hard == EXPECTED_DEVELOPMENT_HARD_CAP,
        "frozen DEVELOPMENT hard caps differ",
    )
    candidates = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/m2_candidate_bundles.json")
    )
    require(
        candidates.get("candidate_order")
        == ["baseline", "precision", "recall", "balanced"]
        and candidates.get("development_contract", {}).get("candidate_task_arm_runs")
        == 48
        and candidates.get("development_contract", {}).get("targets_per_candidate")
        == 12
        and candidates.get("development_contract", {}).get("component_ablation_claim")
        == "PROHIBITED",
        "four frozen M2 candidate definitions differ",
    )
    return target_order, dict(hard)


def _validate_freeze_and_bindings(
    repository: Path,
    source_head: str,
    contracts: Mapping[str, str],
) -> dict[str, Any]:
    freeze_raw = commit_bytes(repository, source_head, FREEZE_PATH)
    freeze = strict_json(freeze_raw)
    files = freeze.get("files")
    require(
        freeze.get("schema") == FREEZE_SCHEMA and isinstance(files, Mapping),
        "activation research freeze is malformed",
    )
    require(SENTINEL_PATH not in files, "_011 entered its activation-source freeze")
    previous_freeze_entry = files.get(PREVIOUS_SENTINEL_PATH)
    require(
        previous_freeze_entry is None
        or previous_freeze_entry
        == {
            "bytes": len(
                commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH)
            ),
            "sha256": PREVIOUS_SENTINEL_SHA256,
        },
        "research freeze records different historical _010 bytes",
    )

    paths = {**SCIENCE_BINDING_PATHS, **ACTIVATION_BINDING_PATHS}
    bindings: dict[str, Any] = {
        "freeze_sha256": "sha256:" + hashlib.sha256(freeze_raw).hexdigest(),
    }
    for name, path in paths.items():
        raw = commit_bytes(repository, source_head, path)
        digest = hashlib.sha256(raw).hexdigest()
        require(
            files.get(path) == {"bytes": len(raw), "sha256": digest},
            f"activation research freeze does not bind path: {path}",
        )
        bindings[name] = "sha256:" + digest
    for name, path in D110_CONTRACT_PATHS.items():
        digest = _sha256_at(repository, source_head, path)
        require(
            contracts.get(name) == digest
            and files.get(path)
            == {
                "bytes": len(commit_bytes(repository, source_head, path)),
                "sha256": digest,
            },
            f"freeze does not bind current D1.10 contract: {name}",
        )
        bindings[name] = "sha256:" + digest
    gate_hashes: dict[str, str] = {}
    for path in REQUIRED_REMOTE_GATE_WORKFLOWS:
        raw = commit_bytes(repository, source_head, path)
        digest = hashlib.sha256(raw).hexdigest()
        require(
            files.get(path) == {"bytes": len(raw), "sha256": digest},
            f"freeze does not bind remote gate workflow: {path}",
        )
        gate_hashes[path] = "sha256:" + digest
    bindings["remote_gate_workflow_blob_sha256"] = gate_hashes
    return bindings


def _validate_source(repository: Path, source_head: str) -> dict[str, Any]:
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    require(
        git(repository, "cat-file", "-t", source_head).strip() == "commit",
        "source HEAD is not a commit",
    )
    _validate_starting_source(repository)
    changes = _validate_activation_diff(repository, source_head)
    _validate_historical_010(repository, source_head)
    _validate_preserved_science(repository, source_head)
    _validate_workflow_activation(repository, source_head)
    _validate_remote_gate_workflow_contracts(repository, source_head)
    _amendment, _inventory, contracts = _validate_d110_seal(
        repository, source_head
    )
    target_order, hard_cap = _validate_frozen_science_documents(
        repository, source_head
    )
    bindings = _validate_freeze_and_bindings(repository, source_head, contracts)
    return {
        "activation_changes": changes,
        "bindings": bindings,
        "hard_cap": hard_cap,
        "target_order": target_order,
    }


# D1.12 deliberately replaces the copied D1.10 source assembler above.  The
# low-level Git/JSON/workflow/runner helpers remain self-contained in this
# module, while the active source contract starts at the sealed D1.11 commit.
def _load_immutable_previous_request(repository: Path) -> dict[str, Any]:
    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _011 execution commit is unavailable",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256,
        "immutable _011 request bytes differ",
    )
    previous = strict_json(raw)
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.10"
        and previous.get("request_id")
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011"
        and previous.get("request_path") == PREVIOUS_SENTINEL_PATH
        and previous.get("source_head") == PREVIOUS_SOURCE_HEAD
        and previous.get("request_sha256")
        == "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "immutable _011 request identity differs",
    )
    return previous


def _validate_d112_activation_diff(
    repository: Path, source_head: str
) -> dict[str, str]:
    require(
        source_head != STARTING_SOURCE_HEAD
        and _is_ancestor(repository, STARTING_SOURCE_HEAD, source_head),
        "D1.12 source is not a strict descendant of the sealed D1.11 HEAD",
    )
    lines = git(
        repository,
        "diff",
        "--no-ext-diff",
        "--name-status",
        "--no-renames",
        STARTING_SOURCE_HEAD,
        source_head,
    ).splitlines()
    changes: dict[str, str] = {}
    for line in lines:
        pieces = line.split("\t")
        require(len(pieces) == 2, "D1.12 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.12 diff status is forbidden: {status}")
        require(path in ALLOWED_ACTIVATION_PATHS, f"D1.12 changed forbidden path: {path}")
        require(path not in changes, f"D1.12 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_ACTIVATION_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.12-only change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_historical_011(
    repository: Path, source_head: str
) -> dict[str, Any]:
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.12 source does not preserve the immutable _011 execution",
    )
    previous = _load_immutable_previous_request(repository)
    current_raw = commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH)
    require(
        hashlib.sha256(current_raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and current_raw
        == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH),
        "historical _011 request was modified after execution",
    )
    require(
        not git(
            repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH
        ).strip(),
        "_012 exists in activation-source history",
    )
    return previous


def _validate_d112_workflow(repository: Path, source_head: str) -> None:
    try:
        workflow = commit_bytes(repository, source_head, EXPECTED_WORKFLOW_PATH).decode(
            "utf-8", errors="strict"
        )
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError("benchmark workflow is not UTF-8") from exc
    require(
        workflow.count(f"      - {SENTINEL_PATH}\n") == 1,
        "_012 push-path identity differs",
    )
    require(
        f"      - {PREVIOUS_SENTINEL_PATH}\n" not in workflow,
        "spent _011 remains an active push trigger",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-011" not in workflow,
        "_012 concurrency identity differs",
    )
    active_command = "python -I -S scripts/trimem_development_trigger_d112.py"
    require(
        workflow.count(active_command) == 2
        and "python -I -S scripts/trimem_development_trigger_d110.py"
        not in workflow,
        "active trigger validator is not exclusively D1.12 _012",
    )
    require(
        workflow.count(
            "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, "
            "trimem-benchmark]"
        ) == 2,
        "D1.12 jobs do not use the exact collision-free runner labels",
    )
    require(
        workflow.count("--runner-host-preflight-event-path \"$GITHUB_EVENT_PATH\"")
        == 1
        and workflow.count("github.run_attempt == 1") >= 2
        and "environment: trimem-benchmark-exec" in workflow,
        "D1.12 attempt, host-preflight, or protected-environment gate differs",
    )


def _freeze_entry(
    repository: Path,
    source_head: str,
    files: Mapping[str, Any],
    path: str,
) -> str:
    raw = commit_bytes(repository, source_head, path)
    digest = hashlib.sha256(raw).hexdigest()
    require(
        files.get(path) == {"bytes": len(raw), "sha256": digest},
        f"D1.12 freeze does not bind path: {path}",
    )
    return "sha256:" + digest


def _validate_d112_freeze_and_bindings(
    repository: Path,
    source_head: str,
    previous_request: Mapping[str, Any],
) -> dict[str, Any]:
    freeze_raw = commit_bytes(repository, source_head, FREEZE_PATH)
    freeze = strict_json(freeze_raw)
    files = freeze.get("files")
    require(
        freeze.get("schema") == FREEZE_SCHEMA and isinstance(files, Mapping),
        "D1.12 research freeze is malformed",
    )
    require(SENTINEL_PATH not in files, "_012 entered its source freeze")
    previous_raw = commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH)
    require(
        files.get(PREVIOUS_SENTINEL_PATH)
        == {
            "bytes": len(previous_raw),
            "sha256": PREVIOUS_SENTINEL_SHA256,
        },
        "D1.12 freeze does not preserve the exact _011 request",
    )

    previous_bindings = previous_request.get("bindings")
    require(isinstance(previous_bindings, Mapping), "_011 bindings are malformed")
    bindings: dict[str, Any] = {
        "freeze_sha256": "sha256:" + hashlib.sha256(freeze_raw).hexdigest()
    }
    for name, path in SCIENCE_BINDING_PATHS.items():
        observed = _freeze_entry(repository, source_head, files, path)
        require(
            observed == previous_bindings.get(name),
            f"scientific binding changed after _011: {name}",
        )
        bindings[name] = observed
    for name, path in ACTIVATION_BINDING_PATHS.items():
        bindings[name] = _freeze_entry(repository, source_head, files, path)
    for name, path in EXECUTION_CONTRACT_PATHS.items():
        bindings[name] = _freeze_entry(repository, source_head, files, path)

    gate_hashes: dict[str, str] = {}
    for path in REQUIRED_REMOTE_GATE_WORKFLOWS:
        gate_hashes[path] = _freeze_entry(repository, source_head, files, path)
    bindings["remote_gate_workflow_blob_sha256"] = gate_hashes
    for path in REQUIRED_ACTIVATION_CHANGES:
        if path != FREEZE_PATH:
            _freeze_entry(repository, source_head, files, path)
    return bindings


def _validate_d112_documents(repository: Path, source_head: str) -> None:
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    require(
        amendment.get("schema") == AMENDMENT_SCHEMA
        and inventory.get("schema") == INVENTORY_SCHEMA
        and amendment.get("classification") == AMENDMENT_CLASSIFICATION
        and inventory.get("classification") == AMENDMENT_CLASSIFICATION
        and amendment.get("status") == AMENDMENT_STATUS
        and inventory.get("status") == AMENDMENT_STATUS
        and amendment.get("endpoint") == AMENDMENT_ENDPOINT
        and inventory.get("endpoint") == AMENDMENT_ENDPOINT,
        "D1.12 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_011_attempt_one_consumed") is True
        and authority.get("request_011_rerun_allowed") is False
        and authority.get("request_012_creation_authorized") is True
        and authority.get("request_012_created") is False
        and authority.get("actual_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("sentinel_contains_execution_authority") is False,
        "D1.12 authority boundary differs",
    )


def _validate_source(repository: Path, source_head: str) -> dict[str, Any]:
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    require(
        git(repository, "cat-file", "-t", source_head).strip() == "commit",
        "source HEAD is not a commit",
    )
    _validate_starting_source(repository)
    changes = _validate_d112_activation_diff(repository, source_head)
    previous = _validate_historical_011(repository, source_head)
    _validate_preserved_science(repository, source_head)
    _validate_d112_workflow(repository, source_head)
    _validate_remote_gate_workflow_contracts(repository, source_head)
    _validate_d112_documents(repository, source_head)
    target_order, hard_cap = _validate_frozen_science_documents(
        repository, source_head
    )
    require(
        previous.get("exact_model")
        == {
            "base_url": "https://api.openai.com/v1",
            "model_id": MODEL_ID,
            "reasoning_effort": REASONING_EFFORT,
            "same_snapshot_for": [
                "decomposition",
                "solve",
                "experience_extraction",
            ],
        }
        and previous.get("hard_caps") == hard_cap
        and previous.get("scientific_workload", {}).get("target_order")
        == target_order
        and previous.get("scientific_workload", {}).get("stream_order")
        == list(EXPECTED_STREAM_ORDER),
        "scientific identity differs from immutable _011",
    )
    bindings = _validate_d112_freeze_and_bindings(
        repository, source_head, previous
    )
    return {
        "activation_changes": changes,
        "bindings": bindings,
        "hard_cap": hard_cap,
        "previous_request": previous,
        "target_order": target_order,
    }


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
    validated = _validate_source(repository, selected)
    return {
        "activation_changes": validated["activation_changes"],
        "bindings": validated["bindings"],
        "model_calls": 0,
        "paid_model_calls": 0,
        "request_id": REQUEST_ID,
        "sentinel_path": SENTINEL_PATH,
        "sentinel_present": False,
        "source_head": selected,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


# An expressive alias for callers that do not need historical naming parity.
validate_activation_source = validate_correction_source


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed if parsed.tzinfo == timezone.utc else None


def _utc_timestamp(value: Any) -> bool:
    return _parse_utc_timestamp(value) is not None


def _validate_runner_readiness_freshness(
    evidence: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    observed = _parse_utc_timestamp(evidence.get("observed_at_utc"))
    require(observed is not None, "runner readiness timestamp is malformed")
    current = datetime.now(timezone.utc) if now is None else now
    require(
        current.tzinfo is not None
        and current.utcoffset() == timezone.utc.utcoffset(current),
        "runner readiness comparison time is not UTC",
    )
    age_seconds = (current - observed).total_seconds()
    require(
        -MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS
        <= age_seconds
        <= MAXIMUM_RUNNER_READINESS_AGE_SECONDS,
        "runner readiness observation is stale or future-dated",
    )


def _validate_pull_request_binding(
    pull_requests: Any, source_head: str
) -> bool:
    if not isinstance(pull_requests, list) or len(pull_requests) != 1:
        return False
    pull = pull_requests[0]
    head = pull.get("head") if isinstance(pull, Mapping) else None
    return (
        isinstance(pull, Mapping)
        and pull.get("number") == PULL_REQUEST_NUMBER
        and isinstance(head, Mapping)
        and head.get("sha") == source_head
    )


def _validate_remote_gate_evidence(
    evidence: Any, *, source_head: str
) -> dict[str, Any]:
    require(isinstance(evidence, Mapping), "remote gate evidence is missing")
    require(
        set(evidence)
        == {
            "activation_actuals",
            "all_required_workflows_passed",
            "observed_at_utc",
            "pull_request",
            "pull_request_number",
            "repository",
            "schema",
            "source_head",
            "source_ref",
            "workflows",
        },
        "remote gate evidence field set differs",
    )
    require(
        evidence.get("schema") == REMOTE_GATE_SCHEMA
        and evidence.get("repository") == EXPECTED_REPOSITORY
        and evidence.get("source_head") == source_head
        and evidence.get("source_ref") == EXPECTED_REF
        and evidence.get("pull_request_number") == PULL_REQUEST_NUMBER
        and evidence.get("all_required_workflows_passed") is True,
        "remote gate source or aggregate identity differs",
    )
    pull = evidence.get("pull_request")
    require(
        isinstance(pull, Mapping)
        and pull
        == {
            "base_ref": EXPECTED_BASE_BRANCH,
            "base_sha": EXPECTED_BASE_HEAD,
            "draft": True,
            "head_ref": EXPECTED_BRANCH,
            "head_repository": EXPECTED_REPOSITORY,
            "head_sha": source_head,
            "html_url": (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/pull/18"
            ),
            "number": PULL_REQUEST_NUMBER,
            "state": "open",
        },
        "current PR #18 OPEN/DRAFT exact-head binding differs",
    )
    require(
        _utc_timestamp(evidence.get("observed_at_utc")),
        "remote gate observation timestamp is not exact UTC",
    )
    require(
        evidence.get("activation_actuals") == ACTIVATION_ZERO_COUNTERS,
        "credential-free activation gates contain scientific execution",
    )
    rows = evidence.get("workflows")
    require(
        isinstance(rows, list) and len(rows) == len(REMOTE_GATE_SPECS),
        "remote gate workflow count differs",
    )
    selected_run_ids: set[int] = set()
    for spec, row in zip(REMOTE_GATE_SPECS, rows, strict=True):
        path, event, pr_number = spec
        require(
            isinstance(row, Mapping)
            and set(row)
            == {
                "conclusion",
                "event",
                "head_branch",
                "head_sha",
                "html_url",
                "pull_request_number",
                "run_attempt",
                "run_id",
                "status",
                "workflow_path",
            },
            f"remote gate row shape differs: {path}",
        )
        run_id = row.get("run_id")
        require(
            row.get("workflow_path") == path
            and row.get("event") == event
            and row.get("pull_request_number") == pr_number
            and row.get("head_branch") == EXPECTED_BRANCH
            and row.get("head_sha") == source_head
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
            and type(run_id) is int
            and run_id > 0
            and type(row.get("run_attempt")) is int
            and row.get("run_attempt") == 1
            and row.get("html_url")
            == (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                f"actions/runs/{run_id}"
            ),
            f"remote gate is missing, red, rerun, or misbound: {path}:{event}",
        )
        require(
            run_id not in selected_run_ids,
            f"remote gate run ID is duplicated: {path}:{event}",
        )
        selected_run_ids.add(run_id)
    return deepcopy(dict(evidence))


def _query_github_runs(
    gh: str, source_head: str, event: str, safe_environment: Mapping[str, str]
) -> list[dict[str, Any]]:
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
                f"event={event}",
                "-f",
                "per_page=100",
            ],
            capture_output=True,
            text=False,
            check=False,
            timeout=60,
            env=dict(safe_environment),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerError("GitHub remote gate query failed") from exc
    require(query.returncode == 0, "GitHub remote gate query failed")
    response = strict_json(query.stdout)
    runs = response.get("workflow_runs")
    require(isinstance(runs, list), "GitHub remote gate response has no workflow runs")
    total = response.get("total_count")
    require(
        type(total) is int and total == len(runs) and total <= 100,
        "GitHub remote gate response is incomplete or paginated",
    )
    return [dict(run) for run in runs if isinstance(run, Mapping)]


def _safe_process_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key not in FORBIDDEN_PREFLIGHT_SECRETS
    }


def _run_readiness_command(
    argv: Sequence[str],
    *,
    safe_environment: Mapping[str, str],
    label: str,
    timeout: int = 60,
) -> bytes:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            check=False,
            timeout=timeout,
            env=dict(safe_environment),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerError(f"runner readiness command failed: {label}") from exc
    require(
        completed.returncode == 0,
        f"runner readiness command failed: {label}",
    )
    return completed.stdout


def collect_remote_runner_rows() -> list[dict[str, Any]]:
    """Read the complete repository-runner set without exposing benchmark secrets."""

    gh = shutil.which("gh")
    require(gh is not None, "gh CLI is required to verify self-hosted runners")
    raw = _run_readiness_command(
        [
            gh,
            "api",
            "--hostname",
            "github.com",
            "--method",
            "GET",
            f"repos/{EXPECTED_REPOSITORY}/actions/runners",
            "-f",
            "per_page=100",
        ],
        safe_environment=_safe_process_environment(),
        label="GitHub repository runners",
    )
    response = strict_json(raw)
    runners = response.get("runners")
    require(
        response.get("total_count") == 2
        and isinstance(runners, list)
        and len(runners) == 2,
        "exactly two fresh repository runners are required",
    )
    rows: list[dict[str, Any]] = []
    for runner in runners:
        require(isinstance(runner, Mapping), "runner registration row is malformed")
        labels = runner.get("labels")
        require(isinstance(labels, list), "runner labels are malformed")
        label_names = [
            row.get("name") for row in labels if isinstance(row, Mapping)
        ]
        require(
            len(label_names) == len(labels)
            and all(isinstance(label, str) for label in label_names),
            "runner label row is malformed",
        )
        label_names.sort()
        normalized_labels = [str(label).lower() for label in label_names]
        row = {
            "busy": runner.get("busy"),
            "id": runner.get("id"),
            "labels": label_names,
            "name": runner.get("name"),
            "status": runner.get("status"),
        }
        require(
            type(row["id"]) is int
            and row["id"] > 0
            and row["name"] in RUNNER_NAMES
            and row["status"] == "online"
            and row["busy"] is False
            and len(label_names) == len(labels) == len(REQUIRED_RUNNER_LABELS)
            and all(isinstance(label, str) for label in label_names)
            and len(set(normalized_labels)) == len(normalized_labels)
            and set(normalized_labels) == set(REQUIRED_RUNNER_LABELS),
            "repository runner is stale, busy, offline, or incorrectly labelled",
        )
        rows.append(row)
    rows.sort(key=lambda row: str(row["name"]))
    require(
        tuple(row["name"] for row in rows) == RUNNER_NAMES,
        "fresh runner identities differ",
    )
    return rows


def _wsl_stdout(
    wsl: str,
    args: Sequence[str],
    *,
    safe_environment: Mapping[str, str],
    label: str,
) -> str:
    raw = _run_readiness_command(
        [wsl, "-d", RUNNER_DISTRIBUTION, "--", *args],
        safe_environment=safe_environment,
        label=label,
    )
    try:
        return raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError(
            f"runner readiness output is not UTF-8: {label}"
        ) from exc


def _validate_ubuntu_os_release(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError("runner OS release is not UTF-8") from exc
    selected: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        require("=" in line, "runner OS release contains a malformed line")
        name, value = line.split("=", 1)
        if name not in {"ID", "VERSION_ID"}:
            continue
        require(name not in selected, f"runner OS release duplicates {name}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        require(
            bool(value)
            and value == value.strip()
            and not any(character in value for character in "\\\"'\x00"),
            f"runner OS release {name} is malformed",
        )
        selected[name] = value
    require(
        selected == {"ID": "ubuntu", "VERSION_ID": "24.04"},
        "runner OS release is not exact Ubuntu 24.04",
    )
    return {"os_id": selected["ID"], "os_version_id": selected["VERSION_ID"]}


def _expected_execution_images(repository: Path, source_head: str) -> list[str]:
    development = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/development_manifest.json")
    )
    target_ids = {
        f"{row.get('benchmark_id')}--{row.get('instance_id')}"
        for row in development.get("targets", ())
        if isinstance(row, Mapping)
    }
    image_lock = strict_json(
        commit_bytes(repository, source_head, "artifacts/trimem_v1/grader_image_lock.json")
    )
    locked_targets = image_lock.get("benchmark_target_images", {}).get("targets")
    support = image_lock.get("support_images")
    require(
        len(target_ids) == 12
        and isinstance(locked_targets, list)
        and isinstance(support, list),
        "runner image readiness inputs are malformed",
    )
    target_images = [
        row.get("image")
        for row in locked_targets
        if isinstance(row, Mapping) and row.get("target_id") in target_ids
    ]
    support_images = [
        row.get("image") for row in support if isinstance(row, Mapping)
    ]
    images = target_images + support_images
    require(
        len(target_images) == 12
        and len(images) == len(set(images))
        and all(isinstance(image, str) and "@sha256:" in image for image in images),
        "runner image readiness set differs from the frozen DEV image set",
    )
    return sorted(str(image) for image in images)


def _validate_runner_readiness(
    evidence: Any, *, source_head: str
) -> dict[str, Any]:
    require(isinstance(evidence, Mapping), "runner readiness evidence is missing")
    require(
        set(evidence)
        == {
            "activation_actuals",
            "host",
            "observed_at_utc",
            "repository",
            "required_labels",
            "runners",
            "schema",
            "sequential_self_hosted_jobs",
            "source_head",
        },
        "runner readiness evidence field set differs",
    )
    require(
        evidence.get("schema") == RUNNER_READINESS_SCHEMA
        and evidence.get("repository") == EXPECTED_REPOSITORY
        and evidence.get("source_head") == source_head
        and evidence.get("required_labels") == list(REQUIRED_RUNNER_LABELS)
        and evidence.get("sequential_self_hosted_jobs")
        == ["bounded-context-preflight", "frozen-serial-phase"]
        and evidence.get("activation_actuals") == ACTIVATION_ZERO_COUNTERS
        and _utc_timestamp(evidence.get("observed_at_utc")),
        "runner readiness identity differs",
    )
    runners = evidence.get("runners")
    require(
        isinstance(runners, list)
        and len(runners) == 2
        and tuple(row.get("name") for row in runners if isinstance(row, Mapping))
        == RUNNER_NAMES,
        "runner readiness registration set differs",
    )
    for row in runners:
        require(
            isinstance(row, Mapping)
            and set(row) == {"busy", "id", "labels", "name", "status"}
            and type(row.get("id")) is int
            and row.get("id") > 0
            and row.get("status") == "online"
            and row.get("busy") is False
            and isinstance(row.get("labels"), list)
            and len(row["labels"]) == len(REQUIRED_RUNNER_LABELS)
            and all(isinstance(label, str) for label in row["labels"])
            and len({str(label).lower() for label in row["labels"]})
            == len(REQUIRED_RUNNER_LABELS)
            and {str(label).lower() for label in row["labels"]}
            == set(REQUIRED_RUNNER_LABELS),
            "runner readiness registration row differs",
        )
    host = evidence.get("host")
    require(
        isinstance(host, Mapping)
        and set(host)
        == {
            "architecture",
            "cached_execution_images",
            "container_count",
            "disk_available_bytes",
            "docker_server_version",
            "exact_python_path",
            "exact_python_version",
            "forbidden_secret_names_present",
            "fresh_runner_roots",
            "listener_bindings",
            "local_runner_bindings",
            "minimum_disk_available_bytes",
            "os_id",
            "os_version_id",
            "stale_runner_roots_absent",
            "tool_cache_root",
            "wsl_distribution",
        }
        and host.get("architecture") == "x86_64"
        and host.get("cached_execution_images") == 13
        and host.get("container_count") == 0
        and type(host.get("disk_available_bytes")) is int
        and host["disk_available_bytes"] >= MINIMUM_RUNNER_DISK_BYTES
        and host.get("minimum_disk_available_bytes") == MINIMUM_RUNNER_DISK_BYTES
        and host.get("os_id") == "ubuntu"
        and host.get("os_version_id") == "24.04"
        and isinstance(host.get("docker_server_version"), str)
        and bool(host["docker_server_version"])
        and host.get("exact_python_path") == f"{EXACT_PYTHON_ROOT}/bin/python"
        and host.get("exact_python_version") == "Python 3.11.10"
        and host.get("forbidden_secret_names_present") == []
        and host.get("fresh_runner_roots") == list(RUNNER_ROOTS)
        and isinstance(host.get("listener_bindings"), list)
        and [row.get("root") for row in host["listener_bindings"]]
        == list(RUNNER_ROOTS)
        and all(
            isinstance(row, Mapping)
            and set(row) == {"pid", "root"}
            and type(row.get("pid")) is int
            and row["pid"] > 0
            for row in host["listener_bindings"]
        )
        and len({row["pid"] for row in host["listener_bindings"]})
        == len(RUNNER_ROOTS)
        and isinstance(host.get("local_runner_bindings"), list)
        and host.get("local_runner_bindings")
        == [
            {
                "agent_id": row["id"],
                "agent_name": row["name"],
                "root": RUNNER_ROOTS[index],
                "work_folder": "_work",
            }
            for index, row in enumerate(runners)
        ]
        and host.get("stale_runner_roots_absent") == list(STALE_RUNNER_ROOTS)
        and host.get("tool_cache_root") == RUNNER_TOOL_CACHE
        and host.get("wsl_distribution") == RUNNER_DISTRIBUTION,
        "self-hosted runner host readiness differs",
    )
    return deepcopy(dict(evidence))


def collect_runner_readiness(
    repository: Path, source_head: str
) -> dict[str, Any]:
    """Verify two clean WSL runners and all local prerequisites without pulls."""

    wsl = shutil.which("wsl.exe")
    require(wsl is not None, "WSL is required for benchmark runner readiness")
    safe_environment = _safe_process_environment()
    runners = collect_remote_runner_rows()
    architecture = _wsl_stdout(
        wsl, ["uname", "-m"], safe_environment=safe_environment, label="architecture"
    )
    docker_version = _wsl_stdout(
        wsl,
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        safe_environment=safe_environment,
        label="Docker daemon",
    )
    disk_text = _wsl_stdout(
        wsl,
        ["df", "-B1", "--output=avail", "/opt"],
        safe_environment=safe_environment,
        label="runner disk",
    )
    try:
        disk_available = int(disk_text.splitlines()[-1].strip())
    except (IndexError, ValueError) as exc:
        raise DevelopmentTriggerError("runner disk observation is malformed") from exc
    python_version = _wsl_stdout(
        wsl,
        [f"{EXACT_PYTHON_ROOT}/bin/python", "--version"],
        safe_environment=safe_environment,
        label="exact Python 3.11.10",
    )
    os_release = _validate_ubuntu_os_release(
        _run_readiness_command(
            [wsl, "-d", RUNNER_DISTRIBUTION, "--", "cat", "/etc/os-release"],
            safe_environment=safe_environment,
            label="exact Ubuntu 24.04 release",
        )
    )
    container_text = _wsl_stdout(
        wsl,
        ["docker", "ps", "-aq"],
        safe_environment=safe_environment,
        label="stale containers",
    )
    require(not container_text, "a stale benchmark or service container remains")
    listener_probe = """\
import json
import os
from pathlib import Path
import sys

names = set(json.loads(sys.argv[1]))
roots = set(json.loads(sys.argv[2]))
if names.intersection(os.environ):
    raise SystemExit(41)
listeners = []
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        comm = (proc / 'comm').read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        continue
    if comm != 'Runner.Listener':
        continue
    environment = (proc / 'environ').read_bytes().split(b'\\0')
    keys = {
        item.split(b'=', 1)[0].decode('utf-8', errors='strict')
        for item in environment
        if item
    }
    if names.intersection(keys):
        raise SystemExit(42)
    listeners.append({'pid': int(proc.name), 'root': os.readlink(proc / 'cwd')})
listeners.sort(key=lambda row: row['root'])
if len(listeners) != 2 or {row['root'] for row in listeners} != roots:
    raise SystemExit(43)
if len({row['pid'] for row in listeners}) != 2:
    raise SystemExit(45)
print(json.dumps({'listeners': listeners}, sort_keys=True, separators=(',', ':')))
"""
    listener_document = strict_json(
        _run_readiness_command(
            [
                wsl,
                "-d",
                RUNNER_DISTRIBUTION,
                "--",
                f"{EXACT_PYTHON_ROOT}/bin/python",
                "-I",
                "-S",
                "-c",
                listener_probe,
                json.dumps(sorted(FORBIDDEN_PREFLIGHT_SECRETS)),
                json.dumps(list(RUNNER_ROOTS)),
            ],
            safe_environment=safe_environment,
            label="runner listener identity and secret-name absence",
        )
    )
    listener_bindings = listener_document.get("listeners")
    require(
        isinstance(listener_bindings, list)
        and [row.get("root") for row in listener_bindings if isinstance(row, Mapping)]
        == list(RUNNER_ROOTS),
        "runner listener roots differ",
    )
    for root in STALE_RUNNER_ROOTS:
        completed = subprocess.run(
            [wsl, "-d", RUNNER_DISTRIBUTION, "--", "test", "!", "-e", root],
            capture_output=True,
            check=False,
            env=dict(safe_environment),
        )
        require(completed.returncode == 0, f"stale runner workspace remains: {root}")
    remote_by_name = {str(row["name"]): row for row in runners}
    local_bindings: list[dict[str, Any]] = []
    for index, root in enumerate(RUNNER_ROOTS):
        expected_name = RUNNER_NAMES[index]
        for relative in (".runner", "run.sh"):
            _run_readiness_command(
                [
                    wsl,
                    "-d",
                    RUNNER_DISTRIBUTION,
                    "--",
                    "test",
                    "-f",
                    f"{root}/{relative}",
                ],
                safe_environment=safe_environment,
                label=f"fresh runner file {root}/{relative}",
            )
        _run_readiness_command(
            [
                wsl,
                "-d",
                RUNNER_DISTRIBUTION,
                "--",
                "test",
                "!",
                "-e",
                f"{root}/_work/enterprise-shared-memory-poc",
            ],
            safe_environment=safe_environment,
            label=f"clean runner workspace {root}",
        )
        resolved_cache = _wsl_stdout(
            wsl,
            ["readlink", "-f", f"{root}/_work/_tool"],
            safe_environment=safe_environment,
            label=f"runner tool cache {root}",
        )
        require(resolved_cache == RUNNER_TOOL_CACHE, "runner tool cache differs")
        local_config_probe = """\
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
names = [name.encode('ascii') + b'=' for name in json.loads(sys.argv[2])]
config_raw = (root / '.runner').read_bytes()
utf8_bom = b'\\xef\\xbb\\xbf'
if config_raw.startswith(utf8_bom):
    config_raw = config_raw[len(utf8_bom):]

def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate runner config key')
        result[key] = value
    return result

def reject_constant(value):
    raise ValueError('invalid runner config constant')

config = json.loads(
    config_raw.decode('utf-8', errors='strict'),
    object_pairs_hook=reject_duplicates,
    parse_constant=reject_constant,
)
for filename in ('.env', '.path'):
    path = root / filename
    if not path.exists():
        continue
    lines = path.read_bytes().splitlines()
    if any(line.startswith(prefix) for line in lines for prefix in names):
        raise SystemExit(44)
selected = {
    'agentId': config.get('agentId'),
    'agentName': config.get('agentName'),
    'gitHubUrl': config.get('gitHubUrl'),
    'workFolder': config.get('workFolder'),
}
print(json.dumps(selected, sort_keys=True, separators=(',', ':')))
"""
        local_config = strict_json(
            _run_readiness_command(
                [
                    wsl,
                    "-d",
                    RUNNER_DISTRIBUTION,
                    "--",
                    f"{EXACT_PYTHON_ROOT}/bin/python",
                    "-I",
                    "-S",
                    "-c",
                    local_config_probe,
                    root,
                    json.dumps(sorted(FORBIDDEN_PREFLIGHT_SECRETS)),
                ],
                safe_environment=safe_environment,
                label=f"runner identity and config secret-name absence {root}",
            )
        )
        remote = remote_by_name[expected_name]
        require(
            local_config.get("agentId") == remote["id"]
            and local_config.get("agentName") == expected_name
            and local_config.get("gitHubUrl")
            == "https://github.com/Scuttie/enterprise-shared-memory-poc"
            and local_config.get("workFolder") == "_work",
            f"local runner identity differs from GitHub registration: {root}",
        )
        local_bindings.append(
            {
                "agent_id": remote["id"],
                "agent_name": expected_name,
                "root": root,
                "work_folder": "_work",
            }
        )
    images = _expected_execution_images(repository, source_head)
    for locked_image in images:
        _run_readiness_command(
            [
                wsl,
                "-d",
                RUNNER_DISTRIBUTION,
                "--",
                "docker",
                "image",
                "inspect",
                locked_image,
            ],
            safe_environment=safe_environment,
            label=f"cached image {locked_image}",
        )
    evidence = {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "host": {
            "architecture": architecture,
            "cached_execution_images": len(images),
            "container_count": 0,
            "disk_available_bytes": disk_available,
            "docker_server_version": docker_version,
            "exact_python_path": f"{EXACT_PYTHON_ROOT}/bin/python",
            "exact_python_version": python_version,
            "forbidden_secret_names_present": [],
            "fresh_runner_roots": list(RUNNER_ROOTS),
            "listener_bindings": listener_bindings,
            "local_runner_bindings": local_bindings,
            "minimum_disk_available_bytes": MINIMUM_RUNNER_DISK_BYTES,
            **os_release,
            "stale_runner_roots_absent": list(STALE_RUNNER_ROOTS),
            "tool_cache_root": RUNNER_TOOL_CACHE,
            "wsl_distribution": RUNNER_DISTRIBUTION,
        },
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "repository": EXPECTED_REPOSITORY,
        "required_labels": list(REQUIRED_RUNNER_LABELS),
        "runners": runners,
        "schema": RUNNER_READINESS_SCHEMA,
        "sequential_self_hosted_jobs": [
            "bounded-context-preflight",
            "frozen-serial-phase",
        ],
        "source_head": source_head,
    }
    return _validate_runner_readiness(evidence, source_head=source_head)


def _local_stdout(
    argv: Sequence[str], *, safe_environment: Mapping[str, str], label: str
) -> str:
    raw = _run_readiness_command(
        argv,
        safe_environment=safe_environment,
        label=label,
    )
    try:
        return raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError(
            f"runner host preflight output is not UTF-8: {label}"
        ) from exc


def collect_local_runner_host_readiness(
    repository: Path,
    source_head: str,
    expected_readiness: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Re-observe the committed runner facts on the assigned Linux host."""

    environment = os.environ if environ is None else environ
    _validate_secret_free_branch_environment(environment)
    safe_environment = {
        key: value
        for key, value in environment.items()
        if key not in FORBIDDEN_PREFLIGHT_SECRETS
    }
    expected = _validate_runner_readiness(
        expected_readiness, source_head=source_head
    )
    require(os.name == "posix" and hasattr(os, "uname"), "runner host is not POSIX")
    architecture = os.uname().machine
    os_release = _validate_ubuntu_os_release(Path("/etc/os-release").read_bytes())
    require(
        tuple(sys.version_info[:3]) == (3, 11, 10),
        "runner host Python version differs",
    )
    expected_python = Path(f"{EXACT_PYTHON_ROOT}/bin/python").resolve(strict=True)
    observed_python = Path(sys.executable).resolve(strict=True)
    require(observed_python == expected_python, "runner host Python path differs")

    workspace = Path(str(environment.get("GITHUB_WORKSPACE", ""))).resolve(
        strict=True
    )
    workspace_roots = [
        root
        for root in RUNNER_ROOTS
        if workspace.is_relative_to(Path(root).resolve(strict=True))
    ]
    require(
        len(workspace_roots) == 1,
        "runner workspace is not inside exactly one fresh runner root",
    )

    listeners: list[dict[str, Any]] = []
    proc_root = Path("/proc")
    require(proc_root.is_dir(), "runner process filesystem is unavailable")
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            comm = (proc / "comm").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if comm != "Runner.Listener":
            continue
        try:
            process_environment = (proc / "environ").read_bytes().split(b"\0")
            cwd = os.readlink(proc / "cwd")
        except FileNotFoundError:
            continue
        keys = {
            item.split(b"=", 1)[0].decode("utf-8", errors="strict")
            for item in process_environment
            if item
        }
        require(
            not FORBIDDEN_PREFLIGHT_SECRETS.intersection(keys),
            "runner listener exposes a protected benchmark secret name",
        )
        listeners.append({"pid": int(proc.name), "root": cwd})
    listeners.sort(key=lambda row: str(row["root"]))
    require(
        len(listeners) == 2
        and [row["root"] for row in listeners] == list(RUNNER_ROOTS)
        and len({row["pid"] for row in listeners}) == 2,
        "live runner listener bindings differ",
    )

    expected_runners = expected["runners"]
    local_bindings: list[dict[str, Any]] = []
    for index, root in enumerate(RUNNER_ROOTS):
        root_path = Path(root)
        require(root_path.is_dir(), f"fresh runner root is missing: {root}")
        for relative in (".runner", "run.sh"):
            require(
                (root_path / relative).is_file(),
                f"fresh runner file is missing: {root}/{relative}",
            )
        require(
            (root_path / "_work" / "_tool").resolve(strict=True)
            == Path(RUNNER_TOOL_CACHE).resolve(strict=True),
            "runner tool cache differs",
        )
        config = strict_runner_config_json((root_path / ".runner").read_bytes())
        for filename in (".env", ".path"):
            path = root_path / filename
            if not path.exists():
                continue
            names = {
                line.split(b"=", 1)[0].decode("utf-8", errors="strict")
                for line in path.read_bytes().splitlines()
                if line
            }
            require(
                not FORBIDDEN_PREFLIGHT_SECRETS.intersection(names),
                f"runner config exposes a protected secret name: {root}/{filename}",
            )
        remote = expected_runners[index]
        require(
            config.get("agentId") == remote["id"]
            and config.get("agentName") == remote["name"]
            and config.get("gitHubUrl")
            == "https://github.com/Scuttie/enterprise-shared-memory-poc"
            and config.get("workFolder") == "_work",
            f"live local runner identity differs: {root}",
        )
        local_bindings.append(
            {
                "agent_id": remote["id"],
                "agent_name": remote["name"],
                "root": root,
                "work_folder": "_work",
            }
        )
    active_root_index = RUNNER_ROOTS.index(workspace_roots[0])
    require(
        environment.get("RUNNER_NAME")
        == expected_runners[active_root_index]["name"],
        "assigned runner name differs from its local root",
    )

    for root in STALE_RUNNER_ROOTS:
        require(not Path(root).exists(), f"stale runner workspace remains: {root}")
    docker_version = _local_stdout(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        safe_environment=safe_environment,
        label="live Docker daemon",
    )
    container_ids = _local_stdout(
        ["docker", "ps", "-aq"],
        safe_environment=safe_environment,
        label="live stale containers",
    )
    require(not container_ids, "a stale benchmark or service container remains")
    disk_available = shutil.disk_usage("/opt").free
    require(
        disk_available >= MINIMUM_RUNNER_DISK_BYTES,
        "live runner disk availability is below the frozen minimum",
    )
    images = _expected_execution_images(repository, source_head)
    for locked_image in images:
        _run_readiness_command(
            ["docker", "image", "inspect", locked_image],
            safe_environment=safe_environment,
            label=f"live cached image {locked_image}",
        )

    live_host = {
        "architecture": architecture,
        "cached_execution_images": len(images),
        "container_count": 0,
        "disk_available_bytes": disk_available,
        "docker_server_version": docker_version,
        "exact_python_path": f"{EXACT_PYTHON_ROOT}/bin/python",
        "exact_python_version": "Python 3.11.10",
        "forbidden_secret_names_present": [],
        "fresh_runner_roots": list(RUNNER_ROOTS),
        "listener_bindings": listeners,
        "local_runner_bindings": local_bindings,
        "minimum_disk_available_bytes": MINIMUM_RUNNER_DISK_BYTES,
        **os_release,
        "stale_runner_roots_absent": list(STALE_RUNNER_ROOTS),
        "tool_cache_root": RUNNER_TOOL_CACHE,
        "wsl_distribution": RUNNER_DISTRIBUTION,
    }
    expected_host = expected["host"]
    require(
        {
            key: value
            for key, value in live_host.items()
            if key != "disk_available_bytes"
        }
        == {
            key: value
            for key, value in expected_host.items()
            if key != "disk_available_bytes"
        },
        "live runner host facts differ from the committed readiness evidence",
    )
    return live_host


def validate_runner_host_preflight(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind a fresh local-host observation to the exact `_012` push run."""

    environment = os.environ if environ is None else environ
    _validate_secret_free_branch_environment(environment)
    require(environment.get("GITHUB_EVENT_NAME") == "push", "event is not push")
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "attempt must be one")
    require(
        environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY,
        "repository differs",
    )
    require(environment.get("GITHUB_REF") == EXPECTED_REF, "ref differs")
    require(
        environment.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF,
        "workflow ref differs",
    )
    require(
        environment.get("GITHUB_JOB") == "bounded-context-preflight",
        "runner host probe is outside the bounded-context preflight job",
    )
    require(
        environment.get("RUNNER_OS") == "Linux"
        and environment.get("RUNNER_ARCH") == "X64",
        "runner host platform differs",
    )
    run_id = environment.get("GITHUB_RUN_ID", "")
    require(run_id.isascii() and run_id.isdigit() and int(run_id) > 0, "run ID differs")

    event = strict_json(event_path.read_bytes())
    repository_record = event.get("repository")
    before, after = event.get("before"), event.get("after")
    require(
        event.get("ref") == EXPECTED_REF
        and event.get("created") is False
        and event.get("deleted") is False
        and event.get("forced") is False
        and isinstance(repository_record, Mapping)
        and repository_record.get("full_name") == EXPECTED_REPOSITORY
        and isinstance(before, str)
        and HEX40.fullmatch(before) is not None
        and isinstance(after, str)
        and HEX40.fullmatch(after) is not None,
        "runner host push payload differs",
    )
    require(
        environment.get("GITHUB_SHA") == after
        and environment.get("GITHUB_WORKFLOW_SHA") == after,
        "runner host execution SHA differs",
    )
    request = validate_sentinel_commit(
        repository,
        after,
        expected_parent=before,
        require_checked_out_head=True,
    )
    readiness = request["runner_readiness"]
    _validate_runner_readiness_freshness(readiness, now=now)
    live_host = collect_local_runner_host_readiness(
        repository,
        before,
        readiness,
        environ=environment,
    )
    return {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "execution_run_attempt": 1,
        "execution_run_id": int(run_id),
        "live_host_sha256": hashlib.sha256(canonical_bytes(live_host)).hexdigest(),
        "request_id": REQUEST_ID,
        "source_head": before,
        "status": "PASS",
        "trigger_commit": after,
    }


def _pinned_gh_context() -> tuple[str, dict[str, str]]:
    gh = shutil.which("gh")
    require(gh is not None, "gh CLI is required to verify remote gates")
    # The workflow installs the byte-pinned CLI before invoking this module.
    try:
        root = Path(__file__).resolve().parents[1]
        lock = load_gh_cli_lock(root / GH_CLI_LOCK_PATH)
        verification = verify_installed_gh(lock, Path(gh))
    except (ImportError, OSError, ValueError) as exc:
        raise DevelopmentTriggerError(
            "remote gate observer does not match the pinned gh byte lock"
        ) from exc
    require(
        verification.get("status") == "PASS"
        and verification.get("first_version_line")
        == "gh version 2.97.0 (2026-07-31)",
        "remote gate observer is not exact gh 2.97.0",
    )
    return gh, _safe_process_environment()


def _collect_current_pull_request(
    gh: str,
    safe_environment: Mapping[str, str],
    *,
    expected_head: str,
) -> dict[str, Any]:
    require(HEX40.fullmatch(expected_head) is not None, "PR head is not a commit SHA")
    pull_raw = _run_readiness_command(
        [
            gh,
            "api",
            "--hostname",
            "github.com",
            f"repos/{EXPECTED_REPOSITORY}/pulls/{PULL_REQUEST_NUMBER}",
        ],
        safe_environment=safe_environment,
        label="current PR #18",
    )
    pull_response = strict_json(pull_raw)
    pull_head = pull_response.get("head")
    pull_base = pull_response.get("base")
    pull_head_repo = (
        pull_head.get("repo") if isinstance(pull_head, Mapping) else None
    )
    record = {
        "base_ref": pull_base.get("ref") if isinstance(pull_base, Mapping) else None,
        "base_sha": pull_base.get("sha") if isinstance(pull_base, Mapping) else None,
        "draft": pull_response.get("draft"),
        "head_ref": pull_head.get("ref") if isinstance(pull_head, Mapping) else None,
        "head_repository": (
            pull_head_repo.get("full_name")
            if isinstance(pull_head_repo, Mapping)
            else None
        ),
        "head_sha": pull_head.get("sha") if isinstance(pull_head, Mapping) else None,
        "html_url": pull_response.get("html_url"),
        "number": pull_response.get("number"),
        "state": pull_response.get("state"),
    }
    require(
        record
        == {
            "base_ref": EXPECTED_BASE_BRANCH,
            "base_sha": EXPECTED_BASE_HEAD,
            "draft": True,
            "head_ref": EXPECTED_BRANCH,
            "head_repository": EXPECTED_REPOSITORY,
            "head_sha": expected_head,
            "html_url": (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/pull/18"
            ),
            "number": PULL_REQUEST_NUMBER,
            "state": "open",
        },
        "current PR #18 is not OPEN/DRAFT at the exact expected head",
    )
    return record


def _collect_remote_gate_rows(
    gh: str,
    safe_environment: Mapping[str, str],
    *,
    source_head: str,
) -> list[dict[str, Any]]:
    runs_by_event = {
        event: _query_github_runs(gh, source_head, event, safe_environment)
        for event in sorted({spec[1] for spec in REMOTE_GATE_SPECS})
    }
    return _select_remote_gate_rows(runs_by_event, source_head=source_head)


def _select_remote_gate_rows(
    runs_by_event: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    source_head: str,
) -> list[dict[str, Any]]:
    """Select source gates from immutable top-level workflow-run fields.

    ``workflow_run.pull_requests`` is mutable relationship metadata and is
    intentionally never inspected.  The current PR is queried and validated
    independently by :func:`_collect_current_pull_request`.
    """

    require(HEX40.fullmatch(source_head) is not None, "source head is invalid")
    rows: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    for path, event, pr_number in REMOTE_GATE_SPECS:
        matches = [
            run
            for run in runs_by_event.get(event, ())
            if run.get("path") == path
            and run.get("event") == event
            and run.get("head_sha") == source_head
        ]
        require(
            len(matches) == 1,
            f"exactly one exact-head event run is required: {path}:{event}",
        )
        run = matches[0]
        run_id = run.get("id")
        require(
            type(run_id) is int and run_id > 0 and run_id not in selected_ids,
            f"source gate run ID is invalid or duplicated: {path}:{event}",
        )
        selected_ids.add(run_id)
        rows.append(
            {
                "conclusion": run.get("conclusion"),
                "event": run.get("event"),
                "head_branch": run.get("head_branch"),
                "head_sha": run.get("head_sha"),
                "html_url": run.get("html_url"),
                "pull_request_number": pr_number,
                "run_attempt": run.get("run_attempt"),
                "run_id": run_id,
                "status": run.get("status"),
                "workflow_path": run.get("path"),
            }
        )
    return rows


def collect_remote_gate_evidence(source_head: str) -> dict[str, Any]:
    """Collect the exact mixed-event twelve-gate activation evidence."""

    require(HEX40.fullmatch(source_head) is not None, "source_head is not a commit SHA")
    gh, safe_environment = _pinned_gh_context()
    pull_record = _collect_current_pull_request(
        gh, safe_environment, expected_head=source_head
    )
    rows = _collect_remote_gate_rows(
        gh, safe_environment, source_head=source_head
    )
    evidence = {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "all_required_workflows_passed": True,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z"),
        "pull_request_number": PULL_REQUEST_NUMBER,
        "pull_request": pull_record,
        "repository": EXPECTED_REPOSITORY,
        "schema": REMOTE_GATE_SCHEMA,
        "source_head": source_head,
        "source_ref": EXPECTED_REF,
        "workflows": rows,
    }
    return _validate_remote_gate_evidence(evidence, source_head=source_head)


def _validate_unique_execution_run(
    trigger_head: str, environment: Mapping[str, str]
) -> dict[str, Any]:
    run_id_text = environment.get("GITHUB_RUN_ID")
    require(
        isinstance(run_id_text, str)
        and run_id_text.isascii()
        and run_id_text.isdigit()
        and int(run_id_text) > 0,
        "current workflow run ID is invalid",
    )
    gh, safe_environment = _pinned_gh_context()
    matches = [
        run
        for run in _query_github_runs(
            gh, trigger_head, "push", safe_environment
        )
        if run.get("path") == EXPECTED_WORKFLOW_PATH
        and run.get("event") == "push"
        and run.get("head_sha") == trigger_head
    ]
    require(
        len(matches) == 1,
        "exactly one benchmark workflow push run is allowed for _012 HEAD",
    )
    run = matches[0]
    require(
        run.get("id") == int(run_id_text)
        and run.get("run_attempt") == 1
        and run.get("head_branch") == EXPECTED_BRANCH
        and run.get("status") in {"queued", "in_progress", "completed"}
        and run.get("conclusion") in {None, "success"},
        "current benchmark workflow run identity differs",
    )
    return {
        "event": "push",
        "head_sha": trigger_head,
        "run_attempt": 1,
        "run_id": int(run_id_text),
        "workflow_path": EXPECTED_WORKFLOW_PATH,
    }


def _request_execution_contracts(bindings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "cell_failure_policy": {
            "contained_failures_remain_in_denominator": True,
            "grader_invoked_after_partial_patch_or_canonical_noop": True,
            "terminal_cell_and_ledger_written_before_cursor_advance": True,
        },
        "contract_bindings": {
            name: bindings[name]
            for name in (
                "loader_environment_contract_sha256",
                "loader_preflight_sha256",
                "grader_lifecycle_sha256",
                "cell_commit_journal_sha256",
                "resume_disposition_sha256",
            )
        },
        "global_failure_resume_allowed": False,
        "loader_preflight_before_credentials_models_images_and_reservation": True,
        "required_order": [
            "branch-trigger preflight",
            "bounded-context roundtrip",
            "D1.12 activation-bound cell-terminal roundtrip",
            "pinned harness materialization",
            "exact official-harness loader preflight",
            "protected approval materialization",
            "exact execution gate",
            "credential format and run binding",
            "exact-model metadata check",
            "protocol canary",
            "PostgreSQL migration",
            "digest-locked image materialization",
            "frozen DEV streams",
            "deterministic M2 selection",
            "M0 and M1",
            "aggregate",
            "public allowlisted result",
            "restricted-evidence inventory and encryption",
            "remote custody verification",
            "secret, runner, container and plaintext cleanup",
        ],
        "same_attempt_resume_dispositions": [
            "RESUME_SAFE_DURABLE_SUFFIX",
            "RESUME_SAFE_CELL_COMMIT_JOURNAL",
        ],
    }


def build_request(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    validated = _validate_source(repository, source_head)
    gates = _validate_remote_gate_evidence(
        remote_gate_evidence, source_head=source_head
    )
    readiness = _validate_runner_readiness(
        runner_readiness, source_head=source_head
    )
    hard_cap = validated["hard_cap"]
    bindings = validated["bindings"]
    previous = validated["previous_request"]
    previous_control_plane = previous.get("control_plane")
    previous_exact_model = previous.get("exact_model")
    previous_scientific_workload = previous.get("scientific_workload")
    require(
        isinstance(previous_control_plane, Mapping)
        and isinstance(previous_exact_model, Mapping)
        and isinstance(previous_scientific_workload, Mapping),
        "immutable _011 scientific template is malformed",
    )
    payload = {
        "actual_execution_authorized": False,
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "amendment_classification": AMENDMENT_CLASSIFICATION,
        "authorization_semantics": (
            "This sentinel creates one push run only. Protected execution requires "
            "one distinct approval bound to the sentinel commit, activation source, "
            "freeze, request bytes, workflow run ID/attempt, caps, actor, timestamp, "
            "nonce, legal acceptance, and exact OpenAI-key commitment."
        ),
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "control_plane": deepcopy(dict(previous_control_plane)),
        "d112_execution_contracts": _request_execution_contracts(bindings),
        "exact_model": deepcopy(dict(previous_exact_model)),
        "external_execution_approval_received": False,
        "hard_caps": hard_cap,
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
            "DEVELOPMENT_TUNING_EXEC_REQUEST_011_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_013",
            "HELDOUT_BENCHMARK",
            "component_ablation",
            "grader_smoke_rerun",
            "merge_tag_or_release",
            "model_or_reasoning_change",
            "post_start_code_approval_target_candidate_or_cap_change",
        ],
        "protected_environment": {
            "environment_name": "trimem-benchmark-exec",
            "permitted_secret_names": [
                "OPENAI_API_KEY",
                "TRIMEM_EXEC_APPROVAL_B64",
                "TRIMEM_EVIDENCE_PASSPHRASE",
            ],
            "sentinel_contains_execution_authority": False,
        },
        "recovery_provenance": {
            "benchmark_image_pulls": 0,
            "completed_terminal_cells": 0,
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": 1,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "grader_containers": 0,
            "grader_state": "NOT_STARTED_BEFORE_PROTECTED_ENVIRONMENT",
            "model_api_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "protected_environment_entered": False,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "remote_gate_evidence": gates,
        "runner_readiness": readiness,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "required_external_approval_fields": list(DEVELOPMENT_APPROVAL_FIELDS),
        "required_external_authorization": REQUIRED_EXTERNAL_AUTHORIZATION,
        "request_creation_authority_received": True,
        "requires_external_approval": True,
        "schema": REQUEST_SCHEMA,
        "scientific_workload": deepcopy(dict(previous_scientific_workload)),
        "source_head": source_head,
        "workflow_path": EXPECTED_WORKFLOW_PATH,
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
    gates = _validate_remote_gate_evidence(
        value.get("remote_gate_evidence"), source_head=source_head
    )
    readiness = _validate_runner_readiness(
        value.get("runner_readiness"), source_head=source_head
    )
    expected = build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
    )
    require(value == expected, "_012 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_012 request bytes are not canonical UTF-8 plus one LF",
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
    require(HEX40.fullmatch(after) is not None, "trigger commit SHA is invalid")
    if require_checked_out_head:
        require(git(repository, "rev-parse", "HEAD").strip() == after, "HEAD differs")
    parents = git(repository, "rev-list", "--parents", "-n", "1", after).split()
    require(len(parents) == 2, "trigger must be a single-parent commit")
    parent = parents[1]
    if expected_parent is not None:
        require(parent == expected_parent, "trigger parent differs from push before SHA")
    changes = git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        after,
    ).splitlines()
    require(
        changes == [f"A\t{SENTINEL_PATH}"],
        "trigger commit is not the exclusive _012 sentinel addition",
    )
    tree_entry = git(
        repository,
        "ls-tree",
        "--full-tree",
        after,
        "--",
        SENTINEL_PATH,
    ).strip().split("\t", 1)
    require(
        len(tree_entry) == 2
        and tree_entry[1] == SENTINEL_PATH
        and tree_entry[0].split()[:2] == ["100644", "blob"],
        "_012 sentinel is not a regular non-executable 100644 Git blob",
    )
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_012 already exists before the trigger commit",
    )
    return validate_request(
        repository,
        commit_bytes(repository, after, SENTINEL_PATH),
        source_head=parent,
    )


def _validate_secret_free_branch_environment(environ: Mapping[str, str]) -> None:
    exposed = sorted(name for name in FORBIDDEN_PREFLIGHT_SECRETS if name in environ)
    require(not exposed, "branch preflight exposes protected benchmark secrets")


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
    require(
        environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY,
        "repository differs",
    )
    require(environment.get("GITHUB_REF") == EXPECTED_REF, "ref differs")
    require(
        environment.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF,
        "workflow ref differs",
    )
    repository_record = event.get("repository")
    require(
        event.get("ref") == EXPECTED_REF
        and event.get("created") is False
        and isinstance(repository_record, Mapping)
        and repository_record.get("full_name") == EXPECTED_REPOSITORY,
        "push payload branch or repository identity differs",
    )
    require(event.get("forced") is False, "forced push is forbidden")
    require(event.get("deleted") is False, "deleted push is forbidden")
    before, after = event.get("before"), event.get("after")
    require(
        isinstance(before, str)
        and HEX40.fullmatch(before) is not None
        and isinstance(after, str)
        and HEX40.fullmatch(after) is not None,
        "push before/after SHA is invalid",
    )
    require(environment.get("GITHUB_SHA") == after, "event after SHA differs")
    require(environment.get("GITHUB_WORKFLOW_SHA") == after, "workflow SHA differs")
    _validate_secret_free_branch_environment(environment)
    execution_run = _validate_unique_execution_run(after, environment)
    request = validate_sentinel_commit(
        repository, after, expected_parent=before, require_checked_out_head=True
    )
    _validate_runner_readiness_freshness(request["runner_readiness"])
    gh, safe_environment = _pinned_gh_context()
    _collect_current_pull_request(
        gh, safe_environment, expected_head=after
    )
    live_rows = _collect_remote_gate_rows(
        gh, safe_environment, source_head=before
    )
    require(
        request.get("remote_gate_evidence", {}).get("workflows")
        == live_rows,
        "embedded remote gates differ from current exact remote runs",
    )
    require(
        request.get("runner_readiness", {}).get("runners")
        == collect_remote_runner_rows(),
        "embedded runner registrations differ from current repository runners",
    )
    return {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "request_id": REQUEST_ID,
        "execution_run": execution_run,
        "source_head": before,
        "status": "PASS",
        "trigger_commit": after,
    }


def write_request(repository: Path) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    _validate_secret_free_branch_environment(os.environ)
    require(
        git(repository, "symbolic-ref", "--quiet", "HEAD").strip()
        == EXPECTED_REF,
        "request rendering is on the wrong branch",
    )
    require(
        not git(
            repository, "status", "--porcelain=v1", "--untracked-files=all"
        ).strip(),
        "request rendering requires a clean worktree",
    )
    source_head = git(repository, "rev-parse", "HEAD").strip()
    target = repository / Path(*PurePosixPath(SENTINEL_PATH).parts)
    require(not target.exists(), "_012 sentinel already exists in the worktree")
    _validate_source(repository, source_head)
    gates = collect_remote_gate_evidence(source_head)
    readiness = collect_runner_readiness(repository, source_head)
    document = build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
    )
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise DevelopmentTriggerError("_012 sentinel could not be created exclusively") from exc
    return {
        "bytes": len(raw),
        "path": SENTINEL_PATH,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_head": source_head,
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-head")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--event-path", type=Path)
    group.add_argument("--runner-host-preflight-event-path", type=Path)
    group.add_argument("--write-request", action="store_true")
    group.add_argument("--validate-source", action="store_true")
    args = parser.parse_args(argv)
    if args.source_head is not None and not args.validate_source:
        parser.error("--source-head requires --validate-source")
    try:
        if args.write_request:
            result = write_request(args.repository)
        elif args.runner_host_preflight_event_path is not None:
            result = validate_runner_host_preflight(
                args.repository,
                args.runner_host_preflight_event_path,
            )
        elif args.validate_source:
            result = validate_correction_source(
                args.repository,
                args.source_head,
                require_checked_out_head=True,
            )
        else:
            result = validate_branch_trigger(args.repository, args.event_path)
    except (DevelopmentTriggerError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
