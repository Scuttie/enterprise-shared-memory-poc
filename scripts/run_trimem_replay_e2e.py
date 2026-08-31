"""Generate the deterministic TriMem full-path credential-free evidence bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from enterprise_memory.trimem.credential_free import run_credential_free_e2e


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/trimem_v1/credential_free_e2e")
    args = parser.parse_args()
    report = run_credential_free_e2e(Path(args.output))
    print(json.dumps({
        "status": report["status"],
        "bundle_hash": report["bundle_hash"],
        "paid_model_calls": report["paid_model_calls"],
        "official_grader_execution": report["official_grader_execution"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
