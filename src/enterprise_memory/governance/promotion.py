"""P6/R19 §9 — outcome-aware governance state machine with FROZEN thresholds.

candidate -> probation (after source verification) -> promoted (reviewed criteria) ; repeated MEMORY_LOSS ->
quarantine ; version invalidation -> deprecate. Manual review always overrides automated promotion; there is no
force-promote bypass. Thresholds are frozen before live evaluation (artifacts/p6/governance_thresholds.json).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..experience.schema import GovernanceState

# FROZEN thresholds (dev-selected; do not tune on held-out outcomes)
PROMOTE_MIN_GAINS = 2          # distinct MEMORY_GAIN targets required in probation
PROMOTE_MAX_LOSSES = 0         # zero losses allowed before promotion
QUARANTINE_MIN_LOSSES = 2      # repeated losses trigger quarantine
CONFIDENCE_STEP = 0.1


@dataclass
class CardStats:
    gains: int = 0
    losses: int = 0
    neutral: int = 0
    confidence: float = 0.0


class GovernanceError(RuntimeError):
    pass


class GovernanceMachine:
    """Pure decision functions; the repository applies the returned target state + audits it."""

    def on_source_verified(self, state: GovernanceState, source_passed: bool) -> GovernanceState:
        if not source_passed:
            # a card whose source did not pass verification can never leave candidate
            return state
        if state == GovernanceState.CANDIDATE:
            return GovernanceState.PROBATION
        return state

    def evaluate(self, state: GovernanceState, stats: CardStats, reviewed: bool) -> GovernanceState:
        # quarantine takes precedence on repeated harm, regardless of review
        if stats.losses >= QUARANTINE_MIN_LOSSES:
            return GovernanceState.QUARANTINED
        if state == GovernanceState.PROBATION:
            if stats.gains >= PROMOTE_MIN_GAINS and stats.losses <= PROMOTE_MAX_LOSSES and reviewed:
                return GovernanceState.PROMOTED
        return state

    def promote(self, state: GovernanceState, stats: CardStats, reviewed: bool) -> GovernanceState:
        # explicit promote requires manual review + criteria; no force bypass
        if not reviewed:
            raise GovernanceError("promotion requires manual review (no force-promote bypass)")
        if state != GovernanceState.PROBATION:
            raise GovernanceError("only probation cards may be promoted")
        if stats.gains < PROMOTE_MIN_GAINS or stats.losses > PROMOTE_MAX_LOSSES:
            raise GovernanceError("promotion criteria not met")
        return GovernanceState.PROMOTED

    def on_version_invalidated(self, state: GovernanceState) -> GovernanceState:
        if state in (GovernanceState.PROMOTED, GovernanceState.PROBATION):
            return GovernanceState.DEPRECATED
        return state

    def apply_credit(self, stats: CardStats, outcome_class: str) -> CardStats:
        from .outcome import MEMORY_GAIN, MEMORY_LOSS, MEMORY_NEUTRAL
        if outcome_class == MEMORY_GAIN:
            stats.gains += 1
            stats.confidence = min(1.0, stats.confidence + CONFIDENCE_STEP)
        elif outcome_class == MEMORY_LOSS:
            stats.losses += 1
            stats.confidence = max(0.0, stats.confidence - CONFIDENCE_STEP)
        elif outcome_class == MEMORY_NEUTRAL:
            stats.neutral += 1
        return stats
