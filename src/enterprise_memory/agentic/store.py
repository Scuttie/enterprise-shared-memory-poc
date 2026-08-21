"""P6/R19 §7 — experience store abstraction for the agentic search/browse flow.

The store yields metadata-only candidate summaries for search, and the full execution view ONLY on an authorized
browse (canonical reload). An in-memory implementation backs the offline demo and tests; the Postgres/Qdrant
implementation plugs in behind the same protocol. Vector text is never treated as canonical — the execution view
is always compiled from the canonical ExperienceCardVersion.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Protocol

from ..experience.schema import ExperienceCardVersion, SEARCHABLE_STATES, GovernanceState
from ..experience.compiler import retrieval_projection, execution_view


@dataclass
class CandidateSummary:
    """Metadata-only (what search returns). Contains NO execution view / patch / identity / verdict."""
    card_key: str
    version_id: str
    title: str
    repository_scope: str
    framework: str
    language: str
    version_scope: str
    path_scope: str
    governance_state: str
    similarity: float
    similarity_margin: float
    reason_tags: list = field(default_factory=list)
    # router-relevant, non-sensitive descriptors
    affected_apis: list = field(default_factory=list)
    affected_symbols: list = field(default_factory=list)
    symptom_signature: str = ""
    operation: str = ""
    source_verified: bool = False
    provides_executable_action: bool = False
    generic_advice_only: bool = False


class ExperienceStore(Protocol):
    def search(self, org_id: str, repository: str, query: str, top_k: int) -> list: ...
    def canonical_version(self, org_id: str, version_id: str) -> Optional[ExperienceCardVersion]: ...


def _tok(s: str):
    return {w for w in re.findall(r"[a-zA-Z_][a-zA-Z_0-9]{2,}", (s or "").lower())}


class InMemoryExperienceStore:
    """Offline/test store. add() indexes a canonical version; search() ranks promoted/probation cards in the same
    repository by token overlap (a stand-in for the vector index). Enforces tenant + searchable-state filtering."""

    def __init__(self):
        self._by_version = {}   # (org, version_id) -> ExperienceCardVersion
        self._order = []        # insertion order of (org, version_id)

    def add(self, org_id: str, version_id: str, card: ExperienceCardVersion) -> None:
        self._by_version[(org_id, version_id)] = card
        self._order.append((org_id, version_id))

    def canonical_version(self, org_id: str, version_id: str):
        return self._by_version.get((org_id, version_id))

    def search(self, org_id: str, repository: str, query: str, top_k: int = 10) -> list:
        q = _tok(query)
        scored = []
        for (o, vid) in self._order:
            if o != org_id:
                continue
            card = self._by_version[(o, vid)]
            if GovernanceState(card.governance_state) not in SEARCHABLE_STATES:
                continue  # quarantined/deprecated/deleted/candidate never searchable
            if card.source_repository != repository:
                continue
            proj = retrieval_projection(card)
            text = " ".join(str(x) for x in [proj["symptom_signature"], proj["task_or_failure_type"],
                                             " ".join(proj["affected_apis"])])
            sim = _jaccard(q, _tok(text))
            scored.append((sim, vid, card, proj))
        scored.sort(key=lambda t: (-t[0], t[1]))
        out = []
        for rank, (sim, vid, card, proj) in enumerate(scored[:top_k]):
            margin = sim - scored[rank + 1][0] if rank + 1 < len(scored) else sim
            out.append(CandidateSummary(
                card_key=card.card_key, version_id=vid, title=proj["symptom_signature"][:80],
                repository_scope=card.source_repository, framework=card.framework, language=card.language,
                version_scope=card.version_scope, path_scope=card.path_scope,
                governance_state=card.governance_state, similarity=round(sim, 4), similarity_margin=round(margin, 4),
                reason_tags=[], affected_apis=card.affected_apis, affected_symbols=card.affected_symbols,
                symptom_signature=card.symptom_signature, operation=(card.repair_strategy or "").split(".")[0],
                source_verified=(card.source_outcome.value == "passed"),
                provides_executable_action=bool(card.ordered_actions or card.patch_pattern),
                generic_advice_only=not bool(card.ordered_actions or card.patch_pattern or card.affected_symbols)))
        return out

    def execution_view_for(self, org_id: str, version_id: str) -> dict:
        card = self.canonical_version(org_id, version_id)
        if card is None:
            raise KeyError("no such version")
        return execution_view(card)  # compiled from canonical, never from vector text


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a or b) else 0.0
