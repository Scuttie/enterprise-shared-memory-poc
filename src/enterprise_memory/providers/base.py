"""Coding-model provider interface + accounting record (P4 §11-§12)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple


STRUCTURED_TEXT = "STRUCTURED_TEXT"
SINGLE_FUNCTION_CALL = "SINGLE_FUNCTION_CALL"


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
    response_mode: str = STRUCTURED_TEXT
    function_tools: Tuple[Mapping[str, Any], ...] = ()
    function_tools_sha256: Optional[str] = None
    tool_choice: Optional[Any] = None
    parallel_tool_calls: Optional[bool] = None

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
        if self.response_mode not in {STRUCTURED_TEXT, SINGLE_FUNCTION_CALL}:
            raise ValueError("unknown response mode")
        function_contract = (
            bool(self.function_tools),
            self.function_tools_sha256 is not None,
            self.tool_choice is not None,
            self.parallel_tool_calls is not None,
        )
        if self.response_mode == SINGLE_FUNCTION_CALL:
            if not all(function_contract):
                raise ValueError("single-function mode requires the complete function contract")
            if any(value is not None for value in contract) or self.strict_structured_output:
                raise ValueError("single-function mode cannot use text structured output")
            if self.parallel_tool_calls is not False:
                raise ValueError("single-function mode forbids parallel tool calls")
        elif any(function_contract):
            raise ValueError("structured-text mode cannot carry function tools")


@dataclass(frozen=True)
class ProviderOutputItem:
    index: int
    item_id: Optional[str]
    item_type: str
    raw_json: str
    raw_json_bytes: int
    raw_json_sha256: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "item_type": self.item_type,
            "raw_json_bytes": self.raw_json_bytes,
            "raw_json_sha256": self.raw_json_sha256,
        }


@dataclass(frozen=True)
class ProviderMessageItem(ProviderOutputItem):
    content_item_count: int
    content_item_types: Tuple[str, ...]
    text_item_count: int
    text: str
    text_bytes: int
    text_sha256: Optional[str]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            **super().to_public_dict(),
            "content_item_count": self.content_item_count,
            "content_item_types": list(self.content_item_types),
            "text_item_count": self.text_item_count,
            "text_bytes": self.text_bytes,
            "text_sha256": self.text_sha256,
        }


@dataclass(frozen=True)
class ProviderFunctionCall(ProviderOutputItem):
    function_name: Optional[str]
    call_id: Optional[str]
    arguments: str
    argument_bytes: int
    arguments_sha256: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            **super().to_public_dict(),
            "function_name": self.function_name,
            "argument_bytes": self.argument_bytes,
            "arguments_sha256": self.arguments_sha256,
        }


@dataclass(frozen=True)
class ProviderRefusalItem:
    output_index: int
    content_index: int
    refusal: str
    refusal_bytes: int
    refusal_sha256: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "output_index": self.output_index,
            "content_index": self.content_index,
            "refusal_bytes": self.refusal_bytes,
            "refusal_sha256": self.refusal_sha256,
        }


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
    output_items: Tuple[Mapping[str, Any], ...] = ()

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
            "output_items": [dict(item) for item in self.output_items],
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
    response_mode: str = STRUCTURED_TEXT
    output_items: Tuple[ProviderOutputItem, ...] = ()
    function_call_id: Optional[str] = None
    function_name: Optional[str] = None
    function_arguments: Optional[str] = None
    function_arguments_sha256: Optional[str] = None


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
