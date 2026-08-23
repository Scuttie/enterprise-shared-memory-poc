"""Frozen experiment plan (P5.1 §9/§12). Deterministically builds the full set of experiment cells (one per
family × arm) for a split, plus stable content hashes used by the freeze manifests and seal tests. No RNG,
no clock."""
from __future__ import annotations
import hashlib
import json

from benchmarks.p5_1_static import generate, generation_hash, GENERATOR_VERSION
from . import assignment as ASG
from . import arms as A

# stable per-task instruction (the client-visible natural-language request; NOT authoritative)
INSTRUCTION_TEMPLATE = ("Implement the function {symbol} in {path} so that all of the repository's tests pass. "
                        "Return only a unified diff patch.")

CALIBRATION = {"split": "calibration", "n_per_domain": 4, "n_users": 8}
MAIN = {"split": "main", "n_per_domain": 8, "n_users": 12}


def instruction_for(task):
    return INSTRUCTION_TEMPLATE.format(symbol=task.target_symbol, path=task.target_path)


def build_plan(experiment_id: str, split_cfg: dict, include_safety=False) -> dict:
    split, n_per_domain, n_users = split_cfg["split"], split_cfg["n_per_domain"], split_cfg["n_users"]
    fams = {f.family_id: f for f in generate(split, n_per_domain)}
    pool, cells = ASG.assign(split, n_per_domain, n_users, include_safety=include_safety)
    for c in cells:
        f = fams[c["family_id"]]
        c["instruction"] = instruction_for(f.target)
        c["target_symbol"] = f.target.target_symbol
        c["target_path"] = f.target.target_path
        c["exact_signature"] = f.target.exact_signature
        c["editable_paths"] = list(f.target.editable_paths)
        c["maximum_changed_lines"] = 40     # whole-file rewrite of a tiny stub -> a small diff; generous cap
        c["world_constant"] = f.world_constant
        c["prior_default"] = f.prior_default
        c["hidden_expected"] = f.target.hidden_expected
    return {
        "experiment_id": experiment_id, "split": split, "n_per_domain": n_per_domain, "n_users": n_users,
        "include_safety": include_safety, "generator_version": GENERATOR_VERSION,
        "benchmark_generation_hash": generation_hash(split, n_per_domain),
        "arms": [a.code for a in (A.PRIMARY + (A.SAFETY if include_safety else []))],
        "users": pool, "cells": cells,
    }


def plan_hash(plan: dict) -> str:
    h = hashlib.sha256()
    h.update(plan["generator_version"].encode())
    h.update(plan["benchmark_generation_hash"].encode())
    for c in sorted(plan["cells"], key=lambda x: x["cell_id"]):
        h.update(json.dumps({k: c[k] for k in ("cell_id", "arm", "target_user", "source_user",
                                               "target_task_id", "source_task_id", "memory_form",
                                               "instruction", "hidden_expected", "world_constant")},
                            sort_keys=True).encode())
    return h.hexdigest()
