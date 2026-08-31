#!/usr/bin/env python3
"""R23-B0 §6 — fail-closed gradeability aggregate. Derives per-label counts from downloaded grade_<iid>.json; exits
nonzero if any requested target lacks a terminal record or is INFRA_FAILURE. GRADEABLE count is a result, not a gate.
Credential-free."""
import argparse
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r23")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-dir", required=True)
    ap.add_argument("--out", default=os.path.join(ART, "gradeability_results.json"))
    a = ap.parse_args()
    per = {}
    for p in glob.glob(os.path.join(a.download_dir, "**", "grade_*.json"), recursive=True):
        try:
            d = json.load(open(p, encoding="utf-8"))
            per[d["instance_id"]] = d.get("label", "UNKNOWN")
        except Exception:
            pass
    from collections import Counter
    counts = dict(Counter(per.values()))
    infra = counts.get("INFRA_FAILURE", 0) + counts.get("UNKNOWN", 0)
    complete = infra == 0 and len(per) > 0
    out = {"targets": len(per), "label_counts": counts, "gradeable": counts.get("GRADEABLE", 0),
           "audit_complete": complete, "per_target_label": per}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=2)
    print("R23 GRADEABILITY: targets=%d gradeable=%d complete=%s counts=%s"
          % (len(per), counts.get("GRADEABLE", 0), complete, counts))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
