"""Map a validated external approval to a fixed committed execution phase."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from trimem_benchmark_run import BenchmarkExecutionError, read_json, validate_exec_approval  # noqa: E402


PHASE_TO_NAME = {
    "GRADER_SMOKE": "grader-smoke",
    "DEVELOPMENT_TUNING": "development",
    "HELDOUT_BENCHMARK": "heldout",
}


def approved_name(path: Path) -> str:
    value = read_json(path)
    phase = value.get("approval", {}).get("approved_phase") if isinstance(value, dict) else None
    try:
        name = PHASE_TO_NAME[phase]
    except KeyError as exc:
        raise BenchmarkExecutionError("external approval phase is unknown") from exc
    event_name = os.environ.get("GITHUB_EVENT_NAME")
    if event_name == "push" and name != "development":
        raise BenchmarkExecutionError(
            "benchmark branch push accepts only DEVELOPMENT_TUNING approval"
        )
    if event_name == "workflow_dispatch" and name != "heldout":
        raise BenchmarkExecutionError(
            "benchmark main dispatch accepts only HELDOUT_BENCHMARK approval"
        )
    validate_exec_approval(name, path)
    return name


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()
    try:
        name = approved_name(args.approval_file.resolve())
        if args.github_env:
            with args.github_env.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(f"TRIMEM_EXEC_SPLIT={name}\n")
        print(json.dumps({"approved_manifest": name, "status": "PASS"}, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
