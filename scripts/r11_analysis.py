#!/usr/bin/env python3
"""REALBENCH-R11 — main analysis. Loads arms/{M0,M1,M2,M3}.json, aligns by question_id, computes official Pass@1
per arm and the paired contrasts with exact McNemar + paired repository/task bootstrap 95% CI.

Primary: H1 = M1 - M2 (relevant vs shuffled-matched). Secondary: M1 - M0, M3 - M1.
ITT: every frozen target with an arm result counts; an arm's infra terminal failure counts as passed=false.
The paired contrasts are computed over targets that HAVE memory in BOTH arms (coverage reported). No p-value
selection; a null/negative result is final. No randomness API: bootstrap uses a fixed integer LCG seeded from a
constant so it is deterministic and resumable.
"""
import os, sys, io, json, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
A = "artifacts/livecodebench_r11/arms"


def load(arm):
    d = json.load(open("%s/%s.json" % (A, arm), encoding="utf-8"))
    return {r["question_id"]: r for r in d["results"]}


def mcnemar_exact(b, c):
    """two-sided exact McNemar p on discordant counts b, c (binomial with p=0.5)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    from math import comb
    tail = sum(comb(n, i) for i in range(0, k + 1)) * (0.5 ** n)
    return min(1.0, 2 * tail)


def lcg(seed):
    x = seed & 0xFFFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x


def boot_ci(pairs, B=2000):
    """paired bootstrap 95% CI of mean(a)-mean(b) over pairs [(a,b)]; deterministic LCG resampling."""
    n = len(pairs)
    if n == 0:
        return (None, None)
    g = lcg(20260818)
    diffs = []
    for _ in range(B):
        s = 0.0
        for _ in range(n):
            idx = next(g) % n
            s += pairs[idx][0] - pairs[idx][1]
        diffs.append(s / n)
    diffs.sort()
    return (round(diffs[int(0.025 * B)], 4), round(diffs[int(0.975 * B)], 4))


def contrast(name, armA, armB, a, b, restrict_to_memory=None):
    ids = [q for q in a if q in b]
    if restrict_to_memory is not None:
        ids = [q for q in ids if q in restrict_to_memory]
    pa = [1 if a[q]["passed"] else 0 for q in ids]
    pb = [1 if b[q]["passed"] else 0 for q in ids]
    b_only = sum(1 for i in range(len(ids)) if pa[i] == 1 and pb[i] == 0)  # A pass, B fail
    c_only = sum(1 for i in range(len(ids)) if pa[i] == 0 and pb[i] == 1)  # A fail, B pass
    diff = (sum(pa) - sum(pb)) / len(ids) if ids else None
    ci = boot_ci(list(zip(pa, pb)))
    p = mcnemar_exact(b_only, c_only)
    return {"contrast": name, "n": len(ids), "passA": sum(pa), "passB": sum(pb),
            "rateA": round(sum(pa) / len(ids), 4) if ids else None,
            "rateB": round(sum(pb) / len(ids), 4) if ids else None,
            "diff_%s_minus_%s" % (armA, armB): round(diff, 4) if diff is not None else None,
            "positive_transfer(A>B)": c_only if armA in ("M1", "M3", "M4") else b_only,
            "discordant_Apass_Bfail": b_only, "discordant_Afail_Bpass": c_only,
            "mcnemar_exact_p": round(p, 4), "boot95ci_diff": ci}


def main():
    arms = {}
    for name in ["M0", "M1", "M2", "M3"]:
        if os.path.isfile("%s/%s.json" % (A, name)):
            arms[name] = load(name)
    print("arms present:", list(arms.keys()))
    passrate = {k: round(sum(1 for r in v.values() if r["passed"]) / len(v), 4) for k, v in arms.items()}
    print("Pass@1 by arm:", passrate)

    mem = None
    if os.path.isfile("artifacts/livecodebench_r11/memory_M1.json"):
        mem = set(json.load(open("artifacts/livecodebench_r11/memory_M1.json", encoding="utf-8")).keys())

    report = {"experiment": "REALBENCH_LIVECODEBENCH_R11", "pass_at_1_by_arm": passrate,
              "memory_coverage_targets": (len(mem) if mem else None), "contrasts": {}}
    if "M1" in arms and "M2" in arms:
        report["contrasts"]["H1_primary_M1_minus_M2"] = contrast("H1 M1-M2", "M1", "M2", arms["M1"], arms["M2"], mem)
    if "M1" in arms and "M0" in arms:
        report["contrasts"]["H2_M1_minus_M0"] = contrast("M1-M0", "M1", "M0", arms["M1"], arms["M0"], mem)
    if "M3" in arms and "M1" in arms:
        report["contrasts"]["H3_M3_minus_M1"] = contrast("M3-M1", "M3", "M1", arms["M3"], arms["M1"], mem)

    for k, v in report["contrasts"].items():
        print("\n%s:" % k)
        for kk, vv in v.items():
            print("   %s: %s" % (kk, vv))
    json.dump(report, open("artifacts/livecodebench_r11/main_result.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)
    print("\nwrote artifacts/livecodebench_r11/main_result.json")


if __name__ == "__main__":
    main()
