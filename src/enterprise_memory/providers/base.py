"""Coding-model provider interface + accounting record (P4 §11-§12)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


class ProviderError(Exception):
    """Transport/5xx/exhaustion failure. Never carries the API key."""


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
class ModelRequest:
    messages: List[dict]
    max_output_tokens: int
    temperature: float = 0.0
    top_p: float = 1.0


@dataclass
class ModelResponse:
    text: str
    finish_reason: Optional[str]
    returned_model: Optional[str]
    provider_request_id: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]


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

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


class CodingModelProvider(ABC):
    @abstractmethod
    async def generate(self, request: ModelRequest, *, logical_request_id: str, org_id: str): ...
