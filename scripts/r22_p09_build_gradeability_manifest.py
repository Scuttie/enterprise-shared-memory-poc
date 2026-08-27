#!/usr/bin/env python3
"""R22-P0.9 §7 — freeze the development-pool gradeability manifest (metadata only; no evaluator execution).

58 v2 development PAIRS resolve to 55 unique TARGETS (40 ORIGINAL_P2 + 15 DEV_RESERVE); 3 targets appear in two
pairs each (different sources). Gradeability is a per-TARGET property, so the audit set is 55 targets / 110 cells.
This is surfaced explicitly against the spec's pair-based '58/116'."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r22")
OUT = os.path.join(ROOT, "artifacts", "r22_p09")

ci = json.load(open(os.path.join(OUT, "dev58_case_image.json"), encoding="utf-8"))["records"]
pairs = json.load(open(os.path.join(ART, "dev_manifest_v2.json"), encoding="utf-8"))["pairs"]

# complete, case-insensitive language resolution by repo
_LANG = {"astropy": "python", "sympy": "python", "xarray": "python", "seaborn": "python", "django": "python",
         "lucene": "java", "gson": "java", "ruff": "rust", "axum": "rust", "tokio": "rust",
         "rubocop": "ruby", "caddy": "go", "prometheus": "go", "framework": "php", "php-cs-fixer": "php"}


def lang_of(repo):
    name = (repo or "").split("/")[-1].lower()
    return _LANG.get(name, "unknown")

# collect all (source,class) relations per target
rel = {}
for p in pairs:
    rel.setdefault(p["target_id"], []).append(
        {"source_id": p["source_id"], "source_repo": p["source_repo"], "class": p["class"]})

records = {}
for iid, r in ci.items():
    records[iid] = {
        "target_id": iid, "original_status": r["original_status"], "language": lang_of(r["repository_cluster"]),
        "subset": r.get("subset"), "repository_cluster": r["repository_cluster"],
        "base_commit": r.get("base_commit"), "case_path": r.get("case_path"),
        "case_sha256": r.get("case_sha256"), "gold_patch_sha256": r.get("gold_patch_sha256"),
        "test_patch_sha256": r.get("test_patch_sha256"), "noop_patch_sha256": r["noop_patch_sha256"],
        "f2p_canon": r.get("f2p_canon"), "p2p_canon": r.get("p2p_canon"),
        "image": r.get("image"), "image_digest": r.get("image_digest"), "linux_amd64": r.get("linux_amd64"),
        "pair_relations": rel.get(iid, []),
        # gradeability label is UNAUDITED until the gated §8 execution runs
        "gradeability": "UNAUDITED",
    }

from collections import Counter
manifest = {
    "experiment": "R22_P09_DEV_POOL_GRADEABILITY",
    "pinned_evaluator_commit": "31bb04155f52b184bf31b220e3cff0607ac9c953",
    "noop_baseline": "NOOP_BASELINE_PATCH (adds .r22_noop)",
    "pair_count": len(pairs), "unique_targets": len(records),
    "targets_appearing_in_two_pairs": sorted(t for t, c in Counter(p["target_id"] for p in pairs).items() if c > 1),
    "original_p2": sum(1 for r in records.values() if r["original_status"] == "ORIGINAL_P2"),
    "dev_reserve": sum(1 for r in records.values() if r["original_status"] == "DEV_RESERVE"),
    "spec_reconciliation": ("Spec §7 counts 58 development candidates (= 58 PAIRS = 40 selected + 18 extra pairings). "
                            "Those 58 pairs contain 55 UNIQUE targets (40 ORIGINAL_P2 + 15 DEV_RESERVE); 3 targets "
                            "recur across two pairs. Gradeability is per-TARGET, so the audit is 55 targets / 110 "
                            "cells, not 58/116. No targets were dropped; the pair->target reduction is recorded."),
    "language_distribution": dict(Counter(r["language"] for r in records.values())),
    "subset_distribution": dict(Counter(r["subset"] for r in records.values())),
    "cases_present": sum(1 for r in records.values() if r["case_sha256"]),
    "image_digests_present": sum(1 for r in records.values() if (r["image_digest"] or "").startswith("sha256:")),
    "records": records,
}
os.makedirs(OUT, exist_ok=True)
json.dump(manifest, open(os.path.join(OUT, "dev55_gradeability_manifest.json"), "w", encoding="utf-8"), indent=2)
print("wrote dev55_gradeability_manifest.json: unique_targets=%d orig=%d reserve=%d cases=%d images=%d"
      % (manifest["unique_targets"], manifest["original_p2"], manifest["dev_reserve"],
         manifest["cases_present"], manifest["image_digests_present"]))
print("languages:", manifest["language_distribution"])
print("dual-pair targets:", manifest["targets_appearing_in_two_pairs"])
