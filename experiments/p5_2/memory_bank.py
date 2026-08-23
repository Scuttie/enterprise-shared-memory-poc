"""P5.2 memory-bank builders (§5). The relevant memory is rendered from the family's convention (edge rule +
multiplier K) with the domain vocabulary + technique tag engineered so it out-ranks same-domain near-misses
and cross-domain irrelevant decoys under the deterministic embedder. Target-free: the memory carries K and the
rule, never the target's base*K edge value. Negative controls: wrong-rule (S4) uses a wrong K; expired /
out-of-scope are gated by validity / path before injection; relevant-absent (S1) seeds only decoys."""
from __future__ import annotations
import uuid

from enterprise_memory.contracts import schema as SS, codec
from experiments.p5_2 import tokens as T

_PAST_FROM = "2000-01-01"
_PAST_UNTIL = "2000-02-01"


def _arg(family):
    return family.target.exact_signature.split("(", 1)[1].rstrip(")")


def edge_content(family, K):
    t = family.target
    return ("edge rule: for the %s (%s >= %d) return the base multiplied by the edge multiplier %d; core "
            "behaviour is base * %s for smaller inputs" % (t.edge_name, _arg(family), t.edge_input, K, t.core_expr))


def _relevant_text(family, K, tag=None):
    return T.mem_text(family.domain, tag or family.tag, edge_content(family, K))


def private_canonical(family, target_repo):
    return {"private_note": _relevant_text(family, family.edge_multiplier), "domain": family.domain,
            "edge_multiplier": family.edge_multiplier, "tag": family.tag, "repo_id": target_repo}


def ungoverned_canonical(family):
    return {"summary": _relevant_text(family, family.edge_multiplier), "edge_multiplier": family.edge_multiplier,
            "domain": family.domain, "tag": family.tag, "kind": "shared_summary"}


def _contract(org_id, repo_id, domain, summary_text, *, path_globs=None, valid_from="2020-01-01",
              valid_until="", tag="t"):
    c = SS.MemoryContract(
        contract_id=str(uuid.uuid4()), schema_version=SS.SCHEMA_VERSION, title="%s edge convention" % domain,
        canonical_summary=summary_text,
        scope=SS.ContractScope(org_id=str(org_id), team_ids=[], repo_ids=[str(repo_id)],
                               path_globs=list(path_globs or []), language="python", framework="none",
                               dependency_version_constraints={}, branch_or_release_constraints=["main"],
                               error_signatures=[tag], applies_when=[T._DOMAIN_VOCAB[domain], tag],
                               does_not_apply_when=["a different codebase / edge convention"]),
        action=SS.ContractAction(ordered_steps=[summary_text], code_pattern="edge_multiplier",
                                 forbidden_patterns=[], required_inputs=[], operation_order=[]),
        validity=SS.ContractValidity(valid_from=valid_from, valid_until=valid_until, environment_constraints={},
                                     version_constraints={}, invalidation_events=[], supersedes_contract_ids=[],
                                     superseded_by_contract_id=""),
        verification=SS.ContractVerification(test_commands=["pytest"], expected_observations=["pass"],
                                             regression_checks=["noreg"], failure_observations=["fail"]),
        provenance=SS.ContractProvenance(source_episode_ids=["ep0"], contributor_user_ids_pseudonymized=["u0"],
                                         source_commit_shas=["s0"], source_test_results=["r0"],
                                         extractor_version="p5.2/1"),
        evidence=SS.ContractEvidence(), governance=SS.ContractGovernance(state="promoted", visibility="shared")
    ).stamp()
    return c


def governed_relevant(org_id, repo_id, family, *, form="shared_governed"):
    """The relevant governed contract for the family. form=governed_wrong uses a wrong K (prior-default-like);
    governed_out_of_scope path-scopes it away; governed_expired sets a past validity (DB columns at seed)."""
    if form == "governed_wrong":
        wrong_K = family.edge_multiplier + 1          # a plausible-but-wrong edge multiplier
        text = _relevant_text(family, wrong_K)
        return _contract(org_id, repo_id, family.domain, text, tag=family.tag), wrong_K
    text = _relevant_text(family, family.edge_multiplier)
    path_globs = ["docs/**"] if form == "governed_out_of_scope" else []
    return _contract(org_id, repo_id, family.domain, text, path_globs=path_globs, tag=family.tag), \
        family.edge_multiplier


def decoy_contract(org_id, repo_id, domain, tag):
    """A same-domain near-miss (domain matches, tag differs) or cross-domain irrelevant decoy that passes all
    hard metadata gates. Its content is generic and does not solve the target task."""
    text = T.mem_text(domain, tag, "edge rule: use the standard documented behaviour for this technique")
    return _contract(org_id, repo_id, domain, text, tag=tag)


def canonical_of(contract):
    return codec.encode_memory_contract(contract)
