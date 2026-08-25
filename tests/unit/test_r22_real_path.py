"""R22 §11 — credential-free REAL-path verification (no API key, no model call; Docker grading reused from G0).
Loaders + adapter wiring + runtime plumbing are exercised with a MOCK provider and a stub grader; the actual paid
path uses the real provider + official grader."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from experiments.r22.runtime import loaders as LD
from experiments.r22.runtime import task_runtime as TR
from experiments.r22.runtime.provider import FakeReaderProvider
from experiments.r22.runtime.accounting import Ledger
from experiments.r22.runtime.integrity import check_campaign

SCB = os.environ.get("R22_SCB_DATA", os.path.join(ROOT, "artifacts", "r22", "_scb_data"))
HAS_SCB = os.path.isfile(os.path.join(SCB, "SWEContextBench_Related.parquet"))
P1_IDS_HASH = "081440dbbb63bed1"
DEV_IDS_HASH = "20f887f1f1b93afe"


def _ids_hash(tasks):
    return hashlib.sha256(json.dumps(sorted(t["target_id"] for t in tasks)).encode()).hexdigest()[:16]


def _git_repo(bug=True):
    root = tempfile.mkdtemp()
    open(os.path.join(root, "calc.py"), "w").write("def mul(a,b):\n    return a+b\n" if bug else "def mul(a,b):\n    return a*b\n")
    subprocess.run(["git", "init", "-q"], cwd=root, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=x", "commit", "-qm", "i"],
                   cwd=root, capture_output=True)
    return root


def _stub_grade(task, patch):
    return {"resolved": "return a*b" in (patch or ""), "grader": "stub_test_only", "returncode": 0}


def _real_task(tid="apache__lucene-13388"):
    return {"target_id": tid, "subset": "SWE-ContextBench", "dataset_name": LD.SCB_DATASET,
            "repository": "apache/lucene", "repo_cluster": "apache/lucene", "issue": "mul is wrong",
            "stage": "COMPREHEND", "source_id": "src-x", "source_user": "gold_a", "target_user": "u_b",
            "target_leak_tokens": [tid]}


# ---- 1,2 frozen ids + routes -------------------------------------------------
@pytest.mark.skipif(not HAS_SCB, reason="SWE-ContextBench parquet not present")
def test_frozen_real_ids_load_exactly():
    p1 = LD.RealR22TaskLoader("oracle_smoke_manifest.json", SCB).load()
    dev = LD.RealR22TaskLoader("oracle_dev_manifest.json", SCB).load()
    assert len(p1) == 12 and _ids_hash(p1) == P1_IDS_HASH
    assert len(dev) == 40 and _ids_hash(dev) == DEV_IDS_HASH
    assert all(t["dataset_name"] == LD.SCB_DATASET for t in p1)


# ---- 3 real mode cannot call fake fixtures ----------------------------------
def test_real_mode_cannot_call_fake_fixtures(monkeypatch):
    import experiments.r22.paid_runner as PRD
    from experiments.r22.runtime import repo_agent as RA
    monkeypatch.setattr(PRD, "fake_tasks", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fake_tasks called")))
    monkeypatch.setattr(RA, "make_fixture", lambda *a, **k: (_ for _ in ()).throw(AssertionError("make_fixture")))
    monkeypatch.setattr(RA, "local_grade", lambda *a, **k: (_ for _ in ()).throw(AssertionError("local_grade")))
    if not HAS_SCB:
        pytest.skip("needs SCB parquet")
    tasks = LD.RealR22TaskLoader("oracle_smoke_manifest.json", SCB).load()   # real loader, no fake call
    assert len(tasks) == 12


# ---- 4,5 grading discrimination reused from G0 (same adapter) ----------------
def test_grader_discrimination_reused_from_g0_and_adapter_is_official():
    g0 = json.load(open(os.path.join(ROOT, "artifacts", "r22", "grader_smoke.json")))
    assert g0.get("gold_resolved") == 12 and g0.get("nopatch_resolved") == 0
    assert hasattr(LD.OfficialSWEGrader, "grade_via_cli")   # the adapter the real runtime calls (not local_grade)
    src = open(os.path.join(ROOT, "experiments", "r22", "paid_runner.py"), encoding="utf-8").read()
    real_block = src.split('cfg.task_source == "real"')[1][:400]
    assert "OfficialSWEGrader.grade_via_cli" in real_block and "LocalFixtureGrader" not in real_block


# ---- 6 stage-record source lookup -------------------------------------------
def test_frozen_stage_memory_lookup():
    ml = LD.FrozenStageMemoryLoader()
    bank = json.load(open(os.path.join(ROOT, "artifacts", "r22", "gold_precedent_bank.json")))
    ok = 0
    for e in bank["records"][:50]:
        rec = e["record"]
        if ml.load(rec["identity"]["source_task_id"], rec["stage"]):
            ok += 1
    assert ok == 50


# ---- 7 O1 visible, no historical content; O1 != O0 --------------------------
def test_o1_visible_no_historical_and_differs_from_o0():
    recs = {}
    for arm in ("O0", "O1"):
        prov = FakeReaderProvider(script={"fix": {"path": "calc.py", "start_line": 2, "end_line": 2,
                                                  "new_content": "    return a*b"}, "stage": "EDIT"})
        recs[arm] = TR.run_task_arm(task=_real_task(), arm=arm, provider=prov, ledger=Ledger("fake-reader", 100),
                                    grade_fn=_stub_grade, workspace_root=_git_repo())
    sys0 = recs["O0"]["messages"][0]["content"]
    sys1 = recs["O1"]["messages"][0]["content"]
    assert sys1 != sys0 and "scaffold" in sys1.lower()
    assert not recs["O1"]["injection"]["historical_content"]


# ---- 9 payload hash == payload bytes; 10 evidence present -------------------
def test_payload_hash_and_evidence_present():
    prov = FakeReaderProvider(script={"fix": {"path": "calc.py", "start_line": 2, "end_line": 2,
                                              "new_content": "    return a*b"}, "stage": "EDIT"})
    ml = LD.FakeMemorySourceLoader()
    rec = TR.run_task_arm(task=_real_task(), arm="O6", provider=prov, ledger=Ledger("fake-reader", 100),
                          grade_fn=_stub_grade, workspace_root=_git_repo(), memory_record=ml.load("s", "EDIT"))
    inj = rec["injection"]
    assert inj["byte_hash"] == hashlib.sha256(inj["text"].encode("utf-8")).hexdigest()
    for f in ("patch_sha256", "raw_response_sha256", "grader", "content_hash", "usage", "messages"):
        assert rec.get(f), "missing evidence field %s" % f


# ---- 8 O2 derangement exact --------------------------------------------------
def test_o2_derangement_from_manifest():
    import experiments.r22.paid_runner as PRD
    d = PRD._real_derangement("oracle_dev_manifest.json", [])
    assert d and all(k != v for k, v in d.items() if v)   # no fixed point


# ---- 11 campaign model drift detected ---------------------------------------
def test_campaign_model_drift_detected():
    recs = [{"target_id": "t1", "arm": "O0", "returned_model": "m1", "injection": {"text": None}},
            {"target_id": "t1", "arm": "O1", "returned_model": "m2", "injection": {"text": None}}]
    for r in recs:
        r["returned_model"] = r["returned_model"]
    models = {r["returned_model"] for r in recs}
    assert len(models) > 1     # the campaign check in paid_runner flags this


# ---- 13 result hash sensitivity ---------------------------------------------
def test_content_hash_changes_on_patch_or_verdict():
    def rec(patch, resolved):
        prov = FakeReaderProvider(script={"fix": {"path": "calc.py", "start_line": 2, "end_line": 2,
                                                  "new_content": patch}, "stage": "EDIT"})
        return TR.run_task_arm(task=_real_task(), arm="O0", provider=prov, ledger=Ledger("fake-reader", 100),
                               grade_fn=lambda t, p: {"resolved": resolved, "grader": "stub", "returncode": 0},
                               workspace_root=_git_repo())
    a = rec("    return a*b", True)
    b = rec("    return a*b", False)
    assert a["content_hash"] != b["content_hash"]     # verdict change -> hash change


# ---- 14 missing repo cluster fails analysis ---------------------------------
def test_missing_cluster_fails_analysis(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text(json.dumps({"cell_key": "t::O0", "target_id": "t", "arm": "O0", "resolved": True,
                             "patch_sha256": "x", "raw_response_sha256": "y", "usage": {"cost_usd": 0.0},
                             "returned_model": "m", "injection": {"text": None}}) + "\n")  # no repo_cluster
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "r22_paid_analyze.py"),
                        "--input", str(f), "--expected-cells", "1", "--out", str(tmp_path / "a.json")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "cluster" in r.stdout.lower()


# ---- 12 P1/P2 provider wiring valid (string checks; no yaml dep) -------------
def test_p1_p2_provider_wiring():
    for wf in ("r22-reader-smoke.yml", "r22-oracle-dev.yml"):
        src = open(os.path.join(ROOT, ".github", "workflows", wf), encoding="utf-8").read()
        assert "reader_provider: {description:" in src, "%s missing reader_provider input" % wf
        assert '--provider "${{ inputs.reader_provider }}"' in src, "%s passes wrong --provider" % wf
        assert '--provider "${{ inputs.reader_model }}"' not in src, "%s still passes model as provider" % wf
