#!/usr/bin/env python3
"""R23-B0 §6 — per-target gradeability for SWE-bench Verified via the OFFICIAL swebench harness.

GOLD (official case patch) -> expect resolved; NOOP (deterministic .r23_noop file-only patch) -> tests execute,
expect UNRESOLVED. Official prebuilt image pulled once per target by digest. Credential-free (Docker only; NO model,
NO secret, paid=0). Gated on R23_UPSTREAM_EXEC_APPROVED=1. Not the swebench_memory fork — this is mainline swebench
5.0.2 on the enriched SWE-bench/SWE-bench_Verified dataset (image field present)."""
import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r23")
DATASET = "SWE-bench/SWE-bench_Verified"

NOOP_R23_PATCH = ("diff --git a/.r23_noop b/.r23_noop\n"
                  "new file mode 100644\n--- /dev/null\n+++ b/.r23_noop\n@@ -0,0 +1 @@\n+r23 gradeability noop\n")


class EmptyBaselineRejected(Exception):
    pass


def assert_valid_baseline(patch):
    if not (patch or "").strip():
        raise EmptyBaselineRejected("empty patch short-circuits the harness; use NOOP_R23_PATCH")
    return patch


def _approved():
    return os.environ.get("R23_UPSTREAM_EXEC_APPROVED") == "1"


def _grade(iid, model_patch, results_dir, run_tag):
    os.makedirs(results_dir, exist_ok=True)
    run_id = "r23-%s-%s" % (run_tag, hashlib.sha256((iid + model_patch).encode()).hexdigest()[:8])
    preds = os.path.join(results_dir, run_id + "_preds.jsonl")
    open(preds, "w").write(json.dumps({"instance_id": iid, "model_name_or_path": "r23", "model_patch": model_patch}) + "\n")
    cmd = ["python", "-m", "swebench.harness.run_evaluation", "--dataset_name", DATASET,
           "--instance_ids", iid, "--predictions_path", preds, "--run_id", run_id, "--max_workers", "1"]
    proc = subprocess.run(cmd, cwd=results_dir, capture_output=True, text=True)
    open(os.path.join(results_dir, run_id + "_stdout.log"), "w").write(proc.stdout or "")
    open(os.path.join(results_dir, run_id + "_stderr.log"), "w").write(proc.stderr or "")
    report, rp = None, None
    for p in glob.glob(os.path.join(results_dir, "*%s*.json" % run_id)) + \
             glob.glob(os.path.join(results_dir, "logs", "**", "*%s*" % run_id, "**", "report.json"), recursive=True):
        try:
            r = json.load(open(p))
            if "resolved_ids" in r or "resolved" in r:
                report, rp = r, p; break
        except Exception:
            continue
    resolved = bool(report and (iid in set(report.get("resolved_ids", [])) or report.get("resolved") is True))
    return {"resolved": resolved, "returncode": proc.returncode, "report_found": report is not None,
            "report_path": rp, "run_id": run_id, "preds": preds}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-id", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--results-dir", default=os.path.join(ART, "grader_run"))
    a = ap.parse_args()
    if not _approved():
        print("R23 gradeability execution requires R23_UPSTREAM_EXEC_APPROVED=1 (credential-free docker); refusing.")
        return 3
    iid = a.instance_id
    d = os.path.join(a.results_dir, iid)
    # GOLD = the official dataset gold patch (loaded from the pinned dataset at exec time); NOOP = .r23_noop file.
    import datasets  # noqa: E402  (exec-time only)
    row = [r for r in datasets.load_dataset(DATASET, split="test") if r["instance_id"] == iid][0]
    g = _grade(iid, row["patch"], os.path.join(d, "gold"), "gold")
    n = _grade(iid, assert_valid_baseline(NOOP_R23_PATCH), os.path.join(d, "noop"), "noop")
    gradeable = bool(g["resolved"]) and not n["resolved"] and g["report_found"] and n["report_found"] \
        and g["returncode"] == 0 and n["returncode"] == 0
    label = "GRADEABLE" if gradeable else ("UNGRADEABLE_GOLD" if not g["resolved"] else
             ("UNGRADEABLE_NOOP" if n["resolved"] else "INFRA_FAILURE"))
    out = {"instance_id": iid, "gold_resolved": g["resolved"], "noop_resolved": n["resolved"],
           "label": label, "gold": g, "noop": n, "noop_patch_sha256": hashlib.sha256(NOOP_R23_PATCH.encode()).hexdigest()}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(out, open(a.out, "w"), indent=2)
    print("R23 GRADE", iid, "->", label, "gold", g["resolved"], "noop", n["resolved"])
    return 0 if gradeable else 1


if __name__ == "__main__":
    raise SystemExit(main())
