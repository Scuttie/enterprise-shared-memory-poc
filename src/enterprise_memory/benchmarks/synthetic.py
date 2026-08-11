"""Executable 16-family cross-user coding benchmark (handoff §9/§12). 4 domains x 4 families. Each
family: a small Python function to implement, whose correct output requires a PRIVATE org-specific rule
(unknowable from public knowledge) PLUS a target-specific computation, graded ONLY by executable hidden
pytest (no LLM judge). Four target variants per family: APPLICABLE / OUT_OF_SCOPE / EXPIRED /
IRRELEVANT. The memory (oracle contract / M6) states the reusable rule and contains NO target input
value, expected output, patch, hidden-test assertion, target id, or option label."""
from __future__ import annotations
import hashlib
import json

# (domain, func, rule_desc, apply_expr, base_input, factors) — apply_expr uses x and {f}; the public
# no-rule default is always `x`. The PRIVATE constant {f} is unknowable without the memory.
_FAMILIES = [
    ("internal_api", "retry_delay", "For tenant class {tag}, the retry delay is {f}x the Retry-After value; other tenants use Retry-After unchanged.",
     "{f} * x", [12, 15, 18, 20], [3, 4, 6, 7]),
    ("config", "resolve_timeout", "In project mode SAFE, USER config overrides ENV, then add the org grace of {f}; otherwise ENV wins with no grace.",
     "x + {f}", [20, 25, 30, 35], [3, 5, 7, 9]),
    ("schema", "migrate_value", "For schema version >= the pin, multiply the legacy field by the org scale {f}; below the pin, keep it unchanged.",
     "{f} * x", [8, 10, 14, 16], [3, 4, 5, 6]),
    ("cache", "cache_budget", "For a write-through cache in an active transaction, the budget is the number of keys times the org ttl-factor {f}; read-only caches use the key count.",
     "{f} * x", [9, 11, 13, 15], [3, 4, 6, 8]),
]


def _hash(o):
    return "sha256:" + hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:24]


def families():
    out = []
    for domain, func, rule_tmpl, apply_expr, inputs, factors in _FAMILIES:
        for idx in range(4):
            f = factors[idx]
            x = inputs[idx]
            tag = "ORCHID"
            rule_desc = rule_tmpl.format(tag=tag, f=f)
            fam_id = "fam.%s.%02d" % (domain, idx)
            expr_f = apply_expr.format(f=f)          # e.g. "6 * x" or "x + 7"
            # gold answers per variant (executable-verifiable)
            gold_applicable = eval(expr_f, {"x": x})  # requires the private factor
            gold_oos = x                              # scope off -> public default
            gold_expired = -1                        # expired -> must NOT use old rule; sentinel "migrate" = -1
            gold_irrelevant = x + 1                  # unrelated arithmetic
            stub = "def %s(x):\n    raise NotImplementedError\n" % func
            def hidden(fn, arg, expected):
                return "from mod import %s\n\ndef test_h():\n    assert %s(%d) == %d\n" % (fn, fn, arg, expected)
            def gp(fn, expr):
                return "def %s(x):\n    return %s\n" % (fn, expr)
            variants = {
                "APPLICABLE": {"facts": {"x": x, "scope_ok": True, "version": "v_ok"}, "gold": gold_applicable,
                               "hidden": hidden(func, x, gold_applicable), "gold_patch": gp(func, expr_f), "needs_rule": True},
                "OUT_OF_SCOPE": {"facts": {"x": x, "scope_ok": False, "version": "v_ok"}, "gold": gold_oos,
                                 "hidden": hidden(func, x, gold_oos), "gold_patch": gp(func, "x"), "needs_rule": False},
                "EXPIRED": {"facts": {"x": x, "scope_ok": True, "version": "v_expired"}, "gold": gold_expired,
                            "hidden": hidden(func, x, gold_expired), "gold_patch": gp(func, "-1"), "needs_rule": False},
                "IRRELEVANT": {"facts": {"x": x, "scope_ok": False, "version": "v_ok"}, "gold": gold_irrelevant,
                               "hidden": hidden(func, x, gold_irrelevant), "gold_patch": gp(func, "x + 1"), "needs_rule": False},
            }
            gold_patch = variants["APPLICABLE"]["gold_patch"]     # source bank = verified applicable gold
            oracle_contract = ("RULE: %s\nFUNCTION: %s(x)\nAPPLIES-WHEN: scope holds and version is current\n"
                               "DOES-NOT-APPLY-WHEN: out of scope (use the plain value) \nEXPIRES-WHEN: the version changed\n"
                               "VERIFY: the returned value matches the rule for the given x" % (rule_desc, func))
            out.append({"family_id": fam_id, "domain": domain, "func": func, "factor": f,
                        "rule_desc": rule_desc, "oracle_contract": oracle_contract, "stub": stub,
                        "gold_patch": gold_patch, "variants": variants,
                        "content_hash": _hash([fam_id, func, f, x, gold_applicable, gold_oos])})
    return out


def leakage_ok(fam):
    """The oracle contract/memory must not contain the target input value, gold answer, patch, or
    hidden-test assertion."""
    text = fam["oracle_contract"]
    for v in fam["variants"].values():
        if str(v["gold"]) not in ("0", "1", "2", "-1") and (" %d " % v["gold"]) in (" " + text + " "):
            return False, ("gold_in_memory", v["gold"])
        if str(v["facts"]["x"]) in text.split():
            return False, ("target_x_in_memory", v["facts"]["x"])
    if "assert" in text or "def " in text:
        return False, ("code_in_memory",)
    return True, None


def manifest():
    fams = families()
    return {"n_families": len(fams), "family_hashes": [f["content_hash"] for f in fams],
            "manifest_hash": _hash([f["content_hash"] for f in fams]),
            "by_domain": {d: sum(1 for f in fams if f["domain"] == d) for d in ("internal_api", "config", "schema", "cache")}}
