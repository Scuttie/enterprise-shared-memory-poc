from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/trimem_d113_reseal.py"
REPORT = ROOT / "reports/TRIMEM_D113_EXEC_013_RECOVERY.md"
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d113_reseal as reseal  # noqa: E402


SOURCE_HEAD = "9db94e2a4abfaad0bb27079738b77836d68fa2e4"
EXECUTION_HEAD = "491d1022fe079d182d7b453c48083c486936dcb2"
REQUEST_RAW_SHA256 = (
    "6691a24bf488a79b4e1843a129d3d8773090fe2654828534c35eeecc22cc9d38"
)
REQUEST_PAYLOAD_SHA256 = (
    "efa99c554fbae9bbeb8a87536365fcfc6afa54e6ee48de17ef9ffdb0eb72132b"
)
FREEZE_SHA256 = (
    "3bbafc53504b45c20996094d96a6abfa5fd9e90c5b078eb2f1dc3f1f6d7ad5b4"
)


def _git_blob(commit: str, relative: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout


def test_d113_module_is_valid_python_and_help_is_dependency_free() -> None:
    ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--write" in completed.stdout
    assert "--check" in completed.stdout


def test_d113_identity_and_zero_authority_are_exact() -> None:
    assert reseal.STATUS == (
        "FROZEN_CREDENTIAL_FREE_EXEC_012_FAILURE_READY_FOR_EXEC_013_REQUEST"
    )
    assert reseal.CLASSIFICATION == (
        "POST_EXEC_012_ZERO_MODEL_RUNNER_OBSERVER_RECOVERY"
    )
    assert reseal.FAILURE_SUBTYPE == (
        "HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION"
    )
    assert reseal.ENDPOINT == "TRIMEM_V1_READY_FOR_EXEC_013_REQUEST"
    assert reseal.D113_REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013"
    assert reseal.D113_REQUEST_SCHEMA == (
        "trimem/development-tuning-branch-trigger/1.13"
    )
    assert reseal.D113_REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013_APPROVED_ONCE"
    )
    assert reseal.ZERO_ACTUALS == {
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


def test_exec_012_commit_blob_and_two_hash_identities_are_immutable() -> None:
    historical = reseal.validate_historical_d112()
    assert historical == {
        "amendment_sha256": reseal.D112_AMENDMENT_SHA256,
        "execution_head": EXECUTION_HEAD,
        "execution_parent": SOURCE_HEAD,
        "freeze_sha256": FREEZE_SHA256,
        "inventory_sha256": reseal.D112_INVENTORY_SHA256,
        "request_blob_oid": "f4111cfd1a26b4099f0b0fdc4dd840d4de21764f",
        "request_bytes": 20_561,
        "request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012",
        "request_payload_sha256": REQUEST_PAYLOAD_SHA256,
        "request_raw_sha256": REQUEST_RAW_SHA256,
        "run_attempt": 1,
        "run_id": 34_128_541_859,
        "sentinel_only": True,
        "source_head": SOURCE_HEAD,
        "status": "PASS",
    }
    raw = _git_blob(EXECUTION_HEAD, reseal.D112_REQUEST_PATH)
    assert len(raw) == 20_561
    assert hashlib.sha256(raw).hexdigest() == REQUEST_RAW_SHA256
    request = json.loads(raw)
    assert request["request_sha256"] == f"sha256:{REQUEST_PAYLOAD_SHA256}"
    assert request["request_sha256"] != f"sha256:{REQUEST_RAW_SHA256}"
    assert raw.endswith(b"\n")
    assert b"\r" not in raw


def test_failure_fixture_is_validated_by_its_own_gate_contract() -> None:
    replay = reseal.validate_failure_replay()
    assert replay["status"] == "PASS"
    assert replay["source_head"] == SOURCE_HEAD
    assert replay["execution_head"] == EXECUTION_HEAD
    assert replay["execution_run_id"] == 34_128_541_859
    assert replay["execution_run_attempt"] == 1
    assert replay["protected_environment_entered"] is False
    assert replay["self_hosted_job_assignments"] == 0
    for key in (
        "benchmark_image_pulls",
        "grader_containers",
        "model_api_calls",
        "official_grader_runs",
        "paid_model_calls",
        "task_arm_runs",
        "total_usd",
    ):
        assert replay[key] == 0


def test_failure_replay_fails_closed_when_gate_module_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(reseal, "GATE_CONTRACT_PATH", tmp_path / "missing.py")
    with pytest.raises(reseal.D113ResealError, match="absent or non-regular"):
        reseal.validate_failure_replay()


def test_failure_replay_rechecks_gate_zero_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = {
        "execution_head": EXECUTION_HEAD,
        "execution_run_attempt": 1,
        "execution_run_id": 34_128_541_859,
        "model_api_calls": 1,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "protected_environment_entered": False,
        "source_head": SOURCE_HEAD,
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }
    fake = SimpleNamespace(
        EXPECTED_SOURCE_HEAD=SOURCE_HEAD,
        EXPECTED_EXECUTION_HEAD=EXECUTION_HEAD,
        EXPECTED_RUN_ID=34_128_541_859,
        EXPECTED_RUN_ATTEMPT=1,
        EXPECTED_FAILURE_CLASSIFICATION=reseal.GATE_FAILURE_CLASSIFICATION,
        load_fixture=lambda _path: {},
        validate_fixture=lambda _value: result,
    )
    monkeypatch.setattr(reseal, "_load_exact_module", lambda _name, _path: fake)
    with pytest.raises(reseal.D113ResealError, match="nonzero execution actuals"):
        reseal.validate_failure_replay()


def test_failure_and_recovery_records_do_not_claim_a_result_or_authority() -> None:
    failure = reseal.current_failure_record()
    assert failure["workflow_run"] == {
        "attempt": 1,
        "conclusion": "failure",
        "head_sha": EXECUTION_HEAD,
        "id": 34_128_541_859,
        "source_head_sha": SOURCE_HEAD,
    }
    assert failure["failure_boundary"] == {
        "bounded_context_preflight": "SKIPPED",
        "branch_trigger_preflight": "FAILED",
        "frozen_serial_phase": "SKIPPED",
        "protected_environment_entered": False,
    }
    assert failure["observed_usage"] == reseal.ZERO_ACTUALS
    assert failure["performance_measured"] is False
    assert failure["pass_at_1"] is None
    assert failure["process_disposition"] == {
        "attempt_one_consumed": True,
        "attempt_two_allowed": False,
        "request_012_rerun_allowed": False,
        "request_013_execution_authorized": False,
    }

    recovery = reseal.current_recovery_record()
    assert recovery["request_creation_authority_received"] is True
    assert recovery["actual_execution_authorized"] is False
    assert recovery["external_execution_approval_received"] is False
    assert recovery["performance_measured"] is False
    assert recovery["request_present_in_recovery_source"] is False


def test_control_plane_allowlist_excludes_every_scientific_input() -> None:
    assert set(reseal.IMPLEMENTATION_PATHS).isdisjoint(
        reseal.PRESERVED_SCIENTIFIC_PATHS
    )
    assert reseal.D112_REQUEST_PATH not in reseal.ALLOWED_CHANGED_PATHS
    assert reseal.D113_REQUEST_PATH not in reseal.ALLOWED_CHANGED_PATHS
    assert set(reseal.REQUIRED_CHANGED_PATHS) <= reseal.ALLOWED_CHANGED_PATHS
    assert reseal.AMENDMENT_PATH.relative_to(ROOT).as_posix() in (
        reseal.REQUIRED_CHANGED_PATHS
    )
    assert reseal.INVENTORY_PATH.relative_to(ROOT).as_posix() in (
        reseal.REQUIRED_CHANGED_PATHS
    )
    assert reseal.FREEZE_PATH.relative_to(ROOT).as_posix() in (
        reseal.REQUIRED_CHANGED_PATHS
    )


def test_generated_documents_are_deterministic_and_have_no_source_head_cycle() -> None:
    first_amendment, first_inventory = reseal.build_artifacts()
    second_amendment, second_inventory = reseal.build_artifacts()
    assert (first_amendment, first_inventory) == (
        second_amendment,
        second_inventory,
    )
    assert first_amendment["schema"] == reseal.AMENDMENT_SCHEMA
    assert first_inventory["schema"] == reseal.INVENTORY_SCHEMA
    assert first_amendment["status"] == reseal.STATUS
    assert first_inventory["status"] == reseal.STATUS
    assert first_amendment["classification"] == reseal.CLASSIFICATION
    assert first_inventory["classification"] == reseal.CLASSIFICATION
    assert first_amendment["endpoint"] == reseal.ENDPOINT
    assert first_inventory["endpoint"] == reseal.ENDPOINT
    assert first_amendment["implementation_sha256"] == first_inventory[
        "implementation_sha256"
    ]
    assert set(first_amendment["implementation_sha256"]) == set(
        reseal.IMPLEMENTATION_PATHS
    )
    assert first_amendment["zero_cost_recovery_actuals"] == reseal.ZERO_ACTUALS
    authority = first_amendment["authority_boundary"]
    assert authority["request_013_creation_authorized"] is True
    assert authority["request_013_created"] is False
    assert authority["actual_execution_authorized"] is False
    assert authority["development_execution_authorized"] is False
    assert authority["external_execution_approval_received"] is False
    assert authority["request_013_execution_authorized"] is False
    assert authority["sentinel_contains_execution_authority"] is False

    execution = reseal.validate_optional_exec_013_boundary()
    source_head = reseal._source_head(execution)
    assert source_head not in json.dumps(
        first_amendment,
        ensure_ascii=False,
        sort_keys=True,
    )
    assert first_amendment["active_recovery"]["source_validation"] == (
        "GIT_BLOB_EXACT_AT_CHECK_TIME"
    )


def test_optional_013_boundary_is_absent_at_source_or_exact_sentinel_child() -> None:
    observed = reseal.validate_optional_exec_013_boundary()
    assert observed is None or reseal.HEX40.fullmatch(observed) is not None


def test_report_freezes_permission_attestation_and_no_result_meaning() -> None:
    raw = REPORT.read_bytes()
    assert raw.startswith(b"# TriMem-Coder V1 D1.13")
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    required = (
        "34128541859",
        "attempt `1`",
        "HOSTED_GITHUB_TOKEN_REPOSITORY_RUNNER_LIST_COMMAND_FAILURE",
        "HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION",
        "is not repository-runner inventory",
        "writer-time snapshot is provenance, not a permanent liveness claim",
        "bounded self-hosted job performs a live, event-bound local attestation",
        "Protected execution then requires a newly generated external approval",
        "gpt-5.4-mini-2026-03-17",
        "Paid/model calls remain `0`",
    )
    for marker in required:
        assert marker in text


def test_reseal_source_does_not_embed_a_mutable_current_source_head() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"source_head_validated_by_git_blobs"' not in source
    assert '"source_validation": "GIT_BLOB_EXACT_AT_CHECK_TIME"' in source
