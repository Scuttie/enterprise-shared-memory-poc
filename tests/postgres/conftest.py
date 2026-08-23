"""P1 PostgreSQL integration test harness. Runs only when DATABASE_URL is set (ci-postgres). Engines
connect as the runtime roles (api_service/worker_service/audit_reader) so RLS actually applies; seeding
uses the superuser."""
import os
import sys
import asyncio
import uuid
import pytest
from sqlalchemy import text

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.persistence.database import make_engine          # noqa: E402
from enterprise_memory.persistence.tenant_context import tenant_tx      # noqa: E402

_CREDS = {"postgres": ("postgres", "postgres"), "api": ("api_service", "api_pw"),
          "worker": ("worker_service", "worker_pw"), "audit": ("audit_reader", "audit_pw"),
          "index": ("index_worker_service", "index_pw")}


def eng(role="api"):
    u, p = _CREDS[role]
    return make_engine(u, p)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _require_db():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("no DATABASE_URL (ci-postgres only)")


@pytest.fixture(autouse=True)
def _clean(_require_db):
    """Isolate tests: claim_next_job is cross-tenant, so leftover jobs from a prior test would be claimed.
    Truncate the transactional tables (as superuser) before each test; identity/org rows are per-test."""
    async def _c():
        e = eng("postgres")
        async with e.begin() as conn:
            await conn.execute(text(
                "TRUNCATE solve_jobs, outbox_events, audit_events, memory_contracts, private_episodes,"
                " idempotency_keys RESTART IDENTITY CASCADE"))
        await e.dispose()
    run(_c())
    yield


async def _seed():
    e = eng("postgres")
    ids = {}
    async with e.begin() as c:
        for k in ("A", "B"):
            org, usr, usr2, repo = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            await c.execute(text("INSERT INTO organisations(id,external_key) VALUES(:i,:k)"), {"i": org, "k": "org-%s-%s" % (k, org)})
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"), {"i": usr, "o": org, "s": "u1-" + k})
            await c.execute(text("INSERT INTO users(id,org_id,external_subject) VALUES(:i,:o,:s)"), {"i": usr2, "o": org, "s": "u2-" + k})
            await c.execute(text("INSERT INTO repositories(id,org_id,external_repo_id) VALUES(:i,:o,:r)"), {"i": repo, "o": org, "r": "repo-" + k})
            ids[k] = {"org": org, "user": usr, "user2": usr2, "repo": repo}
    await e.dispose()
    return ids


@pytest.fixture
def seeded():
    return run(_seed())
