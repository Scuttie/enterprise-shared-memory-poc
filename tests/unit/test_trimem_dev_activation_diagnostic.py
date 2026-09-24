from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_dev_activation_diagnostic as diagnostic  # noqa: E402


SOURCE_BANK_SHA256 = "a" * 64


def _contracts():
    manifest_path = ROOT / diagnostic.MATRIX_PATH
    policy_path = ROOT / diagnostic.POLICY_PATH
    development_path = ROOT / "configs/trimem_v1/development_manifest.json"
    manifest = diagnostic.strict_json_load(manifest_path)
    policy = diagnostic.strict_json_load(policy_path)
    development = diagnostic.strict_json_load(development_path)
    return manifest, policy, development, development_path


def _decision(
    target_id: str,
    *,
    attempt: str,
    safe_candidates: int,
    reason: str,
) -> dict:
    no_generated_candidate = reason in {
        "NO_CANDIDATE_GENERATED",
        "NO_COMPLEMENTARY_CANDIDATE",
        "NO_SEED_MATCH",
    }
    before = 0 if no_generated_candidate else max(1, safe_candidates)
    return {
        "recall_attempt_id": attempt,
        "target_id": target_id,
        "subtask_id": "S1",
        "bank_type": "ORG_SEMANTIC",
        "candidate_count_before_filter": before,
        "candidate_count_after_filter": safe_candidates,
        "top_candidate_id": "memory-1" if before else None,
        "top_embedding_score": 0.4 if before else None,
        "top_ppr_score": 0.2 if before else None,
        "threshold": {"min_confidence": 0.25, "min_margin": 0.0},
        "Q_USE": None,
        "Q_ABSTAIN": None,
        "router_policy": "N/A",
        "final_reason_code": reason,
    }


def _injection() -> dict:
    return {
        "memory_id": "memory-1",
        "source_task_id": "source-task-1",
        "source_repository": "example/repo",
        "target_repository": "example/repo",
        "bank_type": "ORG_SEMANTIC",
        "subtask_id": "S1",
        "repo_overlap": True,
        "active_subtask_projection_sha256": "c" * 64,
        "active_subtask_declared_file_overlap": ["src/example.py"],
        "active_subtask_declared_symbol_overlap": ["Example"],
        "active_subtask_declared_api_overlap": [],
        "active_subtask_declared_error_overlap": [],
        "pre_execution_target_issue_overlap": {
            "errors_overlap": 0,
            "apis_overlap": 0,
            "symbols_overlap": 1,
            "paths_overlap": 1,
            "tokens_overlap": 1,
        },
    }


def _results(
    *,
    resolved_by_arm: dict[str, set[int]] | None = None,
    c1_inject: bool = False,
    c1_injected_targets: set[int] | None = None,
    c2_covered: int = 12,
) -> tuple[dict, dict, dict]:
    manifest, policy, _, _ = _contracts()
    resolved_by_arm = resolved_by_arm or {arm: set() for arm in diagnostic.ARMS}
    cells = []
    for expected in diagnostic.expected_cells(manifest):
        arm = expected["arm_id"]
        target_id = expected["target_id"]
        target_order = expected["target_order_index"]
        decisions = []
        injections = []
        if arm == "C1":
            inject_current_target = c1_inject or (
                c1_injected_targets is not None
                and target_order in c1_injected_targets
            )
            if inject_current_target:
                reason = "INJECTED"
                injections = [_injection()]
            else:
                reason = "BELOW_CONFIDENCE_THRESHOLD"
            decisions = [
                _decision(
                    target_id,
                    attempt=f"{arm}-{target_order}",
                    safe_candidates=1,
                    reason=reason,
                )
            ]
        elif arm == "C2":
            covered = target_order < c2_covered
            decisions = [
                _decision(
                    target_id,
                    attempt=f"{arm}-{target_order}",
                    safe_candidates=int(covered),
                    reason="INJECTED" if covered else "NO_CANDIDATE_GENERATED",
                )
            ]
            injections = [_injection()] if covered else []
        cells.append(
            {
                "schema": "trimem/dev-activation-cell/1.0",
                "diagnostic_id": manifest["diagnostic_id"],
                **expected,
                "source_bank_manifest_sha256": None if arm == "C0" else SOURCE_BANK_SHA256,
                "official_grader_evidence_sha256": "b" * 64,
                "terminal": True,
                "terminal_reason_code": "PER_SUBTASK_STEP_CAP_REACHED",
                "official_grader_resolved": target_order in resolved_by_arm.get(arm, set()),
                "diagnostic_resolved": target_order in resolved_by_arm.get(arm, set()),
                "patch_class": "CANONICAL_NOOP",
                "model_failure_code": None,
                "extraction_status": "SUCCESS",
                "extraction_failure_code": None,
                "injections": injections,
                "recall_decisions": decisions,
                "adaptive_horizon": {
                    "extensions_granted": 0,
                    "progress_event_ids": [],
                    "per_subtask_extensions": {"S1": 0},
                    "agent_completed_count": 0,
                    "per_subtask_step_cap_reached_count": 1,
                },
                "accounting": {
                    "decomposition_calls": 1,
                    "solve_calls": 8,
                    "extraction_calls": 1,
                    "input_tokens": 100,
                    "cached_input_tokens": 0,
                    "output_tokens": 50,
                    "paid_model_calls": 10,
                    "model_wall_time_ms": 10,
                    "tool_wall_time_ms": 20,
                    "grader_wall_time_ms": 30,
                    "grader_calls": 1,
                    "grader_containers": 1,
                    "official_grader_runs": 1,
                    "task_wall_time_ms": 60,
                    "total_usd": "0.01",
                },
            }
        )
    return {
        "schema": "trimem/dev-activation-results/1.0",
        "diagnostic_id": manifest["diagnostic_id"],
        "cells": cells,
    }, manifest, policy


def test_committed_manifest_is_exact_frozen_three_by_twelve_projection() -> None:
    manifest, policy, development, development_path = _contracts()
    cells = diagnostic.validate_contract_documents(
        manifest,
        policy,
        development,
        development_raw_sha256=diagnostic.file_sha256(development_path),
    )
    assert [row["arm_id"] for row in manifest["arms"]] == ["C0", "C1", "C2"]
    assert len(cells) == 36
    assert [row["cell_index"] for row in cells] == list(range(36))
    assert diagnostic.canonical_sha256(cells) == manifest["matrix"]["cell_sequence_sha256"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "verdict_precedence",
            [
                "RETRIEVAL_BANK_COVERAGE_INSUFFICIENT",
                "CURRENT_ROUTER_ACTIVATED_POSITIVE",
                "MEMORY_CONTENT_UPPER_BOUND_POSITIVE_ROUTER_BLOCKED",
                "FORCED_MEMORY_NEGATIVE_TRANSFER",
                "FORCED_MEMORY_MIXED_ZERO_NET",
                "FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED",
            ],
            "primary verdict precedence drift",
        ),
        ("secondary_verdict_labels", [], "secondary verdict label drift"),
    ],
)
def test_primary_and_secondary_verdict_policy_is_fail_closed(
    field: str, value: list[str], reason: str
) -> None:
    manifest, policy, development, development_path = _contracts()
    policy[field] = value
    with pytest.raises(diagnostic.DiagnosticContractError, match=reason):
        diagnostic.validate_contract_documents(
            manifest,
            policy,
            development,
            development_raw_sha256=diagnostic.file_sha256(development_path),
        )


def test_preflight_accepts_exact_frozen_target_disjoint_source_bank() -> None:
    manifest, policy, cells, source_hash = diagnostic.load_and_validate_contract(
        require_tracked=False
    )
    assert manifest["diagnostic_id"] == policy["diagnostic_id"]
    assert len(cells) == 36
    assert source_hash == policy["source_bank"]["manifest_raw_sha256"]


def test_historical_179_row_projection_is_exact_and_never_imputes_identity() -> None:
    recoverability_path = ROOT / diagnostic.HISTORICAL_RECOVERABILITY_PATH
    projection_path = ROOT / diagnostic.HISTORICAL_PROJECTION_PATH
    recoverability = diagnostic.strict_json_load(recoverability_path)
    projection = diagnostic.strict_json_load(projection_path)
    diagnostic.validate_historical_abstention_projection(
        projection,
        recoverability,
        recoverability_raw_sha256=diagnostic.file_sha256(recoverability_path),
    )
    rows = projection["rows"]
    assert len(rows) == 179
    assert len({row["projection_row_id"] for row in rows}) == 179
    assert sum(row["aggregate_stream"] == "M0" for row in rows) == 14
    for row in rows:
        assert row["recall_attempt_id"] == diagnostic.HISTORICAL_UNKNOWN
        assert row["target_id"] == diagnostic.HISTORICAL_UNKNOWN
        assert row["subtask_id"] == diagnostic.HISTORICAL_UNKNOWN
    non_controls = [row for row in rows if row["aggregate_stream"] != "M0"]
    assert len(non_controls) == 165
    assert all(
        all(row[field] == diagnostic.HISTORICAL_UNKNOWN for field in diagnostic.HISTORICAL_DECISION_FIELDS)
        for row in non_controls
    )


def _source_bank(source_task_id: str = "historical-task") -> dict:
    record = {
        "memory_id": "historical-memory",
        "source_task_id": source_task_id,
        "source_dataset_id": "public-dataset@revision",
        "source_dataset_revision": "a" * 40,
        "source_row_sha256": "a" * 64,
        "source_repository": "example/repository",
        "source_base_commit": "a" * 40,
        "source_commit": "b" * 40,
        "source_timestamp": "2025-01-02T03:04:05Z",
        "bank_type": "ORG_SEMANTIC",
        "changed_paths": ["src/example.py"],
        "symbols": ["example"],
        "apis": [],
        "errors": [],
        "verified": True,
        "reviewed": True,
        "source_outcome": "passed",
        "source_fix_verification_signal": "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT",
        "verification_evidence_sha256": "c" * 64,
        "chronology_and_version_evidence_sha256": "c" * 64,
        "provenance_sha256": "d" * 64,
        "payload_sha256": "e" * 64,
        "payload_path": f"dev_activation_source_bank_payloads/{'e' * 64}.json",
        "permission_scope": "PUBLIC_READ",
        "tenant_scope": "BENCHMARK_ISOLATED",
        "repository_scope": "EXACT_SOURCE_AND_TARGET_REPOSITORY",
        "version_scope": "EXACT_SOURCE_COMMIT",
        "path_scope": "**",
        "quarantined": False,
        "target_derived": False,
    }
    return {
        "schema": "trimem/dev-activation-source-bank/1.0",
        "status": "FROZEN_VERIFIED_TARGET_DISJOINT",
        "read_only": True,
        "result_blind_construction": True,
        "development_target_set_sha256": "f" * 64,
        "target_overlap_count": 0,
        "record_count": 1,
        "records_sha256": diagnostic.canonical_sha256([record]),
        "records": [record],
    }


def test_source_bank_validator_rejects_target_identity_and_target_fields() -> None:
    bank = _source_bank()
    records = diagnostic.validate_source_bank_document(
        bank,
        development_target_set_sha256="f" * 64,
        forbidden_task_ids={"current-target"},
    )
    assert [row["source_task_id"] for row in records] == ["historical-task"]

    overlapping = _source_bank("current-target")
    with pytest.raises(diagnostic.DiagnosticContractError, match="target-derived"):
        diagnostic.validate_source_bank_document(
            overlapping,
            development_target_set_sha256="f" * 64,
            forbidden_task_ids={"current-target"},
        )

    contaminated = _source_bank()
    contaminated["target_gold_patch"] = "forbidden"
    with pytest.raises(diagnostic.DiagnosticContractError, match="forbidden target fields"):
        diagnostic.validate_source_bank_document(
            contaminated,
            development_target_set_sha256="f" * 64,
            forbidden_task_ids=set(),
        )


def test_payload_paths_are_manifest_relative_and_symlinks_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "bank" / "manifest.json"
    payload = manifest.parent / "payloads" / "payload.json"
    payload.parent.mkdir(parents=True)
    payload.write_text("{}", encoding="utf-8")
    manifest.write_text("{}", encoding="utf-8")
    assert diagnostic._manifest_relative_payload_path(  # noqa: SLF001
        manifest, "payloads/payload.json"
    ) == payload.resolve()

    with pytest.raises(diagnostic.DiagnosticContractError, match="escapes"):
        diagnostic._manifest_relative_payload_path(  # noqa: SLF001
            manifest, "../payload.json"
        )

    original_is_symlink = Path.is_symlink

    def pretend_payload_directory_is_symlink(path: Path) -> bool:
        return path == payload.parent or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", pretend_payload_directory_is_symlink)
    with pytest.raises(diagnostic.DiagnosticContractError, match="symlink"):
        diagnostic._manifest_relative_payload_path(  # noqa: SLF001
            manifest, "payloads/payload.json"
        )


def test_payload_loader_hashes_exact_manifest_relative_bytes(tmp_path: Path) -> None:
    manifest = tmp_path / "configs" / "bank" / "manifest.json"
    payload = manifest.parent / "payloads" / "memory.json"
    payload.parent.mkdir(parents=True)
    raw = b'{"schema":"source-payload"}'
    payload.write_bytes(raw)
    manifest.write_text("{}", encoding="utf-8")
    record = {
        "memory_id": "memory",
        "payload_path": "payloads/memory.json",
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
    }
    observed = diagnostic._load_source_bank_payloads(  # noqa: SLF001
        tmp_path,
        manifest,
        [record],
        require_tracked=False,
    )
    assert observed == {"payloads/memory.json": raw}

    payload.write_bytes(raw + b"\n")
    with pytest.raises(diagnostic.DiagnosticContractError, match="hash drift"):
        diagnostic._load_source_bank_payloads(  # noqa: SLF001
            tmp_path,
            manifest,
            [record],
            require_tracked=False,
        )


def test_target_drift_from_development_manifest_is_rejected() -> None:
    manifest, policy, development, development_path = _contracts()
    drifted = deepcopy(manifest)
    drifted["targets"][0]["target_id"] = "changed"
    with pytest.raises(diagnostic.DiagnosticContractError, match="targets/order drift"):
        diagnostic.validate_contract_documents(
            drifted,
            policy,
            development,
            development_raw_sha256=diagnostic.file_sha256(development_path),
        )


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown"])
def test_aggregate_rejects_incomplete_duplicate_or_unknown_cells(mutation: str) -> None:
    result, manifest, policy = _results()
    if mutation == "missing":
        result["cells"].pop()
    elif mutation == "duplicate":
        result["cells"][-1] = deepcopy(result["cells"][0])
    else:
        result["cells"][-1]["cell_id"] = "C2--unknown-target"
    with pytest.raises(diagnostic.DiagnosticContractError, match="cell matrix incomplete"):
        diagnostic.aggregate_results(
            result,
            manifest,
            policy,
            source_bank_sha256=SOURCE_BANK_SHA256,
        )


def test_aggregate_requires_official_boolean_outcome_and_known_reason() -> None:
    result, manifest, policy = _results()
    result["cells"][0]["official_grader_resolved"] = None
    with pytest.raises(diagnostic.DiagnosticContractError, match="result is unknown"):
        diagnostic.aggregate_results(
            result, manifest, policy, source_bank_sha256=SOURCE_BANK_SHA256
        )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("input", "input-token budget"),
        ("output", "output-token budget"),
        ("paid_calls", "paid model calls"),
        ("extraction", "model-call budget"),
        ("usd", "total_usd cap"),
    ],
)
def test_cell_and_aggregate_accounting_caps_fail_closed(
    mutation: str,
    reason: str,
) -> None:
    result, manifest, policy = _results()
    if mutation == "input":
        result["cells"][0]["accounting"]["input_tokens"] = 500_001
    elif mutation == "output":
        result["cells"][0]["accounting"]["output_tokens"] = 65_537
    elif mutation == "paid_calls":
        result["cells"][0]["accounting"]["paid_model_calls"] = 11
    elif mutation == "extraction":
        result["cells"][0]["accounting"]["extraction_calls"] = 2
    else:
        for cell in result["cells"]:
            cell["accounting"]["total_usd"] = "0.70"
    with pytest.raises(diagnostic.DiagnosticContractError, match=reason):
        diagnostic.aggregate_results(
            result,
            manifest,
            policy,
            source_bank_sha256=SOURCE_BANK_SHA256,
        )


@pytest.mark.parametrize(
    ("resolved", "c1_inject", "expected"),
    [
        (
            {"C0": set(), "C1": set(), "C2": {0}},
            False,
            "MEMORY_CONTENT_UPPER_BOUND_POSITIVE_ROUTER_BLOCKED",
        ),
        (
            {"C0": set(), "C1": {0}, "C2": {0}},
            True,
            "CURRENT_ROUTER_ACTIVATED_POSITIVE",
        ),
        (
            {"C0": {0}, "C1": set(), "C2": set()},
            False,
            "FORCED_MEMORY_NEGATIVE_TRANSFER",
        ),
        (
            {"C0": {0}, "C1": set(), "C2": {1}},
            False,
            "FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED",
        ),
        (
            {"C0": set(), "C1": set(), "C2": set()},
            False,
            "FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED",
        ),
    ],
)
def test_frozen_positive_negative_mixed_and_no_lift_verdicts(
    resolved: dict[str, set[int]], c1_inject: bool, expected: str
) -> None:
    result, manifest, policy = _results(
        resolved_by_arm=resolved,
        c1_inject=c1_inject,
    )
    aggregate = diagnostic.aggregate_results(
        result, manifest, policy, source_bank_sha256=SOURCE_BANK_SHA256
    )
    assert aggregate["verdict"] == expected
    assert aggregate["status"] == "COMPLETE_36_OF_36_OFFICIAL_CELLS"
    assert all(
        "diagnostic_solved" in row
        and "diagnostic_pass_at_1" in row
        and "official_solved" in row
        and "official_pass_at_1" in row
        and "solved" not in row
        and "pass_at_1" not in row
        for row in aggregate["arm_summary"]
    )
    if resolved == {"C0": {0}, "C1": set(), "C2": {1}}:
        assert aggregate["secondary_labels"] == ["FORCED_MEMORY_MIXED_ZERO_NET"]
    else:
        assert "FORCED_MEMORY_MIXED_ZERO_NET" not in aggregate["secondary_labels"]


def test_current_router_positive_requires_injection_aligned_target_flip() -> None:
    result, manifest, policy = _results(
        resolved_by_arm={"C0": set(), "C1": {1}, "C2": {1}},
        c1_injected_targets={0},
    )
    aggregate = diagnostic.aggregate_results(
        result, manifest, policy, source_bank_sha256=SOURCE_BANK_SHA256
    )
    assert aggregate["verdict"] == (
        "MEMORY_CONTENT_UPPER_BOUND_POSITIVE_ROUTER_BLOCKED"
    )
    assert aggregate["verdict_basis"][
        "c1_injection_aligned_positive_target_ids"
    ] == []


def test_coverage_insufficiency_has_verdict_precedence() -> None:
    result, manifest, policy = _results(
        resolved_by_arm={"C0": set(), "C1": set(), "C2": {0}},
        c2_covered=11,
    )
    aggregate = diagnostic.aggregate_results(
        result, manifest, policy, source_bank_sha256=SOURCE_BANK_SHA256
    )
    assert aggregate["verdict"] == "RETRIEVAL_BANK_COVERAGE_INSUFFICIENT"
    assert aggregate["secondary_labels"] == [
        "OBSERVED_C2_POSITIVE_UNDER_INSUFFICIENT_COVERAGE"
    ]


def test_retrieval_reason_codes_map_to_frozen_abstention_taxonomy() -> None:
    target = "target"
    decisions = [
        _decision(
            target,
            attempt="one",
            safe_candidates=1,
            reason="BELOW_CONFIDENCE_THRESHOLD",
        ),
        _decision(
            target,
            attempt="two",
            safe_candidates=0,
            reason="EMPTY_EXECUTION_VIEW_REJECTION",
        ),
        _decision(
            target,
            attempt="three",
            safe_candidates=1,
            reason="TASK_INJECTION_LIMIT_REJECTION",
        ),
    ]
    histogram = diagnostic.abstention_histogram(decisions)
    assert histogram["below_semantic_or_ppr_threshold"] == 1
    assert histogram["safe_gate_rejected"] == 1
    assert histogram["context_or_injection_budget_rejection"] == 1


def test_selection_only_retrieval_event_cannot_be_a_final_decision() -> None:
    decision = _decision(
        "target",
        attempt="selection-only",
        safe_candidates=1,
        reason="CANDIDATE_SELECTED",
    )
    with pytest.raises(diagnostic.DiagnosticContractError, match="unknown recall"):
        diagnostic.validate_recall_decision(decision, "target")
