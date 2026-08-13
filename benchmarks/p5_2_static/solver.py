"""P5.2 gold solver + executable grader + the memory-less 'prior' baseline (§4/§6). The gold patch is audit
/ memory-verification only and never enters a prompt. `prior_core_file` is the natural core-for-all-inputs
implementation a memory-less model tends to produce (no edge branch); by construction it passes prior_aligned
and fails context_inferable/prior_conflict at the edge."""
from __future__ import annotations
import sys
import types
import difflib


def solved_file(task) -> str:
    return task.gold_body


def prior_core_file(task) -> str:
    """Core-for-all-inputs (no edge branch) — the memory-less default."""
    from .families import _DOMAIN
    m = _DOMAIN[task.domain]["m"]
    return "%s:\n    return %d * %s\n" % (task.exact_signature, task.base, m)


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
        exec(compile(test_code, "t_%s" % task.target_symbol, "exec"), ns)
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
