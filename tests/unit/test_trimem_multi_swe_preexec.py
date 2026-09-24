from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_multi_swe_preexec as preexec  # noqa: E402
import trimem_multi_swe_entrypoint as entrypoint  # noqa: E402
import trimem_official_grader as official_grader  # noqa: E402


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _install_frozen_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, object]]:
    source_row: dict[str, object] = {
        "base": {"sha": preexec.BASE_COMMIT},
        "instance_id": preexec.INSTANCE_ID,
        "number": 8911,
        "org": "vuejs",
        "repo": "core",
    }
    source_hash = official_grader.canonical_row_hash(source_row)

    manifest = json.loads(preexec.MANIFEST_PATH.read_text(encoding="utf-8"))
    for row in manifest["targets"]:
        if row["instance_id"] == preexec.INSTANCE_ID:
            row["source_row_sha256"] = source_hash
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest)

    grader_lock = json.loads(preexec.GRADER_LOCK_PATH.read_text(encoding="utf-8"))
    grader_lock_path = tmp_path / "grader-lock.json"
    _write_json(grader_lock_path, grader_lock)

    image_lock_path = tmp_path / "image-lock.json"
    image_lock_path.write_bytes(preexec.IMAGE_LOCK_PATH.read_bytes())

    source_path = tmp_path / "pinned-mini.jsonl"
    source_path.write_text(
        json.dumps(source_row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    monkeypatch.setattr(preexec, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(preexec, "GRADER_LOCK_PATH", grader_lock_path)
    monkeypatch.setattr(preexec, "IMAGE_LOCK_PATH", image_lock_path)
    monkeypatch.setattr(preexec, "download_locked", lambda _spec, _cache: source_path)
    monkeypatch.setattr(
        preexec,
        "_exercise_pinned_control_flow",
        lambda **_kwargs: {
            "baked_patch_trusted_as_submission": False,
            "baked_fixture_patch_sha256": "1" * 64,
            "build_image_existing_tag_probe_calls": 1,
            "docker_client_factory_calls_mocked": 1,
            "docker_container_create_calls": 1,
            "docker_container_start_calls": 1,
            "host_prepare_script_reads": 0,
            "effective_submitted_patch_sha256": (
                "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775"
            ),
            "image_exists_queries": 1,
            "mocked_docker_run_calls": 1,
            "mounted_patch_bytes": 165,
            "mounted_patch_sha256": (
                "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775"
            ),
            "run_and_save_logs_calls": 0,
            "source_image_build_calls": 0,
            "support_container_bootstrap_calls": 0,
            "submitted_patch_container_destination": "/home/fix.patch",
            "submitted_patch_mount_mode": "rw",
            "submitted_patch_request_identity_match": True,
            "upstream_module_main_executed": False,
        },
    )
    monkeypatch.setattr(
        official_grader.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(
            argv,
            0,
            stdout=preexec.MULTI_HARNESS_REVISION + "\n",
            stderr="",
        ),
    )
    return source_path, source_row


def test_live_row_rehearsal_uses_production_builder_and_publishes_no_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_path, _source_row = _install_frozen_fixture(tmp_path, monkeypatch)
    harness_root = tmp_path / "pinned-harness"
    harness_root.mkdir()

    report = preexec.run_rehearsal(
        cache_dir=tmp_path / "cache", harness_root=harness_root
    )

    assert report["status"] == "PASS"
    assert report["production_builder"] == (
        "trimem_official_grader.build_harness_invocation"
    )
    assert report["exact_config"] == {
        "fix_patch_run_cmd": "bash -e /home/fix-run.sh",
        "force_build": False,
        "human_mode": True,
        "mode": "instance_only",
        "need_clone": False,
    }
    assert report["image"] == {
        "expected_digest": preexec.EXPECTED_DIGEST,
        "harness_tag": preexec.EXPECTED_TAG,
        "immutable_reference": preexec.EXPECTED_IMAGE,
    }
    assert report["noop_patch"] == {
        "bytes": 165,
        "sha256": "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775",
    }
    assert report["private_payload_purge"] == {
        "generated_file_count": 3,
        "remaining_file_count": 0,
        "temporary_root_removed": True,
    }
    entrypoint_raw = preexec.ENTRYPOINT_PATH.read_bytes()
    assert report["production_entrypoint"] == {
        "bytes": len(entrypoint_raw),
        "path": "scripts/trimem_multi_swe_entrypoint.py",
        "sha256": hashlib.sha256(entrypoint_raw).hexdigest(),
    }
    assert report["pinned_control_flow"]["support_container_bootstrap_calls"] == 0
    assert report["pinned_control_flow"]["upstream_module_main_executed"] is False
    assert {
        "api_calls": report["api_calls"],
        "docker_calls": report["docker_calls"],
        "grader_calls": report["grader_calls"],
        "model_calls": report["model_calls"],
        "official_evaluator_calls": report["official_evaluator_calls"],
    } == {
        "api_calls": 0,
        "docker_calls": 0,
        "grader_calls": 0,
        "model_calls": 0,
        "official_evaluator_calls": 0,
    }
    public = json.dumps(report, ensure_ascii=False, sort_keys=True)
    assert report["submitted_or_gold_payload_published"] is False
    assert "trimem grader discrimination noop" not in public
    assert "test_patch" not in public
    assert '"fix_patch":' not in public
    assert len(report["adapter_execution_contract_sha256"]) == 64


def test_live_row_rehearsal_fails_before_download_on_image_identity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source_path, _source_row = _install_frozen_fixture(tmp_path, monkeypatch)
    image_lock = json.loads(preexec.IMAGE_LOCK_PATH.read_text(encoding="utf-8"))
    for row in image_lock["targets"]:
        if row["instance_id"] == preexec.INSTANCE_ID:
            row["expected_digest"] = "sha256:" + "0" * 64
    drifted = tmp_path / "drifted-image-lock.json"
    _write_json(drifted, image_lock)
    monkeypatch.setattr(preexec, "IMAGE_LOCK_PATH", drifted)
    called = False

    def forbidden_download(_spec: object, _cache: Path) -> Path:
        nonlocal called
        called = True
        raise AssertionError("dataset download must not follow frozen-image drift")

    monkeypatch.setattr(preexec, "download_locked", forbidden_download)
    harness_root = tmp_path / "harness"
    harness_root.mkdir()
    with pytest.raises(preexec.PreexecError, match="immutable image identity differs"):
        preexec.run_rehearsal(cache_dir=tmp_path / "cache", harness_root=harness_root)
    assert called is False


def test_allowlisted_rehearsal_report_is_hash_only_for_private_material() -> None:
    source = (ROOT / "scripts/trimem_multi_swe_preexec.py").read_text(encoding="utf-8")
    assert "source_row" not in {
        "dataset",
        "image",
        "noop_patch",
        "private_payload_purge",
    }
    assert "submitted_or_gold_payload_published" in source
    assert hashlib.sha256(preexec.NOOP_BASELINE_PATCH).hexdigest() == (
        "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775"
    )


def test_pinned_control_flow_imports_with_docker_factory_stub_and_restores_spies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the live-rehearsal seam without requiring Docker locally.

    The CI workflow runs the same function with the real pinned upstream
    modules.  This focused test proves that import-time ``docker.from_env`` and
    every evaluator side-effect are intercepted and restored by that function.
    """

    harness_root = tmp_path / "multi-swe-bench"
    module_file = harness_root / "multi_swe_bench/harness/run_evaluation.py"
    module_file.parent.mkdir(parents=True)
    module_file.write_text("# pinned-module location sentinel\n", encoding="utf-8")

    run_root = tmp_path / "one-row-rehearsal"
    patch_path = run_root / "work/vuejs/core/evals/pr-8911/fix.patch"
    patch_path.parent.mkdir(parents=True)
    patch_path.write_bytes(preexec.NOOP_BASELINE_PATCH)
    config_path = run_root / "config.json"
    _write_json(
        config_path,
        {
            "clear_env": True,
            "dataset_files": [str(run_root / "dataset.jsonl")],
            "fix_patch_run_cmd": preexec.FIX_PATCH_RUN_COMMAND,
            "force_build": False,
            "global_env": [],
            "human_mode": True,
            "log_dir": str(run_root / "logs"),
            "log_level": "DEBUG",
            "log_to_console": True,
            "max_workers": 1,
            "max_workers_build_image": 1,
            "max_workers_run_instance": 1,
            "mode": "instance_only",
            "need_clone": False,
            "output_dir": str(run_root / "output"),
            "patch_files": [str(run_root / "prediction.jsonl")],
            "repo_dir": str(run_root / "repos"),
            "skips": [],
            "specifics": ["vuejs/core:pr-8911"],
            "stop_on_error": True,
            "workdir": str(run_root / "work"),
        },
    )

    class Dependency:
        @staticmethod
        def image_full_name() -> str:
            return preexec.EXPECTED_TAG

        @staticmethod
        def fix_patch_path() -> str:
            return "/home/fix.patch"

        @staticmethod
        def workdir() -> str:
            return "pr-8911"

    class Instance:
        pr = types.SimpleNamespace(
            id="vuejs/core:pr-8911", org="vuejs", repo="core"
        )

        @staticmethod
        def dependency() -> Dependency:
            return Dependency()

        @staticmethod
        def name() -> str:
            return preexec.EXPECTED_TAG

    original_run = object()
    original_exists = object()
    original_build = object()
    docker_util = types.SimpleNamespace(
        run=original_run,
        exists=original_exists,
        build=original_build,
    )

    class FakeCli:
        mode = "instance_only"
        force_build = False
        human_mode = True
        need_clone = False

        def __init__(self, parsed_config: Path) -> None:
            self.config_path = parsed_config
            config = json.loads(parsed_config.read_text(encoding="utf-8"))
            self.clear_env = config["clear_env"]
            self.stop_on_error = config["stop_on_error"]
            self.global_env = config["global_env"]
            self.skips = set(config["skips"])
            self.log_level = config["log_level"]
            self.log_to_console = config["log_to_console"]
            self.max_workers = config["max_workers"]
            self.max_workers_build_image = config["max_workers_build_image"]
            self.max_workers_run_instance = config["max_workers_run_instance"]
            self.fix_patch_run_cmd = config["fix_patch_run_cmd"]
            self.patch_files = config["patch_files"]
            self.dataset_files = config["dataset_files"]
            self.specifics = set(config["specifics"])
            self.workdir = Path(config["workdir"])
            self.output_dir = Path(config["output_dir"])
            self.repo_dir = Path(config["repo_dir"])
            self.log_dir = Path(config["log_dir"])
            self.instances = [Instance()]
            self.patches = {
                "vuejs/core:pr-8911": types.SimpleNamespace(
                    fix_patch=preexec.NOOP_BASELINE_PATCH.decode("utf-8")
                )
            }

        def run(self) -> None:
            docker_util.run(
                preexec.EXPECTED_TAG,
                preexec.FIX_PATCH_RUN_COMMAND,
                output_path=self.config_path.parent
                / "work/vuejs/core/evals/pr-8911/fix-patch-run.log",
                global_env=[],
                volumes={
                    self.config_path.parent
                    / "work/vuejs/core/evals/pr-8911/fix.patch": {
                        "bind": "/home/fix.patch",
                        "mode": "rw",
                    }
                },
            )

        def build_image(self, dependency: Dependency) -> None:
            if docker_util.exists(dependency.image_full_name()) and not self.force_build:
                return
            docker_util.build(dependency)

    class FakeCliArgs:
        @staticmethod
        def from_dict(values: dict[str, object]) -> FakeCli:
            return FakeCli(Path(str(values["config"])))

    def get_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser()
        parser.add_argument("--config", type=Path, required=True)
        return parser

    run_module = types.SimpleNamespace(
        __file__=str(module_file),
        CliArgs=FakeCliArgs,
        docker_util=docker_util,
        get_parser=get_parser,
    )
    original_session = object()
    session_module = types.SimpleNamespace(run_and_save_logs=original_session)
    original_from_env = lambda: "real-client-must-not-be-called"
    docker_module = types.SimpleNamespace(from_env=original_from_env)
    monkeypatch.setitem(sys.modules, "docker", docker_module)

    imported_factory_results: list[object] = []
    run_module_imported = False

    def import_module(name: str) -> object:
        nonlocal run_module_imported
        if name == "multi_swe_bench.harness.run_evaluation":
            # The pinned module constructs its Docker client at import time.
            if not run_module_imported:
                imported_factory_results.append(docker_module.from_env())
                docker_util.docker_client = imported_factory_results[-1]
                run_module_imported = True
            return run_module
        if name == "multi_swe_bench.utils.session_util":
            return session_module
        raise AssertionError(f"unexpected import: {name}")

    monkeypatch.setattr(preexec.importlib, "import_module", import_module)
    monkeypatch.setattr(
        entrypoint, "_verify_checkout", lambda path: path.resolve(strict=True)
    )

    proof = preexec._exercise_pinned_control_flow(
        harness_root=harness_root,
        config_path=config_path,
        expected_patch=preexec.NOOP_BASELINE_PATCH,
    )

    assert len(imported_factory_results) == 1
    assert type(imported_factory_results[0]).__name__ == "_NoDockerClient"
    assert proof == {
        "baked_patch_trusted_as_submission": False,
            "baked_fixture_patch_sha256": (
            "12e1b4f57f5b5d6cee7b7bf188bc2bc9dc54fcdb9a2364b20e055ca9ee5b8a37"
            ),
            "actual_container_image": preexec.EXPECTED_IMAGE,
        "build_image_existing_tag_probe_calls": 1,
            "docker_client_factory_calls_mocked": 1,
            "docker_container_create_calls": 1,
            "docker_container_start_calls": 1,
            "container_exit_status": 0,
            "container_exit_status_captured": True,
        "host_prepare_script_reads": 0,
        "effective_submitted_patch_sha256": hashlib.sha256(
            preexec.NOOP_BASELINE_PATCH
        ).hexdigest(),
            "image_exists_queries": 1,
            "image_pull_fallback_calls": 0,
            "immutable_image_get_queries": [
                preexec.EXPECTED_IMAGE,
                preexec.EXPECTED_TAG,
            ],
        "mocked_docker_run_calls": 1,
        "mounted_patch_bytes": len(preexec.NOOP_BASELINE_PATCH),
        "mounted_patch_sha256": hashlib.sha256(
            preexec.NOOP_BASELINE_PATCH
        ).hexdigest(),
        "run_and_save_logs_calls": 0,
        "source_image_build_calls": 0,
        "support_container_bootstrap_calls": 0,
        "submitted_patch_container_destination": "/home/fix.patch",
        "submitted_patch_mount_mode": "rw",
        "submitted_patch_request_identity_match": True,
        "upstream_module_main_executed": False,
    }
    assert docker_module.from_env is original_from_env
    assert docker_util.run is original_run
    assert docker_util.exists is original_exists
    assert docker_util.build is original_build
    assert session_module.run_and_save_logs is original_session
    assert str(harness_root.resolve()) not in sys.path
