"""R22-P0.8.2 §3/§4 — fail-closed aggregate: PASS on a good fixture; FAIL on each of 6 defects.
Credential-free (no docker/model/secret); builds synthetic shard artifacts."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART = os.path.join(ROOT, "artifacts", "r22")
AGG = os.path.join(ROOT, "scripts", "r22_scb_aggregate.py")


def _frozen_ids():
    m = json.load(open(os.path.join(ART, "oracle_smoke_manifest.json"), encoding="utf-8"))
    out = []
    for t in m["task_list"]:
        if t.get("target_id") not in out:
            out.append(t["target_id"])
    return out


def _good_cell(gold=True, noop_resolved=False, noop_tests=True, digest_match=True):
    dig = "sha256:aaaa"
    return {
        "image": "jiayuanz3/swecontextbench:x", "case_sha256": "c0", "noop_patch_sha256": "n0",
        "image_expected_digest": dig, "image_observed_digest": dig if digest_match else "sha256:bbbb",
        "image_digest_verified": digest_match,
        "gold": {"resolved": gold, "patch_applied": True, "infra_ok": True, "tests_executed": True,
                 "f2p_complete": True, "p2p_regression": 0, "patch_sha256": "g0"},
        "noop_baseline": {"resolved": noop_resolved, "patch_applied": True, "infra_ok": True,
                          "tests_executed": noop_tests,
                          "not_shortcircuit": bool(noop_tests), "patch_sha256": "n0"},
    }


def _write_shard(dl, iid, cell, with_logs=("gold", "noop")):
    d = os.path.join(dl, "scb-smoke-" + iid)
    os.makedirs(d, exist_ok=True)
    json.dump({"results": {iid: cell}}, open(os.path.join(d, "scb_grader_smoke_%s.json" % iid), "w"))
    for cond in ("gold", "noop"):
        cd = os.path.join(d, iid, cond)
        os.makedirs(cd, exist_ok=True)
        if cond in with_logs:
            open(os.path.join(cd, "run_instance.log"), "w").write("ok")
            open(os.path.join(cd, "test_output.txt"), "w").write("FAIL_TO_PASS: 1/1")
            open(os.path.join(cd, "r_stdout.log"), "w").write("out")
            open(os.path.join(cd, "r_stderr.log"), "w").write("")


def _good_fixture(dl, ids):
    for iid in ids:
        _write_shard(dl, iid, _good_cell())


def _run(dl, tmp):
    r = subprocess.run([sys.executable, AGG, "--download-dir", dl,
                        "--out", os.path.join(tmp, "camp.json"),
                        "--evidence-out", os.path.join(tmp, "ev.json"),
                        "--sha256sums", os.path.join(tmp, "SHA256SUMS"),
                        "--report", os.path.join(tmp, "report.md")], capture_output=True, text=True)
    camp = json.load(open(os.path.join(tmp, "camp.json"))) if os.path.isfile(os.path.join(tmp, "camp.json")) else {}
    return r.returncode, camp, r.stdout + r.stderr


def test_aggregate_pass_on_good_fixture(tmp_path):
    dl = str(tmp_path / "dl"); _good_fixture(dl, _frozen_ids())
    rc, camp, log = _run(dl, str(tmp_path))
    assert rc == 0, log
    assert camp["verdict_pass"] is True and camp["endpoint"].endswith("AWAITING_READER_SELECTION")
    assert camp["failed_gates"] == []


def test_fail_missing_shard(tmp_path):
    ids = _frozen_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    import shutil
    shutil.rmtree(os.path.join(dl, "scb-smoke-" + ids[0]))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["summary_files"]


def test_fail_duplicate_shard(tmp_path):
    ids = _frozen_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    # a second artifact folder with the same target's summary = duplicate shard
    d2 = os.path.join(dl, "scb-smoke-%s-copy" % ids[0]); os.makedirs(d2)
    json.dump({"results": {ids[0]: _good_cell()}},
              open(os.path.join(d2, "scb_grader_smoke_%s.json" % ids[0]), "w"))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["no_duplicate_cells"]


def test_fail_digest_mismatch(tmp_path):
    ids = _frozen_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    _write_shard(dl, ids[0], _good_cell(digest_match=False))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["digest_match"]


def test_fail_noop_tests_not_executed(tmp_path):
    ids = _frozen_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    _write_shard(dl, ids[0], _good_cell(noop_tests=False))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and (not camp["gates"]["noop_tests_executed"] or not camp["gates"]["noop_no_shortcircuit"])


def test_fail_gold_unresolved(tmp_path):
    ids = _frozen_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    _write_shard(dl, ids[0], _good_cell(gold=False))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["gold_resolved"]


def test_fail_missing_raw_log(tmp_path):
    ids = _frozen_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    # actually delete the noop raw logs for one target
    noop_dir = os.path.join(dl, "scb-smoke-" + ids[0], ids[0], "noop")
    for name in ("run_instance.log", "test_output.txt"):
        os.remove(os.path.join(noop_dir, name))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["no_missing_raw_evidence"]
