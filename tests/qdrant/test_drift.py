"""Drift detector: the index is correct only if it mirrors the canonical CURRENT set. Detects
missing / stale / orphan points against PostgreSQL."""
import pytest
from conftest import run, eng, seed_contract_version
from enterprise_memory.indexing.models import IndexRecord, SHARED
from enterprise_memory.indexing.canonical_loaders import embed_text
from enterprise_memory.indexing import drift as D

pytestmark = pytest.mark.qdrant


def _rec(vid, org, cid, h, canonical, repo, ver=1):
    return IndexRecord(scope=SHARED, object_type="contract_version", object_id=vid, org_id=str(org),
                       content_hash=h, text=embed_text(canonical), contract_id=cid,
                       repository_id=str(repo), version_number=ver)


def test_shared_drift_buckets(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        c1 = {"text": "one"}; c2 = {"text": "two"}
        cid1, v1, h1 = await seed_contract_version(su, a["org"], a["repo"], c1)
        cid2, v2, h2 = await seed_contract_version(su, a["org"], a["repo"], c2)
        await su.dispose()
        # index both correctly -> no drift
        await index.upsert([_rec(v1, a["org"], cid1, h1, c1, a["repo"])], embedder.embed([embed_text(c1)]))
        await index.upsert([_rec(v2, a["org"], cid2, h2, c2, a["repo"])], embedder.embed([embed_text(c2)]))
        weng = eng("index")
        rep = await D.check_shared(weng, index, a["org"])
        assert not rep.has_drift and rep.canonical_count == 2 and rep.index_count == 2

        # introduce all three drift kinds
        # stale: overwrite v1's point with a wrong hash (same pid)
        await index.upsert([_rec(v1, a["org"], cid1, "WRONG", c1, a["repo"])], embedder.embed([embed_text(c1)]))
        # orphan: a point with no canonical object
        import uuid
        ghost = str(uuid.uuid4())
        await index.upsert([_rec(ghost, a["org"], str(uuid.uuid4()), "h", {"text": "x"}, a["repo"])],
                           embedder.embed(["x"]))
        # missing: a canonical current version that was never indexed
        su = eng("postgres")
        cid3, v3, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": "three"})
        await su.dispose()

        rep2 = await D.check_shared(weng, index, a["org"])
        await weng.dispose()
        assert rep2.has_drift
        assert v1 in rep2.stale_in_index
        assert ghost in rep2.orphan_in_index
        assert v3 in rep2.missing_in_index
    run(body())
