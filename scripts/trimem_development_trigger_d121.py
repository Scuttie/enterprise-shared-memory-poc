"""Fail-closed one-time DEVELOPMENT_TUNING ``_021`` recovery trigger.

D1.21 preserves the spent ``_020`` execution as immutable history.  That run
reached the first official SWE-bench result, whose fail-to-pass set was empty
and whose pass-to-pass set contained one regression.  The old adapter
incorrectly converted that legitimate unresolved scientific outcome into an
adapter-contract failure.  D1.21 changes only outcome normalization and the
governance/routing required for a fresh request.

Importing this module has no network, Docker, grader, credential, image,
model, GitHub, or filesystem-mutation side effect.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import threading
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d120 as d120


d119 = d120.d119
d118 = d120.d118
d115 = d120.d115
d114 = d120.d114
d113 = d120.d113
d112 = d120.d112

EXPECTED_REPOSITORY = d120.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d120.EXPECTED_BRANCH
EXPECTED_REF = d120.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d120.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d120.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d120.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d120.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d120.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d120.EXPECTED_BASE_HEAD

PREVIOUS_SOURCE_HEAD = "138619d5d5e83009c3c22a4d9619a9394b0b59a1"
PREVIOUS_EXECUTION_HEAD = "f15371a612d6c35acabe56e7d3196429b95ca3bb"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_020.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "c177d9664972eaa128c3d7efe6666c192c2666912fd52b258364944fa3ad2665"
)
PREVIOUS_SENTINEL_BYTES = 49_618
PREVIOUS_SENTINEL_BLOB_OID = "c37ed850c34bb8d398e7670eaf242e4e6020f14d"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "041f09b92e2f8b42224c560a95dac82fd76cbede7aa726042135d54fdab53d7c"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "3b91b43f7b299bdcca90f604e78975308543b5680b37be0a19ebb370686b5e71"
)
PREVIOUS_RUN_ID = 34_240_675_412
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_FAILURE_SUBTYPE = (
    "SWE_PASS_TO_PASS_REGRESSION_MISCLASSIFIED_AS_ADAPTER_CONTRACT_FAILURE"
)
PREVIOUS_FAILURE_CLASSIFICATION = (
    "OFFICIAL_GRADER_SCIENTIFIC_OUTCOME_CLASSIFICATION_FAILURE"
)
PREVIOUS_FAILURE_MESSAGE = (
    "official grader failed before an authoritative result: adapter_contract_failed"
)
PREVIOUS_FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d121/"
    "exec_020_swe_p2p_outcome_misclassification.json"
)
PREVIOUS_FAILURE_FIXTURE_SHA256 = (
    "fb2749067a9803416cb9359d2ff0e694fa4e9bd120fc17e8164d128ed7a3b7a0"
)
PREVIOUS_FAILURE_FIXTURE_BYTES = 7_212

STARTING_SOURCE_HEAD = PREVIOUS_EXECUTION_HEAD
STARTING_FREEZE_SHA256 = PREVIOUS_SOURCE_FREEZE_SHA256
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.21"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_021.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-021"

AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_021_recovery_amendment.json"
)
AMENDMENT_SCHEMA = (
    "trimem/development-exec-021-swe-outcome-normalization-amendment/1.0"
)
INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_021_recovery_inventory.json"
)
INVENTORY_SCHEMA = (
    "trimem/development-exec-021-swe-outcome-normalization-inventory/1.0"
)
AMENDMENT_CLASSIFICATION = (
    "POST_EXEC_020_PARTIAL_SCIENTIFIC_SWE_OUTCOME_NORMALIZATION_RECOVERY"
)
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_020_PARTIAL_SCIENTIFIC_FAILURE_"
    "READY_FOR_EXEC_021_REQUEST"
)
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_021_REQUEST"
REPORT_PATH = "reports/TRIMEM_D121_EXEC_021_RECOVERY.md"
TRIGGER_PATH = "scripts/trimem_development_trigger_d121.py"
RESEAL_PATH = "scripts/trimem_d121_reseal.py"
APPROVAL_SECRET_PATH = d120.APPROVAL_SECRET_PATH
CHECKOUT_REHEARSAL_PATH = d120.CHECKOUT_REHEARSAL_PATH
EXACT_HEAD_GATE_WORKFLOW_PATH = d120.EXACT_HEAD_GATE_WORKFLOW_PATH
LOADER_REHEARSAL_COLLECTOR_PATH = "scripts/trimem_d121_loader_rehearsal.py"
GRADER_FACTORY_REHEARSAL_PATH = d120.GRADER_FACTORY_REHEARSAL_PATH

FREEZE_PATH = d120.FREEZE_PATH
FREEZE_SCHEMA = d120.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.21"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.21"

MODEL_ID = d120.MODEL_ID
REASONING_EFFORT = d120.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d120.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d120.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d120.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d120.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d120.ACTIVATION_ZERO_COUNTERS
REMOTE_GATE_SPECS = d120.REMOTE_GATE_SPECS
REQUIRED_REMOTE_GATE_WORKFLOWS = d120.REQUIRED_REMOTE_GATE_WORKFLOWS
PRESERVED_SCIENTIFIC_PATHS = d120.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d120.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d120.EXECUTION_CONTRACT_PATHS
CHECKOUT_ACTION_SHA = d120.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d120.SETUP_PYTHON_ACTION_SHA
HEX40 = d120.HEX40

DevelopmentTriggerError = d120.DevelopmentTriggerError
require = d120.require
canonical_bytes = d120.canonical_bytes
strict_json = d120.strict_json
git = d120.git
commit_bytes = d120.commit_bytes
resolve_repository_root = d120.resolve_repository_root
_is_ancestor = d120._is_ancestor
_tree_entry = d120._tree_entry


OUTCOME_NORMALIZATION_CONTRACT: dict[str, bool | str] = {
    "adapter_and_infrastructure_failures_remain_fail_closed": True,
    "computed_resolved_predicate": (
        "len(FAIL_TO_PASS.failure)==0 and len(PASS_TO_PASS.failure)==0"
    ),
    "failure_sets_disjoint_and_complete": True,
    "matrix_recomputes_outcome_independently": True,
    "pass_to_pass_regression_count_is_reported": True,
    "pass_to_pass_regression_is_valid_scientific_unresolved": True,
    "source_domain_equality_required": True,
}

# The D1.21 diff is limited to the two normalizers and the smallest complete
# governance/routing surface.  Frozen prompts, tools, models, targets, stream
# order, budgets, image locks, and harness revisions are excluded.
ALLOWED_RECOVERY_PATHS = frozenset(
    {
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/trimem-benchmark.yml",
        AMENDMENT_PATH,
        INVENTORY_PATH,
        PREVIOUS_FAILURE_FIXTURE_PATH,
        "artifacts/trimem_v1/freeze.json",
        "artifacts/trimem_v1/readiness_requirements.json",
        REPORT_PATH,
        LOADER_REHEARSAL_COLLECTOR_PATH,
        RESEAL_PATH,
        TRIGGER_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_official_grader.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d114_post_setup_environment.py",
        "tests/unit/test_trimem_d120_trigger.py",
        "tests/unit/test_trimem_d121_trigger.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_grader_terminal_evidence.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    }
)

REQUIRED_RECOVERY_CHANGES: dict[str, str] = {
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    PREVIOUS_FAILURE_FIXTURE_PATH: "A",
    "artifacts/trimem_v1/freeze.json": "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    REPORT_PATH: "A",
    LOADER_REHEARSAL_COLLECTOR_PATH: "A",
    RESEAL_PATH: "A",
    TRIGGER_PATH: "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    "scripts/trimem_official_grader.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d114_post_setup_environment.py": "M",
    "tests/unit/test_trimem_d120_trigger.py": "M",
    "tests/unit/test_trimem_d121_trigger.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_grader_terminal_evidence.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}
ALLOWED_ACTIVATION_PATHS = ALLOWED_RECOVERY_PATHS
REQUIRED_ACTIVATION_CHANGES = REQUIRED_RECOVERY_CHANGES

IMPLEMENTATION_SEAL_PATHS = frozenset(
    {
        EXPECTED_WORKFLOW_PATH,
        LOADER_REHEARSAL_COLLECTOR_PATH,
        RESEAL_PATH,
        TRIGGER_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_official_grader.py",
        "scripts/trimem_verify_ready.py",
    }
)

ACTIVATION_BINDING_PATHS = {
    "approval_secret_producer_sha256": APPROVAL_SECRET_PATH,
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "checkout_rehearsal_sha256": CHECKOUT_REHEARSAL_PATH,
    "d121_amendment_sha256": AMENDMENT_PATH,
    "d121_inventory_sha256": INVENTORY_PATH,
    "d121_reseal_sha256": RESEAL_PATH,
    "d121_run_fixture_sha256": PREVIOUS_FAILURE_FIXTURE_PATH,
    "d121_trigger_reader_sha256": TRIGGER_PATH,
    "grader_factory_rehearsal_sha256": GRADER_FACTORY_REHEARSAL_PATH,
    "loader_rehearsal_collector_sha256": LOADER_REHEARSAL_COLLECTOR_PATH,
    "multi_swe_contract_sha256": "scripts/trimem_multi_swe_contract.py",
    "official_grader_sha256": "scripts/trimem_official_grader.py",
    "readiness_requirements_sha256": "artifacts/trimem_v1/readiness_requirements.json",
    "verify_ready_sha256": "scripts/trimem_verify_ready.py",
}


HISTORICAL_EXECUTION_ACTUALS: dict[str, int | str | None] = {
    "benchmark_image_pulls": 13,
    "cached_input_tokens": 0,
    "completed_task_arm_runs": 0,
    "decomposition_calls": 1,
    "exact_model_metadata_requests": 1,
    "extraction_calls": 0,
    "grader_attempts": 1,
    "grader_containers": 1,
    "input_tokens": 143_150,
    "model_generation_calls": 18,
    "official_grader_runs": 1,
    "output_tokens": 6_444,
    "paid_model_calls": 18,
    "protocol_canary_generation_calls": 1,
    "provider_control_plane_requests": 1,
    "reasoning_tokens": None,
    "reasoning_tokens_status": "UNAVAILABLE_NOT_INFERRED",
    "scientific_model_calls": 17,
    "solve_calls": 16,
    "task_arm_reservations": 1,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_tokens_excluding_unavailable_reasoning_breakout": 149_594,
    "total_usd": "0.136360500000",
}

SCIENTIFIC_EXECUTION_ACTUALS: dict[str, int | str | None] = {
    "cached_input_tokens": 0,
    "decomposition_calls": 1,
    "extraction_calls": 0,
    "input_tokens": 142_200,
    "model_generation_calls": 17,
    "output_tokens": 6_416,
    "paid_model_calls": 17,
    "reasoning_tokens": None,
    "reasoning_tokens_status": "UNAVAILABLE_NOT_INFERRED",
    "solve_calls": 16,
    "total_tokens_excluding_unavailable_reasoning_breakout": 148_616,
    "total_usd": "0.135522000000",
}

CANARY_EXECUTION_ACTUALS: dict[str, int | str | None] = {
    "cached_input_tokens": 0,
    "input_tokens": 950,
    "model_generation_calls": 1,
    "output_tokens": 28,
    "paid_model_calls": 1,
    "reasoning_tokens": None,
    "reasoning_tokens_status": "UNAVAILABLE_NOT_INFERRED",
    "total_tokens_excluding_unavailable_reasoning_breakout": 978,
    "total_usd": "0.000838500000",
}

ZERO_CURRENT_EXECUTION_ACTUALS: dict[str, int | float] = {
    "benchmark_image_pulls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "model_generation_calls": 0,
    "model_metadata_requests": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_usd": 0.0,
}
ZERO_SCIENTIFIC_ACTUALS = ZERO_CURRENT_EXECUTION_ACTUALS


_D120_CONTEXT_LOCK = threading.RLock()


def _context_bindings() -> dict[str, Any]:
    """Values observed by every inherited D1.20-D1.12 adapter."""

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
def _d121_runtime_context() -> Iterator[None]:
    """Bind the inherited implementation to one coherent D1.21 identity."""

    # Acquire the parent context lock before changing any D1.20 globals.  A
    # concurrent historical D1.20 validation holds this lock for its complete
    # context; mutating first would transiently expose D1.21 identities inside
    # that otherwise coherent historical validation.
    with d120._D119_CONTEXT_LOCK, _D120_CONTEXT_LOCK:
        bindings = _context_bindings()
        previous = {name: getattr(d120, name) for name in bindings}
        try:
            for name, value in bindings.items():
                setattr(d120, name, value)
            with d120._d120_runtime_context():
                yield
        finally:
            for name, value in reversed(tuple(previous.items())):
                setattr(d120, name, value)


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _020 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _020 execution parent differs",
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
        "immutable _020 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _020 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and b"\r" not in raw,
        "immutable _020 sentinel raw bytes differ",
    )
    previous = strict_json(raw)
    bindings = previous.get("bindings")
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.20"
        and previous.get("request_id") == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020"
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
        "immutable _020 request identity, bytes, or zero authority differs",
    )
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.21 source does not preserve immutable EXEC _020",
    )
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical _020 request changed after execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_021 exists in recovery-source history",
    )
    return previous


def _validate_previous_run_fixture(
    repository: Path, source_head: str
) -> dict[str, Any]:
    raw = commit_bytes(repository, source_head, PREVIOUS_FAILURE_FIXTURE_PATH)
    value = strict_json(raw)
    require(
        len(raw) == PREVIOUS_FAILURE_FIXTURE_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_FAILURE_FIXTURE_SHA256
        and not raw.startswith(b"\xef\xbb\xbf")
        and b"\x00" not in raw
        and b"\r" not in raw
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and raw
        == json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n",
        "EXEC _020 failure fixture bytes differ",
    )
    require(
        value.get("schema")
        == "trimem/development-exec-020-swe-p2p-outcome-misclassification/1.0"
        and value.get("repository") == EXPECTED_REPOSITORY
        and value.get("branch") == EXPECTED_BRANCH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("execution_head") == PREVIOUS_EXECUTION_HEAD
        and value.get("performance_measured") is False
        and value.get("pass_at_1") is None,
        "EXEC _020 failure fixture identity differs",
    )
    workflow = value.get("workflow_run")
    require(
        isinstance(workflow, Mapping)
        and workflow.get("id") == PREVIOUS_RUN_ID
        and workflow.get("run_attempt") == PREVIOUS_RUN_ATTEMPT
        and workflow.get("head_sha") == PREVIOUS_EXECUTION_HEAD
        and workflow.get("path") == EXPECTED_WORKFLOW_PATH
        and workflow.get("conclusion") == "failure",
        "EXEC _020 workflow identity differs",
    )
    require(
        value.get("actuals") == HISTORICAL_EXECUTION_ACTUALS
        and value.get("scientific_actuals") == SCIENTIFIC_EXECUTION_ACTUALS
        and value.get("canary_actuals") == CANARY_EXECUTION_ACTUALS,
        "EXEC _020 exact accounting differs",
    )
    request = value.get("request")
    require(
        request
        == {
            "id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020",
            "path": PREVIOUS_SENTINEL_PATH,
            "source_head": PREVIOUS_SOURCE_HEAD,
            "raw_bytes": PREVIOUS_SENTINEL_BYTES,
            "raw_sha256": PREVIOUS_SENTINEL_SHA256,
            "git_blob_oid": PREVIOUS_SENTINEL_BLOB_OID,
            "payload_sha256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "freeze_sha256": PREVIOUS_SOURCE_FREEZE_SHA256,
        },
        "EXEC _020 request evidence differs",
    )
    cell = value.get("scientific_cell")
    require(
        isinstance(cell, Mapping)
        and cell.get("sequence_index") == 0
        and cell.get("target_id") == "swebench_verified--django__django-16100"
        and cell.get("stream") == "M2-baseline"
        and cell.get("official_grader") is True
        and cell.get("container_started") is True
        and cell.get("harness_exit_code") == 0
        and cell.get("authoritative_report_present") is True
        and cell.get("fail_to_pass") == {"failure_count": 0, "status": "PASS"}
        and cell.get("pass_to_pass")
        == {"failure_count": 1, "status": "REGRESSION"}
        and cell.get("computed_resolved") is False
        and cell.get("scientific_outcome") == "UNRESOLVED"
        and cell.get("terminal_cell_committed") is False
        and cell.get("terminal_cells") == 0,
        "EXEC _020 authoritative scientific outcome differs",
    )
    failure = value.get("observed_failure")
    require(
        isinstance(failure, Mapping)
        and failure.get("adapter_status") == "adapter_contract_failed"
        and failure.get("driver_error") == PREVIOUS_FAILURE_MESSAGE
        and failure.get("process_disposition") == "GLOBAL_GRADER_INFRA_FAILURE"
        and failure.get("process_exit_code") == 1
        and failure.get("request_020_attempt_one_consumed") is True
        and failure.get("request_020_rerun_allowed") is False
        and failure.get("resume_eligible") is False
        and failure.get("resume_started") is False,
        "EXEC _020 observed adapter failure differs",
    )
    cause = value.get("root_cause")
    require(
        isinstance(cause, Mapping)
        and cause.get("classification") == PREVIOUS_FAILURE_CLASSIFICATION
        and cause.get("failure_subtype") == PREVIOUS_FAILURE_SUBTYPE
        and cause.get("scientific_result") == "UNRESOLVED"
        and cause.get("recovery_contract") == OUTCOME_NORMALIZATION_CONTRACT,
        "EXEC _020 root-cause replay differs",
    )
    custody = value.get("evidence_custody")
    require(
        isinstance(custody, Mapping)
        and custody.get("public_result") == "ABSENT_EXPECTED"
        and custody.get("remote_custody_status")
        == "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS"
        and custody.get("restricted_artifact", {}).get("id") == 10_062_528_991
        and custody.get("inventory_artifact", {}).get("id") == 10_062_530_700
        and custody.get("custody_artifact", {}).get("id") == 10_062_533_559
        and custody.get("restricted_inventory", {}).get("inventory_sha256")
        == "2eb8ab41af1211632134ecfe92348a44537ea346e479dd15211f8099e7e4f14a",
        "EXEC _020 evidence custody differs",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    require(
        source_head != PREVIOUS_EXECUTION_HEAD
        and _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.21 source is not a strict descendant of immutable EXEC _020",
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
        require(len(pieces) == 2, "D1.21 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.21 diff status is forbidden: {status}")
        require(path in ALLOWED_RECOVERY_PATHS, f"D1.21 changed forbidden path: {path}")
        require(path not in changes, f"D1.21 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.21 recovery change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path),
            f"frozen scientific input changed during D1.21 recovery: {path}",
        )


def _validate_workflow(repository: Path, source_head: str) -> None:
    d120._validate_exact_head_gate_workflow(repository, source_head)
    try:
        workflow = commit_bytes(repository, source_head, EXPECTED_WORKFLOW_PATH).decode(
            "utf-8", errors="strict"
        )
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError("benchmark workflow is not UTF-8") from exc
    require(
        workflow.count(f"      - {SENTINEL_PATH}\n") == 1
        and f"      - {PREVIOUS_SENTINEL_PATH}\n" not in workflow,
        "active push sentinel is not exclusively _021",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-020" not in workflow,
        "_021 concurrency identity differs",
    )
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        all(workflow.count(marker) == 1 for marker in (
            branch_marker, bounded_marker, frozen_marker
        )),
        "D1.21 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(branch_start < bounded_start < frozen_start, "D1.21 job order differs")
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    command = f"python -I -S {TRIGGER_PATH}"
    require(
        branch_job.count(command) == 1
        and bounded_job.count(command) == 1
        and frozen_job.count(command) == 4
        and "scripts/trimem_development_trigger_d120.py" not in workflow,
        "active trigger validator is not exclusively D1.21 _021",
    )
    rehearsal_command = f"python {CHECKOUT_REHEARSAL_PATH}"
    require(
        bounded_job.count(rehearsal_command) == 1
        and bounded_job.index(rehearsal_command)
        < bounded_job.index("Materialize pinned harnesses in unprotected loader preflight")
        and rehearsal_command not in branch_job
        and rehearsal_command not in frozen_job,
        "all-target credential-free checkout rehearsal boundary differs",
    )
    grader_rehearsal_command = f"python {GRADER_FACTORY_REHEARSAL_PATH}"
    require(
        bounded_job.count(grader_rehearsal_command) == 1
        and bounded_job.index(grader_rehearsal_command)
        > bounded_job.index(d115.LOADER_PREFLIGHT_COMMAND_FRAGMENT)
        and grader_rehearsal_command not in branch_job
        and frozen_job.count(grader_rehearsal_command) == 1
        and f"{grader_rehearsal_command}\n          --synthetic" in frozen_job
        and frozen_job.index(grader_rehearsal_command)
        < frozen_job.index("Materialize protected external approval")
        and frozen_job.index(grader_rehearsal_command)
        < frozen_job.index("Validate exact OpenAI credential format"),
        "precredential grader-factory rehearsal boundary differs",
    )
    exact_execution_command = (
        '"$pythonLocation/bin/python3.11" scripts/trimem_run_with_resume.py'
    )
    require(
        frozen_job.count(exact_execution_command) == 1
        and "\n          python scripts/trimem_run_with_resume.py" not in frozen_job,
        "protected execution is not bound to the exact preflight launcher",
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
        "D1.21 hosted/self-hosted/protected boundary differs",
    )
    for action, digest in (
        ("actions/checkout", CHECKOUT_ACTION_SHA),
        ("actions/setup-python", SETUP_PYTHON_ACTION_SHA),
    ):
        require(
            f"uses: {action}@{digest}" in workflow,
            f"benchmark workflow action is not pinned: {action}",
        )
    strict_decoder = (
        "base64.b64decode(os.environ['TRIMEM_EXEC_APPROVAL_B64'], validate=True)"
    )
    require(
        workflow.count("continue-on-error:") == 0
        and workflow.count("|| echo") == 0
        and workflow.count(strict_decoder) == 1
        and "lstrip(\"\\ufeff\")" not in workflow
        and ".lstrip('\\ufeff')" not in workflow
        and "errors=\"ignore\"" not in workflow
        and "errors='ignore'" not in workflow,
        "fail-closed workflow or strict approval decoder was weakened",
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
        "D1.21 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_020_attempt_one_consumed") is True
        and authority.get("request_020_rerun_allowed") is False
        and authority.get("request_021_request_creation_authorized") is True
        and authority.get("request_021_created_in_source") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_021_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.21 authority boundary differs",
    )
    require(
        amendment.get("consumed_execution_actuals") == HISTORICAL_EXECUTION_ACTUALS
        and amendment.get("scientific_execution_actuals")
        == SCIENTIFIC_EXECUTION_ACTUALS
        and amendment.get("canary_execution_actuals") == CANARY_EXECUTION_ACTUALS,
        "D1.21 amendment does not preserve exact EXEC _020 accounting",
    )
    implementation = amendment.get("implementation_sha256")
    require(
        isinstance(implementation, Mapping)
        and implementation == inventory.get("implementation_sha256")
        and set(implementation) == IMPLEMENTATION_SEAL_PATHS,
        "D1.21 implementation seal shape differs",
    )
    for path in sorted(IMPLEMENTATION_SEAL_PATHS):
        require(
            implementation.get(path)
            == hashlib.sha256(commit_bytes(repository, source_head, path)).hexdigest(),
            f"D1.21 implementation seal differs: {path}",
        )
    require(
        amendment.get("recovery_contract") == OUTCOME_NORMALIZATION_CONTRACT,
        "D1.21 SWE outcome-normalization contract differs",
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
        "scientific identity differs from immutable _020",
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
    result = deepcopy(dict(d120._request_execution_contracts(bindings)))
    result["swe_official_result_normalization"] = deepcopy(
        OUTCOME_NORMALIZATION_CONTRACT
    )
    result["contract_bindings"]["benchmark_matrix_sha256"] = bindings[
        "benchmark_matrix_sha256"
    ]
    result["contract_bindings"]["official_grader_sha256"] = bindings[
        "official_grader_sha256"
    ]
    return result


def validate_checkout_rehearsal(value: Any) -> dict[str, Any]:
    with _d121_runtime_context():
        return d120.validate_checkout_rehearsal(value)


def collect_exact_checkout_rehearsal(
    repository: Path, source_head: str
) -> dict[str, Any]:
    with _d121_runtime_context():
        return d120.collect_exact_checkout_rehearsal(repository, source_head)


def validate_loader_rehearsal_record(
    value: Any,
    *,
    source_head: str,
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    with _d121_runtime_context():
        return d120.validate_loader_rehearsal_record(
            value,
            source_head=source_head,
            runner_readiness=runner_readiness,
        )


def _build_request_impl(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
    loader_rehearsal: Mapping[str, Any],
    checkout_rehearsal: Mapping[str, Any],
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
    checkout = validate_checkout_rehearsal(checkout_rehearsal)
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
        "checkout_rehearsal": checkout,
        "checkout_rehearsal_sha256": "sha256:"
        + hashlib.sha256(canonical_bytes(checkout)).hexdigest(),
        "control_plane": deepcopy(dict(previous["control_plane"])),
        "d121_execution_contracts": _request_execution_contracts(bindings),
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
            "DEVELOPMENT_TUNING_EXEC_REQUEST_020_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_022",
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
            "canary_actuals": deepcopy(CANARY_EXECUTION_ACTUALS),
            "consumed_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_fixture_sha256": "sha256:" + PREVIOUS_FAILURE_FIXTURE_SHA256,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "official_scientific_outcome": "UNRESOLVED",
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_payload_sha256": (
                "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
            ),
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "previous_source_head": PREVIOUS_SOURCE_HEAD,
            "public_result_available": False,
            "remote_custody_status": "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS",
            "request_020_rerun_allowed": False,
            "scientific_actuals": deepcopy(SCIENTIFIC_EXECUTION_ACTUALS),
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
    checkout = validate_checkout_rehearsal(value.get("checkout_rehearsal"))
    require(
        value.get("checkout_rehearsal_sha256")
        == "sha256:" + hashlib.sha256(canonical_bytes(checkout)).hexdigest(),
        "_021 checkout rehearsal hash differs",
    )
    expected = _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
        loader_rehearsal=rehearsal,
        checkout_rehearsal=checkout,
    )
    require(value == expected, "_021 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_021 request bytes are not canonical UTF-8 plus one LF",
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
        "trigger commit is not the exclusive _021 sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "_021 sentinel is not a regular non-executable blob")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_021 already exists before the trigger commit",
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
    repository = resolve_repository_root(repository)
    selected = source_head or git(repository, "rev-parse", "HEAD").strip()
    if require_checked_out_head:
        require(git(repository, "rev-parse", "HEAD").strip() == selected, "HEAD differs")
    with _d121_runtime_context():
        return _validate_source_impl(repository, selected)


def build_request(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
    loader_rehearsal: Mapping[str, Any],
    checkout_rehearsal: Mapping[str, Any],
) -> dict[str, Any]:
    with _d121_runtime_context():
        return _build_request_impl(
            repository,
            source_head=source_head,
            remote_gate_evidence=remote_gate_evidence,
            runner_readiness=runner_readiness,
            loader_rehearsal=loader_rehearsal,
            checkout_rehearsal=checkout_rehearsal,
        )


def validate_request(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    with _d121_runtime_context():
        return _validate_request_impl(repository, raw, source_head=source_head)


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    with _d121_runtime_context():
        return _validate_sentinel_commit_impl(
            repository,
            after,
            expected_parent=expected_parent,
            require_checked_out_head=require_checked_out_head,
        )


def _delegate(name: str, *args: Any, **kwargs: Any) -> Any:
    with _d121_runtime_context():
        return getattr(d120, name)(*args, **kwargs)


def validate_branch_trigger(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_branch_trigger", repository, event_path, **kwargs)


def write_request(repository: Path) -> dict[str, Any]:
    """Create ``_021`` only after fresh gates and exact rehearsals."""

    return _delegate("write_request", repository)


def validate_runner_host_preflight(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_runner_host_preflight", repository, event_path, **kwargs)


def validate_pre_setup_cache_host(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_pre_setup_cache_host", repository, event_path, **kwargs)


def validate_protected_runner_preflight(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate(
        "validate_protected_runner_preflight", repository, event_path, **kwargs
    )


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


def current_failure_record() -> dict[str, Any]:
    return {
        "classification": AMENDMENT_CLASSIFICATION,
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "failure_boundary": {
            "approval_materialization": "PASS",
            "bounded_context_preflight": "PASS",
            "branch_trigger_preflight": "PASS",
            "completed_task_arm_runs": 0,
            "exec_gate": "PASS",
            "image_materialization": "PASS",
            "model_metadata": "PASS",
            "official_grader_container_started": True,
            "official_grader_harness_exit_code": 0,
            "protocol_canary": "PASS",
            "protected_grader_factory_rehearsal": "PASS",
            "scientific_model_calls": 17,
            "task_arm_reservations": 1,
            "terminal_cells": 0,
        },
        "failure_subtype": PREVIOUS_FAILURE_SUBTYPE,
        "observed_execution_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "official_scientific_outcome": {
            "fail_to_pass_failures": 0,
            "pass_to_pass_regressions": 1,
            "resolved": False,
            "status": "UNRESOLVED",
        },
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_020_rerun_allowed": False,
            "request_021_execution_authorized": False,
        },
        "request": {
            "id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_020",
            "path": PREVIOUS_SENTINEL_PATH,
            "payload_sha256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": PREVIOUS_SENTINEL_SHA256,
            "source_head": PREVIOUS_SOURCE_HEAD,
        },
        "root_cause": {
            "classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failed_target": "swebench_verified--django__django-16100",
            "recovery_rule": (
                "accept a complete zero-exit SWE report with PASS_TO_PASS "
                "regressions as an authoritative unresolved scientific outcome; "
                "resolve only when both failure sets are empty"
            ),
            "scope": "FIRST_CELL_POST_GRADER_RESULT_NORMALIZATION",
        },
        "schema": (
            "trimem/development-exec-020-swe-p2p-outcome-"
            "misclassification/1.0"
        ),
        "scientific_status": "ONE_UNRESOLVED_OUTCOME_NO_TERMINAL_CAMPAIGN_CELL",
        "status": "IMMUTABLE_PUBLIC_AND_RESTRICTED_RUN_EVIDENCE_VERIFIED",
        "workflow_run": {
            "attempt": PREVIOUS_RUN_ATTEMPT,
            "conclusion": "failure",
            "head_sha": PREVIOUS_EXECUTION_HEAD,
            "id": PREVIOUS_RUN_ID,
            "source_head_sha": PREVIOUS_SOURCE_HEAD,
        },
    }


def current_recovery_record() -> dict[str, Any]:
    return {
        "actual_execution_authorized": False,
        "classification": AMENDMENT_CLASSIFICATION,
        "consumed_exec_020_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "current_execution_actuals": dict(ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": AMENDMENT_ENDPOINT,
        "external_execution_approval_received": False,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "request_present_in_recovery_source": False,
        "schema": "trimem/development-exec-021-recovery/1.0",
    }


def validate_optional_exec_021_boundary(repository: Path) -> str | None:
    """Accept only the D1.21 recovery source or exact sentinel-only child."""

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
        require(not target.exists(), "uncommitted `_021` request exists")
        return None
    require(len(additions) == 1, "`_021` was added more than once")
    execution_head = additions[0]
    require(execution_head == head, "commits exist after the active `_021` request")
    parents = git(repository, "rev-list", "--parents", "-n", "1", execution_head).split()
    require(len(parents) == 2, "`_021` parent differs")
    validate_sentinel_commit(
        repository,
        execution_head,
        expected_parent=parents[1],
        require_checked_out_head=True,
    )
    return execution_head


def validate_current_recovery(repository: Path) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    execution_head = validate_optional_exec_021_boundary(repository)
    source_head = (
        git(repository, "rev-parse", "HEAD").strip()
        if execution_head is None
        else git(repository, "rev-list", "--parents", "-n", "1", execution_head).split()[1]
    )
    result = validate_correction_source(
        repository,
        source_head,
        require_checked_out_head=execution_head is None,
    )
    return {
        **result,
        "request_020_attempt_one_consumed": True,
        "request_020_rerun_allowed": False,
        "request_021_created": execution_head is not None,
        "request_021_execution_authorized": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or create the fail-closed D1.21 DEV recovery request"
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
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
        parser.error("--source-head is valid only with --validate-source")

    if args.write_request:
        result = write_request(args.repository)
    elif args.validate_source:
        result = validate_correction_source(
            args.repository,
            args.source_head,
            require_checked_out_head=True,
        )
    elif args.validate_current:
        result = validate_current_recovery(args.repository)
    else:
        event_path = (
            args.event_path
            or args.runner_host_preflight_event_path
            or args.pre_setup_cache_host_event_path
            or args.protected_runner_preflight_event_path
            or args.start_protected_services_event_path
            or args.verify_protected_services_event_path
            or args.cleanup_protected_services_event_path
        )
        assert event_path is not None
        if args.runner_host_preflight_event_path is not None:
            result = validate_runner_host_preflight(args.repository, event_path)
        elif args.pre_setup_cache_host_event_path is not None:
            result = validate_pre_setup_cache_host(args.repository, event_path)
        elif args.protected_runner_preflight_event_path is not None:
            result = validate_protected_runner_preflight(args.repository, event_path)
        elif args.start_protected_services_event_path is not None:
            result = start_protected_services(args.repository, event_path)
        elif args.verify_protected_services_event_path is not None:
            result = verify_protected_services(args.repository, event_path)
        elif args.cleanup_protected_services_event_path is not None:
            result = cleanup_protected_services(args.repository, event_path)
        else:
            result = validate_branch_trigger(args.repository, event_path)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
