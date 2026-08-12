"""Full reindex + atomic alias swap + rollback. The rebuild targets a fresh collection; the live pointer
flips only after the build succeeds, and rollback restores the previous collection instantly."""
import pytest
from conftest import run, eng, seed_contract_version, grant_repo_read
from enterprise_memory.indexing.models import SHARED, SHARED_COLLECTION
from enterprise_memory.indexing.validated_search import validated_search
from enterprise_memory.indexing import reindex as R

pytestmark = pytest.mark.qdrant
QUERY = "retry once with backoff"


def test_full_reindex_swap_and_rollback(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        cid1, v1, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "n": 1})
        cid2, v2, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "n": 2})
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()

        reng = eng("index")
        report = await R.full_reindex(reng, index, embedder, SHARED, [{"org_id": a["org"]}], suffix="b1")
        await reng.dispose()
        assert report.indexed == 2
        assert report.new_collection == SHARED_COLLECTION + "_b1"
        assert await index.resolve(SHARED) == report.new_collection            # alias flipped to new collection
        assert report.previous_collection == SHARED_COLLECTION

        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY,
                                     limit=10, user_id=str(a["user"]))
        assert {h.canonical_version_id for h in res.hits} == {v1, v2}                     # served from the new collection

        # rollback restores the previous (empty) base collection instantly
        await R.rollback(index, SHARED, report)
        assert await index.resolve(SHARED) == SHARED_COLLECTION
        res2 = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose()
        assert res2.hits == []
    run(body())
