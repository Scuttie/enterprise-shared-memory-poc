#!/usr/bin/env python3
"""R22 §5 — recompute the paid v2 run counts + hard-cap costs from first principles (no model calls).

Emits configs/r22/paid_run_plan_v2.json and reports/R22_PAID_COST_PLAN_V2.md. All arithmetic is computed here; no
decimal is hard-coded in the plan. Prices are re-checked before execution; the frozen provisional prices below are
stamped with a check date for provenance.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "r22")

PRICE_CHECK_DATE = "2026-08-25"
# provider public per-Mtoken prices (USD); re-checked before any paid run
PRICES = {
    "deepseek-chat": {"in": 0.27, "out": 1.10, "provider": "deepseek", "secret": "DEEPSEEK_API_KEY",
                      "snapshot_pinnable": False, "note": "alias -> MODEL_DRIFT_REPLICATION"},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60, "provider": "openai", "secret": "OPENAI_API_KEY",
                    "snapshot_pinnable": True},
    "gpt-4o": {"in": 2.50, "out": 10.00, "provider": "openai", "secret": "OPENAI_API_KEY",
               "snapshot_pinnable": True},
}
# frozen candidate order for reader-band selection (§3)
READER_ORDER = ["deepseek-chat", "gpt-4o-mini", "gpt-4o"]

# hard per-run token cap (§5)
HARD_IN_TOK = 800_000
HARD_OUT_TOK = 80_000

# run counts (§4) — one source per target; O0 40 reused from reader selection in P2
RUN_COUNTS = {
    "reader_band_per_candidate": 40,        # O0 NO_MEMORY only, per candidate, stop at first in-band
    "p1_smoke": 12 * 7,                     # 84
    "p2_analyzed_cells": 40 * 7,            # 280
    "p2_new_for_selected": 40 * 6,          # 240 (O1-O6; O0 reused)
    "selected_reader_total_new": 40 + 12 * 7 + 40 * 6,  # 364
}


def per_run_usd(model):
    p = PRICES[model]
    return (HARD_IN_TOK / 1e6) * p["in"] + (HARD_OUT_TOK / 1e6) * p["out"]


def build():
    per_run = {m: round(per_run_usd(m), 6) for m in PRICES}
    caps = {}
    for m in PRICES:
        r = per_run_usd(m)
        caps[m] = {
            "per_run_usd": round(r, 6),
            "reader_band_hard_cap": round(r * RUN_COUNTS["reader_band_per_candidate"], 4),
            "p1_hard_cap": round(r * RUN_COUNTS["p1_smoke"], 4),
            "p2_total_hard_cap": round(r * RUN_COUNTS["p2_analyzed_cells"], 4),
            "selected_reader_total_hard_cap": round(r * RUN_COUNTS["selected_reader_total_new"], 4),
        }
    plan = {
        "schema": "r22/paid_run_plan_v2/2.0.0",
        "authoritative": True,
        "supersedes": "configs/r22/paid_run_plan.json (v1) — preserved for provenance",
        "price_check_date": PRICE_CHECK_DATE,
        "hard_per_run_tokens": {"input": HARD_IN_TOK, "output": HARD_OUT_TOK},
        "prices_per_mtok": PRICES,
        "reader_candidate_order": READER_ORDER,
        "reader_band": "[0.10, 0.70] resolved on frozen 40-task dev O0; first in-band candidate wins",
        "run_counts": RUN_COUNTS,
        "per_run_usd": per_run,
        "hard_caps": caps,
        "primary_contrasts": {"Q1": "O5 - O2", "Q2": "O5 - O4", "Q3": "O6 - O5"},
        "product_candidates": ["O4", "O5", "O6"],
        "oracle_upper_bound_not_selectable": "O3",
        "approval_variables": {
            "reader_selection": "R22_READER_SELECTION_BUDGET_USD",
            "p1_smoke": "R22_SMOKE_BUDGET_USD",
            "p2_oracle": "R22_ORACLE_BUDGET_USD",
            "gate": "RUN_APPROVED",
            "forbidden": "R22_MAIN_BUDGET_USD (P3 withheld — power-blocked)",
        },
        "run_order": ["reader-band O0 pilot", "reader lock commit", "P1 12x7", "P1 integrity PASS",
                      "P2 O1-O6 40x6 (reuse O0)", "P2 analysis", "method verdict", "P3 NOT RUN"],
    }
    return plan


def main():
    plan = build()
    os.makedirs(OUT, exist_ok=True)
    json.dump(plan, open(os.path.join(ROOT, "configs", "r22", "paid_run_plan_v2.json"), "w", encoding="utf-8"),
              indent=2)
    # markdown cost table
    rows = ["# R22 §5 — paid v2 cost plan (recomputed)", "",
            "All values computed by `scripts/r22_recompute_paid_costs.py` (no hard-coded decimals). Hard per-run "
            "cap: %d in / %d out tokens. Prices per Mtok checked %s." % (HARD_IN_TOK, HARD_OUT_TOK, PRICE_CHECK_DATE),
            "", "| model | per-run | reader-band 40 | P1 84 | P2 total 280 | selected-reader total 364 |",
            "|---|---:|---:|---:|---:|---:|"]
    for m in READER_ORDER:
        c = plan["hard_caps"][m]
        rows.append("| %s | $%.3f | $%.3f | $%.3f | $%.3f | $%.3f |" % (
            m, c["per_run_usd"], c["reader_band_hard_cap"], c["p1_hard_cap"],
            c["p2_total_hard_cap"], c["selected_reader_total_hard_cap"]))
    rows += ["", "Run counts: reader-band %d/candidate · P1 %d · P2 analyzed %d (O0 40 reused → %d new for the "
             "selected reader). Primary contrasts: Q1 O5−O2 · Q2 O5−O4 · Q3 O6−O5. Product candidates O4/O5/O6 "
             "(O3 is an oracle upper bound, not selectable)." % (
                 RUN_COUNTS["reader_band_per_candidate"], RUN_COUNTS["p1_smoke"],
                 RUN_COUNTS["p2_analyzed_cells"], RUN_COUNTS["selected_reader_total_new"]),
             "", "Approval vars: `R22_READER_SELECTION_BUDGET_USD`, `R22_SMOKE_BUDGET_USD`, "
             "`R22_ORACLE_BUDGET_USD`, `RUN_APPROVED`. **`R22_MAIN_BUDGET_USD` must remain unset (P3 withheld).**"]
    open(os.path.join(ROOT, "reports", "R22_PAID_COST_PLAN_V2.md"), "w", encoding="utf-8").write("\n".join(rows))
    print(json.dumps({m: plan["hard_caps"][m] for m in READER_ORDER}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
