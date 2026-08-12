"""Async Qdrant index adapter (P2). Two PHYSICALLY separate collections — enterprise_private_v1 and
enterprise_shared_v1 — never one collection with a scope column: a private point can never surface in a
shared search because it lives in a different collection. Each scope has a *_current alias so a full
reindex can atomically swap to a freshly built collection and roll back. The stored payload is a reference
only (ids + content_hash); the coding model never sees index text. The sync qdrant-client is driven from a
worker thread so callers stay async. In CI a real digest-pinned qdrant service is used when QDRANT_URL is
set; otherwise an in-process local store keeps the suite hermetic."""
from __future__ import annotations
import asyncio
import os
from typing import List, Optional

from .models import (PRIVATE, SHARED, PRIVATE_COLLECTION, SHARED_COLLECTION,
                     PRIVATE_ALIAS, SHARED_ALIAS, ALIAS, Candidate, IndexRecord)


def client_provenance() -> dict:
    try:
        from importlib.metadata import version
        ver = version("qdrant-client")
    except Exception:
        ver = "unavailable"
    return {"qdrant_client_version": ver,
            "mode": "url" if os.environ.get("QDRANT_URL") else "local"}


class QdrantIndex:
    def __init__(self, client, dim: int, server: bool = True):
        self._c = client
        self.dim = dim
        self._server = server               # payload indexes / native aliases only apply to a real server
        # scope -> physical collection currently serving reads/writes; reindex swaps these.
        self._active = {PRIVATE: PRIVATE_COLLECTION, SHARED: SHARED_COLLECTION}

    @classmethod
    def from_env(cls, dim: int, url: Optional[str] = None):
        from qdrant_client import QdrantClient
        url = url or os.environ.get("QDRANT_URL")
        if url:
            return cls(QdrantClient(url=url, timeout=15.0), dim, server=True)
        return cls(QdrantClient(location=":memory:"), dim, server=False)

    def collection_for(self, scope: str) -> str:
        return self._active[scope]

    # ---------------------------------------------------------------- lifecycle (sync internals)
    def _create_collection(self, name: str):
        from qdrant_client import models as qm
        existing = {c.name for c in self._c.get_collections().collections}
        if name not in existing:
            self._c.create_collection(
                name, vectors_config=qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE))
            if self._server:                 # payload indexes are a no-op (and warn) in local mode
                for f in ("org_id", "owner_user_id", "object_type", "content_hash", "contract_id"):
                    try:
                        self._c.create_payload_index(name, field_name=f,
                                                     field_schema=qm.PayloadSchemaType.KEYWORD)
                    except Exception:
                        pass

    def _point_alias(self, alias: str, collection: str):
        from qdrant_client import models as qm
        try:
            self._c.update_collection_aliases(change_aliases_operations=[
                qm.CreateAliasOperation(create_alias=qm.CreateAlias(
                    collection_name=collection, alias_name=alias))])
        except Exception:
            pass  # local mode may not support aliases; _active is authoritative for our own reads

    def _ensure(self):
        self._create_collection(PRIVATE_COLLECTION)
        self._create_collection(SHARED_COLLECTION)
        self._point_alias(PRIVATE_ALIAS, self._active[PRIVATE])
        self._point_alias(SHARED_ALIAS, self._active[SHARED])

    def _upsert(self, records: List[IndexRecord], vectors: List[List[float]], collection: Optional[str] = None):
        from qdrant_client import models as qm
        if not records:
            return
        by_scope = {}
        for rec, vec in zip(records, vectors):
            coll = collection or self._active[rec.scope]
            by_scope.setdefault(coll, []).append(
                qm.PointStruct(id=rec.pid, vector=vec, payload=rec.payload()))
        for coll, pts in by_scope.items():
            self._c.upsert(coll, points=pts, wait=True)

    def _delete(self, scope: str, pids: List[str], collection: Optional[str] = None):
        from qdrant_client import models as qm
        coll = collection or self._active[scope]
        self._c.delete(coll, points_selector=qm.PointIdsList(points=list(pids)), wait=True)

    def _search(self, scope: str, vector: List[float], org_id: str,
                owner_user_id: Optional[str], limit: int):
        from qdrant_client import models as qm
        must = [qm.FieldCondition(key="org_id", match=qm.MatchValue(value=str(org_id)))]
        if owner_user_id is not None:  # private scope: store-side owner isolation (defence in depth)
            must.append(qm.FieldCondition(key="owner_user_id", match=qm.MatchValue(value=str(owner_user_id))))
        res = self._c.query_points(self._active[scope], query=vector,
                                   query_filter=qm.Filter(must=must), limit=limit, with_payload=True)
        return [Candidate(pid=str(p.id), score=float(p.score), payload=dict(p.payload or {}))
                for p in res.points]

    def _scroll(self, scope: str, collection: Optional[str] = None):
        coll = collection or self._active[scope]
        out, offset = [], None
        while True:
            pts, offset = self._c.scroll(coll, limit=256, offset=offset, with_payload=True, with_vectors=False)
            for p in pts:
                out.append({"pid": str(p.id), "payload": dict(p.payload or {})})
            if offset is None:
                break
        return out

    def _count(self, scope: str, collection: Optional[str] = None) -> int:
        coll = collection or self._active[scope]
        return int(self._c.count(coll, exact=True).count)

    def _swap(self, scope: str, new_collection: str):
        self._active[scope] = new_collection
        self._point_alias(ALIAS[scope], new_collection)

    def _reset_base(self):
        """Drop and recreate the two base collections; reset active pointers. Used to isolate tests on a
        shared server (a no-op-ish fresh start in local mode)."""
        for name in (PRIVATE_COLLECTION, SHARED_COLLECTION):
            try:
                self._c.delete_collection(name)
            except Exception:
                pass
        self._active = {PRIVATE: PRIVATE_COLLECTION, SHARED: SHARED_COLLECTION}
        self._ensure()

    # ---------------------------------------------------------------- async surface
    async def ensure_collections(self):
        await asyncio.to_thread(self._ensure)

    async def upsert(self, records, vectors, collection=None):
        await asyncio.to_thread(self._upsert, records, vectors, collection)

    async def delete(self, scope, pids, collection=None):
        await asyncio.to_thread(self._delete, scope, list(pids), collection)

    async def search(self, scope, vector, org_id, owner_user_id=None, limit=10):
        return await asyncio.to_thread(self._search, scope, vector, org_id, owner_user_id, limit)

    async def scroll(self, scope, collection=None):
        return await asyncio.to_thread(self._scroll, scope, collection)

    async def count(self, scope, collection=None):
        return await asyncio.to_thread(self._count, scope, collection)

    async def create_collection(self, name):
        await asyncio.to_thread(self._create_collection, name)

    async def swap(self, scope, new_collection):
        await asyncio.to_thread(self._swap, scope, new_collection)

    async def reset_base(self):
        await asyncio.to_thread(self._reset_base)

    async def close(self):
        try:
            await asyncio.to_thread(self._c.close)
        except Exception:
            pass
