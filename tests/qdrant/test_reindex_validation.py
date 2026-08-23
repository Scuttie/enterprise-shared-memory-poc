"""Pre-swap reindex validation (P2.1 §6) — pure index, no PostgreSQL. validate_shadow must detect a
corrupt shadow collection so a bad rebuild can never swap the live alias."""
from conftest import run, mk_record
from enterprise_memory.indexing.models import SHARED, SHARED_COLLECTION
from enterprise_memory.indexing.reindex import validate_shadow


def _rec(vid, h, **kw):
    return mk_record(SHARED, canonical_version_id=vid, org_id="o1", content_hash=h, contract_id="c",
                     repository_id="r1", **kw)


def test_validate_shadow_clean(index, embedder):
    async def body():
        shadow = SHARED_COLLECTION + "_s1"
        await index.create_collection(shadow)
        recs = [_rec("v1", "h1"), _rec("v2", "h2")]
        await index.upsert(recs, embedder.embed([r.text for r in recs]), collection=shadow)
        v = await validate_shadow(index, embedder, SHARED, shadow, recs)
        assert v.ok and v.expected == 2 and v.actual == 2 and v.representative_search_ok
    run(body())


def test_validate_shadow_detects_missing_extra_hash_schema(index, embedder):
    async def body():
        shadow = SHARED_COLLECTION + "_s2"
        await index.create_collection(shadow)
        r1, r2 = _rec("v1", "h1"), _rec("v2", "h2")            # expected set
        bad_v1 = _rec("v1", "WRONG", index_schema_version=999)  # same pid as r1: wrong hash + bad schema
        ghost = _rec("gz", "h")                                 # extra; v2 is missing
        await index.upsert([bad_v1, ghost], embedder.embed([bad_v1.text, ghost.text]), collection=shadow)
        v = await validate_shadow(index, embedder, SHARED, shadow, [r1, r2])
        assert not v.ok
        assert "v1" in v.wrong_hash and "v1" in v.wrong_schema
        assert "gz" in v.extra and "v2" in v.missing
    run(body())
