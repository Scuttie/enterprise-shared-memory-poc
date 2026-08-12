"""Validated search end-to-end: PostgreSQL is authoritative. A candidate only becomes a hit after it is
reloaded from PostgreSQL and passes every gate; the returned content is the canonical row, never the index
payload. This exercises the full rejection matrix — each doctored candidate maps to one RejectionReason."""
import uuid
import pytest
from conftest import run, eng, mk_record, seed_contract_version, seed_private, grant_repo_read
from enterprise_memory.indexing.models import PRIVATE, SHARED, RejectionReason as RR
from enterprise_memory.indexing.canonical_loaders import embed_text
from enterprise_memory.indexing.validated_search import validated_search

pytestmark = pytest.mark.qdrant
QUERY = "retry once with backoff"


async def _seed_valid(a, canonical=None, **seed_kw):
    """Seed a current promoted contract with repo read granted to a['user']. Returns (cid, vid, h, canon)."""
    canonical = canonical or {"text": QUERY, "path_scope": ["src/**"]}
    su = eng("postgres")
    cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], canonical, **seed_kw)
    await grant_repo_read(su, a["org"], a["repo"], a["user"])
    await su.dispose()
    return cid, vid, h, canonical


async def _search(index, embedder, a, scope=SHARED, user=None, requested_path=None):
    api = eng("api")
    res = await validated_search(api, index, embedder, scope, str(a["org"]), QUERY,
                                 user_id=str(user or a["user"]), requested_path=requested_path)
    await api.dispose()
    return res


def _correct_shared(a, cid, vid, h, canonical, version_number=1):
    return mk_record(SHARED, canonical_version_id=vid, org_id=a["org"], content_hash=h,
                     text=embed_text(canonical), contract_id=cid, repository_id=a["repo"],
                     version_number=version_number)


def test_requires_authenticated_user(seeded, index, embedder):
    async def body():
        api = eng("api")
        with pytest.raises(ValueError):
            await validated_search(api, index, embedder, SHARED, str(seeded["A"]["org"]), QUERY, user_id=None)
        await api.dispose()
    run(body())


def test_shared_returns_canonical(seeded, index, embedder):
    async def body():
        a = seeded["A"]
        cid, vid, h, canon = await _seed_valid(a)
        rec = _correct_shared(a, cid, vid, h, canon)
        await index.upsert([rec], embedder.embed([rec.text]))
        res = await _search(index, embedder, a, requested_path="src/foo.py")
        assert len(res.hits) == 1
        hit = res.hits[0]
        assert hit.canonical_version_id == vid and hit.canonical == canon and hit.content_hash == h
    run(body())


def test_private_returns_canonical_and_owner_isolation(seeded, index, embedder):
    async def body():
        a = seeded["A"]; canonical = {"text": QUERY}
        su = eng("postgres"); eid, h = await seed_private(su, a["org"], a["user"], canonical, repo=a["repo"]); await su.dispose()
        rec = mk_record(PRIVATE, canonical_version_id=eid, org_id=a["org"], content_hash=h,
                        text=embed_text(canonical), owner_user_id=a["user"], repository_id=a["repo"])
        await index.upsert([rec], embedder.embed([rec.text]))
        owner = await _search(index, embedder, a, scope=PRIVATE, user=a["user"])
        other = await _search(index, embedder, a, scope=PRIVATE, user=a["user2"])
        assert len(owner.hits) == 1 and owner.hits[0].canonical_version_id == eid
        assert other.hits == []                          # store-side owner filter isolates
    run(body())


# ---- rejection matrix (seed a valid current contract, index ONE doctored point) --------------------
def _reject_case(seeded, index, embedder, doctor, reason, requested_path=None):
    async def body():
        a = seeded["A"]
        cid, vid, h, canon = await _seed_valid(a)
        rec = doctor(a, cid, vid, h, canon)
        await index.upsert([rec], embedder.embed([rec.text]), collection=rec_collection(index, rec))
        res = await _search(index, embedder, a, scope=SHARED, requested_path=requested_path)
        assert res.hits == [] and reason.value in res.reasons()
    run(body())


def rec_collection(index, rec):
    # a private-scoped doctored record is deliberately planted in the shared collection for SCOPE_MISMATCH
    return index.alias_for(SHARED) if rec.scope == PRIVATE else None


def test_schema_version_unknown(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text=embed_text(k), contract_id=c, repository_id=a["repo"],
                     index_schema_version=999), RR.SCHEMA_VERSION_UNKNOWN)


def test_wrong_object_kind(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text=embed_text(k), contract_id=c, repository_id=a["repo"],
                     object_kind="private_episode"), RR.WRONG_OBJECT_KIND)


def test_scope_mismatch(seeded, index, embedder):
    # a private-scoped payload planted into the shared collection
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(PRIVATE, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text=embed_text(k), owner_user_id=a["user"], repository_id=a["repo"]),
                 RR.SCOPE_MISMATCH)


def test_not_in_postgres(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=str(uuid.uuid4()),
                     org_id=a["org"], content_hash=h, text=embed_text(k), contract_id=c,
                     repository_id=a["repo"]), RR.NOT_IN_POSTGRES)


def test_wrong_repository(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text=embed_text(k), contract_id=c, repository_id=str(uuid.uuid4())),
                 RR.WRONG_REPOSITORY)


def test_version_mismatch(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text=embed_text(k), contract_id=c, repository_id=a["repo"],
                     version_number=999), RR.VERSION_MISMATCH)


def test_contract_mismatch(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text=embed_text(k), contract_id=str(uuid.uuid4()),
                     repository_id=a["repo"]), RR.CONTRACT_MISMATCH)


def test_hash_mismatch(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash="STALE", text=embed_text(k), contract_id=c, repository_id=a["repo"]),
                 RR.HASH_MISMATCH)


def test_retrieval_hash_mismatch(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text="a completely different retrieval text", contract_id=c,
                     repository_id=a["repo"]), RR.RETRIEVAL_HASH_MISMATCH)


def test_path_scope_mismatch(seeded, index, embedder):
    _reject_case(seeded, index, embedder,
                 lambda a, c, v, h, k: mk_record(SHARED, canonical_version_id=v, org_id=a["org"],
                     content_hash=h, text=embed_text(k), contract_id=c, repository_id=a["repo"]),
                 RR.PATH_SCOPE_MISMATCH, requested_path="docs/readme.md")   # canonical path_scope = src/**


def test_no_read_permission(seeded, index, embedder):
    async def body():
        a = seeded["A"]
        su = eng("postgres")
        cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY})
        await su.dispose()                                          # NO grant_repo_read
        rec = _correct_shared(a, cid, vid, h, {"text": QUERY})
        await index.upsert([rec], embedder.embed([rec.text]))
        res = await _search(index, embedder, a)
        assert res.hits == [] and RR.NO_READ_PERMISSION.value in res.reasons()
    run(body())


def test_not_current_version(seeded, index, embedder):
    async def body():
        a = seeded["A"]; c1 = {"text": QUERY}
        su = eng("postgres")
        cid, v1, h1 = await seed_contract_version(su, a["org"], a["repo"], c1, version_number=1)
        await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "v": 2}, version_number=2,
                                    contract_id=cid, supersedes=v1)
        await grant_repo_read(su, a["org"], a["repo"], a["user"]); await su.dispose()
        rec = _correct_shared(a, cid, v1, h1, c1)                   # index the now-stale v1
        await index.upsert([rec], embedder.embed([rec.text]))
        res = await _search(index, embedder, a)
        assert res.hits == [] and RR.NOT_CURRENT_VERSION.value in res.reasons()
    run(body())


def test_deprecated_current(seeded, index, embedder):
    async def body():
        a = seeded["A"]; c2 = {"text": QUERY}
        su = eng("postgres")
        cid, v1, _ = await seed_contract_version(su, a["org"], a["repo"], {"text": QUERY, "v": 1})
        _, v2, h2 = await seed_contract_version(su, a["org"], a["repo"], c2, version_number=2,
                                                contract_id=cid, supersedes=v1, governance="deprecated")
        await grant_repo_read(su, a["org"], a["repo"], a["user"]); await su.dispose()
        rec = _correct_shared(a, cid, v2, h2, c2, version_number=2)  # current but deprecated
        await index.upsert([rec], embedder.embed([rec.text]))
        res = await _search(index, embedder, a)
        assert res.hits == [] and RR.DEPRECATED.value in res.reasons()
    run(body())


def test_not_valid_yet(seeded, index, embedder):
    async def body():
        a = seeded["A"]; canon = {"text": QUERY}
        cid, vid, h, _ = await _seed_valid(a, canonical=canon, valid_from="now() + interval '1 day'")
        rec = _correct_shared(a, cid, vid, h, canon)
        await index.upsert([rec], embedder.embed([rec.text]))
        res = await _search(index, embedder, a)
        assert res.hits == [] and RR.NOT_VALID_YET.value in res.reasons()
    run(body())


def test_expired(seeded, index, embedder):
    async def body():
        a = seeded["A"]; canon = {"text": QUERY}
        cid, vid, h, _ = await _seed_valid(a, canonical=canon, valid_until="now() - interval '1 day'")
        rec = _correct_shared(a, cid, vid, h, canon)
        await index.upsert([rec], embedder.embed([rec.text]))
        res = await _search(index, embedder, a)
        assert res.hits == [] and RR.EXPIRED.value in res.reasons()
    run(body())


def test_cross_org_isolation(seeded, index, embedder):
    async def body():
        a = seeded["A"]; b = seeded["B"]
        cid, vid, h, canon = await _seed_valid(a)
        rec = _correct_shared(a, cid, vid, h, canon)
        await index.upsert([rec], embedder.embed([rec.text]))
        res = await _search(index, embedder, b, user=b["user"])     # org B searches
        assert res.hits == []                                       # never sees org A's contract
    run(body())
