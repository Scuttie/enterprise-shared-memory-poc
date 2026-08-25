"""R22-P0.8 §5 — BENCHMARK-SPECIFIC official SWE-ContextBench grader adapter.

This module INVOKES the pinned upstream evaluator; it does NOT vendor it. At grade time it makes an ephemeral
pinned checkout of `jiayuanz3/SWEContextBench` at the frozen commit, verifies the evaluator file hashes against
`artifacts/r22/scb_official_evaluator_lock.json`, writes predictions in the official format, and runs
`python -m swebench_memory.harness.run_evaluation` from that checkout using the official per-instance image
`jiayuanz3/swecontextbench:<instance-tag>`. It NEVER calls generic `swebench.harness.run_evaluation` for SCB
Related targets, and never synthesizes an `image` field for generic swebench 5.0.2.

Rights: the upstream evaluation code has NO explicit license (see reports/R22_UPSTREAM_RIGHTS_STATUS.md). This
adapter only executes an ephemeral pinned checkout and copies nothing into our repo/wheel/image/release. Execution
is gated on an explicit approval flag; without it the adapter refuses to run (compliance, not a technical block).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ART = os.path.join(ROOT, "artifacts", "r22")

UPSTREAM_REPO_URL = "https://github.com/jiayuanz3/SWEContextBench.git"
PINNED_COMMIT = "31bb04155f52b184bf31b220e3cff0607ac9c953"
IMAGE_REPOSITORY = "jiayuanz3/swecontextbench"       # HARDENED_IMAGE_REPOSITORY in upstream run_evaluation.py:35
EVALUATOR_MODULE = "swebench_memory.harness.run_evaluation"

# The exact upstream derivation (run_evaluation.py:2954 / :3345):
#   image_tag = f"{HARDENED_IMAGE_REPOSITORY}:{instance_id.replace('__', '.').lower()}"
def derive_image_tag(instance_id: str) -> str:
    return "%s:%s" % (IMAGE_REPOSITORY, instance_id.replace("__", ".").lower())


class UpstreamExecutionNotApproved(Exception):
    """Raised when the adapter would execute the unlicensed upstream evaluator without explicit approval."""


class GraderInfraError(Exception):
    """Infrastructure failure (checkout/hash/harness) — never conflated with a model (unresolved) result."""


def _approved() -> bool:
    return os.environ.get("R22_SCB_UPSTREAM_EXEC_APPROVED") == "1"


def ensure_checkout(cache_dir: str) -> str:
    """Ephemeral pinned checkout of the upstream evaluator. Returns the checkout dir. No redistribution."""
    os.makedirs(cache_dir, exist_ok=True)
    if not os.path.isdir(os.path.join(cache_dir, ".git")):
        subprocess.run(["git", "init", "-q"], cwd=cache_dir, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", UPSTREAM_REPO_URL], cwd=cache_dir,
                       capture_output=True)
    subprocess.run(["git", "fetch", "--depth", "1", "origin", PINNED_COMMIT], cwd=cache_dir,
                   check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-q", PINNED_COMMIT], cwd=cache_dir, check=True, capture_output=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cache_dir, capture_output=True, text=True).stdout.strip()
    if head != PINNED_COMMIT:
        raise GraderInfraError("checkout HEAD %s != pinned %s" % (head, PINNED_COMMIT))
    return cache_dir


def verify_tree_hashes(checkout_dir: str) -> dict:
    """sha256 the evaluator files and compare to the frozen lock. Fail closed on any mismatch."""
    lock = json.load(open(os.path.join(ART, "scb_official_evaluator_lock.json"), encoding="utf-8"))
    mism = {}
    for path, meta in lock["files"].items():
        fp = os.path.join(checkout_dir, path)
        if not os.path.isfile(fp):
            mism[path] = "missing"
            continue
        got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
        if got != meta["sha256"]:
            mism[path] = {"expected": meta["sha256"], "got": got}
    if mism:
        raise GraderInfraError("upstream evaluator hash mismatch vs frozen lock: %s" % json.dumps(mism))
    return {"verified_files": len(lock["files"]), "pinned_commit": PINNED_COMMIT}


def _load_case(checkout_dir: str, case_route: dict) -> dict:
    """Read the OFFICIAL case JSON from the pinned checkout (authoritative F2P/P2P/test_patch)."""
    fp = os.path.join(checkout_dir, case_route["case_path"])
    if not os.path.isfile(fp):
        raise GraderInfraError("official case file absent in checkout: %s" % case_route["case_path"])
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    if case_route.get("case_sha256") and got != case_route["case_sha256"]:
        raise GraderInfraError("case JSON hash drift for %s" % case_route["instance_id"])
    return json.loads(open(fp, encoding="utf-8").read())


def grade(case_route: dict, model_patch: str, results_dir: str, model_name: str = "r22-reader") -> dict:
    """Grade one (instance, patch) with the OFFICIAL SCB evaluator + OFFICIAL image. Docker required at runtime.

    Returns durable evidence. Infra failure is reported separately from a model (unresolved) verdict. Executing the
    unlicensed upstream code requires R22_SCB_UPSTREAM_EXEC_APPROVED=1 (compliance gate)."""
    if not _approved():
        raise UpstreamExecutionNotApproved(
            "SCB official evaluator execution requires R22_SCB_UPSTREAM_EXEC_APPROVED=1 "
            "(upstream evaluation code has no explicit license; see R22_UPSTREAM_RIGHTS_STATUS.md)")
    os.makedirs(results_dir, exist_ok=True)
    iid = case_route["instance_id"]
    checkout = ensure_checkout(os.path.join(results_dir, "_scb_upstream"))
    lock_info = verify_tree_hashes(checkout)
    case = _load_case(checkout, case_route)

    run_id = "r22scb-%s" % hashlib.sha256((iid + (model_patch or "")).encode()).hexdigest()[:10]
    # official dataset row = the official case JSON (single instance); official predictions row
    ds_path = os.path.join(results_dir, run_id + "_dataset.json")
    preds_path = os.path.join(results_dir, run_id + "_predictions.json")
    json.dump([case], open(ds_path, "w", encoding="utf-8"))
    json.dump([{"instance_id": iid, "model_name_or_path": model_name, "model_patch": model_patch or ""}],
              open(preds_path, "w", encoding="utf-8"))

    env = dict(os.environ)
    env["PYTHONPATH"] = checkout + os.pathsep + env.get("PYTHONPATH", "")
    image_tag = derive_image_tag(iid)
    t0 = time.time()
    proc = subprocess.run(
        ["python", "-m", EVALUATOR_MODULE, "--dataset_name", ds_path,
         "--predictions_path", preds_path, "--run_id", run_id],
        cwd=results_dir, env=env, capture_output=True, text=True)
    elapsed = time.time() - t0

    report_path = os.path.join(results_dir, run_id + ".json")
    report = json.load(open(report_path, encoding="utf-8")) if os.path.isfile(report_path) else None
    per = (report or {}).get(iid, {}) if isinstance(report, dict) else {}
    resolved = bool(report and iid in set(report.get("resolved_ids", [])))
    report_found = report is not None
    infra_ok = report_found and proc.returncode == 0
    return {
        "instance_id": iid, "grader": "scb_official", "grader_module": EVALUATOR_MODULE,
        "upstream_repo": UPSTREAM_REPO_URL, "pinned_commit": PINNED_COMMIT,
        "evaluator_hash_verified": lock_info["verified_files"],
        "case_path": case_route["case_path"], "case_sha256": case_route.get("case_sha256"),
        "image": image_tag, "image_digest": case_route.get("image_digest"),
        "resolved": resolved,
        "fail_to_pass_result": per.get("tests_status", {}).get("FAIL_TO_PASS") if isinstance(per, dict) else None,
        "pass_to_pass_result": per.get("tests_status", {}).get("PASS_TO_PASS") if isinstance(per, dict) else None,
        "patch_applied": per.get("patch_successfully_applied") if isinstance(per, dict) else None,
        "report_found": report_found, "report_path": report_path if report_found else None,
        "returncode": proc.returncode, "infra_ok": infra_ok, "elapsed_sec": round(elapsed, 2),
        "predictions_path": preds_path, "dataset_path": ds_path,
        "stdout_tail": (proc.stdout or "")[-2500:], "stderr_tail": (proc.stderr or "")[-2500:],
    }
