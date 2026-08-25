#!/usr/bin/env python3
"""R22 §3 — audit every unique frozen paid target and record its official grading route. No model calls.

Rule 1: prefer a pinned enriched SWE-bench/* row if the exact instance exists. Rule 3: else the official swebench
image-build path pinned to the grader. Rule 5: image=None is forbidden — a target with no reproducible official
image (and not gradeable by a proven build recipe) yields R22_REAL_PAID_HARNESS_TECHNICAL_BLOCK.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r22")
DATA = os.environ.get("R22_SCB_DATA", os.path.join(ART, "_scb_data"))
ENRICHED = {
    "SWE-bench Verified": ("SWE-bench/SWE-bench_Verified", "78f471bf655a3137b2e8a75af1501690ec009ec3"),
    "SWE-bench Lite": ("SWE-bench/SWE-bench_Lite", "b0dde1093fe417d83b7184254edf8199c1f0dff5"),
    "SWE-bench Multilingual": ("SWE-bench/SWE-bench_Multilingual", "846e647b9f33c0b51b739d005d13d85493c9af09"),
}


def _sha(x):
    return hashlib.sha256(str(x).encode()).hexdigest()


def main():
    sys.path.insert(0, ROOT)
    import pandas as pd
    from datasets import load_dataset
    from experiments.r22.runtime import loaders as LD
    ids = sorted(set(LD._frozen_ids("oracle_dev_manifest.json")) | set(LD._frozen_ids("oracle_smoke_manifest.json")))
    scb_rel = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Related.parquet"))
    scb_exp = pd.read_parquet(os.path.join(DATA, "SWEContextBench_Experience.parquet"))
    scb = {}
    for df in (scb_rel, scb_exp):
        for _, r in df.iterrows():
            scb.setdefault(r["instance_id"], r)
    enr = {}
    for label, (name, rev) in ENRICHED.items():
        for r in load_dataset(name, split="test", revision=rev):
            if r["instance_id"] in ids:
                enr[r["instance_id"]] = (label, name, rev, r)

    routes = []
    build_needed = 0
    missing = 0
    for tid in ids:
        s = scb.get(tid)
        if s is None:
            routes.append({"instance_id": tid, "route": "MISSING_FROM_SCB"}); missing += 1; continue
        row = {"instance_id": tid, "repository": s["repo"], "base_commit": s["base_commit"],
               "scb_row_hash": _sha(dict(s)), "fail_to_pass_hash": _sha(s["FAIL_TO_PASS"]),
               "pass_to_pass_hash": _sha(s["PASS_TO_PASS"]),
               "environment_setup_commit": s.get("environment_setup_commit"), "version": str(s.get("version"))}
        if tid in enr:
            label, name, rev, er = enr[tid]
            row.update({"route": "ENRICHED_PREBUILT_IMAGE", "official_subset": label, "dataset_name": name,
                        "dataset_revision": rev, "image": er.get("image"), "eval_type": er.get("eval_type"),
                        "official_row_hash": _sha(dict(er))})
        else:
            row.update({"route": "OFFICIAL_IMAGE_BUILD", "official_subset": "SWE-ContextBench",
                        "dataset_name": "jiayuanz3/SWEContextBench", "dataset_revision": LD.SCB_GH_COMMIT,
                        "image": None, "image_build": "swebench build from base_commit + version + test_patch "
                        "(pinned swebench==5.0.2); digest recorded by the grade probe before approval",
                        "build_validated": False})
            build_needed += 1
        routes.append(row)

    audit = {"schema": "r22/paid_target_routes/1.0.0", "total": len(ids),
             "enriched_prebuilt": len(enr), "build_needed": build_needed, "missing_from_scb": missing,
             "routes": routes,
             "block_if_any_unbuildable": "R22_REAL_PAID_HARNESS_TECHNICAL_BLOCK — set once the grade probe result "
             "for the OFFICIAL_IMAGE_BUILD route type is known"}
    json.dump(audit, open(os.path.join(ART, "paid_target_routes.json"), "w", encoding="utf-8"), indent=2, default=str)
    json.dump({"schema": "r22/paid_image_manifest/1.0.0",
               "images": [{"instance_id": r["instance_id"], "route": r["route"], "image": r.get("image"),
                           "build_validated": r.get("build_validated", r["route"] == "ENRICHED_PREBUILT_IMAGE")}
                          for r in routes if r["route"] != "MISSING_FROM_SCB"]},
              open(os.path.join(ART, "paid_image_manifest.json"), "w", encoding="utf-8"), indent=2, default=str)
    print(json.dumps({"total": len(ids), "enriched_prebuilt": len(enr), "build_needed": build_needed,
                      "missing_from_scb": missing}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
