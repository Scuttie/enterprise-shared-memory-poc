"""SolarProvider resilience/accounting/redaction (P4 §13). Fake in-process server; no real key, no network."""
import asyncio
import pytest
from conftest import ok_body
from enterprise_memory.providers.solar import SolarProvider
from enterprise_memory.providers.base import (ModelRequest, ProviderError, AuthError, InvalidRequestError,
                                              CircuitOpenError)
from enterprise_memory.providers.circuit import CircuitBreaker

pytestmark = pytest.mark.solar
REQ = ModelRequest(messages=[{"role": "user", "content": "fix the bug"}], max_output_tokens=64)


async def _noop_sleep(d):
    return None


def run(coro):
    return asyncio.run(coro)


def _prov(fake, secret, **kw):
    kw.setdefault("sleep", _noop_sleep)
    kw.setdefault("max_attempts", 3)
    return SolarProvider(fake.base_url, "solar-pro2-251215", secret, **kw)


def test_success_and_accounting(fake_solar, secret):
    async def body():
        p = _prov(fake_solar, secret)
        resp, rec = await p.generate(REQ, logical_request_id="lr-1", org_id="o1")
        await p.aclose()
        assert resp.text == "PATCH-OK" and resp.returned_model == "solar-pro2-251215"
        assert rec.total_tokens == 18 and rec.output_tokens == 7 and rec.logical_request_id == "lr-1"
        assert rec.attempts == 1 and rec.finish_reason == "stop" and rec.circuit_state == "closed"
    run(body())


def test_429_retry_after_then_success(fake_solar, secret):
    async def body():
        fake_solar.program([{"status": 429, "headers": {"Retry-After": "0"}, "body": {}},
                            {"status": 200, "body": ok_body()}])
        p = _prov(fake_solar, secret)
        resp, rec = await p.generate(REQ, logical_request_id="lr-2", org_id="o1")
        await p.aclose()
        assert resp.text == "PATCH-OK" and rec.attempts == 2 and "429" in rec.retry_reasons
    run(body())


def test_repeated_5xx_exhausts(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 503, "body": {}})
        p = _prov(fake_solar, secret, max_attempts=3)
        with pytest.raises(ProviderError):
            await p.generate(REQ, logical_request_id="lr-3", org_id="o1")
        await p.aclose()
        assert fake_solar.count == 3                      # bounded attempts
    run(body())


def test_no_retry_on_4xx(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 401, "body": {}})
        p = _prov(fake_solar, secret)
        with pytest.raises(AuthError):
            await p.generate(REQ, logical_request_id="lr", org_id="o1")
        fake_solar.set_default({"status": 400, "body": {}})
        with pytest.raises(InvalidRequestError):
            await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
        assert fake_solar.count == 2                       # one request each, no retries
    run(body())


def test_connect_failure(secret):
    async def body():
        p = SolarProvider("http://127.0.0.1:1/v1", "solar", secret, max_attempts=2, sleep=_noop_sleep)
        with pytest.raises(ProviderError):
            await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
    run(body())


def test_read_timeout(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 200, "delay": 0.5, "body": ok_body()})
        p = _prov(fake_solar, secret, read_timeout=0.15, max_attempts=2)
        with pytest.raises(ProviderError):
            await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
    run(body())


def test_circuit_opens_then_half_open_recovers(fake_solar, secret):
    async def body():
        clk = {"t": 0.0}
        b = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0, clock=lambda: clk["t"])
        p = _prov(fake_solar, secret, breaker=b, max_attempts=1, clock=lambda: clk["t"])
        fake_solar.set_default({"status": 503, "body": {}})
        with pytest.raises(ProviderError):
            await p.generate(REQ, logical_request_id="lr", org_id="o1")   # 1 failure -> open
        with pytest.raises(CircuitOpenError):
            await p.generate(REQ, logical_request_id="lr", org_id="o1")   # short-circuited
        clk["t"] = 20.0                                                    # past recovery timeout
        fake_solar.set_default({"status": 200, "body": ok_body()})
        resp, rec = await p.generate(REQ, logical_request_id="lr", org_id="o1")   # half-open -> success
        await p.aclose()
        assert resp.text == "PATCH-OK" and b.state == "closed"
    run(body())


def test_per_org_concurrency_serialises(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 200, "delay": 0.25, "body": ok_body()})
        p = _prov(fake_solar, secret, per_org_concurrency=1, global_concurrency=10)
        await asyncio.gather(p.generate(REQ, logical_request_id="a", org_id="o1"),
                             p.generate(REQ, logical_request_id="b", org_id="o1"))
        await p.aclose()
        assert fake_solar.max_concurrent == 1
    run(body())


def test_global_concurrency_limit(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 200, "delay": 0.25, "body": ok_body()})
        p = _prov(fake_solar, secret, per_org_concurrency=10, global_concurrency=1)
        await asyncio.gather(p.generate(REQ, logical_request_id="a", org_id="o1"),
                             p.generate(REQ, logical_request_id="b", org_id="o2"))
        await p.aclose()
        assert fake_solar.max_concurrent == 1
    run(body())


def test_cancellation(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 200, "delay": 1.0, "body": ok_body()})
        p = _prov(fake_solar, secret)
        t = asyncio.create_task(p.generate(REQ, logical_request_id="a", org_id="o1"))
        await asyncio.sleep(0.1)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        await p.aclose()
    run(body())


def test_secret_redaction_status(fake_solar, secret):
    async def body():
        leaked = "here is a token ghp_" + "A" * 36 + " do not store raw"
        fake_solar.set_default({"status": 200, "body": ok_body(content=leaked)})
        p = _prov(fake_solar, secret)
        resp, rec = await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
        assert rec.redaction_status == "redacted"          # accounting flags the secret
    run(body())


def test_sanitized_artifact_persistence(fake_solar, secret, tmp_path):
    async def body():
        from enterprise_memory.providers.redaction import sanitize
        from enterprise_memory.artifacts.store import LocalArtifactStore
        from enterprise_memory.artifacts import records as R
        leaked = "patch with ghp_" + "B" * 36
        fake_solar.set_default({"status": 200, "body": ok_body(content=leaked)})
        p = _prov(fake_solar, secret)
        resp, rec = await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
        sanitized, status = sanitize(resp.text)
        assert status == "redacted" and "ghp_" not in sanitized
        store = LocalArtifactStore(str(tmp_path / "s"))
        h = R.sha256_hex(sanitized.encode())
        key = R.content_key("o1", R.SANITIZED_MODEL_RESPONSE, h)
        store.put(key, sanitized.encode(), h)
        assert store.get(key).decode() == sanitized        # only the sanitized payload is stored
    run(body())
