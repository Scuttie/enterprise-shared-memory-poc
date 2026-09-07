from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/trimem_d111_gate_contract.py"
FIXTURE = ROOT / "tests/fixtures/trimem_d111/exec_011_branch_transition.json"
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d111_gate_contract as contract  # noqa: E402


EXPECTED_GATE_ORACLE = (
    (34046493129, ".github/workflows/ci-trimem.yml", "push"),
    (34046493102, ".github/workflows/ci-trimem-grader-loader.yml", "push"),
    (34046493066, ".github/workflows/ci-trimem-harness-lock.yml", "push"),
    (34046493075, ".github/workflows/ci-trimem-multi-swe-contract.yml", "push"),
    (34046493064, ".github/workflows/ci-trimem-e2e.yml", "push"),
    (34046493119, ".github/workflows/ci-trimem-dev-toolchain.yml", "push"),
    (34046495419, ".github/workflows/ci.yml", "pull_request"),
    (34046495420, ".github/workflows/codeql.yml", "pull_request"),
    (34046495429, ".github/workflows/ci-docs.yml", "pull_request"),
    (34046495417, ".github/workflows/ci-company-package.yml", "pull_request"),
    (34046495426, ".github/workflows/ci-company-harness.yml", "pull_request"),
    (34046495396, ".github/workflows/ci-company-demo.yml", "pull_request"),
)
ZERO_COUNTER_ORACLE = {
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


def _document() -> dict[str, object]:
    return contract.load_replay(FIXTURE)


def _run(document: dict[str, object], path: str) -> dict[str, object]:
    runs = document["historical_source_runs"]
    assert isinstance(runs, list)
    return next(run for run in runs if run["path"] == path)


def test_exec_011_fixture_replays_actual_mutable_pr_transition() -> None:
    document = _document()
    runs = document["historical_source_runs"]
    assert isinstance(runs, list)
    pull_request_runs = [run for run in runs if run["event"] == "pull_request"]

    assert len(pull_request_runs) == 6
    assert all(
        run["head_sha"] == contract.EXPECTED_SOURCE_HEAD
        and run["pull_requests"][0]["head"]["sha"]
        == contract.EXPECTED_EXECUTION_HEAD
        for run in pull_request_runs
    )

    report = contract.validate_replay(document)

    assert report == {
        "execution_head": contract.EXPECTED_EXECUTION_HEAD,
        "execution_run_attempt": 1,
        "execution_run_id": contract.EXPECTED_EXECUTION_RUN_ID,
        "historical_source_gates": 12,
        "ignored_mutable_historical_fields": ["pull_requests"],
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "source_head": contract.EXPECTED_SOURCE_HEAD,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def test_all_twelve_gate_tuples_are_frozen_by_literal_test_oracle() -> None:
    document = _document()
    manifest = document["expected_source_gates"]
    assert isinstance(manifest, list)

    assert contract.REQUIRED_SOURCE_GATES == EXPECTED_GATE_ORACLE
    assert tuple(
        (row["run_id"], row["workflow_path"], row["event"]) for row in manifest
    ) == EXPECTED_GATE_ORACLE

    runs = document["historical_source_runs"]
    assert isinstance(runs, list)
    observed = tuple((run["id"], run["path"], run["event"]) for run in runs)
    assert observed == EXPECTED_GATE_ORACLE


def test_zero_counter_set_is_frozen_by_literal_test_oracle() -> None:
    document = _document()
    failure = document["failed_execution"]
    assert isinstance(failure, dict)

    assert contract.EXPECTED_ZERO_COUNTERS == ZERO_COUNTER_ORACLE
    assert failure["actuals"] == ZERO_COUNTER_ORACLE


@pytest.mark.parametrize(
    "replacement",
    [
        None,
        [],
        {"untrusted": "relationship metadata"},
        [{"head": {"sha": "f" * 40}, "number": 999}],
    ],
)
def test_historical_selection_ignores_entire_pull_requests_value(
    replacement: object,
) -> None:
    document = _document()
    runs = document["historical_source_runs"]
    assert isinstance(runs, list)
    for run in runs:
        run["pull_requests"] = deepcopy(replacement)

    assert contract.validate_replay(document)["historical_source_gates"] == 12


def test_historical_selection_does_not_require_pull_requests_key() -> None:
    document = _document()
    runs = document["historical_source_runs"]
    assert isinstance(runs, list)
    for run in runs:
        run.pop("pull_requests", None)

    assert contract.validate_replay(document)["historical_source_gates"] == 12


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 34046495418),
        ("id", True),
        ("path", ".github/workflows/wrong.yml"),
        ("event", "push"),
        ("head_sha", contract.EXPECTED_EXECUTION_HEAD),
        ("head_branch", "wrong-branch"),
        ("run_attempt", 2),
        ("run_attempt", True),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("html_url", "https://github.com/example/wrong/actions/runs/1"),
    ],
)
def test_historical_gate_fails_closed_on_top_level_identity_drift(
    field: str, value: object
) -> None:
    document = _document()
    run = _run(document, ".github/workflows/ci.yml")
    run[field] = value

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


def test_nested_source_sha_cannot_override_top_level_head_drift() -> None:
    document = _document()
    run = _run(document, ".github/workflows/ci.yml")
    run["head_sha"] = contract.EXPECTED_EXECUTION_HEAD
    run["pull_requests"] = [
        {"head": {"sha": contract.EXPECTED_SOURCE_HEAD}, "number": 18}
    ]

    with pytest.raises(
        contract.D111GateContractError,
        match="exactly one immutable source gate",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_historical_run_shape_fails_closed(mutation: str) -> None:
    document = _document()
    runs = document["historical_source_runs"]
    assert isinstance(runs, list)
    if mutation == "missing":
        runs[0].pop("status")
    elif mutation == "extra":
        runs[0]["unfrozen"] = "field"
    else:
        runs[0] = ["not", "an", "object"]

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


@pytest.mark.parametrize("operation", ["missing", "duplicate"])
def test_historical_gate_fails_closed_on_missing_or_duplicate(operation: str) -> None:
    document = _document()
    runs = document["historical_source_runs"]
    assert isinstance(runs, list)
    if operation == "missing":
        runs.pop()
    else:
        runs[-1] = deepcopy(runs[0])

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


def test_expected_run_manifest_is_frozen_independently_of_observed_runs() -> None:
    document = _document()
    manifest = document["expected_source_gates"]
    assert isinstance(manifest, list)
    manifest[0]["run_id"] += 1

    with pytest.raises(
        contract.D111GateContractError,
        match="expected source-gate manifest differs",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize("replacement", [None, [], [{"event": "push"}]])
def test_expected_run_manifest_shape_fails_closed(replacement: object) -> None:
    document = _document()
    document["expected_source_gates"] = replacement

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "trimem/wrong/1.0"),
        ("repository", "wrong/repository"),
        ("branch", "wrong-branch"),
    ],
)
def test_replay_root_identity_is_exact(field: str, value: object) -> None:
    document = _document()
    document[field] = value

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_replay_root_shape_fails_closed(mutation: str) -> None:
    document = _document()
    if mutation == "missing":
        document.pop("failed_execution")
    elif mutation == "extra":
        document["unfrozen"] = True
    else:
        with pytest.raises(contract.D111GateContractError, match="replay is not an object"):
            contract.validate_replay([])
        return

    with pytest.raises(contract.D111GateContractError, match="replay field set differs"):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("number", 19),
        ("number", 18.0),
        ("head_sha", contract.EXPECTED_SOURCE_HEAD),
        ("head_ref", "wrong-branch"),
        ("head_repository", "wrong/repository"),
        ("base_ref", "wrong-base"),
        ("base_sha", "f" * 40),
        ("state", "closed"),
        ("draft", False),
        ("draft", 1),
        ("html_url", "https://github.com/example/wrong/pull/18"),
    ],
)
def test_current_pr_is_separately_bound_to_execution_head(
    field: str, value: object
) -> None:
    document = _document()
    pull = document["current_pull_request"]
    assert isinstance(pull, dict)
    pull[field] = value

    with pytest.raises(
        contract.D111GateContractError,
        match="current PR is not exact at execution head",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_current_pr_shape_fails_closed(mutation: str) -> None:
    document = _document()
    if mutation == "wrong-container":
        document["current_pull_request"] = []
    else:
        pull = document["current_pull_request"]
        assert isinstance(pull, dict)
        if mutation == "missing":
            pull.pop("head_sha")
        else:
            pull["unfrozen"] = "field"

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    "parents",
    [
        [],
        ["f" * 40],
        [contract.EXPECTED_SOURCE_HEAD, "f" * 40],
    ],
)
def test_transition_requires_exact_single_source_parent(parents: list[str]) -> None:
    document = _document()
    transition = document["transition"]
    assert isinstance(transition, dict)
    transition["execution_parents"] = parents

    with pytest.raises(
        contract.D111GateContractError,
        match="exact single-parent child",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_head", "f" * 40),
        ("execution_head", "f" * 40),
    ],
)
def test_transition_heads_are_exact(field: str, value: str) -> None:
    document = _document()
    transition = document["transition"]
    assert isinstance(transition, dict)
    transition[field] = value

    with pytest.raises(
        contract.D111GateContractError,
        match="source or execution head differs",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("path", "artifacts/trimem_v1/exec_requests/wrong.json"),
        ("mode", "100755"),
        ("status", "M"),
    ],
)
def test_transition_requires_only_regular_011_sentinel_addition(
    field: str, value: object
) -> None:
    document = _document()
    transition = document["transition"]
    assert isinstance(transition, dict)
    transition["changed_files"][0][field] = value

    with pytest.raises(
        contract.D111GateContractError,
        match="sentinel-only regular-file addition",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize("changed_files", [[], [None, None]])
def test_transition_rejects_changed_file_cardinality(
    changed_files: list[object],
) -> None:
    document = _document()
    transition = document["transition"]
    assert isinstance(transition, dict)
    transition["changed_files"] = changed_files

    with pytest.raises(
        contract.D111GateContractError,
        match="sentinel-only regular-file addition",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_transition_shape_fails_closed(mutation: str) -> None:
    document = _document()
    if mutation == "wrong-container":
        document["transition"] = []
    else:
        transition = document["transition"]
        assert isinstance(transition, dict)
        if mutation == "missing":
            transition.pop("source_head")
        else:
            transition["unfrozen"] = True

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


@pytest.mark.parametrize("counter", sorted(ZERO_COUNTER_ORACLE))
def test_exec_011_failure_counters_must_remain_exact_zero(counter: str) -> None:
    document = _document()
    failure = document["failed_execution"]
    assert isinstance(failure, dict)
    actuals = failure["actuals"]
    assert isinstance(actuals, dict)
    actuals[counter] = 1.0 if counter == "total_usd" else 1

    with pytest.raises(
        contract.D111GateContractError,
        match=f"zero-call failure counter differs: {counter}",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    ("counter", "value"),
    [("paid_model_calls", False), ("total_usd", 0)],
)
def test_zero_counters_reject_bool_or_numeric_type_aliases(
    counter: str, value: object
) -> None:
    document = _document()
    failure = document["failed_execution"]
    assert isinstance(failure, dict)
    actuals = failure["actuals"]
    assert isinstance(actuals, dict)
    actuals[counter] = value

    with pytest.raises(
        contract.D111GateContractError,
        match=f"zero-call failure counter differs: {counter}",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_attempt", 2),
        ("run_attempt", True),
        ("run_id", 34047573549),
        ("head_sha", contract.EXPECTED_SOURCE_HEAD),
        ("head_branch", "wrong-branch"),
        ("event", "pull_request"),
        ("status", "in_progress"),
        ("workflow_path", ".github/workflows/wrong.yml"),
        ("failure_message", "wrong failure"),
        ("protected_environment_entered", True),
        ("conclusion", "success"),
    ],
)
def test_failed_execution_boundary_rejects_rerun_or_stage_drift(
    field: str, value: object
) -> None:
    document = _document()
    failure = document["failed_execution"]
    assert isinstance(failure, dict)
    failure[field] = value

    with pytest.raises(
        contract.D111GateContractError,
        match="failed execution identity or boundary differs",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize(
    ("job", "value"),
    [
        ("branch-trigger-preflight", "success"),
        ("bounded-context-preflight", "success"),
        ("frozen-serial-phase", "success"),
    ],
)
def test_job_boundary_is_exact_after_branch_gate_failure(
    job: str, value: str
) -> None:
    document = _document()
    failure = document["failed_execution"]
    assert isinstance(failure, dict)
    failure["jobs"][job] = value

    with pytest.raises(
        contract.D111GateContractError,
        match="failed execution job boundary differs",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize("jobs", [{}, [], {"branch-trigger-preflight": "failure"}])
def test_job_boundary_shape_fails_closed(jobs: object) -> None:
    document = _document()
    failure = document["failed_execution"]
    assert isinstance(failure, dict)
    failure["jobs"] = jobs

    with pytest.raises(
        contract.D111GateContractError,
        match="failed execution job boundary differs",
    ):
        contract.validate_replay(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_failed_execution_shape_fails_closed(mutation: str) -> None:
    document = _document()
    if mutation == "wrong-container":
        document["failed_execution"] = []
    else:
        failure = document["failed_execution"]
        assert isinstance(failure, dict)
        if mutation == "missing":
            failure.pop("run_id")
        else:
            failure["unfrozen"] = True

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_zero_counter_shape_fails_closed(mutation: str) -> None:
    document = _document()
    failure = document["failed_execution"]
    assert isinstance(failure, dict)
    if mutation == "wrong-container":
        failure["actuals"] = []
    else:
        actuals = failure["actuals"]
        assert isinstance(actuals, dict)
        if mutation == "missing":
            actuals.pop("paid_model_calls")
        else:
            actuals["unfrozen"] = 0

    with pytest.raises(contract.D111GateContractError):
        contract.validate_replay(document)


def test_strict_json_rejects_bom_duplicate_keys_and_nonfinite_numbers() -> None:
    invalid = (
        b'\xef\xbb\xbf{"status":"PASS"}',
        b'{"status":"PASS","status":"FAIL"}',
        b'{"value":NaN}',
    )
    for raw in invalid:
        with pytest.raises(contract.D111GateContractError):
            contract.strict_json(raw)


def test_module_has_no_network_process_or_environment_dependency() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert not imported_roots & {
        "http",
        "os",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }


def test_cli_replays_fixture_under_isolated_python_without_credentials(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--fixture", str(FIXTURE)],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env={"PYTHONIOENCODING": "utf-8"},
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["status"] == "PASS"
    assert json.loads(completed.stdout)["historical_source_gates"] == 12
