"""P5.2 §7/§12 seal — the frozen P5.2 plan/manifests/thresholds match a fresh deterministic recomputation;
any post-freeze edit diverges a hash and fails. Independent of the P5.1 seal."""
import hashlib
import json
import os

from experiments.p5_2 import plan as PLAN, assignment as ASG
from experiments.p5_2.plan import CALIBRATION, MAIN

ART = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "experiments", "p5_2")


def _load(n):
    return json.load(open(os.path.join(ART, n), encoding="utf-8"))


def _canon(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True).encode()).hexdigest()


def test_plan_hashes_match():
    fz = _load("freeze.json")
    cal = PLAN.build_plan("EXP_P5_2_CAL", CALIBRATION, include_safety=True)
    main = PLAN.build_plan("EXP_P5_2_MAIN", MAIN, include_safety=True)
    assert PLAN.plan_hash(cal) == fz["calibration"]["plan_hash"]
    assert PLAN.plan_hash(main) == fz["main"]["plan_hash"]


def test_manifests_unmodified():
    fz = _load("freeze.json")
    for name, key in [("task_manifest.json", "task_manifest"), ("user_assignment.json", "user_assignment"),
                      ("source_target_pairs.json", "source_target_pairs"),
                      ("memory_bank_manifest.json", "memory_bank_manifest"),
                      ("prompt_manifest.json", "prompt_manifest")]:
        assert _canon(_load(name)) == fz["manifest_hashes"][key], "%s modified after freeze" % name
    assert _canon(_load("retrieval_thresholds.json")) == fz["manifest_hashes"]["retrieval_thresholds"]


def test_prompt_and_thresholds_sealed():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
    import p5_2_freeze  # noqa
    assert p5_2_freeze.prompt_manifest() == _load("prompt_manifest.json")
    thr = _load("retrieval_thresholds.json")
    fz = _load("freeze.json")
    assert (thr["tau_abs"], thr["tau_margin"]) == (fz["tau_abs"], fz["tau_margin"]) == (0.8, 0.5)


def test_calibration_main_disjoint_and_invariants():
    fz = _load("freeze.json")
    cf, mf = set(fz["calibration"]["families"]), set(fz["main"]["families"])
    assert cf and mf and not (cf & mf)
    _, cells = ASG.assign("calibration", 4, 8, include_safety=True)
    v = ASG.validate_assignment(cells)
    assert v["cross_user_source_ne_target"] and v["m1_source_eq_target"] and v["m0_no_source"]
    assert v["families_all_primary_arms"]


def test_model_lock_frozen():
    lock = json.load(open(os.path.join(ART, "..", "..", "..", "configs", "experiments",
                                       "p5_2_model_lock.json"), encoding="utf-8"))
    assert lock["model"] == "solar-pro2-251215" and lock["attempts"] == 1 and lock["repair_in_primary"] is False
