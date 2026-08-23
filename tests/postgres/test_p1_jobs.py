"""P1 §18 — durable jobs (idempotency, two-worker claim, lease recovery, dead-letter), transactional
outbox (atomicity, dedup, distinct versions, quarantine), audit append-only."""
import asyncio
import uuid
import json
import pytest
from sqlalchemy import text
from conftest import eng, run, tenant_tx
from enterprise_memory.persistence.postgres import create_job, claim_job, publish_outbox, emit_audit

pytestmark = pytest.mark.postgres


def test_job_idempotent_create(seeded):
    async def body():
        e = eng("api")
        a = seeded["A"]
        j1, c1 = await create_job(e, a["org"], a["user"], a["repo"], {"x": 1}, "idem-1", "lrq-1")
        j2, c2 = await create_job(e, a["org"], a["user"], a["repo"], {"x": 1}, "idem-1", "lrq-1")
        assert j1 == j2 and c1 is True and c2 is False    # duplicate -> same job, not created twice
        await e.dispose()
    run(body())


def test_two_workers_cannot_claim_one_job(seeded):
    async def body():
        a = seeded["A"]
        su = eng("postgres")
        jid = uuid.uuid4()
        async with su.begin() as c:                        # seed one QUEUED job (superuser)
            await c.execute(text("INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,spec_json)"
                                 " VALUES(:i,:o,:u,:r,'lrq','{}')"), {"i": jid, "o": a["org"], "u": a["user"], "r": a["repo"]})
        # deterministic safety invariant (§17: assert DB synchronization directly): once worker-1 claims
        # the job it becomes RETRIEVING+leased, so a second worker's claim finds nothing eligible.
        # dispose worker-1's engine so its commit is fully flushed before worker-2's separate connection reads.
        w1 = eng("worker")
        r1 = await claim_job(w1, "worker-1")
        await w1.dispose()
        w2 = eng("worker")
        r2 = await claim_job(w2, "worker-2")
        await w2.dispose()
        assert r1 is not None and r1["job_id"] == str(jid) and r2 is None   # exactly one worker claims it
        await su.dispose()
    run(body())


def test_expired_lease_recovery(seeded):
    async def body():
        a = seeded["A"]; su = eng("postgres"); w = eng("worker")
        jid = uuid.uuid4()
        async with su.begin() as c:
            await c.execute(text("INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,spec_json)"
                                 " VALUES(:i,:o,:u,:r,'lrq','{}')"), {"i": jid, "o": a["org"], "u": a["user"], "r": a["repo"]})
        first = await claim_job(w, "worker-1")
        assert first and first["job_id"] == str(jid)
        # a second claim finds nothing (leased + RETRIEVING)
        assert await claim_job(w, "worker-2") is None
        # expire the lease -> recoverable
        async with su.begin() as c:
            await c.execute(text("UPDATE solve_jobs SET lease_expires_at = now() - interval '1 hour' WHERE id=:i"), {"i": jid})
        recovered = await claim_job(w, "worker-2")
        assert recovered and recovered["job_id"] == str(jid) and recovered["attempt"] == 2
        for x in (su, w):
            await x.dispose()
    run(body())


def test_outbox_atomicity_rollback(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]; cid = uuid.uuid4()
        # canonical change + outbox event in one tx, then raise -> neither survives
        try:
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("INSERT INTO memory_contracts(id,org_id) VALUES(:i,:o)"), {"i": cid, "o": a["org"]})
                await publish_outbox(c, a["org"], "CONTRACT_INDEX", "contract", cid, 1, {"x": 1})
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        async with tenant_tx(e, a["org"], a["user"]) as c:
            assert (await c.execute(text("SELECT count(*) FROM memory_contracts WHERE id=:i"), {"i": cid})).scalar() == 0
            assert (await c.execute(text("SELECT count(*) FROM outbox_events WHERE aggregate_id=:i"), {"i": cid})).scalar() == 0
        await e.dispose()
    run(body())


def test_outbox_dedup_and_distinct_versions(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]; aid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], "CONTRACT_INDEX", "contract", aid, 1, {})
            await publish_outbox(c, a["org"], "CONTRACT_INDEX", "contract", aid, 1, {})   # dup composite -> no-op
            await publish_outbox(c, a["org"], "CONTRACT_INDEX", "contract", aid, 2, {})   # distinct version -> new
        async with tenant_tx(e, a["org"], a["user"]) as c:
            n = (await c.execute(text("SELECT count(*) FROM outbox_events WHERE aggregate_id=:i"), {"i": aid})).scalar()
            assert n == 2
        await e.dispose()
    run(body())


def test_api_cannot_mutate_outbox_state(seeded):
    # §2.3: the API role may publish (INSERT) an outbox event but may NOT change its processing state.
    # (proper quarantine via lease-token dispatch is covered in test_p1_1 / test_p2_0.)
    async def body():
        e = eng("api"); a = seeded["A"]; aid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], "REINDEX", "contract", aid, 1, {})   # api CAN publish
        with pytest.raises(Exception):                                             # api CANNOT mutate state
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("UPDATE outbox_events SET status='QUARANTINED' WHERE aggregate_id=:i"), {"i": aid})
        await e.dispose()
    run(body())


def test_audit_append_only(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await emit_audit(c, a["org"], "solve_outcome", "job", "j1", {"pass1": 1}, "genesis", "h1")
        # UPDATE denied (trigger)
        with pytest.raises(Exception):
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("UPDATE audit_events SET event_type='tamper' WHERE org_id=:o"), {"o": a["org"]})
        # DELETE denied (trigger)
        with pytest.raises(Exception):
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("DELETE FROM audit_events WHERE org_id=:o"), {"o": a["org"]})
        async with tenant_tx(e, a["org"], a["user"]) as c:
            assert (await c.execute(text("SELECT count(*) FROM audit_events WHERE org_id=:o"), {"o": a["org"]})).scalar() == 1
        await e.dispose()
    run(body())
