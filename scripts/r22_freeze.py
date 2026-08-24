#!/usr/bin/env python3
"""R22 §15 — freeze/seal all R22 manifests. Records a hash of every artifact; --check fails if any drifted."""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "r22")
FREEZE = os.path.join(OUT, "freeze.json")
SEALED = [
    "benchmark_lock.json", "leakage_audit.json", "duplicate_audit.json", "repository_alias_map.json",
    "temporal_reaudit.json", "dev_manifest.json", "main_manifest.json", "partition_log.json",
    "dev_manifest_v2.json", "main_manifest_v2.json", "power_grid.json", "gold_precedent_manifest.json",
    "oracle_smoke_manifest.json", "oracle_dev_manifest.json", "oracle_arm_manifest.json",
    "grader_smoke_manifest.json", "upstream/swe_exp_lock.json",
]


def _sha(p):
    with open(p, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def build():
    hashes = {}
    for rel in SEALED:
        p = os.path.join(OUT, rel)
        hashes[rel] = _sha(p) if os.path.isfile(p) else None
    man = {"schema": "r22/freeze/1.0.0", "hashes": hashes}
    man["freeze_sha256"] = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return man


def main():
    check = "--check" in sys.argv
    man = build()
    if check:
        if not os.path.isfile(FREEZE):
            print("R22 freeze missing"); return 1
        old = json.load(open(FREEZE, encoding="utf-8"))
        if {k: v for k, v in old.get("hashes", {}).items()} != man["hashes"]:
            print("R22 SEAL DRIFT — main must refuse to run"); return 1
        print("R22 seal current:", man["freeze_sha256"][:16]); return 0
    json.dump(man, open(FREEZE, "w", encoding="utf-8"), indent=2)
    print("wrote freeze.json:", man["freeze_sha256"][:16])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
