"""Full reindex + pre-swap validation + atomic alias swap + rollback. The rebuild targets a fresh
collection; the live pointer flips only after validation passes, a corrupt shadow never swaps, and rollback
restores the previous collection instantly."""
import uuid
import pytest
from conftest import run, eng, mk_record, seed_contract_version, grant_repo_read
from enterprise_memory.indexing.models import SHARED, SHARED_COLLECTION
from enterprise_memory.indexing.canonical_loaders import embed_text
from enterprise_memory.indexing.validated_search import validated_search
from enterprise_memory.indexing import reindex as R

pytestmark = pytest.mark.qdrant
QUERY = "retry once with backoff"


def test_full_reindex_validate_swap_and_rollback(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        _, v1, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "n": 1})
        _, v2, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "n": 2})
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()

        reng = eng("index")
        report = await R.full_reindex(reng, index, embedder, SHARED, [{"org_id": a["org"]}], suffix="b1")
        assert report.indexed == 2 and report.validation["ok"] is True
        assert report.new_collection == SHARED_COLLECTION + "_b1"
        assert await index.resolve(SHARED) == report.new_collection          # alias flipped after validation
        assert report.previous_collection == SHARED_COLLECTION

        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY,
                                     limit=10, user_id=str(a["user"]))
        assert {h.canonical_version_id for h in res.hits} == {v1, v2}

        await R.rollback(index, SHARED, report)                              # instant rollback
        assert await index.resolve(SHARED) == SHARED_COLLECTION
        res2 = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose(); await reng.dispose()
        assert res2.hits == []
    run(body())


def test_corrupt_shadow_blocks_swap(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "n": 1})
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()

        async def corrupt(idx, collection):                                  # inject an extra ghost point
            ghost = mk_record(SHARED, canonical_version_id=str(uuid.uuid4()), org_id=a["org"],
                              content_hash="h", contract_id=str(uuid.uuid4()), repository_id=a["repo"])
            await idx.upsert([ghost], embedder.embed([ghost.text]), collection=collection)

        reng = eng("index")
        with pytest.raises(R.ReindexValidationError):
            await R.full_reindex(reng, index, embedder, SHARED, [{"org_id": a["org"]}], suffix="bad",
                                 after_build=corrupt)
        await reng.dispose()
        assert await index.resolve(SHARED) == SHARED_COLLECTION              # live alias UNCHANGED
    run(body())
