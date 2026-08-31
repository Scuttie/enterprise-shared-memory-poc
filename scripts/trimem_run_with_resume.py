"""Run one approved benchmark phase with one same-attempt recovery try.

This wrapper never changes target selection or approval scope. It records both
process attempts verbatim in restricted evidence and returns the final nonzero
status if the one permitted resume attempt also fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, raw: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def run_with_one_resume(split: str, approval_file: Path) -> int:
    output = ROOT / "artifacts/trimem_v1/benchmark_exec" / split / "driver-evidence"
    base = [
        sys.executable,
        str(ROOT / "scripts/trimem_benchmark_run.py"),
        "--split", split,
        "--approval-file", str(approval_file.resolve()),
    ]
    attempts = []
    final_code = 1
    for index, resume in enumerate((False, True), start=1):
        command = [*base, *(["--resume"] if resume else [])]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
        stdout = _write(output / f"attempt-{index}.stdout.bin", completed.stdout)
        stderr = _write(output / f"attempt-{index}.stderr.bin", completed.stderr)
        attempts.append({
            "attempt": index,
            "argv": ["python", "scripts/trimem_benchmark_run.py", "--split", split,
                     "--approval-file", "<external-protected-approval>", *(["--resume"] if resume else [])],
            "exit_code": completed.returncode,
            "resume": resume,
            "stdout": stdout,
            "stderr": stderr,
        })
        sys.stdout.buffer.write(completed.stdout)
        sys.stdout.buffer.flush()
        sys.stderr.buffer.write(completed.stderr)
        sys.stderr.buffer.flush()
        final_code = completed.returncode
        if completed.returncode == 0:
            break
    manifest = {
        "schema": "trimem/benchmark-process-attempts/1.0",
        "split": split,
        "same_workflow_run_and_attempt_required_by_external_approval": True,
        "maximum_resume_attempts": 1,
        "attempts": attempts,
        "status": "PASS" if final_code == 0 else "FAIL",
    }
    (output / "attempts.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return 0 if final_code == 0 else max(1, final_code)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("development", "heldout"), required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    args = parser.parse_args()
    return run_with_one_resume(args.split, args.approval_file)


if __name__ == "__main__":
    raise SystemExit(main())
