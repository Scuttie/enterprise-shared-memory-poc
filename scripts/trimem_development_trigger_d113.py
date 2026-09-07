"""Fail-closed one-time DEVELOPMENT_TUNING ``_013`` recovery trigger.

D1.13 changes one trust boundary from D1.12: the hosted branch job validates
the fresh runner preregistration evidence embedded before the sentinel was
created, but it does not ask the repository-runners administration endpoint
to repeat that observation.  The zero-authority writer still performs the
administrative runner collection.  The bounded and protected jobs retain the
local listener, registration, environment, scheduler, port, container, and
cache checks from D1.12.

The large, audited host/runtime implementation remains in the immutable D1.12
module.  Calls into it are made through a locked, reversible identity context;
importing this module never changes D1.12 global state.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import threading
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d112 as d112


# Repository and workflow identity is unchanged.
EXPECTED_REPOSITORY = d112.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d112.EXPECTED_BRANCH
EXPECTED_REF = d112.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d112.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d112.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d112.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d112.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d112.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d112.EXPECTED_BASE_HEAD

# Immutable EXEC _012 lineage and public failure evidence.
PREVIOUS_SOURCE_HEAD = "9db94e2a4abfaad0bb27079738b77836d68fa2e4"
PREVIOUS_EXECUTION_HEAD = "491d1022fe079d182d7b453c48083c486936dcb2"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_012.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "6691a24bf488a79b4e1843a129d3d8773090fe2654828534c35eeecc22cc9d38"
)
PREVIOUS_SENTINEL_BYTES = 20_561
PREVIOUS_SENTINEL_BLOB_OID = "f4111cfd1a26b4099f0b0fdc4dd840d4de21764f"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "efa99c554fbae9bbeb8a87536365fcfc6afa54e6ee48de17ef9ffdb0eb72132b"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "3bbafc53504b45c20996094d96a6abfa5fd9e90c5b078eb2f1dc3f1f6d7ad5b4"
)
PREVIOUS_RUN_ID = 34_128_541_859
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_FAILURE_SUBTYPE = "HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION"
PREVIOUS_FAILURE_CLASSIFICATION = (
    "HOSTED_GITHUB_TOKEN_REPOSITORY_RUNNER_LIST_COMMAND_FAILURE"
)
PREVIOUS_FAILURE_MESSAGE = (
    "runner readiness command failed: GitHub repository runners"
)
PREVIOUS_FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d113/exec_012_preprotected_failure.json"
)

# D1.13 starts after the exclusive _012 sentinel commit.  These names are
# deliberately exported for compatibility with freeze/status tooling.
STARTING_SOURCE_HEAD = PREVIOUS_EXECUTION_HEAD
STARTING_FREEZE_SHA256 = PREVIOUS_SOURCE_FREEZE_SHA256
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.13"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_013.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-013"

AMENDMENT_PATH = "artifacts/trimem_v1/development_exec_013_recovery_amendment.json"
AMENDMENT_SCHEMA = "trimem/development-exec-013-recovery-amendment/1.0"
INVENTORY_PATH = "artifacts/trimem_v1/development_exec_013_recovery_inventory.json"
INVENTORY_SCHEMA = "trimem/development-exec-013-recovery-inventory/1.0"
AMENDMENT_CLASSIFICATION = "POST_EXEC_012_ZERO_MODEL_RUNNER_OBSERVER_RECOVERY"
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_012_FAILURE_READY_FOR_EXEC_013_REQUEST"
)
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_013_REQUEST"
REPORT_PATH = "reports/TRIMEM_D113_EXEC_013_RECOVERY.md"
GATE_CONTRACT_PATH = "scripts/trimem_d113_gate_contract.py"
RESEAL_PATH = "scripts/trimem_d113_reseal.py"

FREEZE_PATH = d112.FREEZE_PATH
FREEZE_SCHEMA = d112.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.13"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.13"

# The science, caps, action pins, runner registrations, runner roots, cached
# interpreter, Docker client, images, and service namespace do not change.
MODEL_ID = d112.MODEL_ID
REASONING_EFFORT = d112.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d112.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d112.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d112.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d112.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d112.ACTIVATION_ZERO_COUNTERS
REMOTE_GATE_SPECS = d112.REMOTE_GATE_SPECS
REQUIRED_REMOTE_GATE_WORKFLOWS = d112.REQUIRED_REMOTE_GATE_WORKFLOWS
PRESERVED_SCIENTIFIC_PATHS = d112.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d112.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d112.EXECUTION_CONTRACT_PATHS

CHECKOUT_ACTION_SHA = d112.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d112.SETUP_PYTHON_ACTION_SHA
CODEQL_ACTION_SHA = d112.CODEQL_ACTION_SHA
RUNNER_DISTRIBUTION = d112.RUNNER_DISTRIBUTION
RUNNER_WSL_USER = d112.RUNNER_WSL_USER
RUNNER_NAMES = d112.RUNNER_NAMES
RUNNER_ROOTS = d112.RUNNER_ROOTS
RUNNER_TOOL_CACHE = d112.RUNNER_TOOL_CACHE
EXACT_PYTHON_ROOT = d112.EXACT_PYTHON_ROOT
EXACT_PYTHON_LIBRARY_PATH = d112.EXACT_PYTHON_LIBRARY_PATH
PYTHON_TOOLCACHE_COMPLETE_PATH = d112.PYTHON_TOOLCACHE_COMPLETE_PATH
PYTHON_TOOLCACHE_COMPLETE_BYTES = d112.PYTHON_TOOLCACHE_COMPLETE_BYTES
PYTHON_TOOLCACHE_COMPLETE_SHA256 = d112.PYTHON_TOOLCACHE_COMPLETE_SHA256
RUNNER_PACKAGE_VERSION = d112.RUNNER_PACKAGE_VERSION
RUNNER_PACKAGE_ARCHIVE_PATH = d112.RUNNER_PACKAGE_ARCHIVE_PATH
RUNNER_PACKAGE_ARCHIVE_BYTES = d112.RUNNER_PACKAGE_ARCHIVE_BYTES
RUNNER_PACKAGE_ARCHIVE_SHA256 = d112.RUNNER_PACKAGE_ARCHIVE_SHA256
RUNNER_LISTENER_BYTES = d112.RUNNER_LISTENER_BYTES
RUNNER_LISTENER_SHA256 = d112.RUNNER_LISTENER_SHA256
REQUIRED_RUNNER_LABELS = d112.REQUIRED_RUNNER_LABELS
STALE_RUNNER_ROOTS = d112.STALE_RUNNER_ROOTS
MINIMUM_RUNNER_DISK_BYTES = d112.MINIMUM_RUNNER_DISK_BYTES
MAXIMUM_RUNNER_READINESS_AGE_SECONDS = d112.MAXIMUM_RUNNER_READINESS_AGE_SECONDS
MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS = d112.MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS
BENCHMARK_EXEC_RUNNER_BOUNDARY = d112.BENCHMARK_EXEC_RUNNER_BOUNDARY
DOCKER_CLIENT_PATH = d112.DOCKER_CLIENT_PATH
DOCKER_CLIENT_BYTES = d112.DOCKER_CLIENT_BYTES
DOCKER_CLIENT_SHA256 = d112.DOCKER_CLIENT_SHA256
DOCKER_VERSION = d112.DOCKER_VERSION
DOCKER_ROOT_DIRECTORY = d112.DOCKER_ROOT_DIRECTORY
SERVICE_PORTS = d112.SERVICE_PORTS
SERVICE_IMAGE_REFS = d112.SERVICE_IMAGE_REFS
SERVICE_STATE_SCHEMA = d112.SERVICE_STATE_SCHEMA
SERVICE_STATE_FILENAME = d112.SERVICE_STATE_FILENAME
SERVICE_CONTAINER_NAME_PREFIX = d112.SERVICE_CONTAINER_NAME_PREFIX
RUNNER_SERVICE_UID = d112.RUNNER_SERVICE_UID
RUNNER_SERVICE_GID = d112.RUNNER_SERVICE_GID

GH_CLI_LOCK_PATH = d112.GH_CLI_LOCK_PATH
BENCHMARK_ENVIRONMENT_LOCK_PATH = d112.BENCHMARK_ENVIRONMENT_LOCK_PATH
HEX40 = d112.HEX40

DevelopmentTriggerError = d112.DevelopmentTriggerError
DevelopmentTriggerD113Error = DevelopmentTriggerError
require = d112.require
canonical_bytes = d112.canonical_bytes
strict_json = d112.strict_json
git = d112.git
commit_bytes = d112.commit_bytes
resolve_repository_root = d112.resolve_repository_root
_is_ancestor = d112._is_ancestor
_sha256_at = d112._sha256_at
_validate_secret_free_branch_environment = d112._validate_secret_free_branch_environment
_validate_unique_execution_run = d112._validate_unique_execution_run
_pinned_gh_context = d112._pinned_gh_context
_collect_current_pull_request = d112._collect_current_pull_request
_collect_remote_gate_rows = d112._collect_remote_gate_rows
_require_no_pending_benchmark_consumers = d112._require_no_pending_benchmark_consumers


# D1.13 is a control-plane repair.  The allowlist is explicit and excludes all
# model, prompt, target, arm, grader, and pricing inputs.
ALLOWED_RECOVERY_PATHS = frozenset(
    {
        ".gitattributes",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem.yml",
        EXPECTED_WORKFLOW_PATH,
        AMENDMENT_PATH,
        INVENTORY_PATH,
        PREVIOUS_FAILURE_FIXTURE_PATH,
        FREEZE_PATH,
        "artifacts/trimem_v1/readiness_requirements.json",
        REPORT_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        GATE_CONTRACT_PATH,
        RESEAL_PATH,
        "scripts/trimem_development_trigger_d113.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d113_e1_trigger.py",
        "tests/unit/test_trimem_d113_gate_contract.py",
        "tests/unit/test_trimem_d113_status_and_reseal.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    }
)
REQUIRED_RECOVERY_CHANGES = {
    ".gitattributes": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/ci-trimem.yml": "M",
    EXPECTED_WORKFLOW_PATH: "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    PREVIOUS_FAILURE_FIXTURE_PATH: "A",
    FREEZE_PATH: "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    REPORT_PATH: "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    GATE_CONTRACT_PATH: "A",
    RESEAL_PATH: "A",
    "scripts/trimem_development_trigger_d113.py": "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d113_e1_trigger.py": "A",
    "tests/unit/test_trimem_d113_gate_contract.py": "A",
    "tests/unit/test_trimem_d113_status_and_reseal.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}
# Compatibility names used by existing freeze and audit tooling.
ALLOWED_ACTIVATION_PATHS = ALLOWED_RECOVERY_PATHS
REQUIRED_ACTIVATION_CHANGES = REQUIRED_RECOVERY_CHANGES

ACTIVATION_BINDING_PATHS = {
    "gitattributes_sha256": ".gitattributes",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "d113_amendment_sha256": AMENDMENT_PATH,
    "d113_gate_contract_sha256": GATE_CONTRACT_PATH,
    "d113_inventory_sha256": INVENTORY_PATH,
    "d113_reseal_sha256": RESEAL_PATH,
    "d113_run_fixture_sha256": PREVIOUS_FAILURE_FIXTURE_PATH,
    "readiness_requirements_sha256": "artifacts/trimem_v1/readiness_requirements.json",
    "trigger_reader_sha256": "scripts/trimem_development_trigger_d113.py",
    "verify_ready_sha256": "scripts/trimem_verify_ready.py",
}


def _runtime_overrides() -> dict[str, Any]:
    """Return D1.13 bindings late, after all custom functions are defined."""

    return {
        "STARTING_SOURCE_HEAD": STARTING_SOURCE_HEAD,
        "STARTING_FREEZE_SHA256": STARTING_FREEZE_SHA256,
        "BASELINE_SOURCE_HEAD": BASELINE_SOURCE_HEAD,
        "BASELINE_FREEZE_SHA256": BASELINE_FREEZE_SHA256,
        "REQUEST_ID": REQUEST_ID,
        "REQUEST_SCHEMA": REQUEST_SCHEMA,
        "SENTINEL_PATH": SENTINEL_PATH,
        "ACTIVE_SENTINEL_PATH": ACTIVE_SENTINEL_PATH,
        "CURRENT_ACTIVE_WORKFLOW_REF": CURRENT_ACTIVE_WORKFLOW_REF,
        "PREVIOUS_SENTINEL_PATH": PREVIOUS_SENTINEL_PATH,
        "PREVIOUS_SENTINEL_SHA256": PREVIOUS_SENTINEL_SHA256,
        "PREVIOUS_REQUEST_PAYLOAD_SHA256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "PREVIOUS_SOURCE_HEAD": PREVIOUS_SOURCE_HEAD,
        "PREVIOUS_EXECUTION_HEAD": PREVIOUS_EXECUTION_HEAD,
        "PREVIOUS_RUN_ID": PREVIOUS_RUN_ID,
        "PREVIOUS_FAILURE_SUBTYPE": PREVIOUS_FAILURE_SUBTYPE,
        "REQUIRED_EXTERNAL_AUTHORIZATION": REQUIRED_EXTERNAL_AUTHORIZATION,
        "EXPECTED_CONCURRENCY_GROUP": EXPECTED_CONCURRENCY_GROUP,
        "AMENDMENT_PATH": AMENDMENT_PATH,
        "AMENDMENT_SCHEMA": AMENDMENT_SCHEMA,
        "INVENTORY_PATH": INVENTORY_PATH,
        "INVENTORY_SCHEMA": INVENTORY_SCHEMA,
        "AMENDMENT_CLASSIFICATION": AMENDMENT_CLASSIFICATION,
        "AMENDMENT_STATUS": AMENDMENT_STATUS,
        "AMENDMENT_ENDPOINT": AMENDMENT_ENDPOINT,
        "REMOTE_GATE_SCHEMA": REMOTE_GATE_SCHEMA,
        "RUNNER_READINESS_SCHEMA": RUNNER_READINESS_SCHEMA,
        "ALLOWED_ACTIVATION_PATHS": ALLOWED_ACTIVATION_PATHS,
        "REQUIRED_ACTIVATION_CHANGES": REQUIRED_ACTIVATION_CHANGES,
        "ACTIVATION_BINDING_PATHS": ACTIVATION_BINDING_PATHS,
        "_validate_source": _validate_source_impl,
        "build_request": _build_request_impl,
        "validate_request": _validate_request_impl,
        "validate_sentinel_commit": _validate_sentinel_commit_impl,
        "validate_branch_trigger": _validate_branch_trigger_impl,
    }


_D112_CONTEXT_LOCK = threading.RLock()


@contextmanager
def _d113_runtime_context() -> Iterator[None]:
    """Temporarily bind D1.12 runtime code to D1.13, restoring every name."""

    with _D112_CONTEXT_LOCK:
        overrides = _runtime_overrides()
        previous = {name: getattr(d112, name) for name in overrides}
        try:
            for name, value in overrides.items():
                setattr(d112, name, value)
            yield
        finally:
            for name, value in previous.items():
                setattr(d112, name, value)


def _tree_entry(repository: Path, commit: str, path: str) -> tuple[str, str]:
    raw = git(repository, "ls-tree", "--full-tree", commit, "--", path).strip()
    pieces = raw.split("\t", 1)
    require(len(pieces) == 2 and pieces[1] == path, f"Git tree path differs: {path}")
    metadata = pieces[0].split()
    require(len(metadata) == 3 and metadata[1] == "blob", f"Git blob differs: {path}")
    return metadata[0], metadata[2]


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    """Pin the _012 commit graph, blob bytes, source, and self-hash."""

    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip() == "commit",
        "immutable _012 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _012 execution parent differs",
    )
    changes = git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        PREVIOUS_EXECUTION_HEAD,
    ).splitlines()
    require(
        changes == [f"A\t{PREVIOUS_SENTINEL_PATH}"],
        "immutable _012 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(
        repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH
    )
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _012 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and b"\r" not in raw,
        "immutable _012 sentinel raw bytes differ",
    )
    previous = strict_json(raw)
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.12"
        and previous.get("request_id")
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012"
        and previous.get("request_path") == PREVIOUS_SENTINEL_PATH
        and previous.get("source_head") == PREVIOUS_SOURCE_HEAD
        and previous.get("request_sha256")
        == "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
        and raw == canonical_bytes(previous, trailing_lf=True),
        "immutable _012 request identity or canonical bytes differ",
    )
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.13 source does not preserve immutable EXEC _012",
    )
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical _012 request changed after execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_013 exists in recovery-source history",
    )
    return previous


def _validate_previous_run_fixture(repository: Path, source_head: str) -> dict[str, Any]:
    raw = commit_bytes(repository, source_head, PREVIOUS_FAILURE_FIXTURE_PATH)
    value = strict_json(raw)
    require(
        not raw.startswith(b"\xef\xbb\xbf")
        and b"\x00" not in raw
        and b"\r" not in raw
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and raw
        == json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        + b"\n",
        "EXEC _012 failure fixture is not canonical pretty UTF-8 plus one LF",
    )
    # The dedicated contract owns every allowlisted API/job/step field and all
    # projection digests.  Keeping that exact validator as the source of truth
    # avoids a permissive second parser here.
    try:
        import trimem_d113_gate_contract as gate_contract

        replay = gate_contract.validate_fixture(value)
    except Exception as exc:
        raise DevelopmentTriggerError(
            "EXEC _012 failure fixture rejected by D1.13 gate contract"
        ) from exc
    require(
        replay.get("status") == "PASS"
        and replay.get("execution_run_id") == PREVIOUS_RUN_ID
        and replay.get("execution_run_attempt") == PREVIOUS_RUN_ATTEMPT,
        "EXEC _012 failure replay identity differs",
    )
    workflow = value.get("workflow_run")
    boundary = value.get("boundary")
    failure = value.get("failed_log_summary")
    digests = value.get("digests")
    actuals = value.get("actuals")
    jobs = value.get("jobs")
    require(
        value.get("schema") == "trimem/d113-exec-012-preprotected-failure/1.0"
        and value.get("repository") == EXPECTED_REPOSITORY
        and value.get("branch") == EXPECTED_BRANCH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("execution_head") == PREVIOUS_EXECUTION_HEAD,
        "EXEC _012 failure fixture identity differs",
    )
    require(
        isinstance(workflow, Mapping)
        and workflow.get("id") == PREVIOUS_RUN_ID
        and workflow.get("run_attempt") == PREVIOUS_RUN_ATTEMPT
        and workflow.get("event") == "push"
        and workflow.get("head_sha") == PREVIOUS_EXECUTION_HEAD
        and workflow.get("path") == EXPECTED_WORKFLOW_PATH
        and workflow.get("status") == "completed"
        and workflow.get("conclusion") == "failure",
        "EXEC _012 workflow-run history differs",
    )
    require(
        isinstance(boundary, Mapping)
        and boundary.get("branch_trigger_preflight_entered") is True
        and boundary.get("bounded_context_preflight_entered") is False
        and boundary.get("frozen_serial_phase_entered") is False
        and boundary.get("protected_environment_approval_requested") is False
        and boundary.get("protected_environment_entered") is False
        and boundary.get("self_hosted_job_assignments") == 0,
        "EXEC _012 pre-protected boundary differs",
    )
    require(
        isinstance(failure, Mapping)
        and failure.get("failure_classification")
        == PREVIOUS_FAILURE_CLASSIFICATION
        and failure.get("failure_message") == PREVIOUS_FAILURE_MESSAGE
        and failure.get("failed_job") == "branch-trigger-preflight"
        and failure.get("failed_step") == "Verify one-time zero-authority DEV trigger"
        and failure.get("process_exit_code") == 1,
        "EXEC _012 failure location differs",
    )
    require(
        isinstance(digests, Mapping)
        and digests.get("request_raw_sha256") == PREVIOUS_SENTINEL_SHA256
        and digests.get("request_self_hash_sha256")
        == PREVIOUS_REQUEST_PAYLOAD_SHA256
        and digests.get("source_freeze_sha256") == PREVIOUS_SOURCE_FREEZE_SHA256,
        "EXEC _012 frozen digest evidence differs",
    )
    expected_actuals = {
        "benchmark_image_pulls": 0,
        "grader_containers": 0,
        "input_tokens": 0,
        "model_api_calls": 0,
        "model_generation_calls": 0,
        "model_metadata_requests": 0,
        "official_grader_runs": 0,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "task_arm_runs": 0,
        "terminal_cells": 0,
        "total_usd": 0.0,
    }
    require(actuals == expected_actuals, "EXEC _012 failure fixture is not zero-use")
    require(
        isinstance(jobs, list)
        and [(row.get("name"), row.get("conclusion")) for row in jobs]
        == [
            ("branch-trigger-preflight", "failure"),
            ("bounded-context-preflight", "skipped"),
            ("frozen-serial-phase", "skipped"),
        ],
        "EXEC _012 workflow job funnel differs",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    require(
        source_head != PREVIOUS_EXECUTION_HEAD
        and _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.13 source is not a strict descendant of immutable EXEC _012",
    )
    lines = git(
        repository,
        "diff",
        "--no-ext-diff",
        "--name-status",
        "--no-renames",
        PREVIOUS_EXECUTION_HEAD,
        source_head,
    ).splitlines()
    changes: dict[str, str] = {}
    for line in lines:
        pieces = line.split("\t")
        require(len(pieces) == 2, "D1.13 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.13 diff status is forbidden: {status}")
        require(path in ALLOWED_RECOVERY_PATHS, f"D1.13 changed forbidden path: {path}")
        require(path not in changes, f"D1.13 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.13 recovery change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path),
            f"frozen scientific input changed during D1.13 recovery: {path}",
        )


def _validate_workflow(repository: Path, source_head: str) -> None:
    try:
        workflow = commit_bytes(repository, source_head, EXPECTED_WORKFLOW_PATH).decode(
            "utf-8", errors="strict"
        )
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError("benchmark workflow is not UTF-8") from exc
    require(
        workflow.count(f"      - {SENTINEL_PATH}\n") == 1
        and f"      - {PREVIOUS_SENTINEL_PATH}\n" not in workflow,
        "active push sentinel is not exclusively _013",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-012" not in workflow,
        "_013 concurrency identity differs",
    )
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        all(workflow.count(marker) == 1 for marker in (branch_marker, bounded_marker, frozen_marker)),
        "D1.13 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(branch_start < bounded_start < frozen_start, "D1.13 job order differs")
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    command = "python -I -S scripts/trimem_development_trigger_d113.py"
    require(
        branch_job.count(command) == 1
        and bounded_job.count(command) == 1
        and frozen_job.count(command) == 4
        and "python -I -S scripts/trimem_development_trigger_d112.py" not in workflow,
        "active trigger validator is not exclusively D1.13 _013",
    )
    exact_selector = (
        "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, trimem-benchmark]"
    )
    require(
        "runs-on: ubuntu-24.04" in branch_job
        and exact_selector not in branch_job
        and exact_selector in bounded_job
        and exact_selector in frozen_job
        and "environment:" not in workflow[:frozen_start]
        and frozen_job.count("environment: trimem-benchmark-exec") == 1
        and "secrets." not in workflow[:frozen_start]
        and workflow.count("github.run_attempt == 1") >= 2,
        "D1.13 hosted/self-hosted/protected boundary differs",
    )
    for action, digest in (
        ("actions/checkout", CHECKOUT_ACTION_SHA),
        ("actions/setup-python", SETUP_PYTHON_ACTION_SHA),
    ):
        require(
            f"{action}@v" not in workflow and f"{action}@{digest}" in workflow,
            f"D1.13 workflow action is mutable: {action}",
        )


def _freeze_entry(
    repository: Path, source_head: str, files: Mapping[str, Any], path: str
) -> str:
    raw = commit_bytes(repository, source_head, path)
    digest = hashlib.sha256(raw).hexdigest()
    require(
        files.get(path) == {"bytes": len(raw), "sha256": digest},
        f"D1.13 freeze does not bind path: {path}",
    )
    return "sha256:" + digest


def _validate_freeze_and_bindings(
    repository: Path, source_head: str, previous: Mapping[str, Any]
) -> dict[str, Any]:
    freeze_raw = commit_bytes(repository, source_head, FREEZE_PATH)
    freeze = strict_json(freeze_raw)
    files = freeze.get("files")
    require(
        freeze.get("schema") == FREEZE_SCHEMA and isinstance(files, Mapping),
        "D1.13 research freeze is malformed",
    )
    require(SENTINEL_PATH not in files, "_013 entered its source freeze")
    old_raw = commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH)
    require(
        files.get(PREVIOUS_SENTINEL_PATH)
        == {"bytes": PREVIOUS_SENTINEL_BYTES, "sha256": PREVIOUS_SENTINEL_SHA256}
        and hashlib.sha256(old_raw).hexdigest() == PREVIOUS_SENTINEL_SHA256,
        "D1.13 freeze does not preserve immutable _012",
    )
    previous_bindings = previous.get("bindings")
    require(isinstance(previous_bindings, Mapping), "immutable _012 bindings malformed")
    bindings = deepcopy(dict(previous_bindings))
    bindings["freeze_sha256"] = "sha256:" + hashlib.sha256(freeze_raw).hexdigest()
    for name, path in SCIENCE_BINDING_PATHS.items():
        observed = _freeze_entry(repository, source_head, files, path)
        require(
            observed == previous_bindings.get(name),
            f"scientific binding changed after EXEC _012: {name}",
        )
        bindings[name] = observed
    for name, path in ACTIVATION_BINDING_PATHS.items():
        bindings[name] = _freeze_entry(repository, source_head, files, path)
    for name, path in EXECUTION_CONTRACT_PATHS.items():
        bindings[name] = _freeze_entry(repository, source_head, files, path)
    bindings["remote_gate_workflow_blob_sha256"] = {
        path: _freeze_entry(repository, source_head, files, path)
        for path in REQUIRED_REMOTE_GATE_WORKFLOWS
    }
    for path in REQUIRED_RECOVERY_CHANGES:
        if path != FREEZE_PATH:
            _freeze_entry(repository, source_head, files, path)
    bindings["previous_request_raw_sha256"] = "sha256:" + PREVIOUS_SENTINEL_SHA256
    bindings["previous_request_payload_sha256"] = (
        "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
    )
    return bindings


def _validate_documents(repository: Path, source_head: str) -> None:
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
        and inventory.get("source_changed_paths")
        == list(sorted(REQUIRED_RECOVERY_CHANGES)),
        "D1.13 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_012_attempt_one_consumed") is True
        and authority.get("request_012_rerun_allowed") is False
        and authority.get("request_013_request_creation_authorized") is True
        and authority.get("request_013_created_in_source") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_013_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.13 authority boundary differs",
    )


def _validate_source_impl(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    require(
        git(repository, "cat-file", "-t", source_head).strip() == "commit",
        "source HEAD is not a commit",
    )
    changes = _validate_recovery_diff(repository, source_head)
    previous = _load_previous_request(repository, source_head)
    failure = _validate_previous_run_fixture(repository, source_head)
    _validate_preserved_science(repository, source_head)
    _validate_workflow(repository, source_head)
    d112._validate_remote_gate_workflow_contracts(repository, source_head)
    _validate_documents(repository, source_head)
    target_order, hard_cap = d112._validate_frozen_science_documents(
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
        "scientific identity differs from immutable _012",
    )
    bindings = _validate_freeze_and_bindings(
        repository, source_head, previous
    )
    return {
        "activation_changes": changes,
        "bindings": bindings,
        "failure_fixture": failure,
        "hard_cap": hard_cap,
        "previous_request": previous,
        "target_order": target_order,
    }


def _validate_source(repository: Path, source_head: str) -> dict[str, Any]:
    return _validate_source_impl(repository, source_head)


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
    validated = _validate_source_impl(repository, selected)
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


validate_activation_source = validate_correction_source


def _validate_remote_gate_evidence(
    evidence: Any, *, source_head: str
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112._validate_remote_gate_evidence(evidence, source_head=source_head)


def _validate_runner_readiness(
    evidence: Any, *, source_head: str
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112._validate_runner_readiness(evidence, source_head=source_head)


def _validate_runner_readiness_freshness(
    evidence: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    with _d113_runtime_context():
        d112._validate_runner_readiness_freshness(evidence, now=now)


def _request_execution_contracts(bindings: Mapping[str, Any]) -> dict[str, Any]:
    result = d112._request_execution_contracts(bindings)
    order = result.get("required_order")
    require(isinstance(order, list), "execution contract order is malformed")
    result["required_order"] = [
        "D1.13 recovery-bound cell-terminal roundtrip"
        if row == "D1.12 activation-bound cell-terminal roundtrip"
        else row
        for row in order
    ]
    return result


def _build_request_impl(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    validated = _validate_source_impl(repository, source_head)
    gates = _validate_remote_gate_evidence(remote_gate_evidence, source_head=source_head)
    readiness = _validate_runner_readiness(runner_readiness, source_head=source_head)
    previous = validated["previous_request"]
    for name in ("control_plane", "exact_model", "scientific_workload"):
        require(isinstance(previous.get(name), Mapping), f"immutable _012 {name} malformed")
    bindings = validated["bindings"]
    payload = {
        "actual_execution_authorized": False,
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "amendment_classification": AMENDMENT_CLASSIFICATION,
        "authorization_semantics": (
            "This sentinel creates one push run only. Protected execution requires "
            "one distinct approval bound to the sentinel commit, recovery source, "
            "freeze, request bytes, workflow run ID/attempt, caps, actor, timestamp, "
            "nonce, legal acceptance, and exact OpenAI-key commitment."
        ),
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "control_plane": deepcopy(dict(previous["control_plane"])),
        "d113_execution_contracts": _request_execution_contracts(bindings),
        "exact_model": deepcopy(dict(previous["exact_model"])),
        "external_execution_approval_received": False,
        "hard_caps": validated["hard_cap"],
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
            "DEVELOPMENT_TUNING_EXEC_REQUEST_012_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_014",
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
            "bounded_context_preflight_entered": False,
            "completed_terminal_cells": 0,
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "failure_classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "grader_containers": 0,
            "grader_state": "NOT_STARTED_BEFORE_PROTECTED_ENVIRONMENT",
            "model_api_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_payload_sha256": (
                "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
            ),
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "previous_source_head": PREVIOUS_SOURCE_HEAD,
            "protected_environment_entered": False,
            "self_hosted_job_assignments": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "remote_gate_evidence": gates,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "required_external_approval_fields": list(DEVELOPMENT_APPROVAL_FIELDS),
        "required_external_authorization": REQUIRED_EXTERNAL_AUTHORIZATION,
        "requires_external_approval": True,
        "runner_readiness": readiness,
        "schema": REQUEST_SCHEMA,
        "scientific_workload": deepcopy(dict(previous["scientific_workload"])),
        "source_head": source_head,
        "workflow_path": EXPECTED_WORKFLOW_PATH,
    }
    return {
        **payload,
        "request_sha256": "sha256:"
        + hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def build_request(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    return _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=remote_gate_evidence,
        runner_readiness=runner_readiness,
    )


def _validate_request_impl(
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
    expected = _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
    )
    require(value == expected, "_013 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_013 request bytes are not canonical UTF-8 plus one LF",
    )
    return value


def validate_request(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    return _validate_request_impl(repository, raw, source_head=source_head)


def _validate_sentinel_commit_impl(
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
        "trigger commit is not the exclusive _013 sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "_013 sentinel is not a regular non-executable blob")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_013 already exists before the trigger commit",
    )
    return _validate_request_impl(
        repository, commit_bytes(repository, after, SENTINEL_PATH), source_head=parent
    )


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    return _validate_sentinel_commit_impl(
        repository,
        after,
        expected_parent=expected_parent,
        require_checked_out_head=require_checked_out_head,
    )


def _validate_branch_trigger_impl(
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
    require(environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY, "repository differs")
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
    with _d113_runtime_context():
        execution_run = _validate_unique_execution_run(after, environment)
    request = _validate_sentinel_commit_impl(
        repository, after, expected_parent=before, require_checked_out_head=True
    )
    _validate_runner_readiness_freshness(request["runner_readiness"])
    gh, safe_environment = _pinned_gh_context()
    _collect_current_pull_request(
        gh, safe_environment, expected_head=after, allowed_stale_head=before
    )
    live_rows = _collect_remote_gate_rows(gh, safe_environment, source_head=before)
    require(
        request.get("remote_gate_evidence", {}).get("workflows") == live_rows,
        "embedded remote gates differ from current exact remote runs",
    )
    # Deliberately no repository-runners endpoint call here.  The embedded
    # evidence was admin-observed by write_request; freshness is bounded above,
    # and both subsequent self-hosted jobs prove the live local identities.
    return {
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "execution_run": execution_run,
        "request_id": REQUEST_ID,
        "runner_readiness_authority": "FRESH_EMBEDDED_PREREGISTRATION",
        "source_head": before,
        "status": "PASS",
        "trigger_commit": after,
    }


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return _validate_branch_trigger_impl(repository, event_path, environ=environ)


def collect_remote_gate_evidence(
    source_head: str,
    *,
    allowed_stale_pr_head: str | None = None,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.collect_remote_gate_evidence(
            source_head,
            allowed_stale_pr_head=allowed_stale_pr_head,
            _observer_context=_observer_context,
        )


def collect_remote_runner_rows() -> list[dict[str, Any]]:
    with _d113_runtime_context():
        return d112.collect_remote_runner_rows()


def collect_runner_readiness(
    repository: Path,
    source_head: str,
    *,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.collect_runner_readiness(
            repository, source_head, _observer_context=_observer_context
        )


def collect_local_runner_host_readiness(
    repository: Path,
    source_head: str,
    expected_readiness: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.collect_local_runner_host_readiness(
            repository, source_head, expected_readiness, environ=environ
        )


def validate_runner_host_preflight(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.validate_runner_host_preflight(
            repository, event_path, environ=environ, now=now
        )


def validate_pre_setup_cache_host(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.validate_pre_setup_cache_host(
            repository, event_path, environ=environ, now=now
        )


def collect_protected_runner_readiness(
    repository: Path,
    source_head: str,
    trigger_head: str,
    run_id: int,
    expected_readiness: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.collect_protected_runner_readiness(
            repository,
            source_head,
            trigger_head,
            run_id,
            expected_readiness,
            environ=environ,
        )


def validate_protected_runner_preflight(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.validate_protected_runner_preflight(
            repository, event_path, environ=environ, now=now
        )


def start_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.start_protected_services(repository, event_path, environ=environ)


def verify_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    _monotonic: Any = None,
    _sleep: Any = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.verify_protected_services(
            repository,
            event_path,
            environ=environ,
            _monotonic=_monotonic,
            _sleep=_sleep,
        )


def cleanup_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d113_runtime_context():
        return d112.cleanup_protected_services(repository, event_path, environ=environ)


def _recheck_request_write_boundary(
    repository: Path, source_head: str, target: Path
) -> None:
    expected_target = repository / Path(*PurePosixPath(SENTINEL_PATH).parts)
    require(target == expected_target, "request write target escaped the repository")
    require(
        target.parent.is_dir()
        and not target.parent.is_symlink()
        and target.parent.resolve(strict=True) == target.parent,
        "request write parent is not the exact repository directory",
    )
    require(
        git(repository, "symbolic-ref", "--quiet", "HEAD").strip() == EXPECTED_REF,
        "request rendering branch changed before the exclusive write",
    )
    require(
        git(repository, "rev-parse", "HEAD").strip() == source_head,
        "request rendering HEAD changed before the exclusive write",
    )
    require(
        not git(repository, "status", "--porcelain=v1", "--untracked-files=all").strip(),
        "request rendering worktree changed before the exclusive write",
    )
    require(not os.path.lexists(target), "_013 sentinel appeared before exclusive write")
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_013 entered Git history before the exclusive write",
    )


def write_request(repository: Path) -> dict[str, Any]:
    """Create _013; this is the sole path that performs admin runner lookup."""

    repository = resolve_repository_root(repository)
    _validate_secret_free_branch_environment(os.environ)
    require(
        git(repository, "symbolic-ref", "--quiet", "HEAD").strip() == EXPECTED_REF,
        "request rendering is on the wrong branch",
    )
    require(
        not git(repository, "status", "--porcelain=v1", "--untracked-files=all").strip(),
        "request rendering requires a clean worktree",
    )
    source_head = git(repository, "rev-parse", "HEAD").strip()
    target = repository / Path(*PurePosixPath(SENTINEL_PATH).parts)
    require(not os.path.lexists(target), "_013 sentinel already exists in worktree")
    _validate_source_impl(repository, source_head)
    observer_context = _pinned_gh_context()
    _require_no_pending_benchmark_consumers(*observer_context)
    gates = collect_remote_gate_evidence(
        source_head,
        allowed_stale_pr_head=None,
        _observer_context=observer_context,
    )
    # This call intentionally retains D1.12's admin repository-runners
    # collection and exact local WSL host corroboration.
    readiness = collect_runner_readiness(
        repository, source_head, _observer_context=observer_context
    )
    document = _build_request_impl(
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
        raise DevelopmentTriggerError(
            "_013 sentinel could not be created exclusively"
        ) from exc
    return {
        "bytes": len(raw),
        "path": SENTINEL_PATH,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_head": source_head,
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
    }


def __getattr__(name: str) -> Any:
    """Expose unchanged D1.12 constants/helpers without copying runtime code."""

    return getattr(d112, name)


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
                args.repository, args.runner_host_preflight_event_path
            )
        elif args.pre_setup_cache_host_event_path is not None:
            result = validate_pre_setup_cache_host(
                args.repository, args.pre_setup_cache_host_event_path
            )
        elif args.protected_runner_preflight_event_path is not None:
            result = validate_protected_runner_preflight(
                args.repository, args.protected_runner_preflight_event_path
            )
        elif args.start_protected_services_event_path is not None:
            result = start_protected_services(
                args.repository, args.start_protected_services_event_path
            )
        elif args.verify_protected_services_event_path is not None:
            result = verify_protected_services(
                args.repository, args.verify_protected_services_event_path
            )
        elif args.cleanup_protected_services_event_path is not None:
            result = cleanup_protected_services(
                args.repository, args.cleanup_protected_services_event_path
            )
        elif args.validate_source:
            result = validate_correction_source(
                args.repository, args.source_head, require_checked_out_head=True
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
