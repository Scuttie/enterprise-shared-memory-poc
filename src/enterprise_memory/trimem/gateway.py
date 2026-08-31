"""Model gateway boundary shared by paid providers and credential-free replay."""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Awaitable, Callable, Mapping, Optional, Protocol

from .accounting import CallRecord, RawEvidenceLedger, RunAccounting, sha256_bytes


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


@dataclass(frozen=True)
class GatewayResponse:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    wall_time_ms: int
    paid: bool
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    attempt: int = 1
    status: str = "success"


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
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        reasoning_tokens: int = 0,
        wall_time_ms: int = 0,
        response_text: str = "",
    ):
        raw_usage = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        invalid_usage = (
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
            input_tokens = output_tokens = cached_input_tokens = reasoning_tokens = 0
        super().__init__("model gateway invocation failed: " + status)
        self.provider = provider
        self.model = model
        self.status = status
        self.attempt = max(1, int(attempt))
        self.input_tokens = max(0, int(input_tokens or 0))
        self.output_tokens = max(0, int(output_tokens or 0))
        self.cached_input_tokens = max(0, int(cached_input_tokens or 0))
        self.reasoning_tokens = max(0, int(reasoning_tokens or 0))
        self.wall_time_ms = max(0, int(wall_time_ms or 0))
        self.response_text = response_text if isinstance(response_text, str) else ""
        self.paid = True


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
            raise GatewayInvocationFailure(
                provider="openai-responses",
                model=self.expected_model,
                status=str(getattr(record, "final_status", "provider_failure")),
                attempt=max(1, int(getattr(record, "attempts", 1))),
                input_tokens=getattr(record, "input_tokens", 0) or 0,
                output_tokens=getattr(record, "output_tokens", 0) or 0,
                cached_input_tokens=getattr(record, "cached_input_tokens", 0) or 0,
                reasoning_tokens=getattr(record, "reasoning_tokens", 0) or 0,
                wall_time_ms=max(0, int(round(float(getattr(record, "total_latency", 0.0) or 0.0) * 1000))),
            ) from None
        returned = response.returned_model or record.returned_model
        if returned != self.expected_model:
            raise GatewayInvocationFailure(
                provider="openai-responses",
                model=str(returned or self.expected_model),
                status="returned_model_mismatch",
                attempt=max(1, int(record.attempts)),
                input_tokens=_usage_or_zero(response.input_tokens),
                output_tokens=_usage_or_zero(response.output_tokens),
                cached_input_tokens=_usage_or_zero(getattr(record, "cached_input_tokens", 0)),
                reasoning_tokens=_usage_or_zero(getattr(record, "reasoning_tokens", 0)),
                wall_time_ms=max(0, int(round(float(record.total_latency or 0.0) * 1000))),
                response_text=response.text,
            )
        usage = {
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cached_input_tokens": getattr(record, "cached_input_tokens", 0) or 0,
            "reasoning_tokens": getattr(record, "reasoning_tokens", 0) or 0,
        }
        if (
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
        ):
            raise GatewayInvocationFailure(
                provider="openai-responses",
                model=str(returned),
                status="invalid_token_usage",
                attempt=max(1, int(record.attempts)),
                input_tokens=_usage_or_zero(response.input_tokens),
                output_tokens=_usage_or_zero(response.output_tokens),
                cached_input_tokens=_usage_or_zero(getattr(record, "cached_input_tokens", 0)),
                reasoning_tokens=_usage_or_zero(getattr(record, "reasoning_tokens", 0)),
                wall_time_ms=max(0, int(round(float(record.total_latency or 0.0) * 1000))),
                response_text=response.text,
            )
        if not isinstance(response.text, str) or not response.text:
            raise GatewayInvocationFailure(
                provider="openai-responses",
                model=str(returned),
                status="empty_response",
                attempt=max(1, int(record.attempts)),
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                cached_input_tokens=usage["cached_input_tokens"],
                reasoning_tokens=usage["reasoning_tokens"],
                wall_time_ms=max(0, int(round(float(record.total_latency or 0.0) * 1000))),
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
        prompt_ref = self.evidence.put_blob(request.prompt)
        self.evidence.append(
            "model_request",
            {
                "task_id": request.task_id,
                "arm": request.arm,
                "step_no": request.step_no,
                "call_kind": request.call_kind,
                "logical_call_id": request.logical_call_id,
                "active_node_id": request.active_node_id,
                "org_id": request.org_id,
                "prompt": prompt_ref,
                "max_output_tokens": request.max_output_tokens,
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
            )
            self.accounting.add_call(record)
            self.evidence.append(
                "model_failure",
                {
                    "logical_call_id": request.logical_call_id,
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
        )
        self.accounting.add_call(record)
        self.evidence.append(
            "model_response",
            {
                "logical_call_id": request.logical_call_id,
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
