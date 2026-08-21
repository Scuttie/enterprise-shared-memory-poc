"""P6/R19 §7 — progressive search + gated browse: metadata-only search, router-gated injection, budgets, shadow,
idempotency, and searchable-state / tenant / repository isolation."""
from enterprise_memory.experience import SourceEvidence, Bank, SourceOutcome, GovernanceState, compile_card
from enterprise_memory.agentic import InMemoryExperienceStore, MemorySearchService, SearchSession, tools
from enterprise_memory.router import TaskContext, TrajectoryState


def _card(repo="django/django", state=GovernanceState.PROMOTED, symbols=None, apis=None, actions=True, outcome="passed"):
    ev = SourceEvidence(
        bank=Bank.HISTORICAL_VERIFIED, source_type="issue_fix", source_repository=repo, source_commit="c",
        source_issue_id="1", source_author_id="u1", source_timestamp="2020-01-01T00:00:00Z",
        source_outcome=SourceOutcome.PASSED if outcome == "passed" else SourceOutcome.UNKNOWN,
        symptom_signature="migration loader namespace package __file__ missing",
        root_cause="loader assumes __file__", fault_localization="django/db/migrations/loader.py",
        affected_symbols=symbols if symbols is not None else ["MigrationLoader.load_disk"],
        affected_apis=apis if apis is not None else ["importlib"],
        repair_strategy="guard for missing __file__", ordered_actions=["add guard"] if actions else [],
        patch_pattern="if getattr(m,'__file__',None) is None:" if actions else "",
        validation_strategy="run migration tests", language="python", framework="django", confidence=0.7)
    card = compile_card(ev)
    card.governance_state = state
    return card


def _store():
    s = InMemoryExperienceStore()
    c = _card()
    s.add("o1", "v1", c)
    return s, c


def _task(**kw):
    base = dict(org_id="o1", repository="django/django", subtask="modification",
                target_apis=["importlib"], target_symbols=["MigrationLoader.load_disk"],
                error_signature="loader namespace package __file__ missing", version="")
    base.update(kw)
    return TaskContext(**base)


def _sess(mode="utility_gated", **kw):
    return SearchSession(session_id="s1", org_id="o1", request_id="r1", actor_id_hash="h",
                         target_task_id="t1", mode=mode, **kw)


def test_search_is_metadata_only():
    store, _ = _store()
    svc = MemorySearchService(store)
    res = svc.search_experiences(_sess(), _task(), "namespace package migration loader")
    assert res and "execution_view" not in res[0]
    for forbidden in ("ordered_repair_operations", "patch_pattern", "raw_diff", "root_cause"):
        assert forbidden not in res[0]
    assert res[0]["version_id"] == "v1"


def test_browse_injects_on_use():
    store, _ = _store()
    svc = MemorySearchService(store)
    sess = _sess()
    cands = store.search("o1", "django/django", "namespace loader __file__")
    view = svc.browse_experience(sess, _task(), TrajectoryState(), cands[0])
    assert view is not None
    assert view["fault_localization"] == "django/db/migrations/loader.py"
    assert "raw_diff" not in view
    assert sess.browsed_keys == [cands[0].card_key]
    assert sess.injected_tokens > 0


def test_browse_blocked_on_abstain_wrong_repo():
    store, _ = _store()
    svc = MemorySearchService(store)
    sess = _sess()
    cands = store.search("o1", "django/django", "namespace loader")
    # task in a different repo -> router ABSTAIN_SCOPE -> no injection
    view = svc.browse_experience(sess, _task(repository="flask/flask"), TrajectoryState(), cands[0])
    assert view is None and sess.browsed_keys == []


def test_shadow_mode_injects_nothing():
    store, _ = _store()
    svc = MemorySearchService(store)
    sess = _sess(mode="shadow")
    cands = store.search("o1", "django/django", "namespace loader __file__")
    view = svc.browse_experience(sess, _task(), TrajectoryState(), cands[0])
    assert view is None
    assert any(e["kind"] == "browse_shadow" for e in sess.audit)
    assert sess.injected_tokens == 0


def test_idempotent_rebrowse():
    store, _ = _store()
    svc = MemorySearchService(store)
    sess = _sess()
    cands = store.search("o1", "django/django", "namespace loader __file__")
    assert svc.browse_experience(sess, _task(), TrajectoryState(), cands[0]) is not None
    # re-browsing same card -> noop (already tried -> ABSTAIN_ALREADY_TRIED before injection)
    again = svc.browse_experience(sess, _task(), TrajectoryState(), cands[0])
    assert again is None and len(sess.browsed_keys) == 1


def test_token_budget_enforced():
    store, _ = _store()
    svc = MemorySearchService(store)
    sess = _sess(max_injected_tokens=1)  # too small to fit any execution view
    cands = store.search("o1", "django/django", "namespace loader __file__")
    view = svc.browse_experience(sess, _task(), TrajectoryState(), cands[0])
    assert view is None
    assert any(e["kind"] == "browse_token_budget_exhausted" for e in sess.audit)


def test_quarantined_not_searchable():
    s = InMemoryExperienceStore()
    s.add("o1", "v1", _card(state=GovernanceState.QUARANTINED))
    assert s.search("o1", "django/django", "namespace loader") == []


def test_tenant_isolation_in_search():
    s = InMemoryExperienceStore()
    s.add("o1", "v1", _card())
    assert s.search("o2", "django/django", "namespace loader") == []  # different org sees nothing


def test_agentic_reference_mode_ungated():
    store, _ = _store()
    svc = MemorySearchService(store)
    sess = _sess(mode="agentic_reference")
    cands = store.search("o1", "django/django", "namespace loader __file__")
    # ungated reference approves a verified promoted card even in a different repo? scope still not enforced by router
    view = svc.browse_experience(sess, _task(), TrajectoryState(), cands[0])
    assert view is not None  # reference policy injects verified cards


def test_tool_contracts_present():
    assert tools.TOOL_NAMES == ["search_experiences", "browse_experience", "report_memory_outcome",
                                "memory_explain_decision"]
