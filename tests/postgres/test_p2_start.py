"""P2-start residual lease/outbox invariants."""
import uuid
import pytest
from sqlalchemy import text
from conftest import eng, run, tenant_tx
from enterprise_memory.persistence.postgres import create_job, claim_job, heartbeat, claim_outbox_event, publish_outbox

pytestmark = pytest.mark.postgres


def test_heartbeat_requires_live_lease(seeded):
    async def body():
        a = seeded["A"]; api = eng("api"); w = eng("worker"); su = eng("postgres")
        jid, _ = await create_job(api, a["org"], a["user"], a["repo"], {}, "hb-1", "lrq")
        claimed = await claim_job(w, "hb-w")
        assert claimed and claimed["job_id"] == jid
        await heartbeat(api, a["org"], jid, "hb-w")                 # live lease -> ok
        with pytest.raises(ValueError):                            # excessive extension rejected
            await heartbeat(api, a["org"], jid, "hb-w", lease_seconds=99999)
        async with su.begin() as c:                                # expire the lease
            await c.execute(text("UPDATE solve_jobs SET lease_expires_at=now()-interval '1 hour' WHERE id=:i"), {"i": jid})
        with pytest.raises(PermissionError):                       # expired lease cannot be revived by the old worker
            await heartbeat(api, a["org"], jid, "hb-w")
        for x in (api, w, su):
            await x.dispose()
    run(body())


def test_outbox_skip_exhausted_and_auto_quarantine(seeded):
    async def body():
        e = eng("api"); idx = eng("index"); su = eng("postgres"); a = seeded["A"]; aid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], "REINDEX", "contract", aid, 1, {})
        async with su.begin() as c:
            await c.execute(text("UPDATE outbox_events SET max_attempts=1 WHERE aggregate_id=:i"), {"i": aid})
        ev = await claim_outbox_event(idx, "ow")                    # attempts -> 1 == max
        assert ev
        async with su.begin() as c:                                # expire the PROCESSING lease
            await c.execute(text("UPDATE outbox_events SET lease_expires_at=now()-interval '1 hour' WHERE id=:i"), {"i": ev["id"]})
        assert await claim_outbox_event(idx, "ow2") is None         # exhausted+expired -> not reclaimed
        async with su.connect() as c:                              # ...it was auto-quarantined
            st = (await c.execute(text("SELECT status, lease_owner FROM outbox_events WHERE id=:i"), {"i": ev["id"]})).first()
            assert st[0] == "QUARANTINED" and st[1] is None
        for x in (e, idx, su):
            await x.dispose()
    run(body())


def test_lease_state_constraint(seeded):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        with pytest.raises(Exception):   # PROCESSING with NULL lease violates the lease-state CHECK
            async with su.begin() as c:
                await c.execute(text("INSERT INTO outbox_events(org_id,event_type,aggregate_type,aggregate_id,aggregate_version,status)"
                                     " VALUES(:o,'REINDEX','contract',:i,1,'PROCESSING')"), {"o": a["org"], "i": uuid.uuid4()})
        await su.dispose()
    run(body())


def test_backoff_bounds_and_server_side_redaction(seeded):
    async def body():
        e = eng("api"); idx = eng("index"); su = eng("postgres"); a = seeded["A"]; aid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], "REINDEX", "contract", aid, 1, {})
        ev = await claim_outbox_event(idx, "ow")
        # backoff bounds enforced server-side
        for bad in (-1, 999999):
            with pytest.raises(Exception):
                async with idx.begin() as c:
                    await c.execute(text("SELECT retry_outbox_event(cast(:e as uuid),'ow',cast(:t as uuid),'x',:b)"),
                                    {"e": ev["id"], "t": ev["lease_token"], "b": bad})
        # direct function invocation with a secret-like string -> stored value is redacted server-side
        async with idx.begin() as c:
            await c.execute(text("SELECT retry_outbox_event(cast(:e as uuid),'ow',cast(:t as uuid),:err,0)"),
                            {"e": ev["id"], "t": ev["lease_token"], "err": "leak ghp_" + "a" * 36})
        async with su.connect() as c:
            stored = (await c.execute(text("SELECT error_detail_sanitized FROM outbox_events WHERE id=:i"), {"i": ev["id"]})).scalar()
            assert "ghp_" not in (stored or "") and "[REDACTED]" in (stored or "")
        for x in (e, idx, su):
            await x.dispose()
    run(body())
