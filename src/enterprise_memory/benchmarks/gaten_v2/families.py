"""V2 family generator (§3-§10). Four domains, two counterfactual contract worlds per family. A family
carries: an editable starter file with ONE marked frozen-signature function, two worlds (each = a
2-clause opaque-ID contract + gold/hidden tests + an N1 decision), a default no-memory patch, and an N1
probe target. Splits use disjoint numeric pools + disjoint per-split surface wording, so no family ID,
value, constant, hidden test, seed, or exact task wording overlaps across splits."""
from __future__ import annotations
import hashlib
import json

DOMAINS = ["internal_api", "config", "schema", "cache"]
SPLITS = {"unit": 2, "calibration": 3, "confirmation": 4, "canary": 4}   # families per domain
_OFF = {"unit": 0, "calibration": 100, "confirmation": 200, "canary": 300}  # disjoint numeric base
# per-split surface wording so exact NL task wording differs across splits (semantics identical)
_WORD = {"unit": "micro-service", "calibration": "internal API", "confirmation": "backend service", "canary": "platform service"}

# domain schema: func, ordered args, primary numeric arg, selector arg + applicable/distractor values,
# selector kind (eq | ge), and the (W1, W2) applicable-clause operation pair.
_DSPEC = {
    "internal_api": dict(func="compute_retry_delay", args=["retry_after", "tenant_class", "api_version"],
                         primary="retry_after", selector="tenant_class", kind="eq", applic="ORCHID",
                         distract="FALCON", ops=("multiply", "add")),
    "config": dict(func="resolve_config", args=["env_val", "user_val", "project_val", "mode"],
                   primary="env_val", selector="mode", kind="eq", applic="SAFE", distract="FAST",
                   ops=("select_user", "select_env")),
    "schema": dict(func="normalize_amount", args=["amount", "schema_version"],
                   primary="amount", selector="schema_version", kind="ge", applic=None, distract=None,
                   ops=("scale", "scale")),
    "cache": dict(func="cache_ttl", args=["num_keys", "txn_active"],
                  primary="num_keys", selector="txn_active", kind="eq", applic=True, distract=False,
                  ops=("multiply", "add")),
}


def _oid(prefix, *parts):
    return prefix + "_" + hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8]


def _apply(op, operand, args, primary_name):
    p = args[primary_name]
    if op == "multiply":
        return p * operand
    if op == "add":
        return p + operand
    if op == "scale":
        return p * operand
    if op == "identity":
        return p
    if op == "select_user":
        return args["user_val"]
    if op == "select_env":
        return args["env_val"]
    if op == "select_project":
        return args["project_val"]
    raise ValueError(op)


def _sel_applies(kind, argval, applic, pin=None):
    if kind == "eq":
        return argval == applic
    if kind == "ge":
        return argval >= pin
    raise ValueError(kind)


def _world_clauses(domain, k):
    """Return (worldW1, worldW2) each: {applic:(op,operand,scope_txt,nonapplic_txt), distract:(...)}.
    A/B differ in exactly ONE convention: the applicable clause's operation/operand. Distractor identical."""
    s = _DSPEC[domain]
    if domain == "internal_api":
        m = 3 + (k % 4); a = 7 + (k % 5); d = 2 + (k % 3)
        app1 = ("multiply", m); app2 = ("add", a); dist = ("add", d)
        return (dict(applic=app1, distract=dist), dict(applic=app2, distract=dist),
                dict(scope="tenant_class == 'ORCHID'", nonapplic="any other tenant class (return retry_after unchanged)",
                     dscope="tenant_class == 'FALCON'", dop_desc="add %d to retry_after" % d))
    if domain == "cache":
        m = 3 + (k % 4); a = 8 + (k % 5); d = 1 + (k % 3)
        app1 = ("multiply", m); app2 = ("add", a); dist = ("add", d)
        return (dict(applic=app1, distract=dist), dict(applic=app2, distract=dist),
                dict(scope="txn_active is True (write-through, active transaction)",
                     nonapplic="a read-only cache (return num_keys unchanged)",
                     dscope="txn_active is False", dop_desc="add %d to num_keys" % d))
    if domain == "schema":
        app1 = ("scale", 100); app2 = ("scale", 10); dist = ("identity", 0)  # both worlds non-identity
        return (dict(applic=app1, distract=dist), dict(applic=app2, distract=dist),
                dict(scope="schema_version >= the pinned version",
                     nonapplic="a schema_version below the pin (return amount unchanged)",
                     dscope="schema_version < the pin", dop_desc="return amount unchanged"))
    if domain == "config":
        app1 = ("select_user", None); app2 = ("select_env", None); dist = ("select_project", None)
        return (dict(applic=app1, distract=dist), dict(applic=app2, distract=dist),
                dict(scope="mode == 'SAFE'", nonapplic="any other mode (return the project value)",
                     dscope="mode == 'FAST'", dop_desc="return the project value"))
    raise ValueError(domain)


def _op_desc(op, operand):
    return {"multiply": "multiply the value by %s" % operand, "add": "add %s to the value" % operand,
            "scale": "multiply the value by %s" % operand, "identity": "return the value unchanged",
            "select_user": "return the user-config value", "select_env": "return the environment-config value",
            "select_project": "return the project-config value"}[op]


def _gold_body(domain, world, pin):
    """Full function body (list of code lines, indented 4) realising BOTH clauses + default."""
    s = _DSPEC[domain]; app_op, app_operand = world["applic"]; d_op, d_operand = world["distract"]
    L = []
    if domain == "internal_api":
        L = ["    if tenant_class == 'ORCHID':", "        return %s" % _expr("retry_after", app_op, app_operand),
             "    if tenant_class == 'FALCON':", "        return %s" % _expr("retry_after", d_op, d_operand),
             "    return retry_after"]
    elif domain == "cache":
        L = ["    if txn_active:", "        return %s" % _expr("num_keys", app_op, app_operand),
             "    return %s" % _expr("num_keys", d_op, d_operand)]
    elif domain == "schema":
        L = ["    if schema_version >= %d:" % pin, "        return %s" % _expr("amount", app_op, app_operand),
             "    return amount"]
    elif domain == "config":
        L = ["    if mode == 'SAFE':", "        return %s" % _sel_expr(app_op),
             "    if mode == 'FAST':", "        return %s" % _sel_expr(d_op),
             "    return env_val"]
    return L


def _expr(primary, op, operand):
    if op in ("multiply", "scale"):
        return "%s * %d" % (primary, operand)
    if op == "add":
        return "%s + %d" % (primary, operand)
    if op == "identity":
        return primary
    raise ValueError(op)


def _sel_expr(op):
    return {"select_user": "user_val", "select_env": "env_val", "select_project": "project_val"}[op]


def _default_body(domain):
    """The no-memory baseline: apply no org rule -> return the primary value unchanged (config: env)."""
    return {"internal_api": ["    return retry_after"], "cache": ["    return num_keys"],
            "schema": ["    return amount"], "config": ["    return env_val"]}[domain]


def _inputs(domain, k, pin):
    """Deterministic probe (N1) + hidden (N2) input dicts. Hidden inputs are disjoint from the probe."""
    s = _DSPEC[domain]
    if domain == "internal_api":
        probe = dict(retry_after=12 + k, tenant_class="ORCHID", api_version=2)
        hidden = [dict(retry_after=21 + 2 * k, tenant_class="ORCHID", api_version=2),
                  dict(retry_after=17 + k, tenant_class="ORCHID", api_version=3),
                  dict(retry_after=9 + k, tenant_class="FALCON", api_version=2),
                  dict(retry_after=15 + 3 * k, tenant_class="RAVEN", api_version=2)]
    elif domain == "cache":
        probe = dict(num_keys=11 + k, txn_active=True)
        hidden = [dict(num_keys=19 + 2 * k, txn_active=True), dict(num_keys=13 + k, txn_active=True),
                  dict(num_keys=8 + k, txn_active=False)]
    elif domain == "schema":
        probe = dict(amount=7 + k, schema_version=pin)
        hidden = [dict(amount=6 + 2 * k, schema_version=pin), dict(amount=9 + k, schema_version=pin + 2),
                  dict(amount=5 + k, schema_version=pin - 1)]
    elif domain == "config":
        base = 20 + k
        probe = dict(env_val=base, user_val=base + 5, project_val=base + 9, mode="SAFE")
        hidden = [dict(env_val=base + 1, user_val=base + 6, project_val=base + 11, mode="SAFE"),
                  dict(env_val=base + 2, user_val=base + 7, project_val=base + 13, mode="FAST"),
                  dict(env_val=base + 3, user_val=base + 8, project_val=base + 15, mode="AUDIT")]
    return probe, hidden


def _compute(domain, world, args, pin):
    """World-correct output for an input dict (used to build gold expectations + N1 derived value)."""
    s = _DSPEC[domain]; app_op, app_operand = world["applic"]; d_op, d_operand = world["distract"]
    if domain == "schema":
        if args["schema_version"] >= pin:
            return _apply(app_op, app_operand, args, s["primary"])
        return args["amount"]
    if domain == "config":
        if args["mode"] == "SAFE":
            return _apply(app_op, app_operand, args, s["primary"])
        if args["mode"] == "FAST":
            return _apply(d_op, d_operand, args, s["primary"])
        return args["env_val"]
    # eq-selector arithmetic domains (internal_api, cache)
    if _sel_applies("eq", args[s["selector"]], s["applic"]):
        return _apply(app_op, app_operand, args, s["primary"])
    if _sel_applies("eq", args[s["selector"]], s["distract"]):
        return _apply(d_op, d_operand, args, s["primary"])
    return args[s["primary"]]


def _family(split, domain, i):
    s = _DSPEC[domain]; k = _OFF[split] + domain_salt(domain) + i
    pin = 5 + (k % 4)
    w1, w2, desc = _world_clauses(domain, k)
    probe, hidden = _inputs(domain, k, pin)
    fam_id = "gv2.%s.%s.%02d" % (split, domain, i)
    worlds = {}
    for wlabel, world in (("W1", w1), ("W2", w2)):
        app_op, app_operand = world["applic"]
        cid = _oid("ct", fam_id, wlabel)
        cl_app = _oid("cl", fam_id, wlabel, "app"); cl_dist = _oid("cl", fam_id, wlabel, "dist")
        # correct N1 decision on the probe target
        derived = _compute(domain, world, probe, pin)
        operand_out = None if app_operand in (None, 0) else app_operand
        decision = {"status": "APPLY", "contract_id": cid, "clause_id": cl_app,
                    "operation": app_op, "operand": operand_out, "derived_value": derived}
        gold_lines = _gold_body(domain, world, pin)
        hid = [(h, _compute(domain, world, h, pin)) for h in hidden]
        worlds[wlabel] = {"contract_id": cid, "clause_app": cl_app, "clause_dist": cl_dist,
                          "applic_op": app_op, "applic_operand": app_operand, "pin": pin,
                          "scope": desc["scope"], "nonapplic": desc["nonapplic"], "dscope": desc["dscope"],
                          "dop_desc": desc["dop_desc"], "gold_lines": gold_lines, "hidden": hid,
                          "decision": decision, "op_desc": _op_desc(app_op, app_operand)}
    return {"family_id": fam_id, "split": split, "domain": domain, "func": s["func"], "args": s["args"],
            "primary": s["primary"], "selector": s["selector"], "kind": s["kind"], "pin": pin,
            "word": _WORD[split], "probe": probe, "default_lines": _default_body(domain),
            "worlds": worlds,
            "content_hash": _hash([fam_id, s["func"], pin, worlds["W1"]["hidden"], worlds["W2"]["hidden"]])}


def domain_salt(domain):
    return {"internal_api": 7, "config": 19, "schema": 31, "cache": 43}[domain]


def _hash(o):
    return "sha256:" + hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:24]


def families(split):
    assert split in SPLITS, split
    out = []
    for domain in DOMAINS:
        for i in range(SPLITS[split]):
            out.append(_family(split, domain, i))
    return out


def split_manifest(split):
    fams = families(split)
    return {"split": split, "n_families": len(fams), "family_ids": [f["family_id"] for f in fams],
            "family_hashes": [f["content_hash"] for f in fams],
            "manifest_hash": _hash([f["content_hash"] for f in fams]),
            "by_domain": {d: sum(1 for f in fams if f["domain"] == d) for d in DOMAINS}}
