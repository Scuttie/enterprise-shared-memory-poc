from __future__ import annotations

from copy import deepcopy
import json

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.context_projection import ContextProjectionError
from enterprise_memory.trimem.subgoal_context import (
    TaskSubgoalTraceStore,
    project_subgoal_context,
)
from enterprise_memory.trimem.working_graph import (
    Evidence,
    ShortTermWorkingGraph,
    SubtaskSpec,
)


def _row(step, node, tool, arguments, result):
    request = {"tool": tool, "arguments": arguments}
    return {
        "task_id": "task", "arm": "M0", "step_no": step,
        "active_node_id": node, "tool": tool, "status": "success",
        "request_payload": request, "result_payload": result,
        "request": {
            "sha256": sha256_bytes(canonical_bytes(request)),
            "bytes": len(canonical_bytes(request)),
        },
        "result": {
            "sha256": sha256_bytes(canonical_bytes(result)),
            "bytes": len(canonical_bytes(result)),
        },
    }


def _fixture():
    graph = ShortTermWorkingGraph("task", "Repair timeout handling", "org/repo")
    graph.add_subtask(SubtaskSpec(
        node_id="first", objective="Propagate the timeout argument",
        operation="forward timeout to callers",
    ))
    graph.add_subtask(SubtaskSpec(
        node_id="second", objective="Repair the retry boundary",
        operation="adjust retry exception handling", dependencies=("first",),
    ))
    graph.activate("first")
    history = [
        _row(1, "first", "write_file", {
            "path": "client.py", "content": "COMPLETED_RAW_PRIVATE_DETAIL",
        }, {"path": "client.py", "content_hash": "a" * 64, "bytes": 28}),
        _row(2, "first", "run_public_tests", {}, {
            "passed": False, "exit_code": 1,
            "stdout": "COMPLETED_RAW_TEST_OUTPUT", "stderr": "",
        }),
        _row(3, "second", "read_file", {"path": "retry.py"}, {
            "path": "retry.py", "content": "ACTIVE_PUBLIC_SOURCE_DETAIL\n",
        }),
    ]
    graph.complete_active(Evidence.capture(
        "tool_result", "Timeout forwarding changed; public tests still report exit code 1",
        history[1]["result_payload"], supports_completion=True,
        source="complete_subtask",
    ))
    graph.activate("second")
    return graph, history


def test_completed_raw_trace_becomes_grounded_summary_and_active_detail_remains():
    graph, history = _fixture()
    original_graph, original_history = graph.snapshot(), deepcopy(history)
    projection = project_subgoal_context(graph, history)
    body = projection.model_value()
    text = canonical_bytes(body).decode("utf-8")
    assert "COMPLETED_RAW_PRIVATE_DETAIL" not in text
    assert "COMPLETED_RAW_TEST_OUTPUT" not in text
    assert "ACTIVE_PUBLIC_SOURCE_DETAIL" in text
    assert len(body["active_history"]["observations"]) == 1
    assert body["active_history"]["observations"][0]["active_node_id"] == "second"
    summary = body["completed_subgoals"][0]
    evidence = graph.nodes["first"].completion_evidence[0]
    assert summary["status"] == "COMPLETED"
    assert summary["completion_evidence"][0]["summary"]["text"] == evidence.summary
    assert summary["completion_evidence"][0]["payload_sha256"] == evidence.payload_hash
    assert summary["tool_results"][1]["result_facts"]["passed"] is False
    assert summary["tool_results"][1]["result_facts"]["exit_code"] == 1
    assert summary["tool_results"][0]["result_facts"]["content_hash"]["text"] == "a" * 64
    assert summary["tool_results"][1]["result_reference"] == history[1]["result"]
    assert summary["trace_reference"]["sha256"] == sha256_bytes(canonical_bytes(history[:2]))
    assert graph.snapshot() == original_graph and history == original_history


def test_checkpoint_reconstruction_and_trace_retrieval_are_bound_and_return_copies():
    graph, history = _fixture()
    initial = project_subgoal_context(graph, history)
    restored_graph = ShortTermWorkingGraph.from_snapshot(json.loads(canonical_bytes(graph.snapshot())))
    restored_history = json.loads(canonical_bytes(history))
    restored = project_subgoal_context(restored_graph, restored_history)
    assert restored.model_value() == initial.model_value()
    assert restored.report_dict() == initial.report_dict()
    traces = TaskSubgoalTraceStore(restored_graph, restored_history)
    recalled = traces.retrieve_trace(task_id="task", subgoal_id="first")
    assert recalled == history[:2]
    recalled[0]["request_payload"]["arguments"]["content"] = "changed returned copy"
    restored_history[0]["result_payload"]["path"] = "changed original input"
    assert traces.retrieve_trace(task_id="task", subgoal_id="first") == history[:2]
    with pytest.raises(ContextProjectionError, match="task binding"):
        traces.retrieve_trace(task_id="other-task", subgoal_id="first")
    with pytest.raises(ContextProjectionError, match="unknown subgoal"):
        traces.retrieve_trace(task_id="task", subgoal_id="not-here")


@pytest.mark.parametrize("cap", [1024, 2048, 4096, 8192, 16000, 98304])
def test_combined_context_including_unicode_summaries_stays_under_byte_cap(cap):
    graph, history = _fixture()
    graph.nodes["first"].objective = "Repair timeout: " + "한글과 유니코드 🦋 \\\"\n" * 1000
    for step in range(4, 65):
        history.append(_row(step, "second", "read_file", {"path": "한글.py"}, {
            "path": "한글.py", "content": "줄 단위 공개 관찰 🦋\n" * 200,
        }))
    projection = project_subgoal_context(graph, history, max_bytes=cap)
    raw = canonical_bytes(projection.model_value())
    assert len(raw) <= cap
    assert json.loads(raw)["task_id"] == "task"
    assert projection.projected_history_bytes == len(raw)
    assert projection.projection_sha256 == sha256_bytes(raw)
    assert project_subgoal_context(graph, history, cap).model_value() == projection.model_value()
    record = projection.record(final_prompt=raw.decode("utf-8"))
    active = projection.model_value()["active_history"]
    assert record["final_prompt_bytes"] == len(raw)
    assert record["included_observation_count"] + record["omitted_observation_count"] == len(history) - 2
    assert sum(active["omitted_tool_counts"].values()) == active["omitted_observation_count"]


def test_summary_context_has_one_cap_when_task_has_many_completed_subgoals():
    graph = ShortTermWorkingGraph("task", "Repair repository callers", "org/repo")
    history = []
    for index in range(60):
        node = graph.add_subtask(SubtaskSpec(
            node_id=f"node-{index}", objective=f"Repair timeout caller {index}",
            operation="forward timeout",
        ))
        graph.activate(node.node_id)
        history.append(_row(index + 1, node.node_id, "read_file", {"path": "client.py"}, {
            "content": f"RAW_COMPLETED_{index}",
        }))
        graph.complete_active(Evidence.capture(
            "inspection", "Observed that caller forwards timeout", {"caller": index},
            supports_completion=True,
        ))
    projection = project_subgoal_context(graph, history, max_bytes=8192)
    body = projection.model_value()
    assert body["active_node_id"] is None
    assert len(canonical_bytes(body)) <= 8192
    assert "RAW_COMPLETED_" not in canonical_bytes(body).decode("utf-8")
    assert 0 < len(body["completed_subgoals"]) < 60
    assert len(body["completed_subgoals"]) + body["omitted_completed_subgoal_count"] == 60
    traces = TaskSubgoalTraceStore(graph, history)
    assert traces.retrieve_trace(task_id="task", subgoal_id="node-0") == history[:1]


@pytest.mark.parametrize("mutation, message", [
    (lambda row: row.update(task_id="other-task"), "task binding"),
    (lambda row: row.update(active_node_id="unknown"), "unknown subgoal"),
    (lambda row: row.update(hidden_grader={"gold_patch": "hidden"}), "only public tool"),
    (lambda row: row["result_payload"].update(content_hash="changed"), "exact evidence"),
    (lambda row: row.update(tool="hidden_grader"), "public tool identity"),
])
def test_foreign_or_non_public_history_and_tampered_references_are_rejected(mutation, message):
    graph, history = _fixture()
    mutation(history[0])
    with pytest.raises(ContextProjectionError, match=message):
        project_subgoal_context(graph, history)
    with pytest.raises(ContextProjectionError, match=message):
        TaskSubgoalTraceStore(graph, history)


def test_projected_outputs_do_not_mutate_future_reads():
    graph, history = _fixture()
    projection = project_subgoal_context(graph, history)
    original = projection.model_value()
    altered = projection.public_dict()
    altered["completed_subgoals"][0]["completion_evidence"][0]["summary"]["text"] = "changed"
    assert projection.model_value() == original


def test_empty_graph_history_projects_without_an_active_subgoal():
    graph = ShortTermWorkingGraph("task", "Inspect retry behavior", "org/repo")
    projection = project_subgoal_context(graph, [], 1024)
    body = projection.model_value()
    assert body["active_node_id"] is None
    assert body["completed_subgoals"] == []
    assert body["active_history"]["observations"] == []
    assert len(canonical_bytes(body)) <= 1024


@pytest.mark.parametrize("cap", [0, 1023, 98305, True, 2048.0])
def test_invalid_budget_is_rejected(cap):
    graph, history = _fixture()
    with pytest.raises(ContextProjectionError, match="cap is invalid"):
        project_subgoal_context(graph, history, cap)
