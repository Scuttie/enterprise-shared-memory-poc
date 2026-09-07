"""Build and verify the credential-free D1.12 ``_012`` activation seal.

D1.12 records authority to *create* one zero-authority request sentinel after
fresh source CI and runner-readiness gates.  It does not grant protected DEV
execution authority.  A separate external approval must be bound to the exact
sentinel commit and workflow attempt before credentials or benchmark work can
be reached.

The historical D1.11 seal is read from its immutable Git commit.  This module
performs no network, credential, Docker, grader, image, or model operation.
"""

from __future__ import annotations

import argparse
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
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/readiness_requirements.json",
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
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH.relative_to(ROOT).as_posix(): "A",
    INVENTORY_PATH.relative_to(ROOT).as_posix(): "A",
    "artifacts/trimem_v1/freeze.json": "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md": "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_d112_reseal.py": "A",
    "scripts/trimem_development_trigger_d112.py": "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_d112_e1_trigger.py": "A",
    "tests/unit/test_trimem_d112_status_and_reseal.py": "A",
    "tests/unit/test_trimem_development_trigger.py": "M",
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
        and runner.get("benchmark_exec_runner_labels") == labels,
        "benchmark runner labels are not collision-free",
    )
    workflow = source_bytes(".github/workflows/trimem-benchmark.yml").decode(
        "utf-8", errors="strict"
    )
    selector = "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, trimem-benchmark]"
    require(workflow.count(selector) == 2, "protected D1.12 runner selector differs")
    require(workflow.count("runs-on: ubuntu-24.04") == 1, "hosted preflight selector differs")
    return {
        "automatic_hosted_label": "ubuntu-24.04",
        "benchmark_self_hosted_labels": labels,
        "exact_runner_count_required_before_request": 2,
        "ordinary_hosted_job_can_match_benchmark_runner": False,
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
