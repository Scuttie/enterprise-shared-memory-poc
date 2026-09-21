"""Synthetic generic environment integration without containers or grading."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_skhynix_architecture_environment as environment
import trimem_skhynix_architecture_dataset as dataset


@pytest.fixture
def setup(tmp_path, monkeypatch):
    source = tmp_path / "datasets" / "public.bin"
    source.parent.mkdir()
    source.write_bytes(b"Synthetic public source")
    target = {"target_id": "swebench--fixture__repo-1", "instance_id": "fixture__repo-1",
        "benchmark_id": "swebench_verified", "repository": "fixture/repo", "base_commit": "a" * 40,
        "role": "TRAINING", "source_dataset_id": "SWE-bench/SWE-bench",
        "dataset_revision": "b" * 40}
    rows = {target["instance_id"]: {"problem_statement": "Synthetic public issue", "version": "1.0",
        "environment_setup_commit": "d" * 40}}
    manifest = {"schema": dataset.SCHEMA, "targets": [target],
        "datasets": {"TRAINING": {"path": str(source)}}}
    tag = dataset.official_image_tag(target["instance_id"])
    index = tmp_path / "images.json"
    index.write_text(json.dumps({"rows": [{"instance_id": target["instance_id"], "role": "TRAINING",
        "status": "AVAILABLE", "harness_image_tag": tag,
        "image": tag.removesuffix(":latest") + "@sha256:" + "c" * 64}]}))
    monkeypatch.setattr(environment.sys, "platform", "linux")
    monkeypatch.setattr(dataset, "load_architecture_rows", lambda *a, **kw: ([target], rows, manifest))
    monkeypatch.setattr(environment.local, "prepare_harnesses", lambda path: {"swebench_verified": path})
    monkeypatch.setattr(environment.local.benchmark, "load_official_harness_loader_preflight",
        lambda path: {"status": "PASS", "synthetic": True})
    monkeypatch.setattr(environment.local.benchmark, "validate_preflight_harness_root_binding", lambda *a: None)
    return {"target": target, "rows": rows, "manifest": manifest, "source": source,
        "kwargs": {"manifest_path": tmp_path / "manifest.json", "sha": "e" * 64,
            "image_index_path": index, "workspace_root": tmp_path / "workspaces",
            "output_root": tmp_path / "output", "harness_root": tmp_path / "harnesses",
            "loader_preflight_path": tmp_path / "loader.json"}}


def test_build_validates_public_bindings_without_private_rows_images_or_checkouts(setup, monkeypatch):
    monkeypatch.setattr(dataset, "bind_architecture_grader", lambda *a, **kw: pytest.fail("Private grader called"))
    monkeypatch.setattr(environment.local.benchmark, "prepare_checkouts", lambda *a, **kw: pytest.fail("Checkout called"))
    monkeypatch.setattr(environment.local.subprocess, "run", lambda *a, **kw: pytest.fail("Process called"))
    value = environment.build_environment(**setup["kwargs"])
    assert value.arms == ("BASELINE", "PDF_MEMORY")
    assert len(value.tasks) == 1 and value._rows == setup["rows"]
    assert value.summary["status"] == "PASS_PUBLIC_BINDINGS"
    assert value.summary["grader_construction"] == "LAZY_PRIVATE_BINDING_PER_PREPARED_CELL"
    assert value.summary["model_calls"] == value.summary["official_grader_runs"] == 0
    assert value._images[setup["target"]["instance_id"]]["benchmark_id"] == "swebench_verified"
    assert not value._prepared_cells


@pytest.mark.parametrize("arms", [(), ("BASELINE", "BASELINE"), ("NO_MEMORY",), ("A", "C")])
def test_build_rejects_unknown_or_duplicate_arms(setup, arms):
    with pytest.raises(environment.local.LocalEnvironmentError, match="arms"):
        environment.build_environment(**{**setup["kwargs"], "arms": arms})


def test_build_rejects_missing_image_before_harness_preparation(setup, monkeypatch):
    Path(setup["kwargs"]["image_index_path"]).write_text('{"rows": []}')
    monkeypatch.setattr(environment.local, "prepare_harnesses", lambda *a: pytest.fail("Missing image reached harness"))
    with pytest.raises(dataset.ArchitectureDatasetError, match="digest binding"):
        environment.build_environment(**setup["kwargs"])


@pytest.mark.parametrize("location", ["output_root", "harness_root", "dataset_child"])
def test_workspace_must_be_separate_from_manager_evidence_and_datasets(setup, location):
    kwargs = dict(setup["kwargs"])
    kwargs["workspace_root"] = (setup["source"].parent / "child" if location == "dataset_child"
                                  else kwargs[location])
    with pytest.raises(environment.local.LocalEnvironmentError, match="separate"):
        environment.build_environment(**kwargs)


@pytest.fixture
def prepared(setup, monkeypatch):
    value = environment.build_environment(**setup["kwargs"])
    task = value.tasks[0]
    events = []
    monkeypatch.setattr(environment.PreparedArchitectureEnvironment, "prepare_target",
        lambda self, task: events.append("image"))
    def checkouts(tasks, targets, images, root, *, resume):
        events.append("checkout")
        root.mkdir(parents=True, exist_ok=True)
        runner = environment.local.DockerSandboxCommandRunner(images[task.task_id.split("--", 1)[1]]["image"])
        factory = environment.local.GitCheckoutWorkspaceFactory(
            {task.task_id: root}, {task.task_id: task.commit}, command_runners={task.task_id: runner})
        return factory, {task.task_id: {"initial_status": "", "history_isolation": {},
            "command_sandbox_content_hash": runner.content_hash}}
    monkeypatch.setattr(environment.local.benchmark, "prepare_checkouts", checkouts)
    monkeypatch.setattr(environment.local.benchmark, "_valid_history_isolation_evidence", lambda *a, **kw: True)
    def sandbox(cell):
        events.append("sandbox")
        assert cell.grader is None
        return {"status": "PASS"}
    monkeypatch.setattr(environment.local, "_probe_solver", sandbox)
    def python(cell):
        events.append("python")
        runner = cell.workspace_factory.command_runners[task.task_id]
        return {"status": "PASS", "python_executable": "/opt/synthetic/envs/testbed/bin/python",
            "python_version": "3.11.9", "image": runner.image,
            "command_sandbox_content_hash": runner.content_hash}
    monkeypatch.setattr(environment, "_probe_public_python", python)
    def grader(target, manifest, image, harnesses, output, arm, **kwargs):
        events.append("grader")
        assert manifest == setup["manifest"]
        assert kwargs["loader_preflight_evidence"] is value.loader_preflight
        return {**target, "source_row_sha256": "f" * 64}, SimpleNamespace(arm=arm, output=output)
    monkeypatch.setattr(dataset, "bind_architecture_grader", grader)
    return value, task, events


def test_cells_have_independent_checkouts_lazy_graders_and_probed_public_configuration(prepared):
    value, task, events = prepared
    first, second = [value.prepare_cell(arm, task) for arm in value.arms]
    assert events == ["image", "checkout", "sandbox", "python", "grader"] * 2
    assert first.workspace_factory.checkout_roots != second.workspace_factory.checkout_roots
    assert first.grader.output != second.grader.output
    assert first.target["source_row_sha256"] == "f" * 64
    public = value.public_workspace_configuration(first)
    assert public["python_executable"] == "/opt/synthetic/envs/testbed/bin/python"
    assert public["python_version"] == "3.11.9" and public["source_version"] == "1.0"
    assert public["container_workspace"] == "/testbed"
    assert "source_row_sha256" not in public
    with pytest.raises(environment.local.LocalEnvironmentError, match="already prepared"):
        value.prepare_cell(value.arms[0], task)


def test_python_probe_failure_prevents_private_grader_loading(prepared, monkeypatch):
    value, task, events = prepared
    def fail(cell):
        raise environment.local.LocalEnvironmentError("Synthetic runtime failure")
    monkeypatch.setattr(environment, "_probe_public_python", fail)
    with pytest.raises(environment.local.LocalEnvironmentError, match="runtime failure"):
        value.prepare_cell(value.arms[0], task)
    assert "grader" not in events and not value._prepared_cells


def test_dirty_checkout_prevents_runtime_and_private_grader(prepared, monkeypatch):
    value, task, events = prepared
    monkeypatch.setattr(environment.local.benchmark, "_valid_history_isolation_evidence", lambda *a, **kw: False)
    with pytest.raises(environment.local.LocalEnvironmentError, match="base-only"):
        value.prepare_cell(value.arms[0], task)
    assert events == ["image", "checkout"]


def python_cell(result, calls):
    def run(root, argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(exit_code=0, timed_out=False, output_truncated=False,
            stdout=json.dumps(result), stderr="")
    runner = SimpleNamespace(run=run, image="public@sha256:" + "a" * 64, content_hash="b" * 64)
    return SimpleNamespace(task=SimpleNamespace(task_id="one"), workspace_factory=SimpleNamespace(
        command_runners={"one": runner}, checkout_roots={"one": Path("/synthetic/public")}))


def test_python_probe_uses_actual_image_executable_metadata_without_host_commands():
    calls = []
    metadata = {"python_executable": "/opt/custom/envs/testbed/bin/python",
        "python_realpath": "/opt/custom/envs/testbed/bin/python3.11", "python_version": "3.11.9",
        "implementation": "CPython"}
    evidence = environment._probe_public_python(python_cell(metadata, calls))
    assert evidence["python_executable"] == metadata["python_executable"]
    assert evidence["official_grader_runs"] == 0
    assert len(calls) == 1 and calls[0][:2] == ("/bin/sh", "-ceu")
    assert "/opt/*/envs/testbed/bin/python" in calls[0][2]
    assert "sys.executable" in calls[0][2]


@pytest.mark.parametrize("field,value", [("python_executable", "../../unsafe"),
    ("python_realpath", "/opt/../unsafe"), ("python_version", "unparseable"),
    ("implementation", "unknown"), ("unexpected", "forbidden")])
def test_python_probe_rejects_invalid_public_metadata(field, value):
    metadata = {"python_executable": "/opt/python", "python_realpath": "/opt/python",
        "python_version": "3.11.9", "implementation": "CPython", field: value}
    with pytest.raises(environment.local.LocalEnvironmentError, match="metadata is invalid"):
        environment._probe_public_python(python_cell(metadata, []))


def test_image_index_rejects_duplicate_instances(setup):
    path = Path(setup["kwargs"]["image_index_path"])
    value = json.loads(path.read_text())
    value["rows"].append(value["rows"][0])
    path.write_text(json.dumps(value))
    with pytest.raises(environment.local.LocalEnvironmentError, match="duplicate"):
        environment.load_image_index(path)
