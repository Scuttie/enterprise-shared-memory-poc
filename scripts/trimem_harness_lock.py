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
import stat
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
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "LANG": "C",
    }
    try:
        completed = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-C",
                str(repository),
                *arguments,
            ],
            capture_output=True,
            text=False,
            check=False,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessLockError("pinned harness Git command could not complete") from exc
    if completed.returncode != 0:
        raise HarnessLockError("pinned harness Git command failed closed")
    return completed.stdout


def _is_link_or_reparse(path: Path) -> bool:
    """Recognize POSIX links and Windows junction/reparse-point escapes."""

    try:
        value = os.lstat(path)
    except OSError:
        return path.is_symlink()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(value, "st_file_attributes", 0)
    return stat.S_ISLNK(value.st_mode) or bool(reparse_flag & attributes)


def validate_lexical_directory_chain(path: Path, *, label: str) -> Path:
    """Return an absolute lexical path after rejecting existing link ancestors."""

    try:
        absolute = path.absolute()
    except (OSError, RuntimeError) as exc:
        raise HarnessLockError(f"{label} path could not be made absolute") from exc
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        try:
            status = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise HarnessLockError(f"{label} ancestor could not be inspected") from exc
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        attributes = getattr(status, "st_file_attributes", 0)
        if stat.S_ISLNK(status.st_mode) or bool(reparse_flag & attributes):
            raise HarnessLockError(f"{label} path contains a link or reparse point")
        if not stat.S_ISDIR(status.st_mode):
            raise HarnessLockError(f"{label} path contains a non-directory ancestor")
    return absolute


def validate_pristine_checkout(repository: Path, commit: str) -> None:
    """Compare one lexical harness work tree with an immutable Git tree.

    Git supplies only content-addressed object identities.  The mutable index,
    ignore files, local ``core.worktree``, filters and fsmonitor are never used
    to decide whether the executable harness bytes are pristine.
    """

    if not isinstance(repository, Path) or not repository.is_absolute():
        raise HarnessLockError("harness checkout must be an absolute pathlib.Path")
    if HEX40.fullmatch(commit) is None:
        raise HarnessLockError("harness checkout revision is malformed")
    repository = validate_lexical_directory_chain(
        repository, label="harness checkout"
    )
    if _is_link_or_reparse(repository) or not repository.is_dir():
        raise HarnessLockError("harness checkout is not a regular directory")
    git_dir = repository / ".git"
    if _is_link_or_reparse(git_dir) or not git_dir.is_dir():
        raise HarnessLockError("harness Git metadata is not local")

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LC_ALL": "C",
        "LANG": "C",
    }

    try:
        config = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                f"--git-dir={git_dir}",
                "config",
                "--local",
                "--no-includes",
                "--null",
                "--name-only",
                "--list",
            ],
            cwd=repository,
            capture_output=True,
            text=False,
            check=False,
            timeout=120,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HarnessLockError(
            "harness local Git configuration could not be inspected"
        ) from exc
    if config.returncode != 0:
        raise HarnessLockError(
            "harness local Git configuration could not be inspected"
        )
    try:
        config_keys = [
            value.decode("utf-8", errors="strict").lower()
            for value in config.stdout.split(b"\0")
            if value
        ]
    except UnicodeDecodeError as exc:
        raise HarnessLockError("harness local Git configuration is not UTF-8") from exc
    forbidden_config = {
        "core.attributesfile",
        "core.fsmonitor",
        "core.hookspath",
        "core.pager",
        "core.worktree",
        "interactive.difffilter",
    }
    if any(
        key in forbidden_config
        or key.startswith("filter.")
        or key.startswith("include.")
        or key.startswith("includeif.")
        or (
            key.startswith("diff.")
            and (key.endswith(".command") or key.endswith(".textconv"))
        )
        for key in config_keys
    ):
        raise HarnessLockError("harness local Git configuration is unsafe")

    def git_object_query(*arguments: str) -> bytes:
        try:
            completed = subprocess.run(
                [
                    "git",
                    "--no-replace-objects",
                    f"--git-dir={git_dir}",
                    f"--work-tree={repository}",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    f"core.hooksPath={os.devnull}",
                    *arguments,
                ],
                capture_output=True,
                text=False,
                check=False,
                timeout=120,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HarnessLockError(
                "harness Git object query could not complete"
            ) from exc
        if completed.returncode != 0:
            raise HarnessLockError("harness Git object query failed closed")
        return completed.stdout

    if git_object_query("rev-parse", "--verify", "HEAD").strip() != commit.encode(
        "ascii"
    ):
        raise HarnessLockError("harness checkout HEAD differs")
    raw_tree = git_object_query("ls-tree", "-rz", "--full-tree", commit)
    blobs: dict[str, tuple[str, str]] = {}
    gitlinks: set[str] = set()
    for raw_entry in raw_tree.split(b"\0"):
        if not raw_entry:
            continue
        try:
            header, raw_path = raw_entry.split(b"\t", 1)
            mode, kind, object_id = header.decode("ascii").split(" ")
            relative = raw_path.decode("utf-8", errors="strict")
        except (UnicodeDecodeError, ValueError) as exc:
            raise HarnessLockError("harness Git tree is malformed") from exc
        parts = relative.split("/")
        if (
            not relative
            or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or (os.name == "nt" and "\\" in relative)
            or HEX40.fullmatch(object_id) is None
        ):
            raise HarnessLockError("harness Git tree path is unsafe")
        if kind == "blob" and mode in {"100644", "100755", "120000"}:
            blobs[relative] = (mode, object_id)
        elif kind == "commit" and mode == "160000":
            gitlinks.add(relative)
        else:
            raise HarnessLockError("harness Git tree entry is unsupported")
    if len(blobs) + len(gitlinks) != len(set(blobs) | gitlinks):
        raise HarnessLockError("harness Git tree paths collide")

    expected_leaf_paths = set(blobs)
    allowed_directories: set[str] = set()
    required_directories: set[str] = set()
    for relative in (*blobs, *gitlinks):
        parts = relative.split("/")
        parents = ["/".join(parts[:index]) for index in range(1, len(parts))]
        allowed_directories.update(parents)
        if relative in blobs:
            required_directories.update(parents)
    allowed_directories.update(gitlinks)

    for relative, (mode, object_id) in blobs.items():
        candidate = repository.joinpath(*relative.split("/"))
        current = repository
        for part in relative.split("/")[:-1]:
            current = current / part
            if _is_link_or_reparse(current) or not current.is_dir():
                raise HarnessLockError("harness tracked parent is unsafe")
        if mode == "120000":
            if candidate.is_symlink():
                target = os.readlink(candidate)
                raw = target if isinstance(target, bytes) else os.fsencode(target)
            elif os.name == "nt" and not _is_link_or_reparse(
                candidate
            ) and candidate.is_file():
                # Git for Windows materializes symlink blobs as regular files
                # when core.symlinks=false.  The blob bytes remain authoritative.
                raw = candidate.read_bytes()
            else:
                raise HarnessLockError("harness tracked symlink differs")
        else:
            if _is_link_or_reparse(candidate) or not candidate.is_file():
                raise HarnessLockError("harness tracked file is absent")
            raw = candidate.read_bytes()
            if os.name != "nt" and bool(candidate.stat().st_mode & stat.S_IXUSR) != (
                mode == "100755"
            ):
                raise HarnessLockError("harness executable mode differs")
        header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
        if hashlib.sha1(header + raw).hexdigest() != object_id:
            raise HarnessLockError("harness differs from its frozen Git blob")

    for relative in gitlinks:
        candidate = repository.joinpath(*relative.split("/"))
        if candidate.exists() or candidate.is_symlink():
            if (
                _is_link_or_reparse(candidate)
                or not candidate.is_dir()
                or any(candidate.iterdir())
            ):
                raise HarnessLockError("harness gitlink is not pristine")

    observed_leaf_paths: set[str] = set()
    observed_directories: set[str] = set()
    for current_root, directory_names, file_names in os.walk(
        repository,
        topdown=True,
        followlinks=False,
    ):
        current = Path(current_root)
        if current == repository and ".git" in directory_names:
            directory_names.remove(".git")
        for name in list(directory_names):
            path = current / name
            relative = path.relative_to(repository).as_posix()
            if _is_link_or_reparse(path):
                directory_names.remove(name)
                observed_leaf_paths.add(relative)
            else:
                observed_directories.add(relative)
        for name in file_names:
            observed_leaf_paths.add(
                (current / name).relative_to(repository).as_posix()
            )
    if (
        observed_leaf_paths != expected_leaf_paths
        or not required_directories <= observed_directories
        or not observed_directories <= allowed_directories
    ):
        raise HarnessLockError("harness inventory differs from its frozen Git tree")


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
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        "LANG": "C",
    }
    try:
        completed = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
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
            env=environment,
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
    root: Path,
    *,
    materialize_worktrees: bool,
    checkout_core_autocrlf: str = "input",
) -> dict[str, Path]:
    if not isinstance(root, Path):
        raise HarnessLockError("harness checkout root must be a pathlib.Path")
    if checkout_core_autocrlf not in {"false", "input", "true"}:
        raise HarnessLockError("checkout core.autocrlf value is invalid")
    environment, rows = _load_lock_rows()
    del environment
    root = validate_lexical_directory_chain(root, label="harness checkout root")
    root.mkdir(parents=True, exist_ok=True)
    root = validate_lexical_directory_chain(root, label="harness checkout root")
    if not root.is_dir():
        raise HarnessLockError("harness checkout root is not a regular directory")
    result: dict[str, Path] = {}
    for row in rows:
        target = root / row["checkout_key"]
        existed = target.exists()
        if existed:
            target = validate_lexical_directory_chain(
                target, label="harness checkout"
            )
            if not target.is_dir():
                raise HarnessLockError("harness checkout is not a regular directory")
            git_dir = target / ".git"
            if _is_link_or_reparse(git_dir) or not git_dir.is_dir():
                raise HarnessLockError("harness Git metadata is not local")
        if not existed:
            _clone(row["repository"], target)
        if existed:
            observed_autocrlf = _run_git(
                target, ["config", "--get", "core.autocrlf"]
            ).decode("utf-8").strip()
            if observed_autocrlf != checkout_core_autocrlf:
                raise HarnessLockError(
                    "existing harness core.autocrlf differs from rehearsal"
                )
        else:
            _run_git(
                target,
                [
                    "config",
                    "--local",
                    "core.autocrlf",
                    checkout_core_autocrlf,
                ],
            )
        if materialize_worktrees and not existed:
            _run_git(target, ["checkout", "--detach", row["revision"]], timeout=900)
        if materialize_worktrees:
            validate_pristine_checkout(target.absolute(), row["revision"])
        origin = _run_git(target, ["remote", "get-url", "origin"]).decode("utf-8").strip()
        if _normalized_repository_url(origin) != _normalized_repository_url(row["repository"]):
            raise HarnessLockError("official harness checkout origin mismatch")
        validate_dependency_declarations(
            target, row["revision"], row["dependency_declarations"]
        )
        for benchmark_id in row["benchmark_ids"]:
            result[benchmark_id] = target
    return result


def prepare_harnesses(
    root: Path, *, checkout_core_autocrlf: str = "input"
) -> dict[str, Path]:
    """Run the exact production clone, checkout, and Git-blob validation path."""

    return _prepare_harness_sources(
        root,
        materialize_worktrees=True,
        checkout_core_autocrlf=checkout_core_autocrlf,
    )


def prepare_harness_blob_sources(
    root: Path, *, checkout_core_autocrlf: str = "input"
) -> dict[str, Path]:
    """Validate portable object locks without materializing a case-sensitive tree."""

    return _prepare_harness_sources(
        root,
        materialize_worktrees=False,
        checkout_core_autocrlf=checkout_core_autocrlf,
    )


def build_rehearsal(
    checkout_root: Path,
    *,
    materialize_worktrees: bool = True,
    checkout_core_autocrlf: str = "input",
) -> dict[str, Any]:
    """Exercise the selected full-production or object-only boundary, then stop."""

    if checkout_root.exists():
        raise HarnessLockError("exact rehearsal checkout root must be fresh")
    environment, rows = _load_lock_rows()
    harnesses = (
        prepare_harnesses(
            checkout_root,
            checkout_core_autocrlf=checkout_core_autocrlf,
        )
        if materialize_worktrees
        else prepare_harness_blob_sources(
            checkout_root,
            checkout_core_autocrlf=checkout_core_autocrlf,
        )
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
        observed_core_autocrlf = core_autocrlf.decode("utf-8").strip()
        if observed_core_autocrlf != checkout_core_autocrlf:
            raise HarnessLockError("rehearsal core.autocrlf identity differs")
        harness_row: dict[str, Any] = {
            "benchmark_ids": list(row["benchmark_ids"]),
            "checkout_key": row["checkout_key"],
            "core_autocrlf": observed_core_autocrlf,
            "pinned_commit": row["revision"],
            "repository": row["repository"],
            "working_tree_materialized": materialize_worktrees,
        }
        if materialize_worktrees:
            validate_pristine_checkout(
                repository.absolute(), row["revision"]
            )
            harness_row.update({"clean": True, "head": row["revision"]})
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
        "harness_dependency_lock_status": "ESTABLISHED",
        "official_grader_execution_status": "NOT_PERFORMED_CREDENTIAL_FREE_REHEARSAL",
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
    checkout_core_autocrlf: str = "input",
) -> dict[str, Any]:
    value = build_rehearsal(
        checkout_root,
        materialize_worktrees=materialize_worktrees,
        checkout_core_autocrlf=checkout_core_autocrlf,
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
        "harness_dependency_lock_status": "NOT_ESTABLISHED",
        "official_grader_execution_status": "NOT_PERFORMED_CREDENTIAL_FREE_REHEARSAL",
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
    parser.add_argument(
        "--checkout-core-autocrlf",
        choices=("false", "input", "true"),
        required=True,
        help="explicit trusted checkout conversion mode for this rehearsal row",
    )
    args = parser.parse_args()
    materialize_worktrees = not args.blob_only
    try:
        value = write_rehearsal(
            args.checkout_root.resolve(),
            args.output.resolve(),
            materialize_worktrees=materialize_worktrees,
            checkout_core_autocrlf=args.checkout_core_autocrlf,
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
