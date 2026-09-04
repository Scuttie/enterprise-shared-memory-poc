"""Generate the deterministic TriMem full-path credential-free evidence bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from enterprise_memory.trimem.credential_free import run_credential_free_e2e


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="artifacts/trimem_v1/credential_free_e2e")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    expected = (Path.cwd() / "artifacts/trimem_v1/credential_free_e2e").resolve()
    if args.replace:
        if output != expected:
            raise SystemExit("--replace is restricted to the canonical generated bundle")
        if output.is_dir():
            shutil.rmtree(output)
    report = run_credential_free_e2e(output)
    print(json.dumps({
        "status": report["status"],
        "bundle_hash": report["bundle_hash"],
        "paid_model_calls": report["paid_model_calls"],
        "official_grader_execution": report["official_grader_execution"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
