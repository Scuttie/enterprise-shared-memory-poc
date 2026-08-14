"""Official BigCodeBench grader wrapper (REALBENCH-R2 §3). Thin, faithful shim over the official
`bigcodebench` package — NO benchmark test or reference solution is modified. Grading calls the official
`bigcodebench.evaluate.check_correctness` -> `bigcodebench.eval.untrusted_check`, which runs the task's own
`unittest.TestCase` under the official resource guards. That path uses the Unix `resource` module and the
pinned Python-3.10 eval dependency set, so it runs ONLY inside the official
`bigcodebench/bigcodebench-evaluate` image (Linux) — never on the Windows dev box or the 3.11 worker host.

Pass@1(BigCodeBench) = the task's base test suite passes (BigCodeBench has one test suite per task; there is
no separate "plus" set — `check_correctness` returns {"base": (status, details)}).
"""
from __future__ import annotations
import functools
import hashlib
import os

BIGCODE_SUBSET = os.environ.get("BIGCODE_SUBSET", "full")     # "full" (1140) or "hard" (148)
BIGCODE_VERSION = os.environ.get("BIGCODE_VERSION", "default")  # -> package BIGCODEBENCH_VERSION (v0.1.4)

# Official default resource limits (bigcodebench/evaluate.py main defaults). Frozen so grading is identical
# to the official run.
LIMITS = {"max_as_limit": 30 * 1024, "max_data_limit": 30 * 1024, "max_stack_limit": 10,
          "min_time_limit": 1.0, "gt_time_limit": 2.0}

_FIELDS = ("task_id", "entry_point", "complete_prompt", "instruct_prompt", "canonical_solution", "test")


@functools.lru_cache(maxsize=1)
def _dataset():
    from bigcodebench.data import get_bigcodebench
    return get_bigcodebench(subset=BIGCODE_SUBSET, version=BIGCODE_VERSION)


def task(tid):
    return _dataset()[tid]


def all_task_ids():
    return sorted(_dataset().keys())


def task_count():
    return len(_dataset())


def dataset_hash():
    """Official hash (line-ending sensitive across OS, like evalplus). Prefer content_hash() for pinning."""
    from bigcodebench.data import get_bigcodebench_hash
    return get_bigcodebench_hash(subset=BIGCODE_SUBSET, version=BIGCODE_VERSION)


def content_hash():
    """Platform-independent sha256 over the sorted official task fields (newline-normalised) so the pin is
    identical on every OS."""
    d = _dataset()
    h = hashlib.sha256()
    for tid in sorted(d):
        t = d[tid]
        for k in _FIELDS:
            v = t.get(k)
            s = "" if v is None else str(v).replace("\r\n", "\n").replace("\r", "\n")
            h.update(("\x1f%s\x1f%s\x1e" % (k, s)).encode("utf-8"))
    return h.hexdigest()


def reference_solution(task_id):
    """The official full reference (complete_prompt + canonical_solution), as get_groundtruth builds it.
    Used ONLY for source-fact verification and evaluator provenance checks — NEVER exposed to the backend or
    placed in memory."""
    t = _dataset()[task_id]
    return t["complete_prompt"] + "\n" + t["canonical_solution"]


def grade(task_id, candidate_code):
    """Grade one candidate through the OFFICIAL evaluator. Returns the base pass flag + status. Never
    receives or uses the reference solution (BigCodeBench tests are self-contained assertions)."""
    from bigcodebench.evaluate import check_correctness
    prob = _dataset()[task_id]
    try:
        ret = check_correctness(0, prob, candidate_code, LIMITS["max_as_limit"], LIMITS["max_data_limit"],
                                LIMITS["max_stack_limit"], identifier=task_id,
                                min_time_limit=LIMITS["min_time_limit"], gt_time_limit=LIMITS["gt_time_limit"])
        status = ret["base"][0] if isinstance(ret["base"], (list, tuple)) else ret["base"]
    except Exception as e:
        # A grader crash/timeout on a MODEL-generated candidate is a NON-PASS for that candidate (honest),
        # not a job failure. The grader itself is validated separately (canonical 12/12 in ci-bigcode-grader).
        return {"base_pass": False, "status": "grader_error:%s" % type(e).__name__, "exec_ok": False,
                "bigcodebench_pass": False}
    return {"base_pass": (status == "pass"), "status": status, "exec_ok": (status != "timeout"),
            "bigcodebench_pass": (status == "pass")}
