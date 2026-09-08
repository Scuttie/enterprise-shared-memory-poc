"""Fail-closed D1.23 activation for one fresh DEV EXEC ``_022`` request.

D1.23 binds the credential-free D1.22 repair evidence to a new source commit.
The source may create exactly one ``_022`` sentinel-only child after its own
remote gates and runner rehearsals pass. The sentinel never grants execution
authority; a separate run/attempt-bound external approval is still required.

Importing this module performs no network, Docker, grader, credential, image,
model, GitHub, or filesystem-mutation operation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import threading
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d121 as d121
import trimem_development_trigger_d122 as d122


d120 = d121.d120
d119 = d121.d119
d118 = d121.d118
d115 = d121.d115
d114 = d121.d114
d113 = d121.d113
d112 = d121.d112

EXPECTED_REPOSITORY = d121.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d121.EXPECTED_BRANCH
EXPECTED_REF = d121.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d121.EXPECTED_WORKFLOW_PATH
EXPECTED_WORKFLOW_REF = d121.EXPECTED_WORKFLOW_REF
EXPECTED_PHASE = d121.EXPECTED_PHASE
PULL_REQUEST_NUMBER = d121.PULL_REQUEST_NUMBER
EXPECTED_BASE_BRANCH = d121.EXPECTED_BASE_BRANCH
EXPECTED_BASE_HEAD = d121.EXPECTED_BASE_HEAD

# Immutable spent EXEC-021 and verified D1.22 recovery identities.
PREVIOUS_SOURCE_HEAD = d122.PREVIOUS_SOURCE_HEAD
PREVIOUS_EXECUTION_HEAD = d122.PREVIOUS_EXECUTION_HEAD
PREVIOUS_SENTINEL_PATH = d122.PREVIOUS_SENTINEL_PATH
PREVIOUS_SENTINEL_SHA256 = d122.PREVIOUS_SENTINEL_SHA256
PREVIOUS_SENTINEL_BYTES = d122.PREVIOUS_SENTINEL_BYTES
PREVIOUS_SENTINEL_BLOB_OID = d122.PREVIOUS_SENTINEL_BLOB_OID
PREVIOUS_REQUEST_PAYLOAD_SHA256 = d122.PREVIOUS_REQUEST_PAYLOAD_SHA256
PREVIOUS_SOURCE_FREEZE_SHA256 = d122.PREVIOUS_SOURCE_FREEZE_SHA256
PREVIOUS_RUN_ID = d122.PREVIOUS_RUN_ID
PREVIOUS_RUN_ATTEMPT = d122.PREVIOUS_RUN_ATTEMPT
PREVIOUS_FAILURE_SUBTYPE = d122.FAILURE_SUBTYPE
PREVIOUS_FAILURE_CLASSIFICATION = d122.FAILURE_CLASSIFICATION
PREVIOUS_FAILURE_MESSAGE = (
    "Qdrant/RocksDB exhausted the inherited soft nofile limit while creating "
    "the first private collection of the third stream"
)
PREVIOUS_FAILURE_FIXTURE_PATH = d122.FAILURE_FIXTURE_PATH
PREVIOUS_FAILURE_FIXTURE_SHA256 = d122.FAILURE_FIXTURE_SHA256
PREVIOUS_FAILURE_FIXTURE_BYTES = d122.FAILURE_FIXTURE_BYTES

BASELINE_SOURCE_HEAD = "cfa79b2406f174bd152eb873e98018725947d349"
STARTING_SOURCE_HEAD = BASELINE_SOURCE_HEAD
# This value is retained only as a historical compatibility binding; D1.23
# validates the exact baseline freeze directly from the baseline commit.
STARTING_FREEZE_SHA256 = (
    "c1f06ddedbfcde0de46407a8ee271c562bb32a9d4844dff6c6a05c5a3645b8a7"
)
BASELINE_FREEZE_SHA256 = STARTING_FREEZE_SHA256

REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_022"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.23"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_022.json"
)
ACTIVE_SENTINEL_PATH = SENTINEL_PATH
CURRENT_ACTIVE_WORKFLOW_REF = EXPECTED_WORKFLOW_REF
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_022_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-022"

AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_022_activation_amendment.json"
)
AMENDMENT_SCHEMA = "trimem/development-exec-022-activation-amendment/1.0"
INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_022_activation_inventory.json"
)
INVENTORY_SCHEMA = "trimem/development-exec-022-activation-inventory/1.0"
AMENDMENT_CLASSIFICATION = (
    "POST_EXEC_021_FRESH_EXEC_022_CREDENTIAL_FREE_ACTIVATION"
)
AMENDMENT_STATUS = "READY_FOR_EXEC_022_REQUEST"
AMENDMENT_ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_022_REQUEST"
REPORT_PATH = "reports/TRIMEM_D123_EXEC_022_ACTIVATION.md"
TRIGGER_PATH = "scripts/trimem_development_trigger_d123.py"
RESEAL_PATH = "scripts/trimem_d123_reseal.py"
APPROVAL_SECRET_PATH = d121.APPROVAL_SECRET_PATH
CHECKOUT_REHEARSAL_PATH = d121.CHECKOUT_REHEARSAL_PATH
EXACT_HEAD_GATE_WORKFLOW_PATH = d121.EXACT_HEAD_GATE_WORKFLOW_PATH
LOADER_REHEARSAL_COLLECTOR_PATH = "scripts/trimem_d123_loader_rehearsal.py"
GRADER_FACTORY_REHEARSAL_PATH = d121.GRADER_FACTORY_REHEARSAL_PATH
REMOTE_CI_EVIDENCE_PATH = (
    "tests/fixtures/trimem_d123/d122_remote_ci_evidence.json"
)
REMOTE_CI_EVIDENCE_BYTES = 2_090
REMOTE_CI_EVIDENCE_SHA256 = (
    "0abfc20181ca47e4ada3e1bb847ff91347d1f8d99844157cbb2e5e7e623b9e6a"
)
D122_EVIDENCE_WORKFLOWS = frozenset(
    {
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/ci-trimem-e2e.yml",
        ".github/workflows/ci-trimem-grader-loader.yml",
        ".github/workflows/ci-trimem-harness-lock.yml",
        ".github/workflows/ci-trimem-multi-swe-contract.yml",
    }
)

FREEZE_PATH = d121.FREEZE_PATH
FREEZE_SCHEMA = d121.FREEZE_SCHEMA
REMOTE_GATE_SCHEMA = "trimem/development-activation-gate-evidence/1.23"
RUNNER_READINESS_SCHEMA = "trimem/self-hosted-runner-readiness/1.23"

MODEL_ID = d121.MODEL_ID
REASONING_EFFORT = d121.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d121.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d121.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d121.EXPECTED_DEVELOPMENT_HARD_CAP
DEVELOPMENT_APPROVAL_FIELDS = d121.DEVELOPMENT_APPROVAL_FIELDS
ACTIVATION_ZERO_COUNTERS = d121.ACTIVATION_ZERO_COUNTERS
REMOTE_GATE_SPECS = d121.REMOTE_GATE_SPECS
REQUIRED_REMOTE_GATE_WORKFLOWS = d121.REQUIRED_REMOTE_GATE_WORKFLOWS
PRESERVED_SCIENTIFIC_PATHS = d121.PRESERVED_SCIENTIFIC_PATHS
SCIENCE_BINDING_PATHS = d121.SCIENCE_BINDING_PATHS
EXECUTION_CONTRACT_PATHS = d121.EXECUTION_CONTRACT_PATHS
CHECKOUT_ACTION_SHA = d121.CHECKOUT_ACTION_SHA
SETUP_PYTHON_ACTION_SHA = d121.SETUP_PYTHON_ACTION_SHA
HEX40 = d121.HEX40

DevelopmentTriggerError = d121.DevelopmentTriggerError
require = d121.require
canonical_bytes = d121.canonical_bytes
strict_json = d121.strict_json
git = d121.git
commit_bytes = d121.commit_bytes
resolve_repository_root = d121.resolve_repository_root
_is_ancestor = d121._is_ancestor
_tree_entry = d121._tree_entry

HISTORICAL_EXECUTION_ACTUALS = deepcopy(d122.HISTORICAL_EXECUTION_ACTUALS)
SCIENTIFIC_EXECUTION_ACTUALS = deepcopy(d122.SCIENTIFIC_EXECUTION_ACTUALS)
CANARY_EXECUTION_ACTUALS = deepcopy(d122.CANARY_EXECUTION_ACTUALS)
ZERO_CURRENT_EXECUTION_ACTUALS = deepcopy(d122.ZERO_CURRENT_EXECUTION_ACTUALS)
ZERO_SCIENTIFIC_ACTUALS = ZERO_CURRENT_EXECUTION_ACTUALS

FRESH_EXECUTION_CONTRACT: dict[str, Any] = {
    "cross_run_resume_allowed": False,
    "grader_containers": 72,
    "historical_partial_cells_reused": 0,
    "input_token_cap": 36_004_096,
    "new_campaign_starts_at_sequence_zero": True,
    "output_token_cap": 4_720_640,
    "paid_model_call_cap": 1_873,
    "partial_candidate_checkpoint_selection_allowed": False,
    "protocol_canary_generation_calls": 1,
    "scientific_generation_call_cap": 1_872,
    "task_arm_runs": 72,
    "total_usd_hard_cap": 50.0,
}

ALLOWED_ACTIVATION_PATHS = frozenset(
    {
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        ".github/workflows/trimem-benchmark.yml",
        AMENDMENT_PATH,
        INVENTORY_PATH,
        REMOTE_CI_EVIDENCE_PATH,
        REPORT_PATH,
        LOADER_REHEARSAL_COLLECTOR_PATH,
        RESEAL_PATH,
        TRIGGER_PATH,
        "artifacts/trimem_v1/freeze.json",
        "artifacts/trimem_v1/readiness_requirements.json",
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d114_post_setup_environment.py",
        "tests/unit/test_trimem_d121_trigger.py",
        "tests/unit/test_trimem_d122_trigger.py",
        "tests/unit/test_trimem_d123_trigger.py",
        "tests/unit/test_trimem_d16_native_action.py",
        "tests/unit/test_trimem_d16_native_action_protocol.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    }
)
ALLOWED_RECOVERY_PATHS = ALLOWED_ACTIVATION_PATHS

REQUIRED_ACTIVATION_CHANGES: dict[str, str] = {
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    REMOTE_CI_EVIDENCE_PATH: "A",
    REPORT_PATH: "A",
    LOADER_REHEARSAL_COLLECTOR_PATH: "A",
    RESEAL_PATH: "A",
    TRIGGER_PATH: "A",
    "artifacts/trimem_v1/freeze.json": "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_d123_trigger.py": "A",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}
REQUIRED_RECOVERY_CHANGES = REQUIRED_ACTIVATION_CHANGES

IMPLEMENTATION_SEAL_PATHS = frozenset(
    {
        EXPECTED_WORKFLOW_PATH,
        LOADER_REHEARSAL_COLLECTOR_PATH,
        RESEAL_PATH,
        TRIGGER_PATH,
        REMOTE_CI_EVIDENCE_PATH,
        REPORT_PATH,
        "scripts/trimem_benchmark_matrix.py",
        "scripts/trimem_benchmark_run.py",
        "scripts/trimem_multi_swe_contract.py",
        "scripts/trimem_verify_ready.py",
    }
)

ACTIVATION_BINDING_PATHS = {
    "approval_secret_producer_sha256": APPROVAL_SECRET_PATH,
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "benchmark_workflow_sha256": EXPECTED_WORKFLOW_PATH,
    "checkout_rehearsal_sha256": CHECKOUT_REHEARSAL_PATH,
    "d123_amendment_sha256": AMENDMENT_PATH,
    "d123_inventory_sha256": INVENTORY_PATH,
    "d123_remote_ci_evidence_sha256": REMOTE_CI_EVIDENCE_PATH,
    "d123_reseal_sha256": RESEAL_PATH,
    "d123_trigger_reader_sha256": TRIGGER_PATH,
    "grader_factory_rehearsal_sha256": GRADER_FACTORY_REHEARSAL_PATH,
    "loader_rehearsal_collector_sha256": LOADER_REHEARSAL_COLLECTOR_PATH,
    "multi_swe_contract_sha256": "scripts/trimem_multi_swe_contract.py",
    "official_grader_sha256": "scripts/trimem_official_grader.py",
    "readiness_requirements_sha256": (
        "artifacts/trimem_v1/readiness_requirements.json"
    ),
    "verify_ready_sha256": "scripts/trimem_verify_ready.py",
}

_PARENT_CONTEXT_LOCK = threading.RLock()
_D121_VALIDATE_WORKFLOW = d121._validate_workflow


def _context_bindings() -> dict[str, Any]:
    """Values propagated through every inherited active-reader adapter."""

    result: dict[str, Any] = {}
    for name in d121._context_bindings():
        if name not in globals():
            raise DevelopmentTriggerError(f"D1.23 context binding is absent: {name}")
        result[name] = globals()[name]
    return result


@contextmanager
def _d123_runtime_context() -> Iterator[None]:
    """Bind inherited runner helpers to one coherent D1.23 identity."""

    with (
        d120._D119_CONTEXT_LOCK,
        d121._D120_CONTEXT_LOCK,
        _PARENT_CONTEXT_LOCK,
    ):
        bindings = _context_bindings()
        previous = {name: getattr(d121, name) for name in bindings}
        try:
            for name, value in bindings.items():
                setattr(d121, name, value)
            with d121._d121_runtime_context():
                yield
        finally:
            for name, value in reversed(tuple(previous.items())):
                setattr(d121, name, value)


def _load_previous_request(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    previous = d122.validate_previous_request(repository)
    require(
        _is_ancestor(repository, PREVIOUS_EXECUTION_HEAD, source_head),
        "D1.23 source does not preserve immutable EXEC `_021`",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH) == raw,
        "historical `_021` request changed after execution",
    )
    require(
        not git(repository, "log", "--format=%H", source_head, "--", SENTINEL_PATH).strip(),
        "`_022` exists in activation-source history",
    )
    require(
        previous.get("actual_execution_authorized") is False
        and previous.get("external_execution_approval_received") is False,
        "spent `_021` sentinel authority boundary differs",
    )
    return previous


def _validate_previous_run_fixture(
    repository: Path, source_head: str
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    raw = commit_bytes(repository, source_head, PREVIOUS_FAILURE_FIXTURE_PATH)
    require(
        len(raw) == PREVIOUS_FAILURE_FIXTURE_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_FAILURE_FIXTURE_SHA256
        and raw == commit_bytes(
            repository, BASELINE_SOURCE_HEAD, PREVIOUS_FAILURE_FIXTURE_PATH
        ),
        "immutable EXEC `_021` failure fixture differs",
    )
    value = strict_json(raw)
    require(
        value.get("scientific_status") == d122.SCIENTIFIC_STATUS
        and value.get("performance_measured") is False
        and value.get("pass_at_1") is None
        and value.get("actuals") == HISTORICAL_EXECUTION_ACTUALS
        and value.get("workflow_run", {}).get("id") == PREVIOUS_RUN_ID
        and value.get("workflow_run", {}).get("attempt") == PREVIOUS_RUN_ATTEMPT,
        "EXEC `_021` partial-science evidence differs",
    )
    return value


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    repository = resolve_repository_root(repository)
    require(
        source_head != BASELINE_SOURCE_HEAD
        and _is_ancestor(repository, BASELINE_SOURCE_HEAD, source_head),
        "D1.23 source is not a strict descendant of the exact D1.22 baseline",
    )
    changes: dict[str, str] = {}
    lines = git(
        repository,
        "diff",
        "--no-ext-diff",
        "--name-status",
        "--no-renames",
        BASELINE_SOURCE_HEAD,
        source_head,
    ).splitlines()
    for line in lines:
        pieces = line.split("\t")
        require(len(pieces) == 2, "D1.23 diff contains a noncanonical change")
        status, path = pieces
        require(status in {"A", "M"}, f"D1.23 diff status is forbidden: {status}")
        require(path in ALLOWED_ACTIVATION_PATHS, f"D1.23 changed forbidden path: {path}")
        require(path not in changes, f"D1.23 changed a path twice: {path}")
        changes[path] = status
    for path, status in REQUIRED_ACTIVATION_CHANGES.items():
        require(
            changes.get(path) == status,
            f"required D1.23 activation change is missing or wrong: {path}",
        )
    return dict(sorted(changes.items()))


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, source_head, path)
            == commit_bytes(repository, BASELINE_SOURCE_HEAD, path),
            f"frozen scientific input changed during D1.23 activation: {path}",
        )


def _validate_workflow(repository: Path, source_head: str) -> None:
    _D121_VALIDATE_WORKFLOW(repository, source_head)
    current = commit_bytes(repository, source_head, EXPECTED_WORKFLOW_PATH)
    baseline = commit_bytes(repository, BASELINE_SOURCE_HEAD, EXPECTED_WORKFLOW_PATH)
    checkout_without_clean = (
        b"        uses: actions/checkout@"
        b"11bd71901bbe5b1630ceea73d27597364c9af683\n"
        b"        with:\n"
        b"          fetch-depth: 0\n"
        b"          persist-credentials: false\n"
        b"          ref: ${{ github.sha }}\n"
    )
    checkout_with_clean = (
        b"        uses: actions/checkout@"
        b"11bd71901bbe5b1630ceea73d27597364c9af683\n"
        b"        with:\n"
        b"          clean: true\n"
        b"          fetch-depth: 0\n"
        b"          persist-credentials: false\n"
        b"          ref: ${{ github.sha }}\n"
    )
    require(
        current.count(checkout_with_clean) == 3
        and current.count(b"clean: true") == 3
        and b"actions/download-artifact" not in current,
        "fresh EXEC-022 checkout isolation differs",
    )
    restored = current.replace(
        SENTINEL_PATH.encode(), PREVIOUS_SENTINEL_PATH.encode()
    ).replace(
        EXPECTED_CONCURRENCY_GROUP.encode(),
        b"trimem-v1-development-tuning-exec-021",
    ).replace(
        TRIGGER_PATH.encode(), b"scripts/trimem_development_trigger_d121.py"
    ).replace(
        checkout_with_clean,
        checkout_without_clean,
    )
    require(restored == baseline, "benchmark workflow changed beyond D1.23 routing")
    text = current.decode("utf-8", errors="strict")
    require(
        text.count(TRIGGER_PATH) == 8
        and "scripts/trimem_development_trigger_d121.py" not in text
        and "scripts/trimem_development_trigger_d122.py" not in text,
        "active benchmark reader is not exclusively D1.23",
    )


def _validate_active_reader_sources(repository: Path, source_head: str) -> None:
    """Prove runner/matrix edits are only the active-reader import swap."""

    old = b"from trimem_development_trigger_d121 import"
    new = b"from trimem_development_trigger_d123 import"
    for path in ("scripts/trimem_benchmark_run.py", "scripts/trimem_benchmark_matrix.py"):
        current = commit_bytes(repository, source_head, path)
        baseline = commit_bytes(repository, BASELINE_SOURCE_HEAD, path)
        require(current.count(new) == 1 and old not in current, f"D1.23 reader differs: {path}")
        require(
            current.replace(new, old) == baseline,
            f"D1.23 changed active reader source beyond import routing: {path}",
        )


def _validate_documents(repository: Path, source_head: str) -> None:
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    evidence_raw = commit_bytes(repository, source_head, REMOTE_CI_EVIDENCE_PATH)
    require(
        len(evidence_raw) == REMOTE_CI_EVIDENCE_BYTES
        and hashlib.sha256(evidence_raw).hexdigest() == REMOTE_CI_EVIDENCE_SHA256,
        "D1.22 remote-CI evidence identity differs",
    )
    evidence = strict_json(evidence_raw)
    require(
        evidence.get("status") == "PASS"
        and evidence.get("exact_head") == BASELINE_SOURCE_HEAD
        and evidence.get("benchmark_execution_runs") == 0
        and evidence.get("paid_model_calls") == 0,
        "D1.22 remote-CI evidence semantics differ",
    )
    require(
        amendment.get("schema") == AMENDMENT_SCHEMA
        and inventory.get("schema") == INVENTORY_SCHEMA
        and amendment.get("classification") == AMENDMENT_CLASSIFICATION
        and inventory.get("classification") == AMENDMENT_CLASSIFICATION
        and amendment.get("status") == AMENDMENT_STATUS
        and inventory.get("status") == AMENDMENT_STATUS
        and amendment.get("endpoint") == AMENDMENT_ENDPOINT
        and inventory.get("endpoint") == AMENDMENT_ENDPOINT,
        "D1.23 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_021_attempt_one_consumed") is True
        and authority.get("request_021_attempt_two_allowed") is False
        and authority.get("request_021_rerun_allowed") is False
        and authority.get("request_022_creation_authorized") is True
        and authority.get("request_022_created_in_source") is False
        and authority.get("request_022_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("required_external_authorization")
        == REQUIRED_EXTERNAL_AUTHORIZATION
        and authority.get("sentinel_contains_execution_authority") is False,
        "D1.23 authority boundary differs",
    )
    frozen = amendment.get("frozen_scientific_identity")
    require(
        amendment.get("d122_baseline_head") == BASELINE_SOURCE_HEAD
        and amendment.get("remote_ci_evidence_sha256") == REMOTE_CI_EVIDENCE_SHA256
        and amendment.get("consumed_execution_actuals")
        == HISTORICAL_EXECUTION_ACTUALS
        and amendment.get("scientific_execution_actuals")
        == SCIENTIFIC_EXECUTION_ACTUALS
        and amendment.get("canary_execution_actuals") == CANARY_EXECUTION_ACTUALS
        and amendment.get("current_execution_actuals")
        == ZERO_CURRENT_EXECUTION_ACTUALS
        and amendment.get("performance_measured") is False
        and amendment.get("pass_at_1") is None
        and isinstance(frozen, Mapping)
        and frozen.get("model_id") == MODEL_ID
        and frozen.get("reasoning_effort") == REASONING_EFFORT
        and frozen.get("targets") == 12
        and frozen.get("task_arm_runs") == 72
        and frozen.get("scientific_generation_call_cap") == 1_872
        and frozen.get("paid_model_call_cap") == 1_873
        and frozen.get("hard_cap_usd") == 50.0
        and inventory.get("source_changed_paths")
        == list(_validate_recovery_diff(repository, source_head)),
        "D1.23 historical, science, cap, or changed-path seal differs",
    )
    implementation = amendment.get("implementation_sha256")
    require(
        isinstance(implementation, Mapping)
        and implementation == inventory.get("implementation_sha256")
        and set(implementation) == IMPLEMENTATION_SEAL_PATHS,
        "D1.23 implementation inventory differs",
    )
    for path, digest in implementation.items():
        require(
            hashlib.sha256(commit_bytes(repository, source_head, path)).hexdigest()
            == digest,
            f"D1.23 implementation hash differs: {path}",
        )
    report = commit_bytes(repository, source_head, REPORT_PATH).decode(
        "utf-8", errors="strict"
    )
    for marker in (
        BASELINE_SOURCE_HEAD,
        AMENDMENT_ENDPOINT,
        "24 of 72",
        "paid model calls       = 0",
        "gpt-5.4-mini-2026-03-17",
    ):
        require(marker in report, f"D1.23 report marker is absent: {marker}")


def _validate_d122_baseline(repository: Path) -> dict[str, Any]:
    """Validate D1.22 at its commit without consulting the live `_022` path."""

    repository = resolve_repository_root(repository)
    require(
        git(repository, "cat-file", "-t", BASELINE_SOURCE_HEAD).strip() == "commit",
        "exact D1.22 baseline commit is unavailable",
    )
    require(
        not git(
            repository,
            "log",
            "--format=%H",
            BASELINE_SOURCE_HEAD,
            "--",
            SENTINEL_PATH,
        ).strip(),
        "exact D1.22 baseline unexpectedly contains `_022`",
    )
    d122.validate_previous_request(repository)
    d122.validate_failure_fixture(repository)
    changes = d122._validate_recovery_diff(repository, BASELINE_SOURCE_HEAD)
    d122._validate_preserved_science(repository, BASELINE_SOURCE_HEAD)
    d122._validate_documents(repository, BASELINE_SOURCE_HEAD)
    qdrant = d122.validate_qdrant_source_contract()
    return {
        "changed_paths": changes,
        "current_execution_actuals": deepcopy(ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": d122.AMENDMENT_ENDPOINT,
        "historical_execution_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "qdrant_nofile_contract": qdrant,
        "request_021_attempt_one_consumed": True,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": False,
        "request_022_execution_authorized": False,
        "source_head": BASELINE_SOURCE_HEAD,
        "status": "PASS",
    }


def validate_d122_baseline(repository: Path) -> dict[str, Any]:
    """Public, read-only validation of the exact D1.22 source boundary."""

    return _validate_d122_baseline(repository)


def validate_remote_ci_evidence(
    repository: Path, source_head: str | None = None
) -> dict[str, Any]:
    """Validate the committed or pending D1.22 exact-head PASS receipt."""

    repository = resolve_repository_root(repository)
    if source_head is None:
        path = repository.joinpath(*PurePosixPath(REMOTE_CI_EVIDENCE_PATH).parts)
        require(path.is_file() and not path.is_symlink(), "D1.22 CI receipt is absent")
        raw = path.read_bytes()
    else:
        raw = commit_bytes(repository, source_head, REMOTE_CI_EVIDENCE_PATH)
    require(
        len(raw) == REMOTE_CI_EVIDENCE_BYTES
        and hashlib.sha256(raw).hexdigest() == REMOTE_CI_EVIDENCE_SHA256,
        "D1.22 exact-head CI receipt identity differs",
    )
    value = strict_json(raw)
    workflows = value.get("required_workflows")
    topology = value.get("topology_rehearsal")
    require(
        value.get("schema") == "trimem/d122-exact-head-remote-ci-evidence/1.0"
        and value.get("status") == "PASS"
        and value.get("exact_head") == BASELINE_SOURCE_HEAD
        and value.get("benchmark_execution_runs") == 0
        and value.get("credential_access") is False
        and value.get("model_api_calls") == 0
        and value.get("paid_model_calls") == 0
        and isinstance(workflows, Mapping)
        and set(workflows) == D122_EVIDENCE_WORKFLOWS
        and all(
            isinstance(record, Mapping)
            and record.get("attempt") == 1
            and record.get("conclusion") == "success"
            and isinstance(record.get("run_id"), int)
            for record in workflows.values()
        )
        and isinstance(topology, Mapping)
        and topology.get("status") == "PASS"
        and topology.get("hostconfig_nofile") == {"hard": 65_535, "soft": 65_535}
        and topology.get("pid1_nofile") == {"hard": 65_535, "soft": 65_535}
        and topology.get("namespaces") == 6
        and topology.get("collections") == 12
        and topology.get("payload_indexes") == 72
        and topology.get("cleanup_absent") is True
        and topology.get("model_calls") == 0
        and topology.get("grader_containers") == 0,
        "D1.22 exact-head CI receipt semantics differ",
    )
    return value


def validate_no_exec_022(
    repository: Path,
    source_head: str | None = None,
    *,
    require_worktree_absent: bool = True,
) -> None:
    """Fail closed if `_022` exists in source history or an active worktree."""

    repository = resolve_repository_root(repository)
    selected = source_head or git(repository, "rev-parse", "HEAD").strip()
    require(
        not git(
            repository, "log", "--format=%H", selected, "--", SENTINEL_PATH
        ).strip(),
        "unauthorized `_022` exists in source history",
    )
    if require_worktree_absent:
        target = repository.joinpath(*PurePosixPath(SENTINEL_PATH).parts)
        require(
            not os.path.lexists(target),
            "unauthorized working-tree `_022` exists",
        )


def _validate_source_impl(repository: Path, source_head: str) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    require(
        git(repository, "cat-file", "-t", source_head).strip() == "commit",
        "D1.23 source HEAD is unavailable",
    )
    baseline = _validate_d122_baseline(repository)
    require(
        baseline.get("status") == "PASS"
        and baseline.get("request_022_creation_authorized") is False,
        "exact D1.22 baseline validation failed",
    )
    changes = _validate_recovery_diff(repository, source_head)
    previous = _load_previous_request(repository, source_head)
    fixture = _validate_previous_run_fixture(repository, source_head)
    _validate_preserved_science(repository, source_head)
    _validate_workflow(repository, source_head)
    _validate_active_reader_sources(repository, source_head)
    with d114._d114_runtime_context(), d113._d113_runtime_context():
        d112._validate_remote_gate_workflow_contracts(repository, source_head)
        d112._validate_remote_gate_workflow_refs(repository, source_head)
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
        "scientific identity changed after spent EXEC `_021`",
    )
    bindings = d114._validate_freeze_and_bindings(repository, source_head, previous)
    return {
        "activation_changes": changes,
        "bindings": bindings,
        "d122_baseline": baseline,
        "failure_fixture": fixture,
        "hard_cap": hard_cap,
        "previous_request": previous,
        "source_head": source_head,
        "target_order": target_order,
    }


def _request_execution_contracts(bindings: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(d121._request_execution_contracts(bindings)))
    result["d122_qdrant_nofile"] = d122.validate_qdrant_source_contract()
    result["fresh_exec_022"] = deepcopy(FRESH_EXECUTION_CONTRACT)
    result["contract_bindings"] = {
        **dict(result.get("contract_bindings", {})),
        "benchmark_matrix_sha256": bindings["benchmark_matrix_sha256"],
        "benchmark_runner_sha256": bindings["benchmark_runner_sha256"],
        "benchmark_workflow_sha256": bindings["benchmark_workflow_sha256"],
        "d123_trigger_reader_sha256": bindings["d123_trigger_reader_sha256"],
        "d123_remote_ci_evidence_sha256": bindings[
            "d123_remote_ci_evidence_sha256"
        ],
    }
    return result


def validate_checkout_rehearsal(value: Any) -> dict[str, Any]:
    with _d123_runtime_context():
        return d121.validate_checkout_rehearsal(value)


def collect_exact_checkout_rehearsal(
    repository: Path, source_head: str
) -> dict[str, Any]:
    with _d123_runtime_context():
        return d121.collect_exact_checkout_rehearsal(repository, source_head)


def validate_loader_rehearsal_record(
    value: Any,
    *,
    source_head: str,
    runner_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    with _d123_runtime_context():
        return d121.validate_loader_rehearsal_record(
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
    pre_execution_actuals = {
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
    }
    payload = {
        "actual_execution_authorized": False,
        "activation_actuals": dict(ACTIVATION_ZERO_COUNTERS),
        "amendment_classification": AMENDMENT_CLASSIFICATION,
        "authorization_semantics": (
            "This sentinel creates one push run only. Protected execution "
            "requires one distinct approval bound to the sentinel commit, "
            "activation source, freeze, request bytes, workflow run ID/attempt, "
            "caps, actor, timestamp, nonce, legal acceptance, and exact "
            "OpenAI-key commitment."
        ),
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "checkout_rehearsal": checkout,
        "checkout_rehearsal_sha256": "sha256:"
        + hashlib.sha256(canonical_bytes(checkout)).hexdigest(),
        "control_plane": deepcopy(dict(previous["control_plane"])),
        "d123_execution_contracts": _request_execution_contracts(bindings),
        "exact_model": deepcopy(dict(previous["exact_model"])),
        "external_execution_approval_received": False,
        "hard_caps": validated["hard_cap"],
        "loader_rehearsal": rehearsal,
        "phase": EXPECTED_PHASE,
        "pre_execution_actuals": pre_execution_actuals,
        "prohibited_actions": [
            "DEVELOPMENT_TUNING_EXEC_REQUEST_021_rerun_or_attempt_2",
            "EXEC_021_partial_cell_reuse_or_cross_run_resume",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_023",
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
            "failure_fixture_sha256": "sha256:"
            + PREVIOUS_FAILURE_FIXTURE_SHA256,
            "failure_label": PREVIOUS_FAILURE_SUBTYPE,
            "historical_partial_cells_reused": 0,
            "new_campaign_starts_at_sequence_zero": True,
            "official_scientific_outcome": "NO_CAMPAIGN_RESULT_PARTIAL_24_OF_72",
            "performance_measured": False,
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_payload_sha256": "sha256:"
            + PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "previous_request_raw_sha256": "sha256:"
            + PREVIOUS_SENTINEL_SHA256,
            "previous_source_head": PREVIOUS_SOURCE_HEAD,
            "public_result_available": False,
            "qdrant_nofile_contract": d122.validate_qdrant_source_contract(),
            "remote_custody_status": "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS",
            "request_021_rerun_allowed": False,
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
        "`_022` checkout rehearsal hash differs",
    )
    expected = _build_request_impl(
        repository,
        source_head=source_head,
        remote_gate_evidence=gates,
        runner_readiness=readiness,
        loader_rehearsal=rehearsal,
        checkout_rehearsal=checkout,
    )
    require(value == expected, "`_022` request content differs")
    require(
        raw == canonical_bytes(expected, trailing_lf=True),
        "`_022` request bytes are not canonical UTF-8 plus one LF",
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
        "trigger commit is not the exclusive `_022` sentinel addition",
    )
    mode, _oid = _tree_entry(repository, after, SENTINEL_PATH)
    require(mode == "100644", "`_022` sentinel is not a regular file")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "`_022` already exists before the trigger commit",
    )
    return _validate_request_impl(
        repository,
        commit_bytes(repository, after, SENTINEL_PATH),
        source_head=parent,
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
    validate_no_exec_022(
        repository,
        selected,
        require_worktree_absent=require_checked_out_head,
    )
    with _d123_runtime_context():
        return _validate_source_impl(repository, selected)


validate_activation_source = validate_correction_source


def build_request(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
    runner_readiness: Mapping[str, Any],
    loader_rehearsal: Mapping[str, Any],
    checkout_rehearsal: Mapping[str, Any],
) -> dict[str, Any]:
    validate_no_exec_022(repository, source_head, require_worktree_absent=True)
    with _d123_runtime_context():
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
    with _d123_runtime_context():
        return _validate_request_impl(repository, raw, source_head=source_head)


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    with _d123_runtime_context():
        return _validate_sentinel_commit_impl(
            repository,
            after,
            expected_parent=expected_parent,
            require_checked_out_head=require_checked_out_head,
        )


def _delegate(name: str, *args: Any, **kwargs: Any) -> Any:
    with _d123_runtime_context():
        return getattr(d121, name)(*args, **kwargs)


def validate_branch_trigger(
    repository: Path, event_path: Path, **kwargs: Any
) -> dict[str, Any]:
    return _delegate("validate_branch_trigger", repository, event_path, **kwargs)


def write_request(repository: Path) -> dict[str, Any]:
    """Create `_022` only after fresh exact-head gates and rehearsals."""

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
    return deepcopy(d122.current_failure_record())


def current_activation_record(*, request_created: bool = False) -> dict[str, Any]:
    return {
        "actual_execution_authorized": False,
        "classification": AMENDMENT_CLASSIFICATION,
        "consumed_exec_021_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "current_execution_actuals": deepcopy(ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": AMENDMENT_ENDPOINT,
        "external_execution_approval_received": False,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "request_present_in_activation_source": False,
        "request_022_creation_authorized": True,
        "request_022_created": request_created,
        "request_022_created_in_source": False,
        "request_022_execution_authorized": False,
        "schema": "trimem/development-exec-022-activation/1.0",
        "status": AMENDMENT_STATUS,
    }


def current_recovery_record() -> dict[str, Any]:
    return current_activation_record(request_created=False)


def validate_optional_exec_022_boundary(repository: Path) -> str | None:
    """Accept only the D1.23 source or its exact sentinel-only child."""

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
        require(not os.path.lexists(target), "uncommitted `_022` request exists")
        return None
    require(len(additions) == 1, "`_022` was added more than once")
    execution_head = additions[0]
    require(execution_head == head, "commits exist after the active `_022` request")
    parents = git(repository, "rev-list", "--parents", "-n", "1", execution_head).split()
    require(len(parents) == 2, "`_022` parent differs")
    validate_sentinel_commit(
        repository,
        execution_head,
        expected_parent=parents[1],
        require_checked_out_head=True,
    )
    return execution_head


def validate_current_activation(repository: Path) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    execution_head = validate_optional_exec_022_boundary(repository)
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
    activation = current_activation_record(request_created=execution_head is not None)
    return {
        **result,
        **activation,
        "request_021_attempt_one_consumed": True,
        "request_021_rerun_allowed": False,
    }


validate_current_recovery = validate_current_activation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or create the fail-closed D1.23 DEV `_022` request"
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
        result = validate_current_activation(args.repository)
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
