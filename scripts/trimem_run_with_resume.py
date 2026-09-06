"""Run one approved phase and resume only an explicitly safe durable suffix."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence
import uuid


ROOT = Path(__file__).resolve().parents[1]
PROCESS_DISPOSITIONS = frozenset(
    {
        "SUCCESS",
        "RESUME_SAFE_DURABLE_SUFFIX",
        "RESUME_SAFE_CELL_COMMIT_JOURNAL",
        "GLOBAL_ENVIRONMENT_FAILURE",
        "GLOBAL_CREDENTIAL_FAILURE",
        "GLOBAL_MODEL_IDENTITY_FAILURE",
        "GLOBAL_LEDGER_INTEGRITY_FAILURE",
        "GLOBAL_GRADER_INFRA_FAILURE",
        "GLOBAL_EVIDENCE_FAILURE",
        "UNKNOWN_FAILURE",
    }
)
RESUME_SAFE_DISPOSITIONS = frozenset(
    {"RESUME_SAFE_DURABLE_SUFFIX", "RESUME_SAFE_CELL_COMMIT_JOURNAL"}
)
_PRODUCTION_TASK_STREAM_FIELDS = frozenset(
    {
        "schema",
        "namespace",
        "experiment_id",
        "split",
        "arm_id",
        "task_order_hash",
        "config_hash",
        "run_nonce",
        "next_sequence_index",
        "task_cursor",
        "stream_state",
        "canonical_evidence",
        "qdrant_evidence",
        "lifecycle_receipt_evidence",
        "completed_task_digests",
        "lifecycle_state",
    }
)
_PREPARED_TASK_FIELDS = frozenset(
    {
        "schema",
        "namespace",
        "experiment_id",
        "split",
        "arm_id",
        "task_order_hash",
        "config_hash",
        "run_nonce",
        "sequence_index",
        "task_id",
        "canonical_evidence",
        "qdrant_evidence",
        "lifecycle_receipt_evidence",
        "lifecycle_state",
    }
)


def _is_link_or_reparse(path: Path) -> bool:
    """Recognize POSIX links and Windows junction/reparse-point escapes."""

    try:
        value = os.lstat(path)
    except OSError:
        return path.is_symlink()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    attributes = getattr(value, "st_file_attributes", 0)
    return stat.S_ISLNK(value.st_mode) or bool(reparse_flag & attributes)


def _secure_existing_path(
    root: Path,
    path: Path,
    *,
    directory: bool,
    label: str,
) -> Path:
    """Return one non-link path that is lexically and physically under root."""

    lexical_root = root.absolute()
    lexical_path = path.absolute()
    if _is_link_or_reparse(lexical_root) or not lexical_root.is_dir():
        raise ValueError(f"{label} root is not a regular directory")
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes its authority root") from exc
    current = lexical_root
    for part in relative.parts:
        current = current / part
        if _is_link_or_reparse(current):
            raise ValueError(f"{label} contains a symbolic link or reparse point")
    try:
        resolved_root = lexical_root.resolve(strict=True)
        resolved = lexical_path.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} is unavailable or escapes its authority root") from exc
    if directory:
        if not resolved.is_dir():
            raise ValueError(f"{label} is not a regular directory")
    elif not resolved.is_file():
        raise ValueError(f"{label} is not a regular file")
    return resolved


def _secure_optional_path(
    root: Path,
    path: Path,
    *,
    directory: bool,
    label: str,
) -> Path | None:
    """Validate an optional path, rejecting dangling links as present attacks."""

    if path.is_symlink():
        raise ValueError(f"{label} is a symbolic link")
    if not path.exists():
        return None
    return _secure_existing_path(root, path, directory=directory, label=label)


def _write(path: Path, raw: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _disposition(stdout: bytes, exit_code: int) -> str:
    """Validate only the final non-empty benchmark-runner stdout line."""

    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return "UNKNOWN_FAILURE"
    try:
        value = json.loads(lines[-1].decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "UNKNOWN_FAILURE"
    if not isinstance(value, dict):
        return "UNKNOWN_FAILURE"
    disposition = value.get("process_disposition")
    status = value.get("status")
    if disposition not in PROCESS_DISPOSITIONS:
        return "UNKNOWN_FAILURE"
    if exit_code == 0:
        return (
            "SUCCESS"
            if disposition == "SUCCESS" and status == "PASS"
            else "UNKNOWN_FAILURE"
        )
    return (
        str(disposition)
        if disposition != "SUCCESS" and status == "FAIL"
        else "UNKNOWN_FAILURE"
    )


def _invoke(
    base: list[str],
    *,
    resume: bool,
    output: Path,
    attempt: int,
    split: str,
) -> tuple[object, dict[str, Any]]:
    command = [*base, *(["--resume"] if resume else [])]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
    stdout = _write(output / f"attempt-{attempt}.stdout.bin", completed.stdout)
    stderr = _write(output / f"attempt-{attempt}.stderr.bin", completed.stderr)
    disposition = _disposition(completed.stdout, completed.returncode)
    row = {
        "attempt": attempt,
        "argv": [
            "python",
            "scripts/trimem_benchmark_run.py",
            "--split",
            split,
            "--approval-file",
            "<external-protected-approval>",
            *(["--resume"] if resume else []),
        ],
        "exit_code": completed.returncode,
        "process_disposition": disposition,
        "resume": resume,
        "stdout": stdout,
        "stderr": stderr,
    }
    sys.stdout.buffer.write(completed.stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(completed.stderr)
    sys.stderr.buffer.flush()
    return completed, row


def _validated_cached_task_plan(
    benchmark: Any,
    *,
    split: str,
    frozen_targets: Sequence[Mapping[str, Any]],
) -> tuple[list[Any], dict[str, dict[str, Any]], str]:
    """Rebuild the exact task stream without permitting a dataset download."""

    grader_lock = benchmark.read_json(
        benchmark.ROOT / "configs/trimem_v1/grader_lock.json"
    )
    specs = {
        row.get("benchmark_id"): row
        for row in grader_lock.get("dataset_files", ())
        if isinstance(row, Mapping)
    }
    cache_root = benchmark.ROOT / ".trimem-exec/datasets"
    for benchmark_id in sorted(
        {str(row.get("benchmark_id")) for row in frozen_targets}
    ):
        spec = specs.get(benchmark_id)
        if not isinstance(spec, Mapping):
            raise ValueError("resume dataset lock is absent")
        target = (
            cache_root
            / str(spec.get("benchmark_id"))
            / str(spec.get("dataset_revision"))
            / Path(str(spec.get("path"))).name
        )
        if target.is_symlink() or not target.is_file():
            raise ValueError("resume requires an already cached frozen dataset")
        raw = target.read_bytes()
        if (
            type(spec.get("bytes")) is not int
            or len(raw) != spec["bytes"]
            or benchmark.sha256_bytes(raw) != spec.get("sha256")
        ):
            raise ValueError("cached resume dataset differs from its frozen lock")
    loaded_targets, rows = benchmark.load_frozen_rows(split, cache_root)
    if benchmark.canonical_bytes(loaded_targets) != benchmark.canonical_bytes(
        list(frozen_targets)
    ):
        raise ValueError("cached task targets differ from the frozen manifest")
    tasks = benchmark.coding_tasks(loaded_targets, rows)
    from enterprise_memory.trimem.production_runtime import (
        _sha256,
        _task_order_payload,
    )

    task_order_hash = _sha256([_task_order_payload(task) for task in tasks])
    return tasks, rows, task_order_hash


def _require_committed_file_bytes(
    benchmark: Any,
    *,
    commit: str,
    paths: Sequence[Path],
) -> None:
    """Reject working-tree configuration bytes not present at approved HEAD."""

    root = benchmark.ROOT.resolve(strict=True)
    git_dir = root / ".git"
    if _is_link_or_reparse(git_dir) or not git_dir.is_dir():
        raise ValueError("approved runtime Git metadata is not local")
    git_environment = {
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

    def git_read(*arguments: str) -> bytes:
        completed = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                f"--git-dir={git_dir}",
                f"--work-tree={root}",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                *arguments,
            ],
            capture_output=True,
            check=False,
            env=git_environment,
        )
        if completed.returncode != 0:
            raise ValueError("approved runtime Git object query failed")
        return completed.stdout

    tree = git_read(
        "ls-tree",
        "-r",
        "-z",
        "--name-only",
        commit,
        "--",
        "scripts",
        "src/enterprise_memory",
    )
    committed_code = []
    for raw_name in tree.split(b"\0"):
        if not raw_name:
            continue
        try:
            name = raw_name.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("approved runtime code path is not UTF-8") from exc
        if (
            name.startswith("scripts/")
            and name.endswith(".py")
        ) or (
            name.startswith("src/enterprise_memory/")
            and name.endswith(".py")
        ):
            committed_code.append(root / name)
    if not committed_code:
        raise ValueError("approved runtime code tree is empty")
    expected_code = {
        path.relative_to(root).as_posix() for path in committed_code
    }
    observed_code: set[str] = set()
    for code_root in (root / "scripts", root / "src/enterprise_memory"):
        for current_root, directory_names, file_names in os.walk(
            code_root,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_root)
            for name in list(directory_names):
                candidate = current / name
                if _is_link_or_reparse(candidate):
                    raise ValueError("runtime code tree contains a linked directory")
            for name in file_names:
                if not name.endswith(".py"):
                    continue
                candidate = current / name
                if _is_link_or_reparse(candidate) or not candidate.is_file():
                    raise ValueError("runtime Python path is not a regular file")
                observed_code.add(candidate.relative_to(root).as_posix())
    if observed_code != expected_code:
        raise ValueError("runtime Python inventory differs from approved Git tree")

    unique_paths = {path.absolute() for path in (*paths, *committed_code)}
    for path in sorted(unique_paths, key=lambda value: value.as_posix()):
        resolved = _secure_existing_path(
            root,
            path,
            directory=False,
            label="approved runtime file",
        )
        relative = resolved.relative_to(root).as_posix()
        committed_raw = git_read("cat-file", "blob", f"{commit}:{relative}")
        if committed_raw != resolved.read_bytes():
            raise ValueError(
                "resume configuration differs from approved Git blob: "
                + relative
            )


def _workspace_factory_for_stream(
    benchmark: Any,
    *,
    split: str,
    stream_id: str,
    tasks: Sequence[Any],
    targets: Sequence[Mapping[str, Any]],
    images: Mapping[str, Mapping[str, Any]],
) -> Any:
    """Construct the production workspace identity without touching a checkout."""

    roots: dict[str, Path] = {}
    commits: dict[str, str] = {}
    runners: dict[str, Any] = {}
    for task, target in zip(tasks, targets):
        safe_task = re.sub(r"[^A-Za-z0-9_.-]", "_", str(task.task_id))
        roots[str(task.task_id)] = (
            benchmark.ROOT
            / ".trimem-exec/checkouts"
            / split
            / stream_id
            / safe_task
        )
        commits[str(task.task_id)] = str(task.commit)
        image = images.get(str(target.get("instance_id")), {}).get("image")
        if not isinstance(image, str) or not image:
            raise ValueError("frozen task image is absent")
        runners[str(task.task_id)] = benchmark.DockerSandboxCommandRunner(image)
    factory = benchmark.GitCheckoutWorkspaceFactory(
        roots,
        commits,
        command_runners=runners,
    )
    if factory.production_capable is not True:
        raise ValueError("resume workspace factory is not production capable")
    return factory


def _validate_resume_checkout_suffix(
    benchmark: Any,
    *,
    split: str,
    authority: Mapping[str, Any],
    stream_authorities: Mapping[str, Mapping[str, Any]],
    grouped: Mapping[str, Sequence[tuple[Path, Mapping[str, Any]]]],
    checkpoint_workspace_states: Mapping[tuple[str, int], Mapping[str, Any]],
) -> None:
    """Reject injected bytes in every checkout process two may execute."""

    from enterprise_memory.trimem.accounting import canonical_bytes
    from enterprise_memory.trimem.git_workspace import GitCheckoutWorkspace

    repository_root = benchmark.ROOT.resolve(strict=True)
    checkout_split = (
        benchmark.ROOT / ".trimem-exec" / "checkouts" / split
    ).absolute()
    if not checkout_split.exists():
        raise ValueError("resume checkout split root is absent")
    checkout_split = _secure_existing_path(
        repository_root,
        checkout_split,
        directory=True,
        label="resume checkout split root",
    )
    planned_stream_ids = [
        stream_id for stream_id, _runtime_arm in authority["stream_plan"]
    ]
    stream_entries = list(checkout_split.iterdir())
    if any(
        _is_link_or_reparse(entry) or not entry.is_dir()
        for entry in stream_entries
    ) or not {entry.name for entry in stream_entries} <= set(planned_stream_ids):
        raise ValueError("resume checkout stream inventory differs")

    tasks = list(authority["tasks"])
    expected_names = {
        re.sub(r"[^A-Za-z0-9_.-]", "_", str(task.task_id)): task
        for task in tasks
    }
    if len(expected_names) != len(tasks):
        raise ValueError("resume checkout task path identities collide")
    observed_stream_dirs = {entry.name: entry for entry in stream_entries}
    for stream_id in planned_stream_ids:
        stream_path = observed_stream_dirs.get(stream_id)
        if stream_path is None:
            if stream_id in grouped:
                raise ValueError("started resume stream has no checkouts")
            continue
        stream_path = _secure_existing_path(
            repository_root,
            stream_path,
            directory=True,
            label="resume checkout stream",
        )
        checkout_entries = list(stream_path.iterdir())
        if (
            any(
                _is_link_or_reparse(entry) or not entry.is_dir()
                for entry in checkout_entries
            )
            or {entry.name for entry in checkout_entries} != set(expected_names)
        ):
            raise ValueError("resume checkout task inventory differs")
        protected_prefix = len(grouped.get(stream_id, ()))
        for index, task in enumerate(tasks):
            safe_name = re.sub(
                r"[^A-Za-z0-9_.-]", "_", str(task.task_id)
            )
            checkout = _secure_existing_path(
                repository_root,
                stream_path / safe_name,
                directory=True,
                label="resume task checkout",
            )
            git_metadata = checkout / ".git"
            if _is_link_or_reparse(git_metadata) or not git_metadata.is_dir():
                raise ValueError("resume checkout Git metadata is not local")
            if stream_id in stream_authorities:
                expected_factory_path = stream_authorities[stream_id][
                    "workspace_factory"
                ].checkout_roots[str(task.task_id)]
                if Path(expected_factory_path).resolve(strict=True) != checkout:
                    raise ValueError(
                        "resume checkout differs from workspace authority"
                    )
            if stream_id in grouped and index < protected_prefix:
                expected_state = checkpoint_workspace_states.get(
                    (stream_id, index)
                )
                if not isinstance(expected_state, Mapping):
                    raise ValueError(
                        "resume committed checkout has no workspace checkpoint"
                    )
                observed_state = GitCheckoutWorkspace(
                    checkout,
                    base_commit=str(task.commit),
                ).checkpoint_state()
                if canonical_bytes(observed_state) != canonical_bytes(
                    dict(expected_state)
                ):
                    raise ValueError(
                        "resume committed checkout differs from workspace checkpoint"
                    )
            else:
                _validate_checkout_tree_bytes(
                    checkout,
                    expected_commit=str(task.commit),
                )


def _validate_checkout_tree_bytes(
    checkout: Path,
    *,
    expected_commit: str,
) -> None:
    """Compare a future checkout byte-for-byte with one immutable Git tree.

    This deliberately ignores the checkout index, status cache, ignore files,
    fsmonitor and local ``core.worktree``.  Those are mutable inputs and can
    hide injected bytes.  Git supplies only the content-addressed tree/object
    identities; Python walks and hashes the lexical work tree without following
    links.
    """

    if re.fullmatch(r"[0-9a-f]{40}", expected_commit) is None:
        raise ValueError("resume checkout base commit is malformed")
    git_dir = checkout / ".git"
    if _is_link_or_reparse(git_dir) or not git_dir.is_dir():
        raise ValueError("resume checkout Git metadata is not local")
    git_env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LC_ALL": "C",
        "LANG": "C",
    }

    def git_read(*arguments: str) -> bytes:
        completed = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                f"--git-dir={git_dir}",
                f"--work-tree={checkout}",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                *arguments,
            ],
            capture_output=True,
            check=False,
            env=git_env,
        )
        if completed.returncode != 0:
            raise ValueError("resume checkout Git object query failed")
        return completed.stdout

    if git_read("rev-parse", "--verify", "HEAD").strip() != (
        expected_commit.encode("ascii")
    ):
        raise ValueError("resume checkout commit identity differs")
    raw_tree = git_read("ls-tree", "-rz", "--full-tree", expected_commit)
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
            raise ValueError("resume checkout Git tree is malformed") from exc
        parts = relative.split("/")
        if (
            not relative
            or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in parts)
            or (os.name == "nt" and "\\" in relative)
            or re.fullmatch(r"[0-9a-f]{40}", object_id) is None
        ):
            raise ValueError("resume checkout Git path is unsafe")
        if kind == "blob" and mode in {"100644", "100755", "120000"}:
            blobs[relative] = (mode, object_id)
        elif kind == "commit" and mode == "160000":
            gitlinks.add(relative)
        else:
            raise ValueError("resume checkout Git tree entry is unsupported")
    if len(blobs) + len(gitlinks) != len(set(blobs) | gitlinks):
        raise ValueError("resume checkout Git tree paths collide")

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
        candidate = checkout.joinpath(*relative.split("/"))
        current = checkout
        for part in relative.split("/")[:-1]:
            current = current / part
            if _is_link_or_reparse(current) or not current.is_dir():
                raise ValueError("resume checkout tracked parent is unsafe")
        if mode == "120000":
            if candidate.is_symlink():
                target = os.readlink(candidate)
                raw = target if isinstance(target, bytes) else os.fsencode(target)
            elif os.name == "nt" and not _is_link_or_reparse(
                candidate
            ) and candidate.is_file():
                # Git for Windows may materialize a symlink blob as its target
                # text when core.symlinks=false; bind those exact blob bytes.
                raw = candidate.read_bytes()
            else:
                raise ValueError("resume checkout tracked symlink differs")
        else:
            if _is_link_or_reparse(candidate) or not candidate.is_file():
                raise ValueError("resume checkout tracked file is absent")
            raw = candidate.read_bytes()
            if os.name != "nt" and bool(candidate.stat().st_mode & stat.S_IXUSR) != (
                mode == "100755"
            ):
                raise ValueError("resume checkout executable mode differs")
        header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
        if hashlib.sha1(header + raw).hexdigest() != object_id:
            raise ValueError("future resume checkout differs from frozen Git blob")

    for relative in gitlinks:
        candidate = checkout.joinpath(*relative.split("/"))
        if candidate.exists() or candidate.is_symlink():
            if (
                _is_link_or_reparse(candidate)
                or not candidate.is_dir()
                or any(candidate.iterdir())
            ):
                raise ValueError("resume checkout gitlink is not pristine")

    observed_leaf_paths: set[str] = set()
    observed_directories: set[str] = set()
    for current_root, directory_names, file_names in os.walk(
        checkout, topdown=True, followlinks=False
    ):
        current = Path(current_root)
        if current == checkout and ".git" in directory_names:
            directory_names.remove(".git")
        for name in list(directory_names):
            path = current / name
            relative = path.relative_to(checkout).as_posix()
            if _is_link_or_reparse(path):
                directory_names.remove(name)
                observed_leaf_paths.add(relative)
            else:
                observed_directories.add(relative)
        for name in file_names:
            observed_leaf_paths.add(
                (current / name).relative_to(checkout).as_posix()
            )
    if (
        observed_leaf_paths != expected_leaf_paths
        or not required_directories <= observed_directories
        or not observed_directories <= allowed_directories
    ):
        raise ValueError("future resume checkout inventory differs from frozen tree")


def _expected_memory_controller_hash(
    *,
    runtime_arm: str,
    policy: Mapping[str, Any],
) -> str:
    """Rebuild the configuration-only controller identity without I/O."""

    from enterprise_memory.trimem.agent_runtime import NoMemoryController
    from enterprise_memory.trimem.arms import (
        ActiveNodeTriMemController,
        CurrentV03MemoryController,
    )
    from enterprise_memory.trimem.ppr import PinnedSentenceTransformerPPR
    from enterprise_memory.trimem.production_v03_lifecycle import (
        LIVE_V03_IMPLEMENTATION_MANIFEST,
    )
    from enterprise_memory.trimem.retrieval import (
        InMemoryMemoryGraphStore,
        RetrievalConfig,
        TriMemoryRetriever,
    )

    if runtime_arm == "M0":
        return NoMemoryController().content_hash
    if runtime_arm == "M1":
        controller = CurrentV03MemoryController(
            lambda _task, _active_node: None,
            lambda _digest: None,
            task_id="__FROZEN_CONTROLLER_IDENTITY__",
            implementation_manifest=LIVE_V03_IMPLEMENTATION_MANIFEST,
        )
        return controller.content_hash
    if runtime_arm != "M2":
        raise ValueError("resume runtime arm is not frozen")
    retrieval = policy.get("retrieval")
    if not isinstance(retrieval, Mapping):
        raise ValueError("resume M2 retrieval policy is absent")
    config = RetrievalConfig(
        min_confidence=float(retrieval["min_confidence"]),
        min_margin=float(retrieval["min_margin"]),
        episode_complete_threshold=float(
            retrieval["episode_complete_threshold"]
        ),
        max_episodic_per_node=int(
            retrieval["max_episodic_per_active_node"]
        ),
        max_semantic_per_node=int(
            retrieval["max_semantic_per_active_node"]
        ),
        max_task_injections=int(retrieval["max_task_injections"]),
        context_budget_bytes=int(retrieval["context_budget_bytes"]),
        embedding_dimensions=int(retrieval["embedding_dimensions"]),
        embedding_weight=float(retrieval["embedding_weight"]),
        lexical_weight=float(retrieval["lexical_weight"]),
        ppr_damping=float(retrieval["ppr_damping"]),
        ppr_iterations=int(retrieval["ppr_iterations"]),
    )
    retriever = TriMemoryRetriever(
        InMemoryMemoryGraphStore(),
        config,
        embedder=PinnedSentenceTransformerPPR(),
    )
    return ActiveNodeTriMemController(
        retriever,
        task_id="__FROZEN_CONTROLLER_IDENTITY__",
    ).content_hash


def _validated_local_harnesses(benchmark: Any) -> dict[str, Path]:
    """Validate pinned harness bytes without invoking mutable checkout config."""

    import trimem_harness_lock as harness_lock

    repository_root = benchmark.ROOT.resolve(strict=True)
    root = (benchmark.ROOT / ".trimem-exec/harnesses").absolute()
    _environment, rows = harness_lock._load_lock_rows()
    root = _secure_existing_path(
        repository_root,
        root,
        directory=True,
        label="resume harness checkout root",
    )
    entries = list(root.iterdir())
    expected_checkout_keys = {str(row["checkout_key"]) for row in rows}
    if (
        any(_is_link_or_reparse(path) or not path.is_dir() for path in entries)
        or {path.name for path in entries} != expected_checkout_keys
    ):
        raise ValueError("resume harness checkout inventory differs")
    harnesses: dict[str, Path] = {}
    for row in rows:
        path = root / str(row["checkout_key"])
        path = _secure_existing_path(
            repository_root,
            path,
            directory=True,
            label="resume pinned harness checkout",
        )
        _validate_checkout_tree_bytes(
            path,
            expected_commit=str(row["revision"]),
        )
        harness_lock.validate_dependency_declarations(
            path,
            str(row["revision"]),
            row["dependency_declarations"],
        )
        for benchmark_id in row["benchmark_ids"]:
            harnesses[str(benchmark_id)] = path
    if set(harnesses) != {
        str(benchmark_id)
        for row in rows
        for benchmark_id in row["benchmark_ids"]
    }:
        raise ValueError("resume harness set differs from its committed lock")
    return harnesses


def _validated_identity_seed(
    benchmark: Any,
    *,
    execution_root: Path,
    experiment_id: str,
    stream_id: str,
    tasks: Sequence[Any],
) -> dict[str, Any]:
    """Recompute every execution-bearing identity in retained seed evidence."""

    from enterprise_memory.trimem.benchmark_seed import (
        _normalize_tasks,
        _permission_id,
    )

    path = _secure_existing_path(
        execution_root,
        execution_root / "identity-seeds" / f"{stream_id}.json",
        directory=False,
        label="resume identity-seed evidence",
    )
    evidence = benchmark.read_json(path)
    org_id, user_id, normalized = _normalize_tasks(
        tasks,
        benchmark.repository_identity_resolver(experiment_id, stream_id),
    )
    rows = []
    for item in normalized:
        spec = {
            "schema": "trimem/benchmark-seeded-solve-job/1.0",
            "experiment_id": experiment_id,
            "stream_id": stream_id,
            "task_id": item["task_id"],
            "repository": item["repository"],
            "commit": item["commit"],
        }
        rows.append(
            {
                "task_id": item["task_id"],
                "repository": item["repository"],
                "repository_id": item["repository_id"],
                "repository_permission_id": _permission_id(
                    org_id, item["repository_id"], user_id
                ),
                "task_policy_id": item["task_policy_id"],
                "solve_job_id": item["solve_job_id"],
                "spec_hash": benchmark.canonical_hash(spec),
            }
        )
    admin_role = evidence.get("admin_role")
    if (
        not isinstance(admin_role, str)
        or not admin_role
        or admin_role != admin_role.strip()
    ):
        raise ValueError("resume identity-seed admin role is malformed")
    body = {
        "schema": "trimem/benchmark-identity-seed-evidence/1.0",
        "experiment_id": experiment_id,
        "stream_id": stream_id,
        "org_id": org_id,
        "user_id": user_id,
        "admin_role": admin_role,
        "admin_bypassrls": True,
        "rows": rows,
    }
    expected = {**body, "digest": benchmark.canonical_hash(body)}
    if evidence != expected or any(
        token in json.dumps(evidence, sort_keys=True).casefold()
        for token in ("database_url", "password")
    ):
        raise ValueError("resume identity-seed evidence differs")
    return expected


def _validated_session_identity(
    benchmark: Any,
    *,
    execution_root: Path,
    split: str,
    stream_id: str,
    experiment_id: str,
    execution_lock_hash: str,
) -> dict[str, Any]:
    path = _secure_existing_path(
        execution_root,
        execution_root / f"{stream_id}.session-identity.json",
        directory=False,
        label="resume stream session identity",
    )
    envelope = benchmark.read_json(path)
    payload = envelope.get("payload")
    if (
        set(envelope) != {"payload", "digest"}
        or not isinstance(payload, Mapping)
        or set(payload)
        != {
            "schema",
            "arm",
            "split",
            "experiment_id",
            "execution_lock_hash",
            "run_nonce",
        }
        or envelope.get("digest")
        != "sha256:"
        + benchmark.sha256_bytes(benchmark.canonical_bytes(payload))
    ):
        raise ValueError("resume stream session identity seal differs")
    expected = {
        "schema": "trimem/benchmark-arm-session-identity/1.0",
        "arm": stream_id,
        "split": split,
        "experiment_id": experiment_id,
        "execution_lock_hash": execution_lock_hash,
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise ValueError("resume stream session identity differs")
    run_nonce = str(uuid.UUID(str(payload.get("run_nonce"))))
    if payload.get("run_nonce") != run_nonce:
        raise ValueError("resume stream run nonce is not canonical")
    return dict(payload)


def _stream_static_authority(
    benchmark: Any,
    authority: Mapping[str, Any],
    execution_root: Path,
    *,
    split: str,
    stream_id: str,
    runtime_arm: str,
    selected_candidate_id: str,
) -> dict[str, Any]:
    """Derive a stream's exact static identities through production builders."""

    tasks = authority["tasks"]
    targets = authority["targets"]
    images = authority["images"]
    experiment_id = (
        "trimemv1-"
        + str(authority["git_head"])[:12]
        + "-"
        + re.sub(r"[^a-z0-9-]", "-", stream_id.lower())
    )
    if selected_candidate_id not in benchmark.CANDIDATE_IDS:
        raise ValueError("resume selected candidate is not preregistered")
    runtime_lock = benchmark.runtime_lock_for(selected_candidate_id)
    policy = benchmark.load_candidate_policy(selected_candidate_id)
    m2_manifest = policy if runtime_arm == "M2" else None
    checkpoint_path: Path | None = None
    if split == "heldout" and runtime_arm == "M2":
        selected = benchmark.validate_selected_m2(require_frozen=True)
        if selected.get("selected_candidate_id") != selected_candidate_id:
            raise ValueError("held-out candidate differs from committed selection")
        checkpoint_path = benchmark.ROOT / str(selected["selected_checkpoint_path"])
    workspace = _workspace_factory_for_stream(
        benchmark,
        split=split,
        stream_id=stream_id,
        tasks=tasks,
        targets=targets,
        images=images,
    )
    identity_seed = _validated_identity_seed(
        benchmark,
        execution_root=execution_root,
        experiment_id=experiment_id,
        stream_id=stream_id,
        tasks=tasks,
    )
    execution_lock_hash = benchmark.build_execution_lock_hash(
        split=split,
        arm=runtime_arm,
        stream_id=stream_id,
        approval=authority["approval"],
        targets=targets,
        rows=authority["rows"],
        tasks=tasks,
        workspace_factory=workspace,
        harnesses=authority["harnesses"],
        images=images,
        model_lock=authority["model_lock"],
        m2_manifest=m2_manifest,
        checkpoint_path=checkpoint_path,
        runtime_lock=runtime_lock,
        identity_seed_evidence=identity_seed,
        official_harness_loader_preflight=authority["official_preflight"],
    )
    identity = _validated_session_identity(
        benchmark,
        execution_root=execution_root,
        split=split,
        stream_id=stream_id,
        experiment_id=experiment_id,
        execution_lock_hash=execution_lock_hash,
    )
    from enterprise_memory.trimem.ppr import PinnedSentenceTransformerPPR
    from enterprise_memory.trimem.production_runtime import (
        _load_frozen_policy,
        _service_endpoint_hash,
        _sha256,
        _validate_database_url,
        _validate_qdrant_url,
        _verify_embedder_lock,
        benchmark_namespace,
    )

    database_url = _validate_database_url(os.environ.get("TRIMEM_DATABASE_URL", ""))
    qdrant_url = _validate_qdrant_url(os.environ.get("TRIMEM_QDRANT_URL", ""))
    provenance = _verify_embedder_lock(
        PinnedSentenceTransformerPPR(),
        authority["model_lock"]["retrieval_embedding"]["production"],
    )
    _policy, checkpoint_hash = _load_frozen_policy(
        checkpoint_path,
        required=(runtime_arm == "M2" and split == "heldout"),
    )
    if runtime_arm == "M0":
        lifecycle_hash = _sha256({"lifecycle": "NONE"})
    elif runtime_arm == "M1":
        lifecycle_hash = benchmark.production_v03_lifecycle_factory.configuration_hash
        if not str(lifecycle_hash).startswith("sha256:"):
            lifecycle_hash = "sha256:" + str(lifecycle_hash)
    else:
        lifecycle_hash = "sha256:" + benchmark.sha256_bytes(
            benchmark.canonical_bytes(policy)
        )
    namespace = benchmark_namespace(experiment_id, split, runtime_arm)
    config_hash = _sha256(
        {
            "schema": "trimem/production-arm-config/1.0",
            "namespace": namespace,
            "arm_id": runtime_arm,
            "split": split,
            "evaluation": split == "heldout",
            "task_order_hash": authority["task_order_hash"],
            "execution_lock_hash": execution_lock_hash,
            "database_endpoint_hash": _service_endpoint_hash(database_url),
            "qdrant_endpoint_hash": _service_endpoint_hash(qdrant_url),
            "dqn_checkpoint_hash": checkpoint_hash,
            "lifecycle_configuration_hash": lifecycle_hash,
            "embedder_provenance": provenance,
            "canonical_backend": "postgresql",
            "vector_backend": "qdrant",
        }
    )
    return {
        "experiment_id": experiment_id,
        "namespace": namespace,
        "task_order_hash": authority["task_order_hash"],
        "config_hash": config_hash,
        "run_nonce": identity["run_nonce"],
        "execution_lock_hash": execution_lock_hash,
        "identity_seed_digest": identity_seed["digest"],
        "runtime_lock_sha256": "sha256:" + runtime_lock.content_hash,
        "m2_policy_manifest_sha256": (
            "sha256:" + benchmark.sha256_bytes(benchmark.canonical_bytes(policy))
            if runtime_arm == "M2"
            else None
        ),
        "selected_prompt_candidate_id": selected_candidate_id,
        "workspace_factory_hash": workspace.content_hash,
        "memory_controller_hash": _expected_memory_controller_hash(
            runtime_arm=runtime_arm,
            policy=policy,
        ),
        "workspace_factory": workspace,
        "images": images,
    }


def _validate_namespace_evidence(
    benchmark: Any,
    *,
    namespace: str,
    owner_user_id: str,
    canonical_evidence: object,
    qdrant_evidence: object,
    receipt_evidence: object,
) -> None:
    from enterprise_memory.trimem.production_runtime import (
        _canonical_counts,
        _qdrant_point_digest_maps,
        _sha256,
        _verified_receipt_suffix,
    )

    counts = _canonical_counts(canonical_evidence)
    if not isinstance(canonical_evidence, Mapping) or canonical_evidence != {
        "namespace": namespace,
        "row_counts": [[name, count] for name, count in counts.items()],
        "digest": _sha256(
            {"namespace": namespace, "row_counts": list(counts.items())}
        ),
    }:
        raise ValueError("resume canonical namespace evidence differs")
    point_maps = _qdrant_point_digest_maps(qdrant_evidence)
    if (
        not isinstance(qdrant_evidence, Mapping)
        or set(qdrant_evidence) != {"collections", "digest"}
        or qdrant_evidence.get("digest")
        != _sha256(qdrant_evidence.get("collections"))
        or set(point_maps) != set(qdrant_evidence.get("collections", {}))
    ):
        raise ValueError("resume Qdrant namespace evidence differs")
    for collection in qdrant_evidence["collections"].values():
        if (
            not isinstance(collection, Mapping)
            or set(collection)
            != {"exists", "points", "point_digests", "content_digest"}
            or type(collection.get("exists")) is not bool
            or type(collection.get("points")) is not int
            or collection["points"] < 0
            or not isinstance(collection.get("point_digests"), list)
            or not isinstance(collection.get("content_digest"), str)
            or re.fullmatch(
                r"sha256:[0-9a-f]{64}", collection["content_digest"]
            )
            is None
        ):
            raise ValueError("resume Qdrant collection evidence differs")
    _verified_receipt_suffix(
        receipt_evidence,
        receipt_evidence,
        namespace=namespace,
        owner_user_id=owner_user_id,
    )
    if (
        not isinstance(receipt_evidence, Mapping)
        or set(receipt_evidence)
        != {"schema", "namespace", "owner_user_id", "rows", "digest"}
    ):
        raise ValueError("resume lifecycle receipt evidence differs")


def _selected_candidate_for_stream(
    benchmark: Any,
    *,
    execution_root: Path,
    split: str,
    stream_id: str,
) -> str:
    if split == "heldout":
        return str(
            benchmark.validate_selected_m2(require_frozen=True)[
                "selected_candidate_id"
            ]
        )
    if stream_id.startswith("M2-"):
        candidate_id = stream_id.removeprefix("M2-")
        if candidate_id not in benchmark.CANDIDATE_IDS:
            raise ValueError("development M2 stream is not preregistered")
        return candidate_id
    selection_path = _secure_existing_path(
        execution_root,
        execution_root / "development-selection.json",
        directory=False,
        label="selected development candidate evidence",
    )
    evidence = benchmark.read_json(selection_path)
    summaries = evidence.get("candidate_summaries")
    recalculated = benchmark.select_development_candidate(summaries)
    if (
        evidence.get("schema")
        != "trimem/development-m2-selection-evidence/1.0"
        or evidence.get("status")
        != "COMPLETE_PENDING_COMMIT_FREEZE_AND_HELDOUT_APPROVAL"
        or evidence.get("candidate_bundle_sha256")
        != "sha256:"
        + benchmark.sha256_bytes(
            benchmark.canonical_bytes(benchmark.load_m2_candidate_bundle())
        )
        or evidence.get("selection") != recalculated
    ):
        raise ValueError("development candidate selection evidence differs")
    return str(recalculated["selected_candidate_id"])


def _validate_task_model_journals(
    benchmark: Any,
    *,
    execution_root: Path,
    task_dir: Path,
    stream_id: str,
    task_arm_key: str,
    ledger_requests: Mapping[str, Any],
    expected_model: str,
) -> list[Mapping[str, Any]]:
    """Bind every local model-call journal to one terminal ledger request."""

    expected = {
        logical_id.removeprefix(stream_id + ":"): row
        for logical_id, row in ledger_requests.items()
        if isinstance(logical_id, str)
        and logical_id.startswith(stream_id + ":")
        and isinstance(row, Mapping)
        and row.get("task_arm_key") == task_arm_key
    }
    model_root = _secure_optional_path(
        execution_root,
        task_dir / "terminal-journal" / "model",
        directory=True,
        label="resume model-journal directory",
    )
    if model_root is None:
        if expected:
            raise ValueError("terminal ledger requests have no model journals")
        return []
    try:
        evidence = benchmark.RawEvidenceLedger(task_dir / "evidence")
        evidence.verify()
        raw_events = evidence.verified_suffix("0" * 64)
    except Exception as exc:
        raise ValueError("resume model evidence ledger is invalid") from exc
    terminal_evidence: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
    for event in raw_events:
        event_type = event.get("event_type")
        payload = event.get("payload")
        if (
            event_type not in {"model_response", "model_failure"}
            or not isinstance(payload, Mapping)
            or not isinstance(payload.get("logical_call_id"), str)
        ):
            continue
        terminal_evidence.setdefault(
            str(payload["logical_call_id"]), []
        ).append((str(event_type), payload))
    paths = list(model_root.iterdir())
    if any(path.is_symlink() or not path.is_file() for path in paths):
        raise ValueError("resume model-journal inventory contains a non-file")
    observed: set[str] = set()
    for path in paths:
        path = _secure_existing_path(
            execution_root,
            path,
            directory=False,
            label="resume model journal",
        )
        row = benchmark.read_json(path)
        key = row.get("key")
        status = row.get("status")
        ledger_row = expected.get(key) if isinstance(key, str) else None
        terminal_payload = (
            "response"
            if status == "PROVIDER_TERMINAL_SUCCESS"
            else "failure"
            if status == "PROVIDER_TERMINAL_FAILURE"
            else None
        )
        base_fields = {
            "schema",
            "kind",
            "key",
            "request_sha256",
            "status",
            "provider_send_started",
            "preflight",
            "ledger_reservation",
        }
        try:
            preflight_value = row.get("preflight")
            if not isinstance(preflight_value, Mapping):
                raise TypeError("preflight is absent")
            preflight = benchmark.ReservationPreflight(**dict(preflight_value))
        except (TypeError, ValueError) as exc:
            raise ValueError("resume model-journal preflight is malformed") from exc
        preflight_plan = {
            name: getattr(preflight, name)
            for name in (
                "status",
                "request_sha256",
                "ledger_logical_call_id",
                "task_arm_key",
                "call_kind",
                "input_upper_bound",
                "output_cap",
                "reserved_usd",
                "reservation_id",
                "ledger_state_sha256",
            )
        }
        expected_reservation = {
            "reservation_id": preflight.reservation_id,
            "input_upper_bound": preflight.input_upper_bound,
            "output_cap": preflight.output_cap,
            "charged_conservatively": False,
        }
        if (
            terminal_payload is None
            or not isinstance(key, str)
            or not key
            or key in observed
            or path.name
            != benchmark.sha256_bytes(key.encode("utf-8")) + ".json"
            or row.get("schema") != "trimem/terminal-invocation-journal/2.0"
            or row.get("kind") != "model"
            or row.get("provider_send_started") is not True
            or set(row) != base_fields | {terminal_payload}
            or not isinstance(row.get(terminal_payload), Mapping)
            or not isinstance(ledger_row, Mapping)
            or row.get("request_sha256") != preflight.request_sha256
            or preflight.plan_sha256
            != benchmark.sha256_bytes(benchmark.canonical_bytes(preflight_plan))
            or preflight.ledger_logical_call_id != f"{stream_id}:{key}"
            or preflight.task_arm_key != task_arm_key
            or preflight.reservation_id != ledger_row.get("reservation_id")
            or preflight.input_upper_bound != ledger_row.get("input_upper_bound")
            or preflight.output_cap != ledger_row.get("output_cap")
            or preflight.reserved_usd != ledger_row.get("reserved_usd")
            or preflight.call_kind != ledger_row.get("call_kind")
            or ledger_row.get("call_cap_name")
            != benchmark.CALL_CAP_BY_KIND.get(preflight.call_kind)
            or row.get("ledger_reservation") != expected_reservation
        ):
            raise ValueError("resume model journal is not terminal and ledger-bound")
        terminal = row[terminal_payload]
        if status == "PROVIDER_TERMINAL_SUCCESS":
            response_fields = {
                "text",
                "provider",
                "model",
                "input_tokens",
                "output_tokens",
                "wall_time_ms",
                "paid",
                "cached_input_tokens",
                "reasoning_tokens",
                "attempt",
                "status",
                "provider_reported_usage_available",
                "provider_response_envelope",
                "ledger_reservation",
                "terminal_outcome_replayed",
                "response_mode",
                "output_items",
                "function_call_id",
                "function_name",
                "function_arguments",
                "function_arguments_sha256",
            }
            allowed_ledger_statuses = {
                "SUCCESS",
                "SUCCESS_CONSERVATIVE_USAGE",
            }
            if (
                set(terminal) != response_fields
                or terminal.get("provider") != "openai-responses"
                or terminal.get("model") != expected_model
                or terminal.get("paid") is not True
                or terminal.get("terminal_outcome_replayed") is not False
                or not isinstance(terminal.get("text"), str)
                or type(terminal.get("wall_time_ms")) is not int
                or terminal["wall_time_ms"] < 0
                or type(terminal.get("attempt")) is not int
                or terminal["attempt"] < 1
                or not isinstance(terminal.get("status"), str)
                or not terminal["status"]
                or type(terminal.get("provider_reported_usage_available"))
                is not bool
                or ledger_row.get("status") not in allowed_ledger_statuses
            ):
                raise ValueError("resume model success payload is malformed")
        else:
            failure_fields = {
                "provider",
                "model",
                "status",
                "attempt",
                "input_tokens",
                "output_tokens",
                "cached_input_tokens",
                "reasoning_tokens",
                "wall_time_ms",
                "response_text",
                "provider_request_id",
                "response_id",
                "response_status",
                "response_error_code",
                "incomplete_reason",
                "output_item_types",
                "content_item_types",
                "refusal_present",
                "provider_reported_usage_available",
                "raw_envelope_reference",
                "extracted_text_bytes",
                "structured_output_bytes",
                "original_provider_terminal_classification",
                "provider_response_envelope",
                "ledger_reservation",
            }
            allowed_ledger_statuses = {
                "PROVIDER_FAILURE",
                "PROVIDER_FAILURE_CONSERVATIVE",
            }
            if (
                set(terminal) != failure_fields
                or terminal.get("provider") != "openai-responses"
                or terminal.get("model") != expected_model
                or not isinstance(terminal.get("status"), str)
                or not terminal["status"]
                or type(terminal.get("attempt")) is not int
                or terminal["attempt"] < 1
                or type(terminal.get("wall_time_ms")) is not int
                or terminal["wall_time_ms"] < 0
                or not isinstance(terminal.get("response_text"), str)
                or type(terminal.get("provider_reported_usage_available"))
                is not bool
                or ledger_row.get("status") not in allowed_ledger_statuses
            ):
                raise ValueError("resume model failure payload is malformed")
        usage_available = terminal["provider_reported_usage_available"]
        usage_fields = (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
        )
        if usage_available:
            if (
                any(
                    type(terminal.get(name)) is not int
                    or terminal[name] < 0
                    for name in (*usage_fields, "reasoning_tokens")
                )
                or terminal["cached_input_tokens"] > terminal["input_tokens"]
                or terminal["reasoning_tokens"] > terminal["output_tokens"]
                or any(
                    ledger_row.get(name) != terminal[name]
                    for name in usage_fields
                )
                or "CONSERVATIVE" in str(ledger_row.get("status"))
            ):
                raise ValueError("resume model exact usage differs from ledger")
        elif (
            any(terminal.get(name) is not None for name in (*usage_fields, "reasoning_tokens"))
            or any(
                ledger_row.get(name) != bound
                for name, bound in (
                    ("input_tokens", preflight.input_upper_bound),
                    ("cached_input_tokens", 0),
                    ("output_tokens", preflight.output_cap),
                )
            )
            or "CONSERVATIVE" not in str(ledger_row.get("status"))
        ):
            raise ValueError("resume model conservative usage differs from ledger")
        expected_terminal_reservation = {
            **expected_reservation,
            "charged_conservatively": not usage_available,
        }
        if terminal.get("ledger_reservation") != expected_terminal_reservation:
            raise ValueError("resume model terminal reservation differs")
        matching_evidence = terminal_evidence.get(key, [])
        if len(matching_evidence) != 1:
            raise ValueError("resume model terminal evidence set differs")
        event_type, event_payload = matching_evidence[0]
        if (
            event_payload.get("request_sha256") != row["request_sha256"]
            or event_payload.get("logical_call_id") != key
            or event_payload.get("paid") is not True
        ):
            raise ValueError("resume model terminal evidence identity differs")
        try:
            response_text = benchmark._checkpoint_evidence_blob(
                evidence,
                event_payload.get("response"),
                media_type="text/plain; charset=utf-8",
            ).decode("utf-8", errors="strict")
        except Exception as exc:
            raise ValueError("resume model response evidence is invalid") from exc
        if status == "PROVIDER_TERMINAL_SUCCESS":
            evidence_fields = {
                name: event_payload.get(name)
                for name in (
                    "provider",
                    "model",
                    "attempt",
                    "input_tokens",
                    "output_tokens",
                    "cached_input_tokens",
                    "reasoning_tokens",
                    "wall_time_ms",
                    "status",
                    "provider_reported_usage_available",
                    "provider_response_envelope",
                    "ledger_reservation",
                    "response_mode",
                    "output_items",
                    "function_name",
                    "function_arguments_sha256",
                )
            }
            terminal_fields = {
                name: terminal.get(name) for name in evidence_fields
            }
            if (
                event_type != "model_response"
                or response_text != terminal.get("text")
                or evidence_fields != terminal_fields
            ):
                raise ValueError("resume model success differs from raw evidence")
            for name in ("function_call_id", "function_arguments"):
                reference = event_payload.get(name)
                expected_value = terminal.get(name)
                if reference is None:
                    if expected_value is not None:
                        raise ValueError(
                            "resume model function evidence differs"
                        )
                    continue
                try:
                    observed_value = benchmark._checkpoint_evidence_blob(
                        evidence,
                        reference,
                        media_type="text/plain; charset=utf-8",
                    ).decode("utf-8", errors="strict")
                except Exception as exc:
                    raise ValueError(
                        "resume model function evidence is invalid"
                    ) from exc
                if observed_value != expected_value:
                    raise ValueError("resume model function evidence differs")
        else:
            shared_failure_fields = failure_fields - {"response_text"}
            if (
                event_type not in {"model_response", "model_failure"}
                or response_text != terminal.get("response_text")
                or any(
                    event_payload.get(name) != terminal.get(name)
                    for name in shared_failure_fields
                )
            ):
                raise ValueError("resume model failure differs from raw evidence")
        observed.add(key)
    if observed != set(expected):
        raise ValueError("resume model journal set differs from terminal ledger requests")
    return [expected[key] for key in sorted(expected)]


def _validate_result_against_reserved_task_arm(
    benchmark: Any,
    *,
    record: Mapping[str, Any],
    task_row: Mapping[str, Any],
    task_arm_key: str,
    request_rows: Sequence[Mapping[str, Any]],
) -> None:
    """Prove a PREPARED cell is safe before mutating its ledger row."""

    accounting = record.get("actual_accounting")
    if (
        not isinstance(accounting, Mapping)
        or set(task_row) != benchmark.RESERVED_LEDGER_TASK_ARM_FIELDS
        or task_row.get("status") != "RESERVED"
        or task_row.get("actual_input_tokens") != accounting.get("input_tokens")
        or task_row.get("actual_model_calls")
        != accounting.get("model_gateway_calls")
        or task_row.get("actual_output_tokens") != accounting.get("output_tokens")
        or task_row.get("actual_decomposition_output_tokens")
        != accounting.get("actual_decomposition_output_tokens")
        or task_row.get("actual_solve_output_tokens")
        != accounting.get("actual_solve_output_tokens")
        or task_row.get("actual_extraction_output_tokens")
        != accounting.get("actual_extraction_output_tokens")
        or any(
            task_row.get(name) != 0
            for name in (
                "outstanding_input_tokens",
                "outstanding_model_calls",
                "outstanding_output_tokens",
            )
        )
    ):
        raise ValueError("resume reserved task-arm/result projection differs")
    role_fields = {
        "decompose": "actual_decomposition_output_tokens",
        "solve": "actual_solve_output_tokens",
        "extract": "actual_extraction_output_tokens",
    }
    for role, field in role_fields.items():
        if task_row.get(benchmark.TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[role]) != (
            benchmark.TASK_OUTPUT_POOL_BY_CALL_KIND[role]
            - int(accounting[field])
        ):
            raise ValueError("resume reserved task-arm role pool differs")
    # Historical credential-free zero-call fixtures intentionally have no paid
    # request projection.  Every executable provider path has either a request
    # row or explicit pre-request failure metadata and is checked here.
    if request_rows or accounting.get("model_gateway_calls") or record.get(
        "failure_metadata"
    ) is not None:
        benchmark.validate_result_request_statuses(record, list(request_rows))


def _validated_resume_authority(
    execution_root: Path,
    *,
    split: str,
    approval_file: Path,
) -> dict[str, Any]:
    """Reconstruct the immutable approval and ordered campaign plan."""

    import trimem_benchmark_run as benchmark

    repository_root = benchmark.ROOT.resolve(strict=True)
    expected_execution_root = (
        benchmark.ROOT
        / "artifacts/trimem_v1/benchmark_exec"
        / split
    ).absolute()
    secured_execution_root = _secure_existing_path(
        repository_root,
        expected_execution_root,
        directory=True,
        label="resume execution root",
    )
    if (
        execution_root.absolute() != expected_execution_root
        or execution_root.resolve(strict=True) != secured_execution_root
    ):
        raise ValueError("resume execution root differs from repository authority")
    if split not in {"development", "heldout"}:
        raise ValueError("resume split is not an executable benchmark phase")
    approval = benchmark.validate_exec_approval(split, approval_file)
    committed_paths = [
        benchmark.ROOT / "scripts/trimem_run_with_resume.py",
        benchmark.ROOT / "scripts/trimem_benchmark_run.py",
        benchmark.ROOT / "scripts/trimem_harness_lock.py",
        benchmark.ROOT / "scripts/trimem_m2_candidates.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/agent_runtime.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/benchmark_seed.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/checkpoint.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/git_workspace.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/ppr.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/production_lifecycle.py",
        benchmark.ROOT
        / "src/enterprise_memory/trimem/production_v03_lifecycle.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/production_runtime.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/runtime_lock.py",
        benchmark.ROOT / "src/enterprise_memory/trimem/schema.py",
        benchmark.ROOT / "configs/trimem_v1/model_lock.json",
        benchmark.ROOT / "configs/trimem_v1/cost_plan.json",
        benchmark.ROOT / "configs/trimem_v1/m2_policy.json",
        benchmark.ROOT / "configs/trimem_v1/m2_candidate_bundles.json",
        benchmark.ROOT / "configs/trimem_v1/selected_m2.json",
        benchmark.ROOT / "configs/trimem_v1/grader_lock.json",
        benchmark.ROOT / "configs/trimem_v1/benchmark_environment_lock.json",
        benchmark.ROOT / "configs/trimem_v1/benchmark_environment.lock",
        benchmark.ROOT / "configs/trimem_v1/benchmark_environment.in",
        benchmark.ROOT / "artifacts/trimem_v1/grader_image_lock.json",
        benchmark.ROOT / "artifacts/trimem_v1/freeze.json",
        benchmark.ROOT / benchmark.MANIFESTS[split],
        *(
            benchmark.ROOT
            / "configs/trimem_v1/m2_candidates"
            / f"{candidate_id}.json"
            for candidate_id in benchmark.CANDIDATE_IDS
        ),
    ]
    _require_committed_file_bytes(
        benchmark,
        commit=approval["git_head"],
        paths=committed_paths,
    )
    manifest = benchmark.read_json(benchmark.ROOT / benchmark.MANIFESTS[split])
    targets = manifest.get("targets")
    if (
        manifest.get("status") != "FROZEN"
        or not isinstance(targets, list)
        or not targets
        or benchmark.sha256_bytes(benchmark.canonical_bytes(targets))
        != manifest.get("target_set_sha256")
        or [row.get("order_index") for row in targets]
        != list(range(len(targets)))
    ):
        raise ValueError("frozen resume target manifest differs")
    target_ids = [
        row.get("target_id") if isinstance(row, dict) else None
        for row in targets
    ]
    if (
        any(not isinstance(value, str) or not value for value in target_ids)
        or len(set(target_ids)) != len(target_ids)
    ):
        raise ValueError("frozen resume target identities differ")
    if split == "development":
        stream_plan = [
            *(
                (f"M2-{candidate_id}", "M2")
                for candidate_id in benchmark.CANDIDATE_IDS
            ),
            ("M0", "M0"),
            ("M1", "M1"),
        ]
        canary = benchmark.read_json(
            execution_root / benchmark.PROTOCOL_CANARY_RELATIVE_PATH
        )
        hard_cap = benchmark.scientific_caps_after_protocol_canary(
            approval["hard_cap"],
            canary,
            expected_approval_sha256=approval["approval_artifact_sha256"],
        )
    else:
        stream_plan = [(arm, arm) for arm in benchmark.ARMS]
        hard_cap = approval["hard_cap"]
    cost = benchmark.read_json(
        benchmark.ROOT / "configs/trimem_v1/cost_plan.json"
    )
    tasks, rows, task_order_hash = _validated_cached_task_plan(
        benchmark,
        split=split,
        frozen_targets=targets,
    )
    images, _support = benchmark.image_entries(require_benchmark=True)
    if any(str(row.get("instance_id")) not in images for row in targets):
        raise ValueError("one or more frozen resume images are absent")
    model_lock = benchmark.read_json(
        benchmark.ROOT / "configs/trimem_v1/model_lock.json"
    )
    official_preflight = benchmark.load_official_harness_loader_preflight()
    harnesses = _validated_local_harnesses(benchmark)
    benchmark.validate_preflight_harness_root_binding(
        official_preflight, harnesses
    )
    for stream_id, _runtime_arm in stream_plan:
        experiment_id = (
            "trimemv1-"
            + str(approval["git_head"])[:12]
            + "-"
            + re.sub(r"[^a-z0-9-]", "-", stream_id.lower())
        )
        _validated_identity_seed(
            benchmark,
            execution_root=execution_root,
            experiment_id=experiment_id,
            stream_id=stream_id,
            tasks=tasks,
        )
    approval_raw = approval_file.resolve(strict=True).read_bytes()
    if benchmark.sha256_bytes(approval_raw) != approval["approval_artifact_sha256"]:
        raise ValueError("resume approval bytes changed")
    restricted_approval = _secure_existing_path(
        execution_root,
        execution_root / "restricted-external-approval.json",
        directory=False,
        label="restricted resume approval",
    )
    if restricted_approval.read_bytes() != approval_raw:
        raise ValueError("retained resume approval differs")
    expected_public = {
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "approved_request_sha256": approval["approved_request_sha256"],
        "approved_workflow_run_id": approval["approved_workflow_run_id"],
        "approved_workflow_run_attempt": approval[
            "approved_workflow_run_attempt"
        ],
        "freeze_sha256": approval["freeze_sha256"],
        "git_head": approval["git_head"],
        "phase": approval["phase"],
    }
    if split == "development":
        expected_public["source_head"] = approval["source_head"]
    public_approval = _secure_existing_path(
        execution_root,
        execution_root / "external-approval-evidence.json",
        directory=False,
        label="public resume approval evidence",
    )
    if benchmark.read_json(public_approval) != expected_public:
        raise ValueError("public resume approval evidence differs")
    return {
        "approval": dict(approval),
        "approval_digest": approval["approval_artifact_sha256"],
        "git_head": approval["git_head"],
        "hard_cap": hard_cap,
        "pricing": cost["model_pricing"],
        "stream_plan": stream_plan,
        "targets": [dict(row) for row in targets],
        "target_ids": target_ids,
        "target_sequence_sha256": benchmark.sequence_sha256(targets),
        "tasks": tasks,
        "rows": rows,
        "task_order_hash": task_order_hash,
        "images": images,
        "model_lock": model_lock,
        "official_preflight": official_preflight,
        "harnesses": harnesses,
    }


def _durable_resume_disposition(
    execution_root: Path,
    *,
    split: str,
    approval_file: Path,
) -> str:
    """Recognize only a fully cross-checked durable continuation frontier."""

    try:
        import trimem_benchmark_run as benchmark

        authority = _validated_resume_authority(
            execution_root,
            split=split,
            approval_file=approval_file,
        )
        ledger_path = _secure_existing_path(
            execution_root,
            execution_root / "budget-ledger.json",
            directory=False,
            label="resume budget ledger",
        )
        _secure_optional_path(
            execution_root,
            execution_root / "budget-ledger.json.lock",
            directory=False,
            label="resume budget ledger lock",
        )
        ledger = benchmark.AtomicBudgetLedger(
            ledger_path,
            approval_digest=authority["approval_digest"],
            caps=authority["hard_cap"],
            pricing=authority["pricing"],
        )
        ledger_state = ledger._read()
        planned_stream_set = {
            stream_id for stream_id, _runtime_arm in authority["stream_plan"]
        }
        for root_entry in execution_root.iterdir():
            if _is_link_or_reparse(root_entry):
                return "UNKNOWN_FAILURE"
            if not root_entry.is_dir():
                continue
            if re.match(r"^[0-9]{3}-", root_entry.name):
                return "UNKNOWN_FAILURE"
            if root_entry.name in planned_stream_set:
                continue
            try:
                for child in root_entry.iterdir():
                    if _is_link_or_reparse(child):
                        return "UNKNOWN_FAILURE"
                    if child.is_dir() and re.match(r"^[0-9]{3}-", child.name):
                        return "UNKNOWN_FAILURE"
            except OSError:
                return "UNKNOWN_FAILURE"

        expected_task_directories = {
            stream_id: {
                f"{index:03d}-"
                + re.sub(r"[^A-Za-z0-9_.-]", "_", target_id)
                for index, target_id in enumerate(authority["target_ids"])
            }
            for stream_id, _runtime_arm in authority["stream_plan"]
        }
        journals: list[Path] = []
        for stream_id, expected_names in expected_task_directories.items():
            stream_root = execution_root / stream_id
            if _is_link_or_reparse(stream_root):
                return "UNKNOWN_FAILURE"
            if not stream_root.exists():
                continue
            try:
                stream_root = _secure_existing_path(
                    execution_root,
                    stream_root,
                    directory=True,
                    label="resume stream directory",
                )
                for task_dir in stream_root.iterdir():
                    if _is_link_or_reparse(task_dir) or not task_dir.is_dir():
                        return "UNKNOWN_FAILURE"
                    if task_dir.name not in expected_names:
                        return "UNKNOWN_FAILURE"
                    task_dir = _secure_existing_path(
                        execution_root,
                        task_dir,
                        directory=True,
                        label="resume task directory",
                    )
                    journal_path = task_dir / "cell-commit-journal.json"
                    if _is_link_or_reparse(journal_path) or not journal_path.is_file():
                        # An unjournaled task footprint cannot prove whether an
                        # external call already crossed its send boundary.
                        return "UNKNOWN_FAILURE"
                    journals.append(
                        _secure_existing_path(
                            execution_root,
                            journal_path,
                            directory=False,
                            label="resume cell-commit journal",
                        )
                    )
            except (OSError, ValueError):
                return "UNKNOWN_FAILURE"
        journals.sort()
        if not journals:
            return "UNKNOWN_FAILURE"
        grouped: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
        journal_task_keys: set[str] = set()
        incomplete: list[tuple[Path, dict[str, Any]]] = []
        stream_authorities: dict[str, dict[str, Any]] = {}
        completed_digests: dict[tuple[str, int], str] = {}
        prepared_payloads: dict[tuple[str, int], dict[str, Any]] = {}
        terminal_lifecycle_states: dict[tuple[str, int], dict[str, Any]] = {}
        checkpoint_workspace_states: dict[
            tuple[str, int], dict[str, Any]
        ] = {}
        for path in journals:
            _secure_existing_path(
                execution_root,
                path.parent,
                directory=True,
                label="resume task directory",
            )
            row = benchmark.CellCommitJournal.read_verified(path)
            binding = row["binding"]
            relative = path.resolve().relative_to(execution_root.resolve())
            if len(relative.parts) != 3:
                return "UNKNOWN_FAILURE"
            stream_directory, task_directory, filename = relative.parts
            safe_target = re.sub(
                r"[^A-Za-z0-9_.-]", "_", binding["target_id"]
            )
            if (
                filename != "cell-commit-journal.json"
                or stream_directory != binding["stream_id"]
                or task_directory
                != f"{binding['expected_cursor']:03d}-{safe_target}"
                or binding["task_arm_key"]
                != (
                    f"{binding['stream_id']}:{binding['arm']}:"
                    f"{binding['target_id']}"
                )
                or binding["task_arm_key"] in journal_task_keys
            ):
                return "UNKNOWN_FAILURE"
            stream_plan = dict(authority["stream_plan"])
            expected_targets = authority["target_ids"]
            expected_cursor = binding["expected_cursor"]
            if (
                binding["stream_id"] not in stream_plan
                or binding["arm"] != stream_plan[binding["stream_id"]]
                or expected_cursor >= len(expected_targets)
                or binding["target_id"] != expected_targets[expected_cursor]
            ):
                return "UNKNOWN_FAILURE"
            stream_id = str(binding["stream_id"])
            runtime_arm = str(binding["arm"])
            task = authority["tasks"][expected_cursor]
            if task.task_id != binding["target_id"]:
                return "UNKNOWN_FAILURE"
            stream_authority = stream_authorities.get(stream_id)
            if stream_authority is None:
                selected_candidate = _selected_candidate_for_stream(
                    benchmark,
                    execution_root=execution_root,
                    split=split,
                    stream_id=stream_id,
                )
                stream_authority = _stream_static_authority(
                    benchmark,
                    authority,
                    execution_root,
                    split=split,
                    stream_id=stream_id,
                    runtime_arm=runtime_arm,
                    selected_candidate_id=selected_candidate,
                )
                stream_authorities[stream_id] = stream_authority
            journal_task_keys.add(binding["task_arm_key"])
            grader_result = benchmark._validated_task_grader_result(path.parent)
            if (
                benchmark.sha256_bytes(benchmark.canonical_bytes(grader_result))
                != binding["grader_result_sha256"]
            ):
                return "UNKNOWN_FAILURE"
            expected_result_path = path.parent / f"{safe_target}.result.json"
            secured_result_path = _secure_optional_path(
                execution_root,
                expected_result_path,
                directory=False,
                label="resume canonical cell result",
            )
            if secured_result_path is not None:
                journal = benchmark.CellCommitJournal(path, binding)
                result_record = journal.verify_result(
                    secured_result_path, grader_result=grader_result
                )
            elif row["status"] == "PREPARED":
                result_record = row["result_record"]
            else:
                return "UNKNOWN_FAILURE"
            if (
                result_record.get("arm") != binding["stream_id"]
                or result_record.get("runtime_arm") != binding["arm"]
                or result_record.get("target_id") != binding["target_id"]
                or result_record.get("sequence_index") != expected_cursor
                or result_record.get("sequence_sha256")
                != authority["target_sequence_sha256"]
                or result_record.get("execution_lock_hash")
                != stream_authority["execution_lock_hash"]
                or result_record.get("namespace")
                != stream_authority["namespace"]
                or result_record.get("identity_seed_digest")
                != stream_authority["identity_seed_digest"]
                or result_record.get("runtime_lock_sha256")
                != stream_authority["runtime_lock_sha256"]
                or result_record.get("m2_policy_manifest_sha256")
                != stream_authority["m2_policy_manifest_sha256"]
                or result_record.get("selected_prompt_candidate_id")
                != stream_authority["selected_prompt_candidate_id"]
                or result_record.get("workspace_factory_hash")
                != stream_authority["workspace_factory_hash"]
                or result_record.get("actual_usd")
                != benchmark.actual_usd_for_accounting(
                    result_record.get("actual_accounting", {}),
                    authority["pricing"],
                )
            ):
                return "UNKNOWN_FAILURE"
            target = authority["targets"][expected_cursor]
            image = stream_authority["images"].get(
                str(target.get("instance_id"))
            )
            if (
                not isinstance(image, Mapping)
                or result_record.get("expected_image_digest")
                != image.get("expected_digest")
                or result_record.get("observed_image_digest")
                != image.get("expected_digest")
                or grader_result.get("container_digest") != image.get("image")
                or benchmark.observed_target_digest(
                    benchmark.GradeResult(**grader_result)
                )
                != image.get("expected_digest")
            ):
                return "UNKNOWN_FAILURE"
            checkout_root = str(
                stream_authority["workspace_factory"].checkout_roots[
                    task.task_id
                ]
            )
            expected_target = {
                **dict(target),
                "repository": task.repository,
                "workspace_checkout_root": checkout_root,
                "task_config_sha256": benchmark.task_configuration_sha256(task),
            }
            benchmark.validate_cell_session_result_against_done_checkpoint(
                path.parent,
                row,
                result_record,
                grader_result=grader_result,
                expected_target=expected_target,
            )
            session_result = row.get("session_result")
            if not isinstance(session_result, Mapping):
                return "UNKNOWN_FAILURE"
            expected_run_id = re.sub(
                r"[^A-Za-z0-9_-]", "_", f"{task.task_id}-{stream_id}"
            )
            if session_result.get("run_id") != expected_run_id:
                return "UNKNOWN_FAILURE"
            agent_hashes = result_record.get("agent_config_hashes")
            if not isinstance(agent_hashes, Mapping):
                return "UNKNOWN_FAILURE"
            expected_model_hash = benchmark.sha256_bytes(
                benchmark.canonical_bytes(
                    {
                        "execution_lock_hash": stream_authority[
                            "execution_lock_hash"
                        ],
                        "primary_model": authority["model_lock"].get(
                            "primary_model"
                        ),
                    }
                )
            )
            expected_grader_hash = benchmark.sha256_bytes(
                benchmark.canonical_bytes(
                    {
                        "execution_lock_hash": stream_authority[
                            "execution_lock_hash"
                        ],
                        "target": target,
                        "source_row_sha256": target["source_row_sha256"],
                        "grader_image": image,
                    }
                )
            )
            lifecycle_hash = (
                stream_authority["m2_policy_manifest_sha256"]
                if runtime_arm == "M2"
                else (
                    benchmark.production_v03_lifecycle_factory.configuration_hash
                    if runtime_arm == "M1"
                    else benchmark.sha256_bytes(
                        (
                            "enterprise_memory.trimem.agent_runtime."
                            "NullExperienceLifecycle"
                        ).encode("utf-8")
                    )
                )
            )
            if isinstance(lifecycle_hash, str):
                lifecycle_hash = lifecycle_hash.removeprefix("sha256:")
            if (
                set(agent_hashes) != benchmark._AGENT_CONFIG_HASH_FIELDS
                or agent_hashes.get("runtime")
                != stream_authority["runtime_lock_sha256"].removeprefix(
                    "sha256:"
                )
                or agent_hashes.get("task")
                != expected_target["task_config_sha256"]
                or agent_hashes.get("model") != expected_model_hash
                or agent_hashes.get("grader") != expected_grader_hash
                or agent_hashes.get("workspace")
                != stream_authority["workspace_factory_hash"]
                or agent_hashes.get("memory_controller")
                != stream_authority["memory_controller_hash"]
                or agent_hashes.get("lifecycle") != lifecycle_hash
            ):
                return "UNKNOWN_FAILURE"
            checkpoint_root = _secure_existing_path(
                execution_root,
                path.parent / "agent-checkpoints",
                directory=True,
                label="resume agent-checkpoint directory",
            )
            checkpoint_name = str(session_result.get("run_id"))
            checkpoint_entries = list(checkpoint_root.iterdir())
            if any(
                _is_link_or_reparse(entry) or not entry.is_file()
                for entry in checkpoint_entries
            ) or {entry.name for entry in checkpoint_entries} != {
                f"{expected_run_id}.json",
                f"{expected_run_id}.sha256",
            }:
                return "UNKNOWN_FAILURE"
            _secure_existing_path(
                execution_root,
                checkpoint_root / f"{checkpoint_name}.json",
                directory=False,
                label="resume terminal agent checkpoint",
            )
            _secure_existing_path(
                execution_root,
                checkpoint_root / f"{checkpoint_name}.sha256",
                directory=False,
                label="resume terminal agent checkpoint sidecar",
            )
            terminal_checkpoint = benchmark.FileCheckpointStore(
                checkpoint_root
            ).load(
                checkpoint_name,
                required_config_hashes=agent_hashes,
                required_evidence_hash=str(session_result.get("evidence_tail_hash")),
            )
            from enterprise_memory.trimem.production_runtime import _sha256

            completed_digests[(stream_id, expected_cursor)] = _sha256(
                {
                    "task_id": task.task_id,
                    "arm": runtime_arm,
                    "sequence_index": expected_cursor,
                    "result": dict(session_result),
                    "controller_state": dict(
                        terminal_checkpoint.memory_controller_state
                    ),
                }
            )
            terminal_lifecycle_states[(stream_id, expected_cursor)] = dict(
                terminal_checkpoint.lifecycle_state
            )
            checkpoint_workspace_states[(stream_id, expected_cursor)] = dict(
                terminal_checkpoint.workspace_state
            )
            prepared_path = _secure_existing_path(
                execution_root,
                path.parent / "prepared-task-checkpoint.json",
                directory=False,
                label="resume prepared-task checkpoint",
            )
            prepared = benchmark.read_json(prepared_path)
            prepared_payload = prepared.get("payload")
            prepared_expected = {
                "schema": "trimem/benchmark-prepared-task-checkpoint/1.0",
                "namespace": stream_authority["namespace"],
                "experiment_id": stream_authority["experiment_id"],
                "split": split,
                "arm_id": runtime_arm,
                "task_order_hash": stream_authority["task_order_hash"],
                "config_hash": stream_authority["config_hash"],
                "run_nonce": stream_authority["run_nonce"],
                "sequence_index": expected_cursor,
                "task_id": task.task_id,
            }
            if (
                set(prepared) != {"payload", "digest"}
                or not isinstance(prepared_payload, Mapping)
                or set(prepared_payload) != _PREPARED_TASK_FIELDS
                or prepared.get("digest")
                != "sha256:"
                + benchmark.sha256_bytes(
                    benchmark.canonical_bytes(prepared_payload)
                )
                or any(
                    prepared_payload.get(name) != value
                    for name, value in prepared_expected.items()
                )
                or not isinstance(prepared_payload.get("lifecycle_state"), Mapping)
            ):
                return "UNKNOWN_FAILURE"
            _validate_namespace_evidence(
                benchmark,
                namespace=stream_authority["namespace"],
                owner_user_id=task.user_id,
                canonical_evidence=prepared_payload.get("canonical_evidence"),
                qdrant_evidence=prepared_payload.get("qdrant_evidence"),
                receipt_evidence=prepared_payload.get(
                    "lifecycle_receipt_evidence"
                ),
            )
            prepared_payloads[(stream_id, expected_cursor)] = dict(
                prepared_payload
            )
            task_row = ledger_state["task_arms"].get(binding["task_arm_key"])
            if not isinstance(task_row, dict) or (
                task_row.get("reservation_id")
                != binding["task_arm_reservation_id"]
            ):
                return "UNKNOWN_FAILURE"
            request_rows = _validate_task_model_journals(
                benchmark,
                execution_root=execution_root,
                task_dir=path.parent,
                stream_id=stream_id,
                task_arm_key=binding["task_arm_key"],
                ledger_requests=ledger_state["requests"],
                expected_model=str(
                    authority["model_lock"]["primary_model"]["model_id"]
                ),
            )
            if row["status"] in {"PREPARED", "RESULT_WRITTEN"}:
                if task_row.get("status") != "RESERVED":
                    return "UNKNOWN_FAILURE"
                _validate_result_against_reserved_task_arm(
                    benchmark,
                    record=result_record,
                    task_row=task_row,
                    task_arm_key=binding["task_arm_key"],
                    request_rows=request_rows,
                )
            else:
                if task_row.get("status") != "CELL_TERMINAL":
                    return "UNKNOWN_FAILURE"
                benchmark._validate_cell_result_ledger_pair(
                    result_record,
                    task_row,
                    task_arm_key=binding["task_arm_key"],
                )
                if request_rows or result_record["actual_accounting"].get(
                    "model_gateway_calls"
                ) or result_record.get("failure_metadata") is not None:
                    benchmark.validate_result_request_statuses(
                        result_record, list(request_rows)
                    )
            grouped.setdefault(binding["stream_id"], []).append((path, row))
            if row.get("status") != "COMMITTED":
                incomplete.append((path, row))
        if len(incomplete) > 1:
            return "UNKNOWN_FAILURE"
        if set(ledger_state["task_arms"]) != journal_task_keys:
            return "UNKNOWN_FAILURE"
        planned_stream_ids = [row[0] for row in authority["stream_plan"]]
        observed_stream_ids = [
            stream_id for stream_id in planned_stream_ids if stream_id in grouped
        ]
        if (
            set(grouped) != set(observed_stream_ids)
            or observed_stream_ids
            != planned_stream_ids[: len(observed_stream_ids)]
        ):
            return "UNKNOWN_FAILURE"
        _validate_resume_checkout_suffix(
            benchmark,
            split=split,
            authority=authority,
            stream_authorities=stream_authorities,
            grouped=grouped,
            checkpoint_workspace_states=checkpoint_workspace_states,
        )
        for future_stream in planned_stream_ids[len(observed_stream_ids) :]:
            future_paths = (
                execution_root / f"{future_stream}.session-identity.json",
                execution_root / f"{future_stream}.freshness.json",
                execution_root / f"{future_stream}.stream-checkpoint.json",
                execution_root / f"{future_stream}.stream-checkpoint.sha256",
                execution_root
                / f"{future_stream}.development-finalization-binding.json",
                execution_root
                / f"{future_stream}.pre-development-finalization-checkpoint.json",
                execution_root
                / f"{future_stream}.post-development-frozen-checkpoint.json",
            )
            if any(path.exists() or path.is_symlink() for path in future_paths):
                return "UNKNOWN_FAILURE"
        for prior_stream in observed_stream_ids[:-1]:
            prior_entries = grouped[prior_stream]
            if (
                len(prior_entries) != len(authority["target_ids"])
                or any(row["status"] != "COMMITTED" for _path, row in prior_entries)
            ):
                return "UNKNOWN_FAILURE"
        for stream_id, entries in grouped.items():
            ordered = sorted(entries, key=lambda item: item[1]["binding"]["expected_cursor"])
            indices = [row["binding"]["expected_cursor"] for _path, row in ordered]
            if indices != list(range(len(indices))):
                return "UNKNOWN_FAILURE"
            statuses = [row["status"] for _path, row in ordered]
            if any(status != "COMMITTED" for status in statuses[:-1]):
                return "UNKNOWN_FAILURE"
            last_path, last = ordered[-1]
            prior_cursor = len(statuses) - 1
            last_status = last["status"]
            checkpoint_path = execution_root / f"{stream_id}.stream-checkpoint.json"
            sidecar_path = execution_root / f"{stream_id}.stream-checkpoint.sha256"
            finalization_binding_path = (
                benchmark._development_finalization_binding_path(
                    execution_root, stream_id
                )
            )
            pre_finalization_checkpoint_path = (
                benchmark._development_pre_finalization_checkpoint_path(
                    execution_root, stream_id
                )
            )
            finalization_binding = _secure_optional_path(
                execution_root,
                finalization_binding_path,
                directory=False,
                label="resume development-finalization binding",
            )
            pre_finalization_checkpoint = _secure_optional_path(
                execution_root,
                pre_finalization_checkpoint_path,
                directory=False,
                label="resume pre-development-finalization checkpoint",
            )
            checkpoint_file = _secure_optional_path(
                execution_root,
                checkpoint_path,
                directory=False,
                label="resume stream checkpoint",
            )
            sidecar_file = _secure_optional_path(
                execution_root,
                sidecar_path,
                directory=False,
                label="resume stream checkpoint sidecar",
            )
            if (checkpoint_file is None) != (sidecar_file is None):
                return "UNKNOWN_FAILURE"
            if checkpoint_file is None:
                if (
                    finalization_binding is not None
                    or pre_finalization_checkpoint is not None
                ):
                    return "UNKNOWN_FAILURE"
                if prior_cursor != 0 or last_status not in {
                    "PREPARED",
                    "RESULT_WRITTEN",
                    "LEDGER_TERMINAL",
                }:
                    return "UNKNOWN_FAILURE"
                continue
            checkpoint = benchmark.load_arm_checkpoint(execution_root, stream_id)
            payload = checkpoint.get("payload")
            if not isinstance(payload, dict):
                return "UNKNOWN_FAILURE"
            stream_state = (
                payload.get("stream_state")
            )
            if (
                stream_state != "DEVELOPMENT_FINALIZED"
                and finalization_binding is not None
            ):
                return "UNKNOWN_FAILURE"
            if (
                stream_id in observed_stream_ids[:-1]
                and dict(authority["stream_plan"])[stream_id] == "M2"
                and stream_state != "DEVELOPMENT_FINALIZED"
            ):
                return "UNKNOWN_FAILURE"
            if stream_state == "DEVELOPMENT_FINALIZED":
                cursor = len(statuses)
                cursor_shape_valid = (
                    last_status == "COMMITTED"
                    and cursor == len(authority["target_ids"])
                    and set(payload)
                    == (
                        _PRODUCTION_TASK_STREAM_FIELDS
                        | {"final_policy_checkpoint"}
                    )
                    and payload.get("split") == "development"
                    and payload.get("next_sequence_index") == cursor + 1
                    and payload.get("arm_id") == "M2"
                    and isinstance(payload.get("final_policy_checkpoint"), dict)
                    and isinstance(payload.get("completed_task_digests"), list)
                    and len(payload["completed_task_digests"]) == cursor
                )
            else:
                if set(payload) != _PRODUCTION_TASK_STREAM_FIELDS:
                    return "UNKNOWN_FAILURE"
                cursor = payload.get("task_cursor")
                cursor_shape_valid = (
                    stream_state in {None, "TASK_STREAM"}
                    and type(cursor) is int
                    and cursor >= 0
                    and (
                        "next_sequence_index" not in payload
                        or payload.get("next_sequence_index") == cursor
                    )
                    and (
                        "completed_task_digests" not in payload
                        or (
                            isinstance(
                                payload.get("completed_task_digests"), list
                            )
                            and len(payload["completed_task_digests"]) == cursor
                        )
                    )
                )
            if pre_finalization_checkpoint is not None:
                if (
                    runtime_arm != "M2"
                    or last_status != "COMMITTED"
                    or cursor != len(authority["target_ids"])
                ):
                    return "UNKNOWN_FAILURE"
                retained_checkpoint = (
                    benchmark._load_development_pre_finalization_checkpoint(
                        execution_root,
                        stream_id,
                        last_cell=last,
                    )
                )
                if (
                    stream_state != "DEVELOPMENT_FINALIZED"
                    and retained_checkpoint != checkpoint
                ):
                    return "UNKNOWN_FAILURE"
            elif stream_state == "DEVELOPMENT_FINALIZED":
                return "UNKNOWN_FAILURE"
            expected_experiment_id = (
                "trimemv1-"
                + str(authority["git_head"])[:12]
                + "-"
                + re.sub(r"[^a-z0-9-]", "-", stream_id.lower())
            )
            stream_authority = stream_authorities[stream_id]
            expected_completed = [
                completed_digests[(stream_id, index)]
                for index in range(cursor)
            ]
            if (
                set(checkpoint) != {"payload", "digest"}
                or checkpoint.get("digest")
                != "sha256:"
                + benchmark.sha256_bytes(benchmark.canonical_bytes(payload))
                or payload.get("task_cursor") != cursor
                or not cursor_shape_valid
                or payload.get("split") != split
                or payload.get("arm_id") != dict(authority["stream_plan"])[stream_id]
                or payload.get("experiment_id") != expected_experiment_id
                or payload.get("schema")
                != "trimem/benchmark-arm-checkpoint/1.0"
                or payload.get("namespace") != stream_authority["namespace"]
                or payload.get("task_order_hash")
                != stream_authority["task_order_hash"]
                or payload.get("config_hash")
                != stream_authority["config_hash"]
                or payload.get("run_nonce") != stream_authority["run_nonce"]
                or payload.get("completed_task_digests")
                != expected_completed
                or not isinstance(payload.get("lifecycle_state"), Mapping)
            ):
                return "UNKNOWN_FAILURE"
            _validate_namespace_evidence(
                benchmark,
                namespace=stream_authority["namespace"],
                owner_user_id=authority["tasks"][0].user_id,
                canonical_evidence=payload.get("canonical_evidence"),
                qdrant_evidence=payload.get("qdrant_evidence"),
                receipt_evidence=payload.get("lifecycle_receipt_evidence"),
            )
            if (
                stream_state != "DEVELOPMENT_FINALIZED"
                and cursor > 0
                and dict(authority["stream_plan"])[stream_id] in {
                    "M1",
                    "M2",
                }
            ):
                lifecycle_state = payload.get("lifecycle_state")
                if (
                    set(lifecycle_state) != {"persistence", "lifecycle"}
                    or lifecycle_state.get("lifecycle")
                    != terminal_lifecycle_states[(stream_id, cursor - 1)]
                ):
                    return "UNKNOWN_FAILURE"
            prepared_at_cursor = prepared_payloads.get((stream_id, cursor))
            if prepared_at_cursor is not None and any(
                payload.get(name) != prepared_at_cursor.get(name)
                for name in (
                    "canonical_evidence",
                    "qdrant_evidence",
                    "lifecycle_receipt_evidence",
                )
            ):
                return "UNKNOWN_FAILURE"
            if stream_state == "DEVELOPMENT_FINALIZED":
                benchmark.load_development_finalization_binding(
                    execution_root,
                    stream_id,
                    last_cell_journal_path=last_path,
                )
                from enterprise_memory.trimem.policy import DoubleDQNMemoryPolicy

                restored_policy = DoubleDQNMemoryPolicy.from_frozen_checkpoint(
                    payload["final_policy_checkpoint"]
                )
                if restored_policy.frozen is not True:
                    return "UNKNOWN_FAILURE"
                selected_checkpoint_path = (
                    execution_root
                    / f"{stream_id}.post-development-frozen-checkpoint.json"
                )
                selected_checkpoint = _secure_optional_path(
                    execution_root,
                    selected_checkpoint_path,
                    directory=False,
                    label="resume selected policy checkpoint",
                )
                if selected_checkpoint is not None and benchmark.read_json(
                    selected_checkpoint
                ) != payload["final_policy_checkpoint"]:
                    return "UNKNOWN_FAILURE"
            else:
                if last_status in {"PREPARED", "RESULT_WRITTEN"}:
                    expected_cursor = prior_cursor
                elif last_status == "LEDGER_TERMINAL":
                    if cursor not in {prior_cursor, prior_cursor + 1}:
                        return "UNKNOWN_FAILURE"
                    expected_cursor = cursor
                else:
                    expected_cursor = prior_cursor + 1
                if cursor != expected_cursor:
                    return "UNKNOWN_FAILURE"
                if cursor > 0:
                    checkpoint_row = ordered[cursor - 1][1]
                    checkpoint_status = checkpoint_row["status"]
                    if checkpoint_status in {"CURSOR_ADVANCED", "COMMITTED"}:
                        observed_checkpoint_sha256 = benchmark.sha256_bytes(
                            benchmark.canonical_bytes(checkpoint)
                        )
                        if (
                            checkpoint_row.get("stream_checkpoint_sha256")
                            != observed_checkpoint_sha256
                        ):
                            return "UNKNOWN_FAILURE"
                    elif not (
                        checkpoint_status == "LEDGER_TERMINAL"
                        and cursor == len(statuses)
                        and last_path == ordered[cursor - 1][0]
                    ):
                        return "UNKNOWN_FAILURE"
        return (
            "RESUME_SAFE_CELL_COMMIT_JOURNAL"
            if incomplete
            else "RESUME_SAFE_DURABLE_SUFFIX"
        )
    except Exception:
        return "UNKNOWN_FAILURE"


def _close_ambiguous_grader_processes(execution_root: Path) -> int:
    """Conservatively seal killed grader children without invoking a grader."""

    import trimem_benchmark_run as benchmark

    _secure_existing_path(
        execution_root,
        execution_root,
        directory=True,
        label="grader reconciliation execution root",
    )
    paths = sorted(
        execution_root.glob("*/*/terminal-journal/grader/*.json")
    )
    ambiguous: list[Path] = []
    for path in paths:
        secured = _secure_existing_path(
            execution_root,
            path,
            directory=False,
            label="grader reconciliation journal",
        )
        _secure_existing_path(
            execution_root,
            secured.parent,
            directory=True,
            label="grader reconciliation journal directory",
        )
        _secure_existing_path(
            execution_root,
            secured.parent.parent,
            directory=True,
            label="grader reconciliation terminal directory",
        )
        row = benchmark.TerminalInvocationJournal._validated_grader_row(secured)
        if row.get("status") in {
            "GRADER_PROCESS_STARTED",
            "GRADER_CONTAINER_STARTED",
        }:
            ambiguous.append(secured)
    for path in ambiguous:
        benchmark.close_ambiguous_grader_journal(path)
    return len(ambiguous)


def run_with_one_resume(split: str, approval_file: Path) -> int:
    output = ROOT / "artifacts/trimem_v1/benchmark_exec" / split / "driver-evidence"
    base = [
        sys.executable,
        str(ROOT / "scripts/trimem_benchmark_run.py"),
        "--split", split,
        "--approval-file", str(approval_file.resolve()),
    ]
    first, first_row = _invoke(
        base, resume=False, output=output, attempt=1, split=split
    )
    attempts = [first_row]
    first_disposition = str(first_row["process_disposition"])
    try:
        reconciled_graders = _close_ambiguous_grader_processes(output.parent)
    except Exception:
        reconciled_graders = -1
    if reconciled_graders > 0:
        first_row["reported_process_disposition"] = first_disposition
        first_row["process_disposition"] = "GLOBAL_GRADER_INFRA_FAILURE"
        first_row["disposition_source"] = (
            "VERIFIED_GRADER_LIFECYCLE_RECONCILIATION"
        )
        first_row["reconciled_ambiguous_grader_processes"] = reconciled_graders
        first_disposition = "GLOBAL_GRADER_INFRA_FAILURE"
    elif reconciled_graders < 0:
        first_row["reported_process_disposition"] = first_disposition
        first_row["process_disposition"] = "GLOBAL_EVIDENCE_FAILURE"
        first_row["disposition_source"] = "GRADER_LIFECYCLE_RECONCILIATION_FAILED"
        first_disposition = "GLOBAL_EVIDENCE_FAILURE"
    elif first.returncode != 0 and first_disposition in RESUME_SAFE_DISPOSITIONS:
        durable_disposition = _durable_resume_disposition(
            output.parent,
            split=split,
            approval_file=approval_file,
        )
        if durable_disposition != first_disposition:
            first_row["reported_process_disposition"] = first_disposition
            first_row["process_disposition"] = "GLOBAL_EVIDENCE_FAILURE"
            first_row["disposition_source"] = (
                "REPORTED_RESUME_DISPOSITION_FAILED_DURABLE_VERIFICATION"
            )
            first_disposition = "GLOBAL_EVIDENCE_FAILURE"
        else:
            first_row["disposition_source"] = (
                "RUNNER_STDOUT_AND_VERIFIED_DURABLE_LOCAL_EVIDENCE"
            )
    first_row.setdefault("disposition_source", "RUNNER_STDOUT")
    resume_eligible = (
        first.returncode != 0 and first_disposition in RESUME_SAFE_DISPOSITIONS
    )
    resume_started = False
    second_exit_code: int | None = None
    first_succeeded = first.returncode == 0 and first_disposition == "SUCCESS"
    if first_succeeded:
        resume_reason = "FIRST_PROCESS_SUCCEEDED"
        final_code = 0
    elif first.returncode == 0:
        resume_reason = "FIRST_PROCESS_SUCCESS_MARKER_INVALID"
        final_code = 1
    elif not resume_eligible:
        resume_reason = "FIRST_DISPOSITION_NOT_RESUME_SAFE"
        final_code = first.returncode
    else:
        resume_reason = first_disposition
        resume_started = True
        second, second_row = _invoke(
            base, resume=True, output=output, attempt=2, split=split
        )
        attempts.append(second_row)
        second_exit_code = int(second.returncode)
        second_disposition = str(second_row["process_disposition"])
        try:
            reconciled_graders = _close_ambiguous_grader_processes(
                output.parent
            )
        except Exception:
            reconciled_graders = -1
        if reconciled_graders > 0:
            second_row["reported_process_disposition"] = second_disposition
            second_row["process_disposition"] = (
                "GLOBAL_GRADER_INFRA_FAILURE"
            )
            second_row["disposition_source"] = (
                "VERIFIED_GRADER_LIFECYCLE_RECONCILIATION"
            )
            second_row["reconciled_ambiguous_grader_processes"] = (
                reconciled_graders
            )
        elif reconciled_graders < 0:
            second_row["reported_process_disposition"] = second_disposition
            second_row["process_disposition"] = "GLOBAL_EVIDENCE_FAILURE"
            second_row["disposition_source"] = (
                "GRADER_LIFECYCLE_RECONCILIATION_FAILED"
            )
        else:
            second_row.setdefault("disposition_source", "RUNNER_STDOUT")
        second_succeeded = (
            second.returncode == 0
            and second_row["process_disposition"] == "SUCCESS"
        )
        final_code = 0 if second_succeeded else max(1, int(second.returncode))
    manifest = {
        "schema": "trimem/benchmark-process-attempts/2.0",
        "split": split,
        "same_workflow_run_and_attempt_required_by_external_approval": True,
        "maximum_resume_attempts": 1,
        "first_exit_code": int(first.returncode),
        "first_disposition": first_disposition,
        "resume_eligible": resume_eligible,
        "resume_started": resume_started,
        "resume_reason": resume_reason,
        "second_process_exit_code": second_exit_code,
        "attempts": attempts,
        "status": "PASS" if final_code == 0 else "FAIL",
    }
    (output / "attempts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return 0 if final_code == 0 else max(1, final_code)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("development", "heldout"), required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    args = parser.parse_args()
    return run_with_one_resume(args.split, args.approval_file)


if __name__ == "__main__":
    raise SystemExit(main())
