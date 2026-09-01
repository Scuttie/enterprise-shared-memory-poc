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


FREEZE_PATH = Path("artifacts/trimem_v1/freeze.json")
CONFIG_PATHS = (
    "configs/trimem_v1/arms.json",
    "configs/trimem_v1/benchmark_environment.in",
    "configs/trimem_v1/benchmark_environment.lock",
    "configs/trimem_v1/benchmark_environment_lock.json",
    "configs/trimem_v1/benchmark_exec_request.json",
    "configs/trimem_v1/cost_plan.json",
    "configs/trimem_v1/development_manifest.json",
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
    "configs/trimem_v1/selected_m2.json",
    "configs/trimem_v1/selection_plan.json",
    "configs/trimem_v1/tool_environment_lock.json",
)
ARTIFACT_PATHS = (
    "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json",
    "artifacts/trimem_v1/credential_free_e2e/dqn_frozen_checkpoint.json",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/checkpoints/source-json-extension-M2.json",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/checkpoints/source-json-extension-M2.sha256",
    "artifacts/trimem_v1/credential_free_e2e/source-json-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/checkpoints/target-yaml-extension-M2.json",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/checkpoints/target-yaml-extension-M2.sha256",
    "artifacts/trimem_v1/credential_free_e2e/target-yaml-extension/evidence/events.ndjson",
    "artifacts/trimem_v1/grader_image_lock.json",
    "artifacts/trimem_v1/grader_smoke_environment_protection.json",
    "artifacts/trimem_v1/grader_smoke_result.json",
    "artifacts/trimem_v1/noop_baseline_six_commit_audit.json",
    "artifacts/trimem_v1/readiness_requirements.json",
    "artifacts/trimem_v1/upstream_source_audit.json",
)
SCRIPT_PATHS = (
    "scripts/run_trimem_replay_e2e.py",
    "scripts/trimem_approved_phase.py",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_cleanup_exec.py",
    "scripts/trimem_evidence_inventory.py",
    "scripts/trimem_exec_approval.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_grader_smoke.py",
    "scripts/trimem_grader_smoke_protocol.py",
    "scripts/trimem_grader_smoke_trigger_preflight.py",
    "scripts/trimem_m2_candidates.py",
    "scripts/trimem_official_grader.py",
    "scripts/trimem_public_artifact.py",
    "scripts/trimem_pull_locked_images.py",
    "scripts/trimem_pytest_no_skip.py",
    "scripts/trimem_run_with_resume.py",
    "scripts/trimem_select_targets.py",
    "scripts/trimem_verify_credential_free.py",
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
    "src/enterprise_memory/trimem/production_lifecycle.py",
    "src/enterprise_memory/trimem/production_promotion.py",
    "src/enterprise_memory/trimem/production_runtime.py",
    "src/enterprise_memory/trimem/production_v03_lifecycle.py",
    "src/enterprise_memory/trimem/retrieval.py",
    "src/enterprise_memory/trimem/retrieval_store.py",
    "src/enterprise_memory/trimem/runtime_lock.py",
    "src/enterprise_memory/trimem/schema.py",
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
    "tests/unit/test_trimem_accounting_checkpoint.py",
    "tests/unit/test_trimem_benchmark_checkpoint_recovery.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_grader_smoke_trigger.py",
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
    "tests/unit/test_trimem_vector_index.py",
    "tests/unit/test_trimem_working_retrieval.py",
)
WORKFLOW_PATHS = (
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/trimem-benchmark.yml",
    ".github/workflows/trimem-grader-smoke.yml",
)
FROZEN_PATHS = (
    ".gitattributes",
    "alembic.ini",
    "DEPENDENCY_PROVENANCE.json",
    "docs/TRIMEM_V1_SYSTEM.md",
    "pyproject.toml",
    "requirements.lock",
    "scripts/check_migration_head.py",
    "scripts/postgres_bootstrap.py",
    "scripts/postgres_bootstrap_roles.sql",
    "src/enterprise_memory/service/app.py",
    "tests/openai/test_openai_provider.py",
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


def frozen_paths(root: Path) -> tuple[str, ...]:
    """Return the closed allowlist for the current pre/post-development phase."""

    paths = [*FROZEN_PATHS, *referenced_blob_paths(root)]
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
        "path_policy": "explicit_allowlist_plus_hash_bound_event_blob_references_no_tree_walk",
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
