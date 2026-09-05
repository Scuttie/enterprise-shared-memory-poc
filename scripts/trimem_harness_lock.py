"""Cross-platform locks for the pinned official grader harnesses.

Dependency hashes in this module are defined over Git blob bytes at an exact
commit.  A checkout is still required by the official harness, but its line
ending conversion, filters, and other working-tree materialization choices are
never part of the dependency-lock identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
GRADER_LOCK_PATH = ROOT / "configs/trimem_v1/grader_lock.json"
ENVIRONMENT_LOCK_PATH = ROOT / "configs/trimem_v1/benchmark_environment_lock.json"
REHEARSAL_SCHEMA = "trimem/harness-lock-pre-exec-rehearsal/1.0"
REHEARSAL_ENDPOINT = "TRIMEM_HARNESS_LOCK_PRE_EXEC_REHEARSAL_PASS"
REHEARSAL_FAILURE_ENDPOINT = "TRIMEM_HARNESS_LOCK_PRE_EXEC_REHEARSAL_FAIL_CLOSED"
HASH_BASIS = "PINNED_GIT_BLOB_BYTES_AT_REVISION"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHECKOUT_KEY = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
GITHUB_REPOSITORY = re.compile(
    r"^https://github[.]com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:[.]git)?$"
)
REGULAR_BLOB_MODES = {"100644", "100755"}
LEGACY_HASH_FIELDS = {
    "dependency_declaration",
    "dependency_declaration_sha256",
    "upstream_uv_lock_sha256",
}


class HarnessLockError(ValueError):
    """The pinned harness or dependency-blob contract failed closed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _zero_execution_counters() -> dict[str, int]:
    return {
        "docker_image_pulls": 0,
        "grader_containers": 0,
        "input_tokens": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "task_arm_runs": 0,
        "total_usd": 0,
    }


def _strict_json(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise HarnessLockError(f"duplicate JSON key in harness lock: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, HarnessLockError):
            raise
        raise HarnessLockError(f"invalid harness lock JSON: {path}") from exc
    if not isinstance(value, dict):
        raise HarnessLockError(f"harness lock root is not an object: {path}")
    return value


def _run_git(
    repository: Path,
    arguments: Sequence[str],
    *,
    timeout: int = 120,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(repository), *arguments],
            capture_output=True,
            text=False,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessLockError("pinned harness Git command could not complete") from exc
    if completed.returncode != 0:
        raise HarnessLockError("pinned harness Git command failed closed")
    return completed.stdout


def _safe_blob_path(path: str) -> str:
    if not isinstance(path, str) or not path or "\\" in path or ":" in path:
        raise HarnessLockError("pinned Git blob path is not safe POSIX relative syntax")
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        raise HarnessLockError("pinned Git blob path contains a control character")
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or path.startswith("-")
        or candidate.as_posix() != path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise HarnessLockError("pinned Git blob path is not canonical and relative")
    return path


def read_pinned_git_blob(
    repository: Path,
    commit: str,
    path: str,
) -> bytes:
    """Return exact committed blob bytes, independent of the working tree.

    The tree entry must be one exact regular-file blob.  Symlinks, submodules,
    trees, missing paths, abbreviated revisions, and unsafe paths are rejected.
    """

    if not isinstance(repository, Path):
        raise HarnessLockError("pinned Git repository must be a pathlib.Path")
    try:
        repository = repository.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HarnessLockError("pinned Git repository is missing") from exc
    if not repository.is_dir():
        raise HarnessLockError("pinned Git repository is not a directory")
    if not isinstance(commit, str) or HEX40.fullmatch(commit) is None:
        raise HarnessLockError("pinned Git commit must be one full lowercase SHA-1")
    path = _safe_blob_path(path)

    if _run_git(repository, ["cat-file", "-t", commit]).strip() != b"commit":
        raise HarnessLockError("pinned Git revision is not a commit")
    tree_raw = _run_git(
        repository, ["ls-tree", "-z", commit, "--", f":(top,literal){path}"]
    )
    records = [record for record in tree_raw.split(bytes([0])) if record]
    if len(records) != 1 or bytes([9]) not in records[0]:
        raise HarnessLockError("pinned Git path does not resolve to one tree entry")
    metadata, observed_path = records[0].split(bytes([9]), 1)
    fields = metadata.split()
    try:
        decoded_path = observed_path.decode("utf-8")
        mode = fields[0].decode("ascii")
        object_type = fields[1].decode("ascii")
        object_id = fields[2].decode("ascii")
    except (IndexError, UnicodeDecodeError) as exc:
        raise HarnessLockError("pinned Git tree entry is malformed") from exc
    if (
        decoded_path != path
        or mode not in REGULAR_BLOB_MODES
        or object_type != "blob"
        or HEX40.fullmatch(object_id) is None
    ):
        raise HarnessLockError("pinned Git path is not one regular-file blob")
    return _run_git(repository, ["cat-file", "blob", object_id])


def _dependency_rows(environment: Mapping[str, Any]) -> list[dict[str, Any]]:
    if environment.get("harness_dependency_hash_basis") != HASH_BASIS:
        raise HarnessLockError("harness dependency hash basis is not Git blob bytes")
    rows = environment.get("harness_source_environment")
    if not isinstance(rows, list) or not rows:
        raise HarnessLockError("harness source environment rows are missing")
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise HarnessLockError("harness source environment row is not an object")
        legacy = LEGACY_HASH_FIELDS.intersection(row)
        if legacy:
            raise HarnessLockError(
                "working-tree dependency hash fields remain: " + ",".join(sorted(legacy))
            )
        benchmark_ids = row.get("benchmark_ids")
        declarations = row.get("dependency_declarations")
        if (
            not isinstance(benchmark_ids, list)
            or not benchmark_ids
            or any(not isinstance(value, str) or not value for value in benchmark_ids)
            or len(benchmark_ids) != len(set(benchmark_ids))
            or not isinstance(declarations, list)
            or not declarations
        ):
            raise HarnessLockError("harness dependency declaration list is invalid")
        checkout_key = row.get("checkout_key")
        repository = row.get("repository")
        revision = row.get("revision")
        if (
            not isinstance(checkout_key, str)
            or CHECKOUT_KEY.fullmatch(checkout_key) is None
            or not isinstance(repository, str)
            or GITHUB_REPOSITORY.fullmatch(repository) is None
            or not isinstance(revision, str)
            or HEX40.fullmatch(revision) is None
        ):
            raise HarnessLockError("harness source identity is not exact")
        paths: list[str] = []
        for declaration in declarations:
            if not isinstance(declaration, dict) or set(declaration) != {
                "bytes",
                "git_blob_sha256",
                "path",
            }:
                raise HarnessLockError("Git blob dependency declaration shape is invalid")
            dependency_path = _safe_blob_path(declaration.get("path"))
            byte_count = declaration.get("bytes")
            digest = declaration.get("git_blob_sha256")
            if (
                isinstance(byte_count, bool)
                or not isinstance(byte_count, int)
                or byte_count <= 0
                or not isinstance(digest, str)
                or SHA256.fullmatch(digest) is None
            ):
                raise HarnessLockError("Git blob dependency declaration lock is invalid")
            paths.append(dependency_path)
        if len(paths) != len(set(paths)):
            raise HarnessLockError("duplicate Git blob dependency declaration path")
        result.append(row)
    checkout_keys = [str(row["checkout_key"]) for row in result]
    all_benchmark_ids = [
        benchmark_id for row in result for benchmark_id in row["benchmark_ids"]
    ]
    if (
        len(checkout_keys) != len(set(checkout_keys))
        or len(all_benchmark_ids) != len(set(all_benchmark_ids))
    ):
        raise HarnessLockError("harness checkout key or benchmark ID is duplicated")
    return result


def _portable_projection(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    projection = [
        {
            "bytes": declaration["bytes"],
            "git_blob_sha256": declaration["git_blob_sha256"],
            "path": declaration["path"],
            "repository": row["repository"],
            "revision": row["revision"],
        }
        for row in rows
        for declaration in row["dependency_declarations"]
    ]
    return sorted(
        projection,
        key=lambda item: (item["repository"], item["revision"], item["path"]),
    )


def _validate_lock_projection(
    environment: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]
) -> str:
    lock = environment.get("harness_dependency_lock")
    projection = _portable_projection(rows)
    observed = _sha256(_canonical(projection))
    if (
        not isinstance(lock, Mapping)
        or lock.get("basis") != HASH_BASIS
        or lock.get("dependency_count") != len(projection)
        or lock.get("portable_projection_sha256") != observed
    ):
        raise HarnessLockError("harness dependency portable projection mismatch")
    return observed


def validate_dependency_declarations(
    repository: Path,
    commit: str,
    declarations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Validate every configured dependency through ``read_pinned_git_blob``."""

    result: list[dict[str, Any]] = []
    for declaration in declarations:
        path = _safe_blob_path(declaration.get("path"))
        expected_bytes = declaration.get("bytes")
        expected_sha256 = declaration.get("git_blob_sha256")
        raw = read_pinned_git_blob(repository, commit, path)
        observed_sha256 = _sha256(raw)
        if len(raw) != expected_bytes or observed_sha256 != expected_sha256:
            raise HarnessLockError("harness dependency Git blob hash mismatch")
        result.append(
            {
                "bytes": len(raw),
                "git_blob_sha256": observed_sha256,
                "path": path,
            }
        )
    return result


def _normalized_repository_url(value: str) -> str:
    normalized = value.rstrip("/")
    return normalized[:-4] if normalized.endswith(".git") else normalized


def _clone(repository: str, target: Path) -> None:
    try:
        completed = subprocess.run(
            [
                "git",
                "clone",
                "--no-checkout",
                "--filter=blob:none",
                repository,
                str(target),
            ],
            capture_output=True,
            text=False,
            check=False,
            timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessLockError("pinned harness clone could not complete") from exc
    if completed.returncode != 0:
        raise HarnessLockError("pinned harness clone failed closed")


def _load_lock_rows() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grader = _strict_json(GRADER_LOCK_PATH)
    environment = _strict_json(ENVIRONMENT_LOCK_PATH)
    rows = _dependency_rows(environment)
    _validate_lock_projection(environment, rows)
    grader_rows = grader.get("harnesses")
    if not isinstance(grader_rows, list) or len(grader_rows) != len(rows):
        raise HarnessLockError("grader/environment harness row count mismatch")
    grader_by_ids = {
        tuple(row.get("benchmark_ids", ())): row
        for row in grader_rows
        if isinstance(row, Mapping)
    }
    if len(grader_by_ids) != len(grader_rows):
        raise HarnessLockError("grader harness benchmark IDs are duplicated or invalid")
    for row in rows:
        locked = grader_by_ids.get(tuple(row["benchmark_ids"]))
        if (
            not isinstance(locked, Mapping)
            or locked.get("repository") != row["repository"]
            or locked.get("revision") != row["revision"]
        ):
            raise HarnessLockError("harness environment/source revision mismatch")
    return environment, rows


def validate_harness_lock_configuration() -> dict[str, Any]:
    """Validate the complete local cross-file lock without cloning or executing."""

    environment, rows = _load_lock_rows()
    projection_sha256 = _validate_lock_projection(environment, rows)
    return {
        "benchmark_ids": sorted(
            benchmark_id for row in rows for benchmark_id in row["benchmark_ids"]
        ),
        "dependency_count": sum(
            len(row["dependency_declarations"]) for row in rows
        ),
        "hash_basis": HASH_BASIS,
        "portable_projection_sha256": projection_sha256,
    }


def _prepare_harness_sources(
    root: Path, *, materialize_worktrees: bool
) -> dict[str, Path]:
    if not isinstance(root, Path):
        raise HarnessLockError("harness checkout root must be a pathlib.Path")
    environment, rows = _load_lock_rows()
    del environment
    root.mkdir(parents=True, exist_ok=True)
    result: dict[str, Path] = {}
    for row in rows:
        target = root / row["checkout_key"]
        existed = target.exists()
        if not existed:
            _clone(row["repository"], target)
        origin = _run_git(target, ["remote", "get-url", "origin"]).decode("utf-8").strip()
        if _normalized_repository_url(origin) != _normalized_repository_url(row["repository"]):
            raise HarnessLockError("official harness checkout origin mismatch")
        if materialize_worktrees and not existed:
            _run_git(target, ["checkout", "--detach", row["revision"]], timeout=900)
        if materialize_worktrees:
            head = _run_git(target, ["rev-parse", "HEAD"]).decode("ascii").strip()
            status = _run_git(target, ["status", "--porcelain=v1"])
            if head != row["revision"] or status:
                raise HarnessLockError("official harness checkout is not exact and clean")
        validate_dependency_declarations(
            target, row["revision"], row["dependency_declarations"]
        )
        for benchmark_id in row["benchmark_ids"]:
            result[benchmark_id] = target
    return result


def prepare_harnesses(root: Path) -> dict[str, Path]:
    """Run the exact production clone, checkout, and Git-blob validation path."""

    return _prepare_harness_sources(root, materialize_worktrees=True)


def prepare_harness_blob_sources(root: Path) -> dict[str, Path]:
    """Validate portable object locks without materializing a case-sensitive tree."""

    return _prepare_harness_sources(root, materialize_worktrees=False)


def build_rehearsal(
    checkout_root: Path, *, materialize_worktrees: bool = True
) -> dict[str, Any]:
    """Exercise the selected full-production or object-only boundary, then stop."""

    if checkout_root.exists():
        raise HarnessLockError("exact rehearsal checkout root must be fresh")
    environment, rows = _load_lock_rows()
    harnesses = (
        prepare_harnesses(checkout_root)
        if materialize_worktrees
        else prepare_harness_blob_sources(checkout_root)
    )
    dependencies: list[dict[str, Any]] = []
    harness_rows: list[dict[str, Any]] = []
    for row in rows:
        repository_paths = {
            harnesses[benchmark_id] for benchmark_id in row["benchmark_ids"]
        }
        if len(repository_paths) != 1:
            raise HarnessLockError("rehearsal harness row does not share one repository")
        repository = repository_paths.pop()
        core_autocrlf = _run_git(repository, ["config", "--get", "core.autocrlf"])
        harness_row: dict[str, Any] = {
            "benchmark_ids": list(row["benchmark_ids"]),
            "checkout_key": row["checkout_key"],
            "core_autocrlf": core_autocrlf.decode("utf-8").strip(),
            "pinned_commit": row["revision"],
            "repository": row["repository"],
            "working_tree_materialized": materialize_worktrees,
        }
        if materialize_worktrees:
            head = _run_git(repository, ["rev-parse", "HEAD"]).decode("ascii").strip()
            status = _run_git(repository, ["status", "--porcelain=v1"])
            if head != row["revision"] or status:
                raise HarnessLockError(
                    "rehearsal full harness checkout is not exact and clean"
                )
            harness_row.update({"clean": status == b"", "head": head})
        harness_rows.append(harness_row)
        for declaration in row["dependency_declarations"]:
            blob = read_pinned_git_blob(repository, row["revision"], declaration["path"])
            if (
                len(blob) != declaration["bytes"]
                or _sha256(blob) != declaration["git_blob_sha256"]
            ):
                raise HarnessLockError(
                    "rehearsal evidence blob differs from its validated lock"
                )
            dependency: dict[str, Any] = {
                "benchmark_ids": list(row["benchmark_ids"]),
                "bytes": len(blob),
                "git_blob_sha256": _sha256(blob),
                "path": declaration["path"],
                "repository": row["repository"],
                "revision": row["revision"],
            }
            if materialize_worktrees:
                working_path = repository.joinpath(
                    *PurePosixPath(declaration["path"]).parts
                )
                working = working_path.read_bytes()
                dependency.update(
                    {
                        "working_tree_bytes_observation": len(working),
                        "working_tree_equals_git_blob": working == blob,
                        "working_tree_sha256_observation": _sha256(working),
                    }
                )
            dependencies.append(dependency)
    expected_benchmarks = sorted(
        benchmark_id for row in rows for benchmark_id in row["benchmark_ids"]
    )
    if sorted(harnesses) != expected_benchmarks:
        raise HarnessLockError("rehearsal benchmark coverage mismatch")
    projection_sha256 = _validate_lock_projection(environment, rows)
    payload: dict[str, Any] = {
        "canonical_lock_projection_sha256": projection_sha256,
        "dependency_count": len(dependencies),
        "dependencies": sorted(
            dependencies,
            key=lambda item: (item["repository"], item["revision"], item["path"]),
        ),
        "endpoint": REHEARSAL_ENDPOINT,
        "execution_counters": _zero_execution_counters(),
        "harnesses": sorted(harness_rows, key=lambda item: item["checkout_key"]),
        "hash_basis": HASH_BASIS,
        "official_grader_viability": "NOT_YET_ESTABLISHED",
        "platform": {
            "architecture": platform.machine().lower(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "system": platform.system().lower(),
        },
        "rehearsal_boundary": (
            "EXACT_PRODUCTION_PREPARE_HARNESSES"
            if materialize_worktrees
            else "CROSS_PLATFORM_GIT_BLOB_LOCK_ONLY"
        ),
        "schema": REHEARSAL_SCHEMA,
        "status": "PASS",
    }
    payload["rehearsal_sha256"] = _sha256(_canonical(payload))
    return payload


def _write_exclusive_json(output: Path, value: Mapping[str, Any]) -> None:
    raw = _canonical(value) + bytes([10])
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise HarnessLockError("refusing to overwrite harness rehearsal report") from exc


def write_rehearsal(
    checkout_root: Path,
    output: Path,
    *,
    materialize_worktrees: bool = True,
) -> dict[str, Any]:
    value = build_rehearsal(
        checkout_root, materialize_worktrees=materialize_worktrees
    )
    _write_exclusive_json(output, value)
    return value


def failure_rehearsal(
    error: BaseException, *, materialize_worktrees: bool
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "endpoint": REHEARSAL_FAILURE_ENDPOINT,
        "error": {
            "message": str(error),
            "type": type(error).__name__,
        },
        "execution_counters": _zero_execution_counters(),
        "official_grader_viability": "NOT_YET_ESTABLISHED",
        "platform": {
            "architecture": platform.machine().lower(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "system": platform.system().lower(),
        },
        "rehearsal_boundary": (
            "EXACT_PRODUCTION_PREPARE_HARNESSES"
            if materialize_worktrees
            else "CROSS_PLATFORM_GIT_BLOB_LOCK_ONLY"
        ),
        "schema": REHEARSAL_SCHEMA,
        "status": "FAIL_CLOSED",
    }
    value["rehearsal_sha256"] = _sha256(_canonical(value))
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--blob-only",
        action="store_true",
        help="validate object locks without a full working tree (Windows portability row)",
    )
    args = parser.parse_args()
    materialize_worktrees = not args.blob_only
    try:
        value = write_rehearsal(
            args.checkout_root.resolve(),
            args.output.resolve(),
            materialize_worktrees=materialize_worktrees,
        )
    except (OSError, HarnessLockError) as exc:
        failure = failure_rehearsal(
            exc, materialize_worktrees=materialize_worktrees
        )
        try:
            _write_exclusive_json(args.output.resolve(), failure)
        except (OSError, HarnessLockError) as report_exc:
            failure["report_write_error"] = {
                "message": str(report_exc),
                "type": type(report_exc).__name__,
            }
            failure.pop("rehearsal_sha256", None)
            failure["rehearsal_sha256"] = _sha256(_canonical(failure))
        print(json.dumps(failure, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "canonical_lock_projection_sha256": value[
                    "canonical_lock_projection_sha256"
                ],
                "dependency_count": value["dependency_count"],
                "endpoint": value["endpoint"],
                "rehearsal_sha256": value["rehearsal_sha256"],
                "status": value["status"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
