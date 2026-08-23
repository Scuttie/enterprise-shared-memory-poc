"""P2.1 §9 real-Mem0 harness. Requires DATABASE_URL (PostgreSQL) and the mem0 extra (mem0ai + a HF
embedder). Credential-free: no Solar/company key, no company database. The LLM transport is spied and must
never be called under infer=False."""
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

_CREDS = {"postgres": ("postgres", "postgres"), "index": ("index_worker_service", "index_pw")}


def eng(role="index"):
    u, p = _CREDS[role]
    return make_engine(u, p)


def run(coro):
    return asyncio.run(coro)


def chash(canonical) -> str:
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def _require_db():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("no DATABASE_URL (ci-mem0 only)")


@pytest.fixture
def org_ids():
    async def _seed():
        e = eng("postgres")
        org, usr, repo = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with e.begin() as c:
            await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"),
                            {"i": org, "k": "org-mem0-%s" % org})
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"),
                            {"i": usr, "o": org, "s": "u-" + str(usr)})
            await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"),
                            {"i": repo, "o": org, "r": "repo-mem0"})
        await e.dispose()
        return {"org": org, "user": usr, "repo": repo}
    return run(_seed())


async def seed_contract(org, repo, canonical):
    vid = uuid.uuid4(); cid = uuid.uuid4(); h = chash(canonical)
    su = eng("postgres")
    async with su.begin() as c:
        await c.execute(text("INSERT INTO memory_contracts(id,org_id,repository_id) VALUES(:i,:o,:r)"),
                        {"i": cid, "o": org, "r": repo})
        await c.execute(text(
            "INSERT INTO memory_contract_versions(id,contract_id,org_id,version_number,canonical_json,"
            "content_hash,governance_state) VALUES(:i,:c,:o,1,cast(:j as jsonb),:h,'promoted')"),
            {"i": vid, "c": cid, "o": org, "j": json.dumps(canonical), "h": h})
        await c.execute(text("UPDATE memory_contracts SET current_version_id=:v WHERE id=:c"),
                        {"v": vid, "c": cid})
    await su.dispose()
    return str(cid), str(vid), h
