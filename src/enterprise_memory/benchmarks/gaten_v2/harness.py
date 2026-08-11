"""V2 bounded-edit harness (§4-§10): starter files, opaque-ID contracts, gold/default patches, hidden
tests, N1/N2 prompts, a tolerant unified-diff applicator with scope/line-budget/import/signature/
new-file guards, N1 exact grading, and N2 sandboxed execution. Restrictions are identical for M0/M6."""
from __future__ import annotations
import ast
import os
import re
import tempfile
import shutil

from ...serving import sandbox as SB

LINE_BUDGET = 12


class PatchError(Exception):
    pass


# ---------------------------------------------------------------- artifacts
def _sig(fam):
    return "def %s(%s):" % (fam["func"], ", ".join(fam["args"]))


def starter_file(fam):
    """One editable module, one marked frozen-signature function whose body is the only edit region."""
    return ("\"\"\"Bounded contract-application target (%s). Implement ONLY the marked function; keep its\n"
            "signature; no new files/imports/deps.\"\"\"\n\n"
            "%s\n"
            "    # BEGIN SOLUTION -- implement the org rule for this function (edit only below)\n"
            "    raise NotImplementedError\n"
            "    # END SOLUTION\n") % (fam["domain"], _sig(fam))


def _fill(fam, body_lines):
    return ("%s\n" % _sig(fam)) + "\n".join(body_lines) + "\n"


def gold_patch_text(fam, wlabel):
    return _fill(fam, fam["worlds"][wlabel]["gold_lines"])


def default_patch_text(fam):
    return _fill(fam, fam["default_lines"])


def hidden_test_text(fam, wlabel):
    lines = ["from mod import %s" % fam["func"], "", "def test_hidden():"]
    for args, expected in fam["worlds"][wlabel]["hidden"]:
        call = "%s(%s)" % (fam["func"], ", ".join(repr(args[a]) for a in fam["args"]))
        lines.append("    assert %s == %r" % (call, expected))
    return "\n".join(lines) + "\n"


def contract_text(fam, wlabel):
    """A reusable org contract with TWO opaque-ID clauses (one applicable, one plausible-inapplicable).
    Contains NO target value, expected output, patch, hidden-test assertion, target id, or world label."""
    w = fam["worlds"][wlabel]
    return (
        "INTERNAL ENGINEERING CONTRACT (fictional org; authoritative; overrides generic conventions)\n"
        "contract_id: %s\n"
        "function: %s(%s)\n"
        "clause %s [APPLICABLE-WHEN %s]:\n"
        "    action: %s\n"
        "clause %s [APPLICABLE-WHEN %s]:\n"
        "    action: %s\n"
        "default (no clause applies): return the primary value unchanged.\n"
        "verify: the returned value follows the applicable clause for the given inputs.\n"
        % (w["contract_id"], fam["func"], ", ".join(fam["args"]),
           w["clause_app"], w["scope"], w["op_desc"],
           w["clause_dist"], w["dscope"], w["dop_desc"]))


def _facts_block(fam):
    return ", ".join("%s=%r" % (a, fam["probe"][a]) for a in fam["args"])


# ---------------------------------------------------------------- prompts
_N2_RULES = ("Modify ONLY the function body between BEGIN SOLUTION and END SOLUTION. Keep the exact "
             "signature. Do NOT add files, imports, or dependencies; do not touch tests. Change at most "
             "%d lines. Return ONLY a unified diff (```diff fenced), no prose." % LINE_BUDGET)


def n2_prompt(fam, condition):
    mem = ("Authoritative internal contract:\n%s\n" % contract_text(fam, _cond_world(condition))
           if condition.startswith("M6") else "No internal contract is available.\n")
    return ("You are editing a fictional internal %s repository.\n\nFILE mod.py:\n```python\n%s```\n\n"
            "%sTask: implement `%s` so it follows the org's rule for every input. %s\n"
            % (fam["word"], starter_file(fam), mem, fam["func"], _N2_RULES))


def n1_prompt(fam, condition):
    mem = ("Authoritative internal contract:\n%s\n" % contract_text(fam, _cond_world(condition))
           if condition.startswith("M6") else "No internal contract is available.\n")
    return ("Fictional internal %s. Public target facts: %s\n\n%s\n"
            "Do NOT write code. Decide ONLY, as strict JSON:\n"
            '{"status":"APPLY|NO_APPLICABLE_CLAUSE","contract_id":"...","clause_id":"...",'
            '"operation":"multiply|add|scale|identity|select_user|select_env|select_project",'
            '"operand":<int or null>,"derived_value":<int>}\n'
            "operation is the applicable clause action; operand the org constant (null if none); "
            "derived_value is the result for THESE facts.\n"
            % (fam["word"], _facts_block(fam), mem))


def _cond_world(condition):
    # condition like "M6:W1" / "M0:W2"
    return condition.split(":")[1] if ":" in condition else "W1"


# ---------------------------------------------------------------- unified diff
def _find_block(text_lines, before):
    if not before:
        return -1
    n = len(before)
    strip = [b.rstrip() for b in before]
    for i in range(0, len(text_lines) - n + 1):
        if [t.rstrip() for t in text_lines[i:i + n]] == strip:
            return i
    return -1


def apply_unified_diff(original, diff):
    """Tolerant hunk applicator (ignores @@ line numbers; matches by context). Returns (new_text, meta)."""
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
            cur = [ln]  # diff with no @@ header
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


def check_and_build(fam, diff):
    """Apply a model diff to the starter, enforce bounded-edit rules. Returns (new_text, report)."""
    original = starter_file(fam)
    new_text, meta = apply_unified_diff(original, diff)
    viol = []
    # signature frozen
    if _sig(fam) not in new_text:
        viol.append("signature_changed")
    # no new imports
    for l in meta["added_lines"]:
        if re.match(r"\s*(import|from)\s+\w", l):
            viol.append("import_added"); break
    # line budget (changed non-comment lines)
    changed = len(_noncomment([l for l in meta["added_lines"]])) + meta["del"]
    if changed > LINE_BUDGET:
        viol.append("line_budget_exceeded")
    # must parse and define the function
    try:
        tree = ast.parse(new_text)
        if not any(isinstance(n, ast.FunctionDef) and n.name == fam["func"] for n in tree.body):
            viol.append("function_missing")
    except SyntaxError:
        viol.append("syntax_error")
    # edit confined to the function (only one top-level def; no new top-level statements)
    try:
        tree = ast.parse(new_text)
        tops = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.Expr))]
        if tops:
            viol.append("out_of_function_edit")
    except SyntaxError:
        pass
    return new_text, {"violations": viol, "changed_lines": changed}


def run_n2(fam, wlabel, diff, condition):
    """Apply the model's diff and run the world's hidden test in the sandbox."""
    res = {"family": fam["family_id"], "world": wlabel, "condition": condition,
           "passed": 0, "exec_ok": 0, "malformed": 0, "scope_violation": 0}
    try:
        new_text, rep = check_and_build(fam, diff)
    except PatchError as e:
        res["malformed"] = 1; res["reason"] = "patch:%s" % e; return res
    if rep["violations"]:
        res["scope_violation"] = 1; res["reason"] = ",".join(rep["violations"]); return res
    d = tempfile.mkdtemp()
    try:
        open(os.path.join(d, "mod.py"), "w", encoding="utf-8").write(starter_file(fam))
        open(os.path.join(d, "test_hidden.py"), "w", encoding="utf-8").write(hidden_test_text(fam, wlabel))
        r = SB.run_task(d, {"mod.py": new_text}, "test_hidden.py", timeout=20)
        res["passed"], res["exec_ok"] = int(r["passed"]), int(r["exec_ok"])
    finally:
        shutil.rmtree(d, ignore_errors=True)
    return res


# ---------------------------------------------------------------- N1 grading
def grade_n1(fam, wlabel, raw):
    """Exact grading. Returns per-dimension correctness + selection/full-instantiation booleans."""
    dec = fam["worlds"][wlabel]["decision"]
    def g(pat, cast=str):
        m = re.search(pat, raw or "")
        if not m:
            return None
        v = m.group(1)
        try:
            return cast(v)
        except Exception:
            return v
    status = g(r'"status"\s*:\s*"([A-Z_]+)"')
    clause = g(r'"clause_id"\s*:\s*"([^"]+)"')
    op = g(r'"operation"\s*:\s*"(\w+)"')
    operand = g(r'"operand"\s*:\s*(-?\d+)', int)
    derived = g(r'"derived_value"\s*:\s*(-?\d+)', int)
    d = {
        "status": status == dec["status"],
        "clause": clause == dec["clause_id"],
        "operation": op == dec["operation"],
        "operand": operand == dec["operand"],
        "derived": derived == dec["derived_value"],
    }
    selection = d["status"] and d["clause"] and d["operation"]
    full = selection and d["operand"] and d["derived"]
    return {"family": fam["family_id"], "world": wlabel, "dims": d,
            "selection_correct": int(selection), "full_correct": int(full)}
