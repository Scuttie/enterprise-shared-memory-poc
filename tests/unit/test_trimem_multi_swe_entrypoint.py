from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_multi_swe_entrypoint as entrypoint  # noqa: E402


EXPECTED_IMAGE = "mswebench/vuejs_m_core@sha256:" + "1" * 64
EXPECTED_TAG = "mswebench/vuejs_m_core:pr-8911"


class _PinnedArgumentParser(argparse.ArgumentParser):
    """Minimal faithful form of pinned args_util.ArgumentParser.

    Its unusual ``use_config`` first positional parameter is the regression
    boundary under test.  The config/environment loading order and strict
    default-only replacement match the pinned upstream implementation.
    """

    def __init__(self, use_config: bool = True, *args: object, **kwargs: object):
        super().__init__(*args, **kwargs)
        if use_config:
            self.add_argument("--config", type=Path, default=None)

    def parse_args(
        self, use_config: bool = True, *args: object, **kwargs: object
    ) -> argparse.Namespace:
        parsed = super().parse_args(*args, **kwargs)
        if use_config:
            if parsed.config:
                self.load_from_config_file(parsed, parsed.config)
            self.load_from_env_variables(parsed)
        return parsed

    def load_from_config_file(
        self, parsed: argparse.Namespace, file_path: Path, strict: bool = True
    ) -> None:
        config = json.loads(file_path.read_text(encoding="utf-8"))
        for key, value in config.items():
            if strict and not hasattr(parsed, key):
                raise ValueError(f"invalid config key: {key}")
            if getattr(parsed, key) == self.get_default(key):
                setattr(parsed, key, value)

    def load_from_env_variables(self, parsed: argparse.Namespace) -> None:
        for key in vars(parsed):
            env_value = os.getenv(key.replace("-", "_").upper())
            if env_value is not None and getattr(parsed, key) == self.get_default(key):
                setattr(parsed, key, env_value)


def _configure_pinned_parser(
    parser: _PinnedArgumentParser,
) -> _PinnedArgumentParser:
    defaults: dict[str, object] = {
        "clear_env": True,
        "dataset_files": None,
        "fix_patch_run_cmd": "",
        "force_build": False,
        "global_env": None,
        "human_mode": True,
        "log_dir": None,
        "log_level": "INFO",
        "log_to_console": True,
        "max_workers": 8,
        "max_workers_build_image": 8,
        "max_workers_run_instance": 8,
        "mode": "evaluation",
        "need_clone": True,
        "output_dir": None,
        "patch_files": None,
        "repo_dir": None,
        "skips": None,
        "specifics": None,
        "stop_on_error": True,
        "workdir": None,
    }
    for name, default in defaults.items():
        parser.add_argument(f"--{name}", default=default)
    return parser


def _pinned_parser() -> _PinnedArgumentParser:
    return _configure_pinned_parser(_PinnedArgumentParser())


def _config(root: Path) -> dict[str, object]:
    return {
        "clear_env": True,
        "dataset_files": [str(root / "dataset.jsonl")],
        "fix_patch_run_cmd": entrypoint.FIX_PATCH_RUN_COMMAND,
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


def test_pinned_argument_parser_requires_argv_bound_by_keyword(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    signature = inspect.signature(_PinnedArgumentParser.parse_args)
    assert tuple(signature.parameters) == ("self", "use_config", "args", "kwargs")
    assert signature.parameters["use_config"].default is True
    assert signature.parameters["args"].kind is inspect.Parameter.VAR_POSITIONAL
    assert signature.parameters["kwargs"].kind is inspect.Parameter.VAR_KEYWORD

    config_path = tmp_path / "config.json"
    _write_config(config_path, {"mode": "instance_only"})
    monkeypatch.setattr(sys, "argv", ["wrapper", "--wrapper-only-option"])

    with pytest.raises(SystemExit):
        # This is the former bug: the list binds to ``use_config`` rather than
        # argparse's ``args`` and process argv is consumed instead.
        _pinned_parser().parse_args(["--config", str(config_path)])

    parsed = _pinned_parser().parse_args(
        args=["--config", str(config_path)]
    )
    assert parsed.config == config_path
    assert parsed.mode == "instance_only"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("mode", "evaluation"),
        ("force_build", True),
        ("human_mode", False),
        ("need_clone", True),
        ("max_workers_run_instance", 2),
        ("fix_patch_run_cmd", "bash /home/fix-run.sh"),
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

    class RecordingParser(_PinnedArgumentParser):
        def parse_args(
            self, use_config: bool = True, *args: object, **kwargs: object
        ) -> argparse.Namespace:
            calls.append("get_parser.parse_args")
            return super().parse_args(use_config, *args, **kwargs)

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
        fix_patch_run_cmd = entrypoint.FIX_PATCH_RUN_COMMAND
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
            assert values["config"] == config_path
            assert values["fix_patch_run_cmd"] == entrypoint.FIX_PATCH_RUN_COMMAND
            assert {key: values[key] for key in config} == config
            calls.append("CliArgs.from_dict")
            return Cli()

    upstream_main_calls: list[str] = []
    module = types.SimpleNamespace(
        __file__=str(module_path),
        get_parser=lambda: _configure_pinned_parser(RecordingParser()),
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
    guarded: list[tuple[str, str, Path]] = []

    def execute_guard(
        _module: object,
        guarded_cli: Cli,
        *,
        expected_image: str,
        expected_tag: str,
        exit_status_path: Path,
    ) -> None:
        guarded.append((expected_image, expected_tag, exit_status_path))
        guarded_cli.run()

    monkeypatch.setattr(entrypoint, "_execute_guarded_cli", execute_guard)
    status_path = tmp_path / "container-exit-status.json"

    returned = entrypoint.execute_pinned_instance_only(
        harness_root=harness_root,
        config_path=config_path,
        expected_image=EXPECTED_IMAGE,
        expected_tag=EXPECTED_TAG,
        exit_status_path=status_path,
    )

    assert isinstance(returned, Cli)
    assert calls == ["get_parser.parse_args", "CliArgs.from_dict", "CliArgs.run"]
    assert guarded == [(EXPECTED_IMAGE, EXPECTED_TAG, status_path)]
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
        fix_patch_run_cmd=entrypoint.FIX_PATCH_RUN_COMMAND,
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
            parse_args=lambda *, args: types.SimpleNamespace(config=config_path)
        ),
        CliArgs=types.SimpleNamespace(from_dict=lambda _values: cli),
    )
    monkeypatch.setattr(
        entrypoint, "_verify_checkout", lambda value: value.resolve(strict=True)
    )
    monkeypatch.setattr(entrypoint.importlib, "import_module", lambda _name: module)

    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="CLI contract differs"):
        entrypoint.execute_pinned_instance_only(
            harness_root=harness_root,
            config_path=config_path,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=tmp_path / "container-exit-status.json",
        )
    assert ran == []


class _ImageCollection:
    def __init__(self, *, tag_present: bool = True, same_id: bool = True) -> None:
        self.tag_present = tag_present
        self.same_id = same_id
        self.get_calls: list[str] = []
        self.pull_calls = 0

    def get(self, reference: str) -> object:
        self.get_calls.append(reference)
        if reference == EXPECTED_TAG and not self.tag_present:
            raise LookupError(reference)
        suffix = "2" if reference == EXPECTED_IMAGE or self.same_id else "3"
        return types.SimpleNamespace(id="sha256:" + suffix * 64)

    def pull(self, *_args: object, **_kwargs: object) -> object:
        self.pull_calls += 1
        raise AssertionError("pull must never be called")


class _RawContainer:
    def __init__(
        self,
        status_code: int,
        wait_error: object = None,
        start_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.wait_error = wait_error
        self.start_error = start_error
        self.removed = False
        self.started = False

    def start(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def logs(self, *, stream: bool = False, follow: bool = False) -> object:
        assert stream is True and follow is True
        return iter([b"complete mocked test output\n"])

    def wait(self) -> dict[str, object]:
        result: dict[str, object] = {"StatusCode": self.status_code}
        if self.wait_error is not None:
            result["Error"] = self.wait_error
        return result

    def remove(self, *, force: bool) -> None:
        assert force is True
        self.removed = True


class _ContainerCollection:
    def __init__(
        self,
        status_code: int,
        wait_error: object = None,
        start_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.wait_error = wait_error
        self.start_error = start_error
        self.calls: list[dict[str, object]] = []
        self.created: list[_RawContainer] = []

    def create(self, **kwargs: object) -> _RawContainer:
        self.calls.append(dict(kwargs))
        container = _RawContainer(
            self.status_code,
            self.wait_error,
            self.start_error,
        )
        self.created.append(container)
        return container

    def run(self, **_kwargs: object) -> _RawContainer:
        raise AssertionError("ContainerCollection.run auto-pull surface must not be called")


def _guard_fixture(
    tmp_path: Path,
    *,
    status_code: int = 0,
    tag_present: bool = True,
    same_id: bool = True,
    wait_error: object = None,
    start_error: Exception | None = None,
    command: str = entrypoint.FIX_PATCH_RUN_COMMAND,
    mount_destination: str = "/home/fix.patch",
    mounted_patch: str = "diff --git a/a b/a\n",
) -> tuple[object, object, Path, _ImageCollection, _ContainerCollection]:
    images = _ImageCollection(tag_present=tag_present, same_id=same_id)
    containers = _ContainerCollection(status_code, wait_error, start_error)
    client = types.SimpleNamespace(images=images, containers=containers)
    docker_util = types.SimpleNamespace(docker_client=client)

    def original_run(
        image_full_name: str,
        run_command: str,
        output_path: Path | None = None,
        global_env: list[str] | None = None,
        volumes: dict[Path, dict[str, str]] | None = None,
    ) -> str:
        container = docker_util.docker_client.containers.run(
            image=image_full_name,
            command=run_command,
            remove=False,
            detach=True,
            stdout=True,
            stderr=True,
            environment=global_env,
            volumes=volumes,
        )
        output = ""
        try:
            assert output_path is not None
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8", newline="\n") as stream:
                for raw in container.logs(stream=True, follow=True):
                    decoded = raw.decode("utf-8")
                    stream.write(decoded)
                    output += decoded
            return output
        finally:
            container.remove(force=True)

    docker_util.run = original_run
    docker_util.exists = lambda _image: True
    docker_util.build = lambda *_args, **_kwargs: None

    workdir = tmp_path / "work"
    output_dir = tmp_path / "output"
    dependency = types.SimpleNamespace(
        image_full_name=lambda: EXPECTED_TAG,
        fix_patch_path=lambda: "/home/fix.patch",
        workdir=lambda: "pr-8911",
    )
    instance = types.SimpleNamespace(
        pr=types.SimpleNamespace(org="vuejs", repo="core", id="vuejs/core:pr-8911"),
        dependency=lambda: dependency,
        name=lambda: EXPECTED_TAG,
    )
    expected_patch = "diff --git a/a b/a\n"
    cli = types.SimpleNamespace(
        output_dir=output_dir,
        workdir=workdir,
        instances=[instance],
        patches={instance.pr.id: types.SimpleNamespace(fix_patch=expected_patch)},
    )

    def run() -> None:
        patch_path = workdir / "vuejs/core/evals/pr-8911/fix.patch"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_text(mounted_patch, encoding="utf-8", newline="\n")
        docker_util.run(
            EXPECTED_TAG,
            command,
            workdir / "vuejs/core/evals/pr-8911/fix-patch-run.log",
            [],
            volumes={patch_path: {"bind": mount_destination, "mode": "rw"}},
        )

    cli.run = run
    return (
        types.SimpleNamespace(docker_util=docker_util),
        cli,
        tmp_path / "container-exit-status.json",
        images,
        containers,
    )


def test_runtime_guard_executes_digest_and_records_zero_status(tmp_path: Path) -> None:
    module, cli, status_path, images, containers = _guard_fixture(tmp_path)

    entrypoint._execute_guarded_cli(
        module,
        cli,
        expected_image=EXPECTED_IMAGE,
        expected_tag=EXPECTED_TAG,
        exit_status_path=status_path,
    )

    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status == {
        "executed_image": EXPECTED_IMAGE,
        "expected_image": EXPECTED_IMAGE,
        "expected_tag": EXPECTED_TAG,
        "image_id": "sha256:" + "2" * 64,
        "run_command": "bash -e /home/fix-run.sh",
        "schema": "trimem/multi-swe-container-exit-status/1.0",
        "status_code": 0,
        "submitted_patch_bytes": len("diff --git a/a b/a\n".encode()),
        "submitted_patch_sha256": hashlib.sha256(b"diff --git a/a b/a\n").hexdigest(),
    }
    assert images.get_calls == [EXPECTED_IMAGE, EXPECTED_TAG]
    assert images.pull_calls == 0
    assert len(containers.calls) == 1
    assert len(containers.created) == 1
    assert containers.created[0].started is True
    assert containers.calls[0]["image"] == EXPECTED_IMAGE
    assert containers.calls[0]["command"] == "bash -e /home/fix-run.sh"
    assert set(containers.calls[0]) == {"image", "command", "environment", "volumes"}


def test_runtime_guard_restores_original_container_run_after_success(
    tmp_path: Path,
) -> None:
    module, cli, status_path, _images, containers = _guard_fixture(tmp_path)
    original_client = module.docker_util.docker_client
    original_container_run = containers.run

    entrypoint._execute_guarded_cli(
        module,
        cli,
        expected_image=EXPECTED_IMAGE,
        expected_tag=EXPECTED_TAG,
        exit_status_path=status_path,
    )

    assert module.docker_util.docker_client is original_client
    assert containers.run == original_container_run


def test_runtime_guard_restores_original_container_run_after_failure(
    tmp_path: Path,
) -> None:
    module, cli, status_path, _images, containers = _guard_fixture(
        tmp_path, same_id=False
    )
    original_client = module.docker_util.docker_client
    original_container_run = containers.run

    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="different image IDs"):
        entrypoint._execute_guarded_cli(
            module,
            cli,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=status_path,
        )

    assert module.docker_util.docker_client is original_client
    assert containers.run == original_container_run


def test_runtime_guard_records_nonzero_for_later_full_domain_validation(
    tmp_path: Path,
) -> None:
    module, cli, status_path, _images, _containers = _guard_fixture(
        tmp_path, status_code=1
    )
    entrypoint._execute_guarded_cli(
        module,
        cli,
        expected_image=EXPECTED_IMAGE,
        expected_tag=EXPECTED_TAG,
        exit_status_path=status_path,
    )
    assert json.loads(status_path.read_text(encoding="utf-8"))["status_code"] == 1


def test_runtime_guard_missing_tag_fails_without_pull(tmp_path: Path) -> None:
    module, cli, status_path, images, containers = _guard_fixture(
        tmp_path, tag_present=False
    )
    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="image is missing"):
        entrypoint._execute_guarded_cli(
            module,
            cli,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=status_path,
        )
    assert images.pull_calls == 0
    assert containers.calls == []
    assert not status_path.exists()


def test_runtime_guard_rejects_tag_digest_image_id_mismatch(tmp_path: Path) -> None:
    module, cli, status_path, _images, containers = _guard_fixture(
        tmp_path, same_id=False
    )
    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="different image IDs"):
        entrypoint._execute_guarded_cli(
            module,
            cli,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=status_path,
        )
    assert containers.calls == []


@pytest.mark.parametrize(
    ("command", "destination", "patch", "message"),
    [
        ("bash /home/fix-run.sh", "/home/fix.patch", "diff --git a/a b/a\n", "run contract"),
        (entrypoint.FIX_PATCH_RUN_COMMAND, "/tmp/fix.patch", "diff --git a/a b/a\n", "mount contract"),
        (entrypoint.FIX_PATCH_RUN_COMMAND, "/home/fix.patch", "changed\n", "mount bytes differ"),
    ],
)
def test_runtime_guard_rejects_command_mount_and_patch_drift(
    tmp_path: Path,
    command: str,
    destination: str,
    patch: str,
    message: str,
) -> None:
    module, cli, status_path, _images, containers = _guard_fixture(
        tmp_path,
        command=command,
        mount_destination=destination,
        mounted_patch=patch,
    )
    with pytest.raises(entrypoint.MultiSWEEntrypointError, match=message):
        entrypoint._execute_guarded_cli(
            module,
            cli,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=status_path,
        )
    assert containers.calls == []
    assert not status_path.exists()


def test_runtime_guard_accepts_empty_optional_wait_error(tmp_path: Path) -> None:
    module, cli, status_path, _images, _containers = _guard_fixture(
        tmp_path, wait_error={"Message": ""}
    )
    entrypoint._execute_guarded_cli(
        module,
        cli,
        expected_image=EXPECTED_IMAGE,
        expected_tag=EXPECTED_TAG,
        exit_status_path=status_path,
    )
    assert status_path.is_file()


def test_runtime_guard_rejects_engine_wait_error(tmp_path: Path) -> None:
    module, cli, status_path, _images, _containers = _guard_fixture(
        tmp_path, wait_error={"Message": "daemon wait failed"}
    )
    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="engine error"):
        entrypoint._execute_guarded_cli(
            module,
            cli,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=status_path,
        )
    assert not status_path.exists()


def test_runtime_guard_rechecks_patch_bytes_immediately_before_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, cli, status_path, _images, containers = _guard_fixture(tmp_path)
    original_read_bytes = Path.read_bytes
    patch_reads = 0

    def changing_read_bytes(path: Path) -> bytes:
        nonlocal patch_reads
        raw = original_read_bytes(path)
        if path.name == "fix.patch":
            patch_reads += 1
            if patch_reads == 2:
                return b"changed after upstream guard\n"
        return raw

    monkeypatch.setattr(Path, "read_bytes", changing_read_bytes)
    with pytest.raises(entrypoint.MultiSWEEntrypointError, match="changed before container create"):
        entrypoint._execute_guarded_cli(
            module,
            cli,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=status_path,
        )
    assert patch_reads == 2
    assert containers.calls == []
    assert not status_path.exists()


def test_runtime_guard_removes_created_container_when_start_fails(
    tmp_path: Path,
) -> None:
    start_error = RuntimeError("mocked Docker start failure")
    module, cli, status_path, images, containers = _guard_fixture(
        tmp_path,
        start_error=start_error,
    )
    with pytest.raises(RuntimeError, match="mocked Docker start failure"):
        entrypoint._execute_guarded_cli(
            module,
            cli,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=status_path,
        )
    assert images.pull_calls == 0
    assert len(containers.calls) == 1
    assert len(containers.created) == 1
    assert containers.created[0].started is False
    assert containers.created[0].removed is True
    assert not status_path.exists()


def test_runtime_guard_cannot_be_bypassed_by_fresh_docker_collections(
    tmp_path: Path,
) -> None:
    module, cli, status_path, _images, _containers = _guard_fixture(tmp_path)
    backing_images = _ImageCollection()
    backing_containers = _ContainerCollection(0)

    class FreshImages:
        def get(self, reference: str) -> object:
            return backing_images.get(reference)

        def pull(self, *args: object, **kwargs: object) -> object:
            return backing_images.pull(*args, **kwargs)

    class FreshContainers:
        def create(self, **kwargs: object) -> _RawContainer:
            return backing_containers.create(**kwargs)

        def run(self, **kwargs: object) -> _RawContainer:
            return backing_containers.run(**kwargs)

    class FreshDockerClient:
        image_collection_accesses = 0
        container_collection_accesses = 0

        @property
        def images(self) -> FreshImages:
            self.image_collection_accesses += 1
            return FreshImages()

        @property
        def containers(self) -> FreshContainers:
            self.container_collection_accesses += 1
            return FreshContainers()

    client = FreshDockerClient()
    module.docker_util.docker_client = client

    entrypoint._execute_guarded_cli(
        module,
        cli,
        expected_image=EXPECTED_IMAGE,
        expected_tag=EXPECTED_TAG,
        exit_status_path=status_path,
    )

    assert client.image_collection_accesses == 1
    assert client.container_collection_accesses == 1
    assert backing_images.pull_calls == 0
    assert len(backing_containers.calls) == 1
    assert backing_containers.calls[0]["image"] == EXPECTED_IMAGE
    assert backing_containers.created[0].started is True
