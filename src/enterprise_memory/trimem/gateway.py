"""Model gateway boundary shared by paid providers and credential-free replay."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import time
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from .accounting import CallRecord, RawEvidenceLedger, RunAccounting, canonical_bytes, sha256_bytes


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

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        request_sha256 = sha256_bytes(canonical_bytes(asdict(request)))
        replay = getattr(self.delegate, "replay_terminal", None)
        if callable(replay):
            try:
                replayed = replay(request)
            except GatewayInvocationFailure as failure:
                if not failure.terminal_outcome_replayed:
                    raise
                self.evidence.append("model_terminal_outcome_replayed", {
                    "logical_call_id": request.logical_call_id,
                    "request_sha256": request_sha256,
                    "attempt": failure.attempt,
                    "terminal_event_type": "model_failure",
                    "status": failure.status,
                    "counted_as_model_call": False,
                })
                raise
            if replayed is not None:
                if not replayed.terminal_outcome_replayed:
                    raise RuntimeError("journal replay did not mark its terminal outcome")
                self.evidence.append("model_terminal_outcome_replayed", {
                    "logical_call_id": request.logical_call_id,
                    "request_sha256": request_sha256,
                    "attempt": replayed.attempt,
                    "terminal_event_type": "model_response",
                    "status": replayed.status,
                    "counted_as_model_call": False,
                })
                return replayed
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
                    "max_output_tokens": request.max_output_tokens,
                    "output_schema_name": request.output_schema_name,
                    "output_schema_sha256": request.output_schema_sha256,
                    "strict_structured_output": request.strict_structured_output,
                },
        )
        try:
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
            self.evidence.append(
                "model_failure",
                {
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
                },
            )
            raise
        response_ref = self.evidence.put_blob(response.text)
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
            response_hash=response_ref["sha256"],
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
            },
        )
        return response


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
