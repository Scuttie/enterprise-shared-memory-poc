"""Verify the vendored frozen memory bank after a host move.

The frozen bank pins every record by absolute path plus sha256, so a clone on a
different host has to map the original capture host's root onto the vendored
copy before any of it resolves. Rewriting nothing but the prefix keeps the
hashes meaningful: each file still has to hash to the value the bank recorded.

    python scripts/trimem_skhynix_verify_portable_bank.py [--bank-root DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ORIGINAL_ROOT = "/home/trimem-runner/skhynix-architecture-scale-001"
DEFAULT_BANK_ROOT = (Path(__file__).resolve().parent.parent / "artifacts" / "skhynix_v1"
                     / "architecture_scale_001" / "frozen-bank-240")
MANIFEST_RELATIVE = "pipeline-v15/bank-240/bank.json"
EXPECTED = {"L1_episodes": 919, "L2_nodes": 4653, "L2_edges": 4193, "L3_skills": 1}


def remap(reference_path, bank_root):
    if not reference_path.startswith(ORIGINAL_ROOT + "/"):
        raise ValueError("Reference outside the original capture root: " + reference_path)
    return bank_root / reference_path[len(ORIGINAL_ROOT) + 1:]


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def check(reference, bank_root, failures):
    path = remap(reference["path"], bank_root)
    if not path.is_file():
        failures.append({"path": reference["path"], "reason": "MISSING"})
    elif file_hash(path) != reference["sha256"]:
        failures.append({"path": reference["path"], "reason": "HASH_DIFFERS"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bank-root", default=str(DEFAULT_BANK_ROOT))
    arguments = parser.parse_args()
    bank_root = Path(arguments.bank_root).resolve()
    manifest_path = bank_root / MANIFEST_RELATIVE
    manifest = json.loads(manifest_path.read_bytes())

    failures, checked = [], 1
    manifest_sha = file_hash(manifest_path)
    for key in ("authority", "source_authority"):
        check(manifest[key], bank_root, failures)
        checked += 1
    for key in ("captures", "proposals", "observations"):
        for reference in manifest["catalog"][key].values():
            check(reference, bank_root, failures)
            checked += 1

    counts = dict(manifest["layer_counts"])
    counts["L2_edges"] = len(manifest["catalog"]["edges"])
    result = {
        "schema": "skhynix/portable-bank-verification/1.0",
        "status": "PASS" if not failures and counts == EXPECTED else "FAIL",
        "bank_root": str(bank_root),
        "original_root": ORIGINAL_ROOT,
        "manifest_sha256": manifest_sha,
        "references_checked": checked,
        "layer_counts": counts,
        "layer_counts_expected": EXPECTED,
        "catalog_sizes": {key: len(manifest["catalog"][key])
                          for key in ("captures", "proposals", "observations", "edges")},
        "failures": failures[:20],
        "failure_count": len(failures),
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True)
    print()
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
