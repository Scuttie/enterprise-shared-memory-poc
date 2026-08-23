"""REALBENCH-R3 §18 — confirmatory main analysis. Two co-primary hypotheses with Holm correction across them:
  H1 representation effect: M2 (selected bundle) > M1 (plain), same relevant source.
  H2 relevance effect:      M2 > M3 (shuffled-matched), same selected bundle.
Each reports exact success counts, paired difference, task-cluster bootstrap 95% CI, exact McNemar,
Holm-adjusted p, positive/negative transfer. Secondary (not in the primary Holm family): M4-M0, M5-M0, M6-M2.
A one-sided superiority claim uses the McNemar p; a null is final. ITT primary (missing = failure).
"""
from __future__ import annotations
import collections

from experiments.bigcode_r2.analysis import paired, holm


def _byarm(rows):
    out = collections.defaultdict(dict)
    for r in rows:
        out[r["arm"]][r["tid"]] = int(r["pass1"])
    return out


def _transfer(a_rows, b_rows):
    """positive = arm a passes where b fails; negative = a fails where b passes (a vs b)."""
    a = {r["tid"]: int(r["pass1"]) for r in a_rows}
    b = {r["tid"]: int(r["pass1"]) for r in b_rows}
    tids = set(a) & set(b)
    return {"positive": sum(1 for t in tids if a[t] == 1 and b[t] == 0),
            "negative": sum(1 for t in tids if a[t] == 0 and b[t] == 1)}


def analyze(rows):
    by = _byarm(rows)
    arms_pass1 = {a: (round(sum(by[a].values()) / len(by[a]), 4) if by[a] else 0.0) for a in sorted(by)}
    tids = set().union(*[set(by[a]) for a in by]) if by else set()
    # co-primary
    H1 = paired(by.get("M2", {}), by.get("M1", {}), tids)   # representation effect
    H2 = paired(by.get("M2", {}), by.get("M3", {}), tids)   # relevance effect
    hp = holm({"H1_representation": H1["mcnemar"]["p_value"], "H2_relevance": H2["mcnemar"]["p_value"]})
    counts = lambda x, y: {"a_pass": sum(by.get(x, {}).values()), "b_pass": sum(by.get(y, {}).values())}
    primary = {
        "H1_representation_M2_gt_M1": {**H1, "holm": hp["H1_representation"], "counts": counts("M2", "M1"),
                                       "transfer": _transfer(rows_of(rows, "M2"), rows_of(rows, "M1"))},
        "H2_relevance_M2_gt_M3": {**H2, "holm": hp["H2_relevance"], "counts": counts("M2", "M3"),
                                  "transfer": _transfer(rows_of(rows, "M2"), rows_of(rows, "M3"))},
    }
    secondary = {
        "M4_minus_M0_deployable": paired(by.get("M4", {}), by.get("M0", {}), tids),
        "M5_minus_M0_private": paired(by.get("M5", {}), by.get("M0", {}), tids),
        "M6_minus_M2_gold_headroom": paired(by.get("M6", {}), by.get("M2", {}), tids),
    }
    return {"experiment": "R3_MAIN", "n_targets": len(tids), "arms_pass1": arms_pass1,
            "primary": primary, "secondary": secondary,
            "reject_any_primary": any(v["holm"]["reject"] for v in
                                      [primary["H1_representation_M2_gt_M1"], primary["H2_relevance_M2_gt_M3"]])}


def rows_of(rows, arm):
    return [r for r in rows if r["arm"] == arm]
