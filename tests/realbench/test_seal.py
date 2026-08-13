"""REALBENCH-R1 §15/§16 seal — frozen split/manifests match a fresh deterministic recomputation."""
import hashlib, json, os
import pytest
pytest.importorskip("evalplus")
from experiments.realbench_r1 import experiment as X
ART = os.path.join(os.path.dirname(__file__), "..", "..", "artifacts", "realbench_r1")


def _load(n): return json.load(open(os.path.join(ART, n), encoding="utf-8"))
def _canon(o): return hashlib.sha256(json.dumps(o, sort_keys=True).encode()).hexdigest()


def test_split_hash_and_audit():
    fz = _load("freeze.json"); sp = X.build_split()
    assert X.split_hash(sp) == fz["split_hash"]
    a = X.audit_split(sp)
    assert a["source_target_task_overlap"] == 0 and a["calibration_main_overlap"] == 0
    assert a["source_target_funcname_overlap"] == 0 and a["dev_overlap"] == 0


def test_manifests_unmodified():
    fz = _load("freeze.json")
    for name, key in [("source_manifest.json", "source"), ("calibration_targets.json", "calibration_targets"),
                      ("main_targets.json", "main_targets"), ("prompt_manifest.json", "prompt_manifest"),
                      ("evaluator_manifest.json", "evaluator_manifest"), ("memory_bank.json", "memory_bank")]:
        assert _canon(_load(name)) == fz["manifest_hashes"][key], "%s changed after freeze" % name


def test_model_lock():
    lock = json.load(open(os.path.join(ART, "..", "..", "configs", "realbench_r1", "model_lock.json"), encoding="utf-8"))
    assert lock["model"] == "solar-pro2-251215" and lock["generations"] == 1 and lock["repair_in_primary"] is False
