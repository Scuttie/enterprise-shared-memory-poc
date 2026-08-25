"""R22-P0.8 §11 — credential-free tests for the OFFICIAL SWE-ContextBench grader wiring.

These catch the P0.7 bugs P0.8 fixes: wrong evaluator selected, image=None on real tasks, generic-swebench call in
the real path, unverified case/image coverage, ungated execution of the unlicensed upstream evaluator. No docker,
no secret, no model call, no paid API."""
import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
ART = os.path.join(ROOT, "artifacts", "r22")

from experiments.r22.runtime import loaders as LD
from experiments.r22.runtime import scb_official_grader as SG

SCB = os.environ.get("R22_SCB_DATA", os.path.join(ART, "_scb_data"))
HAS_SCB = os.path.isfile(os.path.join(SCB, "SWEContextBench_Related.parquet"))


def _load(name):
    return json.load(open(os.path.join(ART, name), encoding="utf-8"))


def _frozen_ids(mn):
    m = _load(mn)
    out = []
    for t in m["task_list"]:
        if t.get("target_id") not in out:
            out.append(t["target_id"])
    return out


# ---- §2 evaluator lock -------------------------------------------------------
def test_evaluator_lock_pins_official_harness_and_license():
    lk = _load("scb_official_evaluator_lock.json")
    assert lk["pinned_commit"] == "31bb04155f52b184bf31b220e3cff0607ac9c953"
    for f in ("evaluation.sh", "swebench_memory/harness/run_evaluation.py",
              "swebench_memory/harness/combine_instances.py"):
        assert f in lk["files"] and len(lk["files"][f]["sha256"]) == 64
    assert "NO EXPLICIT LICENSE" in lk["evaluation_code_license"].upper()
    assert lk["image_tag_derivation"] == "jiayuanz3/swecontextbench:{instance_id.replace('__','.').lower()}"


# ---- §4 tag derivation matches the frozen image manifest for all 40 ----------
def test_derive_image_tag_matches_manifest_40_40():
    im = _load("scb_image_manifest.json")
    assert im["manifest_found"] == 40 and im["linux_amd64"] == 40
    for iid, e in im["images"].items():
        assert SG.derive_image_tag(iid) == e["image"]
        assert e["http_status"] == 200 and e["linux_amd64"] is True
        assert (e["digest"] or "").startswith("sha256:")


# ---- §3 case coverage + equivalence 40/40 ------------------------------------
def test_case_coverage_and_equivalence_40_40():
    cm = _load("scb_case_route_manifest.json")
    assert cm["found"] == 40 and cm["missing"] == []
    dev = set(_frozen_ids("oracle_dev_manifest.json"))
    assert dev.issubset(set(cm["cases"].keys()))
    ce = _load("scb_case_equivalence.json")
    assert ce["byte_core_equivalent"] == 40 and ce["test_identity_equivalent"] == 40


# ---- §5 grader refuses to execute the unlicensed upstream w/o approval --------
def test_grader_refuses_without_execution_approval(monkeypatch):
    monkeypatch.delenv("R22_SCB_UPSTREAM_EXEC_APPROVED", raising=False)
    route = {"instance_id": "astropy__astropy-14500",
             "case_path": "cases/SWEContextBench Verified/astropy__astropy-14500.json"}
    with pytest.raises(SG.UpstreamExecutionNotApproved):
        SG.grade(route, "", tempfile.mkdtemp())


# ---- §7 real tasks carry the OFFICIAL image + case route (no image=None) ------
def test_real_task_has_official_image_and_route_not_none():
    ld = open(os.path.join(ROOT, "experiments", "r22", "runtime", "loaders.py"), encoding="utf-8").read()
    assert '"image": None' not in ld                      # the P0.7 bug is gone
    assert "OfficialSWEGrader = SCBOfficialGrader" in ld    # generic name re-routed
    if not HAS_SCB:
        pytest.skip("needs SCB parquet")
    tasks = LD.RealR22TaskLoader("oracle_smoke_manifest.json", SCB).load()
    assert len(tasks) == 12
    for t in tasks:
        assert t["image"] and t["image"].startswith("jiayuanz3/swecontextbench:")
        assert (t["image_digest"] or "").startswith("sha256:")
        assert t.get("case_route") and t["case_route"]["case_path"].startswith("cases/")


# ---- workflows gated on execution approval -----------------------------------
def test_scb_workflows_are_dispatch_only_and_exec_gated():
    for wf in ("ci-r22-scb-grader-smoke.yml", "ci-r22-scb-real-path.yml"):
        src = open(os.path.join(ROOT, ".github", "workflows", wf), encoding="utf-8").read()
        assert "workflow_dispatch" in src and "schedule" not in src and "on: [push" not in src
        assert "EXEC_APPROVED" in src and "R22_SCB_UPSTREAM_EXEC_APPROVED" in src


# ---- §1 the P0.7 technical-block doc is retracted -----------------------------
def test_p07_block_is_retracted():
    doc = open(os.path.join(ROOT, "reports", "R22_PAID_TARGET_ROUTE_AUDIT.md"), encoding="utf-8").read()
    assert "RETRACT" in doc.upper()
    assert "R22_WRONG_GRADER_SELECTED_PENDING_OFFICIAL_SCB_RERUN" in doc
    rights = open(os.path.join(ROOT, "reports", "R22_UPSTREAM_RIGHTS_STATUS.md"), encoding="utf-8").read()
    assert "R22_UPSTREAM_EVALUATOR_EXECUTION_REVIEW" in rights
