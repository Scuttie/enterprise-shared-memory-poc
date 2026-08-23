"""REALBENCH-R3 §9/§10 — execution-view RENDERERS B0..B9. Each renderer deterministically projects the ONE
canonical object into an ordered list of priority segments (high->low). §10 token control assembles segments up
to an EXACT 220-token budget using ONE tokenizer, dropping lowest-priority whole segments (never mid-field) and
recording omitted fields + actual token count. The matched decoder (decoders.py) is always included (the bundle
is representation + decoder). Source-specific constants/names are redacted to placeholders — no renderer may emit
a marked source constant (§26 hard stop). B9 (raw trace) is diagnostic and eligible only under the §9 gates.
"""
from __future__ import annotations
import functools
import re

from experiments.actionable_memory_r3.decoders import DECODERS, GENERIC_DECODER

MAX_TOKENS = 220
TOKENIZER = "cl100k_base"


@functools.lru_cache(maxsize=1)
def _encoder():
    try:
        import tiktoken
        return ("tiktoken:cl100k_base", tiktoken.get_encoding("cl100k_base"))
    except Exception:
        return ("heuristic", None)


def count_tokens(text: str) -> int:
    name, enc = _encoder()
    if enc is not None:
        return len(enc.encode(text or ""))
    # deterministic fallback: subword-ish approximation (words + punctuation runs)
    return len(re.findall(r"\w+|[^\w\s]", text or ""))


def tokenizer_name() -> str:
    return _encoder()[0]


def _redact(text: str, source_constants) -> str:
    """Replace marked source identifiers (>=2 chars) with VAR and marked numeric literals with N, so no renderer
    can emit a source-specific name/constant (§26). Single-char names are left (too generic to leak an answer)."""
    if not text:
        return ""
    raw = [c.strip("'\"") for c in (source_constants or [])]
    names = sorted({c for c in raw if len(c) >= 2 and not _is_num(c)}, key=len, reverse=True)
    nums = sorted({c for c in raw if _is_num(c)}, key=len, reverse=True)
    out = text
    for b in names:
        out = re.sub(r"\b%s\b" % re.escape(b), "VAR", out)
    for b in nums:
        out = re.sub(r"(?<![\w.])%s(?![\w.])" % re.escape(b), "N", out)
    return out


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _lst(items, n, sep=", "):
    return sep.join(str(x) for x in (items or [])[:n])


def _get(c, k, default=""):
    v = c.get(k, default)
    return v if v not in (None,) else default


# ---- each renderer returns an ordered list of (label, line) high-priority-first --------------------------------
def _b0(c):
    return [("technique", "Technique: %s" % (_get(c, "positive_pattern") or _get(c, "data_transformation")
                                             or _get(c, "task_family"))),
            ("pitfall", "Pitfall: %s" % _get(c, "common_failure")),
            ("verify", "Verify: %s" % (_lst(_get(c, "verification_procedure", []), 1) or "check output type/shape"))]


def _b1(c):
    return [("apis", "Imports: %s | APIs: %s" % (_lst(_get(c, "required_imports", []), 4),
                                                 _lst(_get(c, "relevant_apis", []), 6))),
            ("contract", "In: %s  Out: %s" % (_get(c, "input_contract"), _get(c, "output_contract"))),
            ("pre", "Preconditions: %s" % _lst(_get(c, "preconditions", []), 3, "; ")),
            ("ops", "Ordered ops: %s" % _lst(_get(c, "ordered_operations", []), 5, " -> ")),
            ("misuse", "Common misuse: %s" % _get(c, "negative_pattern")),
            ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b2(c):
    pre = _get(c, "preconditions", []) or [_get(c, "applicability")]
    ops = _get(c, "ordered_operations", []) or [_get(c, "positive_pattern")]
    rows = [("row%d" % i, "IF %s -> %s" % (p, ops[min(i, len(ops) - 1)] if ops else "apply technique"))
            for i, p in enumerate(pre[:3])]
    return rows + [("forbidden", "NEVER: %s" % _get(c, "negative_pattern")),
                   ("edge", "Edge: %s" % _get(c, "common_failure")),
                   ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b3(c):
    return [("proc", "Procedure: %s" % _lst(_get(c, "ordered_operations", []), 6, " -> ")),
            ("cf", "Control flow: %s" % _get(c, "control_flow_pattern")),
            ("edge", "Edge cases: %s" % _get(c, "common_failure")),
            ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b4(c):
    return [("edit", "AST edit: %s" % _lst(_get(c, "generalized_ast_edit", []), 6, " ; ")),
            ("preserve", "Preserve: %s" % (_get(c, "output_contract") or "the required return variable/interface")),
            ("forbid", "Do not change: %s" % _get(c, "negative_pattern")),
            ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b5(c):
    return [("diff", "Diff template:\n%s" % _get(c, "generalized_diff_template")),
            ("region", "Editable region binds placeholders to target symbols; before->after must hold."),
            ("forbid", "Do not copy source identifiers/constants."),
            ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b6(c):
    props = c.get("executable_properties", []) or []
    return [("props", "Properties: %s" % _lst(props, 4, "; ")),
            ("pre", "Preconditions: %s" % _lst(_get(c, "preconditions", []), 2, "; ")),
            ("post", "Postconditions: %s" % _lst(_get(c, "postconditions", []), 2, "; ")),
            ("forbid", "Forbidden: %s" % _get(c, "negative_pattern")),
            ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b7(c):
    return [("pos", "Correct pattern: %s" % _get(c, "positive_pattern")),
            ("neg", "Incorrect pattern: %s" % _get(c, "negative_pattern")),
            ("disc", "Applies when: %s | Not when: %s" % (_get(c, "applicability"), _get(c, "non_applicability"))),
            ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b8(c):
    props = c.get("executable_properties", []) or []
    return [("appl", "Applies when: %s" % _get(c, "applicability")),
            ("api", "APIs: %s" % _lst(_get(c, "relevant_apis", []), 5)),
            ("edit", "Edit: %s" % _lst(_get(c, "generalized_ast_edit", []), 2, " ; ")),
            ("props", "Properties: %s" % _lst(props, 2, "; ")),
            ("neg", "Avoid: %s" % _get(c, "negative_pattern")),
            ("verify", "Verify: %s" % _lst(_get(c, "verification_procedure", []), 1))]


def _b9(c):
    trace = (c.get("evidence", {}) or {}).get("solution_code", "")
    return [("trace", "Worked example (redacted):\n%s" % trace),
            ("verify", "Re-derive for the target; do not copy identifiers/constants.")]


RENDERERS = {"B0": _b0, "B1": _b1, "B2": _b2, "B3": _b3, "B4": _b4, "B5": _b5, "B6": _b6, "B7": _b7,
             "B8": _b8, "B9": _b9}
BUNDLE_ORDER = ["B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]


def render(bundle: str, canon: dict, *, decoder: str = None, max_tokens: int = MAX_TOKENS):
    """Assemble the execution view for `bundle` from the canonical object, budget-fit to max_tokens.
    Returns {view, tokens, tokenizer, omitted, decoder_kind}. `decoder` overrides the matched decoder text
    (used by the §13 ablation with GENERIC_DECODER)."""
    src_const = canon.get("source_constants", [])
    segs = [(lbl, _redact(line, src_const)) for lbl, line in RENDERERS[bundle](canon)]
    dec_text = decoder if decoder is not None else DECODERS[bundle]
    dec_line = "Decoder: " + dec_text
    # decoder is essential and always included; then add segments high->low until budget
    kept, omitted = [], []
    budget = max_tokens - count_tokens(dec_line) - 1
    used = 0
    for lbl, line in segs:
        t = count_tokens(line) + 1
        if used + t <= budget or not kept:   # always keep at least the top segment
            kept.append(line); used += t
        else:
            omitted.append(lbl)
    view = "\n".join(kept + [dec_line])
    return {"view": view, "tokens": count_tokens(view), "tokenizer": tokenizer_name(),
            "omitted": omitted, "decoder_kind": "matched" if decoder is None else "generic",
            "bundle": bundle}
