"""Quota accounting uses synthetic authenticated evidence, never a native call."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_skhynix_architecture_broker as broker_module
import trimem_skhynix_architecture_native as native
import trimem_skhynix_architecture_run as execution
import trimem_skhynix_evaluation_continuation as grader_continuation
import trimem_skhynix_evaluation_quota_continuation as quota
from test_trimem_skhynix_training_grade_hold import write, mutate, TASK, INSTANCE, PATCH
from test_trimem_skhynix_evaluation_hold_continuation import scheduling_runner


USAGE_LIMIT = "You've hit your usage limit."


@pytest.fixture
def quota_factory(tmp_path, monkeypatch):
    """Real broker, launch/admission bindings and failed audit; invented task only."""
    serial = [0]

    def build(*, arm="BASELINE", message=USAGE_LIMIT):
        serial[0] += 1
        root = tmp_path / str(serial[0])
        root.mkdir()
        config = {"schema": execution.SCHEMA, "phase": "EVALUATION_RUNTIME",
            "run_root": str(root / "run"), "native_control_root": str(root / "native"),
            "source_root": str(root / "source"), "source_sha256": {},
            "model": "gpt-6-astra", "reasoning_effort": "high", "codex_binary": "C:/fixture/codex.exe",
            "windows_python": "C:/fixture/python.exe", "wsl_windows_python": "/mnt/c/fixture/python.exe"}
        config_path = root / "execution.json"
        config_ref = write(config_path, config, sidecar=True)
        folder = root / "run/cells/EVALUATION" / TASK / arm
        folder.mkdir(parents=True)
        cell_path = folder / "cell.json"
        checkout = root / "checkout"
        checkout.mkdir()
        (checkout / "public.py").write_text("synthetic public workspace\n")
        public = {"task_id": TASK, "repository": "fixture/repo", "commit": "a" * 40,
            "instruction": "Repair the public synthetic regression."}
        target = {"target_id": TASK, "instance_id": INSTANCE, "repository": public["repository"],
            "base_commit": public["commit"], "role": "EVALUATION",
            "instruction_sha256": execution.digest(public["instruction"].encode())}
        workspace = {"checkout_root": str(checkout), "image": "fixture/image@sha256:" + "c" * 64}
        clock = [1000.0]
        bank_sha = "0" * 64 if arm == "BASELINE" else "b" * 64
        broker = broker_module.ArchitectureBroker.create(folder / "broker", task_public=public,
            arm=arm, workspace=SimpleNamespace(patch=lambda: PATCH),
            configuration_sha256=execution.digest(execution.canonical(config)), bank_sha256=bank_sha,
            tool_schema={"read_file": {"type": "object"}}, clock=lambda: clock[0],
            workspace_configuration=workspace)
        cell = {"schema": execution.SCHEMA, "phase": "EVALUATION", "arm": arm,
            "experiment_config": str(config_path), "task_public": public, "target": target,
            "broker_root": str(broker.root), "bank_sha256": bank_sha, "bank_reference": None,
            "workspace_configuration": workspace,
            "prepared_output_root": str(root / "run/environment/EVALUATION/cells" / arm / TASK)}
        write(cell_path, cell, sidecar=True)
        worker_id = arm.lower() + "-" + INSTANCE + "-1"
        issued = broker.issue_handoff(worker_id)
        worker = root / "native/EVALUATION" / INSTANCE / arm / "worker-001"
        output = worker / "output"
        output.mkdir(parents=True)
        prompt = execution.prompt_prefix("EVALUATION") + execution.canonical(issued["packet"])
        (worker / "prompt.txt").write_bytes(prompt)
        write(worker / "packet.json", issued["packet"])
        worker_config = {"schema": execution.SCHEMA, "linux_source_root": config["source_root"],
            "linux_cell_config": str(cell_path), "worker_id": worker_id,
            "worker_output": str(output), "worker_cwd": str(worker / "cwd"),
            "admission_path": str(worker / "admission.json"), "prompt_path": str(worker / "prompt.txt"),
            "prompt_sha256": execution.digest(prompt), "packet_sha256": issued["packet_sha256"],
            "codex_binary": config["codex_binary"], "windows_python": config["windows_python"],
            "model": config["model"], "reasoning_effort": config["reasoning_effort"],
            "authentication": "CHATGPT", "worker_timeout_seconds": 1200}
        write(worker / "config.json", worker_config)
        launch = {"schema": native.SCHEMA, "worker_id": worker_id, "requested_model": config["model"],
            "reasoning_effort": config["reasoning_effort"], "authentication": "CHATGPT_FORCED",
            "prompt_sha256": execution.digest(prompt), "prompt_bytes": len(prompt),
            "packet_sha256": issued["packet_sha256"], "fresh_session": True, "resume_or_fork_used": False,
            "separate_model_api_client_calls": 0, "started_at": clock[0],
            "command_sha256": execution.digest(execution.canonical(native.worker_command(worker_config, worker / "config.json")))}
        write(output / "launch.json", launch)
        admitted = broker.admit_worker(worker_id, issued["packet_sha256"], {
            "thread_id": "synthetic-thread-1", "fresh_session": True, "fork_turns": "none",
            "requested_model": config["model"], "launch_evidence_sha256": execution.digest(execution.canonical(launch))})
        token = admitted.pop("admission_token")
        write(worker / "admission.json", {**admitted, "worker_id": worker_id, "token": token})
        native_events = [{"type": "thread.started", "thread_id": "synthetic-thread-1"},
            {"type": "error", "message": message},
            {"type": "turn.failed", "error": {"message": message}}]
        raw = b"".join(execution.canonical(event) + b"\n" for event in native_events)
        (output / "events.jsonl").write_bytes(raw)
        completion_ref = write(output / "completion.json", {"thread_id": "synthetic-thread-1", "admitted": True,
            "outside_broker_tool_events": [], "errors": [], "transport_errors": [],
            "timed_out": False, "exit_code": 1, "ended_at": 1001.0,
            "wall_seconds": 1.0, "events_sha256": execution.digest(raw), "usage": None})
        write(folder / "native-execution-failure.json", {"launcher_returncode": 1,
            "worker_id": worker_id, "completion_sha256": completion_ref["sha256"]})
        clock[0] = 1002.0
        broker.seal_partial(reason="NATIVE_WORKER_INFRASTRUCTURE_FAILURE")
        monkeypatch.setattr(execution, "open_cell", lambda *args, **kwargs: (cell, config, broker))
        with pytest.raises(RuntimeError, match="Native execution audit failed"):
            execution.execution_audit(cell_path)
        assert execution.read(folder / "execution-audit.json")["passed"] is False
        cohort = root / "cohort"
        row = {"ordinal": 16, "task_id": TASK, "arm": arm, "cell_config": str(cell_path), "target": target}
        manifest = {"phase": "EVALUATION", "experiment_reference": config_ref, "bank_reference": None,
            "arms": [arm], "schedule": [row], "min_free_bytes": 10}
        write(cohort / "cohort.json", manifest)
        events = [
            {"stage": "PREPARED", "sequence": 1, "task_id": TASK, "arm": arm,
                "details": {"cell_reference": quota.core.ref(cell_path)}},
            {"stage": "SOLVE_STARTED", "sequence": 2, "task_id": TASK, "arm": arm, "details": {}},
            {"stage": "INFRA_ERROR", "sequence": 3, "task_id": TASK, "arm": arm,
                "details": {"error_type": "RuntimeError", "automatic_retry": False,
                    "error": "Native execution audit failed; no solve-rate result may be emitted"}},
        ]
        for event in events:
            write(cohort / "events" / f"{event['sequence']:08d}.json", event)

        def validate_cell(current):
            actual = execution.read(current["cell_config"])
            assert execution.digest(execution.canonical(actual)) == cell_path.with_suffix(".sha256").read_text().strip()
            assert actual["arm"] == current["arm"] and actual["task_public"]["task_id"] == current["task_id"]
            return actual

        runner = SimpleNamespace(root=cohort, manifest=manifest, config=config, schedule=[row], operations=execution,
            _cell_events=lambda current: events, _validate_cell=validate_cell,
            _row_config=lambda current: config, _row_experiment_reference=lambda current: config_ref,
            _broker_status=lambda path: broker.status())
        amendment = write(root / "amendment.json", {"schema": quota.AMENDMENT_SCHEMA, "policy": quota.POLICY})
        for name in ("run_workers", "grade_cell"):
            monkeypatch.setattr(execution, name, lambda *args, **kwargs:
                pytest.fail("Quota retention must not invoke a native worker or grader"))
        return SimpleNamespace(root=root, folder=folder, cell_path=cell_path, cell=cell,
            config_path=config_path, config=config, broker=broker, worker=worker, output=output,
            checkout=checkout, runner=runner, row=row, events=events, amendment_ref=amendment,
            output_root=root / "continuation", hold=quota.quota_hold_path(root / "continuation", runner, row))

    return build


def retain(ctx, *, create=True):
    return quota.retain_quota_hold(ctx.output_root, ctx.runner, ctx.row,
        amendment_reference=ctx.amendment_ref, create=create)


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_authenticated_quota_is_immutable_unscored_and_preserves_resources(quota_factory, arm):
    ctx = quota_factory(arm=arm)
    originals = {p: p.read_bytes() for p in ctx.root.rglob("*") if p.is_file()}
    status_before = ctx.broker.status()
    assert retain(ctx, create=False) is None
    value, reference = retain(ctx)
    assert value["classification"] == quota.CLASSIFICATION
    assert value["official"] is False and value["resolved"] is None
    assert value["phase"] == "EVALUATION" and value["arm"] == arm
    assert value["resources_retained"] is True
    assert value["native_retries"] is value["official_grader_retries"] is False
    assert value["model_calls"] == value["official_grader_runs"] == value["training_memory_writes"] == 0
    assert value["memory_injections"] == status_before["memory_injections"]
    assert reference == quota.core.ref(ctx.hold)
    assert retain(ctx, create=False) == retain(ctx) == (value, reference)
    assert all(p.read_bytes() == raw for p, raw in originals.items())
    assert ctx.broker.status() == status_before
    assert ctx.checkout.is_dir()
    assert not (ctx.folder / "public-result.json").exists()
    assert not (ctx.folder / "grader-pending.json").exists()
    assert ctx.hold.parent.name == "native-quota-unscored"
    assert not grader_continuation.hold_path(ctx.output_root, ctx.runner, ctx.row).exists()


@pytest.mark.parametrize("message", [
    "Native worker crashed.",
    "Rate limit exceeded; retry later.",
    "Connection reset by peer.",
])
def test_other_native_failures_are_not_quota_outcomes(quota_factory, message):
    ctx = quota_factory(message=message)
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


@pytest.mark.parametrize("filename", ["public-result.json", "grader-private.json", "grader-pending.json",
    "training-grade-undetermined.json"])
def test_grade_or_training_evidence_conflicts_with_native_quota(quota_factory, filename):
    ctx = quota_factory()
    (ctx.folder / filename).write_bytes(b"DO NOT READ PRIVATE GRADE CONTENT")
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


@pytest.mark.parametrize("stage", ["SOLVE_COMPLETE", "GRADE_STARTED", "GRADED", "GRADE_UNDETERMINED",
    "CELL_COMPLETE", "LEARNED", "CLEANED"])
def test_post_native_lifecycle_cannot_be_reclassified(quota_factory, stage):
    ctx = quota_factory()
    ctx.events.append({"stage": stage, "details": {}})
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


@pytest.mark.parametrize("target", ["audit", "failure", "patch", "submission", "completion", "native_events",
    "launch", "admission", "worker_config", "packet", "prompt", "broker_state", "broker_events"])
def test_retained_quota_rejects_any_original_evidence_change(quota_factory, target):
    ctx = quota_factory()
    retain(ctx)
    paths = {"audit": ctx.folder / "execution-audit.json", "failure": ctx.folder / "native-execution-failure.json",
        "patch": ctx.folder / "broker/submission.diff", "submission": ctx.folder / "broker/submission.json",
        "completion": ctx.output / "completion.json", "native_events": ctx.output / "events.jsonl",
        "launch": ctx.output / "launch.json", "admission": ctx.worker / "admission.json",
        "worker_config": ctx.worker / "config.json", "packet": ctx.worker / "packet.json",
        "prompt": ctx.worker / "prompt.txt", "broker_state": ctx.folder / "broker/state.json",
        "broker_events": ctx.folder / "broker/events.jsonl"}
    path = paths[target]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx, create=False)


@pytest.mark.parametrize("relative", ["execution-audit.json", "broker/submission.diff", "broker/submission.json"])
def test_missing_historical_native_evidence_is_never_recreated(quota_factory, monkeypatch, relative):
    ctx = quota_factory()
    missing = ctx.folder / relative
    missing.unlink()
    monkeypatch.setattr(execution, "execution_audit", lambda *args, **kwargs:
        pytest.fail("Missing historical audit must not be regenerated"))
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        retain(ctx)
    assert not missing.exists() and not ctx.hold.exists()


def test_without_native_failure_receipt_there_is_no_quota_exception(quota_factory):
    ctx = quota_factory()
    (ctx.folder / "native-execution-failure.json").unlink()
    assert retain(ctx) is None
    assert not ctx.hold.exists()


@pytest.mark.parametrize("changes", [
    {"worker_id": "unadmitted-worker"}, {"launcher_returncode": 0}, {"launcher_returncode": True},
    {"completion_sha256": "f" * 64},
])
def test_failure_receipt_requires_the_actual_failed_worker(quota_factory, changes):
    ctx = quota_factory()
    mutate(ctx.folder / "native-execution-failure.json", **changes)
    audit = execution.read(ctx.folder / "execution-audit.json")
    audit["errors"][0]["failure_sha256"] = quota.core.ref(ctx.folder / "native-execution-failure.json")["sha256"]
    write(ctx.folder / "execution-audit.json", audit)
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


@pytest.mark.parametrize("changes", [
    {"passed": True}, {"task_id": "other-task"}, {"arm": "PDF_MEMORY"},
    {"patch_sha256": "f" * 64}, {"event_tail_sha256": "f" * 64},
    {"configuration_sha256": "f" * 64}, {"errors": []},
])
def test_failed_audit_must_bind_the_same_enrolled_attempt(quota_factory, changes):
    ctx = quota_factory()
    mutate(ctx.folder / "execution-audit.json", **changes)
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


@pytest.mark.parametrize("changes", [
    {"admitted": False}, {"timed_out": True}, {"exit_code": 0}, {"exit_code": True},
    {"thread_id": "unadmitted-thread"}, {"errors": ["malformed native event"]},
    {"transport_errors": ["manager failed"]}, {"outside_broker_tool_events": ["shell"]},
])
def test_quota_text_does_not_override_invalid_completion(quota_factory, changes):
    ctx = quota_factory()
    mutate(ctx.output / "completion.json", **changes)
    refresh_failure_bindings(ctx)
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


def refresh_failure_bindings(ctx):
    """Rebind synthetic failure receipts to exercise semantics, not stale hashes."""
    mutate(ctx.folder / "native-execution-failure.json",
        completion_sha256=quota.core.ref(ctx.output / "completion.json")["sha256"])
    audit = execution.read(ctx.folder / "execution-audit.json")
    audit["errors"][0]["failure_sha256"] = quota.core.ref(ctx.folder / "native-execution-failure.json")["sha256"]
    write(ctx.folder / "execution-audit.json", audit)


@pytest.mark.parametrize("native_events", [
    [{"type": "item.completed", "item": {"type": "agent_message", "text": USAGE_LIMIT}}],
    [{"type": "error", "message": USAGE_LIMIT}],
    [{"type": "turn.failed", "error": {"message": USAGE_LIMIT}}],
    [{"type": "error", "message": USAGE_LIMIT},
        {"type": "turn.failed", "error": {"message": "Native worker crashed."}}],
    [{"type": "error", "message": USAGE_LIMIT},
        {"type": "turn.failed", "error": {"message": USAGE_LIMIT}},
        {"type": "turn.completed", "usage": {}}],
])
def test_only_matching_terminal_service_errors_authenticate_quota(quota_factory, native_events):
    ctx = quota_factory()
    events = [{"type": "thread.started", "thread_id": "synthetic-thread-1"}, *native_events]
    raw = b"".join(execution.canonical(event) + b"\n" for event in events)
    (ctx.output / "events.jsonl").write_bytes(raw)
    mutate(ctx.output / "completion.json", events_sha256=execution.digest(raw))
    refresh_failure_bindings(ctx)
    with pytest.raises((ValueError, RuntimeError)):
        retain(ctx)
    assert not ctx.hold.exists()


def advance(runner, root, amendment):
    return quota.advance_one(runner, root=root, amendment_reference=amendment,
        grader_module=grader_continuation, grader_amendment_reference={}, grader_roots=[root])


def scheduled_native_runner(ctx, monkeypatch):
    """Exercise real retention while bounding only the next scheduled operation."""
    runner = ctx.runner
    rows = [ctx.row, {"task_id": "next", "arm": ctx.row["arm"],
        "cell_config": str(ctx.root / "next/cell.json")}]
    calls = []
    runner.schedule = rows
    runner._journal_snapshot = nullcontext
    runner._check_execution_api = lambda: None
    runner._check_controller_source = lambda: None
    runner._cell_events = lambda row: ctx.events if row["task_id"] == TASK else []
    runner.disk_free = lambda path: 1000
    runner._cleanup = lambda row: calls.append(("cleanup", row["task_id"]))
    runner._advance = lambda row: calls.append(("advance", row["task_id"]))
    monkeypatch.setattr(execution, "load_experiment", lambda path: execution.read(path))

    def record(stage, row, details):
        calls.append(("record", stage, row["task_id"]))
        event = {"stage": stage, "sequence": len(ctx.events) + 1,
            "task_id": row["task_id"], "arm": row["arm"], "details": details}
        ctx.events.append(event)
        write(runner.root / "events" / f"{event['sequence']:08d}.json", event)

    runner._record = record
    return runner, calls


def test_original_quota_hold_advances_to_next_task_without_retry_or_cleanup(quota_factory, monkeypatch):
    ctx = quota_factory()
    runner, calls = scheduled_native_runner(ctx, monkeypatch)
    first = advance(runner, ctx.output_root, ctx.amendment_ref)
    assert first["kind"] == "HELD" and first["task_id"] == TASK
    assert calls == []
    second = advance(runner, ctx.output_root, ctx.amendment_ref)
    assert second == {"kind": "OFFICIAL", "task_id": "next", "arm": "BASELINE"}
    assert ("advance", TASK) not in calls and ("cleanup", TASK) not in calls
    assert calls.count(("advance", "next")) == 1


def test_new_quota_is_retained_then_pauses_before_the_next_native_attempt(quota_factory, monkeypatch):
    ctx = quota_factory()
    runner, calls = scheduled_native_runner(ctx, monkeypatch)
    failure_path = ctx.folder / "native-execution-failure.json"
    failure_bytes = failure_path.read_bytes()
    failure_path.unlink()
    ctx.events.pop()
    (runner.root / "events/00000003.json").unlink()

    def fail_during_new_attempt(row):
        calls.append(("advance", row["task_id"]))
        assert row["task_id"] == TASK
        failure_path.write_bytes(failure_bytes)
        raise RuntimeError("Native execution audit failed; no solve-rate result may be emitted")

    runner._advance = fail_during_new_attempt
    with pytest.raises(quota.NativeQuotaPaused, match="paused"):
        advance(runner, ctx.output_root, ctx.amendment_ref)
    assert ctx.hold.is_file()
    value, reference = retain(ctx, create=False)
    assert value["official"] is False and value["resolved"] is None
    assert reference == quota.core.ref(ctx.hold)
    assert calls.count(("advance", TASK)) == 1
    assert ("advance", "next") not in calls
    assert not any(call[0] == "cleanup" for call in calls)


@pytest.mark.parametrize("already_complete", [False, True])
def test_other_arm_is_still_evaluated_but_its_resources_are_retained(quota_factory, tmp_path, already_complete):
    ctx = quota_factory(arm="PDF_MEMORY")
    retain(ctx)
    rows = [{"task_id": TASK, "arm": "BASELINE"}, {"task_id": "next", "arm": "BASELINE"}]
    history = {TASK + ":BASELINE": [{"stage": "CELL_COMPLETE"}]} if already_complete else {}
    runner, calls = scheduling_runner(tmp_path, rows, history)
    outcome = advance(runner, ctx.output_root, ctx.amendment_ref)
    assert ("cleanup", TASK, "BASELINE") not in calls
    assert ("validate" if already_complete else "advance", TASK, "BASELINE") in calls
    assert outcome["task_id"] == ("next" if already_complete else TASK)


@pytest.mark.parametrize("exception", [OSError("generic infrastructure failure"), RuntimeError(USAGE_LIMIT)])
def test_exception_text_alone_never_skips_a_scheduled_cell(tmp_path, exception):
    rows = [{"task_id": "first", "arm": "BASELINE"}, {"task_id": "next", "arm": "BASELINE"}]
    runner, calls = scheduling_runner(tmp_path, rows, {})

    def broken(row):
        calls.append(("advance", row["task_id"], row["arm"]))
        raise exception

    runner._advance = broken
    with pytest.raises(type(exception), match=str(exception)):
        advance(runner, tmp_path, {})
    assert ("advance", "next", "BASELINE") not in calls
    assert not any(isinstance(c, tuple) and c[0] == "cleanup" for c in calls)


def test_disk_reserve_still_blocks_before_a_new_attempt(tmp_path):
    runner, calls = scheduling_runner(tmp_path, [{"task_id": "next", "arm": "BASELINE"}], {})
    runner.disk_free = lambda path: 0
    with pytest.raises((ValueError, RuntimeError), match="storage"):
        advance(runner, tmp_path, {})
    assert not any(isinstance(c, tuple) and c[0] in {"advance", "cleanup"} for c in calls)


def test_cross_cohort_tampering_blocks_new_execution(quota_factory, tmp_path):
    ctx = quota_factory()
    retain(ctx)
    path = ctx.output / "events.jsonl"
    path.write_bytes(path.read_bytes() + b" ")
    runner, calls = scheduling_runner(tmp_path, [{"task_id": "next", "arm": "BASELINE"}], {})
    with pytest.raises((ValueError, RuntimeError)):
        advance(runner, ctx.output_root, ctx.amendment_ref)
    assert not any(isinstance(c, tuple) and c[0] in {"advance", "cleanup"} for c in calls)
