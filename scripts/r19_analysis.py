#!/usr/bin/env python3
"""R19-SMALL analysis — resolved rate per arm A0..A5 + preregistered contrasts + decision label.

Contrasts (frozen): L1=A4-A0, L2=A4-A1, L3=A4-A2, H1=A5-A0 (primary), H2=A5-A1, H3=A5-A2, H4=A5-A4.
Exact paired McNemar + repository-cluster bootstrap 95% CI. ITT (infra failure = unresolved). Decision label per
§10.7. A null/negative is valid and reported honestly (reduced power — see the amendment)."""
import os, sys, io, json, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
A = "artifacts/p6/arms_out"
ARMS = ["A0", "A1", "A2", "A3", "A4", "A5"]


def load(arm):
    d = {}
    for f in glob.glob("%s/%s/*.json" % (A, arm)):
        if f.endswith(".patch"):
            continue
        r = json.load(open(f, encoding="utf-8"))
        d[r["instance_id"]] = {"passed": r.get("resolved") is True, "repo": r.get("repo")}
    return d


def mcnemar(b, c):
    from math import comb
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) * 0.5 ** n)


def lcg(s):
    x = s & 0x7FFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x


def cluster_boot(ids, a, b, repos, B=3000):
    from collections import defaultdict
    byrepo = defaultdict(list)
    for q in ids:
        byrepo[repos[q]].append(q)
    rk = list(byrepo); g = lcg(20260822); diffs = []
    for _ in range(B):
        s = 0.0; n = 0
        for _ in range(len(rk)):
            rep = rk[next(g) % len(rk)]
            for q in byrepo[rep]:
                s += (1 if a[q] else 0) - (1 if b[q] else 0); n += 1
        diffs.append(s / n if n else 0)
    diffs.sort()
    return (round(diffs[int(0.025 * B)], 4), round(diffs[int(0.975 * B)], 4))


def contrast(name, arms, repos, X, Y):
    ids = [q for q in arms[X] if q in arms[Y]]
    a = {q: arms[X][q]["passed"] for q in ids}; b = {q: arms[Y][q]["passed"] for q in ids}
    bo = sum(1 for q in ids if a[q] and not b[q]); co = sum(1 for q in ids if not a[q] and b[q])
    return {"contrast": name, "n": len(ids), "rateA": round(sum(a.values()) / len(ids), 4),
            "rateB": round(sum(b.values()) / len(ids), 4),
            "diff": round((sum(a.values()) - sum(b.values())) / len(ids), 4),
            "A_only": bo, "B_only": co, "mcnemar_p": round(mcnemar(bo, co), 4),
            "cluster_ci": cluster_boot(ids, a, b, repos)}


def main():
    arms = {m: load(m) for m in ARMS if os.path.isdir("%s/%s" % (A, m))}
    print("arms:", {m: len(v) for m, v in arms.items()})
    repos = {}
    for v in arms.values():
        for q, r in v.items():
            repos[q] = r["repo"]
    rate = {m: round(sum(1 for r in v.values() if r["passed"]) / len(v), 4) for m, v in arms.items() if v}
    print("resolved rate by arm:", rate)
    C = {}
    for nm, x, y in [("L1_A4_A0", "A4", "A0"), ("L2_A4_A1", "A4", "A1"), ("L3_A4_A2", "A4", "A2"),
                     ("H1_A5_A0", "A5", "A0"), ("H2_A5_A1", "A5", "A1"), ("H3_A5_A2", "A5", "A2"),
                     ("H4_A5_A4", "A5", "A4")]:
        if x in arms and y in arms:
            C[nm] = contrast("%s-%s" % (x, y), arms, repos, x, y)
            print("\n%s:" % nm)
            for k, val in C[nm].items():
                print("   %s: %s" % (k, val))
    # decision label (§10.7): POSITIVE iff H1 (A5-A0) > 0 & significant & not explained by A1/A2
    label = "UTILITY_ROUTER_NOT_RUN"
    if "H1_A5_A0" in C:
        h1 = C["H1_A5_A0"]
        pos = h1["diff"] > 0 and h1["mcnemar_p"] < 0.05 and h1["cluster_ci"][0] > 0
        neg = h1["diff"] < 0 and h1["mcnemar_p"] < 0.05
        label = "UTILITY_ROUTER_POSITIVE" if pos else ("UTILITY_ROUTER_NEGATIVE" if neg else "UTILITY_ROUTER_NULL")
    print("\nDECISION LABEL:", label, "(reduced-power R19-SMALL; see amendment)")
    json.dump({"rate": rate, "contrasts": C, "label": label},
              open("artifacts/p6/r19_small_result.json", "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()
