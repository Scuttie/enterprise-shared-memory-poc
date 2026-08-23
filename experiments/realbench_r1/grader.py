"""Official EvalPlus MBPP+ grader wrapper (§5/§11). A candidate solution is graded with the OFFICIAL
`evalplus.eval.untrusted_check` against the official base + plus (augmented) inputs; ground-truth expected
outputs come from the official canonical solution (computed server-side, NEVER shown to the coding backend).
Pass@1 for MBPP+ requires BOTH base and plus to pass.

The evalplus 0.3.1 whole-dataset ground-truth cache cannot pickle rare re.Match outputs; we compute
ground-truth per task in-memory (pickle cache disabled) to stay on the official code path without that bug."""
from __future__ import annotations
import functools


@functools.lru_cache(maxsize=1)
def _dataset():
    from evalplus.data import get_mbpp_plus
    from evalplus.data.mbpp import get_mbpp_plus_hash
    return get_mbpp_plus(), get_mbpp_plus_hash()


@functools.lru_cache(maxsize=2048)
def _groundtruth(task_id):
    # replicate evalplus.evaluate.get_groundtruth per task, IN MEMORY (no shared-hash pickle cache), using the
    # official trusted_exec on the official canonical solution.
    from evalplus.gen.util import trusted_exec
    from evalplus.eval._special_oracle import MBPP_OUTPUT_NOT_NONE_TASKS
    p = _dataset()[0][task_id]
    onn = p["entry_point"] in MBPP_OUTPUT_NOT_NONE_TASKS
    code = p["prompt"] + p["canonical_solution"]
    base, base_t = trusted_exec(code, p["base_input"], p["entry_point"], record_time=True, output_not_none=onn)
    plus, plus_t = trusted_exec(code, p["plus_input"], p["entry_point"], record_time=True, output_not_none=onn)
    return {"base": base, "base_time": base_t, "plus": plus, "plus_time": plus_t}


def dataset_hash():
    return _dataset()[1]                              # evalplus file hash (line-ending sensitive; informational)


@functools.lru_cache(maxsize=1)
def content_hash():
    """Platform-independent content hash of the official MBPP+ tasks (task_id + entry_point + prompt +
    canonical + base/plus inputs), so provenance is stable across OSes (unlike get_mbpp_plus_hash)."""
    import hashlib
    d = _dataset()[0]
    h = hashlib.sha256()
    for tid in sorted(d.keys()):
        p = d[tid]
        h.update(("%s|%s|%s|%s|%r|%r" % (tid, p["entry_point"], p["prompt"], p["canonical_solution"],
                                         p["base_input"], p["plus_input"])).encode("utf-8", "replace"))
    return h.hexdigest()


def task(task_id):
    return _dataset()[0][task_id]


def grade(task_id, candidate_code):
    """Return {base_pass, plus_pass, mbpp_plus_pass, exec_ok}. exec_ok = the candidate executed at all."""
    from evalplus.eval import untrusted_check, PASS
    p = _dataset()[0][task_id]
    gt = _groundtruth(task_id)
    entry = p["entry_point"]
    atol = p["atol"]

    def _check(inputs, expected, times):
        if not inputs:
            return True
        st, _ = untrusted_check("mbpp", candidate_code, inputs, entry, expected, atol, times,
                                fast_check=False, min_time_limit=1.0, gt_time_limit_factor=4.0)
        return st == PASS

    try:
        base = _check(p["base_input"], gt["base"], gt["base_time"])
        plus = _check(p["plus_input"], gt["plus"], gt["plus_time"])
        exec_ok = True
    except Exception:
        return {"base_pass": False, "plus_pass": False, "mbpp_plus_pass": False, "exec_ok": False}
    return {"base_pass": bool(base), "plus_pass": bool(plus), "mbpp_plus_pass": bool(base and plus),
            "exec_ok": exec_ok}


def all_task_ids():
    return list(_dataset()[0].keys())


# NOTE: the official evalplus grader (unsafe_execute) requires the Unix `resource` module and therefore runs
# only on Linux (CI). Grading is never performed on the local Windows host; canonical-pass / wrong-fail
# validation is done in ci-realbench-grader.
