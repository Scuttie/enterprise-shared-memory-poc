"""Hermetic loader environment for pinned official-harness Python processes.

The protected benchmark runner uses the interpreter installed by
``actions/setup-python``.  Its ELF loader directory is an installation
property of that exact interpreter; it is never inherited from the parent
process.  This module derives, verifies, and records that property before any
official harness process is started.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence


LOADER_EVIDENCE_SCHEMA = "trimem/official-harness-python-loader/1.0"
EXPECTED_LIBPYTHON = "libpython3.11.so.1.0"
LOADER_PROBE_CODE = (
    "import json,os,sys,sysconfig;"
    "print(json.dumps({"
    "'version':sys.version,'executable':sys.executable,'prefix':sys.prefix,"
    "'base_prefix':sys.base_prefix,'libdir':sysconfig.get_config_var('LIBDIR'),"
    "'ldlibrary':sysconfig.get_config_var('LDLIBRARY')},sort_keys=True))"
)
SAFE_ENV_KEYS = frozenset(
    {
        "COMSPEC",
        "DOCKER_CONFIG",
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    }
)
FORBIDDEN_INHERITED_KEYS = frozenset(
    {"LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"}
)
FIXED_ENVIRONMENT = MappingProxyType(
    {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
    }
)


class OfficialHarnessPythonLoaderError(RuntimeError):
    """The exact interpreter cannot be launched under a trusted loader path."""


@dataclass(frozen=True)
class OfficialHarnessPythonLoader:
    """Verified child environment and its non-secret canonical evidence."""

    environment: Mapping[str, str]
    evidence: Mapping[str, Any]


LoaderRunner = Callable[..., subprocess.CompletedProcess[object]]
_ORIGINAL_SUBPROCESS_RUN = subprocess.run


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
    except OSError:
        if os.name != "nt" or path.stat().st_size != 0:
            raise
        # Microsoft Store execution aliases are zero-byte reparse points that
        # Windows can execute but refuses to open as files.  This branch is
        # developer-platform compatibility only; the production Linux path
        # always hashes the resolved executable bytes above.
        marker = b"WINDOWS_APP_EXECUTION_ALIAS\x00" + os.fspath(path).encode("utf-8")
        digest.update(marker)
    return digest.hexdigest(), size


def _raw_stream(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    return str(value).encode("utf-8")


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise OfficialHarnessPythonLoaderError(
                    "loader probe returned duplicate JSON fields"
                )
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialHarnessPythonLoaderError(
            "loader probe did not return strict UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise OfficialHarnessPythonLoaderError("loader probe result is not an object")
    return value


def _source_value(source: Mapping[str, str], name: str) -> str | None:
    values = [str(value) for key, value in source.items() if key.upper() == name]
    if len(values) > 1 and len(set(values)) != 1:
        raise OfficialHarnessPythonLoaderError(
            f"conflicting case variants for child environment key {name}"
        )
    return values[0] if values else None


def _resolve_python_binary(
    source: Mapping[str, str], python_binary: str | Path
) -> tuple[Path, Path]:
    supplied = os.fspath(python_binary)
    if not supplied or "\x00" in supplied:
        raise OfficialHarnessPythonLoaderError("python binary is empty or malformed")
    lexical = Path(supplied)
    if not lexical.is_absolute():
        search_path = _source_value(source, "PATH")
        if not search_path:
            raise OfficialHarnessPythonLoaderError(
                "relative python binary requires an explicit PATH"
            )
        located = shutil.which(supplied, path=search_path)
        if located is None:
            raise OfficialHarnessPythonLoaderError("python binary was not found on PATH")
        lexical = Path(located)
    lexical = Path(os.path.abspath(os.fspath(lexical)))
    try:
        real = lexical.resolve(strict=True)
    except OSError as exc:
        if os.name == "nt" and lexical.exists() and lexical.is_file():
            # Store-app execution aliases intentionally cannot be resolved by
            # ``GetFinalPathNameByHandle`` through pathlib, but remain the only
            # callable identity.  No production Linux execution reaches this.
            real = lexical
        else:
            raise OfficialHarnessPythonLoaderError("python binary does not exist") from exc
    if not real.is_file():
        raise OfficialHarnessPythonLoaderError("python binary is not a regular file")
    if os.name != "nt" and not os.access(real, os.X_OK):
        raise OfficialHarnessPythonLoaderError("python binary is not executable")
    return lexical, real


def _derived_prefix(real_python: Path) -> Path:
    parent = real_python.parent
    if parent.name.casefold() in {"bin", "scripts"}:
        return parent.parent.resolve(strict=True)
    return parent.resolve(strict=True)


def _is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _mode_text(path: Path) -> str:
    return f"{_mode(path):04o}"


def _require_secure(path: Path, *, kind: str) -> None:
    # Windows does not expose meaningful POSIX group/world write bits.  The
    # production contract is Linux; synthetic Windows tests still exercise
    # path containment, hashing, and inherited-environment rejection.
    if os.name != "nt" and _mode(path) & (stat.S_IWGRP | stat.S_IWOTH):
        raise OfficialHarnessPythonLoaderError(f"{kind} is group/world writable")


def _validated_library_directory(directory: Path, prefix: Path) -> tuple[Path, Path, Path]:
    try:
        real_directory = directory.resolve(strict=True)
    except OSError as exc:
        raise OfficialHarnessPythonLoaderError("candidate libdir does not exist") from exc
    if not real_directory.is_dir() or not _is_within(real_directory, prefix):
        raise OfficialHarnessPythonLoaderError("candidate libdir escaped Python prefix")
    _require_secure(real_directory, kind="candidate libdir")
    library_path = real_directory / EXPECTED_LIBPYTHON
    try:
        real_library = library_path.resolve(strict=True)
    except OSError as exc:
        raise OfficialHarnessPythonLoaderError(
            f"candidate libdir lacks {EXPECTED_LIBPYTHON}"
        ) from exc
    if not real_library.is_file() or not _is_within(real_library, prefix):
        raise OfficialHarnessPythonLoaderError("libpython escaped Python prefix")
    _require_secure(real_library, kind="libpython")
    return real_directory, library_path, real_library


def _validated_sysconfig_libdir(value: str, prefix: Path) -> tuple[Path, Path, Path]:
    """Validate the single LIBDIR reported by the exact interpreter.

    A reported value is authoritative input to the loader decision, so an
    invalid value is never silently discarded in favour of ``<prefix>/lib``.
    """

    if not value or "\x00" in value:
        raise OfficialHarnessPythonLoaderError("loader probe LIBDIR is empty or malformed")
    if os.pathsep in value:
        raise OfficialHarnessPythonLoaderError(
            "loader probe LIBDIR must be one directory, not a search path"
        )
    candidate = Path(value)
    if not candidate.is_absolute():
        raise OfficialHarnessPythonLoaderError("loader probe LIBDIR is relative")
    try:
        return _validated_library_directory(candidate, prefix)
    except OfficialHarnessPythonLoaderError as exc:
        raise OfficialHarnessPythonLoaderError(
            "loader probe LIBDIR is not a trusted Python library directory"
        ) from exc


def _sanitized_base_environment(source: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in source.items():
        normalized = key.upper()
        if normalized in SAFE_ENV_KEYS and normalized not in FORBIDDEN_INHERITED_KEYS:
            result[normalized] = str(value)
    result.update(FIXED_ENVIRONMENT)
    return result


def _execute_loader_probe(
    python_realpath: Path,
    *,
    environment: Mapping[str, str],
    cwd: Path,
    runner: LoaderRunner,
) -> tuple[Sequence[str], subprocess.CompletedProcess[object], dict[str, Any]]:
    argv = [str(python_realpath), "-c", LOADER_PROBE_CODE]
    try:
        completed = runner(
            argv,
            cwd=cwd,
            env=dict(environment),
            capture_output=True,
            text=False,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OfficialHarnessPythonLoaderError("exact Python loader probe failed to start") from exc
    stdout = _raw_stream(completed.stdout)
    if completed.returncode != 0:
        raise OfficialHarnessPythonLoaderError(
            f"exact Python loader probe exited {completed.returncode}"
        )
    payload = _strict_json_object(stdout)
    required = {"version", "executable", "prefix", "base_prefix", "libdir", "ldlibrary"}
    if set(payload) != required:
        raise OfficialHarnessPythonLoaderError("loader probe field set differs")
    if not all(isinstance(payload[name], str) for name in ("version", "executable", "prefix", "base_prefix")):
        raise OfficialHarnessPythonLoaderError("loader probe identity fields are invalid")
    if payload["libdir"] is not None and not isinstance(payload["libdir"], str):
        raise OfficialHarnessPythonLoaderError("loader probe LIBDIR is invalid")
    if payload["ldlibrary"] is not None and not isinstance(payload["ldlibrary"], str):
        raise OfficialHarnessPythonLoaderError("loader probe LDLIBRARY is invalid")
    return argv, completed, payload


def build_official_harness_python_loader(
    source: Mapping[str, str],
    *,
    python_binary: str | Path,
    runner: LoaderRunner | None = None,
    probe_cwd: Path | None = None,
) -> OfficialHarnessPythonLoader:
    """Derive one trusted loader directory from the exact interpreter.

    ``LD_LIBRARY_PATH`` is bootstrapped only from ``<prefix>/lib``.  The exact
    interpreter then reports ``sysconfig.LIBDIR``; both paths are resolved,
    security checked, and deduplicated.  Any second accepted directory fails
    closed rather than creating a search list.
    """

    if not isinstance(source, Mapping):
        raise OfficialHarnessPythonLoaderError("source environment must be a mapping")
    probe_runner = runner or _ORIGINAL_SUBPROCESS_RUN
    lexical_python, real_python = _resolve_python_binary(source, python_binary)
    derived_prefix = _derived_prefix(real_python)
    python_sha256, python_bytes = _sha256_file(real_python)
    python_mode = _mode_text(real_python)
    environment = _sanitized_base_environment(source)

    prefix_candidate = derived_prefix / "lib"
    bootstrap: tuple[Path, Path, Path] | None = None
    expected_at_prefix = prefix_candidate / EXPECTED_LIBPYTHON
    if expected_at_prefix.exists() or expected_at_prefix.is_symlink():
        bootstrap = _validated_library_directory(prefix_candidate, derived_prefix)
        environment["LD_LIBRARY_PATH"] = str(bootstrap[0])

    cwd = (probe_cwd or derived_prefix)
    try:
        cwd = cwd.resolve(strict=True)
    except OSError as exc:
        raise OfficialHarnessPythonLoaderError("loader probe cwd does not exist") from exc
    if not cwd.is_dir():
        raise OfficialHarnessPythonLoaderError("loader probe cwd is not a directory")

    probe_argv, completed, payload = _execute_loader_probe(
        real_python,
        environment=environment,
        cwd=cwd,
        runner=probe_runner,
    )
    try:
        observed_executable = Path(payload["executable"]).resolve(strict=True)
        executable_matches = observed_executable == real_python
    except OSError as exc:
        if os.name == "nt":
            executable_matches = os.path.normcase(
                os.path.abspath(payload["executable"])
            ) == os.path.normcase(os.path.abspath(os.fspath(real_python)))
        else:
            raise OfficialHarnessPythonLoaderError(
                "loader probe executable identity does not resolve"
            ) from exc
    if not executable_matches:
        raise OfficialHarnessPythonLoaderError("loader probe executed a different Python binary")

    posix_loader_required = os.name == "posix" or bootstrap is not None
    if posix_loader_required:
        try:
            observed_prefix = Path(payload["prefix"]).resolve(strict=True)
            observed_base_prefix = Path(payload["base_prefix"]).resolve(strict=True)
        except OSError as exc:
            raise OfficialHarnessPythonLoaderError("loader probe prefix does not resolve") from exc
        if observed_prefix != derived_prefix or observed_base_prefix != derived_prefix:
            raise OfficialHarnessPythonLoaderError("loader probe Python prefix differs")
        if payload["ldlibrary"] != EXPECTED_LIBPYTHON:
            raise OfficialHarnessPythonLoaderError("loader probe LDLIBRARY differs")
        if not payload["libdir"]:
            raise OfficialHarnessPythonLoaderError("loader probe LIBDIR is unavailable")
        accepted: dict[Path, tuple[Path, Path, Path]] = {}
        if expected_at_prefix.exists() or expected_at_prefix.is_symlink():
            validated = _validated_library_directory(prefix_candidate, derived_prefix)
            accepted[validated[0]] = validated
        sysconfig_directory = _validated_sysconfig_libdir(
            payload["libdir"], derived_prefix
        )
        accepted[sysconfig_directory[0]] = sysconfig_directory
        for candidate in accepted:
            try:
                candidate.relative_to(derived_prefix)
            except ValueError as exc:  # defensive; validators already enforce this
                raise OfficialHarnessPythonLoaderError(
                    "trusted Python library directory escaped the prefix"
                ) from exc
        if len(accepted) != 1:
            raise OfficialHarnessPythonLoaderError(
                "exactly one trusted Python library directory is required"
            )
        libdir, libpython_path, libpython_realpath = next(iter(accepted.values()))
        environment["LD_LIBRARY_PATH"] = str(libdir)
        libpython_sha256, libpython_bytes = _sha256_file(libpython_realpath)
        libdir_value: str | None = str(libdir)
        libdir_mode: str | None = _mode_text(libdir)
        libpython_path_value: str | None = str(libpython_path)
        libpython_realpath_value: str | None = str(libpython_realpath)
        libpython_mode: str | None = _mode_text(libpython_realpath)
    else:
        # Non-ELF developer platforms still use the same strict environment
        # filtering and exact-interpreter probe.  The production Linux
        # contract above never takes this branch.
        environment.pop("LD_LIBRARY_PATH", None)
        observed_prefix = Path(payload["prefix"]).resolve(strict=True)
        libdir_value = None
        libdir_mode = None
        libpython_path_value = None
        libpython_realpath_value = None
        libpython_sha256 = None
        libpython_bytes = None
        libpython_mode = None

    for forbidden in FORBIDDEN_INHERITED_KEYS:
        if forbidden != "LD_LIBRARY_PATH" and forbidden in environment:
            raise AssertionError("forbidden inherited environment key survived")
    if "LD_PRELOAD" in environment:
        raise AssertionError("LD_PRELOAD survived loader environment construction")
    stdout = _raw_stream(completed.stdout)
    stderr = _raw_stream(completed.stderr)
    evidence: dict[str, Any] = {
        "schema": LOADER_EVIDENCE_SCHEMA,
        "python_binary": str(lexical_python),
        "python_binary_realpath": str(real_python),
        "python_binary_sha256": python_sha256,
        "python_binary_bytes": python_bytes,
        "python_binary_mode": python_mode,
        "python_version": payload["version"],
        "python_prefix": str(observed_prefix),
        "libdir": libdir_value,
        "libdir_mode": libdir_mode,
        "libpython_path": libpython_path_value,
        "libpython_realpath": libpython_realpath_value,
        "libpython_sha256": libpython_sha256,
        "libpython_bytes": libpython_bytes,
        "libpython_mode": libpython_mode,
        "inherited_ld_library_path_used": False,
        "ld_preload_present": False,
        "generated_environment_keys": sorted(environment),
        "loader_probe_argv": list(probe_argv),
        "loader_probe_exit_code": completed.returncode,
        "loader_probe_stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "loader_probe_stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "status": "PASS",
    }
    return OfficialHarnessPythonLoader(
        environment=MappingProxyType(dict(environment)),
        evidence=MappingProxyType(evidence),
    )


__all__ = [
    "EXPECTED_LIBPYTHON",
    "FIXED_ENVIRONMENT",
    "FORBIDDEN_INHERITED_KEYS",
    "LOADER_EVIDENCE_SCHEMA",
    "LOADER_PROBE_CODE",
    "OfficialHarnessPythonLoader",
    "OfficialHarnessPythonLoaderError",
    "build_official_harness_python_loader",
]
