"""P6/R19 §6 — card compiler + projection leakage guarantees."""
import pytest

from enterprise_memory.experience import (
    SourceEvidence, Bank, SourceOutcome, GovernanceState,
    compile_card, retrieval_projection, execution_view, compile_all, CompileError,
)


def _ev(**kw):
    base = dict(
        bank=Bank.HISTORICAL_VERIFIED, source_type="issue_fix", source_repository="django/django",
        source_commit="abc123", source_issue_id="12663", source_author_id="u07",
        source_timestamp="2020-01-01T00:00:00Z", source_outcome=SourceOutcome.PASSED,
        source_verifier_hash="v-hash", symptom_signature="migration loader rejects namespace packages",
        root_cause="loader assumes __file__ present", fault_localization="django/db/migrations/loader.py",
        affected_symbols=["MigrationLoader.load_disk"], affected_apis=["importlib"],
        repair_strategy="guard for packages without __file__.", ordered_actions=["locate loader", "add guard"],
        patch_pattern="if getattr(module, '__file__', None) is None: ...", validation_strategy="run migration tests",
        language="python", framework="django", raw_diff="diff --git a/django/db/migrations/loader.py b/...",
        evidence_hashes=["h1"], confidence=0.7,
    )
    base.update(kw)
    return SourceEvidence(**base)


def test_compile_deterministic():
    a = compile_card(_ev())
    b = compile_card(_ev())
    assert a.content_hash == b.content_hash
    assert a.card_key == b.card_key
    assert a.governance_state == GovernanceState.CANDIDATE  # never born promoted


def test_retrieval_projection_is_neutral():
    card, proj, _ = compile_all(_ev())
    # forbidden fields absent
    for k in ("patch_pattern", "ordered_actions", "repair_strategy", "source_author_id",
              "source_verifier_hash", "evidence_hashes", "source_outcome", "raw_diff"):
        assert k not in proj, k
    # no raw diff text anywhere in projection values
    assert not any(isinstance(v, str) and "diff --git" in v for v in proj.values())
    # useful neutral fields present
    assert proj["repository_scope"] == "django/django"
    assert proj["framework"] == "django"
    assert "symptom_signature" in proj


def test_execution_view_actionable_no_diff():
    card, _, view = compile_all(_ev())
    assert view["ordered_repair_operations"] == ["locate loader", "add guard"]
    assert view["fault_localization"] == "django/db/migrations/loader.py"
    assert "raw_diff" not in view and "patch" not in view
    assert "diff --git" not in str(view)


def test_empty_evidence_rejected():
    with pytest.raises(CompileError):
        compile_card(_ev(symptom_signature="", root_cause="", repair_strategy=""))


def test_missing_repo_rejected():
    with pytest.raises(CompileError):
        compile_card(_ev(source_repository=""))
