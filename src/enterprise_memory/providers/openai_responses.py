"""OpenAI Responses API provider with fail-closed outcome observability."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable, Mapping, Optional

from .base import (
    AttemptRecord,
    AuthError,
    CodingModelProvider,
    InvalidRequestError,
    ModelCallRecord,
    ModelRequest,
    ModelResponse,
    ParserError,
    PolicyRejection,
    ProviderError,
    ProviderResponseEnvelope,
)
from .redaction import sanitize


_REASONING_FAMILIES = {
    "gpt5", "gpt-5", "gpt5.4", "gpt-5.4", "gpt5.6", "gpt-5.6", "reasoning"
}
_NONREASONING_FAMILIES = {"gpt4o", "gpt-4o", "nonreasoning"}
_ENVELOPE_SCHEMA = "trimem/provider-response-envelope/1.0"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value

    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("provider response root is not an object")
    return value


def _optional_nonnegative_int(value: Any) -> Optional[int]:
    return value if type(value) is int and value >= 0 else None


class RestrictedProviderResponseStore:
    """Content-addressed store intended for the encrypted restricted bundle."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def __call__(self, raw: bytes, logical_request_id: str) -> str:
        if not isinstance(raw, bytes) or not logical_request_id:
            raise ValueError("raw provider response and logical request ID are required")
        digest = hashlib.sha256(raw).hexdigest()
        target = self.root / digest
        if target.exists():
            if target.read_bytes() != raw:
                raise RuntimeError("provider-response content-address collision")
        else:
            fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=str(self.root))
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return "restricted-provider-response://sha256/" + digest


class OpenAIResponsesProvider(CodingModelProvider):
    def __init__(
        self,
        base_url,
        model,
        secret_provider,
        *,
        family,
        key_name="OPENAI_API_KEY",
        reasoning_effort="medium",
        timeout=180.0,
        max_retries=6,
        http_client=None,
        raw_response_recorder: Optional[Callable[[bytes, str], str]] = None,
    ):
        self._base = base_url.rstrip("/")
        self._model = model
        self._secrets = secret_provider
        self._key_name = key_name
        fam = str(family).lower()
        if fam in _REASONING_FAMILIES:
            self._reasoning = True
        elif fam in _NONREASONING_FAMILIES:
            self._reasoning = False
        else:
            raise ValueError("unknown model family %r (expected gpt5 reasoning or gpt4o)" % family)
        self._effort = reasoning_effort
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = http_client
        self._raw_response_recorder = raw_response_recorder

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "input": [{"role": "user", "content": request.messages[-1]["content"]}],
            "max_output_tokens": request.max_output_tokens,
        }
        if request.output_json_schema is not None:
            digest = hashlib.sha256(_canonical_bytes(request.output_json_schema)).hexdigest()
            if digest != request.output_schema_sha256:
                raise InvalidRequestError("structured output schema hash mismatch")
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.output_schema_name,
                    "strict": request.strict_structured_output,
                    "schema": json.loads(_canonical_bytes(request.output_json_schema)),
                }
            }
        if self._reasoning:
            body["reasoning"] = {"effort": self._effort}
        else:
            body["temperature"] = 0.0
        return body

    def _headers(self):
        key = self._secrets.get(self._key_name)
        if not key:
            raise AuthError("missing %s" % self._key_name)
        return {"Authorization": "Bearer %s" % key, "Content-Type": "application/json"}

    async def _post(self, body):
        assert self._client is not None, "no http client bound"
        return await self._client.post(
            self._base + "/responses",
            json=body,
            headers=self._headers(),
            timeout=self._timeout,
        )

    @staticmethod
    def _extract_observations(data: Mapping[str, Any]) -> dict[str, Any]:
        output_types: list[str] = []
        content_types: list[str] = []
        text_parts: list[str] = []
        refusals: list[str] = []
        output = data.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, Mapping):
                    continue
                item_type = item.get("type")
                if isinstance(item_type, str):
                    output_types.append(item_type)
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if not isinstance(part, Mapping):
                        continue
                    content_type = part.get("type")
                    if isinstance(content_type, str):
                        content_types.append(content_type)
                    if content_type in {"output_text", "text"} and isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
                    if content_type == "refusal":
                        refusal = part.get("refusal", part.get("text", ""))
                        if isinstance(refusal, str):
                            refusals.append(refusal)
        if not text_parts and isinstance(data.get("output_text"), str):
            text_parts.append(data["output_text"])
        return {
            "output_item_types": tuple(output_types),
            "content_item_types": tuple(content_types),
            "text": "".join(text_parts),
            "refusal": "".join(refusals),
        }

    def _persist_raw(self, raw: bytes, logical_request_id: str) -> str:
        if self._raw_response_recorder is None:
            return "raw-provider-response-unpersisted://sha256/" + hashlib.sha256(raw).hexdigest()
        return self._raw_response_recorder(raw, logical_request_id)

    @staticmethod
    def _response_bytes(resp: Any) -> bytes:
        raw = getattr(resp, "content", None)
        if isinstance(raw, bytes):
            return raw
        raise ProviderError("HTTP adapter did not expose raw response bytes")

    @staticmethod
    def _usage(data: Mapping[str, Any]) -> dict[str, Optional[int]]:
        usage = data.get("usage")
        if not isinstance(usage, Mapping):
            usage = {}
        input_details = usage.get("input_tokens_details")
        output_details = usage.get("output_tokens_details")
        return {
            "input_tokens": _optional_nonnegative_int(usage.get("input_tokens")),
            "cached_input_tokens": _optional_nonnegative_int(
                input_details.get("cached_tokens") if isinstance(input_details, Mapping) else None
            ),
            "output_tokens": _optional_nonnegative_int(usage.get("output_tokens")),
            "reasoning_tokens": _optional_nonnegative_int(
                output_details.get("reasoning_tokens") if isinstance(output_details, Mapping) else None
            ),
            "total_tokens": _optional_nonnegative_int(usage.get("total_tokens")),
        }

    def _envelope(
        self,
        *,
        logical_request_id: str,
        http_status: int,
        provider_request_id: Optional[str],
        data: Mapping[str, Any],
        observations: Mapping[str, Any],
        raw: bytes,
        raw_reference: str,
        structured: bool,
        parsing_stage: str,
        classification: str,
    ) -> ProviderResponseEnvelope:
        usage = self._usage(data)
        error = data.get("error")
        error = error if isinstance(error, Mapping) else {}
        error_message = error.get("message")
        incomplete = data.get("incomplete_details")
        incomplete = incomplete if isinstance(incomplete, Mapping) else {}
        text = observations.get("text") if isinstance(observations.get("text"), str) else ""
        refusal = observations.get("refusal") if isinstance(observations.get("refusal"), str) else ""
        text_raw = text.encode("utf-8")
        refusal_raw = refusal.encode("utf-8")
        return ProviderResponseEnvelope(
            schema_version=_ENVELOPE_SCHEMA,
            logical_request_id=logical_request_id,
            http_status=http_status,
            provider_request_id=provider_request_id,
            response_id=data.get("id") if isinstance(data.get("id"), str) else None,
            response_status=data.get("status") if isinstance(data.get("status"), str) else None,
            response_model=data.get("model") if isinstance(data.get("model"), str) else None,
            response_error_code=error.get("code") if isinstance(error.get("code"), str) else None,
            response_error_message_sha256=(
                hashlib.sha256(error_message.encode("utf-8")).hexdigest()
                if isinstance(error_message, str)
                else None
            ),
            incomplete_reason=(
                incomplete.get("reason") if isinstance(incomplete.get("reason"), str) else None
            ),
            output_item_types=tuple(observations.get("output_item_types", ())),
            content_item_types=tuple(observations.get("content_item_types", ())),
            refusal_present=bool(refusal),
            refusal_bytes=len(refusal_raw),
            refusal_sha256=hashlib.sha256(refusal_raw).hexdigest() if refusal_raw else None,
            extracted_text_bytes=len(text_raw),
            extracted_text_sha256=hashlib.sha256(text_raw).hexdigest() if text_raw else None,
            structured_output_bytes=len(text_raw) if structured else 0,
            structured_output_sha256=(
                hashlib.sha256(text_raw).hexdigest() if structured and text_raw else None
            ),
            input_tokens=usage["input_tokens"],
            cached_input_tokens=usage["cached_input_tokens"],
            output_tokens=usage["output_tokens"],
            reasoning_tokens=usage["reasoning_tokens"],
            total_tokens=usage["total_tokens"],
            raw_response_json_bytes=len(raw),
            raw_response_json_sha256=hashlib.sha256(raw).hexdigest(),
            raw_restricted_evidence_reference=raw_reference,
            parsing_stage=parsing_stage,
            terminal_classification=classification,
        )

    async def generate(
        self, request: ModelRequest, *, logical_request_id: str, org_id: str = "default"
    ):
        prompt = request.messages[-1]["content"]
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        body = self._payload(request)
        attempts: list[AttemptRecord] = []
        retry_reasons: list[str] = []
        t0 = time.monotonic()

        for attempt in range(1, self._max_retries + 1):
            a0 = time.monotonic()
            try:
                resp = await self._post(body)
            except (AuthError, InvalidRequestError):
                raise
            except Exception as exc:
                attempts.append(AttemptRecord(
                    attempt=attempt, start=a0, end=time.monotonic(),
                    exception=type(exc).__name__, retry_decision="retry", error_code="transport",
                ))
                retry_reasons.append("transport")
                if attempt >= self._max_retries:
                    raise ProviderError(
                        "transport failure",
                        self._rec(logical_request_id, prompt_hash, attempt, attempts,
                                  retry_reasons, t0, "TRANSPORT_FAILURE"),
                    )
                time.sleep(min(30.0, 2.0 * attempt))
                continue

            status = int(resp.status_code)
            raw = self._response_bytes(resp)
            # Durability precedes JSON decoding, status interpretation, text
            # extraction, and structured-output schema validation.
            raw_reference = self._persist_raw(raw, logical_request_id)
            header_request_id = resp.headers.get("x-request-id")
            header_request_id = header_request_id if isinstance(header_request_id, str) else None
            try:
                data = _strict_json_object(raw)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                observations = {
                    "output_item_types": (), "content_item_types": (), "text": "", "refusal": ""
                }
                classification = "HTTP_200_INVALID_JSON" if status == 200 else "HTTP_ERROR_INVALID_JSON"
                envelope = self._envelope(
                    logical_request_id=logical_request_id, http_status=status,
                    provider_request_id=header_request_id, data={}, observations=observations,
                    raw=raw, raw_reference=raw_reference,
                    structured=request.output_json_schema is not None,
                    parsing_stage="RAW_JSON_DECODE", classification=classification,
                )
                attempts.append(AttemptRecord(
                    attempt=attempt, start=a0, end=time.monotonic(),
                    provider_request_id=header_request_id, status=status,
                    retry_decision="stop", error_code=classification,
                ))
                rec = self._rec(
                    logical_request_id, prompt_hash, attempt, attempts, retry_reasons, t0,
                    classification, req_id=header_request_id, envelope=envelope,
                )
                if status == 200:
                    raise ParserError("HTTP 200 response was not valid JSON", rec)
                raise InvalidRequestError("HTTP error response was not valid JSON", rec)

            observations = self._extract_observations(data)
            if status == 200:
                return self._parse_ok(
                    data, observations, request, logical_request_id, prompt_hash, attempt,
                    attempts, retry_reasons, t0, a0, header_request_id, raw, raw_reference,
                )

            classification = "HTTP_RETRYABLE_ERROR" if status in {429, 500, 502, 503, 504} else (
                "HTTP_AUTH_ERROR" if status in {401, 403} else "HTTP_INVALID_REQUEST"
            )
            envelope = self._envelope(
                logical_request_id=logical_request_id, http_status=status,
                provider_request_id=header_request_id, data=data, observations=observations,
                raw=raw, raw_reference=raw_reference,
                structured=request.output_json_schema is not None,
                parsing_stage="HTTP_STATUS", classification=classification,
            )
            retryable = status in {429, 500, 502, 503, 504}
            attempts.append(AttemptRecord(
                attempt=attempt, start=a0, end=time.monotonic(),
                provider_request_id=header_request_id, status=status,
                retry_decision="retry" if retryable and attempt < self._max_retries else "stop",
                error_code=str(status),
            ))
            if retryable:
                retry_reasons.append(str(status))
                if attempt < self._max_retries:
                    time.sleep(min(60.0, 2.0 * attempt))
                    continue
            usage = self._usage(data)
            rec = self._rec(
                logical_request_id, prompt_hash, attempt, attempts, retry_reasons, t0,
                classification, returned_model=envelope.response_model, req_id=header_request_id,
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                total_tokens=usage["total_tokens"], reasoning_tokens=usage["reasoning_tokens"],
                cached_input_tokens=usage["cached_input_tokens"], finish=envelope.response_status,
                envelope=envelope,
            )
            if status in {401, 403}:
                raise AuthError("auth error %s" % status, rec)
            if retryable:
                raise ProviderError("exhausted after %s" % status, rec)
            raise InvalidRequestError("client error %s" % status, rec)

        raise AssertionError("unreachable provider retry state")

    def _parse_ok(
        self, data, observations, request, logical_request_id, prompt_hash, attempt,
        attempts, retry_reasons, t0, attempt_started, request_id, raw, raw_reference,
    ):
        status = data.get("status") if isinstance(data.get("status"), str) else None
        incomplete = data.get("incomplete_details")
        incomplete_reason = (
            incomplete.get("reason")
            if isinstance(incomplete, Mapping) and isinstance(incomplete.get("reason"), str)
            else None
        )
        if status == "failed":
            classification, parsing_stage = "RESPONSE_FAILED", "RESPONSE_STATUS"
        elif status == "incomplete":
            if incomplete_reason == "max_output_tokens":
                classification = "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"
            elif incomplete_reason == "content_filter":
                classification = "RESPONSE_INCOMPLETE_CONTENT_FILTER"
            else:
                classification = "RESPONSE_INCOMPLETE_OTHER"
            parsing_stage = "RESPONSE_STATUS"
        elif observations["refusal"]:
            classification, parsing_stage = "RESPONSE_REFUSAL", "RESPONSE_CONTENT"
        elif status == "completed" and observations["text"]:
            classification = "SUCCESS"
            parsing_stage = (
                "STRUCTURED_OUTPUT_SCHEMA" if request.output_json_schema is not None else "OUTPUT_TEXT"
            )
        elif status == "completed":
            classification = "RESPONSE_COMPLETED_WITHOUT_CONSUMABLE_OUTPUT"
            parsing_stage = "RESPONSE_CONTENT"
        else:
            classification, parsing_stage = "RESPONSE_FAILED", "RESPONSE_STATUS"

        envelope = self._envelope(
            logical_request_id=logical_request_id, http_status=200,
            provider_request_id=request_id, data=data, observations=observations,
            raw=raw, raw_reference=raw_reference,
            structured=request.output_json_schema is not None,
            parsing_stage=parsing_stage, classification=classification,
        )
        usage = self._usage(data)
        attempts.append(AttemptRecord(
            attempt=attempt, start=attempt_started, end=time.monotonic(),
            provider_request_id=request_id, status=200, retry_decision="stop",
            input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
            error_code=None if classification == "SUCCESS" else classification,
        ))

        def record(final_classification: str, *, response_hash=None):
            final_envelope = envelope if envelope.terminal_classification == final_classification else replace(
                envelope, terminal_classification=final_classification,
                parsing_stage="STRUCTURED_OUTPUT_SCHEMA",
            )
            return self._rec(
                logical_request_id, prompt_hash, attempt, attempts, retry_reasons, t0,
                "success" if final_classification == "SUCCESS" else final_classification,
                returned_model=envelope.response_model, req_id=request_id,
                input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
                total_tokens=usage["total_tokens"], reasoning_tokens=usage["reasoning_tokens"],
                cached_input_tokens=usage["cached_input_tokens"], response_hash=response_hash,
                finish=status, envelope=final_envelope,
            )

        if classification == "RESPONSE_FAILED":
            raise ProviderError("provider response status was failed", record(classification))
        if classification.startswith("RESPONSE_INCOMPLETE_"):
            raise ProviderError("provider response status was incomplete", record(classification))
        if classification == "RESPONSE_REFUSAL":
            raise PolicyRejection("provider response contained a refusal", record(classification))
        if classification == "RESPONSE_COMPLETED_WITHOUT_CONSUMABLE_OUTPUT":
            raise ParserError("completed response had no consumable output", record(classification))

        text = observations["text"]
        if request.output_json_schema is not None:
            from enterprise_memory.trimem.provider_output_contracts import validate_structured_value

            try:
                value = _strict_json_object(text.encode("utf-8"))
                validate_structured_value(value, request.output_json_schema)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ParserError(
                    "structured output did not satisfy the frozen schema",
                    record("STRUCTURED_OUTPUT_SCHEMA_FAILURE"),
                ) from None
        redacted, redaction_status = sanitize(text)
        response_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec = record("SUCCESS", response_hash=response_hash)
        rec.redaction_status = redaction_status
        return ModelResponse(
            text=redacted, finish_reason=status, returned_model=envelope.response_model,
            provider_request_id=request_id, input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"], total_tokens=usage["total_tokens"],
            envelope=rec.response_envelope,
        ), rec

    def _rec(
        self, logical_request_id, prompt_hash, attempts_n, attempts, retry_reasons,
        t0, final_status, *, returned_model=None, req_id=None, input_tokens=None,
        output_tokens=None, total_tokens=None, reasoning_tokens=None,
        cached_input_tokens=None, response_hash=None, redaction="clean", finish=None,
        envelope=None,
    ):
        rec = ModelCallRecord(
            logical_request_id=logical_request_id, attempts=attempts_n,
            provider_request_id=req_id, requested_model=self._model,
            returned_model=returned_model, prompt_hash=prompt_hash,
            response_hash=response_hash, input_tokens=input_tokens,
            output_tokens=output_tokens, total_tokens=total_tokens,
            first_byte_latency=None, total_latency=time.monotonic() - t0,
            retry_reasons=list(retry_reasons), finish_reason=finish,
            redaction_status=redaction, final_status=final_status,
            attempt_records=list(attempts), response_envelope=envelope,
        )
        rec.reasoning_tokens = reasoning_tokens
        rec.cached_input_tokens = cached_input_tokens
        return rec
