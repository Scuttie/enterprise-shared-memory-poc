"""Fail-closed one-time DEVELOPMENT_TUNING ``_019`` recovery trigger.

D1.19 preserves the spent ``_018`` execution as immutable history.  That run
failed closed while materializing an externally produced approval secret whose
text acquired a leading U+FEFF; it reached no provider, model, image, grader, or
task-arm operation.  The recovery keeps the workflow's strict Base64 decoder
and moves approval-secret transport to a byte-only, round-trip-verified path.
Importing this module has no network, Docker, grader, credential, image, model,
or GitHub mutation side effect.
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

import trimem_development_trigger_d118 as d118


d115 = d118.d115
d114 = d118.d114
d113 = d118.d113
d112 = d118.d112

EXPECTED_REPOSITORY = d118.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d118.EXPECTED_BRANCH
EXPECTED_REF = d118.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d118.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d118.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d118.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d118.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d118.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d118.EXPECTED_BASE_HEAD

PREVIOUS_SOURCE_HEAD = "3236bd546ff581e396ca6123bb1655bad5294ce4"
PREVIOUS_EXECUTION_HEAD = "5cce6502a61c81c2e0490578dc5a2a3045f8c179"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_018.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "9264a90a8ace461f515e4725d4058e5ee486fa7304364cf75d65dfba6be603a0"
)
PREVIOUS_SENTINEL_BYTES = 48_072
PREVIOUS_SENTINEL_BLOB_OID = "a5b61b9524fe87cdb9c56202f034c3f028c1665c"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "f008b7d7a117966ae389a11d0c645fec64e0a0687c654f870a49968bd4ce3f43"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "fa52e13a2e88bcc7bc0a22a300fdace9902bbad8907b427e6f5c62fd67f7b61d"
)
PREVIOUS_RUN_ID = 34_211_486_542
PREVIOUS_RUN_ATTEMPT = 1
PREVIOUS_FAILURE_SUBTYPE = "EXTERNAL_APPROVAL_BASE64_UFEFF_PREFIX"
PREVIOUS_FAILURE_CLASSIFICATION = "APPROVAL_SECRET_TRANSPORT_ENCODING_FAILURE"
PREVIOUS_FAILURE_MESSAGE = "string argument should contain only ASCII characters"
PREVIOUS_FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d119/exec_018_approval_bom_failure.json"
)
PREVIOUS_FAILURE_FIXTURE_SHA256 = (
    "19387c022f8b06411adf497500e1fdf788ff891082654ba8137acf715fa70463"
)
PREVIOUS_FAILURE_FIXTURE_BYTES = 4_959

STARTING_SOURCE_HEAD = PREVIOUS_EXECUTION_HEAD
STARTING_FREEZE_SHA256 = PREVIOUS_SOURCE_FREEZE_SHA256
BASELINE_SOURCE_HEAD = STARTING_SOURCE_HEAD
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_019"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.19"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_019.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_019_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-019"

AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_019_recovery_amendment.json"
)
AMENDMENT_SCHEMA = "trimem/development-exec-019-approval-secret-transport-amendment/1.0"
INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_019_recovery_inventory.json"
)
INVENTORY_SCHEMA = "trimem/development-exec-019-approval-secret-transport-inventory/1.0"
AMENDMENT_CLASSIFICATION = (
    "POST_EXEC_018_PRE_MODEL_APPROVAL_SECRET_TRANSPORT_RECOVERY"
)
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_018_PRE_MODEL_APPROVAL_FAILURE_"
    "READY_FOR_EXEC_019_REQUEST"
)
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_019_REQUEST"
REPORT_PATH = "reports/TRIMEM_D119_EXEC_019_RECOVERY.md"
TRIGGER_PATH = "scripts/trimem_development_trigger_d119.py"
APPROVAL_SECRET_PATH = "scripts/trimem_d119_approval_secret.py"
CHECKOUT_REHEARSAL_PATH = d118.CHECKOUT_REHEARSAL_PATH
EXACT_HEAD_GATE_WORKFLOW_PATH = ".github/workflows/ci-trimem-dev-toolchain.yml"
LOADER_REHEARSAL_COLLECTOR_PATH = "scripts/trimem_d119_loader_rehearsal.py"
GRADER_FACTORY_REHEARSAL_PATH = d118.GRADER_FACTORY_REHEARSAL_PATH

FREEZE_PATH = d118.FREEZE_PATH
FREEZE_SCHEMA = d118.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.19"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.19"

MODEL_ID = d118.MODEL_ID
REASONING_EFFORT = d118.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d118.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d118.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d118.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d118.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d118.ACTIVATION_ZERO_COUNTERS
REMOTE_GATE_SPECS = d118.REMOTE_GATE_SPECS
REQUIRED_REMOTE_GATE_WORKFLOWS = d118.REQUIRED_REMOTE_GATE_WORKFLOWS
PRESERVED_SCIENTIFIC_PATHS = d118.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d118.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d118.EXECUTION_CONTRACT_PATHS
CHECKOUT_ACTION_SHA = d118.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d118.SETUP_PYTHON_ACTION_SHA
HEX40 = d118.HEX40

DevelopmentTriggerError = d118.DevelopmentTriggerError
require = d118.require
canonical_bytes = d118.canonical_bytes
strict_json = d118.strict_json
git = d118.git
commit_bytes = d118.commit_bytes
resolve_repository_root = d118.resolve_repository_root
_is_ancestor = d118._is_ancestor


# Only approval-secret production, active routing/readiness, and direct tests
# may differ from the consumed _018 execution.  The strict decoder and frozen
# tasks, arms, prompts, images, graders, model, pricing, selection, and stream
# order are excluded.
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
        APPROVAL_SECRET_PATH,
        LOADER_REHEARSAL_COLLECTOR_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_multi_swe_contract.py",
        TRIGGER_PATH,
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d114_post_setup_environment.py",
        "tests/unit/test_trimem_d118_trigger.py",
        "tests/unit/test_trimem_d119_approval_secret.py",
        "tests/unit/test_trimem_d119_trigger.py",
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
    APPROVAL_SECRET_PATH: "A",
    LOADER_REHEARSAL_COLLECTOR_PATH: "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    TRIGGER_PATH: "A",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d114_post_setup_environment.py": "M",
    "tests/unit/test_trimem_d118_trigger.py": "M",
    "tests/unit/test_trimem_d119_approval_secret.py": "A",
    "tests/unit/test_trimem_d119_trigger.py": "A",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}
ALLOWED_ACTIVATION_PATHS = ALLOWED_RECOVERY_PATHS
REQUIRED_ACTIVATION_CHANGES = REQUIRED_RECOVERY_CHANGES

ACTIVATION_BINDING_PATHS = {
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "checkout_rehearsal_sha256": CHECKOUT_REHEARSAL_PATH,
    "grader_factory_rehearsal_sha256": GRADER_FACTORY_REHEARSAL_PATH,
    "approval_secret_producer_sha256": APPROVAL_SECRET_PATH,
    "d119_amendment_sha256": AMENDMENT_PATH,
    "d119_inventory_sha256": INVENTORY_PATH,
    "d119_run_fixture_sha256": PREVIOUS_FAILURE_FIXTURE_PATH,
    "d119_trigger_reader_sha256": TRIGGER_PATH,
    "loader_rehearsal_collector_sha256": LOADER_REHEARSAL_COLLECTOR_PATH,
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


_D118_CONTEXT_LOCK = threading.RLock()


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
def _d119_runtime_context() -> Iterator[None]:
    """Bind inherited D1.18 adapters to one coherent D1.19 view."""

    with (
        _D118_CONTEXT_LOCK,
        d118._D117_CONTEXT_LOCK,
        d118.d117._D116_CONTEXT_LOCK,
        d115._D114_CONTEXT_LOCK,
        d114._D113_CONTEXT_LOCK,
        d113._D112_CONTEXT_LOCK,
    ):
        bindings = _context_bindings()
        previous = {name: getattr(d118, name) for name in bindings}
        try:
            for name, value in bindings.items():
                setattr(d118, name, value)
            # D1.19 calls some implementation functions directly while this
            # context is active.  Propagate the dynamic bindings through both
            # inherited adapters so those calls observe one coherent D1.19
            # identity all the way down to D1.14 (not a stale D1.14/D1.15
            # sentinel or schema).  The inherited contexts are re-entrant and
            # restore their own modules before we restore D1.19 below.
            with d118._d118_runtime_context(), d115._d115_runtime_context():
                yield
        finally:
            for name, value in reversed(tuple(previous.items())):
                setattr(d118, name, value)


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


validate_loader_rehearsal_record = d118.validate_loader_rehearsal_record


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _018 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _018 execution parent differs",
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
        "immutable _018 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _018 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n")
        and b"\r" not in raw,
        "immutable _018 sentinel raw bytes differ",
    )
    previous = strict_json(raw)
    bindings = previous.get("bindings")
    require(
        previous.get("schema") == "trimem/development-tuning-branch-trigger/1.18"
        and previous.get("request_id") == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_018"
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
        "immutable _018 request identity, bytes, or zero authority differs",
    )
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.19 source does not preserve immutable EXEC _018",
    )
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical _018 request changed after execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "_019 exists in recovery-source history",
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
        "EXEC _018 failure fixture bytes differ",
    )
    workflow = value.get("workflow_run")
    jobs = value.get("jobs")
    actuals = value.get("actuals")
    approval = value.get("approval_boundary")
    boundary = value.get("boundary")
    failure = value.get("failure")
    cause = value.get("root_cause")
    custody = value.get("evidence_custody")
    request = value.get("request")
    require(
        value.get("schema")
        == "trimem/development-exec-018-approval-secret-bom-failure/1.0"
        and value.get("repository") == EXPECTED_REPOSITORY
        and value.get("branch") == EXPECTED_BRANCH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("execution_head") == PREVIOUS_EXECUTION_HEAD
        and value.get("performance_measured") is False
        and value.get("pass_at_1") is None,
        "EXEC _018 failure fixture identity differs",
    )
    require(
        workflow
        == {
            "conclusion": "failure",
            "created_at": "2026-09-08T09:42:33Z",
            "event": "push",
            "head_sha": PREVIOUS_EXECUTION_HEAD,
            "html_url": (
                "https://github.com/Scuttie/enterprise-shared-memory-poc/"
                "actions/runs/34211486542"
            ),
            "id": PREVIOUS_RUN_ID,
            "path": EXPECTED_WORKFLOW_PATH,
            "run_attempt": PREVIOUS_RUN_ATTEMPT,
            "status": "completed",
            "updated_at": "2026-09-08T09:59:23Z",
        },
        "EXEC _018 workflow identity differs",
    )
    require(
        jobs
        == [
            {
                "completed_at": "2026-09-08T09:42:58Z",
                "conclusion": "success",
                "id": 102_013_284_681,
                "name": "branch-trigger-preflight",
                "started_at": "2026-09-08T09:42:35Z",
            },
            {
                "completed_at": "2026-09-08T09:48:14Z",
                "conclusion": "success",
                "id": 102_013_411_023,
                "name": "bounded-context-preflight",
                "started_at": "2026-09-08T09:43:02Z",
            },
            {
                "completed_at": "2026-09-08T09:59:23Z",
                "conclusion": "failure",
                "id": 102_014_971_076,
                "name": "frozen-serial-phase",
                "started_at": "2026-09-08T09:58:30Z",
            },
        ],
        "EXEC _018 workflow jobs differ",
    )
    require(actuals == HISTORICAL_EXECUTION_ACTUALS, "EXEC _018 accounting differs")
    require(
        approval
        == {
            "approval_json_bytes": 1_027,
            "approval_json_sha256": (
                "7d737413fcb3a0ff179f49016f7a71aa1c90a841238f71df2f9c1af9b821e6d5"
            ),
            "approval_materialization": "FAIL_CLOSED",
            "decoder": "base64.b64decode(value, validate=True)",
            "environment_secret_count_after_cleanup": 0,
            "exec_gate": "NOT_REACHED",
            "intended_base64_bytes": 1_372,
            "intended_base64_sha256": (
                "f84f47603ec73e8a443a01ead6c58b286878514c1bd8d551442ea47f19049417"
            ),
            "intended_base64_validated": True,
            "observed_non_ascii_character": "U+FEFF",
            "observed_non_ascii_position": 0,
            "protected_environment_entered": True,
        },
        "EXEC _018 approval materialization boundary differs",
    )
    require(
        boundary
        == {
            "aggregate_entered": False,
            "bounded_context_preflight": "PASS",
            "branch_trigger_preflight": "PASS",
            "cache_only_service_cleanup": "PASS",
            "campaign_result_available": False,
            "exact_model_metadata": "NOT_REACHED",
            "failure_stage": "PROTECTED_APPROVAL_MATERIALIZATION_PRE_EXEC_GATE",
            "final_custody_cleanup": "FAIL_CLOSED_CUSTODY_OUTPUTS_SKIPPED",
            "image_materialization": "NOT_REACHED",
            "protected_grader_factory_rehearsal": "PASS",
            "protocol_canary": "NOT_REACHED",
            "task_arm_reservation_started": False,
        },
        "EXEC _018 pre-execution boundary differs",
    )
    require(
        isinstance(failure, Mapping)
        and failure.get("exception_chain") == ["UnicodeEncodeError", "ValueError"]
        and failure.get("final_message") == PREVIOUS_FAILURE_MESSAGE
        and failure.get("frozen_job_log_bytes") == 140_761
        and failure.get("frozen_job_log_sha256")
        == "fb32b0d75e9d8732d7437dde095681e11ae89b2312882782697dca3286ec97ad"
        and failure.get("process_exit_code") == 1
        and failure.get("request_018_attempt_one_consumed") is True
        and failure.get("request_018_rerun_allowed") is False
        and failure.get("resume_eligible") is False,
        "EXEC _018 decoder failure evidence differs",
    )
    require(
        request
        == {
            "id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_018",
            "path": PREVIOUS_SENTINEL_PATH,
            "payload_sha256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": PREVIOUS_SENTINEL_SHA256,
            "source_head": PREVIOUS_SOURCE_HEAD,
        },
        "EXEC _018 request evidence differs",
    )
    require(
        cause
        == {
            "classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_subtype": PREVIOUS_FAILURE_SUBTYPE,
            "recovery_contract": {
                "approval_document_rebuilt_for_new_run_attempt_one": True,
                "base64_ascii_no_bom_whitespace_validation": True,
                "base64_round_trip_validation": True,
                "byte_only_external_secret_production": True,
                "strict_workflow_decoder_preserved": True,
            },
            "scope": "EXTERNAL_POWERSHELL_STDIN_SECRET_UPLOAD",
            "scientific_result": False,
        },
        "EXEC _018 approval-secret root-cause replay differs",
    )
    require(
        custody
        == {
            "github_artifacts": [],
            "public_result": "ABSENT_EXPECTED",
            "remote_custody_status": "NOT_APPLICABLE_PRE_APPROVAL_MATERIALIZATION",
            "runner_removed_after_failure": True,
            "secrets_removed_after_failure": True,
        },
        "EXEC _018 cleanup/custody boundary differs",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    require(
        source_head != PREVIOUS_EXECUTION_HEAD
        and _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.19 source is not a strict descendant of immutable EXEC _018",
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
        require(len(pieces) == 2, "D1.19 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.19 diff status is forbidden: {status}")
        require(path in ALLOWED_RECOVERY_PATHS, f"D1.19 changed forbidden path: {path}")
        require(path not in changes, f"D1.19 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.19 recovery change is missing or has wrong status: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path),
            f"frozen scientific input changed during D1.19 recovery: {path}",
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
        "active push sentinel is not exclusively _019",
    )
    require(
        workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and "group: trimem-v1-development-tuning-exec-018" not in workflow,
        "_019 concurrency identity differs",
    )
    branch_marker = "  branch-trigger-preflight:\n"
    bounded_marker = "  bounded-context-preflight:\n"
    frozen_marker = "  frozen-serial-phase:\n"
    require(
        all(workflow.count(marker) == 1 for marker in (branch_marker, bounded_marker, frozen_marker)),
        "D1.19 workflow job identity differs",
    )
    branch_start = workflow.index(branch_marker)
    bounded_start = workflow.index(bounded_marker)
    frozen_start = workflow.index(frozen_marker)
    require(branch_start < bounded_start < frozen_start, "D1.19 job order differs")
    branch_job = workflow[branch_start:bounded_start]
    bounded_job = workflow[bounded_start:frozen_start]
    frozen_job = workflow[frozen_start:]
    command = "python -I -S scripts/trimem_development_trigger_d119.py"
    require(
        branch_job.count(command) == 1
        and bounded_job.count(command) == 1
        and frozen_job.count(command) == 4
        and "scripts/trimem_development_trigger_d118.py" not in workflow,
        "active trigger validator is not exclusively D1.19 _019",
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
        "D1.19 hosted/self-hosted/protected boundary differs",
    )
    for action, digest in (
        ("actions/checkout", CHECKOUT_ACTION_SHA),
        ("actions/setup-python", SETUP_PYTHON_ACTION_SHA),
    ):
        require(
            f"{action}@v" not in workflow and f"{action}@{digest}" in workflow,
            f"D1.19 workflow action is mutable: {action}",
        )
    strict_decoder = (
        "base64.b64decode(os.environ['TRIMEM_EXEC_APPROVAL_B64'], validate=True)"
    )
    require(
        workflow.count(strict_decoder) == 1
        and "lstrip(\"\\ufeff\")" not in workflow
        and ".lstrip('\\ufeff')" not in workflow
        and "errors=\"ignore\"" not in workflow
        and "errors='ignore'" not in workflow,
        "strict approval Base64 decoder was weakened",
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
        "D1.19 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_018_attempt_one_consumed") is True
        and authority.get("request_018_rerun_allowed") is False
        and authority.get("request_019_request_creation_authorized") is True
        and authority.get("request_019_created_in_source") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_019_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION,
        "D1.19 authority boundary differs",
    )
    require(
        amendment.get("consumed_execution_actuals") == HISTORICAL_EXECUTION_ACTUALS,
        "D1.19 amendment does not preserve exact zero EXEC _018 accounting",
    )
    implementation = amendment.get("implementation_sha256")
    expected_implementation_paths = {
        EXPECTED_WORKFLOW_PATH,
        APPROVAL_SECRET_PATH,
        LOADER_REHEARSAL_COLLECTOR_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        TRIGGER_PATH,
    }
    require(
        isinstance(implementation, Mapping)
        and implementation == inventory.get("implementation_sha256")
        and set(implementation) == expected_implementation_paths,
        "D1.19 implementation seal shape differs",
    )
    for path in sorted(expected_implementation_paths):
        require(
            implementation.get(path)
            == hashlib.sha256(commit_bytes(repository, source_head, path)).hexdigest(),
            f"D1.19 implementation seal differs: {path}",
        )
    require(
        amendment.get("recovery_contract")
        == {
            "approval_document_rebuilt_for_new_run_attempt_one": True,
            "base64_ascii_no_bom_whitespace_validation": True,
            "base64_round_trip_validation": True,
            "byte_only_external_secret_production": True,
            "strict_workflow_decoder_preserved": True,
        },
        "D1.19 approval-secret recovery contract differs",
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
        "scientific identity differs from immutable _018",
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
    result = deepcopy(dict(d118._request_execution_contracts(bindings)))
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
    result["official_grader_preflight_launcher_binding"] = {
        "factory_full_identity_check_before_model": True,
        "factory_reuses_preflight_lexical_launcher": True,
        "journal_reuses_preflight_lexical_launcher": True,
        "protected_driver_uses_exact_python3_11": True,
        "protected_precredential_synthetic_rehearsal": True,
        "twelve_target_credential_free_factory_rehearsal": True,
    }
    result["contract_bindings"]["grader_factory_rehearsal_sha256"] = bindings[
        "grader_factory_rehearsal_sha256"
    ]
    result["approval_secret_encoding"] = {
        "approval_document_rebuilt_for_new_run_attempt_one": True,
        "base64_ascii_no_bom_whitespace_validation": True,
        "base64_round_trip_validation": True,
        "byte_only_external_secret_production": True,
        "strict_workflow_decoder_preserved": True,
    }
    result["contract_bindings"]["approval_secret_producer_sha256"] = bindings[
        "approval_secret_producer_sha256"
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
    with tempfile.TemporaryDirectory(prefix="trimem-d119-source-bundle-") as host_temp:
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
            label="D1.19 source bundle path translation",
            timeout=30,
        ).decode("utf-8", errors="strict").strip()
        require(
            bundle_wsl.startswith("/") and "\x00" not in bundle_wsl,
            "D1.19 WSL source bundle path differs",
        )
        temporary = run(
            [
                "/usr/bin/mktemp",
                "-d",
                "-p",
                "/tmp",
                "trimem-d119-writer-XXXXXXXXXX",
            ],
            label="D1.19 checkout rehearsal temporary root",
            timeout=30,
        ).decode("ascii", errors="strict").strip()
        require(
            re.fullmatch(r"/tmp/trimem-d119-writer-[A-Za-z0-9]+", temporary)
            is not None,
            "D1.19 checkout rehearsal temporary root differs",
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
                label="D1.19 exact source bundle clone",
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
                label="D1.19 exact source checkout",
                timeout=300,
            )
            observed_head = run(
                [*isolated, "/usr/bin/git", "-C", source, "rev-parse", "HEAD"],
                label="D1.19 exact source HEAD verification",
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
                label="D1.19 exact source cleanliness verification",
                timeout=30,
            )
            require(
                observed_head == source_head and observed_status == b"",
                "D1.19 WSL source checkout is not exact and clean",
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
                label="D1.19 checkout rehearsal evidence read",
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
                label="D1.19 checkout rehearsal temporary cleanup",
                timeout=300,
            )


HISTORICAL_EXECUTION_ACTUALS: dict[str, int | str] = {
    "benchmark_image_pulls": 0,
    "cached_input_tokens": 0,
    "completed_task_arm_runs": 0,
    "decomposition_calls": 0,
    "exact_model_metadata_requests": 0,
    "extraction_calls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "model_generation_calls": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "protocol_canary_generation_calls": 0,
    "provider_control_plane_requests": 0,
    "reasoning_tokens": 0,
    "scientific_model_calls": 0,
    "solve_calls": 0,
    "task_arm_reservations": 0,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_tokens": 0,
    "total_usd": "0.000000000000",
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
        "d119_execution_contracts": _request_execution_contracts(bindings),
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
            "DEVELOPMENT_TUNING_EXEC_REQUEST_018_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_020",
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
            "failure_fixture_sha256": "sha256:" + PREVIOUS_FAILURE_FIXTURE_SHA256,
            "frozen_job_log_sha256": (
                "sha256:fb32b0d75e9d8732d7437dde095681e11ae89b2312882782697dca3286ec97ad"
            ),
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": PREVIOUS_RUN_ATTEMPT,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "failure_message": PREVIOUS_FAILURE_MESSAGE,
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_018",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_payload_sha256": (
                "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
            ),
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "previous_source_head": PREVIOUS_SOURCE_HEAD,
            "public_result_available": False,
            "remote_custody_status": "NOT_APPLICABLE_PRE_APPROVAL_MATERIALIZATION",
            "request_018_rerun_allowed": False,
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
        "_019 checkout rehearsal hash differs",
    )
    expected = _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
        loader_rehearsal=rehearsal,
        checkout_rehearsal=checkout,
    )
    require(value == expected, "_019 request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "_019 request bytes are not canonical UTF-8 plus one LF",
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
        "trigger commit is not the exclusive _019 sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "_019 sentinel is not a regular non-executable blob")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_019 already exists before the trigger commit",
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
    with _d119_runtime_context():
        return d118.validate_correction_source(
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
    with _d119_runtime_context():
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
    with _d119_runtime_context():
        return _validate_request_impl(repository, raw, source_head=source_head)


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    with _d119_runtime_context():
        return d118.validate_sentinel_commit(
            repository,
            after,
            expected_parent=expected_parent,
            require_checked_out_head=require_checked_out_head,
        )


def _delegate(name: str, *args: Any, **kwargs: Any) -> Any:
    with _d119_runtime_context():
        return getattr(d118, name)(*args, **kwargs)


def validate_branch_trigger(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_branch_trigger", repository, event_path, **kwargs)


def write_request(repository: Path) -> dict[str, Any]:
    """Create ``_019`` only after fresh gates and exact rehearsals."""

    with _d119_runtime_context():
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
        require(not os.path.lexists(target), "_019 sentinel already exists in worktree")
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
                "_019 sentinel could not be created exclusively"
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
            "approval_materialization": "FAIL_CLOSED",
            "bounded_context_preflight": "PASS",
            "branch_trigger_preflight": "PASS",
            "exec_gate": "NOT_REACHED",
            "image_materialization": "NOT_REACHED",
            "model_metadata": "NOT_REACHED",
            "protocol_canary": "NOT_REACHED",
            "protected_grader_factory_rehearsal": "PASS",
            "scientific_model_calls": 0,
            "task_arm_reservation_started": False,
            "terminal_cells": 0,
        },
        "failure_subtype": PREVIOUS_FAILURE_SUBTYPE,
        "observed_execution_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_018_rerun_allowed": False,
            "request_019_execution_authorized": False,
        },
        "request": {
            "id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_018",
            "path": PREVIOUS_SENTINEL_PATH,
            "payload_sha256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": PREVIOUS_SENTINEL_SHA256,
            "source_head": PREVIOUS_SOURCE_HEAD,
        },
        "root_cause": {
            "classification": PREVIOUS_FAILURE_CLASSIFICATION,
            "failed_target": None,
            "recovery_rule": (
                "rebuild a fresh run-bound approval and Base64 payload using "
                "Python bytes only; verify ASCII, no BOM or whitespace, and "
                "strict Base64 round trip before secret upload; preserve the "
                "workflow decoder unchanged"
            ),
            "scope": "PROTECTED_APPROVAL_MATERIALIZATION_PRE_EXEC_GATE",
        },
        "schema": "trimem/development-exec-018-approval-secret-bom-failure/1.0",
        "scientific_status": "NOT_STARTED_ON_EXEC_018",
        "status": "IMMUTABLE_PUBLIC_RUN_EVIDENCE_VERIFIED",
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
        "consumed_exec_018_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "current_execution_actuals": dict(ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": AMENDMENT_ENDPOINT,
        "external_execution_approval_received": False,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "request_present_in_recovery_source": False,
        "schema": "trimem/development-exec-019-recovery/1.0",
    }


def validate_optional_exec_019_boundary(repository: Path) -> str | None:
    """Accept only the D1.19 recovery source or exact sentinel-only child."""

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
        require(not target.exists(), "uncommitted `_019` request exists")
        return None
    require(len(additions) == 1, "`_019` was added more than once")
    execution_head = additions[0]
    require(execution_head == head, "commits exist after the active `_019` request")
    parents = git(repository, "rev-list", "--parents", "-n", "1", execution_head).split()
    require(len(parents) == 2, "`_019` parent differs")
    validate_sentinel_commit(
        repository,
        execution_head,
        expected_parent=parents[1],
        require_checked_out_head=True,
    )
    return execution_head


def validate_current_recovery(repository: Path) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    execution_head = validate_optional_exec_019_boundary(repository)
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
        "request_018_attempt_one_consumed": True,
        "request_018_rerun_allowed": False,
        "request_019_created": execution_head is not None,
        "request_019_execution_authorized": False,
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
