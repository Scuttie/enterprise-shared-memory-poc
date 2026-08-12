"""Qdrant adapter: server-side org/owner filtering, scroll, delete, and reindex swap. Pure index — no
PostgreSQL. Runs in local :memory: mode (or against QDRANT_URL when set)."""
from conftest import run, DIM
from enterprise_memory.indexing.models import IndexRecord, PRIVATE, SHARED, SHARED_COLLECTION


def _rec(scope, oid, org, h, text, owner=None, ver=1):
    return IndexRecord(scope=scope, object_type=("private_episode" if scope == PRIVATE else "contract_version"),
                       object_id=oid, org_id=org, content_hash=h, text=text, owner_user_id=owner,
                       version_number=ver)


def test_org_and_owner_filter(index, embedder):
    async def body():
        rs = _rec(SHARED, "v1", "o1", "hs", "alpha retry backoff")
        rp = _rec(PRIVATE, "ep1", "o1", "hp", "alpha retry backoff", owner="u1")
        await index.upsert([rs], embedder.embed([rs.text]))
        await index.upsert([rp], embedder.embed([rp.text]))
        q = embedder.embed(["alpha retry backoff"])[0]
        assert [c.payload["object_id"] for c in await index.search(SHARED, q, "o1")] == ["v1"]
        assert len(await index.search(SHARED, q, "otherorg")) == 0          # org filter
        assert len(await index.search(PRIVATE, q, "o1", owner_user_id="u2")) == 0  # owner filter
        assert [c.payload["object_id"] for c in await index.search(PRIVATE, q, "o1", owner_user_id="u1")] == ["ep1"]
    run(body())


def test_payload_has_no_raw_text(index, embedder):
    async def body():
        rs = _rec(SHARED, "v1", "o1", "hs", "secret canonical body text")
        await index.upsert([rs], embedder.embed([rs.text]))
        q = embedder.embed(["secret canonical body text"])[0]
        cand = (await index.search(SHARED, q, "o1"))[0]
        assert "text" not in cand.payload and "secret canonical body text" not in str(cand.payload)
        assert cand.payload["content_hash"] == "hs"                          # only a reference remains
    run(body())


def test_delete_and_reindex_swap(index, embedder):
    async def body():
        rs = _rec(SHARED, "v1", "o1", "hs", "alpha retry backoff")
        await index.upsert([rs], embedder.embed([rs.text]))
        assert await index.count(SHARED) == 1
        await index.delete(SHARED, [rs.pid])
        assert await index.count(SHARED) == 0
        # build a fresh collection and swap the active pointer to it
        new = SHARED_COLLECTION + "_rebuild1"
        await index.create_collection(new)
        await index.upsert([rs], embedder.embed([rs.text]), collection=new)
        await index.swap(SHARED, new)
        assert await index.resolve(SHARED) == new and await index.count(SHARED) == 1
    run(body())
