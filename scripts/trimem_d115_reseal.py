"""Build and verify the credential-free D1.15 ``_015`` recovery seal.

The seal preserves immutable D1.14 source/request history and the zero-model
EXEC ``_014`` loader failure.  It grants request-creation authority only; it
never executes a model, grader, image, container, or benchmark task.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT_DIRECTORY = str(Path(__file__).resolve().parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

import trimem_development_trigger_d115 as d115


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = ROOT / d115.AMENDMENT_PATH
INVENTORY_PATH = ROOT / d115.INVENTORY_PATH
READINESS_PATH = ROOT / "artifacts/trimem_v1/readiness_requirements.json"
FREEZE_PATH = ROOT / d115.FREEZE_PATH
REPORT_PATH = ROOT / d115.REPORT_PATH
FIXTURE_PATH = ROOT / d115.PREVIOUS_FAILURE_FIXTURE_PATH
GATE_CONTRACT_PATH = ROOT / d115.GATE_CONTRACT_PATH
TRIGGER_PATH = ROOT / d115.TRIGGER_PATH
ALIAS_HELPER_PATH = ROOT / d115.COMPILED_PREFIX_ALIAS_PATH

AMENDMENT_SCHEMA = d115.AMENDMENT_SCHEMA
INVENTORY_SCHEMA = d115.INVENTORY_SCHEMA
STATUS = d115.AMENDMENT_STATUS
CLASSIFICATION = d115.AMENDMENT_CLASSIFICATION
ENDPOINT = d115.AMENDMENT_ENDPOINT
FAILURE_SUBTYPE = d115.PREVIOUS_FAILURE_SUBTYPE
GATE_FAILURE_CLASSIFICATION = d115.PREVIOUS_FAILURE_CLASSIFICATION
GATE_FAILURE_MESSAGE = d115.PREVIOUS_FAILURE_MESSAGE

EXPECTED_REPOSITORY = d115.EXPECTED_REPOSITORY
EXPECTED_BRANCH = d115.EXPECTED_BRANCH
EXPECTED_REF = d115.EXPECTED_REF
EXPECTED_WORKFLOW_PATH = d115.EXPECTED_WORKFLOW_PATH
EXPECTED_CONCURRENCY_GROUP = d115.EXPECTED_CONCURRENCY_GROUP
EXPECTED_REMOTE_GATE_SPECS = d115.REMOTE_GATE_SPECS
EXPECTED_REMOTE_GATE_WORKFLOWS = d115.REQUIRED_REMOTE_GATE_WORKFLOWS

D114_SOURCE_HEAD = d115.PREVIOUS_SOURCE_HEAD
D114_EXECUTION_HEAD = d115.PREVIOUS_EXECUTION_HEAD
D114_RUN_ID = d115.PREVIOUS_RUN_ID
D114_RUN_ATTEMPT = d115.PREVIOUS_RUN_ATTEMPT
D114_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
D114_REQUEST_PATH = d115.PREVIOUS_SENTINEL_PATH
D114_REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.14"
D114_REQUEST_BLOB_OID = d115.PREVIOUS_SENTINEL_BLOB_OID
D114_REQUEST_BYTES = d115.PREVIOUS_SENTINEL_BYTES
D114_REQUEST_RAW_SHA256 = d115.PREVIOUS_SENTINEL_SHA256
D114_REQUEST_PAYLOAD_SHA256 = d115.PREVIOUS_REQUEST_PAYLOAD_SHA256
D114_FREEZE_SHA256 = d115.PREVIOUS_SOURCE_FREEZE_SHA256
D114_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_014_recovery_amendment.json"
)
D114_INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_014_recovery_inventory.json"
)
D114_AMENDMENT_SHA256 = (
    "fbe9e8193b79cdcef1d53be802ac493d9fc051046c20063c5ad10f5c053d0c1f"
)
D114_INVENTORY_SHA256 = (
    "d7ee03df98ab73dc427b0d12b94052331a854241fcaabae358a99beb4a6e3a14"
)
D114_GATE_SHA256 = (
    "2bd9aceb9db0e571cb194565473a0da19b5e2001913b236d7d0af9570da6e52b"
)
D114_RESEAL_SHA256 = (
    "9a10ffb0b2f91d842ff3579b4e06608109e320bd691db07bf98c361c8e8e3cdf"
)
D114_TRIGGER_SHA256 = (
    "94da6bdcca105ea27e031eb240ebe4c333b25998b5e4bc5b35ecfb674dc734ac"
)
D114_FIXTURE_SHA256 = (
    "f076d409b7b979d989f69ed6fe31dca91601c5eede407673315ba298ab35eea1"
)

D115_REQUEST_ID = d115.REQUEST_ID
D115_REQUEST_PATH = d115.SENTINEL_PATH
D115_REQUEST_SCHEMA = d115.REQUEST_SCHEMA
D115_REQUIRED_EXTERNAL_AUTHORIZATION = d115.REQUIRED_EXTERNAL_AUTHORIZATION

PRESERVED_SCIENTIFIC_PATHS = d115.PRESERVED_SCIENTIFIC_PATHS
GENERATED_PATHS = frozenset(
    {
        d115.AMENDMENT_PATH,
        d115.INVENTORY_PATH,
        d115.FREEZE_PATH,
    }
)
ALLOWED_CHANGED_PATHS = d115.ALLOWED_RECOVERY_PATHS
REQUIRED_CHANGED_PATHS = d115.REQUIRED_RECOVERY_CHANGES
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
DEVELOPMENT_TRIGGER_MODULE = re.compile(
    r"trimem_development_trigger_d[0-9]+\Z"
)
EXPECTED_ACTIVE_CONSUMER_IMPORTS: Mapping[
    str, frozenset[tuple[str, str | None]]
] = {
    "scripts/trimem_benchmark_matrix.py": frozenset(
        {
            ("SENTINEL_PATH", "DEVELOPMENT_SENTINEL_PATH"),
            ("DevelopmentTriggerError", None),
            (
                "validate_sentinel_commit",
                "validate_development_sentinel_commit",
            ),
        }
    ),
    "scripts/trimem_benchmark_run.py": frozenset(
        {
            ("EXPECTED_WORKFLOW_REF", "DEVELOPMENT_WORKFLOW_REF"),
            ("SENTINEL_PATH", "DEVELOPMENT_SENTINEL_PATH"),
            ("DevelopmentTriggerError", None),
            (
                "validate_sentinel_commit",
                "validate_development_sentinel_commit",
            ),
        }
    ),
}

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
EXEC_014_CONTROL_PLANE_ACTUALS: dict[str, int] = {
    "dependency_installations": 1,
    "harness_materializations": 2,
    "official_harness_loader_preflight_attempts": 1,
    "self_hosted_job_assignments": 1,
}


class D115ResealError(ValueError):
    """The D1.15 history, zero-authority boundary, or seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D115ResealError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise D115ResealError("JSON contains a duplicate field")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise D115ResealError(f"JSON contains non-finite constant: {value}")


def _strict_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    require(not raw.startswith(b"\xef\xbb\xbf"), f"{label} starts with BOM")
    require(b"\x00" not in raw, f"{label} contains NUL")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D115ResealError(f"{label} is not strict UTF-8 JSON") from exc
    require(isinstance(value, dict), f"{label} is not an object")
    return value


def read_json(path: Path) -> dict[str, Any]:
    return _strict_json_bytes(path.read_bytes(), label=str(path))


def git(*args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=text,
        )
    except subprocess.CalledProcessError as exc:
        raise D115ResealError("Git command failed") from exc


def _git_text(*args: str) -> str:
    raw = git(*args).stdout
    try:
        return raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise D115ResealError("Git returned non-UTF-8 text") from exc


def _git_lines(*args: str) -> list[str]:
    value = _git_text(*args)
    return [] if not value else value.splitlines()


def git_blob(commit: str, relative: str) -> bytes:
    return git("cat-file", "blob", f"{commit}:{relative}").stdout


def _working_bytes(relative: str) -> bytes:
    path = ROOT.joinpath(*PurePosixPath(relative).parts)
    require(path.is_file() and not path.is_symlink(), f"file is absent: {relative}")
    return path.read_bytes()


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        check=False,
        capture_output=True,
    ).returncode == 0


def validate_historical_d114() -> dict[str, Any]:
    require(
        _is_ancestor(D114_EXECUTION_HEAD, _git_text("rev-parse", "HEAD")),
        "current history does not preserve immutable D1.14 `_014`",
    )
    require(
        _git_lines("rev-list", "--parents", "-n", "1", D114_EXECUTION_HEAD)
        == [f"{D114_EXECUTION_HEAD} {D114_SOURCE_HEAD}"],
        "immutable `_014` parent differs",
    )
    require(
        _git_lines(
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            "--no-renames",
            D114_EXECUTION_HEAD,
        )
        == [f"A\t{D114_REQUEST_PATH}"],
        "immutable `_014` commit is not sentinel-only",
    )
    raw = git_blob(D114_EXECUTION_HEAD, D114_REQUEST_PATH)
    request = _strict_json_bytes(raw, label="immutable `_014` request")
    require(
        len(raw) == D114_REQUEST_BYTES
        and sha256(raw) == D114_REQUEST_RAW_SHA256
        and _git_text("rev-parse", f"{D114_EXECUTION_HEAD}:{D114_REQUEST_PATH}")
        == D114_REQUEST_BLOB_OID
        and request.get("schema") == D114_REQUEST_SCHEMA
        and request.get("request_id") == D114_REQUEST_ID
        and request.get("request_sha256")
        == "sha256:" + D114_REQUEST_PAYLOAD_SHA256
        and request.get("source_head") == D114_SOURCE_HEAD
        and request.get("actual_execution_authorized") is False
        and request.get("external_execution_approval_received") is False
        and raw == d115.canonical_bytes(request, trailing_lf=True),
        "immutable `_014` request identity differs",
    )
    historical_paths = {
        D114_AMENDMENT_PATH: D114_AMENDMENT_SHA256,
        D114_INVENTORY_PATH: D114_INVENTORY_SHA256,
        "scripts/trimem_d114_gate_contract.py": D114_GATE_SHA256,
        "scripts/trimem_d114_reseal.py": D114_RESEAL_SHA256,
        "scripts/trimem_development_trigger_d114.py": D114_TRIGGER_SHA256,
        "tests/fixtures/trimem_d114/exec_013_post_setup_failure.json": (
            D114_FIXTURE_SHA256
        ),
        "artifacts/trimem_v1/freeze.json": D114_FREEZE_SHA256,
    }
    for relative, expected in historical_paths.items():
        require(
            sha256(git_blob(D114_SOURCE_HEAD, relative)) == expected,
            f"historical D1.14 blob differs: {relative}",
        )
    amendment = _strict_json_bytes(
        git_blob(D114_SOURCE_HEAD, D114_AMENDMENT_PATH),
        label="historical D1.14 amendment",
    )
    inventory = _strict_json_bytes(
        git_blob(D114_SOURCE_HEAD, D114_INVENTORY_PATH),
        label="historical D1.14 inventory",
    )
    require(
        amendment.get("endpoint") == "TRIMEM_V1_READY_FOR_EXEC_014_REQUEST"
        and inventory.get("endpoint") == "TRIMEM_V1_READY_FOR_EXEC_014_REQUEST",
        "historical D1.14 endpoint differs",
    )
    return {
        "amendment_sha256": D114_AMENDMENT_SHA256,
        "execution_head": D114_EXECUTION_HEAD,
        "execution_parent": D114_SOURCE_HEAD,
        "freeze_sha256": D114_FREEZE_SHA256,
        "historical_d113": amendment.get("historical_d113"),
        "inventory_sha256": D114_INVENTORY_SHA256,
        "request_blob_oid": D114_REQUEST_BLOB_OID,
        "request_bytes": D114_REQUEST_BYTES,
        "request_id": D114_REQUEST_ID,
        "request_payload_sha256": D114_REQUEST_PAYLOAD_SHA256,
        "request_raw_sha256": D114_REQUEST_RAW_SHA256,
        "run_attempt": D114_RUN_ATTEMPT,
        "run_id": D114_RUN_ID,
        "sentinel_only": True,
        "source_head": D114_SOURCE_HEAD,
        "status": "PASS",
    }


def validate_optional_exec_015_boundary() -> str | None:
    head = _git_text("rev-parse", "HEAD")
    additions = _git_lines(
        "log", "--format=%H", "--diff-filter=A", head, "--", D115_REQUEST_PATH
    )
    target = ROOT.joinpath(*PurePosixPath(D115_REQUEST_PATH).parts)
    if not additions:
        require(not target.exists(), "uncommitted `_015` request exists")
        return None
    require(len(additions) == 1, "`_015` was added more than once")
    execution_head = additions[0]
    parents = _git_lines("rev-list", "--parents", "-n", "1", execution_head)
    require(len(parents) == 1 and len(parents[0].split()) == 2, "`_015` parent differs")
    parent = parents[0].split()[1]
    require(
        _git_lines(
            "diff-tree", "--no-commit-id", "--name-status", "-r", "--no-renames", execution_head
        )
        == [f"A\t{D115_REQUEST_PATH}"],
        "`_015` commit is not sentinel-only",
    )
    require(
        _is_ancestor(execution_head, head),
        "current tree does not preserve `_015`",
    )
    d115.validate_sentinel_commit(
        ROOT,
        execution_head,
        expected_parent=parent,
        require_checked_out_head=False,
    )
    return execution_head


def _source_head(execution_head: str | None) -> str:
    if execution_head is None:
        return _git_text("rev-parse", "HEAD")
    return _git_lines("rev-list", "--parents", "-n", "1", execution_head)[0].split()[1]


def source_bytes(relative: str, *, source_head: str | None = None) -> bytes:
    selected = _source_head(validate_optional_exec_015_boundary()) if source_head is None else source_head
    return git_blob(selected, relative)


def verify_changed_path_coverage(source_head: str | None = None) -> tuple[str, ...]:
    selected = _source_head(validate_optional_exec_015_boundary()) if source_head is None else source_head
    require(
        selected != D114_EXECUTION_HEAD
        and _is_ancestor(D114_EXECUTION_HEAD, selected),
        "D1.15 source is not a strict descendant of immutable `_014`",
    )
    changes: dict[str, str] = {}
    for line in _git_lines(
        "diff", "--no-ext-diff", "--name-status", "--no-renames", D114_EXECUTION_HEAD, selected
    ):
        pieces = line.split("\t")
        require(len(pieces) == 2, "D1.15 changed-path stream is malformed")
        status, relative = pieces
        require(status in {"A", "M"}, f"D1.15 diff status is forbidden: {status}")
        require(relative in ALLOWED_CHANGED_PATHS, f"D1.15 path escapes allowlist: {relative}")
        require(relative not in changes, f"D1.15 path appears twice: {relative}")
        changes[relative] = status
    for relative, expected in REQUIRED_CHANGED_PATHS.items():
        require(
            changes.get(relative) == expected,
            f"required D1.15 change missing or wrong status: {relative}",
        )
    require(
        not _git_lines("log", "--format=%H", selected, "--", D115_REQUEST_PATH),
        "D1.15 source history already contains `_015`",
    )
    return tuple(sorted(changes))


def validate_preserved_science(source_head: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in PRESERVED_SCIENTIFIC_PATHS:
        historical = git_blob(D114_EXECUTION_HEAD, relative)
        current = git_blob(source_head, relative)
        require(current == historical, f"scientific input changed in D1.15: {relative}")
        result[relative] = sha256(current)
    return result


def validate_failure_replay() -> dict[str, Any]:
    gate = importlib.import_module("trimem_d115_gate_contract")
    try:
        result = gate.validate_fixture(gate.load_fixture(FIXTURE_PATH))
    except Exception as exc:
        raise D115ResealError("D1.15 failure replay rejected its fixture") from exc
    require(
        result.get("status") == "PASS"
        and result.get("source_head") == D114_SOURCE_HEAD
        and result.get("execution_head") == D114_EXECUTION_HEAD
        and result.get("execution_run_id") == D114_RUN_ID
        and result.get("execution_run_attempt") == D114_RUN_ATTEMPT
        and result.get("protected_environment_entered") is False,
        "D1.15 failure replay identity differs",
    )
    for name in ZERO_SCIENTIFIC_ACTUALS:
        if name in result:
            require(result[name] == 0, f"D1.15 replay counter is nonzero: {name}")
    return dict(result)


def diagnostic_rehearsal_record() -> dict[str, Any]:
    return {
        "actuals": {
            "grader_attempts": 0,
            "grader_containers": 0,
            "image_pulls": 0,
            "model_generation_calls": 0,
            "model_metadata_requests": 0,
            "paid_calls": 0,
            "usd": 0,
        },
        "alias_path": d115.COMPILED_PREFIX_ALIAS,
        "alias_target": d115.COMPILED_PREFIX_ALIAS_TARGET,
        "benchmark_evidence_validator": "PASS",
        "classification": "CREDENTIAL_FREE_DIAGNOSTIC_ONLY",
        "evidence_sha256": None,
        "future_revalidation_required": True,
        "loader_implementation": "UNCHANGED_D114",
        "loader_preflight_marker": "TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_PASS",
        "observed_at_utc": None,
        "pinned_harness_clones": True,
        "production_result": False,
        "runner_distribution": d115.RUNNER_DISTRIBUTION,
        "status": "PASS",
    }


def current_failure_record() -> dict[str, Any]:
    return {
        "classification": CLASSIFICATION,
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "failure_boundary": {
            "bounded_context_preflight": "FAILED_AT_EXACT_LOADER_GATE",
            "branch_trigger_preflight": "PASSED",
            "dependency_install_completed": True,
            "frozen_serial_phase": "SKIPPED",
            "harness_materialization_completed": True,
            "protected_environment_entered": False,
        },
        "failure_subtype": FAILURE_SUBTYPE,
        "observed_control_plane_actuals": dict(EXEC_014_CONTROL_PLANE_ACTUALS),
        "observed_scientific_actuals": dict(ZERO_SCIENTIFIC_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_014_rerun_allowed": False,
            "request_015_execution_authorized": False,
        },
        "request": {
            "id": D114_REQUEST_ID,
            "path": D114_REQUEST_PATH,
            "payload_sha256": D114_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": D114_REQUEST_RAW_SHA256,
            "source_head": D114_SOURCE_HEAD,
        },
        "root_cause": {
            "compiled_alias": d115.COMPILED_PREFIX_ALIAS,
            "expected_alias_target": d115.COMPILED_PREFIX_ALIAS_TARGET,
            "observed_python_real_prefix": d115.OBSERVED_PYTHON_REAL_PREFIX,
            "observed_sysconfig_libdir": d115.OBSERVED_SYSCONFIG_LIBDIR,
            "observed_sysconfig_libdir_exists": False,
            "recovery_rule": (
                "validate the exact root-owned compiled-prefix alias, then rerun "
                "the complete loader and benchmark-evidence validator"
            ),
        },
        "schema": "trimem/development-exec-014-loader-failure/1.0",
        "scientific_status": "NOT_STARTED_ON_EXEC_014",
        "status": "IMMUTABLE_PUBLIC_GITHUB_EVIDENCE_REPLAYED",
        "workflow_run": {
            "attempt": D114_RUN_ATTEMPT,
            "conclusion": "failure",
            "head_sha": D114_EXECUTION_HEAD,
            "id": D114_RUN_ID,
            "source_head_sha": D114_SOURCE_HEAD,
        },
    }


def current_recovery_record() -> dict[str, Any]:
    return {
        "actual_execution_authorized": False,
        "benchmark_image_pulls": 0,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "external_execution_approval_received": False,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "performance_measured": False,
        "request_creation_authority_received": True,
        "request_id": D115_REQUEST_ID,
        "request_path": D115_REQUEST_PATH,
        "request_present_in_recovery_source": False,
        "schema": "trimem/development-exec-015-recovery/1.0",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def _validate_active_consumer_imports(relative: str, source: str) -> None:
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        raise D115ResealError(
            f"D1.15 active request consumer is invalid Python: {relative}"
        ) from exc

    trigger_imports: list[ast.Import | ast.ImportFrom] = []
    active_imports: list[ast.ImportFrom] = []
    dynamic_trigger_references: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                DEVELOPMENT_TRIGGER_MODULE.fullmatch(alias.name)
                for alias in node.names
            ):
                trigger_imports.append(node)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if DEVELOPMENT_TRIGGER_MODULE.fullmatch(module):
                trigger_imports.append(node)
                if module == "trimem_development_trigger_d115":
                    active_imports.append(node)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and DEVELOPMENT_TRIGGER_MODULE.fullmatch(node.value)
        ):
            dynamic_trigger_references.add(node.value)

    expected_names = EXPECTED_ACTIVE_CONSUMER_IMPORTS[relative]
    actual_names = (
        frozenset((alias.name, alias.asname) for alias in active_imports[0].names)
        if len(active_imports) == 1
        else frozenset()
    )
    require(
        len(trigger_imports) == 1
        and len(active_imports) == 1
        and active_imports[0].level == 0
        and actual_names == expected_names
        and not dynamic_trigger_references,
        f"D1.15 active request consumer differs: {relative}",
    )


def validate_active_contract(source_head: str) -> dict[str, Any]:
    trigger = importlib.import_module("trimem_development_trigger_d115")
    expected = {
        "REQUEST_ID": D115_REQUEST_ID,
        "REQUEST_SCHEMA": D115_REQUEST_SCHEMA,
        "SENTINEL_PATH": D115_REQUEST_PATH,
        "REQUIRED_EXTERNAL_AUTHORIZATION": D115_REQUIRED_EXTERNAL_AUTHORIZATION,
        "AMENDMENT_CLASSIFICATION": CLASSIFICATION,
        "AMENDMENT_STATUS": STATUS,
        "AMENDMENT_ENDPOINT": ENDPOINT,
        "PREVIOUS_SOURCE_HEAD": D114_SOURCE_HEAD,
        "PREVIOUS_EXECUTION_HEAD": D114_EXECUTION_HEAD,
        "PREVIOUS_RUN_ID": D114_RUN_ID,
        "PREVIOUS_RUN_ATTEMPT": D114_RUN_ATTEMPT,
        "PREVIOUS_SENTINEL_SHA256": D114_REQUEST_RAW_SHA256,
        "PREVIOUS_REQUEST_PAYLOAD_SHA256": D114_REQUEST_PAYLOAD_SHA256,
        "EXPECTED_CONCURRENCY_GROUP": EXPECTED_CONCURRENCY_GROUP,
        "LOADER_REHEARSAL_SCHEMA": "trimem/d115-exact-loader-rehearsal/1.0",
        "COMPILED_PREFIX_ALIAS_SCHEMA": "trimem/compiled-prefix-alias/1.0",
    }
    for name, value in expected.items():
        require(getattr(trigger, name, None) == value, f"D1.15 trigger differs: {name}")
    workflow = git_blob(source_head, EXPECTED_WORKFLOW_PATH).decode(
        "utf-8", errors="strict"
    )
    require("\r" not in workflow, "D1.15 workflow is not LF-only")
    require(
        workflow.count(f"      - {D115_REQUEST_PATH}\n") == 1
        and f"      - {D114_REQUEST_PATH}\n" not in workflow
        and workflow.count(f"group: {EXPECTED_CONCURRENCY_GROUP}") == 1
        and workflow.count("scripts/trimem_compiled_prefix_alias.py --check") == 2
        and workflow.count('exact_python="$pythonLocation/bin/python3.11"') == 2
        and workflow.count("scripts/trimem_official_harness_loader_preflight.py") == 2,
        "D1.15 workflow alias/loader/request contract differs",
    )
    for relative in EXPECTED_ACTIVE_CONSUMER_IMPORTS:
        consumer = git_blob(source_head, relative).decode("utf-8", errors="strict")
        _validate_active_consumer_imports(relative, consumer)
    return {
        "actual_execution_authorized": False,
        "alias_validation": "EXACT_ROOT_OWNED_DEFAULT_ONLY",
        "direct_loader_python": "$pythonLocation/bin/python3.11",
        "full_loader_rehearsal_required": True,
        "protected_execution_authorized": False,
        "pull_request_remote_gate_count": 14,
        "push_remote_gate_count": 6,
        "remote_gate_count": len(EXPECTED_REMOTE_GATE_SPECS),
        "request_creation_authority_only": True,
        "request_id": D115_REQUEST_ID,
        "request_path": D115_REQUEST_PATH,
        "unique_remote_gate_workflow_count": len(EXPECTED_REMOTE_GATE_WORKFLOWS),
    }


def validate_readiness() -> None:
    readiness = read_json(READINESS_PATH)
    status = readiness.get("current_status")
    authority = readiness.get("development_authorization_boundary")
    require(
        isinstance(status, Mapping)
        and status.get("CLASSIFICATION") == CLASSIFICATION
        and status.get("ENDPOINT") == ENDPOINT
        and status.get("FAILURE_SUBTYPE") == FAILURE_SUBTYPE
        and status.get("DEV_APPROVAL_ALLOWED") == "NO"
        and status.get("DEV_EXECUTION_ALLOWED") == "NO"
        and status.get("DEV_SCIENTIFIC_STATUS") == "NOT_STARTED_ON_EXEC_014"
        and status.get("SCIENTIFIC_RESULT") == "NO_DEVELOPMENT_SCIENTIFIC_RESULT"
        and status.get("OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH")
        == "NOT_REACHED_ON_EXEC_014"
        and status.get("OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START")
        == "NOT_REACHED_ON_EXEC_014"
        and status.get("PERFORMANCE") == "NOT_MEASURED",
        "D1.15 current status differs",
    )
    require(
        readiness.get("historical_development_exec_014_loader_failure")
        == current_failure_record(),
        "D1.15 historical `_014` failure record differs",
    )
    require(
        readiness.get("current_development_activation") == current_recovery_record(),
        "D1.15 current recovery activation differs",
    )
    require(
        isinstance(authority, Mapping)
        and authority.get("active_development_approval") is False
        and authority.get("approval_request_eligible") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_014_created") is True
        and authority.get("request_014_attempt_one_consumed") is True
        and authority.get("request_014_attempt_two_allowed") is False
        and authority.get("request_014_rerun_allowed") is False
        and authority.get("request_015_created") is False
        and authority.get("request_015_allowed_after_exact_remote_gates_and_rehearsal")
        is True
        and authority.get("request_015_authorized") is False
        and authority.get("fresh_execution_request_creation_authorized") is True
        and authority.get("required_external_authorization")
        == D115_REQUIRED_EXTERNAL_AUTHORIZATION
        and authority.get("recovery_request_id") == D115_REQUEST_ID
        and authority.get("recovery_request_path") == D115_REQUEST_PATH,
        "D1.15 development authority boundary differs",
    )


def _validate_implementation_sources(
    source_head: str, changed_paths: Sequence[str]
) -> dict[str, str]:
    implementation: dict[str, str] = {}
    for relative in changed_paths:
        if relative in GENERATED_PATHS:
            continue
        raw = git_blob(source_head, relative)
        require(
            _working_bytes(relative) == raw,
            f"D1.15 implementation is uncommitted: {relative}",
        )
        if relative.endswith(".py"):
            try:
                ast.parse(raw.decode("utf-8", errors="strict"), filename=relative)
            except (UnicodeDecodeError, SyntaxError) as exc:
                raise D115ResealError(f"D1.15 Python source invalid: {relative}") from exc
        implementation[relative] = sha256(raw)
    return implementation


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    execution_head = validate_optional_exec_015_boundary()
    source_head = _source_head(execution_head)
    changed_paths = verify_changed_path_coverage(source_head)
    historical = validate_historical_d114()
    replay = validate_failure_replay()
    science = validate_preserved_science(source_head)
    active = validate_active_contract(source_head)
    validate_readiness()
    implementation = _validate_implementation_sources(source_head, changed_paths)
    authority = {
        "active_development_approval": False,
        "actual_execution_authorized": False,
        "development_execution_authorized": False,
        "external_execution_approval_received": False,
        "request_014_attempt_one_consumed": True,
        "request_014_attempt_two_allowed": False,
        "request_014_rerun_allowed": False,
        "request_015_created": False,
        "request_015_created_in_source": False,
        "request_015_creation_authorized": True,
        "request_015_execution_authorized": False,
        "request_015_request_creation_authorized": True,
        "required_external_authorization": D115_REQUIRED_EXTERNAL_AUTHORIZATION,
        "sentinel_contains_execution_authority": False,
    }
    repair_contract = {
        "alias_helper": d115.COMPILED_PREFIX_ALIAS_PATH,
        "alias_mutation_by_helper": False,
        "alias_path": d115.COMPILED_PREFIX_ALIAS,
        "alias_target": d115.COMPILED_PREFIX_ALIAS_TARGET,
        "benchmark_evidence_validator_required": True,
        "full_loader_preflight_required": True,
        "loader_binary": "$pythonLocation/bin/python3.11",
        "protected_environment_entered_on_exec_014": False,
        "strict_loader_validator": "UNCHANGED_FAIL_CLOSED",
    }
    amendment = {
        "active_recovery": active,
        "authority_boundary": authority,
        "classification": CLASSIFICATION,
        "credential_free_failure_replay": replay,
        "diagnostic_rehearsal": diagnostic_rehearsal_record(),
        "endpoint": ENDPOINT,
        "exec_014_failure": current_failure_record(),
        "historical_d114": historical,
        "implementation_sha256": implementation,
        "preserved_scientific_sha256": science,
        "repair_contract": repair_contract,
        "schema": AMENDMENT_SCHEMA,
        "status": STATUS,
        "zero_scientific_recovery_actuals": dict(ZERO_SCIENTIFIC_ACTUALS),
    }
    inventory = {
        "allowed_changed_paths": sorted(ALLOWED_CHANGED_PATHS),
        "changed_path_policy": "VALIDATED_AT_CHECK_TIME_NOT_EMBEDDED",
        "classification": CLASSIFICATION,
        "diagnostic_rehearsal": diagnostic_rehearsal_record(),
        "documents": {
            "amendment": d115.AMENDMENT_PATH,
            "failure_fixture": d115.PREVIOUS_FAILURE_FIXTURE_PATH,
            "readiness": "artifacts/trimem_v1/readiness_requirements.json",
            "report": d115.REPORT_PATH,
        },
        "endpoint": ENDPOINT,
        "historical_boundary": historical,
        "implementation_sha256": implementation,
        "preserved_scientific_sha256": science,
        "schema": INVENTORY_SCHEMA,
        "source_changed_paths": list(changed_paths),
        "status": STATUS,
    }
    canonical_bytes(amendment)
    canonical_bytes(inventory)
    return amendment, inventory


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_all() -> None:
    require(
        validate_optional_exec_015_boundary() is None,
        "D1.15 source artifacts cannot be rewritten after `_015` creation",
    )
    amendment, inventory = build_artifacts()
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    execution_head = validate_optional_exec_015_boundary()
    amendment, inventory = build_artifacts()
    require(read_json(AMENDMENT_PATH) == amendment, "D1.15 amendment is stale")
    require(read_json(INVENTORY_PATH) == inventory, "D1.15 inventory is stale")
    import trimem_freeze

    trimem_freeze.check_freeze(ROOT)
    return {
        "benchmark_image_pulls": 0,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "grader_containers": 0,
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "request_014_attempt_one_consumed": True,
        "request_014_rerun_allowed": False,
        "request_015_created": execution_head is not None,
        "request_015_execution_authorized": False,
        "research_freeze_sha256": sha256(source_bytes(d115.FREEZE_PATH)),
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the credential-free D1.15 exec-015 recovery seal"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_all()
            result = check_all()
        else:
            result = check_all()
    except (D115ResealError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
