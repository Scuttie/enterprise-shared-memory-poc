"""`enterprise-memory-index-worker` entrypoint — drains the transactional outbox onto the Qdrant index
(separate lifecycle from the API and the solve worker)."""
import asyncio
import os
import uuid

from ..persistence.database import make_engine
from ..indexing.qdrant_indexes import QdrantIndex
from ..indexing.embeddings import DeterministicTestEmbedder
from ..indexing import index_worker as W

DIM = int(os.environ.get("INDEX_DIM", "64"))


async def _loop(worker_id, poll_interval=0.5, max_iterations=None):
    engine = make_engine("index_worker_service", "index_pw")
    index = QdrantIndex.from_env(DIM)
    await index.ensure_ready()
    embedder = DeterministicTestEmbedder(DIM)
    i = 0
    try:
        while max_iterations is None or i < max_iterations:
            i += 1
            out = await W.drain(engine, index, embedder, worker_id, max_events=50)
            if not out:
                await asyncio.sleep(poll_interval)
    finally:
        await engine.dispose()
        await index.close()


def main():
    asyncio.run(_loop(os.environ.get("WORKER_ID", "index-worker-%s" % uuid.uuid4().hex[:8])))


if __name__ == "__main__":
    main()
