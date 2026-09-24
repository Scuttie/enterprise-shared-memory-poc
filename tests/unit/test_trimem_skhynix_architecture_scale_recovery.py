"""Retained-evidence recovery tests; no native, grader, or Docker invocation."""
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import trimem_skhynix_architecture_scale_pipeline as scale


def retain(path, value):
    return scale.core.retain(path, value)


def event(root, stage, *, task=None, job=None, details=None):
    rows = scale.core.read_event_chain(root)
    body = {"sequence": len(rows) + 1, "previous_sha256": rows[-1]["sha256"] if rows else "0" * 64,
            "stage": stage, "task_id": task, "job": job, "details": details or {}}
    body["sha256"] = scale.core.digest(scale.canonical_bytes(body))
    return retain(root / "events" / f"{len(rows) + 1:08d}.json", body)


@pytest.fixture
def recovery(tmp_path):
    task = "swebench--django__django-16686"
    ids = [f"task-{n:03d}" for n in range(240)]
    ids[45] = task
    datasets = {n: retain(tmp_path / f"dataset-{n}.json", {"targets": [
        {"target_id": item, "role": "TRAINING"} for item in ids[:n]]}) for n in scale.SIZES}
    prior_config = retain(tmp_path / "original.json", {"run_root": str(tmp_path / "original")})
    global_rows = []
    for item in ids[:21]:
        cell = retain(tmp_path / "original/cells/TRAINING" / item / "PDF_MEMORY/cell.json",
                      {"task_public": {"task_id": item}})
        global_rows.append({"task_id": item, "cell_reference": cell})
    original_tail = event(tmp_path / "pilot", "BLOCKED")
    global_adoption = retain(tmp_path / "adoption-global.json", {"rows": global_rows,
        "predecessor_configrefs": [prior_config], "source_count": 21, "official_complete": 19,
        "original_pipeline_event_tail_reference": original_tail})
    stages = []
    for n in scale.SIZES:
        authority = retain(tmp_path / f"authority-{n}.json", {"purpose": "TRAINING_REMAINDER_24" if n == 24 else "TRAINING_INCREMENT",
            "dataset_reference": datasets[n], "cumulative_training_count": n,
            "source_adoption_reference": global_adoption if n == 24 else None,
            "task_ids": ids[21:24] if n == 24 else ids[24 if n == 120 else 120:n]})
        config = {"dataset_manifest": datasets[n], "run_root": str(tmp_path / f"run-{n}"),
            "native_control_root": str(tmp_path / f"native-{n}"), "scale_authority_reference": authority,
            "source_root": "/unchanged-frozen-source", "source_sha256": {"code": "unchanged"},
            "model": "gpt-6-astra", "reasoning_effort": "high", "authentication": "CHATGPT",
            "phase": "TRAINING_RUNTIME", "limits": {"task_requests": 120, "task_seconds": 1200},
            "training_owner_by_instance": {"django__django-16686": 2}, "org_id": "same"}
        stages.append({"size": n, "execution_reference": retain(tmp_path / f"execution-{n}.json", config)})
    old_execution = stages[1]["execution_reference"]
    old = scale.core.check(old_execution)
    for item in ids[21:24]:
        folder = tmp_path / "run-24/cells/TRAINING" / item / "PDF_MEMORY"
        retain(folder / "cell.json", {"task_public": {"task_id": item}, "broker_root": str(folder / "broker")})
        retain(folder / "broker/state.json", {"status": "SUBMITTED"})
        retain(folder / "execution-audit.json", {"passed": True})
    adopted = []
    for item in ids[24:45]:
        cell = retain(tmp_path / "run-120/cells/TRAINING" / item / "PDF_MEMORY/cell.json",
                      {"task_public": {"task_id": item}})
        adopted.append({"task_id": item, "cell_reference": cell})
        event(tmp_path / "run-120/cohort", "CELL_COMPLETE", task=item)
    stage_adoption = retain(tmp_path / "adoption-stage.json", {"rows": adopted,
        "predecessor_configrefs": [old_execution], "source_count": 21, "official_complete": 21})
    old_root = tmp_path / "old-pipeline"
    learning_root = old_root / "learning-24"
    enrollment = retain(learning_root / "learning-enrollment.json", {"dataset_reference": datasets[24]})
    catalog = retain(learning_root / "catalog.json", {"skills": []})
    plan = retain(tmp_path / "reflection-old/bank-24/reflection-plan.json", {"jobs": [], "binding": {"enrollment_reference": enrollment}})
    bank = retain(old_root / "bank-24/bank-status.json", {"size": 24, "status": "NOT_READY",
        "source_attempts": 24, "bank_reference": None, "reason": "NO_VERIFIED_GATE_B_SKILL",
        "catalog_reference": catalog, "reflection_plan_reference": plan})
    bank_event = event(old_root, "BANK_NOT_READY", job="bank-24", details={"reference": bank})
    pipeline_tail = event(old_root, "PIPELINE_BLOCKED", job="bank-120")
    helper = retain(tmp_path / "helper.json", {})
    old_config = {"schema": scale.SCHEMA, "selection_policy": scale.SELECTION_POLICY, "outcome_retries": False,
        "pipeline_root": str(old_root), "progress_root": str(tmp_path / "progress"),
        "reflection_native_root": str(tmp_path / "reflection-old"), "evaluation_native_root": str(tmp_path / "eval-old"),
        "training_stages": stages, "training_experiment_reference": stages[0]["execution_reference"],
        "source_adoption_reference": global_adoption, "protocol_reference": helper,
        "pipeline_source_reference": helper, "reflection_source_reference": helper,
        "helper_references": {"same": helper}, "reflection_max_bytes": 190000}
    old_pipeline = retain(tmp_path / "pipeline-old.json", old_config)
    retain(old_root / "pipeline-binding.json", {"schema": scale.SCHEMA, "configuration_reference": old_pipeline})
    retain(tmp_path / "run-120/cohort/cohort.json", {"experiment_reference": old_execution})
    folder = tmp_path / "run-120/cells/TRAINING" / task / "PDF_MEMORY"
    cell = retain(folder / "cell.json", {"task_public": {"task_id": task}, "phase": "TRAINING", "arm": "PDF_MEMORY",
        "target": {"instance_id": "django__django-16686"}, "experiment_config": old_execution["path"], "bank_reference": None})
    (folder / "cell.sha256").write_text(scale.core.digest(scale.canonical_bytes(scale.core.check(cell))) + '\n')
    event(tmp_path / "run-120/cohort", "PREPARED", task=task, details={"cell_reference": cell})
    cohort_tail = event(tmp_path / "run-120/cohort", "INFRA_ERROR", task=task)
    patch_path = folder / "broker/submission.diff"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(b"retained original partial patch\n")
    patch = scale.core.ref(patch_path)
    config_sha = scale.core.digest(scale.canonical_bytes(old))
    submission = retain(folder / "broker/submission.json", {"task_id": task, "configuration_sha256": config_sha,
        "reason": "NATIVE_WORKER_INFRASTRUCTURE_FAILURE", "agent_completed": False, "actions": 21, "patch_sha256": patch["sha256"]})
    audit = retain(folder / "execution-audit.json", {"passed": False, "errors": ["Trusted launcher failure persisted"],
        "task_id": task, "configuration_sha256": config_sha, "patch_sha256": patch["sha256"]})
    native = tmp_path / "native-120/TRAINING/django__django-16686/PDF_MEMORY/worker-003/output"
    native.mkdir(parents=True)
    event_path = native / "events.jsonl"
    event_path.write_text('\n'.join(json.dumps({"type": kind, "message": "You've hit your usage limit."}) for kind in ("error", "turn.failed")) + '\n')
    native_events = scale.core.ref(event_path)
    completion = retain(native / "completion.json", {"exit_code": 1, "admitted": True, "timed_out": False,
        "errors": [], "transport_errors": [], "outside_broker_tool_events": [], "events_sha256": native_events["sha256"]})
    failure = retain(folder / "native-execution-failure.json", {"worker_id": "pdf_memory-django__django-16686-3",
        "launcher_returncode": 1, "completion_sha256": completion["sha256"]})
    new_authority = retain(tmp_path / "authority-new.json", {"purpose": "TRAINING_INCREMENT", "cumulative_training_count": 120,
        "dataset_reference": datasets[120], "source_adoption_reference": stage_adoption, "task_ids": ids[45:120]})
    new_execution = retain(tmp_path / "execution-new.json", {**old, "run_root": str(tmp_path / "run-new"),
        "native_control_root": str(tmp_path / "native-new"), "scale_authority_reference": new_authority})
    inheritance = retain(tmp_path / "inheritance.json", {"schema": scale.INHERITANCE_SCHEMA,
        "predecessor_pipeline_reference": old_pipeline, "event_reference": bank_event,
        "result_reference": bank, "learning_enrollment_reference": enrollment})
    receipt = {"schema": scale.REPLACEMENT_SCHEMA, "operation": "AUTHORIZE_ONE_QUOTA_REPLACEMENT", "task_id": task,
        "old_execution_reference": old_execution, "new_execution_reference": new_execution,
        "old_cell_reference": cell, "audit_reference": audit, "native_failure_reference": failure,
        "submission_reference": submission, "submission_patch_reference": patch,
        "native_completion_reference": completion, "native_events_reference": native_events,
        "predecessor_pipeline_reference": old_pipeline, "predecessor_pipeline_event_tail_reference": pipeline_tail,
        "predecessor_cohort_event_tail_reference": cohort_tail, "historical_actions": 21,
        "fresh_task_requests": 120, "fresh_task_seconds": 1200, "replacement_limit": 1, "reason": "CODEX_USAGE_LIMIT",
        "original_attempt_excluded_from_memory": True, "official_outcome_retries": False,
        "protocol_amendment": "ONE_NATIVE_INFRASTRUCTURE_REPLACEMENT_WITH_FRESH_BUDGET", "model_calls": 0, "official_grader_runs": 0}
    config = {**old_config, "pipeline_root": str(tmp_path / "new-pipeline"),
        "supersedes_configuration_reference": old_pipeline,
        "infrastructure_replacement_reference": retain(tmp_path / "replacement.json", receipt),
        "training_stages": [{**stages[0], "learning_root": str(learning_root), "inherited_bank_reference": inheritance},
                            {"size": 120, "execution_reference": new_execution}, stages[2]]}
    return SimpleNamespace(root=tmp_path, config=config, receipt=receipt, task=task, ids=ids, folder=folder,
        old_config=old_config, new_execution=new_execution, old_execution=old_execution, adoption=stage_adoption)


def pipeline(recovery):
    p = scale.ScalePipeline.__new__(scale.ScalePipeline)
    p.config = recovery.config
    p.root = Path(p.config["pipeline_root"])
    p.reference = retain(p.root / "config.json", p.config)
    p.adoption = scale.core.check(p.config["source_adoption_reference"])
    p.base_reflection_root = p.config["reflection_native_root"]
    p.operations = SimpleNamespace()
    p.clock = lambda: 1
    p.progress = lambda: None
    return p


def replace_receipt(recovery, **changes):
    recovery.config["infrastructure_replacement_reference"] = retain(recovery.root / "changed-replacement.json", {**recovery.receipt, **changes})


def test_exact_quota_recovery_validates_retained_originals_and_fresh_protocol(recovery):
    seen = []
    execution = SimpleNamespace(execution_enrollment=lambda config, dataset: seen.append(config))
    assert scale.validate_infrastructure_replacement(recovery.config, execution=execution) == recovery.receipt
    assert seen == [scale.core.check(recovery.new_execution)]
    scale.validate_config(recovery.config)


@pytest.mark.parametrize("field,value", [("task_id", "other-task"), ("replacement_limit", 2),
    ("fresh_task_requests", 240), ("historical_actions", 20), ("reason", "SOLVER_FAILURE"),
    ("original_attempt_excluded_from_memory", False), ("official_outcome_retries", True),
    ("protocol_amendment", "UNCHANGED_NO_RETRY_PROTOCOL")])
def test_recovery_rejects_scope_budget_or_protocol_mutation(recovery, field, value):
    replace_receipt(recovery, **{field: value})
    with pytest.raises(scale.core.PipelineError):
        scale.validate_infrastructure_replacement(recovery.config)


@pytest.mark.parametrize("name", ["public-result.json", "grader-pending.json"])
def test_quota_replacement_never_retries_an_official_or_active_grade(recovery, name):
    retain(recovery.folder / name, {"existing": True})
    with pytest.raises(scale.core.PipelineError, match="no official result"):
        scale.validate_infrastructure_replacement(recovery.config)


def test_changed_native_event_bytes_fail_before_replacement(recovery):
    Path(recovery.receipt["native_events_reference"]["path"]).write_text('{}\n')
    with pytest.raises(scale.core.PipelineError):
        scale.validate_infrastructure_replacement(recovery.config)


def test_newly_advanced_predecessor_cohort_is_not_adoptable(recovery):
    event(recovery.root / "run-120/cohort", "PREPARE_STARTED", task="later")
    with pytest.raises(scale.core.PipelineError, match="advanced"):
        scale.validate_infrastructure_replacement(recovery.config)


def test_cloned_predecessor_cannot_borrow_actual_blocked_journal(recovery):
    cloned = retain(recovery.root / "cloned-pipeline.json", {**recovery.old_config, "reflection_max_bytes": 200000})
    replace_receipt(recovery, predecessor_pipeline_reference=cloned)
    recovery.config.update(supersedes_configuration_reference=cloned, reflection_max_bytes=200000)
    with pytest.raises(scale.core.PipelineError, match="exact original configuration"):
        scale.validate_infrastructure_replacement(recovery.config)


def test_stage_specific_adoption_preserves24_and_reuses45_without_failed_source(recovery):
    p = pipeline(recovery)
    first, cumulative = p._source_cells(24), p._source_cells(120)
    assert len(first) == 24 and len(cumulative) == 45
    assert {scale.core.check(ref)["task_public"]["task_id"] for ref in cumulative} == set(recovery.ids[:45])
    assert recovery.receipt["old_cell_reference"] not in cumulative


def test_duplicate_adopted_cell_in_new_root_rejected(recovery):
    folder = recovery.root / "run-new/cells/TRAINING" / recovery.ids[24] / "PDF_MEMORY"
    retain(folder / "cell.json", {"task_public": {"task_id": recovery.ids[24]}, "broker_root": str(folder / "broker")})
    retain(folder / "broker/state.json", {"status": "SUBMITTED"})
    retain(folder / "execution-audit.json", {"passed": True})
    with pytest.raises(scale.core.PipelineError, match="repeat"):
        pipeline(recovery)._source_cells(120)


def test_learning_enrolls_old_owners_and_new_scope_but_captures_only45(recovery):
    p = pipeline(recovery)
    calls, captured = [], []
    learning = SimpleNamespace(initialize_learning=lambda root, **kw: calls.append(kw),
                               capture_cell=lambda root, path: captured.append(path))
    p.operations.modules = {"learning": learning}
    p._learning(p.config["training_stages"][1])
    refs = calls[0]["execution_references"]
    assert recovery.old_execution in refs and recovery.new_execution in refs
    assert refs.index(recovery.old_execution) > refs.index(p.config["training_stages"][0]["execution_reference"])
    assert len({ref["path"] for ref in refs}) == len(refs)
    assert len(captured) == 45 and recovery.receipt["old_cell_reference"]["path"] not in captured


def test_inherited_not_ready_reuses_original_decision_without_learning_or_publisher(recovery):
    p = pipeline(recovery)
    p._learning = lambda *args: pytest.fail("original source bank must not be recaptured")
    p._runner = lambda *args: pytest.fail("original cohort must not rerun")
    stage = p.config["training_stages"][0]
    before = Path(scale.core.check(stage["inherited_bank_reference"])["result_reference"]["path"]).read_bytes()
    result = p._bank(stage)
    assert result["status"] == "NOT_READY" and result["source_attempts"] == 24
    assert p.latest("BANK_NOT_READY", "bank-24")["details"]["reflection_repeated"] is False
    assert p._bank(stage) == result
    assert before == Path(scale.core.check(stage["inherited_bank_reference"])["result_reference"]["path"]).read_bytes()


def test_inheritance_rejects_catalog_changes(recovery):
    receipt = scale.core.check(recovery.config["training_stages"][0]["inherited_bank_reference"])
    result = scale.core.check(receipt["result_reference"])
    Path(result["catalog_reference"]["path"]).write_text('{}\n')
    with pytest.raises(scale.core.PipelineError):
        scale.validate_infrastructure_replacement(recovery.config)


def test_recovery_holds_old_pipeline_and_failed_cohort_locks(recovery, monkeypatch):
    from contextlib import contextmanager
    held = set()

    @contextmanager
    def lock(path):
        held.add(path)
        try:
            yield
        finally:
            held.remove(path)

    p = pipeline(recovery)
    p.operations.modules = {"cohort": SimpleNamespace(execution=SimpleNamespace(execution_enrollment=lambda *args: None))}
    monkeypatch.setattr(scale, "locked", lock)
    with p._controller_locks():
        assert held == {recovery.root / "pilot/run.lock", recovery.root / "old-pipeline/run.lock",
                        recovery.root / "run-120/cohort/run.lock", p.root / "run.lock"}
    assert not held
