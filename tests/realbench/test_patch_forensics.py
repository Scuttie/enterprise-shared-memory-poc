"""REALBENCH-R2 §1.3 — evidence-based patch-adoption classifier tests. Core guarantee: a different failing
patch is NOT labelled adoption unless it contains a NEW source code element (import/API/control-flow/op)."""
from experiments import patch_forensics as PF


BASE = "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n"


def test_unrelated_error_when_no_source_element():
    # memory arm produced a DIFFERENT failing patch, but it shares no NEW element with the source.
    mem = "def f(xs):\n    return xs[0]\n"
    src = {"apis": ["bisect"], "operations": ["sorted"], "imports": ["bisect"], "control_flow": ["while_loop"]}
    cls, ev = PF.classify_loss(mem, BASE, src, injected=True)
    assert cls == "UNRELATED_IMPLEMENTATION_ERROR", (cls, ev)


def test_source_api_call_adoption():
    mem = "import bisect\ndef f(xs):\n    return bisect.bisect(xs, 3)\n"
    src = {"apis": ["bisect"], "imports": ["bisect"], "operations": [], "control_flow": []}
    cls, ev = PF.classify_loss(mem, BASE, src, injected=True)
    assert cls == "SOURCE_API_CALL_ADOPTION", (cls, ev)
    assert "bisect" in ev["adopted_apis"]


def test_operation_adoption_exact_and_partial():
    mem = "def f(xs):\n    return sorted(set(xs))\n"
    src_exact = {"operations": ["sorted", "set"], "apis": [], "imports": [], "control_flow": []}
    cls, _ = PF.classify_loss(mem, BASE, src_exact, injected=True)
    assert cls == "EXACT_SOURCE_OPERATION_ADOPTION", cls
    src_partial = {"operations": ["sorted", "set", "reversed"], "apis": [], "imports": [], "control_flow": []}
    cls2, _ = PF.classify_loss(mem, BASE, src_partial, injected=True)
    assert cls2 == "PARTIAL_SOURCE_OPERATION_ADOPTION", cls2


def test_control_flow_adoption():
    mem = "def f(xs):\n    return [x for x in xs if x]\n"          # comprehension is new vs BASE (for-loop)
    src = {"control_flow": ["comprehension"], "apis": [], "imports": [], "operations": []}
    cls, ev = PF.classify_loss(mem, BASE, src, injected=True)
    assert cls == "SOURCE_CONTROL_FLOW_ADOPTION", (cls, ev)


def test_not_injected_is_unrelated_not_adoption():
    mem = "import bisect\ndef f(xs):\n    return bisect.bisect(xs, 3)\n"
    src = {"apis": ["bisect"], "imports": ["bisect"], "operations": [], "control_flow": []}
    cls, _ = PF.classify_loss(mem, BASE, src, injected=False)
    assert cls == "UNRELATED_IMPLEMENTATION_ERROR", cls


def test_parser_or_apply_failure():
    cls, _ = PF.classify_loss("def f(:\n  pass", BASE, {"apis": ["x"]}, injected=True)
    assert cls == "PARSER_OR_APPLY_FAILURE", cls
    cls2, _ = PF.classify_loss("", BASE, {"apis": ["x"]}, injected=True)
    assert cls2 == "PARSER_OR_APPLY_FAILURE", cls2


def test_grader_failure_precedence():
    cls, _ = PF.classify_loss(BASE, BASE, {"apis": ["x"]}, injected=True, grader_ok=False)
    assert cls == "GRADER_FAILURE", cls


def test_unclassified_when_source_missing():
    mem = "import bisect\ndef f(xs):\n    return bisect.bisect(xs,3)\n"
    cls, _ = PF.classify_loss(mem, BASE, None, injected=True)
    assert cls == "UNCLASSIFIED", cls


def test_element_must_be_new_vs_base():
    # source element already present in the no-memory base patch -> not newly adopted -> unrelated.
    base = "import bisect\ndef f(xs):\n    return bisect.bisect(xs, 1)\n"
    mem = "import bisect\ndef f(xs):\n    return bisect.bisect(xs, 2)\n"
    src = {"apis": ["bisect"], "imports": ["bisect"], "operations": [], "control_flow": []}
    cls, _ = PF.classify_loss(mem, base, src, injected=True)
    assert cls == "UNRELATED_IMPLEMENTATION_ERROR", cls


def test_summarize_counts_all_classes():
    rows = [
        {"tid": "a", "arm": "M2", "memory_patch": "import bisect\ndef f():\n return bisect.bisect([],1)",
         "base_patch": BASE, "source": {"imports": ["bisect"], "apis": ["bisect"]}, "injected": True},
        {"tid": "b", "arm": "M2", "memory_patch": "def f():\n return 0", "base_patch": BASE,
         "source": {"apis": ["sorted"]}, "injected": True},
    ]
    s = PF.summarize(rows)
    assert s["n"] == 2 and s["counts"]["SOURCE_API_CALL_ADOPTION"] == 1
    assert s["counts"]["UNRELATED_IMPLEMENTATION_ERROR"] == 1
