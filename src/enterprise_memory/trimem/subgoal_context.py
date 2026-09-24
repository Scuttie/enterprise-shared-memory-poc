"""Task-local, subgoal-chunked working context with recoverable public traces.

Completed subgoals expose grounded summaries; only the active subgoal exposes
public action/observation detail. Exact traces remain in the existing checkpoint
history and evidence ledger. This view and its retrieval index can be rebuilt
from a working-graph snapshot plus that history without a model call or a second
persistent store. Neither API accepts a hidden grader result.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .accounting import canonical_bytes, sha256_bytes
from .context_projection import (
    ContextProjectionError,
    MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
    bounded_text_record,
    project_tool_history_for_model,
)
from .working_graph import COMPLETED, SemanticSubtaskNode, ShortTermWorkingGraph, WorkingGraphError


_PUBLIC_TOOLS = frozenset({
    "list_files", "read_file", "search", "write_file", "replace_text",
    "run_public_tests", "run_command", "revise_subtask_dag", "complete_subtask",
})
_HISTORY_FIELDS = frozenset({
    "task_id", "arm", "step_no", "active_node_id", "tool", "request", "result",
    "wall_time_ms", "status", "request_payload", "result_payload",
})
_RESULT_FACTS = frozenset({
    "path", "passed", "exit_code", "timed_out", "error", "completed",
    "content_hash", "new_sha256", "prior_sha256", "full_file_sha256",
    "bytes", "old_bytes", "new_bytes", "replacements", "returned_count",
    "total_matching_count", "truncated", "dag_revised",
})


def _identity(value: Any) -> dict[str, Any]:
    raw = canonical_bytes(value)
    return {"sha256": sha256_bytes(raw), "bytes": len(raw)}


def _validated_history(
    graph: ShortTermWorkingGraph, history: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    steps: set[int] = set()
    for value in history:
        if not isinstance(value, Mapping) or set(value) - _HISTORY_FIELDS:
            raise ContextProjectionError("subgoal history must contain only public tool rows")
        row = deepcopy(dict(value))
        if row.get("task_id") != graph.task_id:
            raise ContextProjectionError("subgoal history task binding differs")
        if row.get("active_node_id") not in graph.nodes:
            raise ContextProjectionError("subgoal history refers to an unknown subgoal")
        step = row.get("step_no")
        if type(step) is not int or step < 1 or step in steps:
            raise ContextProjectionError("subgoal history step numbers must be unique positive integers")
        steps.add(step)
        request, result = row.get("request_payload"), row.get("result_payload")
        if not isinstance(request, Mapping) or not isinstance(result, Mapping):
            raise ContextProjectionError("subgoal history requires exact public request/result objects")
        if (
            request.get("tool") not in _PUBLIC_TOOLS
            or request.get("tool") != row.get("tool")
            or not isinstance(request.get("arguments"), Mapping)
            or row.get("status") not in {"success", "error"}
        ):
            raise ContextProjectionError("subgoal history public tool identity is invalid")
        for name, payload in (("request", request), ("result", result)):
            identity = _identity(payload)
            reference = row.get(name)
            if reference is not None and (
                not isinstance(reference, Mapping)
                or any(reference.get(key) != val for key, val in identity.items())
            ):
                raise ContextProjectionError("subgoal history differs from exact evidence reference")
        rows.append(row)
    return rows


class TaskSubgoalTraceStore:
    """Read-only task-bound index over a copy of checkpointed public tool history.

    Reconstruct this index after a restart or after new tools run. The runtime's
    checkpoint/evidence ledger owns persistence; this object never modifies it.
    Retrieval returns exact public rows and is intended for explicit task-local
    recall, not automatic reinjection into every subsequent prompt.
    """

    def __init__(
        self, graph: ShortTermWorkingGraph, history: Sequence[Mapping[str, Any]],
    ):
        self._task_id = graph.task_id
        self._traces: dict[str, list[dict[str, Any]]] = {key: [] for key in graph.nodes}
        for row in _validated_history(graph, history):
            self._traces[row["active_node_id"]].append(row)

    @property
    def task_id(self) -> str:
        return self._task_id

    def retrieve_trace(self, *, task_id: str, subgoal_id: str) -> list[dict[str, Any]]:
        if task_id != self.task_id:
            raise ContextProjectionError("trace retrieval task binding differs")
        if subgoal_id not in self._traces:
            raise ContextProjectionError("trace retrieval refers to an unknown subgoal")
        return deepcopy(self._traces[subgoal_id])

    def trace_reference(self, *, task_id: str, subgoal_id: str) -> dict[str, Any]:
        rows = self.retrieve_trace(task_id=task_id, subgoal_id=subgoal_id)
        return {
            "task_id": self.task_id, "subgoal_id": subgoal_id,
            "observation_count": len(rows), **_identity(rows),
        }


def _tool_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    result = row["result_payload"]
    facts = {}
    for key in sorted(_RESULT_FACTS & set(result)):
        value = result[key]
        # Do not copy arbitrary nested metadata or stdout/code into a summary.
        if value is None or type(value) in {bool, int, float}:
            facts[key] = value
        elif isinstance(value, str):
            facts[key] = bounded_text_record(value, maximum=160)
    return {
        "step_no": row["step_no"], "tool": row["tool"], "status": row["status"],
        "result_facts": facts,
        "request_reference": _identity(row["request_payload"]),
        "result_reference": _identity(result),
    }


def _completed_summary(
    node: SemanticSubtaskNode, rows: Sequence[Mapping[str, Any]],
    trace_reference: Mapping[str, Any], *, compact: bool = False,
) -> dict[str, Any]:
    if not node.completion_evidence or any(
        not item.supports_completion for item in node.completion_evidence
    ):
        raise ContextProjectionError("completed subgoal lacks supporting graph evidence")
    evidence_limit, result_limit = (1, 1) if compact else (4, 4)
    evidence = node.completion_evidence[-evidence_limit:]
    results = sorted(rows, key=lambda row: row["step_no"])[-result_limit:]
    # COMPLETED reports graph state. It is deliberately separate from the
    # literal public-test outcomes below: agent completion is not CI success.
    return {
        "subgoal_id": node.node_id, "status": node.status,
        "objective": bounded_text_record(node.objective, maximum=96 if compact else 256),
        "completion_evidence": [{
            "evidence_id": item.evidence_id,
            "summary": bounded_text_record(item.summary, maximum=96 if compact else 320),
            "payload_sha256": item.payload_hash,
        } for item in evidence],
        "omitted_completion_evidence_count": len(node.completion_evidence) - len(evidence),
        "tool_results": [_tool_summary(row) for row in results],
        "omitted_tool_result_count": len(rows) - len(results),
        "trace_reference": dict(trace_reference),
    }


@dataclass(frozen=True)
class SubgoalContextProjection:
    _body: Mapping[str, Any]
    raw_history_bytes: int
    projected_history_bytes: int
    projection_sha256: str
    cap: int

    def model_value(self) -> dict[str, Any]:
        return deepcopy(dict(self._body))

    def public_dict(self) -> dict[str, Any]:
        return self.model_value()

    def report_dict(self) -> dict[str, Any]:
        active = self._body["active_history"]
        completed = self._body["completed_subgoals"]
        return {
            "schema": "trimem/subgoal-context-projection-record/1.0",
            "raw_history_bytes": self.raw_history_bytes,
            "projected_history_bytes": self.projected_history_bytes,
            "included_observation_count": len(active["observations"]),
            "omitted_observation_count": active["omitted_observation_count"],
            "omitted_tool_counts": deepcopy(active["omitted_tool_counts"]),
            "completed_summary_count": len(completed),
            "omitted_completed_subgoal_count": self._body["omitted_completed_subgoal_count"],
            "summarized_observation_count": sum(
                row["trace_reference"]["observation_count"] for row in completed
            ),
            "other_observation_count": self._body["other_observation_count"],
            "projection_sha256": self.projection_sha256,
            "cap": self.cap,
        }

    def record(self, *, final_prompt: str, status: str = "BOUNDED") -> dict[str, Any]:
        raw = final_prompt.encode("utf-8")
        return {
            **self.report_dict(), "final_prompt_bytes": len(raw),
            "final_prompt_sha256": sha256_bytes(raw), "status": status,
        }


def project_subgoal_context(
    graph: ShortTermWorkingGraph,
    history: Sequence[Mapping[str, Any]],
    max_bytes: int = MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
) -> SubgoalContextProjection:
    """Project completed summaries plus active public detail under ONE UTF-8 cap.

    With an active trace, summaries get at most a third of the total cap; active
    observations use the remainder and the existing deterministic projection.
    Completed dependencies have priority over other completed subgoals. Whole
    summaries/observations are omitted when necessary, with explicit counters.
    Raw checkpoint history is never replaced by this lossy prompt view.
    """
    if type(max_bytes) is not int or not 1_024 <= max_bytes <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES:
        raise ContextProjectionError("subgoal context cap is invalid")
    # Validate graph state as well as history, including completion-evidence
    # membership, dependency order, and the active-node binding after restart.
    try:
        graph = ShortTermWorkingGraph.from_snapshot(graph.snapshot())
    except WorkingGraphError as exc:
        raise ContextProjectionError("subgoal context graph state is invalid") from exc
    store = TaskSubgoalTraceStore(graph, history)
    active_id = graph.active_node_id
    active_rows = (
        store.retrieve_trace(task_id=graph.task_id, subgoal_id=active_id)
        if active_id else []
    )
    completed = [node for node in graph.nodes.values() if node.status == COMPLETED]
    dependencies = set(graph.active_node.dependencies) if graph.active_node else set()
    completed.sort(key=lambda node: (
        node.node_id not in dependencies, -node.created_order, node.node_id,
    ))
    body: dict[str, Any] = {
        "schema": "trimem/subgoal-context/1.0", "task_id": graph.task_id,
        "active_node_id": active_id,
        "active_history": {
            "schema": "trimem/model-visible-tool-history/1.0", "observations": [],
            "omitted_observation_count": len(active_rows), "omitted_tool_counts": {},
        },
        "completed_subgoals": [],
        "omitted_completed_subgoal_count": len(completed),
        "other_observation_count": sum(
            row["active_node_id"] != active_id
            and graph.nodes[row["active_node_id"]].status != COMPLETED
            for row in history
        ),
    }
    base_bytes = len(canonical_bytes(body))
    if base_bytes > max_bytes:
        raise ContextProjectionError("required subgoal context metadata exceeds cap")
    summary_budget = max_bytes - base_bytes
    if active_rows:
        summary_budget = min(max_bytes // 3, max(0, summary_budget - 1_024))
    for node in completed:
        rows = store.retrieve_trace(task_id=graph.task_id, subgoal_id=node.node_id)
        reference = store.trace_reference(task_id=graph.task_id, subgoal_id=node.node_id)
        for compact in (False, True):
            candidate = _completed_summary(node, rows, reference, compact=compact)
            if len(canonical_bytes([*body["completed_subgoals"], candidate])) <= summary_budget:
                body["completed_subgoals"].append(candidate)
                body["omitted_completed_subgoal_count"] -= 1
                break
    if active_id:
        empty_history_bytes = len(canonical_bytes(body["active_history"]))
        remaining = max_bytes - len(canonical_bytes(body)) + empty_history_bytes
        projection = project_tool_history_for_model(
            active_rows, active_node_id=active_id,
            max_bytes=min(MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES, max(1_024, remaining)),
        )
        body["active_history"] = projection.model_value()
    while len(canonical_bytes(body)) > max_bytes:
        active = body["active_history"]
        if active["observations"]:
            removed = active["observations"].pop()
            active["omitted_observation_count"] += 1
            tool = removed["tool"]
            counts = active["omitted_tool_counts"]
            counts[tool] = counts.get(tool, 0) + 1
        elif body["completed_subgoals"]:
            body["completed_subgoals"].pop()
            body["omitted_completed_subgoal_count"] += 1
        else:
            raise ContextProjectionError("required subgoal context metadata exceeds cap")
    serialized = canonical_bytes(body)
    return SubgoalContextProjection(
        _body=body, raw_history_bytes=len(canonical_bytes(history)),
        projected_history_bytes=len(serialized),
        projection_sha256=sha256_bytes(serialized), cap=max_bytes,
    )
