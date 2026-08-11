"""Production unified-diff applicator (§2.2). Moved out of the research benchmark package so production
code never imports `benchmarks`/`research`. Tolerant hunk application (ignores @@ line numbers, matches by
context) with bounded-edit validation."""
from __future__ import annotations
import ast
import re

LINE_BUDGET = 12


class PatchError(Exception):
    pass


def _find_block(text_lines, before):
    if not before:
        return -1
    n = len(before)
    strip = [b.rstrip() for b in before]
    for i in range(0, len(text_lines) - n + 1):
        if [t.rstrip() for t in text_lines[i:i + n]] == strip:
            return i
    return -1


def apply_unified_diff(original: str, diff: str):
    """Apply a (possibly fenced) unified diff to `original`. Returns (new_text, meta) or raises PatchError."""
    body = diff
    m = re.search(r"```(?:diff|patch)?\s*(.*?)```", diff, re.S)
    if m:
        body = m.group(1)
    hunks = []
    cur = None
    for ln in body.splitlines():
        if ln.startswith("@@"):
            if cur is not None:
                hunks.append(cur)
            cur = []
        elif cur is not None:
            if ln.startswith("--- ") or ln.startswith("+++ "):
                continue
            cur.append(ln)
        elif ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")):
            cur = [ln]
    if cur is not None:
        hunks.append(cur)
    if not hunks:
        raise PatchError("no_hunks")
    lines = original.split("\n")
    add = dele = 0
    added_lines = []
    for h in hunks:
        before = [l[1:] for l in h if l[:1] in (" ", "-")]
        after = [l[1:] for l in h if l[:1] in (" ", "+")]
        add += sum(1 for l in h if l[:1] == "+")
        dele += sum(1 for l in h if l[:1] == "-")
        added_lines += [l[1:] for l in h if l[:1] == "+"]
        idx = _find_block(lines, before)
        if idx < 0:
            raise PatchError("context_not_found")
        lines = lines[:idx] + after + lines[idx + len(before):]
    return "\n".join(lines), {"add": add, "del": dele, "added_lines": added_lines}


def _noncomment(lines):
    return [l for l in lines if l.strip() and not l.strip().startswith("#")]


def validate_bounded_edit(new_text: str, func: str, signature: str, meta: dict):
    """Enforce the bounded-edit contract: frozen signature, no new imports, <=LINE_BUDGET changed lines,
    single-function scope, parseable. Returns a list of violation strings (empty = OK)."""
    viol = []
    if signature not in new_text:
        viol.append("signature_changed")
    for l in meta["added_lines"]:
        if re.match(r"\s*(import|from)\s+\w", l):
            viol.append("import_added")
            break
    changed = len(_noncomment(list(meta["added_lines"]))) + meta["del"]
    if changed > LINE_BUDGET:
        viol.append("line_budget_exceeded")
    try:
        tree = ast.parse(new_text)
        if not any(isinstance(n, ast.FunctionDef) and n.name == func for n in tree.body):
            viol.append("function_missing")
        tops = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.Expr))]
        if tops:
            viol.append("out_of_function_edit")
    except SyntaxError:
        viol.append("syntax_error")
    return viol
