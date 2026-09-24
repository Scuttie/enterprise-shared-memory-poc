"""Credential-free D1.13 closure for the ``_012`` pre-protected failure.

The fixture consumed by this module is a deliberately small, allowlisted
projection of the GitHub workflow-run API, jobs API, and failed-step log.  It
contains no raw log, environment block, credential, or authorization header.
The validator is offline and fail closed: exact identities and stage
boundaries are checked directly while SHA-256 digests freeze every remaining
allowlisted metadata value.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, NoReturn


SCHEMA = "trimem/d113-exec-012-preprotected-failure/1.0"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_SOURCE_HEAD = "9db94e2a4abfaad0bb27079738b77836d68fa2e4"
EXPECTED_EXECUTION_HEAD = "491d1022fe079d182d7b453c48083c486936dcb2"
EXPECTED_RUN_ID = 34_128_541_859
EXPECTED_EXECUTION_RUN_ID = EXPECTED_RUN_ID
EXPECTED_RUN_ATTEMPT = 1
EXPECTED_RUN_NUMBER = 12
EXPECTED_WORKFLOW_ID = 349_104_146
EXPECTED_WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"
EXPECTED_RUN_URL = (
    "https://github.com/Scuttie/enterprise-shared-memory-poc/"
    "actions/runs/34128541859"
)
EXPECTED_FAILED_JOB = "branch-trigger-preflight"
EXPECTED_FAILED_STEP = "Verify one-time zero-authority DEV trigger"
EXPECTED_FAILED_STEP_NUMBER = 6
EXPECTED_FAILURE_MESSAGE = (
    "runner readiness command failed: GitHub repository runners"
)
EXPECTED_FAILURE_CLASSIFICATION = (
    "HOSTED_GITHUB_TOKEN_REPOSITORY_RUNNER_LIST_COMMAND_FAILURE"
)
EXPECTED_FAILURE_SUBTYPE = "HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION"

EXPECTED_JOB_IDS = {
    "branch-trigger-preflight": 101_762_848_605,
    "bounded-context-preflight": 101_762_966_076,
    "frozen-serial-phase": 101_762_966_474,
}
EXPECTED_JOB_CONCLUSIONS = {
    "branch-trigger-preflight": "failure",
    "bounded-context-preflight": "skipped",
    "frozen-serial-phase": "skipped",
}
EXPECTED_BRANCH_STEPS = (
    (1, "Set up job", "success"),
    (2, "Checkout exact trigger commit", "success"),
    (3, "Set up exact Python", "success"),
    (4, "Install pinned GitHub CLI for branch gate", "success"),
    (5, "Verify pinned GitHub CLI for branch gate", "success"),
    (6, EXPECTED_FAILED_STEP, "failure"),
    (11, "Post Set up exact Python", "skipped"),
    (12, "Post Checkout exact trigger commit", "success"),
    (13, "Complete job", "success"),
)
SELF_HOSTED_LABELS = (
    "self-hosted",
    "linux",
    "x64",
    "trimem-ubuntu-24.04",
    "trimem-benchmark",
)

EXPECTED_ZERO_COUNTERS: dict[str, int | float] = {
    "benchmark_image_pulls": 0,
    "grader_containers": 0,
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
    "bounded_context_preflight_entered": False,
    "branch_trigger_preflight_entered": True,
    "failure_stage": (
        "HOSTED_BRANCH_TRIGGER_BEFORE_SELF_HOSTED_OR_PROTECTED_EXECUTION"
    ),
    "frozen_serial_phase_entered": False,
    "protected_environment_approval_requested": False,
    "protected_environment_entered": False,
    "self_hosted_job_assignments": 0,
}
EXPECTED_SANITIZATION: dict[str, object] = {
    "jobs_api": "ALLOWLISTED_FIELDS_ONLY",
    "raw_log_embedded": False,
    "run_api": "ALLOWLISTED_FIELDS_ONLY",
    "step_log": "NORMALIZED_SUMMARY_ONLY",
}
EXPECTED_STATIC_DIGESTS = {
    "request_raw_sha256": (
        "6691a24bf488a79b4e1843a129d3d8773090fe2654828534c35eeecc22cc9d38"
    ),
    "request_self_hash_sha256": (
        "efa99c554fbae9bbeb8a87536365fcfc6afa54e6ee48de17ef9ffdb0eb72132b"
    ),
    "source_freeze_sha256": (
        "3bbafc53504b45c20996094d96a6abfa5fd9e90c5b078eb2f1dc3f1f6d7ad5b4"
    ),
    "trigger_reader_sha256": (
        "34bd85b208e3b466fec719dbed0805939fbdd7387cb57385b78c4774a8abe593"
    ),
    "workflow_file_sha256": (
        "c077b9f3d0e325e8fac687d34a78cbb648901e0ca8ba2d43fa3f9455ac49c61f"
    ),
}

# Filled from canonical JSON projections of the allowlisted fixture.  Literal
# tests independently pin these values so changing a fixture field cannot be
# hidden by merely updating the fixture's own digest map.
EXPECTED_PROJECTION_DIGESTS = {
    "evidence_bundle_sha256": (
        "3e7d5281ca8d67d54c979e2ae8aac1b6ca60c74d9e2d7a8052ee657050f4ec76"
    ),
    "failed_log_summary_sha256": (
        "a081239244e02910f214c17551f1fab023694f94c40de00d848f2ecd596cdc2c"
    ),
    "jobs_projection_sha256": (
        "4b8f1421ed2a0d31f25d3a6f56a4b3396efbca030094edb2c1357d1e08ac397d"
    ),
    "workflow_run_projection_sha256": (
        "c8d9de3c70db99ae95ab13e5ed9933f5fdabf9712bb3775cfc12098fedb0fc13"
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
    "created_at",
    "display_title",
    "event",
    "head_branch",
    "head_sha",
    "html_url",
    "id",
    "path",
    "run_attempt",
    "run_number",
    "run_started_at",
    "status",
    "updated_at",
    "workflow_id",
}
JOB_KEYS = {
    "completed_at",
    "conclusion",
    "html_url",
    "id",
    "labels",
    "name",
    "run_attempt",
    "run_id",
    "runner_group_id",
    "runner_group_name",
    "runner_id",
    "runner_name",
    "started_at",
    "status",
    "steps",
}
STEP_KEYS = {
    "completed_at",
    "conclusion",
    "name",
    "number",
    "started_at",
    "status",
}
LOG_SUMMARY_KEYS = {
    "failure_classification",
    "failure_message",
    "failed_job",
    "failed_step",
    "failed_step_number",
    "freeze_check",
    "process_exit_code",
    "raw_log_embedded",
    "sanitization",
}
DIGEST_KEYS = set(EXPECTED_STATIC_DIGESTS) | set(EXPECTED_PROJECTION_DIGESTS)

_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_UTC_SECONDS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")


class D113GateContractError(ValueError):
    """The frozen D1.13 failure evidence differs from its strict contract."""


def _fail(message: str) -> NoReturn:
    raise D113GateContractError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} is not an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    _require(set(value) == expected, f"{label} field set differs")


def _strict_equal(observed: Any, expected: Any, label: str) -> None:
    _require(type(observed) is type(expected), f"{label} type differs")
    if isinstance(expected, dict):
        _exact_keys(observed, set(expected), label)
        for key, expected_value in expected.items():
            _strict_equal(observed[key], expected_value, f"{label}.{key}")
    elif isinstance(expected, list):
        _require(len(observed) == len(expected), f"{label} length differs")
        for index, expected_value in enumerate(expected):
            _strict_equal(observed[index], expected_value, f"{label}[{index}]")
    else:
        _require(observed == expected, f"{label} differs")


def _reject_constant(value: str) -> NoReturn:
    _fail(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON key is forbidden: {key}")
        result[key] = value
    return result


def strict_json(raw: bytes) -> Any:
    """Decode strict UTF-8 JSON while rejecting BOMs, duplicates, and NaN."""

    _require(not raw.startswith(b"\xef\xbb\xbf"), "UTF-8 BOM is forbidden")
    _require(b"\x00" not in raw, "NUL is forbidden")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise D113GateContractError("fixture is not strict UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except D113GateContractError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise D113GateContractError("fixture is not strict JSON") from exc


def canonical_sha256(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise D113GateContractError("evidence is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _timestamp(value: Any, label: str) -> None:
    _require(
        isinstance(value, str) and _UTC_SECONDS.fullmatch(value) is not None,
        f"{label} is not exact UTC-second metadata",
    )


def _validate_workflow_run(value: Any) -> dict[str, Any]:
    run = _mapping(value, "workflow_run")
    _exact_keys(run, RUN_KEYS, "workflow_run")
    _require(
        type(run.get("id")) is int
        and run.get("id") == EXPECTED_RUN_ID
        and type(run.get("run_attempt")) is int
        and run.get("run_attempt") == EXPECTED_RUN_ATTEMPT
        and type(run.get("run_number")) is int
        and run.get("run_number") == EXPECTED_RUN_NUMBER
        and type(run.get("workflow_id")) is int
        and run.get("workflow_id") == EXPECTED_WORKFLOW_ID
        and run.get("event") == "push"
        and run.get("path") == EXPECTED_WORKFLOW_PATH
        and run.get("head_branch") == EXPECTED_BRANCH
        and run.get("head_sha") == EXPECTED_EXECUTION_HEAD
        and run.get("status") == "completed"
        and run.get("conclusion") == "failure"
        and run.get("html_url") == EXPECTED_RUN_URL,
        "workflow run identity or terminal state differs",
    )
    for name in ("created_at", "run_started_at", "updated_at"):
        _timestamp(run.get(name), f"workflow_run.{name}")
    _require(
        run.get("display_title")
        == "chore(trimem): add zero-authority exec 012 request",
        "workflow run display title differs",
    )
    return dict(run)


def _validate_branch_steps(value: Any) -> list[dict[str, Any]]:
    _require(isinstance(value, list), "branch job steps is not a list")
    _require(
        len(value) == len(EXPECTED_BRANCH_STEPS),
        "branch job step count differs",
    )
    result: list[dict[str, Any]] = []
    for index, (item, expected) in enumerate(zip(value, EXPECTED_BRANCH_STEPS)):
        step = _mapping(item, f"branch job step {index}")
        _exact_keys(step, STEP_KEYS, f"branch job step {index}")
        number, name, conclusion = expected
        _require(
            type(step.get("number")) is int
            and step.get("number") == number
            and step.get("name") == name
            and step.get("status") == "completed"
            and step.get("conclusion") == conclusion,
            f"branch job step {index} identity or outcome differs",
        )
        _timestamp(step.get("started_at"), f"branch job step {index}.started_at")
        _timestamp(
            step.get("completed_at"),
            f"branch job step {index}.completed_at",
        )
        result.append(dict(step))
    return result


def _canonical_job_url(job_id: int) -> str:
    return f"{EXPECTED_RUN_URL}/job/{job_id}"


def _validate_jobs(value: Any) -> list[dict[str, Any]]:
    _require(isinstance(value, list), "jobs is not a list")
    expected_names = tuple(EXPECTED_JOB_IDS)
    _require(
        len(value) == 3
        and tuple(
            item.get("name") if isinstance(item, Mapping) else None
            for item in value
        )
        == expected_names,
        "job order or cardinality differs",
    )
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        job = _mapping(item, f"job {index}")
        _exact_keys(job, JOB_KEYS, f"job {index}")
        name = job.get("name")
        _require(
            isinstance(name, str) and name in EXPECTED_JOB_IDS,
            f"job {index} name differs",
        )
        expected_id = EXPECTED_JOB_IDS[name]
        _require(
            type(job.get("id")) is int
            and job.get("id") == expected_id
            and type(job.get("run_id")) is int
            and job.get("run_id") == EXPECTED_RUN_ID
            and type(job.get("run_attempt")) is int
            and job.get("run_attempt") == EXPECTED_RUN_ATTEMPT
            and job.get("status") == "completed"
            and job.get("conclusion") == EXPECTED_JOB_CONCLUSIONS[name]
            and job.get("html_url") == _canonical_job_url(expected_id),
            f"job identity or outcome differs: {name}",
        )
        _timestamp(job.get("started_at"), f"job {name}.started_at")
        _timestamp(job.get("completed_at"), f"job {name}.completed_at")
        if name == EXPECTED_FAILED_JOB:
            _strict_equal(job.get("labels"), ["ubuntu-24.04"], "hosted labels")
            _require(
                type(job.get("runner_id")) is int
                and job["runner_id"] > 0
                and job.get("runner_name") == "GitHub Actions 1000012125"
                and job.get("runner_group_id") == 0
                and type(job.get("runner_group_id")) is int
                and job.get("runner_group_name") == "GitHub Actions",
                "hosted branch runner identity differs",
            )
            _validate_branch_steps(job.get("steps"))
        else:
            _strict_equal(
                job.get("labels"), list(SELF_HOSTED_LABELS), f"job {name} labels"
            )
            _require(
                job.get("runner_id") is None
                and job.get("runner_name") is None
                and job.get("runner_group_id") is None
                and job.get("runner_group_name") is None
                and job.get("steps") == [],
                f"skipped self-hosted job was assigned or entered: {name}",
            )
        result.append(dict(job))
    return result


def _validate_failed_log_summary(value: Any) -> dict[str, Any]:
    summary = _mapping(value, "failed_log_summary")
    _exact_keys(summary, LOG_SUMMARY_KEYS, "failed_log_summary")
    expected = {
        "failure_classification": EXPECTED_FAILURE_CLASSIFICATION,
        "failure_message": EXPECTED_FAILURE_MESSAGE,
        "failed_job": EXPECTED_FAILED_JOB,
        "failed_step": EXPECTED_FAILED_STEP,
        "failed_step_number": EXPECTED_FAILED_STEP_NUMBER,
        "freeze_check": {"files": 436, "status": "PASS"},
        "process_exit_code": 1,
        "raw_log_embedded": False,
        "sanitization": "ALLOWLISTED_NORMALIZED_SUMMARY_ONLY",
    }
    _strict_equal(dict(summary), expected, "failed_log_summary")
    return dict(summary)


def _validate_zero_counters(value: Any) -> dict[str, int | float]:
    counters = _mapping(value, "actuals")
    _exact_keys(counters, set(EXPECTED_ZERO_COUNTERS), "actuals")
    for name, expected in EXPECTED_ZERO_COUNTERS.items():
        observed = counters.get(name)
        expected_type = float if name == "total_usd" else int
        _require(
            type(observed) is expected_type and observed == expected,
            f"zero counter differs: {name}",
        )
    return dict(EXPECTED_ZERO_COUNTERS)


def _validate_digests(
    document: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
    jobs: list[dict[str, Any]],
    summary: Mapping[str, Any],
) -> dict[str, str]:
    digests = _mapping(document.get("digests"), "digests")
    _exact_keys(digests, DIGEST_KEYS, "digests")
    for name, value in digests.items():
        _require(
            isinstance(value, str) and _HEX64.fullmatch(value) is not None,
            f"digest is malformed: {name}",
        )
    for name, expected in EXPECTED_STATIC_DIGESTS.items():
        _require(digests.get(name) == expected, f"static digest differs: {name}")

    bundle = {key: document[key] for key in sorted(ROOT_KEYS - {"digests"})}
    observed_projections = {
        "evidence_bundle_sha256": canonical_sha256(bundle),
        "failed_log_summary_sha256": canonical_sha256(summary),
        "jobs_projection_sha256": canonical_sha256(jobs),
        "workflow_run_projection_sha256": canonical_sha256(run),
    }
    for name, expected in EXPECTED_PROJECTION_DIGESTS.items():
        _require(
            digests.get(name) == expected
            and observed_projections[name] == expected,
            f"canonical projection digest differs: {name}",
        )
    return {name: str(digests[name]) for name in sorted(digests)}


def validate_fixture(value: Any) -> dict[str, Any]:
    """Validate the exact, sanitized terminal evidence for run 34128541859."""

    document = _mapping(value, "fixture")
    _exact_keys(document, ROOT_KEYS, "fixture")
    _require(document.get("schema") == SCHEMA, "fixture schema differs")
    _require(
        document.get("repository") == EXPECTED_REPOSITORY
        and document.get("branch") == EXPECTED_BRANCH
        and document.get("source_head") == EXPECTED_SOURCE_HEAD
        and document.get("execution_head") == EXPECTED_EXECUTION_HEAD,
        "fixture repository, branch, or head identity differs",
    )
    _require(
        _HEX40.fullmatch(str(document.get("source_head"))) is not None
        and _HEX40.fullmatch(str(document.get("execution_head"))) is not None,
        "fixture head is malformed",
    )
    _strict_equal(
        document.get("sanitization"),
        EXPECTED_SANITIZATION,
        "sanitization",
    )
    _strict_equal(document.get("boundary"), EXPECTED_BOUNDARY, "boundary")
    actuals = _validate_zero_counters(document.get("actuals"))
    run = _validate_workflow_run(document.get("workflow_run"))
    jobs = _validate_jobs(document.get("jobs"))
    summary = _validate_failed_log_summary(document.get("failed_log_summary"))
    digests = _validate_digests(
        document,
        run=run,
        jobs=jobs,
        summary=summary,
    )
    return {
        "benchmark_image_pulls": actuals["benchmark_image_pulls"],
        "evidence_bundle_sha256": digests["evidence_bundle_sha256"],
        "execution_head": EXPECTED_EXECUTION_HEAD,
        "execution_run_attempt": EXPECTED_RUN_ATTEMPT,
        "execution_run_id": EXPECTED_RUN_ID,
        "failed_job": EXPECTED_FAILED_JOB,
        "failed_step": EXPECTED_FAILED_STEP,
        "grader_containers": actuals["grader_containers"],
        "model_api_calls": actuals["model_api_calls"],
        "official_grader_runs": actuals["official_grader_runs"],
        "paid_model_calls": actuals["paid_model_calls"],
        "protected_environment_entered": False,
        "self_hosted_job_assignments": 0,
        "source_head": EXPECTED_SOURCE_HEAD,
        "status": "PASS",
        "task_arm_runs": actuals["task_arm_runs"],
        "total_usd": actuals["total_usd"],
    }


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise D113GateContractError(f"cannot read D1.13 fixture: {path}") from exc
    return dict(_mapping(strict_json(raw), "fixture"))


def validate_replay(value: Any) -> dict[str, Any]:
    """Compatibility entry point for reseal and trigger contracts."""

    return validate_fixture(value)


def load_replay(path: Path) -> dict[str, Any]:
    """Compatibility loader for reseal and trigger contracts."""

    return load_fixture(path)


def _default_fixture() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "trimem_d113"
        / "exec_012_preprotected_failure.json"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the sanitized D1.13 pre-protected failure closure"
    )
    parser.add_argument("--fixture", type=Path, default=_default_fixture())
    args = parser.parse_args(argv)
    try:
        result = validate_fixture(load_fixture(args.fixture))
    except D113GateContractError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
