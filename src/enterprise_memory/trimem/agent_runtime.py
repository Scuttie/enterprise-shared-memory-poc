"""Iterative coding-agent runtime that connects every TriMem V1 stage.

The runtime is deliberately benchmark-arm agnostic.  M0, M1, and M2 receive
the same prompt/tool/parser/step lock and differ only through a memory
controller.  The official grader is behind a separate interface, so the
credential-free replay exercises the same boundary without claiming that an
official container was executed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from typing import Any, Mapping, Optional, Protocol

from .accounting import (
    CallRecord,
    GraderRecord,
    RawEvidenceLedger,
    RunAccounting,
    ToolRecord,
    canonical_bytes,
    sha256_bytes,
    strict_json_loads,
)
from .checkpoint import CheckpointMismatch, FileCheckpointStore, RuntimeCheckpoint
from .gateway import (
    GatewayInvocationFailure,
    GatewayRequest,
    ModelGateway,
    RecordingModelGateway,
    parse_tool_action,
    strict_json_object,
)
from .grader import (
    GradeRequest,
    GradeResult,
    GraderGateway,
    GraderInvocationFailure,
    RecordingGraderGateway,
)
from .retrieval import MemoryInjection, RecallDecision
from .provider_output_contracts import output_contract
from .runtime_lock import RuntimeLock
from .working_graph import Evidence, ShortTermWorkingGraph, SubtaskSpec
from .workspace import (
    InMemoryWorkspaceFactory,
    RepositoryWorkspace,
    RecordingToolExecutor,
    WorkspaceFactory,
)


class RuntimeFailure(RuntimeError):
    pass


class InjectedCrash(RuntimeError):
    """Test-only crash at an explicitly fsynced evidence/checkpoint boundary."""


def _checkpoint_active_node(checkpoint: RuntimeCheckpoint) -> Optional[str]:
    """Return the only node on which an uncheckpointed solve can operate."""

    try:
        graph = ShortTermWorkingGraph.from_snapshot(checkpoint.graph_snapshot)
    except Exception as exc:
        raise CheckpointMismatch("checkpoint working graph is invalid") from exc
    if graph.task_id != checkpoint.task_id:
        raise CheckpointMismatch("checkpoint working graph task mismatch")
    if graph.active_node_id != checkpoint.active_node_id:
        raise CheckpointMismatch("checkpoint active-node identity mismatch")
    if graph.complete:
        return None
    if graph.active_node is not None:
        return graph.active_node.node_id
    ready = graph.ready_nodes()
    if not ready:
        raise CheckpointMismatch("checkpoint working graph has no resumable node")
    return ready[0].node_id


def _require_suffix_payload(
    event: Mapping[str, Any], event_type: str
) -> Mapping[str, Any]:
    if event.get("event_type") != event_type:
        raise CheckpointMismatch("evidence suffix is outside the checkpoint crash window")
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise CheckpointMismatch("evidence suffix payload is malformed")
    return payload


def _validate_model_suffix_event(
    payload: Mapping[str, Any],
    *,
    event_type: str,
    task: "CodingTask",
    arm: str,
    call_kind: str,
    logical_call_id: str,
    step_no: int,
    active_node_id: Optional[str],
) -> None:
    if payload.get("logical_call_id") != logical_call_id:
        raise CheckpointMismatch("evidence suffix logical call identity mismatch")
    if event_type != "model_request":
        return
    expected = {
        "task_id": task.task_id,
        "arm": arm,
        "step_no": step_no,
        "call_kind": call_kind,
        "logical_call_id": logical_call_id,
        "active_node_id": active_node_id,
        "org_id": task.org_id,
    }
    if any(payload.get(name) != value for name, value in expected.items()):
        raise CheckpointMismatch("evidence suffix model request mismatch")
    prompt = payload.get("prompt")
    if (
        not isinstance(prompt, Mapping)
        or set(prompt) != {"sha256", "bytes", "media_type"}
        or not isinstance(payload.get("max_output_tokens"), int)
    ):
        raise CheckpointMismatch("evidence suffix model request is malformed")


def _validate_evidence_suffix(
    suffix: tuple[Mapping[str, Any], ...],
    *,
    checkpoint: RuntimeCheckpoint,
    task: "CodingTask",
    arm: str,
) -> None:
    """Accept only an fsynced prefix of the next phase transition.

    A valid hash chain alone is not authorization: an attacker could append an
    unrelated, correctly hashed event.  These small phase automata bind every
    accepted suffix to the task/arm, the next deterministic logical call, and
    (for solve work) the one node resumable from the checkpointed DAG.
    """

    if not suffix:
        return
    phase = checkpoint.state
    events = tuple(str(event.get("event_type", "")) for event in suffix)

    if phase in {"DECOMPOSED", "RUNNING"}:
        active_node_id = _checkpoint_active_node(checkpoint)
        if active_node_id is None:
            raise CheckpointMismatch("completed graph has an uncheckpointed solve suffix")
        allowed = {
            ("memory_recall",),
            ("memory_recall", "model_request"),
            ("memory_recall", "model_request", "model_response"),
            ("memory_recall", "model_request", "model_failure"),
            ("memory_recall", "model_request", "model_response", "tool_result"),
        }
        if events not in allowed:
            raise CheckpointMismatch("evidence suffix is outside the solve crash window")
        recall = _require_suffix_payload(suffix[0], "memory_recall")
        if any(
            recall.get(name) != value
            for name, value in {
                "task_id": task.task_id,
                "arm": arm,
                "active_node_id": active_node_id,
            }.items()
        ):
            raise CheckpointMismatch("evidence suffix recall identity mismatch")
        for name in ("injections", "bank_trace", "rejections"):
            if not isinstance(recall.get(name), list):
                raise CheckpointMismatch("evidence suffix recall payload is malformed")
        logical_call_id = "%s:%s:solve:%04d" % (
            task.task_id,
            arm,
            checkpoint.next_step_no,
        )
        if len(suffix) >= 2:
            request = _require_suffix_payload(suffix[1], "model_request")
            _validate_model_suffix_event(
                request,
                event_type="model_request",
                task=task,
                arm=arm,
                call_kind="solve",
                logical_call_id=logical_call_id,
                step_no=checkpoint.next_step_no,
                active_node_id=active_node_id,
            )
        if len(suffix) >= 3:
            response_type = events[2]
            response = _require_suffix_payload(suffix[2], response_type)
            _validate_model_suffix_event(
                response,
                event_type=response_type,
                task=task,
                arm=arm,
                call_kind="solve",
                logical_call_id=logical_call_id,
                step_no=checkpoint.next_step_no,
                active_node_id=active_node_id,
            )
        if len(suffix) == 4:
            tool = _require_suffix_payload(suffix[3], "tool_result")
            if any(
                tool.get(name) != value
                for name, value in {
                    "task_id": task.task_id,
                    "arm": arm,
                    "step_no": checkpoint.next_step_no,
                    "active_node_id": active_node_id,
                }.items()
            ):
                raise CheckpointMismatch("evidence suffix tool identity mismatch")
        return

    if phase == "AGENT_COMPLETE":
        if events != ("patch_finalized",):
            raise CheckpointMismatch("evidence suffix is outside the patch crash window")
        payload = _require_suffix_payload(suffix[0], "patch_finalized")
        if payload.get("task_id") != task.task_id or payload.get("arm") != arm:
            raise CheckpointMismatch("evidence suffix patch identity mismatch")
        return

    if phase == "PATCH_FINALIZED":
        if events not in {("grader_request",), ("grader_request", "grader_result")}:
            raise CheckpointMismatch("evidence suffix is outside the grader crash window")
        request = _require_suffix_payload(suffix[0], "grader_request")
        if request.get("task_id") != task.task_id or request.get("arm") != arm:
            raise CheckpointMismatch("evidence suffix grader request mismatch")
        if len(suffix) == 2:
            result = _require_suffix_payload(suffix[1], "grader_result")
            if result.get("task_id") != task.task_id or result.get("arm") != arm:
                raise CheckpointMismatch("evidence suffix grader result mismatch")
        return

    if phase == "GRADED":
        allowed = {
            ("model_request",),
            ("model_request", "model_response"),
            ("model_request", "model_failure"),
            ("model_request", "model_response", "experience_extracted"),
        }
        if events not in allowed:
            raise CheckpointMismatch("evidence suffix is outside the extraction crash window")
        logical_call_id = "%s:%s:extract:0001" % (task.task_id, arm)
        request = _require_suffix_payload(suffix[0], "model_request")
        _validate_model_suffix_event(
            request,
            event_type="model_request",
            task=task,
            arm=arm,
            call_kind="extract",
            logical_call_id=logical_call_id,
            step_no=checkpoint.next_step_no,
            active_node_id=None,
        )
        if len(suffix) >= 2:
            response_type = events[1]
            response = _require_suffix_payload(suffix[1], response_type)
            _validate_model_suffix_event(
                response,
                event_type=response_type,
                task=task,
                arm=arm,
                call_kind="extract",
                logical_call_id=logical_call_id,
                step_no=checkpoint.next_step_no,
                active_node_id=None,
            )
        if len(suffix) == 3:
            extracted = _require_suffix_payload(suffix[2], "experience_extracted")
            if extracted.get("task_id") != task.task_id or extracted.get("arm") != arm:
                raise CheckpointMismatch("evidence suffix extraction identity mismatch")
        return

    if phase == "LIFECYCLE_CREDITED":
        if events != ("agent_run_finished",):
            raise CheckpointMismatch("evidence suffix is outside the terminal crash window")
        payload = _require_suffix_payload(suffix[0], "agent_run_finished")
        if payload.get("task_id") != task.task_id or payload.get("arm") != arm:
            raise CheckpointMismatch("evidence suffix terminal identity mismatch")
        return

    # GRADER_FAILED, EXTRACTED, LIFECYCLE_STORED, and DONE have no evidence
    # append between their checkpoint and the next durable transition.
    raise CheckpointMismatch("checkpoint phase permits no evidence suffix")


def _evidence_blob(
    evidence: RawEvidenceLedger,
    reference: object,
    *,
    media_type: str,
) -> bytes:
    if (
        not isinstance(reference, Mapping)
        or set(reference) != {"sha256", "bytes", "media_type"}
        or reference.get("media_type") != media_type
        or not isinstance(reference.get("sha256"), str)
        or type(reference.get("bytes")) is not int
        or reference["bytes"] < 0
    ):
        raise CheckpointMismatch("completed tool suffix blob reference is malformed")
    path = evidence.blob_dir / str(reference["sha256"])
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CheckpointMismatch("completed tool suffix blob is unavailable") from exc
    if len(raw) != reference["bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise CheckpointMismatch("completed tool suffix blob differs from its reference")
    return raw


def _completed_tool_suffix(
    suffix: tuple[Mapping[str, Any], ...],
    evidence: RawEvidenceLedger,
    *,
    tool_names: set[str],
) -> Optional[dict[str, Any]]:
    if tuple(event.get("event_type") for event in suffix) != (
        "memory_recall",
        "model_request",
        "model_response",
        "tool_result",
    ):
        return None
    request_event = _require_suffix_payload(suffix[1], "model_request")
    response_event = _require_suffix_payload(suffix[2], "model_response")
    tool_event = _require_suffix_payload(suffix[3], "tool_result")
    try:
        response_text = _evidence_blob(
            evidence,
            response_event.get("response"),
            media_type="text/plain; charset=utf-8",
        ).decode("utf-8", errors="strict")
        request_payload = strict_json_loads(
            _evidence_blob(
                evidence,
                tool_event.get("request"),
                media_type="application/json",
            )
        )
        result_payload = strict_json_loads(
            _evidence_blob(
                evidence,
                tool_event.get("result"),
                media_type="application/json",
            )
        )
        tool, arguments = parse_tool_action(response_text, tool_names)
    except (UnicodeDecodeError, ValueError) as exc:
        raise CheckpointMismatch("completed tool suffix payload is invalid") from exc
    if (
        not isinstance(request_payload, Mapping)
        or dict(request_payload) != {"tool": tool, "arguments": arguments}
        or not isinstance(result_payload, Mapping)
        or tool_event.get("tool") != tool
        or tool_event.get("status") not in {"success", "error"}
    ):
        raise CheckpointMismatch("completed tool suffix request/result binding differs")
    return {
        "recall_event": _require_suffix_payload(suffix[0], "memory_recall"),
        "model_request": request_event,
        "model_response": response_event,
        "tool_event": tool_event,
        "tool": tool,
        "arguments": dict(arguments),
        "result": dict(result_payload),
    }


def _model_suffix_call(
    evidence: RawEvidenceLedger,
    *,
    task: "CodingTask",
    arm: str,
    request_event: Mapping[str, Any],
    result_event: Mapping[str, Any],
    call_kind: str,
    active_node_id: Optional[str],
    failure: bool,
) -> tuple[CallRecord, str, bool]:
    required_numbers = {"wall_time_ms", "attempt"}
    usage_available = result_event.get("provider_reported_usage_available", True)
    usage_fields = {
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
    }
    if (
        any(type(result_event.get(name)) is not int for name in required_numbers)
        or type(usage_available) is not bool
        or (
            usage_available
            and any(type(result_event.get(name)) is not int for name in usage_fields)
        )
        or (
            not usage_available
            and any(result_event.get(name) is not None for name in usage_fields)
        )
        or not isinstance(result_event.get("provider"), str)
        or not isinstance(result_event.get("model"), str)
        or not isinstance(result_event.get("paid"), bool)
        or not isinstance(result_event.get("status"), str)
        or result_event.get("logical_call_id") != request_event.get("logical_call_id")
    ):
        raise CheckpointMismatch("model suffix accounting is malformed")
    try:
        response_text = _evidence_blob(
            evidence,
            result_event.get("response"),
            media_type="text/plain; charset=utf-8",
        ).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CheckpointMismatch("model suffix response is not UTF-8") from exc
    prompt = request_event.get("prompt")
    if not isinstance(prompt, Mapping):
        raise CheckpointMismatch("model suffix prompt reference is malformed")
    return (
        CallRecord(
            task_id=task.task_id,
            arm=arm,
            step_no=int(request_event["step_no"]),
            call_kind=call_kind,
            logical_call_id=str(request_event["logical_call_id"]),
            provider=str(result_event["provider"]),
            model=str(result_event["model"]),
            input_tokens=result_event["input_tokens"],
            output_tokens=result_event["output_tokens"],
            cached_input_tokens=result_event["cached_input_tokens"],
            reasoning_tokens=result_event["reasoning_tokens"],
            wall_time_ms=result_event["wall_time_ms"],
            prompt_hash=str(prompt["sha256"]),
            response_hash=str(result_event["response"]["sha256"]),
            active_node_id=active_node_id,
            paid=result_event["paid"],
            attempt=result_event["attempt"],
            status=result_event["status"],
            provider_reported_usage_available=usage_available,
            provider_response_envelope=result_event.get("provider_response_envelope"),
            ledger_reservation=result_event.get("ledger_reservation"),
        ),
        response_text,
        failure,
    )


def _recovered_gateway_failure(
    result_event: Mapping[str, Any], call: CallRecord, response_text: str
) -> GatewayInvocationFailure:
    return GatewayInvocationFailure(
        provider=call.provider,
        model=call.model,
        status=call.status,
        attempt=call.attempt,
        input_tokens=call.input_tokens,
        output_tokens=call.output_tokens,
        cached_input_tokens=call.cached_input_tokens,
        reasoning_tokens=call.reasoning_tokens,
        wall_time_ms=call.wall_time_ms,
        response_text=response_text,
        provider_request_id=result_event.get("provider_request_id"),
        response_id=result_event.get("response_id"),
        response_status=result_event.get("response_status"),
        response_error_code=result_event.get("response_error_code"),
        incomplete_reason=result_event.get("incomplete_reason"),
        output_item_types=tuple(result_event.get("output_item_types", ())),
        content_item_types=tuple(result_event.get("content_item_types", ())),
        refusal_present=bool(result_event.get("refusal_present", False)),
        provider_reported_usage_available=call.provider_reported_usage_available,
        raw_envelope_reference=result_event.get("raw_envelope_reference"),
        extracted_text_bytes=int(result_event.get("extracted_text_bytes", 0)),
        structured_output_bytes=int(result_event.get("structured_output_bytes", 0)),
        original_provider_terminal_classification=result_event.get(
            "original_provider_terminal_classification"
        ),
        provider_response_envelope=result_event.get("provider_response_envelope"),
        ledger_reservation=result_event.get("ledger_reservation"),
    )


def _grader_suffix_result(
    evidence: RawEvidenceLedger,
    *,
    task: "CodingTask",
    arm: str,
    request_event: Mapping[str, Any],
    result_event: Mapping[str, Any],
) -> tuple[GradeResult, GraderRecord]:
    if (
        request_event.get("task_id") != task.task_id
        or request_event.get("arm") != arm
        or result_event.get("task_id") != task.task_id
        or result_event.get("arm") != arm
    ):
        raise CheckpointMismatch("grader suffix identity mismatch")
    try:
        stdout = _evidence_blob(
            evidence,
            result_event.get("stdout"),
            media_type="text/plain; charset=utf-8",
        ).decode("utf-8", errors="strict")
        stderr = _evidence_blob(
            evidence,
            result_event.get("stderr"),
            media_type="text/plain; charset=utf-8",
        ).decode("utf-8", errors="strict")
        report = strict_json_loads(
            _evidence_blob(
                evidence,
                result_event.get("report"),
                media_type="application/json",
            )
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise CheckpointMismatch("grader suffix blobs are invalid") from exc
    if (
        not isinstance(report, Mapping)
        or not isinstance(result_event.get("official"), bool)
        or not isinstance(result_event.get("container_started"), bool)
        or not isinstance(result_event.get("resolved"), bool)
        or type(result_event.get("exit_code")) is not int
        or type(result_event.get("wall_time_ms")) is not int
        or not isinstance(result_event.get("grader_id"), str)
        or not isinstance(result_event.get("container_digest"), str)
        or not isinstance(result_event.get("status"), str)
    ):
        raise CheckpointMismatch("grader suffix accounting is malformed")
    grade = GradeResult(
        task_id=task.task_id,
        resolved=result_event["resolved"],
        exit_code=result_event["exit_code"],
        stdout=stdout,
        stderr=stderr,
        report=dict(report),
        grader_id=result_event["grader_id"],
        container_digest=result_event["container_digest"],
        official=result_event["official"],
        wall_time_ms=result_event["wall_time_ms"],
        container_started=result_event["container_started"],
        status=result_event["status"],
    )
    record = GraderRecord(
        task_id=task.task_id,
        arm=arm,
        grader_id=grade.grader_id,
        container_digest=grade.container_digest,
        exit_code=grade.exit_code,
        resolved=grade.resolved,
        wall_time_ms=grade.wall_time_ms,
        stdout_hash=result_event["stdout"]["sha256"],
        stderr_hash=result_event["stderr"]["sha256"],
        report_hash=result_event["report"]["sha256"],
        official=grade.official,
        container_started=grade.container_started,
        status=grade.status,
    )
    return grade, record


def _recall_payload(task: "CodingTask", arm: str, decision: RecallDecision) -> dict[str, Any]:
    injections = []
    for item in decision.injections:
        if not item.verify():
            raise RuntimeFailure("injection bytes/hash mismatch")
        injections.append(_injection_dict(item))
    return {
        "task_id": task.task_id,
        "arm": arm,
        "active_node_id": decision.active_node_id,
        "injections": injections,
        "bank_trace": list(decision.bank_trace),
        "rejections": list(decision.rejections),
    }


def _public_tool_evidence(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step_no": row["step_no"],
            "active_node_id": row["active_node_id"],
            "tool": row["tool"],
            "request_hash": row["request"]["sha256"],
            "result_hash": row["result"]["sha256"],
            "request": row["request_payload"],
            "result": row["result_payload"],
            "status": row["status"],
        }
        for row in history
    ]


def _extraction_evidence_payload(
    task: "CodingTask",
    arm: str,
    extraction: "ExperienceExtraction",
    *,
    resolved: bool,
) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "arm": arm,
        "source_outcome": "passed" if resolved else "failed",
        "semantic_candidate": extraction.semantic_candidate is not None,
        "response_hash": extraction.response_hash,
        "patch_hash": extraction.patch_hash,
        "public_evidence_hash": extraction.public_evidence_hash,
        "hidden_grader_payload_exposed": False,
    }


@dataclass(frozen=True)
class CodingTask:
    task_id: str
    org_id: str
    user_id: str
    repository: str
    commit: str
    instruction: str
    files: Mapping[str, str]
    editable_paths: tuple[str, ...]
    public_test: Optional[Any] = None

    def __post_init__(self) -> None:
        for name in ("task_id", "org_id", "user_id", "repository", "commit", "instruction"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if not isinstance(self.files, Mapping):
            raise ValueError("files must be a mapping")

    def public_payload(self) -> dict[str, Any]:
        payload = {
            "task_id": self.task_id,
            "repository": self.repository,
            "commit": self.commit,
            "instruction": self.instruction,
        }
        if self.files:
            payload["files"] = dict(sorted(self.files.items()))
        if self.editable_paths:
            payload["editable_paths"] = list(self.editable_paths)
        return payload


@dataclass(frozen=True)
class ExperienceExtraction:
    episode: Mapping[str, Any]
    semantic_candidate: Optional[Mapping[str, Any]]
    response_hash: str
    patch_hash: str
    public_evidence_hash: str

    def __post_init__(self) -> None:
        for name in ("response_hash", "patch_hash", "public_evidence_hash"):
            value = getattr(self, name)
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a lowercase sha256 digest")


@dataclass(frozen=True)
class AgentRunResult:
    run_id: str
    task_id: str
    arm: str
    resolved: bool
    patch: str
    graph_snapshot: Mapping[str, Any]
    grade: GradeResult
    extraction: ExperienceExtraction
    injections: tuple[Mapping[str, Any], ...]
    accounting: Mapping[str, Any]
    evidence_tail_hash: str
    lifecycle_result: Mapping[str, Any]


class RuntimeMemoryController(Protocol):
    @property
    def content_hash(self) -> str: ...
    def recall(self, graph: ShortTermWorkingGraph, task: CodingTask) -> RecallDecision: ...
    def context_for(self, active_node_id: str) -> tuple[MemoryInjection, ...]: ...
    def checkpoint_state(self) -> Mapping[str, Any]: ...
    def restore(self, value: Mapping[str, Any]) -> None: ...


class ExperienceLifecycle(Protocol):
    def store_experience(
        self,
        task: CodingTask,
        graph: ShortTermWorkingGraph,
        extraction: ExperienceExtraction,
        grade: GradeResult,
        injections: tuple[Mapping[str, Any], ...],
    ) -> Mapping[str, Any]: ...

    def credit_outcome(
        self,
        task: CodingTask,
        grade: GradeResult,
        injections: tuple[Mapping[str, Any], ...],
        *,
        outcome_metrics: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class NullExperienceLifecycle:
    def store_experience(self, task, graph, extraction, grade, injections):
        return {
            "storage_action": "NONE",
            "retained_records": 0,
            "archived_records": 0,
            "net_memory_growth": 0,
        }

    def credit_outcome(self, task, grade, injections, *, outcome_metrics):
        return {"credited": 0}


def _component_configuration_hash(component: Any) -> str:
    """Return a stable fallback binding for non-production test gateways.

    Production callers pass an explicit hash covering the complete model or
    grader lock.  Lightweight/replay callers may instead expose ``content_hash``;
    the class identity fallback keeps their existing API deterministic without
    pretending to discover opaque provider configuration.
    """

    advertised = getattr(component, "content_hash", None)
    if (
        isinstance(advertised, str)
        and len(advertised) == 64
        and all(character in "0123456789abcdef" for character in advertised)
    ):
        return advertised
    component_type = type(component)
    return sha256_bytes(
        canonical_bytes(
            {
                "module": component_type.__module__,
                "qualified_name": component_type.__qualname__,
            }
        )
    )


class NoMemoryController:
    """M0 controller; emits explicit abstention and cannot accumulate context."""

    @property
    def content_hash(self) -> str:
        return sha256_bytes(b"trimem-no-memory-controller-v1")

    def recall(self, graph, task):
        if graph.active_node is None:
            raise RuntimeFailure("recall without active node")
        return RecallDecision(
            graph.active_node.node_id,
            (),
            ({"bank": "ALL", "decision": "ABSTAIN", "reason": "M0_NO_MEMORY"},),
            (),
        )

    def context_for(self, active_node_id):
        return ()

    def checkpoint_state(self):
        return {}

    def restore(self, value):
        if value:
            raise RuntimeFailure("M0 checkpoint unexpectedly contains memory state")


class TriMemAgentRuntime:
    def __init__(
        self,
        *,
        runtime_lock: RuntimeLock,
        model_gateway: ModelGateway,
        grader_gateway: GraderGateway,
        memory_controller: RuntimeMemoryController,
        evidence: RawEvidenceLedger,
        checkpoint_store: FileCheckpointStore,
        lifecycle: Optional[ExperienceLifecycle] = None,
        model_config_hash: Optional[str] = None,
        grader_config_hash: Optional[str] = None,
        workspace_factory: Optional[WorkspaceFactory] = None,
    ):
        self.lock = runtime_lock
        self.model_delegate = model_gateway
        self.grader_delegate = grader_gateway
        self.memory = memory_controller
        self.evidence = evidence
        self.checkpoints = checkpoint_store
        self.lifecycle = lifecycle or NullExperienceLifecycle()
        self.model_config_hash = model_config_hash or _component_configuration_hash(model_gateway)
        self.grader_config_hash = grader_config_hash or _component_configuration_hash(grader_gateway)
        for name, value in {
            "model_config_hash": self.model_config_hash,
            "grader_config_hash": self.grader_config_hash,
        }.items():
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be a lowercase sha256 digest")
        self.workspace_factory = workspace_factory or InMemoryWorkspaceFactory()
        if not isinstance(getattr(self.workspace_factory, "content_hash", None), str):
            raise ValueError("workspace factory must expose a content hash")
        if len(self.workspace_factory.content_hash) != 64:
            raise ValueError("workspace factory content hash must be sha256")

    def run(
        self,
        task: CodingTask,
        *,
        arm: str,
        run_id: Optional[str] = None,
        resume: bool = False,
        crash_after_checkpoints: Optional[int] = None,
        crash_after_tool_evidence_step: Optional[int] = None,
        crash_after_model_response_step: Optional[int] = None,
        crash_after_patch_evidence: bool = False,
        crash_after_grader_result: bool = False,
        crash_after_extraction_model_response: bool = False,
        crash_after_extraction_evidence: bool = False,
        crash_after_finished_evidence: bool = False,
    ) -> AgentRunResult:
        if arm not in {"M0", "M1", "M2"}:
            raise ValueError("arm must be M0, M1, or M2")
        run_id = run_id or f"{task.task_id}-{arm}"
        config_hashes = {
            "runtime": self.lock.content_hash,
            "task": sha256_bytes(
                canonical_bytes(
                    {
                        "org_id": task.org_id,
                        "user_id": task.user_id,
                        "public_payload": task.public_payload(),
                    }
                )
            ),
            "model": self.model_config_hash,
            "memory_controller": self.memory.content_hash,
            "grader": self.grader_config_hash,
            "workspace": self.workspace_factory.content_hash,
            "lifecycle": _lifecycle_configuration_hash(self.lifecycle),
        }

        workspace = self.workspace_factory(task)
        if not isinstance(workspace, RepositoryWorkspace):
            raise RuntimeFailure("workspace factory returned an invalid workspace")
        locked_tool_names = {str(row["name"]) for row in self.lock.tool_schema}
        if set(workspace.tool_names) != locked_tool_names:
            raise RuntimeFailure("workspace tool surface differs from the runtime lock")

        checkpoint: Optional[RuntimeCheckpoint] = None
        recovered_tool: Optional[dict[str, Any]] = None
        recovered_solve_model: Optional[dict[str, Any]] = None
        recovered_recall_only: Optional[Mapping[str, Any]] = None
        recovered_patch: Optional[Mapping[str, Any]] = None
        recovered_grader: Optional[tuple[Mapping[str, Any], Mapping[str, Any]]] = None
        recovered_extraction: Optional[dict[str, Any]] = None
        recovered_finished: Optional[Mapping[str, Any]] = None
        if resume:
            checkpoint = self.checkpoints.load(
                run_id,
                required_config_hashes=config_hashes,
                required_evidence_hash=None,
            )
            try:
                # The evidence ledger and latest-checkpoint file are separate
                # durability domains.  A crash can leave a valid, fsynced
                # evidence suffix after the checkpoint tail.  Accept only when
                # the checkpoint tail is a verified ancestor of the current
                # append-only chain; unrelated/replaced evidence still fails.
                suffix = self.evidence.verified_suffix(
                    checkpoint.evidence_event_hash
                )
                # Verify every content-addressed blob before interpreting the
                # phase-specific suffix.  A valid event hash that points at a
                # missing or replaced prompt/result is not resumable evidence.
                self.evidence.verify()
                _validate_evidence_suffix(
                    suffix,
                    checkpoint=checkpoint,
                    task=task,
                    arm=arm,
                )
                recovered_tool = _completed_tool_suffix(
                    suffix,
                    self.evidence,
                    tool_names=locked_tool_names,
                )
                suffix_events = tuple(
                    str(event.get("event_type", "")) for event in suffix
                )
                ambiguous = suffix_events in {
                    ("memory_recall", "model_request"),
                    ("grader_request",),
                    ("model_request",),
                }
                if ambiguous:
                    self.evidence.append(
                        "recovery_blocked",
                        {
                            "run_id": run_id,
                            "task_id": task.task_id,
                            "arm": arm,
                            "checkpoint_state": checkpoint.state,
                            "reason": "external request has no durable terminal result",
                            "suffix_events": list(suffix_events),
                            "accounting_disposition": "UNKNOWN_EXTERNAL_CALL_NOT_RETRIED",
                            "retry_allowed": False,
                        },
                    )
                    raise CheckpointMismatch(
                        "ambiguous external request has no durable result; retry refused"
                    )
                if suffix_events == ("memory_recall",):
                    recovered_recall_only = _require_suffix_payload(
                        suffix[0], "memory_recall"
                    )
                elif suffix_events in {
                    ("memory_recall", "model_request", "model_response"),
                    ("memory_recall", "model_request", "model_failure"),
                }:
                    recovered_solve_model = {
                        "recall_event": _require_suffix_payload(
                            suffix[0], "memory_recall"
                        ),
                        "model_request": _require_suffix_payload(
                            suffix[1], "model_request"
                        ),
                        "model_result": _require_suffix_payload(
                            suffix[2], suffix_events[2]
                        ),
                        "failure": suffix_events[2] == "model_failure",
                    }
                elif suffix_events == ("patch_finalized",):
                    recovered_patch = _require_suffix_payload(
                        suffix[0], "patch_finalized"
                    )
                elif suffix_events == ("grader_request", "grader_result"):
                    recovered_grader = (
                        _require_suffix_payload(suffix[0], "grader_request"),
                        _require_suffix_payload(suffix[1], "grader_result"),
                    )
                elif suffix_events in {
                    ("model_request", "model_response"),
                    ("model_request", "model_failure"),
                    ("model_request", "model_response", "experience_extracted"),
                }:
                    recovered_extraction = {
                        "model_request": _require_suffix_payload(
                            suffix[0], "model_request"
                        ),
                        "model_result": _require_suffix_payload(
                            suffix[1], suffix_events[1]
                        ),
                        "failure": suffix_events[1] == "model_failure",
                        "extracted_event": (
                            _require_suffix_payload(
                                suffix[2], "experience_extracted"
                            )
                            if len(suffix) == 3
                            else None
                        ),
                    }
                elif suffix_events == ("agent_run_finished",):
                    recovered_finished = _require_suffix_payload(
                        suffix[0], "agent_run_finished"
                    )
            except ValueError as exc:
                raise CheckpointMismatch(
                    "checkpoint evidence hash is not a verified ledger prefix"
                ) from exc
            if checkpoint.task_id != task.task_id or checkpoint.arm != arm:
                raise RuntimeFailure("checkpoint task/arm mismatch")
            graph = ShortTermWorkingGraph.from_snapshot(checkpoint.graph_snapshot)
            accounting = RunAccounting.from_dict(checkpoint.accounting)
            if (
                recovered_tool is not None
                and recovered_tool["tool"] == "write_file"
                and recovered_tool["tool_event"]["status"] == "success"
            ):
                recover = getattr(workspace, "recover_completed_tool", None)
                if not callable(recover):
                    workspace.restore_checkpoint(checkpoint.workspace_state)
                    replayed = workspace.execute(
                        recovered_tool["tool"], recovered_tool["arguments"]
                    )
                    if replayed != recovered_tool["result"]:
                        raise CheckpointMismatch(
                            "replayed workspace tool differs from durable evidence"
                        )
                else:
                    recover(
                        checkpoint.workspace_state,
                        tool=recovered_tool["tool"],
                        arguments=recovered_tool["arguments"],
                        result=recovered_tool["result"],
                    )
            else:
                workspace.restore_checkpoint(checkpoint.workspace_state)
            self.memory.restore(checkpoint.memory_controller_state)
            if checkpoint.lifecycle_state:
                restore_lifecycle = getattr(self.lifecycle, "restore_state", None)
                if not callable(restore_lifecycle):
                    raise RuntimeFailure("checkpoint contains lifecycle state but lifecycle cannot restore it")
                restore_lifecycle(checkpoint.lifecycle_state)
            tool_history = list(checkpoint.tool_history)
            next_step = checkpoint.next_step_no
            generation = checkpoint.generation
            previous_checkpoint_hash = checkpoint.content_hash
            completed_call_ids = set(checkpoint.completed_call_ids)
            terminal_payload = dict(checkpoint.terminal_payload)
            recall_rejections = [
                dict(row) for row in terminal_payload.get("recall_rejections", ())
            ]
            phase_state = checkpoint.state
        else:
            accounting = RunAccounting()
            model = RecordingModelGateway(self.model_delegate, accounting, self.evidence)
            graph = self._decompose(task, arm, model)
            tool_history: list[dict] = []
            next_step = 1
            generation = 0
            previous_checkpoint_hash = "0" * 64
            completed_call_ids = {f"{task.task_id}:{arm}:decompose:0001"}
            terminal_payload: dict[str, Any] = {}
            recall_rejections: list[dict[str, Any]] = []
            phase_state = "DECOMPOSED"

        model = RecordingModelGateway(self.model_delegate, accounting, self.evidence)
        tools = RecordingToolExecutor(workspace, accounting, self.evidence, task_id=task.task_id, arm=arm)
        tools.history = tool_history
        checkpoint_count = 0

        def save_checkpoint(state: str, active_node_id: Optional[str]) -> None:
            nonlocal generation, previous_checkpoint_hash, checkpoint_count, phase_state
            generation += 1
            cp = RuntimeCheckpoint(
                run_id=run_id,
                task_id=task.task_id,
                arm=arm,
                generation=generation,
                next_step_no=next_step,
                state=state,
                active_node_id=active_node_id,
                graph_snapshot=graph.snapshot(),
                workspace_state=dict(workspace.checkpoint_state()),
                injected_memory_ids=tuple(sorted(_memory_ids(self.memory.checkpoint_state()))),
                injected_bytes=_memory_bytes(self.memory.checkpoint_state()),
                injection_ledger=tuple(_memory_ledger(self.memory.checkpoint_state())),
                tool_history=tuple(tools.history),
                completed_call_ids=tuple(sorted(completed_call_ids)),
                accounting=accounting.to_dict(),
                config_hashes=config_hashes,
                evidence_event_hash=self.evidence.last_event_hash,
                memory_controller_state=dict(self.memory.checkpoint_state()),
                lifecycle_state=_lifecycle_checkpoint_state(self.lifecycle),
                terminal_payload=dict(terminal_payload),
                previous_checkpoint_hash=previous_checkpoint_hash,
            )
            previous_checkpoint_hash = self.checkpoints.save(cp)
            phase_state = state
            checkpoint_count += 1
            if crash_after_checkpoints is not None and checkpoint_count >= crash_after_checkpoints:
                raise InjectedCrash(f"injected after checkpoint {checkpoint_count}")

        if not resume:
            self.evidence.append(
                "agent_run_started",
                {
                    "run_id": run_id,
                    "task_id": task.task_id,
                    "arm": arm,
                    "public_task_hash": sha256_bytes(canonical_bytes(task.public_payload())),
                    "runtime_lock_hash": self.lock.content_hash,
                    "paid_model_calls": 0,
                },
            )
            save_checkpoint("DECOMPOSED", None)

        prepared_recall: Optional[RecallDecision] = None
        solve_recovery = recovered_tool or recovered_solve_model
        recall_event = (
            solve_recovery["recall_event"]
            if solve_recovery is not None
            else recovered_recall_only
        )
        if recall_event is not None:
            assert checkpoint is not None
            try:
                node = graph.active_node or graph.activate_next()
                if node is None:
                    raise CheckpointMismatch(
                        "solve suffix has no resumable active node"
                    )
                decision = self.memory.recall(graph, task)
                replayed_recall = _recall_payload(task, arm, decision)
                if canonical_bytes(replayed_recall) != canonical_bytes(
                    recall_event
                ):
                    raise CheckpointMismatch(
                        "replayed memory recall differs from durable evidence"
                    )
                recall_rejections.extend(
                    dict(row) for row in decision.rejections
                )
                terminal_payload["recall_rejections"] = list(recall_rejections)

                if solve_recovery is None:
                    prepared_recall = decision
                    solve_recovery = None
                    # The fsynced recall event is now represented by the replayed
                    # controller state. The loop below consumes it without
                    # appending a duplicate memory_recall event.
                    pass
                else:
                    request_event = solve_recovery["model_request"]
                    result_event = (
                        solve_recovery["model_response"]
                        if recovered_tool is not None
                        else solve_recovery["model_result"]
                    )
                    call, response_text, failed = _model_suffix_call(
                        self.evidence,
                        task=task,
                        arm=arm,
                        request_event=request_event,
                        result_event=result_event,
                        call_kind="solve",
                        active_node_id=node.node_id,
                        failure=(
                            False
                            if recovered_tool is not None
                            else bool(solve_recovery["failure"])
                        ),
                    )
                    expected_prompt = self._solve_prompt(
                        task,
                        graph,
                        tools.history,
                        self.memory.context_for(node.node_id),
                    )
                    recorded_prompt = _evidence_blob(
                        self.evidence,
                        request_event.get("prompt"),
                        media_type="text/plain; charset=utf-8",
                    ).decode("utf-8", errors="strict")
                    if (
                        recorded_prompt != expected_prompt
                        or request_event.get("max_output_tokens")
                        != self.lock.limits.max_output_tokens_per_solve
                    ):
                        raise CheckpointMismatch(
                            "replayed solve prompt differs from durable evidence"
                        )
                    accounting.add_call(call)
                    completed_call_ids.add(call.logical_call_id)
                    if failed:
                        terminal_payload["recovered_solve_failure"] = {
                            "provider": call.provider,
                            "model": call.model,
                            "status": call.status,
                            "attempt": call.attempt,
                        }
                        save_checkpoint(checkpoint.state, graph.active_node_id)
                        raise _recovered_gateway_failure(
                            result_event, call, response_text
                        )

                    if recovered_tool is None:
                        tool, arguments = parse_tool_action(
                            response_text, set(workspace.tool_names)
                        )
                        result = tools.execute(next_step, node.node_id, tool, arguments)
                    else:
                        tool = recovered_tool["tool"]
                        arguments = recovered_tool["arguments"]
                        result = recovered_tool["result"]
                        tool_event = recovered_tool["tool_event"]
                        if type(tool_event.get("wall_time_ms")) is not int:
                            raise CheckpointMismatch(
                                "completed tool suffix accounting is malformed"
                            )
                        accounting.add_tool(ToolRecord(
                            task_id=task.task_id,
                            arm=arm,
                            step_no=next_step,
                            active_node_id=node.node_id,
                            tool_name=tool,
                            request_hash=tool_event["request"]["sha256"],
                            result_hash=tool_event["result"]["sha256"],
                            wall_time_ms=tool_event["wall_time_ms"],
                            status=tool_event["status"],
                        ))
                        tools.history.append({
                            **dict(tool_event),
                            "request_payload": {
                                "tool": tool,
                                "arguments": arguments,
                            },
                            "result_payload": result,
                        })
                if solve_recovery is not None:
                    tool_evidence = self._tool_evidence(
                        next_step,
                        tool,
                        arguments,
                        result,
                    )
                    if (
                        tool == "revise_subtask_dag"
                        and result.get("dag_revised")
                    ):
                        self._apply_dag_revision(
                            graph, tool_evidence, result
                        )
                    elif (
                        tool == "complete_subtask"
                        and result.get("completed")
                    ):
                        graph.complete_active(tool_evidence)
                    else:
                        graph.update_from_evidence(tool_evidence)
                    next_step += 1
                    save_checkpoint(
                        "RUNNING" if not graph.complete else "AGENT_COMPLETE",
                        graph.active_node_id,
                    )
            except BaseException:
                rollback = getattr(workspace, "rollback_checkpoint", None)
                if callable(rollback):
                    rollback(checkpoint.workspace_state)
                else:
                    workspace.restore_checkpoint(checkpoint.workspace_state)
                raise

        if terminal_payload.get("recovered_solve_failure") is not None:
            failure = terminal_payload["recovered_solve_failure"]
            raise RuntimeFailure(
                "durable solve model failure: %s" % failure.get("status", "unknown")
            )

        solve_calls = sum(1 for record in accounting.calls if record.call_kind == "solve")
        while not graph.complete:
            node = graph.active_node or graph.activate_next()
            if node is None:
                raise RuntimeFailure("DAG has no ready node but is incomplete")
            # The controller is responsible for idempotent, active-node-only recall.
            if (
                prepared_recall is not None
                and prepared_recall.active_node_id == node.node_id
            ):
                decision = prepared_recall
                prepared_recall = None
            else:
                decision = self.memory.recall(graph, task)
                self._record_recall(task, arm, decision)
                recall_rejections.extend(dict(row) for row in decision.rejections)
                terminal_payload["recall_rejections"] = list(recall_rejections)
            node_steps = sum(
                1 for record in accounting.calls
                if record.call_kind == "solve" and record.active_node_id == node.node_id
            )
            while graph.active_node is not None:
                if solve_calls >= self.lock.limits.max_solve_calls or next_step > self.lock.limits.max_agent_steps:
                    raise RuntimeFailure("solve-call or global step cap reached")
                if node_steps >= self.lock.limits.max_steps_per_subtask:
                    raise RuntimeFailure("per-subtask step cap reached")
                prompt = self._solve_prompt(task, graph, tools.history, self.memory.context_for(node.node_id))
                logical_id = f"{task.task_id}:{arm}:solve:{next_step:04d}"
                if logical_id in completed_call_ids:
                    raise RuntimeFailure("checkpoint would repeat a completed logical call")
                reply = model.invoke(
                    GatewayRequest(
                        task_id=task.task_id,
                        arm=arm,
                        step_no=next_step,
                        call_kind="solve",
                        logical_call_id=logical_id,
                        prompt=prompt,
                        max_output_tokens=self.lock.limits.max_output_tokens_per_solve,
                        org_id=task.org_id,
                        active_node_id=node.node_id,
                    )
                )
                if crash_after_model_response_step == next_step:
                    raise InjectedCrash(
                        f"injected after durable model response for step {next_step}"
                    )
                completed_call_ids.add(logical_id)
                solve_calls += 1
                node_steps += 1
                tool, arguments = parse_tool_action(reply.text, set(workspace.tool_names))
                result = tools.execute(next_step, node.node_id, tool, arguments)
                if crash_after_tool_evidence_step == next_step:
                    raise InjectedCrash(
                        f"injected after durable tool evidence for step {next_step}"
                    )
                evidence = self._tool_evidence(next_step, tool, arguments, result)
                if tool == "revise_subtask_dag" and result.get("dag_revised"):
                    self._apply_dag_revision(graph, evidence, result)
                elif tool == "complete_subtask" and result.get("completed"):
                    graph.complete_active(evidence)
                else:
                    graph.update_from_evidence(evidence)
                next_step += 1
                save_checkpoint("RUNNING" if not graph.complete else "AGENT_COMPLETE", graph.active_node_id)

        if not graph.complete or phase_state not in {
            "AGENT_COMPLETE", "PATCH_FINALIZED", "GRADED", "GRADER_FAILED",
            "EXTRACTED", "LIFECYCLE_STORED", "LIFECYCLE_CREDITED", "DONE",
        }:
            raise RuntimeFailure("terminal phase requires a complete DAG and a recognized checkpoint state")

        phase_order = {
            "AGENT_COMPLETE": 0,
            "PATCH_FINALIZED": 1,
            "GRADED": 2,
            "GRADER_FAILED": 2,
            "EXTRACTED": 3,
            "LIFECYCLE_STORED": 4,
            "LIFECYCLE_CREDITED": 5,
            "DONE": 6,
        }
        patch = workspace.patch()
        patch_hash = sha256_bytes(patch.encode("utf-8"))
        if recovered_patch is not None:
            if (
                recovered_patch.get("task_id") != task.task_id
                or recovered_patch.get("arm") != arm
                or recovered_patch.get("graph_hash") != graph.content_hash()
            ):
                raise CheckpointMismatch("patch suffix identity mismatch")
            recorded_patch = _evidence_blob(
                self.evidence,
                recovered_patch.get("patch"),
                media_type="text/plain; charset=utf-8",
            ).decode("utf-8", errors="strict")
            if recorded_patch != patch:
                raise CheckpointMismatch("patch suffix differs from the Git workspace")
            terminal_payload.update({
                "patch": dict(recovered_patch["patch"]),
                "patch_sha256": patch_hash,
            })
            save_checkpoint("PATCH_FINALIZED", None)
        if phase_order[phase_state] < phase_order["PATCH_FINALIZED"]:
            patch_ref = self.evidence.put_blob(patch)
            if patch_ref["sha256"] != patch_hash:
                raise RuntimeFailure("workspace patch evidence hash mismatch")
            terminal_payload.update({"patch": patch_ref, "patch_sha256": patch_hash})
            self.evidence.append(
                "patch_finalized",
                {"task_id": task.task_id, "arm": arm, "patch": patch_ref, "graph_hash": graph.content_hash()},
            )
            if crash_after_patch_evidence:
                raise InjectedCrash("injected after durable patch evidence")
            save_checkpoint("PATCH_FINALIZED", None)
        elif terminal_payload.get("patch_sha256") != patch_hash:
            raise RuntimeFailure("resumed workspace patch differs from the terminal checkpoint")

        if recovered_grader is not None:
            grader_request, grader_result = recovered_grader
            if (
                grader_request.get("repository") != task.repository
                or grader_request.get("base_commit") != task.commit
                or not isinstance(grader_request.get("patch"), Mapping)
                or grader_request["patch"].get("sha256") != patch_hash
            ):
                raise CheckpointMismatch("grader request suffix differs from the task patch")
            grade, grader_record = _grader_suffix_result(
                self.evidence,
                task=task,
                arm=arm,
                request_event=grader_request,
                result_event=grader_result,
            )
            accounting.add_grader(grader_record)
            _store_terminal_grade(terminal_payload, grade)
            if grade.status != "success":
                save_checkpoint("GRADER_FAILED", None)
                raise GraderInvocationFailure(grade)
            save_checkpoint("GRADED", None)

        grade_payload = terminal_payload.get("grade")
        if phase_state == "GRADER_FAILED":
            grade = _grade_from_terminal(grade_payload, task.task_id, terminal_payload)
            raise GraderInvocationFailure(grade)
        if phase_order[phase_state] < phase_order["GRADED"]:
            grader = RecordingGraderGateway(self.grader_delegate, accounting, self.evidence, arm)
            request = GradeRequest(
                task_id=task.task_id,
                repository=task.repository,
                base_commit=task.commit,
                patch=patch,
                workspace=workspace.grader_context(base_commit=task.commit),
            )
            try:
                grade = grader.grade(request)
                if crash_after_grader_result:
                    raise InjectedCrash("injected after durable grader result")
            except GraderInvocationFailure as failure:
                _store_terminal_grade(terminal_payload, failure.result)
                save_checkpoint("GRADER_FAILED", None)
                raise
            _store_terminal_grade(terminal_payload, grade)
            save_checkpoint("GRADED", None)
        else:
            grade = _grade_from_terminal(grade_payload, task.task_id, terminal_payload)

        extraction_payload = terminal_payload.get("extraction")
        if terminal_payload.get("recovered_extraction_failure") is not None:
            failure = terminal_payload["recovered_extraction_failure"]
            raise RuntimeFailure(
                "durable extraction model failure: %s"
                % failure.get("status", "unknown")
            )
        if recovered_extraction is not None:
            assert checkpoint is not None
            request_event = recovered_extraction["model_request"]
            result_event = recovered_extraction["model_result"]
            call, response_text, failed = _model_suffix_call(
                self.evidence,
                task=task,
                arm=arm,
                request_event=request_event,
                result_event=result_event,
                call_kind="extract",
                active_node_id=None,
                failure=bool(recovered_extraction["failure"]),
            )
            expected_prompt, public_tool_evidence = self._extraction_prompt(
                task, graph, tools.history, patch, grade
            )
            recorded_prompt = _evidence_blob(
                self.evidence,
                request_event.get("prompt"),
                media_type="text/plain; charset=utf-8",
            ).decode("utf-8", errors="strict")
            if (
                recorded_prompt != expected_prompt
                or request_event.get("max_output_tokens")
                != self.lock.limits.max_output_tokens_extraction
            ):
                raise CheckpointMismatch(
                    "replayed extraction request differs from durable evidence"
                )
            accounting.add_call(call)
            completed_call_ids.add(call.logical_call_id)
            if failed:
                terminal_payload["recovered_extraction_failure"] = {
                    "provider": call.provider,
                    "model": call.model,
                    "status": call.status,
                    "attempt": call.attempt,
                }
                save_checkpoint("GRADED", None)
                raise _recovered_gateway_failure(
                    result_event, call, response_text
                )
            extraction = self._extraction_from_text(
                task,
                arm,
                patch,
                grade,
                response_text,
                public_tool_evidence,
                append_evidence=False,
            )
            expected_extracted_event = _extraction_evidence_payload(
                task, arm, extraction, resolved=grade.resolved
            )
            recorded_extracted_event = recovered_extraction["extracted_event"]
            if recorded_extracted_event is None:
                self.evidence.append(
                    "experience_extracted", expected_extracted_event
                )
            elif canonical_bytes(recorded_extracted_event) != canonical_bytes(
                expected_extracted_event
            ):
                raise CheckpointMismatch(
                    "experience extraction suffix differs from its model response"
                )
            extraction_payload = asdict(extraction)
            terminal_payload["extraction"] = extraction_payload
            terminal_payload["extraction_sha256"] = sha256_bytes(
                canonical_bytes(extraction_payload)
            )

        injections = tuple(_memory_ledger(self.memory.checkpoint_state()))
        if phase_order[phase_state] < phase_order["EXTRACTED"]:
            if recovered_extraction is None:
                extraction = self._extract(
                    task,
                    arm,
                    graph,
                    tools.history,
                    patch,
                    grade,
                    model,
                    next_step,
                    crash_after_model_response=crash_after_extraction_model_response,
                )
                if crash_after_extraction_evidence:
                    raise InjectedCrash("injected after durable extraction evidence")
                completed_call_ids.add(f"{task.task_id}:{arm}:extract:0001")
                extraction_payload = asdict(extraction)
                terminal_payload["extraction"] = extraction_payload
                terminal_payload["extraction_sha256"] = sha256_bytes(
                    canonical_bytes(extraction_payload)
                )
            prepare = getattr(self.lifecycle, "prepare_store_experience", None)
            if callable(prepare):
                prepare(task, extraction, grade, injections)
            save_checkpoint("EXTRACTED", None)
        else:
            extraction = _extraction_from_terminal(extraction_payload, terminal_payload)
        if phase_order[phase_state] < phase_order["LIFECYCLE_STORED"]:
            storage_result = dict(
                self.lifecycle.store_experience(task, graph, extraction, grade, injections)
            )
            terminal_payload["storage_result"] = storage_result
            terminal_payload["storage_result_sha256"] = sha256_bytes(canonical_bytes(storage_result))
            save_checkpoint("LIFECYCLE_STORED", None)
        else:
            storage_result = _mapping_from_terminal(
                terminal_payload, "storage_result", "storage_result_sha256"
            )

        if phase_order[phase_state] < phase_order["LIFECYCLE_CREDITED"]:
            outcome_metrics = _outcome_metrics(
                graph, accounting, injections, recall_rejections, grade
            )
            terminal_payload["outcome_metrics"] = outcome_metrics
            terminal_payload["outcome_metrics_sha256"] = sha256_bytes(
                canonical_bytes(outcome_metrics)
            )
            credit_result = dict(
                self.lifecycle.credit_outcome(
                    task,
                    grade,
                    injections,
                    outcome_metrics=outcome_metrics,
                )
            )
            terminal_payload["credit_result"] = credit_result
            terminal_payload["credit_result_sha256"] = sha256_bytes(canonical_bytes(credit_result))
            save_checkpoint("LIFECYCLE_CREDITED", None)
        else:
            credit_result = _mapping_from_terminal(
                terminal_payload, "credit_result", "credit_result_sha256"
            )

        lifecycle_result = {"storage": storage_result, "credit": credit_result}
        expected_finished = {
            "run_id": run_id,
            "task_id": task.task_id,
            "arm": arm,
            "resolved": grade.resolved,
            "lifecycle": lifecycle_result,
            "accounting": accounting.summary(),
        }
        if recovered_finished is not None:
            if canonical_bytes(recovered_finished) != canonical_bytes(
                expected_finished
            ):
                raise CheckpointMismatch(
                    "terminal evidence differs from the canonical run result"
                )
            save_checkpoint("DONE", None)
        if phase_state != "DONE":
            self.evidence.append("agent_run_finished", expected_finished)
            if crash_after_finished_evidence:
                raise InjectedCrash("injected after durable terminal evidence")
            save_checkpoint("DONE", None)
        return AgentRunResult(
            run_id=run_id,
            task_id=task.task_id,
            arm=arm,
            resolved=grade.resolved,
            patch=patch,
            graph_snapshot=graph.snapshot(),
            grade=grade,
            extraction=extraction,
            injections=injections,
            accounting=accounting.to_dict(),
            evidence_tail_hash=self.evidence.last_event_hash,
            lifecycle_result=lifecycle_result,
        )

    def _decompose(self, task: CodingTask, arm: str, model: RecordingModelGateway) -> ShortTermWorkingGraph:
        prompt = self.lock.decomposer_prompt + "\n\nPUBLIC TASK:\n" + json.dumps(
            task.public_payload(), ensure_ascii=False, sort_keys=True
        )
        logical_id = f"{task.task_id}:{arm}:decompose:0001"
        response = model.invoke(
            GatewayRequest(
                task_id=task.task_id,
                arm=arm,
                step_no=0,
                call_kind="decompose",
                logical_call_id=logical_id,
                prompt=prompt,
                max_output_tokens=self.lock.limits.max_output_tokens_decomposition,
                org_id=task.org_id,
                **output_contract("trimem_decomposition_v1"),
            )
        )
        payload = strict_json_object(response.text)
        if set(payload) != {"subtasks"} or not isinstance(payload["subtasks"], list) or not payload["subtasks"]:
            raise RuntimeFailure("decomposer must return a non-empty subtasks list")
        graph = ShortTermWorkingGraph(task.task_id, task.instruction, task.repository)
        seen: set[str] = set()
        allowed = {
            "id", "objective", "predicted_operation", "depends_on", "preconditions", "invariants",
            "files", "symbols", "apis", "errors", "tests", "required_memory_facets",
        }
        for row in payload["subtasks"]:
            if not isinstance(row, dict) or not {"id", "objective", "predicted_operation"} <= set(row):
                raise RuntimeFailure("invalid semantic subtask record")
            if set(row) - allowed:
                raise RuntimeFailure("unknown semantic subtask field")
            node_id = str(row["id"])
            dependencies = tuple(str(x) for x in row.get("depends_on", ()))
            if node_id in seen or any(dep not in seen for dep in dependencies):
                raise RuntimeFailure("subtask IDs must be unique and dependencies must precede dependents")
            graph.add_subtask(
                SubtaskSpec(
                    node_id=node_id,
                    objective=str(row["objective"]),
                    operation=str(row["predicted_operation"]),
                    dependencies=dependencies,
                    preconditions=tuple(row.get("preconditions", ())),
                    invariants=tuple(row.get("invariants", ())),
                    files=tuple(row.get("files", ())),
                    symbols=tuple(row.get("symbols", ())),
                    apis=tuple(row.get("apis", ())),
                    errors=tuple(row.get("errors", ())),
                    tests=tuple(row.get("tests", ())),
                    required_memory_facets=tuple(
                        row.get("required_memory_facets", ("operation", "precondition", "verification"))
                    ),
                )
            )
            seen.add(node_id)
        self.evidence.append(
            "semantic_dag_created",
            {
                "task_id": task.task_id,
                "arm": arm,
                "graph_hash": graph.content_hash(),
                "subtask_count": len(graph.nodes),
                "subtask_ids": list(graph.nodes),
            },
        )
        return graph

    def _solve_prompt(self, task, graph, history, injections):
        node = graph.active_node
        if node is None:
            raise RuntimeFailure("solve prompt requires active node")
        memory = [
            {
                "memory_id": item.memory_id,
                "kind": item.kind.value,
                "version": item.memory_version,
                "sha256": item.sha256,
                "exact_text": item.exact_text,
            }
            for item in injections
            if item.active_node_id == node.node_id or item.active_node_id == "__TASK__"
        ]
        body = {
            "public_task": {
                "task_id": task.task_id,
                "repository": task.repository,
                "commit": task.commit,
                "instruction": task.instruction,
                "editable_paths": list(task.editable_paths),
            },
            "active_subtask": node.canonical_dict(),
            "memory_for_active_subtask_only": memory,
            "tool_history": history,
            "tool_schema": list(self.lock.tool_schema),
        }
        return self.lock.solve_prompt + "\n\nSTATE:\n" + json.dumps(body, ensure_ascii=False, sort_keys=True)

    def _extraction_prompt(self, task, graph, history, patch, grade):
        # These are public repository/tool observations already shown to the
        # solving model. Hidden grader streams/reports never enter history.
        public_tool_evidence = _public_tool_evidence(history)
        # Deliberately exclude grader stdout/stderr/report and any hidden fixture.
        body = {
            "public_instruction": task.instruction,
            "repository": task.repository,
            "source_commit": task.commit,
            "semantic_subtasks": [
                {"id": node.node_id, "objective": node.objective, "operation": node.operation}
                for node in graph.nodes.values()
            ],
            "public_tool_evidence": public_tool_evidence,
            "applied_patch": patch,
            "official_or_replay_verdict_only": {"resolved": grade.resolved},
        }
        prompt = self.lock.extraction_prompt + "\n\nSOURCE EVIDENCE:\n" + json.dumps(
            body, ensure_ascii=False, sort_keys=True
        )
        return prompt, public_tool_evidence

    def _extract(
        self,
        task,
        arm,
        graph,
        history,
        patch,
        grade,
        model,
        step_no,
        *,
        crash_after_model_response=False,
    ):
        prompt, public_tool_evidence = self._extraction_prompt(
            task, graph, history, patch, grade
        )
        logical_id = f"{task.task_id}:{arm}:extract:0001"
        response = model.invoke(
            GatewayRequest(
                task_id=task.task_id,
                arm=arm,
                step_no=step_no,
                call_kind="extract",
                logical_call_id=logical_id,
                prompt=prompt,
                max_output_tokens=self.lock.limits.max_output_tokens_extraction,
                org_id=task.org_id,
                **output_contract("trimem_experience_extraction_v1"),
            )
        )
        if crash_after_model_response:
            raise InjectedCrash("injected after durable extraction model response")
        return self._extraction_from_text(
            task,
            arm,
            patch,
            grade,
            response.text,
            public_tool_evidence,
            append_evidence=True,
        )

    def _extraction_from_text(
        self,
        task,
        arm,
        patch,
        grade,
        response_text,
        public_tool_evidence,
        *,
        append_evidence,
    ):
        payload = strict_json_object(response_text)
        if set(payload) != {"episode", "semantic_candidate"} or not isinstance(payload["episode"], dict):
            raise RuntimeFailure("invalid extraction response")
        semantic = payload["semantic_candidate"]
        if semantic is not None and not isinstance(semantic, dict):
            raise RuntimeFailure("semantic_candidate must be object or null")
        if not grade.resolved and semantic is not None:
            raise RuntimeFailure("failed source attempted to enter semantic bank")
        required_episode = {"summary", "action", "outcome"}
        if not required_episode <= set(payload["episode"]):
            raise RuntimeFailure("episode extraction is incomplete")
        expected_outcome = "passed" if grade.resolved else "failed"
        if payload["episode"].get("outcome") != expected_outcome:
            raise RuntimeFailure("extractor outcome contradicts grader")
        if semantic is not None:
            required_semantic = {
                "preconditions", "operation", "invariant", "non_applicability", "verification",
                "applicability_scope",
            }
            if not required_semantic <= set(semantic):
                raise RuntimeFailure("semantic candidate is incomplete")
            if semantic.get("applicability_scope") not in {
                "EXACT_REPOSITORY", "CROSS_REPOSITORY"
            }:
                raise RuntimeFailure("semantic applicability_scope is invalid")
        extraction = ExperienceExtraction(
            episode=dict(payload["episode"]),
            semantic_candidate=dict(semantic) if semantic is not None else None,
            response_hash=sha256_bytes(response_text.encode()),
            patch_hash=sha256_bytes(patch.encode("utf-8")),
            public_evidence_hash=sha256_bytes(canonical_bytes(public_tool_evidence)),
        )
        event_payload = _extraction_evidence_payload(
            task, arm, extraction, resolved=grade.resolved
        )
        if append_evidence:
            self.evidence.append("experience_extracted", event_payload)
        return extraction

    def _record_recall(self, task, arm, decision):
        injections = []
        for item in decision.injections:
            if not item.verify():
                raise RuntimeFailure("injection bytes/hash mismatch")
            blob = self.evidence.put_blob(item.exact_utf8)
            if blob["sha256"] != item.sha256 or blob["bytes"] != item.byte_count:
                raise RuntimeFailure("persisted injection differs from actual bytes")
            injections.append(_injection_dict(item))
        self.evidence.append(
            "memory_recall",
            {
                "task_id": task.task_id,
                "arm": arm,
                "active_node_id": decision.active_node_id,
                "injections": injections,
                "bank_trace": list(decision.bank_trace),
                "rejections": list(decision.rejections),
            },
        )

    @staticmethod
    def _apply_dag_revision(
        graph: ShortTermWorkingGraph,
        evidence: Evidence,
        result: Mapping[str, Any],
    ) -> None:
        """Apply one validated, evidence-bound semantic topology delta."""

        graph.record_evidence(evidence)
        for row in result.get("new_subtasks", ()):
            graph.add_subtask(SubtaskSpec(
                node_id=str(row["id"]),
                objective=str(row["objective"]),
                operation=str(row["predicted_operation"]),
                dependencies=tuple(row.get("depends_on", ())),
                preconditions=tuple(row.get("preconditions", ())),
                invariants=tuple(row.get("invariants", ())),
                files=tuple(row.get("files", ())),
                symbols=tuple(row.get("symbols", ())),
                apis=tuple(row.get("apis", ())),
                errors=tuple(row.get("errors", ())),
                tests=tuple(row.get("tests", ())),
                required_memory_facets=tuple(
                    row.get("required_memory_facets", ("operation", "precondition", "verification"))
                ),
            ))
        for row in result.get("dependency_additions", ()):
            graph.add_dependency(str(row["node_id"]), str(row["depends_on"]))

    @staticmethod
    def _tool_evidence(step_no, tool, arguments, result):
        attributes: dict[str, Any] = {}
        if tool in {"read_file", "write_file"} and arguments.get("path"):
            attributes["files"] = [arguments["path"]]
        if tool == "search":
            attributes["files"] = sorted({hit["path"] for hit in result.get("hits", [])})
        if tool == "run_public_tests" and not result.get("passed"):
            attributes["errors"] = [result.get("stderr") or result.get("stdout") or "public test failed"]
            attributes["tests"] = ["public test"]
        if tool == "run_command":
            attributes["tests"] = ["public repository command"]
            if result.get("exit_code") != 0:
                attributes["errors"] = [
                    result.get("stderr") or result.get("stdout") or "public repository command failed"
                ]
        if tool == "revise_subtask_dag":
            attributes["predicted_operation"] = "revise semantic subtask topology from new evidence"
        supports = tool == "complete_subtask" and bool(result.get("completed"))
        return Evidence.capture(
            "tool_result",
            f"step {step_no} {tool}: {json.dumps(result, ensure_ascii=False, sort_keys=True)}",
            {"tool": tool, "arguments": arguments, "result": result},
            source=tool,
            attributes=attributes,
            supports_completion=supports,
            evidence_id=f"tool-{step_no:04d}",
        )


def _injection_dict(item: MemoryInjection) -> dict[str, Any]:
    return {
        "memory_id": item.memory_id,
        "kind": item.kind.value,
        "active_node_id": item.active_node_id,
        "exact_text": item.exact_text,
        "byte_count": item.byte_count,
        "sha256": item.sha256,
        "confidence": item.confidence,
        "margin": item.margin,
        "graph_hash": item.graph_hash,
        "memory_version": item.memory_version,
    }


def _memory_ledger(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = state.get("ledger", []) if isinstance(state, Mapping) else []
    return [dict(row) for row in rows]


def _memory_ids(state: Mapping[str, Any]) -> set[str]:
    return {str(row["memory_id"]) for row in _memory_ledger(state)}


def _memory_bytes(state: Mapping[str, Any]) -> int:
    return sum(int(row["byte_count"]) for row in _memory_ledger(state))


def _outcome_metrics(
    graph: ShortTermWorkingGraph,
    accounting: RunAccounting,
    injections: tuple[Mapping[str, Any], ...],
    recall_rejections: list[dict[str, Any]],
    grade: GradeResult,
) -> dict[str, Any]:
    total = len(graph.nodes)
    completed = sum(node.status == "COMPLETED" for node in graph.nodes.values())
    summary = accounting.summary()
    injected_ids = {str(row.get("memory_id", "")) for row in injections}
    # Recall rejection is pre-use evidence and therefore cannot establish
    # negative transfer.  Only a trusted grader's explicit post-use marker may
    # penalize a memory that was actually injected.
    raw_feedback = grade.report.get("post_use_memory_feedback", ())
    if not isinstance(raw_feedback, (list, tuple)):
        raise RuntimeFailure("post-use memory feedback must be a list")
    stale_conflict_ids: set[str] = set()
    for row in raw_feedback:
        if not isinstance(row, Mapping) or set(row) != {
            "memory_id", "disposition", "evidence_hash"
        }:
            raise RuntimeFailure("post-use memory feedback shape is invalid")
        memory_id = row.get("memory_id")
        disposition = row.get("disposition")
        evidence_hash = row.get("evidence_hash")
        if (
            not isinstance(memory_id, str)
            or not memory_id
            or disposition not in {"STALE", "CONFLICT", "CONTRADICTED"}
            or not isinstance(evidence_hash, str)
            or len(evidence_hash) != 64
            or any(character not in "0123456789abcdef" for character in evidence_hash)
        ):
            raise RuntimeFailure("post-use memory feedback value is invalid")
        if memory_id in injected_ids:
            stale_conflict_ids.add(memory_id)
    # Keep this argument intentional: rejected candidates remain evidence for
    # audit, but must never be converted into a post-use penalty.
    if not isinstance(recall_rejections, list):
        raise RuntimeFailure("recall rejection evidence must be a list")
    conflict_ids = tuple(sorted(stale_conflict_ids))
    return {
        "schema": "trimem/outcome-metrics/1.0",
        "subtask_completion": completed / total if total else 0.0,
        "actual_total_tokens": int(summary["actual_input_tokens"])
        + int(summary["actual_output_tokens"]),
        "actual_reasoning_tokens": int(summary["actual_reasoning_tokens"]),
        "actual_wall_time_ms": int(summary["actual_model_wall_time_ms"])
        + int(summary["actual_tool_wall_time_ms"])
        + int(summary["actual_grader_wall_time_ms"]),
        "injected_context_bytes": sum(int(row.get("byte_count", 0)) for row in injections),
        "stale_conflict_reuse_count": len(conflict_ids),
        "stale_conflict_memory_ids": list(conflict_ids),
    }


def _lifecycle_configuration_hash(lifecycle: object) -> str:
    value = getattr(lifecycle, "configuration_hash", None)
    if isinstance(value, str):
        value = value.removeprefix("sha256:")
        if len(value) == 64 and all(ch in "0123456789abcdef" for ch in value):
            return value
        raise ValueError("lifecycle configuration_hash must be sha256")
    return sha256_bytes(
        (type(lifecycle).__module__ + "." + type(lifecycle).__qualname__).encode("utf-8")
    )


def _lifecycle_checkpoint_state(lifecycle: object) -> dict[str, Any]:
    snapshot = getattr(lifecycle, "checkpoint_state", None)
    if not callable(snapshot):
        return {}
    value = snapshot()
    if not isinstance(value, Mapping):
        raise RuntimeFailure("lifecycle checkpoint state must be a mapping")
    # Canonical serialization rejects process objects and other values that
    # could not survive a real restart.
    canonical_bytes(value)
    return dict(value)


def _store_terminal_grade(payload: dict[str, Any], grade: GradeResult) -> None:
    value = asdict(grade)
    payload["grade"] = value
    payload["grade_sha256"] = sha256_bytes(canonical_bytes(value))


def _grade_from_terminal(
    value: object,
    task_id: str,
    payload: Mapping[str, Any],
) -> GradeResult:
    if not isinstance(value, Mapping):
        raise RuntimeFailure("terminal checkpoint has no grader result")
    observed = sha256_bytes(canonical_bytes(value))
    if payload.get("grade_sha256") != observed:
        raise RuntimeFailure("terminal grader result hash mismatch")
    try:
        grade = GradeResult(**dict(value))
    except (TypeError, ValueError) as exc:
        raise RuntimeFailure("terminal grader result is invalid") from exc
    if grade.task_id != task_id:
        raise RuntimeFailure("terminal grader task identity mismatch")
    return grade


def _extraction_from_terminal(
    value: object,
    payload: Mapping[str, Any],
) -> ExperienceExtraction:
    if not isinstance(value, Mapping):
        raise RuntimeFailure("terminal checkpoint has no extraction result")
    observed = sha256_bytes(canonical_bytes(value))
    if payload.get("extraction_sha256") != observed:
        raise RuntimeFailure("terminal extraction result hash mismatch")
    try:
        semantic = value.get("semantic_candidate")
        return ExperienceExtraction(
            episode=dict(value["episode"]),
            semantic_candidate=dict(semantic) if semantic is not None else None,
            response_hash=str(value["response_hash"]),
            patch_hash=str(value["patch_hash"]),
            public_evidence_hash=str(value["public_evidence_hash"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeFailure("terminal extraction result is invalid") from exc


def _mapping_from_terminal(
    payload: Mapping[str, Any],
    value_name: str,
    hash_name: str,
) -> dict[str, Any]:
    value = payload.get(value_name)
    if not isinstance(value, Mapping):
        raise RuntimeFailure(f"terminal checkpoint has no {value_name}")
    copied = dict(value)
    if payload.get(hash_name) != sha256_bytes(canonical_bytes(copied)):
        raise RuntimeFailure(f"terminal {value_name} hash mismatch")
    return copied
