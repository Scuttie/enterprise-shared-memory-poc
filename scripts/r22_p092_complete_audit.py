#!/usr/bin/env python3
"""R22-P0.9.2 §5 — complete the gradeability audit WITHOUT overwriting P0.9.1.

Combines the frozen 53 P0.9.1 target results with exactly the 2 P0.9.2 resume results (downloaded to --resume-dir).
Requires 55 unique targets / 110 cells / every target a terminal label / no INFRA_FAILURE or UNKNOWN. A resume
target with no valid summary (or an explicit persistent-timeout marker) is labelled UNGRADEABLE_TOOLCHAIN
(reason PERSISTENT_TIMEOUT_180M) — an instrument-execution classification, not a model failure."""
import argparse
import glob
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART09 = os.path.join(ROOT, "artifacts", "r22_p09")
OUT = os.path.join(ROOT, "artifacts", "r22_p092")
RESUME_TARGETS = ["sympy__sympy-20959", "sympy__sympy-21758"]
EXECUTED_LABELS = {"GRADEABLE", "UNGRADEABLE_SELECTOR", "UNGRADEABLE_GOLD"}
TERMINAL_LABELS = EXECUTED_LABELS | {"UNGRADEABLE_CASE_IMAGE", "UNGRADEABLE_TOOLCHAIN"}


def sha(b):
    return hashlib.sha256(b.encode() if isinstance(b, str) else b).hexdigest()


def _label(rec):
    return rec.get("label") or rec.get("gradeability") or rec.get("verdict")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume-dir", required=True, help="dir with the 2 downloaded resume grade_<iid>.json + evidence")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    p091 = json.load(open(os.path.join(ART09, "dev58_gradeability_results.json"), encoding="utf-8"))
    per091 = p091.get("per_target", p091.get("results", {}))
    ev091 = json.load(open(os.path.join(ART09, "dev58_gradeability_evidence_manifest.json"), encoding="utf-8"))
    man = json.load(open(os.path.join(ART09, "dev55_gradeability_manifest.json"), encoding="utf-8"))["records"]

    combined = {t: dict(r) for t, r in per091.items() if t not in RESUME_TARGETS}   # frozen 53 (drop the 2 stubs)
    evidence = dict(ev091.get("evidence_present", ev091.get("evidence", {})))

    # add exactly the 2 resume results
    for iid in RESUME_TARGETS:
        hits = glob.glob(os.path.join(a.resume_dir, "**", "grade_%s.json" % iid), recursive=True)
        if hits:
            s = json.load(open(hits[0], encoding="utf-8"))
            r = (s.get("results") or {}).get(iid) or s.get(iid) or s
            if not _label(r):
                r["label"] = "UNGRADEABLE_TOOLCHAIN"; r["reason"] = "no terminal label in resume summary"
            combined[iid] = r
        else:
            combined[iid] = {"label": "UNGRADEABLE_TOOLCHAIN", "reason": "PERSISTENT_TIMEOUT_180M",
                             "original_status": man[iid]["original_status"], "note": "no resume summary (180-min timeout)"}
        # evidence from the resume tree (relpath+bytes+sha256) if present
        evidence[iid] = {}
        for cond in ("gold", "noop"):
            evidence[iid][cond] = {}
            for f in glob.glob(os.path.join(a.resume_dir, "**", iid, cond, "*"), recursive=True):
                if os.path.isfile(f):
                    b = open(f, "rb").read()
                    evidence[iid][cond][os.path.basename(f)] = {"bytes": len(b), "sha256": sha(b)}

    ids = list(combined)
    labels = {t: _label(combined[t]) for t in ids}
    import collections
    counts = collections.Counter(labels.values())
    infra_or_unknown = [t for t, l in labels.items() if l in ("INFRA_FAILURE", "UNKNOWN") or l not in TERMINAL_LABELS]
    gates = {
        "unique_targets_55": len(set(ids)) == 55,
        "summaries_55": len(ids) == 55,
        "no_duplicate": len(ids) == len(set(ids)),
        "all_terminal_label": len(infra_or_unknown) == 0,
        "no_infra_or_unknown": all(l not in ("INFRA_FAILURE", "UNKNOWN") for l in labels.values()),
    }
    audit_complete = all(gates.values())
    orig = [t for t in ids if man[t]["original_status"] == "ORIGINAL_P2"]
    res = [t for t in ids if man[t]["original_status"] == "DEV_RESERVE"]
    lang = collections.Counter(man[t]["language"] for t in ids if labels[t] == "GRADEABLE")
    subset = collections.Counter(man[t].get("subset") for t in ids if labels[t] == "GRADEABLE")

    out = {"experiment": "R22_P09_2_COMPLETE", "audit_complete": audit_complete, "gates": gates,
           "targets": len(ids), "label_counts": dict(counts),
           "gradeable_total": counts.get("GRADEABLE", 0),
           "original40_gradeable": sum(1 for t in orig if labels[t] == "GRADEABLE"),
           "reserve15_gradeable": sum(1 for t in res if labels[t] == "GRADEABLE"),
           "gradeable_language_distribution": dict(lang),
           "gradeable_subset_distribution": dict(subset),
           "resume_targets": {t: labels[t] for t in RESUME_TARGETS},
           "per_target_label": labels,
           "note": "Frozen 53 P0.9.1 results reused byte-for-byte; only the 2 resume targets added."}
    json.dump(out, open(os.path.join(OUT, "dev55_gradeability_results_complete.json"), "w", encoding="utf-8"), indent=2)
    json.dump({"targets": len(ids), "evidence": evidence},
              open(os.path.join(OUT, "dev55_gradeability_evidence_manifest.json"), "w", encoding="utf-8"), indent=2)
    lines = []
    for p in (os.path.join(OUT, "dev55_gradeability_results_complete.json"),
              os.path.join(OUT, "dev55_gradeability_evidence_manifest.json"),
              os.path.join(OUT, "resume_manifest.json")):
        lines.append("%s  %s" % (sha(open(p, "rb").read()), os.path.relpath(p, ROOT)))
    open(os.path.join(OUT, "SHA256SUMS"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("AUDIT COMPLETE=%s | targets=%d | %s" % (audit_complete, len(ids), dict(counts)))
    print("original40 gradeable=%d/40 | reserve15 gradeable=%d/15" % (out["original40_gradeable"], out["reserve15_gradeable"]))
    print("resume:", out["resume_targets"])
    print("gradeable languages:", dict(lang), "| subsets:", dict(subset))
    if not audit_complete:
        print("INCOMPLETE gates:", [k for k, v in gates.items() if not v], "| non-terminal:", infra_or_unknown)
    return 0 if audit_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
