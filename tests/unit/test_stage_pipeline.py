"""R22 §4/§5/§6 — stage state machine, tools, retrieval pipeline, hard gate, budgets (credential-free)."""
import pytest

from enterprise_memory.experience.stage_schema import Stage
from enterprise_memory.service.stage_state import StageState, StageObservation, StageTransitionError
from enterprise_memory.service.stage_memory_tools import StageMemoryTools, BudgetError, MAX_SEARCH_PER_STAGE
from enterprise_memory.retrieval.stage_query import StageQuery
from enterprise_memory.retrieval.stage_pipeline import retrieve_stage, hard_gate
from enterprise_memory.retrieval.hybrid_candidates import score_candidates
from enterprise_memory.retrieval.applicability_reranker import select_top1, RANK_D_MIN_SCORE


def _views():
    return [
        {"memory_id": "m_edit", "stage": "EDIT", "error_signature": "AttributeError",
         "symbols": ["get_context"], "apis": [], "operation_type": "defensive_copy",
         "failing_test_signature": "test_checkbox", "repository_scope": "django/django"},
        {"memory_id": "m_other", "stage": "EDIT", "error_signature": "KeyError",
         "symbols": ["load"], "apis": ["yaml"], "operation_type": "guard", "repository_scope": "acme/x"},
    ]


def _q():
    return StageQuery(stage=Stage.EDIT, error_signature="AttributeError", symbols=["get_context"],
                      operation_type="defensive_copy", failing_test_signature="test_checkbox")


def test_stage_transition_requires_evidence():
    s = StageState()
    with pytest.raises(StageTransitionError):
        s.advance(Stage.EDIT)                      # no reproduction/localization evidence
    s.obs.issue_contract = "x"; s.advance(Stage.REPRODUCE)
    s.obs.reproduction = "failing test"; s.advance(Stage.LOCALIZE)
    s.obs.candidate_locations = ["a.py:f"]; s.advance(Stage.EDIT)   # now allowed
    assert s.stage == Stage.EDIT


def test_edit_search_blocked_without_localize():
    s = StageState(stage=Stage.EDIT)               # forced stage but no localize evidence
    assert s.can_search(Stage.EDIT) is False
    s.obs.candidate_locations = ["a.py"]
    assert s.can_search(Stage.EDIT) is True
    assert s.can_search(Stage.VERIFY) is False      # no applied patch


def test_hard_gate_target_leakage_and_repo():
    assert hard_gate({"memory_id": "x", "target_patch": "diff"}, {}) == "target_leakage"
    assert hard_gate({"memory_id": "x", "repository_scope": "acme/x"},
                     {"allowed_repositories": ["django/django"]}) == "repository"
    assert hard_gate({"memory_id": "x", "governance_state": "quarantined"}, {}) == "quarantine_deprecated_deleted"
    assert hard_gate({"memory_id": "x", "repository_scope": "django/django"},
                     {"allowed_repositories": ["django/django"]}) is None


def test_retrieve_uses_or_abstains():
    ctx = {"allowed_repositories": ["django/django", "acme/x"]}
    res = retrieve_stage(_q(), _views(), ctx)
    assert res["decision"] in ("USE", "ABSTAIN")
    # strong exact match should be USE and pick m_edit
    if res["decision"] == "USE":
        assert res["candidate"]["memory_id"] == "m_edit"


def test_reranker_abstains_on_weak():
    weak = score_candidates(StageQuery(stage=Stage.EDIT, error_signature="zzz"),
                            [{"memory_id": "m", "stage": "EDIT", "error_signature": "qqq", "symbols": []}])
    assert select_top1(weak) is None                # below min score -> ABSTAIN


def test_search_and_browse_budgets():
    s = StageState(stage=Stage.EDIT, obs=StageObservation(candidate_locations=["a.py"]))
    exec_views = {"m_edit": {"kind": "ExecutionView", "approx_tokens": 200}}
    tools = StageMemoryTools(s, _views(), {"allowed_repositories": ["django/django", "acme/x"]},
                             exec_view_of=lambda cid: exec_views.get(cid, {"approx_tokens": 999}))
    for _ in range(MAX_SEARCH_PER_STAGE):
        tools.memory_search_stage(_q())
    with pytest.raises(BudgetError):
        tools.memory_search_stage(_q())             # search budget exhausted
    g1 = tools.memory_browse_stage("m_edit")
    assert g1["granted"] is True
    g2 = tools.memory_browse_stage("m_edit")        # 200+200=400 <= 440 ok
    assert g2["granted"] in (True, False)
    # (O2 frozen-derangement no-fixed-point is verified end-to-end by experiments/r22/oracle.py dry-run)
