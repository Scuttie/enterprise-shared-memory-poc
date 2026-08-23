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


class SentenceTransformerEmbedder(Embedder):
    """Pinned PRODUCTION embedder (REALBENCH-R2 §6.2). Wraps a sentence-transformers model (default
    all-MiniLM-L6-v2, dim 384) for real dense semantic retrieval. Offline after the first model fetch,
    deterministic on CPU, no API key and no per-call cost. Pinned by the sentence-transformers library
    version + the requested revision; the RESOLVED model snapshot revision is recorded in provenance() so a
    swap is detectable and the run is reproducible (§24 item 14). This is the embedder the paid benchmark
    service path must use — never DeterministicTestEmbedder (enforced by ci-r1-causal-audit / ci-bigcode-*)."""
    def __init__(self, model_id="sentence-transformers/all-MiniLM-L6-v2", revision=None, device="cpu",
                 normalize=True, batch_size=64):
        self.model_id = model_id
        self._revision = revision
        self._device = device
        self._normalize = normalize
        self._batch = batch_size
        self._model = None
        self._resolved_revision = None
        self._st_version = None
        self.dim = 0

    def _load(self):
        if self._model is None:
            import sentence_transformers as st
            self._st_version = getattr(st, "__version__", "unknown")
            self._model = st.SentenceTransformer(self.model_id, revision=self._revision, device=self._device)
            self.dim = int(self._model.get_sentence_embedding_dimension())
            self._resolved_revision = self._revision or _resolve_hf_revision(self.model_id)
        return self._model

    def embed(self, texts: List[str]) -> List[List[float]]:
        m = self._load()
        vecs = m.encode(list(texts), batch_size=self._batch, normalize_embeddings=self._normalize,
                        convert_to_numpy=True, show_progress_bar=False)
        return [[float(x) for x in row] for row in vecs]

    def provenance(self) -> dict:
        self._load()
        return {"model_id": self.model_id, "dim": self.dim,
                "revision": self._resolved_revision, "sentence_transformers_version": self._st_version,
                "device": self._device, "normalized": self._normalize,
                "algorithm_digest": "sentence-transformers-encode-l2norm"}


def _resolve_hf_revision(model_id):
    """Best-effort: read the resolved commit hash of the locally-cached HF snapshot so provenance pins the
    exact weights actually used. Returns None if it cannot be determined (no network access here)."""
    try:
        from huggingface_hub import HfApi
        return HfApi().model_info(model_id).sha
    except Exception:
        try:
            import glob
            import os
            base = os.path.expanduser("~/.cache/huggingface/hub")
            snaps = glob.glob(os.path.join(base, "models--" + model_id.replace("/", "--"), "snapshots", "*"))
            return os.path.basename(sorted(snaps)[-1]) if snaps else None
        except Exception:
            return None
