#!/usr/bin/env python3
"""R22-P0.8.1 §2/§6 — OFFICIAL SCB grader discrimination smoke (frozen P1 12 targets).

For each target, two conditions graded by the BENCHMARK-SPECIFIC evaluator (pinned ephemeral checkout of
swebench_memory + the official image, pulled BY DIGEST and verified):
  A. GOLD           = official case `patch`         -> expect resolved, FAIL_TO_PASS complete, PASS_TO_PASS 0 regress
  B. NOOP-BASELINE  = NOOP_BASELINE_PATCH (adds .r22_noop; no source/test change) -> expect UNRESOLVED but with the
     tests ACTUALLY EXECUTED (patch_applied=true, tests_status present) — NOT the empty-patch 'No patch' short-circuit.

An EMPTY patch is explicitly rejected as an invalid control. No model calls, no secret, paid API = 0. Requires
Docker + R22_SCB_UPSTREAM_EXEC_APPROVED=1."""
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


def _f2p_complete(res):
    ts = (res.get("fail_to_pass_result") or {})
    return bool(ts.get("success")) and not ts.get("failure")


def _p2p_regression(res):
    ts = (res.get("pass_to_pass_result") or {})
    return len(ts.get("failure") or [])


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

    checkout = SG.ensure_checkout(os.path.join(a.results_dir, "_scb_upstream"))
    SG.verify_tree_hashes(checkout)

    # NOOP baseline is the ONLY valid control; an empty patch would short-circuit (assert that up front).
    noop = SG.assert_valid_baseline_patch(SG.NOOP_BASELINE_PATCH)

    results = {}
    gold_resolved = noop_resolved = infra_fail = digest_ok = 0
    gold_cells = noop_cells = 0
    for iid in ids:
        route = dict(routes[iid]); route["instance_id"] = iid
        route["image_digest"] = images.get(iid, {}).get("digest")
        case = json.loads(open(os.path.join(checkout, route["case_path"]), encoding="utf-8").read())
        gold_patch = case.get("patch") or ""
        try:
            g = SG.grade(route, gold_patch, os.path.join(a.results_dir, iid, "gold"))
            gold_cells += 1
            n = SG.grade(route, noop, os.path.join(a.results_dir, iid, "noop"))
            noop_cells += 1
        except SG.ImageDigestMismatch as e:
            results[iid] = {"image_integrity_error": str(e)}; print("DIGEST-MISMATCH", iid); continue
        except SG.GraderInfraError as e:
            infra_fail += 1; results[iid] = {"infra_error": str(e)}; print("INFRA-FAIL", iid); continue
        gr, nr = bool(g.get("resolved")), bool(n.get("resolved"))
        gold_resolved += gr; noop_resolved += nr
        infra_fail += (not g.get("infra_ok")) + (not n.get("infra_ok"))
        digest_ok += bool(g.get("image_digest_verified")) and (g.get("image_expected_digest") == g.get("image_observed_digest"))
        results[iid] = {
            "image": route["image_digest"] and images[iid]["image"],
            "image_expected_digest": g.get("image_expected_digest"),
            "image_observed_digest": g.get("image_observed_digest"),
            "image_digest_verified": g.get("image_digest_verified"),
            "gold": {"resolved": gr, "patch_applied": g.get("patch_applied"), "infra_ok": g.get("infra_ok"),
                     "tests_executed": g.get("tests_executed"), "f2p_complete": _f2p_complete(g),
                     "p2p_regression": _p2p_regression(g)},
            "noop_baseline": {"resolved": nr, "patch_applied": n.get("patch_applied"), "infra_ok": n.get("infra_ok"),
                              "tests_executed": n.get("tests_executed"),
                              "not_shortcircuit": bool(n.get("tests_executed")) and (n.get("patch_applied") is True)},
        }
        print("SMOKE", iid, "gold", gr, "noop", nr, "noop_tests_exec", n.get("tests_executed"))
        sys.stdout.flush()

    n = len(ids)
    gold_ok = all(r.get("gold", {}).get("resolved") and r["gold"]["patch_applied"] and r["gold"]["infra_ok"]
                  and r["gold"]["f2p_complete"] and r["gold"]["p2p_regression"] == 0
                  for r in results.values() if "gold" in r)
    noop_ok = all((not r["noop_baseline"]["resolved"]) and r["noop_baseline"]["patch_applied"]
                  and r["noop_baseline"]["infra_ok"] and r["noop_baseline"]["tests_executed"]
                  for r in results.values() if "noop_baseline" in r)
    summary = {"targets": n, "pinned_commit": SG.PINNED_COMMIT, "baseline": "noop-baseline",
               "noop_patch_sha256": __import__("hashlib").sha256(noop.encode()).hexdigest(),
               "gold_cells": gold_cells, "noop_cells": noop_cells,
               "gold_resolved": gold_resolved, "noop_resolved": noop_resolved,
               "infra_failures": infra_fail, "image_digest_verified": digest_ok,
               "discrimination_pass": (gold_cells == n and noop_cells == n and gold_resolved == n
                                       and noop_resolved == 0 and infra_fail == 0 and digest_ok == n
                                       and gold_ok and noop_ok),
               "results": results}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(summary, open(a.out, "w", encoding="utf-8"), indent=2)
    print("SCB SMOKE: gold=%d/%d noop_resolved=%d/%d digest_ok=%d/%d infra_fail=%d PASS=%s"
          % (gold_resolved, n, noop_resolved, n, digest_ok, n, infra_fail, summary["discrimination_pass"]))
    return 0 if summary["discrimination_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
