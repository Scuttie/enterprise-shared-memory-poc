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
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from trimem_install_pinned_gh import load_gh_cli_lock, verify_observer_gh


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
BENCHMARK_ENVIRONMENT_LOCK_PATH = "configs/trimem_v1/benchmark_environment_lock.json"

REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.12"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.12"
RUNNER_DISTRIBUTION = "TriMemRunner2404"
RUNNER_WSL_USER = "trimem-runner"
RUNNER_NAMES = ("trimem-d112-exec", "trimem-d112-preflight")
RUNNER_ROOTS = (
    "/opt/trimem-d112-runners/exec",
    "/opt/trimem-d112-runners/preflight",
)
RUNNER_TOOL_CACHE = "/opt/trimem-runner-cache/work-ci/_tool"
EXACT_PYTHON_ROOT = f"{RUNNER_TOOL_CACHE}/Python/3.11.10/x64"
EXACT_PYTHON_LIBRARY_PATH = f"{EXACT_PYTHON_ROOT}/lib"
PYTHON_TOOLCACHE_COMPLETE_PATH = f"{EXACT_PYTHON_ROOT}.complete"
PYTHON_TOOLCACHE_COMPLETE_BYTES = 0
PYTHON_TOOLCACHE_COMPLETE_SHA256 = (
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)
RUNNER_PACKAGE_VERSION = "2.337.0"
RUNNER_PACKAGE_ARCHIVE_PATH = (
    "/opt/trimem-runner-cache/actions-runner-linux-x64-2.337.0.tar.gz"
)
RUNNER_PACKAGE_ARCHIVE_BYTES = 226_430_031
RUNNER_PACKAGE_ARCHIVE_SHA256 = (
    "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613"
)
RUNNER_LISTENER_BYTES = 72_568
RUNNER_LISTENER_SHA256 = (
    "f4584cf5ef53ebc8507e9edfad07973e389ff6488906a1abe5f698aa86b295cf"
)
POSTGRES_SERVICE_IMAGE = (
    "postgres@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412"
)
QDRANT_SERVICE_IMAGE = (
    "qdrant/qdrant@sha256:241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636"
)
SERVICE_IMAGE_REFS = {
    "postgres": POSTGRES_SERVICE_IMAGE,
    "qdrant": QDRANT_SERVICE_IMAGE,
}
SERVICE_PORTS = {"postgres": 5432, "qdrant": 6333}
SERVICE_CONTAINER_NAME_PREFIX = "trimem-d112"
SERVICE_STATE_SCHEMA = "trimem/protected-cache-only-services/1.0"
SERVICE_STATE_FILENAME = "trimem-d112-cache-only-services.json"
RUNNER_SERVICE_UID = 1000
RUNNER_SERVICE_GID = 1000
DOCKER_VERSION = "29.1.3"
DOCKER_CREATE_PULL_NEVER_MARKER = "--pull string Pull image before creating"
DOCKER_CLIENT_PATH = "/usr/bin/docker"
DOCKER_CLIENT_BYTES = 31_369_824
DOCKER_CLIENT_SHA256 = (
    "7ed12b00293d64742419a6601ae97960a367a0ce97c88b06e3278cc0a409557b"
)
DOCKER_ROOT_DIRECTORY = "/var/lib/docker"
DOCKER_LOCAL_PREFIX = (
    DOCKER_CLIENT_PATH,
    "--host",
    "unix:///var/run/docker.sock",
)
DOCKER_AUTHORITY_ENV = frozenset(
    {
        "DOCKER_API_VERSION",
        "DOCKER_CERT_PATH",
        "DOCKER_CONTENT_TRUST",
        "DOCKER_CONTENT_TRUST_SERVER",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_DEFAULT_PLATFORM",
        "DOCKER_HOST",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
    }
)
SERVICE_READY_TIMEOUT_SECONDS = 120
SERVICE_READY_POLL_SECONDS = 2
BENCHMARK_EXEC_RUNNER_BOUNDARY = (
    "protected ephemeral self-hosted runner; one serial phase job owns "
    "PostgreSQL, Qdrant and the atomic global ledger"
)
MINIMUM_RUNNER_DISK_BYTES = 500 * 1024 * 1024 * 1024
MAXIMUM_RUNNER_READINESS_AGE_SECONDS = 60 * 60
MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS = 5 * 60
REMOTE_VISIBILITY_TIMEOUT_SECONDS = 30
REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS = 2
REMOTE_VISIBILITY_MAX_POLLS = (
    REMOTE_VISIBILITY_TIMEOUT_SECONDS // REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS
    + 1
)
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
        ".gitattributes",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/trimem-benchmark.yml",
        AMENDMENT_PATH,
        INVENTORY_PATH,
        "artifacts/trimem_v1/readiness_requirements.json",
        GH_CLI_LOCK_PATH,
        FREEZE_PATH,
        "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md",
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_d112_reseal.py",
        "scripts/trimem_development_trigger_preflight.py",
        "scripts/trimem_development_trigger_d112.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_install_pinned_gh.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_pinned_gh.py",
        "tests/unit/test_trimem_d112_e1_trigger.py",
        "tests/unit/test_trimem_d112_status_and_reseal.py",
        "tests/unit/test_trimem_development_trigger.py",
    }
)
REQUIRED_ACTIVATION_CHANGES = {
    ".gitattributes": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    GH_CLI_LOCK_PATH: "M",
    FREEZE_PATH: "M",
    "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md": "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_d112_reseal.py": "A",
    "scripts/trimem_development_trigger_preflight.py": "M",
    "scripts/trimem_development_trigger_d112.py": "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_install_pinned_gh.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d112_e1_trigger.py": "A",
    "tests/unit/test_trimem_d112_status_and_reseal.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_pinned_gh.py": "M",
}
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
    "gitattributes_sha256": ".gitattributes",
    "approval_consumer_sha256": "scripts/trimem_exec_approval.py",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "d112_amendment_sha256": AMENDMENT_PATH,
    "d112_inventory_sha256": INVENTORY_PATH,
    "gh_cli_lock_sha256": GH_CLI_LOCK_PATH,
    "gh_observer_verifier_sha256": "scripts/trimem_install_pinned_gh.py",
    "gh_observer_verifier_test_sha256": "tests/unit/test_trimem_pinned_gh.py",
    "historical_preflight_compatibility_sha256": (
        "scripts/trimem_development_trigger_preflight.py"
    ),
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
) | DOCKER_AUTHORITY_ENV

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DOCKER_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")


class DevelopmentTriggerError(ValueError):
    """The D1.12 source, request, remote gates, or branch event differs."""


# Kept as an explicit alias for diagnostics without changing the stable name
# consumed by the runner and matrix.
DevelopmentTriggerD112Error = DevelopmentTriggerError


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DevelopmentTriggerError(message)


def _remaining_visibility_seconds(
    deadline: float,
    monotonic: Callable[[], float],
    *,
    failure_message: str,
) -> float:
    remaining = deadline - monotonic()
    if not remaining > 0:
        raise DevelopmentTriggerError(failure_message)
    return min(float(REMOTE_VISIBILITY_TIMEOUT_SECONDS), remaining)


def _sleep_for_visibility_retry(
    deadline: float,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
    *,
    failure_message: str,
) -> None:
    remaining = _remaining_visibility_seconds(
        deadline, monotonic, failure_message=failure_message
    )
    sleeper(min(float(REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS), remaining))


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


def resolve_repository_root(repository: Path) -> Path:
    """Return ``repository`` only when it is the exact Git worktree root."""

    resolved = repository.resolve(strict=True)
    require(resolved.is_dir(), "repository path is not a directory")
    reported = git(resolved, "rev-parse", "--show-toplevel").strip()
    require(bool(reported), "Git did not report a repository top-level")
    top_level = Path(reported).resolve(strict=True)
    require(
        resolved == top_level,
        "repository path must be the exact Git worktree top-level",
    )
    return resolved


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
    benchmark_environment = strict_json(
        commit_bytes(
            repository,
            source_head,
            "configs/trimem_v1/benchmark_environment_lock.json",
        )
    )
    frozen_runner = benchmark_environment.get("runner")
    require(
        benchmark_environment.get("schema")
        == "trimem/benchmark-environment-lock/1.0"
        and benchmark_environment.get("status") == "FROZEN"
        and isinstance(frozen_runner, Mapping)
        and frozen_runner.get("benchmark_exec_runner_boundary")
        == BENCHMARK_EXEC_RUNNER_BOUNDARY
        and frozen_runner.get("benchmark_exec_runner_labels")
        == list(REQUIRED_RUNNER_LABELS)
        and frozen_runner.get("operating_system") == "linux"
        and frozen_runner.get("architecture") == "x86_64"
        and frozen_runner.get("python_implementation") == "CPython"
        and frozen_runner.get("python_version") == "3.11.10",
        "frozen benchmark execution runner boundary differs",
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
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        workflow.count(branch_marker) == 1
        and workflow.count(bounded_marker) == 1
        and workflow.count(frozen_marker) == 1,
        "D1.12 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(
        branch_start < bounded_start < frozen_start,
        "D1.12 workflow job order differs",
    )
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    protected_mode = '--protected-runner-preflight-event-path "$GITHUB_EVENT_PATH"'
    pre_setup_mode = '--pre-setup-cache-host-event-path "$GITHUB_EVENT_PATH"'
    start_mode = '--start-protected-services-event-path "$GITHUB_EVENT_PATH"'
    verify_mode = '--verify-protected-services-event-path "$GITHUB_EVENT_PATH"'
    cleanup_mode = '--cleanup-protected-services-event-path "$GITHUB_EVENT_PATH"'
    require(
        branch_job.count(active_command) == 1
        and bounded_job.count(active_command) == 1
        and frozen_job.count(active_command) == 4
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
        "runs-on: ubuntu-24.04" in branch_job
        and "runs-on: [self-hosted" not in branch_job
        and "runs-on: [self-hosted" in bounded_job
        and "runs-on: [self-hosted" in frozen_job
        and branch_job.count('--event-path "$GITHUB_EVENT_PATH"') == 1
        and '--event-path "$GITHUB_EVENT_PATH"' not in bounded_job
        and bounded_job.count(
            '--runner-host-preflight-event-path "$GITHUB_EVENT_PATH"'
        )
        == 1
        and "--runner-host-preflight-event-path" not in branch_job
        and bounded_job.count(pre_setup_mode) == 1
        and frozen_job.count(pre_setup_mode) == 1
        and frozen_job.count(protected_mode) == 1
        and frozen_job.count(start_mode) == 1
        and frozen_job.count(verify_mode) == 1
        and frozen_job.count(cleanup_mode) == 1
        and protected_mode not in branch_job
        and protected_mode not in bounded_job
        and "    services:\n" not in frozen_job
        and "job.services." not in frozen_job
        and workflow.count("github.run_attempt == 1") >= 2
        and "environment:" not in workflow[:frozen_start]
        and frozen_job.count("environment: trimem-benchmark-exec") == 1
        and "secrets." not in workflow[:frozen_start],
        "D1.12 attempt, host-preflight, or protected-environment gate differs",
    )
    bounded_pre_setup = f'''\
      - name: Checkout bounded-context correction
        uses: actions/checkout@{CHECKOUT_ACTION_SHA}
        with:
          fetch-depth: 0
          persist-credentials: false
          ref: ${{{{ github.sha }}}}
      - name: Verify complete cached Python before setup-python
        env:
          LD_LIBRARY_PATH: {EXACT_PYTHON_LIBRARY_PATH}
          RUNNER_TOOL_CACHE: ${{{{ runner.tool_cache }}}}
        run: >-
          {EXACT_PYTHON_ROOT}/bin/python
          -I -S scripts/trimem_development_trigger_d112.py
          --repository "$GITHUB_WORKSPACE"
          {pre_setup_mode}
      - name: Set up exact Python
        uses: actions/setup-python@{SETUP_PYTHON_ACTION_SHA}
        env:
          RUNNER_TOOL_CACHE: ${{{{ runner.tool_cache }}}}
'''
    require(
        bounded_job.count(bounded_pre_setup) == 1
        and bounded_job.index("Set up exact Python")
        < bounded_job.index("Re-observe exact self-hosted runner")
        < bounded_job.index("Install hash-locked environment"),
        "bounded pre-setup cache-host order differs",
    )
    protected_step = f'''\
      - name: Checkout approved frozen source
        uses: actions/checkout@{CHECKOUT_ACTION_SHA}
        with:
          fetch-depth: 0
          persist-credentials: false
          ref: ${{{{ github.sha }}}}
      - name: Verify complete cached Python before setup-python
        env:
          LD_LIBRARY_PATH: {EXACT_PYTHON_LIBRARY_PATH}
          RUNNER_TOOL_CACHE: ${{{{ runner.tool_cache }}}}
        run: >-
          {EXACT_PYTHON_ROOT}/bin/python
          -I -S scripts/trimem_development_trigger_d112.py
          --repository "$GITHUB_WORKSPACE"
          {pre_setup_mode}
      - name: Set up exact Python
        uses: actions/setup-python@{SETUP_PYTHON_ACTION_SHA}
        env:
          RUNNER_TOOL_CACHE: ${{{{ runner.tool_cache }}}}
        with:
          python-version: 3.11.10
          cache: ""
      - name: Re-observe protected runner before cache-only service creation
        run: >-
          {active_command}
          --repository "$GITHUB_WORKSPACE"
          {protected_mode}
      - name: Start exact cache-only benchmark services
        run: >-
          {active_command}
          --repository "$GITHUB_WORKSPACE"
          {start_mode}
      - name: Verify exact cache-only benchmark services
        run: >-
          {active_command}
          --repository "$GITHUB_WORKSPACE"
          {verify_mode}
      - name: Install hash-locked environment
'''
    require(
        frozen_job.count(protected_step) == 1
        and "secrets." not in protected_step
        and frozen_job.index(protected_step)
        < frozen_job.index("Materialize protected external approval"),
        "protected cache-only lifecycle placement differs",
    )
    runner_tool_cache_forwarding = "RUNNER_TOOL_CACHE: ${{ runner.tool_cache }}"
    require(
        bounded_job.count(runner_tool_cache_forwarding) == 2
        and frozen_job.count(runner_tool_cache_forwarding) == 2,
        "setup-python does not inherit the validated runner tool cache",
    )
    cleanup_step = f'''\
      - name: Remove exact cache-only benchmark services
        if: always()
        run: >-
          {active_command}
          --repository "$GITHUB_WORKSPACE"
          {cleanup_mode}'''
    require(
        frozen_job.count(cleanup_step) == 1
        and frozen_job.rstrip().endswith(cleanup_step)
        and "docker manifest" not in frozen_job
        and "docker pull" not in frozen_job,
        "cache-only service cleanup or no-pull boundary differs",
    )
    exact_ipv4_consumers = (
        "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@127.0.0.1:5432/trimem_benchmark",
        "TRIMEM_QDRANT_URL: http://127.0.0.1:6333",
        "DATABASE_URL: postgresql://postgres:postgres@127.0.0.1:5432/trimem_benchmark",
        "PGHOST: 127.0.0.1",
        "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/trimem_benchmark",
    )
    require(
        all(frozen_job.count(binding) == 1 for binding in exact_ipv4_consumers)
        and "@localhost:5432" not in frozen_job
        and "http://localhost:6333" not in frozen_job
        and "PGHOST: localhost" not in frozen_job,
        "benchmark service consumers are not exact IPv4 loopback bindings",
    )
    exact_selector = (
        "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, "
        "trimem-benchmark]"
    )
    workflow_paths = git(
        repository,
        "ls-tree",
        "-r",
        "--name-only",
        source_head,
        "--",
        ".github/workflows",
    ).splitlines()
    require(EXPECTED_WORKFLOW_PATH in workflow_paths, "benchmark workflow is missing")
    for path in workflow_paths:
        if path == EXPECTED_WORKFLOW_PATH:
            continue
        try:
            other = commit_bytes(repository, source_head, path).decode(
                "utf-8", errors="strict"
            )
        except UnicodeDecodeError as exc:
            raise DevelopmentTriggerError("workflow source is not UTF-8") from exc
        require(
            exact_selector not in other
            and not all(label in other for label in REQUIRED_RUNNER_LABELS),
            "another workflow can select the protected benchmark runner",
        )
    ordered_markers = (
        "Verify one-time zero-authority DEV trigger",
        "Re-observe exact self-hosted runner before any install or materialization",
        "Verify bounded context round trip before provider access",
        "Verify production terminal-cell round trip before provider access",
        "Materialize pinned harnesses in unprotected loader preflight",
        "Gate protected job on unprotected exact loader preflight",
        "Re-observe protected runner before cache-only service creation",
        "Start exact cache-only benchmark services",
        "Verify exact cache-only benchmark services",
        "Materialize protected external approval",
        "Verify exact phase EXEC gate",
        "Validate exact OpenAI credential format before network access",
        "Retrieve exact model metadata before image materialization",
        "Execute one native-action protocol canary before benchmark images",
        "Apply exact migration head",
        "Pull committed images by digest and verify local observations",
        "Execute frozen serial streams with one atomic phase ledger",
        "Aggregate exact stream and target set fail closed",
        "Build public allowlisted result",
        "Inventory complete restricted benchmark evidence",
        "Encrypt complete restricted evidence",
        "Verify durable external artifact custody before cleanup",
        "Remove plaintext and temporary EXEC material",
        "Remove exact cache-only benchmark services",
    )
    positions: list[int] = []
    for marker in ordered_markers:
        require(workflow.count(marker) == 1, f"workflow stage differs: {marker}")
        positions.append(workflow.index(marker))
    require(positions == sorted(positions), "D1.12 workflow stage order differs")


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
    repository = resolve_repository_root(repository)
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
    repository = resolve_repository_root(repository)
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
    expected_pull = {
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
    }
    require(
        isinstance(pull, Mapping)
        and set(pull) == set(expected_pull)
        and pull.get("draft") is True
        and type(pull.get("number")) is int
        and pull == expected_pull,
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
    gh: str,
    source_head: str | None,
    event: str | None,
    safe_environment: Mapping[str, str],
    *,
    timeout: float = 60,
    complete_result_required: bool = True,
) -> list[dict[str, Any]]:
    require(timeout > 0, "GitHub remote gate query timeout is exhausted")
    arguments = [
        gh,
        "api",
        "--hostname",
        "github.com",
        "--method",
        "GET",
        f"repos/{EXPECTED_REPOSITORY}/actions/runs",
    ]
    if source_head is not None:
        require(
            isinstance(source_head, str)
            and HEX40.fullmatch(source_head) is not None,
            "GitHub remote gate query head is invalid",
        )
        arguments.extend(["-f", f"head_sha={source_head}"])
    if event is not None:
        require(
            event in {"push", "pull_request"},
            "GitHub remote gate query event is invalid",
        )
        arguments.extend(["-f", f"event={event}"])
    arguments.extend(["-f", "per_page=100"])
    try:
        query = subprocess.run(
            arguments,
            capture_output=True,
            text=False,
            check=False,
            timeout=timeout,
            env=dict(safe_environment),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerError("GitHub remote gate query failed") from exc
    require(query.returncode == 0, "GitHub remote gate query failed")
    response = strict_json(query.stdout)
    runs = response.get("workflow_runs")
    require(isinstance(runs, list), "GitHub remote gate response has no workflow runs")
    require(
        all(isinstance(run, Mapping) for run in runs),
        "GitHub remote gate response contains a malformed workflow run",
    )
    total = response.get("total_count")
    if complete_result_required:
        require(
            type(total) is int and total == len(runs) and total <= 100,
            "GitHub remote gate response is incomplete or paginated",
        )
    else:
        require(
            type(total) is int and total >= len(runs) and len(runs) <= 100,
            "GitHub workflow-run visibility response is malformed",
        )
    return [dict(run) for run in runs]


def _require_no_pending_benchmark_consumers(
    gh: str, safe_environment: Mapping[str, str]
) -> None:
    """Reject active consumers from one complete, transition-safe snapshot."""

    raw = _run_readiness_command(
        [
            gh,
            "api",
            "--hostname",
            "github.com",
            "--method",
            "GET",
            f"repos/{EXPECTED_REPOSITORY}/actions/workflows/trimem-benchmark.yml/runs",
            "-f",
            "per_page=100",
            "--paginate",
            "--slurp",
        ],
        safe_environment=safe_environment,
        label="complete benchmark workflow consumer snapshot",
    )
    pages = strict_json(b'{"pages":' + raw + b"}").get("pages")
    require(isinstance(pages, list) and len(pages) >= 1, "benchmark run snapshot is malformed")
    totals: set[int] = set()
    rows: list[Mapping[str, Any]] = []
    for index, page in enumerate(pages):
        require(
            isinstance(page, Mapping)
            and set(page) == {"total_count", "workflow_runs"}
            and type(page.get("total_count")) is int
            and page["total_count"] >= 0
            and isinstance(page.get("workflow_runs"), list)
            and len(page["workflow_runs"]) <= 100
            and (index == len(pages) - 1 or len(page["workflow_runs"]) == 100),
            "benchmark run snapshot page is malformed",
        )
        totals.add(int(page["total_count"]))
        rows.extend(page["workflow_runs"])
    require(
        len(totals) == 1
        and len(rows) == next(iter(totals))
        and len(pages) == max(1, (len(rows) + 99) // 100),
        "benchmark run snapshot changed or is incomplete during pagination",
    )
    allowed_statuses = {
        "completed",
        "in_progress",
        "pending",
        "queued",
        "requested",
        "waiting",
    }
    active_statuses = {"in_progress", "pending", "queued", "requested", "waiting"}
    observed_ids: set[int] = set()
    for row in rows:
        require(
            isinstance(row, Mapping)
            and type(row.get("id")) is int
            and row["id"] > 0
            and row["id"] not in observed_ids
            and row.get("path") == EXPECTED_WORKFLOW_PATH
            and row.get("status") in allowed_statuses,
            "benchmark workflow run snapshot row is malformed or duplicated",
        )
        observed_ids.add(int(row["id"]))
    require(
        not any(row.get("status") in active_statuses for row in rows),
        "an existing benchmark workflow consumer is still active",
    )


def _query_github_run_by_id(
    gh: str,
    run_id: int,
    safe_environment: Mapping[str, str],
    *,
    timeout: float,
) -> dict[str, Any] | None:
    """Read one run by immutable ID; a narrowly identified 404 is not-yet-visible."""

    require(type(run_id) is int and run_id > 0, "GitHub workflow run ID is invalid")
    require(timeout > 0, "GitHub workflow-run query timeout is exhausted")
    try:
        query = subprocess.run(
            [
                gh,
                "api",
                "--hostname",
                "github.com",
                "--method",
                "GET",
                f"repos/{EXPECTED_REPOSITORY}/actions/runs/{run_id}",
            ],
            capture_output=True,
            text=False,
            check=False,
            timeout=timeout,
            env=dict(safe_environment),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerError("GitHub workflow-run ID query failed") from exc
    if query.returncode != 0:
        try:
            error = query.stderr.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise DevelopmentTriggerError(
                "GitHub workflow-run ID query returned malformed stderr"
            ) from exc
        if query.returncode == 1 and error == "gh: Not Found (HTTP 404)":
            return None
        raise DevelopmentTriggerError("GitHub workflow-run ID query failed")
    return strict_json(query.stdout)


def _safe_process_environment() -> dict[str, str]:
    docker_controls = sorted(
        name for name in os.environ if name.upper().startswith("DOCKER_")
    )
    require(not docker_controls, "process environment exposes a Docker control name")
    return {
        key: value
        for key, value in os.environ.items()
        if not _is_forbidden_environment_name(key)
    }


def _is_forbidden_environment_name(name: str) -> bool:
    """Reject protected names and every Docker CLI control namespace.

    Windows environment names are case-insensitive, so case-folding here also
    prevents a request writer from smuggling a lower/mixed-case Docker override
    into WSL or a later Linux process.
    """

    return (
        name in FORBIDDEN_PREFLIGHT_SECRETS
        or name.upper().startswith("DOCKER_")
    )


def _forbidden_environment_names(bindings: Mapping[str, str]) -> list[str]:
    return sorted(name for name in bindings if _is_forbidden_environment_name(name))


def _safe_environment(bindings: Mapping[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in bindings.items()
        if not _is_forbidden_environment_name(key)
    }


def _run_readiness_command(
    argv: Sequence[str],
    *,
    safe_environment: Mapping[str, str],
    label: str,
    timeout: float = 60,
    cwd: Path | str | None = None,
) -> bytes:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            check=False,
            timeout=timeout,
            env=dict(safe_environment),
            cwd=cwd,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerError(f"runner readiness command failed: {label}") from exc
    require(
        completed.returncode == 0,
        f"runner readiness command failed: {label}",
    )
    return completed.stdout


def _collect_remote_runner_rows(
    gh: str, safe_environment: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Read the complete repository-runner set without exposing benchmark secrets."""

    require(isinstance(gh, str) and bool(gh), "verified GitHub observer is missing")
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
        safe_environment=safe_environment,
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


def collect_remote_runner_rows() -> list[dict[str, Any]]:
    """Collect runners through the same byte-pinned observer as all gates."""

    return _collect_remote_runner_rows(*_pinned_gh_context())


def _wsl_stdout(
    wsl: str,
    args: Sequence[str],
    *,
    safe_environment: Mapping[str, str],
    label: str,
    cwd: str | None = None,
) -> str:
    raw = _run_readiness_command(
        [*_wsl_command_prefix(wsl, cwd=cwd), *args],
        safe_environment=safe_environment,
        label=label,
    )
    try:
        return raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError(
            f"runner readiness output is not UTF-8: {label}"
        ) from exc


def _wsl_command_prefix(wsl: str, *, cwd: str | None = None) -> list[str]:
    require(bool(wsl) and "\x00" not in wsl, "WSL executable path is malformed")
    arguments = [
        wsl,
        "-d",
        RUNNER_DISTRIBUTION,
        "--user",
        RUNNER_WSL_USER,
    ]
    if cwd is not None:
        require(
            cwd in RUNNER_ROOTS and PurePosixPath(cwd).is_absolute(),
            "WSL working directory is not an exact runner root",
        )
        arguments.extend(["--cd", cwd])
    return [*arguments, "--"]


def _validate_wsl_runner_identity(raw: str) -> tuple[int, int, str]:
    expected = f"{RUNNER_SERVICE_UID}:{RUNNER_SERVICE_GID}:{RUNNER_WSL_USER}"
    require(raw == expected, "explicit WSL runner user UID/GID differs")
    return RUNNER_SERVICE_UID, RUNNER_SERVICE_GID, RUNNER_WSL_USER


def _validate_local_runner_identity(
    uid: Any, gid: Any, user: Any
) -> tuple[int, int, str]:
    require(
        type(uid) is int
        and uid == RUNNER_SERVICE_UID
        and type(gid) is int
        and gid == RUNNER_SERVICE_GID
        and user == RUNNER_WSL_USER,
        "local runner user UID/GID differs",
    )
    return uid, gid, str(user)


def _observe_local_runner_identity() -> tuple[int, int, str]:
    require(
        os.name == "posix" and hasattr(os, "getuid") and hasattr(os, "getgid"),
        "local runner identity requires POSIX",
    )
    try:
        import pwd

        user = pwd.getpwuid(os.getuid()).pw_name
    except (ImportError, KeyError) as exc:
        raise DevelopmentTriggerError("local runner user cannot be resolved") from exc
    return _validate_local_runner_identity(os.getuid(), os.getgid(), user)


def _verify_wsl_file_lock(
    wsl: str,
    path: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    safe_environment: Mapping[str, str],
    label: str,
) -> None:
    regular = _wsl_stdout(
        wsl,
        [
            "sh",
            "-c",
            'test -f "$1" && test ! -L "$1" && readlink -f -- "$1"',
            "trimem-file-lock",
            path,
        ],
        safe_environment=safe_environment,
        label=f"{label} direct regular file",
    )
    observed_bytes = _wsl_stdout(
        wsl,
        ["stat", "-c", "%s", "--", path],
        safe_environment=safe_environment,
        label=f"{label} size",
    )
    observed_sha256 = _wsl_stdout(
        wsl,
        ["sha256sum", "--", path],
        safe_environment=safe_environment,
        label=f"{label} SHA-256",
    )
    require(
        regular == path and observed_bytes == str(expected_bytes),
        f"locked file size differs: {label}",
    )
    require(
        observed_sha256 == f"{expected_sha256}  {path}",
        f"locked file SHA-256 differs: {label}",
    )


def _wsl_exact_python_argv(*arguments: str) -> list[str]:
    """Launch the Actions-cached Python with its frozen shared-library root."""

    return [
        "env",
        f"LD_LIBRARY_PATH={EXACT_PYTHON_LIBRARY_PATH}",
        f"{EXACT_PYTHON_ROOT}/bin/python",
        *arguments,
    ]


def _strict_environment_bindings(
    raw: bytes,
    *,
    separator: bytes,
    label: str,
) -> dict[str, str]:
    """Decode a runner-owned environment file without normalization."""

    require(separator in {b"\n", b"\0"}, "environment separator is invalid")
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError(
            f"runner environment is not strict UTF-8: {label}"
        ) from exc
    delimiter = separator.decode("ascii")
    pieces = decoded.split(delimiter)
    if pieces and pieces[-1] == "":
        pieces.pop()
    bindings: dict[str, str] = {}
    for piece in pieces:
        if separator == b"\n" and piece.endswith("\r"):
            piece = piece[:-1]
        require(
            bool(piece)
            and all(ord(character) >= 32 and ord(character) != 127 for character in piece)
            and "=" in piece,
            f"runner environment row is malformed: {label}",
        )
        name, value = piece.split("=", 1)
        require(
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is not None,
            f"runner environment name is malformed: {label}",
        )
        require(name not in bindings, f"runner environment name is duplicated: {label}")
        bindings[name] = value
    return bindings


def _require_exact_python_library_binding(
    bindings: Mapping[str, str], *, label: str
) -> str:
    require(
        bindings.get("LD_LIBRARY_PATH") == EXACT_PYTHON_LIBRARY_PATH,
        f"runner LD_LIBRARY_PATH binding differs: {label}",
    )
    return EXACT_PYTHON_LIBRARY_PATH


def _require_pre_setup_runner_tool_cache_binding(
    bindings: Mapping[str, str], *, active_root: str, label: str
) -> str:
    """Bind setup-python to the active runner's intended central-cache link."""

    expected_value = f"{active_root}/_work/_tool"
    require(
        bindings.get("RUNNER_TOOL_CACHE") == expected_value,
        f"RUNNER_TOOL_CACHE string differs: {label}",
    )
    selected = Path(expected_value)
    central = Path(RUNNER_TOOL_CACHE)
    try:
        selected_resolved = selected.resolve(strict=True)
        central_resolved = central.resolve(strict=True)
    except OSError as exc:
        raise DevelopmentTriggerError(
            f"RUNNER_TOOL_CACHE path is missing: {label}"
        ) from exc
    require(
        selected.is_dir()
        and selected.is_symlink()
        and selected_resolved == central
        and central.is_dir()
        and not central.is_symlink()
        and central_resolved == central,
        f"RUNNER_TOOL_CACHE path binding differs: {label}",
    )
    return expected_value


def _validate_docker_version(raw: str) -> tuple[str, str]:
    require(
        raw == f"{DOCKER_VERSION} {DOCKER_VERSION}",
        "Docker client/server version differs",
    )
    return DOCKER_VERSION, DOCKER_VERSION


def _validate_docker_root_directory(raw: str) -> str:
    require(raw == DOCKER_ROOT_DIRECTORY, "Docker root directory differs")
    return DOCKER_ROOT_DIRECTORY


def _validate_docker_pull_never_help(raw: str) -> bool:
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    matching = [line for line in lines if line == DOCKER_CREATE_PULL_NEVER_MARKER]
    require(
        len(matching) == 1,
        "Docker create does not expose the pinned --pull=never contract",
    )
    return True


def _verify_local_file_lock(
    path: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
    label: str,
) -> None:
    require(
        path.is_file()
        and not path.is_symlink()
        and path.resolve(strict=True) == path,
        f"locked file is missing or indirect: {label}",
    )
    require(path.stat().st_size == expected_bytes, f"locked file size differs: {label}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise DevelopmentTriggerError(f"locked file could not be read: {label}") from exc
    require(
        digest.hexdigest() == expected_sha256,
        f"locked file SHA-256 differs: {label}",
    )


def _verify_local_docker_client() -> None:
    path = Path(DOCKER_CLIENT_PATH)
    _verify_local_file_lock(
        path,
        expected_bytes=DOCKER_CLIENT_BYTES,
        expected_sha256=DOCKER_CLIENT_SHA256,
        label="absolute Docker client",
    )
    observed = path.stat()
    require(
        stat.S_IMODE(observed.st_mode) == 0o755
        and observed.st_uid == 0
        and observed.st_gid == 0,
        "absolute Docker client ownership or mode differs",
    )


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


def _expected_service_images(repository: Path, source_head: str) -> dict[str, str]:
    """Read the two service image identities from the frozen source blob."""

    lock = strict_json(
        commit_bytes(repository, source_head, BENCHMARK_ENVIRONMENT_LOCK_PATH)
    )
    services = lock.get("credential_free_real_services")
    require(
        lock.get("schema") == "trimem/benchmark-environment-lock/1.0"
        and isinstance(services, Mapping)
        and set(services) == set(SERVICE_IMAGE_REFS),
        "frozen service image lock is malformed",
    )
    observed: dict[str, str] = {}
    for role, expected_image in SERVICE_IMAGE_REFS.items():
        record = services.get(role)
        require(
            isinstance(record, Mapping)
            and record.get("image") == expected_image,
            f"frozen {role} service image identity differs",
        )
        observed[role] = expected_image
    return observed


def _probe_local_service_ports_available() -> list[int]:
    """Bind both exact IPv4 loopback ports without making a network request."""

    sockets: list[socket.socket] = []
    try:
        for port in SERVICE_PORTS.values():
            ipv4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sockets.append(ipv4)
            ipv4.bind(("127.0.0.1", port))
        return list(SERVICE_PORTS.values())
    except OSError as exc:
        raise DevelopmentTriggerError(
            "a frozen service host port is not free and bindable"
        ) from exc
    finally:
        for probe in sockets:
            probe.close()


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
            "available_service_ports",
            "cached_execution_images",
            "container_count",
            "disk_available_bytes",
            "docker_client_bytes",
            "docker_client_path",
            "docker_client_sha256",
            "docker_client_version",
            "docker_create_pull_never_supported",
            "docker_root_directory",
            "docker_server_version",
            "exact_python_library_path",
            "exact_python_path",
            "exact_python_version",
            "forbidden_secret_names_present",
            "fresh_runner_roots",
            "listener_bindings",
            "local_runner_bindings",
            "minimum_disk_available_bytes",
            "os_id",
            "os_version_id",
            "python_toolcache_complete_bytes",
            "python_toolcache_complete_path",
            "python_toolcache_complete_sha256",
            "runner_listener_bytes",
            "runner_listener_sha256",
            "runner_package_archive_bytes",
            "runner_package_archive_path",
            "runner_package_archive_sha256",
            "runner_package_version",
            "service_image_ids",
            "service_images",
            "stale_runner_roots_absent",
            "tool_cache_root",
            "wsl_distribution",
            "wsl_gid",
            "wsl_uid",
            "wsl_user",
        }
        and host.get("architecture") == "x86_64"
        and host.get("available_service_ports") == list(SERVICE_PORTS.values())
        and all(type(port) is int for port in host["available_service_ports"])
        and host.get("cached_execution_images") == 13
        and host.get("container_count") == 0
        and type(host.get("disk_available_bytes")) is int
        and host["disk_available_bytes"] >= MINIMUM_RUNNER_DISK_BYTES
        and host.get("minimum_disk_available_bytes") == MINIMUM_RUNNER_DISK_BYTES
        and host.get("os_id") == "ubuntu"
        and host.get("os_version_id") == "24.04"
        and type(host.get("python_toolcache_complete_bytes")) is int
        and host.get("python_toolcache_complete_bytes")
        == PYTHON_TOOLCACHE_COMPLETE_BYTES
        and host.get("python_toolcache_complete_path")
        == PYTHON_TOOLCACHE_COMPLETE_PATH
        and host.get("python_toolcache_complete_sha256")
        == PYTHON_TOOLCACHE_COMPLETE_SHA256
        and host.get("docker_client_bytes") == DOCKER_CLIENT_BYTES
        and type(host.get("docker_client_bytes")) is int
        and host.get("docker_client_path") == DOCKER_CLIENT_PATH
        and host.get("docker_client_sha256") == DOCKER_CLIENT_SHA256
        and host.get("docker_client_version") == DOCKER_VERSION
        and host.get("docker_create_pull_never_supported") is True
        and host.get("docker_root_directory") == DOCKER_ROOT_DIRECTORY
        and host.get("docker_server_version") == DOCKER_VERSION
        and host.get("exact_python_library_path") == EXACT_PYTHON_LIBRARY_PATH
        and host.get("exact_python_path") == f"{EXACT_PYTHON_ROOT}/bin/python"
        and host.get("exact_python_version") == "Python 3.11.10"
        and type(host.get("runner_listener_bytes")) is int
        and host.get("runner_listener_bytes") == RUNNER_LISTENER_BYTES
        and host.get("runner_listener_sha256") == RUNNER_LISTENER_SHA256
        and type(host.get("runner_package_archive_bytes")) is int
        and host.get("runner_package_archive_bytes") == RUNNER_PACKAGE_ARCHIVE_BYTES
        and host.get("runner_package_archive_path") == RUNNER_PACKAGE_ARCHIVE_PATH
        and host.get("runner_package_archive_sha256")
        == RUNNER_PACKAGE_ARCHIVE_SHA256
        and host.get("runner_package_version") == RUNNER_PACKAGE_VERSION
        and isinstance(host.get("service_image_ids"), Mapping)
        and set(host["service_image_ids"]) == set(SERVICE_IMAGE_REFS)
        and all(
            isinstance(image_id, str)
            and DOCKER_IMAGE_ID.fullmatch(image_id) is not None
            for image_id in host["service_image_ids"].values()
        )
        and type(host.get("service_images")) is int
        and host.get("service_images") == len(SERVICE_IMAGE_REFS)
        and host.get("forbidden_secret_names_present") == []
        and host.get("fresh_runner_roots") == list(RUNNER_ROOTS)
        and isinstance(host.get("listener_bindings"), list)
        and [row.get("root") for row in host["listener_bindings"]]
        == list(RUNNER_ROOTS)
        and all(
            isinstance(row, Mapping)
            and set(row) == {"ld_library_path", "pid", "root"}
            and row.get("ld_library_path") == EXACT_PYTHON_LIBRARY_PATH
            and type(row.get("pid")) is int
            and row["pid"] > 0
            for row in host["listener_bindings"]
        )
        and len({row["pid"] for row in host["listener_bindings"]})
        == len(RUNNER_ROOTS)
        and isinstance(host.get("local_runner_bindings"), list)
        and all(
            isinstance(row, Mapping)
            and row.get("disable_update") is True
            and row.get("ephemeral") is True
            and row.get("ld_library_path") == EXACT_PYTHON_LIBRARY_PATH
            and type(row.get("listener_bytes")) is int
            and row.get("listener_bytes") == RUNNER_LISTENER_BYTES
            and row.get("listener_sha256") == RUNNER_LISTENER_SHA256
            and row.get("listener_version") == RUNNER_PACKAGE_VERSION
            for row in host["local_runner_bindings"]
        )
        and host.get("local_runner_bindings")
        == [
            {
                "agent_id": row["id"],
                "agent_name": row["name"],
                "disable_update": True,
                "ephemeral": True,
                "ld_library_path": EXACT_PYTHON_LIBRARY_PATH,
                "listener_bytes": RUNNER_LISTENER_BYTES,
                "listener_sha256": RUNNER_LISTENER_SHA256,
                "listener_version": RUNNER_PACKAGE_VERSION,
                "root": RUNNER_ROOTS[index],
                "work_folder": "_work",
            }
            for index, row in enumerate(runners)
        ]
        and host.get("stale_runner_roots_absent") == list(STALE_RUNNER_ROOTS)
        and host.get("tool_cache_root") == RUNNER_TOOL_CACHE
        and host.get("wsl_distribution") == RUNNER_DISTRIBUTION
        and type(host.get("wsl_gid")) is int
        and host.get("wsl_gid") == RUNNER_SERVICE_GID
        and type(host.get("wsl_uid")) is int
        and host.get("wsl_uid") == RUNNER_SERVICE_UID
        and host.get("wsl_user") == RUNNER_WSL_USER,
        "self-hosted runner host readiness differs",
    )
    return deepcopy(dict(evidence))


def collect_runner_readiness(
    repository: Path,
    source_head: str,
    *,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Verify two clean WSL runners and all local prerequisites without pulls."""

    repository = resolve_repository_root(repository)
    wsl = shutil.which("wsl.exe")
    require(wsl is not None, "WSL is required for benchmark runner readiness")
    safe_environment = _safe_process_environment()
    observer_context = (
        _pinned_gh_context()
        if _observer_context is None
        else _observer_context
    )
    runners = _collect_remote_runner_rows(*observer_context)
    wsl_identity = _wsl_stdout(
        wsl,
        [
            "/bin/sh",
            "-c",
            "printf '%s:%s:%s\\n' \"$(/usr/bin/id -u)\" \"$(/usr/bin/id -g)\" \"$(/usr/bin/id -un)\"",
        ],
        safe_environment=safe_environment,
        label="explicit WSL runner user identity",
    )
    wsl_uid, wsl_gid, wsl_user = _validate_wsl_runner_identity(wsl_identity)
    architecture = _wsl_stdout(
        wsl, ["uname", "-m"], safe_environment=safe_environment, label="architecture"
    )
    _verify_wsl_file_lock(
        wsl,
        DOCKER_CLIENT_PATH,
        expected_bytes=DOCKER_CLIENT_BYTES,
        expected_sha256=DOCKER_CLIENT_SHA256,
        safe_environment=safe_environment,
        label="absolute Docker client",
    )
    require(
        _wsl_stdout(
            wsl,
            ["stat", "-c", "%U:%G %a", "--", DOCKER_CLIENT_PATH],
            safe_environment=safe_environment,
            label="absolute Docker client ownership and mode",
        )
        == "root:root 755",
        "absolute Docker client ownership or mode differs",
    )
    docker_client_version, docker_server_version = _validate_docker_version(_wsl_stdout(
        wsl,
        [*DOCKER_LOCAL_PREFIX, "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
        safe_environment=safe_environment,
        label="Docker daemon",
    ))
    docker_root_directory = _validate_docker_root_directory(
        _wsl_stdout(
            wsl,
            [*DOCKER_LOCAL_PREFIX, "info", "--format", "{{.DockerRootDir}}"],
            safe_environment=safe_environment,
            label="Docker root directory",
        )
    )
    docker_pull_never = _validate_docker_pull_never_help(
        _wsl_stdout(
            wsl,
            [*DOCKER_LOCAL_PREFIX, "create", "--help"],
            safe_environment=safe_environment,
            label="Docker cache-only create contract",
        )
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
        _wsl_exact_python_argv("--version"),
        safe_environment=safe_environment,
        label="exact Python 3.11.10",
    )
    _verify_wsl_file_lock(
        wsl,
        RUNNER_PACKAGE_ARCHIVE_PATH,
        expected_bytes=RUNNER_PACKAGE_ARCHIVE_BYTES,
        expected_sha256=RUNNER_PACKAGE_ARCHIVE_SHA256,
        safe_environment=safe_environment,
        label="cached Actions Runner archive",
    )
    _verify_wsl_file_lock(
        wsl,
        PYTHON_TOOLCACHE_COMPLETE_PATH,
        expected_bytes=PYTHON_TOOLCACHE_COMPLETE_BYTES,
        expected_sha256=PYTHON_TOOLCACHE_COMPLETE_SHA256,
        safe_environment=safe_environment,
        label="exact Python toolcache complete marker",
    )
    os_release = _validate_ubuntu_os_release(
        _run_readiness_command(
            [*_wsl_command_prefix(wsl), "cat", "/etc/os-release"],
            safe_environment=safe_environment,
            label="exact Ubuntu 24.04 release",
        )
    )
    container_text = _wsl_stdout(
        wsl,
        [*DOCKER_LOCAL_PREFIX, "ps", "-aq"],
        safe_environment=safe_environment,
        label="stale containers",
    )
    require(not container_text, "a stale benchmark or service container remains")
    port_probe = """\
import json
import socket

ports = [5432, 6333]
sockets = []
try:
    for port in ports:
        ipv4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sockets.append(ipv4)
        ipv4.bind(('127.0.0.1', port))
    print(json.dumps({'available_ports': ports}, sort_keys=True, separators=(',', ':')))
finally:
    for probe in sockets:
        probe.close()
"""
    port_document = strict_json(
        _run_readiness_command(
            [*_wsl_command_prefix(wsl), *_wsl_exact_python_argv("-I", "-S", "-c", port_probe)],
            safe_environment=safe_environment,
            label="free frozen service host ports",
        )
    )
    available_service_ports = port_document.get("available_ports")
    require(
        available_service_ports == list(SERVICE_PORTS.values())
        and all(type(port) is int for port in available_service_ports),
        "frozen service host ports are not free and bindable",
    )
    listener_probe = """\
import json
import os
from pathlib import Path
import sys

names = set(json.loads(sys.argv[1]))
roots = set(json.loads(sys.argv[2]))
expected_library_path = sys.argv[3]
if names.intersection(os.environ) or any(name.upper().startswith('DOCKER_') for name in os.environ):
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
    if names.intersection(keys) or any(name.upper().startswith('DOCKER_') for name in keys):
        raise SystemExit(42)
    library_entries = [
        item.decode('utf-8', errors='strict')
        for item in environment
        if item and item.split(b'=', 1)[0] == b'LD_LIBRARY_PATH'
    ]
    if library_entries != ['LD_LIBRARY_PATH=' + expected_library_path]:
        raise SystemExit(46)
    listeners.append({
        'ld_library_path': expected_library_path,
        'pid': int(proc.name),
        'root': os.readlink(proc / 'cwd'),
    })
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
                *_wsl_command_prefix(wsl),
                *_wsl_exact_python_argv(
                    "-I",
                    "-S",
                    "-c",
                    listener_probe,
                    json.dumps(sorted(FORBIDDEN_PREFLIGHT_SECRETS)),
                    json.dumps(list(RUNNER_ROOTS)),
                    EXACT_PYTHON_LIBRARY_PATH,
                ),
            ],
            safe_environment=safe_environment,
            label="runner listener identity and secret-name absence",
        )
    )
    listener_bindings = listener_document.get("listeners")
    require(
        isinstance(listener_bindings, list)
        and len(listener_bindings) == len(RUNNER_ROOTS)
        and all(
            isinstance(row, Mapping)
            and set(row) == {"ld_library_path", "pid", "root"}
            and row.get("ld_library_path") == EXACT_PYTHON_LIBRARY_PATH
            for row in listener_bindings
        )
        and [row.get("root") for row in listener_bindings]
        == list(RUNNER_ROOTS),
        "runner listener roots differ",
    )
    for root in STALE_RUNNER_ROOTS:
        completed = subprocess.run(
            [
                *_wsl_command_prefix(wsl),
                "sh",
                "-c",
                'test ! -e "$1" && test ! -L "$1"',
                "trimem-stale-root",
                root,
            ],
            capture_output=True,
            check=False,
            env=dict(safe_environment),
        )
        require(completed.returncode == 0, f"stale runner workspace remains: {root}")
    remote_by_name = {str(row["name"]): row for row in runners}
    local_bindings: list[dict[str, Any]] = []
    for index, root in enumerate(RUNNER_ROOTS):
        expected_name = RUNNER_NAMES[index]
        direct_root = _wsl_stdout(
            wsl,
            [
                "sh",
                "-c",
                'test -d "$1" && test ! -L "$1" && readlink -f -- "$1"',
                "trimem-runner-root",
                root,
            ],
            safe_environment=safe_environment,
            label=f"direct runner root {root}",
        )
        require(direct_root == root, f"runner root is missing or indirect: {root}")
        for relative in (".env", ".runner", "bin/Runner.Listener", "run.sh"):
            _run_readiness_command(
                [
                    *_wsl_command_prefix(wsl),
                    "test",
                    "-f",
                    f"{root}/{relative}",
                ],
                safe_environment=safe_environment,
                label=f"fresh runner file {root}/{relative}",
            )
        listener_path = f"{root}/bin/Runner.Listener"
        _verify_wsl_file_lock(
            wsl,
            listener_path,
            expected_bytes=RUNNER_LISTENER_BYTES,
            expected_sha256=RUNNER_LISTENER_SHA256,
            safe_environment=safe_environment,
            label=f"runner listener {root}",
        )
        listener_version = _wsl_stdout(
            wsl,
            [listener_path, "--version"],
            safe_environment=safe_environment,
            label=f"runner listener version {root}",
            cwd=root,
        )
        require(
            listener_version == RUNNER_PACKAGE_VERSION,
            f"runner listener version differs: {root}",
        )
        _run_readiness_command(
            [
                *_wsl_command_prefix(wsl),
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
forbidden_names = set(json.loads(sys.argv[2]))
expected_library_path = sys.argv[3]
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
try:
    env_text = (root / '.env').read_bytes().decode('utf-8', errors='strict')
except (FileNotFoundError, UnicodeDecodeError):
    raise SystemExit(47)
bindings = {}
for line in env_text.splitlines():
    if not line or '=' not in line:
        raise SystemExit(48)
    if any(ord(character) < 32 or ord(character) == 127 for character in line):
        raise SystemExit(48)
    name, value = line.split('=', 1)
    valid_name = (
        bool(name)
        and (name[0] == '_' or 'A' <= name[0] <= 'Z' or 'a' <= name[0] <= 'z')
        and all(
            character == '_'
            or 'A' <= character <= 'Z'
            or 'a' <= character <= 'z'
            or '0' <= character <= '9'
            for character in name[1:]
        )
    )
    if not valid_name or name in bindings:
        raise SystemExit(49)
    bindings[name] = value
if forbidden_names.intersection(bindings) or any(name.upper().startswith('DOCKER_') for name in bindings):
    raise SystemExit(44)
if bindings.get('LD_LIBRARY_PATH') != expected_library_path:
    raise SystemExit(46)
path_file = root / '.path'
if path_file.exists():
    forbidden_prefixes = [name.encode('ascii') + b'=' for name in forbidden_names]
    if any(
        line.startswith(prefix)
        for line in path_file.read_bytes().splitlines()
        for prefix in forbidden_prefixes
    ) or any(
        line.split(b'=', 1)[0].decode('utf-8', errors='strict').upper().startswith('DOCKER_')
        for line in path_file.read_bytes().splitlines()
        if line
    ):
        raise SystemExit(44)
selected = {
    'agentId': config.get('agentId'),
    'agentName': config.get('agentName'),
    'disableUpdate': config.get('disableUpdate'),
    'ephemeral': config.get('ephemeral'),
    'gitHubUrl': config.get('gitHubUrl'),
    'ld_library_path': expected_library_path,
    'workFolder': config.get('workFolder'),
}
print(json.dumps(selected, sort_keys=True, separators=(',', ':')))
"""
        local_config = strict_json(
            _run_readiness_command(
                [
                    *_wsl_command_prefix(wsl),
                    *_wsl_exact_python_argv(
                        "-I",
                        "-S",
                        "-c",
                        local_config_probe,
                        root,
                        json.dumps(sorted(FORBIDDEN_PREFLIGHT_SECRETS)),
                        EXACT_PYTHON_LIBRARY_PATH,
                    ),
                ],
                safe_environment=safe_environment,
                label=f"runner identity and config secret-name absence {root}",
            )
        )
        remote = remote_by_name[expected_name]
        require(
            local_config.get("agentId") == remote["id"]
            and local_config.get("agentName") == expected_name
            and local_config.get("disableUpdate") is True
            and local_config.get("ephemeral") is True
            and local_config.get("gitHubUrl")
            == "https://github.com/Scuttie/enterprise-shared-memory-poc"
            and local_config.get("ld_library_path")
            == EXACT_PYTHON_LIBRARY_PATH
            and local_config.get("workFolder") == "_work",
            f"local runner identity differs from GitHub registration: {root}",
        )
        local_bindings.append(
            {
                "agent_id": remote["id"],
                "agent_name": expected_name,
                "disable_update": True,
                "ephemeral": True,
                "ld_library_path": EXACT_PYTHON_LIBRARY_PATH,
                "listener_bytes": RUNNER_LISTENER_BYTES,
                "listener_sha256": RUNNER_LISTENER_SHA256,
                "listener_version": listener_version,
                "root": root,
                "work_folder": "_work",
            }
        )
    images = _expected_execution_images(repository, source_head)
    for locked_image in images:
        _run_readiness_command(
            [
                *_wsl_command_prefix(wsl),
                *DOCKER_LOCAL_PREFIX,
                "image",
                "inspect",
                locked_image,
            ],
            safe_environment=safe_environment,
            label=f"cached image {locked_image}",
        )
    service_images = _expected_service_images(repository, source_head)
    service_image_ids: dict[str, str] = {}
    for role, locked_image in service_images.items():
        image_id = _wsl_stdout(
            wsl,
            [*DOCKER_LOCAL_PREFIX, "image", "inspect", "--format", "{{.Id}}", locked_image],
            safe_environment=safe_environment,
            label=f"cached {role} service image {locked_image}",
        )
        require(
            DOCKER_IMAGE_ID.fullmatch(image_id) is not None,
            f"cached {role} service image ID is malformed",
        )
        service_image_ids[role] = image_id
    evidence = {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "host": {
            "architecture": architecture,
            "available_service_ports": available_service_ports,
            "cached_execution_images": len(images),
            "container_count": 0,
            "disk_available_bytes": disk_available,
            "docker_client_bytes": DOCKER_CLIENT_BYTES,
            "docker_client_path": DOCKER_CLIENT_PATH,
            "docker_client_sha256": DOCKER_CLIENT_SHA256,
            "docker_client_version": docker_client_version,
            "docker_create_pull_never_supported": docker_pull_never,
            "docker_root_directory": docker_root_directory,
            "docker_server_version": docker_server_version,
            "exact_python_library_path": EXACT_PYTHON_LIBRARY_PATH,
            "exact_python_path": f"{EXACT_PYTHON_ROOT}/bin/python",
            "exact_python_version": python_version,
            "forbidden_secret_names_present": [],
            "fresh_runner_roots": list(RUNNER_ROOTS),
            "listener_bindings": listener_bindings,
            "local_runner_bindings": local_bindings,
            "minimum_disk_available_bytes": MINIMUM_RUNNER_DISK_BYTES,
            **os_release,
            "python_toolcache_complete_bytes": PYTHON_TOOLCACHE_COMPLETE_BYTES,
            "python_toolcache_complete_path": PYTHON_TOOLCACHE_COMPLETE_PATH,
            "python_toolcache_complete_sha256": PYTHON_TOOLCACHE_COMPLETE_SHA256,
            "runner_listener_bytes": RUNNER_LISTENER_BYTES,
            "runner_listener_sha256": RUNNER_LISTENER_SHA256,
            "runner_package_archive_bytes": RUNNER_PACKAGE_ARCHIVE_BYTES,
            "runner_package_archive_path": RUNNER_PACKAGE_ARCHIVE_PATH,
            "runner_package_archive_sha256": RUNNER_PACKAGE_ARCHIVE_SHA256,
            "runner_package_version": RUNNER_PACKAGE_VERSION,
            "service_image_ids": service_image_ids,
            "service_images": len(service_images),
            "stale_runner_roots_absent": list(STALE_RUNNER_ROOTS),
            "tool_cache_root": RUNNER_TOOL_CACHE,
            "wsl_distribution": RUNNER_DISTRIBUTION,
            "wsl_gid": wsl_gid,
            "wsl_uid": wsl_uid,
            "wsl_user": wsl_user,
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
    argv: Sequence[str],
    *,
    safe_environment: Mapping[str, str],
    label: str,
    cwd: Path | str | None = None,
    timeout: float = 60,
) -> str:
    raw = _run_readiness_command(
        argv,
        safe_environment=safe_environment,
        label=label,
        cwd=cwd,
        timeout=timeout,
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

    repository = resolve_repository_root(repository)
    environment = os.environ if environ is None else environ
    _validate_secret_free_branch_environment(environment)
    _require_exact_python_library_binding(
        environment, label="bounded-context preflight process environment"
    )
    safe_environment = _safe_environment(environment)
    expected = _validate_runner_readiness(
        expected_readiness, source_head=source_head
    )
    require(os.name == "posix" and hasattr(os, "uname"), "runner host is not POSIX")
    runner_uid, runner_gid, runner_user = _observe_local_runner_identity()
    architecture = os.uname().machine
    os_release = _validate_ubuntu_os_release(Path("/etc/os-release").read_bytes())
    require(
        tuple(sys.version_info[:3]) == (3, 11, 10),
        "runner host Python version differs",
    )
    expected_python = Path(f"{EXACT_PYTHON_ROOT}/bin/python").resolve(strict=True)
    observed_python = Path(sys.executable).resolve(strict=True)
    require(observed_python == expected_python, "runner host Python path differs")
    _verify_local_file_lock(
        Path(RUNNER_PACKAGE_ARCHIVE_PATH),
        expected_bytes=RUNNER_PACKAGE_ARCHIVE_BYTES,
        expected_sha256=RUNNER_PACKAGE_ARCHIVE_SHA256,
        label="cached Actions Runner archive",
    )
    _verify_local_file_lock(
        Path(PYTHON_TOOLCACHE_COMPLETE_PATH),
        expected_bytes=PYTHON_TOOLCACHE_COMPLETE_BYTES,
        expected_sha256=PYTHON_TOOLCACHE_COMPLETE_SHA256,
        label="exact Python toolcache complete marker",
    )

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
            process_environment_raw = (proc / "environ").read_bytes()
            cwd = os.readlink(proc / "cwd")
        except FileNotFoundError:
            continue
        process_environment = _strict_environment_bindings(
            process_environment_raw,
            separator=b"\0",
            label=f"Runner.Listener pid {proc.name}",
        )
        require(
            not _forbidden_environment_names(process_environment),
            "runner listener exposes a protected benchmark secret name",
        )
        listeners.append(
            {
                "ld_library_path": _require_exact_python_library_binding(
                    process_environment,
                    label=f"Runner.Listener pid {proc.name}",
                ),
                "pid": int(proc.name),
                "root": cwd,
            }
        )
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
        require(
            root_path.is_dir()
            and not root_path.is_symlink()
            and root_path.resolve(strict=True) == root_path,
            f"fresh runner root is missing or indirect: {root}",
        )
        for relative in (".env", ".runner", "bin/Runner.Listener", "run.sh"):
            require(
                (root_path / relative).is_file(),
                f"fresh runner file is missing: {root}/{relative}",
            )
        listener_path = root_path / "bin" / "Runner.Listener"
        _verify_local_file_lock(
            listener_path,
            expected_bytes=RUNNER_LISTENER_BYTES,
            expected_sha256=RUNNER_LISTENER_SHA256,
            label=f"runner listener {root}",
        )
        listener_version = _local_stdout(
            [str(listener_path), "--version"],
            safe_environment=safe_environment,
            label=f"runner listener version {root}",
            cwd=root_path,
        )
        require(
            listener_version == RUNNER_PACKAGE_VERSION,
            f"runner listener version differs: {root}",
        )
        require(
            (root_path / "_work" / "_tool").resolve(strict=True)
            == Path(RUNNER_TOOL_CACHE).resolve(strict=True),
            "runner tool cache differs",
        )
        config = strict_runner_config_json((root_path / ".runner").read_bytes())
        env_bindings = _strict_environment_bindings(
            (root_path / ".env").read_bytes(),
            separator=b"\n",
            label=f"{root}/.env",
        )
        require(
            not _forbidden_environment_names(env_bindings),
            f"runner config exposes a protected secret name: {root}/.env",
        )
        library_path = _require_exact_python_library_binding(
            env_bindings, label=f"{root}/.env"
        )
        path_file = root_path / ".path"
        if path_file.exists():
            names = {
                line.split(b"=", 1)[0].decode("utf-8", errors="strict")
                for line in path_file.read_bytes().splitlines()
                if line
            }
            require(
                not any(_is_forbidden_environment_name(name) for name in names),
                f"runner config exposes a protected secret name: {root}/.path",
            )
        remote = expected_runners[index]
        require(
            config.get("agentId") == remote["id"]
            and config.get("agentName") == remote["name"]
            and config.get("disableUpdate") is True
            and config.get("ephemeral") is True
            and config.get("gitHubUrl")
            == "https://github.com/Scuttie/enterprise-shared-memory-poc"
            and config.get("workFolder") == "_work",
            f"live local runner identity differs: {root}",
        )
        local_bindings.append(
            {
                "agent_id": remote["id"],
                "agent_name": remote["name"],
                "disable_update": True,
                "ephemeral": True,
                "ld_library_path": library_path,
                "listener_bytes": RUNNER_LISTENER_BYTES,
                "listener_sha256": RUNNER_LISTENER_SHA256,
                "listener_version": listener_version,
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
        require(not os.path.lexists(root), f"stale runner workspace remains: {root}")
    _verify_local_docker_client()
    docker_client_version, docker_server_version = _validate_docker_version(_local_stdout(
        [*DOCKER_LOCAL_PREFIX, "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
        safe_environment=safe_environment,
        label="live Docker daemon",
    ))
    docker_root_directory = _validate_docker_root_directory(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "info", "--format", "{{.DockerRootDir}}"],
            safe_environment=safe_environment,
            label="live Docker root directory",
        )
    )
    docker_pull_never = _validate_docker_pull_never_help(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "create", "--help"],
            safe_environment=safe_environment,
            label="live Docker cache-only create contract",
        )
    )
    container_ids = _local_stdout(
        [*DOCKER_LOCAL_PREFIX, "ps", "-aq"],
        safe_environment=safe_environment,
        label="live stale containers",
    )
    require(not container_ids, "a stale benchmark or service container remains")
    available_service_ports = _probe_local_service_ports_available()
    disk_available = shutil.disk_usage("/opt").free
    require(
        disk_available >= MINIMUM_RUNNER_DISK_BYTES,
        "live runner disk availability is below the frozen minimum",
    )
    images = _expected_execution_images(repository, source_head)
    for locked_image in images:
        _run_readiness_command(
            [*DOCKER_LOCAL_PREFIX, "image", "inspect", locked_image],
            safe_environment=safe_environment,
            label=f"live cached image {locked_image}",
        )
    service_images = _expected_service_images(repository, source_head)
    service_image_ids: dict[str, str] = {}
    for role, locked_image in service_images.items():
        image_id = _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "image", "inspect", "--format", "{{.Id}}", locked_image],
            safe_environment=safe_environment,
            label=f"live cached {role} service image {locked_image}",
        )
        require(
            DOCKER_IMAGE_ID.fullmatch(image_id) is not None,
            f"live cached {role} service image ID is malformed",
        )
        service_image_ids[role] = image_id

    live_host = {
        "architecture": architecture,
        "available_service_ports": available_service_ports,
        "cached_execution_images": len(images),
        "container_count": 0,
        "disk_available_bytes": disk_available,
        "docker_client_bytes": DOCKER_CLIENT_BYTES,
        "docker_client_path": DOCKER_CLIENT_PATH,
        "docker_client_sha256": DOCKER_CLIENT_SHA256,
        "docker_client_version": docker_client_version,
        "docker_create_pull_never_supported": docker_pull_never,
        "docker_root_directory": docker_root_directory,
        "docker_server_version": docker_server_version,
        "exact_python_library_path": EXACT_PYTHON_LIBRARY_PATH,
        "exact_python_path": f"{EXACT_PYTHON_ROOT}/bin/python",
        "exact_python_version": "Python 3.11.10",
        "forbidden_secret_names_present": [],
        "fresh_runner_roots": list(RUNNER_ROOTS),
        "listener_bindings": listeners,
        "local_runner_bindings": local_bindings,
        "minimum_disk_available_bytes": MINIMUM_RUNNER_DISK_BYTES,
        **os_release,
        "python_toolcache_complete_bytes": PYTHON_TOOLCACHE_COMPLETE_BYTES,
        "python_toolcache_complete_path": PYTHON_TOOLCACHE_COMPLETE_PATH,
        "python_toolcache_complete_sha256": PYTHON_TOOLCACHE_COMPLETE_SHA256,
        "runner_listener_bytes": RUNNER_LISTENER_BYTES,
        "runner_listener_sha256": RUNNER_LISTENER_SHA256,
        "runner_package_archive_bytes": RUNNER_PACKAGE_ARCHIVE_BYTES,
        "runner_package_archive_path": RUNNER_PACKAGE_ARCHIVE_PATH,
        "runner_package_archive_sha256": RUNNER_PACKAGE_ARCHIVE_SHA256,
        "runner_package_version": RUNNER_PACKAGE_VERSION,
        "service_image_ids": service_image_ids,
        "service_images": len(service_images),
        "stale_runner_roots_absent": list(STALE_RUNNER_ROOTS),
        "tool_cache_root": RUNNER_TOOL_CACHE,
        "wsl_distribution": RUNNER_DISTRIBUTION,
        "wsl_gid": runner_gid,
        "wsl_uid": runner_uid,
        "wsl_user": runner_user,
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

    repository = resolve_repository_root(repository)
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


def validate_pre_setup_cache_host(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prove the complete cached Python before setup-python can download."""

    repository = resolve_repository_root(repository)
    environment = os.environ if environ is None else environ
    _validate_secret_free_branch_environment(environment)
    _require_exact_python_library_binding(
        environment, label="pre-setup cache-host process environment"
    )
    _observe_local_runner_identity()
    job = environment.get("GITHUB_JOB")
    require(
        job in {"bounded-context-preflight", "frozen-serial-phase"},
        "pre-setup cache-host probe is outside a self-hosted job",
    )
    require(
        environment.get("GITHUB_EVENT_NAME") == "push"
        and environment.get("GITHUB_RUN_ATTEMPT") == "1"
        and environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY
        and environment.get("GITHUB_REF") == EXPECTED_REF
        and environment.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF
        and environment.get("RUNNER_OS") == "Linux"
        and environment.get("RUNNER_ARCH") == "X64",
        "pre-setup cache-host runtime identity differs",
    )
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
        and HEX40.fullmatch(after) is not None
        and environment.get("GITHUB_SHA") == after
        and environment.get("GITHUB_WORKFLOW_SHA") == after,
        "pre-setup cache-host event identity differs",
    )
    run_id = environment.get("GITHUB_RUN_ID", "")
    require(run_id.isascii() and run_id.isdigit() and int(run_id) > 0, "run ID differs")
    request = validate_sentinel_commit(
        repository, after, expected_parent=before, require_checked_out_head=True
    )
    readiness = _validate_runner_readiness(
        request.get("runner_readiness"), source_head=before
    )
    if job == "bounded-context-preflight":
        _validate_runner_readiness_freshness(readiness, now=now)
    workspace = Path(str(environment.get("GITHUB_WORKSPACE", ""))).resolve(strict=True)
    matching = []
    for index, root_value in enumerate(RUNNER_ROOTS):
        root = Path(root_value)
        require(
            root.is_dir()
            and not root.is_symlink()
            and root.resolve(strict=True) == root,
            f"pre-setup runner root is missing or indirect: {root_value}",
        )
        if workspace.is_relative_to(root):
            matching.append(index)
    require(
        len(matching) == 1
        and environment.get("RUNNER_NAME") == RUNNER_NAMES[matching[0]],
        "pre-setup runner name/root mapping differs",
    )
    _require_pre_setup_runner_tool_cache_binding(
        environment,
        active_root=RUNNER_ROOTS[matching[0]],
        label=f"pre-setup {job}",
    )
    require(
        tuple(sys.version_info[:3]) == (3, 11, 10)
        and Path(sys.executable).resolve(strict=True)
        == Path(f"{EXACT_PYTHON_ROOT}/bin/python").resolve(strict=True),
        "pre-setup exact Python differs",
    )
    _verify_local_file_lock(
        Path(PYTHON_TOOLCACHE_COMPLETE_PATH),
        expected_bytes=PYTHON_TOOLCACHE_COMPLETE_BYTES,
        expected_sha256=PYTHON_TOOLCACHE_COMPLETE_SHA256,
        label="pre-setup exact Python toolcache complete marker",
    )
    return {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "execution_run_attempt": 1,
        "execution_run_id": int(run_id),
        "request_id": REQUEST_ID,
        "source_head": before,
        "status": "PASS",
        "trigger_commit": after,
    }


def _validate_service_container_id(value: Any, *, role: str) -> str:
    require(
        isinstance(value, str) and HEX64.fullmatch(value) is not None,
        f"{role} service container ID differs",
    )
    return value


def _validate_protected_runner_readiness(
    evidence: Any,
    *,
    source_head: str,
    trigger_head: str,
    run_id: int,
    expected_readiness: Mapping[str, Any],
    execution_images: Sequence[str],
    service_images: Mapping[str, str],
) -> dict[str, Any]:
    """Validate the secret-free observation made inside the protected job."""

    expected = _validate_runner_readiness(
        expected_readiness, source_head=source_head
    )
    require(isinstance(evidence, Mapping), "protected runner evidence is missing")
    require(
        set(evidence)
        == {
            "activation_actuals",
            "architecture",
            "available_service_ports",
            "cached_execution_image_ids",
            "container_count",
            "current_runner_binding",
            "disk_available_bytes",
            "docker_client_bytes",
            "docker_client_path",
            "docker_client_sha256",
            "docker_client_version",
            "docker_create_pull_never_supported",
            "docker_root_directory",
            "docker_server_version",
            "exact_python_library_path",
            "exact_python_path",
            "exact_python_version",
            "execution_run_attempt",
            "execution_run_id",
            "forbidden_secret_names_present",
            "listener_binding",
            "minimum_disk_available_bytes",
            "observed_at_utc",
            "os_id",
            "os_version_id",
            "python_toolcache_complete_bytes",
            "python_toolcache_complete_path",
            "python_toolcache_complete_sha256",
            "repository",
            "runner_listener_bytes",
            "runner_listener_sha256",
            "runner_package_archive_bytes",
            "runner_package_archive_path",
            "runner_package_archive_sha256",
            "runner_package_version",
            "runner_gid",
            "runner_uid",
            "runner_user",
            "service_image_ids",
            "source_head",
            "stale_runner_roots_absent",
            "status",
            "teardown_listener_binding",
            "tool_cache_root",
            "trigger_head",
        },
        "protected runner evidence field set differs",
    )
    require(
        evidence.get("activation_actuals") == ACTIVATION_ZERO_COUNTERS
        and evidence.get("architecture") == "x86_64"
        and evidence.get("available_service_ports") == list(SERVICE_PORTS.values())
        and all(type(port) is int for port in evidence["available_service_ports"])
        and evidence.get("container_count") == 0
        and type(evidence.get("disk_available_bytes")) is int
        and evidence["disk_available_bytes"] >= MINIMUM_RUNNER_DISK_BYTES
        and type(evidence.get("docker_client_bytes")) is int
        and evidence.get("docker_client_bytes") == DOCKER_CLIENT_BYTES
        and evidence.get("docker_client_path") == DOCKER_CLIENT_PATH
        and evidence.get("docker_client_sha256") == DOCKER_CLIENT_SHA256
        and evidence.get("docker_client_version") == DOCKER_VERSION
        and evidence.get("docker_create_pull_never_supported") is True
        and evidence.get("docker_root_directory") == DOCKER_ROOT_DIRECTORY
        and evidence.get("docker_server_version") == DOCKER_VERSION
        and evidence.get("exact_python_library_path") == EXACT_PYTHON_LIBRARY_PATH
        and evidence.get("exact_python_path") == f"{EXACT_PYTHON_ROOT}/bin/python"
        and evidence.get("exact_python_version") == "Python 3.11.10"
        and evidence.get("execution_run_attempt") == 1
        and type(evidence.get("execution_run_attempt")) is int
        and evidence.get("execution_run_id") == run_id
        and type(evidence.get("execution_run_id")) is int
        and evidence.get("forbidden_secret_names_present") == []
        and evidence.get("minimum_disk_available_bytes")
        == MINIMUM_RUNNER_DISK_BYTES
        and _utc_timestamp(evidence.get("observed_at_utc"))
        and evidence.get("os_id") == "ubuntu"
        and evidence.get("os_version_id") == "24.04"
        and type(evidence.get("python_toolcache_complete_bytes")) is int
        and evidence.get("python_toolcache_complete_bytes")
        == PYTHON_TOOLCACHE_COMPLETE_BYTES
        and evidence.get("python_toolcache_complete_path")
        == PYTHON_TOOLCACHE_COMPLETE_PATH
        and evidence.get("python_toolcache_complete_sha256")
        == PYTHON_TOOLCACHE_COMPLETE_SHA256
        and evidence.get("repository") == EXPECTED_REPOSITORY
        and type(evidence.get("runner_listener_bytes")) is int
        and evidence.get("runner_listener_bytes") == RUNNER_LISTENER_BYTES
        and evidence.get("runner_listener_sha256") == RUNNER_LISTENER_SHA256
        and type(evidence.get("runner_package_archive_bytes")) is int
        and evidence.get("runner_package_archive_bytes")
        == RUNNER_PACKAGE_ARCHIVE_BYTES
        and evidence.get("runner_package_archive_path")
        == RUNNER_PACKAGE_ARCHIVE_PATH
        and evidence.get("runner_package_archive_sha256")
        == RUNNER_PACKAGE_ARCHIVE_SHA256
        and evidence.get("runner_package_version") == RUNNER_PACKAGE_VERSION
        and type(evidence.get("runner_gid")) is int
        and evidence.get("runner_gid") == RUNNER_SERVICE_GID
        and type(evidence.get("runner_uid")) is int
        and evidence.get("runner_uid") == RUNNER_SERVICE_UID
        and evidence.get("runner_user") == RUNNER_WSL_USER
        and evidence.get("source_head") == source_head
        and evidence.get("stale_runner_roots_absent") == list(STALE_RUNNER_ROOTS)
        and evidence.get("status") == "PASS"
        and evidence.get("tool_cache_root") == RUNNER_TOOL_CACHE
        and evidence.get("trigger_head") == trigger_head,
        "protected runner identity or host facts differ",
    )
    binding = evidence.get("current_runner_binding")
    require(
        isinstance(binding, Mapping)
        and binding.get("agent_name") in RUNNER_NAMES,
        "protected current runner binding differs",
    )
    active_index = RUNNER_NAMES.index(str(binding["agent_name"]))
    expected_remote = expected["runners"][active_index]
    expected_binding = {
        "agent_id": expected_remote["id"],
        "agent_name": RUNNER_NAMES[active_index],
        "disable_update": True,
        "ephemeral": True,
        "ld_library_path": EXACT_PYTHON_LIBRARY_PATH,
        "listener_bytes": RUNNER_LISTENER_BYTES,
        "listener_sha256": RUNNER_LISTENER_SHA256,
        "listener_version": RUNNER_PACKAGE_VERSION,
        "root": RUNNER_ROOTS[active_index],
        "work_folder": "_work",
    }
    require(
        isinstance(binding, Mapping)
        and binding.get("disable_update") is True
        and binding.get("ephemeral") is True
        and dict(binding) == expected_binding,
        "protected current runner binding differs",
    )
    listener = evidence.get("listener_binding")
    require(
        isinstance(listener, Mapping)
        and set(listener) == {"ld_library_path", "pid", "root"}
        and listener.get("ld_library_path") == EXACT_PYTHON_LIBRARY_PATH
        and type(listener.get("pid")) is int
        and listener["pid"] > 0
        and listener.get("root") == RUNNER_ROOTS[active_index],
        "protected live listener binding differs",
    )
    teardown = evidence.get("teardown_listener_binding")
    inactive_root = RUNNER_ROOTS[1 - active_index]
    require(
        teardown is None
        or (
            isinstance(teardown, Mapping)
            and set(teardown) == {"ld_library_path", "pid", "root"}
            and teardown.get("ld_library_path") == EXACT_PYTHON_LIBRARY_PATH
            and type(teardown.get("pid")) is int
            and teardown["pid"] > 0
            and teardown.get("root") == inactive_root
            and teardown.get("pid") != listener.get("pid")
        ),
        "protected teardown listener binding differs",
    )
    cached = evidence.get("cached_execution_image_ids")
    require(
        isinstance(cached, Mapping)
        and set(cached) == set(execution_images)
        and len(cached) == 13
        and all(
            isinstance(image_id, str)
            and DOCKER_IMAGE_ID.fullmatch(image_id) is not None
            for image_id in cached.values()
        ),
        "protected cached DEV image observations differ",
    )
    service_image_ids = evidence.get("service_image_ids")
    require(
        isinstance(service_image_ids, Mapping)
        and set(service_image_ids) == set(SERVICE_IMAGE_REFS)
        and dict(service_image_ids) == expected["host"]["service_image_ids"]
        and all(
            isinstance(service_image_ids.get(role), str)
            and DOCKER_IMAGE_ID.fullmatch(str(service_image_ids[role])) is not None
            for role in SERVICE_IMAGE_REFS
        ),
        "protected service image observations differ",
    )
    require(dict(service_images) == SERVICE_IMAGE_REFS, "protected service locks differ")
    return deepcopy(dict(evidence))


def _mapped_host_port(container: Mapping[str, Any], *, role: str) -> int:
    network = container.get("NetworkSettings")
    ports = network.get("Ports") if isinstance(network, Mapping) else None
    expected_key = f"{SERVICE_PORTS[role]}/tcp"
    require(isinstance(ports, Mapping), f"{role} service port map is malformed")
    mapped = {key: value for key, value in ports.items() if value is not None}
    require(
        set(mapped) == {expected_key} and isinstance(mapped[expected_key], list),
        f"{role} service port map differs",
    )
    bindings = mapped[expected_key]
    require(
        len(bindings) == 1
        and all(
            isinstance(row, Mapping)
            and set(row) == {"HostIp", "HostPort"}
            and row.get("HostIp") == "127.0.0.1"
            and row.get("HostPort") == str(SERVICE_PORTS[role])
            for row in bindings
        ),
        f"{role} service host port binding differs",
    )
    return SERVICE_PORTS[role]


def collect_protected_runner_readiness(
    repository: Path,
    source_head: str,
    trigger_head: str,
    run_id: int,
    expected_readiness: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Observe the remaining runner and two already-created job services."""

    repository = resolve_repository_root(repository)
    environment = os.environ if environ is None else environ
    _validate_secret_free_branch_environment(environment)
    _require_exact_python_library_binding(
        environment, label="protected preflight process environment"
    )
    safe_environment = _safe_environment(environment)
    expected = _validate_runner_readiness(
        expected_readiness, source_head=source_head
    )
    require(os.name == "posix" and hasattr(os, "uname"), "runner host is not POSIX")
    runner_uid, runner_gid, runner_user = _observe_local_runner_identity()
    architecture = os.uname().machine
    os_release = _validate_ubuntu_os_release(Path("/etc/os-release").read_bytes())
    require(tuple(sys.version_info[:3]) == (3, 11, 10), "runner host Python version differs")
    exact_python = Path(f"{EXACT_PYTHON_ROOT}/bin/python").resolve(strict=True)
    require(Path(sys.executable).resolve(strict=True) == exact_python, "runner host Python path differs")
    require(
        Path(str(environment.get("pythonLocation", ""))).resolve(strict=True)
        == Path(EXACT_PYTHON_ROOT).resolve(strict=True),
        "setup-python location differs",
    )
    require(
        Path(str(environment.get("RUNNER_TOOL_CACHE", ""))).resolve(strict=True)
        == Path(RUNNER_TOOL_CACHE).resolve(strict=True),
        "runner tool cache environment differs",
    )
    _verify_local_file_lock(
        Path(RUNNER_PACKAGE_ARCHIVE_PATH),
        expected_bytes=RUNNER_PACKAGE_ARCHIVE_BYTES,
        expected_sha256=RUNNER_PACKAGE_ARCHIVE_SHA256,
        label="cached Actions Runner archive",
    )
    _verify_local_file_lock(
        Path(PYTHON_TOOLCACHE_COMPLETE_PATH),
        expected_bytes=PYTHON_TOOLCACHE_COMPLETE_BYTES,
        expected_sha256=PYTHON_TOOLCACHE_COMPLETE_SHA256,
        label="protected exact Python toolcache complete marker",
    )
    workspace = Path(str(environment.get("GITHUB_WORKSPACE", ""))).resolve(strict=True)
    for root_value in RUNNER_ROOTS:
        root_path = Path(root_value)
        require(
            root_path.is_dir()
            and not root_path.is_symlink()
            and root_path.resolve(strict=True) == root_path,
            f"protected runner root is missing or indirect: {root_value}",
        )
    matching_roots = [
        index
        for index, root_value in enumerate(RUNNER_ROOTS)
        if workspace.is_relative_to(Path(root_value).resolve(strict=True))
    ]
    require(
        len(matching_roots) == 1
        and environment.get("RUNNER_NAME") == RUNNER_NAMES[matching_roots[0]],
        "protected runner name, root, or workspace differs",
    )
    active_index = matching_roots[0]
    root = Path(RUNNER_ROOTS[active_index])
    for relative in (".env", ".runner", "bin/Runner.Listener", "run.sh"):
        selected = root / relative
        require(
            selected.is_file()
            and not selected.is_symlink()
            and selected.resolve(strict=True) == selected,
            f"protected runner file is missing or indirect: {selected}",
        )
    listener_path = root / "bin" / "Runner.Listener"
    _verify_local_file_lock(
        listener_path,
        expected_bytes=RUNNER_LISTENER_BYTES,
        expected_sha256=RUNNER_LISTENER_SHA256,
        label="protected runner listener",
    )
    listener_version = _local_stdout(
        [str(listener_path), "--version"],
        safe_environment=safe_environment,
        label="protected runner listener version",
        cwd=root,
    )
    require(listener_version == RUNNER_PACKAGE_VERSION, "protected runner listener version differs")
    require(
        (root / "_work" / "_tool").resolve(strict=True)
        == Path(RUNNER_TOOL_CACHE).resolve(strict=True),
        "protected runner tool cache differs",
    )
    config = strict_runner_config_json((root / ".runner").read_bytes())
    env_bindings = _strict_environment_bindings(
        (root / ".env").read_bytes(), separator=b"\n", label=f"{root}/.env"
    )
    require(
        not _forbidden_environment_names(env_bindings),
        "protected runner .env exposes a protected secret name",
    )
    library_path = _require_exact_python_library_binding(
        env_bindings, label=f"{root}/.env"
    )
    remote = expected["runners"][active_index]
    require(
        config.get("agentId") == remote["id"]
        and config.get("agentName") == RUNNER_NAMES[active_index]
        and config.get("disableUpdate") is True
        and config.get("ephemeral") is True
        and config.get("gitHubUrl")
        == "https://github.com/Scuttie/enterprise-shared-memory-poc"
        and config.get("workFolder") == "_work",
        "protected runner configuration differs",
    )
    current_binding = {
        "agent_id": remote["id"],
        "agent_name": RUNNER_NAMES[active_index],
        "disable_update": True,
        "ephemeral": True,
        "ld_library_path": library_path,
        "listener_bytes": RUNNER_LISTENER_BYTES,
        "listener_sha256": RUNNER_LISTENER_SHA256,
        "listener_version": listener_version,
        "root": RUNNER_ROOTS[active_index],
        "work_folder": "_work",
    }
    listeners: list[dict[str, Any]] = []
    proc_root = Path("/proc")
    require(proc_root.is_dir(), "runner process filesystem is unavailable")
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / "comm").read_text(encoding="utf-8").strip() != "Runner.Listener":
                continue
            process_environment = _strict_environment_bindings(
                (proc / "environ").read_bytes(),
                separator=b"\0",
                label=f"Runner.Listener pid {proc.name}",
            )
            cwd = os.readlink(proc / "cwd")
        except FileNotFoundError:
            continue
        require(
            not _forbidden_environment_names(process_environment),
            "runner listener exposes a protected benchmark secret name",
        )
        listeners.append(
            {
                "ld_library_path": _require_exact_python_library_binding(
                    process_environment, label=f"Runner.Listener pid {proc.name}"
                ),
                "pid": int(proc.name),
                "root": cwd,
            }
        )
    active_listeners = [row for row in listeners if row["root"] == RUNNER_ROOTS[active_index]]
    teardown_listeners = [
        row for row in listeners if row["root"] == RUNNER_ROOTS[1 - active_index]
    ]
    require(
        len(active_listeners) == 1
        and len(teardown_listeners) <= 1
        and len(listeners) == len(active_listeners) + len(teardown_listeners)
        and len({row["pid"] for row in listeners}) == len(listeners),
        "protected runner listener set differs",
    )
    for stale_root in STALE_RUNNER_ROOTS:
        require(not os.path.lexists(stale_root), f"stale runner workspace remains: {stale_root}")
    disk_available = shutil.disk_usage("/opt").free
    require(
        disk_available >= MINIMUM_RUNNER_DISK_BYTES,
        "live runner disk availability is below the frozen minimum",
    )
    _verify_local_docker_client()
    docker_client_version, docker_server_version = _validate_docker_version(_local_stdout(
        [*DOCKER_LOCAL_PREFIX, "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
        safe_environment=safe_environment,
        label="protected Docker daemon",
    ))
    docker_root_directory = _validate_docker_root_directory(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "info", "--format", "{{.DockerRootDir}}"],
            safe_environment=safe_environment,
            label="protected Docker root directory",
        )
    )
    docker_pull_never = _validate_docker_pull_never_help(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "create", "--help"],
            safe_environment=safe_environment,
            label="protected Docker cache-only create contract",
        )
    )
    execution_images = _expected_execution_images(repository, source_head)
    cached_image_ids: dict[str, str] = {}
    for image in execution_images:
        image_id = _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "image", "inspect", "--format", "{{.Id}}", image],
            safe_environment=safe_environment,
            label=f"protected cached image {image}",
        )
        require(DOCKER_IMAGE_ID.fullmatch(image_id) is not None, "cached DEV image ID is malformed")
        cached_image_ids[image] = image_id
    service_images = _expected_service_images(repository, source_head)
    service_image_ids: dict[str, str] = {}
    for role, image in service_images.items():
        image_id = _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "image", "inspect", "--format", "{{.Id}}", image],
            safe_environment=safe_environment,
            label=f"protected {role} service image",
        )
        require(DOCKER_IMAGE_ID.fullmatch(image_id) is not None, f"{role} service image ID is malformed")
        service_image_ids[role] = image_id
    container_text = _local_stdout(
        [*DOCKER_LOCAL_PREFIX, "ps", "-aq", "--no-trunc"],
        safe_environment=safe_environment,
        label="protected exact service container set",
    )
    container_ids = container_text.splitlines()
    require(
        container_ids == [],
        "protected preflight requires zero Docker containers",
    )
    available_service_ports = _probe_local_service_ports_available()
    evidence = {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "architecture": architecture,
        "available_service_ports": available_service_ports,
        "cached_execution_image_ids": cached_image_ids,
        "container_count": 0,
        "current_runner_binding": current_binding,
        "disk_available_bytes": disk_available,
        "docker_client_bytes": DOCKER_CLIENT_BYTES,
        "docker_client_path": DOCKER_CLIENT_PATH,
        "docker_client_sha256": DOCKER_CLIENT_SHA256,
        "docker_client_version": docker_client_version,
        "docker_create_pull_never_supported": docker_pull_never,
        "docker_root_directory": docker_root_directory,
        "docker_server_version": docker_server_version,
        "exact_python_library_path": EXACT_PYTHON_LIBRARY_PATH,
        "exact_python_path": f"{EXACT_PYTHON_ROOT}/bin/python",
        "exact_python_version": "Python 3.11.10",
        "execution_run_attempt": 1,
        "execution_run_id": run_id,
        "forbidden_secret_names_present": [],
        "listener_binding": active_listeners[0],
        "minimum_disk_available_bytes": MINIMUM_RUNNER_DISK_BYTES,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        **os_release,
        "python_toolcache_complete_bytes": PYTHON_TOOLCACHE_COMPLETE_BYTES,
        "python_toolcache_complete_path": PYTHON_TOOLCACHE_COMPLETE_PATH,
        "python_toolcache_complete_sha256": PYTHON_TOOLCACHE_COMPLETE_SHA256,
        "repository": EXPECTED_REPOSITORY,
        "runner_listener_bytes": RUNNER_LISTENER_BYTES,
        "runner_listener_sha256": RUNNER_LISTENER_SHA256,
        "runner_package_archive_bytes": RUNNER_PACKAGE_ARCHIVE_BYTES,
        "runner_package_archive_path": RUNNER_PACKAGE_ARCHIVE_PATH,
        "runner_package_archive_sha256": RUNNER_PACKAGE_ARCHIVE_SHA256,
        "runner_package_version": RUNNER_PACKAGE_VERSION,
        "runner_gid": runner_gid,
        "runner_uid": runner_uid,
        "runner_user": runner_user,
        "service_image_ids": service_image_ids,
        "source_head": source_head,
        "stale_runner_roots_absent": list(STALE_RUNNER_ROOTS),
        "status": "PASS",
        "teardown_listener_binding": (
            teardown_listeners[0] if teardown_listeners else None
        ),
        "tool_cache_root": RUNNER_TOOL_CACHE,
        "trigger_head": trigger_head,
    }
    return _validate_protected_runner_readiness(
        evidence,
        source_head=source_head,
        trigger_head=trigger_head,
        run_id=run_id,
        expected_readiness=expected,
        execution_images=execution_images,
        service_images=service_images,
    )


def validate_protected_runner_preflight(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bind the first protected run step to `_012`, runner, and services."""

    repository = resolve_repository_root(repository)
    environment = os.environ if environ is None else environ
    _validate_secret_free_branch_environment(environment)
    _require_exact_python_library_binding(
        environment, label="protected preflight process environment"
    )
    require(environment.get("GITHUB_EVENT_NAME") == "push", "event is not push")
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "attempt must be one")
    require(environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY, "repository differs")
    require(environment.get("GITHUB_REF") == EXPECTED_REF, "ref differs")
    require(environment.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF, "workflow ref differs")
    require(
        environment.get("GITHUB_JOB") == "frozen-serial-phase",
        "protected probe is outside the frozen-serial-phase job",
    )
    require(
        environment.get("RUNNER_OS") == "Linux"
        and environment.get("RUNNER_ARCH") == "X64",
        "runner host platform differs",
    )
    run_id_text = environment.get("GITHUB_RUN_ID", "")
    require(
        run_id_text.isascii() and run_id_text.isdigit() and int(run_id_text) > 0,
        "run ID differs",
    )
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
        "protected push payload differs",
    )
    require(
        environment.get("GITHUB_SHA") == after
        and environment.get("GITHUB_WORKFLOW_SHA") == after,
        "protected execution SHA differs",
    )
    request = validate_sentinel_commit(
        repository,
        after,
        expected_parent=before,
        require_checked_out_head=True,
    )
    readiness = _validate_runner_readiness(
        request["runner_readiness"], source_head=before
    )
    # A protected-environment review can exceed the source snapshot age.
    # This live observation supersedes it; branch/bounded gates remain fresh.
    del now
    live = collect_protected_runner_readiness(
        repository,
        before,
        after,
        int(run_id_text),
        readiness,
        environ=environment,
    )
    return {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "execution_run_attempt": 1,
        "execution_run_id": int(run_id_text),
        "protected_runner_sha256": hashlib.sha256(canonical_bytes(live)).hexdigest(),
        "request_id": REQUEST_ID,
        "source_head": before,
        "status": "PASS",
        "trigger_commit": after,
    }


def _service_container_names(run_id: int) -> dict[str, str]:
    require(type(run_id) is int and run_id > 0, "service run ID differs")
    return {
        role: f"{SERVICE_CONTAINER_NAME_PREFIX}-{run_id}-{role}"
        for role in SERVICE_IMAGE_REFS
    }


def _service_volume_name(run_id: int) -> str:
    require(type(run_id) is int and run_id > 0, "service volume run ID differs")
    return f"{SERVICE_CONTAINER_NAME_PREFIX}-{run_id}-postgres-data"


def _service_state_path(environ: Mapping[str, str]) -> Path:
    raw = environ.get("RUNNER_TEMP")
    require(isinstance(raw, str) and bool(raw), "runner temporary root is missing")
    root = Path(raw)
    runner_name = environ.get("RUNNER_NAME")
    require(runner_name in RUNNER_NAMES, "runner identity is missing")
    active_index = RUNNER_NAMES.index(str(runner_name))
    expected_root = Path(RUNNER_ROOTS[active_index]) / "_work" / "_temp"
    workspace_raw = environ.get("GITHUB_WORKSPACE")
    require(isinstance(workspace_raw, str) and bool(workspace_raw), "runner workspace is missing")
    workspace = Path(workspace_raw).resolve(strict=True)
    require(
        root.is_absolute()
        and root.is_dir()
        and not root.is_symlink()
        and root.resolve(strict=True) == root
        and root == expected_root,
        "runner temporary root is missing or indirect",
    )
    require(
        workspace.is_relative_to(Path(RUNNER_ROOTS[active_index])),
        "runner temporary root and workspace belong to different runners",
    )
    return root / SERVICE_STATE_FILENAME


def _protected_execution_context(
    repository: Path,
    event_path: Path,
    environment: Mapping[str, str],
) -> tuple[str, str, int, dict[str, Any]]:
    repository = resolve_repository_root(repository)
    _validate_secret_free_branch_environment(environment)
    _require_exact_python_library_binding(
        environment, label="protected service lifecycle process environment"
    )
    require(environment.get("GITHUB_EVENT_NAME") == "push", "event is not push")
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "attempt must be one")
    require(environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY, "repository differs")
    require(environment.get("GITHUB_REF") == EXPECTED_REF, "ref differs")
    require(environment.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF, "workflow ref differs")
    require(environment.get("GITHUB_JOB") == "frozen-serial-phase", "service lifecycle is outside the frozen job")
    require(
        environment.get("RUNNER_OS") == "Linux"
        and environment.get("RUNNER_ARCH") == "X64",
        "runner host platform differs",
    )
    run_id_text = environment.get("GITHUB_RUN_ID", "")
    require(run_id_text.isascii() and run_id_text.isdigit() and int(run_id_text) > 0, "run ID differs")
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
        and HEX40.fullmatch(after) is not None
        and environment.get("GITHUB_SHA") == after
        and environment.get("GITHUB_WORKFLOW_SHA") == after,
        "protected service lifecycle event identity differs",
    )
    request = validate_sentinel_commit(
        repository,
        after,
        expected_parent=before,
        require_checked_out_head=True,
    )
    _validate_runner_readiness(request.get("runner_readiness"), source_head=before)
    return before, after, int(run_id_text), request


def _validate_service_state(
    raw: bytes,
    *,
    source_head: str,
    trigger_head: str,
    run_id: int,
    service_images: Mapping[str, str],
) -> dict[str, Any]:
    state = strict_json(raw)
    require(raw == canonical_bytes(state, trailing_lf=True), "service state is not canonical")
    require(
        set(state)
        == {
            "baseline_volume_names",
            "containers",
            "execution_run_attempt",
            "execution_run_id",
            "repository",
            "schema",
            "source_head",
            "postgres_volume",
            "trigger_head",
        }
        and state.get("schema") == SERVICE_STATE_SCHEMA
        and state.get("repository") == EXPECTED_REPOSITORY
        and state.get("source_head") == source_head
        and state.get("trigger_head") == trigger_head
        and type(state.get("execution_run_attempt")) is int
        and state.get("execution_run_attempt") == 1
        and type(state.get("execution_run_id")) is int
        and state.get("execution_run_id") == run_id,
        "service state identity differs",
    )
    baseline = state.get("baseline_volume_names")
    volume = state.get("postgres_volume")
    expected_volume_name = _service_volume_name(run_id)
    require(
        isinstance(baseline, list)
        and baseline == sorted(baseline)
        and len(baseline) == len(set(baseline))
        and all(isinstance(name, str) and bool(name) for name in baseline)
        and expected_volume_name not in baseline
        and isinstance(volume, Mapping)
        and set(volume) == {"destination", "name", "source"}
        and volume.get("destination") == "/var/lib/postgresql/data"
        and volume.get("name") == expected_volume_name
        and volume.get("source")
        == f"{DOCKER_ROOT_DIRECTORY}/volumes/{expected_volume_name}/_data",
        "service state volume boundary differs",
    )
    containers = state.get("containers")
    names = _service_container_names(run_id)
    require(
        isinstance(containers, Mapping) and set(containers) == set(SERVICE_IMAGE_REFS),
        "service state container set differs",
    )
    ids: list[str] = []
    for role, image in service_images.items():
        row = containers.get(role)
        require(
            isinstance(row, Mapping)
            and set(row) == {"container_id", "image", "image_id", "name", "port", "role"}
            and row.get("role") == role
            and row.get("name") == names[role]
            and row.get("image") == image
            and isinstance(row.get("image_id"), str)
            and DOCKER_IMAGE_ID.fullmatch(row["image_id"]) is not None
            and type(row.get("port")) is int
            and row.get("port") == SERVICE_PORTS[role],
            f"{role} service state differs",
        )
        ids.append(_validate_service_container_id(row.get("container_id"), role=role))
    require(len(ids) == len(set(ids)), "service state container IDs are not unique")
    return state


def _read_service_state(
    path: Path,
    *,
    source_head: str,
    trigger_head: str,
    run_id: int,
    service_images: Mapping[str, str],
) -> dict[str, Any]:
    raw = _read_direct_service_state_bytes(path)
    return _validate_service_state(
        raw,
        source_head=source_head,
        trigger_head=trigger_head,
        run_id=run_id,
        service_images=service_images,
    )


def _require_service_state_metadata(
    observed: os.stat_result, *, label: str
) -> None:
    require(
        stat.S_ISREG(observed.st_mode)
        and not stat.S_ISLNK(observed.st_mode)
        and stat.S_IMODE(observed.st_mode) == 0o600
        and observed.st_uid == RUNNER_SERVICE_UID
        and observed.st_gid == RUNNER_SERVICE_GID
        and observed.st_nlink == 1,
        f"service state file metadata differs: {label}",
    )


def _require_service_state_process_identity(uid: int, gid: int) -> None:
    require(
        type(uid) is int
        and type(gid) is int
        and uid == RUNNER_SERVICE_UID
        and gid == RUNNER_SERVICE_GID,
        "service state process ownership differs",
    )


def _read_direct_service_state_bytes(path: Path) -> bytes:
    """Read a state file only through an owned, direct, single-link inode."""

    require(
        os.name == "posix" and hasattr(os, "getuid") and hasattr(os, "getgid"),
        "service state ownership can only be verified on POSIX",
    )
    _require_service_state_process_identity(os.getuid(), os.getgid())
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise DevelopmentTriggerError("service state file is missing or indirect") from exc
    _require_service_state_metadata(
        before,
        label="before open",
    )
    require(resolved == path, "service state file is missing or indirect")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise DevelopmentTriggerError("service state file could not be opened safely") from exc
    try:
        opened = os.fstat(descriptor)
        _require_service_state_metadata(
            opened,
            label="after open",
        )
        require(
            (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
            "service state file changed during open",
        )
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        raise DevelopmentTriggerError("service state file changed during read") from exc
    _require_service_state_metadata(
        after,
        label="after read",
    )
    require(
        (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino),
        "service state file changed during read",
    )
    return raw


def _service_create_argv(
    *,
    role: str,
    image: str,
    name: str,
    run_id: int,
    source_head: str,
    trigger_head: str,
    postgres_volume_name: str,
) -> list[str]:
    port = SERVICE_PORTS[role]
    argv = [
        *DOCKER_LOCAL_PREFIX,
        "create",
        "--pull=never",
        "--name",
        name,
        "--label",
        f"trimem.d112.role={role}",
        "--label",
        f"trimem.d112.run_id={run_id}",
        "--label",
        f"trimem.d112.source_head={source_head}",
        "--label",
        f"trimem.d112.trigger_head={trigger_head}",
        "--publish",
        f"127.0.0.1:{port}:{port}",
    ]
    if role == "postgres":
        argv.extend(
            [
                "--mount",
                "type=volume,source="
                + postgres_volume_name
                + ",target=/var/lib/postgresql/data",
                "--env",
                "POSTGRES_DB=trimem_benchmark",
                "--env",
                "POSTGRES_PASSWORD=postgres",
                "--env",
                "POSTGRES_USER=postgres",
                "--health-cmd",
                "pg_isready -U postgres -d trimem_benchmark",
                "--health-interval",
                "5s",
                "--health-timeout",
                "5s",
                "--health-retries",
                "20",
            ]
        )
    argv.append(image)
    return argv


def _docker_container_ids(
    safe_environment: Mapping[str, str], *, label: str, timeout: float = 60
) -> list[str]:
    text = _local_stdout(
        [*DOCKER_LOCAL_PREFIX, "ps", "-aq", "--no-trunc"],
        safe_environment=safe_environment,
        label=label,
        timeout=timeout,
    )
    ids = text.splitlines() if text else []
    require(
        len(ids) == len(set(ids))
        and all(HEX64.fullmatch(value) is not None for value in ids),
        "Docker container ID set is malformed",
    )
    return ids


def _docker_volume_names(
    safe_environment: Mapping[str, str], *, label: str, timeout: float = 60
) -> list[str]:
    text = _local_stdout(
        [*DOCKER_LOCAL_PREFIX, "volume", "ls", "-q"],
        safe_environment=safe_environment,
        label=label,
        timeout=timeout,
    )
    names = text.splitlines() if text else []
    require(
        len(names) == len(set(names))
        and all(
            bool(name)
            and name == name.strip()
            and all(character.isalnum() or character in "_.-" for character in name)
            for name in names
        ),
        "Docker volume name set is malformed",
    )
    return sorted(names)


def _inspect_named_service_volume(
    volume_name: str,
    *,
    state: Mapping[str, Any],
    safe_environment: Mapping[str, str],
    timeout: float = 60,
) -> dict[str, str]:
    document = strict_json(
        _run_readiness_command(
            [*DOCKER_LOCAL_PREFIX, "volume", "inspect", "--format", "{{json .}}", volume_name],
            safe_environment=safe_environment,
            label="exact run-bound postgres volume",
            timeout=timeout,
        )
    )
    labels = document.get("Labels")
    require(
        document.get("Name") == volume_name
        and document.get("Driver") == "local"
        and document.get("Mountpoint")
        == f"{DOCKER_ROOT_DIRECTORY}/volumes/{volume_name}/_data"
        and isinstance(labels, Mapping)
        and labels.get("trimem.d112.role") == "postgres-data"
        and labels.get("trimem.d112.run_id") == str(state["execution_run_id"])
        and labels.get("trimem.d112.source_head") == state["source_head"]
        and labels.get("trimem.d112.trigger_head") == state["trigger_head"],
        "run-bound postgres volume identity differs",
    )
    return {
        "destination": "/var/lib/postgresql/data",
        "name": volume_name,
        "source": str(document["Mountpoint"]),
    }


def _remaining_service_timeout(
    deadline: float, monotonic: Callable[[], float]
) -> float:
    remaining = deadline - monotonic()
    require(remaining > 0, "cache-only services did not become ready in 120 seconds")
    return min(60.0, remaining)


def _observe_state_bound_services(
    state: Mapping[str, Any],
    *,
    safe_environment: Mapping[str, str],
    require_running: bool,
    allow_absent: bool = False,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, dict[str, Any]]:
    rows = state["containers"]
    expected_ids = {str(row["container_id"]) for row in rows.values()}
    current_ids = set(
        _docker_container_ids(
            safe_environment,
            label="exact cache-only service set",
            timeout=(
                60
                if deadline is None
                else _remaining_service_timeout(deadline, monotonic)
            ),
        )
    )
    require(
        current_ids.issubset(expected_ids) if allow_absent else current_ids == expected_ids,
        "Docker container set is not exactly the state-bound services",
    )
    observed: dict[str, dict[str, Any]] = {}
    for role in SERVICE_IMAGE_REFS:
        expected = rows[role]
        container_id = str(expected["container_id"])
        if container_id not in current_ids:
            continue
        document = strict_json(
            _run_readiness_command(
                [*DOCKER_LOCAL_PREFIX, "container", "inspect", "--format", "{{json .}}", container_id],
                safe_environment=safe_environment,
                label=f"state-bound {role} service",
                timeout=(
                    60
                    if deadline is None
                    else _remaining_service_timeout(deadline, monotonic)
                ),
            )
        )
        config = document.get("Config")
        state_record = document.get("State")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        expected_labels = {
            "trimem.d112.role": role,
            "trimem.d112.run_id": str(state["execution_run_id"]),
            "trimem.d112.source_head": state["source_head"],
            "trimem.d112.trigger_head": state["trigger_head"],
        }
        require(
            document.get("Id") == container_id
            and document.get("Name") == "/" + str(expected["name"])
            and document.get("Image") == expected["image_id"]
            and isinstance(config, Mapping)
            and config.get("Image") == expected["image"]
            and isinstance(labels, Mapping)
            and all(labels.get(key) == value for key, value in expected_labels.items())
            and isinstance(state_record, Mapping)
            and type(state_record.get("Running")) is bool
            and (not require_running or state_record.get("Running") is True)
            and _mapped_host_port(document, role=role) == expected["port"],
            f"state-bound {role} service identity differs",
        )
        mounts = document.get("Mounts")
        require(isinstance(mounts, list), f"{role} service mount set is malformed")
        if role == "postgres":
            volume = state["postgres_volume"]
            require(
                len(mounts) == 1
                and isinstance(mounts[0], Mapping)
                and mounts[0].get("Type") == "volume"
                and mounts[0].get("Name") == volume["name"]
                and mounts[0].get("Source") == volume["source"]
                and mounts[0].get("Destination") == volume["destination"]
                and mounts[0].get("RW") is True,
                "state-bound postgres volume mount differs",
            )
            _inspect_named_service_volume(
                str(volume["name"]),
                state=state,
                safe_environment=safe_environment,
                timeout=(
                    60
                    if deadline is None
                    else _remaining_service_timeout(deadline, monotonic)
                ),
            )
        else:
            require(mounts == [], "qdrant service unexpectedly owns a mount")
        if role == "postgres":
            environment_rows = config.get("Env")
            require(isinstance(environment_rows, list), "postgres environment is malformed")
            for binding in (
                "POSTGRES_DB=trimem_benchmark",
                "POSTGRES_PASSWORD=postgres",
                "POSTGRES_USER=postgres",
            ):
                name = binding.split("=", 1)[0] + "="
                require(
                    [row for row in environment_rows if isinstance(row, str) and row.startswith(name)]
                    == [binding],
                    "postgres service environment differs",
                )
        observed[role] = dict(document)
    return observed


def _rollback_created_services(
    created_ids: Sequence[str],
    *,
    created_volume: str | None,
    baseline_volume_names: Sequence[str],
    safe_environment: Mapping[str, str],
) -> None:
    require(
        len(created_ids) == len(set(created_ids))
        and all(HEX64.fullmatch(value) is not None for value in created_ids),
        "partial service rollback IDs are malformed",
    )
    baseline = list(baseline_volume_names)
    require(
        baseline == sorted(baseline) and len(baseline) == len(set(baseline)),
        "partial service rollback baseline is malformed",
    )
    expected_ids = set(created_ids)
    remaining_ids = set(
        _docker_container_ids(
            safe_environment, label="partial rollback current container set"
        )
    )
    require(
        remaining_ids.issubset(expected_ids),
        "partial service rollback found an unknown Docker container",
    )
    for container_id in reversed(created_ids):
        if container_id not in remaining_ids:
            continue
        _run_readiness_command(
            [*DOCKER_LOCAL_PREFIX, "rm", "-f", "--volumes", "--", container_id],
            safe_environment=safe_environment,
            label="partial cache-only service rollback container",
        )
    current_volumes = set(
        _docker_volume_names(
            safe_environment, label="partial rollback current volume set"
        )
    )
    baseline_set = set(baseline)
    if created_volume is not None:
        require(
            created_volume == _service_volume_name(int(created_volume.split("-")[2])),
            "partial service rollback volume name differs",
        )
        require(
            baseline_set.issubset(current_volumes)
            and current_volumes - baseline_set <= {created_volume},
            "partial service rollback found an unknown or missing Docker volume",
        )
        if created_volume in current_volumes:
            _run_readiness_command(
                [*DOCKER_LOCAL_PREFIX, "volume", "rm", "--", created_volume],
                safe_environment=safe_environment,
                label="partial postgres volume rollback",
            )
    else:
        require(
            current_volumes == baseline_set,
            "partial service rollback changed the baseline volume set",
        )
    require(
        _docker_container_ids(safe_environment, label="partial rollback verification") == [],
        "partial service rollback left a Docker container",
    )
    require(
        _docker_volume_names(
            safe_environment, label="partial volume rollback verification"
        )
        == baseline,
        "partial service rollback changed the baseline volume set",
    )


def start_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    environment = os.environ if environ is None else environ
    preflight = validate_protected_runner_preflight(
        repository, event_path, environ=environment
    )
    source_head = str(preflight["source_head"])
    trigger_head = str(preflight["trigger_commit"])
    run_id = int(preflight["execution_run_id"])
    state_path = _service_state_path(environment)
    require(not os.path.lexists(state_path), "cache-only service state already exists")
    safe_environment = _safe_environment(environment)
    _verify_local_docker_client()
    _validate_docker_version(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
            safe_environment=safe_environment,
            label="cache-only service Docker version",
        )
    )
    _validate_docker_root_directory(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "info", "--format", "{{.DockerRootDir}}"],
            safe_environment=safe_environment,
            label="cache-only service Docker root directory",
        )
    )
    _validate_docker_pull_never_help(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "create", "--help"],
            safe_environment=safe_environment,
            label="cache-only service create contract",
        )
    )
    require(
        _docker_container_ids(safe_environment, label="pre-create container set") == [],
        "cache-only service creation requires zero containers",
    )
    _probe_local_service_ports_available()
    images = _expected_service_images(repository, source_head)
    names = _service_container_names(run_id)
    baseline_volume_names = _docker_volume_names(
        safe_environment, label="pre-create baseline volume set"
    )
    volume_name = _service_volume_name(run_id)
    require(
        volume_name not in baseline_volume_names,
        "run-bound postgres volume already exists",
    )
    image_ids: dict[str, str] = {}
    for role, image in images.items():
        image_id = _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "image", "inspect", "--format", "{{.Id}}", image],
            safe_environment=safe_environment,
            label=f"pre-create cached {role} service image",
        )
        require(DOCKER_IMAGE_ID.fullmatch(image_id) is not None, f"{role} service image ID is malformed")
        image_ids[role] = image_id
    created: list[str] = []
    created_volume: str | None = None
    try:
        observed_volume_name = _local_stdout(
            [
                *DOCKER_LOCAL_PREFIX,
                "volume",
                "create",
                "--label",
                "trimem.d112.role=postgres-data",
                "--label",
                f"trimem.d112.run_id={run_id}",
                "--label",
                f"trimem.d112.source_head={source_head}",
                "--label",
                f"trimem.d112.trigger_head={trigger_head}",
                volume_name,
            ],
            safe_environment=safe_environment,
            label="create exact run-bound postgres volume",
        )
        require(observed_volume_name == volume_name, "created postgres volume name differs")
        created_volume = volume_name
        rows: dict[str, dict[str, Any]] = {}
        for role, image in images.items():
            container_id = _local_stdout(
                _service_create_argv(
                    role=role,
                    image=image,
                    name=names[role],
                    run_id=run_id,
                    source_head=source_head,
                    trigger_head=trigger_head,
                    postgres_volume_name=volume_name,
                ),
                safe_environment=safe_environment,
                label=f"create cache-only {role} service",
            )
            _validate_service_container_id(container_id, role=role)
            created.append(container_id)
            rows[role] = {
                "container_id": container_id,
                "image": image,
                "image_id": image_ids[role],
                "name": names[role],
                "port": SERVICE_PORTS[role],
                "role": role,
            }
        require(len(created) == len(set(created)), "created service IDs are not unique")
        for role in SERVICE_IMAGE_REFS:
            started = _local_stdout(
                [*DOCKER_LOCAL_PREFIX, "start", rows[role]["container_id"]],
                safe_environment=safe_environment,
                label=f"start cache-only {role} service",
            )
            require(started == rows[role]["container_id"], f"{role} service start result differs")
        state = {
            "baseline_volume_names": baseline_volume_names,
            "containers": rows,
            "execution_run_attempt": 1,
            "execution_run_id": run_id,
            "repository": EXPECTED_REPOSITORY,
            "schema": SERVICE_STATE_SCHEMA,
            "source_head": source_head,
            "postgres_volume": {
                "destination": "/var/lib/postgresql/data",
                "name": volume_name,
                "source": f"{DOCKER_ROOT_DIRECTORY}/volumes/{volume_name}/_data",
            },
            "trigger_head": trigger_head,
        }
        _inspect_named_service_volume(
            volume_name, state=state, safe_environment=safe_environment
        )
        raw = canonical_bytes(state, trailing_lf=True)
        _validate_service_state(
            raw,
            source_head=source_head,
            trigger_head=trigger_head,
            run_id=run_id,
            service_images=images,
        )
        descriptor = os.open(
            state_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(
            _read_service_state(
                state_path,
                source_head=source_head,
                trigger_head=trigger_head,
                run_id=run_id,
                service_images=images,
            )
            == state,
            "service state differs immediately after publication",
        )
    except BaseException:
        if os.path.lexists(state_path):
            state_path.unlink()
        _rollback_created_services(
            created,
            created_volume=created_volume,
            baseline_volume_names=baseline_volume_names,
            safe_environment=safe_environment,
        )
        raise
    return {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "container_count": 2,
        "service_state_sha256": hashlib.sha256(raw).hexdigest(),
        "status": "STARTED_CACHE_ONLY_SERVICES",
    }


def _qdrant_ready(*, timeout: float = 2) -> bool:
    require(timeout > 0, "qdrant readiness timeout is exhausted")
    connection = http.client.HTTPConnection(
        "127.0.0.1", SERVICE_PORTS["qdrant"], timeout=min(2.0, timeout)
    )
    try:
        connection.request("GET", "/readyz")
        response = connection.getresponse()
        body = response.read(1024)
        return response.status == 200 and len(body) < 1024
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def verify_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    _monotonic: Callable[[], float] | None = None,
    _sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    environment = os.environ if environ is None else environ
    source_head, trigger_head, run_id, _request = _protected_execution_context(
        repository, event_path, environment
    )
    state_path = _service_state_path(environment)
    images = _expected_service_images(repository, source_head)
    state = _read_service_state(
        state_path,
        source_head=source_head,
        trigger_head=trigger_head,
        run_id=run_id,
        service_images=images,
    )
    safe_environment = _safe_environment(environment)
    _verify_local_docker_client()
    _validate_docker_version(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
            safe_environment=safe_environment,
            label="service verification Docker version",
        )
    )
    _validate_docker_root_directory(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "info", "--format", "{{.DockerRootDir}}"],
            safe_environment=safe_environment,
            label="service verification Docker root directory",
        )
    )
    monotonic = time.monotonic if _monotonic is None else _monotonic
    sleeper = time.sleep if _sleep is None else _sleep
    deadline = monotonic() + SERVICE_READY_TIMEOUT_SECONDS
    while True:
        observed = _observe_state_bound_services(
            state,
            safe_environment=safe_environment,
            require_running=True,
            deadline=deadline,
            monotonic=monotonic,
        )
        postgres_state = observed["postgres"].get("State")
        health = postgres_state.get("Health") if isinstance(postgres_state, Mapping) else None
        health_status = health.get("Status") if isinstance(health, Mapping) else None
        require(
            health_status in {"starting", "healthy"},
            "cache-only postgres service health failed",
        )
        if health_status == "healthy":
            qdrant_ready = _qdrant_ready(
                timeout=_remaining_service_timeout(deadline, monotonic)
            )
            require(
                deadline - monotonic() > 0,
                "cache-only services did not become ready in 120 seconds",
            )
            if qdrant_ready:
                break
        remaining = deadline - monotonic()
        require(remaining > 0, "cache-only services did not become ready in 120 seconds")
        sleeper(min(float(SERVICE_READY_POLL_SECONDS), remaining))
    raw = _read_direct_service_state_bytes(state_path)
    require(
        _validate_service_state(
            raw,
            source_head=source_head,
            trigger_head=trigger_head,
            run_id=run_id,
            service_images=images,
        )
        == state,
        "service state changed during verification",
    )
    return {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "container_count": 2,
        "service_state_sha256": hashlib.sha256(raw).hexdigest(),
        "status": "VERIFIED_CACHE_ONLY_SERVICES",
    }


def _cleanup_state_free_partial_services(
    *,
    source_head: str,
    trigger_head: str,
    run_id: int,
    service_images: Mapping[str, str],
    safe_environment: Mapping[str, str],
) -> int:
    """Recover only exact run-labelled objects left before state publication."""

    ids = _docker_container_ids(
        safe_environment, label="state-free partial service container set"
    )
    require(len(ids) <= len(SERVICE_IMAGE_REFS), "unbound Docker containers remain")
    names = _service_container_names(run_id)
    roles: set[str] = set()
    for container_id in ids:
        document = strict_json(
            _run_readiness_command(
                [*DOCKER_LOCAL_PREFIX, "container", "inspect", "--format", "{{json .}}", container_id],
                safe_environment=safe_environment,
                label="state-free partial service identity",
            )
        )
        config = document.get("Config")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        role = labels.get("trimem.d112.role") if isinstance(labels, Mapping) else None
        require(role in SERVICE_IMAGE_REFS and role not in roles, "unbound Docker container identity differs")
        roles.add(str(role))
        local_image_id = _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "image", "inspect", "--format", "{{.Id}}", service_images[str(role)]],
            safe_environment=safe_environment,
            label=f"state-free {role} cached image",
        )
        require(
            document.get("Id") == container_id
            and document.get("Name") == "/" + names[str(role)]
            and document.get("Image") == local_image_id
            and isinstance(config, Mapping)
            and config.get("Image") == service_images[str(role)]
            and labels.get("trimem.d112.run_id") == str(run_id)
            and labels.get("trimem.d112.source_head") == source_head
            and labels.get("trimem.d112.trigger_head") == trigger_head
            and _mapped_host_port(document, role=str(role)) == SERVICE_PORTS[str(role)],
            "unbound Docker container identity differs",
        )
        mounts = document.get("Mounts")
        require(isinstance(mounts, list), "unbound Docker mount set is malformed")
        if role == "postgres":
            volume_name = _service_volume_name(run_id)
            require(
                len(mounts) == 1
                and isinstance(mounts[0], Mapping)
                and mounts[0].get("Type") == "volume"
                and mounts[0].get("Name") == volume_name
                and mounts[0].get("Destination") == "/var/lib/postgresql/data"
                and mounts[0].get("RW") is True,
                "unbound postgres volume mount differs",
            )
        else:
            require(mounts == [], "unbound qdrant mount set differs")
    volume_name = _service_volume_name(run_id)
    current_volumes = _docker_volume_names(
        safe_environment, label="state-free partial service volume set"
    )
    volume_present = volume_name in current_volumes
    require("postgres" not in roles or volume_present, "partial postgres volume is missing")
    baseline = [name for name in current_volumes if name != volume_name]
    if volume_present:
        synthetic_state = {
            "execution_run_id": run_id,
            "source_head": source_head,
            "trigger_head": trigger_head,
        }
        _inspect_named_service_volume(
            volume_name, state=synthetic_state, safe_environment=safe_environment
        )
    for container_id in ids:
        _run_readiness_command(
            [*DOCKER_LOCAL_PREFIX, "rm", "-f", "--volumes", "--", container_id],
            safe_environment=safe_environment,
            label="remove exact state-free partial service",
        )
    if volume_present:
        _run_readiness_command(
            [*DOCKER_LOCAL_PREFIX, "volume", "rm", "--", volume_name],
            safe_environment=safe_environment,
            label="remove exact state-free postgres volume",
        )
    require(
        _docker_container_ids(safe_environment, label="state-free cleanup container verification") == []
        and _docker_volume_names(safe_environment, label="state-free cleanup volume verification") == baseline,
        "state-free partial service cleanup did not restore the baseline",
    )
    return len(ids)


def _cleanup_state_bound_services(
    state: Mapping[str, Any], *, safe_environment: Mapping[str, str]
) -> int:
    """Remove any remaining exact state-owned objects, one mutation at a time."""

    _observe_state_bound_services(
        state,
        safe_environment=safe_environment,
        require_running=False,
        allow_absent=True,
    )
    present_ids = set(
        _docker_container_ids(
            safe_environment, label="state-bound cleanup container set"
        )
    )
    expected_ids = {
        str(state["containers"][role]["container_id"]) for role in SERVICE_IMAGE_REFS
    }
    require(
        present_ids.issubset(expected_ids),
        "state-bound cleanup found an unknown Docker container",
    )
    for role in SERVICE_IMAGE_REFS:
        container_id = str(state["containers"][role]["container_id"])
        if container_id not in present_ids:
            continue
        _run_readiness_command(
            [*DOCKER_LOCAL_PREFIX, "rm", "-f", "--volumes", "--", container_id],
            safe_environment=safe_environment,
            label=f"remove exact state-bound {role} service",
        )
    volume_name = str(state["postgres_volume"]["name"])
    baseline_volumes = set(state["baseline_volume_names"])
    current_volumes = set(
        _docker_volume_names(
            safe_environment, label="state-bound cleanup volume set"
        )
    )
    require(
        baseline_volumes.issubset(current_volumes)
        and current_volumes - baseline_volumes <= {volume_name},
        "state-bound cleanup found an unknown or missing Docker volume",
    )
    if volume_name in current_volumes:
        _inspect_named_service_volume(
            volume_name, state=state, safe_environment=safe_environment
        )
        _run_readiness_command(
            [*DOCKER_LOCAL_PREFIX, "volume", "rm", "--", volume_name],
            safe_environment=safe_environment,
            label="remove exact state-bound postgres volume",
        )
    require(
        _docker_container_ids(safe_environment, label="cache-only service cleanup verification") == [],
        "cache-only service cleanup left a Docker container",
    )
    require(
        _docker_volume_names(
            safe_environment, label="cache-only service volume cleanup verification"
        )
        == state["baseline_volume_names"],
        "cache-only service cleanup changed the baseline volume set",
    )
    return len(present_ids)


def cleanup_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    environment = os.environ if environ is None else environ
    source_head, trigger_head, run_id, _request = _protected_execution_context(
        repository, event_path, environment
    )
    safe_environment = _safe_environment(environment)
    _verify_local_docker_client()
    _validate_docker_version(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
            safe_environment=safe_environment,
            label="service cleanup Docker version",
        )
    )
    _validate_docker_root_directory(
        _local_stdout(
            [*DOCKER_LOCAL_PREFIX, "info", "--format", "{{.DockerRootDir}}"],
            safe_environment=safe_environment,
            label="service cleanup Docker root directory",
        )
    )
    state_path = _service_state_path(environment)
    images = _expected_service_images(repository, source_head)
    if not os.path.lexists(state_path):
        removed = _cleanup_state_free_partial_services(
            source_head=source_head,
            trigger_head=trigger_head,
            run_id=run_id,
            service_images=images,
            safe_environment=safe_environment,
        )
        return {
            "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
            "container_count": 0,
            "recovered_partial_containers": removed,
            "status": "NO_SERVICES_TO_CLEAN" if removed == 0 else "CLEANED_PARTIAL_CACHE_ONLY_SERVICES",
        }
    state = _read_service_state(
        state_path,
        source_head=source_head,
        trigger_head=trigger_head,
        run_id=run_id,
        service_images=images,
    )
    _cleanup_state_bound_services(state, safe_environment=safe_environment)
    require(
        _read_service_state(
            state_path,
            source_head=source_head,
            trigger_head=trigger_head,
            run_id=run_id,
            service_images=images,
        )
        == state,
        "cache-only service state changed during cleanup",
    )
    state_path.unlink()
    require(not os.path.lexists(state_path), "cache-only service state cleanup failed")
    return {"activation_actuals": dict(ACTIVATION_ZERO_COUNTERS), "container_count": 0, "status": "CLEANED_CACHE_ONLY_SERVICES"}


def _pinned_gh_context() -> tuple[str, dict[str, str]]:
    gh = shutil.which("gh")
    require(gh is not None, "gh CLI is required to verify remote gates")
    # Hosted Linux uses the installed locked payload; the Windows request
    # writer uses a separately byte-pinned native observer.  The shared
    # verifier selects the exact platform record and never falls back to a
    # version-only check.
    try:
        root = Path(__file__).resolve().parents[1]
        lock = load_gh_cli_lock(root / GH_CLI_LOCK_PATH)
        verification = verify_observer_gh(lock, Path(gh))
    except (ImportError, OSError, ValueError) as exc:
        raise DevelopmentTriggerError(
            "remote gate observer does not match the pinned gh byte lock"
        ) from exc
    require(
        verification.get("status") == "PASS"
        and verification.get("first_version_line")
        == "gh version 2.97.0 (2026-07-31)"
        and verification.get("observer_platform")
        in {"linux_amd64", "windows_amd64"},
        "remote gate observer is not exact gh 2.97.0",
    )
    return gh, _safe_process_environment()


def _collect_current_pull_request(
    gh: str,
    safe_environment: Mapping[str, str],
    *,
    expected_head: str,
    allowed_stale_head: str | None,
    _monotonic: Callable[[], float] | None = None,
    _sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    require(
        isinstance(expected_head, str)
        and HEX40.fullmatch(expected_head) is not None,
        "PR head is not a commit SHA",
    )
    if allowed_stale_head is not None:
        require(
            isinstance(allowed_stale_head, str)
            and HEX40.fullmatch(allowed_stale_head) is not None
            and allowed_stale_head != expected_head,
            "allowed stale PR head is not a distinct commit SHA",
        )
    monotonic = time.monotonic if _monotonic is None else _monotonic
    sleeper = time.sleep if _sleep is None else _sleep
    timeout_message = (
        "current PR #18 exact-head visibility remained incomplete for 30 seconds"
    )
    deadline = monotonic() + REMOTE_VISIBILITY_TIMEOUT_SECONDS
    expected = {
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
    }
    for poll_index in range(REMOTE_VISIBILITY_MAX_POLLS):
        command_timeout = _remaining_visibility_seconds(
            deadline, monotonic, failure_message=timeout_message
        )
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
            timeout=command_timeout,
        )
        _remaining_visibility_seconds(
            deadline, monotonic, failure_message=timeout_message
        )
        pull_response = strict_json(pull_raw)
        pull_head = pull_response.get("head")
        pull_base = pull_response.get("base")
        if "head" in pull_response and pull_head is not None:
            require(isinstance(pull_head, Mapping), "current PR head is malformed")
        if "base" in pull_response and pull_base is not None:
            require(isinstance(pull_base, Mapping), "current PR base is malformed")
        pull_head_repo = (
            pull_head.get("repo") if isinstance(pull_head, Mapping) else None
        )
        if (
            isinstance(pull_head, Mapping)
            and "repo" in pull_head
            and pull_head_repo is not None
        ):
            require(
                isinstance(pull_head_repo, Mapping),
                "current PR head repository is malformed",
            )
        record = {
            "base_ref": (
                pull_base.get("ref") if isinstance(pull_base, Mapping) else None
            ),
            "base_sha": (
                pull_base.get("sha") if isinstance(pull_base, Mapping) else None
            ),
            "draft": pull_response.get("draft"),
            "head_ref": (
                pull_head.get("ref") if isinstance(pull_head, Mapping) else None
            ),
            "head_repository": (
                pull_head_repo.get("full_name")
                if isinstance(pull_head_repo, Mapping)
                else None
            ),
            "head_sha": (
                pull_head.get("sha") if isinstance(pull_head, Mapping) else None
            ),
            "html_url": pull_response.get("html_url"),
            "number": pull_response.get("number"),
            "state": pull_response.get("state"),
        }
        for name in (
            "base_ref",
            "base_sha",
            "head_ref",
            "head_repository",
            "head_sha",
            "html_url",
            "state",
        ):
            require(
                record[name] is None or isinstance(record[name], str),
                f"current PR field has the wrong type: {name}",
            )
        require(
            record["draft"] is None or type(record["draft"]) is bool,
            "current PR field has the wrong type: draft",
        )
        require(
            record["number"] is None or type(record["number"]) is int,
            "current PR field has the wrong type: number",
        )
        if record == expected:
            _remaining_visibility_seconds(
                deadline, monotonic, failure_message=timeout_message
            )
            return record
        non_head = {
            name: value for name, value in record.items() if name != "head_sha"
        }
        expected_non_head = {
            name: value for name, value in expected.items() if name != "head_sha"
        }
        non_head_compatible = all(
            value is None or value == expected_non_head[name]
            for name, value in non_head.items()
        )
        observed_head = record["head_sha"]
        head_compatible = (
            observed_head is None
            or observed_head == expected_head
            or observed_head == allowed_stale_head
        )
        incomplete = (
            any(value is None for value in record.values())
            and non_head_compatible
            and head_compatible
        )
        stale_head_only = (
            non_head == expected_non_head
            and allowed_stale_head is not None
            and observed_head == allowed_stale_head
        )
        require(
            incomplete or stale_head_only,
            "current PR #18 is not OPEN/DRAFT at the exact expected head",
        )
        if poll_index == REMOTE_VISIBILITY_MAX_POLLS - 1:
            raise DevelopmentTriggerError(timeout_message)
        _sleep_for_visibility_retry(
            deadline,
            monotonic,
            sleeper,
            failure_message=timeout_message,
        )
    raise AssertionError("unreachable current PR polling boundary")


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


def collect_remote_gate_evidence(
    source_head: str,
    *,
    allowed_stale_pr_head: str | None = None,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Collect the exact mixed-event twelve-gate activation evidence."""

    require(
        isinstance(source_head, str)
        and HEX40.fullmatch(source_head) is not None,
        "source_head is not a commit SHA",
    )
    gh, safe_environment = (
        _pinned_gh_context()
        if _observer_context is None
        else _observer_context
    )
    pull_record = _collect_current_pull_request(
        gh,
        safe_environment,
        expected_head=source_head,
        allowed_stale_head=allowed_stale_pr_head,
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
    trigger_head: str,
    environment: Mapping[str, str],
    *,
    _monotonic: Callable[[], float] | None = None,
    _sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    require(
        isinstance(trigger_head, str)
        and HEX40.fullmatch(trigger_head) is not None,
        "trigger workflow head is not a commit SHA",
    )
    run_id_text = environment.get("GITHUB_RUN_ID")
    require(
        isinstance(run_id_text, str)
        and run_id_text.isascii()
        and run_id_text.isdigit()
        and int(run_id_text) > 0,
        "current workflow run ID is invalid",
    )
    gh, safe_environment = _pinned_gh_context()
    monotonic = time.monotonic if _monotonic is None else _monotonic
    sleeper = time.sleep if _sleep is None else _sleep
    timeout_message = (
        "current _012 workflow run visibility remained incomplete for 30 seconds"
    )
    deadline = monotonic() + REMOTE_VISIBILITY_TIMEOUT_SECONDS
    expected_run_id = int(run_id_text)
    required_fields = {
        "conclusion",
        "event",
        "head_branch",
        "head_sha",
        "id",
        "path",
        "run_attempt",
        "status",
    }
    for poll_index in range(REMOTE_VISIBILITY_MAX_POLLS):
        command_timeout = _remaining_visibility_seconds(
            deadline, monotonic, failure_message=timeout_message
        )
        candidate = _query_github_run_by_id(
            gh,
            expected_run_id,
            safe_environment,
            timeout=command_timeout,
        )
        _remaining_visibility_seconds(
            deadline, monotonic, failure_message=timeout_message
        )
        if candidate is not None:
            present = set(candidate)
            # Any visible contradictory identity is deterministic, not an
            # eventual-consistency condition, and therefore fails immediately.
            if "id" in present:
                require(
                    type(candidate.get("id")) is int
                    and candidate.get("id") == expected_run_id,
                    "current benchmark workflow run identity differs",
                )
            for name, expected in (
                ("path", EXPECTED_WORKFLOW_PATH),
                ("event", "push"),
                ("head_sha", trigger_head),
                ("head_branch", EXPECTED_BRANCH),
            ):
                if name in present:
                    require(
                        isinstance(candidate.get(name), str)
                        and candidate.get(name) == expected,
                        "current benchmark workflow run identity differs",
                    )
            if "run_attempt" in present:
                require(
                    type(candidate.get("run_attempt")) is int
                    and candidate.get("run_attempt") == 1,
                    "current benchmark workflow run identity differs",
                )
            if "status" in present:
                require(
                    isinstance(candidate.get("status"), str)
                    and candidate.get("status")
                    in {"queued", "in_progress", "completed"},
                    "current benchmark workflow run identity differs",
                )
            if "conclusion" in present:
                conclusion = candidate.get("conclusion")
                require(
                    conclusion is None
                    or (isinstance(conclusion, str) and conclusion == "success"),
                    "current benchmark workflow run identity differs",
                )
            if "status" in present and "conclusion" in present:
                status = candidate.get("status")
                conclusion = candidate.get("conclusion")
                require(
                    (
                        status in {"queued", "in_progress"}
                        and conclusion is None
                    )
                    or (status == "completed" and conclusion == "success"),
                    "current benchmark workflow run state/conclusion differs",
                )
            if required_fields <= present:
                exact_query_timeout = _remaining_visibility_seconds(
                    deadline, monotonic, failure_message=timeout_message
                )
                exact_runs = _query_github_runs(
                    gh,
                    trigger_head,
                    "push",
                    safe_environment,
                    timeout=exact_query_timeout,
                )
                _remaining_visibility_seconds(
                    deadline, monotonic, failure_message=timeout_message
                )
                exact_workflow_rows = [
                    row
                    for row in exact_runs
                    if row.get("path") == EXPECTED_WORKFLOW_PATH
                    and row.get("event") == "push"
                    and row.get("head_sha") == trigger_head
                ]
                require(
                    len(exact_workflow_rows) <= 1,
                    "exactly one benchmark workflow push run is allowed for _012 HEAD",
                )
                if exact_workflow_rows:
                    exact_run_id = exact_workflow_rows[0].get("id")
                    require(
                        type(exact_run_id) is int
                        and exact_run_id == expected_run_id,
                        "exact benchmark workflow run ID differs",
                    )
                    _remaining_visibility_seconds(
                        deadline, monotonic, failure_message=timeout_message
                    )
                    return {
                        "event": "push",
                        "head_sha": trigger_head,
                        "run_attempt": 1,
                        "run_id": expected_run_id,
                        "workflow_path": EXPECTED_WORKFLOW_PATH,
                    }
        if poll_index == REMOTE_VISIBILITY_MAX_POLLS - 1:
            raise DevelopmentTriggerError(timeout_message)
        _sleep_for_visibility_retry(
            deadline,
            monotonic,
            sleeper,
            failure_message=timeout_message,
        )
    raise AssertionError("unreachable workflow-run polling boundary")


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
            "frozen cached-Python pre-setup verification",
            "protected live runner re-observation",
            "cache-only PostgreSQL and Qdrant start",
            "exact cache-only service verification",
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
            "final exact cache-only service and volume cleanup",
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
    repository = resolve_repository_root(repository)
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
    repository = resolve_repository_root(repository)
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
    repository = resolve_repository_root(repository)
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
    exposed = _forbidden_environment_names(environ)
    require(not exposed, "branch preflight exposes protected benchmark secrets")


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
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
    require(
        environment.get("GITHUB_JOB") == "branch-trigger-preflight",
        "branch trigger validation is outside the branch-trigger-preflight job",
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
        gh,
        safe_environment,
        expected_head=after,
        allowed_stale_head=before,
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
        == _collect_remote_runner_rows(gh, safe_environment),
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


def _recheck_request_write_boundary(
    repository: Path,
    source_head: str,
    target: Path,
) -> None:
    repository = resolve_repository_root(repository)
    expected_target = repository / Path(*PurePosixPath(SENTINEL_PATH).parts)
    require(target == expected_target, "request write target escaped the repository")
    require(
        target.parent.is_dir()
        and not target.parent.is_symlink()
        and target.parent.resolve(strict=True) == target.parent,
        "request write parent is not the exact repository directory",
    )
    require(
        git(repository, "symbolic-ref", "--quiet", "HEAD").strip()
        == EXPECTED_REF,
        "request rendering branch changed before the exclusive write",
    )
    require(
        git(repository, "rev-parse", "HEAD").strip() == source_head,
        "request rendering HEAD changed before the exclusive write",
    )
    require(
        not git(
            repository, "status", "--porcelain=v1", "--untracked-files=all"
        ).strip(),
        "request rendering worktree changed before the exclusive write",
    )
    require(
        not os.path.lexists(target),
        "_012 sentinel appeared before the exclusive write",
    )
    require(
        not git(
            repository,
            "log",
            "--format=%H",
            source_head,
            "--",
            SENTINEL_PATH,
        ).strip(),
        "_012 entered Git history before the exclusive write",
    )


def write_request(repository: Path) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
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
    require(
        not os.path.lexists(target),
        "_012 sentinel already exists in the worktree",
    )
    _validate_source(repository, source_head)
    observer_context = _pinned_gh_context()
    _require_no_pending_benchmark_consumers(*observer_context)
    gates = collect_remote_gate_evidence(
        source_head,
        allowed_stale_pr_head=None,
        _observer_context=observer_context,
    )
    readiness = collect_runner_readiness(
        repository, source_head, _observer_context=observer_context
    )
    document = build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
    )
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_no_pending_benchmark_consumers(*observer_context)
    _recheck_request_write_boundary(repository, source_head, target)
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
    group.add_argument("--pre-setup-cache-host-event-path", type=Path)
    group.add_argument("--protected-runner-preflight-event-path", type=Path)
    group.add_argument("--start-protected-services-event-path", type=Path)
    group.add_argument("--verify-protected-services-event-path", type=Path)
    group.add_argument("--cleanup-protected-services-event-path", type=Path)
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
        elif args.pre_setup_cache_host_event_path is not None:
            result = validate_pre_setup_cache_host(
                args.repository,
                args.pre_setup_cache_host_event_path,
            )
        elif args.protected_runner_preflight_event_path is not None:
            result = validate_protected_runner_preflight(
                args.repository,
                args.protected_runner_preflight_event_path,
            )
        elif args.start_protected_services_event_path is not None:
            result = start_protected_services(
                args.repository,
                args.start_protected_services_event_path,
            )
        elif args.verify_protected_services_event_path is not None:
            result = verify_protected_services(
                args.repository,
                args.verify_protected_services_event_path,
            )
        elif args.cleanup_protected_services_event_path is not None:
            result = cleanup_protected_services(
                args.repository,
                args.cleanup_protected_services_event_path,
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
