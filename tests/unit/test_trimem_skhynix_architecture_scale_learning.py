"""Cumulative authorities built from public broker fixtures; no execution or gold."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
from test_trimem_skhynix_architecture_learning import inputs, cell, write, captured


def scaled(inputs, monkeypatch, count=24, *, change=None, enroll=True):
    targets = deepcopy(inputs.targets[:2])
    rows = deepcopy(inputs.rows)
    def add(instance, role, scope=None):
        text = "Public scale fixture issue " + instance
        target = {"role": role, "target_id": ("swebench_verified--" if scope == "FINAL" else "swebench--") + instance,
            "instance_id": instance, "repository": "example/project", "base_commit": "a" * 40,
            "instruction_sha256": memory.sha256_bytes(text.encode())}
        if scope:
            target["evaluation_scope"] = scope
        targets.append(target)
        rows[instance] = {"problem_statement": text}
    for index in range(count - 2):
        add("example__project-source-" + str(index), "TRAINING")
    targets.append({**inputs.targets[2], "evaluation_scope": "FINAL"})
    for index in range(learning.SCALE_FINAL_COUNT - 1):
        add("example__project-final-" + str(index), "EVALUATION", "FINAL")
    for index in range(learning.SCALE_DEVELOPMENT_COUNT):
        add("example__project-dev-" + str(index), "EVALUATION", "DEVELOPMENT")
    manifest = {"schema": learning.SCALE_DATASET_SCHEMA, "training_count": count,
        "evaluation_count": learning.SCALE_FINAL_COUNT + learning.SCALE_DEVELOPMENT_COUNT}
    dataset = write(inputs.tmp / "scale-dataset.json", manifest)
    config = {**inputs.config, "dataset_manifest": dataset, "reasoning_effort": "high",
        "run_root": str(inputs.tmp / "scale-run"),
        "training_owner_by_instance": {row["instance_id"]: (index % 2) + 1 for index, row in enumerate(targets[:count])}}
    if change:
        change(config, targets, rows, manifest)
    execution = write(inputs.tmp / "scale-execution.json", config, sidecar=True)
    previous_loader = learning._public_dataset
    def loader(reference):
        if reference == dataset:
            memory._check_ref(reference)
            return deepcopy(targets), deepcopy(rows), deepcopy(manifest)
        return previous_loader(reference)
    monkeypatch.setattr(learning, "_public_dataset", loader)
    root = inputs.tmp / "scale-memory"
    if enroll:
        learning.initialize_learning(root, execution_references=[inputs.execution, execution], dataset_reference=dataset)
    return SimpleNamespace(root=root, tmp=inputs.tmp, targets=targets, rows=rows, config=config,
        execution=execution, dataset=dataset, manifest=manifest)


@pytest.mark.parametrize("count", [24, 120, 240])
def test_cumulative_authority_accepts_all_stage_sizes_and_exact_old_subset(inputs, monkeypatch, count):
    ctx = scaled(inputs, monkeypatch, count)
    enrollment = memory._read(ctx.root / "learning-enrollment.json")
    assert len(enrollment["training_tasks"]) == count
    assert len(enrollment["evaluation_descriptors"]) == 560
    assert enrollment["execution_references"] == [inputs.execution, ctx.execution]
    membership = enrollment["scale_authority"]["execution_training_tasks"]
    assert membership[inputs.execution["sha256"]] == sorted(row["target_id"] for row in inputs.targets[:2])
    assert len(membership[ctx.execution["sha256"]]) == count
    with learning._session(ctx.root, mutable=False):
        pass


@pytest.mark.parametrize("kind", ["owner", "instruction", "revision", "repository", "role", "scope", "count", "organisation", "budget"])
def test_scale_enrollment_rejects_scope_drift_and_historical_retagging(inputs, monkeypatch, kind):
    def mutate(config, targets, rows, manifest):
        if kind == "owner": config["training_owner_by_instance"][targets[0]["instance_id"]] = 2
        elif kind == "instruction":
            rows[targets[0]["instance_id"]]["problem_statement"] = "Changed public issue"
            targets[0]["instruction_sha256"] = memory.sha256_bytes(b"Changed public issue")
        elif kind == "revision": targets[0]["base_commit"] = "b" * 40
        elif kind == "repository": targets[0]["repository"] = "another/project"
        elif kind == "role": targets[0]["role"] = "EVALUATION"
        elif kind == "scope": targets[-1]["evaluation_scope"] = "FINAL"
        elif kind == "count": manifest["training_count"] = 120
        elif kind == "organisation": config["org_id"] = "another-org"
        elif kind == "budget": config["limits"] = {"task_requests": 240}
    with pytest.raises(learning.LearningError):
        scaled(inputs, monkeypatch, change=mutate)


def test_scale_enrollment_requires_execution_coverage_for_every_source(inputs, monkeypatch):
    ctx = scaled(inputs, monkeypatch, enroll=False)
    with pytest.raises(learning.LearningError, match="not all enrolled"):
        learning.initialize_learning(ctx.root, execution_references=[inputs.execution], dataset_reference=ctx.dataset)


def test_development_instruction_alias_cannot_enter_training_bank_scope(inputs, monkeypatch):
    def mutate(config, targets, rows, manifest):
        target = targets[-1]
        target["instruction_sha256"] = targets[0]["instruction_sha256"]
        rows[target["instance_id"]]["problem_statement"] = rows[targets[0]["instance_id"]]["problem_statement"]
    with pytest.raises(ValueError, match="disjoint"):
        scaled(inputs, monkeypatch, change=mutate)


def test_old_public_sources_import_without_grader_or_resolve_and_preserve_old_authority(inputs, monkeypatch):
    paths, refs = captured(inputs, second_green=False)
    old_bytes = {p: p.read_bytes() for p in inputs.root.rglob("*") if p.is_file()}
    ctx = scaled(inputs, monkeypatch, 120)
    imported = learning.import_captured_sources(ctx.root, source_receipt_references=refs,
        output_path=ctx.tmp / "source-import.json")
    receipt = memory._read(imported["path"])
    assert receipt["status"] == "COMPLETE" and len(receipt["sources"]) == 2
    assert receipt["model_calls"] == receipt["solver_runs"] == receipt["official_grader_runs"] == 0
    assert receipt["official_outcomes_read"] is False
    assert {p: p.read_bytes() for p in old_bytes} == old_bytes
    assert learning.capture_existing_sources(ctx.root, cell_references=[memory._ref(p) for p in paths],
        output_path=ctx.tmp / "source-import.json") == imported
    assert not memory._read(ctx.root / "catalog.json")["skills"]


def test_expanded_authority_cannot_claim_new_task_executed_under_old_scope(inputs, monkeypatch):
    ctx = scaled(inputs, monkeypatch)
    path = cell(ctx, 3)
    value = memory._read(path)
    value["experiment_config"] = inputs.execution["path"]
    memory._write(path, value)
    path.with_suffix(".sha256").write_text(memory._hash(value) + "\n")
    receipt = memory._read(learning.capture_cell(ctx.root, path)["path"])
    assert receipt["status"] == "INVALID_SOURCE" and receipt["captures"] == []
    assert "never enrolled" in receipt["failures"][0]["reason"]


def test_scale_execution_membership_excludes_adopted_and_previously_run_sources(inputs, monkeypatch):
    ctx = scaled(inputs, monkeypatch, enroll=False)
    eligible = [row["target_id"] for row in ctx.targets[2:24]]
    authority = {"purpose": "TRAINING_INCREMENT", "task_ids": eligible}
    ctx.config["scale_authority_reference"] = write(inputs.tmp / "subset-authority.json", authority)
    memory._write(ctx.execution["path"], ctx.config)
    Path(ctx.execution["path"]).with_suffix(".sha256").write_text(memory._hash(ctx.config) + "\n")
    ctx.execution = memory._ref(ctx.execution["path"])
    import trimem_skhynix_architecture_run as execution_module
    monkeypatch.setattr(execution_module, "execution_enrollment", lambda config, dataset=None: deepcopy(authority))
    learning.initialize_learning(ctx.root, execution_references=[inputs.execution, ctx.execution], dataset_reference=ctx.dataset)
    enrollment = memory._read(ctx.root / "learning-enrollment.json")
    assert enrollment["scale_authority"]["execution_training_tasks"][ctx.execution["sha256"]] == sorted(eligible)
    forbidden = cell(ctx, 1)
    receipt = memory._read(learning.capture_cell(ctx.root, forbidden)["path"])
    assert receipt["status"] == "INVALID_SOURCE" and receipt["captures"] == []
    assert "outside every explicitly enrolled" in receipt["failures"][0]["reason"]


def test_no_ready_smaller_bank_does_not_stop_larger_source_capture(inputs, monkeypatch):
    paths, _ = captured(inputs, second_green=False)
    with pytest.raises(learning.LearningError, match="reflection proposal"):
        learning.freeze_published_bank(inputs.root, inputs.tmp / "no-bank.json")
    ctx = scaled(inputs, monkeypatch, 120)
    assert memory._read(learning.capture_cell(ctx.root, paths[0])["path"])["status"] == "CAPTURED"
    assert not (inputs.tmp / "no-bank.json").exists()
    assert not (ctx.root / "learning-frozen.json").exists()


def test_default_authority_keeps_original_schema_without_scale_switches(inputs):
    enrollment = memory._read(inputs.root / "learning-enrollment.json")
    assert "scale_authority" not in enrollment
    assert enrollment["learning_version"] == 2
    assert enrollment["execution_references"] == [inputs.execution]
