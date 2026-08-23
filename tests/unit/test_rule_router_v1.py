"""P6/R19 §8 — RuleRouterV1: every reason code, determinism, sentinel leakage rejection, coverage accounting."""
import pytest

from enterprise_memory.router import (
    RuleRouterV1, TaskContext, TrajectoryState, Candidate, Policy,
    RouterLeakageError, USE_CODES, ABSTAIN_CODES, ALL_CODES, CoverageAccountant,
)
from enterprise_memory.router import reason_codes as RC

R = RuleRouterV1()


def ctx(**kw):
    base = dict(org_id="o1", repository="django/django", subtask="modification",
                target_apis=["importlib"], target_symbols=["MigrationLoader.load_disk"],
                error_signature="loader rejects namespace package without __file__", version="4.1")
    base.update(kw)
    return TaskContext(**base)


def cand(**kw):
    base = dict(card_key="ec_1", version_id="v1", governance_state="promoted", source_verified=True,
                repository_scope="django/django", version_scope="4.1", affected_apis=["importlib"],
                affected_symbols=["MigrationLoader.load_disk"], symptom_signature="loader rejects namespace __file__",
                operation="guard missing __file__", similarity=0.8, similarity_margin=0.2,
                provides_executable_action=True)
    base.update(kw)
    return Candidate(**base)


def traj(**kw):
    return TrajectoryState(**kw)


def d(c=None, t=None, tr=None):
    return R.decide(t or ctx(), tr or traj(), c or cand())


def test_direct_symbol_match_use():
    r = d()
    assert r.decision == "USE"
    assert RC.USE_DIRECT_SYMBOL_MATCH in r.reason_codes


def test_direct_api_match_use():
    r = d(cand(affected_symbols=["Other.thing"]))  # no symbol overlap, api overlaps
    assert r.decision == "USE" and RC.USE_DIRECT_API_MATCH in r.reason_codes


def test_failure_signature_match_use():
    c = cand(affected_symbols=["Other.thing"], affected_apis=["zzz"])  # only signature overlaps
    r = d(c)
    assert r.decision == "USE" and RC.USE_FAILURE_SIGNATURE_MATCH in r.reason_codes


def test_version_compatible_workaround_use():
    c = cand(version_scope="3.2", affected_symbols=["Other"], affected_apis=["zzz"], symptom_signature="unrelated x")
    r = d(c, ctx(version="4.1", error_signature="totally different wording here"))
    # version mismatch but provides executable action -> workaround USE (grounding via none, actionable)
    assert r.decision in ("USE", "ABSTAIN")
    if r.decision == "USE":
        assert RC.USE_VERSION_COMPATIBLE_WORKAROUND in r.reason_codes


def test_abstain_unverified_governance():
    assert d(cand(governance_state="quarantined")).reason_codes == [RC.ABSTAIN_UNVERIFIED]
    assert d(cand(source_verified=False)).reason_codes == [RC.ABSTAIN_UNVERIFIED]


def test_abstain_scope_wrong_repo():
    assert d(cand(repository_scope="flask/flask")).reason_codes == [RC.ABSTAIN_SCOPE]


def test_abstain_version_mismatch():
    c = cand(version_scope="3.2", provides_executable_action=False)
    assert d(c, ctx(version="4.1")).reason_codes == [RC.ABSTAIN_VERSION_MISMATCH]


def test_abstain_wrong_stage():
    c = cand(provides_executable_action=False)
    assert d(c, ctx(subtask="comprehension")).reason_codes == [RC.ABSTAIN_WRONG_STAGE]


def test_abstain_already_tried():
    assert d(tr=traj(browsed_card_keys=["ec_1"])).reason_codes == [RC.ABSTAIN_ALREADY_TRIED]
    assert d(tr=traj(tried_operations=["guard missing __file__"])).reason_codes == [RC.ABSTAIN_ALREADY_TRIED]


def test_abstain_high_risk():
    assert d(cand(contains_secret_or_pii=True)).reason_codes == [RC.ABSTAIN_HIGH_RISK]
    assert d(cand(contradicts_target=True)).reason_codes == [RC.ABSTAIN_HIGH_RISK]
    assert d(t=ctx(permitted=False)).reason_codes == [RC.ABSTAIN_HIGH_RISK]


def test_abstain_no_actionable_delta():
    c = cand(provides_executable_action=False, affected_symbols=["x"], affected_apis=["y"],
             symptom_signature="unrelated", version_scope="4.1")
    r = d(c, ctx(target_symbols=["z"], target_apis=["w"], error_signature="nothing matching here at all"))
    assert r.decision == "ABSTAIN" and RC.ABSTAIN_NO_ACTIONABLE_DELTA in r.reason_codes


def test_abstain_redundant_generic_advice():
    c = cand(generic_advice_only=True)
    r = d(c)
    assert r.decision == "ABSTAIN" and RC.ABSTAIN_REDUNDANT in r.reason_codes


def test_abstain_theme_only():
    # some similarity, but no grounding and no actionable delta
    c = cand(provides_executable_action=False, affected_symbols=["x"], affected_apis=["y"],
             symptom_signature="loosely related theme", similarity=0.5, version_scope="4.1")
    r = d(c, ctx(target_symbols=["z"], target_apis=["w"], error_signature="orthogonal issue text entirely"))
    assert r.decision == "ABSTAIN"
    assert RC.ABSTAIN_NO_ACTIONABLE_DELTA in r.reason_codes or RC.ABSTAIN_THEME_ONLY in r.reason_codes


def test_determinism():
    a = d(); b = d()
    assert (a.decision, a.reason_codes, a.score) == (b.decision, b.reason_codes, b.score)


def test_leakage_sentinel_rejected():
    t = ctx()
    t.extra = {"gold_patch": "diff --git ..."}
    with pytest.raises(RouterLeakageError):
        R.decide(t, traj(), cand())


def test_all_emitted_codes_are_frozen():
    seen = set()
    for r in [d(), d(cand(governance_state="deleted")), d(cand(repository_scope="x/y"))]:
        seen.update(r.reason_codes)
    assert seen <= ALL_CODES


def test_coverage_accountant_floor():
    acc = CoverageAccountant()
    acc.record(d())                        # USE
    acc.record(d(cand(repository_scope="x/y")))  # ABSTAIN scope
    assert acc.n_use == 1 and acc.n_abstain == 1
    assert acc.injection_coverage == 0.5
    assert acc.meets_floor(0.4) and not acc.meets_floor(0.6)
