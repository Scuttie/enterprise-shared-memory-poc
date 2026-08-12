"""P2-0 canonical-integrity + dispatcher/outbox hardening tests."""
import uuid
import pytest
from sqlalchemy import text
from conftest import eng, run, tenant_tx
from enterprise_memory.persistence.postgres import (claim_job, claim_outbox_event, mark_processed,
                                                    mark_retry, publish_outbox, redact)

pytestmark = pytest.mark.postgres


async def _mk_contract_version(c, org, contract_id, vid, vnum=1, supersedes=None):
    await c.execute(text("INSERT INTO memory_contracts(id,org_id) VALUES(:i,:o) ON CONFLICT DO NOTHING"), {"i": contract_id, "o": org})
    await c.execute(text("INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,content_hash,supersedes_version_id)"
                         " VALUES(:v,:c,:o,:n,'{}',:h,:s)"), {"v": vid, "c": contract_id, "o": org, "n": vnum, "h": "h" + str(vid)[:6], "s": supersedes})


def test_current_version_must_belong_to_same_contract(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]
        c1, v1, c2, v2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await _mk_contract_version(c, a["org"], c1, v1)
            await _mk_contract_version(c, a["org"], c2, v2)
        async with tenant_tx(e, a["org"], a["user"]) as c:                 # own version -> ok
            r = await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"), {"v": v1, "c": c1})
            assert r.rowcount == 1
        with pytest.raises(Exception):                                     # another contract's version -> FK reject
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"), {"v": v2, "c": c1})
        await e.dispose()
    run(body())


def test_current_version_cross_org_rejected(seeded):
    async def body():
        su = eng("postgres")   # superuser bypasses RLS so the FK (not RLS) is what fires
        cA, vA, cB, vB = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with su.begin() as c:
            await _mk_contract_version(c, seeded["A"]["org"], cA, vA)
            await _mk_contract_version(c, seeded["B"]["org"], cB, vB)
        with pytest.raises(Exception):
            async with su.begin() as c:
                await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"), {"v": vB, "c": cA})
        await su.dispose()
    run(body())


def test_supersession_linear_chain_and_cross_contract(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]
        c1, v1, v2, v3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:                 # linear chain valid
            await _mk_contract_version(c, a["org"], c1, v1, 1, None)
            await _mk_contract_version(c, a["org"], c1, v2, 2, v1)
            await _mk_contract_version(c, a["org"], c1, v3, 3, v2)
        c2, v2a = uuid.uuid4(), uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await _mk_contract_version(c, a["org"], c2, v2a, 1, None)
        with pytest.raises(Exception):                                     # supersede another contract's version
            async with tenant_tx(e, a["org"], a["user"]) as c:
                await _mk_contract_version(c, a["org"], c2, uuid.uuid4(), 2, v1)   # v1 belongs to c1
        await e.dispose()
    run(body())


def test_p11_tenant_fks(seeded):
    async def body():
        su = eng("postgres"); a, b = seeded["A"], seeded["B"]
        tid = uuid.uuid4()
        async with su.begin() as c:
            await c.execute(text("INSERT INTO teams(id,org_id,name) VALUES(:i,:o,'t')"), {"i": tid, "o": a["org"]})
        # team membership referencing org B user -> composite FK fails
        with pytest.raises(Exception):
            async with su.begin() as c:
                await c.execute(text("INSERT INTO team_memberships(org_id,team_id,user_id) VALUES(:o,:t,:u)"),
                                {"o": a["org"], "t": tid, "u": b["user"]})
        # artifact referencing org B job -> fails; first make an org-B job
        jb = uuid.uuid4()
        async with su.begin() as c:
            await c.execute(text("INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,spec_json)"
                                 " VALUES(:i,:o,:u,:r,'l','{}')"), {"i": jb, "o": b["org"], "u": b["user"], "r": b["repo"]})
        with pytest.raises(Exception):
            async with su.begin() as c:
                await c.execute(text("INSERT INTO artifacts(org_id,job_id,kind,object_key) VALUES(:o,:j,'k','x')"),
                                {"o": a["org"], "j": jb})
        # promotion decision referencing org B reviewer -> fails
        with pytest.raises(Exception):
            async with su.begin() as c:
                await c.execute(text("INSERT INTO promotion_decisions(org_id,outcome,decided_by) VALUES(:o,'PROMOTED',:u)"),
                                {"o": a["org"], "u": b["user"]})
        await su.dispose()
    run(body())


def test_claim_input_validation():
    async def body():
        w = eng("worker")
        for bad in ((-1,), (0,), (99999,)):
            with pytest.raises(Exception):
                await claim_job(w, "cw", lease_seconds=bad[0])
        with pytest.raises(Exception):
            async with w.begin() as c:
                await c.execute(text("SELECT * FROM claim_next_job('', 30)"))   # empty worker
        await w.dispose()
    run(body())


def test_claim_skips_cancelled_and_exhausted(seeded):
    async def body():
        a = seeded["A"]; su = eng("postgres"); w = eng("worker")
        cancel_j, exhaust_j, expired_dead = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with su.begin() as c:
            await c.execute(text("INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,spec_json,cancel_requested_at)"
                                 " VALUES(:i,:o,:u,:r,'l','{}',now())"), {"i": cancel_j, "o": a["org"], "u": a["user"], "r": a["repo"]})
            await c.execute(text("INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,spec_json,attempts,max_attempts)"
                                 " VALUES(:i,:o,:u,:r,'l','{}',3,3)"), {"i": exhaust_j, "o": a["org"], "u": a["user"], "r": a["repo"]})
            await c.execute(text("INSERT INTO solve_jobs(id,org_id,submitter_user_id,repository_id,logical_request_id,spec_json,state,attempts,max_attempts,lease_expires_at)"
                                 " VALUES(:i,:o,:u,:r,'l','{}','RETRIEVING',3,3,now()-interval '1 hour')"),
                            {"i": expired_dead, "o": a["org"], "u": a["user"], "r": a["repo"]})
        got = await claim_job(w, "cw")                       # only eligible jobs -> none of the three
        assert got is None
        async with su.connect() as c:                        # exhausted-expired swept to DEAD_LETTER
            st = (await c.execute(text("SELECT state FROM solve_jobs WHERE id=:i"), {"i": expired_dead})).scalar()
            assert st == "DEAD_LETTER"
        for x in (su, w):
            await x.dispose()
    run(body())


def test_outbox_lease_owner_enforced(seeded):
    async def body():
        e = eng("api"); a = seeded["A"]; aid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], "REINDEX", "contract", aid, 1, {})
        ev = await claim_outbox_event(e, a["org"], "owA")
        assert ev
        with pytest.raises(PermissionError):                 # worker B cannot process worker A's event
            await mark_processed(e, a["org"], ev["id"], "owB")
        await mark_processed(e, a["org"], ev["id"], "owA")   # owner ok
        with pytest.raises(PermissionError):                 # already processed -> not PROCESSING
            await mark_processed(e, a["org"], ev["id"], "owA")
        await e.dispose()
    run(body())


def test_error_redaction():
    assert "ghp_" not in redact("boom token=ghp_" + "a" * 36) and "[REDACTED]" in redact("x ghp_" + "a" * 36)
    assert "-----BEGIN" not in redact("-----BEGIN RSA PRIVATE KEY-----\nMII")
    assert redact("plain message") == "plain message"
