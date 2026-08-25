#!/usr/bin/env python3
"""R22 §7 — P1 real-reader integration smoke: 12 tasks x O0-O6 = 84 cells. Integrity gate -> P1_INTEGRITY_PASS or
R22_P1_INTEGRATION_STOP. No efficacy conclusion. FAKE mode offline; REAL mode needs the verified reader lock."""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from experiments.r22 import paid_runner as PR   # noqa: E402

ARMS = ["O0", "O1", "O2", "O3", "O4", "O5", "O6"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fake", "real"], default="fake")
    ap.add_argument("--provider"); ap.add_argument("--model", required=True); ap.add_argument("--secret-name")
    ap.add_argument("--hard-cap", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=12)
    a = ap.parse_args()
    spec = {"mode": "fake", "model": a.model} if a.mode == "fake" else {
        "mode": "real", "provider": a.provider, "model": a.model, "secret_name": a.secret_name}
    manifest, integ = PR.run(phase="p1", arms=ARMS, provider_spec=spec, hard_cap=a.hard_cap,
                             out_dir=a.out, n_tasks=a.n, task_prefix="smoke")
    expected = a.n * len(ARMS)
    verdict = "P1_INTEGRITY_PASS" if (integ["clean"] and integ["cells"] == expected) else "R22_P1_INTEGRATION_STOP"
    out = {"phase": "p1", "verdict": verdict, "cells": integ["cells"], "expected": expected,
           "integrity_clean": integ["clean"], "violations": integ["violations"],
           "resolved_by_arm": manifest["resolved_by_arm"],
           "NOTE": "NO EFFICACY CONCLUSION — INTEGRATION SMOKE",
           "result_hash": manifest["results_sha256"], "ledger": manifest["ledger"]}
    json.dump(out, open(os.path.join(a.out, "integrity_result.json"), "w", encoding="utf-8"), indent=2)
    print(json.dumps({k: out[k] for k in ("verdict", "cells", "expected", "integrity_clean")}, indent=2))
    return 0 if verdict == "P1_INTEGRITY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
