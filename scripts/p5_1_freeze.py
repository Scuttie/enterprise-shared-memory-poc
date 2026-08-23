"""Preregistration freeze for the P5.1 static multi-user experiment (§12). Deterministically writes the
freeze manifests, configs, and model lock. Everything here is a pure function of the frozen generator +
assignment + arms + prompt/compiler source, so re-running reproduces byte-identical manifests. Run BEFORE any
calibration model call; the seal tests then fail if any frozen input changes."""
import hashlib
import inspect
import json
import os

from experiments.p5_1 import plan as PLAN, arms as A, memory_bank as MB
from experiments.p5_1.plan import CALIBRATION, MAIN
from experiments.p5_1.manifest import prompt_manifest

ART = os.path.join("artifacts", "experiments", "p5_1")
CFG = os.path.join("configs", "experiments")

MODEL_LOCK = {
    "backend": "solar", "base_url": "https://api.upstage.ai/v1/solar", "model": "solar-pro2-251215",
    "temperature": 0, "top_p": 1.0, "max_output_tokens": 1024, "attempts": 1, "repair_in_primary": False,
    "sandbox": {"kind": "controlled_local", "grading": "hidden_test", "timeout_s": 20},
}

STOP_RULES = {
    "calibration_gates": ["G1_executability", "G2_dynamic_range", "G3_memory_necessity", "G4_retrieval",
                          "G5_safety", "G6_instrument_consistency"],
    "primary_endpoint": "CrossUserLift = Pass@1(M3) - Pass@1(M0), paired by family",
    "primary_success": "mean paired lift >= +0.05 AND family-cluster bootstrap 95% CI lower bound > 0",
    "no_edit_after_results": True,
}


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _src_hash(*objs):
    h = hashlib.sha256()
    for o in objs:
        h.update(inspect.getsource(o).encode("utf-8"))
    return h.hexdigest()


def _write(path, obj):  # noqa
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")
    return _sha(json.dumps(obj, sort_keys=True))


def _yaml(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    for k, v in obj.items():
        lines.append("%s: %s" % (k, json.dumps(v)))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def task_manifest(cal, main):
    return {"generator_version": cal["generator_version"],
            "calibration": {"generation_hash": cal["benchmark_generation_hash"],
                            "families": sorted({c["family_id"] for c in cal["cells"]})},
            "main": {"generation_hash": main["benchmark_generation_hash"],
                     "families": sorted({c["family_id"] for c in main["cells"]})}}


def main():
    cal = PLAN.build_plan("EXP_P5_1_CAL", CALIBRATION, include_safety=True)
    main = PLAN.build_plan("EXP_P5_1_MAIN", MAIN, include_safety=True)
    pm = prompt_manifest()

    ua = {"calibration_users": cal["users"], "main_users": main["users"]}
    stp = {"calibration": [{"cell_id": c["cell_id"], "arm": c["arm"], "target_user": c["target_user"],
                            "source_user": c["source_user"], "target_task_id": c["target_task_id"],
                            "source_task_id": c["source_task_id"]} for c in cal["cells"]],
           "main": [{"cell_id": c["cell_id"], "arm": c["arm"], "target_user": c["target_user"],
                     "source_user": c["source_user"], "target_task_id": c["target_task_id"],
                     "source_task_id": c["source_task_id"]} for c in main["cells"]]}
    mem = {"forms": {a.code: a.memory_form for a in A.ALL},
           "retrieval_policies": {a.code: a.retrieval_policy for a in A.ALL},
           "expired_window": [MB._PAST_FROM, MB._PAST_UNTIL]}

    h_task = _write(os.path.join(ART, "task_manifest.json"), task_manifest(cal, main))
    h_ua = _write(os.path.join(ART, "user_assignment.json"), ua)
    h_stp = _write(os.path.join(ART, "source_target_pairs.json"), stp)
    h_mem = _write(os.path.join(ART, "memory_bank_manifest.json"), mem)
    h_prompt = _write(os.path.join(ART, "prompt_manifest.json"), pm)

    freeze = {
        "experiment": "P5.1 static multi-user coding",
        "generator_version": cal["generator_version"],
        "calibration": {"experiment_id": cal["experiment_id"], "plan_hash": PLAN.plan_hash(cal),
                        "cells": len(cal["cells"]), "users": len(cal["users"]),
                        "families": sorted({c["family_id"] for c in cal["cells"]})},
        "main": {"experiment_id": main["experiment_id"], "plan_hash": PLAN.plan_hash(main),
                 "cells": len(main["cells"]), "users": len(main["users"]),
                 "families": sorted({c["family_id"] for c in main["cells"]})},
        "manifest_hashes": {"task_manifest": h_task, "user_assignment": h_ua, "source_target_pairs": h_stp,
                            "memory_bank_manifest": h_mem, "prompt_manifest": h_prompt},
        "model_lock": MODEL_LOCK,
        "analysis_code_hash": _src_hash(PLAN.plan_hash, PLAN.build_plan),
        "stop_rules": STOP_RULES,
        "call_budget": {"calibration_primary": 16 * 5, "calibration_with_safety": 16 * 9,
                        "main_primary": 32 * 5, "main_with_safety": 32 * 9},
    }
    _write(os.path.join(ART, "freeze.json"), freeze)

    _yaml(os.path.join(CFG, "p5_1_calibration.yaml"),
          {"experiment_id": cal["experiment_id"], "split": "calibration", "n_per_domain": 4, "n_users": 8,
           "include_safety": True, "arms": cal["arms"], "plan_hash": PLAN.plan_hash(cal)})
    _yaml(os.path.join(CFG, "p5_1_main.yaml"),
          {"experiment_id": main["experiment_id"], "split": "main", "n_per_domain": 8, "n_users": 12,
           "include_safety": True, "arms": main["arms"], "plan_hash": PLAN.plan_hash(main)})
    _write(os.path.join(CFG, "p5_1_model_lock.json"), MODEL_LOCK)
    print("froze calibration plan_hash", freeze["calibration"]["plan_hash"][:16],
          "main plan_hash", freeze["main"]["plan_hash"][:16])


if __name__ == "__main__":
    main()
