"""Credential-free full grader-factory/loader binding rehearsal.

The workflow deliberately runs this command through the ``python`` launcher
alias after producing loader evidence with ``python3.11``.  A successful run
therefore proves that the production factory reuses the exact approved
preflight launcher and that the complete journal-time loader comparison passes
before any model call, Docker command, or official grader process can start.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import os
import sys
from typing import Any, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from trimem_benchmark_run import (  # noqa: E402
    JournaledGraderGateway,
    TerminalInvocationJournal,
    atomic_write,
    canonical_bytes,
    grader_factory,
    image_entries,
    load_frozen_rows,
    read_json,
    sha256_bytes,
    validate_official_harness_loader_preflight_evidence,
    validate_preflight_harness_root_binding,
)
from trimem_official_grader import canonical_row_hash  # noqa: E402


REPORT_SCHEMA = "trimem/development-grader-factory-rehearsal/1.0"
FORBIDDEN_CREDENTIAL_NAMES = frozenset(
    {
        "OPENAI_API_KEY",
        "TRIMEM_EXEC_APPROVAL_B64",
        "TRIMEM_EVIDENCE_PASSPHRASE",
    }
)


def _synthetic_inputs() -> tuple[
    list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]
]:
    """Return construction-only rows for all three official adapter routes."""

    targets: list[dict[str, Any]] = []
    rows: dict[str, dict[str, Any]] = {}
    images: dict[str, dict[str, Any]] = {}
    for index, benchmark_id in enumerate(
        (
            "swebench_verified",
            "multi_swe_bench_mini",
            "multi_swe_bench_flash",
        )
    ):
        instance_id = f"trimem__loader-{index + 1}"
        row = {"adapter_route": benchmark_id, "instance_id": instance_id}
        target_id = f"{benchmark_id}--{instance_id}"
        targets.append(
            {
                "base_commit": f"{index + 1:040x}",
                "benchmark_id": benchmark_id,
                "dataset_revision": f"{index + 4:040x}",
                "instance_id": instance_id,
                "repository": "trimem/loader",
                "source_row_sha256": canonical_row_hash(row),
                "target_id": target_id,
            }
        )
        rows[instance_id] = row
        images[instance_id] = {
            "harness_image_tag": f"trimem/loader:preflight-{index}",
            "image": f"trimem/loader@sha256:{index + 1:064x}",
        }
    return targets, rows, images


def build_rehearsal(
    *,
    preflight_path: Path,
    harness_root: Path,
    dataset_cache_root: Path,
    output_root: Path,
    synthetic: bool = False,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    source_environment = os.environ if environment is None else environment
    present = sorted(FORBIDDEN_CREDENTIAL_NAMES.intersection(source_environment))
    if present:
        raise ValueError(
            "grader-factory rehearsal environment contains protected credentials"
        )

    preflight = validate_official_harness_loader_preflight_evidence(
        read_json(preflight_path)
    )
    harnesses = {
        "swebench_verified": harness_root / "swebench_verified",
        "multi_swe_bench_mini": harness_root / "multi",
        "multi_swe_bench_flash": harness_root / "multi",
    }
    validate_preflight_harness_root_binding(preflight, harnesses)
    if synthetic:
        targets, rows, images = _synthetic_inputs()
        support: Sequence[tuple[str, str]] = ()
    else:
        targets, rows = load_frozen_rows("development", dataset_cache_root)
        images, support = image_entries(require_benchmark=True)
    expected_preflight_sha256 = sha256_bytes(canonical_bytes(preflight))
    preflight_launcher = str(preflight["python_loader"]["python_binary"])

    result_rows: list[dict[str, Any]] = []
    for order_index, target in enumerate(targets):
        instance_id = str(target["instance_id"])
        gateway = grader_factory(
            target,
            rows[instance_id],
            images[instance_id],
            harnesses,
            output_root / f"{order_index:03d}-{target['target_id']}",
            "M2",
            support,
            loader_preflight_evidence=preflight,
        )
        journaled = JournaledGraderGateway(
            gateway,
            TerminalInvocationJournal(
                output_root / f"{order_index:03d}-journal"
            ),
            preflight_evidence=preflight,
            python_binary=preflight_launcher,
        )
        observed_sha256 = journaled._preflight_sha256()
        if observed_sha256 != expected_preflight_sha256:
            raise ValueError("journal-time loader preflight digest differs")
        result_rows.append(
            {
                "benchmark_id": target["benchmark_id"],
                "instance_id": instance_id,
                "loader_preflight_sha256": observed_sha256,
                "order_index": order_index,
                "status": "PASS",
                "target_id": target["target_id"],
            }
        )

    expected_target_count = 3 if synthetic else 12
    if len(result_rows) != expected_target_count:
        raise ValueError("grader-factory rehearsal target count differs")
    return {
        "credential_access": False,
        "environment_identity_sha256": preflight[
            "environment_identity_sha256"
        ],
        "grader_containers": 0,
        "image_pulls": 0,
        "journal_preflight_checks": len(result_rows),
        "loader_preflight_sha256": expected_preflight_sha256,
        "model_calls": 0,
        "mode": "SYNTHETIC_ADAPTER_ROUTES" if synthetic else "FROZEN_DEVELOPMENT",
        "official_grader_runs": 0,
        "preflight_launcher": preflight_launcher,
        "runtime_launcher": sys.executable,
        "schema": REPORT_SCHEMA,
        "status": "PASS",
        "target_count": len(result_rows),
        "targets": result_rows,
        "task_arm_runs": 0,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--harness-root", required=True, type=Path)
    parser.add_argument("--dataset-cache-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--synthetic", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_rehearsal(
        preflight_path=args.preflight,
        harness_root=args.harness_root,
        dataset_cache_root=args.dataset_cache_root,
        output_root=args.output_root,
        synthetic=args.synthetic,
    )
    atomic_write(args.report, canonical_bytes(report) + b"\n")
    print("TRIMEM_DEVELOPMENT_GRADER_FACTORY_REHEARSAL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
