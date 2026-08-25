#!/usr/bin/env python3
"""R22 §6 — reader-band O0 pilot on the frozen 40-task set for ONE candidate. Decides IN_BAND / OUT_OF_BAND /
R22_READER_BAND_STOP and (on IN_BAND) writes a reader-lock artifact. Does NOT auto-dispatch the next candidate.
FAKE mode is offline; REAL mode needs the named secret + approved cap.
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from experiments.r22 import paid_runner as PR   # noqa: E402

BAND = (0.10, 0.70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fake", "real"], default="fake")
    ap.add_argument("--provider"); ap.add_argument("--model", required=True); ap.add_argument("--secret-name")
    ap.add_argument("--hard-cap", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=40)
    a = ap.parse_args()
    spec = {"mode": "fake", "model": a.model} if a.mode == "fake" else {
        "mode": "real", "provider": a.provider, "model": a.model, "secret_name": a.secret_name}
    manifest, integ = PR.run(phase="reader_band", arms=["O0"], provider_spec=spec, hard_cap=a.hard_cap,
                             out_dir=a.out, n_tasks=a.n, task_prefix="dev")
    resolved = manifest["resolved_by_arm"]["O0"]
    rate = resolved / max(1, a.n)
    if not integ["clean"]:
        decision = "R22_READER_BAND_INTEGRITY_FAIL"
    elif BAND[0] <= rate <= BAND[1]:
        decision = "IN_BAND_SELECTED"
    else:
        decision = "OUT_OF_BAND_CONTINUE"
    dec = {"candidate_model": a.model, "resolved": resolved, "n": a.n, "resolved_rate": round(rate, 4),
           "band": BAND, "decision": decision, "integrity_clean": integ["clean"],
           "returned_model_drift_label": "MODEL_DRIFT_REPLICATION" if a.model == "deepseek-chat" else None,
           "note": "OUT_OF_BAND_CONTINUE requires a SEPARATE budget approval for the next frozen candidate"}
    json.dump(dec, open(os.path.join(a.out, "decision.json"), "w", encoding="utf-8"), indent=2)
    if decision == "IN_BAND_SELECTED":
        lock = {"schema": "r22/reader_lock/1.0.0", "provider": a.provider or "fake", "model": a.model,
                "requested_model": a.model, "returned_model": manifest["ledger"]["model"],
                "resolved_rate": round(rate, 4),
                "result_hash": manifest["results_sha256"],
                "paid_v2_freeze": _freeze_hash(), "grader": "official swebench (real) / local fixture (fake)"}
        lock["reader_lock_sha256"] = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
        json.dump(lock, open(os.path.join(a.out, "reader_lock.json"), "w", encoding="utf-8"), indent=2)
    print(json.dumps(dec, indent=2))
    return 0 if decision in ("IN_BAND_SELECTED", "OUT_OF_BAND_CONTINUE") else 1


def _freeze_hash():
    p = os.path.join(ROOT, "artifacts", "r22", "paid_v2_freeze.json")
    return json.load(open(p)).get("freeze_sha256") if os.path.isfile(p) else None


if __name__ == "__main__":
    raise SystemExit(main())
