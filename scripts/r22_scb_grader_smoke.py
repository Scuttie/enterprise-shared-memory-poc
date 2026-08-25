#!/usr/bin/env python3
"""R22-P0.8 §6 — OFFICIAL SCB grader discrimination smoke.

For each frozen target: grade the OFFICIAL gold patch (expect resolved) and a no-patch prediction (expect
unresolved) with the BENCHMARK-SPECIFIC evaluator (pinned ephemeral checkout of swebench_memory + official
per-instance image). Requires Docker at runtime and R22_SCB_UPSTREAM_EXEC_APPROVED=1 (compliance gate — upstream
evaluation code has no explicit license). No model calls, no secret, no paid API.

Usage:
  python scripts/r22_scb_grader_smoke.py --manifest oracle_smoke_manifest.json --out artifacts/r22/scb_grader_smoke.json
  python scripts/r22_scb_grader_smoke.py --instance-ids apache__lucene-13388 astropy__astropy-14500 --out ...
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
ART = os.path.join(ROOT, "artifacts", "r22")

from experiments.r22.runtime import scb_official_grader as SG  # noqa: E402


def _frozen_ids(manifest_name):
    m = json.load(open(os.path.join(ART, manifest_name), encoding="utf-8"))
    out = []
    for t in m["task_list"]:
        if t.get("target_id") not in out:
            out.append(t["target_id"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--instance-ids", nargs="*")
    ap.add_argument("--out", required=True)
    ap.add_argument("--results-dir", default=os.path.join(ART, "_scb_smoke_run"))
    a = ap.parse_args()

    ids = a.instance_ids or _frozen_ids(a.manifest)
    routes = json.load(open(os.path.join(ART, "scb_case_route_manifest.json"), encoding="utf-8"))["cases"]
    images = json.load(open(os.path.join(ART, "scb_image_manifest.json"), encoding="utf-8"))["images"]

    # single ephemeral checkout reused across targets (the gold patch lives in the official case JSON)
    checkout = SG.ensure_checkout(os.path.join(a.results_dir, "_scb_upstream"))
    SG.verify_tree_hashes(checkout)

    results = {}
    gold_resolved = nopatch_resolved = infra_fail = 0
    for iid in ids:
        route = dict(routes[iid])
        route["instance_id"] = iid
        route["image_digest"] = images.get(iid, {}).get("digest")
        case = json.loads(open(os.path.join(checkout, route["case_path"]), encoding="utf-8").read())
        gold_patch = case.get("patch") or ""
        try:
            g = SG.grade(route, gold_patch, os.path.join(a.results_dir, iid, "gold"))
            n = SG.grade(route, "", os.path.join(a.results_dir, iid, "nopatch"))
        except SG.GraderInfraError as e:
            infra_fail += 1
            results[iid] = {"infra_error": str(e)}
            print("INFRA-FAIL", iid, str(e)[:120]); continue
        gr = bool(g.get("resolved")); nr = bool(n.get("resolved"))
        gold_resolved += gr; nopatch_resolved += nr
        infra_fail += (not g.get("infra_ok")) + (not n.get("infra_ok"))
        results[iid] = {"image": route.get("image", images.get(iid, {}).get("image")),
                        "image_digest": route["image_digest"],
                        "gold_resolved": gr, "nopatch_resolved": nr,
                        "gold_infra_ok": g.get("infra_ok"), "nopatch_infra_ok": n.get("infra_ok"),
                        "gold_report": g.get("report_path"), "elapsed_sec": g.get("elapsed_sec")}
        print("SMOKE", iid, "gold_resolved", gr, "nopatch_resolved", nr)
        sys.stdout.flush()

    n = len(ids)
    summary = {"targets": n, "pinned_commit": SG.PINNED_COMMIT,
               "gold_resolved": gold_resolved, "nopatch_resolved": nopatch_resolved,
               "infra_failures": infra_fail,
               "discrimination_pass": (gold_resolved == n and nopatch_resolved == 0 and infra_fail == 0),
               "results": results}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(summary, open(a.out, "w", encoding="utf-8"), indent=2)
    print("SCB SMOKE: gold_resolved=%d/%d nopatch_resolved=%d/%d infra_fail=%d PASS=%s"
          % (gold_resolved, n, nopatch_resolved, n, infra_fail, summary["discrimination_pass"]))
    return 0 if summary["discrimination_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
