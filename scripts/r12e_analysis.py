#!/usr/bin/env python3
"""REALBENCH-R12-E — SWE-PolyBench memory main analysis. Loads arms/{M0..M4}.json (per-instance resolved),
computes resolved rate by arm and the paired contrasts H1=M1-M2, H2=M3-M1, H3=M4-M0 with exact McNemar +
repository-cluster bootstrap 95% CI + positive/negative transfer. ITT (infra terminal failure = unresolved).
A null is final. Deterministic bootstrap (fixed LCG)."""
import os, sys, io, json, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
A = "artifacts/swe_polybench_r12_openai/arms"


def load(arm):
    d = {}
    for f in glob.glob("%s/%s/*.json" % (A, arm)):
        if f.endswith(".patch"):
            continue
        r = json.load(open(f, encoding="utf-8"))
        d[r["instance_id"]] = {"passed": r.get("resolved") is True, "repo": r.get("repo"),
                               "terminal": r.get("terminal_state")}
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


def cluster_boot(ids, a, b, repos, B=2000):
    # repository-cluster bootstrap: resample repos (clusters), then their tasks
    from collections import defaultdict
    byrepo = defaultdict(list)
    for q in ids:
        byrepo[repos[q]].append(q)
    rk = list(byrepo)
    g = lcg(20260819)
    diffs = []
    for _ in range(B):
        s = 0.0; n = 0
        for _ in range(len(rk)):
            rep = rk[next(g) % len(rk)]
            for q in byrepo[rep]:
                s += (1 if a[q] else 0) - (1 if b[q] else 0); n += 1
        diffs.append(s / n if n else 0)
    diffs.sort()
    return (round(diffs[int(0.025 * B)], 4), round(diffs[int(0.975 * B)], 4))


def contrast(name, A1, A2, arms, repos):
    ids = [q for q in arms[A1] if q in arms[A2]]
    a = {q: arms[A1][q]["passed"] for q in ids}
    b = {q: arms[A2][q]["passed"] for q in ids}
    bo = sum(1 for q in ids if a[q] and not b[q])
    co = sum(1 for q in ids if not a[q] and b[q])
    return {"contrast": name, "n": len(ids), "rateA": round(sum(a.values()) / len(ids), 4),
            "rateB": round(sum(b.values()) / len(ids), 4),
            "diff": round((sum(a.values()) - sum(b.values())) / len(ids), 4),
            "positive_transfer_A_over_B": bo, "negative_transfer": co,
            "mcnemar_p": round(mcnemar(bo, co), 4),
            "cluster_boot95ci": cluster_boot(ids, a, b, repos)}


def main():
    arms = {m: load(m) for m in ["M0", "M1", "M2", "M3", "M4"] if os.path.isdir("%s/%s" % (A, m))}
    print("arms:", {m: len(v) for m, v in arms.items()})
    repos = {}
    for v in arms.values():
        for q, r in v.items():
            repos[q] = r["repo"]
    rate = {m: round(sum(1 for r in v.values() if r["passed"]) / len(v), 4) for m, v in arms.items()}
    print("resolved rate by arm:", rate)
    rep = {"experiment": "REALBENCH_SWE_POLYBENCH_R12_OPENAI", "reader": "gpt-5.6-terra",
           "resolved_rate_by_arm": rate, "contrasts": {}}
    if "M1" in arms and "M2" in arms:
        rep["contrasts"]["H1_primary_M1_M2"] = contrast("M1-M2", "M1", "M2", arms, repos)
    if "M3" in arms and "M1" in arms:
        rep["contrasts"]["H2_M3_M1"] = contrast("M3-M1", "M3", "M1", arms, repos)
    if "M4" in arms and "M0" in arms:
        rep["contrasts"]["H3_M4_M0"] = contrast("M4-M0", "M4", "M0", arms, repos)
    if "M1" in arms and "M0" in arms:
        rep["contrasts"]["aux_M1_M0"] = contrast("M1-M0", "M1", "M0", arms, repos)
    print(json.dumps(rep["contrasts"], indent=2, ensure_ascii=False))
    json.dump(rep, open("artifacts/swe_polybench_r12_openai/main_result.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
