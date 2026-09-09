"""Credential-free contract and aggregation for the DEV activation diagnostic.

This module deliberately does not execute a model, mutate a memory bank, or run
an official grader.  It validates the frozen C0/C1/C2 matrix and the dedicated
source-bank boundary, emits the deterministic execution plan, and aggregates a
complete set of externally produced official cell records fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from trimem_dev_activation_source_bank import (
    CHRONOLOGY_PATH as SOURCE_BANK_CHRONOLOGY_PATH,
    PLAN_PATH as SOURCE_BANK_PLAN_PATH,
    SourceBankError,
    validate_source_bank as validate_compiled_source_bank,
)


ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = Path("configs/trimem_v1/dev_activation_manifest.json")
POLICY_PATH = Path("configs/trimem_v1/dev_activation_policy.json")
HISTORICAL_RECOVERABILITY_PATH = Path(
    "artifacts/trimem_v1/dev_activation_diagnostic/"
    "exec_022_abstention_recoverability.json"
)
HISTORICAL_PROJECTION_PATH = Path(
    "artifacts/trimem_v1/dev_activation_diagnostic/"
    "exec_022_abstention_projection.json"
)
ARMS = ("C0", "C1", "C2")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TERMINAL_REASONS = {
    "AGENT_COMPLETED",
    "PER_SUBTASK_STEP_CAP_REACHED",
    "MODEL_FAILURE_CONTINUED_TO_GRADER",
    "CONTAINED_RUNTIME_FAILURE_CONTINUED_TO_GRADER",
    "EXTRACTION_FAILURE_AFTER_OFFICIAL_GRADE",
}
PATCH_CLASSES = {"MODEL_PATCH", "PARTIAL_PATCH", "CANONICAL_NOOP"}
ABSTENTION_BUCKETS = (
    "no_candidate_generated",
    "safe_gate_rejected",
    "below_semantic_or_ppr_threshold",
    "router_selected_abstain_with_valid_candidate",
    "context_or_injection_budget_rejection",
    "other_explicit_reason",
)
REASON_TO_BUCKET = {
    "NO_CANDIDATE_GENERATED": "no_candidate_generated",
    "PERMISSION_GATE_REJECTED": "safe_gate_rejected",
    "TENANT_GATE_REJECTED": "safe_gate_rejected",
    "REPOSITORY_GATE_REJECTED": "safe_gate_rejected",
    "PATH_GATE_REJECTED": "safe_gate_rejected",
    "VERSION_GATE_REJECTED": "safe_gate_rejected",
    "PROVENANCE_GATE_REJECTED": "safe_gate_rejected",
    "LEAKAGE_GATE_REJECTED": "safe_gate_rejected",
    "QUARANTINE_GATE_REJECTED": "safe_gate_rejected",
    "NO_SAFE_CANDIDATE": "safe_gate_rejected",
    "NO_COMPLEMENTARY_CANDIDATE": "no_candidate_generated",
    "NO_SEED_MATCH": "no_candidate_generated",
    "BELOW_CONFIDENCE_THRESHOLD": "below_semantic_or_ppr_threshold",
    "BELOW_MARGIN_THRESHOLD": "below_semantic_or_ppr_threshold",
    "PER_NODE_INJECTION_LIMIT_REJECTION": "context_or_injection_budget_rejection",
    "SUBTASK_INJECTION_LIMIT_REJECTION": "context_or_injection_budget_rejection",
    "ALREADY_INJECTED_REJECTION": "context_or_injection_budget_rejection",
    "TASK_INJECTION_LIMIT_REJECTION": "context_or_injection_budget_rejection",
    "CONTEXT_INJECTION_BUDGET_REJECTION": "context_or_injection_budget_rejection",
    "EMPTY_EXECUTION_VIEW_REJECTION": "safe_gate_rejected",
    "CANONICAL_GATE_REJECTED": "safe_gate_rejected",
    "FORCED_SAFE_TOP1_LIMIT_REJECTION": "context_or_injection_budget_rejection",
}
DECISION_REASONS = set(REASON_TO_BUCKET) | {"INJECTED"}
FORBIDDEN_SOURCE_KEYS = {
    "gold_patch",
    "target_gold",
    "target_gold_patch",
    "target_test",
    "target_tests",
    "test_patch",
    "fail_to_pass",
    "pass_to_pass",
    "target_outcome",
    "target_resolved",
}
SOURCE_RECORD_FIELDS = {
    "memory_id",
    "source_task_id",
    "source_dataset_id",
    "source_dataset_revision",
    "source_row_sha256",
    "source_repository",
    "source_base_commit",
    "source_commit",
    "source_timestamp",
    "bank_type",
    "changed_paths",
    "symbols",
    "apis",
    "errors",
    "verified",
    "reviewed",
    "source_outcome",
    "source_fix_verification_signal",
    "verification_evidence_sha256",
    "chronology_and_version_evidence_sha256",
    "provenance_sha256",
    "payload_sha256",
    "payload_path",
    "permission_scope",
    "tenant_scope",
    "repository_scope",
    "version_scope",
    "path_scope",
    "quarantined",
    "target_derived",
}
HISTORICAL_DECISION_FIELDS = (
    "recall_attempt_id",
    "target_id",
    "subtask_id",
    "bank_type",
    "candidate_count_before_filter",
    "candidate_count_after_filter",
    "top_candidate_id",
    "top_embedding_score",
    "top_ppr_score",
    "threshold",
    "Q_USE",
    "Q_ABSTAIN",
    "router_policy",
    "final_reason_code",
)
HISTORICAL_ROW_FIELDS = {
    "projection_row_id",
    "aggregate_stream",
    "projection_semantics",
    *HISTORICAL_DECISION_FIELDS,
}
HISTORICAL_UNKNOWN = "UNKNOWN_NOT_RECORDED_EXEC_022"


class DiagnosticContractError(ValueError):
    """A fail-closed diagnostic contract violation."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DiagnosticContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise DiagnosticContractError(f"non-finite JSON number: {value}")


def strict_json_load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiagnosticContractError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DiagnosticContractError(f"JSON root must be an object: {path}")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_historical_abstention_projection(
    recoverability: Mapping[str, Any],
    *,
    recoverability_raw_sha256: str,
) -> dict[str, Any]:
    """Expand only retained aggregate counts into explicitly non-identifying rows.

    The expansion is a reporting projection, not reconstructed decision evidence.
    Except for the retained fact that the fourteen M0 rows were intentional
    no-memory controls, row-level target, subtask, candidate, score, and reason
    identities remain unknown rather than being guessed from stream order.
    """

    if recoverability.get("schema") != (
        "trimem/dev-activation-exec-022-abstention-recoverability/1.0"
    ):
        raise DiagnosticContractError("historical recoverability schema drift")
    if recoverability.get("status") != "PARTIAL_AGGREGATE_ONLY_FAIL_CLOSED":
        raise DiagnosticContractError("historical recoverability status drift")
    if not SHA256.fullmatch(recoverability_raw_sha256):
        raise DiagnosticContractError("historical recoverability raw hash is malformed")
    aggregate = recoverability.get("aggregate_counts")
    streams = aggregate.get("streams") if isinstance(aggregate, Mapping) else None
    if not isinstance(streams, list):
        raise DiagnosticContractError("historical abstention stream counts are missing")
    expected_stream_counts = (
        ("M0", 14),
        ("M1", 12),
        ("M2-baseline", 39),
        ("M2-precision", 39),
        ("M2-recall", 36),
        ("M2-balanced", 39),
    )
    observed_stream_counts: list[tuple[str, int]] = []
    for stream in streams:
        if not isinstance(stream, Mapping):
            raise DiagnosticContractError("historical abstention stream row is malformed")
        arm = stream.get("arm")
        count = stream.get("abstention_decisions")
        if not isinstance(arm, str) or type(count) is not int:
            raise DiagnosticContractError("historical abstention stream identity/count drift")
        observed_stream_counts.append((arm, count))
    if tuple(observed_stream_counts) != expected_stream_counts:
        raise DiagnosticContractError("historical abstention aggregate stream drift")
    if aggregate.get("abstention_decisions") != 179:
        raise DiagnosticContractError("historical abstention total drift")

    rows: list[dict[str, Any]] = []
    for stream, count in expected_stream_counts:
        for ordinal in range(1, count + 1):
            unknowns = {field: HISTORICAL_UNKNOWN for field in HISTORICAL_DECISION_FIELDS}
            row: dict[str, Any] = {
                "projection_row_id": f"EXEC_022_{stream.upper()}_{ordinal:03d}",
                "aggregate_stream": stream,
                "projection_semantics": (
                    "AGGREGATE_COUNT_EXPANSION_NOT_ORIGINAL_DECISION_IDENTITY"
                ),
                **unknowns,
            }
            if stream == "M0":
                row.update(
                    {
                        "bank_type": "NO_MEMORY_CONTROL",
                        "Q_USE": "NOT_APPLICABLE_RETRIEVAL_DQN_ABSENT",
                        "Q_ABSTAIN": "NOT_APPLICABLE_RETRIEVAL_DQN_ABSENT",
                        "router_policy": "NOT_APPLICABLE_M0_NO_MEMORY_CONTROL",
                        "final_reason_code": "INTENTIONAL_M0_NO_MEMORY_CONTROL",
                    }
                )
            rows.append(row)
    return {
        "schema": "trimem/dev-activation-exec-022-abstention-projection/1.0",
        "status": "HISTORICAL_179_ROWS_PROJECTED_WITH_UNKNOWNS_FAIL_CLOSED",
        "source": {
            "path": HISTORICAL_RECOVERABILITY_PATH.as_posix(),
            "raw_sha256": recoverability_raw_sha256,
            "evidence_granularity": "AGGREGATE_ONLY",
        },
        "approval_binding": dict(recoverability.get("approval_binding", {})),
        "row_count": len(rows),
        "known_m0_control_row_count": 14,
        "unknown_historical_decision_row_count": 165,
        "missing_field_value": HISTORICAL_UNKNOWN,
        "row_identity_warning": (
            "projection_row_id is synthetic aggregate expansion identity; it is "
            "not a recovered recall_attempt_id, target_id, or subtask_id"
        ),
        "rows_sha256": canonical_sha256(rows),
        "rows": rows,
        "model_api_calls_for_projection": 0,
        "paid_model_calls_for_projection": 0,
        "official_grader_runs_for_projection": 0,
        "total_usd_for_projection": "0.000000000000",
    }


def validate_historical_abstention_projection(
    projection: Mapping[str, Any],
    recoverability: Mapping[str, Any],
    *,
    recoverability_raw_sha256: str,
) -> None:
    expected = build_historical_abstention_projection(
        recoverability,
        recoverability_raw_sha256=recoverability_raw_sha256,
    )
    if canonical_bytes(projection) != canonical_bytes(expected):
        raise DiagnosticContractError(
            "historical abstention projection differs from retained aggregate evidence"
        )
    rows = projection.get("rows")
    if not isinstance(rows, list) or len(rows) != 179:
        raise DiagnosticContractError("historical abstention projection row-count drift")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != HISTORICAL_ROW_FIELDS:
            raise DiagnosticContractError(
                f"historical abstention projection field-set drift at {index}"
            )
        if row["aggregate_stream"] != "M0" and any(
            row[field] != HISTORICAL_UNKNOWN
            for field in HISTORICAL_DECISION_FIELDS
        ):
            raise DiagnosticContractError(
                f"historical row-level decision value was imputed at {index}"
            )


def _repo_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise DiagnosticContractError("repository-relative path is missing")
    path = (root / relative).resolve()
    resolved_root = root.resolve()
    if path != resolved_root and resolved_root not in path.parents:
        raise DiagnosticContractError(f"path escapes repository: {relative}")
    return path


def _require_tracked(root: Path, relative: str) -> None:
    result = subprocess.run(
        _hermetic_git_command(
            ["ls-files", "--error-unmatch", "--", relative]
        ),
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env=_hermetic_git_environment(),
    )
    if result.returncode != 0:
        raise DiagnosticContractError(f"required contract is not git-tracked: {relative}")


def _hermetic_git_environment() -> dict[str, str]:
    """Return the minimum non-secret environment needed by local Git reads."""

    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"}
    environment = {
        key: value for key, value in os.environ.items() if key.upper() in allowed
    }
    environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "LANG": "C",
        }
    )
    return environment


def _hermetic_git_command(arguments: Sequence[str]) -> list[str]:
    return [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.hooksPath={os.devnull}",
        *arguments,
    ]


def expected_cells(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets = manifest.get("targets")
    arms = manifest.get("arms")
    if not isinstance(targets, list) or not isinstance(arms, list):
        raise DiagnosticContractError("diagnostic arms/targets are missing")
    cells: list[dict[str, Any]] = []
    for arm_index, arm in enumerate(arms):
        if not isinstance(arm, dict):
            raise DiagnosticContractError("diagnostic arm row is not an object")
        for target in targets:
            if not isinstance(target, dict):
                raise DiagnosticContractError("diagnostic target row is not an object")
            cell_index = arm_index * len(targets) + target["order_index"]
            cells.append(
                {
                    "arm_id": arm["arm_id"],
                    "cell_id": f"{arm['arm_id']}--{target['target_id']}",
                    "cell_index": cell_index,
                    "target_id": target["target_id"],
                    "target_order_index": target["order_index"],
                }
            )
    return cells


def validate_contract_documents(
    manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
    development: Mapping[str, Any],
    *,
    development_raw_sha256: str,
) -> list[dict[str, Any]]:
    if manifest.get("schema") != "trimem/dev-activation-manifest/1.0":
        raise DiagnosticContractError("diagnostic manifest schema drift")
    if manifest.get("status") != "FROZEN_PRE_EXEC_DIAGNOSTIC_CONTRACT":
        raise DiagnosticContractError("diagnostic manifest is not frozen")
    if manifest.get("execution_authorized") is not False:
        raise DiagnosticContractError("diagnostic manifest must not authorize execution")
    binding = manifest.get("development_manifest")
    if not isinstance(binding, dict):
        raise DiagnosticContractError("development manifest binding is missing")
    if binding.get("path") != "configs/trimem_v1/development_manifest.json":
        raise DiagnosticContractError("development manifest path drift")
    if binding.get("raw_sha256") != development_raw_sha256:
        raise DiagnosticContractError("development manifest raw hash drift")
    if binding.get("target_set_sha256") != development.get("target_set_sha256"):
        raise DiagnosticContractError("development target-set binding drift")
    if canonical_sha256(development.get("targets")) != development.get("target_set_sha256"):
        raise DiagnosticContractError("development target-set digest mismatch")

    arms = manifest.get("arms")
    if not isinstance(arms, list) or [row.get("arm_id") for row in arms if isinstance(row, dict)] != list(ARMS):
        raise DiagnosticContractError("diagnostic arm order must be exactly C0,C1,C2")
    if len(arms) != len(ARMS) or len({row["arm_id"] for row in arms}) != len(ARMS):
        raise DiagnosticContractError("diagnostic arm set is duplicated or incomplete")

    targets = manifest.get("targets")
    development_targets = development.get("targets")
    if not isinstance(targets, list) or not isinstance(development_targets, list):
        raise DiagnosticContractError("diagnostic/development targets are missing")
    if len(targets) != 12 or len(development_targets) != 12:
        raise DiagnosticContractError("diagnostic requires the exact 12-target DEV set")
    projection_keys = (
        "target_id",
        "instance_id",
        "benchmark_id",
        "dataset_revision",
        "source_row_sha256",
        "base_commit",
        "repository",
        "language",
        "order_index",
    )
    projected = [{key: row.get(key) for key in projection_keys} for row in development_targets]
    if targets != projected:
        raise DiagnosticContractError("diagnostic targets/order drift from frozen DEV")
    ids = [row.get("target_id") for row in targets]
    if len(set(ids)) != 12 or any(row.get("order_index") != index for index, row in enumerate(targets)):
        raise DiagnosticContractError("diagnostic targets are duplicated or out of order")

    cells = expected_cells(manifest)
    matrix = manifest.get("matrix")
    if not isinstance(matrix, dict):
        raise DiagnosticContractError("diagnostic matrix metadata is missing")
    if (
        matrix.get("arm_count") != 3
        or matrix.get("target_count") != 12
        or matrix.get("cell_count") != 36
        or matrix.get("order") != "ARM_MAJOR_THEN_FROZEN_TARGET_ORDER"
        or matrix.get("cell_sequence_sha256") != canonical_sha256(cells)
    ):
        raise DiagnosticContractError("diagnostic 3x12 matrix lock drift")

    if policy.get("schema") != "trimem/dev-activation-policy/1.0":
        raise DiagnosticContractError("diagnostic policy schema drift")
    if policy.get("status") != "FROZEN_PRE_EXEC_DIAGNOSTIC_POLICY":
        raise DiagnosticContractError("diagnostic policy is not frozen")
    if policy.get("diagnostic_id") != manifest.get("diagnostic_id"):
        raise DiagnosticContractError("diagnostic manifest/policy ID mismatch")
    if policy.get("execution_authorized") is not False:
        raise DiagnosticContractError("diagnostic policy must not authorize execution")
    if policy.get("verdict_precedence") != [
        "RETRIEVAL_BANK_COVERAGE_INSUFFICIENT",
        "CURRENT_ROUTER_ACTIVATED_POSITIVE",
        "MEMORY_CONTENT_UPPER_BOUND_POSITIVE_ROUTER_BLOCKED",
        "FORCED_MEMORY_NEGATIVE_TRANSFER",
        "FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED",
    ]:
        raise DiagnosticContractError("primary verdict precedence drift")
    if policy.get("secondary_verdict_labels") != [
        "FORCED_MEMORY_MIXED_ZERO_NET"
    ]:
        raise DiagnosticContractError("secondary verdict label drift")
    policy_arms = policy.get("arms")
    if not isinstance(policy_arms, dict) or tuple(policy_arms) != ARMS:
        raise DiagnosticContractError("diagnostic policy arm order/set drift")

    horizon = policy.get("adaptive_horizon")
    expected_horizon = {
        "base_steps_per_subtask": 8,
        "extension_steps": 4,
        "max_extensions_per_subtask": 2,
        "max_steps_per_subtask": 16,
        "max_solve_calls_per_task_arm": 24,
    }
    if not isinstance(horizon, dict) or any(horizon.get(k) != v for k, v in expected_horizon.items()):
        raise DiagnosticContractError("adaptive horizon numeric contract drift")
    if (
        horizon.get("extension_budget_scope") != "PER_SUBTASK_ACTIVE_NODE"
        or horizon.get("progress_high_water_scope")
        != "TASK_WORKSPACE_WITH_EVENT_CREDIT_TO_ACTIVE_SUBTASK"
    ):
        raise DiagnosticContractError("adaptive horizon scope drift")
    c1 = policy_arms.get("C1")
    c2 = policy_arms.get("C2")
    if (
        not isinstance(c1, dict)
        or "controls retention actions only" not in str(c1.get("dqn_semantics", ""))
        or "no recall USE/ABSTAIN actions" not in str(c1.get("dqn_semantics", ""))
        or not isinstance(c2, dict)
        or c2.get("bypass")
        != [
            "RETRIEVAL_SCORE_ADMISSION_MIN_CONFIDENCE",
            "RETRIEVAL_SCORE_ADMISSION_MIN_MARGIN",
        ]
        or c2.get("tie_break")
        != "confidence descending, embedding score descending, PPR score descending, canonical memory_id ascending"
    ):
        raise DiagnosticContractError("retention-DQN/recall bypass boundary drift")
    coverage_policy = policy.get("coverage_sufficiency")
    if not isinstance(coverage_policy, dict) or coverage_policy.get("required_target_count") != 12:
        raise DiagnosticContractError("coverage precedence must require all 12 DEV targets")
    expected_taxonomy = {
        bucket: sorted(reason for reason, mapped in REASON_TO_BUCKET.items() if mapped == bucket)
        for bucket in ABSTENTION_BUCKETS
    }
    taxonomy = policy.get("reason_taxonomy")
    if not isinstance(taxonomy, dict) or set(taxonomy) != set(expected_taxonomy):
        raise DiagnosticContractError("recall reason taxonomy bucket drift")
    for bucket, reasons in expected_taxonomy.items():
        observed = taxonomy.get(bucket)
        if not isinstance(observed, list) or sorted(observed) != reasons:
            raise DiagnosticContractError(f"recall reason taxonomy drift: {bucket}")
    historical = policy.get("historical_abstention_projection")
    if (
        not isinstance(historical, dict)
        or historical.get("dqn_recall_action_claim_allowed") is not False
        or historical.get("artifact_path") != HISTORICAL_PROJECTION_PATH.as_posix()
        or historical.get("expected_projection_rows") != 179
        or historical.get("m0_control_rows") != 14
        or historical.get("missing_field_value") != HISTORICAL_UNKNOWN
        or historical.get("required_fields") != list(HISTORICAL_DECISION_FIELDS)
        or historical.get("no_imputation") is not True
        or taxonomy.get("router_selected_abstain_with_valid_candidate") != []
    ):
        raise DiagnosticContractError("unsupported recall-DQN claim is enabled")
    expected_caps = {
        "cached_input_tokens": 18_000_000,
        "decomposition_calls": 36,
        "extraction_calls": 36,
        "grader_containers": 36,
        "input_tokens": 18_000_000,
        "max_input_tokens_per_task_arm": 500_000,
        "max_output_tokens_per_task_arm": 65_536,
        "model_calls": 936,
        "model_calls_per_task_arm": 26,
        "official_grader_runs": 36,
        "output_tokens": 2_359_296,
        "paid_model_calls": 936,
        "protocol_canary_calls": 0,
        "scientific_model_calls": 936,
        "solve_calls": 864,
        "task_arm_runs": 36,
        "total_usd": "25.000000000000",
        "uncached_token_cost_ceiling_usd": "24.116832000000",
    }
    if policy.get("hard_caps") != expected_caps:
        raise DiagnosticContractError("diagnostic hard-cap contract drift")
    if policy.get("canary_policy") != {
        "authorized": False,
        "included_in_scientific_model_calls": False,
        "model_call_cap": 0,
        "required_authority_if_proposed_later": "SEPARATE_EXTERNAL_CANARY_APPROVAL",
    }:
        raise DiagnosticContractError("diagnostic canary authority/cap drift")
    if policy.get("development_protocol_binding") != {
        "adaptive_runtime_lock_sha256": (
            "c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652"
        ),
        "historical_runtime_lock_sha256": (
            "f38dbb148e7c7e0573bfab87400ebb9c0c4a786f888d4315d214fdca289fb581"
        ),
        "only_registered_runtime_change": (
            "ENABLE_IDENTICAL_FROZEN_ADAPTIVE_HORIZON_FOR_C0_C1_C2"
        ),
        "public_results_raw_sha256": (
            "a983bcd807d80520349942d296d8b4910bf7c5eb4f1079185aca1937adacd9a1"
        ),
        "selected_candidate_id": "recall",
        "selection_execution_head": "889f4fc0d461d812b531f9413aeaceb2ec3b9fff",
        "selection_rule_outcome_reoptimized": False,
        "selection_workflow_run_attempt": 1,
        "selection_workflow_run_id": 34292287112,
        "status": (
            "FROZEN_EXEC_022_SELECTED_RECALL_WITH_DIAGNOSTIC_ADAPTIVE_HORIZON"
        ),
    }:
        raise DiagnosticContractError("EXEC-022 selected recall protocol binding drift")
    uncached_ceiling = (
        Decimal(expected_caps["input_tokens"]) * Decimal("0.75")
        + Decimal(expected_caps["output_tokens"]) * Decimal("4.5")
    ) / Decimal(1_000_000)
    if format(uncached_ceiling, ".12f") != expected_caps[
        "uncached_token_cost_ceiling_usd"
    ]:
        raise DiagnosticContractError("diagnostic uncached USD ceiling drift")
    namespace = policy.get("namespace_initialization")
    if (
        not isinstance(namespace, dict)
        or namespace.get("cross_cell_carryover") is not False
        or namespace.get("source_bank_mutation") is not False
    ):
        raise DiagnosticContractError("diagnostic namespace isolation drift")
    bank_policy = policy.get("source_bank")
    if (
        not isinstance(bank_policy, dict)
        or bank_policy.get("payload_root")
        != "dev_activation_source_bank_payloads"
        or set(bank_policy.get("required_record_fields", [])) != SOURCE_RECORD_FIELDS
        or bank_policy.get("runtime_safe_pool_metadata")
        != {
            "changed_paths_role": "SEPARATE_CANONICAL_SOURCE_FEATURE_NOT_PATH_SCOPE",
            "path_scope": "**",
            "permission_scope": "PUBLIC_READ",
            "tenant_scope": "BENCHMARK_ISOLATED",
            "version_scope": "EXACT_SOURCE_COMMIT",
        }
    ):
        raise DiagnosticContractError("source-bank record contract drift")
    return cells


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).casefold()
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def validate_source_bank_document(
    bank: Mapping[str, Any],
    *,
    development_target_set_sha256: str,
    forbidden_task_ids: set[str],
) -> list[dict[str, Any]]:
    if bank.get("schema") != "trimem/dev-activation-source-bank/1.0":
        raise DiagnosticContractError("source-bank manifest schema drift")
    if bank.get("status") != "FROZEN_VERIFIED_TARGET_DISJOINT":
        raise DiagnosticContractError("source bank is not frozen verified target-disjoint")
    if bank.get("read_only") is not True or bank.get("result_blind_construction") is not True:
        raise DiagnosticContractError("source bank must be read-only and result-blind")
    if bank.get("development_target_set_sha256") != development_target_set_sha256:
        raise DiagnosticContractError("source bank is not bound to the exact DEV target set")
    if bank.get("target_overlap_count") != 0:
        raise DiagnosticContractError("source bank declares target overlap")
    records = bank.get("records")
    if not isinstance(records, list) or not records:
        raise DiagnosticContractError("source bank has no record inventory")
    if bank.get("record_count") != len(records) or bank.get("records_sha256") != canonical_sha256(records):
        raise DiagnosticContractError("source-bank record count/hash drift")
    forbidden_observed = sorted(set(_walk_keys(bank)) & FORBIDDEN_SOURCE_KEYS)
    if forbidden_observed:
        raise DiagnosticContractError(f"source bank contains forbidden target fields: {forbidden_observed}")

    memory_ids: set[str] = set()
    source_ids: set[str] = set()
    for position, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != SOURCE_RECORD_FIELDS:
            raise DiagnosticContractError(f"source-bank record field drift at {position}")
        memory_id = record["memory_id"]
        source_task_id = record["source_task_id"]
        if not isinstance(memory_id, str) or not memory_id or memory_id in memory_ids:
            raise DiagnosticContractError(f"invalid/duplicate memory_id at {position}")
        if not isinstance(source_task_id, str) or not source_task_id or source_task_id in source_ids:
            raise DiagnosticContractError(f"invalid/duplicate source_task_id at {position}")
        if source_task_id in forbidden_task_ids or any(
            source_task_id.endswith("--" + identity)
            for identity in forbidden_task_ids
        ):
            raise DiagnosticContractError(f"target-derived source record: {source_task_id}")
        if (
            record["verified"] is not True
            or record["reviewed"] is not True
            or record["source_outcome"] != "passed"
            or record["quarantined"] is not False
            or record["target_derived"] is not False
            or record["repository_scope"]
            != "EXACT_SOURCE_AND_TARGET_REPOSITORY"
            or record["bank_type"] != "ORG_SEMANTIC"
            or record["permission_scope"] != "PUBLIC_READ"
            or record["tenant_scope"] != "BENCHMARK_ISOLATED"
            or record["version_scope"] != "EXACT_SOURCE_COMMIT"
            or record["path_scope"] != "**"
        ):
            raise DiagnosticContractError(f"unsafe source record: {memory_id}")
        if record["source_dataset_id"] == "PUBLIC_GITHUB_MERGED_PR":
            if (
                record["source_fix_verification_signal"]
                != "PUBLIC_GITHUB_MERGED_PR_DIFF"
                or record["source_dataset_revision"] != record["source_commit"]
            ):
                raise DiagnosticContractError(
                    f"GitHub oracle source identity drift: {memory_id}"
                )
        elif (
            record["source_fix_verification_signal"]
            != "UPSTREAM_MERGED_FIX_PATCH_EQUIVALENT"
        ):
            raise DiagnosticContractError(
                f"source verification signal drift: {memory_id}"
            )
        for key in (
            "source_dataset_revision",
            "source_base_commit",
            "source_commit",
        ):
            if not HEX40.fullmatch(str(record[key])):
                raise DiagnosticContractError(f"unpinned {key}: {memory_id}")
        if not ISO_UTC.fullmatch(str(record["source_timestamp"])):
            raise DiagnosticContractError(f"unknown/non-UTC source timestamp: {memory_id}")
        for key in (
            "source_row_sha256",
            "verification_evidence_sha256",
            "chronology_and_version_evidence_sha256",
            "provenance_sha256",
            "payload_sha256",
        ):
            if not SHA256.fullmatch(str(record[key])):
                raise DiagnosticContractError(f"invalid {key}: {memory_id}")
        for key in (
            "source_dataset_id",
            "source_repository",
            "bank_type",
            "source_fix_verification_signal",
            "payload_path",
            "permission_scope",
            "tenant_scope",
            "repository_scope",
            "version_scope",
            "path_scope",
        ):
            if not isinstance(record[key], str) or not record[key]:
                raise DiagnosticContractError(f"missing {key}: {memory_id}")
        if not REPOSITORY.fullmatch(record["source_repository"]):
            raise DiagnosticContractError(f"malformed source_repository: {memory_id}")
        for key in ("changed_paths", "symbols", "apis", "errors"):
            values = record[key]
            if (
                not isinstance(values, list)
                or any(not isinstance(value, str) or not value for value in values)
                or values != sorted(set(values))
            ):
                raise DiagnosticContractError(
                    f"non-canonical source feature {key}: {memory_id}"
                )
        if not record["changed_paths"]:
            raise DiagnosticContractError(f"source record has no changed paths: {memory_id}")
        payload_relative = record["payload_path"]
        if (
            payload_relative
            != (
                "dev_activation_source_bank_payloads/"
                f"{record['payload_sha256']}.json"
            )
            or "\\" in payload_relative
        ):
            raise DiagnosticContractError(
                f"payload reference is not content-addressed: {memory_id}"
            )
        memory_ids.add(memory_id)
        source_ids.add(source_task_id)
    return list(records)


def _manifest_relative_payload_path(
    manifest_path: Path,
    relative: str,
) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise DiagnosticContractError("source-bank payload path is malformed")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise DiagnosticContractError(
            f"source-bank payload path escapes manifest directory: {relative}"
        )
    manifest_directory = manifest_path.parent.resolve()
    candidate = manifest_directory.joinpath(*pure.parts)
    current = manifest_directory
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise DiagnosticContractError(
                f"source-bank payload path contains symlink: {relative}"
            )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DiagnosticContractError(
            f"source-bank payload is missing: {relative}"
        ) from exc
    if manifest_directory not in resolved.parents or not resolved.is_file():
        raise DiagnosticContractError(
            f"source-bank payload path escapes manifest directory: {relative}"
        )
    return resolved


def _load_source_bank_payloads(
    root: Path,
    bank_path: Path,
    records: Sequence[Mapping[str, Any]],
    *,
    require_tracked: bool,
) -> dict[str, bytes]:
    payloads: dict[str, bytes] = {}
    for record in records:
        payload_relative = str(record["payload_path"])
        payload_path = _manifest_relative_payload_path(bank_path, payload_relative)
        payload_raw = payload_path.read_bytes()
        if hashlib.sha256(payload_raw).hexdigest() != record["payload_sha256"]:
            raise DiagnosticContractError(
                f"source-bank payload hash drift: {record['memory_id']}"
            )
        if require_tracked:
            repository_relative = payload_path.relative_to(root.resolve()).as_posix()
            _require_tracked(root, repository_relative)
        payload = strict_json_load(payload_path)
        forbidden_payload_keys = sorted(
            set(_walk_keys(payload)) & FORBIDDEN_SOURCE_KEYS
        )
        if forbidden_payload_keys:
            raise DiagnosticContractError(
                "source-bank payload contains forbidden target fields: "
                f"{record['memory_id']} {forbidden_payload_keys}"
            )
        payloads[payload_relative] = payload_raw
    return payloads


def load_and_validate_contract(
    root: Path = ROOT,
    *,
    require_source_bank: bool = True,
    require_tracked: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], str | None]:
    matrix_path = _repo_path(root, MATRIX_PATH.as_posix())
    policy_path = _repo_path(root, POLICY_PATH.as_posix())
    development_path = _repo_path(root, "configs/trimem_v1/development_manifest.json")
    for relative, path in (
        (MATRIX_PATH.as_posix(), matrix_path),
        (POLICY_PATH.as_posix(), policy_path),
        ("configs/trimem_v1/development_manifest.json", development_path),
    ):
        if not path.is_file():
            raise DiagnosticContractError(f"required contract is missing: {relative}")
        if require_tracked:
            _require_tracked(root, relative)
    manifest = strict_json_load(matrix_path)
    policy = strict_json_load(policy_path)
    development = strict_json_load(development_path)
    cells = validate_contract_documents(
        manifest,
        policy,
        development,
        development_raw_sha256=file_sha256(development_path),
    )

    frozen_inputs = policy.get("frozen_inputs")
    if not isinstance(frozen_inputs, dict):
        raise DiagnosticContractError("frozen input registry is missing")
    for name, binding in frozen_inputs.items():
        if not isinstance(binding, dict):
            raise DiagnosticContractError(f"frozen input binding is malformed: {name}")
        relative = binding.get("path")
        expected = binding.get("raw_sha256")
        input_path = _repo_path(root, relative)
        if not input_path.is_file():
            raise DiagnosticContractError(f"frozen input is missing: {name}")
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            raise DiagnosticContractError(f"frozen input hash is malformed: {name}")
        if file_sha256(input_path) != expected:
            raise DiagnosticContractError(f"frozen input hash drift: {name}")
        if require_tracked:
            _require_tracked(root, relative)

    historical_policy = policy["historical_abstention_projection"]
    recoverability_path = _repo_path(
        root, HISTORICAL_RECOVERABILITY_PATH.as_posix()
    )
    projection_relative = historical_policy["artifact_path"]
    projection_path = _repo_path(root, projection_relative)
    if not recoverability_path.is_file() or not projection_path.is_file():
        raise DiagnosticContractError("historical abstention projection closure is missing")
    if require_tracked:
        _require_tracked(root, HISTORICAL_RECOVERABILITY_PATH.as_posix())
        _require_tracked(root, projection_relative)
    recoverability = strict_json_load(recoverability_path)
    projection = strict_json_load(projection_path)
    validate_historical_abstention_projection(
        projection,
        recoverability,
        recoverability_raw_sha256=file_sha256(recoverability_path),
    )
    protocol = policy["development_protocol_binding"]
    accessible = recoverability.get("accessible_evidence")
    approval_binding = recoverability.get("approval_binding")
    if (
        not isinstance(accessible, Mapping)
        or accessible.get("public_results_sha256")
        != protocol["public_results_raw_sha256"]
        or not isinstance(approval_binding, Mapping)
        or approval_binding.get("git_head") != protocol["selection_execution_head"]
        or approval_binding.get("workflow_run_id")
        != protocol["selection_workflow_run_id"]
        or approval_binding.get("workflow_run_attempt")
        != protocol["selection_workflow_run_attempt"]
    ):
        raise DiagnosticContractError("EXEC-022 public selection provenance drift")
    bundle_binding = frozen_inputs["m2_candidate_bundle"]
    candidate_bundle = strict_json_load(_repo_path(root, bundle_binding["path"]))
    candidate_rows = candidate_bundle.get("candidates")
    if not isinstance(candidate_rows, list):
        raise DiagnosticContractError("M2 candidate bundle inventory is missing")
    recall_rows = [
        row
        for row in candidate_rows
        if isinstance(row, Mapping)
        and row.get("candidate_id") == protocol["selected_candidate_id"]
    ]
    selected_policy = frozen_inputs["selected_recall_policy"]
    if len(recall_rows) != 1:
        raise DiagnosticContractError("selected recall candidate is missing or duplicated")
    recall_row = recall_rows[0]
    if (
        recall_row.get("full_policy_path") != selected_policy["path"]
        or recall_row.get("full_policy_file_sha256")
        != selected_policy["raw_sha256"]
        or recall_row.get("runtime_lock_sha256")
        != "sha256:" + protocol["historical_runtime_lock_sha256"]
    ):
        raise DiagnosticContractError("selected recall candidate bundle binding drift")
    try:
        from dataclasses import replace

        from enterprise_memory.trimem.adaptive_horizon import AdaptiveHorizonPolicy
        from trimem_m2_candidates import runtime_lock_for

        historical_runtime = runtime_lock_for("recall")
        adaptive_runtime = replace(
            historical_runtime,
            adaptive_horizon=AdaptiveHorizonPolicy(enabled=True),
        )
    except (ImportError, TypeError, ValueError) as exc:
        raise DiagnosticContractError(
            f"cannot reconstruct selected recall runtime lock: {exc}"
        ) from exc
    if (
        historical_runtime.content_hash
        != protocol["historical_runtime_lock_sha256"]
        or adaptive_runtime.content_hash
        != protocol["adaptive_runtime_lock_sha256"]
    ):
        raise DiagnosticContractError("selected/adaptive recall runtime lock drift")

    bank_policy = policy.get("source_bank")
    if not isinstance(bank_policy, dict):
        raise DiagnosticContractError("source-bank policy is missing")
    bank_relative = bank_policy.get("manifest_path")
    bank_path = _repo_path(root, bank_relative)
    expected_hash = bank_policy.get("manifest_raw_sha256")
    if not require_source_bank:
        return manifest, policy, cells, None
    if not bank_path.is_file():
        raise DiagnosticContractError("SOURCE_BANK_MANIFEST_MISSING")
    if not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash):
        raise DiagnosticContractError("SOURCE_BANK_HASH_NOT_FROZEN")
    if require_tracked:
        _require_tracked(root, bank_relative)
    observed_hash = file_sha256(bank_path)
    if observed_hash != expected_hash:
        raise DiagnosticContractError("SOURCE_BANK_MANIFEST_HASH_DRIFT")
    bank = strict_json_load(bank_path)
    forbidden_ids = {
        str(value)
        for target in development["targets"]
        for value in (target["target_id"], target["instance_id"])
    }
    records = validate_source_bank_document(
        bank,
        development_target_set_sha256=development["target_set_sha256"],
        forbidden_task_ids=forbidden_ids,
    )
    source_plan_relative = SOURCE_BANK_PLAN_PATH.as_posix()
    source_plan_path = _repo_path(root, source_plan_relative)
    if not source_plan_path.is_file():
        raise DiagnosticContractError("SOURCE_BANK_PLAN_MISSING")
    if require_tracked:
        _require_tracked(root, source_plan_relative)
    source_plan = strict_json_load(source_plan_path)
    if bank.get("source_bank_plan_sha256") != canonical_sha256(source_plan):
        raise DiagnosticContractError("SOURCE_BANK_PLAN_HASH_DRIFT")

    chronology = bank.get("chronology_cache")
    if (
        not isinstance(chronology, dict)
        or chronology.get("path") != SOURCE_BANK_CHRONOLOGY_PATH.as_posix()
        or not SHA256.fullmatch(str(chronology.get("raw_sha256", "")))
    ):
        raise DiagnosticContractError("SOURCE_BANK_CHRONOLOGY_BINDING_DRIFT")
    chronology_relative = chronology["path"]
    chronology_path = root / chronology_relative
    if chronology_path.is_symlink() or not chronology_path.is_file():
        raise DiagnosticContractError("SOURCE_BANK_CHRONOLOGY_CACHE_MISSING_OR_SYMLINK")
    if file_sha256(chronology_path) != chronology["raw_sha256"]:
        raise DiagnosticContractError("SOURCE_BANK_CHRONOLOGY_CACHE_HASH_DRIFT")
    if require_tracked:
        _require_tracked(root, chronology_relative)

    payloads = _load_source_bank_payloads(
        root,
        bank_path,
        records,
        require_tracked=require_tracked,
    )
    try:
        validate_compiled_source_bank(
            bank,
            development=development,
            payloads=payloads,
            plan=source_plan,
        )
    except SourceBankError as exc:
        raise DiagnosticContractError(f"SOURCE_BANK_SCHEMA_DRIFT:{exc}") from exc
    return manifest, policy, cells, observed_hash


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise DiagnosticContractError(f"{field} must be a non-negative integer")
    return value


def _usd(value: Any) -> Decimal:
    if not isinstance(value, str):
        raise DiagnosticContractError("total_usd must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise DiagnosticContractError("total_usd is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise DiagnosticContractError("total_usd must be finite and non-negative")
    return parsed


def validate_recall_decision(decision: Mapping[str, Any], target_id: str) -> None:
    required = {
        "recall_attempt_id",
        "target_id",
        "subtask_id",
        "bank_type",
        "candidate_count_before_filter",
        "candidate_count_after_filter",
        "top_candidate_id",
        "top_embedding_score",
        "top_ppr_score",
        "threshold",
        "Q_USE",
        "Q_ABSTAIN",
        "router_policy",
        "final_reason_code",
    }
    if set(decision) != required:
        raise DiagnosticContractError("recall decision field-set drift")
    if decision.get("target_id") != target_id:
        raise DiagnosticContractError("recall decision target mismatch")
    for field in ("recall_attempt_id", "subtask_id", "bank_type"):
        if not isinstance(decision.get(field), str) or not decision[field]:
            raise DiagnosticContractError(f"recall decision missing {field}")
    before = _nonnegative_int(decision.get("candidate_count_before_filter"), "candidate_count_before_filter")
    after = _nonnegative_int(decision.get("candidate_count_after_filter"), "candidate_count_after_filter")
    if after > before:
        raise DiagnosticContractError("candidate count grows across the safe filter")
    top_id = decision.get("top_candidate_id")
    if before == 0 and (after != 0 or top_id is not None):
        raise DiagnosticContractError("zero generated candidates cannot have a top candidate")
    if before > 0 and (not isinstance(top_id, str) or not top_id):
        raise DiagnosticContractError("generated candidates require a top candidate")
    for field in ("top_embedding_score", "top_ppr_score"):
        value = decision.get(field)
        if value is not None and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise DiagnosticContractError(f"{field} must be numeric or null")
    if not isinstance(decision.get("threshold"), dict):
        raise DiagnosticContractError("recall threshold snapshot is missing")
    if decision.get("Q_USE") is not None or decision.get("Q_ABSTAIN") is not None:
        raise DiagnosticContractError("DQN recall Q-values are not implemented and must be null")
    if decision.get("router_policy") != "N/A":
        raise DiagnosticContractError("recall router_policy must be N/A for this implementation")
    reason = decision.get("final_reason_code")
    if reason not in DECISION_REASONS:
        raise DiagnosticContractError(f"unknown recall final_reason_code: {reason}")
    if reason == "INJECTED" and after == 0:
        raise DiagnosticContractError("injected decision has no safe candidate")


def _validate_cell(
    cell: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    source_bank_sha256: str,
) -> None:
    required = {
        "schema",
        "diagnostic_id",
        "cell_id",
        "cell_index",
        "arm_id",
        "target_id",
        "target_order_index",
        "source_bank_manifest_sha256",
        "official_grader_evidence_sha256",
        "terminal",
        "terminal_reason_code",
        "official_grader_resolved",
        "diagnostic_resolved",
        "patch_class",
        "model_failure_code",
        "extraction_status",
        "extraction_failure_code",
        "injections",
        "recall_decisions",
        "adaptive_horizon",
        "accounting",
    }
    if set(cell) != required or cell.get("schema") != "trimem/dev-activation-cell/1.0":
        raise DiagnosticContractError("diagnostic cell schema/field-set drift")
    for key in ("cell_id", "cell_index", "arm_id", "target_id", "target_order_index"):
        if cell.get(key) != expected.get(key):
            raise DiagnosticContractError(f"diagnostic cell identity drift: {key}")
    arm = cell["arm_id"]
    expected_bank = None if arm == "C0" else source_bank_sha256
    if cell.get("source_bank_manifest_sha256") != expected_bank:
        raise DiagnosticContractError("cell source-bank binding drift")
    if cell.get("terminal") is not True or cell.get("terminal_reason_code") not in TERMINAL_REASONS:
        raise DiagnosticContractError("cell is not terminal with a known reason")
    if not isinstance(cell.get("official_grader_resolved"), bool):
        raise DiagnosticContractError("cell official grader result is unknown")
    if not isinstance(cell.get("diagnostic_resolved"), bool):
        raise DiagnosticContractError("cell diagnostic result is unknown")
    if not SHA256.fullmatch(str(cell.get("official_grader_evidence_sha256"))):
        raise DiagnosticContractError("cell official grader evidence hash is missing")
    if cell.get("patch_class") not in PATCH_CLASSES:
        raise DiagnosticContractError("cell patch class is unknown")
    failure = cell.get("model_failure_code")
    if failure is not None and (not isinstance(failure, str) or not failure):
        raise DiagnosticContractError("model_failure_code must be null or non-empty")
    failure_terminal = cell["terminal_reason_code"] in {
        "MODEL_FAILURE_CONTINUED_TO_GRADER",
        "CONTAINED_RUNTIME_FAILURE_CONTINUED_TO_GRADER",
    }
    if failure_terminal != (failure is not None):
        raise DiagnosticContractError("model failure and terminal reason disagree")
    extraction_status = cell.get("extraction_status")
    extraction_failure = cell.get("extraction_failure_code")
    if extraction_status not in {"SUCCESS", "MEMORY_EXTRACTION_FAILED"}:
        raise DiagnosticContractError("cell extraction_status is unknown")
    if extraction_status == "SUCCESS":
        if extraction_failure is not None:
            raise DiagnosticContractError(
                "successful extraction cannot have an extraction failure code"
            )
    elif not isinstance(extraction_failure, str) or not extraction_failure:
        raise DiagnosticContractError(
            "failed extraction requires a separate non-empty failure code"
        )
    expected_diagnostic_resolved = (
        cell["official_grader_resolved"]
        and failure is None
        and extraction_status == "SUCCESS"
    )
    if cell["diagnostic_resolved"] is not expected_diagnostic_resolved:
        raise DiagnosticContractError(
            "diagnostic unresolved classification disagrees with model failures"
        )
    extraction_only = (
        cell["terminal_reason_code"]
        == "EXTRACTION_FAILURE_AFTER_OFFICIAL_GRADE"
    )
    if extraction_only and not (
        extraction_status == "MEMORY_EXTRACTION_FAILED" and failure is None
    ):
        raise DiagnosticContractError(
            "extraction-only terminal semantics disagree with failure fields"
        )

    injections = cell.get("injections")
    if not isinstance(injections, list) or len(injections) > 3:
        raise DiagnosticContractError("cell injections are missing or exceed task cap")
    injection_fields = {
        "memory_id", "source_task_id", "source_repository", "target_repository",
        "bank_type", "subtask_id", "repo_overlap",
        "active_subtask_projection_sha256",
        "active_subtask_declared_file_overlap",
        "active_subtask_declared_symbol_overlap",
        "active_subtask_declared_api_overlap",
        "active_subtask_declared_error_overlap",
        "pre_execution_target_issue_overlap",
    }
    seen_memory: set[str] = set()
    per_subtask: Counter[str] = Counter()
    for injection in injections:
        if not isinstance(injection, dict) or set(injection) != injection_fields:
            raise DiagnosticContractError("injection overlap evidence field drift")
        if not isinstance(injection["memory_id"], str) or not injection["memory_id"]:
            raise DiagnosticContractError("injection memory_id is missing")
        for key in ("source_task_id", "source_repository", "target_repository"):
            if not isinstance(injection[key], str) or not injection[key]:
                raise DiagnosticContractError(f"injection {key} is missing")
        if injection["repo_overlap"] != (
            injection["source_repository"] == injection["target_repository"]
        ):
            raise DiagnosticContractError("injection repository overlap is inconsistent")
        if injection["memory_id"] in seen_memory:
            raise DiagnosticContractError("duplicate injection memory_id in one cell")
        if not isinstance(injection["subtask_id"], str) or not injection["subtask_id"]:
            raise DiagnosticContractError("injection subtask_id is missing")
        if type(injection["repo_overlap"]) is not bool:
            raise DiagnosticContractError("repo overlap must be boolean")
        if not SHA256.fullmatch(injection["active_subtask_projection_sha256"]):
            raise DiagnosticContractError(
                "active subtask overlap projection hash is malformed"
            )
        for key in (
            "active_subtask_declared_file_overlap",
            "active_subtask_declared_symbol_overlap",
            "active_subtask_declared_api_overlap",
            "active_subtask_declared_error_overlap",
        ):
            if not isinstance(injection[key], list) or any(not isinstance(v, str) for v in injection[key]):
                raise DiagnosticContractError(f"{key} must be a string list")
        frozen_overlap = injection["pre_execution_target_issue_overlap"]
        if not isinstance(frozen_overlap, dict) or set(frozen_overlap) != {
            "errors_overlap", "apis_overlap", "symbols_overlap",
            "paths_overlap", "tokens_overlap",
        } or any(type(value) is not int or value < 0 for value in frozen_overlap.values()):
            raise DiagnosticContractError(
                "pre-execution target issue overlap is malformed"
            )
        seen_memory.add(injection["memory_id"])
        per_subtask[injection["subtask_id"]] += 1
    if arm == "C0" and injections:
        raise DiagnosticContractError("C0 cannot contain memory injections")
    if arm == "C2" and any(count > 1 for count in per_subtask.values()):
        raise DiagnosticContractError("C2 exceeds safe top-1 per subtask")

    decisions = cell.get("recall_decisions")
    if not isinstance(decisions, list):
        raise DiagnosticContractError("recall decisions are missing")
    if arm == "C0" and decisions:
        raise DiagnosticContractError("C0 cannot contain recall decisions")
    attempts: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise DiagnosticContractError("recall decision is not an object")
        validate_recall_decision(decision, cell["target_id"])
        attempt = decision["recall_attempt_id"]
        if attempt in attempts:
            raise DiagnosticContractError("duplicate recall_attempt_id")
        attempts.add(attempt)
    injected_decisions = sum(row["final_reason_code"] == "INJECTED" for row in decisions)
    if injected_decisions != len(injections):
        raise DiagnosticContractError("injection evidence/decision count mismatch")

    horizon = cell.get("adaptive_horizon")
    if not isinstance(horizon, dict) or set(horizon) != {
        "extensions_granted", "progress_event_ids", "per_subtask_extensions",
        "agent_completed_count", "per_subtask_step_cap_reached_count",
    }:
        raise DiagnosticContractError("adaptive horizon evidence field drift")
    extensions = _nonnegative_int(horizon["extensions_granted"], "extensions_granted")
    per_subtask_extensions = horizon["per_subtask_extensions"]
    if (
        not isinstance(per_subtask_extensions, dict)
        or any(not isinstance(key, str) or not key for key in per_subtask_extensions)
    ):
        raise DiagnosticContractError("per-subtask adaptive evidence is invalid")
    for subtask_id, count in per_subtask_extensions.items():
        if type(count) is not int or count < 0 or count > 2:
            raise DiagnosticContractError(
                f"subtask exceeds two adaptive extensions: {subtask_id}"
            )
    if sum(per_subtask_extensions.values()) != extensions:
        raise DiagnosticContractError("per-subtask extension total mismatch")
    events = horizon["progress_event_ids"]
    if not isinstance(events, list) or len(events) != extensions or len(set(events)) != len(events):
        raise DiagnosticContractError("adaptive extension/progress evidence mismatch")
    _nonnegative_int(horizon["agent_completed_count"], "agent_completed_count")
    _nonnegative_int(
        horizon["per_subtask_step_cap_reached_count"],
        "per_subtask_step_cap_reached_count",
    )

    accounting = cell.get("accounting")
    accounting_fields = {
        "decomposition_calls", "solve_calls", "extraction_calls", "input_tokens",
        "cached_input_tokens", "output_tokens", "paid_model_calls", "model_wall_time_ms",
        "tool_wall_time_ms", "grader_wall_time_ms", "grader_calls",
        "grader_containers", "official_grader_runs", "task_wall_time_ms",
        "total_usd",
    }
    if not isinstance(accounting, dict) or set(accounting) != accounting_fields:
        raise DiagnosticContractError("cell accounting field-set drift")
    for field in accounting_fields - {"total_usd"}:
        _nonnegative_int(accounting[field], field)
    if accounting["cached_input_tokens"] > accounting["input_tokens"]:
        raise DiagnosticContractError("cached input tokens exceed input tokens")
    if any(
        accounting[field] != 1
        for field in ("grader_calls", "grader_containers", "official_grader_runs")
    ):
        raise DiagnosticContractError(
            "each cell requires exactly one official grader run/container"
        )
    _usd(accounting["total_usd"])
    if (
        accounting["decomposition_calls"] > 1
        or accounting["solve_calls"] > 24
        or accounting["extraction_calls"] > 1
        or accounting["decomposition_calls"]
        + accounting["solve_calls"]
        + accounting["extraction_calls"]
        > 26
    ):
        raise DiagnosticContractError("cell exceeds the frozen model-call budget")
    model_calls = (
        accounting["decomposition_calls"]
        + accounting["solve_calls"]
        + accounting["extraction_calls"]
    )
    if accounting["paid_model_calls"] > model_calls:
        raise DiagnosticContractError("paid model calls exceed actual model calls")
    if accounting["input_tokens"] > 500_000:
        raise DiagnosticContractError("cell exceeds the frozen input-token budget")
    if accounting["output_tokens"] > 65_536:
        raise DiagnosticContractError("cell exceeds the frozen output-token budget")


def abstention_histogram(decisions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    histogram = {bucket: 0 for bucket in ABSTENTION_BUCKETS}
    for decision in decisions:
        target = decision.get("target_id")
        if not isinstance(target, str) or not target:
            raise DiagnosticContractError("abstention decision target_id is missing")
        validate_recall_decision(decision, target)
        reason = decision["final_reason_code"]
        if reason != "INJECTED":
            histogram[REASON_TO_BUCKET[reason]] += 1
    return histogram


def _verdict(
    resolved: Mapping[str, int],
    target_resolved: Mapping[str, Mapping[str, bool]],
    injected_targets: Mapping[str, set[str]],
    c2_covered_targets: int,
    required_coverage: int,
) -> tuple[str, list[str]]:
    secondary: list[str] = []
    c20 = resolved["C2"] - resolved["C0"]
    c10 = resolved["C1"] - resolved["C0"]
    flips_up = sum(
        target_resolved["C2"][target] and not target_resolved["C0"][target]
        for target in target_resolved["C0"]
    )
    flips_down = sum(
        target_resolved["C0"][target] and not target_resolved["C2"][target]
        for target in target_resolved["C0"]
    )
    c1_injection_aligned_positive_flip = any(
        target in injected_targets["C1"]
        and target_resolved["C1"][target]
        and not target_resolved["C0"][target]
        for target in target_resolved["C0"]
    )
    if c2_covered_targets < required_coverage:
        if c20 > 0:
            secondary.append("OBSERVED_C2_POSITIVE_UNDER_INSUFFICIENT_COVERAGE")
        elif c20 < 0:
            secondary.append("OBSERVED_C2_NEGATIVE_UNDER_INSUFFICIENT_COVERAGE")
        elif flips_up and flips_down:
            secondary.append("OBSERVED_C2_MIXED_ZERO_NET_UNDER_INSUFFICIENT_COVERAGE")
        return "RETRIEVAL_BANK_COVERAGE_INSUFFICIENT", secondary
    if c1_injection_aligned_positive_flip and c10 > 0:
        if c20 > 0:
            secondary.append("MEMORY_CONTENT_UPPER_BOUND_POSITIVE")
        return "CURRENT_ROUTER_ACTIVATED_POSITIVE", secondary
    if c20 > 0:
        return "MEMORY_CONTENT_UPPER_BOUND_POSITIVE_ROUTER_BLOCKED", secondary
    if c20 < 0:
        return "FORCED_MEMORY_NEGATIVE_TRANSFER", secondary
    if flips_up and flips_down:
        secondary.append("FORCED_MEMORY_MIXED_ZERO_NET")
    return "FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED", secondary


def aggregate_results(
    result: Mapping[str, Any],
    manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    source_bank_sha256: str,
) -> dict[str, Any]:
    if result.get("schema") != "trimem/dev-activation-results/1.0":
        raise DiagnosticContractError("diagnostic results schema drift")
    if result.get("diagnostic_id") != manifest.get("diagnostic_id"):
        raise DiagnosticContractError("diagnostic result ID mismatch")
    ledger_finalization_sha256 = result.get(
        "atomic_budget_ledger_finalization_sha256"
    )
    if ledger_finalization_sha256 is not None and not SHA256.fullmatch(
        str(ledger_finalization_sha256)
    ):
        raise DiagnosticContractError(
            "atomic budget ledger finalization hash is malformed"
        )
    cells = result.get("cells")
    if not isinstance(cells, list):
        raise DiagnosticContractError("diagnostic cells are missing")
    expected = expected_cells(manifest)
    expected_by_id = {row["cell_id"]: row for row in expected}
    observed_ids = [row.get("cell_id") for row in cells if isinstance(row, dict)]
    duplicates = sorted(cell_id for cell_id, count in Counter(observed_ids).items() if count > 1)
    missing = sorted(set(expected_by_id) - set(observed_ids))
    unknown = sorted(str(cell_id) for cell_id in set(observed_ids) - set(expected_by_id))
    if len(cells) != 36 or duplicates or missing or unknown or len(observed_ids) != len(cells):
        raise DiagnosticContractError(
            f"cell matrix incomplete: missing={missing}, duplicate={duplicates}, unknown={unknown}"
        )

    by_arm: dict[str, list[Mapping[str, Any]]] = {arm: [] for arm in ARMS}
    all_decisions: list[Mapping[str, Any]] = []
    all_attempt_ids: set[str] = set()
    for cell in cells:
        expected_cell = expected_by_id[cell["cell_id"]]
        _validate_cell(cell, expected_cell, source_bank_sha256=source_bank_sha256)
        if cell["diagnostic_id"] != manifest["diagnostic_id"]:
            raise DiagnosticContractError("cell diagnostic_id drift")
        by_arm[cell["arm_id"]].append(cell)
        for decision in cell["recall_decisions"]:
            attempt_id = decision["recall_attempt_id"]
            if attempt_id in all_attempt_ids:
                raise DiagnosticContractError("duplicate recall_attempt_id across cells")
            all_attempt_ids.add(attempt_id)
            all_decisions.append(decision)
    for arm in ARMS:
        by_arm[arm].sort(key=lambda row: row["target_order_index"])

    summaries: list[dict[str, Any]] = []
    resolved: dict[str, int] = {}
    official_resolved: dict[str, int] = {}
    injection_tasks: dict[str, int] = {}
    injected_targets: dict[str, set[str]] = {}
    target_resolved: dict[str, dict[str, bool]] = {}
    target_official_resolved: dict[str, dict[str, bool]] = {}
    coverage: dict[tuple[str, str], set[str]] = defaultdict(set)
    coverage_candidates: Counter[tuple[str, str]] = Counter()
    for arm in ARMS:
        rows = by_arm[arm]
        resolved[arm] = sum(row["diagnostic_resolved"] for row in rows)
        official_resolved[arm] = sum(
            row["official_grader_resolved"] for row in rows
        )
        injection_tasks[arm] = sum(bool(row["injections"]) for row in rows)
        injected_targets[arm] = {
            row["target_id"] for row in rows if row["injections"]
        }
        target_resolved[arm] = {
            row["target_id"]: row["diagnostic_resolved"] for row in rows
        }
        target_official_resolved[arm] = {
            row["target_id"]: row["official_grader_resolved"] for row in rows
        }
        for row in rows:
            for decision in row["recall_decisions"]:
                safe = decision["candidate_count_after_filter"]
                if safe > 0:
                    key = (arm, decision["bank_type"])
                    coverage[key].add(row["target_id"])
                    coverage_candidates[key] += safe
        accounting_fields = (
            "decomposition_calls", "solve_calls", "extraction_calls", "input_tokens",
            "cached_input_tokens", "output_tokens", "paid_model_calls", "model_wall_time_ms",
            "tool_wall_time_ms", "grader_wall_time_ms", "grader_calls",
            "grader_containers", "official_grader_runs", "task_wall_time_ms",
        )
        totals = {field: sum(row["accounting"][field] for row in rows) for field in accounting_fields}
        totals["model_calls"] = (
            totals["decomposition_calls"] + totals["solve_calls"] + totals["extraction_calls"]
        )
        totals["total_usd"] = format(sum((_usd(row["accounting"]["total_usd"]) for row in rows), Decimal(0)), "f")
        summaries.append(
            {
                "arm": arm,
                "injected_tasks": injection_tasks[arm],
                "total_injections": sum(len(row["injections"]) for row in rows),
                "terminal": sum(row["terminal"] is True for row in rows),
                "partial_patch": sum(row["patch_class"] == "PARTIAL_PATCH" for row in rows),
                "no_op": sum(row["patch_class"] == "CANONICAL_NOOP" for row in rows),
                "extraction_failures": sum(
                    row["extraction_status"] == "MEMORY_EXTRACTION_FAILED"
                    for row in rows
                ),
                "diagnostic_solved": resolved[arm],
                "diagnostic_pass_at_1": format(
                    Decimal(resolved[arm]) / Decimal(12), ".12f"
                ),
                "official_solved": official_resolved[arm],
                "official_pass_at_1": format(
                    Decimal(official_resolved[arm]) / Decimal(12), ".12f"
                ),
                **totals,
            }
        )

    caps = policy["hard_caps"]
    capped_totals = {
        "decomposition_calls": sum(row["decomposition_calls"] for row in summaries),
        "solve_calls": sum(row["solve_calls"] for row in summaries),
        "extraction_calls": sum(row["extraction_calls"] for row in summaries),
        "model_calls": sum(row["model_calls"] for row in summaries),
        "paid_model_calls": sum(row["paid_model_calls"] for row in summaries),
        "input_tokens": sum(row["input_tokens"] for row in summaries),
        "cached_input_tokens": sum(row["cached_input_tokens"] for row in summaries),
        "output_tokens": sum(row["output_tokens"] for row in summaries),
    }
    for field, observed in capped_totals.items():
        if observed > caps[field]:
            raise DiagnosticContractError(
                f"aggregate exceeds the frozen {field} cap"
            )
    total_usd = sum(
        (_usd(row["total_usd"]) for row in summaries),
        Decimal(0),
    )
    if total_usd > Decimal(caps["total_usd"]):
        raise DiagnosticContractError("aggregate exceeds the frozen total_usd cap")

    c2_covered = {
        row["target_id"]
        for row in by_arm["C2"]
        if any(decision["candidate_count_after_filter"] > 0 for decision in row["recall_decisions"])
    }
    required_coverage = policy["coverage_sufficiency"]["required_target_count"]
    verdict, secondary = _verdict(
        resolved,
        target_resolved,
        injected_targets,
        len(c2_covered),
        required_coverage,
    )

    def flips(
        left: str,
        right: str,
        outcomes: Mapping[str, Mapping[str, bool]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "target_id": target,
                f"{left}_resolved": outcomes[left][target],
                f"{right}_resolved": outcomes[right][target],
            }
            for target in outcomes[left]
            if outcomes[left][target] != outcomes[right][target]
        ]

    c1_aligned_positive_targets = sorted(
        target
        for target in injected_targets["C1"]
        if target_resolved["C1"][target] and not target_resolved["C0"][target]
    )

    aggregate = {
        "schema": "trimem/dev-activation-aggregate/1.0",
        "status": "COMPLETE_36_OF_36_OFFICIAL_CELLS",
        "diagnostic_id": manifest["diagnostic_id"],
        "scientific_role": "POST_DEV_ACTIVATION_DIAGNOSTIC_NOT_SELECTION_OR_HELDOUT_EVIDENCE",
        "source_bank_manifest_sha256": source_bank_sha256,
        "arm_summary": summaries,
        "c2_minus_c0_diagnostic_target_flips": flips(
            "C0", "C2", target_resolved
        ),
        "c2_minus_c1_diagnostic_target_flips": flips(
            "C1", "C2", target_resolved
        ),
        "c2_minus_c0_official_target_flips": flips(
            "C0", "C2", target_official_resolved
        ),
        "c2_minus_c1_official_target_flips": flips(
            "C1", "C2", target_official_resolved
        ),
        "verdict_basis": {
            "outcome": (
                "diagnostic_resolved: official grader resolved with no "
                "solve/runtime/extraction model failure"
            ),
            "official_outcome_reported_separately": True,
            "c1_current_router_requires_injection_aligned_positive_flip": True,
            "c1_injection_aligned_positive_target_ids": (
                c1_aligned_positive_targets
            ),
            "c2_comparison": "paired arm-level intention-to-treat",
        },
        "bank_candidate_coverage": [
            {
                "arm": arm,
                "bank_type": bank,
                "covered_target_count": len(coverage[(arm, bank)]),
                "safe_candidate_count": coverage_candidates[(arm, bank)],
            }
            for arm, bank in sorted(coverage)
        ],
        "c2_safe_candidate_coverage": {
            "covered_target_count": len(c2_covered),
            "required_target_count": required_coverage,
            "sufficient": len(c2_covered) >= required_coverage,
        },
        "abstention_reason_histogram": abstention_histogram(all_decisions),
        "injected_memory_overlap": [
            {
                "arm": row["arm_id"],
                "target_id": row["target_id"],
                **dict(injection),
            }
            for row in cells
            for injection in row["injections"]
        ],
        "extraction_failures": sum(
            row["extraction_status"] == "MEMORY_EXTRACTION_FAILED"
            for row in cells
        ),
        "step_cap_extensions": sum(
            row["adaptive_horizon"]["extensions_granted"] for row in cells
        ),
        "agent_completed": sum(
            row["adaptive_horizon"]["agent_completed_count"] for row in cells
        ),
        "per_subtask_step_cap_reached": sum(
            row["adaptive_horizon"]["per_subtask_step_cap_reached_count"] for row in cells
        ),
        "verdict": verdict,
        "secondary_labels": secondary,
    }
    if ledger_finalization_sha256 is not None:
        aggregate["atomic_budget_ledger_finalization_sha256"] = (
            ledger_finalization_sha256
        )
    return aggregate


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "contract",
        help="validate the complete frozen credential-free contract and source bank",
    )
    historical_projection = subparsers.add_parser(
        "historical-projection",
        help="materialize the deterministic 179-row aggregate-only projection",
    )
    historical_projection.add_argument(
        "--output",
        type=Path,
        default=ROOT / HISTORICAL_PROJECTION_PATH,
    )
    subparsers.add_parser("preflight", help="validate all frozen inputs, including source bank")
    subparsers.add_parser("plan", help="emit the exact 36-cell plan after full preflight")
    aggregate = subparsers.add_parser("aggregate", help="aggregate 36 external official cell records")
    aggregate.add_argument("--results", type=Path, required=True)
    aggregate.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "historical-projection":
            recoverability_path = ROOT / HISTORICAL_RECOVERABILITY_PATH
            recoverability = strict_json_load(recoverability_path)
            payload = build_historical_abstention_projection(
                recoverability,
                recoverability_raw_sha256=file_sha256(recoverability_path),
            )
            args.output.write_bytes(canonical_bytes(payload) + b"\n")
        elif args.command == "contract":
            manifest, policy, cells, bank_hash = load_and_validate_contract()
            payload: dict[str, Any] = {
                "status": "PASS_FROZEN_CONTRACT_SOURCE_BANK_READY",
                "diagnostic_id": manifest["diagnostic_id"],
                "cell_count": len(cells),
                "source_bank_manifest_sha256": bank_hash,
                "execution_authorized": False,
                "model_calls": 0,
                "official_grader_runs": 0,
            }
        else:
            manifest, policy, cells, bank_hash = load_and_validate_contract()
        if args.command == "historical-projection":
            pass
        elif args.command == "contract":
            pass
        elif args.command == "preflight":
            payload = {
                "status": "PASS",
                "cell_count": len(cells),
                "source_bank_manifest_sha256": bank_hash,
                "model_calls": 0,
                "official_grader_runs": 0,
            }
        elif args.command == "plan":
            payload = {
                "status": "READY_FOR_SEPARATE_EXEC_APPROVAL",
                "cells": cells,
                "source_bank_manifest_sha256": bank_hash,
                "execution_authorized": False,
            }
        else:
            result = strict_json_load(args.results)
            payload = aggregate_results(
                result,
                manifest,
                policy,
                source_bank_sha256=str(bank_hash),
            )
            if args.output:
                args.output.write_bytes(canonical_bytes(payload) + b"\n")
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except DiagnosticContractError as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
