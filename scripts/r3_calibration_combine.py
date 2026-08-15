"""REALBENCH-R3 §16 — combine calibration raw chunks -> technical gate decision (G1-G7). A null/negative memory
effect does NOT block the main; only TECHNICAL failures do. Writes calibration_results.json + prints PASS or
CALIBRATION STOP. Light. Usage: python scripts/r3_calibration_combine.py"""
import collections
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from experiments.actionable_memory_r3.main_seeding import CALIB_ARMS  # noqa: E402

ART = os.path.join(REPO, "artifacts", "actionable_memory_r3")


def main():
    rows, seen, bundle = [], set(), None
    for f in sorted(glob.glob(os.path.join(ART, "results", "calib_raw.*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        bundle = bundle or d.get("selected_bundle")
        for r in d["rows"]:
            k = (r["arm"], r["tid"])
            if k in seen:
                continue
            seen.add(k); rows.append(r)
    if not rows:
        raise SystemExit("no calibration raw chunks")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    p1 = lambda a: (sum(x["pass1"] for x in by[a]) / len(by[a])) if by.get(a) else 0.0
    arms_pass1 = {a: round(p1(a), 4) for a in CALIB_ARMS}
    c0 = p1("C0")
    malformed = sum(1 for r in rows if r.get("state") not in ("SUCCEEDED", None) and r.get("exec1") == 0)
    malformed_rate = round(malformed / max(1, len(rows)), 4)
    cross_user = sum(r.get("cross_user", 0) for r in rows)
    # injection sanity: C1/C2/C3/C4/C5 (memory arms) should inject on covered targets; C0 must not inject
    c0_inject = sum(r.get("injected", 0) for r in by.get("C0", []))
    gates = {
        "G1_malformed_le_0.02": malformed_rate <= 0.02,
        "G3_dynamic_range_C0_in_[0.10,0.90]": 0.10 <= c0 <= 0.90,
        "G4_cross_user_private_injection_0": cross_user == 0,
        "G4_C0_no_injection": c0_inject == 0,
        "G6_production_embedder": os.environ.get("EMBEDDER", "st") == "st",
    }
    decision = "PASS" if all(gates.values()) else "CALIBRATION_STOP"
    out = {"experiment": "R3_CALIBRATION", "selected_bundle": bundle, "n_rows": len(rows),
           "arms_pass1": arms_pass1, "C0_no_memory_pass1": round(c0, 4), "malformed_rate": malformed_rate,
           "cross_user_private_injection": cross_user, "gates": gates, "decision": decision,
           "note": "technical gates only; a null/negative memory effect does not block the main (§16)"}
    json.dump(out, open(os.path.join(ART, "results", "calibration_results.json"), "w", encoding="utf-8",
                        newline="\n"), indent=2, sort_keys=True)
    print("CALIB arms_pass1:", arms_pass1, flush=True)
    print("gates:", gates, flush=True)
    print("DECISION:", decision, flush=True)
    if decision != "PASS":
        sys.exit(4)


if __name__ == "__main__":
    main()
