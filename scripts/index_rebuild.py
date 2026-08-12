#!/usr/bin/env python
"""P2 full index rebuild. Rebuilds one scope for one org into a FRESH collection from the canonical
PostgreSQL set, then atomically swaps the *_current alias/active pointer to it. The live collection is
never mutated, so a rollback is instantaneous. Prints a JSON report. The suffix names the new collection
deterministically (e.g. a build id) — never wall-clock — so rebuilds are reproducible. Never prints
secrets."""
import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.persistence.database import make_engine          # noqa: E402
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex, client_provenance  # noqa: E402
from enterprise_memory.indexing.embeddings import DeterministicTestEmbedder  # noqa: E402
from enterprise_memory.indexing import reindex as R                    # noqa: E402


def _engine():
    return make_engine(os.environ.get("INDEX_DB_USER", "index_worker_service"),
                       os.environ.get("INDEX_DB_PASSWORD", "index_pw"))


async def _run(args):
    engine = _engine()
    dim = int(os.environ.get("INDEX_DIM", "64"))
    index = QdrantIndex.from_env(dim)
    await index.ensure_collections()
    embedder = DeterministicTestEmbedder(dim)   # production wires a real embedder here (same interface)
    targets = [{"org_id": args.org, "user_id": args.user}]
    try:
        rep = await R.full_reindex(engine, index, embedder, args.scope, targets, args.suffix)
        out = rep.to_dict()
        out["index_provenance"] = client_provenance()
        out["embedder"] = embedder.provenance()
        return out
    finally:
        await engine.dispose()
        await index.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True)
    ap.add_argument("--scope", choices=["shared", "private"], default="shared")
    ap.add_argument("--user", default=None)
    ap.add_argument("--suffix", required=True, help="deterministic new-collection suffix (e.g. a build id)")
    args = ap.parse_args()
    if args.scope == "private" and not args.user:
        raise SystemExit("private rebuild requires --user")
    rep = asyncio.run(_run(args))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
