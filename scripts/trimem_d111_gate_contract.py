"""Credential-free D1.11 replay of the failed ``_011`` GitHub gate.

The GitHub Actions API exposes ``workflow_run.pull_requests`` as mutable
relationship metadata.  In particular, the nested pull-request head for an
old run advances when the live pull request advances.  This module therefore
never reads that field while selecting historical source-gate runs.  The live
pull request is validated separately against the expected execution head.

This is a source-only regression contract.  It does not call GitHub, inspect
credentials, create an execution request, or start a workflow.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
import re
import sys
from typing import Any, NoReturn


SCHEMA = "trimem/d111-exec-011-branch-transition-replay/1.0"
EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_BASE_BRANCH = "main"
EXPECTED_BASE_HEAD = "ce10ab49586db7a859fbe5cca93051b93f9f5b55"
EXPECTED_PULL_REQUEST = 18
EXPECTED_PULL_REQUEST_URL = (
    "https://github.com/Scuttie/enterprise-shared-memory-poc/pull/18"
)
EXPECTED_SOURCE_HEAD = "155fe314631ef74828ea98b562036bdb0adca495"
EXPECTED_EXECUTION_HEAD = "e54d04b0af9e738d311c389dc89cfd510fd7065b"
EXPECTED_EXECUTION_RUN_ID = 34_047_573_548
EXPECTED_WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"
EXPECTED_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/"
    "DEVELOPMENT_TUNING_EXEC_REQUEST_011.json"
)
EXPECTED_FAILURE_MESSAGE = (
    "exactly one exact-head event run is required: "
    ".github/workflows/ci.yml:pull_request"
)

# These IDs and top-level identities were frozen in the _011 request before
# its sentinel-only child was pushed.  The order is part of the replay.
REQUIRED_SOURCE_GATES: tuple[tuple[int, str, str], ...] = (
    (34_046_493_129, ".github/workflows/ci-trimem.yml", "push"),
    (
        34_046_493_102,
        ".github/workflows/ci-trimem-grader-loader.yml",
        "push",
    ),
    (
        34_046_493_066,
        ".github/workflows/ci-trimem-harness-lock.yml",
        "push",
    ),
    (
        34_046_493_075,
        ".github/workflows/ci-trimem-multi-swe-contract.yml",
        "push",
    ),
    (34_046_493_064, ".github/workflows/ci-trimem-e2e.yml", "push"),
    (
        34_046_493_119,
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        "push",
    ),
    (34_046_495_419, ".github/workflows/ci.yml", "pull_request"),
    (34_046_495_420, ".github/workflows/codeql.yml", "pull_request"),
    (34_046_495_429, ".github/workflows/ci-docs.yml", "pull_request"),
    (
        34_046_495_417,
        ".github/workflows/ci-company-package.yml",
        "pull_request",
    ),
    (
        34_046_495_426,
        ".github/workflows/ci-company-harness.yml",
        "pull_request",
    ),
    (
        34_046_495_396,
        ".github/workflows/ci-company-demo.yml",
        "pull_request",
    ),
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

_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_RUN_REQUIRED_KEYS = frozenset(
    {
        "conclusion",
        "event",
        "head_branch",
        "head_sha",
        "html_url",
        "id",
        "path",
        "run_attempt",
        "status",
    }
)
_RUN_IGNORED_KEYS = frozenset({"pull_requests"})


class D111GateContractError(ValueError):
    """The frozen D1.11 gate replay differs from its strict contract."""


def _fail(message: str) -> NoReturn:
    raise D111GateContractError(message)


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), f"{label} is not an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    _require(set(value) == expected, f"{label} field set differs")


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
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise D111GateContractError("fixture is not strict UTF-8") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except D111GateContractError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise D111GateContractError("fixture is not strict JSON") from exc


def _validate_expected_gate_manifest(value: Any) -> None:
    _require(isinstance(value, list), "expected_source_gates is not a list")
    expected = [
        {"event": event, "run_id": run_id, "workflow_path": path}
        for run_id, path, event in REQUIRED_SOURCE_GATES
    ]
    _require(value == expected, "expected source-gate manifest differs")


def _validate_run_shape(run: Mapping[str, Any], index: int) -> None:
    keys = set(run)
    _require(
        _RUN_REQUIRED_KEYS <= keys,
        f"historical source run {index} is missing immutable fields",
    )
    _require(
        not keys - _RUN_REQUIRED_KEYS - _RUN_IGNORED_KEYS,
        f"historical source run {index} has unexpected fields",
    )


def _canonical_run_url(run_id: int) -> str:
    return (
        "https://github.com/Scuttie/enterprise-shared-memory-poc/"
        f"actions/runs/{run_id}"
    )


def select_source_gate_runs(
    value: Any, *, source_head: str
) -> list[dict[str, Any]]:
    """Select all historical gates using immutable top-level run identity.

    The optional ``pull_requests`` key is intentionally never read.  It may be
    absent or contain any JSON value without changing selection or validation.
    """

    _require(_HEX40.fullmatch(source_head) is not None, "source head is invalid")
    _require(isinstance(value, list), "historical_source_runs is not a list")
    _require(
        len(value) == len(REQUIRED_SOURCE_GATES),
        "historical source run count differs",
    )

    runs: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        run = _mapping(item, f"historical source run {index}")
        _validate_run_shape(run, index)
        runs.append(run)

    selected_indices: set[int] = set()
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    for expected_id, expected_path, expected_event in REQUIRED_SOURCE_GATES:
        matches = [
            (index, run)
            for index, run in enumerate(runs)
            if run.get("path") == expected_path
            and run.get("event") == expected_event
            and run.get("head_sha") == source_head
        ]
        _require(
            len(matches) == 1,
            "exactly one immutable source gate is required: "
            f"{expected_path}:{expected_event}",
        )
        index, run = matches[0]
        run_id = run.get("id")
        _require(
            type(run_id) is int
            and run_id == expected_id
            and run.get("head_branch") == EXPECTED_BRANCH
            and type(run.get("run_attempt")) is int
            and run.get("run_attempt") == 1
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("html_url") == _canonical_run_url(expected_id),
            "immutable source-gate identity differs: "
            f"{expected_path}:{expected_event}",
        )
        _require(run_id not in selected_ids, "historical source run ID is duplicated")
        selected_ids.add(run_id)
        selected_indices.add(index)
        selected.append(
            {
                "conclusion": "success",
                "event": expected_event,
                "head_branch": EXPECTED_BRANCH,
                "head_sha": source_head,
                "html_url": _canonical_run_url(expected_id),
                "run_attempt": 1,
                "run_id": expected_id,
                "status": "completed",
                "workflow_path": expected_path,
            }
        )

    _require(
        selected_indices == set(range(len(runs))),
        "historical source runs contain an unselected record",
    )
    return selected


def validate_current_pull_request(value: Any, *, expected_head: str) -> dict[str, Any]:
    """Bind the live PR separately to the exact execution head."""

    _require(_HEX40.fullmatch(expected_head) is not None, "expected PR head is invalid")
    pull = _mapping(value, "current_pull_request")
    expected = {
        "base_ref": EXPECTED_BASE_BRANCH,
        "base_sha": EXPECTED_BASE_HEAD,
        "draft": True,
        "head_ref": EXPECTED_BRANCH,
        "head_repository": EXPECTED_REPOSITORY,
        "head_sha": expected_head,
        "html_url": EXPECTED_PULL_REQUEST_URL,
        "number": EXPECTED_PULL_REQUEST,
        "state": "open",
    }
    _exact_keys(pull, set(expected), "current_pull_request")
    _require(
        type(pull.get("number")) is int
        and pull.get("draft") is True
        and dict(pull) == expected,
        "current PR is not exact at execution head",
    )
    return expected


def validate_transition(value: Any) -> dict[str, Any]:
    """Require the exact one-parent, sentinel-only source-to-execution edge."""

    transition = _mapping(value, "transition")
    _exact_keys(
        transition,
        {"changed_files", "execution_head", "execution_parents", "source_head"},
        "transition",
    )
    _require(
        transition.get("source_head") == EXPECTED_SOURCE_HEAD
        and transition.get("execution_head") == EXPECTED_EXECUTION_HEAD,
        "source or execution head differs",
    )
    _require(
        transition.get("execution_parents") == [EXPECTED_SOURCE_HEAD],
        "execution commit is not the exact single-parent child of source",
    )
    expected_change = [
        {"mode": "100644", "path": EXPECTED_SENTINEL_PATH, "status": "A"}
    ]
    _require(
        transition.get("changed_files") == expected_change,
        "execution commit is not the sentinel-only regular-file addition",
    )
    return {
        "changed_files": expected_change,
        "execution_head": EXPECTED_EXECUTION_HEAD,
        "execution_parents": [EXPECTED_SOURCE_HEAD],
        "source_head": EXPECTED_SOURCE_HEAD,
    }


def _validate_zero_counters(value: Any) -> dict[str, int | float]:
    counters = _mapping(value, "failed_execution.actuals")
    _exact_keys(counters, set(EXPECTED_ZERO_COUNTERS), "failed_execution.actuals")
    for name, expected in EXPECTED_ZERO_COUNTERS.items():
        observed = counters.get(name)
        expected_type = float if name == "total_usd" else int
        _require(
            type(observed) is expected_type and observed == expected,
            f"zero-call failure counter differs: {name}",
        )
    return dict(EXPECTED_ZERO_COUNTERS)


def validate_failed_execution(value: Any, *, execution_head: str) -> dict[str, Any]:
    failure = _mapping(value, "failed_execution")
    _exact_keys(
        failure,
        {
            "actuals",
            "conclusion",
            "event",
            "failure_message",
            "head_branch",
            "head_sha",
            "jobs",
            "protected_environment_entered",
            "run_attempt",
            "run_id",
            "status",
            "workflow_path",
        },
        "failed_execution",
    )
    _require(
        type(failure.get("run_id")) is int
        and failure.get("run_id") == EXPECTED_EXECUTION_RUN_ID
        and type(failure.get("run_attempt")) is int
        and failure.get("run_attempt") == 1
        and failure.get("workflow_path") == EXPECTED_WORKFLOW_PATH
        and failure.get("event") == "push"
        and failure.get("head_branch") == EXPECTED_BRANCH
        and failure.get("head_sha") == execution_head
        and failure.get("status") == "completed"
        and failure.get("conclusion") == "failure"
        and failure.get("failure_message") == EXPECTED_FAILURE_MESSAGE
        and failure.get("protected_environment_entered") is False,
        "failed execution identity or boundary differs",
    )
    jobs = failure.get("jobs")
    _require(
        jobs
        == {
            "bounded-context-preflight": "skipped",
            "branch-trigger-preflight": "failure",
            "frozen-serial-phase": "skipped",
        },
        "failed execution job boundary differs",
    )
    actuals = _validate_zero_counters(failure.get("actuals"))
    return {
        "actuals": actuals,
        "conclusion": "failure",
        "event": "push",
        "failure_message": EXPECTED_FAILURE_MESSAGE,
        "head_branch": EXPECTED_BRANCH,
        "head_sha": execution_head,
        "jobs": dict(jobs),
        "protected_environment_entered": False,
        "run_attempt": 1,
        "run_id": EXPECTED_EXECUTION_RUN_ID,
        "status": "completed",
        "workflow_path": EXPECTED_WORKFLOW_PATH,
    }


def validate_replay(value: Any) -> dict[str, Any]:
    document = _mapping(value, "replay")
    _exact_keys(
        document,
        {
            "branch",
            "current_pull_request",
            "expected_source_gates",
            "failed_execution",
            "historical_source_runs",
            "repository",
            "schema",
            "transition",
        },
        "replay",
    )
    _require(document.get("schema") == SCHEMA, "replay schema differs")
    _require(
        document.get("repository") == EXPECTED_REPOSITORY
        and document.get("branch") == EXPECTED_BRANCH,
        "replay repository or branch differs",
    )
    transition = validate_transition(document.get("transition"))
    _validate_expected_gate_manifest(document.get("expected_source_gates"))
    gates = select_source_gate_runs(
        document.get("historical_source_runs"),
        source_head=transition["source_head"],
    )
    validate_current_pull_request(
        document.get("current_pull_request"),
        expected_head=transition["execution_head"],
    )
    validate_failed_execution(
        document.get("failed_execution"),
        execution_head=transition["execution_head"],
    )
    return {
        "execution_head": transition["execution_head"],
        "execution_run_attempt": 1,
        "execution_run_id": EXPECTED_EXECUTION_RUN_ID,
        "historical_source_gates": len(gates),
        "ignored_mutable_historical_fields": ["pull_requests"],
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "source_head": transition["source_head"],
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def load_replay(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise D111GateContractError(f"cannot read replay fixture: {path}") from exc
    value = strict_json(raw)
    return dict(_mapping(value, "replay"))


def _default_fixture() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "fixtures"
        / "trimem_d111"
        / "exec_011_branch_transition.json"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay the credential-free D1.11 GitHub gate regression"
    )
    parser.add_argument("--fixture", type=Path, default=_default_fixture())
    args = parser.parse_args(argv)
    try:
        result = validate_replay(load_replay(args.fixture))
    except D111GateContractError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
