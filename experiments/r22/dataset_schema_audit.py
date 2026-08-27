#!/usr/bin/env python3
"""R22 §2-§4 (G0.1) — pin the current OFFICIAL enriched SWE-bench datasets, verify legacy<->enriched row
equivalence for the frozen 12 smoke instances, and re-route to the enriched datasets (image taken from the row).

No model calls. Fixes the KeyError:'image' root cause: legacy princeton-nlp/* rows lack the enriched evaluation
schema (image/eval_script/log_parser/eval_type) that swebench 5.0.2 requires.
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "artifacts", "r22")

ENRICHED = [
    ("SWE-bench Verified", "SWE-bench/SWE-bench_Verified"),
    ("SWE-bench Lite", "SWE-bench/SWE-bench_Lite"),
    ("SWE-bench Multilingual", "SWE-bench/SWE-bench_Multilingual"),
]
LEGACY = {  # what the previous run routed to
    "SWE-bench Verified": "princeton-nlp/SWE-bench_Verified",
    "SWE-bench Lite": "princeton-nlp/SWE-bench_Lite",
    "SWE-bench Multilingual": "swe-bench/SWE-bench_Multilingual",
}
REQUIRED = ["instance_id", "repo", "base_commit", "patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS",
            "image", "eval_script", "log_parser", "eval_type"]
CORE = ["repo", "base_commit", "patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS", "problem_statement",
        "environment_setup_commit"]


def _sha(x):
    return hashlib.sha256(str(x).encode()).hexdigest()


def _canon_list(v):
    """Normalize JSON-string-vs-list representation before hashing (§3)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            pass
    if isinstance(v, list):
        return _sha(json.dumps(sorted(map(str, v))))
    return _sha(v)


def _load(name):
    from datasets import load_dataset
    from huggingface_hub import dataset_info
    sha = dataset_info(name).sha
    ds = load_dataset(name, split="test")
    return sha, ds, {r["instance_id"]: r for r in ds}


def main():
    smoke = json.load(open(os.path.join(OUT, "grader_smoke_manifest.json")))
    ids = [t["instance_id"] for t in smoke["tasks"]]

    enriched_by = {}
    schema_lock = {"schema": "r22/official_dataset_schema_lock/1.0.0", "datasets": {}}
    for label, name in ENRICHED:
        sha, ds, by = _load(name)
        enriched_by[label] = by
        cols = ds.column_names
        schema_lock["datasets"][label] = {
            "dataset": name, "revision": sha, "split": "test", "rows": len(ds),
            "license": "MIT (SWE-bench)", "fields": cols,
            "required_present": [f for f in REQUIRED if f in cols],
            "required_missing": [f for f in REQUIRED if f not in cols],
        }
    json.dump(schema_lock, open(os.path.join(OUT, "official_dataset_schema_lock.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    legacy_by = {}
    for label, lname in LEGACY.items():
        try:
            _, _, by = _load(lname)
            legacy_by[label] = by
        except Exception:
            legacy_by[label] = {}

    # route each instance to the enriched subset that contains it
    def subset_of(iid):
        for label, _ in ENRICHED:
            if iid in enriched_by[label]:
                return label
        return None

    comparison = []
    routes = []
    images = []
    fails = []
    for iid in ids:
        label = subset_of(iid)
        if label is None:
            fails.append("%s MISSING_FROM_CURRENT_OFFICIAL_DATASET" % iid)
            comparison.append({"instance_id": iid, "class": "MISSING_FROM_CURRENT_OFFICIAL_DATASET"})
            continue
        er = enriched_by[label][iid]
        # required-field completeness
        missing = [f for f in REQUIRED if not er.get(f) and er.get(f) != ""]
        img = er.get("image")
        if not img:
            fails.append("%s enriched row missing image" % iid)
        # legacy comparison
        lr = legacy_by.get(label, {}).get(iid)
        rec = {"instance_id": iid, "subset": label, "enriched_dataset": dict(ENRICHED)[label],
               "enriched_revision": schema_lock["datasets"][label]["revision"],
               "image": img, "eval_type": er.get("eval_type"),
               "required_missing": missing}
        if lr is None:
            rec["class"] = "ENRICHED_ONLY_NO_LEGACY"
        else:
            diffs = []
            for f in CORE:
                lv = _canon_list(lr.get(f)) if f in ("FAIL_TO_PASS", "PASS_TO_PASS") else _sha(lr.get(f))
                ev = _canon_list(er.get(f)) if f in ("FAIL_TO_PASS", "PASS_TO_PASS") else _sha(er.get(f))
                if lv != ev:
                    diffs.append(f)
            rec["core_diffs"] = diffs
            rec["class"] = "EXACT_CORE_MATCH_ENRICHED" if not diffs else "CORE_FIELD_MISMATCH"
            if diffs:
                fails.append("%s CORE_FIELD_MISMATCH: %s" % (iid, diffs))
        comparison.append(rec)
        routes.append({"instance_id": iid, "subset": label, "dataset_name": dict(ENRICHED)[label],
                       "dataset_revision": schema_lock["datasets"][label]["revision"],
                       "repo": er.get("repo"), "base_commit": er.get("base_commit"),
                       "image_from_row": img, "eval_type": er.get("eval_type"),
                       "gold_patch_sha256": _sha(er.get("patch"))})
        images.append({"instance_id": iid, "subset": label, "image": img,
                       "provisioning": "from enriched row 'image' field (not reconstructed)"})

    counts = {}
    for c in comparison:
        counts[c["class"]] = counts.get(c["class"], 0) + 1
    json.dump({"schema": "r22/legacy_enriched_row_comparison/1.0.0", "counts": counts, "rows": comparison},
              open(os.path.join(OUT, "legacy_enriched_row_comparison.json"), "w", encoding="utf-8"),
              indent=2, default=str)
    json.dump({"schema": "r22/grader_instance_routes/2.0.0",
               "note": "enriched SWE-bench/* datasets with pinned revisions; image taken from the row",
               "total": len(ids), "routes": routes},
              open(os.path.join(OUT, "grader_instance_routes.json"), "w", encoding="utf-8"), indent=2, default=str)
    json.dump({"schema": "r22/grader_image_manifest/2.0.0", "images": images},
              open(os.path.join(OUT, "grader_image_manifest.json"), "w", encoding="utf-8"), indent=2, default=str)

    summary = {"schema_lock_revisions": {k: v["revision"] for k, v in schema_lock["datasets"].items()},
               "required_missing_any": {k: v["required_missing"] for k, v in schema_lock["datasets"].items()},
               "comparison_counts": counts, "image_field_complete": sum(1 for r in routes if r["image_from_row"]),
               "instances": len(ids), "fails": fails}
    print(json.dumps(summary, indent=2))
    if fails:
        print("R22_OFFICIAL_DATASET_REVISION_MISMATCH" if any("MISMATCH" in f or "MISSING" in f for f in fails)
              else "SCHEMA_INCOMPLETE")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
