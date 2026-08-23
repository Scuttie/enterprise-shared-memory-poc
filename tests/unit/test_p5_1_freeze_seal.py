"""P5.1 §12 seal tests. The frozen manifests must exactly match a fresh deterministic recomputation from the
generator / assignment / arms / prompt+compiler source. If any frozen input is edited after the freeze, a hash
diverges and these tests fail — so a post-freeze change can never be silently mixed with result data."""
import hashlib
import json
import os

from experiments.p5_1 import plan as PLAN, assignment as ASG
from experiments.p5_1.plan import CALIBRATION, MAIN

ART = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "experiments", "p5_1")


def _load(name):
    with open(os.path.join(ART, name), encoding="utf-8") as f:
        return json.load(f)


def _canon_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def test_freeze_plan_hashes_match():
    freeze = _load("freeze.json")
    cal = PLAN.build_plan("EXP_P5_1_CAL", CALIBRATION, include_safety=True)
    main = PLAN.build_plan("EXP_P5_1_MAIN", MAIN, include_safety=True)
    assert PLAN.plan_hash(cal) == freeze["calibration"]["plan_hash"], "calibration plan changed after freeze"
    assert PLAN.plan_hash(main) == freeze["main"]["plan_hash"], "main plan changed after freeze"


def test_frozen_manifest_files_unmodified():
    freeze = _load("freeze.json")
    for name, key in [("task_manifest.json", "task_manifest"), ("user_assignment.json", "user_assignment"),
                      ("source_target_pairs.json", "source_target_pairs"),
                      ("memory_bank_manifest.json", "memory_bank_manifest"),
                      ("prompt_manifest.json", "prompt_manifest")]:
        assert _canon_hash(_load(name)) == freeze["manifest_hashes"][key], "%s modified after freeze" % name


def test_prompt_and_compiler_hash_sealed():
    from experiments.p5_1.manifest import prompt_manifest
    assert prompt_manifest() == _load("prompt_manifest.json"), "prompt/compiler source changed after freeze"


def test_calibration_main_disjoint_and_invariants():
    freeze = _load("freeze.json")
    calf = set(freeze["calibration"]["families"]); mainf = set(freeze["main"]["families"])
    assert calf and mainf and not (calf & mainf)
    _, cells = ASG.assign("calibration", 4, 8, include_safety=True)
    v = ASG.validate_assignment(cells)
    assert v["cross_user_source_ne_target"] and v["m1_source_eq_target"] and v["m0_no_source"]
    assert v["source_target_task_disjoint"] and v["families_all_primary_arms"]


def test_model_lock_frozen():
    lock = json.load(open(os.path.join(ART, "..", "..", "..", "configs", "experiments",
                                        "p5_1_model_lock.json"), encoding="utf-8"))
    assert lock["model"] == "solar-pro2-251215" and lock["attempts"] == 1 and lock["repair_in_primary"] is False
