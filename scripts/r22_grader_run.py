#!/usr/bin/env python3
"""R22 §3.2 — grade ONE routed instance for ONE patch condition via the OFFICIAL swebench harness.

No model calls, no test modification, no invented images. Routes to the instance's own subset dataset. Writes a
per-(instance,condition) result JSON so shards are resumable/idempotent. Called by ci-r22-grader-smoke.yml.

Usage: python scripts/r22_grader_run.py --instance <iid> --condition gold|nopatch
"""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "r22")
DATA = os.environ.get("R22_SCB_DATA", os.path.join(ROOT, "artifacts", "r22", "_scb_data"))
RESULTS = os.path.join(OUT, "grader_results")


def _route(iid):
    routes = json.load(open(os.path.join(OUT, "grader_instance_routes.json")))["routes"]
    for r in routes:
        if r["instance_id"] == iid:
            return r
    raise SystemExit("instance %s not in routes" % iid)


def _gold_patch(iid, subset_dataset):
    from datasets import load_dataset
    ds = load_dataset(subset_dataset, split="test")
    for r in ds:
        if r["instance_id"] == iid:
            return r["patch"]
    raise SystemExit("gold patch not found for %s" % iid)


def main():
    a = sys.argv
    iid = a[a.index("--instance") + 1]
    cond = a[a.index("--condition") + 1]
    route = _route(iid)
    subset = route["dataset_name"]
    os.makedirs(RESULTS, exist_ok=True)
    run_id = "r22-%s-%s" % (iid.replace("__", "_"), cond)
    preds_path = os.path.join(RESULTS, "%s_preds.jsonl" % run_id)
    patch = _gold_patch(iid, subset) if cond == "gold" else ""
    with open(preds_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"instance_id": iid, "model_name_or_path": cond, "model_patch": patch}) + "\n")

    cmd = [sys.executable, "-m", "swebench.harness.run_evaluation",
           "--dataset_name", subset, "--instance_ids", iid,
           "--predictions_path", preds_path, "--run_id", run_id,
           "--max_workers", "1", "--timeout", "1800"]
    print("ROUTED %s (%s) cond=%s -> %s" % (iid, route["subset"], cond, subset))
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    sys.stdout.write(proc.stdout[-4000:]); sys.stderr.write(proc.stderr[-2000:])

    # official harness writes <model>.<run_id>.json report
    report = None
    for p in glob.glob(os.path.join(ROOT, "*%s*.json" % run_id)) + glob.glob(os.path.join(ROOT, "**", "*%s*.json" % run_id), recursive=True):
        try:
            report = json.load(open(p, encoding="utf-8")); break
        except Exception:
            continue
    resolved = bool(report and iid in set(report.get("resolved_ids", [])))
    infra_ok = report is not None and proc.returncode == 0
    result = {"instance_id": iid, "subset": route["subset"], "dataset": subset, "condition": cond,
              "resolved": resolved, "harness_report_found": report is not None,
              "returncode": proc.returncode, "infra_ok": infra_ok}
    json.dump(result, open(os.path.join(RESULTS, "%s_result.json" % run_id), "w", encoding="utf-8"), indent=2)
    print(json.dumps(result))
    # exit 0 always: aggregation/gate is done by --verify over all per-task results
    return 0


if __name__ == "__main__":
    sys.exit(main())
