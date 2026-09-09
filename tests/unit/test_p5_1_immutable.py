"""P5.2 §1/§12 — P5.1 is permanently frozen. The content hash of every P5.1 frozen file and the calibration
results is locked; if P5.2 code overwrites any of them, this test fails (a hard stop). This is independent of
the P5.1 seal test (which checks internal plan/manifest consistency)."""
import hashlib
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCK = os.path.join(ROOT, "artifacts", "experiments", "p5_1", "P5_1_IMMUTABLE_LOCK.json")


def _unchanged_git_blob(rel: str) -> bytes:
    path = os.path.join(ROOT, rel)
    assert os.path.exists(path), "P5.1 frozen file deleted: %s" % rel
    unchanged = subprocess.run(
        ["git", "diff", "--quiet", "--no-ext-diff", "HEAD", "--", rel],
        cwd=ROOT,
        check=False,
    )
    assert unchanged.returncode == 0, "P5.1 frozen file modified: %s" % rel
    return subprocess.check_output(["git", "show", "HEAD:" + rel], cwd=ROOT)


def test_p5_1_frozen_files_unmodified():
    lock = json.load(open(LOCK, encoding="utf-8"))
    assert len(lock) >= 19
    bad = []
    for rel, want in lock.items():
        got = hashlib.sha256(_unchanged_git_blob(rel)).hexdigest()
        if got != want:
            bad.append(rel)
    assert not bad, "P5.1 frozen file(s) modified by P5.2 (forbidden): %s" % bad


def test_p5_1_calibration_result_immutable():
    lock = json.load(open(LOCK, encoding="utf-8"))
    key = "artifacts/experiments/p5_1/results/calibration_results.json"
    assert key in lock
    assert hashlib.sha256(_unchanged_git_blob(key)).hexdigest() == lock[key]
