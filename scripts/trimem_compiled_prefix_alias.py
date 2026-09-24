"""Read-only, fail-closed validation of the frozen CPython prefix alias.

The ``actions/setup-python`` CPython archive records ``/opt/hostedtoolcache``
as its compiled installation root.  The private runner stores the identical
tool cache below ``/opt/trimem-runner-cache/work-ci/_tool``.  A single
root-owned host alias makes the compiled path resolve to those same bytes.

This module never creates or repairs the alias.  It only proves the exact
single-hop relationship and the Python/libpython identities before a
credential-bearing job can be considered ready.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Sequence


EVIDENCE_SCHEMA = "trimem/compiled-prefix-alias/1.0"
FROZEN_ALIAS_PATH = "/opt/hostedtoolcache"
FROZEN_EXPECTED_TARGET = "/opt/trimem-runner-cache/work-ci/_tool"
FROZEN_PYTHON_PREFIX_RELATIVE = "Python/3.11.10/x64"
FROZEN_PYTHON_BINARY_RELATIVE = "bin/python3.11"
FROZEN_LIBPYTHON_RELATIVE = "lib/libpython3.11.so.1.0"
FROZEN_PYTHON_SHA256 = (
    "930be806841bf98ef6898a7d8c69b0083b68c803c5fcd7a77becefaf84bc25c9"
)
FROZEN_LIBPYTHON_SHA256 = (
    "f102768d427dd8441feed6e4b5cd950077d17e097b95fc3dcc59bd99838ac97d"
)
SHA256 = re.compile(r"[0-9a-f]{64}")


class CompiledPrefixAliasError(RuntimeError):
    """The frozen compiled-prefix alias is absent or differs."""


def _canonical_absolute_path(value: str | Path, *, label: str) -> Path:
    raw = os.fspath(value)
    if not raw or "\x00" in raw or os.pathsep in raw:
        raise CompiledPrefixAliasError(f"{label} is empty or malformed")
    path = Path(raw)
    if not path.is_absolute() or os.path.normpath(raw) != raw:
        raise CompiledPrefixAliasError(f"{label} is not a canonical absolute path")
    return path


def _canonical_relative_path(value: str | Path, *, label: str) -> Path:
    raw = os.fspath(value)
    if not raw or "\x00" in raw or os.pathsep in raw:
        raise CompiledPrefixAliasError(f"{label} is empty or malformed")
    path = Path(raw)
    if (
        path.is_absolute()
        or os.path.normpath(raw) != raw
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise CompiledPrefixAliasError(f"{label} is not a canonical relative path")
    return path


def _validated_sha256(value: str, *, label: str) -> str:
    if SHA256.fullmatch(value) is None:
        raise CompiledPrefixAliasError(f"{label} is not a lowercase SHA-256")
    return value


def _path_lstat(path: Path) -> os.stat_result:
    """Small seam used by tests to model root-owned host metadata."""

    return path.lstat()


def _mode_text(metadata: os.stat_result) -> str:
    return f"{stat.S_IMODE(metadata.st_mode):04o}"


def _directory_chain(path: Path) -> list[Path]:
    if not path.is_absolute():  # defensive; all callers validate first.
        raise CompiledPrefixAliasError("directory chain root is not absolute")
    chain = [Path(path.anchor)]
    current = chain[0]
    for part in path.parts[1:]:
        current = current / part
        chain.append(current)
    return chain


def _secure_directory(
    path: Path,
    *,
    require_root_owner: bool,
) -> dict[str, Any]:
    try:
        metadata = _path_lstat(path)
    except OSError as exc:
        raise CompiledPrefixAliasError(
            f"trusted directory component does not exist: {path}"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise CompiledPrefixAliasError(
            f"trusted directory component is an indirect symlink: {path}"
        )
    if not stat.S_ISDIR(metadata.st_mode):
        raise CompiledPrefixAliasError(
            f"trusted directory component is not a directory: {path}"
        )
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise CompiledPrefixAliasError(
            f"trusted directory component is group/world writable: {path}"
        )
    if require_root_owner and metadata.st_uid != 0:
        raise CompiledPrefixAliasError(
            f"compiled-prefix alias parent is not root-owned: {path}"
        )
    return {"mode": f"{mode:04o}", "path": str(path), "uid": metadata.st_uid}


def _secure_regular_file(
    path: Path,
    *,
    executable: bool,
) -> tuple[Path, os.stat_result]:
    try:
        metadata = _path_lstat(path)
    except OSError as exc:
        raise CompiledPrefixAliasError(f"frozen file does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CompiledPrefixAliasError(
            f"frozen file is not a direct regular file: {path}"
        )
    mode = stat.S_IMODE(metadata.st_mode)
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise CompiledPrefixAliasError(f"frozen file is group/world writable: {path}")
    if executable and not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
        raise CompiledPrefixAliasError(
            f"frozen Python binary is not executable: {path}"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:  # defensive; lstat already proved a direct file.
        raise CompiledPrefixAliasError(f"frozen file does not resolve: {path}") from exc
    if resolved != path:
        raise CompiledPrefixAliasError(f"frozen file resolved through an alias: {path}")
    return resolved, metadata


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
    except OSError as exc:
        raise CompiledPrefixAliasError(f"frozen file cannot be hashed: {path}") from exc
    return digest.hexdigest(), size


def validate_compiled_prefix_alias(
    *,
    alias_path: str | Path = FROZEN_ALIAS_PATH,
    expected_target: str | Path = FROZEN_EXPECTED_TARGET,
    python_prefix_relative: str | Path = FROZEN_PYTHON_PREFIX_RELATIVE,
    python_binary_relative: str | Path = FROZEN_PYTHON_BINARY_RELATIVE,
    libpython_relative: str | Path = FROZEN_LIBPYTHON_RELATIVE,
    expected_python_sha256: str = FROZEN_PYTHON_SHA256,
    expected_libpython_sha256: str = FROZEN_LIBPYTHON_SHA256,
) -> dict[str, Any]:
    """Return canonical non-secret evidence for the exact host alias.

    Validation is POSIX-only and read-only.  The alias must itself be a
    root-owned symbolic link whose raw target is the exact expected absolute
    path.  No other component in the target or installation paths may be a
    symlink or group/world writable.
    """

    if os.name != "posix":
        raise CompiledPrefixAliasError(
            "compiled-prefix alias validation requires POSIX"
        )
    alias = _canonical_absolute_path(alias_path, label="alias path")
    target = _canonical_absolute_path(expected_target, label="expected target")
    prefix_relative = _canonical_relative_path(
        python_prefix_relative, label="Python prefix relative path"
    )
    python_relative = _canonical_relative_path(
        python_binary_relative, label="Python binary relative path"
    )
    libpython_relative_path = _canonical_relative_path(
        libpython_relative, label="libpython relative path"
    )
    python_expected_hash = _validated_sha256(
        expected_python_sha256, label="expected Python hash"
    )
    libpython_expected_hash = _validated_sha256(
        expected_libpython_sha256, label="expected libpython hash"
    )
    try:
        target.relative_to(alias.parent)
    except ValueError as exc:
        raise CompiledPrefixAliasError(
            "expected target is outside the root-owned alias parent"
        ) from exc

    directory_rows: dict[str, dict[str, Any]] = {}
    for component in _directory_chain(alias.parent):
        directory_rows[str(component)] = _secure_directory(
            component, require_root_owner=True
        )

    try:
        alias_metadata = _path_lstat(alias)
    except OSError as exc:
        raise CompiledPrefixAliasError("compiled-prefix alias does not exist") from exc
    if not stat.S_ISLNK(alias_metadata.st_mode):
        raise CompiledPrefixAliasError("compiled-prefix alias is not a symbolic link")
    if alias_metadata.st_uid != 0:
        raise CompiledPrefixAliasError("compiled-prefix alias is not root-owned")
    try:
        observed_target = os.readlink(alias)
    except OSError as exc:
        raise CompiledPrefixAliasError(
            "compiled-prefix alias target cannot be read"
        ) from exc
    if observed_target != str(target):
        raise CompiledPrefixAliasError("compiled-prefix alias lexical target differs")

    prefix = target / prefix_relative
    libdir = prefix / libpython_relative_path.parent
    python_path = prefix / python_relative
    libpython_path = prefix / libpython_relative_path
    for directory in (target, prefix, libdir, python_path.parent):
        for component in _directory_chain(directory):
            if str(component) not in directory_rows:
                directory_rows[str(component)] = _secure_directory(
                    component, require_root_owner=False
                )

    try:
        resolved_target = alias.resolve(strict=True)
    except OSError as exc:
        raise CompiledPrefixAliasError(
            "compiled-prefix alias target does not resolve"
        ) from exc
    if resolved_target != target:
        raise CompiledPrefixAliasError("compiled-prefix alias resolved target differs")

    python_realpath, python_metadata = _secure_regular_file(
        python_path, executable=True
    )
    libpython_realpath, libpython_metadata = _secure_regular_file(
        libpython_path, executable=False
    )
    compiled_python = alias / prefix_relative / python_relative
    compiled_libpython = alias / prefix_relative / libpython_relative_path
    try:
        if compiled_python.resolve(strict=True) != python_realpath:
            raise CompiledPrefixAliasError("compiled-prefix Python identity differs")
        if compiled_libpython.resolve(strict=True) != libpython_realpath:
            raise CompiledPrefixAliasError("compiled-prefix libpython identity differs")
    except OSError as exc:
        raise CompiledPrefixAliasError(
            "compiled-prefix file identity does not resolve"
        ) from exc

    python_hash, python_bytes = _sha256_file(python_realpath)
    libpython_hash, libpython_bytes = _sha256_file(libpython_realpath)
    if python_hash != python_expected_hash:
        raise CompiledPrefixAliasError("frozen Python hash differs")
    if libpython_hash != libpython_expected_hash:
        raise CompiledPrefixAliasError("frozen libpython hash differs")

    return {
        "alias_path": str(alias),
        "alias_uid": alias_metadata.st_uid,
        "compiled_libpython_path": str(compiled_libpython),
        "compiled_python_path": str(compiled_python),
        "expected_lexical_target": str(target),
        "libdir_mode": directory_rows[str(libdir)]["mode"],
        "libpython_bytes": libpython_bytes,
        "libpython_mode": _mode_text(libpython_metadata),
        "libpython_realpath": str(libpython_realpath),
        "libpython_sha256": libpython_hash,
        "observed_lexical_target": observed_target,
        "python_binary_bytes": python_bytes,
        "python_binary_mode": _mode_text(python_metadata),
        "python_binary_realpath": str(python_realpath),
        "python_binary_sha256": python_hash,
        "resolved_libdir": str(libdir),
        "resolved_prefix": str(prefix),
        "resolved_target": str(resolved_target),
        "schema": EVIDENCE_SCHEMA,
        "secure_directories": [directory_rows[key] for key in sorted(directory_rows)],
        "status": "PASS",
    }


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the frozen root-owned compiled-prefix alias"
    )
    parser.add_argument("--check", action="store_true", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        evidence = validate_compiled_prefix_alias()
    except (CompiledPrefixAliasError, OSError) as exc:
        failure = {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "schema": EVIDENCE_SCHEMA,
            "status": "NOT_READY",
        }
        sys.stderr.buffer.write(canonical_bytes(failure) + b"\n")
        return 1
    sys.stdout.buffer.write(canonical_bytes(evidence) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CompiledPrefixAliasError",
    "EVIDENCE_SCHEMA",
    "FROZEN_ALIAS_PATH",
    "FROZEN_EXPECTED_TARGET",
    "FROZEN_LIBPYTHON_RELATIVE",
    "FROZEN_LIBPYTHON_SHA256",
    "FROZEN_PYTHON_BINARY_RELATIVE",
    "FROZEN_PYTHON_PREFIX_RELATIVE",
    "FROZEN_PYTHON_SHA256",
    "canonical_bytes",
    "main",
    "validate_compiled_prefix_alias",
]
