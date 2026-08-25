#!/usr/bin/env python3
"""R22 §9 — paired statistics: exact McNemar, Holm, task + repository-cluster bootstrap. Pure python, deterministic.
Importable; also a thin CLI used by ci-r22-paid-analysis when a p2_results artifact exists."""
import json
import math
import random
import sys
from collections import defaultdict


def _binom_two_sided(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def mcnemar(pairs):
    """pairs: list of (a_pass, b_pass) booleans. Returns b, c, exact two-sided p, and delta = mean(a)-mean(b)."""
    b = sum(1 for a, x in pairs if a and not x)
    c = sum(1 for a, x in pairs if x and not a)
    p = _binom_two_sided(b, c)
    n = len(pairs)
    delta = (sum(1 for a, _ in pairs if a) - sum(1 for _, x in pairs if x)) / max(1, n)
    return {"b": b, "c": c, "p_value": p, "delta_pp": round(delta, 4), "net_flips": b - c, "n": n}


def holm(pvals: dict):
    """pvals: {name: p}. Returns {name: adjusted_p} by Holm-Bonferroni."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj = {}
    running = 0.0
    for i, (name, p) in enumerate(items):
        a = min(1.0, (m - i) * p)
        running = max(running, a)
        adj[name] = round(running, 6)
    return adj


def bootstrap_ci(pairs, clusters=None, iters=2000, seed=17):
    """Paired difference (mean a - mean b) 95% CI. If clusters given (list aligned with pairs), resample clusters."""
    rng = random.Random(seed)
    diffs = []
    if clusters:
        by = defaultdict(list)
        for pr, cl in zip(pairs, clusters):
            by[cl].append(pr)
        keys = list(by)
        for _ in range(iters):
            samp = []
            for _ in range(len(keys)):
                samp += by[rng.choice(keys)]
            diffs.append(_delta(samp))
    else:
        n = len(pairs)
        for _ in range(iters):
            samp = [pairs[rng.randrange(n)] for _ in range(n)]
            diffs.append(_delta(samp))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    return {"ci95_low": round(lo, 4), "ci95_high": round(hi, 4)}


def _delta(pairs):
    n = max(1, len(pairs))
    return (sum(1 for a, _ in pairs if a) - sum(1 for _, x in pairs if x)) / n


def paired(records_by_arm, arm_a, arm_b):
    """Align tasks present in both arms -> list of (a_pass, b_pass) + repo clusters."""
    a = {r["target_id"]: r for r in records_by_arm.get(arm_a, [])}
    b = {r["target_id"]: r for r in records_by_arm.get(arm_b, [])}
    common = sorted(set(a) & set(b))
    pairs = [(bool(a[t]["resolved"]), bool(b[t]["resolved"])) for t in common]
    clusters = [a[t].get("repo_cluster", a[t]["target_id"].split("_")[0]) for t in common]
    return pairs, clusters


if __name__ == "__main__":       # pragma: no cover
    recs = [json.loads(l) for l in open(sys.argv[sys.argv.index("--input") + 1], encoding="utf-8")]
    by = defaultdict(list)
    for r in recs:
        by[r["arm"]].append(r)
    for name, (x, y) in {"Q1": ("O5", "O2"), "Q2": ("O5", "O4"), "Q3": ("O6", "O5")}.items():
        pr, cl = paired(by, x, y)
        print(name, mcnemar(pr), bootstrap_ci(pr, cl))
