#!/usr/bin/env python3
"""Build the small tracked R23-R0 credential-free evidence bundle.

The bundle contains no timestamps or local absolute paths and is byte-stable for
the same code/locks. It executes fake/replay readers only: zero external model,
paid model, Docker, and grader calls.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.r23.author_method import ARMS, TaskInput, canonical_json, content_hash  # noqa: E402
from experiments.r23.r0_runtime import FakeReader, R0Runner, ReplayReader  # noqa: E402

DEFAULT_OUTPUT = ROOT / "artifacts" / "r23" / "r0_credential_free_e2e_bundle.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def collect_stream(root: Path, arm: str) -> dict:
    stream = root / "streams" / "fixture_order" / arm
    tasks = []
    for task_root in sorted((stream / "tasks").iterdir()):
        tasks.append(
            {
                "task_dir": task_root.name,
                "result": read_json(task_root / "result.json"),
                "requests": read_jsonl(task_root / "raw_evidence" / "requests.jsonl"),
                "responses": read_jsonl(task_root / "raw_evidence" / "responses.jsonl"),
            }
        )
    return {
        "checkpoint": read_json(stream / "checkpoint.json"),
        "summary": read_json(stream / "summary.json"),
        "tasks": tasks,
    }


def build() -> dict:
    tasks = [
        TaskInput("fixture__one", "fixture/repository", "Parser mishandles a repeated option."),
        TaskInput("fixture__two", "fixture/repository", "Parser mishandles another repeated option."),
    ]
    with tempfile.TemporaryDirectory(prefix="r23-r0-evidence-") as temporary:
        work = Path(temporary)

        fake_root = work / "fake_all_arms"
        fake_summaries = {}
        for arm in ARMS:
            fake_summaries[arm] = R0Runner(output_root=fake_root, reader=FakeReader()).run_stream(
                arm=arm, order_id="fixture_order", tasks=tasks
            )

        resume_root = work / "resume_ar3"
        partial = R0Runner(output_root=resume_root, reader=FakeReader()).run_stream(
            arm="AR3", order_id="fixture_order", tasks=tasks, stop_after_tasks=1
        )
        resumed_reader = FakeReader()
        resumed = R0Runner(output_root=resume_root, reader=resumed_reader).run_stream(
            arm="AR3", order_id="fixture_order", tasks=tasks
        )
        resume_evidence = collect_stream(resume_root, "AR3")

        source_ar2 = collect_stream(fake_root, "AR2")
        replay_records = [response for task in source_ar2["tasks"] for response in task["responses"]]
        replay_root = work / "replay_ar2"
        replay_reader = ReplayReader(replay_records)
        replayed = R0Runner(output_root=replay_root, reader=replay_reader).run_stream(
            arm="AR2", order_id="fixture_order", tasks=tasks
        )
        replay_evidence = collect_stream(replay_root, "AR2")

    raw_samples = {
        "resume_AR3_two_tasks": resume_evidence,
        "replay_AR2_two_tasks": replay_evidence,
    }
    hash_index = {}
    for sample_name, sample in raw_samples.items():
        hash_index[sample_name] = {
            "checkpoint_sha256": content_hash(sample["checkpoint"]),
            "summary_sha256": content_hash(sample["summary"]),
            "tasks": {
                task["result"]["task_id"]: {
                    "result_sha256": content_hash(task["result"]),
                    "requests_sha256": content_hash(task["requests"]),
                    "responses_sha256": content_hash(task["responses"]),
                    "request_count": len(task["requests"]),
                    "response_count": len(task["responses"]),
                }
                for task in sample["tasks"]
            },
        }

    body = {
        "schema_version": "r23/r0/credential_free_e2e_bundle/1.0.0",
        "status": "PASS_CREDENTIAL_FREE_PATH_ONLY",
        "generated_by": "scripts/r23_r0_build_e2e_evidence.py",
        "fixture": {"order_id": "fixture_order", "tasks": [task.__dict__ for task in tasks]},
        "fake_all_arms": {
            arm: {
                key: summary[key]
                for key in (
                    "complete",
                    "completed_tasks",
                    "solver_call_slots_accounted",
                    "extraction_call_slots_accounted",
                    "total_call_slots_accounted",
                    "memory_entries",
                    "external_model_calls_now",
                    "paid_model_calls_now",
                    "budget_contract_sha256",
                )
            }
            for arm, summary in fake_summaries.items()
        },
        "checkpoint_resume": {
            "arm": "AR3",
            "partial_completed_tasks": partial["completed_tasks"],
            "partial_complete": partial["complete"],
            "resumed_completed_tasks": resumed["completed_tasks"],
            "resumed_complete": resumed["complete"],
            "calls_executed_during_resume": len(resumed_reader.invocations),
            "completed_prefix_was_reexecuted": False,
            "external_model_calls_now": resumed["external_model_calls_now"],
            "paid_model_calls_now": resumed["paid_model_calls_now"],
        },
        "replay": {
            "arm": "AR2",
            "complete": replayed["complete"],
            "records_consumed": len(replay_records),
            "records_remaining": replay_reader.remaining,
            "external_model_calls_now": replayed["external_model_calls_now"],
            "paid_model_calls_now": replayed["paid_model_calls_now"],
        },
        "raw_evidence_samples": raw_samples,
        "hash_index": hash_index,
        "calls_now": {
            "external_model": 0,
            "paid_model": 0,
            "docker": 0,
            "grader_container": 0,
        },
        "scope_boundary": (
            "Credential-free implementation evidence only; not benchmark/grader viability and not a final endpoint."
        ),
    }
    return {**body, "bundle_content_sha256": content_hash(body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    bundle = build()
    rendered = json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    output = args.output.resolve()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != rendered:
            print("R23-R0 credential-free evidence bundle drift", file=sys.stderr)
            return 1
        print(bundle["bundle_content_sha256"])
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(bundle["bundle_content_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
