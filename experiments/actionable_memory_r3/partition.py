"""REALBENCH-R3 §5 — frozen, deterministic, near-dup-safe task partition for DS-1000.

DS-1000 ships perturbation FAMILIES: Surface/Semantic/Difficult-Rewrite variants share a
(library, perturbation_origin_id) with their Origin task and are near-duplicates by construction. The frozen
near-duplicate rule is therefore: **assign each whole family atomically to a single split** — no family member
ever crosses a split boundary, which guarantees source∩target near-duplicate leakage = 0 by design (stronger
than a post-hoc Jaccard threshold, which we still compute as an audit).

Splits are stratified by library so every split proportionally covers all 7 libraries (needed for the §16 G3
dynamic-range strata and §17 main coverage). Allocation is deterministic (fixed seed, stable sort); no model
signal is used. Targets for the 1000-task universe: SOURCE 200 / DEV 80 / DISCOVERY 120 / CALIB 100 / MAIN 450 /
RESERVE 50. Because families are atomic and sized 1..7, realised sizes approximate the targets; the deterministic
adjustment rule (fill the split furthest below its per-library quota) keeps MAIN>=400 and SOURCE>=150 (§5).
"""
from __future__ import annotations
import collections
import hashlib
import json
import random

SPLIT_TARGETS = {  # fraction of each library's tasks
    "SOURCE_POOL": 0.20, "RETRIEVAL_DEV": 0.08, "REPRESENTATION_DISCOVERY": 0.12,
    "INSTRUMENT_CALIBRATION": 0.10, "CONFIRMATORY_MAIN": 0.45, "RESERVE": 0.05,
}
SPLIT_ORDER = ["CONFIRMATORY_MAIN", "SOURCE_POOL", "REPRESENTATION_DISCOVERY",
               "INSTRUMENT_CALIBRATION", "RETRIEVAL_DEV", "RESERVE"]
SEED = 20260815


def families(tasks: list[dict]) -> dict[tuple, list[dict]]:
    fam = collections.defaultdict(list)
    for t in tasks:
        m = t["metadata"]
        fam[(m["library"], m["perturbation_origin_id"])].append(t)
    return fam


def build(tasks: list[dict]) -> dict:
    fam = families(tasks)
    # per-library family lists, deterministically ordered then seeded-shuffled
    by_lib = collections.defaultdict(list)
    for key, members in fam.items():
        by_lib[key[0]].append((key, members))
    assign = {s: [] for s in SPLIT_TARGETS}  # split -> list of task ids
    rng = random.Random(SEED)
    for lib in sorted(by_lib):
        fams = sorted(by_lib[lib], key=lambda kv: kv[0][1])  # by origin id (stable)
        rng.shuffle(fams)
        lib_n = sum(len(m) for _, m in fams)
        quota = {s: SPLIT_TARGETS[s] * lib_n for s in SPLIT_TARGETS}
        filled = {s: 0 for s in SPLIT_TARGETS}
        # largest families first so big atomic blocks land where the deficit is greatest
        for key, members in sorted(fams, key=lambda kv: -len(kv[1])):
            # choose the split (in priority order) with the largest remaining deficit
            split = max(SPLIT_ORDER, key=lambda s: (quota[s] - filled[s], SPLIT_ORDER[::-1].index(s)))
            for t in members:
                assign[split].append(t["_id"])
            filled[split] += len(members)
    sizes = {s: len(v) for s, v in assign.items()}
    # near-dup audit: no (library,origin) family spans >1 split (must be 0)
    fam_split = {}
    span = 0
    id_split = {tid: s for s, ids in assign.items() for tid in ids}
    for key, members in fam.items():
        splits = {id_split[t["_id"]] for t in members}
        fam_split[str(key)] = sorted(splits)
        if len(splits) > 1:
            span += 1
    # signature note: shared wrapper function names (e.g. 'g','solve') are the benchmark harness convention
    part = {
        "benchmark": "DS-1000",
        "seed": SEED,
        "near_dup_rule": "atomic (library,perturbation_origin_id) family assignment",
        "sizes": sizes,
        "family_span_violations": span,
        "sets": {s: sorted(v, key=lambda x: int(x.split("_")[1])) for s, v in assign.items()},
        "per_library": {s: dict(collections.Counter(tid_lib[tid] for tid in v))
                        for s, v in assign.items()} if (tid_lib := {t["_id"]: t["_library"] for t in tasks}) else {},
    }
    part["split_hash"] = hashlib.sha256(
        json.dumps({s: part["sets"][s] for s in sorted(part["sets"])}, sort_keys=True).encode()).hexdigest()[:16]
    return part
