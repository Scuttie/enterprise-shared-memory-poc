"""R22 §5 — full stage retrieval pipeline: hard gate → candidate generation → applicability rerank → top-1.

The hard gate is deterministic and cannot be overturned by any reranker (§5.1). The pipeline returns at most one
execution candidate or ABSTAIN.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .stage_query import StageQuery
from .hybrid_candidates import score_candidates
from .applicability_reranker import select_top1


# hard-gate reason codes (frozen)
GATE_REASONS = ("tenant", "private_owner", "repository", "path", "version", "validity", "governance",
                "provenance", "secret_pii", "target_leakage", "quarantine_deprecated_deleted")


def hard_gate(view: dict, ctx: dict) -> Optional[str]:
    """Return a reason code if the candidate is rejected, else None. Deterministic; no LLM."""
    if view.get("tenant") not in (None, ctx.get("tenant")):
        return "tenant"
    if view.get("private_owner") and view.get("private_owner") != ctx.get("user"):
        return "private_owner"
    if ctx.get("allowed_repositories") is not None and view.get("repository_scope") not in ctx["allowed_repositories"]:
        return "repository"
    if view.get("governance_state") in ("quarantined", "deprecated", "deleted"):
        return "quarantine_deprecated_deleted"
    if view.get("source_verified") is False:
        return "validity"
    # target-leakage sentinel: any forbidden key present -> reject
    for k in view.keys():
        if str(k).lower() in ("target_patch", "target_tests", "fail_to_pass", "gold_patch", "hidden_test"):
            return "target_leakage"
    return None


def retrieve_stage(query: StageQuery, index_views: List[dict], ctx: dict,
                   embed_score: Optional[Callable] = None,
                   rank_l: Optional[Callable] = None) -> Dict:
    """Returns {"decision": "USE"|"ABSTAIN", "candidate": <or None>, "gated": [...], "reason": ...}."""
    passed, gated = [], []
    for v in index_views:
        r = hard_gate(v, ctx)
        if r:
            gated.append({"memory_id": v.get("memory_id"), "reason": r})
        else:
            passed.append(v)
    if not passed:
        return {"decision": "ABSTAIN", "candidate": None, "gated": gated, "reason": "all_gated_or_empty"}
    cands = score_candidates(query, passed, embed_score=embed_score, top_n=20)
    top1 = select_top1(cands, rank_l=rank_l)
    if top1 is None:
        return {"decision": "ABSTAIN", "candidate": None, "gated": gated, "reason": "weak_or_ambiguous"}
    return {"decision": "USE", "candidate": top1, "gated": gated, "reason": "applicable_top1"}
