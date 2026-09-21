"""Executable broker lifecycle with fake public workspace; no models/containers."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import trimem_skhynix_architecture_broker as broker_module
from enterprise_memory.trimem.native_architecture_context import HandoffLimits, HandoffMemory


TASK = {"task_id": "task-1", "repository": "org/repo", "commit": "a" * 40,
        "instruction": "Repair timeout propagation and retry handling"}
CONFIG, BANK = "c" * 64, "b" * 64
PATCH = "diff --git a/client.py b/client.py\n--- a/client.py\n+++ b/client.py\n@@ -1 +1 @@\n-old\n+new\n"
SUBGOALS = [
    {"node_id": "timeout", "objective": "Propagate timeout through callers", "operation": "inspect callers"},
    {"node_id": "retry", "objective": "Repair retry exception handling", "operation": "adjust retry boundary",
     "dependencies": ["timeout"]},
]


def fixture(tmp_path, arm="PDF_MEMORY", *, limits=HandoffLimits()):
    now, calls, recalls = [1000.0], [], []

    def execute(name, arguments):
        calls.append((name, deepcopy(arguments)))
        if name == "read_file":
            return {"path": arguments["path"], "content": "RAW_COMPLETED_CALLER_DETAIL\n"}
        if name == "run_command":
            return {"exit_code": 1, "stdout": "public regression still fails", "stderr": ""}
        return {"path": "client.py", "content_hash": "f" * 64, "bytes": 3}

    def recall(task, graph, query, checkpoint):
        recalls.append(deepcopy(query))
        items = []
        if not checkpoint:
            text = "Check caller contracts before changing timeout behavior."
            items = [HandoffMemory("lesson-1", "REPOSITORY_SEMANTIC", graph.active_node_id,
                text, broker_module.sha(text.encode()), "d" * 64, BANK)]
        return {"injections": items, "checkpoint": {"calls": checkpoint.get("calls", 0) + 1}, "decisions": []}

    workspace = SimpleNamespace(execute=execute, patch=lambda: PATCH)
    broker = broker_module.ArchitectureBroker.create(tmp_path / arm, task_public=TASK, arm=arm,
        workspace=workspace, configuration_sha256=CONFIG, bank_sha256=BANK,
        tool_schema={"read_file": {"type": "object"}}, limits=limits,
        memory_callback=recall, clock=lambda: now[0])
    return SimpleNamespace(broker=broker, now=now, calls=calls, recalls=recalls,
                           workspace=workspace, request_no=0, tokens={}, packets={})


def launch(ctx, worker):
    issued = ctx.broker.issue_handoff(worker)
    receipt = {"thread_id": "thread-" + worker, "fresh_session": True, "fork_turns": "none",
               "requested_model": "gpt-6-astra", "launch_evidence_sha256": "e" * 64}
    admitted = ctx.broker.admit_worker(worker, issued["packet_sha256"], receipt)
    ctx.tokens[worker] = admitted["admission_token"]
    ctx.packets[worker] = issued["packet"]
    return issued, admitted


def action(ctx, worker, op, **kwargs):
    ctx.request_no += 1
    return ctx.broker.action(worker, ctx.tokens[worker], {"request_id": f"request-{ctx.request_no}", "op": op, **kwargs})


def begin(ctx):
    launch(ctx, "planner")
    assert action(ctx, "planner", "plan_subgoals", subgoals=SUBGOALS)["ok"]
    transition = action(ctx, "planner", "activate_subgoal", node_id="timeout")
    assert transition["ok"] and transition["result"]["handoff_required"]
    launch(ctx, "solver-1")


def complete_first(ctx):
    assert action(ctx, "solver-1", "tool", name="read_file", arguments={"path": "client.py"})["ok"]
    result = action(ctx, "solver-1", "tool", name="run_command", arguments={"argv": ["python", "test.py"]})
    assert result["ok"] and result["result"]["exit_code"] == 1
    step = result["step_no"]
    assert step == result["budget"]["requests_used"]
    completion = action(ctx, "solver-1", "complete_subgoal", summary="Timeout inspected; public regression still fails",
                        evidence_steps=[step])
    assert completion["ok"] and completion["result"]["handoff_required"]
    return launch(ctx, "solver-2")


@pytest.mark.parametrize("arm", ["BASELINE", "PDF_MEMORY"])
def test_full_planner_two_subgoals_fresh_workers_and_one_sealed_patch(tmp_path, arm):
    ctx = fixture(tmp_path, arm)
    begin(ctx)
    issued, _ = complete_first(ctx)
    raw = broker_module.canonical(issued["packet"]).decode()
    assert ("RAW_COMPLETED_CALLER_DETAIL" in raw) is (arm == "BASELINE")
    assert issued["packet"]["body"]["binding"]["previous_worker_id"] == "solver-1"
    if arm == "PDF_MEMORY":
        summary = issued["packet"]["body"]["working_context"]["completed_subgoals"][0]
        assert any(row["result_facts"].get("exit_code") == 1 for row in summary["tool_results"])
    result = action(ctx, "solver-2", "submit", summary="Focused partial repair; public regression still fails")
    assert result["ok"] and result["result"]["patch_sha256"] == broker_module.sha(PATCH.encode())
    status = ctx.broker.status()
    assert status["status"] == "SUBMITTED" and status["workers_admitted"] == 3
    assert status["budget"]["requests_used"] == 6
    assert result["step_no"] == 6
    assert status["memory_injections"] == (1 if arm == "PDF_MEMORY" else 0)
    assert len(ctx.recalls) == (2 if arm == "PDF_MEMORY" else 0)
    assert (ctx.broker.root / "submission.diff").read_text() == PATCH
    assert all(row["arm"] == arm for row in broker_module.read(ctx.broker.root / "state.json")["history"])


def test_planner_cannot_use_repo_tools_before_active_subgoal_and_errors_consume_budget(tmp_path):
    ctx = fixture(tmp_path)
    launch(ctx, "planner")
    response = action(ctx, "planner", "tool", name="read_file", arguments={"path": "client.py"})
    assert not response["ok"] and "active semantic subgoal" in response["error"]
    assert ctx.calls == [] and response["budget"]["requests_used"] == 1


def test_revoked_worker_cannot_run_and_identical_transition_retry_is_idempotent(tmp_path):
    ctx = fixture(tmp_path)
    launch(ctx, "planner")
    assert action(ctx, "planner", "plan_subgoals", subgoals=SUBGOALS)["ok"]
    request = {"request_id": "transition", "op": "activate_subgoal", "node_id": "timeout"}
    first = ctx.broker.action("planner", ctx.tokens["planner"], request)
    assert ctx.broker.action("planner", ctx.tokens["planner"], request) == first
    assert ctx.broker.status()["budget"]["requests_used"] == 2
    with pytest.raises(broker_module.BrokerError, match="revoked"):
        action(ctx, "planner", "info")
    with pytest.raises(broker_module.BrokerError, match="different bytes"):
        ctx.broker.action("planner", ctx.tokens["planner"], {**request, "node_id": "retry"})


@pytest.mark.parametrize("mutation", [
    {"fresh_session": False}, {"fork_turns": "all"}, {"requested_model": "other-model"},
    {"launch_evidence_sha256": "invalid"},
])
def test_admission_requires_actual_new_native_launch_receipt(tmp_path, mutation):
    ctx = fixture(tmp_path)
    issued = ctx.broker.issue_handoff("planner")
    receipt = {"thread_id": "thread-planner", "fresh_session": True, "fork_turns": "none",
               "requested_model": "gpt-6-astra", "launch_evidence_sha256": "e" * 64, **mutation}
    with pytest.raises(Exception):
        ctx.broker.admit_worker("planner", issued["packet_sha256"], receipt)
    assert ctx.broker.status()["workers_admitted"] == 0


def test_admission_rejects_wrong_packet_token_and_reused_thread(tmp_path):
    ctx = fixture(tmp_path)
    issued = ctx.broker.issue_handoff("planner")
    receipt = {"thread_id": "thread-planner", "fresh_session": True, "fork_turns": "none",
               "requested_model": "gpt-6-astra", "launch_evidence_sha256": "e" * 64}
    with pytest.raises(broker_module.BrokerError, match="packet hash"):
        ctx.broker.admit_worker("planner", "f" * 64, receipt)
    admitted = ctx.broker.admit_worker("planner", issued["packet_sha256"], receipt)
    ctx.tokens["planner"] = admitted["admission_token"]
    with pytest.raises(broker_module.BrokerError, match="token"):
        ctx.broker.action("planner", "bad", {"request_id": "x", "op": "info"})
    action(ctx, "planner", "plan_subgoals", subgoals=SUBGOALS)
    action(ctx, "planner", "activate_subgoal", node_id="timeout")
    second = ctx.broker.issue_handoff("solver-1")
    with pytest.raises(broker_module.BrokerError, match="thread was already used"):
        ctx.broker.admit_worker("solver-1", second["packet_sha256"], receipt)
    assert admitted["admission_token"] not in (ctx.broker.root / "events.jsonl").read_text()


def test_whole_task_request_and_time_limits_survive_fresh_workers_and_reload(tmp_path):
    ctx = fixture(tmp_path, limits=HandoffLimits(task_requests=3))
    begin(ctx)
    assert action(ctx, "solver-1", "info")["budget"]["requests_remaining"] == 0
    fresh = broker_module.ArchitectureBroker(ctx.broker.root, workspace=ctx.workspace,
        configuration_sha256=CONFIG, bank_sha256=BANK, clock=lambda: ctx.now[0])
    with pytest.raises(broker_module.BrokerError, match="budget exhausted"):
        fresh.action("solver-1", ctx.tokens["solver-1"], {"request_id": "extra", "op": "info"})
    sealed = fresh.seal_partial(reason="REQUEST_LIMIT")
    assert sealed["actions"] == 3 and sealed["agent_completed"] is False


def test_command_timeout_clamps_remaining_whole_task_wall_time(tmp_path):
    ctx = fixture(tmp_path)
    begin(ctx)
    ctx.now[0] += 1193
    result = action(ctx, "solver-1", "tool", name="run_command",
                    arguments={"argv": ["python", "test.py"], "timeout_seconds": 120})
    assert result["ok"] and ctx.calls[-1][1]["timeout_seconds"] == 7
    ctx.now[0] += 8
    with pytest.raises(broker_module.BrokerError, match="budget exhausted"):
        action(ctx, "solver-1", "info")
    assert ctx.broker.seal_partial(reason="TIME_LIMIT")["started_at"] == 1000


def test_completion_requires_owned_observation_and_does_not_invent_test_success(tmp_path):
    ctx = fixture(tmp_path)
    begin(ctx)
    bad = action(ctx, "solver-1", "complete_subgoal", summary="Done", evidence_steps=[999])
    assert not bad["ok"] and "does not belong" in bad["error"]
    state = broker_module.read(ctx.broker.root / "state.json")
    assert state["graph"]["active_node_id"] == "timeout"
    assert state["graph"]["nodes"][0]["completion_evidence"] == []


def test_pdf_trace_uses_bound_handoff_snapshot_after_new_worker_has_added_rows(tmp_path):
    ctx = fixture(tmp_path)
    begin(ctx)
    complete_first(ctx)
    action(ctx, "solver-2", "tool", name="read_file", arguments={"path": "client.py"})
    page = action(ctx, "solver-2", "trace", subgoal_id="timeout", max_bytes=48000, start_after_step=0)
    assert page["ok"] and page["result"]["rows"][0]["result_payload"]["content"] == "RAW_COMPLETED_CALLER_DETAIL\n"
    row = page["result"]["rows"][0]
    chunk = action(ctx, "solver-2", "trace_chunk", subgoal_id="timeout", step_no=row["step_no"],
                   offset_bytes=0, max_bytes=8192)
    assert chunk["ok"] and chunk["result"]["row_sha256"] == broker_module.sha(broker_module.canonical(row))
    assert chunk["result"]["complete_observation"] is False


def test_memory_reservation_only_counts_as_delivery_after_actual_admission(tmp_path):
    ctx = fixture(tmp_path)
    launch(ctx, "planner")
    action(ctx, "planner", "plan_subgoals", subgoals=SUBGOALS)
    action(ctx, "planner", "activate_subgoal", node_id="timeout")
    ctx.broker.issue_handoff("solver-1")
    status = ctx.broker.status()
    assert status["memory_records_reserved"] == 1 and status["memory_injections"] == 0


@pytest.mark.parametrize("field", ["configuration_sha256", "bank_sha256"])
def test_frozen_config_and_bank_cannot_change_on_restart(tmp_path, field):
    ctx = fixture(tmp_path)
    args = {"configuration_sha256": CONFIG, "bank_sha256": BANK, field: "f" * 64}
    with pytest.raises(broker_module.BrokerError, match="frozen configuration or bank"):
        broker_module.ArchitectureBroker(ctx.broker.root, workspace=ctx.workspace, **args)


def test_changed_checkpoint_journal_and_sealed_patch_are_rejected(tmp_path):
    ctx = fixture(tmp_path)
    begin(ctx)
    state_path = ctx.broker.root / "state.json"
    original = state_path.read_bytes()
    state = broker_module.read(state_path)
    state["actions"] = 0
    broker_module.write(state_path, state)
    with pytest.raises(broker_module.BrokerError, match="checkpoint differs"):
        ctx.broker.status()
    state_path.write_bytes(original)
    action(ctx, "solver-1", "submit", summary="Prepared patch")
    (ctx.broker.root / "submission.diff").write_text("changed")
    with pytest.raises(broker_module.BrokerError, match="submission artifact changed"):
        ctx.broker.status()


def test_crashed_tool_is_not_reexecuted_and_manager_seals_partial_with_consumed_budget(tmp_path):
    ctx = fixture(tmp_path)
    begin(ctx)
    def crash(*args):
        ctx.calls.append(("crashed", {}))
        raise KeyboardInterrupt("worker interrupted during command")
    ctx.workspace.execute = crash
    with pytest.raises(KeyboardInterrupt):
        action(ctx, "solver-1", "tool", name="run_command", arguments={"argv": ["python", "test.py"]})
    with pytest.raises(broker_module.BrokerError, match="unfinished broker action"):
        ctx.broker.status()
    sealed = ctx.broker.seal_partial(reason="WORKER_TERMINATED")
    assert sealed["actions"] == 3 and sealed["agent_completed"] is False
    assert ctx.broker.status()["unfinished_actions"] == 1
    assert len(ctx.calls) == 1


def test_committed_action_checkpoint_recovery_replays_no_repository_operation(tmp_path, monkeypatch):
    ctx = fixture(tmp_path)
    begin(ctx)
    original = broker_module.write
    def fail_checkpoint(path, value):
        if Path(path).name == "state.json":
            raise OSError("simulated checkpoint write interruption")
        return original(path, value)
    monkeypatch.setattr(broker_module, "write", fail_checkpoint)
    with pytest.raises(OSError):
        action(ctx, "solver-1", "tool", name="read_file", arguments={"path": "client.py"})
    monkeypatch.setattr(broker_module, "write", original)
    assert ctx.broker.status()["budget"]["requests_used"] == 3
    assert len(ctx.calls) == 1


def test_manager_revoke_prevents_reusing_same_native_context(tmp_path):
    ctx = fixture(tmp_path)
    begin(ctx)
    ctx.broker.revoke_worker("solver-1", reason="Native process terminated")
    assert ctx.broker.status()["status"] == "TERMINATED"
    with pytest.raises(broker_module.BrokerError, match="not waiting"):
        ctx.broker.issue_handoff("solver-retry")
    assert ctx.broker.seal_partial(reason="NATIVE_PROCESS_TERMINATED")["agent_completed"] is False


@pytest.mark.parametrize("fault", ["missing_callback", "wrong_bank", "duplicate_records", "invalid_checkpoint", "memory_budget"])
def test_invalid_memory_callback_fails_before_worker_packet_or_admission(tmp_path, fault):
    ctx = fixture(tmp_path, limits=HandoffLimits(max_memory_bytes=10) if fault == "memory_budget" else HandoffLimits())
    launch(ctx, "planner")
    action(ctx, "planner", "plan_subgoals", subgoals=SUBGOALS)
    action(ctx, "planner", "activate_subgoal", node_id="timeout")
    original = ctx.broker.memory_callback
    def broken(*args):
        result = original(*args)
        if fault == "wrong_bank":
            item = result["injections"][0]
            result["injections"] = [HandoffMemory(item.memory_id, item.kind, item.active_node_id,
                item.exact_text, item.sha256, item.source_content_sha256, "f" * 64)]
        elif fault == "duplicate_records":
            result["injections"] *= 2
        elif fault == "invalid_checkpoint":
            result["checkpoint"] = []
        return result
    ctx.broker.memory_callback = None if fault == "missing_callback" else broken
    with pytest.raises(broker_module.BrokerError):
        ctx.broker.issue_handoff("solver-1")
    status = ctx.broker.status()
    assert status["status"] == "WAITING_HANDOFF" and status["workers_issued"] == 1
    assert status["memory_records_reserved"] == 0
    assert not (ctx.broker.root / "packets" / "0002.json").exists()


def test_baseline_never_invokes_failing_external_memory_callback(tmp_path):
    ctx = fixture(tmp_path, "BASELINE")
    def forbidden(*args):
        raise AssertionError("BASELINE must never open memory")
    ctx.broker.memory_callback = forbidden
    begin(ctx)
    assert action(ctx, "solver-1", "recall")["result"]["injections"] == []
    assert ctx.broker.status()["memory_injections"] == 0


def test_unknown_authenticated_operation_is_charged_with_its_global_step(tmp_path):
    ctx = fixture(tmp_path)
    begin(ctx)
    response = action(ctx, "solver-1", "unsafe_external_action")
    assert not response["ok"] and response["step_no"] == 3
    assert response["budget"]["requests_used"] == 3
    assert ctx.calls == []


def test_immutable_packet_and_initial_checkpoint_cannot_be_replaced(tmp_path):
    ctx = fixture(tmp_path)
    foreign_path = ctx.broker.root / "packets" / "0001.json"
    broker_module.write_once(foreign_path, {"foreign": True})
    with pytest.raises(broker_module.BrokerError, match="immutable broker artifact"):
        ctx.broker.issue_handoff("planner")
    assert broker_module.read(foreign_path) == {"foreign": True}
    state_path = ctx.broker.root / "initial-state.json"
    state = broker_module.read(state_path)
    state["status"] = "RUNNING"
    broker_module.write(state_path, state)
    with pytest.raises(broker_module.BrokerError, match="initial checkpoint"):
        ctx.broker.status()
