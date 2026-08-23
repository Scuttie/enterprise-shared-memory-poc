"""REALBENCH-R3 — isolated single-task DS-1000 grader entrypoint. Run as a CLEAN subprocess by the ESM worker so
the official evaluator's multiprocessing.Process fork never forks the heavy async worker (torch/tf/ST loaded ->
fork+threads deadlock). Reads problem_id from argv[1] and the already-extracted completion from stdin; prints one
JSON line {"passed":bool,"result":str}. Uses the OFFICIAL execution.check_correctness unchanged.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.environ.get("DS1000_REPO", os.path.join(REPO, "DS-1000")))
os.environ["R3_GRADE_IN_CHILD"] = "1"

from experiments.actionable_memory_r3 import ds1000_grader as G  # noqa: E402


def main():
    pid = sys.argv[1]
    answer = sys.stdin.read()
    try:
        r = G.grade_by_id(pid, answer, already_extracted=True)
        print(json.dumps({"passed": bool(r["passed"]), "result": str(r["result"])[:300]}))
    except Exception as e:  # a grader crash on a candidate is an honest NON-PASS, never a worker hang
        print(json.dumps({"passed": False, "result": "GRADE_EXC:%s" % type(e).__name__}))


if __name__ == "__main__":
    main()
