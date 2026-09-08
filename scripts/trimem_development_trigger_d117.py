"""Fail-closed one-time DEVELOPMENT_TUNING ``_017`` recovery trigger.

D1.17 preserves the consumed ``_016`` request, run, paid protocol canary, image
materialization, and encrypted failure evidence as immutable history.  The
correction constructs every newly cloned task worktree from pinned Git blob
bytes, rehearses all twelve frozen DEV checkouts before provider access, and
never repairs an existing/resumed checkout.  Importing this module has no
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
import re
import subprocess
import sys
import tempfile
import threading
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d116 as d116


d115 = d116.d115
d114 = d116.d114
d113 = d116.d113
d112 = d116.d112

EXPECTED_REPOSITORY = d116.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d116.EXPECTED_BRANCH
EXPECTED_REF = d116.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d116.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d116.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d116.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d116.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d116.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d116.EXPECTED_BASE_HEAD

PREVIOUS_SOURCE_HEAD = "c39b3dbfcf16ecc938ba7c958b044306f1874ff0"
PREVIOUS_EXECUTION_HEAD = "0b31ee30abadae4242ce24d5a5821f01c727c6cc"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_016.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "4f423e31e130240d1747647bd05909f244f2d840699e9ff25b6de6711f2f6533"
)
PREVIOUS_SENTINEL_BYTES = 38_966
PREVIOUS_SENTINEL_BLOB_OID = "fe22be0e882667e1d61cd99ee07f969a3e61473f"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "d04c884033be9fe1f39ae6d1cd6523434419f4c1a46ffdefb38545d514217edf"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "43e411d5016ef1c891fcc64e02f90221d24627b14ff2b303c68fb053d55e71bd"
)
PREVIOUS_RUN_ID = 34_185_194_819
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_FAILURE_SUBTYPE = "ORDINARY_CHECKOUT_APPLIED_COMMITTED_CRLF_TRANSFORM"
PREVIOUS_FAILURE_CLASSIFICATION = "GIT_BLOB_WORKTREE_EOL_PORTABILITY_FAILURE"
PREVIOUS_FAILURE_MESSAGE = (
    "new checkout is not exact and clean: "
    "multi_swe_bench_mini--ponylang__ponyc-1981"
)
PREVIOUS_FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d117/exec_016_checkout_portability_failure.json"
)
PREVIOUS_FAILURE_FIXTURE_SHA256 = (
    "f63f5853937c10cc954cf6e4439e279dd5bfa8776e7047c968f8efd530350283"
)
PREVIOUS_FAILURE_FIXTURE_BYTES = 5_947

STARTING_SOURCE_HEAD = PREVIOUS_EXECUTION_HEAD
STARTING_FREEZE_SHA256 = PREVIOUS_SOURCE_FREEZE_SHA256
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_017"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.17"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_017.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_017_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-017"

AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_017_recovery_amendment.json"
)
AMENDMENT_SCHEMA = "trimem/development-exec-017-checkout-portability-amendment/1.0"
INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_017_recovery_inventory.json"
)
INVENTORY_SCHEMA = "trimem/development-exec-017-checkout-portability-inventory/1.0"
AMENDMENT_CLASSIFICATION = (
    "POST_EXEC_016_PRE_TASK_GIT_BLOB_WORKTREE_PORTABILITY_RECOVERY"
)
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_016_PRE_TASK_CHECKOUT_FAILURE_"
    "READY_FOR_EXEC_017_REQUEST"
)
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_017_REQUEST"
REPORT_PATH = "reports/TRIMEM_D117_EXEC_017_RECOVERY.md"
TRIGGER_PATH = "scripts/trimem_development_trigger_d117.py"
CHECKOUT_REHEARSAL_PATH = "scripts/trimem_d117_checkout_rehearsal.py"
EXACT_HEAD_GATE_WORKFLOW_PATH = ".github/workflows/ci-trimem-dev-toolchain.yml"
LOADER_REHEARSAL_COLLECTOR_PATH = d116.LOADER_REHEARSAL_COLLECTOR_PATH

FREEZE_PATH = d116.FREEZE_PATH
FREEZE_SCHEMA = d116.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.17"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.17"

MODEL_ID = d116.MODEL_ID
REASONING_EFFORT = d116.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d116.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d116.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d116.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d116.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d116.ACTIVATION_ZERO_COUNTERS
REMOTE_GATE_SPECS = d116.REMOTE_GATE_SPECS
REQUIRED_REMOTE_GATE_WORKFLOWS = d116.REQUIRED_REMOTE_GATE_WORKFLOWS
PRESERVED_SCIENTIFIC_PATHS = d116.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d116.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d116.EXECUTION_CONTRACT_PATHS
CHECKOUT_ACTION_SHA = d116.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d116.SETUP_PYTHON_ACTION_SHA
HEX40 = d116.HEX40

DevelopmentTriggerError = d116.DevelopmentTriggerError
require = d116.require
canonical_bytes = d116.canonical_bytes
strict_json = d116.strict_json
git = d116.git
commit_bytes = d116.commit_bytes
resolve_repository_root = d116.resolve_repository_root
_is_ancestor = d116._is_ancestor


# Only construction/runtime custody, readiness, and their direct tests may
# differ from the consumed _016 execution.  Frozen tasks, arms, prompts,
# images, graders, model, pricing, selection, and stream order are excluded.
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
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        CHECKOUT_REHEARSAL_PATH,
        "scripts/trimem_freeze.py",
        "scripts/trimem_multi_swe_contract.py",
        TRIGGER_PATH,
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_atomic_resume.py",
        "tests/unit/test_trimem_d110_checkout_custody.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d114_post_setup_environment.py",
        "tests/unit/test_trimem_d115_status_and_reseal.py",
        "tests/unit/test_trimem_d117_trigger.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    }
)
REQUIRED_RECOVERY_CHANGES = {
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
    CHECKOUT_REHEARSAL_PATH: "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    TRIGGER_PATH: "A",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_d110_atomic_resume.py": "M",
    "tests/unit/test_trimem_d110_checkout_custody.py": "M",
    "tests/unit/test_trimem_d117_trigger.py": "A",
}
ALLOWED_ACTIVATION_PATHS = ALLOWED_RECOVERY_PATHS
REQUIRED_ACTIVATION_CHANGES = REQUIRED_RECOVERY_CHANGES

ACTIVATION_BINDING_PATHS = {
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "checkout_rehearsal_sha256": CHECKOUT_REHEARSAL_PATH,
    "d117_amendment_sha256": AMENDMENT_PATH,
    "d117_inventory_sha256": INVENTORY_PATH,
    "d117_run_fixture_sha256": PREVIOUS_FAILURE_FIXTURE_PATH,
    "d117_trigger_reader_sha256": TRIGGER_PATH,
    "multi_swe_contract_sha256": "scripts/trimem_multi_swe_contract.py",
    "readiness_requirements_sha256": "artifacts/trimem_v1/readiness_requirements.json",
    "verify_ready_sha256": "scripts/trimem_verify_ready.py",
}

CHECKOUT_REHEARSAL_SCHEMA = "trimem/development-task-checkout-rehearsal/1.0"
EMPTY_PATH_SET_SHA256 = (
    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)
EXPECTED_CHECKOUT_MATERIALIZATION: tuple[
    tuple[str, str, int, int, str], ...
] = (
    (
        "swebench_verified--django__django-16100",
        "c6350d594c359151ee17b0c4f354bb44f28ff69e",
        6645,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "swebench_verified--sympy__sympy-23262",
        "fdc707f73a65a429935c01532cd3970d3355eab6",
        1968,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "swebench_verified--sphinx-doc__sphinx-11445",
        "71db08c05197545944949d5aa76cd340e7143627",
        1635,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "swebench_verified--matplotlib__matplotlib-25311",
        "430fb1db88843300fb4baae3edc499bbfe073b0c",
        4393,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "multi_swe_bench_mini--mui__material-ui-29880",
        "0d94283959a3aa016881b9644767b937c34d2807",
        37002,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "multi_swe_bench_mini--ponylang__ponyc-1981",
        "560c412e0eb23a0b922a9ba3bea064c14f18d84a",
        697,
        1,
        "1c0fc6c9cbbb976f487528140255670f1c97f7c9a2d5fc99c4cdc1ba38470f76",
    ),
    (
        "multi_swe_bench_mini--clap-rs__clap-3960",
        "5e02445ce5f6eb89933d5985736c69059d0dc7af",
        625,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "multi_swe_bench_mini--facebook__zstd-938",
        "b3d76e0a94502e2f484d7495c88ca3a21d44155b",
        389,
        30,
        "9e990b89344de1db4fd5fc3965743652760e8fd10cc1771ea4ecfb8c431845bf",
    ),
    (
        "multi_swe_bench_flash--sharkdp__bat-1276",
        "33128d75f22a7c029df17b1ee595865933551469",
        309,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "multi_swe_bench_flash--catchorg__Catch2-1616",
        "00347f1e79260e76d5072cca5b3636868397dda5",
        346,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "multi_swe_bench_flash--clap-rs__clap-3394",
        "d4cfceedabb908068473650410924ff2a522d5d1",
        381,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
    (
        "multi_swe_bench_flash--cli__cli-869",
        "658d548c5e690b4fb4dd6ac06d4b798238b6157f",
        154,
        0,
        EMPTY_PATH_SET_SHA256,
    ),
)


_D116_CONTEXT_LOCK = threading.RLock()


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
def _d117_runtime_context() -> Iterator[None]:
    """Bind the inherited D1.16/D1.15 engine to one coherent D1.17 view."""

    with (
        _D116_CONTEXT_LOCK,
        d116._D115_CONTEXT_LOCK,
        d115._D114_CONTEXT_LOCK,
        d114._D113_CONTEXT_LOCK,
        d113._D112_CONTEXT_LOCK,
    ):
        bindings = _context_bindings()
        previous = {name: getattr(d116, name) for name in bindings}
        try:
            for name, value in bindings.items():
                setattr(d116, name, value)
            yield
        finally:
            for name, value in reversed(tuple(previous.items())):
                setattr(d116, name, value)


def _tree_entry(repository: Path, commit: str, path: str) -> tuple[str, str]:
    raw = git(repository, "ls-tree", "--full-tree", commit, "--", path).strip()
    left, separator, observed_path = raw.partition("\t")
    fields = left.split()
    require(
        separator == "\t"
        and observed_path == path
        and len(fields) == 3
        and fields[1] == "blob",
        f"Git blob differs: {path}",
    )
    return fields[0], fields[2]


validate_loader_rehearsal_record = d116.validate_loader_rehearsal_record


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _016 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _016 execution parent differs",
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
        "immutable _016 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _016 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and b"\r" not in raw,
        "immutable _016 sentinel raw bytes differ",
    )
    previous = strict_json(raw)
    bindings = previous.get("bindings")
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.16"
        and previous.get("request_id") == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_016"
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
        "immutable _016 request identity, bytes, or zero authority differs",
    )
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.17 source does not preserve immutable EXEC _016",
    )
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical _016 request changed after execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_017 exists in recovery-source history",
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
        "EXEC _016 failure fixture bytes differ",
    )
    workflow = value.get("workflow_run")
    actuals = value.get("actuals")
    approval = value.get("approval_boundary")
    failure = value.get("failure")
    cause = value.get("root_cause")
    custody = value.get("evidence_custody")
    require(
        value.get("schema")
        == "trimem/d117-exec-016-checkout-portability-failure/1.0"
        and value.get("repository") == EXPECTED_REPOSITORY
        and value.get("branch") == EXPECTED_BRANCH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("execution_head") == PREVIOUS_EXECUTION_HEAD
        and value.get("performance_measured") is False
        and value.get("pass_at_1") is None,
        "EXEC _016 failure fixture identity differs",
    )
    require(
        workflow
        == {
            "conclusion": "failure",
            "created_at": "2026-09-08T03:55:46Z",
            "event": "push",
            "head_sha": PREVIOUS_EXECUTION_HEAD,
            "html_url": (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                "actions/runs/34185194819"
            ),
            "id": PREVIOUS_RUN_ID,
            "path": EXPECTED_WORKFLOW_PATH,
            "run_attempt": PREVIOUS_RUN_ATTEMPT,
            "status": "completed",
            "updated_at": "2026-09-08T04:09:20Z",
        },
        "EXEC _016 workflow identity differs",
    )
    require(
        actuals == HISTORICAL_EXECUTION_ACTUALS,
        "EXEC _016 accounting differs",
    )
    require(
        approval
        == {
            "approval_artifact_sha256": (
                "0f7be5d6b7fbb16551b7d3c212206f4ca3e05648745c7ccbeaca365096e869ff"
            ),
            "approval_materialization": "PASS",
            "approved_request_sha256": PREVIOUS_SENTINEL_SHA256,
            "approved_workflow_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "approved_workflow_run_id": PREVIOUS_RUN_ID,
            "environment_secret_count_after_cleanup": 0,
            "exec_gate": "PASS",
            "protected_environment_entered": True,
        },
        "EXEC _016 approval or cleanup boundary differs",
    )
    require(
        isinstance(failure, Mapping)
        and failure.get("message") == PREVIOUS_FAILURE_MESSAGE
        and failure.get("failed_target_id")
        == "multi_swe_bench_mini--ponylang__ponyc-1981"
        and failure.get("failed_target_repository") == "ponylang/ponyc"
        and failure.get("failed_target_commit")
        == "560c412e0eb23a0b922a9ba3bea064c14f18d84a"
        and failure.get("process_exit_code") == 1
        and failure.get("resume_eligible") is False
        and failure.get("resume_started") is False,
        "EXEC _016 process failure boundary differs",
    )
    require(
        isinstance(cause, Mapping)
        and cause.get("classification") == PREVIOUS_FAILURE_CLASSIFICATION
        and cause.get("failure_subtype") == PREVIOUS_FAILURE_SUBTYPE
        and cause.get("expected_source_identity")
        == "PINNED_GIT_BLOB_BYTES_AT_REVISION"
        and cause.get("validator_disposition")
        == "CORRECT_FAIL_CLOSED_REJECTION_OF_NON_BLOB_BYTES"
        and cause.get("scientific_result") is False
        and cause.get("reproduction")
        == {
            "facebook_zstd_transformed_bytes_inserted": 6401,
            "facebook_zstd_transformed_paths": 30,
            "other_targets_with_zero_transformed_paths": 10,
            "ponylang_ponyc_transformed_paths": 1,
            "targets_checked": 12,
        },
        "EXEC _016 checkout root-cause replay differs",
    )
    require(
        isinstance(custody, Mapping)
        and custody.get("remote_custody_status")
        == "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS"
        and custody.get("public_result") == "ABSENT_EXPECTED"
        and custody.get("recomputed_inventory")
        == {
            "inventory_sha256": (
                "71c6bf1d778850c94ca808b457165da9307cac19aae00187933cf331ab6b955f"
            ),
            "matches_uploaded_inventory": True,
            "total_bytes": 104729,
            "total_files": 96,
        },
        "EXEC _016 evidence custody differs",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    require(
        source_head != PREVIOUS_EXECUTION_HEAD
        and _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.17 source is not a strict descendant of immutable EXEC _016",
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
        require(len(pieces) == 2, "D1.17 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.17 diff status is forbidden: {status}")
        require(path in ALLOWED_RECOVERY_PATHS, f"D1.17 changed forbidden path: {path}")
        require(path not in changes, f"D1.17 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.17 recovery change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path),
            f"frozen scientific input changed during D1.17 recovery: {path}",
        )


def _validate_exact_head_gate_workflow(
    repository: Path, source_head: str
) -> None:
    """Require one branch-only DEV-toolchain run for every exact source HEAD."""

    try:
        workflow = commit_bytes(
            repository, source_head, EXACT_HEAD_GATE_WORKFLOW_PATH
        ).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError(
            "exact-head DEV toolchain workflow is not UTF-8"
        ) from exc
    start_marker = "on:\n"
    end_marker = "\npermissions:\n"
    require(
        workflow.count(start_marker) == 1 and workflow.count(end_marker) == 1,
        "exact-head DEV toolchain trigger boundary differs",
    )
    trigger = workflow[
        workflow.index(start_marker) : workflow.index(end_marker)
    ].rstrip("\n") + "\n"
    expected = (
        "on:\n"
        "  push:\n"
        "    branches:\n"
        f"      - {EXPECTED_BRANCH}\n"
    )
    require(
        trigger == expected
        and "paths:" not in trigger
        and "paths-ignore:" not in trigger,
        "exact-head DEV toolchain push gate is filtered or misbound",
    )


def _validate_workflow(repository: Path, source_head: str) -> None:
    _validate_exact_head_gate_workflow(repository, source_head)
    try:
        workflow = commit_bytes(repository, source_head, EXPECTED_WORKFLOW_PATH).decode(
            "utf-8", errors="strict"
        )
    except UnicodeDecodeError as exc:
        raise DevelopmentTriggerError("benchmark workflow is not UTF-8") from exc
    require(
        workflow.count(f"      - {SENTINEL_PATH}\n") == 1
        and f"      - {PREVIOUS_SENTINEL_PATH}\n" not in workflow,
        "active push sentinel is not exclusively _017",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-016" not in workflow,
        "_017 concurrency identity differs",
    )
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        all(workflow.count(marker) == 1 for marker in (branch_marker, bounded_marker, frozen_marker)),
        "D1.17 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(branch_start < bounded_start < frozen_start, "D1.17 job order differs")
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    command = "python -I -S scripts/trimem_development_trigger_d117.py"
    require(
        branch_job.count(command) == 1
        and bounded_job.count(command) == 1
        and frozen_job.count(command) == 4
        and "scripts/trimem_development_trigger_d116.py" not in workflow,
        "active trigger validator is not exclusively D1.17 _017",
    )
    rehearsal_command = "python scripts/trimem_d117_checkout_rehearsal.py"
    require(
        bounded_job.count(rehearsal_command) == 1
        and bounded_job.index(rehearsal_command)
        < bounded_job.index("Materialize pinned harnesses in unprotected loader preflight")
        and rehearsal_command not in branch_job
        and rehearsal_command not in frozen_job,
        "all-target credential-free checkout rehearsal boundary differs",
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
        "D1.17 hosted/self-hosted/protected boundary differs",
    )
    for action, digest in (
        ("actions/checkout", CHECKOUT_ACTION_SHA),
        ("actions/setup-python", SETUP_PYTHON_ACTION_SHA),
    ):
        require(
            f"{action}@v" not in workflow and f"{action}@{digest}" in workflow,
            f"D1.17 workflow action is mutable: {action}",
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
        "D1.17 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_016_attempt_one_consumed") is True
        and authority.get("request_016_rerun_allowed") is False
        and authority.get("request_017_request_creation_authorized") is True
        and authority.get("request_017_created_in_source") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_017_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.17 authority boundary differs",
    )
    accounting = amendment.get("consumed_execution_actuals")
    require(
        accounting == HISTORICAL_EXECUTION_ACTUALS,
        "D1.17 amendment does not preserve exact EXEC _016 accounting",
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
        "scientific identity differs from immutable _016",
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
    result = deepcopy(dict(d116._request_execution_contracts(bindings)))
    result["git_blob_checkout_portability"] = {
        "all_frozen_dev_targets_rehearsed_before_provider_access": True,
        "committed_eol_crlf_transform_is_narrowly_reversible": True,
        "existing_or_resumed_checkout_repair_allowed": False,
        "fresh_checkout_source_identity": "PINNED_GIT_BLOB_BYTES_AT_REVISION",
        "strict_raw_blob_validator_weakened": False,
        "target_count": 12,
        "transformed_path_count": 31,
    }
    result["contract_bindings"]["checkout_rehearsal_sha256"] = bindings[
        "checkout_rehearsal_sha256"
    ]
    return result


def validate_checkout_rehearsal(value: Any) -> dict[str, Any]:
    """Validate the complete, credential-free, twelve-target rehearsal."""

    require(isinstance(value, Mapping), "checkout rehearsal evidence is missing")
    expected_top_keys = {
        "schema",
        "status",
        "split",
        "credential_access",
        "model_calls",
        "image_pulls",
        "grader_containers",
        "official_grader_runs",
        "task_arm_runs",
        "source_identity",
        "transform_rule",
        "target_count",
        "regular_blob_count",
        "normalized_path_count",
        "targets",
    }
    require(
        set(value) == expected_top_keys
        and value.get("schema") == CHECKOUT_REHEARSAL_SCHEMA
        and value.get("status") == "PASS"
        and value.get("split") == "DEVELOPMENT_TUNING"
        and value.get("credential_access") is False
        and value.get("model_calls") == 0
        and value.get("image_pulls") == 0
        and value.get("grader_containers") == 0
        and value.get("official_grader_runs") == 0
        and value.get("task_arm_runs") == 0
        and value.get("source_identity") == "PINNED_GIT_BLOB_BYTES_AT_REVISION"
        and value.get("transform_rule") == "COMMITTED_TEXT_SET_EOL_CRLF_ONLY"
        and value.get("target_count") == 12
        and value.get("regular_blob_count") == 54_544
        and value.get("normalized_path_count") == 31,
        "checkout rehearsal summary differs",
    )
    rows = value.get("targets")
    require(isinstance(rows, list) and len(rows) == 12, "checkout rehearsal rows differ")
    repositories = {
        "swebench_verified--django__django-16100": "django/django",
        "swebench_verified--sympy__sympy-23262": "sympy/sympy",
        "swebench_verified--sphinx-doc__sphinx-11445": "sphinx-doc/sphinx",
        "swebench_verified--matplotlib__matplotlib-25311": "matplotlib/matplotlib",
        "multi_swe_bench_mini--mui__material-ui-29880": "mui/material-ui",
        "multi_swe_bench_mini--ponylang__ponyc-1981": "ponylang/ponyc",
        "multi_swe_bench_mini--clap-rs__clap-3960": "clap-rs/clap",
        "multi_swe_bench_mini--facebook__zstd-938": "facebook/zstd",
        "multi_swe_bench_flash--sharkdp__bat-1276": "sharkdp/bat",
        "multi_swe_bench_flash--catchorg__Catch2-1616": "catchorg/Catch2",
        "multi_swe_bench_flash--clap-rs__clap-3394": "clap-rs/clap",
        "multi_swe_bench_flash--cli__cli-869": "cli/cli",
    }
    row_keys = {
        "order_index",
        "target_id",
        "repository",
        "commit",
        "tree_object_id",
        "regular_blob_count",
        "normalized_paths",
        "normalized_path_count",
        "normalized_paths_sha256",
        "strict_raw_blob_validation",
    }
    for index, (row, expected) in enumerate(
        zip(rows, EXPECTED_CHECKOUT_MATERIALIZATION)
    ):
        target_id, commit, regular_count, normalized_count, path_hash = expected
        require(isinstance(row, Mapping) and set(row) == row_keys, "checkout rehearsal row shape differs")
        paths = row.get("normalized_paths")
        require(
            row.get("order_index") == index
            and row.get("target_id") == target_id
            and row.get("repository") == repositories[target_id]
            and row.get("commit") == commit
            and isinstance(row.get("tree_object_id"), str)
            and HEX40.fullmatch(str(row["tree_object_id"])) is not None
            and row.get("regular_blob_count") == regular_count
            and isinstance(paths, list)
            and paths == sorted(set(paths))
            and len(paths) == normalized_count
            and row.get("normalized_path_count") == normalized_count
            and row.get("normalized_paths_sha256") == path_hash
            and hashlib.sha256(canonical_bytes(paths)).hexdigest() == path_hash
            and row.get("strict_raw_blob_validation") == "PASS",
            f"checkout rehearsal row differs: {target_id}",
        )
        if target_id == "multi_swe_bench_mini--ponylang__ponyc-1981":
            require(paths == ["make.bat"], "Ponylang normalized path differs")
        elif target_id != "multi_swe_bench_mini--facebook__zstd-938":
            require(paths == [], f"unexpected normalized path: {target_id}")
    return deepcopy(dict(value))


def collect_exact_checkout_rehearsal(
    repository: Path, source_head: str
) -> dict[str, Any]:
    """Run the frozen all-target rehearsal in the exact WSL runner surface."""

    repository = resolve_repository_root(repository)
    require(
        git(repository, "rev-parse", "HEAD").strip() == source_head,
        "checkout rehearsal source HEAD differs",
    )
    wsl = d115._system_wsl_path()
    system_root = str(Path(wsl).parent.parent)
    safe_environment = d115._wsl_collector_host_environment(
        os.environ, system_root=system_root
    )
    prefix = [
        wsl,
        "-d",
        d115.RUNNER_DISTRIBUTION,
        "--user",
        d115.RUNNER_WSL_USER,
        "--exec",
    ]

    def run(argv: Sequence[str], *, label: str, timeout: float) -> bytes:
        return d115._run_wsl_collector_command(
            [*prefix, *argv],
            environment=safe_environment,
            label=label,
            timeout=timeout,
        )

    # A repository mounted from Windows is deliberately rejected by Linux
    # Git's ownership guard.  Do not weaken that guard or add a persistent
    # ``safe.directory`` exception.  Export the exact committed object graph
    # as a host-created Git bundle, then clone it into a WSL-owned directory.
    # The rehearsal therefore reads only the pinned commit and has a normal,
    # clean Linux index/worktree rather than copying platform-shaped bytes.
    with tempfile.TemporaryDirectory(prefix="trimem-d117-source-bundle-") as host_temp:
        bundle = Path(host_temp) / "source.bundle"
        host_environment = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "WINDIR": os.environ.get("WINDIR", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "LANG": "C",
        }
        bundled = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                f"core.hooksPath={os.devnull}",
                "bundle",
                "create",
                str(bundle),
                "HEAD",
            ],
            cwd=repository,
            capture_output=True,
            check=False,
            env=host_environment,
        )
        require(
            bundled.returncode == 0
            and bundled.stdout == b""
            and bundled.stderr == b""
            and bundle.is_file()
            and bundle.stat().st_size > 0,
            "exact source bundle creation failed",
        )
        bundle_wsl = run(
            ["/usr/bin/wslpath", "-a", "-u", str(bundle)],
            label="D1.17 source bundle path translation",
            timeout=30,
        ).decode("utf-8", errors="strict").strip()
        require(
            bundle_wsl.startswith("/") and "\x00" not in bundle_wsl,
            "D1.17 WSL source bundle path differs",
        )
        temporary = run(
            [
                "/usr/bin/mktemp",
                "-d",
                "-p",
                "/tmp",
                "trimem-d117-writer-XXXXXXXXXX",
            ],
            label="D1.17 checkout rehearsal temporary root",
            timeout=30,
        ).decode("ascii", errors="strict").strip()
        require(
            re.fullmatch(r"/tmp/trimem-d117-writer-[A-Za-z0-9]+", temporary)
            is not None,
            "D1.17 checkout rehearsal temporary root differs",
        )
        source = f"{temporary}/source"
        output = f"{temporary}/checkout-rehearsal.json"
        isolated = [
            "/usr/bin/env",
            "-i",
            f"HOME={d115.WSL_COLLECTOR_HOME}",
            "LANG=C.UTF-8",
            "LC_ALL=C.UTF-8",
            f"PATH={d115.WSL_COLLECTOR_PATH}",
        ]
        try:
            run(
                [
                    *isolated,
                    "/usr/bin/git",
                    "clone",
                    "--quiet",
                    "--no-checkout",
                    "--",
                    bundle_wsl,
                    source,
                ],
                label="D1.17 exact source bundle clone",
                timeout=300,
            )
            run(
                [
                    *isolated,
                    "/usr/bin/git",
                    "-C",
                    source,
                    "checkout",
                    "--quiet",
                    "--detach",
                    source_head,
                ],
                label="D1.17 exact source checkout",
                timeout=300,
            )
            observed_head = run(
                [*isolated, "/usr/bin/git", "-C", source, "rev-parse", "HEAD"],
                label="D1.17 exact source HEAD verification",
                timeout=30,
            ).decode("ascii", errors="strict").strip()
            observed_status = run(
                [
                    *isolated,
                    "/usr/bin/git",
                    "-C",
                    source,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ],
                label="D1.17 exact source cleanliness verification",
                timeout=30,
            )
            require(
                observed_head == source_head and observed_status == b"",
                "D1.17 WSL source checkout is not exact and clean",
            )
            stdout = run(
                [
                    "/usr/bin/env",
                    "-i",
                    "-C",
                    source,
                    f"HOME={d115.WSL_COLLECTOR_HOME}",
                    "LANG=C.UTF-8",
                    "LC_ALL=C.UTF-8",
                    f"PATH={d115.WSL_COLLECTOR_PATH}",
                    f"LD_LIBRARY_PATH={d115.EXACT_PYTHON_LIBRARY_PATH}",
                    f"{d115.EXACT_PYTHON_ROOT}/bin/python3.11",
                    "-I",
                    CHECKOUT_REHEARSAL_PATH,
                    "--checkout-root",
                    f"{temporary}/checkouts",
                    "--cache-root",
                    f"{temporary}/datasets",
                    "--output",
                    output,
                ],
                label="exact twelve-target checkout rehearsal",
                timeout=3600,
            )
            require(
                stdout == b"TRIMEM_DEVELOPMENT_TASK_CHECKOUT_REHEARSAL_PASS\n",
                "checkout rehearsal marker differs",
            )
            raw = run(
                ["/usr/bin/cat", "--", output],
                label="D1.17 checkout rehearsal evidence read",
                timeout=30,
            )
            value = strict_json(raw)
            require(
                raw == canonical_bytes(value, trailing_lf=True),
                "checkout rehearsal output is not canonical UTF-8 plus one LF",
            )
            return validate_checkout_rehearsal(value)
        finally:
            # ``temporary`` is accepted only by the exact anchored regex above.
            run(
                ["/usr/bin/rm", "-rf", "--", temporary],
                label="D1.17 checkout rehearsal temporary cleanup",
                timeout=300,
            )


HISTORICAL_EXECUTION_ACTUALS: dict[str, int | str] = {
    "benchmark_image_pulls": 13,
    "cached_input_tokens": 0,
    "completed_task_arm_runs": 0,
    "exact_model_metadata_requests": 1,
    "grader_containers": 0,
    "input_tokens": 950,
    "model_generation_calls": 1,
    "official_grader_runs": 0,
    "output_tokens": 28,
    "paid_model_calls": 1,
    "protocol_canary_generation_calls": 1,
    "provider_control_plane_requests": 1,
    "reasoning_tokens": 0,
    "scientific_model_calls": 0,
    "task_arm_reservations": 0,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_tokens": 978,
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
        "d117_execution_contracts": _request_execution_contracts(bindings),
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
            "DEVELOPMENT_TUNING_EXEC_REQUEST_016_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_018",
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
            "consumed_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
            "evidence_inventory_sha256": (
                "71c6bf1d778850c94ca808b457165da9307cac19aae00187933cf331ab6b955f"
            ),
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_016",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_payload_sha256": (
                "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
            ),
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "previous_source_head": PREVIOUS_SOURCE_HEAD,
            "public_result_available": False,
            "remote_custody_status": "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS",
            "request_016_rerun_allowed": False,
            "scientific_model_calls": 0,
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
        "_017 checkout rehearsal hash differs",
    )
    expected = _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
        loader_rehearsal=rehearsal,
        checkout_rehearsal=checkout,
    )
    require(value == expected, "_017 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_017 request bytes are not canonical UTF-8 plus one LF",
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
        "trigger commit is not the exclusive _017 sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "_017 sentinel is not a regular non-executable blob")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_017 already exists before the trigger commit",
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
    with _d117_runtime_context():
        return d116.validate_correction_source(
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
    checkout_rehearsal: Mapping[str, Any],
) -> dict[str, Any]:
    with _d117_runtime_context():
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
    with _d117_runtime_context():
        return _validate_request_impl(repository, raw, source_head=source_head)


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    with _d117_runtime_context():
        return d116.validate_sentinel_commit(
            repository,
            after,
            expected_parent=expected_parent,
            require_checked_out_head=require_checked_out_head,
        )


def _delegate(name: str, *args: Any, **kwargs: Any) -> Any:
    with _d117_runtime_context():
        return getattr(d116, name)(*args, **kwargs)


def validate_branch_trigger(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_branch_trigger", repository, event_path, **kwargs)


def write_request(repository: Path) -> dict[str, Any]:
    """Create ``_017`` only after fresh gates and both exact rehearsals."""

    with _d117_runtime_context():
        repository = resolve_repository_root(repository)
        d115._validate_secret_free_branch_environment(os.environ)
        require(
            git(repository, "symbolic-ref", "--quiet", "HEAD").strip()
            == EXPECTED_REF,
            "request rendering is on the wrong branch",
        )
        require(
            not git(
                repository, "status", "--porcelain=v1", "--untracked-files=all"
            ).strip(),
            "request rendering requires a clean worktree",
        )
        source_head = git(repository, "rev-parse", "HEAD").strip()
        target = repository.joinpath(*PurePosixPath(SENTINEL_PATH).parts)
        require(not os.path.lexists(target), "_017 sentinel already exists in worktree")
        _validate_source_impl(repository, source_head)
        observer_context = d115._pinned_gh_context()
        d115._require_no_pending_benchmark_consumers(*observer_context)
        gates = d115.collect_remote_gate_evidence(
            source_head,
            allowed_stale_pr_head=None,
            _observer_context=observer_context,
        )
        readiness = d115.collect_runner_readiness(
            repository, source_head, _observer_context=observer_context
        )
        loader = d115.collect_exact_loader_rehearsal(
            repository,
            source_head,
            readiness,
        )
        checkout = collect_exact_checkout_rehearsal(repository, source_head)
        document = _build_request_impl(
            repository,
            source_head=source_head,
            remote_gate_evidence=gates,
            runner_readiness=readiness,
            loader_rehearsal=loader,
            checkout_rehearsal=checkout,
        )
        raw = canonical_bytes(document, trailing_lf=True)
        d115._require_no_pending_benchmark_consumers(*observer_context)
        d115._validate_runner_readiness_freshness(readiness)
        d115.validate_loader_rehearsal(
            loader,
            source_head=source_head,
            runner_readiness=readiness,
        )
        validate_checkout_rehearsal(checkout)
        with d114._d114_runtime_context(), d113._d113_runtime_context():
            d113._recheck_request_write_boundary(repository, source_head, target)
        try:
            with target.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise DevelopmentTriggerError(
                "_017 sentinel could not be created exclusively"
            ) from exc
        return {
            "bytes": len(raw),
            "path": SENTINEL_PATH,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "source_head": source_head,
            "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
        }


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


def current_failure_record() -> dict[str, Any]:
    return {
        "classification": AMENDMENT_CLASSIFICATION,
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "failure_boundary": {
            "approval_materialization": "PASSED",
            "bounded_context_preflight": "PASSED",
            "branch_trigger_preflight": "PASSED",
            "exec_gate": "PASSED",
            "image_materialization": "PASSED",
            "protocol_canary": "PASSED",
            "task_arm_reservation_started": False,
        },
        "failure_subtype": PREVIOUS_FAILURE_SUBTYPE,
        "observed_execution_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_016_rerun_allowed": False,
            "request_017_execution_authorized": False,
        },
        "request": {
            "id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_016",
            "path": PREVIOUS_SENTINEL_PATH,
            "payload_sha256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": PREVIOUS_SENTINEL_SHA256,
            "source_head": PREVIOUS_SOURCE_HEAD,
        },
        "root_cause": {
            "classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failed_target": "multi_swe_bench_mini--ponylang__ponyc-1981",
            "recovery_rule": (
                "construct fresh task worktrees from pinned Git blob bytes, "
                "reject every other transform, never repair resume state, and "
                "rehearse all twelve frozen targets before provider access"
            ),
            "scope": "PRE_TASK_ARM_CHECKOUT_CONSTRUCTION",
        },
        "schema": "trimem/development-exec-016-checkout-portability-failure/1.0",
        "scientific_status": "NOT_STARTED_ON_EXEC_016",
        "status": "IMMUTABLE_EVIDENCE_CUSTODY_VERIFIED",
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
        "consumed_exec_016_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "current_execution_actuals": dict(ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": AMENDMENT_ENDPOINT,
        "external_execution_approval_received": False,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "request_present_in_recovery_source": False,
        "schema": "trimem/development-exec-017-recovery/1.0",
    }


def validate_optional_exec_017_boundary(repository: Path) -> str | None:
    """Accept only the D1.17 recovery source or its exact sentinel-only child."""

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
        require(not target.exists(), "uncommitted `_017` request exists")
        return None
    require(len(additions) == 1, "`_017` was added more than once")
    execution_head = additions[0]
    require(execution_head == head, "commits exist after the active `_017` request")
    parents = git(repository, "rev-list", "--parents", "-n", "1", execution_head).split()
    require(len(parents) == 2, "`_017` parent differs")
    validate_sentinel_commit(
        repository,
        execution_head,
        expected_parent=parents[1],
        require_checked_out_head=True,
    )
    return execution_head


def validate_current_recovery(repository: Path) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    execution_head = validate_optional_exec_017_boundary(repository)
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
        "request_016_attempt_one_consumed": True,
        "request_016_rerun_allowed": False,
        "request_017_created": execution_head is not None,
        "request_017_execution_authorized": False,
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
                args.repository,
                args.source_head,
                require_checked_out_head=True,
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
