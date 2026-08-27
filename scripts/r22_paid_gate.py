#!/usr/bin/env python3
"""R22 §8 — paid-run gate validator (credential-free; NO model calls, NO secret values printed).

Checks that a paid stage may start: RUN_APPROVED is exactly 'RUN_APPROVED', the approved budget >= the v2 hard cap
for the chosen stage+model, and the required secret NAME is provided (never its value). Exits non-zero if any gate
fails. Used as the first step of every paid workflow.

Usage: python scripts/r22_paid_gate.py --stage reader_band|p1|p2 --model <m> \
         --budget <usd> --run-approved <val> --secret-name <NAME>
"""
import argparse
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _caps(model):
    spec = importlib.util.spec_from_file_location(
        "r22cost", os.path.join(ROOT, "scripts", "r22_recompute_paid_costs.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    plan = m.build()
    return plan["hard_caps"][model], plan


STAGE_CAP = {"reader_band": "reader_band_hard_cap", "p1": "p1_hard_cap", "p2": "p2_total_hard_cap"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=list(STAGE_CAP))
    ap.add_argument("--model", required=True)
    ap.add_argument("--budget", type=float, required=True)
    ap.add_argument("--run-approved", required=True)
    ap.add_argument("--secret-name", required=True)
    ap.add_argument("--reader-candidate", help="§8: model being selected; enforced against the frozen order")
    ap.add_argument("--decided", default="", help="§8: comma list of candidates already decided out-of-band")
    a = ap.parse_args()

    fails = []
    if a.run_approved != "RUN_APPROVED":
        fails.append("RUN_APPROVED gate: value is not exactly 'RUN_APPROVED'")
    # §8 — a human must not skip directly to a later reader candidate
    if a.reader_candidate:
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from experiments.r22.runtime.candidate_order import assert_not_skipping, CandidateOrderViolation
        try:
            assert_not_skipping(a.reader_candidate, [x for x in a.decided.split(",") if x])
        except CandidateOrderViolation as e:
            fails.append(str(e))
    try:
        caps, _ = _caps(a.model)
    except KeyError:
        print("unknown model %s" % a.model); return 2
    hard_cap = caps[STAGE_CAP[a.stage]]
    if a.budget < hard_cap:
        fails.append("budget $%.4f < %s hard cap $%.4f for %s" % (a.budget, a.stage, hard_cap, a.model))
    if not a.secret_name or a.secret_name.strip() == "":
        fails.append("secret NAME not provided")
    # never print the secret VALUE; only confirm the named env var is present (name-only)
    present = os.environ.get(a.secret_name) is not None
    if a.stage != "gate-dry" and not present:
        fails.append("named secret env %s is not present in this runner" % a.secret_name)
    # P3 main budget must never be set
    if os.environ.get("R22_MAIN_BUDGET_USD") is not None:
        fails.append("R22_MAIN_BUDGET_USD is set — P3 is withheld; refuse")

    if fails:
        print("R22 PAID GATE: REFUSED")
        for f in fails:
            print("  - " + f)
        return 1
    print("R22 PAID GATE: PASS (stage=%s model=%s budget=$%.4f >= hard cap $%.4f; secret name present; "
          "no secret value printed)" % (a.stage, a.model, a.budget, hard_cap))
    return 0


if __name__ == "__main__":
    sys.exit(main())
