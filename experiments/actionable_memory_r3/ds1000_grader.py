"""REALBENCH-R3 — thin wrapper over the OFFICIAL DS-1000 evaluator. We import the upstream `execution` module
(cloned at the pinned commit, placed on PYTHONPATH) and call its `check_correctness` verbatim — we never
reimplement or modify the benchmark's tests (§26 hard stop). The same official grader is used for reference
reproduction, source-bank verification, calibration, and the confirmatory main (service path routes here via the
`DS1000:<problem_id>` grading marker).
"""
from __future__ import annotations
import functools
import gzip
import json
import os
import re

from experiments.actionable_memory_r3.ds1000_adapter import assemble_program


@functools.lru_cache(maxsize=1)
def _tasks(data_path: str) -> dict:
    """problem_id(str) -> task record, from the pinned ds1000.jsonl.gz."""
    out = {}
    with gzip.open(data_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[str(r["metadata"]["problem_id"])] = r
    return out


def _data_path() -> str:
    return os.environ.get("DS1000_DATA", os.path.join(os.environ.get("DS1000_REPO", "DS-1000"),
                                                       "data", "ds1000.jsonl.gz"))


def extract_completion(raw: str) -> str:
    """Extract the DS-1000 solution snippet from a chat model's raw output. Deterministic post-processing:
    take a fenced ```python block if present, else the raw text; then cut at the upstream solution markers
    (END SOLUTION / </code>) and drop a leading BEGIN SOLUTION marker. No benchmark semantics are altered —
    this only recovers the completion string the official grader assigns to `code`."""
    if raw is None:
        return ""
    m = re.search(r"```(?:python)?\s*(.*?)```", raw, re.S)
    body = m.group(1) if m else raw
    # drop everything from an explicit solution terminator onward
    for term in ("END SOLUTION", "</code>", "\nprint(", "\nresult ="):
        pass
    idx = min([i for i in (body.find("END SOLUTION"), body.find("</code>")) if i != -1], default=-1)
    if idx != -1:
        body = body[:idx]
    body = body.replace("BEGIN SOLUTION", "")
    return body.strip("\n") + "\n"


def grade(answer_code: str, code_context: str, timeout: float = 120.0, completion_id=None) -> dict:
    import execution  # official upstream module, on PYTHONPATH in the grader env
    program = assemble_program(answer_code, code_context)
    out = execution.check_correctness(program, timeout=timeout, completion_id=completion_id)
    return {"passed": bool(out.get("passed")), "result": out.get("result"), "passed_raw": out}


def grade_by_id(problem_id, raw_or_answer: str, *, already_extracted: bool = False,
                timeout: float = 120.0) -> dict:
    """Grade a service-path candidate for DS-1000 `problem_id`. `raw_or_answer` is the model's raw output
    (extracted here) unless already_extracted. Returns {'passed', 'result', 'answer'}.

    In the ESM service (R3_GRADE_SUBPROCESS=1, and NOT already inside the isolated child) the official grader is
    run in a CLEAN subprocess (scripts/r3_ds1000_grade_one.py) so its multiprocessing.Process fork never forks
    the heavy async worker (torch/tf/ST loaded -> fork+threads deadlock). Otherwise it runs in-process (used by
    the child and by the reference-reproduction driver, which already runs in a clean interpreter)."""
    answer = raw_or_answer if already_extracted else extract_completion(raw_or_answer)
    if os.environ.get("R3_GRADE_SUBPROCESS") == "1" and os.environ.get("R3_GRADE_IN_CHILD") != "1":
        return _grade_subprocess(problem_id, answer, timeout=timeout)
    task = _tasks(_data_path()).get(str(problem_id))
    if task is None:
        return {"passed": False, "result": "unknown_problem_id:%s" % problem_id, "answer": ""}
    r = grade(answer, task["code_context"], timeout=timeout)
    return {"passed": r["passed"], "result": r["result"], "answer": answer}


def _grade_subprocess(problem_id, answer: str, *, timeout: float = 120.0) -> dict:
    import json as _json
    import subprocess
    import sys
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "scripts", "r3_ds1000_grade_one.py")
    try:
        p = subprocess.run([sys.executable, script, str(problem_id)], input=answer, text=True,
                           capture_output=True, timeout=timeout + 60)
        line = [ln for ln in (p.stdout or "").splitlines() if ln.strip().startswith("{")]
        if not line:
            return {"passed": False, "result": "no_grade_output:%s" % (p.stderr or "")[:160], "answer": answer}
        d = _json.loads(line[-1])
        return {"passed": bool(d.get("passed")), "result": d.get("result"), "answer": answer}
    except subprocess.TimeoutExpired:
        return {"passed": False, "result": "grade_subprocess_timeout", "answer": answer}
