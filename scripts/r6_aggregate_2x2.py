#!/usr/bin/env python3
"""REALBENCH-R6 §2 aggregator: combine the frozen 2x2 diagnostic batches into a viability table.

Cells: P2-A0 (reuse R5 A0), P2-A1, P3-A0, P3-A1. Batches *-b1/*-b2 (15+15) merge per cell.
Reads artifacts/skills_reader_r6/bench_run_<arm>.json (downloaded from CI). P2-A0 is loaded from
the frozen R5 A0_calibration_results.json (NOT rerun). Emits per-cell exact-success counts, per-task
reward maps, net-gain-over-A0, and the §3 viability verdict inputs. Exact success is the ONLY KPI.
No model calls; deterministic.
"""
import json, glob, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R6 = os.path.join(ROOT, "artifacts", "skills_reader_r6")
R5 = os.path.join(ROOT, "artifacts", "swe_skills_r5")


def load_r5_a0():
    """P2-A0: reuse exact R5 result; do not rerun."""
    d = json.load(open(os.path.join(R5, "A0_calibration_results.json"), encoding="utf-8"))
    res = d.get("results") or d.get("per_task") or {}
    out = {}
    for tid, r in res.items():
        rw = r.get("reward")
        out[tid] = {"reward": rw, "passed": bool(r.get("passed")) if r.get("passed") is not None else (rw == 1.0 or rw == 1),
                    "tools": r.get("tool_calls"), "secs": r.get("secs")}
    return out


def load_cell(arm):
    """Merge *-b1/*-b2 batch files for one cell."""
    merged = {}
    for path in sorted(glob.glob(os.path.join(R6, f"bench_run_{arm}-b*.json")) +
                       glob.glob(os.path.join(R6, f"bench_run_{arm}.json"))):
        d = json.load(open(path, encoding="utf-8"))
        for tid, r in (d.get("results") or {}).items():
            merged[tid] = r
    return merged


def summ(cell):
    n = len(cell)
    exact = sum(1 for r in cell.values() if r.get("reward") == 1.0 or r.get("reward") == 1 or r.get("passed") is True)
    exec_ok = sum(1 for r in cell.values() if r.get("reward") is not None)  # verifier ran (not env/None)
    env_err = sum(1 for r in cell.values() if r.get("reward") is None)
    return {"n": n, "exact": exact, "exec_ran": exec_ok, "env_err": env_err}


def main():
    cells = {"P2-A0": load_r5_a0(), "P2-A1": load_cell("P2-A1"),
             "P3-A0": load_cell("P3-A0"), "P3-A1": load_cell("P3-A1")}
    report = {"experiment": "REALBENCH_SKILLS_READER_R6_DIAGNOSTIC", "cells": {}}
    for name, cell in cells.items():
        s = summ(cell)
        report["cells"][name] = s
        print(f"{name:7s} n={s['n']:2d}  exact_success={s['exact']:2d}/{s['n']:<2d}  "
              f"verifier_ran={s['exec_ran']:2d}  env_err={s['env_err']}")

    print("\n--- §3 viability per reader (skill = A1 vs no-skill = A0) ---")
    for reader, a0, a1 in [("P2/solar-pro2", "P2-A0", "P2-A1"), ("P3/solar-pro3", "P3-A0", "P3-A1")]:
        c0, c1 = cells[a0], cells[a1]
        if not c1:
            print(f"{reader}: A1 not yet available")
            continue
        # net gains: tasks where A1 passed and A0 did not
        a0pass = {t for t, r in c0.items() if r.get("reward") in (1, 1.0) or r.get("passed") is True}
        a1pass = {t for t, r in c1.items() if r.get("reward") in (1, 1.0) or r.get("passed") is True}
        net_gain = len(a1pass - a0pass)
        regress = len(a0pass - a1pass)
        s1 = summ(c1)
        viable = (s1["exec_ran"] >= 29 and s1["env_err"] == 0 and s1["exact"] >= 3 and net_gain >= 3)
        report.setdefault("viability", {})[reader] = {
            "A1_exact": s1["exact"], "A1_exec_ran": s1["exec_ran"], "A1_env_err": s1["env_err"],
            "net_gain_over_A0": net_gain, "regressions": regress, "viable": viable}
        print(f"{reader}: A1 exact={s1['exact']}/{s1['n']} exec_ran={s1['exec_ran']} env_err={s1['env_err']} "
              f"net_gain={net_gain} regress={regress} -> VIABLE={viable}")

    out = os.path.join(R6, "R6_2x2_aggregate.json")
    os.makedirs(R6, exist_ok=True)
    json.dump(report, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
