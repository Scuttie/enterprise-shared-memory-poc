"""P5.2 preregistration freeze (§7). Writes the P5.2 manifests + configs + model lock, all pure functions of
the frozen generator + assignment + arms + prompt/compiler source + the (already-frozen) retrieval thresholds.
Independent of the P5.1 seal. Run BEFORE any P5.2 calibration/main model call."""
import hashlib
import inspect
import json
import os

from experiments.p5_2 import plan as PLAN, arms as A, memory_bank as MB, tokens as TOK
from experiments.p5_2.plan import CALIBRATION, MAIN, instruction_for
from enterprise_memory.service.execution import P52WholeFileExecutionBackend
from enterprise_memory.service import private_view
from enterprise_memory.contracts import codec

ART = os.path.join("artifacts", "experiments", "p5_2")
CFG = os.path.join("configs", "experiments")

MODEL_LOCK = {"backend": "solar_p52", "base_url": "https://api.upstage.ai/v1/solar",
              "model": "solar-pro2-251215", "temperature": 0, "top_p": 1.0, "max_output_tokens": 1200,
              "attempts": 1, "repair_in_primary": False,
              "sandbox": {"kind": "controlled_local", "grading": "hidden_test", "timeout_s": 20}}

STOP_RULES = {"gates": ["G1", "G2", "G3", "G4", "G5", "G6", "G7"],
              "primary": "CrossUserLift = Pass@1(M3) - Pass@1(M0), paired by family",
              "primary_success": "mean paired lift >= +0.05 AND family-cluster bootstrap 95% CI lower bound > 0",
              "no_edit_after_results": True,
              "note": "M3-M0 is not evidence for the contract format when M3-M2 is null"}


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _src(*o):
    h = hashlib.sha256()
    for x in o:
        h.update(inspect.getsource(x).encode())
    return h.hexdigest()


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, sort_keys=True); f.write("\n")
    return _sha(json.dumps(obj, sort_keys=True))


def _yaml(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join("%s: %s" % (k, json.dumps(v)) for k, v in obj.items()) + "\n")


def prompt_manifest():
    return {"instruction_builder_hash": _src(instruction_for),
            "prompt_builder_hash": _src(P52WholeFileExecutionBackend._build_prompt),
            "execution_view_compiler_hash": _src(codec.retrieval_text_and_path_scope,
                                                 private_view.compile_private_view),
            "retrieval_token_hash": _src(TOK.mem_text, TOK.query_text)}


def main():
    cal = PLAN.build_plan("EXP_P5_2_CAL", CALIBRATION, include_safety=True)
    main = PLAN.build_plan("EXP_P5_2_MAIN", MAIN, include_safety=True)
    thr = json.load(open(os.path.join(ART, "retrieval_thresholds.json"), encoding="utf-8"))
    pm = prompt_manifest()

    ua = {"calibration_users": cal["users"], "main_users": main["users"]}
    stp = {s: [{"cell_id": c["cell_id"], "arm": c["arm"], "stratum": c["stratum"],
                "target_user": c["target_user"], "source_user": c["source_user"],
                "target_task_id": c["target_task_id"]} for c in p["cells"]]
           for s, p in (("calibration", cal), ("main", main))}
    mem = {"forms": {a.code: a.memory_form for a in A.ALL},
           "retrieval_policies": {a.code: a.retrieval_policy for a in A.ALL},
           "candidate_pool": {"relevant_present": "1 relevant + 3 same-domain near-miss + 4 cross-domain irrelevant",
                              "relevant_absent_S1": "0 relevant + 4 near-miss + 4 irrelevant"},
           "expired_window": [MB._PAST_FROM, MB._PAST_UNTIL], "tau_abs": A.TAU_ABS, "tau_margin": A.TAU_MARGIN}
    tm = {"generator_version": cal["generator_version"],
          "calibration": {"generation_hash": cal["benchmark_generation_hash"],
                          "families": sorted({c["family_id"] for c in cal["cells"]}),
                          "strata": {c["family_id"]: c["stratum"] for c in cal["cells"]}},
          "main": {"generation_hash": main["benchmark_generation_hash"],
                   "families": sorted({c["family_id"] for c in main["cells"]})}}

    h = {"task_manifest": _write(os.path.join(ART, "task_manifest.json"), tm),
         "user_assignment": _write(os.path.join(ART, "user_assignment.json"), ua),
         "source_target_pairs": _write(os.path.join(ART, "source_target_pairs.json"), stp),
         "memory_bank_manifest": _write(os.path.join(ART, "memory_bank_manifest.json"), mem),
         "prompt_manifest": _write(os.path.join(ART, "prompt_manifest.json"), pm),
         "retrieval_thresholds": _sha(json.dumps(thr, sort_keys=True))}

    freeze = {"experiment": "P5.2 static multi-user coding (dynamic-range + retrieval-abstention)",
              "generator_version": cal["generator_version"],
              "calibration": {"experiment_id": cal["experiment_id"], "plan_hash": PLAN.plan_hash(cal),
                              "cells": len(cal["cells"]), "users": len(cal["users"]),
                              "families": sorted({c["family_id"] for c in cal["cells"]})},
              "main": {"experiment_id": main["experiment_id"], "plan_hash": PLAN.plan_hash(main),
                       "cells": len(main["cells"]), "users": len(main["users"]),
                       "families": sorted({c["family_id"] for c in main["cells"]})},
              "manifest_hashes": h, "tau_abs": A.TAU_ABS, "tau_margin": A.TAU_MARGIN,
              "model_lock": MODEL_LOCK, "analysis_code_hash": _src(PLAN.plan_hash, PLAN.build_plan),
              "stop_rules": STOP_RULES,
              "call_budget": {"instrument_dev": 8 * 9, "calibration": 16 * 9, "main": 32 * 9}}
    _write(os.path.join(ART, "freeze.json"), freeze)
    _yaml(os.path.join(CFG, "p5_2_calibration.yaml"),
          {"experiment_id": cal["experiment_id"], "split": "calibration", "n_per_domain": 4, "n_users": 8,
           "arms": cal["arms"], "plan_hash": PLAN.plan_hash(cal), "tau_abs": A.TAU_ABS, "tau_margin": A.TAU_MARGIN})
    _yaml(os.path.join(CFG, "p5_2_main.yaml"),
          {"experiment_id": main["experiment_id"], "split": "main", "n_per_domain": 8, "n_users": 12,
           "arms": main["arms"], "plan_hash": PLAN.plan_hash(main), "tau_abs": A.TAU_ABS, "tau_margin": A.TAU_MARGIN})
    _write(os.path.join(CFG, "p5_2_model_lock.json"), MODEL_LOCK)
    print("froze P5.2 calibration plan_hash", freeze["calibration"]["plan_hash"][:16],
          "main plan_hash", freeze["main"]["plan_hash"][:16])


if __name__ == "__main__":
    main()
