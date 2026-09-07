from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d112 as trigger  # noqa: E402


class _FakeMonotonic:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "d112-trigger@example.invalid")
    _git(repository, "config", "user.name", "D1.12 trigger fixture")
    (repository / "base.txt").write_bytes(b"immutable base\n")
    return repository, _commit(repository, "fixture: immutable base")


def _pull_request(head: str) -> dict[str, object]:
    return {
        "base_ref": trigger.EXPECTED_BASE_BRANCH,
        "base_sha": trigger.EXPECTED_BASE_HEAD,
        "draft": True,
        "head_ref": trigger.EXPECTED_BRANCH,
        "head_repository": trigger.EXPECTED_REPOSITORY,
        "head_sha": head,
        "html_url": (
            "https://github.com/Scuttie/enterprise-shared-memory-poc/pull/18"
        ),
        "number": trigger.PULL_REQUEST_NUMBER,
        "state": "open",
    }


def _raw_pull_request(head: str) -> dict[str, object]:
    return {
        "base": {
            "ref": trigger.EXPECTED_BASE_BRANCH,
            "sha": trigger.EXPECTED_BASE_HEAD,
        },
        "draft": True,
        "head": {
            "ref": trigger.EXPECTED_BRANCH,
            "repo": {"full_name": trigger.EXPECTED_REPOSITORY},
            "sha": head,
        },
        "html_url": (
            "https://github.com/Scuttie/enterprise-shared-memory-poc/pull/18"
        ),
        "number": trigger.PULL_REQUEST_NUMBER,
        "state": "open",
    }


def _raw_runs(source_head: str) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = {"push": [], "pull_request": []}
    for index, (path, event, _pr_number) in enumerate(
        trigger.REMOTE_GATE_SPECS, start=1
    ):
        run_id = 1_120_000 + index
        result[event].append(
            {
                "conclusion": "success",
                "event": event,
                "head_branch": trigger.EXPECTED_BRANCH,
                "head_sha": source_head,
                "html_url": (
                    "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                    f"actions/runs/{run_id}"
                ),
                "id": run_id,
                "path": path,
                "pull_requests": [
                    {
                        "number": 999,
                        "head": {"sha": "f" * 40},
                    }
                ],
                "run_attempt": 1,
                "status": "completed",
            }
        )
    return result


def _execution_run(head: str, run_id: int = 990_012) -> dict[str, object]:
    return {
        "conclusion": None,
        "event": "push",
        "head_branch": trigger.EXPECTED_BRANCH,
        "head_sha": head,
        "id": run_id,
        "path": trigger.EXPECTED_WORKFLOW_PATH,
        "run_attempt": 1,
        "status": "in_progress",
    }


def _remote_gate_evidence(source_head: str) -> dict[str, object]:
    rows = trigger._select_remote_gate_rows(
        _raw_runs(source_head), source_head=source_head
    )
    return {
        "activation_actuals": dict(trigger.ACTIVATION_ZERO_COUNTERS),
        "all_required_workflows_passed": True,
        "observed_at_utc": _now_utc(),
        "pull_request": _pull_request(source_head),
        "pull_request_number": trigger.PULL_REQUEST_NUMBER,
        "repository": trigger.EXPECTED_REPOSITORY,
        "schema": trigger.REMOTE_GATE_SCHEMA,
        "source_head": source_head,
        "source_ref": trigger.EXPECTED_REF,
        "workflows": rows,
    }


def _runner_rows() -> list[dict[str, object]]:
    return [
        {
            "busy": False,
            "id": 2_120_000 + index,
            "labels": [
                "Linux",
                "X64",
                "self-hosted",
                "trimem-benchmark",
                "trimem-ubuntu-24.04",
            ],
            "name": name,
            "status": "online",
        }
        for index, name in enumerate(trigger.RUNNER_NAMES, start=1)
    ]


def _runner_readiness(source_head: str) -> dict[str, object]:
    runners = _runner_rows()
    return {
        "activation_actuals": dict(trigger.ACTIVATION_ZERO_COUNTERS),
        "host": {
            "architecture": "x86_64",
            "available_service_ports": list(trigger.SERVICE_PORTS.values()),
            "cached_execution_images": 13,
            "container_count": 0,
            "disk_available_bytes": trigger.MINIMUM_RUNNER_DISK_BYTES,
            "docker_client_bytes": trigger.DOCKER_CLIENT_BYTES,
            "docker_client_path": trigger.DOCKER_CLIENT_PATH,
            "docker_client_sha256": trigger.DOCKER_CLIENT_SHA256,
            "docker_client_version": trigger.DOCKER_VERSION,
            "docker_create_pull_never_supported": True,
            "docker_root_directory": trigger.DOCKER_ROOT_DIRECTORY,
            "docker_server_version": "29.1.3",
            "exact_python_library_path": trigger.EXACT_PYTHON_LIBRARY_PATH,
            "exact_python_path": f"{trigger.EXACT_PYTHON_ROOT}/bin/python",
            "exact_python_version": "Python 3.11.10",
            "forbidden_secret_names_present": [],
            "fresh_runner_roots": list(trigger.RUNNER_ROOTS),
            "listener_bindings": [
                {
                    "ld_library_path": trigger.EXACT_PYTHON_LIBRARY_PATH,
                    "pid": 3_120_000 + index,
                    "root": root,
                }
                for index, root in enumerate(trigger.RUNNER_ROOTS, start=1)
            ],
            "local_runner_bindings": [
                {
                    "agent_id": row["id"],
                    "agent_name": row["name"],
                    "disable_update": True,
                    "ephemeral": True,
                    "ld_library_path": trigger.EXACT_PYTHON_LIBRARY_PATH,
                    "listener_bytes": trigger.RUNNER_LISTENER_BYTES,
                    "listener_sha256": trigger.RUNNER_LISTENER_SHA256,
                    "listener_version": trigger.RUNNER_PACKAGE_VERSION,
                    "root": trigger.RUNNER_ROOTS[index],
                    "work_folder": "_work",
                }
                for index, row in enumerate(runners)
            ],
            "minimum_disk_available_bytes": trigger.MINIMUM_RUNNER_DISK_BYTES,
            "os_id": "ubuntu",
            "os_version_id": "24.04",
            "python_toolcache_complete_bytes": trigger.PYTHON_TOOLCACHE_COMPLETE_BYTES,
            "python_toolcache_complete_path": trigger.PYTHON_TOOLCACHE_COMPLETE_PATH,
            "python_toolcache_complete_sha256": trigger.PYTHON_TOOLCACHE_COMPLETE_SHA256,
            "runner_listener_bytes": trigger.RUNNER_LISTENER_BYTES,
            "runner_listener_sha256": trigger.RUNNER_LISTENER_SHA256,
            "runner_package_archive_bytes": trigger.RUNNER_PACKAGE_ARCHIVE_BYTES,
            "runner_package_archive_path": trigger.RUNNER_PACKAGE_ARCHIVE_PATH,
            "runner_package_archive_sha256": trigger.RUNNER_PACKAGE_ARCHIVE_SHA256,
            "runner_package_version": trigger.RUNNER_PACKAGE_VERSION,
            "service_image_ids": {
                "postgres": "sha256:" + "a" * 64,
                "qdrant": "sha256:" + "b" * 64,
            },
            "service_images": 2,
            "stale_runner_roots_absent": list(trigger.STALE_RUNNER_ROOTS),
            "tool_cache_root": trigger.RUNNER_TOOL_CACHE,
            "wsl_distribution": trigger.RUNNER_DISTRIBUTION,
            "wsl_gid": trigger.RUNNER_SERVICE_GID,
            "wsl_uid": trigger.RUNNER_SERVICE_UID,
            "wsl_user": trigger.RUNNER_WSL_USER,
        },
        "observed_at_utc": _now_utc(),
        "repository": trigger.EXPECTED_REPOSITORY,
        "required_labels": list(trigger.REQUIRED_RUNNER_LABELS),
        "runners": runners,
        "schema": trigger.RUNNER_READINESS_SCHEMA,
        "sequential_self_hosted_jobs": [
            "bounded-context-preflight",
            "frozen-serial-phase",
        ],
        "source_head": source_head,
    }


def _event(before: str, after: str) -> dict[str, object]:
    return {
        "after": after,
        "before": before,
        "created": False,
        "deleted": False,
        "forced": False,
        "ref": trigger.EXPECTED_REF,
        "repository": {"full_name": trigger.EXPECTED_REPOSITORY},
    }


def _environment(after: str, run_id: int = 990_012) -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_JOB": "branch-trigger-preflight",
        "GITHUB_REF": trigger.EXPECTED_REF,
        "GITHUB_REPOSITORY": trigger.EXPECTED_REPOSITORY,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": str(run_id),
        "GITHUB_SHA": after,
        "GITHUB_WORKFLOW_REF": trigger.EXPECTED_WORKFLOW_REF,
        "GITHUB_WORKFLOW_SHA": after,
    }


def _protected_environment(after: str, run_id: int = 990_012) -> dict[str, str]:
    return {
        **_environment(after, run_id),
        "GITHUB_JOB": "frozen-serial-phase",
        "LD_LIBRARY_PATH": trigger.EXACT_PYTHON_LIBRARY_PATH,
        "RUNNER_ARCH": "X64",
        "RUNNER_OS": "Linux",
    }


def _protected_observation(
    source_head: str,
    trigger_head: str,
    *,
    run_id: int = 990_012,
    active_index: int = 0,
) -> tuple[dict[str, object], list[str]]:
    readiness = _runner_readiness(source_head)
    runner = readiness["runners"][active_index]  # type: ignore[index]
    execution_images = [
        f"example.invalid/trimem-{index}@sha256:{index:064x}"
        for index in range(1, 14)
    ]
    evidence: dict[str, object] = {
        "activation_actuals": dict(trigger.ACTIVATION_ZERO_COUNTERS),
        "architecture": "x86_64",
        "available_service_ports": list(trigger.SERVICE_PORTS.values()),
        "cached_execution_image_ids": {
            image: "sha256:" + f"{index + 20:064x}"
            for index, image in enumerate(execution_images)
        },
        "container_count": 0,
        "current_runner_binding": {
            "agent_id": runner["id"],  # type: ignore[index]
            "agent_name": trigger.RUNNER_NAMES[active_index],
            "disable_update": True,
            "ephemeral": True,
            "ld_library_path": trigger.EXACT_PYTHON_LIBRARY_PATH,
            "listener_bytes": trigger.RUNNER_LISTENER_BYTES,
            "listener_sha256": trigger.RUNNER_LISTENER_SHA256,
            "listener_version": trigger.RUNNER_PACKAGE_VERSION,
            "root": trigger.RUNNER_ROOTS[active_index],
            "work_folder": "_work",
        },
        "disk_available_bytes": trigger.MINIMUM_RUNNER_DISK_BYTES,
        "docker_client_bytes": trigger.DOCKER_CLIENT_BYTES,
        "docker_client_path": trigger.DOCKER_CLIENT_PATH,
        "docker_client_sha256": trigger.DOCKER_CLIENT_SHA256,
        "docker_client_version": trigger.DOCKER_VERSION,
        "docker_create_pull_never_supported": True,
        "docker_root_directory": trigger.DOCKER_ROOT_DIRECTORY,
        "docker_server_version": trigger.DOCKER_VERSION,
        "exact_python_library_path": trigger.EXACT_PYTHON_LIBRARY_PATH,
        "exact_python_path": f"{trigger.EXACT_PYTHON_ROOT}/bin/python",
        "exact_python_version": "Python 3.11.10",
        "execution_run_attempt": 1,
        "execution_run_id": run_id,
        "forbidden_secret_names_present": [],
        "listener_binding": {
            "ld_library_path": trigger.EXACT_PYTHON_LIBRARY_PATH,
            "pid": 9_001,
            "root": trigger.RUNNER_ROOTS[active_index],
        },
        "minimum_disk_available_bytes": trigger.MINIMUM_RUNNER_DISK_BYTES,
        "observed_at_utc": _now_utc(),
        "os_id": "ubuntu",
        "os_version_id": "24.04",
        "python_toolcache_complete_bytes": trigger.PYTHON_TOOLCACHE_COMPLETE_BYTES,
        "python_toolcache_complete_path": trigger.PYTHON_TOOLCACHE_COMPLETE_PATH,
        "python_toolcache_complete_sha256": trigger.PYTHON_TOOLCACHE_COMPLETE_SHA256,
        "repository": trigger.EXPECTED_REPOSITORY,
        "runner_listener_bytes": trigger.RUNNER_LISTENER_BYTES,
        "runner_listener_sha256": trigger.RUNNER_LISTENER_SHA256,
        "runner_package_archive_bytes": trigger.RUNNER_PACKAGE_ARCHIVE_BYTES,
        "runner_package_archive_path": trigger.RUNNER_PACKAGE_ARCHIVE_PATH,
        "runner_package_archive_sha256": trigger.RUNNER_PACKAGE_ARCHIVE_SHA256,
        "runner_package_version": trigger.RUNNER_PACKAGE_VERSION,
        "runner_gid": trigger.RUNNER_SERVICE_GID,
        "runner_uid": trigger.RUNNER_SERVICE_UID,
        "runner_user": trigger.RUNNER_WSL_USER,
        "service_image_ids": deepcopy(readiness["host"]["service_image_ids"]),  # type: ignore[index]
        "source_head": source_head,
        "stale_runner_roots_absent": list(trigger.STALE_RUNNER_ROOTS),
        "status": "PASS",
        "teardown_listener_binding": None,
        "tool_cache_root": trigger.RUNNER_TOOL_CACHE,
        "trigger_head": trigger_head,
    }
    return evidence, execution_images


def _previous_request() -> dict[str, object]:
    return {
        "control_plane": {
            "exact_model_metadata_requests": 1,
            "one_time_workflow_run_attempt": 1,
            "one_time_workflow_runs": 1,
            "precedes_benchmark_image_pull": True,
            "protocol_canary_generation_requests": 1,
            "scientific_generation_request_cap": 1_872,
        },
        "exact_model": {
            "base_url": "https://api.openai.com/v1",
            "model_id": trigger.MODEL_ID,
            "reasoning_effort": trigger.REASONING_EFFORT,
            "same_snapshot_for": [
                "decomposition",
                "solve",
                "experience_extraction",
            ],
        },
        "scientific_workload": {
            "grader_containers": 72,
            "m2_candidate_streams": 4,
            "protocol_canary_generation_calls": 1,
            "scientific_generation_call_cap": 1_872,
            "stream_order": list(trigger.EXPECTED_STREAM_ORDER),
            "target_order": list(trigger.EXPECTED_TARGET_ORDER),
            "task_arm_runs": 72,
        },
    }


def _validated_source() -> dict[str, object]:
    binding_names = set(trigger.SCIENCE_BINDING_PATHS)
    binding_names.update(trigger.ACTIVATION_BINDING_PATHS)
    binding_names.update(trigger.EXECUTION_CONTRACT_PATHS)
    bindings = {
        name: "sha256:" + hashlib.sha256(name.encode("ascii")).hexdigest()
        for name in binding_names
    }
    bindings["freeze_sha256"] = "sha256:" + "a" * 64
    bindings["remote_gate_workflow_blob_sha256"] = {
        path: "sha256:" + hashlib.sha256(path.encode("ascii")).hexdigest()
        for path in trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
    }
    return {
        "activation_changes": {},
        "bindings": bindings,
        "hard_cap": dict(trigger.EXPECTED_DEVELOPMENT_HARD_CAP),
        "previous_request": _previous_request(),
        "target_order": list(trigger.EXPECTED_TARGET_ORDER),
    }


def test_d112_frozen_identity_and_zero_authority_constants() -> None:
    assert trigger.BASELINE_SOURCE_HEAD == (
        "fa1af529a2af4f8ba606b01410434412881f3d27"
    )
    assert trigger.BASELINE_FREEZE_SHA256 == (
        "e2964255c9c214f29c04bc8df2a5fe275601d43a40f8cad6b1fc926b8cf73739"
    )
    assert trigger.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012"
    assert trigger.REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012_APPROVED_ONCE"
    )
    assert trigger.SENTINEL_PATH.endswith("EXEC_REQUEST_012.json")
    assert trigger.RUNNER_NAMES == (
        "trimem-d112-exec",
        "trimem-d112-preflight",
    )
    assert trigger.RUNNER_PACKAGE_VERSION == "2.337.0"
    assert trigger.RUNNER_PACKAGE_ARCHIVE_PATH == (
        "/opt/trimem-runner-cache/actions-runner-linux-x64-2.337.0.tar.gz"
    )
    assert trigger.RUNNER_PACKAGE_ARCHIVE_BYTES == 226_430_031
    assert trigger.RUNNER_PACKAGE_ARCHIVE_SHA256 == (
        "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613"
    )
    assert trigger.RUNNER_LISTENER_BYTES == 72_568
    assert trigger.RUNNER_LISTENER_SHA256 == (
        "f4584cf5ef53ebc8507e9edfad07973e389ff6488906a1abe5f698aa86b295cf"
    )
    assert trigger.BENCHMARK_EXEC_RUNNER_BOUNDARY == (
        "protected ephemeral self-hosted runner; one serial phase job owns "
        "PostgreSQL, Qdrant and the atomic global ledger"
    )
    assert trigger.REQUIRED_RUNNER_LABELS == (
        "self-hosted",
        "linux",
        "x64",
        "trimem-ubuntu-24.04",
        "trimem-benchmark",
    )
    assert trigger.REQUIRED_ACTIVATION_CHANGES[".gitattributes"] == "M"
    assert trigger.REQUIRED_ACTIVATION_CHANGES[trigger.GH_CLI_LOCK_PATH] == "M"
    assert trigger.REQUIRED_ACTIVATION_CHANGES[
        "scripts/trimem_install_pinned_gh.py"
    ] == "M"
    assert trigger.REQUIRED_ACTIVATION_CHANGES[
        "tests/unit/test_trimem_pinned_gh.py"
    ] == "M"
    assert trigger.REQUIRED_ACTIVATION_CHANGES[
        "scripts/trimem_development_trigger_preflight.py"
    ] == "M"
    assert trigger.ACTIVATION_BINDING_PATHS["gitattributes_sha256"] == (
        ".gitattributes"
    )
    assert trigger.ACTIVATION_BINDING_PATHS["gh_cli_lock_sha256"] == (
        trigger.GH_CLI_LOCK_PATH
    )
    assert trigger.ACTIVATION_BINDING_PATHS[
        "gh_observer_verifier_sha256"
    ] == "scripts/trimem_install_pinned_gh.py"
    assert trigger.ACTIVATION_BINDING_PATHS[
        "gh_observer_verifier_test_sha256"
    ] == "tests/unit/test_trimem_pinned_gh.py"
    assert trigger.ACTIVATION_BINDING_PATHS[
        "historical_preflight_compatibility_sha256"
    ] == "scripts/trimem_development_trigger_preflight.py"


def test_d112_cli_imports_sibling_lock_reader_under_isolated_python() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(ROOT / "scripts" / "trimem_development_trigger_d112.py"),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr


def test_d112_windows_observer_is_byte_verified_before_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    windows_binary = (tmp_path / "gh.EXE").resolve()
    lock = {"schema": "trimem/gh-cli-lock/1.1"}
    safe_environment = {"PATH": "verified-observer-only"}
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        trigger.shutil, "which", lambda name: str(windows_binary) if name == "gh" else None
    )
    monkeypatch.setattr(trigger, "load_gh_cli_lock", lambda path: lock)

    def verify_observer(
        selected_lock: object, binary: Path
    ) -> dict[str, object]:
        calls.append((selected_lock, binary))
        return {
            "first_version_line": "gh version 2.97.0 (2026-07-31)",
            "observer_platform": "windows_amd64",
            "status": "PASS",
        }

    monkeypatch.setattr(trigger, "verify_observer_gh", verify_observer)
    monkeypatch.setattr(
        trigger, "_safe_process_environment", lambda: safe_environment
    )

    assert trigger._pinned_gh_context() == (
        str(windows_binary),
        safe_environment,
    )
    assert calls == [(lock, windows_binary)]


def test_d112_runner_api_uses_the_same_byte_verified_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    safe_environment = {"PATH": "verified-observer-only"}
    expected = _runner_rows()
    response_rows = [
        {
            **row,
            "labels": [{"name": label} for label in row["labels"]],
        }
        for row in expected
    ]
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        trigger,
        "_pinned_gh_context",
        lambda: ("C:\\locked\\gh.exe", safe_environment),
    )

    def run_command(
        argv: object,
        *,
        safe_environment: object,
        label: str,
        timeout: int = 60,
    ) -> bytes:
        calls.append((tuple(argv), safe_environment, label, timeout))  # type: ignore[arg-type]
        return trigger.canonical_bytes(
            {"runners": response_rows, "total_count": len(response_rows)}
        )

    monkeypatch.setattr(trigger, "_run_readiness_command", run_command)

    assert trigger.collect_remote_runner_rows() == expected
    assert len(calls) == 1
    argv, observed_environment, label, timeout = calls[0]
    assert argv[0] == "C:\\locked\\gh.exe"  # type: ignore[index]
    assert observed_environment is safe_environment
    assert label == "GitHub repository runners"
    assert timeout == 60


def test_d112_wsl_python_probes_pin_actions_cache_library_path() -> None:
    prefix = [
        "env",
        f"LD_LIBRARY_PATH={trigger.EXACT_PYTHON_ROOT}/lib",
        f"{trigger.EXACT_PYTHON_ROOT}/bin/python",
    ]
    assert trigger.EXACT_PYTHON_LIBRARY_PATH == f"{trigger.EXACT_PYTHON_ROOT}/lib"
    assert trigger._wsl_exact_python_argv("--version") == [
        *prefix,
        "--version",
    ]
    assert trigger._wsl_exact_python_argv("-I", "-S", "-c", "pass") == [
        *prefix,
        "-I",
        "-S",
        "-c",
        "pass",
    ]


@pytest.mark.parametrize(
    ("separator", "raw"),
    [
        (
            b"\n",
            (
                b"PATH=/usr/bin\nLD_LIBRARY_PATH="
                + trigger.EXACT_PYTHON_LIBRARY_PATH.encode("ascii")
                + b"\n"
            ),
        ),
        (
            b"\0",
            (
                b"PATH=/usr/bin\0LD_LIBRARY_PATH="
                + trigger.EXACT_PYTHON_LIBRARY_PATH.encode("ascii")
                + b"\0"
            ),
        ),
    ],
)
def test_d112_runner_env_and_listener_library_binding_is_exact(
    separator: bytes, raw: bytes
) -> None:
    bindings = trigger._strict_environment_bindings(
        raw, separator=separator, label="fixture"
    )
    assert trigger._require_exact_python_library_binding(
        bindings, label="fixture"
    ) == trigger.EXACT_PYTHON_LIBRARY_PATH


@pytest.mark.parametrize("source", ["env", "listener"])
@pytest.mark.parametrize("failure", ["missing", "wrong", "duplicate", "control"])
def test_d112_runner_env_and_listener_library_binding_fails_closed(
    source: str, failure: str
) -> None:
    separator = b"\n" if source == "env" else b"\0"
    exact = (
        b"LD_LIBRARY_PATH="
        + trigger.EXACT_PYTHON_LIBRARY_PATH.encode("ascii")
    )
    if failure == "missing":
        raw = b"PATH=/usr/bin" + separator
    elif failure == "wrong":
        raw = b"LD_LIBRARY_PATH=/wrong/lib" + separator
    elif failure == "duplicate":
        raw = exact + separator + exact + separator
    else:
        raw = exact + b"\x01" + separator

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="LD_LIBRARY_PATH|duplicated|malformed",
    ):
        bindings = trigger._strict_environment_bindings(
            raw,
            separator=separator,
            label=source,
        )
        trigger._require_exact_python_library_binding(bindings, label=source)


@pytest.mark.parametrize(
    ("job", "active_root"),
    list(zip(("bounded-context-preflight", "frozen-serial-phase"), trigger.RUNNER_ROOTS)),
)
@pytest.mark.parametrize("failure", ["missing", "different"])
def test_d112_pre_setup_tool_cache_string_fails_closed_for_both_jobs(
    job: str, active_root: str, failure: str
) -> None:
    bindings = {}
    if failure == "different":
        bindings["RUNNER_TOOL_CACHE"] = trigger.RUNNER_TOOL_CACHE
    with pytest.raises(trigger.DevelopmentTriggerError, match="string differs"):
        trigger._require_pre_setup_runner_tool_cache_binding(
            bindings, active_root=active_root, label=job
        )


def test_d112_pre_setup_tool_cache_rejects_non_symlink_runner_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    active_root = tmp_path / "runner"
    selected = active_root / "_work" / "_tool"
    selected.mkdir(parents=True)
    central = tmp_path / "central-tool-cache"
    central.mkdir()
    monkeypatch.setattr(trigger, "RUNNER_TOOL_CACHE", str(central))
    with pytest.raises(trigger.DevelopmentTriggerError, match="path binding"):
        trigger._require_pre_setup_runner_tool_cache_binding(
            {"RUNNER_TOOL_CACHE": f"{active_root}/_work/_tool"},
            active_root=str(active_root),
            label="fixture",
        )


def test_d112_all_wsl_probes_use_exact_unprivileged_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wsl = r"C:\Windows\System32\wsl.exe"
    expected = [
        wsl,
        "-d",
        trigger.RUNNER_DISTRIBUTION,
        "--user",
        trigger.RUNNER_WSL_USER,
        "--",
    ]
    assert trigger._wsl_command_prefix(wsl) == expected
    assert trigger._wsl_command_prefix(wsl, cwd=trigger.RUNNER_ROOTS[0]) == [
        *expected[:-1],
        "--cd",
        trigger.RUNNER_ROOTS[0],
        "--",
    ]
    calls: list[list[str]] = []
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda argv, **_kwargs: calls.append(list(argv)) or b"1000:1000\n",
    )
    assert trigger._wsl_stdout(
        wsl,
        ["id", "-u"],
        safe_environment={},
        label="fixture",
    ) == "1000:1000"
    assert calls == [[*expected, "id", "-u"]]


def test_d112_wsl_prefix_rejects_uncommitted_working_directory() -> None:
    with pytest.raises(trigger.DevelopmentTriggerError, match="working directory"):
        trigger._wsl_command_prefix("wsl.exe", cwd="/tmp")


def test_d112_wsl_runner_identity_is_exact_unprivileged_uid_gid() -> None:
    assert trigger._validate_wsl_runner_identity("1000:1000:trimem-runner") == (
        1000,
        1000,
        "trimem-runner",
    )
    for mutation in (
        "0:0:root",
        "1000:0:trimem-runner",
        "0:1000:trimem-runner",
        "1000:1000:root",
        "1000:1000:trimem-runner\n",
    ):
        with pytest.raises(trigger.DevelopmentTriggerError, match="UID/GID"):
            trigger._validate_wsl_runner_identity(mutation)


def test_d112_local_runner_identity_is_exact_unprivileged_uid_gid() -> None:
    assert trigger._validate_local_runner_identity(1000, 1000, "trimem-runner") == (
        1000,
        1000,
        "trimem-runner",
    )
    for values in ((0, 1000, "trimem-runner"), (1000, 0, "trimem-runner"), (1000, 1000, "root"), (True, 1000, "trimem-runner")):
        with pytest.raises(trigger.DevelopmentTriggerError, match="UID/GID"):
            trigger._validate_local_runner_identity(*values)


@pytest.mark.parametrize("job", ["bounded-context-preflight", "frozen-serial-phase"])
def test_d112_pre_setup_rejects_wrong_local_uid_before_event_or_setup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, job: str
) -> None:
    monkeypatch.setattr(trigger, "resolve_repository_root", lambda repository: repository)
    monkeypatch.setattr(
        trigger,
        "_observe_local_runner_identity",
        lambda: trigger._validate_local_runner_identity(0, 0, "root"),
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="UID/GID"):
        trigger.validate_pre_setup_cache_host(
            tmp_path,
            tmp_path / "must-not-be-read.json",
            environ={
                "GITHUB_JOB": job,
                "LD_LIBRARY_PATH": trigger.EXACT_PYTHON_LIBRARY_PATH,
            },
        )


def test_d112_workflow_locks_job_placement_order_and_secret_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = (ROOT / trigger.EXPECTED_WORKFLOW_PATH).read_bytes()
    monkeypatch.setattr(
        trigger,
        "commit_bytes",
        lambda _repository, _source, path: workflow
        if path == trigger.EXPECTED_WORKFLOW_PATH
        else pytest.fail(f"unexpected path: {path}"),
    )
    monkeypatch.setattr(
        trigger,
        "git",
        lambda *_args: trigger.EXPECTED_WORKFLOW_PATH + "\n",
    )
    trigger._validate_d112_workflow(ROOT, "a" * 40)

    exposed = workflow.replace(
        b"  bounded-context-preflight:\n",
        b"  bounded-context-preflight:\n    env:\n      LEAK: ${{ secrets.OPENAI_API_KEY }}\n",
        1,
    )
    monkeypatch.setattr(trigger, "commit_bytes", lambda *_args: exposed)
    with pytest.raises(trigger.DevelopmentTriggerError, match="protected-environment"):
        trigger._validate_d112_workflow(ROOT, "a" * 40)

    ambiguous = workflow.replace(b"127.0.0.1:5432", b"localhost:5432", 1)
    monkeypatch.setattr(trigger, "commit_bytes", lambda *_args: ambiguous)
    with pytest.raises(trigger.DevelopmentTriggerError, match="IPv4 loopback"):
        trigger._validate_d112_workflow(ROOT, "a" * 40)

    setup_cache_not_forwarded = workflow.replace(
        (
            b"uses: actions/setup-python@"
            + trigger.SETUP_PYTHON_ACTION_SHA.encode("ascii")
            + b"\n        env:\n          RUNNER_TOOL_CACHE: ${{ runner.tool_cache }}\n"
        ),
        b"uses: actions/setup-python@" + trigger.SETUP_PYTHON_ACTION_SHA.encode("ascii") + b"\n",
        1,
    )
    monkeypatch.setattr(trigger, "commit_bytes", lambda *_args: setup_cache_not_forwarded)
    with pytest.raises(trigger.DevelopmentTriggerError, match="pre-setup|inherit"):
        trigger._validate_d112_workflow(ROOT, "a" * 40)


def test_d112_request_execution_contract_binds_cache_only_lifecycle_order() -> None:
    bindings = {
        name: "sha256:" + "a" * 64 for name in trigger.EXECUTION_CONTRACT_PATHS
    }
    required_order = trigger._request_execution_contracts(bindings)["required_order"]
    assert required_order == [
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
    ]


@pytest.mark.parametrize(
    "raw",
    [
        b"\xef\xbb\xbf{}",
        b"\xff{}",
        b'{"duplicate":1,"duplicate":2}',
        b'{"value":NaN}',
    ],
)
def test_d112_contract_json_is_strict(raw: bytes) -> None:
    with pytest.raises(trigger.DevelopmentTriggerError, match="invalid|duplicate"):
        trigger.strict_json(raw)


def test_d112_gate_selection_ignores_mutable_nested_pull_requests() -> None:
    source_head = "a" * 40
    runs = _raw_runs(source_head)
    selected = trigger._select_remote_gate_rows(runs, source_head=source_head)

    without_nested = deepcopy(runs)
    for rows in without_nested.values():
        for row in rows:
            row.pop("pull_requests", None)
    with_arbitrary_nested = deepcopy(runs)
    for rows in with_arbitrary_nested.values():
        for row in rows:
            row["pull_requests"] = {"mutable": [None, "anything", 7]}

    assert trigger._select_remote_gate_rows(
        without_nested, source_head=source_head
    ) == selected
    assert trigger._select_remote_gate_rows(
        with_arbitrary_nested, source_head=source_head
    ) == selected
    assert len(selected) == 12


def test_d112_gate_selection_rejects_missing_and_duplicate_top_level_identity() -> None:
    source_head = "a" * 40
    missing = _raw_runs(source_head)
    missing["pull_request"].pop()
    with pytest.raises(trigger.DevelopmentTriggerError, match="exactly one"):
        trigger._select_remote_gate_rows(missing, source_head=source_head)

    duplicate = _raw_runs(source_head)
    duplicate["push"].append(deepcopy(duplicate["push"][0]))
    with pytest.raises(trigger.DevelopmentTriggerError, match="exactly one"):
        trigger._select_remote_gate_rows(duplicate, source_head=source_head)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda rows: rows[0].__setitem__("run_attempt", 2), "rerun"),
        (lambda rows: rows[0].__setitem__("status", "in_progress"), "red"),
        (lambda rows: rows[0].__setitem__("conclusion", "failure"), "red"),
        (lambda rows: rows[1].__setitem__("run_id", rows[0]["run_id"]), "duplicated"),
    ],
)
def test_d112_gate_evidence_rejects_rerun_red_or_duplicate(
    mutation: object, message: str
) -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    rows = evidence["workflows"]
    assert isinstance(rows, list)
    mutation(rows)  # type: ignore[operator]
    if message == "duplicated":
        rows[1]["html_url"] = rows[0]["html_url"]

    with pytest.raises(trigger.DevelopmentTriggerError, match=message):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_d112_current_pr_is_validated_separately_from_historical_runs() -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    pull = evidence["pull_request"]
    assert isinstance(pull, dict)
    pull["head_sha"] = "b" * 40

    with pytest.raises(trigger.DevelopmentTriggerError, match="PR #18"):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_d112_embedded_pr_rejects_bool_int_coercion() -> None:
    source_head = "a" * 40
    evidence = _remote_gate_evidence(source_head)
    pull = evidence["pull_request"]
    assert isinstance(pull, dict)
    pull["draft"] = 1

    with pytest.raises(trigger.DevelopmentTriggerError, match="PR #18"):
        trigger._validate_remote_gate_evidence(evidence, source_head=source_head)


def test_d112_current_pr_visibility_polls_only_missing_or_stale_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_head = "b" * 40
    responses = [
        {},
        _raw_pull_request("a" * 40),
        _raw_pull_request(expected_head),
    ]
    sleeps: list[float] = []

    def run_command(*_args: object, **_kwargs: object) -> bytes:
        return trigger.canonical_bytes(responses.pop(0))

    monkeypatch.setattr(trigger, "_run_readiness_command", run_command)
    assert trigger._collect_current_pull_request(
        "verified-gh",
        {"PATH": "verified"},
        expected_head=expected_head,
        allowed_stale_head="a" * 40,
        _sleep=sleeps.append,
    ) == _pull_request(expected_head)
    assert responses == []
    assert sleeps == [
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
    ]
    assert sum(sleeps) <= trigger.REMOTE_VISIBILITY_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "malformed",
    ["wrong-draft", "integer-draft", "boolean-number", "malformed-head"],
)
def test_d112_current_pr_deterministic_errors_do_not_poll(
    monkeypatch: pytest.MonkeyPatch, malformed: str
) -> None:
    expected_head = "b" * 40
    response = _raw_pull_request(expected_head)
    if malformed == "wrong-draft":
        response["draft"] = False
    elif malformed == "integer-draft":
        response["draft"] = 1
    elif malformed == "boolean-number":
        response["number"] = True
    else:
        response["head"] = "not-an-object"
    sleeps: list[float] = []
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes(response),
    )

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="OPEN/DRAFT|malformed|wrong type",
    ):
        trigger._collect_current_pull_request(
            "verified-gh",
            {"PATH": "verified"},
            expected_head=expected_head,
            allowed_stale_head=None,
            _sleep=sleeps.append,
        )
    assert sleeps == []


def test_d112_current_pr_rejects_arbitrary_stale_head_without_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    response = _raw_pull_request("c" * 40)
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes(response),
    )

    with pytest.raises(trigger.DevelopmentTriggerError, match="exact expected head"):
        trigger._collect_current_pull_request(
            "verified-gh",
            {"PATH": "verified"},
            expected_head="b" * 40,
            allowed_stale_head="a" * 40,
            _sleep=sleeps.append,
        )
    assert sleeps == []


def test_d112_current_pr_visibility_timeout_is_bounded_to_30_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[bool] = []
    sleeps: list[float] = []
    clock = _FakeMonotonic()

    def missing_response(*_args: object, **_kwargs: object) -> bytes:
        observations.append(True)
        return b"{}"

    monkeypatch.setattr(trigger, "_run_readiness_command", missing_response)

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock.sleep(seconds)

    with pytest.raises(trigger.DevelopmentTriggerError, match="30 seconds"):
        trigger._collect_current_pull_request(
            "verified-gh",
            {"PATH": "verified"},
            expected_head="b" * 40,
            allowed_stale_head=None,
            _monotonic=clock,
            _sleep=sleep,
        )
    assert len(observations) == trigger.REMOTE_VISIBILITY_MAX_POLLS - 1
    assert len(sleeps) == trigger.REMOTE_VISIBILITY_MAX_POLLS - 1
    assert sum(sleeps) == trigger.REMOTE_VISIBILITY_TIMEOUT_SECONDS


def test_d112_current_pr_command_elapsed_time_consumes_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeMonotonic()
    command_timeouts: list[float] = []
    sleeps: list[float] = []

    def slow_command(
        *_args: object, timeout: float, **_kwargs: object
    ) -> bytes:
        command_timeouts.append(timeout)
        clock.advance(timeout + 0.001)
        return trigger.canonical_bytes(_raw_pull_request("b" * 40))

    monkeypatch.setattr(trigger, "_run_readiness_command", slow_command)
    with pytest.raises(trigger.DevelopmentTriggerError, match="30 seconds"):
        trigger._collect_current_pull_request(
            "verified-gh",
            {"PATH": "verified"},
            expected_head="b" * 40,
            allowed_stale_head=None,
            _monotonic=clock,
            _sleep=sleeps.append,
        )
    assert command_timeouts == [30.0]
    assert sleeps == []


def test_d112_branch_trigger_binds_source_execution_pr_and_runner_separately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    gates = _remote_gate_evidence(before)
    readiness = _runner_readiness(before)
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    calls: list[tuple[object, ...]] = []

    def validate_sentinel(
        repository: Path,
        selected: str,
        *,
        expected_parent: str,
        require_checked_out_head: bool,
    ) -> dict[str, object]:
        calls.append(
            (
                "sentinel",
                repository,
                selected,
                expected_parent,
                require_checked_out_head,
            )
        )
        return {
            "remote_gate_evidence": gates,
            "runner_readiness": readiness,
            "source_head": expected_parent,
            "trigger_commit": selected,
        }

    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        validate_sentinel,
    )

    def validate_execution_run(
        selected: str, environment: dict[str, str]
    ) -> dict[str, object]:
        calls.append(("execution", selected, environment["GITHUB_RUN_ID"]))
        return {
            "event": "push",
            "head_sha": selected,
            "run_attempt": 1,
            "run_id": int(environment["GITHUB_RUN_ID"]),
            "workflow_path": trigger.EXPECTED_WORKFLOW_PATH,
        }

    monkeypatch.setattr(
        trigger,
        "_validate_unique_execution_run",
        validate_execution_run,
    )
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("pinned-gh", {}))

    def current_pull_request(
        gh: str,
        environment: dict[str, str],
        *,
        expected_head: str,
        allowed_stale_head: str | None,
    ) -> dict[str, object]:
        calls.append(
            (
                "current-pr",
                gh,
                environment,
                expected_head,
                allowed_stale_head,
            )
        )
        return _pull_request(expected_head)

    monkeypatch.setattr(
        trigger,
        "_collect_current_pull_request",
        current_pull_request,
    )

    def remote_gates(
        gh: str, environment: dict[str, str], *, source_head: str
    ) -> object:
        calls.append(("source-gates", gh, environment, source_head))
        return gates["workflows"]

    monkeypatch.setattr(
        trigger,
        "_collect_remote_gate_rows",
        remote_gates,
    )
    def remote_runners(
        gh: str, environment: dict[str, str]
    ) -> list[dict[str, object]]:
        calls.append(("runners", gh, environment))
        return deepcopy(readiness["runners"])  # type: ignore[return-value]

    monkeypatch.setattr(trigger, "_collect_remote_runner_rows", remote_runners)

    result = trigger.validate_branch_trigger(
        ROOT, event_path, environ=_environment(after)
    )
    assert result["source_head"] == before
    assert result["trigger_commit"] == after
    assert result["execution_run"]["head_sha"] == after
    assert result["activation_actuals"] == trigger.ACTIVATION_ZERO_COUNTERS
    assert calls == [
        ("execution", after, "990012"),
        ("sentinel", ROOT, after, before, True),
        ("current-pr", "pinned-gh", {}, after, before),
        ("source-gates", "pinned-gh", {}, before),
        ("runners", "pinned-gh", {}),
    ]


def test_d112_branch_trigger_rejects_secret_or_second_attempt_before_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    monkeypatch.setattr(trigger, "validate_sentinel_commit", pytest.fail)
    monkeypatch.setattr(trigger, "_validate_unique_execution_run", pytest.fail)

    second_attempt = {**_environment(after), "GITHUB_RUN_ATTEMPT": "2"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="attempt"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=second_attempt)

    wrong_job = {**_environment(after), "GITHUB_JOB": "bounded-context-preflight"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="branch-trigger-preflight"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=wrong_job)

    with_secret = {**_environment(after), "OPENAI_API_KEY": "must-not-be-visible"}
    with pytest.raises(trigger.DevelopmentTriggerError, match="protected benchmark"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=with_secret)


def test_d112_branch_trigger_rejects_stale_embedded_runner_before_live_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    readiness = _runner_readiness(before)
    readiness["observed_at_utc"] = "2000-01-01T00:00:00.000Z"
    event_path = tmp_path / "event.json"
    event_path.write_bytes(trigger.canonical_bytes(_event(before, after)))
    monkeypatch.setattr(
        trigger,
        "_validate_unique_execution_run",
        lambda *_args, **_kwargs: {"run_id": 990_012},
    )
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda *_args, **_kwargs: {
            "remote_gate_evidence": _remote_gate_evidence(before),
            "runner_readiness": readiness,
        },
    )
    monkeypatch.setattr(trigger, "_pinned_gh_context", pytest.fail)

    with pytest.raises(trigger.DevelopmentTriggerError, match="stale"):
        trigger.validate_branch_trigger(ROOT, event_path, environ=_environment(after))


def test_d112_execution_current_id_query_uses_exact_endpoint_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, run_id = "b" * 40, 990_012
    run = _execution_run(head, run_id)
    observed: list[dict[str, object]] = []

    def subprocess_run(argv: list[str], **kwargs: object) -> object:
        observed.append({"argv": argv, **kwargs})
        return trigger.subprocess.CompletedProcess(
            argv,
            0,
            stdout=trigger.canonical_bytes(run),
            stderr=b"",
        )

    monkeypatch.setattr(trigger.subprocess, "run", subprocess_run)
    assert trigger._query_github_run_by_id(
        "C:\\locked\\gh.EXE",
        run_id,
        {"PATH": "verified"},
        timeout=7.25,
    ) == run
    assert observed[0]["argv"] == [
        "C:\\locked\\gh.EXE",
        "api",
        "--hostname",
        "github.com",
        "--method",
        "GET",
        (
            "repos/Scuttie/enterprise-shared-memory-poc/"
            f"actions/runs/{run_id}"
        ),
    ]
    assert observed[0]["timeout"] == 7.25


def test_d112_execution_current_id_exact_404_is_not_yet_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        trigger.subprocess,
        "run",
        lambda argv, **_kwargs: trigger.subprocess.CompletedProcess(
            argv,
            1,
            stdout=b"",
            stderr=b"gh: Not Found (HTTP 404)\n",
        ),
    )
    assert (
        trigger._query_github_run_by_id(
            "C:\\locked\\gh.EXE",
            990_012,
            {"PATH": "verified"},
            timeout=5.0,
        )
        is None
    )


def test_d112_execution_run_is_unique_and_attempt_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, run_id = "b" * 40, 990_012
    run = _execution_run(head, run_id)
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("pinned-gh", {}))
    monkeypatch.setattr(trigger, "_query_github_run_by_id", lambda *_args, **_kwargs: run)
    monkeypatch.setattr(
        trigger, "_query_github_runs", lambda *_args, **_kwargs: [run]
    )
    assert trigger._validate_unique_execution_run(
        head, {"GITHUB_RUN_ID": str(run_id)}
    )["run_attempt"] == 1

    monkeypatch.setattr(
        trigger,
        "_query_github_runs",
        lambda *_args, **_kwargs: [run, deepcopy(run)],
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="exactly one"):
        trigger._validate_unique_execution_run(
            head, {"GITHUB_RUN_ID": str(run_id)}
        )


def test_d112_execution_exact_list_visibility_can_lag_current_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, run_id = "b" * 40, 990_012
    run = _execution_run(head, run_id)
    exact_responses = [[], [run]]
    clock = _FakeMonotonic()
    calls: list[str] = []
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("verified-gh", {}))

    def current(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append("current-id")
        return run

    def exact(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        calls.append("exact-list")
        return exact_responses.pop(0)

    monkeypatch.setattr(trigger, "_query_github_run_by_id", current)
    monkeypatch.setattr(trigger, "_query_github_runs", exact)
    result = trigger._validate_unique_execution_run(
        head,
        {"GITHUB_RUN_ID": str(run_id)},
        _monotonic=clock,
        _sleep=clock.sleep,
    )
    assert result["run_id"] == run_id
    assert calls == ["current-id", "exact-list", "current-id", "exact-list"]
    assert clock.value == trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS


def test_d112_execution_queries_share_one_monotonic_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, run_id = "b" * 40, 990_012
    run = _execution_run(head, run_id)
    clock = _FakeMonotonic()
    timeouts: list[tuple[str, float]] = []
    sleeps: list[float] = []
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("verified-gh", {}))

    def current(
        *_args: object, timeout: float, **_kwargs: object
    ) -> dict[str, object]:
        timeouts.append(("current-id", timeout))
        clock.advance(10.0)
        return run

    def exact(
        *_args: object, timeout: float, **_kwargs: object
    ) -> list[dict[str, object]]:
        timeouts.append(("exact-list", timeout))
        clock.advance(timeout + 0.001)
        return [run]

    monkeypatch.setattr(trigger, "_query_github_run_by_id", current)
    monkeypatch.setattr(trigger, "_query_github_runs", exact)
    with pytest.raises(trigger.DevelopmentTriggerError, match="30 seconds"):
        trigger._validate_unique_execution_run(
            head,
            {"GITHUB_RUN_ID": str(run_id)},
            _monotonic=clock,
            _sleep=sleeps.append,
        )
    assert timeouts == [("current-id", 30.0), ("exact-list", 20.0)]
    assert sleeps == []


def test_d112_execution_visibility_polls_missing_and_incomplete_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head, run_id = "b" * 40, 990_012
    complete = _execution_run(head, run_id)
    incomplete = deepcopy(complete)
    del incomplete["status"]
    del incomplete["conclusion"]
    responses = [None, incomplete, complete]
    sleeps: list[float] = []
    calls: list[tuple[object, ...]] = []
    safe_environment = {"PATH": "verified"}
    monkeypatch.setattr(
        trigger,
        "_pinned_gh_context",
        lambda: ("C:\\locked\\gh.exe", safe_environment),
    )

    def query_by_id(
        gh: str,
        selected_run_id: int,
        environment: object,
        *,
        timeout: float,
    ) -> dict[str, object] | None:
        calls.append(("current-id", gh, selected_run_id, environment, timeout))
        return responses.pop(0)

    def query_exact(
        gh: str,
        source_head: str,
        event: str,
        environment: object,
        *,
        timeout: float,
        complete_result_required: bool = True,
    ) -> list[dict[str, object]]:
        calls.append(
            (
                "exact",
                gh,
                source_head,
                event,
                environment,
                timeout,
                complete_result_required,
            )
        )
        return [complete]

    monkeypatch.setattr(trigger, "_query_github_run_by_id", query_by_id)
    monkeypatch.setattr(trigger, "_query_github_runs", query_exact)
    result = trigger._validate_unique_execution_run(
        head,
        {"GITHUB_RUN_ID": str(run_id)},
        _sleep=sleeps.append,
    )
    assert result["run_id"] == run_id
    assert responses == []
    assert [row[0] for row in calls] == [
        "current-id",
        "current-id",
        "current-id",
        "exact",
    ]
    assert all(row[1] == "C:\\locked\\gh.exe" for row in calls)
    assert all(row[3] is safe_environment for row in calls[:3])
    assert calls[-1][2:5] == (head, "push", safe_environment)
    assert all(0 < row[-1] <= 30 for row in calls[:3])
    assert sleeps == [
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
        trigger.REMOTE_VISIBILITY_POLL_INTERVAL_SECONDS,
    ]
    assert sum(sleeps) <= trigger.REMOTE_VISIBILITY_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "red",
        "rerun",
        "bool-attempt",
        "wrong-path",
        "wrong-head",
        "in-progress-success",
        "completed-none",
    ],
)
def test_d112_execution_deterministic_errors_do_not_poll(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    head, run_id = "b" * 40, 990_012
    run = _execution_run(head, run_id)
    if failure == "duplicate":
        rows = [run, deepcopy(run)]
        expected_message = "exactly one"
    elif failure == "red":
        run["status"] = "completed"
        run["conclusion"] = "failure"
        rows = [run]
        expected_message = "identity differs"
    else:
        rows = [run]
        if failure == "rerun":
            run["run_attempt"] = 2
            expected_message = "identity differs"
        elif failure == "bool-attempt":
            run["run_attempt"] = True
            expected_message = "identity differs"
        elif failure == "wrong-path":
            run["path"] = ".github/workflows/ci.yml"
            expected_message = "identity differs"
        elif failure == "wrong-head":
            run["head_sha"] = "c" * 40
            expected_message = "identity differs"
        elif failure == "in-progress-success":
            run["conclusion"] = "success"
            expected_message = "state/conclusion differs"
        else:
            run["status"] = "completed"
            expected_message = "state/conclusion differs"
    sleeps: list[float] = []
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: ("verified-gh", {}))
    monkeypatch.setattr(
        trigger,
        "_query_github_run_by_id",
        lambda *_args, **_kwargs: run,
    )
    monkeypatch.setattr(
        trigger,
        "_query_github_runs",
        (lambda *_args, **_kwargs: rows)
        if failure == "duplicate"
        else pytest.fail,
    )

    with pytest.raises(trigger.DevelopmentTriggerError, match=expected_message):
        trigger._validate_unique_execution_run(
            head,
            {"GITHUB_RUN_ID": str(run_id)},
            _sleep=sleeps.append,
        )
    assert sleeps == []


def test_d112_runner_readiness_requires_exact_fresh_identity() -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    assert trigger._validate_runner_readiness(
        readiness, source_head=source_head
    ) == readiness

    wrong_label = deepcopy(readiness)
    wrong_label["runners"][0]["labels"][-1] = "ubuntu-24.04"  # type: ignore[index]
    with pytest.raises(trigger.DevelopmentTriggerError, match="registration row"):
        trigger._validate_runner_readiness(wrong_label, source_head=source_head)

    stale_name = deepcopy(readiness)
    stale_name["runners"][0]["name"] = "trimem-d110-exec"  # type: ignore[index]
    with pytest.raises(trigger.DevelopmentTriggerError, match="registration set"):
        trigger._validate_runner_readiness(stale_name, source_head=source_head)


@pytest.mark.parametrize(
    "failure",
    [
        "listener-env-missing",
        "listener-env-wrong",
        "persisted-env-missing",
        "persisted-env-wrong",
        "ephemeral-int",
        "disable-update-int",
        "archive-bytes-bool",
        "archive-sha",
        "listener-bytes",
        "listener-version",
        "wsl-user",
        "wsl-uid",
        "wsl-gid-bool",
    ],
)
def test_d112_runner_lifecycle_evidence_fails_closed(failure: str) -> None:
    source_head = "a" * 40
    readiness = _runner_readiness(source_head)
    host = readiness["host"]
    assert isinstance(host, dict)
    listeners = host["listener_bindings"]
    local = host["local_runner_bindings"]
    assert isinstance(listeners, list) and isinstance(local, list)
    if failure == "listener-env-missing":
        listeners[0].pop("ld_library_path")
    elif failure == "listener-env-wrong":
        listeners[0]["ld_library_path"] = "/wrong/lib"
    elif failure == "persisted-env-missing":
        local[0].pop("ld_library_path")
    elif failure == "persisted-env-wrong":
        local[0]["ld_library_path"] = "/wrong/lib"
    elif failure == "ephemeral-int":
        local[0]["ephemeral"] = 1
    elif failure == "disable-update-int":
        local[0]["disable_update"] = 1
    elif failure == "archive-bytes-bool":
        host["runner_package_archive_bytes"] = True
    elif failure == "archive-sha":
        host["runner_package_archive_sha256"] = "0" * 64
    elif failure == "listener-bytes":
        local[0]["listener_bytes"] = trigger.RUNNER_LISTENER_BYTES + 1
    elif failure == "listener-version":
        local[0]["listener_version"] = "2.336.0"
    elif failure == "wsl-user":
        host["wsl_user"] = "root"
    elif failure == "wsl-uid":
        host["wsl_uid"] = 0
    else:
        host["wsl_gid"] = True

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="self-hosted runner host readiness differs",
    ):
        trigger._validate_runner_readiness(readiness, source_head=source_head)


def test_d112_request_preserves_science_and_records_zero_call_recovery(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _fixture_head = _repository(tmp_path)
    source_head = "a" * 40
    validated = _validated_source()
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: validated)
    request = trigger.build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=_remote_gate_evidence(source_head),
        runner_readiness=_runner_readiness(source_head),
    )

    previous = validated["previous_request"]
    assert request["exact_model"] == previous["exact_model"]  # type: ignore[index]
    assert request["scientific_workload"] == previous["scientific_workload"]  # type: ignore[index]
    assert request["hard_caps"] == trigger.EXPECTED_DEVELOPMENT_HARD_CAP
    assert request["actual_execution_authorized"] is False
    assert request["external_execution_approval_received"] is False
    assert request["request_creation_authority_received"] is True
    assert request["requires_external_approval"] is True
    assert request["required_external_authorization"] == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012_APPROVED_ONCE"
    )
    assert request["recovery_provenance"]["model_api_calls"] == 0
    assert request["recovery_provenance"]["grader_containers"] == 0
    assert request["recovery_provenance"]["total_usd"] == 0.0
    assert request["pre_execution_actuals"]["paid_model_calls"] == 0


def test_d112_request_validation_requires_canonical_utf8_plus_one_lf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _fixture_head = _repository(tmp_path)
    source_head = "a" * 40
    validated = _validated_source()
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: validated)
    request = trigger.build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=_remote_gate_evidence(source_head),
        runner_readiness=_runner_readiness(source_head),
    )
    raw = trigger.canonical_bytes(request, trailing_lf=True)
    assert trigger.validate_request(repository, raw, source_head=source_head) == request

    with pytest.raises(trigger.DevelopmentTriggerError, match="canonical"):
        trigger.validate_request(repository, raw[:-1], source_head=source_head)


def test_d112_sentinel_accepts_exact_single_parent_regular_addition(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, source = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"zero_authority":true}\n')
    execution = _commit(repository, "control: add D1.12 sentinel only")
    monkeypatch.setattr(
        trigger,
        "validate_request",
        lambda _repo, raw, *, source_head: {
            "raw": raw,
            "source_head": source_head,
        },
    )

    validated = trigger.validate_sentinel_commit(
        repository, execution, expected_parent=source
    )
    assert validated == {
        "raw": b'{"zero_authority":true}\n',
        "source_head": source,
    }


@pytest.mark.parametrize("invalid_kind", ["extra", "executable", "history"])
def test_d112_sentinel_rejects_nonexclusive_mode_or_prior_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invalid_kind: str
) -> None:
    repository, source = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    if invalid_kind == "history":
        sentinel.write_bytes(b'{"old":true}\n')
        _commit(repository, "fixture: create prior sentinel")
        sentinel.unlink()
        source = _commit(repository, "fixture: remove prior sentinel")
    sentinel.write_bytes(b'{"zero_authority":true}\n')
    if invalid_kind == "extra":
        (repository / "unexpected.txt").write_bytes(b"unexpected\n")
    if invalid_kind == "executable":
        _git(repository, "add", "--chmod=+x", "--", trigger.SENTINEL_PATH)
        _git(repository, "commit", "-m", "control: invalid executable sentinel")
        execution = _git(repository, "rev-parse", "HEAD")
    else:
        execution = _commit(repository, "control: invalid sentinel")
    monkeypatch.setattr(trigger, "validate_request", pytest.fail)

    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="exclusive|100644|already exists",
    ):
        trigger.validate_sentinel_commit(
            repository, execution, expected_parent=source
        )


def test_d112_source_diff_is_strict_descendant_and_explicit_allowlist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, baseline = _repository(tmp_path)
    monkeypatch.setattr(trigger, "STARTING_SOURCE_HEAD", baseline)
    monkeypatch.setattr(trigger, "ALLOWED_ACTIVATION_PATHS", frozenset({"allowed.txt"}))
    monkeypatch.setattr(
        trigger, "REQUIRED_ACTIVATION_CHANGES", {"allowed.txt": "A"}
    )
    (repository / "allowed.txt").write_bytes(b"D1.12 control only\n")
    source = _commit(repository, "control: allowed D1.12 source")
    assert trigger._validate_d112_activation_diff(repository, source) == {
        "allowed.txt": "A"
    }

    (repository / "forbidden.txt").write_bytes(b"scientific drift\n")
    forbidden = _commit(repository, "control: forbidden D1.12 source")
    with pytest.raises(trigger.DevelopmentTriggerError, match="forbidden path"):
        trigger._validate_d112_activation_diff(repository, forbidden)


def test_d112_source_requires_empty_sentinel_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, _base = _repository(tmp_path)
    previous = {
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_011",
        "request_path": "previous.json",
        "request_sha256": "sha256:" + trigger.PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "schema": "trimem/development-tuning-branch-trigger/1.10",
        "source_head": trigger.PREVIOUS_SOURCE_HEAD,
    }
    previous_raw = trigger.canonical_bytes(previous, trailing_lf=True)
    previous_path = repository / "previous.json"
    previous_path.write_bytes(previous_raw)
    previous_execution = _commit(repository, "fixture: immutable _011")
    (repository / "source.txt").write_bytes(b"activation source\n")
    source = _commit(repository, "fixture: D1.12 source")
    monkeypatch.setattr(trigger, "PREVIOUS_EXECUTION_HEAD", previous_execution)
    monkeypatch.setattr(trigger, "PREVIOUS_SENTINEL_PATH", "previous.json")
    monkeypatch.setattr(
        trigger, "PREVIOUS_SENTINEL_SHA256", hashlib.sha256(previous_raw).hexdigest()
    )
    assert trigger._validate_historical_011(repository, source) == previous

    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"{}\n")
    with_history = _commit(repository, "fixture: premature _012")
    with pytest.raises(trigger.DevelopmentTriggerError, match="source history"):
        trigger._validate_historical_011(repository, with_history)


def test_d112_windows_writer_shares_one_verified_observer_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, source_head = _repository(tmp_path)
    _git(repository, "branch", "-M", trigger.EXPECTED_BRANCH)
    observer_environment = {"PATH": "verified-observer-only"}
    observer_context = ("C:\\locked\\gh.exe", observer_environment)
    calls: list[tuple[object, ...]] = []
    gates = _remote_gate_evidence(source_head)
    readiness = _runner_readiness(source_head)

    monkeypatch.setattr(
        trigger, "_validate_secret_free_branch_environment", lambda _env: None
    )
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: {})
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: observer_context)
    monkeypatch.setattr(
        trigger, "_require_no_pending_benchmark_consumers", lambda *_args: None
    )

    def collect_gates(
        selected_head: str,
        *,
        allowed_stale_pr_head: str | None,
        _observer_context: object,
    ) -> dict[str, object]:
        calls.append(
            (
                "gates",
                selected_head,
                allowed_stale_pr_head,
                _observer_context,
            )
        )
        assert allowed_stale_pr_head is None
        assert _observer_context is observer_context
        return gates

    def collect_readiness(
        selected_repository: Path,
        selected_head: str,
        *,
        _observer_context: object,
    ) -> dict[str, object]:
        calls.append(
            ("runners", selected_repository, selected_head, _observer_context)
        )
        assert _observer_context is observer_context
        return readiness

    document = {"request_id": trigger.REQUEST_ID, "source_head": source_head}
    monkeypatch.setattr(trigger, "collect_remote_gate_evidence", collect_gates)
    monkeypatch.setattr(trigger, "collect_runner_readiness", collect_readiness)
    monkeypatch.setattr(trigger, "build_request", lambda *_args, **_kwargs: document)

    written = trigger.write_request(repository)
    target = repository / trigger.SENTINEL_PATH
    assert target.read_bytes() == trigger.canonical_bytes(document, trailing_lf=True)
    assert written["source_head"] == source_head
    assert calls == [
        ("gates", source_head, None, observer_context),
        ("runners", repository.resolve(), source_head, observer_context),
    ]


def test_d112_repository_entrypoints_reject_subdirectory_before_observation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, source_head = _repository(tmp_path)
    nested = repository / "nested"
    nested.mkdir()
    missing_event = nested / "event-does-not-exist.json"
    monkeypatch.setattr(trigger, "_pinned_gh_context", pytest.fail)
    monkeypatch.setattr(trigger.shutil, "which", pytest.fail)

    invocations = [
        lambda: trigger._validate_source(nested, source_head),
        lambda: trigger.validate_correction_source(nested, source_head),
        lambda: trigger.collect_runner_readiness(nested, source_head),
        lambda: trigger.collect_local_runner_host_readiness(
            nested, source_head, {}
        ),
        lambda: trigger.build_request(
            nested,
            source_head=source_head,
            remote_gate_evidence={},
            runner_readiness={},
        ),
        lambda: trigger.validate_request(nested, b"{}", source_head=source_head),
        lambda: trigger.validate_sentinel_commit(nested, source_head),
        lambda: trigger.validate_branch_trigger(nested, missing_event),
        lambda: trigger.validate_runner_host_preflight(nested, missing_event),
        lambda: trigger.write_request(nested),
    ]
    for invocation in invocations:
        with pytest.raises(trigger.DevelopmentTriggerError, match="exact Git"):
            invocation()
    assert not (repository / trigger.SENTINEL_PATH).exists()


def test_d112_writer_rechecks_dirty_race_before_exclusive_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, source_head = _repository(tmp_path)
    _git(repository, "branch", "-M", trigger.EXPECTED_BRANCH)
    gates = _remote_gate_evidence(source_head)
    readiness = _runner_readiness(source_head)
    observer_context = ("C:\\locked\\gh.EXE", {"PATH": "verified"})

    monkeypatch.setattr(
        trigger, "_validate_secret_free_branch_environment", lambda _env: None
    )
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: {})
    monkeypatch.setattr(trigger, "_pinned_gh_context", lambda: observer_context)
    monkeypatch.setattr(
        trigger, "_require_no_pending_benchmark_consumers", lambda *_args: None
    )

    def collect_gates(
        _selected_head: str,
        *,
        allowed_stale_pr_head: str | None,
        _observer_context: object,
    ) -> dict[str, object]:
        assert allowed_stale_pr_head is None
        assert _observer_context is observer_context
        (repository / "base.txt").write_bytes(b"raced worktree mutation\n")
        return gates

    monkeypatch.setattr(trigger, "collect_remote_gate_evidence", collect_gates)
    monkeypatch.setattr(
        trigger,
        "collect_runner_readiness",
        lambda *_args, **_kwargs: readiness,
    )
    monkeypatch.setattr(
        trigger,
        "build_request",
        lambda *_args, **_kwargs: {"request_id": trigger.REQUEST_ID},
    )

    with pytest.raises(trigger.DevelopmentTriggerError, match="worktree changed"):
        trigger.write_request(repository)
    assert not (repository / trigger.SENTINEL_PATH).exists()


def test_d112_protected_observation_accepts_either_exact_remaining_runner() -> None:
    source_head, trigger_head, run_id = "a" * 40, "b" * 40, 990_012
    readiness = _runner_readiness(source_head)
    for active_index in (0, 1):
        evidence, images = _protected_observation(
            source_head, trigger_head, run_id=run_id, active_index=active_index
        )
        assert trigger._validate_protected_runner_readiness(
            evidence,
            source_head=source_head,
            trigger_head=trigger_head,
            run_id=run_id,
            expected_readiness=readiness,
            execution_images=images,
            service_images=trigger.SERVICE_IMAGE_REFS,
        ) == evidence


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("ephemeral", 1),
        ("disable_update", 1),
        ("docker_create_pull_never_supported", 1),
        ("docker_server_version", "29.1.2"),
        ("exact_python_path", "/wrong/python"),
        ("container_count", 1),
        ("runner_uid", 0),
        ("runner_gid", True),
        ("runner_user", "root"),
    ],
)
def test_d112_protected_observation_rejects_bool_like_or_changed_host_fields(
    mutation: str, value: object
) -> None:
    source_head, trigger_head = "a" * 40, "b" * 40
    readiness = _runner_readiness(source_head)
    evidence, images = _protected_observation(source_head, trigger_head)
    if mutation in {"ephemeral", "disable_update"}:
        evidence["current_runner_binding"][mutation] = value  # type: ignore[index]
    else:
        evidence[mutation] = value
    with pytest.raises(trigger.DevelopmentTriggerError, match="protected"):
        trigger._validate_protected_runner_readiness(
            evidence,
            source_head=source_head,
            trigger_head=trigger_head,
            run_id=990_012,
            expected_readiness=readiness,
            execution_images=images,
            service_images=trigger.SERVICE_IMAGE_REFS,
        )


def test_d112_protected_observation_allows_only_exact_known_teardown_listener() -> None:
    source_head, trigger_head = "a" * 40, "b" * 40
    readiness = _runner_readiness(source_head)
    evidence, images = _protected_observation(source_head, trigger_head)
    evidence["teardown_listener_binding"] = {
        "ld_library_path": trigger.EXACT_PYTHON_LIBRARY_PATH,
        "pid": 9_002,
        "root": trigger.RUNNER_ROOTS[1],
    }
    trigger._validate_protected_runner_readiness(
        evidence,
        source_head=source_head,
        trigger_head=trigger_head,
        run_id=990_012,
        expected_readiness=readiness,
        execution_images=images,
        service_images=trigger.SERVICE_IMAGE_REFS,
    )
    evidence["teardown_listener_binding"]["root"] = "/opt/unknown"  # type: ignore[index]
    with pytest.raises(trigger.DevelopmentTriggerError, match="teardown listener"):
        trigger._validate_protected_runner_readiness(
            evidence,
            source_head=source_head,
            trigger_head=trigger_head,
            run_id=990_012,
            expected_readiness=readiness,
            execution_images=images,
            service_images=trigger.SERVICE_IMAGE_REFS,
        )


def test_d112_cache_only_service_create_argv_is_local_loopback_and_never_pulls() -> None:
    argv = trigger._service_create_argv(
        role="postgres",
        image=trigger.POSTGRES_SERVICE_IMAGE,
        name="trimem-d112-990012-postgres",
        run_id=990_012,
        source_head="a" * 40,
        trigger_head="b" * 40,
        postgres_volume_name="trimem-d112-990012-postgres-data",
    )
    assert argv[:3] == list(trigger.DOCKER_LOCAL_PREFIX)
    assert argv[3:5] == ["create", "--pull=never"]
    assert "127.0.0.1:5432:5432" in argv
    assert trigger.POSTGRES_SERVICE_IMAGE == argv[-1]
    assert "pull" not in argv
    assert "manifest" not in argv


def test_d112_docker_pull_never_help_accepts_wrapped_v29_output() -> None:
    raw = """
Usage: docker create [OPTIONS] IMAGE [COMMAND] [ARG...]
      --pull string        Pull image before creating
                           (always|missing|never) (default missing)
"""
    assert trigger._validate_docker_pull_never_help(raw) is True
    with pytest.raises(trigger.DevelopmentTriggerError, match="pull=never"):
        trigger._validate_docker_pull_never_help("Usage: docker create\n")


@pytest.mark.parametrize(
    "name",
    [*sorted(trigger.DOCKER_AUTHORITY_ENV), "DOCKER_FUTURE_OVERRIDE", "docker_future_override"],
)
def test_d112_docker_authority_overrides_are_forbidden(name: str) -> None:
    with pytest.raises(trigger.DevelopmentTriggerError, match="protected benchmark"):
        trigger._validate_secret_free_branch_environment({name: "attacker"})


def test_d112_docker_client_is_absolute_and_byte_locked() -> None:
    assert trigger.DOCKER_LOCAL_PREFIX == (
        "/usr/bin/docker",
        "--host",
        "unix:///var/run/docker.sock",
    )
    assert trigger.DOCKER_CLIENT_BYTES == 31_369_824
    assert trigger.DOCKER_CLIENT_SHA256 == (
        "7ed12b00293d64742419a6601ae97960a367a0ce97c88b06e3278cc0a409557b"
    )
    assert trigger.DOCKER_ROOT_DIRECTORY == "/var/lib/docker"


def test_d112_docker_root_directory_is_exact() -> None:
    assert trigger._validate_docker_root_directory("/var/lib/docker") == "/var/lib/docker"
    with pytest.raises(trigger.DevelopmentTriggerError, match="root directory"):
        trigger._validate_docker_root_directory("/mnt/remote-docker")


def test_d112_toolcache_complete_marker_is_direct_empty_file(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "x64.complete"
    marker.write_bytes(b"")
    trigger._verify_local_file_lock(
        marker,
        expected_bytes=trigger.PYTHON_TOOLCACHE_COMPLETE_BYTES,
        expected_sha256=trigger.PYTHON_TOOLCACHE_COMPLETE_SHA256,
        label="fixture marker",
    )
    marker.write_bytes(b"not-complete")
    with pytest.raises(trigger.DevelopmentTriggerError, match="size"):
        trigger._verify_local_file_lock(
            marker,
            expected_bytes=0,
            expected_sha256=trigger.PYTHON_TOOLCACHE_COMPLETE_SHA256,
            label="fixture marker",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("st_mode", stat.S_IFREG | 0o640),
        ("st_mode", stat.S_IFLNK | 0o600),
        ("st_uid", 1001),
        ("st_gid", 1001),
        ("st_nlink", 2),
    ],
)
def test_d112_service_state_metadata_is_owned_direct_0600_single_link(
    field: str, value: int
) -> None:
    metadata = {
        "st_mode": stat.S_IFREG | 0o600,
        "st_uid": 1000,
        "st_gid": 1000,
        "st_nlink": 1,
    }
    trigger._require_service_state_metadata(
        SimpleNamespace(**metadata),  # type: ignore[arg-type]
        label="fixture",
    )
    metadata[field] = value
    with pytest.raises(trigger.DevelopmentTriggerError, match="metadata"):
        trigger._require_service_state_metadata(
            SimpleNamespace(**metadata),  # type: ignore[arg-type]
            label="fixture",
        )


def test_d112_service_state_process_identity_is_exact_uid_gid_1000() -> None:
    trigger._require_service_state_process_identity(1000, 1000)
    for uid, gid in ((0, 1000), (1000, 0), (True, 1000)):
        with pytest.raises(trigger.DevelopmentTriggerError, match="process ownership"):
            trigger._require_service_state_process_identity(uid, gid)  # type: ignore[arg-type]


def _benchmark_workflow_run(run_id: int, *, status: str = "completed") -> dict[str, object]:
    return {
        "conclusion": "success" if status == "completed" else None,
        "event": "push",
        "head_branch": trigger.EXPECTED_BRANCH,
        "head_sha": f"{run_id:040x}"[-40:],
        "id": run_id,
        "path": trigger.EXPECTED_WORKFLOW_PATH,
        "run_attempt": 1,
        "status": status,
    }


def test_d112_pending_consumer_guard_uses_one_complete_workflow_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(argv: object, **_kwargs: object) -> bytes:
        calls.append(list(argv))  # type: ignore[arg-type]
        return trigger.canonical_bytes([{"total_count": 0, "workflow_runs": []}])

    monkeypatch.setattr(trigger, "_run_readiness_command", run)
    trigger._require_no_pending_benchmark_consumers("pinned-gh", {"PATH": "exact"})
    assert len(calls) == 1
    assert "actions/workflows/trimem-benchmark.yml/runs" in " ".join(calls[0])
    assert "per_page=100" in calls[0]
    assert "--paginate" in calls[0] and "--slurp" in calls[0]
    assert not any(value.startswith("status=") for value in calls[0])


def test_d112_pending_consumer_guard_rejects_active_or_paginated_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = {
        "total_count": 1,
        "workflow_runs": [
            {
                "event": "unknown-historical-event",
                "head_branch": None,
                "head_sha": None,
                "id": 101,
                "path": trigger.EXPECTED_WORKFLOW_PATH,
                "status": "in_progress",
            }
        ],
    }
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes([active]),
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="still active"):
        trigger._require_no_pending_benchmark_consumers("pinned-gh", {})


def test_d112_pending_consumer_snapshot_allows_completed_historical_variation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    historical = {
        "conclusion": None,
        "event": "schedule",
        "head_branch": None,
        "head_sha": None,
        "id": 88,
        "path": trigger.EXPECTED_WORKFLOW_PATH,
        "run_attempt": None,
        "status": "completed",
    }
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes(
            [{"total_count": 1, "workflow_runs": [historical]}]
        ),
    )
    trigger._require_no_pending_benchmark_consumers("pinned-gh", {})


@pytest.mark.parametrize(
    "row",
    [
        {"id": True, "path": trigger.EXPECTED_WORKFLOW_PATH, "status": "completed"},
        {"id": 0, "path": trigger.EXPECTED_WORKFLOW_PATH, "status": "completed"},
        {"id": 1, "path": ".github/workflows/other.yml", "status": "completed"},
        {"id": 1, "path": trigger.EXPECTED_WORKFLOW_PATH, "status": "unknown"},
        "not-a-row",
    ],
)
def test_d112_pending_consumer_snapshot_rejects_malformed_common_row(
    monkeypatch: pytest.MonkeyPatch, row: object
) -> None:
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes(
            [{"total_count": 1, "workflow_runs": [row]}]
        ),
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="malformed"):
        trigger._require_no_pending_benchmark_consumers("pinned-gh", {})


def test_d112_pending_consumer_snapshot_rejects_incomplete_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes(
            [{"total_count": 2, "workflow_runs": [_benchmark_workflow_run(1)]}]
        ),
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="incomplete"):
        trigger._require_no_pending_benchmark_consumers("pinned-gh", {})


def test_d112_pending_consumer_snapshot_rejects_duplicate_or_changing_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = [_benchmark_workflow_run(index + 1) for index in range(100)]
    duplicate = _benchmark_workflow_run(100)
    pages = [
        {"total_count": 101, "workflow_runs": first},
        {"total_count": 101, "workflow_runs": [duplicate]},
    ]
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: trigger.canonical_bytes(pages),
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="duplicated"):
        trigger._require_no_pending_benchmark_consumers("pinned-gh", {})


def test_d112_partial_rollback_is_retry_safe_and_removes_one_exact_id_at_a_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = ["a" * 64, "b" * 64]
    baseline = ["existing-volume"]
    volume_name = "trimem-d112-990012-postgres-data"
    containers = set(created)
    volumes = {baseline[0], volume_name}
    fail_second_once = True
    calls: list[list[str]] = []

    def mutate(argv: object, **_kwargs: object) -> bytes:
        nonlocal fail_second_once
        command = list(argv)  # type: ignore[arg-type]
        calls.append(command)
        if command[3:7] == ["rm", "-f", "--volumes", "--"]:
            selected = command[-1]
            if selected == created[0] and fail_second_once:
                fail_second_once = False
                raise trigger.DevelopmentTriggerError("injected rollback failure")
            containers.remove(selected)
        elif command[3:6] == ["volume", "rm", "--"]:
            volumes.remove(command[-1])
        return b""

    monkeypatch.setattr(
        trigger, "_docker_container_ids", lambda *_args, **_kwargs: sorted(containers)
    )
    monkeypatch.setattr(
        trigger, "_docker_volume_names", lambda *_args, **_kwargs: sorted(volumes)
    )
    monkeypatch.setattr(trigger, "_run_readiness_command", mutate)

    with pytest.raises(trigger.DevelopmentTriggerError, match="injected"):
        trigger._rollback_created_services(
            created,
            created_volume=volume_name,
            baseline_volume_names=baseline,
            safe_environment={},
        )
    assert containers == {created[0]}
    assert volume_name in volumes

    trigger._rollback_created_services(
        created,
        created_volume=volume_name,
        baseline_volume_names=baseline,
        safe_environment={},
    )
    assert containers == set()
    assert volumes == set(baseline)
    assert all(
        len(command) == 8
        for command in calls
        if command[3:7] == ["rm", "-f", "--volumes", "--"]
    )


def _service_state_fixture() -> dict[str, object]:
    run_id = 990_012
    volume_name = trigger._service_volume_name(run_id)
    return {
        "baseline_volume_names": ["existing-volume"],
        "containers": {
            role: {
                "container_id": character * 64,
                "image": trigger.SERVICE_IMAGE_REFS[role],
                "image_id": "sha256:" + character * 64,
                "name": trigger._service_container_names(run_id)[role],
                "port": trigger.SERVICE_PORTS[role],
                "role": role,
            }
            for role, character in (("postgres", "a"), ("qdrant", "b"))
        },
        "execution_run_attempt": 1,
        "execution_run_id": run_id,
        "postgres_volume": {
            "destination": "/var/lib/postgresql/data",
            "name": volume_name,
            "source": f"{trigger.DOCKER_ROOT_DIRECTORY}/volumes/{volume_name}/_data",
        },
        "repository": trigger.EXPECTED_REPOSITORY,
        "schema": trigger.SERVICE_STATE_SCHEMA,
        "source_head": "a" * 40,
        "trigger_head": "b" * 40,
    }


def _service_container_document(
    state: dict[str, object], role: str
) -> dict[str, object]:
    row = state["containers"][role]  # type: ignore[index]
    labels = {
        "trimem.d112.role": role,
        "trimem.d112.run_id": str(state["execution_run_id"]),
        "trimem.d112.source_head": state["source_head"],
        "trimem.d112.trigger_head": state["trigger_head"],
    }
    mounts: list[dict[str, object]] = []
    if role == "postgres":
        volume = state["postgres_volume"]  # type: ignore[assignment]
        mounts = [
            {
                "Destination": volume["destination"],  # type: ignore[index]
                "Name": volume["name"],  # type: ignore[index]
                "RW": True,
                "Source": volume["source"],  # type: ignore[index]
                "Type": "volume",
            }
        ]
    environment = []
    if role == "postgres":
        environment = [
            "POSTGRES_DB=trimem_benchmark",
            "POSTGRES_PASSWORD=postgres",
            "POSTGRES_USER=postgres",
        ]
    return {
        "Config": {"Env": environment, "Image": row["image"], "Labels": labels},  # type: ignore[index]
        "Id": row["container_id"],  # type: ignore[index]
        "Image": row["image_id"],  # type: ignore[index]
        "Mounts": mounts,
        "Name": "/" + row["name"],  # type: ignore[index]
        "NetworkSettings": {
            "Ports": {
                f"{row['port']}/tcp": [  # type: ignore[index]
                    {"HostIp": "127.0.0.1", "HostPort": str(row["port"])}  # type: ignore[index]
                ]
            }
        },
        "State": {
            "Health": {"Status": "healthy"} if role == "postgres" else None,
            "Running": True,
        },
    }


def test_d112_state_free_cleanup_retries_after_one_exact_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _service_state_fixture()
    documents = {
        role: _service_container_document(state, role)
        for role in trigger.SERVICE_IMAGE_REFS
    }
    id_to_role = {
        state["containers"][role]["container_id"]: role  # type: ignore[index]
        for role in trigger.SERVICE_IMAGE_REFS
    }
    volume_name = state["postgres_volume"]["name"]  # type: ignore[index]
    containers = set(id_to_role)
    volumes = {"existing-volume", volume_name}
    fail_qdrant_once = True
    mutation_calls: list[list[str]] = []

    def run(argv: object, **_kwargs: object) -> bytes:
        nonlocal fail_qdrant_once
        command = list(argv)  # type: ignore[arg-type]
        if command[3:6] == ["container", "inspect", "--format"]:
            return trigger.canonical_bytes(documents[id_to_role[command[-1]]])
        mutation_calls.append(command)
        if command[3:7] == ["rm", "-f", "--volumes", "--"]:
            selected = command[-1]
            if id_to_role[selected] == "qdrant" and fail_qdrant_once:
                fail_qdrant_once = False
                raise trigger.DevelopmentTriggerError("injected state-free failure")
            containers.remove(selected)
        elif command[3:6] == ["volume", "rm", "--"]:
            volumes.remove(command[-1])
        return b""

    def local_stdout(argv: object, **_kwargs: object) -> str:
        image = list(argv)[-1]  # type: ignore[arg-type]
        role = next(role for role, value in trigger.SERVICE_IMAGE_REFS.items() if value == image)
        return state["containers"][role]["image_id"]  # type: ignore[index,return-value]

    monkeypatch.setattr(
        trigger, "_docker_container_ids", lambda *_args, **_kwargs: sorted(containers)
    )
    monkeypatch.setattr(
        trigger, "_docker_volume_names", lambda *_args, **_kwargs: sorted(volumes)
    )
    monkeypatch.setattr(trigger, "_run_readiness_command", run)
    monkeypatch.setattr(trigger, "_local_stdout", local_stdout)
    monkeypatch.setattr(trigger, "_inspect_named_service_volume", lambda *_args, **_kwargs: {})

    arguments = {
        "source_head": state["source_head"],
        "trigger_head": state["trigger_head"],
        "run_id": state["execution_run_id"],
        "service_images": trigger.SERVICE_IMAGE_REFS,
        "safe_environment": {},
    }
    with pytest.raises(trigger.DevelopmentTriggerError, match="injected"):
        trigger._cleanup_state_free_partial_services(**arguments)  # type: ignore[arg-type]
    assert len(containers) == 1
    assert volume_name in volumes

    assert trigger._cleanup_state_free_partial_services(**arguments) == 1  # type: ignore[arg-type]
    assert containers == set()
    assert volumes == {"existing-volume"}
    assert all(
        len(command) == 8
        for command in mutation_calls
        if command[3:7] == ["rm", "-f", "--volumes", "--"]
    )


def test_d112_state_free_cleanup_rejects_unknown_identity_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown_id = "c" * 64
    document = {
        "Config": {"Labels": {"trimem.d112.role": "unknown"}},
        "Id": unknown_id,
    }
    calls: list[list[str]] = []
    monkeypatch.setattr(
        trigger, "_docker_container_ids", lambda *_args, **_kwargs: [unknown_id]
    )

    def inspect(argv: object, **_kwargs: object) -> bytes:
        command = list(argv)  # type: ignore[arg-type]
        calls.append(command)
        return trigger.canonical_bytes(document)

    monkeypatch.setattr(trigger, "_run_readiness_command", inspect)
    with pytest.raises(trigger.DevelopmentTriggerError, match="identity"):
        trigger._cleanup_state_free_partial_services(
            source_head="a" * 40,
            trigger_head="b" * 40,
            run_id=990_012,
            service_images=trigger.SERVICE_IMAGE_REFS,
            safe_environment={},
        )
    assert len(calls) == 1
    assert calls[0][3] == "container"


@pytest.mark.parametrize("failure", ["extra", "stopped", "wrong-image", "wrong-port"])
def test_d112_service_observation_fails_closed_on_container_drift(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    state = _service_state_fixture()
    documents = {
        role: _service_container_document(state, role)
        for role in trigger.SERVICE_IMAGE_REFS
    }
    ids = [state["containers"][role]["container_id"] for role in trigger.SERVICE_IMAGE_REFS]  # type: ignore[index]
    if failure == "extra":
        ids.append("c" * 64)
    elif failure == "stopped":
        documents["qdrant"]["State"]["Running"] = False  # type: ignore[index]
    elif failure == "wrong-image":
        documents["qdrant"]["Image"] = "sha256:" + "c" * 64
    else:
        documents["qdrant"]["NetworkSettings"]["Ports"] = {  # type: ignore[index]
            "6333/tcp": [{"HostIp": "0.0.0.0", "HostPort": "6333"}]
        }
    monkeypatch.setattr(trigger, "_docker_container_ids", lambda *_args, **_kwargs: ids)
    monkeypatch.setattr(trigger, "_inspect_named_service_volume", lambda *_args, **_kwargs: {})

    def inspect(argv: object, **_kwargs: object) -> bytes:
        selected_id = list(argv)[-1]  # type: ignore[arg-type]
        role = "postgres" if selected_id == "a" * 64 else "qdrant"
        return trigger.canonical_bytes(documents[role])

    monkeypatch.setattr(trigger, "_run_readiness_command", inspect)
    with pytest.raises(trigger.DevelopmentTriggerError, match="service|container|port"):
        trigger._observe_state_bound_services(
            state, safe_environment={}, require_running=True
        )


def test_d112_state_bound_cleanup_is_retry_safe_after_partial_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _service_state_fixture()
    postgres_id = state["containers"]["postgres"]["container_id"]  # type: ignore[index]
    qdrant_id = state["containers"]["qdrant"]["container_id"]  # type: ignore[index]
    volume_name = state["postgres_volume"]["name"]  # type: ignore[index]
    containers = {postgres_id, qdrant_id}
    volumes = {"existing-volume", volume_name}
    fail_qdrant_once = True
    calls: list[list[str]] = []

    def observe(*_args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["allow_absent"] is True
        return {}

    def mutate(argv: object, **_kwargs: object) -> bytes:
        nonlocal fail_qdrant_once
        command = list(argv)  # type: ignore[arg-type]
        calls.append(command)
        if command[3:7] == ["rm", "-f", "--volumes", "--"]:
            selected = command[-1]
            if selected == qdrant_id and fail_qdrant_once:
                fail_qdrant_once = False
                raise trigger.DevelopmentTriggerError("injected Docker failure")
            containers.remove(selected)
        elif command[3:6] == ["volume", "rm", "--"]:
            volumes.remove(command[-1])
        return b""

    monkeypatch.setattr(trigger, "_observe_state_bound_services", observe)
    monkeypatch.setattr(
        trigger, "_docker_container_ids", lambda *_args, **_kwargs: sorted(containers)
    )
    monkeypatch.setattr(
        trigger, "_docker_volume_names", lambda *_args, **_kwargs: sorted(volumes)
    )
    monkeypatch.setattr(trigger, "_inspect_named_service_volume", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(trigger, "_run_readiness_command", mutate)

    with pytest.raises(trigger.DevelopmentTriggerError, match="injected"):
        trigger._cleanup_state_bound_services(state, safe_environment={})
    assert containers == {qdrant_id}
    assert volume_name in volumes

    assert trigger._cleanup_state_bound_services(state, safe_environment={}) == 1
    assert containers == set()
    assert volumes == {"existing-volume"}
    removal_calls = [row for row in calls if row[3] in {"rm", "volume"}]
    assert all(
        not (row[3] == "rm" and len(row[7:]) != 1)
        for row in removal_calls
    )


def test_d112_state_bound_cleanup_rejects_unknown_container_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _service_state_fixture()
    monkeypatch.setattr(
        trigger,
        "_docker_container_ids",
        lambda *_args, **_kwargs: ["c" * 64],
    )
    monkeypatch.setattr(
        trigger,
        "_run_readiness_command",
        lambda *_args, **_kwargs: pytest.fail("must not mutate unknown container"),
    )
    with pytest.raises(trigger.DevelopmentTriggerError, match="state-bound services"):
        trigger._cleanup_state_bound_services(state, safe_environment={})
