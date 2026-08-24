#!/usr/bin/env python3
"""R22 §3 (G0) — per-instance official-grader routing for the frozen 12-task mixed smoke (no model calls).

Determines, for each smoke instance, which official SWE-bench subset (Lite / Verified / Multilingual) contains it,
and freezes the official grading coordinates. Emits artifacts/r22/{grader_instance_routes,grader_image_manifest}.json.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "artifacts", "r22")

SUBSETS = [
    ("SWE-bench Verified", ["princeton-nlp/SWE-bench_Verified"]),
    ("SWE-bench Lite", ["princeton-nlp/SWE-bench_Lite"]),
    ("SWE-bench Multilingual", ["swe-bench/SWE-bench_Multilingual", "SWE-bench/SWE-bench_Multilingual",
                                "princeton-nlp/SWE-bench_Multilingual"]),
]


def _load_ids(names):
    from datasets import load_dataset
    for n in names:
        try:
            ds = load_dataset(n, split="test")
            return n, {r["instance_id"]: r for r in ds}
        except Exception as e:
            last = e
            continue
    print("  (could not load any of %s: %s)" % (names, last))
    return None, {}


def main():
    smoke = json.load(open(os.path.join(OUT, "grader_smoke_manifest.json")))
    ids = [t["instance_id"] for t in smoke["tasks"]]
    subset_rows = {}
    subset_used = {}
    for label, names in SUBSETS:
        used, rows = _load_ids(names)
        subset_rows[label] = rows
        subset_used[label] = used
        print("%s: loaded %d rows via %s" % (label, len(rows), used))

    routes = []
    unrouted = []
    for iid in ids:
        found = None
        for label, _ in SUBSETS:
            if iid in subset_rows[label]:
                r = subset_rows[label][iid]
                found = {
                    "instance_id": iid, "subset": label, "dataset_name": subset_used[label],
                    "repo": r.get("repo"), "base_commit": r.get("base_commit"),
                    "environment_setup_commit": r.get("environment_setup_commit"),
                    "version": str(r.get("version")),
                    "FAIL_TO_PASS": r.get("FAIL_TO_PASS"), "PASS_TO_PASS": r.get("PASS_TO_PASS"),
                    "gold_patch_sha256": __import__("hashlib").sha256(
                        (r.get("patch") or "").encode()).hexdigest(),
                }
                break
        if found:
            routes.append(found)
        else:
            unrouted.append(iid)
            routes.append({"instance_id": iid, "subset": "UNROUTED", "dataset_name": None})

    by_subset = {}
    for r in routes:
        by_subset.setdefault(r["subset"], []).append(r["instance_id"])

    route_manifest = {"schema": "r22/grader_instance_routes/1.0.0", "run_id": "r22-grader-smoke",
                      "total": len(ids), "by_subset": {k: len(v) for k, v in by_subset.items()},
                      "unrouted": unrouted, "routes": routes,
                      "grader": "official swebench harness, per-instance --dataset_name routing",
                      "note": "eval code NOT vendored; official images built/pulled by the harness"}
    json.dump(route_manifest, open(os.path.join(OUT, "grader_instance_routes.json"), "w", encoding="utf-8"),
              indent=2, default=str)

    # official image name convention (SWE-bench harness x86_64 instance images)
    images = [{"instance_id": r["instance_id"], "subset": r["subset"], "dataset_name": r.get("dataset_name"),
               "image": "swebench/sweb.eval.x86_64.%s:latest" % r["instance_id"].replace("__", "_1776_")
               if r["subset"] != "UNROUTED" else None,
               "provisioning": "official harness build/pull (cache_level=env)"}
              for r in routes]
    json.dump({"schema": "r22/grader_image_manifest/1.0.0", "images": images},
              open(os.path.join(OUT, "grader_image_manifest.json"), "w", encoding="utf-8"), indent=2, default=str)

    print(json.dumps({"by_subset": route_manifest["by_subset"], "unrouted": unrouted}, indent=2))
    return 0 if not unrouted else 3


if __name__ == "__main__":
    sys.exit(main())
