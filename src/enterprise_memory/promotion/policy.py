"""Promotion state machine (handoff §5.2). private episode -> candidate -> schema -> security -> source
tests -> scope/anti-scope -> validity -> conflict -> held-out replay -> promoted|quarantined|private-only.
Every rejection is persisted (candidate id, failed gate, reason, evidence hash, state). No unconditional
force-promote."""
from __future__ import annotations
import hashlib
import json
from . import security_scan as SEC

PROMOTED, QUARANTINED, PRIVATE_ONLY = "promoted", "quarantined", "private-only"


def _evhash(o):
    return "sha256:" + hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:24]


def evaluate_candidate(contract, source_episode_passed: bool, regression_passed: bool,
                       replay_applicable_success: bool, replay_nonapplicable_rejected: bool,
                       existing_promoted: list = None, candidate_text: str = ""):
    """Returns (state, reason, evidence). existing_promoted = list of dicts {contract_id, scope_key,
    equivalent, contradictory} for conflict handling."""
    ev = {"candidate": contract.contract_id}

    def reject(gate, reason, state=PRIVATE_ONLY):
        ev.update({"failed_gate": gate, "reason": reason, "state": state})
        return (state, reason, {**ev, "evidence_hash": _evhash(ev)})

    # schema
    errs = contract.validate()
    if errs:
        return reject("schema", ";".join(errs))
    # security
    ok, scan = SEC.is_promotable(candidate_text or contract.canonical_summary)
    if not ok:
        return reject("security", scan["result"], state=QUARANTINED if scan["result"] == SEC.BLOCK_SECRET else PRIVATE_ONLY)
    # source + regression tests
    if not source_episode_passed:
        return reject("source_test", "source_task_failed")
    if not regression_passed:
        return reject("regression", "regression_failed")
    # scope / anti-scope explicitness
    sc = contract.scope
    if not (sc.repo_ids or sc.org_id):
        return reject("scope", "no_repo_or_org")
    if not sc.applies_when:
        return reject("scope", "empty_applies_when")
    if not sc.does_not_apply_when:
        return reject("anti_scope", "empty_does_not_apply_when")
    if not contract.verification.test_commands:
        return reject("verification", "no_verification")
    if not (contract.provenance.source_episode_ids and contract.provenance.source_commit_shas):
        return reject("provenance", "incomplete_provenance")
    # conflict handling
    for other in (existing_promoted or []):
        if other.get("equivalent"):
            ev["merge_into"] = other["contract_id"]
            return (PROMOTED, "merged_duplicate_evidence", {**ev, "evidence_hash": _evhash(ev), "merge": True})
        if other.get("contradictory"):
            return reject("conflict", "unresolved_contradiction", state=QUARANTINED)
    # held-out replay
    if not replay_applicable_success:
        return reject("replay", "applicable_replay_failed", state=QUARANTINED)
    if not replay_nonapplicable_rejected:
        return reject("replay", "nonapplicable_not_rejected", state=QUARANTINED)
    ev.update({"failed_gate": None, "reason": "all_gates_passed", "state": PROMOTED})
    return (PROMOTED, "all_gates_passed", {**ev, "evidence_hash": _evhash(ev)})
