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
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator, Mapping


PINNED_MULTI_SWE_REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"
UPSTREAM_MODULE = "multi_swe_bench.harness.run_evaluation"
UPSTREAM_MODULE_PATH = Path("multi_swe_bench/harness/run_evaluation.py")
FIX_PATCH_RUN_COMMAND = "bash -e /home/fix-run.sh"
IMMUTABLE_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")
TAGGED_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9._-]+$")
DOCKER_IMAGE_ID = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_CONFIG_FIELDS = frozenset(
    {
        "clear_env",
        "dataset_files",
        "force_build",
        "fix_patch_run_cmd",
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
        or config.get("fix_patch_run_cmd") != FIX_PATCH_RUN_COMMAND
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


def _canonical_exit_status(
    *,
    expected_image: str,
    expected_tag: str,
    image_id: str,
    status_code: int,
    submitted_patch: bytes,
) -> bytes:
    value = {
        "executed_image": expected_image,
        "expected_image": expected_image,
        "expected_tag": expected_tag,
        "image_id": image_id,
        "run_command": FIX_PATCH_RUN_COMMAND,
        "schema": "trimem/multi-swe-container-exit-status/1.0",
        "status_code": status_code,
        "submitted_patch_bytes": len(submitted_patch),
        "submitted_patch_sha256": hashlib.sha256(submitted_patch).hexdigest(),
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


class _ExitCheckedContainer:
    """Proxy a Docker SDK container and retain its exact terminal status."""

    def __init__(self, container: Any) -> None:
        self._container = container
        self.status_code: int | None = None

    def _capture_status(self) -> None:
        if self.status_code is not None:
            return
        result = self._container.wait()
        if (
            not isinstance(result, Mapping)
            or not {"StatusCode"} <= set(result) <= {"StatusCode", "Error"}
        ):
            raise MultiSWEEntrypointError("Docker wait result field set differs")
        wait_error = result.get("Error")
        if wait_error not in (None, {}):
            if (
                not isinstance(wait_error, Mapping)
                or set(wait_error) != {"Message"}
                or wait_error.get("Message") != ""
            ):
                raise MultiSWEEntrypointError("Docker wait returned an engine error")
        status_code = result.get("StatusCode")
        if type(status_code) is not int or not 0 <= status_code <= 255:
            raise MultiSWEEntrypointError("Docker container exit status is invalid")
        self.status_code = status_code

    def logs(self, *args: Any, **kwargs: Any) -> Any:
        if kwargs.get("stream") is True:
            if kwargs.get("follow") is not True:
                raise MultiSWEEntrypointError("Docker log-follow contract differs")
            stream = self._container.logs(*args, **kwargs)

            def checked_stream() -> Iterator[bytes]:
                for chunk in stream:
                    yield chunk
                self._capture_status()

            return checked_stream()
        value = self._container.logs(*args, **kwargs)
        self._capture_status()
        return value

    def wait(self, *args: Any, **kwargs: Any) -> Any:
        if args or kwargs:
            raise MultiSWEEntrypointError("Docker wait invocation contract differs")
        self._capture_status()
        return {"StatusCode": self.status_code}

    def remove(self, *args: Any, **kwargs: Any) -> Any:
        return self._container.remove(*args, **kwargs)


def _resolved_image_id(images: Any, reference: str) -> str:
    try:
        image = images.get(reference)
    except Exception as exc:
        raise MultiSWEEntrypointError(
            f"required preloaded Docker image is missing: {reference}"
        ) from exc
    image_id = getattr(image, "id", None)
    if not isinstance(image_id, str) or DOCKER_IMAGE_ID.fullmatch(image_id) is None:
        raise MultiSWEEntrypointError("resolved Docker image ID is invalid")
    return image_id


def _write_exclusive_fsynced(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        view = memoryview(raw)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise MultiSWEEntrypointError("container exit-status write made no progress")
            written += count
        os.fsync(descriptor)
    except FileExistsError as exc:
        raise MultiSWEEntrypointError("container exit-status output already exists") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _execute_guarded_cli(
    module: Any,
    cli: Any,
    *,
    expected_image: str,
    expected_tag: str,
    exit_status_path: Path,
) -> None:
    """Run pinned control flow while enforcing the immutable Docker boundary.

    The upstream ``run_instance`` still invokes its own ``docker_util.run``
    with the generated tag and submitted-patch bind.  This guarded proxy
    validates that exact call, substitutes the already-materialized digest for
    the actual container create, disables docker-py's pull fallback, and
    records the exact terminal StatusCode for the outer official grader.
    """

    if (
        IMMUTABLE_IMAGE.fullmatch(expected_image) is None
        or TAGGED_IMAGE.fullmatch(expected_tag) is None
        or "@" in expected_tag
        or expected_image.rsplit("@", 1)[0] != expected_tag.rsplit(":", 1)[0]
    ):
        raise MultiSWEEntrypointError("expected Docker image identity is invalid")
    expected_status_path = Path(str(cli.output_dir)).parent / "container-exit-status.json"
    if exit_status_path.resolve(strict=False) != expected_status_path.resolve(strict=False):
        raise MultiSWEEntrypointError("container exit-status output path differs")
    if exit_status_path.exists():
        raise MultiSWEEntrypointError("container exit-status output already exists")

    instances = list(cli.instances)
    if len(instances) != 1:
        raise MultiSWEEntrypointError("pinned Multi-SWE instance set differs")
    instance = instances[0]
    try:
        dependency = instance.dependency()
        generated_tag = dependency.image_full_name()
        instance_tag = instance.name()
        patch_destination = dependency.fix_patch_path()
        instance_dir = (
            Path(str(cli.workdir))
            / str(instance.pr.org)
            / str(instance.pr.repo)
            / "evals"
            / str(dependency.workdir())
        )
        patches = dict(cli.patches)
        instance_id = str(instance.pr.id)
        patch_value = patches[instance_id].fix_patch
    except (AttributeError, TypeError, ValueError) as exc:
        raise MultiSWEEntrypointError("pinned Multi-SWE instance identity differs") from exc
    if (
        generated_tag != expected_tag
        or instance_tag != expected_tag
        or patch_destination != "/home/fix.patch"
        or set(patches) != {instance_id}
        or not isinstance(patch_value, str)
        or not patch_value
    ):
        raise MultiSWEEntrypointError("pinned Multi-SWE generated image tag differs")
    expected_patch = patch_value.encode("utf-8")

    expected_patch_path = (instance_dir / "fix.patch").resolve(strict=False)
    expected_output_path = (instance_dir / "fix-patch-run.log").resolve(strict=False)
    docker_util = getattr(module, "docker_util", None)
    client = getattr(docker_util, "docker_client", None)
    images = getattr(client, "images", None)
    containers = getattr(client, "containers", None)
    original_run = getattr(docker_util, "run", None)
    original_exists = getattr(docker_util, "exists", None)
    original_build = getattr(docker_util, "build", None)
    original_docker_client = getattr(docker_util, "docker_client", None)
    original_pull = getattr(images, "pull", None)
    original_container_run = getattr(containers, "run", None)
    original_container_create = getattr(containers, "create", None)
    if not all(
        callable(value)
        for value in (
            original_run,
            original_exists,
            original_build,
            getattr(images, "get", None),
            original_pull,
            original_container_run,
            original_container_create,
        )
    ):
        raise MultiSWEEntrypointError("pinned Docker SDK boundary is unavailable")

    upstream_run_calls = 0
    container_run_calls = 0
    container_create_calls = 0
    container_start_calls = 0
    active_container: _ExitCheckedContainer | None = None

    def forbidden_pull(*_args: Any, **_kwargs: Any) -> Any:
        raise MultiSWEEntrypointError("Docker image pull fallback is prohibited")

    def forbidden_exists(*_args: Any, **_kwargs: Any) -> Any:
        raise MultiSWEEntrypointError("instance_only entered image-existence/build path")

    def forbidden_build(*_args: Any, **_kwargs: Any) -> Any:
        raise MultiSWEEntrypointError("instance_only entered source-image build path")

    def guarded_container_run(*args: Any, **kwargs: Any) -> _ExitCheckedContainer:
        nonlocal active_container, container_run_calls
        nonlocal container_create_calls, container_start_calls
        container_run_calls += 1
        if args or container_run_calls != 1:
            raise MultiSWEEntrypointError("Docker container-run invocation count differs")
        if (
            kwargs.get("image") != expected_image
            or kwargs.get("command") != FIX_PATCH_RUN_COMMAND
            or kwargs.get("remove") is not False
            or kwargs.get("detach") is not True
            or kwargs.get("stdout") is not True
            or kwargs.get("stderr") is not True
            or kwargs.get("environment") != []
            or kwargs.get("volumes")
            != {expected_patch_path: {"bind": "/home/fix.patch", "mode": "rw"}}
            or set(kwargs)
            != {
                "image",
                "command",
                "remove",
                "detach",
                "stdout",
                "stderr",
                "environment",
                "volumes",
            }
        ):
            raise MultiSWEEntrypointError("Docker container-run contract differs")
        if expected_patch_path.is_symlink():
            raise MultiSWEEntrypointError("submitted-patch mount source became a symlink")
        try:
            create_time_patch = expected_patch_path.read_bytes()
        except OSError as exc:
            raise MultiSWEEntrypointError(
                "submitted-patch mount source became unreadable"
            ) from exc
        if create_time_patch != expected_patch:
            raise MultiSWEEntrypointError(
                "submitted-patch mount bytes changed before container create"
            )
        # Do not call ContainerCollection.run: docker-py catches ImageNotFound
        # there and automatically invokes images.pull.  Direct create/start
        # preserves the pinned digest and lets a missing local image fail.
        container_create_calls += 1
        raw_container = original_container_create(
            image=expected_image,
            command=FIX_PATCH_RUN_COMMAND,
            environment=[],
            volumes={expected_patch_path: {"bind": "/home/fix.patch", "mode": "rw"}},
        )
        if container_create_calls != 1 or not callable(getattr(raw_container, "start", None)):
            raise MultiSWEEntrypointError("Docker container-create contract differs")
        try:
            raw_container.start()
        except Exception:
            try:
                raw_container.remove(force=True)
            except Exception as cleanup_exc:
                raise MultiSWEEntrypointError(
                    "Docker container start failed and cleanup failed"
                ) from cleanup_exc
            raise
        container_start_calls += 1
        active_container = _ExitCheckedContainer(raw_container)
        return active_container

    def guarded_upstream_run(
        image_full_name: str,
        run_command: str,
        output_path: Path | None = None,
        global_env: list[str] | None = None,
        volumes: Mapping[Path, Mapping[str, str]] | None = None,
    ) -> str:
        nonlocal upstream_run_calls
        upstream_run_calls += 1
        if (
            upstream_run_calls != 1
            or image_full_name != expected_tag
            or run_command != FIX_PATCH_RUN_COMMAND
            or output_path is None
            or Path(output_path).resolve(strict=False) != expected_output_path
            or global_env != []
            or volumes is None
            or len(volumes) != 1
        ):
            raise MultiSWEEntrypointError("pinned docker_util.run contract differs")
        [(host_path, binding)] = volumes.items()
        if (
            Path(host_path).resolve(strict=False) != expected_patch_path
            or dict(binding) != {"bind": "/home/fix.patch", "mode": "rw"}
        ):
            raise MultiSWEEntrypointError("submitted-patch mount contract differs")
        if Path(host_path).is_symlink():
            raise MultiSWEEntrypointError("submitted-patch mount source is a symlink")
        try:
            mounted_patch = Path(host_path).read_bytes()
        except OSError as exc:
            raise MultiSWEEntrypointError("submitted-patch mount source is unreadable") from exc
        if mounted_patch != expected_patch:
            raise MultiSWEEntrypointError("submitted-patch mount bytes differ from prediction")
        output = original_run(
            expected_image,
            FIX_PATCH_RUN_COMMAND,
            output_path,
            [],
            volumes={expected_patch_path: {"bind": "/home/fix.patch", "mode": "rw"}},
        )
        if active_container is None or active_container.status_code is None:
            raise MultiSWEEntrypointError("Docker container exit status was not captured")
        if not isinstance(output, str):
            raise MultiSWEEntrypointError("pinned docker_util.run output type differs")
        return output

    class GuardedImages:
        def get(self, reference: str) -> Any:
            return images.get(reference)

        def pull(self, *args: Any, **kwargs: Any) -> Any:
            return forbidden_pull(*args, **kwargs)

    class GuardedContainers:
        def run(self, *args: Any, **kwargs: Any) -> _ExitCheckedContainer:
            return guarded_container_run(*args, **kwargs)

    class GuardedDockerClient:
        images = GuardedImages()
        containers = GuardedContainers()

        def __getattr__(self, name: str) -> Any:
            raise MultiSWEEntrypointError(
                f"unexpected Docker client surface accessed: {name}"
            )

    docker_util.docker_client = GuardedDockerClient()
    docker_util.exists = forbidden_exists
    docker_util.build = forbidden_build
    docker_util.run = guarded_upstream_run
    containers.run = guarded_container_run
    try:
        digest_id = _resolved_image_id(images, expected_image)
        tag_id = _resolved_image_id(images, expected_tag)
        if digest_id != tag_id:
            raise MultiSWEEntrypointError(
                "expected Docker tag and immutable digest resolve to different image IDs"
            )
        cli.run()
        if (
            upstream_run_calls != 1
            or container_run_calls != 1
            or container_create_calls != 1
            or container_start_calls != 1
            or active_container is None
            or active_container.status_code is None
        ):
            raise MultiSWEEntrypointError("pinned container execution count differs")
        _write_exclusive_fsynced(
            exit_status_path,
            _canonical_exit_status(
                expected_image=expected_image,
                expected_tag=expected_tag,
                image_id=digest_id,
                status_code=active_container.status_code,
                submitted_patch=expected_patch,
            ),
        )
    finally:
        containers.run = original_container_run
        docker_util.docker_client = original_docker_client
        docker_util.run = original_run
        docker_util.build = original_build
        docker_util.exists = original_exists


def execute_pinned_instance_only(
    *,
    harness_root: Path,
    config_path: Path,
    expected_image: str,
    expected_tag: str,
    exit_status_path: Path,
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
        or cli.fix_patch_run_cmd != FIX_PATCH_RUN_COMMAND
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
    _execute_guarded_cli(
        module,
        cli,
        expected_image=expected_image,
        expected_tag=expected_tag,
        exit_status_path=exit_status_path,
    )
    return cli


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-image", required=True)
    parser.add_argument("--expected-tag", required=True)
    parser.add_argument("--exit-status-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        execute_pinned_instance_only(
            harness_root=args.harness_root,
            config_path=args.config,
            expected_image=args.expected_image,
            expected_tag=args.expected_tag,
            exit_status_path=args.exit_status_output,
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
