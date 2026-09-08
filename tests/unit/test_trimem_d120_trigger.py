from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d119 as d119
import trimem_development_trigger_d120 as d120
import trimem_development_trigger_d121 as d121
import trimem_development_trigger_d122 as d122
import trimem_d120_loader_rehearsal as d120_collector


def _fixture_bytes() -> bytes:
    return (ROOT / d120.PREVIOUS_FAILURE_FIXTURE_PATH).read_bytes()


def test_d120_exact_active_and_historical_identities() -> None:
    assert d120.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020"
    assert d120.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.20"
    assert d120.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_020.json")
    assert d120.PREVIOUS_SOURCE_HEAD == "df93cdbcf0d8e30014035e79cf5d7d52848d5072"
    assert d120.PREVIOUS_EXECUTION_HEAD == "f3053cddc6b32c2b51ef7de5a6ccf0d95ea578c2"
    assert d120.PREVIOUS_SENTINEL_SHA256 == (
        "534d8500073ae414fa7839b6af7c88bdcc88dbb28997066826ba18ebe8868c4e"
    )
    assert d120.PREVIOUS_RUN_ID == 34_223_706_155
    assert d120.PREVIOUS_RUN_ATTEMPT == 1
    assert (
        d120.REQUIRED_EXTERNAL_AUTHORIZATION
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020_APPROVED_ONCE"
    )
    completed = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{d120.PREVIOUS_EXECUTION_HEAD}:{d120.PREVIOUS_SENTINEL_PATH}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == d120.PREVIOUS_SENTINEL_BLOB_OID
    previous = d120._load_previous_request(ROOT, d120.PREVIOUS_EXECUTION_HEAD)
    assert previous["request_sha256"] == (
        "sha256:" + d120.PREVIOUS_REQUEST_PAYLOAD_SHA256
    )
    assert previous["bindings"]["freeze_sha256"] == (
        "sha256:" + d120.PREVIOUS_SOURCE_FREEZE_SHA256
    )


def test_d121_freeze_preserves_immutable_exec_019_and_exec_020() -> None:
    freeze = json.loads((ROOT / d120.FREEZE_PATH).read_bytes())
    files = freeze["files"]
    previous_raw = (ROOT / d120.PREVIOUS_SENTINEL_PATH).read_bytes()
    exec_020_raw = (ROOT / d120.SENTINEL_PATH).read_bytes()

    assert files[d120.PREVIOUS_SENTINEL_PATH] == {
        "bytes": len(previous_raw),
        "sha256": hashlib.sha256(previous_raw).hexdigest(),
    }
    assert files[d120.SENTINEL_PATH] == {
        "bytes": d121.PREVIOUS_SENTINEL_BYTES,
        "sha256": d121.PREVIOUS_SENTINEL_SHA256,
    }
    assert len(exec_020_raw) == d121.PREVIOUS_SENTINEL_BYTES
    assert hashlib.sha256(exec_020_raw).hexdigest() == d121.PREVIOUS_SENTINEL_SHA256
    assert d121.SENTINEL_PATH not in files


def test_d120_fixture_is_exact_and_replays_partial_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _fixture_bytes()
    assert len(raw) == d120.PREVIOUS_FAILURE_FIXTURE_BYTES
    assert hashlib.sha256(raw).hexdigest() == d120.PREVIOUS_FAILURE_FIXTURE_SHA256
    monkeypatch.setattr(d120, "commit_bytes", lambda *_args: raw)
    observed = d120._validate_previous_run_fixture(
        ROOT, d120.PREVIOUS_EXECUTION_HEAD
    )
    assert observed["performance_measured"] is False
    assert observed["pass_at_1"] is None
    assert observed["actuals"] == d120.HISTORICAL_EXECUTION_ACTUALS
    assert observed["actuals"]["paid_model_calls"] == 19
    assert observed["actuals"]["scientific_model_calls"] == 18
    assert observed["actuals"]["grader_containers"] == 1
    assert observed["first_terminal_cell"]["resolved"] is True
    assert observed["second_cell_boundary"]["model_calls"] == 0


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value["actuals"].__setitem__("paid_model_calls", 18),
        lambda value: value["actuals"].__setitem__("total_usd", "0.155753550001"),
        lambda value: value.__setitem__("performance_measured", True),
        lambda value: value.__setitem__("pass_at_1", 1.0),
        lambda value: value["failure"].__setitem__("resume_eligible", True),
        lambda value: value["first_terminal_cell"].__setitem__("resolved", False),
        lambda value: value["second_cell_boundary"].__setitem__("model_calls", 1),
        lambda value: value["root_cause"].__setitem__(
            "classification", "SCIENTIFIC_MODEL_FAILURE"
        ),
        lambda value: value["root_cause"]["recovery_contract"].__setitem__(
            "pristine_checkout_validation_preserved", False
        ),
    ),
)
def test_d120_fixture_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch, mutation: object
) -> None:
    modified = deepcopy(json.loads(_fixture_bytes()))
    assert callable(mutation)
    mutation(modified)
    raw = (
        json.dumps(modified, ensure_ascii=False, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    monkeypatch.setattr(d120, "commit_bytes", lambda *_args: raw)
    with pytest.raises(d120.DevelopmentTriggerError):
        d120._validate_previous_run_fixture(ROOT, d120.PREVIOUS_EXECUTION_HEAD)


def test_d120_accounting_separates_canary_science_and_current_zero() -> None:
    actuals = d120.HISTORICAL_EXECUTION_ACTUALS
    assert actuals["protocol_canary_generation_calls"] == 1
    assert actuals["scientific_model_calls"] == 18
    assert actuals["model_generation_calls"] == 19
    assert actuals["decomposition_calls"] == 1
    assert actuals["solve_calls"] == 16
    assert actuals["extraction_calls"] == 1
    assert actuals["input_tokens"] == 178_497
    assert actuals["cached_input_tokens"] == 1_664
    assert actuals["output_tokens"] == 5_112
    assert actuals["reasoning_tokens"] == 2_853
    assert actuals["total_usd"] == "0.155753550000"
    assert all(value == 0 for value in d120.ZERO_CURRENT_EXECUTION_ACTUALS.values())
    assert d119.HISTORICAL_EXECUTION_ACTUALS["paid_model_calls"] == 0


def test_d120_context_propagates_and_restores_inherited_bindings() -> None:
    modules = (d119, d120.d118, d120.d115, d120.d114)
    missing = object()
    before = {
        module: (
            module.REQUEST_ID,
            module.REQUEST_SCHEMA,
            module.SENTINEL_PATH,
            getattr(module, "LOADER_REHEARSAL_COLLECTOR_PATH", missing),
        )
        for module in modules
    }

    with d120._d120_runtime_context():
        for module in modules:
            assert module.REQUEST_ID == d120.REQUEST_ID
            assert module.REQUEST_SCHEMA == d120.REQUEST_SCHEMA
            assert module.SENTINEL_PATH == d120.SENTINEL_PATH
        for module in (d119, d120.d118, d120.d115):
            assert (
                module.LOADER_REHEARSAL_COLLECTOR_PATH
                == d120.LOADER_REHEARSAL_COLLECTOR_PATH
            )
        assert d120.d118.RUNNER_READINESS_SCHEMA == d120.RUNNER_READINESS_SCHEMA

    for module in modules:
        assert (
            module.REQUEST_ID,
            module.REQUEST_SCHEMA,
            module.SENTINEL_PATH,
            getattr(module, "LOADER_REHEARSAL_COLLECTOR_PATH", missing),
        ) == before[module]


def test_d120_loader_subprocess_wrapper_binds_parent_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[object, object, object, object]] = []

    def parent_main(argv: object = None) -> int:
        observed.append(
            (
                argv,
                d120.d118.RUNNER_READINESS_SCHEMA,
                d120.d115.RUNNER_READINESS_SCHEMA,
                d120.d115.LOADER_REHEARSAL_COLLECTOR_PATH,
            )
        )
        return 31

    monkeypatch.setattr(d120_collector.d115_collector, "main", parent_main)
    argv = ["--synthetic"]
    assert d120_collector.main(argv) == 31
    assert observed == [
        (
            argv,
            d120.RUNNER_READINESS_SCHEMA,
            d120.RUNNER_READINESS_SCHEMA,
            d120.LOADER_REHEARSAL_COLLECTOR_PATH,
        )
    ]


def test_d120_reuses_strict_d119_byte_approval_producer() -> None:
    assert d120.APPROVAL_SECRET_PATH == "scripts/trimem_d119_approval_secret.py"
    assert d120.APPROVAL_SECRET_PATH not in d120.REQUIRED_RECOVERY_CHANGES
    assert d120.APPROVAL_SECRET_PATH not in d120.ALLOWED_RECOVERY_PATHS
    source = (ROOT / d120.APPROVAL_SECRET_PATH).read_text(encoding="utf-8")
    assert "write_bytes" in source
    assert "base64.b64decode(encoded, validate=True)" in source


def test_d120_current_records_separate_consumed_and_current_actuals() -> None:
    failure = d120.current_failure_record()
    recovery = d120.current_recovery_record()
    assert failure["pass_at_1"] is None
    assert failure["performance_measured"] is False
    assert failure["observed_execution_actuals"] == d120.HISTORICAL_EXECUTION_ACTUALS
    assert failure["failure_boundary"]["scientific_model_calls"] == 18
    assert failure["failure_boundary"]["terminal_cells"] == 1
    assert recovery["consumed_exec_019_actuals"] == d120.HISTORICAL_EXECUTION_ACTUALS
    assert all(value == 0 for value in recovery["current_execution_actuals"].values())
    assert recovery["actual_execution_authorized"] is False
    assert recovery["endpoint"] == "TRIMEM_V1_READY_FOR_EXEC_020_REQUEST"


def test_d120_contract_adds_runtime_isolation_without_weakening_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        d119,
        "_request_execution_contracts",
        lambda _bindings: {"contract_bindings": {}},
    )
    bindings = {
        "official_grader_sha256": "sha256:" + "a" * 64,
        "official_harness_loader_preflight_sha256": "sha256:" + "b" * 64,
        "swe_bench_entrypoint_sha256": "sha256:" + "c" * 64,
    }
    contracts = d120._request_execution_contracts(bindings)
    assert contracts["official_harness_runtime_isolation"] == {
        "frozen_harness_checkout_never_used_as_runtime_cwd": True,
        "pinned_harness_import_root_preserved": True,
        "pristine_checkout_validation_preserved": True,
        "runtime_output_directory_unique_per_task_arm_cell": True,
        "sequential_swe_cells_rehearsed": True,
    }
    assert contracts["contract_bindings"] == bindings


def test_d120_recovery_scope_excludes_science_and_historical_d119() -> None:
    forbidden = {
        ".gitattributes",
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/model_lock.json",
        d119.AMENDMENT_PATH,
        d119.INVENTORY_PATH,
        d119.PREVIOUS_FAILURE_FIXTURE_PATH,
        d119.LOADER_REHEARSAL_COLLECTOR_PATH,
        d119.TRIGGER_PATH,
    }
    assert forbidden.isdisjoint(d120.ALLOWED_RECOVERY_PATHS)


def test_d121_history_validates_spent_exec_020_and_exact_exec_021() -> None:
    request_020 = d120.validate_sentinel_commit(
        ROOT,
        d121.PREVIOUS_EXECUTION_HEAD,
        expected_parent=d121.PREVIOUS_SOURCE_HEAD,
        require_checked_out_head=False,
    )
    assert request_020["request_id"] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020"
    assert request_020["source_head"] == d121.PREVIOUS_SOURCE_HEAD
    request_021 = d121.validate_sentinel_commit(
        ROOT,
        d122.PREVIOUS_EXECUTION_HEAD,
        expected_parent=d122.PREVIOUS_SOURCE_HEAD,
        require_checked_out_head=False,
    )
    assert request_021["request_id"] == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"
    assert request_021["source_head"] == d122.PREVIOUS_SOURCE_HEAD
    assert request_021["request_path"] == d122.PREVIOUS_SENTINEL_PATH
