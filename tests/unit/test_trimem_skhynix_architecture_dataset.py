"""Public projection and isolated grader handoff, using synthetic sources only."""
from copy import deepcopy
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import trimem_skhynix_architecture_dataset as dataset
import trimem_skhynix_architecture_plan as plan


def write_json(path, value):
    path.write_bytes(plan.canonical(value) + b"\n")
    return {"path": str(path), "sha256": plan.file_sha(path)}


def source_row(repository, number):
    return {"instance_id": repository.replace("/", "__") + f"-{number}", "repo": repository,
        "base_commit": f"{number:040x}", "created_at": f"2020-01-{1 + number % 20:02d}T00:00:00Z",
        "problem_statement": f"  Synthetic public problem {repository} {number}.\n",
        "version": "1.0", "environment_setup_commit": "d" * 40,
        "patch": "SYNTHETIC_PRIVATE_PATCH_SENTINEL", "test_patch": "SYNTHETIC_PRIVATE_TEST_SENTINEL",
        "hints_text": "SYNTHETIC_PRIVATE_HINT_SENTINEL", "FAIL_TO_PASS": '["private_test"]',
        "PASS_TO_PASS": '["other_private_test"]'}


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    repositories = [f"fixture{index}/repo" for index in range(12)]
    evaluation_rows = [source_row(repositories[index % 12], index) for index in range(500)]
    training_rows = [source_row(repository, 1001 + index) for repository in repositories for index in range(3)]
    result = {"output": tmp_path / "manifest.json", "training_rows": training_rows}
    for role, rows, pin in (("evaluation", evaluation_rows, plan.EVALUATION_SOURCE),
                            ("training", training_rows, dataset.TRAINING_SOURCE)):
        source = tmp_path / (role + ".parquet")
        pq.write_table(pa.Table.from_pylist(rows), source)
        pin = {**pin, "sha256": plan.file_sha(source), "bytes": source.stat().st_size}
        tasks = sorted((dataset._descriptor(row) for row in rows), key=lambda row: row["instance_id"])
        if role == "evaluation":
            monkeypatch.setattr(plan, "EVALUATION_SOURCE", pin)
            monkeypatch.setattr(plan, "EVALUATION_TASKS_SHA256", plan.sha(plan.canonical(tasks)))
        else:
            monkeypatch.setattr(dataset, "TRAINING_SOURCE", pin)
        inventory = {"schema": plan.INVENTORY_SCHEMA, "dataset": {**pin, "path": str(source)}, "tasks": tasks}
        result[role] = write_json(tmp_path / (role + ".json"), inventory)
        result[role + "_value"] = inventory
        result[role + "_source"] = source
    return result


def build(inputs):
    proposal = dataset.propose_training_enrollment(inputs["evaluation"], inputs["training"])
    return dataset.build_architecture_manifest(inputs["evaluation"], inputs["training"],
        training_instance_ids=proposal["instance_ids"], output=inputs["output"])


def load(receipt, **kwargs):
    return dataset.load_architecture_rows(receipt["path"], expected_sha256=receipt["sha256"], **kwargs)


def image(target):
    tag = dataset.official_image_tag(target["instance_id"])
    return {"instance_id": target["instance_id"], "benchmark_id": "swebench_verified",
        "harness_image_tag": tag, "image": tag.removesuffix(":latest") + "@sha256:" + "a" * 64}


def test_proposal_is_deterministic_all_twelve_repositories_and_writes_nothing(inputs, monkeypatch):
    monkeypatch.setattr(pq, "read_table", lambda *a, **kw: pytest.fail("Proposal decoded source rows"))
    proposal = dataset.propose_training_enrollment(inputs["evaluation"], inputs["training"])
    assert proposal == dataset.propose_training_enrollment(inputs["evaluation"], inputs["training"])
    assert proposal["status"] == "PROPOSED_NOT_ENROLLED"
    assert len(proposal["instance_ids"]) == 24
    assert len({row["repository"] for row in proposal["tasks"]}) == 12
    assert all(identity.endswith(("-1001", "-1002")) for identity in proposal["instance_ids"])
    assert not inputs["output"].exists()


def test_public_loader_reads_only_allowlisted_columns_and_builds_full500_plus24(inputs, monkeypatch):
    original = pq.read_table
    calls = []
    def public_only(path, **kwargs):
        columns = kwargs.get("columns")
        assert columns and set(columns) <= set((*dataset.PUBLIC_COLUMNS, *dataset.PUBLIC_ENVIRONMENT_COLUMNS))
        calls.append(columns)
        return original(path, **kwargs)
    monkeypatch.setattr(pq, "read_table", public_only)
    receipt = build(inputs)
    targets, rows, manifest = load(receipt)
    assert len(targets) == len(rows) == 524
    assert len(calls) == 4
    assert [target["order_index"] for target in targets] == list(range(524))
    assert sum(target["role"] == "EVALUATION" for target in targets) == 500
    assert manifest["source_instance_ids_disjoint"] and manifest["public_instruction_hashes_disjoint"]
    assert manifest["model_calls"] == manifest["training_runs"] == manifest["official_grader_runs"] == 0
    assert all("source_row_sha256" not in target for target in targets)
    assert b"PRIVATE_" not in plan.canonical([targets, rows, manifest])
    import trimem_benchmark_run as benchmark
    tasks = benchmark.coding_tasks(targets, rows)
    assert len(tasks) == 524 and all(task.instruction.startswith("Synthetic public problem") for task in tasks)
    assert tasks[0].task_id.startswith("swebench--")
    assert tasks[-1].task_id.startswith("swebench_verified--")
    assert targets[0]["source_dataset_id"] == "SWE-bench/SWE-bench"
    assert targets[0]["dataset_revision"] == dataset.TRAINING_SOURCE["revision"]


@pytest.mark.parametrize("role,count", [("TRAINING", 24), ("EVALUATION", 500)])
def test_role_subset_keeps_exact_manifest_and_public_row_alignment(inputs, role, count):
    targets, rows, manifest = load(build(inputs), role=role)
    assert len(targets) == len(rows) == count
    assert all(target["role"] == role for target in targets)
    assert len(manifest["targets"]) == 524


@pytest.mark.parametrize("selection", [[], ["absent__repo-1"], ["fixture0__repo-1001"] * 2])
def test_invalid_explicit_training_selection_is_rejected(inputs, selection):
    with pytest.raises(dataset.ArchitectureDatasetError):
        dataset.build_architecture_manifest(inputs["evaluation"], inputs["training"],
            training_instance_ids=selection, output=inputs["output"])
    assert not inputs["output"].exists()


@pytest.mark.parametrize("field", ["instance_id", "instruction_sha256", "repository"])
def test_training_inventory_overlap_and_foreign_repository_fail_before_source_decode(inputs, field, monkeypatch):
    value = deepcopy(inputs["training_value"])
    if field == "repository":
        value["tasks"][0].update(repository="foreign/repo", instance_id="foreign__repo-1")
    elif field == "instance_id":
        value["tasks"][0] = deepcopy(inputs["evaluation_value"]["tasks"][0])
    else:
        value["tasks"][0][field] = inputs["evaluation_value"]["tasks"][0][field]
    value["tasks"].sort(key=lambda row: row["instance_id"])
    reference = write_json(Path(inputs["training"]["path"]), value)
    monkeypatch.setattr(pq, "read_table", lambda *a, **kw: pytest.fail("Invalid inventory decoded source"))
    with pytest.raises(dataset.ArchitectureDatasetError):
        dataset.propose_training_enrollment(inputs["evaluation"], reference)


@pytest.mark.parametrize("tamper", ["manifest_bytes", "target_drop", "target_hash", "target_gold", "source_bytes"])
def test_loader_rejects_changed_bytes_omissions_and_extra_fields(inputs, tamper):
    receipt = build(inputs)
    if tamper == "source_bytes":
        with inputs["evaluation_source"].open("ab") as stream:
            stream.write(b"changed")
    elif tamper == "manifest_bytes":
        with inputs["output"].open("ab") as stream:
            stream.write(b" ")
    else:
        value = plan._json(inputs["output"].read_bytes())
        if tamper == "target_drop":
            value["targets"].pop()
        elif tamper == "target_hash":
            value["targets"][0]["public_source_row_sha256"] = "f" * 64
        else:
            value["targets"][0]["patch"] = "forbidden"
        receipt = write_json(inputs["output"], value)
    with pytest.raises((dataset.ArchitectureDatasetError, plan.ArchitecturePlanError)):
        load(receipt)


def test_builder_retains_existing_manifest_and_never_overwrites_different_bytes(inputs):
    receipt = build(inputs)
    assert build(inputs) == receipt
    original = inputs["output"].read_bytes()
    inputs["output"].write_bytes(original + b" ")
    with pytest.raises(dataset.ArchitectureDatasetError, match="Existing"):
        build(inputs)
    assert inputs["output"].read_bytes() == original + b" "


def test_grader_lazily_decodes_exact_original_source_only_at_manager_handoff(inputs, monkeypatch):
    targets, rows, manifest = load(build(inputs), role="TRAINING")
    target = targets[0]
    original = pq.read_table
    calls = []
    def private_exact(path, **kwargs):
        assert "columns" not in kwargs
        assert kwargs["filters"] == [("instance_id", "==", target["instance_id"])]
        assert Path(path) == inputs["training_source"]
        calls.append(path)
        return original(path, **kwargs)
    monkeypatch.setattr(pq, "read_table", private_exact)
    import trimem_benchmark_run as benchmark
    sentinel = object()
    def existing_factory(bound, private, img, harnesses, output, arm, support, **kwargs):
        assert private["patch"] == "SYNTHETIC_PRIVATE_PATCH_SENTINEL"
        assert bound["source_row_sha256"] == plan.sha(plan.canonical(private))
        assert bound["benchmark_id"] == "swebench_verified"
        assert bound["dataset_revision"] == dataset.TRAINING_SOURCE["revision"]
        assert support == ()
        return sentinel
    monkeypatch.setattr(benchmark, "grader_factory", existing_factory)
    bound, grader = dataset.bind_architecture_grader(target, manifest, image(target), {},
        inputs["output"].parent / "grader", "A")
    assert grader is sentinel and len(calls) == 1
    assert len(bound["source_row_sha256"]) == 64
    assert "source_row_sha256" not in target
    assert b"PRIVATE_" not in plan.canonical([bound, rows, manifest])
    rebound, repeated = dataset.bind_architecture_grader(bound, manifest, image(target), {},
        inputs["output"].parent / "grader", "C")
    assert rebound == bound and repeated is sentinel and len(calls) == 2
    with pytest.raises(dataset.ArchitectureDatasetError, match="Previously bound"):
        dataset.bind_architecture_grader({**bound, "source_row_sha256": "f" * 64}, manifest,
            image(target), {}, inputs["output"].parent / "grader", "A")


@pytest.mark.parametrize("field,value", [("image", "swebench/foreign@sha256:" + "a" * 64),
    ("harness_image_tag", "swebench/foreign:latest"), ("instance_id", "foreign__repo-1"),
    ("benchmark_id", "other")])
def test_mismatched_image_is_rejected_before_private_decoding(inputs, monkeypatch, field, value):
    targets, _, manifest = load(build(inputs), role="TRAINING")
    target = targets[0]
    binding = {**image(target), field: value}
    monkeypatch.setattr(pq, "read_table", lambda *a, **kw: pytest.fail("Image failure decoded private source"))
    with pytest.raises(dataset.ArchitectureDatasetError):
        dataset.bind_architecture_grader(target, manifest, binding, {}, inputs["output"].parent, "A")


def test_public_row_must_match_descriptor_even_with_updated_opaque_source_pin(inputs, monkeypatch):
    inventory = deepcopy(inputs["training_value"])
    altered = deepcopy(inputs["training_rows"])
    altered[0]["problem_statement"] = "Different synthetic statement"
    source = inputs["training_source"]
    pq.write_table(pa.Table.from_pylist(altered), source)
    pin = {**dataset.TRAINING_SOURCE, "sha256": plan.file_sha(source), "bytes": source.stat().st_size}
    monkeypatch.setattr(dataset, "TRAINING_SOURCE", pin)
    inventory["dataset"] = {**pin, "path": str(source)}
    inputs["training"] = write_json(Path(inputs["training"]["path"]), inventory)
    with pytest.raises(dataset.ArchitectureDatasetError, match="descriptor"):
        build(inputs)


def test_source_tamper_fails_before_private_parquet_decode(inputs, monkeypatch):
    targets, _, manifest = load(build(inputs), role="TRAINING")
    target = targets[0]
    with inputs["training_source"].open("ab") as stream:
        stream.write(b"changed")
    monkeypatch.setattr(pq, "read_table", lambda *a, **kw: pytest.fail("Changed source was decoded"))
    with pytest.raises(dataset.ArchitectureDatasetError, match="pinned source"):
        dataset.bind_architecture_grader(target, manifest, image(target), {},
            inputs["output"].parent / "grader", "A")


def test_public_reader_result_with_forbidden_fields_is_rejected(inputs, monkeypatch):
    original = pq.read_table
    class UnexpectedColumns:
        def __init__(self, rows):
            self.rows = rows
        def to_pylist(self):
            return [{**row, "patch": "SYNTHETIC_READER_ERROR"} for row in self.rows]
    monkeypatch.setattr(pq, "read_table", lambda path, **kwargs:
        UnexpectedColumns(original(path, **kwargs).to_pylist()))
    with pytest.raises(dataset.ArchitectureDatasetError, match="forbidden columns"):
        build(inputs)
