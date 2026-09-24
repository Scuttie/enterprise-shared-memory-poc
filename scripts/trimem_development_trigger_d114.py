"""Fail-closed one-time DEVELOPMENT_TUNING ``_014`` recovery trigger.

D1.14 preserves the spent ``_013`` request and its credential-free attempt-one
failure as immutable Git history.  The only runtime correction is an explicit
workflow binding that restores the one frozen Python library directory after
``actions/setup-python``.  The strict D1.12 listener, ``.env``, and process
environment validators are deliberately not relaxed.

The audited runner implementation remains in D1.12 and the D1.13 hosted-gate
repair remains in D1.13.  Calls into them use a locked, reversible identity
context; importing this module has no side effect and performs no network,
Docker, grader, credential, or model action.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
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

import trimem_development_trigger_d113 as d113

d112 = d113.d112


# Repository, branch, phase, and scientific identity remain unchanged.
EXPECTED_REPOSITORY = d113.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d113.EXPECTED_BRANCH
EXPECTED_REF = d113.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d113.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d113.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d113.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d113.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d113.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d113.EXPECTED_BASE_HEAD

# Immutable EXEC _013 lineage and public failure evidence.  These are Git-blob
# byte identities; do not derive them from a CRLF-smudged working tree.
PREVIOUS_SOURCE_HEAD = "cb17ceae0fbc951dff34213de977a73b5405fefc"
PREVIOUS_EXECUTION_HEAD = "35bfa338915d731dab499f2dfee08b38741bfe8d"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_013.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "a500568cedfa800bd85e20263b604fa2c1d24f634644d5ef14f517a8330b6417"
)
PREVIOUS_SENTINEL_BYTES = 21_784
PREVIOUS_SENTINEL_BLOB_OID = "899492ee4835394f78699ee1d4a6273c2d26e875"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "132c7fc8a7ca166076882a53d3a69db56b4ccc5ab9e41ec1071a196f0618fe26"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "ea74940aad297761c62c9f2555eb9aba3819e584082bf68951247e9a39d1f0c6"
)
PREVIOUS_RUN_ID = 34_138_918_074
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_FAILURE_SUBTYPE = "SETUP_PYTHON_POST_SETUP_LD_LIBRARY_PATH_SHAPE"
PREVIOUS_FAILURE_CLASSIFICATION = (
    "POST_SETUP_PYTHON_DUAL_LD_LIBRARY_PATH_FAIL_CLOSED"
)
PREVIOUS_FAILURE_MESSAGE = (
    "runner LD_LIBRARY_PATH binding differs: bounded-context preflight process "
    "environment"
)
PREVIOUS_FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d114/exec_013_post_setup_failure.json"
)

STARTING_SOURCE_HEAD = PREVIOUS_EXECUTION_HEAD
STARTING_FREEZE_SHA256 = PREVIOUS_SOURCE_FREEZE_SHA256
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.14"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_014.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-014"

AMENDMENT_PATH = "artifacts/trimem_v1/development_exec_014_recovery_amendment.json"
AMENDMENT_SCHEMA = "trimem/development-exec-014-recovery-amendment/1.0"
INVENTORY_PATH = "artifacts/trimem_v1/development_exec_014_recovery_inventory.json"
INVENTORY_SCHEMA = "trimem/development-exec-014-recovery-inventory/1.0"
AMENDMENT_CLASSIFICATION = "POST_EXEC_013_ZERO_MODEL_SETUP_PYTHON_ENVIRONMENT_RECOVERY"
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_013_FAILURE_READY_FOR_EXEC_014_REQUEST"
)
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_014_REQUEST"
REPORT_PATH = "reports/TRIMEM_D114_EXEC_014_RECOVERY.md"
GATE_CONTRACT_PATH = "scripts/trimem_d114_gate_contract.py"
RESEAL_PATH = "scripts/trimem_d114_reseal.py"

FREEZE_PATH = d113.FREEZE_PATH
FREEZE_SCHEMA = d113.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.14"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.14"

MODEL_ID = d113.MODEL_ID
REASONING_EFFORT = d113.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d113.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d113.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d113.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d113.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d113.ACTIVATION_ZERO_COUNTERS
# Exact source-HEAD checks observed before the `_013` trigger.  D1.14 freezes
# all 20 successful checks instead of inheriting D1.12's older 12-check set.
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
    (".github/workflows/ci-company-package.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-company-harness.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-company-demo.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-trimem-harness-lock.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-oidc.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-experience-schema.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-oss-release.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-trimem-grader-loader.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-trimem-multi-swe-contract.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-trimem-e2e.yml", "pull_request", PULL_REQUEST_NUMBER),
    (".github/workflows/ci-trimem.yml", "pull_request", PULL_REQUEST_NUMBER),
)
REQUIRED_REMOTE_GATE_WORKFLOWS = tuple(
    dict.fromkeys(spec[0] for spec in REMOTE_GATE_SPECS)
)
PRESERVED_SCIENTIFIC_PATHS = d113.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d113.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d113.EXECUTION_CONTRACT_PATHS

CHECKOUT_ACTION_SHA = d113.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d113.SETUP_PYTHON_ACTION_SHA
CODEQL_ACTION_SHA = d113.CODEQL_ACTION_SHA
RUNNER_DISTRIBUTION = d113.RUNNER_DISTRIBUTION
RUNNER_WSL_USER = d113.RUNNER_WSL_USER
RUNNER_NAMES = d113.RUNNER_NAMES
RUNNER_ROOTS = d113.RUNNER_ROOTS
RUNNER_TOOL_CACHE = d113.RUNNER_TOOL_CACHE
EXACT_PYTHON_ROOT = d113.EXACT_PYTHON_ROOT
EXACT_PYTHON_LIBRARY_PATH = d113.EXACT_PYTHON_LIBRARY_PATH
PYTHON_TOOLCACHE_COMPLETE_PATH = d113.PYTHON_TOOLCACHE_COMPLETE_PATH
PYTHON_TOOLCACHE_COMPLETE_BYTES = d113.PYTHON_TOOLCACHE_COMPLETE_BYTES
PYTHON_TOOLCACHE_COMPLETE_SHA256 = d113.PYTHON_TOOLCACHE_COMPLETE_SHA256
RUNNER_PACKAGE_VERSION = d113.RUNNER_PACKAGE_VERSION
RUNNER_PACKAGE_ARCHIVE_PATH = d113.RUNNER_PACKAGE_ARCHIVE_PATH
RUNNER_PACKAGE_ARCHIVE_BYTES = d113.RUNNER_PACKAGE_ARCHIVE_BYTES
RUNNER_PACKAGE_ARCHIVE_SHA256 = d113.RUNNER_PACKAGE_ARCHIVE_SHA256
RUNNER_LISTENER_BYTES = d113.RUNNER_LISTENER_BYTES
RUNNER_LISTENER_SHA256 = d113.RUNNER_LISTENER_SHA256
REQUIRED_RUNNER_LABELS = d113.REQUIRED_RUNNER_LABELS
STALE_RUNNER_ROOTS = d113.STALE_RUNNER_ROOTS
MINIMUM_RUNNER_DISK_BYTES = d113.MINIMUM_RUNNER_DISK_BYTES
MAXIMUM_RUNNER_READINESS_AGE_SECONDS = d113.MAXIMUM_RUNNER_READINESS_AGE_SECONDS
MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS = d113.MAXIMUM_RUNNER_CLOCK_SKEW_SECONDS
BENCHMARK_EXEC_RUNNER_BOUNDARY = d113.BENCHMARK_EXEC_RUNNER_BOUNDARY
DOCKER_CLIENT_PATH = d113.DOCKER_CLIENT_PATH
DOCKER_CLIENT_BYTES = d113.DOCKER_CLIENT_BYTES
DOCKER_CLIENT_SHA256 = d113.DOCKER_CLIENT_SHA256
DOCKER_VERSION = d113.DOCKER_VERSION
DOCKER_ROOT_DIRECTORY = d113.DOCKER_ROOT_DIRECTORY
SERVICE_PORTS = d113.SERVICE_PORTS
SERVICE_IMAGE_REFS = d113.SERVICE_IMAGE_REFS
SERVICE_STATE_SCHEMA = d113.SERVICE_STATE_SCHEMA
SERVICE_STATE_FILENAME = d113.SERVICE_STATE_FILENAME
SERVICE_CONTAINER_NAME_PREFIX = d113.SERVICE_CONTAINER_NAME_PREFIX
RUNNER_SERVICE_UID = d113.RUNNER_SERVICE_UID
RUNNER_SERVICE_GID = d113.RUNNER_SERVICE_GID
GH_CLI_LOCK_PATH = d113.GH_CLI_LOCK_PATH
BENCHMARK_ENVIRONMENT_LOCK_PATH = d113.BENCHMARK_ENVIRONMENT_LOCK_PATH
HEX40 = d113.HEX40

DevelopmentTriggerError = d113.DevelopmentTriggerError
DevelopmentTriggerD114Error = DevelopmentTriggerError
require = d113.require
canonical_bytes = d113.canonical_bytes
strict_json = d113.strict_json
git = d113.git
commit_bytes = d113.commit_bytes
resolve_repository_root = d113.resolve_repository_root
_is_ancestor = d113._is_ancestor
_sha256_at = d113._sha256_at
_validate_secret_free_branch_environment = d113._validate_secret_free_branch_environment
_validate_unique_execution_run = d113._validate_unique_execution_run
_pinned_gh_context = d113._pinned_gh_context
_collect_current_pull_request = d113._collect_current_pull_request
_collect_remote_gate_rows = d113._collect_remote_gate_rows
_require_no_pending_benchmark_consumers = d113._require_no_pending_benchmark_consumers


# The platform correction is explicit and lexical.  ``actions/setup-python``
# prepended an active-runner symlink spelling to the already frozen central
# spelling during EXEC _013.  D1.14 does not accept that two-entry value; each
# post-setup validator step must override it with this one exact value.
POST_SETUP_REQUIRED_LD_LIBRARY_PATH = EXACT_PYTHON_LIBRARY_PATH
EXEC_013_OBSERVED_LD_LIBRARY_PATH = (
    f"{RUNNER_ROOTS[0]}/_work/_tool/Python/3.11.10/x64/lib:"
    f"{EXACT_PYTHON_LIBRARY_PATH}"
)
POST_SETUP_EXACT_ENV_STEPS = (
    "Re-observe exact self-hosted runner before any install or materialization",
    "Re-observe protected runner before cache-only service creation",
    "Start exact cache-only benchmark services",
    "Verify exact cache-only benchmark services",
    "Remove exact cache-only benchmark services",
)


# D1.14 admits only control-plane, evidence, and current-validator changes.
# Model, prompt, target, arm, grader, image, pricing, and budget inputs are not
# in this vocabulary and are checked byte-for-byte below.
ALLOWED_RECOVERY_PATHS = frozenset(
    {
        ".gitattributes",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/ci-experience-schema.yml",
        ".github/workflows/ci-oidc.yml",
        ".github/workflows/ci-oss-release.yml",
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
        GATE_CONTRACT_PATH,
        RESEAL_PATH,
        "scripts/trimem_development_trigger_d114.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d113_status_and_reseal.py",
        "tests/unit/test_trimem_d114_e1_trigger.py",
        "tests/unit/test_trimem_d114_gate_contract.py",
        "tests/unit/test_trimem_d114_post_setup_environment.py",
        "tests/unit/test_trimem_d114_status_and_reseal.py",
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
    ".github/workflows/ci-experience-schema.yml": "M",
    ".github/workflows/ci-oidc.yml": "M",
    ".github/workflows/ci-oss-release.yml": "M",
    ".github/workflows/ci-trimem-e2e.yml": "M",
    ".github/workflows/ci-trimem-harness-lock.yml": "M",
    ".github/workflows/ci-trimem-multi-swe-contract.yml": "M",
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
    "scripts/trimem_development_trigger_d114.py": "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d113_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d114_e1_trigger.py": "A",
    "tests/unit/test_trimem_d114_gate_contract.py": "A",
    "tests/unit/test_trimem_d114_post_setup_environment.py": "A",
    "tests/unit/test_trimem_d114_status_and_reseal.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}
ALLOWED_ACTIVATION_PATHS = ALLOWED_RECOVERY_PATHS
REQUIRED_ACTIVATION_CHANGES = REQUIRED_RECOVERY_CHANGES

ACTIVATION_BINDING_PATHS = {
    "gitattributes_sha256": ".gitattributes",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "d114_amendment_sha256": AMENDMENT_PATH,
    "d114_gate_contract_sha256": GATE_CONTRACT_PATH,
    "d114_inventory_sha256": INVENTORY_PATH,
    "d114_reseal_sha256": RESEAL_PATH,
    "d114_run_fixture_sha256": PREVIOUS_FAILURE_FIXTURE_PATH,
    "readiness_requirements_sha256": "artifacts/trimem_v1/readiness_requirements.json",
    "trigger_reader_sha256": "scripts/trimem_development_trigger_d114.py",
    "verify_ready_sha256": "scripts/trimem_verify_ready.py",
}


def _runtime_overrides() -> dict[str, Any]:
    """Return D1.14 bindings after every custom function has been defined."""

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


_D113_CONTEXT_LOCK = threading.RLock()


@contextmanager
def _d114_runtime_context() -> Iterator[None]:
    """Temporarily bind D1.13 adapters to D1.14 and restore every name."""

    # D1.13 uses this same re-entrant lock before it mutates D1.12.  Holding it
    # while D1.14 temporarily binds D1.13 prevents a concurrent D1.13 caller
    # from observing a half-applied generation identity.
    with _D113_CONTEXT_LOCK, d113._D112_CONTEXT_LOCK:
        overrides = _runtime_overrides()
        previous = {name: getattr(d113, name) for name in overrides}
        d112_overrides = {
            "REMOTE_GATE_SPECS": REMOTE_GATE_SPECS,
            "REQUIRED_REMOTE_GATE_WORKFLOWS": REQUIRED_REMOTE_GATE_WORKFLOWS,
        }
        d112_previous = {
            name: getattr(d112, name) for name in d112_overrides
        }
        try:
            for name, value in overrides.items():
                setattr(d113, name, value)
            for name, value in d112_overrides.items():
                setattr(d112, name, value)
            yield
        finally:
            for name, value in reversed(tuple(d112_previous.items())):
                setattr(d112, name, value)
            for name, value in reversed(tuple(previous.items())):
                setattr(d113, name, value)


def _tree_entry(repository: Path, commit: str, path: str) -> tuple[str, str]:
    raw = git(repository, "ls-tree", "--full-tree", commit, "--", path).strip()
    left, separator, observed_path = raw.partition("\t")
    fields = left.split()
    require(
        separator == "\t"
        and observed_path == path
        and len(fields) == 3
        and fields[1] == "blob",
        f"Git blob differs: {path}",
    )
    return fields[0], fields[2]


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    """Pin the exact ``_013`` graph, raw blob, self-hash, and zero authority."""

    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _013 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _013 execution parent differs",
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
        "immutable _013 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _013 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and b"\r" not in raw,
        "immutable _013 sentinel raw bytes differ",
    )
    previous = strict_json(raw)
    bindings = previous.get("bindings")
    activation_actuals = previous.get("activation_actuals")
    pre_execution_actuals = previous.get("pre_execution_actuals")
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.13"
        and previous.get("request_id") == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013"
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
        "immutable _013 request identity, bytes, or zero authority differs",
    )
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.14 source does not preserve immutable EXEC _013",
    )
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical _013 request changed after execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_014 exists in recovery-source history",
    )
    return previous


def _load_failure_contract() -> Any:
    return importlib.import_module("trimem_d114_gate_contract")


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
        "EXEC _013 failure fixture is not canonical pretty UTF-8 plus one LF",
    )
    try:
        contract = _load_failure_contract()
        replay = contract.validate_fixture(value)
    except Exception as exc:
        raise DevelopmentTriggerError(
            "EXEC _013 failure fixture rejected by D1.14 gate contract"
        ) from exc
    require(
        replay.get("status") == "PASS"
        and replay.get("source_head") == PREVIOUS_SOURCE_HEAD
        and replay.get("execution_head") == PREVIOUS_EXECUTION_HEAD
        and replay.get("execution_run_id") == PREVIOUS_RUN_ID
        and replay.get("execution_run_attempt") == PREVIOUS_RUN_ATTEMPT
        and replay.get("protected_environment_entered") is False
        and replay.get("self_hosted_job_assignments") == 1,
        "EXEC _013 failure replay identity differs",
    )
    workflow = value.get("workflow_run")
    boundary = value.get("boundary")
    failure = value.get("failed_log_summary")
    digests = value.get("digests")
    actuals = value.get("actuals")
    jobs = value.get("jobs")
    require(
        value.get("schema") == "trimem/d114-exec-013-post-setup-failure/1.0"
        and value.get("repository") == EXPECTED_REPOSITORY
        and value.get("branch") == EXPECTED_BRANCH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("execution_head") == PREVIOUS_EXECUTION_HEAD,
        "EXEC _013 failure fixture identity differs",
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
        "EXEC _013 workflow-run history differs",
    )
    require(
        isinstance(boundary, Mapping)
        and boundary.get("branch_trigger_preflight_entered") is True
        and boundary.get("bounded_context_preflight_entered") is True
        and boundary.get("pre_setup_cache_host_passed") is True
        and boundary.get("setup_python_passed") is True
        and boundary.get("dependency_install_started") is False
        and boundary.get("harness_materialization_started") is False
        and boundary.get("post_setup_runner_reobservation_entered") is True
        and boundary.get("frozen_serial_phase_entered") is False
        and boundary.get("protected_environment_approval_requested") is False
        and boundary.get("protected_environment_entered") is False
        and boundary.get("self_hosted_job_assignments") == 1,
        "EXEC _013 pre-install boundary differs",
    )
    require(
        isinstance(failure, Mapping)
        and failure.get("failure_classification")
        == PREVIOUS_FAILURE_CLASSIFICATION
        and failure.get("failure_subtype") == PREVIOUS_FAILURE_SUBTYPE
        and failure.get("failure_message") == PREVIOUS_FAILURE_MESSAGE
        and failure.get("failed_job") == "bounded-context-preflight"
        and failure.get("failed_step")
        == "Re-observe exact self-hosted runner before any install or materialization"
        and failure.get("process_exit_code") == 1
        and failure.get("observed_ld_library_path")
        == EXEC_013_OBSERVED_LD_LIBRARY_PATH
        and failure.get("expected_ld_library_path")
        == POST_SETUP_REQUIRED_LD_LIBRARY_PATH,
        "EXEC _013 failure location or environment differs",
    )
    require(
        isinstance(digests, Mapping)
        and digests.get("request_raw_sha256") == PREVIOUS_SENTINEL_SHA256
        and digests.get("request_self_hash_sha256")
        == PREVIOUS_REQUEST_PAYLOAD_SHA256
        and digests.get("source_freeze_sha256")
        == PREVIOUS_SOURCE_FREEZE_SHA256,
        "EXEC _013 frozen digest evidence differs",
    )
    expected_actuals = {
        "benchmark_image_pulls": 0,
        "dependency_installations": 0,
        "grader_containers": 0,
        "harness_materializations": 0,
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
    require(actuals == expected_actuals, "EXEC _013 failure fixture is not zero-use")
    require(
        isinstance(jobs, list)
        and [(row.get("name"), row.get("conclusion")) for row in jobs]
        == [
            ("branch-trigger-preflight", "success"),
            ("bounded-context-preflight", "failure"),
            ("frozen-serial-phase", "skipped"),
        ],
        "EXEC _013 workflow job funnel differs",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    require(
        source_head != PREVIOUS_EXECUTION_HEAD
        and _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.14 source is not a strict descendant of immutable EXEC _013",
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
        require(len(pieces) == 2, "D1.14 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.14 diff status is forbidden: {status}")
        require(path in ALLOWED_RECOVERY_PATHS, f"D1.14 changed forbidden path: {path}")
        require(path not in changes, f"D1.14 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.14 recovery change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path),
            f"frozen scientific input changed during D1.14 recovery: {path}",
        )


def _step_block(workflow: str, name: str) -> str:
    marker = f"      - name: {name}\n"
    require(workflow.count(marker) == 1, f"workflow step differs: {name}")
    start = workflow.index(marker)
    end = workflow.find("\n      - name: ", start + len(marker))
    return workflow[start:] if end < 0 else workflow[start:end]


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
        "active push sentinel is not exclusively _014",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-013" not in workflow,
        "_014 concurrency identity differs",
    )
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        all(
            workflow.count(marker) == 1
            for marker in (branch_marker, bounded_marker, frozen_marker)
        ),
        "D1.14 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(branch_start < bounded_start < frozen_start, "D1.14 job order differs")
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    command = "python -I -S scripts/trimem_development_trigger_d114.py"
    require(
        branch_job.count(command) == 1
        and bounded_job.count(command) == 1
        and frozen_job.count(command) == 4
        and "scripts/trimem_development_trigger_d113.py" not in workflow,
        "active trigger validator is not exclusively D1.14 _014",
    )
    exact_env_row = f"          LD_LIBRARY_PATH: {POST_SETUP_REQUIRED_LD_LIBRARY_PATH}\n"
    for step_name in POST_SETUP_EXACT_ENV_STEPS:
        block = _step_block(workflow, step_name)
        require(
            block.count(exact_env_row) == 1
            and "LD_LIBRARY_PATH:" not in block.replace(exact_env_row, "")
            and "trimem_development_trigger_d114.py" in block,
            f"post-setup exact library environment differs: {step_name}",
        )
    require(
        EXEC_013_OBSERVED_LD_LIBRARY_PATH not in workflow,
        "workflow preserves the rejected EXEC _013 dual library path",
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
        "D1.14 hosted/self-hosted/protected boundary differs",
    )
    for action, digest in (
        ("actions/checkout", CHECKOUT_ACTION_SHA),
        ("actions/setup-python", SETUP_PYTHON_ACTION_SHA),
    ):
        require(
            f"{action}@v" not in workflow and f"{action}@{digest}" in workflow,
            f"D1.14 workflow action is mutable: {action}",
        )


def _freeze_entry(
    repository: Path, source_head: str, files: Mapping[str, Any], path: str
) -> str:
    raw = commit_bytes(repository, source_head, path)
    digest = hashlib.sha256(raw).hexdigest()
    require(
        files.get(path) == {"bytes": len(raw), "sha256": digest},
        f"D1.14 freeze does not bind path: {path}",
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
        "D1.14 research freeze is malformed",
    )
    require(SENTINEL_PATH not in files, "_014 entered its source freeze")
    old_raw = commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH)
    require(
        files.get(PREVIOUS_SENTINEL_PATH)
        == {"bytes": PREVIOUS_SENTINEL_BYTES, "sha256": PREVIOUS_SENTINEL_SHA256}
        and hashlib.sha256(old_raw).hexdigest() == PREVIOUS_SENTINEL_SHA256,
        "D1.14 freeze does not preserve immutable _013",
    )
    previous_bindings = previous.get("bindings")
    require(isinstance(previous_bindings, Mapping), "immutable _013 bindings malformed")
    bindings = deepcopy(dict(previous_bindings))
    bindings["freeze_sha256"] = "sha256:" + hashlib.sha256(freeze_raw).hexdigest()
    for name, path in SCIENCE_BINDING_PATHS.items():
        observed = _freeze_entry(repository, source_head, files, path)
        require(
            observed == previous_bindings.get(name),
            f"scientific binding changed after EXEC _013: {name}",
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
        "D1.14 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_013_attempt_one_consumed") is True
        and authority.get("request_013_rerun_allowed") is False
        and authority.get("request_014_request_creation_authorized") is True
        and authority.get("request_014_created_in_source") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_014_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.14 authority boundary differs",
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
    with d113._d113_runtime_context():
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
        "scientific identity differs from immutable _013",
    )
    bindings = _validate_freeze_and_bindings(repository, source_head, previous)
    return {
        "activation_changes": changes,
        "bindings": bindings,
        "failure_fixture": failure,
        "hard_cap": hard_cap,
        "previous_request": previous,
        "target_order": target_order,
    }


def _validate_source(repository: Path, source_head: str) -> dict[str, Any]:
    with _d114_runtime_context():
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
    with _d114_runtime_context():
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
    with _d114_runtime_context():
        return d113._validate_remote_gate_evidence(evidence, source_head=source_head)


def _validate_runner_readiness(
    evidence: Any, *, source_head: str
) -> dict[str, Any]:
    with _d114_runtime_context():
        return d113._validate_runner_readiness(evidence, source_head=source_head)


def _validate_runner_readiness_freshness(
    evidence: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    with _d114_runtime_context():
        d113._validate_runner_readiness_freshness(evidence, now=now)


def _request_execution_contracts(bindings: Mapping[str, Any]) -> dict[str, Any]:
    with _d114_runtime_context(), d113._d113_runtime_context():
        result = d112._request_execution_contracts(bindings)
    order = result.get("required_order")
    require(isinstance(order, list), "execution contract order is malformed")
    result["required_order"] = [
        "D1.14 exact post-setup Python-library binding"
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
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    validated = _validate_source_impl(repository, source_head)
    gates = _validate_remote_gate_evidence(remote_gate_evidence, source_head=source_head)
    readiness = _validate_runner_readiness(runner_readiness, source_head=source_head)
    previous = validated["previous_request"]
    for name in ("control_plane", "exact_model", "scientific_workload"):
        require(isinstance(previous.get(name), Mapping), f"immutable _013 {name} malformed")
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
        "d114_execution_contracts": _request_execution_contracts(bindings),
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
            "DEVELOPMENT_TUNING_EXEC_REQUEST_013_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_015",
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
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "grader_containers": 0,
            "grader_state": "NOT_STARTED_BEFORE_INSTALL_OR_PROTECTED_ENVIRONMENT",
            "hash_locked_install_entered": False,
            "model_api_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013",
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
) -> dict[str, Any]:
    with _d114_runtime_context():
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
    require(value == expected, "_014 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_014 request bytes are not canonical UTF-8 plus one LF",
    )
    return value


def validate_request(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    with _d114_runtime_context():
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
        "trigger commit is not the exclusive _014 sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "_014 sentinel is not a regular non-executable blob")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_014 already exists before the trigger commit",
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
    with _d114_runtime_context():
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
    with _d114_runtime_context():
        return d113._validate_branch_trigger_impl(
            repository, event_path, environ=environ
        )


def collect_remote_gate_evidence(
    source_head: str,
    *,
    allowed_stale_pr_head: str | None = None,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    with _d114_runtime_context():
        return d113.collect_remote_gate_evidence(
            source_head,
            allowed_stale_pr_head=allowed_stale_pr_head,
            _observer_context=_observer_context,
        )


def collect_remote_runner_rows() -> list[dict[str, Any]]:
    with _d114_runtime_context():
        return d113.collect_remote_runner_rows()


def collect_runner_readiness(
    repository: Path,
    source_head: str,
    *,
    _observer_context: tuple[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    with _d114_runtime_context():
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
    with _d114_runtime_context():
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
    with _d114_runtime_context():
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
    with _d114_runtime_context():
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
    with _d114_runtime_context():
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
    with _d114_runtime_context():
        return d113.validate_protected_runner_preflight(
            repository, event_path, environ=environ, now=now
        )


def start_protected_services(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    with _d114_runtime_context():
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
    with _d114_runtime_context():
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
    with _d114_runtime_context():
        return d113.cleanup_protected_services(
            repository, event_path, environ=environ
        )


def write_request(repository: Path) -> dict[str, Any]:
    """Create `_014` through the inherited exclusive zero-authority writer."""

    with _d114_runtime_context():
        return d113.write_request(repository)


def __getattr__(name: str) -> Any:
    """Expose unchanged D1.13/D1.12 helpers without copying runtime code."""

    return getattr(d113, name)


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
