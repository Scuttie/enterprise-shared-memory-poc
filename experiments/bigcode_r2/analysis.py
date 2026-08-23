"""BIGCODE-R2 confirmatory analysis (§11/§12). Fixed-sequence primary family E1 (M2 vs M3) then E2 (M4 vs M0);
Holm correction across the SECONDARY superiority tests; task-cluster bootstrap CI + exact McNemar. Intention-
to-treat (terminal infra failures scored as failure) is primary; complete-case is a separate sensitivity."""
from __future__ import annotations
import math
import random

BOOTSTRAP_SEED = 20260814
BOOTSTRAP_N = 10000


def _mcnemar(a, b, tids):
    """Exact two-sided McNemar over paired arms a,b (dicts tid->pass1)."""
    disc_b = sum(1 for t in tids if a.get(t) == 1 and b.get(t) == 0)   # a wins
    disc_c = sum(1 for t in tids if b.get(t) == 1 and a.get(t) == 0)   # b wins
    n = disc_b + disc_c
    p = 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) * 0.5 ** n for i in range(min(disc_b, disc_c) + 1)))
    return {"b": disc_b, "c": disc_c, "n_discordant": n, "p_value": p}


def paired(a, b, tids):
    """a,b: dict tid->pass1. Returns diff, task-bootstrap 95% CI, exact McNemar. diff = mean(a-b)."""
    tids = [t for t in tids if t in a and t in b]
    if not tids:
        return {"diff": 0.0, "ci": {"lo": 0.0, "hi": 0.0}, "mcnemar": _mcnemar(a, b, []), "n": 0}
    diffs = [a[t] - b[t] for t in tids]
    rng = random.Random(BOOTSTRAP_SEED); m = len(diffs)
    means = sorted(sum(diffs[rng.randrange(m)] for _ in range(m)) / m for _ in range(BOOTSTRAP_N))
    return {"diff": sum(diffs) / m, "ci": {"lo": means[int(0.025 * BOOTSTRAP_N)],
                                           "hi": means[int(0.975 * BOOTSTRAP_N)]},
            "mcnemar": _mcnemar(a, b, tids), "n": m}


def holm(named_pvals, alpha=0.05):
    """Holm-Bonferroni across the secondary tests. named_pvals: {name: p}. Returns {name: {p, reject, adj}}."""
    items = sorted(named_pvals.items(), key=lambda kv: kv[1])
    k = len(items)
    out = {}
    prev_reject = True
    for i, (name, p) in enumerate(items):
        thresh = alpha / (k - i)
        reject = prev_reject and (p <= thresh)
        prev_reject = reject
        out[name] = {"p": p, "threshold": thresh, "reject": reject}
    return out
