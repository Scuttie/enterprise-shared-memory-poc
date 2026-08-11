"""Production-service P0/P4/P5/P6 tests (offline; no external infra). Covers the production-refusal
startup gate, the generalised compiler IR + plugins + refusal, the durable job state machine, JWT
identity validation, outbox idempotency, and a REAL local end-to-end solve (Gate A in local mode)."""
import os
import sys
import time
import difflib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from enterprise_memory.service.settings import AppSettings, ProductionStartupError            # noqa: E402
from enterprise_memory.service import compiler_ir as C                                          # noqa: E402
from enterprise_memory.service.jobs import InMemoryJobRepository, can_transition, JobError      # noqa: E402
from enterprise_memory.service.outbox import InMemoryOutbox                                      # noqa: E402
from enterprise_memory.service import identity as ID                                            # noqa: E402
from enterprise_memory.service.orchestrator import SolveOrchestrator                            # noqa: E402
from enterprise_memory.service.container import build_container                                  # noqa: E402
from enterprise_memory.service.providers_local import FakeSolarProvider, LocalEvaluationSandbox, ListMetrics  # noqa: E402


# ---------------- settings / production refusal ----------------
def test_local_settings_ok():
    assert AppSettings(environment="local").validate() == []


def test_production_refuses_dev_backends():
    for kwargs in [{"registry_backend": "sqlite"}, {"identity_provider": "static"},
                   {"sandbox_provider": "local"}, {"coding_model": "fake"}, {"secrets_source": "env"}]:
        s = AppSettings(environment="production", registry_backend="postgres", private_index="mem0",
                        shared_index="mem0", identity_provider="oidc", sandbox_provider="kubernetes",
                        artifact_store="s3", coding_model="solar", secrets_source="k8s")
        for k, v in kwargs.items():
            setattr(s, k, v)
        try:
            s.validate()
            assert False, "expected refusal for %s" % kwargs
        except ProductionStartupError:
            pass


def test_production_requires_https_endpoints():
    s = AppSettings(environment="production", registry_backend="postgres", private_index="mem0",
                    shared_index="mem0", identity_provider="oidc", sandbox_provider="kubernetes",
                    artifact_store="s3", coding_model="solar", secrets_source="k8s",
                    external_endpoints={"qdrant": "http://q:6333"})
    try:
        s.validate(); assert False
    except ProductionStartupError as e:
        assert "https" in str(e)


# ---------------- compiler IR ----------------
def _directive(state="PROMOTED", validity="CURRENT", scope_ok=True, template="arithmetic.scale"):
    return C.ExecutionDirective(
        directive_id="d1", language="python", target_symbol="rate",
        exact_signature="rate(x)",
        predicates=[C.Predicate("tier", "==", "PLATINUM", "str"), C.Predicate("rev", ">=", 3, "int")],
        operation=C.Operation("o1", template, {"operand": 3}, "x"),
        verification="", source_contract_id="c1", source_contract_version="v3", source_contract_hash="h",
        governance_state=state, validity_state=validity, scope_ok=scope_ok)


def test_compiler_literal_and_retention():
    out = C.compile_directive(_directive())
    v = out["view"]
    assert "multiply x by 3" in v and "tier == 'PLATINUM'" in v and "rev >= 3" in v
    assert "rate(x)" in v
    assert out["parent_contract_hash"] == "h"
    assert "ct_" not in v and "provenance" not in v.lower() and "score=" not in v


def test_compiler_offset_and_select_plugins():
    assert "add 5 to x" in C.compile_directive(_directive(template="arithmetic.offset")
                                               .__class__(**{**_directive().__dict__,
                                                             "operation": C.Operation("o", "arithmetic.offset", {"operand": 5}, "x")}))["view"]


def test_compiler_refuses_invalid_and_unsupported():
    for st in C.REFUSE_STATES:
        try:
            C.compile_directive(_directive(state=st)); assert False
        except C.ViewRefused as e:
            assert e.reason == st
    for kw in [dict(validity="EXPIRED"), dict(scope_ok=False)]:
        try:
            C.compile_directive(_directive(**kw)); assert False
        except C.ViewRefused:
            pass
    d = _directive(); d.operation = C.Operation("o", "unknown.template", {}, "x")
    try:
        C.compile_directive(d); assert False
    except C.ViewRefused as e:
        assert e.reason == "REFUSED_UNSUPPORTED_DIRECTIVE"


# ---------------- job state machine ----------------
def test_job_transitions_and_idempotency():
    r = InMemoryJobRepository()
    j = r.create({"task": 1}, idempotency_key="k1")
    assert r.create({"task": 1}, idempotency_key="k1")["job_id"] == j["job_id"]   # duplicate -> same
    assert can_transition("QUEUED", "RETRIEVING") and not can_transition("SUCCEEDED", "QUEUED")
    claimed = r.claim("w1")
    assert claimed["state"] == "RETRIEVING" and claimed["attempts"] == 1
    r.transition(j["job_id"], "GENERATING"); r.transition(j["job_id"], "TESTING")
    r.transition(j["job_id"], "SUCCEEDED")
    try:
        r.transition(j["job_id"], "QUEUED"); assert False
    except JobError:
        pass


def test_job_lease_recovery():
    t = [0]
    r = InMemoryJobRepository(clock=lambda: t[0])
    j = r.create({"task": 2})
    r.claim("w1")                       # w1 leases, moves to RETRIEVING
    t[0] = 100                          # lease expires
    recovered = r.claim("w2")           # another worker recovers the expired-lease job
    assert recovered["job_id"] == j["job_id"] and recovered["lease_owner"] == "w2"


# ---------------- identity ----------------
def test_jwt_valid_and_invalid():
    now = 1000.0
    p = JwtP = ID.JwtIdentityProvider("https://idp", "esm-api", hs256_secret="s3cr3t", now_fn=lambda: now)
    good = ID.make_hs256({"iss": "https://idp", "aud": "esm-api", "sub": "u1", "org_id": "o1",
                          "exp": now + 60, "scope": "solve:submit solve:read", "jti": "t1"}, "s3cr3t")
    ic = p.authenticate("Bearer " + good)
    assert ic.subject_id == "u1" and ic.has_scope("solve:submit")
    bad_sig = good[:-2] + ("aa" if not good.endswith("aa") else "bb")
    for tok, exp in [("Bearer " + bad_sig, "bad_signature"), ("", "missing_bearer"),
                     ("Bearer " + ID.make_hs256({"iss": "evil", "aud": "esm-api", "sub": "u", "org_id": "o"}, "s3cr3t"), "bad_issuer")]:
        try:
            p.authenticate(tok); assert False
        except ID.AuthError:
            pass


def test_expired_jwt_rejected():
    now = 2000.0
    p = ID.JwtIdentityProvider("https://idp", "esm-api", hs256_secret="s", now_fn=lambda: now)
    tok = ID.make_hs256({"iss": "https://idp", "aud": "esm-api", "sub": "u", "org_id": "o", "exp": now - 100}, "s")
    try:
        p.authenticate("Bearer " + tok); assert False
    except ID.AuthError as e:
        assert "expired" in str(e)


# ---------------- outbox ----------------
def test_outbox_idempotent_and_quarantine():
    ob = InMemoryOutbox(max_attempts=2)
    ob.publish("CONTRACT_INDEX", "c1", {"x": 1})
    ob.publish("CONTRACT_INDEX", "c1", {"x": 1})     # same key -> applied once
    applied = []
    ob.drain(lambda ev: applied.append(ev["key"]))
    assert applied == ["c1"]
    ob.publish("CONTRACT_INDEX", "poison", {})
    def boom(ev):
        raise RuntimeError("fail")
    ob.drain(boom); r = ob.drain(boom)
    assert r["quarantined"] == 1


# ---------------- local end-to-end (Gate A, local mode) ----------------
class _DictRegistry:
    def __init__(self, contracts):
        self._c = contracts
    def get_contract(self, cid):
        return self._c.get(cid)
    def put_contract(self, c):
        return "h"
    def list_contracts(self, org_id=None, state=None):
        return list(self._c.values())


class _Index:
    def __init__(self, ids):
        self._ids = ids
    def add_view(self, *a, **k):
        pass
    def search(self, scope_id, query, k, filters):
        return list(self._ids) if scope_id.startswith("shared") else []


class _Audit:
    def __init__(self):
        self.events = []
    def emit(self, t, actor, subject, detail):
        self.events.append((t, subject)); return "a"


def _gold_responder(starter):
    fixed = starter.replace("raise NotImplementedError", "return x * 3")
    diff = "".join(difflib.unified_diff(starter.splitlines(True), fixed.splitlines(True), "a", "b"))
    return lambda prompt: "```diff\n%s```" % diff


def test_local_end_to_end_gate_a():
    starter = "def rate(x):\n    # BEGIN SOLUTION\n    raise NotImplementedError\n    # END SOLUTION\n"
    hidden = "from mod import rate\n\ndef test_h():\n    assert rate(10) == 30\n    assert rate(4) == 12\n"
    fixtures = {"repoX": {"files": {"mod.py": starter, "test_hidden.py": hidden}}}
    contract = {"contract_id": "c1", "version": "v3", "hash": "h1"}
    registry = _DictRegistry({"c1": contract})

    def directive_builder(c, task):
        return C.ExecutionDirective("d", "python", "rate", "rate(x)",
                                    [C.Predicate("tier", "==", "PLATINUM", "str")],
                                    C.Operation("o", "arithmetic.scale", {"operand": 3}, "x"),
                                    source_contract_id=c["contract_id"], source_contract_version=c["version"],
                                    source_contract_hash=c["hash"])
    cont = build_container(AppSettings(environment="local"), {"fixtures": fixtures})
    audit = _Audit()
    orch = SolveOrchestrator(registry, _Index([]), _Index(["c1"]), ID.StaticRepoAuthz({"o1": {"repoX"}}),
                             cont.repo_provider, FakeSolarProvider(_gold_responder(starter)),
                             cont.sandbox, audit, ListMetrics(), directive_builder)
    ident = ID.IdentityContext("bob", "o1", scopes=["solve:submit"])
    task = {"repo_id": "repoX", "query": "retry rule", "target_file": "mod.py", "test_entry": "test_hidden.py",
            "instruction": "Implement rate per the org rule.", "path_allowlist": ["mod.py", "test_hidden.py"]}
    out = orch.solve(ident, task, "lrq1")
    assert out["pass1"] == 1 and out["exec1"] == 1
    assert out["injected_contracts"] and out["injected_contracts"][0]["contract_id"] == "c1"
    assert out["private_leak"] is False
    assert any(t == "solve_outcome" for t, _ in audit.events)


def test_local_end_to_end_refuses_expired_contract():
    starter = "def rate(x):\n    # BEGIN SOLUTION\n    raise NotImplementedError\n    # END SOLUTION\n"
    fixtures = {"repoX": {"files": {"mod.py": starter, "test_hidden.py": "from mod import rate\n\ndef test_h():\n    assert rate(10)==30\n"}}}
    registry = _DictRegistry({"c1": {"contract_id": "c1", "version": "v1", "hash": "h"}})

    def expired_builder(c, task):
        return C.ExecutionDirective("d", "python", "rate", "rate(x)", [C.Predicate("tier", "==", "P", "str")],
                                    C.Operation("o", "arithmetic.scale", {"operand": 3}, "x"),
                                    validity_state="EXPIRED", source_contract_id="c1")
    cont = build_container(AppSettings(environment="local"), {"fixtures": fixtures})
    orch = SolveOrchestrator(registry, _Index([]), _Index(["c1"]), ID.StaticRepoAuthz({"o1": {"repoX"}}),
                             cont.repo_provider, FakeSolarProvider(lambda p: "```diff\n```"),
                             cont.sandbox, _Audit(), ListMetrics(), expired_builder)
    out = orch.solve(ID.IdentityContext("bob", "o1", scopes=["solve:submit"]),
                     {"repo_id": "repoX", "query": "q", "target_file": "mod.py", "test_entry": "test_hidden.py",
                      "instruction": "x", "path_allowlist": ["mod.py", "test_hidden.py"]}, "lrq2")
    assert out["injected_contracts"] == []       # expired contract refused -> no model-facing view
