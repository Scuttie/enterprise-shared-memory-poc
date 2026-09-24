"""Parallel evaluation dispatch policy without native models or official graders."""
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import trimem_skhynix_architecture_scale_pipeline as scale


@pytest.mark.parametrize("value", [0, -1, 5, True, False, None, "2", 2.0])
def test_invalid_parallel_limit_is_rejected_before_configuration_side_effects(value):
    with pytest.raises(scale.core.PipelineError, match="evaluation_max_workers"):
        scale.validate_config({"evaluation_max_workers": value})


def test_parallelism_is_opt_in_and_bounded():
    assert scale.evaluation_max_workers({}) == 1
    for value in (1, 2, 3, 4):
        assert scale.evaluation_max_workers({"evaluation_max_workers": value}) == value


class BatchRunner:
    def __init__(self, root, planned=5, *, block=False, invalid_delta=False):
        self.root = root
        self.planned = planned
        self.completed = 0
        self.calls = []
        self.block = block
        self.invalid_delta = invalid_delta
        self.max_workers = 1

    def status(self):
        complete = self.completed == self.planned
        return {"status": "COMPLETE" if complete else "IN_PROGRESS",
                "completed_cells": self.completed, "planned_cells": self.planned,
                "terminal_full_audit_complete": complete, "cells": [], "max_workers": self.max_workers,
                "parallel_policy_reference": None if self.max_workers == 1 else
                    {"path": str(self.root / "parallel-policy.json"), "sha256": "p" * 64}}

    def run(self, **kwargs):
        self.calls.append(kwargs)
        self.max_workers = kwargs.get("max_workers", 1)
        self.completed += min(kwargs["cell_limit"], self.planned - self.completed)
        if self.invalid_delta:
            self.completed += 1
        value = self.status()
        if self.block:
            value["status"] = "BLOCKED"
        return value


def controller():
    pipeline = scale.ScalePipeline.__new__(scale.ScalePipeline)
    pipeline.records = []
    pipeline.record = lambda stage, details, **kwargs: pipeline.records.append((stage, details))
    pipeline.progress = lambda: None
    return pipeline


def test_default_training_advance_preserves_serial_call_shape(tmp_path):
    pipeline = controller()
    pipeline.config = {"evaluation_max_workers": 4}
    runner = BatchRunner(tmp_path)
    result = pipeline._advance_runner(runner, "training-240")
    assert result["status"] == "COMPLETE"
    assert runner.calls == [{"cell_limit": 1}] * 5


@pytest.mark.parametrize("workers", [2, 3, 4])
def test_evaluation_bounded_batches_allow_multiple_completions(tmp_path, workers):
    runner = BatchRunner(tmp_path)
    result = controller()._advance_runner(runner, "verified500", max_workers=workers)
    assert result["status"] == "COMPLETE"
    assert all(call == {"cell_limit": workers, "max_workers": workers} for call in runner.calls)
    assert len(runner.calls) == (5 + workers - 1) // workers


def test_blocked_batch_is_not_retried_after_other_cells_complete(tmp_path):
    runner = BatchRunner(tmp_path, block=True)
    with pytest.raises(scale.core.PipelineError, match="cohort blocked"):
        controller()._advance_runner(runner, "bank-240", max_workers=2)
    assert len(runner.calls) == 1
    assert runner.completed == 2


def test_completion_count_cannot_exceed_declared_batch(tmp_path):
    with pytest.raises(scale.core.PipelineError, match="completion count"):
        controller()._advance_runner(BatchRunner(tmp_path, invalid_delta=True), "bank-240", max_workers=2)


@pytest.mark.parametrize("requested,actual_workers", [(2, 1), (2, 3), (1, 2)])
def test_completed_cohort_cannot_be_relabeled_as_different_parallelism(tmp_path, requested, actual_workers):
    runner = BatchRunner(tmp_path)
    runner.completed = runner.planned
    runner.max_workers = actual_workers
    with pytest.raises(scale.core.PipelineError, match="parallel execution policy"):
        controller()._advance_runner(runner, "bank-240", max_workers=requested)
    assert not runner.calls


def test_missing_policy_evidence_cannot_be_reported_as_parallel(tmp_path):
    runner = BatchRunner(tmp_path)
    original = runner.status
    runner.status = lambda: {**original(), "parallel_policy_reference": None}
    with pytest.raises(scale.core.PipelineError, match="parallel execution policy"):
        controller()._advance_runner(runner, "bank-240", max_workers=2)
    assert len(runner.calls) == 1


@pytest.mark.parametrize("purpose", ["DEVELOPMENT_BASELINE", "DEVELOPMENT_BANK", "FINAL_EVALUATION"])
@pytest.mark.parametrize("workers", [1, 2, "default"])
def test_all_evaluation_arms_use_same_declared_limit_and_report_it(tmp_path, purpose, workers):
    declared = workers
    workers = 1 if workers == "default" else workers
    pipeline = controller()
    pipeline.root = tmp_path / "pipeline"
    pipeline.config = {"evaluation_native_root": str(tmp_path / "native"), "evaluation_max_workers": workers}
    if declared == "default":
        del pipeline.config["evaluation_max_workers"]
    pipeline.reference = scale.core.retain(tmp_path / "pipeline.json", pipeline.config)
    pipeline.latest = lambda *args: None
    if workers == 1:
        # The retained reflection-recovery controller forwards positional args
        # only. Default serial evaluation must keep that adapter compatible.
        advance = pipeline._advance_runner
        pipeline._advance_runner = lambda *args: advance(*args)
    template = scale.core.retain(tmp_path / "template.json", {
        "dataset_manifest": {"path": "/synthetic/dataset", "sha256": "d" * 64},
        "training_grade_hold_policy": scale.TRAINING_GRADE_HOLD_POLICY})
    arms = ("BASELINE", "PDF_MEMORY") if purpose == "FINAL_EVALUATION" else (
        ("BASELINE",) if purpose == "DEVELOPMENT_BASELINE" else ("PDF_MEMORY",))
    captured = []

    class EvaluationRunner(BatchRunner):
        @classmethod
        def create(cls, root, **kwargs):
            assert kwargs["phase"] == "EVALUATION"
            execution = scale.core.read(kwargs["experiment_path"])
            assert "training_grade_hold_policy" not in execution
            scale.core.retain(root / "cohort.json", {"synthetic": True})
            runner = cls(root, planned=len(arms))
            runner.schedule = [{"task_id": "synthetic-task", "arm": arm} for arm in arms]
            captured.append(runner)
            return runner

        def _validate_result(self, row):
            return ({"resolved": True, "broker_status": {"submission": {"actions": 1},
                    "memory_injections": int(row["arm"] == "PDF_MEMORY")}, "grader_wall_time_ms": 1},
                    {"path": "/synthetic/public-result", "sha256": "r" * 64})

        def status(self):
            return {**super().status(), "max_workers": workers,
                    "parallel_policy_reference": None if workers == 1 else {"path": "/synthetic/policy", "sha256": "p" * 64}}

    pipeline.operations = SimpleNamespace(cohorts={}, modules={
        "cohort": SimpleNamespace(CohortRunner=EvaluationRunner, execution=SimpleNamespace(
            create_execution_enrollment=lambda path, **kwargs: scale.core.retain(path, {"synthetic": True}))),
        "quarantine": SimpleNamespace(initialize_quarantine=lambda path, **kwargs: scale.core.retain(path / "binding.json", {"synthetic": True}),
                                      make_quarantine_hook=lambda path: lambda *args: None),
        "cleanup": SimpleNamespace(create_cleanup_policy=lambda path, **kwargs: scale.core.retain(path, {"synthetic": True})),
    })
    report, reference = pipeline._evaluation(purpose, {"size": 240, "execution_reference": template}, None, "evaluation")
    if declared == "default":
        assert "max_workers" not in report and "parallel_policy_reference" not in report
    else:
        assert report["max_workers"] == workers
        assert report["parallel_policy_reference"] == captured[0].status()["parallel_policy_reference"]
    assert scale.core.check(reference) == report
    assert all(call.get("max_workers", 1) == workers for call in captured[0].calls)
