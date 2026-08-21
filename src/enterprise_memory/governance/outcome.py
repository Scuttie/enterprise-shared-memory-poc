"""P6/R19 §9 — outcome credit assignment.

Classifies a memory-assisted target into an outcome class using the target outcome, the no-memory counterfactual,
and ADOPTION evidence. Adoption is never inferred merely because two patches differ (§9): the source operation /
symbol / api must actually appear in the target patch. Outcome stats from one target may affect FUTURE targets
only — this module computes a credit record; it never mutates a card for its own target.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# outcome classes
MEMORY_GAIN = "MEMORY_GAIN"
MEMORY_LOSS = "MEMORY_LOSS"
MEMORY_NEUTRAL = "MEMORY_NEUTRAL"
COMPUTE_ONLY_GAIN = "COMPUTE_ONLY_GAIN"
UNATTRIBUTED = "UNATTRIBUTED"
INFRA_FAILURE = "INFRA_FAILURE"

# evidence classes
EXACT_SOURCE_OPERATION_ADOPTION = "EXACT_SOURCE_OPERATION_ADOPTION"
PARTIAL_SOURCE_OPERATION_ADOPTION = "PARTIAL_SOURCE_OPERATION_ADOPTION"
SOURCE_API_ADOPTION = "SOURCE_API_ADOPTION"
SOURCE_CONTROL_FLOW_ADOPTION = "SOURCE_CONTROL_FLOW_ADOPTION"
UNRELATED_ERROR = "UNRELATED_ERROR"
NO_BEHAVIORAL_CHANGE = "NO_BEHAVIORAL_CHANGE"
UNCLASSIFIED = "UNCLASSIFIED"

_ADOPTION_EVIDENCE = {EXACT_SOURCE_OPERATION_ADOPTION, PARTIAL_SOURCE_OPERATION_ADOPTION,
                      SOURCE_API_ADOPTION, SOURCE_CONTROL_FLOW_ADOPTION}


def _tok(s):
    return {w for w in re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", (s or ""))}


def classify_adoption(execution_view: dict, target_patch: str) -> str:
    """Conservative: require the source's own symbols/apis/operation to appear in the target patch."""
    if not target_patch or not target_patch.strip():
        return NO_BEHAVIORAL_CHANGE
    patch_tokens = _tok(target_patch)
    symbols = set(execution_view.get("affected_symbols") or [])
    apis = set(execution_view.get("affected_apis") or [])
    ops = execution_view.get("ordered_repair_operations") or []
    strat = execution_view.get("repair_strategy") or ""

    sym_hit = any(_leaf(s) in patch_tokens for s in symbols)
    api_hit = any(_leaf(a) in patch_tokens for a in apis)
    op_terms = _tok(" ".join(ops) + " " + strat)
    op_overlap = len(op_terms & patch_tokens)

    if sym_hit and op_overlap >= 2:
        return EXACT_SOURCE_OPERATION_ADOPTION
    if sym_hit or (op_overlap >= 2 and api_hit):
        return PARTIAL_SOURCE_OPERATION_ADOPTION
    if api_hit:
        return SOURCE_API_ADOPTION
    if op_overlap >= 3:
        return SOURCE_CONTROL_FLOW_ADOPTION
    return NO_BEHAVIORAL_CHANGE


@dataclass
class CreditRecord:
    target_task_id: str
    outcome_class: str
    evidence_class: str
    target_outcome: str
    counterfactual_outcome: Optional[str]
    injected_card_keys: list = field(default_factory=list)
    cost: dict = field(default_factory=dict)

    def is_gain(self):
        return self.outcome_class == MEMORY_GAIN

    def is_loss(self):
        return self.outcome_class == MEMORY_LOSS


class OutcomeCreditAssigner:
    def assign(self, target_task_id: str, target_outcome: str, injected_views: list,
               target_patch: str = "", counterfactual_outcome: Optional[str] = None,
               cost: Optional[dict] = None) -> CreditRecord:
        cost = cost or {}
        if target_outcome == "infra_failure":
            return CreditRecord(target_task_id, INFRA_FAILURE, UNCLASSIFIED, target_outcome,
                                counterfactual_outcome, [], cost)
        injected = bool(injected_views)
        resolved = target_outcome == "resolved"
        cf_resolved = counterfactual_outcome == "resolved"

        # best adoption evidence across all injected cards
        evidence = NO_BEHAVIORAL_CHANGE
        keys = []
        best_rank = -1
        rank = {EXACT_SOURCE_OPERATION_ADOPTION: 4, PARTIAL_SOURCE_OPERATION_ADOPTION: 3,
                SOURCE_API_ADOPTION: 2, SOURCE_CONTROL_FLOW_ADOPTION: 1}
        for v in injected_views:
            keys.append(v.get("card_key"))
            e = classify_adoption(v, target_patch)
            if rank.get(e, 0) > best_rank:
                best_rank = rank.get(e, 0)
                evidence = e
        adopted = evidence in _ADOPTION_EVIDENCE

        if not injected:
            return CreditRecord(target_task_id, UNATTRIBUTED, UNCLASSIFIED, target_outcome,
                                counterfactual_outcome, [], cost)
        if resolved and not cf_resolved and adopted:
            cls = MEMORY_GAIN
        elif resolved and not cf_resolved and not adopted:
            cls = COMPUTE_ONLY_GAIN            # solved, but no source-pattern adoption -> credit compute, not memory
        elif (not resolved) and cf_resolved:
            cls = MEMORY_LOSS                  # would have solved without memory
        else:
            cls = MEMORY_NEUTRAL
        return CreditRecord(target_task_id, cls, evidence, target_outcome, counterfactual_outcome, keys, cost)


def _leaf(sym: str) -> str:
    return re.split(r"[.\s(]", str(sym))[-1] if sym else ""
