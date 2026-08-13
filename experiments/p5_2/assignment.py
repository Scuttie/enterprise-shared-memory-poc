"""P5.2 deterministic multi-user assignment (§9). Same invariants as P5.1 (source!=target for cross arms;
own-source==target for M1; every family in all primary arms), over the P5.2 strata families."""
from __future__ import annotations
import hashlib
import uuid

from benchmarks.p5_2_static import generate
from . import arms as A

_NS = uuid.UUID("7c2b9e1a-6d4f-4a3b-8e2c-9f1a0b3c4d5e")


def _h(*p):
    return int(hashlib.sha256("|".join(str(x) for x in p).encode()).hexdigest(), 16)


def users(split, n):
    return [str(uuid.uuid5(_NS, "user|%s|%d" % (split, i))) for i in range(n)]


def assign(split, n_per_domain, n_users, include_safety=True):
    fams = generate(split, n_per_domain)
    pool = users(split, n_users)
    arms = A.PRIMARY + (A.SAFETY if include_safety else [])
    cells = []
    for f in fams:
        ti = _h(split, f.family_id, "target") % n_users
        target_user = pool[ti]
        for arm in arms:
            if arm.code == "M0":
                su = None
            elif arm.source_role == "own_source":
                su = target_user
            else:
                off = 1 + (_h(split, f.family_id, arm.code) % (n_users - 1))
                su = pool[(ti + off) % n_users]
            cells.append({"cell_id": "%s|%s|%s" % (split, f.family_id, arm.code), "split": split,
                          "family_id": f.family_id, "domain": f.domain, "stratum": f.stratum,
                          "arm": arm.code, "arm_name": arm.name, "memory_form": arm.memory_form,
                          "retrieval_policy": dict(arm.retrieval_policy), "safety": arm.safety,
                          "target_user": target_user, "source_user": su,
                          "target_task_id": f.target.task_id, "target_repo": f.target.repo_fixture_id,
                          "tag": f.tag})
    return pool, cells


def validate_assignment(cells):
    cross = [c for c in cells if c["arm"] in ("M2", "M3", "M4", "S1", "S2", "S3", "S4")]
    m1 = [c for c in cells if c["arm"] == "M1"]
    m0 = [c for c in cells if c["arm"] == "M0"]
    from collections import defaultdict
    seen = defaultdict(set)
    for c in cells:
        seen[c["family_id"]].add(c["arm"])
    prim = {a.code for a in A.PRIMARY}
    return {"cells": len(cells),
            "cross_user_source_ne_target": all(c["source_user"] != c["target_user"] for c in cross),
            "m1_source_eq_target": all(c["source_user"] == c["target_user"] for c in m1),
            "m0_no_source": all(c["source_user"] is None for c in m0),
            "families_all_primary_arms": all(prim <= a for a in seen.values())}
