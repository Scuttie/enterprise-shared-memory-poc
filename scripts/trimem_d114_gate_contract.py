"""Offline fail-closed contract for the spent DEV ``_013`` workflow run.

The fixture is an allowlisted projection of public workflow/job metadata and
one normalized, non-secret environment observation.  This module performs no
network, process, Docker, credential, grader, or model action.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
from typing import Any, NoReturn


SCHEMA = "trimem/d114-exec-013-post-setup-failure/1.0"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_SOURCE_HEAD = "cb17ceae0fbc951dff34213de977a73b5405fefc"
EXPECTED_EXECUTION_HEAD = "35bfa338915d731dab499f2dfee08b38741bfe8d"
EXPECTED_RUN_ID = 34_138_918_074
EXPECTED_RUN_ATTEMPT = 1
EXPECTED_WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"

EXPECTED_FAILED_JOB = "bounded-context-preflight"
EXPECTED_FAILED_STEP = (
    "Re-observe exact self-hosted runner before any install or materialization"
)
EXPECTED_FAILURE_MESSAGE = (
    "runner LD_LIBRARY_PATH binding differs: bounded-context preflight process "
    "environment"
)
EXPECTED_FAILURE_CLASSIFICATION = (
    "POST_SETUP_PYTHON_DUAL_LD_LIBRARY_PATH_FAIL_CLOSED"
)
EXPECTED_FAILURE_SUBTYPE = "SETUP_PYTHON_POST_SETUP_LD_LIBRARY_PATH_SHAPE"
EXPECTED_LIBRARY_PATH = (
    "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib"
)
OBSERVED_LIBRARY_PATH = (
    "/opt/trimem-d112-runners/exec/_work/_tool/Python/3.11.10/x64/lib:"
    + EXPECTED_LIBRARY_PATH
)

EXPECTED_JOB_IDS = {
    "branch-trigger-preflight": 101_796_222_373,
    "bounded-context-preflight": 101_796_314_944,
    "frozen-serial-phase": 101_796_404_674,
}
EXPECTED_JOBS = (
    {
        "conclusion": "success",
        "id": EXPECTED_JOB_IDS["branch-trigger-preflight"],
        "name": "branch-trigger-preflight",
        "runner_boundary": "GITHUB_HOSTED",
        "steps": {"one_time_zero_authority_trigger": "success"},
    },
    {
        "conclusion": "failure",
        "id": EXPECTED_JOB_IDS["bounded-context-preflight"],
        "name": "bounded-context-preflight",
        "runner_boundary": "SELF_HOSTED_UNPROTECTED",
        "steps": {
            "checkout": "success",
            "post_setup_runner_reobservation": "failure",
            "pre_setup_cached_python": "success",
            "setup_python": "success",
        },
    },
    {
        "conclusion": "skipped",
        "id": EXPECTED_JOB_IDS["frozen-serial-phase"],
        "name": "frozen-serial-phase",
        "runner_boundary": "SELF_HOSTED_PROTECTED",
        "steps": {},
    },
)

EXPECTED_ZERO_COUNTERS: dict[str, int | float] = {
    "benchmark_image_pulls": 0,
    "dependency_installations": 0,
    "grader_containers": 0,
    "harness_materializations": 0,
    "input_tokens": 0,
    "model_api_calls": 0,
    "model_generation_calls": 0,
    "model_metadata_requests": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_usd": 0.0,
}
EXPECTED_BOUNDARY: dict[str, object] = {
    "bounded_context_preflight_entered": True,
    "branch_trigger_preflight_entered": True,
    "dependency_install_started": False,
    "failure_stage": (
        "BOUNDED_SELF_HOSTED_POST_SETUP_REOBSERVATION_BEFORE_INSTALL_OR_"
        "MATERIALIZATION"
    ),
    "frozen_serial_phase_entered": False,
    "harness_materialization_started": False,
    "post_setup_runner_reobservation_entered": True,
    "pre_setup_cache_host_passed": True,
    "protected_environment_approval_requested": False,
    "protected_environment_entered": False,
    "self_hosted_job_assignments": 1,
    "setup_python_passed": True,
}
EXPECTED_SANITIZATION: dict[str, object] = {
    "environment_projection": "TWO_ALLOWLISTED_LD_LIBRARY_PATH_VALUES_ONLY",
    "jobs_api": "ALLOWLISTED_FIELDS_ONLY",
    "raw_log_embedded": False,
    "run_api": "ALLOWLISTED_FIELDS_ONLY",
    "step_log": "NORMALIZED_SUMMARY_ONLY",
}
EXPECTED_STATIC_DIGESTS = {
    "d113_amendment_sha256": (
        "961539205cc4670ce11cf983ec89200498a3ebd31d47c6e7cf3e0d4403200d99"
    ),
    "d113_inventory_sha256": (
        "162649ed15af5a19c45bea1f3233f6280cae964e55e0c7fb63b8c4c09fe2ae74"
    ),
    "request_raw_sha256": (
        "a500568cedfa800bd85e20263b604fa2c1d24f634644d5ef14f517a8330b6417"
    ),
    "request_self_hash_sha256": (
        "132c7fc8a7ca166076882a53d3a69db56b4ccc5ab9e41ec1071a196f0618fe26"
    ),
    "source_freeze_sha256": (
        "ea74940aad297761c62c9f2555eb9aba3819e584082bf68951247e9a39d1f0c6"
    ),
    "trigger_reader_sha256": (
        "4e4de8fb39ae7ee67c890fa3db1573a5278aefd17f5e64bf61cadd0aea6b5fac"
    ),
    "workflow_file_sha256": (
        "7d7f26d015a378eb516cf2977f763ae867d7a53532ac78a79001033bb3ebabcc"
    ),
}
EXPECTED_PROJECTION_DIGESTS = {
    "evidence_bundle_sha256": (
        "a03af8f037ec5725c5e71e3264966c7169319bc8fdea3ca0888b2bd89f59b87b"
    ),
    "failed_log_summary_sha256": (
        "6c6b50de5c8a7037b7207f6ef2f3df421e3036f0e65e41d9ff5c16ce5f77d2c6"
    ),
    "jobs_projection_sha256": (
        "3deb85f023ffbc0801095bb09f41d7e4272e50404db3625b3e3d72b26a77db96"
    ),
    "workflow_run_projection_sha256": (
        "7d89a1b360dbeeea16aefed77beb96058444a11a2a6a422f209c5aead3aca41e"
    ),
}

ROOT_KEYS = {
    "actuals",
    "boundary",
    "branch",
    "digests",
    "execution_head",
    "failed_log_summary",
    "jobs",
    "repository",
    "sanitization",
    "schema",
    "source_head",
    "workflow_run",
}
RUN_KEYS = {
    "conclusion",
    "event",
    "head_branch",
    "head_sha",
    "id",
    "path",
    "run_attempt",
    "source_head_sha",
    "status",
}
FAILURE_KEYS = {
    "expected_ld_library_path",
    "failed_job",
    "failed_step",
    "failure_classification",
    "failure_message",
    "failure_subtype",
    "observed_ld_library_path",
    "process_exit_code",
    "raw_log_embedded",
    "sanitization",
}
DIGEST_KEYS = set(EXPECTED_STATIC_DIGESTS) | set(EXPECTED_PROJECTION_DIGESTS)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class D114GateContractError(ValueError):
    """The frozen D1.14 evidence projection differs."""


def _fail(message: str) -> NoReturn:
    raise D114GateContractError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} is not an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    _require(set(value) == expected, f"{label} field set differs")


def _typed_equal(observed: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return isinstance(observed, bool) and observed is expected
    if type(expected) is int:
        return type(observed) is int and observed == expected
    if type(expected) is float:
        return type(observed) in {int, float} and not isinstance(observed, bool) and observed == expected
    return type(observed) is type(expected) and observed == expected


def _exact_mapping(
    observed: Mapping[str, Any], expected: Mapping[str, Any], label: str
) -> None:
    _exact_keys(observed, set(expected), label)
    for key, expected_value in expected.items():
        _require(
            _typed_equal(observed.get(key), expected_value),
            f"{label}.{key} differs",
        )


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise D114GateContractError("evidence is not finite canonical JSON") from exc


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("evidence contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> NoReturn:
    _fail(f"evidence contains a non-finite JSON constant: {value}")


def strict_json_bytes(raw: bytes) -> dict[str, Any]:
    _require(not raw.startswith(b"\xef\xbb\xbf"), "evidence starts with UTF-8 BOM")
    _require(b"\x00" not in raw, "evidence contains NUL")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D114GateContractError("evidence is not strict UTF-8 JSON") from exc
    _require(isinstance(value, dict), "evidence root is not an object")
    return value


def load_fixture(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = strict_json_bytes(raw)
    expected = (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
        + b"\n"
    )
    _require(raw == expected, "fixture is not canonical pretty UTF-8 plus one LF")
    return value


def validate_fixture(value: Any) -> dict[str, Any]:
    document = _mapping(value, "fixture")
    _exact_keys(document, ROOT_KEYS, "fixture")
    _require(document.get("schema") == SCHEMA, "fixture schema differs")
    _require(document.get("repository") == EXPECTED_REPOSITORY, "repository differs")
    _require(document.get("branch") == EXPECTED_BRANCH, "branch differs")
    _require(document.get("source_head") == EXPECTED_SOURCE_HEAD, "source HEAD differs")
    _require(
        document.get("execution_head") == EXPECTED_EXECUTION_HEAD,
        "execution HEAD differs",
    )

    actuals = _mapping(document.get("actuals"), "actuals")
    _exact_mapping(actuals, EXPECTED_ZERO_COUNTERS, "actuals")
    boundary = _mapping(document.get("boundary"), "boundary")
    _exact_mapping(boundary, EXPECTED_BOUNDARY, "boundary")
    sanitization = _mapping(document.get("sanitization"), "sanitization")
    _exact_mapping(sanitization, EXPECTED_SANITIZATION, "sanitization")

    workflow = _mapping(document.get("workflow_run"), "workflow_run")
    _exact_keys(workflow, RUN_KEYS, "workflow_run")
    expected_workflow = {
        "conclusion": "failure",
        "event": "push",
        "head_branch": EXPECTED_BRANCH,
        "head_sha": EXPECTED_EXECUTION_HEAD,
        "id": EXPECTED_RUN_ID,
        "path": EXPECTED_WORKFLOW_PATH,
        "run_attempt": EXPECTED_RUN_ATTEMPT,
        "source_head_sha": EXPECTED_SOURCE_HEAD,
        "status": "completed",
    }
    _exact_mapping(workflow, expected_workflow, "workflow_run")

    jobs = document.get("jobs")
    _require(isinstance(jobs, list), "jobs is not an array")
    _require(len(jobs) == len(EXPECTED_JOBS), "job cardinality differs")
    for index, expected_job in enumerate(EXPECTED_JOBS):
        observed = _mapping(jobs[index], f"jobs[{index}]")
        _exact_keys(observed, set(expected_job), f"jobs[{index}]")
        for key in ("conclusion", "id", "name", "runner_boundary"):
            _require(
                _typed_equal(observed.get(key), expected_job[key]),
                f"jobs[{index}].{key} differs",
            )
        steps = _mapping(observed.get("steps"), f"jobs[{index}].steps")
        _exact_mapping(steps, expected_job["steps"], f"jobs[{index}].steps")

    failure = _mapping(document.get("failed_log_summary"), "failed_log_summary")
    _exact_keys(failure, FAILURE_KEYS, "failed_log_summary")
    expected_failure = {
        "expected_ld_library_path": EXPECTED_LIBRARY_PATH,
        "failed_job": EXPECTED_FAILED_JOB,
        "failed_step": EXPECTED_FAILED_STEP,
        "failure_classification": EXPECTED_FAILURE_CLASSIFICATION,
        "failure_message": EXPECTED_FAILURE_MESSAGE,
        "failure_subtype": EXPECTED_FAILURE_SUBTYPE,
        "observed_ld_library_path": OBSERVED_LIBRARY_PATH,
        "process_exit_code": 1,
        "raw_log_embedded": False,
        "sanitization": "ALLOWLISTED_NORMALIZED_SUMMARY_ONLY",
    }
    _exact_mapping(failure, expected_failure, "failed_log_summary")
    observed_parts = str(failure["observed_ld_library_path"]).split(":")
    _require(
        observed_parts
        == [
            "/opt/trimem-d112-runners/exec/_work/_tool/Python/3.11.10/x64/lib",
            EXPECTED_LIBRARY_PATH,
        ],
        "observed LD_LIBRARY_PATH is not the exact setup-python prepend",
    )

    digests = _mapping(document.get("digests"), "digests")
    _exact_keys(digests, DIGEST_KEYS, "digests")
    for key, expected_digest in EXPECTED_STATIC_DIGESTS.items():
        _require(digests.get(key) == expected_digest, f"static digest differs: {key}")
    projections = {
        "evidence_bundle_sha256": {
            key: item for key, item in document.items() if key != "digests"
        },
        "failed_log_summary_sha256": failure,
        "jobs_projection_sha256": jobs,
        "workflow_run_projection_sha256": workflow,
    }
    for key, projection in projections.items():
        observed = digests.get(key)
        _require(
            isinstance(observed, str)
            and HEX64.fullmatch(observed) is not None
            and observed == EXPECTED_PROJECTION_DIGESTS[key]
            and observed == _canonical_sha256(projection),
            f"projection digest differs: {key}",
        )

    return {
        "benchmark_image_pulls": 0,
        "dependency_installations": 0,
        "execution_head": EXPECTED_EXECUTION_HEAD,
        "execution_run_attempt": EXPECTED_RUN_ATTEMPT,
        "execution_run_id": EXPECTED_RUN_ID,
        "grader_containers": 0,
        "harness_materializations": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "protected_environment_entered": False,
        "self_hosted_job_assignments": 1,
        "source_head": EXPECTED_SOURCE_HEAD,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the offline D1.14 exec-013 failure projection"
    )
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_fixture(load_fixture(args.fixture))
    except (D114GateContractError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
