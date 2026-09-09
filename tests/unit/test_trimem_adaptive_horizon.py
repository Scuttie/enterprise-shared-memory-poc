from __future__ import annotations

import json

import pytest

from enterprise_memory.trimem.accounting import RawEvidenceLedger, sha256_bytes
from enterprise_memory.trimem.adaptive_horizon import (
    ADAPTIVE_HORIZON_TERMINAL_KEY,
    AdaptiveHorizonPolicy,
    AdaptiveHorizonTracker,
    recognized_test_command,
)
from enterprise_memory.trimem.agent_runtime import (
    CodingTask,
    InjectedCrash,
    NoMemoryController,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.checkpoint import FileCheckpointStore
from enterprise_memory.trimem.gateway import ReplayModelGateway
from enterprise_memory.trimem.grader import ReplayGraderGateway
from enterprise_memory.trimem.runtime_lock import RuntimeLock


def _policy() -> AdaptiveHorizonPolicy:
    return AdaptiveHorizonPolicy(enabled=True)


def test_adaptive_horizon_requires_fresh_high_water_for_each_extension() -> None:
    tracker = AdaptiveHorizonTracker(_policy(), base_steps_per_subtask=8)

    observed = tracker.observe_successful_tool_result(
        node_id="S1",
        step_no=1,
        tool="write_file",
        arguments={"path": "value.py", "content": "VALUE = 2\n"},
        result={"path": "value.py"},
        canonical_git_diff="first canonical diff",
    )
    assert [row["kind"] for row in observed] == ["PATCH_DIFF_HIGH_WATER"]
    assert tracker.observe_successful_tool_result(
        node_id="S1",
        step_no=7,
        tool="read_file",
        arguments={"path": "value.py"},
        result={"content": "VALUE = 2\n"},
        canonical_git_diff="first canonical diff",
    ) == ()

    first = tracker.extend_at_boundary(
        node_id="S1", observed_node_steps=8, next_step_no=9
    )
    assert first is not None
    assert (first["prior_step_limit"], first["extended_step_limit"]) == (8, 12)
    assert tracker.extend_at_boundary(
        node_id="S1", observed_node_steps=12, next_step_no=13
    ) is None

    tracker.observe_successful_tool_result(
        node_id="S1",
        step_no=9,
        tool="write_file",
        arguments={"path": "value.py", "content": "VALUE = 200\n"},
        result={"path": "value.py"},
        canonical_git_diff="a longer canonical git diff than the first one",
    )
    second = tracker.extend_at_boundary(
        node_id="S1", observed_node_steps=12, next_step_no=13
    )
    assert second is not None
    assert (second["prior_step_limit"], second["extended_step_limit"]) == (12, 16)
    assert tracker.extension_count == 2
    assert tracker.extend_at_boundary(
        node_id="S1", observed_node_steps=16, next_step_no=17
    ) is None


@pytest.mark.parametrize(
    ("argv", "recognized"),
    [
        (["pytest", "-q"], True),
        (["python", "-m", "unittest"], True),
        (["go", "test", "./..."], True),
        (["npm", "run", "test:unit"], True),
        (["gradlew", ":app:test"], True),
        (["python", "script.py"], False),
        (["sh", "-c", "pytest"], False),
        (["true"], False),
    ],
)
def test_recognized_test_command_is_shell_free_and_locked(argv, recognized) -> None:
    assert recognized_test_command({"argv": argv}) is recognized


def test_only_first_successful_recognized_test_is_test_progress() -> None:
    tracker = AdaptiveHorizonTracker(_policy(), base_steps_per_subtask=8)
    common = {
        "node_id": "S1",
        "canonical_git_diff": "",
    }
    assert tracker.observe_successful_tool_result(
        **common,
        step_no=1,
        tool="run_command",
        arguments={"argv": ["pytest", "-q"]},
        result={"exit_code": 1, "timed_out": False},
    ) == ()
    assert tracker.observe_successful_tool_result(
        **common,
        step_no=2,
        tool="run_command",
        arguments={"argv": ["true"]},
        result={"exit_code": 0, "timed_out": False},
    ) == ()
    progress = tracker.observe_successful_tool_result(
        **common,
        step_no=3,
        tool="run_command",
        arguments={"argv": ["pytest", "-q"]},
        result={"exit_code": 0, "timed_out": False},
    )
    assert [row["kind"] for row in progress] == ["TEST_PASS_HIGH_WATER"]
    assert tracker.observe_successful_tool_result(
        **common,
        step_no=4,
        tool="run_public_tests",
        arguments={},
        result={"passed": True},
    ) == ()


def test_adaptive_horizon_checkpoint_round_trip_and_tamper_rejection() -> None:
    tracker = AdaptiveHorizonTracker(_policy(), base_steps_per_subtask=8)
    tracker.observe_successful_tool_result(
        node_id="S1",
        step_no=1,
        tool="run_public_tests",
        arguments={},
        result={"passed": True},
        canonical_git_diff="",
    )
    tracker.extend_at_boundary(node_id="S1", observed_node_steps=8, next_step_no=9)
    state = tracker.checkpoint_state()
    restored = AdaptiveHorizonTracker(
        _policy(), base_steps_per_subtask=8, checkpoint_state=state
    )
    assert restored.checkpoint_state() == state

    state["nodes"]["S1"]["current_step_limit"] = 16
    with pytest.raises(ValueError, match="inconsistent"):
        AdaptiveHorizonTracker(
            _policy(), base_steps_per_subtask=8, checkpoint_state=state
        )


def _task() -> CodingTask:
    return CodingTask(
        task_id="adaptive-horizon-fixture",
        org_id="org",
        user_id="user",
        repository="example/repo",
        commit="f" * 40,
        instruction="Make the fixture value larger and finish after verification.",
        files={"value.py": "VALUE = 1\n"},
        editable_paths=("value.py",),
    )


def _model_response(request) -> str:
    if request.call_kind == "decompose":
        return json.dumps({
            "subtasks": [{
                "id": "S1",
                "objective": "increase and verify the fixture value",
                "predicted_operation": "edit and inspect value.py",
                "depends_on": [],
            }]
        })
    if request.call_kind == "extract":
        return json.dumps({
            "episode": {
                "summary": "The fixture value was increased.",
                "action": "Edited and inspected value.py.",
                "outcome": "passed",
            },
            "semantic_candidate": None,
        })
    step = request.step_no
    if step == 1:
        action = {
            "tool": "write_file",
            "arguments": {"path": "value.py", "content": "VALUE = 2\n"},
        }
    elif step == 9:
        action = {
            "tool": "write_file",
            "arguments": {
                "path": "value.py",
                "content": "VALUE = 200\n# verified after initial progress\n",
            },
        }
    elif step == 13:
        action = {
            "tool": "complete_subtask",
            "arguments": {"evidence": "two durable patch high-water increases"},
        }
    else:
        action = {"tool": "read_file", "arguments": {"path": "value.py"}}
    return json.dumps(action)


def _runtime(tmp_path, model: ReplayModelGateway) -> TriMemAgentRuntime:
    return TriMemAgentRuntime(
        runtime_lock=RuntimeLock(adaptive_horizon=_policy()),
        model_gateway=model,
        grader_gateway=ReplayGraderGateway(
            lambda files: (
                "VALUE = 200" in files["value.py"],
                "credential-free adaptive fixture",
                "",
            ),
            fixture_digest=sha256_bytes(b"adaptive-horizon-grader-fixture"),
        ),
        memory_controller=NoMemoryController(),
        evidence=RawEvidenceLedger(tmp_path / "evidence"),
        checkpoint_store=FileCheckpointStore(tmp_path / "checkpoints"),
    )


def _no_progress_response(request) -> str:
    if request.call_kind == "decompose":
        return json.dumps({
            "subtasks": [{
                "id": "S1",
                "objective": "inspect the fixture without claiming completion",
                "predicted_operation": "inspect value.py",
                "depends_on": [],
            }]
        })
    if request.call_kind == "extract":
        return json.dumps({
            "episode": {
                "summary": "No repository progress was made.",
                "action": "Repeated the same inspection.",
                "outcome": "failed",
            },
            "semantic_candidate": None,
        })
    return json.dumps({
        "tool": "read_file",
        "arguments": {"path": "value.py"},
    })


def test_no_progress_retains_original_cap_and_terminal_reason(tmp_path) -> None:
    runtime = _runtime(tmp_path, ReplayModelGateway(_no_progress_response))
    result = runtime.run(_task(), arm="M0", run_id="no-progress")

    assert result.cell_status == "CELL_SCIENTIFIC_FAILURE"
    assert result.model_failure_class == "per-subtask step cap reached"
    assert result.agent_completed is False
    assert result.accounting["summary"]["by_call_kind"]["solve"]["calls"] == 8
    terminal = runtime.checkpoints.load(
        "no-progress", required_config_hashes=None
    )
    state = terminal.terminal_payload[ADAPTIVE_HORIZON_TERMINAL_KEY]
    assert state["nodes"]["S1"]["current_step_limit"] == 8
    assert state["extension_events"] == []
    assert state["progress_events"] == []


def test_runtime_adaptive_horizon_extension_is_checkpointed_and_resume_safe(
    tmp_path,
) -> None:
    model = ReplayModelGateway(_model_response)
    runtime = _runtime(tmp_path, model)
    task = _task()

    # Counted checkpoints: DECOMPOSED=1, two per solve step through step 8=17,
    # then the independently durable 8->12 horizon extension=18.
    with pytest.raises(InjectedCrash):
        runtime.run(
            task,
            arm="M0",
            run_id="adaptive-resume",
            crash_after_checkpoints=18,
        )
    checkpoint = runtime.checkpoints.load(
        "adaptive-resume", required_config_hashes=None
    )
    state = checkpoint.terminal_payload[ADAPTIVE_HORIZON_TERMINAL_KEY]
    assert state["nodes"]["S1"]["current_step_limit"] == 12
    assert len(state["extension_events"]) == 1
    before = tuple(model.invocations)

    result = runtime.run(task, arm="M0", run_id="adaptive-resume", resume=True)
    assert result.cell_status == "AGENT_COMPLETED"
    assert result.resolved is True
    assert result.accounting["summary"]["by_call_kind"]["solve"]["calls"] == 13
    assert len(model.invocations) == len(set(model.invocations))
    assert set(before) < set(model.invocations)

    terminal = runtime.checkpoints.load(
        "adaptive-resume", required_config_hashes=None
    )
    terminal_state = terminal.terminal_payload[ADAPTIVE_HORIZON_TERMINAL_KEY]
    assert [
        row["extended_step_limit"]
        for row in terminal_state["extension_events"]
    ] == [12, 16]
    assert len(terminal_state["progress_events"]) == 2


def test_disabled_policy_preserves_legacy_runtime_manifest() -> None:
    legacy = RuntimeLock()
    assert "adaptive_horizon" not in legacy.to_manifest()
    enabled = RuntimeLock(adaptive_horizon=_policy())
    assert enabled.to_manifest()["adaptive_horizon"] == _policy().manifest(
        base_steps_per_subtask=8
    )
    assert enabled.to_manifest()["limits"] == legacy.to_manifest()["limits"]
