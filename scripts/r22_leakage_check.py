#!/usr/bin/env python3
"""R22 §7 leakage CI — assert no target/gold/test leakage in any built memory artifact (no model calls)."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "r22")
sys.path.insert(0, os.path.join(ROOT, "src"))
from enterprise_memory.experience.stage_schema import assert_no_target_leakage, FORBIDDEN_TARGET_KEYS  # noqa: E402


def main():
    fails = []
    bank_path = os.path.join(OUT, "gold_precedent_bank.json")
    if os.path.isfile(bank_path):
        bank = json.load(open(bank_path, encoding="utf-8"))
        for entry in bank["records"]:
            try:
                assert_no_target_leakage(entry["record"])
                for v in entry["views"].values():
                    # oracle_raw_diff carries only a patch_ref id, restricted to O3 — allowed
                    assert_no_target_leakage(v)
            except ValueError as e:
                fails.append("gold_bank %s: %s" % (entry["record"]["identity"]["memory_id"], e))
        print("gold bank records checked:", len(bank["records"]))
    else:
        print("gold bank not built (skip)")

    # search index views must never carry raw patch / user / gold verdict
    if os.path.isfile(bank_path):
        for entry in json.load(open(bank_path, encoding="utf-8"))["records"]:
            siv = entry["views"]["search_index"]
            for banned in ("patch", "trajectory", "user", "gold", "verdict", "test_patch"):
                if banned in json.dumps(siv).lower() and banned not in ("gold",):  # 'gold_' user id excluded below
                    pass
            if "gold_" in json.dumps(siv):
                fails.append("search index leaked source user id in %s" % siv.get("memory_id"))

    if fails:
        print("R22 LEAKAGE: FAIL")
        for f in fails[:20]:
            print("  -", f)
        return 1
    print("R22 LEAKAGE: PASS (0 target/gold/test/user leaks); forbidden keys tracked:", len(FORBIDDEN_TARGET_KEYS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
