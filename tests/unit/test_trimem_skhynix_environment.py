"""Preparation rejects leakage and keeps paired workspaces/images independent."""
from __future__ import annotations

import importlib.util
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/trimem_skhynix_environment.py"
SPEC = importlib.util.spec_from_file_location("trimem_skhynix_environment", SCRIPT)
assert SPEC and SPEC.loader
environment = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = environment
SPEC.loader.exec_module(environment)

IMAGE = "example/target@sha256:" + "1" * 64


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    task = environment.CodingTask(
        task_id="dev-001", org_id="org", user_id="user", repository="org/project",
        commit="a" * 40, instruction="Fix the public issue", files={}, editable_paths=(),
    )
    target = {"target_id": task.task_id, "instance_id": "project-1", "benchmark_id": "swebench_verified"}
    value = environment.PreparedLocalEnvironment(
        (task,), {task.task_id: target}, tmp_path / "workspaces", tmp_path / "output",
        environment.ARMS, {"status": "PASS"}, {}, {"project-1": {"private_gold": "NEVER EXPOSE"}},
        {"project-1": {"image": IMAGE, "harness_image_tag": "example/target:test"}}, (), {},
    )
    monkeypatch.setattr(environment.PreparedLocalEnvironment, "prepare_target", lambda self, task: {})
    return value, task


def test_image_inspection_never_retains_environment_values(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "digests": [IMAGE], "environment": ["PATH=/a/private/tool/path", "LANG=C.UTF-8"],
        }))

    monkeypatch.setattr(environment.subprocess, "run", run)
    rows = environment.inspect_locked_images(
        [{"instance_id": "one", "benchmark_id": "swebench_verified"}], {"one": {"image": IMAGE}}, [],
    )
    assert rows[0]["environment"]["variable_names"] == ["LANG", "PATH"]
    assert "/a/private/tool/path" not in json.dumps(rows)
    assert len(calls) == 1 and calls[0][1:3] == ["image", "inspect"]


@pytest.mark.parametrize("entry", ["OPENAI_API_KEY=secret", "HINT=/tmp/test.patch", "SERVICE_TOKEN=secret"])
def test_image_inspection_rejects_solver_visible_private_material(entry):
    with pytest.raises(environment.LocalEnvironmentError, match="evaluator or secret") as caught:
        environment._image_environment_evidence([entry])
    assert entry not in str(caught.value)


def test_image_inspection_rejects_extra_digest(monkeypatch):
    monkeypatch.setattr(environment.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout=json.dumps({"digests": [IMAGE, "other@sha256:" + "2" * 64], "environment": []}),
    ))
    with pytest.raises(environment.LocalEnvironmentError, match="inspection is invalid"):
        environment.inspect_locked_images(
            [{"instance_id": "one", "benchmark_id": "swebench_verified"}], {"one": {"image": IMAGE}}, [],
        )


def test_cells_use_distinct_checkouts_and_graders_and_refuse_duplicate(prepared, monkeypatch):
    value, task = prepared
    paths, grader_paths, private_rows = [], [], []

    def checkouts(tasks, targets, images, root, *, resume):
        assert not resume
        paths.append(root)
        root.mkdir(parents=True)
        runner = environment.DockerSandboxCommandRunner(IMAGE)
        factory = environment.GitCheckoutWorkspaceFactory(
            {task.task_id: root}, {task.task_id: task.commit}, command_runners={task.task_id: runner},
        )
        return factory, {task.task_id: {"initial_status": "", "history_isolation": {},
                                     "command_sandbox_content_hash": runner.content_hash}}

    def grader(target, row, image, harnesses, output, arm, support, **kwargs):
        grader_paths.append(output)
        private_rows.append(row)
        assert kwargs["loader_preflight_evidence"] is value.loader_preflight
        return SimpleNamespace(arm=arm)

    monkeypatch.setattr(environment.benchmark, "prepare_checkouts", checkouts)
    monkeypatch.setattr(environment.benchmark, "_valid_history_isolation_evidence", lambda *a, **k: True)
    monkeypatch.setattr(environment.benchmark, "grader_factory", grader)
    monkeypatch.setattr(environment, "_probe_solver", lambda cell: {"status": "PASS"})
    cells = [value.prepare_cell(arm, task) for arm in value.arms]
    assert len(set(paths)) == len(set(grader_paths)) == 3
    assert all(cells[i].workspace_factory is not cells[j].workspace_factory
               for i in range(3) for j in range(i))
    assert len(private_rows) == 3
    assert all("private_gold" not in json.dumps(cell.checkout_evidence) for cell in cells)
    with pytest.raises(environment.LocalEnvironmentError, match="already prepared"):
        value.prepare_cell(value.arms[0], task)


def test_cleanup_selects_only_run_owned_images_and_matching_new_tags(prepared, monkeypatch):
    value, _task = prepared
    value._owned_images[IMAGE] = ["new:tag", "changed:tag"]
    ids = {IMAGE: "expected", "new:tag": "expected", "changed:tag": "someone-elses-image"}
    removed = []
    monkeypatch.setattr(environment.PreparedLocalEnvironment, "_image_id", staticmethod(ids.get))

    def run(argv, **kwargs):
        removed.extend(argv[3:])
        for reference in argv[3:]:
            ids.pop(reference, None)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(environment.subprocess, "run", run)
    assert not value._release_image("preexisting:cache")
    assert value._release_image(IMAGE)
    assert removed == ["new:tag", IMAGE]
    assert ids["changed:tag"] == "someone-elses-image"


def test_evidence_is_never_overwritten(tmp_path):
    path = tmp_path / "evidence.json"
    environment._retain(path, {"status": "original"})
    with pytest.raises(environment.LocalEnvironmentError, match="differs"):
        environment._retain(path, {"status": "replacement"})
    assert json.loads(path.read_text()) == {"status": "original"}


def test_initial_preflight_validates_all_targets_without_pulls_or_checkouts(prepared, monkeypatch, tmp_path):
    _value, template = prepared
    tasks = [replace(template, task_id=f"dev-{index:03}") for index in range(12)]
    targets = [{"target_id": task.task_id, "instance_id": task.task_id,
                "benchmark_id": "swebench_verified"} for task in tasks]
    images = {task.task_id: {"image": IMAGE} for task in tasks}
    rows = {task.task_id: {"restricted_gold": "not public"} for task in tasks}
    constructors = []
    monkeypatch.setattr(environment.sys, "platform", "linux")
    monkeypatch.setattr(environment.benchmark, "load_frozen_rows", lambda *args: (targets, rows))
    monkeypatch.setattr(environment.benchmark, "coding_tasks", lambda *args: tasks)
    monkeypatch.setattr(environment.benchmark, "image_entries", lambda **kwargs: (images, []))
    monkeypatch.setattr(environment, "prepare_harnesses", lambda root: {
        "swebench_verified": root, "multi_swe_bench_mini": root,
    })
    monkeypatch.setattr(environment, "run_official_harness_loader_preflight", lambda **kwargs: {"status": "PASS"})
    monkeypatch.setattr(environment.benchmark, "validate_official_harness_loader_preflight_evidence", lambda value: value)
    monkeypatch.setattr(environment.benchmark, "validate_preflight_harness_root_binding", lambda *args: None)

    def grader(*args, **kwargs):
        constructors.append(args[0]["target_id"])
        return SimpleNamespace()

    def unexpected(*args, **kwargs):
        raise AssertionError("Initial preflight must defer image/container/checkout operations")

    monkeypatch.setattr(environment.benchmark, "grader_factory", grader)
    monkeypatch.setattr(environment.benchmark, "prepare_checkouts", unexpected)
    monkeypatch.setattr(environment.subprocess, "run", unexpected)
    result = environment.prepare_local_environment(
        workspace_root=tmp_path / "workspaces", output_root=tmp_path / "output",
        dataset_cache_root=tmp_path / "datasets", harness_root=tmp_path / "harnesses",
    )
    assert constructors == [task.task_id for task in tasks]
    assert result.summary["planned_cells"] == 36
    assert result.summary["model_calls"] == result.summary["official_grader_runs"] == 0
    assert "restricted_gold" not in json.dumps(result.summary)
    assert not (tmp_path / "workspaces").exists()


def test_disk_reserve_uses_host_mount_in_wsl(prepared, monkeypatch):
    value, _task = prepared
    inspected = []
    monkeypatch.setattr(environment.Path, "is_dir", lambda self: str(self).replace("\\", "/") == "/mnt/c")
    monkeypatch.setattr(environment.Path, "exists", lambda self: True)

    def usage(root):
        inspected.append(root)
        return SimpleNamespace(free=value.disk_reserve_bytes - 1)

    monkeypatch.setattr(environment.shutil, "disk_usage", usage)
    with pytest.raises(environment.LocalEnvironmentError, match="physical free disk"):
        value._check_disk_reserve()
    assert inspected == [Path("/mnt/c")]


@pytest.mark.parametrize("binding", [{"supplemental_manifest_path": "manifest.json"},
                                      {"supplemental_manifest_sha256": "a" * 64}])
def test_supplemental_manifest_requires_path_and_hash_together(tmp_path, monkeypatch, binding):
    monkeypatch.setattr(environment.sys, "platform", "linux")
    with pytest.raises(environment.LocalEnvironmentError, match="must be paired"):
        environment.prepare_local_environment(
            workspace_root=tmp_path / "workspaces", output_root=tmp_path / "output",
            dataset_cache_root=tmp_path / "datasets", harness_root=tmp_path / "harnesses", **binding)
