"""Credential-free R23-R0 execution, replay, budgeting, and evidence runtime.

The runtime accepts an injected reader.  This repository intentionally ships
only ``FakeReader`` and ``ReplayReader``: neither can contact a model service.
An official reader/Docker adapter is a later EXEC-approved action.  All six R0
arms nevertheless traverse the same payload, budget, journal, checkpoint, and
streaming paths used by such an adapter.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from experiments.r23.author_method import (
    ARMS,
    WHOLE_TASK,
    CategoryMachine,
    MemoryEntry,
    StreamingState,
    SubtaskIntent,
    TaskInput,
    TrajectoryEvent,
    arm_config,
    build_extraction_payload,
    build_solve_payload,
    canonical_json,
    content_hash,
    derive_intent,
    parse_extracted_memory,
    retrieve_for_arm,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "r23"

SCAFFOLD_STEP_CAP = 250
SOLVER_CALL_HARD_CAP = 250
COMMON_RESERVED_EXTRACTION_CALLS = 4
TOTAL_CALL_HARD_CAP = SOLVER_CALL_HARD_CAP + COMMON_RESERVED_EXTRACTION_CALLS
SOLVER_INPUT_TOKEN_HARD_CAP = 1_000_000
SOLVER_OUTPUT_TOKEN_HARD_CAP = 100_000
COMMON_RESERVED_EXTRACTION_INPUT_TOKENS = 64_000
COMMON_RESERVED_EXTRACTION_OUTPUT_TOKENS = 8_192
TOTAL_INPUT_TOKEN_HARD_CAP = SOLVER_INPUT_TOKEN_HARD_CAP + COMMON_RESERVED_EXTRACTION_INPUT_TOKENS
TOTAL_OUTPUT_TOKEN_HARD_CAP = SOLVER_OUTPUT_TOKEN_HARD_CAP + COMMON_RESERVED_EXTRACTION_OUTPUT_TOKENS
MEMORY_INJECTION_TOKEN_CAP = 2_048
SOLVE_CALL_MAX_OUTPUT_TOKENS = 4_096
EXTRACTION_CALL_MAX_OUTPUT_TOKENS = 2_048

ARM_EXTRACTION_INPUT_HARD_CAP = {
    "AR0": 0,
    "AR1": 0,
    "AR2": 16_000,
    "AR3": COMMON_RESERVED_EXTRACTION_INPUT_TOKENS,
    "AR4": COMMON_RESERVED_EXTRACTION_INPUT_TOKENS,
    "AR5": COMMON_RESERVED_EXTRACTION_INPUT_TOKENS,
}
ARM_EXTRACTION_OUTPUT_HARD_CAP = {
    "AR0": 0,
    "AR1": 0,
    "AR2": 2_048,
    "AR3": COMMON_RESERVED_EXTRACTION_OUTPUT_TOKENS,
    "AR4": COMMON_RESERVED_EXTRACTION_OUTPUT_TOKENS,
    "AR5": COMMON_RESERVED_EXTRACTION_OUTPUT_TOKENS,
}


class BudgetExceeded(RuntimeError):
    pass


class EvidenceIntegrityError(RuntimeError):
    pass


class IncompleteCallEvidence(EvidenceIntegrityError):
    pass


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _append_jsonl(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical_json(value) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvidenceIntegrityError("invalid JSONL at %s:%d" % (path, number)) from error
        if not isinstance(row, dict):
            raise EvidenceIntegrityError("JSONL row must be an object at %s:%d" % (path, number))
        rows.append(row)
    return rows


def estimate_tokens(value: object) -> int:
    """Frozen credential-free preflight estimate: ceil(UTF-8 bytes / 3), minimum one."""

    byte_count = len(canonical_json(value).encode("utf-8"))
    return max(1, (byte_count + 2) // 3)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int

    def validate(self) -> "Usage":
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts cannot be negative")
        return self


@dataclass(frozen=True)
class ReaderResponse:
    content: str
    actions: tuple[dict, ...] = ()
    transition_signal: str = "CONTINUE"
    local_outcome: str = "SUCCESS"
    subtask_complete: bool = False
    task_complete: bool = False
    extraction: dict | None = None
    submission: str = ""
    usage: Usage = Usage(0, 0)
    origin_external_model_call: bool = False
    origin_paid_model_call: bool = False

    def validate(self) -> "ReaderResponse":
        if self.local_outcome not in {"SUCCESS", "FAILURE"}:
            raise ValueError("reader local_outcome must be SUCCESS or FAILURE")
        self.usage.validate()
        if self.origin_paid_model_call and not self.origin_external_model_call:
            raise ValueError("paid call must also be an external model call")
        return self

    def to_dict(self) -> dict:
        value = asdict(self)
        value["actions"] = list(self.actions)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ReaderResponse":
        usage = value.get("usage", {})
        if not isinstance(usage, Mapping):
            raise ValueError("reader response usage must be an object")
        extraction = value.get("extraction")
        if extraction is not None and not isinstance(extraction, Mapping):
            raise ValueError("reader response extraction must be an object or null")
        response = cls(
            content=str(value.get("content", "")),
            actions=tuple(dict(action) for action in value.get("actions", [])),
            transition_signal=str(value.get("transition_signal", "CONTINUE")),
            local_outcome=str(value.get("local_outcome", "SUCCESS")).upper(),
            subtask_complete=bool(value.get("subtask_complete", False)),
            task_complete=bool(value.get("task_complete", False)),
            extraction=dict(extraction) if extraction is not None else None,
            submission=str(value.get("submission", "")),
            usage=Usage(int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))),
            origin_external_model_call=bool(value.get("origin_external_model_call", False)),
            origin_paid_model_call=bool(value.get("origin_paid_model_call", False)),
        )
        return response.validate()


class Reader(Protocol):
    mode: str

    def __call__(self, call_kind: str, payload: Mapping[str, object]) -> ReaderResponse:
        ...


class FakeReader:
    """Deterministic, credential-free reader that exercises every production contract."""

    mode = "fake"

    def __init__(self, failure_task_ids: Sequence[str] = ()) -> None:
        self.failure_task_ids = set(failure_task_ids)
        self.invocations: list[dict] = []

    def __call__(self, call_kind: str, payload: Mapping[str, object]) -> ReaderResponse:
        payload_sha256 = content_hash(payload)
        self.invocations.append({"call_kind": call_kind, "payload_sha256": payload_sha256})
        task = payload.get("task", {})
        task_id = str(task.get("task_id", "")) if isinstance(task, Mapping) else ""
        input_tokens = estimate_tokens(payload)

        if call_kind == "extract":
            outcome = str(payload["local_outcome"]).upper()
            category = str(payload["intent"]["z"])
            kind = "reusable success pattern" if outcome == "SUCCESS" else "failure-avoidance lesson"
            experience = "%s for %s from target-visible trajectory evidence" % (kind, category)
            return ReaderResponse(
                content=canonical_json({"evaluation": outcome, "experience": experience}),
                extraction={"evaluation": outcome, "experience": experience},
                local_outcome=outcome,
                usage=Usage(input_tokens, estimate_tokens(experience)),
            ).validate()

        if call_kind != "solve":
            raise ValueError("unsupported reader call kind %r" % call_kind)
        control = payload.get("r23_control")
        failed = task_id in self.failure_task_ids
        if control is None or (isinstance(control, Mapping) and control.get("current_category") == WHOLE_TASK):
            outcome = "FAILURE" if failed else "SUCCESS"
            signal = "TASK_FAILED" if failed else "TASK_COMPLETE"
            return ReaderResponse(
                content="fake whole-task solver response for %s" % task_id,
                actions=({"command": "true"},),
                transition_signal=signal,
                local_outcome=outcome,
                subtask_complete=True,
                task_complete=True,
                submission="" if failed else "diff --git a/example.py b/example.py\n",
                usage=Usage(input_tokens, 16),
            ).validate()

        if not isinstance(control, Mapping):
            raise ValueError("structured solve payload missing r23_control")
        category = str(control["current_category"])
        transitions = {
            "ANALYZE": "ANALYSIS_COMPLETE",
            "REPRODUCE": "REPRODUCTION_COMPLETE",
            "EDIT": "EDIT_COMPLETE",
            "VERIFY": "VERIFICATION_FAILED" if failed else "VERIFICATION_PASSED",
        }
        if category not in transitions:
            raise ValueError("fake reader received invalid category %r" % category)
        outcome = "FAILURE" if category == "VERIFY" and failed else "SUCCESS"
        terminal = category == "VERIFY"
        return ReaderResponse(
            content="fake %s solver response for %s" % (category.lower(), task_id),
            actions=({"command": "true"},),
            transition_signal=transitions[category],
            local_outcome=outcome,
            subtask_complete=True,
            task_complete=terminal,
            submission="" if failed else ("diff --git a/example.py b/example.py\n" if terminal else ""),
            usage=Usage(input_tokens, 16),
        ).validate()


class ReplayReader:
    """Credential-free ordered replay of previously captured response objects."""

    mode = "replay"

    def __init__(self, records: Sequence[Mapping[str, object]]) -> None:
        self._records = [dict(record) for record in records]
        self._index = 0
        self.invocations: list[dict] = []

    @classmethod
    def from_jsonl(cls, path: Path) -> "ReplayReader":
        return cls(_read_jsonl(path))

    @property
    def remaining(self) -> int:
        return len(self._records) - self._index

    def __call__(self, call_kind: str, payload: Mapping[str, object]) -> ReaderResponse:
        if self._index >= len(self._records):
            raise EvidenceIntegrityError("replay exhausted")
        row = self._records[self._index]
        self._index += 1
        payload_sha256 = content_hash(payload)
        expected_kind = row.get("call_kind", call_kind)
        expected_hash = row.get("payload_sha256")
        if expected_kind != call_kind:
            raise EvidenceIntegrityError("replay call-kind mismatch")
        if expected_hash is not None and expected_hash != payload_sha256:
            raise EvidenceIntegrityError("replay payload hash mismatch")
        raw_response = row.get("response", row)
        if not isinstance(raw_response, Mapping):
            raise EvidenceIntegrityError("replay response must be an object")
        self.invocations.append({"call_kind": call_kind, "payload_sha256": payload_sha256})
        # Replaying evidence makes no external or paid call now, even when the origin did.
        response = ReaderResponse.from_dict(raw_response)
        return ReaderResponse(
            **{
                **response.to_dict(),
                "actions": response.actions,
                "usage": response.usage,
                "origin_external_model_call": False,
                "origin_paid_model_call": False,
            }
        ).validate()


def deterministic_fake_embed(description: dict) -> list[float]:
    """Offline test/replay embedder, never the preregistered live semantic encoder."""

    vector = [0.0] * 64
    text = "%s %s" % (description.get("objective", ""), " ".join(description.get("keywords", [])))
    for token in re.findall(r"[a-z0-9_.-]+", text.lower()):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:2], "big") % len(vector)
        vector[bucket] += 1.0 if digest[2] % 2 else -1.0
    return vector


@dataclass(frozen=True)
class BudgetContract:
    arm: str
    scaffold_step_cap: int
    solver_calls_hard_cap: int
    extraction_calls_hard_cap: int
    common_reserved_extraction_calls: int
    total_calls_hard_cap: int
    solver_input_tokens_hard_cap: int
    solver_output_tokens_hard_cap: int
    extraction_input_tokens_hard_cap: int
    extraction_output_tokens_hard_cap: int
    common_total_input_tokens_hard_cap: int
    common_total_output_tokens_hard_cap: int
    memory_injection_token_cap: int

    @classmethod
    def for_arm(cls, arm: str) -> "BudgetContract":
        config = arm_config(arm)
        return cls(
            arm=arm,
            scaffold_step_cap=SCAFFOLD_STEP_CAP,
            solver_calls_hard_cap=SOLVER_CALL_HARD_CAP,
            extraction_calls_hard_cap=int(config["extraction_call_cap"]),
            common_reserved_extraction_calls=COMMON_RESERVED_EXTRACTION_CALLS,
            total_calls_hard_cap=TOTAL_CALL_HARD_CAP,
            solver_input_tokens_hard_cap=SOLVER_INPUT_TOKEN_HARD_CAP,
            solver_output_tokens_hard_cap=SOLVER_OUTPUT_TOKEN_HARD_CAP,
            extraction_input_tokens_hard_cap=ARM_EXTRACTION_INPUT_HARD_CAP[arm],
            extraction_output_tokens_hard_cap=ARM_EXTRACTION_OUTPUT_HARD_CAP[arm],
            common_total_input_tokens_hard_cap=TOTAL_INPUT_TOKEN_HARD_CAP,
            common_total_output_tokens_hard_cap=TOTAL_OUTPUT_TOKEN_HARD_CAP,
            memory_injection_token_cap=MEMORY_INJECTION_TOKEN_CAP,
        )

    @property
    def contract_sha256(self) -> str:
        return content_hash(asdict(self))


@dataclass
class BudgetLedger:
    contract: BudgetContract
    solver_calls: int = 0
    extraction_calls: int = 0
    solver_input_tokens: int = 0
    solver_output_tokens: int = 0
    extraction_input_tokens: int = 0
    extraction_output_tokens: int = 0

    @property
    def total_calls(self) -> int:
        return self.solver_calls + self.extraction_calls

    @property
    def total_input_tokens(self) -> int:
        return self.solver_input_tokens + self.extraction_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self.solver_output_tokens + self.extraction_output_tokens

    def preflight(self, call_kind: str, payload: Mapping[str, object]) -> None:
        estimated_input = estimate_tokens(payload)
        requested_output = int(payload.get("generation", {}).get("max_output_tokens", 0))
        if call_kind == "solve":
            if self.solver_calls + 1 > self.contract.solver_calls_hard_cap:
                raise BudgetExceeded("solver call/step cap exhausted")
            if self.solver_input_tokens + estimated_input > self.contract.solver_input_tokens_hard_cap:
                raise BudgetExceeded("solver input-token cap exhausted")
            if self.solver_output_tokens + requested_output > self.contract.solver_output_tokens_hard_cap:
                raise BudgetExceeded("solver output-token reservation exceeds cap")
        elif call_kind == "extract":
            if self.extraction_calls + 1 > self.contract.extraction_calls_hard_cap:
                raise BudgetExceeded("extraction call cap exhausted")
            if self.extraction_input_tokens + estimated_input > self.contract.extraction_input_tokens_hard_cap:
                raise BudgetExceeded("extraction input-token cap exhausted")
            if self.extraction_output_tokens + requested_output > self.contract.extraction_output_tokens_hard_cap:
                raise BudgetExceeded("extraction output-token reservation exceeds cap")
        else:
            raise ValueError("unknown call kind %r" % call_kind)
        if self.total_calls + 1 > self.contract.total_calls_hard_cap:
            raise BudgetExceeded("common total call cap exhausted")
        if self.total_input_tokens + estimated_input > self.contract.common_total_input_tokens_hard_cap:
            raise BudgetExceeded("common total input-token cap exhausted")
        if self.total_output_tokens + requested_output > self.contract.common_total_output_tokens_hard_cap:
            raise BudgetExceeded("common total output-token reservation exceeds cap")

    def commit(self, call_kind: str, usage: Usage) -> None:
        usage.validate()
        if call_kind == "solve":
            self.solver_calls += 1
            self.solver_input_tokens += usage.input_tokens
            self.solver_output_tokens += usage.output_tokens
        elif call_kind == "extract":
            self.extraction_calls += 1
            self.extraction_input_tokens += usage.input_tokens
            self.extraction_output_tokens += usage.output_tokens
        else:
            raise ValueError("unknown call kind %r" % call_kind)
        if self.solver_calls > self.contract.solver_calls_hard_cap:
            raise BudgetExceeded("solver call/step cap exceeded")
        if self.extraction_calls > self.contract.extraction_calls_hard_cap:
            raise BudgetExceeded("extraction call cap exceeded")
        if self.total_calls > self.contract.total_calls_hard_cap:
            raise BudgetExceeded("common total call cap exceeded")
        if self.solver_input_tokens > self.contract.solver_input_tokens_hard_cap:
            raise BudgetExceeded("solver input-token cap exceeded")
        if self.solver_output_tokens > self.contract.solver_output_tokens_hard_cap:
            raise BudgetExceeded("solver output-token cap exceeded")
        if self.extraction_input_tokens > self.contract.extraction_input_tokens_hard_cap:
            raise BudgetExceeded("extraction input-token cap exceeded")
        if self.extraction_output_tokens > self.contract.extraction_output_tokens_hard_cap:
            raise BudgetExceeded("extraction output-token cap exceeded")
        if self.total_input_tokens > self.contract.common_total_input_tokens_hard_cap:
            raise BudgetExceeded("common total input-token cap exceeded")
        if self.total_output_tokens > self.contract.common_total_output_tokens_hard_cap:
            raise BudgetExceeded("common total output-token cap exceeded")

    def to_dict(self) -> dict:
        return {
            "solver_calls": self.solver_calls,
            "extraction_calls": self.extraction_calls,
            "total_calls": self.total_calls,
            "solver_input_tokens": self.solver_input_tokens,
            "solver_output_tokens": self.solver_output_tokens,
            "extraction_input_tokens": self.extraction_input_tokens,
            "extraction_output_tokens": self.extraction_output_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "contract_sha256": self.contract.contract_sha256,
        }


@dataclass
class InvocationAccounting:
    executed_calls_now: int = 0
    replayed_calls: int = 0
    external_model_calls_now: int = 0
    paid_model_calls_now: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class CallJournal:
    """Full request/response evidence with call-level deterministic resume."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.requests_path = root / "requests.jsonl"
        self.responses_path = root / "responses.jsonl"

    def _indexed(self) -> tuple[dict[str, dict], dict[str, dict]]:
        requests = _read_jsonl(self.requests_path)
        responses = _read_jsonl(self.responses_path)
        request_map = {str(row.get("call_id")): row for row in requests}
        response_map = {str(row.get("call_id")): row for row in responses}
        if len(request_map) != len(requests) or len(response_map) != len(responses):
            raise EvidenceIntegrityError("duplicate call_id in raw evidence")
        if set(response_map) - set(request_map):
            raise EvidenceIntegrityError("response exists without request")
        return request_map, response_map

    def invoke(
        self,
        *,
        call_index: int,
        call_kind: str,
        payload: Mapping[str, object],
        reader: Reader,
        ledger: BudgetLedger,
        accounting: InvocationAccounting,
    ) -> ReaderResponse:
        call_id = "call-%04d" % call_index
        payload_sha256 = content_hash(payload)
        request_map, response_map = self._indexed()
        if call_id in request_map:
            request = request_map[call_id]
            if request.get("call_kind") != call_kind or request.get("payload_sha256") != payload_sha256:
                raise EvidenceIntegrityError("resume payload mismatch for %s" % call_id)
            if call_id not in response_map:
                raise IncompleteCallEvidence(
                    "%s has a durable request but no response; fail closed to avoid repeating a paid call" % call_id
                )
            response = ReaderResponse.from_dict(response_map[call_id]["response"])
            ledger.commit(call_kind, response.usage)
            accounting.replayed_calls += 1
            return response

        ledger.preflight(call_kind, payload)
        _append_jsonl(
            self.requests_path,
            {
                "call_id": call_id,
                "call_kind": call_kind,
                "payload_sha256": payload_sha256,
                "payload": dict(payload),
                "reader_mode": reader.mode,
            },
        )
        try:
            response = reader(call_kind, payload).validate()
        except Exception as error:
            _append_jsonl(
                self.root / "errors.jsonl",
                {"call_id": call_id, "error_type": type(error).__name__, "error": str(error)},
            )
            raise
        _append_jsonl(
            self.responses_path,
            {
                "call_id": call_id,
                "call_kind": call_kind,
                "payload_sha256": payload_sha256,
                "response": response.to_dict(),
            },
        )
        ledger.commit(call_kind, response.usage)
        accounting.executed_calls_now += 1
        if response.origin_external_model_call:
            accounting.external_model_calls_now += 1
        if response.origin_paid_model_call:
            accounting.paid_model_calls_now += 1
        return response


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("unsafe path component")
    return cleaned


def _scaffold_payload_contract() -> dict:
    lock = _load_json(ARTIFACTS / "agent_scaffold_lock.json")
    required = {
        "scaffold_repo",
        "commit",
        "config_path",
        "config_git_blob",
        "config_sha256",
        "system_prompt_sha256",
        "instance_prompt_sha256",
        "observation_prompt_sha256",
        "format_error_prompt_sha256",
        "tool_schema_canonical_sha256",
        "tool_call_parser_source_sha256",
        "patch_parser_source_sha256",
        "default_step_cap",
        "environment",
        "mount_and_image_route",
    }
    missing = required - set(lock)
    if missing:
        raise EvidenceIntegrityError("incomplete scaffold lock: %s" % sorted(missing))
    if lock["commit"] != "25941c89cfbc91eb40b3f8756348c91d9977d57e":
        raise EvidenceIntegrityError("unexpected Mini-SWE-Agent commit")
    if int(lock["default_step_cap"]) != SCAFFOLD_STEP_CAP:
        raise EvidenceIntegrityError("runtime/scaffold step-cap drift")
    return {key: lock[key] for key in sorted(required)}


@dataclass
class TaskRun:
    result: dict
    memory_entries: list[MemoryEntry]


class R0Runner:
    def __init__(
        self,
        *,
        output_root: Path,
        reader: Reader,
        embed: Callable[[dict], Sequence[float]] = deterministic_fake_embed,
    ) -> None:
        if reader.mode not in {"fake", "replay"}:
            raise ValueError("R0 repository runtime permits only credential-free fake/replay readers before EXEC")
        self.output_root = output_root.resolve()
        self.reader = reader
        self.embed = embed
        self.scaffold = _scaffold_payload_contract()

    def _invoke(
        self,
        *,
        journal: CallJournal,
        ledger: BudgetLedger,
        accounting: InvocationAccounting,
        call_kind: str,
        payload: Mapping[str, object],
    ) -> ReaderResponse:
        return journal.invoke(
            call_index=ledger.total_calls,
            call_kind=call_kind,
            payload=payload,
            reader=self.reader,
            ledger=ledger,
            accounting=accounting,
        )

    def _extract(
        self,
        *,
        arm: str,
        task: TaskInput,
        intent: SubtaskIntent,
        events: Sequence[TrajectoryEvent],
        local_outcome: str,
        journal: CallJournal,
        ledger: BudgetLedger,
        accounting: InvocationAccounting,
    ) -> MemoryEntry:
        payload = build_extraction_payload(
            arm=arm,
            task=task,
            intent=intent,
            events=events,
            local_outcome=local_outcome,
            max_output_tokens=EXTRACTION_CALL_MAX_OUTPUT_TOKENS,
        )
        response = self._invoke(
            journal=journal,
            ledger=ledger,
            accounting=accounting,
            call_kind="extract",
            payload=payload,
        )
        if response.extraction is None:
            raise ValueError("extractor response missing structured extraction")
        return parse_extracted_memory(
            arm=arm,
            task=task,
            intent=intent,
            events=events,
            local_outcome=local_outcome,
            extracted=response.extraction,
            injection_token_cap=ledger.contract.memory_injection_token_cap,
        )

    def _run_task(self, *, arm: str, task: TaskInput, state: StreamingState, task_root: Path) -> TaskRun:
        config = arm_config(arm)
        contract = BudgetContract.for_arm(arm)
        ledger = BudgetLedger(contract)
        accounting = InvocationAccounting()
        journal = CallJournal(task_root / "raw_evidence")
        visible = state.visible_for(task.task_id)
        history: list[TrajectoryEvent] = []
        buffered_entries: list[MemoryEntry] = []
        retrieved_source_ids: list[str] = []
        submission = ""
        final_outcome = "FAILURE"

        if config["structured_transitions"]:
            machine = CategoryMachine()
            while not machine.finished:
                category = machine.current
                intent = derive_intent(task, category)
                memory = retrieve_for_arm(arm, intent, visible, self.embed)
                if memory is not None:
                    if memory.source_task_id == task.task_id:
                        raise AssertionError("online no-self-memory violation")
                    retrieved_source_ids.append(memory.source_task_id)
                payload = build_solve_payload(
                    scaffold=self.scaffold,
                    arm=arm,
                    task=task,
                    intent=intent,
                    history=history,
                    memory=memory,
                    allowed_signals=machine.allowed_signals(),
                    max_output_tokens=SOLVE_CALL_MAX_OUTPUT_TOKENS,
                    injection_token_cap=contract.memory_injection_token_cap,
                )
                response = self._invoke(
                    journal=journal,
                    ledger=ledger,
                    accounting=accounting,
                    call_kind="solve",
                    payload=payload,
                )
                event = TrajectoryEvent(
                    category=category,
                    content=response.content,
                    actions=response.actions,
                    transition_signal=response.transition_signal,
                    local_outcome=response.local_outcome,
                    subtask_complete=response.subtask_complete,
                    task_complete=response.task_complete,
                )
                history.append(event)
                if response.subtask_complete:
                    if response.transition_signal == "CONTINUE":
                        raise ValueError("completed subtask cannot signal CONTINUE")
                    local_events = [row for row in history if row.category == category]
                    if config["extraction_scope"] == "per_subtask":
                        buffered_entries.append(
                            self._extract(
                                arm=arm,
                                task=task,
                                intent=intent,
                                events=local_events,
                                local_outcome=response.local_outcome,
                                journal=journal,
                                ledger=ledger,
                                accounting=accounting,
                            )
                        )
                    machine.apply(response.transition_signal)
                    if machine.finished != response.task_complete:
                        raise ValueError("task_complete disagrees with terminal category transition")
                else:
                    if response.transition_signal != "CONTINUE" or response.task_complete:
                        raise ValueError("incomplete subtask must CONTINUE without completing task")
                    machine.apply("CONTINUE")
                submission = response.submission or submission
                final_outcome = response.local_outcome
        else:
            intent = derive_intent(task, WHOLE_TASK)
            while True:
                memory = retrieve_for_arm(arm, intent, visible, self.embed)
                if memory is not None:
                    if memory.source_task_id == task.task_id:
                        raise AssertionError("online no-self-memory violation")
                    retrieved_source_ids.append(memory.source_task_id)
                payload = build_solve_payload(
                    scaffold=self.scaffold,
                    arm=arm,
                    task=task,
                    intent=intent,
                    history=history,
                    memory=memory,
                    allowed_signals=("CONTINUE", "TASK_COMPLETE", "TASK_FAILED"),
                    max_output_tokens=SOLVE_CALL_MAX_OUTPUT_TOKENS,
                    injection_token_cap=contract.memory_injection_token_cap,
                )
                response = self._invoke(
                    journal=journal,
                    ledger=ledger,
                    accounting=accounting,
                    call_kind="solve",
                    payload=payload,
                )
                if response.transition_signal not in {"CONTINUE", "TASK_COMPLETE", "TASK_FAILED"}:
                    raise ValueError("invalid unstructured transition")
                event = TrajectoryEvent(
                    category=WHOLE_TASK,
                    content=response.content,
                    actions=response.actions,
                    transition_signal=response.transition_signal,
                    local_outcome=response.local_outcome,
                    subtask_complete=response.subtask_complete,
                    task_complete=response.task_complete,
                )
                history.append(event)
                submission = response.submission or submission
                final_outcome = response.local_outcome
                if response.task_complete:
                    break
                if response.transition_signal != "CONTINUE":
                    raise ValueError("nonterminal unstructured solve must signal CONTINUE")
            if config["extraction_scope"] == "whole_task":
                buffered_entries.append(
                    self._extract(
                        arm=arm,
                        task=task,
                        intent=intent,
                        events=history,
                        local_outcome=final_outcome,
                        journal=journal,
                        ledger=ledger,
                        accounting=accounting,
                    )
                )

        if any(entry.source_task_id == task.task_id for entry in visible):
            raise AssertionError("target saw its own memory")
        result = {
            "schema_version": "r23/r0/task_result/1.0.0",
            "track": "R23-R",
            "method_family": "COARSE_AUTHOR_REPRODUCTION",
            "arm": arm,
            "task_id": task.task_id,
            "repository": task.repository,
            "outcome": final_outcome,
            "submission": submission,
            "transition_signals": [event.transition_signal for event in history],
            "visible_source_task_ids": sorted({entry.source_task_id for entry in visible}),
            "retrieved_source_task_ids": retrieved_source_ids,
            "self_memory_seen": False,
            "buffered_memory_entries": [asdict(entry) for entry in buffered_entries],
            "budget": ledger.to_dict(),
            "invocation_accounting": accounting.to_dict(),
            "raw_evidence": {
                "requests": "raw_evidence/requests.jsonl",
                "responses": "raw_evidence/responses.jsonl",
                "errors": "raw_evidence/errors.jsonl",
            },
        }
        _write_json_atomic(task_root / "result.json", result)
        return TaskRun(result=result, memory_entries=buffered_entries)

    def run_stream(
        self,
        *,
        arm: str,
        order_id: str,
        tasks: Sequence[TaskInput],
        stop_after_tasks: int | None = None,
    ) -> dict:
        arm_config(arm)
        ids = [task.task_id for task in tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("stream order contains duplicate task IDs")
        order_sha256 = content_hash(ids)
        stream_root = self.output_root / "streams" / _safe_component(order_id) / arm
        checkpoint_path = stream_root / "checkpoint.json"
        contract = BudgetContract.for_arm(arm)

        if checkpoint_path.exists():
            checkpoint = _load_json(checkpoint_path)
            expected = {
                "arm": arm,
                "order_id": order_id,
                "order_sha256": order_sha256,
                "budget_contract_sha256": contract.contract_sha256,
            }
            for key, value in expected.items():
                if checkpoint.get(key) != value:
                    raise EvidenceIntegrityError("checkpoint %s mismatch" % key)
            state = StreamingState.from_dict(checkpoint["streaming_state"])
            next_index = int(checkpoint["next_index"])
            results = list(checkpoint.get("results", []))
            if [row["task_id"] for row in results] != ids[:next_index]:
                raise EvidenceIntegrityError("checkpoint completed prefix mismatch")
            if state.completed != set(ids[:next_index]):
                raise EvidenceIntegrityError("checkpoint memory/completed prefix mismatch")
        else:
            state = StreamingState()
            next_index = 0
            results = []
            checkpoint = {
                "schema_version": "r23/r0/checkpoint/1.0.0",
                "track": "R23-R",
                "arm": arm,
                "order_id": order_id,
                "order_sha256": order_sha256,
                "budget_contract_sha256": contract.contract_sha256,
                "next_index": 0,
                "inflight_task_id": None,
                "streaming_state": state.to_dict(),
                "results": [],
            }
            _write_json_atomic(checkpoint_path, checkpoint)

        completed_now = 0
        invocation_this_process = InvocationAccounting()
        for index in range(next_index, len(tasks)):
            if stop_after_tasks is not None and completed_now >= stop_after_tasks:
                break
            task = tasks[index]
            checkpoint["inflight_task_id"] = task.task_id
            _write_json_atomic(checkpoint_path, checkpoint)
            task_root = stream_root / "tasks" / ("%04d_%s" % (index, _safe_component(task.task_id)))
            task_run = self._run_task(arm=arm, task=task, state=state, task_root=task_root)
            task_accounting = task_run.result["invocation_accounting"]
            invocation_this_process.executed_calls_now += task_accounting["executed_calls_now"]
            invocation_this_process.replayed_calls += task_accounting["replayed_calls"]
            invocation_this_process.external_model_calls_now += task_accounting["external_model_calls_now"]
            invocation_this_process.paid_model_calls_now += task_accounting["paid_model_calls_now"]
            # Online isolation boundary: only now do this task's buffered entries become visible.
            state.commit(task.task_id, task_run.memory_entries)
            results.append(
                {
                    "task_id": task.task_id,
                    "result": str((task_root / "result.json").relative_to(stream_root)).replace("\\", "/"),
                    "outcome": task_run.result["outcome"],
                    "budget": task_run.result["budget"],
                    "invocation_accounting": task_run.result["invocation_accounting"],
                }
            )
            checkpoint.update(
                {
                    "next_index": index + 1,
                    "inflight_task_id": None,
                    "streaming_state": state.to_dict(),
                    "results": results,
                }
            )
            _write_json_atomic(checkpoint_path, checkpoint)
            completed_now += 1

        summary = {
            "schema_version": "r23/r0/stream_summary/1.0.0",
            "track": "R23-R",
            "method_family": "COARSE_AUTHOR_REPRODUCTION",
            "arm": arm,
            "order_id": order_id,
            "order_sha256": order_sha256,
            "complete": int(checkpoint["next_index"]) == len(tasks),
            "completed_tasks": int(checkpoint["next_index"]),
            "total_tasks": len(tasks),
            "memory_entries": len(state.store),
            "solver_call_slots_accounted": sum(row["budget"]["solver_calls"] for row in results),
            "extraction_call_slots_accounted": sum(row["budget"]["extraction_calls"] for row in results),
            "total_call_slots_accounted": sum(row["budget"]["total_calls"] for row in results),
            "reader_calls_executed_now": invocation_this_process.executed_calls_now,
            "reader_calls_replayed_now": invocation_this_process.replayed_calls,
            "external_model_calls_now": invocation_this_process.external_model_calls_now,
            "paid_model_calls_now": invocation_this_process.paid_model_calls_now,
            "budget_contract": asdict(contract),
            "budget_contract_sha256": contract.contract_sha256,
            "checkpoint": "checkpoint.json",
            "results": results,
        }
        _write_json_atomic(stream_root / "summary.json", summary)
        return summary


def load_tasks_manifest(path: Path) -> list[TaskInput]:
    raw = _load_json(path)
    rows = raw.get("tasks") if isinstance(raw, Mapping) else raw
    if not isinstance(rows, list):
        raise ValueError("task manifest must be a list or an object with a tasks list")
    return [TaskInput.from_mapping(row) for row in rows]


def budget_contract_matrix() -> dict[str, dict]:
    return {arm: asdict(BudgetContract.for_arm(arm)) for arm in ARMS}
