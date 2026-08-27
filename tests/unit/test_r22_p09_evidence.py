"""R22-P0.9 §5/§8 — fail-closed evidence aggregate: PASS on a good 55-target fixture; FAIL on each defect.
Credential-free (no docker/model/secret); builds synthetic per-target shard summaries + the full 8-file raw
evidence set per condition, mirroring what scripts/r22_p09_gradeability.py stashes."""
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ART09 = os.path.join(ROOT, "artifacts", "r22_p09")
AGG = os.path.join(ROOT, "scripts", "r22_p09_aggregate.py")
MANIFEST = os.path.join(ART09, "dev55_gradeability_manifest.json")
EVIDENCE = ["run_instance.log", "test_output.txt", "report.json", "summary_report.json",
            "stdout.log", "stderr.log", "dataset.json", "prediction.json"]
DIG = "sha256:aaaa"


def _target_ids():
    m = json.load(open(MANIFEST, encoding="utf-8"))
    return sorted(m["records"].keys())


def _content(iid, cond, name):
    return ("%s/%s/%s :: r22 p09 raw evidence" % (iid, cond, name)).encode()


def _good_cell(gold=True, noop_resolved=False):
    return ({"resolved": gold, "patch_applied": True, "infra_ok": True, "tests_executed": True,
             "f2p_complete": True, "p2p_regression": 0, "patch_sha256": "g0"},
            {"resolved": noop_resolved, "patch_applied": True, "infra_ok": True, "tests_executed": True,
             "not_shortcircuit": True, "patch_sha256": "n0"})


def _write_target(dl, iid, label="GRADEABLE", digest_match=True):
    """Write one shard folder: grade_<iid>.json + the full raw evidence set under <iid>/<cond>/<name>."""
    d = os.path.join(dl, "shard-" + iid)
    ev = {}
    for cond in ("gold", "noop"):
        cd = os.path.join(d, iid, cond)
        os.makedirs(cd, exist_ok=True)
        cev = {}
        for name in EVIDENCE:
            data = _content(iid, cond, name)
            open(os.path.join(cd, name), "wb").write(data)
            cev[name] = {"relpath": "%s/%s/%s" % (iid, cond, name),
                         "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        ev[cond] = cev
    gcell, ncell = _good_cell()
    summary = {"instance_id": iid, "label": label, "image_expected_digest": DIG,
               "image_observed_digest": DIG if digest_match else "sha256:bbbb",
               "image_digest_verified": digest_match, "case_sha256": "c0", "noop_patch_sha256": "n0",
               "gold": gcell, "noop_baseline": ncell, "evidence": ev}
    os.makedirs(d, exist_ok=True)
    json.dump(summary, open(os.path.join(d, "grade_%s.json" % iid), "w", encoding="utf-8"))


def _good_fixture(dl, ids):
    for iid in ids:
        _write_target(dl, iid)


def _run(dl, tmp):
    r = subprocess.run([sys.executable, AGG, "--download-dir", dl,
                        "--out", os.path.join(tmp, "res.json"),
                        "--evidence-out", os.path.join(tmp, "ev.json"),
                        "--sha256sums", os.path.join(tmp, "SHA256SUMS"),
                        "--report", os.path.join(tmp, "report.md")], capture_output=True, text=True)
    rp = os.path.join(tmp, "res.json")
    camp = json.load(open(rp)) if os.path.isfile(rp) else {}
    return r.returncode, camp, r.stdout + r.stderr


def test_aggregate_pass_on_good_fixture(tmp_path):
    dl = str(tmp_path / "dl"); _good_fixture(dl, _target_ids())
    rc, camp, log = _run(dl, str(tmp_path))
    assert rc == 0, log
    assert camp["audit_complete"] is True and camp["endpoint"].endswith("AUDIT_COMPLETE")
    assert camp["failed_gates"] == []
    assert camp["counts"]["gradeable"] == 55 and camp["label_counts"]["GRADEABLE"] == 55


def test_fail_missing_summary(tmp_path):
    ids = _target_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    shutil.rmtree(os.path.join(dl, "shard-" + ids[0]))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["summary_files_55"]


def test_fail_duplicate_target(tmp_path):
    ids = _target_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    d2 = os.path.join(dl, "shard-%s-copy" % ids[0]); os.makedirs(d2)
    json.dump({"instance_id": ids[0], "label": "GRADEABLE"},
              open(os.path.join(d2, "grade_%s.json" % ids[0]), "w"))
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["no_duplicate_targets"]


def test_fail_infra_failure(tmp_path):
    ids = _target_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    _write_target(dl, ids[0], label="INFRA_FAILURE")
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["no_infra_failure"]


def test_fail_unknown(tmp_path):
    ids = _target_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    _write_target(dl, ids[0], label="UNKNOWN")
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["no_unknown"]


def test_fail_digest_mismatch(tmp_path):
    ids = _target_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    _write_target(dl, ids[0], digest_match=False)
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["no_digest_mismatch"]


@pytest.mark.parametrize("name", EVIDENCE)
def test_fail_missing_raw_evidence(tmp_path, name):
    ids = _target_ids(); dl = str(tmp_path / "dl"); _good_fixture(dl, ids)
    os.remove(os.path.join(dl, "shard-" + ids[0], ids[0], "gold", name))   # delete one required raw evidence file
    rc, camp, _ = _run(dl, str(tmp_path))
    assert rc != 0 and not camp["gates"]["raw_evidence_complete"]
    assert camp["counts"]["missing_raw_evidence"] >= 1
