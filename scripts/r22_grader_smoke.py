#!/usr/bin/env python3
"""R22 §2 — official-grader smoke prep + verdict (clean-room; delegates grading to the SWE-bench harness).

Selects 12 fixed tasks (varied repos, CLEAN + dev-only), writes a task manifest, a GOLD-patch predictions file
(expected resolved) and a NO-patch predictions file (expected unresolved). The CI workflow runs the official
`swebench` harness on both and this script verifies discrimination. NO model calls, NO benchmark-test modification.

Usage:
  python scripts/r22_grader_smoke.py --prepare        # emit manifest + predictions
  python scripts/r22_grader_smoke.py --verify <gold_report.json> <nopatch_report.json>
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.environ.get("R22_SCB_DATA", os.path.join(ROOT, "artifacts", "r22", "_scb_data"))
OUT = os.path.join(ROOT, "artifacts", "r22")
RUN_ID = "r22-grader-smoke"


def prepare():
    import pandas as pd
    exp = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Experience.parquet")).drop_duplicates("instance_id")
    dev = json.load(open(os.path.join(OUT, "dev_manifest_v2.json")))["pairs"]
    src_ids = sorted(set(p["source_id"] for p in dev))
    exp_by = {r["instance_id"]: r for _, r in exp.iterrows()}
    # deterministic 12: spread across distinct repositories
    picked, seen_repo = [], set()
    for sid in sorted(src_ids, key=lambda s: hashlib.sha256(s.encode()).hexdigest()):
        row = exp_by.get(sid)
        if row is None:
            continue
        if row["repo"] in seen_repo and len(seen_repo) < 12:
            continue
        seen_repo.add(row["repo"]); picked.append(row)
        if len(picked) == 12:
            break
    if len(picked) < 12:   # fill remaining ignoring repo spread
        for sid in sorted(src_ids):
            if len(picked) == 12:
                break
            row = exp_by.get(sid)
            if row is not None and row["instance_id"] not in {p["instance_id"] for p in picked}:
                picked.append(row)

    manifest = [{"instance_id": r["instance_id"], "repo": r["repo"], "base_commit": r["base_commit"],
                 "environment_setup_commit": r.get("environment_setup_commit"),
                 "FAIL_TO_PASS": r["FAIL_TO_PASS"], "PASS_TO_PASS": r["PASS_TO_PASS"]} for r in picked]
    gold = [{"instance_id": r["instance_id"], "model_name_or_path": "gold",
             "model_patch": r["patch"]} for r in picked]
    nopatch = [{"instance_id": r["instance_id"], "model_name_or_path": "nopatch",
                "model_patch": ""} for r in picked]
    os.makedirs(OUT, exist_ok=True)
    json.dump({"schema": "r22/grader_smoke_manifest/1.0.0", "run_id": RUN_ID, "tasks": manifest,
               "repositories": sorted({m["repo"] for m in manifest})},
              open(os.path.join(OUT, "grader_smoke_manifest.json"), "w", encoding="utf-8"), indent=2, default=str)
    with open(os.path.join(OUT, "gold_predictions.jsonl"), "w", encoding="utf-8") as fh:
        for p in gold:
            fh.write(json.dumps(p) + "\n")
    with open(os.path.join(OUT, "nopatch_predictions.jsonl"), "w", encoding="utf-8") as fh:
        for p in nopatch:
            fh.write(json.dumps(p) + "\n")
    print("prepared 12 tasks across %d repos" % len({m["repo"] for m in manifest}))
    return 0


def _resolved_ids(report_path):
    r = json.load(open(report_path, encoding="utf-8"))
    # swebench run_evaluation report schema
    return set(r.get("resolved_ids", r.get("resolved", [])))


def verify_sharded():
    """Aggregate per-(instance,condition) results written by scripts/r22_grader_run.py."""
    import glob
    manifest = json.load(open(os.path.join(OUT, "grader_smoke_manifest.json")))
    ids = [t["instance_id"] for t in manifest["tasks"]]
    res = {}
    for p in glob.glob(os.path.join(OUT, "grader_results", "*_result.json")):
        r = json.load(open(p, encoding="utf-8"))
        res[(r["instance_id"], r["condition"])] = r
    gold_ok = sum(1 for i in ids if res.get((i, "gold"), {}).get("resolved"))
    nop_bad = sum(1 for i in ids if res.get((i, "nopatch"), {}).get("resolved"))
    completeness = sum(1 for i in ids for c in ("gold", "nopatch") if (i, c) in res)
    infra_fail = sum(1 for i in ids for c in ("gold", "nopatch")
                     if (i, c) in res and not res[(i, c)]["infra_ok"])
    per_task = {i: {c: (res.get((i, c), {}).get("resolved"),
                        res.get((i, c), {}).get("infra_ok")) for c in ("gold", "nopatch")} for i in ids}
    result = {"schema": "r22/grader_smoke/1.0.0", "run_id": RUN_ID, "tasks": len(ids),
              "gold_resolved": gold_ok, "gold_resolved_expected": len(ids),
              "nopatch_resolved": nop_bad, "nopatch_resolved_expected": 0,
              "result_completeness": completeness, "result_completeness_expected": 2 * len(ids),
              "infrastructure_failures": infra_fail, "official_tests_modified": 0,
              "gold_resolved_all": gold_ok == len(ids), "nopatch_all_unresolved": nop_bad == 0,
              "per_task": per_task}
    result["PASS"] = (result["gold_resolved_all"] and result["nopatch_all_unresolved"]
                      and completeness == 2 * len(ids) and infra_fail == 0)
    json.dump(result, open(os.path.join(OUT, "grader_smoke.json"), "w", encoding="utf-8"), indent=2, default=str)
    print(json.dumps({k: result[k] for k in ("tasks", "gold_resolved", "nopatch_resolved",
          "result_completeness", "infrastructure_failures", "PASS")}, indent=2))
    if not result["PASS"]:
        print("R22_MIXED_GRADER_TECHNICAL_BLOCK — see per_task in artifacts/r22/grader_smoke.json")
    return 0 if result["PASS"] else 1


if __name__ == "__main__":
    if "--prepare" in sys.argv:
        raise SystemExit(prepare())
    if "--verify-sharded" in sys.argv:
        raise SystemExit(verify_sharded())
    print(__doc__)
    raise SystemExit(2)
