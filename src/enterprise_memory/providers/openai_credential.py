"""Fail-closed OpenAI credential validation and run-bound commitments."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping


MIN_OPENAI_KEY_BYTES = 20
MAX_OPENAI_KEY_BYTES = 512


class OpenAICredentialValidationError(ValueError):
    """A public-safe failure that never includes credential material."""

    def __init__(self, classification: str):
        self.classification = classification
        super().__init__(classification)


def validate_openai_api_key(value: object) -> bytes:
    """Return the exact validated ASCII bytes without repairing the input."""

    if value is None or value == "" or value == b"":
        raise OpenAICredentialValidationError("OPENAI_KEY_EMPTY")
    if isinstance(value, bytes):
        raw = value
        try:
            text = raw.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            raise OpenAICredentialValidationError("OPENAI_KEY_NON_ASCII") from None
    elif isinstance(value, str):
        text = value
        try:
            raw = text.encode("ascii", errors="strict")
        except UnicodeEncodeError:
            raise OpenAICredentialValidationError("OPENAI_KEY_NON_ASCII") from None
    else:
        raise OpenAICredentialValidationError("OPENAI_KEY_NON_ASCII")

    if text[0] in {"'", '"'} or text[-1] in {"'", '"'}:
        raise OpenAICredentialValidationError("OPENAI_KEY_SURROUNDING_QUOTES")
    if any(byte < 0x21 or byte > 0x7E for byte in raw):
        raise OpenAICredentialValidationError("OPENAI_KEY_CONTROL_CHARACTER")
    if not MIN_OPENAI_KEY_BYTES <= len(raw) <= MAX_OPENAI_KEY_BYTES:
        raise OpenAICredentialValidationError("OPENAI_KEY_LENGTH_INVALID")
    return raw


def build_openai_headers(
    value: object, *, include_json_content_type: bool = True
) -> dict[str, str]:
    raw = validate_openai_api_key(value)
    headers = {"Authorization": "Bearer " + raw.decode("ascii")}
    if include_json_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def canonical_credential_binding_bytes(binding: Mapping[str, Any]) -> bytes:
    expected = {
        "request_id",
        "execution_head",
        "source_head",
        "workflow_run_id",
        "workflow_run_attempt",
        "model_id",
        "approval_nonce",
    }
    if set(binding) != expected or not all(
        isinstance(binding[field], str) and binding[field]
        for field in expected
    ):
        raise ValueError("credential binding field set or scalar type differs")
    return json.dumps(
        dict(binding),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def compute_openai_key_commitment(
    value: object, binding: Mapping[str, Any]
) -> str:
    key = validate_openai_api_key(value)
    return hmac.new(
        key,
        canonical_credential_binding_bytes(binding),
        hashlib.sha256,
    ).hexdigest()


def verify_openai_key_commitment(
    value: object, binding: Mapping[str, Any], expected: object
) -> bool:
    if not isinstance(expected, str) or len(expected) != 64:
        return False
    try:
        int(expected, 16)
    except ValueError:
        return False
    return hmac.compare_digest(compute_openai_key_commitment(value, binding), expected)


__all__ = [
    "MAX_OPENAI_KEY_BYTES",
    "MIN_OPENAI_KEY_BYTES",
    "OpenAICredentialValidationError",
    "build_openai_headers",
    "canonical_credential_binding_bytes",
    "compute_openai_key_commitment",
    "validate_openai_api_key",
    "verify_openai_key_commitment",
]
