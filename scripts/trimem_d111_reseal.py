"""Build and verify the credential-free D1.11 activation-lifecycle seal.

D1.11 records the terminal ``_011`` branch-preflight failure without rewriting
the spent D1.10 trigger.  It freezes two corrections for any future activation:

* historical workflow runs are selected only from immutable top-level run
  identity; the mutable ``pull_requests`` relationship is ignored; and
* benchmark runners use a repository-specific OS label which cannot satisfy a
  normal GitHub-hosted ``runs-on: ubuntu-24.04`` request.

This module performs no network, Docker, grader, credential, or model action.
"""

from __future__ import annotations

import argparse
import hashlib
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
    "artifacts/trimem_v1/development_activation_lifecycle_amendment.json"
)
INVENTORY_PATH = ROOT / (
    "artifacts/trimem_v1/development_activation_lifecycle_inventory.json"
)
READINESS_PATH = ROOT / "artifacts/trimem_v1/readiness_requirements.json"
FIXTURE_PATH = ROOT / "tests/fixtures/trimem_d111/exec_011_branch_transition.json"

AMENDMENT_SCHEMA = "trimem/development-activation-lifecycle-amendment/1.0"
INVENTORY_SCHEMA = "trimem/development-activation-lifecycle-inventory/1.0"
STATUS = "FROZEN_CREDENTIAL_FREE_EXEC_011_FAILURE_CORRECTED"
CLASSIFICATION = "POST_EXEC_011_ZERO_MODEL_ACTIVATION_LIFECYCLE_CORRECTION"
ENDPOINT = "TRIMEM_V1_DEV_INCOMPLETE"
FAILURE_SUBTYPE = "MUTABLE_HISTORICAL_PULL_REQUEST_ASSOCIATION"

SOURCE_HEAD = "155fe314631ef74828ea98b562036bdb0adca495"
EXECUTION_HEAD = "e54d04b0af9e738d311c389dc89cfd510fd7065b"
RUN_ID = 34_047_573_548
RUN_ATTEMPT = 1
REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011"
REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_011.json"
)
REQUEST_SHA256 = "75acaaa8f1f2f0dc138530dfc533df440e2c70f4ee885732b8297a8150de2fa0"
NEXT_REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_012.json"
)

HISTORICAL_D110_SHA256 = {
    ".github/workflows/trimem-benchmark.yml": (
        "61be12e8d5152c41aa2bfcd6b6579359d4176e37947f30df082b33fb873009f2"
    ),
    "artifacts/trimem_v1/development_grader_launch_stream_commit_amendment.json": (
        "8b6b979d4d21e57334b220ab37933436ff95bb387daf61c8473173f8383e1698"
    ),
    "artifacts/trimem_v1/development_grader_launch_stream_commit_inventory.json": (
        "4ad746c388e2ba93f1082853d4da582f687f9c1cc7b5b056b379f5ce58a34a8c"
    ),
    "artifacts/trimem_v1/freeze.json": (
        "74678dd3f340405c05fccf98f6f31e5c09796b3b3189c41cb1e94c2bd8d364cc"
    ),
    REQUEST_PATH: REQUEST_SHA256,
    "scripts/trimem_d110_reseal.py": (
        "f0c88e008597ce4b54cbbaa0f7a103ffd1b0a5e22850e6e171c370e9651c9c06"
    ),
    "scripts/trimem_development_trigger_d110.py": (
        "cc6d02c48af12de64f67bacd46d72149d382b1dcc16b2323e72e5630038670f9"
    ),
}

UNIQUE_RUNNER_LABEL = "trimem-ubuntu-24.04"
BENCHMARK_RUNNER_LABELS = (
    "self-hosted",
    "linux",
    "x64",
    UNIQUE_RUNNER_LABEL,
    "trimem-benchmark",
)

STATUS_FIELDS = {
    "OFFICIAL_GRADER_SEMANTICS_AND_DISCRIMINATION": "ESTABLISHED_BY_P0_1_5",
    "OFFICIAL_GRADER_IMAGE_INTEGRITY": "ESTABLISHED",
    "OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH": "NOT_REACHED_ON_EXEC_011",
    "OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START": "NOT_REACHED_ON_EXEC_011",
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

# Every post-_011 committed change must be named here or be a generated seal.
IMPLEMENTATION_PATHS = (
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/readiness_requirements.json",
    "configs/trimem_v1/benchmark_environment_lock.json",
    "reports/TRIMEM_D111_ACTIVATION_LIFECYCLE_CORRECTION.md",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_d111_gate_contract.py",
    "scripts/trimem_d111_reseal.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_verify_ready.py",
    "tests/fixtures/trimem_d111/exec_011_branch_transition.json",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_d110_status_and_reseal.py",
    "tests/unit/test_trimem_d111_gate_contract.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
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
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class D111ResealError(ValueError):
    """The D1.11 history, implementation, or generated seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D111ResealError(message)


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


def read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    require(not raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM is forbidden: {path}")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D111ResealError(f"invalid strict JSON: {path}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {path}")
    return value


def source_bytes(relative: str) -> bytes:
    path = PurePosixPath(relative)
    require(
        not path.is_absolute() and ".." not in path.parts,
        f"unsafe D1.11 path: {relative}",
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


def git_blob(commit: str, relative: str) -> bytes:
    require(HEX40.fullmatch(commit) is not None, "historical commit is malformed")
    completed = git("show", f"{commit}:{relative}")
    require(completed.returncode == 0, f"historical Git blob is unavailable: {relative}")
    return bytes(completed.stdout)


def _git_lines(*args: str) -> list[str]:
    completed = git(*args, text=True)
    require(completed.returncode == 0, "Git history query failed")
    return [line for line in completed.stdout.splitlines() if line]


def verify_historical_boundary() -> dict[str, Any]:
    parents = _git_lines("rev-list", "--parents", "-n", "1", EXECUTION_HEAD)
    require(
        parents == [f"{EXECUTION_HEAD} {SOURCE_HEAD}"],
        "_011 execution commit is not the exact single-parent source child",
    )
    changes = _git_lines(
        "diff-tree",
        "--no-ext-diff",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        EXECUTION_HEAD,
    )
    require(changes == [f"A\t{REQUEST_PATH}"], "_011 commit is not sentinel-only")
    require(
        sha256(git_blob(EXECUTION_HEAD, REQUEST_PATH)) == REQUEST_SHA256,
        "_011 request Git blob differs",
    )
    for relative, expected in HISTORICAL_D110_SHA256.items():
        require(
            sha256(git_blob(EXECUTION_HEAD, relative)) == expected,
            f"immutable D1.10 Git blob differs: {relative}",
        )
    require(
        _git_lines("merge-base", "--is-ancestor", EXECUTION_HEAD, "HEAD") == [],
        "current correction is not descended from _011 execution head",
    )
    additions = _git_lines(
        "log", "--format=%H", "--diff-filter=A", "HEAD", "--", NEXT_REQUEST_PATH
    )
    require(not additions and not (ROOT / NEXT_REQUEST_PATH).exists(), "_012 exists without authority")
    return {
        "execution_head": EXECUTION_HEAD,
        "execution_parent": SOURCE_HEAD,
        "request_path": REQUEST_PATH,
        "request_sha256": REQUEST_SHA256,
        "run_attempt": RUN_ATTEMPT,
        "run_id": RUN_ID,
        "sentinel_only": True,
    }


def verify_changed_path_coverage() -> tuple[str, ...]:
    completed = git(
        "diff",
        "--no-ext-diff",
        "--no-renames",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        "-z",
        EXECUTION_HEAD,
        "HEAD",
    )
    require(completed.returncode == 0, "cannot enumerate D1.11 committed paths")
    try:
        changed = tuple(
            sorted(
                token.decode("utf-8")
                for token in completed.stdout.split(b"\0")
                if token
            )
        )
    except UnicodeDecodeError as exc:
        raise D111ResealError("D1.11 committed path is not UTF-8") from exc
    unexpected = sorted(set(changed) - ALLOWED_CHANGED_PATHS)
    require(not unexpected, "D1.11 paths escape the explicit seal: " + ", ".join(unexpected))
    tracked = _git_lines("ls-files")
    forbidden = [
        path
        for path in tracked
        if path.endswith((".pyc", ".pyo"))
        or "__pycache__" in PurePosixPath(path).parts
        or any(
            part in {"build", "dist"} or part.endswith(".egg-info")
            for part in PurePosixPath(path).parts
        )
    ]
    require(not forbidden, f"tracked build artifacts are forbidden: {forbidden}")
    return changed


def validate_gate_replay() -> dict[str, Any]:
    import trimem_d111_gate_contract as gate

    report = gate.validate_replay(gate.load_replay(FIXTURE_PATH))
    require(
        report
        == {
            "execution_head": EXECUTION_HEAD,
            "execution_run_attempt": RUN_ATTEMPT,
            "execution_run_id": RUN_ID,
            "historical_source_gates": 12,
            "ignored_mutable_historical_fields": ["pull_requests"],
            "model_api_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "source_head": SOURCE_HEAD,
            "status": "PASS",
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "D1.11 source-to-sentinel replay differs",
    )
    return report


def validate_runner_isolation() -> dict[str, Any]:
    environment = read_json(ROOT / "configs/trimem_v1/benchmark_environment_lock.json")
    runner = environment.get("runner")
    require(isinstance(runner, Mapping), "benchmark runner lock is missing")
    require(
        runner.get("automatic_ci_runner_label") == "ubuntu-24.04"
        and runner.get("benchmark_exec_runner_labels")
        == list(BENCHMARK_RUNNER_LABELS),
        "benchmark runner labels are not isolated",
    )
    workflow = source_bytes(".github/workflows/trimem-benchmark.yml").decode("utf-8")
    unique_selector = (
        "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, "
        "trimem-benchmark]"
    )
    require(workflow.count(unique_selector) == 2, "protected runner selector differs")
    require(
        workflow.count("runs-on: ubuntu-24.04") == 1,
        "hosted branch preflight selector differs",
    )
    require(
        "[self-hosted, linux, x64, ubuntu-24.04, trimem-benchmark]" not in workflow,
        "ambiguous hosted label remains on protected jobs",
    )
    return {
        "automatic_hosted_label": "ubuntu-24.04",
        "benchmark_self_hosted_labels": list(BENCHMARK_RUNNER_LABELS),
        "live_os_probe_required": {"ID": "ubuntu", "VERSION_ID": "24.04"},
        "ordinary_hosted_job_can_match_benchmark_runner": False,
    }


def current_failure_record() -> dict[str, Any]:
    return {
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "failure_boundary": {
            "bounded_context_preflight": "SKIPPED",
            "branch_trigger_preflight": "FAILED",
            "failure_message": (
                "exactly one exact-head event run is required: "
                ".github/workflows/ci.yml:pull_request"
            ),
            "frozen_serial_phase": "SKIPPED",
            "protected_environment_entered": False,
        },
        "failure_subtype": FAILURE_SUBTYPE,
        "observed_usage": dict(ZERO_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_011_rerun_allowed": False,
            "request_012_authorized": False,
        },
        "request": {
            "id": REQUEST_ID,
            "path": REQUEST_PATH,
            "raw_sha256": REQUEST_SHA256,
            "source_head": SOURCE_HEAD,
        },
        "root_cause": {
            "immutable_top_level_head_sha": SOURCE_HEAD,
            "mutable_nested_pull_request_head_sha": EXECUTION_HEAD,
            "recovery_rule": (
                "ignore historical workflow_run.pull_requests; validate immutable "
                "top-level run identity and current PR independently"
            ),
        },
        "schema": "trimem/development-activation-failure/1.0",
        "scientific_status": "NOT_STARTED_ON_EXEC_011",
        "status": "IMMUTABLE_PUBLIC_GITHUB_EVIDENCE_REPLAYED",
        "workflow_run": {
            "attempt": RUN_ATTEMPT,
            "conclusion": "failure",
            "head_sha": EXECUTION_HEAD,
            "id": RUN_ID,
            "source_head_sha": SOURCE_HEAD,
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
        and status.get("DEV_APPROVAL_ALLOWED") == "NO"
        and status.get("DEV_EXECUTION_ALLOWED") == "NO"
        and status.get("DEV_SCIENTIFIC_STATUS") == "NOT_STARTED_ON_EXEC_011"
        and status.get("FAILURE_SUBTYPE") == FAILURE_SUBTYPE
        and status.get("SCIENTIFIC_RESULT") == "NO_DEVELOPMENT_SCIENTIFIC_RESULT",
        "D1.11 current status differs",
    )
    require(
        readiness.get("current_development_activation_failure") == current_failure_record(),
        "D1.11 current failure record differs",
    )
    require(
        isinstance(authority, Mapping)
        and authority.get("active_development_approval") is False
        and authority.get("approval_request_eligible") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("future_recovery_authority_received") is False
        and authority.get("request_011_created") is True
        and authority.get("request_011_attempt_one_consumed") is True
        and authority.get("request_011_rerun_allowed") is False
        and authority.get("request_011_attempt_two_allowed") is False
        and authority.get("request_012_created") is False
        and authority.get("request_012_authorized") is False
        and authority.get("fresh_execution_request") == "NONE"
        and authority.get("fresh_execution_request_creation_authorized") is False
        and authority.get("required_external_authorization") == "NOT_GRANTED",
        "D1.11 development authority boundary differs",
    )


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    verify_changed_path_coverage()
    history = verify_historical_boundary()
    replay = validate_gate_replay()
    runner = validate_runner_isolation()
    validate_readiness()
    implementation = {
        relative: sha256(source_bytes(relative)) for relative in IMPLEMENTATION_PATHS
    }
    authority = {
        "active_development_approval": False,
        "dev_execution_authorized": False,
        "fresh_execution_request": "NONE",
        "future_recovery_authority_received": False,
        "request_011_attempt_one_consumed": True,
        "request_011_attempt_two_allowed": False,
        "request_011_rerun_allowed": False,
        "request_012_authorized": False,
        "request_012_created": False,
    }
    amendment = {
        "authority_boundary": authority,
        "classification": CLASSIFICATION,
        "credential_free_replay": replay,
        "endpoint": ENDPOINT,
        "exec_011_failure": current_failure_record(),
        "historical_d110_sha256": dict(HISTORICAL_D110_SHA256),
        "implementation_sha256": implementation,
        "runner_isolation": runner,
        "schema": AMENDMENT_SCHEMA,
        "status": STATUS,
        "zero_cost_correction_actuals": dict(ZERO_ACTUALS),
    }
    inventory = {
        "allowed_changed_paths": sorted(ALLOWED_CHANGED_PATHS),
        "changed_path_policy": "VALIDATED_AT_CHECK_TIME_NOT_EMBEDDED",
        "classification": CLASSIFICATION,
        "documents": {
            "amendment": AMENDMENT_PATH.relative_to(ROOT).as_posix(),
            "fixture": FIXTURE_PATH.relative_to(ROOT).as_posix(),
            "readiness": READINESS_PATH.relative_to(ROOT).as_posix(),
        },
        "historical_boundary": history,
        "implementation_sha256": implementation,
        "schema": INVENTORY_SCHEMA,
        "status": STATUS,
    }
    return amendment, inventory


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value)
    fd, temp_name = tempfile.mkstemp(prefix=".trimem-d111-", dir=path.parent)
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
    amendment, inventory = build_artifacts()
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    amendment, inventory = build_artifacts()
    require(read_json(AMENDMENT_PATH) == amendment, "D1.11 amendment is stale")
    require(read_json(INVENTORY_PATH) == inventory, "D1.11 inventory is stale")
    import trimem_freeze

    trimem_freeze.check_freeze(ROOT)
    return {
        "benchmark_image_pulls": 0,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "grader_containers": 0,
        "historical_source_gates": 12,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "request_011_attempt_one_consumed": True,
        "request_012_authorized": False,
        "research_freeze_sha256": sha256(source_bytes("artifacts/trimem_v1/freeze.json")),
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
    except (D111ResealError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
