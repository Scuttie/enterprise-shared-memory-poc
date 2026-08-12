"""Async Qdrant index adapter (P2 / P2.1). Two PHYSICALLY separate collections — enterprise_private_v1 and
enterprise_shared_v1 — never one collection with a scope column. Routing is done through **durable Qdrant
aliases** (`enterprise_private_current` / `enterprise_shared_current`), which are the authoritative pointer:
every normal read/write targets the alias, and a full reindex atomically repoints the alias to a validated
shadow collection (delete+create in a single alias operation) and can roll back. There is no process-local
routing state — a fresh adapter or a reconnected client sees the current alias immediately. Readiness is
fail-closed: a missing base collection is bootstrapped, a missing alias is created, and an ambiguous or
dangling alias raises. The sync qdrant-client runs on a worker thread so callers stay async. In CI a real
digest-pinned qdrant service is used when QDRANT_URL is set; otherwise an in-process local store keeps the
suite hermetic (local mode resolves aliases too). The stored payload is a reference only — the coding model
never sees index text."""
from __future__ import annotations
import asyncio
import os
from typing import List, Optional

from .models import (PRIVATE, SHARED, PRIVATE_COLLECTION, SHARED_COLLECTION,
                     PRIVATE_ALIAS, SHARED_ALIAS, ALIAS, BASE_COLLECTION, Candidate, IndexRecord)

_COLLECTION_PREFIX = "enterprise_"


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
        self._server = server               # payload indexes only apply to a real server

    @classmethod
    def from_env(cls, dim: int, url: Optional[str] = None):
        from qdrant_client import QdrantClient
        url = url or os.environ.get("QDRANT_URL")
        if url:
            # No check_compatibility=False: the client is pinned to a server-compatible minor (see the
            # `qdrant` extra), so the version check must stay ON and pass.
            return cls(QdrantClient(url=url, timeout=15.0), dim, server=True)
        return cls(QdrantClient(location=":memory:"), dim, server=False)

    # ---------------------------------------------------------------- alias-authoritative routing
    def alias_for(self, scope: str) -> str:
        return ALIAS[scope]

    def _alias_targets(self) -> dict:
        """alias_name -> [collection, ...] from the live Qdrant alias table."""
        out = {}
        for a in self._c.get_aliases().aliases:
            out.setdefault(a.alias_name, []).append(a.collection_name)
        return out

    def _resolve(self, scope: str) -> str:
        targets = self._alias_targets().get(ALIAS[scope], [])
        if len(targets) != 1:
            raise RuntimeError("alias %r resolves to %d collections (expected 1)" % (ALIAS[scope], len(targets)))
        return targets[0]

    def _create_collection(self, name: str):
        from qdrant_client import models as qm
        existing = {c.name for c in self._c.get_collections().collections}
        if name in existing:
            return
        self._c.create_collection(
            name, vectors_config=qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE))
        if self._server:                 # payload indexes are a no-op (and warn) in local mode
            for f in ("org_id", "owner_user_id", "object_kind", "canonical_content_hash", "contract_id",
                      "index_schema_version"):
                self._c.create_payload_index(name, field_name=f, field_schema=qm.PayloadSchemaType.KEYWORD)

    def _ensure_ready(self) -> dict:
        """Fail-closed bootstrap + verification. Returns {scope: resolved_collection}."""
        from qdrant_client import models as qm
        cols = {c.name for c in self._c.get_collections().collections}
        for scope in (PRIVATE, SHARED):
            base = BASE_COLLECTION[scope]
            if base not in cols:
                self._create_collection(base)
        targets = self._alias_targets()
        for scope in (PRIVATE, SHARED):
            alias = ALIAS[scope]
            have = targets.get(alias, [])
            if len(have) > 1:
                raise RuntimeError("ambiguous alias %r -> %r" % (alias, have))
            if len(have) == 0:
                self._c.update_collection_aliases(change_aliases_operations=[
                    qm.CreateAliasOperation(create_alias=qm.CreateAlias(
                        collection_name=BASE_COLLECTION[scope], alias_name=alias))])
        # re-read and verify each scope alias resolves to exactly one existing collection
        cols = {c.name for c in self._c.get_collections().collections}
        resolved = {}
        targets = self._alias_targets()
        for scope in (PRIVATE, SHARED):
            have = targets.get(ALIAS[scope], [])
            if len(have) != 1:
                raise RuntimeError("readiness: alias %r not singular (%r)" % (ALIAS[scope], have))
            if have[0] not in cols:
                raise RuntimeError("readiness: alias %r dangles to missing %r" % (ALIAS[scope], have[0]))
            resolved[scope] = have[0]
        return resolved

    def _upsert(self, records: List[IndexRecord], vectors: List[List[float]], collection: Optional[str] = None):
        from qdrant_client import models as qm
        if not records:
            return
        by_target = {}
        for rec, vec in zip(records, vectors):
            target = collection or ALIAS[rec.scope]
            by_target.setdefault(target, []).append(
                qm.PointStruct(id=rec.pid, vector=vec, payload=rec.payload()))
        for target, pts in by_target.items():
            self._c.upsert(target, points=pts, wait=True)

    def _delete(self, scope: str, pids: List[str], collection: Optional[str] = None):
        from qdrant_client import models as qm
        self._c.delete(collection or ALIAS[scope],
                       points_selector=qm.PointIdsList(points=list(pids)), wait=True)

    def _search(self, scope: str, vector: List[float], org_id: str,
                owner_user_id: Optional[str], limit: int, collection: Optional[str] = None):
        from qdrant_client import models as qm
        must = [qm.FieldCondition(key="org_id", match=qm.MatchValue(value=str(org_id)))]
        if owner_user_id is not None:  # private scope: store-side owner isolation (defence in depth)
            must.append(qm.FieldCondition(key="owner_user_id", match=qm.MatchValue(value=str(owner_user_id))))
        res = self._c.query_points(collection or ALIAS[scope], query=vector,
                                   query_filter=qm.Filter(must=must), limit=limit, with_payload=True)
        return [Candidate(pid=str(p.id), score=float(p.score), payload=dict(p.payload or {}))
                for p in res.points]

    def _scroll(self, scope: str, collection: Optional[str] = None):
        target = collection or ALIAS[scope]
        out, offset = [], None
        while True:
            pts, offset = self._c.scroll(target, limit=256, offset=offset, with_payload=True, with_vectors=False)
            for p in pts:
                out.append({"pid": str(p.id), "payload": dict(p.payload or {})})
            if offset is None:
                break
        return out

    def _count(self, scope: str, collection: Optional[str] = None) -> int:
        return int(self._c.count(collection or ALIAS[scope], exact=True).count)

    def _swap(self, scope: str, new_collection: str):
        """Atomic single alias operation: delete the old mapping and create the new one together."""
        from qdrant_client import models as qm
        cols = {c.name for c in self._c.get_collections().collections}
        if new_collection not in cols:
            raise RuntimeError("swap target %r does not exist" % new_collection)
        alias = ALIAS[scope]
        ops = []
        if self._alias_targets().get(alias):
            ops.append(qm.DeleteAliasOperation(delete_alias=qm.DeleteAlias(alias_name=alias)))
        ops.append(qm.CreateAliasOperation(create_alias=qm.CreateAlias(
            collection_name=new_collection, alias_name=alias)))
        self._c.update_collection_aliases(change_aliases_operations=ops)

    def _reset(self):
        """Test isolation: drop every enterprise_* collection (aliases drop with them) then re-bootstrap."""
        for c in list(self._c.get_collections().collections):
            if c.name.startswith(_COLLECTION_PREFIX):
                self._c.delete_collection(c.name)
        self._ensure_ready()

    # ---------------------------------------------------------------- async surface
    async def ensure_ready(self):
        return await asyncio.to_thread(self._ensure_ready)

    async def ensure_collections(self):        # back-compat alias
        return await asyncio.to_thread(self._ensure_ready)

    async def resolve(self, scope):
        return await asyncio.to_thread(self._resolve, scope)

    async def alias_targets(self):
        return await asyncio.to_thread(self._alias_targets)

    async def upsert(self, records, vectors, collection=None):
        await asyncio.to_thread(self._upsert, records, vectors, collection)

    async def delete(self, scope, pids, collection=None):
        await asyncio.to_thread(self._delete, scope, list(pids), collection)

    async def search(self, scope, vector, org_id, owner_user_id=None, limit=10, collection=None):
        return await asyncio.to_thread(self._search, scope, vector, org_id, owner_user_id, limit, collection)

    async def scroll(self, scope, collection=None):
        return await asyncio.to_thread(self._scroll, scope, collection)

    async def count(self, scope, collection=None):
        return await asyncio.to_thread(self._count, scope, collection)

    async def create_collection(self, name):
        await asyncio.to_thread(self._create_collection, name)

    async def swap(self, scope, new_collection):
        await asyncio.to_thread(self._swap, scope, new_collection)

    async def reset_base(self):
        await asyncio.to_thread(self._reset)

    async def close(self):
        try:
            await asyncio.to_thread(self._c.close)
        except Exception:
            pass
