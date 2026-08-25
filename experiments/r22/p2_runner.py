#!/usr/bin/env python3
"""R22 §8 — P2 oracle development: 40 tasks x O1-O6 = 240 new cells; reuse the selected reader's 40 O0 (P2 analyzed
= 280). Starts only after reader-lock + P1_INTEGRITY_PASS verification (done by the workflow). FAKE mode offline."""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from experiments.r22 import paid_runner as PR   # noqa: E402

NEW_ARMS = ["O1", "O2", "O3", "O4", "O5", "O6"]      # O0 reused
ALL_ARMS = ["O0"] + NEW_ARMS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fake", "real"], default="fake")
    ap.add_argument("--provider"); ap.add_argument("--model", required=True); ap.add_argument("--secret-name")
    ap.add_argument("--hard-cap", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--reuse-o0-from", help="reader-band results.jsonl with the selected reader's O0 cells")
    a = ap.parse_args()
    spec = {"mode": "fake", "model": a.model} if a.mode == "fake" else {
        "mode": "real", "provider": a.provider, "model": a.model, "secret_name": a.secret_name}
    # run all 7 arms; if reuse provided, O0 cells are pre-seeded (not re-called)
    manifest, integ = PR.run(phase="p2", arms=ALL_ARMS, provider_spec=spec, hard_cap=a.hard_cap,
                             out_dir=a.out, n_tasks=a.n, reuse_o0_from=a.reuse_o0_from, task_prefix="dev")
    expected = a.n * len(ALL_ARMS)
    out = {"phase": "p2", "analyzed_cells": integ["cells"], "expected": expected,
           "new_cells_o1_o6": a.n * len(NEW_ARMS), "reused_o0": manifest["reused_o0"],
           "integrity_clean": integ["clean"], "violations": integ["violations"],
           "resolved_by_arm": manifest["resolved_by_arm"], "result_hash": manifest["results_sha256"],
           "ledger": manifest["ledger"], "NOTE": "development method-discovery; NOT confirmatory"}
    json.dump(out, open(os.path.join(a.out, "p2_summary.json"), "w", encoding="utf-8"), indent=2)
    print(json.dumps({k: out[k] for k in ("analyzed_cells", "expected", "reused_o0", "integrity_clean")}, indent=2))
    return 0 if (integ["clean"] and integ["cells"] == expected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
