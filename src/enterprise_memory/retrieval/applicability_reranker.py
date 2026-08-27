"""R22 §5.3 — applicability rerank (top-20 → top-3 → top-1).

RANK-D: deterministic frozen weighted score. RANK-L: a small-LLM structured selector INTERFACE — implemented but
NEVER called here (a mock is injected for tests). Neither can recover a hard-gate reject.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

# frozen weights (tuned only on dev before freeze; recorded here for determinism)
RANK_D_WEIGHTS = {
    # stage_match is a soft prior, not evidence — a stage-only match must NOT clear the threshold on its own.
    "stage_match": 1.0, "error_signature": 2.5, "failing_test_signature": 2.0, "exact_symbol": 2.0,
    "exact_api": 1.5, "operation_type": 1.5, "embedding": 1.0, "bm25": 0.5, "code_graph": 0.5,
}
RANK_D_MIN_SCORE = 3.0     # frozen threshold (dev-only)
RANK_D_MIN_MARGIN = 0.5    # frozen top1-vs-top2 margin


def rank_d(candidates: List[Dict], top_k: int = 3) -> List[Dict]:
    for c in candidates:
        c["rank_d_score"] = round(sum(RANK_D_WEIGHTS.get(k, 0) * v for k, v in c["signals"].items()), 6)
    ranked = sorted(candidates, key=lambda c: (-c["rank_d_score"], str(c["memory_id"])))
    return ranked[:top_k]


def select_top1(candidates: List[Dict],
                rank_l: Optional[Callable[[Dict], Dict]] = None) -> Optional[Dict]:
    """Return the top-1 applicable candidate or None (ABSTAIN). rank_l (if provided) is a structured selector;
    it can only DEMOTE (mark inapplicable), never resurrect a rejected/low candidate."""
    top3 = rank_d(candidates)
    if not top3:
        return None
    top1 = top3[0]
    if top1["rank_d_score"] < RANK_D_MIN_SCORE:
        return None
    if len(top3) > 1 and (top1["rank_d_score"] - top3[1]["rank_d_score"]) < RANK_D_MIN_MARGIN:
        return None
    if rank_l is not None:
        verdict = rank_l(top1)   # structured: {applicable, stage_match, new_action_added, conflict, reason_code, confidence}
        if not verdict.get("applicable", False) or verdict.get("conflict", False):
            return None
        top1 = {**top1, "rank_l": verdict}
    return top1
