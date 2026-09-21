"""The evaluation denominator and pre-solve freeze are experimental contracts."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/trimem_skhynix_codex_batch.py"
spec = importlib.util.spec_from_file_location("native_batch", SCRIPT)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_training_without_admissible_shared_record_remains_in_split(tmp_path):
    path = tmp_path / "bank.json"
    batch.broker.write(path, {"training_task_ids": ["passed", "failed"],
        "evaluation_task_ids": ["eval"], "evaluation_targets": [{"task_id": "eval"}],
        "cold_start": False, "records": [{"source": {"task_id": "passed"}}]})
    contract = {"frozen_memory_bank": {"path": str(path),
                                     "sha256": batch.broker.sha(path.read_bytes())}}
    batch.validate_split(contract, {"passed", "failed"}, {"eval"})


@pytest.mark.parametrize("additional", [None, [], ["older"], ["older", "unknown"]])
def test_split_includes_additional_prior_training_targets(tmp_path, additional):
    b = batch.broker
    bank_path, manifest_path = tmp_path / "bank.json", tmp_path / "manifest.json"
    b.write(bank_path, {"training_task_ids": ["train", "prior", "older"],
        "evaluation_task_ids": ["eval"], "evaluation_targets": [{"task_id": "eval"}],
        "cold_start": False, "records": []})
    manifest = {"targets": [{"target_id": "train", "role": "TRAINING"},
                            {"target_id": "eval", "role": "EVALUATION"}],
                "prior_training_target": {"target_id": "prior"}}
    if additional is not None:
        manifest["additional_prior_training_targets"] = [{"target_id": item} for item in additional]
    b.write(manifest_path, manifest)
    contract = {"frozen_memory_bank": b.frozen_input(bank_path),
                "supplemental_manifest": b.frozen_input(manifest_path)}
    if additional == ["older"]:
        batch.validate_split(contract, {"train", "prior", "older"}, {"eval"})
    else:
        with pytest.raises(ValueError, match="manifest roles differ"):
            batch.validate_split(contract, {"train", "prior", "older"}, {"eval"})


@pytest.mark.parametrize("profile", ["native004", "native005", "native002", "native003", "missing"])
def test_only_independent_profiles_can_omit_prior_training(tmp_path, profile):
    import trimem_skhynix_native_dataset as dataset
    b = batch.broker
    bank_path, manifest_path = tmp_path / "bank.json", tmp_path / "manifest.json"
    b.write(bank_path, {"training_task_ids": ["train1", "train2"],
        "evaluation_task_ids": ["eval"], "evaluation_targets": [{"task_id": "eval"}],
        "cold_start": False, "records": [{"source": {"task_id": "train1"}}]})
    manifest = {"targets": [{"target_id": "train1", "role": "TRAINING"},
                            {"target_id": "train2", "role": "TRAINING"},
                            {"target_id": "eval", "role": "EVALUATION"}],
                "prior_training_target": None, "additional_prior_training_targets": []}
    selections = {"native004": dataset.NATIVE004_SELECTION, "native005": dataset.NATIVE005_SELECTION,
                  "native003": dataset.NATIVE003_SELECTION,
                  "native002": dataset.SELECTION}
    if profile in selections:
        manifest["selection"] = selections[profile]
    b.write(manifest_path, manifest)
    contract = {"frozen_memory_bank": b.frozen_input(bank_path),
                "supplemental_manifest": b.frozen_input(manifest_path)}
    if profile in ("native004", "native005"):
        batch.validate_split(contract, {"train1", "train2"}, {"eval"})
    else:
        with pytest.raises(ValueError, match="Only the independent native004 profile"):
            batch.validate_split(contract, {"train1", "train2"}, {"eval"})


@pytest.mark.parametrize("additional", [False, True])
@pytest.mark.parametrize("profile", ["NATIVE004_SELECTION", "NATIVE005_SELECTION"])
def test_independent_split_rejects_prior_injection_even_when_bank_agrees(tmp_path, additional, profile):
    import trimem_skhynix_native_dataset as dataset
    b = batch.broker
    bank_path, manifest_path = tmp_path / "bank.json", tmp_path / "manifest.json"
    b.write(bank_path, {"training_task_ids": ["train", "future"],
        "evaluation_task_ids": ["eval"], "evaluation_targets": [{"task_id": "eval"}],
        "cold_start": False, "records": [{"source": {"task_id": "future"}}]})
    b.write(manifest_path, {"selection": getattr(dataset, profile),
        "targets": [{"target_id": "train", "role": "TRAINING"}, {"target_id": "eval", "role": "EVALUATION"}],
        "prior_training_target": None if additional else {"target_id": "future"},
        "additional_prior_training_targets": [{"target_id": "future"}] if additional else []})
    contract = {"frozen_memory_bank": b.frozen_input(bank_path),
                "supplemental_manifest": b.frozen_input(manifest_path)}
    with pytest.raises(ValueError, match="forbids prior training"):
        batch.validate_split(contract, {"train", "future"}, {"eval"})


@pytest.mark.parametrize("mutation", ["training_ids", "runner_hash", "fractional_count"])
def test_modified_native005_profile_cannot_enable_no_prior_exception(tmp_path, mutation):
    import copy
    import trimem_skhynix_native_dataset as dataset
    b = batch.broker
    bank_path, manifest_path = tmp_path / "bank.json", tmp_path / "manifest.json"
    b.write(bank_path, {"training_task_ids": ["train"], "evaluation_task_ids": ["eval"],
        "evaluation_targets": [{"task_id": "eval"}], "cold_start": False, "records": []})
    selection = copy.deepcopy(dataset.NATIVE005_SELECTION)
    if mutation == "training_ids":
        selection["training_instance_ids"].reverse()
    elif mutation == "runner_hash":
        selection["required_runner_sha256"] = "f" * 64
    else:
        selection["new_training_count"] = 2.0
    b.write(manifest_path, {"selection": selection,
        "targets": [{"target_id": "train", "role": "TRAINING"}, {"target_id": "eval", "role": "EVALUATION"}],
        "prior_training_target": None, "additional_prior_training_targets": []})
    contract = {"frozen_memory_bank": b.frozen_input(bank_path),
                "supplemental_manifest": b.frozen_input(manifest_path)}
    with pytest.raises(ValueError, match="Only the independent"):
        batch.validate_split(contract, {"train"}, {"eval"})


def test_evaluation_cannot_receive_training_procedure_outside_memory(experiment):
    root, train, one, two, _ = experiment
    plan = batch.broker.read(one / "plan.json")
    plan["procedure_declaration"] = {"path": "training-procedure.json", "sha256": "d" * 64}
    batch.broker.write(one / "plan.json", plan)
    output = root / "batch.json"
    with pytest.raises(ValueError, match="training procedure instructions outside memory"):
        batch.freeze(output, [one, two], [(train, "A")])
    assert not output.exists()


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    b = batch.broker
    monkeypatch.setattr(b, "load_plan", lambda run: b.read(run / "plan.json"))
    monkeypatch.setattr(b, "workspace_for", lambda *args: SimpleNamespace(patch=lambda: ""))
    bank = tmp_path / "bank.json"
    b.write(bank, {"training_task_ids": ["train"], "evaluation_task_ids": ["eval1", "eval2"],
                   "evaluation_targets": [{"task_id": "eval1"}, {"task_id": "eval2"}],
                   "cold_start": False, "records": [{"source": {"task_id": "train"}}]})

    def make(name):
        run = tmp_path / name
        plan = {"schema": b.SCHEMA, "experiment_id": "native-batch", "public_task": {"task_id": name,
                    "repository": "sympy/sympy", "commit": "a" * 40}, "cells": dict(b.CELLS),
                "target": {"target_id": name, "repository": "sympy/sympy", "base_commit": "a" * 40},
                "limits": dict(b.LIMITS), "requested_solver_model": "gpt-6-astra",
                "frozen_memory_bank": {"path": str(bank), "sha256": b.sha(bank.read_bytes())},
                "supplemental_manifest": None, "public_python": "/env/python", "execution": "fresh",
                "l0_projection": "native", "memory_learning": "frozen", "host_isolation": "protocol",
                "source_hashes": {"implementation": "a" * 64}}
        b.write(run / "plan.json", plan)
        (run / "plan.sha256").write_text(b.sha(b.canonical(plan)))
        for cell in b.CELLS:
            b.write(run / "cells" / cell / "state.json",
                    {"status": "OPEN", "actions": 0, "started_at": None, "tail_sha256": "0" * 64})
        return run

    def result(run, cell, resolved):
        plan = b.read(run / "plan.json")
        root = run / "cells" / cell
        state = {"status": "SUBMITTED", "actions": 1, "started_at": 100, "tail_sha256": "0" * 64}
        b.append_event(root, state, {"op": "submit"}, {"ok": True, "result": {"status": "SUBMITTED"}})
        b.write(root / "state.json", state)
        patch = b"verified public patch"
        (root / "submission.diff").write_bytes(patch)
        b.write(root / "submission.json", {"plan_sha256": b.sha(b.canonical(plan)),
            "cell": cell, "arm": b.CELLS[cell], "target_id": run.name,
            "experiment_id": plan["experiment_id"], "actions": 1, "agent_completed": True,
            "patch_sha256": b.sha(patch), "patch_utf8_bytes": len(patch)})
        b.write(root / "grader-private.json", {"resolved": resolved})
        row = {"schema": b.SCHEMA, "experiment_id": plan["experiment_id"],
               "target_id": run.name, "cell": cell, "arm": b.CELLS[cell],
               "plan_sha256": b.sha(b.canonical(plan)), "official": True,
               "grader_status": "success", "resolved": resolved, "actions": 1,
               "memory_injections": 0, "memory_bytes": 0, "memory_queries": 0, "injected_memory_ids": [],
               "patch_sha256": b.sha(patch), "patch_utf8_bytes": len(patch), "agent_completed": True,
               "tool_event_tail_sha256": state["tail_sha256"], "tool_errors": 0,
               "command_count": 0, "successful_commands": 0,
               "grader_private_sha256": b.sha((root / "grader-private.json").read_bytes())}
        b.write(run / "cells" / cell / "public-result.json", row)

    train, one, two = (make(name) for name in ("train", "eval1", "eval2"))
    result(train, "A", True)
    return tmp_path, train, one, two, result


def test_complete_comparison_retains_failures_in_denominator(experiment):
    root, train, one, two, result = experiment
    plan = root / "batch.json"
    batch.freeze(plan, [one, two], [(train, "A")])
    for run in (one, two):
        for cell in batch.broker.CELLS:
            result(run, cell, cell != "A" or run == one)
    value = batch.aggregate(plan, root / "report.json")
    assert value["status"] == "COMPLETE"
    assert value["completed_cells"] == 6
    assert value["comparison"]["NO_MEMORY"]["n"] == 2
    assert value["comparison"]["NO_MEMORY"]["solve_rate"] == .5
    assert value["comparison"]["SKHYNIX"]["difference_percentage_points"] == 50


def test_partial_evaluation_does_not_publish_selected_denominator(experiment):
    root, train, one, two, result = experiment
    plan = root / "batch.json"
    batch.freeze(plan, [one, two], [(train, "A")])
    for cell in batch.broker.CELLS:
        result(one, cell, True)
    value = batch.aggregate(plan, root / "report.json")
    assert value["status"] == "INCOMPLETE"
    assert value["comparison"] is None
    assert value["fully_paired_targets"] == ["eval1"]


@pytest.mark.parametrize("change", ["started", "submission", "result", "overlap", "bank", "model", "python"])
def test_freeze_rejects_contamination_or_unequal_conditions(experiment, change):
    root, train, one, two, result = experiment
    b = batch.broker
    if change == "started":
        b.write(one / "cells/A/state.json", {"status": "OPEN", "actions": 1, "started_at": 123})
    elif change == "submission":
        b.write(one / "cells/A/submission.json", {})
    elif change == "result":
        result(one, "A", True)
    else:
        plan = b.read(two / "plan.json")
        if change == "overlap": plan["public_task"]["task_id"] = "train"
        elif change == "bank": plan["frozen_memory_bank"]["sha256"] = "b" * 64
        elif change == "python": plan["public_python"] = "/different/python"
        else: plan["requested_solver_model"] = "different"
        b.write(two / "plan.json", plan)
    with pytest.raises(ValueError):
        batch.freeze(root / "batch.json", [one, two], [(train, "A")])


@pytest.mark.parametrize("change", ["resolved", "private", "memory", "actions", "patch", "event"])
def test_aggregate_rejects_edited_public_summary_or_underlying_receipts(experiment, change):
    root, train, one, two, result = experiment
    plan = root / "batch.json"
    batch.freeze(plan, [one, two], [(train, "A")])
    result(one, "A", False)
    cell = one / "cells/A"
    b = batch.broker
    if change in ("resolved", "memory", "actions"):
        row = b.read(cell / "public-result.json")
        row[{"resolved": "resolved", "memory": "memory_injections", "actions": "actions"}[change]] = (
            True if change == "resolved" else 999)
        b.write(cell / "public-result.json", row)
    elif change == "private":
        b.write(cell / "grader-private.json", {"resolved": True})
    elif change == "patch":
        (cell / "submission.diff").write_bytes(b"changed after grading")
    else:
        (cell / "tool-events.jsonl").write_bytes(b"")
    with pytest.raises(ValueError):
        batch.aggregate(plan, root / "report.json")


@pytest.mark.parametrize("change", ["reset_state_with_old_journal", "dirty_checkout"])
def test_freeze_rejects_hidden_prior_execution(experiment, monkeypatch, change):
    root, train, one, two, result = experiment
    b = batch.broker
    if change == "dirty_checkout":
        monkeypatch.setattr(b, "workspace_for", lambda *args: SimpleNamespace(patch=lambda: "unsubmitted edits"))
    else:
        cell = one / "cells/A"
        state = b.read(cell / "state.json")
        b.append_event(cell, {**state, "actions": 1}, {"op": "info"}, {"ok": True, "result": {}})
        # The journal survives an accidentally reset OPEN/zero state.
    with pytest.raises(ValueError):
        batch.freeze(root / "batch.json", [one, two], [(train, "A")])


@pytest.mark.parametrize("change", ["training_ids", "evaluation_ids", "declared_targets", "record_sources", "cold"])
def test_freeze_requires_actual_bank_split_to_match_batch(experiment, change):
    root, train, one, two, _ = experiment
    b = batch.broker
    bank_path = root / "bank.json"
    bank = b.read(bank_path)
    if change == "training_ids": bank["training_task_ids"] = ["other-training"]
    elif change == "evaluation_ids": bank["evaluation_task_ids"] = ["eval1"]
    elif change == "declared_targets": bank["evaluation_targets"][0]["task_id"] = "unknown"
    elif change == "record_sources": bank["records"][0]["source"]["task_id"] = "eval1"
    else: bank["cold_start"] = True
    b.write(bank_path, bank)
    for run in (one, two):
        plan = b.read(run / "plan.json")
        plan["frozen_memory_bank"]["sha256"] = b.sha(bank_path.read_bytes())
        b.write(run / "plan.json", plan)
    with pytest.raises(ValueError):
        batch.freeze(root / "batch.json", [one, two], [(train, "A")])


def test_training_receipts_remain_frozen_during_aggregation(experiment):
    root, train, one, two, _ = experiment
    path = root / "batch.json"
    batch.freeze(path, [one, two], [(train, "A")])
    receipt = train / "cells/A/public-result.json"
    value = batch.broker.read(receipt)
    value["resolved"] = False
    batch.broker.write(receipt, value)
    with pytest.raises(ValueError, match="Training evidence changed"):
        batch.aggregate(path, root / "report.json")


def test_changed_batch_or_run_plan_is_rejected(experiment):
    root, train, one, two, _ = experiment
    path = root / "batch.json"
    batch.freeze(path, [one, two], [(train, "A")])
    plan = batch.broker.read(one / "plan.json")
    plan["limits"]["repository_actions"] += 1
    batch.broker.write(one / "plan.json", plan)
    with pytest.raises(ValueError, match="changed after batch freeze"):
        batch.aggregate(path, root / "report.json")
    value = batch.broker.read(path)
    value["planned_cells"] = 1
    batch.broker.write(path, value)
    with pytest.raises(ValueError, match="batch plan changed"):
        batch.aggregate(path, root / "report.json")
