"""Qdrant outage/replay: when the index is unavailable the outbox event is retried (stays PENDING) and is
NEVER marked processed, so an outage is a replayable backlog, not data loss. When the index recovers the
event replays successfully."""
import pytest
from sqlalchemy import text
from conftest import run, eng, seed_contract_version, grant_repo_read
from enterprise_memory.persistence.tenant_context import tenant_tx
from enterprise_memory.persistence.postgres import publish_outbox
from enterprise_memory.indexing import index_worker as W
from enterprise_memory.indexing.models import SHARED
from enterprise_memory.indexing.validated_search import validated_search

pytestmark = pytest.mark.qdrant
QUERY = "retry once with backoff"


class OutageIndex:
    """Delegates to the real index but simulates a store outage on writes."""
    def __init__(self, real):
        self._r = real

    async def upsert(self, *a, **k):
        raise ConnectionError("qdrant unavailable")

    def __getattr__(self, name):
        return getattr(self._r, name)


def test_outage_retries_then_replays(seeded, index, embedder):
    async def body():
        su = eng("postgres"); a = seeded["A"]
        canonical = {"text": QUERY}
        cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], canonical)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()

        api = eng("api")
        async with tenant_tx(api, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], W.CONTRACT_INDEX, "contract_version", vid, 1, {})
        await api.dispose()

        weng = eng("index")
        # 1) outage: run_once fails the upsert -> event goes back to PENDING, not PROCESSED
        r = await W.run_once(weng, OutageIndex(index), embedder, "iw-out")
        assert r["status"] == "PENDING"
        su = eng("postgres")
        async with su.connect() as c:
            st = (await c.execute(text("SELECT status FROM outbox_events WHERE aggregate_id=:i"),
                                  {"i": vid})).scalar()
        await su.dispose()
        assert st == "PENDING"                     # never marked processed during the outage

        # 2) recovery: the same event replays successfully against the healthy index
        out = await W.drain(weng, index, embedder, "iw-out")
        await weng.dispose()
        assert any(x["status"] == "PROCESSED" for x in out)
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose()
        assert len(res.hits) == 1 and res.hits[0].canonical_version_id == vid
    run(body())
