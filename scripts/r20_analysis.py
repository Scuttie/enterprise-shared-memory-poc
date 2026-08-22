#!/usr/bin/env python3
"""R20 analysis — 2x2 factorial (relevance x router) + B0/B1 controls, preregistered estimands.

Primary: interaction I = (F11-F10) - (F01-F00), task-level binary DID with repository-cluster bootstrap.
Also: relevance R_avg, router G_avg, bundle P=F11-B0, orchestration O=B1-B0; paired exact McNemar per contrast;
practical-equivalence at +-5pp (cluster 90% CI). Six separate labels. ITT (infra failure = unresolved)."""
import os, sys, io, json, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
A = "artifacts/r20/arms_out"
ARMS = ["B0", "B1", "F00", "F10", "F01", "F11"]


def load(arm):
    d = {}
    for f in glob.glob("%s/%s/*.json" % (A, arm)):
        if f.endswith(".patch"):
            continue
        r = json.load(open(f, encoding="utf-8"))
        d[r["instance_id"]] = {"p": r.get("resolved") is True, "repo": r.get("repo")}
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


def cluster_boot(ids, vals, repos, B=3000, lo=0.025, hi=0.975):
    from collections import defaultdict
    byrepo = defaultdict(list)
    for q in ids:
        byrepo[repos[q]].append(q)
    rk = list(byrepo); g = lcg(20260823); out = []
    for _ in range(B):
        s = 0.0; n = 0
        for _ in range(len(rk)):
            rep = rk[next(g) % len(rk)]
            for q in byrepo[rep]:
                s += vals[q]; n += 1
        out.append(s / n if n else 0)
    out.sort()
    return (round(out[int(lo * B)], 4), round(out[int(hi * B)], 4))


def paired(name, arms, repos, X, Y):
    ids = [q for q in arms[X] if q in arms[Y]]
    a = {q: arms[X][q]["p"] for q in ids}; b = {q: arms[Y][q]["p"] for q in ids}
    bo = sum(1 for q in ids if a[q] and not b[q]); co = sum(1 for q in ids if not a[q] and b[q])
    diffvals = {q: (1 if a[q] else 0) - (1 if b[q] else 0) for q in ids}
    return {"contrast": name, "n": len(ids), "rateA": round(sum(a.values()) / len(ids), 4),
            "rateB": round(sum(b.values()) / len(ids), 4),
            "diff": round((sum(a.values()) - sum(b.values())) / len(ids), 4),
            "gain": bo, "loss": co, "tie": len(ids) - bo - co, "mcnemar_p": round(mcnemar(bo, co), 4),
            "cluster95": cluster_boot(ids, diffvals, repos)}


def label(diff, p, ci95):
    if diff > 0 and p < 0.05 and ci95[0] > 0:
        return "POSITIVE"
    if diff < 0 and p < 0.05 and ci95[1] < 0:
        return "NEGATIVE"
    return "NULL_OR_INCONCLUSIVE"


def main():
    arms = {m: load(m) for m in ARMS if os.path.isdir("%s/%s" % (A, m))}
    print("arms:", {m: len(v) for m, v in arms.items()})
    if len(arms) < 6:
        print("waiting for all 6 arms"); return
    repos = {}
    for v in arms.values():
        for q, r in v.items():
            repos[q] = r["repo"]
    rate = {m: round(sum(1 for r in v.values() if r["p"]) / len(v), 4) for m, v in arms.items()}
    print("resolved rate by arm:", rate)

    C = {}
    for nm, x, y in [("B1_B0", "B1", "B0"), ("F10_F00", "F10", "F00"), ("F11_F01", "F11", "F01"),
                     ("F01_F00", "F01", "F00"), ("F11_F10", "F11", "F10"), ("F11_B0", "F11", "B0"),
                     ("F00_B1", "F00", "B1"), ("F10_B1", "F10", "B1")]:
        C[nm] = paired("%s-%s" % (x, y), arms, repos, x, y)

    # interaction DID (task-level), repo-cluster bootstrap 95%
    ids = [q for q in arms["F11"] if q in arms["F10"] and q in arms["F01"] and q in arms["F00"]]
    did = {q: ((1 if arms["F11"][q]["p"] else 0) - (1 if arms["F10"][q]["p"] else 0)) -
              ((1 if arms["F01"][q]["p"] else 0) - (1 if arms["F00"][q]["p"] else 0)) for q in ids}
    I = round(sum(did.values()) / len(ids), 4)
    I_ci = cluster_boot(ids, did, repos)
    I_ci90 = cluster_boot(ids, did, repos, lo=0.05, hi=0.95)

    # estimands
    R_off = C["F10_F00"]["diff"]; R_on = C["F11_F01"]["diff"]; R_avg = round((R_off + R_on) / 2, 4)
    G_shuf = C["F01_F00"]["diff"]; G_rel = C["F11_F10"]["diff"]; G_avg = round((G_shuf + G_rel) / 2, 4)
    P = C["F11_B0"]["diff"]; O = C["B1_B0"]["diff"]

    def equiv(ci90):
        if ci90[0] >= -0.05 and ci90[1] <= 0.05:
            return "PASS"
        return "FAIL_OR_NOT_ESTABLISHED"

    labels = {
        "SYSTEM_BUNDLE_EFFECT": label(P, C["F11_B0"]["mcnemar_p"], C["F11_B0"]["cluster95"]),
        "ORCHESTRATION_EFFECT": label(O, C["B1_B0"]["mcnemar_p"], C["B1_B0"]["cluster95"]),
        "RELEVANCE_EFFECT": ("POSITIVE" if (label(R_off, C["F10_F00"]["mcnemar_p"], C["F10_F00"]["cluster95"]) == "POSITIVE"
                                            or label(R_on, C["F11_F01"]["mcnemar_p"], C["F11_F01"]["cluster95"]) == "POSITIVE")
                             else "NULL_OR_INCONCLUSIVE"),
        "ROUTER_MAIN_EFFECT": ("POSITIVE" if (label(G_shuf, C["F01_F00"]["mcnemar_p"], C["F01_F00"]["cluster95"]) == "POSITIVE"
                                              or label(G_rel, C["F11_F10"]["mcnemar_p"], C["F11_F10"]["cluster95"]) == "POSITIVE")
                               else "NULL_OR_INCONCLUSIVE"),
        "ROUTER_X_RELEVANCE_INTERACTION": ("POSITIVE" if (I > 0 and I_ci[0] > 0) else
                                           ("NEGATIVE" if (I < 0 and I_ci[1] < 0) else "NULL_OR_INCONCLUSIVE")),
        "PRACTICAL_EQUIVALENCE_interaction": equiv(I_ci90),
    }
    print("\n=== estimands ===")
    print("Interaction I = (F11-F10)-(F01-F00) = %+.4f  cluster95=%s  cluster90=%s" % (I, I_ci, I_ci90))
    print("Relevance R_avg=%+.4f (off=%+.4f on=%+.4f)" % (R_avg, R_off, R_on))
    print("Router G_avg=%+.4f (shuffled=%+.4f relevant=%+.4f)" % (G_avg, G_shuf, G_rel))
    print("Bundle P=F11-B0=%+.4f | Orchestration O=B1-B0=%+.4f" % (P, O))
    print("\n=== paired contrasts ===")
    for k, v in C.items():
        print("  %-9s diff=%+.4f gain/loss=%d/%d p=%.4f ci95=%s" % (k, v["diff"], v["gain"], v["loss"], v["mcnemar_p"], v["cluster95"]))
    print("\n=== LABELS ===")
    for k, v in labels.items():
        print("  %-34s %s" % (k, v))
    out = {"rate": rate, "interaction": {"I": I, "ci95": I_ci, "ci90": I_ci90, "n": len(ids)},
           "estimands": {"R_off": R_off, "R_on": R_on, "R_avg": R_avg, "G_shuffled": G_shuf, "G_relevant": G_rel,
                         "G_avg": G_avg, "P_bundle": P, "O_orchestration": O},
           "contrasts": C, "labels": labels}
    json.dump(out, open("artifacts/r20/r20_result.json", "w", encoding="utf-8"), indent=2)


if __name__ == "__main__":
    main()
