"""Cohort orchestration tests use public synthetic tasks and no model/grader process."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path[:0] = [str(Path(__file__).resolve().parents[2] / "src"),
                str(Path(__file__).resolve().parents[2] / "scripts")]
import trimem_skhynix_architecture_cohort as cohort


class FakeOperations:
    """Durable cell artifacts, with injected interruption at real stage boundaries."""

    def __init__(self, root):
        self.root = root
        self.calls = []
        self.fail_prepare = None
        self.fail_solve = None
        self.fail_grade = None
        self.audit_error = False
        self.elapsed = 0
        self.outcomes = {}
        targets = []
        for phase, count in (("TRAINING", 24), ("EVALUATION", 500)):
            for index in range(count):
                identity = f"{phase.lower()}-{index:03d}"
                targets.append({"target_id": identity, "instance_id": identity,
                    "repository": "synthetic/public", "base_commit": "a" * 40,
                    "instruction_sha256": cohort.sha(f"Public issue {identity}".encode()),
                    "role": phase, "order_index": index})
        dataset = root / "dataset.json"
        cohort.write(dataset, {"training_count": 24, "evaluation_count": 500, "targets": targets})
        self.config = {"dataset_manifest": cohort.reference(dataset), "run_root": str(root / "runs"),
            "native_control_root": str(root / "native"), "org_id": "org-fixture",
            "phase": "TRAINING_RUNTIME", "evaluation_status": "NOT_EVALUATION_READY",
            "exclusion_references": [{"path": "explicit-parent-preflight-receipt", "sha256": "e" * 64}]}
        self.experiment = root / "experiment.json"
        cohort.write(self.experiment, self.config)

    def load_experiment(self, path):
        assert Path(path) == self.experiment
        return deepcopy(self.config)

    def cell_path(self, task, arm):
        phase = "TRAINING" if task.startswith("training-") else "EVALUATION"
        return Path(self.config["run_root"]) / "cells" / phase / task / arm / "cell.json"

    def prepare_cell(self, experiment, task, arm, *, bank_reference=None):
        self.calls.append(("prepare", task, arm))
        path = self.cell_path(task, arm)
        if self.fail_prepare == "before":
            path.parent.mkdir(parents=True)
            raise RuntimeError("preparation interrupted before completed config")
        target = next(row for row in cohort.read(self.config["dataset_manifest"]["path"])["targets"]
                      if row["target_id"] == task)
        cell = {"phase": target["role"], "arm": arm, "experiment_config": str(self.experiment),
            "task_public": {"task_id": task, "repository": target["repository"],
                "commit": target["base_commit"], "instruction": f"Public issue {task}"},
            "broker_root": str(path.parent / "broker"), "bank_reference": bank_reference,
            "bank_sha256": bank_reference["sha256"] if bank_reference else cohort.execution.EMPTY_BANK_SHA}
        cohort.write(path, cell)
        path.with_suffix(".sha256").write_text(cohort.sha(cohort.canonical(cell)), encoding="ascii")
        cohort.write(path.parent / "broker" / "fixture-status.json", {
            "status": "WAITING_HANDOFF", "workers_issued": 0, "workers_admitted": 0,
            "event_tail_sha256": "1" * 64, "submission": None,
            "budget": {"requests_used": 0, "elapsed_seconds": 0}})
        if self.fail_prepare == "after":
            raise RuntimeError("preparation interrupted after durable config")
        return path

    def open_cell(self, path):
        owner = self

        class Broker:
            def status(self):
                status = cohort.read(Path(path).parent / "broker" / "fixture-status.json")
                owner.elapsed += 1
                status["budget"]["elapsed_seconds"] = owner.elapsed
                return status

        return cohort.read(path), deepcopy(self.config), Broker()

    def run_workers(self, path):
        cell = cohort.read(path)
        self.calls.append(("solve", cell["task_public"]["task_id"], cell["arm"]))
        status_path = Path(path).parent / "broker" / "fixture-status.json"
        status = cohort.read(status_path)
        status.update(workers_issued=1, workers_admitted=1)
        status["budget"]["requests_used"] = 9
        if self.fail_solve == "active":
            status["status"] = "WORKER_ACTIVE"
            cohort.write(status_path, status)
            raise RuntimeError("manager interrupted with admitted worker")
        patch = Path(path).parent / "broker" / "submission.diff"
        patch.write_bytes(b"synthetic sealed public diff\n")
        status.update(status="SUBMITTED", event_tail_sha256="2" * 64,
                      submission={"patch_sha256": cohort.sha(patch.read_bytes()), "reason": "SUBMIT"})
        cohort.write(status_path, status)
        if self.fail_solve == "after":
            raise RuntimeError("manager interrupted after sealed submission")
        return status

    def execution_audit(self, path):
        if self.audit_error:
            raise RuntimeError("native execution audit failed")
        status = self.open_cell(path)[2].status()
        assert status["status"] == "SUBMITTED"
        audit = {"passed": True, "errors": [], "event_tail_sha256": status["event_tail_sha256"],
                 "patch_sha256": status["submission"]["patch_sha256"]}
        audit_path = Path(path).parent / "execution-audit.json"
        if audit_path.exists():
            assert cohort.read(audit_path) == audit
        else:
            cohort.write(audit_path, audit)
        return audit

    def grade_cell(self, path):
        cell = cohort.read(path)
        identity = cell["task_public"]["task_id"]
        self.calls.append(("grade", identity, cell["arm"]))
        cohort.write(Path(path).parent / "grader-pending.json", {"started": True})
        if self.fail_grade == "before":
            raise RuntimeError("grader interrupted without public completion")
        self.execution_audit(path)
        status = self.open_cell(path)[2].status()
        result = {"task_id": identity, "arm": cell["arm"], "phase": cell["phase"],
            "official": True, "resolved": self.outcomes.get((identity, cell["arm"]), False),
            "grader_status": "success", "patch_sha256": status["submission"]["patch_sha256"],
            "event_tail_sha256": status["event_tail_sha256"],
            "experiment_sha256": cohort.sha(cohort.canonical(self.config)),
            "bank_sha256": cell["bank_sha256"], "broker_status": status,
            "execution_audit_sha256": cohort.reference(Path(path).parent / "execution-audit.json")["sha256"]}
        cohort.write(Path(path).parent / "public-result.json", result)
        if self.fail_grade == "after":
            raise RuntimeError("grader completed before manager interruption")
        return result


class EffortOperations(FakeOperations):
    """Use the cell's immutable experiment when creating public audit artifacts."""

    def load_experiment(self, path):
        return cohort.read(path)

    def prepare_cell(self, experiment, *args, **kwargs):
        original, original_path = self.config, self.experiment
        self.config, self.experiment = self.load_experiment(experiment), Path(experiment)
        try:
            return super().prepare_cell(experiment, *args, **kwargs)
        finally:
            self.config, self.experiment = original, original_path

    def grade_cell(self, path):
        original = self.config
        self.config = self.load_experiment(cohort.read(path)["experiment_config"])
        try:
            return super().grade_cell(path)
        finally:
            self.config = original


@pytest.fixture
def ops(tmp_path):
    return FakeOperations(tmp_path)


def make(ops, *, phase="TRAINING", full=False, **kwargs):
    if phase == "EVALUATION":
        ops.config.update(phase="EVALUATION_RUNTIME", evaluation_status="EVALUATION_READY")
        cohort.write(ops.experiment, ops.config)
    if phase == "EVALUATION" and "bank_reference" not in kwargs:
        bank = ops.root / "bank.json"
        cohort.write(bank, {"frozen": True})
        kwargs["bank_reference"] = cohort.reference(bank)
    return cohort.CohortRunner.create(ops.root / "cohort", experiment_path=ops.experiment, phase=phase,
        target_ids=None if full else [f"{phase.lower()}-000", f"{phase.lower()}-001"],
        operations=ops, bank_validator=lambda *_: {"L1_episodes": 1, "L2_nodes": 2, "L2_edges": 1, "L3_skills": 1},
        disk_free=lambda _: 10**15, clock=lambda: 1.0, **kwargs)


def reopen(ops, **kwargs):
    return cohort.CohortRunner(ops.root / "cohort", operations=ops, disk_free=lambda _: 10**15, **kwargs)


def counts(ops, stage):
    return sum(call[0] == stage for call in ops.calls)


def install_training_hold(ops, monkeypatch, *, policy=True, proof_available=True, budget_terminal=False):
    if policy:
        ops.config["training_grade_hold_policy"] = cohort.TRAINING_GRADE_HOLD_POLICY
        cohort.write(ops.experiment, ops.config)
    original_grade, original_workers = ops.grade_cell, ops.run_workers
    def workers(path):
        status = original_workers(path)
        if budget_terminal:
            status["submission"].update(agent_completed=False, reason="NATIVE_WORKER_WALL_LIMIT")
            cohort.write(Path(path).parent / "broker/fixture-status.json", status)
        return status
    def grade(path):
        cell = cohort.read(path)
        if cell["task_public"]["task_id"].endswith("-001"):
            return original_grade(path)
        ops.calls.append(("grade", cell["task_public"]["task_id"], cell["arm"]))
        cohort.write(Path(path).parent / "grader-pending.json", {"started": True})
        raise cohort.GraderInvocationFailure(None)
    def proof(path, *, create=False):
        outcome = Path(path).parent / "training-grade-undetermined.json"
        if outcome.exists():
            return cohort.read(outcome), cohort.reference(outcome)
        if not proof_available or not create:
            return None
        cell = cohort.read(path)
        status = cohort.read(Path(path).parent / "broker/fixture-status.json")
        payload = {"task_id": cell["task_public"]["task_id"], "arm": cell["arm"], "phase": cell["phase"],
            "official": False, "resolved": None, "official_outcome": "UNDETERMINED", "grader_status": "undetermined",
            "patch_sha256": status["submission"]["patch_sha256"], "event_tail_sha256": status["event_tail_sha256"],
            "experiment_sha256": cohort.sha(cohort.canonical(ops.config)), "bank_sha256": cell["bank_sha256"],
            "broker_status": status, "execution_audit_sha256": cohort.reference(Path(path).parent / "execution-audit.json")["sha256"]}
        cohort.write(outcome, payload)
        return payload, cohort.reference(outcome)
    monkeypatch.setattr(ops, "run_workers", workers)
    monkeypatch.setattr(ops, "grade_cell", grade)
    monkeypatch.setattr(ops, "training_grade_undetermined", proof, raising=False)


@pytest.mark.parametrize("budget_terminal", [False, True])
def test_training_ambiguous_grade_captures_and_cleans_then_advances_without_scoring_or_retry(ops, monkeypatch, budget_terminal):
    install_training_hold(ops, monkeypatch, budget_terminal=budget_terminal)
    ops.outcomes[("training-001", "PDF_MEMORY")] = True
    cleanup = FakeCleanup(ops)
    policy_path = ops.root / "cleanup-policy.json"
    cohort.write(policy_path, {"experiment_reference": cohort.reference(ops.experiment)})
    hook = synthetic_capture_hook(ops)
    runner = make(ops, learning_hook=hook, cleanup_operations=cleanup, cleanup_policy_reference=cohort.reference(policy_path))
    status = runner.run()
    assert status["status"] == "COMPLETE" and status["completed_cells"] == 2
    assert status["by_arm"]["PDF_MEMORY"] == {"planned": 2, "official_complete": 1, "resolved": 1,
        "infra_errors": 0, "missing": 0, "undetermined": 1, "completed_cell_solve_rate": 1.0, "full_enrollment_solve_rate": None}
    cell = ops.cell_path("training-000", "PDF_MEMORY")
    result = cohort.read(cell.parent / "training-grade-undetermined.json")
    assert result["resolved"] is None and result["official"] is False
    if budget_terminal:
        assert result["broker_status"]["submission"]["agent_completed"] is False
    assert not (cell.parent / "public-result.json").exists()
    assert len(cleanup.cleaned) == 2 and counts(ops, "grade") == 2 and counts(ops, "solve") == 2
    before = list(ops.calls)
    assert reopen(ops, learning_hook=hook, cleanup_operations=cleanup).run()["status"] == "COMPLETE"
    assert before == ops.calls


@pytest.mark.parametrize("policy,proof_available", [(False, True), (True, False)])
def test_unrecognized_or_unauthorized_training_hold_remains_blocked_without_retry(ops, monkeypatch, policy, proof_available):
    install_training_hold(ops, monkeypatch, policy=policy, proof_available=proof_available)
    runner = make(ops, learning_hook=synthetic_capture_hook(ops))
    assert runner.run()["status"] == "BLOCKED"
    assert runner.run()["status"] == "BLOCKED"
    assert counts(ops, "grade") == 1 and counts(ops, "solve") == 1
    assert not any(event["stage"] in {"LEARNED", "GRADE_UNDETERMINED"} for event in runner._events())


def test_existing_terminal_ambiguous_grade_is_captured_after_restart_without_regrading(ops, monkeypatch):
    install_training_hold(ops, monkeypatch, proof_available=False)
    hook = synthetic_capture_hook(ops)
    assert make(ops, learning_hook=hook).run()["status"] == "BLOCKED"
    install_training_hold(ops, monkeypatch, proof_available=True)
    assert reopen(ops, learning_hook=hook).run(cell_limit=1)["completed_cells"] == 1
    assert counts(ops, "grade") == 1 and counts(ops, "solve") == 1


def test_evaluation_rejects_training_hold_policy_before_any_task(ops, monkeypatch):
    install_training_hold(ops, monkeypatch)
    with pytest.raises(cohort.CohortError, match="training-only"):
        make(ops, phase="EVALUATION")
    assert ops.calls == []


def test_evaluation_ambiguous_grade_still_blocks_without_capture_or_policy(ops, monkeypatch):
    install_training_hold(ops, monkeypatch, policy=False)
    runner = make(ops, phase="EVALUATION", quarantine_hook=synthetic_capture_hook(ops, evaluation=True))
    status = runner.run()
    assert status["status"] == "BLOCKED" and status["completed_cells"] == 0
    assert status["paired_comparison"]["completed_pairs"] == 0
    assert not any(event["stage"] in {"LEARNED", "GRADE_UNDETERMINED"} for event in runner._events())


@pytest.mark.parametrize("phase,expected", [("TRAINING", 24), ("EVALUATION", 1000)])
def test_full_enrollment_and_cell_limit_preserve_frozen_population(ops, phase, expected):
    runner = make(ops, phase=phase, full=True)
    original = cohort.reference(runner.root / "cohort.json")
    assert len(runner.schedule) == expected
    status = runner.run(cell_limit=1)
    assert status["completed_cells"] == 1 and status["planned_cells"] == expected
    assert status["scope"] == "FULL_FIXED_COHORT"
    assert cohort.reference(runner.root / "cohort.json") == original
    assert all(value["full_enrollment_solve_rate"] is None for value in status["by_arm"].values())
    if phase == "EVALUATION":
        assert status["paired_comparison"]["completed_pairs"] == 0
        assert status["paired_comparison"]["full_cohort_delta_percentage_points"] is None


def test_resume_keeps_failed_solver_results_and_never_retries_completed_cells(ops):
    runner = make(ops)
    first = runner.run(cell_limit=1)
    retained = list((runner.root / "events").glob("*.json"))
    hashes = {path: cohort.reference(path) for path in retained}
    assert first["by_arm"]["PDF_MEMORY"]["resolved"] == 0
    second = reopen(ops).run()
    assert second["status"] == "COMPLETE"
    assert [call[1] for call in ops.calls if call[0] == "solve"] == ["training-000", "training-001"]
    assert counts(ops, "prepare") == counts(ops, "solve") == counts(ops, "grade") == 2
    assert second["by_arm"]["PDF_MEMORY"]["full_enrollment_solve_rate"] == 0
    assert {path: cohort.reference(path) for path in retained} == hashes
    reopen(ops).run()
    assert len(ops.calls) == 6


def test_only_paired_completed_official_results_contribute_to_lift(ops):
    ops.outcomes[("evaluation-000", "PDF_MEMORY")] = True
    ops.outcomes[("evaluation-001", "BASELINE")] = True
    runner = make(ops, phase="EVALUATION")
    partial = runner.run(cell_limit=3)
    paired = partial["paired_comparison"]
    assert paired["completed_pairs"] == 1 and paired["missing_pairs"] == 1
    assert paired["completed_pair_delta_percentage_points"] == 100
    assert paired["full_cohort_delta_percentage_points"] is None
    complete = reopen(ops).run()
    assert complete["paired_comparison"]["full_cohort_delta_percentage_points"] == 0
    assert [call[2] for call in ops.calls if call[0] == "solve"] == ["BASELINE", "PDF_MEMORY"] * 2
    assert complete["by_arm"]["BASELINE"]["full_enrollment_solve_rate"] == 0.5
    assert complete["by_arm"]["PDF_MEMORY"]["full_enrollment_solve_rate"] == 0.5


@pytest.mark.parametrize("stage", ["prepare", "grade"])
def test_ambiguous_interrupted_operation_is_not_retried(ops, stage):
    setattr(ops, f"fail_{stage}", "before")
    runner = make(ops)
    first = runner.run()
    assert first["status"] == "BLOCKED"
    assert first["by_arm"]["PDF_MEMORY"]["official_complete"] == 0
    assert first["by_arm"]["PDF_MEMORY"]["infra_errors"] == 1
    setattr(ops, f"fail_{stage}", None)
    again = reopen(ops).run()
    assert again["status"] == "BLOCKED" and counts(ops, stage) == 1
    assert again["completed_cells"] == 0


@pytest.mark.parametrize("stage", ["prepare", "solve", "grade"])
def test_durable_completion_can_be_recovered_without_reexecuting_stage(ops, stage):
    setattr(ops, f"fail_{stage}", "after")
    runner = make(ops)
    assert runner.run()["status"] == "BLOCKED"
    setattr(ops, f"fail_{stage}", None)
    recovered = reopen(ops).run(cell_limit=1)
    assert recovered["completed_cells"] == 1 and counts(ops, stage) == 1
    assert counts(ops, "prepare") == counts(ops, "solve") == counts(ops, "grade") == 1


def test_active_worker_is_never_replaced_on_resume(ops):
    ops.fail_solve = "active"
    runner = make(ops)
    assert runner.run()["status"] == "BLOCKED"
    ops.fail_solve = None
    result = reopen(ops).run()
    assert result["completed_cells"] == 0 and counts(ops, "solve") == 1
    assert counts(ops, "grade") == 0


def test_sealed_patch_with_failed_native_audit_cannot_be_graded_or_retried(ops):
    ops.audit_error = True
    runner = make(ops)
    first = runner.run()
    assert first["status"] == "BLOCKED"
    assert first["by_arm"]["PDF_MEMORY"]["official_complete"] == 0
    reopen(ops).run()
    assert counts(ops, "solve") == 1 and counts(ops, "grade") == 0


@pytest.mark.parametrize("receipt_valid", [False, True])
def test_subgoal_resume_requires_last_native_worker_completion_receipt(ops, receipt_valid):
    path = ops.prepare_cell(ops.experiment, "training-000", "PDF_MEMORY")
    status_path = path.parent / "broker" / "fixture-status.json"
    status = cohort.read(status_path)
    status.update(workers_issued=1, workers_admitted=1)
    cohort.write(status_path, status)
    if receipt_valid:
        receipt = Path(ops.config["native_control_root"]) / "TRAINING/training-000/PDF_MEMORY/worker-001/output/completion.json"
        raw = cohort.canonical({"type": "thread.started", "thread_id": "fixture-fresh-1"}) + b"\n"
        receipt.parent.mkdir(parents=True)
        (receipt.parent / "events.jsonl").write_bytes(raw)
        cohort.write(receipt, {"admitted": True, "errors": [], "outside_broker_tool_events": [],
            "timed_out": False, "exit_code": 0, "thread_id": "fixture-fresh-1", "events_sha256": cohort.sha(raw)})
    runner = make(ops, adopt_existing=[path])
    result = runner.run(cell_limit=1)
    assert result["completed_cells"] == int(receipt_valid)
    assert counts(ops, "solve") == int(receipt_valid)


def test_explicit_adoption_imports_audited_official_result_without_solver_or_grader(ops):
    path = ops.prepare_cell(ops.experiment, "training-000", "PDF_MEMORY")
    ops.run_workers(path)
    ops.grade_cell(path)
    ops.calls.clear()
    runner = make(ops, adopt_existing=[path])
    assert runner.run(cell_limit=1)["completed_cells"] == 1
    assert ops.calls == []
    assert runner._events()[0]["details"]["adopted_existing"] is True


def test_unregistered_existing_cell_requires_explicit_adoption(ops):
    ops.prepare_cell(ops.experiment, "training-000", "PDF_MEMORY")
    runner = make(ops)
    status = runner.run()
    assert status["status"] == "BLOCKED"
    assert "unregistered" in runner._events()[-1]["details"]["error"]
    assert counts(ops, "solve") == 0


@pytest.mark.parametrize("actual_actions", [0, 1])
def test_excluded_preflight_requires_actual_zero_actions_in_separate_directory(ops, actual_actions):
    old = ops.root / "old-run/cell"
    cohort.write(old / "broker/state.json", {"actions": actual_actions})
    receipt = ops.root / "outside.json"
    cohort.write(receipt, {"schema": "skhynix/architecture-outside-cohort/1.0",
        "classification": "PREFLIGHT_ABORTED_ZERO_ACTION", "actions": 0,
        "reason": "transport failed before any benchmark action", "cell_root": str(old)})
    if actual_actions:
        with pytest.raises(cohort.CohortError, match="actual solver actions"):
            make(ops, outside_cohort=[receipt])
    else:
        status = make(ops, outside_cohort=[receipt]).status()
        assert status["outside_cohort_trials"] == 1
        assert status["execution_config_exclusion_references"] == ops.config["exclusion_references"]
        assert status["completed_cells"] == 0


def test_learning_hook_is_separate_and_recovers_durable_mirror_without_second_capture(ops):
    calls = []

    def hook(cell, public_result, receipt_directory):
        calls.append(str(cell))
        receipt = ops.root / "captured-learning.json"
        cohort.write(receipt, {"schema": "skhynix/native-architecture-learning/1.0",
            "operation": "CAPTURE_CELL", "cell_path": str(cell),
            "task_id": cohort.read(cell)["task_public"]["task_id"],
            "source_references": {"cell.json": cohort.reference(cell)},
            "status": "CAPTURED", "failures": []})
        ref = cohort.reference(receipt)
        cohort.write(receipt_directory / "learning-capture.json", {
            "schema": "skhynix/native-architecture-learning/1.0", "operation": "COHORT_CAPTURE", "capture_receipt": ref})
        raise RuntimeError("capture durably completed before manager interruption")

    runner = make(ops, learning_hook=hook)
    assert runner.run()["status"] == "BLOCKED"
    result = reopen(ops, learning_hook=hook).run(cell_limit=1)
    assert result["completed_cells"] == 1 and len(calls) == 1
    assert counts(ops, "solve") == counts(ops, "grade") == 1
    assert any(event["stage"] == "LEARNED" and event["details"].get("recovered_durable_capture")
               for event in runner._events())


def test_learning_interruption_without_receipt_never_recaptures(ops):
    calls = []

    def hook(*_):
        calls.append(True)
        raise RuntimeError("capture interrupted")

    runner = make(ops, learning_hook=hook)
    assert runner.run()["status"] == "BLOCKED"
    assert reopen(ops, learning_hook=hook).run()["status"] == "BLOCKED"
    assert len(calls) == 1


def test_evaluation_disallows_bank_changes_or_training_capture(ops):
    with pytest.raises(cohort.CohortError, match="requires a frozen"):
        make(ops, phase="EVALUATION", bank_reference=None)
    with pytest.raises(cohort.CohortError, match="cannot update"):
        make(ops, phase="EVALUATION", learning_hook=lambda *_: None)
    runner = make(ops, phase="EVALUATION")
    Path(runner.manifest["bank_reference"]["path"]).write_bytes(b"{}")
    with pytest.raises(cohort.CohortError, match="reference changed"):
        runner.run()
    assert ops.calls == []


def test_disk_block_happens_before_preparation_and_retains_files(ops):
    runner = make(ops)
    runner.disk_free = lambda _: 0
    status = runner.run()
    assert status["status"] == "BLOCKED" and ops.calls == []
    assert runner._events()[-1]["details"]["operation_started"] is False
    assert "RETAIN_ALL" in status["cleanup_policy"]
    assert (runner.root / "cohort.json").is_file()


def test_event_chain_and_frozen_definition_tampering_fail_closed(ops):
    runner = make(ops)
    runner.run(cell_limit=1)
    event_path = runner.root / "events/00000001.json"
    event = cohort.read(event_path)
    event["task_id"] = "foreign"
    cohort.write(event_path, event)
    with pytest.raises(cohort.CohortError, match="event chain changed"):
        runner.status()
    definition = cohort.read(runner.root / "cohort.json")
    definition["outcome_retries"] = True
    cohort.write(runner.root / "cohort.json", definition)
    with pytest.raises(cohort.CohortError, match="definition changed"):
        reopen(ops)


def test_frozen_execution_api_hash_is_checked_before_any_operation(ops):
    fake_source = ops.root / "runtime.py"
    fake_source.write_text("frozen code", encoding="utf-8")
    ops.__file__ = str(fake_source)
    ops.config["source_sha256"] = {"scripts/trimem_skhynix_architecture_run.py": cohort.sha(fake_source.read_bytes())}
    cohort.write(ops.experiment, ops.config)
    runner = make(ops)
    fake_source.write_text("changed code", encoding="utf-8")
    with pytest.raises(cohort.CohortError, match="frozen runtime source"):
        runner.run()
    assert ops.calls == []


@pytest.mark.parametrize("field,value", [("official", False), ("resolved", 1),
    ("task_id", "foreign"), ("arm", "BASELINE"), ("bank_sha256", "f" * 64),
    ("execution_audit_sha256", "f" * 64)])
def test_adopted_public_results_require_exact_identity_official_boolean_and_audit(ops, field, value):
    path = ops.prepare_cell(ops.experiment, "training-000", "PDF_MEMORY")
    ops.run_workers(path)
    ops.grade_cell(path)
    result_path = path.parent / "public-result.json"
    result = cohort.read(result_path)
    result[field] = value
    cohort.write(result_path, result)
    runner = make(ops, adopt_existing=[path])
    status = runner.run(cell_limit=1)
    assert status["status"] == "BLOCKED" and status["completed_cells"] == 0
    assert status["by_arm"]["PDF_MEMORY"]["official_complete"] == 0
    assert counts(ops, "grade") == 1


def test_original_result_and_patch_remain_bound_after_completion(ops):
    runner = make(ops)
    runner.run(cell_limit=1)
    path = Path(runner.schedule[0]["cell_config"]).parent / "broker/submission.diff"
    path.write_bytes(b"modified after official grading")
    with pytest.raises(cohort.CohortError, match="sealed patch"):
        runner.status()


def synthetic_capture_hook(ops, *, evaluation=False, capture_status=None):
    def hook(cell_path, result, receipt_directory):
        cell = cohort.read(cell_path)
        schema = "skhynix/architecture-evaluation-capture/1.0" if evaluation else "skhynix/native-architecture-learning/1.0"
        status = capture_status or ("BASELINE_AUDIT_ONLY" if evaluation and cell["arm"] == "BASELINE" else "NO_PUBLIC_ATTEMPTS")
        inner = {"schema": schema, "operation": "CAPTURE_EVALUATION_CELL" if evaluation else "CAPTURE_CELL",
            "cell_path": str(cell_path), "task_id": cell["task_public"]["task_id"],
            "source_references": {"cell.json": cohort.reference(cell_path)}, "status": status, "failures": []}
        if evaluation:
            inner.update(arm=cell["arm"], bank_sha256=cell["bank_sha256"], admitted_to_frozen_bank=False,
                         quarantine_references=[])
        capture_path = receipt_directory / "inner.json"
        cohort.write(capture_path, inner)
        mirror = receipt_directory / "learning-capture.json"
        cohort.write(mirror, {"schema": schema, "operation": "COHORT_CAPTURE", "capture_receipt": cohort.reference(capture_path)})
        return cohort.reference(mirror)

    return hook


@pytest.mark.parametrize("status", ["CAPTURED", "NO_PUBLIC_ATTEMPTS", "PARTIAL_CAPTURE_FAILURE", "INVALID_SOURCE"])
def test_actual_capture_status_is_preserved_and_failed_capture_never_retried(ops, status):
    hook = synthetic_capture_hook(ops, capture_status=status)
    runner = make(ops, learning_hook=hook)
    result = runner.run(cell_limit=1)
    success = status in {"CAPTURED", "NO_PUBLIC_ATTEMPTS"}
    assert result["completed_cells"] == int(success)
    if success:
        event = next(event for event in runner._events() if event["stage"] == "LEARNED")
        assert event["details"]["capture_status"] == status
    else:
        assert result["status"] == "BLOCKED"
        before = list(ops.calls)
        assert reopen(ops, learning_hook=hook).run()["status"] == "BLOCKED"
        assert ops.calls == before


def test_real_learning_hook_mirror_is_compatible_with_cohort(ops, monkeypatch):
    import trimem_skhynix_architecture_learning as learning
    synthetic = synthetic_capture_hook(ops)

    def capture_cell(root, cell):
        mirror_ref = synthetic(cell, {}, ops.root / "capture-source")
        return cohort.checked(mirror_ref)["capture_receipt"]

    monkeypatch.setattr(learning, "capture_cell", capture_cell)
    runner = make(ops, learning_hook=learning.make_capture_hook(ops.root / "learning"))
    result = runner.run(cell_limit=1)
    assert result["completed_cells"] == 1
    learned = next(event for event in runner._events() if event["stage"] == "LEARNED")
    assert learned["details"]["capture_status"] == "NO_PUBLIC_ATTEMPTS"


def test_evaluation_quarantine_is_separate_and_baseline_has_only_audit_receipt(ops):
    hook = synthetic_capture_hook(ops, evaluation=True)
    runner = make(ops, phase="EVALUATION", quarantine_hook=hook)
    bank_before = cohort.reference(runner.manifest["bank_reference"]["path"])
    status = runner.run(cell_limit=2)
    assert status["capture_mode"] == "SEPARATE_EVALUATION_QUARANTINE"
    assert status["frozen_evaluation_bank_updates"] is False
    assert runner.manifest["learning_enabled"] is False
    learned = [event for event in runner._events() if event["stage"] == "LEARNED"]
    assert [event["details"]["capture_status"] for event in learned] == ["BASELINE_AUDIT_ONLY", "NO_PUBLIC_ATTEMPTS"]
    assert cohort.reference(runner.manifest["bank_reference"]["path"]) == bank_before


class FakeCleanup:
    def __init__(self, ops):
        self.ops, self.registered, self.cleaned = ops, {}, set()
        original_open = ops.open_cell

        def open_cell(path):
            if str(path) in self.cleaned:
                raise FileNotFoundError("completed checkout was removed")
            return original_open(path)

        ops.open_cell = open_cell

    def cleanup_completed_cell(self, cell, result, capture, *, policy_reference):
        value = cohort.read(cell)
        task, arm = value["task_public"]["task_id"], value["arm"]
        self.registered[(task, arm)] = (cell, result, capture)
        required = ("PDF_MEMORY",) if value["phase"] == "TRAINING" else ("BASELINE", "PDF_MEMORY")
        if any((task, name) not in self.registered for name in required):
            return {"status": "WAITING_FOR_PAIRED_COMPLETION", "cleanup_reference": None}
        folder = Path(self.ops.config["run_root"]) / "cleanup" / task
        for name in required:
            self.cleaned.add(str(self.registered[(task, name)][0]))
        receipt_path = folder / "completion.json"
        cohort.write(receipt_path, {"status": "COMPLETE", "task_id": task})
        ref = cohort.reference(receipt_path)
        cohort.write(folder / "completion.ref.json", ref)
        return {"status": "COMPLETE", "cleanup_reference": ref}

    def validate_completed_cleanup(self, cell, result, capture=None):
        value = cohort.read(cell)
        assert self.registered[(value["task_public"]["task_id"], value["arm"])] == (cell, result, capture)
        public = cohort.checked(result)
        cohort.checked(capture)
        return {"broker_status": public["broker_status"]}


@pytest.mark.parametrize("phase", ["TRAINING", "EVALUATION"])
def test_optional_cleanup_retains_status_and_never_reopens_deleted_checkouts(ops, phase):
    cleanup = FakeCleanup(ops)
    if phase == "EVALUATION":
        ops.config.update(phase="EVALUATION_RUNTIME", evaluation_status="EVALUATION_READY")
        cohort.write(ops.experiment, ops.config)
    policy_path = ops.root / "cleanup-policy.json"
    cohort.write(policy_path, {"experiment_reference": cohort.reference(ops.experiment)})
    hook = synthetic_capture_hook(ops, evaluation=phase == "EVALUATION")
    hook_options = {"learning_hook": hook} if phase == "TRAINING" else {"quarantine_hook": hook}
    runner = make(ops, phase=phase, cleanup_policy_reference=cohort.reference(policy_path),
                  cleanup_operations=cleanup, **hook_options)
    status = runner.run()
    assert status["status"] == "COMPLETE"
    assert len(cleanup.cleaned) == (2 if phase == "TRAINING" else 4)
    before = list(ops.calls)
    resumed = reopen(ops, cleanup_operations=cleanup, **hook_options).run()
    assert resumed["status"] == "COMPLETE" and ops.calls == before
    assert len([event for event in runner._events() if event["stage"] == "CLEANED"]) == len(cleanup.cleaned)
    assert all((Path(cell).parent / "broker/submission.diff").exists() for cell in cleanup.cleaned)


def test_cleanup_requires_capture_and_exact_execution_policy(ops):
    policy = ops.root / "cleanup-policy.json"
    cohort.write(policy, {"experiment_reference": cohort.reference(ops.experiment)})
    with pytest.raises(cohort.CohortError, match="post-grade capture"):
        make(ops, cleanup_policy_reference=cohort.reference(policy), cleanup_operations=FakeCleanup(ops))
    cohort.write(policy, {"experiment_reference": {"path": str(ops.experiment), "sha256": "a" * 64}})
    with pytest.raises(cohort.CohortError, match="cleanup policy differs"):
        make(ops, cleanup_policy_reference=cohort.reference(policy), learning_hook=lambda *_: None)


def test_wsl_storage_reserve_checks_physical_windows_volume(monkeypatch, tmp_path):
    original_is_dir = Path.is_dir
    monkeypatch.setattr(Path, "is_dir", lambda path: True if str(path) == "/mnt/c" else original_is_dir(path))
    monkeypatch.setattr(cohort.shutil, "disk_usage", lambda path: SimpleNamespace(free=7 if str(path) == "/mnt/c" else 10**15))
    assert cohort.available_storage_bytes(tmp_path) == 7


@pytest.mark.parametrize("mutation", ["transport", "event_hash", "manager_error", "outside_tool"])
def test_subgoal_resume_rejects_tampered_or_failed_native_transport(ops, mutation):
    path = ops.prepare_cell(ops.experiment, "training-000", "PDF_MEMORY")
    status_path = path.parent / "broker/fixture-status.json"
    status = cohort.read(status_path)
    status.update(workers_issued=1, workers_admitted=1)
    cohort.write(status_path, status)
    output = Path(ops.config["native_control_root"]) / "TRAINING/training-000/PDF_MEMORY/worker-001/output"
    output.mkdir(parents=True)
    events = [{"type": "thread.started", "thread_id": "thread-1"}]
    if mutation == "outside_tool":
        events.append({"type": "item.completed", "item": {"type": "command_execution"}})
    raw = b"\n".join(cohort.canonical(event) for event in events) + b"\n"
    (output / "events.jsonl").write_bytes(raw)
    receipt = {"admitted": True, "errors": [], "outside_broker_tool_events": [], "timed_out": False,
        "exit_code": 0, "thread_id": "thread-1", "events_sha256": cohort.sha(raw)}
    if mutation == "transport":
        receipt["transport_errors"] = ["MCP rejected"]
    if mutation == "event_hash":
        receipt["events_sha256"] = "f" * 64
    if mutation == "manager_error":
        cohort.write(output / "manager-error-action.json", {"error": "manager request rejected"})
    cohort.write(output / "completion.json", receipt)
    runner = make(ops, adopt_existing=[path])
    result = runner.run(cell_limit=1)
    assert result["status"] == "BLOCKED" and counts(ops, "solve") == 0


@pytest.mark.parametrize("phase,readiness", [("TRAINING_RUNTIME", "EVALUATION_READY"),
    ("EVALUATION_RUNTIME", "NOT_EVALUATION_READY")])
def test_training_or_unready_config_cannot_start_evaluation(ops, phase, readiness):
    ops.config.update(phase=phase, evaluation_status=readiness)
    cohort.write(ops.experiment, ops.config)
    with pytest.raises(cohort.CohortError, match="configuration phase|EVALUATION_READY"):
        cohort.CohortRunner.create(ops.root / "cohort", experiment_path=ops.experiment,
                                  phase="EVALUATION", operations=ops)
    assert ops.calls == []


def test_adopted_cell_cannot_replace_the_frozen_cold_start_bank_identity(ops):
    path = ops.prepare_cell(ops.experiment, "training-000", "PDF_MEMORY")
    cell = cohort.read(path)
    cell["bank_sha256"] = "f" * 64
    cohort.write(path, cell)
    path.with_suffix(".sha256").write_text(cohort.sha(cohort.canonical(cell)), encoding="ascii")
    with pytest.raises(cohort.CohortError, match="bank differs"):
        make(ops, adopt_existing=[path])


@pytest.fixture
def real_cleanup_case(tmp_path, monkeypatch):
    """Reuse the actual cleanup fixtures and helper; simulate only OS removals."""
    import test_trimem_skhynix_architecture_cleanup as fixtures
    import trimem_skhynix_architecture_cleanup as cleanup
    original_write = fixtures.write

    def enrolled_write(path, value):
        if Path(path).name == "execution.json":
            value.update(phase="TRAINING_RUNTIME", org_id="fixture-org")
        if Path(path).name == "dataset.json":
            for number, target in enumerate(value["targets"]):
                target["order_index"] = number
        if Path(path).name == "cell.json":
            value["bank_reference"] = None
        return original_write(path, value)

    monkeypatch.setattr(fixtures, "write", enrolled_write)
    monkeypatch.setattr(cohort.execution, "EMPTY_BANK_SHA", "d" * 64)
    value = fixtures.factory.__wrapped__(tmp_path, monkeypatch)()
    absent, removal_calls = fixtures.simulated_removal.__wrapped__(monkeypatch)
    inspector = cohort._inspect_absent_owned_image
    monkeypatch.setattr(cohort, "_inspect_absent_owned_image", lambda image: None)
    item = value["cells"]["PDF_MEMORY"]
    calls = []

    def open_cell(path):
        calls.append("open")
        if str(item["checkout"]) in absent:
            pytest.fail("Controller reopened a checkout already removed under immutable intent")
        return cohort.read(path), value["config"], SimpleNamespace(status=lambda: deepcopy(item["result"]["broker_status"]))

    def capture(path, result, directory):
        mirror = Path(directory) / "learning-capture.json"
        cohort.write(mirror, {"schema": "skhynix/native-architecture-learning/1.0", "operation": "COHORT_CAPTURE",
            "capture_receipt": item["registration"]["capture_reference"]})
        return cohort.reference(mirror)

    operations = SimpleNamespace(load_experiment=cohort.read, open_cell=open_cell,
        execution_audit=lambda path: cohort.read(Path(path).parent / "execution-audit.json"),
        run_workers=lambda *_: pytest.fail("Native execution must not be repeated"),
        grade_cell=lambda *_: pytest.fail("Official grading must not be repeated"))
    runner = cohort.CohortRunner.create(tmp_path / "cohort", experiment_path=value["root"] / "execution.json",
        phase="TRAINING", target_ids=[value["target"]["target_id"]], operations=operations,
        cleanup_policy_reference=value["policy"], cleanup_operations=cleanup, learning_hook=capture,
        adopt_existing=[item["path"]], disk_free=lambda _: 10**15)
    return SimpleNamespace(value=value, item=item, cleanup=cleanup, runner=runner, calls=calls,
        absent=absent, removal_calls=removal_calls, operations=operations, capture=capture, inspector=inspector)


def test_real_partial_cleanup_status_uses_retained_intent_and_explicit_retry_never_reopens_checkout(real_cleanup_case, monkeypatch):
    case = real_cleanup_case
    monkeypatch.setattr(case.cleanup, "_release_owned_images", lambda owned: [{"image": image, "removed": False} for image in owned])
    status = case.runner.run(cell_limit=1)
    assert status["status"] == "BLOCKED" and status["completed_cells"] == 1
    assert status["cleanup_pending_cells"] == 1 and status["cells"][0]["cleanup_state"] == "PENDING"
    folder = case.value["root"] / "cleanup" / case.value["target"]["target_id"]
    attempt = cohort.reference(folder / "attempt-0001.json")
    assert cohort.checked(attempt)["status"] == "INCOMPLETE_IMAGE_RELEASE"
    assert not (folder / "completion.ref.json").exists()
    assert str(case.item["checkout"]) in case.absent
    opened = list(case.calls)
    assert case.runner.status()["cleanup_pending_cells"] == 1 and case.calls == opened
    monkeypatch.setattr(case.cleanup, "cleanup_completed_cell", lambda *a, **k: pytest.fail("Pending cleanup must not reenter the deletion helper"))
    monkeypatch.setattr(cohort, "_inspect_absent_owned_image", case.inspector)
    monkeypatch.setattr(cohort.subprocess, "run", lambda argv, **kw: SimpleNamespace(returncode=1, stdout="[]\n",
        stderr="Error response from daemon: No such image: " + argv[-1] + "\n"))
    resumed = cohort.CohortRunner(case.runner.root, operations=case.operations,
        cleanup_operations=case.cleanup, learning_hook=case.capture, disk_free=lambda _: 10**15).run(cell_limit=1)
    assert resumed["status"] == "COMPLETE" and resumed["cleanup_pending_cells"] == 0
    assert resumed["cells"][0]["cleanup_state"] == "COMPLETE" and case.calls == opened
    assert cohort.reference(attempt["path"]) == attempt
    assert cohort.checked(cohort.read(folder / "completion.ref.json"))["official_grader_runs"] == 0


@pytest.mark.parametrize("change", ["intent", "patch", "capture", "audit"])
def test_real_partial_cleanup_still_rejects_changed_retained_evidence(real_cleanup_case, monkeypatch, change):
    case = real_cleanup_case
    monkeypatch.setattr(case.cleanup, "_release_owned_images", lambda owned: [{"image": image, "removed": False} for image in owned])
    case.runner.run(cell_limit=1)
    folder = case.value["root"] / "cleanup" / case.value["target"]["target_id"]
    if change == "intent":
        path = folder / "intent.json"
        value = cohort.read(path)
        value["policy_reference"]["sha256"] = "f" * 64
        cohort.write(path, value)
    else:
        path = {"patch": case.item["path"].parent / "broker" / "submission.diff",
            "capture": Path(case.item["registration"]["capture_reference"]["path"]),
            "audit": case.item["path"].parent / "execution-audit.json"}[change]
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises((cohort.CohortError, case.cleanup.CleanupError, ValueError)):
        case.runner.status()


def old_controller_cohort(ops, monkeypatch):
    current = cohort.__file__
    previous = ops.root / "previous-controller.py"
    previous.write_text("# synthetic previous frozen controller\n")
    with monkeypatch.context() as scoped:
        scoped.setattr(cohort, "__file__", str(previous))
        runner = make(ops)
        runner.run(cell_limit=1)
    return runner, cohort.reference(previous), cohort.reference(current)


def test_explicit_controller_revision_preserves_frozen_cohort_events_and_execution(ops, monkeypatch):
    runner, previous, new = old_controller_cohort(ops, monkeypatch)
    frozen = {path: path.read_bytes() for path in runner.root.rglob("*") if path.is_file() and path.suffix != ".lock"}
    calls = list(ops.calls)
    with pytest.raises(cohort.CohortError, match="explicitly adopt"):
        reopen(ops)
    revision = cohort.adopt_controller_revision(runner.root, previous_source_reference=previous,
        new_source_reference=new, reason="Validate retained cleanup intent after partial image release")
    assert all(path.read_bytes() == raw for path, raw in frozen.items())
    assert cohort.adopt_controller_revision(runner.root, previous_source_reference=previous,
        new_source_reference=new, reason="Validate retained cleanup intent after partial image release") == revision
    status = reopen(ops).status()
    assert status["controller_revision_count"] == 1 and status["controller_source_reference"] == new
    assert status["completed_cells"] == 1 and ops.calls == calls
    receipt = cohort.checked(revision)
    assert receipt["cohort_reference"] == cohort.reference(runner.root / "cohort.json")
    assert receipt["official_grader_runs"] == receipt["model_calls"] == 0
    assert reopen(ops).run()["completed_cells"] == 2


@pytest.mark.parametrize("change", ["previous", "new", "reason", "event_binding", "source_bytes"])
def test_controller_revision_rejects_unbound_or_changed_authority(ops, monkeypatch, change):
    runner, previous, new = old_controller_cohort(ops, monkeypatch)
    if change in {"previous", "new", "reason"}:
        arguments = {"previous_source_reference": previous, "new_source_reference": new, "reason": "Reviewed controller fix"}
        if change == "previous": arguments["previous_source_reference"] = new
        if change == "new": arguments["new_source_reference"] = previous
        if change == "reason": arguments["reason"] = ""
        with pytest.raises(cohort.CohortError):
            cohort.adopt_controller_revision(runner.root, **arguments)
        assert not (runner.root / "controller-revisions").exists()
    else:
        ref = cohort.adopt_controller_revision(runner.root, previous_source_reference=previous,
            new_source_reference=new, reason="Reviewed controller fix")
        if change == "source_bytes":
            Path(previous["path"]).write_text("# changed previous authority\n")
        else:
            value = cohort.read(ref["path"])
            value["event_tail_sha256"] = "f" * 64
            value["sha256"] = cohort.sha(cohort.canonical({key: item for key, item in value.items() if key != "sha256"}))
            cohort.write(ref["path"], value)
        with pytest.raises(cohort.CohortError):
            reopen(ops)


@pytest.mark.parametrize("kind", ["image", "object"])
@pytest.mark.parametrize("stdout", ["\n", "[]\n"])
def test_real_cleanup_reconciles_only_proven_absence_without_another_remove(real_cleanup_case, monkeypatch, kind, stdout):
    case = real_cleanup_case
    image_calls = []

    def failed_release(owned):
        image_calls.append(deepcopy(owned))
        return [{"image": image, "removed": False} for image in owned]

    def inspect(argv, **options):
        assert argv == ["docker", "image", "inspect", case.value["image"]]
        assert options == {"capture_output": True, "text": True, "check": False, "timeout": 30}
        return SimpleNamespace(returncode=1, stdout=stdout, stderr=f"Error response from daemon: No such {kind}: {argv[-1]}\n")

    monkeypatch.setattr(case.cleanup, "_release_owned_images", failed_release)
    monkeypatch.setattr(cohort, "_inspect_absent_owned_image", case.inspector)
    monkeypatch.setattr(cohort.subprocess, "run", inspect)
    result = case.runner.run(cell_limit=1)
    assert result["status"] == "COMPLETE" and result["cleanup_pending_cells"] == 0
    assert len(image_calls) == 1
    folder = case.value["root"] / "cleanup" / case.value["target"]["target_id"]
    failed_ref = cohort.reference(folder / "attempt-0001.json")
    completion = cohort.checked(cohort.read(folder / "completion.ref.json"))
    receipt = cohort.checked(completion["reconciliation_reference"])
    assert receipt["failed_attempt_reference"] == failed_ref
    assert receipt["delete_operations"] == receipt["model_calls"] == receipt["official_grader_runs"] == 0
    assert len(receipt["images"]) == 1 and receipt["images"][0]["image"] == case.value["image"]
    assert receipt["images"][0]["inspect"]["stderr_sha256"] == cohort.sha(receipt["images"][0]["inspect"]["stderr"].encode())
    opened = list(case.calls)
    assert case.runner.run()["status"] == "COMPLETE" and case.calls == opened and len(image_calls) == 1
    assert cohort.reference(failed_ref["path"]) == failed_ref
    proof_path = Path(completion["reconciliation_reference"]["path"])
    proof_path.write_bytes(proof_path.read_bytes() + b"changed")
    with pytest.raises(cohort.CohortError, match="changed"):
        case.runner.status()


@pytest.mark.parametrize("failure", ["daemon", "transport", "present", "other_image", "stdout", "returncode"])
def test_image_absence_reconciliation_fails_closed_on_ambiguous_docker_results(real_cleanup_case, monkeypatch, failure):
    case = real_cleanup_case
    monkeypatch.setattr(case.cleanup, "_release_owned_images", lambda owned: [{"image": image, "removed": False} for image in owned])
    monkeypatch.setattr(cohort, "_inspect_absent_owned_image", case.inspector)

    def inspect(argv, **options):
        if failure == "transport":
            raise cohort.subprocess.TimeoutExpired(argv, 30)
        return SimpleNamespace(returncode=0 if failure == "present" else 2 if failure == "returncode" else 1,
            stdout="[{\"Id\":\"sha256:public\"}]" if failure in {"present", "stdout"} else "",
            stderr="Cannot connect to the Docker daemon" if failure == "daemon" else
                "Error response from daemon: No such image: " + ("unowned/image" if failure == "other_image" else argv[-1]))

    monkeypatch.setattr(cohort.subprocess, "run", inspect)
    result = case.runner.run(cell_limit=1)
    assert result["status"] == "BLOCKED" and result["cleanup_pending_cells"] == 1
    folder = case.value["root"] / "cleanup" / case.value["target"]["target_id"]
    assert not (folder / "completion.json").exists() and not (folder / "absence-reconciliation.json").exists()


def test_resumed_failed_cleanup_never_retries_deletion_or_mistakes_daemon_failure_for_absence(real_cleanup_case, monkeypatch):
    case = real_cleanup_case
    monkeypatch.setattr(case.cleanup, "_release_owned_images", lambda owned: [{"image": image, "removed": False} for image in owned])
    assert case.runner.run(cell_limit=1)["cleanup_pending_cells"] == 1
    before = list(case.calls)
    monkeypatch.setattr(case.cleanup, "cleanup_completed_cell", lambda *a, **k: pytest.fail("Deletion helper must not run for prior incomplete attempt"))
    monkeypatch.setattr(cohort, "_inspect_absent_owned_image", case.inspector)
    monkeypatch.setattr(cohort.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect to the Docker daemon"))
    result = case.runner.run()
    assert result["status"] == "BLOCKED" and result["cleanup_pending_cells"] == 1
    assert case.calls == before
    assert len(list((case.value["root"] / "cleanup" / case.value["target"]["target_id"]).glob("attempt-*.json"))) == 1


def test_fresh_helper_complete_requires_strict_owned_image_postcondition_and_resumes_without_deletion(real_cleanup_case, monkeypatch):
    case = real_cleanup_case
    # The inherited helper can claim removed=True after an ambiguous inspect.
    monkeypatch.setattr(cohort, "_inspect_absent_owned_image", case.inspector)
    monkeypatch.setattr(cohort.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect to the Docker daemon"))
    result = case.runner.run(cell_limit=1)
    folder = case.value["root"] / "cleanup" / case.value["target"]["target_id"]
    assert (folder / "completion.ref.json").is_file()
    assert result["status"] == "BLOCKED" and result["cleanup_pending_cells"] == 1
    assert not any(event["stage"] == "CLEANED" for event in case.runner._events())
    assert not (folder / "owned-image-postcondition.json").exists()
    completion_before = cohort.reference(folder / "completion.json")
    monkeypatch.setattr(case.cleanup, "_remove_checkout", lambda *a: pytest.fail("Completed checkout removal cannot repeat"))
    monkeypatch.setattr(case.cleanup, "_release_owned_images", lambda *a: pytest.fail("Completed image release cannot repeat"))
    monkeypatch.setattr(cohort.subprocess, "run", lambda argv, **k: SimpleNamespace(returncode=1, stdout="[]\n",
        stderr="Error response from daemon: No such image: " + argv[-1] + "\n"))
    assert case.runner.run()["status"] == "COMPLETE"
    assert cohort.reference(folder / "completion.json") == completion_before
    proof = cohort.read(folder / "owned-image-postcondition.json")
    assert proof["completion_reference"] == completion_before
    assert proof["delete_operations"] == proof["model_calls"] == proof["official_grader_runs"] == 0
    assert proof["images"][0]["inspect"]["stdout"] == "[]\n"


def test_final_cell_crash_before_image_postcondition_keeps_cohort_in_progress(real_cleanup_case, monkeypatch):
    case = real_cleanup_case

    class ManagerCrash(BaseException):
        pass

    def crash(*args):
        raise ManagerCrash()

    monkeypatch.setattr(case.runner, "_require_image_postcondition", crash)
    with pytest.raises(ManagerCrash):
        case.runner.run(cell_limit=1)
    assert case.runner._events()[-1]["stage"] == "CELL_COMPLETE"
    status = case.runner.status()
    assert status["completed_cells"] == status["planned_cells"] == 1
    assert status["cleanup_pending_cells"] == 1 and status["status"] == "IN_PROGRESS"


def finish_real_cleanup(case, monkeypatch):
    monkeypatch.setattr(cohort, "_inspect_absent_owned_image", case.inspector)
    monkeypatch.setattr(cohort.subprocess, "run", lambda argv, **kw: SimpleNamespace(returncode=1, stdout="[]\n",
        stderr="Error response from daemon: No such image: " + argv[-1] + "\n"))
    result = case.runner.run(cell_limit=1)
    assert result["status"] == "COMPLETE" and result["terminal_full_audit_complete"]
    return result


def test_one_journal_snapshot_per_operation_and_no_unchanged_event_rereads(ops, monkeypatch):
    runner = make(ops, full=True)
    original_chain, original_read = cohort._event_chain, cohort.read
    scans, journal_reads = [], []

    def chain(*args, **kwargs):
        scans.append(True)
        return original_chain(*args, **kwargs)

    def read(path):
        if Path(path).parent == runner.root / "events":
            journal_reads.append(str(path))
        return original_read(path)

    monkeypatch.setattr(cohort, "_event_chain", chain)
    monkeypatch.setattr(cohort, "read", read)
    assert runner.run(cell_limit=3)["completed_cells"] == 3
    assert len(scans) == 1 and journal_reads == []
    for _ in range(3):
        assert runner.status()["completed_cells"] == 3
    assert len(scans) == 4 and journal_reads == []
    # Returned observations cannot mutate the verified process-local journal.
    exposed = runner._events()
    exposed[0]["details"]["outside_change"] = True
    assert "outside_change" not in runner._events()[0]["details"]


def test_journal_snapshot_accepts_verified_external_append_and_detects_historical_mutation(ops, monkeypatch):
    runner = make(ops, full=True)
    runner.run(cell_limit=1)
    reopened = reopen(ops)
    reopened._record("DISK_BLOCK", reopened.schedule[1], {"operation_started": False})
    assert runner.status()["status"] == "BLOCKED"
    path = runner.root / "events" / "00000001.json"
    value = cohort.read(path)
    value["details"]["changed"] = True
    cohort.write(path, value)
    with pytest.raises(cohort.CohortError, match="event chain changed"):
        runner.status()


def test_cleaned_history_uses_coherent_cache_but_full_audit_and_fresh_runner_revalidate(real_cleanup_case, monkeypatch):
    case = real_cleanup_case
    finished = finish_real_cleanup(case, monkeypatch)
    assert finished["validation_mode"] == "FULL_AUDIT"
    original = case.cleanup.validate_completed_cleanup
    validations = []

    def validate(*args, **kwargs):
        validations.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(case.cleanup, "validate_completed_cleanup", validate)
    for _ in range(3):
        assert case.runner.status()["validation_mode"] == "COHERENT_IN_PROCESS_CACHE"
        assert case.runner.run()["status"] == "COMPLETE"
    assert validations == []
    assert case.runner.full_audit()["terminal_full_audit_complete"]
    assert len(validations) == 1
    validations.clear()
    new = cohort.CohortRunner(case.runner.root, operations=case.operations, cleanup_operations=case.cleanup,
        learning_hook=case.capture, disk_free=lambda _: 10**15)
    assert new.status()["validation_mode"] == "FULL_AUDIT"
    assert len(validations) == 1


@pytest.mark.parametrize("change", ["patch", "capture", "new_native_failure", "recreated_checkout", "authority"])
def test_cached_terminal_validation_invalidates_on_retained_file_directory_or_authority_change(real_cleanup_case, monkeypatch, change):
    case = real_cleanup_case
    finish_real_cleanup(case, monkeypatch)
    if change == "recreated_checkout":
        case.absent.remove(str(case.item["checkout"]))
        # Simulated removal leaves the physical directory in place; change the
        # absent-path stamp just as an actual recreation would do.
        original_stamp = cohort._stamp
        monkeypatch.setattr(cohort, "_stamp", lambda path: ("RECREATED",) if str(path) == str(case.item["checkout"]) else original_stamp(path))
    elif change == "new_native_failure":
        cohort.write(case.item["path"].parent / "native-execution-failure.json", {"error": "new failure evidence"})
    else:
        path = {"patch": case.item["path"].parent / "broker" / "submission.diff",
            "capture": Path(case.item["registration"]["capture_reference"]["path"]),
            "authority": Path(case.value["config"]["dataset_manifest"]["path"])}[change]
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises((cohort.CohortError, case.cleanup.CleanupError, ValueError)):
        case.runner.status()


def test_explicit_full_audit_rehashes_content_even_if_metadata_cache_is_held_constant(real_cleanup_case, monkeypatch):
    case = real_cleanup_case
    finish_real_cleanup(case, monkeypatch)
    patch = case.item["path"].parent / "broker" / "submission.diff"
    original_stamp, stamp = cohort._stamp, cohort._stamp(patch)
    patch.write_bytes(patch.read_bytes().replace(b"Synthetic", b"Changed!!"))
    monkeypatch.setattr(cohort, "_stamp", lambda path: stamp if str(path) == str(patch) else original_stamp(path))
    with pytest.raises((cohort.CohortError, case.cleanup.CleanupError, ValueError)):
        case.runner.full_audit()


def test_historical_cleaned_event_without_image_postcondition_never_enters_terminal_cache(real_cleanup_case, monkeypatch):
    case = real_cleanup_case
    finish_real_cleanup(case, monkeypatch)
    postcondition = case.value["root"] / "cleanup" / case.value["target"]["target_id"] / "owned-image-postcondition.json"
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda path: False if path == postcondition else original(path))
    new = cohort.CohortRunner(case.runner.root, operations=case.operations, cleanup_operations=case.cleanup,
        learning_hook=case.capture, disk_free=lambda _: 10**15)
    status = new.status()
    assert status["status"] == "IN_PROGRESS" and status["cleanup_pending_cells"] == 1
    assert new._terminal_cache == {}


@pytest.fixture
def effort_case(tmp_path, monkeypatch):
    import trimem_skhynix_architecture_learning as learning
    ops = EffortOperations(tmp_path)
    ops.config.update(reasoning_effort="ultra", reasoning_source="original user configuration",
        model="gpt-6-astra", limits={"requests": 96}, source_sha256={"frozen-runtime": "a" * 64})
    cohort.write(ops.experiment, ops.config)
    policy = tmp_path / "policy-ultra.json"
    cohort.write(policy, {"experiment_reference": cohort.reference(ops.experiment), "run_root": ops.config["run_root"]})
    enrollment = tmp_path / "learning-old" / "learning-enrollment.json"
    cohort.write(enrollment, {"learning_version": 2, "execution_references": [cohort.reference(ops.experiment)],
        "capture_policy": "same deterministic public checkpoints", "source_owners": {"task": "owner"}})
    cleanup = FakeCleanup(ops)
    policy_calls = []
    original_cleanup = cleanup.cleanup_completed_cell

    def checked_cleanup(cell, result, capture, *, policy_reference):
        assert cohort.checked(policy_reference)["experiment_reference"] == cohort.reference(cohort.read(cell)["experiment_config"])
        policy_calls.append(policy_reference)
        return original_cleanup(cell, result, capture, policy_reference=policy_reference)

    cleanup.cleanup_completed_cell = checked_cleanup
    runner = make(ops, full=True, learning_root=enrollment.parent, learning_hook=synthetic_capture_hook(ops),
        cleanup_policy_reference=cohort.reference(policy), cleanup_operations=cleanup)
    high = tmp_path / "experiment-high.json"
    cohort.write(high, {**ops.config, "reasoning_effort": "high", "reasoning_source": "explicit forward user request",
        "prelaunch_revision": {"previous": cohort.reference(ops.experiment), "outcome_retries": False}})
    high_policy = tmp_path / "policy-high.json"
    cohort.write(high_policy, {**cohort.read(policy), "experiment_reference": cohort.reference(high)})
    new_enrollment = tmp_path / "learning-new" / "learning-enrollment.json"
    cohort.write(new_enrollment, {**cohort.read(enrollment), "execution_references":
        [cohort.reference(ops.experiment), cohort.reference(high)]})
    captures = []

    def factory(root):
        assert Path(root) == new_enrollment.parent
        synthetic = synthetic_capture_hook(ops)

        def capture(cell, result, directory):
            captures.append((str(root), str(cell), cohort.read(cell)["experiment_config"]))
            return synthetic(cell, result, directory)

        return capture

    monkeypatch.setattr(learning, "make_capture_hook", factory)
    return SimpleNamespace(ops=ops, runner=runner, cleanup=cleanup, high=high, high_policy=high_policy,
        enrollment=new_enrollment, captures=captures, policy_calls=policy_calls)


def start_effort_cell(case, number=0, *, prepare=True):
    row = case.runner.schedule[number]
    case.runner._record("PREPARE_STARTED", row, {})
    if prepare:
        path = case.ops.prepare_cell(case.ops.experiment, row["task_id"], row["arm"])
        case.runner._record("PREPARED", row, {"cell_reference": cohort.reference(path)})
    return row


def adopt_effort(case, **changes):
    events = case.runner._events()
    arguments = {"expected_event_tail_reference": cohort.reference(case.runner.root / "events" / f"{len(events):08d}.json"),
        "high_experiment_reference": cohort.reference(case.high), "high_cleanup_policy_reference": cohort.reference(case.high_policy),
        "learning_enrollment_reference": cohort.reference(case.enrollment), "reason": "User requested high for future cells",
        "operations": case.ops}
    return cohort.adopt_reasoning_effort_transition(case.runner.root, **{**arguments, **changes})


def test_effort_transition_preserves_completed_and_started_ultra_routes_only_future_high(effort_case):
    case = effort_case
    assert case.runner.run(cell_limit=1)["completed_cells"] == 1
    start_effort_cell(case, 1)
    preserved = {path: cohort.reference(path) for path in [case.runner.root / "cohort.json",
        *sorted((case.runner.root / "events").glob("*.json")),
        Path(case.runner.schedule[0]["cell_config"]), Path(case.runner.schedule[1]["cell_config"]),
        Path(case.runner.schedule[0]["cell_config"]).parent / "public-result.json"]}
    bound = adopt_effort(case)
    value = cohort.validate_reasoning_effort_transition(case.runner.root, bound, operations=case.ops)
    assert value["preserved_ultra_ordinals"] == [1, 2] and value["high_ordinals"] == list(range(3, 25))
    before = list(case.ops.calls)
    # The existing runner observes a newly enrolled immutable transition and invalidates its cache.
    status = case.runner.run(cell_limit=2)
    assert status["completed_cells"] == 3
    assert [row["reasoning_effort"] for row in status["cells"][:4]] == ["ultra", "ultra", "high", "high"]
    assert status["reasoning_effort_transition_reference"] == bound
    assert status["active_learning_root"] == str(case.enrollment.parent)
    assert case.ops.calls[len(before):] == [("solve", "training-001", "PDF_MEMORY"), ("grade", "training-001", "PDF_MEMORY"),
        ("prepare", "training-002", "PDF_MEMORY"), ("solve", "training-002", "PDF_MEMORY"), ("grade", "training-002", "PDF_MEMORY")]
    assert [item[2] for item in case.captures] == [str(case.ops.experiment), str(case.high)]
    assert case.policy_calls[-2:] == [case.runner.manifest["cleanup_policy_reference"], cohort.reference(case.high_policy)]
    assert {path: cohort.reference(path) for path in preserved} == preserved
    assert cohort.read(Path(case.runner.schedule[0]["cell_config"]).parent / "public-result.json")["resolved"] is False
    assert cohort.validate_reasoning_effort_transition(case.runner.root, bound, operations=case.ops) == value
    assert reopen(case.ops, cleanup_operations=case.cleanup).status()["completed_cells"] == 3


def test_effort_transition_does_not_replace_active_ultra_worker(effort_case):
    case = effort_case
    case.ops.fail_solve = "active"
    assert case.runner.run(cell_limit=1)["status"] == "BLOCKED"
    adopt_effort(case)
    before = list(case.ops.calls)
    case.ops.fail_solve = None
    status = case.runner.run(cell_limit=1)
    assert status["status"] == "BLOCKED" and case.ops.calls == before
    assert status["cells"][0]["reasoning_effort"] == "ultra" and not case.captures


def test_effort_transition_keeps_interrupted_prepare_guard(effort_case):
    case = effort_case
    start_effort_cell(case, prepare=False)
    adopt_effort(case)
    status = case.runner.run(cell_limit=1)
    assert status["status"] == "BLOCKED" and not case.ops.calls
    assert "no automatic retry" in case.runner._events()[-1]["details"]["error"]


@pytest.mark.parametrize("kind", ["cell", "workspace", "prepared", "native", "symlink"])
def test_effort_adoption_rejects_preexisting_future_artifacts(effort_case, kind):
    case = effort_case
    start_effort_cell(case)
    _, _, paths = cohort._effort_partition(case.runner.manifest, case.runner._events(), case.ops.config)
    row = case.runner.schedule[1]
    choices = {"cell": Path(row["cell_config"]).parent,
        "workspace": Path(case.ops.config["run_root"]) / "workspaces" / row["arm"] / row["task_id"],
        "prepared": Path(case.ops.config["run_root"]) / "environment/TRAINING/cells" / row["arm"] / row["task_id"],
        "native": Path(case.ops.config["native_control_root"]) / "TRAINING" / row["target"]["instance_id"] / row["arm"]}
    path = choices.get(kind, choices["cell"])
    assert str(path) in paths
    if kind == "symlink":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(case.ops.root / "missing", target_is_directory=True)
    else:
        path.mkdir(parents=True)
    with pytest.raises(cohort.CohortError, match="already has"):
        adopt_effort(case)
    assert not (case.runner.root / "reasoning-effort-transition.json").exists()


@pytest.mark.parametrize("field,value", [("limits", {"requests": 192}), ("model", "another-model"),
    ("run_root", "/another-root"), ("native_control_root", "/another-native"), ("source_sha256", {}),
    ("reasoning_effort", "medium"), ("reasoning_source", "")])
def test_effort_adoption_rejects_changes_to_runtime_budgets_or_unsupported_effort(effort_case, field, value):
    case = effort_case
    start_effort_cell(case)
    cohort.write(case.high, {**cohort.read(case.high), field: value})
    with pytest.raises(cohort.CohortError, match="only ultra to high"):
        adopt_effort(case)


@pytest.mark.parametrize("kind", ["policy", "learning_scope", "learning_refs", "tail", "partition"])
def test_effort_transition_rejects_changed_policy_scope_boundary_and_partition(effort_case, kind):
    case = effort_case
    start_effort_cell(case)
    if kind == "policy":
        cohort.write(case.high_policy, {**cohort.read(case.high_policy), "release_owned_images": False})
    elif kind.startswith("learning"):
        key, value = ("source_owners", {"task": "different"}) if kind == "learning_scope" else ("execution_references", [cohort.reference(case.high)])
        cohort.write(case.enrollment, {**cohort.read(case.enrollment), key: value})
    elif kind == "tail":
        stale = cohort.reference(case.runner.root / "events/00000001.json")
        with pytest.raises(cohort.CohortError, match="journal advanced"):
            adopt_effort(case, expected_event_tail_reference=stale)
        return
    else:
        bound = adopt_effort(case)
        value = cohort.checked(bound)
        value["preserved_ultra_ordinals"], value["high_ordinals"] = [], list(range(1, 25))
        cohort.write(bound["path"], value)
        cohort.write(case.runner.root / "reasoning-effort-transition.ref.json", cohort.reference(bound["path"]))
        with pytest.raises(cohort.CohortError, match="partition"):
            cohort.validate_reasoning_effort_transition(case.runner.root, operations=case.ops)
        return
    with pytest.raises(cohort.CohortError, match="cleanup policy|learning authority"):
        adopt_effort(case)


def test_effort_transition_wrong_config_on_started_cell_and_changed_sidecar_fail_closed(effort_case):
    case = effort_case
    row = start_effort_cell(case)
    bound = adopt_effort(case)
    case.runner.status()
    cell = cohort.read(row["cell_config"])
    cohort.write(row["cell_config"], {**cell, "experiment_config": str(case.high)})
    Path(row["cell_config"]).with_suffix(".sha256").write_text(cohort.sha(cohort.canonical(cohort.read(row["cell_config"]))))
    with pytest.raises(cohort.CohortError, match="cell identity"):
        case.runner._validate_cell(row)
    Path(bound["path"]).write_bytes(Path(bound["path"]).read_bytes() + b" ")
    with pytest.raises(cohort.CohortError, match="reference differs"):
        case.runner.status()


def test_effort_adoption_rejects_rewritten_prepared_ultra_cell_even_with_recomputed_checksum(effort_case):
    case = effort_case
    row = start_effort_cell(case)
    path = Path(row["cell_config"])
    cohort.write(path, {**cohort.read(path), "unexpected_rewrite": True})
    path.with_suffix(".sha256").write_text(cohort.sha(cohort.canonical(cohort.read(path))))
    with pytest.raises(cohort.CohortError, match="original journal reference"):
        adopt_effort(case)


def test_high_evaluation_configuration_applies_identically_to_both_arms(ops):
    ops.config.update(reasoning_effort="high", reasoning_source="same explicit user request for both evaluation arms")
    runner = make(ops, phase="EVALUATION")
    status = runner.run(cell_limit=2)
    assert {row["reasoning_effort"] for row in status["cells"]} == {"high"}
    assert {row["experiment_reference"]["sha256"] for row in status["cells"]} == {cohort.reference(ops.experiment)["sha256"]}
    assert status["paired_comparison"]["completed_pairs"] == 1


def test_returned_effort_status_references_cannot_mutate_cell_authority(effort_case):
    case = effort_case
    start_effort_cell(case)
    adopt_effort(case)
    status = case.runner.status()
    status["cells"][0]["experiment_reference"]["path"] = "/changed-ultra"
    status["cells"][1]["experiment_reference"]["path"] = "/changed-high"
    fresh = case.runner.status()
    assert fresh["cells"][0]["experiment_reference"] == cohort.reference(case.ops.experiment)
    assert fresh["cells"][1]["experiment_reference"] == cohort.reference(case.high)
