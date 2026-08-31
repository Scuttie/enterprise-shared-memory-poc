"""Remove fixed sensitive EXEC material after encrypted/public uploads finish."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def _remove_tree(parent: Path, target: Path) -> None:
    parent_resolved = parent.resolve(strict=True)
    if not target.exists():
        return
    if target.is_symlink():
        raise RuntimeError(f"refusing cleanup through symlink: {target}")
    target_resolved = target.resolve(strict=True)
    if parent_resolved not in target_resolved.parents:
        raise RuntimeError(f"cleanup target escapes fixed root: {target}")
    if not target_resolved.is_dir():
        raise RuntimeError(f"expected cleanup directory: {target}")
    shutil.rmtree(target_resolved)


def _remove_file(parent: Path, target: Path) -> None:
    parent_resolved = parent.resolve(strict=True)
    if not target.exists():
        return
    if target.is_symlink():
        raise RuntimeError(f"refusing cleanup through symlink: {target}")
    target_resolved = target.resolve(strict=True)
    if parent_resolved not in target_resolved.parents or not target_resolved.is_file():
        raise RuntimeError(f"cleanup file escapes fixed root: {target}")
    target_resolved.unlink()


def cleanup(phase: str, runner_temp: Path) -> None:
    if phase not in {"grader-smoke", "benchmark"}:
        raise ValueError("cleanup phase is not one of the frozen execution phases")
    _remove_tree(ROOT, ROOT / ".trimem-exec")
    if phase == "grader-smoke":
        _remove_tree(ROOT, ROOT / "artifacts/trimem_v1/grader_smoke_exec")
        encrypted = runner_temp / "trimem-grader-smoke-restricted.tar.enc"
    else:
        _remove_tree(ROOT, ROOT / "artifacts/trimem_v1/benchmark_exec")
        _remove_tree(ROOT, ROOT / "artifacts/trimem_v1/development_selection")
        encrypted = runner_temp / "trimem-benchmark-restricted.tar.enc"
    _remove_file(runner_temp, runner_temp / "trimem-exec-approval.json")
    _remove_file(runner_temp, encrypted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("grader-smoke", "benchmark"), required=True)
    args = parser.parse_args()
    runner_temp = os.environ.get("RUNNER_TEMP")
    if not runner_temp:
        raise SystemExit("RUNNER_TEMP is required")
    cleanup(args.phase, Path(runner_temp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
