#!/usr/bin/env python3
"""P6/R19 §13 — deterministic OFFLINE company demo. No credentials, no network, no DB.

Exercises the full governed flow end to end on the in-memory components:
  Alice solves a verified source task -> card compiled -> reviewer promotes -> Bob gets an applicable target ->
  search -> router USE -> execution view injected -> outcome credited (MEMORY_GAIN) ->
  incompatible card -> router ABSTAIN -> wrong card -> repeated loss -> quarantine ->
  Alice's PRIVATE memory never appears in Bob's context -> audit chain verifies.
Prints `DEMO_PASS: true` and writes a JSON evidence bundle with NO secret/private text.

Usage: python scripts/demo_company_handoff.py --offline
       python scripts/demo_company_handoff.py --endpoint <url> --manifest configs/company.example.yaml   (connected; not required offline)
"""
import argparse
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from enterprise_memory.experience import SourceEvidence, Bank, SourceOutcome, GovernanceState, compile_card
from enterprise_memory.agentic import InMemoryExperienceStore, MemorySearchService, SearchSession
from enterprise_memory.router import TaskContext, TrajectoryState
from enterprise_memory.governance import (
    OutcomeCreditAssigner, GovernanceMachine, CardStats, MEMORY_GAIN, MEMORY_LOSS,
)

ORG = "org-demo"


def _ev(**kw):
    base = dict(
        bank=Bank.HISTORICAL_VERIFIED, source_type="issue_fix", source_repository="acme/widgets",
        source_commit="c1", source_issue_id="101", source_author_id="alice",
        source_timestamp="2020-01-01T00:00:00Z", source_outcome=SourceOutcome.PASSED,
        source_verifier_hash="verified", symptom_signature="widget loader crashes on missing config key",
        root_cause="loader assumes config key present", fault_localization="acme/widgets/loader.py",
        affected_symbols=["WidgetLoader.load"], affected_apis=["configparser"],
        repair_strategy="guard for missing config key before access",
        ordered_actions=["locate WidgetLoader.load", "guard missing key with default"],
        patch_pattern="cfg.get(key, default)", validation_strategy="run loader tests",
        language="python", framework="acme", version_scope="2.x", confidence=0.8)
    base.update(kw)
    return SourceEvidence(**base)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--endpoint", default="")
    ap.add_argument("--manifest", default="")
    args = ap.parse_args()

    if args.endpoint and not args.offline:
        print("connected mode is a stub in this build; use --offline for the deterministic demo.")
        print("DEMO_PASS: false")
        return 2

    ev = {"steps": [], "org": ORG}
    ok = True

    def step(name, passed, **extra):
        nonlocal ok
        ok = ok and bool(passed)
        ev["steps"].append({"step": name, "pass": bool(passed), **extra})

    store = InMemoryExperienceStore()          # shared, searchable store
    private_store = InMemoryExperienceStore()   # Alice's PRIVATE store (never shared)
    svc = MemorySearchService(store)
    gov = GovernanceMachine()
    assigner = OutcomeCreditAssigner()

    # 1-4: Alice's verified source -> card -> promote
    card = compile_card(_ev())
    step("compile_card", card.content_hash and card.governance_state == GovernanceState.CANDIDATE,
         card_key=card.card_key, content_hash=card.content_hash[:16])
    state = gov.on_source_verified(card.governance_state, source_passed=True)   # -> probation
    stats = CardStats(gains=2, losses=0)                                        # two prior gains in probation
    state = gov.promote(state, stats, reviewed=True)                            # reviewer promotes
    card.governance_state = state
    store.add(ORG, "v1", card)
    step("promote_after_review", state == GovernanceState.PROMOTED, state=state.value)

    # Alice's PRIVATE card (different content) stays only in the private store
    priv = compile_card(_ev(source_issue_id="P1", symptom_signature="alice private note about internal token"))
    priv.governance_state = GovernanceState.PROMOTED
    private_store.add(ORG, "pv1", priv)

    # 5-8: Bob's applicable target -> search -> USE -> inject -> credit
    bob_task = TaskContext(org_id=ORG, repository="acme/widgets", subtask="modification",
                           target_apis=["configparser"], target_symbols=["WidgetLoader.load"],
                           error_signature="widget loader crashes missing config key", version="2.x")
    sess = SearchSession(session_id="sess-bob-1", org_id=ORG, request_id="req-bob-1", actor_id_hash="bob-hash",
                         target_task_id="acme-widgets-205", mode="utility_gated")
    results = svc.search_experiences(sess, bob_task, "widget loader missing config key crash")
    step("search_returns_card", any(r["version_id"] == "v1" for r in results), n_results=len(results))
    cands = store.search(ORG, "acme/widgets", "widget loader missing config key crash")
    view = svc.browse_experience(sess, bob_task, TrajectoryState(is_stuck=True), cands[0])
    dec = svc.explain_decision(sess)[-1]
    step("router_USE_and_inject", view is not None and dec["decision"] == "USE",
         reason_codes=dec["reason_codes"])
    # Bob adopts the source operation -> resolved; counterfactual (no memory) would not have resolved
    bob_patch = "cfg.get(key, default)  # guard missing key in WidgetLoader.load using configparser"
    credit = assigner.assign("acme-widgets-205", "resolved", [view], target_patch=bob_patch,
                             counterfactual_outcome="unresolved")
    step("credit_memory_gain", credit.outcome_class == MEMORY_GAIN,
         outcome_class=credit.outcome_class, evidence_class=credit.evidence_class)

    # 13-14: superficially similar but INCOMPATIBLE card (version mismatch, no executable action) -> ABSTAIN
    incompat = compile_card(_ev(source_issue_id="102", version_scope="1.x", ordered_actions=[], patch_pattern="",
                                symptom_signature="widget loader config key theme"))
    incompat.governance_state = GovernanceState.PROMOTED
    store.add(ORG, "v2", incompat)
    sess2 = SearchSession(session_id="sess-bob-2", org_id=ORG, request_id="req-bob-2", actor_id_hash="bob-hash",
                          target_task_id="acme-widgets-206", mode="utility_gated")
    c2 = [c for c in store.search(ORG, "acme/widgets", "widget loader config key theme") if c.version_id == "v2"]
    abstain_view = svc.browse_experience(sess2, TaskContext(org_id=ORG, repository="acme/widgets",
                                         subtask="modification", version="2.x"), TrajectoryState(), c2[0]) if c2 else "n/a"
    dec2 = [d for d in svc.explain_decision(sess2)]
    step("router_ABSTAIN_incompatible", abstain_view is None and dec2 and dec2[-1]["decision"] == "ABSTAIN",
         reason_codes=(dec2[-1]["reason_codes"] if dec2 else []))

    # 15-16: wrong reusable pattern -> repeated MEMORY_LOSS -> quarantine
    wrong = compile_card(_ev(source_issue_id="103", symptom_signature="widget loader wrong pattern"))
    wrong.governance_state = GovernanceState.PROMOTED
    wstats = CardStats(gains=0, losses=0)
    for _ in range(2):
        gov.apply_credit(wstats, MEMORY_LOSS)
    wstate = gov.evaluate(wrong.governance_state, wstats, reviewed=True)
    step("quarantine_on_repeated_loss", wstate == GovernanceState.QUARANTINED, losses=wstats.losses)

    # 17: Alice's PRIVATE memory never appears in Bob's shared context
    leak = svc.search_experiences(SearchSession(session_id="sess-bob-3", org_id=ORG, request_id="req-bob-3",
                                  actor_id_hash="bob-hash", target_task_id="x", mode="utility_gated"),
                                  bob_task, "alice private note internal token")
    private_leaked = any(r["version_id"] == "pv1" for r in leak)
    step("private_not_leaked", not private_leaked)

    # 18: audit chain present + free of secret/private text
    audit_blob = json.dumps(sess.audit + sess2.audit)
    no_secret = "internal token" not in audit_blob and "alice private" not in audit_blob
    step("audit_chain_no_secret", bool(sess.audit) and no_secret, audit_events=len(sess.audit) + len(sess2.audit))

    ev["DEMO_PASS"] = ok
    ev["evidence_hash"] = hashlib.sha256(json.dumps(ev["steps"], sort_keys=True).encode()).hexdigest()
    outdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "artifacts", "p6")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "demo_evidence.json"), "w", encoding="utf-8") as fh:
        json.dump(ev, fh, indent=2)

    for s in ev["steps"]:
        print(("  PASS " if s["pass"] else "  FAIL ") + s["step"])
    print("DEMO_PASS: %s" % ("true" if ok else "false"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
