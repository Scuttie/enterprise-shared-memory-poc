"""Governed Mem0 index adapter (P2). Mem0 is used ONLY as a governed reference index, exactly like Qdrant:
every write goes through with infer=False (Mem0's LLM extraction is never triggered), and the stored value
is a reference payload — the canonical content is always reloaded from PostgreSQL afterwards. Two
physically separated Memory instances (private / shared) mean a private memory can never be returned by a
shared search. The wrapper targets the mem0.Memory API surface (add/search/delete) so a lightweight stub
can prove the governance contract — infer never True, hidden LLM calls == 0 — without torch, a model
download, or any network in CI. The real Mem0 is import-guarded behind the `mem0` extra."""
from __future__ import annotations
import os
from .models import PRIVATE, SHARED

# P3.1 §4 — pinned embedder policy. The moving default branch is NOT acceptable in staging/production; the
# adapter fails closed if it cannot enforce the pinned revision + trust policy + dimension.
EMBEDDER_PIN = {
    "model_id": "sentence-transformers/multi-qa-MiniLM-L6-cos-v1",
    "dimension": 384,
    "trust_remote_code": False,
    "license": "Apache-2.0",
    "revision_env": "EMBEDDER_REVISION",
}


class EmbedderPinError(Exception):
    pass


def enforce_embedder_pin(revision=None, trust_remote_code=False, environment="production",
                         loader=None, info_fn=None) -> dict:
    """Load the pinned embedder under the fixed trust policy and record its provenance. Raises
    EmbedderPinError if trust_remote_code is requested, the dimension does not match, a revision cannot be
    honored, or (in staging/production) no revision is pinned. `loader`/`info_fn` are injectable for tests."""
    if trust_remote_code:
        raise EmbedderPinError("trust_remote_code must be False")
    revision = revision if revision is not None else os.environ.get(EMBEDDER_PIN["revision_env"])
    if environment in ("staging", "production") and not revision:
        raise EmbedderPinError("pinned embedder revision required in %s (no moving default)" % environment)
    model_id = EMBEDDER_PIN["model_id"]
    if loader is None:
        def loader():
            from sentence_transformers import SentenceTransformer
            return SentenceTransformer(model_id, revision=revision, trust_remote_code=False)
    model = loader()
    dim = getattr(model, "get_sentence_embedding_dimension", lambda: EMBEDDER_PIN["dimension"])()
    if int(dim) != EMBEDDER_PIN["dimension"]:
        raise EmbedderPinError("embedding dimension mismatch: %s != %s" % (dim, EMBEDDER_PIN["dimension"]))
    resolved = revision
    if info_fn is not None:
        try:
            resolved = info_fn()
        except Exception:
            resolved = revision
    else:
        try:
            from huggingface_hub import model_info
            resolved = model_info(model_id, revision=revision).sha
        except Exception:
            resolved = revision
    return {"model_id": model_id, "requested_revision": revision, "resolved_revision": resolved,
            "dimension": int(dim), "trust_remote_code": False, "license": EMBEDDER_PIN["license"]}


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


def build_real(paths: dict, embedder_model: str = None, environment: str = None):
    """Construct physically separated real Mem0 stores over local Qdrant (governed: no LLM). Enforces the
    pinned embedder (revision/trust/dimension) BEFORE constructing anything; the resolved provenance is
    attached to the returned index. Requires the `mem0` extra."""
    if not mem0_available():
        raise RuntimeError("mem0 extra not installed")
    env = environment or os.environ.get("ENVIRONMENT", "test")
    provenance = enforce_embedder_pin(environment=env)          # fail-closed on trust/revision/dimension
    model_id = provenance["model_id"]
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

    priv = _Adapter(Mem0Store(paths["private"], model_id, llm=None))
    shar = _Adapter(Mem0Store(paths["shared"], model_id, llm=None))
    idx = GovernedMem0Index(priv, shar)
    idx.embedder_provenance = provenance
    return idx
