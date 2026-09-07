"""Fail-closed one-time DEVELOPMENT_TUNING ``_015`` recovery trigger.

D1.15 preserves the spent ``_014`` request and its zero-model loader-preflight
failure as immutable Git history.  A new zero-authority request can be rendered
only after all exact-head gates, fresh runner observation, and a fresh full
self-hosted loader rehearsal have passed.  Importing this module has no network,
Docker, grader, credential, image, or model side effect.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import threading
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d114 as d114

d113 = d114.d113
d112 = d114.d112


EXPECTED_REPOSITORY = d114.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d114.EXPECTED_BRANCH
EXPECTED_REF = d114.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d114.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d114.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d114.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d114.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d114.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d114.EXPECTED_BASE_HEAD

PREVIOUS_SOURCE_HEAD = "6e9abe999f2b9d7ebdd3eea23dbbea8f6afad931"
PREVIOUS_EXECUTION_HEAD = "31234fdd58fd43170764524662c9e51687521761"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_014.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "7b4ff50e423cd12baea93413bbedcf7c2ee210d031fc20b30ad1c9d9f3c2dbaa"
)
PREVIOUS_SENTINEL_BYTES = 25_763
PREVIOUS_SENTINEL_BLOB_OID = "f240997fccf2b0ef54d38e093ea21843272c6f5f"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "e046c09ac2a40a4f5a819e8dc522074d20157ddd6201233de8c49e209451d353"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "19da74e3e4d217354c7b2483bf1a462da10867ebe62c995df72405f273847448"
)
PREVIOUS_RUN_ID = 34_147_189_320
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_FAILURE_SUBTYPE = "CACHED_PYTHON_SYSCONFIG_LIBDIR_ALIAS_ABSENT"
PREVIOUS_FAILURE_CLASSIFICATION = (
    "CACHED_PYTHON_SYSCONFIG_LIBDIR_RELOCATION_FAIL_CLOSED"
)
PREVIOUS_FAILURE_MESSAGE = "credential-free official-harness loader preflight failed"
PREVIOUS_FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d115/exec_014_loader_failure.json"
)

STARTING_SOURCE_HEAD = PREVIOUS_EXECUTION_HEAD
STARTING_FREEZE_SHA256 = PREVIOUS_SOURCE_FREEZE_SHA256
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.15"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_015.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-015"

AMENDMENT_PATH = "artifacts/trimem_v1/development_exec_015_recovery_amendment.json"
AMENDMENT_SCHEMA = "trimem/development-exec-015-recovery-amendment/1.0"
INVENTORY_PATH = "artifacts/trimem_v1/development_exec_015_recovery_inventory.json"
INVENTORY_SCHEMA = "trimem/development-exec-015-recovery-inventory/1.0"
AMENDMENT_CLASSIFICATION = (
    "POST_EXEC_014_ZERO_MODEL_CACHED_PYTHON_LIBDIR_ALIAS_RECOVERY"
)
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_014_FAILURE_READY_FOR_EXEC_015_REQUEST"
)
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_015_REQUEST"
REPORT_PATH = "reports/TRIMEM_D115_EXEC_015_RECOVERY.md"
GATE_CONTRACT_PATH = "scripts/trimem_d115_gate_contract.py"
RESEAL_PATH = "scripts/trimem_d115_reseal.py"
TRIGGER_PATH = "scripts/trimem_development_trigger_d115.py"
COMPILED_PREFIX_ALIAS_PATH = "scripts/trimem_compiled_prefix_alias.py"
LOADER_REHEARSAL_COLLECTOR_PATH = "scripts/trimem_d115_loader_rehearsal.py"

WSL_HOST_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "USERPROFILE",
    }
)
WSL_COLLECTOR_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

FREEZE_PATH = d114.FREEZE_PATH
FREEZE_SCHEMA = d114.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.15"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.15"
LOADER_REHEARSAL_SCHEMA = "trimem/d115-exact-loader-rehearsal/1.0"
COMPILED_PREFIX_ALIAS_SCHEMA = "trimem/compiled-prefix-alias/1.0"

MODEL_ID = d114.MODEL_ID
REASONING_EFFORT = d114.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d114.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d114.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d114.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d114.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d114.ACTIVATION_ZERO_COUNTERS
REMOTE_GATE_SPECS = d114.REMOTE_GATE_SPECS
REQUIRED_REMOTE_GATE_WORKFLOWS = d114.REQUIRED_REMOTE_GATE_WORKFLOWS
PRESERVED_SCIENTIFIC_PATHS = d114.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d114.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d114.EXECUTION_CONTRACT_PATHS

CHECKOUT_ACTION_SHA = d114.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d114.SETUP_PYTHON_ACTION_SHA
CODEQL_ACTION_SHA = d114.CODEQL_ACTION_SHA
RUNNER_DISTRIBUTION = d114.RUNNER_DISTRIBUTION
RUNNER_WSL_USER = d114.RUNNER_WSL_USER
WSL_COLLECTOR_HOME = f"/home/{RUNNER_WSL_USER}"
RUNNER_NAMES = d114.RUNNER_NAMES
RUNNER_ROOTS = d114.RUNNER_ROOTS
RUNNER_TOOL_CACHE = d114.RUNNER_TOOL_CACHE
EXACT_PYTHON_ROOT = d114.EXACT_PYTHON_ROOT
EXACT_PYTHON_LIBRARY_PATH = d114.EXACT_PYTHON_LIBRARY_PATH
PYTHON_TOOLCACHE_COMPLETE_PATH = d114.PYTHON_TOOLCACHE_COMPLETE_PATH
PYTHON_TOOLCACHE_COMPLETE_BYTES = d114.PYTHON_TOOLCACHE_COMPLETE_BYTES
PYTHON_TOOLCACHE_COMPLETE_SHA256 = d114.PYTHON_TOOLCACHE_COMPLETE_SHA256
RUNNER_PACKAGE_VERSION = d114.RUNNER_PACKAGE_VERSION
RUNNER_PACKAGE_ARCHIVE_PATH = d114.RUNNER_PACKAGE_ARCHIVE_PATH
RUNNER_PACKAGE_ARCHIVE_BYTES = d114.RUNNER_PACKAGE_ARCHIVE_BYTES
RUNNER_PACKAGE_ARCHIVE_SHA256 = d114.RUNNER_PACKAGE_ARCHIVE_SHA256
RUNNER_LISTENER_BYTES = d114.RUNNER_LISTENER_BYTES
RUNNER_LISTENER_SHA256 = d114.RUNNER_LISTENER_SHA256
REQUIRED_RUNNER_LABELS = d114.REQUIRED_RUNNER_LABELS
STALE_RUNNER_ROOTS = d114.STALE_RUNNER_ROOTS
MINIMUM_RUNNER_DISK_BYTES = d114.MINIMUM_RUNNER_DISK_BYTES
MAXIMUM_RUNNER_READINESS_AGE_SECONDS = d114.MAXIMUM_RUNNER_READINESS_AGE_SECONDS
MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS = d114.MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS
BENCHMARK_EXEC_RUNNER_BOUNDARY = d114.BENCHMARK_EXEC_RUNNER_BOUNDARY
DOCKER_CLIENT_PATH = d114.DOCKER_CLIENT_PATH
DOCKER_CLIENT_BYTES = d114.DOCKER_CLIENT_BYTES
DOCKER_CLIENT_SHA256 = d114.DOCKER_CLIENT_SHA256
DOCKER_VERSION = d114.DOCKER_VERSION
DOCKER_ROOT_DIRECTORY = d114.DOCKER_ROOT_DIRECTORY
SERVICE_PORTS = d114.SERVICE_PORTS
SERVICE_IMAGE_REFS = d114.SERVICE_IMAGE_REFS
SERVICE_STATE_SCHEMA = d114.SERVICE_STATE_SCHEMA
SERVICE_STATE_FILENAME = d114.SERVICE_STATE_FILENAME
SERVICE_CONTAINER_NAME_PREFIX = d114.SERVICE_CONTAINER_NAME_PREFIX
RUNNER_SERVICE_UID = d114.RUNNER_SERVICE_UID
RUNNER_SERVICE_GID = d114.RUNNER_SERVICE_GID
GH_CLI_LOCK_PATH = d114.GH_CLI_LOCK_PATH
BENCHMARK_ENVIRONMENT_LOCK_PATH = d114.BENCHMARK_ENVIRONMENT_LOCK_PATH
HEX40 = d114.HEX40
HEX64 = re.compile(r"[0-9a-f]{64}\Z")

DevelopmentTriggerError = d114.DevelopmentTriggerError
DevelopmentTriggerD115Error = DevelopmentTriggerError
require = d114.require
canonical_bytes = d114.canonical_bytes
strict_json = d114.strict_json
git = d114.git
commit_bytes = d114.commit_bytes
resolve_repository_root = d114.resolve_repository_root
_is_ancestor = d114._is_ancestor
_sha256_at = d114._sha256_at
_validate_secret_free_branch_environment = d114._validate_secret_free_branch_environment
_pinned_gh_context = d114._pinned_gh_context
_require_no_pending_benchmark_consumers = d114._require_no_pending_benchmark_consumers

COMPILED_PREFIX_ALIAS = "/opt/hostedtoolcache"
COMPILED_PREFIX_ALIAS_TARGET = "/opt/trimem-runner-cache/work-ci/_tool"
OBSERVED_PYTHON_REAL_PREFIX = f"{COMPILED_PREFIX_ALIAS_TARGET}/Python/3.11.10/x64"
OBSERVED_SYSCONFIG_LIBDIR = f"{COMPILED_PREFIX_ALIAS}/Python/3.11.10/x64/lib"
ALIAS_CHECK_COMMAND = (
    '"$exact_python" -I -S scripts/trimem_compiled_prefix_alias.py --check'
)
LOADER_PREFLIGHT_COMMAND_FRAGMENT = (
    "scripts/trimem_official_harness_loader_preflight.py"
)

# This list is intentionally wider than REQUIRED_RECOVERY_CHANGES.  It permits
# active-validator and focused-test integration while still excluding every
# frozen model, prompt, target, arm, grader, image, pricing, and budget input.
ALLOWED_RECOVERY_PATHS = frozenset(
    {
        ".gitattributes",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem-grader-loader.yml",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/ci-trimem-e2e.yml",
        ".github/workflows/ci-trimem-harness-lock.yml",
        ".github/workflows/ci-trimem-multi-swe-contract.yml",
        EXPECTED_WORKFLOW_PATH,
        AMENDMENT_PATH,
        INVENTORY_PATH,
        PREVIOUS_FAILURE_FIXTURE_PATH,
        FREEZE_PATH,
        "artifacts/trimem_v1/readiness_requirements.json",
        REPORT_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        COMPILED_PREFIX_ALIAS_PATH,
        LOADER_REHEARSAL_COLLECTOR_PATH,
        GATE_CONTRACT_PATH,
        RESEAL_PATH,
        TRIGGER_PATH,
        "scripts/trimem_freeze.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d114_status_and_reseal.py",
        "tests/unit/test_trimem_d115_compiled_prefix_alias.py",
        "tests/unit/test_trimem_d115_gate_contract.py",
        "tests/unit/test_trimem_d115_status_and_reseal.py",
        "tests/unit/test_trimem_d115_trigger.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    }
)
REQUIRED_RECOVERY_CHANGES = {
    ".gitattributes": "M",
    EXPECTED_WORKFLOW_PATH: "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    PREVIOUS_FAILURE_FIXTURE_PATH: "A",
    FREEZE_PATH: "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    REPORT_PATH: "A",
    COMPILED_PREFIX_ALIAS_PATH: "A",
    LOADER_REHEARSAL_COLLECTOR_PATH: "A",
    GATE_CONTRACT_PATH: "A",
    RESEAL_PATH: "A",
    TRIGGER_PATH: "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_verify_ready.py": "M",
}
ALLOWED_ACTIVATION_PATHS = ALLOWED_RECOVERY_PATHS
REQUIRED_ACTIVATION_CHANGES = REQUIRED_RECOVERY_CHANGES

ACTIVATION_BINDING_PATHS = {
    "compiled_prefix_alias_sha256": COMPILED_PREFIX_ALIAS_PATH,
    "loader_rehearsal_collector_sha256": LOADER_REHEARSAL_COLLECTOR_PATH,
    "d115_amendment_sha256": AMENDMENT_PATH,
    "d115_gate_contract_sha256": GATE_CONTRACT_PATH,
    "d115_inventory_sha256": INVENTORY_PATH,
    "d115_reseal_sha256": RESEAL_PATH,
    "d115_run_fixture_sha256": PREVIOUS_FAILURE_FIXTURE_PATH,
    "readiness_requirements_sha256": "artifacts/trimem_v1/readiness_requirements.json",
    "trigger_reader_sha256": TRIGGER_PATH,
    "verify_ready_sha256": "scripts/trimem_verify_ready.py",
}


def _runtime_overrides() -> dict[str, Any]:
    """Return D1.15 bindings for the inherited D1.14/D1.13 adapters."""

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
        "PREVIOUS_SENTINEL_BYTES": PREVIOUS_SENTINEL_BYTES,
        "PREVIOUS_SENTINEL_BLOB_OID": PREVIOUS_SENTINEL_BLOB_OID,
        "PREVIOUS_REQUEST_PAYLOAD_SHA256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "PREVIOUS_SOURCE_FREEZE_SHA256": PREVIOUS_SOURCE_FREEZE_SHA256,
        "PREVIOUS_SOURCE_HEAD": PREVIOUS_SOURCE_HEAD,
        "PREVIOUS_EXECUTION_HEAD": PREVIOUS_EXECUTION_HEAD,
        "PREVIOUS_RUN_ID": PREVIOUS_RUN_ID,
        "PREVIOUS_RUN_ATTEMPT": PREVIOUS_RUN_ATTEMPT,
        "PREVIOUS_FAILURE_SUBTYPE": PREVIOUS_FAILURE_SUBTYPE,
        "PREVIOUS_FAILURE_CLASSIFICATION": PREVIOUS_FAILURE_CLASSIFICATION,
        "PREVIOUS_FAILURE_MESSAGE": PREVIOUS_FAILURE_MESSAGE,
        "PREVIOUS_FAILURE_FIXTURE_PATH": PREVIOUS_FAILURE_FIXTURE_PATH,
        "REQUIRED_EXTERNAL_AUTHORIZATION": REQUIRED_EXTERNAL_AUTHORIZATION,
        "EXPECTED_CONCURRENCY_GROUP": EXPECTED_CONCURRENCY_GROUP,
        "AMENDMENT_PATH": AMENDMENT_PATH,
        "AMENDMENT_SCHEMA": AMENDMENT_SCHEMA,
        "INVENTORY_PATH": INVENTORY_PATH,
        "INVENTORY_SCHEMA": INVENTORY_SCHEMA,
        "AMENDMENT_CLASSIFICATION": AMENDMENT_CLASSIFICATION,
        "AMENDMENT_STATUS": AMENDMENT_STATUS,
        "AMENDMENT_ENDPOINT": AMENDMENT_ENDPOINT,
        "REPORT_PATH": REPORT_PATH,
        "GATE_CONTRACT_PATH": GATE_CONTRACT_PATH,
        "RESEAL_PATH": RESEAL_PATH,
        "REMOTE_GATE_SCHEMA": REMOTE_GATE_SCHEMA,
        "REMOTE_GATE_SPECS": REMOTE_GATE_SPECS,
        "REQUIRED_REMOTE_GATE_WORKFLOWS": REQUIRED_REMOTE_GATE_WORKFLOWS,
        "RUNNER_READINESS_SCHEMA": RUNNER_READINESS_SCHEMA,
        "ALLOWED_RECOVERY_PATHS": ALLOWED_RECOVERY_PATHS,
        "REQUIRED_RECOVERY_CHANGES": REQUIRED_RECOVERY_CHANGES,
        "ALLOWED_ACTIVATION_PATHS": ALLOWED_ACTIVATION_PATHS,
        "REQUIRED_ACTIVATION_CHANGES": REQUIRED_ACTIVATION_CHANGES,
        "ACTIVATION_BINDING_PATHS": ACTIVATION_BINDING_PATHS,
        "_validate_source_impl": _validate_source_impl,
        "_validate_source": _validate_source_impl,
        "_build_request_impl": _build_request_impl,
        "build_request": build_request,
        "_validate_request_impl": _validate_request_impl,
        "validate_request": validate_request,
        "_validate_sentinel_commit_impl": _validate_sentinel_commit_impl,
        "validate_sentinel_commit": validate_sentinel_commit,
    }


_D114_CONTEXT_LOCK = threading.RLock()


@contextmanager
def _d115_runtime_context() -> Iterator[None]:
    """Bind D1.14 to D1.15 atomically, then restore it byte-for-byte."""

    with _D114_CONTEXT_LOCK, d114._D113_CONTEXT_LOCK, d113._D112_CONTEXT_LOCK:
        overrides = _runtime_overrides()
        names = {
            **overrides,
            "_runtime_overrides": _runtime_overrides,
            "_load_previous_request": _load_previous_request,
            "_load_failure_contract": _load_failure_contract,
            "_validate_previous_run_fixture": _validate_previous_run_fixture,
            "_validate_workflow": _validate_workflow,
            "_validate_documents": _validate_documents,
        }
        previous = {name: getattr(d114, name) for name in names}
        try:
            for name, value in names.items():
                setattr(d114, name, value)
            yield
        finally:
            for name, value in reversed(tuple(previous.items())):
                setattr(d114, name, value)


def _tree_entry(repository: Path, commit: str, path: str) -> tuple[str, str]:
    return d114._tree_entry(repository, commit, path)


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    """Pin the exact ``_014`` graph, raw blob, self-hash, and zero authority."""

    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _014 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _014 execution parent differs",
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
        "immutable _014 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _014 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and b"\r" not in raw,
        "immutable _014 sentinel raw bytes differ",
    )
    previous = strict_json(raw)
    bindings = previous.get("bindings")
    activation_actuals = previous.get("activation_actuals")
    pre_execution_actuals = previous.get("pre_execution_actuals")
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.14"
        and previous.get("request_id")
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
        and previous.get("request_path") == PREVIOUS_SENTINEL_PATH
        and previous.get("source_head") == PREVIOUS_SOURCE_HEAD
        and previous.get("request_sha256")
        == "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
        and previous.get("actual_execution_authorized") is False
        and previous.get("external_execution_approval_received") is False
        and isinstance(bindings, Mapping)
        and bindings.get("freeze_sha256")
        == "sha256:" + PREVIOUS_SOURCE_FREEZE_SHA256
        and isinstance(activation_actuals, Mapping)
        and all(value == 0 for value in activation_actuals.values())
        and isinstance(pre_execution_actuals, Mapping)
        and all(value == 0 for value in pre_execution_actuals.values())
        and raw == canonical_bytes(previous, trailing_lf=True),
        "immutable _014 request identity, bytes, or zero authority differs",
    )
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.15 source does not preserve immutable EXEC _014",
    )
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical _014 request changed after execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_015 exists in recovery-source history",
    )
    return previous


def _load_failure_contract() -> Any:
    return importlib.import_module("trimem_d115_gate_contract")


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
        == json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n",
        "EXEC _014 failure fixture is not canonical pretty UTF-8 plus one LF",
    )
    try:
        replay = _load_failure_contract().validate_fixture(value)
    except Exception as exc:
        raise DevelopmentTriggerError(
            "EXEC _014 failure fixture rejected by D1.15 gate contract"
        ) from exc
    require(
        replay.get("status") == "PASS"
        and replay.get("source_head") == PREVIOUS_SOURCE_HEAD
        and replay.get("execution_head") == PREVIOUS_EXECUTION_HEAD
        and replay.get("execution_run_id") == PREVIOUS_RUN_ID
        and replay.get("execution_run_attempt") == PREVIOUS_RUN_ATTEMPT
        and replay.get("protected_environment_entered") is False
        and replay.get("self_hosted_job_assignments") == 1,
        "EXEC _014 failure replay identity differs",
    )
    workflow = value.get("workflow_run")
    boundary = value.get("boundary")
    failure = value.get("failed_log_summary")
    digests = value.get("digests")
    actuals = value.get("actuals")
    jobs = value.get("jobs")
    require(
        value.get("schema") == "trimem/d115-exec-014-loader-failure/1.0"
        and value.get("repository") == EXPECTED_REPOSITORY
        and value.get("branch") == EXPECTED_BRANCH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("execution_head") == PREVIOUS_EXECUTION_HEAD,
        "EXEC _014 failure fixture identity differs",
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
        "EXEC _014 workflow-run history differs",
    )
    require(
        isinstance(boundary, Mapping)
        and boundary.get("branch_trigger_preflight_entered") is True
        and boundary.get("bounded_context_preflight_entered") is True
        and boundary.get("dependency_install_completed") is True
        and boundary.get("harness_materialization_completed") is True
        and boundary.get("official_harness_loader_preflight_entered") is True
        and boundary.get("frozen_serial_phase_entered") is False
        and boundary.get("protected_environment_approval_requested") is False
        and boundary.get("protected_environment_entered") is False
        and boundary.get("self_hosted_job_assignments") == 1,
        "EXEC _014 loader-preflight boundary differs",
    )
    require(
        isinstance(failure, Mapping)
        and failure.get("failure_classification")
        == PREVIOUS_FAILURE_CLASSIFICATION
        and failure.get("failure_subtype") == PREVIOUS_FAILURE_SUBTYPE
        and failure.get("failure_message") == PREVIOUS_FAILURE_MESSAGE
        and failure.get("failed_job") == "bounded-context-preflight"
        and failure.get("failed_step")
        == "Gate protected job on unprotected exact loader preflight"
        and failure.get("process_exit_code") == 1
        and failure.get("observed_python_real_prefix")
        == OBSERVED_PYTHON_REAL_PREFIX
        and failure.get("observed_sysconfig_libdir") == OBSERVED_SYSCONFIG_LIBDIR
        and failure.get("observed_sysconfig_libdir_exists") is False,
        "EXEC _014 failure location or compiled-prefix diagnostic differs",
    )
    require(
        isinstance(digests, Mapping)
        and digests.get("request_raw_sha256") == PREVIOUS_SENTINEL_SHA256
        and digests.get("request_self_hash_sha256")
        == PREVIOUS_REQUEST_PAYLOAD_SHA256
        and digests.get("source_freeze_sha256")
        == PREVIOUS_SOURCE_FREEZE_SHA256,
        "EXEC _014 frozen digest evidence differs",
    )
    require(
        isinstance(actuals, Mapping)
        and actuals.get("dependency_installations") == 1
        and actuals.get("harness_materializations") == 2
        and all(
            actuals.get(name) == 0
            for name in (
                "benchmark_image_pulls",
                "grader_containers",
                "input_tokens",
                "model_api_calls",
                "model_generation_calls",
                "model_metadata_requests",
                "official_grader_runs",
                "output_tokens",
                "paid_model_calls",
                "task_arm_runs",
                "terminal_cells",
                "total_usd",
            )
        ),
        "EXEC _014 fixture scientific/model/grader actuals are not zero",
    )
    require(
        isinstance(jobs, list)
        and [(row.get("name"), row.get("conclusion")) for row in jobs]
        == [
            ("branch-trigger-preflight", "success"),
            ("bounded-context-preflight", "failure"),
            ("frozen-serial-phase", "skipped"),
        ],
        "EXEC _014 workflow job funnel differs",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    require(
        source_head != PREVIOUS_EXECUTION_HEAD
        and _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.15 source is not a strict descendant of immutable EXEC _014",
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
        require(len(pieces) == 2, "D1.15 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.15 diff status is forbidden: {status}")
        require(path in ALLOWED_RECOVERY_PATHS, f"D1.15 changed forbidden path: {path}")
        require(path not in changes, f"D1.15 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.15 recovery change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path),
            f"frozen scientific input changed during D1.15 recovery: {path}",
        )


def _step_block(workflow: str, name: str) -> str:
    return d114._step_block(workflow, name)


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
        "active push sentinel is not exclusively _015",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-014" not in workflow,
        "_015 concurrency identity differs",
    )
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        all(
            workflow.count(marker) == 1
            for marker in (branch_marker, bounded_marker, frozen_marker)
        ),
        "D1.15 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(branch_start < bounded_start < frozen_start, "D1.15 job order differs")
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    command = "python -I -S scripts/trimem_development_trigger_d115.py"
    require(
        branch_job.count(command) == 1
        and bounded_job.count(command) == 1
        and frozen_job.count(command) == 4
        and "scripts/trimem_development_trigger_d114.py" not in workflow,
        "active trigger validator is not exclusively D1.15 _015",
    )
    # Both the unprotected full rehearsal and protected execution surface must
    # validate the exact read-only alias before invoking the unchanged loader.
    for label, job in (("bounded", bounded_job), ("protected", frozen_job)):
        require(
            job.count(ALIAS_CHECK_COMMAND) == 1
            and "--alias-path" not in job
            and "--expected-target" not in job
            and "--python-prefix-relative" not in job
            and "--python-binary-relative" not in job
            and "--libpython-relative" not in job
            and "--expected-python-sha256" not in job
            and "--expected-libpython-sha256" not in job,
            f"{label} exact compiled-prefix alias check is missing",
        )
        require(
            job.count(LOADER_PREFLIGHT_COMMAND_FRAGMENT) == 1,
            f"{label} full official-harness loader preflight differs",
        )
        require(
            job.count("validate_official_harness_loader_preflight_evidence") == 2
            and job.index(LOADER_PREFLIGHT_COMMAND_FRAGMENT)
            < job.index("validate_official_harness_loader_preflight_evidence"),
            f"{label} benchmark loader-evidence validation differs",
        )
        require(
            job.index(COMPILED_PREFIX_ALIAS_PATH)
            < job.index(LOADER_PREFLIGHT_COMMAND_FRAGMENT),
            f"{label} alias validation does not precede the loader preflight",
        )
        require(
            job.count('exact_python="$pythonLocation/bin/python3.11"') == 1
            and 'exact_python="$pythonLocation/bin/python"' not in job
            and 'readlink -f "$exact_python"' in job
            and 'readlink -f "$(command -v python)"' in job,
            f"{label} exact direct Python binary identity differs",
        )
    exact_selector = (
        "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, "
        "trimem-benchmark]"
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
        "D1.15 hosted/self-hosted/protected boundary differs",
    )
    for action, digest in (
        ("actions/checkout", CHECKOUT_ACTION_SHA),
        ("actions/setup-python", SETUP_PYTHON_ACTION_SHA),
    ):
        require(
            f"{action}@v" not in workflow and f"{action}@{digest}" in workflow,
            f"D1.15 workflow action is mutable: {action}",
        )


def _validate_documents(repository: Path, source_head: str) -> None:
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    expected_changed_paths = list(_validate_recovery_diff(repository, source_head))
    require(
        amendment.get("schema") == AMENDMENT_SCHEMA
        and inventory.get("schema") == INVENTORY_SCHEMA
        and amendment.get("classification") == AMENDMENT_CLASSIFICATION
        and inventory.get("classification") == AMENDMENT_CLASSIFICATION
        and amendment.get("status") == AMENDMENT_STATUS
        and inventory.get("status") == AMENDMENT_STATUS
        and amendment.get("endpoint") == AMENDMENT_ENDPOINT
        and inventory.get("source_changed_paths") == expected_changed_paths,
        "D1.15 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_014_attempt_one_consumed") is True
        and authority.get("request_014_attempt_two_allowed") is False
        and authority.get("request_014_rerun_allowed") is False
        and authority.get("request_015_request_creation_authorized") is True
        and authority.get("request_015_created_in_source") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_015_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.15 authority boundary differs",
    )
    diagnostic = amendment.get("diagnostic_rehearsal")
    require(
        isinstance(diagnostic, Mapping)
        and diagnostic.get("classification") == "CREDENTIAL_FREE_DIAGNOSTIC_ONLY"
        and diagnostic.get("production_result") is False
        and diagnostic.get("future_revalidation_required") is True
        and diagnostic.get("runner_distribution") == RUNNER_DISTRIBUTION
        and diagnostic.get("alias_path") == COMPILED_PREFIX_ALIAS
        and diagnostic.get("alias_target") == COMPILED_PREFIX_ALIAS_TARGET
        and diagnostic.get("loader_preflight_marker")
        == "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS"
        and diagnostic.get("benchmark_evidence_validator") == "PASS"
        and diagnostic.get("observed_at_utc") is None
        and diagnostic.get("evidence_sha256") is None,
        "D1.15 bounded diagnostic rehearsal record differs",
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
    with d114._d114_runtime_context(), d113._d113_runtime_context():
        d112._validate_remote_gate_workflow_contracts(repository, source_head)
        target_order, hard_cap = d112._validate_frozen_science_documents(
            repository, source_head
        )
    _validate_documents(repository, source_head)
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
        "scientific identity differs from immutable _014",
    )
    bindings = d114._validate_freeze_and_bindings(
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
    with _d115_runtime_context(), d114._d114_runtime_context():
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
    with _d115_runtime_context(), d114._d114_runtime_context():
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
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113._validate_remote_gate_evidence(evidence, source_head=source_head)


def _validate_runner_readiness(
    evidence: Any, *, source_head: str
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113._validate_runner_readiness(evidence, source_head=source_head)


def _validate_runner_readiness_freshness(
    evidence: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    with _d115_runtime_context(), d114._d114_runtime_context():
        d113._validate_runner_readiness_freshness(evidence, now=now)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _utc_datetime(value: Any) -> datetime:
    require(isinstance(value, str) and value.endswith("Z"), "UTC timestamp is malformed")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise DevelopmentTriggerError("UTC timestamp is malformed") from exc
    require(parsed.tzinfo is not None, "UTC timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _validate_alias_evidence(value: Any) -> dict[str, Any]:
    """Validate complete output from the read-only compiled-prefix helper."""

    require(isinstance(value, Mapping), "compiled-prefix alias evidence is missing")
    evidence = dict(value)
    expected_keys = {
        "alias_path",
        "alias_uid",
        "compiled_libpython_path",
        "compiled_python_path",
        "expected_lexical_target",
        "libdir_mode",
        "libpython_bytes",
        "libpython_mode",
        "libpython_realpath",
        "libpython_sha256",
        "observed_lexical_target",
        "python_binary_bytes",
        "python_binary_mode",
        "python_binary_realpath",
        "python_binary_sha256",
        "resolved_libdir",
        "resolved_prefix",
        "resolved_target",
        "schema",
        "secure_directories",
        "status",
    }
    require(set(evidence) == expected_keys, "compiled-prefix alias field set differs")
    helper = importlib.import_module("trimem_compiled_prefix_alias")
    expected_prefix = f"{COMPILED_PREFIX_ALIAS_TARGET}/Python/3.11.10/x64"
    expected_python = f"{expected_prefix}/bin/python3.11"
    expected_libdir = f"{expected_prefix}/lib"
    expected_libpython = f"{expected_libdir}/libpython3.11.so.1.0"
    require(
        evidence.get("schema") == COMPILED_PREFIX_ALIAS_SCHEMA
        and evidence.get("status") == "PASS"
        and evidence.get("alias_path") == COMPILED_PREFIX_ALIAS
        and evidence.get("alias_uid") == 0
        and evidence.get("expected_lexical_target")
        == COMPILED_PREFIX_ALIAS_TARGET
        and evidence.get("observed_lexical_target")
        == COMPILED_PREFIX_ALIAS_TARGET
        and evidence.get("resolved_target") == COMPILED_PREFIX_ALIAS_TARGET
        and evidence.get("resolved_prefix") == expected_prefix
        and evidence.get("resolved_libdir") == expected_libdir
        and evidence.get("compiled_python_path")
        == f"{COMPILED_PREFIX_ALIAS}/Python/3.11.10/x64/bin/python3.11"
        and evidence.get("compiled_libpython_path")
        == f"{COMPILED_PREFIX_ALIAS}/Python/3.11.10/x64/lib/libpython3.11.so.1.0"
        and evidence.get("python_binary_realpath") == expected_python
        and evidence.get("libpython_realpath") == expected_libpython
        and evidence.get("python_binary_sha256") == helper.FROZEN_PYTHON_SHA256
        and evidence.get("libpython_sha256") == helper.FROZEN_LIBPYTHON_SHA256
        and type(evidence.get("python_binary_bytes")) is int
        and evidence["python_binary_bytes"] > 0
        and type(evidence.get("libpython_bytes")) is int
        and evidence["libpython_bytes"] > 0
        and all(
            isinstance(evidence.get(name), str)
            and re.fullmatch(r"[0-7]{4}", str(evidence[name])) is not None
            for name in ("python_binary_mode", "libpython_mode", "libdir_mode")
        ),
        "compiled-prefix alias identity differs",
    )
    directories = evidence.get("secure_directories")
    expected_directory_paths = [
        "/",
        "/opt",
        "/opt/trimem-runner-cache",
        "/opt/trimem-runner-cache/work-ci",
        "/opt/trimem-runner-cache/work-ci/_tool",
        "/opt/trimem-runner-cache/work-ci/_tool/Python",
        "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10",
        "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64",
        "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/bin",
        "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib",
    ]
    require(
        isinstance(directories, list)
        and [row.get("path") for row in directories if isinstance(row, Mapping)]
        == expected_directory_paths
        and all(
            isinstance(row, Mapping)
            and set(row) == {"mode", "path", "uid"}
            and isinstance(row.get("path"), str)
            and str(row["path"]).startswith("/")
            and isinstance(row.get("mode"), str)
            and re.fullmatch(r"[0-7]{4}", str(row["mode"])) is not None
            and int(str(row["mode"]), 8) & 0o022 == 0
            and type(row.get("uid")) is int
            and row["uid"] >= 0
            for row in directories
        ),
        "compiled-prefix secure-directory evidence differs",
    )
    return evidence


def validate_loader_rehearsal(
    value: Any,
    *,
    source_head: str,
    runner_readiness: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate full fresh rehearsal evidence; a PASS marker alone is invalid."""

    require(isinstance(value, Mapping), "exact loader rehearsal evidence is missing")
    evidence = dict(value)
    require(
        set(evidence)
        == {
            "activation_actuals",
            "alias_evidence",
            "benchmark_validation",
            "full_loader_preflight",
            "observed_at_utc",
            "repository",
            "runner_names",
            "runner_readiness_sha256",
            "schema",
            "source_head",
            "status",
        },
        "exact loader rehearsal field set differs",
    )
    observed_at = _utc_datetime(evidence.get("observed_at_utc"))
    reference = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    age = (reference - observed_at).total_seconds()
    require(
        -MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS
        <= age
        <= MAXIMUM_RUNNER_READINESS_AGE_SECONDS,
        "exact loader rehearsal is stale or from the future",
    )
    readiness_sha = _canonical_sha256(dict(runner_readiness))
    require(
        evidence.get("schema") == LOADER_REHEARSAL_SCHEMA
        and evidence.get("status") == "PASS"
        and evidence.get("repository") == EXPECTED_REPOSITORY
        and evidence.get("source_head") == source_head
        and evidence.get("runner_names") == list(RUNNER_NAMES)
        and evidence.get("runner_readiness_sha256") == readiness_sha
        and evidence.get("activation_actuals") == ACTIVATION_ZERO_COUNTERS,
        "exact loader rehearsal identity differs",
    )
    alias = _validate_alias_evidence(evidence.get("alias_evidence"))
    preflight = evidence.get("full_loader_preflight")
    require(isinstance(preflight, Mapping), "full loader preflight evidence is missing")
    required_preflight_keys = {
        "schema",
        "status",
        "marker",
        "environment_constructor",
        "python_loader",
        "environment_identity_sha256",
        "environment_keys",
        "swe_revision",
        "multi_revision",
        "swe_import_check",
        "multi_self_check",
        "invocation_construction",
        "counters",
    }
    counters = preflight.get("counters")
    require(
        set(preflight) == required_preflight_keys
        and preflight.get("schema") == "trimem/official-harness-loader-preflight/1.0"
        and preflight.get("status") == "PASS"
        and preflight.get("marker")
        == "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS"
        and isinstance(counters, Mapping)
        and set(counters)
        == {
            "model_metadata_requests",
            "model_generation_calls",
            "paid_calls",
            "image_pulls",
            "grader_attempts",
            "grader_containers",
            "usd",
        }
        and all(type(counters[name]) is int and counters[name] == 0 for name in counters),
        "full loader preflight contract or zero counters differ",
    )
    loader = preflight.get("python_loader")
    require(
        isinstance(loader, Mapping)
        and loader.get("status") == "PASS"
        and loader.get("python_prefix") == alias["resolved_prefix"]
        and loader.get("python_binary_realpath") == alias["python_binary_realpath"]
        and loader.get("python_binary_sha256") == alias["python_binary_sha256"]
        and loader.get("libdir") == alias["resolved_libdir"]
        and loader.get("libpython_realpath") == alias["libpython_realpath"]
        and loader.get("libpython_sha256") == alias["libpython_sha256"],
        "loader evidence is not bound to compiled-prefix alias evidence",
    )
    for name in (
        "swe_revision",
        "multi_revision",
        "swe_import_check",
        "multi_self_check",
        "invocation_construction",
    ):
        row = preflight.get(name)
        require(
            isinstance(row, Mapping) and row.get("status") == "PASS",
            f"full rehearsal component did not pass: {name}",
        )
    invocation = preflight["invocation_construction"]
    require(
        invocation.get("docker_executions") == 0
        and invocation.get("source_image_build_calls") == 0
        and invocation.get("host_prepare_script_reads") == 0,
        "full rehearsal invocation counters differ",
    )
    validation = evidence.get("benchmark_validation")
    preflight_sha = _canonical_sha256(dict(preflight))
    require(
        isinstance(validation, Mapping)
        and set(validation)
        == {"preflight_sha256", "status", "validator"}
        and validation.get("status") == "PASS"
        and validation.get("validator")
        == "trimem_benchmark_run.validate_official_harness_loader_preflight_evidence"
        and validation.get("preflight_sha256") == preflight_sha,
        "full benchmark evidence validation receipt differs",
    )
    return evidence


def _request_execution_contracts(bindings: Mapping[str, Any]) -> dict[str, Any]:
    with (
        _d115_runtime_context(),
        d114._d114_runtime_context(),
        d113._d113_runtime_context(),
    ):
        result = d112._request_execution_contracts(bindings)
    order = result.get("required_order")
    require(isinstance(order, list), "execution contract order is malformed")
    result["required_order"] = [
        "D1.15 compiled-prefix alias and full loader rehearsal"
        if row == "D1.13 recovery-bound cell-terminal roundtrip"
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
    loader_rehearsal: Mapping[str, Any],
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    validated = _validate_source_impl(repository, source_head)
    gates = _validate_remote_gate_evidence(remote_gate_evidence, source_head=source_head)
    readiness = _validate_runner_readiness(runner_readiness, source_head=source_head)
    rehearsal = validate_loader_rehearsal(
        loader_rehearsal,
        source_head=source_head,
        runner_readiness=readiness,
    )
    previous = validated["previous_request"]
    for name in ("control_plane", "exact_model", "scientific_workload"):
        require(isinstance(previous.get(name), Mapping), f"immutable _014 {name} malformed")
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
        "d115_execution_contracts": _request_execution_contracts(bindings),
        "exact_model": deepcopy(dict(previous["exact_model"])),
        "external_execution_approval_received": False,
        "hard_caps": validated["hard_cap"],
        "loader_rehearsal": rehearsal,
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
            "DEVELOPMENT_TUNING_EXEC_REQUEST_014_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_016",
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
            "bounded_context_preflight_entered": True,
            "cached_python_pre_setup_verified": True,
            "completed_terminal_cells": 0,
            "dependency_installations": 1,
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "grader_containers": 0,
            "grader_state": "NOT_STARTED_BEFORE_PROTECTED_ENVIRONMENT",
            "harness_materializations": 2,
            "loader_preflight_attempted": True,
            "model_api_calls": 0,
            "observed_python_real_prefix": OBSERVED_PYTHON_REAL_PREFIX,
            "observed_sysconfig_libdir": OBSERVED_SYSCONFIG_LIBDIR,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_payload_sha256": (
                "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
            ),
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "previous_source_head": PREVIOUS_SOURCE_HEAD,
            "protected_environment_entered": False,
            "self_hosted_job_assignments": 1,
            "setup_python_completed": True,
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
    loader_rehearsal: Mapping[str, Any],
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return _build_request_impl(
            repository,
            source_head=source_head,
            remote_gate_evidence=remote_gate_evidence,
            runner_readiness=runner_readiness,
            loader_rehearsal=loader_rehearsal,
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
    rehearsal = validate_loader_rehearsal(
        value.get("loader_rehearsal"),
        source_head=source_head,
        runner_readiness=readiness,
    )
    expected = _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
        loader_rehearsal=rehearsal,
    )
    require(value == expected, "_015 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_015 request bytes are not canonical UTF-8 plus one LF",
    )
    return value


def validate_request(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
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
        "trigger commit is not the exclusive _015 sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "_015 sentinel is not a regular non-executable blob")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_015 already exists before the trigger commit",
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
    with _d115_runtime_context(), d114._d114_runtime_context():
        return _validate_sentinel_commit_impl(
            repository,
            after,
            expected_parent=expected_parent,
            require_checked_out_head=require_checked_out_head,
        )


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113._validate_branch_trigger_impl(
            repository, event_path, environ=environ
        )


def collect_remote_gate_evidence(
    source_head: str,
    *,
    allowed_stale_pr_head: str | None = None,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.collect_remote_gate_evidence(
            source_head,
            allowed_stale_pr_head=allowed_stale_pr_head,
            _observer_context=_observer_context,
        )


def collect_remote_runner_rows() -> list[dict[str, Any]]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.collect_remote_runner_rows()


def collect_runner_readiness(
    repository: Path,
    source_head: str,
    *,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.collect_runner_readiness(
            repository, source_head, _observer_context=_observer_context
        )


def collect_local_runner_host_readiness(
    repository: Path,
    source_head: str,
    expected_readiness: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.collect_local_runner_host_readiness(
            repository, source_head, expected_readiness, environ=environ
        )


def validate_runner_host_preflight(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.validate_runner_host_preflight(
            repository, event_path, environ=environ, now=now
        )


def validate_pre_setup_cache_host(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.validate_pre_setup_cache_host(
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
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.collect_protected_runner_readiness(
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
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.validate_protected_runner_preflight(
            repository, event_path, environ=environ, now=now
        )


def start_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.start_protected_services(
            repository, event_path, environ=environ
        )


def verify_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    _monotonic: Any = None,
    _sleep: Any = None,
) -> dict[str, Any]:
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.verify_protected_services(
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
    with _d115_runtime_context(), d114._d114_runtime_context():
        return d113.cleanup_protected_services(
            repository, event_path, environ=environ
        )


def _run_wsl_collector_command(
    argv: Sequence[str], *, environment: Mapping[str, str], label: str, timeout: float
) -> bytes:
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            check=False,
            timeout=timeout,
            env=dict(environment),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DevelopmentTriggerError(f"trusted WSL collector failed: {label}") from exc
    require(
        completed.returncode == 0 and completed.stderr == b"",
        f"trusted WSL collector failed: {label}",
    )
    return completed.stdout


def _wsl_collector_host_environment(
    environ: Mapping[str, str], *, system_root: str
) -> dict[str, str]:
    """Return only Windows process bindings required to launch system WSL.

    The Linux collector receives a separate, empty-by-default environment.  In
    particular, neither Python startup controls nor WSLENV can cross the host
    boundary before the frozen collector starts.
    """

    _validate_secret_free_branch_environment(environ)
    observed: dict[str, tuple[str, str]] = {}
    for name, value in environ.items():
        folded = name.upper()
        if folded not in WSL_HOST_ENVIRONMENT_ALLOWLIST:
            continue
        require(folded not in observed, "duplicate Windows host environment name")
        require(type(value) is str and "\x00" not in value, "invalid host environment")
        observed[folded] = (name, value)
    require(
        type(system_root) is str and system_root and "\x00" not in system_root,
        "Windows system root is invalid",
    )
    result = {name: value for name, value in observed.values()}
    result["SystemRoot"] = system_root
    result["WINDIR"] = system_root
    return result


def _system_wsl_path() -> str:
    """Resolve wsl.exe through the Windows OS API, never PATH or SYSTEMROOT."""

    require(os.name == "nt", "system WSL resolution requires Windows")
    import ctypes

    buffer = ctypes.create_unicode_buffer(32_768)
    length = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    require(0 < length < len(buffer), "Windows system directory lookup failed")
    system_directory = Path(buffer.value).resolve(strict=True)
    candidate = (system_directory / "wsl.exe").resolve(strict=True)
    require(candidate.is_file(), "system WSL executable is absent")
    return str(candidate)


def collect_exact_loader_rehearsal(
    repository: Path,
    source_head: str,
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the frozen collector inside the exact WSL tool-cache surface."""

    repository = resolve_repository_root(repository)
    wsl = _system_wsl_path()
    system_root = str(Path(wsl).parent.parent)
    safe_environment = _wsl_collector_host_environment(
        os.environ, system_root=system_root
    )
    prefix = [
        wsl,
        "-d",
        RUNNER_DISTRIBUTION,
        "--user",
        RUNNER_WSL_USER,
        "--exec",
    ]

    def translate(path: Path) -> str:
        raw = _run_wsl_collector_command(
            [*prefix, "/usr/bin/wslpath", "-a", "-u", str(path)],
            environment=safe_environment,
            label="WSL path translation",
            timeout=30,
        )
        try:
            value = raw.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise DevelopmentTriggerError("WSL path translation is not UTF-8") from exc
        require(value.startswith("/") and "\x00" not in value, "WSL path differs")
        return value

    repository_wsl = translate(repository)
    with tempfile.TemporaryDirectory(prefix="trimem-d115-writer-") as directory:
        readiness_path = Path(directory) / "runner-readiness.json"
        readiness_path.write_bytes(canonical_bytes(dict(runner_readiness), trailing_lf=True))
        readiness_wsl = translate(readiness_path)
        collector = f"{repository_wsl}/{LOADER_REHEARSAL_COLLECTOR_PATH}"
        raw = _run_wsl_collector_command(
            [
                *prefix,
                "/usr/bin/env",
                "-i",
                f"HOME={WSL_COLLECTOR_HOME}",
                "LANG=C.UTF-8",
                "LC_ALL=C.UTF-8",
                f"PATH={WSL_COLLECTOR_PATH}",
                f"LD_LIBRARY_PATH={EXACT_PYTHON_LIBRARY_PATH}",
                f"{EXACT_PYTHON_ROOT}/bin/python3.11",
                "-I",
                collector,
                "--repository",
                repository_wsl,
                "--source-head",
                source_head,
                "--runner-readiness",
                readiness_wsl,
            ],
            environment=safe_environment,
            label="exact full loader rehearsal",
            timeout=900,
        )
    rehearsal = strict_json(raw)
    require(
        raw == canonical_bytes(rehearsal, trailing_lf=True),
        "trusted loader collector output is not canonical UTF-8 plus one LF",
    )
    return validate_loader_rehearsal(
        rehearsal,
        source_head=source_head,
        runner_readiness=runner_readiness,
    )


def write_request(repository: Path) -> dict[str, Any]:
    """Create `_015` only after fresh gates, runners, and full rehearsal."""

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
    require(not os.path.lexists(target), "_015 sentinel already exists in worktree")
    with _d115_runtime_context(), d114._d114_runtime_context():
        _validate_source_impl(repository, source_head)
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
    rehearsal = collect_exact_loader_rehearsal(
        repository,
        source_head,
        readiness,
    )
    document = build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
        loader_rehearsal=rehearsal,
    )
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_no_pending_benchmark_consumers(*observer_context)
    _validate_runner_readiness_freshness(readiness)
    validate_loader_rehearsal(
        rehearsal,
        source_head=source_head,
        runner_readiness=readiness,
    )
    with _d115_runtime_context(), d114._d114_runtime_context():
        d113._recheck_request_write_boundary(repository, source_head, target)
    try:
        with target.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise DevelopmentTriggerError(
            "_015 sentinel could not be created exclusively"
        ) from exc
    return {
        "bytes": len(raw),
        "path": SENTINEL_PATH,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "source_head": source_head,
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
    }


def __getattr__(name: str) -> Any:
    return getattr(d114, name)


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
