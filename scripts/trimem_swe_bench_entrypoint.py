"""Fail-closed task-local launcher for the pinned SWE-bench evaluator.

The pinned upstream evaluator writes ``logs/run_evaluation`` relative to its
current directory.  TriMem keeps the executable harness checkout immutable,
so this launcher runs the exact upstream module from a task-local evidence
directory while binding every imported SWE-bench byte to the pinned Git tree.

This is deliberately not a generic command or module launcher.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
import runpy
import sys
from typing import Sequence


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from trimem_harness_lock import (  # noqa: E402
    HarnessLockError,
    read_pinned_git_blob,
    validate_lexical_directory_chain,
    validate_pristine_checkout,
)


SWE_HARNESS_REVISION = "7a21e05772954cc81471ae19d56f436cecf43c54"
SWE_MODULE = "swebench.harness.run_evaluation"
SWE_MODULE_PATH = "swebench/harness/run_evaluation.py"
INSTANCE_ID = re.compile(r"^[A-Za-z0-9_.-]+__[A-Za-z0-9_.-]+-[0-9]+$")
RUN_ID = re.compile(r"^[0-9a-f]{20}$")
SWE_IMPORT_PROBE_SCHEMA = "trimem/swe-bench-loader-import-probe/1.0"


class SWEBenchEntrypointError(RuntimeError):
    """The exact task-local SWE-bench launch contract is not satisfied."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SWEBenchEntrypointError(message)


def _regular_file_within(path_text: str, root: Path, *, name: str) -> Path:
    path = Path(path_text)
    _require(path.is_absolute(), f"{name} must be absolute")
    _require(not path.is_symlink(), f"{name} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SWEBenchEntrypointError(f"{name} does not resolve") from exc
    _require(root in resolved.parents, f"{name} escaped the task-local run root")
    _require(resolved.is_file(), f"{name} is not a regular file")
    return resolved


def _directory_within(path_text: str, root: Path, *, name: str) -> Path:
    path = Path(path_text)
    _require(path.is_absolute(), f"{name} must be absolute")
    _require(not path.is_symlink(), f"{name} must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SWEBenchEntrypointError(f"{name} does not resolve") from exc
    _require(root in resolved.parents, f"{name} escaped the task-local run root")
    _require(resolved.is_dir(), f"{name} is not a directory")
    return resolved


def _parse(argv: Sequence[str]) -> tuple[Path, bool, list[str]]:
    values = list(argv)
    _require(
        len(values) >= 3 and values[0] == "--harness-root",
        "the pinned harness root must be the first exact option",
    )
    harness_root = Path(values[1])
    _require(harness_root.is_absolute(), "the pinned harness root must be absolute")
    if values[2:] == ["--self-check"]:
        return harness_root, True, []

    expected_options = (
        "--dataset_name",
        "--split",
        "--instance_ids",
        "--predictions_path",
        "--max_workers",
        "--timeout",
        "--run_id",
        "--report_dir",
    )
    forwarded = values[2:]
    _require(
        len(forwarded) == len(expected_options) * 2,
        "the SWE-bench option count differs from the frozen single-target contract",
    )
    _require(
        tuple(forwarded[::2]) == expected_options,
        "the SWE-bench option order differs from the frozen single-target contract",
    )
    return harness_root, False, forwarded


def _bind_pinned_module(harness_root: Path) -> dict[str, object]:
    try:
        validate_pristine_checkout(harness_root, SWE_HARNESS_REVISION)
        root = harness_root.resolve(strict=True)
    except (HarnessLockError, OSError) as exc:
        raise SWEBenchEntrypointError(
            "the pinned SWE-bench checkout is not pristine"
        ) from exc

    expected_path = root.joinpath(*SWE_MODULE_PATH.split("/"))
    try:
        expected_raw = read_pinned_git_blob(
            root, SWE_HARNESS_REVISION, SWE_MODULE_PATH
        )
    except HarnessLockError as exc:
        raise SWEBenchEntrypointError(
            "the pinned SWE-bench module blob cannot be read"
        ) from exc

    # Safe-path mode keeps the task output directory out of the automatic
    # import path.  The one validated harness root is then the first explicit
    # source location.
    _require(bool(sys.flags.safe_path), "Python safe-path mode (-P) is required")
    sys.path.insert(0, str(root))
    try:
        spec = importlib.util.find_spec(SWE_MODULE)
    except (ImportError, AttributeError, ValueError) as exc:
        raise SWEBenchEntrypointError(
            "the pinned SWE-bench module cannot be resolved"
        ) from exc
    _require(spec is not None and spec.origin is not None, "SWE-bench module origin is absent")
    try:
        origin = Path(spec.origin).resolve(strict=True)
    except OSError as exc:
        raise SWEBenchEntrypointError("SWE-bench module origin does not resolve") from exc
    _require(origin == expected_path.resolve(strict=True), "SWE-bench module origin escaped the pinned checkout")
    observed_raw = origin.read_bytes()
    _require(observed_raw == expected_raw, "SWE-bench module bytes differ from the pinned Git blob")
    return {
        "harness_revision": SWE_HARNESS_REVISION,
        "module": SWE_MODULE,
        "module_bytes": len(observed_raw),
        "module_sha256": hashlib.sha256(observed_raw).hexdigest(),
    }


def _validated_forwarded_argv(forwarded: Sequence[str], run_root: Path) -> list[str]:
    values = dict(zip(forwarded[::2], forwarded[1::2]))
    _require(values["--split"] == "test", "SWE-bench split differs")
    _require(values["--max_workers"] == "1", "SWE-bench worker count differs")
    _require(values["--timeout"] == "1800", "SWE-bench timeout differs")
    _require(INSTANCE_ID.fullmatch(values["--instance_ids"]) is not None, "SWE-bench instance identity is malformed")
    _require(RUN_ID.fullmatch(values["--run_id"]) is not None, "SWE-bench run identity is malformed")
    dataset = _regular_file_within(
        values["--dataset_name"], run_root, name="SWE-bench dataset"
    )
    prediction = _regular_file_within(
        values["--predictions_path"], run_root, name="SWE-bench prediction"
    )
    report = _directory_within(
        values["--report_dir"], run_root, name="SWE-bench report directory"
    )
    _require(dataset == run_root / "dataset.json", "SWE-bench dataset path differs")
    _require(prediction == run_root / "prediction.jsonl", "SWE-bench prediction path differs")
    _require(report == run_root / "report", "SWE-bench report path differs")
    return list(forwarded)


def _postflight(harness_root: Path) -> None:
    try:
        validate_pristine_checkout(harness_root, SWE_HARNESS_REVISION)
    except HarnessLockError as exc:
        raise SWEBenchEntrypointError(
            "the pinned SWE-bench checkout changed during evaluation"
        ) from exc


def _self_check_modules(harness_root: Path) -> dict[str, dict[str, object]]:
    root = harness_root.resolve(strict=True)
    rows: dict[str, dict[str, object]] = {}
    for name in (SWE_MODULE, "docker", "datasets", "unidiff"):
        module = importlib.import_module(name)
        raw_path = getattr(module, "__file__", None)
        path = Path(str(raw_path)).resolve(strict=True) if raw_path else None
        within = bool(path is not None and (path == root or root in path.parents))
        if name.startswith("swebench."):
            _require(within, "SWE-bench entry module escaped the pinned checkout")
        raw = path.read_bytes() if path is not None and path.is_file() else b""
        rows[name] = {
            "bytes": len(raw),
            "path": path.relative_to(root).as_posix() if within else None,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    harness_root, self_check, forwarded = _parse(
        sys.argv[1:] if argv is None else argv
    )
    run_root = validate_lexical_directory_chain(
        Path.cwd().absolute(), label="SWE-bench task-local run root"
    ).resolve(strict=True)
    root = harness_root.resolve(strict=True)
    _require(
        root != run_root and root not in run_root.parents and run_root not in root.parents,
        "the task-local run root and pinned harness checkout must be disjoint",
    )
    _bind_pinned_module(harness_root)
    if self_check:
        modules = _self_check_modules(harness_root)
        _postflight(harness_root)
        print(
            json.dumps(
                {
                    "modules": modules,
                    "schema": SWE_IMPORT_PROBE_SCHEMA,
                    "status": "PASS",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0

    upstream_argv = _validated_forwarded_argv(forwarded, run_root)
    primary: BaseException | None = None
    try:
        sys.argv = [SWE_MODULE, *upstream_argv]
        runpy.run_module(SWE_MODULE, run_name="__main__", alter_sys=True)
    except BaseException as exc:  # SystemExit is the upstream CLI result.
        primary = exc
    try:
        _postflight(harness_root)
    except SWEBenchEntrypointError as exc:
        if primary is not None:
            raise exc from primary
        raise
    if primary is not None:
        raise primary
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HarnessLockError, OSError, ValueError, SWEBenchEntrypointError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None
