"""Source continuation must preserve evidence and cannot authorize a retry."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_skhynix_architecture_scale_pipeline as scale
from test_trimem_skhynix_architecture_scale_recovery import event, recovery, retain


@pytest.fixture
def continuation(tmp_path, monkeypatch):
    task = "swebench--mwaskom__seaborn-2766"
    completed = [f"completed-{n}" for n in range(14)]
    remaining = [f"remaining-{n}" for n in range(60)]
    oldroot, newroot = tmp_path / "source-old", tmp_path / "source-new"
    for root in (oldroot, newroot):
        retain(root / "helper.json", {"same": True})
        for name in ("cohort", "cleanup"):
            retain(root / ("scripts/trimem_skhynix_architecture_" + name + ".py"), {"original": name})
    manifest = {"helper.json": scale.core.ref(oldroot / "helper.json")["sha256"],
                "scripts/trimem_skhynix_architecture_run.py": "old"}
    manifest.update({"scripts/trimem_skhynix_architecture_" + name + ".py":
        scale.core.ref(oldroot / ("scripts/trimem_skhynix_architecture_" + name + ".py"))["sha256"] for name in ("cohort", "cleanup")})
    dataset = retain(tmp_path / "dataset.json", {})
    original = retain(tmp_path / "original.json", {})
    prefix = [{"task_id": f"prior-{n}", "cell_reference": {"path": f"/prior/{n}", "sha256": str(n)}} for n in range(21)]
    prior_adoption = retain(tmp_path / "prior-adoption.json", {"rows": prefix, "predecessor_configrefs": [original]})
    oldauth = retain(tmp_path / "old-authority.json", {"source_adoption_reference": prior_adoption,
        "task_ids": completed + [task] + remaining})
    old = {"run_root": str(tmp_path / "run-old"), "native_control_root": str(tmp_path / "native-old"),
        "source_root": str(oldroot), "source_sha256": manifest, "scale_authority_reference": oldauth,
        "dataset_manifest": dataset, "limits": {"task_requests": 120, "task_seconds": 1200}, "model": "gpt-6-astra", "phase": "TRAINING_RUNTIME"}
    oldexec = retain(tmp_path / "old-exec.json", old)
    stage24 = {"size": 24, "execution_reference": original, "inherited_bank_reference": original}
    old240 = retain(tmp_path / "old240.json", {**old, "run_root": str(tmp_path / "run240")})
    oldconfig = {"pipeline_root": str(tmp_path / "pipeline-old"),
        "training_stages": [stage24, {"size": 120, "execution_reference": oldexec}, {"size": 240, "execution_reference": old240}],
        "protocol_reference": original, "source_adoption_reference": original, "selection_policy": scale.SELECTION_POLICY,
        "reflection_max_bytes": 190000, "helper_references": {"helper": scale.core.ref(oldroot / "helper.json")},
        "reflection_source_reference": scale.core.ref(oldroot / "helper.json"),
        "infrastructure_replacement_reference": original}
    predecessor = retain(tmp_path / "old-pipeline.json", oldconfig)
    retain(Path(oldconfig["pipeline_root"]) / "pipeline-binding.json", {"schema": scale.SCHEMA, "configuration_reference": predecessor})
    cohort = Path(old["run_root"]) / "cohort"
    retain(cohort / "cohort.json", {"experiment_reference": oldexec})
    newrows = []
    for item in completed:
        folder = Path(old["run_root"]) / "cells/TRAINING" / item / "PDF_MEMORY"
        cell = retain(folder / "cell.json", {"task_public": {"task_id": item}})
        newrows.append({"task_id": item, "cell_reference": cell, "classification": "OFFICIAL_COMPLETE"})
        event(cohort, "CELL_COMPLETE", task=item)
    folder = Path(old["run_root"]) / "cells/TRAINING" / task / "PDF_MEMORY"
    cell = retain(folder / "cell.json", {"task_public": {"task_id": task}, "phase": "TRAINING", "arm": "PDF_MEMORY",
        "target": {"instance_id": "mwaskom__seaborn-2766"}, "bank_reference": None, "experiment_config": oldexec["path"]})
    (folder / "cell.sha256").write_text(scale.core.digest(scale.canonical_bytes(scale.core.check(cell))))
    event(cohort, "PREPARED", task=task, details={"cell_reference": cell})
    tail = event(cohort, "INFRA_ERROR", task=task, details={"error_type": "GraderInvocationFailure"})
    ptail = event(Path(oldconfig["pipeline_root"]), "PIPELINE_BLOCKED")
    patch = retain(folder / "broker/submission.diff", {"public_patch": True})
    binding = {"task_id": task, "configuration_sha256": scale.core.digest(scale.canonical_bytes(old)), "patch_sha256": patch["sha256"]}
    audit = retain(folder / "execution-audit.json", {**binding, "passed": True, "errors": []})
    submission = retain(folder / "broker/submission.json", {**binding, "agent_completed": True, "reason": "WORKER_SUBMITTED"})
    pending = retain(folder / "grader-pending.json", {"patch_sha256": patch["sha256"]})
    summarydata = {"total_instances": 1, "submitted_instances": 1, "completed_instances": 1,
        "resolved_instances": 0, "unresolved_instances": 1, "ambiguous_failure_instances": 1, "infra_failure_instances": 0,
        "empty_patch_instances": 0, "error_instances": 0, "unstopped_instances": 0,
        "failure_reasons": {"mwaskom__seaborn-2766": "missing_module"}}
    summary = retain(Path(old["run_root"]) / "environment/TRAINING/cells/PDF_MEMORY" / task / "official-grader" / task / "report/summary.json", summarydata)
    newrows.append({"task_id": task, "cell_reference": cell, "classification": "AMBIGUOUS_MISSING_MODULE",
                    "official_result_reference": None, "official_summary_reference": summary})
    adoptiondata = {"rows": prefix + newrows, "predecessor_configrefs": [original, oldexec], "source_count": 36, "official_complete": 35}
    adoption = retain(tmp_path / "adoption.json", adoptiondata)
    authoritydata = {"source_adoption_reference": adoption, "purpose": "TRAINING_INCREMENT", "cumulative_training_count": 120, "task_ids": remaining}
    authority = retain(tmp_path / "authority.json", authoritydata)
    new = {**old, "run_root": str(tmp_path / "run-new"), "native_control_root": str(tmp_path / "native-new"),
           "source_root": str(newroot), "source_sha256": {**manifest, "scripts/trimem_skhynix_architecture_run.py": "new"}, "scale_authority_reference": authority}
    newexec = retain(tmp_path / "new-exec.json", new)
    new240 = retain(tmp_path / "new240.json", {**scale.core.check(old240), **{key: new[key] for key in ("source_root", "source_sha256")}})
    freeze = retain(tmp_path / "freeze.json", {"schema": "skhynix/grading-continuation-runtime-freeze/1.0",
        "previous_execution_reference": oldexec, "old_source_root": old["source_root"], "old_source_sha256": manifest,
        "source_root": new["source_root"], "source_sha256": new["source_sha256"],
        "changed_paths": ["scripts/trimem_skhynix_architecture_run.py"], "model_calls": 0, "official_grader_runs": 0})
    receipt = {"schema": scale.CONTINUATION_SCHEMA, "operation": "CONTINUE_AFTER_UNDETERMINED_SOURCE_GRADE",
        "task_id": task, "official_outcome": "UNDETERMINED", "resolved": None, "classification": "AMBIGUOUS_MISSING_MODULE",
        "source_only": True, "native_retries": False, "official_grader_retries": False, "model_calls": 0, "official_grader_runs": 0,
        "predecessor_pipeline_reference": predecessor, "predecessor_pipeline_event_tail_reference": ptail,
        "predecessor_cohort_event_tail_reference": tail, "old_execution_reference": oldexec, "new_execution_reference": newexec,
        "source_adoption_reference": adoption, "old_cell_reference": cell, "audit_reference": audit,
        "submission_reference": submission, "submission_patch_reference": patch, "grader_pending_reference": pending,
        "official_summary_reference": summary, "runtime_change_reference": freeze}
    config = {**oldconfig, "pipeline_root": str(tmp_path / "pipeline-new"), "supersedes_configuration_reference": predecessor,
        "training_experiment_reference": newexec, "grading_continuation_reference": retain(tmp_path / "continuation.json", receipt),
        "training_stages": [stage24, {"size": 120, "execution_reference": newexec}, {"size": 240, "execution_reference": new240}],
        "helper_references": {"helper": scale.core.ref(newroot / "helper.json")}, "reflection_source_reference": scale.core.ref(newroot / "helper.json")}
    monkeypatch.setattr(scale, "validate_infrastructure_replacement", lambda config, **kw: None)
    monkeypatch.setattr(scale, "_inherited_bank", lambda config, stage: None)
    return SimpleNamespace(root=tmp_path, config=config, receipt=receipt, folder=folder, cohort=cohort,
        adoptiondata=adoptiondata, authoritydata=authoritydata, new=new, old=old, summarydata=summarydata)


def update_receipt(case, **changes):
    case.receipt.update(changes)
    path = case.root / ("receipt-" + str(len(list(case.root.glob("receipt-*")))) + ".json")
    case.config["grading_continuation_reference"] = retain(path, case.receipt)


def test_continuation_preserves_60_original_sources_and_exact_60_remaining(continuation):
    seen = []
    execution = SimpleNamespace(execution_enrollment=lambda config, dataset: seen.append(config))
    assert scale.validate_grading_continuation(continuation.config, execution=execution) == continuation.receipt
    assert seen == [continuation.new]


@pytest.mark.parametrize("field,value", [("task_id", "another-task"), ("resolved", False),
    ("source_only", False), ("native_retries", True), ("official_grader_retries", True),
    ("official_grader_runs", 1), ("classification", "OFFICIAL_COMPLETE")])
def test_continuation_never_promotes_unknown_grade_or_authorizes_retry(continuation, field, value):
    update_receipt(continuation, **{field: value})
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(continuation.config)


def test_continuation_blocks_if_grading_journal_advances(continuation):
    event(continuation.cohort, "GRADED", task=continuation.receipt["task_id"])
    with pytest.raises(scale.core.PipelineError, match="advanced"):
        scale.validate_grading_continuation(continuation.config)


def test_continuation_cannot_adopt_an_existing_official_result(continuation):
    retain(continuation.folder / "public-result.json", {"resolved": False})
    with pytest.raises(scale.core.PipelineError, match="undetermined"):
        scale.validate_grading_continuation(continuation.config)


def test_continuation_rejects_changed_retained_patch(continuation):
    Path(continuation.receipt["submission_patch_reference"]["path"]).write_text("changed")
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(continuation.config)


@pytest.mark.parametrize("mutation", ["count", "cause", "resolved"])
def test_continuation_requires_exact_ambiguous_aggregate(continuation, mutation):
    data = dict(continuation.summarydata)
    data.update({"count": {"ambiguous_failure_instances": 0}, "cause": {"failure_reasons": {"mwaskom__seaborn-2766": "timeout"}},
                 "resolved": {"resolved_instances": 1}}[mutation])
    ref = retain(Path(continuation.receipt["official_summary_reference"]["path"]).with_name("changed.json"), data)
    update_receipt(continuation, official_summary_reference=ref)
    with pytest.raises(scale.core.PipelineError, match="aggregate"):
        scale.validate_grading_continuation(continuation.config)


@pytest.mark.parametrize("mutation", ["prefix", "suffix", "duplicate", "owner", "classification"])
def test_continuation_rejects_source_selection_or_ownership_changes(continuation, mutation):
    import copy
    data, authority = copy.deepcopy(continuation.adoptiondata), copy.deepcopy(continuation.authoritydata)
    if mutation == "prefix":
        data["rows"][0]["task_id"] = "replace-prior"
    elif mutation == "suffix":
        authority["task_ids"] = list(reversed(authority["task_ids"]))
    elif mutation == "duplicate":
        data["rows"][22] = data["rows"][21]
    elif mutation == "owner":
        data["rows"][21]["cell_reference"] = retain(continuation.root / "clone.json", {})
    else:
        data["rows"][-1]["classification"] = "OFFICIAL_COMPLETE"
    adoption = retain(continuation.root / "changed-adoption.json", data)
    authority["source_adoption_reference"] = adoption
    new = {**continuation.new, "scale_authority_reference": retain(continuation.root / "changed-authority.json", authority)}
    execution = retain(continuation.root / "changed-execution.json", new)
    continuation.config["training_stages"][1]["execution_reference"] = execution
    continuation.config["training_experiment_reference"] = execution
    update_receipt(continuation, new_execution_reference=execution, source_adoption_reference=adoption)
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(continuation.config)


def test_historical_quota_authority_is_validated_against_its_original_config(recovery):
    prior = retain(recovery.root / "prior-v4.json", recovery.config)
    continuation = retain(recovery.root / "continuation-history.json", {"predecessor_pipeline_reference": prior})
    config = {**recovery.config, "grading_continuation_reference": continuation,
              "supersedes_configuration_reference": prior, "pipeline_root": str(recovery.root / "new-v5")}
    assert scale.validate_infrastructure_replacement(config) == recovery.receipt
    config["infrastructure_replacement_reference"] = retain(recovery.root / "forged-quota.json", {})
    with pytest.raises(scale.core.PipelineError, match="historical"):
        scale.validate_infrastructure_replacement(config)


@pytest.mark.parametrize("corrupt", [False, True])
def test_reuse_captured_sources_checks_each_bound_receipt_without_reopening_all_executions(tmp_path, corrupt):
    p = scale.ScalePipeline.__new__(scale.ScalePipeline)
    p.config = {"grading_continuation_reference": {"path": "/authority"}}
    p.learning_root = tmp_path
    first, second = [retain(tmp_path / (name + ".json"), {}) for name in ("first", "second")]
    checked, captured, sessions = [], [], []
    retained = retain(tmp_path / "capture.json", {})
    receipt = {"cell_path": first["path"], "source_references": {"cell.json": second if corrupt else first}, "status": "CAPTURED"}

    @contextmanager
    def session(root, *, mutable):
        assert mutable is False
        sessions.append(root)
        yield root, {}, {"cells": {first["path"]: retained}}, []

    learning = SimpleNamespace(_session=session, memory=SimpleNamespace(_hash=lambda value: value["cell_path"], _path=Path),
        _checked_cell_receipt=lambda reference: (checked.append(reference), receipt)[1],
        capture_cell=lambda root, path: captured.append(path))
    p.operations = SimpleNamespace(modules={"learning": learning})
    if corrupt:
        with pytest.raises(scale.core.PipelineError, match="exact source"):
            p._capture_sources([first, second])
        assert not captured
    else:
        p._capture_sources([first, second])
        assert captured == [second["path"]]
    assert sessions == [tmp_path] and checked == [retained]


def add_loader_preflight(case):
    loader = retain(case.root / "loader-preflight.json", {"status": "PASS"})
    case.new = {**case.new, "loader_preflight_path": loader["path"], "loader_preflight_sha256": loader["sha256"]}
    newexec = retain(case.root / "execution-with-loader.json", case.new)
    old240 = scale.core.check(case.config["training_stages"][2]["execution_reference"])
    new240 = retain(case.root / "240-with-loader.json", {**old240,
        "loader_preflight_path": loader["path"], "loader_preflight_sha256": loader["sha256"]})
    case.config["training_stages"][1]["execution_reference"] = newexec
    case.config["training_stages"][2]["execution_reference"] = new240
    case.config["training_experiment_reference"] = newexec
    update_receipt(case, new_execution_reference=newexec, loader_preflight_reference=loader)
    return loader


def add_abandoned_preparation(case, *, stages=("PREPARE_STARTED", "INFRA_ERROR"), task="remaining-0", error=None, error_type="BenchmarkProcessFailure"):
    import copy
    prior = copy.deepcopy(case.config)
    prior["pipeline_root"] = str(case.root / "abandoned-pipeline")
    execution = {**case.new, "run_root": str(case.root / "abandoned-run"),
                 "native_control_root": str(case.root / "abandoned-native")}
    execution_ref = retain(case.root / "abandoned-execution.json", execution)
    prior["training_stages"][1]["execution_reference"] = execution_ref
    prior_ref = retain(case.root / "abandoned-pipeline.json", prior)
    retain(Path(prior["pipeline_root"]) / "pipeline-binding.json", {"schema": scale.SCHEMA, "configuration_reference": prior_ref})
    cohort = Path(execution["run_root"]) / "cohort"
    retain(cohort / "cohort.json", {"experiment_reference": execution_ref})
    error = error or "official harness loader preflight current exact loader/environment identity differs"
    for stage in stages:
        tail = event(cohort, stage, task=task, details={"error": error, "error_type": error_type} if stage == "INFRA_ERROR" else {})
    ptail = event(Path(prior["pipeline_root"]), "PIPELINE_BLOCKED")
    update_receipt(case, abandoned_preparation_pipeline_reference=prior_ref,
        abandoned_preparation_pipeline_event_tail_reference=ptail, abandoned_preparation_cohort_event_tail_reference=tail)
    return prior, execution, cohort


def test_fresh_loader_reference_binds_both_future_stages_and_invokes_exact_loader_checker(continuation, monkeypatch):
    import sys
    loader = add_loader_preflight(continuation)
    checked, enrolled = [], []
    monkeypatch.setitem(sys.modules, "trimem_benchmark_run", SimpleNamespace(
        load_official_harness_loader_preflight=lambda path: checked.append(path)))
    execution = SimpleNamespace(execution_enrollment=lambda config, dataset: enrolled.append(config))
    scale.validate_grading_continuation(continuation.config, execution=execution)
    assert checked == [Path(loader["path"])]
    assert enrolled == [continuation.new]


def test_exact_loader_checker_failure_blocks_continuation(continuation, monkeypatch):
    import sys
    add_loader_preflight(continuation)
    def reject(path):
        raise ValueError("actual loader environment differs")
    monkeypatch.setitem(sys.modules, "trimem_benchmark_run", SimpleNamespace(load_official_harness_loader_preflight=reject))
    with pytest.raises(ValueError, match="actual loader"):
        scale.validate_grading_continuation(continuation.config, execution=SimpleNamespace(
            execution_enrollment=lambda *_: pytest.fail("execution must wait for exact loader verification")))


@pytest.mark.parametrize("index,field", [(1, "loader_preflight_path"), (1, "loader_preflight_sha256"),
                                       (2, "loader_preflight_path"), (2, "loader_preflight_sha256")])
def test_loader_preflight_cannot_differ_in_either_future_stage(continuation, index, field):
    add_loader_preflight(continuation)
    stage = continuation.config["training_stages"][index]
    changed = {**scale.core.check(stage["execution_reference"]), field: "different"}
    stage["execution_reference"] = retain(continuation.root / "wrong-loader-stage.json", changed)
    if index == 1:
        continuation.config["training_experiment_reference"] = stage["execution_reference"]
        update_receipt(continuation, new_execution_reference=stage["execution_reference"])
    with pytest.raises(scale.core.PipelineError, match="loader preflight differs"):
        scale.validate_grading_continuation(continuation.config)


def test_loader_changes_require_explicit_reference(continuation):
    add_loader_preflight(continuation)
    continuation.receipt.pop("loader_preflight_reference")
    update_receipt(continuation)
    with pytest.raises(scale.core.PipelineError, match="task protocol"):
        scale.validate_grading_continuation(continuation.config)


def test_pre_model_loader_failure_can_be_superseded_without_retrying_any_cell(continuation):
    add_loader_preflight(continuation)
    add_abandoned_preparation(continuation)
    assert scale.validate_grading_continuation(continuation.config) == continuation.receipt


@pytest.mark.parametrize("mutation", ["cell", "native", "advanced", "solve", "wrong_task", "wrong_error", "cohort_binding", "error_type"])
def test_abandoned_preparation_cannot_hide_model_work_or_changed_authority(continuation, mutation):
    add_loader_preflight(continuation)
    opts = {}
    if mutation == "solve":
        opts["stages"] = ("PREPARE_STARTED", "SOLVE_STARTED", "INFRA_ERROR")
    elif mutation == "wrong_task":
        opts["task"] = "different-task"
    elif mutation == "wrong_error":
        opts["error"] = "solver failure"
    elif mutation == "error_type":
        opts["error_type"] = "NativeWorkerFailure"
    prior, execution, cohort = add_abandoned_preparation(continuation, **opts)
    if mutation == "cell":
        retain(Path(execution["run_root"]) / "cells/TRAINING/remaining-0/PDF_MEMORY/cell.json", {})
    elif mutation == "native":
        Path(execution["native_control_root"]).mkdir()
    elif mutation == "advanced":
        event(cohort, "SOLVE_STARTED", task="remaining-0")
    elif mutation == "cohort_binding":
        (cohort / "cohort.json").write_text('{"experiment_reference":{}}')
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(continuation.config)


def add_frozen_native_binary(case, monkeypatch):
    root = case.root / "binary-bundle"
    binary = retain(root / "codex.exe", {"public_synthetic_executable": True})
    auxiliary = retain(root / "resources/runner.exe", {"public_synthetic_support": True})
    windows = "C:/frozen-codex/codex.exe"
    monkeypatch.setattr(scale, "_windows_native_path", lambda path: windows)
    receipt = {"schema": "skhynix/frozen-native-binary/1.0", "model_calls": 0, "version": "test-cli",
        "bundle_root": str(root), "binary_reference": binary, "codex_binary": windows,
        "original_binary_reference": {"path": "/removed/old-extension/codex.exe", "sha256": binary["sha256"]},
        "bundle_sha256": {"codex.exe": binary["sha256"], "resources/runner.exe": auxiliary["sha256"]}}
    reference = retain(case.root / "native-binary.json", receipt)
    case.new = {**case.new, "codex_binary": windows}
    new_ref = retain(case.root / "execution-with-native.json", case.new)
    case.config["training_stages"][1]["execution_reference"] = new_ref
    case.config["training_experiment_reference"] = new_ref
    old240 = scale.core.check(case.config["training_stages"][2]["execution_reference"])
    case.config["training_stages"][2]["execution_reference"] = retain(case.root / "240-with-native.json", {**old240, "codex_binary": windows})
    update_receipt(case, new_execution_reference=new_ref, native_binary_reference=reference)
    return receipt


@pytest.fixture
def aborted_native(continuation, monkeypatch):
    import copy
    import json
    case = continuation
    case.binary = add_frozen_native_binary(case, monkeypatch)
    prior = copy.deepcopy(case.config)
    prior["pipeline_root"] = str(case.root / "native-abort-pipeline")
    execution = {**case.new, "run_root": str(case.root / "native-abort-run"),
                 "native_control_root": str(case.root / "native-abort-native"), "codex_binary": "C:/removed/codex.exe"}
    prior_ref = retain(case.root / "native-abort-execution.json", execution)
    prior["training_stages"][1]["execution_reference"] = prior_ref
    pipeline_ref = retain(case.root / "native-abort-pipeline.json", prior)
    retain(Path(prior["pipeline_root"]) / "pipeline-binding.json", {"schema": scale.SCHEMA, "configuration_reference": pipeline_ref})
    root, task = Path(execution["run_root"]), "remaining-0"
    cohort = root / "cohort"
    retain(cohort / "cohort.json", {"experiment_reference": prior_ref})
    folder = root / "cells/TRAINING" / task / "PDF_MEMORY"
    cell = {"experiment_config": prior_ref["path"], "task_public": {"task_id": task}, "target": {"instance_id": task},
            "phase": "TRAINING", "arm": "PDF_MEMORY", "bank_reference": None}
    cellref = retain(folder / "cell.json", cell)
    (folder / "cell.sha256").write_text(scale.core.digest(scale.canonical_bytes(cell)))
    event(cohort, "PREPARE_STARTED", task=task)
    event(cohort, "PREPARED", task=task, details={"cell_reference": cellref})
    event(cohort, "SOLVE_STARTED", task=task)
    native = Path(execution["native_control_root"]) / "TRAINING" / task / "PDF_MEMORY/worker-001"
    tail = event(cohort, "INFRA_ERROR", task=task, details={"error_type": "FileNotFoundError",
        "error": "Missing " + str(native / "output/completion.json")})
    ptail = event(Path(prior["pipeline_root"]), "PIPELINE_BLOCKED")
    packetbody = {"public": "task-only packet"}
    packetsha = scale.core.digest(scale.canonical_bytes(packetbody))
    packet = {"body": packetbody, "sha256": packetsha, "schema": "public-packet"}
    worker_id = "worker-one"
    state = {"status": "WAITING_ADMISSION", "actions": 0, "started_at": None, "history": [], "submission": None,
        "current_worker": worker_id, "last_packet": "0001.json", "workers": {worker_id: {
            "status": "ISSUED", "packet_file": "0001.json", "packet_sha256": packetsha}}}
    retain(folder / "broker/state.json", state)
    broker_event = {"kind": "ISSUE_HANDOFF", "sequence": 1, "previous_sha256": "0" * 64,
                    "state_after_sha256": scale.core.digest(scale.canonical_bytes(state))}
    broker_event["sha256"] = scale.core.digest(scale.canonical_bytes(broker_event))
    (folder / "broker/events.jsonl").write_text(json.dumps(broker_event) + "\n")
    retain(folder / "broker/packets/0001.json", packet)
    retain(native / "packet.json", packet)
    (native / "prompt.txt").write_text("Public synthetic prompt")
    promptsha = scale.core.ref(native / "prompt.txt")["sha256"]
    worker = {"worker_id": worker_id, "linux_cell_config": str(folder / "cell.json"), "codex_binary": execution["codex_binary"],
              "packet_sha256": packetsha, "prompt_sha256": promptsha, "model": "gpt-6-astra", "reasoning_effort": "high", "authentication": "CHATGPT"}
    retain(native / "config.json", worker)
    retain(native / "output/launch.json", {"worker_id": worker_id, "packet_sha256": packetsha, "prompt_sha256": promptsha,
        "requested_model": "gpt-6-astra", "reasoning_effort": "high", "authentication": "CHATGPT_FORCED",
        "fresh_session": True, "resume_or_fork_used": False})
    (native / "launcher-stderr.log").write_bytes(b"Popen CreateProcess WinError 2 \xff\xfe")
    (native / "output/events.jsonl").write_bytes(b"")
    (native / "output/stderr.log").write_bytes(b"")
    paths = {"cell": folder / "cell.json", "cell_checksum": folder / "cell.sha256", "broker_state": folder / "broker/state.json",
        "broker_events": folder / "broker/events.jsonl", "broker_packet": folder / "broker/packets/0001.json",
        "worker_config": native / "config.json", "worker_packet": native / "packet.json", "worker_prompt": native / "prompt.txt",
        "launch": native / "output/launch.json", "launcher_stderr": native / "launcher-stderr.log",
        "events": native / "output/events.jsonl", "stderr": native / "output/stderr.log"}
    update_receipt(case, aborted_native_launch_pipeline_reference=pipeline_ref,
        aborted_native_launch_pipeline_event_tail_reference=ptail, aborted_native_launch_cohort_event_tail_reference=tail,
        aborted_native_launch_evidence_references={key: scale.core.ref(path) for key, path in paths.items()})
    case.aborted_paths, case.aborted_native, case.aborted_cohort, case.aborted_state = paths, native, cohort, state
    return case


def test_exact_pre_admission_binary_launch_failure_can_continue_without_model_retry(aborted_native):
    assert scale.validate_grading_continuation(aborted_native.config) == aborted_native.receipt
    scale._validate_frozen_native_binary(aborted_native.receipt["native_binary_reference"], [aborted_native.new], verify_bytes=True)
    assert not Path(aborted_native.binary["original_binary_reference"]["path"]).exists()


@pytest.mark.parametrize("index", [1, 2])
def test_native_binary_must_match_both_future_stages(aborted_native, index):
    stage = aborted_native.config["training_stages"][index]
    changed = {**scale.core.check(stage["execution_reference"]), "codex_binary": "C:/different.exe"}
    stage["execution_reference"] = retain(aborted_native.root / "different-native.json", changed)
    if index == 1:
        aborted_native.config["training_experiment_reference"] = stage["execution_reference"]
        update_receipt(aborted_native, new_execution_reference=stage["execution_reference"])
    with pytest.raises(scale.core.PipelineError, match="both future stages"):
        scale.validate_grading_continuation(aborted_native.config)


def test_native_bundle_full_validation_hashes_support_files_without_hashing_removed_provenance(aborted_native):
    path = Path(aborted_native.binary["bundle_root"]) / "resources/runner.exe"
    path.write_text("changed support executable")
    scale._validate_frozen_native_binary(aborted_native.receipt["native_binary_reference"], [aborted_native.new], verify_bytes=False)
    with pytest.raises(scale.core.PipelineError):
        scale._validate_frozen_native_binary(aborted_native.receipt["native_binary_reference"], [aborted_native.new], verify_bytes=True)


@pytest.mark.parametrize("mutation", ["actions", "admitted", "started", "history", "model_event", "admission_file", "completion_file",
    "submission_file", "grader_file", "advanced", "packet", "launch_error", "missing_reference"])
def test_zero_activity_native_continuation_rejects_started_or_changed_attempts(aborted_native, mutation):
    import json
    case = aborted_native
    if mutation in {"actions", "admitted", "started", "history"}:
        state = case.aborted_state
        if mutation == "actions": state["actions"] = 1
        elif mutation == "admitted": state["workers"][state["current_worker"]]["status"] = "ADMITTED"
        elif mutation == "started": state["started_at"] = 1
        else: state["history"] = [{"tool": "read_file"}]
        case.aborted_paths["broker_state"].write_bytes(scale.canonical_bytes(state))
        eventbody = {"kind": "ISSUE_HANDOFF", "sequence": 1, "previous_sha256": "0" * 64,
                     "state_after_sha256": scale.core.digest(scale.canonical_bytes(state))}
        eventbody["sha256"] = scale.core.digest(scale.canonical_bytes(eventbody))
        case.aborted_paths["broker_events"].write_text(json.dumps(eventbody) + "\n")
    elif mutation == "model_event": case.aborted_paths["events"].write_text('{"type":"thread.started"}\n')
    elif mutation == "admission_file": retain(case.aborted_native / "admission.json", {})
    elif mutation == "completion_file": retain(case.aborted_native / "output/completion.json", {})
    elif mutation == "submission_file": retain(case.aborted_paths["cell"].parent / "broker/submission.json", {})
    elif mutation == "grader_file": retain(case.aborted_paths["cell"].parent / "grader-pending.json", {})
    elif mutation == "advanced": event(case.aborted_cohort, "SOLVE_COMPLETE", task="remaining-0")
    elif mutation == "packet": case.aborted_paths["worker_packet"].write_text('{}')
    elif mutation == "launch_error": case.aborted_paths["launcher_stderr"].write_text("model quota error")
    refs = {key: scale.core.ref(path) for key, path in case.aborted_paths.items()}
    if mutation == "missing_reference": refs.pop("events")
    update_receipt(case, aborted_native_launch_evidence_references=refs)
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(case.config)


@pytest.fixture
def chained_continuation(continuation):
    return make_chained_continuation(continuation)


def make_chained_continuation(continuation, *, completed_count=11):
    import copy
    case = continuation
    predecessor_config = copy.deepcopy(case.config)
    predecessor = retain(case.root / "chained-predecessor.json", predecessor_config)
    old_ref = predecessor_config["training_stages"][1]["execution_reference"]
    old = scale.core.check(old_ref)
    old_authority = scale.core.check(old["scale_authority_reference"])
    old_adoption = scale.core.check(old_authority["source_adoption_reference"])
    root = Path(old["run_root"])
    retain(Path(predecessor_config["pipeline_root"]) / "pipeline-binding.json", {"schema": scale.SCHEMA, "configuration_reference": predecessor})
    retain(root / "cohort/cohort.json", {"experiment_reference": old_ref})
    added = []
    for task in old_authority["task_ids"][:completed_count]:
        folder = root / "cells/TRAINING" / task / "PDF_MEMORY"
        cell_ref = retain(folder / "cell.json", {"task_public": {"task_id": task}})
        result = retain(folder / "public-result.json", {"official": True, "resolved": False})
        added.append({"task_id": task, "cell_reference": cell_ref, "official_result_reference": result, "classification": "OFFICIAL_COMPLETE"})
        event(root / "cohort", "PREPARED", task=task, details={"cell_reference": cell_ref})
        event(root / "cohort", "CELL_COMPLETE", task=task)
    task = old_authority["task_ids"][completed_count]
    folder = root / "cells/TRAINING" / task / "PDF_MEMORY"
    cell = {"task_public": {"task_id": task}, "phase": "TRAINING", "arm": "PDF_MEMORY",
        "target": {"instance_id": task}, "bank_reference": None, "experiment_config": old_ref["path"]}
    cell_ref = retain(folder / "cell.json", cell)
    (folder / "cell.sha256").write_text(scale.core.digest(scale.canonical_bytes(cell)))
    event(root / "cohort", "PREPARED", task=task, details={"cell_reference": cell_ref})
    tail = event(root / "cohort", "INFRA_ERROR", task=task, details={"error_type": "GraderInvocationFailure"})
    ptail = event(Path(predecessor_config["pipeline_root"]), "PIPELINE_BLOCKED")
    patch = retain(folder / "broker/submission.diff", {"public_patch": True})
    binding = {"task_id": task, "configuration_sha256": scale.core.digest(scale.canonical_bytes(old)), "patch_sha256": patch["sha256"]}
    audit = retain(folder / "execution-audit.json", {**binding, "passed": True, "errors": []})
    submission = retain(folder / "broker/submission.json", {**binding, "agent_completed": True, "reason": "WORKER_SUBMITTED"})
    pending = retain(folder / "grader-pending.json", {"patch_sha256": patch["sha256"]})
    summary = retain(root / "environment/TRAINING/cells/PDF_MEMORY" / task / "official-grader" / task / "report/summary.json",
        {**case.summarydata, "failure_reasons": {task: "missing_module"}})
    added.append({"task_id": task, "cell_reference": cell_ref, "official_result_reference": None,
                  "official_summary_reference": summary, "classification": "AMBIGUOUS_MISSING_MODULE"})
    adoption_data = {"rows": old_adoption["rows"] + added, "predecessor_configrefs": old_adoption["predecessor_configrefs"] + [old_ref],
        "source_count": old_adoption["source_count"] + completed_count + 1,
        "official_complete": old_adoption["official_complete"] + completed_count}
    adoption = retain(case.root / "chained-adoption.json", adoption_data)
    authority_data = {**old_authority, "source_adoption_reference": adoption, "task_ids": old_authority["task_ids"][completed_count + 1:]}
    authority = retain(case.root / "chained-authority.json", authority_data)
    new = {**old, "run_root": str(case.root / "chained-run"), "native_control_root": str(case.root / "chained-native"), "scale_authority_reference": authority}
    new_ref = retain(case.root / "chained-execution.json", new)
    receipt = {"schema": scale.CHAINED_CONTINUATION_SCHEMA, "operation": "CONTINUE_AFTER_UNDETERMINED_SOURCE_GRADE",
        "task_id": task, "official_outcome": "UNDETERMINED", "resolved": None, "classification": "AMBIGUOUS_MISSING_MODULE",
        "source_only": True, "native_retries": False, "official_grader_retries": False, "model_calls": 0, "official_grader_runs": 0,
        "predecessor_pipeline_reference": predecessor, "historical_grading_continuation_reference": predecessor_config["grading_continuation_reference"],
        "predecessor_pipeline_event_tail_reference": ptail, "predecessor_cohort_event_tail_reference": tail,
        "old_execution_reference": old_ref, "new_execution_reference": new_ref, "source_adoption_reference": adoption,
        "old_cell_reference": cell_ref, "audit_reference": audit, "submission_reference": submission,
        "submission_patch_reference": patch, "grader_pending_reference": pending, "official_summary_reference": summary,
        **{key: case.receipt.get(key) for key in ("runtime_change_reference", "loader_preflight_reference", "native_binary_reference")}}
    config = {**copy.deepcopy(predecessor_config), "pipeline_root": str(case.root / "chained-pipeline"),
        "supersedes_configuration_reference": predecessor, "training_experiment_reference": new_ref}
    config["training_stages"][1] = {"size": 120, "execution_reference": new_ref}
    config["grading_continuation_reference"] = retain(case.root / "chained-continuation.json", receipt)
    return SimpleNamespace(root=case.root, config=config, receipt=receipt, new=new, old=old, predecessor_config=predecessor_config,
        adoption_data=adoption_data, authority_data=authority_data, cohort=root / "cohort", folder=folder, summarydata=case.summarydata)


def test_chained_continuation_reuses_all_48_sources_and_only_48_remaining(chained_continuation):
    case = chained_continuation
    assert scale.validate_grading_continuation(case.config) == case.receipt
    assert case.new["source_root"] == case.old["source_root"]
    assert case.config["training_stages"][0] == case.predecessor_config["training_stages"][0]
    assert case.config["training_stages"][2] == case.predecessor_config["training_stages"][2]


@pytest.mark.parametrize("field,value", [("native_retries", True), ("resolved", False), ("official_grader_retries", True),
    ("runtime_change_reference", None), ("historical_grading_continuation_reference", None),
    ("aborted_native_launch_pipeline_reference", {})])
def test_chained_continuation_cannot_change_protocol_or_borrow_old_failure(chained_continuation, field, value):
    update_receipt(chained_continuation, **{field: value})
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(chained_continuation.config)


@pytest.mark.parametrize("mutation", ["prefix", "suffix", "skip", "duplicate", "owner", "scored", "count"])
def test_chained_source_selection_and_outcomes_cannot_change(chained_continuation, mutation):
    import copy
    case = chained_continuation
    adoption, authority = copy.deepcopy(case.adoption_data), copy.deepcopy(case.authority_data)
    if mutation == "prefix": adoption["rows"][0]["task_id"] = "replaced-history"
    elif mutation == "suffix": authority["task_ids"] = list(reversed(authority["task_ids"]))
    elif mutation == "skip": adoption["rows"].pop(36)
    elif mutation == "duplicate": adoption["rows"][37] = adoption["rows"][36]
    elif mutation == "owner": adoption["rows"][36]["cell_reference"] = retain(case.root / "cloned-source.json", {})
    elif mutation == "scored": adoption["rows"][-1]["official_result_reference"] = adoption["rows"][36]["official_result_reference"]
    else: adoption["official_complete"] += 1
    adoption_ref = retain(case.root / "changed-chained-adoption.json", adoption)
    authority["source_adoption_reference"] = adoption_ref
    new = {**case.new, "scale_authority_reference": retain(case.root / "changed-chained-authority.json", authority)}
    execution = retain(case.root / "changed-chained-execution.json", new)
    case.config["training_stages"][1]["execution_reference"] = execution
    case.config["training_experiment_reference"] = execution
    update_receipt(case, new_execution_reference=execution, source_adoption_reference=adoption_ref)
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(case.config)


def test_chained_validation_rechecks_the_original_seaborn_authority(chained_continuation):
    case = chained_continuation
    historical = scale.core.check(case.receipt["historical_grading_continuation_reference"])
    Path(historical["submission_patch_reference"]["path"]).write_text("old immutable patch changed")
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(case.config)


@pytest.mark.parametrize("where", ["current", "historical"])
def test_chained_validation_rejects_advanced_journals(chained_continuation, where):
    case = chained_continuation
    root = case.cohort
    if where == "historical":
        old = scale.core.check(case.receipt["historical_grading_continuation_reference"])
        root = Path(old["predecessor_cohort_event_tail_reference"]["path"]).parent.parent
    event(root, "PREPARE_STARTED", task="not-authorized")
    with pytest.raises(scale.core.PipelineError, match="advanced"):
        scale.validate_grading_continuation(case.config)


def test_chained_controller_holds_current_and_historical_journal_locks(chained_continuation, monkeypatch):
    case = chained_continuation
    p = scale.ScalePipeline.__new__(scale.ScalePipeline)
    p.config = {**case.config}
    p.config.pop("infrastructure_replacement_reference")
    p.root = Path(case.config["pipeline_root"])
    p.reference = retain(p.root / "configuration.json", p.config)
    global_tail = event(case.root / "global-history", "BLOCKED")
    p.adoption = {"original_pipeline_event_tail_reference": global_tail}
    p.operations = SimpleNamespace(modules={"cohort": SimpleNamespace(execution=None)})
    held = set()
    @contextmanager
    def observed(path):
        held.add(path)
        try: yield
        finally: held.remove(path)
    monkeypatch.setattr(scale, "locked", observed)
    monkeypatch.setattr(scale, "validate_grading_continuation", lambda *a, **kw: None)
    expected = {p.root / "run.lock", case.root / "global-history/run.lock"}
    for _, receipt in scale._grading_lineage(p.config):
        expected.update(Path(receipt[key]["path"]).parent.parent / "run.lock"
            for key in ("predecessor_pipeline_event_tail_reference", "predecessor_cohort_event_tail_reference"))
    with p._controller_locks():
        assert held == expected
    assert not held


def test_chained_quota_validation_remains_historical_only(recovery):
    predecessor = retain(recovery.root / "quota-owner-v4.json", recovery.config)
    first_receipt = retain(recovery.root / "historical-grading.json", {"predecessor_pipeline_reference": predecessor})
    first_config = {**recovery.config, "grading_continuation_reference": first_receipt}
    first_ref = retain(recovery.root / "historical-grading-pipeline.json", first_config)
    second_receipt = retain(recovery.root / "chained-quota-history.json", {"schema": scale.CHAINED_CONTINUATION_SCHEMA,
        "predecessor_pipeline_reference": first_ref, "historical_grading_continuation_reference": first_receipt})
    second_config = {**first_config, "grading_continuation_reference": second_receipt}
    assert scale.validate_infrastructure_replacement(second_config) == recovery.receipt


def set_chained_ambiguity(case, *, classification="AMBIGUOUS_NO_TESTS_COLLECTED", reason="no_tests_collected",
                          summary_changes=None, adoption_classification=None, count_pending=False):
    import copy
    summary = {**scale.core.check(case.receipt["official_summary_reference"]),
               "failure_reasons": {case.receipt["task_id"]: reason}, **(summary_changes or {})}
    summary_ref = retain(Path(case.receipt["official_summary_reference"]["path"]).with_name("new-classification-summary.json"), summary)
    adoption = copy.deepcopy(case.adoption_data)
    adoption["rows"][-1].update(classification=adoption_classification or classification, official_summary_reference=summary_ref)
    if count_pending:
        adoption["official_complete"] += 1
    adoption_ref = retain(case.root / "new-classification-adoption.json", adoption)
    authority_ref = retain(case.root / "new-classification-authority.json", {**case.authority_data, "source_adoption_reference": adoption_ref})
    case.new = {**case.new, "scale_authority_reference": authority_ref}
    execution = retain(case.root / "new-classification-execution.json", case.new)
    case.config["training_stages"][1]["execution_reference"] = execution
    case.config["training_experiment_reference"] = execution
    update_receipt(case, classification=classification, official_summary_reference=summary_ref,
                   source_adoption_reference=adoption_ref, new_execution_reference=execution)


def test_no_tests_collected_continuation_preserves_unknown_outcome(chained_continuation):
    case = chained_continuation
    set_chained_ambiguity(case)
    assert scale.validate_grading_continuation(case.config) == case.receipt
    assert case.receipt["resolved"] is None
    assert scale.core.check(case.receipt["source_adoption_reference"])["official_complete"] == 46
    assert case.config["training_stages"][0] == case.predecessor_config["training_stages"][0]
    assert case.config["training_stages"][2] == case.predecessor_config["training_stages"][2]


def test_second_v2_no_tests_continuation_retains_missing_module_history_and_35_suffix(chained_continuation):
    first = chained_continuation
    second = make_chained_continuation(SimpleNamespace(**{**vars(first), "root": first.root / "second-continuation"}), completed_count=12)
    set_chained_ambiguity(second)
    assert scale.validate_grading_continuation(second.config) == second.receipt
    assert len(scale.core.check(second.new["scale_authority_reference"])["task_ids"]) == 35
    adoption = scale.core.check(second.receipt["source_adoption_reference"])
    assert adoption["source_count"] == 61 and adoption["official_complete"] == 58
    assert adoption["rows"][:48] == first.adoption_data["rows"]
    assert len(scale._grading_lineage(second.config)) == 3


@pytest.mark.parametrize("classification,reason", [
    ("AMBIGUOUS_NO_TESTS_COLLECTED", "missing_module"),
    ("AMBIGUOUS_MISSING_MODULE", "no_tests_collected"),
    ("AMBIGUOUS_NO_TESTS_COLLECTED", "timeout"),
    ("OFFICIAL_COMPLETE", "no_tests_collected"),
])
def test_chained_reason_must_match_exact_supported_classification(chained_continuation, classification, reason):
    set_chained_ambiguity(chained_continuation, classification=classification, reason=reason)
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(chained_continuation.config)


@pytest.mark.parametrize("field,value", [
    ("total_instances", 2), ("submitted_instances", 0), ("completed_instances", 0),
    ("completed_instances", True), ("resolved_instances", 1), ("unresolved_instances", 0),
    ("ambiguous_failure_instances", 0), ("infra_failure_instances", 1),
    ("empty_patch_instances", 1), ("error_instances", 1), ("unstopped_instances", 1),
])
def test_no_tests_adoption_requires_one_terminal_unscored_aggregate(chained_continuation, field, value):
    set_chained_ambiguity(chained_continuation, summary_changes={field: value})
    with pytest.raises(scale.core.PipelineError, match="terminal ambiguous aggregate"):
        scale.validate_grading_continuation(chained_continuation.config)


def test_no_tests_receipt_cannot_disagree_with_adopted_classification(chained_continuation):
    set_chained_ambiguity(chained_continuation, adoption_classification="AMBIGUOUS_MISSING_MODULE")
    with pytest.raises(scale.core.PipelineError, match="remain undetermined"):
        scale.validate_grading_continuation(chained_continuation.config)


def test_no_tests_source_cannot_be_counted_as_an_official_result(chained_continuation):
    set_chained_ambiguity(chained_continuation, count_pending=True)
    with pytest.raises(scale.core.PipelineError, match="exact untouched suffix"):
        scale.validate_grading_continuation(chained_continuation.config)


def test_no_tests_continuation_cannot_replace_a_scored_attempt(chained_continuation):
    set_chained_ambiguity(chained_continuation)
    retain(chained_continuation.folder / "public-result.json", {"official": True, "resolved": False})
    with pytest.raises(scale.core.PipelineError, match="undetermined grade"):
        scale.validate_grading_continuation(chained_continuation.config)


def add_training_runtime_revision(case, *, budget_terminal=False):
    import copy
    set_chained_ambiguity(case)
    source = case.root / "training-policy-source"
    hashes = dict(case.old["source_sha256"])
    for name in ("run", "cohort", "cleanup"):
        relative = "scripts/trimem_skhynix_architecture_" + name + ".py"
        hashes[relative] = retain(source / relative, {"training_revision": name})["sha256"]
    helper = retain(source / "helper.json", {"same": True})
    loader = retain(case.root / "training-loader.json", {"exact_runtime": str(source)})
    case.new.update(source_root=str(source), source_sha256=hashes,
        training_grade_hold_policy=scale.TRAINING_GRADE_HOLD_POLICY,
        loader_preflight_path=loader["path"], loader_preflight_sha256=loader["sha256"])
    new_ref = retain(case.root / "training-execution.json", case.new)
    case.config["training_stages"][1]["execution_reference"] = new_ref
    case.config["training_experiment_reference"] = new_ref
    old240 = scale.core.check(case.predecessor_config["training_stages"][2]["execution_reference"])
    fields = ("source_root", "source_sha256", "training_grade_hold_policy", "loader_preflight_path", "loader_preflight_sha256")
    stage240 = copy.deepcopy(case.predecessor_config["training_stages"][2])
    stage240["execution_reference"] = retain(case.root / "training240.json", {**old240, **{k: case.new[k] for k in fields}})
    case.config["training_stages"][2] = stage240
    case.config["helper_references"] = {"helper": helper}
    case.config["reflection_source_reference"] = helper
    freeze = retain(case.root / "training-runtime-freeze.json", {
        "schema": "skhynix/grading-continuation-runtime-freeze/1.0", "previous_execution_reference": case.receipt["old_execution_reference"],
        "old_source_root": case.old["source_root"], "old_source_sha256": case.old["source_sha256"],
        "source_root": str(source), "source_sha256": hashes,
        "changed_paths": sorted("scripts/trimem_skhynix_architecture_" + name + ".py" for name in ("run", "cohort", "cleanup")),
        "model_calls": 0, "official_grader_runs": 0})
    changes = {}
    if budget_terminal:
        audit = scale.core.check(case.receipt["audit_reference"])
        audit["workers"] = [{"outcome": "COMPLETE"}, {"outcome": "BUDGET_TIMEOUT"}]
        changes["audit_reference"] = rewrite_fixture(case.folder / "execution-audit.json", audit)
        submission = scale.core.check(case.receipt["submission_reference"])
        submission.update(agent_completed=False, reason="NATIVE_WORKER_WALL_LIMIT")
        changes["submission_reference"] = rewrite_fixture(case.folder / "broker/submission.json", submission)
    update_receipt(case, schema=scale.TRAINING_CONTINUATION_SCHEMA, new_execution_reference=new_ref,
        runtime_change_reference=freeze, loader_preflight_reference=loader, **changes)


def rewrite_fixture(path, value):
    """Only synthetic pytest records are varied before each validation assertion."""
    path.write_bytes(scale.canonical_bytes(value) + b"\n")
    return scale.core.ref(path)


@pytest.mark.parametrize("budget_terminal", [False, True])
def test_training_runtime_revision_preserves_unknown_grade_and_exact_schedule(chained_continuation, budget_terminal):
    case = chained_continuation
    add_training_runtime_revision(case, budget_terminal=budget_terminal)
    assert scale.validate_grading_continuation(case.config) == case.receipt
    assert scale.core.check(case.new["scale_authority_reference"])["task_ids"] == case.authority_data["task_ids"]
    assert case.receipt["resolved"] is None and case.receipt["official_grader_retries"] is False
    assert case.config["training_stages"][0] == case.predecessor_config["training_stages"][0]
    if budget_terminal:
        assert scale.core.check(case.receipt["submission_reference"])["agent_completed"] is False


@pytest.mark.parametrize("mutation", ["no_budget_worker", "native_error", "wrong_reason", "completed_true"])
def test_training_revision_rejects_false_or_infrastructure_budget_proof(chained_continuation, mutation):
    case = chained_continuation
    add_training_runtime_revision(case, budget_terminal=True)
    if mutation in {"no_budget_worker", "native_error"}:
        audit = scale.core.check(case.receipt["audit_reference"])
        audit["workers"][-1]["outcome"] = "COMPLETE" if mutation == "no_budget_worker" else "NATIVE_INFRA_ERROR"
        update_receipt(case, audit_reference=rewrite_fixture(case.folder / "execution-audit.json", audit))
    else:
        submission = scale.core.check(case.receipt["submission_reference"])
        submission.update({"reason": "OTHER_TIMEOUT"} if mutation == "wrong_reason" else {"agent_completed": True})
        update_receipt(case, submission_reference=rewrite_fixture(case.folder / "broker/submission.json", submission))
    with pytest.raises(scale.core.PipelineError, match="sealed successful native attempt"):
        scale.validate_grading_continuation(case.config)


@pytest.mark.parametrize("index,field,value", [(1, "training_grade_hold_policy", "ANY_ERROR"),
    (2, "training_grade_hold_policy", None), (2, "loader_preflight_sha256", "f" * 64),
    (1, "limits", {"task_requests": 999}), (2, "native_control_root", "/different-native")])
def test_training_runtime_cannot_change_budgets_or_desynchronize_future_stages(chained_continuation, index, field, value):
    case = chained_continuation
    add_training_runtime_revision(case)
    stage = case.config["training_stages"][index]
    config = scale.core.check(stage["execution_reference"])
    config[field] = value
    changed = retain(case.root / "mutated-training-execution.json", config)
    stage["execution_reference"] = changed
    if index == 1:
        case.config["training_experiment_reference"] = changed
        update_receipt(case, new_execution_reference=changed)
    with pytest.raises(scale.core.PipelineError):
        scale.validate_grading_continuation(case.config)


def test_training_runtime_requires_exact_new_loader_checker(chained_continuation, monkeypatch):
    import trimem_benchmark_run as benchmark
    case = chained_continuation
    add_training_runtime_revision(case)
    calls = []
    monkeypatch.setattr(benchmark, "load_official_harness_loader_preflight", lambda path: calls.append(path))
    execution = SimpleNamespace(execution_enrollment=lambda config, dataset: None)
    assert scale.validate_grading_continuation(case.config, execution=execution) == case.receipt
    assert calls == [Path(case.receipt["loader_preflight_reference"]["path"])]


def test_historical_v2_does_not_gain_budget_terminal_authority(chained_continuation):
    case = chained_continuation
    submission = scale.core.check(case.receipt["submission_reference"])
    submission.update(agent_completed=False, reason="NATIVE_WORKER_WALL_LIMIT")
    update_receipt(case, submission_reference=rewrite_fixture(case.folder / "broker/submission.json", submission))
    with pytest.raises(scale.core.PipelineError, match="sealed successful native attempt"):
        scale.validate_grading_continuation(case.config)


def test_runtime_revision_uses_historical_checker_only_for_old_loader(continuation, monkeypatch):
    import trimem_benchmark_run as benchmark
    add_loader_preflight(continuation)
    old_loader = continuation.receipt["loader_preflight_reference"]
    case = make_chained_continuation(continuation)
    add_training_runtime_revision(case)
    historical, current, enrollments = [], [], []
    monkeypatch.setattr(scale, "_validate_historical_loader", lambda ref, config: historical.append((ref, config)))
    monkeypatch.setattr(benchmark, "load_official_harness_loader_preflight", lambda path: current.append(path))
    scale.validate_grading_continuation(case.config, execution=SimpleNamespace(
        execution_enrollment=lambda config, dataset: enrollments.append(config)))
    assert len(historical) == 1 and historical[0][0] == old_loader
    assert historical[0][1]["source_root"] == continuation.new["source_root"]
    assert current == [Path(case.receipt["loader_preflight_reference"]["path"])]
    assert len(enrollments) == 2  # historical source authority remains fully validated


@pytest.mark.parametrize("returncode", [0, 1])
def test_historical_loader_uses_its_frozen_import_root_and_propagates_failure(tmp_path, monkeypatch, returncode):
    root = tmp_path / "historical-runtime"
    module = retain(root / "scripts/trimem_benchmark_run.py", {"frozen": True})
    loader = retain(tmp_path / "loader.json", {"old": True})
    config = {"source_root": str(root), "source_sha256": {"scripts/trimem_benchmark_run.py": module["sha256"]}}
    calls = []
    def invoke(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=returncode)
    monkeypatch.setattr(scale.subprocess, "run", invoke)
    if returncode:
        with pytest.raises(scale.core.PipelineError, match="historical frozen loader"):
            scale._validate_historical_loader(loader, config)
    else:
        scale._validate_historical_loader(loader, config)
    argv, kwargs = calls[0]
    assert argv[0] == scale.sys.executable and argv[-2:] == [loader["path"], str(root)]
    assert argv[1:3] == ["-P", "-c"] and "load_official_harness_loader_preflight" in argv[3]
    assert kwargs["cwd"] == root
    assert kwargs["env"]["PYTHONPATH"] == scale.os.pathsep.join(str(root / name) for name in ("scripts", "src"))
    assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    assert kwargs["timeout"] == 60


def test_historical_loader_rejects_changed_runtime_before_import(tmp_path, monkeypatch):
    module = retain(tmp_path / "source/scripts/trimem_benchmark_run.py", {"frozen": True})
    loader = retain(tmp_path / "loader.json", {"old": True})
    Path(module["path"]).write_bytes(b"changed code")
    monkeypatch.setattr(scale.subprocess, "run", lambda *args, **kwargs: pytest.fail("changed source was imported"))
    with pytest.raises(scale.core.PipelineError):
        scale._validate_historical_loader(loader, {"source_root": str(tmp_path / "source"),
            "source_sha256": {"scripts/trimem_benchmark_run.py": module["sha256"]}})
