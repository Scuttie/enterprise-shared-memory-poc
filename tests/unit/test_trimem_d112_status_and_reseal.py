"""D1.12 source-state authority, immutable D1.11, and `_012` boundary tests."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d112_reseal as reseal  # noqa: E402
import trimem_d113_reseal as current_reseal  # noqa: E402


D112_SOURCE_HEAD = "9db94e2a4abfaad0bb27079738b77836d68fa2e4"


def read(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def read_historical(relative: str) -> dict:
    completed = subprocess.run(
        ["git", "show", f"{D112_SOURCE_HEAD}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout.decode("utf-8", errors="strict"))


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def commit_file(repository: Path, relative: str, raw: bytes, message: str) -> str:
    target = repository / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    git(repository, "add", "--", relative)
    git(repository, "commit", "-m", message)
    return git(repository, "rev-parse", "HEAD")


def repository_with_source(tmp_path: Path) -> tuple[str, str]:
    git(tmp_path, "init")
    git(tmp_path, "config", "user.email", "trimem-tests@example.invalid")
    git(tmp_path, "config", "user.name", "TriMem Tests")
    base = commit_file(tmp_path, "README.md", b"base\n", "base")
    source = commit_file(tmp_path, "source.txt", b"source\n", "source")
    return base, source


def test_source_activation_record_has_creation_but_no_execution_authority() -> None:
    assert reseal.current_activation_record() == {
        "actual_execution_authorized": False,
        "benchmark_image_pulls": 0,
        "classification": "PRE_EXEC_012_ZERO_AUTHORITY_ACTIVATION",
        "endpoint": "TRIMEM_V1_READY_FOR_EXEC_012_REQUEST",
        "external_execution_approval_received": False,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012",
        "request_path": (
            "artifacts/trimem_v1/exec_requests/"
            "DEVELOPMENT_TUNING_EXEC_REQUEST_012.json"
        ),
        "request_present_in_activation_source": False,
        "schema": "trimem/development-exec-012-activation/1.0",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def test_readiness_seals_final_011_no_rerun_wording() -> None:
    # Read the readiness document at the frozen D1.12 source.  The working
    # tree now truthfully describes D1.13 and must not be reinterpreted by the
    # historical D1.12 validator.
    authority = read_historical("artifacts/trimem_v1/readiness_requirements.json")[
        "development_authorization_boundary"
    ]

    assert authority["meaning"] == reseal.DEVELOPMENT_AUTHORITY_MEANING
    assert "_011 attempt-1 run cannot be rerun" in authority["meaning"]
    assert current_reseal.validate_historical_d112()["status"] == "PASS"


def test_historical_d111_is_verified_from_exact_git_blobs() -> None:
    result = reseal.validate_historical_d111()

    assert result == {
        "amendment_sha256": (
            "bd4648ca3bb6542c16d9af9d0bbe96cd64241986212c0b50a52e4fb8a9bf6ca4"
        ),
        "baseline_head": "fa1af529a2af4f8ba606b01410434412881f3d27",
        "freeze_sha256": (
            "e2964255c9c214f29c04bc8df2a5fe275601d43a40f8cad6b1fc926b8cf73739"
        ),
        "implementation_files": 17,
        "inventory_sha256": (
            "383462fce02204fb7ca3507e8102e804f9fa4df135ff5d719a172cf85df8c5c1"
        ),
        "request_011_attempt_one_consumed": True,
        "request_011_model_api_calls": 0,
        "request_011_official_grader_runs": 0,
        "request_011_paid_model_calls": 0,
        "request_011_run_attempt": 1,
        "request_011_run_id": 34_047_573_548,
        "status": "PASS",
    }


def test_optional_012_boundary_accepts_absent_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base, source = repository_with_source(tmp_path)
    monkeypatch.setattr(reseal, "ROOT", tmp_path)

    assert git(tmp_path, "rev-parse", "HEAD") == source
    assert reseal.validate_optional_exec_012_boundary() is None


def test_optional_012_boundary_rejects_uncommitted_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_source(tmp_path)
    target = tmp_path / reseal.REQUEST_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}\n")
    monkeypatch.setattr(reseal, "ROOT", tmp_path)

    with pytest.raises(
        reseal.D112ResealError,
        match="uncommitted or non-historical _012 request is forbidden",
    ):
        reseal.validate_optional_exec_012_boundary()


def test_optional_012_boundary_rejects_multifile_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_with_source(tmp_path)
    target = tmp_path / reseal.REQUEST_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}\n")
    (tmp_path / "extra.txt").write_bytes(b"extra\n")
    git(tmp_path, "add", "--", reseal.REQUEST_PATH, "extra.txt")
    git(tmp_path, "commit", "-m", "bad sentinel")
    monkeypatch.setattr(reseal, "ROOT", tmp_path)

    with pytest.raises(reseal.D112ResealError, match="sentinel-only"):
        reseal.validate_optional_exec_012_boundary()


def test_optional_012_boundary_delegates_exact_child_to_active_trigger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _base, source = repository_with_source(tmp_path)
    execution = commit_file(
        tmp_path,
        reseal.REQUEST_PATH,
        b'{"request_id":"zero-authority-test"}\n',
        "sentinel",
    )
    calls: list[tuple[Path, str, str | None, bool]] = []

    def validate(
        repository: Path,
        after: str,
        *,
        expected_parent: str | None,
        require_checked_out_head: bool,
    ) -> dict:
        calls.append((repository, after, expected_parent, require_checked_out_head))
        return {"status": "PASS"}

    trigger = SimpleNamespace(
        REQUEST_ID=reseal.REQUEST_ID,
        SENTINEL_PATH=reseal.REQUEST_PATH,
        validate_sentinel_commit=validate,
    )
    monkeypatch.setattr(reseal, "ROOT", tmp_path)
    monkeypatch.setattr(
        reseal.importlib,
        "import_module",
        lambda name: trigger
        if name == "trimem_development_trigger_d112"
        else pytest.fail(f"unexpected import: {name}"),
    )

    assert reseal.validate_optional_exec_012_boundary() == execution
    assert calls == [(tmp_path, execution, source, True)]


def test_changed_path_coverage_rejects_unsealed_source_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _source = repository_with_source(tmp_path)
    bad = commit_file(tmp_path, "scripts/unsealed.py", b"pass\n", "unsealed")
    monkeypatch.setattr(reseal, "ROOT", tmp_path)
    monkeypatch.setattr(reseal, "BASE_HEAD", base)

    with pytest.raises(reseal.D112ResealError, match="escape the explicit seal"):
        reseal.verify_changed_path_coverage(bad)


def test_trigger_and_reseal_share_exact_d112_contract_constants() -> None:
    import trimem_development_trigger_d112 as trigger

    assert trigger.AMENDMENT_PATH == reseal.AMENDMENT_PATH.relative_to(ROOT).as_posix()
    assert trigger.INVENTORY_PATH == reseal.INVENTORY_PATH.relative_to(ROOT).as_posix()
    assert trigger.AMENDMENT_SCHEMA == reseal.AMENDMENT_SCHEMA
    assert trigger.INVENTORY_SCHEMA == reseal.INVENTORY_SCHEMA
    assert trigger.AMENDMENT_CLASSIFICATION == reseal.CLASSIFICATION
    assert trigger.AMENDMENT_STATUS == reseal.STATUS
    assert trigger.AMENDMENT_ENDPOINT == reseal.ENDPOINT
    assert trigger.SENTINEL_PATH == reseal.REQUEST_PATH
    assert trigger.ALLOWED_ACTIVATION_PATHS == reseal.ALLOWED_CHANGED_PATHS


def test_runner_isolation_seals_ephemeral_binary_and_environment_contract() -> None:
    runtime = reseal.validate_protected_runtime_contract()
    contract = reseal.validate_runner_isolation()
    assert contract == {
        "automatic_hosted_label": "ubuntu-24.04",
        "benchmark_runner_boundary": (
            "protected ephemeral self-hosted runner; one serial phase job owns "
            "PostgreSQL, Qdrant and the atomic global ledger"
        ),
        "benchmark_self_hosted_labels": [
            "self-hosted",
            "linux",
            "x64",
            "trimem-ubuntu-24.04",
            "trimem-benchmark",
        ],
        "environment_binding": {
            "live_listener_count": 2,
            "persisted_env_count": 2,
            "required_name": "LD_LIBRARY_PATH",
            "required_value": (
                "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib"
            ),
            "single_exact_binding_per_environment": True,
        },
        "exact_runner_count_required_before_request": 2,
        "local_registration": {
            "disable_update": True,
            "ephemeral": True,
        },
        "ordinary_hosted_job_can_match_benchmark_runner": False,
        "protected_runtime": runtime,
        "runner_process_identity": {
            "gid": 1000,
            "uid": 1000,
            "user": "trimem-runner",
        },
        "runner_listener_lock": {
            "bytes": 72_568,
            "sha256": (
                "f4584cf5ef53ebc8507e9edfad07973e389ff6488906a1abe5f698aa86b295cf"
            ),
            "version": "2.337.0",
        },
        "runner_package_lock": {
            "archive_bytes": 226_430_031,
            "archive_path": (
                "/opt/trimem-runner-cache/"
                "actions-runner-linux-x64-2.337.0.tar.gz"
            ),
            "archive_sha256": (
                "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613"
            ),
            "version": "2.337.0",
        },
        "windows_to_wsl_transport": {
            "distribution": "TriMemRunner2404",
            "execution_option": "--exec",
            "explicit_user": "trimem-runner",
            "identity_probe_binary": "/usr/bin/id",
        },
    }
    repeated = reseal.validate_runner_isolation()
    assert repeated == contract
    assert reseal.canonical_bytes(repeated) == reseal.canonical_bytes(contract)


@pytest.mark.parametrize(
    "marker",
    [
        b'frozen_runner.get("benchmark_exec_runner_boundary")',
        b'local_config.get("disableUpdate") is True',
        b'local_config.get("ephemeral") is True',
        b"expected_sha256=RUNNER_PACKAGE_ARCHIVE_SHA256",
        b"expected_sha256=RUNNER_LISTENER_SHA256",
        b"library_entries != ['LD_LIBRARY_PATH=' + expected_library_path]",
        b'config.get("disableUpdate") is True',
        b'config.get("ephemeral") is True',
        b'        "--user",',
        b'return [*arguments, "--exec"]',
        b'expected = f"{RUNNER_SERVICE_UID}:{RUNNER_SERVICE_GID}:{RUNNER_WSL_USER}"',
        b"/usr/bin/id -u)",
        b"_validate_wsl_runner_identity(wsl_identity)",
        b"_validate_local_runner_identity(os.getuid(), os.getgid(), user)",
        b'"wsl_uid": runner_uid',
        b'host.get("wsl_uid") == RUNNER_SERVICE_UID',
    ],
)
def test_reseal_rejects_missing_runner_contract_source_marker(
    monkeypatch: pytest.MonkeyPatch, marker: bytes
) -> None:
    real_source_bytes = reseal.source_bytes

    def altered_source_bytes(relative: str) -> bytes:
        raw = real_source_bytes(relative)
        if relative == "scripts/trimem_development_trigger_d112.py":
            assert marker in raw
            return raw.replace(marker, b"REMOVED_RUNNER_CONTRACT_MARKER", 1)
        return raw

    monkeypatch.setattr(reseal, "source_bytes", altered_source_bytes)
    with pytest.raises(reseal.D112ResealError, match="D1.12"):
        reseal.validate_runner_isolation()


def test_protected_runtime_contract_is_exact_and_zero_authority() -> None:
    contract = reseal.validate_protected_runtime_contract()
    request_required_order = [
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

    assert contract == {
        "docker_authority": {
            "client_binary": {
                "bytes": 31_369_824,
                "path": "/usr/bin/docker",
                "sha256": (
                    "7ed12b00293d64742419a6601ae97960a367a0ce97c88b06e3278cc0a409557b"
                ),
            },
            "client_server_version": "29.1.3",
            "create_pull_policy": "CREATE_PULL_NEVER_CACHE_ONLY",
            "forbidden_override_environment": [
                "DOCKER_API_VERSION",
                "DOCKER_CERT_PATH",
                "DOCKER_CONFIG",
                "DOCKER_CONTENT_TRUST",
                "DOCKER_CONTENT_TRUST_SERVER",
                "DOCKER_CONTEXT",
                "DOCKER_DEFAULT_PLATFORM",
                "DOCKER_HOST",
                "DOCKER_TLS",
                "DOCKER_TLS_VERIFY",
            ],
            "native_job_services_allowed": False,
            "registry_or_pull_allowed": False,
            "root_directory": "/var/lib/docker",
            "socket": "unix:///var/run/docker.sock",
        },
        "pending_workflow_consumers": {
            "active_rows_required": 0,
            "checked_before_observation_and_before_write": True,
            "complete_paginated_snapshot_required": True,
            "single_transition_safe_snapshot": True,
            "statuses": [
                "in_progress",
                "pending",
                "queued",
                "requested",
                "waiting",
            ],
        },
        "pre_setup_cache_host": {
            "active_root_tool_cache_template": "{active_root}/_work/_tool",
            "active_root_tool_cache_symlink_required": True,
            "allowed_jobs": ["bounded-context-preflight", "frozen-serial-phase"],
            "central_tool_cache_direct_directory": (
                "/opt/trimem-runner-cache/work-ci/_tool"
            ),
            "marker_bytes": 0,
            "marker_direct_regular_non_symlink": True,
            "marker_path": (
                "/opt/trimem-runner-cache/work-ci/_tool/"
                "Python/3.11.10/x64.complete"
            ),
            "marker_sha256": (
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            ),
            "runs_before_setup_python": True,
            "workflow_forwarding_count_per_job": 2,
        },
        "protected_live_runner": {
            "active_listener_count": 1,
            "dual_root_name_mapping": {
                "trimem-d112-exec": "/opt/trimem-d112-runners/exec",
                "trimem-d112-preflight": "/opt/trimem-d112-runners/preflight",
            },
            "process_identity": {
                "gid": 1000,
                "uid": 1000,
                "user": "trimem-runner",
            },
            "source_snapshot_age_superseded_by_live_observation": True,
            "teardown_listener_count_max": 1,
        },
        "services": {
            "container_name_template": "trimem-d112-{run_id}-{role}",
            "images": {
                "postgres": (
                    "postgres@sha256:"
                    "e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412"
                ),
                "qdrant": (
                    "qdrant/qdrant@sha256:"
                    "241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636"
                ),
            },
            "loopback_ports": {"postgres": 5432, "qdrant": 6333},
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
                "poll_seconds": 2,
                "timeout_seconds": 120,
            },
            "state": {
                "baseline_restored_on_partial_or_final_cleanup": True,
                "canonical_utf8_json_plus_lf": True,
                "exclusive_mode_octal": "0600",
                "filename": "trimem-d112-cache-only-services.json",
                "owner_gid": 1000,
                "owner_uid": 1000,
                "retry_safe_owned_or_absent_cleanup": True,
                "run_source_trigger_labels_required": True,
                "schema": "trimem/protected-cache-only-services/1.0",
            },
        },
        "workflow": {
            "always_cleanup_is_final_step": True,
            "other_custom_label_workflows_allowed": False,
            "protected_step_sequence": [
                "Checkout approved frozen source",
                "Verify complete cached Python before setup-python",
                "Set up exact Python",
                "Re-observe protected runner before cache-only service creation",
                "Start exact cache-only benchmark services",
                "Verify exact cache-only benchmark services",
                "Install hash-locked environment",
            ],
            "request_required_order": request_required_order,
            "service_consumer_bindings": [
                (
                    "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@"
                    "127.0.0.1:5432/trimem_benchmark"
                ),
                "TRIMEM_QDRANT_URL: http://127.0.0.1:6333",
                (
                    "DATABASE_URL: postgresql://postgres:postgres@"
                    "127.0.0.1:5432/trimem_benchmark"
                ),
                "PGHOST: 127.0.0.1",
                (
                    "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:"
                    "postgres@127.0.0.1:5432/trimem_benchmark"
                ),
            ],
        },
        "zero_authority_actuals": reseal.ZERO_ACTUALS,
    }
    assert reseal.canonical_bytes(contract) == reseal.canonical_bytes(
        reseal.validate_protected_runtime_contract()
    )


@pytest.mark.parametrize(
    "marker",
    [
        b'label="pre-setup exact Python toolcache complete marker"',
        b'bindings.get("RUNNER_TOOL_CACHE") == expected_value',
        b"selected.is_symlink()",
        b"central_resolved == central",
        b"active_root=RUNNER_ROOTS[matching[0]]",
        b"del now",
        b'or name.upper().startswith("DOCKER_")',
        b"expected_sha256=DOCKER_CLIENT_SHA256",
        b"raw == DOCKER_ROOT_DIRECTORY",
        b'"--pull=never"',
        b"raw == canonical_bytes(state, trailing_lf=True)",
        (
            b"and uid == RUNNER_SERVICE_UID\n"
            b"        and gid == RUNNER_SERVICE_GID,\n"
            b'        "service state process ownership differs"'
        ),
        b'os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)',
        b"os.O_WRONLY | os.O_CREAT | os.O_EXCL",
        b"deadline = monotonic() + SERVICE_READY_TIMEOUT_SECONDS",
        b"allow_absent=True",
        b"present_ids.issubset(expected_ids)",
        b'evidence.get("runner_user") == RUNNER_WSL_USER',
        b'active_statuses = {"in_progress", "pending", "queued", "requested", "waiting"}',
        b"final exact cache-only service and volume cleanup",
    ],
)
def test_reseal_rejects_missing_protected_runtime_source_marker(
    monkeypatch: pytest.MonkeyPatch, marker: bytes
) -> None:
    real_source_bytes = reseal.source_bytes

    def altered_source_bytes(relative: str) -> bytes:
        raw = real_source_bytes(relative)
        if relative == "scripts/trimem_development_trigger_d112.py":
            assert marker in raw
            return raw.replace(marker, b"REMOVED_PROTECTED_RUNTIME_MARKER", 1)
        return raw

    monkeypatch.setattr(reseal, "source_bytes", altered_source_bytes)
    with pytest.raises(reseal.D112ResealError, match="D1.12"):
        reseal.validate_protected_runtime_contract()


@pytest.mark.parametrize(
    "marker",
    [
        b"Verify complete cached Python before setup-python",
        b"RUNNER_TOOL_CACHE: ${{ runner.tool_cache }}",
        b"Re-observe protected runner before cache-only service creation",
        b"Start exact cache-only benchmark services",
        b"Verify exact cache-only benchmark services",
        b"TRIMEM_QDRANT_URL: http://127.0.0.1:6333",
        (
            b"      - name: Remove exact cache-only benchmark services\n"
            b"        if: always()"
        ),
    ],
)
def test_reseal_rejects_missing_protected_workflow_marker(
    monkeypatch: pytest.MonkeyPatch, marker: bytes
) -> None:
    real_source_bytes = reseal.source_bytes

    def altered_source_bytes(relative: str) -> bytes:
        raw = real_source_bytes(relative)
        if relative == ".github/workflows/trimem-benchmark.yml":
            assert marker in raw
            return raw.replace(marker, b"REMOVED_PROTECTED_WORKFLOW_MARKER", 1)
        return raw

    monkeypatch.setattr(reseal, "source_bytes", altered_source_bytes)
    with pytest.raises(reseal.D112ResealError, match="D1.12"):
        reseal.validate_protected_runtime_contract()


def test_cross_platform_observer_is_byte_locked_and_bounded() -> None:
    contract = reseal.validate_github_observer_contract()

    assert contract["lock_schema"] == "trimem/gh-cli-lock/1.1"
    assert contract["first_version_line"] == "gh version 2.97.0 (2026-07-31)"
    assert contract["observer_selection_policy"] == (
        "PLATFORM_EXACT_BYTES_AND_VERSION_NO_UNVERIFIED_FALLBACK"
    )
    assert contract["shared_legacy_consumer"] == {
        "current_schema_from_shared_consumer": "trimem/gh-cli-lock/1.1",
        "historical_schema": "trimem/gh-cli-lock/1.0",
        "historical_schema_requires_windows_observer_absent": True,
    }
    assert contract["windows_executable_name_policy"] == "CASEFOLD_EQUALS_GH_EXE"
    assert contract["report_line_ending_contract"] == "GIT_ATTRIBUTE_TEXT_EOL_LF"
    assert contract["platforms"] == {
        "linux_amd64": {
            "archive_sha256": (
                "a2c9b8497e1f85b1ad0dfcb78b5a622e098801b8e461e459e88e1ee12f018112"
            ),
            "binary_sha256": (
                "141507c337e8b202ad398550c3b73d72f5af92e86f71665214538a81efd4c409"
            ),
        },
        "windows_amd64": {
            "archive_sha256": (
                "35d7fe05c4dd1411ffda1e73dfc7c6f44b75c936ca51fa6595c657fdc0350cec"
            ),
            "binary_sha256": (
                "e2efa10a5d2ce93cac9bc4b676932b62947c0967c01c8f2c3a9cb4437ad358d3"
            ),
        },
    }
    assert contract["same_verified_transport_for"] == [
        "current_pull_request",
        "current_execution_workflow_run",
        "source_workflow_runs",
        "repository_runners",
    ]
    assert contract["wsl_exact_python_probes"] == {
        "executable_path": (
            "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/bin/python"
        ),
        "launch_prefix": [
            "env",
            (
                "LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/"
                "Python/3.11.10/x64/lib"
            ),
            (
                "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/"
                "x64/bin/python"
            ),
        ],
        "library_path": (
            "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib"
        ),
        "no_host_environment_fallback": True,
        "probe_sites": [
            "exact_python_version",
            "service_port_availability",
            "listener_identity_and_secret_name_absence",
            "runner_identity_and_config_secret_name_absence",
        ],
        "readiness_evidence_field": "host.exact_python_library_path",
    }
    assert contract["repository_custody"] == {
        "exact_git_top_level_required": True,
        "nested_or_superproject_path_rejected": True,
        "public_entrypoints": [
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
        ],
        "pre_write_recheck": [
            "exact_git_top_level",
            "expected_branch",
            "unchanged_source_head",
            "clean_tracked_and_untracked_worktree",
            "sentinel_absent_from_history_and_filesystem",
        ],
        "pre_write_recheck_occurs_after_remote_observations": True,
    }
    assert contract["visibility_polling"] == {
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
    }
    for relative in (
        ".gitattributes",
        "configs/trimem_v1/gh_cli_lock.json",
        "scripts/trimem_development_trigger_preflight.py",
        "scripts/trimem_install_pinned_gh.py",
        "scripts/trimem_multi_swe_contract.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
        "tests/unit/test_trimem_pinned_gh.py",
    ):
        assert relative in reseal.IMPLEMENTATION_PATHS
        assert reseal.REQUIRED_CHANGED_PATHS[relative] == "M"


@pytest.mark.parametrize(
    "marker",
    [
        b'"rev-parse", "--show-toplevel"',
        b"deadline = monotonic() + REMOTE_VISIBILITY_TIMEOUT_SECONDS",
        b"allowed_stale_head=before",
        b"candidate = _query_github_run_by_id(",
        b"exact_run_id == expected_run_id",
        b'EXACT_PYTHON_LIBRARY_PATH = f"{EXACT_PYTHON_ROOT}/lib"',
        b'_wsl_exact_python_argv("--version")',
        b'host.get("exact_python_library_path") == EXACT_PYTHON_LIBRARY_PATH',
        b'"exact_python_library_path": EXACT_PYTHON_LIBRARY_PATH',
        b"_recheck_request_write_boundary(repository, source_head, target)",
        b"not os.path.lexists(target)",
    ],
)
def test_reseal_rejects_missing_trigger_hardening_source_marker(
    monkeypatch: pytest.MonkeyPatch, marker: bytes
) -> None:
    real_source_bytes = reseal.source_bytes

    def altered_source_bytes(relative: str) -> bytes:
        raw = real_source_bytes(relative)
        if relative == "scripts/trimem_development_trigger_d112.py":
            assert marker in raw
            return raw.replace(marker, b"REMOVED_REVIEWER_HARDENING_MARKER", 1)
        return raw

    monkeypatch.setattr(reseal, "source_bytes", altered_source_bytes)
    with pytest.raises(reseal.D112ResealError, match="D1.12"):
        reseal.validate_github_observer_contract()


@pytest.mark.parametrize(
    "marker",
    [
        b"LOCK_SCHEMA as CURRENT_GH_CLI_LOCK_SCHEMA",
        b'schema == LEGACY_GH_CLI_LOCK_SCHEMA and "windows_observer" not in gh_lock',
        b"_validate_gh_cli_lock_schema(gh_lock)",
    ],
)
def test_reseal_rejects_stale_shared_gh_schema_consumer(
    monkeypatch: pytest.MonkeyPatch, marker: bytes
) -> None:
    real_source_bytes = reseal.source_bytes

    def altered_source_bytes(relative: str) -> bytes:
        raw = real_source_bytes(relative)
        if relative == "scripts/trimem_development_trigger_preflight.py":
            assert marker in raw
            return raw.replace(marker, b"REMOVED_SHARED_SCHEMA_MARKER", 1)
        return raw

    monkeypatch.setattr(reseal, "source_bytes", altered_source_bytes)
    with pytest.raises(reseal.D112ResealError, match="shared historical"):
        reseal.validate_github_observer_contract()


def test_observer_and_custody_contract_is_canonically_reproducible() -> None:
    first = reseal.validate_github_observer_contract()
    second = reseal.validate_github_observer_contract()

    assert first == second
    assert reseal.canonical_bytes(first) == reseal.canonical_bytes(second)


def test_activation_report_records_observer_scope_without_execution_claim() -> None:
    report = (ROOT / "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md").read_text(
        encoding="utf-8"
    )

    assert "same verified GitHub CLI" in report
    assert "gh_2.97.0_windows_amd64.zip" in report
    assert "Windows `gh.EXE`" in report
    assert "shared retired `_005` compatibility validator" in report
    assert "has no `windows_observer`" in report
    assert "30-second monotonic wall-clock deadline" in report
    assert "explicitly supplied immediate predecessor" in report
    assert "source-gate and runner-set evidence never poll" in report
    assert "`ephemeral: true`" in report
    assert "`disableUpdate: true`" in report
    assert "wsl -d TriMemRunner2404 --user trimem-runner --" in report
    assert "1000:1000:trimem-runner" in report
    assert "actions-runner-linux-x64-2.337.0.tar.gz" in report
    assert "226430031" in report
    assert "70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613" in report
    assert "f4584cf5ef53ebc8507e9edfad07973e389ff6488906a1abe5f698aa86b295cf" in report
    assert "LD_LIBRARY_PATH" in report
    assert "exactly one `LD_LIBRARY_PATH` binding" in report
    assert "no host-environment fallback" in report
    assert "x64.complete" in report
    assert "`${{ runner.tool_cache }}`" in report
    assert "active runner root's `_work/_tool`" in report
    assert "symlink resolving to the direct, non-symlink central directory" in report
    assert "exactly one active listener" in report
    assert "Docker `29.1.3`" in report
    assert "31369824" in report
    assert "7ed12b00293d64742419a6601ae97960a367a0ce97c88b06e3278cc0a409557b" in report
    assert "unix:///var/run/docker.sock" in report
    assert "case-insensitive `DOCKER_*` namespace" in report
    assert "docker create --pull=never" in report
    assert "127.0.0.1:5432" in report
    assert "127.0.0.1:6333" in report
    assert "120-second monotonic wall-clock deadline" in report
    assert "mode-`0600`" in report
    assert "UID/GID `1000:1000`" in report
    assert "retry-safe" in report
    assert "complete,\npaginated, transition-safe snapshot" in report
    for status in ("in_progress", "pending", "queued", "requested", "waiting"):
        assert f"`{status}`" in report
    assert "No other tracked workflow" in report
    assert "activation counters remain zero" in report
    assert "exact Git top-level" in report
    assert "rechecks all mutable local preconditions" in report
    assert "no benchmark image" in report
    assert "not DEV execution approval" in report


def test_d112_artifacts_are_reproducible_and_keep_zero_execution_authority() -> None:
    expected_amendment = read_historical(
        "artifacts/trimem_v1/development_exec_012_activation_amendment.json"
    )
    expected_inventory = read_historical(
        "artifacts/trimem_v1/development_exec_012_activation_inventory.json"
    )
    amendment = read(
        "artifacts/trimem_v1/development_exec_012_activation_amendment.json"
    )
    inventory = read(
        "artifacts/trimem_v1/development_exec_012_activation_inventory.json"
    )

    assert amendment == expected_amendment
    assert inventory == expected_inventory
    assert inventory["github_observer"] == amendment["github_observer"]
    assert amendment["zero_cost_activation_actuals"] == reseal.ZERO_ACTUALS
    assert amendment["authority_boundary"] == {
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
    historical = current_reseal.validate_historical_d112()
    assert historical["source_head"] == D112_SOURCE_HEAD
    assert historical["execution_head"] == current_reseal.D112_EXECUTION_HEAD
    assert historical["sentinel_only"] is True
