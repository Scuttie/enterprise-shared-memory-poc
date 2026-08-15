"""REALBENCH-R3 — thin wrapper over the OFFICIAL DS-1000 evaluator. We import the upstream `execution` module
(cloned at the pinned commit, placed on PYTHONPATH) and call its `check_correctness` verbatim — we never
reimplement or modify the benchmark's tests (§26 hard stop). This wrapper only assembles the completion-mode
program and returns pass/fail, so the same official grader is used for reference reproduction, source-bank
verification, calibration, and the confirmatory main.
"""
from __future__ import annotations
from experiments.actionable_memory_r3.ds1000_adapter import assemble_program


def grade(answer_code: str, code_context: str, timeout: float = 120.0, completion_id=None) -> dict:
    """Return {'passed': bool, 'result': str, 'passed_raw': <official dict>}. Import is deferred so this module
    is importable without the heavy DS-1000 env (only the CI grader job has it)."""
    import execution  # official upstream module, on PYTHONPATH in the grader env
    program = assemble_program(answer_code, code_context)
    out = execution.check_correctness(program, timeout=timeout, completion_id=completion_id)
    return {"passed": bool(out.get("passed")), "result": out.get("result"), "passed_raw": out}
