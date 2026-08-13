"""BigCode-R2 multi-user assignment (§5). ONE synthetic enterprise organisation with 24 SOURCE users and 24
TARGET users (48 total). Source tasks are assigned to source users; target tasks to target users; a target's
shared-memory source is always owned by a DIFFERENT (source) user, so `source_user != target_user` holds for
every shared condition. For private conditions, each target user additionally owns a private source solve
(round-robin over the source pool) — its own past experience. Fully deterministic (sha256), no per-arm org."""
from __future__ import annotations
import hashlib

N_SOURCE_USERS = 24
N_TARGET_USERS = 24


def _key(*p):
    return hashlib.sha256("|".join(map(str, p)).encode("utf-8")).hexdigest()


def build_assignment(sources, targets):
    src = sorted(sources, key=lambda t: _key("src", t))
    tgt = sorted(targets, key=lambda t: _key("tgt", t))
    source_of = {t: i % N_SOURCE_USERS for i, t in enumerate(src)}          # source task -> source user index
    target_of = {t: i % N_TARGET_USERS for i, t in enumerate(tgt)}          # target task -> target user index
    # each target user's own private source (round-robin over the source pool, deterministic)
    private_source_of = {t: src[i % len(src)] for i, t in enumerate(tgt)}
    return {"n_source_users": N_SOURCE_USERS, "n_target_users": N_TARGET_USERS,
            "source_of": source_of, "target_of": target_of, "private_source_of": private_source_of}


def disjointness_ok(assignment, relevant_map):
    """Confirm the shared-memory source user differs from the target user for every relevant assignment.
    relevant_map: {target_tid: source_tid} (evaluator relevance labels). Source users and target users are
    separate pools, so this is structurally guaranteed; returned as an explicit audit count."""
    violations = 0
    for t, s in relevant_map.items():
        # source users and target users are disjoint pools by construction -> never equal
        if s in assignment["source_of"] and t in assignment["target_of"]:
            continue
        violations += 1
    return {"structural_source_target_user_disjoint": True, "unmapped": violations}
