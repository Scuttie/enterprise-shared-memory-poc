"""R22 §5/§8/§9 — StageMemoryRecord schema, compiler, views, outcomes (credential-free)."""
import pytest

from enterprise_memory.experience.schema import GovernanceState
from enterprise_memory.experience.stage_schema import (
    Stage, StageMemoryRecord, StageTrigger, StageTransition, StageAction, StageVerification,
    assert_no_target_leakage, record_hash, SCHEMA_VERSION,
)
from enterprise_memory.experience.stage_compiler import compile_stage_record, coverage_report, UNKNOWN
from enterprise_memory.experience.stage_views import (
    episodic_precedent, semantic_recipe, search_index_view, execution_view, EXEC_TOKEN_BUDGET,
)
from enterprise_memory.experience.stage_outcomes import next_state, classify_adoption, AdoptionClass


def _rec():
    return compile_stage_record(
        source_task_id="django__django-12345", source_repository="django/django",
        source_commit="abc123", source_user_id="user_a", source_timestamp="2023-01-01T00:00:00Z",
        source_outcome="resolved", verifier_hash="vh", stage=Stage.EDIT,
        trigger=StageTrigger(error_signature="AttributeError: get_context",
                             affected_symbols=["CheckboxInput.get_context"], language="python",
                             violated_contract="must not mutate shared attrs"),
        transition=StageTransition(observation_before="attrs copied at wrong layer",
                                   attempted_action="copy attrs in parent widget",
                                   failure_reason="only some combos fixed",
                                   successful_action="defensive copy at method entry"),
        action=StageAction(operation_type="defensive_copy", ordered_steps=["copy attrs", "return"],
                           preconditions=["attrs shared"], non_applicability=["attrs already local"]),
        verification=StageVerification(command_type="pytest -k checkbox"),
        patch_artifact_id="patch:xyz", confidence=0.7,
    )


def test_round_trip_and_deterministic_hash():
    r = _rec()
    assert r.schema_version == SCHEMA_VERSION
    d = r.to_dict()
    r2 = StageMemoryRecord.from_dict(d)
    assert record_hash(r) == record_hash(r2)          # round trip is hash-stable
    assert record_hash(r) == record_hash(_rec())      # same source -> same hash (deterministic)
    assert r.identity.memory_id == _rec().identity.memory_id


def test_empty_core_refused():
    with pytest.raises(ValueError):
        compile_stage_record(
            source_task_id="t", source_repository="r", source_commit="c", source_user_id="u",
            source_timestamp="2023", source_outcome="resolved", verifier_hash="v", stage=Stage.EDIT,
            trigger=StageTrigger(),  # no signal
        )


def test_target_leakage_sentinel():
    assert_no_target_leakage(_rec().to_dict())               # clean record passes
    with pytest.raises(ValueError):
        assert_no_target_leakage({"identity": {"target_patch": "diff"}})
    with pytest.raises(ValueError):
        assert_no_target_leakage({"nested": [{"fail_to_pass": "test_x"}]})


def test_search_index_view_is_metadata_only():
    v = search_index_view(_rec())
    assert v["stage"] == "EDIT" and v["content_hash"]
    blob = str(v).lower()
    for banned in ("defensive copy at method entry", "patch:xyz", "user_a", "resolved"):
        assert banned.lower() not in blob, "search index leaked %r" % banned


def test_execution_view_token_cap_and_no_raw_diff_by_default():
    v = execution_view(_rec())
    assert v["approx_tokens"] <= EXEC_TOKEN_BUDGET
    assert "_oracle_raw_diff_ref" not in v                    # raw diff withheld by default
    vo = execution_view(_rec(), include_raw_diff=True)
    assert vo["_oracle_raw_diff_ref"] == "patch:xyz"          # oracle-only reference


def test_views_carry_no_forbidden_keys():
    for v in (episodic_precedent(_rec()), semantic_recipe(_rec()),
              search_index_view(_rec()), execution_view(_rec())):
        assert_no_target_leakage(v)


def test_governance_transitions():
    assert next_state(GovernanceState.CANDIDATE, 0, 0, False) == GovernanceState.PROBATION
    assert next_state(GovernanceState.PROBATION, 2, 0, True) == GovernanceState.PROMOTED
    assert next_state(GovernanceState.PROBATION, 2, 0, False) == GovernanceState.PROBATION  # needs manual review
    assert next_state(GovernanceState.PROBATION, 0, 2, True) == GovernanceState.QUARANTINED


def test_adoption_classification():
    assert classify_adoption(s3_pass=True, s4_pass=False, s5_pass=False,
                             patch_hash_changed=True, memory_op_matches_patch_ast=True) == AdoptionClass.ACTION_ADOPTED
    assert classify_adoption(s3_pass=True, s4_pass=False, s5_pass=False,
                             patch_hash_changed=True, memory_op_matches_patch_ast=False) == AdoptionClass.CONTENT_SPECIFIC_GAIN
    assert classify_adoption(s3_pass=False, s4_pass=True, s5_pass=True,
                             patch_hash_changed=True, memory_op_matches_patch_ast=False) == AdoptionClass.DISTRACTION


def test_coverage_report():
    rep = coverage_report([_rec()])
    assert rep["records"] == 1 and rep["by_stage"]["EDIT"] == 1
    assert rep["missing_operation_type"] == 0
