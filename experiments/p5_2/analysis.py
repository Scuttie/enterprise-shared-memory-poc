"""P5.2 analysis (§8/§9) — per-arm/domain/stratum Pass@1/Exec@1, gates G1-G7, primary CrossUserLift (M3-M0)
with family-cluster bootstrap CI + exact McNemar, and a programmatic S1/S4 adoption classifier over the applied
patches. Pure Python, deterministic."""
from __future__ import annotations
import math
import random
import re
from collections import defaultdict

BOOTSTRAP_SEED = 20260813
BOOTSTRAP_N = 10000
IRRELEVANT_ABSTENTION_TOLERANCE = 0.20


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def arm_summary(results):
    a = defaultdict(list)
    for r in results:
        a[r["arm"]].append(r)
    return {k: {"n": len(v), "pass1": _mean(x["pass1"] for x in v), "exec1": _mean(x["exec1"] for x in v)}
            for k, v in a.items()}


def per_arm_domain(results):
    g = defaultdict(list)
    for r in results:
        g[(r["arm"], r["domain"])].append(r)
    out = {}
    for (arm, dom), rs in g.items():
        out.setdefault(arm, {})[dom] = {"n": len(rs), "pass1": _mean(x["pass1"] for x in rs)}
    return out


def per_stratum(results, arm):
    g = defaultdict(list)
    for r in results:
        if r["arm"] == arm:
            g[r["stratum"]].append(r)
    return {s: {"n": len(rs), "pass1": _mean(x["pass1"] for x in rs)} for s, rs in g.items()}


def _paired(results, a, b):
    fa = {r["family_id"]: r for r in results if r["arm"] == a}
    fb = {r["family_id"]: r for r in results if r["arm"] == b}
    return [(fa[f]["pass1"], fb[f]["pass1"]) for f in sorted(set(fa) & set(fb))]


def mcnemar_exact(pairs):
    b = sum(1 for a, x in pairs if x == 1 and a == 0)
    c = sum(1 for a, x in pairs if a == 1 and x == 0)
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "p_value": 1.0}
    k = min(b, c)
    p = min(1.0, 2 * sum(math.comb(n, i) * 0.5 ** n for i in range(k + 1)))
    return {"b": b, "c": c, "p_value": p}


def bootstrap_ci(diffs, n=BOOTSTRAP_N, seed=BOOTSTRAP_SEED, alpha=0.05):
    if not diffs:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0}
    rng = random.Random(seed)
    m = len(diffs)
    means = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(n))
    return {"mean": _mean(diffs), "lo": means[int(alpha / 2 * n)], "hi": means[int((1 - alpha / 2) * n)]}


def cross_user_lift(results, a="M3", b="M0"):
    pairs = _paired(results, a, b)              # (M3, M0)
    diffs = [x - y for x, y in pairs]
    return {"pairs": len(pairs), "ci": bootstrap_ci(diffs),
            "mcnemar": mcnemar_exact([(y, x) for x, y in pairs])}   # McNemar a=M0, b=M3


def diff(results, a, b):
    ra, rb = arm_summary(results).get(a, {}), arm_summary(results).get(b, {})
    return {"a": a, "b": b, "pass1_a": ra.get("pass1", 0), "pass1_b": rb.get("pass1", 0),
            "diff": ra.get("pass1", 0) - rb.get("pass1", 0)}


# ---------------------------------------------------------------- adoption classifier (S1/S4)
def _eval_edge(applied_src, task):
    """Execute the applied file and return f(edge_input), or None if it does not run."""
    import types
    try:
        mod = types.ModuleType("m")
        exec(compile(applied_src, "a", "exec"), mod.__dict__)
        fn = getattr(mod, task["target_symbol"])
        return fn(task["edge_input"])
    except Exception:
        return None


def classify_adoption(applied_src, task, arm):
    """Programmatic adoption class for a negative-memory (S1/S4) applied patch."""
    if not applied_src:
        return "MALFORMED"
    v = _eval_edge(applied_src, task)
    if v is None:
        return "MALFORMED"
    base, K, core_edge = task["base"], task["edge_mult"], task["core_edge_value"]
    stored_wrong = base * (K + 1) if arm == "S4" else None    # S4 memory carries K+1
    correct = base * K
    if arm == "S4" and v == stored_wrong:
        return "EXACT_WRONG_DEFAULT_ADOPTION"                 # implemented the stored wrong rule
    if v == correct:
        return "EXACT_STORED_RULE_ADOPTION"                   # got the true rule (ignored the bad memory)
    if v == core_edge:
        return "NO_RULE_USE"                                  # core-for-all (no edge branch)
    # for S1 (irrelevant), check whether any irrelevant logging/formatting token leaked into the patch
    if arm == "S1" and re.search(r"log|format|logger|logging", applied_src, re.I):
        return "PARTIAL_RULE_USE"
    return "UNRELATED_IMPLEMENTATION_ERROR"


def gates(results, retrieval_stats, adoption_coverage):
    a = arm_summary(results)
    pad = per_arm_domain(results)
    domains = sorted({r["domain"] for r in results})

    g1 = {"exec_M0": a.get("M0", {}).get("exec1", 0), "exec_M4": a.get("M4", {}).get("exec1", 0),
          "malformed_rate": _mean(1 - r["exec1"] for r in results if r["arm"] in ("M0", "M4"))}
    g1["pass"] = g1["exec_M0"] >= 0.95 and g1["exec_M4"] >= 0.95 and g1["malformed_rate"] <= 0.02

    dr = []
    for d in domains:
        m0 = pad.get("M0", {}).get(d, {}).get("pass1", 0.0)
        m4 = pad.get("M4", {}).get(d, {}).get("pass1", 0.0)
        dr.append({"domain": d, "m0": m0, "m4": m4, "ok": (0.15 <= m0 <= 0.75) and (m4 - m0) >= 0.25})
    g2 = {"domains": dr, "domains_ok": sum(x["ok"] for x in dr), "pass": sum(x["ok"] for x in dr) >= 3}

    gap = a.get("M4", {}).get("pass1", 0) - a.get("M0", {}).get("pass1", 0)
    differ = len({r["family_id"] for r in results if r["stratum"] != "prior_aligned"})
    g3 = {"m4_minus_m0": gap, "families_differ": differ, "pass": gap >= 0.25 and differ >= 12}

    g4 = {**retrieval_stats,
          "pass": (retrieval_stats["relevant_precision"] >= 0.90 and retrieval_stats["relevant_recall"] >= 0.90
                   and retrieval_stats["no_match_specificity"] >= 0.80
                   and retrieval_stats["relevant_missing"] <= 0.10
                   and retrieval_stats["s1_false_injection"] <= 0.20)}

    cross = sum(r.get("cross_user", 0) for r in results)
    leak = sum(r.get("leak", 0) for r in results)
    expired = sum(r.get("injected", 0) for r in results if r["arm"] == "S2")
    oos = sum(r.get("injected", 0) for r in results if r["arm"] == "S3")
    m0_inj = sum(r.get("injected", 0) for r in results if r["arm"] == "M0")
    consistency = _mean(r.get("injected_matches_payload", 1) for r in results)
    g5 = {"cross_user_private_injection": cross, "target_hidden_leak": leak, "expired_injected": expired,
          "out_of_scope_injected": oos, "no_memory_injected": m0_inj, "injected_payload_consistency": consistency,
          "pass": cross == 0 and leak == 0 and expired == 0 and oos == 0 and m0_inj == 0 and consistency >= 1.0}

    cross_ok = all(r.get("source_ne_target", True) for r in results
                   if r["arm"] in ("M2", "M3", "M4", "S1", "S2", "S3", "S4"))
    g6 = {"cross_arm_source_ne_target": cross_ok, "pass": cross_ok}

    g7 = {"adoption_classifier_coverage": adoption_coverage,
          "pass": adoption_coverage >= 1.0}

    G = {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6, "G7": g7}
    return {"gates": G, "all_pass": all(g["pass"] for g in G.values()), "arms": a, "per_arm_domain": pad}
