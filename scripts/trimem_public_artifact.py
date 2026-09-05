"""Publish only fields already verified and sealed by the fail-closed aggregate."""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from enterprise_memory.trimem.scientific_terminal import (  # noqa: E402
    SCIENTIFIC_CELL_STATUSES,
    is_scientific_gateway_failure,
)
from trimem_multi_swe_report_semantics import (
    MultiSWEReportSemanticsError,
    PUBLIC_SUMMARY_FIELDS,
    validate_public_semantics_summary,
)
from trimem_m2_candidates import (
    CandidateContractError,
    load_bundle as load_m2_candidate_bundle,
    select_development_candidate,
)


FORBIDDEN_KEYS = {
    "patch", "gold_patch", "fix_patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS",
    "source_row", "repository_files", "raw_report", "restricted_raw_report",
}
RAW_MULTI_SWE_KEYS = frozenset({
    "error_msg",
    "fixed_tests",
    "passed_tests",
    "failed_tests",
    "skipped_tests",
    "p2p_tests",
    "f2p_tests",
    "s2p_tests",
    "n2p_tests",
    "run_result",
    "test_patch_result",
    "fix_patch_result",
    "valid",
})
PRIVATE_FAILURE_KEYS = frozenset({
    "adapter_primary_error",
    "adapter_secondary_evidence_failures",
    "exception",
    "failure_reason",
    "failure_reasons",
    "primary_failure",
    "reason",
    "secondary_evidence_failures",
    "traceback",
})
SMOKE_OUTCOME_FIELDS = (
    "target_id",
    "benchmark_id",
    "order_index",
    "probe",
    "resolved",
    "applied_patch_sha256",
    "official_test_output_sha256",
    "official_test_status_sha256",
    "container_exit_status_sha256",
    "execution_contract_sha256",
    "execution_control_sha256",
    "submitted_patch_identity_sha256",
    "semantic_normalization",
    "patch_applied",
    "tests_executed",
    "digest_match",
    "submitted_patch_identity",
    "host_prepare_sh_access_count",
    "source_image_build_count",
    "api_calls",
    "container_exit_status_code",
    "container_exit_acceptance",
)
BENCHMARK_OUTCOME_FIELDS = (
    "arm",
    "benchmark_id",
    "benchmark_role",
    "resolved",
    "target_id",
    "actual_accounting",
    "actual_memory_metrics",
    "provider_outcomes",
    "actual_usd",
)
SCIENTIFIC_ACCOUNTING_FIELDS = (
    "solve_calls",
    "decomposition_calls",
    "extraction_calls",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "actual_decomposition_output_tokens",
    "actual_solve_output_tokens",
    "actual_extraction_output_tokens",
    "solve_output_pool_capacity",
    "remaining_solve_output_tokens",
    "replace_text_calls",
    "write_file_calls",
    "model_wall_time_ms",
    "tool_wall_time_ms",
    "grader_wall_time_ms",
    "task_wall_time_ms",
    "model_gateway_calls",
    "paid_model_calls",
    "grader_calls",
    "grader_containers",
    "official_grader_runs",
)
SCIENTIFIC_MEMORY_FIELDS = (
    "recall_attempts",
    "injected_records",
    "episodic_injections",
    "user_semantic_injections",
    "org_semantic_injections",
    "abstention_decisions",
    "retained_records",
    "archived_records",
    "net_memory_growth",
)
PROVIDER_OUTCOME_FIELDS = frozenset(
    {
        "provider_status_distribution",
        "incomplete_count",
        "refusal_count",
        "structured_output_schema_failure_count",
        "provider_reported_usage",
        "ledger_reservation",
    }
)
PROVIDER_USAGE_FIELDS = (
    "available_calls",
    "unavailable_calls",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
)
PROVIDER_RESERVATION_FIELDS = (
    "calls",
    "input_upper_bound",
    "output_cap",
    "conservatively_charged_calls",
)
SCIENTIFIC_PHASE_BUDGET_FIELDS = frozenset(
    {
        "schema",
        "actual_accounting",
        "model_calls",
        "task_arm_runs",
        "total_usd",
        "uncached_token_cost_usd",
        "hard_cap",
        "status",
    }
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
POSITIVE_INTEGER = re.compile(r"^[1-9][0-9]*$")
MONEY_12 = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{12}")
EXPECTED_PHASE_BY_MANIFEST = {
    "grader-smoke": "GRADER_SMOKE",
    "development": "DEVELOPMENT_TUNING",
    "heldout": "HELDOUT_BENCHMARK",
}


def validate_public_approval_binding(
    approval: Any, *, manifest: str
) -> dict[str, str]:
    expected_phase = EXPECTED_PHASE_BY_MANIFEST.get(manifest)
    if expected_phase is None:
        raise PublicArtifactError("aggregate approval manifest is invalid")
    required = {
        "approval_artifact_sha256",
        "approved_request_sha256",
        "approved_workflow_run_id",
        "approved_workflow_run_attempt",
        "freeze_sha256",
        "git_head",
        "phase",
    }
    if manifest == "development":
        required.add("source_head")
    if not isinstance(approval, dict) or set(approval) != required:
        raise PublicArtifactError("aggregate approval binding is malformed")
    for field in (
        "approval_artifact_sha256",
        "approved_request_sha256",
        "freeze_sha256",
    ):
        if not isinstance(approval[field], str) or not SHA256.fullmatch(approval[field]):
            raise PublicArtifactError(f"aggregate approval binding has invalid {field}")
    if not isinstance(approval["git_head"], str) or not HEX40.fullmatch(
        approval["git_head"]
    ):
        raise PublicArtifactError("aggregate approval binding has invalid git_head")
    if manifest == "development" and (
        not isinstance(approval["source_head"], str)
        or not HEX40.fullmatch(approval["source_head"])
    ):
        raise PublicArtifactError("aggregate approval binding has invalid source_head")
    if approval["phase"] != expected_phase:
        raise PublicArtifactError("aggregate approval phase differs from manifest")
    for field in ("approved_workflow_run_id", "approved_workflow_run_attempt"):
        if (
            not isinstance(approval[field], str)
            or POSITIVE_INTEGER.fullmatch(approval[field]) is None
        ):
            raise PublicArtifactError(
                f"aggregate approval binding has invalid {field}"
            )
    if (
        manifest in {"grader-smoke", "development"}
        and approval["approved_workflow_run_attempt"] != "1"
    ):
        raise PublicArtifactError(
            "one-time aggregate approval requires workflow run attempt 1"
        )
    return {field: str(approval[field]) for field in sorted(required)}


SMOKE_ACCOUNTING_FIELDS = (
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
    "task_arm_runs",
    "total_usd",
)
SMOKE_FAILURE_TAXONOMY_FIELDS = (
    "environment_failures",
    "infrastructure_failures",
    "image_lifecycle_failures",
    "official_harness_failures",
    "official_report_failures",
    "adapter_contract_failures",
    "aggregate_failures",
)
SMOKE_IMAGE_LIFECYCLE_ACTUAL = {
    "target_image_pulls": 6,
    "support_image_pulls": 1,
    "exact_image_removals": 7,
    "max_resident_target_images": 1,
    "max_resident_support_images": 1,
    "resident_target_images": 0,
    "resident_support_images": 0,
}


class PublicArtifactError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise PublicArtifactError(f"duplicate JSON key in {path}: {key}")
            value[key] = child
        return value
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(value, dict):
        raise PublicArtifactError(f"JSON root is not an object: {path}")
    return value


def _frozen_current_file_sha256(
    relative_path: str, *, expected_freeze_sha256: str
) -> str:
    """Bind a public scientific contract to the approved local freeze."""

    freeze_path = ROOT / "artifacts/trimem_v1/freeze.json"
    try:
        freeze_raw = freeze_path.read_bytes()
        freeze = json.loads(freeze_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicArtifactError("approved research freeze is unavailable") from exc
    if (
        hashlib.sha256(freeze_raw).hexdigest() != expected_freeze_sha256
        or not isinstance(freeze, Mapping)
    ):
        raise PublicArtifactError("approved research freeze digest differs")
    files = freeze.get("files")
    row = files.get(relative_path) if isinstance(files, Mapping) else None
    path = ROOT / relative_path
    if (
        not isinstance(row, Mapping)
        or set(row) != {"bytes", "sha256"}
        or not path.is_file()
    ):
        raise PublicArtifactError(f"research freeze lacks required file: {relative_path}")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if row.get("bytes") != len(raw) or row.get("sha256") != digest:
        raise PublicArtifactError(f"frozen required file bytes differ: {relative_path}")
    return digest


def _frozen_scientific_pricing(*, expected_freeze_sha256: str) -> dict[str, Any]:
    """Load exact pricing only after binding its current bytes to the freeze."""

    relative_path = "configs/trimem_v1/cost_plan.json"
    expected_digest = _frozen_current_file_sha256(
        relative_path, expected_freeze_sha256=expected_freeze_sha256
    )
    path = ROOT / relative_path
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicArtifactError("frozen scientific pricing is unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != expected_digest or not isinstance(value, Mapping):
        raise PublicArtifactError("frozen scientific pricing bytes changed during validation")
    pricing = value.get("model_pricing")
    fields = {
        "cached_input_per_million_tokens_usd",
        "input_per_million_tokens_usd",
        "model_id",
        "output_per_million_tokens_usd",
        "source_url",
    }
    if not isinstance(pricing, Mapping) or set(pricing) != fields:
        raise PublicArtifactError("frozen scientific pricing field set differs")
    try:
        rates_are_invalid = any(
            not isinstance(pricing.get(field), (int, float))
            or isinstance(pricing.get(field), bool)
            or not Decimal(str(pricing[field])).is_finite()
            or Decimal(str(pricing[field])) < 0
            for field in (
                "cached_input_per_million_tokens_usd",
                "input_per_million_tokens_usd",
                "output_per_million_tokens_usd",
            )
        )
    except InvalidOperation:
        rates_are_invalid = True
    if rates_are_invalid or any(
        not isinstance(pricing.get(field), str) or not pricing[field]
        for field in ("model_id", "source_url")
    ):
        raise PublicArtifactError("frozen scientific pricing values are malformed")
    return dict(pricing)


def _is_forbidden_public_key(value: object) -> bool:
    if not isinstance(value, str):
        return True
    folded = value.casefold()
    if folded in {key.casefold() for key in FORBIDDEN_KEYS}:
        return True
    if folded in RAW_MULTI_SWE_KEYS:
        return True
    # These exact count/digest/boolean fields are the sole name-free category
    # projection emitted by the shared semantics helper.
    if folded in PUBLIC_SUMMARY_FIELDS:
        return False
    if folded in PRIVATE_FAILURE_KEYS or folded.endswith("_failure_reason"):
        return True
    if any(category in folded for category in ("p2p", "f2p", "s2p", "n2p")):
        return True
    if "test_name" in folded or folded.endswith("_test_ids"):
        return True
    if folded.startswith("missing_") and any(
        token in folded for token in ("test", "name", "transition")
    ):
        return True
    return False


def _reject_forbidden(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(
            str(key)
            for key, child in value.items()
            if _is_forbidden_public_key(key)
            and not (
                path == ("evidence_counts",)
                and key == "patch"
                and type(child) is int
                and child >= 0
            )
        )
        if forbidden:
            raise PublicArtifactError(
                f"public artifact contains forbidden keys: {forbidden}"
            )
        for key, child in value.items():
            _reject_forbidden(child, path=(*path, str(key)))
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden(child, path=path)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def validate_public_development_selection(
    aggregate: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the aggregate-bound selection trace and restricted artifact hashes."""

    evidence = aggregate.get("development_selection")
    digest = aggregate.get("development_selection_sha256")
    selected_candidate_id = aggregate.get("selected_candidate_id")
    restricted_hashes = aggregate.get("restricted_selection_artifact_hashes")
    if (
        not isinstance(evidence, dict)
        or set(evidence)
        != {
            "schema",
            "status",
            "candidate_bundle_sha256",
            "candidate_summaries",
            "selection",
        }
        or evidence.get("schema")
        != "trimem/development-m2-selection-evidence/1.0"
        or evidence.get("status")
        != "COMPLETE_PENDING_COMMIT_FREEZE_AND_HELDOUT_APPROVAL"
        or not isinstance(evidence.get("candidate_bundle_sha256"), str)
        or evidence.get("candidate_bundle_sha256")
        != "sha256:" + hashlib.sha256(
            _canonical(load_m2_candidate_bundle())
        ).hexdigest()
    ):
        raise PublicArtifactError("development selection evidence is malformed")
    candidate_fields = {
        "candidate_id",
        "completed_target_count",
        "final_resume_cursor",
        "resolved_count",
        "actual_total_tokens",
        "actual_usd",
        "sequence_sha256",
        "runtime_lock_sha256",
        "m2_policy_manifest_sha256",
        "checkpoint_source_path",
        "checkpoint_source_file_sha256",
        "checkpoint_digest",
        "namespace",
    }
    candidate_summaries = evidence.get("candidate_summaries")
    if (
        not isinstance(candidate_summaries, list)
        or len(candidate_summaries) != 4
        or any(
            not isinstance(row, dict) or set(row) != candidate_fields
            for row in candidate_summaries
        )
    ):
        raise PublicArtifactError("development selection candidate field set differs")
    if (
        not isinstance(digest, str)
        or SHA256.fullmatch(digest) is None
        or hashlib.sha256(_canonical(evidence)).hexdigest() != digest
    ):
        raise PublicArtifactError("development selection evidence hash differs")
    try:
        recalculated = select_development_candidate(
            candidate_summaries
        )
    except CandidateContractError as exc:
        raise PublicArtifactError(str(exc)) from None
    if evidence.get("selection") != recalculated:
        raise PublicArtifactError("development selection trace is not deterministic")
    if selected_candidate_id != recalculated.get("selected_candidate_id"):
        raise PublicArtifactError("aggregate selected M2 candidate differs from trace")
    expected_hash_names = {
        "development_selection_evidence_sha256",
        "selected_m2_checkpoint_sha256",
        "selected_m2_proposal_sha256",
    }
    if (
        not isinstance(restricted_hashes, dict)
        or set(restricted_hashes) != expected_hash_names
        or any(
            not isinstance(value, str) or SHA256.fullmatch(value) is None
            for value in restricted_hashes.values()
        )
    ):
        raise PublicArtifactError("restricted DEV selection artifact hashes are malformed")
    _reject_forbidden(evidence)
    return {
        "development_selection": evidence,
        "development_selection_sha256": digest,
        "restricted_selection_artifact_hashes": restricted_hashes,
        "selected_candidate_id": selected_candidate_id,
    }


def _scientific_usd(
    accounting: Mapping[str, int], pricing: Mapping[str, Any], *, uncached: bool = False
) -> str:
    try:
        cached = int(accounting["cached_input_tokens"])
        total_input = int(accounting["input_tokens"])
        output = int(accounting["output_tokens"])
        if cached < 0 or total_input < cached or output < 0:
            raise ValueError
        cached_rate = (
            pricing["input_per_million_tokens_usd"]
            if uncached
            else pricing["cached_input_per_million_tokens_usd"]
        )
        value = (
            Decimal(total_input - cached)
            * Decimal(str(pricing["input_per_million_tokens_usd"]))
            + Decimal(cached) * Decimal(str(cached_rate))
            + Decimal(output)
            * Decimal(str(pricing["output_per_million_tokens_usd"]))
        ) / Decimal(1_000_000)
    except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
        raise PublicArtifactError("scientific USD inputs are malformed") from exc
    return format(value, ".12f")


def _validate_scientific_accounting(
    value: Any, *, task_count: int, arm: str | None = None
) -> dict[str, int]:
    if (
        not isinstance(value, Mapping)
        or set(value) != set(SCIENTIFIC_ACCOUNTING_FIELDS)
        or type(task_count) is not int
        or task_count <= 0
        or any(
            type(value[field]) is not int or value[field] < 0
            for field in SCIENTIFIC_ACCOUNTING_FIELDS
        )
    ):
        raise PublicArtifactError("scientific actual accounting schema is malformed")
    result = {field: int(value[field]) for field in SCIENTIFIC_ACCOUNTING_FIELDS}
    if (
        result["cached_input_tokens"] > result["input_tokens"]
        or result["reasoning_tokens"] > result["output_tokens"]
        or result["output_tokens"]
        != sum(
            result[field]
            for field in (
                "actual_decomposition_output_tokens",
                "actual_solve_output_tokens",
                "actual_extraction_output_tokens",
            )
        )
        or result["solve_output_pool_capacity"] != 49_152 * task_count
        or result["remaining_solve_output_tokens"]
        != result["solve_output_pool_capacity"] - result["actual_solve_output_tokens"]
        or result["decomposition_calls"] != task_count
        or result["extraction_calls"] != task_count
        or result["solve_calls"] > 24 * task_count
        or result["model_gateway_calls"]
        != result["solve_calls"]
        + result["decomposition_calls"]
        + result["extraction_calls"]
        or result["paid_model_calls"] != result["model_gateway_calls"]
        or any(
            result[field] != task_count
            for field in ("grader_calls", "grader_containers", "official_grader_runs")
        )
    ):
        raise PublicArtifactError("scientific actual accounting arithmetic differs")
    return result


def _validate_scientific_memory(value: Any, *, arm: str) -> dict[str, int]:
    if (
        not isinstance(value, Mapping)
        or set(value) != set(SCIENTIFIC_MEMORY_FIELDS)
        or any(type(value[field]) is not int for field in SCIENTIFIC_MEMORY_FIELDS)
        or any(
            value[field] < 0
            for field in SCIENTIFIC_MEMORY_FIELDS
            if field != "net_memory_growth"
        )
    ):
        raise PublicArtifactError("scientific memory accounting schema is malformed")
    result = {field: int(value[field]) for field in SCIENTIFIC_MEMORY_FIELDS}
    if (
        result["injected_records"]
        != result["episodic_injections"]
        + result["user_semantic_injections"]
        + result["org_semantic_injections"]
        or result["net_memory_growth"]
        != result["retained_records"] - result["archived_records"]
        or (
            arm == "M0"
            and any(
                result[field]
                for field in (
                    "injected_records",
                    "retained_records",
                    "archived_records",
                    "net_memory_growth",
                )
            )
        )
    ):
        raise PublicArtifactError("scientific memory accounting arithmetic differs")
    return result


def _validate_provider_outcomes(
    value: Any, *, accounting: Mapping[str, int] | None = None
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != PROVIDER_OUTCOME_FIELDS:
        raise PublicArtifactError("scientific provider outcome field set differs")
    distribution = value.get("provider_status_distribution")
    usage = value.get("provider_reported_usage")
    reservation = value.get("ledger_reservation")
    if (
        not isinstance(distribution, Mapping)
        or not distribution
        or any(
            not isinstance(name, str)
            or (name != "SUCCESS" and not is_scientific_gateway_failure(name))
            or type(count) is not int
            or count <= 0
            for name, count in distribution.items()
        )
        or not isinstance(usage, Mapping)
        or set(usage) != {*PROVIDER_USAGE_FIELDS, "complete"}
        or type(usage.get("complete")) is not bool
        or any(type(usage[field]) is not int or usage[field] < 0 for field in PROVIDER_USAGE_FIELDS)
        or not isinstance(reservation, Mapping)
        or set(reservation) != set(PROVIDER_RESERVATION_FIELDS)
        or any(
            type(reservation[field]) is not int or reservation[field] < 0
            for field in PROVIDER_RESERVATION_FIELDS
        )
        or any(
            type(value.get(field)) is not int or value[field] < 0
            for field in (
                "incomplete_count",
                "refusal_count",
                "structured_output_schema_failure_count",
            )
        )
    ):
        raise PublicArtifactError("scientific provider outcome schema is malformed")
    call_count = sum(distribution.values())
    expected_incomplete = sum(
        count
        for name, count in distribution.items()
        if name.startswith("RESPONSE_INCOMPLETE")
    )
    if (
        value["incomplete_count"] != expected_incomplete
        or value["refusal_count"] != distribution.get("RESPONSE_REFUSAL", 0)
        or value["structured_output_schema_failure_count"]
        != distribution.get("STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0)
        or usage["available_calls"] + usage["unavailable_calls"] != call_count
        or usage["complete"] is not (usage["unavailable_calls"] == 0)
        or usage["cached_input_tokens"] > usage["input_tokens"]
        or usage["reasoning_tokens"] > usage["output_tokens"]
        or reservation["calls"] != call_count
        or reservation["conservatively_charged_calls"] != usage["unavailable_calls"]
        or reservation["input_upper_bound"] < usage["input_tokens"]
        or reservation["output_cap"] < usage["output_tokens"]
    ):
        raise PublicArtifactError("scientific provider outcome arithmetic differs")
    if accounting is not None:
        if (
            call_count != accounting["model_gateway_calls"]
            or reservation["input_upper_bound"] < accounting["input_tokens"]
            or reservation["output_cap"] < accounting["output_tokens"]
        ):
            raise PublicArtifactError(
                "scientific provider/accounting call or reservation totals differ"
            )
        reported = {
            field: usage[field]
            for field in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_tokens",
            )
        }
        if usage["complete"]:
            if any(reported[field] != accounting[field] for field in reported):
                raise PublicArtifactError(
                    "complete provider usage differs from scientific accounting"
                )
        elif any(reported[field] > accounting[field] for field in reported):
            raise PublicArtifactError(
                "partial provider usage exceeds scientific accounting"
            )
    return {
        "provider_status_distribution": dict(sorted(distribution.items())),
        "incomplete_count": int(value["incomplete_count"]),
        "refusal_count": int(value["refusal_count"]),
        "structured_output_schema_failure_count": int(
            value["structured_output_schema_failure_count"]
        ),
        "provider_reported_usage": {
            field: usage[field] for field in (*PROVIDER_USAGE_FIELDS, "complete")
        },
        "ledger_reservation": {
            field: reservation[field] for field in PROVIDER_RESERVATION_FIELDS
        },
    }


def _sum_integer_projections(
    rows: list[Mapping[str, int]], fields: tuple[str, ...]
) -> dict[str, int]:
    return {field: sum(row[field] for row in rows) for field in fields}


def _combine_provider_outcomes(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    usage = {field: 0 for field in PROVIDER_USAGE_FIELDS}
    reservation = {field: 0 for field in PROVIDER_RESERVATION_FIELDS}
    for row in rows:
        for name, count in row["provider_status_distribution"].items():
            statuses[name] = statuses.get(name, 0) + count
        for field in PROVIDER_USAGE_FIELDS:
            usage[field] += row["provider_reported_usage"][field]
        for field in PROVIDER_RESERVATION_FIELDS:
            reservation[field] += row["ledger_reservation"][field]
    return {
        "provider_status_distribution": dict(sorted(statuses.items())),
        "incomplete_count": sum(
            count for name, count in statuses.items() if name.startswith("RESPONSE_INCOMPLETE")
        ),
        "refusal_count": statuses.get("RESPONSE_REFUSAL", 0),
        "structured_output_schema_failure_count": statuses.get(
            "STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0
        ),
        "provider_reported_usage": {
            **usage,
            "complete": usage["unavailable_calls"] == 0,
        },
        "ledger_reservation": reservation,
    }


def _validate_terminal_distribution_semantics(
    value: Mapping[str, Any], *, label: str
) -> None:
    terminal_count = value["terminal_result_count"]
    contained_count = value["contained_failure_count"]
    cell_counts = value["cell_status_counts"]
    failure_counts = value["model_failure_class_counts"]
    agent_count = int(cell_counts.get("AGENT_COMPLETED", 0))
    cell_failure_count = int(cell_counts.get("CELL_SCIENTIFIC_FAILURE", 0))
    extraction_cell_count = int(cell_counts.get("MEMORY_EXTRACTION_FAILED", 0))
    none_count = int(failure_counts.get("NONE", 0))
    partial_count = value["model_partial_patch_count"]
    noop_count = value["canonical_failed_cell_noop_count"]
    extraction_count = value["extraction_failure_count"]
    if (
        none_count != agent_count
        or sum(
            count for name, count in failure_counts.items() if name != "NONE"
        )
        != contained_count
        or contained_count != cell_failure_count + extraction_cell_count
        or partial_count > cell_failure_count
        or partial_count + noop_count < cell_failure_count
        or partial_count + noop_count > contained_count
        or extraction_count < extraction_cell_count
        or extraction_count > contained_count
        or terminal_count != agent_count + contained_count
    ):
        raise PublicArtifactError(f"scientific {label} semantic distributions differ")


def validate_public_scientific_terminal_summary(
    value: Any,
    *,
    outcomes: list[Any],
) -> dict[str, Any]:
    """Validate the aggregate's name-free scientific terminal projection."""

    fields = {
        "terminal_result_count",
        "resolved_count",
        "unresolved_count",
        "contained_failure_count",
        "cell_status_counts",
        "model_failure_class_counts",
        "model_partial_patch_count",
        "canonical_failed_cell_noop_count",
        "extraction_failure_count",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PublicArtifactError("scientific terminal summary field set differs")
    scalar_fields = fields - {"cell_status_counts", "model_failure_class_counts"}
    if any(type(value[field]) is not int or value[field] < 0 for field in scalar_fields):
        raise PublicArtifactError("scientific terminal summary counts are malformed")
    cell_counts = value["cell_status_counts"]
    failure_counts = value["model_failure_class_counts"]
    if (
        not isinstance(cell_counts, Mapping)
        or not cell_counts
        or set(cell_counts) - set(SCIENTIFIC_CELL_STATUSES)
        or any(type(count) is not int or count <= 0 for count in cell_counts.values())
        or not isinstance(failure_counts, Mapping)
        or not failure_counts
        or any(
            not isinstance(name, str)
            or not name
            or type(count) is not int
            or count <= 0
            for name, count in failure_counts.items()
        )
    ):
        raise PublicArtifactError("scientific terminal summary distributions are malformed")
    terminal_count = value["terminal_result_count"]
    resolved_count = sum(
        isinstance(row, Mapping) and row.get("resolved") is True for row in outcomes
    )
    if (
        terminal_count != len(outcomes)
        or value["resolved_count"] != resolved_count
        or value["unresolved_count"] != terminal_count - resolved_count
        or sum(cell_counts.values()) != terminal_count
        or sum(failure_counts.values()) != terminal_count
        or value["contained_failure_count"]
        != terminal_count - int(cell_counts.get("AGENT_COMPLETED", 0))
    ):
        raise PublicArtifactError("scientific terminal summary arithmetic differs")
    result = dict(value)
    _validate_terminal_distribution_semantics(result, label="terminal summary")
    _reject_forbidden(result)
    return result


def validate_public_scientific_terminal_contract(
    value: Any, *, expected_sha256: str
) -> dict[str, str]:
    fields = {
        "schema",
        "sha256",
        "execution_status",
        "ledger_terminal_status",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != fields
        or value.get("schema") != "trimem/scientific-terminal-contract/1.0"
        or not isinstance(value.get("sha256"), str)
        or SHA256.fullmatch(str(value["sha256"])) is None
        or value.get("sha256") != expected_sha256
        or value.get("execution_status") != "CELL_TERMINAL"
        or value.get("ledger_terminal_status") != "CELL_TERMINAL"
    ):
        raise PublicArtifactError("scientific terminal contract binding differs")
    return {field: str(value[field]) for field in sorted(fields)}


def validate_public_scientific_stream_totals(
    value: Any,
    *,
    outcomes: list[Any],
    arms: Any,
    terminal_summary: Mapping[str, Any],
    pricing: Mapping[str, Any],
    phase_budget: Any,
    global_provider_outcomes: Any,
) -> list[dict[str, Any]]:
    """Validate every per-stream terminal projection and its global sums."""

    fields = {
        "arm",
        "actual_accounting",
        "actual_memory_metrics",
        "provider_outcomes",
        "actual_usd",
        "identity_seed_digest",
        "reporting_scope",
        "resolved_count",
        "terminal_result_count",
        "cell_status_counts",
        "contained_failure_count",
        "model_failure_class_counts",
        "model_partial_patch_count",
        "canonical_failed_cell_noop_count",
        "extraction_failure_count",
    }
    if (
        not isinstance(value, list)
        or not isinstance(arms, list)
        or not arms
        or any(not isinstance(arm, str) or not arm for arm in arms)
        or len(set(arms)) != len(arms)
    ):
        raise PublicArtifactError("scientific stream totals/arms are malformed")
    outcomes_by_arm = {
        arm: [row for row in outcomes if isinstance(row, Mapping) and row.get("arm") == arm]
        for arm in arms
    }
    if sum(len(rows) for rows in outcomes_by_arm.values()) != len(outcomes):
        raise PublicArtifactError("scientific outcome arm is outside the frozen streams")
    identities = [
        (row.get("arm"), row.get("target_id"))
        for row in outcomes
        if isinstance(row, Mapping)
    ]
    if (
        len(identities) != len(outcomes)
        or any(
            not isinstance(row.get("target_id"), str)
            or not row["target_id"]
            or not isinstance(row.get("benchmark_id"), str)
            or not row["benchmark_id"]
            or row.get("benchmark_role") not in {"PRIMARY", "SECONDARY"}
            or type(row.get("resolved")) is not bool
            for row in outcomes
            if isinstance(row, Mapping)
        )
        or len(set(identities)) != len(identities)
    ):
        raise PublicArtifactError("scientific public outcome identity is malformed")

    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    all_accounting: list[Mapping[str, int]] = []
    all_provider_outcomes: list[Mapping[str, Any]] = []
    all_task_usd: list[Decimal] = []
    global_cell_counts: dict[str, int] = {}
    global_failure_counts: dict[str, int] = {}
    summed = {
        "terminal_result_count": 0,
        "resolved_count": 0,
        "contained_failure_count": 0,
        "model_partial_patch_count": 0,
        "canonical_failed_cell_noop_count": 0,
        "extraction_failure_count": 0,
    }
    for row in value:
        if not isinstance(row, Mapping) or set(row) != fields:
            raise PublicArtifactError("scientific stream total field set differs")
        arm = row.get("arm")
        if not isinstance(arm, str) or arm not in outcomes_by_arm or arm in seen:
            raise PublicArtifactError("scientific stream total arm set differs")
        seen.add(arm)
        if (
            row.get("reporting_scope") != "DESCRIPTIVE_POOLED_ALL_BENCHMARKS"
            or not isinstance(row.get("identity_seed_digest"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", row["identity_seed_digest"])
            is None
            or not isinstance(row.get("actual_usd"), str)
            or MONEY_12.fullmatch(row["actual_usd"]) is None
        ):
            raise PublicArtifactError("scientific stream metadata is malformed")
        scalar_names = tuple(summed)
        if any(type(row.get(name)) is not int or row[name] < 0 for name in scalar_names):
            raise PublicArtifactError("scientific stream counts are malformed")
        terminal_count = row["terminal_result_count"]
        cell_counts = row.get("cell_status_counts")
        failure_counts = row.get("model_failure_class_counts")
        if (
            terminal_count <= 0
            or terminal_count != len(outcomes_by_arm[arm])
            or row["resolved_count"]
            != sum(outcome.get("resolved") is True for outcome in outcomes_by_arm[arm])
            or not isinstance(cell_counts, Mapping)
            or not cell_counts
            or set(cell_counts) - set(SCIENTIFIC_CELL_STATUSES)
            or any(type(count) is not int or count <= 0 for count in cell_counts.values())
            or sum(cell_counts.values()) != terminal_count
            or row["contained_failure_count"]
            != terminal_count - int(cell_counts.get("AGENT_COMPLETED", 0))
            or not isinstance(failure_counts, Mapping)
            or not failure_counts
            or any(
                not isinstance(name, str)
                or not name
                or type(count) is not int
                or count <= 0
                for name, count in failure_counts.items()
            )
            or sum(failure_counts.values()) != terminal_count
        ):
            raise PublicArtifactError("scientific stream terminal arithmetic differs")
        _validate_terminal_distribution_semantics(row, label="stream")

        stream_accounting: list[Mapping[str, int]] = []
        stream_memory: list[Mapping[str, int]] = []
        stream_provider: list[Mapping[str, Any]] = []
        stream_task_usd: list[Decimal] = []
        for outcome in outcomes_by_arm[arm]:
            accounting = _validate_scientific_accounting(
                outcome.get("actual_accounting"), task_count=1, arm=arm
            )
            memory = _validate_scientific_memory(
                outcome.get("actual_memory_metrics"), arm=arm
            )
            provider = _validate_provider_outcomes(
                outcome.get("provider_outcomes"), accounting=accounting
            )
            actual_usd = outcome.get("actual_usd")
            if (
                not isinstance(actual_usd, str)
                or MONEY_12.fullmatch(actual_usd) is None
                or actual_usd != _scientific_usd(accounting, pricing)
            ):
                raise PublicArtifactError(
                    "scientific outcome USD differs from frozen pricing/accounting"
                )
            stream_accounting.append(accounting)
            stream_memory.append(memory)
            stream_provider.append(provider)
            stream_task_usd.append(Decimal(actual_usd))

        expected_accounting = _sum_integer_projections(
            stream_accounting, SCIENTIFIC_ACCOUNTING_FIELDS
        )
        expected_memory = _sum_integer_projections(
            stream_memory, SCIENTIFIC_MEMORY_FIELDS
        )
        expected_provider = _combine_provider_outcomes(stream_provider)
        validated_stream_accounting = _validate_scientific_accounting(
            row.get("actual_accounting"), task_count=terminal_count, arm=arm
        )
        validated_stream_memory = _validate_scientific_memory(
            row.get("actual_memory_metrics"), arm=arm
        )
        validated_stream_provider = _validate_provider_outcomes(
            row.get("provider_outcomes"), accounting=validated_stream_accounting
        )
        expected_usd = _scientific_usd(expected_accounting, pricing)
        if (
            validated_stream_accounting != expected_accounting
            or validated_stream_memory != expected_memory
            or validated_stream_provider != expected_provider
            or row["actual_usd"] != expected_usd
            or format(sum(stream_task_usd, Decimal(0)), ".12f") != expected_usd
        ):
            raise PublicArtifactError(
                "scientific task/stream accounting, provider, memory, or USD totals differ"
            )
        all_accounting.extend(stream_accounting)
        all_provider_outcomes.extend(stream_provider)
        all_task_usd.extend(stream_task_usd)
        for name, count in cell_counts.items():
            global_cell_counts[str(name)] = global_cell_counts.get(str(name), 0) + count
        for name, count in failure_counts.items():
            global_failure_counts[str(name)] = (
                global_failure_counts.get(str(name), 0) + count
            )
        for name in summed:
            summed[name] += row[name]
        projected.append(dict(row))

    if set(seen) != set(arms):
        raise PublicArtifactError("scientific stream totals are incomplete")
    expected_global = {
        **summed,
        "unresolved_count": summed["terminal_result_count"]
        - summed["resolved_count"],
        "cell_status_counts": dict(sorted(global_cell_counts.items())),
        "model_failure_class_counts": dict(sorted(global_failure_counts.items())),
    }
    if dict(terminal_summary) != expected_global:
        raise PublicArtifactError("scientific stream/global terminal totals differ")

    if (
        not isinstance(phase_budget, Mapping)
        or set(phase_budget) != SCIENTIFIC_PHASE_BUDGET_FIELDS
        or phase_budget.get("schema") != "trimem/verified-phase-budget/1.0"
        or phase_budget.get("status") != "PASS"
        or not isinstance(phase_budget.get("hard_cap"), Mapping)
    ):
        raise PublicArtifactError("scientific phase budget schema is malformed")
    expected_global_accounting = _sum_integer_projections(
        all_accounting, SCIENTIFIC_ACCOUNTING_FIELDS
    )
    validated_phase_accounting = _validate_scientific_accounting(
        phase_budget.get("actual_accounting"), task_count=len(outcomes)
    )
    expected_global_provider = _combine_provider_outcomes(all_provider_outcomes)
    validated_global_provider = _validate_provider_outcomes(
        global_provider_outcomes, accounting=validated_phase_accounting
    )
    expected_global_usd = _scientific_usd(expected_global_accounting, pricing)
    expected_uncached_usd = _scientific_usd(
        expected_global_accounting, pricing, uncached=True
    )
    if (
        validated_phase_accounting != expected_global_accounting
        or phase_budget.get("model_calls")
        != expected_global_accounting["model_gateway_calls"]
        or phase_budget.get("task_arm_runs") != len(outcomes)
        or phase_budget.get("total_usd") != expected_global_usd
        or phase_budget.get("uncached_token_cost_usd") != expected_uncached_usd
        or format(sum(all_task_usd, Decimal(0)), ".12f") != expected_global_usd
        or validated_global_provider != expected_global_provider
    ):
        raise PublicArtifactError(
            "scientific stream/global accounting, provider, or USD totals differ"
        )
    _reject_forbidden(projected)
    return projected


def _valid_multi_swe_semantic_summary(
    value: Any, *, resolved: object
) -> bool:
    """Validate through the one shared name-free semantics implementation."""

    if not isinstance(value, Mapping):
        return False
    try:
        summary = validate_public_semantics_summary(value)
    except MultiSWEReportSemanticsError:
        return False
    return summary["computed_resolved"] is resolved


def _valid_smoke_image_lifecycle(value: Any) -> bool:
    """Accept only the aggregate's fixed, name-free lifecycle projection."""

    return (
        isinstance(value, Mapping)
        and set(value)
        == {"actual", "event_count", "report_bytes", "report_sha256", "status"}
        and value.get("actual") == SMOKE_IMAGE_LIFECYCLE_ACTUAL
        and type(value.get("event_count")) is int
        and value["event_count"] == 14
        and type(value.get("report_bytes")) is int
        and value["report_bytes"] > 0
        and isinstance(value.get("report_sha256"), str)
        and SHA256.fullmatch(value["report_sha256"]) is not None
        and value.get("status") == "PASS"
    )


def _public_outcome_projection(
    outcomes: list[Any], *, manifest: str
) -> list[dict[str, Any]]:
    """Validate and reconstruct only the frozen public outcome shape."""

    fields = (
        SMOKE_OUTCOME_FIELDS
        if manifest == "grader-smoke"
        else BENCHMARK_OUTCOME_FIELDS
    )
    expected = set(fields)
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(outcomes):
        if not isinstance(row, Mapping) or set(row) != expected:
            raise PublicArtifactError(
                f"aggregate outcome {index} public field set differs"
            )
        projected.append({field: row[field] for field in fields})
    _reject_forbidden(projected)
    return projected


def _verified_aggregate(aggregate_path: Path) -> dict[str, Any]:
    aggregate = read_json(aggregate_path)
    # Stream totals are otherwise validated only after schema/phase routing.
    # Reject a nested private/raw stream channel before a stale phase label can
    # mask the confidentiality boundary. Outcome field-set errors retain their
    # established, more specific public-projection diagnostic below.
    _reject_forbidden(aggregate.get("stream_totals", []))
    digest = aggregate.get("aggregate_sha256")
    body = {key: value for key, value in aggregate.items() if key != "aggregate_sha256"}
    expected_aggregate_schema = (
        "trimem/verified-aggregate/1.0"
        if aggregate.get("manifest") == "grader-smoke"
        else "trimem/verified-aggregate/1.1"
    )
    if (
        aggregate.get("schema") != expected_aggregate_schema
        or aggregate.get("status") != "PASS"
        or not isinstance(digest, str)
        or not SHA256.fullmatch(digest)
        or hashlib.sha256(_canonical(body)).hexdigest() != digest
    ):
        raise PublicArtifactError("aggregate seal is invalid or has not passed")
    if aggregate.get("manifest") not in {"grader-smoke", "development", "heldout"}:
        raise PublicArtifactError("aggregate manifest is invalid")
    approval = aggregate.get("approval_binding")
    validated_approval = validate_public_approval_binding(
        approval,
        manifest=str(aggregate.get("manifest")),
    )
    outcomes = aggregate.get("outcomes")
    totals = aggregate.get("stream_totals", [])
    if not isinstance(outcomes, list) or not isinstance(totals, list):
        raise PublicArtifactError("aggregate public outcomes/totals are malformed")
    _public_outcome_projection(outcomes, manifest=aggregate["manifest"])
    if aggregate.get("manifest") in {"development", "heldout"}:
        pricing = _frozen_scientific_pricing(
            expected_freeze_sha256=validated_approval["freeze_sha256"]
        )
        contract_sha256 = _frozen_current_file_sha256(
            "src/enterprise_memory/trimem/scientific_terminal.py",
            expected_freeze_sha256=validated_approval["freeze_sha256"],
        )
        validate_public_scientific_terminal_contract(
            aggregate.get("scientific_terminal_contract"),
            expected_sha256=contract_sha256,
        )
        terminal_summary = validate_public_scientific_terminal_summary(
            aggregate.get("scientific_terminal_summary"),
            outcomes=outcomes,
        )
        totals = validate_public_scientific_stream_totals(
            totals,
            outcomes=outcomes,
            arms=aggregate.get("arms"),
            terminal_summary=terminal_summary,
            pricing=pricing,
            phase_budget=aggregate.get("phase_budget"),
            global_provider_outcomes=aggregate.get("provider_outcomes"),
        )
        benchmark_totals = aggregate.get("benchmark_totals")
        primary = aggregate.get("primary_endpoints")
        secondary = aggregate.get("secondary_endpoints")
        roles = aggregate.get("benchmark_roles")
        if not all(isinstance(value, list) for value in (
            benchmark_totals, primary, secondary, roles
        )):
            raise PublicArtifactError("aggregate benchmark endpoints are missing")
        if primary != [
            row for row in benchmark_totals
            if isinstance(row, dict) and row.get("reporting_role") == "PRIMARY"
        ] or secondary != [
            row for row in benchmark_totals
            if isinstance(row, dict) and row.get("reporting_role") == "SECONDARY"
        ]:
            raise PublicArtifactError("aggregate benchmark endpoint roles are inconsistent")
        if {row.get("benchmark_id") for row in primary if isinstance(row, dict)} != {
            "swebench_verified"
        }:
            raise PublicArtifactError("aggregate primary endpoint is not SWE-bench Verified")
        if aggregate.get("manifest") == "development":
            validate_public_development_selection(aggregate)
        elif any(
            field in aggregate
            for field in (
                "development_selection",
                "development_selection_sha256",
                "restricted_selection_artifact_hashes",
            )
        ):
            raise PublicArtifactError("HELDOUT aggregate contains DEV selection evidence")
    else:
        if totals != [] or any(
            field in aggregate
            for field in (
                "benchmark_roles",
                "benchmark_totals",
                "primary_endpoints",
                "secondary_endpoints",
            )
        ):
            raise PublicArtifactError(
                "grader-smoke aggregate contains non-smoke public projections"
            )
        expected_evidence_counts = {
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
        expected_evidence_counts["container_exit_status"] = 8
        smoke_target_ids = [
            row.get("target_id") for row in outcomes if isinstance(row, dict)
        ]
        smoke_outcomes_valid = (
            len(outcomes) == 12
            and len(smoke_target_ids) == 12
            and all(isinstance(target_id, str) and target_id for target_id in smoke_target_ids)
            and len(set(smoke_target_ids)) == 12
            and all(
                isinstance(row, dict)
                and row.get("patch_applied") is True
                and row.get("tests_executed") is True
                and row.get("digest_match") is True
                and row.get("submitted_patch_identity") is True
                and type(row.get("host_prepare_sh_access_count")) is int
                and row["host_prepare_sh_access_count"] == 0
                and type(row.get("source_image_build_count")) is int
                and row["source_image_build_count"] == 0
                and type(row.get("api_calls")) is int
                and row["api_calls"] == 0
                and isinstance(row.get("execution_contract_sha256"), str)
                and SHA256.fullmatch(row["execution_contract_sha256"]) is not None
                and isinstance(row.get("execution_control_sha256"), str)
                and SHA256.fullmatch(row["execution_control_sha256"]) is not None
                and isinstance(row.get("submitted_patch_identity_sha256"), str)
                and SHA256.fullmatch(row["submitted_patch_identity_sha256"])
                is not None
                and (
                    (
                        row.get("benchmark_id") == "swebench_verified"
                        and row.get("semantic_normalization") is None
                    )
                    or (
                        row.get("benchmark_id")
                        in {"multi_swe_bench_mini", "multi_swe_bench_flash"}
                        and _valid_multi_swe_semantic_summary(
                            row.get("semantic_normalization"),
                            resolved=row.get("resolved"),
                        )
                    )
                )
                and (
                    (
                        row.get("benchmark_id") == "swebench_verified"
                        and row.get("container_exit_status_code") is None
                        and row.get("container_exit_status_sha256") is None
                        and row.get("container_exit_acceptance") is None
                    )
                    or (
                        row.get("benchmark_id")
                        in {"multi_swe_bench_mini", "multi_swe_bench_flash"}
                        and type(row.get("container_exit_status_code")) is int
                        and 0 <= row["container_exit_status_code"] <= 255
                        and isinstance(row.get("container_exit_status_sha256"), str)
                        and SHA256.fullmatch(row["container_exit_status_sha256"])
                        is not None
                        and row.get("container_exit_acceptance")
                        in {
                            "ZERO_EXIT",
                            "NONZERO_ACCEPTED_AFTER_FULL_DOMAIN_UNRESOLVED_VALIDATION",
                        }
                        and (
                            row.get("resolved") is not True
                            or row["container_exit_status_code"] == 0
                        )
                    )
                )
                for row in outcomes
            )
        )
        if (
            aggregate.get("probe_counts") != {"GOLD": 6, "NOOP_BASELINE": 6}
            or aggregate.get("resolved_counts") != {"GOLD": 6, "NOOP_BASELINE": 0}
            or aggregate.get("unresolved_counts") != {"GOLD": 0, "NOOP_BASELINE": 6}
            or type(aggregate.get("patch_applied_count")) is not int
            or aggregate["patch_applied_count"] != 12
            or type(aggregate.get("tests_executed_count")) is not int
            or aggregate["tests_executed_count"] != 12
            or type(aggregate.get("digest_match_count")) is not int
            or aggregate["digest_match_count"] != 12
            or type(aggregate.get("submitted_patch_identity_count")) is not int
            or aggregate["submitted_patch_identity_count"] != 12
            or type(aggregate.get("host_prepare_sh_access_count")) is not int
            or aggregate["host_prepare_sh_access_count"] != 0
            or type(aggregate.get("source_image_build_count")) is not int
            or aggregate["source_image_build_count"] != 0
            or type(aggregate.get("container_exit_status_captured_count")) is not int
            or aggregate["container_exit_status_captured_count"] != 8
            or type(aggregate.get("container_exit_status_validated_count")) is not int
            or aggregate["container_exit_status_validated_count"] != 8
            or type(aggregate.get("resolved_container_zero_exit_count")) is not int
            or aggregate["resolved_container_zero_exit_count"] != 4
            or type(aggregate.get("attempted_cell_count")) is not int
            or aggregate["attempted_cell_count"] != 12
            or type(aggregate.get("terminal_record_count")) is not int
            or aggregate["terminal_record_count"] != 12
            or type(aggregate.get("official_execution_count")) is not int
            or aggregate["official_execution_count"] != 12
            or type(aggregate.get("complete_execution_evidence_count")) is not int
            or aggregate["complete_execution_evidence_count"] != 12
            or type(aggregate.get("adapter_normalized_count")) is not int
            or aggregate["adapter_normalized_count"] != 12
            or type(aggregate.get("authoritative_cell_count")) is not int
            or aggregate["authoritative_cell_count"] != 12
            or type(aggregate.get("unattempted_cell_count")) is not int
            or aggregate["unattempted_cell_count"] != 0
            or type(aggregate.get("api_calls")) is not int
            or aggregate["api_calls"] != 0
            or any(
                type(aggregate.get(field)) is not int
                or aggregate[field] != 0
                for field in SMOKE_FAILURE_TAXONOMY_FIELDS
            )
            or aggregate.get("empty_patch_ids") != []
            or _canonical(aggregate.get("evidence_counts"))
            != _canonical(expected_evidence_counts)
            or not smoke_outcomes_valid
            or _canonical(aggregate.get("actual_accounting"))
            != _canonical({
                field: 12
                if field in {
                    "grader_calls", "grader_containers", "official_grader_runs"
                }
                else 0
                for field in SMOKE_ACCOUNTING_FIELDS
            })
            or not _valid_smoke_image_lifecycle(aggregate.get("image_lifecycle"))
        ):
            raise PublicArtifactError("grader-smoke exact execution summary differs")
    aggregate["stream_totals"] = totals
    aggregate["approval_binding"] = validated_approval
    return aggregate


def package(aggregate_path: Path, output: Path) -> dict[str, Any]:
    aggregate = _verified_aggregate(aggregate_path)
    outcomes = _public_outcome_projection(
        aggregate["outcomes"], manifest=aggregate["manifest"]
    )
    result = {
        "schema": (
            "trimem/public-benchmark-artifact/1.0"
            if aggregate["manifest"] == "grader-smoke"
            else "trimem/public-benchmark-artifact/1.1"
        ),
        "status": "PASS",
        "verified_aggregate_sha256": aggregate["aggregate_sha256"],
        "manifest": aggregate["manifest"],
        "outcomes": outcomes,
        "stream_totals": aggregate.get("stream_totals", []),
        "approval_binding": aggregate["approval_binding"],
        "restricted_evidence": "ENCRYPTED_SEPARATE_ARTIFACT_NOT_PUBLIC",
        "dataset_rows_or_gold_test_payloads": "EXCLUDED_AND_EPHEMERAL_INPUTS_PURGED",
    }
    for field in (
        "benchmark_roles", "benchmark_totals", "primary_endpoints", "secondary_endpoints",
        "provider_outcomes", "scientific_terminal_contract",
        "scientific_terminal_summary",
    ):
        if field in aggregate:
            result[field] = aggregate[field]
    if aggregate["manifest"] == "development":
        result.update(validate_public_development_selection(aggregate))
    if aggregate["manifest"] == "grader-smoke":
        for field in (
            "actual_accounting", "api_calls", "digest_match_count", "empty_patch_ids",
            "container_exit_status_captured_count",
            "container_exit_status_validated_count",
            "evidence_counts", "expected_target_count", "image_lifecycle",
            "host_prepare_sh_access_count",
            "attempted_cell_count", "terminal_record_count",
            "official_execution_count",
            "complete_execution_evidence_count", "adapter_normalized_count",
            "authoritative_cell_count", "unattempted_cell_count",
            *SMOKE_FAILURE_TAXONOMY_FIELDS, "observed_target_count",
            "patch_applied_count", "probe_counts", "resolved_counts",
            "resolved_container_zero_exit_count",
            "source_image_build_count", "submitted_patch_identity_count",
            "tests_executed_count", "unresolved_counts",
        ):
            result[field] = aggregate[field]
    _reject_forbidden(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    output.write_bytes(raw)
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "records": len(aggregate["outcomes"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    # Retained temporarily for workflow/CLI compatibility. It is deliberately
    # never opened: public material is derived only from the sealed aggregate.
    parser.add_argument("--source", type=Path)
    parser.add_argument("--aggregate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = package(args.aggregate.resolve(), args.output.resolve())
        print(json.dumps({**summary, "status": "PASS"}, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
