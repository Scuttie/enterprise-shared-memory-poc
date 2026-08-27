#!/usr/bin/env python3
"""R22 §9 — fail-closed paid analysis over a completed P2 results file. Exits non-zero on any integrity error;
NEVER uses `|| true`. Computes Q1/Q2/Q3 (McNemar + Holm + task & repo-cluster bootstrap), diagnostics, stage
adoption, and information retention. No model calls.

Usage: python scripts/r22_paid_analyze.py --input <p2 results.jsonl> --expected-cells 280 --out <analysis.json>
"""
import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from experiments.r22 import statistics as ST                  # noqa: E402
from experiments.r22 import mechanism_audit as MA             # noqa: E402
from experiments.r22 import information_retention as IR       # noqa: E402
from experiments.r22.runtime.integrity import check_cell      # noqa: E402

REQUIRED = ["target_id", "arm", "resolved", "patch_sha256", "raw_response_sha256", "usage",
            "returned_model", "injection"]


def fail_closed(records, expected_cells):
    errs = []
    seen = set()
    returned_models = set()
    for r in records:
        for f in REQUIRED:
            if f not in r or r[f] in (None,):
                if f == "raw_response_sha256" and r.get("terminal", "ok") != "ok":
                    continue
                errs.append("%s: missing %s" % (r.get("cell_key"), f))
        k = (r.get("target_id"), r.get("arm"))
        if k in seen:
            errs.append("duplicate cell %s" % (k,))
        seen.add(k)
        if r.get("usage") and (r["usage"].get("cost_usd") is None):
            errs.append("%s: missing cost" % r.get("cell_key"))
        if r.get("returned_model"):
            returned_models.add(r["returned_model"])
        errs += ["%s: %s" % (r.get("cell_key"), m) for m in check_cell(r)]
        if not r.get("repo_cluster"):
            errs.append("%s: missing repository cluster id" % r.get("cell_key"))
        g = r.get("grader") or {}
        if isinstance(g, dict) and g.get("returncode") not in (None, 0) and r.get("terminal", "ok") == "ok":
            errs.append("%s: official grader error (returncode %s)" % (r.get("cell_key"), g.get("returncode")))
    if len(seen) != expected_cells:
        errs.append("incomplete table: %d/%d cells" % (len(seen), expected_cells))
    if len(returned_models) > 1:
        errs.append("reader model drift across campaign: %s" % returned_models)
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--expected-cells", type=int, default=280)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not os.path.isfile(a.input):
        print("R22 ANALYSIS: no input results file"); return 1
    records = [json.loads(l) for l in open(a.input, encoding="utf-8") if l.strip()]

    errs = fail_closed(records, a.expected_cells)
    if errs:
        print("R22 ANALYSIS: FAIL (fail-closed)")
        for e in errs[:20]:
            print("  -", e)
        return 1

    by = defaultdict(list)
    for r in records:
        by[r["arm"]].append(r)
    primary = {}
    for name, (x, y) in {"Q1": ("O5", "O2"), "Q2": ("O5", "O4"), "Q3": ("O6", "O5")}.items():
        pr, cl = ST.paired(by, x, y)
        m = ST.mcnemar(pr)
        primary[name] = {"contrast": "%s-%s" % (x, y), **m,
                         "task_boot": ST.bootstrap_ci(pr), "cluster_boot": ST.bootstrap_ci(pr, cl)}
    holm = ST.holm({k: v["p_value"] for k, v in primary.items()})
    for k in primary:
        primary[k]["holm_adjusted_p"] = holm[k]
    diagnostics = {}
    for name, (x, y) in {"O1-O0": ("O1", "O0"), "O2-O1": ("O2", "O1"), "O3-O0": ("O3", "O0"),
                         "O3-O2": ("O3", "O2"), "O4-O1": ("O4", "O1"), "O5-O1": ("O5", "O1"),
                         "O6-O1": ("O6", "O1")}.items():
        pr, _ = ST.paired(by, x, y)
        diagnostics[name] = ST.mcnemar(pr)

    analysis = {"schema": "r22/paid_analysis/1.0.0", "cells": len(records),
                "note": "DEVELOPMENT method-discovery; not confirmatory. O3 not selectable.",
                "primary_holm": primary, "diagnostics": diagnostics,
                "mechanism": MA.stage_and_adoption(records), "information_retention": IR.retention(records),
                "result_hash": hashlib.sha256(json.dumps(sorted(r["cell_key"] for r in records)).encode()).hexdigest()}
    json.dump(analysis, open(a.out, "w", encoding="utf-8"), indent=2, default=str)
    print(json.dumps({"Q1": primary["Q1"]["holm_adjusted_p"], "Q2": primary["Q2"]["holm_adjusted_p"],
                      "Q3": primary["Q3"]["holm_adjusted_p"], "cells": len(records)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
