"""Build and verify the credential-free D1.12 ``_012`` activation seal.

D1.12 records authority to *create* one zero-authority request sentinel after
fresh source CI and runner-readiness gates.  It does not grant protected DEV
execution authority.  A separate external approval must be bound to the exact
sentinel commit and workflow attempt before credentials or benchmark work can
be reached.

The historical D1.11 seal is read from its immutable Git commit.  This module
also freezes the exact Linux/Windows GitHub observer bytes and bounded
eventual-visibility policy.  It performs no network, credential, Docker,
grader, image, or model operation.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = ROOT / (
    "artifacts/trimem_v1/development_exec_012_activation_amendment.json"
)
INVENTORY_PATH = ROOT / (
    "artifacts/trimem_v1/development_exec_012_activation_inventory.json"
)
READINESS_PATH = ROOT / "artifacts/trimem_v1/readiness_requirements.json"
REPORT_PATH = ROOT / "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md"

AMENDMENT_SCHEMA = "trimem/development-exec-012-activation-amendment/1.0"
INVENTORY_SCHEMA = "trimem/development-exec-012-activation-inventory/1.0"
STATUS = "FROZEN_CREDENTIAL_FREE_READY_FOR_EXEC_012_REQUEST"
CLASSIFICATION = "PRE_EXEC_012_ZERO_AUTHORITY_ACTIVATION"
ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_012_REQUEST"
FAILURE_SUBTYPE = "NONE_PRE_EXEC_012"

BASE_HEAD = "fa1af529a2af4f8ba606b01410434412881f3d27"
BASE_FREEZE_SHA256 = (
    "e2964255c9c214f29c04bc8df2a5fe275601d43a40f8cad6b1fc926b8cf73739"
)
D111_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_activation_lifecycle_amendment.json"
)
D111_INVENTORY_PATH = (
    "artifacts/trimem_v1/development_activation_lifecycle_inventory.json"
)
D111_FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
D111_AMENDMENT_SHA256 = (
    "bd4648ca3bb6542c16d9af9d0bbe96cd64241986212c0b50a52e4fb8a9bf6ca4"
)
D111_INVENTORY_SHA256 = (
    "383462fce02204fb7ca3507e8102e804f9fa4df135ff5d719a172cf85df8c5c1"
)
HISTORICAL_D111_SHA256 = {
    D111_AMENDMENT_PATH: D111_AMENDMENT_SHA256,
    D111_INVENTORY_PATH: D111_INVENTORY_SHA256,
    D111_FREEZE_PATH: BASE_FREEZE_SHA256,
}

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012"
REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_012.json"
)
REQUEST_012_PATH = REQUEST_PATH
PREVIOUS_REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_011.json"
)
PREVIOUS_EXECUTION_HEAD = "e54d04b0af9e738d311c389dc89cfd510fd7065b"
PREVIOUS_RUN_ID = 34_047_573_548
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_REQUEST_SHA256 = (
    "75acaaa8f1f2f0dc138530dfc533df440e2c70f4ee885732b8297a8150de2fa0"
)
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012_APPROVED_ONCE"
)
DEVELOPMENT_AUTHORITY_MEANING = (
    "The _011 attempt-1 run cannot be rerun; it is immutable and final after "
    "failing in the hosted branch trigger with zero model/API calls and before "
    "protected execution. The user authorized creation of one zero-authority "
    "_012 sentinel only after fresh exact-head source CI and exactly two isolated "
    "runners pass. This does not authorize protected DEV execution; a separate "
    "exact _012 external approval remains mandatory."
)
GH_CLI_LOCK_PATH = ROOT / "configs/trimem_v1/gh_cli_lock.json"
GH_CLI_LOCK_SCHEMA = "trimem/gh-cli-lock/1.1"
GH_CLI_VERSION = "2.97.0"
GH_CLI_VERSION_LINE = "gh version 2.97.0 (2026-07-31)"
WSL_EXACT_PYTHON_ROOT = "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64"
WSL_EXACT_PYTHON_LIBRARY_PATH = f"{WSL_EXACT_PYTHON_ROOT}/lib"
RUNNER_DISTRIBUTION = "TriMemRunner2404"
RUNNER_WSL_USER = "trimem-runner"
RUNNER_TOOL_CACHE = "/opt/trimem-runner-cache/work-ci/_tool"
PYTHON_TOOLCACHE_COMPLETE_PATH = f"{WSL_EXACT_PYTHON_ROOT}.complete"
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
RUNNER_BOUNDARY = (
    "protected ephemeral self-hosted runner; one serial phase job owns "
    "PostgreSQL, Qdrant and the atomic global ledger"
)
RUNNER_NAMES = ("trimem-d112-exec", "trimem-d112-preflight")
RUNNER_ROOTS = (
    "/opt/trimem-d112-runners/exec",
    "/opt/trimem-d112-runners/preflight",
)
RUNNER_SERVICE_UID = 1000
RUNNER_SERVICE_GID = 1000
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
DOCKER_VERSION = "29.1.3"
DOCKER_CREATE_PULL_NEVER_MARKER = "--pull string Pull image before creating"
DOCKER_CLIENT_PATH = "/usr/bin/docker"
DOCKER_CLIENT_BYTES = 31_369_824
DOCKER_CLIENT_SHA256 = (
    "7ed12b00293d64742419a6601ae97960a367a0ce97c88b06e3278cc0a409557b"
)
DOCKER_ROOT_DIRECTORY = "/var/lib/docker"
DOCKER_LOCAL_PREFIX = (DOCKER_CLIENT_PATH, "--host", "unix:///var/run/docker.sock")
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
PENDING_WORKFLOW_STATUSES = (
    "in_progress",
    "pending",
    "queued",
    "requested",
    "waiting",
)
REQUEST_REQUIRED_ORDER = (
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
)
WINDOWS_OBSERVER_LOCK = {
    "archive_binary_path": "bin/gh.exe",
    "archive_filename": "gh_2.97.0_windows_amd64.zip",
    "archive_sha256": (
        "35d7fe05c4dd1411ffda1e73dfc7c6f44b75c936ca51fa6595c657fdc0350cec"
    ),
    "archive_sha256_source_line": (
        "35d7fe05c4dd1411ffda1e73dfc7c6f44b75c936ca51fa6595c657fdc0350cec  "
        "gh_2.97.0_windows_amd64.zip"
    ),
    "archive_url": (
        "https://github.com/cli/cli/releases/download/v2.97.0/"
        "gh_2.97.0_windows_amd64.zip"
    ),
    "extracted_gh_binary_sha256": (
        "e2efa10a5d2ce93cac9bc4b676932b62947c0967c01c8f2c3a9cb4437ad358d3"
    ),
    "hash_source": {
        "archive_sha256": "OFFICIAL_GITHUB_CLI_RELEASE_CHECKSUM_FILE",
        "extracted_gh_binary_sha256": (
            "INDEPENDENT_SHA256_OF_EXACT_REGULAR_FILE_PAYLOAD_"
            "AFTER_ARCHIVE_VERIFICATION"
        ),
    },
    "observed_archive_bytes": 14_938_517,
    "observed_gh_binary_bytes": 41_775_416,
    "platform": "windows_amd64",
}

STATUS_FIELDS = {
    "OFFICIAL_GRADER_SEMANTICS_AND_DISCRIMINATION": "ESTABLISHED_BY_P0_1_5",
    "OFFICIAL_GRADER_IMAGE_INTEGRITY": "ESTABLISHED",
    "OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH": "NOT_YET_REACHED_ON_EXEC_012",
    "OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START": "NOT_YET_REACHED_ON_EXEC_012",
    "PERFORMANCE": "NOT_MEASURED",
}

ZERO_ACTUALS: dict[str, int | float] = {
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

# D1.11 records which implementation blobs constituted its historical seal.
# These historical-only documents must still be byte-identical in the D1.12
# tree even though active integration files such as readiness and the workflow
# are deliberately replaced by D1.12.
IMMUTABLE_D111_CURRENT_PATHS = (
    D111_AMENDMENT_PATH,
    D111_INVENTORY_PATH,
    "reports/TRIMEM_D111_ACTIVATION_LIFECYCLE_CORRECTION.md",
    "scripts/trimem_d111_gate_contract.py",
    "scripts/trimem_d111_reseal.py",
    "tests/fixtures/trimem_d111/exec_011_branch_transition.json",
)

# This is the complete D1.12 control-plane diff vocabulary.  The sentinel is
# intentionally absent: it may exist only in the single-file child commit.
IMPLEMENTATION_PATHS = (
    ".gitattributes",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/readiness_requirements.json",
    "configs/trimem_v1/gh_cli_lock.json",
    "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_d112_reseal.py",
    "scripts/trimem_development_trigger_d112.py",
    "scripts/trimem_development_trigger_preflight.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_install_pinned_gh.py",
    "scripts/trimem_multi_swe_contract.py",
    "scripts/trimem_verify_ready.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_d110_status_and_reseal.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
    "tests/unit/test_trimem_d16_native_action.py",
    "tests/unit/test_trimem_d112_e1_trigger.py",
    "tests/unit/test_trimem_d112_status_and_reseal.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    "tests/unit/test_trimem_pinned_gh.py",
)
GENERATED_PATHS = frozenset(
    {
        AMENDMENT_PATH.relative_to(ROOT).as_posix(),
        INVENTORY_PATH.relative_to(ROOT).as_posix(),
        "artifacts/trimem_v1/freeze.json",
    }
)
ALLOWED_CHANGED_PATHS = frozenset(IMPLEMENTATION_PATHS) | GENERATED_PATHS
REQUIRED_CHANGED_PATHS = {
    ".gitattributes": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH.relative_to(ROOT).as_posix(): "A",
    INVENTORY_PATH.relative_to(ROOT).as_posix(): "A",
    "artifacts/trimem_v1/freeze.json": "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    "configs/trimem_v1/gh_cli_lock.json": "M",
    "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md": "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_d112_reseal.py": "A",
    "scripts/trimem_development_trigger_d112.py": "A",
    "scripts/trimem_development_trigger_preflight.py": "M",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_install_pinned_gh.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_d112_e1_trigger.py": "A",
    "tests/unit/test_trimem_d112_status_and_reseal.py": "A",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
    "tests/unit/test_trimem_pinned_gh.py": "M",
}

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class D112ResealError(ValueError):
    """The D1.12 history, source, authority boundary, or seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D112ResealError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def canonical_indented_bytes(value: Any) -> bytes:
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


def _strict_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    require(not raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM is forbidden: {label}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            require(key not in value, f"duplicate JSON key in {label}: {key}")
            value[key] = child
        return value

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D112ResealError(f"invalid strict JSON: {label}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {label}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing regular file: {path}")
    return _strict_json_bytes(path.read_bytes(), label=str(path))


def source_bytes(relative: str) -> bytes:
    path = PurePosixPath(relative)
    require(
        not path.is_absolute() and ".." not in path.parts,
        f"unsafe D1.12 path: {relative}",
    )
    target = ROOT.joinpath(*path.parts)
    require(target.is_file() and not target.is_symlink(), f"missing regular file: {relative}")
    return target.read_bytes()


def _top_level_function_source(source: str, name: str) -> str:
    try:
        module = ast.parse(source)
    except SyntaxError as exc:
        raise D112ResealError("D1.12 trigger source is not valid Python") from exc
    matches = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    require(len(matches) == 1, f"D1.12 trigger function identity differs: {name}")
    node = matches[0]
    require(node.end_lineno is not None, f"D1.12 trigger function has no extent: {name}")
    lines = source.splitlines(keepends=True)
    return "".join(lines[node.lineno - 1 : node.end_lineno])


def _git_environment() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LANG": "C",
        "LC_ALL": "C",
    }


def git(*args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            *args,
        ],
        cwd=ROOT,
        env=_git_environment(),
        capture_output=True,
        check=False,
        text=text,
    )


def _git_text(*args: str) -> str:
    completed = git(*args, text=True)
    require(completed.returncode == 0, "Git query failed: " + " ".join(args))
    return completed.stdout.strip()


def _git_lines(*args: str) -> list[str]:
    output = _git_text(*args)
    return output.splitlines() if output else []


def git_blob(commit: str, relative: str) -> bytes:
    require(HEX40.fullmatch(commit) is not None, "historical commit is malformed")
    path = PurePosixPath(relative)
    require(
        not path.is_absolute() and ".." not in path.parts,
        f"unsafe Git blob path: {relative}",
    )
    completed = git("show", f"{commit}:{relative}")
    require(completed.returncode == 0, f"Git blob is unavailable: {commit}:{relative}")
    return bytes(completed.stdout)


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    completed = git("merge-base", "--is-ancestor", ancestor, descendant)
    require(completed.returncode in {0, 1}, "Git ancestry query failed")
    return completed.returncode == 0


def current_activation_record() -> dict[str, Any]:
    """Return the committed source-state record; never infer EXEC authority."""

    return {
        "actual_execution_authorized": False,
        "benchmark_image_pulls": 0,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "external_execution_approval_received": False,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": REQUEST_PATH,
        "request_present_in_activation_source": False,
        "schema": "trimem/development-exec-012-activation/1.0",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def validate_historical_d111() -> dict[str, Any]:
    """Verify D1.11 only from the immutable baseline and its declared hashes."""

    require(
        _git_text("cat-file", "-t", BASE_HEAD) == "commit",
        "immutable D1.11 baseline commit is unavailable",
    )
    require(
        _git_text("rev-list", "--parents", "-n", "1", BASE_HEAD)
        == f"{BASE_HEAD} {PREVIOUS_EXECUTION_HEAD}",
        "immutable D1.11 baseline is not the exact child of _011",
    )
    require(_is_ancestor(BASE_HEAD, _git_text("rev-parse", "HEAD")), "D1.11 is not an ancestor")
    blobs: dict[str, bytes] = {}
    for relative, digest in HISTORICAL_D111_SHA256.items():
        raw = git_blob(BASE_HEAD, relative)
        require(sha256(raw) == digest, f"immutable D1.11 blob differs: {relative}")
        blobs[relative] = raw

    amendment = _strict_json_bytes(blobs[D111_AMENDMENT_PATH], label=D111_AMENDMENT_PATH)
    inventory = _strict_json_bytes(blobs[D111_INVENTORY_PATH], label=D111_INVENTORY_PATH)
    freeze = _strict_json_bytes(blobs[D111_FREEZE_PATH], label=D111_FREEZE_PATH)
    require(
        blobs[D111_AMENDMENT_PATH] == canonical_bytes(amendment)
        and blobs[D111_INVENTORY_PATH] == canonical_bytes(inventory)
        and blobs[D111_FREEZE_PATH] == canonical_indented_bytes(freeze),
        "immutable D1.11 JSON bytes are not canonical",
    )
    require(
        amendment.get("schema") == "trimem/development-activation-lifecycle-amendment/1.0"
        and inventory.get("schema") == "trimem/development-activation-lifecycle-inventory/1.0"
        and amendment.get("status") == "FROZEN_CREDENTIAL_FREE_EXEC_011_FAILURE_CORRECTED"
        and inventory.get("status") == "FROZEN_CREDENTIAL_FREE_EXEC_011_FAILURE_CORRECTED"
        and freeze.get("schema") == "trimem/freeze/1.0",
        "immutable D1.11 document identity differs",
    )
    implementation = inventory.get("implementation_sha256")
    freeze_files = freeze.get("files")
    require(
        isinstance(implementation, Mapping)
        and implementation
        and amendment.get("implementation_sha256") == implementation
        and isinstance(freeze_files, Mapping),
        "immutable D1.11 implementation inventory is malformed",
    )
    for relative, digest in implementation.items():
        require(
            isinstance(relative, str)
            and isinstance(digest, str)
            and HEX64.fullmatch(digest) is not None,
            "immutable D1.11 implementation hash is malformed",
        )
        raw = git_blob(BASE_HEAD, relative)
        require(sha256(raw) == digest, f"D1.11 inventory hash differs: {relative}")
        require(
            freeze_files.get(relative) == {"bytes": len(raw), "sha256": digest},
            f"D1.11 freeze omits inventory blob: {relative}",
        )
    for relative in IMMUTABLE_D111_CURRENT_PATHS:
        require(
            source_bytes(relative) == git_blob(BASE_HEAD, relative),
            f"immutable D1.11 current-tree file differs: {relative}",
        )
    return {
        "amendment_sha256": D111_AMENDMENT_SHA256,
        "baseline_head": BASE_HEAD,
        "freeze_sha256": BASE_FREEZE_SHA256,
        "implementation_files": len(implementation),
        "inventory_sha256": D111_INVENTORY_SHA256,
        "request_011_attempt_one_consumed": True,
        "request_011_model_api_calls": 0,
        "request_011_official_grader_runs": 0,
        "request_011_paid_model_calls": 0,
        "request_011_run_attempt": PREVIOUS_RUN_ATTEMPT,
        "request_011_run_id": PREVIOUS_RUN_ID,
        "status": "PASS",
    }


def _sentinel_parent(execution_head: str) -> str:
    parents = _git_text("rev-list", "--parents", "-n", "1", execution_head).split()
    require(len(parents) == 2 and parents[0] == execution_head, "_012 must be single-parent")
    return parents[1]


def validate_optional_exec_012_boundary() -> str | None:
    """Return the exact `_012` execution HEAD, or ``None`` at its source.

    If present, `_012` must be the checked-out HEAD and the only change in its
    one-parent commit.  Full request validation is lazily delegated to the
    active trigger so importing this resealer never loads activation/runtime
    code in the source phase.
    """

    head = _git_text("rev-parse", "HEAD")
    require(HEX40.fullmatch(head) is not None, "current HEAD is malformed")
    additions = _git_lines("log", "--format=%H", "--diff-filter=A", head, "--", REQUEST_PATH)
    target = ROOT.joinpath(*PurePosixPath(REQUEST_PATH).parts)
    if not additions:
        require(
            not target.exists() and not target.is_symlink(),
            "uncommitted or non-historical _012 request is forbidden",
        )
        return None
    require(additions == [head], "_012 must have exactly one addition at current HEAD")
    parent = _sentinel_parent(head)
    changes = _git_lines(
        "diff-tree",
        "--no-ext-diff",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        head,
    )
    require(changes == [f"A\t{REQUEST_PATH}"], "_012 commit is not sentinel-only")
    entry = _git_text("ls-tree", "--full-tree", head, "--", REQUEST_PATH).split("\t", 1)
    require(
        len(entry) == 2
        and entry[1] == REQUEST_PATH
        and entry[0].split()[:2] == ["100644", "blob"],
        "_012 is not a regular non-executable 100644 Git blob",
    )
    require(
        not _git_lines("log", "--format=%H", parent, "--", REQUEST_PATH),
        "_012 exists in activation-source history",
    )
    require(target.is_file() and not target.is_symlink(), "checked-out _012 is not regular")
    trigger = importlib.import_module("trimem_development_trigger_d112")
    require(
        getattr(trigger, "SENTINEL_PATH", None) == REQUEST_PATH
        and getattr(trigger, "REQUEST_ID", None) == REQUEST_ID,
        "D1.12 trigger/reseal request identity differs",
    )
    try:
        trigger.validate_sentinel_commit(
            ROOT,
            head,
            expected_parent=parent,
            require_checked_out_head=True,
        )
    except Exception as exc:
        raise D112ResealError("D1.12 trigger rejected the _012 boundary") from exc
    return head


def _source_head(execution_head: str | None) -> str:
    return _git_text("rev-parse", "HEAD") if execution_head is None else _sentinel_parent(execution_head)


def verify_changed_path_coverage(source_head: str | None = None) -> tuple[str, ...]:
    selected = _git_text("rev-parse", "HEAD") if source_head is None else source_head
    require(
        HEX40.fullmatch(selected) is not None
        and selected != BASE_HEAD
        and _is_ancestor(BASE_HEAD, selected),
        "D1.12 source is not a strict descendant of immutable D1.11",
    )
    completed = git(
        "diff",
        "--no-ext-diff",
        "--no-renames",
        "--name-status",
        "-z",
        BASE_HEAD,
        selected,
    )
    require(completed.returncode == 0, "cannot enumerate D1.12 committed paths")
    pieces = [piece for piece in bytes(completed.stdout).split(b"\0") if piece]
    require(len(pieces) % 2 == 0, "D1.12 changed-path stream is malformed")
    changes: dict[str, str] = {}
    try:
        for index in range(0, len(pieces), 2):
            status = pieces[index].decode("ascii", errors="strict")
            relative = pieces[index + 1].decode("utf-8", errors="strict")
            require(status in {"A", "M"}, f"D1.12 diff status is forbidden: {status}")
            require(relative not in changes, f"D1.12 path appears twice: {relative}")
            changes[relative] = status
    except UnicodeDecodeError as exc:
        raise D112ResealError("D1.12 changed path is not canonical UTF-8") from exc
    unexpected = sorted(set(changes) - ALLOWED_CHANGED_PATHS)
    require(not unexpected, "D1.12 paths escape the explicit seal: " + ", ".join(unexpected))
    for relative, status in REQUIRED_CHANGED_PATHS.items():
        require(
            changes.get(relative) == status,
            f"required D1.12 change is missing or has wrong status: {relative}",
        )
    require(
        not _git_lines("log", "--format=%H", selected, "--", REQUEST_PATH),
        "_012 exists in activation-source history",
    )
    tracked = _git_lines("ls-files")
    forbidden = [
        relative
        for relative in tracked
        if relative.endswith((".pyc", ".pyo"))
        or "__pycache__" in PurePosixPath(relative).parts
        or any(
            part in {"build", "dist"} or part.endswith(".egg-info")
            for part in PurePosixPath(relative).parts
        )
    ]
    require(not forbidden, f"tracked build artifacts are forbidden: {forbidden}")
    return tuple(sorted(changes))


def validate_protected_runtime_contract() -> dict[str, Any]:
    """Seal the credential-free pre-setup and cache-only service boundary.

    This is a source inspection only.  It deliberately does not invoke a
    runner, Docker, GitHub, a protected environment, or any benchmark code.
    """

    trigger = importlib.import_module("trimem_development_trigger_d112")
    expected_constants = {
        "DOCKER_AUTHORITY_ENV": DOCKER_AUTHORITY_ENV,
        "DOCKER_CLIENT_BYTES": DOCKER_CLIENT_BYTES,
        "DOCKER_CLIENT_PATH": DOCKER_CLIENT_PATH,
        "DOCKER_CLIENT_SHA256": DOCKER_CLIENT_SHA256,
        "DOCKER_CREATE_PULL_NEVER_MARKER": DOCKER_CREATE_PULL_NEVER_MARKER,
        "DOCKER_LOCAL_PREFIX": DOCKER_LOCAL_PREFIX,
        "DOCKER_ROOT_DIRECTORY": DOCKER_ROOT_DIRECTORY,
        "DOCKER_VERSION": DOCKER_VERSION,
        "EXACT_PYTHON_LIBRARY_PATH": WSL_EXACT_PYTHON_LIBRARY_PATH,
        "EXACT_PYTHON_ROOT": WSL_EXACT_PYTHON_ROOT,
        "PYTHON_TOOLCACHE_COMPLETE_BYTES": PYTHON_TOOLCACHE_COMPLETE_BYTES,
        "PYTHON_TOOLCACHE_COMPLETE_PATH": PYTHON_TOOLCACHE_COMPLETE_PATH,
        "PYTHON_TOOLCACHE_COMPLETE_SHA256": PYTHON_TOOLCACHE_COMPLETE_SHA256,
        "QDRANT_SERVICE_IMAGE": QDRANT_SERVICE_IMAGE,
        "RUNNER_DISTRIBUTION": RUNNER_DISTRIBUTION,
        "RUNNER_NAMES": RUNNER_NAMES,
        "RUNNER_ROOTS": RUNNER_ROOTS,
        "RUNNER_SERVICE_GID": RUNNER_SERVICE_GID,
        "RUNNER_SERVICE_UID": RUNNER_SERVICE_UID,
        "RUNNER_TOOL_CACHE": RUNNER_TOOL_CACHE,
        "RUNNER_WSL_USER": RUNNER_WSL_USER,
        "SERVICE_CONTAINER_NAME_PREFIX": SERVICE_CONTAINER_NAME_PREFIX,
        "SERVICE_IMAGE_REFS": SERVICE_IMAGE_REFS,
        "SERVICE_PORTS": SERVICE_PORTS,
        "SERVICE_READY_POLL_SECONDS": SERVICE_READY_POLL_SECONDS,
        "SERVICE_READY_TIMEOUT_SECONDS": SERVICE_READY_TIMEOUT_SECONDS,
        "SERVICE_STATE_FILENAME": SERVICE_STATE_FILENAME,
        "SERVICE_STATE_SCHEMA": SERVICE_STATE_SCHEMA,
        "POSTGRES_SERVICE_IMAGE": POSTGRES_SERVICE_IMAGE,
    }
    require(
        all(
            getattr(trigger, name, None) == expected
            for name, expected in expected_constants.items()
        ),
        "D1.12 protected runtime constants differ",
    )

    trigger_source = source_bytes(
        "scripts/trimem_development_trigger_d112.py"
    ).decode("utf-8", errors="strict")
    workflow = source_bytes(".github/workflows/trimem-benchmark.yml").decode(
        "utf-8", errors="strict"
    )
    function_names = (
        "validate_pre_setup_cache_host",
        "_require_pre_setup_runner_tool_cache_binding",
        "_observe_local_runner_identity",
        "_validate_protected_runner_readiness",
        "collect_protected_runner_readiness",
        "validate_protected_runner_preflight",
        "_validate_docker_root_directory",
        "_expected_service_images",
        "_probe_local_service_ports_available",
        "_service_state_path",
        "_protected_execution_context",
        "_validate_service_state",
        "_read_service_state",
        "_require_service_state_metadata",
        "_require_service_state_process_identity",
        "_read_direct_service_state_bytes",
        "_service_create_argv",
        "_observe_state_bound_services",
        "_rollback_created_services",
        "start_protected_services",
        "_qdrant_ready",
        "verify_protected_services",
        "_cleanup_state_free_partial_services",
        "_cleanup_state_bound_services",
        "cleanup_protected_services",
        "_require_no_pending_benchmark_consumers",
        "_request_execution_contracts",
        "write_request",
    )
    functions = {
        name: _top_level_function_source(trigger_source, name)
        for name in function_names
    }

    pre_setup = functions["validate_pre_setup_cache_host"]
    pre_setup_tool_cache = functions["_require_pre_setup_runner_tool_cache_binding"]
    local_lock = _top_level_function_source(trigger_source, "_verify_local_file_lock")
    require(
        'job in {"bounded-context-preflight", "frozen-serial-phase"}'
        in pre_setup
        and 'if job == "bounded-context-preflight":' in pre_setup
        and "_validate_runner_readiness_freshness(readiness, now=now)" in pre_setup
        and "len(matching) == 1" in pre_setup
        and "RUNNER_NAMES[matching[0]]" in pre_setup
        and "_observe_local_runner_identity()" in pre_setup
        and "_require_pre_setup_runner_tool_cache_binding(" in pre_setup
        and "active_root=RUNNER_ROOTS[matching[0]]" in pre_setup
        and "Path(PYTHON_TOOLCACHE_COMPLETE_PATH)" in pre_setup
        and "expected_bytes=PYTHON_TOOLCACHE_COMPLETE_BYTES" in pre_setup
        and "expected_sha256=PYTHON_TOOLCACHE_COMPLETE_SHA256" in pre_setup
        and 'label="pre-setup exact Python toolcache complete marker"' in pre_setup
        and "path.is_file()" in local_lock
        and "not path.is_symlink()" in local_lock
        and "path.resolve(strict=True) == path" in local_lock
        and "path.stat().st_size == expected_bytes" in local_lock
        and "digest.hexdigest() == expected_sha256" in local_lock,
        "D1.12 pre-setup direct toolcache marker contract differs",
    )
    require(
        'expected_value = f"{active_root}/_work/_tool"' in pre_setup_tool_cache
        and 'bindings.get("RUNNER_TOOL_CACHE") == expected_value'
        in pre_setup_tool_cache
        and "selected.is_dir()" in pre_setup_tool_cache
        and "selected.is_symlink()" in pre_setup_tool_cache
        and "selected_resolved == central" in pre_setup_tool_cache
        and "central.is_dir()" in pre_setup_tool_cache
        and "not central.is_symlink()" in pre_setup_tool_cache
        and "central_resolved == central" in pre_setup_tool_cache,
        "D1.12 active-root to central toolcache binding differs",
    )

    protected_validator = functions["_validate_protected_runner_readiness"]
    protected_collector = functions["collect_protected_runner_readiness"]
    protected_preflight = functions["validate_protected_runner_preflight"]
    require(
        "del now" in protected_preflight
        and "_validate_runner_readiness_freshness" not in protected_preflight
        and "collect_protected_runner_readiness(" in protected_preflight
        and "for root_value in RUNNER_ROOTS:" in protected_collector
        and "len(matching_roots) == 1" in protected_collector
        and "RUNNER_NAMES[matching_roots[0]]" in protected_collector
        and "len(active_listeners) == 1" in protected_collector
        and "len(teardown_listeners) <= 1" in protected_collector
        and "len(listeners) == len(active_listeners) + len(teardown_listeners)"
        in protected_collector
        and 'config.get("disableUpdate") is True' in protected_collector
        and 'config.get("ephemeral") is True' in protected_collector
        and "_observe_local_runner_identity()" in protected_collector
        and 'evidence.get("runner_gid") == RUNNER_SERVICE_GID'
        in protected_validator
        and 'evidence.get("runner_uid") == RUNNER_SERVICE_UID'
        in protected_validator
        and 'evidence.get("runner_user") == RUNNER_WSL_USER'
        in protected_validator
        and 'evidence.get("stale_runner_roots_absent") == list(STALE_RUNNER_ROOTS)'
        in protected_validator
        and 'teardown.get("root") == inactive_root' in protected_validator,
        "D1.12 protected live-runner supersession contract differs",
    )

    docker_version = _top_level_function_source(trigger_source, "_validate_docker_version")
    docker_root = functions["_validate_docker_root_directory"]
    docker_help = _top_level_function_source(
        trigger_source, "_validate_docker_pull_never_help"
    )
    secret_validator = _top_level_function_source(
        trigger_source, "_validate_secret_free_branch_environment"
    )
    forbidden_name = _top_level_function_source(
        trigger_source, "_is_forbidden_environment_name"
    )
    docker_client_lock = _top_level_function_source(
        trigger_source, "_verify_local_docker_client"
    )
    require(
        ') | DOCKER_AUTHORITY_ENV' in trigger_source
        and "_forbidden_environment_names(environ)" in secret_validator
        and "name.upper().startswith(\"DOCKER_\")" in forbidden_name
        and "Path(DOCKER_CLIENT_PATH)" in docker_client_lock
        and "expected_bytes=DOCKER_CLIENT_BYTES" in docker_client_lock
        and "expected_sha256=DOCKER_CLIENT_SHA256" in docker_client_lock
        and "stat.S_IMODE(observed.st_mode) == 0o755" in docker_client_lock
        and "observed.st_uid == 0" in docker_client_lock
        and "observed.st_gid == 0" in docker_client_lock
        and 'raw == f"{DOCKER_VERSION} {DOCKER_VERSION}"' in docker_version
        and "raw == DOCKER_ROOT_DIRECTORY" in docker_root
        and "DOCKER_CREATE_PULL_NEVER_MARKER" in docker_help
        and "DOCKER_LOCAL_PREFIX = (\n    DOCKER_CLIENT_PATH,\n    \"--host\",\n"
        '    "unix:///var/run/docker.sock",\n)' in trigger_source
        and '[*DOCKER_LOCAL_PREFIX, "pull"' not in trigger_source
        and '[*DOCKER_LOCAL_PREFIX, "login"' not in trigger_source,
        "D1.12 local Docker authority boundary differs",
    )
    require(
        "_validate_docker_root_directory(" in protected_collector
        and "_verify_local_docker_client()" in protected_collector
        and "_validate_docker_root_directory(" in functions["start_protected_services"]
        and "_verify_local_docker_client()" in functions["start_protected_services"]
        and "_validate_docker_root_directory(" in functions["verify_protected_services"]
        and "_verify_local_docker_client()" in functions["verify_protected_services"]
        and "_validate_docker_root_directory(" in functions["cleanup_protected_services"]
        and "_verify_local_docker_client()" in functions["cleanup_protected_services"],
        "D1.12 protected Docker binary/root revalidation differs",
    )

    expected_images = functions["_expected_service_images"]
    port_probe = functions["_probe_local_service_ports_available"]
    service_create = functions["_service_create_argv"]
    service_observer = functions["_observe_state_bound_services"]
    qdrant_ready = functions["_qdrant_ready"]
    require(
        "BENCHMARK_ENVIRONMENT_LOCK_PATH" in expected_images
        and 'record.get("image") == expected_image' in expected_images
        and "for port in SERVICE_PORTS.values():" in port_probe
        and 'ipv4.bind(("127.0.0.1", port))' in port_probe
        and "AF_INET6" not in port_probe
        and '"--pull=never"' in service_create
        and 'f"127.0.0.1:{port}:{port}"' in service_create
        and 'f"trimem.d112.role={role}"' in service_create
        and 'f"trimem.d112.run_id={run_id}"' in service_create
        and 'f"trimem.d112.source_head={source_head}"' in service_create
        and 'f"trimem.d112.trigger_head={trigger_head}"' in service_create
        and '"POSTGRES_DB=trimem_benchmark"' in service_create
        and '"POSTGRES_PASSWORD=postgres"' in service_create
        and '"POSTGRES_USER=postgres"' in service_create
        and '"pg_isready -U postgres -d trimem_benchmark"' in service_create
        and '"type=volume,source="' in service_create
        and '",target=/var/lib/postgresql/data"' in service_create
        and 'document.get("Image") == expected["image_id"]' in service_observer
        and 'config.get("Image") == expected["image"]' in service_observer
        and '_mapped_host_port(document, role=role) == expected["port"]'
        in service_observer
        and "_remaining_service_timeout(deadline, monotonic)" in service_observer
        and 'connection.request("GET", "/readyz")' in qdrant_ready
        and "response.status == 200" in qdrant_ready,
        "D1.12 exact service image, configuration, port, or readiness contract differs",
    )

    state_path = functions["_service_state_path"]
    state_validator = functions["_validate_service_state"]
    state_reader = functions["_read_service_state"]
    state_metadata = functions["_require_service_state_metadata"]
    state_process_identity = functions["_require_service_state_process_identity"]
    direct_state_reader = functions["_read_direct_service_state_bytes"]
    rollback = functions["_rollback_created_services"]
    start = functions["start_protected_services"]
    verify = functions["verify_protected_services"]
    partial_cleanup = functions["_cleanup_state_free_partial_services"]
    state_bound_cleanup = functions["_cleanup_state_bound_services"]
    cleanup = functions["cleanup_protected_services"]
    require(
        "root == expected_root" in state_path
        and "SERVICE_STATE_FILENAME" in state_path
        and "raw == canonical_bytes(state, trailing_lf=True)" in state_validator
        and 'state.get("schema") == SERVICE_STATE_SCHEMA' in state_validator
        and "_service_volume_name(run_id)" in state_validator
        and 'volume.get("destination") == "/var/lib/postgresql/data"'
        in state_validator
        and "_read_direct_service_state_bytes(path)" in state_reader
        and "path.lstat()" in direct_state_reader
        and "path.resolve(strict=True)" in direct_state_reader
        and "stat.S_ISREG(observed.st_mode)" in state_metadata
        and "not stat.S_ISLNK(observed.st_mode)" in state_metadata
        and "stat.S_IMODE(observed.st_mode) == 0o600" in state_metadata
        and "observed.st_uid == RUNNER_SERVICE_UID" in state_metadata
        and "observed.st_gid == RUNNER_SERVICE_GID" in state_metadata
        and "observed.st_nlink == 1" in state_metadata
        and "uid == RUNNER_SERVICE_UID" in state_process_identity
        and "gid == RUNNER_SERVICE_GID" in state_process_identity
        and "_require_service_state_process_identity(os.getuid(), os.getgid())"
        in direct_state_reader
        and direct_state_reader.count("_require_service_state_metadata(") == 3
        and 'os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)' in direct_state_reader
        and "os.fstat(descriptor)" in direct_state_reader
        and "(opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)"
        in direct_state_reader
        and "(after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)"
        in direct_state_reader
        and "_docker_container_ids" in start
        and "baseline_volume_names = _docker_volume_names(" in start
        and '"trimem.d112.role=postgres-data"' in start
        and 'f"trimem.d112.run_id={run_id}"' in start
        and 'f"trimem.d112.source_head={source_head}"' in start
        and 'f"trimem.d112.trigger_head={trigger_head}"' in start
        and "DOCKER_IMAGE_ID.fullmatch(image_id)" in start
        and "os.O_WRONLY | os.O_CREAT | os.O_EXCL" in start
        and 'getattr(os, "O_NOFOLLOW", 0)' in start
        and "0o600" in start
        and "os.fsync(stream.fileno())" in start
        and "_rollback_created_services(" in start
        and "== baseline" in rollback
        and "deadline = monotonic() + SERVICE_READY_TIMEOUT_SECONDS" in verify
        and "_remaining_service_timeout(deadline, monotonic)" in verify
        and 'health_status in {"starting", "healthy"}' in verify
        and "_qdrant_ready(" in verify
        and 'labels.get("trimem.d112.run_id") == str(run_id)' in partial_cleanup
        and "state-free partial service cleanup did not restore the baseline"
        in partial_cleanup
        and "allow_absent=True" in state_bound_cleanup
        and "present_ids.issubset(expected_ids)" in state_bound_cleanup
        and "baseline_volumes.issubset(current_volumes)" in state_bound_cleanup
        and "current_volumes - baseline_volumes <= {volume_name}"
        in state_bound_cleanup
        and '== state["baseline_volume_names"]' in state_bound_cleanup
        and "_cleanup_state_free_partial_services(" in cleanup
        and "_cleanup_state_bound_services(" in cleanup
        and "state_path.unlink()" in cleanup,
        "D1.12 run-bound service state, rollback, or cleanup contract differs",
    )

    zero_counter_functions = (
        pre_setup,
        protected_preflight,
        start,
        verify,
        cleanup,
    )
    require(
        all("ACTIVATION_ZERO_COUNTERS" in source for source in zero_counter_functions),
        "D1.12 protected lifecycle zero-authority counters differ",
    )

    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        workflow.count(branch_marker) == 1
        and workflow.count(bounded_marker) == 1
        and workflow.count(frozen_marker) == 1,
        "D1.12 protected workflow job identity differs",
    )
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    bounded_steps = re.findall(r"^      - name: (.+)$", bounded_job, re.MULTILINE)
    frozen_steps = re.findall(r"^      - name: (.+)$", frozen_job, re.MULTILINE)
    runner_tool_cache_forwarding = "RUNNER_TOOL_CACHE: ${{ runner.tool_cache }}"
    bounded_sequence = [
        "Checkout bounded-context correction",
        "Verify complete cached Python before setup-python",
        "Set up exact Python",
        "Re-observe exact self-hosted runner before any install or materialization",
        "Install hash-locked environment",
    ]
    protected_sequence = [
        "Checkout approved frozen source",
        "Verify complete cached Python before setup-python",
        "Set up exact Python",
        "Re-observe protected runner before cache-only service creation",
        "Start exact cache-only benchmark services",
        "Verify exact cache-only benchmark services",
        "Install hash-locked environment",
    ]
    require(
        bounded_steps[: len(bounded_sequence)] == bounded_sequence
        and frozen_steps[: len(protected_sequence)] == protected_sequence
        and bounded_job.count(runner_tool_cache_forwarding) == 2
        and frozen_job.count(runner_tool_cache_forwarding) == 2,
        "D1.12 checkout, pre-setup, protected reobservation, or install order differs",
    )
    cleanup_mode = '--cleanup-protected-services-event-path "$GITHUB_EVENT_PATH"'
    cleanup_marker = "      - name: Remove exact cache-only benchmark services\n"
    cleanup_adjacency = cleanup_marker + "        if: always()\n"
    require(
        frozen_steps[-1] == "Remove exact cache-only benchmark services"
        and frozen_job.count(cleanup_adjacency) == 1
        and frozen_job.count(cleanup_mode) == 1
        and "    services:\n" not in workflow
        and "job.services." not in workflow
        and "docker manifest" not in workflow
        and "docker pull" not in workflow,
        "D1.12 always-cleanup or no-native-service/no-pull workflow boundary differs",
    )
    exact_ipv4_consumers = (
        "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@"
        "127.0.0.1:5432/trimem_benchmark",
        "TRIMEM_QDRANT_URL: http://127.0.0.1:6333",
        "DATABASE_URL: postgresql://postgres:postgres@"
        "127.0.0.1:5432/trimem_benchmark",
        "PGHOST: 127.0.0.1",
        "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@"
        "127.0.0.1:5432/trimem_benchmark",
    )
    require(
        all(frozen_job.count(binding) == 1 for binding in exact_ipv4_consumers)
        and "@localhost:5432" not in frozen_job
        and "http://localhost:6333" not in frozen_job
        and "PGHOST: localhost" not in frozen_job,
        "D1.12 service consumers are not exact IPv4 loopback bindings",
    )
    selector = (
        "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, "
        "trimem-benchmark]"
    )
    label_markers = (
        "self-hosted",
        "linux",
        "x64",
        "trimem-ubuntu-24.04",
        "trimem-benchmark",
    )
    workflow_paths = _git_lines("ls-files", "--", ".github/workflows")
    require(
        ".github/workflows/trimem-benchmark.yml" in workflow_paths,
        "D1.12 benchmark workflow is not Git-tracked",
    )
    for relative in workflow_paths:
        if relative == ".github/workflows/trimem-benchmark.yml":
            continue
        other = source_bytes(relative).decode("utf-8", errors="strict")
        require(
            selector not in other
            and not all(marker in other for marker in label_markers),
            "another workflow can select the protected D1.12 runner",
        )

    pending = functions["_require_no_pending_benchmark_consumers"]
    writer = functions["write_request"]
    pending_literal = (
        'active_statuses = {"in_progress", "pending", "queued", '
        '"requested", "waiting"}'
    )
    first_pending_index = writer.find("_require_no_pending_benchmark_consumers(")
    gate_observation_index = writer.find("collect_remote_gate_evidence(")
    runner_observation_index = writer.find("collect_runner_readiness(")
    second_pending_index = writer.find(
        "_require_no_pending_benchmark_consumers(", first_pending_index + 1
    )
    exclusive_write_index = writer.find('target.open("xb")')
    require(
        pending_literal in pending
        and '"per_page=100"' in pending
        and '"--paginate"' in pending
        and '"--slurp"' in pending
        and 'pages = strict_json(b\'{"pages":\' + raw + b"}").get("pages")'
        in pending
        and "len(rows) == next(iter(totals))" in pending
        and "len(pages) == max(1, (len(rows) + 99) // 100)" in pending
        and 'row.get("path") == EXPECTED_WORKFLOW_PATH' in pending
        and 'row.get("status") in allowed_statuses' in pending
        and 'row["id"] not in observed_ids' in pending
        and "not any(row.get(\"status\") in active_statuses for row in rows)"
        in pending
        and writer.count("_require_no_pending_benchmark_consumers(") == 2
        and 0 <= first_pending_index < min(
            gate_observation_index, runner_observation_index
        )
        and max(gate_observation_index, runner_observation_index)
        < second_pending_index < exclusive_write_index,
        "D1.12 pending workflow consumer guard differs",
    )
    request_contract_source = functions["_request_execution_contracts"]
    request_bindings = {
        name: name
        for name in (
            "loader_environment_contract_sha256",
            "loader_preflight_sha256",
            "grader_lifecycle_sha256",
            "cell_commit_journal_sha256",
            "resume_disposition_sha256",
        )
    }
    request_contract = trigger._request_execution_contracts(request_bindings)
    require(
        isinstance(request_contract, Mapping)
        and request_contract.get("required_order") == list(REQUEST_REQUIRED_ORDER)
        and all(marker in request_contract_source for marker in REQUEST_REQUIRED_ORDER)
        and [request_contract_source.index(marker) for marker in REQUEST_REQUIRED_ORDER]
        == sorted(request_contract_source.index(marker) for marker in REQUEST_REQUIRED_ORDER),
        "D1.12 request semantic execution order differs",
    )

    return {
        "docker_authority": {
            "client_server_version": DOCKER_VERSION,
            "client_binary": {
                "bytes": DOCKER_CLIENT_BYTES,
                "path": DOCKER_CLIENT_PATH,
                "sha256": DOCKER_CLIENT_SHA256,
            },
            "create_pull_policy": "CREATE_PULL_NEVER_CACHE_ONLY",
            "forbidden_override_environment": sorted(DOCKER_AUTHORITY_ENV),
            "native_job_services_allowed": False,
            "registry_or_pull_allowed": False,
            "root_directory": DOCKER_ROOT_DIRECTORY,
            "socket": DOCKER_LOCAL_PREFIX[-1],
        },
        "pending_workflow_consumers": {
            "active_rows_required": 0,
            "checked_before_observation_and_before_write": True,
            "complete_paginated_snapshot_required": True,
            "single_transition_safe_snapshot": True,
            "statuses": list(PENDING_WORKFLOW_STATUSES),
        },
        "pre_setup_cache_host": {
            "active_root_tool_cache_template": "{active_root}/_work/_tool",
            "active_root_tool_cache_symlink_required": True,
            "allowed_jobs": ["bounded-context-preflight", "frozen-serial-phase"],
            "central_tool_cache_direct_directory": RUNNER_TOOL_CACHE,
            "marker_bytes": PYTHON_TOOLCACHE_COMPLETE_BYTES,
            "marker_direct_regular_non_symlink": True,
            "marker_path": PYTHON_TOOLCACHE_COMPLETE_PATH,
            "marker_sha256": PYTHON_TOOLCACHE_COMPLETE_SHA256,
            "runs_before_setup_python": True,
            "workflow_forwarding_count_per_job": 2,
        },
        "protected_live_runner": {
            "active_listener_count": 1,
            "dual_root_name_mapping": dict(zip(RUNNER_NAMES, RUNNER_ROOTS)),
            "process_identity": {
                "gid": RUNNER_SERVICE_GID,
                "uid": RUNNER_SERVICE_UID,
                "user": RUNNER_WSL_USER,
            },
            "source_snapshot_age_superseded_by_live_observation": True,
            "teardown_listener_count_max": 1,
        },
        "services": {
            "container_name_template": "trimem-d112-{run_id}-{role}",
            "images": dict(SERVICE_IMAGE_REFS),
            "loopback_ports": dict(SERVICE_PORTS),
            "postgres": {
                "database": "trimem_benchmark",
                "health_command": "pg_isready -U postgres -d trimem_benchmark",
                "password": "postgres",
                "user": "postgres",
                "volume_destination": "/var/lib/postgresql/data",
                "volume_name_template": "trimem-d112-{run_id}-postgres-data",
            },
            "qdrant_ready_endpoint": "http://127.0.0.1:6333/readyz",
            "readiness": {
                "clock": "MONOTONIC_WALL_CLOCK_INCLUDING_COMMAND_TIME",
                "poll_seconds": SERVICE_READY_POLL_SECONDS,
                "timeout_seconds": SERVICE_READY_TIMEOUT_SECONDS,
            },
            "state": {
                "baseline_restored_on_partial_or_final_cleanup": True,
                "canonical_utf8_json_plus_lf": True,
                "exclusive_mode_octal": "0600",
                "filename": SERVICE_STATE_FILENAME,
                "owner_gid": RUNNER_SERVICE_GID,
                "owner_uid": RUNNER_SERVICE_UID,
                "retry_safe_owned_or_absent_cleanup": True,
                "run_source_trigger_labels_required": True,
                "schema": SERVICE_STATE_SCHEMA,
            },
        },
        "workflow": {
            "always_cleanup_is_final_step": True,
            "other_custom_label_workflows_allowed": False,
            "protected_step_sequence": protected_sequence,
            "request_required_order": list(REQUEST_REQUIRED_ORDER),
            "service_consumer_bindings": list(exact_ipv4_consumers),
        },
        "zero_authority_actuals": dict(ZERO_ACTUALS),
    }


def validate_runner_isolation() -> dict[str, Any]:
    environment = read_json(ROOT / "configs/trimem_v1/benchmark_environment_lock.json")
    runner = environment.get("runner")
    labels = [
        "self-hosted",
        "linux",
        "x64",
        "trimem-ubuntu-24.04",
        "trimem-benchmark",
    ]
    require(
        isinstance(runner, Mapping)
        and runner.get("automatic_ci_runner_label") == "ubuntu-24.04"
        and runner.get("benchmark_exec_runner_labels") == labels
        and runner.get("benchmark_exec_runner_boundary") == RUNNER_BOUNDARY,
        "benchmark runner isolation contract differs",
    )
    workflow = source_bytes(".github/workflows/trimem-benchmark.yml").decode(
        "utf-8", errors="strict"
    )
    selector = "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, trimem-benchmark]"
    require(workflow.count(selector) == 2, "protected D1.12 runner selector differs")
    require(workflow.count("runs-on: ubuntu-24.04") == 1, "hosted preflight selector differs")
    trigger = importlib.import_module("trimem_development_trigger_d112")
    expected_trigger_constants = {
        "BENCHMARK_EXEC_RUNNER_BOUNDARY": RUNNER_BOUNDARY,
        "DOCKER_CLIENT_BYTES": DOCKER_CLIENT_BYTES,
        "DOCKER_CLIENT_PATH": DOCKER_CLIENT_PATH,
        "DOCKER_CLIENT_SHA256": DOCKER_CLIENT_SHA256,
        "PYTHON_TOOLCACHE_COMPLETE_BYTES": PYTHON_TOOLCACHE_COMPLETE_BYTES,
        "PYTHON_TOOLCACHE_COMPLETE_PATH": PYTHON_TOOLCACHE_COMPLETE_PATH,
        "PYTHON_TOOLCACHE_COMPLETE_SHA256": PYTHON_TOOLCACHE_COMPLETE_SHA256,
        "RUNNER_LISTENER_BYTES": RUNNER_LISTENER_BYTES,
        "RUNNER_LISTENER_SHA256": RUNNER_LISTENER_SHA256,
        "RUNNER_PACKAGE_ARCHIVE_BYTES": RUNNER_PACKAGE_ARCHIVE_BYTES,
        "RUNNER_PACKAGE_ARCHIVE_PATH": RUNNER_PACKAGE_ARCHIVE_PATH,
        "RUNNER_PACKAGE_ARCHIVE_SHA256": RUNNER_PACKAGE_ARCHIVE_SHA256,
        "RUNNER_PACKAGE_VERSION": RUNNER_PACKAGE_VERSION,
        "RUNNER_DISTRIBUTION": RUNNER_DISTRIBUTION,
        "RUNNER_SERVICE_GID": RUNNER_SERVICE_GID,
        "RUNNER_SERVICE_UID": RUNNER_SERVICE_UID,
        "RUNNER_TOOL_CACHE": RUNNER_TOOL_CACHE,
        "RUNNER_WSL_USER": RUNNER_WSL_USER,
    }
    require(
        all(
            getattr(trigger, name, None) == expected
            for name, expected in expected_trigger_constants.items()
        ),
        "D1.12 runner package constants differ",
    )
    trigger_source = source_bytes("scripts/trimem_development_trigger_d112.py").decode(
        "utf-8", errors="strict"
    )
    frozen_source = _top_level_function_source(
        trigger_source, "_validate_frozen_science_documents"
    )
    validator_source = _top_level_function_source(
        trigger_source, "_validate_runner_readiness"
    )
    windows_source = _top_level_function_source(
        trigger_source, "collect_runner_readiness"
    )
    local_source = _top_level_function_source(
        trigger_source, "collect_local_runner_host_readiness"
    )
    wsl_prefix_source = _top_level_function_source(
        trigger_source, "_wsl_command_prefix"
    )
    wsl_identity_source = _top_level_function_source(
        trigger_source, "_validate_wsl_runner_identity"
    )
    local_identity_source = _top_level_function_source(
        trigger_source, "_validate_local_runner_identity"
    )
    local_identity_observer_source = _top_level_function_source(
        trigger_source, "_observe_local_runner_identity"
    )
    wsl_lock_source = _top_level_function_source(
        trigger_source, "_verify_wsl_file_lock"
    )
    local_lock_source = _top_level_function_source(
        trigger_source, "_verify_local_file_lock"
    )
    environment_source = _top_level_function_source(
        trigger_source, "_strict_environment_bindings"
    )
    library_source = _top_level_function_source(
        trigger_source, "_require_exact_python_library_binding"
    )
    require(
        'frozen_runner.get("benchmark_exec_runner_boundary")' in frozen_source
        and "== BENCHMARK_EXEC_RUNNER_BOUNDARY" in frozen_source
        and 'row.get("disable_update") is True' in validator_source
        and 'row.get("ephemeral") is True' in validator_source
        and 'row.get("listener_version") == RUNNER_PACKAGE_VERSION'
        in validator_source
        and 'host.get("runner_package_archive_path")'
        in validator_source
        and "== RUNNER_PACKAGE_ARCHIVE_SHA256" in validator_source
        and windows_source.count("_verify_wsl_file_lock(") == 4
        and "RUNNER_PACKAGE_ARCHIVE_PATH" in windows_source
        and "expected_bytes=RUNNER_PACKAGE_ARCHIVE_BYTES" in windows_source
        and "expected_sha256=RUNNER_PACKAGE_ARCHIVE_SHA256" in windows_source
        and "PYTHON_TOOLCACHE_COMPLETE_PATH" in windows_source
        and "expected_bytes=PYTHON_TOOLCACHE_COMPLETE_BYTES" in windows_source
        and "expected_sha256=PYTHON_TOOLCACHE_COMPLETE_SHA256" in windows_source
        and "DOCKER_CLIENT_PATH" in windows_source
        and "expected_bytes=DOCKER_CLIENT_BYTES" in windows_source
        and "expected_sha256=DOCKER_CLIENT_SHA256" in windows_source
        and "expected_bytes=RUNNER_LISTENER_BYTES" in windows_source
        and "expected_sha256=RUNNER_LISTENER_SHA256" in windows_source
        and 'local_config.get("disableUpdate") is True' in windows_source
        and 'local_config.get("ephemeral") is True' in windows_source
        and "listener_version == RUNNER_PACKAGE_VERSION" in windows_source
        and "library_entries != ['LD_LIBRARY_PATH=' + expected_library_path]"
        in windows_source
        and "bindings.get('LD_LIBRARY_PATH') != expected_library_path"
        in windows_source
        and local_source.count("_verify_local_file_lock(") == 3
        and "RUNNER_PACKAGE_ARCHIVE_PATH" in local_source
        and "expected_bytes=RUNNER_PACKAGE_ARCHIVE_BYTES" in local_source
        and "expected_sha256=RUNNER_PACKAGE_ARCHIVE_SHA256" in local_source
        and "PYTHON_TOOLCACHE_COMPLETE_PATH" in local_source
        and "expected_bytes=PYTHON_TOOLCACHE_COMPLETE_BYTES" in local_source
        and "expected_sha256=PYTHON_TOOLCACHE_COMPLETE_SHA256" in local_source
        and "expected_bytes=RUNNER_LISTENER_BYTES" in local_source
        and "expected_sha256=RUNNER_LISTENER_SHA256" in local_source
        and 'config.get("disableUpdate") is True' in local_source
        and 'config.get("ephemeral") is True' in local_source
        and "listener_version == RUNNER_PACKAGE_VERSION" in local_source
        and local_source.count("_strict_environment_bindings(") == 2
        and local_source.count("_require_exact_python_library_binding(") == 3
        and "/usr/bin/id -u)" in windows_source
        and "/usr/bin/id -g)" in windows_source
        and "/usr/bin/id -un)" in windows_source
        and "_validate_wsl_runner_identity(wsl_identity)" in windows_source
        and '"--user"' in wsl_prefix_source
        and "RUNNER_DISTRIBUTION" in wsl_prefix_source
        and "RUNNER_WSL_USER" in wsl_prefix_source
        and 'arguments.extend(["--cd", cwd])' in wsl_prefix_source
        and 'expected = f"{RUNNER_SERVICE_UID}:{RUNNER_SERVICE_GID}:{RUNNER_WSL_USER}"'
        in wsl_identity_source
        and "raw == expected" in wsl_identity_source
        and "uid == RUNNER_SERVICE_UID" in local_identity_source
        and "gid == RUNNER_SERVICE_GID" in local_identity_source
        and "user == RUNNER_WSL_USER" in local_identity_source
        and "pwd.getpwuid(os.getuid()).pw_name" in local_identity_observer_source
        and "_validate_local_runner_identity(os.getuid(), os.getgid(), user)"
        in local_identity_observer_source
        and "runner_uid, runner_gid, runner_user = _observe_local_runner_identity()"
        in local_source
        and '"wsl_gid": runner_gid' in local_source
        and '"wsl_uid": runner_uid' in local_source
        and '"wsl_user": runner_user' in local_source
        and 'host.get("wsl_gid") == RUNNER_SERVICE_GID' in validator_source
        and 'host.get("wsl_uid") == RUNNER_SERVICE_UID' in validator_source
        and 'host.get("wsl_user") == RUNNER_WSL_USER' in validator_source,
        "D1.12 ephemeral runner evidence path differs",
    )
    require(
        'observed_bytes == str(expected_bytes)' in wsl_lock_source
        and 'observed_sha256 == f"{expected_sha256}  {path}"' in wsl_lock_source
        and "path.stat().st_size == expected_bytes" in local_lock_source
        and "digest.hexdigest() == expected_sha256" in local_lock_source
        and "require(name not in bindings" in environment_source
        and 'bindings.get("LD_LIBRARY_PATH") == EXACT_PYTHON_LIBRARY_PATH'
        in library_source,
        "D1.12 runner byte lock or environment decoder differs",
    )
    protected_runtime = validate_protected_runtime_contract()
    return {
        "automatic_hosted_label": "ubuntu-24.04",
        "benchmark_runner_boundary": RUNNER_BOUNDARY,
        "benchmark_self_hosted_labels": labels,
        "environment_binding": {
            "live_listener_count": 2,
            "persisted_env_count": 2,
            "required_name": "LD_LIBRARY_PATH",
            "required_value": WSL_EXACT_PYTHON_LIBRARY_PATH,
            "single_exact_binding_per_environment": True,
        },
        "exact_runner_count_required_before_request": 2,
        "local_registration": {
            "disable_update": True,
            "ephemeral": True,
        },
        "ordinary_hosted_job_can_match_benchmark_runner": False,
        "protected_runtime": protected_runtime,
        "runner_process_identity": {
            "gid": RUNNER_SERVICE_GID,
            "uid": RUNNER_SERVICE_UID,
            "user": RUNNER_WSL_USER,
        },
        "runner_listener_lock": {
            "bytes": RUNNER_LISTENER_BYTES,
            "sha256": RUNNER_LISTENER_SHA256,
            "version": RUNNER_PACKAGE_VERSION,
        },
        "runner_package_lock": {
            "archive_bytes": RUNNER_PACKAGE_ARCHIVE_BYTES,
            "archive_path": RUNNER_PACKAGE_ARCHIVE_PATH,
            "archive_sha256": RUNNER_PACKAGE_ARCHIVE_SHA256,
            "version": RUNNER_PACKAGE_VERSION,
        },
        "windows_to_wsl_transport": {
            "distribution": RUNNER_DISTRIBUTION,
            "explicit_user": RUNNER_WSL_USER,
            "identity_probe_binary": "/usr/bin/id",
        },
    }


def validate_github_observer_contract() -> dict[str, Any]:
    """Verify one byte-pinned cross-platform transport and bounded visibility.

    This validation inspects committed configuration and source only.  It does
    not execute ``gh`` or perform a GitHub API request.
    """

    lock = read_json(GH_CLI_LOCK_PATH)
    require(
        lock.get("schema") == GH_CLI_LOCK_SCHEMA
        and lock.get("version") == GH_CLI_VERSION
        and lock.get("release_tag") == "v2.97.0"
        and lock.get("platform") == "linux_amd64"
        and lock.get("expected_first_version_line") == GH_CLI_VERSION_LINE
        and lock.get("windows_observer") == WINDOWS_OBSERVER_LOCK,
        "cross-platform GitHub observer byte lock differs",
    )
    installer = source_bytes("scripts/trimem_install_pinned_gh.py").decode(
        "utf-8", errors="strict"
    )
    require(
        f'LOCK_SCHEMA = "{GH_CLI_LOCK_SCHEMA}"' in installer
        and installer.count("def verify_observer_gh(") == 1
        and "_verify_exact_gh_binary(lock, windows_contract, binary_path)"
        in installer
        and 'binary_path.name.casefold() != "gh.exe"' in installer
        and "Windows GitHub CLI observer must be an absolute gh.exe path"
        in installer
        and "pinned GitHub CLI observer platform is unsupported" in installer,
        "cross-platform GitHub observer verifier differs",
    )
    compatibility_source = source_bytes(
        "scripts/trimem_development_trigger_preflight.py"
    ).decode("utf-8", errors="strict")
    compatibility_validator = _top_level_function_source(
        compatibility_source, "_validate_gh_cli_lock_schema"
    )
    require(
        "LOCK_SCHEMA as CURRENT_GH_CLI_LOCK_SCHEMA" in compatibility_source
        and 'LEGACY_GH_CLI_LOCK_SCHEMA = "trimem/gh-cli-lock/1.0"'
        in compatibility_source
        and "schema == CURRENT_GH_CLI_LOCK_SCHEMA" in compatibility_validator
        and 'schema == LEGACY_GH_CLI_LOCK_SCHEMA and "windows_observer" not in gh_lock'
        in compatibility_validator
        and "_validate_gh_cli_lock_schema(gh_lock)" in compatibility_source,
        "shared historical GitHub CLI schema consumer differs",
    )
    attributes = source_bytes(".gitattributes").decode("utf-8", errors="strict")
    report_raw = source_bytes("reports/TRIMEM_D112_EXEC_012_ACTIVATION.md")
    report_attribute = "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md text eol=lf"
    require(
        attributes.splitlines().count(report_attribute) == 1
        and not report_raw.startswith(b"\xef\xbb\xbf")
        and b"\r" not in report_raw,
        "D1.12 report is not byte-stable LF text",
    )
    trigger = importlib.import_module("trimem_development_trigger_d112")
    require(
        getattr(trigger, "GH_CLI_LOCK_PATH", None)
        == GH_CLI_LOCK_PATH.relative_to(ROOT).as_posix()
        and getattr(trigger, "REMOTE_VISIBILITY_TIMEOUT_SECONDS", None) == 30
        and getattr(trigger, "REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS", None) == 2
        and getattr(trigger, "REMOTE_VISIBILITY_MAX_POLLS", None) == 16,
        "D1.12 GitHub observer visibility bounds differ",
    )
    trigger_source = source_bytes("scripts/trimem_development_trigger_d112.py").decode(
        "utf-8", errors="strict"
    )
    require(
        "from trimem_install_pinned_gh import load_gh_cli_lock, verify_observer_gh"
        in trigger_source
        and "verify_observer_gh(lock, Path(gh))" in trigger_source
        and "verify_installed_gh" not in trigger_source
        and trigger_source.count('shutil.which("gh")') == 1
        and "def _collect_remote_runner_rows(" in trigger_source
        and "return _collect_remote_runner_rows(*_pinned_gh_context())"
        in trigger_source
        and "== _collect_remote_runner_rows(gh, safe_environment)"
        in trigger_source
        and "current PR #18 exact-head visibility remained incomplete for 30 seconds"
        in trigger_source
        and "current _012 workflow run visibility remained incomplete for 30 seconds"
        in trigger_source,
        "D1.12 gate/runner observer transport or bounded polling differs",
    )
    public_repository_entrypoints = (
        "validate_correction_source",
        "collect_runner_readiness",
        "collect_local_runner_host_readiness",
        "validate_runner_host_preflight",
        "validate_pre_setup_cache_host",
        "validate_protected_runner_preflight",
        "start_protected_services",
        "verify_protected_services",
        "cleanup_protected_services",
        "build_request",
        "validate_request",
        "validate_sentinel_commit",
        "validate_branch_trigger",
        "write_request",
    )
    require(
        "def resolve_repository_root(" in trigger_source
        and '"rev-parse", "--show-toplevel"' in trigger_source
        and all(
            "resolve_repository_root(repository)"
            in _top_level_function_source(trigger_source, name)
            for name in public_repository_entrypoints
        ),
        "D1.12 public entrypoint Git top-level custody differs",
    )
    pull_source = _top_level_function_source(
        trigger_source, "_collect_current_pull_request"
    )
    execution_source = _top_level_function_source(
        trigger_source, "_validate_unique_execution_run"
    )
    branch_source = _top_level_function_source(trigger_source, "validate_branch_trigger")
    writer_source = _top_level_function_source(trigger_source, "write_request")
    recheck_source = _top_level_function_source(
        trigger_source, "_recheck_request_write_boundary"
    )
    wsl_python_source = _top_level_function_source(
        trigger_source, "_wsl_exact_python_argv"
    )
    runner_readiness_source = _top_level_function_source(
        trigger_source, "collect_runner_readiness"
    )
    runner_readiness_validator_source = _top_level_function_source(
        trigger_source, "_validate_runner_readiness"
    )
    local_runner_host_source = _top_level_function_source(
        trigger_source, "collect_local_runner_host_readiness"
    )
    deadline_marker = "deadline = monotonic() + REMOTE_VISIBILITY_TIMEOUT_SECONDS"
    require(
        "def _remaining_visibility_seconds(" in trigger_source
        and "def _sleep_for_visibility_retry(" in trigger_source
        and deadline_marker in pull_source
        and deadline_marker in execution_source
        and "timeout=command_timeout" in pull_source
        and "timeout=command_timeout" in execution_source
        and "allowed_stale_head: str | None" in pull_source
        and "observed_head == allowed_stale_head" in pull_source
        and "allowed_stale_head=before" in branch_source
        and "allowed_stale_pr_head=None" in writer_source
        and "_query_github_run_by_id(" in execution_source
        and 'candidate.get("id") == expected_run_id' in execution_source
        and "exact_workflow_rows" in execution_source
        and 'exact_run_id = exact_workflow_rows[0].get("id")'
        in execution_source
        and "exact_run_id == expected_run_id" in execution_source,
        "D1.12 monotonic deadline or contradiction policy differs",
    )
    require(
        getattr(trigger, "EXACT_PYTHON_ROOT", None) == WSL_EXACT_PYTHON_ROOT
        and getattr(trigger, "EXACT_PYTHON_LIBRARY_PATH", None)
        == WSL_EXACT_PYTHON_LIBRARY_PATH
        and 'EXACT_PYTHON_LIBRARY_PATH = f"{EXACT_PYTHON_ROOT}/lib"'
        in trigger_source
        and '"env"' in wsl_python_source
        and 'f"LD_LIBRARY_PATH={EXACT_PYTHON_LIBRARY_PATH}"'
        in wsl_python_source
        and 'f"{EXACT_PYTHON_ROOT}/bin/python"' in wsl_python_source
        and "os.environ" not in wsl_python_source
        and "getenv" not in wsl_python_source
        and runner_readiness_source.count("_wsl_exact_python_argv(") == 4
        and runner_readiness_source.count(
            '"exact_python_library_path": EXACT_PYTHON_LIBRARY_PATH'
        )
        == 1
        and 'host.get("exact_python_library_path") == EXACT_PYTHON_LIBRARY_PATH'
        in runner_readiness_validator_source
        and local_runner_host_source.count(
            '"exact_python_library_path": EXACT_PYTHON_LIBRARY_PATH'
        )
        == 1,
        "D1.12 WSL exact-Python shared-library transport differs",
    )
    remote_gate_index = writer_source.find("collect_remote_gate_evidence(")
    runner_readiness_index = writer_source.find("collect_runner_readiness(")
    recheck_index = writer_source.find("_recheck_request_write_boundary(")
    exclusive_create_index = writer_source.find('target.open("xb")')
    require(
        min(
            remote_gate_index,
            runner_readiness_index,
            recheck_index,
            exclusive_create_index,
        )
        >= 0
        and max(remote_gate_index, runner_readiness_index)
        < recheck_index
        < exclusive_create_index
        and "resolve_repository_root(repository)" in recheck_source
        and '"symbolic-ref", "--quiet", "HEAD"' in recheck_source
        and '"rev-parse", "HEAD"' in recheck_source
        and '"status", "--porcelain=v1", "--untracked-files=all"'
        in recheck_source
        and '"log"' in recheck_source
        and "SENTINEL_PATH" in recheck_source
        and "not os.path.lexists(target)" in recheck_source,
        "D1.12 post-observation pre-write custody differs",
    )
    return {
        "first_version_line": GH_CLI_VERSION_LINE,
        "lock_path": GH_CLI_LOCK_PATH.relative_to(ROOT).as_posix(),
        "lock_schema": GH_CLI_LOCK_SCHEMA,
        "observer_selection_policy": (
            "PLATFORM_EXACT_BYTES_AND_VERSION_NO_UNVERIFIED_FALLBACK"
        ),
        "shared_legacy_consumer": {
            "current_schema_from_shared_consumer": GH_CLI_LOCK_SCHEMA,
            "historical_schema": "trimem/gh-cli-lock/1.0",
            "historical_schema_requires_windows_observer_absent": True,
        },
        "windows_executable_name_policy": "CASEFOLD_EQUALS_GH_EXE",
        "report_line_ending_contract": "GIT_ATTRIBUTE_TEXT_EOL_LF",
        "platforms": {
            "linux_amd64": {
                "archive_sha256": lock["archive_sha256"],
                "binary_sha256": lock["extracted_gh_binary_sha256"],
            },
            "windows_amd64": {
                "archive_sha256": WINDOWS_OBSERVER_LOCK["archive_sha256"],
                "binary_sha256": WINDOWS_OBSERVER_LOCK[
                    "extracted_gh_binary_sha256"
                ],
            },
        },
        "same_verified_transport_for": [
            "current_pull_request",
            "current_execution_workflow_run",
            "source_workflow_runs",
            "repository_runners",
        ],
        "wsl_exact_python_probes": {
            "executable_path": f"{WSL_EXACT_PYTHON_ROOT}/bin/python",
            "launch_prefix": [
                "env",
                f"LD_LIBRARY_PATH={WSL_EXACT_PYTHON_LIBRARY_PATH}",
                f"{WSL_EXACT_PYTHON_ROOT}/bin/python",
            ],
            "library_path": WSL_EXACT_PYTHON_LIBRARY_PATH,
            "no_host_environment_fallback": True,
            "probe_sites": [
                "exact_python_version",
                "service_port_availability",
                "listener_identity_and_secret_name_absence",
                "runner_identity_and_config_secret_name_absence",
            ],
            "readiness_evidence_field": "host.exact_python_library_path",
        },
        "repository_custody": {
            "exact_git_top_level_required": True,
            "nested_or_superproject_path_rejected": True,
            "public_entrypoints": list(public_repository_entrypoints),
            "pre_write_recheck": [
                "exact_git_top_level",
                "expected_branch",
                "unchanged_source_head",
                "clean_tracked_and_untracked_worktree",
                "sentinel_absent_from_history_and_filesystem",
            ],
            "pre_write_recheck_occurs_after_remote_observations": True,
        },
        "visibility_polling": {
            "clock": "MONOTONIC_WALL_CLOCK_INCLUDING_API_COMMAND_TIME",
            "deadline_seconds": 30,
            "fail_immediately_for": [
                "malformed_or_contradictory_identity",
                "arbitrary_wrong_pr_head_sha",
                "current_execution_run_id_contradiction",
                "duplicate_or_rerun_workflow",
                "red_source_gate",
                "missing_or_nonready_runner_set",
            ],
            "interval_seconds": 2,
            "maximum_polls": 16,
            "poll_only": [
                "missing_or_incomplete_current_pr",
                "explicitly_allowed_immediate_predecessor_pr_head",
                "missing_or_incomplete_current_execution_workflow_run",
            ],
            "retry_sleep_policy": "CLAMP_TO_REMAINING_DEADLINE",
            "timeout_disposition": "FAIL_CLOSED_BEFORE_SENTINEL_OR_EXECUTION",
        },
    }


def validate_readiness() -> None:
    readiness = read_json(READINESS_PATH)
    status = readiness.get("current_status")
    authority = readiness.get("development_authorization_boundary")
    require(
        isinstance(status, Mapping)
        and "OFFICIAL_GRADER_VIABILITY" not in status
        and all(status.get(key) == value for key, value in STATUS_FIELDS.items())
        and status.get("CLASSIFICATION") == CLASSIFICATION
        and status.get("ENDPOINT") == ENDPOINT
        and status.get("FAILURE_SUBTYPE") == FAILURE_SUBTYPE
        and status.get("DEV_APPROVAL_ALLOWED") == "NO"
        and status.get("DEV_EXECUTION_ALLOWED") == "NO"
        and status.get("DEV_SCIENTIFIC_STATUS") == "NOT_STARTED_ON_EXEC_012"
        and status.get("SCIENTIFIC_RESULT") == "NO_DEVELOPMENT_SCIENTIFIC_RESULT",
        "D1.12 current status differs",
    )
    require(
        readiness.get("current_development_activation") == current_activation_record(),
        "D1.12 current activation record differs",
    )
    historical = _strict_json_bytes(
        git_blob(BASE_HEAD, D111_AMENDMENT_PATH), label=D111_AMENDMENT_PATH
    )
    require(
        readiness.get("historical_development_exec_011_activation_failure")
        == historical.get("exec_011_failure"),
        "historical _011 failure record differs",
    )
    require(
        isinstance(authority, Mapping)
        and authority.get("active_development_approval") is False
        and authority.get("approval_request_eligible") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("fresh_dev_execution_approval_required") is True
        and authority.get("fresh_execution_request_creation_authorized") is True
        and authority.get("future_recovery_authority_received") is True
        and authority.get("recovery_authorization_received") is True
        and authority.get("request_011_attempt_one_consumed") is True
        and authority.get("request_011_attempt_two_allowed") is False
        and authority.get("request_011_rerun_allowed") is False
        and authority.get("request_012_allowed_after_exact_remote_gates") is True
        and authority.get("request_012_authorized") is False
        and authority.get("request_012_created") is False
        and authority.get("meaning") == DEVELOPMENT_AUTHORITY_MEANING
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.12 development authority boundary differs",
    )


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    execution_head = validate_optional_exec_012_boundary()
    source_head = _source_head(execution_head)
    verify_changed_path_coverage(source_head)
    historical = validate_historical_d111()
    validate_readiness()
    runner = validate_runner_isolation()
    observer = validate_github_observer_contract()
    implementation = {
        relative: sha256(source_bytes(relative)) for relative in IMPLEMENTATION_PATHS
    }
    authority = {
        "actual_execution_authorized": False,
        "distinct_external_execution_approval_required": True,
        "external_execution_approval_received": False,
        "request_011_attempt_one_consumed": True,
        "request_011_rerun_allowed": False,
        "request_012_created": False,
        "request_012_creation_authorized": True,
        "request_012_execution_authorized": False,
        "sentinel_contains_execution_authority": False,
    }
    source_contract = {
        "baseline_head": BASE_HEAD,
        "baseline_freeze_sha256": BASE_FREEZE_SHA256,
        "changed_path_policy": "EXPLICIT_ALLOWLIST_VALIDATED_AT_CHECK_TIME",
        "execution_child_policy": "ONE_SINGLE_PARENT_100644_SENTINEL_ONLY_ADDITION",
        "request_absent_from_source_and_source_history": True,
    }
    amendment = {
        "activation": current_activation_record(),
        "authority_boundary": authority,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "historical_d111": historical,
        "github_observer": observer,
        "implementation_sha256": implementation,
        "runner_isolation": runner,
        "schema": AMENDMENT_SCHEMA,
        "source_contract": source_contract,
        "status": STATUS,
        "zero_cost_activation_actuals": dict(ZERO_ACTUALS),
    }
    inventory = {
        "allowed_changed_paths": sorted(ALLOWED_CHANGED_PATHS),
        "changed_path_policy": "VALIDATED_AT_CHECK_TIME_NOT_EMBEDDED",
        "classification": CLASSIFICATION,
        "documents": {
            "amendment": AMENDMENT_PATH.relative_to(ROOT).as_posix(),
            "readiness": READINESS_PATH.relative_to(ROOT).as_posix(),
            "report": REPORT_PATH.relative_to(ROOT).as_posix(),
        },
        "endpoint": ENDPOINT,
        "historical_d111": historical,
        "github_observer": observer,
        "implementation_sha256": implementation,
        "schema": INVENTORY_SCHEMA,
        "source_contract": source_contract,
        "status": STATUS,
    }
    return amendment, inventory


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value)
    fd, temp_name = tempfile.mkstemp(prefix=".trimem-d112-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_all() -> None:
    require(
        validate_optional_exec_012_boundary() is None,
        "D1.12 source artifacts cannot be rewritten after _012 creation",
    )
    amendment, inventory = build_artifacts()
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    execution_head = validate_optional_exec_012_boundary()
    amendment, inventory = build_artifacts()
    require(read_json(AMENDMENT_PATH) == amendment, "D1.12 amendment is stale")
    require(read_json(INVENTORY_PATH) == inventory, "D1.12 inventory is stale")
    import trimem_freeze

    trimem_freeze.check_freeze(ROOT)
    return {
        "benchmark_image_pulls": 0,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "request_011_attempt_one_consumed": True,
        "request_012_created": execution_head is not None,
        "request_012_execution_authorized": False,
        "research_freeze_sha256": sha256(source_bytes(D111_FREEZE_PATH)),
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
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
    except (D112ResealError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
