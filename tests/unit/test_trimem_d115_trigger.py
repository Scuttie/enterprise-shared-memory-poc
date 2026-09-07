from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d114 as d114  # noqa: E402
import trimem_development_trigger_d115 as d115  # noqa: E402


def _alias_evidence() -> dict[str, object]:
    target = d115.COMPILED_PREFIX_ALIAS_TARGET
    prefix = f"{target}/Python/3.11.10/x64"
    directories = [
        "/",
        "/opt",
        "/opt/trimem-runner-cache",
        "/opt/trimem-runner-cache/work-ci",
        target,
        f"{target}/Python",
        f"{target}/Python/3.11.10",
        prefix,
        f"{prefix}/bin",
        f"{prefix}/lib",
    ]
    return {
        "alias_path": d115.COMPILED_PREFIX_ALIAS,
        "alias_uid": 0,
        "compiled_libpython_path": (
            f"{d115.COMPILED_PREFIX_ALIAS}/Python/3.11.10/x64/lib/"
            "libpython3.11.so.1.0"
        ),
        "compiled_python_path": (
            f"{d115.COMPILED_PREFIX_ALIAS}/Python/3.11.10/x64/bin/python3.11"
        ),
        "expected_lexical_target": target,
        "libdir_mode": "0755",
        "libpython_bytes": 23_014_032,
        "libpython_mode": "0755",
        "libpython_realpath": f"{prefix}/lib/libpython3.11.so.1.0",
        "libpython_sha256": (
            "f102768d427dd8441feed6e4b5cd950077d17e097b95fc3dcc59bd99838ac97d"
        ),
        "observed_lexical_target": target,
        "python_binary_bytes": 17_736,
        "python_binary_mode": "0755",
        "python_binary_realpath": f"{prefix}/bin/python3.11",
        "python_binary_sha256": (
            "930be806841bf98ef6898a7d8c69b0083b68c803c5fcd7a77becefaf84bc25c9"
        ),
        "resolved_libdir": f"{prefix}/lib",
        "resolved_prefix": prefix,
        "resolved_target": target,
        "schema": d115.COMPILED_PREFIX_ALIAS_SCHEMA,
        "secure_directories": [
            {"mode": "0755", "path": path, "uid": 0 if path in {"/", "/opt"} else 1000}
            for path in directories
        ],
        "status": "PASS",
    }


def _loader_rehearsal(
    readiness: dict[str, object], *, observed_at: str = "2026-09-08T00:00:00.000Z"
) -> dict[str, object]:
    alias = _alias_evidence()
    preflight = {
        "counters": {
            "grader_attempts": 0,
            "grader_containers": 0,
            "image_pulls": 0,
            "model_generation_calls": 0,
            "model_metadata_requests": 0,
            "paid_calls": 0,
            "usd": 0,
        },
        "environment_constructor": {"status": "PASS"},
        "environment_identity_sha256": "0" * 64,
        "environment_keys": [],
        "invocation_construction": {
            "docker_executions": 0,
            "host_prepare_script_reads": 0,
            "source_image_build_calls": 0,
            "status": "PASS",
        },
        "marker": "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS",
        "multi_revision": {"status": "PASS"},
        "multi_self_check": {"status": "PASS"},
        "python_loader": {
            "libdir": alias["resolved_libdir"],
            "libpython_realpath": alias["libpython_realpath"],
            "libpython_sha256": alias["libpython_sha256"],
            "python_binary_realpath": alias["python_binary_realpath"],
            "python_binary_sha256": alias["python_binary_sha256"],
            "python_prefix": alias["resolved_prefix"],
            "status": "PASS",
        },
        "schema": "trimem/official-harness-loader-preflight/1.0",
        "status": "PASS",
        "swe_import_check": {"status": "PASS"},
        "swe_revision": {"status": "PASS"},
    }
    preflight_sha = hashlib.sha256(d115.canonical_bytes(preflight)).hexdigest()
    return {
        "activation_actuals": dict(d115.ACTIVATION_ZERO_COUNTERS),
        "alias_evidence": alias,
        "benchmark_validation": {
            "preflight_sha256": preflight_sha,
            "status": "PASS",
            "validator": (
                "trimem_benchmark_run."
                "validate_official_harness_loader_preflight_evidence"
            ),
        },
        "full_loader_preflight": preflight,
        "observed_at_utc": observed_at,
        "repository": d115.EXPECTED_REPOSITORY,
        "runner_names": list(d115.RUNNER_NAMES),
        "runner_readiness_sha256": hashlib.sha256(
            d115.canonical_bytes(readiness)
        ).hexdigest(),
        "schema": d115.LOADER_REHEARSAL_SCHEMA,
        "source_head": d115.PREVIOUS_EXECUTION_HEAD,
        "status": "PASS",
    }


def test_d115_identity_and_authority_are_request_only() -> None:
    assert d115.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015"
    assert d115.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_015.json")
    assert d115.AMENDMENT_ENDPOINT == "TRIMEM_V1_READY_FOR_EXEC_015_REQUEST"
    assert d115.PREVIOUS_RUN_ID == 34147189320
    assert d115.PREVIOUS_RUN_ATTEMPT == 1
    assert "loader_rehearsal_path" not in inspect.signature(d115.write_request).parameters
    assert "loader_rehearsal_path" not in inspect.signature(d115.main).parameters


def test_d115_runtime_context_is_reversible() -> None:
    original = d114.REQUEST_ID
    with d115._d115_runtime_context():
        assert d114.REQUEST_ID == d115.REQUEST_ID
        assert d114.SENTINEL_PATH == d115.SENTINEL_PATH
        assert d114._load_previous_request is d115._load_previous_request
    assert d114.REQUEST_ID == original


def test_runner_readiness_uses_system_wsl_and_restores_inherited_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    system_wsl = r"C:\Windows\System32\wsl.exe"
    original_shutil = d115.d112.shutil
    original_safe_environment = d115.d112._safe_process_environment
    original_command_prefix = d115.d112._wsl_command_prefix
    observed: list[dict[str, object]] = []
    order: list[str] = []

    def observer() -> tuple[str, dict[str, str]]:
        order.append("observer")
        return "gh", {"GH_TOKEN": "observer-only"}

    def resolve_wsl() -> str:
        order.append("wsl")
        return system_wsl

    monkeypatch.setattr(d115, "_pinned_gh_context", observer)
    monkeypatch.setattr(d115, "_system_wsl_path", resolve_wsl)
    monkeypatch.setenv("PATH", r"C:\attacker")
    monkeypatch.setenv("SYSTEMROOT", r"C:\attacker-root")
    monkeypatch.setenv("WSLENV", "PYTHONPATH/u:LD_PRELOAD/u")
    monkeypatch.setenv("PYTHONPATH", r"C:\attacker-python")
    monkeypatch.setenv("LD_PRELOAD", "/attacker/preload.so")

    def collect(*_args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["_observer_context"] == (
            "gh",
            {"GH_TOKEN": "observer-only"},
        )
        order.append("collect")
        observed.append(
            {
                "environment": d115.d112._safe_process_environment(),
                "prefix": d115.d112._wsl_command_prefix(
                    d115.d112.shutil.which("wsl.exe"),
                    cwd=d115.RUNNER_ROOTS[0],
                ),
            }
        )
        return {"status": "PASS"}

    monkeypatch.setattr(d115.d113, "collect_runner_readiness", collect)
    result = d115.collect_runner_readiness(
        ROOT,
        d115.PREVIOUS_EXECUTION_HEAD,
    )

    assert result == {"status": "PASS"}
    assert order == ["observer", "wsl", "collect"]
    environment = observed[0]["environment"]
    assert isinstance(environment, dict)
    assert environment["SystemRoot"] == r"C:\Windows"
    assert environment["WINDIR"] == r"C:\Windows"
    assert not {
        "PATH",
        "SYSTEMROOT",
        "WSLENV",
        "PYTHONPATH",
        "LD_PRELOAD",
    } & set(environment)
    assert observed[0]["prefix"] == [
        system_wsl,
        "-d",
        d115.RUNNER_DISTRIBUTION,
        "--user",
        d115.RUNNER_WSL_USER,
        "--cd",
        d115.RUNNER_ROOTS[0],
        "--exec",
        "/usr/bin/env",
        "-i",
        f"HOME={d115.WSL_COLLECTOR_HOME}",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        f"PATH={d115.WSL_COLLECTOR_PATH}",
        f"LD_LIBRARY_PATH={d115.EXACT_PYTHON_LIBRARY_PATH}",
    ]
    assert d115.d112.shutil is original_shutil
    assert d115.d112._safe_process_environment is original_safe_environment
    assert d115.d112._wsl_command_prefix is original_command_prefix


def test_runner_readiness_restores_inherited_globals_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    originals = (
        d115.d112.shutil,
        d115.d112._safe_process_environment,
        d115.d112._wsl_command_prefix,
    )
    monkeypatch.setattr(
        d115, "_system_wsl_path", lambda: r"C:\Windows\System32\wsl.exe"
    )

    def fail(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise RuntimeError("expected test failure")

    monkeypatch.setattr(d115.d113, "collect_runner_readiness", fail)
    with pytest.raises(RuntimeError, match="expected test failure"):
        d115.collect_runner_readiness(
            ROOT,
            d115.PREVIOUS_EXECUTION_HEAD,
            _observer_context=("gh", {}),
        )

    assert (
        d115.d112.shutil,
        d115.d112._safe_process_environment,
        d115.d112._wsl_command_prefix,
    ) == originals


def test_immutable_exec_014_request_reader_uses_exact_git_blob() -> None:
    request = d115._load_previous_request(ROOT, d115.PREVIOUS_EXECUTION_HEAD)

    assert request["request_id"] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
    assert request["source_head"] == d115.PREVIOUS_SOURCE_HEAD
    assert request["actual_execution_authorized"] is False
    assert request["external_execution_approval_received"] is False


def test_recovery_scope_requires_trusted_collector_and_excludes_science() -> None:
    assert d115.LOADER_REHEARSAL_COLLECTOR_PATH in d115.REQUIRED_RECOVERY_CHANGES
    assert d115.COMPILED_PREFIX_ALIAS_PATH in d115.REQUIRED_RECOVERY_CHANGES
    assert "configs/trimem_v1/model_lock.json" not in d115.ALLOWED_RECOVERY_PATHS
    assert "configs/trimem_v1/development_manifest.json" not in d115.ALLOWED_RECOVERY_PATHS


def test_full_loader_rehearsal_binds_alias_loader_validator_and_freshness() -> None:
    readiness = {"stable": "runner-readiness"}
    evidence = _loader_rehearsal(readiness)

    observed = d115.validate_loader_rehearsal(
        evidence,
        source_head=d115.PREVIOUS_EXECUTION_HEAD,
        runner_readiness=readiness,
        now=datetime(2026, 9, 8, 0, 1, tzinfo=timezone.utc),
    )

    assert observed == evidence


@pytest.mark.parametrize(
    "mutation",
    [
        "stale",
        "alias_path_subset",
        "loader_binary",
        "validator_digest",
        "nonzero_counter",
        "marker_only",
    ],
)
def test_full_loader_rehearsal_mutations_fail_closed(mutation: str) -> None:
    readiness = {"stable": "runner-readiness"}
    evidence = _loader_rehearsal(readiness)
    if mutation == "stale":
        evidence["observed_at_utc"] = "2020-01-01T00:00:00.000Z"
    elif mutation == "alias_path_subset":
        evidence["alias_evidence"]["secure_directories"].pop()
    elif mutation == "loader_binary":
        evidence["full_loader_preflight"]["python_loader"][
            "python_binary_realpath"
        ] = "/tmp/not-frozen-python"
    elif mutation == "validator_digest":
        evidence["benchmark_validation"]["preflight_sha256"] = "f" * 64
    elif mutation == "nonzero_counter":
        evidence["full_loader_preflight"]["counters"]["paid_calls"] = 1
    elif mutation == "marker_only":
        evidence["full_loader_preflight"] = {
            "marker": "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS"
        }

    with pytest.raises(d115.DevelopmentTriggerError):
        d115.validate_loader_rehearsal(
            evidence,
            source_head=d115.PREVIOUS_EXECUTION_HEAD,
            runner_readiness=readiness,
            now=datetime(2026, 9, 8, 0, 1, tzinfo=timezone.utc),
        )


def test_wsl_collector_host_environment_is_an_allowlist() -> None:
    environment = {
        "SystemRoot": r"C:\Windows",
        "TEMP": r"C:\Temp",
        "PATH": r"C:\attacker",
        "PYTHONPATH": r"C:\attacker\python",
        "PYTHONHOME": r"C:\attacker\home",
        "VIRTUAL_ENV": r"C:\attacker\venv",
        "WSLENV": "PYTHONPATH/u:LD_PRELOAD/u",
        "LD_PRELOAD": "/attacker/preload.so",
    }

    observed = d115._wsl_collector_host_environment(
        environment, system_root=r"C:\RealWindows"
    )

    assert observed == {
        "TEMP": r"C:\Temp",
        "SystemRoot": r"C:\RealWindows",
        "WINDIR": r"C:\RealWindows",
    }


def test_exact_loader_rehearsal_uses_isolated_absolute_wsl_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    readiness = {"stable": "fresh-readiness"}
    calls: list[tuple[list[str], dict[str, str], str]] = []
    host_environment = {"SystemRoot": r"C:\Windows"}

    monkeypatch.setattr(d115, "resolve_repository_root", lambda path: Path(path))
    monkeypatch.setattr(
        d115,
        "_wsl_collector_host_environment",
        lambda _environment, *, system_root: host_environment,
    )
    monkeypatch.setattr(
        d115, "_system_wsl_path", lambda: r"C:\Windows\System32\wsl.exe"
    )

    def run(
        argv: object, *, environment: object, label: str, timeout: float
    ) -> bytes:
        del timeout
        calls.append((list(argv), dict(environment), label))
        if label == "WSL path translation":
            return b"/mnt/c/frozen-path\n"
        assert label == "exact full loader rehearsal"
        return d115.canonical_bytes(
            _loader_rehearsal(readiness), trailing_lf=True
        )

    monkeypatch.setattr(d115, "_run_wsl_collector_command", run)
    monkeypatch.setattr(
        d115,
        "validate_loader_rehearsal",
        lambda rehearsal, **_kwargs: rehearsal,
    )

    result = d115.collect_exact_loader_rehearsal(
        ROOT, d115.PREVIOUS_EXECUTION_HEAD, readiness
    )

    assert result["status"] == "PASS"
    assert len(calls) == 3
    for argv, environment, _label in calls:
        assert argv[0] == r"C:\Windows\System32\wsl.exe"
        assert environment == host_environment
    assert calls[0][0][-4:] == ["/usr/bin/wslpath", "-a", "-u", str(ROOT)]
    collector_argv = calls[-1][0]
    assert "/usr/bin/env" in collector_argv
    env_index = collector_argv.index("/usr/bin/env")
    assert collector_argv[env_index + 1] == "-i"
    python_index = collector_argv.index(f"{d115.EXACT_PYTHON_ROOT}/bin/python3.11")
    assert collector_argv[python_index + 1] == "-I"
    assert not any(
        value.startswith(("PYTHONPATH=", "PYTHONHOME=", "VIRTUAL_ENV=", "WSLENV="))
        for value in collector_argv
    )


def test_write_request_collects_rehearsal_after_the_same_runner_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    readiness = {"stable": "fresh-readiness"}
    gates = {"stable": "remote-gates"}
    rehearsal = {"stable": "full-rehearsal"}
    events: list[object] = []

    monkeypatch.setattr(d115, "resolve_repository_root", lambda _path: repository)
    monkeypatch.setattr(d115, "_validate_secret_free_branch_environment", lambda _env: None)

    def fake_git(_repository: Path, *args: str) -> str:
        if args[:2] == ("symbolic-ref", "--quiet"):
            return d115.EXPECTED_REF + "\n"
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return d115.PREVIOUS_EXECUTION_HEAD + "\n"
        raise AssertionError(args)

    monkeypatch.setattr(d115, "git", fake_git)
    monkeypatch.setattr(d115, "_d115_runtime_context", nullcontext)
    monkeypatch.setattr(d115.d114, "_d114_runtime_context", nullcontext)
    monkeypatch.setattr(d115, "_validate_source_impl", lambda *_args: events.append("source"))
    monkeypatch.setattr(d115, "_pinned_gh_context", lambda: ("gh", {}))
    monkeypatch.setattr(
        d115,
        "_require_no_pending_benchmark_consumers",
        lambda *_args: events.append("no-pending"),
    )
    monkeypatch.setattr(d115, "collect_remote_gate_evidence", lambda *_args, **_kwargs: gates)

    def collect_readiness(*_args: object, **_kwargs: object) -> dict[str, object]:
        events.append("readiness")
        return readiness

    def collect_rehearsal(
        _repository: Path,
        _source_head: str,
        observed_readiness: dict[str, object],
    ) -> dict[str, object]:
        assert observed_readiness is readiness
        events.append("rehearsal")
        return rehearsal

    monkeypatch.setattr(d115, "collect_runner_readiness", collect_readiness)
    monkeypatch.setattr(d115, "collect_exact_loader_rehearsal", collect_rehearsal)
    monkeypatch.setattr(
        d115,
        "build_request",
        lambda *_args, **kwargs: {
            "same_readiness": kwargs["runner_readiness"] is readiness,
            "same_rehearsal": kwargs["loader_rehearsal"] is rehearsal,
        },
    )
    monkeypatch.setattr(
        d115,
        "_validate_runner_readiness_freshness",
        lambda observed: events.append(("fresh", observed is readiness)),
    )
    monkeypatch.setattr(
        d115,
        "validate_loader_rehearsal",
        lambda observed, **kwargs: events.append(
            (
                "validate-rehearsal",
                observed is rehearsal,
                kwargs["runner_readiness"] is readiness,
            )
        ),
    )
    monkeypatch.setattr(
        d115.d113,
        "_recheck_request_write_boundary",
        lambda *_args: events.append("recheck"),
    )

    result = d115.write_request(repository)

    target = repository / Path(*d115.PurePosixPath(d115.SENTINEL_PATH).parts)
    assert result["status"] == "WROTE_ZERO_AUTHORITY_SENTINEL"
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "same_readiness": True,
        "same_rehearsal": True,
    }
    assert events.index("readiness") < events.index("rehearsal")
    assert ("fresh", True) in events
    assert ("validate-rehearsal", True, True) in events
    assert events[-1] == "recheck"
