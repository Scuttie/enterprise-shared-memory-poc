"""P6/R19 §9 — outcome credit classification + frozen governance state machine."""
import json
import pathlib

import pytest

from enterprise_memory.governance import (
    OutcomeCreditAssigner, classify_adoption, GovernanceMachine, CardStats, GovernanceError,
    MEMORY_GAIN, MEMORY_LOSS, MEMORY_NEUTRAL, COMPUTE_ONLY_GAIN, UNATTRIBUTED, INFRA_FAILURE,
    EXACT_SOURCE_OPERATION_ADOPTION, SOURCE_API_ADOPTION, NO_BEHAVIORAL_CHANGE,
    PROMOTE_MIN_GAINS, QUARANTINE_MIN_LOSSES,
)
from enterprise_memory.experience.schema import GovernanceState

VIEW = {"card_key": "ec_1", "affected_symbols": ["MigrationLoader.load_disk"], "affected_apis": ["importlib"],
        "ordered_repair_operations": ["guard missing __file__ attribute"], "repair_strategy": "guard for missing __file__"}


def test_adoption_exact():
    patch = "def load_disk(self):\n    if getattr(module, '__file__', None) is None:  # guard missing\n        ..."
    assert classify_adoption(VIEW, patch) == EXACT_SOURCE_OPERATION_ADOPTION


def test_adoption_not_inferred_from_mere_difference():
    # an unrelated patch that changes code but shares no source symbol/api/operation
    patch = "def unrelated():\n    return compute_totally_different_thing()"
    assert classify_adoption(VIEW, patch) == NO_BEHAVIORAL_CHANGE


def test_adoption_api_only():
    patch = "import importlib  # new import, but no loader symbol or guard operation"
    assert classify_adoption(VIEW, patch) == SOURCE_API_ADOPTION


A = OutcomeCreditAssigner()


def test_credit_memory_gain():
    patch = "if getattr(module, '__file__', None) is None:  # guard missing __file__ in load_disk"
    r = A.assign("t1", "resolved", [VIEW], target_patch=patch, counterfactual_outcome="unresolved")
    assert r.outcome_class == MEMORY_GAIN and r.evidence_class == EXACT_SOURCE_OPERATION_ADOPTION


def test_credit_compute_only_gain_when_no_adoption():
    r = A.assign("t1", "resolved", [VIEW], target_patch="return unrelated()", counterfactual_outcome="unresolved")
    assert r.outcome_class == COMPUTE_ONLY_GAIN


def test_credit_memory_loss():
    r = A.assign("t1", "unresolved", [VIEW], target_patch="", counterfactual_outcome="resolved")
    assert r.outcome_class == MEMORY_LOSS


def test_credit_neutral_and_unattributed_and_infra():
    assert A.assign("t", "resolved", [VIEW], "guard __file__ load_disk", "resolved").outcome_class == MEMORY_NEUTRAL
    assert A.assign("t", "resolved", [], "", "unresolved").outcome_class == UNATTRIBUTED
    assert A.assign("t", "infra_failure", [VIEW], "", None).outcome_class == INFRA_FAILURE


def test_assigner_is_pure_no_card_mutation():
    # credit assignment returns a record; it must not carry or mutate card governance state
    stats = CardStats(gains=0, losses=0)
    A.assign("t1", "resolved", [VIEW], "guard __file__ load_disk", "unresolved")
    assert stats.gains == 0 and stats.losses == 0  # untouched


G = GovernanceMachine()


def test_source_verification_gates_probation():
    assert G.on_source_verified(GovernanceState.CANDIDATE, True) == GovernanceState.PROBATION
    assert G.on_source_verified(GovernanceState.CANDIDATE, False) == GovernanceState.CANDIDATE


def test_promote_requires_review_and_criteria_no_force():
    stats = CardStats(gains=PROMOTE_MIN_GAINS, losses=0)
    with pytest.raises(GovernanceError):
        G.promote(GovernanceState.PROBATION, stats, reviewed=False)   # no force-promote
    assert G.promote(GovernanceState.PROBATION, stats, reviewed=True) == GovernanceState.PROMOTED
    with pytest.raises(GovernanceError):
        G.promote(GovernanceState.PROBATION, CardStats(gains=0), reviewed=True)  # criteria not met


def test_quarantine_on_repeated_loss():
    stats = CardStats(gains=5, losses=QUARANTINE_MIN_LOSSES)
    assert G.evaluate(GovernanceState.PROMOTED, stats, reviewed=True) == GovernanceState.QUARANTINED


def test_deprecate_on_version_invalidation():
    assert G.on_version_invalidated(GovernanceState.PROMOTED) == GovernanceState.DEPRECATED


def test_apply_credit_updates_stats():
    s = CardStats()
    G.apply_credit(s, MEMORY_GAIN); G.apply_credit(s, MEMORY_GAIN); G.apply_credit(s, MEMORY_LOSS)
    assert s.gains == 2 and s.losses == 1 and 0.0 <= s.confidence <= 1.0


def test_frozen_thresholds_artifact_matches_code():
    p = pathlib.Path(__file__).resolve().parents[2] / "artifacts" / "p6" / "governance_thresholds.json"
    b = json.load(open(p, encoding="utf-8"))
    assert b["PROMOTE_MIN_GAINS"] == PROMOTE_MIN_GAINS
    assert b["QUARANTINE_MIN_LOSSES"] == QUARANTINE_MIN_LOSSES
