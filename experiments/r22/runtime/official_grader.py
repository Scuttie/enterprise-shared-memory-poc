"""R22 §4 — ONE official grader adapter, used by both G0 and the paid runtime. Routes each instance to a pinned
official dataset and grades the generated patch with the pinned swebench harness in the official (built) image.

Key facts established by the probe: swebench cannot load `jiayuanz3/SWEContextBench` directly (its splits are
Experience/Related, not `test`). So SCB targets are graded by writing a LOCAL SWE-bench-format dataset row (the
official spec: repo/base_commit/test_patch/FAIL_TO_PASS/PASS_TO_PASS/version/environment_setup_commit) and passing
that local file to the harness, which builds the image from base_commit. Enriched-prebuilt targets route to their
pinned SWE-bench/* dataset. No `--dataset_name jiayuanz3/SWEContextBench`, no unpinned loads, no recursive glob.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess

SWEBENCH_VERSION = "swebench==5.0.2"
LOCAL_DATASET_COLS = ["instance_id", "repo", "base_commit", "patch", "test_patch", "problem_statement",
                      "hints_text", "created_at", "version", "FAIL_TO_PASS", "PASS_TO_PASS",
                      "environment_setup_commit"]


def build_local_dataset(scb_row: dict, out_path: str) -> str:
    inst = {c: scb_row.get(c) for c in LOCAL_DATASET_COLS if c in scb_row}
    for k in ("FAIL_TO_PASS", "PASS_TO_PASS"):
        v = inst.get(k)
        if isinstance(v, str):
            try:
                inst[k] = json.loads(v)
            except Exception:
                pass
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(inst) + "\n")
    return out_path


def _find_report(run_id: str, cwd: str):
    # bounded search: cwd top-level + the swebench run dir, not an unrestricted recursive glob
    for pat in (os.path.join(cwd, "*%s*.json" % run_id),
                os.path.join(cwd, "logs", "run_evaluation", run_id, "*", "*.json"),
                os.path.join(cwd, "evaluation_results", "*%s*.json" % run_id)):
        for p in glob.glob(pat):
            try:
                r = json.load(open(p, encoding="utf-8"))
                if "resolved_ids" in r:
                    return r, p
            except Exception:
                continue
    return None, None


def grade_patch(task_route: dict, model_patch: str, results_dir: str) -> dict:
    """task_route from paid_target_routes.json. Returns the official grading result + provenance. Docker required.
    Infrastructure failure (returncode/report-missing) is reported separately, never as a model failure."""
    os.makedirs(results_dir, exist_ok=True)
    iid = task_route["instance_id"]
    import hashlib
    run_id = "r22paid-%s" % hashlib.sha256((iid + model_patch).encode()).hexdigest()[:10]
    preds = os.path.join(results_dir, run_id + "_preds.jsonl")
    with open(preds, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"instance_id": iid, "model_name_or_path": "r22paid",
                             "model_patch": model_patch}) + "\n")

    if task_route.get("route") == "ENRICHED_PREBUILT_IMAGE":
        dataset_arg = task_route["dataset_name"]          # pinned SWE-bench/* (prebuilt image pulled)
    else:
        # OFFICIAL_IMAGE_BUILD: local SWE-bench-format dataset from the SCB row (harness builds the image)
        assert "scb_row" in task_route, "OFFICIAL_IMAGE_BUILD route needs the SCB row to build a local dataset"
        dataset_arg = build_local_dataset(task_route["scb_row"], os.path.join(results_dir, run_id + "_ds.jsonl"))

    cmd = ["python", "-m", "swebench.harness.run_evaluation", "--dataset_name", dataset_arg,
           "--instance_ids", iid, "--predictions_path", preds, "--run_id", run_id, "--max_workers", "1"]
    proc = subprocess.run(cmd, cwd=results_dir, capture_output=True, text=True)
    report, report_path = _find_report(run_id, results_dir)
    resolved = bool(report and iid in set(report.get("resolved_ids", [])))
    infra_ok = report is not None and proc.returncode == 0
    return {
        "instance_id": iid, "grader": "official_swebench", "grader_version": SWEBENCH_VERSION,
        "dataset_arg": dataset_arg, "route": task_route.get("route"),
        "image": task_route.get("image"), "resolved": resolved,
        "report_found": report is not None, "report_path": report_path,
        "returncode": proc.returncode, "infra_ok": infra_ok,
        "stdout_tail": (proc.stdout or "")[-2000:], "stderr_tail": (proc.stderr or "")[-2000:],
        "predictions_path": preds,
    }


def prepare_workspace(task_route: dict, dest: str) -> str:
    """Git-checkout the repo at base_commit for the READER to edit (grading uses the official image separately)."""
    repo = task_route["repository"]
    subprocess.run(["git", "clone", "--depth", "50", "https://github.com/%s.git" % repo, dest],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", dest, "fetch", "--depth", "1", "origin", task_route["base_commit"]],
                   capture_output=True)
    subprocess.run(["git", "-C", dest, "checkout", task_route["base_commit"]], capture_output=True)
    return dest
