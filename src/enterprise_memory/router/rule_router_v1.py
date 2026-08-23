"""P6/R19 §8 — utility-aware router. Deterministic, inspectable RuleRouterV1.

decide(task_context, trajectory_state, candidate, policy) -> UtilityDecision(USE|ABSTAIN, reason_codes, features...).

Only PUBLIC / current-trajectory features are used (§8.2). It is a hard error for any target gold patch, hidden
test, final verifier verdict, experiment arm, or future outcome to reach the router — sentinel keys are rejected
fail-closed (§22). Scoring weights are frozen (dev-selected; never tuned on held-out outcomes).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import reason_codes as RC

# ---- frozen scoring weights (RuleRouterV1; selected on development data only) ----
WEIGHTS = {
    "applicability": 1.0, "actionability": 1.0, "novelty": 0.8, "evidence": 0.6, "direct_grounding": 1.2,
    "redundancy": 1.0, "version_risk": 1.5, "scope_risk": 1.5, "mismatch": 1.0,
}
USE_THRESHOLD = 1.0        # utility must clear this
MIN_MARGIN = 0.25          # and beat the abstain-pull by this margin

# sentinel keys that must NEVER be present in any router input (leakage guard, §8.2/§22)
_FORBIDDEN_FEATURE_KEYS = frozenset({
    "gold_patch", "target_gold", "hidden_tests", "target_tests", "final_verdict",
    "verifier_verdict", "future_outcome", "experiment_arm", "arm", "resolved",
})


class RouterLeakageError(RuntimeError):
    """Raised fail-closed if a forbidden (gold/test/verdict/arm/future) field reaches the router."""


@dataclass
class TaskContext:
    org_id: str
    repository: str
    path_scope: str = ""
    language: str = ""
    framework: str = ""
    version: str = ""
    subtask: str = "localization"           # comprehension|localization|modification|validation
    permitted: bool = True                   # tenant/permission pre-checked by the pipeline; router re-asserts
    target_apis: list = field(default_factory=list)
    target_symbols: list = field(default_factory=list)
    error_signature: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class TrajectoryState:
    is_stuck: bool = False
    is_repeating: bool = False
    plan_terms: list = field(default_factory=list)         # terms already in the agent's current plan
    tried_operations: list = field(default_factory=list)   # operations already attempted this run
    browsed_card_keys: list = field(default_factory=list)  # cards already browsed this session


@dataclass
class Candidate:
    card_key: str
    version_id: str
    governance_state: str = "promoted"
    source_verified: bool = False
    repository_scope: str = ""
    path_scope: str = ""
    version_scope: str = ""
    language: str = ""
    framework: str = ""
    affected_apis: list = field(default_factory=list)
    affected_symbols: list = field(default_factory=list)
    symptom_signature: str = ""
    operation: str = ""                       # the concrete repair operation offered
    similarity: float = 0.0
    similarity_margin: float = 0.0            # gap to the next candidate
    provides_executable_action: bool = False
    generic_advice_only: bool = False
    contradicts_target: bool = False
    contains_secret_or_pii: bool = False
    prior_gain_rate: Optional[float] = None   # outcome stats for this card under comparable contexts
    prior_uses: int = 0


@dataclass
class Policy:
    policy_version: str = "rule_router_v1"
    mode: str = "utility_gated"               # off|static_relevant|agentic_reference|utility_gated|shadow
    use_threshold: float = USE_THRESHOLD
    min_margin: float = MIN_MARGIN
    weights: dict = field(default_factory=lambda: dict(WEIGHTS))


@dataclass
class UtilityDecision:
    decision: str                              # "USE" | "ABSTAIN"
    reason_codes: list
    feature_values: dict
    policy_version: str
    candidate_id: str
    candidate_version_id: str
    score: float
    estimated_novelty: float
    estimated_applicability: float
    estimated_actionability: float
    estimated_risk: float


def _overlap(a, b) -> int:
    sa = {str(x).lower() for x in (a or [])}
    sb = {str(x).lower() for x in (b or [])}
    return len(sa & sb)


def _assert_no_leakage(*objs) -> None:
    for o in objs:
        d = getattr(o, "extra", None)
        for src in ([o.__dict__] + ([d] if isinstance(d, dict) else [])):
            for k in src:
                if k.lower() in _FORBIDDEN_FEATURE_KEYS:
                    raise RouterLeakageError("forbidden feature key reached router: %r" % k)


class RuleRouterV1:
    """Deterministic, inspectable. No model calls, no randomness."""

    policy_version = "rule_router_v1"

    def decide(self, task_context: TaskContext, trajectory_state: TrajectoryState,
               candidate: Candidate, policy: Optional[Policy] = None) -> UtilityDecision:
        pol = policy or Policy()
        _assert_no_leakage(task_context, trajectory_state, candidate)

        f: dict = {}
        reasons: list = []

        def out(decision, score, extra_reasons=None):
            rs = list(dict.fromkeys((extra_reasons or []) + reasons))
            return UtilityDecision(
                decision=decision, reason_codes=rs, feature_values=f, policy_version=pol.policy_version,
                candidate_id=candidate.card_key, candidate_version_id=candidate.version_id, score=round(score, 4),
                estimated_novelty=f.get("novelty", 0.0), estimated_applicability=f.get("applicability", 0.0),
                estimated_actionability=f.get("actionability", 0.0), estimated_risk=f.get("risk", 0.0))

        # ---------- 8.1 hard gate (fail closed) ----------
        if not task_context.permitted:
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_HIGH_RISK])
        if candidate.contains_secret_or_pii or candidate.contradicts_target:
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_HIGH_RISK])
        if candidate.governance_state not in ("promoted", "probation"):
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_UNVERIFIED])
        if not candidate.source_verified:
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_UNVERIFIED])
        # scope: repository must match (path narrows further)
        repo_ok = (candidate.repository_scope or "") == (task_context.repository or "")
        if not repo_ok:
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_SCOPE])
        if candidate.path_scope and task_context.path_scope and \
                not task_context.path_scope.startswith(candidate.path_scope) and \
                not candidate.path_scope.startswith(task_context.path_scope):
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_SCOPE])
        # version incompatibility
        version_mismatch = bool(candidate.version_scope and task_context.version and
                                candidate.version_scope != task_context.version)
        if version_mismatch and not candidate.provides_executable_action:
            f["version_risk"] = 1.0
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_VERSION_MISMATCH])
        # subtask stage: memory is for localization/modification; skip during pure comprehension/validation unless
        # it supplies a concrete action
        if task_context.subtask in ("comprehension", "validation") and not candidate.provides_executable_action:
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_WRONG_STAGE])
        # already browsed/tried
        if candidate.card_key in (trajectory_state.browsed_card_keys or []):
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_ALREADY_TRIED])
        if candidate.operation and candidate.operation.lower() in \
                {str(x).lower() for x in (trajectory_state.tried_operations or [])}:
            return out("ABSTAIN", 0.0, [RC.ABSTAIN_ALREADY_TRIED])

        # ---------- 8.2 incremental-utility features (public only) ----------
        sym = _overlap(candidate.affected_symbols, task_context.target_symbols)
        api = _overlap(candidate.affected_apis, task_context.target_apis)
        sig = 1 if (candidate.symptom_signature and task_context.error_signature and
                    _sig_match(candidate.symptom_signature, task_context.error_signature)) else 0
        direct_grounding = 1.0 if (sym or api or sig) else 0.0
        applicability = min(1.0, 0.5 * repo_ok + 0.25 * (api > 0) + 0.25 * (sym > 0))
        actionability = 1.0 if (candidate.provides_executable_action and not candidate.generic_advice_only) else 0.0
        # novelty: not already in the plan, and either agent is stuck or it adds a new operation
        plan = {str(x).lower() for x in (trajectory_state.plan_terms or [])}
        op_new = candidate.operation and candidate.operation.lower() not in plan
        novelty = 0.0
        if candidate.generic_advice_only:
            novelty = 0.0
        elif op_new and (trajectory_state.is_stuck or actionability):
            novelty = 1.0
        elif op_new:
            novelty = 0.5
        evidence = 1.0 if candidate.source_verified else 0.0
        if candidate.prior_gain_rate is not None and candidate.prior_uses >= 3:
            evidence = min(1.0, evidence * (0.5 + candidate.prior_gain_rate))
        redundancy = 1.0 if (candidate.generic_advice_only or (not op_new and not direct_grounding)) else 0.0
        scope_risk = 0.0  # repo already matched; path checked
        version_risk = 1.0 if version_mismatch else 0.0
        # theme-only: some similarity but no direct grounding and no actionable delta
        theme_only = (candidate.similarity >= 0.4 and direct_grounding == 0.0 and actionability == 0.0)
        mismatch = 1.0 if theme_only else 0.0

        f.update(dict(applicability=applicability, actionability=actionability, novelty=novelty,
                      evidence=evidence, direct_grounding=direct_grounding, redundancy=redundancy,
                      version_risk=version_risk, scope_risk=scope_risk, mismatch=mismatch,
                      symbol_overlap=sym, api_overlap=api, signature_match=sig,
                      similarity=candidate.similarity, similarity_margin=candidate.similarity_margin))
        w = pol.weights
        utility = (w["applicability"] * applicability + w["actionability"] * actionability +
                   w["novelty"] * novelty + w["evidence"] * evidence + w["direct_grounding"] * direct_grounding
                   - w["redundancy"] * redundancy - w["version_risk"] * version_risk
                   - w["scope_risk"] * scope_risk - w["mismatch"] * mismatch)
        f["risk"] = round(w["version_risk"] * version_risk + w["scope_risk"] * scope_risk +
                          w["mismatch"] * mismatch, 4)
        f["utility"] = round(utility, 4)

        # ---------- decision ----------
        if actionability == 0.0 and direct_grounding == 0.0:
            return out("ABSTAIN", utility, [RC.ABSTAIN_NO_ACTIONABLE_DELTA])
        if redundancy >= 1.0:
            return out("ABSTAIN", utility, [RC.ABSTAIN_REDUNDANT])
        if theme_only:
            return out("ABSTAIN", utility, [RC.ABSTAIN_THEME_ONLY])
        if utility < pol.use_threshold:
            return out("ABSTAIN", utility, [RC.ABSTAIN_LOW_MARGIN])
        if candidate.similarity_margin and candidate.similarity_margin < 0.02 and direct_grounding == 0.0:
            return out("ABSTAIN", utility, [RC.ABSTAIN_LOW_MARGIN])

        # USE — pick the most specific supporting reason
        use_reason = RC.USE_NEW_VERIFIED_ACTION
        if sym:
            use_reason = RC.USE_DIRECT_SYMBOL_MATCH
        elif api:
            use_reason = RC.USE_DIRECT_API_MATCH
        elif sig:
            use_reason = RC.USE_FAILURE_SIGNATURE_MATCH
        elif version_mismatch and candidate.provides_executable_action:
            use_reason = RC.USE_VERSION_COMPATIBLE_WORKAROUND
        return out("USE", utility, [use_reason])


def _sig_match(a: str, b: str) -> bool:
    ta = {w for w in a.lower().split() if len(w) > 3}
    tb = {w for w in b.lower().split() if len(w) > 3}
    return len(ta & tb) >= 2
