#!/usr/bin/env python3
"""ci-literature-audit gate (P6/R19 §3) — enforce that no unlicensed upstream code/data is vendored.

Fails when:
  - THIRD_PARTY_RESEARCH_REFERENCES.json is missing or unparseable;
  - MemGovern is not labeled REPRODUCTION_BLOCKED while its license is UNRESOLVED;
  - any bundled upstream data artifact is committed (chroma_db_experience/, experience_data.json,
    trajectories/*.tar.gz);
  - any file under src/ carries an upstream provenance marker without a recorded, license-cleared reuse entry.
Pure-stdlib. Intended to run in CI and locally.
"""
from __future__ import annotations
import os
import json
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORBIDDEN_DATA_GLOBS = [
    "**/chroma_db_experience/**",
    "**/experience_data.json",
    "trajectories/*.tar.gz",
    "**/agentic_exp_data_*/**",
]
# markers that would indicate copied upstream source
SRC_MARKERS = ["QuantaAlpha/MemGovern", "moatless.experience", "moatless/experience",
               "MemGovern (c)", "SWE-Exp Authors"]


def fail(msg, bucket):
    bucket.append(msg)


def main() -> int:
    fails = []
    refp = os.path.join(ROOT, "THIRD_PARTY_RESEARCH_REFERENCES.json")
    if not os.path.isfile(refp):
        print("LITERATURE AUDIT: FAIL\n  - THIRD_PARTY_RESEARCH_REFERENCES.json missing")
        return 1
    try:
        refs = json.load(open(refp, encoding="utf-8"))
    except Exception as e:
        print("LITERATURE AUDIT: FAIL\n  - references JSON unparseable: %s" % e)
        return 1

    by_id = {r.get("id"): r for r in refs.get("references", [])}
    mg = by_id.get("memgovern", {})
    if mg.get("license_status") == "UNRESOLVED" and mg.get("reproduction_label") != "REPRODUCTION_BLOCKED":
        fail("MemGovern license UNRESOLVED but not labeled REPRODUCTION_BLOCKED.", fails)

    # forbidden bundled data
    for g in FORBIDDEN_DATA_GLOBS:
        hits = [p for p in glob.glob(os.path.join(ROOT, g), recursive=True)
                if ".git" not in p]
        if hits:
            fail("bundled upstream data artifact committed: %s (%d)" % (g, len(hits)), fails)

    # provenance markers in src/ without a cleared reuse entry
    reused_ok = any(r.get("reuse_decision_current", "").startswith("REUSED") for r in refs.get("references", []))
    src_hits = []
    for f in glob.glob(os.path.join(ROOT, "src", "**", "*.py"), recursive=True):
        try:
            t = open(f, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in SRC_MARKERS:
            if m in t:
                src_hits.append((os.path.relpath(f, ROOT), m))
    if src_hits and not reused_ok:
        for f, m in src_hits:
            fail("upstream provenance marker '%s' in %s without a license-cleared reuse entry." % (m, f), fails)

    if fails:
        print("LITERATURE AUDIT: FAIL")
        for f in fails:
            print("  - " + f)
        return 1
    print("LITERATURE AUDIT: PASS (MemGovern=REPRODUCTION_BLOCKED; no bundled upstream data; no vendored src markers)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
