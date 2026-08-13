"""Deterministic generator for the frozen static instrument (P5.1 §6). Given a split name + count, it emits
Families with three disjoint tasks each. Fully deterministic (constants/names derived by SHA-256 from the
split+index, no RNG, no clock) so regeneration is bit-identical. Different splits ('calibration' vs 'main')
produce disjoint families by construction."""
from __future__ import annotations
import hashlib
from .schema import Task, Family

GENERATOR_VERSION = "p5.1-static/1.0.0"
DOMAINS = ("internal_api", "cache", "config", "schema")

# per-domain: prior default D, candidate convention constants (all != D), public/hidden inputs, base range,
# the formula, and human labels. All formulas are integer-valued and executable.
_DOMAIN = {
    "internal_api": {"prior": 2, "consts": (3, 4, 5), "public_in": 0, "hidden_in": 2, "bases": (1, 2, 3, 5),
                     "label": "base * (C ** attempt)", "arg": "attempt",
                     "note": "In this service retry backoff is base multiplied by the multiplier raised to the "
                             "attempt number; the backoff multiplier for this codebase is %d."},
    "cache": {"prior": 60, "consts": (30, 45, 90), "public_in": 0, "hidden_in": 3, "bases": (10, 20, 40, 80),
              "label": "base + C * tier", "arg": "tier",
              "note": "Cache TTL for a tier is the base TTL plus a fixed per-tier increment; the per-tier "
                      "increment for this codebase is %d seconds."},
    "config": {"prior": 100, "consts": (15, 25, 40), "public_in": 0, "hidden_in": 1, "bases": (5, 12, 30, 50),
               "label": "base + (C if flag else 0)", "arg": "flag",
               "note": "When the environment override flag is set this codebase adds a fixed increment to the "
                       "base value; that override increment is %d."},
    "schema": {"prior": 1, "consts": (3, 7, 9), "public_in": 0, "hidden_in": 5, "bases": (2, 4, 6, 8),
               "label": "value * C", "arg": "value",
               "note": "Field normalization in this codebase scales the raw value by a fixed factor; the scale "
                       "factor is %d."},
}


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest(), 16)


def _pick(seq, *parts):
    return seq[_h(*parts) % len(seq)]


def _perm(seq, *parts):
    """Deterministic permutation of `seq` (Fisher-Yates driven by SHA-256), so distinct picks are guaranteed."""
    items = list(seq)
    for i in range(len(items) - 1, 0, -1):
        j = _h(*parts, i) % (i + 1)
        items[i], items[j] = items[j], items[i]
    return items


def _formula(domain, C, base, x) -> int:
    if domain == "internal_api":
        return base * (C ** x)
    if domain == "cache":
        return base + C * x
    if domain == "config":
        return base + (C if x else 0)
    if domain == "schema":
        return x * C
    raise ValueError(domain)


def _body_expr(domain, C, base):
    if domain == "internal_api":
        return "%d * (%d ** attempt)" % (base, C)
    if domain == "cache":
        return "%d + %d * tier" % (base, C)
    if domain == "config":
        return "%d + (%d if flag else 0)" % (base, C)
    if domain == "schema":
        return "value * %d" % C
    raise ValueError(domain)


def _name(domain, split, fi, role):
    tag = hashlib.sha256(("%s|%s|%d|%s" % (domain, split, fi, role)).encode()).hexdigest()[:6]
    return "%s_%s" % ({"internal_api": "backoff", "cache": "ttl", "config": "cfg", "schema": "scale"}[domain], tag)


def _task(domain, split, fi, role, C, D, base):
    d = _DOMAIN[domain]
    arg = d["arg"]
    fn = _name(domain, split, fi, role)
    fam = "fam_%s_%s_%d" % (split, domain, fi)
    repo = "repo_%s_%s_%d_%s" % (split, domain, fi, role)
    src_path = "src/%s.py" % fn
    test_path = "tests/test_%s.py" % fn
    sig = "def %s(%s)" % (fn, arg)
    stub = "%s:\n    # TODO: implement per the service convention\n    return 0\n" % sig
    gold_body = "%s:\n    return %s\n" % (sig, _body_expr(domain, C, base))
    pub_in, hid_in = d["public_in"], d["hidden_in"]
    pub_out = _formula(domain, C, base, pub_in)
    hid_out = _formula(domain, C, base, hid_in)
    public_test = ("from src.%s import %s\n\n\ndef test_public():\n    assert %s(%d) == %d\n"
                   % (fn, fn, fn, pub_in, pub_out))
    hidden_test = ("from src.%s import %s\n\n\ndef test_hidden():\n    assert %s(%d) == %d\n"
                   % (fn, fn, fn, hid_in, hid_out))
    return Task(task_id="%s_%s" % (fam, role), family_id=fam, domain=domain, role=role, repo_fixture_id=repo,
                target_path=src_path, editable_paths=["src/**"], target_symbol=fn, exact_signature=sig,
                public_test_path=test_path, public_test=public_test, hidden_test=hidden_test, src_stub=stub,
                world_constant=C, prior_default=D, formula_label=d["label"], public_input=pub_in,
                hidden_input=hid_in, base=base, gold_body=gold_body, hidden_expected=hid_out)


def _family(domain, split, fi):
    d = _DOMAIN[domain]
    D = d["prior"]
    C = _pick(d["consts"], split, domain, fi, "C")
    fam = "fam_%s_%s_%d" % (split, domain, fi)
    perm = _perm(d["bases"], split, domain, fi, "base")     # 3 distinct bases -> distinct outputs per role
    roles = ("own_source", "cross_source", "target")
    tasks = {role: _task(domain, split, fi, role, C, D, perm[i]) for i, role in enumerate(roles)}
    return Family(family_id=fam, domain=domain, world_constant=C, prior_default=D,
                  technique_note=(d["note"] % C), tasks=tasks)


def generate(split: str, n_per_domain: int):
    """Return a deterministic list of Families for `split` (e.g. 'calibration' or 'main'), n_per_domain per
    domain (4 domains total)."""
    fams = []
    for domain in DOMAINS:
        for fi in range(n_per_domain):
            fams.append(_family(domain, split, fi))
    return fams


def generation_hash(split: str, n_per_domain: int) -> str:
    """A stable content hash of the generated split — used to prove deterministic regeneration."""
    fams = generate(split, n_per_domain)
    h = hashlib.sha256()
    h.update(GENERATOR_VERSION.encode())
    for f in fams:
        for role in ("own_source", "cross_source", "target"):
            t = f.tasks[role]
            h.update(("%s|%s|%d|%d|%s|%s|%s|%d" % (t.task_id, t.exact_signature, t.world_constant,
                                                   t.hidden_expected, t.src_stub, t.public_test, t.hidden_test,
                                                   t.base)).encode())
    return h.hexdigest()
