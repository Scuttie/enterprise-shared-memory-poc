#!/usr/bin/env python3
"""REALBENCH-R13 — representation analysis. For each encoding format F in {F0..F4}, RelevantLift_F =
Pass@1(relevant-F) - Pass@1(shuffled-F) on the same 109 covered targets, with exact McNemar + paired bootstrap
95% CI + negative transfer + injected-token proxy (memory length). Selects the encoding maximising RelevantLift
(leakage=0 first; ties by min negative transfer, then min injected tokens; NOT by p-value). Also reports each
format vs M0. A null (no format beats shuffled) is final.
"""
import os, sys, io, json, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
A = "artifacts/repr_r13/arms"


def load(arm):
    p = "%s/%s.json" % (A, arm)
    if not os.path.isfile(p):
        return None
    d = json.load(open(p, encoding="utf-8"))
    return {r["question_id"]: (1 if r["passed"] else 0) for r in d["results"]}


def mcnemar(b, c):
    from math import comb
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) * 0.5 ** n)


def lcg(s):
    x = s & 0x7FFFFFFF
    while True:
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        yield x


def boot(vals, B=3000):
    n = len(vals)
    if not n:
        return (None, None)
    g = lcg(20260819)
    out = []
    for _ in range(B):
        s = 0
        for _ in range(n):
            s += vals[next(g) % n]
        out.append(s / n)
    out.sort()
    return (round(out[int(0.025 * B)], 4), round(out[int(0.975 * B)], 4))


def contrast(a, b):
    ids = [q for q in a if q in b]
    pa = [a[q] for q in ids]; pb = [b[q] for q in ids]
    bo = sum(1 for i in range(len(ids)) if pa[i] and not pb[i])
    co = sum(1 for i in range(len(ids)) if not pa[i] and pb[i])
    return {"n": len(ids), "rateA": round(sum(pa) / len(ids), 4), "rateB": round(sum(pb) / len(ids), 4),
            "diff": round((sum(pa) - sum(pb)) / len(ids), 4), "pos_transfer": bo, "neg_transfer": co,
            "mcnemar_p": round(mcnemar(bo, co), 4), "boot95ci": boot([pa[i] - pb[i] for i in range(len(ids))])}


def med_len(fk):
    try:
        d = json.load(open("artifacts/repr_r13/memory_%sR.json" % fk, encoding="utf-8"))
        import statistics as st
        return int(st.median([len(v) for v in d.values()]))
    except Exception:
        return None


def main():
    m0 = load("M0")
    fmts = ["F0", "F1", "F2", "F3", "F4"]
    names = {"F0": "PLAIN", "F1": "API_CARD", "F2": "EXECUTABLE", "F3": "POS_NEG", "F4": "SKELETON"}
    rep = {"experiment": "REALBENCH_REPRESENTATION_R13", "reader": "gpt-4o-mini-2024-07-18",
           "M0_pass_at_1": round(sum(m0.values()) / len(m0), 4) if m0 else None, "formats": {}}
    print("M0 Pass@1:", rep["M0_pass_at_1"])
    print("%-4s %-11s relLift(rel-shuf)  rel   shuf   McNemar  CI               vsM0   inj_len" % ("fmt", "name"))
    for fk in fmts:
        r = load(fk + "R"); s = load(fk + "S")
        if r is None or s is None:
            continue
        rl = contrast(r, s)               # RelevantLift
        vm0 = contrast(r, m0) if m0 else None
        rep["formats"][fk] = {"name": names[fk], "RelevantLift": rl, "relevant_vs_M0": vm0, "inject_len": med_len(fk)}
        print("%-4s %-11s %+.4f          %.3f %.3f  p=%.3f  %s   %+.3f  %s"
              % (fk, names[fk], rl["diff"], rl["rateA"], rl["rateB"], rl["mcnemar_p"], rl["boot95ci"],
                 (vm0["diff"] if vm0 else 0), med_len(fk)))
    # selection: max RelevantLift (leakage assumed 0); tie -> min neg_transfer -> min inject_len
    ranked = sorted(rep["formats"].items(),
                    key=lambda kv: (-kv[1]["RelevantLift"]["diff"], kv[1]["RelevantLift"]["neg_transfer"], kv[1]["inject_len"] or 0))
    rep["selected_encoding"] = ranked[0][0] if ranked else None
    rep["selected_name"] = names.get(rep["selected_encoding"])
    best = ranked[0][1]["RelevantLift"] if ranked else None
    rep["selection_note"] = ("no encoding beats shuffled (all RelevantLift <= 0) -> null; representation does not "
                             "create transfer for this reader" if best and best["diff"] <= 0 else
                             "selected by max RelevantLift (not p-value)")
    print("\nSELECTED encoding:", rep["selected_encoding"], rep["selected_name"], "|", rep["selection_note"])
    json.dump(rep, open("artifacts/repr_r13/main_result.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
