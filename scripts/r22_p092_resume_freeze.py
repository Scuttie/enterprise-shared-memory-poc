#!/usr/bin/env python3
"""R22-P0.9.2 §2 — freeze the two-target resume manifest (only the 2 missing sympy reserves). No other target;
does not regenerate or alter the existing 53 P0.9.1 results."""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ART09 = os.path.join(ROOT, "artifacts", "r22_p09")
OUT = os.path.join(ROOT, "artifacts", "r22_p092")

TARGETS = ["sympy__sympy-20959", "sympy__sympy-21758"]
ORIG_JOBS = {"sympy__sympy-20959": "98038244833", "sympy__sympy-21758": "98038244910"}


def sha(b):
    return hashlib.sha256(b.encode() if isinstance(b, str) else b).hexdigest()


def main():
    os.makedirs(OUT, exist_ok=True)
    from experiments.r22.runtime.scb_official_grader import NOOP_BASELINE_PATCH
    noop_sha = sha(NOOP_BASELINE_PATCH)
    dev55 = json.load(open(os.path.join(ART09, "dev55_gradeability_manifest.json"), encoding="utf-8"))["records"]
    campaign_hash = sha(open(os.path.join(ART09, "dev58_gradeability_results.json"), "rb").read())

    recs = {}
    for iid in TARGETS:
        r = dev55[iid]
        recs[iid] = {
            "target_id": iid, "original_status": r["original_status"], "subset": r["subset"],
            "manifest_record_sha256": sha(json.dumps(r, sort_keys=True)),
            "case_sha256": r["case_sha256"], "image": r["image"], "image_digest": r["image_digest"],
            "gold_patch_sha256": r["gold_patch_sha256"], "noop_patch_sha256": noop_sha,
            "original_shard_job_id": ORIG_JOBS[iid],
            "original_timeout_evidence": {"run": "32922333871", "exit_code": 124, "timeout_minutes": 90,
                                          "note": "step killed at 90-min `timeout` (05:02->06:32)"},
            "original_p091_campaign_sha256": campaign_hash,
            "idempotency_key": sha("R22_P09_RESUME1|" + iid + "|" + r["image_digest"]),
        }
    manifest = {"experiment": "R22_P09_2_RESUME", "resume_attempt": "RESUME1",
                "resume_timeout_minutes": 180, "targets": TARGETS,
                "source_run": "32922333871", "records": recs,
                "rule": "resume ONLY these 2 missing targets, one 180-min attempt; do not alter the frozen 53"}
    json.dump(manifest, open(os.path.join(OUT, "resume_manifest.json"), "w", encoding="utf-8"), indent=2)
    print("wrote resume_manifest.json for", TARGETS)
    for iid in TARGETS:
        print("  %s idempotency=%s img=%s" % (iid, recs[iid]["idempotency_key"][:16], recs[iid]["image_digest"][:20]))


if __name__ == "__main__":
    raise SystemExit(main())
