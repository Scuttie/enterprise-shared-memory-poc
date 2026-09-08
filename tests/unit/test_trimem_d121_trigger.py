from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_d121_reseal as reseal
import trimem_development_trigger_d120 as d120
import trimem_development_trigger_d121 as d121
import trimem_development_trigger_d122 as d122


def _fixture_bytes() -> bytes:
    return (ROOT / d121.PREVIOUS_FAILURE_FIXTURE_PATH).read_bytes()


def test_d121_exact_active_and_historical_identities() -> None:
    assert d121.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"
    assert d121.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.21"
    assert d121.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_021.json")
    assert d121.PREVIOUS_SOURCE_HEAD == "138619d5d5e83009c3c22a4d9619a9394b0b59a1"
    assert d121.PREVIOUS_EXECUTION_HEAD == "f15371a612d6c35acabe56e7d3196429b95ca3bb"
    assert d121.PREVIOUS_SENTINEL_SHA256 == (
        "c177d9664972eaa128c3d7efe6666c192c2666912fd52b258364944fa3ad2665"
    )
    assert d121.PREVIOUS_SENTINEL_BYTES == 49_618
    assert d121.PREVIOUS_RUN_ID == 34_240_675_412
    assert d121.PREVIOUS_RUN_ATTEMPT == 1
    assert d121.REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021_APPROVED_ONCE"
    )
    completed = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{d121.PREVIOUS_EXECUTION_HEAD}:{d121.PREVIOUS_SENTINEL_PATH}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == d121.PREVIOUS_SENTINEL_BLOB_OID


def test_d121_fixture_is_exact_and_replays_scientific_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _fixture_bytes()
    assert len(raw) == d121.PREVIOUS_FAILURE_FIXTURE_BYTES
    assert hashlib.sha256(raw).hexdigest() == d121.PREVIOUS_FAILURE_FIXTURE_SHA256
    monkeypatch.setattr(d121, "commit_bytes", lambda *_args: raw)
    observed = d121._validate_previous_run_fixture(
        ROOT, d121.PREVIOUS_EXECUTION_HEAD
    )
    assert observed["performance_measured"] is False
    assert observed["pass_at_1"] is None
    assert observed["scientific_cell"]["fail_to_pass"]["failure_count"] == 0
    assert observed["scientific_cell"]["pass_to_pass"]["failure_count"] == 1
    assert observed["scientific_cell"]["computed_resolved"] is False
    assert observed["scientific_cell"]["scientific_outcome"] == "UNRESOLVED"
    assert observed["scientific_cell"]["harness_exit_code"] == 0
    assert observed["actuals"] == d121.HISTORICAL_EXECUTION_ACTUALS


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value["scientific_cell"]["fail_to_pass"].__setitem__(
            "failure_count", 1
        ),
        lambda value: value["scientific_cell"]["pass_to_pass"].__setitem__(
            "failure_count", 0
        ),
        lambda value: value["scientific_cell"].__setitem__("computed_resolved", True),
        lambda value: value["scientific_cell"].__setitem__("harness_exit_code", 1),
        lambda value: value["actuals"].__setitem__("paid_model_calls", 17),
        lambda value: value["actuals"].__setitem__("reasoning_tokens", 0),
        lambda value: value["observed_failure"].__setitem__(
            "request_020_rerun_allowed", True
        ),
        lambda value: value.__setitem__("performance_measured", True),
        lambda value: value.__setitem__("pass_at_1", 0.0),
    ),
)
def test_d121_fixture_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch, mutation: object
) -> None:
    modified = deepcopy(json.loads(_fixture_bytes()))
    assert callable(mutation)
    mutation(modified)
    raw = (
        json.dumps(modified, ensure_ascii=False, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    monkeypatch.setattr(d121, "commit_bytes", lambda *_args: raw)
    with pytest.raises(d121.DevelopmentTriggerError):
        d121._validate_previous_run_fixture(ROOT, d121.PREVIOUS_EXECUTION_HEAD)


def test_d121_accounting_separates_science_canary_and_unknown_reasoning() -> None:
    science = d121.SCIENTIFIC_EXECUTION_ACTUALS
    canary = d121.CANARY_EXECUTION_ACTUALS
    total = d121.HISTORICAL_EXECUTION_ACTUALS
    assert science["model_generation_calls"] == 17
    assert science["decomposition_calls"] == 1
    assert science["solve_calls"] == 16
    assert science["extraction_calls"] == 0
    assert science["input_tokens"] == 142_200
    assert science["cached_input_tokens"] == 0
    assert science["output_tokens"] == 6_416
    assert science["total_usd"] == "0.135522000000"
    assert canary["model_generation_calls"] == 1
    assert canary["input_tokens"] == 950
    assert canary["output_tokens"] == 28
    assert canary["total_usd"] == "0.000838500000"
    assert total["model_generation_calls"] == 18
    assert total["input_tokens"] == 143_150
    assert total["output_tokens"] == 6_444
    assert total["total_usd"] == "0.136360500000"
    assert total["reasoning_tokens"] is None
    assert total["reasoning_tokens_status"] == "UNAVAILABLE_NOT_INFERRED"
    assert total["terminal_cells"] == 0
    assert total["task_arm_runs"] == 0
    assert all(value == 0 for value in d121.ZERO_CURRENT_EXECUTION_ACTUALS.values())


def test_d121_context_propagates_and_restores_inherited_bindings() -> None:
    modules = (d120, d121.d119, d121.d118, d121.d115)
    before = {
        module: (module.REQUEST_ID, module.REQUEST_SCHEMA, module.SENTINEL_PATH)
        for module in modules
    }
    with d121._d121_runtime_context():
        for module in modules:
            assert module.REQUEST_ID == d121.REQUEST_ID
            assert module.REQUEST_SCHEMA == d121.REQUEST_SCHEMA
            assert module.SENTINEL_PATH == d121.SENTINEL_PATH
        assert d121.d118.RUNNER_READINESS_SCHEMA == d121.RUNNER_READINESS_SCHEMA
    for module in modules:
        assert (module.REQUEST_ID, module.REQUEST_SCHEMA, module.SENTINEL_PATH) == before[
            module
        ]


def test_d121_context_cannot_mutate_an_active_d120_context() -> None:
    attempted = threading.Event()
    entered = threading.Event()
    observations: list[str] = []

    def enter_d121() -> None:
        attempted.set()
        with d121._d121_runtime_context():
            observations.append(d120.REQUEST_ID)
            entered.set()

    with d120._d120_runtime_context():
        worker = threading.Thread(target=enter_d121, daemon=True)
        worker.start()
        assert attempted.wait(timeout=1)
        assert not entered.wait(timeout=0.2)
        assert d120.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020"

    assert entered.wait(timeout=2)
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert observations == [d121.REQUEST_ID]
    assert d120.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020"


def test_d121_outcome_contract_is_narrow_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        d120,
        "_request_execution_contracts",
        lambda _bindings: {"contract_bindings": {}},
    )
    bindings = {
        "benchmark_matrix_sha256": "sha256:" + "a" * 64,
        "official_grader_sha256": "sha256:" + "b" * 64,
    }
    contracts = d121._request_execution_contracts(bindings)
    assert contracts["swe_official_result_normalization"] == (
        d121.OUTCOME_NORMALIZATION_CONTRACT
    )
    assert contracts["swe_official_result_normalization"][
        "pass_to_pass_regression_is_valid_scientific_unresolved"
    ] is True
    assert contracts["swe_official_result_normalization"][
        "adapter_and_infrastructure_failures_remain_fail_closed"
    ] is True
    assert contracts["contract_bindings"] == bindings


def test_d121_current_records_keep_no_score_and_zero_new_authority() -> None:
    failure = d121.current_failure_record()
    recovery = d121.current_recovery_record()
    assert failure["pass_at_1"] is None
    assert failure["performance_measured"] is False
    assert failure["official_scientific_outcome"] == {
        "fail_to_pass_failures": 0,
        "pass_to_pass_regressions": 1,
        "resolved": False,
        "status": "UNRESOLVED",
    }
    assert failure["failure_boundary"]["terminal_cells"] == 0
    assert recovery["consumed_exec_020_actuals"] == (
        d121.HISTORICAL_EXECUTION_ACTUALS
    )
    assert all(value == 0 for value in recovery["current_execution_actuals"].values())
    assert recovery["actual_execution_authorized"] is False
    assert recovery["endpoint"] == "TRIMEM_V1_READY_FOR_EXEC_021_REQUEST"


def test_d121_recovery_scope_preserves_science_and_excludes_sentinels() -> None:
    forbidden = {
        ".gitattributes",
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/model_lock.json",
        d120.AMENDMENT_PATH,
        d120.INVENTORY_PATH,
        d120.PREVIOUS_FAILURE_FIXTURE_PATH,
        d120.TRIGGER_PATH,
        d121.PREVIOUS_SENTINEL_PATH,
        d121.SENTINEL_PATH,
    }
    assert forbidden.isdisjoint(d121.ALLOWED_RECOVERY_PATHS)
    assert set(d121.REQUIRED_RECOVERY_CHANGES) <= d121.ALLOWED_RECOVERY_PATHS


def test_d121_report_and_reseal_freeze_exact_boundary() -> None:
    text = (ROOT / d121.REPORT_PATH).read_text(encoding="utf-8")
    for marker in (
        "34240675412",
        "PASS_TO_PASS",
        "UNRESOLVED",
        "17 paid generation calls",
        "$0.135522000000",
        "$0.136360500000",
        "UNAVAILABLE_NOT_INFERRED",
        "TRIMEM_V1_READY_FOR_EXEC_021_REQUEST",
        "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021_APPROVED_ONCE",
    ):
        assert marker in text
    fixture = reseal.validate_fixture()
    assert fixture["scientific_cell"]["computed_resolved"] is False


def test_d121_history_has_one_exact_spent_exec_021() -> None:
    request = d121.validate_sentinel_commit(
        ROOT,
        d122.PREVIOUS_EXECUTION_HEAD,
        expected_parent=d122.PREVIOUS_SOURCE_HEAD,
        require_checked_out_head=False,
    )
    assert request["request_id"] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"
    assert request["request_path"] == d122.PREVIOUS_SENTINEL_PATH
    assert request["source_head"] == d122.PREVIOUS_SOURCE_HEAD
    assert not (ROOT / d122.FUTURE_SENTINEL_PATH).exists()
