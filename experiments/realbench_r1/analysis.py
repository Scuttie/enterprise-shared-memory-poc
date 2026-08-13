"""REALBENCH-R1 analysis: paired bootstrap CI + exact McNemar for the primary lift, and §14 patch-level
negative/positive transfer classification (uses the persisted applied patches — never inferred from Pass@1)."""
from __future__ import annotations
import math
import random

BOOTSTRAP_SEED = 20260813
BOOTSTRAP_N = 10000


def paired(diffs, r0, r3, tids):
    if not diffs:
        return {"ci": {"mean": 0, "lo": 0, "hi": 0}, "mcnemar": {"b": 0, "c": 0, "p_value": 1.0}, "n": 0}
    rng = random.Random(BOOTSTRAP_SEED); m = len(diffs)
    means = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(BOOTSTRAP_N))
    b = sum(1 for t in tids if r3[t] == 1 and r0[t] == 0)      # R3 gains
    c = sum(1 for t in tids if r0[t] == 1 and r3[t] == 0)      # R3 losses
    n = b + c
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) * 0.5 ** n for i in range(min(b, c) + 1)))
    return {"ci": {"mean": sum(diffs) / len(diffs), "lo": means[int(0.025 * BOOTSTRAP_N)],
                   "hi": means[int(0.975 * BOOTSTRAP_N)]}, "mcnemar": {"b": b, "c": c, "p_value": p}, "n": len(tids)}


def transfer(by, split):
    """For every memory-induced loss (R0 passed, memory arm failed) classify the patch (§14)."""
    r0 = {r["tid"]: r for r in by.get("R0", [])}
    out = {}
    classes = ("EXACT_MEMORY_PATTERN_ADOPTION", "PARTIAL_MEMORY_PATTERN_ADOPTION", "UNRELATED_ERROR",
               "PARSER_OR_GRADER_FAILURE", "UNCLASSIFIED")
    for arm in ("R2", "R3", "R4", "R1"):
        counts = {k: 0 for k in classes}
        losses = gains = 0
        for r in by.get(arm, []):
            base = r0.get(r["tid"])
            if base is None:
                continue
            if base["pass1"] == 1 and r["pass1"] == 0:         # memory-induced loss
                losses += 1
                counts[_classify_loss(r, base)] += 1
            elif base["pass1"] == 0 and r["pass1"] == 1:
                gains += 1
        out[arm] = {"losses": losses, "gains": gains, "loss_classes": counts,
                    "adoption_coverage": (1.0 if losses == 0 else sum(counts.values()) / losses)}
    return out


def _classify_loss(r, base):
    ap = r.get("applied_patch"); bp = base.get("applied_patch")
    if not r.get("exec1"):
        return "PARSER_OR_GRADER_FAILURE"
    if not r.get("injected"):
        return "UNRELATED_ERROR"                               # memory wasn't injected -> not a memory loss
    if ap is None or bp is None:
        return "UNCLASSIFIED"
    if ap == bp:
        return "UNRELATED_ERROR"                               # identical to no-memory patch
    return "PARTIAL_MEMORY_PATTERN_ADOPTION"                    # injected memory + a different (failing) patch
