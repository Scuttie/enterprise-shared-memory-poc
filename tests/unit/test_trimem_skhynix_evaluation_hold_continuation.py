"""Unscored evaluation accounting: real sealed native evidence, no new execution."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

import trimem_skhynix_evaluation_continuation as continuation
import trimem_skhynix_architecture_run as execution
from enterprise_memory.trimem.grader import GraderInvocationFailure
from test_trimem_skhynix_training_grade_hold import terminal_factory, write, mutate, TASK, INSTANCE


def result(task, resolved):
    return {"task_id": task, "official": resolved is not None, "resolved": resolved}


def test_counts_keep_unscored_outcomes_out_of_official_failures():
    rows = [result("yes", True), result("no", False), result("held", None)]
    counts = continuation.result_counts(rows, 3)
    assert (counts["official_complete"], counts["resolved"], counts["unresolved"], counts["undetermined"]) == (2, 1, 1, 1)
    assert counts["official_completed_solve_rate"] == 0.5
    assert counts["full_enrollment_solve_rate"] is None
    assert counts["full_enrollment_solve_rate_bounds"] == [1 / 3, 2 / 3]


def test_all_unscored_is_not_zero_percent_success():
    counts = continuation.result_counts([result("one", None), result("two", None)], 2)
    assert counts["official_complete"] == counts["unresolved"] == 0
    assert counts["official_completed_solve_rate"] is None
    assert counts["full_enrollment_solve_rate"] is None
    assert counts["full_enrollment_solve_rate_bounds"] == [0, 1]


@pytest.mark.parametrize("rows, planned", [
    ([result("one", True), result("one", False)], 2),
    ([result("one", True)], 2),
    ([{"task_id": "one", "official": False, "resolved": False}], 1),
    ([{"task_id": "one", "official": True, "resolved": None}], 1),
    ([{"task_id": "one", "official": 1, "resolved": True}], 1),
    ([{"task_id": "one", "official": True, "resolved": 1}], 1),
])
def test_counts_reject_missing_duplicate_or_fabricated_results(rows, planned):
    with pytest.raises((ValueError, RuntimeError)):
        continuation.result_counts(rows, planned)


def test_complete_pair_effect_and_full_enrollment_bounds_use_different_denominators():
    off = [result("a", True), result("b", None), result("c", False), result("d", True)]
    on = [result("a", False), result("b", True), result("c", True), result("d", None)]
    counts = continuation.paired_counts(off, on)
    assert (counts["planned_pairs"], counts["completed_pairs"], counts["missing_pairs"]) == (4, 2, 2)
    assert counts["baseline_resolved_on_complete_pairs"] == counts["memory_resolved_on_complete_pairs"] == 1
    assert counts["completed_pair_delta_percentage_points"] == 0
    assert counts["full_enrollment_delta_percentage_points"] is None
    assert counts["full_enrollment_delta_percentage_point_bounds"] == [-25, 25]


def test_all_complete_pairs_produce_the_original_fixed_denominator_delta():
    counts = continuation.paired_counts([result("a", False), result("b", True)],
        [result("a", True), result("b", True)])
    assert counts["completed_pairs"] == 2
    assert counts["completed_pair_delta_percentage_points"] == 50
    assert counts["full_enrollment_delta_percentage_points"] == 50
    assert counts["full_enrollment_delta_percentage_point_bounds"] == [50, 50]


def test_no_complete_pairs_have_no_measured_effect():
    counts = continuation.paired_counts([result("a", None)], [result("a", True)])
    assert counts["completed_pairs"] == 0
    assert counts["completed_pair_delta_percentage_points"] is None
    assert counts["full_enrollment_delta_percentage_points"] is None
    assert counts["full_enrollment_delta_percentage_point_bounds"] == [0, 100]


@pytest.mark.parametrize("off,on", [
    ([result("a", True)], [result("b", True)]),
    ([result("a", True), result("a", False)], [result("a", True)]),
    ([], []),
])
def test_pairs_never_compare_different_problem_sets(off, on):
    with pytest.raises((ValueError, RuntimeError)):
        continuation.paired_counts(off, on)


@pytest.fixture
def evaluation_hold_factory(terminal_factory, tmp_path, monkeypatch):
    """The native audit and broker are real; the cohort adapter validates its checksum."""
    serial = [0]

    def build(*, reason="no_tests_collected", budget=False):
        serial[0] += 1
        ctx = terminal_factory(phase="EVALUATION", policy=False, reason=reason, budget=budget)
        monkeypatch.setattr(execution, "open_cell", lambda *args, **kwargs: (ctx.cell, ctx.config, ctx.broker))
        for name in ("run_workers", "grade_cell"):
            monkeypatch.setattr(execution, name, lambda *args, **kwargs: pytest.fail("Hold validation must never run a worker or grader"))
        cohort = tmp_path / ("cohort-" + str(serial[0]))
        cohort.mkdir()
        config_ref = continuation.core.ref(ctx.config_path)
        row = {"ordinal": 16, "task_id": TASK, "arm": "PDF_MEMORY", "cell_config": str(ctx.cell_path), "target": ctx.cell["target"]}
        manifest = {"phase": "EVALUATION", "experiment_reference": config_ref, "bank_reference": None,
            "arms": ["PDF_MEMORY"], "schedule": [row], "min_free_bytes": 10}
        write(cohort / "cohort.json", manifest)
        events = [
            {"stage": "SOLVE_COMPLETE", "sequence": 1, "details": {"execution_audit_reference": continuation.core.ref(ctx.folder / "execution-audit.json")}},
            {"stage": "GRADE_STARTED", "sequence": 2, "details": {}},
            {"stage": "INFRA_ERROR", "sequence": 3, "details": {"error_type": "GraderInvocationFailure", "automatic_retry": False}},
        ]
        for event in events:
            write(cohort / "events" / f"{event['sequence']:08d}.json", event)

        def validate_cell(current):
            cell = execution.read(current["cell_config"])
            assert execution.digest(execution.canonical(cell)) == Path(current["cell_config"]).with_suffix(".sha256").read_text().strip()
            assert cell["phase"] == "EVALUATION" and cell["arm"] == current["arm"]
            assert cell["task_public"]["task_id"] == current["task_id"]
            return cell

        runner = SimpleNamespace(root=cohort, manifest=manifest, config=ctx.config, schedule=[row], operations=execution,
            _cell_events=lambda current: events, _validate_cell=validate_cell,
            _row_config=lambda current: ctx.config, _row_experiment_reference=lambda current: config_ref,
            _broker_status=lambda path: ctx.broker.status())
        amended = tmp_path / ("amendment-" + str(serial[0]) + ".json")
        amendment_ref = write(amended, {"schema": continuation.AMENDMENT_SCHEMA, "policy": continuation.POLICY})
        ctx.runner, ctx.row, ctx.events = runner, row, events
        ctx.output_root, ctx.amendment_ref = tmp_path / ("continuation-" + str(serial[0])), amendment_ref
        ctx.hold = continuation.hold_path(ctx.output_root, runner, row)
        return ctx

    return build


def retain(ctx, *, create=True):
    return continuation.retain_hold(ctx.output_root, ctx.runner, ctx.row, amendment_reference=ctx.amendment_ref, create=create)


@pytest.mark.parametrize("reason", ["no_tests_collected", "missing_module"])
@pytest.mark.parametrize("budget", [False, True])
def test_known_terminal_native_evidence_is_retained_unscored_without_retry(evaluation_hold_factory, reason, budget):
    ctx = evaluation_hold_factory(reason=reason, budget=budget)
    originals = {p: p.read_bytes() for p in ctx.root.rglob("*") if p.is_file()}
    assert retain(ctx, create=False) is None
    value, ref = retain(ctx)
    assert value["official"] is False and value["resolved"] is None
    assert value["classification"] == "AMBIGUOUS_" + reason.upper()
    assert value["resources_retained"] is True
    assert value["native_retries"] is value["official_grader_retries"] is False
    assert value["model_calls"] == value["official_grader_runs"] == value["training_memory_writes"] == 0
    assert ref == continuation.core.ref(ctx.hold)
    assert retain(ctx, create=False) == (value, ref)
    assert retain(ctx) == (value, ref)
    assert all(p.read_bytes() == b for p, b in originals.items())
    assert not (ctx.folder / "public-result.json").exists()
    assert not (ctx.folder / "training-grade-undetermined.json").exists()
    assert {e["stage"] for e in ctx.events} == {"SOLVE_COMPLETE", "GRADE_STARTED", "INFRA_ERROR"}


@pytest.mark.parametrize("changes", [
    {"schema_version": True}, {"completed_instances": 0}, {"submitted_instances": True},
    {"resolved_instances": 1}, {"infra_failure_instances": 1}, {"error_instances": 1},
    {"empty_patch_instances": 1}, {"unstopped_instances": 1},
    {"completed_ids": ["other__repo-1"]}, {"submitted_ids": []},
    {"incomplete_ids": [INSTANCE]}, {"unstopped_containers": ["still-running"]},
    {"failure_reasons": {"other__repo-1": "no_tests_collected"}},
])
def test_malformed_known_aggregate_never_authorizes_skipping(evaluation_hold_factory, changes):
    ctx = evaluation_hold_factory()
    mutate(ctx.report, **changes)
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


def test_unknown_terminal_error_remains_blocked(evaluation_hold_factory):
    ctx = evaluation_hold_factory(reason="unknown_grader_crash")
    assert retain(ctx) is None
    assert not ctx.hold.exists()


@pytest.mark.parametrize("filename", ["public-result.json", "grader-private.json", "native-execution-failure.json"])
def test_existing_grade_or_native_failure_cannot_be_reclassified(evaluation_hold_factory, filename):
    ctx = evaluation_hold_factory()
    (ctx.folder / filename).write_bytes(b"MUST NOT READ PRIVATE PAYLOAD")
    with pytest.raises((ValueError, RuntimeError), match="conflicts"):
        retain(ctx)
    assert not ctx.hold.exists()


@pytest.mark.parametrize("stage", ["GRADED", "GRADE_UNDETERMINED", "CELL_COMPLETE", "LEARNED", "CLEANED"])
def test_already_recorded_lifecycle_cannot_be_held(evaluation_hold_factory, stage):
    ctx = evaluation_hold_factory()
    ctx.events.append({"stage": stage, "details": {}})
    with pytest.raises((ValueError, RuntimeError), match="unscored"):
        retain(ctx)


def test_hold_requires_the_actual_grader_failure_not_generic_infrastructure_error(evaluation_hold_factory):
    ctx = evaluation_hold_factory()
    ctx.events[-1]["details"]["error_type"] = "OSError"
    with pytest.raises((ValueError, RuntimeError), match="grading ambiguity"):
        retain(ctx)


def test_missing_existing_audit_is_not_regenerated(evaluation_hold_factory, monkeypatch):
    ctx = evaluation_hold_factory()
    (ctx.folder / "execution-audit.json").unlink()
    monkeypatch.setattr(execution, "execution_audit", lambda *args: pytest.fail("Missing historical audit must not be regenerated"))
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        retain(ctx)
    assert not (ctx.folder / "execution-audit.json").exists()


@pytest.mark.parametrize("when", [float("nan"), float("inf"), float("-inf"), True])
def test_pending_timestamp_must_be_finite_and_real(evaluation_hold_factory, when):
    ctx = evaluation_hold_factory()
    path = ctx.folder / "grader-pending.json"
    value = execution.read(path)
    value["started_at"] = when
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


@pytest.mark.parametrize("target", ["aggregate", "patch", "pending", "audit", "completion", "native_events", "submission"])
def test_recorded_hold_rejects_changed_original_evidence(evaluation_hold_factory, target):
    ctx = evaluation_hold_factory()
    retain(ctx)
    paths = {"aggregate": ctx.report, "patch": ctx.folder / "broker/submission.diff",
        "pending": ctx.folder / "grader-pending.json", "audit": ctx.folder / "execution-audit.json",
        "completion": ctx.output / "completion.json", "native_events": ctx.output / "events.jsonl",
        "submission": ctx.folder / "broker/submission.json"}
    p = paths[target]
    p.write_bytes(p.read_bytes() + b" ")
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx, create=False)


def scheduling_runner(tmp_path, rows, history):
    root = tmp_path / "cohort"
    root.mkdir()
    for row in rows:
        row.setdefault("cell_config", str(tmp_path / "cells" / row["task_id"] / row["arm"] / "cell.json"))
    config_ref = write(tmp_path / "execution.json", {"run_root": str(tmp_path)})
    calls = []
    runner = SimpleNamespace(root=root, schedule=rows,
        config={"run_root": str(tmp_path)}, manifest={"experiment_reference": config_ref, "bank_reference": None, "min_free_bytes": 10},
        operations=SimpleNamespace(load_experiment=lambda path: calls.append("load")),
        _journal_snapshot=nullcontext, _check_execution_api=lambda: calls.append("execution-check"),
        _check_controller_source=lambda: calls.append("controller-check"),
        _cell_events=lambda row: history.get(row["task_id"] + ":" + row["arm"], []),
        disk_free=lambda path: 1000,
        _cleanup=lambda row: calls.append(("cleanup", row["task_id"], row["arm"])),
        _validate_result=lambda row: calls.append(("validate", row["task_id"], row["arm"])),
        _advance=lambda row: calls.append(("advance", row["task_id"], row["arm"])),
        _record=lambda stage, row, details: calls.append(("record", stage, row["task_id"], details)))
    return runner, calls


def test_existing_held_row_is_skipped_without_reexecuting_or_faking_completion(tmp_path, monkeypatch):
    rows = [{"task_id": "held", "arm": "BASELINE"}, {"task_id": "next", "arm": "BASELINE"}]
    runner, calls = scheduling_runner(tmp_path, rows, {})
    amendment = write(tmp_path / "amendment.json", {})
    proof_path = continuation.hold_path(tmp_path, runner, rows[0])
    write(proof_path, {"schema": continuation.HOLD_SCHEMA, "policy": continuation.POLICY,
        "phase": "EVALUATION", "official": False, "resolved": None,
        "task_id": "held", "arm": "BASELINE", "amendment_reference": amendment,
        "experiment_reference": runner.manifest["experiment_reference"], "references": {"execution": runner.manifest["experiment_reference"]}})
    monkeypatch.setattr(continuation, "retain_hold", lambda root, runner, row, **kwargs:
        ({"task_id": "held"}, continuation.core.ref(proof_path)) if row["task_id"] == "held" else None)
    outcome = continuation.advance_one(runner, root=tmp_path, amendment_reference=amendment)
    assert outcome == {"kind": "OFFICIAL", "task_id": "next", "arm": "BASELINE"}
    assert ("advance", "next", "BASELINE") in calls
    assert not any(isinstance(c, tuple) and c[0] in {"advance", "cleanup"} and c[1] == "held" for c in calls)
    assert not any(isinstance(c, tuple) and c[0] == "record" and c[1] in {"GRADED", "CELL_COMPLETE", "CLEANED"} for c in calls)


def test_non_grader_failure_stops_before_next_scheduled_task(tmp_path, monkeypatch):
    rows = [{"task_id": "first", "arm": "BASELINE"}, {"task_id": "next", "arm": "BASELINE"}]
    runner, calls = scheduling_runner(tmp_path, rows, {})
    monkeypatch.setattr(continuation, "retain_hold", lambda *args, **kwargs: None)
    def broken(row):
        calls.append(("advance", row["task_id"], row["arm"]))
        raise OSError("trusted infrastructure failure")
    runner._advance = broken
    with pytest.raises(OSError, match="trusted infrastructure"):
        continuation.advance_one(runner, root=tmp_path, amendment_reference={})
    assert ("advance", "next", "BASELINE") not in calls
    assert not any(isinstance(c, tuple) and c[0] == "cleanup" for c in calls)


def test_real_grader_exception_can_be_accounted_without_second_grade(tmp_path, monkeypatch):
    rows = [{"task_id": "one", "arm": "BASELINE"}]
    runner, calls = scheduling_runner(tmp_path, rows, {})
    def held(root, runner, row, *, create=False, **kwargs):
        return ({"resolved": None}, {"path": "retained-proof", "sha256": "h"}) if create else None
    monkeypatch.setattr(continuation, "retain_hold", held)
    def broken(row):
        calls.append(("grade", row["task_id"]))
        raise GraderInvocationFailure("one terminal ambiguous aggregate")
    runner._advance = broken
    outcome = continuation.advance_one(runner, root=tmp_path, amendment_reference={})
    assert outcome["kind"] == "HELD"
    assert calls.count(("grade", "one")) == 1
    assert not any(isinstance(c, tuple) and c[0] == "cleanup" for c in calls)


def test_disk_reserve_blocks_before_any_worker_or_grade(tmp_path, monkeypatch):
    runner, calls = scheduling_runner(tmp_path, [{"task_id": "one", "arm": "BASELINE"}], {})
    monkeypatch.setattr(continuation, "retain_hold", lambda *args, **kwargs: None)
    runner.disk_free = lambda path: 0
    with pytest.raises((ValueError, RuntimeError), match="storage"):
        continuation.advance_one(runner, root=tmp_path, amendment_reference={})
    assert not any(isinstance(c, tuple) and c[0] in {"advance", "cleanup"} for c in calls)


@pytest.mark.parametrize("already_complete", [False, True])
def test_held_task_retains_other_arm_resources_across_separate_cohorts(evaluation_hold_factory, tmp_path, monkeypatch, already_complete):
    ctx = evaluation_hold_factory()
    retain(ctx)
    rows = [{"task_id": TASK, "arm": "BASELINE"}, {"task_id": "next", "arm": "BASELINE"}]
    history = {TASK + ":BASELINE": [{"stage": "CELL_COMPLETE"}]} if already_complete else {}
    runner, calls = scheduling_runner(tmp_path, rows, history)
    outcome = continuation.advance_one(runner, root=ctx.output_root, amendment_reference=ctx.amendment_ref)
    assert ("cleanup", TASK, "BASELINE") not in calls
    expected_operation = "validate" if already_complete else "advance"
    assert (expected_operation, TASK, "BASELINE") in calls
    assert outcome["task_id"] == ("next" if already_complete else TASK)


def test_global_hold_evidence_change_blocks_new_work(evaluation_hold_factory, tmp_path):
    ctx = evaluation_hold_factory()
    retain(ctx)
    ctx.report.write_bytes(ctx.report.read_bytes() + b" ")
    runner, calls = scheduling_runner(tmp_path, [{"task_id": "next", "arm": "BASELINE"}], {})
    with pytest.raises((ValueError, RuntimeError), match="changed"):
        continuation.advance_one(runner, root=ctx.output_root, amendment_reference=ctx.amendment_ref)
    assert not any(isinstance(c, tuple) and c[0] in {"advance", "cleanup"} for c in calls)
