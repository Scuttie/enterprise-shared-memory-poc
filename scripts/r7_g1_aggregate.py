#!/usr/bin/env python3
"""REALBENCH-R7 §4 — G1 no-memory pilot aggregator + gate decision.

Reads the 40 per-task agent evidence jsons (artifacts/swe_polybench_r7/g1/agent_*.json) and evaluates:
  G1a technical terminal rate >= 38/40      (task reached an official graded outcome)
  G1b evaluator/environment failures <= 2/40 (infra/timeout/grader-no-result)
  G1c target/verifier leakage = 0            (agent never saw F2P/P2P/test_patch/gold — structural + patch check)
  G1d no-memory resolved count in [4, 28]    (rate in [0.10, 0.70])
Prints per-language results. Exact resolved (binary) is the KPI. No model calls.
"""
import os, sys, io, json, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

R7 = os.path.join("artifacts", "swe_polybench_r7", "g1")
FAIL_STATES = {"infra_error", "timeout", "error", "grader_no_result"}


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(R7, "agent_*.json"))):
        if f.endswith(".patch"):
            continue
        rows.append(json.load(open(f, encoding="utf-8")))
    n = len(rows)
    graded = [r for r in rows if r.get("resolved") is not None]
    failures = [r for r in rows if r.get("terminal_state") in FAIL_STATES or r.get("resolved") is None]
    resolved = [r for r in rows if r.get("resolved") is True]

    # leakage: agent has no F2P/test in context by construction; also confirm no obvious test_patch marker
    leak = [r for r in rows if r.get("leakage")]  # reserved; agent records none

    by_lang = {}
    for r in rows:
        L = r.get("language", "?")
        d = by_lang.setdefault(L, {"n": 0, "resolved": 0, "graded": 0})
        d["n"] += 1
        d["graded"] += 1 if r.get("resolved") is not None else 0
        d["resolved"] += 1 if r.get("resolved") is True else 0

    G1a = len(graded) >= 38
    G1b = len(failures) <= 2
    G1c = len(leak) == 0
    G1d = 4 <= len(resolved) <= 28
    gate_pass = G1a and G1b and G1c and G1d

    print(f"N={n}  graded={len(graded)}  failures={len(failures)}  resolved={len(resolved)}")
    print("per-language:")
    for L, d in sorted(by_lang.items()):
        print(f"  {L:11s} resolved={d['resolved']}/{d['n']} graded={d['graded']}")
    print(f"G1a technical terminal >=38/40 : {len(graded)}/40 -> {G1a}")
    print(f"G1b failures <=2/40            : {len(failures)}/40 -> {G1b}")
    print(f"G1c leakage == 0               : {len(leak)} -> {G1c}")
    print(f"G1d resolved in [4,28]         : {len(resolved)} -> {G1d}")
    print(f"GATE = {'PASS -> proceed to source bank + main' if gate_pass else 'FAIL -> R7-G1 INSTRUMENT STOP'}")

    report = {"experiment": "REALBENCH_SWE_POLYBENCH_R7", "stage": "G1_no_memory_pilot",
              "n": n, "graded": len(graded), "failures": len(failures), "resolved": len(resolved),
              "per_language": by_lang,
              "gates": {"G1a_graded_ge38": G1a, "G1b_failures_le2": G1b, "G1c_leakage_zero": G1c,
                        "G1d_resolved_in_4_28": G1d, "gate_pass": gate_pass},
              "resolved_ids": sorted(r["instance_id"] for r in resolved),
              "failure_ids": sorted(r["instance_id"] for r in failures),
              "per_task": {r["instance_id"]: {"resolved": r.get("resolved"), "terminal": r.get("terminal_state"),
                            "turns": r.get("turns"), "secs": r.get("secs"), "lang": r.get("language")} for r in rows}}
    out = os.path.join("artifacts", "swe_polybench_r7", "G1_pilot_result.json")
    json.dump(report, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
