"""Fail-closed one-time DEVELOPMENT_TUNING ``_016`` approval-delay recovery.

D1.16 preserves the unapproved ``_015`` request and cancelled workflow as
immutable history.  It separates immutable loader-attestation identity from
live freshness: request creation and the hosted branch trigger require a fresh
attestation, while delayed protected jobs revalidate the live runner and exact
loader instead of expiring the committed request.  Importing this module has no
network, Docker, grader, credential, image, or model side effect.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import threading
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d115 as d115


d114 = d115.d114
d113 = d115.d113
d112 = d115.d112

EXPECTED_REPOSITORY = d115.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d115.EXPECTED_BRANCH
EXPECTED_REF = d115.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d115.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d115.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d115.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d115.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d115.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d115.EXPECTED_BASE_HEAD

PREVIOUS_SOURCE_HEAD = "de4b42be532910bf1a6349241b535ca31a93b6af"
PREVIOUS_EXECUTION_HEAD = "221a23be33597fdfa37b9b2d9ed2a7ffba2767f3"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_015.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "1fc04b6e0f85a041506e42ec83671b9a6ffd6bb3311f34bbff1f9173683617cc"
)
PREVIOUS_SENTINEL_BYTES = 38_583
PREVIOUS_SENTINEL_BLOB_OID = "7d78ea1f0c43764244d756324f37a8d08969b8ff"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "6274e8384ac521d32e74f4b3200d6bf0c6161b92e79f8f9742e358f3c0669498"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "832f13d94dcedcbcb0c2fc45531c6e664f243a1b28ceabf8692f7f24ae849633"
)
PREVIOUS_RUN_ID = 34_160_843_621
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_FAILURE_SUBTYPE = "IMMUTABLE_LOADER_REHEARSAL_WALL_CLOCK_EXPIRY"
PREVIOUS_FAILURE_CLASSIFICATION = (
    "PRE_APPROVAL_CONTROL_PLANE_FRESHNESS_COUPLING_AVOIDED"
)
PREVIOUS_FAILURE_MESSAGE = (
    "the immutable loader rehearsal would expire while protected approval waits"
)
PREVIOUS_FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d116/exec_015_preapproval_freshness_scope_failure.json"
)

STARTING_SOURCE_HEAD = PREVIOUS_EXECUTION_HEAD
STARTING_FREEZE_SHA256 = PREVIOUS_SOURCE_FREEZE_SHA256
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_016"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.16"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_016.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_016_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-016"

AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_016_recovery_amendment.json"
)
AMENDMENT_SCHEMA = "trimem/development-exec-016-approval-delay-amendment/1.0"
INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_016_recovery_inventory.json"
)
INVENTORY_SCHEMA = "trimem/development-exec-016-approval-delay-inventory/1.0"
AMENDMENT_CLASSIFICATION = (
    "POST_EXEC_015_ZERO_MODEL_APPROVAL_DELAY_FRESHNESS_RECOVERY"
)
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_015_CANCELLED_READY_FOR_EXEC_016_REQUEST"
)
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_016_REQUEST"
REPORT_PATH = "reports/TRIMEM_D116_EXEC_016_RECOVERY.md"
TRIGGER_PATH = "scripts/trimem_development_trigger_d116.py"
LOADER_REHEARSAL_COLLECTOR_PATH = "scripts/trimem_d116_loader_rehearsal.py"

FREEZE_PATH = d115.FREEZE_PATH
FREEZE_SCHEMA = d115.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.16"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.16"

MODEL_ID = d115.MODEL_ID
REASONING_EFFORT = d115.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d115.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d115.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d115.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d115.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d115.ACTIVATION_ZERO_COUNTERS
REMOTE_GATE_SPECS = d115.REMOTE_GATE_SPECS
REQUIRED_REMOTE_GATE_WORKFLOWS = d115.REQUIRED_REMOTE_GATE_WORKFLOWS
PRESERVED_SCIENTIFIC_PATHS = d115.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d115.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d115.EXECUTION_CONTRACT_PATHS
CHECKOUT_ACTION_SHA = d115.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d115.SETUP_PYTHON_ACTION_SHA
HEX40 = d115.HEX40

DevelopmentTriggerError = d115.DevelopmentTriggerError
require = d115.require
canonical_bytes = d115.canonical_bytes
strict_json = d115.strict_json
git = d115.git
commit_bytes = d115.commit_bytes
resolve_repository_root = d115.resolve_repository_root
_is_ancestor = d115._is_ancestor

ALLOWED_RECOVERY_PATHS = frozenset(
    {
        ".gitattributes",
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/trimem-benchmark.yml",
        AMENDMENT_PATH,
        INVENTORY_PATH,
        PREVIOUS_FAILURE_FIXTURE_PATH,
        "artifacts/trimem_v1/freeze.json",
        "artifacts/trimem_v1/readiness_requirements.json",
        REPORT_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        LOADER_REHEARSAL_COLLECTOR_PATH,
        "scripts/trimem_multi_swe_contract.py",
        TRIGGER_PATH,
        "scripts/trimem_freeze.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d114_post_setup_environment.py",
        "tests/unit/test_trimem_d116_trigger.py",
        "tests/unit/test_trimem_d115_status_and_reseal.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    }
)
REQUIRED_RECOVERY_CHANGES = {
    ".gitattributes": "M",
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    PREVIOUS_FAILURE_FIXTURE_PATH: "A",
    "artifacts/trimem_v1/freeze.json": "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    REPORT_PATH: "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    LOADER_REHEARSAL_COLLECTOR_PATH: "A",
    "scripts/trimem_multi_swe_contract.py": "M",
    TRIGGER_PATH: "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d114_post_setup_environment.py": "M",
    "tests/unit/test_trimem_d116_trigger.py": "A",
    "tests/unit/test_trimem_d115_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}
ALLOWED_ACTIVATION_PATHS = ALLOWED_RECOVERY_PATHS
REQUIRED_ACTIVATION_CHANGES = REQUIRED_RECOVERY_CHANGES

ACTIVATION_BINDING_PATHS = {
    "gitattributes_sha256": ".gitattributes",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "d116_amendment_sha256": AMENDMENT_PATH,
    "d116_inventory_sha256": INVENTORY_PATH,
    "d116_run_fixture_sha256": PREVIOUS_FAILURE_FIXTURE_PATH,
    "d116_trigger_reader_sha256": TRIGGER_PATH,
    "loader_rehearsal_collector_sha256": LOADER_REHEARSAL_COLLECTOR_PATH,
    "multi_swe_contract_sha256": "scripts/trimem_multi_swe_contract.py",
    "readiness_requirements_sha256": "artifacts/trimem_v1/readiness_requirements.json",
    "verify_ready_sha256": "scripts/trimem_verify_ready.py",
}

_D115_CONTEXT_LOCK = threading.RLock()


def _context_bindings() -> dict[str, Any]:
    return {
        "PREVIOUS_SOURCE_HEAD": PREVIOUS_SOURCE_HEAD,
        "PREVIOUS_EXECUTION_HEAD": PREVIOUS_EXECUTION_HEAD,
        "PREVIOUS_SENTINEL_PATH": PREVIOUS_SENTINEL_PATH,
        "PREVIOUS_SENTINEL_SHA256": PREVIOUS_SENTINEL_SHA256,
        "PREVIOUS_SENTINEL_BYTES": PREVIOUS_SENTINEL_BYTES,
        "PREVIOUS_SENTINEL_BLOB_OID": PREVIOUS_SENTINEL_BLOB_OID,
        "PREVIOUS_REQUEST_PAYLOAD_SHA256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
        "PREVIOUS_SOURCE_FREEZE_SHA256": PREVIOUS_SOURCE_FREEZE_SHA256,
        "PREVIOUS_RUN_ID": PREVIOUS_RUN_ID,
        "PREVIOUS_RUN_ATTEMPT": PREVIOUS_RUN_ATTEMPT,
        "PREVIOUS_FAILURE_SUBTYPE": PREVIOUS_FAILURE_SUBTYPE,
        "PREVIOUS_FAILURE_CLASSIFICATION": PREVIOUS_FAILURE_CLASSIFICATION,
        "PREVIOUS_FAILURE_MESSAGE": PREVIOUS_FAILURE_MESSAGE,
        "PREVIOUS_FAILURE_FIXTURE_PATH": PREVIOUS_FAILURE_FIXTURE_PATH,
        "STARTING_SOURCE_HEAD": STARTING_SOURCE_HEAD,
        "STARTING_FREEZE_SHA256": STARTING_FREEZE_SHA256,
        "BASELINE_SOURCE_HEAD": BASELINE_SOURCE_HEAD,
        "BASELINE_FREEZE_SHA256": BASELINE_FREEZE_SHA256,
        "REQUEST_ID": REQUEST_ID,
        "REQUEST_SCHEMA": REQUEST_SCHEMA,
        "SENTINEL_PATH": SENTINEL_PATH,
        "ACTIVE_SENTINEL_PATH": ACTIVE_SENTINEL_PATH,
        "CURRENT_ACTIVE_WORKFLOW_REF": CURRENT_ACTIVE_WORKFLOW_REF,
        "REQUIRED_EXTERNAL_AUTHORIZATION": REQUIRED_EXTERNAL_AUTHORIZATION,
        "EXPECTED_CONCURRENCY_GROUP": EXPECTED_CONCURRENCY_GROUP,
        "AMENDMENT_PATH": AMENDMENT_PATH,
        "AMENDMENT_SCHEMA": AMENDMENT_SCHEMA,
        "INVENTORY_PATH": INVENTORY_PATH,
        "INVENTORY_SCHEMA": INVENTORY_SCHEMA,
        "AMENDMENT_CLASSIFICATION": AMENDMENT_CLASSIFICATION,
        "AMENDMENT_STATUS": AMENDMENT_STATUS,
        "AMENDMENT_ENDPOINT": AMENDMENT_ENDPOINT,
        "REPORT_PATH": REPORT_PATH,
        "TRIGGER_PATH": TRIGGER_PATH,
        "LOADER_REHEARSAL_COLLECTOR_PATH": LOADER_REHEARSAL_COLLECTOR_PATH,
        "REMOTE_GATE_SCHEMA": REMOTE_GATE_SCHEMA,
        "RUNNER_READINESS_SCHEMA": RUNNER_READINESS_SCHEMA,
        "ALLOWED_RECOVERY_PATHS": ALLOWED_RECOVERY_PATHS,
        "REQUIRED_RECOVERY_CHANGES": REQUIRED_RECOVERY_CHANGES,
        "ALLOWED_ACTIVATION_PATHS": ALLOWED_ACTIVATION_PATHS,
        "REQUIRED_ACTIVATION_CHANGES": REQUIRED_ACTIVATION_CHANGES,
        "ACTIVATION_BINDING_PATHS": ACTIVATION_BINDING_PATHS,
        "_load_previous_request": _load_previous_request,
        "_validate_previous_run_fixture": _validate_previous_run_fixture,
        "_validate_recovery_diff": _validate_recovery_diff,
        "_validate_preserved_science": _validate_preserved_science,
        "_validate_workflow": _validate_workflow,
        "_validate_documents": _validate_documents,
        "_validate_source_impl": _validate_source_impl,
        "_build_request_impl": _build_request_impl,
        "_validate_request_impl": _validate_request_impl,
        "_validate_sentinel_commit_impl": _validate_sentinel_commit_impl,
    }


@contextmanager
def _d116_runtime_context() -> Iterator[None]:
    """Temporarily bind the inherited D1.15 engine to D1.16."""

    # Every older overlay mutates globals in the next module down.  Hold the
    # complete inherited lock chain before changing D1.15 so another
    # generation can never observe a mixed D1.15/D1.16 identity.
    with (
        _D115_CONTEXT_LOCK,
        d115._D114_CONTEXT_LOCK,
        d114._D113_CONTEXT_LOCK,
        d113._D112_CONTEXT_LOCK,
    ):
        bindings = _context_bindings()
        previous = {name: getattr(d115, name) for name in bindings}
        try:
            for name, value in bindings.items():
                setattr(d115, name, value)
            yield
        finally:
            for name, value in reversed(tuple(previous.items())):
                setattr(d115, name, value)


def _tree_entry(repository: Path, commit: str, path: str) -> tuple[str, str]:
    raw = git(repository, "ls-tree", commit, "--", path).strip()
    parts = raw.split(None, 3)
    require(len(parts) == 4 and parts[1] == "blob", f"Git blob is missing: {path}")
    return parts[0], parts[2]


def validate_loader_rehearsal_record(
    value: Any,
    *,
    source_head: str,
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a frozen loader record without coupling it to today's clock.

    The unchanged D1.15 validator still checks the complete field set, exact
    alias/loader identities, hashes, bindings, zero counters, and timestamp
    syntax.  Anchoring ``now`` to that parsed observation disables only the
    present-wall-clock age comparison.  Live entry points below call the same
    strict validator with their actual comparison time.
    """

    require(isinstance(value, Mapping), "exact loader rehearsal evidence is missing")
    observed_at = d115._utc_datetime(value.get("observed_at_utc"))
    return d115.validate_loader_rehearsal(
        value,
        source_head=source_head,
        runner_readiness=runner_readiness,
        now=observed_at,
    )


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _015 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _015 execution parent differs",
    )
    changes = git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        PREVIOUS_EXECUTION_HEAD,
    ).splitlines()
    require(
        changes == [f"A\t{PREVIOUS_SENTINEL_PATH}"],
        "immutable _015 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _015 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and b"\r" not in raw,
        "immutable _015 sentinel raw bytes differ",
    )
    previous = strict_json(raw)
    bindings = previous.get("bindings")
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.15"
        and previous.get("request_id") == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015"
        and previous.get("request_path") == PREVIOUS_SENTINEL_PATH
        and previous.get("source_head") == PREVIOUS_SOURCE_HEAD
        and previous.get("request_sha256")
        == "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
        and previous.get("actual_execution_authorized") is False
        and previous.get("external_execution_approval_received") is False
        and isinstance(bindings, Mapping)
        and bindings.get("freeze_sha256")
        == "sha256:" + PREVIOUS_SOURCE_FREEZE_SHA256
        and all(value == 0 for value in previous.get("activation_actuals", {}).values())
        and all(value == 0 for value in previous.get("pre_execution_actuals", {}).values())
        and raw == canonical_bytes(previous, trailing_lf=True),
        "immutable _015 request identity, bytes, or zero authority differs",
    )
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.16 source does not preserve immutable EXEC _015",
    )
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical _015 request changed after cancellation",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_016 exists in recovery-source history",
    )
    return previous


def _validate_previous_run_fixture(
    repository: Path, source_head: str
) -> dict[str, Any]:
    value = strict_json(commit_bytes(repository, source_head, PREVIOUS_FAILURE_FIXTURE_PATH))
    workflow = value.get("workflow")
    jobs = value.get("jobs")
    actuals = value.get("observed_actuals")
    approval = value.get("approval_boundary")
    root_cause = value.get("root_cause")
    require(
        value.get("schema") == "trimem/d116-exec-015-preapproval-cancellation/1.0"
        and value.get("repository") == EXPECTED_REPOSITORY
        and value.get("branch") == EXPECTED_BRANCH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("execution_head") == PREVIOUS_EXECUTION_HEAD,
        "EXEC _015 cancellation fixture identity differs",
    )
    require(
        workflow
        == {
            "conclusion": "cancelled",
            "created_at": "2026-09-07T20:49:15Z",
            "event": "push",
            "head_sha": PREVIOUS_EXECUTION_HEAD,
            "html_url": (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                "actions/runs/34160843621"
            ),
            "id": PREVIOUS_RUN_ID,
            "run_attempt": PREVIOUS_RUN_ATTEMPT,
            "status": "completed",
            "updated_at": "2026-09-08T01:40:09Z",
        },
        "EXEC _015 workflow history differs",
    )
    require(
        jobs
        == [
            {
                "completed_at": "2026-09-07T20:49:40Z",
                "conclusion": "success",
                "id": 101_862_200_095,
                "name": "branch-trigger-preflight",
                "started_at": "2026-09-07T20:49:18Z",
            },
            {
                "completed_at": "2026-09-07T20:50:41Z",
                "conclusion": "success",
                "id": 101_862_274_185,
                "name": "bounded-context-preflight",
                "started_at": "2026-09-07T20:49:43Z",
            },
            {
                "completed_at": "2026-09-08T01:40:07Z",
                "conclusion": "cancelled",
                "id": 101_862_456_797,
                "name": "frozen-serial-phase",
                "started_at": "2026-09-07T20:50:41Z",
            },
        ],
        "EXEC _015 workflow job funnel differs",
    )
    require(
        actuals
        == {
            "benchmark_image_pulls": 0,
            "grader_containers": 0,
            "input_tokens": 0,
            "model_api_calls": 0,
            "model_generation_calls": 0,
            "model_metadata_requests": 0,
            "official_grader_runs": 0,
            "output_tokens": 0,
            "paid_model_calls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        }
        and approval
        == {
            "deployment_approved": False,
            "environment_secret_count": 0,
            "protected_environment_entered": False,
        }
        and root_cause
        == {
            "classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "failure_subtype": PREVIOUS_FAILURE_SUBTYPE,
            "loader_rehearsal_observed_at_utc": "2026-09-07T20:43:18.456Z",
            "maximum_age_seconds": 3600,
            "scientific_result": False,
        },
        "EXEC _015 pre-execution actuals or approval boundary differ",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    require(
        source_head != PREVIOUS_EXECUTION_HEAD
        and _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.16 source is not a strict descendant of immutable EXEC _015",
    )
    lines = git(
        repository,
        "diff",
        "--no-ext-diff",
        "--name-status",
        "--no-renames",
        PREVIOUS_EXECUTION_HEAD,
        source_head,
    ).splitlines()
    changes: dict[str, str] = {}
    for line in lines:
        pieces = line.split("\t")
        require(len(pieces) == 2, "D1.16 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.16 diff status is forbidden: {status}")
        require(path in ALLOWED_RECOVERY_PATHS, f"D1.16 changed forbidden path: {path}")
        require(path not in changes, f"D1.16 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.16 recovery change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path),
            f"frozen scientific input changed during D1.16 recovery: {path}",
        )


def _validate_workflow(repository: Path, source_head: str) -> None:
    try:
        workflow = commit_bytes(repository, source_head, EXPECTED_WORKFLOW_PATH).decode(
            "utf-8", errors="strict"
        )
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError("benchmark workflow is not UTF-8") from exc
    require(
        workflow.count(f"      - {SENTINEL_PATH}\n") == 1
        and f"      - {PREVIOUS_SENTINEL_PATH}\n" not in workflow,
        "active push sentinel is not exclusively _016",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-015" not in workflow,
        "_016 concurrency identity differs",
    )
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        all(workflow.count(marker) == 1 for marker in (branch_marker, bounded_marker, frozen_marker)),
        "D1.16 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(branch_start < bounded_start < frozen_start, "D1.16 job order differs")
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    command = "python -I -S scripts/trimem_development_trigger_d116.py"
    require(
        branch_job.count(command) == 1
        and bounded_job.count(command) == 1
        and frozen_job.count(command) == 4
        and "scripts/trimem_development_trigger_d115.py" not in workflow,
        "active trigger validator is not exclusively D1.16 _016",
    )
    for label, job in (("bounded", bounded_job), ("protected", frozen_job)):
        require(
            job.count(d115.ALIAS_CHECK_COMMAND) == 1
            and job.count(d115.LOADER_PREFLIGHT_COMMAND_FRAGMENT) == 1
            and job.count("validate_official_harness_loader_preflight_evidence") == 2
            and job.index(d115.COMPILED_PREFIX_ALIAS_PATH)
            < job.index(d115.LOADER_PREFLIGHT_COMMAND_FRAGMENT),
            f"{label} exact alias/loader validation differs",
        )
    exact_selector = (
        "runs-on: [self-hosted, linux, x64, trimem-ubuntu-24.04, trimem-benchmark]"
    )
    require(
        "runs-on: ubuntu-24.04" in branch_job
        and exact_selector not in branch_job
        and exact_selector in bounded_job
        and exact_selector in frozen_job
        and "environment:" not in workflow[:frozen_start]
        and frozen_job.count("environment: trimem-benchmark-exec") == 1
        and "secrets." not in workflow[:frozen_start]
        and workflow.count("github.run_attempt == 1") >= 2,
        "D1.16 hosted/self-hosted/protected boundary differs",
    )
    for action, digest in (
        ("actions/checkout", CHECKOUT_ACTION_SHA),
        ("actions/setup-python", SETUP_PYTHON_ACTION_SHA),
    ):
        require(
            f"{action}@v" not in workflow and f"{action}@{digest}" in workflow,
            f"D1.16 workflow action is mutable: {action}",
        )


def _validate_documents(repository: Path, source_head: str) -> None:
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    expected_changed_paths = list(_validate_recovery_diff(repository, source_head))
    require(
        amendment.get("schema") == AMENDMENT_SCHEMA
        and inventory.get("schema") == INVENTORY_SCHEMA
        and amendment.get("classification") == AMENDMENT_CLASSIFICATION
        and inventory.get("classification") == AMENDMENT_CLASSIFICATION
        and amendment.get("status") == AMENDMENT_STATUS
        and inventory.get("status") == AMENDMENT_STATUS
        and amendment.get("endpoint") == AMENDMENT_ENDPOINT
        and inventory.get("source_changed_paths") == expected_changed_paths,
        "D1.16 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_015_cancelled_unapproved") is True
        and authority.get("request_015_rerun_allowed") is False
        and authority.get("request_016_request_creation_authorized") is True
        and authority.get("request_016_created_in_source") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_016_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.16 authority boundary differs",
    )


def _validate_source_impl(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    require(
        git(repository, "cat-file", "-t", source_head).strip() == "commit",
        "source HEAD is not a commit",
    )
    changes = _validate_recovery_diff(repository, source_head)
    previous = _load_previous_request(repository, source_head)
    fixture = _validate_previous_run_fixture(repository, source_head)
    _validate_preserved_science(repository, source_head)
    _validate_workflow(repository, source_head)
    with d114._d114_runtime_context(), d113._d113_runtime_context():
        d112._validate_remote_gate_workflow_contracts(repository, source_head)
        target_order, hard_cap = d112._validate_frozen_science_documents(
            repository, source_head
        )
    _validate_documents(repository, source_head)
    require(
        previous.get("exact_model")
        == {
            "base_url": "https://api.openai.com/v1",
            "model_id": MODEL_ID,
            "reasoning_effort": REASONING_EFFORT,
            "same_snapshot_for": [
                "decomposition",
                "solve",
                "experience_extraction",
            ],
        }
        and previous.get("hard_caps") == hard_cap
        and previous.get("scientific_workload", {}).get("target_order")
        == target_order
        and previous.get("scientific_workload", {}).get("stream_order")
        == list(EXPECTED_STREAM_ORDER),
        "scientific identity differs from immutable _015",
    )
    bindings = d114._validate_freeze_and_bindings(repository, source_head, previous)
    return {
        "activation_changes": changes,
        "bindings": bindings,
        "failure_fixture": fixture,
        "hard_cap": hard_cap,
        "previous_request": previous,
        "target_order": target_order,
    }


def _request_execution_contracts(bindings: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(d115._request_execution_contracts(bindings)))
    result["approval_delay_freshness"] = {
        "immutable_loader_attestation": "IDENTITY_ONLY_AFTER_BRANCH_TRIGGER",
        "live_freshness_required_at": [
            "request_write",
            "branch_trigger",
            "unprotected_bounded_preflight",
        ],
        "protected_substitute": [
            "live_protected_runner_reobservation",
            "exact_protected_harness_loader_preflight",
        ],
    }
    return result


def _build_request_impl(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
    loader_rehearsal: Mapping[str, Any],
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    validated = _validate_source_impl(repository, source_head)
    gates = d115._validate_remote_gate_evidence(
        remote_gate_evidence, source_head=source_head
    )
    readiness = d115._validate_runner_readiness(
        runner_readiness, source_head=source_head
    )
    rehearsal = validate_loader_rehearsal_record(
        loader_rehearsal,
        source_head=source_head,
        runner_readiness=readiness,
    )
    previous = validated["previous_request"]
    bindings = validated["bindings"]
    payload = {
        "actual_execution_authorized": False,
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "amendment_classification": AMENDMENT_CLASSIFICATION,
        "authorization_semantics": (
            "This sentinel creates one push run only. Protected execution requires "
            "one distinct approval bound to the sentinel commit, recovery source, "
            "freeze, request bytes, workflow run ID/attempt, caps, actor, timestamp, "
            "nonce, legal acceptance, and exact OpenAI-key commitment."
        ),
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "control_plane": deepcopy(dict(previous["control_plane"])),
        "d116_execution_contracts": _request_execution_contracts(bindings),
        "exact_model": deepcopy(dict(previous["exact_model"])),
        "external_execution_approval_received": False,
        "hard_caps": validated["hard_cap"],
        "loader_rehearsal": rehearsal,
        "phase": EXPECTED_PHASE,
        "pre_execution_actuals": {
            "benchmark_target_image_pulls": 0,
            "cached_input_tokens": 0,
            "completed_task_arm_runs": 0,
            "exact_model_metadata_requests": 0,
            "grader_containers": 0,
            "input_tokens": 0,
            "model_generation_calls": 0,
            "official_grader_runs": 0,
            "output_tokens": 0,
            "paid_model_calls": 0,
            "protocol_canary_generation_calls": 0,
            "provider_generation_calls": 0,
            "reasoning_tokens": 0,
            "scientific_model_calls": 0,
            "support_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "prohibited_actions": [
            "DEVELOPMENT_TUNING_EXEC_REQUEST_015_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_017",
            "HELDOUT_BENCHMARK",
            "component_ablation",
            "grader_smoke_rerun",
            "merge_tag_or_release",
            "model_or_reasoning_change",
            "post_start_code_approval_target_candidate_or_cap_change",
        ],
        "protected_environment": {
            "environment_name": "trimem-benchmark-exec",
            "permitted_secret_names": [
                "OPENAI_API_KEY",
                "TRIMEM_EXEC_APPROVAL_B64",
                "TRIMEM_EVIDENCE_PASSPHRASE",
            ],
            "sentinel_contains_execution_authority": False,
        },
        "recovery_provenance": {
            "benchmark_image_pulls": 0,
            "bounded_context_preflight": "PASS",
            "cancelled_before_approval": True,
            "completed_terminal_cells": 0,
            "deployment_approved": False,
            "environment_secret_count": 0,
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "grader_containers": 0,
            "model_api_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_payload_sha256": (
                "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
            ),
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "previous_source_head": PREVIOUS_SOURCE_HEAD,
            "protected_environment_entered": False,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "remote_gate_evidence": gates,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "required_external_approval_fields": list(DEVELOPMENT_APPROVAL_FIELDS),
        "required_external_authorization": REQUIRED_EXTERNAL_AUTHORIZATION,
        "requires_external_approval": True,
        "runner_readiness": readiness,
        "schema": REQUEST_SCHEMA,
        "scientific_workload": deepcopy(dict(previous["scientific_workload"])),
        "source_head": source_head,
        "workflow_path": EXPECTED_WORKFLOW_PATH,
    }
    return {
        **payload,
        "request_sha256": "sha256:"
        + hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def _validate_request_impl(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    value = strict_json(raw)
    gates = d115._validate_remote_gate_evidence(
        value.get("remote_gate_evidence"), source_head=source_head
    )
    readiness = d115._validate_runner_readiness(
        value.get("runner_readiness"), source_head=source_head
    )
    rehearsal = validate_loader_rehearsal_record(
        value.get("loader_rehearsal"),
        source_head=source_head,
        runner_readiness=readiness,
    )
    expected = _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
        loader_rehearsal=rehearsal,
    )
    require(value == expected, "_016 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_016 request bytes are not canonical UTF-8 plus one LF",
    )
    return value


def _validate_sentinel_commit_impl(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(HEX40.fullmatch(after) is not None, "trigger commit SHA is invalid")
    if require_checked_out_head:
        require(git(repository, "rev-parse", "HEAD").strip() == after, "HEAD differs")
    parents = git(repository, "rev-list", "--parents", "-n", "1", after).split()
    require(len(parents) == 2, "trigger must be a single-parent commit")
    parent = parents[1]
    if expected_parent is not None:
        require(parent == expected_parent, "trigger parent differs from push before SHA")
    changes = git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        after,
    ).splitlines()
    require(
        changes == [f"A\t{SENTINEL_PATH}"],
        "trigger commit is not the exclusive _016 sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "_016 sentinel is not a regular non-executable blob")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_016 already exists before the trigger commit",
    )
    return _validate_request_impl(
        repository, commit_bytes(repository, after, SENTINEL_PATH), source_head=parent
    )


def validate_correction_source(
    repository: Path,
    source_head: str | None = None,
    *,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    with _d116_runtime_context():
        return d115.validate_correction_source(
            repository,
            source_head,
            require_checked_out_head=require_checked_out_head,
        )


def build_request(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
    loader_rehearsal: Mapping[str, Any],
) -> dict[str, Any]:
    with _d116_runtime_context():
        return d115.build_request(
            repository,
            source_head=source_head,
            remote_gate_evidence=remote_gate_evidence,
            runner_readiness=runner_readiness,
            loader_rehearsal=loader_rehearsal,
        )


def validate_request(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    with _d116_runtime_context():
        return d115.validate_request(repository, raw, source_head=source_head)


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    with _d116_runtime_context():
        return d115.validate_sentinel_commit(
            repository,
            after,
            expected_parent=expected_parent,
            require_checked_out_head=require_checked_out_head,
        )


def validate_branch_trigger(
    repository: Path,
    event_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    now: Any = None,
) -> dict[str, Any]:
    with _d116_runtime_context():
        repository = resolve_repository_root(repository)
        event = strict_json(event_path.read_bytes())
        require(isinstance(event, Mapping), "push event is not an object")
        before, after = event.get("before"), event.get("after")
        require(
            isinstance(before, str)
            and HEX40.fullmatch(before) is not None
            and isinstance(after, str)
            and HEX40.fullmatch(after) is not None,
            "push before/after SHA is invalid",
        )
        request = d115.validate_sentinel_commit(
            repository,
            after,
            expected_parent=before,
            require_checked_out_head=True,
        )
        d115.validate_loader_rehearsal(
            request.get("loader_rehearsal"),
            source_head=before,
            runner_readiness=request.get("runner_readiness"),
            now=now,
        )
        return d115.validate_branch_trigger(
            repository, event_path, environ=environ
        )


def _delegate(name: str, *args: Any, **kwargs: Any) -> Any:
    with _d116_runtime_context():
        return getattr(d115, name)(*args, **kwargs)


def write_request(repository: Path) -> dict[str, Any]:
    return _delegate("write_request", repository)


def validate_runner_host_preflight(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_runner_host_preflight", repository, event_path, **kwargs)


def validate_pre_setup_cache_host(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    with _d116_runtime_context():
        environment = os.environ if kwargs.get("environ") is None else kwargs["environ"]
        if environment.get("GITHUB_JOB") == "bounded-context-preflight":
            event = strict_json(event_path.read_bytes())
            require(isinstance(event, Mapping), "push event is not an object")
            before, after = event.get("before"), event.get("after")
            require(
                isinstance(before, str)
                and HEX40.fullmatch(before) is not None
                and isinstance(after, str)
                and HEX40.fullmatch(after) is not None,
                "push before/after SHA is invalid",
            )
            request = d115.validate_sentinel_commit(
                repository,
                after,
                expected_parent=before,
                require_checked_out_head=True,
            )
            d115.validate_loader_rehearsal(
                request.get("loader_rehearsal"),
                source_head=before,
                runner_readiness=request.get("runner_readiness"),
                now=kwargs.get("now"),
            )
        return d115.validate_pre_setup_cache_host(repository, event_path, **kwargs)


def validate_protected_runner_preflight(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_protected_runner_preflight", repository, event_path, **kwargs)


def start_protected_services(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("start_protected_services", repository, event_path, **kwargs)


def verify_protected_services(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("verify_protected_services", repository, event_path, **kwargs)


def cleanup_protected_services(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("cleanup_protected_services", repository, event_path, **kwargs)


ZERO_SCIENTIFIC_ACTUALS: dict[str, int | float] = {
    "benchmark_image_pulls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "model_api_calls": 0,
    "model_generation_calls": 0,
    "model_metadata_requests": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_usd": 0.0,
}


def current_failure_record() -> dict[str, Any]:
    """Return the immutable, zero-science EXEC ``_015`` cancellation state."""

    return {
        "classification": AMENDMENT_CLASSIFICATION,
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "failure_boundary": {
            "bounded_context_preflight": "PASSED",
            "branch_trigger_preflight": "PASSED",
            "frozen_serial_phase": "CANCELLED_WHILE_WAITING_FOR_APPROVAL",
            "protected_environment_entered": False,
        },
        "failure_subtype": PREVIOUS_FAILURE_SUBTYPE,
        "observed_scientific_actuals": dict(ZERO_SCIENTIFIC_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_015_rerun_allowed": False,
            "request_016_execution_authorized": False,
        },
        "request": {
            "id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015",
            "path": PREVIOUS_SENTINEL_PATH,
            "payload_sha256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": PREVIOUS_SENTINEL_SHA256,
            "source_head": PREVIOUS_SOURCE_HEAD,
        },
        "root_cause": {
            "loader_rehearsal_maximum_age_seconds": (
                d115.MAXIMUM_RUNNER_READINESS_AGE_SECONDS
            ),
            "recovery_rule": (
                "keep full immutable record validation, require live freshness at "
                "request write and unprotected trigger gates, and re-observe the "
                "protected runner plus exact loader after approval"
            ),
            "scope": "PRE_APPROVAL_CONTROL_PLANE_ONLY",
        },
        "schema": "trimem/development-exec-015-preapproval-cancellation/1.0",
        "scientific_status": "NOT_STARTED_ON_EXEC_015",
        "status": "IMMUTABLE_PUBLIC_GITHUB_EVIDENCE_REPLAYED",
        "workflow_run": {
            "attempt": PREVIOUS_RUN_ATTEMPT,
            "conclusion": "cancelled",
            "head_sha": PREVIOUS_EXECUTION_HEAD,
            "id": PREVIOUS_RUN_ID,
            "source_head_sha": PREVIOUS_SOURCE_HEAD,
        },
    }


def current_recovery_record() -> dict[str, Any]:
    """Return the zero-authority D1.16 request-creation state."""

    return {
        "actual_execution_authorized": False,
        "benchmark_image_pulls": 0,
        "classification": AMENDMENT_CLASSIFICATION,
        "endpoint": AMENDMENT_ENDPOINT,
        "external_execution_approval_received": False,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "request_present_in_recovery_source": False,
        "schema": "trimem/development-exec-016-recovery/1.0",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def validate_optional_exec_016_boundary(repository: Path) -> str | None:
    """Accept only the recovery source or its exact sentinel-only child."""

    repository = resolve_repository_root(repository)
    head = git(repository, "rev-parse", "HEAD").strip()
    additions = git(
        repository,
        "log",
        "--format=%H",
        "--diff-filter=A",
        head,
        "--",
        SENTINEL_PATH,
    ).splitlines()
    target = repository.joinpath(*PurePosixPath(SENTINEL_PATH).parts)
    if not additions:
        require(not target.exists(), "uncommitted `_016` request exists")
        return None
    require(len(additions) == 1, "`_016` was added more than once")
    execution_head = additions[0]
    require(execution_head == head, "commits exist after the active `_016` request")
    parents = git(repository, "rev-list", "--parents", "-n", "1", execution_head).split()
    require(len(parents) == 2, "`_016` parent differs")
    validate_sentinel_commit(
        repository,
        execution_head,
        expected_parent=parents[1],
        require_checked_out_head=True,
    )
    return execution_head


def validate_current_recovery(repository: Path) -> dict[str, Any]:
    """Validate the checked-out D1.16 source or exact ``_016`` child."""

    repository = resolve_repository_root(repository)
    execution_head = validate_optional_exec_016_boundary(repository)
    source_head = (
        git(repository, "rev-parse", "HEAD").strip()
        if execution_head is None
        else git(
            repository, "rev-list", "--parents", "-n", "1", execution_head
        ).split()[1]
    )
    result = validate_correction_source(
        repository,
        source_head,
        require_checked_out_head=execution_head is None,
    )
    return {
        **result,
        "request_015_attempt_one_consumed": True,
        "request_015_rerun_allowed": False,
        "request_016_created": execution_head is not None,
        "request_016_execution_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--source-head")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--event-path", type=Path)
    group.add_argument("--runner-host-preflight-event-path", type=Path)
    group.add_argument("--pre-setup-cache-host-event-path", type=Path)
    group.add_argument("--protected-runner-preflight-event-path", type=Path)
    group.add_argument("--start-protected-services-event-path", type=Path)
    group.add_argument("--verify-protected-services-event-path", type=Path)
    group.add_argument("--cleanup-protected-services-event-path", type=Path)
    group.add_argument("--write-request", action="store_true")
    group.add_argument("--validate-source", action="store_true")
    group.add_argument("--validate-current", action="store_true")
    args = parser.parse_args(argv)
    if args.source_head is not None and not args.validate_source:
        parser.error("--source-head requires --validate-source")
    try:
        if args.write_request:
            result = write_request(args.repository)
        elif args.runner_host_preflight_event_path is not None:
            result = validate_runner_host_preflight(
                args.repository, args.runner_host_preflight_event_path
            )
        elif args.pre_setup_cache_host_event_path is not None:
            result = validate_pre_setup_cache_host(
                args.repository, args.pre_setup_cache_host_event_path
            )
        elif args.protected_runner_preflight_event_path is not None:
            result = validate_protected_runner_preflight(
                args.repository, args.protected_runner_preflight_event_path
            )
        elif args.start_protected_services_event_path is not None:
            result = start_protected_services(
                args.repository, args.start_protected_services_event_path
            )
        elif args.verify_protected_services_event_path is not None:
            result = verify_protected_services(
                args.repository, args.verify_protected_services_event_path
            )
        elif args.cleanup_protected_services_event_path is not None:
            result = cleanup_protected_services(
                args.repository, args.cleanup_protected_services_event_path
            )
        elif args.validate_source:
            result = validate_correction_source(
                args.repository, args.source_head, require_checked_out_head=True
            )
        elif args.validate_current:
            result = validate_current_recovery(args.repository)
        else:
            result = validate_branch_trigger(args.repository, args.event_path)
    except (DevelopmentTriggerError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
