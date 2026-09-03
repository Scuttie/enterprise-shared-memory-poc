from __future__ import annotations

from copy import deepcopy
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_benchmark_run as benchmark_run  # noqa: E402
import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_cleanup_exec as cleanup_exec  # noqa: E402
import trimem_development_trigger_preflight as trigger  # noqa: E402
import trimem_freeze as freeze  # noqa: E402
import trimem_grader_smoke as grader_smoke  # noqa: E402
import trimem_grader_smoke_authority as smoke_authority  # noqa: E402
import trimem_grader_smoke_failure_closure as failure_closure  # noqa: E402
import trimem_grader_smoke_finalization as finalization_journal  # noqa: E402
import trimem_grader_smoke_stage_evidence as stage_evidence  # noqa: E402
import trimem_grader_smoke_protocol as smoke_protocol  # noqa: E402
import trimem_grader_smoke_trigger_preflight as smoke_trigger  # noqa: E402
import trimem_evidence_inventory as evidence_inventory  # noqa: E402
import trimem_exec_approval as exec_approval  # noqa: E402
import trimem_m2_candidates as candidates  # noqa: E402
import trimem_official_grader as official_grader  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402
import trimem_pull_locked_images as image_pull  # noqa: E402
import trimem_run_with_resume as resume_runner  # noqa: E402
import trimem_select_targets as selector  # noqa: E402
import trimem_smoke_attestation as smoke_attestation  # noqa: E402
import trimem_verify_ready as readiness  # noqa: E402
from enterprise_memory.trimem.workspace import WorkspaceGraderContext  # noqa: E402


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _smoke_accounting(grader_count: int) -> dict[str, int]:
    return {
        field: grader_count
        if field in {"grader_calls", "grader_containers", "official_grader_runs"}
        else 0
        for field in readiness.SMOKE_ACCOUNTING_FIELDS
    }


def _public_multi_semantics_summary(resolved: bool) -> dict[str, object]:
    missing = 0 if resolved else 1
    summary: dict[str, object] = {
        "schema": "trimem/multi-swe-report-semantics/1.0",
        "report_valid_observed": True,
        "report_valid_recomputed": True,
        "report_valid_match": True,
        "expected_coverage_complete": resolved,
        "expected_p2p_count": 0,
        "observed_expected_p2p_count": 0,
        "expected_f2p_count": 1,
        "observed_expected_f2p_count": 1 - missing,
        "expected_s2p_count": 0,
        "observed_expected_s2p_count": 0,
        "expected_n2p_count": 0,
        "observed_expected_n2p_count": 0,
        "missing_expected_transition_count": missing,
        "expected_transition_domain_sha256": "a" * 64,
        "observed_expected_transition_domain_sha256": (
            "a" * 64 if resolved else "b" * 64
        ),
        "computed_resolved": resolved,
        "official_final_report_resolved": resolved,
        "final_report_match": True,
        "report_invalidity_reason": "NONE",
    }
    return readiness.validate_public_summary(summary)


ZERO_SMOKE_ACCOUNTING_FIELDS = tuple(
    field
    for field in readiness.SMOKE_ACCOUNTING_FIELDS
    if field not in {"grader_calls", "grader_containers", "official_grader_runs"}
)


def test_p011_preserves_failed_trigger_and_records_nonsemantic_amendment() -> None:
    historical_path = (
        ROOT
        / "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json"
    )
    historical_raw = historical_path.read_bytes()
    assert hashlib.sha256(historical_raw).hexdigest() == (
        "03207843e241bef409d64d0181596f4cec4c83fe157dfc22670d429bc14f91f0"
    )
    frozen = _read(ROOT / "artifacts/trimem_v1/freeze.json")["files"]
    assert frozen[historical_path.relative_to(ROOT).as_posix()] == {
        "bytes": len(historical_raw),
        "sha256": hashlib.sha256(historical_raw).hexdigest(),
    }
    amendment = _read(
        ROOT / "configs/trimem_v1/grader_smoke_manifest.json"
    )["execution_control_amendment"]
    assert amendment == {
        "benchmark_result_existed_when_amended": False,
        "classification": "NON_SEMANTIC_EXECUTION_CONTROL_FIX",
        "previous_failed_run": {
            "head": "71edef406f0bc5202244ae1ad4f84419662e7126",
            "run_attempt": 1,
            "run_id": 33470431940,
            "scientific_or_evaluator_execution": False,
        },
        "reason": (
            "GitHub Actions push-event payload contract correction; "
            "no benchmark result existed when amended."
        ),
        "scientific_inputs_changed": False,
    }

    current_manifest = _read(
        ROOT / "configs/trimem_v1/grader_smoke_manifest.json"
    )
    assert current_manifest[
        "multi_swe_prebuilt_evaluation_contract_amendment"
    ] == {
        "classification": "NON_SEMANTIC_MULTI_SWE_PREBUILT_EVALUATION_CONTRACT_FIX",
        "completed_cells_authoritative": False,
        "completed_cells_diagnostic_only": 4,
        "previous_failed_run": {
            "head": "a0f8cf2bbc3e13690c583b86054aaae562dfe3fd",
            "run_attempt": 1,
            "run_id": 33594270929,
            "scientific_or_evaluator_execution": True,
        },
        "reason": (
            "Correct the Multi-SWE digest-pinned prebuilt-image evaluation mode "
            "and submitted-patch mount contract; the four completed SWE-bench "
            "cells from the interrupted mixed-adapter campaign remain diagnostic only."
        ),
        "scientific_inputs_changed": False,
    }
    scientific_fields = (
        "matrix_kind",
        "noop_baseline",
        "selection",
        "target_set_sha256",
        "targets",
    )
    scientific_projection = {
        field: current_manifest[field] for field in scientific_fields
    }
    assert hashlib.sha256(_canonical(scientific_projection)).hexdigest() == (
        "d9882fbf694c1fba6cfab5953360b3264b284b2dee685c07a73e0c55ec5aa088"
    )
    baseline_raw_hashes = {
        "configs/trimem_v1/benchmark_exec_request.json": (
            "05e19aeec6630f2362c481a86eb66d0e630041794866a638c3ebbf07e5ccbba4"
        ),
        "artifacts/trimem_v1/grader_image_lock.json": (
            "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb"
        ),
        "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json": (
            "e03e96f26b56fffb2e911504b526b6986a9148b4db620aa9b58bb5e100083e4c"
        ),
        "scripts/trimem_grader_smoke_protocol.py": (
            "f73d7da715b3cc6a2d15e3bc39c355cfeccf585ab2014a1834c9b275839fc7b8"
        ),
    }
    for relative, expected_sha256 in baseline_raw_hashes.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == (
            expected_sha256
        )


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_all_execution_config_readers_reject_duplicate_json_keys(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"maximum_budget_is_not_actual_compute":true,"maximum_budget_is_not_actual_compute":false}', encoding="utf-8")
    with pytest.raises((ValueError, readiness.ReadinessError), match="duplicate JSON key"):
        readiness.read_json(duplicate)
    with pytest.raises((ValueError, candidates.CandidateContractError), match="duplicate JSON key"):
        candidates.read_json(duplicate)
    with pytest.raises((ValueError, selector.SelectionError), match="duplicate JSON key"):
        selector.read_object(duplicate)
    arms = readiness.read_json(ROOT / "configs/trimem_v1/arms.json")
    assert arms["comparability_contract"]["maximum_budget_is_not_actual_compute"] is True


def test_resume_metric_and_aggregate_json_boundaries_reject_duplicate_keys(tmp_path: Path) -> None:
    with pytest.raises(benchmark_matrix.MatrixError, match="duplicate JSON key"):
        benchmark_matrix._strict_loads('{"resolved":true,"resolved":false}')
    checkpoint = tmp_path / "M0.stream-checkpoint.json"
    sidecar = tmp_path / "M0.stream-checkpoint.sha256"
    raw = b'{"payload":{},"payload":{}}'
    checkpoint.write_bytes(raw)
    sidecar.write_text(hashlib.sha256(raw).hexdigest(), encoding="ascii")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        benchmark_run.load_arm_checkpoint(tmp_path, "M0")
    events = tmp_path / "events.ndjson"
    events.write_text('{"event_type":"memory_recall","event_type":"other"}\n', encoding="utf-8")
    result = type("Result", (), {
        "injections": (),
        "lifecycle_result": {"storage": {
            "retained_records": 0, "archived_records": 0, "net_memory_growth": 0,
        }},
    })()
    with pytest.raises(ValueError, match="duplicate JSON key"):
        benchmark_run.actual_memory_metrics(result, events)


def test_target_set_digests_bind_exact_ordered_rows() -> None:
    expected = {
        "development": "e7da59b3c2638c89da4e333a7391851e992c122acac11bc9edf60619cfd5eff2",
        "heldout": "abd3f182acef8f37018e5f05ab9ba185b7b1efbc111dee273e66a38e6ab16267",
        "grader_smoke": "01f9e41f1ce3f285c651c3bc857a1f7422ed7e0f9ccfb451b42aedf9a4aef52e",
    }
    for name, digest in expected.items():
        manifest = _read(ROOT / f"configs/trimem_v1/{name}_manifest.json")
        assert manifest["target_set_sha256"] == digest
        assert hashlib.sha256(_canonical(manifest["targets"])).hexdigest() == digest


def test_benchmark_roles_freeze_primary_secondary_endpoints_before_results() -> None:
    for name in ("development", "heldout"):
        manifest = _read(ROOT / f"configs/trimem_v1/{name}_manifest.json")
        roles = benchmark_matrix._validate_benchmark_roles(
            manifest, manifest["targets"]
        )
        assert [row["benchmark_id"] for row in roles if row["role"] == "PRIMARY"] == [
            "swebench_verified"
        ]
        assert all(
            row["role"] == "SECONDARY"
            for row in roles
            if row["benchmark_id"].startswith("multi_swe_bench_")
        )

        tampered = deepcopy(manifest)
        tampered["benchmark_roles"][0]["target_count"] += 1
        with pytest.raises(benchmark_matrix.MatrixError, match="count/revision"):
            benchmark_matrix._validate_benchmark_roles(
                tampered, tampered["targets"]
            )
    development = _read(ROOT / "configs/trimem_v1/development_manifest.json")
    assert "pooled resolved_count" in development["tuning_selection_objective"]
    assert "not the held-out primary endpoint" in development[
        "tuning_selection_objective"
    ]


def test_arm_by_benchmark_pass_at_1_is_separate_from_pooled_totals() -> None:
    roles = [
        {
            "benchmark_id": "swebench_verified",
            "dataset_id": "primary",
            "dataset_revision": "a" * 40,
            "role": "PRIMARY",
            "target_count": 2,
        },
        {
            "benchmark_id": "multi_swe_bench_mini",
            "dataset_id": "secondary",
            "dataset_revision": "b" * 40,
            "role": "SECONDARY",
            "target_count": 1,
        },
    ]
    outcomes = [
        {"arm": "M0", "benchmark_id": "swebench_verified", "resolved": True},
        {"arm": "M0", "benchmark_id": "swebench_verified", "resolved": False},
        {"arm": "M0", "benchmark_id": "multi_swe_bench_mini", "resolved": True},
    ]
    totals = benchmark_matrix._benchmark_endpoint_totals(
        outcomes, ("M0",), roles
    )
    assert totals[0]["reporting_role"] == "PRIMARY"
    assert (totals[0]["n"], totals[0]["resolved_count"], totals[0]["pass_at_1"]) == (
        2, 1, "0.500000000000"
    )
    assert totals[1]["reporting_role"] == "SECONDARY"
    assert totals[1]["pass_at_1"] == "1.000000000000"
    with pytest.raises(benchmark_matrix.MatrixError, match="target counts"):
        benchmark_matrix._benchmark_endpoint_totals(outcomes[:-1], ("M0",), roles)


def test_selector_score_uses_only_public_identity() -> None:
    public = {"instance_id": "org__repo-1", "patch": "secret-a", "test_patch": "secret-b"}
    changed_hidden = {**public, "patch": "different", "test_patch": "different"}
    assert selector._score("seed", "development", "swebench_verified", public) == selector._score(
        "seed", "development", "swebench_verified", changed_hidden
    )
    plan = _read(ROOT / "configs/trimem_v1/selection_plan.json")
    assert plan["schema"] == "trimem/selection-plan/3.0"
    assert "source_row_sha256" not in plan["row_score"]
    assert "salt" not in json.dumps(plan).lower()


def test_four_candidate_bundle_is_executable_and_preserves_hard_retrieval_limits() -> None:
    bundle = candidates.load_bundle()
    assert bundle["candidate_order"] == list(candidates.CANDIDATE_IDS)
    assert bundle["development_contract"]["candidate_task_arm_runs"] == 48
    hashes = set()
    for candidate_id in candidates.CANDIDATE_IDS:
        policy = candidates.load_candidate_policy(candidate_id)
        assert policy["retrieval"]["max_episodic_per_active_node"] == 1
        assert policy["retrieval"]["max_semantic_per_active_node"] == 1
        hashes.add(candidates.digest_value(policy))
        assert "candidate" not in candidates.PROMPT_SUFFIXES[candidate_id].lower()
        assert "development" not in candidates.PROMPT_SUFFIXES[candidate_id].lower()
    assert len(hashes) == 4


def test_cost_history_and_post_smoke_readiness_are_non_circular() -> None:
    model = _read(ROOT / "configs/trimem_v1/model_lock.json")
    assert model["schema"] == "trimem/model-lock/1.2"
    assert model["primary_model"]["model_id"] == "gpt-5.4-mini-2026-03-17"
    assert {
        role["model_id"] for role in model["model_roles"].values()
    } == {"gpt-5.4-mini-2026-03-17"}
    assert "gpt-5.4-nano" not in json.dumps(model).lower()
    amendment = _read(
        ROOT / "artifacts/trimem_v1/development_model_pricing_amendment.json"
    )
    assert amendment["amendment"]["classification"] == (
        "PRE_EXECUTION_COST_PERFORMANCE_AMENDMENT"
    )
    assert amendment["causal_boundary"]["paid_model_calls_before_amendment"] == 0
    assert amendment["execution_boundary"]["development_execution_authorized"] is False
    assert amendment["execution_boundary"]["grader_smoke_rerun_authorized"] is False
    cost = _read(ROOT / "configs/trimem_v1/cost_plan.json")
    assert cost["schema"] == "trimem/cost-plan/1.4"
    assert cost["model_pricing"] == {
        "cached_input_per_million_tokens_usd": 0.075,
        "input_per_million_tokens_usd": 0.75,
        "model_id": "gpt-5.4-mini-2026-03-17",
        "output_per_million_tokens_usd": 4.5,
        "source_url": "https://developers.openai.com/api/docs/models/gpt-5.4-mini",
    }
    assert cost["expected_cost"]["phase_totals"]["DEVELOPMENT_TUNING"]["total_usd"] == 10.8
    assert cost["phase_hard_caps"]["DEVELOPMENT_TUNING"]["total_usd"] == 50.0
    assert cost["run_counts"]["development_physical_task_arm_runs"] == 72
    assert cost["run_counts"]["heldout_physical_task_arm_runs"] == 81
    assert cost["run_counts"]["total_physical_task_arm_runs"] == 153
    assert cost["actual_to_date_scope"] == (
        "CUMULATIVE_INCLUDES_P0.1.4_DIAGNOSTIC_HISTORY_AND_"
        "P0.1.5_EXEC_005_AUTHORITATIVE_PASS"
    )
    p014_actual = {
        **_smoke_accounting(6),
        "docker_pulls": 4,
        "support_image_pulls": 1,
        "target_image_pulls": 3,
    }
    p015_actual = {
        **_smoke_accounting(12),
        "docker_pulls": 7,
        "support_image_pulls": 1,
        "target_image_pulls": 6,
    }
    assert cost["accounting_windows"]["p014_diagnostic_history"] == {
        **p014_actual,
        "git_head": "0e9ed55196da922dcebf1fb33b73940873007180",
        "scientific_role": "DIAGNOSTIC_ONLY",
        "scope": "IMMUTABLE_DIAGNOSTIC_HISTORY_ONLY",
        "workflow_run_attempt": 1,
        "workflow_run_id": 33630256522,
    }
    assert cost["accounting_windows"]["p015_correction_pre_exec_005"] == {
        **readiness.SMOKE_RECOVERY_ACTUAL_EXECUTION,
        "scope": readiness.SMOKE_RECOVERY_SCOPE,
    }
    assert cost["accounting_windows"]["p015_authoritative_exec_005"] == {
        **p015_actual,
        "git_head": readiness.SMOKE_PASS_EXECUTION_HEAD,
        "scientific_role": "AUTHORITATIVE",
        "scope": readiness.SMOKE_PASS_READINESS_SCOPE,
        "workflow_run_attempt": int(readiness.SMOKE_PASS_RUN_ATTEMPT),
        "workflow_run_id": int(readiness.SMOKE_PASS_RUN_ID),
    }
    cumulative = {
        field: p014_actual[field] + p015_actual[field]
        for field in p014_actual
    }
    assert cumulative == {
        "api_calls": 0,
        "cached_input_tokens": 0,
        "decomposition_calls": 0,
        "docker_pulls": 11,
        "extraction_calls": 0,
        "grader_calls": 18,
        "grader_containers": 18,
        "input_tokens": 0,
        "model_calls": 0,
        "model_gateway_calls": 0,
        "official_grader_runs": 18,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "reasoning_tokens": 0,
        "solve_calls": 0,
        "support_image_pulls": 2,
        "target_image_pulls": 9,
        "task_arm_runs": 0,
        "total_usd": 0,
    }
    assert cost["actual_to_date"] == cumulative
    assert cost["expected_cost"]["phase_totals"]["GRADER_SMOKE"][
        "grader_containers"
    ] == 12
    assert cost["phase_hard_caps"]["GRADER_SMOKE"][
        "benchmark_grader_containers"
    ] == 12
    requirements = _read(ROOT / "artifacts/trimem_v1/readiness_requirements.json")
    assert requirements["current_status"] == {
        "DEV_APPROVAL_ALLOWED": "NO",
        "DEV_EXECUTION_ALLOWED": "NO",
        "ENDPOINT": readiness.DEVELOPMENT_INCOMPLETE_ENDPOINT,
        "GRADER_EXEC_PACKAGE": "PASS",
        "OFFICIAL_GRADER_VIABILITY": "ESTABLISHED",
        "PERFORMANCE": "NOT_MEASURED",
        "SCIENTIFIC_RESULT": "NO_DEVELOPMENT_SCIENTIFIC_RESULT",
        "TRIMEM_SYSTEM_IMPLEMENTATION": "CREDENTIAL_FREE_GREEN",
    }
    authorization = requirements["development_authorization_boundary"]
    assert authorization["approval_request_eligible"] is False
    assert authorization["active_development_approval"] is False
    assert authorization["attempt_one_consumed"] is True
    assert authorization["attempt_two_allowed"] is False
    assert authorization["development_execution_authorized"] is False
    assert authorization["grader_smoke_rerun_authorized"] is False
    assert authorization["heldout_execution_authorized"] is False
    assert authorization["future_recovery_authority_received"] is False
    assert authorization["prior_failed_run_reusable"] is False
    assert authorization["recovery_authorization_received"] is True
    assert authorization["recovery_authorization"] == (
        "TRIMEM_V1_DEV_PREFLIGHT_RECOVERY_002_APPROVED_ONCE"
    )
    assert authorization["recovery_request_id"] == trigger.REQUEST_ID
    assert authorization["recovery_request_path"] == trigger.SENTINEL_PATH
    assert authorization["request_002_final"] is True
    assert authorization["request_003_allowed"] is False
    assert authorization["rerun_allowed"] is False
    assert "final and consumed" in authorization["meaning"]
    assert "PRE_DEVELOPMENT" in authorization["selected_m2_checkpoint"]
    service_boundary = requirements["credential_free_service_ci_boundary"]
    assert "ALLOWED_PRE_EXEC" in service_boundary
    assert "digest-pinned PostgreSQL and Qdrant support services" in service_boundary
    assert "official grader/benchmark target images" in service_boundary
    request = _read(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    assert request["readiness_gate"].endswith(
        "--level benchmark-approval --require-git-tracked"
    )
    assert "official grader/benchmark target image pull or run" in request["prohibited_before_approval"]
    assert "Docker image pull or run" not in request["prohibited_before_approval"]
    assert requirements["execution_counters"] == {
        "api_calls": 0,
        "cached_input_tokens": 0,
        "decomposition_calls": 0,
        "docker_pulls": 7,
        "extraction_calls": 0,
        "grader_calls": 12,
        "grader_containers": 12,
        "input_tokens": 0,
        "model_calls": 0,
        "model_gateway_calls": 0,
        "official_grader_runs": 12,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "reasoning_tokens": 0,
        "solve_calls": 0,
        "support_image_pulls": 1,
        "target_image_pulls": 6,
        "task_arm_runs": 0,
        "total_usd": 0,
    }
    assert requirements["execution_counter_scope"] == readiness.SMOKE_PASS_READINESS_SCOPE
    assert requirements["grader_smoke_exec_005_failure_closure"] == {
        "failure_receipt_path": freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
        "failure_receipt_present": False,
        "historical_p014_paths_reused": False,
        "schema": readiness.SMOKE_PASS_FAILURE_CLOSURE_STATUS_SCHEMA,
        "status": "NOT_APPLICABLE_PASS",
    }
    assert not (ROOT / freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH).exists()
    assert requirements["grader_smoke_scientific_result"] == {
        "gold_resolved": 6,
        "gold_total": 6,
        "noop_unresolved": 6,
        "noop_total": 6,
        "status": "PASS",
    }
    smoke = _read(ROOT / "artifacts/trimem_v1/grader_smoke_result.json")
    assert requirements["grader_smoke_exec_005_success_evidence"] == {
        "schema": readiness.SMOKE_PASS_SUCCESS_EVIDENCE_SCHEMA,
        "status": "PASS",
        **smoke["official_execution_evidence"],
    }
    history = requirements["historical_grader_smoke_execution"]
    assert history == readiness._validated_p014_historical_execution()
    assert history["evidence"]["failure_receipt_path"] == (
        freeze.P014_FAILURE_RECEIPT_PATH
    )
    assert history["evidence"]["evidence_inventory_path"] == (
        freeze.P014_EVIDENCE_INVENTORY_PATH
    )
    assert freeze.P014_FAILURE_RECEIPT_PATH != (
        freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
    )
    assert freeze.P014_EVIDENCE_INVENTORY_PATH != (
        freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
    )
    assert history["failure_taxonomy"] == {
        "adapter_contract_failures": 1,
        "aggregate_failures": 0,
        "environment_failures": 0,
        "image_lifecycle_failures": 0,
        "infrastructure_failures": 0,
        "official_harness_failures": 0,
        "official_report_failures": 0,
    }
    development_failure = requirements["historical_development_preflight_failure"]
    assert development_failure == readiness._validated_development_preflight_failure()
    assert development_failure["endpoint"] == readiness.DEVELOPMENT_INCOMPLETE_ENDPOINT
    assert development_failure["execution_accounting"]["task_arm_runs"] == 0
    assert development_failure["execution_accounting"]["model_calls"] == 0
    assert development_failure["execution_accounting"]["grader_containers"] == 0
    assert development_failure["recovery"] == {
        "attempt_two_allowed": False,
        "protected_execution_authorization_required": (
            trigger.REQUIRED_EXTERNAL_AUTHORIZATION
        ),
        "received_recovery_authorization": trigger.RECOVERY_AUTHORIZATION,
        "request_id": trigger.REQUEST_ID,
        "request_path": trigger.SENTINEL_PATH,
        "single_new_attempt_one_run_allowed": True,
    }
    current_failure = requirements["development_execution_failure"]
    assert current_failure == readiness._validated_development_exec_002_failure()
    assert current_failure["status"] == (
        "FINAL_CONSUMED_BEFORE_SCIENTIFIC_EXECUTION"
    )
    assert current_failure["scientific_run"] is False
    assert current_failure["performance"] == "NOT_MEASURED"
    assert current_failure["execution_accounting"] == {
        **{
            field: 0
            for field in (
                "api_calls",
                "cached_input_tokens",
                "decomposition_calls",
                "extraction_calls",
                "grader_calls",
                "grader_containers",
                "input_tokens",
                "model_calls",
                "model_gateway_calls",
                "official_grader_runs",
                "output_tokens",
                "paid_model_calls",
                "reasoning_tokens",
                "solve_calls",
                "target_image_pulls",
                "task_arm_runs",
            )
        },
        "support_service_containers": 2,
        "support_service_image_pulls": 2,
        "total_usd": 0.0,
    }
    assert current_failure["authority"] == {
        "attempt_one_consumed": True,
        "attempt_two_allowed": False,
        "future_recovery_authority_received": False,
        "request_002_final": True,
        "request_003_allowed": False,
        "rerun_allowed": False,
    }


def test_post_smoke_readiness_is_evidence_derived_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = readiness.validate_targets()
    derived = readiness.validate_readiness_plan(targets)
    assert derived["current_status"]["ENDPOINT"] == (
        readiness.DEVELOPMENT_INCOMPLETE_ENDPOINT
    )
    assert derived["current_status"]["DEV_APPROVAL_ALLOWED"] == "NO"
    assert derived["current_status"]["DEV_EXECUTION_ALLOWED"] == "NO"
    assert derived["current_status"]["PERFORMANCE"] == "NOT_MEASURED"
    assert derived["development_execution_failure"] == (
        readiness._validated_development_exec_002_failure()
    )
    assert derived["scientific_result"] == {
        "gold_resolved": 6,
        "gold_total": 6,
        "noop_unresolved": 6,
        "noop_total": 6,
        "status": "PASS",
    }
    assert derived["execution_counters"]["grader_containers"] == 12
    assert derived["execution_counters"]["target_image_pulls"] == 6
    assert derived["execution_counters"]["support_image_pulls"] == 1

    tampered = _read(ROOT / "artifacts/trimem_v1/readiness_requirements.json")
    tampered["execution_counters"]["grader_containers"] = 11
    original_read_json = readiness.read_json

    def read_json_with_tampered_plan(path: Path) -> dict:
        if path == readiness.ARTIFACT / "readiness_requirements.json":
            return deepcopy(tampered)
        return original_read_json(path)

    monkeypatch.setattr(readiness, "read_json", read_json_with_tampered_plan)
    with pytest.raises(
        readiness.ReadinessError,
        match="authoritative exec-005 counters differ",
    ):
        readiness.validate_readiness_plan(targets)
    protection = _read(
        ROOT / "artifacts/trimem_v1/grader_smoke_environment_protection.json"
    )
    assert protection["configured_before_sentinel"] is True
    assert protection["environment"] == {
        "can_admins_bypass": False,
        "id": 20971935382,
        "name": "trimem-grader-smoke-exec",
    }
    assert protection["schema"] == "trimem/grader-smoke-environment-protection/1.1"
    assert protection["observed_at_utc"] == "2026-09-01T04:18:06Z"
    assert protection["protection_rule"]["type"] == "required_reviewers"
    assert protection["branch_policies"] == {
        "branch_policies": [
            {"id": 58766765, "name": "codex/trimem-coder-v1", "type": "branch"},
            {"id": 58775497, "name": "main", "type": "branch"},
        ],
        "total_count": 2,
    }
    assert protection["secret_state_before_sentinel"]["installed_secret_names"] == []
    assert protection["secret_state_before_sentinel"]["total_count"] == 0
    readiness.validate_smoke_environment_protection(protection)


def test_development_exec_002_receipt_digest_and_semantics_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = ROOT / readiness.DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_PATH
    assert hashlib.sha256(receipt_path.read_bytes()).hexdigest() == (
        readiness.DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_RAW_SHA256
    )
    monkeypatch.setattr(
        readiness,
        "DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_RAW_SHA256",
        "0" * 64,
    )
    with pytest.raises(readiness.ReadinessError, match="receipt bytes differ"):
        readiness._validated_development_exec_002_failure()


def test_development_exec_002_semantic_drift_fails_even_with_bound_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = readiness._strict_json_bytes

    def tampered_parser(raw: bytes, *, label: str) -> dict:
        value = original(raw, label=label)
        if label == readiness.DEVELOPMENT_EXEC_002_FAILURE_RECEIPT_PATH:
            value["execution_accounting"]["support_service_containers"] = 1
        return value

    monkeypatch.setattr(readiness, "_strict_json_bytes", tampered_parser)
    with pytest.raises(readiness.ReadinessError, match="current-attempt accounting"):
        readiness._validated_development_exec_002_failure()


def test_consumed_development_failure_blocks_approval_and_execution(
    tmp_path: Path,
) -> None:
    assert readiness.preapproval_blockers() == [
        readiness.DEVELOPMENT_EXEC_002_CONSUMED_BLOCKER
    ]
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps({"approval": {"approved_phase": "DEVELOPMENT_TUNING"}}),
        encoding="utf-8",
    )
    blockers, phase = readiness.execution_blockers(approval_path)
    assert phase == "development"
    assert blockers == [readiness.DEVELOPMENT_EXEC_002_CONSUMED_BLOCKER]


def test_benchmark_exec_cli_blocks_consumed_development_attempt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        readiness,
        "validate_static",
        lambda require_git_tracked: {
            "grader_exec_package": "PASS",
            "official_grader_viability": "ESTABLISHED",
            "performance": "NOT_MEASURED",
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["trimem_verify_ready.py", "--level", "benchmark-exec"],
    )
    assert readiness.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "FAIL_CLOSED"
    assert report["blockers"] == [readiness.DEVELOPMENT_EXEC_002_CONSUMED_BLOCKER]
    assert report["git_tracked_freeze_required"] is True


def test_smoke_environment_policy_set_is_exact_and_matches_both_workflow_routes() -> None:
    protection = _read(
        ROOT / "artifacts/trimem_v1/grader_smoke_environment_protection.json"
    )
    policies = protection["branch_policies"]["branch_policies"]
    assert {row["name"] for row in policies} == {
        source_ref.removeprefix("refs/heads/")
        for source_ref in readiness.SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT.values()
    }
    for mutate in (
        lambda value: value["branch_policies"].update(total_count=1),
        lambda value: value["branch_policies"]["branch_policies"][1].update(
            id=58766765
        ),
        lambda value: value["branch_policies"]["branch_policies"][1].update(
            name="codex/trimem-coder-v1"
        ),
        lambda value: value["secret_state_before_sentinel"].update(total_count=1),
    ):
        tampered = json.loads(json.dumps(protection))
        mutate(tampered)
        with pytest.raises(readiness.ReadinessError, match="route policy set differs"):
            readiness.validate_smoke_environment_protection(tampered)


def test_benchmark_environment_policy_set_is_exact_and_zero_secret() -> None:
    protection = _read(
        ROOT / "artifacts/trimem_v1/benchmark_environment_protection.json"
    )
    readiness.validate_benchmark_environment_protection(protection)
    assert protection["environment"] == {
        "can_admins_bypass": False,
        "id": 21138935165,
        "name": "trimem-benchmark-exec",
    }
    assert protection["branch_policies"]["branch_policies"] == [
        {"id": 58983771, "name": "codex/trimem-coder-v1", "type": "branch"},
        {"id": 58983776, "name": "main", "type": "branch"},
    ]
    assert protection["secret_state_before_sentinel"] == {
        "installed_secret_names": [],
        "required_later": [
            "OPENAI_API_KEY",
            "TRIMEM_EVIDENCE_PASSPHRASE",
            "TRIMEM_EXEC_APPROVAL_B64",
        ],
        "total_count": 0,
    }
    for mutate in (
        lambda value: value["environment"].update(can_admins_bypass=True),
        lambda value: value["branch_policies"].update(total_count=1),
        lambda value: value["branch_policies"]["branch_policies"][0].update(
            name="*"
        ),
        lambda value: value["secret_state_before_sentinel"].update(total_count=1),
    ):
        tampered = deepcopy(protection)
        mutate(tampered)
        with pytest.raises(
            readiness.ReadinessError,
            match="benchmark protected environment snapshot/route policy set differs",
        ):
            readiness.validate_benchmark_environment_protection(tampered)


def test_benchmark_approval_cannot_disable_git_tracked_freeze(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: list[bool] = []
    monkeypatch.setattr(
        readiness,
        "validate_static",
        lambda require_git_tracked: observed.append(require_git_tracked) or {},
    )
    monkeypatch.setattr(readiness, "preapproval_blockers", lambda: [])
    monkeypatch.setattr(
        sys,
        "argv",
        ["trimem_verify_ready.py", "--level", "benchmark-approval"],
    )
    assert readiness.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert observed == [True]
    assert report["git_tracked_freeze_required"] is True
    assert "endpoint" not in report
    assert report["official_grader_viability"] == "NOT_YET_ESTABLISHED"


def test_readiness_report_derives_validated_post_smoke_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        readiness,
        "validate_static",
        lambda require_git_tracked: {
            "grader_exec_package": "PASS",
            "official_grader_viability": "ESTABLISHED",
            "performance": "NOT_MEASURED",
        },
    )
    monkeypatch.setattr(readiness, "preapproval_blockers", lambda: [])
    monkeypatch.setattr(
        sys,
        "argv",
        ["trimem_verify_ready.py", "--level", "benchmark-approval"],
    )
    assert readiness.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["grader_exec_package"] == "PASS"
    assert report["official_grader_viability"] == "ESTABLISHED"


def test_pre_exec_grader_gate_keeps_not_yet_established_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        readiness,
        "validate_static",
        lambda require_git_tracked: {
            "grader_exec_package": "CORRECTION_READY_FOR_EXECUTION",
            "official_grader_viability": "NOT_YET_ESTABLISHED",
            "performance": "NOT_MEASURED",
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["trimem_verify_ready.py", "--level", "grader-smoke-exec"],
    )
    assert readiness.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "FAIL_CLOSED"
    assert report["grader_exec_package"] == "CORRECTION_READY_FOR_EXECUTION"
    assert report["official_grader_viability"] == "NOT_YET_ESTABLISHED"


def test_grader_smoke_exec_gate_accepts_only_validated_005_recovery_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps({"approval": {"approved_phase": "GRADER_SMOKE"}}),
        encoding="utf-8",
    )
    calls: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        readiness,
        "validate_exec_approval",
        lambda split, path: calls.append((split, path)) or {"validated": True},
    )
    monkeypatch.setattr(
        readiness,
        "validate_selected_m2",
        lambda require_frozen: {"status": "PRE_DEVELOPMENT"},
    )
    original_read_json = readiness.read_json

    def fake_read_json(path: Path) -> dict:
        if path == readiness.ARTIFACT / "grader_smoke_result.json":
            return {"status": readiness.SMOKE_RECOVERY_STATUS}
        return original_read_json(path)

    validated_smoke: list[dict] = []
    monkeypatch.setattr(readiness, "read_json", fake_read_json)
    monkeypatch.setattr(
        readiness,
        "validate_grader_smoke_result",
        lambda smoke: validated_smoke.append(smoke) or {},
    )

    blockers, phase = readiness.execution_blockers(approval_path)
    assert blockers == []
    assert phase == "grader-smoke"
    assert calls == [("grader-smoke", approval_path)]
    assert validated_smoke == [{"status": readiness.SMOKE_RECOVERY_STATUS}]
    assert readiness.GRADER_SMOKE_REQUEST_ID == "TRIMEM_V1_GRADER_SMOKE_EXEC_005"


def test_grader_smoke_exec_gate_rejects_repeat_after_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval_path = tmp_path / "approval.json"
    approval_path.write_text(
        json.dumps({"approval": {"approved_phase": "GRADER_SMOKE"}}),
        encoding="utf-8",
    )
    original_read_json = readiness.read_json

    def fake_read_json(path: Path) -> dict:
        if path == readiness.ARTIFACT / "grader_smoke_result.json":
            return {"status": "PASS"}
        return original_read_json(path)

    monkeypatch.setattr(readiness, "read_json", fake_read_json)
    monkeypatch.setattr(readiness, "validate_exec_approval", lambda *_args: {})
    monkeypatch.setattr(readiness, "validate_grader_smoke_result", lambda _smoke: {})

    blockers, phase = readiness.execution_blockers(approval_path)
    assert phase == "grader-smoke"
    assert blockers == [
        "fresh grader-smoke execution requires the exact P0.1.5 "
        "recovery-ready state"
    ]


def _inventory_bytes(value: dict) -> bytes:
    payload = {
        "files": value["files"],
        "root": value["root"],
        "schema": value["schema"],
        "total_bytes": sum(row["bytes"] for row in value["files"]),
        "total_files": len(value["files"]),
    }
    value.update(payload)
    value["inventory_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    return _canonical(value) + b"\n"


def _official_smoke_pass_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict, dict, dict, bytes, bytes, bytes, bytes]:
    source_root = ROOT
    repository = tmp_path / "repository"
    config = repository / "configs/trimem_v1"
    artifact = repository / "artifacts/trimem_v1"
    official = artifact / "grader_smoke_official/exec-005"
    config.mkdir(parents=True)
    official.mkdir(parents=True)
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    (config / "grader_smoke_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    trusted_root_raw = (
        source_root / "configs/trimem_v1/sigstore_trusted_root.jsonl"
    ).read_bytes()
    attestation_policy_raw = (
        source_root / "configs/trimem_v1/smoke_attestation_policy.json"
    ).read_bytes()
    (config / "sigstore_trusted_root.jsonl").write_bytes(trusted_root_raw)
    (config / "smoke_attestation_policy.json").write_bytes(attestation_policy_raw)
    monkeypatch.setattr(readiness, "ROOT", repository)
    monkeypatch.setattr(readiness, "CONFIG", config)
    monkeypatch.setattr(readiness, "ARTIFACT", artifact)
    monkeypatch.setenv("GH_TOKEN", "fixture-read-only-token")

    execution_head = "b" * 40
    historical_freeze = readiness._pretty_json({
        "files": {
            readiness.SMOKE_ATTESTATION_POLICY_PATH: {
                "bytes": len(attestation_policy_raw),
                "sha256": hashlib.sha256(attestation_policy_raw).hexdigest(),
            },
            readiness.SMOKE_TRUSTED_ROOT_PATH: {
                "bytes": len(trusted_root_raw),
                "sha256": hashlib.sha256(trusted_root_raw).hexdigest(),
            },
        },
        "hash_algorithm": "sha256",
        "path_policy": "fixture",
        "schema": "trimem/freeze/1.0",
    })
    freeze_sha = hashlib.sha256(historical_freeze).hexdigest()
    request = {
        "schema": readiness.GRADER_SMOKE_REQUEST_SCHEMA,
        "phase": "GRADER_SMOKE",
        "actual_execution_authorized": False,
        "requires_external_approval": True,
        "freeze_sha256": "sha256:" + freeze_sha,
    }
    historical_request = _canonical(request) + b"\n"
    approval = {
        "approval_artifact_sha256": "a" * 64,
        "approved_request_sha256": hashlib.sha256(historical_request).hexdigest(),
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "1",
        "freeze_sha256": freeze_sha,
        "git_head": execution_head,
        "phase": "GRADER_SMOKE",
    }
    outcomes = [
        {
            "benchmark_id": target["benchmark_id"],
            "order_index": index,
            "probe": target["probe"],
            "resolved": target["expected_resolved"],
            "target_id": target["target_id"],
            "applied_patch_sha256": "c" * 64,
            "official_test_output_sha256": "d" * 64,
            "official_test_status_sha256": "e" * 64,
            "execution_contract_sha256": "6" * 64,
            "execution_control_sha256": "7" * 64,
            "submitted_patch_identity_sha256": "8" * 64,
            "patch_applied": True,
            "tests_executed": True,
            "digest_match": True,
            "submitted_patch_identity": True,
            "semantic_normalization": (
                None
                if target["benchmark_id"] == "swebench_verified"
                else _public_multi_semantics_summary(target["expected_resolved"])
            ),
            "host_prepare_sh_access_count": 0,
            "source_image_build_count": 0,
            "api_calls": 0,
            "container_exit_status_code": (
                None
                if target["benchmark_id"] == "swebench_verified"
                else (0 if target["expected_resolved"] else 1)
            ),
            "container_exit_acceptance": (
                None
                if target["benchmark_id"] == "swebench_verified"
                else (
                    "ZERO_EXIT"
                    if target["expected_resolved"]
                    else "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION"
                )
            ),
            "container_exit_status_sha256": (
                None if target["benchmark_id"] == "swebench_verified" else "9" * 64
            ),
        }
        for index, target in enumerate(manifest["targets"])
    ]
    lifecycle_raw = b'{"official":"image-lifecycle"}\n'
    lifecycle = {
        "actual": {
            "target_image_pulls": 6,
            "support_image_pulls": 1,
            "exact_image_removals": 7,
            "max_resident_target_images": 1,
            "max_resident_support_images": 1,
            "resident_target_images": 0,
            "resident_support_images": 0,
        },
        "event_count": 14,
        "report_bytes": len(lifecycle_raw),
        "report_sha256": hashlib.sha256(lifecycle_raw).hexdigest(),
        "status": "PASS",
    }
    public = {
        "schema": "trimem/public-benchmark-artifact/1.0",
        "status": "PASS",
        "manifest": "grader-smoke",
        "outcomes": outcomes,
        "stream_totals": [],
        "approval_binding": approval,
        "restricted_evidence": "ENCRYPTED_SEPARATE_ARTIFACT_NOT_PUBLIC",
        "dataset_rows_or_gold_test_payloads": "EXCLUDED_AND_EPHEMERAL_INPUTS_PURGED",
        "actual_accounting": _smoke_accounting(12),
        "api_calls": 0,
        "container_exit_status_captured_count": 8,
        "container_exit_status_validated_count": 8,
        "digest_match_count": 12,
        "empty_patch_ids": [],
        "evidence_counts": {
            name: 12 for name in (
                "patch", "tests", "container", "evaluator", "report", "digest",
                "execution_contract", "execution_control",
                "submitted_patch_identity", "applied_patch", "test_output",
                "official_test_status",
            )
        },
        "expected_target_count": 12,
        "host_prepare_sh_access_count": 0,
        "image_lifecycle": lifecycle,
        "attempted_cell_count": 12,
        "terminal_record_count": 12,
        "complete_execution_evidence_count": 12,
        "adapter_normalized_count": 12,
        "authoritative_cell_count": 12,
        "official_execution_count": 12,
        "unattempted_cell_count": 0,
        **{field: 0 for field in grader_smoke.FAILURE_TAXONOMY_FIELDS},
        "observed_target_count": 12,
        "patch_applied_count": 12,
        "probe_counts": {"GOLD": 6, "NOOP_BASELINE": 6},
        "resolved_container_zero_exit_count": 4,
        "resolved_counts": {"GOLD": 6, "NOOP_BASELINE": 0},
        "source_image_build_count": 0,
        "submitted_patch_identity_count": 12,
        "tests_executed_count": 12,
        "unresolved_counts": {"GOLD": 0, "NOOP_BASELINE": 6},
    }
    public["evidence_counts"]["container_exit_status"] = 8
    aggregate_body = {
        field: public[field] for field in readiness.SMOKE_AGGREGATE_BODY_FIELDS
    }
    aggregate_body["schema"] = "trimem/verified-aggregate/1.0"
    aggregate_sha = hashlib.sha256(_canonical(aggregate_body)).hexdigest()
    public["verified_aggregate_sha256"] = aggregate_sha
    aggregate_raw = readiness._pretty_json(
        {**aggregate_body, "aggregate_sha256": aggregate_sha}
    )
    public_raw = readiness._pretty_json(public)
    summary = {
        "schema": "trimem/grader-smoke-execution/2.0",
        "expected_target_count": 12,
        "observed_target_count": 12,
        "probe_counts": {"GOLD": 6, "NOOP_BASELINE": 6},
        "empty_patch_ids": [],
        "failures": [],
        **_smoke_accounting(12),
        "patch_applied_count": 12,
        "tests_executed_count": 12,
        "digest_match_count": 12,
        "submitted_patch_identity_count": 12,
        "host_prepare_sh_access_count": 0,
        "source_image_build_count": 0,
        "container_exit_status_captured_count": 8,
        "container_exit_status_validated_count": 8,
        "resolved_container_zero_exit_count": 4,
        "attempted_cell_count": 12,
        "terminal_record_count": 12,
        "official_execution_count": 12,
        "complete_execution_evidence_count": 12,
        "adapter_normalized_count": 12,
        "authoritative_cell_count": 12,
        "unattempted_cell_count": 0,
        **{field: 0 for field in grader_smoke.FAILURE_TAXONOMY_FIELDS},
        "status": "PASS",
    }
    summary_raw = readiness._pretty_json(summary)
    # This is the exact production PASS summary from exec-005.  Keep the
    # fixture independently sealed so a production field cannot be omitted
    # from both the readiness reconstruction and its synthetic inventory.
    assert len(summary_raw) == 1409
    assert hashlib.sha256(summary_raw).hexdigest() == (
        "40a86b900af452d04484c9d63ebe75002d643935e159a118a6489d87ec2ec4a5"
    )
    inventory_rows = [
        {"path": "aggregate.json", "sha256": hashlib.sha256(aggregate_raw).hexdigest(), "bytes": len(aggregate_raw)},
        {"path": "image-materialization/image-lifecycle-report.json", "sha256": lifecycle["report_sha256"], "bytes": lifecycle["report_bytes"]},
        {"path": "public-results.json", "sha256": hashlib.sha256(public_raw).hexdigest(), "bytes": len(public_raw)},
        {"path": "results/external-approval-evidence.json", "sha256": hashlib.sha256(readiness._pretty_json(approval)).hexdigest(), "bytes": len(readiness._pretty_json(approval))},
        {"path": "results/restricted-external-approval.json", "sha256": approval["approval_artifact_sha256"], "bytes": 257},
        {"path": "results/smoke-execution-summary.json", "sha256": hashlib.sha256(summary_raw).hexdigest(), "bytes": len(summary_raw)},
    ]
    for index, target in enumerate(manifest["targets"]):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target["target_id"])
        inventory_rows.append({
            "path": f"results/{index:03d}-{safe}/{safe}.result.json",
            "sha256": hashlib.sha256(f"result-{index}".encode()).hexdigest(),
            "bytes": 100 + index,
        })
    inventory = {
        "schema": "trimem/restricted-evidence-inventory/1.0",
        "root": "grader_smoke_exec",
        "files": sorted(inventory_rows, key=lambda row: row["path"]),
        "total_bytes": 0,
        "total_files": 0,
        "inventory_sha256": "",
    }
    inventory_raw = _inventory_bytes(inventory)
    subject = {
        "approval_binding": approval,
        "artifacts": {
            "encrypted_restricted_evidence": {
                "bytes": 4096,
                "name": "trimem-grader-smoke-restricted.tar.enc",
                "sha256": "f" * 64,
            },
            "evidence_inventory": {
                "bytes": len(inventory_raw),
                "name": "evidence-inventory.json",
                "sha256": hashlib.sha256(inventory_raw).hexdigest(),
            },
            "public_results": {
                "bytes": len(public_raw),
                "name": "public-results.json",
                "sha256": hashlib.sha256(public_raw).hexdigest(),
            },
        },
        "execution": {
            "event_name": "push",
            "repository": readiness.SMOKE_ATTESTATION_REPOSITORY,
            "runner_environment": readiness.SMOKE_ATTESTATION_RUNNER,
            "signer_workflow": readiness.SMOKE_ATTESTATION_WORKFLOW,
            "source_digest": execution_head,
            "source_ref": readiness.SMOKE_ATTESTATION_SOURCE_REF_BY_EVENT["push"],
            "workflow_run_attempt": approval["approved_workflow_run_attempt"],
            "workflow_run_id": approval["approved_workflow_run_id"],
        },
        "schema": readiness.SMOKE_ATTESTATION_SCHEMA,
    }
    subject_raw = readiness._pretty_json(subject)
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "predicate": {},
        "predicateType": "https://slsa.dev/provenance/v1",
        "subject": [{
            "digest": {"sha256": hashlib.sha256(subject_raw).hexdigest()},
            "name": "attestation-subject.json",
        }],
    }
    bundle = {
        "dsseEnvelope": {
            "payload": base64.b64encode(_canonical(statement)).decode("ascii"),
            "payloadType": "application/vnd.in-toto+json",
            "signatures": [{"sig": "ZmFrZS1zaWduYXR1cmU="}],
        },
        "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "verificationMaterial": {
            "certificate": {"rawBytes": "ZmFrZS1jZXJ0aWZpY2F0ZQ=="},
            "timestampVerificationData": {},
        },
    }
    bundle_raw = readiness._pretty_json(bundle)
    smoke = {
        "schema": "trimem/grader-smoke-result/1.0",
        "status": "PASS",
        "trimem_system_implementation": "CREDENTIAL_FREE_GREEN",
        "grader_exec_package": "PASS",
        "official_grader_viability": "ESTABLISHED",
        "performance": "NOT_MEASURED",
        "expected_unique_instances": 6,
        "expected_target_count": 12,
        "expected_condition_rows": {"GOLD": 6, "NOOP_BASELINE": 6},
        "actual_execution": {
            "docker_pulls": 7,
            "grader_containers": 12,
            "input_tokens": 0,
            "model_calls": 0,
            "official_grader_runs": 12,
            "output_tokens": 0,
            "paid_model_calls": 0,
            "total_usd": 0,
        },
        "official_execution_evidence": {
            "public_result_path": freeze.OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
            "public_result_raw_sha256": hashlib.sha256(public_raw).hexdigest(),
            "evidence_inventory_path": freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
            "evidence_inventory_raw_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "verified_aggregate_sha256": aggregate_sha,
            "aggregate_raw_sha256": hashlib.sha256(aggregate_raw).hexdigest(),
            "approval_binding": approval,
            "attestation_subject_path": freeze.OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
            "attestation_subject_raw_sha256": hashlib.sha256(subject_raw).hexdigest(),
            "attestation_bundle_path": freeze.OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
            "attestation_bundle_raw_sha256": hashlib.sha256(bundle_raw).hexdigest(),
        },
    }
    (artifact / "grader_smoke_result.json").write_bytes(readiness._pretty_json(smoke))
    (repository / freeze.OFFICIAL_SMOKE_PUBLIC_RESULT_PATH).write_bytes(public_raw)
    (repository / freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH).write_bytes(inventory_raw)
    (repository / freeze.OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH).write_bytes(subject_raw)
    (repository / freeze.OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH).write_bytes(bundle_raw)
    monkeypatch.setattr(
        readiness,
        "_bundle_certificate_bindings",
        lambda _bundle: readiness._expected_certificate_bindings(subject),
    )
    monkeypatch.setattr(readiness, "_execution_head_is_ancestor", lambda commit: commit == execution_head)
    monkeypatch.setattr(
        readiness,
        "_validate_historical_smoke_request",
        lambda commit, raw: json.loads(raw),
    )
    monkeypatch.setattr(
        readiness,
        "_historical_git_file",
        lambda commit, path: {
            "artifacts/trimem_v1/freeze.json": historical_freeze,
            readiness.GRADER_SMOKE_SENTINEL_PATH: historical_request,
            readiness.SMOKE_ATTESTATION_POLICY_PATH: attestation_policy_raw,
            readiness.SMOKE_TRUSTED_ROOT_PATH: trusted_root_raw,
        }[path],
    )
    return smoke, public, inventory, public_raw, inventory_raw, subject_raw, bundle_raw


def _rebind_public_and_inventory(
    smoke: dict, public: dict, inventory: dict
) -> tuple[bytes, bytes]:
    aggregate_body = {
        field: public[field] for field in readiness.SMOKE_AGGREGATE_BODY_FIELDS
    }
    aggregate_body["schema"] = "trimem/verified-aggregate/1.0"
    aggregate_sha = hashlib.sha256(_canonical(aggregate_body)).hexdigest()
    public["verified_aggregate_sha256"] = aggregate_sha
    aggregate_raw = readiness._pretty_json(
        {**aggregate_body, "aggregate_sha256": aggregate_sha}
    )
    public_raw = readiness._pretty_json(public)
    by_path = {row["path"]: row for row in inventory["files"]}
    by_path["aggregate.json"].update({
        "sha256": hashlib.sha256(aggregate_raw).hexdigest(),
        "bytes": len(aggregate_raw),
    })
    by_path["public-results.json"].update({
        "sha256": hashlib.sha256(public_raw).hexdigest(),
        "bytes": len(public_raw),
    })
    inventory_raw = _inventory_bytes(inventory)
    evidence = smoke["official_execution_evidence"]
    evidence.update({
        "public_result_raw_sha256": hashlib.sha256(public_raw).hexdigest(),
        "evidence_inventory_raw_sha256": hashlib.sha256(inventory_raw).hexdigest(),
        "verified_aggregate_sha256": aggregate_sha,
        "aggregate_raw_sha256": hashlib.sha256(aggregate_raw).hexdigest(),
    })
    return public_raw, inventory_raw


def _rebind_attestation(
    smoke: dict,
    subject_raw: bytes,
    bundle_raw: bytes,
    *,
    public_raw: bytes,
    inventory_raw: bytes,
) -> tuple[dict, bytes, bytes]:
    subject = json.loads(subject_raw)
    subject["artifacts"]["public_results"].update({
        "bytes": len(public_raw),
        "sha256": hashlib.sha256(public_raw).hexdigest(),
    })
    subject["artifacts"]["evidence_inventory"].update({
        "bytes": len(inventory_raw),
        "sha256": hashlib.sha256(inventory_raw).hexdigest(),
    })
    subject_raw = readiness._pretty_json(subject)
    bundle = json.loads(bundle_raw)
    statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
    statement["subject"] = [{
        "digest": {"sha256": hashlib.sha256(subject_raw).hexdigest()},
        "name": "attestation-subject.json",
    }]
    bundle["dsseEnvelope"]["payload"] = base64.b64encode(
        _canonical(statement)
    ).decode("ascii")
    bundle_raw = readiness._pretty_json(bundle)
    smoke["official_execution_evidence"].update({
        "attestation_subject_raw_sha256": hashlib.sha256(subject_raw).hexdigest(),
        "attestation_bundle_raw_sha256": hashlib.sha256(bundle_raw).hexdigest(),
    })
    return subject, subject_raw, bundle_raw


def test_self_asserted_smoke_pass_without_official_artifacts_is_rejected() -> None:
    smoke = _read(ROOT / "artifacts/trimem_v1/grader_smoke_result.json")
    smoke.pop("official_execution_evidence")
    with pytest.raises(readiness.ReadinessError, match="field set"):
        readiness.validate_grader_smoke_result(smoke)


def test_committed_smoke_pass_has_exact_authoritative_execution() -> None:
    smoke = _read(ROOT / "artifacts/trimem_v1/grader_smoke_result.json")
    actual = readiness.validate_grader_smoke_result(smoke)

    assert smoke["status"] == "PASS"
    assert smoke["grader_exec_package"] == "PASS"
    assert smoke["official_grader_viability"] == "ESTABLISHED"
    assert actual == {
        "docker_pulls": 7,
        "grader_containers": 12,
        "input_tokens": 0,
        "model_calls": 0,
        "official_grader_runs": 12,
        "output_tokens": 0,
        "paid_model_calls": 0,
        "total_usd": 0,
    }
    assert readiness.preapproval_blockers() == [
        readiness.DEVELOPMENT_EXEC_002_CONSUMED_BLOCKER
    ]


def test_recovery_ready_history_rejects_rebound_receipt_hash() -> None:
    smoke = {
        "actual_execution": dict(readiness.SMOKE_RECOVERY_ACTUAL_EXECUTION),
        "actual_execution_scope": readiness.SMOKE_RECOVERY_SCOPE,
        "endpoint": readiness.SMOKE_RECOVERY_ENDPOINT,
        "expected_condition_rows": {"GOLD": 6, "NOOP_BASELINE": 6},
        "expected_target_count": 12,
        "expected_unique_instances": 6,
        "grader_exec_package": readiness.SMOKE_RECOVERY_STATUS,
        "historical_execution": readiness._validated_p014_historical_execution(),
        "official_grader_viability": "NOT_YET_ESTABLISHED",
        "performance": "NOT_MEASURED",
        "schema": readiness.P015_FAILURE_RESULT_SCHEMA,
        "status": readiness.SMOKE_RECOVERY_STATUS,
        "trimem_system_implementation": "CREDENTIAL_FREE_GREEN",
    }
    smoke["historical_execution"]["evidence"][
        "failure_receipt_raw_sha256"
    ] = "f" * 64

    with pytest.raises(readiness.ReadinessError, match="diagnostic history binding"):
        readiness.validate_grader_smoke_result(smoke)


def _obsolete_minimal_exec_005_failure_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempted: int = 6,
    normalized: int = 5,
    taxonomy_field: str = "adapter_contract_failures",
) -> tuple[dict, dict, bytes, bytes]:
    source_head = "a" * 40
    execution_head = "b" * 40
    matrix_order = [
        f"fixture--instance-{index // 2}--"
        f"{'gold' if index % 2 == 0 else 'noop-baseline'}"
        for index in range(12)
    ]
    request = {
        "request_id": readiness.GRADER_SMOKE_REQUEST_ID,
        "schema": readiness.GRADER_SMOKE_REQUEST_SCHEMA,
        "source_head": source_head,
    }
    request_raw = _canonical(request)
    request_path = tmp_path / readiness.GRADER_SMOKE_SENTINEL_PATH
    request_path.parent.mkdir(parents=True)
    request_path.write_bytes(request_raw)
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(
        readiness,
        "validate_request_document",
        lambda *_args, **_kwargs: {
            "matrix_order": matrix_order,
            "request_id": readiness.GRADER_SMOKE_REQUEST_ID,
        },
    )

    records: list[dict] = []
    inventory_rows: list[dict] = []
    for index in range(attempted):
        target_id = matrix_order[index]
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target_id)
        terminal_raw = f"terminal-{index}".encode("ascii")
        terminal_reference = {
            "bytes": len(terminal_raw),
            "path": f"results/{index:03d}-{safe}/{safe}.result.json",
            "sha256": hashlib.sha256(terminal_raw).hexdigest(),
        }
        inventory_rows.append(terminal_reference)
        records.append({
            "target_id": target_id,
            "order_index": index,
            "probe": "GOLD" if index % 2 == 0 else "NOOP_BASELINE",
            "grader_invoked": True,
            "container_started": True,
            "official_tests_executed": True,
            "raw_test_evidence_captured": True,
            "adapter_normalized": index < normalized,
            "primary_failure_taxonomy": (
                taxonomy_field
                if index == attempted - 1
                and taxonomy_field != "aggregate_failures"
                else None
            ),
            "restricted_terminal_record": terminal_reference,
        })
    lifecycle_raw = b"synthetic lifecycle evidence"
    lifecycle_reference = {
        "bytes": len(lifecycle_raw),
        "path": "image-materialization/image-lifecycle-report.json",
        "sha256": hashlib.sha256(lifecycle_raw).hexdigest(),
    }
    inventory_rows.append(lifecycle_reference)
    inventory_rows.sort(key=lambda row: row["path"])
    inventory_payload = {
        "files": inventory_rows,
        "root": "grader_smoke_exec",
        "schema": "trimem/restricted-evidence-inventory/1.0",
        "total_bytes": sum(row["bytes"] for row in inventory_rows),
        "total_files": len(inventory_rows),
    }
    inventory = {
        **inventory_payload,
        "inventory_sha256": hashlib.sha256(
            _canonical(inventory_payload)
        ).hexdigest(),
    }
    inventory_raw = _canonical(inventory) + b"\n"
    inventory_path = tmp_path / freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_bytes(inventory_raw)

    approval = {
        "approval_artifact_sha256": "c" * 64,
        "approved_request_sha256": hashlib.sha256(request_raw).hexdigest(),
        "approved_workflow_run_attempt": "1",
        "approved_workflow_run_id": "987654321",
        "freeze_sha256": "d" * 64,
        "git_head": execution_head,
        "phase": "GRADER_SMOKE",
    }
    taxonomy = {
        field: int(field == taxonomy_field)
        for field in grader_smoke.FAILURE_TAXONOMY_FIELDS
    }
    endpoint = (
        readiness.SMOKE_FAILURE_ENDPOINT
        if taxonomy_field == "adapter_contract_failures"
        else (
            readiness.P015_SCIENTIFIC_FAILURE_ENDPOINT
            if taxonomy_field == "aggregate_failures"
            else readiness.P015_INCOMPLETE_ENDPOINT
        )
    )
    target_pulls = min(6, (attempted + 1) // 2)
    support_pulls = int(attempted > 4)
    actual = {
        **readiness.SMOKE_RECOVERY_ACTUAL_EXECUTION,
        "grader_containers": attempted,
        "official_grader_runs": attempted,
        "support_image_pulls": support_pulls,
        "target_image_pulls": target_pulls,
    }
    receipt_payload = {
        "schema": readiness.P015_FAILURE_CLOSURE_SCHEMA,
        "status": "FAIL",
        "endpoint": endpoint,
        "development_approval_allowed": False,
        "scientific_result": "NOT_AGGREGATED",
        "request_binding": {
            "path": readiness.GRADER_SMOKE_SENTINEL_PATH,
            "request_id": readiness.GRADER_SMOKE_REQUEST_ID,
            "schema": readiness.GRADER_SMOKE_REQUEST_SCHEMA,
            "raw_sha256": hashlib.sha256(request_raw).hexdigest(),
            "source_head": source_head,
        },
        "approval_binding": approval,
        "workflow_run": {
            "id": approval["approved_workflow_run_id"],
            "run_attempt": 1,
            "head_sha": execution_head,
            "conclusion": "failure",
        },
        "terminal_summary": {
            "attempted_cell_count": attempted,
            "terminal_record_count": attempted,
            "official_execution_count": attempted,
            "complete_execution_evidence_count": attempted,
            "adapter_normalized_count": normalized,
            "authoritative_cell_count": 0,
            "unattempted_cell_count": 12 - attempted,
        },
        "terminal_records": records,
        "failure_taxonomy": taxonomy,
        "actual_execution": actual,
        "image_lifecycle": {
            "target_image_pulls": target_pulls,
            "support_image_pulls": support_pulls,
            "restricted_report": lifecycle_reference,
        },
        "evidence_inventory": {
            "path": freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
            "raw_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "inventory_sha256": inventory["inventory_sha256"],
            "total_files": inventory["total_files"],
            "total_bytes": inventory["total_bytes"],
        },
    }
    receipt = {
        **receipt_payload,
        "receipt_payload_sha256": hashlib.sha256(
            _canonical(receipt_payload)
        ).hexdigest(),
    }
    receipt_raw = readiness._pretty_json(receipt)
    receipt_path = tmp_path / freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(receipt_raw)
    smoke = {
        "schema": readiness.P015_FAILURE_RESULT_SCHEMA,
        "status": "FAIL",
        "trimem_system_implementation": "CREDENTIAL_FREE_GREEN",
        "grader_exec_package": "FAIL",
        "official_grader_viability": "NOT_YET_ESTABLISHED",
        "performance": "NOT_MEASURED",
        "expected_unique_instances": 6,
        "expected_target_count": 12,
        "expected_condition_rows": {"GOLD": 6, "NOOP_BASELINE": 6},
        "actual_execution": actual,
        "endpoint": endpoint,
        "historical_execution": {},
        "official_execution_failure_evidence": {
            "failure_receipt_path": freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
            "failure_receipt_raw_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "evidence_inventory_path": freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
            "evidence_inventory_raw_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "approval_binding": approval,
        },
    }
    return smoke, receipt, receipt_raw, inventory_raw


def _fresh_exec_005_failure_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempted: int = 6,
    normalized: int = 5,
    taxonomy_field: str = "adapter_contract_failures",
    last_container_started: bool = True,
    failure_reason: str = "synthetic adapter contract failure",
    secondary_failures: tuple[str, ...] = (),
    lifecycle_error: str = "synthetic",
) -> tuple[dict, dict, bytes, bytes]:
    source_head = "a" * 40
    execution_head = "b" * 40
    matrix_order = [
        f"fixture--instance-{index // 2}--"
        f"{'gold' if index % 2 == 0 else 'noop-baseline'}"
        for index in range(12)
    ]
    if taxonomy_field == "aggregate_failures":
        attempted = 12
        normalized = 12
    frozen_material = {
        path: ("fixture:" + path).encode("utf-8")
        for path in (
            smoke_trigger.OFFICIAL_GRADER_PATH,
            smoke_trigger.ADAPTER_FAILURE_ENVELOPE_CONTRACT_PATH,
            smoke_trigger.CREDENTIAL_FREE_BUNDLE_PATH,
            smoke_trigger.FREEZE_PATH,
            smoke_trigger.FROZEN_REQUEST_PATH,
            smoke_trigger.IMAGE_LOCK_PATH,
            smoke_trigger.MANIFEST_PATH,
            smoke_trigger.MULTI_SWE_ENTRYPOINT_PATH,
            smoke_trigger.MULTI_SWE_EVALUATION_CONTRACT_LOCK_PATH,
            smoke_trigger.MULTI_SWE_REPORT_SEMANTICS_LOCK_PATH,
            smoke_trigger.MULTI_SWE_REPORT_SEMANTICS_PATH,
            smoke_trigger.MULTI_SWE_PROBE_EVIDENCE_PATH,
        )
    }
    monkeypatch.setattr(
        smoke_trigger,
        "_validate_frozen_material",
        lambda *_args, **_kwargs: (
            frozen_material,
            {"target_set_sha256": "e" * 64},
            matrix_order,
        ),
    )
    monkeypatch.setattr(
        smoke_trigger, "_resolve_probe_evidence_head", lambda *_args, **_kwargs: "f" * 40
    )
    monkeypatch.setattr(
        smoke_trigger,
        "validate_committed_evidence",
        lambda *_args, **_kwargs: {"schema": "fixture/probe-evidence/1.0", "status": "PASS"},
    )
    request = smoke_trigger.build_request_document(
        tmp_path, source_head=source_head
    )
    request_raw = _canonical(request)
    request_path = tmp_path / readiness.GRADER_SMOKE_SENTINEL_PATH
    request_path.parent.mkdir(parents=True)
    request_path.write_bytes(request_raw)
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    monkeypatch.setattr(
        readiness,
        "validate_request_document",
        lambda *_args, **_kwargs: {
            "matrix_order": matrix_order,
            "request_id": failure_closure.REQUEST_ID,
        },
    )

    approval = {
        "approval_artifact_sha256": "c" * 64,
        "approved_request_sha256": hashlib.sha256(request_raw).hexdigest(),
        "approved_workflow_run_attempt": "1",
        "approved_workflow_run_id": "987654321",
        "freeze_sha256": "d" * 64,
        "git_head": execution_head,
        "phase": "GRADER_SMOKE",
    }
    restricted_root = tmp_path / "restricted"
    results_root = restricted_root / "results"
    results_root.mkdir(parents=True)
    (results_root / "external-approval-evidence.json").write_bytes(
        readiness._pretty_json(approval)
    )

    failure_shapes = {
        "adapter_contract_failures": {
            "stage": "adapter_semantic_normalization",
            "status": "adapter_contract_failed",
            "reason": failure_reason,
        },
        "image_lifecycle_failures": {
            "stage": "image_materialization",
            "status": "image_pull_failed",
            "reason": "synthetic image lifecycle failure",
        },
        "infrastructure_failures": {
            "stage": "official_grader_invocation",
            "status": "harness_timeout",
            "reason": "synthetic infrastructure failure",
        },
        "official_harness_failures": {
            "stage": "official_harness",
            "status": "official_harness_failed",
            "reason": "synthetic harness failure",
        },
        "official_report_failures": {
            "stage": "official_report",
            "status": "official_report_failed",
            "reason": "synthetic report failure",
        },
    }
    for index in range(attempted):
        target_id = matrix_order[index]
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", target_id)
        task_root = results_root / f"{index:03d}-{safe}"
        task_root.mkdir()

        def retained(relative: str, raw: bytes) -> dict[str, object]:
            path = task_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return {
                "bytes": len(raw),
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }

        applied_patch = retained("restricted-input/applied.patch", b"fixture patch\n")
        stdout = retained("stdout.txt", b"fixture stdout\n")
        stderr = retained("stderr.txt", b"")
        restricted_values = {
            "restricted_raw_report": retained(
                "official-grader/restricted-evidence/r.bin",
                b"{}\n",
            ),
            "test_output": retained(
                "official-grader/restricted-evidence/o.bin",
                b"fixture test output\n",
            ),
            "official_test_status": retained(
                "official-grader/restricted-evidence/s.bin",
                b"{}\n",
            ),
        }

        def nested(reference: Mapping[str, object]) -> dict[str, object]:
            return {
                **reference,
                "path": str(reference["path"]).removeprefix("official-grader/"),
                "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
            }

        report = retained(
            "report.json",
            readiness._pretty_json(
                {
                    "_trimem": {
                        name: nested(reference)
                        for name, reference in restricted_values.items()
                    }
                }
            ),
        )
        normalized_cell = index < normalized
        primary = (
            failure_shapes[taxonomy_field]
            if taxonomy_field != "aggregate_failures"
            and index == attempted - 1
            else None
        )
        official_outcome = index % 2 == 0
        container_started = last_container_started or index != attempted - 1
        if taxonomy_field == "aggregate_failures" and index == attempted - 1:
            official_outcome = True
        terminal = {
            "schema": grader_smoke.TERMINAL_CELL_SCHEMA,
            "target_id": target_id,
            "order_index": index,
            "probe": "GOLD" if index % 2 == 0 else "NOOP_BASELINE",
            "grader_invoked": True,
            "container_started": container_started,
            "harness_completed": True,
            "final_report_generated": True,
            "official_tests_executed": True,
            "raw_test_evidence_captured": True,
            "submitted_patch_identity_verified": True,
            "digest_verified": True,
            "adapter_normalized": normalized_cell,
            "authoritative_cell": False,
            "official_final_report_resolved": official_outcome,
            "scientific_resolved": official_outcome if primary is None else None,
            "primary_failure": primary,
            "secondary_evidence_failures": list(secondary_failures),
            "execution_status": "SUCCESS" if primary is None else "FAILURE",
            "actual_accounting": {
                **_smoke_accounting(1),
                "grader_containers": int(container_started),
                "official_grader_runs": int(container_started),
            },
            "execution_evidence": {
                "patch_applied": normalized_cell,
                "tests_executed": normalized_cell,
                "digest_match": True,
                "submitted_patch_identity": True,
                "host_prepare_sh_access_count": 0,
                "source_image_build_count": 0,
                "api_calls": 0,
                "container_exit_status_code": None,
                "container_exit_acceptance": None,
                "container_exit_status_sha256": None,
            },
            "evidence": {
                "applied_patch": applied_patch,
                "stdout": stdout,
                "stderr": stderr,
                "report": report,
                "restricted_grader_raw": sorted(
                    restricted_values.values(), key=lambda value: str(value["path"])
                ),
            },
        }
        (task_root / f"{safe}.result.json").write_bytes(
            readiness._pretty_json(terminal)
        )

    lifecycle = {
        "schema": "trimem/grader-smoke-image-lifecycle/1.0",
        "status": "FAILED",
        "phase": "GRADER_SMOKE",
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "git_head": execution_head,
        "expected": {
            "target_image_pulls": 6,
            "support_image_pulls": 1,
            "exact_image_removals": 7,
            "max_resident_target_images": 1,
            "max_resident_support_images": 1,
        },
        "actual": {
            "target_image_pulls": 0,
            "support_image_pulls": 0,
            "exact_image_removals": 0,
            "max_resident_target_images": 0,
            "max_resident_support_images": 0,
            "resident_target_images": 0,
            "resident_support_images": 0,
        },
        "failure": {"error_type": "FixtureFailure", "error": lifecycle_error},
        "events": [],
    }
    lifecycle_path = (
        restricted_root / "image-materialization/image-lifecycle-report.json"
    )
    lifecycle_path.parent.mkdir()
    lifecycle_path.write_bytes(readiness._pretty_json(lifecycle))

    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    inventory_raw = _canonical(inventory) + b"\n"
    inventory_path = tmp_path / freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_path.write_bytes(inventory_raw)
    workflow = {
        "id": approval["approved_workflow_run_id"],
        "run_attempt": 1,
        "head_sha": execution_head,
        "conclusion": "failure",
    }
    receipt = failure_closure.build_failure_closure(
        restricted_root=restricted_root,
        inventory_raw=inventory_raw,
        request_raw=request_raw,
        approval_binding=approval,
        workflow_run=workflow,
    )
    receipt_raw = readiness._pretty_json(receipt)
    receipt_path = tmp_path / freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
    receipt_path.write_bytes(receipt_raw)
    smoke = {
        "schema": readiness.P015_FAILURE_RESULT_SCHEMA,
        "status": "FAIL",
        "trimem_system_implementation": "CREDENTIAL_FREE_GREEN",
        "grader_exec_package": "FAIL",
        "official_grader_viability": "NOT_YET_ESTABLISHED",
        "performance": "NOT_MEASURED",
        "expected_unique_instances": 6,
        "expected_target_count": 12,
        "expected_condition_rows": {"GOLD": 6, "NOOP_BASELINE": 6},
        "actual_execution": receipt["actual_execution"],
        "endpoint": receipt["endpoint"],
        "historical_execution": {},
        "official_execution_failure_evidence": {
            "failure_receipt_path": freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
            "failure_receipt_raw_sha256": hashlib.sha256(receipt_raw).hexdigest(),
            "evidence_inventory_path": freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
            "evidence_inventory_raw_sha256": hashlib.sha256(inventory_raw).hexdigest(),
            "approval_binding": approval,
        },
    }
    return smoke, receipt, receipt_raw, inventory_raw


def test_fresh_exec_005_failure_closure_is_namespaced_and_evidence_derived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    history = readiness._validated_p014_historical_execution()
    smoke, receipt, _receipt_raw, _inventory_raw = _fresh_exec_005_failure_fixture(
        tmp_path, monkeypatch
    )
    smoke["historical_execution"] = history
    monkeypatch.setattr(
        readiness, "_validated_p014_historical_execution", lambda: history
    )

    assert readiness.validate_grader_smoke_result(smoke) == (
        receipt["actual_execution"]
    )
    assert receipt["terminal_summary"] == {
        "attempted_cell_count": 6,
        "terminal_record_count": 6,
        "official_execution_count": 6,
        "complete_execution_evidence_count": 6,
        "adapter_normalized_count": 5,
        "authoritative_cell_count": 0,
        "unattempted_cell_count": 6,
    }
    assert smoke["official_execution_failure_evidence"][
        "failure_receipt_path"
    ] == freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
    assert smoke["official_execution_failure_evidence"][
        "evidence_inventory_path"
    ] == freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH


def test_failure_closure_accepts_non_authoritative_scientific_mismatch_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_exec_005_failure_fixture(tmp_path, monkeypatch)
    terminal_path = sorted(
        (tmp_path / "restricted/results").rglob("*.result.json")
    )[-1]
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["adapter_normalized"] = True
    terminal["official_final_report_resolved"] = False
    terminal["scientific_resolved"] = False
    terminal["authoritative_cell"] = False
    terminal["execution_status"] = "FAILURE"
    terminal["primary_failure"] = {
        "stage": "scientific_outcome",
        "status": "expected_outcome_mismatch",
        "reason": "official final outcome differs from the frozen GOLD/NOOP expectation",
    }

    validated = failure_closure._terminal_record(
        terminal,
        index=terminal["order_index"],
        target_id=terminal["target_id"],
    )

    assert validated["adapter_normalized"] is True
    assert validated["scientific_resolved"] is False
    assert validated["primary_failure"]["stage"] == "scientific_outcome"


def test_failure_closure_rejects_unproven_failed_adapter_phase_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fresh_exec_005_failure_fixture(tmp_path, monkeypatch)
    terminal_path = sorted(
        (tmp_path / "restricted/results").rglob("*.result.json")
    )[-1]
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    assert terminal["adapter_normalized"] is False
    terminal["execution_evidence"]["patch_applied"] = True
    terminal["execution_evidence"]["tests_executed"] = True

    with pytest.raises(
        failure_closure.FailureClosureError,
        match="execution evidence differs",
    ):
        failure_closure._terminal_record(
            terminal,
            index=terminal["order_index"],
            target_id=terminal["target_id"],
        )


def test_exec_005_failure_closure_rejects_non_derived_terminal_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, receipt, _receipt_raw, inventory_raw = _fresh_exec_005_failure_fixture(
        tmp_path, monkeypatch
    )
    receipt["terminal_summary"]["adapter_normalized_count"] = 6
    payload = {
        key: value for key, value in receipt.items()
        if key != "receipt_payload_sha256"
    }
    receipt["receipt_payload_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    with pytest.raises(readiness.ReadinessError, match="evidence-derived"):
        readiness._validated_p015_failure_closure(
            readiness._pretty_json(receipt), inventory_raw
        )


def test_exec_005_official_execution_count_uses_container_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, receipt, _receipt_raw, _inventory_raw = _fresh_exec_005_failure_fixture(
        tmp_path,
        monkeypatch,
        last_container_started=False,
    )

    assert receipt["terminal_summary"]["attempted_cell_count"] == 6
    assert receipt["terminal_summary"]["official_execution_count"] == 5
    assert receipt["actual_execution"]["grader_containers"] == 5
    assert receipt["actual_execution"]["official_grader_runs"] == 5


def test_exec_005_failure_closure_rejects_missing_terminal_raw_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, receipt, _receipt_raw, _inventory_raw = _fresh_exec_005_failure_fixture(
        tmp_path, monkeypatch
    )
    restricted_root = tmp_path / "restricted"
    missing = sorted(
        restricted_root.rglob(
            "official-grader/restricted-evidence/s.bin"
        )
    )[-1]
    missing.unlink()
    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    inventory_raw = _canonical(inventory) + b"\n"
    request_raw = (tmp_path / readiness.GRADER_SMOKE_SENTINEL_PATH).read_bytes()

    with pytest.raises(
        failure_closure.FailureClosureError,
        match="terminal restricted grader evidence.*not inventory-bound",
    ):
        failure_closure.build_failure_closure(
            restricted_root=restricted_root,
            inventory_raw=inventory_raw,
            request_raw=request_raw,
            approval_binding=receipt["approval_binding"],
            workflow_run=receipt["workflow_run"],
        )


def test_failure_closure_validates_all_bytes_behind_provisional_terminal(
    tmp_path: Path,
) -> None:
    restricted_root = tmp_path / "restricted"
    task_prefix = "results/000-target"
    applied_relative = f"{task_prefix}/restricted-input/applied.patch"
    grader_relative = (
        f"{task_prefix}/official-grader/restricted-evidence/partial.bin"
    )
    rows: dict[str, dict[str, object]] = {}
    for relative, raw in (
        (applied_relative, b"patch\n"),
        (grader_relative, b"partial grader bytes\n"),
    ):
        path = restricted_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        rows[relative] = {
            "path": relative,
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    record = {
        "grader_invoked": True,
        "container_started": False,
        "harness_completed": False,
        "final_report_generated": False,
        "official_tests_executed": False,
        "raw_test_evidence_captured": False,
        "submitted_patch_identity_verified": False,
        "digest_verified": False,
        "adapter_normalized": False,
        "authoritative_cell": False,
        "official_final_report_resolved": None,
        "scientific_resolved": None,
        "primary_failure": {
            "stage": "official_grader_invocation",
            "status": "grader_invocation_incomplete",
            "reason": "runner did not durably observe a return",
        },
        "evidence": {
            "applied_patch": {
                **rows[applied_relative],
                "path": "restricted-input/applied.patch",
            },
            "restricted_grader_raw": [],
        },
    }

    failure_closure._terminal_evidence_bytes(
        restricted_root=restricted_root,
        inventory_rows=rows,
        terminal_path=f"{task_prefix}/target.result.json",
        record=record,
    )

    (restricted_root / grader_relative).write_bytes(b"tampered\n")
    with pytest.raises(
        failure_closure.FailureClosureError,
        match="provisional terminal retained evidence.*differ",
    ):
        failure_closure._terminal_evidence_bytes(
            restricted_root=restricted_root,
            inventory_rows=rows,
            terminal_path=f"{task_prefix}/target.result.json",
            record=record,
        )


def test_exec_005_public_failure_receipt_hashes_restricted_failure_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_secret = "SECRET_TEST_NAME::private/path/test_hidden.py"
    secondary_secret = "TOKEN_LIKE_VALUE::do-not-publish"
    lifecycle_secret = "C:/private/runner/work/repository"
    _smoke, receipt, receipt_raw, _inventory_raw = _fresh_exec_005_failure_fixture(
        tmp_path,
        monkeypatch,
        failure_reason=primary_secret,
        secondary_failures=(secondary_secret,),
        lifecycle_error=lifecycle_secret,
    )

    assert primary_secret.encode() not in receipt_raw
    assert secondary_secret.encode() not in receipt_raw
    assert lifecycle_secret.encode() not in receipt_raw
    terminal = receipt["terminal_records"][-1]
    assert terminal["primary_failure_summary"]["reason"] == {
        "bytes": len(primary_secret.encode()),
        "sha256": hashlib.sha256(primary_secret.encode()).hexdigest(),
    }
    assert terminal["secondary_evidence_failure_summary"]["count"] == 1
    assert receipt["image_lifecycle"]["failure_summary"]["present"] is True


@pytest.mark.parametrize(
    ("stage", "taxonomy"),
    [
        ("EXEC_GATE", "environment_failures"),
        ("BENCHMARK_ENVIRONMENT_VALIDATION", "environment_failures"),
        ("HARNESS_PREPARATION", "infrastructure_failures"),
        ("CELL_PREPARATION", "infrastructure_failures"),
        ("IMAGE_LIFECYCLE_INITIALIZATION", "image_lifecycle_failures"),
    ],
)
def test_exec_005_pre_cell_failure_closes_from_explicit_stage_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    taxonomy: str,
) -> None:
    seed_root = tmp_path / "seed"
    _smoke, seed_receipt, _raw, _inventory = _fresh_exec_005_failure_fixture(
        seed_root, monkeypatch
    )
    request_raw = (
        seed_root / readiness.GRADER_SMOKE_SENTINEL_PATH
    ).read_bytes()
    approval = seed_receipt["approval_binding"]
    restricted_root = tmp_path / "pre-cell"
    results_root = restricted_root / "results"
    stage_evidence.write_pre_cell_failure_evidence(
        results_root,
        approval_binding=approval,
        stage=stage,
        reason="synthetic caught pre-cell failure",
    )
    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    inventory_raw = _canonical(inventory) + b"\n"

    receipt = failure_closure.build_failure_closure(
        restricted_root=restricted_root,
        inventory_raw=inventory_raw,
        request_raw=request_raw,
        approval_binding=approval,
        workflow_run=seed_receipt["workflow_run"],
    )
    validated = failure_closure.validate_failure_closure(
        readiness._pretty_json(receipt),
        inventory_raw,
        request_raw=request_raw,
        restricted_root=restricted_root,
    )

    assert validated["endpoint"] == readiness.P015_INCOMPLETE_ENDPOINT
    assert validated["terminal_summary"] == {
        "attempted_cell_count": 0,
        "terminal_record_count": 0,
        "official_execution_count": 0,
        "complete_execution_evidence_count": 0,
        "adapter_normalized_count": 0,
        "authoritative_cell_count": 0,
        "unattempted_cell_count": 12,
    }
    assert validated["failure_taxonomy"][taxonomy] == 1
    assert sum(validated["failure_taxonomy"].values()) == 1
    assert validated["actual_execution"] == stage_evidence.ZERO_EXECUTION
    assert validated["image_lifecycle"]["status"] == "NOT_STARTED"


def test_runner_prepare_harness_failure_writes_valid_pre_cell_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval_raw = b"fixture protected approval bytes"
    approval_path = tmp_path / "approval.json"
    approval_path.write_bytes(approval_raw)
    approval = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": "a" * 64,
        "approved_workflow_run_attempt": "1",
        "approved_workflow_run_id": "123456789",
        "freeze_sha256": "b" * 64,
        "git_head": "c" * 40,
        "phase": "GRADER_SMOKE",
    }
    monkeypatch.setattr(
        grader_smoke,
        "validate_exec_approval",
        lambda *_args, **_kwargs: dict(approval),
    )
    monkeypatch.setattr(grader_smoke, "validate_benchmark_environment", lambda: None)
    monkeypatch.setattr(grader_smoke, "read_json", lambda _path: {"targets": []})
    monkeypatch.setattr(grader_smoke, "_smoke_targets", lambda _manifest: [])
    monkeypatch.setattr(grader_smoke, "_rows_for_targets", lambda *_args: {})
    monkeypatch.setattr(grader_smoke, "image_entries", lambda **_kwargs: ({}, []))

    def fail_prepare(_root: Path) -> object:
        raise grader_smoke.BenchmarkExecutionError("fixture harness lock failure")

    monkeypatch.setattr(grader_smoke, "prepare_harnesses", fail_prepare)
    results_root = tmp_path / "restricted/results"
    with pytest.raises(
        grader_smoke.BenchmarkExecutionError, match="fixture harness lock failure"
    ):
        grader_smoke._run_smoke_impl(
            approval_path,
            results_root,
            tmp_path / "restricted/image-materialization",
            [],
            [],
        )

    evidence_path = results_root / "pre-cell-failure-evidence.json"
    assert evidence_path.is_file()
    evidence = stage_evidence.validate_pre_cell_failure_evidence(
        json.loads(evidence_path.read_text(encoding="utf-8"))
    )
    assert evidence["stage"] == "HARNESS_PREPARATION"
    assert evidence["failure_taxonomy"] == "infrastructure_failures"
    assert evidence["actual_execution"] == stage_evidence.ZERO_EXECUTION


def test_exec_005_failed_image_pull_counts_attempt_not_materialization(
    tmp_path: Path,
) -> None:
    restricted_root = tmp_path / "restricted"
    image_root = restricted_root / "image-materialization"
    stage_root = image_root / "000-pull"
    stage_root.mkdir(parents=True)
    image = "registry.example/target@sha256:" + "a" * 64
    stdout_raw = b""
    stderr_raw = b"pull failed\n"
    (stage_root / "stdout.txt").write_bytes(stdout_raw)
    (stage_root / "stderr.txt").write_bytes(stderr_raw)
    stage_record = {
        "argv": ["docker", "pull", image],
        "returncode": 1,
        "stage": "pull",
        "status": "NONZERO",
        "stdout": {
            "path": "000-pull/stdout.txt",
            "bytes": len(stdout_raw),
            "sha256": hashlib.sha256(stdout_raw).hexdigest(),
        },
        "stderr": {
            "path": "000-pull/stderr.txt",
            "bytes": len(stderr_raw),
            "sha256": hashlib.sha256(stderr_raw).hexdigest(),
        },
    }
    (stage_root / "stage.json").write_bytes(readiness._pretty_json(stage_record))
    approval = {
        "approval_artifact_sha256": "a" * 64,
        "approved_request_sha256": "b" * 64,
        "approved_workflow_run_attempt": "1",
        "approved_workflow_run_id": "123",
        "freeze_sha256": "c" * 64,
        "git_head": "d" * 40,
        "phase": "GRADER_SMOKE",
    }
    lifecycle = {
        "schema": "trimem/grader-smoke-image-lifecycle/1.0",
        "status": "FAILED",
        "phase": "GRADER_SMOKE",
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "git_head": approval["git_head"],
        "expected": {
            "target_image_pulls": 6,
            "support_image_pulls": 1,
            "exact_image_removals": 7,
            "max_resident_target_images": 1,
            "max_resident_support_images": 1,
        },
        "actual": {
            "target_image_pulls": 0,
            "support_image_pulls": 0,
            "exact_image_removals": 0,
            "max_resident_target_images": 1,
            "max_resident_support_images": 0,
            "resident_target_images": 1,
            "resident_support_images": 0,
        },
        "failure": {"error_type": "BenchmarkExecutionError", "error": "pull failed"},
        "events": [
            {
                "action": "PULL_TARGET_FAILED",
                "identity": "fixture-target",
                "image": image,
                "pull_materialized": False,
                "failure_stage": "PULL",
                "error_type": "BenchmarkExecutionError",
                "error": "pull failed",
            }
        ],
    }
    lifecycle_path = image_root / "image-lifecycle-report.json"
    lifecycle_path.write_bytes(readiness._pretty_json(lifecycle))
    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    rows = {row["path"]: row for row in inventory["files"]}

    projected = failure_closure._lifecycle_projection(
        lifecycle_path.read_bytes(),
        reference=rows["image-materialization/image-lifecycle-report.json"],
        approval=approval,
        restricted_root=restricted_root,
        inventory_rows=rows,
    )

    assert projected["target_image_pulls"] == 1
    assert projected["target_image_materialized_count"] == 0
    assert projected["pull_attempts"][0]["pull_status"] == "NONZERO"
    assert projected["pull_attempts"][0]["outcome"] == "PULL_NONZERO"


def test_exec_005_pass_lifecycle_public_projection_validates_without_private_failure() -> None:
    digest = "registry.example/image@sha256:" + "a" * 64
    stage = {"bytes": 1, "path": "image-stage", "sha256": "b" * 64}
    attempts = [
        {
            "action": "PULL_TARGET",
            "image": digest,
            "outcome": "SUCCESS",
            "image_materialized": True,
            "pull_status": "PASS",
            "pull_returncode": 0,
            "restricted_pull_stage": stage,
            "inspect_status": "PASS",
            "inspect_returncode": 0,
            "restricted_inspect_stage": stage,
        }
        for _ in range(6)
    ]
    attempts.append(
        {
            "action": "PULL_SUPPORT",
            "image": digest,
            "outcome": "SUCCESS",
            "image_materialized": True,
            "pull_status": "PASS",
            "pull_returncode": 0,
            "restricted_pull_stage": stage,
            "inspect_status": "PASS",
            "inspect_returncode": 0,
            "restricted_inspect_stage": stage,
        }
    )
    projection = {
        "status": "PASS",
        "target_image_pulls": 6,
        "support_image_pulls": 1,
        "target_image_materialized_count": 6,
        "support_image_materialized_count": 1,
        "exact_image_removals": 7,
        "max_resident_target_images": 1,
        "max_resident_support_images": 1,
        "resident_target_images": 0,
        "resident_support_images": 0,
        "failure_summary": {"present": False, "bytes": 0, "sha256": None},
        "pull_attempts": attempts,
        "restricted_report": {
            "bytes": 1,
            "path": "image-materialization/image-lifecycle-report.json",
            "sha256": "c" * 64,
        },
    }

    assert failure_closure._validate_lifecycle_projection(projection) == projection


def test_exec_005_failure_closure_rejects_taxonomy_endpoint_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, receipt, _receipt_raw, inventory_raw = _fresh_exec_005_failure_fixture(
        tmp_path, monkeypatch
    )
    receipt["endpoint"] = readiness.P015_INCOMPLETE_ENDPOINT
    payload = {
        key: value for key, value in receipt.items()
        if key != "receipt_payload_sha256"
    }
    receipt["receipt_payload_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    with pytest.raises(readiness.ReadinessError, match="endpoint|evidence-derived"):
        readiness._validated_p015_failure_closure(
            readiness._pretty_json(receipt), inventory_raw
        )


def test_p014_and_exec_005_failure_evidence_are_not_cross_acceptable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, _receipt, fresh_receipt_raw, fresh_inventory_raw = (
        _fresh_exec_005_failure_fixture(tmp_path, monkeypatch)
    )
    legacy_receipt_raw = (ROOT / freeze.P014_FAILURE_RECEIPT_PATH).read_bytes()
    legacy_inventory_raw = (ROOT / freeze.P014_EVIDENCE_INVENTORY_PATH).read_bytes()
    with pytest.raises(readiness.ReadinessError, match="field set"):
        readiness._validated_p015_failure_closure(
            legacy_receipt_raw, legacy_inventory_raw
        )

    legacy_root = tmp_path / "legacy-rebound"
    legacy_receipt = legacy_root / freeze.P014_FAILURE_RECEIPT_PATH
    legacy_inventory = legacy_root / freeze.P014_EVIDENCE_INVENTORY_PATH
    legacy_receipt.parent.mkdir(parents=True)
    legacy_receipt.write_bytes(fresh_receipt_raw)
    legacy_inventory.write_bytes(fresh_inventory_raw)
    with pytest.raises(ValueError, match="exact payload|byte count"):
        readiness.validate_committed_failure_evidence(legacy_root)


def test_p015_contract_artifacts_are_bound_to_production_projections() -> None:
    validated = readiness.validate_p015_semantics_and_envelope_contracts()
    semantics_path = (
        ROOT / "artifacts/trimem_v1/multi_swe_report_semantics_lock.json"
    )
    envelope_path = (
        ROOT / "artifacts/trimem_v1/adapter_failure_envelope_contract.json"
    )
    semantics = _read(semantics_path)
    envelope = _read(envelope_path)

    assert validated["status"] == "PASS"
    assert validated["source_blobs"] == 5
    assert validated["module_sha256"] == semantics["implementation"]["sha256"]
    assert validated["lock_sha256"] == semantics["lock_sha256"]
    assert validated["adapter_failure_envelope_contract_sha256"] == (
        hashlib.sha256(envelope_path.read_bytes()).hexdigest()
    )
    assert set(envelope["failure_taxonomy_fields"]) == set(
        grader_smoke.FAILURE_TAXONOMY_FIELDS
    )
    assert envelope["terminal_cell"]["schema"] == grader_smoke.TERMINAL_CELL_SCHEMA
    assert set(envelope["terminal_cell"]["required_lifecycle_fields"]) == set(
        grader_smoke.TERMINAL_LIFECYCLE_FIELDS
    )
    assert set(envelope["terminal_cell"]["record_fields"]) == set(
        grader_smoke.TERMINAL_CELL_FIELDS
    )
    assert envelope["failure_taxonomy_rules"] == [
        {
            "counter": rule["counter"],
            "exact_stages": list(rule["exact_stages"]),
            "fallback": rule["fallback"],
            "stage_prefixes": list(rule["stage_prefixes"]),
        }
        for rule in grader_smoke.FAILURE_TAXONOMY_RULES
    ]
    assert envelope["terminal_accounting"]["official_execution_count"] == (
        "sum(container_started is true)"
    )
    assert envelope["terminal_accounting"]["historical_six_five_fixture"] == (
        readiness._validated_p014_historical_execution()["campaign"]
    )


def test_smoke_result_unknown_status_fails_closed() -> None:
    smoke = _read(ROOT / "artifacts/trimem_v1/grader_smoke_result.json")
    smoke["status"] = "PENDINGISH"
    with pytest.raises(readiness.ReadinessError, match="status is unknown"):
        readiness.validate_grader_smoke_result(smoke)


def test_official_smoke_pass_requires_cross_bound_public_inventory_and_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke, _public, _inventory, _public_raw, _inventory_raw, _subject_raw, _bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    assert readiness.validate_grader_smoke_result(smoke)["official_grader_runs"] == 12


@pytest.mark.parametrize("artifact_name", ["public", "inventory", "subject", "bundle"])
def test_official_smoke_pass_rejects_exact_raw_byte_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact_name: str
) -> None:
    smoke, _public, _inventory, public_raw, inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    values = {
        "public": public_raw,
        "inventory": inventory_raw,
        "subject": subject_raw,
        "bundle": bundle_raw,
    }
    values[artifact_name] += b" "
    with pytest.raises(readiness.ReadinessError, match="committed bytes"):
        readiness._validate_official_smoke_pass(
            smoke, public_raw=values["public"], inventory_raw=values["inventory"],
            subject_raw=values["subject"], bundle_raw=values["bundle"],
        )


def test_official_smoke_pass_rejects_resealed_inventory_missing_restricted_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke, _public, inventory, public_raw, _inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    inventory["files"] = [
        row for row in inventory["files"]
        if row["path"] != "results/restricted-external-approval.json"
    ]
    inventory_raw = _inventory_bytes(inventory)
    smoke["official_execution_evidence"]["evidence_inventory_raw_sha256"] = (
        hashlib.sha256(inventory_raw).hexdigest()
    )
    subject, subject_raw, bundle_raw = _rebind_attestation(
        smoke,
        subject_raw,
        bundle_raw,
        public_raw=public_raw,
        inventory_raw=inventory_raw,
    )
    monkeypatch.setattr(
        readiness,
        "_bundle_certificate_bindings",
        lambda _bundle: readiness._expected_certificate_bindings(subject),
    )
    with pytest.raises(readiness.ReadinessError, match="restricted approval"):
        readiness._validate_official_smoke_pass(
            smoke, public_raw=public_raw, inventory_raw=inventory_raw,
            subject_raw=subject_raw, bundle_raw=bundle_raw,
        )


def test_official_smoke_pass_rejects_fully_resealed_scientific_outcome_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke, public, inventory, _public_raw, _inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    public["outcomes"][0]["resolved"] = False
    public_raw, inventory_raw = _rebind_public_and_inventory(
        smoke, public, inventory
    )
    with pytest.raises(readiness.ReadinessError, match="outcome 0|attestation public_results"):
        readiness._validate_official_smoke_pass(
            smoke, public_raw=public_raw, inventory_raw=inventory_raw,
            subject_raw=subject_raw, bundle_raw=bundle_raw,
        )


def test_pass_state_adds_exact_public_artifacts_to_dynamic_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(freeze, "FROZEN_PATHS", ())
    monkeypatch.setattr(freeze, "referenced_blob_paths", lambda root: ())
    smoke_path = tmp_path / "artifacts/trimem_v1/grader_smoke_result.json"
    selected_path = tmp_path / "configs/trimem_v1/selected_m2.json"
    smoke_path.parent.mkdir(parents=True)
    selected_path.parent.mkdir(parents=True)
    selected_path.write_text('{"status":"PRE_DEVELOPMENT"}', encoding="utf-8")
    smoke_path.write_text(json.dumps({
        "status": "PASS",
        "official_execution_evidence": {
            "attestation_bundle_path": freeze.OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
            "attestation_subject_path": freeze.OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
            "public_result_path": freeze.OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
            "evidence_inventory_path": freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
        },
    }), encoding="utf-8")
    assert set(freeze.frozen_paths(tmp_path)) == {
        freeze.OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
        freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
        freeze.OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
        freeze.OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
    }


def test_fail_state_adds_only_exact_failure_artifacts_to_dynamic_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(freeze, "FROZEN_PATHS", ())
    monkeypatch.setattr(freeze, "referenced_blob_paths", lambda root: ())
    smoke_path = tmp_path / "artifacts/trimem_v1/grader_smoke_result.json"
    selected_path = tmp_path / "configs/trimem_v1/selected_m2.json"
    receipt_path = tmp_path / freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH
    inventory_path = tmp_path / freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH
    smoke_path.parent.mkdir(parents=True)
    selected_path.parent.mkdir(parents=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    selected_path.write_text('{"status":"PRE_DEVELOPMENT"}', encoding="utf-8")
    receipt_path.write_text("{}", encoding="utf-8")
    inventory_path.write_text("{}", encoding="utf-8")
    smoke_path.write_text(json.dumps({
        "status": "FAIL",
        "official_execution_failure_evidence": {
            "failure_receipt_path": freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
            "evidence_inventory_path": freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
        },
    }), encoding="utf-8")

    assert set(freeze.frozen_paths(tmp_path)) == {
        freeze.OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
        freeze.OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
    }


def _mock_gh_verification_output(subject_raw: bytes, bundle_raw: bytes) -> bytes:
    subject = json.loads(subject_raw)
    bundle = json.loads(bundle_raw)
    certificate = readiness._expected_certificate_bindings(subject)
    cert_identity = readiness._smoke_cert_identity(
        subject["execution"]["source_ref"]
    )
    certificate.pop("protectedEnvironment")
    statement = json.loads(base64.b64decode(bundle["dsseEnvelope"]["payload"]))
    value = [{
        "attestation": {"bundle": bundle, "bundle_url": "", "initiator": ""},
        "verificationResult": {
            "mediaType": "application/vnd.dev.sigstore.verificationresult+json;version=0.1",
            "signature": {"certificate": certificate},
            "statement": statement,
            "verifiedIdentity": {
                "issuer": {"issuer": "", "regexp": ".*"},
                "runnerEnvironment": readiness.SMOKE_ATTESTATION_RUNNER,
                "subjectAlternativeName": {
                    "subjectAlternativeName": cert_identity,
                },
            },
            "verifiedTimestamps": [{
                "timestamp": "2026-09-01T00:00:00Z",
                "type": "TimestampAuthority",
                "uri": "timestamp.githubapp.com",
            }],
        },
    }]
    return _canonical(value)


def _mock_live_run_attempt_output(
    subject_raw: bytes, *, status: str = "completed", conclusion: str = "success"
) -> bytes:
    execution = json.loads(subject_raw)["execution"]
    return _canonical({
        "conclusion": conclusion,
        "event": execution["event_name"],
        "head_branch": execution["source_ref"].removeprefix("refs/heads/"),
        "head_sha": execution["source_digest"],
        "id": int(execution["workflow_run_id"]),
        "path": readiness.SMOKE_ATTESTATION_WORKFLOW,
        "repository_full_name": readiness.SMOKE_ATTESTATION_REPOSITORY,
        "run_attempt": int(execution["workflow_run_attempt"]),
        "status": status,
        "workflow_id": 123456789,
    })


def test_pre_frozen_sigstore_trusted_root_policy_is_exact() -> None:
    policy = readiness.validate_smoke_attestation_policy()
    trusted = policy["trusted_root"]
    raw = (ROOT / trusted["path"]).read_bytes()
    assert len(raw) == 34634
    assert raw.count(b"\n") == 2
    assert hashlib.sha256(raw).hexdigest() == trusted["raw_sha256"]


def test_attestation_subject_routes_only_sentinel_push_or_post_merge_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approval = {
        "approval_artifact_sha256": "a" * 64,
        "approved_request_sha256": "b" * 64,
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "1",
        "freeze_sha256": "c" * 64,
        "git_head": "d" * 40,
        "phase": "GRADER_SMOKE",
    }
    validated = {**approval, "approval": {}, "approval_document": {}}
    monkeypatch.setattr(
        smoke_attestation, "validate_exec_approval", lambda *_args: validated
    )
    public = tmp_path / "public-results.json"
    inventory = tmp_path / "evidence-inventory.json"
    encrypted = tmp_path / "restricted.tar.enc"
    approval_file = tmp_path / "approval.json"
    public.write_text(
        json.dumps({"approval_binding": approval, "status": "PASS"}),
        encoding="utf-8",
    )
    inventory.write_bytes(b"inventory")
    encrypted.write_bytes(b"ciphertext")
    approval_file.write_bytes(b"approval")
    for event_name, source_ref in smoke_attestation.SOURCE_REF_BY_EVENT.items():
        subject = smoke_attestation.build_subject(
            public_result=public,
            evidence_inventory=inventory,
            encrypted_evidence=encrypted,
            approval_file=approval_file,
            repository=smoke_attestation.EXPECTED_REPOSITORY,
            source_ref=source_ref,
            event_name=event_name,
            source_digest=approval["git_head"],
            run_id=approval["approved_workflow_run_id"],
            run_attempt=approval["approved_workflow_run_attempt"],
            runner_environment=smoke_attestation.HOSTED_RUNNER,
        )
        assert subject["execution"]["event_name"] == event_name
        assert subject["execution"]["source_ref"] == source_ref
    with pytest.raises(
        smoke_attestation.AttestationSubjectError, match="event/source ref"
    ):
        smoke_attestation.build_subject(
            public_result=public,
            evidence_inventory=inventory,
            encrypted_evidence=encrypted,
            approval_file=approval_file,
            repository=smoke_attestation.EXPECTED_REPOSITORY,
            source_ref="refs/heads/codex/trimem-coder-v1",
            event_name="workflow_dispatch",
            source_digest=approval["git_head"],
            run_id=approval["approved_workflow_run_id"],
            run_attempt=approval["approved_workflow_run_attempt"],
            runner_environment=smoke_attestation.HOSTED_RUNNER,
        )


def test_certificate_oids_require_canonical_definite_der_utf8() -> None:
    value = b"trimem-grader-smoke-exec"
    assert readiness._decode_utf8_extension(
        b"\x0c" + bytes([len(value)]) + value,
        oid=readiness.SMOKE_PROTECTED_ENVIRONMENT_OID,
    ) == value.decode("ascii")
    identity = b"x" * 130
    assert readiness._decode_utf8_extension(
        b"\x0c\x81\x82" + identity,
        oid="1.3.6.1.4.1.57264.1.9",
    ) == identity.decode("ascii")
    large = b"y" * 256
    assert readiness._decode_utf8_extension(
        b"\x0c\x82\x01\x00" + large,
        oid="1.3.6.1.4.1.57264.1.9",
    ) == large.decode("ascii")
    for malformed in (
        b"\x0c\x81" + bytes([len(value)]) + value,
        b"\x0c\x80" + value,
        b"\x0c\x82\x00\x82" + identity,
        b"\x0c\x81\x82" + identity[:-1],
        b"\x0c\x81\x82" + identity + b"x",
        b"\x0c" + bytes([len(value)]) + value + b"x",
        b"\x16" + bytes([len(value)]) + value,
    ):
        with pytest.raises(readiness.ReadinessError, match="certificate OID"):
            readiness._decode_utf8_extension(
                malformed, oid=readiness.SMOKE_PROTECTED_ENVIRONMENT_OID
            )


def test_official_smoke_pass_rejects_post_execution_trust_root_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    smoke, _public, _inventory, public_raw, inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    root_path = tmp_path / "repository" / readiness.SMOKE_TRUSTED_ROOT_PATH
    root_path.write_bytes(root_path.read_bytes() + b"\n")
    with pytest.raises(readiness.ReadinessError, match="post-smoke mutation"):
        readiness._validate_official_smoke_pass(
            smoke,
            public_raw=public_raw,
            inventory_raw=inventory_raw,
            subject_raw=subject_raw,
            bundle_raw=bundle_raw,
        )


def test_paid_phase_attestation_gate_rejects_missing_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _official_smoke_pass_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: None)
    with pytest.raises(readiness.ReadinessError, match="gh CLI is required"):
        readiness.verify_official_smoke_attestation_cryptographically()


def test_paid_phase_attestation_gate_rejects_missing_actions_read_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _official_smoke_pass_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(readiness.ReadinessError, match="GH_TOKEN is required"):
        readiness.verify_official_smoke_attestation_cryptographically()


def test_paid_phase_attestation_gate_rejects_gh_verification_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _official_smoke_pass_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        readiness.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0 if command[1:] == ["--version"] else 1,
            stdout=(
                b"gh version 2.97.0 (2026-07-31)\n"
                if command[1:] == ["--version"] else b""
            ),
            stderr=(b"" if command[1:] == ["--version"] else b"signature failure"),
        ),
    )
    with pytest.raises(readiness.ReadinessError, match="cryptographic.*failed"):
        readiness.verify_official_smoke_attestation_cryptographically()


def test_paid_phase_attestation_gate_rejects_gh_version_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _official_smoke_pass_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        readiness.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=b"gh version 2.98.0 (2026-09-02)\n", stderr=b""
        ),
    )
    with pytest.raises(readiness.ReadinessError, match="CLI version differs"):
        readiness.verify_official_smoke_attestation_cryptographically()


def test_paid_phase_attestation_gate_uses_exact_custom_root_and_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, _public, _inventory, _public_raw, _inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "/usr/bin/gh")

    def fake_run(command, **kwargs):
        commands.append(list(command))
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=b"gh version 2.97.0 (2026-07-31)\n", stderr=b""
            )
        if command[1:3] == ["api", "--hostname"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=_mock_live_run_attempt_output(subject_raw),
                stderr=b"",
            )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=_mock_gh_verification_output(subject_raw, bundle_raw),
            stderr=b"",
        )

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)
    readiness.verify_official_smoke_attestation_cryptographically()
    assert len(commands) == 3
    assert commands[0] == ["/usr/bin/gh", "--version"]
    command = commands[1]
    assert command[:3] == ["/usr/bin/gh", "attestation", "verify"]
    for exact in (
        "--custom-trusted-root",
        "--cert-identity",
        "--cert-oidc-issuer",
        "--deny-self-hosted-runners",
        "--signer-digest",
        "--source-digest",
        "--source-ref",
        "--predicate-type=https://slsa.dev/provenance/v1",
        "--digest-alg=sha256",
        "--format=json",
    ):
        assert exact in command
    assert "--signer-workflow" not in command
    live_command = commands[2]
    subject = json.loads(subject_raw)
    execution = subject["execution"]
    assert live_command == [
        "/usr/bin/gh", "api", "--hostname", "github.com",
        readiness.SMOKE_RUN_API_ROUTE_TEMPLATE.format(
            repository=readiness.SMOKE_ATTESTATION_REPOSITORY,
            run_id=execution["workflow_run_id"],
            run_attempt=execution["workflow_run_attempt"],
        ),
        "--method", "GET",
        "-H", f"Accept: {readiness.SMOKE_GITHUB_API_ACCEPT}",
        "-H", f"X-GitHub-Api-Version: {readiness.SMOKE_GITHUB_API_VERSION}",
        "--jq", readiness.SMOKE_RUN_API_JSON_PROJECTION,
    ]


def test_paid_phase_attestation_gate_rejects_red_or_incomplete_exact_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, _public, _inventory, _public_raw, _inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "/usr/bin/gh")

    for status, conclusion in (("completed", "failure"), ("in_progress", "")):
        def fake_run(command, **kwargs):
            if command[1:] == ["--version"]:
                stdout = readiness.SMOKE_GH_VERSION_LINE.encode() + b"\n"
            elif command[1:3] == ["attestation", "verify"]:
                stdout = _mock_gh_verification_output(subject_raw, bundle_raw)
            else:
                stdout = _mock_live_run_attempt_output(
                    subject_raw, status=status, conclusion=conclusion
                )
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

        monkeypatch.setattr(readiness.subprocess, "run", fake_run)
        with pytest.raises(readiness.ReadinessError, match="completed successful"):
            readiness.verify_official_smoke_attestation_cryptographically()


def test_paid_phase_attestation_gate_rejects_live_attempt_api_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, _public, _inventory, _public_raw, _inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "/usr/bin/gh")

    def fake_run(command, **kwargs):
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=readiness.SMOKE_GH_VERSION_LINE.encode() + b"\n", stderr=b""
            )
        if command[1:3] == ["attestation", "verify"]:
            return subprocess.CompletedProcess(
                command, 0, stdout=_mock_gh_verification_output(subject_raw, bundle_raw), stderr=b""
            )
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"red run")

    monkeypatch.setattr(readiness.subprocess, "run", fake_run)
    with pytest.raises(readiness.ReadinessError, match="run-attempt verification failed"):
        readiness.verify_official_smoke_attestation_cryptographically()


def test_paid_phase_attestation_gate_rejects_success_exit_with_tampered_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _smoke, _public, _inventory, _public_raw, _inventory_raw, subject_raw, bundle_raw = (
        _official_smoke_pass_fixture(tmp_path, monkeypatch)
    )
    output = json.loads(_mock_gh_verification_output(subject_raw, bundle_raw))
    output[0]["verificationResult"]["signature"]["certificate"][
        "runInvocationURI"
    ] = "https://github.com/Scuttie/enterprise-shared-memory-poc/actions/runs/9/attempts/9"
    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(
        readiness.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                b"gh version 2.97.0 (2026-07-31)\n"
                if command[1:] == ["--version"] else _canonical(output)
            ),
            stderr=b"",
        ),
    )
    with pytest.raises(readiness.ReadinessError, match="runInvocationURI"):
        readiness.verify_official_smoke_attestation_cryptographically()


def test_freeze_allowlist_closes_all_trimem_execution_surfaces() -> None:
    frozen = set(freeze.frozen_paths(ROOT))
    assert "COMPANY_HANDOFF_MANIFEST.json" not in frozen
    assert "docs/STATUS.yaml" not in frozen
    discovered = {
        path.relative_to(ROOT).as_posix()
        for base, pattern in (
            (ROOT / "src/enterprise_memory/trimem", "*.py"),
            (ROOT / "scripts", "trimem_*.py"),
            (ROOT / "tests/unit", "test_trimem_*.py"),
        )
        for path in base.glob(pattern)
    }
    discovered.add("scripts/run_trimem_replay_e2e.py")
    discovered.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "configs/trimem_v1").rglob("*") if path.is_file()
    )
    discovered.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "migrations/versions").glob("*.py")
    )
    discovered.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "migrations/sql").glob("*_up.*")
    )
    assert discovered <= frozen
    assert {
        ".gitattributes", "alembic.ini", "DEPENDENCY_PROVENANCE.json", "requirements.lock",
        "src/enterprise_memory/service/app.py", "src/enterprise_memory/providers/openai_responses.py",
        "docs/TRIMEM_V1_SYSTEM.md", "tests/trimem/test_real_services_e2e.py",
        "src/enterprise_memory/providers/base.py",
        "src/enterprise_memory/providers/redaction.py",
        "src/enterprise_memory/indexing/canonical_loaders.py",
        "src/enterprise_memory/indexing/embeddings.py",
        "src/enterprise_memory/indexing/__init__.py",
        "src/enterprise_memory/indexing/drift.py",
        "src/enterprise_memory/indexing/reindex.py",
        "src/enterprise_memory/indexing/index_worker.py",
        "src/enterprise_memory/indexing/models.py",
        "src/enterprise_memory/indexing/projection.py",
        "src/enterprise_memory/indexing/qdrant_indexes.py",
        "src/enterprise_memory/indexing/validated_search.py",
        "src/enterprise_memory/persistence/tenant_context.py",
        "src/enterprise_memory/persistence/__init__.py",
        "src/enterprise_memory/persistence/postgres/__init__.py",
        "src/enterprise_memory/persistence/postgres/repos.py",
        "src/enterprise_memory/providers/__init__.py",
        "src/enterprise_memory/service/durable.py",
        "src/enterprise_memory/service/injection.py",
        "src/enterprise_memory/service/private_view.py",
        "src/enterprise_memory/service/__init__.py",
        "src/enterprise_memory/contracts/codec.py",
        "src/enterprise_memory/contracts/schema.py",
        "src/enterprise_memory/promotion/security_scan.py",
        "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_002.json",
        "artifacts/trimem_v1/development_tuning_exec/exec-002/protected-exec-gate-failure-receipt.json",
        "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_002_PROTECTED_GATE_FAILURE.md",
    } <= frozen
    assert not any(path.endswith("freeze.json") for path in frozen)
    referenced_blobs = set(freeze.referenced_blob_paths(ROOT))
    assert referenced_blobs
    assert referenced_blobs <= frozen
    assert all("/evidence/blobs/" in path for path in referenced_blobs)
    assert all((ROOT / path).is_file() for path in frozen)
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "artifacts/trimem_v1/**/evidence/blobs/** -text" in attributes


def test_frozen_noop_baseline_audit_proves_all_six_exact_base_trees() -> None:
    audit = _read(ROOT / "artifacts/trimem_v1/noop_baseline_six_commit_audit.json")
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    body = {key: value for key, value in audit.items() if key != "audit_sha256"}
    assert audit["status"] == "PASS"
    assert audit["noop_baseline"] == smoke_protocol.NOOP_BASELINE_LOCK
    assert audit["manifest_target_set_sha256"] == manifest["target_set_sha256"]
    assert audit["audit_sha256"] == hashlib.sha256(_canonical(body)).hexdigest()
    assert len(audit["rows"]) == 6
    assert {
        (row["repository"], row["instance_id"], row["base_commit"])
        for row in audit["rows"]
    } == {
        (row["repository"], row["instance_id"], row["base_commit"])
        for row in manifest["targets"]
        if row["probe"] == "GOLD"
    }
    for row in audit["rows"]:
        assert row["root_marker_absent_at_base"] is True
        assert row["patch_applies_cached"] is True
        assert row["isolated_temporary_index"] is True
        assert row["staged_marker_sha256"] == hashlib.sha256(
            smoke_protocol.NOOP_BASELINE_CONTENT
        ).hexdigest()
        assert row["changed_paths"] == [smoke_protocol.NOOP_BASELINE_PATH]
        assert row["forbidden_source_test_build_or_package_paths_touched"] == []
        assert re.fullmatch(r"[0-9a-f]{40}", row["base_tree"])


def test_freeze_contains_clean_import_execution_closure() -> None:
    script = r'''
import json
import pathlib
import sys
import enterprise_memory.trimem.production_runtime
import enterprise_memory.providers.openai_responses
import trimem_benchmark_run
import trimem_verify_ready
root = pathlib.Path.cwd().resolve()
paths = sorted({
    pathlib.Path(module.__file__).resolve().relative_to(root).as_posix()
    for name, module in sys.modules.items()
    if name.startswith("enterprise_memory")
    and getattr(module, "__file__", None)
    and root in pathlib.Path(module.__file__).resolve().parents
})
print(json.dumps(paths))
'''
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(ROOT / "src"), str(ROOT / "scripts"))
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    imported = set(json.loads(completed.stdout))
    assert imported
    assert imported <= set(freeze.frozen_paths(ROOT))
    assert "src/enterprise_memory/indexing/embeddings.py" in imported


def test_workflows_are_pinned_no_input_fail_closed_and_protect_raw_evidence() -> None:
    workflows = [
        ROOT / ".github/workflows/ci-trimem.yml",
        ROOT / ".github/workflows/ci-trimem-e2e.yml",
        ROOT / ".github/workflows/trimem-grader-smoke.yml",
        ROOT / ".github/workflows/trimem-benchmark.yml",
        ROOT / ".github/workflows/ci-trimem-harness-lock.yml",
        ROOT / ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ]
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        assert "continue-on-error" not in text
        assert "|| true" not in text
        assert ":latest" not in text
        assert "inputs:" not in text
        assert all(
            re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", match.group(1))
            for match in re.finditer(r"uses:\s*([^\s]+)", text)
        )
    static = workflows[0].read_text(encoding="utf-8")
    assert "tests/unit/test_trimem_*.py" in static
    assert "tests/trimem/e2e/test_full_replay.py" in static
    assert "terminal DEV gate-failure closure" in static
    assert '("benchmark-approval", consumed)' in static
    assert '"--require-git-tracked"' in static
    assert '"status": "FAIL_CLOSED"' in static
    assert "expected fail-closed report" in static
    assert "are final and consumed after a protected EXEC-gate failure" in static
    service = workflows[1].read_text(encoding="utf-8")
    assert "test_real_services_e2e.py" in service
    assert "python scripts/postgres_bootstrap.py" in service
    assert "TRIMEM_TEST_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in service
    assert "TRIMEM_TEST_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in service
    multi_swe_contract = workflows[5].read_text(encoding="utf-8")
    assert "pull_request:" in multi_swe_contract
    assert "workflow_dispatch:" not in multi_swe_contract
    assert "scripts/trimem_multi_swe_contract.py" in multi_swe_contract
    assert "tests/unit/test_trimem_multi_*.py" in multi_swe_contract
    assert "24f493f8a103e72312ded4f6b9c89f081d69cb09" in multi_swe_contract
    assert "environment:" not in multi_swe_contract
    assert "secrets." not in multi_swe_contract
    assert "trimem_grader_smoke.py" not in multi_swe_contract
    assert "github.event_name == 'push'" in multi_swe_contract
    assert "github.ref == 'refs/heads/codex/trimem-coder-v1'" in multi_swe_contract
    assert "github.run_attempt == 1" not in multi_swe_contract
    assert "github.event.head_commit.added" not in multi_swe_contract
    assert "contains(github.event" not in multi_swe_contract
    assert "scripts/trimem_multi_swe_probe_request.py" in multi_swe_contract
    assert '--event-path "$GITHUB_EVENT_PATH"' in multi_swe_contract
    assert "scripts/trimem_multi_swe_image_probe.py" in multi_swe_contract
    assert "always() && steps.image_probe.outcome != 'skipped'" in multi_swe_contract
    assert 'test "$IMAGE_PROBE_OUTCOME" = "success"' in multi_swe_contract
    assert "persist-credentials: false" in multi_swe_contract
    probe_gate = (ROOT / "scripts/trimem_multi_swe_probe_request.py").read_text(
        encoding="utf-8"
    )
    assert 'environment.get("GITHUB_RUN_ATTEMPT") == "1"' in probe_gate
    assert "artifacts/trimem_v1/probe_requests/" in probe_gate
    assert "MULTI_SWE_VUE_IMAGE_PROBE_REQUEST_001.json" in probe_gate
    smoke = workflows[2].read_text(encoding="utf-8")
    assert "workflow_dispatch:" in smoke and "pull_request:" not in smoke
    assert "push:" in smoke
    assert "      - codex/trimem-coder-v1" in smoke
    assert f"      - {readiness.GRADER_SMOKE_SENTINEL_PATH}" in smoke
    assert all(
        f"      - {path}" not in smoke for path, _ in readiness.HISTORICAL_SENTINELS
    )
    assert "group: trimem-v1-grader-smoke-exec-005" in smoke
    assert "cancel-in-progress: false" in smoke
    assert "branch-trigger-preflight:" in smoke
    assert "environment: trimem-grader-smoke-exec" in smoke
    assert "permissions:\n      attestations: write\n      contents: read\n      id-token: write" in smoke
    assert smoke.count(readiness.SMOKE_ATTESTATION_ACTION) == 1
    assert "create-storage-record: false" in smoke
    assert "push-to-registry: false" in smoke
    assert "subject-path: ${{ runner.temp }}/attestation-subject.json" in smoke
    assert "trimem_smoke_attestation.py" in smoke
    assert "trimem-grader-smoke-attestation-bundle.json" in smoke
    assert "name: trimem-grader-smoke-exec-005-public" in smoke
    assert "name: trimem-grader-smoke-exec-005-evidence-inventory" in smoke
    assert "name: trimem-grader-smoke-exec-005-restricted-encrypted" in smoke
    assert "name: trimem-grader-smoke-exec-005-attestation-bundle" in smoke
    assert "bounded-disk exact GOLD and NOOP_BASELINE pairs" in smoke
    assert "id: exec_gate" in smoke
    assert "id: run_smoke" in smoke
    assert "id: aggregate" in smoke
    assert "id: public_result" in smoke
    assert "id: workflow_image_cleanup" in smoke
    assert smoke.count(
        "--image-evidence-dir artifacts/trimem_v1/grader_smoke_exec/image-materialization"
    ) == 2
    assert "--cleanup-grader-smoke" in smoke
    assert ">(tee" not in smoke
    for stage in (
        "exec-gate",
        "run-smoke",
        "aggregate",
        "public-result",
        "image-cleanup",
        "authority-rollback",
    ):
        assert f"workflow-stages/{stage}/stdout.txt" in smoke
        assert f"workflow-stages/{stage}/stderr.txt" in smoke
    revoke_authority = smoke.index(
        "- name: Recover or revoke terminal authority after any campaign failure"
    )
    evidence_inventory = smoke.index("- name: Inventory every restricted evidence file")
    encrypt_evidence = smoke.index("- name: Encrypt complete restricted evidence")
    image_cleanup = smoke.index("- name: Remove only frozen smoke image references")
    failure_closure = smoke.index(
        "- name: Build namespaced exec-005 campaign failure closure"
    )
    attestation_subject = smoke.index(
        "- name: Build deterministic official smoke attestation subject"
    )
    upload_encrypted = smoke.index("- name: Upload encrypted restricted evidence")
    upload_failure_closure = smoke.index(
        "- name: Upload namespaced exec-005 failure closure"
    )
    cleanup_plaintext = smoke.index(
        "- name: Remove plaintext and temporary EXEC material before signing"
    )
    assert (
        image_cleanup
        < revoke_authority
        < evidence_inventory
        < failure_closure
        < encrypt_evidence
        < attestation_subject
        < upload_failure_closure
        < upload_encrypted
        < cleanup_plaintext
    )
    rollback_block = smoke[revoke_authority:evidence_inventory]
    assert "steps.exec_gate.outcome == 'success'" in rollback_block
    assert "steps.run_smoke.outcome != 'skipped'" in rollback_block
    assert "steps.run_smoke.outcome != 'success'" in rollback_block
    assert "steps.aggregate.outcome != 'success'" in rollback_block
    assert "steps.public_result.outcome != 'success'" in rollback_block
    assert "steps.workflow_image_cleanup.outcome != 'success'" in rollback_block
    assert "scripts/trimem_grader_smoke_authority.py" in rollback_block
    assert "--recover-interrupted" in rollback_block
    assert 'cause_stage="authority_finalization"' in rollback_block
    assert 'failure_taxonomy="infrastructure_failures"' in rollback_block
    assert "--cause-stage \"$cause_stage\"" in rollback_block
    assert "--failure-taxonomy \"$failure_taxonomy\"" in rollback_block
    assert "--reason-file \"$RUNNER_TEMP/trimem-authority-rollback-reason.txt\"" in rollback_block
    inventory_block = smoke[evidence_inventory:failure_closure]
    assert "steps.approval_materialization.outcome != 'skipped'" in inventory_block
    assert "campaign_authority_rollback" not in inventory_block
    closure_block = smoke[failure_closure:upload_failure_closure]
    assert "steps.evidence_inventory.outcome == 'success'" in closure_block
    assert "steps.campaign_authority_rollback.outcome == 'success'" in closure_block
    assert "steps.campaign_authority_rollback.outcome == 'skipped'" in closure_block
    assert "steps.exec_gate.outcome != 'success'" in closure_block
    for step_id in (
        "run_smoke",
        "aggregate",
        "public_result",
        "workflow_image_cleanup",
    ):
        assert f"steps.{step_id}.outcome != 'success'" in closure_block
    assert "scripts/trimem_grader_smoke_failure_closure.py" in closure_block
    assert "--workflow-conclusion \"${{ job.status }}\"" in closure_block
    failure_upload_block = smoke[upload_failure_closure:cleanup_plaintext]
    assert "steps.failure_closure.outcome == 'success'" in failure_upload_block
    encryption_block = smoke[encrypt_evidence:attestation_subject]
    assert "steps.approval_materialization.outcome != 'skipped'" in encryption_block
    assert "steps.evidence_inventory.outcome == 'success'" not in encryption_block
    assert "inventory_args=()" in encryption_block
    assert '"${inventory_args[@]}"' in encryption_block
    assert (
        "rm -f -- \"$RUNNER_TEMP/trimem-authority-rollback-reason.txt\""
        in smoke
    )
    upload_public = smoke.index("- name: Upload public smoke result")
    upload_inventory = smoke.index(
        "- name: Upload non-sensitive restricted evidence inventory"
    )
    upload_encrypted = smoke.index("- name: Upload encrypted restricted evidence")
    cleanup_before_signing = smoke.index(
        "- name: Remove plaintext and temporary EXEC material before signing"
    )
    attest = smoke.index("- name: Attest exact uploaded and cleaned official smoke subject")
    materialize_bundle = smoke.index("- name: Materialize fixed attestation bundle name")
    upload_bundle = smoke.index("- name: Upload official smoke attestation bundle")
    cleanup_staged = smoke.index("- name: Remove staged attestation material")
    assert (
        failure_closure
        < encrypt_evidence
        < attestation_subject
        < upload_inventory
        < upload_encrypted
        < cleanup_before_signing
        < attest
        < materialize_bundle
        < upload_public
        < upload_bundle
        < cleanup_staged
    )
    cleanup_block = smoke[cleanup_before_signing:attest]
    assert (
        "RESTRICTED_UPLOAD_OUTCOME: ${{ steps.restricted_upload.outcome }}"
        in cleanup_block
    )
    assert 'if [ "$RESTRICTED_UPLOAD_OUTCOME" != "success" ]; then' in cleanup_block
    assert "preserving plaintext and ciphertext" in cleanup_block
    for label in (
        "Remove only frozen smoke image references",
        "Recover or revoke terminal authority after any campaign failure",
        "Inventory every restricted evidence file",
        "Build namespaced exec-005 campaign failure closure",
        "Encrypt complete restricted evidence",
        "Build deterministic official smoke attestation subject",
        "Upload namespaced exec-005 failure closure",
        "Upload non-sensitive restricted evidence inventory",
        "Upload encrypted restricted evidence",
        "Remove plaintext and temporary EXEC material before signing",
        "Attest exact uploaded and cleaned official smoke subject",
        "Materialize fixed attestation bundle name",
        "Upload public smoke result",
        "Upload official smoke attestation bundle",
        "Remove staged attestation material",
    ):
        assert smoke.count(f"- name: {label}") == 1
    restricted_root = "artifacts/trimem_v1/grader_smoke_exec"
    immutable_phase = smoke[failure_closure:cleanup_before_signing]
    immutable_root_lines = [
        line.strip()
        for line in immutable_phase.splitlines()
        if restricted_root in line
    ]
    assert immutable_root_lines == [
        f"--restricted-root {restricted_root} \\",
        f"-C {restricted_root} . \\",
        f"--public-result {restricted_root}/public-results.json \\",
        (
            'python -c "import os,pathlib,shutil; '
            f"source=pathlib.Path('{restricted_root}/public-results.json'); "
            "target=pathlib.Path(os.environ['RUNNER_TEMP'],"
            "'trimem-grader-smoke-public-results.json'); "
            "assert source.is_file() and not target.exists(); "
            "shutil.copyfile(source,target); "
            'assert source.read_bytes() == target.read_bytes()"'
        ),
    ]
    assert smoke.count("python scripts/trimem_evidence_inventory.py") == 1
    assert smoke.count("openssl enc -aes-256-cbc") == 1
    assert smoke.count("python scripts/trimem_grader_smoke_authority.py") == 1
    assert smoke.count("python scripts/trimem_grader_smoke_failure_closure.py") == 1
    assert smoke.count("python scripts/trimem_cleanup_exec.py --phase grader-smoke") == 1
    assert smoke.count("id: evidence_inventory") == 1
    assert smoke.count("id: failure_closure") == 1
    assert smoke.count("id: encrypt_evidence") == 1
    assert smoke.count("id: smoke-attestation") == 1
    assert "delivery_authority_rollback" not in smoke
    assert "--pre-cell-failure-output artifacts/trimem_v1/grader_smoke_exec/results" in smoke
    attest_block = smoke[attest:upload_bundle]
    assert "if: always()" not in attest_block
    benchmark = workflows[3].read_text(encoding="utf-8")
    assert "workflow_dispatch:" in benchmark
    assert "pull_request:" not in benchmark
    assert "schedule:" not in benchmark
    assert "push:" in benchmark
    assert "      - codex/trimem-coder-v1" in benchmark
    assert (
        "      - artifacts/trimem_v1/exec_requests/"
        "DEVELOPMENT_TUNING_EXEC_REQUEST_002.json"
    ) in benchmark
    assert "branch-trigger-preflight:" in benchmark
    assert "needs: branch-trigger-preflight" in benchmark
    assert "group: trimem-v1-development-tuning-exec-002" in benchmark
    assert "group: trimem-v1-development-tuning-exec-001" not in benchmark
    assert "cancel-in-progress: false" in benchmark
    preflight = benchmark.split("  branch-trigger-preflight:", 1)[1].split(
        "  frozen-serial-phase:", 1
    )[0]
    assert "runs-on: ubuntu-24.04" in preflight
    assert "fetch-depth: 0" in preflight
    assert "persist-credentials: false" in preflight
    assert (
        "python -I -S scripts/trimem_freeze.py --check --require-git-tracked"
        in preflight
    )
    assert "python -I -S scripts/trimem_development_trigger_preflight.py" in preflight
    assert "secrets." not in preflight
    assert "environment:" not in preflight
    for path in workflows[2:4]:
        text = path.read_text(encoding="utf-8")
        assert "openssl enc -aes-256-cbc" in text
        assert "restricted-encrypted" in text
    assert "runs-on: [self-hosted, linux, x64, ubuntu-24.04, trimem-benchmark]" in benchmark
    assert "timeout-minutes: 7200" in benchmark
    assert "matrix:" not in benchmark
    assert "permissions:\n  actions: read\n  contents: read" in benchmark
    assert benchmark.count("GH_TOKEN: ${{ github.token }}") == 1
    gate_start = benchmark.index("- name: Verify exact phase EXEC gate")
    secret_gate = benchmark.index(
        "- name: Verify required protected runtime secrets before paid work"
    )
    gate_end = benchmark.index("- name: Apply exact migration head")
    image_pull = benchmark.index(
        "- name: Pull committed images by digest and verify local observations"
    )
    assert gate_start < secret_gate < gate_end < image_pull
    assert "GH_TOKEN: ${{ github.token }}" in benchmark[gate_start:gate_end]
    assert "trimem_run_with_resume.py" in benchmark
    assert 'test -n "$OPENAI_API_KEY"' in benchmark
    assert 'test -n "$TRIMEM_EVIDENCE_PASSPHRASE"' in benchmark
    assert "umask 077" in benchmark
    assert "trap cleanup_partial_approval EXIT" in benchmark
    assert 'rm -f -- "$approval_tmp" "$restricted_approval"' in benchmark
    assert "trap - EXIT" in benchmark
    assert "trimem_cleanup_exec.py --phase benchmark" in benchmark
    assert "python scripts/postgres_bootstrap.py" in benchmark
    assert "TRIMEM_DATABASE_URL: postgresql+asyncpg://api_service:api_pw@" in benchmark
    assert "TRIMEM_ADMIN_DATABASE_URL: postgresql+asyncpg://postgres:postgres@" in benchmark
    assert "trimem_cleanup_exec.py --phase grader-smoke" in workflows[2].read_text(encoding="utf-8")


def _patch_smoke_workflow_text(
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    smoke_path = (ROOT / ".github/workflows/trimem-grader-smoke.yml").resolve()
    original_read_text = Path.read_text

    def patched_read_text(path: Path, *args, **kwargs) -> str:
        if path.resolve() == smoke_path:
            return replacement
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", patched_read_text)


def test_workflow_validator_rejects_cleanup_after_authority_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_path = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    smoke = smoke_path.read_text(encoding="utf-8")
    image_cleanup = "- name: Remove only frozen smoke image references"
    rollback = "- name: Recover or revoke terminal authority after any campaign failure"
    placeholder = "- name: TEMPORARY ORDER PLACEHOLDER"
    tampered = smoke.replace(image_cleanup, placeholder, 1)
    tampered = tampered.replace(rollback, image_cleanup, 1)
    tampered = tampered.replace(placeholder, rollback, 1)
    _patch_smoke_workflow_text(monkeypatch, tampered)

    with pytest.raises(
        readiness.ReadinessError,
        match="cleanup/rollback/inventory/encryption/upload/signing order differs",
    ):
        readiness.validate_workflows()


def test_workflow_validator_rejects_incomplete_authority_recovery_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_path = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    smoke = smoke_path.read_text(encoding="utf-8")
    tampered = smoke.replace(
        "          steps.exec_gate.outcome == 'success' &&\n"
        "          steps.run_smoke.outcome != 'skipped' &&\n"
        "          (steps.run_smoke.outcome != 'success' ||\n",
        "          steps.exec_gate.outcome == 'success' &&\n"
        "          steps.run_smoke.outcome == 'success' &&\n"
        "          (steps.run_smoke.outcome != 'success' ||\n",
        1,
    )
    _patch_smoke_workflow_text(monkeypatch, tampered)

    with pytest.raises(
        readiness.ReadinessError,
        match="authority recovery is not total",
    ):
        readiness.validate_workflows()


def test_workflow_validator_rejects_inventory_gated_on_authority_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_path = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    smoke = smoke_path.read_text(encoding="utf-8")
    tampered = smoke.replace(
        "          steps.approval_materialization.outcome != 'skipped'\n",
        "          (steps.campaign_authority_rollback.outcome == 'success' ||\n"
        "           steps.campaign_authority_rollback.outcome == 'skipped')\n",
        1,
    )
    _patch_smoke_workflow_text(monkeypatch, tampered)

    with pytest.raises(
        readiness.ReadinessError,
        match="inventory is not independent of authority recovery",
    ):
        readiness.validate_workflows()


def test_workflow_validator_rejects_encryption_gated_on_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_path = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    smoke = smoke_path.read_text(encoding="utf-8")
    encrypt_marker = "      - name: Encrypt complete restricted evidence"
    encrypt_at = smoke.index(encrypt_marker)
    before, block = smoke[:encrypt_at], smoke[encrypt_at:]
    block = block.replace(
        "          steps.approval_materialization.outcome != 'skipped'\n",
        "          steps.evidence_inventory.outcome == 'success'\n",
        1,
    )
    _patch_smoke_workflow_text(monkeypatch, before + block)

    with pytest.raises(
        readiness.ReadinessError,
        match="encryption is not independent of optional inventory evidence",
    ):
        readiness.validate_workflows()


def test_workflow_validator_rejects_cleanup_without_uploaded_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_path = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    smoke = smoke_path.read_text(encoding="utf-8")
    tampered = smoke.replace(
        '          if [ "$RESTRICTED_UPLOAD_OUTCOME" != "success" ]; then\n',
        '          if [ "$RESTRICTED_UPLOAD_OUTCOME" = "success" ]; then\n',
        1,
    )
    _patch_smoke_workflow_text(monkeypatch, tampered)

    with pytest.raises(
        readiness.ReadinessError,
        match="uploads/signing are not outcome-gated after evidence preservation",
    ):
        readiness.validate_workflows()


def test_workflow_validator_rejects_restricted_root_mutation_after_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke_path = ROOT / ".github/workflows/trimem-grader-smoke.yml"
    smoke = smoke_path.read_text(encoding="utf-8")
    encryption = "      - name: Encrypt complete restricted evidence"
    late_mutation = (
        "      - name: Synthetic forbidden post-inventory write\n"
        "        run: mkdir -p artifacts/trimem_v1/grader_smoke_exec/late-write\n"
    )
    tampered = smoke.replace(encryption, late_mutation + encryption, 1)
    _patch_smoke_workflow_text(monkeypatch, tampered)

    with pytest.raises(
        readiness.ReadinessError,
        match="restricted evidence root is not immutable between inventory and deletion",
    ):
        readiness.validate_workflows()


def test_same_attempt_driver_retries_exactly_once_and_propagates_final_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary
) -> None:
    monkeypatch.setattr(resume_runner, "ROOT", tmp_path)
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        code = 23 if len(calls) == 1 else 29
        return type("Completed", (), {
            "returncode": code,
            "stdout": f"stdout-{len(calls)}".encode(),
            "stderr": f"stderr-{len(calls)}".encode(),
        })()

    monkeypatch.setattr(resume_runner.subprocess, "run", fake_run)
    assert resume_runner.run_with_one_resume("development", tmp_path.parent / "approval.json") == 29
    assert len(calls) == 2
    assert "--resume" not in calls[0] and calls[1][-1] == "--resume"
    evidence = _read(tmp_path / "artifacts/trimem_v1/benchmark_exec/development/driver-evidence/attempts.json")
    assert [row["exit_code"] for row in evidence["attempts"]] == [23, 29]
    assert evidence["maximum_resume_attempts"] == 1 and evidence["status"] == "FAIL"
    captured = capsysbinary.readouterr()
    assert b"stdout-1" in captured.out and b"stdout-2" in captured.out
    assert b"stderr-1" in captured.err and b"stderr-2" in captured.err


def test_exec_cleanup_removes_only_fixed_scoped_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    runner_temp = tmp_path / "runner-temp"
    (repository / ".trimem-exec/datasets").mkdir(parents=True)
    (repository / "artifacts/trimem_v1/benchmark_exec/development").mkdir(parents=True)
    (repository / "artifacts/trimem_v1/development_selection").mkdir(parents=True)
    runner_temp.mkdir()
    (runner_temp / "trimem-exec-approval.json").write_text("secret", encoding="utf-8")
    (runner_temp / "trimem-benchmark-restricted.tar.enc").write_bytes(b"encrypted")
    keep = repository / "configs/keep.txt"
    keep.parent.mkdir()
    keep.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(cleanup_exec, "ROOT", repository)
    cleanup_exec.cleanup("benchmark", runner_temp)
    assert not (repository / ".trimem-exec").exists()
    assert not (repository / "artifacts/trimem_v1/benchmark_exec").exists()
    assert not (repository / "artifacts/trimem_v1/development_selection").exists()
    assert not (runner_temp / "trimem-exec-approval.json").exists()
    assert keep.read_text(encoding="utf-8") == "keep"


def test_image_pull_timeout_preserves_partial_stdout_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def timeout(*args, **kwargs):
        raise image_pull.subprocess.TimeoutExpired(
            cmd=args[0], timeout=3600, output=b"partial-out", stderr=b"partial-err"
        )

    monkeypatch.setattr(image_pull.subprocess, "run", timeout)
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="timed out"):
        image_pull._run(["docker", "pull", "repo@sha256:" + "a" * 64], tmp_path, 0, "pull")
    stage = _read(tmp_path / "000-pull/stage.json")
    assert stage["status"] == "TIMEOUT" and stage["returncode"] is None
    assert (tmp_path / "000-pull/stdout.txt").read_text(encoding="utf-8") == "partial-out"
    assert (tmp_path / "000-pull/stderr.txt").read_text(encoding="utf-8") == "partial-err"


def test_image_pull_preserves_non_utf8_process_streams_byte_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_kwargs: dict = {}

    def completed(argv, **kwargs):
        observed_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=b"raw-out-\xff\r\n",
            stderr=b"raw-err-\xfe\r\n",
        )

    monkeypatch.setattr(image_pull.subprocess, "run", completed)
    result, refs = image_pull._run(
        ["docker", "pull", "repo@sha256:" + "a" * 64],
        tmp_path,
        0,
        "pull",
    )

    assert observed_kwargs["text"] is False
    assert result.returncode == 0
    assert (tmp_path / refs["stdout"]["path"]).read_bytes() == b"raw-out-\xff\r\n"
    assert (tmp_path / refs["stderr"]["path"]).read_bytes() == b"raw-err-\xfe\r\n"


def test_bounded_disk_image_helpers_pull_inspect_and_remove_only_exact_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image = "example/image@sha256:" + "a" * 64
    tag = "example/image:frozen-harness-tag"
    calls: list[list[str]] = []

    def fake_run(argv, root, index, stage):
        calls.append(list(argv))
        stdout = json.dumps([image]) if stage == "inspect" else ""
        return (
            type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})(),
            {
                "stdout": {"path": f"{index:03d}-{stage}/stdout.txt", "bytes": len(stdout), "sha256": "b" * 64},
                "stderr": {"path": f"{index:03d}-{stage}/stderr.txt", "bytes": 0, "sha256": "c" * 64},
            },
        )

    monkeypatch.setattr(image_pull, "_run", fake_run)
    observed = image_pull.pull_and_observe_image(image, tmp_path, 4)
    removed = image_pull.remove_materialized_image(image, [tag], tmp_path, 5)
    assert observed["expected_digest"] == "sha256:" + "a" * 64
    assert removed["references"] == [tag, image]
    assert calls == [
        ["docker", "pull", image],
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image],
        ["docker", "image", "rm", "--force", tag, image],
    ]
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="not exact"):
        image_pull.remove_materialized_image(image, ["bad tag"], tmp_path, 6)


def test_workflow_fallback_cleanup_touches_only_fourteen_frozen_refs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv, root, index, stage):
        calls.append(list(argv))
        completed = type(
            "Completed", (), {"returncode": 0, "stdout": "[]", "stderr": ""}
        )()
        refs = {
            stream: {
                "path": f"{index:03d}-{stage}/{stream}.txt",
                "bytes": 0,
                "sha256": "a" * 64,
            }
            for stream in ("stdout", "stderr")
        }
        return completed, refs

    monkeypatch.setattr(image_pull, "_run", fake_run)
    report = image_pull.cleanup_grader_smoke_images(tmp_path)
    inspected = [call[-1] for call in calls if call[:3] == ["docker", "image", "inspect"]]
    removed = [call[-1] for call in calls if call[:4] == ["docker", "image", "rm", "--force"]]
    assert len(inspected) == len(set(inspected)) == 14
    assert removed == inspected
    assert report["exact_reference_count"] == 14
    assert report["removed_reference_count"] == 14
    assert report["already_absent_reference_count"] == 0


def test_smoke_image_lifecycle_pulls_each_identity_once_and_removes_exact_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    calls: list[tuple[str, str, tuple[str, ...]]] = []

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        calls.append(("PULL", image, ()))
        return {
            "image": image,
            "expected_digest": image.rsplit("@", 1)[1],
            "observed_digests": [image.rsplit("@", 1)[1]],
            "pull": {"stdout": {}, "stderr": {}},
            "inspect": {"stdout": {}, "stderr": {}},
        }

    def fake_remove(
        image: str, tags: list[str], evidence_root: Path, index: int
    ) -> dict:
        calls.append(("REMOVE", image, tuple(tags)))
        return {
            "image": image,
            "references": [*tags, image],
            "remove": {"stdout": {}, "stderr": {}},
            "status": "PASS",
        }

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fake_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={
            "phase": "GRADER_SMOKE",
            "approval_artifact_sha256": "a" * 64,
            "git_head": "b" * 40,
        },
        evidence_root=tmp_path,
        targets=manifest["targets"],
        images=images,
        support=support,
    )
    for index, target in enumerate(manifest["targets"]):
        lifecycle.before_target(index, target)
        lifecycle.after_target(index, target)
    lifecycle.finish()

    target_rows = manifest["targets"][0::2]
    target_images = [images[row["instance_id"]]["image"] for row in target_rows]
    support_image, support_tag = support[0]
    assert [image for action, image, _ in calls if action == "PULL"] == [
        *target_images[:2], support_image, *target_images[2:]
    ]
    assert [image for action, image, _ in calls if action == "REMOVE"] == [
        *target_images, support_image
    ]
    assert calls[-1] == ("REMOVE", support_image, (support_tag,))
    report = _read(tmp_path / "image-lifecycle-report.json")
    assert report["status"] == "PASS"
    assert report["actual"] == {
        "exact_image_removals": 7,
        "max_resident_support_images": 1,
        "max_resident_target_images": 1,
        "resident_support_images": 0,
        "resident_target_images": 0,
        "support_image_pulls": 1,
        "target_image_pulls": 6,
    }


def test_smoke_image_lifecycle_cleans_pull_success_inspect_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    stages: list[str] = []

    def fake_run(argv, root, index, stage):
        stages.append(stage)
        stdout = (
            json.dumps(["example.invalid/image@sha256:" + "e" * 64])
            if stage == "inspect"
            else ""
        )
        completed = type(
            "Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""}
        )()
        refs = {
            stream: {
                "path": f"{index:03d}-{stage}/{stream}.txt",
                "bytes": len(stdout) if stream == "stdout" else 0,
                "sha256": "a" * 64,
            }
            for stream in ("stdout", "stderr")
        }
        return completed, refs

    monkeypatch.setattr(image_pull, "_run", fake_run)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": "a" * 64, "git_head": "b" * 40},
        evidence_root=tmp_path,
        targets=manifest["targets"], images=images, support=support,
    )
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="digest mismatch") as captured:
        lifecycle.before_target(0, manifest["targets"][0])
    lifecycle.abort(captured.value)
    report = _read(tmp_path / "image-lifecycle-report.json")
    assert stages == ["pull", "inspect", "remove"]
    assert report["status"] == "FAILED"
    assert report["actual"]["resident_target_images"] == 0
    assert report["events"][0]["action"] == "PULL_TARGET_FAILED"
    assert report["events"][1]["action"] == "REMOVE_TARGET"


def test_smoke_image_lifecycle_abort_removes_target_and_multi_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    calls: list[tuple[str, str]] = []

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        calls.append(("PULL", image))
        digest = image.rsplit("@", 1)[1]
        return {"image": image, "expected_digest": digest, "observed_digests": [digest], "pull": {}, "inspect": {}}

    def fake_remove(image: str, tags: list[str], evidence_root: Path, index: int) -> dict:
        calls.append(("REMOVE", image))
        return {"image": image, "references": [*tags, image], "remove": {}, "status": "PASS"}

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fake_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": "a" * 64, "git_head": "b" * 40},
        evidence_root=tmp_path,
        targets=manifest["targets"], images=images, support=support,
    )
    for index, target in enumerate(manifest["targets"][:4]):
        lifecycle.before_target(index, target)
        lifecycle.after_target(index, target)
    lifecycle.before_target(4, manifest["targets"][4])
    lifecycle.abort(RuntimeError("synthetic post-pull failure"))
    report = _read(tmp_path / "image-lifecycle-report.json")
    support_image = support[0][0]
    multi_image = images[manifest["targets"][4]["instance_id"]]["image"]
    assert calls[-2:] == [("REMOVE", multi_image), ("REMOVE", support_image)]
    assert report["status"] == "FAILED"
    assert report["actual"]["resident_target_images"] == 0
    assert report["actual"]["resident_support_images"] == 0


def test_smoke_image_lifecycle_cleanup_failure_is_truthful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        digest = image.rsplit("@", 1)[1]
        return {"image": image, "expected_digest": digest, "observed_digests": [digest], "pull": {}, "inspect": {}}

    def fail_remove(*args, **kwargs):
        raise benchmark_run.BenchmarkExecutionError("synthetic removal failure")

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fail_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": "a" * 64, "git_head": "b" * 40},
        evidence_root=tmp_path,
        targets=manifest["targets"], images=images, support=support,
    )
    lifecycle.before_target(0, manifest["targets"][0])
    with pytest.raises(benchmark_run.BenchmarkExecutionError) as captured:
        lifecycle.after_target(1, manifest["targets"][1])
    lifecycle.abort(captured.value)
    report = _read(tmp_path / "image-lifecycle-report.json")
    assert report["status"] == "CLEANUP_FAILED"
    assert report["actual"]["resident_target_images"] == 1
    assert report["actual"]["exact_image_removals"] == 0
    assert report["failure"]["cleanup_failures"]


def test_smoke_aggregate_seals_exact_image_lifecycle_and_raw_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    image_root = tmp_path / "image-materialization"
    results = tmp_path / "results"
    results.mkdir()
    approval_hash, head = "a" * 64, "b" * 40
    (results / "external-approval-evidence.json").write_text(
        json.dumps({
            "approval_artifact_sha256": approval_hash,
            "git_head": head,
            "phase": "GRADER_SMOKE",
        }),
        encoding="utf-8",
    )

    def streams(
        index: int, stage: str, argv: list[str], stdout_raw: bytes
    ) -> dict:
        value = {}
        for stream, raw in (("stdout", stdout_raw), ("stderr", b"")):
            path = image_root / f"{index:03d}-{stage}/{stream}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            value[stream] = {
                "path": path.relative_to(image_root).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        stage_path = image_root / f"{index:03d}-{stage}/stage.json"
        stage_path.write_bytes(_canonical({
            "argv": argv,
            "returncode": 0,
            "stage": stage,
            "status": "PASS",
            "stdout": value["stdout"],
            "stderr": value["stderr"],
        }))
        return value

    def fake_pull(image: str, evidence_root: Path, index: int) -> dict:
        digest = image.rsplit("@", 1)[1]
        return {
            "image": image,
            "expected_digest": digest,
            "observed_digests": [digest],
            "pull": streams(
                index, "pull", ["docker", "pull", image], b"pull\n"
            ),
            "inspect": streams(
                index,
                "inspect",
                [
                    "docker", "image", "inspect", "--format",
                    "{{json .RepoDigests}}", image,
                ],
                _canonical([image]),
            ),
        }

    def fake_remove(image: str, tags: list[str], evidence_root: Path, index: int) -> dict:
        return {
            "image": image,
            "references": [*tags, image],
            "remove": streams(
                index,
                "remove",
                ["docker", "image", "rm", "--force", *tags, image],
                b"remove\n",
            ),
            "status": "PASS",
        }

    monkeypatch.setattr(grader_smoke, "pull_and_observe_image", fake_pull)
    monkeypatch.setattr(grader_smoke, "remove_materialized_image", fake_remove)
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval={"phase": "GRADER_SMOKE", "approval_artifact_sha256": approval_hash, "git_head": head},
        evidence_root=image_root,
        targets=manifest["targets"], images=images, support=support,
    )
    for index, target in enumerate(manifest["targets"]):
        lifecycle.before_target(index, target)
        lifecycle.after_target(index, target)
    lifecycle.finish()
    sealed = benchmark_matrix._validate_smoke_image_lifecycle(results, image_root)
    assert sealed["status"] == "PASS" and sealed["event_count"] == 14

    report_path = image_root / "image-lifecycle-report.json"
    report = _read(report_path)
    report["events"].pop()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(benchmark_matrix.MatrixError, match="event count"):
        benchmark_matrix._validate_smoke_image_lifecycle(results, image_root)


def test_external_approval_is_bound_to_single_workflow_dispatch_and_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repository"
    config = repository / "configs/trimem_v1"
    artifact = repository / "artifacts/trimem_v1"
    config.mkdir(parents=True)
    artifact.mkdir(parents=True)
    (config / "grader_smoke_manifest.json").write_text("{}", encoding="utf-8")
    request = _read(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    hard = _read(ROOT / "configs/trimem_v1/cost_plan.json")["phase_hard_caps"]["GRADER_SMOKE"]
    request_path = config / "benchmark_exec_request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    sentinel_path = repository / readiness.GRADER_SMOKE_SENTINEL_PATH
    sentinel_path.parent.mkdir(parents=True)
    sentinel = {
        "schema": readiness.GRADER_SMOKE_REQUEST_SCHEMA,
        "request_id": readiness.GRADER_SMOKE_REQUEST_ID,
        "phase": "GRADER_SMOKE",
        "frozen_request_sha256": "sha256:"
        + hashlib.sha256(request_path.read_bytes()).hexdigest(),
    }
    sentinel_path.write_text(json.dumps(sentinel), encoding="utf-8")
    (config / "cost_plan.json").write_text(json.dumps({"phase_hard_caps": {"GRADER_SMOKE": hard}}), encoding="utf-8")
    freeze_path = artifact / "freeze.json"
    freeze_path.write_text('{"synthetic":"freeze"}', encoding="utf-8")
    approval = {
        "approved_git_commit": "c" * 40,
        "approved_freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        "approved_phase": "GRADER_SMOKE",
        "approved_task_arm_runs": hard["task_arm_runs"],
        "approved_paid_model_call_cap": hard["paid_model_calls"],
        "approved_input_token_cap": hard["input_tokens"],
        "approved_output_token_cap": hard["output_tokens"],
        "approved_currency_hard_cap": hard["total_usd"],
        "approved_grader_containers": hard["benchmark_grader_containers"],
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "1",
        "approved_legal_terms_acceptance": True,
        "approval_actor": "benchmark-owner",
        "approval_timestamp": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
    }
    document = {
        "schema": "trimem/external-exec-approval/1.0",
        "request_id": sentinel["request_id"],
        "approved_request_sha256": hashlib.sha256(sentinel_path.read_bytes()).hexdigest(),
        "approval": approval,
    }
    path = tmp_path / "approval.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(benchmark_run, "ROOT", repository)
    monkeypatch.setattr(benchmark_run, "git_tracked", lambda _path: None)
    monkeypatch.setattr(benchmark_run, "git_head", lambda: "c" * 40)
    monkeypatch.setattr(
        benchmark_run,
        "validate_grader_smoke_sentinel",
        lambda path: sentinel if path == sentinel_path else pytest.fail("wrong sentinel"),
    )
    monkeypatch.setenv("GITHUB_RUN_ID", "8123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    assert benchmark_run.validate_exec_approval("grader-smoke", path)["approved_workflow_run_id"] == "8123456789"

    attempt_two_document = deepcopy(document)
    attempt_two_document["approval"]["approved_workflow_run_attempt"] = "2"
    path.write_text(json.dumps(attempt_two_document), encoding="utf-8")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="one-time phase execution requires workflow run attempt 1",
    ):
        benchmark_run.validate_exec_approval("grader-smoke", path)

    validation_args = {
        "request": sentinel,
        "policy_request": request,
        "hard_cap": hard,
        "request_sha256": hashlib.sha256(sentinel_path.read_bytes()).hexdigest(),
        "freeze_sha256": hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
        "git_head": "c" * 40,
        "workflow_run_id": "8123456789",
        "workflow_run_attempt": "2",
        "now": datetime.now(timezone.utc),
    }
    with pytest.raises(
        exec_approval.ApprovalValidationError,
        match="one-time phase execution requires workflow run attempt 1",
    ):
        exec_approval.validate_external_approval_document(
            attempt_two_document,
            phase="GRADER_SMOKE",
            **validation_args,
        )

    other_phase_document = deepcopy(attempt_two_document)
    other_phase_document["approval"]["approved_phase"] = "DEVELOPMENT_TUNING"
    with pytest.raises(
        exec_approval.ApprovalValidationError,
        match="cannot authorize a different phase",
    ):
        exec_approval.validate_external_approval_document(
            other_phase_document,
            phase="DEVELOPMENT_TUNING",
            **validation_args,
        )

    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    path.write_text(json.dumps(attempt_two_document), encoding="utf-8")
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="differs from this attempt"):
        benchmark_run.validate_exec_approval("grader-smoke", path)
    document["approval"]["approved_workflow_run_attempt"] = "1"
    document["approval"]["approved_task_arm_runs"] = False
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="approved_task_arm_runs"):
        benchmark_run.validate_exec_approval("grader-smoke", path)


def test_cached_and_uncached_input_cost_is_exact_per_task() -> None:
    accounting = {
        "input_tokens": 1_000_000,
        "cached_input_tokens": 250_000,
        "output_tokens": 100_000,
    }
    pricing = {
        "input_per_million_tokens_usd": 0.75,
        "cached_input_per_million_tokens_usd": 0.075,
        "output_per_million_tokens_usd": 4.5,
    }
    assert benchmark_run.actual_usd_for_accounting(accounting, pricing) == "1.031250000000"


def _stream_total_fixture() -> tuple[list[dict], dict, dict]:
    pricing = {
        "input_per_million_tokens_usd": 0.75,
        "cached_input_per_million_tokens_usd": 0.075,
        "output_per_million_tokens_usd": 4.5,
    }
    first_accounting = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
    first_accounting.update({
        "solve_calls": 2,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "input_tokens": 1_000,
        "cached_input_tokens": 200,
        "output_tokens": 100,
        "model_gateway_calls": 4,
        "paid_model_calls": 4,
        "grader_calls": 1,
        "grader_containers": 1,
        "official_grader_runs": 1,
    })
    second_accounting = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
    second_accounting.update({
        "solve_calls": 3,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "input_tokens": 2_000,
        "output_tokens": 200,
        "model_gateway_calls": 5,
        "paid_model_calls": 5,
        "grader_calls": 1,
        "grader_containers": 1,
        "official_grader_runs": 1,
    })
    first_memory = {field: 0 for field in benchmark_matrix.MEMORY_FIELDS}
    first_memory.update({
        "recall_attempts": 2,
        "injected_records": 1,
        "episodic_injections": 1,
        "retained_records": 2,
        "archived_records": 1,
        "net_memory_growth": 1,
    })
    second_memory = {field: 0 for field in benchmark_matrix.MEMORY_FIELDS}
    second_memory.update({
        "recall_attempts": 3,
        "injected_records": 1,
        "user_semantic_injections": 1,
        "retained_records": 1,
        "net_memory_growth": 1,
    })
    records = [
        {
            "actual_accounting": first_accounting,
            "actual_memory_metrics": first_memory,
            "actual_usd": "0.001065000000",
            "resolved": True,
        },
        {
            "actual_accounting": second_accounting,
            "actual_memory_metrics": second_memory,
            "actual_usd": "0.002400000000",
            "resolved": False,
        },
    ]
    summary = {
        "actual_accounting": {
            field: first_accounting[field] + second_accounting[field]
            for field in benchmark_matrix.ACCOUNTING_FIELDS
        },
        "actual_memory_metrics": {
            field: first_memory[field] + second_memory[field]
            for field in benchmark_matrix.MEMORY_FIELDS
        },
        "actual_total_tokens": 3_300,
        "actual_usd": "0.003465000000",
        "resolved_count": 1,
    }
    return records, summary, pricing


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("actual_accounting", "input_tokens"),
        ("actual_memory_metrics", "recall_attempts"),
        (None, "resolved_count"),
        (None, "actual_total_tokens"),
        (None, "actual_usd"),
    ],
)
def test_stream_summary_tampering_is_rejected(
    tmp_path: Path, section: str | None, field: str
) -> None:
    records, summary, pricing = _stream_total_fixture()
    benchmark_matrix._validate_stream_summary_totals(
        tmp_path / "M1.arm-summary.json", summary, records, pricing
    )
    tampered = deepcopy(summary)
    if section is None:
        tampered[field] = (
            "0.003465000001" if field == "actual_usd" else int(tampered[field]) + 1
        )
    else:
        tampered[section][field] += 1
    with pytest.raises(benchmark_matrix.MatrixError, match="task/stream"):
        benchmark_matrix._validate_stream_summary_totals(
            tmp_path / "M1.arm-summary.json", tampered, records, pricing
        )


@pytest.mark.parametrize("section", ["actual_accounting", "actual_memory_metrics"])
def test_stream_summary_rejects_unknown_raw_metric_fields(
    tmp_path: Path, section: str
) -> None:
    records, summary, pricing = _stream_total_fixture()
    records[0][section]["unfrozen_extra_metric"] = 1
    with pytest.raises(benchmark_matrix.MatrixError, match="shape differs"):
        benchmark_matrix._validate_stream_summary_totals(
            tmp_path / "M1.arm-summary.json", summary, records, pricing
        )


def test_task_actual_usd_is_recomputed_from_frozen_pricing() -> None:
    records, _summary, pricing = _stream_total_fixture()
    assert benchmark_matrix._actual_usd_from_accounting(
        records[0]["actual_accounting"], pricing
    ) == records[0]["actual_usd"]


def test_aggregate_revalidates_exact_workflow_approval_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "8123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    head = "b" * 40
    repository = tmp_path / "repository"
    sentinel = repository / readiness.GRADER_SMOKE_SENTINEL_PATH
    frozen = repository / "artifacts/trimem_v1/freeze.json"
    config = repository / "configs/trimem_v1"
    sentinel.parent.mkdir(parents=True)
    frozen.parent.mkdir(parents=True, exist_ok=True)
    config.mkdir(parents=True)
    request_id = readiness.GRADER_SMOKE_REQUEST_ID
    sentinel.write_text(
        json.dumps({"request_id": request_id, "request": "exact-sentinel"}) + "\n",
        encoding="utf-8",
    )
    frozen.write_text('{"freeze":"exact"}\n', encoding="utf-8")
    policy = _read(ROOT / "configs/trimem_v1/benchmark_exec_request.json")
    hard = _read(ROOT / "configs/trimem_v1/cost_plan.json")["phase_hard_caps"]["GRADER_SMOKE"]
    (config / "benchmark_exec_request.json").write_text(
        json.dumps(policy), encoding="utf-8"
    )
    (config / "cost_plan.json").write_text(
        json.dumps({"phase_hard_caps": {"GRADER_SMOKE": hard}}), encoding="utf-8"
    )
    monkeypatch.setattr(benchmark_matrix, "ROOT", repository)
    monkeypatch.setattr(
        benchmark_matrix.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, head + "\n", ""),
    )
    request_digest = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    freeze_digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
    approval_raw = _canonical({
        "schema": "trimem/external-exec-approval/1.0",
        "request_id": request_id,
        "approved_request_sha256": request_digest,
        "approval": {
            "approved_freeze_sha256": freeze_digest,
            "approved_git_commit": head,
            "approved_phase": "GRADER_SMOKE",
            "approved_task_arm_runs": hard["task_arm_runs"],
            "approved_paid_model_call_cap": hard["paid_model_calls"],
            "approved_input_token_cap": hard["input_tokens"],
            "approved_output_token_cap": hard["output_tokens"],
            "approved_currency_hard_cap": hard["total_usd"],
            "approved_grader_containers": hard["benchmark_grader_containers"],
            "approved_workflow_run_id": "8123456789",
            "approved_workflow_run_attempt": "1",
            "approved_legal_terms_acceptance": True,
            "approval_actor": "benchmark-owner",
            "approval_timestamp": (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat().replace("+00:00", "Z"),
        },
    }) + b"\n"
    (tmp_path / "restricted-external-approval.json").write_bytes(approval_raw)
    evidence = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": request_digest,
        "approved_workflow_run_id": "8123456789",
        "approved_workflow_run_attempt": "1",
        "freeze_sha256": freeze_digest,
        "git_head": head,
        "phase": "GRADER_SMOKE",
    }
    path = tmp_path / "external-approval-evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert benchmark_matrix._approval_binding("grader-smoke", tmp_path) == {
        key: str(evidence[key]) for key in sorted(evidence)
    }
    evidence["phase"] = "HELDOUT_BENCHMARK"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(benchmark_matrix.MatrixError, match="phase"):
        benchmark_matrix._approval_binding("grader-smoke", tmp_path)
    evidence["phase"] = "GRADER_SMOKE"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    (tmp_path / "restricted-external-approval.json").write_bytes(approval_raw + b" ")
    with pytest.raises(benchmark_matrix.MatrixError, match="restricted exact"):
        benchmark_matrix._approval_binding("grader-smoke", tmp_path)


def test_benchmark_database_role_boundary_is_exact() -> None:
    benchmark_run.validate_database_role_boundary(
        "postgresql+asyncpg://postgres:admin@db.example:5432/trimem",
        "postgresql+asyncpg://api_service:runtime@db.example:5432/trimem",
    )
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="roles"):
        benchmark_run.validate_database_role_boundary(
            "postgresql+asyncpg://postgres:admin@db.example:5432/trimem",
            "postgresql+asyncpg://api_service_shadow:runtime@db.example:5432/trimem",
        )
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="endpoints"):
        benchmark_run.validate_database_role_boundary(
            "postgresql+asyncpg://postgres:admin@db.example:5432/trimem",
            "postgresql+asyncpg://api_service:runtime@other.example:5432/trimem",
        )


@pytest.mark.parametrize("arm", ["M0", "M1"])
def test_non_m2_stream_rejects_m2_artifacts_before_session_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arm: str,
) -> None:
    experiment_id = "trimemv1-aaaaaaaaaaaa-" + arm.lower()
    seed_body = {
        "schema": "trimem/benchmark-identity-seed-evidence/1.0",
        "experiment_id": experiment_id,
        "stream_id": arm,
        "rows": [],
    }
    monkeypatch.setattr(
        benchmark_run,
        "read_json",
        lambda _path: {
            "retrieval_embedding": {"production": {"model_id": "unused"}}
        },
    )
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="cannot receive an M2 policy/checkpoint",
    ):
        benchmark_run.run_arm_stream(
            split="development",
            arm=arm,
            stream_id=arm,
            runtime_lock=object(),
            m2_manifest={"unexpected": True},
            dqn_checkpoint_path=tmp_path / "unexpected-checkpoint.json",
            selected_prompt_candidate_id="baseline",
            approval={"git_head": "a" * 40},
            targets=[],
            rows={},
            tasks=[],
            workspace_factory=object(),
            checkout_evidence={},
            harnesses={},
            output_root=tmp_path,
            ledger=object(),
            database_url="unused",
            qdrant_url="unused",
            resume=False,
            identity_seed_evidence={
                **seed_body,
                "digest": benchmark_run.canonical_hash(seed_body),
            },
        )


def _sealed_public_aggregate(tmp_path: Path) -> Path:
    digest = "a" * 64
    body = {
        "schema": "trimem/verified-aggregate/1.0",
        "manifest": "heldout",
        "status": "PASS",
        "outcomes": [{
            "target_id": "t",
            "arm": "M0",
            "benchmark_id": "swebench_verified",
            "benchmark_role": "PRIMARY",
            "resolved": False,
            "actual_accounting": {"task_wall_time_ms": 17},
            "actual_memory_metrics": {"recall_attempts": 0},
            "actual_usd": "0.000000000000",
        }],
        "stream_totals": [{
            "arm": "M0",
            "actual_accounting": {"task_wall_time_ms": 17},
            "actual_memory_metrics": {"recall_attempts": 0},
            "actual_usd": "0.000000000000",
            "identity_seed_digest": "sha256:" + digest,
            "resolved_count": 0,
        }],
        "benchmark_roles": [{
            "benchmark_id": "swebench_verified",
            "dataset_id": "SWE-bench/SWE-bench_Verified",
            "dataset_revision": "c" * 40,
            "role": "PRIMARY",
            "target_count": 1,
        }],
        "benchmark_totals": [{
            "arm": "M0",
            "benchmark_id": "swebench_verified",
            "dataset_revision": "c" * 40,
            "endpoint": "official_resolved_pass_at_1",
            "n": 1,
            "pass_at_1": "0.000000000000",
            "reporting_role": "PRIMARY",
            "resolved_count": 0,
        }],
        "primary_endpoints": [{
            "arm": "M0",
            "benchmark_id": "swebench_verified",
            "dataset_revision": "c" * 40,
            "endpoint": "official_resolved_pass_at_1",
            "n": 1,
            "pass_at_1": "0.000000000000",
            "reporting_role": "PRIMARY",
            "resolved_count": 0,
        }],
        "secondary_endpoints": [],
        "approval_binding": {
            "approval_artifact_sha256": digest,
            "approved_request_sha256": digest,
            "freeze_sha256": digest,
            "git_head": "b" * 40,
            "phase": "HELDOUT_BENCHMARK",
            "approved_workflow_run_id": "8123456789",
            "approved_workflow_run_attempt": "1",
        },
    }
    aggregate = tmp_path / "aggregate.json"
    aggregate.write_text(json.dumps({
        **body,
        "aggregate_sha256": hashlib.sha256(
            json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
    }), encoding="utf-8")
    return aggregate


def test_public_artifact_consumes_only_sealed_aggregate(tmp_path: Path) -> None:
    source = tmp_path / "restricted"
    source.mkdir()
    record = {
        "target_id": "t", "arm": "M0", "runtime_arm": "M0",
        "execution_status": "SUCCESS", "official_grader": True, "resolved": False,
        "actual_accounting": {"task_wall_time_ms": 999999},
        "patch": "TOP_SECRET_GOLD", "test_patch": "TOP_SECRET_TEST",
    }
    raw_result = source / "t.result.json"
    raw_result.write_text(json.dumps(record), encoding="utf-8")
    aggregate = _sealed_public_aggregate(tmp_path)
    output = tmp_path / "public.json"
    public_artifact.package(aggregate, output)
    first = output.read_bytes()

    # Raw records can change after aggregation without entering the public
    # package; only the already-sealed aggregate is consumed.
    record["actual_accounting"]["task_wall_time_ms"] = 123456789
    record["raw_report"] = "LATE_PRIVATE_TAMPER"
    raw_result.write_text(json.dumps(record), encoding="utf-8")
    public_artifact.package(aggregate, output)
    assert output.read_bytes() == first

    text = output.read_text(encoding="utf-8")
    value = json.loads(text)
    assert "TOP_SECRET" not in text and "LATE_PRIVATE_TAMPER" not in text
    assert value["outcomes"][0]["actual_usd"] == "0.000000000000"
    assert value["outcomes"][0]["actual_accounting"]["task_wall_time_ms"] == 17
    assert value["primary_endpoints"][0]["benchmark_id"] == "swebench_verified"
    assert value["approval_binding"]["approved_workflow_run_id"] == "8123456789"


def test_public_artifact_rejects_post_aggregate_payload_tampering(tmp_path: Path) -> None:
    aggregate = _sealed_public_aggregate(tmp_path)
    value = json.loads(aggregate.read_text(encoding="utf-8"))
    value["outcomes"][0]["resolved"] = True
    aggregate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(public_artifact.PublicArtifactError, match="aggregate seal"):
        public_artifact.package(aggregate, tmp_path / "public.json")


def test_grader_smoke_protocol_is_one_nonempty_interleaved_baseline() -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    targets = grader_smoke._smoke_targets(manifest)
    assert manifest["matrix_kind"] == smoke_protocol.MATRIX_KIND
    assert manifest["noop_baseline"] == smoke_protocol.NOOP_BASELINE_LOCK
    assert len(smoke_protocol.NOOP_BASELINE_PATCH) == 165
    assert hashlib.sha256(smoke_protocol.NOOP_BASELINE_PATCH).hexdigest() == (
        "0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775"
    )
    assert [row["probe"] for row in targets] == list(smoke_protocol.PROBE_SEQUENCE)
    assert [row["order_index"] for row in targets] == list(range(12))
    for gold, noop in zip(targets[0::2], targets[1::2]):
        assert gold["instance_id"] == noop["instance_id"]
        assert gold["target_id"].endswith("--gold")
        assert noop["target_id"].endswith("--noop-baseline")
        assert grader_smoke._patch_for_target(noop, {}, manifest).encode() == (
            smoke_protocol.NOOP_BASELINE_PATCH
        )


def test_grader_smoke_rejects_empty_gold_before_grader_factory() -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    target = manifest["targets"][0]
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match="lacks patch"):
        grader_smoke._patch_for_target(target, {"patch": " \n"}, manifest)


def test_official_gateway_rejects_empty_patch_before_image_or_evaluator() -> None:
    target = _frozen_official_target("swebench_verified")
    gateway = object.__new__(official_grader.OfficialHarnessGraderGateway)
    gateway.target = target
    calls: list[str] = []
    gateway._verify_and_tag = lambda *args, **kwargs: calls.append("image")
    for patch in ("", " \n\t"):
        request = official_grader.GradeRequest(
            task_id=target.target_id,
            repository=target.repository,
            base_commit=target.base_commit,
            patch=patch,
            workspace=WorkspaceGraderContext(
                kind="test", repository_files={}, base_commit=target.base_commit,
            ),
        )
        with pytest.raises(ValueError, match="empty patch"):
            gateway.grade(request)
    assert calls == []


def test_official_gateway_requires_exact_singleton_image_digest() -> None:
    target = _frozen_official_target("swebench_verified")
    gateway = object.__new__(official_grader.OfficialHarnessGraderGateway)
    gateway.docker_binary = "docker"
    gateway._redact = lambda value: value
    gateway._restricted_streams = lambda *_args, **_kwargs: {}
    calls: list[list[str]] = []
    expected = target.image.rsplit("@", 1)[1]
    extra = "sha256:" + "e" * 64

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps([
                "example.invalid/grader@" + expected,
                "example.invalid/other@" + extra,
            ]),
            stderr="",
        )

    gateway._run = run
    gateway._failure = lambda *_args, **kwargs: official_grader.OfficialGraderError(
        str(kwargs["reason"])
    )
    with pytest.raises(official_grader.OfficialGraderError, match="digest_mismatch"):
        gateway._verify_and_tag(
            object(), 0, target.image, target.harness_image_tag, [], role="TARGET"
        )
    assert calls == [[
        "docker", "image", "inspect", "--format", "{{json .RepoDigests}}", target.image,
    ]]


def test_noop_baseline_patch_applies_as_one_file_only_index_change(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.email", "trimem@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "config", "user.name", "TriMem Test"], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "base"],
        check=True, capture_output=True,
    )
    patch = tmp_path / "noop.patch"
    patch.write_bytes(smoke_protocol.NOOP_BASELINE_PATCH)
    subprocess.run(
        ["git", "-C", str(repository), "apply", "--cached", "--check", str(patch)], check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "apply", "--cached", str(patch)], check=True,
    )
    changed = subprocess.run(
        ["git", "-C", str(repository), "diff", "--cached", "--name-status", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    marker = subprocess.run(
        ["git", "-C", str(repository), "show", ":0:.trimem_grader_noop"],
        check=True, capture_output=True,
    ).stdout
    assert changed == ["A\t.trimem_grader_noop"]
    assert marker == smoke_protocol.NOOP_BASELINE_CONTENT


def _frozen_official_target(benchmark_id: str) -> official_grader.FrozenOfficialTarget:
    swe = benchmark_id == "swebench_verified"
    return official_grader.FrozenOfficialTarget(
        target_id="target",
        benchmark_id=benchmark_id,
        instance_id="astropy__astropy-13579" if swe else "vuejs__core-8911",
        repository="astropy/astropy" if swe else "vuejs/core",
        base_commit="a" * 40,
        dataset_revision="b" * 40,
        source_row_sha256="c" * 64,
        image="example.invalid/grader@sha256:" + "d" * 64,
        harness_image_tag="example.invalid/grader:locked",
        harness_revision=(
            official_grader.SWE_HARNESS_REVISION
            if swe else official_grader.MULTI_HARNESS_REVISION
        ),
    )


def test_swe_actual_test_evidence_requires_complete_f2p_and_zero_regressions() -> None:
    target = _frozen_official_target("swebench_verified")
    source = {"FAIL_TO_PASS": ["f2p"], "PASS_TO_PASS": ["p2p"]}
    status = {
        target.instance_id: {
            "patch_exists": True,
            "patch_is_None": False,
            "patch_successfully_applied": True,
            "infra_failure": False,
            "resolved": True,
            "tests_status": {
                "FAIL_TO_PASS": {"success": ["f2p"], "failure": []},
                "PASS_TO_PASS": {"success": ["p2p"], "failure": []},
            },
        }
    }
    summary = official_grader.validate_official_test_evidence(
        target,
        source_row=source,
        test_output_raw=b"real pytest output\n",
        test_status_raw=_canonical(status),
        resolved=True,
    )
    assert summary["fail_to_pass_classified"] == summary["fail_to_pass_expected"] == 1
    assert summary["pass_to_pass_regressions"] == 0

    regressed = deepcopy(status)
    regressed[target.instance_id]["tests_status"]["PASS_TO_PASS"] = {
        "success": [], "failure": ["p2p"],
    }
    with pytest.raises(official_grader.OfficialGraderError, match="regression"):
        official_grader.validate_official_test_evidence(
            target,
            source_row=source,
            test_output_raw=b"real pytest output\n",
            test_status_raw=_canonical(regressed),
            resolved=True,
        )
    for field, value in (("patch_is_None", True), ("infra_failure", True)):
        invalid = deepcopy(status)
        invalid[target.instance_id][field] = value
        with pytest.raises(official_grader.OfficialGraderError, match="status/result"):
            official_grader.validate_official_test_evidence(
                target,
                source_row=source,
                test_output_raw=b"real pytest output\n",
                test_status_raw=_canonical(invalid),
                resolved=True,
            )


def _multi_result(
    *,
    passed: tuple[str, ...] = (),
    failed: tuple[str, ...] = (),
    skipped: tuple[str, ...] = (),
) -> dict:
    return {
        "passed_count": len(passed),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "passed_tests": list(passed),
        "failed_tests": list(failed),
        "skipped_tests": list(skipped),
    }


def _multi_source_and_noop_status() -> tuple[dict, dict]:
    stable = {"run": "PASS", "test": "PASS", "fix": "PASS"}
    repaired = {"run": "NONE", "test": "FAIL", "fix": "PASS"}
    source = {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "run_result": _multi_result(passed=("stable",)),
        "test_patch_result": _multi_result(
            passed=("stable",), failed=("target", "missing")
        ),
        "fix_patch_result": _multi_result(passed=("stable", "target", "missing")),
        "p2p_tests": {"stable": stable},
        "f2p_tests": {"target": repaired, "missing": repaired},
        "s2p_tests": {},
        "n2p_tests": {},
    }
    status = {
        "org": "vuejs", "repo": "core", "number": 8911, "valid": True,
        "error_msg": "",
        "run_result": _multi_result(passed=("stable",)),
        "test_patch_result": _multi_result(
            passed=("stable",), failed=("target", "missing")
        ),
        "fix_patch_result": _multi_result(
            passed=("stable", "target"), failed=("missing",)
        ),
        "fixed_tests": {"target": repaired},
        "p2p_tests": {"stable": stable},
        "f2p_tests": {"target": repaired},
        "s2p_tests": {},
        "n2p_tests": {},
    }
    return source, status


def _multi_final_report(resolved: bool) -> dict:
    canonical_id = "vuejs/core:pr-8911"
    return {
        "total_instances": 1,
        "submitted_instances": 1,
        "completed_instances": 1,
        "incomplete_instances": 0,
        "resolved_instances": int(resolved),
        "unresolved_instances": int(not resolved),
        "empty_patch_instances": 0,
        "error_instances": 0,
        "submitted_ids": [canonical_id],
        "completed_ids": [canonical_id],
        "incomplete_ids": [],
        "resolved_ids": [canonical_id] if resolved else [],
        "unresolved_ids": [] if resolved else [canonical_id],
        "empty_patch_ids": [],
        "error_ids": [],
    }


def test_multi_unresolved_noop_requires_and_accepts_each_full_frozen_test_domain() -> None:
    target = _frozen_official_target("multi_swe_bench_mini")
    source, status = _multi_source_and_noop_status()
    summary = official_grader.validate_official_test_evidence(
        target,
        source_row=source,
        test_output_raw=b"actual multi test output\n",
        test_status_raw=_canonical(status),
        resolved=False,
        final_report=_multi_final_report(False),
    )
    assert summary["report_valid_observed"] is True
    assert summary["report_valid_recomputed"] is True
    assert summary["expected_coverage_complete"] is False
    assert summary["expected_f2p_count"] == 2
    assert summary["observed_expected_f2p_count"] == 1
    assert summary["missing_expected_transition_count"] == 1
    assert summary["computed_resolved"] is False
    assert summary["official_final_report_resolved"] is False
    assert all(
        "stable" not in str(value) and "target" not in str(value)
        for key, value in summary.items()
        if key != "source"
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "one_test",
        "overlap",
        "duplicate",
        "run_reclassified",
        "test_reclassified",
        "source_domain_drift",
    ),
)
def test_multi_unresolved_results_reject_incomplete_or_invalid_test_domains(
    tamper: str,
) -> None:
    target = _frozen_official_target("multi_swe_bench_mini")
    source, status = _multi_source_and_noop_status()
    fix = status["fix_patch_result"]
    if tamper == "one_test":
        status["fix_patch_result"] = _multi_result(failed=("target",))
        match = "observed fixed transitions differ"
    elif tamper == "overlap":
        fix["failed_tests"].append("stable")
        fix["failed_count"] += 1
        match = "classifications overlap"
    elif tamper == "duplicate":
        fix["passed_tests"].append("stable")
        fix["passed_count"] += 1
        match = "duplicate test identifiers"
    elif tamper == "run_reclassified":
        status["run_result"] = _multi_result(failed=("stable",))
        match = "classifications differ from frozen source"
    elif tamper == "test_reclassified":
        status["test_patch_result"] = _multi_result(
            failed=("stable", "target", "missing")
        )
        match = "classifications differ from frozen source"
    else:
        source["fix_patch_result"] = _multi_result(passed=("stable", "target", "drift"))
        match = "frozen f2p_tests differs"
    with pytest.raises(official_grader.OfficialGraderError, match=match):
        official_grader.validate_official_test_evidence(
            target,
            source_row=source,
            test_output_raw=b"actual multi test output\n",
            test_status_raw=_canonical(status),
            resolved=False,
            final_report=_multi_final_report(False),
        )


def test_multi_unresolved_accepts_nonexpected_candidate_fix_result_member() -> None:
    """Pinned Report permits candidate-only result members outside expected keys."""

    target = _frozen_official_target("multi_swe_bench_mini")
    source, status = _multi_source_and_noop_status()
    fix = status["fix_patch_result"]
    fix["failed_tests"].append("rogue")
    fix["failed_count"] += 1
    summary = official_grader.validate_official_test_evidence(
        target,
        source_row=source,
        test_output_raw=b"actual multi test output\n",
        test_status_raw=_canonical(status),
        resolved=False,
        final_report=_multi_final_report(False),
    )
    assert summary["report_valid_recomputed"] is True
    assert summary["expected_coverage_complete"] is False
    assert summary["computed_resolved"] is False


def test_matrix_revalidation_rejects_tampered_multi_unresolved_test_domain() -> None:
    frozen_target = _frozen_official_target("multi_swe_bench_mini")
    target = {
        "benchmark_id": frozen_target.benchmark_id,
        "instance_id": frozen_target.instance_id,
    }
    source, status = _multi_source_and_noop_status()
    summary = official_grader.validate_official_test_evidence(
        frozen_target,
        source_row=source,
        test_output_raw=b"actual multi test output\n",
        test_status_raw=_canonical(status),
        resolved=False,
        final_report=_multi_final_report(False),
    )
    status["fix_patch_result"] = _multi_result(failed=("target",))
    with pytest.raises(benchmark_matrix.MatrixError, match="observed fixed transitions differ"):
        benchmark_matrix._validate_smoke_test_status(
            Path("multi-noop.result.json"),
            target,
            status,
            summary,
            resolved=False,
            source_row=source,
            final_report=_multi_final_report(False),
        )


def test_official_harness_invocations_bind_actual_test_evidence_paths(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    model = "trimem/smoke"
    swe_row = {
        "instance_id": "astropy__astropy-13579",
        "repo": "astropy/astropy",
        "base_commit": "a" * 40,
    }
    swe_target = replace(
        _frozen_official_target("swebench_verified"),
        source_row_sha256=official_grader.canonical_row_hash(swe_row),
    )
    swe = official_grader.build_harness_invocation(
        swe_target, row=swe_row, patch="patch", harness_root=harness,
        run_root=tmp_path / "swe-run", model_name=model,
    )
    run_id = hashlib.sha256(f"{swe_target.target_id}:{model}".encode()).hexdigest()[:20]
    expected_swe = (
        harness / "logs/run_evaluation" / run_id / "trimem__smoke" / swe_target.instance_id
    )
    assert swe.test_output_path == expected_swe / "test_output.txt"
    assert swe.test_status_path == expected_swe / "report.json"

    multi_row = {
        "org": "vuejs", "repo": "core", "number": 8911,
        "base": {"sha": "a" * 40},
    }
    multi_target = replace(
        _frozen_official_target("multi_swe_bench_mini"),
        source_row_sha256=official_grader.canonical_row_hash(multi_row),
    )
    multi_root = tmp_path / "multi-run"
    multi = official_grader.build_harness_invocation(
        multi_target, row=multi_row, patch="patch", harness_root=harness,
        run_root=multi_root, model_name=model,
    )
    expected_multi = multi_root / "work/vuejs/core/evals/pr-8911"
    assert multi.test_output_path == expected_multi / "fix-patch-run.log"
    assert multi.test_status_path == expected_multi / "report.json"


def test_official_final_reports_reject_bool_counters_and_duplicate_ids() -> None:
    swe = _frozen_official_target("swebench_verified")
    swe_report = {
        "schema_version": 2, "total_instances": 1, "submitted_instances": 1,
        "completed_instances": 1, "resolved_instances": 0, "unresolved_instances": 1,
        "infra_failure_instances": 0, "ambiguous_failure_instances": 0,
        "empty_patch_instances": 0, "error_instances": 0,
        "submitted_ids": [swe.instance_id], "completed_ids": [swe.instance_id],
        "incomplete_ids": [], "resolved_ids": [], "unresolved_ids": [swe.instance_id],
        "empty_patch_ids": [], "error_ids": [], "infra_failure_ids": [],
        "ambiguous_failure_ids": [],
    }
    assert official_grader.parse_official_report(swe, swe_report) is False
    swe_report["empty_patch_instances"] = False
    with pytest.raises(official_grader.OfficialGraderError, match="non-empty-patch"):
        official_grader.parse_official_report(swe, swe_report)

    multi = _frozen_official_target("multi_swe_bench_mini")
    canonical_id = "vuejs/core:pr-8911"
    multi_report = {
        "total_instances": 1, "submitted_instances": 1, "completed_instances": 1,
        "incomplete_instances": 0, "resolved_instances": 0, "unresolved_instances": 1,
        "empty_patch_instances": 0, "error_instances": 0,
        "submitted_ids": [canonical_id], "completed_ids": [canonical_id],
        "incomplete_ids": [], "resolved_ids": [], "unresolved_ids": [canonical_id],
        "empty_patch_ids": [], "error_ids": [],
    }
    assert official_grader.parse_official_report(multi, multi_report) is False
    multi_report["unresolved_ids"] = [canonical_id, canonical_id]
    multi_report["unresolved_instances"] = 2
    with pytest.raises(official_grader.OfficialGraderError, match="duplicated"):
        official_grader.parse_official_report(multi, multi_report)


def _smoke_blob(task: Path, name: str, raw: bytes) -> dict:
    path = task / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {
        "path": path.relative_to(task).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _smoke_json_blob(task: Path, name: str, value: dict) -> dict:
    return _smoke_blob(task, name, _canonical(value))


def _baseline_smoke_evidence_fixture(tmp_path: Path) -> tuple[Path, dict, dict, dict]:
    task = tmp_path / "baseline-task"
    task.mkdir()
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    target = {
        **manifest["targets"][1],
        "image": benchmark_matrix._locked_images()[
            manifest["targets"][1]["instance_id"]
        ],
    }
    source_row = {"FAIL_TO_PASS": ["f2p"], "PASS_TO_PASS": ["p2p"]}
    applied = _smoke_blob(
        task, "restricted-input/applied.patch", smoke_protocol.NOOP_BASELINE_PATCH
    )
    test_output_raw = b"actual official pytest output\n"
    test_output = _smoke_blob(task, "official-grader/restricted-evidence/test.bin", test_output_raw)
    status_value = {
        target["instance_id"]: {
            "patch_exists": True,
            "patch_is_None": False,
            "patch_successfully_applied": True,
            "infra_failure": False,
            "resolved": False,
            "tests_status": {
                "FAIL_TO_PASS": {"success": [], "failure": ["f2p"]},
                "PASS_TO_PASS": {"success": ["p2p"], "failure": []},
            },
        }
    }
    status_raw = _canonical(status_value)
    status = _smoke_blob(
        task, "official-grader/restricted-evidence/status.bin", status_raw
    )
    inspect_raw = _canonical([target["image"]])
    inspect_stdout = _smoke_blob(
        task, "official-grader/restricted-evidence/inspect-stdout.bin", inspect_raw
    )
    inspect_stderr = _smoke_blob(
        task, "official-grader/restricted-evidence/inspect-stderr.bin", b""
    )
    tag_stdout = _smoke_blob(
        task, "official-grader/restricted-evidence/tag-stdout.bin", b""
    )
    tag_stderr = _smoke_blob(
        task, "official-grader/restricted-evidence/tag-stderr.bin", b""
    )
    harness_stdout = _smoke_blob(
        task, "official-grader/restricted-evidence/harness-stdout.bin", b"harness\n"
    )
    harness_stderr = _smoke_blob(
        task, "official-grader/restricted-evidence/harness-stderr.bin", b""
    )
    summary = {
        "schema": "trimem/official-test-status-summary/1.0",
        "benchmark_id": target["benchmark_id"],
        "source": "SWE_PER_INSTANCE_REPORT",
        "fail_to_pass_expected": 1,
        "fail_to_pass_classified": 1,
        "fail_to_pass_failures": 1,
        "pass_to_pass_expected": 1,
        "pass_to_pass_classified": 1,
        "pass_to_pass_regressions": 0,
        "expected_test_spec_sha256": hashlib.sha256(_canonical({
            "FAIL_TO_PASS": ["f2p"], "PASS_TO_PASS": ["p2p"],
        })).hexdigest(),
        "resolved": False,
    }
    patch_doc = {
        "schema": "trimem/grader-smoke-patch-evidence/1.0",
        "mode": "OFFICIAL_GRADER_SMOKE_PRIVATE_PATCH",
        "probe": "NOOP_BASELINE",
        "patch_bytes": len(smoke_protocol.NOOP_BASELINE_PATCH),
        "patch_nonempty": True,
        "patch_sha256": smoke_protocol.NOOP_BASELINE_PATCH_SHA256,
        "restricted_applied_patch": applied,
        "noop_baseline_changed_paths": [smoke_protocol.NOOP_BASELINE_PATH],
        "source_row_sha256": target["source_row_sha256"],
        "applied_patch_bytes_retained": "RESTRICTED_EVIDENCE_ONLY",
        "gold_or_test_bytes_public": False,
    }
    tests_doc = {
        "schema": "trimem/grader-smoke-tests-evidence/1.0",
        "official_test_status": {"bytes": len(status_raw), "sha256": status["sha256"]},
        "container_exit_status": None,
        "container_exit_summary": None,
        "probe": "NOOP_BASELINE",
        "summary": summary,
        "target_id": target["target_id"],
        "test_output": {"bytes": len(test_output_raw), "sha256": test_output["sha256"]},
    }
    harness_revision = official_grader.SWE_HARNESS_REVISION
    grader_id = f"official-{target['benchmark_id']}@{harness_revision}"
    image_digest = target["image"].rsplit("@", 1)[1]
    harness_image_tag = benchmark_matrix._locked_smoke_harness_tag(
        target["instance_id"]
    )
    patch_raw = smoke_protocol.NOOP_BASELINE_PATCH
    execution_contract = grader_smoke._expected_execution_contract(target, patch_raw)
    execution_contract_sha256 = hashlib.sha256(
        _canonical(execution_contract)
    ).hexdigest()
    execution_control = grader_smoke._expected_execution_control(target)
    execution_control_sha256 = hashlib.sha256(
        _canonical(execution_control)
    ).hexdigest()
    dataset_raw = b"fixture single-row dataset\n"
    prediction_raw = grader_smoke._prediction_input_bytes(target, patch_raw)
    materialized_private_inputs = [
        {
            "name": "dataset.json",
            "sha256": hashlib.sha256(dataset_raw).hexdigest(),
            "bytes": len(dataset_raw),
            "retention": "PURGED_AFTER_HASH_BOUND_GRADING",
        },
        {
            "name": "prediction.jsonl",
            "sha256": hashlib.sha256(prediction_raw).hexdigest(),
            "bytes": len(prediction_raw),
            "retention": "PURGED_AFTER_HASH_BOUND_GRADING",
        },
    ]
    container_doc = {
        "schema": "trimem/grader-smoke-container-evidence/1.0",
        "container_digest": target["image"], "container_started": True,
        "container_exit_status_code": None,
        "container_exit_status_sha256": None,
        "exit_code": 0, "official": True, "status": "success",
        "target_id": target["target_id"],
    }
    evaluator_doc = {
        "schema": "trimem/grader-smoke-evaluator-evidence/1.0",
        "benchmark_id": target["benchmark_id"],
        "dataset_revision": target["dataset_revision"],
        "grader_id": grader_id,
        "harness_revision": harness_revision,
        "source_row_sha256": target["source_row_sha256"],
        "target_id": target["target_id"],
    }
    digest_doc = {
        "schema": "trimem/grader-smoke-digest-evidence/1.0",
        "container_digest": target["image"],
        "expected_image_digest": image_digest,
        "observed_image_digest": image_digest,
        "target_id": target["target_id"],
    }
    final_report = {
        "schema_version": 2,
        "total_instances": 1, "submitted_instances": 1, "completed_instances": 1,
        "resolved_instances": 0, "unresolved_instances": 1,
        "infra_failure_instances": 0, "ambiguous_failure_instances": 0,
        "empty_patch_instances": 0, "error_instances": 0,
        "submitted_ids": [target["instance_id"]], "completed_ids": [target["instance_id"]],
        "incomplete_ids": [], "resolved_ids": [], "unresolved_ids": [target["instance_id"]],
        "empty_patch_ids": [], "error_ids": [], "infra_failure_ids": [],
        "ambiguous_failure_ids": [],
    }
    restricted_raw_report = _smoke_json_blob(
        task,
        "official-grader/restricted-evidence/final-report.bin",
        final_report,
    )

    def grader_raw_reference(reference: dict) -> dict:
        return {
            "path": str(reference["path"]).removeprefix("official-grader/"),
            "sha256": reference["sha256"],
            "bytes": reference["bytes"],
            "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
        }

    report_doc = {
        "task_id": target["target_id"],
        "status": "success",
        "failure_stage": None,
        "reason": None,
        "_trimem": {
            "schema": official_grader.OFFICIAL_EVIDENCE_SCHEMA,
            "benchmark_id": target["benchmark_id"],
            "dataset_revision": target["dataset_revision"],
            "harness_revision": harness_revision,
            "source_row_sha256": target["source_row_sha256"],
            "execution_contract": execution_contract,
            "execution_control_evidence": execution_control,
            "materialized_private_inputs": materialized_private_inputs,
            "materialized_patch_evidence": None,
            "invocation_argv": ["python", "-m", "swebench.harness.run_evaluation"],
            "harness_invocation_status": "SUCCESS",
            "report_invocation_argv": [],
            "report_invocation_status": "NOT_APPLICABLE",
            "image_evidence": [{
                "schema": official_grader.OFFICIAL_IMAGE_EVIDENCE_SCHEMA,
                "role": "TARGET",
                "image": target["image"],
                "tag": harness_image_tag,
                "expected": image_digest,
                "observed": [image_digest],
                "inspect_argv": [
                    "docker", "image", "inspect", "--format",
                    "{{json .RepoDigests}}", target["image"],
                ],
                "inspect_invocation_status": "SUCCESS",
                "inspect_exit_code": 0,
                "inspect_restricted_raw_streams": {
                    "stdout": grader_raw_reference(inspect_stdout),
                    "stderr": grader_raw_reference(inspect_stderr),
                },
                "tag_argv": [
                    "docker", "image", "tag", target["image"], harness_image_tag,
                ],
                "tag_invocation_status": "SUCCESS",
                "tag_exit_code": 0,
                "tag_restricted_raw_streams": {
                    "stdout": grader_raw_reference(tag_stdout),
                    "stderr": grader_raw_reference(tag_stderr),
                },
            }],
            "harness_restricted_raw_streams": {
                "stdout": grader_raw_reference(harness_stdout),
                "stderr": grader_raw_reference(harness_stderr),
            },
            "report_restricted_raw_streams": None,
            "restricted_raw_report": grader_raw_reference(restricted_raw_report),
            "test_output": grader_raw_reference(test_output),
            "official_test_status": grader_raw_reference(status),
            "container_exit_status": None,
            "container_exit_summary": None,
            "semantic_normalization": summary,
            "adapter_status": "SUCCESS",
            "adapter_failure_stage": None,
            "adapter_primary_error": None,
            "adapter_secondary_evidence_failures": [],
            "official_final_report_resolved": False,
            "adapter_normalized": True,
            "scientific_resolved": False,
        },
    }
    execution_contract_doc = {
        "schema": "trimem/grader-smoke-execution-contract-evidence/1.0",
        "target_id": target["target_id"],
        "execution_contract_sha256": execution_contract_sha256,
        "execution_contract": execution_contract,
    }
    execution_control_doc = {
        "schema": "trimem/grader-smoke-execution-control-evidence/1.0",
        "target_id": target["target_id"],
        "execution_control_sha256": execution_control_sha256,
        "execution_control": execution_control,
    }
    fixture_grade = grader_smoke.GradeResult(
        task_id=target["target_id"],
        resolved=False,
        exit_code=0,
        stdout="",
        stderr="",
        report=report_doc,
        grader_id=grader_id,
        container_digest=target["image"],
        official=True,
        wall_time_ms=0,
        container_started=True,
    )
    submitted_patch_identity = grader_smoke._validated_submitted_patch_identity(
        fixture_grade,
        target=target,
        patch_raw=patch_raw,
        grader_root=task / "official-grader",
        restricted_submitted_patch=applied,
    )
    submitted_patch_identity_sha256 = hashlib.sha256(
        _canonical(submitted_patch_identity)
    ).hexdigest()
    submitted_patch_identity_doc = {
        **submitted_patch_identity,
        "identity_evidence_sha256": submitted_patch_identity_sha256,
    }
    evidence = {
        "patch": _smoke_json_blob(task, "patch-evidence.json", patch_doc),
        "tests": _smoke_json_blob(task, "tests-evidence.json", tests_doc),
        "container": _smoke_json_blob(task, "container-evidence.json", container_doc),
        "evaluator": _smoke_json_blob(task, "evaluator-evidence.json", evaluator_doc),
        "report": _smoke_json_blob(task, "report.json", report_doc),
        "digest": _smoke_json_blob(task, "digest-evidence.json", digest_doc),
        "execution_contract": _smoke_json_blob(
            task, "execution-contract-evidence.json", execution_contract_doc
        ),
        "execution_control": _smoke_json_blob(
            task, "execution-control-evidence.json", execution_control_doc
        ),
        "submitted_patch_identity": _smoke_json_blob(
            task,
            "submitted-patch-identity-evidence.json",
            submitted_patch_identity_doc,
        ),
        "stdout": _smoke_blob(task, "stdout.txt", b""),
        "stderr": _smoke_blob(task, "stderr.txt", b""),
        "applied_patch": applied,
        "test_output": test_output,
        "official_test_status": status,
        "restricted_grader_raw": [
            harness_stderr, harness_stdout, inspect_stderr, inspect_stdout,
            restricted_raw_report, status, tag_stderr, tag_stdout, test_output,
        ],
    }
    record = {
        "target_id": target["target_id"], "benchmark_id": target["benchmark_id"],
        "order_index": target["order_index"], "arm": "NOOP_BASELINE",
        "probe": "NOOP_BASELINE", "execution_status": "SUCCESS", "grader_exit_code": 0,
        "grader_id": grader_id, "grader_status": "success",
        "grader_container_digest": target["image"], "container_started": True,
        "container_exit_status_code": None,
        "container_exit_status_sha256": None,
        "official_grader": True, "resolved": False,
        "patch_bytes": len(smoke_protocol.NOOP_BASELINE_PATCH),
        "patch_sha256": smoke_protocol.NOOP_BASELINE_PATCH_SHA256,
        "expected_image_digest": image_digest, "observed_image_digest": image_digest,
        "execution_contract_sha256": execution_contract_sha256,
        "execution_control_sha256": execution_control_sha256,
        "submitted_patch_identity_sha256": submitted_patch_identity_sha256,
        "execution_evidence": {
            "patch_applied": True,
            "tests_executed": True,
            "digest_match": True,
            "submitted_patch_identity": True,
            "host_prepare_sh_access_count": 0,
            "source_image_build_count": 0,
            "api_calls": 0,
            "container_exit_status_code": None,
            "container_exit_acceptance": None,
            "container_exit_status_sha256": None,
        },
        "actual_accounting": _smoke_accounting(1),
        "evidence": evidence,
    }
    result_file = task / f"{target['target_id']}.result.json"
    result_file.write_bytes(_canonical(record))
    return result_file, record, target, source_row


def test_smoke_evidence_validator_binds_all_required_actual_evidence(tmp_path: Path) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    sealed = benchmark_matrix._validate_smoke_evidence(
        result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
    )
    assert sealed["applied_patch_sha256"] == smoke_protocol.NOOP_BASELINE_PATCH_SHA256
    assert benchmark_matrix._report_image_digest(
        result_file, record, target["image"]
    ) == target["image"].rsplit("@", 1)[1]
    benchmark_matrix._restricted_evidence(result_file, record, target)


def test_smoke_restricted_image_evidence_recomputes_digest_from_raw_inspect(
    tmp_path: Path,
) -> None:
    result_file, record, target, _source = _baseline_smoke_evidence_fixture(
        tmp_path
    )
    report_ref = record["evidence"]["report"]
    report_path = result_file.parent / report_ref["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    inspect_ref = report["_trimem"]["image_evidence"][0][
        "inspect_restricted_raw_streams"
    ]["stdout"]
    outer_path = "official-grader/" + inspect_ref["path"]
    updated = _smoke_blob(
        result_file.parent,
        outer_path,
        b'{"forged":"sha256:' + b"f" * 64 + b'"}',
    )
    report["_trimem"]["image_evidence"][0][
        "inspect_restricted_raw_streams"
    ]["stdout"] = {
        **updated,
        "path": updated["path"].removeprefix("official-grader/"),
        "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
    }
    record["evidence"]["restricted_grader_raw"] = [
        updated if row["path"] == outer_path else row
        for row in record["evidence"]["restricted_grader_raw"]
    ]
    record["evidence"]["report"] = _smoke_json_blob(
        result_file.parent, report_ref["path"], report
    )

    with pytest.raises(
        benchmark_matrix.MatrixError,
        match="raw inspect digest binding differs",
    ):
        benchmark_matrix._restricted_evidence(result_file, record, target)


def test_smoke_restricted_image_stream_references_cannot_be_reused(
    tmp_path: Path,
) -> None:
    result_file, record, target, _source = _baseline_smoke_evidence_fixture(
        tmp_path
    )
    report_ref = record["evidence"]["report"]
    report_path = result_file.parent / report_ref["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    streams = report["_trimem"]["image_evidence"][0][
        "tag_restricted_raw_streams"
    ]
    removed_path = "official-grader/" + streams["stderr"]["path"]
    streams["stderr"] = dict(streams["stdout"])
    record["evidence"]["restricted_grader_raw"] = [
        row
        for row in record["evidence"]["restricted_grader_raw"]
        if row["path"] != removed_path
    ]
    record["evidence"]["report"] = _smoke_json_blob(
        result_file.parent, report_ref["path"], report
    )

    with pytest.raises(benchmark_matrix.MatrixError, match="reference is reused"):
        benchmark_matrix._restricted_evidence(result_file, record, target)


def test_expected_multi_image_rows_bind_target_then_exact_support_lock() -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    target = next(
        row
        for row in manifest["targets"]
        if row["benchmark_id"].startswith("multi_swe_bench")
    )
    target = {
        **target,
        "image": benchmark_matrix._locked_images()[target["instance_id"]],
    }
    rows = benchmark_matrix._expected_official_image_rows(target)
    lock = _read(ROOT / "artifacts/trimem_v1/grader_image_lock.json")

    assert [row["role"] for row in rows] == ["TARGET", "SUPPORT"]
    assert rows[1] == {
        "role": "SUPPORT",
        "image": lock["support_images"][0]["image"],
        "tag": lock["support_images"][0]["harness_image_tag"],
        "expected": lock["support_images"][0]["expected_digest"],
    }


@pytest.mark.parametrize("field", ZERO_SMOKE_ACCOUNTING_FIELDS)
def test_smoke_evidence_validator_rejects_nonzero_zero_accounting(
    tmp_path: Path, field: str
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    record["actual_accounting"][field] = 1
    with pytest.raises(benchmark_matrix.MatrixError, match="exact accounting mismatch"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_matrix_independently_revalidates_multi_container_exit_patch_and_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_raw = b"diff --git a/a b/a\n"
    expected_tag = "mswebench/vuejs_m_core:pr-8911"
    target = {
        "target_id": "multi_swe_bench_mini--vuejs__core-8911--noop-baseline",
        "benchmark_id": "multi_swe_bench_mini",
        "instance_id": "vuejs__core-8911",
        "repository": "vuejs/core",
        "base_commit": "a" * 40,
        "dataset_revision": "b" * 40,
        "source_row_sha256": "c" * 64,
        "image": "mswebench/vuejs_m_core@sha256:" + "d" * 64,
    }
    summary = {
        "schema": "trimem/multi-swe-report-semantics/1.0",
        "report_valid_observed": False,
        "report_valid_recomputed": False,
        "report_valid_match": True,
        "expected_coverage_complete": True,
        "expected_p2p_count": 0,
        "observed_expected_p2p_count": 0,
        "expected_f2p_count": 1,
        "observed_expected_f2p_count": 1,
        "expected_s2p_count": 0,
        "observed_expected_s2p_count": 0,
        "expected_n2p_count": 0,
        "observed_expected_n2p_count": 0,
        "missing_expected_transition_count": 0,
        "expected_transition_domain_sha256": "e" * 64,
        "observed_expected_transition_domain_sha256": "e" * 64,
        "computed_resolved": False,
        "official_final_report_resolved": False,
        "final_report_match": True,
        "report_invalidity_reason": "NO_NON_PASS_TO_PASS_TRANSITION",
    }
    status = {
        "executed_image": target["image"],
        "expected_image": target["image"],
        "expected_tag": expected_tag,
        "image_id": "sha256:" + "f" * 64,
        "run_command": official_grader.MULTI_FIX_PATCH_RUN_COMMAND,
        "schema": "trimem/multi-swe-container-exit-status/1.0",
        "status_code": 1,
        "submitted_patch_bytes": len(patch_raw),
        "submitted_patch_sha256": hashlib.sha256(patch_raw).hexdigest(),
    }
    raw = json.dumps(status, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    evidence_path = tmp_path / "restricted/container-exit-status.json"
    evidence_path.parent.mkdir()
    evidence_path.write_bytes(raw)
    result_file = tmp_path / "cell.result.json"
    record = {
        "resolved": False,
        "evidence": {
            "container_exit_status": {
                "path": "restricted/container-exit-status.json",
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        },
    }
    frozen = official_grader.FrozenOfficialTarget(
        **target,
        harness_image_tag=expected_tag,
        harness_revision=official_grader.MULTI_HARNESS_REVISION,
    )
    expected_summary = official_grader.validate_multi_swe_container_exit_status(
        frozen,
        raw=raw,
        resolved=False,
        test_summary=summary,
        expected_patch=patch_raw.decode(),
    )
    tests_evidence = {
        "container_exit_status": {
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "container_exit_summary": expected_summary,
    }
    monkeypatch.setattr(
        benchmark_matrix, "_locked_smoke_harness_tag", lambda _instance: expected_tag
    )

    observed_raw, observed_summary = benchmark_matrix._validate_smoke_container_exit(
        result_file,
        record,
        target,
        raw_patch=patch_raw,
        test_summary=summary,
        expected_harness_revision=official_grader.MULTI_HARNESS_REVISION,
        tests_evidence=tests_evidence,
    )
    assert observed_raw == raw
    assert observed_summary == expected_summary

    status["submitted_patch_sha256"] = "0" * 64
    tampered = json.dumps(status, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    evidence_path.write_bytes(tampered)
    record["evidence"]["container_exit_status"].update(
        bytes=len(tampered), sha256=hashlib.sha256(tampered).hexdigest()
    )
    tests_evidence["container_exit_status"] = {
        "bytes": len(tampered),
        "sha256": hashlib.sha256(tampered).hexdigest(),
    }
    with pytest.raises(benchmark_matrix.MatrixError, match="independently validate"):
        benchmark_matrix._validate_smoke_container_exit(
            result_file,
            record,
            target,
            raw_patch=patch_raw,
            test_summary=summary,
            expected_harness_revision=official_grader.MULTI_HARNESS_REVISION,
            tests_evidence=tests_evidence,
        )


def test_smoke_restricted_raw_evidence_cannot_remove_report_group_and_files(
    tmp_path: Path,
) -> None:
    result_file, record, target, _source = _baseline_smoke_evidence_fixture(tmp_path)
    report_ref = record["evidence"]["report"]
    report_path = result_file.parent / report_ref["path"]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    del report["_trimem"]["harness_restricted_raw_streams"]
    record["evidence"]["report"] = _smoke_json_blob(
        result_file.parent, report_ref["path"], report
    )
    record["evidence"]["restricted_grader_raw"] = [
        reference
        for reference in record["evidence"]["restricted_grader_raw"]
        if "harness-" not in reference["path"]
    ]
    with pytest.raises(benchmark_matrix.MatrixError, match="official harness raw stream"):
        benchmark_matrix._restricted_evidence(result_file, record, target)


@pytest.mark.parametrize(
    ("evidence_name", "field", "value", "message"),
    [
        ("patch", "patch_nonempty", False, "applied-patch"),
        ("tests", "probe", "GOLD", "tests evidence"),
        ("container", "status", "failure", "container evidence"),
        ("container", "exit_code", False, "container evidence"),
        ("evaluator", "source_row_sha256", "f" * 64, "evaluator"),
        ("report", "empty_patch_ids", ["astropy__astropy-13579"], "final official report"),
        ("digest", "observed_image_digest", "f" * 64, "digest evidence"),
    ],
)
def test_smoke_evidence_validator_rejects_semantic_tampering(
    tmp_path: Path, evidence_name: str, field: str, value: object, message: str
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    reference = record["evidence"][evidence_name]
    evidence_path = result_file.parent / reference["path"]
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence_name == "report" and field == "empty_patch_ids":
        raw_reference = document["_trimem"]["restricted_raw_report"]
        raw_path = (
            result_file.parent / "official-grader" / raw_reference["path"]
        )
        final_report = json.loads(raw_path.read_text(encoding="utf-8"))
        final_report[field] = value
        updated_raw_reference = _smoke_json_blob(
            result_file.parent,
            "official-grader/" + raw_reference["path"],
            final_report,
        )
        document["_trimem"]["restricted_raw_report"] = {
            "path": raw_reference["path"],
            "sha256": updated_raw_reference["sha256"],
            "bytes": updated_raw_reference["bytes"],
            "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
        }
        record["evidence"]["restricted_grader_raw"] = [
            updated_raw_reference
            if row["path"] == updated_raw_reference["path"]
            else row
            for row in record["evidence"]["restricted_grader_raw"]
        ]
    else:
        document[field] = value
    record["evidence"][evidence_name] = _smoke_json_blob(
        result_file.parent, reference["path"], document
    )
    with pytest.raises(benchmark_matrix.MatrixError, match=message):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_hash_consistent_baseline_patch_substitution(
    tmp_path: Path,
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    substituted = smoke_protocol.NOOP_BASELINE_PATCH + b"# extra\n"
    applied = _smoke_blob(result_file.parent, "restricted-input/applied.patch", substituted)
    record["evidence"]["applied_patch"] = applied
    record["patch_bytes"] = len(substituted)
    record["patch_sha256"] = applied["sha256"]
    patch_path = result_file.parent / record["evidence"]["patch"]["path"]
    patch_doc = json.loads(patch_path.read_text(encoding="utf-8"))
    patch_doc.update({
        "patch_bytes": len(substituted), "patch_sha256": applied["sha256"],
        "restricted_applied_patch": applied,
    })
    record["evidence"]["patch"] = _smoke_json_blob(
        result_file.parent, record["evidence"]["patch"]["path"], patch_doc
    )
    with pytest.raises(benchmark_matrix.MatrixError, match="frozen bytes"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_empty_actual_test_output(tmp_path: Path) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    record["evidence"]["test_output"] = _smoke_blob(
        result_file.parent, "official-grader/restricted-evidence/test.bin", b"\n"
    )
    with pytest.raises(benchmark_matrix.MatrixError, match="actual official test evidence is empty"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_empty_official_test_status(
    tmp_path: Path,
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    record["evidence"]["official_test_status"] = _smoke_blob(
        result_file.parent, "official-grader/restricted-evidence/status.bin", b"\n"
    )
    with pytest.raises(benchmark_matrix.MatrixError, match="actual official test evidence is empty"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def test_smoke_evidence_validator_rejects_missing_mandatory_reference(
    tmp_path: Path,
) -> None:
    result_file, record, target, source = _baseline_smoke_evidence_fixture(tmp_path)
    del record["evidence"]["evaluator"]
    with pytest.raises(benchmark_matrix.MatrixError, match="missing evaluator evidence"):
        benchmark_matrix._validate_smoke_evidence(
            result_file, record, target, source, official_grader.SWE_HARNESS_REVISION
        )


def _aggregate_count_fixture() -> tuple[list[dict], list[tuple[Path, dict]]]:
    targets: list[dict] = []
    records: list[tuple[Path, dict]] = []
    image = "example.invalid/grader@sha256:" + "d" * 64
    for identity in range(6):
        for probe, resolved in (("GOLD", True), ("NOOP_BASELINE", False)):
            order = len(targets)
            target_id = f"benchmark--instance-{identity}--{probe.lower().replace('_', '-')}"
            target = {
                "target_id": target_id,
                "benchmark_id": (
                    "swebench_verified"
                    if identity < 2
                    else "multi_swe_bench_mini"
                ),
                "instance_id": f"org__repo-{identity}",
                "probe": probe,
                "expected_resolved": resolved,
                "order_index": order,
                "image": image,
            }
            targets.append(target)
            records.append((Path(f"{order:02d}.result.json"), {
                "schema": "trimem/grader-smoke-terminal-cell/2.0",
                "target_id": target_id,
                "execution_status": "SUCCESS",
                "grader_exit_code": 0,
                "grader_status": "success",
                "grader_invoked": True,
                "container_started": True,
                "harness_completed": True,
                "final_report_generated": True,
                "official_tests_executed": True,
                "raw_test_evidence_captured": True,
                "submitted_patch_identity_verified": True,
                "digest_verified": True,
                "adapter_normalized": True,
                "authoritative_cell": True,
                "official_final_report_resolved": resolved,
                "scientific_resolved": resolved,
                "primary_failure": None,
                "secondary_evidence_failures": [],
                "official_grader": True,
                "expected_image_digest": "sha256:" + "d" * 64,
                "observed_image_digest": "sha256:" + "d" * 64,
                "resolved": resolved,
                "actual_accounting": _smoke_accounting(1),
                "evidence": {
                    name: {}
                    for name in (
                        "patch",
                        "tests",
                        "container",
                        "evaluator",
                        "report",
                        "digest",
                        "execution_contract",
                        "execution_control",
                        "submitted_patch_identity",
                        "applied_patch",
                        "test_output",
                        "official_test_status",
                    )
                },
            }))
            if identity >= 2:
                records[-1][1]["evidence"]["container_exit_status"] = {}
    return targets, records


def test_smoke_aggregate_requires_exact_six_by_six_and_preserves_manifest_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    targets, records = _aggregate_count_fixture()
    monkeypatch.setattr(benchmark_matrix, "execution_matrix", lambda name: targets)
    monkeypatch.setattr(
        benchmark_matrix, "_smoke_source_rows", lambda rows: {row["target_id"]: {} for row in rows}
    )
    monkeypatch.setattr(
        benchmark_matrix, "_locked_harness_revisions",
        lambda: {
            "swebench_verified": official_grader.SWE_HARNESS_REVISION,
            "multi_swe_bench_mini": official_grader.MULTI_HARNESS_REVISION,
        },
    )
    monkeypatch.setattr(benchmark_matrix, "_result_records", lambda root: records)
    monkeypatch.setattr(
        benchmark_matrix, "_report_image_digest",
        lambda path, record, image: image.rsplit("@", 1)[1],
    )
    monkeypatch.setattr(benchmark_matrix, "_evidence_file", lambda *args: b"")
    monkeypatch.setattr(benchmark_matrix, "_restricted_evidence", lambda *args: None)
    monkeypatch.setattr(
        benchmark_matrix,
        "_validate_smoke_evidence",
        lambda path, record, target, source, revision: {
            "applied_patch_sha256": "a" * 64,
            "official_test_output_sha256": "b" * 64,
            "official_test_status_sha256": "c" * 64,
            "container_exit_status_sha256": (
                None
                if target["benchmark_id"] == "swebench_verified"
                else "9" * 64
            ),
            "execution_contract_sha256": "d" * 64,
            "execution_control_sha256": "e" * 64,
            "submitted_patch_identity_sha256": "f" * 64,
            "patch_applied": True,
            "tests_executed": True,
            "digest_match": True,
            "submitted_patch_identity": True,
            "host_prepare_sh_access_count": 0,
            "source_image_build_count": 0,
            "api_calls": 0,
            "container_exit_status_code": (
                None
                if target["benchmark_id"] == "swebench_verified"
                else (0 if target["expected_resolved"] else 1)
            ),
            "container_exit_acceptance": (
                None
                if target["benchmark_id"] == "swebench_verified"
                else (
                    "ZERO_EXIT"
                    if target["expected_resolved"]
                    else "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION"
                )
            ),
        },
    )
    result = benchmark_matrix._aggregate_smoke(tmp_path)
    assert result["probe_counts"] == {"GOLD": 6, "NOOP_BASELINE": 6}
    assert result["resolved_counts"] == {"GOLD": 6, "NOOP_BASELINE": 0}
    assert result["unresolved_counts"] == {"GOLD": 0, "NOOP_BASELINE": 6}
    assert result["patch_applied_count"] == 12
    assert result["tests_executed_count"] == 12
    assert result["digest_match_count"] == 12
    assert result["submitted_patch_identity_count"] == 12
    assert result["host_prepare_sh_access_count"] == 0
    assert result["source_image_build_count"] == 0
    assert result["container_exit_status_captured_count"] == 8
    assert result["container_exit_status_validated_count"] == 8
    assert result["resolved_container_zero_exit_count"] == 4
    assert result["api_calls"] == 0
    assert result["attempted_cell_count"] == 12
    assert result["terminal_record_count"] == 12
    assert result["official_execution_count"] == 12
    assert result["complete_execution_evidence_count"] == 12
    assert result["adapter_normalized_count"] == 12
    assert result["authoritative_cell_count"] == 12
    assert result["unattempted_cell_count"] == 0
    assert all(result[field] == 0 for field in grader_smoke.FAILURE_TAXONOMY_FIELDS)
    assert result["empty_patch_ids"] == []
    assert result["evidence_counts"]["container_exit_status"] == 8
    assert all(
        count == 12
        for name, count in result["evidence_counts"].items()
        if name != "container_exit_status"
    )
    assert [row["target_id"] for row in result["outcomes"]] == [
        row["target_id"] for row in targets
    ]

    targets[-1]["probe"] = "GOLD"
    targets[-1]["expected_resolved"] = True
    records[-1][1]["resolved"] = True
    records[-1][1]["official_final_report_resolved"] = True
    records[-1][1]["scientific_resolved"] = True
    with pytest.raises(benchmark_matrix.MatrixError, match="exact 6/6"):
        benchmark_matrix._aggregate_smoke(tmp_path)


def test_exec_005_downstream_failure_rollback_drives_exact_closure_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_root = tmp_path / "rollback-closure"
    _smoke, seed_receipt, _receipt_raw, _inventory_raw = (
        _fresh_exec_005_failure_fixture(
            seed_root,
            monkeypatch,
            taxonomy_field="aggregate_failures",
        )
    )
    restricted_root = seed_root / "restricted"
    results_root = restricted_root / "results"
    terminal_paths = sorted(results_root.rglob("*.result.json"))
    assert len(terminal_paths) == 12
    for index, path in enumerate(terminal_paths):
        terminal = json.loads(path.read_text(encoding="utf-8"))
        terminal["authoritative_cell"] = True
        expected = index % 2 == 0
        terminal["official_final_report_resolved"] = expected
        terminal["scientific_resolved"] = expected
        path.write_bytes(readiness._pretty_json(terminal))

    private_reason = "cleanup failed at C:/private/runner/secret-path"
    rollback = smoke_authority.rollback_authoritative_terminal_records(
        results_root,
        cause_stage="image_cleanup",
        failure_taxonomy="image_lifecycle_failures",
        reason=private_reason,
    )
    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    inventory_raw = _canonical(inventory) + b"\n"
    request_raw = (
        seed_root / readiness.GRADER_SMOKE_SENTINEL_PATH
    ).read_bytes()
    receipt = failure_closure.build_failure_closure(
        restricted_root=restricted_root,
        inventory_raw=inventory_raw,
        request_raw=request_raw,
        approval_binding=seed_receipt["approval_binding"],
        workflow_run=seed_receipt["workflow_run"],
    )
    receipt_raw = readiness._pretty_json(receipt)
    validated = failure_closure.validate_failure_closure(
        receipt_raw,
        inventory_raw,
        request_raw=request_raw,
        restricted_root=restricted_root,
    )

    assert validated["terminal_summary"]["authoritative_cell_count"] == 0
    assert validated["failure_taxonomy"]["image_lifecycle_failures"] == 1
    assert sum(validated["failure_taxonomy"].values()) == 1
    assert validated["endpoint"] == readiness.P015_INCOMPLETE_ENDPOINT
    assert validated["scientific_result"] == "NOT_AGGREGATED"
    assert validated["authority_rollback"]["payload_sha256"] == rollback[
        "payload_sha256"
    ]
    assert private_reason.encode() not in receipt_raw


def test_exec_005_interrupted_authority_finalization_has_one_infrastructure_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed_root = tmp_path / "authority-recovery-closure"
    _smoke, seed_receipt, _receipt_raw, _inventory_raw = (
        _fresh_exec_005_failure_fixture(
            seed_root,
            monkeypatch,
            taxonomy_field="aggregate_failures",
        )
    )
    restricted_root = seed_root / "restricted"
    results_root = restricted_root / "results"
    terminal_paths = sorted(results_root.rglob("*.result.json"))
    assert len(terminal_paths) == 12
    for index, path in enumerate(terminal_paths):
        terminal = json.loads(path.read_text(encoding="utf-8"))
        expected = index % 2 == 0
        terminal["official_final_report_resolved"] = expected
        terminal["scientific_resolved"] = expected
        terminal["authoritative_cell"] = False
        path.write_bytes(readiness._pretty_json(terminal))
    (results_root / "smoke-execution-summary.json").unlink(missing_ok=True)
    journal = finalization_journal.write_finalization_journal(
        results_root,
        status=finalization_journal.AUTHORITY_PROMOTION_STARTED,
    )

    private_reason = "authority commit failed at C:/private/runner/transaction"
    recovery = smoke_authority.recover_interrupted_authority_transaction(
        results_root,
        cause_stage="authority_finalization",
        failure_taxonomy="infrastructure_failures",
        reason=private_reason,
    )
    assert recovery is not None
    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    inventory_raw = _canonical(inventory) + b"\n"
    request_raw = (
        seed_root / readiness.GRADER_SMOKE_SENTINEL_PATH
    ).read_bytes()
    receipt = failure_closure.build_failure_closure(
        restricted_root=restricted_root,
        inventory_raw=inventory_raw,
        request_raw=request_raw,
        approval_binding=seed_receipt["approval_binding"],
        workflow_run=seed_receipt["workflow_run"],
    )
    receipt_raw = readiness._pretty_json(receipt)
    validated = failure_closure.validate_failure_closure(
        receipt_raw,
        inventory_raw,
        request_raw=request_raw,
        restricted_root=restricted_root,
    )

    assert validated["terminal_summary"]["authoritative_cell_count"] == 0
    assert validated["failure_taxonomy"]["infrastructure_failures"] == 1
    assert sum(validated["failure_taxonomy"].values()) == 1
    assert validated["endpoint"] == readiness.P015_INCOMPLETE_ENDPOINT
    assert validated["scientific_result"] == "NOT_AGGREGATED"
    assert validated["authority_rollback"]["schema"] == (
        smoke_authority.RECOVERY_EVIDENCE_SCHEMA
    )
    assert validated["authority_rollback"]["payload_sha256"] == recovery[
        "payload_sha256"
    ]
    assert validated["authority_rollback"]["finalization_journal"] == {
        "bytes": (
            results_root / finalization_journal.RELATIVE_PATH
        ).stat().st_size,
        "path": "results/" + finalization_journal.RELATIVE_PATH.as_posix(),
        "payload_sha256": journal["payload_sha256"],
        "sha256": hashlib.sha256(
            (results_root / finalization_journal.RELATIVE_PATH).read_bytes()
        ).hexdigest(),
        "status": finalization_journal.AUTHORITY_PROMOTION_STARTED,
    }
    assert private_reason.encode() not in receipt_raw

    journal_path = results_root / finalization_journal.RELATIVE_PATH
    journal_path.write_bytes(journal_path.read_bytes() + b"tampered")
    tampered_inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    with pytest.raises(
        failure_closure.FailureClosureError,
        match="finalization journal is not inventory-bound",
    ):
        failure_closure.build_failure_closure(
            restricted_root=restricted_root,
            inventory_raw=_canonical(tampered_inventory) + b"\n",
            request_raw=request_raw,
            approval_binding=seed_receipt["approval_binding"],
            workflow_run=seed_receipt["workflow_run"],
        )


@pytest.mark.parametrize(
    ("boundary", "private_reason"),
    (
        (
            "12th-after_target",
            "after_target failed at C:/private/runner/remove-final-image",
        ),
        (
            "finish",
            "finish failed at C:/private/runner/lifecycle-finalization",
        ),
    ),
)
def test_exec_005_complete_false_tree_lifecycle_boundary_keeps_image_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    private_reason: str,
) -> None:
    seed_root = tmp_path / boundary
    _smoke, seed_receipt, _receipt_raw, _inventory_raw = (
        _fresh_exec_005_failure_fixture(
            seed_root,
            monkeypatch,
            taxonomy_field="aggregate_failures",
        )
    )
    restricted_root = seed_root / "restricted"
    results_root = restricted_root / "results"
    terminal_paths = sorted(results_root.rglob("*.result.json"))
    assert len(terminal_paths) == 12
    for index, path in enumerate(terminal_paths):
        terminal = json.loads(path.read_text(encoding="utf-8"))
        expected = index % 2 == 0
        terminal["official_final_report_resolved"] = expected
        terminal["scientific_resolved"] = expected
        terminal["primary_failure"] = None
        terminal["execution_status"] = "SUCCESS"
        terminal["authoritative_cell"] = False
        path.write_bytes(readiness._pretty_json(terminal))

    (results_root / "smoke-execution-summary.json").unlink(missing_ok=True)
    journal_path = results_root / finalization_journal.RELATIVE_PATH
    assert not journal_path.exists()
    lifecycle_path = (
        restricted_root / "image-materialization/image-lifecycle-report.json"
    )
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    lifecycle["status"] = "FAILED"
    lifecycle["failure"] = {
        "error_type": "SyntheticLifecycleBoundaryFailure",
        "error": private_reason,
    }
    lifecycle_path.write_bytes(readiness._pretty_json(lifecycle))

    recovery = smoke_authority.recover_interrupted_authority_transaction(
        results_root,
        cause_stage="authority_finalization",
        failure_taxonomy="infrastructure_failures",
        reason="run_smoke did not succeed",
    )
    assert recovery is None
    assert not (
        results_root / smoke_authority.DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH
    ).exists()

    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    inventory_raw = _canonical(inventory) + b"\n"
    request_raw = (
        seed_root / readiness.GRADER_SMOKE_SENTINEL_PATH
    ).read_bytes()
    receipt = failure_closure.build_failure_closure(
        restricted_root=restricted_root,
        inventory_raw=inventory_raw,
        request_raw=request_raw,
        approval_binding=seed_receipt["approval_binding"],
        workflow_run=seed_receipt["workflow_run"],
    )
    receipt_raw = readiness._pretty_json(receipt)
    validated = failure_closure.validate_failure_closure(
        receipt_raw,
        inventory_raw,
        request_raw=request_raw,
        restricted_root=restricted_root,
    )

    assert validated["terminal_summary"]["terminal_record_count"] == 12
    assert validated["terminal_summary"]["adapter_normalized_count"] == 12
    assert validated["terminal_summary"]["authoritative_cell_count"] == 0
    assert validated["authority_rollback"] is None
    assert validated["failure_taxonomy"]["image_lifecycle_failures"] == 1
    assert sum(validated["failure_taxonomy"].values()) == 1
    assert validated["scientific_result"] == "NOT_AGGREGATED"
    assert validated["endpoint"] == readiness.P015_INCOMPLETE_ENDPOINT
    assert private_reason.encode() not in receipt_raw


def test_failed_closure_never_allows_an_empty_primary_taxonomy() -> None:
    summary, taxonomy, actual, endpoint, scientific = failure_closure._derive(
        [],
        {
            "status": "IN_PROGRESS",
            "support_image_pulls": 0,
            "target_image_pulls": 0,
        },
        None,
        None,
    )

    assert summary["terminal_record_count"] == 0
    assert taxonomy["infrastructure_failures"] == 1
    assert sum(taxonomy.values()) == 1
    assert actual["grader_containers"] == 0
    assert endpoint == readiness.P015_INCOMPLETE_ENDPOINT
    assert scientific == "NOT_AGGREGATED"


@pytest.mark.parametrize(
    ("failure_mode", "expected_outcome", "expected_failure_stage"),
    (
        ("nonzero", "INSPECT_NONZERO", "INSPECT"),
        ("timeout", "INSPECT_TIMEOUT", "INSPECT"),
        ("invalid", "INSPECT_OUTPUT_INVALID", "INSPECT_OUTPUT"),
        ("digest_mismatch", "DIGEST_MISMATCH", "DIGEST_VERIFICATION"),
    ),
)
def test_pull_pass_inspect_failure_is_materialized_and_stage_truthful(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
    expected_outcome: str,
    expected_failure_stage: str,
) -> None:
    """Exercise the production pull, lifecycle, inventory, and closure path."""

    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    target = manifest["targets"][0]
    image = images[target["instance_id"]]["image"]
    other = "registry.example/other@sha256:" + "f" * 64
    restricted_root = tmp_path / "restricted"
    image_root = restricted_root / "image-materialization"

    def fake_subprocess_run(argv: list[str], **_kwargs: object):
        if argv[:2] == ["docker", "pull"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=b"pull complete\xff\n", stderr=b""
            )
        if argv[:3] == ["docker", "image", "inspect"]:
            if failure_mode == "nonzero":
                return subprocess.CompletedProcess(
                    argv, 42, stdout=b"", stderr=b"inspect failed\xfe\n"
                )
            if failure_mode == "timeout":
                raise subprocess.TimeoutExpired(
                    cmd=argv,
                    timeout=3600,
                    output=b"partial inspect\xff",
                    stderr=b"timeout detail\xfe",
                )
            if failure_mode == "invalid":
                stdout = b'{"not":"a RepoDigests list"}\xff'
            else:
                stdout = json.dumps([other]).encode("utf-8")
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")
        if argv[:4] == ["docker", "image", "rm", "--force"]:
            return subprocess.CompletedProcess(
                argv, 0, stdout=b"removed\n", stderr=b""
            )
        raise AssertionError(f"unexpected command: {argv!r}")

    monkeypatch.setattr(image_pull.subprocess, "run", fake_subprocess_run)
    approval = {
        "phase": "GRADER_SMOKE",
        "approval_artifact_sha256": "a" * 64,
        "git_head": "b" * 40,
    }
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval=approval,
        evidence_root=image_root,
        targets=manifest["targets"],
        images=images,
        support=support,
    )

    with pytest.raises(benchmark_run.BenchmarkExecutionError) as captured:
        lifecycle.before_target(0, target)
    primary_type = type(captured.value).__name__
    primary_message = str(captured.value)
    lifecycle.abort(captured.value)

    report_path = image_root / "image-lifecycle-report.json"
    report = _read(report_path)
    failed_event = report["events"][0]
    assert report["status"] == "FAILED"
    assert report["actual"]["target_image_pulls"] == 1
    assert report["actual"]["resident_target_images"] == 0
    assert failed_event["action"] == "PULL_TARGET_FAILED"
    assert failed_event["pull_materialized"] is True
    assert failed_event["failure_stage"] == expected_failure_stage
    assert failed_event["error_type"] == primary_type
    assert failed_event["error"] == primary_message
    assert report["failure"]["error_type"] == primary_type
    assert report["failure"]["error"] == primary_message

    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    rows = {row["path"]: row for row in inventory["files"]}
    projection = failure_closure._lifecycle_projection(
        report_path.read_bytes(),
        reference=rows["image-materialization/image-lifecycle-report.json"],
        approval=approval,
        restricted_root=restricted_root,
        inventory_rows=rows,
    )
    validated = failure_closure._validate_lifecycle_projection(projection)
    attempt = validated["pull_attempts"][0]
    assert validated["target_image_pulls"] == 1
    assert validated["target_image_materialized_count"] == 1
    assert attempt["outcome"] == expected_outcome
    assert attempt["image_materialized"] is True
    assert attempt["pull_status"] == "PASS"
    assert attempt["pull_returncode"] == 0
    assert attempt["inspect_status"] == (
        "NONZERO"
        if failure_mode == "nonzero"
        else "TIMEOUT"
        if failure_mode == "timeout"
        else "PASS"
    )
    assert attempt["restricted_pull_stage"] == rows[
        "image-materialization/000-pull/stage.json"
    ]
    assert attempt["restricted_inspect_stage"] == rows[
        "image-materialization/000-inspect/stage.json"
    ]


def test_pull_pass_inspect_failure_requires_inventory_bound_inspect_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _read(ROOT / "configs/trimem_v1/grader_smoke_manifest.json")
    images, support = benchmark_run.image_entries(require_benchmark=False)
    target = manifest["targets"][0]
    restricted_root = tmp_path / "restricted"
    image_root = restricted_root / "image-materialization"

    def fake_subprocess_run(argv: list[str], **_kwargs: object):
        if argv[:2] == ["docker", "pull"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        if argv[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(
                argv, 9, stdout=b"", stderr=b"failed"
            )
        if argv[:4] == ["docker", "image", "rm", "--force"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        raise AssertionError(f"unexpected command: {argv!r}")

    monkeypatch.setattr(image_pull.subprocess, "run", fake_subprocess_run)
    approval = {
        "phase": "GRADER_SMOKE",
        "approval_artifact_sha256": "a" * 64,
        "git_head": "b" * 40,
    }
    lifecycle = grader_smoke._SerialImageLifecycle(
        approval=approval,
        evidence_root=image_root,
        targets=manifest["targets"],
        images=images,
        support=support,
    )
    with pytest.raises(benchmark_run.BenchmarkExecutionError) as captured:
        lifecycle.before_target(0, target)
    lifecycle.abort(captured.value)
    report_path = image_root / "image-lifecycle-report.json"
    inventory = evidence_inventory.build_inventory(
        restricted_root, root_label="grader_smoke_exec"
    )
    rows = {row["path"]: row for row in inventory["files"]}
    del rows["image-materialization/000-inspect/stderr.txt"]

    with pytest.raises(
        failure_closure.FailureClosureError,
        match="image inspect stderr is not inventory-bound",
    ):
        failure_closure._lifecycle_projection(
            report_path.read_bytes(),
            reference=rows["image-materialization/image-lifecycle-report.json"],
            approval=approval,
            restricted_root=restricted_root,
            inventory_rows=rows,
        )
