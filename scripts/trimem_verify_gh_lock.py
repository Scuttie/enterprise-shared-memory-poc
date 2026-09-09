"""Verify the prefix-local GitHub CLI against the shared immutable lock."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trimem_install_pinned_gh import (
    DEFAULT_LOCK_PATH,
    load_gh_cli_lock,
    resolve_installed_binary,
    verify_installed_gh,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK_PATH)
    parser.add_argument("--prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        lock = load_gh_cli_lock(args.lock)
        report = verify_installed_gh(
            lock, resolve_installed_binary(lock, args.prefix)
        )
    except Exception:
        print(json.dumps({"status": "FAIL_CLOSED"}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
