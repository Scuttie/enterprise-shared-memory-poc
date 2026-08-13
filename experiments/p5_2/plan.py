"""P5.2 frozen plan (§7). Deterministic cells (family x arm) + stable hashes. The client-visible instruction
carries the domain + technique tag so the competitive retrieval matches the relevant memory (never the arm)."""
from __future__ import annotations
import hashlib
import json

from benchmarks.p5_2_static import generate, generation_hash, GENERATOR_VERSION
from . import assignment as ASG, arms as A, tokens as T

CALIBRATION = {"split": "calibration", "n_per_domain": 4, "n_users": 8}
MAIN = {"split": "main", "n_per_domain": 8, "n_users": 12}
INSTRUMENT_DEV = {"split": "instrument_dev", "n_per_domain": 2, "n_users": 6}


def instruction_for(family):
    t = family.target
    return "%s Implement %s in %s so that all tests pass. Return only the full file." % (
        T.query_text(family.domain, family.tag), t.target_symbol, t.target_path)


def build_plan(experiment_id, cfg, include_safety=True):
    split, n, nu = cfg["split"], cfg["n_per_domain"], cfg["n_users"]
    fams = {f.family_id: f for f in generate(split, n)}
    pool, cells = ASG.assign(split, n, nu, include_safety=include_safety)
    for c in cells:
        f = fams[c["family_id"]]
        c["instruction"] = instruction_for(f)
        c["target_symbol"] = f.target.target_symbol
        c["target_path"] = f.target.target_path
        c["exact_signature"] = f.target.exact_signature
        c["editable_paths"] = list(f.target.editable_paths)
        c["maximum_changed_lines"] = 60
        c["edge_multiplier"] = f.edge_multiplier
        c["edge_value"] = f.target.edge_value
    return {"experiment_id": experiment_id, "split": split, "n_per_domain": n, "n_users": nu,
            "include_safety": include_safety, "generator_version": GENERATOR_VERSION,
            "benchmark_generation_hash": generation_hash(split, n),
            "arms": [a.code for a in (A.PRIMARY + (A.SAFETY if include_safety else []))],
            "tau_abs": A.TAU_ABS, "tau_margin": A.TAU_MARGIN, "users": pool, "cells": cells}


def plan_hash(plan):
    h = hashlib.sha256(); h.update(plan["generator_version"].encode())
    h.update(plan["benchmark_generation_hash"].encode()); h.update(("%s|%s" % (plan["tau_abs"], plan["tau_margin"])).encode())
    for c in sorted(plan["cells"], key=lambda x: x["cell_id"]):
        h.update(json.dumps({k: c[k] for k in ("cell_id", "arm", "stratum", "target_user", "source_user",
                                               "target_task_id", "memory_form", "instruction",
                                               "edge_multiplier")}, sort_keys=True).encode())
    return h.hexdigest()
