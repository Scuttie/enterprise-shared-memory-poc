"""REALBENCH-R3 §7 — derive the ONE CanonicalActionMemory per verified source.

Two deterministic-then-abstracted stages:
  1. STRUCTURAL (deterministic, AST): required_imports / relevant_apis / ordered_operations / control_flow /
     source_constants — extracted from the verified source solution. source_constants (numeric/string literals
     and non-library identifiers) are MARKED so no renderer can emit them as target facts.
  2. SEMANTIC (one temp-0 model abstraction over the SOURCE problem + verified solution only): task_family,
     contracts, preconditions/postconditions/invariants, applicability, ordered_operations prose,
     positive/negative pattern, generalized_ast_edit, generalized_diff_template (placeholders only), executable
     properties, verification_procedure. The model NEVER sees the target; the prompt forbids source-specific
     literals/names (placeholders VAR/ARR/DF/N only). The same canonical object then feeds every renderer
     deterministically (§8) — we never write separate per-format memories.

The abstraction is a source-side memory-formation step (promotion), not a target solve. If it fails to parse,
the source still yields a structural-only canonical object (renderers degrade gracefully).
"""
from __future__ import annotations
import ast
import hashlib
import json
import re

from experiments import patch_forensics as PF
from experiments.actionable_memory_r3.schema import CanonicalActionMemory

_LIB_ROOTS = {"numpy", "np", "pandas", "pd", "scipy", "sklearn", "matplotlib", "plt", "torch", "tensorflow",
              "tf", "math", "collections", "itertools", "re", "copy", "os", "sys"}


def _hash(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()


def structural(solution_code: str) -> dict:
    sig = PF.patch_signature(solution_code) or {"imports": set(), "apis": set(), "control_flow": set(),
                                                 "operations": set()}
    consts, names = set(), set()
    try:
        tree = ast.parse(solution_code or "")
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, str, bytes)):
                v = n.value
                if isinstance(v, str) and len(v) <= 40:
                    consts.add(repr(v))
                elif isinstance(v, (int, float)):
                    consts.add(repr(v))
            elif isinstance(n, ast.Name) and n.id not in _LIB_ROOTS and not n.id.startswith("__"):
                names.add(n.id)
    except SyntaxError:
        pass
    return {"required_imports": sorted(sig["imports"]), "relevant_apis": sorted(sig["apis"]),
            "operations": sorted(sig["operations"]), "control_flow": sorted(sig["control_flow"]),
            "source_constants": sorted(consts | names)}


ABSTRACTION_PROMPT = (
    "You are forming a REUSABLE coding memory from one verified solved example, for a data-science coding "
    "assistant. Abstract the technique so it can transfer to OTHER problems in the same library. Output STRICT "
    "JSON only (no prose, no code fences) with these keys:\n"
    '{"task_family":str,"input_contract":str,"output_contract":str,"preconditions":[str],'
    '"postconditions":[str],"invariants":[str],"applicability":str,"non_applicability":str,'
    '"ordered_operations":[str],"control_flow_pattern":str,"data_transformation":str,"common_failure":str,'
    '"positive_pattern":str,"negative_pattern":str,"generalized_ast_edit":[str],'
    '"generalized_diff_template":str,"executable_properties":[str],"verification_procedure":[str]}\n'
    "HARD RULES:\n"
    "- Use ONLY placeholders for any value/name (VAR, ARR, DF, COL, N, K, AXIS). NEVER copy a specific number, "
    "string literal, column name, or variable name from the example.\n"
    "- Describe the general method, preconditions, and how to verify — not this one answer.\n"
    "- generalized_ast_edit: 3-6 abstract ops like 'REPLACE call X with Y', 'INSERT guard before loop', "
    "'WRAP expression with normalization', 'PRESERVE return variable'.\n"
    "- generalized_diff_template: a short unified-diff-like sketch with placeholders, no real identifiers.\n"
    "- executable_properties: 2-4 checkable properties/invariants the correct output must satisfy.\n"
    "LIBRARY: %s\nPROBLEM:\n%s\nVERIFIED SOLUTION:\n%s\n"
)


def build_prompt(library: str, problem: str, solution: str) -> str:
    return ABSTRACTION_PROMPT % (library, problem[:2000], solution[:1200])


_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_abstraction(text: str) -> dict:
    m = _JSON_RE.search(text or "")
    if not m:
        return {}
    try:
        d = json.loads(m.group(0))
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        return {}


def _strip_source_constants(fields: dict, source_constants: list[str]) -> dict:
    """Belt-and-suspenders: blank any semantic string that leaked a marked source constant/name."""
    bad = [c.strip("'\"") for c in source_constants if len(c.strip("'\"")) >= 3 and not c.strip("'\"").isdigit()]
    def clean(v):
        if isinstance(v, str):
            return "" if any(b in v for b in bad) else v
        if isinstance(v, list):
            return [x for x in (clean(i) for i in v) if x]
        return v
    return {k: clean(v) for k, v in fields.items()}


def assemble(source_task: dict, solution_code: str, source_user: str, evaluator_hash: str,
             semantic: dict) -> CanonicalActionMemory:
    st = structural(solution_code)
    sem = _strip_source_constants(semantic or {}, st["source_constants"])
    md = source_task.get("metadata", {})
    lib = md.get("library", "")
    cam = CanonicalActionMemory(
        source_task_id="ds1000_%s" % md.get("problem_id"), source_user_id=source_user,
        source_solution_hash=_hash(solution_code), source_evaluator_hash=evaluator_hash,
        task_family=sem.get("task_family", lib.lower()), language="python", libraries=(lib,),
        required_imports=tuple(st["required_imports"]), relevant_apis=tuple(st["relevant_apis"]),
        input_contract=sem.get("input_contract", ""), output_contract=sem.get("output_contract", ""),
        preconditions=tuple(sem.get("preconditions", []) or []),
        postconditions=tuple(sem.get("postconditions", []) or []),
        invariants=tuple(sem.get("invariants", []) or []),
        applicability=sem.get("applicability", ""), non_applicability=sem.get("non_applicability", ""),
        ordered_operations=tuple(sem.get("ordered_operations", []) or st["operations"]),
        control_flow_pattern=sem.get("control_flow_pattern", ", ".join(st["control_flow"])),
        data_transformation=sem.get("data_transformation", ""),
        common_failure=sem.get("common_failure", ""), positive_pattern=sem.get("positive_pattern", ""),
        negative_pattern=sem.get("negative_pattern", ""),
        generalized_ast_edit=tuple(sem.get("generalized_ast_edit", []) or []),
        generalized_diff_template=sem.get("generalized_diff_template", ""),
        verification_procedure=tuple(sem.get("verification_procedure", []) or []),
        validity="verified_source_success", provenance={"source_user": source_user, "library": lib,
                                                         "problem_id": md.get("problem_id")},
        evidence={"solution_code": solution_code,
                  "executable_properties": list(sem.get("executable_properties", []) or [])},
        governance_state="promoted_shared", source_constants=tuple(st["source_constants"]))
    return cam
