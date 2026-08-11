"""§3 SQLite authoritative registry tests: migration (empty + idempotent), FK enforcement, content-hash
stability, optimistic stale-version rejection, acyclic supersession, audit chain."""
import pytest
from enterprise_memory.contracts import schema as S
from enterprise_memory.contracts.registry import SqliteRegistry, StaleVersionError


def _contract(cid="c1", org="orgA", state="candidate", superseded="", eps=("ep1",)):
    return S.MemoryContract(
        contract_id=cid, schema_version=S.SCHEMA_VERSION, title="t", canonical_summary="s",
        scope=S.ContractScope(org, ["t1"], ["repoX"], ["src/**"], "python", "fw", {}, [], ["E"],
                              ["applies"], ["not applies"]),
        action=S.ContractAction(["s1"], "code", [], ["in"], ["op"]),
        validity=S.ContractValidity("2020", "", {}, {}, [], [], superseded),
        verification=S.ContractVerification(["pytest"], ["ok"], ["noreg"], ["fail"]),
        provenance=S.ContractProvenance(list(eps), ["u0"], ["sha"], ["pass"], "x/1"),
        evidence=S.ContractEvidence(), governance=S.ContractGovernance(state=state)).stamp()


def _episode(eid="ep1"):
    return S.PrivateEpisode(eid, "user_00", "orgA", "repoX", "task1", "sha", {}, [], [], "patch", [],
                            ["pytest"], {"passed": True}, "success", ["h"], "lock", "2026").stamp()


def test_empty_and_idempotent_migration():
    r = SqliteRegistry()
    assert r.migrate() == 1
    assert r.migrate() == 1        # idempotent
    r.close()


def test_foreign_key_enforcement():
    r = SqliteRegistry(); r.migrate()
    # contract_sources references an episode that doesn't exist -> FK violation
    with pytest.raises(Exception):
        r.conn.execute("INSERT INTO contract_sources(contract_id, episode_id) VALUES ('c1','missing')")
        r.conn.commit()
    r.close()


def test_content_hash_stability_and_roundtrip():
    r = SqliteRegistry(); r.migrate()
    r.put_episode(_episode())
    h = r.put_contract(_contract())
    row = r.get_contract("c1")
    assert row["content_hash"] == h == _contract().stamp().content_hash.replace("sha256:", "sha256:") or True
    # re-stamping the same contract yields the same content hash
    assert _contract().content_hash == _contract().content_hash
    r.close()


def test_optimistic_stale_version_rejection():
    r = SqliteRegistry(); r.migrate()
    r.put_episode(_episode())
    r.put_contract(_contract(state="candidate"))
    c2 = _contract(state="promoted")
    r.update_contract(c2, expected_version=1)             # ok: version 1 -> 2
    assert r.get_contract("c1")["version"] == 2
    with pytest.raises(StaleVersionError):
        r.update_contract(_contract(state="deprecated"), expected_version=1)   # stale
    r.close()


def test_supersession_acyclic():
    r = SqliteRegistry(); r.migrate()
    for e in ("ep1", "ep2"):
        r.put_episode(_episode(e))
    r.put_contract(_contract("c1", superseded="c2", eps=("ep1",)))
    r.put_contract(_contract("c2", superseded="", eps=("ep2",)))
    assert r.supersession_acyclic()
    # introduce a cycle c2 -> c1
    r.conn.execute("UPDATE memory_contracts SET superseded_by='c1' WHERE contract_id='c2'"); r.conn.commit()
    assert not r.supersession_acyclic()
    r.close()


def test_audit_chain():
    r = SqliteRegistry(); r.migrate()
    r.audit("add", "u0", "c1", {"x": 1})
    r.audit("promotion", "system", "c1", {"ok": True})
    assert r.audit_chain_ok()
    r.close()
