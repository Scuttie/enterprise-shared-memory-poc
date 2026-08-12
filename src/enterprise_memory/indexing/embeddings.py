"""Embedding abstraction (P2). The production embedder is pluggable; CI uses DeterministicTestEmbedder,
which needs no credentials, no network, and no model download — identical text always yields an identical
vector, so index/search/drift/reindex are reproducible. Provenance (model id + dim + an algorithm digest)
is recorded so a drift check can detect an embedder swap that would silently invalidate the index."""
from __future__ import annotations
import hashlib
import math
from typing import List


class Embedder:
    """Structural interface: attributes `dim`, `model_id`; method `embed(list[str]) -> list[list[float]]`
    and `provenance() -> dict`. Kept as a plain base (not typing.Protocol) so import stays 3.10-safe."""
    dim: int = 0
    model_id: str = "abstract"

    def embed(self, texts: List[str]) -> List[List[float]]:  # pragma: no cover - interface
        raise NotImplementedError

    def provenance(self) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class DeterministicTestEmbedder(Embedder):
    """Hash-seeded bag-of-tokens embedder. Deterministic, offline, credential-free. NOT production-quality
    retrieval — it exists so the indexing/search/drift/reindex machinery is testable without a real
    embedding model or an API key. Same text -> same L2-normalised vector on every machine."""
    model_id = "deterministic-test-embedder-v1"

    def __init__(self, dim: int = 64):
        if dim < 8:
            raise ValueError("dim too small")
        self.dim = dim

    def _vec(self, text: str) -> List[float]:
        v = [0.0] * self.dim
        for tok in (text or "").lower().split():
            h = hashlib.sha256(tok.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            v[idx] += 1.0 if (h[4] & 1) else -1.0
        # a stable per-character component so distinct short texts still separate
        hh = hashlib.sha256((text or "").encode("utf-8")).digest()
        for i in range(self.dim):
            v[i] += (hh[i % len(hh)] - 128) / 512.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed(self, texts: List[str]) -> List[List[float]]:
        return [self._vec(t) for t in texts]

    def provenance(self) -> dict:
        return {"model_id": self.model_id, "dim": self.dim,
                "algorithm_digest": "sha256-bag-of-tokens-l2norm-v1"}
