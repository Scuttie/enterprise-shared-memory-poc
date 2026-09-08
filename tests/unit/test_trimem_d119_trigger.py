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

import trimem_development_trigger_d118 as d118
import trimem_development_trigger_d119 as d119
import trimem_d119_loader_rehearsal as d119_collector


def _fixture_bytes() -> bytes:
    return (ROOT / d119.PREVIOUS_FAILURE_FIXTURE_PATH).read_bytes()


def _synthetic_checkout() -> dict[str, object]:
    rows = []
    for (
        target_id,
        tree,
        regular_blob_count,
        normalized_count,
        path_set_sha256,
    ) in d119.EXPECTED_CHECKOUT_MATERIALIZATION:
        normalized_paths: list[str] = []
        if normalized_count:
            normalized_paths = [
                f"normalized/{index:03d}.txt" for index in range(normalized_count)
            ]
            path_set_sha256 = hashlib.sha256(
                d119.canonical_bytes(normalized_paths)
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
        "schema": d119.CHECKOUT_REHEARSAL_SCHEMA,
        "source_identity": "PINNED_GIT_BLOB_BYTES_AT_REVISION",
        "split": "DEVELOPMENT_TUNING",
        "status": "PASS",
        "target_count": 12,
        "targets": rows,
        "task_arm_runs": 0,
        "transform_rule": "COMMITTED_TEXT_SET_EOL_CRLF_ONLY",
    }


def test_d119_exact_active_and_historical_identities() -> None:
    assert d119.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_019"
    assert d119.REQUEST_SCHEMA == "trimem/development-tuning-branch-trigger/1.19"
    assert d119.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_019.json")
    assert d119.PREVIOUS_SOURCE_HEAD == "3236bd546ff581e396ca6123bb1655bad5294ce4"
    assert d119.PREVIOUS_EXECUTION_HEAD == "5cce6502a61c81c2e0490578dc5a2a3045f8c179"
    assert d119.PREVIOUS_RUN_ID == 34_211_486_542
    assert d119.PREVIOUS_RUN_ATTEMPT == 1
    assert (
        d119.REQUIRED_EXTERNAL_AUTHORIZATION
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_019_APPROVED_ONCE"
    )
    completed = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{d119.PREVIOUS_EXECUTION_HEAD}:{d119.PREVIOUS_SENTINEL_PATH}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == d119.PREVIOUS_SENTINEL_BLOB_OID
    previous = d119._load_previous_request(ROOT, d119.PREVIOUS_EXECUTION_HEAD)
    assert previous["request_sha256"] == (
        "sha256:" + d119.PREVIOUS_REQUEST_PAYLOAD_SHA256
    )
    assert previous["bindings"]["freeze_sha256"] == (
        "sha256:" + d119.PREVIOUS_SOURCE_FREEZE_SHA256
    )


def test_d119_fixture_is_exact_and_replays_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _fixture_bytes()
    assert len(raw) == d119.PREVIOUS_FAILURE_FIXTURE_BYTES
    assert hashlib.sha256(raw).hexdigest() == d119.PREVIOUS_FAILURE_FIXTURE_SHA256
    monkeypatch.setattr(d119, "commit_bytes", lambda *_args: raw)
    observed = d119._validate_previous_run_fixture(
        ROOT, d119.PREVIOUS_EXECUTION_HEAD
    )
    assert observed["performance_measured"] is False
    assert observed["pass_at_1"] is None
    assert observed["actuals"] == d119.HISTORICAL_EXECUTION_ACTUALS
    assert observed["approval_boundary"]["observed_non_ascii_character"] == "U+FEFF"
    assert observed["approval_boundary"]["exec_gate"] == "NOT_REACHED"


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value["actuals"].__setitem__("paid_model_calls", 1),
        lambda value: value["actuals"].__setitem__("total_usd", "0.000000000001"),
        lambda value: value.__setitem__("performance_measured", True),
        lambda value: value.__setitem__("pass_at_1", 0.0),
        lambda value: value["approval_boundary"].__setitem__(
            "approval_materialization", "PASS"
        ),
        lambda value: value["approval_boundary"].__setitem__(
            "observed_non_ascii_character", "U+000A"
        ),
        lambda value: value["root_cause"].__setitem__(
            "classification", "APPROVAL_DOCUMENT_PRODUCTION_FAILURE"
        ),
        lambda value: value["root_cause"]["recovery_contract"].__setitem__(
            "strict_workflow_decoder_preserved", False
        ),
        lambda value: value["evidence_custody"].__setitem__(
            "secrets_removed_after_failure", False
        ),
    ),
)
def test_d119_fixture_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch, mutation: object
) -> None:
    modified = deepcopy(json.loads(_fixture_bytes()))
    assert callable(mutation)
    mutation(modified)
    raw = (
        json.dumps(modified, ensure_ascii=False, indent=2, allow_nan=False).encode()
        + b"\n"
    )
    monkeypatch.setattr(d119, "commit_bytes", lambda *_args: raw)
    with pytest.raises(d119.DevelopmentTriggerError):
        d119._validate_previous_run_fixture(ROOT, d119.PREVIOUS_EXECUTION_HEAD)


def test_d119_accounting_keeps_d118_zero_and_d117_partial_separate() -> None:
    assert all(
        value in {0, "0.000000000000"}
        for value in d119.HISTORICAL_EXECUTION_ACTUALS.values()
    )
    assert d119.HISTORICAL_EXECUTION_ACTUALS["paid_model_calls"] == 0
    assert d119.HISTORICAL_EXECUTION_ACTUALS["task_arm_runs"] == 0
    assert d119.HISTORICAL_EXECUTION_ACTUALS["grader_containers"] == 0
    assert d119.HISTORICAL_EXECUTION_ACTUALS["benchmark_image_pulls"] == 0
    assert d118.HISTORICAL_EXECUTION_ACTUALS["paid_model_calls"] == 18
    assert d118.HISTORICAL_EXECUTION_ACTUALS["scientific_model_calls"] == 17
    assert d118.HISTORICAL_EXECUTION_ACTUALS["total_usd"] == "0.170929500000"


def test_d119_context_propagates_and_restores_inherited_bindings() -> None:
    modules = (d118, d119.d115, d119.d114)
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

    with d119._d119_runtime_context():
        for module in modules:
            assert module.REQUEST_ID == d119.REQUEST_ID
            assert module.REQUEST_SCHEMA == d119.REQUEST_SCHEMA
            assert module.SENTINEL_PATH == d119.SENTINEL_PATH
        for module in (d118, d119.d115):
            assert (
                module.LOADER_REHEARSAL_COLLECTOR_PATH
                == d119.LOADER_REHEARSAL_COLLECTOR_PATH
            )
        with d119._d119_runtime_context():
            assert d118.REQUEST_ID == d119.REQUEST_ID

    for module in modules:
        assert (
            module.REQUEST_ID,
            module.REQUEST_SCHEMA,
            module.SENTINEL_PATH,
            getattr(module, "LOADER_REHEARSAL_COLLECTOR_PATH", missing),
        ) == before[module]


def test_d119_loader_subprocess_wrapper_binds_parent_collector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[tuple[object, object, object, object]] = []

    def parent_main(argv: object = None) -> int:
        observed.append(
            (
                argv,
                d119.d118.RUNNER_READINESS_SCHEMA,
                d119.d115.RUNNER_READINESS_SCHEMA,
                d119.d115.LOADER_REHEARSAL_COLLECTOR_PATH,
            )
        )
        return 29

    monkeypatch.setattr(d119_collector.d115_collector, "main", parent_main)
    argv = ["--synthetic"]
    assert d119_collector.main(argv) == 29
    assert observed == [
        (
            argv,
            d119.RUNNER_READINESS_SCHEMA,
            d119.RUNNER_READINESS_SCHEMA,
            d119.LOADER_REHEARSAL_COLLECTOR_PATH,
        )
    ]


def test_d119_new_sources_are_required_and_bound() -> None:
    assert d119.REQUIRED_RECOVERY_CHANGES[d119.TRIGGER_PATH] == "A"
    assert d119.REQUIRED_RECOVERY_CHANGES[d119.APPROVAL_SECRET_PATH] == "A"
    assert (
        d119.REQUIRED_RECOVERY_CHANGES[d119.LOADER_REHEARSAL_COLLECTOR_PATH]
        == "A"
    )
    assert (
        d119.ACTIVATION_BINDING_PATHS["loader_rehearsal_collector_sha256"]
        == d119.LOADER_REHEARSAL_COLLECTOR_PATH
    )
    assert (
        d119.ACTIVATION_BINDING_PATHS["approval_secret_producer_sha256"]
        == d119.APPROVAL_SECRET_PATH
    )
    assert (
        d119.ACTIVATION_BINDING_PATHS["benchmark_runner_sha256"]
        == "scripts/trimem_benchmark_run.py"
    )
    assert d119.ACTIVATION_BINDING_PATHS["benchmark_workflow_sha256"] == (
        ".github/workflows/trimem-benchmark.yml"
    )


def test_d119_recovery_scope_excludes_science_and_historical_d118() -> None:
    forbidden = {
        ".gitattributes",
        "configs/trimem_v1/arms.json",
        "configs/trimem_v1/cost_plan.json",
        "configs/trimem_v1/development_manifest.json",
        "configs/trimem_v1/grader_lock.json",
        "configs/trimem_v1/model_lock.json",
        d118.AMENDMENT_PATH,
        d118.INVENTORY_PATH,
        d118.PREVIOUS_FAILURE_FIXTURE_PATH,
        d118.GRADER_FACTORY_REHEARSAL_PATH,
        d118.LOADER_REHEARSAL_COLLECTOR_PATH,
        d118.TRIGGER_PATH,
    }
    assert forbidden.isdisjoint(d119.ALLOWED_RECOVERY_PATHS)


def test_d119_current_records_separate_consumed_and_current_actuals() -> None:
    failure = d119.current_failure_record()
    recovery = d119.current_recovery_record()
    assert failure["pass_at_1"] is None
    assert failure["performance_measured"] is False
    assert failure["observed_execution_actuals"] == d119.HISTORICAL_EXECUTION_ACTUALS
    assert failure["failure_boundary"]["approval_materialization"] == "FAIL_CLOSED"
    assert failure["failure_boundary"]["scientific_model_calls"] == 0
    assert recovery["consumed_exec_018_actuals"] == d119.HISTORICAL_EXECUTION_ACTUALS
    assert all(value == 0 for value in recovery["current_execution_actuals"].values())
    assert recovery["actual_execution_authorized"] is False
    assert recovery["endpoint"] == "TRIMEM_V1_READY_FOR_EXEC_019_REQUEST"


def test_d119_build_request_binds_byte_only_secret_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = _synthetic_checkout()
    previous = {
        "control_plane": {"one_time_workflow_runs": 1},
        "exact_model": {"model_id": d119.MODEL_ID},
        "scientific_workload": {"task_arm_runs": 72},
    }
    bindings = {
        "approval_secret_producer_sha256": "sha256:" + "c" * 64,
        "checkout_rehearsal_sha256": "sha256:" + "a" * 64,
        "grader_factory_rehearsal_sha256": "sha256:" + "b" * 64,
    }
    monkeypatch.setattr(
        d119,
        "_validate_source_impl",
        lambda *_args: {
            "previous_request": previous,
            "bindings": bindings,
            "hard_cap": {"total_usd": 50.0},
        },
    )
    monkeypatch.setattr(
        d119.d115, "_validate_remote_gate_evidence", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(
        d119.d115, "_validate_runner_readiness", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(
        d119, "validate_loader_rehearsal_record", lambda value, **_kwargs: value
    )
    monkeypatch.setattr(d119, "validate_checkout_rehearsal", lambda value: value)
    monkeypatch.setattr(
        d118,
        "_request_execution_contracts",
        lambda _bindings: {"contract_bindings": {}},
    )
    request = d119._build_request_impl(
        ROOT,
        source_head="a" * 40,
        remote_gate_evidence={"gates": True},
        runner_readiness={"runner": True},
        loader_rehearsal={"loader": True},
        checkout_rehearsal=checkout,
    )
    contracts = request["d119_execution_contracts"]
    assert contracts["approval_secret_encoding"] == {
        "approval_document_rebuilt_for_new_run_attempt_one": True,
        "base64_ascii_no_bom_whitespace_validation": True,
        "base64_round_trip_validation": True,
        "byte_only_external_secret_production": True,
        "strict_workflow_decoder_preserved": True,
    }
    assert contracts["contract_bindings"]["approval_secret_producer_sha256"] == (
        bindings["approval_secret_producer_sha256"]
    )
    assert request["recovery_provenance"]["scientific_model_calls"] == 0
    assert request["recovery_provenance"]["request_018_rerun_allowed"] is False
    assert request["request_sha256"].startswith("sha256:")


def test_d119_workflow_keeps_strict_decoder_and_active_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = {
        d119.EXACT_HEAD_GATE_WORKFLOW_PATH: (
            ROOT / d119.EXACT_HEAD_GATE_WORKFLOW_PATH
        ).read_bytes(),
        d119.EXPECTED_WORKFLOW_PATH: (ROOT / d119.EXPECTED_WORKFLOW_PATH).read_bytes(),
    }
    monkeypatch.setattr(d119, "commit_bytes", lambda _r, _h, path: files[path])
    d119._validate_workflow(ROOT, "a" * 40)

    workflow = files[d119.EXPECTED_WORKFLOW_PATH].decode()
    changed = workflow.replace(
        "base64.b64decode(os.environ['TRIMEM_EXEC_APPROVAL_B64'], validate=True)",
        "base64.b64decode(os.environ['TRIMEM_EXEC_APPROVAL_B64'], validate=False)",
        1,
    )
    files[d119.EXPECTED_WORKFLOW_PATH] = changed.encode()
    with pytest.raises(
        d119.DevelopmentTriggerError,
        match="strict approval Base64 decoder",
    ):
        d119._validate_workflow(ROOT, "a" * 40)


def test_d119_current_history_has_no_uncommitted_or_committed_019() -> None:
    assert d119.validate_optional_exec_019_boundary(ROOT) is None
