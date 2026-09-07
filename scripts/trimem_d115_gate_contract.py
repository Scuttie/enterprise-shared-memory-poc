"""Offline fail-closed contract for the spent DEV ``_014`` workflow run.

The fixture contains only an allowlisted projection of public Actions metadata
and a credential-free exact-interpreter diagnostic.  Validation performs no
network, Docker, image, grader, credential, or model action.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
from typing import Any, NoReturn


SCHEMA = "trimem/d115-exec-014-loader-failure/1.0"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_SOURCE_HEAD = "6e9abe999f2b9d7ebdd3eea23dbbea8f6afad931"
EXPECTED_EXECUTION_HEAD = "31234fdd58fd43170764524662c9e51687521761"
EXPECTED_RUN_ID = 34_147_189_320
EXPECTED_RUN_ATTEMPT = 1
EXPECTED_WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"

EXPECTED_FAILED_JOB = "bounded-context-preflight"
EXPECTED_FAILED_STEP = "Gate protected job on unprotected exact loader preflight"
EXPECTED_FAILURE_MESSAGE = "credential-free official-harness loader preflight failed"
EXPECTED_FAILURE_CLASSIFICATION = (
    "CACHED_PYTHON_SYSCONFIG_LIBDIR_RELOCATION_FAIL_CLOSED"
)
EXPECTED_FAILURE_SUBTYPE = "CACHED_PYTHON_SYSCONFIG_LIBDIR_ALIAS_ABSENT"
EXPECTED_REMOTE_MARKER = "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_NOT_READY"
EXPECTED_PYTHON_REAL_PREFIX = (
    "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64"
)
EXPECTED_SYSCONFIG_LIBDIR = "/opt/hostedtoolcache/Python/3.11.10/x64/lib"
EXPECTED_LOADER_ERROR_CHAIN = [
    "candidate libdir does not exist",
    "loader probe LIBDIR is not a trusted Python library directory",
    "exact Python loader is not ready",
    EXPECTED_FAILURE_MESSAGE,
]

EXPECTED_JOB_IDS = {
    "branch-trigger-preflight": 101_821_655_367,
    "bounded-context-preflight": 101_821_724_190,
    "frozen-serial-phase": 101_821_923_240,
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
            "bounded_context_roundtrip": "success",
            "checkout": "success",
            "hash_locked_install": "success",
            "official_harness_loader_preflight": "failure",
            "pinned_harness_materialization": "success",
            "post_setup_runner_reobservation": "success",
            "pre_setup_cached_python": "success",
            "setup_python": "success",
            "terminal_cell_roundtrip": "success",
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

EXPECTED_ACTUALS: dict[str, int | float] = {
    "benchmark_image_pulls": 0,
    "dependency_installations": 1,
    "grader_containers": 0,
    "harness_materializations": 2,
    "input_tokens": 0,
    "model_api_calls": 0,
    "model_generation_calls": 0,
    "model_metadata_requests": 0,
    "official_grader_runs": 0,
    "official_harness_loader_preflight_attempts": 1,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_usd": 0.0,
}
EXPECTED_ZERO_SCIENTIFIC_COUNTERS = (
    "benchmark_image_pulls",
    "grader_containers",
    "input_tokens",
    "model_api_calls",
    "model_generation_calls",
    "model_metadata_requests",
    "official_grader_runs",
    "output_tokens",
    "paid_model_calls",
    "task_arm_runs",
    "terminal_cells",
    "total_usd",
)
EXPECTED_BOUNDARY: dict[str, object] = {
    "bounded_context_preflight_entered": True,
    "branch_trigger_preflight_entered": True,
    "dependency_install_completed": True,
    "failure_stage": "BOUNDED_SELF_HOSTED_EXACT_OFFICIAL_HARNESS_LOADER_PREFLIGHT",
    "frozen_serial_phase_entered": False,
    "harness_materialization_completed": True,
    "official_harness_loader_preflight_entered": True,
    "protected_environment_approval_requested": False,
    "protected_environment_entered": False,
    "self_hosted_job_assignments": 1,
    "setup_python_passed": True,
}
EXPECTED_SANITIZATION: dict[str, object] = {
    "diagnostic_source": (
        "PUBLIC_RUN_METADATA_PLUS_CREDENTIAL_FREE_EXACT_INTERPRETER_REHEARSAL"
    ),
    "environment_projection": (
        "ALLOWLISTED_PYTHON_PREFIX_AND_SYSCONFIG_LIBDIR_ONLY"
    ),
    "jobs_api": "ALLOWLISTED_FIELDS_ONLY",
    "raw_log_embedded": False,
    "run_api": "ALLOWLISTED_FIELDS_ONLY",
    "step_log": "ALLOWLISTED_NORMALIZED_SUMMARY_ONLY",
}
EXPECTED_STATIC_DIGESTS = {
    "d114_amendment_sha256": (
        "fbe9e8193b79cdcef1d53be802ac493d9fc051046c20063c5ad10f5c053d0c1f"
    ),
    "d114_gate_contract_sha256": (
        "2bd9aceb9db0e571cb194565473a0da19b5e2001913b236d7d0af9570da6e52b"
    ),
    "d114_inventory_sha256": (
        "d7ee03df98ab73dc427b0d12b94052331a854241fcaabae358a99beb4a6e3a14"
    ),
    "d114_reseal_sha256": (
        "9a10ffb0b2f91d842ff3579b4e06608109e320bd691db07bf98c361c8e8e3cdf"
    ),
    "loader_preflight_sha256": (
        "3517f0b841be71c2dea472f3df26c1133e3ddbca6dbaf580551bbbacdc6c2b02"
    ),
    "loader_sha256": (
        "b988a2afe1740d1c9767736dae72daf96238d2b306786a6b765b6f423411f20d"
    ),
    "request_raw_sha256": (
        "7b4ff50e423cd12baea93413bbedcf7c2ee210d031fc20b30ad1c9d9f3c2dbaa"
    ),
    "request_self_hash_sha256": (
        "e046c09ac2a40a4f5a819e8dc522074d20157ddd6201233de8c49e209451d353"
    ),
    "source_freeze_sha256": (
        "19da74e3e4d217354c7b2483bf1a462da10867ebe62c995df72405f273847448"
    ),
    "trigger_reader_sha256": (
        "94da6bdcca105ea27e031eb240ebe4c333b25998b5e4bc5b35ecfb674dc734ac"
    ),
    "workflow_file_sha256": (
        "901aba968d9965430710b157a93b9cdbc874637a2ceca3f65ffc1a87d044854a"
    ),
}
EXPECTED_PROJECTION_DIGESTS = {
    "evidence_bundle_sha256": (
        "6a3d6a2e76ecf5452e1740bb015a72366a41ad46ce1dcc3d62bf8509fe8bc5ef"
    ),
    "failed_log_summary_sha256": (
        "64a98513315779e22ed2d5e6683f9498011c50c65703d5fa3b2bca27733d7190"
    ),
    "jobs_projection_sha256": (
        "ee986db606fc17c4754d23363201433bfcb9b5ba929811126fe4d21ad417a100"
    ),
    "workflow_run_projection_sha256": (
        "ca1d815615cf6a8010bfd0e5ffed6d2f78472e97193f4b77ddce65e346dbc245"
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
    "failed_job",
    "failed_step",
    "failure_classification",
    "failure_message",
    "failure_subtype",
    "loader_error_chain",
    "observed_python_real_prefix",
    "observed_sysconfig_libdir",
    "observed_sysconfig_libdir_exists",
    "process_exit_code",
    "raw_log_embedded",
    "remote_marker",
    "sanitization",
}
DIGEST_KEYS = set(EXPECTED_STATIC_DIGESTS) | set(EXPECTED_PROJECTION_DIGESTS)
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class D115GateContractError(ValueError):
    """The frozen D1.15 evidence projection differs."""


def _fail(message: str) -> NoReturn:
    raise D115GateContractError(message)


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
        return (
            type(observed) in {int, float}
            and not isinstance(observed, bool)
            and observed == expected
        )
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
        raise D115GateContractError("evidence is not finite canonical JSON") from exc


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
        raise D115GateContractError("evidence is not strict UTF-8 JSON") from exc
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
    _exact_mapping(actuals, EXPECTED_ACTUALS, "actuals")
    for name in EXPECTED_ZERO_SCIENTIFIC_COUNTERS:
        _require(actuals[name] == 0, f"scientific counter is nonzero: {name}")
    boundary = _mapping(document.get("boundary"), "boundary")
    _exact_mapping(boundary, EXPECTED_BOUNDARY, "boundary")
    sanitization = _mapping(document.get("sanitization"), "sanitization")
    _exact_mapping(sanitization, EXPECTED_SANITIZATION, "sanitization")

    workflow = _mapping(document.get("workflow_run"), "workflow_run")
    _exact_keys(workflow, RUN_KEYS, "workflow_run")
    _exact_mapping(
        workflow,
        {
            "conclusion": "failure",
            "event": "push",
            "head_branch": EXPECTED_BRANCH,
            "head_sha": EXPECTED_EXECUTION_HEAD,
            "id": EXPECTED_RUN_ID,
            "path": EXPECTED_WORKFLOW_PATH,
            "run_attempt": EXPECTED_RUN_ATTEMPT,
            "source_head_sha": EXPECTED_SOURCE_HEAD,
            "status": "completed",
        },
        "workflow_run",
    )

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
        _exact_mapping(
            _mapping(observed.get("steps"), f"jobs[{index}].steps"),
            expected_job["steps"],
            f"jobs[{index}].steps",
        )

    failure = _mapping(document.get("failed_log_summary"), "failed_log_summary")
    _exact_keys(failure, FAILURE_KEYS, "failed_log_summary")
    _exact_mapping(
        failure,
        {
            "failed_job": EXPECTED_FAILED_JOB,
            "failed_step": EXPECTED_FAILED_STEP,
            "failure_classification": EXPECTED_FAILURE_CLASSIFICATION,
            "failure_message": EXPECTED_FAILURE_MESSAGE,
            "failure_subtype": EXPECTED_FAILURE_SUBTYPE,
            "loader_error_chain": EXPECTED_LOADER_ERROR_CHAIN,
            "observed_python_real_prefix": EXPECTED_PYTHON_REAL_PREFIX,
            "observed_sysconfig_libdir": EXPECTED_SYSCONFIG_LIBDIR,
            "observed_sysconfig_libdir_exists": False,
            "process_exit_code": 1,
            "raw_log_embedded": False,
            "remote_marker": EXPECTED_REMOTE_MARKER,
            "sanitization": "ALLOWLISTED_NORMALIZED_SUMMARY_ONLY",
        },
        "failed_log_summary",
    )
    _require(
        not str(failure["observed_sysconfig_libdir"]).startswith(
            str(failure["observed_python_real_prefix"]) + "/"
        ),
        "failed sysconfig LIBDIR unexpectedly lies below the real prefix",
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
        "dependency_installations": 1,
        "execution_head": EXPECTED_EXECUTION_HEAD,
        "execution_run_attempt": EXPECTED_RUN_ATTEMPT,
        "execution_run_id": EXPECTED_RUN_ID,
        "grader_containers": 0,
        "harness_materializations": 2,
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
        description="Validate the offline D1.15 exec-014 failure projection"
    )
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_fixture(load_fixture(args.fixture))
    except (D115GateContractError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
