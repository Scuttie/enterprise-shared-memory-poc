"""Safe retrieval projection (P3.1 §2): a typed MemoryContract's index record embeds ONLY the target-free
retrieval view — never provenance, hidden tests, or identities. Pure (no DB / no server)."""
from enterprise_memory.contracts import schema as S
from enterprise_memory.contracts import codec
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.models import SHARED

SECRETS = ["ep_secret_1", "u_alice_SECRET", "deadbeefSECRET", "SECRET_TEST_LOG"]


def _contract():
    return S.MemoryContract(
        contract_id="c1", schema_version=S.SCHEMA_VERSION, title="Retry with backoff",
        canonical_summary="retry once with backoff",
        scope=S.ContractScope(org_id="orgA", team_ids=[], repo_ids=["repoX"], path_globs=["src/**"],
                              language="python", framework="fastapi", dependency_version_constraints={},
                              branch_or_release_constraints=["main"], error_signatures=["E_RETRY"],
                              applies_when=["api v2 timeout"], does_not_apply_when=["non-retryable"]),
        action=S.ContractAction(ordered_steps=["compute delay", "retry once"], code_pattern="",
                                forbidden_patterns=[], required_inputs=[], operation_order=[]),
        validity=S.ContractValidity(valid_from="2020-01-01", valid_until="", environment_constraints={},
                                    version_constraints={}, invalidation_events=[],
                                    supersedes_contract_ids=[], superseded_by_contract_id=""),
        verification=S.ContractVerification(test_commands=["pytest -q"], expected_observations=[],
                                            regression_checks=[], failure_observations=[]),
        provenance=S.ContractProvenance(source_episode_ids=["ep_secret_1"],
                                        contributor_user_ids_pseudonymized=["u_alice_SECRET"],
                                        source_commit_shas=["deadbeefSECRET"],
                                        source_test_results=["SECRET_TEST_LOG"], extractor_version="x/1"),
        evidence=S.ContractEvidence(),
        governance=S.ContractGovernance(state="promoted", visibility="shared")).stamp()


def test_typed_contract_projection_excludes_provenance():
    c = _contract()
    row = {"contract_id": "c1", "object_id": "v1", "version_number": 1, "content_hash": c.content_hash,
           "org_id": "orgA", "canonical": codec.encode_memory_contract(c), "repository_id": "repoX",
           "governance_state": "promoted", "valid_from": None, "valid_until": None}
    rec = build_record(SHARED, row)
    for secret in SECRETS:
        assert secret not in rec.text                     # no provenance / hidden tests in the embed text
    assert "pytest -q" not in rec.text                    # verification test commands excluded
    assert "retry once" in rec.text                       # action atoms retained
    assert rec.path_scope == ["src/**"]                   # path from scope.path_globs
    assert "text" not in rec.payload()                    # payload carries no embed text at all
    assert rec.retrieval_text_hash != c.content_hash      # projection hash distinct from content hash
