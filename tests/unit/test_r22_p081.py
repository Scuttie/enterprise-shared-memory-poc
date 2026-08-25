"""R22-P0.8.1 §1-§4/§8 — credential-free tests. No docker, no secret, no model, paid API = 0."""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
ART = os.path.join(ROOT, "artifacts", "r22")
REPORTS = os.path.join(ROOT, "reports")

from experiments.r22.runtime import scb_official_grader as SG
from experiments.r22.runtime import candidate_order as CO


# ---- §1 endpoint reconciliation / consistency --------------------------------
def test_exactly_one_report_claims_current_endpoint():
    marker = "R22_CURRENT_ENDPOINT:"
    holders = [p for p in glob.glob(os.path.join(REPORTS, "*.md"))
               if marker in open(p, encoding="utf-8").read()]
    assert len(holders) == 1, "exactly one report may declare the current R22 endpoint, found %s" % holders
    txt = open(holders[0], encoding="utf-8").read()
    endpoint = re.search(r"R22_CURRENT_ENDPOINT:\s*(\S+)", txt).group(1)
    sup = json.load(open(os.path.join(ART, "grader_smoke_supersession.json"), encoding="utf-8"))
    assert endpoint == sup["current_endpoint"] == "R22_UPSTREAM_EVALUATOR_EXECUTION_REVIEW"


def test_generic_report_is_superseded_and_retitled():
    txt = open(os.path.join(REPORTS, "R22_GRADER_REPRODUCTION.md"), encoding="utf-8").read()
    assert "GENERIC_ENRICHED_SWEBENCH_GRADER_PASS" in txt
    assert "R22_SUPERSEDED_BY:" in txt and "R22_CURRENT_ENDPOINT:" not in txt
    assert "NOT sufficient for paid approval" in txt


def test_historical_grader_smoke_bytes_preserved():
    d = json.load(open(os.path.join(ART, "grader_smoke.json"), encoding="utf-8"))
    assert d["verdict"] == "R22_GRADER_READY_AWAITING_PAID_APPROVAL"   # historical value intact
    sup = json.load(open(os.path.join(ART, "grader_smoke_supersession.json"), encoding="utf-8"))
    assert sup["historical_commit"].startswith("1cc9d92") and sup["current_head"].startswith("f1e78b7")


# ---- §2 no-op baseline vs empty short-circuit --------------------------------
def test_empty_patch_rejected_as_invalid_control():
    with pytest.raises(SG.EmptyBaselineRejected):
        SG.assert_valid_baseline_patch("")
    with pytest.raises(SG.EmptyBaselineRejected):
        SG.assert_valid_baseline_patch("   \n ")
    assert SG.assert_valid_baseline_patch(SG.NOOP_BASELINE_PATCH) == SG.NOOP_BASELINE_PATCH


def test_noop_patch_touches_only_the_noop_file():
    added = re.findall(r"^\+\+\+ b/(.+)$", SG.NOOP_BASELINE_PATCH, re.M)
    assert added == [".r22_noop"]                      # no source/test file modified
    assert "new file mode" in SG.NOOP_BASELINE_PATCH


def test_smoke_driver_uses_noop_not_empty():
    src = open(os.path.join(ROOT, "scripts", "r22_scb_grader_smoke.py"), encoding="utf-8").read()
    assert "NOOP_BASELINE_PATCH" in src and "assert_valid_baseline_patch" in src
    assert "noop-baseline" in src and "noop_resolved == 0" in src


# ---- §3 runtime image-digest verification ------------------------------------
def test_verify_digest_pure():
    assert SG.verify_digest("sha256:abc", "sha256:abc") is True
    assert SG.verify_digest("sha256:abc", "sha256:def") is False
    assert SG.verify_digest("", "sha256:abc") is False


def test_pull_verify_raises_on_missing_expected_digest():
    # negative path reachable without docker: no expected digest -> integrity block before any pull
    with pytest.raises(SG.ImageDigestMismatch):
        SG.pull_and_verify_image("jiayuanz3/swecontextbench:astropy.astropy-14500", "")


def test_grade_verifies_digest_before_evaluator():
    src = open(os.path.join(ROOT, "experiments", "r22", "runtime", "scb_official_grader.py"), encoding="utf-8").read()
    # the digest verification call inside grade() precedes the evaluator subprocess invocation
    assert src.index("img_info = pull_and_verify_image") < src.index('"-m", EVALUATOR_MODULE')


# ---- §4 matrix derived from the frozen manifest ------------------------------
def test_prepare_matrix_from_frozen_manifest(tmp_path):
    out = tmp_path / "matrix.json"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "r22_scb_prepare_matrix.py"),
                        "--out", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.load(open(out, encoding="utf-8"))
    assert d["targets"] == 12 and len(d["instance_ids"]) == 12
    assert d["frozen_ids_sha256"] == "081440dbbb63bed1f1b800673f4885aadce6524d1d7c637186e840f714c70a3c"
    assert d["cases_present"] and d["image_digests_present"] and d["errors"] == []
    # spec §4 hash is surfaced as UNRECONCILED (does not match); frozen identity is authoritative
    assert d["spec_manifest_hash_matches"] is False


def test_workflow_has_no_second_hardcoded_target_list():
    wf = open(os.path.join(ROOT, ".github", "workflows", "ci-r22-scb-grader-smoke.yml"), encoding="utf-8").read()
    assert "fromJson(needs.prepare.outputs.matrix)" in wf
    assert "- apache__lucene-13388" not in wf          # the hard-coded list is gone


# ---- §8 frozen candidate order (reconcile only) ------------------------------
def test_frozen_candidate_order_from_plan():
    assert CO.frozen_order() == ["deepseek-chat", "gpt-4o-mini", "gpt-4o"]


def test_cannot_skip_to_later_candidate():
    assert CO.assert_not_skipping("deepseek-chat", []) == "deepseek-chat"
    with pytest.raises(CO.CandidateOrderViolation):
        CO.assert_not_skipping("gpt-4o", [])
    with pytest.raises(CO.CandidateOrderViolation):
        CO.assert_not_skipping("gpt-4o-mini", [])
    assert CO.assert_not_skipping("gpt-4o-mini", ["deepseek-chat"]) == "gpt-4o-mini"
    assert CO.assert_not_skipping("gpt-4o", ["deepseek-chat", "gpt-4o-mini"]) == "gpt-4o"
