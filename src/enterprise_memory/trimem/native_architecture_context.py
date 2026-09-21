"""Additive, model-free context handoffs for a future native ON/OFF runner.

This module assembles bytes; it does not launch workers, erase a conversation,
retrieve external memories, verify skills, or change a broker. A caller must
launch a *new* worker with ``fork_turns="none"`` and admit only the bound packet.
The exact public history remains in the owner-side context, not in the worker.
Hashes are integrity bindings to a trusted caller's records, not authentication.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import base64
import json
import re
from typing import Any, Mapping, Sequence

from .accounting import canonical_bytes, sha256_bytes
from .context_projection import (
    ContextProjectionError,
    MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
    MAX_SOLVE_PROMPT_UTF8_BYTES,
    project_tool_history_for_model,
)
from .subgoal_context import TaskSubgoalTraceStore, project_subgoal_context
from .working_graph import COMPLETED, ShortTermWorkingGraph, WorkingGraphError


SCHEMA = "skhynix/native-architecture-handoff/1.0"
ARMS = frozenset({"BASELINE", "PDF_MEMORY"})
_PRIVATE_FIELDS = frozenset({
    "hidden_grader", "gold_patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS",
    "fail_to_pass", "pass_to_pass", "grader_result", "grader_private",
})
_BODY_FIELDS = frozenset({
    "binding", "task", "graph", "tool_schema", "limits", "worker_launch",
    "memory_injections", "working_context", "trace_retrieval", "implementation_status",
})


class HandoffError(ContextProjectionError):
    pass


def _hash(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise HandoffError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HandoffError(f"{label} must be nonempty text")
    return value


def _public_copy(value: Any) -> Any:
    """Keep exact JSON values and reject known grader-only fields at any depth."""
    def visit(item):
        if isinstance(item, Mapping):
            if any(not isinstance(key, str) for key in item):
                raise HandoffError("public JSON keys must be strings")
            if _PRIVATE_FIELDS.intersection(item):
                raise HandoffError("grader-only fields are not public context")
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        elif item is not None and type(item) not in {str, int, float, bool}:
            raise HandoffError("public context must contain JSON values only")
    visit(value)
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise HandoffError("public context must contain finite JSON values") from exc


@dataclass(frozen=True)
class HandoffLimits:
    max_packet_bytes: int = MAX_SOLVE_PROMPT_UTF8_BYTES
    max_history_bytes: int = 48_000
    max_trace_bytes: int = 48_000
    max_memory_bytes: int = 12_000
    max_memory_injections: int = 3
    task_requests: int = 120
    task_seconds: int = 1_200

    def __post_init__(self):
        for key, value in asdict(self).items():
            minimum = 0 if key in {"max_memory_bytes", "max_memory_injections"} else 1
            if type(value) is not int or value < minimum:
                raise HandoffError(f"{key} must be a valid integer limit")
        if not 4_096 <= self.max_packet_bytes <= MAX_SOLVE_PROMPT_UTF8_BYTES:
            raise HandoffError("packet byte cap is invalid")
        if not 1_024 <= self.max_history_bytes <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES:
            raise HandoffError("history byte cap is invalid")
        if not 1_024 <= self.max_trace_bytes <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES:
            raise HandoffError("trace byte cap is invalid")
        if self.max_memory_bytes > MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES:
            raise HandoffError("memory byte cap is invalid")


@dataclass(frozen=True)
class HandoffMemory:
    """Already-authorised controller output; this type does not certify relevance."""
    memory_id: str
    kind: str
    active_node_id: str
    exact_text: str
    sha256: str
    source_content_sha256: str
    bank_sha256: str

    def __post_init__(self):
        for name in ("memory_id", "active_node_id", "exact_text"):
            _text(getattr(self, name), name)
        if self.kind not in {"SKILL", "REPOSITORY_SEMANTIC", "EPISODIC"}:
            raise HandoffError("unknown PDF memory layer")
        for name in ("sha256", "source_content_sha256", "bank_sha256"):
            _digest(getattr(self, name), name)
        if sha256_bytes(self.exact_text.encode("utf-8")) != self.sha256:
            raise HandoffError("memory text hash differs")

    def public_dict(self):
        return {**asdict(self), "byte_count": len(self.exact_text.encode("utf-8"))}


@dataclass(frozen=True)
class HandoffBinding:
    task_sha256: str
    graph_sha256: str
    history_sha256: str
    history_count: int
    tool_schema_sha256: str
    limits_sha256: str
    arm: str
    configuration_sha256: str
    bank_sha256: str
    worker_id: str
    active_node_id: str | None
    reason: str
    previous_worker_id: str | None
    previous_packet_sha256: str | None


@dataclass(frozen=True)
class NativeHandoffPacket:
    binding: HandoffBinding
    sha256: str
    _body: Mapping[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "body": deepcopy(dict(self._body)), "sha256": self.sha256}

    @property
    def utf8(self) -> bytes:
        return canonical_bytes(self.public_dict())


def validate_handoff(
    packet: Mapping[str, Any], *, expected_binding: HandoffBinding,
    expected_sha256: str, fork_turns: str, new_worker: bool,
) -> dict[str, Any]:
    """Check against trusted owner-side bindings before admitting worker input.

    ``new_worker`` and ``fork_turns`` must describe the actual launch. This
    function cannot inspect the host's conversation or establish those facts.
    """
    if fork_turns != "none" or new_worker is not True:
        raise HandoffError("handoff requires a new worker with fork_turns=none")
    if not isinstance(expected_binding, HandoffBinding):
        raise HandoffError("a trusted handoff binding is required")
    _digest(expected_sha256, "expected packet hash")
    value = _public_copy(packet)
    if not isinstance(value, dict) or set(value) != {"schema", "body", "sha256"}:
        raise HandoffError("handoff envelope fields differ")
    body = value["body"]
    if (value["schema"] != SCHEMA or not isinstance(body, dict)
            or set(body) != _BODY_FIELDS):
        raise HandoffError("handoff body schema differs")
    if value["sha256"] != expected_sha256 or _hash(body) != expected_sha256:
        raise HandoffError("handoff packet hash differs")
    if body["binding"] != asdict(expected_binding):
        raise HandoffError("handoff task, arm, worker, or frozen binding differs")
    if body["worker_launch"] != {
        "new_worker_required": True, "fork_turns": "none",
        "existing_conversation_erased": False,
    }:
        raise HandoffError("handoff launch contract differs")
    if body["implementation_status"] != {
        "scope": "PACKET_ASSEMBLY_FOUNDATION_ONLY", "runtime_wired": False,
        "live_worker_delivery_attested": False,
    }:
        raise HandoffError("handoff implementation scope differs")
    if not isinstance(body["limits"], dict) or set(body["limits"]) != set(asdict(HandoffLimits())):
        raise HandoffError("handoff limit fields differ")
    limits = HandoffLimits(**body["limits"])
    if _hash(body["limits"]) != expected_binding.limits_sha256:
        raise HandoffError("handoff limits binding differs")
    if len(canonical_bytes(value)) > limits.max_packet_bytes:
        raise HandoffError("handoff exceeds packet byte cap")
    return value


class TaskHandoffContext:
    """Owner-side immutable snapshot; exact traces never enter default packets.

    Create a new snapshot after a subgoal completes. The ordinary flat baseline
    uses the existing bounded projection (including its usual edit-body
    omission); it does not introduce PDF completed-subgoal summaries.
    """

    def __init__(self, *, task: Mapping[str, Any], graph: ShortTermWorkingGraph,
                 history: Sequence[Mapping[str, Any]], tool_schema: Mapping[str, Any]):
        self._task = _public_copy(task)
        required = {"task_id", "repository", "commit", "instruction"}
        if (not isinstance(self._task, dict) or not required <= set(self._task)
                or set(self._task) - required - {"files", "editable_paths"}):
            raise HandoffError("task must be the exact public coding-task shape")
        for name in required:
            _text(self._task[name], name)
        if "files" in self._task and (not isinstance(self._task["files"], dict)
                or any(not isinstance(v, str) for v in self._task["files"].values())):
            raise HandoffError("public task files must map names to text")
        if "editable_paths" in self._task and (not isinstance(self._task["editable_paths"], list)
                or any(not isinstance(v, str) for v in self._task["editable_paths"])):
            raise HandoffError("editable paths must be a list of text")
        if not isinstance(graph, ShortTermWorkingGraph):
            raise HandoffError("a public working graph is required")
        snapshot = _public_copy(graph.snapshot())
        for node in snapshot["nodes"]:
            for evidence in (*node["evidence"], *node["completion_evidence"]):
                if type(evidence["supports_completion"]) is not bool:
                    raise HandoffError("completion support must be boolean")
        try:
            self._graph = ShortTermWorkingGraph.from_snapshot(snapshot)
        except (WorkingGraphError, KeyError, TypeError, ValueError) as exc:
            raise HandoffError("handoff graph state is invalid") from exc
        if (self._graph.task_id != self._task["task_id"]
                or self._graph.repository != self._task["repository"]
                or self._graph.objective != self._task["instruction"].strip()):
            raise HandoffError("handoff graph task binding differs")
        if not isinstance(history, (list, tuple)):
            raise HandoffError("public history must be a sequence")
        self._history = _public_copy(history)
        self._traces = TaskSubgoalTraceStore(self._graph, self._history)
        if [row["step_no"] for row in self._history] != sorted(row["step_no"] for row in self._history):
            raise HandoffError("history must be in increasing broker step order")
        self._tool_schema = _public_copy(tool_schema)
        if not isinstance(self._tool_schema, dict) or not self._tool_schema:
            raise HandoffError("a nonempty public tool schema is required")

    def _common_graph(self):
        value = self._graph.snapshot()
        # Do not copy Evidence.attributes or anchors/operations merged from
        # those attributes. PDF summaries come only from the bounded projector.
        return {key: value[key] for key in (
            "schema_version", "task_id", "repository", "revision", "active_node_id",
        )} | {"nodes": [{key: row[key] for key in (
            "node_id", "objective", "status", "dependencies",
        )} for row in value["nodes"]]}

    def build_handoff(
        self, *, arm: str, worker_id: str, configuration_sha256: str,
        bank_sha256: str, limits: HandoffLimits = HandoffLimits(),
        memory_injections: Sequence[HandoffMemory] = (),
        previous_packet: NativeHandoffPacket | None = None,
    ) -> NativeHandoffPacket:
        if arm not in ARMS:
            raise HandoffError("unknown architecture arm")
        if any(row.get("arm") != arm for row in self._history):
            raise HandoffError("history row canonical architecture arm binding differs or is missing")
        _text(worker_id, "worker_id")
        _digest(configuration_sha256, "configuration hash")
        _digest(bank_sha256, "bank hash")
        if not isinstance(limits, HandoffLimits):
            raise HandoffError("typed handoff limits are required")
        if not isinstance(memory_injections, (list, tuple)) or any(
                not isinstance(item, HandoffMemory) for item in memory_injections):
            raise HandoffError("typed memory injections are required")
        if arm == "BASELINE" and memory_injections:
            raise HandoffError("baseline must receive zero external memory")
        if len({item.memory_id for item in memory_injections}) != len(memory_injections):
            raise HandoffError("duplicate memory injections")
        if any(item.active_node_id != self._graph.active_node_id or item.bank_sha256 != bank_sha256
               for item in memory_injections):
            raise HandoffError("memory active-subgoal or frozen-bank binding differs")
        if (len(memory_injections) > limits.max_memory_injections or
                sum(len(item.exact_text.encode("utf-8")) for item in memory_injections) > limits.max_memory_bytes):
            raise HandoffError("memory injection budget exceeded")
        common = {
            "task_sha256": _hash(self._task), "tool_schema_sha256": _hash(self._tool_schema),
            "limits_sha256": _hash(asdict(limits)), "arm": arm,
            "configuration_sha256": configuration_sha256, "bank_sha256": bank_sha256,
        }
        if previous_packet is None:
            if self._history or any(n.status == COMPLETED for n in self._graph.nodes.values()):
                raise HandoffError("initial handoff requires an empty history")
            reason, previous_worker, previous_hash = "INITIAL", None, None
        else:
            if not isinstance(previous_packet, NativeHandoffPacket):
                raise HandoffError("previous handoff must be an owner-side packet")
            prior = previous_packet.binding
            validate_handoff(previous_packet.public_dict(), expected_binding=prior,
                expected_sha256=previous_packet.sha256, fork_turns="none", new_worker=True)
            if any(getattr(prior, key) != value for key, value in common.items()):
                raise HandoffError("previous task, arm, tool, limit, config, or bank binding differs")
            if prior.worker_id == worker_id:
                raise HandoffError("handoff requires a different worker identity")
            if (prior.active_node_id == self._graph.active_node_id or self._graph.active_node_id is None
                    or (prior.active_node_id is not None and (
                        prior.active_node_id not in self._graph.nodes
                        or self._graph.nodes[prior.active_node_id].status != COMPLETED))):
                raise HandoffError("handoff requires a completed prior subgoal and a new active subgoal")
            if (prior.history_count > len(self._history) or
                    _hash(self._history[:prior.history_count]) != prior.history_sha256):
                raise HandoffError("prior history is not an exact prefix of the current history")
            reason, previous_worker, previous_hash = "SUBGOAL_CHANGE", prior.worker_id, previous_packet.sha256
        binding = HandoffBinding(**common, graph_sha256=_hash(self._graph.snapshot()),
            history_sha256=_hash(self._history), history_count=len(self._history),
            worker_id=worker_id, active_node_id=self._graph.active_node_id,
            reason=reason, previous_worker_id=previous_worker, previous_packet_sha256=previous_hash)
        body = {
            "binding": asdict(binding), "task": deepcopy(self._task),
            "graph": self._common_graph(), "tool_schema": deepcopy(self._tool_schema),
            "limits": asdict(limits), "worker_launch": {
                "new_worker_required": True, "fork_turns": "none", "existing_conversation_erased": False,
            },
            "implementation_status": {
                "scope": "PACKET_ASSEMBLY_FOUNDATION_ONLY", "runtime_wired": False,
                "live_worker_delivery_attested": False,
            },
            "memory_injections": [item.public_dict() for item in memory_injections],
            "working_context": {}, "trace_retrieval": {
                "enabled": arm == "PDF_MEMORY", "task_id": self._task["task_id"],
                "history_sha256": binding.history_sha256, "max_response_bytes": limits.max_trace_bytes,
                "scope": "EXPLICIT_TASK_LOCAL_PUBLIC_TRACE", "automatic_raw_reinjection": False,
                "oversized_row_retrieval": "EXPLICIT_CANONICAL_JSON_BASE64_CHUNKS",
            },
        }
        envelope_bytes = len(canonical_bytes({"schema": SCHEMA, "body": body, "sha256": "0" * 64}))
        history_cap = min(limits.max_history_bytes, limits.max_packet_bytes - envelope_bytes + 2)
        if history_cap < 1_024:
            raise HandoffError("required issue, graph, memory, or tool metadata exceeds packet budget")
        if arm == "BASELINE":
            if self._graph.active_node_id is None and not self._history:
                # The first worker can be a planner before any semantic node
                # exists. No synthetic subgoal or observation is needed.
                body["working_context"] = {
                    "schema": "trimem/model-visible-tool-history/1.0", "observations": [],
                    "omitted_observation_count": 0, "omitted_tool_counts": {},
                }
            else:
                body["working_context"] = project_tool_history_for_model(
                    self._history, active_node_id=self._graph.active_node_id, max_bytes=history_cap).model_value()
        else:
            body["working_context"] = project_subgoal_context(self._graph, self._history, history_cap).model_value()
        packet = NativeHandoffPacket(binding, _hash(body), deepcopy(body))
        validate_handoff(packet.public_dict(), expected_binding=binding,
            expected_sha256=packet.sha256, fork_turns="none", new_worker=True)
        return packet

    def _checked_trace(
        self, packet: Mapping[str, Any], *, expected_binding: HandoffBinding,
        expected_sha256: str, worker_id: str, task_id: str, subgoal_id: str,
        max_bytes: int,
    ):
        value = validate_handoff(packet, expected_binding=expected_binding,
            expected_sha256=expected_sha256, fork_turns="none", new_worker=True)
        body, bound = value["body"], expected_binding
        if bound.arm != "PDF_MEMORY":
            raise HandoffError("baseline has no PDF trace retrieval")
        if any(row.get("arm") != bound.arm for row in self._history):
            raise HandoffError("trace history arm binding differs")
        if worker_id != bound.worker_id or task_id != self._task["task_id"]:
            raise HandoffError("trace task or worker binding differs")
        if (bound.task_sha256 != _hash(self._task) or bound.graph_sha256 != _hash(self._graph.snapshot())
                or bound.history_sha256 != _hash(self._history)
                or bound.tool_schema_sha256 != _hash(self._tool_schema)):
            raise HandoffError("trace context is stale or belongs to a different owner snapshot")
        if type(max_bytes) is not int or not 1_024 <= max_bytes <= body["limits"]["max_trace_bytes"]:
            raise HandoffError("trace response byte cap is invalid")
        rows = self._traces.retrieve_trace(task_id=task_id, subgoal_id=subgoal_id)
        reference = self._traces.trace_reference(task_id=task_id, subgoal_id=subgoal_id)
        return rows, reference

    def retrieve_trace(
        self, packet: Mapping[str, Any], *, expected_binding: HandoffBinding,
        expected_sha256: str, worker_id: str, task_id: str, subgoal_id: str,
        max_bytes: int, start_after_step: int = 0,
    ) -> dict[str, Any]:
        """Explicit PDF-only paging of whole exact rows under a response-byte cap.

        The future broker must authorise the actual worker and charge this call
        to its task budget. No partial row is presented as an exact observation.
        """
        rows, reference = self._checked_trace(packet, expected_binding=expected_binding,
            expected_sha256=expected_sha256, worker_id=worker_id, task_id=task_id,
            subgoal_id=subgoal_id, max_bytes=max_bytes)
        if type(start_after_step) is not int or start_after_step < 0:
            raise HandoffError("trace cursor must be a nonnegative integer")
        if start_after_step and start_after_step not in {row["step_no"] for row in rows}:
            raise HandoffError("trace cursor is not an exact row in this subgoal")
        pending = [row for row in rows if row["step_no"] > start_after_step]
        result = {
            "schema": "skhynix/native-architecture-trace-page/1.0",
            "packet_sha256": expected_sha256, "worker_id": worker_id,
            "trace_reference": reference,
            "start_after_step": start_after_step, "rows": [], "next_after_step": None,
            "remaining_observation_count": len(pending),
        }
        for index, row in enumerate(pending):
            candidate = {**result, "rows": [*result["rows"], row],
                "next_after_step": row["step_no"] if index + 1 < len(pending) else None,
                "remaining_observation_count": len(pending) - index - 1}
            if len(canonical_bytes(candidate)) > max_bytes:
                break
            result = candidate
        if pending and not result["rows"]:
            raise HandoffError("one exact trace row cannot fit the response byte cap; use retrieve_trace_chunk")
        if len(canonical_bytes(result)) > max_bytes:
            raise HandoffError("trace reference metadata exceeds response byte cap")
        return deepcopy(result)

    def retrieve_trace_chunk(
        self, packet: Mapping[str, Any], *, expected_binding: HandoffBinding,
        expected_sha256: str, worker_id: str, task_id: str, subgoal_id: str,
        step_no: int, offset_bytes: int, max_bytes: int,
    ) -> dict[str, Any]:
        """Return exact canonical row bytes, explicitly typed as a byte fragment.

        UTF-8 codepoints may span chunks. Concatenate decoded base64 bytes,
        verify the full row hash/length, then parse JSON. This never labels a
        fragment as a complete tool observation or reads an arbitrary file.
        """
        rows, reference = self._checked_trace(packet, expected_binding=expected_binding,
            expected_sha256=expected_sha256, worker_id=worker_id, task_id=task_id,
            subgoal_id=subgoal_id, max_bytes=max_bytes)
        if type(step_no) is not int or step_no < 1:
            raise HandoffError("trace chunk step must be a positive integer")
        row = next((row for row in rows if row["step_no"] == step_no), None)
        if row is None:
            raise HandoffError("trace chunk step is not owned by this task and subgoal")
        raw = canonical_bytes(row)
        if type(offset_bytes) is not int or not 0 <= offset_bytes < len(raw):
            raise HandoffError("trace chunk byte cursor is outside the exact row")
        result = {
            "schema": "skhynix/native-architecture-trace-chunk/1.0",
            "packet_sha256": expected_sha256, "worker_id": worker_id,
            "trace_reference": reference, "step_no": step_no,
            "row_sha256": sha256_bytes(raw), "row_total_bytes": len(raw),
            "offset_bytes": offset_bytes, "encoding": "BASE64_CANONICAL_JSON_UTF8",
            "complete_observation": False, "requires_reassembly": True,
        }

        def candidate(length):
            end = offset_bytes + length
            return {**result, "chunk_bytes": length,
                "chunk_base64": base64.b64encode(raw[offset_bytes:end]).decode("ascii"),
                "next_offset_bytes": end if end < len(raw) else None}

        low, high = 0, min(len(raw) - offset_bytes, max_bytes)
        while low < high:
            middle = (low + high + 1) // 2
            if len(canonical_bytes(candidate(middle))) <= max_bytes:
                low = middle
            else:
                high = middle - 1
        if low == 0:
            raise HandoffError("trace chunk metadata leaves no bytes within response cap")
        return candidate(low)
