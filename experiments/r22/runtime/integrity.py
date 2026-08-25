"""R22 §7/§9 — integrity checks over a set of task-arm records (no model calls). Fail-closed."""
from __future__ import annotations

import hashlib
from typing import List

from .arm_payload import MEMORY_ENABLED, HISTORICAL_CONTENT


def check_cell(rec: dict) -> List[str]:
    """Per-cell invariants. Returns a list of violation strings (empty = clean)."""
    v = []
    arm = rec["arm"]
    inj = rec.get("injection") or {}
    # O0: no memory search, no injection
    if arm == "O0" and (rec.get("memory_search_calls", 0) != 0 or inj.get("text")):
        v.append("O0 had memory search/injection")
    # O1: no historical content
    if arm == "O1" and inj.get("historical_content"):
        v.append("O1 carried historical content")
    # injected_view_hash == sha256(payload bytes)
    if inj.get("text") is not None:
        h = hashlib.sha256(inj["text"].encode("utf-8")).hexdigest()
        if inj.get("byte_hash") != h:
            v.append("injection hash mismatch")
    # source_user != target_user for memory arms
    if MEMORY_ENABLED[arm] and inj.get("source_user") and inj.get("source_user") == inj.get("target_user"):
        v.append("source_user == target_user")
    # target leakage: target id/gold/test tokens must not be in the injected text
    for tok in rec.get("target_leak_tokens", []):
        if tok and inj.get("text") and tok in inj["text"]:
            v.append("target token in injection: %s" % tok[:20])
    # returned model present
    if not rec.get("returned_model"):
        v.append("missing returned model")
    return v


def check_campaign(records: List[dict], expected_cells: int, o2_derangement: dict) -> dict:
    keys = set()
    violations = []
    o3_selected = 0
    for r in records:
        k = (r["target_id"], r["arm"])
        if k in keys:
            violations.append("duplicate cell %s" % (k,))
        keys.add(k)
        violations += ["%s/%s: %s" % (r["target_id"], r["arm"], m) for m in check_cell(r)]
        if r["arm"] == "O2":
            src = (r.get("injection") or {}).get("source_id")
            if src == r["target_id"]:
                violations.append("O2 fixed point at %s" % r["target_id"])
            elif o2_derangement and o2_derangement.get(r["target_id"]) not in (None, src):
                violations.append("O2 source != frozen derangement at %s" % r["target_id"])
        if r.get("selected_as_product") and r["arm"] == "O3":
            o3_selected += 1
    complete = len(keys) == expected_cells
    return {"complete": complete, "cells": len(keys), "expected": expected_cells,
            "o3_product_selections": o3_selected, "violations": violations,
            "clean": complete and not violations and o3_selected == 0}
