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

import trimem_d118_loader_rehearsal as d118_collector
import trimem_development_trigger_d117 as d117
import trimem_development_trigger_d118 as d118


def _fixture_bytes() -> bytes:
    return (ROOT / d118.PREVIOUS_FAILURE_FIXTURE_PATH).read_bytes()


def _synthetic_checkout() -> dict[str, object]:
    rows = []
    for (
        target_id,
        tree,
        regular_blob_count,
        normalized_count,
        path_set_sha256,
    ) in d118.EXPECTED_CHECKOUT_MATERIALIZATION:
        normalized_paths: list[str] = []
        if normalized_count:
            normalized_paths = [f"normalized/{index:03d}.txt" for index in range(normalized_count)]
            path_set_sha256 = hashlib.sha256(
                d118.canonical_bytes(normalized_paths)
            ).hexdigest()
        rows.append(
            {
                "commit": "a" * 40,
                "git_tree": tree,
                "normalized_path_count": normalized_count,
                "normalized_path_set_sha256": path_set_sha256,
                "normalized_paths": normalized_paths,
                "regular_blob_count": regular_blob_count,
                "status": "PASS",
                "strict_raw_blob_validation": "PASS",
                "target_id": target_id,
            }
        )
    return {
        "credential_access": False,
        "grader_containers": 0,
        "image_pulls": 0,
        "model_calls": 0,
        "normalized_path_count": 31,
        "official_grader_runs": 0,
        "regular_blob_count": 54_544,
        "schema": d118.CHECKOUT_REHEARSAL_SCHEMA,
        "source_identity": "PINNED_GIT_BLOB_BYTES_AT_REVISION",
        "split": "DEVELOPMENT_TUNING",
        "status": "PASS",
        "target_count": 12,
        "targets": rows,
        "task_arm_runs": 0,
        "transform_rule": "COMMITTED_TEXT_SET_EOL_CRLF_ONLY",
    }


def test_d118_exact_active_and_historical_identities() -> None:
    assert d118.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_018"
    assert d118.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.18"
    assert d118.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_018.json")
    assert d118.PREVIOUS_SOURCE_HEAD == "f1cfcbcbeff9a75bb118c3ee53ad1c3c36f7ff5f"
    assert d118.PREVIOUS_EXECUTION_HEAD == "63ed76143267b25d9086ed3b33d338bf368aa3fa"
    assert d118.PREVIOUS_RUN_ID == 34_200_331_390
    assert (
        d118.REQUIRED_EXTERNAL_AUTHORIZATION
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_018_APPROVED_ONCE"
    )
    completed = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{d118.PREVIOUS_EXECUTION_HEAD}:{d118.PREVIOUS_SENTINEL_PATH}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == d118.PREVIOUS_SENTINEL_BLOB_OID
    assert d118._load_previous_request(
        ROOT, d118.PREVIOUS_EXECUTION_HEAD
    )["request_sha256"] == "sha256:" + d118.PREVIOUS_REQUEST_PAYLOAD_SHA256


def test_d118_fixture_is_exact_and_replays_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _fixture_bytes()
    assert len(raw) == d118.PREVIOUS_FAILURE_FIXTURE_BYTES
    assert hashlib.sha256(raw).hexdigest() == d118.PREVIOUS_FAILURE_FIXTURE_SHA256
    monkeypatch.setattr(d118, "commit_bytes", lambda *_args: raw)
    observed = d118._validate_previous_run_fixture(
        ROOT, d118.PREVIOUS_EXECUTION_HEAD
    )
    assert observed["performance_measured"] is False
    assert observed["pass_at_1"] is None
    assert observed["actuals"] == d118.HISTORICAL_EXECUTION_ACTUALS


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value["actuals"].__setitem__("paid_model_calls", 17),
        lambda value: value["actuals"].__setitem__("total_usd", "0.000000000000"),
        lambda value: value.__setitem__("performance_measured", True),
        lambda value: value.__setitem__("pass_at_1", 0.0),
        lambda value: value["failure"].__setitem__("process_disposition", "RETRYABLE"),
        lambda value: value["root_cause"]["identity"].__setitem__(
            "runtime_launcher_directly_observed", True
        ),
        lambda value: value["root_cause"]["recovery_contract"].__setitem__(
            "factory_reuses_preflight_lexical_launcher", False
        ),
        lambda value: value["approval_boundary"].__setitem__(
            "environment_secret_count_after_cleanup", 1
        ),
    ),
)
def test_d118_fixture_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch, mutation: object
) -> None:
    modified = deepcopy(json.loads(_fixture_bytes()))
    assert callable(mutation)
    mutation(modified)
    raw = (
        json.dumps(modified, ensure_ascii=False, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    monkeypatch.setattr(d118, "commit_bytes", lambda *_args: raw)
    with pytest.raises(d118.DevelopmentTriggerError):
        d118._validate_previous_run_fixture(ROOT, d118.PREVIOUS_EXECUTION_HEAD)


def test_d118_historical_accounting_separates_partial_science_and_grader() -> None:
    actual = d118.HISTORICAL_EXECUTION_ACTUALS
    assert actual["provider_control_plane_requests"] == 1
    assert actual["protocol_canary_generation_calls"] == 1
    assert actual["scientific_model_calls"] == 17
    assert actual["decomposition_calls"] == 1
    assert actual["solve_calls"] == 16
    assert actual["extraction_calls"] == 0
    assert actual["paid_model_calls"] == 18
    assert actual["input_tokens"] == 197_498
    assert actual["output_tokens"] == 5_068
    assert actual["reasoning_tokens"] == 3_157
    assert actual["total_usd"] == "0.170929500000"
    assert actual["task_arm_reservations"] == 1
    assert actual["task_arm_runs"] == 0
    assert actual["grader_containers"] == 0
    assert actual["official_grader_runs"] == 0


def test_d118_context_propagates_and_restores_inherited_bindings() -> None:
    modules = (d117, d118.d115, d118.d114)
    missing = object()
    before = {
        module: {
            "request_id": module.REQUEST_ID,
            "schema": module.REQUEST_SCHEMA,
            "sentinel": module.SENTINEL_PATH,
            "loader_collector": getattr(
                module, "LOADER_REHEARSAL_COLLECTOR_PATH", missing
            ),
        }
        for module in modules
    }

    with d118._d118_runtime_context():
        for module in modules:
            assert module.REQUEST_ID == d118.REQUEST_ID
            assert module.REQUEST_SCHEMA == d118.REQUEST_SCHEMA
            assert module.SENTINEL_PATH == d118.SENTINEL_PATH
        for module in (d117, d118.d115):
            assert (
                module.LOADER_REHEARSAL_COLLECTOR_PATH
                == d118.LOADER_REHEARSAL_COLLECTOR_PATH
            )
        with d118._d118_runtime_context():
            assert d117.REQUEST_ID == d118.REQUEST_ID

    for module in modules:
        assert module.REQUEST_ID == before[module]["request_id"]
        assert module.REQUEST_SCHEMA == before[module]["schema"]
        assert module.SENTINEL_PATH == before[module]["sentinel"]
        prior = before[module]["loader_collector"]
        if prior is missing:
            assert not hasattr(module, "LOADER_REHEARSAL_COLLECTOR_PATH")
        else:
            assert module.LOADER_REHEARSAL_COLLECTOR_PATH == prior


def test_d118_loader_subprocess_wrapper_binds_parent_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[object, object, object, object]] = []

    def parent_main(argv: object = None) -> int:
        observed.append(
            (
                argv,
                d118.d117.RUNNER_READINESS_SCHEMA,
                d118.d115.RUNNER_READINESS_SCHEMA,
                d118.d115.LOADER_REHEARSAL_COLLECTOR_PATH,
            )
        )
        return 23

    monkeypatch.setattr(d118_collector.d115_collector, "main", parent_main)
    argv = ["--synthetic"]
    assert d118_collector.main(argv) == 23
    assert observed == [
        (
            argv,
            d118.RUNNER_READINESS_SCHEMA,
            d118.RUNNER_READINESS_SCHEMA,
            d118.LOADER_REHEARSAL_COLLECTOR_PATH,
        )
    ]


def test_d118_new_sources_are_required_and_bound() -> None:
    assert d118.REQUIRED_RECOVERY_CHANGES[d118.TRIGGER_PATH] == "A"
    assert d118.REQUIRED_RECOVERY_CHANGES[d118.LOADER_REHEARSAL_COLLECTOR_PATH] == "A"
    assert d118.REQUIRED_RECOVERY_CHANGES[d118.GRADER_FACTORY_REHEARSAL_PATH] == "A"
    assert (
        d118.ACTIVATION_BINDING_PATHS["grader_factory_rehearsal_sha256"]
        == d118.GRADER_FACTORY_REHEARSAL_PATH
    )
    assert (
        d118.ACTIVATION_BINDING_PATHS["benchmark_runner_sha256"]
        == "scripts/trimem_benchmark_run.py"
    )
    assert d118.ACTIVATION_BINDING_PATHS["benchmark_workflow_sha256"] == (
        ".github/workflows/trimem-benchmark.yml"
    )


def test_d118_recovery_scope_excludes_science_and_historical_d117() -> None:
    forbidden = {
        ".gitattributes",
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/model_lock.json",
        d117.AMENDMENT_PATH,
        d117.INVENTORY_PATH,
        d117.PREVIOUS_FAILURE_FIXTURE_PATH,
        d117.LOADER_REHEARSAL_COLLECTOR_PATH,
        d117.TRIGGER_PATH,
    }
    assert forbidden.isdisjoint(d118.ALLOWED_RECOVERY_PATHS)


def test_d118_current_records_separate_consumed_and_current_actuals() -> None:
    failure = d118.current_failure_record()
    recovery = d118.current_recovery_record()
    assert failure["pass_at_1"] is None
    assert failure["performance_measured"] is False
    assert failure["observed_execution_actuals"] == d118.HISTORICAL_EXECUTION_ACTUALS
    assert failure["failure_boundary"]["task_arm_reservation_started"] is True
    assert recovery["consumed_exec_017_actuals"] == d118.HISTORICAL_EXECUTION_ACTUALS
    assert all(value == 0 for value in recovery["current_execution_actuals"].values())
    assert recovery["actual_execution_authorized"] is False
    assert recovery["endpoint"] == "TRIMEM_V1_READY_FOR_EXEC_018_REQUEST"


def test_d118_build_request_binds_rehearsal_and_launcher_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = _synthetic_checkout()
    previous = {
        "control_plane": {"one_time_workflow_runs": 1},
        "exact_model": {"model_id": d118.MODEL_ID},
        "scientific_workload": {"task_arm_runs": 72},
    }
    bindings = {
        "checkout_rehearsal_sha256": "sha256:" + "a" * 64,
        "grader_factory_rehearsal_sha256": "sha256:" + "b" * 64,
    }
    monkeypatch.setattr(
        d118,
        "_validate_source_impl",
        lambda *_args: {
            "previous_request": previous,
            "bindings": bindings,
            "hard_cap": {"total_usd": 50.0},
        },
    )
    monkeypatch.setattr(
        d118.d115, "_validate_remote_gate_evidence", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(
        d118.d115, "_validate_runner_readiness", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(
        d118, "validate_loader_rehearsal_record", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(d118, "validate_checkout_rehearsal", lambda value: value)
    monkeypatch.setattr(
        d118.d117, "_request_execution_contracts", lambda _bindings: {"contract_bindings": {}}
    )
    request = d118._build_request_impl(
        ROOT,
        source_head="a" * 40,
        remote_gate_evidence={"gates": True},
        runner_readiness={"runner": True},
        loader_rehearsal={"loader": True},
        checkout_rehearsal=checkout,
    )
    contracts = request["d118_execution_contracts"]
    assert contracts["official_grader_preflight_launcher_binding"] == {
        "factory_full_identity_check_before_model": True,
        "factory_reuses_preflight_lexical_launcher": True,
        "journal_reuses_preflight_lexical_launcher": True,
        "protected_driver_uses_exact_python3_11": True,
        "protected_precredential_synthetic_rehearsal": True,
        "twelve_target_credential_free_factory_rehearsal": True,
    }
    assert contracts["contract_bindings"]["grader_factory_rehearsal_sha256"] == (
        bindings["grader_factory_rehearsal_sha256"]
    )
    assert request["recovery_provenance"]["scientific_model_calls"] == 17
    assert request["recovery_provenance"]["request_017_rerun_allowed"] is False
    assert request["request_sha256"].startswith("sha256:")


def test_d118_workflow_requires_exact_driver_and_factory_rehearsal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # D1.19 intentionally moves the live route to _019. Exercise D1.18 against
    # its immutable correction-source blobs instead of the newer live files.
    d118_source_head = "3236bd546ff581e396ca6123bb1655bad5294ce4"
    files = {
        path: d118.commit_bytes(ROOT, d118_source_head, path)
        for path in (
            d118.EXACT_HEAD_GATE_WORKFLOW_PATH,
            d118.EXPECTED_WORKFLOW_PATH,
        )
    }
    monkeypatch.setattr(d118, "commit_bytes", lambda _r, _h, path: files[path])
    d118._validate_workflow(ROOT, "a" * 40)

    workflow = files[d118.EXPECTED_WORKFLOW_PATH].decode()
    changed = workflow.replace(
        '"$pythonLocation/bin/python3.11" scripts/trimem_run_with_resume.py',
        "python scripts/trimem_run_with_resume.py",
        1,
    )
    files[d118.EXPECTED_WORKFLOW_PATH] = changed.encode()
    with pytest.raises(
        d118.DevelopmentTriggerError,
        match="exact preflight launcher",
    ):
        d118._validate_workflow(ROOT, "a" * 40)
