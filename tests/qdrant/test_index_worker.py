"""Outbox index worker: canonical PostgreSQL changes are projected onto the index via durable outbox
events. Covers index / supersede / deprecate / delete semantics."""
import pytest
from sqlalchemy import text
from conftest import run, eng, seed_contract_version, seed_private, grant_repo_read
from enterprise_memory.persistence.tenant_context import tenant_tx
from enterprise_memory.persistence.postgres import publish_outbox
from enterprise_memory.indexing import index_worker as W
from enterprise_memory.indexing.models import SHARED, PRIVATE
from enterprise_memory.indexing.validated_search import validated_search

pytestmark = pytest.mark.qdrant
QUERY = "retry once with backoff"


async def _publish(org, user, event_type, aggregate_type, aggregate_id, version, payload):
    api = eng("api")
    async with tenant_tx(api, org, user) as c:
        await publish_outbox(c, org, event_type, aggregate_type, aggregate_id, version, payload)
    await api.dispose()


async def _search(index, embedder, scope, org, user):
    api = eng("api")
    res = await validated_search(api, index, embedder, scope, str(org), QUERY, user_id=str(user))
    await api.dispose()
    return res


def test_contract_index_then_supersede_then_deprecate(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        c1 = {"text": QUERY, "v": 1}
        cid, vid1, _ = await seed_contract_version(su, a["org"], a["repo"], c1, version_number=1)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()
        weng = eng("index")

        # index v1
        await _publish(a["org"], a["user"], W.CONTRACT_INDEX, "contract_version", vid1, 1, {})
        out = await W.drain(weng, index, embedder, "iw-1")
        assert any(r["action"] == "CONTRACT_INDEX:upserted" for r in out)
        r1 = await _search(index, embedder, SHARED, a["org"], a["user"])
        assert len(r1.hits) == 1 and r1.hits[0].canonical_version_id == vid1

        # supersede: v2 current, remove v1 point + add v2 point
        su = eng("postgres")
        _, vid2, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "v": 2},
                                                 version_number=2, contract_id=cid, supersedes=vid1)
        await su.dispose()
        await _publish(a["org"], a["user"], W.CONTRACT_SUPERSEDE, "contract_version", vid2, 2,
                       {"old_version_id": vid1, "old_version_number": 1})
        out2 = await W.drain(weng, index, embedder, "iw-1")
        assert any(r["action"] == "CONTRACT_SUPERSEDE:swapped" for r in out2)
        r2 = await _search(index, embedder, SHARED, a["org"], a["user"])
        assert len(r2.hits) == 1 and r2.hits[0].canonical_version_id == vid2 and r2.hits[0].canonical["v"] == 2

        # deprecate v2 -> point removed
        await _publish(a["org"], a["user"], W.CONTRACT_DEPRECATE, "contract_version", vid2, 2,
                       {"version_number": 2})
        await W.drain(weng, index, embedder, "iw-1")
        r3 = await _search(index, embedder, SHARED, a["org"], a["user"])
        await weng.dispose()
        assert r3.hits == []
    run(body())


def test_private_index_then_delete(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        canonical = {"text": QUERY}
        eid, _ = await seed_private(su, a["org"], a["user"], canonical, repo=a["repo"])
        await grant_repo_read(su, a["org"], a["repo"], a["user"])   # private recall re-checks repo read
        await su.dispose()
        weng = eng("index")
        await _publish(a["org"], a["user"], W.PRIVATE_INDEX, "private_episode", eid, 1,
                       {"owner_user_id": str(a["user"])})
        await W.drain(weng, index, embedder, "iw-p")
        r1 = await _search(index, embedder, PRIVATE, a["org"], a["user"])
        assert len(r1.hits) == 1 and r1.hits[0].canonical_version_id == eid

        await _publish(a["org"], a["user"], W.PRIVATE_DELETE, "private_episode", eid, 1,
                       {"owner_user_id": str(a["user"]), "version_number": 1})
        await W.drain(weng, index, embedder, "iw-p")
        r2 = await _search(index, embedder, PRIVATE, a["org"], a["user"])
        await weng.dispose()
        assert r2.hits == []
    run(body())


def test_worker_writes_index_audit(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        cid, vid, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY})
        await su.dispose()
        weng = eng("index")
        await _publish(a["org"], a["user"], W.CONTRACT_INDEX, "contract_version", vid, 1, {})
        await W.drain(weng, index, embedder, "iw-audit")
        async with tenant_tx(weng, a["org"]) as c:
            rows = (await c.execute(text("SELECT result, qdrant_operation, point_id, canonical_version_id"
                                         " FROM index_audit_events WHERE org_id=:o"), {"o": a["org"]})).fetchall()
        await weng.dispose()
        assert any(r[0] == "CONTRACT_INDEX:upserted" and r[1] == "upsert" and r[2] and str(r[3]) == vid
                   for r in rows)
    run(body())


def test_stale_index_event_does_not_overwrite_current(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        cid, v1, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "v": 1}, version_number=1)
        _, v2, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "v": 2},
                                               version_number=2, contract_id=cid, supersedes=v1)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()
        weng = eng("index")
        await _publish(a["org"], a["user"], W.CONTRACT_INDEX, "contract_version", v2, 2, {})   # index current v2
        await W.drain(weng, index, embedder, "iw-o")
        # a stale/reordered CONTRACT_INDEX for the superseded v1 arrives later
        await _publish(a["org"], a["user"], W.CONTRACT_INDEX, "contract_version", v1, 1, {})
        out = await W.drain(weng, index, embedder, "iw-o")
        assert any(r["action"] == "CONTRACT_INDEX:not_current_deleted" for r in out)
        r = await _search(index, embedder, SHARED, a["org"], a["user"])
        await weng.dispose()
        assert len(r.hits) == 1 and r.hits[0].canonical_version_id == v2   # current point never overwritten
    run(body())
