"""P1 §18 — migrations, roles, RLS/tenant isolation, pool context, contract immutability."""
import uuid
import pytest
from sqlalchemy import text
from conftest import eng, run, tenant_tx

pytestmark = pytest.mark.postgres

_TENANT_TABLES = ["users", "repositories", "private_episodes", "memory_contracts",
                  "memory_contract_versions", "solve_jobs", "audit_events", "outbox_events"]


def test_tables_and_rls_forced():
    async def body():
        e = eng("postgres")
        async with e.connect() as c:
            for t in _TENANT_TABLES + ["organisations", "idempotency_keys"]:
                assert (await c.execute(text("SELECT to_regclass(:t)"), {"t": "public." + t})).scalar() is not None
            rows = (await c.execute(text(
                "SELECT relname FROM pg_class WHERE relrowsecurity AND relforcerowsecurity AND relname = ANY(:x)"),
                {"x": _TENANT_TABLES})).fetchall()
            assert {r[0] for r in rows} == set(_TENANT_TABLES)   # every tenant table has FORCE RLS
        await e.dispose()
    run(body())


def test_runtime_roles_have_no_bypassrls():
    async def body():
        e = eng("postgres")
        async with e.connect() as c:
            for role in ("api_service", "worker_service", "audit_reader"):
                bp = (await c.execute(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=:r"), {"r": role})).scalar()
                assert bp is False, role
        await e.dispose()
    run(body())


def test_org_isolation(seeded):
    async def body():
        e = eng("api")
        # api_service under org A context can see org A repo but not org B
        async with tenant_tx(e, seeded["A"]["org"]) as c:
            n_a = (await c.execute(text("SELECT count(*) FROM repositories"))).scalar()
            assert n_a == 1
        async with tenant_tx(e, seeded["B"]["org"]) as c:
            got = (await c.execute(text("SELECT external_repo_id FROM repositories"))).scalar()
            assert got == "repo-B"                       # only org B rows visible
        await e.dispose()
    run(body())


def test_private_episode_ownership_and_guessed_uuid(seeded):
    async def body():
        e = eng("api")
        epid = uuid.uuid4()
        # owner user1 inserts a private episode under org A + user1 context
        async with tenant_tx(e, seeded["A"]["org"], seeded["A"]["user"]) as c:
            await c.execute(text("INSERT INTO private_episodes(id,org_id,owner_user_id,canonical_json,content_hash)"
                                 " VALUES(:i,:o,:u,'{}','h')"), {"i": epid, "o": seeded["A"]["org"], "u": seeded["A"]["user"]})
        # user2 (same org) cannot read user1's private episode (RESTRICTIVE owner policy)
        async with tenant_tx(e, seeded["A"]["org"], seeded["A"]["user2"]) as c:
            assert (await c.execute(text("SELECT count(*) FROM private_episodes"))).scalar() == 0
        # org B cannot read it either
        async with tenant_tx(e, seeded["B"]["org"], seeded["B"]["user"]) as c:
            assert (await c.execute(text("SELECT count(*) FROM private_episodes WHERE id=:i"), {"i": epid})).scalar() == 0
        # owner can
        async with tenant_tx(e, seeded["A"]["org"], seeded["A"]["user"]) as c:
            assert (await c.execute(text("SELECT count(*) FROM private_episodes WHERE id=:i"), {"i": epid})).scalar() == 1
        await e.dispose()
    run(body())


def test_missing_and_malformed_context_fail_closed(seeded):
    async def body():
        e = eng("api")
        # no tenant context -> app.org_id empty -> nullif(...)::uuid is NULL -> no rows
        async with e.connect() as c:
            assert (await c.execute(text("SELECT count(*) FROM repositories"))).scalar() == 0
        # malformed uuid in context -> cast error -> fails closed (raises), never leaks rows
        async with e.connect() as c:
            await c.execute(text("SELECT set_config('app.org_id','not-a-uuid', true)"))
            with pytest.raises(Exception):
                await c.execute(text("SELECT count(*) FROM repositories"))
        await e.dispose()
    run(body())


def test_pool_reuse_no_tenant_leak(seeded):
    async def body():
        e = eng("api")   # pool_size small; alternate org A / B on reused connections
        for _ in range(4):
            async with tenant_tx(e, seeded["A"]["org"]) as c:
                assert (await c.execute(text("SELECT external_repo_id FROM repositories"))).scalar() == "repo-A"
            async with tenant_tx(e, seeded["B"]["org"]) as c:
                assert (await c.execute(text("SELECT external_repo_id FROM repositories"))).scalar() == "repo-B"
            # a borrow with NO context must see nothing (previous tenant did not leak)
            async with e.connect() as c:
                assert (await c.execute(text("SELECT count(*) FROM repositories"))).scalar() == 0
        await e.dispose()
    run(body())


def test_contract_version_immutability_and_optimistic(seeded):
    async def body():
        e = eng("api"); cid = uuid.uuid4()
        async with tenant_tx(e, seeded["A"]["org"], seeded["A"]["user"]) as c:
            await c.execute(text("INSERT INTO memory_contracts(id,org_id) VALUES(:i,:o)"), {"i": cid, "o": seeded["A"]["org"]})
            await c.execute(text("INSERT INTO memory_contract_versions(contract_id,org_id,version_number,canonical_json,content_hash)"
                                 " VALUES(:c,:o,1,'{}','h1')"), {"c": cid, "o": seeded["A"]["org"]})
        # duplicate (contract_id, content_hash) rejected -> immutable-content invariant
        with pytest.raises(Exception):
            async with tenant_tx(e, seeded["A"]["org"], seeded["A"]["user"]) as c:
                await c.execute(text("INSERT INTO memory_contract_versions(contract_id,org_id,version_number,canonical_json,content_hash)"
                                     " VALUES(:c,:o,2,'{}','h1')"), {"c": cid, "o": seeded["A"]["org"]})
        # duplicate version_number rejected
        with pytest.raises(Exception):
            async with tenant_tx(e, seeded["A"]["org"], seeded["A"]["user"]) as c:
                await c.execute(text("INSERT INTO memory_contract_versions(contract_id,org_id,version_number,canonical_json,content_hash)"
                                     " VALUES(:c,:o,1,'{}','h2')"), {"c": cid, "o": seeded["A"]["org"]})
        # optimistic bump of current_version_id succeeds once with expected version
        async with tenant_tx(e, seeded["A"]["org"], seeded["A"]["user"]) as c:
            vid = (await c.execute(text("SELECT id FROM memory_contract_versions WHERE contract_id=:c"), {"c": cid})).scalar()
            r = await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c AND current_version_id IS NULL"),
                                {"v": vid, "c": cid})
            assert r.rowcount == 1
        await e.dispose()
    run(body())
