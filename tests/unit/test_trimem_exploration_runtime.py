from __future__ import annotations

from dataclasses import replace
import json

import pytest

from enterprise_memory.trimem.accounting import (
    CallRecord, RawEvidenceLedger, RunAccounting, canonical_bytes, sha256_bytes,
)
from enterprise_memory.trimem.adaptive_horizon import AdaptiveHorizonPolicy
from enterprise_memory.trimem.agent_runtime import (
    CellScientificFailure, CodingTask, InjectedCrash, NoMemoryController,
)
from enterprise_memory.trimem.checkpoint import CheckpointMismatch, FileCheckpointStore
from enterprise_memory.trimem.exploration_runtime import (
    ExplorationPolicy, ExplorationSkhynixAgentRuntime, ExplorationTriMemAgentRuntime,
    repeated_observation_summary,
)
from enterprise_memory.trimem.gateway import ReplayModelGateway
from enterprise_memory.trimem.grader import ReplayGraderGateway
from enterprise_memory.trimem.runtime_lock import RuntimeLimits, RuntimeLock
from enterprise_memory.trimem.retrieval import MemoryInjection, MemoryKind
from enterprise_memory.trimem.skill_runtime import SkillLayer
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


RUNTIMES = [ExplorationTriMemAgentRuntime, ExplorationSkhynixAgentRuntime]


def task():
    def public_test(files):
        namespace = {}
        exec(files["value.py"], namespace)
        passed = namespace["double"](3) == 6
        return passed, "double(3) == 6" if passed else "double(3) differs from 6", ""

    return CodingTask(
        "exploration-fixture", "org", "user", "example/repo", "a" * 40,
        "Double the input value and verify the arithmetic.",
        {"value.py": "def double(value):\n    return value\n"}, ("value.py",), public_test,
    )


def graph():
    value = task()
    result = ShortTermWorkingGraph(value.task_id, value.instruction, value.repository)
    result.add_subtask(SubtaskSpec("Double input arithmetic", "double", node_id="S1"))
    result.activate("S1")
    return result


def lock():
    return RuntimeLock(limits=RuntimeLimits(
        max_steps_per_subtask=24, max_agent_steps=48, max_solve_calls=48,
    ))


def runtime(tmp_path, model, cls=ExplorationTriMemAgentRuntime, **kwargs):
    return cls(
        runtime_lock=kwargs.pop("runtime_lock", lock()), model_gateway=model,
        grader_gateway=ReplayGraderGateway(
            task().public_test, fixture_digest=sha256_bytes(b"exploration-arithmetic"),
        ),
        memory_controller=NoMemoryController(),
        evidence=RawEvidenceLedger(tmp_path / "evidence"),
        checkpoint_store=FileCheckpointStore(tmp_path / "checkpoints"), **kwargs,
    )


def observation(step, tool="read_file", arguments=None, result=None, status="success", node="S1"):
    return {
        "task_id": task().task_id,
        "step_no": step, "active_node_id": node, "tool": tool, "status": status,
        "request_payload": {"tool": tool, "arguments": arguments or {"path": "value.py"}},
        "result_payload": result or {"path": "value.py", "content": "VALUE = 1\n"},
    }


def solve_record(step, *, node="S1", status="success", kind="solve"):
    return CallRecord(
        task_id=task().task_id, arm="M0", step_no=step, call_kind=kind,
        logical_call_id=f"fixture:{kind}:{step}", provider="replay", model="fixture",
        input_tokens=10, output_tokens=5, wall_time_ms=0, prompt_hash="a" * 64,
        response_hash="b" * 64, active_node_id=node, status=status,
    )


def state(request):
    return json.loads(request.prompt.rsplit("\n\nSTATE:\n", 1)[1])


@pytest.mark.parametrize("cls", RUNTIMES)
def test_budget_uses_all_accounted_solve_calls_and_binds_actual_prompt(tmp_path, cls):
    runner = runtime(tmp_path, ReplayModelGateway(lambda request: ""), cls)
    accounting = RunAccounting()
    for call in (
        solve_record(0, kind="decompose"), solve_record(1, node="earlier"),
        solve_record(2, status="error"), solve_record(3, status="SOLVE_FUNCTION_ARGUMENT_SCHEMA_FAILURE"),
    ):
        accounting.add_call(call)
    history = [observation(1), observation(2), observation(3, status="error")]
    request, projection = runner._build_solve_request(
        task(), "M0", graph(), history, (), accounting, 4,
    )
    body = state(request)
    guidance = body["exploration_guidance"]
    budget = guidance["budget"]
    assert budget["task_solve_calls_used"] == 3
    assert budget["active_subtask_solve_calls_used"] == 2
    assert budget["task_solve_calls_remaining"] == 45
    assert budget["active_subtask_solve_calls_remaining"] == 22
    assert budget["global_steps_remaining"] == 45
    assert budget["effective_active_subtask_actions_remaining"] == 22
    assert budget["solve_output_tokens_remaining"] == lock().limits.max_total_solve_output_tokens_per_task_arm - 15
    assert guidance["repetition"]["warnings"][0]["successful_execution_count"] == 2
    assert projection["final_prompt_bytes"] == len(request.prompt.encode("utf-8"))
    assert projection["final_prompt_sha256"] == sha256_bytes(request.prompt.encode("utf-8"))
    assert projection["exploration_guidance_sha256"] == sha256_bytes(canonical_bytes(guidance))
    assert projection["exploration_guidance_bytes"] == len(canonical_bytes(guidance))
    assert request.prompt_projection == projection
    assert ("subgoal_working_memory" in body) is (cls is ExplorationSkhynixAgentRuntime)
    _, base_projection = super(type(runner).__mro__[1], runner)._build_solve_request(
        task(), "M0", graph(), history, (), accounting, 4,
    )
    assert projection["projection_sha256"] == base_projection["projection_sha256"]


@pytest.mark.parametrize("tool", ["read_file", "search", "list_files"])
def test_repeated_successful_exact_observations_are_counted(tool):
    rows = [observation(1, tool), observation(2, tool, status="error"), observation(3, tool)]
    before = canonical_bytes(rows)
    summary = repeated_observation_summary(rows, ExplorationPolicy())
    assert summary["extra_identical_read_executions"] == 1
    assert summary["successful_read_executions_in_epoch"] == 2
    assert summary["warnings"][0]["first_step"] == 1
    assert summary["warnings"][0]["last_step"] == 3
    assert canonical_bytes(rows) == before


@pytest.mark.parametrize("tool", ["write_file", "replace_text", "run_command", "run_public_tests", "future_mutator"])
@pytest.mark.parametrize("status", ["success", "error"])
def test_possible_mutations_reset_reads_even_on_failure(tool, status):
    rows = [observation(1), observation(2), observation(3, tool, status=status), observation(4)]
    summary = repeated_observation_summary(rows, ExplorationPolicy())
    assert summary["epoch_start_step"] == 3
    assert summary["successful_read_executions_in_epoch"] == 1
    assert summary["warnings"] == []


def test_changed_result_starts_new_epoch_and_changed_arguments_are_distinct():
    rows = [observation(1), observation(2, arguments={"path": "other.py"}),
            observation(3, result={"path": "value.py", "content": "VALUE = 2\n"})]
    summary = repeated_observation_summary(rows, ExplorationPolicy())
    assert summary["warnings"] == []
    assert summary["epoch_start_step"] == 3
    assert summary["successful_read_executions_in_epoch"] == 1


def test_graph_transition_keeps_real_repetition_and_bounded_warning_counts():
    rows = []
    for index in range(6):
        arguments = {"path": f"file{index}.py", "query": "한" * 2000}
        rows.extend([observation(index * 3 + 1, arguments=arguments),
                     observation(index * 3 + 2, "complete_subtask"),
                     observation(index * 3 + 3, arguments=arguments, node="S2")])
    summary = repeated_observation_summary(rows, ExplorationPolicy())
    assert summary["repeated_request_count"] == 6
    assert summary["extra_identical_read_executions"] == 6
    assert len(summary["warnings"]) == 4
    assert summary["omitted_warning_count"] == 2
    assert summary["warnings"][0]["last_active_node_id"] == "S2"
    preview = summary["warnings"][0]["argument_preview"]
    assert preview["truncated"]
    assert len((preview["head"] + preview["tail"]).encode("utf-8")) <= 512


def responder(captured):
    def respond(request):
        if request.call_kind == "decompose":
            return json.dumps({"subtasks": [{"id": "S1", "objective": "Double input arithmetic",
                "predicted_operation": "double", "depends_on": []}]})
        if request.call_kind == "extract":
            return json.dumps({"episode": {"summary": "Doubled arithmetic input",
                "action": "Edited arithmetic and observed a test", "outcome": "passed"},
                "semantic_candidate": None})
        captured.append(request)
        step = request.step_no
        if step == 1:
            action = {"tool": "read_file", "arguments": {"path": "missing.py"}}
        elif step in (2, 3):
            action = {"tool": "read_file", "arguments": {"path": "value.py"}}
        elif step == 4:
            assert state(request)["exploration_guidance"]["repetition"]["warnings"][0]["successful_execution_count"] == 2
            action = {"tool": "write_file", "arguments": {
                "path": "value.py", "content": "def double(value):\n    return value * 2\n"}}
        elif step == 5:
            assert state(request)["exploration_guidance"]["repetition"]["warnings"] == []
            action = {"tool": "run_public_tests", "arguments": {}}
        else:
            action = {"tool": "complete_subtask", "arguments": {"evidence": "Returned double(3) == 6 public test passed"}}
        return json.dumps(action)
    return respond


@pytest.mark.parametrize("cls", RUNTIMES)
@pytest.mark.parametrize("crash", [None, "checkpoint", "tool", "model"])
def test_real_runtime_patch_public_test_and_resume_keep_truthful_budgets(tmp_path, cls, crash):
    captured = []
    model = ReplayModelGateway(responder(captured))
    runner = runtime(tmp_path, model, cls)
    if crash is not None:
        controls = ({"crash_after_checkpoints": 8} if crash == "checkpoint" else
                    {"crash_after_tool_evidence_step": 3} if crash == "tool" else
                    {"crash_after_model_response_step": 3})
        with pytest.raises(InjectedCrash):
            runner.run(task(), arm="M0", run_id="resume", **controls)
        # Recreate the runtime object to prove no transient tracking is needed.
        runner = runtime(tmp_path, model, cls)
    result = runner.run(task(), arm="M0", run_id="resume", resume=crash is not None)
    assert result.agent_completed and result.resolved
    assert result.accounting["summary"]["by_call_kind"]["solve"]["calls"] == 6
    assert len(model.invocations) == len(set(model.invocations))
    assert [state(request)["exploration_guidance"]["budget"]["task_solve_calls_used"]
            for request in captured] == list(range(6))
    assert [state(request)["exploration_guidance"]["budget"]["active_subtask_solve_calls_remaining"]
            for request in captured] == list(range(24, 18, -1))


def test_policy_changes_reject_checkpoint_resume(tmp_path):
    model = ReplayModelGateway(responder([]))
    runner = runtime(tmp_path, model)
    with pytest.raises(InjectedCrash):
        runner.run(task(), arm="M0", run_id="bound", crash_after_checkpoints=4)
    changed = runtime(tmp_path, model, exploration_policy=ExplorationPolicy(reserve_final_actions=3))
    before = len(model.invocations)
    with pytest.raises(CheckpointMismatch):
        changed.run(task(), arm="M0", run_id="bound", resume=True)
    assert len(model.invocations) == before


@pytest.mark.parametrize("cls", RUNTIMES)
def test_added_guidance_prompt_cap_failure_is_graded_before_solve_send(tmp_path, monkeypatch, cls):
    import enterprise_memory.trimem.exploration_runtime as module
    monkeypatch.setattr(module, "MAX_SOLVE_PROMPT_UTF8_BYTES", 200)
    captured = []
    model = ReplayModelGateway(responder(captured))
    result = runtime(tmp_path, model, cls).run(task(), arm="M0")
    assert result.cell_status == "CELL_SCIENTIFIC_FAILURE"
    assert result.model_failure_class == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    assert captured == []
    assert len(result.accounting["graders"]) == 1


def test_final_action_guidance_reflects_smallest_limit(tmp_path):
    limited = replace(lock(), limits=replace(lock().limits, max_agent_steps=5))
    runner = runtime(tmp_path, ReplayModelGateway(lambda request: ""), runtime_lock=limited)
    request, _ = runner._build_solve_request(task(), "M0", graph(), [], (), RunAccounting(), 5)
    budget = state(request)["exploration_guidance"]["budget"]
    assert budget["effective_active_subtask_actions_remaining"] == 1
    assert budget["suggested_final_actions_to_reserve"] == 1
    assert budget["final_action_reserve_reached"] is True


@pytest.mark.parametrize("kwargs", [
    {"repetition_threshold": 1}, {"reserve_final_actions": True},
    {"max_repeat_warnings": 17}, {"reserve_final_actions": 0},
])
def test_invalid_policy_rejected(kwargs):
    with pytest.raises(ValueError):
        ExplorationPolicy(**kwargs)


def test_policy_is_hash_bound_and_adaptive_horizon_refused(tmp_path):
    policy = ExplorationPolicy()
    assert policy.content_hash == sha256_bytes(canonical_bytes(policy.manifest()))
    assert policy.content_hash != ExplorationPolicy(repetition_threshold=3).content_hash
    with pytest.raises(ValueError, match="adaptive horizon disabled"):
        runtime(tmp_path, ReplayModelGateway(lambda request: ""), runtime_lock=RuntimeLock(
            adaptive_horizon=AdaptiveHorizonPolicy(enabled=True)))


@pytest.mark.parametrize("cls,kind", [
    (ExplorationTriMemAgentRuntime, MemoryKind.ORG_SEMANTIC),
    (ExplorationSkhynixAgentRuntime, SkillLayer.REPOSITORY_SEMANTIC),
])
def test_nonempty_memory_is_preserved_and_recovery_hook_rejects_context_drift(tmp_path, cls, kind):
    runner = runtime(tmp_path, ReplayModelGateway(lambda request: ""), cls)
    value, working = task(), graph()
    raw = "Double the arithmetic input; verify the returned result.".encode("utf-8")
    injection = MemoryInjection("memory", kind, "S1", raw.decode("utf-8"), raw, len(raw),
                                sha256_bytes(raw), 1.0, 0.0, "a" * 64, "1")
    with pytest.raises(CheckpointMismatch, match="prepared context"):
        runner._solve_prompt(value, working, [], (injection,))
    request, _ = runner._build_solve_request(value, "M2", working, [], (injection,), RunAccounting(), 1)
    assert raw.decode("utf-8") in request.prompt
    assert runner._solve_prompt(value, working, [], (injection,)) == request.prompt
    with pytest.raises(CheckpointMismatch, match="prepared context"):
        runner._solve_prompt(value, working, [observation(1)], (injection,))
    with pytest.raises(CheckpointMismatch, match="prepared context"):
        runner._solve_prompt(value, working, [], (replace(injection, memory_version="2"),))
    hashes = runner._configuration_hashes(value)
    assert hashes["exploration_policy"] == ExplorationPolicy().content_hash
    assert ("skhynix_subgoal_context" in hashes) is (cls is ExplorationSkhynixAgentRuntime)
