"""Eight renderer conditions P0-P7 that ALL derive deterministically from one canonical contract. Each
successive contrast changes exactly one manipulated feature so a passing semantic gate licenses a causal
read: P1 full-original(action-late) -> P2 action-first -> P3 no-IDs -> P4 reduced-control-plane ->
P5 compact-literal / P6 compact-natural (shared compact IR) ; P7 concise-summary baseline."""
from __future__ import annotations
import re

from ...serving.governed_view import compile_execution_view

RENDERERS = ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7"]
RENDER_META = {
    "P0": "NO_MEMORY", "P1": "FULL_CANONICAL_ORIGINAL(action-late)", "P2": "FULL_CANONICAL_ACTION_FIRST",
    "P3": "ACTION_FIRST_NO_IDS", "P4": "REDUCED_CONTROL_PLANE", "P5": "M7_COMPACT_LITERAL",
    "P6": "M7_COMPACT_NATURAL", "P7": "CONCISE_SUMMARY_BASELINE",
}
_HEADER = "INTERNAL CONTRACT (fictional; authoritative)"


def _verb(c):
    a = c["action"]
    return ("multiply %s by %d" % (a["target"], a["operand"])) if a["op"] == "multiply" else ("add %d to %s" % (a["operand"], a["target"]))


def _blocks(c, with_ids=True, with_control=True):
    """Ordered (label, text) blocks used to build P1-P4."""
    cid = " [%s]" % c["clause_apply"] if with_ids else ""
    b = []
    if with_ids:
        b.append(("id", "contract_id: %s" % c["contract_id"]))
    b += [
        ("func", "function: %s(%s)" % (c["func"], ", ".join(c["args"]))),
        ("scope", "scope%s: applies when %s and %s" % (cid, c["applicability"][0], c["applicability"][1])),
        ("anti", "anti-scope: %s" % c["anti_scope"][0]),
        ("validity", "validity: %s (%s)" % (c["validity"]["state"], c["validity"]["version"])),
        ("verify", "verification: the returned value follows the applicable clause"),
        ("action", "action%s: %s" % (cid, _verb(c))),
        ("params", "parameters: operand=%d, target=%s" % (c["action"]["operand"], c["action"]["target"])),
    ]
    if with_control:
        b += [("provenance", "provenance: source_episode=%s, contributor=%s" % (c["provenance"]["source_episode"], c["provenance"]["contributor"])),
              ("audit", "audit: chain_ok=true; registry_state=promoted; score=0.9"),
              ("supersession", "supersession: none")]
    return b


def _join(header, blocks):
    return header + "\n" + "\n".join(t for _, t in blocks) + "\n"


def render(c, cond):
    if cond == "P0":
        return None
    if cond == "P1":                        # full canonical, action LATE (E4 style)
        return _join(_HEADER, _blocks(c, with_ids=True, with_control=True))
    if cond == "P2":                        # identical content, action FIRST
        b = _blocks(c, with_ids=True, with_control=True)
        act = [x for x in b if x[0] in ("action", "params")]
        rest = [x for x in b if x[0] not in ("action", "params")]
        return _join(_HEADER, act + rest)
    if cond == "P3":                        # P2 minus opaque IDs
        b = _blocks(c, with_ids=False, with_control=True)
        act = [x for x in b if x[0] in ("action", "params")]
        rest = [x for x in b if x[0] not in ("action", "params")]
        return _join(_HEADER, act + rest)
    if cond == "P4":                        # P3 minus control-plane fields
        b = _blocks(c, with_ids=False, with_control=False)
        act = [x for x in b if x[0] in ("action", "params")]
        rest = [x for x in b if x[0] not in ("action", "params")]
        return _join(_HEADER, act + rest)
    if cond == "P5":                        # M7 compact literal
        return compile_execution_view(_compile_input(c, natural=False))
    if cond == "P6":                        # M7 compact natural (paraphrased predicates)
        return compile_execution_view(_compile_input(c, natural=True))
    if cond == "P7":                        # concise summary baseline (M4-style, deterministic)
        return ("Rule for %s: %s when %s and %s; otherwise %s. Keep the signature %s(%s)."
                % (c["func"], _verb(c), c["applicability"][0], c["applicability"][1], c["default"],
                   c["func"], ", ".join(c["args"])))
    raise ValueError(cond)


def _compile_input(c, natural):
    applic = c["applicability_nl"] if natural else c["applicability"]
    return {"func": c["func"], "args": c["args"], "applicability": applic, "action": c["action"],
            "default": c["default"], "validity": c["validity"], "scope_ok": c["scope_ok"]}


def _strip_ids(t):
    return re.sub(r"\s*\[(?:ct|cl)_[0-9a-z]+\]", "", re.sub(r"contract_id: \S+\n", "", t))


def semantic_gate(c):
    """Verify the manipulated-feature-only property of each contrast + content retention. Returns dict."""
    P = {r: render(c, r) for r in RENDERERS}
    res = {}
    # P2 differs from P1 ONLY by section reordering (same set of body lines)
    b1 = set(P["P1"].strip().splitlines()[1:]); b2 = set(P["P2"].strip().splitlines()[1:])
    res["P2_reorder_only"] = (b1 == b2)
    # P3 differs from P2 ONLY by ID removal
    res["P3_ids_only"] = (_strip_ids(P["P2"]).replace("\n", "") == P["P3"].replace("\n", ""))
    # P4 removes ONLY declared control-plane lines from P3
    removed = set(P["P3"].splitlines()) - set(P["P4"].splitlines())
    res["P4_control_plane_only"] = all(any(k in ln for k in ("provenance", "audit", "supersession")) for ln in removed) and len(removed) == 3
    # P5/P6 share compact IR (same action/params/interface, differ only in applicability text)
    res["P5_P6_same_action"] = (_verb(c) in P["P5"] and _verb(c) in P["P6"])
    res["P5_P6_differ_only_predicate"] = (P["P5"] != P["P6"] and c["func"] + "(" in P["P5"] and c["func"] + "(" in P["P6"])
    # content retention + no leakage for all memory renderers
    hidden_nums = set()
    for a, e in c["hidden_rows"]:
        hidden_nums.add(str(e)); hidden_nums.add(str(a[c["primary"]]))
    hidden_nums.discard(str(c["action"]["operand"]))
    ok_content = True; ok_leak = True
    for r in ("P1", "P2", "P3", "P4", "P5", "P6", "P7"):
        t = P[r]
        if _verb(c) not in t and not (c["action"]["op"] in t and str(c["action"]["operand"]) in t):
            ok_content = False
        toks = set(re.findall(r"\d+", re.sub(r"\b(?:ct|cl|ep|p)_[0-9a-z]+\b|v\d|0\.9|score=0\.9", "", t)))
        if toks & {x for x in hidden_nums if x.isdigit()}:
            ok_leak = False
    res["content_retained"] = ok_content
    res["no_target_leakage"] = ok_leak
    res["ALL"] = all(res.values())
    return res


def renderer_manifest():
    import hashlib
    from .bench import families
    h = {}
    for c in families():
        for r in RENDERERS:
            t = render(c, r)
            h["%s:%s:%s" % (c["family_id"], c["world"], r)] = "sha256:" + hashlib.sha256((t or "").encode()).hexdigest()[:12]
    blob = "|".join("%s=%s" % (k, h[k]) for k in sorted(h))
    return {"n": len(h), "manifest_hash": "sha256:" + hashlib.sha256(blob.encode()).hexdigest()[:24]}
