"""Deterministic generator for the frozen static instrument (P5.1 §6). Given a split name + count, it emits
Families with three disjoint tasks each. Fully deterministic (constants/names derived by SHA-256 from the
split+index, no RNG, no clock) so regeneration is bit-identical. Different splits ('calibration' vs 'main')
produce disjoint families by construction.

Each domain's function depends only on its argument and the family convention constant C (no per-task base),
so the reusable technique (formula shape + C) fully determines a correct GENERAL implementation — exactly what
governed memory carries. The three roles differ by a distinct hidden-test input, so their outputs differ while
the code is identical. A memory-less model cannot recover the formula shape OR C from the (incomplete) public
test, which only pins the C-independent case at input 0."""
from __future__ import annotations
import hashlib
from .schema import Task, Family

GENERATOR_VERSION = "p5.1-static/2.0.0"
DOMAINS = ("internal_api", "cache", "config", "schema")

# distinct hidden-test input per role -> distinct outputs (all reveal C); public input is always 0 (reveals no C)
ROLE_HIDDEN = {"own_source": 2, "cross_source": 3, "target": 4}

# per-domain: prior default D, candidate convention constants (all != D), the formula expression over the arg
# (with C as a %d slot), the arg name, and the human note (which states the general formula + C).
_DOMAIN = {
    "internal_api": {"prior": 2, "consts": (3, 4, 5), "arg": "attempt", "expr": "%d ** attempt",
                     "label": "C ** attempt",
                     "note": "In this service the retry backoff for an attempt is the backoff multiplier "
                             "raised to the attempt number (backoff = multiplier ** attempt); the multiplier "
                             "for this codebase is %d."},
    "cache": {"prior": 60, "consts": (30, 45, 90), "arg": "tier", "expr": "%d * tier", "label": "C * tier",
              "note": "Cache TTL for a tier is a fixed per-tier increment multiplied by the tier level "
                      "(ttl = increment * tier); the per-tier increment for this codebase is %d."},
    "config": {"prior": 10, "consts": (15, 25, 40), "arg": "level", "expr": "%d * level * level",
               "label": "C * level * level",
               "note": "The environment override for a level scales quadratically with the level "
                       "(value = factor * level * level); the override factor for this codebase is %d."},
    "schema": {"prior": 1, "consts": (3, 7, 9), "arg": "value", "expr": "value ** %d", "label": "value ** C",
               "note": "Field normalization raises the raw value to a fixed power (normalized = value ** "
                       "power); the power for this codebase is %d."},
}


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest(), 16)


def _pick(seq, *parts):
    return seq[_h(*parts) % len(seq)]


def _eval(domain, C, n) -> int:
    if domain == "internal_api":
        return C ** n
    if domain == "cache":
        return C * n
    if domain == "config":
        return C * n * n
    if domain == "schema":
        return n ** C
    raise ValueError(domain)


def _name(domain, split, fi, role):
    tag = hashlib.sha256(("%s|%s|%d|%s" % (domain, split, fi, role)).encode()).hexdigest()[:6]
    return "%s_%s" % ({"internal_api": "backoff", "cache": "ttl", "config": "cfg", "schema": "scale"}[domain], tag)


def _task(domain, split, fi, role, C, D):
    d = _DOMAIN[domain]
    arg = d["arg"]
    fn = _name(domain, split, fi, role)
    fam = "fam_%s_%s_%d" % (split, domain, fi)
    repo = "repo_%s_%s_%d_%s" % (split, domain, fi, role)
    src_path = "src/%s.py" % fn
    test_path = "tests/test_%s.py" % fn
    sig = "def %s(%s)" % (fn, arg)
    stub = "%s:\n    # TODO: implement per the service convention\n    return 0\n" % sig
    body_expr = d["expr"] % C
    gold_body = "%s:\n    return %s\n" % (sig, body_expr)
    pub_in = 0
    hid_in = ROLE_HIDDEN[role]
    pub_out = _eval(domain, C, pub_in)
    hid_out = _eval(domain, C, hid_in)
    public_test = ("from src.%s import %s\n\n\ndef test_public():\n    assert %s(%d) == %d\n"
                   % (fn, fn, fn, pub_in, pub_out))
    hidden_test = ("from src.%s import %s\n\n\ndef test_hidden():\n    assert %s(%d) == %d\n"
                   % (fn, fn, fn, hid_in, hid_out))
    return Task(task_id="%s_%s" % (fam, role), family_id=fam, domain=domain, role=role, repo_fixture_id=repo,
                target_path=src_path, editable_paths=["src/**"], target_symbol=fn, exact_signature=sig,
                public_test_path=test_path, public_test=public_test, hidden_test=hidden_test, src_stub=stub,
                world_constant=C, prior_default=D, formula_label=d["label"], public_input=pub_in,
                hidden_input=hid_in, base=hid_in, gold_body=gold_body, hidden_expected=hid_out)


def _family(domain, split, fi):
    d = _DOMAIN[domain]
    D = d["prior"]
    C = _pick(d["consts"], split, domain, fi, "C")
    fam = "fam_%s_%s_%d" % (split, domain, fi)
    roles = ("own_source", "cross_source", "target")
    tasks = {role: _task(domain, split, fi, role, C, D) for role in roles}
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
                                                   t.hidden_input)).encode())
    return h.hexdigest()
