"""Model gateway boundary shared by paid providers and credential-free replay."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import time
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from .accounting import CallRecord, RawEvidenceLedger, RunAccounting, canonical_bytes, sha256_bytes
from enterprise_memory.providers.base import SINGLE_FUNCTION_CALL, STRUCTURED_TEXT
from .function_tools import (
    PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256,
    validate_function_arguments,
)


ACTION_CONTRACT_FAILURE_STATUSES = frozenset({
    "SOLVE_EXPECTED_FUNCTION_CALL",
    "SOLVE_MULTIPLE_FUNCTION_CALLS",
    "SOLVE_UNEXPECTED_MESSAGE_OUTPUT",
    "SOLVE_UNKNOWN_FUNCTION",
    "SOLVE_FUNCTION_ARGUMENT_INVALID_JSON",
    "SOLVE_FUNCTION_ARGUMENT_SCHEMA_FAILURE",
    "SOLVE_FUNCTION_CALL_ID_MISSING",
})

PREFLIGHT_PASSED = "PREFLIGHT_PASSED"
CELL_MODEL_PREFLIGHT_FAILURES = frozenset({
    "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
    "TASK_ARM_INPUT_POOL_EXHAUSTED",
    "TASK_ARM_MODEL_CALL_POOL_EXHAUSTED",
    "TASK_ROLE_OUTPUT_POOL_EXHAUSTED",
    "TASK_TOTAL_OUTPUT_POOL_EXHAUSTED",
})
GLOBAL_MODEL_PREFLIGHT_FAILURES = frozenset({
    "PHASE_MODEL_CALL_CAP_EXHAUSTED",
    "PHASE_INPUT_CAP_EXHAUSTED",
    "PHASE_OUTPUT_CAP_EXHAUSTED",
    "PHASE_USD_CAP_EXHAUSTED",
    "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE",
})

REQUEST_LIFECYCLE_CONTRACT: Mapping[str, Any] = {
    "schema": "trimem/request-lifecycle-contract/1.0",
    "covered_call_kinds": ["decompose", "solve", "extract"],
    "prepared_checkpoint_phases": {
        "decompose": "DECOMPOSE_PREPARED",
        "solve": "RECALL_PREPARED",
        "extract": "GRADED_OR_CELL_FAILURE_GRADED_REQUEST_SUFFIX",
    },
    "states": [
        "NOT_PREPARED",
        "NOT_STARTED",
        "PREFLIGHT_PASSED",
        "REQUEST_RECORDED",
        "PROVIDER_SEND_STARTED",
        "PROVIDER_TERMINAL_SUCCESS",
        "PROVIDER_TERMINAL_FAILURE",
        "PROVIDER_OUTCOME_UNKNOWN",
    ],
    "durable_journal_states": [
        "REQUEST_RECORDED",
        "PROVIDER_SEND_STARTED",
        "PROVIDER_TERMINAL_SUCCESS",
        "PROVIDER_TERMINAL_FAILURE",
        "PROVIDER_OUTCOME_UNKNOWN",
    ],
    "ordering": [
        "construct_exact_request",
        "deterministic_prompt_projection",
        "read_only_budget_preflight",
        "record_model_request",
        "record_journal_request",
        "atomic_reservation_recheck",
        "record_provider_send_started",
        "provider_invocation",
        "record_provider_terminal_outcome",
        "reconcile_atomic_ledger",
        "record_terminal_evidence_and_accounting",
    ],
    "resume_authorization": {
        "source": "HASH_BOUND_REQUEST_LIFECYCLE_SNAPSHOT",
        "not_started_requires_no_ledger_reservation": True,
        "provider_started_requires_terminal_or_unknown_replay": True,
        "replay_none_after_provider_start": "GLOBAL_INTEGRITY_FAILURE_NO_SEND",
    },
}
REQUEST_LIFECYCLE_CONTRACT_SHA256 = sha256_bytes(
    canonical_bytes(REQUEST_LIFECYCLE_CONTRACT)
)

RESUME_AUTOMATON: Mapping[str, Any] = {
    "schema": "trimem/request-resume-automaton/1.0",
    "covered_call_kinds": ["decompose", "solve", "extract"],
    "rules": {
        "A": {
            "evidence": "REQUEST_RECORDED",
            "journal": "ABSENT",
            "ledger": "ABSENT",
            "action": "PREFLIGHT_AND_SEND_ONCE_WITHOUT_DUPLICATE_REQUEST",
        },
        "B": {
            "journal": "REQUEST_RECORDED",
            "provider_send_started": False,
            "action": "RESERVE_OR_RESUME_AND_SEND_ONCE",
        },
        "C": {
            "journal": "PROVIDER_SEND_STARTED",
            "terminal": "ABSENT",
            "action": "DO_NOT_RETRY_SETTLE_UNKNOWN",
        },
        "D": {
            "journal": ["PROVIDER_TERMINAL_SUCCESS", "PROVIDER_TERMINAL_FAILURE"],
            "action": "RECONCILE_OR_VERIFY_AND_REPLAY_WITH_ZERO_PROVIDER_CALLS",
        },
        "E": {
            "preflight": "FAILED",
            "action": "NO_REQUEST_NO_RESERVATION_CELL_OR_GLOBAL_FAILURE",
        },
    },
}
RESUME_AUTOMATON_SHA256 = sha256_bytes(canonical_bytes(RESUME_AUTOMATON))


@dataclass(frozen=True)
class ReservationPreflight:
    """Immutable, hash-bound result of a read-only local budget preview."""

    status: str
    request_sha256: str
    ledger_logical_call_id: str
    task_arm_key: str
    call_kind: str
    input_upper_bound: int
    output_cap: int
    reserved_usd: float
    reservation_id: str
    ledger_state_sha256: str
    plan_sha256: str

    def __post_init__(self) -> None:
        if self.status != PREFLIGHT_PASSED:
            raise ValueError("reservation preflight status must be PREFLIGHT_PASSED")
        for name in (
            "request_sha256",
            "reservation_id",
            "ledger_state_sha256",
            "plan_sha256",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"reservation preflight {name} is not a sha256 digest")
        if (
            not self.ledger_logical_call_id
            or not self.task_arm_key
            or self.call_kind not in {"solve", "decompose", "extract"}
            or type(self.input_upper_bound) is not int
            or self.input_upper_bound <= 0
            or type(self.output_cap) is not int
            or self.output_cap <= 0
            or isinstance(self.reserved_usd, bool)
            or not isinstance(self.reserved_usd, (int, float))
            or self.reserved_usd < 0
        ):
            raise ValueError("reservation preflight fields are malformed")


class ModelPreflightFailure(RuntimeError):
    """Sanitized local rejection proven to occur before provider transmission."""

    def __init__(
        self,
        classification: str,
        *,
        details: Optional[Mapping[str, Any]] = None,
        request_sha256: Optional[str] = None,
        logical_call_id: Optional[str] = None,
    ) -> None:
        if classification in CELL_MODEL_PREFLIGHT_FAILURES:
            scope = "CELL"
        elif classification in GLOBAL_MODEL_PREFLIGHT_FAILURES:
            scope = "GLOBAL"
        else:
            raise ValueError("unknown model preflight failure classification")
        super().__init__(classification)
        self.classification = classification
        self.status = classification
        self.scope = scope
        self.details = dict(details or {})
        self.request_sha256 = request_sha256
        self.logical_call_id = logical_call_id

    @property
    def cell_scoped(self) -> bool:
        return self.scope == "CELL"


@dataclass(frozen=True)
class GatewayRequest:
    task_id: str
    arm: str
    step_no: int
    call_kind: str
    logical_call_id: str
    prompt: str
    max_output_tokens: int
    org_id: str = ""
    active_node_id: Optional[str] = None
    output_schema_name: Optional[str] = None
    output_json_schema: Optional[Mapping[str, Any]] = None
    output_schema_sha256: Optional[str] = None
    strict_structured_output: bool = False
    response_mode: str = STRUCTURED_TEXT
    function_tools: tuple[Mapping[str, Any], ...] = ()
    function_tools_sha256: Optional[str] = None
    tool_choice: Optional[Any] = None
    parallel_tool_calls: Optional[bool] = None
    prompt_projection: Optional[Mapping[str, Any]] = None

    def __post_init__(self) -> None:
        if self.response_mode not in {STRUCTURED_TEXT, SINGLE_FUNCTION_CALL}:
            raise ValueError("unknown response mode")
        structured = (
            self.output_schema_name,
            self.output_json_schema,
            self.output_schema_sha256,
        )
        if any(item is not None for item in structured) and not all(
            item is not None for item in structured
        ):
            raise ValueError("structured output contract fields must be supplied together")
        function_contract = (
            bool(self.function_tools),
            self.function_tools_sha256 is not None,
            self.tool_choice is not None,
            self.parallel_tool_calls is not None,
        )
        if self.response_mode == SINGLE_FUNCTION_CALL:
            if not all(function_contract):
                raise ValueError("single-function mode requires the complete function contract")
            if any(item is not None for item in structured) or self.strict_structured_output:
                raise ValueError("single-function mode cannot use structured text")
            if self.parallel_tool_calls is not False:
                raise ValueError("single-function mode forbids parallel tool calls")
        elif any(function_contract):
            raise ValueError("structured-text mode cannot carry function tools")
        if self.prompt_projection is not None:
            if not isinstance(self.prompt_projection, Mapping):
                raise ValueError("prompt_projection must be a mapping")
            if self.prompt_projection.get("final_prompt_sha256") != sha256_bytes(
                self.prompt.encode("utf-8")
            ):
                raise ValueError("prompt_projection final prompt hash differs")


def gateway_request_sha256(request: GatewayRequest) -> str:
    payload = asdict(request)
    # Preserve the exact pre-D1.9 identity for historical requests.  A bounded
    # D1.9 projection is hash-bound when present, while an absent optional field
    # must not silently rewrite old journal/evidence identities.
    if request.prompt_projection is None:
        payload.pop("prompt_projection")
    return sha256_bytes(canonical_bytes(payload))


@dataclass(frozen=True)
class GatewayResponse:
    text: str
    provider: str
    model: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    wall_time_ms: int
    paid: bool
    cached_input_tokens: Optional[int] = 0
    reasoning_tokens: Optional[int] = 0
    attempt: int = 1
    status: str = "success"
    provider_reported_usage_available: bool = True
    provider_response_envelope: Optional[Mapping[str, Any]] = None
    ledger_reservation: Optional[Mapping[str, Any]] = None
    terminal_outcome_replayed: bool = False
    response_mode: str = STRUCTURED_TEXT
    output_items: tuple[Mapping[str, Any], ...] = ()
    function_call_id: Optional[str] = None
    function_name: Optional[str] = None
    function_arguments: Optional[str] = None
    function_arguments_sha256: Optional[str] = None


class ModelGateway(Protocol):
    def invoke(self, request: GatewayRequest) -> GatewayResponse: ...


class GatewayInvocationFailure(RuntimeError):
    """Sanitized paid-provider failure with accounting metadata."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        status: str,
        attempt: int,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cached_input_tokens: Optional[int] = None,
        reasoning_tokens: Optional[int] = None,
        wall_time_ms: int = 0,
        response_text: str = "",
        provider_request_id: Optional[str] = None,
        response_id: Optional[str] = None,
        response_status: Optional[str] = None,
        response_error_code: Optional[str] = None,
        incomplete_reason: Optional[str] = None,
        output_item_types: tuple[str, ...] = (),
        content_item_types: tuple[str, ...] = (),
        refusal_present: bool = False,
        provider_reported_usage_available: Optional[bool] = None,
        raw_envelope_reference: Optional[str] = None,
        extracted_text_bytes: int = 0,
        structured_output_bytes: int = 0,
        original_provider_terminal_classification: Optional[str] = None,
        provider_response_envelope: Optional[Mapping[str, Any]] = None,
        ledger_reservation: Optional[Mapping[str, Any]] = None,
        terminal_outcome_replayed: bool = False,
    ):
        if provider_reported_usage_available is None:
            provider_reported_usage_available = all(
                type(value) is int
                for value in (
                    input_tokens,
                    output_tokens,
                    cached_input_tokens,
                    reasoning_tokens,
                )
            )
        raw_usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        invalid_usage = provider_reported_usage_available and (
            any(type(value) is not int or value < 0 for value in raw_usage.values())
            or (
                type(input_tokens) is int
                and type(cached_input_tokens) is int
                and cached_input_tokens > input_tokens
            )
            or (
                type(output_tokens) is int
                and type(reasoning_tokens) is int
                and reasoning_tokens > output_tokens
            )
        )
        if invalid_usage:
            status = "invalid_token_usage"
            input_tokens = output_tokens = cached_input_tokens = reasoning_tokens = None
            provider_reported_usage_available = False
        super().__init__("model gateway invocation failed: " + status)
        self.provider = provider
        self.model = model
        self.status = status
        self.attempt = max(1, int(attempt))
        self.input_tokens = input_tokens if provider_reported_usage_available else None
        self.output_tokens = output_tokens if provider_reported_usage_available else None
        self.cached_input_tokens = cached_input_tokens if provider_reported_usage_available else None
        self.reasoning_tokens = reasoning_tokens if provider_reported_usage_available else None
        self.wall_time_ms = max(0, int(wall_time_ms or 0))
        self.response_text = response_text if isinstance(response_text, str) else ""
        self.paid = True
        self.provider_request_id = provider_request_id
        self.response_id = response_id
        self.response_status = response_status
        self.response_error_code = response_error_code
        self.incomplete_reason = incomplete_reason
        self.output_item_types = tuple(output_item_types)
        self.content_item_types = tuple(content_item_types)
        self.refusal_present = bool(refusal_present)
        self.provider_reported_usage_available = bool(provider_reported_usage_available)
        self.raw_envelope_reference = raw_envelope_reference
        self.extracted_text_bytes = max(0, int(extracted_text_bytes))
        self.structured_output_bytes = max(0, int(structured_output_bytes))
        self.original_provider_terminal_classification = (
            original_provider_terminal_classification or status
        )
        self.provider_response_envelope = (
            dict(provider_response_envelope) if isinstance(provider_response_envelope, Mapping) else None
        )
        self.ledger_reservation = (
            dict(ledger_reservation) if isinstance(ledger_reservation, Mapping) else None
        )
        self.terminal_outcome_replayed = bool(terminal_outcome_replayed)


class ProviderCoroutineRunner(Protocol):
    def __call__(self, coroutine: Awaitable[Any]) -> Any: ...


class AsyncProviderModelGateway:
    """Bridge an async production provider into the common synchronous runtime.

    The benchmark arm session supplies one long-lived event-loop runner.  This
    class intentionally does not create a loop per call.
    """

    def __init__(self, provider: Any, runner: ProviderCoroutineRunner, *, expected_model: str):
        if not expected_model:
            raise ValueError("expected_model is required")
        self.provider = provider
        self.runner = runner
        self.expected_model = expected_model

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        if not request.org_id:
            raise ValueError("paid provider calls require an explicit org_id")
        from enterprise_memory.providers.base import ModelRequest

        model_request = ModelRequest(
            messages=[{"role": "user", "content": request.prompt}],
            max_output_tokens=request.max_output_tokens,
            temperature=0.0,
            top_p=1.0,
            output_schema_name=request.output_schema_name,
            output_json_schema=request.output_json_schema,
            output_schema_sha256=request.output_schema_sha256,
            strict_structured_output=request.strict_structured_output,
            response_mode=request.response_mode,
            function_tools=request.function_tools,
            function_tools_sha256=request.function_tools_sha256,
            tool_choice=request.tool_choice,
            parallel_tool_calls=request.parallel_tool_calls,
        )
        try:
            response, record = self.runner(
                self.provider.generate(
                    model_request,
                    logical_request_id=request.logical_call_id,
                    org_id=request.org_id,
                )
            )
        except Exception as exc:
            record = getattr(exc, "record", None)
            if record is None:
                raise
            envelope = getattr(record, "response_envelope", None)
            public_envelope = envelope.to_public_dict() if envelope is not None else None
            usage_available = (
                envelope.provider_reported_usage_available
                if envelope is not None
                else all(
                    type(value) is int
                    for value in (
                        getattr(record, "input_tokens", None),
                        getattr(record, "output_tokens", None),
                        getattr(record, "cached_input_tokens", 0),
                        getattr(record, "reasoning_tokens", 0),
                    )
                )
            )
            raise GatewayInvocationFailure(
                provider="openai-responses",
                model=self.expected_model,
                status=str(getattr(record, "final_status", "provider_failure")),
                attempt=max(1, int(getattr(record, "attempts", 1))),
                input_tokens=getattr(record, "input_tokens", None),
                output_tokens=getattr(record, "output_tokens", None),
                cached_input_tokens=getattr(record, "cached_input_tokens", 0),
                reasoning_tokens=getattr(record, "reasoning_tokens", 0),
                wall_time_ms=max(0, int(round(float(getattr(record, "total_latency", 0.0) or 0.0) * 1000))),
                provider_request_id=getattr(record, "provider_request_id", None),
                response_id=getattr(envelope, "response_id", None),
                response_status=getattr(envelope, "response_status", None),
                response_error_code=getattr(envelope, "response_error_code", None),
                incomplete_reason=getattr(envelope, "incomplete_reason", None),
                output_item_types=getattr(envelope, "output_item_types", ()),
                content_item_types=getattr(envelope, "content_item_types", ()),
                refusal_present=bool(getattr(envelope, "refusal_present", False)),
                provider_reported_usage_available=usage_available,
                raw_envelope_reference=getattr(envelope, "raw_restricted_evidence_reference", None),
                extracted_text_bytes=getattr(envelope, "extracted_text_bytes", 0),
                structured_output_bytes=getattr(envelope, "structured_output_bytes", 0),
                original_provider_terminal_classification=getattr(
                    envelope, "terminal_classification", getattr(record, "final_status", None)
                ),
                provider_response_envelope=public_envelope,
            ) from None
        returned = response.returned_model or record.returned_model
        envelope = response.envelope
        cached_input_tokens = getattr(
            record, "cached_input_tokens", None if envelope is not None else 0
        )
        reasoning_tokens = getattr(
            record, "reasoning_tokens", None if envelope is not None else 0
        )
        usage_available = (
            envelope.provider_reported_usage_available
            if envelope is not None
            else all(
                type(value) is int
                for value in (
                    response.input_tokens,
                    response.output_tokens,
                    cached_input_tokens,
                    reasoning_tokens,
                )
            )
        )
        if returned != self.expected_model:
            raise GatewayInvocationFailure(
                provider="openai-responses",
                model=str(returned or self.expected_model),
                status="returned_model_mismatch",
                attempt=max(1, int(record.attempts)),
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cached_input_tokens=cached_input_tokens,
                reasoning_tokens=reasoning_tokens,
                wall_time_ms=max(0, int(round(float(record.total_latency or 0.0) * 1000))),
                response_text=response.text,
                provider_reported_usage_available=usage_available,
                provider_response_envelope=(
                    response.envelope.to_public_dict() if response.envelope is not None else None
                ),
            )
        usage = {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        if (
            usage_available
            and (
                any(type(value) is not int or value < 0 for value in usage.values())
            or (
                type(usage["cached_input_tokens"]) is int
                and type(usage["input_tokens"]) is int
                and usage["cached_input_tokens"] > usage["input_tokens"]
            )
            or (
                type(usage["reasoning_tokens"]) is int
                and type(usage["output_tokens"]) is int
                and usage["reasoning_tokens"] > usage["output_tokens"]
            )
            )
        ):
            raise GatewayInvocationFailure(
                provider="openai-responses",
                model=str(returned),
                status="invalid_token_usage",
                attempt=max(1, int(record.attempts)),
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cached_input_tokens=cached_input_tokens,
                reasoning_tokens=reasoning_tokens,
                wall_time_ms=max(0, int(round(float(record.total_latency or 0.0) * 1000))),
                response_text=response.text,
                provider_reported_usage_available=usage_available,
                provider_response_envelope=(
                    response.envelope.to_public_dict() if response.envelope is not None else None
                ),
            )
        return GatewayResponse(
            text=response.text,
            provider="openai-responses",
            model=returned,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            reasoning_tokens=usage["reasoning_tokens"],
            wall_time_ms=max(0, int(round(float(record.total_latency or 0.0) * 1000))),
            paid=True,
            attempt=max(1, int(record.attempts)),
            status=str(record.final_status),
            provider_reported_usage_available=usage_available,
            provider_response_envelope=(
                response.envelope.to_public_dict() if response.envelope is not None else None
            ),
            response_mode=response.response_mode,
            output_items=tuple(
                item.to_public_dict() for item in response.output_items
            ),
            function_call_id=response.function_call_id,
            function_name=response.function_name,
            function_arguments=response.function_arguments,
            function_arguments_sha256=response.function_arguments_sha256,
        )


class ReplayModelGateway:
    """Deterministic fixture gateway; it performs no network or paid model call."""

    def __init__(self, responses: Mapping[str, str] | Callable[[GatewayRequest], str], *, model="trimem-replay-v1"):
        self._responses = responses
        self.model = model
        self.invocations: list[str] = []

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        start = time.perf_counter_ns()
        if callable(self._responses):
            text = self._responses(request)
        else:
            if request.logical_call_id not in self._responses:
                raise KeyError(f"no replay response for {request.logical_call_id}")
            text = self._responses[request.logical_call_id]
        self.invocations.append(request.logical_call_id)
        elapsed = max(0, (time.perf_counter_ns() - start) // 1_000_000)
        if request.response_mode == SINGLE_FUNCTION_CALL:
            value = strict_json_object(text)
            if set(value) != {"tool", "arguments"}:
                raise ValueError("credential-free function replay requires legacy tool/arguments fixture")
            value["arguments"] = _complete_legacy_nullable_arguments(
                str(value["tool"]), value["arguments"]
            )
            function_arguments = json.dumps(
                value["arguments"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            return GatewayResponse(
                text="",
                provider="credential-free-replay",
                model=self.model,
                input_tokens=_deterministic_tokens(request.prompt),
                output_tokens=_deterministic_tokens(text),
                wall_time_ms=elapsed,
                paid=False,
                response_mode=SINGLE_FUNCTION_CALL,
                function_call_id="replay-" + sha256_bytes(request.logical_call_id.encode())[:24],
                function_name=value["tool"],
                function_arguments=function_arguments,
                function_arguments_sha256=sha256_bytes(function_arguments.encode("utf-8")),
            )
        return GatewayResponse(
            text=text,
            provider="credential-free-replay",
            model=self.model,
            input_tokens=_deterministic_tokens(request.prompt),
            output_tokens=_deterministic_tokens(text),
            wall_time_ms=elapsed,
            paid=False,
        )


class RecordingModelGateway:
    """Persists the full prompt/response and exact accounting around any gateway."""

    def __init__(self, delegate: ModelGateway, accounting: RunAccounting, evidence: RawEvidenceLedger):
        self.delegate = delegate
        self.accounting = accounting
        self.evidence = evidence

    def _recorded_events(
        self, request: GatewayRequest, request_sha256: str
    ) -> tuple[Optional[Mapping[str, Any]], Optional[Mapping[str, Any]]]:
        request_event: Optional[Mapping[str, Any]] = None
        terminal_event: Optional[Mapping[str, Any]] = None
        for event in self.evidence.verified_suffix("0" * 64):
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if payload.get("logical_call_id") != request.logical_call_id:
                continue
            event_type = event.get("event_type")
            if event_type not in {"model_request", "model_response", "model_failure"}:
                continue
            if payload.get("request_sha256") != request_sha256:
                raise RuntimeError("recorded model request identity mismatch")
            if event_type == "model_request":
                if request_event is not None:
                    raise RuntimeError("duplicate recorded model request")
                request_event = event
            else:
                if terminal_event is not None:
                    raise RuntimeError("duplicate recorded model terminal outcome")
                terminal_event = event
        if terminal_event is not None and request_event is None:
            raise RuntimeError("model terminal outcome has no recorded request")
        return request_event, terminal_event

    @staticmethod
    def _prompt_reference(
        request_event: Mapping[str, Any], request: GatewayRequest
    ) -> Mapping[str, Any]:
        payload = request_event.get("payload")
        prompt = payload.get("prompt") if isinstance(payload, Mapping) else None
        if (
            not isinstance(prompt, Mapping)
            or prompt.get("sha256") != sha256_bytes(request.prompt.encode("utf-8"))
            or prompt.get("bytes") != len(request.prompt.encode("utf-8"))
        ):
            raise RuntimeError("recorded model prompt identity mismatch")
        return prompt

    def invoke(
        self,
        request: GatewayRequest,
        *,
        request_already_recorded: bool = False,
        required_request_lifecycle_state: Optional[str] = None,
    ) -> GatewayResponse:
        request_sha256 = gateway_request_sha256(request)
        request_event, terminal_event = self._recorded_events(request, request_sha256)
        if request_already_recorded and request_event is None:
            raise RuntimeError("request_already_recorded has no matching evidence event")
        if request_already_recorded and required_request_lifecycle_state is None:
            raise RuntimeError(
                "recorded-request recovery requires an explicit lifecycle state"
            )
        if required_request_lifecycle_state is not None and not request_already_recorded:
            raise RuntimeError(
                "request lifecycle recovery requires a recorded request event"
            )
        lifecycle_states = {
            "NOT_PREPARED", "NOT_STARTED", "REQUEST_RECORDED",
            "PROVIDER_SEND_STARTED", "PROVIDER_TERMINAL_SUCCESS",
            "PROVIDER_TERMINAL_FAILURE", "PROVIDER_OUTCOME_UNKNOWN",
        }
        if (
            required_request_lifecycle_state is not None
            and required_request_lifecycle_state not in lifecycle_states
        ):
            raise RuntimeError("unknown required request lifecycle state")
        replay = getattr(self.delegate, "replay_terminal", None)
        replayed_response: Optional[GatewayResponse] = None
        replayed_failure: Optional[GatewayInvocationFailure] = None
        if callable(replay):
            replayed: Optional[GatewayResponse] = None
            try:
                replayed = replay(request)
            except GatewayInvocationFailure as failure:
                if not failure.terminal_outcome_replayed:
                    raise
                if terminal_event is not None:
                    self.evidence.append("model_terminal_outcome_replayed", {
                        "logical_call_id": request.logical_call_id,
                        "request_sha256": request_sha256,
                        "attempt": failure.attempt,
                        "terminal_event_type": "model_failure",
                        "status": failure.status,
                        "counted_as_model_call": False,
                    })
                    raise
                replayed_failure = failure
            if replayed is not None:
                if not replayed.terminal_outcome_replayed:
                    raise RuntimeError("journal replay did not mark its terminal outcome")
                if terminal_event is not None:
                    self.evidence.append("model_terminal_outcome_replayed", {
                        "logical_call_id": request.logical_call_id,
                        "request_sha256": request_sha256,
                        "attempt": replayed.attempt,
                        "terminal_event_type": "model_response",
                        "status": replayed.status,
                        "counted_as_model_call": False,
                    })
                    return replayed
                replayed_response = replayed

        # A lifecycle snapshot is the authorization boundary for resuming a
        # durable request-only suffix.  Never interpret a broken/partial
        # replay implementation as permission to send.  In particular, a
        # provider-started request must settle/replay a terminal outcome; a
        # None result is a global integrity failure, not a retry signal.
        if required_request_lifecycle_state is not None:
            expected = required_request_lifecycle_state
            if expected in {"NOT_PREPARED", "NOT_STARTED", "REQUEST_RECORDED"}:
                if replayed_response is not None or replayed_failure is not None:
                    raise RuntimeError(
                        "request lifecycle changed after its recovery snapshot"
                    )
            elif expected == "PROVIDER_TERMINAL_SUCCESS":
                if replayed_response is None or replayed_failure is not None:
                    raise RuntimeError(
                        "terminal-success lifecycle did not replay exact success"
                    )
            elif expected == "PROVIDER_TERMINAL_FAILURE":
                if replayed_failure is None or replayed_response is not None:
                    raise RuntimeError(
                        "terminal-failure lifecycle did not replay exact failure"
                    )
            else:
                if (
                    replayed_failure is None
                    or replayed_response is not None
                    or replayed_failure.status
                    != "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN"
                ):
                    raise RuntimeError(
                        "provider-started lifecycle did not settle unknown outcome"
                    )

        preflight: Optional[ReservationPreflight] = None
        if replayed_response is None and replayed_failure is None:
            preview = getattr(self.delegate, "preview_reservation", None)
            if callable(preview):
                try:
                    preflight = preview(request)
                except ModelPreflightFailure as failure:
                    if failure.request_sha256 not in {None, request_sha256}:
                        raise RuntimeError("preflight failure request identity mismatch") from None
                    self.evidence.append(
                        "model_preflight_failure",
                        {
                            "task_id": request.task_id,
                            "arm": request.arm,
                            "step_no": request.step_no,
                            "call_kind": request.call_kind,
                            "logical_call_id": request.logical_call_id,
                            "request_sha256": request_sha256,
                            "prompt_sha256": sha256_bytes(request.prompt.encode("utf-8")),
                            "prompt_bytes": len(request.prompt.encode("utf-8")),
                            "prompt_projection": (
                                dict(request.prompt_projection)
                                if request.prompt_projection is not None
                                else None
                            ),
                            "classification": failure.classification,
                            "scope": failure.scope,
                            "details": failure.details,
                            "model_calls": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_usd": 0,
                        },
                    )
                    raise
                if preflight is not None and (
                    not isinstance(preflight, ReservationPreflight)
                    or preflight.request_sha256 != request_sha256
                    or preflight.status != PREFLIGHT_PASSED
                ):
                    raise RuntimeError("model reservation preflight contract differs")

        if request_event is not None:
            prompt_ref = self._prompt_reference(request_event, request)
        else:
            if replayed_response is not None or replayed_failure is not None:
                raise RuntimeError("journal terminal outcome has no recorded model request")
            prompt_ref = self.evidence.put_blob(request.prompt)
            self.evidence.append(
                "model_request",
                {
                    "task_id": request.task_id,
                    "arm": request.arm,
                    "step_no": request.step_no,
                    "call_kind": request.call_kind,
                    "logical_call_id": request.logical_call_id,
                    "request_sha256": request_sha256,
                    "active_node_id": request.active_node_id,
                    "org_id": request.org_id,
                    "prompt": prompt_ref,
                    "prompt_projection": (
                        dict(request.prompt_projection)
                        if request.prompt_projection is not None
                        else None
                    ),
                    "max_output_tokens": request.max_output_tokens,
                    "output_schema_name": request.output_schema_name,
                    "output_schema_sha256": request.output_schema_sha256,
                    "strict_structured_output": request.strict_structured_output,
                    "response_mode": request.response_mode,
                    "function_tools_sha256": request.function_tools_sha256,
                    "tool_choice": request.tool_choice,
                    "parallel_tool_calls": request.parallel_tool_calls,
                },
            )
        try:
            if replayed_failure is not None:
                raise replayed_failure
            if replayed_response is not None:
                response = replayed_response
            else:
                invoke_preflighted = getattr(self.delegate, "invoke_preflighted", None)
                if callable(invoke_preflighted):
                    response = invoke_preflighted(request, preflight)
                else:
                    response = self.delegate.invoke(request)
        except GatewayInvocationFailure as failure:
            response_ref = self.evidence.put_blob(failure.response_text)
            record = CallRecord(
                task_id=request.task_id,
                arm=request.arm,
                step_no=request.step_no,
                call_kind=request.call_kind,
                logical_call_id=request.logical_call_id,
                provider=failure.provider,
                model=failure.model,
                input_tokens=failure.input_tokens,
                output_tokens=failure.output_tokens,
                cached_input_tokens=failure.cached_input_tokens,
                reasoning_tokens=failure.reasoning_tokens,
                wall_time_ms=failure.wall_time_ms,
                prompt_hash=prompt_ref["sha256"],
                response_hash=response_ref["sha256"],
                active_node_id=request.active_node_id,
                paid=failure.paid,
                attempt=failure.attempt,
                status=failure.status,
                provider_reported_usage_available=failure.provider_reported_usage_available,
                provider_response_envelope=failure.provider_response_envelope,
                ledger_reservation=failure.ledger_reservation,
            )
            self.accounting.add_call(record)
            failure_payload = {
                    "logical_call_id": request.logical_call_id,
                    "request_sha256": request_sha256,
                    "provider": failure.provider,
                    "model": failure.model,
                    "paid": failure.paid,
                    "attempt": failure.attempt,
                    "input_tokens": failure.input_tokens,
                    "output_tokens": failure.output_tokens,
                    "cached_input_tokens": failure.cached_input_tokens,
                    "reasoning_tokens": failure.reasoning_tokens,
                    "wall_time_ms": failure.wall_time_ms,
                    "status": failure.status,
                    "response": response_ref,
                    "provider_reported_usage_available": failure.provider_reported_usage_available,
                    "provider_response_envelope": failure.provider_response_envelope,
                    "ledger_reservation": failure.ledger_reservation,
                    "original_provider_terminal_classification": (
                        failure.original_provider_terminal_classification
                    ),
                    "provider_request_id": failure.provider_request_id,
                    "response_id": failure.response_id,
                    "response_status": failure.response_status,
                    "response_error_code": failure.response_error_code,
                    "incomplete_reason": failure.incomplete_reason,
                    "output_item_types": list(failure.output_item_types),
                    "content_item_types": list(failure.content_item_types),
                    "refusal_present": failure.refusal_present,
                    "raw_envelope_reference": failure.raw_envelope_reference,
                    "extracted_text_bytes": failure.extracted_text_bytes,
                    "structured_output_bytes": failure.structured_output_bytes,
                }
            if (
                request.response_mode == SINGLE_FUNCTION_CALL
                and failure.status in ACTION_CONTRACT_FAILURE_STATUSES
            ):
                self.evidence.append(
                    "model_response",
                    {
                        **failure_payload,
                        "response_mode": SINGLE_FUNCTION_CALL,
                        "output_items": list(
                            (failure.provider_response_envelope or {}).get("output_items", ())
                        ),
                        "function_call_id": None,
                        "function_name": _failure_function_name(failure),
                        "function_arguments": None,
                        "function_arguments_sha256": _failure_argument_hash(failure),
                    },
                )
                self.evidence.append(
                    "action_contract_failure",
                    {
                        "task_id": request.task_id,
                        "arm": request.arm,
                        "step_no": request.step_no,
                        "active_node_id": request.active_node_id,
                        "logical_call_id": request.logical_call_id,
                        "request_sha256": request_sha256,
                        "provider_response_id": failure.response_id,
                        "failure_class": failure.status,
                        "function_name": _failure_function_name(failure),
                        "argument_sha256": _failure_argument_hash(failure),
                        "ledger_reservation": failure.ledger_reservation,
                    },
                )
            else:
                self.evidence.append("model_failure", failure_payload)
            raise
        if (
            request.response_mode == SINGLE_FUNCTION_CALL
            and response.response_mode == STRUCTURED_TEXT
            and not response.paid
        ):
            response = _adapt_credential_free_legacy_response(
                request, response
            )
        response_ref = self.evidence.put_blob(response.text)
        function_arguments_ref = (
            self.evidence.put_blob(response.function_arguments)
            if response.function_arguments is not None
            else None
        )
        record = CallRecord(
            task_id=request.task_id,
            arm=request.arm,
            step_no=request.step_no,
            call_kind=request.call_kind,
            logical_call_id=request.logical_call_id,
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_input_tokens=response.cached_input_tokens,
            reasoning_tokens=response.reasoning_tokens,
            wall_time_ms=response.wall_time_ms,
            prompt_hash=prompt_ref["sha256"],
            response_hash=(
                response.function_arguments_sha256
                if response.response_mode == SINGLE_FUNCTION_CALL
                else response_ref["sha256"]
            ),
            active_node_id=request.active_node_id,
            paid=response.paid,
            attempt=response.attempt,
            status=response.status,
            provider_reported_usage_available=response.provider_reported_usage_available,
            provider_response_envelope=response.provider_response_envelope,
            ledger_reservation=response.ledger_reservation,
        )
        self.accounting.add_call(record)
        self.evidence.append(
            "model_response",
            {
                "logical_call_id": request.logical_call_id,
                "request_sha256": request_sha256,
                "response": response_ref,
                "provider": response.provider,
                "model": response.model,
                "paid": response.paid,
                "attempt": response.attempt,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cached_input_tokens": response.cached_input_tokens,
                "reasoning_tokens": response.reasoning_tokens,
                "wall_time_ms": response.wall_time_ms,
                "status": response.status,
                "provider_reported_usage_available": response.provider_reported_usage_available,
                "provider_response_envelope": response.provider_response_envelope,
                "ledger_reservation": response.ledger_reservation,
                "response_mode": response.response_mode,
                "output_items": [dict(item) for item in response.output_items],
                "function_call_id": (
                    self.evidence.put_blob(response.function_call_id)
                    if response.function_call_id is not None
                    else None
                ),
                "function_name": response.function_name,
                "function_arguments": function_arguments_ref,
                "function_arguments_sha256": response.function_arguments_sha256,
            },
        )
        return response


def _failure_function_name(failure: GatewayInvocationFailure) -> Optional[str]:
    envelope = failure.provider_response_envelope or {}
    for item in envelope.get("output_items", ()):
        if isinstance(item, Mapping) and item.get("item_type") == "function_call":
            name = item.get("function_name")
            return name if isinstance(name, str) else None
    return None


def _failure_argument_hash(failure: GatewayInvocationFailure) -> Optional[str]:
    envelope = failure.provider_response_envelope or {}
    for item in envelope.get("output_items", ()):
        if isinstance(item, Mapping) and item.get("item_type") == "function_call":
            digest = item.get("arguments_sha256")
            return digest if isinstance(digest, str) else None
    return None


def parse_function_action(
    response: GatewayResponse,
    tool_names: set[str],
) -> tuple[str, dict[str, Any]]:
    """Validate the native action envelope without altering its arguments."""

    if response.response_mode != SINGLE_FUNCTION_CALL:
        raise ValueError("SOLVE_EXPECTED_FUNCTION_CALL")
    if not response.function_call_id:
        raise ValueError("SOLVE_FUNCTION_CALL_ID_MISSING")
    if response.function_name not in tool_names:
        raise ValueError("SOLVE_UNKNOWN_FUNCTION")
    if not isinstance(response.function_arguments, str):
        raise ValueError("SOLVE_FUNCTION_ARGUMENT_INVALID_JSON")
    raw = response.function_arguments.encode("utf-8")
    if sha256_bytes(raw) != response.function_arguments_sha256:
        raise ValueError("SOLVE_FUNCTION_ARGUMENT_INVALID_JSON")
    try:
        arguments = strict_json_object(response.function_arguments)
    except ValueError as exc:
        raise ValueError("SOLVE_FUNCTION_ARGUMENT_INVALID_JSON") from exc
    try:
        validate_function_arguments(response.function_name, arguments)
    except ValueError as exc:
        raise ValueError("SOLVE_FUNCTION_ARGUMENT_SCHEMA_FAILURE") from exc
    return response.function_name, arguments


def _complete_legacy_nullable_arguments(
    name: str,
    value: Any,
    *,
    allow_pre_d19_unpaginated_list_files: bool = False,
) -> Any:
    """Adapt immutable pre-D1.6 text fixtures, never live provider output."""

    if not isinstance(value, dict):
        return value
    result = dict(value)
    nullable = {
        "read_file": ("start_line", "max_lines"),
        "search": ("path",),
        "run_command": ("cwd", "timeout_seconds"),
    }
    for field in nullable.get(name, ()):
        result.setdefault(field, None)
    if (
        name == "list_files"
        and not result
        and allow_pre_d19_unpaginated_list_files
    ):
        # Immutable pre-D1.9 fixtures used `{}`.  Live provider output still
        # traverses the strict native schema and cannot use this adapter.
        result.update({
            "path_prefix": None,
            "start_after": None,
            "limit": 100,
        })
    if name == "revise_subtask_dag":
        rows = []
        for original in result.get("new_subtasks", ()):
            row = dict(original) if isinstance(original, Mapping) else original
            if isinstance(row, dict):
                for field in (
                    "preconditions", "invariants", "files", "symbols", "apis",
                    "errors", "tests", "required_memory_facets",
                ):
                    row.setdefault(field, None)
            rows.append(row)
        result["new_subtasks"] = rows
    return result


def _adapt_credential_free_legacy_response(
    request: GatewayRequest, response: GatewayResponse
) -> GatewayResponse:
    """Keep old fake/replay fixtures usable without weakening the paid path."""

    value = strict_json_object(response.text)
    if set(value) != {"tool", "arguments"}:
        raise ValueError("credential-free function replay requires tool/arguments")
    actual_function_tools_sha256 = sha256_bytes(
        canonical_bytes(request.function_tools)
    )
    explicit_pre_d19_replay = (
        request.function_tools_sha256
        == PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256
        and actual_function_tools_sha256
        == PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256
    )
    arguments = _complete_legacy_nullable_arguments(
        str(value["tool"]),
        value["arguments"],
        allow_pre_d19_unpaginated_list_files=explicit_pre_d19_replay,
    )
    raw = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return replace(
        response,
        text="",
        response_mode=SINGLE_FUNCTION_CALL,
        function_call_id="replay-" + sha256_bytes(
            request.logical_call_id.encode("utf-8")
        )[:24],
        function_name=str(value["tool"]),
        function_arguments=raw,
        function_arguments_sha256=sha256_bytes(raw.encode("utf-8")),
    )


def strict_json_object(raw: str) -> dict:
    """Parse one JSON object and reject duplicate keys and non-object roots."""

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError(f"duplicate JSON key: {key}")
            out[key] = value
        return out

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid strict JSON: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON response must be an object")
    return value


def parse_tool_action(raw: str, tool_names: set[str]) -> tuple[str, dict]:
    value = strict_json_object(raw)
    if set(value) != {"tool", "arguments"}:
        raise ValueError("tool response must contain exactly tool and arguments")
    if value["tool"] not in tool_names:
        raise ValueError("unknown tool")
    if not isinstance(value["arguments"], dict):
        raise ValueError("tool arguments must be an object")
    return value["tool"], value["arguments"]


def _deterministic_tokens(text: str) -> int:
    # Credential-free runs do not claim provider tokenizer parity.  The manifest
    # labels this whitespace counter explicitly and paid gateways must report their
    # provider usage instead.
    return max(1, len((text or "").split()))


def _usage_or_zero(value: object) -> int:
    return value if type(value) is int and value >= 0 else 0
