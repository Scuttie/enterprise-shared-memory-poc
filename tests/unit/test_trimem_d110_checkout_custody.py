from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.git_workspace import GitCheckoutWorkspace
from enterprise_memory.trimem.workspace import ToolExecutionError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_run_with_resume as resume_driver
import trimem_benchmark_run as benchmark_run
import trimem_harness_lock as harness_lock
import trimem_official_grader as official_grader
import trimem_official_harness_loader_preflight as loader_preflight


def _git(repository: Path, *arguments: str) -> str:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _committed_checkout(path: Path) -> str:
    path.mkdir(parents=True)
    completed = subprocess.run(
        ["git", "init", "--quiet", str(path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    assert completed.returncode == 0, completed.stderr
    (path / "tracked.txt").write_text("frozen\n", encoding="utf-8")
    _git(path, "add", "--", "tracked.txt")
    _git(
        path,
        "-c",
        "user.name=TriMem Test",
        "-c",
        "user.email=trimem-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "frozen checkout",
    )
    return _git(path, "rev-parse", "--verify", "HEAD")


def _committed_eol_checkout(
    path: Path,
    files: dict[str, bytes],
) -> str:
    path.mkdir(parents=True)
    completed = subprocess.run(
        ["git", "init", "--quiet", str(path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
        },
    )
    assert completed.returncode == 0, completed.stderr
    suffixes = sorted({Path(relative).suffix for relative in files})
    attributes = b"".join(
        f"*{suffix} text eol=crlf\n".encode("ascii") for suffix in suffixes
    )
    (path / ".gitattributes").write_bytes(attributes)
    for relative, raw in files.items():
        candidate = path / relative
        candidate.parent.mkdir(parents=True, exist_ok=True)
        assert b"\r" not in raw and b"\n" in raw
        candidate.write_bytes(raw)
    _git(path, "add", "--", ".gitattributes", *sorted(files))
    _git(
        path,
        "-c",
        "user.name=TriMem Test",
        "-c",
        "user.email=trimem-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "frozen eol checkout",
    )
    commit = _git(path, "rev-parse", "--verify", "HEAD")
    for relative, raw in files.items():
        (path / relative).write_bytes(raw.replace(b"\n", b"\r\n"))
    return commit


def test_two_swe_cells_keep_shared_harness_pristine_and_outputs_task_local(
    tmp_path: Path,
) -> None:
    harness = tmp_path / "pinned-swe-harness"
    commit = _committed_checkout(harness)
    row = {
        "instance_id": "owner__repo-1",
        "repo": "owner/repo",
        "base_commit": "b" * 40,
    }
    target = official_grader.FrozenOfficialTarget(
        target_id="swebench_verified--owner__repo-1",
        benchmark_id="swebench_verified",
        instance_id="owner__repo-1",
        repository="owner/repo",
        base_commit="b" * 40,
        dataset_revision="c" * 40,
        source_row_sha256=official_grader.canonical_row_hash(row),
        image="owner/repo@sha256:" + "d" * 64,
        harness_image_tag="owner/repo:latest",
        harness_revision=official_grader.SWE_HARNESS_REVISION,
    )

    for index in range(2):
        run_root = tmp_path / f"task-{index}" / "official-grader"
        invocation = official_grader.build_harness_invocation(
            target,
            row=row,
            patch="diff --git a/a b/a\n",
            harness_root=harness,
            run_root=run_root,
            model_name="trimem-v1-M2",
        )
        assert invocation.cwd == run_root
        assert harness not in invocation.test_output_path.parents
        log_root = invocation.test_output_path.parent
        log_root.mkdir(parents=True)
        for name in (
            "run_instance.log",
            "patch.diff",
            "eval.sh",
            "test_output.txt",
            "report.json",
        ):
            (log_root / name).write_bytes(b"retained task-local evidence\n")
        (log_root.parents[1] / "run.json").write_bytes(b"{}\n")
        harness_lock.validate_pristine_checkout(harness.absolute(), commit)

    assert not (harness / "logs").exists()


def test_fresh_checkout_materialization_restores_exact_git_blob_bytes(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "eol-checkout"
    raw = b"@echo off\necho frozen\n"
    commit = _committed_eol_checkout(checkout, {"make.bat": raw})

    with pytest.raises(
        harness_lock.HarnessLockError,
        match="differs from its frozen Git blob",
    ):
        harness_lock.validate_pristine_checkout(checkout.absolute(), commit)

    evidence = benchmark_run._materialize_exact_git_blob_checkout(
        checkout.absolute(), commit
    )

    assert (checkout / "make.bat").read_bytes() == raw
    assert evidence["schema"] == "trimem/git-blob-worktree-materialization/1.0"
    assert evidence["status"] == "PASS"
    assert evidence["commit"] == commit
    assert evidence["regular_blob_count"] == 2
    assert evidence["normalized_paths"] == ["make.bat"]
    assert evidence["normalized_path_count"] == 1
    assert evidence["normalized_paths_sha256"] == benchmark_run.sha256_bytes(
        benchmark_run.canonical_bytes(["make.bat"])
    )
    assert benchmark_run._valid_checkout_materialization_evidence(
        evidence,
        expected_commit=commit,
    )
    harness_lock.validate_pristine_checkout(checkout.absolute(), commit)
    resume_driver._validate_checkout_tree_bytes(
        checkout.absolute(),
        expected_commit=commit,
    )


def test_fresh_checkout_materialization_handles_zstd_style_file_set(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "multi-eol-checkout"
    files = {
        "build/a.vcxproj": b"<Project>\n</Project>\n",
        "build/b.sln": b"header\nproject\n",
        "scripts/c.cmd": b"@echo off\necho c\n",
        "scripts/d.bat": b"@echo off\necho d\n",
    }
    commit = _committed_eol_checkout(checkout, files)

    evidence = benchmark_run._materialize_exact_git_blob_checkout(
        checkout.absolute(), commit
    )

    assert evidence["normalized_paths"] == sorted(files)
    for relative, raw in files.items():
        assert (checkout / relative).read_bytes() == raw
    harness_lock.validate_pristine_checkout(checkout.absolute(), commit)


def test_fresh_checkout_materialization_rejects_non_declared_tamper_atomically(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "tampered-eol-checkout"
    files = {
        "a.bat": b"@echo off\necho a\n",
        "b.bat": b"@echo off\necho b\n",
    }
    commit = _committed_eol_checkout(checkout, files)
    expected_checkout_a = files["a.bat"].replace(b"\n", b"\r\n")
    (checkout / "b.bat").write_bytes(b"@echo off\necho attacker\n")

    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="differ from their committed checkout transform",
    ):
        benchmark_run._materialize_exact_git_blob_checkout(
            checkout.absolute(), commit
        )

    assert (checkout / "a.bat").read_bytes() == expected_checkout_a
    assert (checkout / "b.bat").read_bytes() == b"@echo off\necho attacker\n"


def test_fresh_checkout_materialization_rejects_inventory_before_writes(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "untracked-eol-checkout"
    raw = b"@echo off\necho frozen\n"
    commit = _committed_eol_checkout(checkout, {"make.bat": raw})
    expected_checkout = raw.replace(b"\n", b"\r\n")
    (checkout / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="inventory differs before Git-blob materialization",
    ):
        benchmark_run._materialize_exact_git_blob_checkout(
            checkout.absolute(), commit
        )

    assert (checkout / "make.bat").read_bytes() == expected_checkout


def test_fresh_checkout_materialization_rejects_mutable_info_attributes(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "info-attributes-checkout"
    commit = _committed_eol_checkout(
        checkout,
        {"make.bat": b"@echo off\necho frozen\n"},
    )
    info_attributes = checkout / ".git" / "info" / "attributes"
    info_attributes.write_text("*.bat -text\n", encoding="utf-8")

    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="mutable info attributes",
    ):
        benchmark_run._materialize_exact_git_blob_checkout(
            checkout.absolute(), commit
        )


def test_exact_fresh_checkout_materialization_records_zero_transforms(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "exact-checkout"
    commit = _committed_checkout(checkout)

    evidence = benchmark_run._materialize_exact_git_blob_checkout(
        checkout.absolute(), commit
    )

    assert evidence["normalized_paths"] == []
    assert evidence["normalized_path_count"] == 0
    assert evidence["regular_blob_count"] == 1
    harness_lock.validate_pristine_checkout(checkout.absolute(), commit)


def test_prepare_checkouts_fresh_clone_uses_materialization_and_records_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    raw = b"@echo off\necho frozen\n"
    commit = _committed_eol_checkout(source, {"make.bat": raw})
    stream_root = tmp_path / "fresh-task-checkouts"
    task = SimpleNamespace(
        task_id="task-0",
        repository="example/repository",
        commit=commit,
    )
    real_runner = benchmark_run._run_hermetic_git

    def local_clone(arguments: object) -> object:
        argv = list(arguments)
        if argv[:2] == ["clone", "--no-checkout"]:
            argv[-2] = str(source)
        return real_runner(argv)

    monkeypatch.setattr(benchmark_run, "_run_hermetic_git", local_clone)
    factory, evidence = benchmark_run.prepare_checkouts(
        [task],
        [{"instance_id": "fixture-instance"}],
        {
            "fixture-instance": {
                "image": "example/image@sha256:" + "0" * 64,
            }
        },
        stream_root,
        resume=False,
    )

    checkout = factory.checkout_roots["task-0"]
    assert (checkout / "make.bat").read_bytes() == raw
    assert evidence["task-0"]["checkout_origin"] == "FRESH_CLONE"
    assert evidence["task-0"]["materialization"]["normalized_paths"] == [
        "make.bat"
    ]
    harness_lock.validate_pristine_checkout(checkout, commit)


def test_preexisting_checkout_is_never_repaired_as_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream_root = tmp_path / "preexisting-task-checkouts"
    checkout = stream_root / "task-0"
    commit = _committed_eol_checkout(
        checkout,
        {"make.bat": b"@echo off\necho frozen\n"},
    )
    task = SimpleNamespace(
        task_id="task-0",
        repository="example/repository",
        commit=commit,
    )

    def forbidden_materializer(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("an existing checkout was passed to the materializer")

    monkeypatch.setattr(
        benchmark_run,
        "_materialize_exact_git_blob_checkout",
        forbidden_materializer,
    )
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="new checkout is not exact and clean",
    ):
        benchmark_run.prepare_checkouts(
            [task],
            [{"instance_id": "fixture-instance"}],
            {
                "fixture-instance": {
                    "image": "example/image@sha256:" + "0" * 64,
                }
            },
            stream_root,
            resume=False,
        )

    assert (checkout / "make.bat").read_bytes().endswith(b"\r\n")


def _custody_case(
    tmp_path: Path,
    *,
    linked_future: bool = False,
) -> tuple[SimpleNamespace, dict[str, object], dict[str, object], Path]:
    repository_root = tmp_path / "approved-runtime"
    stream_root = (
        repository_root / ".trimem-exec" / "checkouts" / "development" / "M0"
    )
    prior_checkout = stream_root / "task-0"
    future_checkout = stream_root / "task-1"
    prior_commit = _committed_checkout(prior_checkout)

    if linked_future:
        outside_checkout = tmp_path / "escaped-future-checkout"
        future_commit = _committed_checkout(outside_checkout)
        _directory_link_or_skip(future_checkout, outside_checkout)
        factory_future = outside_checkout.resolve(strict=True)
    else:
        future_commit = _committed_checkout(future_checkout)
        factory_future = future_checkout

    tasks = [
        SimpleNamespace(task_id="task-0", commit=prior_commit),
        SimpleNamespace(task_id="task-1", commit=future_commit),
    ]
    authority: dict[str, object] = {
        "stream_plan": [("M0", "M0")],
        "tasks": tasks,
    }
    stream_authorities: dict[str, object] = {
        "M0": {
            "workspace_factory": SimpleNamespace(
                checkout_roots={
                    "task-0": prior_checkout,
                    "task-1": factory_future,
                }
            )
        }
    }
    benchmark = SimpleNamespace(ROOT=repository_root)
    return benchmark, authority, stream_authorities, future_checkout


def _validate(
    benchmark: SimpleNamespace,
    authority: dict[str, object],
    stream_authorities: dict[str, object],
    checkpoint_workspace_states: dict[tuple[str, int], dict[str, object]]
    | None = None,
) -> None:
    if checkpoint_workspace_states is None:
        prior_task = authority["tasks"][0]
        prior_checkout = stream_authorities["M0"][
            "workspace_factory"
        ].checkout_roots[prior_task.task_id]
        prior_state = GitCheckoutWorkspace(
            prior_checkout,
            base_commit=prior_task.commit,
        ).checkpoint_state()
        checkpoint_workspace_states = {("M0", 0): dict(prior_state)}
    resume_driver._validate_resume_checkout_suffix(
        benchmark,
        split="development",
        authority=authority,
        stream_authorities=stream_authorities,
        grouped={"M0": [(Path("committed-cell-journal.json"), {})]},
        checkpoint_workspace_states=checkpoint_workspace_states,
    )


def _harness_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    linked_harness: bool = False,
) -> tuple[SimpleNamespace, Path]:
    repository_root = tmp_path / "approved-harness-runtime"
    harness_root = repository_root / ".trimem-exec" / "harnesses"
    harness_root.mkdir(parents=True)
    harness = harness_root / "pinned-harness"
    if linked_harness:
        outside = tmp_path / "escaped-harness"
        revision = _committed_checkout(outside)
        _git(
            outside,
            "remote",
            "add",
            "origin",
            "https://github.com/example/pinned-harness",
        )
        _directory_link_or_skip(harness, outside)
    else:
        revision = _committed_checkout(harness)
        _git(
            harness,
            "remote",
            "add",
            "origin",
            "https://github.com/example/pinned-harness",
        )
    rows = [
        {
            "benchmark_ids": ["fixture-benchmark"],
            "checkout_key": "pinned-harness",
            "dependency_declarations": [],
            "repository": "https://github.com/example/pinned-harness",
            "revision": revision,
        }
    ]
    monkeypatch.setattr(harness_lock, "_load_lock_rows", lambda: ({}, rows))
    return SimpleNamespace(ROOT=repository_root), harness


def _directory_link_or_skip(link: Path, target: Path) -> str:
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink"
    except (NotImplementedError, OSError) as symlink_error:
        if os.name != "nt":
            pytest.skip(f"directory symlinks are unsupported: {symlink_error}")
        completed = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(
                "neither a directory symlink nor a junction is supported: "
                + completed.stderr
            )
        return "junction"


def test_clean_future_checkout_passes(tmp_path: Path) -> None:
    benchmark, authority, stream_authorities, _future = _custody_case(tmp_path)

    _validate(benchmark, authority, stream_authorities)


@pytest.mark.parametrize("tamper_kind", ["tracked", "untracked"])
def test_dirty_future_checkout_is_rejected(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    benchmark, authority, stream_authorities, future = _custody_case(tmp_path)
    if tamper_kind == "tracked":
        (future / "tracked.txt").write_text("tampered\n", encoding="utf-8")
    else:
        (future / "untracked-attack.py").write_text(
            "raise RuntimeError('injected')\n",
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="future resume checkout"):
        _validate(benchmark, authority, stream_authorities)


def test_future_checkout_at_wrong_head_is_rejected(tmp_path: Path) -> None:
    benchmark, authority, stream_authorities, future = _custody_case(tmp_path)
    (future / "tracked.txt").write_text("different committed bytes\n", encoding="utf-8")
    _git(future, "add", "--", "tracked.txt")
    _git(
        future,
        "-c",
        "user.name=TriMem Test",
        "-c",
        "user.email=trimem-test@example.invalid",
        "commit",
        "--quiet",
        "-m",
        "wrong head",
    )

    with pytest.raises(ValueError, match="resume checkout commit identity differs"):
        _validate(benchmark, authority, stream_authorities)


def test_checkout_symlink_or_junction_escape_is_rejected(tmp_path: Path) -> None:
    benchmark, authority, stream_authorities, _future = _custody_case(
        tmp_path,
        linked_future=True,
    )

    with pytest.raises(ValueError, match="resume checkout task inventory differs"):
        _validate(benchmark, authority, stream_authorities)


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_index_flags_cannot_hide_future_tracked_tamper(
    tmp_path: Path,
    index_flag: str,
) -> None:
    benchmark, authority, stream_authorities, future = _custody_case(tmp_path)
    _git(future, "update-index", index_flag, "tracked.txt")
    (future / "tracked.txt").write_text("hidden tamper\n", encoding="utf-8")

    with pytest.raises(ValueError, match="frozen Git blob"):
        _validate(benchmark, authority, stream_authorities)


def test_local_ignore_cannot_hide_future_untracked_file(tmp_path: Path) -> None:
    benchmark, authority, stream_authorities, future = _custody_case(tmp_path)
    (future / ".git" / "info" / "exclude").write_text(
        "ignored-attack.py\n", encoding="utf-8"
    )
    (future / "ignored-attack.py").write_text(
        "raise RuntimeError('injected')\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="frozen tree"):
        _validate(benchmark, authority, stream_authorities)


def test_local_core_worktree_cannot_redirect_byte_validation(tmp_path: Path) -> None:
    benchmark, authority, stream_authorities, future = _custody_case(tmp_path)
    decoy = tmp_path / "clean-decoy"
    decoy.mkdir()
    (decoy / "tracked.txt").write_text("frozen\n", encoding="utf-8")
    _git(future, "config", "core.worktree", str(decoy))
    (future / "tracked.txt").write_text("redirected tamper\n", encoding="utf-8")

    with pytest.raises(ValueError, match="frozen Git blob"):
        _validate(benchmark, authority, stream_authorities)


@pytest.mark.parametrize(
    "tamper_kind",
    ["ignored-file", "empty-directory", "index-hidden-tracked"],
)
def test_committed_checkout_must_match_exact_workspace_checkpoint(
    tmp_path: Path,
    tamper_kind: str,
) -> None:
    benchmark, authority, stream_authorities, _future = _custody_case(tmp_path)
    prior_task = authority["tasks"][0]
    prior_checkout = Path(
        stream_authorities["M0"]["workspace_factory"].checkout_roots[
            prior_task.task_id
        ]
    )
    expected_state = dict(
        GitCheckoutWorkspace(
            prior_checkout,
            base_commit=prior_task.commit,
        ).checkpoint_state()
    )
    if tamper_kind == "ignored-file":
        (prior_checkout / ".git" / "info" / "exclude").write_text(
            "hidden-current.py\n",
            encoding="utf-8",
        )
        (prior_checkout / "hidden-current.py").write_text(
            "raise RuntimeError('hidden committed task attack')\n",
            encoding="utf-8",
        )
    elif tamper_kind == "empty-directory":
        (prior_checkout / "hidden-empty-package").mkdir()
    else:
        _git(
            prior_checkout,
            "update-index",
            "--assume-unchanged",
            "tracked.txt",
        )
        (prior_checkout / "tracked.txt").write_text(
            "hidden committed tracked attack\n",
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="workspace checkpoint"):
        _validate(
            benchmark,
            authority,
            stream_authorities,
            checkpoint_workspace_states={("M0", 0): expected_state},
        )


def test_committed_checkout_textconv_config_is_rejected_without_execution(
    tmp_path: Path,
) -> None:
    benchmark, authority, stream_authorities, _future = _custody_case(tmp_path)
    prior_task = authority["tasks"][0]
    prior_checkout = Path(
        stream_authorities["M0"]["workspace_factory"].checkout_roots[
            prior_task.task_id
        ]
    )
    expected_state = dict(
        GitCheckoutWorkspace(
            prior_checkout,
            base_commit=prior_task.commit,
        ).checkpoint_state()
    )
    sentinel = tmp_path / "workspace-textconv-was-executed"
    if os.name == "nt":
        hook = tmp_path / "malicious-textconv.cmd"
        hook.write_text(f'@echo invoked>"{sentinel}"\r\n', encoding="utf-8")
    else:
        hook = tmp_path / "malicious-textconv"
        hook.write_text(
            "#!/bin/sh\nprintf invoked > " + str(sentinel) + "\ncat \"$1\"\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
    (prior_checkout / ".git" / "info" / "attributes").write_text(
        "tracked.txt diff=attack\n",
        encoding="utf-8",
    )
    _git(prior_checkout, "config", "diff.attack.textconv", str(hook))

    with pytest.raises(ToolExecutionError, match="execute host code"):
        _validate(
            benchmark,
            authority,
            stream_authorities,
            checkpoint_workspace_states={("M0", 0): expected_state},
        )
    assert not sentinel.exists()


def test_harness_tracked_tamper_hidden_by_index_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, harness = _harness_case(tmp_path, monkeypatch)
    _git(harness, "update-index", "--assume-unchanged", "tracked.txt")
    (harness / "tracked.txt").write_text("hidden harness tamper\n", encoding="utf-8")

    with pytest.raises(ValueError, match="frozen Git blob"):
        resume_driver._validated_local_harnesses(benchmark)


def test_harness_local_ignore_cannot_hide_untracked_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, harness = _harness_case(tmp_path, monkeypatch)
    (harness / ".git" / "info" / "exclude").write_text(
        "shadow_module.py\n",
        encoding="utf-8",
    )
    (harness / "shadow_module.py").write_text(
        "raise RuntimeError('injected harness module')\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="frozen tree"):
        resume_driver._validated_local_harnesses(benchmark)


def test_harness_core_worktree_and_fsmonitor_cannot_redirect_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, harness = _harness_case(tmp_path, monkeypatch)
    decoy = tmp_path / "clean-harness-decoy"
    decoy.mkdir()
    (decoy / "tracked.txt").write_text("frozen\n", encoding="utf-8")
    sentinel = tmp_path / "fsmonitor-was-executed"
    if os.name == "nt":
        hook = tmp_path / "malicious-fsmonitor.cmd"
        hook.write_text(
            f'@echo invoked>"{sentinel}"\r\n',
            encoding="utf-8",
        )
    else:
        hook = tmp_path / "malicious-fsmonitor"
        hook.write_text(
            "#!/bin/sh\nprintf invoked > " + str(sentinel) + "\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
    _git(harness, "config", "core.worktree", str(decoy))
    _git(harness, "config", "core.fsmonitor", str(hook))
    (harness / "tracked.txt").write_text(
        "redirected harness tamper\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="frozen Git blob"):
        resume_driver._validated_local_harnesses(benchmark)
    assert not sentinel.exists()


def test_harness_symlink_or_junction_escape_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, _harness = _harness_case(
        tmp_path,
        monkeypatch,
        linked_harness=True,
    )

    with pytest.raises(ValueError, match="resume harness checkout inventory differs"):
        resume_driver._validated_local_harnesses(benchmark)


@pytest.mark.parametrize("index_flag", ["--assume-unchanged", "--skip-worktree"])
def test_direct_prepare_harnesses_rejects_index_hidden_tracked_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    index_flag: str,
) -> None:
    benchmark, harness = _harness_case(tmp_path, monkeypatch)
    _git(harness, "update-index", index_flag, "tracked.txt")
    (harness / "tracked.txt").write_text(
        "hidden direct-prepare tamper\n",
        encoding="utf-8",
    )

    with pytest.raises(
        harness_lock.HarnessLockError,
        match="frozen Git blob",
    ):
        harness_lock.prepare_harnesses(
            benchmark.ROOT / ".trimem-exec" / "harnesses"
        )


def test_direct_prepare_harnesses_rejects_ignored_untracked_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, harness = _harness_case(tmp_path, monkeypatch)
    (harness / ".git" / "info" / "exclude").write_text(
        "ignored-direct-attack.py\n",
        encoding="utf-8",
    )
    (harness / "ignored-direct-attack.py").write_text(
        "raise RuntimeError('injected direct harness module')\n",
        encoding="utf-8",
    )

    with pytest.raises(harness_lock.HarnessLockError, match="frozen Git tree"):
        harness_lock.prepare_harnesses(
            benchmark.ROOT / ".trimem-exec" / "harnesses"
        )


def test_direct_prepare_harnesses_rejects_core_worktree_without_fsmonitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, harness = _harness_case(tmp_path, monkeypatch)
    decoy = tmp_path / "direct-prepare-clean-decoy"
    decoy.mkdir()
    (decoy / "tracked.txt").write_text("frozen\n", encoding="utf-8")
    sentinel = tmp_path / "direct-prepare-fsmonitor-was-executed"
    if os.name == "nt":
        hook = tmp_path / "direct-prepare-fsmonitor.cmd"
        hook.write_text(f'@echo invoked>"{sentinel}"\r\n', encoding="utf-8")
    else:
        hook = tmp_path / "direct-prepare-fsmonitor"
        hook.write_text(
            "#!/bin/sh\nprintf invoked > " + str(sentinel) + "\n",
            encoding="utf-8",
        )
        hook.chmod(0o755)
    _git(harness, "config", "core.worktree", str(decoy))
    _git(harness, "config", "core.fsmonitor", str(hook))
    (harness / "tracked.txt").write_text(
        "redirected direct-prepare tamper\n",
        encoding="utf-8",
    )

    with pytest.raises(
        harness_lock.HarnessLockError,
        match="local Git configuration is unsafe",
    ):
        harness_lock.prepare_harnesses(
            benchmark.ROOT / ".trimem-exec" / "harnesses"
        )
    assert not sentinel.exists()


def test_direct_prepare_harnesses_rejects_linked_checkout_before_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, _harness = _harness_case(
        tmp_path,
        monkeypatch,
        linked_harness=True,
    )

    with pytest.raises(harness_lock.HarnessLockError, match="link or reparse point"):
        harness_lock.prepare_harnesses(
            benchmark.ROOT / ".trimem-exec" / "harnesses"
        )


def test_direct_prepare_harnesses_rejects_linked_root_ancestor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "linked-root-runtime"
    (runtime / ".trimem-exec").mkdir(parents=True)
    outside_root = tmp_path / "outside-harness-root"
    harness = outside_root / "pinned-harness"
    revision = _committed_checkout(harness)
    _git(
        harness,
        "remote",
        "add",
        "origin",
        "https://github.com/example/pinned-harness",
    )
    rows = [
        {
            "benchmark_ids": ["fixture-benchmark"],
            "checkout_key": "pinned-harness",
            "dependency_declarations": [],
            "repository": "https://github.com/example/pinned-harness",
            "revision": revision,
        }
    ]
    monkeypatch.setattr(harness_lock, "_load_lock_rows", lambda: ({}, rows))
    linked_root = runtime / ".trimem-exec" / "harnesses"
    _directory_link_or_skip(linked_root, outside_root)

    with pytest.raises(harness_lock.HarnessLockError, match="link or reparse point"):
        harness_lock.prepare_harnesses(linked_root)


@pytest.mark.parametrize("tamper_kind", ["tracked-index-hidden", "ignored-untracked"])
def test_direct_loader_preflight_rejects_tamper_before_loader_or_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper_kind: str,
) -> None:
    harness = tmp_path / "direct-preflight-harness"
    revision = _committed_checkout(harness)
    monkeypatch.setattr(loader_preflight, "SWE_HARNESS_REVISION", revision)
    monkeypatch.setattr(loader_preflight, "MULTI_HARNESS_REVISION", revision)
    if tamper_kind == "tracked-index-hidden":
        _git(harness, "update-index", "--assume-unchanged", "tracked.txt")
        (harness / "tracked.txt").write_text(
            "hidden direct-preflight tamper\n",
            encoding="utf-8",
        )
    else:
        (harness / ".git" / "info" / "exclude").write_text(
            "ignored-preflight-attack.py\n",
            encoding="utf-8",
        )
        (harness / "ignored-preflight-attack.py").write_text(
            "raise RuntimeError('preflight import attack')\n",
            encoding="utf-8",
        )

    def forbidden_builder(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("loader/environment construction ran before custody")

    def forbidden_runner(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("revision/import subprocess ran before custody")

    with pytest.raises(
        loader_preflight.OfficialHarnessLoaderPreflightError,
        match="not pristine",
    ):
        loader_preflight.run_official_harness_loader_preflight(
            python_binary=sys.executable,
            swe_harness_root=harness,
            multi_harness_root=harness,
            source_environment={},
            runner=forbidden_runner,
            loader_builder=forbidden_builder,
            environment_builder=forbidden_builder,
        )


def test_process2_harness_preparation_rejects_local_fsmonitor_without_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark, harness = _harness_case(tmp_path, monkeypatch)
    sentinel = tmp_path / "prepare-harness-fsmonitor-was-executed"
    _git(harness, "config", "core.fsmonitor", str(sentinel))

    with pytest.raises(
        harness_lock.HarnessLockError,
        match="local Git configuration is unsafe",
    ):
        harness_lock.prepare_harnesses(
            benchmark.ROOT / ".trimem-exec" / "harnesses"
        )
    assert not sentinel.exists()


def test_process2_task_checkout_rejects_local_fsmonitor_without_invocation(
    tmp_path: Path,
) -> None:
    stream_root = tmp_path / "task-checkouts"
    checkout = stream_root / "task-0"
    commit = _committed_checkout(checkout)
    sentinel = tmp_path / "prepare-task-fsmonitor-was-executed"
    _git(checkout, "config", "core.fsmonitor", str(sentinel))
    task = SimpleNamespace(
        task_id="task-0",
        repository="example/repository",
        commit=commit,
    )

    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="Git configuration is unsafe",
    ):
        benchmark_run.prepare_checkouts(
            [task],
            [{"instance_id": "fixture-instance"}],
            {
                "fixture-instance": {
                    "image": "example/image@sha256:" + "0" * 64,
                }
            },
            stream_root,
            resume=True,
        )

    assert not sentinel.exists()


def test_process2_task_checkout_ignores_host_git_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream_root = tmp_path / "host-env-task-checkouts"
    checkout = stream_root / "task-0"
    commit = _committed_checkout(checkout)
    decoy = tmp_path / "host-git-env-decoy"
    _committed_checkout(decoy)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(decoy / ".git" / "objects"))
    monkeypatch.setenv(
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", str(decoy / ".git" / "objects")
    )
    task = SimpleNamespace(
        task_id="task-0",
        repository="example/repository",
        commit=commit,
    )

    factory, evidence = benchmark_run.prepare_checkouts(
        [task],
        [{"instance_id": "fixture-instance"}],
        {
            "fixture-instance": {
                "image": "example/image@sha256:" + "0" * 64,
            }
        },
        stream_root,
        resume=True,
    )

    assert factory.checkout_roots["task-0"] == checkout.resolve(strict=True)
    assert evidence["task-0"]["head"] == commit
    assert evidence["task-0"]["initial_status"] == ""
    assert evidence["task-0"]["checkout_origin"] == "EXISTING_CHECKOUT"
    assert evidence["task-0"]["materialization"] is None


def test_process2_task_checkout_root_link_escape_is_rejected(
    tmp_path: Path,
) -> None:
    outside_root = tmp_path / "outside-task-checkouts"
    checkout = outside_root / "task-0"
    commit = _committed_checkout(checkout)
    linked_root = tmp_path / "runtime" / "task-checkouts"
    linked_root.parent.mkdir(parents=True)
    _directory_link_or_skip(linked_root, outside_root)
    task = SimpleNamespace(
        task_id="task-0",
        repository="example/repository",
        commit=commit,
    )

    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="root is unsafe"):
        benchmark_run.prepare_checkouts(
            [task],
            [{"instance_id": "fixture-instance"}],
            {
                "fixture-instance": {
                    "image": "example/image@sha256:" + "0" * 64,
                }
            },
            linked_root,
            resume=True,
        )


def test_workspace_git_ignores_host_git_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "workspace-host-env"
    commit = _committed_checkout(checkout)
    decoy = tmp_path / "workspace-host-env-decoy"
    _committed_checkout(decoy)
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
    monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(decoy / ".git" / "objects"))
    monkeypatch.setenv(
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", str(decoy / ".git" / "objects")
    )

    state = GitCheckoutWorkspace(checkout, base_commit=commit).checkpoint_state()

    assert state["base_commit"] == commit
    assert state["patch"] == ""
