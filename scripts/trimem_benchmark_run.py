"""Approved TriMem V1 benchmark orchestrator.

The command has no free-form instance selection.  It reads one committed split,
executes one complete arm stream serially, and refuses to start before the
approval binding, freeze, target rows, production services, model bridge,
workspace factory, grader images, and hard caps all verify.

Importing this module is credential-free.  The CLI is an EXEC path and must only
be invoked by the manual workflows after their fail-closed gate passes.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
import urllib.request
import uuid

from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from enterprise_memory.providers.openai_responses import (  # noqa: E402
    OpenAIResponsesProvider,
    RestrictedProviderResponseStore,
)
from enterprise_memory.trimem.accounting import RawEvidenceLedger, strict_json_loads  # noqa: E402
from enterprise_memory.trimem.agent_runtime import (  # noqa: E402
    AgentRunResult,
    CodingTask,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.benchmark_seed import seed_benchmark_identities  # noqa: E402
from enterprise_memory.trimem.checkpoint import (  # noqa: E402
    FileCheckpointStore,
    RuntimeCheckpoint,
)
from enterprise_memory.trimem.gateway import (  # noqa: E402
    AsyncProviderModelGateway,
    GatewayInvocationFailure,
    GatewayRequest,
    GatewayResponse,
)
from enterprise_memory.trimem.git_workspace import (  # noqa: E402
    DockerSandboxCommandRunner,
    GitCheckoutWorkspaceFactory,
)
from enterprise_memory.trimem.grader import (  # noqa: E402
    GradeRequest,
    GradeResult,
    GraderInvocationFailure,
)
from enterprise_memory.trimem.production_lifecycle import production_dqn_lifecycle_factory  # noqa: E402
from enterprise_memory.trimem.production_runtime import open_benchmark_arm  # noqa: E402
from enterprise_memory.trimem.production_v03_lifecycle import (  # noqa: E402
    production_v03_lifecycle_factory,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402
from enterprise_memory.trimem.schema import canonical_hash  # noqa: E402
from enterprise_memory.trimem.scientific_terminal import (  # noqa: E402
    SCIENTIFIC_CELL_STATUSES,
    SCIENTIFIC_EXECUTION_STATUS,
    SCIENTIFIC_LEDGER_TERMINAL_STATUS,
    SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES,
    ScientificTerminalContractError,
    canonical_scientific_failure_class,
    scientific_task_arm_key,
    validate_result_ledger_pair,
    validate_result_request_statuses,
    validate_scientific_terminal_result,
)
from trimem_benchmark_matrix import sequence_sha256  # noqa: E402
from trimem_harness_lock import prepare_harnesses  # noqa: E402
from trimem_m2_candidates import (  # noqa: E402
    CANDIDATE_IDS,
    candidate_row,
    load_bundle as load_m2_candidate_bundle,
    load_candidate_policy,
    runtime_lock_for,
    select_development_candidate,
    validate_selected_m2,
)
from trimem_official_grader import FrozenOfficialTarget, OfficialHarnessGraderGateway  # noqa: E402
from trimem_grader_smoke_trigger_preflight import (  # noqa: E402
    REQUEST_SCHEMA as GRADER_SMOKE_REQUEST_SCHEMA,
    SENTINEL_PATH as GRADER_SMOKE_SENTINEL_PATH,
    TriggerPreflightError,
    validate_request_document as validate_grader_smoke_request_document,
)
from trimem_development_trigger_d18 import (  # noqa: E402
    EXPECTED_WORKFLOW_REF as DEVELOPMENT_WORKFLOW_REF,
    SENTINEL_PATH as DEVELOPMENT_SENTINEL_PATH,
    DevelopmentTriggerError,
    validate_sentinel_commit as validate_development_sentinel_commit,
)
from trimem_exec_approval import (  # noqa: E402
    ApprovalValidationError,
    validate_external_approval_document,
)
from trimem_development_phase_cap import (  # noqa: E402
    DevelopmentPhaseCapError,
    PROTOCOL_CANARY_INPUT_RESERVATION,
    PROTOCOL_CANARY_OUTPUT_RESERVATION,
    scientific_cap_after_protocol_canary,
    validate_development_phase_hard_cap,
)


SHA256 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
ARMS = ("M0", "M1", "M2")
SPLITS = ("development", "heldout")
MANIFESTS = {
    "development": Path("configs/trimem_v1/development_manifest.json"),
    "heldout": Path("configs/trimem_v1/heldout_manifest.json"),
    "grader-smoke": Path("configs/trimem_v1/grader_smoke_manifest.json"),
}
PHASES = {
    "development": "DEVELOPMENT_TUNING",
    "heldout": "HELDOUT_BENCHMARK",
    "grader-smoke": "GRADER_SMOKE",
}
LEDGER_ACTUAL_FIELDS = (
    "paid_model_calls",
    "solve_calls",
    "decomposition_calls",
    "extraction_calls",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "total_usd",
    "task_arm_runs",
    "grader_containers",
)
LEDGER_OUTSTANDING_FIELDS = tuple(
    field for field in LEDGER_ACTUAL_FIELDS if field != "cached_input_tokens"
)
CALL_CAP_BY_KIND = {
    "solve": "solve_calls",
    "decompose": "decomposition_calls",
    "extract": "extraction_calls",
}
TASK_LEDGER_PROJECTION_FIELDS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "solve_calls",
    "decomposition_calls",
    "extraction_calls",
    "model_gateway_calls",
    "paid_model_calls",
    "total_usd",
)
TERMINAL_LEDGER_REQUEST_FIELDS = {
    "reservation_id",
    "status",
    "input_upper_bound",
    "output_cap",
    "reserved_usd",
    "task_arm_key",
    "call_kind",
    "call_cap_name",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "actual_usd",
}
TERMINAL_LEDGER_TASK_ARM_FIELDS = {
    "reservation_id",
    "status",
    "actual_input_tokens",
    "outstanding_input_tokens",
    "actual_model_calls",
    "outstanding_model_calls",
    "actual_output_tokens",
    "outstanding_output_tokens",
    "actual_decomposition_output_tokens",
    "actual_solve_output_tokens",
    "actual_extraction_output_tokens",
    "remaining_decomposition_output_tokens",
    "remaining_solve_output_tokens",
    "remaining_extraction_output_tokens",
    "container_started",
}
MAX_LEDGER_INPUT_BOUND_PER_CALL = 262_000
MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND = {
    "solve": 16_384,
    "decompose": 8_192,
    "extract": 8_192,
}
TASK_OUTPUT_POOL_BY_CALL_KIND = {
    "decompose": 8_192,
    "solve": 49_152,
    "extract": 8_192,
}
TASK_TOTAL_OUTPUT_POOL = 65_536
PROTOCOL_CANARY_RELATIVE_PATH = Path("control/protocol-action-canary.json")
TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND = {
    "decompose": "actual_decomposition_output_tokens",
    "solve": "actual_solve_output_tokens",
    "extract": "actual_extraction_output_tokens",
}
TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND = {
    "decompose": "remaining_decomposition_output_tokens",
    "solve": "remaining_solve_output_tokens",
    "extract": "remaining_extraction_output_tokens",
}
BENCHMARK_EXEC_REQUEST = Path("configs/trimem_v1/benchmark_exec_request.json")
GRADER_SMOKE_EXEC_REQUEST = Path(
    GRADER_SMOKE_SENTINEL_PATH
)
DEVELOPMENT_EXEC_REQUEST = Path(DEVELOPMENT_SENTINEL_PATH)
OFFICIAL_DATASET_URLS = {
    "swebench_verified": "https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified/resolve/{revision}/{path}",
    "multi_swe_bench_mini": "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench_mini/resolve/{revision}/{path}",
    "multi_swe_bench_flash": "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench-flash/resolve/{revision}/{path}",
}


class BenchmarkExecutionError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise BenchmarkExecutionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BenchmarkExecutionError(f"JSON root is not an object: {path}")
    return value


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0 or not HEX40.fullmatch(completed.stdout.strip()):
        raise BenchmarkExecutionError("cannot resolve exact Git HEAD")
    return completed.stdout.strip()


def validate_grader_smoke_sentinel(request_path: Path) -> dict[str, Any]:
    """Revalidate the full committed sentinel contract at the EXEC boundary."""

    request = read_json(request_path)
    expected_source_head = request.get("source_head")
    if not isinstance(expected_source_head, str) or HEX40.fullmatch(expected_source_head) is None:
        raise BenchmarkExecutionError("grader-smoke sentinel source_head is invalid")
    execution_head = git_head()
    if os.environ.get("GITHUB_EVENT_NAME") == "push":
        parents = subprocess.run(
            ["git", "rev-list", "--parents", "-n", "1", execution_head],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        parent_fields = parents.stdout.strip().split()
        if (
            parents.returncode != 0
            or parent_fields != [execution_head, expected_source_head]
        ):
            raise BenchmarkExecutionError(
                "grader-smoke push HEAD is not the exact one-parent sentinel commit"
            )
    try:
        return validate_grader_smoke_request_document(
            ROOT,
            request_path.read_bytes(),
            expected_source_head=expected_source_head,
            material_commit=execution_head,
        )
    except (ImportError, OSError, TriggerPreflightError) as exc:
        raise BenchmarkExecutionError(
            f"grader-smoke sentinel exact-content validation failed: {exc}"
        ) from None


def git_tracked(path: Path) -> None:
    relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    completed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0:
        raise BenchmarkExecutionError(f"required execution artifact is not git-tracked: {relative}")


def validate_benchmark_environment() -> dict[str, Any]:
    import importlib.metadata

    lock_path = ROOT / "configs/trimem_v1/benchmark_environment_lock.json"
    requirements_path = ROOT / "configs/trimem_v1/benchmark_environment.lock"
    input_path = ROOT / "configs/trimem_v1/benchmark_environment.in"
    for path in (lock_path, requirements_path, input_path):
        git_tracked(path)
    lock = read_json(lock_path)
    runner, dependency = lock.get("runner", {}), lock.get("dependency_lock", {})
    if runner != {
        "automatic_ci_runner_label": "ubuntu-24.04",
        "benchmark_exec_runner_labels": [
            "self-hosted", "linux", "x64", "ubuntu-24.04", "trimem-benchmark"
        ],
        "benchmark_exec_max_job_minutes": 7200,
        "benchmark_exec_runner_boundary": (
            "protected ephemeral self-hosted runner; one serial phase job owns PostgreSQL, "
            "Qdrant and the atomic global ledger"
        ),
        "operating_system": "linux", "architecture": "x86_64",
        "python_implementation": "CPython", "python_version": "3.11.10",
    }:
        raise BenchmarkExecutionError("benchmark runner lock is not exact")
    if platform.system().lower() != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        raise BenchmarkExecutionError("benchmark runner OS/architecture mismatch")
    if platform.python_implementation() != "CPython" or platform.python_version() != "3.11.10":
        raise BenchmarkExecutionError("benchmark CPython version mismatch")
    for path, field in ((requirements_path, "lock_sha256"), (input_path, "input_sha256")):
        if sha256_bytes(path.read_bytes()) != dependency.get(field):
            raise BenchmarkExecutionError(f"benchmark dependency {field} mismatch")
    expected_env = lock.get("embedding_execution", {}).get("environment", {})
    if not isinstance(expected_env, Mapping) or any(os.environ.get(key) != value for key, value in expected_env.items()):
        raise BenchmarkExecutionError("CPU/deterministic benchmark environment variables are not exact")
    for distribution, expected_version in lock.get("critical_versions", {}).items():
        try:
            observed = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise BenchmarkExecutionError(f"benchmark dependency is missing: {distribution}") from exc
        if observed != expected_version:
            raise BenchmarkExecutionError(f"benchmark dependency version mismatch: {distribution}")
    import torch
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    if not torch.are_deterministic_algorithms_enabled() or torch.cuda.is_available():
        raise BenchmarkExecutionError("benchmark embedder is not CPU-only deterministic")
    return lock


def validate_database_role_boundary(admin_database_url: str, runtime_database_url: str) -> None:
    try:
        admin = make_url(admin_database_url)
        runtime = make_url(runtime_database_url)
    except Exception as exc:
        raise BenchmarkExecutionError("benchmark database URLs are invalid") from exc
    if admin.drivername != "postgresql+asyncpg" or runtime.drivername != "postgresql+asyncpg":
        raise BenchmarkExecutionError("benchmark admin/runtime databases require postgresql+asyncpg")
    if runtime.username != "api_service" or admin.username in {
        None, "api_service", "worker_service", "index_worker_service"
    }:
        raise BenchmarkExecutionError("benchmark database roles are not admin/runtime separated")
    admin_endpoint = (admin.host, admin.port or 5432, admin.database)
    runtime_endpoint = (runtime.host, runtime.port or 5432, runtime.database)
    if admin_endpoint != runtime_endpoint:
        raise BenchmarkExecutionError("benchmark admin/runtime database endpoints differ")


def _iso_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def validate_exec_approval(split: str, approval_path: Path) -> dict[str, Any]:
    """Bind an external immutable approval to an already-frozen commit.

    The committed request deliberately remains PENDING.  Making that file
    APPROVED would change both HEAD and the freeze it was meant to approve, so
    an approval embedded in the freeze has no finite fixed point.  The manual
    workflow instead supplies a protected, immutable artifact outside the
    repository and this function binds every byte of it to the committed
    request, HEAD, freeze, phase, and caps.
    """
    if split == "heldout" and os.environ.get("GITHUB_EVENT_NAME") == "push":
        raise BenchmarkExecutionError(
            "benchmark branch push cannot route to HELDOUT_BENCHMARK"
        )
    policy_request_path = ROOT / BENCHMARK_EXEC_REQUEST
    request_path = {
        "grader-smoke": ROOT / GRADER_SMOKE_EXEC_REQUEST,
        "development": ROOT / DEVELOPMENT_EXEC_REQUEST,
        "heldout": policy_request_path,
    }[split]
    freeze_path = ROOT / "artifacts/trimem_v1/freeze.json"
    cost_path = ROOT / "configs/trimem_v1/cost_plan.json"
    for path in (
        policy_request_path,
        request_path,
        freeze_path,
        cost_path,
        ROOT / MANIFESTS[split],
    ):
        git_tracked(path)
    request = read_json(request_path)
    policy_request = read_json(policy_request_path)
    cost = read_json(cost_path)
    phase = PHASES[split]
    if policy_request.get("approval_state") != "PENDING_EXEC_APPROVAL":
        raise BenchmarkExecutionError("committed request must remain pending and immutable")
    phases = {
        row.get("phase"): row
        for row in policy_request.get("phases", ())
        if isinstance(row, dict)
    }
    if phases.get(phase, {}).get("status") != "PENDING_EXEC_APPROVAL":
        raise BenchmarkExecutionError(f"committed {phase} request is not pending")
    if split == "grader-smoke":
        if request.get("schema") != GRADER_SMOKE_REQUEST_SCHEMA:
            raise BenchmarkExecutionError("grader-smoke sentinel schema mismatch")
        if request.get("phase") != phase:
            raise BenchmarkExecutionError("grader-smoke sentinel phase mismatch")
        policy_hash = sha256_bytes(policy_request_path.read_bytes())
        if request.get("frozen_request_sha256") not in {
            policy_hash,
            "sha256:" + policy_hash,
        }:
            raise BenchmarkExecutionError(
                "grader-smoke sentinel does not bind the frozen execution policy"
            )
        validate_grader_smoke_sentinel(request_path)
    elif split == "development":
        if os.environ.get("GITHUB_EVENT_NAME") != "push":
            raise BenchmarkExecutionError(
                "one-time DEVELOPMENT_TUNING execution requires the exact sentinel push"
            )
        if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            raise BenchmarkExecutionError(
                "one-time DEVELOPMENT_TUNING execution requires workflow attempt 1"
            )
        if os.environ.get("GITHUB_WORKFLOW_REF") != DEVELOPMENT_WORKFLOW_REF:
            raise BenchmarkExecutionError(
                "DEVELOPMENT_TUNING approval is outside the exact branch workflow"
            )
        if os.environ.get("GITHUB_WORKFLOW_SHA") != git_head():
            raise BenchmarkExecutionError(
                "DEVELOPMENT_TUNING workflow source differs from execution HEAD"
            )
        try:
            validated_request = validate_development_sentinel_commit(
                ROOT,
                git_head(),
            )
        except DevelopmentTriggerError as exc:
            raise BenchmarkExecutionError(str(exc)) from None
        if request != validated_request:
            raise BenchmarkExecutionError("DEV sentinel validation result differs")
    try:
        approval_resolved = approval_path.resolve(strict=True)
    except OSError as exc:
        raise BenchmarkExecutionError("external EXEC approval artifact is missing") from exc
    root_resolved = ROOT.resolve()
    if approval_resolved == root_resolved or root_resolved in approval_resolved.parents:
        raise BenchmarkExecutionError("EXEC approval must be external to the frozen repository")
    approval_raw = approval_resolved.read_bytes()
    approval_document = read_json(approval_resolved)
    expected_approval_schema = (
        "trimem/external-exec-approval/1.2"
        if split == "development"
        and "approved_openai_key_commitment"
        in request.get("required_external_approval_fields", ())
        else "trimem/external-exec-approval/1.1"
        if split == "development"
        else "trimem/external-exec-approval/1.0"
    )
    if approval_document.get("schema") != expected_approval_schema:
        raise BenchmarkExecutionError("external EXEC approval schema mismatch")
    if approval_document.get("request_id") != request.get("request_id"):
        raise BenchmarkExecutionError("external approval request identity mismatch")
    request_hash = sha256_bytes(request_path.read_bytes())
    if approval_document.get("approved_request_sha256") not in {request_hash, "sha256:" + request_hash}:
        raise BenchmarkExecutionError("external approval does not bind the committed request bytes")
    approval = approval_document.get("approval")
    if not isinstance(approval, dict):
        raise BenchmarkExecutionError("external approval binding is missing")
    required_approval_fields = (
        request.get("required_external_approval_fields", ())
        if split == "development"
        else policy_request.get("required_approval_fields", ())
    )
    missing = sorted(set(required_approval_fields) - set(approval))
    if missing:
        raise BenchmarkExecutionError(f"approval binding fields are missing: {missing}")
    head = git_head()
    if approval.get("approved_git_commit") != head:
        raise BenchmarkExecutionError("approval Git commit differs from execution HEAD")
    source_head = request.get("source_head") if split == "development" else None
    if split == "development" and approval.get("approved_source_git_commit") != source_head:
        raise BenchmarkExecutionError(
            "approval source Git commit differs from the DEV sentinel parent"
        )
    freeze_hash = sha256_bytes(freeze_path.read_bytes())
    if approval.get("approved_freeze_sha256") not in {freeze_hash, "sha256:" + freeze_hash}:
        raise BenchmarkExecutionError("approval freeze digest differs from committed freeze")
    if approval.get("approved_phase") != phase:
        raise BenchmarkExecutionError("approval phase mismatch")
    workflow_run_id = os.environ.get("GITHUB_RUN_ID")
    workflow_run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT")
    if not workflow_run_id or re.fullmatch(r"[1-9][0-9]*", workflow_run_id) is None:
        raise BenchmarkExecutionError("exact GITHUB_RUN_ID is required for single-dispatch approval binding")
    if not workflow_run_attempt or re.fullmatch(r"[1-9][0-9]*", workflow_run_attempt) is None:
        raise BenchmarkExecutionError("exact GITHUB_RUN_ATTEMPT is required for single-attempt approval binding")
    if split in {"grader-smoke", "development"} and workflow_run_attempt != "1":
        raise BenchmarkExecutionError(
            "one-time phase execution requires workflow run attempt 1"
        )
    if str(approval.get("approved_workflow_run_id")) != workflow_run_id:
        raise BenchmarkExecutionError("approval workflow run ID differs from this dispatch")
    if str(approval.get("approved_workflow_run_attempt")) != workflow_run_attempt:
        raise BenchmarkExecutionError("approval workflow run attempt differs from this attempt")
    if not isinstance(approval.get("approval_actor"), str) or not approval["approval_actor"].strip():
        raise BenchmarkExecutionError("approval actor is missing")
    if not _iso_timestamp(approval.get("approval_timestamp")):
        raise BenchmarkExecutionError("approval timestamp is not an exact UTC timestamp")
    approved_at = datetime.fromisoformat(approval["approval_timestamp"][:-1] + "+00:00")
    if approved_at > datetime.now(timezone.utc):
        raise BenchmarkExecutionError("approval timestamp is in the future")
    if approval.get("approved_legal_terms_acceptance") is not True:
        raise BenchmarkExecutionError("approval actor did not accept applicable benchmark/source-project terms")
    hard = cost.get("phase_hard_caps", {}).get(phase, {})
    if not isinstance(hard, dict) or not hard:
        raise BenchmarkExecutionError("frozen phase hard cap is missing")
    if phase == "DEVELOPMENT_TUNING":
        try:
            hard = validate_development_phase_hard_cap(hard)
        except DevelopmentPhaseCapError as exc:
            raise BenchmarkExecutionError(str(exc)) from None
    exact = {
        "approved_task_arm_runs": hard.get("task_arm_runs"),
        "approved_paid_model_call_cap": hard.get("paid_model_calls"),
        "approved_input_token_cap": hard.get("input_tokens"),
        "approved_output_token_cap": hard.get("output_tokens"),
        "approved_currency_hard_cap": hard.get("total_usd"),
        "approved_grader_containers": hard.get("benchmark_grader_containers"),
    }
    for name, expected in exact.items():
        if approval.get(name) != expected:
            raise BenchmarkExecutionError(f"approval cap does not equal frozen proposed cap: {name}")
    try:
        approval = validate_external_approval_document(
            approval_document,
            request=request,
            policy_request=policy_request,
            phase=phase,
            hard_cap=hard,
            request_sha256=request_hash,
            freeze_sha256=freeze_hash,
            git_head=head,
            source_head=source_head,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
    except ApprovalValidationError as exc:
        raise BenchmarkExecutionError(str(exc)) from None
    return {
        "request": request,
        "approval": approval,
        "approval_artifact_sha256": sha256_bytes(approval_raw),
        "approval_document": approval_document,
        "approved_request_sha256": request_hash,
        "approved_workflow_run_id": workflow_run_id,
        "approved_workflow_run_attempt": workflow_run_attempt,
        "git_head": head,
        "source_head": source_head,
        "freeze_sha256": freeze_hash,
        "phase": phase,
        "hard_cap": hard,
    }


def write_external_approval_evidence(
    output: Path,
    *,
    split: str,
    approval_path: Path,
    validated: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist the exact restricted approval and its public hash-only binding."""

    approval_raw = approval_path.resolve(strict=True).read_bytes()
    if sha256_bytes(approval_raw) != validated["approval_artifact_sha256"]:
        raise BenchmarkExecutionError("exact external approval bytes/hash mismatch")
    restricted_approval = output / "restricted-external-approval.json"
    if restricted_approval.exists():
        if restricted_approval.read_bytes() != approval_raw:
            raise BenchmarkExecutionError(
                "resume external approval differs from the first process attempt"
            )
    else:
        restricted_approval.write_bytes(approval_raw)
        try:
            restricted_approval.chmod(0o600)
        except OSError:
            pass
    public = {
        "approval_artifact_sha256": validated["approval_artifact_sha256"],
        "approved_request_sha256": validated["approved_request_sha256"],
        "approved_workflow_run_id": validated["approved_workflow_run_id"],
        "approved_workflow_run_attempt": validated["approved_workflow_run_attempt"],
        "freeze_sha256": validated["freeze_sha256"],
        "git_head": validated["git_head"],
        "phase": validated["phase"],
    }
    if split == "development":
        public["source_head"] = validated["source_head"]
    write_json(output / "external-approval-evidence.json", public)
    return public


@contextmanager
def _exclusive_file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            if stream.seek(0, os.SEEK_END) == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if os.name == "nt":
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


class AtomicBudgetLedger:
    """Cross-process durable caps for one serial benchmark execution.

    All three arms use this same file in one workflow job.  Model calls reserve
    the conservative uncached input byte bound, provider maximum output, one
    paid call, their exact solve/decomposition/extraction class, and worst-case
    USD before delegation. Task-arm and grader capacity is also reserved before
    the runtime starts a task.
    """

    def __init__(self, path: Path, *, approval_digest: str, caps: Mapping[str, Any], pricing: Mapping[str, Any]):
        self.path = path.resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.approval_digest = approval_digest
        self.approved_hard_cap = dict(caps)
        self.caps = {
            "paid_model_calls": int(caps["paid_model_calls"]),
            "solve_calls": int(caps["solve_calls"]),
            "decomposition_calls": int(caps["decomposition_calls"]),
            "extraction_calls": int(caps["extraction_calls"]),
            "input_tokens": int(caps["input_tokens"]),
            "output_tokens": int(caps["output_tokens"]),
            "total_usd": float(caps["total_usd"]),
            "task_arm_runs": int(caps["task_arm_runs"]),
            "grader_containers": int(caps["benchmark_grader_containers"]),
            "max_input_tokens_per_task_arm": int(caps["max_input_tokens_per_task_arm"]),
            "max_model_calls_per_task_arm": int(caps["max_model_calls_per_task_arm"]),
        }
        self.pricing = {
            "input": float(pricing["input_per_million_tokens_usd"]),
            "cached": float(pricing["cached_input_per_million_tokens_usd"]),
            "output": float(pricing["output_per_million_tokens_usd"]),
        }
        if any(value <= 0 for value in self.caps.values()) or any(value <= 0 for value in self.pricing.values()):
            raise ValueError("budget caps and pricing must be positive")
        if int(caps["model_calls"]) != self.caps["paid_model_calls"] or int(
            caps["model_calls"]
        ) != sum(self.caps[field] for field in CALL_CAP_BY_KIND.values()):
            raise ValueError("approved model/paid/role call caps do not add up")
        uncached_ceiling = (
            Decimal(self.caps["input_tokens"]) * Decimal(str(self.pricing["input"]))
            + Decimal(self.caps["output_tokens"])
            * Decimal(str(self.pricing["output"]))
        ) / Decimal(1_000_000)
        if uncached_ceiling != Decimal(str(caps["uncached_token_cost_ceiling_usd"])):
            raise ValueError("uncached token-cost ceiling differs from caps/pricing")

    def _empty(self) -> dict[str, Any]:
        return {
            "schema": "trimem/atomic-budget-ledger/1.4",
            "approval_digest": self.approval_digest,
            "approved_hard_cap": self.approved_hard_cap,
            "approved_hard_cap_sha256": sha256_bytes(
                canonical_bytes(self.approved_hard_cap)
            ),
            "caps": self.caps,
            "pricing": self.pricing,
            "actual": {"paid_model_calls": 0, "solve_calls": 0,
                       "decomposition_calls": 0, "extraction_calls": 0,
                       "input_tokens": 0, "cached_input_tokens": 0,
                       "output_tokens": 0, "total_usd": 0.0, "task_arm_runs": 0,
                       "grader_containers": 0},
            "outstanding": {"paid_model_calls": 0, "solve_calls": 0,
                            "decomposition_calls": 0, "extraction_calls": 0,
                            "input_tokens": 0, "output_tokens": 0,
                            "total_usd": 0.0, "task_arm_runs": 0, "grader_containers": 0},
            "requests": {},
            "task_arms": {},
        }

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        value = read_json(self.path)
        if (value.get("schema") != "trimem/atomic-budget-ledger/1.4" or
                value.get("approval_digest") != self.approval_digest or
                value.get("approved_hard_cap") != self.approved_hard_cap or
                value.get("approved_hard_cap_sha256") != sha256_bytes(
                    canonical_bytes(self.approved_hard_cap)
                ) or
                value.get("caps") != self.caps or value.get("pricing") != self.pricing):
            raise BenchmarkExecutionError("budget ledger approval/cap identity mismatch")
        return value

    @staticmethod
    def _money_equal(left: Any, right: Any) -> bool:
        try:
            if isinstance(left, bool) or isinstance(right, bool):
                return False
            return abs(Decimal(str(left)) - Decimal(str(right))) <= Decimal(
                "0.000000000001"
            )
        except (InvalidOperation, ValueError, TypeError):
            return False

    def finalize(
        self,
        *,
        expected_actual: Mapping[str, Any],
        expected_task_arms: Mapping[str, Mapping[str, Any]],
        expected_result_records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Validate the terminal ledger against every scientific task result."""

        with _exclusive_file_lock(self.lock_path):
            state = self._read()
        if set(state) != {
            "schema", "approval_digest", "approved_hard_cap",
            "approved_hard_cap_sha256", "caps", "pricing", "actual",
            "outstanding", "requests", "task_arms",
        }:
            raise BenchmarkExecutionError("budget ledger top-level shape differs")
        actual, outstanding = state.get("actual"), state.get("outstanding")
        if not isinstance(actual, dict) or set(actual) != set(LEDGER_ACTUAL_FIELDS):
            raise BenchmarkExecutionError("budget ledger actual counter shape differs")
        if not isinstance(outstanding, dict) or set(outstanding) != set(
            LEDGER_OUTSTANDING_FIELDS
        ):
            raise BenchmarkExecutionError("budget ledger outstanding counter shape differs")
        if set(expected_actual) != set(LEDGER_ACTUAL_FIELDS):
            raise BenchmarkExecutionError("task-result ledger projection shape differs")
        for field, expected in expected_actual.items():
            observed = actual[field]
            valid = self._money_equal(observed, expected) if field == "total_usd" else (
                type(observed) is int and observed >= 0 and observed == expected
            )
            if not valid:
                raise BenchmarkExecutionError(
                    f"budget ledger actual {field} differs from task results"
                )
        for field, value in outstanding.items():
            valid = self._money_equal(value, 0) if field == "total_usd" else (
                type(value) is int and value == 0
            )
            if not valid:
                raise BenchmarkExecutionError(
                    f"phase completed with outstanding {field} reservation"
                )
        if actual["cached_input_tokens"] > actual["input_tokens"]:
            raise BenchmarkExecutionError("budget ledger cached input exceeds total input")
        if actual["paid_model_calls"] != sum(
            actual[field] for field in CALL_CAP_BY_KIND.values()
        ):
            raise BenchmarkExecutionError("budget ledger paid/role call totals differ")

        requests = state["requests"]
        if not isinstance(requests, dict) or len(requests) != actual["paid_model_calls"]:
            raise BenchmarkExecutionError("budget ledger request count differs from actual calls")
        role_counts = {field: 0 for field in CALL_CAP_BY_KIND.values()}
        per_task_requests: dict[str, dict[str, Any]] = {
            task_key: {
                field: ("0.000000000000" if field == "total_usd" else 0)
                for field in TASK_LEDGER_PROJECTION_FIELDS
            }
            for task_key in expected_task_arms
        }
        per_task_role_output = {
            task_key: {kind: 0 for kind in TASK_OUTPUT_POOL_BY_CALL_KIND}
            for task_key in expected_task_arms
        }
        per_task_request_rows: dict[str, list[Mapping[str, Any]]] = {
            task_key: [] for task_key in expected_task_arms
        }
        for logical_id, request in requests.items():
            if (
                not isinstance(logical_id, str)
                or not logical_id
                or not isinstance(request, dict)
                or set(request) != TERMINAL_LEDGER_REQUEST_FIELDS
            ):
                raise BenchmarkExecutionError(
                    "budget ledger terminal request shape differs"
                )
            if (
                request.get("status")
                not in SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES
            ):
                raise BenchmarkExecutionError("phase has a non-terminal model reservation")
            cap_name = CALL_CAP_BY_KIND.get(request.get("call_kind"))
            if cap_name is None or request.get("call_cap_name") != cap_name:
                raise BenchmarkExecutionError("budget ledger request role binding differs")
            task_key = request.get("task_arm_key")
            if not isinstance(task_key, str) or task_key not in per_task_requests:
                raise BenchmarkExecutionError("budget ledger request task-arm binding differs")
            per_task_request_rows[task_key].append(request)
            input_upper_bound = request.get("input_upper_bound")
            output_cap = request.get("output_cap")
            if (
                type(input_upper_bound) is not int
                or not 0 < input_upper_bound <= MAX_LEDGER_INPUT_BOUND_PER_CALL
                or type(output_cap) is not int
                or output_cap <= 0
                or output_cap > MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[str(request["call_kind"])]
                or (
                    request["call_kind"] != "solve"
                    and output_cap != MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[str(request["call_kind"])]
                )
            ):
                raise BenchmarkExecutionError(
                    "budget ledger request reservation bounds are invalid"
                )
            expected_reservation_id = sha256_bytes(canonical_bytes({
                "approval": self.approval_digest,
                "logical_call_id": logical_id,
                "task_arm_key": task_key,
                "call_kind": request["call_kind"],
                "input_upper_bound": input_upper_bound,
                "output_cap": output_cap,
            }))
            if request.get("reservation_id") != expected_reservation_id:
                raise BenchmarkExecutionError(
                    "budget ledger request reservation identity differs"
                )
            expected_reserved_usd = (
                Decimal(input_upper_bound) * Decimal(str(self.pricing["input"]))
                + Decimal(output_cap) * Decimal(str(self.pricing["output"]))
            ) / Decimal(1_000_000)
            if not self._money_equal(
                request.get("reserved_usd"), expected_reserved_usd
            ):
                raise BenchmarkExecutionError(
                    "budget ledger request reserved USD differs from bounds/pricing"
                )
            token_values = (
                request.get("input_tokens"), request.get("cached_input_tokens"),
                request.get("output_tokens"),
            )
            if (
                any(type(value) is not int or value < 0 for value in token_values)
                or token_values[1] > token_values[0]
            ):
                raise BenchmarkExecutionError("budget ledger request token accounting is invalid")
            if token_values[0] > input_upper_bound or token_values[2] > output_cap:
                raise BenchmarkExecutionError(
                    "budget ledger request actual usage exceeds its reservation"
                )
            request_usd = (
                Decimal(token_values[0] - token_values[1])
                * Decimal(str(self.pricing["input"]))
                + Decimal(token_values[1]) * Decimal(str(self.pricing["cached"]))
                + Decimal(token_values[2]) * Decimal(str(self.pricing["output"]))
            ) / Decimal(1_000_000)
            if not self._money_equal(request.get("actual_usd"), request_usd):
                raise BenchmarkExecutionError("budget ledger request USD differs from pricing")
            try:
                actual_usd = Decimal(str(request["actual_usd"]))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise BenchmarkExecutionError(
                    "budget ledger request actual USD is invalid"
                ) from exc
            if actual_usd < 0 or actual_usd > expected_reserved_usd + Decimal(
                "0.000000000001"
            ):
                raise BenchmarkExecutionError(
                    "budget ledger request actual USD exceeds its reservation"
                )
            role_counts[cap_name] += 1
            projection = per_task_requests[str(task_key)]
            projection["input_tokens"] += token_values[0]
            projection["cached_input_tokens"] += token_values[1]
            projection["output_tokens"] += token_values[2]
            per_task_role_output[str(task_key)][str(request["call_kind"])] += token_values[2]
            projection[cap_name] += 1
            projection["model_gateway_calls"] += 1
            projection["paid_model_calls"] += 1
            projection["total_usd"] = format(
                Decimal(str(projection["total_usd"])) + request_usd,
                ".12f",
            )
        if any(actual[field] != count for field, count in role_counts.items()):
            raise BenchmarkExecutionError("budget ledger request/role totals differ")

        result_by_task_arm: dict[str, Mapping[str, Any]] = {}
        for record in expected_result_records:
            try:
                validate_scientific_terminal_result(record)
                task_arm_key = scientific_task_arm_key(record)
            except ScientificTerminalContractError as exc:
                raise BenchmarkExecutionError(
                    f"scientific terminal result contract failed: {exc}"
                ) from None
            if task_arm_key in result_by_task_arm:
                raise BenchmarkExecutionError(
                    "scientific terminal result task-arm identity is duplicated"
                )
            result_by_task_arm[task_arm_key] = record
        if set(result_by_task_arm) != set(expected_task_arms):
            raise BenchmarkExecutionError(
                "scientific result/task projection identities differ"
            )

        task_arms = state.get("task_arms")
        if not isinstance(task_arms, dict) or set(task_arms) != set(expected_task_arms):
            raise BenchmarkExecutionError("budget ledger task-arm identities differ from results")
        for task_arm_key, expected in expected_task_arms.items():
            row = task_arms[task_arm_key]
            projection = per_task_requests[task_arm_key]
            if set(expected) != set(TASK_LEDGER_PROJECTION_FIELDS):
                raise BenchmarkExecutionError("task-result ledger projection shape differs")
            for field in TASK_LEDGER_PROJECTION_FIELDS:
                matches = (
                    self._money_equal(projection[field], expected[field])
                    if field == "total_usd"
                    else type(expected[field]) is int
                    and projection[field] == expected[field]
                )
                if not matches:
                    raise BenchmarkExecutionError(
                        "budget ledger per-task request/result accounting differs"
                    )
            expected_task_reservation_id = sha256_bytes(canonical_bytes({
                "approval": self.approval_digest,
                "task_arm_key": task_arm_key,
            }))
            if (
                not isinstance(row, dict)
                or set(row) != TERMINAL_LEDGER_TASK_ARM_FIELDS
                or row.get("reservation_id") != expected_task_reservation_id
                or type(row.get("actual_input_tokens")) is not int
                or row["actual_input_tokens"] != expected["input_tokens"]
                or row["actual_input_tokens"]
                > self.caps["max_input_tokens_per_task_arm"]
                or type(row.get("actual_model_calls")) is not int
                or row["actual_model_calls"] != expected["model_gateway_calls"]
                or row["actual_model_calls"]
                > self.caps["max_model_calls_per_task_arm"]
                or row.get("outstanding_output_tokens") != 0
                or row.get("actual_output_tokens") != expected["output_tokens"]
            ):
                raise BenchmarkExecutionError(
                    "budget ledger task-arm/result accounting differs"
                )
            try:
                validate_result_ledger_pair(
                    result_by_task_arm[task_arm_key],
                    row,
                    ledger_task_arm_key=task_arm_key,
                )
                validate_result_request_statuses(
                    result_by_task_arm[task_arm_key],
                    per_task_request_rows[task_arm_key],
                )
            except ScientificTerminalContractError as exc:
                raise BenchmarkExecutionError(
                    f"scientific result/ledger terminal contract failed: {exc}"
                ) from None
            for kind, pool in TASK_OUTPUT_POOL_BY_CALL_KIND.items():
                actual_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[kind]
                remaining_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[kind]
                role_actual = per_task_role_output[task_arm_key][kind]
                if row.get(actual_field) != role_actual or row.get(remaining_field) != pool - role_actual:
                    raise BenchmarkExecutionError("budget ledger task-arm role output accounting differs")

        hard = self.approved_hard_cap
        bounded = {
            "model_calls": actual["paid_model_calls"],
            "paid_model_calls": actual["paid_model_calls"],
            "solve_calls": actual["solve_calls"],
            "decomposition_calls": actual["decomposition_calls"],
            "extraction_calls": actual["extraction_calls"],
            "input_tokens": actual["input_tokens"],
            "output_tokens": actual["output_tokens"],
            "task_arm_runs": actual["task_arm_runs"],
            "benchmark_grader_containers": actual["grader_containers"],
        }
        for field, value in bounded.items():
            if value > hard[field]:
                raise BenchmarkExecutionError(f"terminal {field} exceeds approved hard cap")
        for field in ("task_arm_runs", "decomposition_calls", "extraction_calls"):
            if bounded[field] != hard[field]:
                raise BenchmarkExecutionError(f"terminal {field} differs from exact workload")
        if bounded["benchmark_grader_containers"] != hard[
            "benchmark_grader_containers"
        ]:
            raise BenchmarkExecutionError(
                "terminal benchmark_grader_containers differs from exact workload"
            )
        actual_usd = Decimal(str(actual["total_usd"]))
        if actual_usd > Decimal(str(hard["total_usd"])) or actual_usd > Decimal(
            str(hard["uncached_token_cost_ceiling_usd"])
        ):
            raise BenchmarkExecutionError("terminal USD exceeds approved hard cap")
        return state

    def reserve_task_arm(self, task_arm_key: str) -> str:
        if not isinstance(task_arm_key, str) or not task_arm_key:
            raise ValueError("task-arm key is required")
        reservation_id = sha256_bytes(canonical_bytes({
            "approval": self.approval_digest, "task_arm_key": task_arm_key,
        }))
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            if task_arm_key in state["task_arms"]:
                raise BenchmarkExecutionError("duplicate or indeterminate task-arm reservation")
            for name in ("task_arm_runs", "grader_containers"):
                total = state["actual"][name] + state["outstanding"][name] + 1
                if total > self.caps[name]:
                    raise BenchmarkExecutionError(f"task rejected before execution: {name} hard cap")
                state["outstanding"][name] += 1
            state["task_arms"][task_arm_key] = {
                "reservation_id": reservation_id,
                "status": "RESERVED",
                "actual_input_tokens": 0,
                "outstanding_input_tokens": 0,
                "actual_model_calls": 0,
                "outstanding_model_calls": 0,
                "actual_output_tokens": 0,
                "outstanding_output_tokens": 0,
                "actual_decomposition_output_tokens": 0,
                "actual_solve_output_tokens": 0,
                "actual_extraction_output_tokens": 0,
                "remaining_decomposition_output_tokens": 8_192,
                "remaining_solve_output_tokens": 49_152,
                "remaining_extraction_output_tokens": 8_192,
            }
            write_json(self.path, state)
        return reservation_id

    def resume_task_arm(self, task_arm_key: str) -> str:
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            row = state["task_arms"].get(task_arm_key)
            if not isinstance(row, dict) or row.get("status") != "RESERVED":
                raise BenchmarkExecutionError("resume has no outstanding task-arm reservation")
            reservation_id = row.get("reservation_id")
            if not isinstance(reservation_id, str) or not SHA256.fullmatch(reservation_id):
                raise BenchmarkExecutionError("resume task-arm reservation is malformed")
            return reservation_id

    def task_arm_status(self, task_arm_key: str) -> Optional[str]:
        with _exclusive_file_lock(self.lock_path):
            row = self._read()["task_arms"].get(task_arm_key)
            return str(row.get("status")) if isinstance(row, dict) else None

    def complete_task_arm(
        self, task_arm_key: str, reservation_id: str, *, status: str,
        container_started: bool = True,
    ) -> None:
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            row = state["task_arms"].get(task_arm_key)
            if (not isinstance(row, dict) or row.get("reservation_id") != reservation_id or
                    row.get("status") != "RESERVED"):
                raise BenchmarkExecutionError("unknown or already completed task-arm reservation")
            if row["outstanding_input_tokens"] or row["outstanding_model_calls"] or row["outstanding_output_tokens"]:
                raise BenchmarkExecutionError("task-arm has unreconciled model reservations")
            state["outstanding"]["task_arm_runs"] -= 1
            state["outstanding"]["grader_containers"] -= 1
            state["actual"]["task_arm_runs"] += 1
            # Unknown failure after starting the runtime conservatively consumes
            # the one reserved grader-container slot.  A proven pre-container
            # failure records zero but can never release task-arm capacity.
            state["actual"]["grader_containers"] += int(bool(container_started))
            row.update({"status": status, "container_started": bool(container_started)})
            write_json(self.path, state)

    def reserve(
        self, logical_call_id: str, *, task_arm_key: str,
        call_kind: str, input_upper_bound: int, output_cap: int,
    ) -> str:
        if (
            not isinstance(logical_call_id, str)
            or not logical_call_id
            or not isinstance(task_arm_key, str)
            or not task_arm_key
            or type(input_upper_bound) is not int
            or input_upper_bound <= 0
            or type(output_cap) is not int
            or output_cap <= 0
        ):
            raise ValueError("reservation requires a logical call and positive bounds")
        if input_upper_bound > MAX_LEDGER_INPUT_BOUND_PER_CALL:
            raise BenchmarkExecutionError("per-call conservative input bound exceeds the frozen runtime cap")
        call_cap_name = {
            "solve": "solve_calls",
            "decompose": "decomposition_calls",
            "extract": "extraction_calls",
        }.get(call_kind)
        if call_cap_name is None:
            raise BenchmarkExecutionError("paid request has an unknown call kind")
        if output_cap > MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind] or (
            call_kind != "solve" and output_cap != MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind]
        ):
            raise BenchmarkExecutionError(
                "per-call output cap differs from the frozen runtime cap"
            )
        amount = input_upper_bound * self.pricing["input"] / 1_000_000 + output_cap * self.pricing["output"] / 1_000_000
        reservation_id = sha256_bytes(canonical_bytes({
            "approval": self.approval_digest, "logical_call_id": logical_call_id,
            "task_arm_key": task_arm_key,
            "call_kind": call_kind, "input_upper_bound": input_upper_bound,
            "output_cap": output_cap,
        }))
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            if logical_call_id in state["requests"]:
                raise BenchmarkExecutionError("duplicate paid logical call reservation")
            task_arm = state["task_arms"].get(task_arm_key)
            if not isinstance(task_arm, dict) or task_arm.get("status") != "RESERVED":
                raise BenchmarkExecutionError("paid call has no active task-arm reservation")
            if (task_arm["actual_input_tokens"] + task_arm["outstanding_input_tokens"] +
                    input_upper_bound > self.caps["max_input_tokens_per_task_arm"]):
                raise BenchmarkExecutionError("paid request rejected before send: task-arm input hard cap")
            if (task_arm["actual_model_calls"] + task_arm["outstanding_model_calls"] + 1 >
                    self.caps["max_model_calls_per_task_arm"]):
                raise BenchmarkExecutionError("paid request rejected before send: task-arm call hard cap")
            actual_role_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[call_kind]
            remaining_role_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[call_kind]
            role_outstanding = sum(
                int(row["output_cap"])
                for row in state["requests"].values()
                if row.get("status") == "RESERVED"
                and row.get("task_arm_key") == task_arm_key
                and row.get("call_kind") == call_kind
            )
            if task_arm[actual_role_field] + role_outstanding + output_cap > TASK_OUTPUT_POOL_BY_CALL_KIND[call_kind]:
                raise BenchmarkExecutionError("paid request rejected before send: task-arm role output pool")
            if task_arm["actual_output_tokens"] + task_arm["outstanding_output_tokens"] + output_cap > TASK_TOTAL_OUTPUT_POOL:
                raise BenchmarkExecutionError("paid request rejected before send: task-arm total output pool")
            combined = {
                "paid_model_calls": state["actual"]["paid_model_calls"] + state["outstanding"]["paid_model_calls"] + 1,
                call_cap_name: state["actual"][call_cap_name] + state["outstanding"][call_cap_name] + 1,
                "input_tokens": state["actual"]["input_tokens"] + state["outstanding"]["input_tokens"] + input_upper_bound,
                "output_tokens": state["actual"]["output_tokens"] + state["outstanding"]["output_tokens"] + output_cap,
                "total_usd": state["actual"]["total_usd"] + state["outstanding"]["total_usd"] + amount,
            }
            for name, total in combined.items():
                if total > self.caps[name] + (1e-12 if name == "total_usd" else 0):
                    raise BenchmarkExecutionError(f"paid request rejected before send: {name} hard cap")
            state["outstanding"]["paid_model_calls"] += 1
            state["outstanding"][call_cap_name] += 1
            state["outstanding"]["input_tokens"] += input_upper_bound
            state["outstanding"]["output_tokens"] += output_cap
            state["outstanding"]["total_usd"] += amount
            task_arm["outstanding_input_tokens"] += input_upper_bound
            task_arm["outstanding_model_calls"] += 1
            task_arm["outstanding_output_tokens"] += output_cap
            task_arm[remaining_role_field] = (
                TASK_OUTPUT_POOL_BY_CALL_KIND[call_kind]
                - task_arm[actual_role_field]
                - role_outstanding
                - output_cap
            )
            state["requests"][logical_call_id] = {
                "reservation_id": reservation_id, "status": "RESERVED",
                "input_upper_bound": input_upper_bound, "output_cap": output_cap,
                "reserved_usd": amount, "task_arm_key": task_arm_key,
                "call_kind": call_kind, "call_cap_name": call_cap_name,
            }
            write_json(self.path, state)
        return reservation_id

    def reconcile(
        self,
        logical_call_id: str,
        reservation_id: str,
        *,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        status: str,
        conservative_unknown: bool = False,
    ) -> None:
        with _exclusive_file_lock(self.lock_path):
            state = self._read()
            request = state["requests"].get(logical_call_id)
            if not isinstance(request, dict) or request.get("reservation_id") != reservation_id or request.get("status") != "RESERVED":
                raise BenchmarkExecutionError("unknown or already reconciled paid reservation")
            call_kind = request.get("call_kind")
            call_cap_name = {
                "solve": "solve_calls",
                "decompose": "decomposition_calls",
                "extract": "extraction_calls",
            }.get(call_kind)
            if call_cap_name is None or request.get("call_cap_name") != call_cap_name:
                raise BenchmarkExecutionError("paid reservation call-kind identity mismatch")
            if conservative_unknown:
                input_tokens, cached_input_tokens, output_tokens = request["input_upper_bound"], 0, request["output_cap"]
            values = (input_tokens, cached_input_tokens, output_tokens)
            if any(type(value) is not int or value < 0 for value in values) or cached_input_tokens > input_tokens:
                raise BenchmarkExecutionError("provider usage is not exact non-negative accounting")
            if input_tokens > request["input_upper_bound"] or output_tokens > request["output_cap"]:
                raise BenchmarkExecutionError("actual provider usage exceeded its atomic reservation")
            uncached = input_tokens - cached_input_tokens
            actual_usd = (
                uncached * self.pricing["input"] + cached_input_tokens * self.pricing["cached"] +
                output_tokens * self.pricing["output"]
            ) / 1_000_000
            state["outstanding"]["paid_model_calls"] -= 1
            state["outstanding"][call_cap_name] -= 1
            state["outstanding"]["input_tokens"] -= request["input_upper_bound"]
            state["outstanding"]["output_tokens"] -= request["output_cap"]
            state["outstanding"]["total_usd"] -= request["reserved_usd"]
            task_arm = state["task_arms"].get(request["task_arm_key"])
            if not isinstance(task_arm, dict) or task_arm.get("status") != "RESERVED":
                raise BenchmarkExecutionError("paid reservation task-arm identity mismatch")
            task_arm["outstanding_input_tokens"] -= request["input_upper_bound"]
            task_arm["outstanding_model_calls"] -= 1
            task_arm["outstanding_output_tokens"] -= request["output_cap"]
            task_arm["actual_input_tokens"] += input_tokens
            task_arm["actual_model_calls"] += 1
            task_arm["actual_output_tokens"] += output_tokens
            actual_role_field = TASK_ACTUAL_OUTPUT_FIELD_BY_CALL_KIND[str(call_kind)]
            remaining_role_field = TASK_REMAINING_OUTPUT_FIELD_BY_CALL_KIND[str(call_kind)]
            task_arm[actual_role_field] += output_tokens
            role_outstanding = sum(
                int(row["output_cap"])
                for key, row in state["requests"].items()
                if key != logical_call_id
                and row.get("status") == "RESERVED"
                and row.get("task_arm_key") == request["task_arm_key"]
                and row.get("call_kind") == call_kind
            )
            task_arm[remaining_role_field] = (
                TASK_OUTPUT_POOL_BY_CALL_KIND[str(call_kind)]
                - task_arm[actual_role_field]
                - role_outstanding
            )
            state["actual"]["paid_model_calls"] += 1
            state["actual"][call_cap_name] += 1
            state["actual"]["input_tokens"] += input_tokens
            state["actual"]["cached_input_tokens"] += cached_input_tokens
            state["actual"]["output_tokens"] += output_tokens
            state["actual"]["total_usd"] += actual_usd
            request.update({"status": status, "input_tokens": input_tokens,
                            "cached_input_tokens": cached_input_tokens, "output_tokens": output_tokens,
                            "actual_usd": actual_usd})
            for name in (
                "paid_model_calls", call_cap_name, "input_tokens", "output_tokens",
                "total_usd",
            ):
                if state["actual"][name] > self.caps[name] + (1e-12 if name == "total_usd" else 0):
                    raise BenchmarkExecutionError(f"reconciled provider usage exceeded {name} hard cap")
            write_json(self.path, state)


class BudgetedModelGateway:
    def __init__(
        self, delegate: AsyncProviderModelGateway, ledger: AtomicBudgetLedger, *, stream_id: str
    ):
        if type(delegate) is not AsyncProviderModelGateway:
            raise TypeError("benchmark model gateway must use AsyncProviderModelGateway")
        if not isinstance(stream_id, str) or not stream_id:
            raise ValueError("benchmark stream_id is required")
        self.delegate = delegate
        self.ledger = ledger
        self.stream_id = stream_id

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        # UTF-8 bytes upper-bound prompt tokens for this text-only envelope;
        # 4096 additional tokens conservatively cover role/schema framing.
        input_bound = max(1, len(request.prompt.encode("utf-8"))) + 4_096
        task_arm_key = f"{self.stream_id}:{request.arm}:{request.task_id}"
        ledger_logical_call_id = f"{self.stream_id}:{request.logical_call_id}"
        reservation = self.ledger.reserve(
            ledger_logical_call_id, task_arm_key=task_arm_key,
            call_kind=request.call_kind,
            input_upper_bound=input_bound, output_cap=request.max_output_tokens
        )
        try:
            response = self.delegate.invoke(request)
        except GatewayInvocationFailure as exc:
            unknown_usage = not exc.provider_reported_usage_available
            self.ledger.reconcile(
                ledger_logical_call_id, reservation,
                input_tokens=exc.input_tokens if not unknown_usage else 0,
                cached_input_tokens=exc.cached_input_tokens if not unknown_usage else 0,
                output_tokens=exc.output_tokens if not unknown_usage else 0,
                status="PROVIDER_FAILURE_CONSERVATIVE" if unknown_usage else "PROVIDER_FAILURE",
                conservative_unknown=unknown_usage,
            )
            exc.ledger_reservation = {
                "reservation_id": reservation,
                "input_upper_bound": input_bound,
                "output_cap": request.max_output_tokens,
                "charged_conservatively": unknown_usage,
            }
            raise
        except BaseException:
            # The request may have reached the provider without exact usage. Keep
            # the entire conservative reservation consumed; never release it.
            self.ledger.reconcile(
                ledger_logical_call_id, reservation, input_tokens=0, cached_input_tokens=0,
                output_tokens=0, status="UNKNOWN_FAILURE_CONSERVATIVE", conservative_unknown=True,
            )
            raise
        if response.paid is not True:
            self.ledger.reconcile(
                ledger_logical_call_id, reservation, input_tokens=0, cached_input_tokens=0,
                output_tokens=0, status="INVALID_UNPAID_RESPONSE_CONSERVATIVE", conservative_unknown=True,
            )
            raise BenchmarkExecutionError("benchmark provider response is not marked paid")
        unknown_usage = not response.provider_reported_usage_available
        self.ledger.reconcile(
            ledger_logical_call_id, reservation,
            input_tokens=response.input_tokens if not unknown_usage else 0,
            cached_input_tokens=response.cached_input_tokens if not unknown_usage else 0,
            output_tokens=response.output_tokens if not unknown_usage else 0,
            status="SUCCESS_CONSERVATIVE_USAGE" if unknown_usage else "SUCCESS",
            conservative_unknown=unknown_usage,
        )
        return replace(response, ledger_reservation={
            "reservation_id": reservation,
            "input_upper_bound": input_bound,
            "output_cap": request.max_output_tokens,
            "charged_conservatively": unknown_usage,
        })


class TerminalInvocationJournal:
    """Write-ahead, hash-bound cache for paid model and official grader calls.

    A completed record is replayed locally after a process restart.  An
    IN_FLIGHT record is deliberately not retried: the external side effect may
    have happened, so automatic repetition would violate the paid/container
    caps.  That ambiguous case requires evidence reconciliation instead of an
    unsafe second invocation.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / (sha256_bytes(key.encode("utf-8")) + ".json")

    def begin(self, kind: str, key: str, request_hash: str) -> Path:
        path = self._path(kind, key)
        if path.exists():
            row = read_json(path)
            if row.get("key") != key or row.get("request_sha256") != request_hash:
                raise BenchmarkExecutionError("terminal journal request identity mismatch")
            return path
        write_json(path, {
            "schema": "trimem/terminal-invocation-journal/1.0",
            "kind": kind,
            "key": key,
            "request_sha256": request_hash,
            "status": "IN_FLIGHT",
        })
        return path

    @staticmethod
    def load(path: Path) -> dict[str, Any]:
        return read_json(path)

    @staticmethod
    def finish(path: Path, value: Mapping[str, Any]) -> None:
        current = read_json(path)
        if current.get("status") != "IN_FLIGHT":
            raise BenchmarkExecutionError("terminal journal entry is already finalized")
        write_json(path, {**current, **dict(value)})


class JournaledModelGateway:
    def __init__(self, delegate: BudgetedModelGateway, journal: TerminalInvocationJournal):
        self.delegate = delegate
        self.journal = journal

    def replay_terminal(self, request: GatewayRequest) -> Optional[GatewayResponse]:
        request_hash = sha256_bytes(canonical_bytes(asdict(request)))
        path = self.journal._path("model", request.logical_call_id)
        if not path.exists():
            return None
        row = self.journal.load(path)
        if row.get("key") != request.logical_call_id or row.get("request_sha256") != request_hash:
            raise BenchmarkExecutionError("terminal journal request identity mismatch")
        if row.get("status") == "SUCCESS":
            return replace(
                GatewayResponse(**row["response"]), terminal_outcome_replayed=True
            )
        if row.get("status") == "FAILURE":
            raise GatewayInvocationFailure(
                **row["failure"], terminal_outcome_replayed=True
            )
        if row.get("status") == "IN_FLIGHT":
            return None
        raise BenchmarkExecutionError("unknown model journal state")

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        replayed = self.replay_terminal(request)
        if replayed is not None:
            return replayed
        request_hash = sha256_bytes(canonical_bytes(asdict(request)))
        path = self.journal.begin("model", request.logical_call_id, request_hash)
        row = self.journal.load(path)
        if row.get("status") != "IN_FLIGHT":
            raise BenchmarkExecutionError("unknown model journal state")
        # A pre-existing write-ahead record is ambiguous.  Only the process
        # that created it may issue the delegate call.
        if row.get("delegate_started") is True:
            raise BenchmarkExecutionError("model invocation is indeterminate; automatic retry refused")
        write_json(path, {**row, "delegate_started": True})
        try:
            response = self.delegate.invoke(request)
        except GatewayInvocationFailure as exc:
            failure = {
                "provider": exc.provider, "model": exc.model, "status": exc.status,
                "attempt": exc.attempt, "input_tokens": exc.input_tokens,
                "output_tokens": exc.output_tokens,
                "cached_input_tokens": exc.cached_input_tokens,
                "reasoning_tokens": exc.reasoning_tokens,
                "wall_time_ms": exc.wall_time_ms, "response_text": exc.response_text,
                "provider_request_id": exc.provider_request_id,
                "response_id": exc.response_id,
                "response_status": exc.response_status,
                "response_error_code": exc.response_error_code,
                "incomplete_reason": exc.incomplete_reason,
                "output_item_types": list(exc.output_item_types),
                "content_item_types": list(exc.content_item_types),
                "refusal_present": exc.refusal_present,
                "provider_reported_usage_available": exc.provider_reported_usage_available,
                "raw_envelope_reference": exc.raw_envelope_reference,
                "extracted_text_bytes": exc.extracted_text_bytes,
                "structured_output_bytes": exc.structured_output_bytes,
                "original_provider_terminal_classification": (
                    exc.original_provider_terminal_classification
                ),
                "provider_response_envelope": exc.provider_response_envelope,
                "ledger_reservation": exc.ledger_reservation,
            }
            self.journal.finish(path, {"status": "FAILURE", "failure": failure})
            raise
        self.journal.finish(path, {"status": "SUCCESS", "response": asdict(response)})
        return response


class JournaledGraderGateway:
    def __init__(self, delegate: OfficialHarnessGraderGateway, journal: TerminalInvocationJournal):
        self.delegate = delegate
        self.journal = journal

    @staticmethod
    def _request_hash(request: GradeRequest) -> str:
        workspace = request.workspace
        return sha256_bytes(canonical_bytes({
            "task_id": request.task_id,
            "repository": request.repository,
            "base_commit": request.base_commit,
            "patch_sha256": sha256_bytes(request.patch.encode("utf-8")),
            "workspace_kind": workspace.kind,
            "workspace_base_commit": workspace.base_commit,
            "workspace_checkout_root": workspace.checkout_root,
        }))

    @staticmethod
    def _result(value: Mapping[str, Any]) -> GradeResult:
        return GradeResult(**dict(value))

    def grade(self, request: GradeRequest) -> GradeResult:
        key = f"{request.task_id}:{self._request_hash(request)}"
        path = self.journal.begin("grader", key, self._request_hash(request))
        row = self.journal.load(path)
        if row.get("status") == "SUCCESS":
            return self._result(row["result"])
        if row.get("status") == "FAILURE":
            raise GraderInvocationFailure(self._result(row["result"]))
        if row.get("status") != "IN_FLIGHT":
            raise BenchmarkExecutionError("unknown grader journal state")
        if row.get("delegate_started") is True:
            raise BenchmarkExecutionError("grader invocation is indeterminate; automatic retry refused")
        write_json(path, {**row, "delegate_started": True})
        try:
            result = self.delegate.grade(request)
        except GraderInvocationFailure as exc:
            self.journal.finish(path, {"status": "FAILURE", "result": asdict(exc.result)})
            raise
        self.journal.finish(path, {"status": "SUCCESS", "result": asdict(result)})
        return result


class _EnvironmentSecret:
    def get(self, name: str) -> str:
        value = os.environ.get(name)
        if not value:
            raise BenchmarkExecutionError(f"required provider secret is absent: {name}")
        return value


def build_paid_model_gateway(
    session: Any, ledger: AtomicBudgetLedger, model_lock: Mapping[str, Any], *,
    stream_id: str, restricted_response_root: Path,
):
    import httpx
    model = model_lock.get("primary_model", {}).get("model_id")
    if model != "gpt-5.4-mini-2026-03-17":
        raise BenchmarkExecutionError("model lock does not select the frozen dated snapshot")
    roles = model_lock.get("model_roles", {})
    if (
        set(roles) != {"decomposition", "solve", "experience_extraction"}
        or any(
            not isinstance(roles.get(role), Mapping)
            or roles[role].get("model_id") != model
            for role in roles
        )
    ):
        raise BenchmarkExecutionError("all benchmark model roles must use the frozen Mini snapshot")
    runner = getattr(session, "coroutine_runner", None)
    if not callable(runner):
        raise BenchmarkExecutionError("production arm has no long-lived coroutine runner")
    client = httpx.AsyncClient()
    provider = OpenAIResponsesProvider(
        "https://api.openai.com/v1", model, _EnvironmentSecret(), family="gpt5.4",
        reasoning_effort="medium", max_retries=1, http_client=client,
        raw_response_recorder=RestrictedProviderResponseStore(restricted_response_root),
    )
    bridge = AsyncProviderModelGateway(provider, runner, expected_model=model)
    return BudgetedModelGateway(bridge, ledger, stream_id=stream_id), client


def close_paid_model_client(session: Any, client: Any) -> None:
    session.run_coroutine(client.aclose())


def _source_base_commit(row: Mapping[str, Any], benchmark_id: str) -> str:
    if benchmark_id == "swebench_verified":
        value = row.get("base_commit")
    else:
        base = row.get("base")
        value = base.get("sha") if isinstance(base, dict) else row.get("base_commit")
    return str(value or "")


def _source_instance_id(row: Mapping[str, Any], benchmark_id: str) -> str:
    if benchmark_id == "swebench_verified":
        return str(row.get("instance_id") or "")
    if row.get("instance_id"):
        return str(row["instance_id"])
    return f"{row.get('org')}__{row.get('repo')}-{row.get('number')}"


def _download_locked(spec: Mapping[str, Any], cache_root: Path) -> Path:
    benchmark_id, revision, relative = spec["benchmark_id"], spec["dataset_revision"], spec["path"]
    target = cache_root / benchmark_id / revision / Path(relative).name
    if target.is_file() and target.stat().st_size == spec["bytes"] and sha256_bytes(target.read_bytes()) == spec["sha256"]:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = OFFICIAL_DATASET_URLS[benchmark_id].format(revision=revision, path=relative)
    fd, temp_name = tempfile.mkstemp(prefix=".dataset-", dir=target.parent)
    digest, count = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as stream, urllib.request.urlopen(url, timeout=120) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                stream.write(chunk)
                digest.update(chunk)
                count += len(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if count != spec["bytes"] or digest.hexdigest() != spec["sha256"]:
            raise BenchmarkExecutionError(f"downloaded dataset bytes/hash mismatch: {benchmark_id}")
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target


def load_frozen_rows(split: str, cache_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest_path = ROOT / MANIFESTS[split]
    git_tracked(manifest_path)
    manifest = read_json(manifest_path)
    targets = manifest.get("targets")
    if manifest.get("status") != "FROZEN" or not isinstance(targets, list):
        raise BenchmarkExecutionError("target manifest is not frozen")
    if [row.get("order_index") for row in targets] != list(range(len(targets))):
        raise BenchmarkExecutionError("target stream order is not contiguous")
    grader_lock = read_json(ROOT / "configs/trimem_v1/grader_lock.json")
    specs = {row["benchmark_id"]: row for row in grader_lock.get("dataset_files", ())}
    selected: dict[str, dict[str, Any]] = {}
    for benchmark_id in sorted({row["benchmark_id"] for row in targets}):
        if benchmark_id not in specs:
            raise BenchmarkExecutionError(f"dataset lock is absent: {benchmark_id}")
        path = _download_locked(specs[benchmark_id], cache_root)
        if benchmark_id == "swebench_verified":
            try:
                import pyarrow.parquet as pq
            except ImportError as exc:
                raise BenchmarkExecutionError("pyarrow is required for the exact SWE-bench parquet") from exc
            source_rows: Iterable[Mapping[str, Any]] = pq.read_table(path).to_pylist()
        else:
            def rows() -> Iterable[Mapping[str, Any]]:
                with path.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        if line.strip():
                            value = strict_json_loads(line)
                            if not isinstance(value, dict):
                                raise BenchmarkExecutionError("Multi-SWE-bench row is not an object")
                            yield value
            source_rows = rows()
        wanted = {row["instance_id"] for row in targets if row["benchmark_id"] == benchmark_id}
        for source in source_rows:
            instance_id = _source_instance_id(source, benchmark_id)
            if instance_id not in wanted:
                continue
            if instance_id in selected:
                raise BenchmarkExecutionError(f"duplicate selected dataset row: {instance_id}")
            selected[instance_id] = dict(source)
    if set(selected) != {row["instance_id"] for row in targets}:
        raise BenchmarkExecutionError("one or more frozen target rows are missing")
    for target in targets:
        source = selected[target["instance_id"]]
        if sha256_bytes(canonical_bytes(source)) != target["source_row_sha256"]:
            raise BenchmarkExecutionError(f"source row hash mismatch: {target['target_id']}")
        if _source_base_commit(source, target["benchmark_id"]) != target["base_commit"]:
            raise BenchmarkExecutionError(f"source row base commit mismatch: {target['target_id']}")
        if target["dataset_revision"] != specs[target["benchmark_id"]]["dataset_revision"]:
            raise BenchmarkExecutionError(f"source revision mismatch: {target['target_id']}")
    return [dict(row) for row in targets], selected


def public_instruction(row: Mapping[str, Any], benchmark_id: str) -> str:
    if benchmark_id == "swebench_verified":
        value = row.get("problem_statement")
    else:
        title, body = row.get("title"), row.get("body")
        if not isinstance(title, str) or not isinstance(body, str):
            raise BenchmarkExecutionError("Multi-SWE-bench public title/body schema mismatch")
        pieces = [title.strip(), body.strip()]
        issues = row.get("resolved_issues")
        if not isinstance(issues, list):
            raise BenchmarkExecutionError("Multi-SWE-bench resolved_issues must be a list")
        for issue in issues:
            if not isinstance(issue, Mapping):
                raise BenchmarkExecutionError("Multi-SWE-bench resolved issue is not an object")
            number, issue_title, issue_body = issue.get("number"), issue.get("title"), issue.get("body")
            if (type(number) is not int or not isinstance(issue_title, str) or
                    not (issue_body is None or isinstance(issue_body, str))):
                raise BenchmarkExecutionError("Multi-SWE-bench resolved issue public schema mismatch")
            pieces.append(
                f"Resolved issue #{number}: {issue_title.strip()}\n"
                f"{issue_body.strip() if isinstance(issue_body, str) else ''}"
            )
        value = "\n\n".join(piece for piece in pieces if piece)
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkExecutionError("public task instruction is missing")
    return value.strip()


def coding_tasks(targets: Sequence[Mapping[str, Any]], rows: Mapping[str, Mapping[str, Any]]) -> list[CodingTask]:
    org_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "trimem-v1-benchmark-org"))
    user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "trimem-v1-benchmark-user"))
    return [CodingTask(
        task_id=target["target_id"], org_id=org_id, user_id=user_id,
        repository=target["repository"], commit=target["base_commit"],
        instruction=public_instruction(rows[target["instance_id"]], target["benchmark_id"]),
        files={}, editable_paths=(), public_test=None,
    ) for target in targets]


def repository_identity_resolver(experiment_id: str, arm: str) -> Callable[[CodingTask], Mapping[str, str]]:
    def resolve(task: CodingTask) -> Mapping[str, str]:
        return {
            "repository_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "trimem-repository:" + task.repository)),
            "solve_job_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"trimem-solve:{experiment_id}:{arm}:{task.task_id}")),
        }
    return resolve


def _run_command(argv: Sequence[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise BenchmarkExecutionError(f"command failed ({argv[0]}): {completed.stderr.strip()}")
    return completed


def prepare_checkouts(
    tasks: Sequence[CodingTask], targets: Sequence[Mapping[str, Any]],
    images: Mapping[str, Mapping[str, Any]], root: Path, *, resume: bool,
) -> tuple[GitCheckoutWorkspaceFactory, dict[str, dict[str, Any]]]:
    if len(tasks) != len(targets):
        raise BenchmarkExecutionError("task/target workspace binding length mismatch")
    roots, commits, evidence = {}, {}, {}
    command_runners = {}
    for task, target in zip(tasks, targets):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", task.task_id)
        checkout = (root / safe).resolve()
        stdout_parts, stderr_parts, argv_rows = [], [], []
        if not checkout.exists():
            if resume:
                raise BenchmarkExecutionError(f"resume checkout is missing: {task.task_id}")
            clone = ["git", "clone", "--no-checkout", "--filter=blob:none",
                     f"https://github.com/{task.repository}.git", str(checkout)]
            result = _run_command(clone)
            stdout_parts.append(result.stdout); stderr_parts.append(result.stderr); argv_rows.append(clone)
            checkout_cmd = ["git", "-C", str(checkout), "checkout", "--detach", task.commit]
            result = _run_command(checkout_cmd)
            stdout_parts.append(result.stdout); stderr_parts.append(result.stderr); argv_rows.append(checkout_cmd)
        head = _run_command(["git", "-C", str(checkout), "rev-parse", "HEAD"]).stdout.strip()
        if head != task.commit:
            raise BenchmarkExecutionError(f"checkout HEAD mismatch: {task.task_id}")
        status = _run_command(["git", "-C", str(checkout), "status", "--porcelain=v1"]).stdout
        if status and not resume:
            raise BenchmarkExecutionError(f"new checkout is not clean: {task.task_id}")
        roots[task.task_id], commits[task.task_id] = checkout, task.commit
        image = images.get(str(target.get("instance_id")), {}).get("image")
        if not isinstance(image, str):
            raise BenchmarkExecutionError(f"task command image is missing: {task.task_id}")
        command_runners[task.task_id] = DockerSandboxCommandRunner(image)
        evidence[task.task_id] = {
            "argv": argv_rows, "stdout": "".join(stdout_parts), "stderr": "".join(stderr_parts),
            "head": head, "initial_status": status,
        }
    factory = GitCheckoutWorkspaceFactory(roots, commits, command_runners=command_runners)
    if factory.production_capable is not True or type(factory) is not GitCheckoutWorkspaceFactory:
        raise BenchmarkExecutionError("benchmark workspace is not the frozen Git checkout factory")
    return factory, evidence


def image_entries(*, require_benchmark: bool) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]]]:
    lock = read_json(ROOT / "artifacts/trimem_v1/grader_image_lock.json")
    if lock.get("status") != "FROZEN" or lock.get("smoke_status") != "FROZEN":
        raise BenchmarkExecutionError("grader-smoke image digest lock is not frozen")
    rows = list(lock.get("targets", ()))
    if require_benchmark:
        benchmark = lock.get("benchmark_target_images", {})
        if benchmark.get("status") != "FROZEN" or not isinstance(benchmark.get("targets"), list):
            raise BenchmarkExecutionError("development/held-out image digests are not frozen")
        rows.extend(benchmark["targets"])
    mapped = {}
    for row in rows:
        instance_id = row.get("instance_id")
        if instance_id in mapped:
            if mapped[instance_id] != row:
                raise BenchmarkExecutionError("conflicting grader image lock")
            continue
        mapped[instance_id] = dict(row)
    support = [(row["image"], row["harness_image_tag"]) for row in lock.get("support_images", ())]
    return mapped, support


def grader_factory(
    target: Mapping[str, Any], row: Mapping[str, Any], image: Mapping[str, Any],
    harnesses: Mapping[str, Path], output_root: Path, arm: str, support: Sequence[tuple[str, str]],
):
    harness_revision = (
        "7a21e05772954cc81471ae19d56f436cecf43c54"
        if target["benchmark_id"] == "swebench_verified"
        else "24f493f8a103e72312ded4f6b9c89f081d69cb09"
    )
    frozen = FrozenOfficialTarget(
        target_id=target["target_id"], benchmark_id=target["benchmark_id"],
        instance_id=target["instance_id"], repository=target["repository"],
        base_commit=target["base_commit"], dataset_revision=target["dataset_revision"],
        source_row_sha256=target["source_row_sha256"], image=image["image"],
        harness_image_tag=image["harness_image_tag"], harness_revision=harness_revision,
    )
    multi_support = support if target["benchmark_id"].startswith("multi_swe_bench") else ()
    return OfficialHarnessGraderGateway(
        frozen, source_row=row, harness_root=harnesses[target["benchmark_id"]],
        output_root=output_root, model_name=f"trimem-v1-{arm}", support_images=multi_support,
    )


def observed_target_digest(grade: GradeResult) -> str:
    """Return the inspected digest, never the expected container field."""
    report = grade.report
    trimem = report.get("_trimem") if isinstance(report, Mapping) else None
    if not isinstance(trimem, Mapping):
        raise BenchmarkExecutionError(
            "official report has no canonical TriMem evidence envelope"
        )
    evidence = trimem.get("image_evidence")
    if not isinstance(evidence, list):
        raise BenchmarkExecutionError("official report has no image-inspect evidence")
    expected = grade.container_digest.rsplit("@", 1)[-1]
    matches = []
    for row in evidence:
        if not isinstance(row, Mapping) or row.get("image") != grade.container_digest:
            continue
        observed = row.get("observed")
        if row.get("expected") != expected or not isinstance(observed, list) or expected not in observed:
            raise BenchmarkExecutionError("official report image evidence does not prove digest equality")
        matches.append(expected)
    if matches != [expected]:
        raise BenchmarkExecutionError("official report must contain one exact target image observation")
    return matches[0]


def restricted_evidence_references(task_dir: Path, grader_root: Path) -> list[dict[str, Any]]:
    root = grader_root / "restricted-evidence"
    if not root.exists():
        return []
    return [evidence_reference(task_dir, path) for path in sorted(root.glob("*.bin"))]


def evidence_reference(result_dir: Path, path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"path": path.resolve().relative_to(result_dir.resolve()).as_posix(),
            "sha256": sha256_bytes(raw), "bytes": len(raw)}


def actual_accounting(value: Mapping[str, Any], *, task_wall_time_ms: int = 0) -> dict[str, int]:
    summary = value.get("summary", {})
    kinds = summary.get("by_call_kind", {})
    tools = value.get("tools", [])
    solve_output = int(kinds.get("solve", {}).get("output_tokens", 0))
    return {
        "solve_calls": int(kinds.get("solve", {}).get("calls", 0)),
        "decomposition_calls": int(kinds.get("decompose", {}).get("calls", 0)),
        "extraction_calls": int(kinds.get("extract", {}).get("calls", 0)),
        "actual_decomposition_output_tokens": int(
            kinds.get("decompose", {}).get("output_tokens", 0)
        ),
        "actual_solve_output_tokens": solve_output,
        "actual_extraction_output_tokens": int(
            kinds.get("extract", {}).get("output_tokens", 0)
        ),
        "solve_output_pool_capacity": 49_152,
        "remaining_solve_output_tokens": 49_152 - solve_output,
        "replace_text_calls": sum(
            int(isinstance(row, Mapping) and row.get("tool_name") == "replace_text")
            for row in tools
        ),
        "write_file_calls": sum(
            int(isinstance(row, Mapping) and row.get("tool_name") == "write_file")
            for row in tools
        ),
        "input_tokens": int(summary.get("actual_input_tokens", 0)),
        "cached_input_tokens": int(summary.get("actual_cached_input_tokens", 0)),
        "output_tokens": int(summary.get("actual_output_tokens", 0)),
        "reasoning_tokens": int(summary.get("actual_reasoning_tokens", 0)),
        "model_wall_time_ms": int(summary.get("actual_model_wall_time_ms", 0)),
        "tool_wall_time_ms": int(summary.get("actual_tool_wall_time_ms", 0)),
        "grader_wall_time_ms": int(summary.get("actual_grader_wall_time_ms", 0)),
        "task_wall_time_ms": int(task_wall_time_ms),
        "model_gateway_calls": int(summary.get("model_gateway_calls", 0)),
        "paid_model_calls": int(summary.get("paid_model_calls", 0)),
        "grader_calls": int(summary.get("grader_calls", 0)),
        "grader_containers": int(summary.get("grader_containers", 0)),
        "official_grader_runs": int(summary.get("official_grader_runs", 0)),
    }


def provider_outcome_accounting(value: Mapping[str, Any]) -> dict[str, Any]:
    """Return a public, text-free provider outcome/usage projection."""

    calls = value.get("calls", [])
    if not isinstance(calls, list):
        raise BenchmarkExecutionError("provider call accounting is malformed")
    status_distribution: dict[str, int] = {}
    known_usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }
    reservation = {
        "calls": 0,
        "input_upper_bound": 0,
        "output_cap": 0,
        "conservatively_charged_calls": 0,
    }
    available_calls = 0
    unavailable_calls = 0
    for call in calls:
        if not isinstance(call, Mapping):
            raise BenchmarkExecutionError("provider call record is malformed")
        envelope = call.get("provider_response_envelope")
        classification = (
            envelope.get("terminal_classification")
            if isinstance(envelope, Mapping)
            else call.get("status")
        )
        if not isinstance(classification, str) or not classification:
            raise BenchmarkExecutionError("provider terminal classification is missing")
        status_distribution[classification] = status_distribution.get(classification, 0) + 1
        if call.get("provider_reported_usage_available") is True:
            available_calls += 1
            for field in known_usage:
                token_value = call.get(field)
                if type(token_value) is not int or token_value < 0:
                    raise BenchmarkExecutionError("provider reported usage is malformed")
                known_usage[field] += token_value
        else:
            unavailable_calls += 1
        ledger = call.get("ledger_reservation")
        if not isinstance(ledger, Mapping):
            raise BenchmarkExecutionError("provider ledger reservation is missing")
        for field in ("input_upper_bound", "output_cap"):
            amount = ledger.get(field)
            if type(amount) is not int or amount < 0:
                raise BenchmarkExecutionError("provider ledger reservation is malformed")
            reservation[field] += amount
        reservation["calls"] += 1
        reservation["conservatively_charged_calls"] += int(
            ledger.get("charged_conservatively") is True
        )
    return {
        "provider_status_distribution": dict(sorted(status_distribution.items())),
        "incomplete_count": sum(
            count for name, count in status_distribution.items()
            if name.startswith("RESPONSE_INCOMPLETE")
        ),
        "refusal_count": status_distribution.get("RESPONSE_REFUSAL", 0),
        "structured_output_schema_failure_count": status_distribution.get(
            "STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0
        ),
        "provider_reported_usage": {
            "available_calls": available_calls,
            "unavailable_calls": unavailable_calls,
            "complete": unavailable_calls == 0,
            **known_usage,
        },
        "ledger_reservation": reservation,
    }


def combine_provider_outcomes(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    usage = {
        "available_calls": 0,
        "unavailable_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
    }
    reservation = {
        "calls": 0,
        "input_upper_bound": 0,
        "output_cap": 0,
        "conservatively_charged_calls": 0,
    }
    for row in rows:
        for name, count in row["provider_status_distribution"].items():
            statuses[name] = statuses.get(name, 0) + int(count)
        for field in usage:
            usage[field] += int(row["provider_reported_usage"][field])
        for field in reservation:
            reservation[field] += int(row["ledger_reservation"][field])
    return {
        "provider_status_distribution": dict(sorted(statuses.items())),
        "incomplete_count": sum(
            count for name, count in statuses.items()
            if name.startswith("RESPONSE_INCOMPLETE")
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


def actual_usd_for_accounting(
    accounting: Mapping[str, int], pricing: Mapping[str, Any]
) -> str:
    cached = int(accounting["cached_input_tokens"])
    total_input = int(accounting["input_tokens"])
    if cached < 0 or total_input < cached:
        raise BenchmarkExecutionError("cached input tokens exceed total input tokens")
    million = Decimal(1_000_000)
    value = (
        Decimal(total_input - cached) * Decimal(str(pricing["input_per_million_tokens_usd"]))
        + Decimal(cached) * Decimal(str(pricing["cached_input_per_million_tokens_usd"]))
        + Decimal(int(accounting["output_tokens"]))
        * Decimal(str(pricing["output_per_million_tokens_usd"]))
    ) / million
    return format(value, ".12f")


def scientific_caps_after_protocol_canary(
    phase_cap: Mapping[str, Any],
    canary: Mapping[str, Any],
    *,
    expected_approval_sha256: str,
) -> dict[str, Any]:
    """Derive a non-transferable scientific budget after the protocol canary."""

    try:
        return scientific_cap_after_protocol_canary(
            phase_cap,
            canary,
            expected_approval_sha256=expected_approval_sha256,
        )
    except DevelopmentPhaseCapError as exc:
        raise BenchmarkExecutionError(str(exc)) from None


def validate_global_phase_accounting(
    phase_cap: Mapping[str, Any], canary: Mapping[str, Any], scientific: Mapping[str, Any]
) -> dict[str, Any]:
    """Prove the separate protocol and scientific ledgers fit the phase cap."""

    combined = {
        "model_calls": int(scientific["paid_model_calls"]) + 1,
        "paid_model_calls": int(scientific["paid_model_calls"]) + 1,
        "input_tokens": int(scientific["input_tokens"]) + int(canary["input_tokens"]),
        "cached_input_tokens": int(scientific["cached_input_tokens"])
        + int(canary["cached_input_tokens"]),
        "output_tokens": int(scientific["output_tokens"]) + int(canary["output_tokens"]),
        "total_usd": format(
            Decimal(str(scientific["total_usd"])) + Decimal(str(canary["actual_usd"])),
            ".12f",
        ),
    }
    for field in ("model_calls", "paid_model_calls", "input_tokens", "output_tokens"):
        if combined[field] > int(phase_cap[field]):
            raise BenchmarkExecutionError(f"combined protocol/scientific {field} exceeds phase cap")
    if Decimal(combined["total_usd"]) > Decimal(str(phase_cap["total_usd"])):
        raise BenchmarkExecutionError("combined protocol/scientific USD exceeds phase cap")
    return combined


def validate_phase_completion(
    output_root: Path,
    *,
    split: str,
    summaries: Sequence[Mapping[str, Any]],
    ledger: AtomicBudgetLedger,
    hard_cap: Mapping[str, Any],
    pricing: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind all terminal result, stream, session, and atomic-ledger evidence."""

    result_records = [
        read_json(path) for path in sorted(output_root.rglob("*.result.json"))
    ]
    if len(result_records) != hard_cap["task_arm_runs"]:
        raise BenchmarkExecutionError(
            "phase result count does not equal the approved exact matrix"
        )
    summary_by_arm: dict[str, Mapping[str, Any]] = {}
    for summary in summaries:
        arm = summary.get("arm")
        if not isinstance(arm, str) or not arm or arm in summary_by_arm:
            raise BenchmarkExecutionError("phase stream summaries have duplicate/invalid arms")
        summary_by_arm[arm] = summary

    empty_accounting = actual_accounting({"summary": {}})
    accounting_fields = set(empty_accounting)
    phase_accounting = {field: 0 for field in empty_accounting}
    task_arm_actual: dict[str, dict[str, Any]] = {}
    observed_keys: set[tuple[str, str]] = set()
    records_by_arm: dict[str, list[Mapping[str, Any]]] = {
        arm: [] for arm in summary_by_arm
    }
    execution_locks: dict[str, str] = {}
    phase_provider_rows: list[Mapping[str, Any]] = []
    for record in result_records:
        try:
            validate_scientific_terminal_result(record)
        except ScientificTerminalContractError as exc:
            raise BenchmarkExecutionError(
                f"phase scientific terminal result contract failed: {exc}"
            ) from None
        arm, runtime_arm, target_id = (
            record.get("arm"), record.get("runtime_arm"), record.get("target_id")
        )
        if (
            not isinstance(arm, str)
            or arm not in summary_by_arm
            or runtime_arm not in ARMS
            or not isinstance(target_id, str)
            or not target_id
            or (arm, target_id) in observed_keys
        ):
            raise BenchmarkExecutionError("phase result stream/task identity differs")
        observed_keys.add((arm, target_id))
        accounting = record.get("actual_accounting")
        if not isinstance(accounting, dict) or set(accounting) != accounting_fields or any(
            type(accounting[field]) is not int or accounting[field] < 0
            for field in accounting_fields
        ):
            raise BenchmarkExecutionError("phase result accounting shape/value differs")
        minimum_solve_calls = 1 if record["agent_completed"] is True else 0
        if (
                accounting["decomposition_calls"] != 1
                or accounting["extraction_calls"] != 1
                or not minimum_solve_calls <= accounting["solve_calls"] <= 24
            or accounting["model_gateway_calls"]
            != accounting["solve_calls"]
            + accounting["decomposition_calls"]
            + accounting["extraction_calls"]
            or accounting["paid_model_calls"] != accounting["model_gateway_calls"]
            or (
                accounting["grader_calls"], accounting["grader_containers"],
                accounting["official_grader_runs"],
            )
            != (1, 1, 1)
        ):
            raise BenchmarkExecutionError("phase result exact call/grader workload differs")
        if (
            accounting["input_tokens"] > hard_cap["max_input_tokens_per_task_arm"]
            or accounting["model_gateway_calls"]
            > hard_cap["max_model_calls_per_task_arm"]
        ):
            raise BenchmarkExecutionError("phase result exceeds a per-task-arm hard cap")
        if accounting["output_tokens"] != sum(
            accounting[field]
            for field in (
                "actual_decomposition_output_tokens",
                "actual_solve_output_tokens",
                "actual_extraction_output_tokens",
            )
        ):
            raise BenchmarkExecutionError("phase result role output totals differ")
        if (
            accounting["solve_output_pool_capacity"] != 49_152
            or accounting["actual_solve_output_tokens"] > 49_152
            or accounting["remaining_solve_output_tokens"]
            != 49_152 - accounting["actual_solve_output_tokens"]
        ):
            raise BenchmarkExecutionError("phase result solve output pool differs")
        actual_usd = actual_usd_for_accounting(accounting, pricing)
        if record.get("actual_usd") != actual_usd:
            raise BenchmarkExecutionError("phase result USD differs from tokens/pricing")
        execution_lock_hash = record.get("execution_lock_hash")
        if (
            not isinstance(execution_lock_hash, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", execution_lock_hash) is None
            or summary_by_arm[arm].get("execution_lock_hash") != execution_lock_hash
        ):
            raise BenchmarkExecutionError("result/summary execution-lock binding differs")
        prior_lock = execution_locks.setdefault(arm, execution_lock_hash)
        if prior_lock != execution_lock_hash:
            raise BenchmarkExecutionError("execution lock changed within a stream")
        for field in accounting_fields:
            phase_accounting[field] += accounting[field]
        provider_outcomes = record.get("provider_outcomes")
        if not isinstance(provider_outcomes, Mapping):
            raise BenchmarkExecutionError("phase result provider outcomes are missing")
        phase_provider_rows.append(provider_outcomes)
        task_arm_key = f"{arm}:{runtime_arm}:{target_id}"
        task_arm_actual[task_arm_key] = {
            "input_tokens": accounting["input_tokens"],
            "cached_input_tokens": accounting["cached_input_tokens"],
            "output_tokens": accounting["output_tokens"],
            "solve_calls": accounting["solve_calls"],
            "decomposition_calls": accounting["decomposition_calls"],
            "extraction_calls": accounting["extraction_calls"],
            "model_gateway_calls": accounting["model_gateway_calls"],
            "paid_model_calls": accounting["paid_model_calls"],
            "total_usd": actual_usd,
        }
        records_by_arm[arm].append(record)

    if len(set(execution_locks.values())) != len(execution_locks):
        raise BenchmarkExecutionError("benchmark streams share an execution lock")
    for arm, summary in summary_by_arm.items():
        stream_records = records_by_arm[arm]
        expected_stream_accounting = {
            field: sum(row["actual_accounting"][field] for row in stream_records)
            for field in accounting_fields
        }
        if summary.get("actual_accounting") != expected_stream_accounting:
            raise BenchmarkExecutionError("stream summary/result accounting totals differ")
        expected_provider_outcomes = combine_provider_outcomes(
            [row["provider_outcomes"] for row in stream_records]
        )
        if summary.get("provider_outcomes") != expected_provider_outcomes:
            raise BenchmarkExecutionError("stream summary/provider outcome totals differ")
        if summary.get("actual_usd") != actual_usd_for_accounting(
            expected_stream_accounting, pricing
        ):
            raise BenchmarkExecutionError("stream summary USD differs from results")
        identity_path = _arm_identity_path(output_root, arm)
        if not identity_path.is_file():
            raise BenchmarkExecutionError("stream session identity evidence is missing")
        envelope = read_json(identity_path)
        payload, digest = envelope.get("payload"), envelope.get("digest")
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "schema", "arm", "split", "experiment_id", "execution_lock_hash",
                "run_nonce",
            }
            or digest != "sha256:" + sha256_bytes(canonical_bytes(payload))
            or payload.get("schema") != "trimem/benchmark-arm-session-identity/1.0"
            or payload.get("arm") != arm
            or payload.get("split") != split
            or payload.get("execution_lock_hash") != execution_locks[arm]
        ):
            raise BenchmarkExecutionError("stream session/execution-lock identity differs")
        try:
            run_nonce = str(uuid.UUID(str(payload.get("run_nonce"))))
        except (ValueError, AttributeError) as exc:
            raise BenchmarkExecutionError("stream session nonce is invalid") from exc
        if payload.get("run_nonce") != run_nonce:
            raise BenchmarkExecutionError("stream session nonce is not canonical")

    expected_ledger_actual = {
        "paid_model_calls": phase_accounting["paid_model_calls"],
        "solve_calls": phase_accounting["solve_calls"],
        "decomposition_calls": phase_accounting["decomposition_calls"],
        "extraction_calls": phase_accounting["extraction_calls"],
        "input_tokens": phase_accounting["input_tokens"],
        "cached_input_tokens": phase_accounting["cached_input_tokens"],
        "output_tokens": phase_accounting["output_tokens"],
        "total_usd": float(actual_usd_for_accounting(phase_accounting, pricing)),
        "task_arm_runs": len(result_records),
        "grader_containers": phase_accounting["grader_containers"],
    }
    ledger.finalize(
        expected_actual=expected_ledger_actual,
        expected_task_arms=task_arm_actual,
        expected_result_records=result_records,
    )
    return {
        "actual_accounting": phase_accounting,
        "actual_usd": actual_usd_for_accounting(phase_accounting, pricing),
        "execution_locks": execution_locks,
        "provider_outcomes": combine_provider_outcomes(phase_provider_rows),
        "task_arm_runs": len(result_records),
    }


def actual_memory_metrics(result: Any, events_path: Path) -> dict[str, int]:
    recalls = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        event = strict_json_loads(line)
        if event.get("event_type") == "memory_recall":
            recalls.append(event.get("payload", {}))
    injections = tuple(result.injections)
    kinds = [str(row.get("kind")) for row in injections]
    storage = result.lifecycle_result.get("storage", {})
    if not isinstance(storage, Mapping):
        raise BenchmarkExecutionError("lifecycle storage metrics are absent")
    required = ("retained_records", "archived_records", "net_memory_growth")
    if any(type(storage.get(name)) is not int or storage[name] < 0 for name in required[:2]):
        raise BenchmarkExecutionError("lifecycle retained/archive metrics are incomplete")
    if type(storage.get("net_memory_growth")) is not int:
        raise BenchmarkExecutionError("lifecycle net-memory-growth metric is incomplete")
    if storage["net_memory_growth"] != storage["retained_records"] - storage["archived_records"]:
        raise BenchmarkExecutionError("lifecycle net-memory-growth arithmetic mismatch")
    return {
        "recall_attempts": len(recalls),
        "injected_records": len(injections),
        "episodic_injections": kinds.count("EPISODIC"),
        "user_semantic_injections": kinds.count("USER_SEMANTIC"),
        "org_semantic_injections": kinds.count("ORG_SEMANTIC"),
        "abstention_decisions": sum(
            1 for recall in recalls
            for row in recall.get("bank_trace", ())
            if isinstance(row, Mapping) and row.get("decision") == "ABSTAIN"
        ),
        "retained_records": int(storage["retained_records"]),
        "archived_records": int(storage["archived_records"]),
        "net_memory_growth": int(storage["net_memory_growth"]),
    }


def _arm_checkpoint_paths(root: Path, arm: str) -> tuple[Path, Path]:
    return root / f"{arm}.stream-checkpoint.json", root / f"{arm}.stream-checkpoint.sha256"


def save_arm_checkpoint(root: Path, arm: str, checkpoint: Mapping[str, Any]) -> None:
    target, sidecar = _arm_checkpoint_paths(root, arm)
    raw = canonical_bytes(checkpoint)
    atomic_write(target, raw)
    atomic_write(sidecar, (sha256_bytes(raw) + "\n").encode("ascii"))


def load_arm_checkpoint(root: Path, arm: str) -> dict[str, Any]:
    target, sidecar = _arm_checkpoint_paths(root, arm)
    if not target.is_file() or not sidecar.is_file():
        raise BenchmarkExecutionError("resume stream checkpoint is missing")
    raw = target.read_bytes()
    if sha256_bytes(raw) != sidecar.read_text(encoding="ascii").strip():
        raise BenchmarkExecutionError("resume stream checkpoint sidecar mismatch")
    value = strict_json_loads(raw)
    if not isinstance(value, dict):
        raise BenchmarkExecutionError("resume stream checkpoint is invalid")
    return value


def _task_recovery_paths(
    root: Path,
    stream_id: str,
    sequence_index: int,
    task: CodingTask,
) -> tuple[Path, str, Path]:
    safe_task_id = re.sub(r"[^A-Za-z0-9_.-]", "_", task.task_id)
    task_dir = root / stream_id / f"{sequence_index:03d}-{safe_task_id}"
    run_id = re.sub(r"[^A-Za-z0-9_-]", "_", f"{task.task_id}-{stream_id}")
    return task_dir, run_id, task_dir / "prepared-task-checkpoint.json"


def load_latest_task_recovery_proofs(
    root: Path,
    *,
    stream_id: str,
    tasks: Sequence[CodingTask],
) -> tuple[Optional[RuntimeCheckpoint], Optional[Mapping[str, Any]]]:
    """Load hash-verified local proofs before touching the canonical session.

    The prepared-task envelope is written before decomposition.  Every later
    AgentRuntime checkpoint must therefore have one; accepting an agent file
    without it would reopen the before-first-checkpoint timestamp window.
    """

    latest_agent: Optional[RuntimeCheckpoint] = None
    latest_prepared: Optional[Mapping[str, Any]] = None
    latest_agent_index = -1
    latest_prepared_index = -1
    for index, task in enumerate(tasks):
        task_dir, run_id, prepared_path = _task_recovery_paths(
            root, stream_id, index, task
        )
        prepared = None
        if prepared_path.exists():
            prepared = read_json(prepared_path)
            if not isinstance(prepared, Mapping):
                raise BenchmarkExecutionError("prepared-task checkpoint is invalid")
            latest_prepared = dict(prepared)
            latest_prepared_index = index
        checkpoint_dir = task_dir / "agent-checkpoints"
        checkpoint_path = checkpoint_dir / f"{run_id}.json"
        sidecar_path = checkpoint_dir / f"{run_id}.sha256"
        if checkpoint_path.exists() != sidecar_path.exists():
            raise BenchmarkExecutionError("agent checkpoint/sidecar is incomplete")
        if not checkpoint_path.exists():
            continue
        if prepared is None:
            raise BenchmarkExecutionError(
                "agent checkpoint has no pre-external-call prepared-task checkpoint"
            )
        checkpoint = FileCheckpointStore(checkpoint_dir).load(
            run_id, required_config_hashes=None
        )
        evidence = RawEvidenceLedger(task_dir / "evidence")
        evidence.verified_suffix(checkpoint.evidence_event_hash)
        evidence.verify()
        if checkpoint.task_id != task.task_id:
            raise BenchmarkExecutionError("agent checkpoint task identity mismatch")
        latest_agent = checkpoint
        latest_agent_index = index
    if latest_agent_index > latest_prepared_index:
        raise BenchmarkExecutionError("latest agent checkpoint lacks task preparation")
    return latest_agent, latest_prepared


def _arm_identity_path(root: Path, arm: str) -> Path:
    return root / f"{arm}.session-identity.json"


def prepare_arm_identity(
    root: Path,
    *,
    arm: str,
    split: str,
    experiment_id: str,
    execution_lock_hash: str,
    resume: bool,
) -> dict[str, Any]:
    """Persist the recovery nonce atomically before PostgreSQL is first touched."""

    path = _arm_identity_path(root, arm)
    expected = {
        "schema": "trimem/benchmark-arm-session-identity/1.0",
        "arm": arm,
        "split": split,
        "experiment_id": experiment_id,
        "execution_lock_hash": execution_lock_hash,
    }
    if resume:
        if not path.is_file():
            raise BenchmarkExecutionError("resume session identity is missing")
        envelope = read_json(path)
        payload = envelope.get("payload")
        digest = envelope.get("digest")
        if not isinstance(payload, Mapping) or digest != "sha256:" + sha256_bytes(
            canonical_bytes(payload)
        ):
            raise BenchmarkExecutionError("resume session identity digest mismatch")
        if any(payload.get(name) != value for name, value in expected.items()):
            raise BenchmarkExecutionError("resume session identity/configuration mismatch")
        try:
            run_nonce = str(uuid.UUID(str(payload.get("run_nonce"))))
        except (ValueError, AttributeError) as exc:
            raise BenchmarkExecutionError("resume session nonce is not a canonical UUID") from exc
        if payload.get("run_nonce") != run_nonce:
            raise BenchmarkExecutionError("resume session nonce is not canonical")
        return dict(payload)

    if path.exists():
        raise BenchmarkExecutionError(
            "session identity already exists; use --resume or a fresh output root"
        )
    payload = {**expected, "run_nonce": str(uuid.uuid4())}
    envelope = {
        "payload": payload,
        "digest": "sha256:" + sha256_bytes(canonical_bytes(payload)),
    }
    write_json(path, envelope)
    return payload


def build_execution_lock_hash(
    *,
    split: str,
    arm: str,
    stream_id: str,
    approval: Mapping[str, Any],
    targets: Sequence[Mapping[str, Any]],
    rows: Mapping[str, Mapping[str, Any]],
    tasks: Sequence[CodingTask],
    workspace_factory: GitCheckoutWorkspaceFactory,
    harnesses: Mapping[str, Path],
    images: Mapping[str, Mapping[str, Any]],
    model_lock: Mapping[str, Any],
    m2_manifest: Optional[Mapping[str, Any]],
    checkpoint_path: Optional[Path],
    runtime_lock: RuntimeLock,
    identity_seed_evidence: Mapping[str, Any],
) -> str:
    """Bind every execution-affecting artifact needed across task-boundary resume."""

    lock_paths = (
        ROOT / "configs/trimem_v1/model_lock.json",
        ROOT / "configs/trimem_v1/m2_policy.json",
        ROOT / "configs/trimem_v1/m2_candidate_bundles.json",
        ROOT / "configs/trimem_v1/selected_m2.json",
        ROOT / "configs/trimem_v1/grader_lock.json",
        ROOT / "configs/trimem_v1/benchmark_environment_lock.json",
        ROOT / "configs/trimem_v1/benchmark_environment.lock",
        ROOT / "configs/trimem_v1/benchmark_environment.in",
        ROOT / "artifacts/trimem_v1/grader_image_lock.json",
        ROOT / "artifacts/trimem_v1/freeze.json",
        ROOT / MANIFESTS[split],
        *(ROOT / "configs/trimem_v1/m2_candidates" / f"{candidate_id}.json"
          for candidate_id in CANDIDATE_IDS),
    )
    files = []
    for path in lock_paths:
        git_tracked(path)
        raw = path.read_bytes()
        files.append(
            {
                "path": path.resolve().relative_to(ROOT.resolve()).as_posix(),
                "sha256": sha256_bytes(raw),
                "bytes": len(raw),
            }
        )
    harness_revisions = {}
    for benchmark_id, path in sorted(harnesses.items()):
        harness_revisions[benchmark_id] = _run_command(
            ["git", "-C", str(path), "rev-parse", "HEAD"]
        ).stdout.strip()
    selected_checkpoint = None
    if checkpoint_path is not None:
        git_tracked(checkpoint_path)
        selected_checkpoint = {
            "sha256": sha256_bytes(checkpoint_path.read_bytes()),
            "bytes": checkpoint_path.stat().st_size,
        }
    task_payloads = [task.public_payload() for task in tasks]
    source_rows = {
        target["instance_id"]: rows[target["instance_id"]]
        for target in targets
    }
    selected_images = {
        target["instance_id"]: images[target["instance_id"]]
        for target in targets
    }
    payload = {
        "schema": "trimem/full-execution-lock/1.0",
        "git_head": approval["git_head"],
        "approval_artifact_sha256": approval["approval_artifact_sha256"],
        "freeze_sha256": approval["freeze_sha256"],
        "split": split,
        "arm": arm,
        "stream_id": stream_id,
        "target_sequence_sha256": sequence_sha256(list(targets)),
        "targets": list(targets),
        "source_rows": source_rows,
        "task_public_payloads": task_payloads,
        "runtime_lock_hash": runtime_lock.content_hash,
        "runtime_lock": runtime_lock.to_manifest(),
        "workspace_factory_hash": workspace_factory.content_hash,
        "model_lock": dict(model_lock),
        "m2_policy": dict(m2_manifest) if isinstance(m2_manifest, Mapping) else None,
        "selected_m2_checkpoint": selected_checkpoint,
        "identity_seed_evidence": dict(identity_seed_evidence),
        "harness_revisions": harness_revisions,
        "grader_images": selected_images,
        "committed_files": files,
    }
    return "sha256:" + sha256_bytes(canonical_bytes(payload))


_TERMINAL_RESULT_OWNED_FIELDS = frozenset(
    {
        "actual_accounting",
        "actual_memory_metrics",
        "actual_usd",
        "agent_completed",
        "cell_status",
        "container_started",
        "evidence",
        "execution_status",
        "extraction_status",
        "grader_exit_code",
        "grader_patch_source",
        "grader_status",
        "model_failure_class",
        "official_grader",
        "provider_outcomes",
        "resolved",
    }
)


def build_terminal_result_record(
    *,
    result: AgentRunResult,
    actual_accounting: Mapping[str, Any],
    actual_memory_metrics: Mapping[str, Any],
    provider_outcomes: Mapping[str, Any],
    actual_usd: str,
    static_fields: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Serialize one current scientific cell through the shared contract.

    The caller supplies identity/evidence bindings, while this function owns
    every scientific terminal-status field.  That separation prevents a test
    fixture or resume path from silently overriding the producer semantics.
    """

    overlap = sorted(_TERMINAL_RESULT_OWNED_FIELDS & set(static_fields))
    if overlap:
        raise BenchmarkExecutionError(
            f"terminal result static fields override producer fields: {overlap}"
        )
    record = {
        **dict(static_fields),
        "actual_accounting": dict(actual_accounting),
        "actual_memory_metrics": dict(actual_memory_metrics),
        "provider_outcomes": dict(provider_outcomes),
        "actual_usd": actual_usd,
        "execution_status": SCIENTIFIC_EXECUTION_STATUS,
        "grader_exit_code": result.grade.exit_code,
        "grader_status": result.grade.status,
        "container_started": result.grade.container_started,
        "cell_status": result.cell_status,
        "model_failure_class": result.model_failure_class,
        "agent_completed": result.agent_completed,
        "grader_patch_source": result.grader_patch_source,
        "extraction_status": result.extraction_status,
        "official_grader": result.grade.official,
        "resolved": result.resolved,
        "evidence": dict(evidence),
    }
    try:
        validate_scientific_terminal_result(record)
    except ScientificTerminalContractError as exc:
        raise BenchmarkExecutionError(
            f"terminal result producer contract failed: {exc}"
        ) from None
    return record


def run_arm_stream(
    *, split: str, arm: str, stream_id: str, runtime_lock: RuntimeLock,
    m2_manifest: Optional[Mapping[str, Any]], dqn_checkpoint_path: Optional[Path],
    selected_prompt_candidate_id: str,
    approval: Mapping[str, Any], targets: list[dict[str, Any]],
    rows: Mapping[str, Mapping[str, Any]], tasks: list[CodingTask], workspace_factory: GitCheckoutWorkspaceFactory,
    checkout_evidence: Mapping[str, Mapping[str, Any]], harnesses: Mapping[str, Path], output_root: Path,
    ledger: AtomicBudgetLedger, database_url: str, qdrant_url: str, resume: bool,
    identity_seed_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if arm not in ARMS or not isinstance(stream_id, str) or not stream_id:
        raise BenchmarkExecutionError("invalid benchmark runtime arm/stream identity")
    digest = sequence_sha256(targets)
    experiment_id = "trimemv1-" + approval["git_head"][:12] + "-" + re.sub(
        r"[^a-z0-9-]", "-", stream_id.lower()
    )
    seed_body = {
        key: value for key, value in identity_seed_evidence.items() if key != "digest"
    }
    if (
        identity_seed_evidence.get("schema")
        != "trimem/benchmark-identity-seed-evidence/1.0"
        or identity_seed_evidence.get("experiment_id") != experiment_id
        or identity_seed_evidence.get("stream_id") != stream_id
        or identity_seed_evidence.get("digest") != canonical_hash(seed_body)
        or len(identity_seed_evidence.get("rows", ())) != len(tasks)
        or "database_url" in json.dumps(identity_seed_evidence).casefold()
    ):
        raise BenchmarkExecutionError("admin identity seed evidence is absent or inconsistent")
    model_lock = read_json(ROOT / "configs/trimem_v1/model_lock.json")
    embedder_lock = model_lock["retrieval_embedding"]["production"]
    if arm != "M2" and (
        m2_manifest is not None or dqn_checkpoint_path is not None
    ):
        raise BenchmarkExecutionError(
            "M0/M1 cannot receive an M2 policy/checkpoint"
        )
    lifecycle_factory = None
    if arm == "M2":
        if not isinstance(m2_manifest, Mapping):
            raise BenchmarkExecutionError("M2 stream has no frozen full-policy manifest")
        m2_hash = "sha256:" + sha256_bytes(canonical_bytes(m2_manifest))
        lifecycle_factory = production_dqn_lifecycle_factory(
            repository_identity_resolver(experiment_id, stream_id),
            policy_manifest=m2_manifest,
            expected_policy_manifest_hash=m2_hash,
        )
    elif arm == "M1":
        # Every arm deliberately has its own solve-job identity.  A lookup by
        # only org/user/repository/task becomes ambiguous once another stream
        # has been seeded, so M1 must use the same exact stream-bound resolver
        # as M2 rather than the database fallback resolver.
        lifecycle_factory = production_v03_lifecycle_factory(
            identity_resolver=repository_identity_resolver(
                experiment_id, stream_id
            )
        )
    images, support = image_entries(require_benchmark=True)
    execution_lock_hash = build_execution_lock_hash(
        split=split,
        arm=arm,
        stream_id=stream_id,
        approval=approval,
        targets=targets,
        rows=rows,
        tasks=tasks,
        workspace_factory=workspace_factory,
        harnesses=harnesses,
        images=images,
        model_lock=model_lock,
        m2_manifest=m2_manifest,
        checkpoint_path=dqn_checkpoint_path,
        runtime_lock=runtime_lock,
        identity_seed_evidence=identity_seed_evidence,
    )
    identity = prepare_arm_identity(
        output_root,
        arm=stream_id,
        split=split,
        experiment_id=experiment_id,
        execution_lock_hash=execution_lock_hash,
        resume=resume,
    )
    run_nonce = identity["run_nonce"]
    inflight_proof: Optional[RuntimeCheckpoint] = None
    prepared_proof: Optional[Mapping[str, Any]] = None
    if resume:
        inflight_proof, prepared_proof = load_latest_task_recovery_proofs(
            output_root, stream_id=stream_id, tasks=tasks
        )
    session = open_benchmark_arm(
        database_url=database_url, qdrant_url=qdrant_url, experiment_id=experiment_id,
        split=split, arm_id=arm, task_order=tasks, dqn_checkpoint_path=dqn_checkpoint_path,
        embedder_lock=embedder_lock, evaluation=(split == "heldout"),
        lifecycle_factory=lifecycle_factory, run_nonce=run_nonce,
        execution_lock_hash=execution_lock_hash,
    )
    client = None
    try:
        if resume:
            restore_stream = getattr(session, "resume_canonical_stream", None)
            if not callable(restore_stream):
                raise BenchmarkExecutionError("production session lacks canonical crash recovery")
            checkpoint = restore_stream(
                inflight_checkpoint=inflight_proof,
                prepared_task_checkpoint=prepared_proof,
                allow_development_finalization=(
                    arm == "M2" and split == "development"
                ),
            )
            if checkpoint is not None:
                save_arm_checkpoint(output_root, stream_id, checkpoint)
            cursor = session.task_cursor
        else:
            freshness = session.assert_fresh()
            write_json(output_root / f"{stream_id}.freshness.json", freshness)
            cursor = 0
        gateway, client = build_paid_model_gateway(
            session, ledger, model_lock, stream_id=stream_id,
            restricted_response_root=(
                output_root / "restricted-provider-responses" / stream_id
            ),
        )
        # A crash after the canonical cursor advanced but before the local cap
        # ledger reconciled is repaired from the already-written task result.
        for completed_index in range(cursor):
            completed_task = tasks[completed_index]
            task_arm_key = f"{stream_id}:{arm}:{completed_task.task_id}"
            if ledger.task_arm_status(task_arm_key) != "RESERVED":
                continue
            safe_completed = re.sub(r"[^A-Za-z0-9_.-]", "_", completed_task.task_id)
            completed_dir = output_root / stream_id / f"{completed_index:03d}-{safe_completed}"
            completed_result_path = completed_dir / f"{safe_completed}.result.json"
            if not completed_result_path.is_file():
                raise BenchmarkExecutionError("canonical cursor is ahead without terminal task evidence")
            completed_record = read_json(completed_result_path)
            try:
                validate_scientific_terminal_result(completed_record)
                if scientific_task_arm_key(completed_record) != task_arm_key:
                    raise ScientificTerminalContractError(
                        "canonical cursor result/task-arm identity mismatch"
                    )
            except ScientificTerminalContractError as exc:
                raise BenchmarkExecutionError(
                    f"canonical cursor terminal result is invalid: {exc}"
                ) from None
            task_reservation = ledger.resume_task_arm(task_arm_key)
            ledger.complete_task_arm(
                task_arm_key,
                task_reservation,
                status=SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                container_started=bool(completed_record["container_started"]),
            )
        for index in range(cursor, len(tasks)):
            task, target = tasks[index], targets[index]
            if target["instance_id"] not in images:
                raise BenchmarkExecutionError(f"grader image missing for {target['target_id']}")
            task_dir, run_id, prepared_path = _task_recovery_paths(
                output_root, stream_id, index, task
            )
            task_dir.mkdir(parents=True, exist_ok=True)
            task_arm_key = f"{stream_id}:{arm}:{task.task_id}"
            task_status = ledger.task_arm_status(task_arm_key)
            if task_status is None:
                task_reservation = ledger.reserve_task_arm(task_arm_key)
            elif resume and task_status == "RESERVED":
                task_reservation = ledger.resume_task_arm(task_arm_key)
            else:
                raise BenchmarkExecutionError("task-arm cap ledger state does not match the stream cursor")
            task_started_ns = time.perf_counter_ns()
            evidence = RawEvidenceLedger(task_dir / "evidence")
            checkpoints = FileCheckpointStore(task_dir / "agent-checkpoints")
            journal = TerminalInvocationJournal(task_dir / "terminal-journal")
            session.before_task(task, index)
            if not prepared_path.exists():
                prepare_checkpoint = getattr(
                    session, "prepared_task_checkpoint", None
                )
                if not callable(prepare_checkpoint):
                    raise BenchmarkExecutionError(
                        "production session lacks pre-external-call task checkpointing"
                    )
                write_json(prepared_path, prepare_checkpoint(task))
            controller = session.controller_for(task)
            official_grader = grader_factory(
                target, rows[target["instance_id"]], images[target["instance_id"]],
                harnesses, task_dir / "official-grader", arm, support,
            )
            grader = JournaledGraderGateway(official_grader, journal)
            task_gateway = JournaledModelGateway(gateway, journal)
            runtime = TriMemAgentRuntime(
                runtime_lock=runtime_lock, model_gateway=task_gateway, grader_gateway=grader,
                memory_controller=controller, evidence=evidence, checkpoint_store=checkpoints,
                lifecycle=session.lifecycle, workspace_factory=workspace_factory,
                model_config_hash=sha256_bytes(canonical_bytes({
                    "execution_lock_hash": execution_lock_hash,
                    "primary_model": model_lock.get("primary_model"),
                })),
                grader_config_hash=sha256_bytes(canonical_bytes({
                    "execution_lock_hash": execution_lock_hash,
                    "target": target,
                    "source_row_sha256": target["source_row_sha256"],
                    "grader_image": images[target["instance_id"]],
                })),
            )
            agent_checkpoint = task_dir / "agent-checkpoints" / f"{run_id}.json"
            try:
                result = runtime.run(task, arm=arm, run_id=run_id, resume=agent_checkpoint.is_file())
            except GatewayInvocationFailure as failure:
                receipt = {
                    "schema": "trimem/provider-terminal-failure-receipt/1.0",
                    "task_id": task.task_id,
                    "arm": arm,
                    "stream_id": stream_id,
                    "logical_provider_status": failure.status,
                    "original_provider_terminal_classification": (
                        failure.original_provider_terminal_classification
                    ),
                    "provider_request_id_sha256": (
                        sha256_bytes(failure.provider_request_id.encode("utf-8"))
                        if failure.provider_request_id
                        else None
                    ),
                    "response_id": failure.response_id,
                    "response_status": failure.response_status,
                    "response_error_code": failure.response_error_code,
                    "incomplete_reason": failure.incomplete_reason,
                    "output_item_types": list(failure.output_item_types),
                    "content_item_types": list(failure.content_item_types),
                    "refusal_present": failure.refusal_present,
                    "provider_reported_usage": {
                        "available": failure.provider_reported_usage_available,
                        "input_tokens": failure.input_tokens,
                        "cached_input_tokens": failure.cached_input_tokens,
                        "output_tokens": failure.output_tokens,
                        "reasoning_tokens": failure.reasoning_tokens,
                    },
                    "ledger_reservation": failure.ledger_reservation,
                    "raw_envelope_reference": failure.raw_envelope_reference,
                    "extracted_text_bytes": failure.extracted_text_bytes,
                    "structured_output_bytes": failure.structured_output_bytes,
                    "provider_response_envelope": failure.provider_response_envelope,
                    "scientific_result_available": False,
                }
                receipt_path = task_dir / "provider-failure-receipt.json"
                if receipt_path.exists() and read_json(receipt_path) != receipt:
                    raise BenchmarkExecutionError(
                        "resumed provider failure differs from its durable receipt"
                    ) from failure
                if not receipt_path.exists():
                    write_json(receipt_path, receipt)
                raise
            except GraderInvocationFailure as failure:
                ledger.complete_task_arm(
                    task_arm_key, task_reservation, status="OFFICIAL_GRADER_FAILURE",
                    container_started=failure.result.container_started,
                )
                raise
            terminal_checkpoint = checkpoints.load(
                run_id, required_config_hashes=None,
                required_evidence_hash=result.evidence_tail_hash,
            )
            if terminal_checkpoint.state != "DONE":
                raise BenchmarkExecutionError("runtime returned without an evidence-bound DONE checkpoint")

            stdout_path = task_dir / "stdout.txt"
            stderr_path = task_dir / "stderr.txt"
            report_path = task_dir / "report.json"
            checkout_path = task_dir / "checkout-evidence.json"
            atomic_write(stdout_path, result.grade.stdout.encode("utf-8"))
            atomic_write(stderr_path, result.grade.stderr.encode("utf-8"))
            write_json(report_path, result.grade.report)
            write_json(checkout_path, checkout_evidence[task.task_id])
            events_path = evidence.events_path
            memory_metrics = actual_memory_metrics(result, events_path)
            observed_digest = observed_target_digest(result.grade)
            expected_digest = images[target["instance_id"]]["expected_digest"]
            task_wall_time_ms = max(0, (time.perf_counter_ns() - task_started_ns) // 1_000_000)
            accounting = actual_accounting(
                result.accounting, task_wall_time_ms=task_wall_time_ms
            )
            provider_outcomes = provider_outcome_accounting(result.accounting)
            pricing = read_json(ROOT / "configs/trimem_v1/cost_plan.json")["model_pricing"]
            task_actual_usd = actual_usd_for_accounting(accounting, pricing)
            record = build_terminal_result_record(
                result=result,
                actual_accounting=accounting,
                actual_memory_metrics=memory_metrics,
                provider_outcomes=provider_outcomes,
                actual_usd=task_actual_usd,
                static_fields={
                "arm": stream_id, "runtime_arm": arm,
                "benchmark_id": target["benchmark_id"],
                "checkout_evidence_sha256": sha256_bytes(canonical_bytes(checkout_evidence[task.task_id])),
                "execution_lock_hash": execution_lock_hash,
                "evidence_tail_hash": result.evidence_tail_hash,
                "namespace": session.namespace, "expected_image_digest": expected_digest,
                "identity_seed_digest": identity_seed_evidence["digest"],
                "observed_image_digest": observed_digest,
                "sequence_index": index, "sequence_sha256": digest, "target_id": target["target_id"],
                "terminal_checkpoint_sha256": terminal_checkpoint.content_hash,
                "terminal_state": terminal_checkpoint.state,
                "runtime_lock_sha256": "sha256:" + runtime_lock.content_hash,
                "m2_policy_manifest_sha256": (
                    "sha256:" + sha256_bytes(canonical_bytes(m2_manifest))
                    if isinstance(m2_manifest, Mapping) else None
                ),
                "selected_prompt_candidate_id": selected_prompt_candidate_id,
                "workspace_factory_hash": workspace_factory.content_hash,
                },
                evidence={
                    "stdout": evidence_reference(task_dir, stdout_path),
                    "stderr": evidence_reference(task_dir, stderr_path),
                    "report": evidence_reference(task_dir, report_path),
                    "raw_events": evidence_reference(task_dir, events_path),
                    "checkout": evidence_reference(task_dir, checkout_path),
                    "terminal_checkpoint": evidence_reference(task_dir, agent_checkpoint),
                    "restricted_grader_raw": restricted_evidence_references(
                        task_dir, task_dir / "official-grader"
                    ),
                },
            )
            result_path = task_dir / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', task.task_id)}.result.json"
            write_json(result_path, record)
            advance = getattr(session, "after_task_and_checkpoint", None)
            if not callable(advance):
                raise BenchmarkExecutionError("production session lacks atomic task/cursor checkpoint")
            stream_checkpoint = advance(task, result)
            save_arm_checkpoint(output_root, stream_id, stream_checkpoint)
            ledger.complete_task_arm(
                task_arm_key,
                task_reservation,
                status=SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                container_started=result.grade.container_started,
            )
        selected_checkpoint = None
        checkpoint_file: Optional[Path] = None
        if arm == "M2" and split == "development":
            if session.development_finalized:
                selected_checkpoint = session.final_policy_checkpoint
                if not isinstance(selected_checkpoint, Mapping):
                    raise BenchmarkExecutionError("finalized stream has no frozen policy checkpoint")
            else:
                finalize = getattr(session, "finalize_development", None)
                if not callable(finalize):
                    raise BenchmarkExecutionError("production M2 session cannot finalize/freeze development")
                selected_checkpoint = finalize(expected_resume_cursor=len(tasks))
                final_envelope = session.latest_checkpoint_envelope
                if not isinstance(final_envelope, Mapping):
                    raise BenchmarkExecutionError("development finalizer was not canonically checkpointed")
                save_arm_checkpoint(output_root, stream_id, final_envelope)
            checkpoint_file = output_root / f"{stream_id}.post-development-frozen-checkpoint.json"
            write_json(checkpoint_file, selected_checkpoint)
        result_records = [
            read_json(path) for path in sorted((output_root / stream_id).rglob("*.result.json"))
        ]
        if len(result_records) != len(tasks):
            raise BenchmarkExecutionError("stream summary cannot account for every frozen target")
        try:
            for record in result_records:
                validate_scientific_terminal_result(record)
        except ScientificTerminalContractError as exc:
            raise BenchmarkExecutionError(
                f"stream summary rejected a scientific terminal result: {exc}"
            ) from None
        empty_accounting = actual_accounting({"summary": {}})
        total_accounting = {
            field: sum(int(row["actual_accounting"][field]) for row in result_records)
            for field in empty_accounting
        }
        total_memory_metrics = {
            field: sum(int(row["actual_memory_metrics"][field]) for row in result_records)
            for field in result_records[0]["actual_memory_metrics"]
        }
        provider_outcomes = combine_provider_outcomes(
            [row["provider_outcomes"] for row in result_records]
        )
        prices = read_json(ROOT / "configs/trimem_v1/cost_plan.json")["model_pricing"]
        actual_usd = actual_usd_for_accounting(total_accounting, prices)
        summary = {
            "arm": stream_id, "runtime_arm": arm,
            "final_resume_cursor": session.task_cursor,
            "completed_target_count": len(tasks),
            "canonical_stream_cursor": session.next_sequence_index,
            "execution_lock_hash": execution_lock_hash, "namespace": session.namespace,
            "identity_seed_digest": identity_seed_evidence["digest"],
            "sequence_sha256": digest, "selected_checkpoint": selected_checkpoint,
            "selected_checkpoint_path": (
                checkpoint_file.resolve().relative_to(ROOT.resolve()).as_posix()
                if checkpoint_file is not None else None
            ),
            "candidate_id": (
                stream_id.removeprefix("M2-") if stream_id.startswith("M2-") else None
            ),
            "selected_prompt_candidate_id": selected_prompt_candidate_id,
            "runtime_lock_sha256": "sha256:" + runtime_lock.content_hash,
            "m2_policy_manifest_sha256": (
                "sha256:" + sha256_bytes(canonical_bytes(m2_manifest))
                if isinstance(m2_manifest, Mapping) else None
            ),
            "actual_accounting": total_accounting,
            "actual_memory_metrics": total_memory_metrics,
            "provider_outcomes": provider_outcomes,
            "actual_total_tokens": (
                # Responses reasoning_tokens is a reported subset of output_tokens.
                total_accounting["input_tokens"] + total_accounting["output_tokens"]
            ),
            "actual_usd": actual_usd,
            "resolved_count": sum(int(row["resolved"]) for row in result_records),
            "cell_status_counts": dict(sorted({
                name: sum(int(row["cell_status"] == name) for row in result_records)
                for name in {str(row["cell_status"]) for row in result_records}
            }.items())),
            "contained_failure_count": sum(
                int(row["cell_status"] != "AGENT_COMPLETED")
                for row in result_records
            ),
            "model_failure_count": sum(
                int(row.get("model_failure_class") is not None)
                for row in result_records
            ),
            "model_failure_distribution": dict(sorted({
                name: sum(
                    int(row.get("model_failure_class") == name)
                    for row in result_records
                )
                for name in {
                    str(row["model_failure_class"])
                    for row in result_records
                    if row.get("model_failure_class") is not None
                }
            }.items())),
            "model_failure_class_counts": dict(sorted({
                name: sum(
                    int(
                        (
                            canonical_scientific_failure_class(
                                row["model_failure_class"]
                            )
                            if row["model_failure_class"] is not None
                            else "NONE"
                        )
                        == name
                    )
                    for row in result_records
                )
                for name in {
                    (
                        canonical_scientific_failure_class(
                            row["model_failure_class"]
                        )
                        if row["model_failure_class"] is not None
                        else "NONE"
                    )
                    for row in result_records
                }
            }.items())),
            "partial_patch_count": sum(
                int(row.get("grader_patch_source") == "MODEL_PARTIAL_PATCH")
                for row in result_records
            ),
            "canonical_noop_count": sum(
                int(row.get("grader_patch_source") == "CANONICAL_FAILED_CELL_NOOP")
                for row in result_records
            ),
            "extraction_failure_count": sum(
                int(row.get("extraction_status") == "MEMORY_EXTRACTION_FAILED")
                for row in result_records
            ),
            "status": "PASS", "workspace_factory_hash": workspace_factory.content_hash,
        }
        write_json(output_root / f"{stream_id}.arm-summary.json", summary)
        return summary
    finally:
        if client is not None:
            close_paid_model_client(session, client)
        session.close()


def write_development_selection_artifacts(
    candidate_summaries: Sequence[Mapping[str, Any]], *, output_root: Path
) -> tuple[dict[str, Any], RuntimeLock, dict[str, Any]]:
    """Select deterministically and emit a reviewable post-DEV seal proposal."""

    compact = []
    for summary in candidate_summaries:
        completed = summary.get("completed_target_count")
        cell_counts = summary.get("cell_status_counts")
        failure_counts = summary.get("model_failure_class_counts")
        if (
            type(completed) is not int
            or completed <= 0
            or not isinstance(cell_counts, Mapping)
            or set(cell_counts) - set(SCIENTIFIC_CELL_STATUSES)
            or any(type(value) is not int or value < 0 for value in cell_counts.values())
            or sum(cell_counts.values()) != completed
            or summary.get("contained_failure_count")
            != completed - int(cell_counts.get("AGENT_COMPLETED", 0))
            or not isinstance(failure_counts, Mapping)
            or sum(failure_counts.values()) != completed
        ):
            raise BenchmarkExecutionError(
                "development candidate terminal summary is incomplete or malformed"
            )
        checkpoint_path = ROOT / str(summary.get("selected_checkpoint_path", ""))
        checkpoint = summary.get("selected_checkpoint")
        if not checkpoint_path.is_file() or not isinstance(checkpoint, Mapping):
            raise BenchmarkExecutionError("development candidate has no frozen final checkpoint")
        if read_json(checkpoint_path) != checkpoint:
            raise BenchmarkExecutionError("development candidate checkpoint file/content mismatch")
        compact.append({
            "candidate_id": summary.get("candidate_id"),
            "completed_target_count": summary.get("completed_target_count"),
            "final_resume_cursor": summary.get("final_resume_cursor"),
            "resolved_count": summary.get("resolved_count"),
            "actual_total_tokens": summary.get("actual_total_tokens"),
            "actual_usd": summary.get("actual_usd"),
            "sequence_sha256": summary.get("sequence_sha256"),
            "runtime_lock_sha256": summary.get("runtime_lock_sha256"),
            "m2_policy_manifest_sha256": summary.get("m2_policy_manifest_sha256"),
            "checkpoint_source_path": summary.get("selected_checkpoint_path"),
            "checkpoint_source_file_sha256": sha256_bytes(checkpoint_path.read_bytes()),
            "checkpoint_digest": checkpoint.get("digest"),
            "namespace": summary.get("namespace"),
        })
    selection = select_development_candidate(compact)
    selected_id = str(selection["selected_candidate_id"])
    selected_summary = next(row for row in candidate_summaries if row.get("candidate_id") == selected_id)
    selected_source = ROOT / str(selected_summary["selected_checkpoint_path"])
    promotion_root = ROOT / "artifacts/trimem_v1/development_selection"
    checkpoint_path = promotion_root / "selected_m2_checkpoint.json"
    atomic_write(checkpoint_path, selected_source.read_bytes())
    checkpoint = read_json(checkpoint_path)
    evidence = {
        "schema": "trimem/development-m2-selection-evidence/1.0",
        "status": "COMPLETE_PENDING_COMMIT_FREEZE_AND_HELDOUT_APPROVAL",
        "candidate_bundle_sha256": "sha256:" + sha256_bytes(
            canonical_bytes(load_m2_candidate_bundle())
        ),
        "candidate_summaries": compact,
        "selection": selection,
    }
    evidence_path = promotion_root / "development_selection_evidence.json"
    write_json(evidence_path, evidence)
    candidate = candidate_row(selected_id)
    proposal = {
        "schema": "trimem/selected-m2/1.0",
        "status": "FROZEN_AFTER_DEVELOPMENT",
        "candidate_bundle_path": "configs/trimem_v1/m2_candidate_bundles.json",
        "selected_candidate_id": selected_id,
        "selected_full_policy_path": candidate["full_policy_path"],
        "selected_full_policy_file_sha256": candidate["full_policy_file_sha256"],
        "selected_runtime_lock_sha256": candidate["runtime_lock_sha256"],
        "selected_checkpoint_path": checkpoint_path.relative_to(ROOT).as_posix(),
        "selected_checkpoint_file_sha256": sha256_bytes(checkpoint_path.read_bytes()),
        "selected_checkpoint_digest": checkpoint.get("digest"),
        "development_selection_evidence_path": evidence_path.relative_to(ROOT).as_posix(),
        "development_selection_evidence_sha256": sha256_bytes(evidence_path.read_bytes()),
        "heldout_execution": "PENDING_SEPARATE_EXEC_APPROVAL",
    }
    write_json(promotion_root / "selected_m2.proposed.json", proposal)
    write_json(output_root / "development-selection.json", evidence)
    return proposal, runtime_lock_for(selected_id), load_candidate_policy(selected_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=SPLITS, required=True)
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        validate_benchmark_environment()
        approval = validate_exec_approval(args.split, args.approval_file)
        manifest_targets, rows = load_frozen_rows(args.split, ROOT / ".trimem-exec/datasets")
        tasks = coding_tasks(manifest_targets, rows)
        output = ROOT / "artifacts/trimem_v1/benchmark_exec" / args.split
        output.mkdir(parents=True, exist_ok=True)
        write_external_approval_evidence(
            output,
            split=args.split,
            approval_path=args.approval_file,
            validated=approval,
        )
        cost = read_json(ROOT / "configs/trimem_v1/cost_plan.json")
        protocol_canary: Optional[dict[str, Any]] = None
        scientific_hard_cap: Mapping[str, Any] = approval["hard_cap"]
        if args.split == "development":
            canary_path = output / PROTOCOL_CANARY_RELATIVE_PATH
            if not canary_path.is_file():
                raise BenchmarkExecutionError(
                    "successful protocol canary evidence is required before DEV"
                )
            protocol_canary = read_json(canary_path)
            scientific_hard_cap = scientific_caps_after_protocol_canary(
                approval["hard_cap"],
                protocol_canary,
                expected_approval_sha256=approval["approval_artifact_sha256"],
            )
        if args.split == "development":
            selected_state = validate_selected_m2(require_frozen=False)
            if selected_state.get("status") != "PRE_DEVELOPMENT":
                raise BenchmarkExecutionError(
                    "development execution requires PRE_DEVELOPMENT selection state"
                )
            load_m2_candidate_bundle()
            planned_stream_ids = [
                *(f"M2-{candidate_id}" for candidate_id in CANDIDATE_IDS), "M0", "M1"
            ]
        else:
            validate_selected_m2(require_frozen=True)
            planned_stream_ids = list(ARMS)

        # Provision every stream's deterministic FK identities before any
        # harness, workspace, model, grader, or runtime object is opened. The
        # admin DSN is removed from the process environment immediately and
        # each seed call disposes its admin engine before returning.
        admin_database_url = os.environ.pop("TRIMEM_ADMIN_DATABASE_URL", "")
        runtime_database_url = os.environ.get("TRIMEM_DATABASE_URL", "")
        validate_database_role_boundary(admin_database_url, runtime_database_url)
        seed_evidence_by_stream: dict[str, Mapping[str, Any]] = {}
        seed_root = output / "identity-seeds"
        for planned_stream_id in planned_stream_ids:
            experiment_id = "trimemv1-" + approval["git_head"][:12] + "-" + re.sub(
                r"[^a-z0-9-]", "-", planned_stream_id.lower()
            )
            evidence = seed_benchmark_identities(
                admin_database_url=admin_database_url,
                experiment_id=experiment_id,
                stream_id=planned_stream_id,
                tasks=tasks,
                identity_resolver=repository_identity_resolver(
                    experiment_id, planned_stream_id
                ),
            )
            if "postgresql" in json.dumps(evidence).casefold() or "password" in json.dumps(evidence).casefold():
                raise BenchmarkExecutionError("identity seed evidence contains database credentials")
            seed_evidence_by_stream[planned_stream_id] = dict(evidence)
            write_json(seed_root / f"{planned_stream_id}.json", evidence)
        del admin_database_url
        if "TRIMEM_ADMIN_DATABASE_URL" in os.environ:
            raise BenchmarkExecutionError("admin database URL remained in runtime environment")

        harnesses = prepare_harnesses(ROOT / ".trimem-exec/harnesses")
        approval_digest = approval["approval_artifact_sha256"]
        ledger = AtomicBudgetLedger(
            output / "budget-ledger.json",
            approval_digest=approval_digest, caps=scientific_hard_cap, pricing=cost["model_pricing"],
        )
        benchmark_images, _ = image_entries(require_benchmark=True)
        summaries: list[dict[str, Any]] = []
        common_workspace_factory_hash: Optional[str] = None

        def run_stream(
            *, runtime_arm: str, stream_id: str, runtime_lock: RuntimeLock,
            m2_manifest: Optional[Mapping[str, Any]], checkpoint_path: Optional[Path],
            prompt_candidate_id: str,
        ) -> dict[str, Any]:
            nonlocal common_workspace_factory_hash
            # The identity is durably written before the namespace claim.  It is
            # therefore the earliest recovery marker; freshness is deliberately
            # later and may be absent when the process dies between claim and
            # the first task checkpoint.
            stream_resume = args.resume and (
                (output / f"{stream_id}.freshness.json").is_file()
                or _arm_identity_path(output, stream_id).is_file()
            )
            workspace, checkout_evidence = prepare_checkouts(
                tasks, manifest_targets, benchmark_images,
                ROOT / ".trimem-exec/checkouts" / args.split / stream_id,
                resume=stream_resume,
            )
            if common_workspace_factory_hash is None:
                common_workspace_factory_hash = workspace.content_hash
            elif workspace.content_hash != common_workspace_factory_hash:
                raise BenchmarkExecutionError("benchmark streams have different workspace/tool factory hashes")
            return run_arm_stream(
                split=args.split, arm=runtime_arm, stream_id=stream_id,
                runtime_lock=runtime_lock, m2_manifest=m2_manifest,
                dqn_checkpoint_path=checkpoint_path,
                selected_prompt_candidate_id=prompt_candidate_id,
                approval=approval, targets=manifest_targets,
                rows=rows, tasks=tasks, workspace_factory=workspace,
                checkout_evidence=checkout_evidence, harnesses=harnesses,
                output_root=output, ledger=ledger,
                database_url=runtime_database_url,
                qdrant_url=os.environ.get("TRIMEM_QDRANT_URL", ""), resume=stream_resume,
                identity_seed_evidence=seed_evidence_by_stream[stream_id],
            )

        # One process/job owns one phase-scoped ledger. Every online memory
        # stream is serial and has its own namespace; there is no task matrix.
        if args.split == "development":
            candidate_summaries = []
            for candidate_id in CANDIDATE_IDS:
                candidate_summary = run_stream(
                    runtime_arm="M2", stream_id=f"M2-{candidate_id}",
                    runtime_lock=runtime_lock_for(candidate_id),
                    m2_manifest=load_candidate_policy(candidate_id), checkpoint_path=None,
                    prompt_candidate_id=candidate_id,
                )
                candidate_summaries.append(candidate_summary)
                summaries.append(candidate_summary)
            proposal, selected_runtime_lock, _ = write_development_selection_artifacts(
                candidate_summaries, output_root=output
            )
            selected_candidate_id = str(proposal["selected_candidate_id"])
            for arm in ("M0", "M1"):
                summaries.append(run_stream(
                    runtime_arm=arm, stream_id=arm, runtime_lock=selected_runtime_lock,
                    m2_manifest=None, checkpoint_path=None,
                    prompt_candidate_id=selected_candidate_id,
                ))
        else:
            selected = validate_selected_m2(require_frozen=True)
            selected_candidate_id = str(selected["selected_candidate_id"])
            selected_runtime_lock = runtime_lock_for(selected_candidate_id)
            selected_policy = load_candidate_policy(selected_candidate_id)
            selected_checkpoint_path = ROOT / str(selected["selected_checkpoint_path"])
            for arm in ARMS:
                summaries.append(run_stream(
                    runtime_arm=arm, stream_id=arm, runtime_lock=selected_runtime_lock,
                    m2_manifest=selected_policy if arm == "M2" else None,
                    checkpoint_path=selected_checkpoint_path if arm == "M2" else None,
                    prompt_candidate_id=selected_candidate_id,
                ))
        phase_evidence = validate_phase_completion(
            output,
            split=args.split,
            summaries=summaries,
            ledger=ledger,
            hard_cap=scientific_hard_cap,
            pricing=cost["model_pricing"],
        )
        if protocol_canary is not None:
            phase_evidence["protocol_canary"] = protocol_canary
            phase_evidence["global_actual_accounting"] = validate_global_phase_accounting(
                approval["hard_cap"],
                protocol_canary,
                {
                    "paid_model_calls": phase_evidence["actual_accounting"]["paid_model_calls"],
                    "input_tokens": phase_evidence["actual_accounting"]["input_tokens"],
                    "cached_input_tokens": phase_evidence["actual_accounting"]["cached_input_tokens"],
                    "output_tokens": phase_evidence["actual_accounting"]["output_tokens"],
                    "total_usd": phase_evidence["actual_usd"],
                },
            )
        print(json.dumps(
            {"phase_evidence": phase_evidence, "streams": summaries, "status": "PASS"},
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
