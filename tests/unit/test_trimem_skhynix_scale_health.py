import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

import trimem_skhynix_scale_health as health

NOW = 2_000_000_000
TASK = "swebench--example__project-1"
SECRET = "NEVER_EMIT_ADMISSION_TOKEN_PRIVATE_PROMPT"


def write(path, value, stamp=NOW - 10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def scenario(tmp_path):
    root = tmp_path / "pipeline"
    root.mkdir()
    config = {"pipeline_root": str(root), "source_adoption_reference": {"path": str(write(tmp_path / "adoption.json", {"source_count": 21, "official_complete": 19}))}, "training_stages": []}
    for size in (24, 120, 240):
        run = tmp_path / f"training-{size}"
        execution = write(tmp_path / f"execution-{size}.json", {"run_root": str(run)})
        config["training_stages"].append({"size": size, "execution_reference": {"path": str(execution)}})
    path = write(tmp_path / "config.json", config)
    return path, config, tmp_path / "training-24"


def active(scenario, *, stage="SOLVE_STARTED", stamp=NOW - 10, pending=0, worker="ADMITTED"):
    path, config, run = scenario
    cell = run / "cells/TRAINING" / TASK / "PDF_MEMORY/cell.json"
    write(run / "cohort/cohort.json", {"phase": "TRAINING", "schedule": [{"task_id": TASK, "arm": "PDF_MEMORY", "cell_config": str(cell), "ordinal": 1}]}, stamp)
    write(run / "cohort/events/00000001.json", {"stage": stage, "task_id": TASK, "arm": "PDF_MEMORY", "ordinal": 1, "at": stamp}, stamp)
    write(cell.parent / "broker/state.json", {"status": "RUNNING", "actions": 7, "unfinished_actions": pending,
        "workers": {"worker": {"status": worker, "admission_token_sha256": SECRET, "launch_receipt": SECRET}},
        "current_worker": "worker" if worker == "ADMITTED" else None, "history": [{"prompt": SECRET}]}, stamp)
    return cell


def test_cold_preparation_and_public_learning_counts_are_not_promotions(scenario):
    path, config, _ = scenario
    assert health.inspect_health(path, now=NOW)["status"] == "IDLE_PREPARATION"
    root = Path(config["pipeline_root"]) / "learning-24"
    write(root / "learning-state.json", {"cells": {"a": SECRET, "b": SECRET}, "reflections": {}, "ingestions": {}})
    write(root / "catalog.json", {"captures": {str(i): SECRET for i in range(4)}, "knowledge": {"a": SECRET}, "edges": [{}], "skills": {}})
    with sqlite3.connect(root / "authority.sqlite3") as db:
        db.executescript("CREATE TABLE memory_records(kind TEXT,revoked INT); CREATE TABLE knowledge_relations(source_id TEXT);")
        db.executemany("INSERT INTO memory_records VALUES(?,?)", [("episode", 0)] * 4 + [("knowledge", 0), ("knowledge", 1)])
        db.execute("INSERT INTO knowledge_relations VALUES('a')")
    before = (root / "authority.sqlite3").read_bytes()
    result = health.inspect_health(path, now=NOW)
    counts = result["stages"][0]["learning"]
    assert (counts["cells"], counts["captures"], counts["L1_episodes"], counts["L2_nodes"], counts["L2_relations"], counts["L3_skills"]) == (2, 4, 4, 1, 1, 0)
    assert result["status"] == "PROGRESSING" and result["adopted_official_complete"] == 19
    assert before == (root / "authority.sqlite3").read_bytes()
    assert SECRET not in json.dumps(result)


def test_block_is_explicit_and_reason_and_private_fields_are_never_emitted(scenario):
    path, config, _ = scenario
    active(scenario)
    write(Path(config["pipeline_root"]) / "events/00000007.json", {"stage": "PIPELINE_BLOCKED", "at": NOW - 20,
        "details": {"error_type": "GraderInvocationFailure", "reason": SECRET, "private_output": SECRET}})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["pipeline"]["error_type"] == "GraderInvocationFailure"
    assert result["stages"][0]["cohort"]["current"]["state"] == "ACTIVE"
    assert result["process_liveness"] == "NOT_OBSERVED"
    assert SECRET not in json.dumps(result)


def test_old_pipeline_snapshot_with_fresh_broker_is_progressing(scenario):
    path, config, _ = scenario
    active(scenario, stamp=NOW - 10)
    write(Path(config["pipeline_root"]) / "events/1.json", {"stage": "COHORT_ADVANCE_STARTED", "at": NOW - 7200}, NOW - 7200)
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "PROGRESSING" and result["activity_age_seconds"] == 10


@pytest.mark.parametrize("pending,worker,expected", [(1, "ADMITTED", "ACTION_PENDING"), (0, "ISSUED", "UNKNOWN"), (0, "REVOKED", "UNKNOWN")])
def test_broker_pending_is_distinct_from_active(scenario, pending, worker, expected):
    path, _, _ = scenario
    active(scenario, pending=pending, worker=worker)
    assert health.inspect_health(path, now=NOW)["stages"][0]["cohort"]["current"]["state"] == expected


def test_submitted_and_official_counts_are_separate_from_workflow_completion(scenario):
    path, _, _ = scenario
    cell = active(scenario, stage="GRADED")
    state = json.loads((cell.parent / "broker/state.json").read_text())
    state.update(status="SUBMITTED", current_worker=None)
    write(cell.parent / "broker/state.json", state)
    write(cell.parent / "public-result.json", {"official": True, "grader_status": "success", "resolved": False, "task_id": TASK, "arm": "PDF_MEMORY", "secret": SECRET})
    cohort = health.inspect_health(path, now=NOW)["stages"][0]["cohort"]
    assert (cohort["completed"], cohort["official_complete"], cohort["resolved"]) == (0, 1, 0)
    assert cohort["current"]["state"] == "SUBMITTED"


@pytest.mark.parametrize("stage,expected", [
    ("PIPELINE_COMPLETE", "COMPLETE"),
    ("PIPELINE_COMPLETE_WITH_UNDETERMINED", "COMPLETE_WITH_UNDETERMINED"),
    ("NO_READY_MEMORY_BANK", "NOT_READY"),
])
def test_terminal_status_not_inferred_from_source_counts(scenario, stage, expected):
    path, config, _ = scenario
    write(Path(config["pipeline_root"]) / "events/1.json", {"stage": stage, "at": NOW - 9000}, NOW - 9000)
    assert health.inspect_health(path, now=NOW)["status"] == expected


def test_completed_with_undetermined_preserves_terminal_event_and_unscored_counts(continuation):
    path, config, _ = continuation["scenario"]
    write(continuation["event_path"], {
        "stage": "PIPELINE_COMPLETE_WITH_UNDETERMINED", "at": NOW - 7200,
        "details": {"cohort_root": str(continuation["cohort"])}}, NOW - 7200)
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "COMPLETE_WITH_UNDETERMINED"
    assert result["pipeline"]["stage"] == "PIPELINE_COMPLETE_WITH_UNDETERMINED"
    assert result["evaluation_cohort"]["official_complete"] == 1
    assert result["evaluation_cohort"]["resolved"] == 1
    assert result["process_liveness"] == "NOT_OBSERVED"


def test_stale_preflight_warns_without_declaring_process_dead(scenario):
    path, _, run = scenario
    write(run / "cohort/events/1.json", {"stage": "PREPARE_STARTED", "at": NOW - 7200}, NOW - 7200)
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "WARNING_STALE" and result["process_liveness"] == "NOT_OBSERVED"


@pytest.mark.parametrize("problem", ["missing", "malformed", "unknown"])
def test_missing_or_malformed_active_state_fails_to_warning_without_payload(scenario, problem):
    path, _, _ = scenario
    cell = active(scenario)
    state = cell.parent / "broker/state.json"
    if problem == "missing":
        state.unlink()
    elif problem == "malformed":
        state.write_text('{"secret":"' + SECRET)
    else:
        write(state, {"status": SECRET})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "WARNING_INVALID_METADATA"
    assert SECRET not in json.dumps(result)


def test_tail_uses_numeric_order_and_retries_append_race(tmp_path, monkeypatch):
    first = write(tmp_path / "9.json", {"stage": "PREPARED"})
    second = write(tmp_path / "10.json", {"stage": "SOLVE_STARTED"})
    write(tmp_path / "private.json", {"secret": SECRET})
    assert health._latest(tmp_path) == second
    paths = iter((first, second, second, second))
    monkeypatch.setattr(health, "_latest", lambda _: next(paths))
    assert health._tail(tmp_path)[0]["stage"] == "SOLVE_STARTED"


def test_atomic_replacement_retry_and_bounded_failure(tmp_path, monkeypatch):
    path = write(tmp_path / "state.json", {"status": "RUNNING"})
    stamps = iter([(1, 1, 10, 1), (1, 2, 10, 2), (1, 2, 10, 2), (1, 2, 10, 2)])
    monkeypatch.setattr(health, "_stamp", lambda _: next(stamps))
    assert health._read(path)[0]["status"] == "RUNNING"
    n = iter(range(10))
    monkeypatch.setattr(health, "_stamp", lambda _: (1, next(n), 10, 1))
    with pytest.raises(health.ProbeError):
        health._read(path, 2)


def test_malformed_config_and_event_values_are_safe(scenario):
    path, config, _ = scenario
    write(Path(config["pipeline_root"]) / "events/1.json", {"stage": {"secret": SECRET}, "details": {"error_type": {"secret": SECRET}}})
    result = health.inspect_health(path, now=NOW)
    assert result["pipeline"]["stage"] == "UNKNOWN" and SECRET not in json.dumps(result)
    path.write_text('{"secret":')
    assert health.inspect_health(path, now=NOW)["status"] == "WARNING_INVALID_METADATA"


def test_idle_configuration_becomes_stale_and_limits_are_checked(scenario):
    path, _, _ = scenario
    os.utime(path, (NOW - 7200, NOW - 7200))
    assert health.inspect_health(path, now=NOW)["status"] == "WARNING_STALE"
    with pytest.raises(ValueError):
        health.inspect_health("relative.json", now=NOW)
    with pytest.raises(ValueError):
        health.inspect_health(path, now=NOW, stale_seconds=float("nan"))


def test_evaluation_broker_activity_prevents_false_stale_warning(scenario):
    path, config, _ = scenario
    run = Path(config["pipeline_root"]) / "development/baseline/run"
    active((path, config, run))
    write(Path(config["pipeline_root"]) / "events/1.json", {"stage": "COHORT_ADVANCE_STARTED", "at": NOW - 7200,
        "details": {"cohort_root": str(run / "cohort")}}, NOW - 7200)
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "PROGRESSING"
    assert result["evaluation_cohort"]["current"]["state"] == "ACTIVE"


def test_probe_ignores_unscoped_cohort_path_and_unknown_error_contents(scenario, tmp_path):
    path, config, _ = scenario
    outside = tmp_path / "outside"
    write(outside / "events/1.json", {"stage": "INFRA_ERROR", "at": NOW})
    write(Path(config["pipeline_root"]) / "events/1.json", {"stage": "PUBLISH_STARTED", "at": NOW - 5,
        "details": {"cohort_root": str(outside), "error_type": SECRET}})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "PROGRESSING" and result["evaluation_cohort"] is None
    assert result["pipeline"]["stage"] == "PUBLISH_STARTED" and SECRET not in json.dumps(result)


def test_invalid_database_reports_unknown_counts_instead_of_zero(scenario):
    path, config, _ = scenario
    root = Path(config["pipeline_root"]) / "learning-24"
    root.mkdir()
    with sqlite3.connect(root / "authority.sqlite3"):
        pass
    result = health.inspect_health(path, now=NOW)
    assert "DATABASE_BUSY_OR_INVALID" in result["warnings"]
    assert "L1_episodes" not in result["stages"][0]["learning"]


@pytest.mark.parametrize("status,workers,current,expected", [
    ("WAITING_HANDOFF", {}, None, "AWAITING_WORKER"),
    ("WAITING_HANDOFF", {"previous": {"status": "REVOKED"}}, None, "AWAITING_WORKER"),
    ("WAITING_ADMISSION", {"next": {"status": "ISSUED"}}, "next", "AWAITING_ADMISSION"),
])
def test_actual_raw_broker_handoff_and_admission_states_are_normal(scenario, status, workers, current, expected):
    path, _, _ = scenario
    cell = active(scenario)
    write(cell.parent / "broker/state.json", {"status": status, "workers": workers,
        "current_worker": current, "unfinished_actions": 0, "actions": 7})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "PROGRESSING" and result["warnings"] == []
    assert result["stages"][0]["cohort"]["current"]["state"] == expected


def test_actual_terminated_broker_warns_without_claiming_process_death(scenario):
    path, _, _ = scenario
    cell = active(scenario)
    write(cell.parent / "broker/state.json", {"status": "TERMINATED", "workers": {},
        "current_worker": None, "unfinished_actions": 0, "actions": 7})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "WARNING_INVALID_METADATA"
    assert result["warnings"] == ["BROKER_TERMINATED"]
    assert result["stages"][0]["cohort"]["current"]["state"] == "TERMINATED"
    assert result["process_liveness"] == "NOT_OBSERVED"


@pytest.mark.parametrize("pending", [0, 1])
def test_running_without_current_admitted_worker_is_unknown(scenario, pending):
    path, _, _ = scenario
    cell = active(scenario)
    write(cell.parent / "broker/state.json", {"status": "RUNNING", "workers": {"old": {"status": "ADMITTED"}},
        "current_worker": None, "unfinished_actions": pending, "actions": 7})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "WARNING_INVALID_METADATA"
    assert result["warnings"] == ["INVALID_BROKER_STATE"]
    assert result["stages"][0]["cohort"]["current"]["state"] == "UNKNOWN"


def test_local_bank_not_ready_does_not_mean_global_terminal_not_ready(scenario):
    path, config, _ = scenario
    write(Path(config["pipeline_root"]) / "events/1.json", {"stage": "BANK_NOT_READY", "job": "bank-24", "at": NOW - 5})
    result = health.inspect_health(path, now=NOW)
    assert result["pipeline"]["stage"] == "BANK_NOT_READY"
    assert result["status"] == "PROGRESSING"


def reference(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def continuation(scenario, tmp_path):
    path, config, _ = scenario
    previous_root = tmp_path / "previous-pipeline"
    run = previous_root / "development/baseline/run"
    tasks = [f"swebench--example__project-{i}" for i in range(1, 4)]
    cells = [run / "cells/EVALUATION" / task / "BASELINE/cell.json" for task in tasks]
    cohort = run / "cohort"
    experiment = write(run.parent / "execution.json", {"phase": "EVALUATION_RUNTIME"})
    manifest = write(cohort / "cohort.json", {"phase": "EVALUATION", "experiment_reference": reference(experiment), "schedule": [
        {"task_id": task, "arm": "BASELINE", "cell_config": str(cell), "ordinal": i}
        for i, (task, cell) in enumerate(zip(tasks, cells), 1)]})
    write(cohort / "events/00000001.json", {
        "stage": "CELL_COMPLETE", "task_id": tasks[0], "arm": "BASELINE", "ordinal": 1, "at": NOW - 120}, NOW - 120)
    held_tail = write(cohort / "events/00000002.json", {
        "stage": "INFRA_ERROR", "task_id": tasks[1], "arm": "BASELINE", "ordinal": 2,
        "at": NOW - 100, "details": {"reason": SECRET, "error_type": "GraderInvocationFailure"}}, NOW - 100)
    write(cohort / "events/00000003.json", {
        "stage": "SOLVE_STARTED", "task_id": tasks[2], "arm": "BASELINE", "ordinal": 3, "at": NOW - 10})
    write(cells[0].parent / "public-result.json", {
        "official": True, "grader_status": "success", "resolved": True,
        "task_id": tasks[0], "arm": "BASELINE"})
    write(cells[1].parent / "public-result.json", {
        "official": True, "grader_status": "undetermined", "resolved": None,
        "task_id": tasks[1], "arm": "BASELINE", "reason": SECRET})
    write(cells[2].parent / "broker/state.json", {
        "status": "RUNNING", "actions": 3, "unfinished_actions": 0,
        "current_worker": "worker", "workers": {"worker": {"status": "ADMITTED"}}})
    for stage in config["training_stages"][:2]:
        stage["learning_root"] = str(tmp_path / f"explicit-learning-{stage['size']}")
    previous = dict(config, pipeline_root=str(previous_root))
    previous_path = write(tmp_path / "previous-config.json", previous)
    amendment = {
        "schema": health.AMENDMENT_SCHEMA, "policy": health.CONTINUATION_POLICY,
        "previous_configuration_reference": reference(previous_path),
        "baseline_cohort_reference": reference(manifest),
        "baseline_event_tail_reference": reference(held_tail)}
    amendment_path = write(tmp_path / "amendment.json", amendment)
    config.update(schema=health.CONTINUATION_SCHEMA,
                  evaluation_continuation_reference=reference(amendment_path),
                  previous_configuration_reference=reference(previous_path))
    write(path, config)
    hold = {
        "schema": "skhynix/evaluation-grade-undetermined/1.0", "policy": health.CONTINUATION_POLICY,
        "amendment_reference": config["evaluation_continuation_reference"],
        "cohort_reference": reference(manifest), "experiment_reference": reference(experiment),
        "task_id": tasks[1], "arm": "BASELINE", "phase": "EVALUATION",
        "official": False, "resolved": None, "grader_status": "undetermined",
        "references": {"graded_error_event": reference(held_tail)}}
    hold_id = hashlib.sha256(json.dumps([reference(experiment), tasks[1], "BASELINE"],
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    hold_path = write(Path(config["pipeline_root"]) / "unscored" / (hold_id + ".json"), hold)
    event_path = write(Path(config["pipeline_root"]) / "events/00000001.json", {
        "stage": "COHORT_ADVANCE_STARTED", "at": NOW - 100,
        "details": {"cohort_root": str(cohort)}}, NOW - 100)
    learning = previous_root / "learning-240"
    write(learning / "learning-state.json", {"cells": {str(i): {} for i in range(240)}})
    write(learning / "catalog.json", {"captures": {str(i): {} for i in range(916)}, "skills": {"verified": {}}})
    with sqlite3.connect(learning / "authority.sqlite3") as db:
        db.executescript("CREATE TABLE memory_records(kind TEXT,revoked INT); CREATE TABLE knowledge_relations(source_id TEXT);")
        db.executemany("INSERT INTO memory_records VALUES(?,0)", [("episode",)] * 919 + [("skill",)])
    return {"scenario": scenario, "config": config, "amendment": amendment,
            "amendment_path": amendment_path, "previous_path": previous_path,
            "manifest_path": manifest, "tail_path": held_tail, "cohort": cohort,
            "event_path": event_path, "learning": learning, "hold_path": hold_path,
            "hold": hold, "experiment_path": experiment, "cells": cells}


def test_hash_bound_continuation_reads_only_retained_baseline_and_original_learning(continuation):
    path, _, _ = continuation["scenario"]
    before = (continuation["learning"] / "authority.sqlite3").read_bytes()
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "PROGRESSING" and result["warnings"] == []
    cohort = result["evaluation_cohort"]
    assert cohort["current"]["state"] == "ACTIVE"
    assert (cohort["planned"], cohort["completed"], cohort["official_complete"], cohort["resolved"]) == (3, 1, 1, 1)
    assert (cohort["undetermined"], cohort["processed"]) == (1, 2)
    assert cohort["last_event"]["task_id"] == "swebench--example__project-3"
    assert result["stages"][2]["learning"]["L1_episodes"] == 919
    assert result["stages"][2]["learning"]["L3_skills"] == 1
    assert before == (continuation["learning"] / "authority.sqlite3").read_bytes()
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("target", ["amendment_path", "previous_path", "manifest_path", "tail_path"])
def test_continuation_tampered_reference_never_redirects(continuation, target):
    path, _, _ = continuation["scenario"]
    target_path = continuation[target]
    target_path.write_bytes(target_path.read_bytes() + b" ")
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "WARNING_INVALID_METADATA"
    assert result["evaluation_cohort"] is None
    assert result["stages"][2]["learning"] == {}
    assert "INVALID_EVALUATION_CONTINUATION" in result["warnings"]
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("mutation", ["policy", "schema", "manifest_path", "tail_path", "previous_root", "previous_reference"])
def test_continuation_rejects_hash_valid_wrong_authority(continuation, mutation, tmp_path):
    path, config, _ = continuation["scenario"]
    amendment = continuation["amendment"]
    if mutation in {"policy", "schema"}:
        amendment[mutation] = SECRET
    elif mutation == "manifest_path":
        other = write(tmp_path / "outside/cohort.json", json.loads(continuation["manifest_path"].read_text()))
        amendment["baseline_cohort_reference"] = reference(other)
    elif mutation == "tail_path":
        other = write(tmp_path / "outside/events/2.json", {"stage": "INFRA_ERROR"})
        amendment["baseline_event_tail_reference"] = reference(other)
    elif mutation == "previous_reference":
        config["previous_configuration_reference"] = reference(continuation["manifest_path"])
    else:
        previous = json.loads(continuation["previous_path"].read_text())
        previous["pipeline_root"] = str(tmp_path / "unrelated")
        write(continuation["previous_path"], previous)
        amendment["previous_configuration_reference"] = reference(continuation["previous_path"])
        config["previous_configuration_reference"] = amendment["previous_configuration_reference"]
    write(continuation["amendment_path"], amendment)
    config["evaluation_continuation_reference"] = reference(continuation["amendment_path"])
    write(path, config)
    result = health.inspect_health(path, now=NOW)
    assert result["evaluation_cohort"] is None
    assert result["stages"][2]["learning"] == {}
    assert "INVALID_EVALUATION_CONTINUATION" in result["warnings"]
    assert SECRET not in json.dumps(result)


def test_continuation_does_not_inspect_unrelated_previous_cohort(continuation, monkeypatch):
    path, _, _ = continuation["scenario"]
    unrelated = continuation["cohort"].parents[1] / "bank-240/run/cohort"
    write(continuation["event_path"], {
        "stage": "COHORT_ADVANCE_STARTED", "at": NOW - 10, "details": {"cohort_root": str(unrelated)}})
    original = health._Probe.cohort
    def guarded(probe, root, **kwargs):
        assert Path(root) != unrelated
        return original(probe, root, **kwargs)
    monkeypatch.setattr(health._Probe, "cohort", guarded)
    result = health.inspect_health(path, now=NOW)
    assert result["evaluation_cohort"] is None
    assert "INVALID_EVALUATION_CONTINUATION" in result["warnings"]


@pytest.mark.parametrize("phase,arm", [("development", "PDF_MEMORY"), ("final", "BASELINE")])
def test_continuation_keeps_normal_new_root_evaluation_and_old_learning(continuation, phase, arm):
    path, config, _ = continuation["scenario"]
    run = Path(config["pipeline_root"]) / phase / "bank-240/run"
    cell = run / "cells/EVALUATION" / TASK / arm / "cell.json"
    write(run / "cohort/cohort.json", {"phase": "EVALUATION", "schedule": [
        {"task_id": TASK, "arm": arm, "cell_config": str(cell), "ordinal": 1}]})
    write(run / "cohort/events/1.json", {"stage": "PREPARE_STARTED", "task_id": TASK, "arm": arm, "ordinal": 1, "at": NOW - 10})
    write(continuation["event_path"], {
        "stage": "COHORT_ADVANCE_STARTED", "at": NOW - 10, "details": {"cohort_root": str(run / "cohort")}})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "PROGRESSING" and result["warnings"] == []
    assert result["evaluation_cohort"]["current"]["state"] == "PREPARING"
    assert result["stages"][2]["learning"]["L1_episodes"] == 919


def test_continuation_learning_fallback_requires_identical_stage_execution(continuation, tmp_path):
    path, config, _ = continuation["scenario"]
    execution = write(tmp_path / "changed-execution.json", {"run_root": str(tmp_path / "changed-run")})
    config["training_stages"][2]["execution_reference"] = {"path": str(execution)}
    write(path, config)
    result = health.inspect_health(path, now=NOW)
    assert result["stages"][2]["learning"] == {}
    assert "INVALID_EVALUATION_CONTINUATION" in result["warnings"]


def test_continuation_respects_explicit_learning_roots(continuation):
    path, config, _ = continuation["scenario"]
    explicit = Path(config["training_stages"][0]["learning_root"])
    write(explicit / "learning-state.json", {"cells": {"actual": {}}})
    result = health.inspect_health(path, now=NOW)
    assert result["stages"][0]["learning"]["cells"] == 1
    assert result["stages"][2]["learning"]["cells"] == 240


def test_old_pipeline_schema_cannot_enable_historical_redirect(continuation):
    path, config, _ = continuation["scenario"]
    config["schema"] = "skhynix/architecture-scale-pipeline/1.0"
    write(path, config)
    result = health.inspect_health(path, now=NOW)
    assert result["evaluation_cohort"] is None
    assert result["stages"][2]["learning"] == {}


@pytest.mark.parametrize("field,value", [
    ("schema", "other"), ("policy", "other"), ("official", True), ("resolved", False),
    ("grader_status", "success"), ("phase", "TRAINING"),
    ("task_id", "swebench--example__project-99"), ("arm", "PDF_MEMORY"),
    ("amendment_reference", {"path": "/other", "sha256": "0" * 64}),
    ("experiment_reference", {"path": "/other", "sha256": "0" * 64}),
])
def test_evaluation_hold_requires_exact_public_identity_and_unscored_status(continuation, field, value):
    path, _, _ = continuation["scenario"]
    proof = dict(continuation["hold"], **{field: value})
    write(continuation["hold_path"], proof)
    result = health.inspect_health(path, now=NOW)
    assert "INVALID_EVALUATION_ACCOUNTING" in result["warnings"]
    assert result["evaluation_cohort"]["completed"] is None
    assert result["evaluation_cohort"]["undetermined"] is None
    assert result["evaluation_cohort"]["official_complete"] == 1
    assert result["evaluation_cohort"]["resolved"] == 1


@pytest.mark.parametrize("target", ["cohort_hash", "error_hash", "experiment_bytes", "filename"])
def test_evaluation_hold_reference_and_filename_tamper_is_not_counted(continuation, target):
    path, _, _ = continuation["scenario"]
    proof = json.loads(continuation["hold_path"].read_text())
    if target == "cohort_hash":
        proof["cohort_reference"]["sha256"] = "0" * 64
    elif target == "error_hash":
        proof["references"]["graded_error_event"]["sha256"] = "0" * 64
    elif target == "experiment_bytes":
        p = continuation["experiment_path"]
        p.write_bytes(p.read_bytes() + b" ")
    else:
        continuation["hold_path"].rename(continuation["hold_path"].with_name("0" * 64 + ".json"))
    if target != "filename":
        write(continuation["hold_path"], proof)
    result = health.inspect_health(path, now=NOW)
    assert "INVALID_EVALUATION_ACCOUNTING" in result["warnings"]
    assert result["evaluation_cohort"]["undetermined"] is None
    assert result["evaluation_cohort"]["official_complete"] == 1


def test_missing_hold_still_counts_actual_completions_without_assuming_failure(continuation):
    path, _, _ = continuation["scenario"]
    continuation["hold_path"].unlink()
    result = health.inspect_health(path, now=NOW)
    cohort = result["evaluation_cohort"]
    assert cohort["completed"] == 1
    assert cohort["official_complete"] == 1 and cohort["resolved"] == 1
    assert cohort["undetermined"] is None and cohort["processed"] is None
    assert "MISSING_EVALUATION_HOLD_PROOF" in result["warnings"]


def test_finished_schedule_separates_official_completions_from_processed_holds(continuation):
    path, _, _ = continuation["scenario"]
    task = "swebench--example__project-3"
    write(continuation["cohort"] / "events/00000004.json", {
        "stage": "CELL_COMPLETE", "task_id": task, "arm": "BASELINE", "ordinal": 3, "at": NOW - 1})
    write(continuation["cells"][2].parent / "public-result.json", {
        "official": True, "grader_status": "success", "resolved": False, "task_id": task, "arm": "BASELINE"})
    write(continuation["event_path"], {
        "stage": "PIPELINE_COMPLETE_WITH_UNDETERMINED", "at": NOW - 1,
        "details": {"cohort_root": str(continuation["cohort"])}})
    result = health.inspect_health(path, now=NOW)
    assert result["status"] == "COMPLETE_WITH_UNDETERMINED"
    cohort = result["evaluation_cohort"]
    assert (cohort["planned"], cohort["completed"], cohort["undetermined"], cohort["processed"]) == (3, 2, 1, 3)
    assert (cohort["official_complete"], cohort["resolved"]) == (2, 1)


def test_duplicate_completion_is_not_double_counted(continuation):
    path, _, _ = continuation["scenario"]
    write(continuation["cohort"] / "events/00000004.json", {
        "stage": "CELL_COMPLETE", "task_id": TASK, "arm": "BASELINE", "ordinal": 1, "at": NOW - 1})
    result = health.inspect_health(path, now=NOW)
    assert "INVALID_EVALUATION_ACCOUNTING" in result["warnings"]
    assert result["evaluation_cohort"]["completed"] is None


def test_completed_cell_cannot_also_be_held(continuation):
    path, _, _ = continuation["scenario"]
    write(continuation["cohort"] / "events/00000004.json", {
        "stage": "CELL_COMPLETE", "task_id": "swebench--example__project-2", "arm": "BASELINE", "ordinal": 2, "at": NOW - 1})
    result = health.inspect_health(path, now=NOW)
    assert "INVALID_EVALUATION_ACCOUNTING" in result["warnings"]
    assert result["evaluation_cohort"]["undetermined"] is None


@pytest.fixture
def quota_continuation(continuation, tmp_path):
    path, config, _ = continuation["scenario"]
    previous_root = Path(config["pipeline_root"])
    root = tmp_path / "quota-pipeline"
    root.mkdir()
    run = continuation["cohort"].parent
    tasks = [f"swebench--example__project-{i}" for i in range(1, 61)]
    cells = [run / "cells/EVALUATION" / task / "BASELINE/cell.json" for task in tasks]
    native_root = tmp_path / "original-native"
    write(continuation["experiment_path"], {"phase": "EVALUATION_RUNTIME", "native_control_root": str(native_root)})
    experiment_ref = reference(continuation["experiment_path"])
    manifest = {"phase": "EVALUATION", "experiment_reference": experiment_ref, "schedule": [
        {"task_id": task, "arm": "BASELINE", "cell_config": str(cell), "ordinal": i}
        for i, (task, cell) in enumerate(zip(tasks, cells), 1)]}
    write(continuation["manifest_path"], manifest)
    continuation["amendment"]["baseline_cohort_reference"] = reference(continuation["manifest_path"])
    write(continuation["amendment_path"], continuation["amendment"])
    config["evaluation_continuation_reference"] = reference(continuation["amendment_path"])
    for ordinal in range(3, 17):
        write(continuation["cohort"] / f"events/{ordinal:08d}.json", {
            "stage": "CELL_COMPLETE", "task_id": tasks[ordinal - 1], "arm": "BASELINE", "ordinal": ordinal, "at": NOW - 20})
        write(cells[ordinal - 1].parent / "public-result.json", {
            "official": True, "grader_status": "success", "resolved": ordinal % 2 == 0,
            "task_id": tasks[ordinal - 1], "arm": "BASELINE"})
    hold = continuation["hold"]
    hold.update(amendment_reference=config["evaluation_continuation_reference"],
                cohort_reference=reference(continuation["manifest_path"]), experiment_reference=experiment_ref)
    continuation["hold_path"].unlink()
    hold_id = hashlib.sha256(json.dumps([experiment_ref, tasks[1], "BASELINE"],
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    grade_path = write(previous_root / "unscored" / (hold_id + ".json"), hold)
    v16 = write(tmp_path / "v16-config.json", config)
    failed_cell = cells[16]
    failure_event = write(continuation["cohort"] / "events/00000017.json", {
        "stage": "INFRA_ERROR", "task_id": tasks[16], "arm": "BASELINE", "ordinal": 17,
        "at": NOW - 10, "details": {"error_type": "RuntimeError", "reason": SECRET, "automatic_retry": False}})
    amendment = {
        "schema": health.QUOTA_AMENDMENT_SCHEMA, "policy": health.QUOTA_POLICY,
        "previous_configuration_reference": reference(v16),
        "baseline_cohort_reference": reference(continuation["manifest_path"]),
        "baseline_event_tail_reference": reference(failure_event)}
    amendment_path = write(tmp_path / "quota-amendment.json", amendment)
    config.update(schema=health.QUOTA_CONTINUATION_SCHEMA, pipeline_root=str(root),
                  native_quota_continuation_reference=reference(amendment_path),
                  supersedes_configuration_reference=reference(v16))
    write(path, config)
    event_path = write(root / "events/1.json", {
        "stage": "COHORT_ADVANCE_STARTED", "at": NOW - 5,
        "details": {"cohort_root": str(continuation["cohort"])}})
    instance_id = tasks[16].split("--", 1)[1]
    write(failed_cell, {"phase": "EVALUATION", "arm": "BASELINE",
        "task_public": {"task_id": tasks[16]}, "target": {"instance_id": instance_id}})
    audit = write(failed_cell.parent / "execution-audit.json", {"passed": False, "errors": [SECRET]})
    submission = write(failed_cell.parent / "broker/submission.json", {
        "agent_completed": False, "reason": "NATIVE_WORKER_INFRASTRUCTURE_FAILURE"})
    write(failed_cell.parent / "broker/state.json", {
        "status": "SUBMITTED", "workers": {}, "current_worker": None, "unfinished_actions": 0, "actions": 9})
    output = native_root / "EVALUATION" / instance_id / "BASELINE/worker-001/output"
    output.mkdir(parents=True)
    stream = output / "events.jsonl"
    stream.write_text(SECRET)
    completion = write(output / "completion.json", {
        "exit_code": 1, "events_sha256": reference(stream)["sha256"], "admitted": True, "timed_out": False,
        "thread_id": SECRET, "errors": [], "transport_errors": [], "outside_broker_tool_events": []})
    failure = write(failed_cell.parent / "native-execution-failure.json", {
        "launcher_returncode": 1, "completion_sha256": reference(completion)["sha256"]})
    native_proof = {
        "schema": health.QUOTA_HOLD_SCHEMA, "policy": health.QUOTA_POLICY,
        "amendment_reference": reference(amendment_path), "cohort_reference": reference(continuation["manifest_path"]),
        "experiment_reference": experiment_ref, "task_id": tasks[16], "arm": "BASELINE", "phase": "EVALUATION",
        "official": False, "resolved": None, "grader_status": "not_invoked", "native_status": "usage_limit",
        "classification": "NATIVE_SERVICE_USAGE_LIMIT", "reason": SECRET, "resources_retained": True,
        "model_calls": 0, "official_grader_runs": 0, "training_memory_writes": 0,
        "native_retries": False, "official_grader_retries": False,
        "references": {"cell": reference(failed_cell), "audit": reference(audit), "submission": reference(submission),
            "native_failure": reference(failure), "failed_event": reference(failure_event),
            "worker_001_completion": reference(completion), "worker_001_events": reference(stream)},
        "native_workers": [{"number": 1, "thread_id": SECRET, "completion_reference": reference(completion),
            "events_reference": reference(stream), "outcome": "NATIVE_SERVICE_USAGE_LIMIT",
            "completion_sha256": reference(completion)["sha256"], "events_sha256": reference(stream)["sha256"]}],
        "service_error_lines": [{"line": 1, "type": "error", "sha256": "a" * 64},
                                {"line": 2, "type": "turn.failed", "sha256": "b" * 64}]}
    native_id = hashlib.sha256(json.dumps([experiment_ref, tasks[16], "BASELINE"],
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    native_path = write(root / "native-quota-unscored" / (native_id + ".json"), native_proof)
    return {**continuation, "config": config, "quota_amendment": amendment, "quota_amendment_path": amendment_path,
            "v16_path": v16, "grade_path": grade_path, "native_path": native_path, "native_proof": native_proof,
            "failure_event": failure_event, "event_path": event_path, "stream": stream, "completion": completion,
            "failed_cell": failed_cell, "cells": cells}


def test_quota_counts_retained_baseline_and_original_learning_without_reading_native_text(quota_continuation, monkeypatch):
    fixture = quota_continuation
    original = Path.read_bytes
    def guarded(path):
        assert path != fixture["stream"]
        assert path.name not in {"grader-private.json", "prompt.txt", "events.jsonl"}
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", guarded)
    result = health.inspect_health(fixture["scenario"][0], now=NOW)
    assert result["warnings"] == [] and result["status"] == "PROGRESSING"
    cohort = result["evaluation_cohort"]
    assert (cohort["planned"], cohort["completed"], cohort["official_complete"]) == (60, 15, 15)
    assert (cohort["grader_undetermined"], cohort["native_infrastructure_undetermined"],
            cohort["undetermined"], cohort["processed"]) == (1, 1, 2, 17)
    assert cohort["resolved"] == 8 and cohort["current"]["state"] == "RETAINED_UNSCORED"
    assert result["stages"][2]["learning"]["cells"] == 240
    assert result["stages"][2]["learning"]["L1_episodes"] == 919
    assert SECRET not in json.dumps(result)


def test_quota_hold_does_not_hide_explicit_pipeline_block(quota_continuation):
    fixture = quota_continuation
    event = json.loads(fixture["event_path"].read_text())
    event["stage"] = "PIPELINE_BLOCKED"
    write(fixture["event_path"], event)
    result = health.inspect_health(fixture["scenario"][0], now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["evaluation_cohort"]["native_infrastructure_undetermined"] == 1


def test_quota_next_task_does_not_inflate_official_completions(quota_continuation):
    fixture = quota_continuation
    write(fixture["cohort"] / "events/00000018.json", {
        "stage": "PREPARE_STARTED", "task_id": "swebench--example__project-18", "arm": "BASELINE",
        "ordinal": 18, "at": NOW - 1})
    cohort = health.inspect_health(fixture["scenario"][0], now=NOW)["evaluation_cohort"]
    assert (cohort["completed"], cohort["official_complete"], cohort["undetermined"], cohort["processed"]) == (15, 15, 2, 17)
    assert cohort["current"]["state"] == "PREPARING"


@pytest.mark.parametrize("target", ["v16_path", "previous_path", "amendment_path", "quota_amendment_path", "failure_event"])
def test_quota_chain_tampering_never_redirects_historical_reads(quota_continuation, target):
    fixture = quota_continuation
    path = fixture[target]
    path.write_bytes(path.read_bytes() + b" ")
    result = health.inspect_health(fixture["scenario"][0], now=NOW)
    assert result["evaluation_cohort"] is None and result["stages"][2]["learning"] == {}
    assert "INVALID_EVALUATION_CONTINUATION" in result["warnings"]


@pytest.mark.parametrize("field,value", [
    ("schema", health.CONTINUATION_SCHEMA), ("policy", health.CONTINUATION_POLICY),
    ("official", True), ("resolved", False), ("grader_status", "success"), ("native_status", "complete"),
    ("classification", "OTHER_ERROR"), ("model_calls", False), ("native_retries", True),
    ("experiment_reference", {"path": "/other", "sha256": "0" * 64}),
    ("amendment_reference", {"path": "/other", "sha256": "0" * 64}),
])
def test_quota_invalid_hold_has_unknown_counts_instead_of_zero_or_failure(quota_continuation, field, value):
    fixture = quota_continuation
    write(fixture["native_path"], dict(fixture["native_proof"], **{field: value}))
    result = health.inspect_health(fixture["scenario"][0], now=NOW)
    cohort = result["evaluation_cohort"]
    assert "INVALID_EVALUATION_ACCOUNTING" in result["warnings"]
    assert cohort["official_complete"] == 15 and cohort["resolved"] == 8
    assert all(cohort[key] is None for key in (
        "completed", "grader_undetermined", "native_infrastructure_undetermined", "undetermined", "processed"))
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("target", ["completion", "stream_hash", "error_hash", "filename", "worker", "service_lines", "grader_result"])
def test_quota_native_metadata_conflicts_fail_closed(quota_continuation, target):
    fixture = quota_continuation
    proof = fixture["native_proof"]
    if target == "completion":
        fixture["completion"].write_bytes(fixture["completion"].read_bytes() + b" ")
    elif target == "stream_hash":
        proof["references"]["worker_001_events"]["sha256"] = "0" * 64
    elif target == "error_hash":
        proof["references"]["failed_event"]["sha256"] = "0" * 64
    elif target == "filename":
        fixture["native_path"].rename(fixture["native_path"].with_name("0" * 64 + ".json"))
    elif target == "worker":
        proof["native_workers"] = [SECRET]
    elif target == "service_lines":
        proof["service_error_lines"] = [{"line": 1, "type": "error", "sha256": "0" * 64}]
    else:
        write(fixture["failed_cell"].parent / "public-result.json", {"official": False, "resolved": None})
    if target != "filename":
        write(fixture["native_path"], proof)
    result = health.inspect_health(fixture["scenario"][0], now=NOW)
    assert "INVALID_EVALUATION_ACCOUNTING" in result["warnings"]
    assert result["evaluation_cohort"]["native_infrastructure_undetermined"] is None
    assert result["evaluation_cohort"]["official_complete"] == 15


@pytest.mark.parametrize("missing", ["native_path", "grade_path"])
def test_quota_missing_hold_does_not_claim_zero_undetermined(quota_continuation, missing):
    fixture = quota_continuation
    fixture[missing].unlink()
    result = health.inspect_health(fixture["scenario"][0], now=NOW)
    assert "MISSING_EVALUATION_HOLD_PROOF" in result["warnings"]
    cohort = result["evaluation_cohort"]
    assert cohort["completed"] == cohort["official_complete"] == 15
    assert all(cohort[key] is None for key in ("grader_undetermined", "native_infrastructure_undetermined", "undetermined", "processed"))
