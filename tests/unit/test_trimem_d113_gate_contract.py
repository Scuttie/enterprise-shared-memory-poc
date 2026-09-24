from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/trimem_d113_gate_contract.py"
FIXTURE = (
    ROOT
    / "tests/fixtures/trimem_d113/exec_012_preprotected_failure.json"
)
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d113_gate_contract as contract  # noqa: E402


RUN_ID = 34_128_541_859
EXECUTION_HEAD = "491d1022fe079d182d7b453c48083c486936dcb2"
SOURCE_HEAD = "9db94e2a4abfaad0bb27079738b77836d68fa2e4"
PROJECTION_DIGEST_ORACLE = {
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
STATIC_DIGEST_ORACLE = {
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
JOB_ORACLE = (
    ("branch-trigger-preflight", 101_762_848_605, "failure"),
    ("bounded-context-preflight", 101_762_966_076, "skipped"),
    ("frozen-serial-phase", 101_762_966_474, "skipped"),
)
STEP_ORACLE = (
    (1, "Set up job", "success"),
    (2, "Checkout exact trigger commit", "success"),
    (3, "Set up exact Python", "success"),
    (4, "Install pinned GitHub CLI for branch gate", "success"),
    (5, "Verify pinned GitHub CLI for branch gate", "success"),
    (6, "Verify one-time zero-authority DEV trigger", "failure"),
    (11, "Post Set up exact Python", "skipped"),
    (12, "Post Checkout exact trigger commit", "success"),
    (13, "Complete job", "success"),
)


def _document() -> dict[str, object]:
    return contract.load_fixture(FIXTURE)


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _job(document: dict[str, object], name: str) -> dict[str, object]:
    jobs = document["jobs"]
    assert isinstance(jobs, list)
    return next(job for job in jobs if job["name"] == name)


def test_exec_012_fixture_validates_exact_preprotected_failure() -> None:
    report = contract.validate_fixture(_document())

    assert report == {
        "benchmark_image_pulls": 0,
        "evidence_bundle_sha256": PROJECTION_DIGEST_ORACLE[
            "evidence_bundle_sha256"
        ],
        "execution_head": EXECUTION_HEAD,
        "execution_run_attempt": 1,
        "execution_run_id": RUN_ID,
        "failed_job": "branch-trigger-preflight",
        "failed_step": "Verify one-time zero-authority DEV trigger",
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "protected_environment_entered": False,
        "self_hosted_job_assignments": 0,
        "source_head": SOURCE_HEAD,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def test_reseal_compatibility_interface_is_exact() -> None:
    assert contract.EXPECTED_EXECUTION_RUN_ID == RUN_ID
    assert contract.EXPECTED_FAILURE_SUBTYPE == (
        "HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION"
    )
    assert contract.load_replay(FIXTURE) == _document()
    assert contract.validate_replay(_document())["status"] == "PASS"


def test_literal_oracles_freeze_jobs_steps_and_zero_counters() -> None:
    document = _document()
    jobs = document["jobs"]
    assert isinstance(jobs, list)
    assert tuple(
        (job["name"], job["id"], job["conclusion"]) for job in jobs
    ) == JOB_ORACLE
    assert tuple(
        (step["number"], step["name"], step["conclusion"])
        for step in jobs[0]["steps"]
    ) == STEP_ORACLE
    assert document["actuals"] == ZERO_COUNTER_ORACLE
    assert contract.EXPECTED_ZERO_COUNTERS == ZERO_COUNTER_ORACLE


def test_projection_digests_are_independently_recomputed_and_nonzero() -> None:
    document = _document()
    digests = document["digests"]
    assert isinstance(digests, dict)
    bundle = {
        key: document[key]
        for key in sorted(set(document) - {"digests"})
    }
    recomputed = {
        "evidence_bundle_sha256": _canonical_sha256(bundle),
        "failed_log_summary_sha256": _canonical_sha256(
            document["failed_log_summary"]
        ),
        "jobs_projection_sha256": _canonical_sha256(document["jobs"]),
        "workflow_run_projection_sha256": _canonical_sha256(
            document["workflow_run"]
        ),
    }

    assert recomputed == PROJECTION_DIGEST_ORACLE
    assert contract.EXPECTED_PROJECTION_DIGESTS == PROJECTION_DIGEST_ORACLE
    assert all(value != "0" * 64 for value in recomputed.values())
    assert {
        key: digests[key] for key in PROJECTION_DIGEST_ORACLE
    } == PROJECTION_DIGEST_ORACLE


def test_static_artifact_digests_are_independently_pinned() -> None:
    document = _document()
    digests = document["digests"]
    assert isinstance(digests, dict)

    assert contract.EXPECTED_STATIC_DIGESTS == STATIC_DIGEST_ORACLE
    assert {
        key: digests[key] for key in STATIC_DIGEST_ORACLE
    } == STATIC_DIGEST_ORACLE


@pytest.mark.parametrize("counter", sorted(ZERO_COUNTER_ORACLE))
def test_every_activity_counter_must_remain_exact_zero(counter: str) -> None:
    document = _document()
    actuals = document["actuals"]
    assert isinstance(actuals, dict)
    actuals[counter] = 1.0 if counter == "total_usd" else 1

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("counter", "value"),
    [("paid_model_calls", False), ("model_api_calls", 0.0), ("total_usd", 0)],
)
def test_zero_counters_reject_bool_and_numeric_type_aliases(
    counter: str, value: object
) -> None:
    document = _document()
    actuals = document["actuals"]
    assert isinstance(actuals, dict)
    actuals[counter] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", RUN_ID + 1),
        ("run_attempt", 2),
        ("run_attempt", True),
        ("run_number", 13),
        ("workflow_id", 1),
        ("event", "workflow_dispatch"),
        ("path", ".github/workflows/wrong.yml"),
        ("head_branch", "wrong-branch"),
        ("head_sha", SOURCE_HEAD),
        ("status", "in_progress"),
        ("conclusion", "success"),
        ("html_url", "https://github.com/example/wrong/actions/runs/1"),
        ("display_title", "wrong title"),
        ("created_at", "not-a-timestamp"),
    ],
)
def test_workflow_run_identity_and_terminal_state_fail_closed(
    field: str, value: object
) -> None:
    document = _document()
    run = document["workflow_run"]
    assert isinstance(run, dict)
    run[field] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_workflow_run_shape_fails_closed(mutation: str) -> None:
    document = _document()
    if mutation == "wrong-container":
        document["workflow_run"] = []
    else:
        run = document["workflow_run"]
        assert isinstance(run, dict)
        if mutation == "missing":
            run.pop("status")
        else:
            run["unfrozen"] = True

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered"])
def test_job_order_and_cardinality_fail_closed(mutation: str) -> None:
    document = _document()
    jobs = document["jobs"]
    assert isinstance(jobs, list)
    if mutation == "missing":
        jobs.pop()
    elif mutation == "duplicate":
        jobs[-1] = deepcopy(jobs[0])
    else:
        jobs[0], jobs[1] = jobs[1], jobs[0]

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", 1),
        ("run_id", RUN_ID + 1),
        ("run_attempt", 2),
        ("run_attempt", True),
        ("status", "queued"),
        ("conclusion", "success"),
        ("runner_id", 0),
        ("runner_group_id", False),
        ("html_url", "https://github.com/example/wrong/job/1"),
    ],
)
def test_failed_hosted_job_identity_and_runner_fail_closed(
    field: str, value: object
) -> None:
    document = _document()
    _job(document, "branch-trigger-preflight")[field] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conclusion", "success"),
        ("runner_id", 1),
        ("runner_name", "runner"),
        ("runner_group_id", 0),
        ("runner_group_name", "group"),
        ("steps", [{"entered": True}]),
        ("labels", ["self-hosted"]),
    ],
)
@pytest.mark.parametrize(
    "job_name", ["bounded-context-preflight", "frozen-serial-phase"]
)
def test_skipped_self_hosted_jobs_never_entered_or_received_assignment(
    job_name: str, field: str, value: object
) -> None:
    document = _document()
    _job(document, job_name)[field] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("number", 7),
        ("number", True),
        ("name", "wrong step"),
        ("status", "in_progress"),
        ("conclusion", "success"),
        ("started_at", "not-a-timestamp"),
    ],
)
def test_exact_failing_step_is_frozen(field: str, value: object) -> None:
    document = _document()
    job = _job(document, "branch-trigger-preflight")
    steps = job["steps"]
    assert isinstance(steps, list)
    step = next(item for item in steps if item["number"] == 6)
    step[field] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "reordered"])
def test_hosted_step_sequence_shape_fails_closed(mutation: str) -> None:
    document = _document()
    job = _job(document, "branch-trigger-preflight")
    steps = job["steps"]
    assert isinstance(steps, list)
    if mutation == "missing":
        steps.pop()
    elif mutation == "extra":
        steps.append(deepcopy(steps[-1]))
    else:
        steps[0], steps[1] = steps[1], steps[0]

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("failure_classification", "WRONG_FAILURE"),
        ("failure_message", "wrong failure"),
        ("failed_job", "wrong-job"),
        ("failed_step", "wrong step"),
        ("failed_step_number", 7),
        ("failed_step_number", True),
        ("process_exit_code", 0),
        ("raw_log_embedded", True),
        ("sanitization", "RAW_LOG"),
        ("freeze_check", {"files": 435, "status": "PASS"}),
    ],
)
def test_normalized_failed_log_summary_is_exact(
    field: str, value: object
) -> None:
    document = _document()
    summary = document["failed_log_summary"]
    assert isinstance(summary, dict)
    summary[field] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protected_environment_entered", True),
        ("protected_environment_approval_requested", True),
        ("bounded_context_preflight_entered", True),
        ("frozen_serial_phase_entered", True),
        ("branch_trigger_preflight_entered", False),
        ("self_hosted_job_assignments", 1),
        ("self_hosted_job_assignments", False),
        ("failure_stage", "PROTECTED_EXECUTION"),
    ],
)
def test_protected_and_self_hosted_boundary_fails_closed(
    field: str, value: object
) -> None:
    document = _document()
    boundary = document["boundary"]
    assert isinstance(boundary, dict)
    boundary[field] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize("field", sorted(PROJECTION_DIGEST_ORACLE))
@pytest.mark.parametrize("replacement", ["0" * 64, "f" * 64, "not-a-digest"])
def test_projection_digest_placeholders_and_drift_are_rejected(
    field: str, replacement: str
) -> None:
    document = _document()
    digests = document["digests"]
    assert isinstance(digests, dict)
    digests[field] = replacement

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize("field", sorted(STATIC_DIGEST_ORACLE))
def test_static_digest_drift_is_rejected(field: str) -> None:
    document = _document()
    digests = document["digests"]
    assert isinstance(digests, dict)
    digests[field] = "f" * 64

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "trimem/wrong/1.0"),
        ("repository", "wrong/repository"),
        ("branch", "wrong-branch"),
        ("source_head", "f" * 40),
        ("execution_head", "f" * 40),
    ],
)
def test_fixture_root_identity_is_exact(field: str, value: object) -> None:
    document = _document()
    document[field] = value

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


@pytest.mark.parametrize("mutation", ["missing", "extra", "wrong-container"])
def test_fixture_root_shape_fails_closed(mutation: str) -> None:
    document = _document()
    if mutation == "wrong-container":
        value: object = []
    else:
        if mutation == "missing":
            document.pop("boundary")
        else:
            document["unfrozen"] = True
        value = document

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(value)


@pytest.mark.parametrize(
    ("section", "mutation"),
    [
        ("actuals", "missing"),
        ("actuals", "extra"),
        ("boundary", "missing"),
        ("boundary", "extra"),
        ("sanitization", "missing"),
        ("sanitization", "extra"),
        ("digests", "missing"),
        ("digests", "extra"),
    ],
)
def test_nested_object_shapes_fail_closed(section: str, mutation: str) -> None:
    document = _document()
    value = document[section]
    assert isinstance(value, dict)
    if mutation == "missing":
        value.pop(next(iter(value)))
    else:
        value["unfrozen"] = False

    with pytest.raises(contract.D113GateContractError):
        contract.validate_fixture(document)


def test_strict_json_rejects_bom_nul_duplicate_and_nonfinite_values() -> None:
    invalid = (
        b'\xef\xbb\xbf{"status":"PASS"}',
        b'{"status":"PASS\x00"}',
        b'{"status":"PASS","status":"FAIL"}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'\xff',
    )
    for raw in invalid:
        with pytest.raises(contract.D113GateContractError):
            contract.strict_json(raw)


def test_fixture_is_utf8_without_bom_nul_cr_or_raw_sensitive_payloads() -> None:
    raw = FIXTURE.read_bytes()
    lowered = raw.lower()

    assert raw.endswith(b"\n")
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\x00" not in raw
    assert b"\r" not in raw
    assert b"authorization:" not in lowered
    assert b"bearer " not in lowered
    assert b'"github_token":' not in lowered
    assert b'"openai_api_key":' not in lowered
    assert b'"trimem_exec_approval":' not in lowered


def test_module_has_no_network_process_or_environment_dependency() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                alias.name.split(".", 1)[0] for alias in node.names
            )
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


def test_cli_validates_fixture_under_isolated_python_without_credentials(
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
    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert report["execution_run_id"] == RUN_ID
    assert report["protected_environment_entered"] is False
    assert report["model_api_calls"] == 0
    assert report["grader_containers"] == 0
