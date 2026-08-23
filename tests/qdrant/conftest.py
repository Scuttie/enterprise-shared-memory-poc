"""P2 Qdrant/indexing test harness. Pure-index tests (embeddings, adapter, separation, governed Mem0
stub) need only qdrant-client and run in local :memory: mode. Integration tests (validated search, worker,
outage/replay, drift, reindex) additionally need PostgreSQL (DATABASE_URL) and are skipped without it.
Nothing here needs credentials, a company database, a company Qdrant, or a company identity."""
import os
import sys
import uuid
import json
import asyncio
import hashlib
import pytest
from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.persistence.database import make_engine            # noqa: E402
from enterprise_memory.persistence.tenant_context import tenant_tx        # noqa: E402
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder  # noqa: E402
from enterprise_memory.indexing.models import IndexRecord, ObjectType, PRIVATE, SHARED, INDEX_SCHEMA_VERSION  # noqa: E402
from enterprise_memory.indexing.canonical_loaders import embed_text        # noqa: E402

DIM = 64


def mk_record(scope, *, canonical_version_id, org_id, content_hash, text="alpha retry backoff",
              canonical_id=None, contract_id=None, version_number=1, owner_user_id=None,
              repository_id=None, object_kind=None, index_schema_version=INDEX_SCHEMA_VERSION,
              governance_state=None, valid_from=None, valid_until=None, path_scope=None):
    """Build an IndexRecord with new-schema fields; override any field to trigger a specific rejection."""
    if scope == SHARED:
        object_kind = object_kind or ObjectType.CONTRACT_VERSION.value
        canonical_id = canonical_id or contract_id or "c"
    else:
        object_kind = object_kind or ObjectType.PRIVATE_EPISODE.value
        canonical_id = canonical_id or canonical_version_id
    return IndexRecord(
        scope=scope, object_kind=object_kind, canonical_id=str(canonical_id),
        canonical_version_id=str(canonical_version_id), canonical_version_number=version_number,
        canonical_content_hash=content_hash, org_id=str(org_id), text=text,
        owner_user_id=(str(owner_user_id) if owner_user_id else None),
        repository_id=(str(repository_id) if repository_id else None),
        contract_id=(str(contract_id) if contract_id else None),
        index_schema_version=index_schema_version, governance_state=governance_state,
        valid_from=valid_from, valid_until=valid_until, path_scope=path_scope)
_CREDS = {"postgres": ("postgres", "postgres"), "api": ("api_service", "api_pw"),
          "worker": ("worker_service", "worker_pw"), "audit": ("audit_reader", "audit_pw"),
          "index": ("index_worker_service", "index_pw")}


def eng(role="api"):
    u, p = _CREDS[role]
    return make_engine(u, p)


def run(coro):
    return asyncio.run(coro)


def qdrant_available():
    try:
        import qdrant_client  # noqa
        return True
    except Exception:
        return False


def chash(canonical) -> str:
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def _require_qdrant():
    if not qdrant_available():
        pytest.skip("qdrant-client not installed (ci-qdrant only)")


@pytest.fixture
def embedder():
    return DeterministicTestEmbedder(DIM)


@pytest.fixture
def index():
    from enterprise_memory.indexing.qdrant_indexes import QdrantIndex
    ix = QdrantIndex.from_env(DIM)
    run(ix.reset_base())
    yield ix
    run(ix.close())


# ------------------------------------------------------------------ PostgreSQL fixtures (integration only)
def _need_db():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("no DATABASE_URL (ci-qdrant integration only)")


@pytest.fixture
def _clean():
    _need_db()

    async def _c():
        e = eng("postgres")
        async with e.begin() as conn:
            await conn.execute(text(
                "TRUNCATE solve_jobs, outbox_events, audit_events, memory_contracts,"
                " memory_contract_versions, contract_sources, private_episodes, idempotency_keys,"
                " repository_permissions, team_memberships, teams RESTART IDENTITY CASCADE"))
        await e.dispose()
    run(_c())
    yield


@pytest.fixture
def seeded(_clean):
    _need_db()

    async def _seed():
        e = eng("postgres")
        ids = {}
        async with e.begin() as c:
            for k in ("A", "B"):
                org, usr, usr2, repo = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                                {"i": org, "k": "org-%s-%s" % (k, org)})
                for u in (usr, usr2):
                    await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                                    {"i": u, "o": org, "s": "u-" + str(u)})
                await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                                {"i": repo, "o": org, "r": "repo-" + k})
                ids[k] = {"org": org, "user": usr, "user2": usr2, "repo": repo}
        await e.dispose()
        return ids
    return run(_seed())


async def seed_contract_version(su, org, repo, canonical, version_number=1, contract_id=None,
                                governance="promoted", make_current=True, supersedes=None,
                                valid_from=None, valid_until=None):
    """Insert (optionally a new) contract + a version; set current_version_id when make_current. valid_from/
    valid_until accept SQL interval expressions like \"now() + interval '1 day'\". Returns
    (contract_id, version_id, content_hash)."""
    vid = uuid.uuid4()
    h = chash(canonical)
    # valid_from/valid_until are trusted test-only SQL fragments (e.g. "now() + interval '1 day'"),
    # inlined because a bound param can't carry a SQL expression.
    vf = valid_from if valid_from else "NULL"
    vu = valid_until if valid_until else "NULL"
    async with su.begin() as c:
        if contract_id is None:
            contract_id = uuid.uuid4()
            await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                            {"i": contract_id, "o": org, "r": repo})
        await c.execute(text(
            "INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,"
            "content_hash,governance_state,supersedes_version_id,valid_from,valid_until)"
            " VALUES(:i,:c,:o,:n,cast(:j as jsonb),:h,:g,:s," + vf + "," + vu + ")"),
            {"i": vid, "c": contract_id, "o": org, "n": version_number,
             "j": json.dumps(canonical), "h": h, "g": governance, "s": supersedes})
        if make_current:
            await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                            {"v": vid, "c": contract_id})
    return str(contract_id), str(vid), h


async def seed_private(su, org, owner, canonical, repo=None):
    eid = uuid.uuid4()
    h = chash(canonical)
    async with su.begin() as c:
        await c.execute(text(
            "INSERT INTO private_episodes(id,org_id,owner_user_id,repository_id,canonical_json,content_hash)"
            " VALUES(:i,:o,:u,:r,cast(:j as jsonb),:h)"),
            {"i": eid, "o": org, "u": owner, "r": repo, "j": json.dumps(canonical), "h": h})
    return str(eid), h


async def grant_repo_read(su, org, repo, user_id):
    async with su.begin() as c:
        await c.execute(text(
            "INSERT INTO repository_permissions(org_id,repository_id,subject_type,subject_id,can_read)"
            " VALUES(:o,:r,'user',:u,true)"), {"o": org, "r": repo, "u": user_id})
