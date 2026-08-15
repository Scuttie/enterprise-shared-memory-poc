"""REALBENCH-R3 §4 GATE — reproduce the OFFICIAL DS-1000 evaluator on the OFFICIAL reference solutions.

Feeds each task's `reference_code` as the completion `answer` through the upstream `execution.check_correctness`
(mirroring test_ds1000.py's ProcessPoolExecutor pattern) and asserts the reference passes at ~100%. If the
reference does not reproduce (>= REF_PASS_MIN), the official evaluator is not faithfully reproduced here ->
TECHNICAL STOP (exit 3). Also verifies task count and records the data-file sha256 + content hash.

Env:
  DS1000_REPO   path to the cloned xlang-ai/DS-1000 (default ./DS-1000); its dir is put on sys.path for `import execution`
  DS1000_SUBSET optional int -> evaluate only the first N-per-library (smoke); default full 1000
  REF_PASS_MIN  default 0.99
Writes artifacts/actionable_memory_r3/ds1000_reference_repro.json
"""
import collections
import concurrent.futures as cf
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
DS1000_REPO = os.environ.get("DS1000_REPO", os.path.join(REPO, "DS-1000"))
sys.path.insert(0, DS1000_REPO)  # so `import execution` resolves to the official module

from experiments.actionable_memory_r3 import ds1000_adapter as AD  # noqa: E402

DATA = os.path.join(DS1000_REPO, "data", "ds1000.jsonl.gz")
OUT = os.path.join(REPO, "artifacts", "actionable_memory_r3", "ds1000_reference_repro.json")
LOCK = json.load(open(os.path.join(REPO, "configs", "actionable_memory_r3", "ds1000_lock.json"),
                     encoding="utf-8"))
REF_PASS_MIN = float(os.environ.get("REF_PASS_MIN", "0.99"))


def _grade_one(args):
    tid, answer, code_context = args
    import execution  # official
    program = AD.assemble_program(answer, code_context)
    try:
        out = execution.check_correctness(program, timeout=120, completion_id=None)
        return tid, bool(out.get("passed")), str(out.get("result"))[:200]
    except Exception as e:  # never let one task crash the gate; record it as a non-pass with reason
        return tid, False, "DRIVER_EXC:%s" % (type(e).__name__)


def main():
    tasks = AD.load_tasks(DATA)
    sha = AD.data_sha256(DATA)
    chash = AD.content_hash(tasks)
    subset = os.environ.get("DS1000_SUBSET")
    if subset:
        n = int(subset)
        bylib = collections.defaultdict(list)
        for t in tasks:
            bylib[t["_library"]].append(t)
        tasks = [t for lib in bylib.values() for t in lib[:n]]
    jobs = [(t["_id"], t["reference_code"], t["code_context"]) for t in tasks]
    lib_of = {t["_id"]: t["_library"] for t in tasks}

    results = {}
    with cf.ProcessPoolExecutor(max_workers=int(os.environ.get("MAXW", "16"))) as ex:
        for tid, passed, res in ex.map(_grade_one, jobs):
            results[tid] = (passed, res)

    n = len(results)
    npass = sum(1 for p, _ in results.values() if p)
    per_lib = collections.defaultdict(lambda: [0, 0])
    for tid, (p, _) in results.items():
        per_lib[lib_of[tid]][1] += 1
        per_lib[lib_of[tid]][0] += 1 if p else 0
    fails = [{"tid": tid, "result": res} for tid, (p, res) in sorted(results.items()) if not p][:40]
    rate = npass / n if n else 0.0
    out = {
        "gate": "ds1000_reference_reproduction",
        "data_sha256": sha,
        "content_hash": chash,
        "expected_count": LOCK["task_count"],
        "evaluated_count": n,
        "reference_pass": npass,
        "reference_pass_rate": round(rate, 4),
        "per_library": {k: {"pass": v[0], "n": v[1], "rate": round(v[0] / v[1], 4)}
                        for k, v in sorted(per_lib.items())},
        "ref_pass_min": REF_PASS_MIN,
        "reproduced": rate >= REF_PASS_MIN,
        "subset": subset or "full",
        "sample_failures": fails,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=2, sort_keys=True)
    print("DS1000 reference reproduction:", json.dumps({k: out[k] for k in
          ("evaluated_count", "reference_pass_rate", "reproduced", "data_sha256", "content_hash")}), flush=True)
    print("per-library:", json.dumps(out["per_library"]), flush=True)
    if not subset and n != LOCK["task_count"]:
        print("TASK COUNT MISMATCH: %d != %d" % (n, LOCK["task_count"]), flush=True)
        sys.exit(2)
    if not out["reproduced"]:
        print("TECHNICAL STOP: reference solutions did not reproduce the official evaluator", flush=True)
        for f in fails[:10]:
            print("  FAIL", f["tid"], f["result"], flush=True)
        sys.exit(3)
    print("GATE PASS: official evaluator reproduced on reference solutions", flush=True)


if __name__ == "__main__":
    main()
