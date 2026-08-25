#!/usr/bin/env python3
"""R22-P0.8.2 §3 — fail-closed aggregate of the 12 SCB smoke shards.

Derives the campaign verdict from DOWNLOADED shard artifacts (per-target summary JSON + the raw evidence tree),
NOT from console output. Verdict is PASS only when every §3 gate holds. Exits non-zero otherwise. Writes:
  artifacts/r22/scb_grader_smoke.json, artifacts/r22/scb_grader_smoke_evidence_manifest.json,
  artifacts/r22/SHA256SUMS, and fills the results block of reports/R22_SCB_GRADER_REPRODUCTION.md."""
import argparse
import glob
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r22")
REPORT = os.path.join(ROOT, "reports", "R22_SCB_GRADER_REPRODUCTION.md")
COND_EVIDENCE = ["run_instance.log", "test_output.txt"]   # raw execution evidence required per condition


def _frozen_ids(manifest_path):
    m = json.load(open(manifest_path, encoding="utf-8"))
    out = []
    for t in m["task_list"]:
        if t.get("target_id") not in out:
            out.append(t["target_id"])
    return out


def _sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _has_evidence(download_dir, iid, cond):
    """True iff every required raw evidence file exists somewhere under .../<iid>/<cond>/ in the download tree."""
    found = {}
    for name in COND_EVIDENCE:
        hits = glob.glob(os.path.join(download_dir, "**", iid, cond, name), recursive=True)
        found[name] = hits[0] if hits else None
    stdout_hits = glob.glob(os.path.join(download_dir, "**", iid, cond, "*_stdout.log"), recursive=True)
    found["stdout"] = stdout_hits[0] if stdout_hits else None
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-dir", required=True)
    ap.add_argument("--manifest", default=os.path.join(ART, "oracle_smoke_manifest.json"))
    ap.add_argument("--out", default=os.path.join(ART, "scb_grader_smoke.json"))
    ap.add_argument("--evidence-out", default=os.path.join(ART, "scb_grader_smoke_evidence_manifest.json"))
    ap.add_argument("--sha256sums", default=os.path.join(ART, "SHA256SUMS"))
    ap.add_argument("--report", default=REPORT)
    a = ap.parse_args()

    frozen = _frozen_ids(a.manifest)
    frozen_set = set(frozen)

    # collect per-instance summaries from the downloaded artifacts; a second summary for the same target = dup shard
    summaries = {}
    dup_shard_count = 0
    for p in sorted(glob.glob(os.path.join(a.download_dir, "**", "scb_grader_smoke_*.json"), recursive=True)):
        base = os.path.basename(p)
        iid = base[len("scb_grader_smoke_"):-len(".json")]
        if iid not in frozen_set:
            continue
        if iid in summaries:
            dup_shard_count += 1
            continue
        try:
            summaries[iid] = json.load(open(p, encoding="utf-8"))
        except Exception:
            pass

    per = {}
    evidence = {}
    counts = dict(summary_files=0, gold_cells=0, noop_cells=0,
                  gold_resolved=0, gold_patch_applied=0, gold_tests_executed=0, gold_f2p_complete=0,
                  gold_p2p_regressions=0, noop_resolved=0, noop_patch_applied=0, noop_tests_executed=0,
                  noop_shortcircuit=0, infra_failures=0, digest_match=0, missing_raw_evidence=0)
    dup_cells = dup_shard_count      # duplicate shard == duplicate target/condition cells

    for iid in frozen:
        s = summaries.get(iid)
        cell = {"present": s is not None}
        if not s:
            counts["missing_raw_evidence"] += len(COND_EVIDENCE) * 2
            per[iid] = {"present": False}; continue
        counts["summary_files"] += 1
        # the per-shard summary stores one target under results[iid]
        r = (s.get("results") or {}).get(iid)
        if not r or "gold" not in r or "noop_baseline" not in r:
            per[iid] = {"present": True, "malformed": True}
            counts["missing_raw_evidence"] += len(COND_EVIDENCE) * 2
            continue
        g, n = r["gold"], r["noop_baseline"]
        counts["gold_cells"] += 1; counts["noop_cells"] += 1
        counts["gold_resolved"] += bool(g.get("resolved"))
        counts["gold_patch_applied"] += (g.get("patch_applied") is True)
        counts["gold_tests_executed"] += bool(g.get("tests_executed"))
        counts["gold_f2p_complete"] += bool(g.get("f2p_complete"))
        counts["gold_p2p_regressions"] += int(g.get("p2p_regression") or 0)
        counts["noop_resolved"] += bool(n.get("resolved"))
        counts["noop_patch_applied"] += (n.get("patch_applied") is True)
        counts["noop_tests_executed"] += bool(n.get("tests_executed"))
        counts["noop_shortcircuit"] += (0 if n.get("not_shortcircuit") else 1)
        counts["infra_failures"] += (not g.get("infra_ok")) + (not n.get("infra_ok"))
        counts["digest_match"] += (bool(r.get("image_digest_verified"))
                                   and r.get("image_expected_digest") == r.get("image_observed_digest"))
        # raw evidence must be present in the downloaded tree (not just referenced in the summary)
        ev = {}
        for cond in ("gold", "noop"):
            found = _has_evidence(a.download_dir, iid, cond)
            ev[cond] = {k: (v is not None) for k, v in found.items()}
            for name in COND_EVIDENCE:
                if not found.get(name):
                    counts["missing_raw_evidence"] += 1
        evidence[iid] = ev
        per[iid] = {"present": True, "gold": g, "noop_baseline": n,
                    "image_expected_digest": r.get("image_expected_digest"),
                    "image_observed_digest": r.get("image_observed_digest"),
                    "case_sha256": r.get("case_sha256"), "noop_patch_sha256": r.get("noop_patch_sha256")}

    N = 12
    target_ids = sorted(k for k in summaries)
    gates = {
        "unique_target_ids": len(target_ids) == N,
        "target_set_equals_frozen": set(target_ids) == frozen_set,
        "summary_files": counts["summary_files"] == N,
        "gold_cells": counts["gold_cells"] == N,
        "noop_cells": counts["noop_cells"] == N,
        "total_cells": counts["gold_cells"] + counts["noop_cells"] == 2 * N,
        "no_duplicate_cells": dup_cells == 0,
        "gold_resolved": counts["gold_resolved"] == N,
        "gold_patch_applied": counts["gold_patch_applied"] == N,
        "gold_tests_executed": counts["gold_tests_executed"] == N,
        "gold_f2p_complete": counts["gold_f2p_complete"] == N,
        "gold_p2p_regressions_zero": counts["gold_p2p_regressions"] == 0,
        "noop_resolved_zero": counts["noop_resolved"] == 0,
        "noop_patch_applied": counts["noop_patch_applied"] == N,
        "noop_tests_executed": counts["noop_tests_executed"] == N,
        "noop_no_shortcircuit": counts["noop_shortcircuit"] == 0,
        "infra_failures_zero": counts["infra_failures"] == 0,
        "digest_match": counts["digest_match"] == N,
        "no_missing_raw_evidence": counts["missing_raw_evidence"] == 0,
    }
    verdict_pass = all(gates.values())
    endpoint = "R22_OFFICIAL_SCB_GRADER_READY_AWAITING_READER_SELECTION" if verdict_pass else "R22_SCB_GRADER_GATE_FAIL"

    campaign = {"schema": "r22/scb_grader_smoke/1.0.0", "targets": N, "baseline": "noop-baseline",
                "counts": counts, "duplicate_cells": dup_cells, "target_ids": target_ids,
                "gates": gates, "verdict_pass": verdict_pass, "endpoint": endpoint,
                "failed_gates": [k for k, v in gates.items() if not v], "per_target": per}
    os.makedirs(ART, exist_ok=True)
    json.dump(campaign, open(a.out, "w", encoding="utf-8"), indent=2)
    json.dump({"targets": N, "evidence_present": evidence}, open(a.evidence_out, "w", encoding="utf-8"), indent=2)

    # SHA256SUMS over the generated campaign + evidence manifest + each downloaded per-shard summary
    lines = []
    for p in [a.out, a.evidence_out] + sorted(
            glob.glob(os.path.join(a.download_dir, "**", "scb_grader_smoke_*.json"), recursive=True)):
        lines.append("%s  %s" % (_sha256_file(p), os.path.relpath(p, ROOT)))
    open(a.sha256sums, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    _fill_report(campaign, a.report)
    print("SCB AGGREGATE: PASS=%s  gold=%d/%d noop_resolved=%d/%d digest=%d/%d infra=%d missing_evidence=%d"
          % (verdict_pass, counts["gold_resolved"], N, counts["noop_resolved"], N, counts["digest_match"], N,
             counts["infra_failures"], counts["missing_raw_evidence"]))
    if not verdict_pass:
        print("FAILED GATES:", campaign["failed_gates"])
        for iid in frozen:
            pt = per.get(iid, {})
            if not pt.get("present"):
                print("  MISSING SHARD:", iid)
            elif pt.get("gold", {}).get("resolved") is not True or pt.get("noop_baseline", {}).get("resolved") is True:
                print("  CELL FAIL:", iid, "gold_resolved", pt.get("gold", {}).get("resolved"),
                      "noop_resolved", pt.get("noop_baseline", {}).get("resolved"))
    return 0 if verdict_pass else 1


def _fill_report(campaign, report_path=REPORT):
    if not os.path.isfile(report_path):
        return
    txt = open(report_path, encoding="utf-8").read()
    g = campaign["counts"]
    block = ("<!-- SCB_RESULTS_START -->\n## Results (aggregated from shard artifacts)\n"
             "Verdict: **%s** — endpoint `%s`.\n\n"
             "| gate | value |\n|---|---|\n"
             "| gold resolved | %d/12 |\n| noop resolved | %d/12 |\n| gold tests_executed | %d/12 |\n"
             "| noop tests_executed | %d/12 |\n| expected==observed digest | %d/12 |\n"
             "| infra failures | %d |\n| missing raw evidence | %d |\n| duplicate cells | %d |\n\n"
             "Failed gates: %s\n<!-- SCB_RESULTS_END -->"
             % ("PASS" if campaign["verdict_pass"] else "FAIL", campaign["endpoint"],
                g["gold_resolved"], g["noop_resolved"], g["gold_tests_executed"], g["noop_tests_executed"],
                g["digest_match"], g["infra_failures"], g["missing_raw_evidence"], campaign["duplicate_cells"],
                campaign["failed_gates"] or "none"))
    import re
    if "<!-- SCB_RESULTS_START -->" in txt:
        txt = re.sub(r"<!-- SCB_RESULTS_START -->.*<!-- SCB_RESULTS_END -->", block, txt, flags=re.S)
    else:
        txt = txt.rstrip() + "\n\n" + block + "\n"
    open(report_path, "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    raise SystemExit(main())
