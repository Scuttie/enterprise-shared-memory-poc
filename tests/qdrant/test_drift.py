"""Drift detector: the index is correct only if it mirrors the canonical CURRENT set. Detects
missing / stale / orphan points against PostgreSQL."""
import uuid
import pytest
from conftest import run, eng, mk_record, seed_contract_version
from enterprise_memory.indexing.models import SHARED
from enterprise_memory.indexing.canonical_loaders import embed_text
from enterprise_memory.indexing import drift as D

pytestmark = pytest.mark.qdrant


def _rec(a, cid, vid, h, canonical):
    return mk_record(SHARED, canonical_version_id=vid, org_id=a["org"], content_hash=h,
                     text=embed_text(canonical), contract_id=cid, repository_id=a["repo"])


def test_shared_drift_buckets(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        c1 = {"text": "one"}; c2 = {"text": "two"}
        cid1, v1, h1 = await seed_contract_version(su, a["org"], a["repo"], c1)
        cid2, v2, h2 = await seed_contract_version(su, a["org"], a["repo"], c2)
        await su.dispose()
        r1 = _rec(a, cid1, v1, h1, c1); r2 = _rec(a, cid2, v2, h2, c2)
        await index.upsert([r1], embedder.embed([r1.text]))
        await index.upsert([r2], embedder.embed([r2.text]))
        weng = eng("index")
        rep = await D.check_shared(weng, index, a["org"])
        assert not rep.has_drift and rep.canonical_count == 2 and rep.index_count == 2

        # stale: overwrite v1's point with a wrong hash (same pid)
        bad = mk_record(SHARED, canonical_version_id=v1, org_id=a["org"], content_hash="WRONG",
                        text=embed_text(c1), contract_id=cid1, repository_id=a["repo"])
        await index.upsert([bad], embedder.embed([bad.text]))
        # orphan: a point with no canonical object
        ghost = str(uuid.uuid4())
        gr = mk_record(SHARED, canonical_version_id=ghost, org_id=a["org"], content_hash="h",
                       text="x", contract_id=str(uuid.uuid4()), repository_id=a["repo"])
        await index.upsert([gr], embedder.embed([gr.text]))
        # missing: a canonical current version never indexed
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


def test_drift_extended_categories(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]; c1 = {"text": "one"}
        cid, v1, h1 = await seed_contract_version(su, a["org"], a["repo"], c1, version_number=1)
        # v2 becomes current -> v1 is superseded and no longer current
        await seed_contract_version(su, a["org"], a["repo"], {"text": "two"}, version_number=2,
                                    contract_id=cid, supersedes=v1)
        await su.dispose()
        # index the superseded v1 (version 1) and a duplicate of it (version 2, same canonical_version_id)
        r1 = _rec(a, cid, v1, h1, c1)
        dup = mk_record(SHARED, canonical_version_id=v1, org_id=a["org"], content_hash=h1,
                        text=embed_text(c1), contract_id=cid, repository_id=a["repo"], version_number=2)
        await index.upsert([r1], embedder.embed([r1.text]))
        await index.upsert([dup], embedder.embed([dup.text]))
        # an invalid-schema point for a ghost object
        gid = str(uuid.uuid4())
        bad = mk_record(SHARED, canonical_version_id=gid, org_id=a["org"], content_hash="h",
                        text="x", contract_id=cid, repository_id=a["repo"], index_schema_version=999)
        await index.upsert([bad], embedder.embed([bad.text]))

        weng = eng("index")
        rep = await D.check_shared(weng, index, a["org"])
        await weng.dispose()
        assert v1 in rep.superseded_searchable
        assert v1 in rep.duplicate
        assert gid in rep.invalid_schema
    run(body())
