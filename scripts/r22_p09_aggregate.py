#!/usr/bin/env python3
"""R22-P0.9 §2 — fail-closed aggregate of the 55-target dev-pool gradeability audit.

Derives the audit verdict from DOWNLOADED per-target summaries (grade_<iid>.json) + the raw evidence tree, NOT from
console output. This aggregate REPORTS gradeability: GRADEABLE<55 is the SCIENTIFIC RESULT, not a hard failure. But it
FAILS CLOSED (exit nonzero) when the audit is INCOMPLETE — missing summaries, missing raw evidence, duplicate targets,
or any INFRA_FAILURE/UNKNOWN target left unresolved. Writes:
  artifacts/r22_p09/dev58_gradeability_results.json, dev58_gradeability_evidence_manifest.json,
  artifacts/r22_p09/SHA256SUMS, and reports/R22_P09_FULL_GRADEABILITY_AUDIT.md."""
import argparse
import glob
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART09 = os.path.join(ROOT, "artifacts", "r22_p09")
REPORT = os.path.join(ROOT, "reports", "R22_P09_FULL_GRADEABILITY_AUDIT.md")
COND_EVIDENCE = ["run_instance.log", "test_output.txt"]     # raw execution evidence required per executed condition
LABELS = ["GRADEABLE", "UNGRADEABLE_SELECTOR", "UNGRADEABLE_GOLD", "UNGRADEABLE_CASE_IMAGE",
          "UNGRADEABLE_TOOLCHAIN", "INFRA_FAILURE", "UNKNOWN"]
# labels whose targets legitimately EXECUTED both conditions (must carry raw evidence + gold/noop cells)
EXECUTED_LABELS = {"GRADEABLE", "UNGRADEABLE_SELECTOR", "UNGRADEABLE_GOLD"}
UNRESOLVED_LABELS = {"INFRA_FAILURE", "UNKNOWN"}


def _sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _has_evidence(download_dir, iid, cond):
    """True map of the raw evidence files present somewhere under .../<iid>/<cond>/ in the download tree."""
    found = {}
    for name in COND_EVIDENCE:
        hits = glob.glob(os.path.join(download_dir, "**", iid, cond, name), recursive=True)
        found[name] = hits[0] if hits else None
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-dir", required=True)
    ap.add_argument("--manifest", default=os.path.join(ART09, "dev55_gradeability_manifest.json"))
    ap.add_argument("--out", default=os.path.join(ART09, "dev58_gradeability_results.json"))
    ap.add_argument("--evidence-out", default=os.path.join(ART09, "dev58_gradeability_evidence_manifest.json"))
    ap.add_argument("--sha256sums", default=os.path.join(ART09, "SHA256SUMS"))
    ap.add_argument("--report", default=REPORT)
    a = ap.parse_args()

    manifest = json.load(open(a.manifest, encoding="utf-8"))
    records = manifest["records"]
    manifest_ids = sorted(records.keys())
    manifest_set = set(manifest_ids)
    N = 55

    # collect per-target summaries; a second grade_<iid>.json for the same target = duplicate shard
    summaries, dup_targets = {}, 0
    for p in sorted(glob.glob(os.path.join(a.download_dir, "**", "grade_*.json"), recursive=True)):
        base = os.path.basename(p)
        iid = base[len("grade_"):-len(".json")]
        if iid not in manifest_set:
            continue
        if iid in summaries:
            dup_targets += 1
            continue
        try:
            summaries[iid] = json.load(open(p, encoding="utf-8"))
        except Exception:
            pass

    per, evidence = {}, {}
    label_counts = {k: 0 for k in LABELS}
    counts = dict(summary_files=0, gold_cells=0, noop_cells=0, gradeable=0,
                  gradeable_original=0, gradeable_reserve=0, missing_cells=0, missing_raw_evidence=0)
    lang_grade, subset_grade, repo_grade = {}, {}, {}

    for iid in manifest_ids:
        rec = records[iid]
        s = summaries.get(iid)
        if not s:
            per[iid] = {"present": False}
            counts["missing_cells"] += 2
            counts["missing_raw_evidence"] += len(COND_EVIDENCE) * 2
            continue
        counts["summary_files"] += 1
        label = s.get("label", "UNKNOWN")
        if label not in label_counts:
            label = "UNKNOWN"
        label_counts[label] += 1
        g, n = s.get("gold"), s.get("noop_baseline")
        if g is not None:
            counts["gold_cells"] += 1
        if n is not None:
            counts["noop_cells"] += 1
        if g is None:
            counts["missing_cells"] += 1
        if n is None:
            counts["missing_cells"] += 1

        # raw evidence must be present in the DOWNLOADED tree for targets that executed (not just referenced)
        ev = {}
        for cond in ("gold", "noop"):
            found = _has_evidence(a.download_dir, iid, cond)
            ev[cond] = {k: (v is not None) for k, v in found.items()}
            if label in EXECUTED_LABELS:
                for name in COND_EVIDENCE:
                    if not found.get(name):
                        counts["missing_raw_evidence"] += 1
        evidence[iid] = ev

        if label == "GRADEABLE":
            counts["gradeable"] += 1
            if rec.get("original_status") == "ORIGINAL_P2":
                counts["gradeable_original"] += 1
            elif rec.get("original_status") == "DEV_RESERVE":
                counts["gradeable_reserve"] += 1
            lang_grade[rec.get("language")] = lang_grade.get(rec.get("language"), 0) + 1
            subset_grade[rec.get("subset")] = subset_grade.get(rec.get("subset"), 0) + 1
            repo_grade[rec.get("repository_cluster")] = repo_grade.get(rec.get("repository_cluster"), 0) + 1

        per[iid] = {"present": True, "label": label, "original_status": rec.get("original_status"),
                    "language": rec.get("language"), "subset": rec.get("subset"),
                    "repository_cluster": rec.get("repository_cluster"),
                    "gold": g, "noop_baseline": n,
                    "image_expected_digest": s.get("image_expected_digest"),
                    "image_observed_digest": s.get("image_observed_digest")}

    target_ids = sorted(summaries.keys())
    orig_total = sum(1 for r in records.values() if r.get("original_status") == "ORIGINAL_P2")
    reserve_total = sum(1 for r in records.values() if r.get("original_status") == "DEV_RESERVE")

    # completeness gates — audit is COMPLETE (exit 0) iff all hold. GRADEABLE count is NOT a gate (science, not infra).
    gates = {
        "unique_targets_55": len(target_ids) == N,
        "target_set_equals_manifest": set(target_ids) == manifest_set,
        "summary_files_55": counts["summary_files"] == N,
        "total_cells_110": counts["gold_cells"] + counts["noop_cells"] == 2 * N,
        "no_duplicate_targets": dup_targets == 0,
        "no_missing_cells": counts["missing_cells"] == 0,
        "raw_evidence_complete": counts["missing_raw_evidence"] == 0,
        "no_infra_failure": label_counts["INFRA_FAILURE"] == 0,
        "no_unknown": label_counts["UNKNOWN"] == 0,
    }
    audit_complete = all(gates.values())
    endpoint = ("R22_P09_GRADEABILITY_AUDIT_COMPLETE" if audit_complete
                else "R22_P09_GRADEABILITY_AUDIT_INCOMPLETE")

    campaign = {"schema": "r22/p09_gradeability/1.0.0", "targets": N,
                "manifest_targets": manifest_ids, "target_ids": target_ids,
                "counts": counts, "label_counts": label_counts, "duplicate_targets": dup_targets,
                "original_p2_total": orig_total, "dev_reserve_total": reserve_total,
                "gradeable_language_distribution": lang_grade,
                "gradeable_subset_distribution": subset_grade,
                "gradeable_repository_distribution": repo_grade,
                "gates": gates, "audit_complete": audit_complete, "endpoint": endpoint,
                "failed_gates": [k for k, v in gates.items() if not v], "per_target": per}
    os.makedirs(ART09, exist_ok=True)
    json.dump(campaign, open(a.out, "w", encoding="utf-8"), indent=2)
    json.dump({"targets": N, "evidence_present": evidence}, open(a.evidence_out, "w", encoding="utf-8"), indent=2)

    # SHA256SUMS over the generated results + evidence manifest + each downloaded per-target summary
    lines = []
    for p in [a.out, a.evidence_out] + sorted(
            glob.glob(os.path.join(a.download_dir, "**", "grade_*.json"), recursive=True)):
        lines.append("%s  %s" % (_sha256_file(p), os.path.relpath(p, ROOT)))
    open(a.sha256sums, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    _write_report(campaign, a.report)
    print("P09 AGGREGATE: complete=%s  GRADEABLE=%d/%d (orig %d/%d, reserve %d/%d)  infra=%d unknown=%d missing_evid=%d"
          % (audit_complete, counts["gradeable"], N, counts["gradeable_original"], orig_total,
             counts["gradeable_reserve"], reserve_total, label_counts["INFRA_FAILURE"],
             label_counts["UNKNOWN"], counts["missing_raw_evidence"]))
    if not audit_complete:
        print("FAILED GATES:", campaign["failed_gates"])
        for iid in manifest_ids:
            pt = per.get(iid, {})
            if not pt.get("present"):
                print("  MISSING SUMMARY:", iid)
            elif pt.get("label") in UNRESOLVED_LABELS:
                print("  UNRESOLVED:", iid, pt.get("label"))
    return 0 if audit_complete else 1


def _write_report(c, report_path):
    g, lc = c["counts"], c["label_counts"]
    rows = "\n".join("| %s | %d |" % (k, lc[k]) for k in LABELS)
    block = ("<!-- P09_RESULTS_START -->\n## Results — 55-target dev-pool gradeability audit\n"
             "Audit: **%s** — endpoint `%s`. GRADEABLE<55 is the scientific result, not an infra failure; the audit "
             "fails closed only when INCOMPLETE.\n\n"
             "**GRADEABLE: %d/55** (original-40: %d/%d, reserve-15: %d/%d)\n\n"
             "| label | count |\n|---|---|\n%s\n\n"
             "| completeness gate | value |\n|---|---|\n"
             "| summary files | %d/55 |\n| total cells | %d/110 |\n| duplicate targets | %d |\n"
             "| missing cells | %d |\n| missing raw evidence | %d |\n"
             "| INFRA_FAILURE | %d |\n| UNKNOWN | %d |\n\n"
             "GRADEABLE by language: %s\nGRADEABLE by subset: %s\n\n"
             "Failed gates: %s\n<!-- P09_RESULTS_END -->"
             % ("COMPLETE" if c["audit_complete"] else "INCOMPLETE", c["endpoint"],
                g["gradeable"], g["gradeable_original"], c["original_p2_total"],
                g["gradeable_reserve"], c["dev_reserve_total"], rows,
                g["summary_files"], g["gold_cells"] + g["noop_cells"], c["duplicate_targets"],
                g["missing_cells"], g["missing_raw_evidence"], lc["INFRA_FAILURE"], lc["UNKNOWN"],
                json.dumps(c["gradeable_language_distribution"]), json.dumps(c["gradeable_subset_distribution"]),
                c["failed_gates"] or "none"))
    if os.path.isfile(report_path):
        import re
        txt = open(report_path, encoding="utf-8").read()
        if "<!-- P09_RESULTS_START -->" in txt:
            txt = re.sub(r"<!-- P09_RESULTS_START -->.*<!-- P09_RESULTS_END -->", block, txt, flags=re.S)
        else:
            txt = txt.rstrip() + "\n\n" + block + "\n"
    else:
        os.makedirs(os.path.dirname(os.path.abspath(report_path)), exist_ok=True)
        txt = ("# R22-P0.9 — Full dev-pool gradeability audit\n\n"
               "Per-target gradeability of the 55 unique dev targets (40 ORIGINAL_P2 + 15 DEV_RESERVE) under the "
               "OFFICIAL SCB evaluator (GOLD + NOOP-BASELINE). Verdict derived from downloaded shard artifacts.\n\n"
               + block + "\n")
    open(report_path, "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    raise SystemExit(main())
