from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d123_reseal as d123_reseal  # noqa: E402
import trimem_development_trigger_d122 as d122  # noqa: E402
import trimem_development_trigger_d123 as d123  # noqa: E402


def test_d122_exact_spent_exec_021_identity() -> None:
    assert d122.PREVIOUS_SOURCE_HEAD == "a171bce0b883d4cc93b893a6d47944a84a947897"
    assert d122.PREVIOUS_EXECUTION_HEAD == "f83eab1e777f803c08e1ed86baac17c97111c546"
    assert d122.PREVIOUS_RUN_ID == 34_257_490_991
    assert d122.PREVIOUS_RUN_ATTEMPT == 1
    assert d122.PREVIOUS_SENTINEL_BYTES == 51_376
    assert d122.PREVIOUS_SENTINEL_SHA256 == (
        "986cfe25514a8bf5594a8047f0bc11edd0419813739dbec02da702ab5da71e75"
    )
    assert d122.PREVIOUS_SENTINEL_BLOB_OID == (
        "994bd4058c45a9988d55c5cabc92b823474ddcf9"
    )
    request = d122.validate_previous_request(ROOT)
    assert request["request_id"] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"
    assert request["source_head"] == d122.PREVIOUS_SOURCE_HEAD


def test_d122_fixture_is_exact_no_score_and_non_aggregatable() -> None:
    raw = (ROOT / d122.FAILURE_FIXTURE_PATH).read_bytes()
    assert len(raw) == d122.FAILURE_FIXTURE_BYTES
    assert hashlib.sha256(raw).hexdigest() == d122.FAILURE_FIXTURE_SHA256
    fixture = d122.validate_failure_fixture(ROOT)
    assert fixture["pass_at_1"] is None
    assert fixture["performance_measured"] is False
    assert fixture["scientific_status"] == (
        "PARTIAL_TWENTY_FOUR_OF_SEVENTY_TWO_NO_CAMPAIGN_SCORE"
    )
    partial = fixture["frozen_partial_outcome"]
    assert partial["terminal_cell_journals"] == 24
    assert partial["terminal_result_documents"] == 24
    assert partial["aggregate_available"] is False
    assert partial["candidate_selection_available"] is False
    assert partial["streams"]["M2-baseline"]["terminal_cells"] == 12
    assert partial["streams"]["M2-precision"]["terminal_cells"] == 12
    assert partial["streams"]["M2-recall"]["terminal_cells"] == 0
    assert partial["streams"]["M2-recall"]["task_arm_reservations"] == 0


def test_d122_exact_accounting_separates_science_canary_and_whole() -> None:
    science = d122.SCIENTIFIC_EXECUTION_ACTUALS
    canary = d122.CANARY_EXECUTION_ACTUALS
    whole = d122.HISTORICAL_EXECUTION_ACTUALS
    assert science["model_generation_calls"] == (
        science["decomposition_calls"]
        + science["solve_calls"]
        + science["extraction_calls"]
    ) == 247
    assert whole["model_generation_calls"] == (
        science["model_generation_calls"] + canary["model_generation_calls"]
    ) == 248
    assert whole["input_tokens"] == science["input_tokens"] + canary["input_tokens"]
    assert whole["output_tokens"] == science["output_tokens"] + canary["output_tokens"]
    assert whole["reasoning_tokens"] == (
        science["reasoning_tokens"] + canary["reasoning_tokens"]
    )
    assert Decimal(str(whole["total_usd"])) == (
        Decimal(str(science["total_usd"])) + Decimal(str(canary["total_usd"]))
    )
    assert whole["task_arm_runs"] == 24
    assert whole["grader_containers"] == 24
    assert whole["resolved_cells"] == 2
    assert whole["unresolved_cells"] == 22
    assert all(value == 0 for value in d122.OUTSTANDING_RESERVATIONS.values())
    assert all(value == 0 for value in d122.ZERO_CURRENT_EXECUTION_ACTUALS.values())


def test_d122_resume_and_authority_boundary_is_fail_closed() -> None:
    boundary = d122.RECOVERY_BOUNDARY
    assert boundary["request_021_attempt_one_consumed"] is True
    assert boundary["request_021_attempt_two_allowed"] is False
    assert boundary["request_021_rerun_allowed"] is False
    assert boundary["resume_eligible"] is False
    assert boundary["resume_reason"] == "FIRST_DISPOSITION_NOT_RESUME_SAFE"
    assert boundary["resume_started"] is False
    assert boundary["cross_run_resume_allowed"] is False
    assert boundary["historical_partial_results_reusable_for_new_campaign"] is False
    assert boundary["partial_candidate_checkpoint_selection_allowed"] is False
    assert boundary["new_campaign_starts_at_sequence_zero"] is True
    assert boundary["request_022_creation_authorized"] is False
    assert boundary["request_022_execution_authorized"] is False
    assert not hasattr(d122, "write_request")
    future = ROOT / d122.FUTURE_SENTINEL_PATH
    if future.exists():
        with pytest.raises(d122.D122RecoveryError, match="unauthorized"):
            d122.validate_no_exec_022(ROOT)
        with pytest.raises(
            d123.DevelopmentTriggerError,
            match="commits exist after the active `_022` request",
        ):
            d123.validate_optional_exec_022_boundary(ROOT)
    else:
        d122.validate_no_exec_022(ROOT)
        assert d123.validate_optional_exec_022_boundary(ROOT) is None


def test_d122_qdrant_contract_is_exact_and_source_enforced() -> None:
    assert d122.validate_qdrant_source_contract() == {
        "applies_only_to": "qdrant",
        "docker_create_argument": "nofile=65535:65535",
        "docker_inspect_exact_match_required": True,
        "hard": 65_535,
        "pid1_proc_limits_exact_match_required": True,
        "soft": 65_535,
        "state_bound_cleanup_rejects_drift_before_mutation": True,
        "state_free_cleanup_rejects_drift_before_mutation": True,
    }


def test_d122_reseal_builds_pending_no_authority_artifacts() -> None:
    baseline = d123_reseal.validate_d122_baseline()
    assert baseline["source_head"] == d123_reseal.D122_BASELINE_HEAD
    assert baseline["status"] == "PASS"
    amendment = json.loads((ROOT / d122.AMENDMENT_PATH).read_text(encoding="utf-8"))
    inventory = json.loads((ROOT / d122.INVENTORY_PATH).read_text(encoding="utf-8"))
    assert amendment["schema"] == d122.AMENDMENT_SCHEMA
    assert inventory["schema"] == d122.INVENTORY_SCHEMA
    assert amendment["status"] == d122.AMENDMENT_STATUS
    assert "READY" not in amendment["status"]
    assert amendment["endpoint"] == "QDRANT_RLIMIT_NOFILE_PORTABILITY_FAILURE"
    assert amendment["pass_at_1"] is None
    assert amendment["performance_measured"] is False
    assert amendment["consumed_execution_actuals"] == (
        d122.HISTORICAL_EXECUTION_ACTUALS
    )
    assert amendment["current_execution_actuals"] == (
        d122.ZERO_CURRENT_EXECUTION_ACTUALS
    )
    assert amendment["rehearsal"]["status"] == (
        "REQUIRED_NOT_EXECUTED_BY_SOURCE_SEAL"
    )
    assert amendment["authority_boundary"]["request_022_creation_authorized"] is False
    assert amendment["authority_boundary"]["request_022_execution_authorized"] is False
    assert amendment["implementation_sha256"] == inventory["implementation_sha256"]
    assert set(amendment["implementation_sha256"]) == d122.IMPLEMENTATION_SEAL_PATHS


def test_d122_scope_excludes_science_and_paid_dispatch_route() -> None:
    forbidden = {
        ".github/workflows/trimem-benchmark.yml",
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_official_grader.py",
        "scripts/trimem_run_with_resume.py",
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/model_lock.json",
        d122.PREVIOUS_SENTINEL_PATH,
        d122.FUTURE_SENTINEL_PATH,
    }
    assert forbidden.isdisjoint(d122.ALLOWED_RECOVERY_PATHS)
    assert set(d122.REQUIRED_RECOVERY_CHANGES) <= d122.ALLOWED_RECOVERY_PATHS
    assert set(d122.PRESERVED_SCIENTIFIC_PATHS).isdisjoint(
        d122.ALLOWED_RECOVERY_PATHS
    )


def test_d122_report_states_exact_pending_boundary() -> None:
    text = (ROOT / d122.REPORT_PATH).read_text(encoding="utf-8")
    for marker in (
        "34257490991",
        "QDRANT_RLIMIT_NOFILE_PORTABILITY_FAILURE",
        "RECOVERY_PENDING_REHEARSAL",
        "24 terminal cells",
        "UNKNOWN_FAILURE",
        "FIRST_DISPOSITION_NOT_RESUME_SAFE",
        "247 paid/model generation calls",
        "$1.546621950000",
        "$1.548175950000",
        "--ulimit nofile=65535:65535",
        "request-creation authority",
    ):
        assert marker in text
    assert "Pass@1`" in text
    assert "not a benchmark score" in text


def test_d122_fixture_json_contains_no_credential_material() -> None:
    value = json.loads((ROOT / d122.FAILURE_FIXTURE_PATH).read_text(encoding="utf-8"))
    serialized = json.dumps(value, sort_keys=True)
    for forbidden in (
        "OPENAI_API_KEY",
        "TRIMEM_EXEC_APPROVAL_B64",
        "TRIMEM_EVIDENCE_PASSPHRASE",
        "sk-proj-",
    ):
        assert forbidden not in serialized
