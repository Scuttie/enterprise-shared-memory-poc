#!/usr/bin/env python3
"""R22-P0.8.2 §1/§4 — derive the SCB smoke matrix from the FROZEN manifest (single source of truth) and verify the
manifest's SEMANTIC hash.

`9e2d24a8...` is the manifest's semantic hash produced by experiments/r22/oracle.py:
    sha256(json.dumps(task_list, sort_keys=True).encode()).hexdigest()
and is stored in the manifest as `manifest_sha256`. It is NOT a raw-file hash. Three integrity values are kept with
distinct names and never cross-compared:
  - manifest_file_sha256       : sha256 of the file bytes (LF-normalized; line-ending independent)
  - task_list_manifest_sha256  : sha256(json.dumps(task_list, sort_keys=True))  == embedded == 9e2d24a8...
  - frozen_target_ids_sha256   : sha256(json.dumps(sorted(unique target_ids)))  == 081440db...
The frozen manifest is never modified to obtain agreement."""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "artifacts", "r22")

SPEC_TASKLIST_SHA256 = "9e2d24a8a04a22b8bbab70f794fad1b8d4191ffc49aba4b4f6f296aa5dbb9fd0"  # semantic task_list hash
FROZEN_IDS_SHA256 = "081440dbbb63bed1f1b800673f4885aadce6524d1d7c637186e840f714c70a3c"   # sorted 12 P1 ids
FROZEN_TASKARM_ROWS = 84                                                                # 12 targets x O0..O6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="oracle_smoke_manifest.json")
    ap.add_argument("--out", default=os.path.join(ART, "scb_smoke_matrix.json"))
    ap.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    a = ap.parse_args()

    raw = open(os.path.join(ART, a.manifest), "rb").read()
    m = json.loads(raw)
    task_list = m["task_list"]
    ids = []
    for t in task_list:
        if t.get("target_id") not in ids:
            ids.append(t["target_id"])

    manifest_file_sha256 = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    task_list_manifest_sha256 = hashlib.sha256(json.dumps(task_list, sort_keys=True).encode()).hexdigest()
    embedded_manifest_sha256 = m.get("manifest_sha256")
    frozen_ids_sha256 = hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()

    errors = []
    if len(ids) != 12:
        errors.append("expected exactly 12 frozen targets, got %d" % len(ids))
    if len(task_list) != FROZEN_TASKARM_ROWS:
        errors.append("expected %d frozen task-arm rows, got %d" % (FROZEN_TASKARM_ROWS, len(task_list)))
    if frozen_ids_sha256 != FROZEN_IDS_SHA256:
        errors.append("frozen P1 target identity drift: %s != %s" % (frozen_ids_sha256, FROZEN_IDS_SHA256))
    # the manifest semantic hash must equal BOTH the embedded value AND the spec-required value
    if task_list_manifest_sha256 != embedded_manifest_sha256:
        errors.append("task_list hash %s != embedded manifest_sha256 %s"
                      % (task_list_manifest_sha256, embedded_manifest_sha256))
    if task_list_manifest_sha256 != SPEC_TASKLIST_SHA256:
        errors.append("task_list hash %s != spec required %s" % (task_list_manifest_sha256, SPEC_TASKLIST_SHA256))

    routes = json.load(open(os.path.join(ART, "scb_case_route_manifest.json"), encoding="utf-8"))["cases"]
    images = json.load(open(os.path.join(ART, "scb_image_manifest.json"), encoding="utf-8"))["images"]
    for iid in ids:
        if iid not in routes or not routes[iid].get("case_path"):
            errors.append("no official case for %s" % iid)
        if not (images.get(iid, {}).get("digest") or "").startswith("sha256:"):
            errors.append("no frozen image digest for %s" % iid)

    spec_matches = (task_list_manifest_sha256 == embedded_manifest_sha256 == SPEC_TASKLIST_SHA256)
    out = {"targets": len(ids), "task_arm_rows": len(task_list), "instance_ids": ids,
           "manifest_file_sha256": manifest_file_sha256,
           "task_list_manifest_sha256": task_list_manifest_sha256,
           "embedded_manifest_sha256": embedded_manifest_sha256,
           "frozen_ids_sha256": frozen_ids_sha256,
           "spec_manifest_hash_matches": spec_matches,
           "cases_present": all(iid in routes for iid in ids),
           "image_digests_present": all((images.get(iid, {}).get("digest") or "").startswith("sha256:") for iid in ids),
           "errors": errors}
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=2)

    if errors:
        print("PREPARE FAILED:", errors); return 1
    matrix = {"instance": ids}
    if a.github_output:
        with open(a.github_output, "a", encoding="utf-8") as fh:
            fh.write("matrix=%s\n" % json.dumps(matrix))
    print("PREPARE OK: 12 targets / 84 task-arm rows; task_list_manifest_sha256=%s (== embedded == spec)"
          % task_list_manifest_sha256[:16])
    print(json.dumps(matrix))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
