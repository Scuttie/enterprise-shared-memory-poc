"""Memory-bank canonical builders (P5.1 §7). Every memory form is rendered from the SAME source fact (the
family's reusable convention) so arm differences are governance/rendering, not content. All forms are
target-free: they carry the convention constant C, never the target's answer. Negative controls are built
separately (stale / out-of-scope / irrelevant / wrong reusable pattern)."""
from __future__ import annotations
import uuid

from enterprise_memory.contracts import schema as SS, codec

# a fixed past window for the 'expired' control (deterministic; no clock)
_PAST_FROM = "2000-01-01"
_PAST_UNTIL = "2000-02-01"


def private_canonical(family, target_repo):
    """The target user's own verified private source note (feeds M1). Contains the convention, not the answer."""
    return {"private_note": family.technique_note, "task_id": family.target.task_id,
            "repo_id": target_repo, "convention_constant": family.world_constant, "domain": family.domain}


def ungoverned_canonical(family):
    """A concise cross-user shared SUMMARY with only basic metadata (feeds M2). Legacy (untyped) canonical."""
    return {"summary": family.technique_note, "convention_constant": family.world_constant,
            "domain": family.domain, "kind": "shared_summary"}


def _contract(org_id, repo_id, family, *, constant, summary, path_globs=None, valid_from="2020-01-01",
              valid_until="", applies_when=None, does_not_apply_when=None):
    c = SS.MemoryContract(
        contract_id=str(uuid.uuid4()), schema_version=SS.SCHEMA_VERSION,
        title="%s convention" % family.domain,
        canonical_summary="%s The convention constant is %d." % (summary, constant),
        scope=SS.ContractScope(org_id=str(org_id), team_ids=[], repo_ids=[str(repo_id)],
                               path_globs=list(path_globs or []), language="python", framework="none",
                               dependency_version_constraints={}, branch_or_release_constraints=["main"],
                               error_signatures=["E_%s" % family.domain.upper()],
                               applies_when=applies_when or ["completing a %s function" % family.domain],
                               does_not_apply_when=does_not_apply_when or ["a different codebase/convention"]),
        action=SS.ContractAction(ordered_steps=["apply the convention constant %d in the %s computation"
                                                % (constant, family.domain)],
                                 code_pattern="constant=%d" % constant, forbidden_patterns=[],
                                 required_inputs=[], operation_order=[]),
        validity=SS.ContractValidity(valid_from=valid_from, valid_until=valid_until,
                                     environment_constraints={}, version_constraints={},
                                     invalidation_events=[], supersedes_contract_ids=[],
                                     superseded_by_contract_id=""),
        verification=SS.ContractVerification(test_commands=["pytest"], expected_observations=["pass"],
                                             regression_checks=["noreg"], failure_observations=["fail"]),
        provenance=SS.ContractProvenance(source_episode_ids=["ep0"],
                                         contributor_user_ids_pseudonymized=["u0"],
                                         source_commit_shas=["sha0"], source_test_results=["r0"],
                                         extractor_version="p5.1/1"),
        evidence=SS.ContractEvidence(),
        governance=SS.ContractGovernance(state="promoted", visibility="shared")).stamp()
    return c


def governed_contract(org_id, repo_id, family, form: str):
    """Return a typed MemoryContract for the given governed form. Forms:
      shared_governed         -> the correct convention, valid + in-scope (M3/M4)
      negative_irrelevant     -> a valid, in-scope contract about an UNRELATED convention (S1)
      negative_expired        -> the correct convention but past its validity window (S2)
      negative_out_of_scope   -> the correct convention but path-scoped away from the target (S3)
      negative_wrong_pattern  -> a valid, in-scope contract asserting the WRONG (prior-default) constant (S4)
    """
    if form == "shared_governed":
        return _contract(org_id, repo_id, family, constant=family.world_constant,
                         summary="Use the codebase convention.")
    if form == "negative_irrelevant":
        return _contract(org_id, repo_id, family, constant=family.world_constant + 1000,
                         summary="An unrelated logging/formatting convention.",
                         applies_when=["writing unrelated log formatting"],
                         does_not_apply_when=["computing %s values" % family.domain])
    if form == "negative_expired":
        return _contract(org_id, repo_id, family, constant=family.world_constant,
                         summary="Use the codebase convention.", valid_from=_PAST_FROM,
                         valid_until=_PAST_UNTIL)
    if form == "negative_out_of_scope":
        return _contract(org_id, repo_id, family, constant=family.world_constant,
                         summary="Use the codebase convention.", path_globs=["docs/**"])
    if form == "negative_wrong_pattern":
        return _contract(org_id, repo_id, family, constant=family.prior_default,
                         summary="Use the (incorrect) common default.")
    raise ValueError("unknown governed form %r" % form)


def canonical_of(contract):
    return codec.encode_memory_contract(contract)
