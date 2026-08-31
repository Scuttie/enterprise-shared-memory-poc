"""R23-B0 §6 — credential-free gradeability adapter checks. No docker/model."""
import importlib.util
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mod():
    spec = importlib.util.spec_from_file_location("r23grad", os.path.join(ROOT, "scripts", "r23_gradeability.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_noop_patch_touches_only_the_noop_file():
    m = _mod()
    added = re.findall(r"^\+\+\+ b/(.+)$", m.NOOP_R23_PATCH, re.M)
    assert added == [".r23_noop"] and "new file mode" in m.NOOP_R23_PATCH


def test_empty_patch_rejected():
    m = _mod()
    with pytest.raises(m.EmptyBaselineRejected):
        m.assert_valid_baseline("")
    assert m.assert_valid_baseline(m.NOOP_R23_PATCH) == m.NOOP_R23_PATCH


def test_uses_mainline_swebench_not_the_memory_fork():
    src = open(os.path.join(ROOT, "scripts", "r23_gradeability.py"), encoding="utf-8").read()
    assert "swebench.harness.run_evaluation" in src
    assert "swebench_memory.harness" not in src              # does not CALL the SWE-ContextBench fork
    assert "SWE-bench/SWE-bench_Verified" in src


def test_execution_gated_credential_free():
    src = open(os.path.join(ROOT, "scripts", "r23_gradeability.py"), encoding="utf-8").read()
    assert "R23_UPSTREAM_EXEC_APPROVED" in src               # docker execution gated
    for banned in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "secrets.", "api_key"):
        assert banned not in src.lower() if banned in ("secrets.", "api_key") else banned not in src
