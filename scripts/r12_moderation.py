#!/usr/bin/env python3
"""REALBENCH-R12 §8 — reader-swap diagnostic + reader moderation (OpenAI gpt-4o-mini vs frozen Solar R11).
Loads R12 arms (artifacts/openai_reader_r12/arms/{M0..M3}.json) and Solar R11 arms
(artifacts/livecodebench_r11/arms/{M0..M3}.json), aligns by question_id on the memory-covered set, and computes:
  - R12 Pass@1 by arm, Exec@1, M1-M2, M1-M0, M3-M1 (+ exact McNemar + paired bootstrap CI, transfer);
  - reader moderation (difference-of-differences vs Solar): (M1-M2)_OpenAI-(M1-M2)_Solar, (M1-M0)_...
    with a per-task DiD table + task-paired bootstrap CI.
All R12-on-R11 inference is a reader-sensitivity DIAGNOSTIC; no diagnostic p-value is called confirmatory.
"""
import os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
R12 = "artifacts/openai_reader_r12/arms"
R11 = "artifacts/livecodebench_r11/arms"


def load(base, arm):
    d = json.load(open("%s/%s.json" % (base, arm), encoding="utf-8"))
    return {r["question_id"]: (1 if r["passed"] else 0) for r in d["results"]}


def mcnemar_exact(b, c):
    from math import comb
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) * 0.5 ** n)


def lcg(seed):
    x = seed & 0x7FFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x


def boot(vals, B=2000):
    n = len(vals)
    if n == 0:
        return (None, None)
    g = lcg(20260819)
    out = []
    for _ in range(B):
        s = 0.0
        for _ in range(n):
            s += vals[next(g) % n]
        out.append(s / n)
    out.sort()
    return (round(out[int(0.025 * B)], 4), round(out[int(0.975 * B)], 4))


def contrast(A, Bm, ids):
    pa = [A[q] for q in ids]; pb = [Bm[q] for q in ids]
    b = sum(1 for i in range(len(ids)) if pa[i] == 1 and pb[i] == 0)
    c = sum(1 for i in range(len(ids)) if pa[i] == 0 and pb[i] == 1)
    diff = (sum(pa) - sum(pb)) / len(ids)
    return {"n": len(ids), "rateA": round(sum(pa) / len(ids), 4), "rateB": round(sum(pb) / len(ids), 4),
            "diff": round(diff, 4), "discordant_Apass_Bfail": b, "discordant_Afail_Bpass": c,
            "mcnemar_p": round(mcnemar_exact(b, c), 4), "boot95ci": boot([pa[i] - pb[i] for i in range(len(ids))])}


def main():
    r12 = {a: load(R12, a) for a in ["M0", "M1", "M2", "M3"]}
    r11 = {a: load(R11, a) for a in ["M0", "M1", "M2", "M3"]}
    mem = list(json.load(open("artifacts/livecodebench_r11/memory_M1.json", encoding="utf-8")).keys())
    ids = [q for q in mem if all(q in r12[a] for a in r12) and all(q in r11[a] for a in r11)]
    print("covered ids used:", len(ids))

    rep = {"experiment": "REALBENCH_OPENAI_READER_R12", "selected_reader": "gpt-4o-mini-2024-07-18",
           "claim_boundary": "reader-sensitivity DIAGNOSTIC; not independent confirmation; not contamination-free",
           "pass_at_1_by_arm_all182": {a: round(sum(load(R12, a).values()) / len(load(R12, a)), 4) for a in r12},
           "covered_n": len(ids)}
    C = {}
    C["M1_minus_M2"] = contrast(r12["M1"], r12["M2"], ids)
    C["M1_minus_M0"] = contrast(r12["M1"], r12["M0"], ids)
    C["M3_minus_M1"] = contrast(r12["M3"], r12["M1"], ids)
    rep["R12_contrasts"] = C

    # reader moderation: DiD vs Solar on the same ids
    def did(armA, armB):
        d12 = [r12[armA][q] - r12[armB][q] for q in ids]
        d11 = [r11[armA][q] - r11[armB][q] for q in ids]
        didv = [d12[i] - d11[i] for i in range(len(ids))]
        return {"openai_diff": round(sum(d12) / len(ids), 4), "solar_diff": round(sum(d11) / len(ids), 4),
                "DiD_openai_minus_solar": round(sum(didv) / len(ids), 4), "boot95ci_DiD": boot(didv)}
    rep["reader_moderation"] = {"relevant_M1_M2": did("M1", "M2"), "memory_M1_M0": did("M1", "M0")}

    print(json.dumps(rep, indent=2, ensure_ascii=False))
    json.dump(rep, open("artifacts/openai_reader_r12/moderation_result.json", "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
