#!/usr/bin/env python3
"""R22 §7.2 — stage-level gain/loss + patch-adoption classification from stored evidence (no model calls)."""
from collections import defaultdict


def stage_and_adoption(records):
    by_target = defaultdict(dict)
    for r in records:
        by_target[r["target_id"]][r["arm"]] = r
    stage_counts = defaultdict(lambda: {"gain": 0, "loss": 0})
    adoption = defaultdict(int)
    for t, arms in by_target.items():
        o0 = arms.get("O0", {}).get("resolved")
        for arm in ("O4", "O5", "O6", "O3"):
            r = arms.get(arm)
            if not r:
                continue
            if r["resolved"] and not o0:
                stage_counts[r["stage"]]["gain"] += 1
            if (not r["resolved"]) and o0:
                stage_counts[r["stage"]]["loss"] += 1
        # adoption uses actual browse + patch evidence, not just a changed patch
        best = arms.get("O6") or arms.get("O5") or {}
        if best.get("resolved") and best.get("browse_calls", 0) > 0 and not arms.get("O5", {}).get("selected_as_product"):
            adoption["ACTION_ADOPTED_or_CONTENT"] += 1
        elif best and not best.get("resolved") and best.get("browse_calls", 0) > 0:
            adoption["DISTRACTION_or_WRONG_PRECEDENT"] += 1
        else:
            adoption["NO_BEHAVIOR_CHANGE"] += 1
    return {"by_stage": dict(stage_counts), "adoption": dict(adoption)}
