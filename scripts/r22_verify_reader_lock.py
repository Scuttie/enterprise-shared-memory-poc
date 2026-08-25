#!/usr/bin/env python3
"""R22 §7 — verify a committed reader-lock before P1 launches. Fail-closed. No model calls.
Usage: python scripts/r22_verify_reader_lock.py <reader_lock.json> <expected_sha256>
"""
import hashlib
import json
import sys


def main():
    path, expected = sys.argv[1], sys.argv[2]
    lock = json.load(open(path, encoding="utf-8"))
    stored = lock.pop("reader_lock_sha256", None)
    recomputed = hashlib.sha256(json.dumps(lock, sort_keys=True).encode()).hexdigest()
    fails = []
    if stored != recomputed:
        fails.append("reader lock self-hash mismatch")
    if stored != expected:
        fails.append("reader lock sha != expected (stale lock)")
    for f in ("provider", "model", "requested_model", "returned_model", "resolved_rate", "result_hash"):
        if f not in lock:
            fails.append("missing field %s" % f)
    if fails:
        print("R22 READER-LOCK VERIFY: FAIL"); [print("  -", f) for f in fails]; return 1
    print("R22 READER-LOCK VERIFY: PASS (%s @ %s)" % (lock["model"], expected[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
