#!/usr/bin/env python3
"""R22-P0.9 §5/§8 — fail-closed aggregate of the 55-target dev-pool gradeability audit (COMPLETE raw evidence).

Derives the audit verdict from DOWNLOADED per-target summaries (grade_<iid>.json) + the raw evidence tree, NOT from
console output. GRADEABLE<55 is the SCIENTIFIC RESULT, not a hard failure. But it FAILS CLOSED (exit nonzero) when the
audit is INCOMPLETE — missing summaries, missing/mismatched raw evidence, duplicate targets, digest mismatch, or any
INFRA_FAILURE/UNKNOWN target. The 8 raw evidence files are required for EXECUTED-label cells only
(GRADEABLE / UNGRADEABLE_SELECTOR / UNGRADEABLE_GOLD); UNGRADEABLE_CASE_IMAGE / UNGRADEABLE_TOOLCHAIN are
pre-collection (evidence-less) but are themselves audit-incomplete — a CASE_IMAGE/TOOLCHAIN target carries a digest
mismatch and/or missing cells, so the hard gates below reject it. A clean audit therefore holds only
GRADEABLE / UNGRADEABLE_SELECTOR / UNGRADEABLE_GOLD. Writes:
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
# §5 — the FULL raw evidence set required per EXECUTED condition (mirrors gradeability EVIDENCE_FILES stash names)
COND_EVIDENCE = ["run_instance.log", "test_output.txt", "report.json", "summary_report.json",
                 "stdout.log", "stderr.log", "dataset.json", "prediction.json"]
CONDITIONS = ("gold", "noop")
LABELS = ["GRADEABLE", "UNGRADEABLE_SELECTOR", "UNGRADEABLE_GOLD", "UNGRADEABLE_CASE_IMAGE",
          "UNGRADEABLE_TOOLCHAIN", "INFRA_FAILURE", "UNKNOWN"]
# labels whose targets legitimately EXECUTED both conditions (must carry the full raw evidence + gold/noop cells)
EXECUTED_LABELS = {"GRADEABLE", "UNGRADEABLE_SELECTOR", "UNGRADEABLE_GOLD"}
UNRESOLVED_LABELS = {"UNGRADEABLE_CASE_IMAGE", "UNGRADEABLE_TOOLCHAIN", "INFRA_FAILURE", "UNKNOWN"}


def _sha256_file(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _index_evidence(download_dir):
    """One os.walk over the download tree -> {(iid, cond, name): filepath} for every .../<iid>/<cond>/<file>.
    A single pass instead of a recursive glob per evidence file (55*2*8 globs would be O(tree^2))."""
    idx = {}
    for dp, _dirs, files in os.walk(download_dir):
        parts = dp.replace("\\", "/").rstrip("/").split("/")
        if len(parts) >= 2 and parts[-1] in CONDITIONS:
            iid, cond = parts[-2], parts[-1]
            for f in files:
                idx.setdefault((iid, cond, f), os.path.join(dp, f))
    return idx


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

    ev_index = _index_evidence(a.download_dir)      # one pass over the download tree
    per, evidence = {}, {}
    label_counts = {k: 0 for k in LABELS}
    counts = dict(summary_files=0, gold_cells=0, noop_cells=0, gradeable=0, gradeable_original=0,
                  gradeable_reserve=0, missing_cells=0, missing_raw_evidence=0, digest_mismatch=0)
    lang_grade, subset_grade, repo_grade = {}, {}, {}

    for iid in manifest_ids:
        rec = records[iid]
        s = summaries.get(iid)
        if not s:
            per[iid] = {"present": False}
            counts["missing_cells"] += 2
            continue
        counts["summary_files"] += 1
        label = s.get("label", "UNKNOWN")
        if label not in label_counts:
            label = "UNKNOWN"
        label_counts[label] += 1
        g, n = s.get("gold"), s.get("noop_baseline")
        counts["gold_cells"] += (g is not None)
        counts["noop_cells"] += (n is not None)
        counts["missing_cells"] += (g is None) + (n is None)

        # §3 — image digest must be non-empty and expected==observed (CASE_IMAGE/TOOLCHAIN leave observed None -> mismatch)
        exp, obs = s.get("image_expected_digest"), s.get("image_observed_digest")
        if not (exp and obs and exp == obs):
            counts["digest_mismatch"] += 1

        # §5 — the FULL raw evidence set must be present in the DOWNLOADED tree AND byte/sha match the summary record
        ev = {}
        for cond in CONDITIONS:
            ev_map = (s.get("evidence") or {}).get(cond) or {}
            cev = {}
            for name in COND_EVIDENCE:
                meta = ev_map.get(name) or {}
                fp = ev_index.get((iid, cond, name))
                entry = {"relpath": meta.get("relpath"), "bytes": meta.get("bytes"),
                         "sha256": meta.get("sha256"), "present": False, "verified": False}
                if fp and os.path.isfile(fp):
                    data = open(fp, "rb").read()
                    entry["present"] = True
                    entry["observed_bytes"], entry["observed_sha256"] = len(data), hashlib.sha256(data).hexdigest()
                    entry["verified"] = bool(meta) and entry["observed_bytes"] == meta.get("bytes") \
                        and entry["observed_sha256"] == meta.get("sha256")
                cev[name] = entry
                if label in EXECUTED_LABELS and not entry["verified"]:
                    counts["missing_raw_evidence"] += 1
            ev[cond] = cev
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
                    "repository_cluster": rec.get("repository_cluster"), "gold": g, "noop_baseline": n,
                    "image_expected_digest": exp, "image_observed_digest": obs}

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
        "no_digest_mismatch": counts["digest_mismatch"] == 0,
        "no_infra_failure": label_counts["INFRA_FAILURE"] == 0,
        "no_unknown": label_counts["UNKNOWN"] == 0,
        "raw_evidence_complete": counts["missing_raw_evidence"] == 0,
    }
    audit_complete = all(gates.values())
    endpoint = ("R22_P09_GRADEABILITY_AUDIT_COMPLETE" if audit_complete
                else "R22_P09_GRADEABILITY_AUDIT_INCOMPLETE")

    campaign = {"schema": "r22/p09_gradeability/2.0.0", "targets": N,
                "manifest_targets": manifest_ids, "target_ids": target_ids,
                "counts": counts, "label_counts": label_counts, "duplicate_targets": dup_targets,
                "original_p2_total": orig_total, "dev_reserve_total": reserve_total,
                "gradeable_language_distribution": lang_grade,
                "gradeable_subset_distribution": subset_grade,
                "gradeable_repository_distribution": repo_grade,
                "gates": gates, "audit_complete": audit_complete, "endpoint": endpoint,
                "failed_gates": [k for k, v in gates.items() if not v], "per_target": per}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(campaign, open(a.out, "w", encoding="utf-8"), indent=2)
    json.dump({"targets": N, "evidence_files": COND_EVIDENCE, "evidence": evidence},
              open(a.evidence_out, "w", encoding="utf-8"), indent=2)

    # SHA256SUMS over the generated results + evidence manifest + each downloaded per-target summary
    lines = []
    for p in [a.out, a.evidence_out] + sorted(
            glob.glob(os.path.join(a.download_dir, "**", "grade_*.json"), recursive=True)):
        lines.append("%s  %s" % (_sha256_file(p), os.path.relpath(p, ROOT)))
    open(a.sha256sums, "w", encoding="utf-8").write("\n".join(lines) + "\n")

    _write_report(campaign, a.report)
    print("P09 AGGREGATE: complete=%s  GRADEABLE=%d/%d (orig %d/%d, reserve %d/%d)  digest_mismatch=%d infra=%d "
          "unknown=%d missing_cells=%d missing_evid=%d"
          % (audit_complete, counts["gradeable"], N, counts["gradeable_original"], orig_total,
             counts["gradeable_reserve"], reserve_total, counts["digest_mismatch"],
             label_counts["INFRA_FAILURE"], label_counts["UNKNOWN"], counts["missing_cells"],
             counts["missing_raw_evidence"]))
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
             "fails closed only when INCOMPLETE. A clean audit holds only GRADEABLE / UNGRADEABLE_SELECTOR / "
             "UNGRADEABLE_GOLD (each carries the full 8-file raw evidence set per condition).\n\n"
             "**GRADEABLE: %d/55** (original-40: %d/%d, reserve-15: %d/%d)\n\n"
             "| label | count |\n|---|---|\n%s\n\n"
             "| completeness gate | value |\n|---|---|\n"
             "| summary files | %d/55 |\n| total cells | %d/110 |\n| duplicate targets | %d |\n"
             "| missing cells | %d |\n| digest mismatch | %d |\n| missing raw evidence | %d |\n"
             "| INFRA_FAILURE | %d |\n| UNKNOWN | %d |\n\n"
             "Raw evidence files required per EXECUTED condition: %s\n\n"
             "GRADEABLE by language: %s\nGRADEABLE by subset: %s\nGRADEABLE by repository: %s\n\n"
             "Failed gates: %s\n<!-- P09_RESULTS_END -->"
             % ("COMPLETE" if c["audit_complete"] else "INCOMPLETE", c["endpoint"],
                g["gradeable"], g["gradeable_original"], c["original_p2_total"],
                g["gradeable_reserve"], c["dev_reserve_total"], rows,
                g["summary_files"], g["gold_cells"] + g["noop_cells"], c["duplicate_targets"],
                g["missing_cells"], g["digest_mismatch"], g["missing_raw_evidence"],
                lc["INFRA_FAILURE"], lc["UNKNOWN"], ", ".join(COND_EVIDENCE),
                json.dumps(c["gradeable_language_distribution"]), json.dumps(c["gradeable_subset_distribution"]),
                json.dumps(c["gradeable_repository_distribution"]), c["failed_gates"] or "none"))
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
               "OFFICIAL SCB evaluator (GOLD + NOOP-BASELINE). Verdict derived from downloaded shard artifacts with "
               "the complete raw evidence set re-verified byte-for-byte against the download tree.\n\n"
               + block + "\n")
    open(report_path, "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    raise SystemExit(main())
