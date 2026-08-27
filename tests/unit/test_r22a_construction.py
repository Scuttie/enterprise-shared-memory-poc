"""R22-P0.9.1 §9 — synthetic replacement regression for the R22A manifest generator (no docker, no network).

Drives scripts/r22a_build_manifests.py with a synthetic per-target audit (the real dev58_gradeability_results.json
does not exist yet) over the frozen dev55 metadata + oracle manifests, and proves: gradeable-only selection,
reserve back-fill, 40/280 (P2) and 12/84 (P1), zero self-source / user-collision / O2-fixed-point / leakage,
deterministic outcome-blind reserve priority, and BenchmarkNotViable when < 40 gradeable exist."""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import r22a_build_manifests as R  # noqa: E402

DEV55 = R.load_dev55()
DUAL = {"astropy__astropy-15082": "astropy__astropy-14995",
        "sympy__sympy-12426": "sympy__sympy-12419",
        "sympy__sympy-12427": "sympy__sympy-12419"}
P1_12 = R.load_p1_targets()
ORIG = sorted(t for t, r in DEV55.items() if r["original_status"] == "ORIGINAL_P2")
RES = sorted(t for t, r in DEV55.items() if r["original_status"] == "DEV_RESERVE")
# 3 ungradeable ORIGINAL_P2 that are NOT in the P1 smoke set (keeps the P1 case to the 2 ruff vacancies)
UNGRADE_P2 = ["sympy__sympy-14973", "sympy__sympy-14975", "sympy__sympy-16342"]


def audit_all_gradeable():
    return {t: R.GRADEABLE for t in DEV55}


def audit_p2_three_removed():
    """3 ORIGINAL_P2 UNGRADEABLE (non-P1), all 15 DEV_RESERVE GRADEABLE."""
    a = {t: R.GRADEABLE for t in DEV55}
    for t in UNGRADE_P2:
        a[t] = "UNGRADEABLE_NOOP_MISMATCH"
    return a


def audit_p1_ruff_removed():
    """The 2 failed ruff UNGRADEABLE, the 2 rust DEV_RESERVE GRADEABLE, all P1 keepers GRADEABLE."""
    a = {t: R.GRADEABLE for t in DEV55}
    for t in R.RUFF_FAILED_P1:
        a[t] = "UNGRADEABLE_INFRA"
    return a


# ---------------------------------------------------------------- P2 selection
def test_select_p2_replaces_removed_with_reserves():
    audit = audit_p2_three_removed()
    sel = R.select_p2(audit, DEV55, DUAL)
    assert len(sel) == 40 and len(set(sel)) == 40
    assert all(R.is_gradeable(audit, t) for t in sel)                 # all GRADEABLE
    assert not any(t in sel for t in UNGRADE_P2)                      # removed originals absent
    reserves_in = [t for t in sel if DEV55[t]["original_status"] == "DEV_RESERVE"]
    assert len(reserves_in) == 3                                      # exactly the 3 vacancies filled from reserve
    assert all(t in RES for t in reserves_in)


def test_p2_task_list_and_validation():
    audit = audit_p2_three_removed()
    m = R.build_manifest("p2", audit=audit, dev55=DEV55, dual_pair_selection=DUAL)
    assert m["target_count"] == 40 and m["cell_count"] == 280
    reserves_in = [t for t in {r["target_id"] for r in m["task_list"]}
                   if DEV55[t]["original_status"] == "DEV_RESERVE"]
    chk = R.validate_manifest(m, 40, 280, removed=UNGRADE_P2, reserves=reserves_in)
    assert chk["all_ok"]
    assert chk["source_target_overlap0"] and chk["leakage0"]
    assert chk["user_distinct_ok"] and chk["o2_fixed_points_ok"]
    assert chk["removed_absent"] and chk["reserves_present"]


# ---------------------------------------------------------------- P1 selection
def test_p1_replaces_ruff_with_rust_reserves():
    audit = audit_p1_ruff_removed()
    sel = R.select_p1(audit, P1_12, DUAL, dev55=DEV55)
    assert len(sel) == 12 and len(set(sel)) == 12
    assert not any(t in sel for t in R.RUFF_FAILED_P1)               # failed ruff removed
    added = [t for t in sel if t not in P1_12]
    assert set(added) == {"tokio-rs__axum-1120", "tokio-rs__tokio-3679"}  # same-language rust reserves
    assert all(DEV55[t]["language"] == "rust" for t in added)


def test_p1_task_list_and_validation():
    audit = audit_p1_ruff_removed()
    m = R.build_manifest("p1", audit=audit, dev55=DEV55, dual_pair_selection=DUAL, current_p1_12=P1_12)
    assert m["target_count"] == 12 and m["cell_count"] == 84
    chk = R.validate_manifest(m, 12, 84, removed=list(R.RUFF_FAILED_P1),
                              reserves=["tokio-rs__axum-1120", "tokio-rs__tokio-3679"])
    assert chk["all_ok"]
    assert chk["source_target_overlap0"] and chk["leakage0"]
    assert chk["user_distinct_ok"] and chk["o2_fixed_points_ok"]


# ---------------------------------------------------------------- reserve priority: deterministic + outcome-blind
def test_reserve_priority_deterministic_and_outcome_blind():
    audit = audit_all_gradeable()
    removed = DEV55["astral-sh__ruff-16445"]                          # rust / Multilingual
    cands = [DEV55[t] for t in RES]
    o1 = R.reserve_priority(removed, cands, audit)
    o2 = R.reserve_priority(removed, cands, audit)
    assert o1 == o2                                                   # deterministic
    # outcome-blind: enrich the audit with pass/fail outcomes but the SAME GRADEABLE set -> identical order
    audit_rich = {t: {"label": R.GRADEABLE, "outcome_pass": 1, "resolved": True} for t in DEV55}
    assert R.reserve_priority(removed, cands, audit_rich) == o1
    # rust reserves (same language) rank strictly ahead of python reserves
    rust = [t for t in o1 if DEV55[t]["language"] == "rust"]
    assert set(rust) == {"tokio-rs__axum-1120", "tokio-rs__tokio-3679"}
    assert o1[:len(rust)] == rust                                     # same-language block leads the order
    # eligibility only: a non-GRADEABLE reserve is dropped entirely
    audit_drop = dict(audit)
    audit_drop["tokio-rs__axum-1120"] = "UNGRADEABLE_NOOP_MISMATCH"
    assert "tokio-rs__axum-1120" not in R.reserve_priority(removed, cands, audit_drop)


# ---------------------------------------------------------------- viability floor
def test_select_p2_not_viable_when_under_40():
    # 1 ORIGINAL_P2 removed and NO gradeable reserves -> only 39 gradeable -> raise
    a = {t: R.GRADEABLE for t in DEV55}
    a["sympy__sympy-14973"] = "UNGRADEABLE_INFRA"
    for t in RES:
        a[t] = "UNGRADEABLE_INFRA"
    with pytest.raises(R.BenchmarkNotViable):
        R.select_p2(a, DEV55, DUAL)


def test_manifest_sha_stable():
    audit = audit_p2_three_removed()
    a = R.build_manifest("p2", audit=audit, dev55=DEV55, dual_pair_selection=DUAL)
    b = R.build_manifest("p2", audit=audit, dev55=DEV55, dual_pair_selection=DUAL)
    assert a["manifest_sha256"] == b["manifest_sha256"]
    # sanity: recompute sha over the task_list
    assert a["manifest_sha256"] == R._sha(json.dumps(a["task_list"], sort_keys=True))
