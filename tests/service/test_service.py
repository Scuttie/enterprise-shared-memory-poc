"""Production-service P0-fix tests (offline). Async interfaces, generalised compiler, job machine, JWT,
outbox, strict config, benchmark-free patch utils, and a local component-chain integration test with real
private-memory ownership accounting and can_modify enforcement."""
import os
import sys
import asyncio
import difflib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from enterprise_memory.service.settings import AppSettings, ProductionStartupError, ConfigError   # noqa: E402
from enterprise_memory.service import compiler_ir as C                                             # noqa: E402
from enterprise_memory.service.jobs import InMemoryJobRepository, can_transition, JobError         # noqa: E402
from enterprise_memory.service.outbox import InMemoryOutbox                                         # noqa: E402
from enterprise_memory.service import identity as ID                                               # noqa: E402
from enterprise_memory.service.orchestrator import SolveOrchestrator                               # noqa: E402
from enterprise_memory.service.container import build_container                                     # noqa: E402
from enterprise_memory.service.providers_local import FakeSolarProvider, ListMetrics, ListAudit, InMemoryOutcomeStore  # noqa: E402
from enterprise_memory.patches import apply_unified_diff, PatchError                                # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ---------------- strict settings ----------------
def test_local_ok_and_unknown_rejected():
    assert AppSettings(environment="local").validate() == []
    try:
        AppSettings(environment="local", execution_view="bogus").validate(); assert False
    except ConfigError as e:
        assert "execution_view" in str(e)


def test_production_diagnostics_complete_then_raise():
    s = AppSettings(environment="production")   # all dev defaults + missing prod fields
    try:
        s.validate(); assert False
    except ProductionStartupError as e:
        joined = "; ".join(e.errors)
        assert "registry_backend" in joined and "oidc_issuer" in joined and "postgres_dsn" in joined
        assert len(e.errors) >= 6   # complete diagnostic list, not first-error-only


def test_production_ok_with_full_prod_config():
    s = AppSettings(environment="production", registry_backend="postgres", private_index="mem0",
                    shared_index="mem0", identity_provider="oidc", sandbox_provider="kubernetes",
                    artifact_store="s3", coding_model="solar", secrets_source="k8s",
                    oidc_issuer="https://idp", oidc_audience="a", oidc_jwks_uri="https://idp/jwks",
                    postgres_dsn="x", qdrant_url="https://q", object_store_endpoint="https://s3",
                    private_collection="p", shared_collection="s")
    assert s.validate() == []


def test_staging_unsafe_backends_flag():
    s = AppSettings(environment="staging", allow_unsafe_staging_backends=True,
                    oidc_issuer="i", oidc_audience="a", oidc_jwks_uri="j", postgres_dsn="d",
                    qdrant_url="https://q", object_store_endpoint="https://o")
    assert s.validate() == []   # permitted only with the explicit unsafe flag


# ---------------- compiler ----------------
def _directive(**kw):
    base = dict(directive_id="d1", language="python", target_symbol="rate", exact_signature="rate(x)",
                predicates=[C.Predicate("tier", "==", "PLATINUM", "str"), C.Predicate("rev", ">=", 3, "int")],
                operation=C.Operation("o1", "arithmetic.scale", {"operand": 3}, "x"),
                source_contract_id="c1", source_contract_version="v3", source_contract_hash="h")
    base.update(kw)
    return C.ExecutionDirective(**base)


def test_compiler_literal_and_refusals():
    v = C.compile_directive(_directive())["view"]
    assert "multiply x by 3" in v and "tier == 'PLATINUM'" in v and "rev >= 3" in v and "rate(x)" in v
    assert "ct_" not in v and "provenance" not in v.lower()
    for st in C.REFUSE_STATES:
        try:
            C.compile_directive(_directive(governance_state=st)); assert False
        except C.ViewRefused as e:
            assert e.reason == st
    d = _directive(operation=C.Operation("o", "unknown.t", {}, "x"))
    try:
        C.compile_directive(d); assert False
    except C.ViewRefused as e:
        assert e.reason == "REFUSED_UNSUPPORTED_DIRECTIVE"


def test_compiler_offset_select_plugins():
    assert "add 5 to x" in C.compile_directive(_directive(operation=C.Operation("o", "arithmetic.offset", {"operand": 5}, "x")))["view"]
    assert "return src" in C.compile_directive(_directive(operation=C.Operation("o", "select.source", {"source_symbol": "src"}, "x")))["view"]


# ---------------- patches (benchmark-free) ----------------
def test_patch_applicator_no_benchmark_import():
    import enterprise_memory.patches.applicator as ap
    assert "benchmarks" not in ap.__name__
    orig = "def f():\n    raise NotImplementedError\n"
    diff = "```diff\n-    raise NotImplementedError\n+    return 7\n```"
    new, meta = apply_unified_diff(orig, diff)
    assert "return 7" in new and meta["add"] == 1


# ---------------- jobs / outbox ----------------
def test_job_machine_async():
    r = InMemoryJobRepository()
    j = run(r.create({"t": 1}, idempotency_key="k1"))
    assert run(r.create({"t": 1}, idempotency_key="k1"))["job_id"] == j["job_id"]
    assert can_transition("QUEUED", "RETRIEVING") and not can_transition("SUCCEEDED", "QUEUED")
    run(r.claim("w1")); run(r.transition(j["job_id"], "GENERATING")); run(r.transition(j["job_id"], "TESTING"))
    run(r.transition(j["job_id"], "SUCCEEDED"))
    try:
        run(r.transition(j["job_id"], "QUEUED")); assert False
    except JobError:
        pass


def test_job_lease_recovery_async():
    t = [0]
    r = InMemoryJobRepository(clock=lambda: t[0])
    j = run(r.create({"t": 2})); run(r.claim("w1")); t[0] = 100
    rec = run(r.claim("w2"))
    assert rec["job_id"] == j["job_id"] and rec["lease_owner"] == "w2"


def test_outbox_idempotent_quarantine():
    ob = InMemoryOutbox(max_attempts=2)
    ob.publish("CONTRACT_INDEX", "c1", {}); ob.publish("CONTRACT_INDEX", "c1", {})
    got = []; ob.drain(lambda ev: got.append(ev["key"]))
    assert got == ["c1"]
    ob.publish("CONTRACT_INDEX", "poison", {})
    ob.drain(lambda ev: (_ for _ in ()).throw(RuntimeError())); r = ob.drain(lambda ev: (_ for _ in ()).throw(RuntimeError()))
    assert r["quarantined"] == 1


# ---------------- identity ----------------
def test_jwt_valid_invalid_expired():
    now = [1000.0]
    p = ID.JwtIdentityProvider("https://idp", "esm-api", hs256_secret="s", now_fn=lambda: now[0])
    good = ID.make_hs256({"iss": "https://idp", "aud": "esm-api", "sub": "u1", "org_id": "o1",
                          "exp": now[0] + 60, "scope": "solve:submit"}, "s")
    assert run(p.authenticate("Bearer " + good)).subject_id == "u1"
    for tok in [good[:-2] + "zz", "", "Bearer " + ID.make_hs256({"iss": "evil", "aud": "esm-api", "sub": "u", "org_id": "o"}, "s")]:
        try:
            run(p.authenticate("Bearer " + tok if tok and not tok.startswith("Bearer") else tok)); assert False
        except ID.AuthError:
            pass
    exp = ID.make_hs256({"iss": "https://idp", "aud": "esm-api", "sub": "u", "org_id": "o", "exp": now[0] - 100}, "s")
    try:
        run(p.authenticate("Bearer " + exp)); assert False
    except ID.AuthError as e:
        assert "expired" in str(e)


# ---------------- local component-chain integration (Gate A: PARTIAL — direct chain, not HTTP/worker/DB) ----------------
class _Reg:
    def __init__(self, c):
        self._c = c
    async def get_contract(self, cid):
        return self._c.get(cid)
    async def put_contract(self, c):
        return "h"
    async def list_contracts(self, org_id=None, state=None):
        return list(self._c.values())


class _Idx:
    def __init__(self, items):
        self._items = items
    async def add_view(self, *a, **k):
        pass
    async def search(self, scope_id, query, k, filters):
        return list(self._items)


def _gold(starter):
    fixed = starter.replace("raise NotImplementedError", "return x * 3")
    diff = "".join(difflib.unified_diff(starter.splitlines(True), fixed.splitlines(True), "a", "b"))
    return lambda p: "```diff\n%s```" % diff


def _mk_orch(shared_items, priv_items, responder):
    starter = "def rate(x):\n    # BEGIN SOLUTION\n    raise NotImplementedError\n    # END SOLUTION\n"
    hidden = "from mod import rate\n\ndef test_h():\n    assert rate(10)==30\n    assert rate(4)==12\n"
    fixtures = {"repoX": {"files": {"mod.py": starter, "test_hidden.py": hidden}}}
    cont = build_container(AppSettings(environment="local"), {"fixtures": fixtures})

    def db(c, task):
        return C.ExecutionDirective("d", "python", "rate", "rate(x)", [C.Predicate("tier", "==", "P", "str")],
                                    C.Operation("o", "arithmetic.scale", {"operand": 3}, "x"),
                                    source_contract_id=c["contract_id"], source_contract_version=c.get("version", "v1"),
                                    source_contract_hash=c.get("hash", "h"),
                                    validity_state=c.get("validity", "CURRENT"))
    orch = SolveOrchestrator(_Reg({"c1": {"contract_id": "c1", "version": "v3", "hash": "h1"}}),
                             _Idx(priv_items), _Idx(shared_items),
                             ID.StaticRepoAuthz({"o1": {"repoX"}}, {"o1": {"repoX"}}),
                             cont.repo_provider, FakeSolarProvider(responder(starter)),
                             cont.sandbox, ListAudit(), ListMetrics(), db,
                             outcome_store=cont.outcome_store, outbox=cont.outbox)
    task = {"repo_id": "repoX", "query": "q", "target_file": "mod.py", "test_entry": "test_hidden.py",
            "func": "rate", "signature": "def rate(x):", "instruction": "Implement rate."}
    return orch, task


def test_local_chain_pass_and_persist():
    orch, task = _mk_orch(["c1"], [], _gold)
    ident = ID.IdentityContext("bob", "o1", scopes=["solve:submit"])
    out = run(orch.solve(ident, task, "lrq1"))
    assert out["pass1"] == 1 and out["exec1"] == 1
    assert out["injected_contracts"][0]["contract_id"] == "c1"
    assert out["cross_user_private_injection_count"] == 0 and out["outcome_id"]


def test_solve_requires_can_modify():
    orch, task = _mk_orch(["c1"], [], _gold)
    orch.authz = ID.StaticRepoAuthz({"o1": {"repoX"}}, {"o1": set()})   # read yes, modify no
    try:
        run(orch.solve(ID.IdentityContext("bob", "o1", scopes=["solve:submit"]), task, "lrq"))
        assert False
    except PermissionError as e:
        assert "modify" in str(e)


def test_cross_user_private_never_injected():
    # a private item owned by someone else must NOT be injected and must be counted (=0 injection)
    orch, task = _mk_orch([], [{"id": "m1", "owner": "alice", "note": "secret", "hash": "h"}], lambda s: (lambda p: "```diff\n```"))
    out = run(orch.solve(ID.IdentityContext("bob", "o1", scopes=["solve:submit"]), task, "lrq"))
    assert out["cross_user_private_injection_count"] == 0     # never INJECTED (hard-fail metric stays 0)
    assert out["cross_user_private_blocked"] == 1             # detected + blocked (defense in depth)
    assert all(m.get("kind") != "private" for m in out["injected_contracts"])   # none injected


def test_expired_contract_refused_no_view():
    orch, task = _mk_orch(["c1"], [], lambda s: (lambda p: "```diff\n```"))
    reg = orch.registry._c["c1"]; reg["validity"] = "EXPIRED"
    out = run(orch.solve(ID.IdentityContext("bob", "o1", scopes=["solve:submit"]), task, "lrq"))
    assert out["injected_contracts"] == []
