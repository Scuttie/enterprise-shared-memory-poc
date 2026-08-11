from enterprise_memory.contracts import schema as S
from enterprise_memory.promotion import policy as P


def _c(applies=("a",), notapplies=("na",), verif=("pytest",), prov_eps=("ep1",), prov_sha=("sha",)):
    return S.MemoryContract("c1", S.SCHEMA_VERSION, "t", "safe retry summary",
        S.ContractScope("orgA", ["t1"], ["repoX"], ["src/**"], "python", "fw", {}, [], ["E"], list(applies), list(notapplies)),
        S.ContractAction(["s1"], "code", [], ["in"], ["op"]),
        S.ContractValidity("2020", "", {}, {}, [], [], ""),
        S.ContractVerification(list(verif), ["ok"], ["nr"], ["f"]),
        S.ContractProvenance(list(prov_eps), ["u0"], list(prov_sha), ["pass"], "x/1"),
        S.ContractEvidence(), S.ContractGovernance(state="candidate")).stamp()


def test_promotion_success():
    st, r, ev = P.evaluate_candidate(_c(), True, True, True, True, candidate_text="safe retry summary")
    assert st == P.PROMOTED and ev["evidence_hash"]


def test_reject_source_failed():
    st, r, _ = P.evaluate_candidate(_c(), False, True, True, True)
    assert st == P.PRIVATE_ONLY and r == "source_task_failed"


def test_reject_missing_antiscope():
    st, r, _ = P.evaluate_candidate(_c(notapplies=()), True, True, True, True)
    assert "does_not_apply_when" in r


def test_reject_secret():
    st, r, _ = P.evaluate_candidate(_c(), True, True, True, True, candidate_text="-----BEGIN PRIVATE KEY-----")
    assert st == P.QUARANTINED and r == "BLOCK_SECRET"


def test_replay_rejection_quarantine():
    st, r, _ = P.evaluate_candidate(_c(), True, True, True, False, candidate_text="safe")
    assert st == P.QUARANTINED and r == "nonapplicable_not_rejected"


def test_conflict_contradiction_quarantine():
    st, r, _ = P.evaluate_candidate(_c(), True, True, True, True, existing_promoted=[{"contract_id": "c9", "contradictory": True}], candidate_text="safe")
    assert st == P.QUARANTINED and r == "unresolved_contradiction"


def test_duplicate_merge():
    st, r, ev = P.evaluate_candidate(_c(), True, True, True, True, existing_promoted=[{"contract_id": "c9", "equivalent": True}], candidate_text="safe")
    assert st == P.PROMOTED and ev.get("merge")
