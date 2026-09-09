from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_grader_smoke as grader_smoke  # noqa: E402
import trimem_multi_swe_report_semantics as report_semantics  # noqa: E402
import trimem_official_grader as official_grader  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402
from enterprise_memory.trimem.grader import GradeResult  # noqa: E402


INSTANCE_ID = "vuejs__core-8911"
CANONICAL_ID = "vuejs/core:pr-8911"
DIGEST = "d" * 64


def _result(
    *,
    passed: tuple[str, ...] = (),
    failed: tuple[str, ...] = (),
    skipped: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "passed_count": len(passed),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "passed_tests": list(passed),
        "failed_tests": list(failed),
        "skipped_tests": list(skipped),
    }


def _transition(run: str, test: str, fix: str) -> dict[str, str]:
    return {"run": run, "test": test, "fix": fix}


def _source_and_status() -> tuple[dict[str, object], dict[str, object]]:
    stable = "SECRET_TEST_NAME::private/stable"
    repaired = "SECRET_TEST_NAME::private/repaired"
    run = _result(passed=(stable,), failed=(repaired,))
    test = _result(passed=(stable,), failed=(repaired,))
    fix = _result(passed=(stable, repaired))
    categories = {
        "p2p_tests": {stable: _transition("PASS", "PASS", "PASS")},
        "f2p_tests": {repaired: _transition("FAIL", "FAIL", "PASS")},
        "s2p_tests": {},
        "n2p_tests": {},
    }
    source: dict[str, object] = {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "run_result": run,
        "test_patch_result": test,
        "fix_patch_result": fix,
        **categories,
    }
    status: dict[str, object] = {
        "org": "vuejs",
        "repo": "core",
        "number": 8911,
        "valid": True,
        "error_msg": "",
        "fixed_tests": {
            repaired: _transition("FAIL", "FAIL", "PASS"),
        },
        "run_result": run,
        "test_patch_result": test,
        "fix_patch_result": fix,
        **categories,
    }
    return source, status


def _final_report(resolved: bool) -> dict[str, object]:
    return {
        "total_instances": 1,
        "submitted_instances": 1,
        "completed_instances": 1,
        "incomplete_instances": 0,
        "resolved_instances": int(resolved),
        "unresolved_instances": int(not resolved),
        "empty_patch_instances": 0,
        "error_instances": 0,
        "submitted_ids": [CANONICAL_ID],
        "completed_ids": [CANONICAL_ID],
        "incomplete_ids": [],
        "resolved_ids": [CANONICAL_ID] if resolved else [],
        "unresolved_ids": [] if resolved else [CANONICAL_ID],
        "empty_patch_ids": [],
        "error_ids": [],
    }


def _target() -> official_grader.FrozenOfficialTarget:
    return official_grader.FrozenOfficialTarget(
        target_id="multi_swe_bench_mini--vuejs__core-8911--gold",
        benchmark_id="multi_swe_bench_mini",
        instance_id=INSTANCE_ID,
        repository="vuejs/core",
        base_commit="a" * 40,
        dataset_revision="b" * 40,
        source_row_sha256="c" * 64,
        image=f"mswebench/vuejs_m_core@sha256:{DIGEST}",
        harness_image_tag="mswebench/vuejs_m_core:pr-8911",
        harness_revision=official_grader.MULTI_HARNESS_REVISION,
    )


def _semantic_summary() -> dict[str, object]:
    source, status = _source_and_status()
    return report_semantics.validate_multi_swe_report_semantics(
        instance_id=INSTANCE_ID,
        source_row=source,
        status=status,
        final_report=_final_report(True),
    ).to_public_dict()


def _unresolved_public_summary() -> dict[str, object]:
    summary = _semantic_summary()
    summary.update(
        {
            "expected_coverage_complete": False,
            "observed_expected_f2p_count": 0,
            "missing_expected_transition_count": 1,
            "observed_expected_transition_domain_sha256": "1" * 64,
            "computed_resolved": False,
            "official_final_report_resolved": False,
        }
    )
    return report_semantics.validate_public_semantics_summary(summary)


def _sealed_smoke_aggregate(path: Path) -> dict[str, object]:
    outcomes: list[dict[str, object]] = []
    for identity in range(6):
        benchmark_id = (
            "swebench_verified" if identity < 2 else "multi_swe_bench_mini"
        )
        for probe, resolved in (("GOLD", True), ("NOOP_BASELINE", False)):
            is_multi = benchmark_id != "swebench_verified"
            outcomes.append(
                {
                    "target_id": f"{benchmark_id}--instance-{identity}--{probe.lower()}",
                    "benchmark_id": benchmark_id,
                    "order_index": len(outcomes),
                    "probe": probe,
                    "resolved": resolved,
                    "applied_patch_sha256": "a" * 64,
                    "official_test_output_sha256": "b" * 64,
                    "official_test_status_sha256": "c" * 64,
                    "container_exit_status_sha256": "d" * 64 if is_multi else None,
                    "execution_contract_sha256": "e" * 64,
                    "execution_control_sha256": "f" * 64,
                    "submitted_patch_identity_sha256": "0" * 64,
                    "semantic_normalization": (
                        _semantic_summary()
                        if is_multi and resolved
                        else _unresolved_public_summary()
                        if is_multi
                        else None
                    ),
                    "patch_applied": True,
                    "tests_executed": True,
                    "digest_match": True,
                    "submitted_patch_identity": True,
                    "host_prepare_sh_access_count": 0,
                    "source_image_build_count": 0,
                    "api_calls": 0,
                    "container_exit_status_code": (
                        0 if is_multi and resolved else 1 if is_multi else None
                    ),
                    "container_exit_acceptance": (
                        "ZERO_EXIT"
                        if is_multi and resolved
                        else "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION"
                        if is_multi
                        else None
                    ),
                }
            )
    evidence_counts = {
        name: 12
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
    }
    evidence_counts["container_exit_status"] = 8
    body: dict[str, object] = {
        "schema": "trimem/verified-aggregate/1.0",
        "manifest": "grader-smoke",
        "status": "PASS",
        "outcomes": outcomes,
        "stream_totals": [],
        "approval_binding": {
            "approval_artifact_sha256": "a" * 64,
            "approved_request_sha256": "b" * 64,
            "approved_workflow_run_id": "1",
            "approved_workflow_run_attempt": "1",
            "freeze_sha256": "c" * 64,
            "git_head": "d" * 40,
            "phase": "GRADER_SMOKE",
        },
        "actual_accounting": {
            field: 12
            if field in {"grader_calls", "grader_containers", "official_grader_runs"}
            else 0
            for field in public_artifact.SMOKE_ACCOUNTING_FIELDS
        },
        "api_calls": 0,
        "container_exit_status_captured_count": 8,
        "container_exit_status_validated_count": 8,
        "digest_match_count": 12,
        "empty_patch_ids": [],
        "evidence_counts": evidence_counts,
        "expected_target_count": 12,
        "host_prepare_sh_access_count": 0,
        "image_lifecycle": {
            "actual": dict(public_artifact.SMOKE_IMAGE_LIFECYCLE_ACTUAL),
            "event_count": 14,
            "report_bytes": 1,
            "report_sha256": "e" * 64,
            "status": "PASS",
        },
        "attempted_cell_count": 12,
        "terminal_record_count": 12,
        "official_execution_count": 12,
        "complete_execution_evidence_count": 12,
        "adapter_normalized_count": 12,
        "authoritative_cell_count": 12,
        "unattempted_cell_count": 0,
        **{field: 0 for field in public_artifact.SMOKE_FAILURE_TAXONOMY_FIELDS},
        "observed_target_count": 12,
        "patch_applied_count": 12,
        "probe_counts": {"GOLD": 6, "NOOP_BASELINE": 6},
        "resolved_counts": {"GOLD": 6, "NOOP_BASELINE": 0},
        "resolved_container_zero_exit_count": 4,
        "source_image_build_count": 0,
        "submitted_patch_identity_count": 12,
        "tests_executed_count": 12,
        "unresolved_counts": {"GOLD": 0, "NOOP_BASELINE": 6},
    }
    sealed = {
        **body,
        "aggregate_sha256": hashlib.sha256(
            json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }
    path.write_text(json.dumps(sealed), encoding="utf-8")
    return sealed


def test_official_final_report_parser_routes_multi_through_shared_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target()
    report = _final_report(True)
    observed: dict[str, Any] = {}

    def shared(**kwargs: Any) -> bool:
        observed.update(kwargs)
        return False

    monkeypatch.setattr(
        official_grader, "validate_multi_swe_final_report_outcome", shared
    )

    assert official_grader.parse_official_report(target, report) is False
    assert observed == {"instance_id": INSTANCE_ID, "final_report": report}


def test_container_exit_revalidates_shared_summary_even_for_zero_exit() -> None:
    target = _target()
    patch = "diff --git a/a b/a\n"
    status = {
        "executed_image": target.image,
        "expected_image": target.image,
        "expected_tag": target.harness_image_tag,
        "image_id": f"sha256:{'e' * 64}",
        "run_command": official_grader.MULTI_FIX_PATCH_RUN_COMMAND,
        "schema": "trimem/multi-swe-container-exit-status/1.0",
        "status_code": 0,
        "submitted_patch_bytes": len(patch.encode()),
        "submitted_patch_sha256": hashlib.sha256(patch.encode()).hexdigest(),
    }
    raw = json.dumps(status, sort_keys=True, separators=(",", ":")).encode()
    summary = _semantic_summary()

    validated = official_grader.validate_multi_swe_container_exit_status(
        target,
        raw=raw,
        resolved=True,
        test_summary=summary,
        expected_patch=patch,
    )
    assert validated["acceptance"] == "ZERO_EXIT"

    forged = dict(summary)
    forged["report_valid_observed"] = False
    with pytest.raises(
        official_grader.OfficialGraderError,
        match="semantic summary failed",
    ):
        official_grader.validate_multi_swe_container_exit_status(
            target,
            raw=raw,
            resolved=True,
            test_summary=forged,
            expected_patch=patch,
        )


def test_matrix_recomputes_raw_multi_status_and_final_report_with_shared_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, status = _source_and_status()
    final_report = _final_report(True)
    summary = _semantic_summary()
    target = {
        "benchmark_id": "multi_swe_bench_mini",
        "instance_id": INSTANCE_ID,
    }
    calls: list[dict[str, Any]] = []
    production = report_semantics.validate_multi_swe_report_semantics

    def shared(**kwargs: Any):
        calls.append(kwargs)
        return production(**kwargs)

    monkeypatch.setattr(
        benchmark_matrix, "validate_multi_swe_report_semantics", shared
    )
    benchmark_matrix._validate_smoke_test_status(
        Path("cell.result.json"),
        target,
        status,
        summary,
        resolved=True,
        source_row=source,
        final_report=final_report,
    )
    assert calls == [
        {
            "instance_id": INSTANCE_ID,
            "source_row": source,
            "status": status,
            "final_report": final_report,
        }
    ]

    with pytest.raises(benchmark_matrix.MatrixError, match="two-stage semantics"):
        benchmark_matrix._validate_smoke_test_status(
            Path("cell.result.json"),
            target,
            status,
            summary,
            resolved=True,
            source_row=source,
            final_report=_final_report(False),
        )


def test_non_success_or_non_boolean_grade_result_cannot_claim_resolved() -> None:
    target = _target()
    base = GradeResult(
        task_id=target.target_id,
        resolved=True,
        exit_code=1,
        stdout="",
        stderr="",
        report={},
        grader_id="official-fixture",
        container_digest=target.image,
        official=True,
        wall_time_ms=1,
        container_started=True,
        status="adapter_contract_failed",
    )
    with pytest.raises(
        grader_smoke.BenchmarkExecutionError,
        match="non-success official grader result cannot claim resolved",
    ):
        grader_smoke._validated_grade_candidate(
            base, target={"target_id": target.target_id}
        )

    with pytest.raises(
        grader_smoke.BenchmarkExecutionError,
        match="non-boolean resolved state",
    ):
        grader_smoke._validated_grade_candidate(
            replace(base, resolved=1, status="success"),
            target={"target_id": target.target_id},
        )


def test_failure_envelope_rejects_compatibility_resolved_but_retains_official_true() -> None:
    target = _target()
    primary = {
        "stage": "adapter_semantic_normalization",
        "status": "adapter_contract_failed",
        "reason": "private semantic detail",
    }
    envelope = {field: None for field in official_grader.OFFICIAL_EVIDENCE_FIELDS}
    envelope.update(
        {
            "schema": official_grader.OFFICIAL_EVIDENCE_SCHEMA,
            "benchmark_id": target.benchmark_id,
            "dataset_revision": target.dataset_revision,
            "harness_revision": target.harness_revision,
            "source_row_sha256": target.source_row_sha256,
            "image_evidence": [],
            "invocation_argv": [],
            "harness_invocation_status": "NOT_REACHED",
            "report_invocation_argv": [],
            "report_invocation_status": "NOT_REACHED",
            "materialized_private_inputs": [],
            "adapter_status": "FAILURE",
            "adapter_failure_stage": primary["stage"],
            "adapter_primary_error": primary,
            "adapter_secondary_evidence_failures": [],
            "official_final_report_resolved": True,
            "adapter_normalized": False,
            "scientific_resolved": None,
        }
    )
    report = {
        "task_id": target.target_id,
        "status": primary["status"],
        "failure_stage": primary["stage"],
        "reason": primary["reason"],
        "_trimem": envelope,
    }
    grade = GradeResult(
        task_id=target.target_id,
        resolved=True,
        exit_code=1,
        stdout="",
        stderr="",
        report=report,
        grader_id="official-fixture",
        container_digest=target.image,
        official=True,
        wall_time_ms=1,
        container_started=False,
        status=primary["status"],
    )

    with pytest.raises(
        grader_smoke.BenchmarkExecutionError,
        match="failure envelope is inconsistent",
    ):
        grader_smoke.validate_adapter_evidence_envelope(
            grade, target=target.__dict__
        )

    validated = grader_smoke.validate_adapter_evidence_envelope(
        replace(grade, resolved=False), target=target.__dict__
    )
    assert validated["official_final_report_resolved"] is True
    assert validated["adapter_normalized"] is False
    assert validated["scientific_resolved"] is None


def test_public_projection_contains_no_raw_test_names_or_private_failure_reasons() -> None:
    summary = _semantic_summary()
    private_marker = "SECRET_TEST_NAME::private"
    assert private_marker not in json.dumps(summary, sort_keys=True)
    row = {
        "target_id": "multi_swe_bench_mini--vuejs__core-8911--gold",
        "benchmark_id": "multi_swe_bench_mini",
        "order_index": 0,
        "probe": "GOLD",
        "resolved": True,
        "applied_patch_sha256": "a" * 64,
        "official_test_output_sha256": "b" * 64,
        "official_test_status_sha256": "c" * 64,
        "container_exit_status_sha256": "d" * 64,
        "execution_contract_sha256": "e" * 64,
        "execution_control_sha256": "f" * 64,
        "submitted_patch_identity_sha256": "0" * 64,
        "semantic_normalization": summary,
        "patch_applied": True,
        "tests_executed": True,
        "digest_match": True,
        "submitted_patch_identity": True,
        "host_prepare_sh_access_count": 0,
        "source_image_build_count": 0,
        "api_calls": 0,
        "container_exit_status_code": 0,
        "container_exit_acceptance": "ZERO_EXIT",
    }
    projected = public_artifact._public_outcome_projection(
        [row], manifest="grader-smoke"
    )
    assert private_marker not in json.dumps(projected, sort_keys=True)

    with pytest.raises(public_artifact.PublicArtifactError, match="forbidden keys"):
        public_artifact._reject_forbidden(
            {"actual_memory_metrics": {"failure_reason": "private path/test name"}}
        )
    with pytest.raises(public_artifact.PublicArtifactError, match="forbidden keys"):
        public_artifact._reject_forbidden(
            {"semantic_normalization": {"p2p_tests": ["private test name"]}}
        )
    public_artifact._reject_forbidden({"report_invalidity_reason": "NONE"})

    lifecycle = {
        "actual": dict(public_artifact.SMOKE_IMAGE_LIFECYCLE_ACTUAL),
        "event_count": 14,
        "report_bytes": 1,
        "report_sha256": "a" * 64,
        "status": "PASS",
    }
    assert public_artifact._valid_smoke_image_lifecycle(lifecycle)
    assert not public_artifact._valid_smoke_image_lifecycle(
        {**lifecycle, "private_failure_reason": "private path/test name"}
    )


@pytest.mark.parametrize("channel", ["stream_totals", "benchmark_roles", "image_lifecycle"])
def test_public_smoke_package_rejects_every_private_side_channel(
    tmp_path: Path, channel: str
) -> None:
    aggregate_path = tmp_path / "aggregate.json"
    output_path = tmp_path / "public.json"
    sealed = _sealed_smoke_aggregate(aggregate_path)
    public_artifact.package(aggregate_path, output_path)
    assert "SECRET_TEST_NAME" not in output_path.read_text(encoding="utf-8")

    body = {key: value for key, value in sealed.items() if key != "aggregate_sha256"}
    if channel == "stream_totals":
        body[channel] = [{"note": "PRIVATE_FAILURE_REASON::test_hidden"}]
    elif channel == "benchmark_roles":
        body[channel] = [{"note": "PRIVATE_FAILURE_REASON::test_hidden"}]
    else:
        body[channel] = {
            **body[channel],  # type: ignore[arg-type]
            "note": "PRIVATE_FAILURE_REASON::test_hidden",
        }
    body["aggregate_sha256"] = hashlib.sha256(
        json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    aggregate_path.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(public_artifact.PublicArtifactError):
        public_artifact.package(aggregate_path, output_path)
