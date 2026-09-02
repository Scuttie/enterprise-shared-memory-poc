from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_official_grader as official_grader  # noqa: E402
from enterprise_memory.trimem.workspace import WorkspaceGraderContext  # noqa: E402


PINNED_MULTI_REVISION = "24f493f8a103e72312ded4f6b9c89f081d69cb09"


def _target(benchmark_id: str, row: dict[str, object]) -> official_grader.FrozenOfficialTarget:
    swe = benchmark_id == "swebench_verified"
    return official_grader.FrozenOfficialTarget(
        target_id="target",
        benchmark_id=benchmark_id,
        instance_id="astropy__astropy-13579" if swe else "vuejs__core-8911",
        repository="astropy/astropy" if swe else "vuejs/core",
        base_commit="a" * 40,
        dataset_revision="b" * 40,
        source_row_sha256=official_grader.canonical_row_hash(row),
        image="example.invalid/grader@sha256:" + "d" * 64,
        harness_image_tag=(
            "example.invalid/grader:locked"
            if swe
            else "mswebench/vuejs_m_core:pr-8911"
        ),
        harness_revision=(
            official_grader.SWE_HARNESS_REVISION
            if swe
            else official_grader.MULTI_HARNESS_REVISION
        ),
    )


@dataclass
class _PinnedDependencySpy:
    number: int
    fix_patch_path_calls: int = 0

    def workdir(self) -> str:
        return f"pr-{self.number}"

    def fix_patch_path(self) -> str:
        self.fix_patch_path_calls += 1
        return "/home/fix.patch"


class _PinnedImageSpy:
    def __init__(self, image_full_name: str) -> None:
        self._image_full_name = image_full_name
        self.dockerfile_calls = 0
        self.files_calls = 0

    def image_full_name(self) -> str:
        return self._image_full_name

    def dockerfile(self) -> str:
        self.dockerfile_calls += 1
        return "FROM fixture"

    def files(self) -> list[object]:
        self.files_calls += 1
        return []


class _PinnedDockerUtilSpy:
    """Spy for the pinned upstream docker_util.exists/build/run boundary."""

    def __init__(self, *, baked_fixture: bytes) -> None:
        self.pretagged: set[str] = set()
        self.baked_fixture = baked_fixture
        self.exists_calls: list[str] = []
        self.build_calls: list[str] = []
        self.run_calls: list[dict[str, object]] = []

    def exists(self, image_name: str) -> bool:
        self.exists_calls.append(image_name)
        return image_name in self.pretagged

    def build(self, image_name: str) -> None:
        self.build_calls.append(image_name)

    def run(
        self,
        image_name: str,
        run_command: str,
        output_path: Path,
        global_env: list[str],
        *,
        volumes: dict[Path, dict[str, str]],
    ) -> None:
        [(host_path, binding)] = volumes.items()
        mounted = host_path.read_bytes()
        mounted_over_fixture = binding["bind"] == "/home/fix.patch"
        effective_container_bytes = mounted if mounted_over_fixture else self.baked_fixture
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"official Multi-SWE test output\n")
        self.run_calls.append({
            "image_name": image_name,
            "run_command": run_command,
            "output_path": output_path,
            "global_env": list(global_env),
            "host_path": host_path,
            "bind": binding["bind"],
            "mode": binding["mode"],
            "mounted_bytes": mounted,
            "mounted_sha256": hashlib.sha256(mounted).hexdigest(),
            "effective_container_bytes": effective_container_bytes,
            "baked_fixture_used": not mounted_over_fixture,
        })


class _AdapterImageRunnerSpy:
    def __init__(
        self,
        *,
        digest_reference: str,
        docker_util: _PinnedDockerUtilSpy,
    ) -> None:
        self.digest_reference = digest_reference
        self.docker_util = docker_util
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        call = tuple(argv)
        self.calls.append(call)
        if call[1:3] == ("image", "inspect"):
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps([self.digest_reference]), stderr=""
            )
        if call[1:3] == ("image", "tag"):
            assert call[3] == self.digest_reference
            self.docker_util.pretagged.add(call[4])
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected adapter command: {call!r}")


def _multi_test_status() -> dict[str, object]:
    def result(*, passed: list[str] | None = None, failed: list[str] | None = None) -> dict[str, object]:
        passed = list(passed or [])
        failed = list(failed or [])
        return {
            "passed_count": len(passed),
            "failed_count": len(failed),
            "skipped_count": 0,
            "passed_tests": passed,
            "failed_tests": failed,
            "skipped_tests": [],
        }

    return {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "valid": False,
        "run_result": result(passed=["run"]),
        "test_patch_result": result(passed=["test"]),
        "fix_patch_result": result(failed=["fix"]),
        "fixed_tests": {},
        "p2p_tests": {},
        "f2p_tests": {},
        "s2p_tests": {},
        "n2p_tests": {},
    }


def _multi_final_report() -> dict[str, object]:
    canonical_id = "vuejs/core:pr-8911"
    return {
        "total_instances": 1,
        "submitted_instances": 1,
        "completed_instances": 1,
        "incomplete_instances": 0,
        "resolved_instances": 0,
        "unresolved_instances": 1,
        "empty_patch_instances": 0,
        "error_instances": 0,
        "submitted_ids": [canonical_id],
        "completed_ids": [canonical_id],
        "incomplete_ids": [],
        "resolved_ids": [],
        "unresolved_ids": [canonical_id],
        "empty_patch_ids": [],
        "error_ids": [],
    }


class _SequentialGatewayRunnerSpy(_AdapterImageRunnerSpy):
    def __init__(
        self,
        *,
        target: official_grader.FrozenOfficialTarget,
        docker_util: _PinnedDockerUtilSpy,
        main_returncode: int = 0,
        report_returncode: int = 0,
        materialized_patch_override: bytes | None = None,
    ) -> None:
        super().__init__(digest_reference=target.image, docker_util=docker_util)
        self.target = target
        self.main_returncode = main_returncode
        self.report_returncode = report_returncode
        self.materialized_patch_override = materialized_patch_override
        self.config: dict[str, object] | None = None
        self.prediction: dict[str, object] | None = None
        self.harness: _PinnedMultiHarnessSpy | None = None

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        call = tuple(argv)
        if call[1:3] == ("image", "inspect") or call[1:3] == ("image", "tag"):
            return super().__call__(argv, **kwargs)
        self.calls.append(call)
        if len(call) > 1 and Path(call[1]).name == "trimem_multi_swe_entrypoint.py":
            if self.main_returncode:
                return subprocess.CompletedProcess(
                    argv, self.main_returncode, stdout="instance failed\n", stderr="main error\n"
                )
            config_path = Path(call[call.index("--config") + 1])
            self.config = json.loads(config_path.read_text(encoding="utf-8"))
            prediction_path = Path(str(self.config["patch_files"][0]))
            self.prediction = json.loads(prediction_path.read_text(encoding="utf-8"))
            self.harness = _PinnedMultiHarnessSpy(self.config, self.docker_util)
            self.harness.run(
                image=_PinnedImageSpy(self.target.harness_image_tag),
                instance={
                    "org": "vuejs",
                    "repo": "core",
                    "number": 8911,
                    "image_name": self.target.harness_image_tag,
                    "dependency": _PinnedDependencySpy(number=8911),
                    "submitted_patch": self.prediction["fix_patch"],
                },
            )
            materialized_patch = (
                Path(str(self.config["workdir"])) / "vuejs/core/evals/pr-8911/fix.patch"
            )
            if self.materialized_patch_override is not None:
                materialized_patch.write_bytes(self.materialized_patch_override)
            status_path = Path(str(self.config["workdir"])) / "vuejs/core/evals/pr-8911/report.json"
            status_path.write_text(
                json.dumps(_multi_test_status(), sort_keys=True), encoding="utf-8", newline="\n"
            )
            return subprocess.CompletedProcess(
                argv, 0, stdout="instance-only complete\n", stderr=""
            )
        if call[1:3] == ("-m", "multi_swe_bench.harness.gen_report"):
            if self.report_returncode:
                return subprocess.CompletedProcess(
                    argv, self.report_returncode, stdout="", stderr="report error\n"
                )
            output_dir = Path(call[call.index("--output_dir") + 1])
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "final_report.json").write_text(
                json.dumps(_multi_final_report(), sort_keys=True), encoding="utf-8", newline="\n"
            )
            return subprocess.CompletedProcess(argv, 0, stdout="report complete\n", stderr="")
        raise AssertionError(f"unexpected gateway command: {call!r}")


class _PinnedMultiHarnessSpy:
    """Control-flow spy for the two relevant methods at PINNED_MULTI_REVISION.

    It deliberately mirrors only ``RunEvaluation.build_image`` and
    ``RunEvaluation.run_instance``. This keeps the test credential-, network-,
    and Docker-free while locking the integration contract we rely upon.
    """

    def __init__(self, config: dict[str, object], docker_util: _PinnedDockerUtilSpy) -> None:
        self.config = config
        self.docker_util = docker_util
        self.workdir = Path(str(config["workdir"]))
        self.global_env = list(config["global_env"])
        self.run_mode_image_calls = 0
        self.check_commit_hashes_calls = 0
        self.build_image_calls = 0
        self.target_source_build_calls = 0
        self.run_and_save_logs_calls = 0
        self.host_prepare_paths: list[Path] = []

    def build_image(self, image: _PinnedImageSpy) -> None:
        # multi_swe_bench/harness/run_evaluation.py:573-578 at the pinned commit.
        self.build_image_calls += 1
        if not self.config["force_build"] and self.docker_util.exists(image.image_full_name()):
            return
        self.target_source_build_calls += 1
        image.dockerfile()
        image.files()
        self.docker_util.build(image.image_full_name())

    def check_commit_hashes(self) -> None:
        self.check_commit_hashes_calls += 1

    def run_mode_image(self, image: _PinnedImageSpy) -> None:
        self.run_mode_image_calls += 1
        self.check_commit_hashes()
        self.build_image(image)

    def run(self, *, image: _PinnedImageSpy, instance: dict[str, object]) -> None:
        # CliArgs.run() dispatches instance_only directly to run_mode_instance_only.
        if self.config["mode"] == "instance_only":
            self.run_instance(**instance)
            return
        if self.config["mode"] == "evaluation":
            self.run_mode_image(image)
            self.run_instance(**instance)
            return
        raise AssertionError(f"unexpected pinned harness mode: {self.config['mode']!r}")

    def run_instance(
        self,
        *,
        org: str,
        repo: str,
        number: int,
        image_name: str,
        dependency: _PinnedDependencySpy,
        submitted_patch: str,
    ) -> None:
        # multi_swe_bench/harness/run_evaluation.py:685-754 at the pinned commit.
        instance_dir = self.workdir / org / repo / "evals" / dependency.workdir()
        instance_dir.mkdir(parents=True, exist_ok=True)
        fix_patch_path = instance_dir.absolute() / "fix.patch"
        fix_patch_path.write_text(submitted_patch, encoding="utf-8", newline="\n")
        output_path = instance_dir / "fix-patch-run.log"
        if not self.config["human_mode"]:
            self.run_and_save_logs_calls += 1
            self.host_prepare_paths.append(
                self.workdir / org / repo / "images" / f"pr-{number}" / "prepare.sh"
            )
            return
        self.docker_util.run(
            image_name,
            "bash /home/fix-run.sh",
            output_path,
            self.global_env,
            volumes={
                fix_patch_path: {
                    "bind": dependency.fix_patch_path(),
                    "mode": "rw",
                }
            },
        )


def test_multi_prebuilt_profile_drives_pinned_human_path_without_source_build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert official_grader.MULTI_HARNESS_REVISION == PINNED_MULTI_REVISION
    assert dict(official_grader.MULTI_SWE_PREBUILT_EVALUATION) == {
        "mode": "instance_only",
        "force_build": False,
        "human_mode": True,
        "need_clone": False,
    }
    with pytest.raises(TypeError):
        official_grader.MULTI_SWE_PREBUILT_EVALUATION["human_mode"] = False  # type: ignore[index]

    row = {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "base": {"sha": "a" * 40},
    }
    target = _target("multi_swe_bench_mini", row)
    harness_root = tmp_path / "pinned-harness"
    harness_root.mkdir()
    monkeypatch.setattr(
        official_grader.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            _args[0], 0, stdout=PINNED_MULTI_REVISION + "\n", stderr=""
        ),
    )
    baked_fixture = b"DIFFERENT BAKED TEST FIXTURE -- MUST NOT BE USED\n"
    docker_util = _PinnedDockerUtilSpy(baked_fixture=baked_fixture)
    adapter_runner = _AdapterImageRunnerSpy(
        digest_reference=target.image,
        docker_util=docker_util,
    )
    gateway = official_grader.OfficialHarnessGraderGateway(
        target,
        source_row=row,
        harness_root=harness_root,
        output_root=tmp_path / "adapter-output",
        model_name="trimem-smoke",
        runner=adapter_runner,
    )
    gateway._restricted_streams = lambda *_args, **_kwargs: {}
    gateway._verify_and_tag(object(), 0, target.image, target.harness_image_tag, [])
    assert adapter_runner.calls == [
        ("docker", "image", "inspect", "--format", "{{json .RepoDigests}}", target.image),
        ("docker", "image", "tag", target.image, target.harness_image_tag),
    ]
    assert docker_util.pretagged == {target.harness_image_tag}

    submitted_patch = (
        "diff --git a/submitted.txt b/submitted.txt\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/submitted.txt\n"
        "@@ -0,0 +1 @@\n"
        "+submitted-only\n"
    )
    invocation = official_grader.build_harness_invocation(
        target,
        row=row,
        patch=submitted_patch,
        harness_root=harness_root,
        run_root=tmp_path / "run",
        model_name="trimem-smoke",
        python_binary="python",
    )
    config = json.loads((tmp_path / "run/config.json").read_text(encoding="utf-8"))
    prediction = json.loads((tmp_path / "run/prediction.jsonl").read_text(encoding="utf-8"))
    assert {name: config[name] for name in official_grader.MULTI_SWE_PREBUILT_EVALUATION} == dict(
        official_grader.MULTI_SWE_PREBUILT_EVALUATION
    )
    assert prediction["fix_patch"] == submitted_patch
    assert invocation.argv == (
        "python",
        str(official_grader.MULTI_ENTRYPOINT),
        "--harness-root",
        str(harness_root),
        "--config",
        str(tmp_path / "run/config.json"),
    )
    assert invocation.report_argv == (
        "python",
        "-m",
        "multi_swe_bench.harness.gen_report",
        "--mode",
        "evaluation",
        "--workdir",
        str(tmp_path / "run/work"),
        "--output_dir",
        str(tmp_path / "run/output"),
        "--specifics",
        "vuejs/core:pr-8911",
        "--dataset_files",
        str(tmp_path / "run/dataset.jsonl"),
        "--max_workers",
        "1",
        "--log_dir",
        str(tmp_path / "run/logs"),
        "--log_level",
        "DEBUG",
        "--log_to_console",
        "true",
        "--regen",
        "true",
    )

    harness = _PinnedMultiHarnessSpy(config, docker_util)
    image = _PinnedImageSpy(target.harness_image_tag)
    dependency = _PinnedDependencySpy(number=8911)

    harness.run(
        image=image,
        instance={
            "org": "vuejs",
            "repo": "core",
            "number": 8911,
            "image_name": target.harness_image_tag,
            "dependency": dependency,
            "submitted_patch": prediction["fix_patch"],
        },
    )

    submitted_raw = submitted_patch.encode("utf-8")
    assert docker_util.exists_calls == []
    assert harness.run_mode_image_calls == 0
    assert harness.check_commit_hashes_calls == 0
    assert harness.build_image_calls == 0
    assert harness.target_source_build_calls == 0
    assert docker_util.build_calls == []
    assert image.dockerfile_calls == image.files_calls == 0
    assert harness.run_and_save_logs_calls == 0
    assert harness.host_prepare_paths == []
    assert dependency.fix_patch_path_calls == 1
    assert len(docker_util.run_calls) == 1
    call = docker_util.run_calls[0]
    assert call["image_name"] == target.harness_image_tag
    assert call["host_path"] == (
        tmp_path / "run/work/vuejs/core/evals/pr-8911/fix.patch"
    ).absolute()
    assert call["bind"] == "/home/fix.patch"
    assert call["mode"] == "rw"
    assert call["mounted_bytes"] == call["effective_container_bytes"] == submitted_raw
    assert call["mounted_sha256"] == hashlib.sha256(submitted_raw).hexdigest()
    assert call["mounted_bytes"] != baked_fixture
    assert call["baked_fixture_used"] is False

    # The production instance_only dispatch never calls build_image. Lock the
    # pinned method's pretagged behavior separately as a fallback tripwire.
    fallback_probe = _PinnedMultiHarnessSpy(config, docker_util)
    fallback_image = _PinnedImageSpy(target.harness_image_tag)
    fallback_probe.build_image(fallback_image)
    assert docker_util.exists_calls == [target.harness_image_tag]
    assert fallback_probe.build_image_calls == 1
    assert fallback_probe.target_source_build_calls == 0
    assert fallback_image.dockerfile_calls == fallback_image.files_calls == 0
    assert docker_util.build_calls == []


def _gateway_and_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    main_returncode: int = 0,
    report_returncode: int = 0,
    materialized_patch_override: bytes | None = None,
) -> tuple[
    official_grader.OfficialHarnessGraderGateway,
    official_grader.GradeRequest,
    _SequentialGatewayRunnerSpy,
    _PinnedDockerUtilSpy,
]:
    row = {
        "org": "vuejs", "repo": "core", "number": 8911,
        "base": {"sha": "a" * 40},
    }
    target = _target("multi_swe_bench_mini", row)
    harness_root = tmp_path / "h"
    harness_root.mkdir()
    monkeypatch.setattr(
        official_grader.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            _args[0], 0, stdout=PINNED_MULTI_REVISION + "\n", stderr=""
        ),
    )
    docker_util = _PinnedDockerUtilSpy(baked_fixture=b"baked fixture must stay hidden\n")
    runner = _SequentialGatewayRunnerSpy(
        target=target,
        docker_util=docker_util,
        main_returncode=main_returncode,
        report_returncode=report_returncode,
        materialized_patch_override=materialized_patch_override,
    )
    gateway = official_grader.OfficialHarnessGraderGateway(
        target,
        source_row=row,
        harness_root=harness_root,
        output_root=tmp_path / "o",
        model_name="trimem-smoke",
        runner=runner,
    )

    def restricted_blob(stage: str, kind: str, raw: bytes) -> dict[str, object]:
        return {
            "path": f"restricted-evidence/{stage}-{kind}.bin",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
        }

    gateway._restricted_blob = restricted_blob
    submitted_patch = "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+submitted\n"
    request = official_grader.GradeRequest(
        task_id=target.target_id,
        repository=target.repository,
        base_commit=target.base_commit,
        patch=submitted_patch,
        workspace=WorkspaceGraderContext(
            kind="test", repository_files={}, base_commit=target.base_commit
        ),
    )
    return gateway, request, runner, docker_util


def _expected_multi_contract(patch: str) -> dict[str, object]:
    raw = patch.encode("utf-8")
    return {
        "schema": "trimem/official-grader-execution-contract/1.0",
        "api_calls": 0,
        "profile": "MULTI_SWE_PREBUILT_EVALUATION",
        "execution_mode": "instance_only",
        "human_mode": True,
        "force_build": False,
        "need_clone": False,
        "report_module": "multi_swe_bench.harness.gen_report",
        "report_mode": "evaluation",
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
        "submitted_patch_bytes": len(raw),
        "submitted_patch_sha256": hashlib.sha256(raw).hexdigest(),
        "patch_transport": {
            "host_source": "evaluation_instance_fix.patch",
            "container_destination": "/home/fix.patch",
            "mode": "rw",
        },
    }


def test_gateway_runs_instance_only_then_official_report_and_parses_final_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, request, runner, docker_util = _gateway_and_request(tmp_path, monkeypatch)
    grade = gateway.grade(request)

    commands = [
        (
            "trimem_multi_swe_entrypoint"
            if len(call) > 1 and Path(call[1]).name == "trimem_multi_swe_entrypoint.py"
            else call[2]
        )
        for call in runner.calls
        if len(call) > 2
        and (
            Path(call[1]).name == "trimem_multi_swe_entrypoint.py"
            or call[1] == "-m"
        )
    ]
    assert commands == [
        "trimem_multi_swe_entrypoint",
        "multi_swe_bench.harness.gen_report",
    ]
    assert runner.config is not None and runner.config["mode"] == "instance_only"
    assert runner.harness is not None
    assert runner.harness.run_mode_image_calls == 0
    assert runner.harness.check_commit_hashes_calls == 0
    assert runner.harness.build_image_calls == 0
    assert runner.harness.target_source_build_calls == 0
    assert runner.harness.run_and_save_logs_calls == 0
    assert runner.harness.host_prepare_paths == []
    assert len(docker_util.run_calls) == 1
    assert docker_util.run_calls[0]["mounted_bytes"] == request.patch.encode("utf-8")
    assert grade.resolved is False and grade.status == "success"
    assert grade.stdout == "instance-only complete\nreport complete\n"
    assert grade.report["_trimem"]["execution_contract"] == _expected_multi_contract(
        request.patch
    )
    assert grade.report["_trimem"]["report_invocation_status"] == "SUCCESS"
    assert Path(grade.report["_trimem"]["report_path"]).as_posix() == "output/final_report.json"
    assert grade.report["_trimem"]["test_evidence"]["summary"]["fix_tests_classified"] == 1
    materialized = grade.report["_trimem"]["materialized_patch_evidence"]
    expected_raw = request.patch.encode("utf-8")
    assert materialized == {
        "schema": "trimem/materialized-submitted-patch-evidence/1.0",
        "host_path": "target/work/vuejs/core/evals/pr-8911/fix.patch",
        "container_destination": "/home/fix.patch",
        "mode": "rw",
        "bytes": len(expected_raw),
        "sha256": hashlib.sha256(expected_raw).hexdigest(),
        "request_identity_match": True,
        "restricted_materialized_patch": {
            "path": "restricted-evidence/submitted-patch-materialized.bin",
            "sha256": hashlib.sha256(expected_raw).hexdigest(),
            "bytes": len(expected_raw),
            "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
        },
        "purged_after_capture": True,
    }
    assert not Path(docker_util.run_calls[0]["host_path"]).exists()
    assert grade.report["_trimem"]["execution_control_evidence"] == {
        "schema": "trimem/official-grader-execution-control/1.0",
        "harness_revision": PINNED_MULTI_REVISION,
        "profile": "MULTI_SWE_PREBUILT_EVALUATION",
        "proof_basis": "PINNED_CONTROL_FLOW_AND_ADAPTER_CONSTRUCTION_INVARIANT",
        "dispatch": (
            "trimem_multi_swe_entrypoint.execute_pinned_instance_only"
            "->CliArgs.run(instance_only)->run_mode_instance_only"
        ),
        "support_container_bootstrap_calls": 0,
        "upstream_module_main_executed": False,
        "structurally_excluded_calls": [
            "run_evaluation.__main__.nix_swe_bootstrap",
            "run_mode_image",
            "check_commit_hashes",
            "build_image",
            "run_and_save_logs",
        ],
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
    }


def test_gateway_rejects_and_purges_materialized_patch_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, request, runner, docker_util = _gateway_and_request(
        tmp_path,
        monkeypatch,
        materialized_patch_override=b"different materialized patch\n",
    )
    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway.grade(request)
    result = caught.value.result
    commands = [
        "trimem_multi_swe_entrypoint"
        if len(call) > 1 and Path(call[1]).name == "trimem_multi_swe_entrypoint.py"
        else call[2]
        for call in runner.calls
        if len(call) > 2
        and (
            Path(call[1]).name == "trimem_multi_swe_entrypoint.py"
            or call[1] == "-m"
        )
    ]
    assert commands == ["trimem_multi_swe_entrypoint"]
    assert result.status == "materialized_patch_invalid"
    assert result.report["reason"] == "materialized submitted patch bytes mismatch"
    assert not Path(docker_util.run_calls[0]["host_path"]).exists()
    assert result.report["_trimem"]["execution_contract"] == _expected_multi_contract(
        request.patch
    )
    observed = b"different materialized patch\n"
    evidence = result.report["_trimem"]["materialized_patch_evidence"]
    assert evidence["bytes"] == len(observed)
    assert evidence["sha256"] == hashlib.sha256(observed).hexdigest()
    assert evidence["request_identity_match"] is False
    assert evidence["purged_after_capture"] is True
    assert evidence["restricted_materialized_patch"] == {
        "path": "restricted-evidence/submitted-patch-materialized.bin",
        "sha256": hashlib.sha256(observed).hexdigest(),
        "bytes": len(observed),
        "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
    }


@pytest.mark.parametrize(
    ("main_returncode", "report_returncode", "expected_status", "expected_modules"),
    [
        (17, 0, "harness_exit_nonzero", ["trimem_multi_swe_entrypoint"]),
        (
            0,
            19,
            "report_exit_nonzero",
            [
                "trimem_multi_swe_entrypoint",
                "multi_swe_bench.harness.gen_report",
            ],
        ),
    ],
)
def test_gateway_sequence_fails_closed_and_retains_execution_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    main_returncode: int,
    report_returncode: int,
    expected_status: str,
    expected_modules: list[str],
) -> None:
    gateway, request, runner, _docker_util = _gateway_and_request(
        tmp_path,
        monkeypatch,
        main_returncode=main_returncode,
        report_returncode=report_returncode,
    )
    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway.grade(request)
    result = caught.value.result
    commands = [
        "trimem_multi_swe_entrypoint"
        if len(call) > 1 and Path(call[1]).name == "trimem_multi_swe_entrypoint.py"
        else call[2]
        for call in runner.calls
        if len(call) > 2
        and (
            Path(call[1]).name == "trimem_multi_swe_entrypoint.py"
            or call[1] == "-m"
        )
    ]
    assert commands == expected_modules
    assert result.status == expected_status
    assert result.report["_trimem"]["execution_contract"] == _expected_multi_contract(
        request.patch
    )
    if main_returncode:
        assert result.report["report_invocation_status"] == "NOT_RUN"
    else:
        assert result.report["report_invocation_status"] == "EXIT_NONZERO"


@pytest.mark.parametrize(
    ("field", "drifted"),
    [
        ("mode", "evaluation"),
        ("force_build", True),
        ("human_mode", False),
        ("need_clone", True),
    ],
)
def test_multi_gateway_construction_rejects_execution_profile_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    drifted: object,
) -> None:
    row = {
        "org": "vuejs", "repo": "core", "number": 8911,
        "base": {"sha": "a" * 40},
    }
    profile = dict(official_grader.MULTI_SWE_PREBUILT_EVALUATION)
    profile[field] = drifted
    monkeypatch.setattr(official_grader, "MULTI_SWE_PREBUILT_EVALUATION", profile)
    with pytest.raises(ValueError, match="MULTI_SWE_PREBUILT_EVALUATION invariant mismatch"):
        official_grader.OfficialHarnessGraderGateway(
            _target("multi_swe_bench_mini", row),
            source_row=row,
            harness_root=tmp_path / "missing-harness",
            output_root=tmp_path / "output",
            model_name="trimem-smoke",
        )


def test_swe_invocation_private_bytes_are_unchanged_by_multi_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Even a drifted Multi profile cannot enter the disjoint SWE invocation branch.
    monkeypatch.setattr(
        official_grader,
        "MULTI_SWE_PREBUILT_EVALUATION",
        {
            "mode": "evaluation",
            "force_build": True,
            "human_mode": False,
            "need_clone": True,
        },
    )
    row = {
        "instance_id": "astropy__astropy-13579",
        "repo": "astropy/astropy",
        "base_commit": "a" * 40,
    }
    invocation = official_grader.build_harness_invocation(
        _target("swebench_verified", row),
        row=row,
        patch="submitted patch\n",
        harness_root=tmp_path / "harness",
        run_root=tmp_path / "run",
        model_name="trimem-smoke",
        python_binary="python",
    )
    dataset_raw, prediction_raw = [path.read_bytes() for path in invocation.private_input_paths]
    assert (len(dataset_raw), hashlib.sha256(dataset_raw).hexdigest()) == (
        196,
        "4ca3d44b3376c54ea9121c2dd340bea869d0851d7d613a1bc1b2c08a3c106805",
    )
    assert (len(prediction_raw), hashlib.sha256(prediction_raw).hexdigest()) == (
        111,
        "f28d03796cc42df9954d426aa79e79dd858cd60406b37ca84b5083496f08e333",
    )
    assert invocation.report_argv == ()
    assert "--task-repo" not in invocation.argv
    assert "--task_repo" not in invocation.argv
    assert "--rewrite_reports" not in invocation.argv
    gateway = object.__new__(official_grader.OfficialHarnessGraderGateway)
    gateway.target = _target("swebench_verified", row)
    assert gateway._execution_contract("submitted patch\n") == {
        "schema": "trimem/official-grader-execution-contract/1.0",
        "api_calls": 0,
        "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
        "execution_mode": "evaluation",
        "human_mode": None,
        "force_build": None,
        "need_clone": None,
        "report_module": "swebench.harness.run_evaluation",
        "report_mode": "inline",
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
        "submitted_patch_bytes": 16,
        "submitted_patch_sha256": (
            "a580e0fa7c50dc9e8b7b4d8c513c5af28717948003dc74d64722109abf6ba820"
        ),
        "patch_transport": {
            "host_source": "prediction.jsonl.model_patch",
            "container_destination": None,
            "mode": None,
        },
    }
    assert gateway._execution_control_evidence() == {
        "schema": "trimem/official-grader-execution-control/1.0",
        "harness_revision": official_grader.SWE_HARNESS_REVISION,
        "profile": "SWE_BENCH_OFFICIAL_PREDICTION",
        "proof_basis": "PINNED_CONTROL_FLOW_AND_FIXED_ARGV",
        "dispatch": "main(task_repo=None,rewrite_reports=False)->run_instances",
        "source_build_guard": {
            "expression": "task_repo and not rewrite_reports",
            "task_repo_argv_present": False,
            "rewrite_reports_argv_present": False,
            "evaluates": False,
        },
        "structurally_excluded_calls": ["_build_before_eval"],
        "source_image_build_calls": 0,
        "host_prepare_script_reads": 0,
    }
