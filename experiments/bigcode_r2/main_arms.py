"""BIGCODE-R2 confirmatory main arms M0-M7 (§10), parameterized by the discovery-selected representation.

Isolation within ONE org (§5): an org-global (repo NULL) shared bank in the SELECTED format serves M2/M3
(forced to a specific source via `oracle_id`) and M4/M5 (production retrieval). Repo-scoped shared memories
(readable only by their own target's repo, enforced by validated_search's repo-permission gate) carry the
plain/governed renderings for M6/M7 and the private own-source for M1. So arms never contaminate each other.

Cross-user: M2/M3/M4/M5/M6/M7 inject SHARED source knowledge authored by source-pool users into target-pool
users (source_user != target_user by construction). M1 injects the target's OWN prior source. No PRIVATE
memory of one user is ever injected into another user's job (cross_user_private_injection == 0)."""
from __future__ import annotations

PLAIN = "F1_PLAIN_LESSON"
GOVERNED = "F3_GOVERNED_COMPACT"


def arms(selected_format):
    """Return the 8 logical arms. `scope`/`source_kind`/`format` drive seeding; `dedup_of` marks an arm that
    is physically identical to another under this selected_format (§10 — run one physical arm, keep the
    logical mapping)."""
    A = [
        {"code": "M0", "name": "NO_MEMORY", "scope": "none", "source_kind": "none", "format": None},
        {"code": "M1", "name": "PRIVATE_SELECTED", "scope": "private", "source_kind": "own",
         "format": selected_format},
        {"code": "M2", "name": "TRUE_RELEVANT_SELECTED", "scope": "shared_oracle", "source_kind": "relevant",
         "format": selected_format},
        {"code": "M3", "name": "SHUFFLED_MATCHED_SELECTED", "scope": "shared_oracle", "source_kind": "shuffled",
         "format": selected_format},
        {"code": "M4", "name": "DEPLOYABLE_RETRIEVED_SELECTED", "scope": "shared_retrieval",
         "source_kind": "retrieved", "format": selected_format, "abstain": {"tau_abs": 0.30, "tau_margin": 0.0}},
        {"code": "M5", "name": "ALWAYS_INJECT_TOP1_SELECTED", "scope": "shared_retrieval",
         "source_kind": "retrieved", "format": selected_format, "abstain": {"tau_abs": 0.0, "tau_margin": 0.0}},
        {"code": "M6", "name": "RELEVANT_PLAIN_SAME_SOURCE", "scope": "shared_repo_oracle",
         "source_kind": "relevant", "format": PLAIN},
        {"code": "M7", "name": "RELEVANT_GOVERNED_SAME_SOURCE", "scope": "shared_repo_oracle",
         "source_kind": "relevant", "format": GOVERNED},
    ]
    # §10 dedup: if the selected representation IS plain/governed, the corresponding same-source arm duplicates
    # M2's content -> mark it as a logical alias of M2 (run one physical arm, no duplicate calls).
    for a in A:
        a["dedup_of"] = None
    if selected_format == PLAIN:
        _by(A, "M6")["dedup_of"] = "M2"
    if selected_format == GOVERNED:
        _by(A, "M7")["dedup_of"] = "M2"
    return A


def physical_arms(selected_format):
    return [a for a in arms(selected_format) if a["dedup_of"] is None]


def _by(A, code):
    return next(a for a in A if a["code"] == code)
