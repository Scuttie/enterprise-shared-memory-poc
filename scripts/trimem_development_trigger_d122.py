"""Fail-closed, credential-free D1.22 recovery gate for spent EXEC ``_021``.

EXEC 021 produced 24 terminal cells before the shared Qdrant service hit a
platform-dependent ``RLIMIT_NOFILE`` failure.  This module preserves that
partial run as immutable, non-aggregatable history and validates only the
credential-free infrastructure correction.  It intentionally has no request
writer and grants no ``_022`` request-creation or execution authority.

Importing this module has no network, Docker, grader, credential, image,
model, GitHub, or filesystem-mutation side effect.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d121 as d121


EXPECTED_REPOSITORY = d121.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d121.EXPECTED_BRANCH
EXPECTED_REF = d121.EXPECTED_REF

PREVIOUS_SOURCE_HEAD = "a171bce0b883d4cc93b893a6d47944a84a947897"
PREVIOUS_EXECUTION_HEAD = "f83eab1e777f803c08e1ed86baac17c97111c546"
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_021.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "986cfe25514a8bf5594a8047f0bc11edd0419813739dbec02da702ab5da71e75"
)
PREVIOUS_SENTINEL_BYTES = 51_376
PREVIOUS_SENTINEL_BLOB_OID = "994bd4058c45a9988d55c5cabc92b823474ddcf9"
PREVIOUS_REQUEST_PAYLOAD_SHA256 = (
    "1c8104c4f535b1f2a0e0e32d452663301c8d6903bf62828be5be4decc9bfc1e9"
)
PREVIOUS_SOURCE_FREEZE_SHA256 = (
    "ac0d781deb1d01c4b34d5fd61b0e07f3527b42c2bddcb8f0f4a2575e75dc1cae"
)
PREVIOUS_RUN_ID = 34_257_490_991
PREVIOUS_RUN_ATTEMPT = 1

FUTURE_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_022"
FUTURE_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_022.json"
)
FUTURE_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_022_APPROVED_ONCE"
)

FAILURE_SUBTYPE = "QDRANT_RLIMIT_NOFILE_PORTABILITY_FAILURE"
FAILURE_CLASSIFICATION = "GLOBAL_MEMORY_BACKEND_INFRASTRUCTURE_FAILURE"
AMENDMENT_CLASSIFICATION = (
    "POST_EXEC_021_PARTIAL_SCIENTIFIC_QDRANT_RLIMIT_NOFILE_PORTABILITY_RECOVERY"
)
AMENDMENT_STATUS = (
    "FROZEN_CREDENTIAL_FREE_EXEC_021_PARTIAL_SCIENTIFIC_FAILURE_"
    "RECOVERY_PENDING_REHEARSAL"
)
AMENDMENT_ENDPOINT = FAILURE_SUBTYPE
SCIENTIFIC_STATUS = "PARTIAL_TWENTY_FOUR_OF_SEVENTY_TWO_NO_CAMPAIGN_SCORE"

AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_022_recovery_amendment.json"
)
AMENDMENT_SCHEMA = "trimem/development-exec-022-qdrant-nofile-amendment/1.0"
INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_022_recovery_inventory.json"
)
INVENTORY_SCHEMA = "trimem/development-exec-022-qdrant-nofile-inventory/1.0"
REPORT_PATH = "reports/TRIMEM_D122_EXEC_022_RECOVERY.md"
TRIGGER_PATH = "scripts/trimem_development_trigger_d122.py"
RESEAL_PATH = "scripts/trimem_d122_reseal.py"
QDRANT_REHEARSAL_PATH = "scripts/trimem_d122_qdrant_nofile_rehearsal.py"
QDRANT_REHEARSAL_TEST_PATH = (
    "tests/unit/test_trimem_d122_qdrant_nofile_rehearsal.py"
)
FAILURE_FIXTURE_PATH = (
    "tests/fixtures/trimem_d122/exec_021_qdrant_nofile_portability_failure.json"
)
FAILURE_FIXTURE_BYTES = 9_241
FAILURE_FIXTURE_SHA256 = (
    "2edd893c3e996a8111565798781a63cdb92775e36febf3564df2fa358156ad7f"
)

QDRANT_NOFILE_SOFT = 65_535
QDRANT_NOFILE_HARD = 65_535

MODEL_ID = d121.MODEL_ID
REASONING_EFFORT = d121.REASONING_EFFORT
EXPECTED_STREAM_ORDER = d121.EXPECTED_STREAM_ORDER
EXPECTED_TARGET_ORDER = d121.EXPECTED_TARGET_ORDER
EXPECTED_DEVELOPMENT_HARD_CAP = d121.EXPECTED_DEVELOPMENT_HARD_CAP
PRESERVED_SCIENTIFIC_PATHS = d121.PRESERVED_SCIENTIFIC_PATHS
FREEZE_PATH = d121.FREEZE_PATH


SCIENTIFIC_EXECUTION_ACTUALS: dict[str, int | str] = {
    "cached_input_tokens": 31_616,
    "decomposition_calls": 24,
    "extraction_calls": 24,
    "input_tokens": 1_533_517,
    "model_generation_calls": 247,
    "output_tokens": 92_850,
    "paid_model_calls": 247,
    "reasoning_tokens": 65_956,
    "solve_calls": 199,
    "total_tokens": 1_626_367,
    "total_usd": "1.546621950000",
}

CANARY_EXECUTION_ACTUALS: dict[str, int | str] = {
    "cached_input_tokens": 0,
    "input_tokens": 950,
    "model_generation_calls": 1,
    "output_tokens": 187,
    "paid_model_calls": 1,
    "reasoning_tokens": 157,
    "total_tokens": 1_137,
    "total_usd": "0.001554000000",
}

HISTORICAL_EXECUTION_ACTUALS: dict[str, int | str] = {
    "benchmark_image_pulls": 13,
    "cached_input_tokens": 31_616,
    "completed_task_arm_runs": 24,
    "decomposition_calls": 24,
    "exact_model_metadata_requests": 1,
    "extraction_calls": 24,
    "grader_attempts": 24,
    "grader_containers": 24,
    "input_tokens": 1_534_467,
    "model_generation_calls": 248,
    "official_grader_runs": 24,
    "output_tokens": 93_037,
    "paid_model_calls": 248,
    "protocol_canary_generation_calls": 1,
    "provider_control_plane_requests": 1,
    "reasoning_tokens": 66_113,
    "resolved_cells": 2,
    "scientific_model_calls": 247,
    "solve_calls": 199,
    "task_arm_reservations": 24,
    "task_arm_runs": 24,
    "terminal_cells": 24,
    "total_tokens": 1_627_504,
    "total_usd": "1.548175950000",
    "unresolved_cells": 22,
}

ZERO_CURRENT_EXECUTION_ACTUALS: dict[str, int | float] = {
    "benchmark_image_pulls": 0,
    "cached_input_tokens": 0,
    "decomposition_calls": 0,
    "extraction_calls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "model_generation_calls": 0,
    "model_metadata_requests": 0,
    "official_grader_runs": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "reasoning_tokens": 0,
    "solve_calls": 0,
    "task_arm_runs": 0,
    "terminal_cells": 0,
    "total_usd": 0.0,
}

OUTSTANDING_RESERVATIONS: dict[str, int | float] = {
    "decomposition_calls": 0,
    "extraction_calls": 0,
    "grader_containers": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "paid_model_calls": 0,
    "solve_calls": 0,
    "task_arm_runs": 0,
    "total_usd": 0.0,
}

QDRANT_NOFILE_CONTRACT: dict[str, Any] = {
    "applies_only_to": "qdrant",
    "docker_create_argument": "nofile=65535:65535",
    "docker_inspect_exact_match_required": True,
    "hard": QDRANT_NOFILE_HARD,
    "pid1_proc_limits_exact_match_required": True,
    "soft": QDRANT_NOFILE_SOFT,
    "state_bound_cleanup_rejects_drift_before_mutation": True,
    "state_free_cleanup_rejects_drift_before_mutation": True,
}

RECOVERY_BOUNDARY: dict[str, bool | int | str] = {
    "cross_run_resume_allowed": False,
    "historical_partial_results_reusable_for_new_campaign": False,
    "maximum_internal_resume_attempts": 1,
    "new_campaign_starts_at_sequence_zero": True,
    "partial_candidate_checkpoint_selection_allowed": False,
    "request_021_attempt_one_consumed": True,
    "request_021_attempt_two_allowed": False,
    "request_021_rerun_allowed": False,
    "request_022_creation_authorized": False,
    "request_022_execution_authorized": False,
    "resume_eligible": False,
    "resume_reason": "FIRST_DISPOSITION_NOT_RESUME_SAFE",
    "resume_started": False,
}

# D1.22 deliberately excludes the benchmark workflow, matrix, runner, model,
# provider, prompt, target, arm, and budget files.  No paid dispatch route is
# changed by this recovery package.
ALLOWED_RECOVERY_PATHS = frozenset(
    {
        ".github/workflows/ci-trimem.yml",
        ".github/workflows/ci-trimem-dev-toolchain.yml",
        AMENDMENT_PATH,
        INVENTORY_PATH,
        FAILURE_FIXTURE_PATH,
        REPORT_PATH,
        RESEAL_PATH,
        TRIGGER_PATH,
        QDRANT_REHEARSAL_PATH,
        QDRANT_REHEARSAL_TEST_PATH,
        "artifacts/trimem_v1/freeze.json",
        "artifacts/trimem_v1/readiness_requirements.json",
        "scripts/trimem_development_trigger_d112.py",
        "scripts/trimem_d113_reseal.py",
        "scripts/trimem_d114_reseal.py",
        "scripts/trimem_freeze.py",
        "scripts/trimem_verify_ready.py",
        "tests/unit/test_trimem_benchmark_readiness.py",
        "tests/unit/test_trimem_d110_status_and_reseal.py",
        "tests/unit/test_trimem_d112_e1_trigger.py",
        "tests/unit/test_trimem_d120_trigger.py",
        "tests/unit/test_trimem_d121_trigger.py",
        "tests/unit/test_trimem_d122_trigger.py",
        "tests/unit/test_trimem_dev_toolchain_workflows.py",
        "tests/unit/test_trimem_development_trigger.py",
        "tests/unit/test_trimem_d16_native_action.py",
    }
)

REQUIRED_RECOVERY_CHANGES: dict[str, str] = {
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    AMENDMENT_PATH: "A",
    INVENTORY_PATH: "A",
    FAILURE_FIXTURE_PATH: "A",
    REPORT_PATH: "A",
    RESEAL_PATH: "A",
    TRIGGER_PATH: "A",
    QDRANT_REHEARSAL_PATH: "A",
    QDRANT_REHEARSAL_TEST_PATH: "A",
    "artifacts/trimem_v1/freeze.json": "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    "scripts/trimem_development_trigger_d112.py": "M",
    "scripts/trimem_d113_reseal.py": "M",
    "scripts/trimem_d114_reseal.py": "M",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d112_e1_trigger.py": "M",
    "tests/unit/test_trimem_d120_trigger.py": "M",
    "tests/unit/test_trimem_d121_trigger.py": "M",
    "tests/unit/test_trimem_d122_trigger.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
}

IMPLEMENTATION_SEAL_PATHS = frozenset(
    {
        QDRANT_REHEARSAL_PATH,
        RESEAL_PATH,
        TRIGGER_PATH,
        "scripts/trimem_development_trigger_d112.py",
        "scripts/trimem_d113_reseal.py",
        "scripts/trimem_d114_reseal.py",
    }
)


class D122RecoveryError(ValueError):
    """The immutable history, correction, or no-authority boundary differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D122RecoveryError(message)


def canonical_bytes(value: Any, *, trailing_lf: bool = False) -> bytes:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return raw + (b"\n" if trailing_lf else b"")


def strict_json(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    require(
        not raw.startswith(b"\xef\xbb\xbf")
        and b"\x00" not in raw
        and b"\r" not in raw,
        "JSON encoding is not canonical UTF-8/LF",
    )
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                D122RecoveryError(f"invalid JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D122RecoveryError(f"invalid JSON: {exc}") from exc
    require(isinstance(value, dict), "JSON document is not an object")
    return value


def resolve_repository_root(repository: Path) -> Path:
    return Path(d121.resolve_repository_root(repository))


def git(repository: Path, *args: str) -> str:
    return d121.git(repository, *args)


def commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    return d121.commit_bytes(repository, commit, path)


def _tree_entry(repository: Path, commit: str, path: str) -> tuple[str, str]:
    return d121._tree_entry(repository, commit, path)


def validate_previous_request(repository: Path) -> dict[str, Any]:
    """Validate the exact, spent sentinel commit without interpreting authority."""

    repository = resolve_repository_root(repository)
    require(
        git(repository, "cat-file", "-t", PREVIOUS_EXECUTION_HEAD).strip()
        == "commit",
        "immutable _021 execution commit is unavailable",
    )
    parents = git(
        repository, "rev-list", "--parents", "-n", "1", PREVIOUS_EXECUTION_HEAD
    ).split()
    require(
        parents == [PREVIOUS_EXECUTION_HEAD, PREVIOUS_SOURCE_HEAD],
        "immutable _021 execution parent differs",
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
        "immutable _021 execution is not the exclusive sentinel addition",
    )
    mode, oid = _tree_entry(
        repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH
    )
    require(
        mode == "100644" and oid == PREVIOUS_SENTINEL_BLOB_OID,
        "immutable _021 sentinel Git blob identity differs",
    )
    raw = commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, PREVIOUS_SENTINEL_PATH)
    require(
        len(raw) == PREVIOUS_SENTINEL_BYTES
        and hashlib.sha256(raw).hexdigest() == PREVIOUS_SENTINEL_SHA256
        and raw.endswith(b"\n")
        and not raw.endswith(b"\n\n"),
        "immutable _021 sentinel raw identity differs",
    )
    value = strict_json(raw)
    bindings = value.get("bindings")
    require(
        value.get("schema") == "trimem/development-tuning-branch-trigger/1.21"
        and value.get("request_id") == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021"
        and value.get("request_path") == PREVIOUS_SENTINEL_PATH
        and value.get("source_head") == PREVIOUS_SOURCE_HEAD
        and value.get("request_sha256")
        == "sha256:" + PREVIOUS_REQUEST_PAYLOAD_SHA256
        and isinstance(bindings, Mapping)
        and bindings.get("freeze_sha256")
        == "sha256:" + PREVIOUS_SOURCE_FREEZE_SHA256,
        "immutable _021 request content identity differs",
    )
    return value


def validate_failure_fixture(repository: Path) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    path = repository.joinpath(*PurePosixPath(FAILURE_FIXTURE_PATH).parts)
    raw = path.read_bytes()
    value = strict_json(raw)
    require(
        len(raw) == FAILURE_FIXTURE_BYTES
        and hashlib.sha256(raw).hexdigest() == FAILURE_FIXTURE_SHA256
        and raw
        == json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode(
            "utf-8"
        )
        + b"\n",
        "EXEC _021 failure fixture identity differs",
    )
    require(
        value.get("schema")
        == "trimem/development-exec-021-qdrant-nofile-portability-failure/1.0"
        and value.get("endpoint") == FAILURE_SUBTYPE
        and value.get("scientific_status") == SCIENTIFIC_STATUS
        and value.get("actuals") == HISTORICAL_EXECUTION_ACTUALS
        and value.get("scientific_actuals") == SCIENTIFIC_EXECUTION_ACTUALS
        and value.get("canary_actuals") == CANARY_EXECUTION_ACTUALS
        and value.get("outstanding_reservations") == OUTSTANDING_RESERVATIONS
        and value.get("recovery_boundary") == RECOVERY_BOUNDARY
        and value.get("pass_at_1") is None
        and value.get("performance_measured") is False,
        "EXEC _021 fixture accounting or no-score boundary differs",
    )
    streams = value.get("frozen_partial_outcome", {}).get("streams", {})
    require(
        streams.get("M2-baseline", {}).get("terminal_cells") == 12
        and streams.get("M2-precision", {}).get("terminal_cells") == 12
        and streams.get("M2-recall", {}).get("terminal_cells") == 0
        and streams.get("M2-recall", {}).get("task_arm_reservations") == 0
        and value.get("frozen_partial_outcome", {}).get("aggregate_available")
        is False
        and value.get("frozen_partial_outcome", {}).get(
            "candidate_selection_available"
        )
        is False,
        "EXEC _021 partial stream boundary differs",
    )
    return value


def validate_qdrant_source_contract() -> dict[str, Any]:
    d112 = d121.d112
    require(
        d112.QDRANT_NOFILE_SOFT == QDRANT_NOFILE_SOFT
        and d112.QDRANT_NOFILE_HARD == QDRANT_NOFILE_HARD,
        "Qdrant nofile constants differ",
    )
    exact = {
        "HostConfig": {
            "Ulimits": [
                {
                    "Hard": QDRANT_NOFILE_HARD,
                    "Name": "nofile",
                    "Soft": QDRANT_NOFILE_SOFT,
                }
            ]
        }
    }
    d112._require_exact_service_ulimits(exact, role="qdrant")
    for mutation in (
        None,
        [],
        [{"Hard": QDRANT_NOFILE_HARD, "Name": "nofile", "Soft": 1024}],
    ):
        try:
            d112._require_exact_service_ulimits(
                {"HostConfig": {"Ulimits": mutation}}, role="qdrant"
            )
        except d112.DevelopmentTriggerError:
            continue
        raise D122RecoveryError("Qdrant inspect drift did not fail closed")
    return deepcopy(QDRANT_NOFILE_CONTRACT)


def validate_no_exec_022(repository: Path, source_head: str | None = None) -> None:
    repository = resolve_repository_root(repository)
    selected = source_head or git(repository, "rev-parse", "HEAD").strip()
    additions = git(
        repository,
        "log",
        "--format=%H",
        "--diff-filter=A",
        selected,
        "--",
        FUTURE_SENTINEL_PATH,
    ).splitlines()
    target = repository.joinpath(*PurePosixPath(FUTURE_SENTINEL_PATH).parts)
    require(not additions, "unauthorized `_022` exists in source history")
    require(not target.exists(), "unauthorized working-tree `_022` exists")


def _validate_recovery_diff(repository: Path, source_head: str) -> dict[str, str]:
    lines = git(
        repository,
        "diff",
        "--name-status",
        "--no-renames",
        PREVIOUS_EXECUTION_HEAD,
        source_head,
    ).splitlines()
    observed: dict[str, str] = {}
    for line in lines:
        fields = line.split("\t")
        require(len(fields) == 2, "D1.22 recovery diff contains a rename/copy")
        status, path = fields
        require(status in {"A", "M"}, f"D1.22 path has forbidden status: {path}")
        require(path not in observed, f"duplicate D1.22 changed path: {path}")
        observed[path] = status
    require(
        set(observed) <= ALLOWED_RECOVERY_PATHS,
        "D1.22 recovery changed a path outside the infrastructure/governance allowlist",
    )
    for path, status in REQUIRED_RECOVERY_CHANGES.items():
        require(
            observed.get(path) == status,
            f"required D1.22 change is missing or has wrong status: {path}",
        )
    return observed


def _validate_preserved_science(repository: Path, source_head: str) -> None:
    for path in PRESERVED_SCIENTIFIC_PATHS:
        require(
            commit_bytes(repository, PREVIOUS_EXECUTION_HEAD, path)
            == commit_bytes(repository, source_head, path),
            f"frozen scientific input changed during D1.22 recovery: {path}",
        )


def _validate_documents(repository: Path, source_head: str) -> None:
    amendment = strict_json(commit_bytes(repository, source_head, AMENDMENT_PATH))
    inventory = strict_json(commit_bytes(repository, source_head, INVENTORY_PATH))
    require(
        amendment.get("schema") == AMENDMENT_SCHEMA
        and inventory.get("schema") == INVENTORY_SCHEMA
        and amendment.get("classification") == AMENDMENT_CLASSIFICATION
        and inventory.get("classification") == AMENDMENT_CLASSIFICATION
        and amendment.get("status") == AMENDMENT_STATUS
        and inventory.get("status") == AMENDMENT_STATUS
        and amendment.get("endpoint") == AMENDMENT_ENDPOINT
        and inventory.get("endpoint") == AMENDMENT_ENDPOINT,
        "D1.22 amendment/inventory identity differs",
    )
    authority = amendment.get("authority_boundary")
    require(
        isinstance(authority, Mapping)
        and authority.get("request_021_attempt_one_consumed") is True
        and authority.get("request_021_attempt_two_allowed") is False
        and authority.get("request_021_rerun_allowed") is False
        and authority.get("request_022_creation_authorized") is False
        and authority.get("request_022_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("development_execution_authorized") is False,
        "D1.22 authority boundary differs",
    )
    require(
        amendment.get("consumed_execution_actuals")
        == HISTORICAL_EXECUTION_ACTUALS
        and amendment.get("scientific_execution_actuals")
        == SCIENTIFIC_EXECUTION_ACTUALS
        and amendment.get("canary_execution_actuals")
        == CANARY_EXECUTION_ACTUALS
        and amendment.get("current_execution_actuals")
        == ZERO_CURRENT_EXECUTION_ACTUALS
        and amendment.get("qdrant_nofile_contract") == QDRANT_NOFILE_CONTRACT,
        "D1.22 accounting or Qdrant contract differs",
    )
    implementation = amendment.get("implementation_sha256")
    require(
        isinstance(implementation, Mapping)
        and implementation == inventory.get("implementation_sha256")
        and set(implementation) == IMPLEMENTATION_SEAL_PATHS,
        "D1.22 implementation seal differs",
    )
    for path, expected in implementation.items():
        require(
            expected == hashlib.sha256(commit_bytes(repository, source_head, path)).hexdigest(),
            f"D1.22 implementation hash differs: {path}",
        )


def validate_recovery_source(
    repository: Path,
    source_head: str | None = None,
    *,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    repository = resolve_repository_root(repository)
    checked_out = git(repository, "rev-parse", "HEAD").strip()
    selected = checked_out if source_head is None else source_head
    if require_checked_out_head:
        require(selected == checked_out, "source HEAD differs from checked-out HEAD")
    require(
        git(repository, "cat-file", "-t", selected).strip() == "commit",
        "D1.22 source HEAD is not a commit",
    )
    require(
        git(repository, "merge-base", "--is-ancestor", PREVIOUS_EXECUTION_HEAD, selected)
        == "",
        "spent EXEC _021 is not an ancestor of D1.22 source",
    )
    validate_previous_request(repository)
    validate_failure_fixture(repository)
    validate_no_exec_022(repository, selected)
    changes = _validate_recovery_diff(repository, selected)
    _validate_preserved_science(repository, selected)
    _validate_documents(repository, selected)
    qdrant = validate_qdrant_source_contract()
    return {
        "changed_paths": changes,
        "current_execution_actuals": dict(ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": AMENDMENT_ENDPOINT,
        "historical_execution_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "qdrant_nofile_contract": qdrant,
        "request_021_attempt_one_consumed": True,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": False,
        "request_022_execution_authorized": False,
        "source_head": selected,
        "status": "PASS",
    }


def current_failure_record() -> dict[str, Any]:
    return {
        "classification": FAILURE_CLASSIFICATION,
        "endpoint": FAILURE_SUBTYPE,
        "observed_execution_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "first": "UNKNOWN_FAILURE",
            "first_exit_code": 1,
            "maximum_internal_resume_attempts": 1,
            "resume_eligible": False,
            "resume_reason": "FIRST_DISPOSITION_NOT_RESUME_SAFE",
            "resume_started": False,
        },
        "request": {
            "execution_head": PREVIOUS_EXECUTION_HEAD,
            "id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_021",
            "path": PREVIOUS_SENTINEL_PATH,
            "payload_sha256": PREVIOUS_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": PREVIOUS_SENTINEL_SHA256,
            "source_head": PREVIOUS_SOURCE_HEAD,
        },
        "scientific_status": SCIENTIFIC_STATUS,
        "status": "IMMUTABLE_PUBLIC_AND_RESTRICTED_RUN_EVIDENCE_VERIFIED",
        "workflow_run": {
            "attempt": PREVIOUS_RUN_ATTEMPT,
            "conclusion": "failure",
            "id": PREVIOUS_RUN_ID,
        },
    }


def current_recovery_record() -> dict[str, Any]:
    return {
        "actual_execution_authorized": False,
        "classification": AMENDMENT_CLASSIFICATION,
        "consumed_exec_021_actuals": deepcopy(HISTORICAL_EXECUTION_ACTUALS),
        "current_execution_actuals": dict(ZERO_CURRENT_EXECUTION_ACTUALS),
        "endpoint": AMENDMENT_ENDPOINT,
        "external_execution_approval_received": False,
        "performance_measured": False,
        "qdrant_rehearsal_required": True,
        "request_021_rerun_allowed": False,
        "request_022_creation_authorized": False,
        "request_022_execution_authorized": False,
        "schema": "trimem/development-exec-022-recovery/1.0",
        "status": AMENDMENT_STATUS,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the no-authority D1.22 credential-free recovery source"
    )
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--source-head")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--validate-current", action="store_true")
    group.add_argument("--current-failure", action="store_true")
    group.add_argument("--current-recovery", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.current_failure:
            result = current_failure_record()
        elif args.current_recovery:
            result = current_recovery_record()
        else:
            result = validate_recovery_source(
                args.repository,
                args.source_head,
                require_checked_out_head=True,
            )
    except (D122RecoveryError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
