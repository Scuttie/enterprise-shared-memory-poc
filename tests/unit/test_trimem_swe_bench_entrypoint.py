from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_harness_lock as harness_lock
import trimem_swe_bench_entrypoint as entrypoint


def _forwarded(run_root: Path) -> list[str]:
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "dataset.json").write_bytes(b"[]\n")
    (run_root / "prediction.jsonl").write_bytes(b"{}\n")
    (run_root / "report").mkdir()
    return [
        "--dataset_name",
        str(run_root / "dataset.json"),
        "--split",
        "test",
        "--instance_ids",
        "owner__repo-1",
        "--predictions_path",
        str(run_root / "prediction.jsonl"),
        "--max_workers",
        "1",
        "--timeout",
        "1800",
        "--run_id",
        "1" * 20,
        "--report_dir",
        str(run_root / "report"),
    ]


def test_entrypoint_accepts_only_fixed_single_target_option_order(
    tmp_path: Path,
) -> None:
    harness = (tmp_path / "harness").absolute()
    harness.mkdir()
    forwarded = _forwarded((tmp_path / "run").absolute())
    observed_root, self_check, observed = entrypoint._parse(
        ["--harness-root", str(harness), *forwarded]
    )
    assert observed_root == harness
    assert self_check is False
    assert observed == forwarded

    for forbidden in ("--task_repo", "--rewrite_reports", "--modal"):
        with pytest.raises(entrypoint.SWEBenchEntrypointError):
            entrypoint._parse(
                ["--harness-root", str(harness), *forwarded, forbidden, "true"]
            )


def test_entrypoint_requires_task_local_exact_paths_and_fixed_limits(
    tmp_path: Path,
) -> None:
    run_root = (tmp_path / "run").absolute()
    run_root.mkdir()
    forwarded = _forwarded(run_root)
    assert entrypoint._validated_forwarded_argv(forwarded, run_root) == forwarded

    escaped = list(forwarded)
    escaped[1] = str((tmp_path / "outside.json").absolute())
    (tmp_path / "outside.json").write_bytes(b"[]\n")
    with pytest.raises(
        entrypoint.SWEBenchEntrypointError,
        match="escaped the task-local run root",
    ):
        entrypoint._validated_forwarded_argv(escaped, run_root)

    unsafe = list(forwarded)
    unsafe[9] = "2"
    with pytest.raises(entrypoint.SWEBenchEntrypointError, match="worker count"):
        entrypoint._validated_forwarded_argv(unsafe, run_root)


def test_entrypoint_binds_exact_module_origin_and_git_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = (tmp_path / "harness").absolute()
    module_path = harness / "swebench/harness/run_evaluation.py"
    module_path.parent.mkdir(parents=True)
    raw = b"# pinned module\n"
    module_path.write_bytes(raw)
    validated: list[tuple[Path, str]] = []
    monkeypatch.setattr(
        entrypoint,
        "validate_pristine_checkout",
        lambda root, revision: validated.append((root, revision)),
    )
    monkeypatch.setattr(entrypoint, "read_pinned_git_blob", lambda *_args: raw)
    monkeypatch.setattr(
        entrypoint.importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(module_path)),
    )
    monkeypatch.setattr(entrypoint.sys, "flags", SimpleNamespace(safe_path=True))

    evidence = entrypoint._bind_pinned_module(harness)
    assert evidence["module_sha256"]
    assert validated == [(harness, entrypoint.SWE_HARNESS_REVISION)]

    module_path.write_bytes(b"# drift\n")
    with pytest.raises(entrypoint.SWEBenchEntrypointError, match="Git blob"):
        entrypoint._bind_pinned_module(harness)


def test_entrypoint_postflight_never_allowlists_generated_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = (tmp_path / "harness").absolute()
    harness.mkdir()

    def reject(_root: Path, _revision: str) -> None:
        raise harness_lock.HarnessLockError(
            "harness inventory differs from its frozen Git tree"
        )

    monkeypatch.setattr(entrypoint, "validate_pristine_checkout", reject)
    with pytest.raises(
        entrypoint.SWEBenchEntrypointError,
        match="changed during evaluation",
    ):
        entrypoint._postflight(harness)


def test_entrypoint_executes_fixed_module_and_postflights_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = (tmp_path / "harness").absolute()
    harness.mkdir()
    run_root = (tmp_path / "run").absolute()
    forwarded = _forwarded(run_root)
    monkeypatch.chdir(run_root)
    monkeypatch.setattr(entrypoint.sys, "flags", SimpleNamespace(safe_path=True))
    monkeypatch.setattr(entrypoint, "_bind_pinned_module", lambda _root: {})

    executed: list[tuple[str, str, bool, tuple[str, ...]]] = []

    def execute(module: str, *, run_name: str, alter_sys: bool) -> None:
        executed.append((module, run_name, alter_sys, tuple(entrypoint.sys.argv)))
        raise SystemExit(23)

    postflights: list[Path] = []
    monkeypatch.setattr(entrypoint.runpy, "run_module", execute)
    monkeypatch.setattr(
        entrypoint,
        "_postflight",
        lambda root: postflights.append(root),
    )

    with pytest.raises(SystemExit) as caught:
        entrypoint.main(["--harness-root", str(harness), *forwarded])

    assert caught.value.code == 23
    assert executed == [
        (
            entrypoint.SWE_MODULE,
            "__main__",
            True,
            (entrypoint.SWE_MODULE, *forwarded),
        )
    ]
    assert postflights == [harness]
