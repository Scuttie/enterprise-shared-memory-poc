"""Async Solar coding-model provider (P4 §11-§12 + P4.1 §3). One reusable async HTTP client per process;
key from a SecretProvider (never logged/persisted/in exceptions). A single ABSOLUTE logical deadline bounds
every attempt and every sleep; per-attempt timeout is the smaller of the read timeout and the remaining
budget. Bounded retries (408/429/selected-5xx/transport only) with exponential backoff + bounded, clamped
jitter/Retry-After; a stable logical_request_id; per-org + global concurrency (per-org limiter is bounded/
LRU); a circuit breaker with half-open recovery; per-attempt accounting + a final LogicalModelCall record on
EVERY outcome (attached to the raised error on failure); redaction status; graceful shutdown."""
from __future__ import annotations
import asyncio
import hashlib
import json
import random
import time
from collections import OrderedDict
from datetime import datetime, timezone

from .base import (CodingModelProvider, ModelRequest, ModelResponse, ModelCallRecord, AttemptRecord,
                   ProviderError, AuthError, InvalidRequestError, ParserError, CircuitOpenError)
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
                 max_org_limiters=1024, breaker=None, client=None, sleep=asyncio.sleep, clock=time.monotonic,
                 rng=None):
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
        self._max_org_limiters = max_org_limiters
        self._breaker = breaker or CircuitBreaker()
        self._client = client
        self._own_client = client is None
        self._sleep = sleep
        self._clock = clock
        self._rng = rng or random.random
        self._global_sem = asyncio.Semaphore(global_concurrency)
        self._org_sem = OrderedDict()

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
            while len(self._org_sem) > self._max_org_limiters:   # bounded/LRU: evict an idle limiter
                k, old = next(iter(self._org_sem.items()))
                if old._value != self._per_org:                  # in use -> keep; try next
                    self._org_sem.move_to_end(k)
                    if k == org_id:
                        break
                    continue
                self._org_sem.pop(k, None)
        else:
            self._org_sem.move_to_end(org_id)
        return s

    def _clamp_delay(self, delay):
        return max(0.0, min(float(delay), self._retry_after_max))

    def _backoff(self, attempt, retry_after):
        if retry_after is not None:
            return self._clamp_delay(retry_after)
        base = min(self._backoff_max, self._backoff_base * (2 ** (attempt - 1)))
        return max(0.0, base + self._rng() * self._backoff_base)   # bounded, non-negative jitter

    @staticmethod
    def _retry_after(resp):
        v = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _record(self, *, logical_request_id, prompt_hash, attempts, attempt_records, retry_reasons,
                started, final_status, response=None, redaction="clean"):
        r = response
        return ModelCallRecord(
            logical_request_id=logical_request_id, attempts=attempts,
            provider_request_id=(r.provider_request_id if r else None), requested_model=self._model,
            returned_model=(r.returned_model if r else None), prompt_hash=prompt_hash,
            response_hash=(_sha(r.text) if r else None), input_tokens=(r.input_tokens if r else None),
            output_tokens=(r.output_tokens if r else None), total_tokens=(r.total_tokens if r else None),
            first_byte_latency=None, total_latency=self._clock() - started, retry_reasons=retry_reasons,
            finish_reason=(r.finish_reason if r else None), parser_status=("ok" if final_status != "parser"
                                                                           else "error"),
            redaction_status=redaction, circuit_state=self._breaker.state,
            created_at=datetime.now(timezone.utc).isoformat(), final_status=final_status,
            attempt_records=attempt_records)

    async def generate(self, request: ModelRequest, *, logical_request_id: str, org_id: str):
        import httpx
        if not self._breaker.allow():
            rec = self._record(logical_request_id=logical_request_id, prompt_hash="", attempts=0,
                               attempt_records=[], retry_reasons=[], started=self._clock(),
                               final_status="circuit_open")
            raise CircuitOpenError("circuit_open", record=rec)
        key = self._secrets.get_secret(self._key_name)
        payload = {"model": self._model, "messages": request.messages, "temperature": request.temperature,
                   "top_p": request.top_p, "max_tokens": request.max_output_tokens}
        prompt_hash = _sha(json.dumps(payload["messages"], sort_keys=True))
        url = self._base + "/chat/completions"
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        retry_reasons, attempt_records = [], []
        started = self._clock()

        async with self._global_sem:
            async with self._org_semaphore(org_id):
                client = self._get_client()
                for attempt in range(1, self._max_attempts + 1):
                    remaining = self._total_deadline - (self._clock() - started)
                    if remaining <= 0:
                        self._breaker.on_failure()
                        raise ProviderError("total_deadline_exceeded", record=self._record(
                            logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempt - 1,
                            attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                            final_status="deadline"))
                    a_start = self._clock()
                    per_attempt_timeout = min(self._timeouts["read"], remaining)
                    try:
                        resp = await client.post(url, json=payload, headers=headers,
                                                 timeout=httpx.Timeout(per_attempt_timeout,
                                                                       connect=min(self._timeouts["connect"], remaining),
                                                                       write=self._timeouts["write"],
                                                                       pool=self._timeouts["pool"]))
                    except (httpx.TimeoutException, httpx.TransportError) as e:
                        delay = self._backoff(attempt, None)
                        last = attempt >= self._max_attempts
                        attempt_records.append(AttemptRecord(
                            attempt=attempt, start=a_start, end=self._clock(), exception=type(e).__name__,
                            retry_decision=("stop" if last else "retry"), retry_delay=(None if last else delay),
                            error_code="transport"))
                        retry_reasons.append("transport:%s" % type(e).__name__)
                        if not last:
                            await self._sleep(min(delay, max(0.0, self._total_deadline - (self._clock() - started))))
                            continue
                        self._breaker.on_failure()
                        raise ProviderError("transport_failed", record=self._record(
                            logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempt,
                            attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                            final_status="transport"))
                    status = resp.status_code
                    if status == 200:
                        return self._parse(resp, request, logical_request_id, prompt_hash, attempt,
                                           attempt_records, retry_reasons, started, a_start)
                    if status in (401, 403):
                        attempt_records.append(AttemptRecord(attempt=attempt, start=a_start, end=self._clock(),
                                                             status=status, retry_decision="stop",
                                                             error_code="auth"))
                        self._breaker.on_failure()
                        raise AuthError("auth_failed:%d" % status, record=self._record(
                            logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempt,
                            attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                            final_status="auth"))
                    if status == 400:
                        attempt_records.append(AttemptRecord(attempt=attempt, start=a_start, end=self._clock(),
                                                             status=status, retry_decision="stop",
                                                             error_code="invalid_request"))
                        raise InvalidRequestError("invalid_request", record=self._record(
                            logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempt,
                            attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                            final_status="invalid"))
                    if status in (408, 429) or status in _RETRIABLE_5XX:
                        delay = self._backoff(attempt, self._retry_after(resp))
                        last = attempt >= self._max_attempts
                        attempt_records.append(AttemptRecord(
                            attempt=attempt, start=a_start, end=self._clock(), status=status,
                            retry_decision=("stop" if last else "retry"), retry_delay=(None if last else delay),
                            error_code=str(status)))
                        retry_reasons.append(str(status))
                        if not last:
                            await self._sleep(min(delay, max(0.0, self._total_deadline - (self._clock() - started))))
                            continue
                        self._breaker.on_failure()
                        raise ProviderError("exhausted:%d" % status, record=self._record(
                            logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempt,
                            attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                            final_status="exhausted"))
                    attempt_records.append(AttemptRecord(attempt=attempt, start=a_start, end=self._clock(),
                                                         status=status, retry_decision="stop",
                                                         error_code="unexpected"))
                    self._breaker.on_failure()
                    raise ProviderError("unexpected_status:%d" % status, record=self._record(
                        logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempt,
                        attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                        final_status="transport"))

    def _parse(self, resp, request, logical_request_id, prompt_hash, attempts, attempt_records,
               retry_reasons, started, a_start):
        try:
            data = resp.json()
            choice = data["choices"][0]
            text = choice["message"]["content"]
            finish = choice.get("finish_reason")
            returned_model = data.get("model")
            provider_request_id = data.get("id")
            usage = data.get("usage", {}) or {}
        except Exception:
            # §3.4: a malformed 200 is NOT a transport retry — account, sanitize, normalize, update breaker.
            attempt_records.append(AttemptRecord(attempt=attempts, start=a_start, end=self._clock(),
                                                 status=200, retry_decision="stop", error_code="parser"))
            self._breaker.on_failure()
            raise ParserError("unparseable_response", record=self._record(
                logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempts,
                attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                final_status="parser"))
        self._breaker.on_success()
        _, redaction_status = sanitize(text)
        attempt_records.append(AttemptRecord(
            attempt=attempts, start=a_start, end=self._clock(), status=200, provider_request_id=provider_request_id,
            retry_decision="stop", input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens")))
        response = ModelResponse(text=text, finish_reason=finish, returned_model=returned_model,
                                 provider_request_id=provider_request_id,
                                 input_tokens=usage.get("prompt_tokens"),
                                 output_tokens=usage.get("completion_tokens"),
                                 total_tokens=usage.get("total_tokens"))
        rec = self._record(logical_request_id=logical_request_id, prompt_hash=prompt_hash, attempts=attempts,
                           attempt_records=attempt_records, retry_reasons=retry_reasons, started=started,
                           final_status="success", response=response, redaction=redaction_status)
        return response, rec

    async def aclose(self):
        if self._own_client and self._client is not None:
            await self._client.aclose()
            self._client = None
