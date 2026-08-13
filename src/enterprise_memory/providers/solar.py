"""Async Solar coding-model provider (P4 §11-§12). One reusable async HTTP client per process; validated
settings; key from a SecretProvider (never logged/persisted/in exceptions). Timeouts (connect/read/write/
pool/total), bounded retries (408/429/selected-5xx/transport only) with exponential backoff + bounded jitter
+ Retry-After (bounded), a stable logical_request_id across attempts, per-org + global concurrency limits, a
circuit breaker with half-open recovery, accounting, redaction status, and graceful shutdown."""
from __future__ import annotations
import asyncio
import hashlib
import json
import random
import time
from datetime import datetime, timezone
from typing import Optional

from .base import (CodingModelProvider, ModelRequest, ModelResponse, ModelCallRecord, ProviderError,
                   AuthError, InvalidRequestError, ParserError, CircuitOpenError)
from .circuit import CircuitBreaker
from .redaction import sanitize

_RETRIABLE_5XX = {500, 502, 503, 504}


def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


class SolarProvider(CodingModelProvider):
    def __init__(self, base_url, model, secret_provider, *, key_name="SOLAR_API_KEY", temperature=0.0,
                 top_p=1.0, max_output_tokens=1024, connect_timeout=5.0, read_timeout=30.0,
                 write_timeout=10.0, pool_timeout=5.0, total_deadline=60.0, max_attempts=4, backoff_base=0.2,
                 backoff_max=8.0, retry_after_max=30.0, per_org_concurrency=4, global_concurrency=16,
                 breaker=None, client=None, sleep=asyncio.sleep, clock=time.monotonic, rng=None):
        self._base = base_url.rstrip("/")
        self._model = model
        self._secrets = secret_provider
        self._key_name = key_name
        self._temperature = temperature
        self._top_p = top_p
        self._max_out = max_output_tokens
        self._timeouts = dict(connect=connect_timeout, read=read_timeout, write=write_timeout,
                              pool=pool_timeout)
        self._total_deadline = total_deadline
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._retry_after_max = retry_after_max
        self._per_org = per_org_concurrency
        self._breaker = breaker or CircuitBreaker()
        self._client = client
        self._own_client = client is None
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.random
        self._global_sem = asyncio.Semaphore(global_concurrency)
        self._org_sem = {}

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeouts["read"], connect=self._timeouts["connect"],
                                      write=self._timeouts["write"], pool=self._timeouts["pool"]))
        return self._client

    def _org_semaphore(self, org_id):
        s = self._org_sem.get(org_id)
        if s is None:
            s = asyncio.Semaphore(self._per_org)
            self._org_sem[org_id] = s
        return s

    def _backoff(self, attempt, retry_after):
        if retry_after is not None:
            return min(float(retry_after), self._retry_after_max)
        base = min(self._backoff_max, self._backoff_base * (2 ** (attempt - 1)))
        return base + self._rng() * self._backoff_base    # bounded jitter

    @staticmethod
    def _retry_after(resp):
        v = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def generate(self, request: ModelRequest, *, logical_request_id: str, org_id: str):
        import httpx
        if not self._breaker.allow():
            raise CircuitOpenError("circuit_open")
        key = self._secrets.get_secret(self._key_name)    # never logged / never in exceptions
        payload = {"model": self._model, "messages": request.messages,
                   "temperature": request.temperature, "top_p": request.top_p,
                   "max_tokens": request.max_output_tokens}
        prompt_hash = _sha(json.dumps(payload["messages"], sort_keys=True))
        url = self._base + "/chat/completions"
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        retry_reasons = []
        started = self._clock()

        async with self._global_sem:
            async with self._org_semaphore(org_id):
                client = self._get_client()
                for attempt in range(1, self._max_attempts + 1):
                    if self._clock() - started > self._total_deadline:
                        self._breaker.on_failure()
                        raise ProviderError("total_deadline_exceeded")
                    try:
                        resp = await client.post(url, json=payload, headers=headers)
                    except (httpx.TimeoutException, httpx.TransportError) as e:
                        retry_reasons.append("transport:%s" % type(e).__name__)
                        if attempt < self._max_attempts:
                            await self._sleep(self._backoff(attempt, None)); continue
                        self._breaker.on_failure()
                        raise ProviderError("transport_failed")
                    status = resp.status_code
                    if status == 200:
                        return self._parse(resp, request, logical_request_id, prompt_hash, attempt,
                                           retry_reasons, started)
                    if status in (401, 403):
                        self._breaker.on_failure()                  # do NOT retry auth failures
                        raise AuthError("auth_failed:%d" % status)
                    if status == 400:
                        raise InvalidRequestError("invalid_request")   # do NOT retry (not a transport issue)
                    if status in (408, 429) or status in _RETRIABLE_5XX:
                        retry_reasons.append(str(status))
                        if attempt < self._max_attempts:
                            await self._sleep(self._backoff(attempt, self._retry_after(resp))); continue
                        self._breaker.on_failure()
                        raise ProviderError("exhausted:%d" % status)
                    self._breaker.on_failure()
                    raise ProviderError("unexpected_status:%d" % status)

    def _parse(self, resp, request, logical_request_id, prompt_hash, attempts, retry_reasons, started):
        try:
            data = resp.json()
            choice = data["choices"][0]
            text = choice["message"]["content"]
            finish = choice.get("finish_reason")
            returned_model = data.get("model")
            provider_request_id = data.get("id")
            usage = data.get("usage", {}) or {}
        except Exception:
            self._breaker.on_failure()
            raise ParserError("unparseable_response")
        self._breaker.on_success()
        _, redaction_status = sanitize(text)
        rec = ModelCallRecord(
            logical_request_id=logical_request_id, attempts=attempts, provider_request_id=provider_request_id,
            requested_model=self._model, returned_model=returned_model, prompt_hash=prompt_hash,
            response_hash=_sha(text), input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"), total_tokens=usage.get("total_tokens"),
            first_byte_latency=None, total_latency=self._clock() - started, retry_reasons=retry_reasons,
            finish_reason=finish, parser_status="ok", redaction_status=redaction_status,
            circuit_state=self._breaker.state,
            created_at=datetime.now(timezone.utc).isoformat())
        response = ModelResponse(text=text, finish_reason=finish, returned_model=returned_model,
                                 provider_request_id=provider_request_id,
                                 input_tokens=usage.get("prompt_tokens"),
                                 output_tokens=usage.get("completion_tokens"),
                                 total_tokens=usage.get("total_tokens"))
        return response, rec

    async def aclose(self):
        if self._own_client and self._client is not None:
            await self._client.aclose()
            self._client = None
