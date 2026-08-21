"""P6/R19 §13/§23 — the offline company demo must produce DEMO_PASS (Definition of Done core)."""
import subprocess
import sys
import os
import json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_offline_demo_passes():
    r = subprocess.run([sys.executable, "scripts/demo_company_handoff.py", "--offline"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DEMO_PASS: true" in r.stdout
    ev = json.load(open(os.path.join(ROOT, "artifacts", "p6", "demo_evidence.json"), encoding="utf-8"))
    assert ev["DEMO_PASS"] is True
    # every scenario step present and passing
    steps = {s["step"] for s in ev["steps"]}
    for required in ("promote_after_review", "router_USE_and_inject", "credit_memory_gain",
                     "router_ABSTAIN_incompatible", "quarantine_on_repeated_loss", "private_not_leaked",
                     "audit_chain_no_secret"):
        assert required in steps, required
    # no secret/private text in the evidence bundle
    blob = json.dumps(ev)
    assert "internal token" not in blob and "alice private" not in blob
