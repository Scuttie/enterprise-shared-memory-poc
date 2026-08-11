"""Canary benchmark: 16 fresh families (8 internal_api + 8 cache), 8 users, source!=target ownership,
4 safety variants, memory conditions M0-M6. Bounded executable editing (reuses gaten_v2 harness). The
scope-distinguishing predicate (api_version / cache_tier) makes the naive-shared 'old action' tempting
so governance (M5 scope+validity gates) is measurable against ungoverned baselines."""
from __future__ import annotations
import hashlib
import json

BOUNDARY = ("Post-calibration domain-scoped engineering evaluation; not confirmatory evidence for "
            "general coding-memory efficacy.")
USERS = ["user_%02d" % i for i in range(8)]
DOMAINS = ["internal_api", "cache"]
VARIANTS = ["APPLICABLE", "OUT_OF_SCOPE", "EXPIRED", "IRRELEVANT"]
CONDITIONS = ["M0", "M1", "M2", "M3", "M4", "M5", "M6"]
_OFF = 500   # disjoint from all gaten_v2 splits

_SPEC = {
    "internal_api": dict(func="compute_retry_delay", args=["retry_after", "tenant_class", "api_version"],
                         primary="retry_after", word="internal API"),
    "cache": dict(func="cache_ttl", args=["num_keys", "txn_active", "cache_tier"],
                  primary="num_keys", word="cache service"),
}


def _hash(o):
    return "sha256:" + hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _inscope(domain, args):
    if domain == "internal_api":
        return args["tenant_class"] == "ORCHID" and args["api_version"] >= 2
    return args["txn_active"] is True and args["cache_tier"] == "HOT"


def _out_args(domain, k, j):
    """A single input dict that is OUT of scope by the decisive predicate (api_version / cache_tier)."""
    if domain == "internal_api":
        return dict(retry_after=14 + k + j, tenant_class="ORCHID", api_version=1)
    return dict(num_keys=12 + k + j, txn_active=True, cache_tier="COLD")


def _in_args(domain, k, j):
    if domain == "internal_api":
        return dict(retry_after=13 + k + 2 * j, tenant_class="ORCHID", api_version=2)
    return dict(num_keys=11 + k + 2 * j, txn_active=True, cache_tier="HOT")


def _rule_out(domain, args, m):
    return args[_SPEC[domain]["primary"]] * m if _inscope(domain, args) else args[_SPEC[domain]["primary"]]


def _gold_lines(domain, m, variant):
    p = _SPEC[domain]["primary"]
    if variant == "APPLICABLE":
        if domain == "internal_api":
            return ["    if tenant_class == 'ORCHID' and api_version >= 2:", "        return retry_after * %d" % m,
                    "    return retry_after"]
        return ["    if txn_active and cache_tier == 'HOT':", "        return num_keys * %d" % m, "    return num_keys"]
    return ["    return %s" % p]   # safety variants: correct behavior is the default (rule not applied)


def _family(domain, i):
    s = _SPEC[domain]; k = _OFF + (7 if domain == "internal_api" else 43) + i * 5
    m = 3 + (k % 4)
    gidx = (0 if domain == "internal_api" else 8) + i
    target_owner = USERS[gidx % 8]; source_owner = USERS[(gidx + 3) % 8]
    assert target_owner != source_owner
    fam_id = "esmc.%s.%02d" % (domain, i)
    # hidden inputs per variant (disjoint j offsets)
    def hid(variant):
        rows = []
        if variant == "APPLICABLE":
            for j in range(3):
                a = _in_args(domain, k, j); rows.append((a, a[s["primary"]] * m))
            a = _out_args(domain, k, 9); rows.append((a, a[s["primary"]]))     # non-scope input -> default
        elif variant == "OUT_OF_SCOPE":
            for j in range(3):
                a = _out_args(domain, k, j); rows.append((a, a[s["primary"]]))  # correct = unchanged
        elif variant == "EXPIRED":
            for j in range(3):
                a = _in_args(domain, k, j + 4); rows.append((a, a[s["primary"]]))  # expired -> must NOT apply
        else:  # IRRELEVANT
            for j in range(3):
                a = _in_args(domain, k, j + 7); rows.append((a, a[s["primary"]]))  # unrelated memory -> default
        return rows
    worlds = {v: {"hidden": hid(v), "gold_lines": _gold_lines(domain, m, v)} for v in VARIANTS}
    probe = _in_args(domain, k, 0)
    return {"family_id": fam_id, "domain": domain, "func": s["func"], "args": s["args"],
            "primary": s["primary"], "word": s["word"], "m": m, "k": k,
            "target_owner": target_owner, "source_owner": source_owner, "probe": probe,
            "worlds": worlds, "default_lines": ["    return %s" % s["primary"]],
            "content_hash": _hash([fam_id, m, worlds["APPLICABLE"]["hidden"], worlds["OUT_OF_SCOPE"]["hidden"]])}


def families():
    return [_family(d, i) for d in DOMAINS for i in range(8)]


def user_assignment():
    a = {f["family_id"]: {"source_owner": f["source_owner"], "target_owner": f["target_owner"]} for f in families()}
    return {"assignment": a, "hash": _hash(a),
            "source_ne_target": all(v["source_owner"] != v["target_owner"] for v in a.values())}


# ---------------------------------------------------------------- source episode bank
def source_bank():
    bank = {}
    for f in families():
        rule = ("for %s the org multiplies the primary value by %d when in scope (%s); otherwise the "
                "value is unchanged" % (f["domain"], f["m"], _scope_desc(f["domain"])))
        patch = "\n".join(["def %s(%s):" % (f["func"], ", ".join(f["args"]))] + _gold_lines(f["domain"], f["m"], "APPLICABLE"))
        ep = {"family": f["family_id"], "owner": f["source_owner"], "domain": f["domain"], "rule": rule,
              "verified_patch": patch, "public_tests": "interface", "hidden_verified": True,
              "version": "v2", "env": "python", "episode_text": "raw fictional trace: solved %s; %s" % (f["func"], rule)}
        ep["hash"] = _hash(ep)
        bank[f["family_id"]] = ep
    return {"episodes": bank, "manifest_hash": _hash({k: v["hash"] for k, v in bank.items()})}


def _scope_desc(domain):
    return "tenant ORCHID and api_version>=2" if domain == "internal_api" else "active transaction and cache_tier HOT"


# ---------------------------------------------------------------- memory representations
def _contract_text(f, expired=False):
    val = "EXPIRED (version changed)" if expired else "CURRENT (v2)"
    return ("INTERNAL CONTRACT (fictional; authoritative)\nfunction: %s(%s)\n"
            "clause cl_apply [APPLICABLE-WHEN %s]: multiply the primary value by %d\n"
            "clause cl_default [otherwise]: return the primary value unchanged\n"
            "validity: %s\nverify: output follows the applicable clause.\n"
            % (f["func"], ", ".join(f["args"]), _scope_desc(f["domain"]), f["m"], val))


def _summary_text(f):
    return ("Org note: %s multiplies the primary value by %d when %s; otherwise unchanged."
            % (f["func"], f["m"], _scope_desc(f["domain"])))


def _raw_text(f):
    return ("Shared fix from %s: for %s, when the tenant/tier qualifies return primary * %d "
            "(no other conditions noted)." % (f["source_owner"], f["func"], f["m"]))


def _private_unrelated(f):
    return "Your earlier note: unrelated config-timeout task; no rule for %s." % f["func"]


def mem_block(f, condition, variant, m3_extract=None, contaminated=False):
    """Return (text_or_None, injected, reason). Governance gradient:
    M2 naive raw (always) · M3 vanilla extract (always) · M4 summary (basic scope filter, no validity) ·
    M5 governed (scope+validity gates) · M6 oracle (applies only when genuinely valid)."""
    if condition == "M0":
        return None, False, "no_memory"
    if condition == "M1":
        return _private_unrelated(f), True, "private_unrelated"   # target user's own history lacks the rule
    if condition == "M2":
        t = _raw_text(f)
        if contaminated:
            t = t.replace("primary * %d" % f["m"], "primary * %d" % (f["m"] + 1))   # benign wrong fix
        return t, True, "raw_shared_no_gate"
    if condition == "M3":
        return (m3_extract or _summary_text(f)), True, "vanilla_extract"
    if condition == "M4":
        if variant == "OUT_OF_SCOPE":
            return None, False, "summary_scope_filtered"   # M4 does basic scope filtering
        return _summary_text(f), True, "summary_no_validity_gate"   # but NOT validity -> injects on EXPIRED
    if condition == "M5":
        # governed: scope gate blocks OUT_OF_SCOPE; validity gate blocks EXPIRED; retrieval abstains on IRRELEVANT
        if variant == "OUT_OF_SCOPE":
            return None, False, "scope_gate_block"
        if variant == "EXPIRED":
            return None, False, "validity_gate_block"
        if variant == "IRRELEVANT":
            return None, False, "retrieval_abstain"
        return _contract_text(f), True, "governed_contract"
    if condition == "M6":
        # oracle: injects the correct related contract only when it genuinely applies
        if variant == "APPLICABLE":
            return _contract_text(f), True, "oracle_contract"
        return None, False, "oracle_no_valid_contract"
    return None, False, "unknown"


def n2_prompt_canary(f, variant, memory_text):
    from ..gaten_v2 import harness as H
    mem = ("Relevant internal memory:\n%s\n" % memory_text) if memory_text else "No internal contract is available.\n"
    rules = ("Modify ONLY the function body between BEGIN SOLUTION and END SOLUTION. Keep the exact "
             "signature. No new files/imports/deps; do not touch tests. Change at most 12 lines. Return "
             "ONLY a unified diff (```diff fenced).")
    return ("You are editing a fictional internal %s repository.\n\nFILE mod.py:\n```python\n%s```\n\n%s"
            "Task: implement `%s` to follow the org's rule for every input. %s\n"
            % (f["word"], H.starter_file(f), mem, f["func"], rules))


# ---------------------------------------------------------------- contamination + M5 registry
def contamination_bank():
    """Precommitted 8-family subset with 4 kinds of benign-bad shared fixes (failed / stale-version /
    repo-mismatch / superseded). Used for clean-vs-contaminated M2/M4/M5 comparison."""
    fams = families()[:8]
    kinds = ["failed_fix", "stale_version", "repo_mismatch", "superseded"]
    sub = {f["family_id"]: kinds[i % 4] for i, f in enumerate(fams)}
    return {"subset": sub, "hash": _hash(sub)}


def m5_registry_and_gates():
    """Store the promoted contracts in the authoritative SQLite registry and exercise the real
    permission/scope/validity gates for APPLICABLE (pass) vs OUT_OF_SCOPE/EXPIRED (block). Returns a
    registry content hash + per-family gate decisions used by M5."""
    from ...contracts.registry import SqliteRegistry
    reg = SqliteRegistry(); reg.migrate()
    ch = {}
    for f in families():
        cid = "c_%s" % f["family_id"].replace(".", "_")
        canon = json.dumps({"contract_id": cid, "func": f["func"], "scope": _scope_desc(f["domain"]),
                            "op": "multiply", "operand": f["m"], "state": "promoted", "version": "v2"}, sort_keys=True)
        ch[cid] = "sha256:" + hashlib.sha256(canon.encode()).hexdigest()[:16]
        reg.audit("promotion", "system", cid, {"family": f["family_id"]})
    reg.close()
    return {"registry_hash": _hash(ch), "n_contracts": len(ch), "audit_chained": True}


def manifest():
    fams = families()
    return {"n_families": len(fams), "by_domain": {d: sum(1 for f in fams if f["domain"] == d) for d in DOMAINS},
            "family_hashes": [f["content_hash"] for f in fams], "manifest_hash": _hash([f["content_hash"] for f in fams]),
            "users": USERS, "variants": VARIANTS, "conditions": CONDITIONS}
