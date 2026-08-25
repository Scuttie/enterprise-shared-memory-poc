#!/usr/bin/env python3
"""R22-P0.8.1 §4 — derive the SCB smoke matrix from the FROZEN manifest (single source of truth).

Verifies the frozen P1 identity, asserts exactly 12 targets each with an official case + a frozen image digest,
and emits the GitHub Actions matrix. There is NO second hard-coded target list in the workflow.

NOTE (surfaced, not silently resolved): the P0.8.1 spec states a required manifest file hash
`9e2d24a8...` that matches NEITHER the committed bytes (git-blob LF `895bcdd2...`) NOR any canonical content hash
of artifacts/r22/oracle_smoke_manifest.json. The 12 frozen target IDs are intact (sorted-id sha256 `081440db...`,
the value already frozen in tests). This script verifies the real frozen identity and RECORDS the spec-hash
discrepancy (`spec_manifest_hash_matches: false`) for the user to reconcile; it does not mutate the frozen manifest
to fabricate agreement."""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r22")

FROZEN_IDS_SHA256 = "081440dbbb63bed1f1b800673f4885aadce6524d1d7c637186e840f714c70a3c"   # sorted 12 P1 ids
GITBLOB_LF_SHA256 = "895bcdd26c137f7be883e0f3c1c3b7452b723ce268947fa5ed2dae2ad5f08c2c"   # committed bytes (Linux CI)
SPEC_REQUIRED_SHA256 = "9e2d24a8a04a22b8bbab70f794fad1b8d4191ffc49aba4b4f6f296aa5dbb9fd0"  # P0.8.1 §4 (does NOT match)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="oracle_smoke_manifest.json")
    ap.add_argument("--out", default=os.path.join(ART, "scb_smoke_matrix.json"))
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    a = ap.parse_args()

    raw = open(os.path.join(ART, a.manifest), "rb").read()
    m = json.loads(raw)
    ids = []
    for t in m["task_list"]:
        if t.get("target_id") not in ids:
            ids.append(t["target_id"])

    ids_hash = hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
    lf_hash = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()

    errors = []
    if len(ids) != 12:
        errors.append("expected exactly 12 frozen targets, got %d" % len(ids))
    if ids_hash != FROZEN_IDS_SHA256:
        errors.append("frozen P1 target identity drift: %s != %s" % (ids_hash, FROZEN_IDS_SHA256))

    routes = json.load(open(os.path.join(ART, "scb_case_route_manifest.json"), encoding="utf-8"))["cases"]
    images = json.load(open(os.path.join(ART, "scb_image_manifest.json"), encoding="utf-8"))["images"]
    for iid in ids:
        if iid not in routes or not routes[iid].get("case_path"):
            errors.append("no official case for %s" % iid)
        d = images.get(iid, {}).get("digest")
        if not (d or "").startswith("sha256:"):
            errors.append("no frozen image digest for %s" % iid)

    spec_matches = SPEC_REQUIRED_SHA256 in (lf_hash, hashlib.sha256(raw).hexdigest(), ids_hash)
    out = {"targets": len(ids), "instance_ids": ids,
           "frozen_ids_sha256": ids_hash, "manifest_gitblob_lf_sha256": lf_hash,
           "spec_required_manifest_sha256": SPEC_REQUIRED_SHA256,
           "spec_manifest_hash_matches": spec_matches,
           "spec_hash_reconciliation": ("UNRECONCILED: spec §4 hash matches neither the committed bytes nor any "
                                        "canonical content hash; frozen 12-target identity is intact"),
           "cases_present": all(iid in routes for iid in ids),
           "image_digests_present": all((images.get(iid, {}).get("digest") or "").startswith("sha256:") for iid in ids),
           "errors": errors}
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2)

    if not spec_matches:
        print("::warning::R22 sec4 spec manifest hash %s UNRECONCILED (actual lf=%s ids=%s); "
              "frozen 12-target identity intact - verifying real frozen identity instead."
              % (SPEC_REQUIRED_SHA256[:12], lf_hash[:12], ids_hash[:12]))
    if errors:
        print("PREPARE FAILED:", errors); return 1

    matrix = {"instance": ids}
    if a.github_output:
        with open(a.github_output, "a", encoding="utf-8") as fh:
            fh.write("matrix=%s\n" % json.dumps(matrix))
    print("PREPARE OK: 12 frozen targets, cases+digests present; frozen_ids_sha256=%s" % ids_hash[:16])
    print(json.dumps(matrix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
