"""R22 §11 — credential-free full harness test: fake-provider E2E + negative tests + release hygiene.
No model calls, no Docker, no secret."""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from experiments.r22 import paid_runner as PR
from experiments.r22.runtime.provider import (FakeReaderProvider, OpenAICompatibleReaderProvider,
                                              ProviderError, ModelDriftError)
from experiments.r22.runtime.checkpoint import CheckpointStore
from experiments.r22.runtime.integrity import check_cell, check_campaign
from experiments.r22.runtime.accounting import Ledger, BudgetExceeded
from enterprise_memory.experience.stage_schema import Stage
from enterprise_memory.service.stage_state import StageState, StageObservation, StageTransitionError

PAID_WORKFLOWS = ["r22-reader-selection.yml", "r22-reader-smoke.yml", "r22-oracle-dev.yml"]


# ---- fake-provider E2E -------------------------------------------------------

def test_fake_e2e_p1_integrity_pass(tmp_path):
    m, integ = PR.run(phase="p1", arms=["O0", "O1", "O2", "O3", "O4", "O5", "O6"],
                      provider_spec={"mode": "fake", "model": "fake-reader"}, hard_cap=100.0,
                      out_dir=str(tmp_path / "p1"), n_tasks=3)
    assert integ["clean"] and integ["cells"] == 21
    assert m["resolved_by_arm"]["O0"] == 3


def test_checkpoint_resume_runs_only_missing(tmp_path):
    out = str(tmp_path / "p1")
    PR.run(phase="p1", arms=["O0", "O1"], provider_spec={"mode": "fake", "model": "fake-reader"},
           hard_cap=100.0, out_dir=out, n_tasks=2)
    n1 = sum(1 for _ in open(os.path.join(out, "results.jsonl")))
    PR.run(phase="p1", arms=["O0", "O1"], provider_spec={"mode": "fake", "model": "fake-reader"},
           hard_cap=100.0, out_dir=out, n_tasks=2)
    n2 = sum(1 for _ in open(os.path.join(out, "results.jsonl")))
    assert n1 == n2 == 4          # resume adds 0 new cells


# ---- negative tests ----------------------------------------------------------

def test_secret_absent_fake_accepted():
    FakeReaderProvider(model="fake-reader")   # no secret needed


def test_secret_absent_paid_refused(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError):
        OpenAICompatibleReaderProvider("openai", "gpt-4o-mini", "OPENAI_API_KEY")


def test_returned_model_drift_stops():
    p = FakeReaderProvider(model="m")
    p._check_model_stable("m")
    with pytest.raises(ModelDriftError):
        p._check_model_stable("m2")


def test_under_budget_gate_stops():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "r22_paid_gate.py"),
                        "--stage", "p1", "--model", "gpt-4o-mini", "--budget", "1",
                        "--run-approved", "RUN_APPROVED", "--secret-name", "OPENAI_API_KEY"],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "hard cap" in r.stdout


def test_budget_hard_stop_in_ledger():
    led = Ledger("gpt-4o", 0.001)
    with pytest.raises(BudgetExceeded):
        led.add(800000, 80000)


def test_duplicate_cell_rejected(tmp_path):
    ck = CheckpointStore(str(tmp_path / "r.jsonl"))
    ck.append({"cell_key": "t::O0", "arm": "O0", "target_id": "t"})
    with pytest.raises(ValueError):
        ck.append({"cell_key": "t::O0", "arm": "O0", "target_id": "t"})


def test_o0_memory_access_rejected():
    v = check_cell({"arm": "O0", "memory_search_calls": 1, "injection": {"text": "x"}, "returned_model": "m"})
    assert any("O0" in x for x in v)


def test_o2_fixed_point_rejected():
    rec = {"target_id": "t", "arm": "O2", "returned_model": "m",
           "injection": {"text": "", "source_id": "t", "byte_hash": None}}
    r = check_campaign([rec], expected_cells=1, o2_derangement={"t": "other"})
    assert any("fixed point" in v for v in r["violations"])


def test_o3_product_selection_rejected():
    rec = {"target_id": "t", "arm": "O3", "returned_model": "m", "selected_as_product": True,
           "injection": {"text": "", "byte_hash": None}}
    r = check_campaign([rec], expected_cells=1, o2_derangement={})
    assert r["o3_product_selections"] == 1 and not r["clean"]


def test_target_leakage_rejected():
    v = check_cell({"arm": "O4", "returned_model": "m", "target_leak_tokens": ["django-123"],
                    "injection": {"text": "see django-123 fix", "byte_hash":
                                  __import__("hashlib").sha256(b"see django-123 fix").hexdigest()}})
    assert any("target token" in x for x in v)


def test_injection_hash_mismatch_rejected():
    v = check_cell({"arm": "O5", "returned_model": "m",
                    "injection": {"text": "abc", "byte_hash": "deadbeef"}})
    assert any("hash mismatch" in x for x in v)


def test_stage_skip_rejected():
    s = StageState(stage=Stage.COMPREHEND, obs=StageObservation())
    with pytest.raises(StageTransitionError):
        s.advance(Stage.EDIT)


def test_stale_reader_lock_rejected(tmp_path):
    lock = {"schema": "x", "provider": "openai", "model": "gpt-4o-mini", "requested_model": "gpt-4o-mini",
            "returned_model": "gpt-4o-mini", "resolved_rate": 0.3, "result_hash": "h"}
    import hashlib
    lock["reader_lock_sha256"] = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    p = tmp_path / "lock.json"
    json.dump(lock, open(p, "w"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "r22_verify_reader_lock.py"),
                        str(p), "WRONGSHA"], capture_output=True, text=True)
    assert r.returncode == 1


def test_fake_provider_is_not_networked():
    p = FakeReaderProvider(model="fake-reader")
    assert not isinstance(p, OpenAICompatibleReaderProvider)


def test_analysis_fail_closed_on_incomplete(tmp_path):
    f = tmp_path / "r.jsonl"
    f.write_text(json.dumps({"cell_key": "t::O0", "target_id": "t", "arm": "O0", "resolved": True,
                             "patch_sha256": "x", "raw_response_sha256": "y", "usage": {"cost_usd": 0.0},
                             "returned_model": "m", "injection": {"text": None}}) + "\n")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "r22_paid_analyze.py"),
                        "--input", str(f), "--expected-cells", "280", "--out", str(tmp_path / "a.json")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "FAIL" in r.stdout


# ---- release hygiene (no placeholders) --------------------------------------

def test_no_paid_workflow_has_commented_runner_or_echo_only():
    wf = os.path.join(ROOT, ".github", "workflows")
    for name in PAID_WORKFLOWS:
        src = open(os.path.join(wf, name), encoding="utf-8").read()
        assert "# python experiments/r22" not in src, "%s has a commented-out runner" % name
        assert "runner is invoked here" not in src, "%s ends after echo" % name
        # references a real runner script
        assert re.search(r"python experiments/r22/\w+_?\w*\.py", src), "%s calls no real runner" % name


def test_paid_analysis_has_no_or_true():
    src = open(os.path.join(ROOT, ".github", "workflows", "ci-r22-paid-analysis.yml"), encoding="utf-8").read()
    assert "|| true" not in src


def test_paid_workflows_invoke_existing_files():
    wf = os.path.join(ROOT, ".github", "workflows")
    for name in PAID_WORKFLOWS + ["ci-r22-paid-analysis.yml"]:
        src = open(os.path.join(wf, name), encoding="utf-8").read()
        for m in re.findall(r"python (experiments/r22/[\w./]+|scripts/[\w./]+)", src):
            assert os.path.isfile(os.path.join(ROOT, m)), "%s references missing %s" % (name, m)
