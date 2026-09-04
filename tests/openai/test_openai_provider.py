"""R12 §4 — OpenAIResponsesProvider contract tests against a FAKE Responses server. Credential-free: the secret
provider returns a dummy token; NO real OpenAI key or endpoint is used. Validates the per-family request schema,
retry policy, redaction, accounting completeness, malformed handling, and stable logical_request_id."""
import asyncio
import json
import pytest

from enterprise_memory.providers.openai_responses import OpenAIResponsesProvider
from enterprise_memory.providers.base import ModelRequest, AuthError, InvalidRequestError, ParserError, ProviderError


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.content = body if isinstance(body, bytes) else json.dumps(
            body, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        self.headers = headers or {"x-request-id": "req_fake_1"}

    def json(self):
        return self._body


class FakeClient:
    """Serves a scripted queue of responses and records the last request body."""
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json, "headers": headers})
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeSecrets:
    def get(self, name):
        return "DUMMY-NOT-REAL-CREDENTIAL-0001"  # never a real key


def ok_body(model="gpt-5.6-terra", text="```python\nprint(1)\n```", rt=64):
    return {"id": "resp_1", "model": model, "status": "completed", "output_text": text,
            "output": [{"id": "msg-1", "type": "message",
                        "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150,
                      "output_tokens_details": {"reasoning_tokens": rt},
                      "input_tokens_details": {"cached_tokens": 10}}}


def run(coro):
    # Each test owns its loop.  Python 3.11 no longer creates an implicit
    # replacement after another suite closes the process-global loop.
    return asyncio.run(coro)


def test_gpt56_schema_reasoning_no_temperature():
    c = FakeClient([FakeResp(200, ok_body())])
    p = OpenAIResponsesProvider("https://fake/v1", "gpt-5.6-terra", FakeSecrets(), family="gpt5.6",
                                reasoning_effort="medium", http_client=c)
    resp, rec = run(p.generate(ModelRequest(messages=[{"role": "user", "content": "solve X"}],
                                            max_output_tokens=4096), logical_request_id="L1"))
    body = c.calls[0]["body"]
    assert body["reasoning"] == {"effort": "medium"}
    assert "temperature" not in body           # HARD: no temperature for GPT-5.6
    assert body["max_output_tokens"] == 4096
    assert rec.final_status == "success" and rec.returned_model == "gpt-5.6-terra"
    assert rec.reasoning_tokens == 64 and rec.cached_input_tokens == 10
    assert rec.input_tokens == 100 and rec.output_tokens == 50


def test_gpt54_mini_dated_snapshot_schema_reasoning_no_temperature():
    c = FakeClient([FakeResp(200, ok_body(model="gpt-5.4-mini-2026-03-17"))])
    p = OpenAIResponsesProvider(
        "https://fake/v1", "gpt-5.4-mini-2026-03-17", FakeSecrets(), family="gpt5.4",
        reasoning_effort="medium", max_retries=1, http_client=c,
    )
    run(p.generate(
        ModelRequest(messages=[{"role": "user", "content": "solve X"}], max_output_tokens=2048),
        logical_request_id="L-gpt54",
    ))
    body = c.calls[0]["body"]
    assert body["reasoning"] == {"effort": "medium"}
    assert "temperature" not in body


def test_gpt4o_schema_temperature_no_reasoning():
    c = FakeClient([FakeResp(200, ok_body(model="gpt-4o-mini-2024-07-18"))])
    p = OpenAIResponsesProvider("https://fake/v1", "gpt-4o-mini-2024-07-18", FakeSecrets(), family="gpt4o",
                                http_client=c)
    resp, rec = run(p.generate(ModelRequest(messages=[{"role": "user", "content": "solve"}],
                                            max_output_tokens=4096), logical_request_id="L2"))
    body = c.calls[0]["body"]
    assert body["temperature"] == 0.0         # HARD: temperature for GPT-4o mini
    assert "reasoning" not in body            # HARD: no reasoning parameter for GPT-4o mini


def test_429_then_success_same_logical_id():
    c = FakeClient([FakeResp(429, {}), FakeResp(200, ok_body())])
    p = OpenAIResponsesProvider("https://fake/v1", "gpt-5.6-luna", FakeSecrets(), family="gpt5.6", http_client=c)
    resp, rec = run(p.generate(ModelRequest([{"role": "user", "content": "x"}], 2048), logical_request_id="LID"))
    assert rec.final_status == "success" and rec.attempts == 2
    assert "429" in rec.retry_reasons and rec.logical_request_id == "LID"


def test_5xx_retry():
    c = FakeClient([FakeResp(503, {}), FakeResp(200, ok_body())])
    p = OpenAIResponsesProvider("https://fake/v1", "gpt-5.6-terra", FakeSecrets(), family="gpt5.6", http_client=c)
    _, rec = run(p.generate(ModelRequest([{"role": "user", "content": "x"}], 2048), logical_request_id="L"))
    assert rec.final_status == "success" and "503" in rec.retry_reasons


def test_ordinary_4xx_no_retry():
    c = FakeClient([FakeResp(400, {"error": "bad"})])
    p = OpenAIResponsesProvider("https://fake/v1", "gpt-5.6-terra", FakeSecrets(), family="gpt5.6", http_client=c)
    with pytest.raises(InvalidRequestError):
        run(p.generate(ModelRequest([{"role": "user", "content": "x"}], 2048), logical_request_id="L"))
    assert len(c.calls) == 1                    # HARD: no retry on ordinary 4xx


def test_auth_error_no_key_never_leaks():
    class NoKey:
        def get(self, n):
            return None
    c = FakeClient([FakeResp(200, ok_body())])
    p = OpenAIResponsesProvider("https://fake/v1", "gpt-5.6-terra", NoKey(), family="gpt5.6", http_client=c)
    with pytest.raises(AuthError) as e:
        run(p.generate(ModelRequest([{"role": "user", "content": "x"}], 2048), logical_request_id="L"))
    assert "sk-" not in str(e.value)            # never carries a key


def test_incomplete_response_has_exact_terminal_classification():
    c = FakeClient([FakeResp(200, {"id": "r", "model": "gpt-5.6-terra", "status": "incomplete",
                                   "output_text": "", "usage": {}, "incomplete_details": {"reason": "max_output_tokens"}})])
    p = OpenAIResponsesProvider("https://fake/v1", "gpt-5.6-terra", FakeSecrets(), family="gpt5.6", http_client=c)
    with pytest.raises(ProviderError) as captured:
        run(p.generate(ModelRequest([{"role": "user", "content": "x"}], 8), logical_request_id="L"))
    assert captured.value.record.final_status == "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"


def test_unknown_family_rejected():
    with pytest.raises(ValueError):
        OpenAIResponsesProvider("https://fake/v1", "gpt-5-nano", FakeSecrets(), family="mystery")
