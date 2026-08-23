"""P6/R19 §7 — progressive search + selective browsing, gated by the utility router.

Flow: subtask -> query -> search (metadata only) -> router decides USE/ABSTAIN per candidate -> only USE candidates
may be browsed -> browsed execution views enter context -> every step persisted. Budgets enforced: max search
rounds, max browse, max injected tokens, max cards. Stable logical IDs; idempotent (re-browsing a card is a no-op).
Modes: off / static_relevant / agentic_reference / utility_gated / shadow (shadow persists decisions, injects
nothing). A client can never bypass server policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .store import InMemoryExperienceStore, CandidateSummary
from ..router import RuleRouterV1, TaskContext, TrajectoryState, Candidate, Policy


@dataclass
class SearchSession:
    session_id: str
    org_id: str
    request_id: str
    actor_id_hash: str
    target_task_id: str
    mode: str = "utility_gated"           # off|static_relevant|agentic_reference|utility_gated|shadow
    max_search_rounds: int = 4
    max_browse: int = 4
    max_injected_tokens: int = 1200
    max_cards: int = 4
    # counters / state
    rounds: int = 0
    browsed_keys: list = field(default_factory=list)
    injected_tokens: int = 0
    audit: list = field(default_factory=list)

    def _log(self, kind, **kw):
        self.audit.append({"kind": kind, **kw})


def _tokens(s: str) -> int:
    return max(1, len((s or "").split()))


class MemorySearchService:
    def __init__(self, store: Optional[InMemoryExperienceStore] = None, router: Optional[RuleRouterV1] = None):
        self.store = store or InMemoryExperienceStore()
        self.router = router or RuleRouterV1()

    # --- search: METADATA ONLY ---
    def search_experiences(self, session: SearchSession, task: TaskContext, query: str,
                           subtask: Optional[str] = None, top_k: int = 10) -> list:
        if session.mode == "off":
            session._log("search_skipped", reason="mode_off")
            return []
        if session.rounds >= session.max_search_rounds:
            session._log("search_budget_exhausted", rounds=session.rounds)
            return []
        session.rounds += 1
        cands = self.store.search(session.org_id, task.repository, query, top_k=top_k)
        session._log("search", round=session.rounds, subtask=subtask or task.subtask,
                     query_tokens=_tokens(query), n_candidates=len(cands),
                     candidate_versions=[c.version_id for c in cands])
        # return metadata-only dicts (never execution view)
        return [self._summary_dict(c) for c in cands]

    # --- router decision for a candidate (persisted; used to gate browse) ---
    def decide(self, session: SearchSession, task: TaskContext, trajectory: TrajectoryState,
               candidate: CandidateSummary, policy: Optional[Policy] = None):
        pol = policy or Policy(mode=session.mode)
        # agentic_reference = ungated literature-style selection: approve by similarity/verification only
        if session.mode == "agentic_reference":
            approve = candidate.source_verified and candidate.governance_state in ("promoted", "probation")
            dec = _ref_decision(candidate, approve)
        else:
            rc = self._to_router_candidate(candidate)
            tr = TrajectoryState(is_stuck=trajectory.is_stuck, is_repeating=trajectory.is_repeating,
                                 plan_terms=trajectory.plan_terms, tried_operations=trajectory.tried_operations,
                                 browsed_card_keys=session.browsed_keys)
            dec = self.router.decide(task, tr, rc, pol)
        session._log("decision", card_key=candidate.card_key, version_id=candidate.version_id,
                     decision=dec.decision, reason_codes=dec.reason_codes, score=dec.score, mode=session.mode)
        return dec

    # --- browse: EXECUTION VIEW, only after approval + budgets ---
    def browse_experience(self, session: SearchSession, task: TaskContext, trajectory: TrajectoryState,
                          candidate: CandidateSummary, policy: Optional[Policy] = None) -> Optional[dict]:
        dec = self.decide(session, task, trajectory, candidate, policy)
        approved = dec.decision == "USE"
        # shadow mode: persist the decision but never inject
        if session.mode == "shadow":
            session._log("browse_shadow", card_key=candidate.card_key, would_use=approved)
            return None
        if not approved:
            return None
        if candidate.card_key in session.browsed_keys:
            session._log("browse_idempotent_noop", card_key=candidate.card_key)
            return None
        if len(session.browsed_keys) >= session.max_browse or len(session.browsed_keys) >= session.max_cards:
            session._log("browse_budget_exhausted", browsed=len(session.browsed_keys))
            return None
        view = self.store.execution_view_for(session.org_id, candidate.version_id)
        cost = _tokens(str(view))
        if session.injected_tokens + cost > session.max_injected_tokens:
            session._log("browse_token_budget_exhausted", have=session.injected_tokens, need=cost)
            return None
        session.browsed_keys.append(candidate.card_key)
        session.injected_tokens += cost
        session._log("browse_injected", card_key=candidate.card_key, version_id=candidate.version_id,
                     injected_tokens=cost, reason_codes=dec.reason_codes)
        return view

    def explain_decision(self, session: SearchSession) -> list:
        return [e for e in session.audit if e["kind"] == "decision"]

    # --- helpers ---
    @staticmethod
    def _summary_dict(c: CandidateSummary) -> dict:
        return {"card_key": c.card_key, "version_id": c.version_id, "title": c.title,
                "repository_scope": c.repository_scope, "framework": c.framework, "language": c.language,
                "version_scope": c.version_scope, "path_scope": c.path_scope,
                "governance_state": c.governance_state, "similarity": c.similarity,
                "similarity_margin": c.similarity_margin, "reason_tags": c.reason_tags,
                "source_verified": c.source_verified}

    @staticmethod
    def _to_router_candidate(c: CandidateSummary) -> Candidate:
        return Candidate(
            card_key=c.card_key, version_id=c.version_id, governance_state=c.governance_state,
            source_verified=c.source_verified, repository_scope=c.repository_scope, path_scope=c.path_scope,
            version_scope=c.version_scope, language=c.language, framework=c.framework,
            affected_apis=c.affected_apis, affected_symbols=c.affected_symbols,
            symptom_signature=c.symptom_signature, operation=c.operation, similarity=c.similarity,
            similarity_margin=c.similarity_margin, provides_executable_action=c.provides_executable_action,
            generic_advice_only=c.generic_advice_only)


def _ref_decision(candidate, approve):
    from ..router.rule_router_v1 import UtilityDecision
    from ..router import reason_codes as RC
    return UtilityDecision(
        decision="USE" if approve else "ABSTAIN",
        reason_codes=[RC.USE_NEW_VERIFIED_ACTION] if approve else [RC.ABSTAIN_UNVERIFIED],
        feature_values={"mode": "agentic_reference"}, policy_version="agentic_reference",
        candidate_id=candidate.card_key, candidate_version_id=candidate.version_id,
        score=candidate.similarity, estimated_novelty=0.0, estimated_applicability=candidate.similarity,
        estimated_actionability=1.0 if approve else 0.0, estimated_risk=0.0)
