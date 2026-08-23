"""Evidence-based patch-adoption forensics (REALBENCH-R2 §1.3 / §13).

Replaces the R1 heuristic that labelled EVERY changed-and-failing memory-arm patch
PARTIAL_MEMORY_PATTERN_ADOPTION. A different failing patch alone is NOT adoption. A loss is only
classified as source adoption when the memory-arm patch contains a concrete code element (an imported
library, a called API, a control-flow structure, or an algorithmic operation) that (a) is NEW relative to
the no-memory patch for the same task and (b) is present in the source memory. Classification is computed
from AST/API/import/control-flow comparison, never inferred from Pass@1.

Classes (§1.3):
  EXACT_SOURCE_OPERATION_ADOPTION   memory-arm patch adopts the source's full operation set (new vs base)
  PARTIAL_SOURCE_OPERATION_ADOPTION memory-arm patch adopts some (not all) source operations
  SOURCE_API_CALL_ADOPTION          memory-arm patch newly calls an API present in the source
  SOURCE_CONTROL_FLOW_ADOPTION      memory-arm patch newly uses a control-flow pattern present in the source
  UNRELATED_IMPLEMENTATION_ERROR    failing patch shares no new source element (or memory was not injected)
  PARSER_OR_APPLY_FAILURE           patch absent or does not parse (never reached the grader as valid code)
  GRADER_FAILURE                    the evaluator itself errored (not a code defect)
  UNCLASSIFIED                      injected + parses but source signature unavailable to compare
"""
from __future__ import annotations
import ast

CLASSES = ("EXACT_SOURCE_OPERATION_ADOPTION", "PARTIAL_SOURCE_OPERATION_ADOPTION", "SOURCE_API_CALL_ADOPTION",
           "SOURCE_CONTROL_FLOW_ADOPTION", "UNRELATED_IMPLEMENTATION_ERROR", "PARSER_OR_APPLY_FAILURE",
           "GRADER_FAILURE", "UNCLASSIFIED")

_CF_NODES = {"For": "for_loop", "AsyncFor": "for_loop", "While": "while_loop", "If": "conditional",
             "Try": "try_except", "With": "context_manager", "ListComp": "comprehension",
             "SetComp": "comprehension", "DictComp": "comprehension", "GeneratorExp": "comprehension",
             "Lambda": "lambda"}
# operation-bearing builtins/keywords whose presence marks an algorithmic operation
_OP_BUILTINS = {"sorted", "sort", "map", "filter", "reduce", "zip", "enumerate", "sum", "min", "max",
                "any", "all", "set", "dict", "list", "reversed", "round", "abs", "range", "len", "join",
                "split", "format", "bisect", "heappush", "heappop", "combinations", "permutations",
                "groupby", "Counter", "defaultdict", "gcd", "sqrt", "ceil", "floor"}


def patch_signature(code):
    """Extract concrete evidence elements from a code string. Returns None on parse failure so the caller
    can classify PARSER_OR_APPLY_FAILURE / UNCLASSIFIED rather than silently treating it as empty."""
    if not code or not str(code).strip():
        return None
    try:
        tree = ast.parse(str(code))
    except SyntaxError:
        return None
    imports, apis, cf, ops = set(), set(), set(), set()
    for n in ast.walk(tree):
        t = type(n).__name__
        if t in _CF_NODES:
            cf.add(_CF_NODES[t])
        if isinstance(n, ast.Import):
            for a in n.names:
                imports.add(a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            if n.module:
                imports.add(n.module.split(".")[0])
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                apis.add(f.attr)
                if f.attr in _OP_BUILTINS:
                    ops.add(f.attr)
            elif isinstance(f, ast.Name):
                apis.add(f.id)
                if f.id in _OP_BUILTINS:
                    ops.add(f.id)
    return {"imports": imports, "apis": apis, "control_flow": cf, "operations": ops}


def _as_sig(x):
    """Accept either a code string or a pre-extracted signature dict (source operation/API tags from the
    source bank). Sets are coerced from any iterable."""
    if x is None:
        return None
    if isinstance(x, dict):
        return {k: set(x.get(k, ())) for k in ("imports", "apis", "control_flow", "operations")}
    return patch_signature(x)


def classify_loss(memory_patch, base_patch, source, *, injected, exec_ok=True, grader_ok=True):
    """Classify a memory-induced loss (base/no-memory passed, memory arm failed) with evidence.

    memory_patch / base_patch: applied patch code strings (from persisted job_patches).
    source: the source memory's code trace OR a signature dict of its operation/API/import/control-flow tags.
    injected: whether the retrieval layer actually injected memory for this job (DB truth).
    exec_ok: whether the candidate executed (False => the grader ran but the code raised/timed out).
    grader_ok: whether the evaluator itself completed (False => infra/evaluator error, not a code defect).
    Returns (class, evidence_dict).
    """
    if not grader_ok:
        return "GRADER_FAILURE", {}
    msig = _as_sig(memory_patch)
    if msig is None:
        return "PARSER_OR_APPLY_FAILURE", {"reason": "memory-arm patch absent or unparseable"}
    if not injected:
        return "UNRELATED_IMPLEMENTATION_ERROR", {"reason": "memory not injected -> loss cannot be adoption"}
    ssig = _as_sig(source)
    if ssig is None:
        return "UNCLASSIFIED", {"reason": "source signature unavailable"}
    bsig = _as_sig(base_patch) or {"imports": set(), "apis": set(), "control_flow": set(), "operations": set()}
    # NEW elements the memory arm introduced relative to the no-memory patch
    new_ops = (msig["operations"] - bsig["operations"]) & ssig["operations"]
    new_apis = (msig["apis"] - bsig["apis"]) & ssig["apis"]
    new_imports = (msig["imports"] - bsig["imports"]) & ssig["imports"]
    new_cf = (msig["control_flow"] - bsig["control_flow"]) & ssig["control_flow"]
    ev = {"adopted_operations": sorted(new_ops), "adopted_apis": sorted(new_apis | new_imports),
          "adopted_control_flow": sorted(new_cf), "source_operations": sorted(ssig["operations"])}
    if new_ops:
        cls = "EXACT_SOURCE_OPERATION_ADOPTION" if ssig["operations"] and new_ops >= ssig["operations"] \
            else "PARTIAL_SOURCE_OPERATION_ADOPTION"
        return cls, ev
    if new_apis or new_imports:
        return "SOURCE_API_CALL_ADOPTION", ev
    if new_cf:
        return "SOURCE_CONTROL_FLOW_ADOPTION", ev
    return "UNRELATED_IMPLEMENTATION_ERROR", {"reason": "no new source element in the failing patch",
                                              "source_operations": sorted(ssig["operations"])}


def summarize(rows):
    """rows: iterable of dicts with keys memory_patch, base_patch, source, injected, exec_ok, grader_ok.
    Returns per-class counts + the classified rows (evidence attached)."""
    counts = {c: 0 for c in CLASSES}
    out = []
    for r in rows:
        cls, ev = classify_loss(r.get("memory_patch"), r.get("base_patch"), r.get("source"),
                                injected=r.get("injected", False), exec_ok=r.get("exec_ok", True),
                                grader_ok=r.get("grader_ok", True))
        counts[cls] += 1
        out.append({**{k: r.get(k) for k in ("tid", "arm")}, "class": cls, "evidence": ev})
    adoption = sum(counts[c] for c in CLASSES[:4])
    return {"counts": counts, "n": len(out), "adoption_total": adoption,
            "unrelated": counts["UNRELATED_IMPLEMENTATION_ERROR"], "rows": out}
