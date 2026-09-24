from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Callable

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/trimem_d115_reseal.py"
REPORT = ROOT / "reports/TRIMEM_D115_EXEC_015_RECOVERY.md"
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d115_reseal as reseal  # noqa: E402
import trimem_development_trigger_d115 as trigger  # noqa: E402
import trimem_freeze as freeze  # noqa: E402


SOURCE_HEAD = "6e9abe999f2b9d7ebdd3eea23dbbea8f6afad931"
EXECUTION_HEAD = "31234fdd58fd43170764524662c9e51687521761"
D115_SOURCE_HEAD = "de4b42be532910bf1a6349241b535ca31a93b6af"
REQUEST_RAW_SHA256 = (
    "7b4ff50e423cd12baea93413bbedcf7c2ee210d031fc20b30ad1c9d9f3c2dbaa"
)
REQUEST_PAYLOAD_SHA256 = (
    "e046c09ac2a40a4f5a819e8dc522074d20157ddd6201233de8c49e209451d353"
)


def _git_blob(commit: str, relative: str) -> bytes:
    return subprocess.run(
        ["git", "cat-file", "blob", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout


def test_d115_module_is_valid_and_help_is_dependency_free() -> None:
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


def test_d115_identity_status_and_zero_authority_are_exact() -> None:
    assert reseal.STATUS == (
        "FROZEN_CREDENTIAL_FREE_EXEC_014_FAILURE_READY_FOR_EXEC_015_REQUEST"
    )
    assert reseal.CLASSIFICATION == (
        "POST_EXEC_014_ZERO_MODEL_CACHED_PYTHON_LIBDIR_ALIAS_RECOVERY"
    )
    assert reseal.FAILURE_SUBTYPE == (
        "CACHED_PYTHON_SYSCONFIG_LIBDIR_ALIAS_ABSENT"
    )
    assert reseal.ENDPOINT == "TRIMEM_V1_READY_FOR_EXEC_015_REQUEST"
    assert reseal.D115_REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015"
    assert reseal.D115_REQUEST_SCHEMA == (
        "trimem/development-tuning-branch-trigger/1.15"
    )
    assert reseal.D115_REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015_APPROVED_ONCE"
    )
    assert len(reseal.EXPECTED_REMOTE_GATE_SPECS) == 20
    assert reseal.EXPECTED_REMOTE_GATE_SPECS == trigger.REMOTE_GATE_SPECS
    assert reseal.EXPECTED_REMOTE_GATE_WORKFLOWS == (
        trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
    )
    assert all(value == 0 for value in reseal.ZERO_SCIENTIFIC_ACTUALS.values())


def test_exact_d114_source_sentinel_and_seal_are_immutable() -> None:
    historical = reseal.validate_historical_d114()
    assert historical["status"] == "PASS"
    assert historical["source_head"] == SOURCE_HEAD
    assert historical["execution_head"] == EXECUTION_HEAD
    assert historical["execution_parent"] == SOURCE_HEAD
    assert historical["sentinel_only"] is True
    assert historical["request_blob_oid"] == (
        "f240997fccf2b0ef54d38e093ea21843272c6f5f"
    )
    assert historical["request_bytes"] == 25_763
    assert historical["request_raw_sha256"] == REQUEST_RAW_SHA256
    assert historical["request_payload_sha256"] == REQUEST_PAYLOAD_SHA256
    assert historical["freeze_sha256"] == reseal.D114_FREEZE_SHA256
    assert historical["run_id"] == 34_147_189_320
    assert historical["run_attempt"] == 1

    raw = _git_blob(EXECUTION_HEAD, reseal.D114_REQUEST_PATH)
    assert len(raw) == 25_763
    assert hashlib.sha256(raw).hexdigest() == REQUEST_RAW_SHA256
    request = json.loads(raw)
    assert request["request_sha256"] == f"sha256:{REQUEST_PAYLOAD_SHA256}"
    assert raw.endswith(b"\n") and b"\r" not in raw


def test_exec_014_failure_replay_separates_control_plane_from_science() -> None:
    replay = reseal.validate_failure_replay()
    assert replay["status"] == "PASS"
    assert replay["source_head"] == SOURCE_HEAD
    assert replay["execution_head"] == EXECUTION_HEAD
    assert replay["execution_run_id"] == 34_147_189_320
    assert replay["execution_run_attempt"] == 1
    assert replay["dependency_installations"] == 1
    assert replay["harness_materializations"] == 2
    assert replay["self_hosted_job_assignments"] == 1
    assert replay["protected_environment_entered"] is False
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


def test_failure_recovery_and_readiness_do_not_claim_a_result_or_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = reseal.current_failure_record()
    assert failure["workflow_run"] == {
        "attempt": 1,
        "conclusion": "failure",
        "head_sha": EXECUTION_HEAD,
        "id": 34_147_189_320,
        "source_head_sha": SOURCE_HEAD,
    }
    assert failure["failure_boundary"] == {
        "bounded_context_preflight": "FAILED_AT_EXACT_LOADER_GATE",
        "branch_trigger_preflight": "PASSED",
        "dependency_install_completed": True,
        "frozen_serial_phase": "SKIPPED",
        "harness_materialization_completed": True,
        "protected_environment_entered": False,
    }
    assert failure["observed_scientific_actuals"] == (
        reseal.ZERO_SCIENTIFIC_ACTUALS
    )
    assert failure["performance_measured"] is False
    assert failure["pass_at_1"] is None
    assert failure["process_disposition"] == {
        "attempt_one_consumed": True,
        "attempt_two_allowed": False,
        "request_014_rerun_allowed": False,
        "request_015_execution_authorized": False,
    }

    recovery = reseal.current_recovery_record()
    assert recovery["request_creation_authority_received"] is True
    assert recovery["actual_execution_authorized"] is False
    assert recovery["external_execution_approval_received"] is False
    assert recovery["request_present_in_recovery_source"] is False
    assert recovery["performance_measured"] is False
    historical_readiness = json.loads(
        _git_blob(
            D115_SOURCE_HEAD,
            "artifacts/trimem_v1/readiness_requirements.json",
        )
    )
    original_read_json = reseal.read_json
    monkeypatch.setattr(
        reseal,
        "read_json",
        lambda path: (
            historical_readiness
            if path == reseal.READINESS_PATH
            else original_read_json(path)
        ),
    )
    reseal.validate_readiness()


def test_changed_path_vocabulary_matches_trigger_and_excludes_science() -> None:
    assert reseal.ALLOWED_CHANGED_PATHS == trigger.ALLOWED_RECOVERY_PATHS
    assert reseal.REQUIRED_CHANGED_PATHS == trigger.REQUIRED_RECOVERY_CHANGES
    assert set(reseal.PRESERVED_SCIENTIFIC_PATHS).isdisjoint(
        reseal.GENERATED_PATHS
    )
    assert reseal.D114_REQUEST_PATH not in reseal.ALLOWED_CHANGED_PATHS
    assert reseal.D115_REQUEST_PATH not in reseal.ALLOWED_CHANGED_PATHS
    assert set(reseal.REQUIRED_CHANGED_PATHS) <= reseal.ALLOWED_CHANGED_PATHS
    assert {
        "scripts/trimem_benchmark_matrix.py": "M",
        "scripts/trimem_benchmark_run.py": "M",
        "scripts/trimem_multi_swe_contract.py": "M",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
    }.items() <= reseal.REQUIRED_CHANGED_PATHS.items()
    assert {
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
    } <= set(freeze.FROZEN_PATHS)
    assert trigger.ACTIVATION_BINDING_PATHS == {
        "gitattributes_sha256": ".gitattributes",
        "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
        "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
        "benchmark_workflow_sha256": trigger.EXPECTED_WORKFLOW_PATH,
        "compiled_prefix_alias_sha256": trigger.COMPILED_PREFIX_ALIAS_PATH,
        "loader_rehearsal_collector_sha256": (
            trigger.LOADER_REHEARSAL_COLLECTOR_PATH
        ),
        "multi_swe_contract_sha256": "scripts/trimem_multi_swe_contract.py",
        "d115_amendment_sha256": trigger.AMENDMENT_PATH,
        "d115_gate_contract_sha256": trigger.GATE_CONTRACT_PATH,
        "d115_inventory_sha256": trigger.INVENTORY_PATH,
        "d115_reseal_sha256": trigger.RESEAL_PATH,
        "d115_run_fixture_sha256": trigger.PREVIOUS_FAILURE_FIXTURE_PATH,
        "readiness_requirements_sha256": (
            "artifacts/trimem_v1/readiness_requirements.json"
        ),
        "trigger_reader_sha256": trigger.TRIGGER_PATH,
        "verify_ready_sha256": "scripts/trimem_verify_ready.py",
    }


def _live_active_contract_blob(_commit: str, relative: str) -> bytes:
    return _git_blob(D115_SOURCE_HEAD, relative)


def test_active_contract_accepts_exact_d115_consumer_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reseal, "git_blob", _live_active_contract_blob)
    observed = reseal.validate_active_contract("unused")
    assert observed["request_id"] == trigger.REQUEST_ID


@pytest.mark.parametrize(
    "tamper",
    (
        lambda source: source.replace(
            "from trimem_development_trigger_d115 import",
            "# from trimem_development_trigger_d115 import\n"
            "from trimem_development_trigger_d114 import",
            1,
        ),
        lambda source: source
        + "\nfrom trimem_development_trigger_d113 import SENTINEL_PATH\n",
        lambda source: source
        + "\nimport trimem_development_trigger_d114 as legacy_trigger\n",
        lambda source: source.replace(
            "    DevelopmentTriggerError,\n", "", 1
        ),
        lambda source: source
        + "\n__import__('trimem_development_trigger_d114')\n",
        lambda source: source + "\nif:\n",
    ),
)
def test_active_contract_rejects_non_exact_or_legacy_consumer_imports(
    monkeypatch: pytest.MonkeyPatch,
    tamper: Callable[[str], str],
) -> None:
    relative = "scripts/trimem_benchmark_matrix.py"
    original = _git_blob(D115_SOURCE_HEAD, relative).decode("utf-8")
    modified = tamper(original)

    def blob(_commit: str, requested: str) -> bytes:
        if requested == relative:
            return modified.encode("utf-8")
        return _live_active_contract_blob(_commit, requested)

    monkeypatch.setattr(reseal, "git_blob", blob)
    with pytest.raises(
        reseal.D115ResealError,
        match="D1.15 active request consumer",
    ):
        reseal.validate_active_contract("unused")


def test_spent_015_live_d115_reader_expires_fail_closed() -> None:
    with pytest.raises(
        trigger.DevelopmentTriggerError,
        match="exact loader rehearsal is stale or from the future",
    ):
        reseal.validate_optional_exec_015_boundary()


def test_report_freezes_exact_failure_fix_and_no_result_meaning() -> None:
    raw = REPORT.read_bytes()
    assert raw.startswith(b"# TriMem-Coder V1 D1.15")
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    required = (
        "34147189320",
        "attempt `1`",
        "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_NOT_READY",
        "CACHED_PYTHON_SYSCONFIG_LIBDIR_RELOCATION_FAIL_CLOSED",
        "CACHED_PYTHON_SYSCONFIG_LIBDIR_ALIAS_ABSENT",
        "/opt/hostedtoolcache",
        "/opt/trimem-runner-cache/work-ci/_tool",
        "NOT_REACHED_ON_EXEC_014",
        "PERFORMANCE",
        "TRIMEM_V1_READY_FOR_EXEC_015_REQUEST",
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015_APPROVED_ONCE",
    )
    for marker in required:
        assert marker in text


def test_freeze_contains_every_d115_authority_input() -> None:
    required = {
        "artifacts/trimem_v1/development_exec_015_recovery_amendment.json",
        "artifacts/trimem_v1/development_exec_015_recovery_inventory.json",
        "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_014.json",
        "reports/TRIMEM_D115_EXEC_015_RECOVERY.md",
        "scripts/trimem_compiled_prefix_alias.py",
        "scripts/trimem_d115_gate_contract.py",
        "scripts/trimem_d115_loader_rehearsal.py",
        "scripts/trimem_d115_reseal.py",
        "scripts/trimem_development_trigger_d115.py",
        "tests/fixtures/trimem_d115/exec_014_loader_failure.json",
        "tests/unit/test_trimem_d115_compiled_prefix_alias.py",
        "tests/unit/test_trimem_d115_gate_contract.py",
        "tests/unit/test_trimem_d115_status_and_reseal.py",
        "tests/unit/test_trimem_d115_trigger.py",
    }
    assert required <= set(freeze.FROZEN_PATHS)


def test_generated_documents_remain_exact_at_immutable_d115_source() -> None:
    first_amendment = json.loads(
        _git_blob(D115_SOURCE_HEAD, trigger.AMENDMENT_PATH)
    )
    first_inventory = json.loads(
        _git_blob(D115_SOURCE_HEAD, trigger.INVENTORY_PATH)
    )
    assert first_amendment["schema"] == reseal.AMENDMENT_SCHEMA
    assert first_inventory["schema"] == reseal.INVENTORY_SCHEMA
    assert first_amendment["status"] == reseal.STATUS
    assert first_inventory["status"] == reseal.STATUS
    assert first_amendment["classification"] == reseal.CLASSIFICATION
    assert first_inventory["classification"] == reseal.CLASSIFICATION
    assert first_amendment["implementation_sha256"] == first_inventory[
        "implementation_sha256"
    ]
    assert first_amendment["zero_scientific_recovery_actuals"] == (
        reseal.ZERO_SCIENTIFIC_ACTUALS
    )
    authority = first_amendment["authority_boundary"]
    assert authority["request_014_attempt_one_consumed"] is True
    assert authority["request_014_rerun_allowed"] is False
    assert authority["request_015_creation_authorized"] is True
    assert authority["request_015_execution_authorized"] is False
    assert authority["actual_execution_authorized"] is False
    assert authority["external_execution_approval_received"] is False


def test_reseal_source_does_not_embed_mutable_d115_source_head() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def source_bytes(" in source
    assert "return git_blob(selected, relative)" in source
    assert "D115_SOURCE_HEAD =" not in source
