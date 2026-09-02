"""Credential-free rehearsal of the exact frozen Multi-SWE Vue smoke input.

This module loads the digest-locked upstream dataset row, binds it to the
committed smoke manifest and image lock, and calls the production invocation
builder.  It executes the pinned evaluator's Python control flow behind
Docker/build/session spies, but never calls ``grade()``, starts a container,
runs an official test/report, or calls a model. Gold/test/submitted patch
payloads remain in a temporary directory and are removed before the
allowlisted report is written.
"""
from __future__ import annotations

import argparse
import builtins
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from trimem_grader_smoke_protocol import (  # noqa: E402
    NOOP_BASELINE_LOCK,
    NOOP_BASELINE_PATCH,
    validate_serial_targets,
)
from trimem_multi_swe_entrypoint import (  # noqa: E402
    FIX_PATCH_RUN_COMMAND,
    execute_pinned_instance_only,
)
from trimem_official_grader import (  # noqa: E402
    MULTI_HARNESS_REVISION,
    MULTI_SWE_PREBUILT_EVALUATION,
    FrozenOfficialTarget,
    OfficialHarnessGraderGateway,
    build_harness_invocation,
    canonical_row_hash,
)
from trimem_select_targets import download_locked  # noqa: E402


MANIFEST_PATH = ROOT / "configs/trimem_v1/grader_smoke_manifest.json"
GRADER_LOCK_PATH = ROOT / "configs/trimem_v1/grader_lock.json"
IMAGE_LOCK_PATH = ROOT / "artifacts/trimem_v1/grader_image_lock.json"
ENTRYPOINT_PATH = ROOT / "scripts/trimem_multi_swe_entrypoint.py"

BENCHMARK_ID = "multi_swe_bench_mini"
INSTANCE_ID = "vuejs__core-8911"
REPOSITORY = "vuejs/core"
BASE_COMMIT = "3be4e3cbe34b394096210897c1be8deeb6d748d8"
EXPECTED_IMAGE = (
    "mswebench/vuejs_m_core@sha256:"
    "2883a52a2eb4054e820dc3a88f9fb0b93fbef7ce10801a57e718f1c6d9f8e9c1"
)
EXPECTED_TAG = "mswebench/vuejs_m_core:pr-8911"
EXPECTED_DIGEST = EXPECTED_IMAGE.rsplit("@", 1)[1]
SHA256 = re.compile(r"[0-9a-f]{64}")


class PreexecError(ValueError):
    """The frozen row, production builder, or zero-execution boundary drifted."""


def _strict_object(path: Path) -> dict[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise PreexecError(f"duplicate JSON key in {path.name}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreexecError(f"cannot load exact JSON contract: {path.name}") from exc
    if not isinstance(value, dict):
        raise PreexecError(f"JSON contract is not an object: {path.name}")
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _frozen_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _strict_object(MANIFEST_PATH)
    targets = manifest.get("targets")
    if not isinstance(targets, list):
        raise PreexecError("grader-smoke manifest has no exact target matrix")
    try:
        validate_serial_targets(
            matrix_kind=manifest.get("matrix_kind"),
            noop_baseline=manifest.get("noop_baseline"),
            targets=targets,
        )
    except ValueError as exc:
        raise PreexecError("grader-smoke target matrix is not frozen") from exc
    vue_rows = [
        dict(row)
        for row in targets
        if isinstance(row, Mapping)
        and row.get("benchmark_id") == BENCHMARK_ID
        and row.get("instance_id") == INSTANCE_ID
    ]
    if (
        len(vue_rows) != 2
        or [row.get("probe") for row in vue_rows] != ["GOLD", "NOOP_BASELINE"]
        or any(row.get("repository") != REPOSITORY for row in vue_rows)
        or any(row.get("base_commit") != BASE_COMMIT for row in vue_rows)
    ):
        raise PreexecError("frozen Vue GOLD/NOOP identity pair differs")
    identity_fields = (
        "base_commit",
        "benchmark_id",
        "dataset_revision",
        "instance_id",
        "repository",
        "source_row_sha256",
    )
    if any(vue_rows[0][field] != vue_rows[1][field] for field in identity_fields):
        raise PreexecError("frozen Vue probe-pair source identity differs")

    grader_lock = _strict_object(GRADER_LOCK_PATH)
    dataset_specs = grader_lock.get("dataset_files")
    matching_specs = [
        dict(row)
        for row in dataset_specs
        if isinstance(row, Mapping) and row.get("benchmark_id") == BENCHMARK_ID
    ] if isinstance(dataset_specs, list) else []
    if (
        len(matching_specs) != 1
        or matching_specs[0].get("dataset_revision") != vue_rows[0]["dataset_revision"]
        or not isinstance(matching_specs[0].get("bytes"), int)
        or SHA256.fullmatch(str(matching_specs[0].get("sha256"))) is None
    ):
        raise PreexecError("pinned Vue dataset file binding differs")

    image_lock = _strict_object(IMAGE_LOCK_PATH)
    image_rows = image_lock.get("targets")
    matching_images = [
        dict(row)
        for row in image_rows
        if isinstance(row, Mapping)
        and row.get("benchmark_id") == BENCHMARK_ID
        and row.get("instance_id") == INSTANCE_ID
    ] if isinstance(image_rows, list) else []
    if len(matching_images) != 1:
        raise PreexecError("frozen Vue image binding is missing or duplicated")
    image = matching_images[0]
    if (
        image.get("image") != EXPECTED_IMAGE
        or image.get("harness_image_tag") != EXPECTED_TAG
        or image.get("expected_digest") != EXPECTED_DIGEST
        or set(image.get("target_ids", [])) != {row["target_id"] for row in vue_rows}
    ):
        raise PreexecError("frozen Vue immutable image identity differs")
    return vue_rows[1], matching_specs[0], image


def _load_exact_row(spec: Mapping[str, Any], cache_dir: Path) -> dict[str, Any]:
    source_path = download_locked(spec, cache_dir)
    matches: list[dict[str, Any]] = []

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise PreexecError("duplicate key in pinned dataset row")
            result[key] = value
        return result

    try:
        with source_path.open("r", encoding="utf-8", newline="") as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line, object_pairs_hook=pairs)
                if isinstance(row, dict) and row.get("instance_id") == INSTANCE_ID:
                    matches.append(row)
                    if len(matches) > 1:
                        break
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreexecError("pinned Vue dataset row cannot be decoded") from exc
    if len(matches) != 1:
        raise PreexecError("pinned Vue dataset row is missing or duplicated")
    return matches[0]


def _exercise_pinned_control_flow(
    *, harness_root: Path, config_path: Path, expected_patch: bytes
) -> dict[str, Any]:
    """Run the pinned Python dispatch with every Docker boundary replaced by spies."""

    harness_root = harness_root.resolve(strict=True)
    import docker

    image_get_calls: list[str] = []
    image_pull_calls = 0
    container_create_calls: list[dict[str, Any]] = []
    container_start_calls = 0
    container_wait_calls = 0

    class _MockImage:
        id = "sha256:" + "a" * 64

    class _MockImages:
        def get(self, reference: str) -> _MockImage:
            image_get_calls.append(reference)
            if reference not in {EXPECTED_IMAGE, EXPECTED_TAG}:
                raise PreexecError("rehearsal requested an unfrozen Docker image")
            return _MockImage()

        def pull(self, *_args: object, **_kwargs: object) -> None:
            nonlocal image_pull_calls
            image_pull_calls += 1
            raise PreexecError("rehearsal attempted a Docker image pull")

    class _MockContainer:
        def start(self) -> None:
            nonlocal container_start_calls
            container_start_calls += 1

        def logs(self, *, stream: bool, follow: bool) -> Any:
            if stream is not True or follow is not True:
                raise PreexecError("rehearsal Docker log contract differs")
            return iter([b"credential-free mocked container output\n"])

        def wait(self) -> dict[str, int]:
            nonlocal container_wait_calls
            container_wait_calls += 1
            return {"StatusCode": 0}

        @staticmethod
        def remove(*, force: bool) -> None:
            if force is not True:
                raise PreexecError("rehearsal Docker cleanup contract differs")

    class _MockContainers:
        def create(self, **kwargs: Any) -> _MockContainer:
            container_create_calls.append(dict(kwargs))
            return _MockContainer()

        @staticmethod
        def run(**_kwargs: Any) -> _MockContainer:
            raise PreexecError("ContainerCollection.run auto-pull surface was called")

    class _NoDockerClient:
        def __init__(self) -> None:
            self.images = _MockImages()
            self.containers = _MockContainers()

    docker_factory_calls = 0
    original_from_env = docker.from_env

    def no_docker_factory(*_args: object, **_kwargs: object) -> _NoDockerClient:
        nonlocal docker_factory_calls
        docker_factory_calls += 1
        return _NoDockerClient()

    docker.from_env = no_docker_factory
    sys.path.insert(0, str(harness_root))
    try:
        try:
            run_module = importlib.import_module(
                "multi_swe_bench.harness.run_evaluation"
            )
            session_module = importlib.import_module(
                "multi_swe_bench.utils.session_util"
            )
        finally:
            docker.from_env = original_from_env
    except BaseException:
        if sys.path and sys.path[0] == str(harness_root):
            sys.path.pop(0)
        raise
    module_path = Path(run_module.__file__).resolve()
    if harness_root not in module_path.parents:
        raise PreexecError("pinned control-flow module escaped the exact checkout")

    docker_util = run_module.docker_util
    original_run = docker_util.run
    original_exists = docker_util.exists
    original_build = docker_util.build
    original_session = session_module.run_and_save_logs
    original_open = builtins.open
    run_calls: list[dict[str, Any]] = []
    exists_calls: list[str] = []
    source_build_calls = 0
    session_calls = 0
    host_prepare_reads = 0
    baked_fixture_patch = (
        b"diff --git a/image-baked.txt b/image-baked.txt\n"
        b"new file mode 100644\n"
        b"--- /dev/null\n"
        b"+++ b/image-baked.txt\n"
        b"@@ -0,0 +1 @@\n"
        b"+image-baked-fixture-must-not-be-used\n"
    )
    if baked_fixture_patch == expected_patch:
        raise PreexecError("submitted and baked-fixture patches are not distinct")

    def mocked_exists(image_name: str) -> bool:
        exists_calls.append(image_name)
        return image_name == EXPECTED_TAG

    def forbidden_build(*_args: object, **_kwargs: object) -> None:
        nonlocal source_build_calls
        source_build_calls += 1
        raise PreexecError("pinned rehearsal attempted a source image build")

    def mocked_run(
        image_name: str,
        run_command: str,
        output_path: Path | None = None,
        global_env: list[str] | None = None,
        volumes: dict[Path, dict[str, str]] | None = None,
    ) -> str:
        if output_path is None or volumes is None or len(volumes) != 1:
            raise PreexecError("pinned docker_util.run boundary differs")
        [(host_path, binding)] = volumes.items()
        host_path = Path(host_path)
        mounted = host_path.read_bytes()
        mounted_over_baked_fixture = binding.get("bind") == "/home/fix.patch"
        effective = mounted if mounted_over_baked_fixture else baked_fixture_patch
        container = docker_util.docker_client.containers.run(
            image=image_name,
            command=run_command,
            remove=False,
            detach=True,
            stdout=True,
            stderr=True,
            environment=list(global_env or []),
            volumes=volumes,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output = ""
        try:
            with output_path.open("w", encoding="utf-8", newline="\n") as stream:
                for raw in container.logs(stream=True, follow=True):
                    decoded = raw.decode("utf-8")
                    stream.write(decoded)
                    output += decoded
        finally:
            container.remove(force=True)
        run_calls.append(
            {
                "image_name": image_name,
                "run_command": run_command,
                "output_path": output_path,
                "global_env": list(global_env or []),
                "host_path": host_path.resolve(),
                "binding": dict(binding),
                "baked_fixture_used": not mounted_over_baked_fixture,
                "effective": effective,
                "mounted": mounted,
            }
        )
        return output

    async def forbidden_session(*_args: object, **_kwargs: object) -> None:
        nonlocal session_calls
        session_calls += 1
        raise PreexecError("pinned rehearsal entered run_and_save_logs")

    def guarded_open(file: object, *args: object, **kwargs: object) -> Any:
        nonlocal host_prepare_reads
        try:
            candidate = os.fspath(file)
        except TypeError:
            candidate = ""
        if str(candidate).replace("\\", "/").endswith("/prepare.sh"):
            host_prepare_reads += 1
            raise PreexecError("pinned rehearsal attempted to read host prepare.sh")
        return original_open(file, *args, **kwargs)

    docker_util.run = mocked_run
    docker_util.exists = mocked_exists
    docker_util.build = forbidden_build
    session_module.run_and_save_logs = forbidden_session
    builtins.open = guarded_open
    try:
        exit_status_path = config_path.parent / "container-exit-status.json"
        cli = execute_pinned_instance_only(
            harness_root=harness_root,
            config_path=config_path,
            expected_image=EXPECTED_IMAGE,
            expected_tag=EXPECTED_TAG,
            exit_status_path=exit_status_path,
        )
        instances = cli.instances
        if len(instances) != 1 or instances[0].pr.id != "vuejs/core:pr-8911":
            raise PreexecError("pinned instance_only target set differs")
        dependency = instances[0].dependency()
        if dependency.image_full_name() != EXPECTED_TAG:
            raise PreexecError("pinned instance image name differs from the frozen tag")
        # This call is a separate early-return tripwire required by the frozen
        # contract. Production instance_only dispatch does not call it.
        cli.build_image(dependency)
    finally:
        builtins.open = original_open
        session_module.run_and_save_logs = original_session
        docker_util.build = original_build
        docker_util.exists = original_exists
        docker_util.run = original_run
        if sys.path and sys.path[0] == str(harness_root):
            sys.path.pop(0)

    if len(run_calls) != 1:
        raise PreexecError("pinned human-mode docker_util.run count differs")
    call = run_calls[0]
    expected_host = (
        config_path.parent / "work/vuejs/core/evals/pr-8911/fix.patch"
    ).resolve()
    if (
        call["image_name"] != EXPECTED_IMAGE
        or call["run_command"] != FIX_PATCH_RUN_COMMAND
        or call["host_path"] != expected_host
        or call["binding"] != {"bind": "/home/fix.patch", "mode": "rw"}
        or call["mounted"] != expected_patch
        or call["effective"] != expected_patch
        or call["effective"] == baked_fixture_patch
        or call["baked_fixture_used"] is not False
    ):
        raise PreexecError("pinned submitted-patch mount contract differs")
    try:
        exit_status = _strict_object(exit_status_path)
    except (OSError, ValueError) as exc:
        raise PreexecError("pinned runtime exit-status evidence is missing") from exc
    if (
        exit_status.get("schema") != "trimem/multi-swe-container-exit-status/1.0"
        or exit_status.get("executed_image") != EXPECTED_IMAGE
        or exit_status.get("expected_image") != EXPECTED_IMAGE
        or exit_status.get("expected_tag") != EXPECTED_TAG
        or exit_status.get("run_command") != FIX_PATCH_RUN_COMMAND
        or exit_status.get("status_code") != 0
        or exit_status.get("submitted_patch_bytes") != len(expected_patch)
        or exit_status.get("submitted_patch_sha256")
        != hashlib.sha256(expected_patch).hexdigest()
    ):
        raise PreexecError("pinned runtime exit-status evidence differs")
    if (
        docker_factory_calls != 1
        or exists_calls != [EXPECTED_TAG]
        or image_get_calls != [EXPECTED_IMAGE, EXPECTED_TAG]
        or image_pull_calls != 0
        or len(container_create_calls) != 1
        or container_create_calls[0].get("image") != EXPECTED_IMAGE
        or container_start_calls != 1
        or container_wait_calls != 1
        or source_build_calls != 0
        or session_calls != 0
        or host_prepare_reads != 0
    ):
        raise PreexecError("pinned no-build/no-prepare control-flow proof differs")
    return {
        "baked_patch_trusted_as_submission": False,
        "baked_fixture_patch_sha256": hashlib.sha256(baked_fixture_patch).hexdigest(),
        "build_image_existing_tag_probe_calls": 1,
        "docker_client_factory_calls_mocked": docker_factory_calls,
        "host_prepare_script_reads": host_prepare_reads,
        "image_exists_queries": len(exists_calls),
        "immutable_image_get_queries": image_get_calls,
        "image_pull_fallback_calls": image_pull_calls,
        "actual_container_image": container_create_calls[0]["image"],
        "container_exit_status": exit_status["status_code"],
        "container_exit_status_captured": True,
        "docker_container_create_calls": len(container_create_calls),
        "docker_container_start_calls": container_start_calls,
        "mocked_docker_run_calls": len(run_calls),
        "effective_submitted_patch_sha256": hashlib.sha256(
            call["effective"]
        ).hexdigest(),
        "mounted_patch_bytes": len(expected_patch),
        "mounted_patch_sha256": hashlib.sha256(expected_patch).hexdigest(),
        "run_and_save_logs_calls": session_calls,
        "source_image_build_calls": source_build_calls,
        "support_container_bootstrap_calls": 0,
        "submitted_patch_container_destination": "/home/fix.patch",
        "submitted_patch_mount_mode": "rw",
        "submitted_patch_request_identity_match": True,
        "upstream_module_main_executed": False,
    }


def run_rehearsal(*, cache_dir: Path, harness_root: Path) -> dict[str, Any]:
    target_row, dataset_spec, image_row = _frozen_inputs()
    source_row = _load_exact_row(dataset_spec, cache_dir)
    if canonical_row_hash(source_row) != target_row["source_row_sha256"]:
        raise PreexecError("pinned Vue source-row hash differs")
    if (
        source_row.get("org") != "vuejs"
        or source_row.get("repo") != "core"
        or str(source_row.get("number")) != "8911"
        or not isinstance(source_row.get("base"), Mapping)
        or source_row["base"].get("sha") != BASE_COMMIT
    ):
        raise PreexecError("pinned Vue source-row identity differs")

    target = FrozenOfficialTarget(
        target_id=str(target_row["target_id"]),
        benchmark_id=BENCHMARK_ID,
        instance_id=INSTANCE_ID,
        repository=REPOSITORY,
        base_commit=BASE_COMMIT,
        dataset_revision=str(target_row["dataset_revision"]),
        source_row_sha256=str(target_row["source_row_sha256"]),
        image=str(image_row["image"]),
        harness_image_tag=str(image_row["harness_image_tag"]),
        harness_revision=MULTI_HARNESS_REVISION,
    )
    patch = NOOP_BASELINE_PATCH.decode("utf-8")
    scratch_removed = False
    generated_private_files = 0
    remaining_private_files = -1
    invocation_contract: dict[str, Any]
    pinned_control_flow: dict[str, Any]
    with tempfile.TemporaryDirectory(prefix="trimem-multi-preexec-") as temporary:
        scratch = Path(temporary).resolve()
        output_root = scratch / "gateway-output"
        invocation = build_harness_invocation(
            target,
            row=source_row,
            patch=patch,
            harness_root=harness_root,
            run_root=scratch / "one-row-rehearsal",
            model_name="trimem-smoke",
        )
        # Construction performs a read-only pinned Git revision check.  grade()
        # is intentionally never called.
        gateway = OfficialHarnessGraderGateway(
            target,
            source_row=source_row,
            harness_root=harness_root,
            output_root=output_root,
            model_name="trimem-smoke",
        )
        invocation_contract = gateway._execution_contract(patch)

        expected_config = {
            "clear_env": True,
            "dataset_files": [str(scratch / "one-row-rehearsal/dataset.jsonl")],
            "fix_patch_run_cmd": FIX_PATCH_RUN_COMMAND,
            "force_build": False,
            "global_env": [],
            "human_mode": True,
            "log_dir": str(scratch / "one-row-rehearsal/logs"),
            "log_level": "DEBUG",
            "log_to_console": True,
            "max_workers": 1,
            "max_workers_build_image": 1,
            "max_workers_run_instance": 1,
            "mode": "instance_only",
            "need_clone": False,
            "output_dir": str(scratch / "one-row-rehearsal/output"),
            "patch_files": [str(scratch / "one-row-rehearsal/prediction.jsonl")],
            "repo_dir": str(scratch / "one-row-rehearsal/repos"),
            "skips": [],
            "specifics": ["vuejs/core:pr-8911"],
            "stop_on_error": True,
            "workdir": str(scratch / "one-row-rehearsal/work"),
        }
        config_path = scratch / "one-row-rehearsal/config.json"
        config = _strict_object(config_path)
        if config != expected_config or {
            key: config[key] for key in MULTI_SWE_PREBUILT_EVALUATION
        } != dict(MULTI_SWE_PREBUILT_EVALUATION):
            raise PreexecError("production Multi-SWE prebuilt config differs")

        expected_main = (
            sys.executable,
            str(ENTRYPOINT_PATH),
            "--harness-root",
            str(harness_root),
            "--config",
            str(config_path),
            "--expected-image",
            EXPECTED_IMAGE,
            "--expected-tag",
            EXPECTED_TAG,
            "--exit-status-output",
            str(scratch / "one-row-rehearsal/container-exit-status.json"),
        )
        expected_report = (
            sys.executable,
            "-m",
            "multi_swe_bench.harness.gen_report",
            "--mode",
            "evaluation",
            "--workdir",
            str(scratch / "one-row-rehearsal/work"),
            "--output_dir",
            str(scratch / "one-row-rehearsal/output"),
            "--specifics",
            "vuejs/core:pr-8911",
            "--dataset_files",
            str(scratch / "one-row-rehearsal/dataset.jsonl"),
            "--max_workers",
            "1",
            "--log_dir",
            str(scratch / "one-row-rehearsal/logs"),
            "--log_level",
            "DEBUG",
            "--log_to_console",
            "true",
            "--regen",
            "true",
        )
        if invocation.argv != expected_main or invocation.report_argv != expected_report:
            raise PreexecError("production Multi-SWE command sequence differs")
        if invocation.report_path != scratch / "one-row-rehearsal/output/final_report.json":
            raise PreexecError("production Multi-SWE report path differs")
        if invocation.materialized_patch_path != (
            scratch / "one-row-rehearsal/work/vuejs/core/evals/pr-8911/fix.patch"
        ):
            raise PreexecError("production submitted-patch mount source differs")

        pinned_control_flow = _exercise_pinned_control_flow(
            harness_root=harness_root,
            config_path=config_path,
            expected_patch=NOOP_BASELINE_PATCH,
        )

        prediction_path = scratch / "one-row-rehearsal/prediction.jsonl"
        prediction = _strict_object(prediction_path)
        if prediction != {
            "fix_patch": patch,
            "number": "8911",
            "org": "vuejs",
            "repo": "core",
        }:
            raise PreexecError("production one-row prediction differs from NOOP sentinel")
        dataset_lines = (scratch / "one-row-rehearsal/dataset.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
        if len(dataset_lines) != 1:
            raise PreexecError("production dataset materialization is not exactly one row")
        materialized_row = json.loads(dataset_lines[0])
        if not isinstance(materialized_row, dict) or canonical_row_hash(materialized_row) != target.source_row_sha256:
            raise PreexecError("production one-row dataset identity differs")

        generated_private_files = sum(path.is_file() for path in invocation.private_input_paths)
        if generated_private_files != 3:
            raise PreexecError("production private input set differs")
        for path in invocation.private_input_paths:
            path.unlink()
        remaining_private_files = sum(path.exists() for path in invocation.private_input_paths)
        if remaining_private_files != 0:
            raise PreexecError("production rehearsal private-input purge failed")
    scratch_removed = not scratch.exists()
    if not scratch_removed:
        raise PreexecError("production rehearsal temporary root purge failed")

    contract_sha = hashlib.sha256(_canonical(invocation_contract)).hexdigest()
    return {
        "adapter_execution_contract_sha256": contract_sha,
        "api_calls": 0,
        "benchmark_id": BENCHMARK_ID,
        "dataset": {
            "bytes": dataset_spec["bytes"],
            "revision": dataset_spec["dataset_revision"],
            "sha256": dataset_spec["sha256"],
            "source_row_sha256": target.source_row_sha256,
        },
        "docker_calls": 0,
        "exact_config": {
            "fix_patch_run_cmd": FIX_PATCH_RUN_COMMAND,
            "force_build": False,
            "human_mode": True,
            "mode": "instance_only",
            "need_clone": False,
        },
        "grader_calls": 0,
        "harness_revision": MULTI_HARNESS_REVISION,
        "image": {
            "expected_digest": EXPECTED_DIGEST,
            "harness_tag": EXPECTED_TAG,
            "immutable_reference": EXPECTED_IMAGE,
        },
        "instance_id": INSTANCE_ID,
        "model_calls": 0,
        "noop_patch": {
            "bytes": NOOP_BASELINE_LOCK["patch_bytes"],
            "sha256": NOOP_BASELINE_LOCK["patch_sha256"],
        },
        "official_evaluator_calls": 0,
        "official_evaluator_subprocess_calls": 0,
        "pinned_upstream_control_flow_rehearsals": 1,
        "pinned_control_flow": pinned_control_flow,
        "private_payload_purge": {
            "generated_file_count": generated_private_files,
            "remaining_file_count": remaining_private_files,
            "temporary_root_removed": scratch_removed,
        },
        "production_builder": "trimem_official_grader.build_harness_invocation",
        "production_entrypoint": {
            "bytes": len(ENTRYPOINT_PATH.read_bytes()),
            "path": ENTRYPOINT_PATH.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(ENTRYPOINT_PATH.read_bytes()).hexdigest(),
        },
        "report_mode": "SEPARATE_PINNED_GEN_REPORT_EVALUATION",
        "schema": "trimem/multi-swe-frozen-row-preexec/1.0",
        "status": "PASS",
        "submitted_or_gold_payload_published": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--harness-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_rehearsal(cache_dir=args.cache_dir, harness_root=args.harness_root)
        raw = json.dumps(
            result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        ).encode("utf-8") + b"\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(raw)
        print(json.dumps({"output_sha256": hashlib.sha256(raw).hexdigest(), "status": "PASS"}, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
