"""R22-P0.9.1 §2 — sentinel-trigger regression tests (static, credential-free)."""
import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, ".github", "workflows", "ci-r22-p09-gradeability.yml")
SENTINEL = "artifacts/r22_p09/EXEC_APPROVED_R22_P09"


def _wf():
    return yaml.safe_load(open(WF, encoding="utf-8"))


def _on(d):
    return d.get("on", d.get(True))   # PyYAML parses bare `on:` as boolean True


def test_push_trigger_is_restricted_to_the_p09_sentinel_path():
    on = _on(_wf())
    push = on["push"]
    assert push["paths"] == [SENTINEL], "push must fire ONLY on the P0.9 sentinel path"
    assert push["branches"] == ["codex/r22-stage-aligned-memory"]


def test_ordinary_branch_push_does_not_trigger():
    # a push touching any other path is not in the paths filter -> no run
    on = _on(_wf())
    assert on["push"]["paths"] == [SENTINEL]
    src = open(WF, encoding="utf-8").read()
    assert "paths-ignore" not in src   # not a broad trigger


def test_does_not_reuse_the_old_scb_sentinel():
    on = _on(_wf())
    # the TRIGGER path and the GATE both use the P0.9 sentinel, never the old 12-target smoke sentinel
    assert on["push"]["paths"] == [SENTINEL]
    assert "artifacts/r22/EXEC_APPROVED " not in "".join(
        l for l in open(WF, encoding="utf-8") if "tr -d" in l)   # gate never reads the old sentinel file


def test_gate_requires_exact_sentinel_content():
    src = open(WF, encoding="utf-8").read()
    # gate accepts dispatch input OR sentinel content, compared to the exact token
    assert 'inputs.confirm_exec_approved }}" = "EXEC_APPROVED_R22_P09"' in src
    assert "%s 2>/dev/null)\" = \"EXEC_APPROVED_R22_P09\"" % SENTINEL in src


def test_no_secret_or_paid_tokens_in_workflow():
    src = open(WF, encoding="utf-8").read()
    for tok in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "RUN_APPROVED", "BUDGET", "secrets."):
        assert tok not in src, "forbidden token in P0.9 workflow: %s" % tok
