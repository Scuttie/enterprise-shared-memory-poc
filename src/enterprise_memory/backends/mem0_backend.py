"""Mem0 private/shared adapters (handoff §4). Signatures derived from the INSTALLED mem0ai==2.0.17
source (verified):
  Memory.add(messages, *, user_id=None, metadata=None, infer=True, ...)
  Memory.search(query, *, top_k=20, filters=None, threshold=0.1, ...)
  Memory.get_all(*, filters=None, top_k=20, ...); Memory.delete(memory_id); Memory.from_config(cfg)
  AsyncMemory exists (async add/search/...).
Mem0 is a retrieval index, NOT the source of truth: the private store indexes a deterministic
retrieval view; the shared store indexes a promoted contract's retrieval_view keyed by contract_id,
and callers reload the canonical contract from the SQLite registry after retrieval. infer=False for
governed indexing; infer=True only for the M3 vanilla baseline. Import is guarded so the base test
suite / CI (InMemoryBackend) never needs torch/mem0."""
from __future__ import annotations
import os


def _mem0_available():
    try:
        import mem0  # noqa
        import torch  # noqa (HF embedder)
        return True
    except Exception:
        return False


# multi-qa-MiniLM-L6-cos-v1 produces 384-dim embeddings; the Qdrant collection must match (mem0
# otherwise defaults to the 1536-dim OpenAI-embedding size and upsert fails).
EMBED_DIMS = 384


def _qdrant_cfg(path, collection, dims=EMBED_DIMS):
    return {"provider": "qdrant", "config": {"path": path, "collection_name": collection,
                                             "embedding_model_dims": dims}}


def _hf_embedder(model, dims=EMBED_DIMS):
    return {"provider": "huggingface", "config": {"model": model, "embedding_dims": dims}}


def build_config(store: dict, embedder_model: str, llm: dict = None):
    """Compose a mem0 MemoryConfig dict (keys verified: vector_store/embedder/history_db_path/llm)."""
    cfg = {"vector_store": _qdrant_cfg(store["qdrant_path"], store["collection"]),
           "embedder": _hf_embedder(embedder_model),
           "history_db_path": store["history_db"]}
    if llm:
        cfg["llm"] = llm
    return cfg


class Mem0Store:
    """Thin sync wrapper over mem0.Memory for one physical store (private OR shared). Distinct Qdrant
    dir + collection + history db per store — no shared client, no mixed search."""

    def __init__(self, store: dict, embedder_model: str, llm: dict = None):
        os.environ.setdefault("MEM0_TELEMETRY", "False")
        from mem0 import Memory
        for d in (store["qdrant_path"], os.path.dirname(store["history_db"])):
            os.makedirs(d, exist_ok=True)
        self.name = store["collection"]
        self.mem = Memory.from_config(build_config(store, embedder_model, llm))

    def _scope(self, metadata):
        return (metadata or {}).get("owner") or (metadata or {}).get("org") or "system"

    def add_view(self, memory_id: str, text: str, metadata: dict, infer: bool = False):
        md = dict(metadata or {}); md["mem_key"] = memory_id
        return self.mem.add(text, user_id=self._scope(md), metadata=md, infer=infer)

    def search(self, query: str, top_k: int, scope_id: str, extra_filters: dict = None):
        """mem0 2.0.17 REQUIRES a scoping filter (user_id/agent_id/run_id) — a good isolation property;
        we always pass the store's scope_id, never an unscoped search."""
        f = {"user_id": scope_id}
        f.update(extra_filters or {})
        res = self.mem.search(query, top_k=top_k, filters=f)
        return res.get("results", res) if isinstance(res, dict) else res

    def get_all(self, scope_id: str):
        res = self.mem.get_all(filters={"user_id": scope_id})
        return res.get("results", res) if isinstance(res, dict) else res

    def add_episode_extracted(self, text: str, user_id: str, metadata: dict):
        """M3 vanilla path: infer=True lets Mem0's LLM extract memories."""
        return self.mem.add(text, user_id=user_id, metadata=dict(metadata or {}), infer=True)


def build_private_shared(paths: dict, embedder_model: str, llm: dict = None):
    """Return (private_store, shared_store) as physically-separated Mem0Store instances."""
    priv = Mem0Store(paths["private"], embedder_model, llm=None)     # private never gets the LLM
    shar = Mem0Store(paths["shared"], embedder_model, llm=llm)
    return priv, shar
