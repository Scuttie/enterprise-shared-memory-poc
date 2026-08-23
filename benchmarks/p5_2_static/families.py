"""P5.2 generator (§4). Every task = an ordinary CORE (a multiplicative formula inferable from the public
tests: f(n) = base * m(n)) plus a local edge-case CONVENTION for n >= EDGE. Strata control the M0 baseline:

  PRIOR_ALIGNED    : the edge value equals the natural core continuation (edge multiplier K = m(EDGE)), so a
                     memory-less model that implements the core for all n already passes. Memory is redundant.
  CONTEXT_INFERABLE: K != m(EDGE), but the stub carries a weak, non-answer repository clue (a named constant +
                     comment) revealing the edge rule, so a memory-less model can infer it.
  PRIOR_CONFLICT   : K != m(EDGE), no clue -> a memory-less model applies the core continuation and fails the
                     edge; the memory is the intended disambiguator.

The edge value is base * K with base task-specific (revealed by the public test) and K the family convention
carried by memory — so no target answer is ever in memory (different roles use different bases).

Roles differ by base only; the convention K and edge rule are shared within a family. Deterministic (SHA-256;
no RNG/clock)."""
from __future__ import annotations
import hashlib
from .schema import Task, Family

GENERATOR_VERSION = "p5.2-static/1.0.0"
DOMAINS = ("internal_api", "cache", "config", "schema")
STRATA = ("prior_aligned", "context_inferable", "prior_conflict")
CORE_INPUTS = (0, 1, 2)
EDGE = 5
ROLE_BASE = {"own_source": 3, "cross_source": 5, "target": 7}     # distinct base per role -> distinct outputs

# per domain: core multiplier m(n) as a python expr over n, the edge-name, and a domain label
_DOMAIN = {
    "internal_api": {"arg": "attempt", "m": "2 ** attempt", "m_fn": lambda n: 2 ** n,
                     "edge_name": "retry cap", "edge_word": "attempts at or beyond the cap tier"},
    "cache": {"arg": "tier", "m": "(tier + 1)", "m_fn": lambda n: n + 1,
              "edge_name": "cold tier", "edge_word": "cold tiers"},
    "config": {"arg": "level", "m": "(level + 2)", "m_fn": lambda n: n + 2,
               "edge_name": "override branch", "edge_word": "override levels"},
    "schema": {"arg": "value", "m": "(3 * value + 1)", "m_fn": lambda n: 3 * n + 1,
               "edge_name": "compat range", "edge_word": "values in the compatibility range"},
}

# per-domain calibration/main stratum layout (§4): calibration 1 PA / 1 CI / 2 PC per domain
_CAL_LAYOUT = ["prior_aligned", "context_inferable", "prior_conflict", "prior_conflict"]
_MAIN_LAYOUT = ["prior_aligned", "prior_aligned", "context_inferable", "context_inferable",
                "prior_conflict", "prior_conflict", "prior_conflict", "prior_conflict"]
_DEV_LAYOUT = ["prior_aligned", "prior_conflict"]     # instrument-dev: 2/domain, tests both M0 extremes


def _h(*p):
    return int(hashlib.sha256("|".join(str(x) for x in p).encode()).hexdigest(), 16)


def family_tag(split, domain, fi):
    return "technique_%s_%s_%d" % (domain, hashlib.sha256(split.encode()).hexdigest()[:4], fi)


def _K(domain, split, fi, stratum):
    d = _DOMAIN[domain]
    aligned = d["m_fn"](EDGE)                       # K that makes the edge == core continuation
    if stratum == "prior_aligned":
        return aligned
    # a distinct convention multiplier (!= aligned), deterministic
    cands = [k for k in (2, 3, 4, 6, 8) if k != aligned]
    return cands[_h(split, domain, fi, "K") % len(cands)]


def _name(domain, split, fi, role):
    tag = hashlib.sha256(("%s|%s|%d|%s" % (domain, split, fi, role)).encode()).hexdigest()[:6]
    return "%s_%s" % ({"internal_api": "backoff", "cache": "ttl", "config": "weight", "schema": "scale"}[domain],
                      tag)


def _task(domain, split, fi, role, stratum, K):
    d = _DOMAIN[domain]
    arg = d["arg"]
    base = ROLE_BASE[role]
    fn = _name(domain, split, fi, role)
    fam = "fam_%s_%s_%d" % (split, domain, fi)
    repo = "repo_%s_%s_%d_%s" % (split, domain, fi, role)
    sig = "def %s(%s)" % (fn, arg)
    edge_val = base * K
    aligned = (K == d["m_fn"](EDGE))
    # stub: PRIOR_ALIGNED/PRIOR_CONFLICT stub has no clue; CONTEXT_INFERABLE stub carries a weak clue constant.
    if stratum == "context_inferable":
        stub = ("_EDGE_MULT = %d  # %s use base * this multiplier for %s (%s >= %d)\n%s:\n"
                "    # TODO: core behaviour, plus the documented edge rule\n    return 0\n"
                % (K, d["edge_name"], d["edge_word"], arg, EDGE, sig))
    else:
        stub = "%s:\n    # TODO: implement per the service behaviour\n    return 0\n" % sig
    gold_body = ("%s:\n    if %s >= %d:\n        return %d * %d\n    return %d * %s\n"
                 % (sig, arg, EDGE, base, K, base, d["m"]))
    # public test: core inputs only (does not reveal the edge). hidden: core + the edge case.
    core_asserts = "\n".join("    assert %s(%d) == %d" % (fn, n, base * d["m_fn"](n)) for n in CORE_INPUTS)
    public_test = "from src.%s import %s\n\n\ndef test_public():\n%s\n" % (fn, fn, core_asserts)
    hidden_test = ("from src.%s import %s\n\n\ndef test_hidden():\n%s\n    assert %s(%d) == %d\n"
                   % (fn, fn, core_asserts, fn, EDGE, edge_val))
    return Task(task_id="%s_%s" % (fam, role), family_id=fam, domain=domain, role=role, stratum=stratum,
                repo_fixture_id=repo, target_path="src/%s.py" % fn, editable_paths=["src/**"],
                target_symbol=fn, exact_signature=sig, public_test_path="tests/test_%s.py" % fn,
                public_test=public_test, hidden_test=hidden_test, src_stub=stub, base=base, edge_input=EDGE,
                edge_mult=K, edge_value=edge_val, aligned=aligned, gold_body=gold_body,
                core_expr=d["m"], edge_name=d["edge_name"])


def _family(domain, split, fi, stratum):
    K = _K(domain, split, fi, stratum)
    fam = "fam_%s_%s_%d" % (split, domain, fi)
    d = _DOMAIN[domain]
    note = ("For %s (%s >= %d) this codebase returns the base multiplied by a fixed edge multiplier; the edge "
            "multiplier is %d (core behaviour is base * %s for smaller inputs)."
            % (d["edge_name"], d["arg"], EDGE, K, d["m"]))
    tasks = {r: _task(domain, split, fi, r, stratum, K) for r in ("own_source", "cross_source", "target")}
    return Family(family_id=fam, domain=domain, stratum=stratum, edge_multiplier=K, technique_note=note,
                  tag=family_tag(split, domain, fi), tasks=tasks)


def generate(split: str, n_per_domain: int):
    layout = {2: _DEV_LAYOUT, 4: _CAL_LAYOUT, 8: _MAIN_LAYOUT}.get(n_per_domain)
    if layout is None:
        raise ValueError("P5.2 supports n_per_domain 2 (dev) / 4 (calibration) / 8 (main); got %r"
                         % n_per_domain)
    fams = []
    for domain in DOMAINS:
        for fi in range(n_per_domain):
            fams.append(_family(domain, split, fi, layout[fi]))
    return fams


def generation_hash(split: str, n_per_domain: int) -> str:
    h = hashlib.sha256(); h.update(GENERATOR_VERSION.encode())
    for f in generate(split, n_per_domain):
        for r in ("own_source", "cross_source", "target"):
            t = f.tasks[r]
            h.update(("%s|%s|%s|%d|%d|%s|%s" % (t.task_id, t.stratum, t.exact_signature, t.edge_value,
                                                t.edge_mult, t.public_test, t.hidden_test)).encode())
    return h.hexdigest()
