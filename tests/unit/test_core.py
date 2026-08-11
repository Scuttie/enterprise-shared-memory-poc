"""Commit-1 core tests: schema hashing, in-memory backend isolation + logical/physical deletion,
permission/scope/validity gates, audit hash-chain. No external service, no API."""
from enterprise_memory.contracts import schema as S
from enterprise_memory.backends.in_memory import InMemoryBackend
from enterprise_memory.retrieval import gates as G
from enterprise_memory.audit.events import AuditLedger


def _user(uid="user_00", org="orgA", team="t1", repos=("repoX",)):
    return S.UserContext(org_id=org, team_id=team, user_id=uid, agent_id="a", allowed_repo_ids=list(repos),
                         allowed_path_globs=["src/**"], role="dev", request_id="req1")


def _task(repo="repoX", lang="python", deps=None, errs=None, paths=("src/api/retry.py",)):
    return S.TaskContext(task_id="t1", org_id="orgA", user_id="user_00", repo_id=repo,
                         repository_commit="abc", branch="main", language=lang, framework="fw",
                         dependency_versions=deps or {"api": "2"}, path_globs=list(paths),
                         task_text="fix retry", error_signatures=list(errs or ["E_RETRY"]),
                         environment_fingerprint="env1", created_at="2026-01-01").stamp()


def _contract(state="promoted", repos=("repoX",), valid_until="", superseded="", ver=None, dep=None,
              errs=("E_RETRY",), paths=("src/**",)):
    return S.MemoryContract(
        contract_id="c1", schema_version=S.SCHEMA_VERSION, title="retry", canonical_summary="retry rule",
        scope=S.ContractScope(org_id="orgA", team_ids=["t1"], repo_ids=list(repos), path_globs=list(paths),
                              language="python", framework="fw", dependency_version_constraints=dep or {},
                              branch_or_release_constraints=[], error_signatures=list(errs),
                              applies_when=["api v2 retry"], does_not_apply_when=["non-retryable code"]),
        action=S.ContractAction(["step1"], "code", [], ["retry_after"], ["op"]),
        validity=S.ContractValidity(valid_from="2020", valid_until=valid_until, environment_constraints={},
                                    version_constraints=ver or {}, invalidation_events=[],
                                    supersedes_contract_ids=[], superseded_by_contract_id=superseded),
        verification=S.ContractVerification(["pytest -q"], ["passes"], ["no regression"], ["fails"]),
        provenance=S.ContractProvenance(["ep1"], ["u0"], ["sha"], ["pass"], "extractor/1"),
        evidence=S.ContractEvidence(), governance=S.ContractGovernance(state=state)).stamp()


def test_schema_hash_stable():
    c = _contract()
    assert c.content_hash == _contract().content_hash
    assert c.validate() == []


def test_private_episode_isolation():
    b = InMemoryBackend()
    b.add("private:orgA:user_00", "ep1", "alice private trace", {"owner": "user_00", "org": "orgA"})
    # user_01 searching their own private namespace cannot see user_00's
    assert b.search("private:orgA:user_01", "trace", 5, {}) == []
    # guessed-ID fetch in another namespace fails
    assert b.get("private:orgA:user_01", "ep1") is None
    # even listing another user's namespace is empty
    assert b.list("private:orgA:user_01", {}) == []


def test_permission_gate():
    ok, _ = G.permission_gate(_user(), _contract())
    assert ok
    ok, r = G.permission_gate(_user(org="orgB"), _contract())
    assert not ok and r == "org_mismatch"
    ok, r = G.permission_gate(_user(), _contract(state="deprecated"))
    assert not ok and r.startswith("state_")
    ok, r = G.permission_gate(_user(repos=("repoY",)), _contract())
    assert not ok and r == "repo_not_allowed"


def test_scope_gate_repo_path_version():
    ok, _ = G.scope_gate(_task(), _contract())
    assert ok
    assert not G.scope_gate(_task(repo="repoY"), _contract())[0]                     # repo out of scope
    assert not G.scope_gate(_task(paths=("docs/readme.md",)), _contract())[0]        # path out of scope
    assert not G.scope_gate(_task(deps={"api": "1"}), _contract(dep={"api": ">=2"}))[0]  # version fails
    assert G.scope_gate(_task(deps={"api": "2"}), _contract(dep={"api": ">=2"}))[0]
    assert not G.scope_gate(_task(errs=["E_OTHER"]), _contract())[0]                 # error sig mismatch


def test_validity_gate_expiry_supersede_version():
    ok, _ = G.validity_gate(_task(), _contract(), now="2026-06-01")
    assert ok
    assert not G.validity_gate(_task(), _contract(valid_until="2025-01-01"), now="2026-06-01")[0]   # expired
    assert not G.validity_gate(_task(), _contract(superseded="c2"), now="2026", successor_valid=True)[0]  # superseded
    assert not G.validity_gate(_task(deps={"api": "3"}), _contract(ver={"api": "<=2"}), now="2026")[0]    # version invalid
    assert not G.validity_gate(_task(), _contract(state="quarantined"), now="2026")[0]               # quarantine excluded


def test_logical_vs_physical_deletion():
    b = InMemoryBackend()
    b.add("shared:orgA", "c1", "contract text", {"state": "promoted"})
    d = b.delete("shared:orgA", "c1", physical=False)
    assert d == {"logical": True, "physical": False}
    assert b.search("shared:orgA", "contract", 5, {}) == []   # search invisibility
    d2 = b.delete("shared:orgA", "c1", physical=True)
    assert d2 == {"logical": True, "physical": True}


def test_audit_hash_chain():
    a = AuditLedger()
    a.emit("add", "u0", "c1", {"x": 1}, seq_time=1)
    a.emit("promotion", "system", "c1", {"ok": True}, seq_time=2)
    assert a.completeness() == 1.0
    assert len(a.events("promotion")) == 1
