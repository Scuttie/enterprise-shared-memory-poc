"""Bounded scheduling and real spawn tests use synthetic files, never native models."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading
import time

import pytest

import test_trimem_skhynix_architecture_cohort as fixtures

cohort = fixtures.cohort


SYNTHETIC_RUNTIME = '''
import hashlib, json, os, time
from pathlib import Path

def load_experiment(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def run_workers(path):
    path = Path(path)
    cell = load_experiment(path)
    config = load_experiment(cell["experiment_config"])
    root = Path(config["run_root"])
    identity = cell["task_public"]["task_id"]
    active = root / (identity + ".active")
    with active.open("x") as stream:
        stream.write(str(os.getpid()))
    calls = {"pid": os.getpid(), "execution_path": str(Path(__file__).resolve()),
        "model": config["model"], "reasoning_effort": config["reasoning_effort"]}
    (path.parent / "synthetic-native-call.json").write_text(json.dumps(calls), encoding="utf-8")
    if cell["arm"] == "BASELINE":
        (root / (identity + ".started")).write_text(str(os.getpid()))
        deadline = time.monotonic() + 20
        while len(list(root.glob("*.started"))) < 2:
            if time.monotonic() > deadline:
                raise RuntimeError("synthetic workers did not overlap")
            time.sleep(0.01)
    time.sleep(0.05)
    status_path = path.parent / "broker" / "fixture-status.json"
    status = load_experiment(status_path)
    patch = path.parent / "broker" / "submission.diff"
    patch.write_bytes(b"synthetic sealed public diff\\n")
    status.update(status="SUBMITTED", workers_issued=1, workers_admitted=1, event_tail_sha256="2" * 64,
        submission={"patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(), "reason": "SUBMIT"})
    status["budget"]["requests_used"] = 9
    status_path.write_text(json.dumps(status), encoding="utf-8")
    active.unlink()
    return status
'''


def install_runtime(ops):
    source_root = ops.root / "synthetic-runtime"
    source = source_root / "scripts" / "trimem_skhynix_architecture_run.py"
    source.parent.mkdir(parents=True)
    source.write_text(SYNTHETIC_RUNTIME, encoding="utf-8")
    ops.__file__ = str(source)
    ops.config.update(source_root=str(source_root),
        source_sha256={"scripts/trimem_skhynix_architecture_run.py": cohort.reference(source)["sha256"]},
        model="synthetic-native-model", reasoning_effort="high")
    cohort.write(ops.experiment, ops.config)


class SyntheticPool:
    """Threads exist only in this fake executor; production executes process workers."""

    def __init__(self, ops, *, fail_task=None, barrier=False, active_failure=False):
        self.ops, self.fail_task, self.active_failure = ops, fail_task, active_failure
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2) if barrier else None
        self.active, self.submitted, self.maximum, self.closed = set(), [], 0, False

    def __call__(self, *, max_workers, mp_context, initializer, initargs):
        assert mp_context.get_start_method() == "spawn"
        assert initializer is exec and "spec_from_file_location" in initargs[0]
        self.pool = ThreadPoolExecutor(max_workers=max_workers)
        return self

    def submit(self, function, request):
        assert function is cohort._native_process
        cell = cohort.read(request["cell_reference"]["path"])
        self.submitted.append((cell["task_public"]["task_id"], cell["arm"]))
        return self.pool.submit(self.work, request)

    def work(self, request):
        path = Path(request["cell_reference"]["path"])
        cell = cohort.read(path)
        task = cell["task_public"]["task_id"]
        with self.lock:
            assert task not in self.active
            self.active.add(task)
            self.maximum = max(self.maximum, len(self.active))
        try:
            if self.barrier is not None and cell["arm"] == "BASELINE":
                self.barrier.wait(timeout=10)
            if task == self.fail_task:
                if self.active_failure:
                    status_path = path.parent / "broker" / "fixture-status.json"
                    status = cohort.read(status_path)
                    status.update(status="WORKER_ACTIVE", workers_issued=1, workers_admitted=1)
                    cohort.write(status_path, status)
                raise RuntimeError("usage limit reached in synthetic native worker")
            time.sleep(0.06)
            status = self.ops.run_workers(path)
            receipt = {"schema": cohort.NATIVE_PROCESS_SCHEMA, "request": request, "pid": os.getpid(),
                "status": "COMPLETE", "broker_status": status}
        except Exception as exc:
            receipt = {"schema": cohort.NATIVE_PROCESS_SCHEMA, "request": request, "pid": os.getpid(),
                "status": "ERROR", "error_type": type(exc).__name__, "error": str(exc)}
        finally:
            with self.lock:
                self.active.remove(task)
        receipt.update(started_at=1.0, ended_at=2.0, wall_seconds=1.0)
        return cohort._retain_json(path.parent / "native-process-completion.json", receipt)

    def shutdown(self, *, wait):
        self.pool.shutdown(wait=wait)
        self.closed = True
        assert not self.active


def setup_runner(tmp_path, *, phase="EVALUATION", real_spawn=False, **pool_options):
    ops = fixtures.FakeOperations(tmp_path)
    install_runtime(ops)
    pool = None if real_spawn else SyntheticPool(ops, **pool_options)
    kwargs = {} if real_spawn else {"executor_factory": pool}
    return ops, pool, fixtures.make(ops, phase=phase, **kwargs)


def test_parallel_overlaps_distinct_tasks_with_one_parent_journal_and_serial_pair_arms(tmp_path, monkeypatch):
    ops, pool, runner = setup_runner(tmp_path, barrier=True)
    parent = threading.get_ident()
    for obj, name in ((runner, "_record"), (ops, "prepare_cell"), (ops, "grade_cell"),
            (runner, "_cleanup"), (runner, "_learning")):
        original = getattr(obj, name)

        def guarded(*args, _original=original, **kwargs):
            assert threading.get_ident() == parent
            return _original(*args, **kwargs)

        monkeypatch.setattr(obj, name, guarded)
    result = runner.run(max_workers=2)
    assert result["status"] == "COMPLETE" and result["completed_cells"] == 4
    assert result["max_workers"] == pool.maximum == 2
    assert result["cells_advanced_this_invocation"] == 4
    assert result["terminal_full_audit_complete"] is True
    assert len(pool.submitted) == len(set(pool.submitted)) == 4
    assert set(pool.submitted[:2]) == {("evaluation-000", "BASELINE"), ("evaluation-001", "BASELINE")}
    for task in ("evaluation-000", "evaluation-001"):
        assert pool.submitted.index((task, "BASELINE")) < pool.submitted.index((task, "PDF_MEMORY"))
    assert pool.closed
    assert cohort.checked(result["parallel_policy_reference"])["max_workers"] == 2
    cohort._event_chain(runner.root)
    before = list(ops.calls)
    assert runner.run(max_workers=2)["status"] == "COMPLETE"
    assert ops.calls == before


def test_real_spawn_uses_pinned_runtime_and_two_child_processes(tmp_path):
    ops, _, runner = setup_runner(tmp_path, real_spawn=True)
    result = runner.run(max_workers=2)
    assert result["status"] == "COMPLETE", runner._events()
    calls = [cohort.read(Path(row["cell_config"]).parent / "synthetic-native-call.json") for row in runner.schedule]
    assert len({item["pid"] for item in calls}) == 2
    assert all(item["pid"] != os.getpid() and item["execution_path"] == ops.__file__
        and item["reasoning_effort"] == "high" and item["model"] == "synthetic-native-model" for item in calls)
    assert not any(call[0] == "solve" for call in ops.calls)
    assert fixtures.counts(ops, "grade") == 4
    receipts = [cohort.read(Path(row["cell_config"]).parent / "native-process-completion.json") for row in runner.schedule]
    assert all(item["ended_at"] >= item["started_at"] and item["wall_seconds"] >= 0.05 for item in receipts)


@pytest.mark.parametrize("max_workers", [0, -1, True, 1.0, "2", None, 5])
def test_worker_bound_rejects_noninteger_and_out_of_range_before_actions(tmp_path, max_workers):
    ops, pool, runner = setup_runner(tmp_path)
    with pytest.raises(cohort.CohortError, match="max_workers"):
        runner.run(max_workers=max_workers)
    assert not ops.calls and not pool.submitted


def test_default_serial_does_not_create_a_parallel_policy_or_pool(tmp_path):
    ops, pool, runner = setup_runner(tmp_path)
    result = runner.run()
    assert result["status"] == "COMPLETE" and result["max_workers"] == 1
    assert result["parallel_policy_reference"] is None and not pool.submitted
    assert fixtures.counts(ops, "solve") == 4


def test_training_stays_serial_and_historical_serial_cohort_cannot_enable_parallel(tmp_path):
    ops, _, runner = setup_runner(tmp_path, phase="TRAINING")
    with pytest.raises(cohort.CohortError, match="evaluation-only"):
        runner.run(max_workers=2)
    assert not ops.calls
    assert runner.run(cell_limit=1)["completed_cells"] == 1


def test_historical_serial_evaluation_and_parallel_cap_changes_fail_closed(tmp_path):
    _, _, runner = setup_runner(tmp_path)
    assert runner.run(cell_limit=1)["completed_cells"] == 1
    with pytest.raises(cohort.CohortError, match="previously started serial"):
        runner.run(max_workers=2)


def test_cell_limit_bounds_started_work_and_parallel_policy_binds_resume(tmp_path):
    ops, pool, runner = setup_runner(tmp_path)
    first = runner.run(cell_limit=1, max_workers=2)
    assert first["completed_cells"] == first["cells_advanced_this_invocation"] == len(pool.submitted) == 1
    assert first["max_workers"] == 2
    for changed in (1, 3):
        with pytest.raises(cohort.CohortError, match="immutable cohort parallel policy"):
            runner.run(max_workers=changed)
    resumed = fixtures.reopen(ops, executor_factory=pool).run(max_workers=2)
    assert resumed["status"] == "COMPLETE" and len(pool.submitted) == 4


@pytest.mark.parametrize("active_failure", [False, True])
def test_quota_failure_stops_new_dispatch_drains_success_and_stays_blocked(tmp_path, active_failure):
    ops, pool, runner = setup_runner(tmp_path, barrier=True, fail_task="evaluation-000", active_failure=active_failure)
    result = runner.run(max_workers=2)
    assert result["status"] == "BLOCKED" and result["completed_cells"] == 1
    assert len(pool.submitted) == 2 and pool.closed and not pool.active
    assert fixtures.counts(ops, "grade") == 1
    assert runner._events()[-1]["stage"] == "INFRA_ERROR"
    assert runner._events()[-1]["details"]["parallel_workers_drained"] is True
    errors = [cohort.read(Path(row["cell_config"]).parent / "native-process-completion.json")
        for row in runner.schedule if Path(row["cell_config"]).exists()]
    assert {item["status"] for item in errors} == {"ERROR", "COMPLETE"}
    calls = list(ops.calls)
    assert fixtures.reopen(ops, executor_factory=pool).run(max_workers=2)["status"] == "BLOCKED"
    assert ops.calls == calls and len(pool.submitted) == 2


def test_missing_process_completion_blocks_resume_before_admission_even_with_zero_workers(tmp_path):
    ops, pool, runner = setup_runner(tmp_path)
    with cohort.locked(runner.root / "run.lock"), runner._journal_snapshot():
        policy = runner._bind_parallel_policy(2)
        row = runner.schedule[2]
        runner._prepare_solve(row)
        request = runner._native_request(row, policy)
        runner._start_solve(row, runner._solve_status(row))
        runner._record("NATIVE_PROCESS_DISPATCHED", row, {"request": request})
    before = list(ops.calls)
    result = fixtures.reopen(ops, executor_factory=pool).run(max_workers=2)
    assert result["status"] == "BLOCKED" and not pool.submitted and ops.calls == before
    assert "no durable completion" in runner._events()[-1]["details"]["error"]


def test_completed_process_receipt_recovers_without_second_native_call(tmp_path):
    ops, pool, runner = setup_runner(tmp_path)
    with cohort.locked(runner.root / "run.lock"), runner._journal_snapshot():
        policy = runner._bind_parallel_policy(2)
        row = runner.schedule[0]
        runner._prepare_solve(row)
        request = runner._native_request(row, policy)
        runner._start_solve(row, runner._solve_status(row))
        runner._record("NATIVE_PROCESS_DISPATCHED", row, {"request": request})
        pool.work(request)
    result = fixtures.reopen(ops, executor_factory=pool).run(cell_limit=1, max_workers=2)
    assert result["completed_cells"] == 1 and result["cells_advanced_this_invocation"] == 1
    assert not pool.submitted and fixtures.counts(ops, "solve") == fixtures.counts(ops, "grade") == 1


def test_disk_block_drains_active_worker_and_remains_blocked(tmp_path):
    ops, pool, runner = setup_runner(tmp_path)
    available = iter([10**15, 0])
    runner.disk_free = lambda _: next(available)
    result = runner.run(max_workers=2)
    assert result["status"] == "BLOCKED" and result["completed_cells"] == 1
    assert len(pool.submitted) == 1 and pool.closed
    assert runner._events()[-1]["stage"] == "DISK_BLOCK"


def test_preparation_failure_drains_started_worker_without_admitting_more(tmp_path, monkeypatch):
    ops, pool, runner = setup_runner(tmp_path)
    prepare = ops.prepare_cell

    def failing_prepare(experiment, task, arm, **kwargs):
        if task.endswith("001"):
            raise RuntimeError("synthetic preparation failure")
        return prepare(experiment, task, arm, **kwargs)

    monkeypatch.setattr(ops, "prepare_cell", failing_prepare)
    result = runner.run(max_workers=2)
    assert result["status"] == "BLOCKED" and result["completed_cells"] == 1
    assert len(pool.submitted) == 1 and pool.closed


def test_parallel_policy_tamper_is_rejected(tmp_path):
    _, _, runner = setup_runner(tmp_path)
    runner.run(cell_limit=1, max_workers=2)
    policy = cohort.read(runner.root / "parallel-policy.json")
    policy["max_workers"] = 3
    cohort.write(runner.root / "parallel-policy.json", policy)
    with pytest.raises(cohort.CohortError, match="reference changed"):
        runner.status()


def test_rewritten_policy_and_sidecar_still_conflict_with_journal(tmp_path):
    _, _, runner = setup_runner(tmp_path)
    runner.run(cell_limit=1, max_workers=2)
    path = runner.root / "parallel-policy.json"
    policy = cohort.read(path)
    policy["max_workers"] = 3
    cohort.write(path, policy)
    cohort.write(runner.root / "parallel-policy.ref.json", cohort.reference(path))
    with pytest.raises(cohort.CohortError, match="journal binding"):
        runner.status()


def test_missing_parallel_policy_cannot_revert_to_serial_resume(tmp_path):
    ops, _, runner = setup_runner(tmp_path)
    runner.run(cell_limit=1, max_workers=2)
    (runner.root / "parallel-policy.json").unlink()
    (runner.root / "parallel-policy.ref.json").unlink()
    before = list(ops.calls)
    with pytest.raises(cohort.CohortError, match="policy is missing"):
        runner.run()
    assert ops.calls == before


def test_full_audit_rejects_changed_native_completion_timing(tmp_path):
    _, _, runner = setup_runner(tmp_path)
    assert runner.run(max_workers=2)["status"] == "COMPLETE"
    path = Path(runner.schedule[0]["cell_config"]).parent / "native-process-completion.json"
    receipt = cohort.read(path)
    receipt["wall_seconds"] = 0.01
    cohort.write(path, receipt)
    with pytest.raises(cohort.CohortError, match="returned receipt"):
        runner.full_audit()


def test_native_child_checks_all_source_pins_before_calling_solver(tmp_path, monkeypatch):
    ops, _, runner = setup_runner(tmp_path)
    with cohort.locked(runner.root / "run.lock"), runner._journal_snapshot():
        policy = runner._bind_parallel_policy(2)
        row = runner.schedule[0]
        runner._prepare_solve(row)
        request = runner._native_request(row, policy)
    monkeypatch.setattr(cohort, "execution", ops)
    Path(ops.__file__).write_text(SYNTHETIC_RUNTIME + "\n# changed frozen source\n", encoding="utf-8")
    receipt = cohort.checked(cohort._native_process(request))
    assert receipt["status"] == "ERROR" and "reference changed" in receipt["error"]
    assert fixtures.counts(ops, "solve") == 0
