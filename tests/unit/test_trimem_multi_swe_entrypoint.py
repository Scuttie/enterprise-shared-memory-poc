from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_multi_swe_entrypoint as entrypoint  # noqa: E402


def _config(root: Path) -> dict[str, object]:
    return {
        "clear_env": True,
        "dataset_files": [str(root / "dataset.jsonl")],
        "force_build": False,
        "global_env": [],
        "human_mode": True,
        "log_dir": str(root / "logs"),
        "log_level": "DEBUG",
        "log_to_console": True,
        "max_workers": 1,
        "max_workers_build_image": 1,
        "max_workers_run_instance": 1,
        "mode": "instance_only",
        "need_clone": False,
        "output_dir": str(root / "output"),
        "patch_files": [str(root / "prediction.jsonl")],
        "repo_dir": str(root / "repos"),
        "skips": [],
        "specifics": ["vuejs/core:pr-8911"],
        "stop_on_error": True,
        "workdir": str(root / "work"),
    }


def _write_config(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
        newline="",
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("mode", "evaluation"),
        ("force_build", True),
        ("human_mode", False),
        ("need_clone", True),
        ("max_workers_run_instance", 2),
        ("patch_files", []),
    ],
)
def test_config_contract_fails_closed(
    tmp_path: Path, field: str, replacement: object
) -> None:
    config = _config(tmp_path)
    config[field] = replacement
    path = tmp_path / "config.json"
    _write_config(path, config)

    with pytest.raises(
        entrypoint.MultiSWEEntrypointError,
        match="one-row prebuilt-evaluation contract",
    ):
        entrypoint._validate_config(path)


def test_config_rejects_unknown_and_duplicate_fields(tmp_path: Path) -> None:
    config = _config(tmp_path)
    unknown = deepcopy(config)
    unknown["fallback_to_source_build"] = True
    unknown_path = tmp_path / "unknown.json"
    _write_config(unknown_path, unknown)
    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="field set differs"):
        entrypoint._validate_config(unknown_path)

    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_bytes(b'{"mode":"instance_only","mode":"evaluation"}')
    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="duplicate config key"):
        entrypoint._validate_config(duplicate_path)


def test_wrapper_calls_exact_pinned_cli_without_upstream_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness_root = tmp_path / "multi-swe-bench"
    module_path = harness_root / entrypoint.UPSTREAM_MODULE_PATH
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# exact pinned module fixture\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config = _config(tmp_path)
    _write_config(config_path, config)

    calls: list[str] = []

    class Parser:
        @staticmethod
        def parse_args(argv: list[str]) -> types.SimpleNamespace:
            assert argv == ["--config", str(config_path)]
            calls.append("get_parser.parse_args")
            return types.SimpleNamespace(config=config_path)

    class Cli:
        mode = "instance_only"
        force_build = False
        human_mode = True
        need_clone = False
        clear_env = True
        stop_on_error = True
        global_env: list[str] = []
        skips: set[str] = set()
        log_level = "DEBUG"
        log_to_console = True
        max_workers = 1
        max_workers_build_image = 1
        max_workers_run_instance = 1
        fix_patch_run_cmd = ""
        patch_files = config["patch_files"]
        dataset_files = config["dataset_files"]
        specifics = set(config["specifics"])
        workdir = Path(str(config["workdir"]))
        output_dir = Path(str(config["output_dir"]))
        repo_dir = Path(str(config["repo_dir"]))
        log_dir = Path(str(config["log_dir"]))
        instances = [object()]

        def run(self) -> None:
            calls.append("CliArgs.run")

    class CliArgs:
        @staticmethod
        def from_dict(values: dict[str, object]) -> Cli:
            assert values == {"config": config_path}
            calls.append("CliArgs.from_dict")
            return Cli()

    upstream_main_calls: list[str] = []
    module = types.SimpleNamespace(
        __file__=str(module_path),
        get_parser=lambda: Parser(),
        CliArgs=CliArgs,
        upstream_main=lambda: upstream_main_calls.append("nix_swe_bootstrap"),
    )
    monkeypatch.setattr(
        entrypoint, "_verify_checkout", lambda value: value.resolve(strict=True)
    )
    monkeypatch.setattr(
        entrypoint.importlib,
        "import_module",
        lambda name: module
        if name == entrypoint.UPSTREAM_MODULE
        else (_ for _ in ()).throw(AssertionError(name)),
    )

    returned = entrypoint.execute_pinned_instance_only(
        harness_root=harness_root, config_path=config_path
    )

    assert isinstance(returned, Cli)
    assert calls == ["get_parser.parse_args", "CliArgs.from_dict", "CliArgs.run"]
    assert upstream_main_calls == []


def test_parsed_cli_runtime_drift_fails_before_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness_root = tmp_path / "multi-swe-bench"
    module_path = harness_root / entrypoint.UPSTREAM_MODULE_PATH
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# exact pinned module fixture\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config = _config(tmp_path)
    _write_config(config_path, config)
    ran: list[bool] = []

    cli = types.SimpleNamespace(
        mode="instance_only",
        force_build=False,
        human_mode=True,
        need_clone=False,
        clear_env=False,
        stop_on_error=True,
        global_env=[],
        skips=set(),
        log_level="DEBUG",
        log_to_console=True,
        max_workers=1,
        max_workers_build_image=1,
        max_workers_run_instance=1,
        fix_patch_run_cmd="",
        patch_files=config["patch_files"],
        dataset_files=config["dataset_files"],
        specifics=set(config["specifics"]),
        workdir=Path(str(config["workdir"])),
        output_dir=Path(str(config["output_dir"])),
        repo_dir=Path(str(config["repo_dir"])),
        log_dir=Path(str(config["log_dir"])),
        instances=[object()],
        run=lambda: ran.append(True),
    )
    module = types.SimpleNamespace(
        __file__=str(module_path),
        get_parser=lambda: types.SimpleNamespace(
            parse_args=lambda _argv: types.SimpleNamespace(config=config_path)
        ),
        CliArgs=types.SimpleNamespace(from_dict=lambda _values: cli),
    )
    monkeypatch.setattr(
        entrypoint, "_verify_checkout", lambda value: value.resolve(strict=True)
    )
    monkeypatch.setattr(entrypoint.importlib, "import_module", lambda _name: module)

    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="CLI contract differs"):
        entrypoint.execute_pinned_instance_only(
            harness_root=harness_root, config_path=config_path
        )
    assert ran == []
