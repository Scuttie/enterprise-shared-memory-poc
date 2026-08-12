"""Governed Mem0 index adapter (P2). Mem0 is used ONLY as a governed reference index, exactly like Qdrant:
every write goes through with infer=False (Mem0's LLM extraction is never triggered), and the stored value
is a reference payload — the canonical content is always reloaded from PostgreSQL afterwards. Two
physically separated Memory instances (private / shared) mean a private memory can never be returned by a
shared search. The wrapper targets the mem0.Memory API surface (add/search/delete) so a lightweight stub
can prove the governance contract — infer never True, hidden LLM calls == 0 — without torch, a model
download, or any network in CI. The real Mem0 is import-guarded behind the `mem0` extra."""
from __future__ import annotations
from .models import PRIVATE, SHARED


def mem0_available() -> bool:
    try:
        import mem0  # noqa
        import torch  # noqa
        return True
    except Exception:
        return False


class GovernedMem0Index:
    """Enforces infer=False on every write and exposes only reference payloads to callers. `private_mem`
    and `shared_mem` are mem0.Memory-compatible objects (or stubs) — never the same instance."""

    def __init__(self, private_mem, shared_mem):
        if private_mem is shared_mem:
            raise ValueError("private and shared Mem0 stores must be physically separate instances")
        self._m = {PRIVATE: private_mem, SHARED: shared_mem}

    def _scope_id(self, rec) -> str:
        return str(rec.owner_user_id) if rec.scope == PRIVATE else str(rec.org_id)

    def index(self, rec):
        md = rec.payload(); md["mem_key"] = rec.pid
        # infer=False is not caller-overridable: governed indexing must never invoke Mem0's LLM extraction.
        return self._m[rec.scope].add(rec.text, user_id=self._scope_id(rec), metadata=md, infer=False)

    def delete(self, scope, memory_id):
        self._m[scope].delete(memory_id)

    def candidates(self, scope, query, scope_id, top_k=10):
        """Return reference payloads (metadata) only — NEVER the stored text. Callers validate each payload
        against PostgreSQL (see validated_search) before any content is surfaced."""
        res = self._m[scope].search(query, top_k=top_k, filters={"user_id": str(scope_id)})
        results = res.get("results", res) if isinstance(res, dict) else res
        return [dict(r.get("metadata") or {}) for r in results]

    def get_all(self, scope, scope_id):
        """List reference payloads for a scope (the 'get' operation) — metadata only, no stored text."""
        res = self._m[scope].get_all(filters={"user_id": str(scope_id)})
        results = res.get("results", res) if isinstance(res, dict) else res
        return [dict(r.get("metadata") or {}) for r in results]


def build_real(paths: dict, embedder_model: str):
    """Construct physically separated real Mem0 stores over local Qdrant (governed: no LLM). Requires the
    `mem0` extra (mem0ai + torch); not installed in ci-qdrant, which exercises the stub path instead."""
    if not mem0_available():
        raise RuntimeError("mem0 extra not installed")
    from ..backends.mem0_backend import Mem0Store

    class _Adapter:
        """Targets mem0.Memory directly with an explicit user_id scope (NOT Mem0Store._scope, which keys off
        legacy owner/org metadata). threshold=0 disables score cut-off — the governed index returns every
        scoped candidate and PostgreSQL is the authority on relevance/validity."""
        def __init__(self, store):
            self._s = store

        def add(self, text, *, user_id, metadata, infer):
            if infer:
                raise ValueError("governed Mem0 index forbids infer=True")
            return self._s.mem.add(text, user_id=str(user_id), metadata=dict(metadata), infer=False)

        def search(self, query, *, top_k, filters):
            return self._s.mem.search(query, top_k=top_k, filters=filters, threshold=0)

        def get_all(self, *, filters):
            return self._s.mem.get_all(filters=filters)

        def delete(self, memory_id):
            return self._s.mem.delete(memory_id)

    priv = _Adapter(Mem0Store(paths["private"], embedder_model, llm=None))
    shar = _Adapter(Mem0Store(paths["shared"], embedder_model, llm=None))
    return GovernedMem0Index(priv, shar)
