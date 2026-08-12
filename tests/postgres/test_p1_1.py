"""P1.1 hardening tests: 0002 tables, tenant-consistent composite FKs (DB-level), real immutability
triggers, optimistic concurrency, supersession-cycle rejection, SECURITY DEFINER ACL, privilege matrix,
true concurrent claim, concurrent idempotency, job/outbox lifecycle."""
import asyncio
import uuid
import pytest
from sqlalchemy import text
from conftest import eng, run, tenant_tx
from enterprise_memory.persistence.postgres import (create_job, claim_job, heartbeat, transition,
                                                    publish_outbox, claim_outbox_event, mark_retry)

pytestmark = pytest.mark.postgres

_NEW = ["teams", "team_memberships", "promotion_decisions", "replay_evidence", "artifacts"]


def test_0002_tables_forced_rls():
    async def body():
        e = eng("postgres")
        async with e.connect() as c:
            rows = (await c.execute(text("SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity"
                                         " AND relname = ANY(:x)"), {"x": _NEW})).fetchall()
            assert {r[0] for r in rows} == set(_NEW)
        await e.dispose()
    run(body())


def test_composite_fk_blocks_cross_org(seeded):
    async def body():
        e = eng("postgres")   # superuser: bypasses RLS so the DB CONSTRAINT (not RLS) is what fires
        with pytest.raises(Exception):
            async with e.begin() as c:
                # org A job referencing a user from org B -> composite FK (org_id, submitter_user_id) fails
                await c.execute(text("INSERT INTO solve_jobs(org_id,submitter_user_id,repository_id,logical_request_id,spec_json)"
                                     " VALUES(:o,:u,:r,'lrq','{}')"),
                                {"o": seeded["A"]["org"], "u": seeded["B"]["user"], "r": seeded["A"]["repo"]})
        await e.dispose()
    run(body())


def test_contract_version_immutable_trigger(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]; cid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await c.execute(text("INSERT INTO memory_contracts(id,org_id) VALUES(:i,:o)"), {"i": cid, "o": a["org"]})
            await c.execute(text("INSERT INTO memory_contract_versions(contract_id,org_id,version_number,canonical_json,content_hash)"
                                 " VALUES(:c,:o,1,'{}','h1')"), {"c": cid, "o": a["org"]})
        with pytest.raises(Exception):   # UPDATE denied by trigger (not just uniqueness)
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("UPDATE memory_contract_versions SET content_hash='x' WHERE contract_id=:c"), {"c": cid})
        with pytest.raises(Exception):   # DELETE denied by trigger
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("DELETE FROM memory_contract_versions WHERE contract_id=:c"), {"c": cid})
        await e.dispose()
    run(body())


def test_optimistic_concurrency(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]; cid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await c.execute(text("INSERT INTO memory_contracts(id,org_id,optimistic_version) VALUES(:i,:o,1)"), {"i": cid, "o": a["org"]})
        async with tenant_tx(e, a["org"], a["user"]) as c:
            r = await c.execute(text("UPDATE memory_contracts SET optimistic_version=optimistic_version+1"
                                     " WHERE id=:i AND optimistic_version=1"), {"i": cid})
            assert r.rowcount == 1
        async with tenant_tx(e, a["org"], a["user"]) as c:
            r = await c.execute(text("UPDATE memory_contracts SET optimistic_version=optimistic_version+1"
                                     " WHERE id=:i AND optimistic_version=1"), {"i": cid})   # stale expected version
            assert r.rowcount == 0
        await e.dispose()
    run(body())


def test_supersession_self_cycle_rejected(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]; cid = uuid.uuid4(); vid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await c.execute(text("INSERT INTO memory_contracts(id,org_id) VALUES(:i,:o)"), {"i": cid, "o": a["org"]})
        with pytest.raises(Exception):   # supersedes_version_id == id -> CHECK violation
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,content_hash,supersedes_version_id)"
                                     " VALUES(:v,:c,:o,1,'{}','h',:v)"), {"v": vid, "c": cid, "o": a["org"]})
        await e.dispose()
    run(body())


def test_security_definer_acl_and_owner():
    async def body():
        su = eng("postgres")
        async with su.connect() as c:
            owner = (await c.execute(text(
                "SELECT r.rolname, r.rolsuper, r.rolcanlogin FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner"
                " WHERE p.proname='claim_next_job'"))).first()
            assert owner[0] == "job_dispatcher_owner" and owner[1] is False and owner[2] is False
            # ACL: PUBLIC has no EXECUTE; worker_service does; api_service does not
            assert (await c.execute(text("SELECT has_function_privilege('worker_service','claim_next_job(text,integer)','EXECUTE')"))).scalar() is True
            assert (await c.execute(text("SELECT has_function_privilege('api_service','claim_next_job(text,integer)','EXECUTE')"))).scalar() is False
            assert (await c.execute(text("SELECT has_function_privilege('audit_reader','claim_next_job(text,integer)','EXECUTE')"))).scalar() is False
        await su.dispose()
    run(body())


def test_privilege_matrix():
    async def body():
        su = eng("postgres")
        async with su.connect() as c:
            def q(role, tbl, priv):
                return c.execute(text("SELECT has_table_privilege(:r,:t,:p)"), {"r": role, "t": tbl, "p": priv})
            assert (await q("api_service", "memory_contract_versions", "INSERT")).scalar() is True
            assert (await q("api_service", "memory_contract_versions", "UPDATE")).scalar() is False
            assert (await q("api_service", "memory_contract_versions", "DELETE")).scalar() is False
            assert (await q("api_service", "outbox_events", "DELETE")).scalar() is False
            assert (await q("api_service", "organisations", "INSERT")).scalar() is False
            assert (await q("audit_reader", "audit_events", "SELECT")).scalar() is True
            assert (await q("audit_reader", "audit_events", "INSERT")).scalar() is False
        await su.dispose()
    run(body())


def test_true_concurrent_claim(seeded):
    async def body():
        a = seeded["A"]; su = eng("postgres"); jid = uuid.uuid4()
        async with su.begin() as c:
            await c.execute(text("INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,spec_json)"
                                 " VALUES(:i,:o,:u,:r,'lrq','{}')"), {"i": jid, "o": a["org"], "u": a["user"], "r": a["repo"]})
        w1, w2 = eng("worker"), eng("worker")
        conn1 = await w1.connect(); t1 = await conn1.begin()
        r1 = (await conn1.execute(text("SELECT job_id FROM claim_next_job('cw1',30)"))).first()   # locks the row
        conn2 = await w2.connect(); t2 = await conn2.begin()
        r2 = (await conn2.execute(text("SELECT job_id FROM claim_next_job('cw2',30)"))).first()   # SKIP LOCKED -> empty
        await t1.commit(); await conn1.close()
        await t2.commit(); await conn2.close()
        assert r1 is not None and r2 is None
        for x in (su, w1, w2):
            await x.dispose()
    run(body())


def test_concurrent_idempotent_create(seeded):
    async def body():
        a = seeded["A"]
        engines = [eng("api") for _ in range(8)]
        results = await asyncio.gather(*[create_job(en, a["org"], a["user"], a["repo"], {}, "cidem", "lrq") for en in engines])
        ids = {r[0] for r in results}
        assert len(ids) == 1 and sum(1 for r in results if r[1]) == 1   # one job, exactly one 'created'
        for en in engines:
            await en.dispose()
    run(body())


def test_job_lifecycle(seeded):
    async def body():
        a = seeded["A"]; api = eng("api"); w = eng("worker")
        jid, created = await create_job(api, a["org"], a["user"], a["repo"], {}, "life-1", "lrq")
        assert created
        claimed = await claim_job(w, "worker-1")
        assert claimed and claimed["job_id"] == jid
        await heartbeat(api, a["org"], jid, "worker-1")
        with pytest.raises(PermissionError):
            await heartbeat(api, a["org"], jid, "someone-else")
        assert await transition(api, a["org"], jid, "worker-1", "GENERATING") == "GENERATING"
        assert await transition(api, a["org"], jid, "worker-1", "TESTING") == "TESTING"
        assert await transition(api, a["org"], jid, "worker-1", "SUCCEEDED") == "SUCCEEDED"
        # terminal -> further transition rejected: SUCCEEDED cleared the lease (P2-0), so the owner check
        # (PermissionError) or the illegal-transition check (ValueError) both correctly reject it.
        with pytest.raises((ValueError, PermissionError)):
            await transition(api, a["org"], jid, "worker-1", "QUEUED")
        for x in (api, w):
            await x.dispose()
    run(body())


def test_outbox_lifecycle_quarantine(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]; aid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], "REINDEX", "contract", aid, 1, {})
        su = eng("postgres")                                 # set max_attempts low so two failures quarantine
        async with su.begin() as c:
            await c.execute(text("UPDATE outbox_events SET max_attempts=2 WHERE aggregate_id=:i"), {"i": aid})
        ev = await claim_outbox_event(e, a["org"], "ow1")
        assert ev and ev["aggregate_id"] == str(aid)
        # backoff 0 so the event is immediately re-claimable for the second failure
        assert await mark_retry(e, a["org"], ev["id"], "ow1", "transient", backoff_seconds=0) == "PENDING"
        ev2 = await claim_outbox_event(e, a["org"], "ow1")   # attempts now 2 == max
        assert ev2 is not None
        st = await mark_retry(e, a["org"], ev2["id"], "ow1", "transient again", backoff_seconds=0)
        assert st == "QUARANTINED"
        for x in (e, su):
            await x.dispose()
    run(body())
