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
    """SUPERSEDED HEURISTIC (kept only for the frozen R1 main artifact's reproducibility).

    REALBENCH-R2 §1.3: this counted gains/losses but labelled every changed-and-failing memory-arm patch
    PARTIAL_MEMORY_PATTERN_ADOPTION, which is NOT evidence of adoption. It also cannot distinguish adoption
    classes because the R1 runner did not persist applied patches into the results artifact. Use
    transfer_forensic() with persisted patches + source signatures instead (R1.1 diagnostic and R2)."""
    r0 = {r["tid"]: r for r in by.get("R0", [])}
    out = {}
    for arm in ("R2", "R3", "R4", "R1"):
        losses = gains = 0
        for r in by.get(arm, []):
            base = r0.get(r["tid"])
            if base is None:
                continue
            if base["pass1"] == 1 and r["pass1"] == 0:
                losses += 1
            elif base["pass1"] == 0 and r["pass1"] == 1:
                gains += 1
        out[arm] = {"losses": losses, "gains": gains,
                    "classifier": "HEURISTIC_SUPERSEDED_see_transfer_forensic"}
    return out


def transfer_forensic(by, source_sig_by_tid, base_arm="R0", arms=("R2", "R3", "R4", "R1")):
    """Evidence-based transfer (§1.3/§14). Requires each result row to carry applied_patch + injected +
    exec1 (+ optional grader_ok), and a per-source-task signature map (imports/apis/control_flow/operations
    tags OR a verified source code trace). Classifies each memory-induced loss AND gain by AST/API evidence
    against the source memory the arm actually used. Never infers adoption from Pass@1 alone."""
    from experiments import patch_forensics as PF
    base = {r["tid"]: r for r in by.get(base_arm, [])}
    out = {}
    for arm in arms:
        rows, gains, losses = [], 0, 0
        for r in by.get(arm, []):
            b = base.get(r["tid"])
            if b is None:
                continue
            src = source_sig_by_tid.get((arm, r["tid"])) or source_sig_by_tid.get(r["tid"])
            if b["pass1"] == 1 and r["pass1"] == 0:
                losses += 1
                cls, ev = PF.classify_loss(r.get("applied_patch"), b.get("applied_patch"), src,
                                           injected=bool(r.get("injected")), exec_ok=bool(r.get("exec1")),
                                           grader_ok=bool(r.get("grader_ok", True)))
                rows.append({"tid": r["tid"], "direction": "loss", "class": cls, "evidence": ev})
            elif b["pass1"] == 0 and r["pass1"] == 1:
                gains += 1
                cls, ev = PF.classify_loss(r.get("applied_patch"), b.get("applied_patch"), src,
                                           injected=bool(r.get("injected")), exec_ok=bool(r.get("exec1")),
                                           grader_ok=bool(r.get("grader_ok", True)))
                rows.append({"tid": r["tid"], "direction": "gain", "class": cls, "evidence": ev})
        counts = {c: 0 for c in PF.CLASSES}
        for row in rows:
            counts[row["class"]] += 1
        out[arm] = {"gains": gains, "losses": losses, "classes": counts,
                    "adoption_total": sum(counts[c] for c in PF.CLASSES[:4]),
                    "unrelated": counts["UNRELATED_IMPLEMENTATION_ERROR"], "rows": rows}
    return out
