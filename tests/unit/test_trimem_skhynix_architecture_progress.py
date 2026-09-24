"""Public synthetic reporting: no native process, model, grader or cleanup."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"), str(Path(__file__).resolve().parents[2] / "scripts")]
import trimem_skhynix_architecture_pipeline as pipeline
import trimem_skhynix_architecture_progress as progress


def execution(tmp_path, phase, effort="ultra", *, shared_root=None, name=None):
    value = {"run_root": str(shared_root or tmp_path / phase), "reasoning_effort": effort,
        "native_control_root": str(tmp_path / (phase + "-native"))}
    reference = pipeline.retain(tmp_path / ((name or phase) + "-config.json"), value)
    Path(reference["path"]).with_suffix(".sha256").write_text(pipeline.digest(pipeline.canonical_bytes(value)))
    return reference


def result(config_reference, phase, arm, resolved, task="public-task"):
    config = pipeline.check(config_reference)
    root = Path(config["run_root"]) / "cells" / phase / task / arm
    pipeline.retain(root / "cell.json", {"experiment_config": config_reference["path"],
        "task_public": {"task_id": task, "repository": "public/repository"},
        "arm": arm, "phase": phase, "target": {"instance_id": task + "-instance"}})
    audit = pipeline.retain(root / "execution-audit.json", {"passed": True})
    (root / "broker").mkdir()
    (root / "broker/submission.diff").write_bytes(b"public synthetic diff\n")
    value = {"official": True, "grader_status": "success", "resolved": resolved,
        "experiment_sha256": pipeline.digest(pipeline.canonical_bytes(config)), "task_id": task, "arm": arm,
        "phase": phase, "execution_audit_sha256": audit["sha256"], "grader_wall_time_ms": 1, "bank_sha256": "a" * 64,
        "broker_status": {"submission": {"actions": 3, "started_at": 1, "submitted_at": 4},
            "workers_admitted": 2, "memory_injections": 0}}
    return pipeline.retain(root / "public-result.json", value)


def operations():
    value = pipeline.FrozenOperations.__new__(pipeline.FrozenOperations)
    value.modules = {"progress": progress}
    return value


def test_exact_snapshot_reference_preserves_partial_denominators_and_paired_delta(tmp_path):
    train, evaluation = execution(tmp_path, "TRAINING"), execution(tmp_path, "EVALUATION")
    result(train, "TRAINING", "PDF_MEMORY", True)
    result(evaluation, "EVALUATION", "BASELINE", False)
    result(evaluation, "EVALUATION", "PDF_MEMORY", True)
    reference = operations().progress([train, evaluation], tmp_path / "public")
    snapshot = pipeline.check(reference)
    assert Path(reference["path"]).read_bytes() == (tmp_path / "public/progress.json").read_bytes()
    assert snapshot["training"]["official_complete"] == 1
    assert snapshot["training"]["full_cohort_rate"] is None
    assert snapshot["completed_pairs"] == 1 and snapshot["completed_pair_delta_percentage_points"] == 100
    assert snapshot["full_cohort_delta_percentage_points"] is None
    assert all(values["missing"] == 499 for values in snapshot["evaluation"].values())


def test_next_export_never_reads_previous_progress_snapshots(tmp_path, monkeypatch):
    config = execution(tmp_path, "TRAINING")
    result(config, "TRAINING", "PDF_MEMORY", False)
    controller = operations()
    old = controller.progress([config], tmp_path / "public")
    old_path, read_bytes = Path(old["path"]), Path.read_bytes
    old_raw = read_bytes(old_path)

    def bounded_read(path):
        if path == old_path:
            raise AssertionError("Historical snapshot was reread while finding the new export")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", bounded_read)
    new = controller.progress([config], tmp_path / "public")
    assert new["path"] != old["path"]
    assert pipeline.check(new)["training"]["resolved"] == 0
    assert read_bytes(old_path) == old_raw


@pytest.mark.parametrize("failure", ["unofficial", "audit", "changed_preserved_result"])
def test_progress_does_not_accept_changed_or_unofficial_evidence(tmp_path, failure):
    config = execution(tmp_path, "TRAINING")
    reference = result(config, "TRAINING", "PDF_MEMORY", True)
    if failure == "changed_preserved_result":
        operations().progress([config], tmp_path / "public")
    path = Path(reference["path"])
    value = pipeline.read(path)
    if failure == "unofficial":
        value["official"] = False
    elif failure == "audit":
        value["execution_audit_sha256"] = "0" * 64
    else:
        value["resolved"] = False
    path.write_bytes(pipeline.canonical_bytes(value))
    with pytest.raises(ValueError, match="official result|execution audit|Preserved public result"):
        operations().progress([config], tmp_path / "public")


@pytest.mark.parametrize("failure", ["missing_reference", "foreign_path", "wrong_current"])
def test_controller_requires_the_exact_new_bound_snapshot(tmp_path, failure):
    target = tmp_path / "public"
    snapshot = pipeline.retain(target / "progress-history/new.json", {"public": True})
    (target / "progress.json").write_bytes(Path(snapshot["path"]).read_bytes())
    if failure == "foreign_path":
        snapshot = pipeline.retain(tmp_path / "foreign.json", {"public": True})
    elif failure == "wrong_current":
        (target / "progress.json").write_bytes(b"{}")
    controller = operations()
    controller.modules["progress"] = SimpleNamespace(export_progress=lambda *args:
        {} if failure == "missing_reference" else {"snapshot_reference": snapshot})
    with pytest.raises(pipeline.PipelineError, match="snapshot"):
        controller.progress([], target)


def test_shared_training_root_routes_preserved_ultra_and_future_high_exactly(tmp_path):
    root = tmp_path / "same-training-run"
    old = execution(tmp_path, "TRAINING", "ultra", shared_root=root, name="v5")
    new = execution(tmp_path, "TRAINING", "high", shared_root=root, name="v6")
    old_result = result(old, "TRAINING", "PDF_MEMORY", False, task="earlier-ultra")
    before = operations().progress([old], tmp_path / "public")
    old_snapshot = Path(before["path"]).read_bytes()
    result(new, "TRAINING", "PDF_MEMORY", True, task="later-high")
    after = pipeline.check(operations().progress([old, new], tmp_path / "public"))
    assert after["training"]["official_complete"] == 2 and after["training"]["missing"] == 22
    assert after["training"]["full_cohort_rate"] is None
    assert after["training_by_reasoning_effort"] == {
        "ultra": {"official_complete": 1, "resolved": 0, "completed_sample_rate": 0},
        "high": {"official_complete": 1, "resolved": 1, "completed_sample_rate": 1}}
    assert {(row["task_id"], row["reasoning_effort"]) for row in after["rows"]} == {
        ("earlier-ultra", "ultra"), ("later-high", "high")}
    assert pipeline.ref(old_result["path"]) == old_result
    assert Path(before["path"]).read_bytes() == old_snapshot


@pytest.mark.parametrize("failure", ["omitted_old", "wrong_cell_path", "duplicate_configuration", "mixed_pair"])
def test_forward_progress_rejects_missing_or_mismatched_execution_authority(tmp_path, failure):
    root = tmp_path / "shared"
    old = execution(tmp_path, "TRAINING", "ultra", shared_root=root, name="old")
    new = execution(tmp_path, "TRAINING", "high", shared_root=root, name="new")
    old_result = result(old, "TRAINING", "PDF_MEMORY", True, task="ultra")
    refs = [old, new]
    if failure == "omitted_old":
        refs = [new]
    elif failure == "wrong_cell_path":
        cell_path = Path(old_result["path"]).parent / "cell.json"
        cell = pipeline.read(cell_path)
        cell["experiment_config"] = new["path"]
        cell_path.write_bytes(pipeline.canonical_bytes(cell))
    elif failure == "duplicate_configuration":
        refs.append(old)
    else:
        result(old, "EVALUATION", "BASELINE", False, task="paired")
        result(new, "EVALUATION", "PDF_MEMORY", True, task="paired")
    with pytest.raises(ValueError, match="unenrolled|binding differs|Duplicate execution|reasoning settings differ"):
        operations().progress(refs, tmp_path / "public")
