"""REALBENCH-R1 preregistration freeze (§15). Writes the frozen manifests (split, source, targets, users,
memory bank, prompt, evaluator, model lock) — pure functions of the official dataset + the frozen split +
arms + prompt/compiler source + the frozen retrieval config. Run BEFORE any calibration/main model call."""
import hashlib
import inspect
import json
import os

from experiments.realbench_r1 import experiment as X, arms as A, grader as G, seeding as SEED
from enterprise_memory.service.execution import P52WholeFileExecutionBackend

ART = os.path.join("artifacts", "realbench_r1")
CFG = os.path.join("configs", "realbench_r1")
MODEL_LOCK = {"backend": "solar_p52", "base_url": "https://api.upstage.ai/v1/solar",
              "model": "solar-pro2-251215", "temperature": 0, "top_p": 1.0, "max_output_tokens": 1200,
              "generations": 1, "repair_in_primary": False, "extraction": "whole-file code block",
              "sandbox": "controlled_local -> official evalplus grader (Linux)", "timeout_s": 20}


def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


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
    return {"prompt_builder_hash": _sha(inspect.getsource(P52WholeFileExecutionBackend._build_prompt)),
            "instruction_builder_hash": _sha(inspect.getsource(SEED._instruction)),
            "memory_render_hash": _sha(inspect.getsource(X.governed_summary) + inspect.getsource(X.ungoverned_text))}


def main():
    sp = X.build_split()
    a = X.audit_split(sp)
    thr = json.load(open(os.path.join(ART, "retrieval_config.json"), encoding="utf-8"))
    pm = prompt_manifest()

    h_src = _write(os.path.join(ART, "source_manifest.json"),
                   {"source_task_ids": sp["source"], "n": len(sp["source"]),
                    "note": "verified: official canonical passes base+plus (ci-realbench-grader)"})
    h_cal = _write(os.path.join(ART, "calibration_targets.json"), {"task_ids": sp["calibration"]})
    h_main = _write(os.path.join(ART, "main_targets.json"), {"task_ids": sp["main"]})
    h_dev = _write(os.path.join(ART, "retrieval_dev.json"), {"task_ids": sp["retrieval_dev"]})
    h_ua = _write(os.path.join(ART, "user_assignment.json"),
                  {"scheme": "one synthetic org+user per arm; R1 private = target's nearest source"})
    h_mem = _write(os.path.join(ART, "memory_bank.json"),
                   {"forms": {x.code: x.memory_form for x in A.ALL},
                    "retrieval_policies": {x.code: x.retrieval_policy for x in A.ALL},
                    "source_facts_sample": {t: X.source_fact(t)["description"] for t in sp["source"][:3]}})
    h_prompt = _write(os.path.join(ART, "prompt_manifest.json"), pm)
    h_eval = _write(os.path.join(ART, "evaluator_manifest.json"),
                    {"benchmark": "MBPP+ (EvalPlus v0.2.0)", "package_version": "0.3.1",
                     "dataset_content_hash": G.content_hash(),
                     "grader": "evalplus.eval.untrusted_check + trusted_exec ground-truth (Linux)"})

    freeze = {"experiment": "REALBENCH_MBPP_PLUS_R1", "split_hash": X.split_hash(sp), "split_audit": a,
              "dataset_content_hash": G.content_hash(),
              "manifest_hashes": {"source": h_src, "calibration_targets": h_cal, "main_targets": h_main,
                                  "retrieval_dev": h_dev, "user_assignment": h_ua, "memory_bank": h_mem,
                                  "prompt_manifest": h_prompt, "evaluator_manifest": h_eval,
                                  "retrieval_config": _sha(json.dumps(thr, sort_keys=True))},
              "tau_abs": A.TAU_ABS, "tau_margin": A.TAU_MARGIN, "index_dim": A.INDEX_DIM,
              "arms": [x.code for x in A.ALL], "model_lock": MODEL_LOCK,
              "primary_endpoint": "Pass@1(R3) - Pass@1(R0), paired by official target task",
              "note": "Do not present M3-M0/R3-R0 as evidence for contract format when R3-R2 is null.",
              "call_budget": {"calibration": len(sp["calibration"]) * len(A.ALL),
                              "main": len(sp["main"]) * len(A.ALL)}}
    _write(os.path.join(ART, "freeze.json"), freeze)
    _yaml(os.path.join(CFG, "calibration.yaml"), {"split": "calibration", "n_targets": len(sp["calibration"]),
                                                  "arms": [x.code for x in A.ALL], "split_hash": X.split_hash(sp)})
    _yaml(os.path.join(CFG, "main.yaml"), {"split": "main", "n_targets": len(sp["main"]),
                                           "arms": [x.code for x in A.ALL], "split_hash": X.split_hash(sp)})
    _write(os.path.join(CFG, "model_lock.json"), MODEL_LOCK)
    print("froze REALBENCH-R1 split_hash", X.split_hash(sp)[:16], "audit", a)


if __name__ == "__main__":
    main()
