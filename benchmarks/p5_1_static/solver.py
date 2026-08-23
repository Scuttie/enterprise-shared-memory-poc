"""Gold solver + in-process executable grader (P5.1 §6). The gold patch is used ONLY for benchmark audit and
memory-bank verification; it must never enter any model prompt. The grader compiles a candidate solution and
runs the (never-shipped) hidden test to decide pass/fail — the same grading the worker sandbox performs."""
from __future__ import annotations
import sys
import types
import difflib


def solved_file(task) -> str:
    """The correct full source file (uses the world constant C)."""
    return task.gold_body


def wrong_world_file(task) -> str:
    """A plausible un-memorised solution that uses the common prior default D instead of the convention C.
    It passes the (incomplete) public test but fails the hidden test."""
    from .families import _DOMAIN
    expr = _DOMAIN[task.domain]["expr"] % task.prior_default
    return "%s:\n    return %s\n" % (task.exact_signature, expr)


def gold_patch(task) -> str:
    a = task.src_stub.splitlines(keepends=True)
    b = solved_file(task).splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, fromfile="a/%s" % task.target_path,
                                        tofile="b/%s" % task.target_path))


def _load(task, src_code):
    modname = "src.%s" % task.target_symbol
    if "src" not in sys.modules:
        pkg = types.ModuleType("src"); pkg.__path__ = []; sys.modules["src"] = pkg
    mod = types.ModuleType(modname)
    exec(compile(src_code, task.target_path, "exec"), mod.__dict__)
    sys.modules[modname] = mod
    return modname


def _run(task, src_code, test_code) -> bool:
    modname = _load(task, src_code)
    try:
        ns = {}
        exec(compile(test_code, "test_%s" % task.target_symbol, "exec"), ns)
        for k, v in ns.items():
            if k.startswith("test_") and callable(v):
                v()
        return True
    except AssertionError:
        return False
    finally:
        sys.modules.pop(modname, None)


def passes_hidden(task, src_code) -> bool:
    return _run(task, src_code, task.hidden_test)


def passes_public(task, src_code) -> bool:
    return _run(task, src_code, task.public_test)
