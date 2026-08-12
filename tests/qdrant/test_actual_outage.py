"""Actual Qdrant process outage/recovery (P2.1 §8). Distinct from the simulated adapter-failure test: this
stops and restarts the REAL digest-pinned Qdrant container. Runs only in ci-qdrant-outage (QDRANT_CONTAINER
set); skipped elsewhere. Proves an outage is a replayable backlog — the event stays PENDING, never processed,
and replays to exactly one point after recovery with canonical state intact."""
import os
import time
import subprocess
import urllib.request
import pytest
from conftest import run, eng, seed_contract_version, grant_repo_read
from enterprise_memory.persistence.tenant_context import tenant_tx
from enterprise_memory.persistence.postgres import publish_outbox
from enterprise_memory.indexing import index_worker as W
from enterprise_memory.indexing.models import SHARED
from enterprise_memory.indexing.validated_search import validated_search

pytestmark = pytest.mark.qdrant
CONTAINER = os.environ.get("QDRANT_CONTAINER")
QURL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QUERY = "retry once with backoff"


def _docker(*args):
    subprocess.run(["docker", *args], check=True)


def _wait_ready(tries=60):
    for _ in range(tries):
        for ep in ("/readyz", "/healthz", "/"):
            try:
                with urllib.request.urlopen(QURL + ep, timeout=2) as r:
                    if r.status < 500:
                        return True
            except Exception:
                pass
        time.sleep(1)
    raise RuntimeError("qdrant not ready after restart")


@pytest.mark.skipif(not CONTAINER, reason="actual-outage workflow only (QDRANT_CONTAINER set)")
def test_actual_container_outage_and_recovery(seeded, index, embedder):
    async def body():
        a = seeded["A"]; canonical = {"text": QUERY}
        su = eng("postgres")
        cid, vid, h = await seed_contract_version(su, a["org"], a["repo"], canonical)
        await grant_repo_read(su, a["org"], a["repo"], a["user"])
        await su.dispose()

        api = eng("api")
        async with tenant_tx(api, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], W.CONTRACT_INDEX, "contract_version", vid, 1, {})
        await api.dispose()

        weng = eng("index")
        _docker("stop", CONTAINER)                       # real outage
        try:
            r = await W.run_once(weng, index, embedder, "iw-actual")
            assert r["status"] == "PENDING"              # replayable, never marked processed
        finally:
            _docker("start", CONTAINER)
            _wait_ready()

        out = await W.drain(weng, index, embedder, "iw-actual")   # replay on recovery
        assert any(x["status"] == "PROCESSED" for x in out)
        assert await index.count(SHARED) == 1            # exactly one point, no duplicate
        api = eng("api")
        res = await validated_search(api, index, embedder, SHARED, str(a["org"]), QUERY, user_id=str(a["user"]))
        await api.dispose(); await weng.dispose()
        assert len(res.hits) == 1 and res.hits[0].canonical_version_id == vid
    run(body())
