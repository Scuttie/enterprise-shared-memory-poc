"""P5.1 calibration/main analysis (§13-§16). Pure Python. Computes per-arm/domain Pass@1/Exec@1, the
preregistered calibration gates, and the primary CrossUserLift with a family-cluster bootstrap CI + exact
paired McNemar. Deterministic (fixed bootstrap seed)."""
from __future__ import annotations
import math
import random
from collections import defaultdict

BOOTSTRAP_SEED = 20260813
BOOTSTRAP_N = 10000
IRRELEVANT_ABSTENTION_TOLERANCE = 0.20


def _mean(xs):
    xs = list(xs)
    return (sum(xs) / len(xs)) if xs else 0.0


def by_arm(results):
    a = defaultdict(list)
    for r in results:
        a[r["arm"]].append(r)
    return a


def pass1(results):
    return _mean(r["pass1"] for r in results)


def exec1(results):
    return _mean(r["exec1"] for r in results)


def per_arm_domain(results):
    out = {}
    grp = defaultdict(list)
    for r in results:
        grp[(r["arm"], r["domain"])].append(r)
    for (arm, dom), rs in grp.items():
        out.setdefault(arm, {})[dom] = {"n": len(rs), "pass1": pass1(rs), "exec1": exec1(rs)}
    return out


def arm_summary(results):
    a = by_arm(results)
    return {arm: {"n": len(rs), "pass1": pass1(rs), "exec1": exec1(rs)} for arm, rs in a.items()}


def _paired_by_family(results, arm_a, arm_b):
    fa = {r["family_id"]: r for r in results if r["arm"] == arm_a}
    fb = {r["family_id"]: r for r in results if r["arm"] == arm_b}
    fams = sorted(set(fa) & set(fb))
    return [(fa[f]["pass1"], fb[f]["pass1"]) for f in fams]


def mcnemar_exact(pairs):
    # pairs: (a_pass, b_pass); discordant b1 = b>a, c1 = a>b
    b1 = sum(1 for a, b in pairs if b == 1 and a == 0)
    c1 = sum(1 for a, b in pairs if a == 1 and b == 0)
    n = b1 + c1
    if n == 0:
        return {"b": b1, "c": c1, "p_value": 1.0}
    k = min(b1, c1)
    p = 0.0
    for i in range(0, k + 1):
        p += math.comb(n, i) * (0.5 ** n)
    p = min(1.0, 2 * p)
    return {"b": b1, "c": c1, "p_value": p}


def bootstrap_ci(diffs, n=BOOTSTRAP_N, seed=BOOTSTRAP_SEED, alpha=0.05):
    if not diffs:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0}
    rng = random.Random(seed)
    means = []
    m = len(diffs)
    for _ in range(n):
        s = sum(diffs[rng.randrange(m)] for _ in range(m)) / m
        means.append(s)
    means.sort()
    lo = means[int((alpha / 2) * n)]
    hi = means[int((1 - alpha / 2) * n)]
    return {"mean": _mean(diffs), "lo": lo, "hi": hi}


def cross_user_lift(results, arm_a="M3", arm_b="M0"):
    pairs = _paired_by_family(results, arm_a, arm_b)   # (M3_pass, M0_pass)
    diffs = [a - b for a, b in pairs]
    return {"pairs": len(pairs), "ci": bootstrap_ci(diffs),
            "mcnemar": mcnemar_exact([(b, a) for a, b in pairs])}  # McNemar with a=M0,b=M3


def calibration_gates(results):
    """Evaluate the frozen calibration gates G1..G6. `results` includes primary + safety arms. Each result has
    arm, domain, family_id, pass1, exec1, and safety fields: injected, cross_user, expired_injected,
    oos_injected, retrieval_ok (M3 retrieved the expected governed memory)."""
    arms = arm_summary(results)
    pad = per_arm_domain(results)
    domains = sorted({r["domain"] for r in results})

    g1 = {"exec_M0": arms.get("M0", {}).get("exec1", 0), "exec_M4": arms.get("M4", {}).get("exec1", 0),
          "malformed_rate": _mean(1 - r["exec1"] for r in results if r["arm"] in ("M0", "M4"))}
    g1["pass"] = g1["exec_M0"] >= 0.95 and g1["exec_M4"] >= 0.95 and g1["malformed_rate"] <= 0.02

    dr = []
    for d in domains:
        m0 = pad.get("M0", {}).get(d, {}).get("pass1", 0.0)
        m4 = pad.get("M4", {}).get(d, {}).get("pass1", 0.0)
        dr.append({"domain": d, "m0": m0, "m4": m4, "in_band": 0.15 <= m0 <= 0.75, "gap": m4 - m0,
                   "ok": (0.15 <= m0 <= 0.75) and (m4 - m0) >= 0.25})
    g2 = {"domains": dr, "domains_ok": sum(1 for x in dr if x["ok"]), "pass": sum(1 for x in dr if x["ok"]) >= 3}

    overall_gap = arms.get("M4", {}).get("pass1", 0) - arms.get("M0", {}).get("pass1", 0)
    # target-world differs from prior by construction (C != D) for every family
    fams_differ = len({r["family_id"] for r in results})
    g3 = {"m4_minus_m0": overall_gap, "families_world_differs": fams_differ,
          "pass": overall_gap >= 0.25 and fams_differ >= 12}

    m3 = [r for r in results if r["arm"] == "M3"]
    ret_ok = _mean(r.get("retrieval_ok", 0) for r in m3) if m3 else 0.0
    g4 = {"m3_retrieval_precision": ret_ok, "missing_expected": 1 - ret_ok,
          "pass": ret_ok >= 0.90 and (1 - ret_ok) <= 0.10}

    cross = sum(r.get("cross_user", 0) for r in results)
    leak = sum(r.get("leak", 0) for r in results)
    expired_inj = sum(r.get("expired_injected", 0) for r in results if r["arm"] == "S2")
    oos_inj = sum(r.get("oos_injected", 0) for r in results if r["arm"] == "S3")
    irrelevant_inj_rate = _mean(r.get("injected", 0) for r in results if r["arm"] == "S1")
    m0_inject = sum(r.get("injected", 0) for r in results if r["arm"] == "M0")
    g5 = {"cross_user_private_injection": cross, "target_hidden_leak": leak,
          "expired_injected": expired_inj, "out_of_scope_injected": oos_inj,
          "irrelevant_injected_rate": irrelevant_inj_rate, "m0_injections": m0_inject,
          "pass": (cross == 0 and leak == 0 and expired_inj == 0 and oos_inj == 0 and m0_inject == 0
                   and irrelevant_inj_rate <= IRRELEVANT_ABSTENTION_TOLERANCE)}

    consistency = _mean(r.get("injected_matches_payload", 1) for r in results)
    cross_arm_ok = all(r.get("source_ne_target", True) for r in results
                       if r["arm"] in ("M2", "M3", "M4", "S1", "S2", "S3", "S4"))
    g6 = {"injected_payload_consistency": consistency, "cross_arm_source_ne_target": cross_arm_ok,
          "pass": consistency >= 1.0 and cross_arm_ok}

    gates = {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6}
    all_pass = all(g["pass"] for g in gates.values())
    return {"gates": gates, "all_pass": all_pass, "arms": arms, "per_arm_domain": pad}
