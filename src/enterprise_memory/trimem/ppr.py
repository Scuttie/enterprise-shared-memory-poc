"""Credential-free deterministic seed retrieval and personalized PageRank."""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol, Sequence


TRIMEM_PRODUCTION_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TRIMEM_PRODUCTION_EMBEDDING_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
TRIMEM_PRODUCTION_EMBEDDING_DIMENSIONS = 384


class TextEmbedder(Protocol):
    """Single-text embedding boundary used to seed PPR."""

    def embed(self, text: str) -> Sequence[float]: ...

    def provenance(self) -> Mapping[str, object]: ...


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w./:+-]+", (text or "").casefold(), flags=re.UNICODE)


@dataclass(frozen=True)
class SeedSignal:
    name: str
    text: str
    weight: float = 1.0


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RankedNode:
    node_id: str
    score: float
    ppr_score: float
    seed_score: float


class DeterministicHashEmbedder:
    """Signed feature hashing with no model download, process salt, or random state."""

    def __init__(self, dimensions: int = 128):
        if dimensions < 8:
            raise ValueError("dimensions must be >= 8")
        self.dimensions = int(dimensions)

    def embed(self, text: str) -> tuple[float, ...]:
        vector = [0.0] * self.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)

    def provenance(self) -> Mapping[str, object]:
        return {
            "model_id": "trimem-deterministic-hash-embedder-v1",
            "revision": "sha256-token-feature-hashing-v1",
            "dimensions": self.dimensions,
            "production": False,
            "credential_free": True,
        }


class PinnedSentenceTransformerPPR:
    """Production PPR seed embedder pinned to an immutable model snapshot.

    Construction and provenance inspection are credential-free and do not load
    model weights.  The first ``embed`` call loads the already pinned snapshot
    through the product's SentenceTransformer adapter.  A caller cannot replace
    the revision with a moving branch or tag.
    """

    def __init__(
        self,
        *,
        model_id: str = TRIMEM_PRODUCTION_EMBEDDING_MODEL,
        revision: str = TRIMEM_PRODUCTION_EMBEDDING_REVISION,
        dimensions: int = TRIMEM_PRODUCTION_EMBEDDING_DIMENSIONS,
        device: str = "cpu",
    ):
        if model_id != TRIMEM_PRODUCTION_EMBEDDING_MODEL:
            raise ValueError("TriMem V1 production embedding model is frozen")
        if revision != TRIMEM_PRODUCTION_EMBEDDING_REVISION:
            raise ValueError("TriMem V1 production embedding revision is frozen")
        if dimensions != TRIMEM_PRODUCTION_EMBEDDING_DIMENSIONS:
            raise ValueError("TriMem V1 production embedding dimensions are frozen")
        self.model_id = model_id
        self.revision = revision
        self.dimensions = dimensions
        self.device = device
        self._delegate = None

    def _load(self):
        if self._delegate is None:
            from enterprise_memory.indexing.embeddings import SentenceTransformerEmbedder

            self._delegate = SentenceTransformerEmbedder(
                self.model_id,
                revision=self.revision,
                device=self.device,
                normalize=True,
            )
        return self._delegate

    def embed(self, text: str) -> tuple[float, ...]:
        values = tuple(float(value) for value in self._load().embed([text])[0])
        if len(values) != self.dimensions:
            raise RuntimeError("production embedding dimension mismatch")
        return values

    def provenance(self) -> Mapping[str, object]:
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "dimensions": self.dimensions,
            "device": self.device,
            "normalized": True,
            "production": True,
            "credential_free": True,
            "license": "Apache-2.0",
        }


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions differ")
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def lexical_similarity(left: str, right: str) -> float:
    a, b = set(_tokens(left)), set(_tokens(right))
    return len(a & b) / len(a | b) if (a or b) else 0.0


def _raw_seed_scores(nodes: Mapping[str, GraphNode], seeds: Iterable[SeedSignal], *,
                     embedder: TextEmbedder, embedding_weight: float,
                     lexical_weight: float) -> dict[str, float]:
    signals = sorted((seed for seed in seeds if seed.text.strip() and seed.weight > 0),
                     key=lambda seed: (seed.name, seed.text, seed.weight))
    seed_vectors = [(seed, embedder.embed(seed.text)) for seed in signals]
    scores: dict[str, float] = {}
    for node_id in sorted(nodes):
        node = nodes[node_id]
        vector = embedder.embed(node.text)
        score = 0.0
        for seed, seed_vector in seed_vectors:
            similarity = (embedding_weight * cosine_similarity(seed_vector, vector) +
                          lexical_weight * lexical_similarity(seed.text, node.text))
            score += float(seed.weight) * similarity
        if score > 0:
            scores[node_id] = round(score, 15)
    return scores


def seed_personalization(nodes: Mapping[str, GraphNode], seeds: Iterable[SeedSignal], *,
                         embedder: TextEmbedder | None = None,
                         embedding_weight: float = 0.65, lexical_weight: float = 0.35) -> dict[str, float]:
    if embedding_weight < 0 or lexical_weight < 0 or embedding_weight + lexical_weight <= 0:
        raise ValueError("seed weights must be non-negative and not both zero")
    model = embedder or DeterministicHashEmbedder()
    raw = _raw_seed_scores(nodes, seeds, embedder=model, embedding_weight=embedding_weight,
                           lexical_weight=lexical_weight)
    total = math.fsum(raw.values())
    return {node_id: round(raw[node_id] / total, 15) for node_id in sorted(raw)} if total else {}


def _weighted_neighbors(value: object, allowed: set[str]) -> tuple[tuple[str, float], ...]:
    if isinstance(value, Mapping):
        pairs = ((str(node_id), float(weight)) for node_id, weight in value.items())
    else:
        pairs = ((str(node_id), 1.0) for node_id in (value or ()))
    positive = [(node_id, weight) for node_id, weight in pairs if node_id in allowed and weight > 0]
    return tuple(sorted(positive, key=lambda item: item[0]))


def personalized_pagerank(adjacency: Mapping[str, object], personalization: Mapping[str, float], *,
                          damping: float = 0.85, iterations: int = 32) -> dict[str, float]:
    """Run a fixed number of iterations over sorted nodes/edges with stable node-id ties."""
    if not 0.0 <= damping < 1.0:
        raise ValueError("damping must be in [0, 1)")
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    node_ids = sorted(set(adjacency) | set(personalization) |
                      {str(dst) for value in adjacency.values()
                       for dst in (value.keys() if isinstance(value, Mapping) else (value or ()))})
    if not node_ids:
        return {}
    allowed = set(node_ids)
    positive = {node_id: max(0.0, float(personalization.get(node_id, 0.0))) for node_id in node_ids}
    total = math.fsum(positive.values())
    if total <= 0:
        return {}
    personal = {node_id: positive[node_id] / total for node_id in node_ids}
    graph = {node_id: _weighted_neighbors(adjacency.get(node_id, ()), allowed) for node_id in node_ids}
    rank = dict(personal)
    for _ in range(iterations):
        dangling = math.fsum(rank[node_id] for node_id in node_ids if not graph[node_id])
        nxt = {node_id: (1.0 - damping) * personal[node_id] +
               damping * dangling * personal[node_id] for node_id in node_ids}
        for source_id in node_ids:
            neighbors = graph[source_id]
            if not neighbors:
                continue
            denominator = math.fsum(weight for _, weight in neighbors)
            for target_id, weight in neighbors:
                nxt[target_id] += damping * rank[source_id] * weight / denominator
        rank = {node_id: round(nxt[node_id], 15) for node_id in node_ids}
    norm = math.fsum(rank.values())
    return {node_id: rank[node_id] / norm for node_id in node_ids}


def rank_graph(nodes: Mapping[str, GraphNode], adjacency: Mapping[str, object], seeds: Iterable[SeedSignal], *,
               embedder: TextEmbedder | None = None, embedding_weight: float = 0.65,
               lexical_weight: float = 0.35, damping: float = 0.85, iterations: int = 32,
               top_k: int | None = None) -> list[RankedNode]:
    model = embedder or DeterministicHashEmbedder()
    seed_list = tuple(seeds)
    raw = _raw_seed_scores(nodes, seed_list, embedder=model, embedding_weight=embedding_weight,
                           lexical_weight=lexical_weight)
    if not raw:
        return []
    raw_max = max(raw.values())
    normalized_seed = {node_id: raw.get(node_id, 0.0) / raw_max for node_id in nodes}
    personal = seed_personalization(nodes, seed_list, embedder=model, embedding_weight=embedding_weight,
                                    lexical_weight=lexical_weight)
    filtered_adjacency = {node_id: adjacency.get(node_id, ()) for node_id in nodes}
    ppr = personalized_pagerank(filtered_adjacency, personal, damping=damping, iterations=iterations)

    # Exact duplicate retrieval texts are semantically tied candidates.  Their
    # graph degree must not make the chosen memory depend on which duplicate
    # happened to receive more edges, so share the group's deterministic mean
    # PPR score and let node_id provide the fixed final tie break.
    text_groups: dict[str, list[str]] = {}
    for node_id in sorted(nodes):
        canonical_text = " ".join(nodes[node_id].text.casefold().split())
        text_groups.setdefault(canonical_text, []).append(node_id)
    effective_ppr = dict(ppr)
    for member_ids in text_groups.values():
        if len(member_ids) < 2:
            continue
        mean = math.fsum(ppr.get(node_id, 0.0) for node_id in member_ids) / len(member_ids)
        for node_id in member_ids:
            effective_ppr[node_id] = mean

    ranked = [RankedNode(
        node_id=node_id,
        score=round(0.7 * effective_ppr.get(node_id, 0.0) + 0.3 * normalized_seed.get(node_id, 0.0), 15),
        ppr_score=round(effective_ppr.get(node_id, 0.0), 15),
        seed_score=round(normalized_seed.get(node_id, 0.0), 15),
    ) for node_id in nodes]
    ranked.sort(key=lambda item: (-item.score, item.node_id))
    return ranked[:top_k] if top_k is not None else ranked
