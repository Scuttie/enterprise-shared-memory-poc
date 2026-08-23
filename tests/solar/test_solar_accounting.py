"""Solar P4.1 §3-§4: hard logical deadline, per-attempt + all-outcome accounting, Retry-After clamp,
parser-failure accounting, bounded per-org limiter, interface conformance."""
import asyncio
import inspect
import pytest
from conftest import ok_body
from enterprise_memory.providers.solar import SolarProvider
from enterprise_memory.providers.base import (CodingModelProvider, ModelRequest, ProviderError, ParserError)

pytestmark = pytest.mark.solar
REQ = ModelRequest(messages=[{"role": "user", "content": "fix"}], max_output_tokens=32)


async def _noop(d):
    return None


def run(coro):
    return asyncio.run(coro)


def test_interface_conformance():
    assert issubclass(SolarProvider, CodingModelProvider)
    assert inspect.iscoroutinefunction(SolarProvider.generate)
    sig = inspect.signature(SolarProvider.generate)
    assert "logical_request_id" in sig.parameters and "org_id" in sig.parameters


def test_all_outcome_accounting_on_exhaustion(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 503, "body": {}})
        p = SolarProvider(fake_solar.base_url, "m", secret, max_attempts=3, sleep=_noop, rng=lambda: 0)
        try:
            await p.generate(REQ, logical_request_id="lr", org_id="o1")
            assert False, "should raise"
        except ProviderError as e:
            assert e.record is not None and e.record.final_status == "exhausted"
            assert len(e.record.attempt_records) == 3
            assert all(ar.error_code == "503" for ar in e.record.attempt_records)
            assert e.record.attempt_records[-1].retry_decision == "stop"
        await p.aclose()
    run(body())


def test_hard_deadline_bounds_total(fake_solar, secret):
    async def body():
        clk = {"t": 0.0}

        async def sleep(d):
            clk["t"] += d                                  # advance the logical clock by the (clamped) delay
        fake_solar.set_default({"status": 503, "body": {}})
        p = SolarProvider(fake_solar.base_url, "m", secret, max_attempts=20, total_deadline=1.0,
                          backoff_base=0.5, sleep=sleep, clock=lambda: clk["t"], rng=lambda: 0)
        try:
            await p.generate(REQ, logical_request_id="lr", org_id="o1")
            assert False
        except ProviderError as e:
            assert e.record.final_status == "deadline"     # not merely one large read timeout
            assert e.record.attempts < 20
        await p.aclose()
    run(body())


def test_retry_after_clamped_non_negative(fake_solar, secret):
    async def body():
        delays = []

        async def sleep(d):
            delays.append(d)
        fake_solar.program([{"status": 429, "headers": {"Retry-After": "-5"}, "body": {}},
                            {"status": 200, "body": ok_body()}])
        p = SolarProvider(fake_solar.base_url, "m", secret, max_attempts=3, sleep=sleep, rng=lambda: 0)
        resp, rec = await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
        assert resp.text == "PATCH-OK" and delays and delays[0] == 0.0   # negative Retry-After -> 0
    run(body())


def test_retry_after_clamped_to_max(fake_solar, secret):
    async def body():
        delays = []

        async def sleep(d):
            delays.append(d)
        fake_solar.program([{"status": 429, "headers": {"Retry-After": "999999"}, "body": {}},
                            {"status": 200, "body": ok_body()}])
        p = SolarProvider(fake_solar.base_url, "m", secret, max_attempts=3, retry_after_max=30.0,
                          total_deadline=1000.0, sleep=sleep, rng=lambda: 0)
        await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
        assert delays and delays[0] == 30.0                 # huge Retry-After clamped to retry_after_max
    run(body())


def test_parser_failure_accounted(fake_solar, secret):
    async def body():
        fake_solar.set_default({"status": 200, "body": "not-a-chat-object"})   # 200 but malformed
        p = SolarProvider(fake_solar.base_url, "m", secret, max_attempts=3, sleep=_noop)
        with pytest.raises(ParserError) as e:
            await p.generate(REQ, logical_request_id="lr", org_id="o1")
        await p.aclose()
        assert e.value.record.final_status == "parser" and e.value.record.parser_status == "error"
        assert fake_solar.count == 1                        # malformed 200 is NOT retried as transport
    run(body())


def test_per_org_limiter_bounded(fake_solar, secret):
    async def body():
        p = SolarProvider(fake_solar.base_url, "m", secret, max_attempts=1, max_org_limiters=4, sleep=_noop)
        for i in range(20):
            await p.generate(REQ, logical_request_id="l", org_id="org-%d" % i)
        await p.aclose()
        assert len(p._org_sem) <= 4                         # bounded/LRU, not unbounded growth
    run(body())
