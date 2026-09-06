from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_multi_swe_entrypoint as multi_entrypoint  # noqa: E402
import trimem_official_grader as official_grader  # noqa: E402
import trimem_official_harness_loader as loader  # noqa: E402
import trimem_official_harness_loader_preflight as preflight  # noqa: E402


def _toolcache_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    prefix = tmp_path / "hostedtoolcache/Python/3.11.10/x64"
    binary = prefix / "bin/python3.11"
    library = prefix / "lib/libpython3.11.so.1.0"
    binary.parent.mkdir(parents=True)
    library.parent.mkdir(parents=True)
    binary.write_bytes(b"exact-python-binary\n")
    library.write_bytes(b"exact-libpython\n")
    binary.chmod(0o555)
    library.parent.chmod(0o555)
    library.chmod(0o444)
    return prefix, binary, library


class _LoaderProbeRunner:
    def __init__(self, *, binary: Path, prefix: Path, libdir: Path | None = None):
        self.binary = binary.resolve()
        self.prefix = prefix.resolve()
        self.libdir = (libdir or prefix / "lib").resolve()
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append({"argv": list(argv), **kwargs})
        payload = {
            "version": "3.11.10 (main, frozen)",
            "executable": str(self.binary),
            "prefix": str(self.prefix),
            "base_prefix": str(self.prefix),
            "libdir": str(self.libdir),
            "ldlibrary": loader.EXPECTED_LIBPYTHON,
        }
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n",
            stderr=b"",
        )


def test_toolcache_loader_is_exact_and_rejects_malicious_parent_environment(
    tmp_path: Path,
) -> None:
    prefix, binary, library = _toolcache_fixture(tmp_path)
    runner = _LoaderProbeRunner(binary=binary, prefix=prefix)
    source = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path / "home"),
        "LD_LIBRARY_PATH": "/attacker/one:/attacker/two",
        "LD_PRELOAD": "/attacker/inject.so",
        "PYTHONPATH": "/attacker/python",
        "PYTHONHOME": "/attacker/home",
        "VIRTUAL_ENV": "/attacker/venv",
        "OPENAI_API_KEY": "must-never-propagate",
        "TRIMEM_EXEC_APPROVAL": "must-never-propagate",
    }

    built = loader.build_official_harness_python_loader(
        source,
        python_binary=binary,
        runner=runner,
        probe_cwd=prefix,
    )

    environment = dict(built.environment)
    evidence = dict(built.evidence)
    assert environment["LD_LIBRARY_PATH"] == str((prefix / "lib").resolve())
    assert not ({"LD_PRELOAD", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} & set(environment))
    assert "/attacker" not in json.dumps(environment, sort_keys=True)
    assert "OPENAI_API_KEY" not in environment
    assert "TRIMEM_EXEC_APPROVAL" not in environment
    assert runner.calls[0]["env"]["LD_LIBRARY_PATH"] == environment["LD_LIBRARY_PATH"]
    assert runner.calls[0]["cwd"] == prefix.resolve()
    assert runner.calls[0]["argv"] == [
        str(binary.resolve()),
        "-c",
        loader.LOADER_PROBE_CODE,
    ]
    assert evidence["schema"] == "trimem/official-harness-python-loader/1.0"
    assert evidence["status"] == "PASS"
    assert evidence["python_binary_realpath"] == str(binary.resolve())
    assert evidence["python_binary_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    assert evidence["python_binary_bytes"] == len(binary.read_bytes())
    assert evidence["libpython_realpath"] == str(library.resolve())
    assert evidence["libpython_sha256"] == hashlib.sha256(library.read_bytes()).hexdigest()
    assert evidence["libpython_bytes"] == len(library.read_bytes())
    assert evidence["inherited_ld_library_path_used"] is False
    assert evidence["ld_preload_present"] is False
    assert evidence["generated_environment_keys"] == sorted(environment)
    assert "must-never-propagate" not in json.dumps(evidence, sort_keys=True)


def test_two_distinct_verified_libdirs_fail_closed(tmp_path: Path) -> None:
    prefix, binary, _library = _toolcache_fixture(tmp_path)
    second = prefix / "alternate-lib"
    second.mkdir()
    (second / loader.EXPECTED_LIBPYTHON).write_bytes(b"second-library")
    second.chmod(0o555)
    (second / loader.EXPECTED_LIBPYTHON).chmod(0o444)
    runner = _LoaderProbeRunner(binary=binary, prefix=prefix, libdir=second)

    with pytest.raises(
        loader.OfficialHarnessPythonLoaderError,
        match="exactly one trusted Python library directory",
    ):
        loader.build_official_harness_python_loader(
            {"PATH": os.environ.get("PATH", "")},
            python_binary=binary,
            runner=runner,
        )


@pytest.mark.parametrize(
    "reported_libdir, expected_message",
    [
        ("relative-lib", "LIBDIR is relative"),
        (f"attacker-one{os.pathsep}attacker-two", "must be one directory"),
    ],
)
def test_untrusted_sysconfig_libdir_is_rejected_not_ignored(
    tmp_path: Path,
    reported_libdir: str,
    expected_message: str,
) -> None:
    prefix, binary, _library = _toolcache_fixture(tmp_path)
    runner = _LoaderProbeRunner(binary=binary, prefix=prefix)
    runner.libdir = Path(reported_libdir)

    with pytest.raises(loader.OfficialHarnessPythonLoaderError, match=expected_message):
        loader.build_official_harness_python_loader(
            {"PATH": os.environ.get("PATH", "")},
            python_binary=binary,
            runner=runner,
        )


def test_absolute_sysconfig_libdir_outside_prefix_is_rejected_not_ignored(
    tmp_path: Path,
) -> None:
    prefix, binary, _library = _toolcache_fixture(tmp_path)
    outside = tmp_path / "outside-lib"
    outside.mkdir()
    (outside / loader.EXPECTED_LIBPYTHON).write_bytes(b"attacker-library")
    runner = _LoaderProbeRunner(binary=binary, prefix=prefix, libdir=outside)

    with pytest.raises(
        loader.OfficialHarnessPythonLoaderError,
        match="not a trusted Python library directory",
    ):
        loader.build_official_harness_python_loader(
            {"PATH": os.environ.get("PATH", "")},
            python_binary=binary,
            runner=runner,
        )


def test_group_writable_libpython_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prefix, _binary, library = _toolcache_fixture(tmp_path)
    # Exercise the production POSIX mode boundary deterministically even when
    # the credential-free developer suite itself runs on Windows.
    monkeypatch.setattr(loader.os, "name", "posix")
    monkeypatch.setattr(loader, "_mode", lambda _path: stat.S_IRUSR | stat.S_IWGRP)
    with pytest.raises(loader.OfficialHarnessPythonLoaderError, match="group/world writable"):
        loader._require_secure(library, kind="libpython")


def test_public_minimal_environment_omits_inherited_loader_and_secret_values() -> None:
    source = dict(os.environ)
    source.update(
        {
            "LD_LIBRARY_PATH": "/attacker/loader",
            "LD_PRELOAD": "/attacker/preload.so",
            "PYTHONPATH": "/attacker/python",
            "VIRTUAL_ENV": "/attacker/venv",
            "OPENAI_API_KEY": "forbidden-test-secret",
        }
    )
    environment = official_grader.minimal_subprocess_env(
        source,
        python_binary=sys.executable,
    )
    assert "LD_PRELOAD" not in environment
    assert "PYTHONPATH" not in environment
    assert "VIRTUAL_ENV" not in environment
    assert "OPENAI_API_KEY" not in environment
    assert "/attacker" not in json.dumps(environment, sort_keys=True)
    if os.name != "posix":
        assert "LD_LIBRARY_PATH" not in environment


def _fake_loader(binary: Path) -> loader.OfficialHarnessPythonLoader:
    environment = MappingProxyType(
        {
            "PATH": os.environ.get("PATH", ""),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONUNBUFFERED": "1",
        }
    )
    evidence = MappingProxyType(
        {
            "schema": loader.LOADER_EVIDENCE_SCHEMA,
            "python_binary_realpath": str(binary.resolve()),
            "status": "PASS",
        }
    )
    return loader.OfficialHarnessPythonLoader(environment=environment, evidence=evidence)


class _PreflightRunner:
    def __init__(self, swe_root: Path, multi_root: Path, binary: Path):
        self.swe_root = swe_root.resolve()
        self.multi_root = multi_root.resolve()
        self.binary = binary.resolve()
        self.calls: list[tuple[list[str], Path, dict[str, str]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        cwd = Path(kwargs["cwd"]).resolve()
        environment = dict(kwargs["env"])
        self.calls.append((list(argv), cwd, environment))
        if argv[0] == "git":
            revision = (
                official_grader.SWE_HARNESS_REVISION
                if cwd == self.swe_root
                else official_grader.MULTI_HARNESS_REVISION
            )
            stdout = (revision + "\n").encode("ascii")
        elif "--loader-self-check" in argv:
            stdout = json.dumps(
                {
                    "schema": preflight.MULTI_SELF_CHECK_SCHEMA,
                    "status": "PASS",
                    "harness_revision": official_grader.MULTI_HARNESS_REVISION,
                    "modules": {},
                    "cli_argument_destinations": [],
                    **dict(preflight.ZERO_COUNTERS),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        else:
            modules = {
                name: {"bytes": 1, "path": None, "sha256": "0" * 64}
                for name in ("swebench.harness.run_evaluation", "docker", "datasets", "unidiff")
            }
            modules["swebench.harness.run_evaluation"]["path"] = (
                "swebench/harness/run_evaluation.py"
            )
            stdout = json.dumps(
                {
                    "schema": preflight.SWE_IMPORT_PROBE_SCHEMA,
                    "status": "PASS",
                    "modules": modules,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")


def test_preflight_uses_exact_roots_environment_and_zero_execution_counters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    swe_root, multi_root = tmp_path / "swe", tmp_path / "multi"
    swe_root.mkdir()
    multi_root.mkdir()
    binary = Path(sys.executable)
    runner = _PreflightRunner(swe_root, multi_root, binary)
    validated: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        preflight,
        "validate_pristine_checkout",
        lambda root, revision: validated.append((root, revision)),
    )

    result = preflight.run_official_harness_loader_preflight(
        python_binary=binary,
        swe_harness_root=swe_root,
        multi_harness_root=multi_root,
        source_environment={"PATH": os.environ.get("PATH", "")},
        runner=runner,
        loader_builder=lambda *_args, **_kwargs: _fake_loader(binary),
        environment_builder=lambda *_args, **_kwargs: dict(
            _fake_loader(binary).environment
        ),
    )

    assert result["schema"] == preflight.PREFLIGHT_SCHEMA
    assert result["marker"] == preflight.PREFLIGHT_PASS
    assert result["status"] == "PASS"
    assert result["environment_constructor"] == (
        "trimem_official_grader.minimal_subprocess_env"
    )
    assert result["counters"] == dict(preflight.ZERO_COUNTERS)
    assert result["invocation_construction"]["docker_executions"] == 0
    assert result["invocation_construction"]["host_prepare_script_reads"] == 0
    assert result["invocation_construction"][
        "execution_environment_identity_sha256"
    ] == result["environment_identity_sha256"]
    assert validated == [
        (swe_root.absolute(), preflight.SWE_HARNESS_REVISION),
        (multi_root.absolute(), preflight.MULTI_HARNESS_REVISION),
    ]
    assert len(runner.calls) == 4
    assert all("OPENAI_API_KEY" not in environment for _, _, environment in runner.calls)
    assert runner.calls[2][1] == swe_root.resolve()
    assert runner.calls[3][1] == multi_root.resolve()
    assert runner.calls[3][0][0] == str(binary.resolve())
    assert "--loader-self-check" in runner.calls[3][0]
    assert all("docker" not in Path(argv[0]).name.lower() for argv, _, _ in runner.calls)


def test_preflight_failure_result_retains_exact_zero_counters() -> None:
    result = preflight.failure_result(RuntimeError("private detail must not appear"))
    assert result == {
        "schema": preflight.PREFLIGHT_SCHEMA,
        "status": "NOT_READY",
        "marker": preflight.PREFLIGHT_NOT_READY,
        "failure_type": "RuntimeError",
        "failure_reason": "credential-free official-harness loader preflight failed",
        "counters": dict(preflight.ZERO_COUNTERS),
    }
    assert "private detail" not in json.dumps(result, sort_keys=True)


def test_preflight_cli_atomically_publishes_pass_and_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {
        "schema": preflight.PREFLIGHT_SCHEMA,
        "status": "PASS",
        "marker": preflight.PREFLIGHT_PASS,
        "counters": dict(preflight.ZERO_COUNTERS),
    }
    monkeypatch.setattr(
        preflight,
        "run_official_harness_loader_preflight",
        lambda **_kwargs: expected,
    )
    output = tmp_path / "evidence/preflight.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trimem_official_harness_loader_preflight.py",
            "--swe-harness-root",
            str(tmp_path / "swe"),
            "--multi-harness-root",
            str(tmp_path / "multi"),
            "--output",
            str(output),
        ],
    )

    assert preflight.main() == 0
    assert output.read_bytes() == preflight._canonical_bytes(expected)
    stdout = capsys.readouterr().out.splitlines()
    assert json.loads(stdout[0]) == expected
    assert stdout[1] == preflight.PREFLIGHT_PASS


def test_multi_loader_self_check_imports_only_and_never_runs_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path.resolve()
    monkeypatch.setattr(multi_entrypoint, "_verify_checkout", lambda _path: root)
    actions = [SimpleNamespace(dest=name) for name in sorted(multi_entrypoint.EXPECTED_CONFIG_FIELDS)]
    modules: dict[str, object] = {}
    for index, name in enumerate(multi_entrypoint.LOADER_SELF_CHECK_MODULES):
        path = root / (name.replace(".", "/") + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# module {index}\n", encoding="utf-8")
        module = SimpleNamespace(__file__=str(path))
        if name == multi_entrypoint.UPSTREAM_MODULE:
            module.get_parser = lambda: SimpleNamespace(_actions=actions)
        modules[name] = module
    monkeypatch.setattr(
        multi_entrypoint.importlib,
        "import_module",
        lambda name: modules[name],
    )
    monkeypatch.setattr(
        multi_entrypoint,
        "_execute_guarded_cli",
        lambda *_args, **_kwargs: pytest.fail("self-check reached Docker execution guard"),
    )

    result = multi_entrypoint.loader_self_check(root)

    assert result["schema"] == multi_entrypoint.LOADER_SELF_CHECK_SCHEMA
    assert result["status"] == "PASS"
    assert result["image_pulls"] == 0
    assert result["grader_attempts"] == 0
    assert result["grader_containers"] == 0
    assert set(result["modules"]) == set(multi_entrypoint.LOADER_SELF_CHECK_MODULES)


def test_multi_loader_self_check_cli_is_disjoint_from_execution_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {
        "schema": multi_entrypoint.LOADER_SELF_CHECK_SCHEMA,
        "status": "PASS",
        "harness_revision": multi_entrypoint.PINNED_MULTI_SWE_REVISION,
        "modules": {},
        "cli_argument_destinations": [],
        "model_metadata_requests": 0,
        "model_generation_calls": 0,
        "paid_calls": 0,
        "image_pulls": 0,
        "grader_attempts": 0,
        "grader_containers": 0,
        "usd": 0,
    }
    monkeypatch.setattr(multi_entrypoint, "loader_self_check", lambda _root: expected)
    monkeypatch.setattr(
        multi_entrypoint,
        "execute_pinned_instance_only",
        lambda **_kwargs: pytest.fail("loader self-check entered production execution"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trimem_multi_swe_entrypoint.py",
            "--loader-self-check",
            "--harness-root",
            str(tmp_path),
        ],
    )

    assert multi_entrypoint.main() == 0
    assert json.loads(capsys.readouterr().out) == expected

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "trimem_multi_swe_entrypoint.py",
            "--loader-self-check",
            "--harness-root",
            str(tmp_path),
            "--config",
            str(tmp_path / "forbidden.json"),
        ],
    )
    assert multi_entrypoint.main() == 1
    failure = json.loads(capsys.readouterr().err)
    assert failure["status"] == "FAIL"
    assert failure["error_type"] == "MultiSWEEntrypointError"
