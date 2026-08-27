#!/usr/bin/env python3
"""R22 §8 — verify P1 integrity PASS before P2 starts. Fail-closed. No model calls.
Usage: python scripts/r22_verify_p1_pass.py <p1_integrity_result.json> [expected_result_hash]
"""
import json
import sys


def main():
    path = sys.argv[1]
    expected_hash = sys.argv[2] if len(sys.argv) > 2 else None
    r = json.load(open(path, encoding="utf-8"))
    fails = []
    if r.get("verdict") != "P1_INTEGRITY_PASS":
        fails.append("verdict is %s (need P1_INTEGRITY_PASS)" % r.get("verdict"))
    if not r.get("integrity_clean"):
        fails.append("integrity not clean: %s" % r.get("violations", [])[:5])
    if r.get("cells") != r.get("expected"):
        fails.append("incomplete: %s/%s cells" % (r.get("cells"), r.get("expected")))
    if expected_hash and r.get("result_hash") != expected_hash:
        fails.append("result hash != expected (stale P1 artifact)")
    if fails:
        print("R22 P1-PASS VERIFY: FAIL"); [print("  -", f) for f in fails]; return 1
    print("R22 P1-PASS VERIFY: PASS (%s cells)" % r.get("cells"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
