"""Coding-model provider interface + accounting record (P4 §11-§12)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple


class ProviderError(Exception):
    """Transport/5xx/exhaustion failure. Never carries the API key. Carries the accounting record so the
    caller can persist a LogicalModelCall on every outcome, not only success."""
    def __init__(self, message, record=None):
        super().__init__(message)
        self.record = record


class AuthError(ProviderError):
    pass


class InvalidRequestError(ProviderError):
    pass


class PolicyRejection(ProviderError):
    pass


class ParserError(ProviderError):
    pass


class CircuitOpenError(ProviderError):
    pass


@dataclass
class AttemptRecord:
    attempt: int
    start: float
    end: float
    provider_request_id: Optional[str] = None
    status: Optional[int] = None
    exception: Optional[str] = None
    retry_decision: str = "stop"      # retry | stop
    retry_delay: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error_code: Optional[str] = None


@dataclass(frozen=True)
class ModelRequest:
    messages: List[dict]
    max_output_tokens: int
    temperature: float = 0.0
    top_p: float = 1.0
    output_schema_name: Optional[str] = None
    output_json_schema: Optional[Mapping[str, Any]] = None
    output_schema_sha256: Optional[str] = None
    strict_structured_output: bool = False

    def __post_init__(self) -> None:
        contract = (
            self.output_schema_name,
            self.output_json_schema,
            self.output_schema_sha256,
        )
        if any(value is not None for value in contract) and not all(
            value is not None for value in contract
        ):
            raise ValueError("structured output contract fields must be supplied together")
        if self.strict_structured_output and not all(value is not None for value in contract):
            raise ValueError("strict structured output requires a complete output contract")


@dataclass(frozen=True)
class ProviderResponseEnvelope:
    """Immutable, sanitized metadata captured before response interpretation.

    Raw provider bytes live only behind ``raw_restricted_evidence_reference``.
    ``to_public_dict`` never emits task output, refusal text, or a raw request ID.
    """

    schema_version: str
    logical_request_id: str
    http_status: int
    provider_request_id: Optional[str]
    response_id: Optional[str]
    response_status: Optional[str]
    response_model: Optional[str]
    response_error_code: Optional[str]
    response_error_message_sha256: Optional[str]
    incomplete_reason: Optional[str]
    output_item_types: Tuple[str, ...]
    content_item_types: Tuple[str, ...]
    refusal_present: bool
    refusal_bytes: int
    refusal_sha256: Optional[str]
    extracted_text_bytes: int
    extracted_text_sha256: Optional[str]
    structured_output_bytes: int
    structured_output_sha256: Optional[str]
    input_tokens: Optional[int]
    cached_input_tokens: Optional[int]
    output_tokens: Optional[int]
    reasoning_tokens: Optional[int]
    total_tokens: Optional[int]
    raw_response_json_bytes: int
    raw_response_json_sha256: str
    raw_restricted_evidence_reference: str
    parsing_stage: str
    terminal_classification: str
    response_error_type: Optional[str] = None
    response_error_param: Optional[str] = None
    response_error_message_bytes: Optional[int] = None
    retry_decision: str = "stop"

    @property
    def provider_reported_usage_available(self) -> bool:
        return all(
            value is not None
            for value in (
                self.input_tokens,
                self.cached_input_tokens,
                self.output_tokens,
                self.reasoning_tokens,
                self.total_tokens,
            )
        )

    def to_public_dict(self) -> dict[str, Any]:
        request_id_hash = None
        if self.provider_request_id:
            import hashlib

            request_id_hash = hashlib.sha256(
                self.provider_request_id.encode("utf-8")
            ).hexdigest()
        return {
            "schema_version": self.schema_version,
            "logical_request_id": self.logical_request_id,
            "http_status": self.http_status,
            "provider_request_id_sha256": request_id_hash,
            "response_id": self.response_id,
            "response_status": self.response_status,
            "response_model": self.response_model,
            "response_error_code": self.response_error_code,
            "response_error_type": self.response_error_type,
            "response_error_param": self.response_error_param,
            "response_error_message_bytes": self.response_error_message_bytes,
            "response_error_message_sha256": self.response_error_message_sha256,
            "incomplete_reason": self.incomplete_reason,
            "output_item_types": list(self.output_item_types),
            "content_item_types": list(self.content_item_types),
            "refusal_present": self.refusal_present,
            "refusal_bytes": self.refusal_bytes,
            "refusal_sha256": self.refusal_sha256,
            "extracted_text_bytes": self.extracted_text_bytes,
            "extracted_text_sha256": self.extracted_text_sha256,
            "structured_output_bytes": self.structured_output_bytes,
            "structured_output_sha256": self.structured_output_sha256,
            "provider_usage": {
                "available": self.provider_reported_usage_available,
                "input_tokens": self.input_tokens,
                "cached_input_tokens": self.cached_input_tokens,
                "output_tokens": self.output_tokens,
                "reasoning_tokens": self.reasoning_tokens,
                "total_tokens": self.total_tokens,
            },
            "raw_response_json_bytes": self.raw_response_json_bytes,
            "raw_response_json_sha256": self.raw_response_json_sha256,
            "raw_restricted_evidence_reference": self.raw_restricted_evidence_reference,
            "parsing_stage": self.parsing_stage,
            "terminal_classification": self.terminal_classification,
            "retry_decision": self.retry_decision,
        }


@dataclass
class ModelResponse:
    text: str
    finish_reason: Optional[str]
    returned_model: Optional[str]
    provider_request_id: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    envelope: Optional[ProviderResponseEnvelope] = None


@dataclass
class ModelCallRecord:
    logical_request_id: str
    attempts: int
    provider_request_id: Optional[str]
    requested_model: str
    returned_model: Optional[str]
    prompt_hash: str
    response_hash: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    first_byte_latency: Optional[float]
    total_latency: Optional[float]
    retry_reasons: List[str] = field(default_factory=list)
    finish_reason: Optional[str] = None
    parser_status: str = "ok"
    redaction_status: str = "clean"
    circuit_state: str = "closed"
    created_at: Optional[str] = None
    final_status: str = "success"     # success|auth|invalid|exhausted|deadline|parser|cancelled|circuit_open|transport
    attempt_records: List[AttemptRecord] = field(default_factory=list)
    response_envelope: Optional[ProviderResponseEnvelope] = None

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__dataclass_fields__}
        d["attempt_records"] = [a.__dict__ for a in self.attempt_records]
        if self.response_envelope is not None:
            d["response_envelope"] = self.response_envelope.to_public_dict()
        return d


class CodingModelProvider(ABC):
    @abstractmethod
    async def generate(self, request: ModelRequest, *, logical_request_id: str, org_id: str): ...
