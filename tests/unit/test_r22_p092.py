"""R22-P0.9.2 §2/§3 — resume sentinel + freeze tests (static, credential-free; no yaml dependency)."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, ".github", "workflows", "ci-r22-p092-resume.yml")
SENTINEL = "artifacts/r22_p092/EXEC_APPROVED_R22_P09_RESUME1"
TARGETS = {"sympy__sympy-20959", "sympy__sympy-21758"}


def _wf():
    return open(WF, encoding="utf-8").read()


def test_resume_sentinel_is_new_path_not_the_old_one():
    src = _wf()
    assert "paths: ['%s']" % SENTINEL in src
    assert "branches: [codex/r22-stage-aligned-memory]" in src
    # never re-touch the old P0.9 sentinel
    gate_lines = [l for l in src.splitlines() if "tr -d" in l]
    assert gate_lines and all(SENTINEL in l for l in gate_lines)
    assert all("artifacts/r22_p09/EXEC_APPROVED_R22_P09 " not in l for l in gate_lines)


def test_gate_requires_exact_resume_content():
    src = _wf()
    assert 'inputs.confirm_exec_approved }}" = "EXEC_APPROVED_R22_P09_RESUME1"' in src
    assert '%s 2>/dev/null)" = "EXEC_APPROVED_R22_P09_RESUME1"' % SENTINEL in src


def test_resume_runs_only_two_targets_at_180min():
    src = _wf()
    assert "[sympy__sympy-20959, sympy__sympy-21758]" in src
    assert "timeout 10800" in src           # 180 minutes
    # no other target smuggled in
    for bad in ("sympy__sympy-11707", "astropy__astropy-14500"):
        assert bad not in src


def test_no_secret_or_paid_tokens():
    src = _wf()
    for tok in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY", "RUN_APPROVED", "BUDGET", "secrets."):
        assert tok not in src


def test_resume_manifest_exactly_two_targets():
    m = json.load(open(os.path.join(ROOT, "artifacts", "r22_p092", "resume_manifest.json"), encoding="utf-8"))
    assert set(m["targets"]) == TARGETS and len(m["records"]) == 2
    assert m["resume_timeout_minutes"] == 180
    for iid in TARGETS:
        r = m["records"][iid]
        assert r["image_digest"].startswith("sha256:") and r["original_timeout_evidence"]["exit_code"] == 124
        assert r["idempotency_key"] and r["original_p091_campaign_sha256"]
