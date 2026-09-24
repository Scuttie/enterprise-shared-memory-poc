from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/trimem_d114_reseal.py"
REPORT = ROOT / "reports/TRIMEM_D114_EXEC_014_RECOVERY.md"
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d114_reseal as reseal  # noqa: E402
import trimem_development_trigger_d114 as trigger  # noqa: E402


SOURCE_HEAD = "cb17ceae0fbc951dff34213de977a73b5405fefc"
EXECUTION_HEAD = "35bfa338915d731dab499f2dfee08b38741bfe8d"
D114_SOURCE_HEAD = "6e9abe999f2b9d7ebdd3eea23dbbea8f6afad931"
D114_EXECUTION_HEAD = "31234fdd58fd43170764524662c9e51687521761"
REQUEST_RAW_SHA256 = (
    "a500568cedfa800bd85e20263b604fa2c1d24f634644d5ef14f517a8330b6417"
)
REQUEST_PAYLOAD_SHA256 = (
    "132c7fc8a7ca166076882a53d3a69db56b4ccc5ab9e41ec1071a196f0618fe26"
)


def _git_blob(commit: str, relative: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout


def test_d114_module_is_valid_and_help_is_dependency_free() -> None:
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
    assert "--write" in completed.stdout and "--check" in completed.stdout


def test_d114_identity_and_zero_authority_are_exact() -> None:
    assert reseal.STATUS == (
        "FROZEN_CREDENTIAL_FREE_EXEC_013_FAILURE_READY_FOR_EXEC_014_REQUEST"
    )
    assert reseal.CLASSIFICATION == (
        "POST_EXEC_013_ZERO_MODEL_SETUP_PYTHON_ENVIRONMENT_RECOVERY"
    )
    assert reseal.FAILURE_SUBTYPE == (
        "SETUP_PYTHON_POST_SETUP_LD_LIBRARY_PATH_SHAPE"
    )
    assert reseal.ENDPOINT == "TRIMEM_V1_READY_FOR_EXEC_014_REQUEST"
    assert reseal.D114_REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
    assert reseal.D114_REQUEST_SCHEMA == (
        "trimem/development-tuning-branch-trigger/1.14"
    )
    assert reseal.D114_REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014_APPROVED_ONCE"
    )
    assert len(reseal.EXPECTED_REMOTE_GATE_SPECS) == 20
    assert reseal.EXPECTED_REMOTE_GATE_SPECS == trigger.REMOTE_GATE_SPECS
    assert reseal.EXPECTED_REMOTE_GATE_WORKFLOWS == (
        trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
    )
    assert all(value == 0 for value in reseal.ZERO_ACTUALS.values())


def test_exact_d113_source_sentinel_and_seal_are_immutable() -> None:
    historical = reseal.validate_historical_d113()
    assert historical["status"] == "PASS"
    assert historical["source_head"] == SOURCE_HEAD
    assert historical["execution_head"] == EXECUTION_HEAD
    assert historical["execution_parent"] == SOURCE_HEAD
    assert historical["sentinel_only"] is True
    assert historical["request_blob_oid"] == (
        "899492ee4835394f78699ee1d4a6273c2d26e875"
    )
    assert historical["request_bytes"] == 21_784
    assert historical["request_raw_sha256"] == REQUEST_RAW_SHA256
    assert historical["request_payload_sha256"] == REQUEST_PAYLOAD_SHA256
    assert historical["freeze_sha256"] == reseal.D113_FREEZE_SHA256
    assert historical["run_id"] == 34_138_918_074
    assert historical["run_attempt"] == 1
    assert historical["historical_d112"]["status"] == "PASS"

    raw = _git_blob(EXECUTION_HEAD, reseal.D113_REQUEST_PATH)
    assert len(raw) == 21_784
    assert hashlib.sha256(raw).hexdigest() == REQUEST_RAW_SHA256
    request = json.loads(raw)
    assert request["request_sha256"] == f"sha256:{REQUEST_PAYLOAD_SHA256}"
    assert raw.endswith(b"\n") and b"\r" not in raw


def test_exec_013_failure_replay_is_exact_and_zero_use() -> None:
    replay = reseal.validate_failure_replay()
    assert replay["status"] == "PASS"
    assert replay["source_head"] == SOURCE_HEAD
    assert replay["execution_head"] == EXECUTION_HEAD
    assert replay["execution_run_id"] == 34_138_918_074
    assert replay["execution_run_attempt"] == 1
    assert replay["self_hosted_job_assignments"] == 1
    assert replay["protected_environment_entered"] is False
    for key in (
        "benchmark_image_pulls",
        "dependency_installations",
        "grader_containers",
        "harness_materializations",
        "model_api_calls",
        "official_grader_runs",
        "paid_model_calls",
        "task_arm_runs",
        "total_usd",
    ):
        assert replay[key] == 0


def test_failure_and_recovery_records_do_not_claim_a_result_or_authority() -> None:
    failure = reseal.current_failure_record()
    assert failure["workflow_run"] == {
        "attempt": 1,
        "conclusion": "failure",
        "head_sha": EXECUTION_HEAD,
        "id": 34_138_918_074,
        "source_head_sha": SOURCE_HEAD,
    }
    assert failure["failure_boundary"]["branch_trigger_preflight"] == "PASSED"
    assert failure["failure_boundary"]["bounded_context_preflight"] == (
        "FAILED_AFTER_SETUP_BEFORE_INSTALL"
    )
    assert failure["failure_boundary"]["dependency_install_started"] is False
    assert failure["failure_boundary"]["harness_materialization_started"] is False
    assert failure["failure_boundary"]["protected_environment_entered"] is False
    assert failure["observed_usage"] == reseal.ZERO_ACTUALS
    assert failure["performance_measured"] is False
    assert failure["pass_at_1"] is None
    assert failure["process_disposition"] == {
        "attempt_one_consumed": True,
        "attempt_two_allowed": False,
        "request_013_rerun_allowed": False,
        "request_014_execution_authorized": False,
    }

    recovery = reseal.current_recovery_record()
    assert recovery["request_creation_authority_received"] is True
    assert recovery["actual_execution_authorized"] is False
    assert recovery["external_execution_approval_received"] is False
    assert recovery["request_present_in_recovery_source"] is False
    assert recovery["performance_measured"] is False


def test_changed_path_vocabulary_matches_trigger_and_excludes_science() -> None:
    assert reseal.ALLOWED_CHANGED_PATHS == trigger.ALLOWED_RECOVERY_PATHS
    assert reseal.REQUIRED_CHANGED_PATHS == trigger.REQUIRED_RECOVERY_CHANGES
    assert set(reseal.IMPLEMENTATION_PATHS).isdisjoint(
        reseal.PRESERVED_SCIENTIFIC_PATHS
    )
    assert reseal.D113_REQUEST_PATH not in reseal.ALLOWED_CHANGED_PATHS
    assert reseal.D114_REQUEST_PATH not in reseal.ALLOWED_CHANGED_PATHS
    assert set(reseal.REQUIRED_CHANGED_PATHS) <= reseal.ALLOWED_CHANGED_PATHS


def test_generated_documents_are_immutable_at_the_d114_source() -> None:
    amendment_raw = _git_blob(
        D114_SOURCE_HEAD,
        reseal.AMENDMENT_PATH.relative_to(ROOT).as_posix(),
    )
    inventory_raw = _git_blob(
        D114_SOURCE_HEAD,
        reseal.INVENTORY_PATH.relative_to(ROOT).as_posix(),
    )
    amendment = json.loads(amendment_raw)
    inventory = json.loads(inventory_raw)
    assert amendment_raw == reseal.AMENDMENT_PATH.read_bytes()
    assert inventory_raw == reseal.INVENTORY_PATH.read_bytes()
    assert amendment["schema"] == reseal.AMENDMENT_SCHEMA
    assert inventory["schema"] == reseal.INVENTORY_SCHEMA
    assert amendment["status"] == reseal.STATUS
    assert inventory["status"] == reseal.STATUS
    assert amendment["classification"] == reseal.CLASSIFICATION
    assert inventory["classification"] == reseal.CLASSIFICATION
    assert amendment["implementation_sha256"] == inventory[
        "implementation_sha256"
    ]
    assert set(amendment["implementation_sha256"]) == set(
        reseal.IMPLEMENTATION_PATHS
    )
    assert amendment["zero_cost_recovery_actuals"] == reseal.ZERO_ACTUALS
    authority = amendment["authority_boundary"]
    assert authority["request_013_attempt_one_consumed"] is True
    assert authority["request_013_rerun_allowed"] is False
    assert authority["request_014_creation_authorized"] is True
    assert authority["request_014_created"] is False
    assert authority["request_014_execution_authorized"] is False
    assert authority["actual_execution_authorized"] is False
    assert authority["external_execution_approval_received"] is False

    serialized = json.dumps(amendment, ensure_ascii=False, sort_keys=True)
    assert D114_SOURCE_HEAD not in serialized
    assert amendment["active_recovery"]["source_validation"] == (
        "GIT_BLOB_EXACT_AT_CHECK_TIME"
    )
    assert amendment["active_recovery"]["remote_gate_count"] == 20
    assert amendment["active_recovery"]["push_remote_gate_count"] == 6
    assert amendment["active_recovery"][
        "pull_request_remote_gate_count"
    ] == 14


def test_014_boundary_is_an_immutable_exact_sentinel_child() -> None:
    observed = trigger.validate_sentinel_commit(
        ROOT,
        D114_EXECUTION_HEAD,
        expected_parent=D114_SOURCE_HEAD,
        require_checked_out_head=False,
    )
    assert observed["request_id"] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
    assert observed["source_head"] == D114_SOURCE_HEAD


def test_report_freezes_exact_failure_fix_and_no_result_meaning() -> None:
    raw = REPORT.read_bytes()
    assert raw.startswith(b"# TriMem-Coder V1 D1.14")
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    required = (
        "34138918074",
        "attempt `1`",
        "101796314944",
        "POST_SETUP_PYTHON_DUAL_LD_LIBRARY_PATH_FAIL_CLOSED",
        "SETUP_PYTHON_POST_SETUP_LD_LIBRARY_PATH_SHAPE",
        "before dependency installation or harness materialization",
        "strict validator remains unchanged",
        "explicit step-level environment binding",
        "all 20 exact-head credential-free gates",
        "not an official harness/grader child launch",
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014_APPROVED_ONCE",
        "Paid/model calls remain `0`",
    )
    for marker in required:
        assert marker in text


def test_historical_d113_status_test_uses_exact_git_blobs_not_current_head() -> None:
    path = ROOT / "tests/unit/test_trimem_d113_status_and_reseal.py"
    source = path.read_text(encoding="utf-8")
    assert SOURCE_HEAD in source
    assert "validate_historical_d113" in source
    assert "build_artifacts()" not in source
    assert "validate_optional_exec_013_boundary()" not in source


def test_reseal_source_does_not_embed_mutable_d114_source_head() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"source_validation": "GIT_BLOB_EXACT_AT_CHECK_TIME"' in source
    assert "D114_SOURCE_HEAD =" not in source
