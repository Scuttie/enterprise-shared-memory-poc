"""Build and verify the credential-free D1.21 ``_021`` recovery seal.

The seal records the spent EXEC ``_020`` accounting and the narrow SWE
outcome-normalization correction.  It grants request-creation authority only;
it never accesses credentials or executes a model, image pull, container,
grader, benchmark task, GitHub mutation, merge, tag, or release.
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

import trimem_development_trigger_d121 as d121


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = ROOT.joinpath(*PurePosixPath(d121.AMENDMENT_PATH).parts)
INVENTORY_PATH = ROOT.joinpath(*PurePosixPath(d121.INVENTORY_PATH).parts)
FIXTURE_PATH = ROOT.joinpath(*PurePosixPath(d121.PREVIOUS_FAILURE_FIXTURE_PATH).parts)
FREEZE_PATH = ROOT.joinpath(*PurePosixPath(d121.FREEZE_PATH).parts)


class D121ResealError(ValueError):
    """The D1.21 history, accounting, authority boundary, or seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D121ResealError(message)


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
        not raw.startswith(b"\xef\xbb\xbf") and b"\x00" not in raw and b"\r" not in raw,
        f"noncanonical JSON encoding: {path}",
    )
    value = json.loads(raw.decode("utf-8", errors="strict"))
    require(isinstance(value, dict), f"JSON document is not an object: {path}")
    return value


def validate_fixture() -> dict[str, Any]:
    raw = FIXTURE_PATH.read_bytes()
    value = _read_json(FIXTURE_PATH)
    require(
        len(raw) == d121.PREVIOUS_FAILURE_FIXTURE_BYTES
        and sha256(raw) == d121.PREVIOUS_FAILURE_FIXTURE_SHA256
        and raw
        == json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n",
        "D1.21 failure fixture identity differs",
    )
    require(
        value.get("actuals") == d121.HISTORICAL_EXECUTION_ACTUALS
        and value.get("scientific_actuals") == d121.SCIENTIFIC_EXECUTION_ACTUALS
        and value.get("canary_actuals") == d121.CANARY_EXECUTION_ACTUALS
        and value.get("root_cause", {}).get("recovery_contract")
        == d121.OUTCOME_NORMALIZATION_CONTRACT,
        "D1.21 failure fixture accounting or contract differs",
    )
    return value


def implementation_sha256() -> dict[str, str]:
    return {
        path: sha256(_working_bytes(path))
        for path in sorted(d121.IMPLEMENTATION_SEAL_PATHS)
    }


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    fixture = validate_fixture()
    implementation = implementation_sha256()
    changed_paths = sorted(d121.REQUIRED_RECOVERY_CHANGES)
    historical = {
        "execution_head": d121.PREVIOUS_EXECUTION_HEAD,
        "request_git_blob_oid": d121.PREVIOUS_SENTINEL_BLOB_OID,
        "request_path": d121.PREVIOUS_SENTINEL_PATH,
        "request_payload_sha256": d121.PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "request_raw_bytes": d121.PREVIOUS_SENTINEL_BYTES,
        "request_raw_sha256": d121.PREVIOUS_SENTINEL_SHA256,
        "run_attempt": d121.PREVIOUS_RUN_ATTEMPT,
        "run_id": d121.PREVIOUS_RUN_ID,
        "source_freeze_sha256": d121.PREVIOUS_SOURCE_FREEZE_SHA256,
        "source_head": d121.PREVIOUS_SOURCE_HEAD,
    }
    authority = {
        "development_execution_authorized": False,
        "external_execution_approval_received": False,
        "request_020_attempt_one_consumed": True,
        "request_020_rerun_allowed": False,
        "request_021_created_in_source": False,
        "request_021_execution_authorized": False,
        "request_021_request_creation_authorized": True,
        "required_external_authorization": d121.REQUIRED_EXTERNAL_AUTHORIZATION,
    }
    frozen_science = {
        "arms": list(d121.EXPECTED_STREAM_ORDER),
        "expected_usd": 10.8,
        "grader_containers": 72,
        "hard_cap_usd": 50.0,
        "model_id": d121.MODEL_ID,
        "paid_model_call_cap": 1873,
        "reasoning_effort": d121.REASONING_EFFORT,
        "scientific_generation_call_cap": 1872,
        "task_arm_runs": 72,
        "targets": 12,
        "unchanged": [
            "model",
            "pricing",
            "prompts",
            "tools",
            "parsers",
            "targets",
            "arms",
            "budgets",
            "grader locks",
            "image locks",
        ],
    }
    amendment = {
        "authority_boundary": authority,
        "canary_execution_actuals": d121.CANARY_EXECUTION_ACTUALS,
        "classification": d121.AMENDMENT_CLASSIFICATION,
        "consumed_execution_actuals": d121.HISTORICAL_EXECUTION_ACTUALS,
        "endpoint": d121.AMENDMENT_ENDPOINT,
        "frozen_scientific_identity": frozen_science,
        "historical_execution": historical,
        "implementation_sha256": implementation,
        "recovery_contract": d121.OUTCOME_NORMALIZATION_CONTRACT,
        "schema": d121.AMENDMENT_SCHEMA,
        "scientific_execution_actuals": d121.SCIENTIFIC_EXECUTION_ACTUALS,
        "scientific_outcome": {
            "fail_to_pass_failures": 0,
            "pass_to_pass_regressions": 1,
            "resolved": False,
            "status": "UNRESOLVED",
        },
        "status": d121.AMENDMENT_STATUS,
    }
    inventory = {
        "classification": d121.AMENDMENT_CLASSIFICATION,
        "documents": {
            "amendment": d121.AMENDMENT_PATH,
            "failure_fixture": d121.PREVIOUS_FAILURE_FIXTURE_PATH,
            "report": d121.REPORT_PATH,
        },
        "endpoint": d121.AMENDMENT_ENDPOINT,
        "historical_boundary": {
            **historical,
            "failure_fixture_bytes": len(FIXTURE_PATH.read_bytes()),
            "failure_fixture_sha256": sha256(FIXTURE_PATH.read_bytes()),
        },
        "implementation_sha256": implementation,
        "schema": d121.INVENTORY_SCHEMA,
        "source_changed_paths": changed_paths,
        "status": d121.AMENDMENT_STATUS,
    }
    # Exercise finite/canonical serialization before returning either record.
    canonical_bytes(amendment)
    canonical_bytes(inventory)
    require(
        fixture.get("performance_measured") is False
        and fixture.get("pass_at_1") is None,
        "D1.21 receipt incorrectly claims campaign performance",
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
    request_path = ROOT.joinpath(*PurePosixPath(d121.SENTINEL_PATH).parts)
    require(not request_path.exists(), "D1.21 source already contains `_021`")
    amendment, inventory = build_artifacts()
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    amendment, inventory = build_artifacts()
    require(_read_json(AMENDMENT_PATH) == amendment, "D1.21 amendment is stale")
    require(_read_json(INVENTORY_PATH) == inventory, "D1.21 inventory is stale")
    import trimem_freeze

    trimem_freeze.check_freeze(ROOT)
    return {
        "benchmark_image_pulls": 0,
        "classification": d121.AMENDMENT_CLASSIFICATION,
        "endpoint": d121.AMENDMENT_ENDPOINT,
        "grader_containers": 0,
        "model_generation_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "request_020_attempt_one_consumed": True,
        "request_020_rerun_allowed": False,
        "request_021_execution_authorized": False,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the credential-free D1.21 exec-021 recovery seal"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_all()
        result = check_all()
    except (D121ResealError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
