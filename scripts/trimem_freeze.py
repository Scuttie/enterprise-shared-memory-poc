"""Build and verify the explicit TriMem V1 hash-linked freeze.

The freeze is intentionally an allowlist.  It never walks the working tree, so
build products, bytecode, and unrelated product artifacts cannot silently enter
the research seal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

# Keep this module importable by the hosted base-Python preflight.  These are
# immutable repository paths, not executable behavior; importing their owner
# modules here would transitively load the grader/runtime dependency graph.
PROBE_REQUEST_PATH = (
    "artifacts/trimem_v1/probe_requests/"
    "MULTI_SWE_VUE_IMAGE_PROBE_REQUEST_001.json"
)
PROBE_RESULT_PATH = (
    "artifacts/trimem_v1/probe_evidence/"
    "MULTI_SWE_VUE_IMAGE_PROBE_RESULT_001.json"
)
PROBE_RECEIPT_PATH = (
    "artifacts/trimem_v1/probe_evidence/"
    "MULTI_SWE_VUE_IMAGE_PROBE_RECEIPT_001.json"
)
P014_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/failure-receipt.json"
)
P014_EVIDENCE_INVENTORY_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/evidence-inventory.json"
)
OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/failure-receipt.json"
)
OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/evidence-inventory.json"
)


FREEZE_PATH = Path("artifacts/trimem_v1/freeze.json")
OFFICIAL_SMOKE_PUBLIC_RESULT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/public-results.json"
)
OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/attestation-subject.json"
)
OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH = (
    "artifacts/trimem_v1/grader_smoke_official/exec-005/attestation-bundle.json"
)
CONFIG_PATHS = (
    "configs/trimem_v1/arms.json",
    "configs/trimem_v1/benchmark_environment.in",
    "configs/trimem_v1/benchmark_environment.lock",
    "configs/trimem_v1/benchmark_environment_lock.json",
    "configs/trimem_v1/benchmark_exec_request.json",
    "configs/trimem_v1/cost_plan.json",
    "configs/trimem_v1/development_manifest.json",
    "configs/trimem_v1/gh_cli_lock.json",
    "configs/trimem_v1/grader_lock.json",
    "configs/trimem_v1/grader_smoke_manifest.json",
    "configs/trimem_v1/heldout_manifest.json",
    "configs/trimem_v1/m2_candidate_bundles.json",
    "configs/trimem_v1/m2_candidates/balanced.json",
    "configs/trimem_v1/m2_candidates/baseline.json",
    "configs/trimem_v1/m2_candidates/precision.json",
    "configs/trimem_v1/m2_candidates/recall.json",
    "configs/trimem_v1/m2_policy.json",
    "configs/trimem_v1/model_lock.json",
    "configs/trimem_v1/provider_output_schemas.json",
    "configs/trimem_v1/selected_m2.json",
    "configs/trimem_v1/selection_plan.json",
    "configs/trimem_v1/solve_output_budget_contract.json",
    "configs/trimem_v1/sigstore_trusted_root.jsonl",
    "configs/trimem_v1/smoke_attestation_policy.json",
    "configs/trimem_v1/tool_environment_lock.json",
)
ARTIFACT_PATHS = (
    "artifacts/trimem_v1/development_model_pricing_amendment.json",
    "artifacts/trimem_v1/development_runner_toolchain_amendment.json",
    "artifacts/trimem_v1/development_response_contract_amendment.json",
    "artifacts/trimem_v1/development_solve_execution_contract_amendment.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-004/solve-0005-output-shape-forensics.json",
    "artifacts/trimem_v1/solve_output_budget_contract_lock.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-001/preflight-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-002/protected-exec-gate-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-003/model-parser-failure-receipt.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-003/provider-observability-terminology-amendment.json",
    "artifacts/trimem_v1/development_tuning_exec/exec-004/provider-incomplete-max-output-tokens-receipt.json",
    "artifacts/trimem_v1/provider_output_schema_lock.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_001.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_002.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_003.json",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_004.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_002.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_003.json",
    "artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_004.json",
    "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json",
    "artifacts/trimem_v1/credential_free_e2e/dqn_frozen_checkpoint.json",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/checkpoints/source-json-extension-M2.json",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/checkpoints/source-json-extension-M2.sha256",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/checkpoints/target-yaml-extension-M2.json",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/checkpoints/target-yaml-extension-M2.sha256",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/grader_image_lock.json",
    "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json",
    "artifacts/trimem_v1/multi_swe_report_semantics_lock.json",
    "artifacts/trimem_v1/adapter_failure_envelope_contract.json",
    P014_FAILURE_RECEIPT_PATH,
    P014_EVIDENCE_INVENTORY_PATH,
    "artifacts/trimem_v1/benchmark_environment_protection.json",
    "artifacts/trimem_v1/grader_smoke_environment_protection.json",
    "artifacts/trimem_v1/grader_smoke_result.json",
    "artifacts/trimem_v1/noop_baseline_six_commit_audit.json",
    "artifacts/trimem_v1/readiness_requirements.json",
    "artifacts/trimem_v1/upstream_source_audit.json",
)
SCRIPT_PATHS = (
    "scripts/run_trimem_replay_e2e.py",
    "scripts/trimem_atomic_evidence.py",
    "scripts/trimem_approved_phase.py",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_cleanup_exec.py",
    "scripts/trimem_development_trigger_preflight.py",
    "scripts/trimem_evidence_inventory.py",
    "scripts/trimem_exec_approval.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_grader_smoke.py",
    "scripts/trimem_grader_smoke_authority.py",
    "scripts/trimem_grader_smoke_failure_closure.py",
    "scripts/trimem_grader_smoke_failure_evidence.py",
    "scripts/trimem_grader_smoke_finalization.py",
    "scripts/trimem_grader_smoke_stage_evidence.py",
    "scripts/trimem_grader_smoke_protocol.py",
    "scripts/trimem_grader_smoke_trigger_preflight.py",
    "scripts/trimem_harness_lock.py",
    "scripts/trimem_install_pinned_gh.py",
    "scripts/trimem_m2_candidates.py",
    "scripts/trimem_multi_swe_contract.py",
    "scripts/trimem_multi_swe_entrypoint.py",
    "scripts/trimem_multi_swe_image_probe.py",
    "scripts/trimem_multi_swe_probe_evidence.py",
    "scripts/trimem_multi_swe_probe_request.py",
    "scripts/trimem_multi_swe_preexec.py",
    "scripts/trimem_multi_swe_report_semantics.py",
    "scripts/trimem_official_grader.py",
    "scripts/trimem_public_artifact.py",
    "scripts/trimem_pull_locked_images.py",
    "scripts/trimem_provider_output_contract.py",
    "scripts/trimem_pytest_no_skip.py",
    "scripts/trimem_run_with_resume.py",
    "scripts/trimem_select_targets.py",
    "scripts/trimem_smoke_attestation.py",
    "scripts/trimem_verify_credential_free.py",
    "scripts/trimem_verify_gh_lock.py",
    "scripts/trimem_verify_ready.py",
)
SOURCE_PATHS = (
    "src/enterprise_memory/contracts/codec.py",
    "src/enterprise_memory/contracts/schema.py",
    "src/enterprise_memory/indexing/canonical_loaders.py",
    "src/enterprise_memory/indexing/__init__.py",
    "src/enterprise_memory/indexing/drift.py",
    "src/enterprise_memory/indexing/embeddings.py",
    "src/enterprise_memory/indexing/index_worker.py",
    "src/enterprise_memory/indexing/models.py",
    "src/enterprise_memory/indexing/projection.py",
    "src/enterprise_memory/indexing/qdrant_indexes.py",
    "src/enterprise_memory/indexing/reindex.py",
    "src/enterprise_memory/indexing/validated_search.py",
    "src/enterprise_memory/persistence/__init__.py",
    "src/enterprise_memory/persistence/postgres/__init__.py",
    "src/enterprise_memory/persistence/postgres/repos.py",
    "src/enterprise_memory/persistence/tenant_context.py",
    "src/enterprise_memory/promotion/security_scan.py",
    "src/enterprise_memory/providers/__init__.py",
    "src/enterprise_memory/providers/base.py",
    "src/enterprise_memory/providers/openai_responses.py",
    "src/enterprise_memory/providers/redaction.py",
    "src/enterprise_memory/service/durable.py",
    "src/enterprise_memory/service/__init__.py",
    "src/enterprise_memory/service/injection.py",
    "src/enterprise_memory/service/private_view.py",
    "src/enterprise_memory/trimem/__init__.py",
    "src/enterprise_memory/trimem/accounting.py",
    "src/enterprise_memory/trimem/agent_runtime.py",
    "src/enterprise_memory/trimem/arms.py",
    "src/enterprise_memory/trimem/benchmark_seed.py",
    "src/enterprise_memory/trimem/checkpoint.py",
    "src/enterprise_memory/trimem/consolidation.py",
    "src/enterprise_memory/trimem/credential_free.py",
    "src/enterprise_memory/trimem/gateway.py",
    "src/enterprise_memory/trimem/git_workspace.py",
    "src/enterprise_memory/trimem/grader.py",
    "src/enterprise_memory/trimem/lifecycle.py",
    "src/enterprise_memory/trimem/policy.py",
    "src/enterprise_memory/trimem/postgres_retrieval.py",
    "src/enterprise_memory/trimem/postgres_store.py",
    "src/enterprise_memory/trimem/ppr.py",
    "src/enterprise_memory/trimem/provider_output_contracts.py",
    "src/enterprise_memory/trimem/production_lifecycle.py",
    "src/enterprise_memory/trimem/production_promotion.py",
    "src/enterprise_memory/trimem/production_runtime.py",
    "src/enterprise_memory/trimem/production_v03_lifecycle.py",
    "src/enterprise_memory/trimem/retrieval.py",
    "src/enterprise_memory/trimem/retrieval_store.py",
    "src/enterprise_memory/trimem/runtime_lock.py",
    "src/enterprise_memory/trimem/schema.py",
    "src/enterprise_memory/trimem/solve_forensics.py",
    "src/enterprise_memory/trimem/store.py",
    "src/enterprise_memory/trimem/vector_index.py",
    "src/enterprise_memory/trimem/working_graph.py",
    "src/enterprise_memory/trimem/workspace.py",
)
MIGRATION_PATHS = (
    "migrations/env.py",
    "migrations/script.py.mako",
    "migrations/versions/0001_initial_production_schema.py",
    "migrations/versions/0002_p1_hardening.py",
    "migrations/versions/0003_canonical_and_dispatch_integrity.py",
    "migrations/versions/0004_index_worker_and_lease.py",
    "migrations/versions/0005_lease_invariants.py",
    "migrations/versions/0006_index_audit_and_heartbeat.py",
    "migrations/versions/0007_artifact_lifecycle.py",
    "migrations/versions/0008_solve_job_snapshot.py",
    "migrations/versions/0009_injection_provenance.py",
    "migrations/versions/0010_idempotent_terminal.py",
    "migrations/versions/0011_task_policy_expansion.py",
    "migrations/versions/0012_experiment_arm.py",
    "migrations/versions/0013_job_patches.py",
    "migrations/versions/0014_experience_memory.py",
    "migrations/versions/0015_trimem_graph_memory.py",
    *(f"migrations/sql/{revision:04d}_up.sql" for revision in range(1, 16)),
    *(f"migrations/sql/{revision:04d}_up.sha256" for revision in range(1, 16)),
)
TEST_PATHS = (
    "tests/trimem/e2e/test_full_replay.py",
    "tests/trimem/test_real_services_e2e.py",
    "tests/unit/test_trimem_atomic_evidence.py",
    "tests/unit/test_trimem_accounting_checkpoint.py",
    "tests/unit/test_trimem_benchmark_checkpoint_recovery.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_d14_solve_contract.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
    "tests/unit/test_trimem_grader_smoke_trigger.py",
    "tests/unit/test_trimem_grader_smoke_authority.py",
    "tests/unit/test_trimem_grader_smoke_execution_accounting.py",
    "tests/unit/test_trimem_grader_smoke_failure_evidence.py",
    "tests/unit/test_trimem_grader_terminal_evidence.py",
    "tests/unit/test_trimem_harness_lock.py",
    "tests/unit/test_trimem_pinned_gh.py",
    "tests/unit/test_trimem_multi_prebuilt_evaluation.py",
    "tests/unit/test_trimem_multi_swe_entrypoint.py",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    "tests/unit/test_trimem_multi_swe_image_probe.py",
    "tests/unit/test_trimem_multi_swe_probe_evidence.py",
    "tests/unit/test_trimem_multi_swe_probe_request.py",
    "tests/unit/test_trimem_multi_swe_preexec.py",
    "tests/unit/test_trimem_multi_swe_report_semantics.py",
    "tests/unit/test_trimem_p015_production_semantics_path.py",
    "tests/unit/test_trimem_git_workspace.py",
    "tests/unit/test_trimem_m1_postwrite_recovery.py",
    "tests/unit/test_trimem_policy_consolidation.py",
    "tests/unit/test_trimem_postgres_retrieval.py",
    "tests/unit/test_trimem_postgres_store.py",
    "tests/unit/test_trimem_production_lifecycle.py",
    "tests/unit/test_trimem_production_runtime.py",
    "tests/unit/test_trimem_production_storage_e2e.py",
    "tests/unit/test_trimem_retrieval_store.py",
    "tests/unit/test_trimem_runtime_boundaries.py",
    "tests/unit/test_trimem_schema_sql.py",
    "tests/unit/test_trimem_schema_store.py",
    "tests/unit/test_trimem_smoke_attestation_only.py",
    "tests/unit/test_trimem_vector_index.py",
    "tests/unit/test_trimem_working_retrieval.py",
)
WORKFLOW_PATHS = (
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/trimem-benchmark.yml",
    ".github/workflows/trimem-grader-smoke.yml",
)
FROZEN_PATHS = (
    ".gitattributes",
    ".gitignore",
    "alembic.ini",
    "DEPENDENCY_PROVENANCE.json",
    "docs/TRIMEM_V1_SYSTEM.md",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_001_PREFLIGHT_FAILURE.md",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_002_PROTECTED_GATE_FAILURE.md",
    "reports/TRIMEM_GRADER_SMOKE_EXEC_004_FAILURE.md",
    "reports/TRIMEM_MULTI_SWE_EVALUATION_CONTRACT.md",
    "reports/TRIMEM_MULTI_SWE_REPORT_SEMANTICS.md",
    "reports/TRIMEM_D14_SOLVE_0005_OUTPUT_SHAPE_FORENSICS.md",
    "pyproject.toml",
    "requirements.lock",
    "scripts/check_migration_head.py",
    "scripts/postgres_bootstrap.py",
    "scripts/postgres_bootstrap_roles.sql",
    "src/enterprise_memory/service/app.py",
    "tests/openai/test_openai_provider.py",
    "tests/openai/test_openai_response_outcomes.py",
    "tests/unit/test_release_hygiene.py",
    *CONFIG_PATHS,
    *ARTIFACT_PATHS,
    *SCRIPT_PATHS,
    *SOURCE_PATHS,
    *MIGRATION_PATHS,
    *TEST_PATHS,
    *WORKFLOW_PATHS,
)
POST_DEVELOPMENT_PATH_FIELDS = (
    "development_selection_evidence_path",
    "selected_checkpoint_path",
    "selected_full_policy_path",
)
OFFICIAL_SMOKE_EVIDENCE_PATH_FIELDS = {
    "attestation_bundle_path": OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
    "attestation_subject_path": OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
    "public_result_path": OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
    "evidence_inventory_path": OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
}
OFFICIAL_SMOKE_FAILURE_EVIDENCE_PATH_FIELDS = {
    "failure_receipt_path": OFFICIAL_SMOKE_FAILURE_RECEIPT_PATH,
    "evidence_inventory_path": OFFICIAL_SMOKE_EVIDENCE_INVENTORY_PATH,
}
EVIDENCE_EVENT_PATHS = (
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/evidence/events.ndjson",
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw: str, *, label: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key in {label}: {key}")
            value[key] = child
        return value
    return json.loads(raw, object_pairs_hook=reject_duplicate_keys)


def _safe_file(root: Path, relative: str) -> Path:
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError(f"unsafe freeze path: {relative}")
    target = (root / relative).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"freeze path escapes repository: {relative}")
    if target.is_symlink() or not target.is_file():
        raise ValueError(f"required regular file is missing: {relative}")
    return target


def referenced_blob_paths(root: Path) -> tuple[str, ...]:
    """Derive the blob allowlist only from hash-bound committed event streams."""

    references: dict[str, int] = {}

    def collect(value: Any, *, event_path: Path) -> None:
        if isinstance(value, dict):
            marker = {"sha256", "bytes", "media_type"}
            if marker <= set(value):
                blob_hash, size = value.get("sha256"), value.get("bytes")
                if (
                    not isinstance(blob_hash, str)
                    or len(blob_hash) != 64
                    or any(character not in "0123456789abcdef" for character in blob_hash)
                    or type(size) is not int
                    or size < 0
                    or not isinstance(value.get("media_type"), str)
                    or not value["media_type"]
                ):
                    raise ValueError(f"malformed evidence blob reference: {event_path}")
                relative = (event_path.parent / "blobs" / blob_hash).relative_to(root).as_posix()
                previous = references.setdefault(relative, size)
                if previous != size:
                    raise ValueError(f"conflicting evidence blob sizes: {blob_hash}")
            for child in value.values():
                collect(child, event_path=event_path)
        elif isinstance(value, list):
            for child in value:
                collect(child, event_path=event_path)

    for relative in EVIDENCE_EVENT_PATHS:
        path = _safe_file(root, relative)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line:
                continue
            row = strict_json(line, label=f"{relative}:{line_number}")
            collect(row, event_path=path)
    if not references:
        raise ValueError("credential-free event streams contain no blob references")
    for relative, size in references.items():
        path = _safe_file(root, relative)
        raw = path.read_bytes()
        expected_hash = path.name
        if len(raw) != size or sha256(raw) != expected_hash:
            raise ValueError(f"evidence blob content-address mismatch: {relative}")
    return tuple(sorted(references))


def conditional_probe_evidence_paths(root: Path) -> tuple[str, ...]:
    """Return the all-or-none post-probe freeze extension.

    The correction commit has no marker and the marker-only child deliberately
    keeps the correction freeze byte-for-byte.  Once a result or receipt is
    present, all three regular files are mandatory and become freeze inputs.
    """

    paths = (PROBE_REQUEST_PATH, PROBE_RESULT_PATH, PROBE_RECEIPT_PATH)
    present = tuple(
        (root / relative).exists() or (root / relative).is_symlink()
        for relative in paths
    )
    if present == (False, False, False) or present == (True, False, False):
        if present[0]:
            _safe_file(root, PROBE_REQUEST_PATH)
        return ()
    if present != (True, True, True):
        raise ValueError(
            "probe evidence freeze phase must be absent, marker-only, or the exact trio"
        )
    for relative in paths:
        _safe_file(root, relative)
    return paths


def frozen_paths(root: Path) -> tuple[str, ...]:
    """Return the closed allowlist for the current pre/post-development phase."""

    paths = [
        *FROZEN_PATHS,
        *referenced_blob_paths(root),
        *conditional_probe_evidence_paths(root),
    ]
    smoke_path = root / "artifacts/trimem_v1/grader_smoke_result.json"
    smoke = strict_json(
        smoke_path.read_text(encoding="utf-8"), label=smoke_path.as_posix()
    )
    if not isinstance(smoke, dict):
        raise ValueError("grader smoke result root is not an object")
    smoke_status = smoke.get("status")
    if smoke_status == "PASS":
        if "official_execution_failure_evidence" in smoke:
            raise ValueError(
                "passed grader smoke cannot claim official execution failure evidence"
            )
        evidence = smoke.get("official_execution_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("passed grader smoke lacks official execution evidence")
        for field, expected_path in OFFICIAL_SMOKE_EVIDENCE_PATH_FIELDS.items():
            if evidence.get(field) != expected_path:
                raise ValueError(f"passed grader smoke has noncanonical {field}")
            paths.append(expected_path)
    elif smoke_status == "FAIL":
        if "official_execution_evidence" in smoke:
            raise ValueError(
                "failed grader smoke cannot claim passed official execution evidence"
            )
        evidence = smoke.get("official_execution_failure_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("failed grader smoke lacks official execution failure evidence")
        for field, expected_path in OFFICIAL_SMOKE_FAILURE_EVIDENCE_PATH_FIELDS.items():
            if evidence.get(field) != expected_path:
                raise ValueError(f"failed grader smoke has noncanonical {field}")
            if expected_path not in paths:
                paths.append(expected_path)
        for relative in (
            OFFICIAL_SMOKE_PUBLIC_RESULT_PATH,
            OFFICIAL_SMOKE_ATTESTATION_SUBJECT_PATH,
            OFFICIAL_SMOKE_ATTESTATION_BUNDLE_PATH,
        ):
            target = root / relative
            if target.exists() or target.is_symlink():
                raise ValueError(
                    f"failed grader smoke cannot retain passed execution artifact: {relative}"
                )
    elif smoke_status in {
        "CORRECTION_IN_PROGRESS",
        "CORRECTION_READY_FOR_EXECUTION",
    }:
        if (
            "official_execution_evidence" in smoke
            or "official_execution_failure_evidence" in smoke
        ):
            raise ValueError(
                "pre-exec grader smoke cannot claim official execution evidence"
            )
    else:
        raise ValueError("grader smoke result has an unknown freeze phase")
    selected_path = root / "configs/trimem_v1/selected_m2.json"
    selected = strict_json(selected_path.read_text(encoding="utf-8"), label=selected_path.as_posix())
    if not isinstance(selected, dict):
        raise ValueError("selected M2 manifest root is not an object")
    status = selected.get("status")
    if status == "FROZEN_AFTER_DEVELOPMENT":
        for field in POST_DEVELOPMENT_PATH_FIELDS:
            relative = selected.get(field)
            if not isinstance(relative, str) or relative.startswith("PENDING"):
                raise ValueError(f"frozen selected M2 lacks exact path: {field}")
            paths.append(relative)
    elif status != "PRE_DEVELOPMENT":
        raise ValueError("selected M2 has an unknown freeze phase")
    if len(paths) != len(set(paths)):
        raise ValueError("freeze allowlist contains duplicate paths")
    return tuple(paths)


def build_freeze(root: Path) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}
    for relative in sorted(frozen_paths(root)):
        raw = _safe_file(root, relative).read_bytes()
        files[relative] = {"bytes": len(raw), "sha256": sha256(raw)}
    return {
        "files": files,
        "hash_algorithm": "sha256",
        "path_policy": (
            "explicit_allowlist_plus_hash_bound_event_blob_references_plus_"
            "conditional_probe_evidence_triad_no_tree_walk"
        ),
        "schema": "trimem/freeze/1.0",
    }


def git_untracked_frozen_paths(root: Path) -> list[str]:
    required = frozen_paths(root)
    completed = subprocess.run(
        ["git", "ls-files", "--", *required],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = {line.replace("\\", "/") for line in completed.stdout.splitlines() if line}
    return sorted(set(required) - tracked)


def check_freeze(root: Path, *, require_git_tracked: bool = False) -> dict[str, Any]:
    expected = build_freeze(root)
    path = root / FREEZE_PATH
    if not path.is_file():
        raise ValueError(f"missing freeze: {FREEZE_PATH.as_posix()}")
    try:
        observed = strict_json(path.read_text(encoding="utf-8"), label=FREEZE_PATH.as_posix())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("freeze is not valid UTF-8 JSON") from exc
    if observed != expected:
        expected_files = expected["files"]
        observed_files = observed.get("files", {}) if isinstance(observed, dict) else {}
        missing = sorted(set(expected_files) - set(observed_files))
        extra = sorted(set(observed_files) - set(expected_files))
        changed = sorted(
            path for path in set(expected_files) & set(observed_files) if expected_files[path] != observed_files[path]
        )
        raise ValueError(f"freeze mismatch: missing={missing}, extra={extra}, changed={changed}")
    if require_git_tracked:
        untracked = git_untracked_frozen_paths(root)
        if untracked:
            raise ValueError(f"frozen paths are not git-tracked: {untracked}")
        completed = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", FREEZE_PATH.as_posix()],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ValueError("freeze.json is not git-tracked")
    return expected


def write_freeze(root: Path) -> None:
    target = root / FREEZE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json(build_freeze(root))
    fd, temp_name = tempfile.mkstemp(prefix=".trimem-freeze-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--emit", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--require-git-tracked", action="store_true")
    args = parser.parse_args()
    root = repository_root()
    try:
        if args.emit:
            print(canonical_json(build_freeze(root)).decode("utf-8"), end="")
        elif args.write:
            write_freeze(root)
            print(f"wrote {FREEZE_PATH.as_posix()}")
        else:
            result = check_freeze(root, require_git_tracked=args.require_git_tracked)
            print(json.dumps({"files": len(result["files"]), "status": "PASS"}, sort_keys=True))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
