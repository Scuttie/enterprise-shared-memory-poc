"""Behavioral checks for the additive SK hynix integration evaluation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/trimem_skhynix_evaluate.py"
SPEC = importlib.util.spec_from_file_location("trimem_skhynix_evaluate", SCRIPT)
assert SPEC and SPEC.loader
evaluation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evaluation
SPEC.loader.exec_module(evaluation)


def test_code_checks_execute_behavior_instead_of_searching_for_fix_tokens():
    assert evaluation.executable_checks({"target.py": evaluation.FIXED_CODE}).passed
    assert not evaluation.executable_checks({"target.py": evaluation.INITIAL_CODE + "# casefold\n"}).passed
    assert not evaluation.executable_checks({"target.py": "def accepts(name):\n    return True\n"}).passed


def test_equal_reader_mechanisms_traverse_the_existing_runtime(tmp_path):
    report = evaluation.evaluate(tmp_path / "comparison")
    assert report["status"] == "PASS", (report["mechanisms"], report["supplemental_integration"])
    assert report["totals"]["cells"] == 13
    assert report["totals"]["comparison_cells"] == 12
    assert report["totals"]["mechanisms_passed"] == 7
    assert report["totals"]["paid_model_calls"] == 0
    assert report["totals"]["official_grader_calls"] == 0
    assert report["totals"]["replay_model_calls"] == 79
    assert report["totals"]["comparison_replay_model_calls"] == 72
    assert report["totals"]["supplemental_replay_model_calls"] == 7
    assert report["supplemental_integration"]["private_episodes_retained"] == 1
    assert report["supplemental_integration"]["resume_replay_model_calls"] == 0
    assert all(row["reader_exposure_verified"] for row in report["cells"])
    assert all(row["evidence_verified"] for row in report["cells"])
    assert "cannot estimate coding lift" in report["interpretation"]
    source_ids = {row["task_id"] for row in report["source_fixtures"]}
    assert source_ids.isdisjoint(row["task_id"] for row in report["cells"])


def test_evaluation_refuses_to_overwrite_prior_evidence(tmp_path):
    prior = tmp_path / "prior"
    prior.mkdir()
    sentinel = prior / "report.json"
    sentinel.write_text("original evidence", encoding="utf-8")
    with pytest.raises(FileExistsError):
        evaluation.evaluate(prior)
    assert sentinel.read_text(encoding="utf-8") == "original evidence"
