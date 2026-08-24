"""R22 §5,§17 — stage-memory outcome credit + governance transitions (deterministic).

Mirrors the v0.3 lifecycle (candidate -> probation -> promoted; repeated harm -> quarantine) but at stage-record
granularity, and records the patch-adoption class used by the mechanism audit. No model calls.
"""
from __future__ import annotations

from enum import Enum

from .schema import GovernanceState


class StageOutcome(str, Enum):
    GAIN = "MEMORY_GAIN"
    LOSS = "MEMORY_LOSS"
    NEUTRAL = "NEUTRAL"
    COMPUTE_ONLY = "COMPUTE_ONLY"


class AdoptionClass(str, Enum):
    ACTION_ADOPTED = "ACTION_ADOPTED"
    CONTENT_SPECIFIC_GAIN = "CONTENT_SPECIFIC_GAIN"
    COMPUTE_GAIN = "COMPUTE_GAIN"
    NO_BEHAVIOR_CHANGE = "NO_BEHAVIOR_CHANGE"
    DISTRACTION = "DISTRACTION"
    WRONG_PRECEDENT_ADOPTION = "WRONG_PRECEDENT_ADOPTION"


# frozen thresholds (dev-only tuning happens before freeze; recorded here for determinism)
PROMOTE_MIN_GAINS = 2
PROMOTE_MAX_LOSSES = 0
QUARANTINE_LOSS_STREAK = 2


def next_state(state: GovernanceState, gains: int, losses: int, manual_review_ok: bool) -> GovernanceState:
    if state in (GovernanceState.DEPRECATED, GovernanceState.DELETED, GovernanceState.QUARANTINED):
        return state
    if losses >= QUARANTINE_LOSS_STREAK:
        return GovernanceState.QUARANTINED
    if state == GovernanceState.CANDIDATE:
        return GovernanceState.PROBATION           # source verified => probation
    if (state == GovernanceState.PROBATION and gains >= PROMOTE_MIN_GAINS
            and losses <= PROMOTE_MAX_LOSSES and manual_review_ok):
        return GovernanceState.PROMOTED
    return state


def classify_adoption(*, s3_pass: bool, s4_pass: bool, s5_pass: bool,
                      patch_hash_changed: bool, memory_op_matches_patch_ast: bool) -> AdoptionClass:
    if memory_op_matches_patch_ast and s3_pass:
        return AdoptionClass.ACTION_ADOPTED
    if s3_pass and not s4_pass and not s5_pass:
        return AdoptionClass.CONTENT_SPECIFIC_GAIN
    if s3_pass and s5_pass:
        return AdoptionClass.COMPUTE_GAIN
    if not patch_hash_changed:
        return AdoptionClass.NO_BEHAVIOR_CHANGE
    if not s3_pass:
        return AdoptionClass.DISTRACTION
    return AdoptionClass.NO_BEHAVIOR_CHANGE
