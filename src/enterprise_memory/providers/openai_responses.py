"""OpenAI Responses-API coding-model provider (R12 §4). Same production CodingModelProvider interface as
SolarProvider: never carries the API key in exceptions/logs, records a ModelCallRecord on every outcome, bounded
retries (429/5xx + transport only; ordinary 4xx never retried), stable logical_request_id across retries,
redaction. Uses the Responses API (`POST {base}/responses`).

Per-family request rules (frozen by R12):
  - GPT-5 reasoning family: reasoning={"effort": <effort>}; NO temperature; reasoning context = current turn
    (one response, no continuation); max_output_tokens = frozen budget.
  - GPT-4o family (mini): temperature=0; NO reasoning parameter; max_output_tokens = frozen budget.
The system instruction, task prompt, memory placement, extraction, grader and budgets are identical across
readers — provider-specific prompt rewriting is prohibited (only the provider/model envelope differs).
"""
from __future__ import annotations
import json
import time
import hashlib
from typing import Optional

from .base import (CodingModelProvider, ModelRequest, ModelResponse, ModelCallRecord, AttemptRecord,
                   ProviderError, AuthError, InvalidRequestError, ParserError)
from .redaction import sanitize

_REASONING_FAMILIES = {"gpt5", "gpt-5", "gpt5.4", "gpt-5.4", "gpt5.6", "gpt-5.6", "reasoning"}
_NONREASONING_FAMILIES = {"gpt4o", "gpt-4o", "nonreasoning"}


class OpenAIResponsesProvider(CodingModelProvider):
    def __init__(self, base_url, model, secret_provider, *, family, key_name="OPENAI_API_KEY",
                 reasoning_effort="medium", timeout=180.0, max_retries=6, http_client=None):
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
        self._client = http_client  # injectable for the fake-server CI

    # ---- request envelope (per family) --------------------------------------------------
    def _payload(self, request: ModelRequest) -> dict:
        # one user message; system instruction is prepended by the caller into the prompt (identical across readers)
        body = {"model": self._model,
                "input": [{"role": "user", "content": request.messages[-1]["content"]}],
                "max_output_tokens": request.max_output_tokens}
        if self._reasoning:
            body["reasoning"] = {"effort": self._effort}
            # NO temperature for GPT-5 reasoning models (hard rule)
        else:
            body["temperature"] = 0.0
            # NO reasoning parameter for GPT-4o mini (hard rule)
        return body

    def _headers(self):
        key = self._secrets.get(self._key_name)
        if not key:
            raise AuthError("missing %s" % self._key_name)  # never includes any key value
        return {"Authorization": "Bearer %s" % key, "Content-Type": "application/json"}

    async def _post(self, body):
        client = self._client
        assert client is not None, "no http client bound"
        return await client.post(self._base + "/responses", json=body, headers=self._headers(),
                                 timeout=self._timeout)

    # ---- response parsing (Responses API) -----------------------------------------------
    @staticmethod
    def _extract_text(data) -> str:
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        parts = []
        for item in (data.get("output") or []):
            for c in (item.get("content") or []):
                if isinstance(c, dict) and c.get("type") in ("output_text", "text") and c.get("text"):
                    parts.append(c["text"])
        return "".join(parts)

    async def generate(self, request: ModelRequest, *, logical_request_id: str, org_id: str = "default"):
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
                raise  # config/auth errors are terminal, never retried as transport
            except Exception as ex:  # transport
                attempts.append(AttemptRecord(attempt=attempt, start=a0, end=time.monotonic(),
                                              exception=type(ex).__name__, retry_decision="retry",
                                              error_code="transport"))
                retry_reasons.append("transport")
                if attempt >= self._max_retries:
                    raise ProviderError("transport failure", self._rec(logical_request_id, prompt_hash, attempt,
                                        attempts, retry_reasons, t0, "transport"))
                time.sleep(min(30.0, 2.0 * attempt)); continue

            status = resp.status_code
            if status == 200:
                data = resp.json()
                return self._parse_ok(data, logical_request_id, prompt_hash, attempt, attempts, retry_reasons, t0,
                                      resp.headers.get("x-request-id"))
            if status in (429, 500, 502, 503, 504):
                attempts.append(AttemptRecord(attempt=attempt, start=a0, end=time.monotonic(), status=status,
                                              retry_decision="retry", error_code=str(status)))
                retry_reasons.append(str(status))
                if attempt >= self._max_retries:
                    raise ProviderError("exhausted after %s" % status,
                                        self._rec(logical_request_id, prompt_hash, attempt, attempts,
                                                  retry_reasons, t0, "exhausted"))
                time.sleep(min(60.0, 2.0 * attempt)); continue
            # ordinary 4xx -> no retry
            attempts.append(AttemptRecord(attempt=attempt, start=a0, end=time.monotonic(), status=status,
                                          retry_decision="stop", error_code=str(status)))
            rec = self._rec(logical_request_id, prompt_hash, attempt, attempts, retry_reasons, t0,
                            "auth" if status in (401, 403) else "invalid")
            if status in (401, 403):
                raise AuthError("auth error %s" % status, rec)
            raise InvalidRequestError("client error %s" % status, rec)

    def _parse_ok(self, data, lrid, prompt_hash, attempts_n, attempts, retry_reasons, t0, req_id):
        text = self._extract_text(data)
        usage = data.get("usage", {}) or {}
        out_details = usage.get("output_tokens_details", {}) or {}
        in_details = usage.get("input_tokens_details", {}) or {}
        redacted, redaction_status = sanitize(text)
        if not text:
            rec = self._rec(lrid, prompt_hash, attempts_n, attempts, retry_reasons, t0, "parser",
                            returned_model=data.get("model"), req_id=req_id,
                            finish=data.get("incomplete_details", {}).get("reason") if isinstance(
                                data.get("incomplete_details"), dict) else data.get("status"))
            rec.parser_status = "empty"
            raise ParserError("empty/incomplete response", rec)
        rec = self._rec(lrid, prompt_hash, attempts_n, attempts, retry_reasons, t0, "success",
                        returned_model=data.get("model"), req_id=data.get("id") or req_id,
                        input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        reasoning_tokens=out_details.get("reasoning_tokens"),
                        cached_input_tokens=in_details.get("cached_tokens"),
                        response_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        redaction=redaction_status, finish=data.get("status") or "completed")
        return ModelResponse(text=text, finish_reason=rec.finish_reason, returned_model=data.get("model"),
                             provider_request_id=rec.provider_request_id, input_tokens=usage.get("input_tokens"),
                             output_tokens=usage.get("output_tokens"), total_tokens=usage.get("total_tokens")), rec

    def _rec(self, lrid, prompt_hash, attempts_n, attempts, retry_reasons, t0, final_status, *,
             returned_model=None, req_id=None, input_tokens=None, output_tokens=None, total_tokens=None,
             reasoning_tokens=None, cached_input_tokens=None, response_hash=None, redaction="clean", finish=None):
        rec = ModelCallRecord(
            logical_request_id=lrid, attempts=attempts_n, provider_request_id=req_id,
            requested_model=self._model, returned_model=returned_model, prompt_hash=prompt_hash,
            response_hash=response_hash, input_tokens=input_tokens, output_tokens=output_tokens,
            total_tokens=total_tokens, first_byte_latency=None, total_latency=time.monotonic() - t0,
            retry_reasons=list(retry_reasons), finish_reason=finish, redaction_status=redaction,
            final_status=final_status, attempt_records=list(attempts))
        # extra reasoning/cache accounting attached (kept out of the frozen dataclass to not break it)
        rec.reasoning_tokens = reasoning_tokens
        rec.cached_input_tokens = cached_input_tokens
        return rec
