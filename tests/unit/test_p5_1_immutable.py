"""P5.2 §1/§12 — P5.1 is permanently frozen. The content hash of every P5.1 frozen file and the calibration
results is locked; if P5.2 code overwrites any of them, this test fails (a hard stop). This is independent of
the P5.1 seal test (which checks internal plan/manifest consistency)."""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK = os.path.join(ROOT, "artifacts", "experiments", "p5_1", "P5_1_IMMUTABLE_LOCK.json")


def test_p5_1_frozen_files_unmodified():
    lock = json.load(open(LOCK, encoding="utf-8"))
    assert len(lock) >= 19
    bad = []
    for rel, want in lock.items():
        p = os.path.join(ROOT, rel)
        assert os.path.exists(p), "P5.1 frozen file deleted: %s" % rel
        got = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if got != want:
            bad.append(rel)
    assert not bad, "P5.1 frozen file(s) modified by P5.2 (forbidden): %s" % bad


def test_p5_1_calibration_result_immutable():
    lock = json.load(open(LOCK, encoding="utf-8"))
    key = "artifacts/experiments/p5_1/results/calibration_results.json"
    assert key in lock
    p = os.path.join(ROOT, key)
    assert hashlib.sha256(open(p, "rb").read()).hexdigest() == lock[key]
