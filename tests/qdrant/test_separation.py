"""Physical private/shared separation: the two scopes live in different collections, so a private point
can NEVER be returned by a shared search (and vice versa), independent of the payload filter."""
from conftest import run
from enterprise_memory.indexing.models import (IndexRecord, PRIVATE, SHARED,
                                               PRIVATE_COLLECTION, SHARED_COLLECTION)


def test_collections_are_physically_distinct():
    assert PRIVATE_COLLECTION != SHARED_COLLECTION


def test_private_point_never_in_shared_search(index, embedder):
    async def body():
        # identical org + identical text in both scopes
        rp = IndexRecord(scope=PRIVATE, object_type="private_episode", object_id="ep1", org_id="o1",
                         content_hash="hp", text="shared secret phrase", owner_user_id="u1")
        rs = IndexRecord(scope=SHARED, object_type="contract_version", object_id="v1", org_id="o1",
                         content_hash="hs", text="shared secret phrase", contract_id="c1")
        await index.upsert([rp], embedder.embed([rp.text]))
        await index.upsert([rs], embedder.embed([rs.text]))
        q = embedder.embed(["shared secret phrase"])[0]
        shared = [c.payload["object_id"] for c in await index.search(SHARED, q, "o1")]
        private = [c.payload["object_id"] for c in await index.search(PRIVATE, q, "o1", owner_user_id="u1")]
        assert shared == ["v1"] and "ep1" not in shared          # private never leaks into shared
        assert private == ["ep1"] and "v1" not in private        # shared never leaks into private
    run(body())
