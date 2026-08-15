"""REALBENCH-R3 §6 — one shared synthetic enterprise organisation with disjoint source/target users.

24 source users + 24 target users in ONE org. Source users own the SOURCE_POOL solves; target users receive
shared/promoted memory in later phases. Because the two user sets are DISJOINT by construction, the invariant
source_user != target_user for every shared condition holds automatically. Private-memory controls give a target
user a DIFFERENT verified own-source task (a source solved under that user's own private identity), so private
memory never crosses users either.
"""
from __future__ import annotations

ORG_ID = "r3-acme"
N_SOURCE_USERS = 24
N_TARGET_USERS = 24


def source_users() -> list[str]:
    return ["r3-su-%02d" % i for i in range(N_SOURCE_USERS)]


def target_users() -> list[str]:
    return ["r3-tu-%02d" % i for i in range(N_TARGET_USERS)]


def private_user_for(target_user: str) -> str:
    """The private-memory identity that owns a target user's OWN verified source (never shared cross-user)."""
    return target_user + "-priv"


def assert_disjoint() -> None:
    s, t = set(source_users()), set(target_users())
    assert s.isdisjoint(t), "source/target user sets must be disjoint"
