"""R22-P0.9.1 §2 — sentinel-trigger regression tests (static, credential-free; no yaml dependency)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, ".github", "workflows", "ci-r22-p09-gradeability.yml")
SENTINEL = "artifacts/r22_p09/EXEC_APPROVED_R22_P09"


def _src():
    return open(WF, encoding="utf-8").read()


def test_push_trigger_is_restricted_to_the_p09_sentinel_path():
    src = _src()
    assert "push:" in src
    assert "paths: ['%s']" % SENTINEL in src, "push must fire ONLY on the P0.9 sentinel path"
    assert "branches: [codex/r22-stage-aligned-memory]" in src


def test_ordinary_branch_push_does_not_trigger():
    src = _src()
    assert "paths: ['%s']" % SENTINEL in src
    assert "paths-ignore" not in src   # not a broad trigger


def test_does_not_reuse_the_old_scb_sentinel():
    # the push TRIGGER path and the GATE both use the P0.9 sentinel, never the old 12-target smoke sentinel
    src = _src()
    assert "paths: ['%s']" % SENTINEL in src
    gate_lines = [l for l in src.splitlines() if "tr -d" in l]
    assert gate_lines and all(SENTINEL in l for l in gate_lines)
    assert all("artifacts/r22/EXEC_APPROVED " not in l for l in gate_lines)   # never reads the old sentinel


def test_gate_requires_exact_sentinel_content():
    src = _src()
    assert 'inputs.confirm_exec_approved }}" = "EXEC_APPROVED_R22_P09"' in src
    assert '%s 2>/dev/null)" = "EXEC_APPROVED_R22_P09"' % SENTINEL in src


def test_no_secret_or_paid_tokens_in_workflow():
    src = _src()
    for tok in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "RUN_APPROVED", "BUDGET", "secrets."):
        assert tok not in src, "forbidden token in P0.9 workflow: %s" % tok
