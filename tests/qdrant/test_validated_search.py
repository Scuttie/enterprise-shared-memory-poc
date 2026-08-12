"""Validated search end-to-end: PostgreSQL is authoritative. A candidate only becomes a hit after it is
reloaded from PostgreSQL and passes every gate; the returned content is the canonical row, never the index
payload. Each failure mode maps to an explicit RejectionReason."""
import pytest
from conftest import run, eng, seed_contract_version, seed_private, grant_repo_read
from enterprise_memory.indexing.models import IndexRecord, PRIVATE, SHARED, RejectionReason as RR
from enterprise_memory.indexing.canonical_loaders import embed_text
from enterprise_memory.indexing.validated_search import validated_search

pytestmark = pytest.mark.qdrant

QUERY = "retry once with backoff"


def _shared_rec(vid, org, cid, h, canonical, repo=None, ver=1):
    return IndexRecord(scope=SHARED, object_type="contract_version", object_id=vid, org_id=str(org),
                       content_hash=h, text=embed_text(canonical), contract_id=cid,
                       repository_id=(str(repo) if repo else None), version_number=ver)


def test_shared_returns_canonical_from_postgres(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        canonical = {"text": QUERY, "k": 1}
        cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], canonical)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()
        rec = _shared_rec(vid, a["org"], cid, h, canonical, repo=a["repo"])
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY,
                                     limit=5, user_id=str(a["user"]))
        await api.dispose()
        assert len(res.hits) == 1
        assert res.hits[0].object_id == vid and res.hits[0].canonical == canonical
        assert res.hits[0].content_hash == h
    run(body())


def test_hash_mismatch_rejected(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        canonical = {"text": QUERY}
        cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], canonical)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()
        rec = _shared_rec(vid, a["org"], cid, "STALEHASH", canonical, repo=a["repo"])  # stale index
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose()
        assert res.hits == [] and RR.HASH_MISMATCH.value in res.reasons()
    run(body())


def test_not_current_version_rejected(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        c1 = {"text": QUERY, "v": 1}
        cid, vid1, h1 = await seed_contract_version(su, a["org"], a["repo"], c1, version_number=1)
        # v2 becomes current -> v1 is no longer current
        _, vid2, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "v": 2},
                                                 version_number=2, contract_id=cid, supersedes=vid1)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()
        rec = _shared_rec(vid1, a["org"], cid, h1, c1, repo=a["repo"], ver=1)  # index the stale v1
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose()
        assert res.hits == [] and RR.NOT_CURRENT_VERSION.value in res.reasons()
    run(body())


def test_deprecated_current_rejected(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        c1 = {"text": QUERY, "v": 1}
        cid, vid1, _ = await seed_contract_version(su, a["org"], a["repo"], c1, version_number=1)
        c2 = {"text": QUERY, "v": 2}
        _, vid2, h2 = await seed_contract_version(su, a["org"], a["repo"], c2, version_number=2,
                                                  contract_id=cid, supersedes=vid1, governance="deprecated")
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()
        rec = _shared_rec(vid2, a["org"], cid, h2, c2, repo=a["repo"], ver=2)  # current but deprecated
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose()
        assert res.hits == [] and RR.DEPRECATED.value in res.reasons()
    run(body())


def test_no_read_permission_then_granted(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        canonical = {"text": QUERY}
        cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], canonical)
        await su.dispose()
        rec = _shared_rec(vid, a["org"], cid, h, canonical, repo=a["repo"])
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        assert res.hits == [] and RR.NO_READ_PERMISSION.value in res.reasons()
        su2 = eng("postgres"); await grant_repo_read(su2, a["org"], a["repo"], a["user"]); await su2.dispose()
        res2 = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose()
        assert len(res2.hits) == 1 and res2.hits[0].object_id == vid
    run(body())


def test_not_in_postgres_rejected(seeded, index, embedder):
    async def body():
        import uuid
        a = seeded["A"]
        ghost = str(uuid.uuid4())
        rec = _shared_rec(ghost, a["org"], str(uuid.uuid4()), "h", {"text": QUERY}, repo=a["repo"])
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose()
        assert res.hits == [] and RR.NOT_IN_POSTGRES.value in res.reasons()
    run(body())


def test_cross_org_isolation(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]; b = seeded["B"]
        canonical = {"text": QUERY}
        cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], canonical)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()
        rec = _shared_rec(vid, a["org"], cid, h, canonical, repo=a["repo"])
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(b["org"]), QUERY, user_id=str(b["user"]))
        await api.dispose()
        assert res.hits == []                       # org B's search never sees org A's indexed contract
    run(body())


def test_private_owner_isolation(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        canonical = {"text": QUERY}
        eid, h = await seed_private(su, a["org"], a["user"], canonical, repo=a["repo"])
        await su.dispose()
        rec = IndexRecord(scope=PRIVATE, object_type="private_episode", object_id=eid, org_id=str(a["org"]),
                          content_hash=h, text=embed_text(canonical), owner_user_id=str(a["user"]),
                          repository_id=str(a["repo"]))
        await index.upsert([rec], embedder.embed([rec.text]))
        api = eng("api")
        owner = await validated_search(api, index, embedder, PRIVATE, str(a["org"]), QUERY,
                                       user_id=str(a["user"]))
        other = await validated_search(api, index, embedder, PRIVATE, str(a["org"]), QUERY,
                                       user_id=str(a["user2"]))
        await api.dispose()
        assert len(owner.hits) == 1 and owner.hits[0].object_id == eid and owner.hits[0].canonical == canonical
        assert other.hits == []                     # another user in the same org never sees the episode
    run(body())
