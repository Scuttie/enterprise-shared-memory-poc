#!/usr/bin/env python3
"""R22-P0.9 §1 — per-target GRADEABILITY driver over the 55-target dev pool.

For one dev target, grade TWO conditions with the BENCHMARK-SPECIFIC official evaluator (pinned ephemeral checkout of
swebench_memory + the official per-instance image, pulled BY DIGEST and verified):
  A. GOLD          = official case `patch`   -> expect resolved, FAIL_TO_PASS complete, PASS_TO_PASS 0 regress
  B. NOOP-BASELINE = NOOP_BASELINE_PATCH (adds .r22_noop; no source/test change) -> expect UNRESOLVED but with the
     tests ACTUALLY EXECUTED (patch_applied=true) — NOT the empty-patch 'No patch' short-circuit.

This driver DOES NOT decide the campaign; it emits a per-target verdict (GRADEABLE / UNGRADEABLE_* / INFRA_FAILURE /
UNKNOWN). No model calls, no secret, paid API = 0. Requires Docker + R22_SCB_UPSTREAM_EXEC_APPROVED=1."""
import argparse
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
ART09 = os.path.join(ROOT, "artifacts", "r22_p09")
MANIFEST = os.path.join(ART09, "dev55_gradeability_manifest.json")

from experiments.r22.runtime import scb_official_grader as SG  # noqa: E402


def _f2p_complete(res):
    ts = (res.get("fail_to_pass_result") or {})
    return bool(ts.get("success")) and not ts.get("failure")


def _p2p_regression(res):
    ts = (res.get("pass_to_pass_result") or {})
    return len(ts.get("failure") or [])


# ---- exact GRADEABLE classification (§1) -------------------------------------
def classify(g, n):
    """Return the per-target label from the two graded conditions. GRADEABLE requires the full gold+noop signature;
    otherwise the MOST SPECIFIC failure bucket. (ImageDigestMismatch / GraderInfraError raised BEFORE collection are
    mapped to UNGRADEABLE_CASE_IMAGE / UNGRADEABLE_TOOLCHAIN by the caller — this handles the value path.)"""
    gie, gio = g.get("image_expected_digest"), g.get("image_observed_digest")
    digest_match = bool(gie) and gie == gio
    gold_infra, noop_infra = bool(g.get("infra_ok")), bool(n.get("infra_ok"))
    gold_te, noop_te = bool(g.get("tests_executed")), bool(n.get("tests_executed"))
    gold_pa, noop_pa = (g.get("patch_applied") is True), (n.get("patch_applied") is True)
    gold_res, noop_res = bool(g.get("resolved")), bool(n.get("resolved"))
    gold_f2p, gold_p2p_reg = _f2p_complete(g), _p2p_regression(g)
    report_ok = bool(g.get("report_found")) and bool(n.get("report_found"))
    rc_ok = (g.get("returncode") == 0) and (n.get("returncode") == 0)

    gradeable = (gold_pa and gold_res and gold_f2p and gold_p2p_reg == 0
                 and noop_pa and (not noop_res)
                 and gold_te and noop_te and digest_match and gold_infra and noop_infra)
    if gradeable:
        return "GRADEABLE"
    # most specific bucket (digest defended first, then infra, then selector, then gold, then unknown)
    if not digest_match:
        return "UNGRADEABLE_CASE_IMAGE"
    if (not report_ok) or (not rc_ok) or (not gold_infra) or (not noop_infra):
        return "INFRA_FAILURE"
    if (not gold_te) or (not noop_te):                       # tests never collected/executed
        return "UNGRADEABLE_SELECTOR"
    if (not gold_res) or (not gold_f2p) or gold_p2p_reg != 0 or (not gold_pa):
        return "UNGRADEABLE_GOLD"
    return "UNKNOWN"                                          # e.g. noop unexpectedly resolved / not applied


# §5 — the FULL raw evidence set per condition (grade() key -> predictable stash name). Recorded as
# {relpath,bytes,sha256} per file (NOT a boolean); the aggregate re-verifies each against the download tree.
EVIDENCE_FILES = (("run_instance_log", "run_instance.log"), ("test_output_txt", "test_output.txt"),
                  ("instance_report_path", "report.json"), ("report_path", "summary_report.json"),
                  ("stdout_path", "stdout.log"), ("stderr_path", "stderr.log"),
                  ("dataset_path", "dataset.json"), ("predictions_path", "prediction.json"))


def _file_meta(path, results_dir):
    data = open(path, "rb").read()
    return {"relpath": os.path.relpath(path, results_dir).replace(os.sep, "/"),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _stash_evidence(res, cond_dir, results_dir):
    """Copy the FULL upstream raw evidence set into predictable names under cond_dir; return {name:{relpath,bytes,sha256}}."""
    os.makedirs(cond_dir, exist_ok=True)
    ev = {}
    for key, dst in EVIDENCE_FILES:
        src = res.get(key)
        if src and os.path.isfile(src):
            d = os.path.join(cond_dir, dst)
            try:
                if os.path.abspath(src) != os.path.abspath(d):
                    shutil.copyfile(src, d)
                ev[dst] = _file_meta(d, results_dir)
            except Exception:
                ev[dst] = None
        else:
            ev[dst] = None
    return ev


def _cell(res):
    """Terse per-condition metric block for the summary."""
    return {"resolved": bool(res.get("resolved")), "patch_applied": res.get("patch_applied"),
            "infra_ok": bool(res.get("infra_ok")), "tests_executed": bool(res.get("tests_executed")),
            "f2p_complete": _f2p_complete(res), "p2p_regression": _p2p_regression(res),
            "report_found": bool(res.get("report_found")), "returncode": res.get("returncode"),
            "patch_sha256": res.get("model_patch_sha256")}


def grade_one(rec, results_dir, checkout):
    """Grade GOLD + NOOP for one target record; return (summary_dict, label)."""
    tid = rec["target_id"]
    route = {"instance_id": tid, "case_path": rec["case_path"], "case_sha256": rec.get("case_sha256"),
             "image": rec.get("image"), "image_digest": rec.get("image_digest")}
    base = {"instance_id": tid, "original_status": rec.get("original_status"),
            "language": rec.get("language"), "subset": rec.get("subset"),
            "repository_cluster": rec.get("repository_cluster")}
    gold_dir, noop_dir = os.path.join(results_dir, tid, "gold"), os.path.join(results_dir, tid, "noop")
    noop = SG.assert_valid_baseline_patch(SG.NOOP_BASELINE_PATCH)   # empty patch is an INVALID control
    gold_patch = json.loads(open(os.path.join(checkout, rec["case_path"]), encoding="utf-8").read()).get("patch") or ""

    # §6 one-pull-per-target: GOLD pulls+verifies the frozen image by digest ONCE and keeps the built instance image
    # (--no-remove-instance-image); NOOP reuses that already-verified local tag (no re-pull).
    # ImageDigestMismatch / GraderInfraError raised before collection classify directly (do not conflate with a model result)
    try:
        g = SG.grade(route, gold_patch, gold_dir, keep_instance_image=True, reuse_pulled_image=False)
        n = SG.grade(route, noop, noop_dir, keep_instance_image=False, reuse_pulled_image=True)
    except SG.ImageDigestMismatch as e:
        base.update({"label": "UNGRADEABLE_CASE_IMAGE", "error": str(e),
                     "image_expected_digest": rec.get("image_digest"), "image_observed_digest": None,
                     "gold": None, "noop_baseline": None, "evidence": {"gold": {}, "noop": {}}})
        return base, "UNGRADEABLE_CASE_IMAGE"
    except SG.GraderInfraError as e:
        base.update({"label": "UNGRADEABLE_TOOLCHAIN", "error": str(e),
                     "image_expected_digest": rec.get("image_digest"), "image_observed_digest": None,
                     "gold": None, "noop_baseline": None, "evidence": {"gold": {}, "noop": {}}})
        return base, "UNGRADEABLE_TOOLCHAIN"

    label = classify(g, n)
    base.update({
        "label": label,
        "image_expected_digest": g.get("image_expected_digest"),
        "image_observed_digest": g.get("image_observed_digest"),
        "image_digest_verified": g.get("image_digest_verified"),
        "case_sha256": rec.get("case_sha256"),
        "noop_patch_sha256": hashlib.sha256(noop.encode()).hexdigest(),
        "gold": _cell(g),
        "noop_baseline": dict(_cell(n), not_shortcircuit=bool(n.get("tests_executed")) and (n.get("patch_applied") is True)),
        "evidence": {"gold": _stash_evidence(g, gold_dir, results_dir),
                     "noop": _stash_evidence(n, noop_dir, results_dir)},
    })
    return base, label


def _out_path(out_arg, tid):
    """Consistent filename scheme grade_<iid>.json; --out overrides in single-instance mode."""
    if out_arg:
        return os.path.abspath(out_arg)
    return os.path.join(ART09, "grade_%s.json" % tid)


def _write(summary, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    json.dump(summary, open(out, "w", encoding="utf-8"), indent=2)


def _skip(out, tid):
    """Idempotent resume: a valid existing summary is a completed grade — do NOT auto-retry a scientific failure."""
    if out and os.path.isfile(out):
        try:
            json.load(open(out, encoding="utf-8"))
            print("SKIP %s (already graded)" % tid); return True
        except Exception:
            return False
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance-id")
    ap.add_argument("--manifest", default=MANIFEST)         # iterate ALL targets when --instance-id absent
    ap.add_argument("--results-dir", default=os.path.join(ART09, "grade_run"))
    ap.add_argument("--out")                                # per-target summary path (single-instance mode)
    a = ap.parse_args()

    manifest = json.load(open(a.manifest, encoding="utf-8"))
    records = manifest["records"]
    results_dir = os.path.abspath(a.results_dir)
    os.makedirs(results_dir, exist_ok=True)

    checkout = SG.ensure_checkout(os.path.join(results_dir, "_scb_upstream"))
    SG.verify_tree_hashes(checkout)

    if a.instance_id:
        tids = [a.instance_id]
    else:
        tids = list(records.keys())                          # --manifest iterate: one grade_<iid>.json per target

    rc = 0
    for tid in tids:
        rec = records.get(tid)
        if not rec:
            print("ERROR: %s not in manifest" % tid); rc = 2; continue
        out = _out_path(a.out if a.instance_id else None, tid)
        if _skip(out, tid):
            continue
        summary, label = grade_one(rec, results_dir, checkout)
        _write(summary, out)
        print("GRADE %s -> %s" % (tid, label)); sys.stdout.flush()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
