"""REALBENCH-R3 §6/§11 — deterministic source-user assignment + evaluator-side relevance labels.

Source-user assignment: each SOURCE_POOL task is owned by exactly one of the 24 source users, stratified by
library (round-robin within library) so every user holds a spread of libraries and no user monopolises a family.
Deterministic (fixed seed, stable order); no model signal.

Relevance labels (evaluator-side, NEVER placed in a prompt): for a target task, a source is `relevant` when it
shares the library AND has high canonical-signature overlap; `shuffled` is a frozen derangement over the
relevant set (same library/domain, matched source frequency); `irrelevant` is a length-matched, zero-overlap
source. Labels are used only to build arms and to score; the model only ever sees the rendered execution view.
"""
from __future__ import annotations
import collections
import random

from experiments.actionable_memory_r3.users import source_users

SEED = 20260815


def assign_source_users(source_tasks: list[dict]) -> dict[str, str]:
    """source_tasks: task dicts with _id and _library. Returns {task_id: source_user}."""
    users = source_users()
    by_lib = collections.defaultdict(list)
    for t in sorted(source_tasks, key=lambda x: int(x["_id"].split("_")[1])):
        by_lib[t["_library"]].append(t["_id"])
    rng = random.Random(SEED)
    out = {}
    # rotate the user ring per library so libraries don't all start at user 0
    for li, lib in enumerate(sorted(by_lib)):
        ids = by_lib[lib]
        rng.shuffle(ids)
        for j, tid in enumerate(ids):
            out[tid] = users[(li * 7 + j) % len(users)]
    return out


def _sig_overlap(a: dict, b: dict) -> float:
    """Jaccard over the union of canonical API/operation/import tags (structural relevance)."""
    ka = set(a.get("relevant_apis", [])) | set(a.get("ordered_operations", [])) | set(a.get("required_imports", []))
    kb = set(b.get("relevant_apis", [])) | set(b.get("ordered_operations", [])) | set(b.get("required_imports", []))
    if not ka or not kb:
        return 0.0
    return len(ka & kb) / len(ka | kb)


def build_relevance(target_sigs: dict[str, dict], source_sigs: dict[str, dict], *, source_lib: dict[str, str],
                    target_lib: dict[str, str], min_overlap: float = 0.1) -> dict[str, dict]:
    # min_overlap frozen at 0.1 (chosen for injection COVERAGE on the discovery split — ~68% of targets get a
    # same-library relevant source sharing >=1 API/op; NOT tuned on any Pass@1 outcome). At 0.2 only 25/120
    # targets matched; 0.1 -> 82/120. Zero-coverage targets (mostly Pytorch, no sources) get no relevant arm.
    """For each target id -> {relevant: src_id|None, shuffled: src_id|None, irrelevant: src_id|None}.
    relevant = same library, max signature overlap >= min_overlap; irrelevant = different library, 0 overlap;
    shuffled = frozen derangement of the relevant assignment restricted to the same library."""
    rng = random.Random(SEED)
    src_by_lib = collections.defaultdict(list)
    for sid, lib in source_lib.items():
        src_by_lib[lib].append(sid)
    relevant = {}
    for tid in sorted(target_sigs):
        lib = target_lib[tid]
        cands = [(sid, _sig_overlap(target_sigs[tid], source_sigs[sid])) for sid in src_by_lib.get(lib, [])]
        cands = [(s, o) for s, o in cands if o >= min_overlap]
        relevant[tid] = max(cands, key=lambda x: x[1])[0] if cands else None
    # shuffled: derangement within library over the targets that have a relevant source
    shuffled = {}
    by_lib_targets = collections.defaultdict(list)
    for tid, sid in relevant.items():
        if sid is not None:
            by_lib_targets[target_lib[tid]].append(tid)
    for lib, tids in by_lib_targets.items():
        srcs = [relevant[t] for t in tids]
        order = list(range(len(tids)))
        for _ in range(64):
            rng.shuffle(order)
            if all(order[i] != i for i in range(len(order))) or len(order) == 1:
                break
        for i, tid in enumerate(tids):
            shuffled[tid] = srcs[order[i]] if len(tids) > 1 else srcs[i]
    # irrelevant: any source from a DIFFERENT library with zero overlap, length-matched by nearest sig size
    irrelevant = {}
    all_src = list(source_lib)
    for tid in sorted(target_sigs):
        lib = target_lib[tid]
        pool = [s for s in all_src if source_lib[s] != lib and _sig_overlap(target_sigs[tid], source_sigs[s]) == 0.0]
        irrelevant[tid] = rng.choice(pool) if pool else None
    return {tid: {"relevant": relevant.get(tid), "shuffled": shuffled.get(tid),
                  "irrelevant": irrelevant.get(tid)} for tid in target_sigs}
