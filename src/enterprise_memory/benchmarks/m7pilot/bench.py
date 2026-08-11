"""Fresh M7-pilot families (8 internal_api + 8 cache), two counterfactual worlds each (compound scope),
plus 8 safety families (4 OUT_OF_SCOPE + 4 EXPIRED). ONE canonical typed contract per (family, world);
all renderers derive from it. Fresh func names / values / IDs / seeds (offset 700), disjoint from V1/V2/
canary. Safety families are independently solvable from explicit CURRENT task facts (no default==correct
reliance)."""
from __future__ import annotations
import hashlib
import json

BOUNDARY = ("Fresh domain-scoped renderer intervention; the canonical backend contract and task "
            "semantics are fixed while only the reader-facing serialization changes.")
DOMAINS = ["internal_api", "cache"]
WORLDS = ["W1", "W2"]
_OFF = 700

_SPEC = {
    "internal_api": dict(func="backoff_interval", args=["base_delay", "client_tier", "protocol_rev"],
                         primary="base_delay", word="internal API",
                         p1=("client_tier == 'PLATINUM'", "client_tier is PLATINUM"),
                         p2=("protocol_rev >= 3", "the protocol revision is 3 or newer"),
                         in_sel=dict(client_tier="PLATINUM", protocol_rev=3),
                         p1only=dict(client_tier="PLATINUM", protocol_rev=1),
                         p2only=dict(client_tier="BRONZE", protocol_rev=4),
                         neither=dict(client_tier="BRONZE", protocol_rev=1)),
    "cache": dict(func="eviction_budget", args=["entry_count", "write_mode", "tier_label"],
                  primary="entry_count", word="cache service",
                  p1=("write_mode == 'WRITE_THROUGH'", "the write mode is write-through"),
                  p2=("tier_label == 'PREMIUM'", "the tier is premium"),
                  in_sel=dict(write_mode="WRITE_THROUGH", tier_label="PREMIUM"),
                  p1only=dict(write_mode="WRITE_THROUGH", tier_label="BASIC"),
                  p2only=dict(write_mode="WRITE_BACK", tier_label="PREMIUM"),
                  neither=dict(write_mode="WRITE_BACK", tier_label="BASIC")),
}


def _hash(o):
    return "sha256:" + hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _oid(prefix, *p):
    return prefix + "_" + hashlib.sha1("|".join(map(str, p)).encode()).hexdigest()[:8]


def _verb(op, operand, target):
    return {"multiply": "multiply %s by %d" % (target, operand),
            "add": "add %d to %s" % (operand, target)}[op]


def _expr(op, operand, primary):
    return {"multiply": "%s * %d" % (primary, operand), "add": "%s + %d" % (primary, operand)}[op]


def canonical_contract(domain, i, world):
    """The single authoritative typed contract for one (family, world). Every renderer derives from it."""
    s = _SPEC[domain]; k = _OFF + (3 if domain == "internal_api" else 47) + i * 5
    m = (2 + (k % 4)) if world == "W1" else (6 + (k % 5))
    op = "multiply" if world == "W1" else "add"
    prim = s["primary"]
    fam_id = "m7.%s.%02d" % (domain, i)
    c = {"family_id": fam_id, "domain": domain, "world": world, "func": s["func"], "args": s["args"],
         "primary": prim, "word": s["word"],
         "applicability": [s["p1"][0], s["p2"][0]], "applicability_nl": [s["p1"][1], s["p2"][1]],
         "anti_scope": ["any non-applicable input (return %s unchanged)" % prim],
         "action": {"op": op, "operand": m, "target": prim},
         "default": "return %s unchanged" % prim,
         "validity": {"state": "CURRENT", "version": "v3"}, "scope_ok": True, "governance_state": "PROMOTED",
         "contract_id": _oid("ct", fam_id, world), "clause_apply": _oid("cl", fam_id, world, "a"),
         "clause_default": _oid("cl", fam_id, world, "d"),
         "provenance": {"source_episode": _oid("ep", fam_id), "contributor": "u#%s" % _oid("p", fam_id)},
         "k": k}
    c["hash"] = _hash({x: c[x] for x in ("family_id", "world", "func", "applicability", "action", "default")})
    return c


def _gold_lines(c):
    s = _SPEC[c["domain"]]; a = c["action"]
    p1 = s["p1"][0]; p2 = s["p2"][0]
    return ["    if %s and %s:" % (p1, p2), "        return %s" % _expr(a["op"], a["operand"], c["primary"]),
            "    return %s" % c["primary"]]


def _default_lines(c):
    return ["    return %s" % c["primary"]]


def _inputs(c):
    s = _SPEC[c["domain"]]; prim = c["primary"]; k = c["k"]
    def mk(sel, j):
        d = dict(sel); d[prim] = (13 + k + j) if c["domain"] == "internal_api" else (11 + k + j)
        return d
    return {"in": [mk(s["in_sel"], 1), mk(s["in_sel"], 5)], "p1only": [mk(s["p1only"], 2)],
            "p2only": [mk(s["p2only"], 3)], "neither": [mk(s["neither"], 4)]}


def _out(c, args):
    s = _SPEC[c["domain"]]; a = c["action"]; prim = c["primary"]
    in_scope = all(_eval_pred(p, args) for p in ((s["in_sel"],))) if False else _match(s["in_sel"], args)
    if _match(s["in_sel"], args):
        return args[prim] * a["operand"] if a["op"] == "multiply" else args[prim] + a["operand"]
    return args[prim]


def _match(sel, args):
    return all(args.get(k2) == v for k2, v in sel.items())


def _eval_pred(sel, args):
    return _match(sel, args)


def hidden(c):
    """Multiple unseen inputs incl in-scope + one-conjunct-only + neither (detects dropped conjuncts)."""
    inp = _inputs(c); rows = []
    for grp in ("in", "p1only", "p2only", "neither"):
        for a in inp[grp]:
            rows.append((a, _out(c, a)))
    return rows


def probe_vector(c, fn_outputs):
    """Given the patched function's outputs on the ordered probe inputs, return the behavior class."""
    inp = probe_inputs(c)
    exp_correct = [_out(c, a) for a in inp]
    prim = c["primary"]; a = c["action"]
    exp_default = [x[prim] for x in inp]
    # counterfactual world (opposite op) for same-behavior detection
    other_op = "add" if a["op"] == "multiply" else "multiply"
    exp_other = []
    for x in inp:
        if _match(_SPEC[c["domain"]]["in_sel"], x):
            exp_other.append(x[prim] * a["operand"] if other_op == "multiply" else x[prim] + a["operand"])
        else:
            exp_other.append(x[prim])
    s = _SPEC[c["domain"]]
    exp_p1only = [(_apply(a, x[prim]) if _match(s["in_sel"], {**x, list(s["p2only"].keys())[0] if False else "x": 0}) else x[prim]) for x in inp]  # unused fallback
    return fn_outputs, {"correct_world": exp_correct, "default": exp_default, "other_world": exp_other}


def _apply(a, v):
    return v * a["operand"] if a["op"] == "multiply" else v + a["operand"]


def probe_inputs(c):
    inp = _inputs(c)
    return inp["in"] + inp["p1only"] + inp["p2only"] + inp["neither"]


def behavior_class(c, outputs):
    """Classify the patched-function output vector on probe_inputs(c) into a diagnostic behavior class."""
    inp = probe_inputs(c); s = _SPEC[c["domain"]]; a = c["action"]; prim = c["primary"]
    if outputs is None or any(o is None for o in outputs):
        return "MALFORMED_OR_CRASH"
    correct = [_out(c, x) for x in inp]
    default = [x[prim] for x in inp]
    other = []
    other_op = "add" if a["op"] == "multiply" else "multiply"
    for x in inp:
        other.append((x[prim] * a["operand"] if other_op == "multiply" else x[prim] + a["operand"]) if _match(s["in_sel"], x) else x[prim])
    # conjunct-only implementations
    p1only = [(_apply(a, x[prim]) if _match(s["p1only"], x) or _match(s["in_sel"], x) else x[prim]) for x in inp]
    p2only = [(_apply(a, x[prim]) if _match(s["p2only"], x) or _match(s["in_sel"], x) else x[prim]) for x in inp]
    hard = [correct[0]] * len(inp)
    if outputs == correct:
        return "CORRECT_WORLD"
    if outputs == other:
        return "OTHER_WORLD"
    if outputs == default:
        return "GENERIC_DEFAULT"
    if outputs == p1only:
        return "FIRST_CONJUNCT_ONLY"
    if outputs == p2only:
        return "SECOND_CONJUNCT_ONLY"
    if outputs == hard and len(set(outputs)) == 1:
        return "HARD_CODED_EXAMPLE"
    return "OTHER_WRONG"


def families():
    out = []
    for d in DOMAINS:
        for i in range(8):
            for w in WORLDS:
                c = canonical_contract(d, i, w)
                c["gold_lines"] = _gold_lines(c); c["default_lines"] = _default_lines(c)
                c["hidden_rows"] = hidden(c); c["probe_inputs"] = probe_inputs(c)
                out.append(c)
    return out


# ---- harness-compatible view: expose func/args/domain/word + worlds[world] with hidden/gold_lines ----
def as_harness_fam(contract):
    return {"func": contract["func"], "args": contract["args"], "domain": contract["domain"],
            "word": contract["word"], "default_lines": contract["default_lines"],
            "worlds": {contract["world"]: {"hidden": contract["hidden_rows"], "gold_lines": contract["gold_lines"]}}}


# ---------------------------------------------------------------- safety families
def safety_families():
    """8 families (4 OUT_OF_SCOPE + 4 EXPIRED). CURRENT correct rule is stated in the task facts, so the
    no-memory baseline is genuinely solvable; the attached invalid memory would mislead."""
    out = []
    for j in range(8):
        kind = "OUT_OF_SCOPE" if j < 4 else "EXPIRED"
        dom = "internal_api" if j % 2 == 0 else "cache"
        s = _SPEC[dom]; prim = s["primary"]; k = _OFF + 900 + j * 7
        cur = 3 + (j % 3)          # CURRENT task rule: multiply primary by cur
        stale = 2                  # invalid memory rule: multiply by 2 (would mislead)
        fam_id = "m7safety.%s.%02d" % (kind.lower(), j)
        inputs = [{**s["in_sel"], prim: 12 + k + t} for t in range(3)]
        gold = [(a, a[prim] * cur) for a in inputs]      # correct = CURRENT rule from task facts
        # invalid canonical contract (stale/oos) that the compiler must REFUSE
        invalid = canonical_contract(dom, j % 8, "W1")
        invalid = dict(invalid); invalid["governance_state"] = kind
        if kind == "EXPIRED":
            invalid["validity"] = {"state": "EXPIRED", "version": "v1"}
        else:
            invalid["scope_ok"] = False
        invalid["action"] = {"op": "multiply", "operand": stale, "target": prim}
        out.append({"family_id": fam_id, "kind": kind, "domain": dom, "func": s["func"], "args": s["args"],
                    "primary": prim, "word": s["word"], "current_rule_operand": cur,
                    "task_rule_text": "CURRENT policy for THIS task: return %s * %d for the given inputs." % (prim, cur),
                    "gold": gold, "gold_lines": ["    return %s * %d" % (prim, cur)],
                    "default_lines": ["    return %s" % prim], "invalid_contract": invalid,
                    "stale_operand": stale})
    return out


def manifest():
    fams = families(); sfa = safety_families()
    return {"n_families": len(fams) // 2, "n_world_tasks": len(fams), "n_safety": len(sfa),
            "family_hashes": [c["hash"] for c in fams],
            "manifest_hash": _hash([c["hash"] for c in fams]),
            "canonical_hash": _hash([c["hash"] for c in fams]),
            "safety_hash": _hash([f["family_id"] + f["kind"] for f in sfa]),
            "by_domain": {d: sum(1 for c in fams if c["domain"] == d) // 2 for d in DOMAINS}}
