"""Deterministic multi-user assignment (P5.1 §9). Synthetic UUID users; each target family appears in every
primary arm; source_user != target_user for cross-user arms; own-source user == target user for M1. Fully
deterministic (uuid5 + SHA-256), no RNG/clock, so the frozen assignment regenerates bit-identically."""
from __future__ import annotations
import hashlib
import uuid

from benchmarks.p5_1_static import generate
from . import arms as A

_NS = uuid.UUID("9f1c8b2a-4d3e-5f6a-8b7c-1a2b3c4d5e6f")


def _h(*parts) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest(), 16)


def users(split: str, n: int):
    return [str(uuid.uuid5(_NS, "user|%s|%d" % (split, i))) for i in range(n)]


def assign(split: str, n_per_domain: int, n_users: int, include_safety=False):
    """Return (users, cells). Each cell is one (family, arm) unit with its target/source users + tasks."""
    fams = generate(split, n_per_domain)
    pool = users(split, n_users)
    arms = A.PRIMARY + (A.SAFETY if include_safety else [])
    cells = []
    for f in fams:
        ti = _h(split, f.family_id, "target") % n_users
        target_user = pool[ti]
        for arm in arms:
            if arm.code == "M0":
                source_user, source_task = None, None
            elif arm.source_role == "own_source":
                source_user, source_task = target_user, f.own_source.task_id   # own-source == target user
            else:
                # a DIFFERENT source user for every cross-user arm
                off = 1 + (_h(split, f.family_id, arm.code) % (n_users - 1))
                source_user = pool[(ti + off) % n_users]
                source_task = f.cross_source.task_id
            cells.append({
                "cell_id": "%s|%s|%s" % (split, f.family_id, arm.code),
                "split": split, "family_id": f.family_id, "domain": f.domain, "arm": arm.code,
                "arm_name": arm.name, "memory_form": arm.memory_form, "oracle": arm.oracle,
                "safety": arm.safety, "retrieval_policy": arm.retrieval_policy,
                "target_user": target_user, "source_user": source_user,
                "target_task_id": f.target.task_id, "source_task_id": source_task,
                "target_repo": f.target.repo_fixture_id,
                "source_repo": (f.own_source.repo_fixture_id if arm.source_role == "own_source"
                                else f.cross_source.repo_fixture_id) if arm.code != "M0" else None,
            })
    return pool, cells


def validate_assignment(cells) -> dict:
    """Assignment invariants (§9)."""
    cross = [c for c in cells if c["arm"] in ("M2", "M3", "M4", "S1", "S2", "S3", "S4")]
    m1 = [c for c in cells if c["arm"] == "M1"]
    m0 = [c for c in cells if c["arm"] == "M0"]
    return {
        "cells": len(cells),
        "cross_user_source_ne_target": all(c["source_user"] != c["target_user"] for c in cross),
        "m1_source_eq_target": all(c["source_user"] == c["target_user"] for c in m1),
        "m0_no_source": all(c["source_user"] is None for c in m0),
        "source_target_task_disjoint": all(c["source_task_id"] != c["target_task_id"]
                                           for c in cells if c["source_task_id"]),
        "families_all_primary_arms": _all_primary(cells),
    }


def _all_primary(cells):
    from collections import defaultdict
    seen = defaultdict(set)
    for c in cells:
        seen[c["family_id"]].add(c["arm"])
    prim = {a.code for a in A.PRIMARY}
    return all(prim <= arms for arms in seen.values())
