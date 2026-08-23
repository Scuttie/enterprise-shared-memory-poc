"""Qdrant adapter: server-side org/owner filtering, scroll, delete, and reindex swap. Pure index — no
PostgreSQL. Runs in local :memory: mode (or against QDRANT_URL when set)."""
from conftest import run, mk_record
from enterprise_memory.indexing.models import PRIVATE, SHARED, SHARED_COLLECTION


def test_org_and_owner_filter(index, embedder):
    async def body():
        rs = mk_record(SHARED, canonical_version_id="v1", org_id="o1", content_hash="hs")
        rp = mk_record(PRIVATE, canonical_version_id="ep1", org_id="o1", content_hash="hp", owner_user_id="u1")
        await index.upsert([rs], embedder.embed([rs.text]))
        await index.upsert([rp], embedder.embed([rp.text]))
        q = embedder.embed(["alpha retry backoff"])[0]
        assert [c.payload["canonical_version_id"] for c in await index.search(SHARED, q, "o1")] == ["v1"]
        assert len(await index.search(SHARED, q, "otherorg")) == 0          # org filter
        assert len(await index.search(PRIVATE, q, "o1", owner_user_id="u2")) == 0  # owner filter
        assert [c.payload["canonical_version_id"] for c in await index.search(PRIVATE, q, "o1", owner_user_id="u1")] == ["ep1"]
    run(body())


def test_payload_has_no_raw_text(index, embedder):
    async def body():
        rs = mk_record(SHARED, canonical_version_id="v1", org_id="o1", content_hash="hs",
                       text="secret canonical body text")
        await index.upsert([rs], embedder.embed([rs.text]))
        q = embedder.embed(["secret canonical body text"])[0]
        cand = (await index.search(SHARED, q, "o1"))[0]
        assert "text" not in cand.payload and "secret canonical body text" not in str(cand.payload)
        assert cand.payload["canonical_content_hash"] == "hs"                # only a reference remains
    run(body())


def test_delete_and_reindex_swap(index, embedder):
    async def body():
        rs = mk_record(SHARED, canonical_version_id="v1", org_id="o1", content_hash="hs")
        await index.upsert([rs], embedder.embed([rs.text]))
        assert await index.count(SHARED) == 1
        await index.delete(SHARED, [rs.pid])
        assert await index.count(SHARED) == 0
        new = SHARED_COLLECTION + "_rebuild1"
        await index.create_collection(new)
        await index.upsert([rs], embedder.embed([rs.text]), collection=new)
        await index.swap(SHARED, new)
        assert await index.resolve(SHARED) == new and await index.count(SHARED) == 1
    run(body())
