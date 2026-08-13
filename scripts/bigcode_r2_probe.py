"""Unpaid BigCodeBench feasibility/provenance probe (§3). Runs inside the official eval image. Loads the
official dataset, asserts the task count, grades K canonical solutions (expect PASS) and K corrupted
solutions (expect FAIL), and prints the platform-independent content_hash + official dataset hash so the
lock can be pinned. No Solar, no model calls. Exits non-zero on any provenance/grader failure (-> endpoint B)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from experiments.bigcode_r2 import grader as G   # noqa: E402

K = int(os.environ.get("PROBE_K", "12"))


def main():
    ids = G.all_task_ids()
    n = len(ids)
    print("task_count", n, flush=True)
    ch = G.content_hash()
    print("content_hash", ch, flush=True)
    try:
        dh = G.dataset_hash()
    except Exception as e:
        dh = "ERR:%s" % type(e).__name__
    print("official_dataset_hash", dh, flush=True)

    # deterministic spread of K tasks across the id space
    step = max(1, n // K)
    sample = ids[::step][:K]
    can_pass = wrong_fail = 0
    for tid in sample:
        ref = G.reference_solution(tid)
        r = G.grade(tid, ref)
        if r["base_pass"]:
            can_pass += 1
        else:
            print("CANON_FAIL", tid, r["status"], flush=True)
        # corrupt: replace the whole module with a wrong stub keeping the entry point name
        ep = G.task(tid)["entry_point"]
        wrong = "def %s(*a, **k):\n    return None\n" % ep
        rw = G.grade(tid, wrong)
        if not rw["base_pass"]:
            wrong_fail += 1
        else:
            print("WRONG_PASSED", tid, flush=True)
    print("canonical_pass %d/%d  wrong_fail %d/%d" % (can_pass, len(sample), wrong_fail, len(sample)), flush=True)

    out = {"task_count": n, "content_hash": ch, "official_dataset_hash": dh,
           "canonical_pass": can_pass, "canonical_n": len(sample),
           "wrong_fail": wrong_fail, "wrong_n": len(sample), "python": sys.version.split()[0]}
    os.makedirs(os.path.join("artifacts", "bigcode_r2"), exist_ok=True)
    with open(os.path.join("artifacts", "bigcode_r2", "provenance_probe.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)

    ok = (can_pass == len(sample)) and (wrong_fail == len(sample)) and n > 0
    if not ok:
        print("PROBE_FAIL: grader/provenance invalid -> BIGCODE INSTRUMENT STOP candidate", flush=True)
        sys.exit(2)
    print("PROBE_OK", flush=True)


if __name__ == "__main__":
    main()
