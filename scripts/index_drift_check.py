#!/usr/bin/env python
"""P2 index drift check. Compares the Qdrant index against the canonical CURRENT set in PostgreSQL for one
org and scope, printing a JSON report and exiting non-zero on drift. PostgreSQL is authoritative; a
non-empty report means the projection pipeline is behind and the outbox should be replayed / a reindex run.
Credential-free defaults match the ci-qdrant roles; override via env. Never prints secrets."""
import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.persistence.database import make_engine          # noqa: E402
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex, client_provenance  # noqa: E402
from enterprise_memory.indexing import drift as D                      # noqa: E402


def _engine():
    return make_engine(os.environ.get("INDEX_DB_USER", "index_worker_service"),
                       os.environ.get("INDEX_DB_PASSWORD", "index_pw"))


async def _run(args):
    engine = _engine()
    index = QdrantIndex.from_env(int(os.environ.get("INDEX_DIM", "64")))
    try:
        if args.scope == "shared":
            rep = await D.check_shared(engine, index, args.org)
        else:
            if not args.user:
                raise SystemExit("private drift check requires --user")
            rep = await D.check_private(engine, index, args.org, args.user)
        out = rep.to_dict()
        out["index_provenance"] = client_provenance()
        return out
    finally:
        await engine.dispose()
        await index.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True)
    ap.add_argument("--scope", choices=["shared", "private"], default="shared")
    ap.add_argument("--user", default=None)
    args = ap.parse_args()
    rep = asyncio.run(_run(args))
    print(json.dumps(rep, indent=1))
    sys.exit(1 if rep["has_drift"] else 0)


if __name__ == "__main__":
    main()
