"""Frozen BigCodeBench partition (§4). Deterministic, computed BEFORE any model call, from the official task
universe only. Splits the 1140 official BigCodeBench-Full task IDs into disjoint sets:

  SOURCE_POOL 300 / RETRIEVAL_DEV 80 / MEMORY_DISCOVERY 120 / INSTRUMENT_CALIBRATION 80 /
  CONFIRMATORY_MAIN 500 / RESERVE 60.

Hard requirements: all pairwise set intersections are empty; no near-duplicate task pair (prompt-token
Jaccard >= NEAR_DUP_TAU) is split across the active sets — near-dup extras are quarantined into RESERVE so no
near-dup pair spans SOURCE and any target set. Function-name disjointness: BigCodeBench uses a single shared
harness entry-point name for (nearly) all tasks, so literal funcname disjointness is inapplicable; we record
the collision statistic and enforce SEMANTIC disjointness via near-dup exclusion instead (documented
deterministic adjustment, §4). No reference solution or test is exposed here."""
from __future__ import annotations
import hashlib
import json
import re

from experiments.bigcode_r2 import grader as G

NEAR_DUP_TAU = 0.7
SIZES = [("source", 300), ("retrieval_dev", 80), ("discovery", 120),
         ("calibration", 80), ("main", 500), ("reserve", 60)]
_TOKEN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]+")


def _tokens(text):
    return set(t.lower() for t in _TOKEN.findall(text or "") if len(t) > 2)


def _order_key(tid):
    return hashlib.sha256(("bcb-r2:" + tid).encode("utf-8")).hexdigest()


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _near_dup_extras(ids, toks):
    """Union-find near-dup clusters (Jaccard >= tau); return the set of non-representative task ids to
    quarantine to RESERVE so only pairwise-distinct representatives remain in the active sets. O(n^2) over
    1140 is fine (~650k comparisons)."""
    parent = {t: t for t in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)

    for i in range(len(ids)):
        ti = ids[i]
        for j in range(i + 1, len(ids)):
            tj = ids[j]
            if _jaccard(toks[ti], toks[tj]) >= NEAR_DUP_TAU:
                union(ti, tj)
    clusters = {}
    for t in ids:
        clusters.setdefault(find(t), []).append(t)
    extras = set()
    for members in clusters.values():
        if len(members) > 1:
            keep = sorted(members, key=_order_key)[0]      # deterministic representative
            extras.update(m for m in members if m != keep)
    return extras


def build_partition():
    ids = G.all_task_ids()
    toks = {t: _tokens(G.task(t)["instruct_prompt"]) for t in ids}
    extras = _near_dup_extras(ids, toks)
    # deterministic order; near-dup extras are forced into reserve first
    active = sorted([t for t in ids if t not in extras], key=_order_key)
    reserve_forced = sorted(extras, key=_order_key)

    out = {name: [] for name, _ in SIZES}
    i = 0
    for name, n in SIZES:
        if name == "reserve":
            continue
        out[name] = active[i:i + n]
        i += n
    # reserve = leftover active + all near-dup extras
    out["reserve"] = active[i:] + reserve_forced

    # funcname collision statistic (informational; shared-harness convention documented in the audit)
    eps = {t: G.task(t)["entry_point"] for t in ids}
    src_eps = set(eps[t] for t in out["source"])
    tgt_eps = set(eps[t] for name in ("discovery", "calibration", "main") for t in out[name])
    out["_meta"] = {
        "universe": len(ids), "near_dup_tau": NEAR_DUP_TAU, "near_dup_quarantined": len(reserve_forced),
        "funcname_collision_source_target": len(src_eps & tgt_eps),
        "distinct_entry_points": len(set(eps.values())),
        "shared_harness_note": "BigCodeBench uses a shared harness entry-point name; literal funcname "
                               "disjointness inapplicable -> semantic disjointness enforced via near-dup "
                               "exclusion (documented §4 adjustment).",
    }
    return out


def audit_partition(p):
    names = [n for n, _ in SIZES]
    sets = {n: set(p[n]) for n in names}
    overlaps = {}
    for a in range(len(names)):
        for b in range(a + 1, len(names)):
            na, nb = names[a], names[b]
            overlaps["%s_%s" % (na, nb)] = len(sets[na] & sets[nb])
    # near-dup across active sets: recompute among active representatives
    active_ids = [t for n in ("source", "retrieval_dev", "discovery", "calibration", "main") for t in p[n]]
    toks = {t: _tokens(G.task(t)["instruct_prompt"]) for t in active_ids}
    src = set(p["source"])
    tgts = set(p["discovery"]) | set(p["calibration"]) | set(p["main"])
    cross_near_dup = 0
    src_l = sorted(src)
    tgt_l = sorted(tgts)
    for s in src_l:
        for t in tgt_l:
            if _jaccard(toks.get(s, set()), toks.get(t, set())) >= NEAR_DUP_TAU:
                cross_near_dup += 1
    return {"overlaps_all_zero": all(v == 0 for v in overlaps.values()),
            "overlaps": overlaps,
            "sizes": {n: len(p[n]) for n in names},
            "source_target_near_dup_pairs": cross_near_dup,
            "funcname_collision_source_target": p["_meta"]["funcname_collision_source_target"],
            "near_dup_quarantined": p["_meta"]["near_dup_quarantined"]}


def split_hash(p):
    payload = {n: p[n] for n, _ in SIZES}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
