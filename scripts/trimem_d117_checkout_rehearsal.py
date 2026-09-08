"""Credential-free rehearsal of all frozen DEV task checkout bytes.

This command stops before provider access, image materialization, Docker, or an
official grader.  It exercises the exact production clone/checkout and raw
Git-blob construction path for every frozen DEVELOPMENT target.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from trimem_benchmark_run import (  # noqa: E402
    BenchmarkExecutionError,
    _GIT_BLOB_MATERIALIZATION_SCHEMA,
    _GIT_BLOB_SOURCE_IDENTITY,
    _GIT_BLOB_TRANSFORM_RULE,
    _valid_checkout_materialization_evidence,
    atomic_write,
    canonical_bytes,
    coding_tasks,
    image_entries,
    load_frozen_rows,
    prepare_checkouts,
    validate_pristine_checkout,
)


REPORT_SCHEMA = "trimem/development-task-checkout-rehearsal/1.0"
EMPTY_PATH_SET_SHA256 = (
    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)
EXPECTED_MATERIALIZATION: dict[str, tuple[int, int, str]] = {
    "swebench_verified--django__django-16100": (6645, 0, EMPTY_PATH_SET_SHA256),
    "swebench_verified--sympy__sympy-23262": (1968, 0, EMPTY_PATH_SET_SHA256),
    "swebench_verified--sphinx-doc__sphinx-11445": (
        1635,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    "swebench_verified--matplotlib__matplotlib-25311": (
        4393,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    "multi_swe_bench_mini--mui__material-ui-29880": (
        37002,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    "multi_swe_bench_mini--ponylang__ponyc-1981": (
        697,
        1,
        "1c0fc6c9cbbb976f487528140255670f1c97f7c9a2d5fc99c4cdc1ba38470f76",
    ),
    "multi_swe_bench_mini--clap-rs__clap-3960": (
        625,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    "multi_swe_bench_mini--facebook__zstd-938": (
        389,
        30,
        "9e990b89344de1db4fd5fc3965743652760e8fd10cc1771ea4ecfb8c431845bf",
    ),
    "multi_swe_bench_flash--sharkdp__bat-1276": (
        309,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    "multi_swe_bench_flash--catchorg__Catch2-1616": (
        346,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    "multi_swe_bench_flash--clap-rs__clap-3394": (
        381,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    "multi_swe_bench_flash--cli__cli-869": (
        154,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
}


def build_rehearsal(
    *,
    checkout_root: Path,
    cache_root: Path,
) -> dict[str, Any]:
    checkout_root = checkout_root.absolute()
    cache_root = cache_root.absolute()
    if checkout_root.exists():
        raise BenchmarkExecutionError("checkout rehearsal root must be fresh")

    targets, rows = load_frozen_rows("development", cache_root)
    if len(targets) != 12 or {
        str(target["target_id"]) for target in targets
    } != set(EXPECTED_MATERIALIZATION):
        raise BenchmarkExecutionError("frozen DEV rehearsal target set differs")
    tasks = coding_tasks(targets, rows)
    images, _support = image_entries(require_benchmark=True)
    factory, checkout_evidence = prepare_checkouts(
        tasks,
        targets,
        images,
        checkout_root,
        resume=False,
    )

    result_rows: list[dict[str, Any]] = []
    total_regular = 0
    total_normalized = 0
    for order_index, (task, target) in enumerate(zip(tasks, targets)):
        target_id = str(target["target_id"])
        evidence = checkout_evidence.get(task.task_id)
        materialization = (
            evidence.get("materialization") if isinstance(evidence, dict) else None
        )
        expected_regular, expected_count, expected_hash = EXPECTED_MATERIALIZATION[
            target_id
        ]
        if (
            not isinstance(materialization, dict)
            or evidence.get("checkout_origin") != "FRESH_CLONE"
            or not isinstance(evidence.get("argv"), list)
            or len(evidence["argv"]) != 2
            or not _valid_checkout_materialization_evidence(
                materialization,
                expected_commit=task.commit,
            )
            or materialization.get("schema")
            != _GIT_BLOB_MATERIALIZATION_SCHEMA
            or materialization.get("status") != "PASS"
            or materialization.get("source_identity") != _GIT_BLOB_SOURCE_IDENTITY
            or materialization.get("transform_rule") != _GIT_BLOB_TRANSFORM_RULE
            or materialization.get("commit") != task.commit
            or materialization.get("regular_blob_count") != expected_regular
            or materialization.get("normalized_path_count") != expected_count
            or materialization.get("normalized_paths_sha256") != expected_hash
        ):
            raise BenchmarkExecutionError(
                f"DEV checkout materialization differs: {target_id}"
            )
        checkout = factory.checkout_roots[task.task_id]
        validate_pristine_checkout(checkout, task.commit)
        total_regular += expected_regular
        total_normalized += expected_count
        result_rows.append(
            {
                "order_index": order_index,
                "target_id": target_id,
                "repository": task.repository,
                "commit": task.commit,
                "tree_object_id": materialization["tree_object_id"],
                "regular_blob_count": expected_regular,
                "normalized_paths": materialization["normalized_paths"],
                "normalized_path_count": expected_count,
                "normalized_paths_sha256": expected_hash,
                "strict_raw_blob_validation": "PASS",
            }
        )
    if total_regular != 54_544 or total_normalized != 31:
        raise BenchmarkExecutionError("DEV checkout rehearsal totals differ")
    return {
        "schema": REPORT_SCHEMA,
        "status": "PASS",
        "split": "DEVELOPMENT_TUNING",
        "credential_access": False,
        "model_calls": 0,
        "image_pulls": 0,
        "grader_containers": 0,
        "official_grader_runs": 0,
        "task_arm_runs": 0,
        "source_identity": _GIT_BLOB_SOURCE_IDENTITY,
        "transform_rule": _GIT_BLOB_TRANSFORM_RULE,
        "target_count": len(result_rows),
        "regular_blob_count": total_regular,
        "normalized_path_count": total_normalized,
        "targets": result_rows,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkout-root", required=True, type=Path)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_rehearsal(
        checkout_root=args.checkout_root,
        cache_root=args.cache_root,
    )
    atomic_write(args.output.absolute(), canonical_bytes(report) + b"\n")
    print("TRIMEM_DEVELOPMENT_TASK_CHECKOUT_REHEARSAL_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
