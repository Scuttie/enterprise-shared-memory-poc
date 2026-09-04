"""Credential-free D1.3 response-envelope and structured-output contract tests."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import pytest

from enterprise_memory.providers.base import ModelRequest, ProviderError
from enterprise_memory.providers.openai_responses import (
    OpenAIResponsesProvider,
    RestrictedProviderResponseStore,
)
from enterprise_memory.trimem.accounting import RawEvidenceLedger, RunAccounting
from enterprise_memory.trimem.gateway import (
    AsyncProviderModelGateway,
    GatewayInvocationFailure,
    GatewayRequest,
    RecordingModelGateway,
)
from enterprise_memory.trimem.provider_output_contracts import (
    SCHEMAS,
    output_contract,
    schema_sha256,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from trimem_benchmark_run import JournaledModelGateway, TerminalInvocationJournal  # noqa: E402


MODEL = "gpt-5.4-mini-2026-03-17"


class Secrets:
    def get(self, name):
        return "credential-free-fixture"


class Response:
    def __init__(self, raw: bytes, *, status=200, request_id="req-header"):
        self.content = raw
        self.status_code = status
        self.headers = {"x-request-id": request_id}


class Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json, "headers": headers})
        return self.responses.pop(0)


def raw(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decomp_value():
    return {
        "subtasks": [{
            "id": "inspect-contract",
            "objective": "Locate the response contract boundary.",
            "predicted_operation": "inspect response envelope",
            "depends_on": [],
            "preconditions": ["provider response is available"],
            "invariants": ["raw bytes precede interpretation"],
            "files": ["src/provider.py"],
            "symbols": ["generate"],
            "apis": ["Responses"],
            "errors": ["incomplete response"],
            "tests": ["envelope is durable before validation"],
            "required_memory_facets": ["operation", "precondition", "verification"],
        }]
    }


def extraction_value():
    return {
        "episode": {"summary": "Observed contract.", "action": "persist envelope", "outcome": "passed"},
        "semantic_candidate": {
            "preconditions": "An HTTP response was received.",
            "operation": "Persist bytes before interpretation.",
            "invariant": "Raw evidence remains restricted.",
            "non_applicability": "No provider response exists.",
            "verification": "Compare raw hash and envelope hash.",
            "applicability_scope": "CROSS_REPOSITORY",
        },
    }


def completed(text: str, *, usage=True, output=None, status="completed", **extra):
    value = {
        "id": "resp-body",
        "status": status,
        "model": MODEL,
        "output_text": text,
        "output": output or [],
        **extra,
    }
    if usage:
        value["usage"] = {
            "input_tokens": 41,
            "input_tokens_details": {"cached_tokens": 7},
            "output_tokens": 23,
            "output_tokens_details": {"reasoning_tokens": 11},
            "total_tokens": 64,
        }
    return value


def provider(tmp_path, body, *, status=200, request_id="req-header"):
    client = Client([Response(body if isinstance(body, bytes) else raw(body), status=status, request_id=request_id)])
    store = RestrictedProviderResponseStore(tmp_path / "restricted")
    return OpenAIResponsesProvider(
        "https://fixture/v1", MODEL, Secrets(), family="gpt5.4", max_retries=1,
        http_client=client, raw_response_recorder=store,
    ), client, store


def request(kind="decompose"):
    contract = output_contract(
        "trimem_decomposition_v1" if kind == "decompose" else "trimem_experience_extraction_v1"
    ) if kind != "solve" else {}
    return ModelRequest([{"role": "user", "content": "fixture prompt"}], 8192 if kind != "solve" else 2048, **contract)


def invoke_direct(p, req=None):
    return asyncio.run(p.generate(req or request(), logical_request_id="logical-1", org_id="org"))


def gateway_request(kind="decompose", *, arm="M2"):
    contract = output_contract(
        "trimem_decomposition_v1" if kind == "decompose" else "trimem_experience_extraction_v1"
    ) if kind != "solve" else {}
    return GatewayRequest(
        task_id="task", arm=arm, step_no=0, call_kind=kind,
        logical_call_id=f"task:{arm}:{kind}:0001", prompt="fixture prompt",
        max_output_tokens=8192 if kind != "solve" else 2048, org_id="org", **contract,
    )


def test_completed_valid_json_schema_output_succeeds(tmp_path):
    text = json.dumps(decomp_value(), separators=(",", ":"))
    p, _, store = provider(tmp_path, completed(text))
    response, record = invoke_direct(p)
    assert response.text == text and record.final_status == "success"
    assert record.response_envelope.terminal_classification == "SUCCESS"
    digest = record.response_envelope.raw_response_json_sha256
    assert (store.root / digest).is_file()


def test_incomplete_max_tokens_preserves_usage_and_ids_through_gateway(tmp_path):
    body = completed("", status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    p, _, _ = provider(tmp_path, body)
    gateway = AsyncProviderModelGateway(p, asyncio.run, expected_model=MODEL)
    with pytest.raises(GatewayInvocationFailure) as captured:
        gateway.invoke(gateway_request())
    failure = captured.value
    assert failure.status == "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"
    assert failure.provider_request_id == "req-header" and failure.response_id == "resp-body"
    assert failure.incomplete_reason == "max_output_tokens"
    assert (failure.input_tokens, failure.output_tokens, failure.reasoning_tokens) == (41, 23, 11)


@pytest.mark.parametrize(
    ("reason", "expected"),
    [("content_filter", "RESPONSE_INCOMPLETE_CONTENT_FILTER"), ("provider_other", "RESPONSE_INCOMPLETE_OTHER")],
)
def test_incomplete_other_reason_has_exact_subtype(tmp_path, reason, expected):
    p, _, _ = provider(tmp_path, completed("", status="incomplete", incomplete_details={"reason": reason}))
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    assert captured.value.record.final_status == expected


def test_failed_response_preserves_error_object_metadata(tmp_path):
    body = completed("", status="failed", error={"code": "upstream_failed", "message": "private detail"})
    p, _, _ = provider(tmp_path, body)
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    envelope = captured.value.record.response_envelope
    assert envelope.terminal_classification == "RESPONSE_FAILED"
    assert envelope.response_error_code == "upstream_failed"
    assert envelope.response_error_message_sha256 == hashlib.sha256(b"private detail").hexdigest()


def test_completed_refusal_is_distinct(tmp_path):
    output = [{"type": "message", "content": [{"type": "refusal", "refusal": "cannot comply"}]}]
    p, _, _ = provider(tmp_path, completed("", output=output))
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    envelope = captured.value.record.response_envelope
    assert envelope.terminal_classification == "RESPONSE_REFUSAL"
    assert envelope.refusal_present and envelope.refusal_bytes == len(b"cannot comply")


def test_completed_without_consumable_output_is_distinct(tmp_path):
    p, _, _ = provider(tmp_path, completed(""))
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    assert captured.value.record.final_status == "RESPONSE_COMPLETED_WITHOUT_CONSUMABLE_OUTPUT"


def test_malformed_structured_output_is_schema_failure(tmp_path):
    p, _, _ = provider(tmp_path, completed('{"subtasks":[]}'))
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    assert captured.value.record.final_status == "STRUCTURED_OUTPUT_SCHEMA_FAILURE"


def test_reasoning_item_before_message_extracts_visible_text(tmp_path):
    text = json.dumps(decomp_value(), separators=(",", ":"))
    output = [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": text}]},
    ]
    p, _, _ = provider(tmp_path, completed("", output=output))
    response, record = invoke_direct(p)
    assert response.text == text
    assert record.response_envelope.output_item_types == ("reasoning", "message")
    assert record.response_envelope.content_item_types == ("output_text",)


def test_http_200_invalid_json_keeps_raw_hash(tmp_path):
    body = b"{not-json"
    p, _, store = provider(tmp_path, body)
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    envelope = captured.value.record.response_envelope
    assert envelope.terminal_classification == "HTTP_200_INVALID_JSON"
    assert envelope.raw_response_json_sha256 == hashlib.sha256(body).hexdigest()
    assert (store.root / envelope.raw_response_json_sha256).read_bytes() == body


def test_missing_usage_is_unavailable_not_zero(tmp_path):
    text = json.dumps(decomp_value(), separators=(",", ":"))
    p, _, _ = provider(tmp_path, completed(text, usage=False))
    _, record = invoke_direct(p)
    envelope = record.response_envelope
    assert envelope.provider_reported_usage_available is False
    assert envelope.input_tokens is None and envelope.output_tokens is None


def test_cached_and_reasoning_usage_are_exact(tmp_path):
    text = json.dumps(decomp_value(), separators=(",", ":"))
    p, _, _ = provider(tmp_path, completed(text))
    _, record = invoke_direct(p)
    envelope = record.response_envelope
    assert (envelope.input_tokens, envelope.cached_input_tokens) == (41, 7)
    assert (envelope.output_tokens, envelope.reasoning_tokens, envelope.total_tokens) == (23, 11, 64)


def test_header_and_body_request_ids_are_both_preserved(tmp_path):
    text = json.dumps(decomp_value(), separators=(",", ":"))
    p, _, _ = provider(tmp_path, completed(text), request_id="req-separate")
    _, record = invoke_direct(p)
    assert record.provider_request_id == "req-separate"
    assert record.response_envelope.response_id == "resp-body"


def test_provider_gateway_failure_propagates_without_metadata_loss(tmp_path):
    body = completed("", status="incomplete", incomplete_details={"reason": "content_filter"})
    p, _, _ = provider(tmp_path, body)
    gateway = AsyncProviderModelGateway(p, asyncio.run, expected_model=MODEL)
    with pytest.raises(GatewayInvocationFailure) as captured:
        gateway.invoke(gateway_request())
    failure = captured.value
    assert failure.original_provider_terminal_classification == "RESPONSE_INCOMPLETE_CONTENT_FILTER"
    assert failure.response_status == "incomplete"
    assert failure.raw_envelope_reference.startswith("restricted-provider-response://")
    assert failure.provider_response_envelope["provider_usage"]["reasoning_tokens"] == 11


def test_raw_response_is_persisted_before_schema_failure(tmp_path):
    p, _, store = provider(tmp_path, completed('{"subtasks":[]}'))
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    digest = captured.value.record.response_envelope.raw_response_json_sha256
    assert (store.root / digest).is_file()


def test_public_envelope_has_no_raw_output_or_refusal_text(tmp_path):
    output = [{"type": "message", "content": [{"type": "refusal", "refusal": "private refusal"}]}]
    p, _, _ = provider(tmp_path, completed("", output=output))
    with pytest.raises(ProviderError) as captured:
        invoke_direct(p)
    public = json.dumps(captured.value.record.response_envelope.to_public_dict(), sort_keys=True)
    assert "private refusal" not in public and "fixture prompt" not in public
    assert "refusal_sha256" in public and "raw_response_json_sha256" in public


def test_terminal_journal_replay_does_not_duplicate_actual_call_events(tmp_path):
    class OnceFailing:
        def __init__(self):
            self.calls = 0

        def invoke(self, req):
            self.calls += 1
            raise GatewayInvocationFailure(
                provider="fixture", model=MODEL, status="RESPONSE_FAILED", attempt=1,
                input_tokens=3, output_tokens=2, cached_input_tokens=0, reasoning_tokens=1,
                provider_reported_usage_available=True,
            )

    delegate = OnceFailing()
    journal = TerminalInvocationJournal(tmp_path / "journal")
    accounting = RunAccounting()
    evidence = RawEvidenceLedger(tmp_path / "evidence", clock=lambda: "2026-09-04T00:00:00Z")
    recording = RecordingModelGateway(JournaledModelGateway(delegate, journal), accounting, evidence)
    req = gateway_request("solve", arm="M0")
    with pytest.raises(GatewayInvocationFailure):
        recording.invoke(req)
    process_level_resumes = 1
    with pytest.raises(GatewayInvocationFailure) as replayed:
        recording.invoke(req)
    assert replayed.value.terminal_outcome_replayed is True and delegate.calls == 1
    events = [json.loads(line)["event_type"] for line in evidence.events_path.read_text().splitlines()]
    assert events.count("model_request") == 1 and events.count("model_failure") == 1
    assert events.count("model_terminal_outcome_replayed") == 1
    assert process_level_resumes == 1
    assert accounting.summary()["model_gateway_calls"] == 1
    assert accounting.summary()["paid_model_calls"] == 1
    assert delegate.calls == 1


def test_decomposition_request_contains_exact_strict_schema(tmp_path):
    text = json.dumps(decomp_value(), separators=(",", ":"))
    p, client, _ = provider(tmp_path, completed(text))
    invoke_direct(p)
    format_body = client.calls[0]["body"]["text"]["format"]
    assert format_body == {
        "type": "json_schema", "name": "trimem_decomposition_v1", "strict": True,
        "schema": SCHEMAS["trimem_decomposition_v1"],
    }


def test_extraction_request_contains_exact_strict_schema(tmp_path):
    text = json.dumps(extraction_value(), separators=(",", ":"))
    p, client, _ = provider(tmp_path, completed(text))
    invoke_direct(p, request("extract"))
    format_body = client.calls[0]["body"]["text"]["format"]
    assert format_body["name"] == "trimem_experience_extraction_v1"
    assert format_body["strict"] is True
    assert schema_sha256(format_body["schema"]) == schema_sha256(
        SCHEMAS["trimem_experience_extraction_v1"]
    )


def test_solve_request_remains_unstructured_and_byte_compatible(tmp_path):
    p, client, _ = provider(tmp_path, completed('{"tool":"list_files","arguments":{}}'))
    invoke_direct(p, request("solve"))
    body = client.calls[0]["body"]
    assert "text" not in body
    assert body == {
        "model": MODEL,
        "input": [{"role": "user", "content": "fixture prompt"}],
        "max_output_tokens": 2048,
        "reasoning": {"effort": "medium"},
    }


def test_all_arms_share_role_contracts_and_output_ceilings():
    lock = RuntimeLock()
    assert lock.limits.max_output_tokens_decomposition == 8192
    assert lock.limits.max_output_tokens_extraction == 8192
    decompose = [gateway_request("decompose", arm=arm) for arm in ("M0", "M1", "M2")]
    extract = [gateway_request("extract", arm=arm) for arm in ("M0", "M1", "M2")]
    assert len({row.output_schema_sha256 for row in decompose}) == 1
    assert len({row.output_schema_sha256 for row in extract}) == 1
    assert {row.max_output_tokens for row in decompose + extract} == {8192}
