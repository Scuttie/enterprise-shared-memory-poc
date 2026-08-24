"""R22 §5.2 — multi-signal candidate generation. Each signal score is stored separately; top-20 returned.

Embedding scores are supplied by a caller-provided callable (deterministic mock in tests / a real embedder in
paid runs); this module never calls a model itself.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .stage_query import StageQuery


def _jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / max(1, len(a | b))


def _bm25ish(terms, text):
    text = (text or "").lower()
    return sum(text.count(t.lower()) for t in terms if t) / (1 + len(text.split()) / 100.0)


def score_candidates(query: StageQuery, index_views: List[dict],
                     embed_score: Optional[Callable[[StageQuery, dict], float]] = None,
                     top_n: int = 20) -> List[Dict]:
    """index_views are SearchIndexView dicts (metadata only). Returns top_n with per-signal scores."""
    out = []
    terms = query.terms()
    for v in index_views:
        signals = {
            "bm25": _bm25ish(terms, " ".join(str(v.get(k, "")) for k in
                                             ("symptom", "error_signature", "contract", "operation_type"))),
            "embedding": float(embed_score(query, v)) if embed_score else 0.0,
            "exact_symbol": _jaccard(query.symbols, v.get("symbols", [])),
            "exact_api": _jaccard(query.apis, v.get("apis", [])),
            "error_signature": 1.0 if query.error_signature and query.error_signature == v.get("error_signature") else 0.0,
            "failing_test_signature": 1.0 if query.failing_test_signature
            and query.failing_test_signature == v.get("failing_test_signature") else 0.0,
            "operation_type": 1.0 if query.operation_type and query.operation_type == v.get("operation_type") else 0.0,
            "stage_match": 1.0 if query.stage.value == v.get("stage") else 0.0,
            "code_graph": _jaccard(query.symbols, v.get("symbols", [])) * 0.5,
        }
        out.append({"memory_id": v.get("memory_id"), "stage": v.get("stage"), "signals": signals,
                    "raw_sum": round(sum(signals.values()), 6)})
    out.sort(key=lambda c: (-c["raw_sum"], str(c["memory_id"])))  # deterministic tie-break
    return out[:top_n]
