"""Build and verify the credential-free D1.22 EXEC-021 failure seal.

The seal records immutable historical accounting and the exact Qdrant nofile
correction.  It does not run the topology rehearsal, create an ``_022``
sentinel, grant execution authority, read credentials, pull images, start a
container or grader, call a model/API, or mutate Git/GitHub state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Sequence

import sys


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d122 as d122


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = ROOT.joinpath(*PurePosixPath(d122.AMENDMENT_PATH).parts)
INVENTORY_PATH = ROOT.joinpath(*PurePosixPath(d122.INVENTORY_PATH).parts)
FIXTURE_PATH = ROOT.joinpath(*PurePosixPath(d122.FAILURE_FIXTURE_PATH).parts)


class D122ResealError(ValueError):
    """The D1.22 history, accounting, correction, or authority seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D122ResealError(message)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _working_bytes(relative: str) -> bytes:
    path = ROOT.joinpath(*PurePosixPath(relative).parts)
    require(path.is_file() and not path.is_symlink(), f"file is absent: {relative}")
    return path.read_bytes()


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    require(
        not raw.startswith(b"\xef\xbb\xbf")
        and b"\x00" not in raw
        and b"\r" not in raw,
        f"noncanonical JSON encoding: {path}",
    )
    value = json.loads(raw.decode("utf-8", errors="strict"))
    require(isinstance(value, dict), f"JSON document is not an object: {path}")
    return value


def implementation_sha256() -> dict[str, str]:
    return {
        path: sha256(_working_bytes(path))
        for path in sorted(d122.IMPLEMENTATION_SEAL_PATHS)
    }


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = d122.validate_failure_fixture(ROOT)
    d122.validate_previous_request(ROOT)
    d122.validate_no_exec_022(ROOT)
    qdrant_contract = d122.validate_qdrant_source_contract()
    implementation = implementation_sha256()
    historical = {
        "execution_head": d122.PREVIOUS_EXECUTION_HEAD,
        "request_git_blob_oid": d122.PREVIOUS_SENTINEL_BLOB_OID,
        "request_path": d122.PREVIOUS_SENTINEL_PATH,
        "request_payload_sha256": d122.PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "request_raw_bytes": d122.PREVIOUS_SENTINEL_BYTES,
        "request_raw_sha256": d122.PREVIOUS_SENTINEL_SHA256,
        "run_attempt": d122.PREVIOUS_RUN_ATTEMPT,
        "run_id": d122.PREVIOUS_RUN_ID,
        "source_freeze_sha256": d122.PREVIOUS_SOURCE_FREEZE_SHA256,
        "source_head": d122.PREVIOUS_SOURCE_HEAD,
    }
    authority = {
        "development_execution_authorized": False,
        "external_execution_approval_received": False,
        "request_021_attempt_one_consumed": True,
        "request_021_attempt_two_allowed": False,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": False,
        "request_022_created_in_source": False,
        "request_022_execution_authorized": False,
        "sentinel_contains_execution_authority": False,
    }
    frozen_science = {
        "arms": list(d122.EXPECTED_STREAM_ORDER),
        "expected_usd": 10.8,
        "grader_containers": 72,
        "hard_cap_usd": 50.0,
        "model_id": d122.MODEL_ID,
        "paid_model_call_cap": 1873,
        "reasoning_effort": d122.REASONING_EFFORT,
        "scientific_generation_call_cap": 1872,
        "targets": 12,
        "task_arm_runs": 72,
        "unchanged": [
            "model",
            "pricing",
            "prompts",
            "tools",
            "parsers",
            "targets",
            "target order",
            "arms",
            "stream order",
            "budgets",
            "grader locks",
            "image locks",
        ],
    }
    rehearsal = {
        "credential_free": True,
        "execution_is_part_of_source_seal": False,
        "path": d122.QDRANT_REHEARSAL_PATH,
        "required_before_any_future_request_authority": True,
        "required_contract": {
            "collections": 12,
            "namespaces": 6,
            "payload_indexes_per_collection": 6,
            "pull_policy": "never",
            "vector_dimension": 384,
        },
        "status": "REQUIRED_NOT_EXECUTED_BY_SOURCE_SEAL",
    }
    amendment = {
        "authority_boundary": authority,
        "canary_execution_actuals": d122.CANARY_EXECUTION_ACTUALS,
        "classification": d122.AMENDMENT_CLASSIFICATION,
        "consumed_execution_actuals": d122.HISTORICAL_EXECUTION_ACTUALS,
        "current_execution_actuals": d122.ZERO_CURRENT_EXECUTION_ACTUALS,
        "endpoint": d122.AMENDMENT_ENDPOINT,
        "frozen_partial_outcome": fixture["frozen_partial_outcome"],
        "frozen_scientific_identity": frozen_science,
        "historical_execution": historical,
        "implementation_sha256": implementation,
        "outstanding_reservations": d122.OUTSTANDING_RESERVATIONS,
        "pass_at_1": None,
        "performance_measured": False,
        "qdrant_nofile_contract": qdrant_contract,
        "recovery_boundary": d122.RECOVERY_BOUNDARY,
        "rehearsal": rehearsal,
        "schema": d122.AMENDMENT_SCHEMA,
        "scientific_execution_actuals": d122.SCIENTIFIC_EXECUTION_ACTUALS,
        "scientific_status": d122.SCIENTIFIC_STATUS,
        "status": d122.AMENDMENT_STATUS,
    }
    inventory = {
        "classification": d122.AMENDMENT_CLASSIFICATION,
        "documents": {
            "amendment": d122.AMENDMENT_PATH,
            "failure_fixture": d122.FAILURE_FIXTURE_PATH,
            "report": d122.REPORT_PATH,
        },
        "endpoint": d122.AMENDMENT_ENDPOINT,
        "historical_boundary": {
            **historical,
            "failure_fixture_bytes": len(FIXTURE_PATH.read_bytes()),
            "failure_fixture_sha256": sha256(FIXTURE_PATH.read_bytes()),
        },
        "implementation_sha256": implementation,
        "qdrant_rehearsal": rehearsal,
        "schema": d122.INVENTORY_SCHEMA,
        "source_changed_paths": sorted(d122.REQUIRED_RECOVERY_CHANGES),
        "status": d122.AMENDMENT_STATUS,
    }
    canonical_bytes(amendment)
    canonical_bytes(inventory)
    require(
        fixture.get("performance_measured") is False
        and fixture.get("pass_at_1") is None
        and fixture.get("scientific_status") == d122.SCIENTIFIC_STATUS,
        "D1.22 fixture incorrectly claims campaign performance",
    )
    return amendment, inventory


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_all() -> None:
    d122.validate_no_exec_022(ROOT)
    amendment, inventory = build_artifacts()
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    d122.validate_no_exec_022(ROOT)
    amendment, inventory = build_artifacts()
    require(_read_json(AMENDMENT_PATH) == amendment, "D1.22 amendment is stale")
    require(_read_json(INVENTORY_PATH) == inventory, "D1.22 inventory is stale")
    import trimem_freeze

    trimem_freeze.check_freeze(ROOT)
    return {
        "benchmark_image_pulls": 0,
        "classification": d122.AMENDMENT_CLASSIFICATION,
        "endpoint": d122.AMENDMENT_ENDPOINT,
        "grader_containers": 0,
        "model_generation_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "qdrant_rehearsal_required": True,
        "request_021_attempt_one_consumed": True,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": False,
        "request_022_execution_authorized": False,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the no-authority D1.22 recovery seal"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_all()
        result = check_all()
    except (D122ResealError, d122.D122RecoveryError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
