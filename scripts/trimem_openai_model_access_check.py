"""Zero-generation access check for the exact frozen OpenAI model."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Mapping

import httpx

from enterprise_memory.providers.openai_credential import (
    build_openai_headers,
    verify_openai_key_commitment,
)


MODEL_ID = "gpt-5.4-mini-2026-03-17"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def strict_json_object(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs):
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8", errors="strict"), object_pairs_hook=reject_duplicates
    )
    if not isinstance(value, dict):
        raise ValueError("response root is not an object")
    return value


def credential_binding_from_approval(document: Mapping[str, Any]) -> dict[str, str]:
    approval = document.get("approval")
    if not isinstance(approval, Mapping):
        raise ValueError("restricted approval binding is missing")
    fields = {
        "request_id": document.get("request_id"),
        "execution_head": approval.get("approved_git_commit"),
        "source_head": approval.get("approved_source_git_commit"),
        "workflow_run_id": str(approval.get("approved_workflow_run_id", "")),
        "workflow_run_attempt": str(
            approval.get("approved_workflow_run_attempt", "")
        ),
        "model_id": MODEL_ID,
        "approval_nonce": approval.get("approval_nonce"),
    }
    if not all(isinstance(value, str) and value for value in fields.values()):
        raise ValueError("restricted approval credential-binding fields differ")
    return fields  # type: ignore[return-value]


def verify_approval_credential_binding(
    api_key: object, document: Mapping[str, Any]
) -> bool:
    approval = document.get("approval")
    if not isinstance(approval, Mapping):
        return False
    return verify_openai_key_commitment(
        api_key,
        credential_binding_from_approval(document),
        approval.get("approved_openai_key_commitment"),
    )


def persist_restricted_raw(root: Path, raw: bytes) -> str:
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    target = root / digest
    if target.exists():
        if target.read_bytes() != raw:
            raise RuntimeError("restricted response digest collision")
    else:
        fd, temporary = tempfile.mkstemp(prefix=f".{digest}.", dir=str(root))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return "restricted-model-access-response://sha256/" + digest


def _error_metadata(data: Mapping[str, Any]) -> dict[str, Any]:
    error = data.get("error")
    error = error if isinstance(error, Mapping) else {}
    message = error.get("message")
    message_raw = message.encode("utf-8") if isinstance(message, str) else b""
    return {
        "provider_error_type": error.get("type")
        if isinstance(error.get("type"), str)
        else None,
        "provider_error_code": error.get("code")
        if isinstance(error.get("code"), str)
        else None,
        "provider_error_param": error.get("param")
        if isinstance(error.get("param"), str)
        else None,
        "provider_error_message_bytes": len(message_raw) if message_raw else None,
        "provider_error_message_sha256": hashlib.sha256(message_raw).hexdigest()
        if message_raw
        else None,
    }


def _access_failure(status: int) -> tuple[str, str]:
    known = {
        401: (
            "OPENAI_CREDENTIAL_REJECTED",
            "HTTP_401_AUTHENTICATION_FAILED",
        ),
        403: (
            "OPENAI_PROJECT_OR_MODEL_PERMISSION_DENIED",
            "HTTP_403_PERMISSION_DENIED",
        ),
        404: (
            "OPENAI_MODEL_NOT_AVAILABLE_TO_PROJECT",
            "HTTP_404_MODEL_NOT_AVAILABLE",
        ),
        429: (
            "OPENAI_ACCOUNT_RATE_OR_QUOTA_BLOCK",
            "HTTP_429_RATE_OR_QUOTA_LIMIT",
        ),
    }
    if status in known:
        return known[status]
    if 500 <= status <= 599:
        return "OPENAI_MODEL_ACCESS_SERVER_ERROR", "HTTP_RETRYABLE_SERVER_ERROR"
    return "OPENAI_MODEL_ACCESS_HTTP_ERROR", "HTTP_OTHER_CLIENT_ERROR"


def check_model_access(
    *,
    api_key: object,
    approval_document: Mapping[str, Any] | None,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 30.0,
    http_client: Any = None,
    raw_recorder: Callable[[bytes], str] | None = None,
) -> dict[str, Any]:
    headers = build_openai_headers(api_key, include_json_content_type=False)
    if approval_document is None:
        binding_status = "NOT_CHECKED_OPERATOR_PREFLIGHT"
    elif verify_approval_credential_binding(api_key, approval_document):
        binding_status = "PASS"
    else:
        return {
            "status": "FAIL",
            "failure_classification": "OPENAI_CREDENTIAL_BINDING_MISMATCH",
            "credential_binding": "FAIL",
            "provider_control_plane_requests": 0,
            "model_generation_requests": 0,
            "model_tokens": 0,
            "benchmark_image_pulls": 0,
            "task_arm_reservations": 0,
            "retry_decision": "stop",
        }

    owned_client = http_client is None
    client = httpx.Client() if owned_client else http_client
    try:
        response = client.get(
            base_url.rstrip("/") + "/models/" + MODEL_ID,
            headers=headers,
            timeout=timeout,
        )
    finally:
        if owned_client:
            client.close()

    raw = response.content
    raw_reference = (
        raw_recorder(raw)
        if raw_recorder is not None
        else "raw-model-access-response-unpersisted://sha256/"
        + hashlib.sha256(raw).hexdigest()
    )
    request_id = response.headers.get("x-request-id")
    request_id_hash = (
        hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        if isinstance(request_id, str) and request_id
        else None
    )
    try:
        data = strict_json_object(raw)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        data = {}
    status = int(response.status_code)
    common = {
        "http_status": status,
        "provider_request_id_sha256": request_id_hash,
        "credential_binding": binding_status,
        "raw_restricted_evidence_reference": raw_reference,
        "raw_response_bytes": len(raw),
        "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
        "provider_usage_available": isinstance(data.get("usage"), Mapping),
        "provider_control_plane_requests": 1,
        "model_generation_requests": 0,
        "model_tokens": 0,
        "benchmark_image_pulls": 0,
        "task_arm_reservations": 0,
        "retry_decision": "stop",
    }
    if (
        status == 200
        and data.get("object") == "model"
        and data.get("id") == MODEL_ID
    ):
        return {
            "status": "PASS",
            "returned_model": MODEL_ID,
            **common,
        }
    failure, http_classification = _access_failure(status)
    return {
        "status": "FAIL",
        "failure_classification": failure,
        "http_classification": http_classification,
        "returned_model": data.get("id") if isinstance(data.get("id"), str) else None,
        **_error_metadata(data),
        **common,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--restricted-evidence-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    approval = None
    if args.approval_file is not None:
        approval = strict_json_object(args.approval_file.read_bytes())
    recorder = None
    if args.restricted_evidence_dir is not None:
        recorder = lambda raw: persist_restricted_raw(
            args.restricted_evidence_dir.resolve(), raw
        )
    result = check_model_access(
        api_key=os.environ.get("OPENAI_API_KEY"),
        approval_document=approval,
        base_url=args.base_url,
        timeout=args.timeout,
        raw_recorder=recorder,
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_bytes(result) + b"\n")
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    if result.get("status") == "PASS":
        print("OPENAI_EXACT_MODEL_ACCESS_PASS")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
