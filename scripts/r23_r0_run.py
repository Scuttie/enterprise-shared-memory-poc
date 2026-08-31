#!/usr/bin/env python3
"""Run the R23-R0 clean-room path with a credential-free fake or replay reader.

No live/model/Docker mode exists in this entry point. Official execution remains
pending a separate EXEC approval and adapter.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.r23.author_method import ARMS  # noqa: E402
from experiments.r23.r0_runtime import FakeReader, R0Runner, ReplayReader, load_tasks_manifest  # noqa: E402


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reader", choices=("fake", "replay"), required=True)
    parser.add_argument("--tasks", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--order-id", default="credential_free_e2e")
    parser.add_argument("--arms", default=",".join(ARMS), help="comma-separated AR0..AR5")
    parser.add_argument("--replay-jsonl", type=Path)
    parser.add_argument("--failure-task-id", action="append", default=[])
    parser.add_argument("--stop-after-tasks", type=int)
    args = parser.parse_args()

    output = args.output.resolve()
    if _inside(output, ROOT / "artifacts" / "r22") or _inside(output, ROOT / "experiments" / "r22"):
        raise ValueError("R23-R0 output cannot be written inside an R22 tree")
    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    if not arms or any(arm not in ARMS for arm in arms) or len(arms) != len(set(arms)):
        raise ValueError("--arms must contain unique AR0..AR5 values")
    tasks = load_tasks_manifest(args.tasks.resolve())

    if args.reader == "replay":
        if args.replay_jsonl is None:
            raise ValueError("--replay-jsonl is required with --reader replay")
        if len(arms) != 1:
            raise ValueError("replay mode accepts exactly one arm per ordered evidence stream")
        reader = ReplayReader.from_jsonl(args.replay_jsonl.resolve())
    else:
        if args.replay_jsonl is not None:
            raise ValueError("--replay-jsonl is valid only with --reader replay")
        reader = FakeReader(args.failure_task_id)

    summaries = {}
    for arm in arms:
        runner = R0Runner(output_root=output, reader=reader)
        summaries[arm] = runner.run_stream(
            arm=arm,
            order_id=args.order_id,
            tasks=tasks,
            stop_after_tasks=args.stop_after_tasks,
        )
    report = {
        "schema_version": "r23/r0/credential_free_run/1.0.0",
        "reader": args.reader,
        "arms": arms,
        "summaries": summaries,
        "external_model_calls_now": sum(row["external_model_calls_now"] for row in summaries.values()),
        "paid_model_calls_now": sum(row["paid_model_calls_now"] for row in summaries.values()),
        "docker_calls_now": 0,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
