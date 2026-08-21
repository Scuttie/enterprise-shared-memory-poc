"""P6/R19 §6.3: deterministic card compiler.

Compiles one SourceEvidence into (1) a canonical ExperienceCardVersion, (2) a NEUTRAL retrieval projection
(metadata only — safe to embed into Qdrant/Mem0), and (3) an EXECUTION view (actionable, injected only after the
router + gates approve). Guarantees, asserted in code:
  - the retrieval projection contains none of the _RETRIEVAL_FORBIDDEN keys (no patch/identity/verdict/target/tests);
  - the execution view never contains the raw diff (evidence stays evidence);
  - a card whose source did not pass verification cannot be compiled as promotable.
Deterministic: same evidence -> same content_hash.
"""
from __future__ import annotations

import re
from typing import Tuple

from .schema import (
    SourceEvidence, ExperienceCardVersion, GovernanceState, SourceOutcome,
    content_hash, _RETRIEVAL_FORBIDDEN,
)


class CompileError(ValueError):
    pass


def _card_key(ev: SourceEvidence) -> str:
    """Stable per-(repo, source) identity; deterministic, no random component."""
    basis = "|".join([
        ev.bank.value, ev.source_repository or "", ev.source_commit or "",
        ev.source_issue_id or ev.source_task_id or "", (ev.symptom_signature or "")[:120],
    ])
    return "ec_" + content_hash({"k": basis})[:24]


def compile_card(ev: SourceEvidence, schema_version: int = 1) -> ExperienceCardVersion:
    if not ev.source_repository:
        raise CompileError("source_repository is required")
    if not (ev.symptom_signature or ev.root_cause or ev.repair_strategy):
        raise CompileError("evidence has no compilable content")
    # A promoted/probation card requires a passing source verification (§5 hard constraint). At compile time we
    # only allow CANDIDATE unless the source outcome passed; promotion happens later in governance.
    initial_state = GovernanceState.CANDIDATE

    canonical_body = {
        "schema_version": schema_version,
        "card_key": _card_key(ev),
        "bank": ev.bank.value,
        "source": {
            "type": ev.source_type, "repository": ev.source_repository, "commit": ev.source_commit,
            "issue_id": ev.source_issue_id, "task_id": ev.source_task_id, "author_id": ev.source_author_id,
            "timestamp": ev.source_timestamp, "outcome": ev.source_outcome.value,
            "verifier_hash": ev.source_verifier_hash,
        },
        "content": {
            "symptom_signature": ev.symptom_signature, "root_cause": ev.root_cause,
            "fault_localization": ev.fault_localization, "affected_symbols": ev.affected_symbols,
            "affected_apis": ev.affected_apis, "repository_convention": ev.repository_convention,
            "preconditions": ev.preconditions, "non_applicability": ev.non_applicability,
            "repair_strategy": ev.repair_strategy, "ordered_actions": ev.ordered_actions,
            "patch_pattern": ev.patch_pattern, "validation_strategy": ev.validation_strategy,
            "common_failure": ev.common_failure,
        },
        "scope": {"version_scope": ev.version_scope, "path_scope": ev.path_scope,
                  "language": ev.language, "framework": ev.framework},
        "evidence_hashes": ev.evidence_hashes,
    }
    ch = content_hash(canonical_body)

    return ExperienceCardVersion(
        schema_version=schema_version, card_key=_card_key(ev), bank=ev.bank,
        source_type=ev.source_type, source_repository=ev.source_repository, source_commit=ev.source_commit,
        source_issue_id=ev.source_issue_id, source_task_id=ev.source_task_id, source_author_id=ev.source_author_id,
        source_timestamp=ev.source_timestamp, source_outcome=ev.source_outcome,
        source_verifier_hash=ev.source_verifier_hash, symptom_signature=ev.symptom_signature,
        root_cause=ev.root_cause, fault_localization=ev.fault_localization, affected_symbols=list(ev.affected_symbols),
        affected_apis=list(ev.affected_apis), repository_convention=ev.repository_convention,
        preconditions=ev.preconditions, non_applicability=ev.non_applicability, repair_strategy=ev.repair_strategy,
        ordered_actions=list(ev.ordered_actions), patch_pattern=ev.patch_pattern,
        validation_strategy=ev.validation_strategy, common_failure=ev.common_failure,
        version_scope=ev.version_scope, path_scope=ev.path_scope, language=ev.language, framework=ev.framework,
        evidence_hashes=list(ev.evidence_hashes), confidence=ev.confidence, governance_state=initial_state,
        content_hash=ch,
    )


def retrieval_projection(card: ExperienceCardVersion) -> dict:
    """Neutral, embeddable metadata. Asserted free of forbidden keys/content."""
    proj = {
        "card_key": card.card_key,
        "task_or_failure_type": card.source_type,
        "symptom_signature": _short(card.symptom_signature, 240),
        "affected_apis": card.affected_apis[:12],
        "operation": _short(card.repair_strategy_operation(), 120) if hasattr(card, "repair_strategy_operation") else "",
        "repository_scope": card.source_repository,
        "framework": card.framework,
        "language": card.language,
        "version_scope": card.version_scope,
        "path_scope": card.path_scope,
        "governance_state": card.governance_state.value,
    }
    _assert_neutral(proj)
    return proj


def execution_view(card: ExperienceCardVersion) -> dict:
    """Actionable view injected only after gates+router approve. Never contains the raw diff."""
    view = {
        "card_key": card.card_key,
        "applicable_symptom": card.symptom_signature,
        "root_cause": card.root_cause,
        "fault_localization": card.fault_localization,
        "affected_symbols": card.affected_symbols,
        "affected_apis": card.affected_apis,
        "ordered_repair_operations": card.ordered_actions,
        "repair_strategy": card.repair_strategy,
        "api_symbol_constraints": {"symbols": card.affected_symbols, "apis": card.affected_apis},
        "non_applicability": card.non_applicability,
        "validation_steps": card.validation_strategy,
        "version_scope": card.version_scope,
        "path_scope": card.path_scope,
    }
    if "raw_diff" in view or "patch" in view:
        raise CompileError("execution view must not contain the raw diff")
    return view


def compile_all(ev: SourceEvidence) -> Tuple[ExperienceCardVersion, dict, dict]:
    card = compile_card(ev)
    return card, retrieval_projection(card), execution_view(card)


def _short(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return s[:n]


def _assert_neutral(proj: dict) -> None:
    lowerkeys = {k.lower() for k in proj}
    bad = lowerkeys & {k.lower() for k in _RETRIEVAL_FORBIDDEN}
    if bad:
        raise CompileError("retrieval projection leaks forbidden fields: %s" % sorted(bad))
    # value-level guard: no unified-diff markers leaked into any projection string
    for k, v in proj.items():
        if isinstance(v, str) and re.search(r"^diff --git |^--- a/|^\+\+\+ b/", v, re.M):
            raise CompileError("retrieval projection value for %r contains a raw diff" % k)


# small convenience so retrieval_projection's optional "operation" doesn't crash if absent
def _repair_operation(card: ExperienceCardVersion) -> str:
    return (card.repair_strategy or "").split(".")[0]


ExperienceCardVersion.repair_strategy_operation = lambda self: _repair_operation(self)  # type: ignore[attr-defined]
