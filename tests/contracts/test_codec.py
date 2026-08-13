"""Versioned canonical codec (P3.1 §1) + safe retrieval projection privacy (§2). Pure unit tests: no
database, no vector store, no network."""
import json
import os
import sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.contracts import schema as S            # noqa: E402
from enterprise_memory.contracts import codec                  # noqa: E402

SECRETS = ["ep_secret_1", "u_alice_SECRET", "deadbeefSECRET", "SECRET_TEST_LOG"]


def _contract():
    return S.MemoryContract(
        contract_id="c1", schema_version=S.SCHEMA_VERSION, title="Retry with backoff",
        canonical_summary="For internal API v2, retry once with backoff.",
        scope=S.ContractScope(org_id="orgA", team_ids=["t1"], repo_ids=["repoX"], path_globs=["src/**"],
                              language="python", framework="fastapi",
                              dependency_version_constraints={"api": ">=2"},
                              branch_or_release_constraints=["main"], error_signatures=["E_RETRY"],
                              applies_when=["api v2 timeout"], does_not_apply_when=["non-retryable"]),
        action=S.ContractAction(ordered_steps=["compute delay", "retry once"], code_pattern="retry(...)",
                                forbidden_patterns=["sleep(0)"], required_inputs=["retry_after"],
                                operation_order=["op"]),
        validity=S.ContractValidity(valid_from="2020-01-01", valid_until="", environment_constraints={},
                                    version_constraints={}, invalidation_events=[],
                                    supersedes_contract_ids=[], superseded_by_contract_id=""),
        verification=S.ContractVerification(test_commands=["pytest -q"], expected_observations=["passes"],
                                            regression_checks=["noreg"], failure_observations=["fails"]),
        provenance=S.ContractProvenance(source_episode_ids=["ep_secret_1"],
                                        contributor_user_ids_pseudonymized=["u_alice_SECRET"],
                                        source_commit_shas=["deadbeefSECRET"],
                                        source_test_results=["SECRET_TEST_LOG"], extractor_version="x/1"),
        evidence=S.ContractEvidence(),
        governance=S.ContractGovernance(state="promoted", visibility="shared")).stamp()


def test_encode_decode_roundtrip():
    c = _contract()
    d = codec.encode_memory_contract(c)
    c2 = codec.decode_memory_contract(d, S.SCHEMA_VERSION)
    assert c2.contract_id == "c1" and c2.scope.path_globs == ["src/**"]
    assert codec.validate_content_hash(c2, expected=c.content_hash)


def test_reject_absent_and_unknown_schema():
    d = codec.encode_memory_contract(_contract())
    with pytest.raises(codec.CodecError):
        codec.decode_memory_contract(d, "")
    with pytest.raises(codec.CodecError):
        codec.decode_memory_contract(d, "enterprise_memory/9.9.9")


def test_reject_malformed_and_missing_scope():
    d = codec.encode_memory_contract(_contract())
    bad = dict(d); bad.pop("scope")
    with pytest.raises(codec.CodecError):
        codec.decode_memory_contract(bad, S.SCHEMA_VERSION)
    bad2 = dict(d); bad2["action"] = {"ordered_steps": []}      # malformed action block
    with pytest.raises(codec.CodecError):
        codec.decode_memory_contract(bad2, S.SCHEMA_VERSION)


def test_content_hash_mismatch_detected():
    c = _contract()
    c.title = "tampered after stamping"
    with pytest.raises(codec.CodecError):
        codec.validate_content_hash(c)


def test_retrieval_projection_excludes_provenance():
    c = _contract()
    text = codec.retrieval_text(codec.encode_memory_contract(c))
    for secret in SECRETS:
        assert secret not in text                              # no provenance / hidden tests / identities
    assert "pytest -q" not in text                             # verification test_commands excluded
    proj = codec.build_retrieval_projection(c)
    # action/scope atoms are retained
    assert proj["path_globs"] == ["src/**"] and "retry once" in proj["steps"]
    assert proj["applies_when"] == ["api v2 timeout"] and proj["state"] == "promoted"


def test_retrieval_hash_distinct_from_content_hash():
    c = _contract()
    text = codec.retrieval_text(codec.encode_memory_contract(c))
    assert S.content_hash(c) != text and c.content_hash != text  # distinct + both traceable


def test_path_scope_from_scope_not_synthetic():
    d = codec.encode_memory_contract(_contract())
    assert codec.path_scope(d) == ["src/**"]                    # read from scope.path_globs
    scope = codec.extract_execution_scope(codec.decode_memory_contract(d, S.SCHEMA_VERSION))
    assert scope["path_globs"] == ["src/**"] and scope["language"] == "python"


def test_private_episode_decode_and_visibility():
    ep = S.PrivateEpisode(episode_id="e1", owner_user_id="u1", org_id="o1", repo_id="r1", task_id="t1",
                          source_commit="sha", request={}, retrieved_memory_ids=[], injected_memory_ids=[],
                          generated_patch="p", tool_events=[], test_commands=["pytest"],
                          test_results={"passed": True}, execution_outcome="success",
                          model_request_hashes=["h"], dependency_lock_hash="lk", created_at="2026").stamp()
    d = {k: getattr(ep, k) for k in S.PrivateEpisode.__dataclass_fields__}
    ep2 = codec.decode_private_episode(d, S.SCHEMA_VERSION)
    assert ep2.owner_user_id == "u1" and ep2.visibility == "private"
    d["visibility"] = "shared"
    with pytest.raises(codec.CodecError):
        codec.decode_private_episode(d, S.SCHEMA_VERSION)
