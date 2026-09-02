"""Fail-closed entrypoint for one pinned Multi-SWE prebuilt-image evaluation.

The pinned upstream ``run_evaluation`` module performs an unrelated
``nix_swe`` container bootstrap in its ``__main__`` block before it parses the
requested mode.  TriMem's prebuilt-image contract must not execute that block:
it imports the exact pinned module, materializes its own ``CliArgs`` from the
production config, and calls ``CliArgs.run()`` directly.

This module has no generic command surface and supports only the immutable
``MULTI_SWE_PREBUILT_EVALUATION`` flags.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


PINNED_MULTI_SWE_REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
UPSTREAM_MODULE = "multi_swe_bench.harness.run_evaluation"
UPSTREAM_MODULE_PATH = Path("multi_swe_bench/harness/run_evaluation.py")
EXPECTED_CONFIG_FIELDS = frozenset(
    {
        "clear_env",
        "dataset_files",
        "force_build",
        "global_env",
        "human_mode",
        "log_dir",
        "log_level",
        "log_to_console",
        "max_workers",
        "max_workers_build_image",
        "max_workers_run_instance",
        "mode",
        "need_clone",
        "output_dir",
        "patch_files",
        "repo_dir",
        "skips",
        "specifics",
        "stop_on_error",
        "workdir",
    }
)


class MultiSWEEntrypointError(RuntimeError):
    """The pinned checkout or the only supported execution config differs."""


def _strict_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise MultiSWEEntrypointError(f"duplicate config key: {key}")
            value[key] = child
        return value

    try:
        value = json.loads(
            path.read_bytes().decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MultiSWEEntrypointError("Multi-SWE config is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise MultiSWEEntrypointError("Multi-SWE config root is not an object")
    return value


def _validate_config(config_path: Path) -> dict[str, Any]:
    config = _strict_object(config_path)
    if set(config) != EXPECTED_CONFIG_FIELDS:
        raise MultiSWEEntrypointError("Multi-SWE production config field set differs")
    if (
        config.get("mode") != "instance_only"
        or config.get("force_build") is not False
        or config.get("human_mode") is not True
        or config.get("need_clone") is not False
        or config.get("clear_env") is not True
        or config.get("stop_on_error") is not True
        or config.get("global_env") != []
        or config.get("skips") != []
        or config.get("log_level") != "DEBUG"
        or config.get("log_to_console") is not True
        or any(
            type(config.get(field)) is not int or config[field] != 1
            for field in (
                "max_workers",
                "max_workers_build_image",
                "max_workers_run_instance",
            )
        )
        or not isinstance(config.get("patch_files"), list)
        or len(config["patch_files"]) != 1
        or not isinstance(config["patch_files"][0], str)
        or not isinstance(config.get("dataset_files"), list)
        or len(config["dataset_files"]) != 1
        or not isinstance(config["dataset_files"][0], str)
        or not isinstance(config.get("specifics"), list)
        or len(config["specifics"]) != 1
        or not isinstance(config["specifics"][0], str)
        or any(
            not isinstance(config.get(field), str) or not config[field]
            for field in ("workdir", "output_dir", "repo_dir", "log_dir")
        )
        or not config["patch_files"][0]
        or not config["dataset_files"][0]
        or not config["specifics"][0]
    ):
        raise MultiSWEEntrypointError(
            "Multi-SWE config is not the one-row prebuilt-evaluation contract"
        )
    return config


def _verify_checkout(harness_root: Path) -> Path:
    root = harness_root.resolve(strict=True)
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if (
        completed.returncode != 0
        or completed.stdout.strip() != PINNED_MULTI_SWE_REVISION
    ):
        raise MultiSWEEntrypointError("Multi-SWE checkout revision differs")
    return root


def execute_pinned_instance_only(
    *, harness_root: Path, config_path: Path
) -> Any:
    """Execute only pinned ``CliArgs.run(instance_only)`` and return the CLI.

    Importing the upstream module initializes its Docker SDK client, as the
    pinned library requires, but deliberately does not execute its module
    ``__main__`` support-container bootstrap.
    """

    root = _verify_checkout(harness_root)
    config_path = config_path.resolve(strict=True)
    config = _validate_config(config_path)
    inserted = str(root)
    sys.path.insert(0, inserted)
    try:
        module = importlib.import_module(UPSTREAM_MODULE)
    finally:
        if sys.path and sys.path[0] == inserted:
            sys.path.pop(0)
    module_file = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
    expected_module = (root / UPSTREAM_MODULE_PATH).resolve(strict=True)
    if module_file != expected_module:
        raise MultiSWEEntrypointError("Multi-SWE module escaped the pinned checkout")

    parser = module.get_parser()
    # The pinned harness subclasses argparse with ``use_config`` as its first
    # positional parameter.  Supplying the argv list positionally would bind
    # that list to ``use_config`` and make argparse consume this wrapper's
    # process argv instead.  Bind argparse's ``args`` parameter by name so the
    # exact config is both selected and loaded.
    parsed = parser.parse_args(args=["--config", str(config_path)])
    cli = module.CliArgs.from_dict(vars(parsed))
    if (
        cli.mode != "instance_only"
        or cli.force_build is not False
        or cli.human_mode is not True
        or cli.need_clone is not False
        or cli.clear_env is not True
        or cli.stop_on_error is not True
        or cli.global_env != []
        or set(cli.skips or ())
        or cli.log_level != "DEBUG"
        or cli.log_to_console is not True
        or cli.max_workers != 1
        or cli.max_workers_build_image != 1
        or cli.max_workers_run_instance != 1
        or cli.fix_patch_run_cmd != ""
        or list(cli.patch_files or ()) != config["patch_files"]
        or list(cli.dataset_files or ()) != config["dataset_files"]
        or set(cli.specifics or ()) != set(config["specifics"])
        or Path(str(cli.workdir)) != Path(config["workdir"])
        or Path(str(cli.output_dir)) != Path(config["output_dir"])
        or Path(str(cli.repo_dir)) != Path(config["repo_dir"])
        or Path(str(cli.log_dir)) != Path(config["log_dir"])
        or len(cli.instances) != 1
    ):
        raise MultiSWEEntrypointError("pinned Multi-SWE CLI contract differs")
    cli.run()
    return cli


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        execute_pinned_instance_only(
            harness_root=args.harness_root, config_path=args.config
        )
        return 0
    except (MultiSWEEntrypointError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "error_type": type(exc).__name__, "status": "FAIL"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
