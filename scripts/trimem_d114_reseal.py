"""Build and verify the credential-free D1.14 ``_014`` recovery seal.

D1.14 preserves the exact D1.13 source, its sentinel-only ``_013`` child, and
the zero-model post-setup runner failure as immutable Git history.  The only
runtime correction is an explicit step environment supplied to the existing
strict LD_LIBRARY_PATH validator; no alternate path shape is accepted.

Importing this module is side-effect free.  It performs no network, Docker,
grader, credential, or model action.
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

ROOT = Path(__file__).resolve().parents[1]

AMENDMENT_PATH = ROOT / (
    "artifacts/trimem_v1/development_exec_014_recovery_amendment.json"
)
INVENTORY_PATH = ROOT / (
    "artifacts/trimem_v1/development_exec_014_recovery_inventory.json"
)
READINESS_PATH = ROOT / "artifacts/trimem_v1/readiness_requirements.json"
FREEZE_PATH = ROOT / "artifacts/trimem_v1/freeze.json"
REPORT_PATH = ROOT / "reports/TRIMEM_D114_EXEC_014_RECOVERY.md"
FIXTURE_PATH = ROOT / (
    "tests/fixtures/trimem_d114/exec_013_post_setup_failure.json"
)
GATE_CONTRACT_PATH = ROOT / "scripts/trimem_d114_gate_contract.py"
TRIGGER_PATH = ROOT / "scripts/trimem_development_trigger_d114.py"

AMENDMENT_SCHEMA = "trimem/development-exec-014-recovery-amendment/1.0"
INVENTORY_SCHEMA = "trimem/development-exec-014-recovery-inventory/1.0"
STATUS = "FROZEN_CREDENTIAL_FREE_EXEC_013_FAILURE_READY_FOR_EXEC_014_REQUEST"
CLASSIFICATION = "POST_EXEC_013_ZERO_MODEL_SETUP_PYTHON_ENVIRONMENT_RECOVERY"
ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_014_REQUEST"
FAILURE_SUBTYPE = "SETUP_PYTHON_POST_SETUP_LD_LIBRARY_PATH_SHAPE"
GATE_FAILURE_CLASSIFICATION = "POST_SETUP_PYTHON_DUAL_LD_LIBRARY_PATH_FAIL_CLOSED"
GATE_FAILURE_MESSAGE = (
    "runner LD_LIBRARY_PATH binding differs: bounded-context preflight process "
    "environment"
)

EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_REF = f"refs/heads/{EXPECTED_BRANCH}"
EXPECTED_WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-014"
EXPECTED_REMOTE_GATE_SPECS = (
    (".github/workflows/ci-trimem.yml", "push", None),
    (".github/workflows/ci-trimem-grader-loader.yml", "push", None),
    (".github/workflows/ci-trimem-harness-lock.yml", "push", None),
    (".github/workflows/ci-trimem-multi-swe-contract.yml", "push", None),
    (".github/workflows/ci-trimem-e2e.yml", "push", None),
    (".github/workflows/ci-trimem-dev-toolchain.yml", "push", None),
    (".github/workflows/ci.yml", "pull_request", 18),
    (".github/workflows/codeql.yml", "pull_request", 18),
    (".github/workflows/ci-docs.yml", "pull_request", 18),
    (".github/workflows/ci-company-package.yml", "pull_request", 18),
    (".github/workflows/ci-company-harness.yml", "pull_request", 18),
    (".github/workflows/ci-company-demo.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-harness-lock.yml", "pull_request", 18),
    (".github/workflows/ci-oidc.yml", "pull_request", 18),
    (".github/workflows/ci-experience-schema.yml", "pull_request", 18),
    (".github/workflows/ci-oss-release.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-grader-loader.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-multi-swe-contract.yml", "pull_request", 18),
    (".github/workflows/ci-trimem-e2e.yml", "pull_request", 18),
    (".github/workflows/ci-trimem.yml", "pull_request", 18),
)
EXPECTED_REMOTE_GATE_WORKFLOWS = tuple(
    dict.fromkeys(spec[0] for spec in EXPECTED_REMOTE_GATE_SPECS)
)
EXACT_PYTHON_LIBRARY_PATH = (
    "/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib"
)

D113_SOURCE_HEAD = "cb17ceae0fbc951dff34213de977a73b5405fefc"
D113_EXECUTION_HEAD = "35bfa338915d731dab499f2dfee08b38741bfe8d"
D113_RUN_ID = 34_138_918_074
D113_RUN_ATTEMPT = 1
D113_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013"
D113_REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_013.json"
)
D113_REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.13"
D113_REQUEST_BLOB_OID = "899492ee4835394f78699ee1d4a6273c2d26e875"
D113_REQUEST_BYTES = 21_784
D113_REQUEST_RAW_SHA256 = (
    "a500568cedfa800bd85e20263b604fa2c1d24f634644d5ef14f517a8330b6417"
)
D113_REQUEST_PAYLOAD_SHA256 = (
    "132c7fc8a7ca166076882a53d3a69db56b4ccc5ab9e41ec1071a196f0618fe26"
)
D113_FREEZE_SHA256 = (
    "ea74940aad297761c62c9f2555eb9aba3819e584082bf68951247e9a39d1f0c6"
)
D113_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_013_recovery_amendment.json"
)
D113_INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_013_recovery_inventory.json"
)
D113_FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
D113_AMENDMENT_SHA256 = (
    "961539205cc4670ce11cf983ec89200498a3ebd31d47c6e7cf3e0d4403200d99"
)
D113_INVENTORY_SHA256 = (
    "162649ed15af5a19c45bea1f3233f6280cae964e55e0c7fb63b8c4c09fe2ae74"
)

D114_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014"
D114_REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_014.json"
)
D114_REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.14"
D114_REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014_APPROVED_ONCE"
)

HISTORICAL_D113_SHA256 = {
    D113_AMENDMENT_PATH: D113_AMENDMENT_SHA256,
    D113_INVENTORY_PATH: D113_INVENTORY_SHA256,
    D113_FREEZE_PATH: D113_FREEZE_SHA256,
    "reports/TRIMEM_D113_EXEC_013_RECOVERY.md": (
        "39814b6a5e931a9341b238e5f9487b955e1baa0e170f30cf44b83ed6152ed676"
    ),
    "scripts/trimem_d113_gate_contract.py": (
        "8817c2baf52b523ad6b0c701b50a846761b64c82f846732e8bab0fa130db7584"
    ),
    "scripts/trimem_d113_reseal.py": (
        "6bdb9303449b6ea15933dc2bdfefbc8081bd1f22f2f7fb1cd793220eb9853816"
    ),
    "scripts/trimem_development_trigger_d113.py": (
        "4e4de8fb39ae7ee67c890fa3db1573a5278aefd17f5e64bf61cadd0aea6b5fac"
    ),
    "tests/fixtures/trimem_d113/exec_012_preprotected_failure.json": (
        "7228e3786fc6ace212686e466eb9eb13808a9c75b620f9190ce646952d6af5b6"
    ),
    "tests/unit/test_trimem_d113_e1_trigger.py": (
        "d26378b105fc7572fb5b16ced4466953041f225f004c49de369dc6d9d190817a"
    ),
    "tests/unit/test_trimem_d113_gate_contract.py": (
        "cf4b5fd4bdae150171122c3c2075aea2cb446aa7f54f82528bc8df34cb801ecb"
    ),
    "tests/unit/test_trimem_d113_status_and_reseal.py": (
        "ac87892c0da8bb30da8104d8d8a61204dbc53cb15f345ffa3911f3d208875c08"
    ),
}

# Active integration files are intentionally absent.  The D1.13 status test
# is adapted to select exact historical Git blobs instead of current HEAD.
IMMUTABLE_D113_CURRENT_PATHS = tuple(
    relative
    for relative in HISTORICAL_D113_SHA256
    if relative
    not in {
        D113_FREEZE_PATH,
        "tests/unit/test_trimem_d113_status_and_reseal.py",
    }
)

ZERO_ACTUALS: dict[str, int | float] = {
    "benchmark_image_pulls": 0,
    "dependency_installations": 0,
    "grader_containers": 0,
    "harness_materializations": 0,
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

STATUS_FIELDS = {
    "OFFICIAL_GRADER_SEMANTICS_AND_DISCRIMINATION": "ESTABLISHED_BY_P0_1_5",
    "OFFICIAL_GRADER_IMAGE_INTEGRITY": "ESTABLISHED",
    "OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH": "NOT_REACHED_ON_EXEC_013",
    "OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START": "NOT_REACHED_ON_EXEC_013",
    "PERFORMANCE": "NOT_MEASURED",
}

PRESERVED_SCIENTIFIC_PATHS = (
    "artifacts/trimem_v1/grader_image_lock.json",
    "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json",
    "artifacts/trimem_v1/multi_swe_report_semantics_lock.json",
    "artifacts/trimem_v1/provider_output_schema_lock.json",
    "artifacts/trimem_v1/solve_output_budget_contract_lock.json",
    "configs/trimem_v1/arms.json",
    "configs/trimem_v1/benchmark_environment.lock",
    "configs/trimem_v1/benchmark_environment_lock.json",
    "configs/trimem_v1/cost_plan.json",
    "configs/trimem_v1/development_manifest.json",
    "configs/trimem_v1/grader_lock.json",
    "configs/trimem_v1/heldout_manifest.json",
    "configs/trimem_v1/m2_candidate_bundles.json",
    "configs/trimem_v1/m2_candidates/balanced.json",
    "configs/trimem_v1/m2_candidates/baseline.json",
    "configs/trimem_v1/m2_candidates/precision.json",
    "configs/trimem_v1/m2_candidates/recall.json",
    "configs/trimem_v1/m2_policy.json",
    "configs/trimem_v1/model_lock.json",
    "configs/trimem_v1/provider_output_schemas.json",
    "configs/trimem_v1/selection_plan.json",
    "configs/trimem_v1/solve_output_budget_contract.json",
    "configs/trimem_v1/tool_environment_lock.json",
    "artifacts/trimem_v1/credential_free_e2e/dqn_frozen_checkpoint.json",
)

IMPLEMENTATION_PATHS = (
    ".gitattributes",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-experience-schema.yml",
    ".github/workflows/ci-oidc.yml",
    ".github/workflows/ci-oss-release.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/readiness_requirements.json",
    "reports/TRIMEM_D114_EXEC_014_RECOVERY.md",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_d114_gate_contract.py",
    "scripts/trimem_d114_reseal.py",
    "scripts/trimem_development_trigger_d114.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_multi_swe_contract.py",
    "scripts/trimem_verify_ready.py",
    "tests/fixtures/trimem_d114/exec_013_post_setup_failure.json",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_d110_status_and_reseal.py",
    "tests/unit/test_trimem_d113_status_and_reseal.py",
    "tests/unit/test_trimem_d114_e1_trigger.py",
    "tests/unit/test_trimem_d114_gate_contract.py",
    "tests/unit/test_trimem_d114_post_setup_environment.py",
    "tests/unit/test_trimem_d114_status_and_reseal.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_d16_native_action.py",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
)
GENERATED_PATHS = frozenset(
    {
        AMENDMENT_PATH.relative_to(ROOT).as_posix(),
        INVENTORY_PATH.relative_to(ROOT).as_posix(),
        FREEZE_PATH.relative_to(ROOT).as_posix(),
    }
)
ALLOWED_CHANGED_PATHS = frozenset(IMPLEMENTATION_PATHS) | GENERATED_PATHS
REQUIRED_CHANGED_PATHS = {
    ".gitattributes": "M",
    ".github/workflows/ci-trimem-dev-toolchain.yml": "M",
    ".github/workflows/ci-trimem.yml": "M",
    ".github/workflows/ci-experience-schema.yml": "M",
    ".github/workflows/ci-oidc.yml": "M",
    ".github/workflows/ci-oss-release.yml": "M",
    ".github/workflows/ci-trimem-e2e.yml": "M",
    ".github/workflows/ci-trimem-harness-lock.yml": "M",
    ".github/workflows/ci-trimem-multi-swe-contract.yml": "M",
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH.relative_to(ROOT).as_posix(): "A",
    INVENTORY_PATH.relative_to(ROOT).as_posix(): "A",
    FREEZE_PATH.relative_to(ROOT).as_posix(): "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    "reports/TRIMEM_D114_EXEC_014_RECOVERY.md": "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_d114_gate_contract.py": "A",
    "scripts/trimem_d114_reseal.py": "A",
    "scripts/trimem_development_trigger_d114.py": "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/fixtures/trimem_d114/exec_013_post_setup_failure.json": "A",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d113_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d114_e1_trigger.py": "A",
    "tests/unit/test_trimem_d114_gate_contract.py": "A",
    "tests/unit/test_trimem_d114_post_setup_environment.py": "A",
    "tests/unit/test_trimem_d114_status_and_reseal.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class D114ResealError(ValueError):
    """The D1.14 history, zero-authority boundary, or seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D114ResealError(message)


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
        )
        + "\n"
    ).encode("utf-8")


def canonical_indented_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise D114ResealError(f"non-finite JSON constant: {value}")


def _strict_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    require(not raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM is forbidden: {label}")
    require(b"\x00" not in raw, f"NUL is forbidden: {label}")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D114ResealError(f"strict JSON decode failed: {label}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {label}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"JSON is absent: {path}")
    return _strict_json_bytes(path.read_bytes(), label=str(path))


def git(*args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=text,
            encoding="utf-8" if text else None,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise D114ResealError("Git command failed") from exc


def _git_text(*args: str) -> str:
    completed = git(*args)
    raw = completed.stdout
    assert isinstance(raw, bytes)
    try:
        return raw.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise D114ResealError("Git returned non-UTF-8 text") from exc


def _git_lines(*args: str) -> list[str]:
    value = _git_text(*args)
    return [] if not value else value.splitlines()


def git_blob(commit: str, relative: str) -> bytes:
    require(HEX40.fullmatch(commit) is not None, "Git blob commit is malformed")
    completed = git("cat-file", "blob", f"{commit}:{relative}")
    raw = completed.stdout
    assert isinstance(raw, bytes)
    return raw


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode not in {0, 1}:
        raise D114ResealError("cannot validate D1.14 ancestry")
    return completed.returncode == 0


def _working_bytes(relative: str) -> bytes:
    path = ROOT.joinpath(*PurePosixPath(relative).parts)
    require(path.is_file() and not path.is_symlink(), f"required file is not regular: {relative}")
    return path.read_bytes()


def _single_parent(commit: str, *, label: str) -> str:
    row = _git_text("rev-list", "--parents", "-n", "1", commit).split()
    require(len(row) == 2 and row[0] == commit, f"{label} must be single-parent")
    return row[1]


def _validate_regular_blob(
    commit: str, relative: str, expected_oid: str | None = None
) -> None:
    row = _git_text("ls-tree", "--full-tree", commit, "--", relative)
    left, separator, observed_path = row.partition("\t")
    fields = left.split()
    require(
        separator == "\t"
        and observed_path == relative
        and len(fields) == 3
        and fields[0] == "100644"
        and fields[1] == "blob"
        and HEX40.fullmatch(fields[2]) is not None,
        f"historical path is not one regular 100644 Git blob: {relative}",
    )
    if expected_oid is not None:
        require(fields[2] == expected_oid, f"historical Git blob OID differs: {relative}")


def _validate_d113_request(raw: bytes) -> dict[str, Any]:
    require(len(raw) == D113_REQUEST_BYTES, "immutable _013 request byte count differs")
    require(sha256(raw) == D113_REQUEST_RAW_SHA256, "immutable _013 raw SHA-256 differs")
    request = _strict_json_bytes(raw, label=D113_REQUEST_PATH)
    require(raw == canonical_bytes(request), "immutable _013 request is not canonical")
    bindings = request.get("bindings")
    require(
        request.get("schema") == D113_REQUEST_SCHEMA
        and request.get("request_id") == D113_REQUEST_ID
        and request.get("request_path") == D113_REQUEST_PATH
        and request.get("source_head") == D113_SOURCE_HEAD
        and request.get("request_sha256") == f"sha256:{D113_REQUEST_PAYLOAD_SHA256}"
        and request.get("phase") == "DEVELOPMENT_TUNING"
        and request.get("actual_execution_authorized") is False
        and request.get("external_execution_approval_received") is False
        and isinstance(bindings, Mapping)
        and bindings.get("freeze_sha256") == f"sha256:{D113_FREEZE_SHA256}"
        and bindings.get("d113_amendment_sha256")
        == f"sha256:{D113_AMENDMENT_SHA256}"
        and bindings.get("d113_inventory_sha256")
        == f"sha256:{D113_INVENTORY_SHA256}",
        "immutable _013 identity or zero-authority binding differs",
    )
    for field in ("activation_actuals", "pre_execution_actuals"):
        actuals = request.get(field)
        require(
            isinstance(actuals, Mapping)
            and all(not isinstance(value, bool) and value == 0 for value in actuals.values()),
            f"immutable _013 {field} contains nonzero actuals",
        )
    return request


def validate_historical_d113() -> dict[str, Any]:
    """Verify the exact D1.13 source, sentinel child, source seal, and D1.12 chain."""

    require(
        _git_text("cat-file", "-t", D113_SOURCE_HEAD) == "commit"
        and _git_text("cat-file", "-t", D113_EXECUTION_HEAD) == "commit",
        "immutable D1.13 source or execution commit is unavailable",
    )
    require(
        _single_parent(D113_EXECUTION_HEAD, label="_013 execution") == D113_SOURCE_HEAD,
        "_013 execution is not the exact child of its frozen source",
    )
    changes = _git_lines(
        "diff-tree",
        "--no-ext-diff",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        D113_EXECUTION_HEAD,
    )
    require(changes == [f"A\t{D113_REQUEST_PATH}"], "_013 commit is not sentinel-only")
    _validate_regular_blob(D113_EXECUTION_HEAD, D113_REQUEST_PATH, D113_REQUEST_BLOB_OID)
    require(
        not _git_lines("log", "--format=%H", D113_SOURCE_HEAD, "--", D113_REQUEST_PATH),
        "_013 existed in its recovery-source history",
    )
    require(
        _git_lines(
            "log", "--format=%H", "--diff-filter=A", D113_EXECUTION_HEAD, "--", D113_REQUEST_PATH
        )
        == [D113_EXECUTION_HEAD],
        "_013 does not have one immutable addition commit",
    )
    request_raw = git_blob(D113_EXECUTION_HEAD, D113_REQUEST_PATH)
    request = _validate_d113_request(request_raw)

    amendment_raw = git_blob(D113_SOURCE_HEAD, D113_AMENDMENT_PATH)
    inventory_raw = git_blob(D113_SOURCE_HEAD, D113_INVENTORY_PATH)
    freeze_raw = git_blob(D113_SOURCE_HEAD, D113_FREEZE_PATH)
    require(
        sha256(amendment_raw) == D113_AMENDMENT_SHA256
        and sha256(inventory_raw) == D113_INVENTORY_SHA256
        and sha256(freeze_raw) == D113_FREEZE_SHA256,
        "immutable D1.13 seal identity differs",
    )
    amendment = _strict_json_bytes(amendment_raw, label=D113_AMENDMENT_PATH)
    inventory = _strict_json_bytes(inventory_raw, label=D113_INVENTORY_PATH)
    freeze = _strict_json_bytes(freeze_raw, label=D113_FREEZE_PATH)
    require(
        amendment_raw == canonical_bytes(amendment)
        and inventory_raw == canonical_bytes(inventory)
        and freeze_raw == canonical_indented_bytes(freeze),
        "immutable D1.13 seal JSON is not canonical",
    )
    implementation = inventory.get("implementation_sha256")
    freeze_files = freeze.get("files")
    require(
        amendment.get("schema") == "trimem/development-exec-013-recovery-amendment/1.0"
        and inventory.get("schema") == "trimem/development-exec-013-recovery-inventory/1.0"
        and amendment.get("status")
        == "FROZEN_CREDENTIAL_FREE_EXEC_012_FAILURE_READY_FOR_EXEC_013_REQUEST"
        and inventory.get("status")
        == "FROZEN_CREDENTIAL_FREE_EXEC_012_FAILURE_READY_FOR_EXEC_013_REQUEST"
        and amendment.get("implementation_sha256") == implementation
        and isinstance(implementation, Mapping)
        and isinstance(freeze_files, Mapping),
        "immutable D1.13 artifact structure differs",
    )
    for relative, digest in implementation.items():
        require(
            isinstance(relative, str)
            and isinstance(digest, str)
            and HEX64.fullmatch(digest) is not None,
            "immutable D1.13 implementation hash is malformed",
        )
        raw = git_blob(D113_SOURCE_HEAD, relative)
        require(sha256(raw) == digest, f"D1.13 implementation blob differs: {relative}")
        require(
            freeze_files.get(relative) == {"bytes": len(raw), "sha256": digest},
            f"D1.13 freeze omits implementation blob: {relative}",
        )
    require(D113_REQUEST_PATH not in freeze_files, "active _013 entered its source freeze")

    head = _git_text("rev-parse", "HEAD")
    require(
        HEX40.fullmatch(head) is not None and _is_ancestor(D113_EXECUTION_HEAD, head),
        "current D1.14 tree is not a descendant of immutable _013",
    )
    require(
        git_blob(head, D113_REQUEST_PATH) == request_raw
        and _working_bytes(D113_REQUEST_PATH) == request_raw,
        "current-tree _013 differs from its immutable execution blob",
    )
    for relative, expected_digest in HISTORICAL_D113_SHA256.items():
        historical = git_blob(D113_EXECUTION_HEAD, relative)
        require(
            sha256(historical) == expected_digest,
            f"immutable D1.13 historical blob differs: {relative}",
        )
        if relative in IMMUTABLE_D113_CURRENT_PATHS:
            require(
                _working_bytes(relative) == historical,
                f"immutable D1.13 current-tree file differs: {relative}",
            )

    d113 = _load_exact_module(
        "trimem_d113_reseal", ROOT / "scripts/trimem_d113_reseal.py"
    )
    historical_d112 = d113.validate_historical_d112()
    require(historical_d112.get("status") == "PASS", "D1.12 history chain differs")
    return {
        "amendment_sha256": D113_AMENDMENT_SHA256,
        "execution_head": D113_EXECUTION_HEAD,
        "execution_parent": D113_SOURCE_HEAD,
        "freeze_sha256": D113_FREEZE_SHA256,
        "historical_d112": historical_d112,
        "inventory_sha256": D113_INVENTORY_SHA256,
        "request_blob_oid": D113_REQUEST_BLOB_OID,
        "request_bytes": D113_REQUEST_BYTES,
        "request_id": D113_REQUEST_ID,
        "request_payload_sha256": D113_REQUEST_PAYLOAD_SHA256,
        "request_raw_sha256": D113_REQUEST_RAW_SHA256,
        "run_attempt": D113_RUN_ATTEMPT,
        "run_id": D113_RUN_ID,
        "sentinel_only": True,
        "source_head": request["source_head"],
        "status": "PASS",
    }


def _sentinel_parent(execution_head: str) -> str:
    return _single_parent(execution_head, label="_014 execution")


def validate_optional_exec_014_boundary() -> str | None:
    """Return the exact `_014` execution HEAD, or ``None`` at its source."""

    head = _git_text("rev-parse", "HEAD")
    additions = _git_lines("log", "--format=%H", "--diff-filter=A", head, "--", D114_REQUEST_PATH)
    target = ROOT.joinpath(*PurePosixPath(D114_REQUEST_PATH).parts)
    if not additions:
        require(not target.exists() and not target.is_symlink(), "uncommitted _014 is forbidden")
        return None
    require(additions == [head], "_014 must have exactly one addition at current HEAD")
    parent = _sentinel_parent(head)
    changes = _git_lines(
        "diff-tree", "--no-ext-diff", "--no-commit-id", "--name-status", "-r", "--no-renames", head
    )
    require(changes == [f"A\t{D114_REQUEST_PATH}"], "_014 commit is not sentinel-only")
    _validate_regular_blob(head, D114_REQUEST_PATH)
    require(
        not _git_lines("log", "--format=%H", parent, "--", D114_REQUEST_PATH),
        "_014 exists in recovery-source history",
    )
    require(target.is_file() and not target.is_symlink(), "checked-out _014 is not regular")
    trigger = _load_exact_module("trimem_development_trigger_d114", TRIGGER_PATH)
    validator = getattr(trigger, "validate_sentinel_commit", None)
    require(callable(validator), "D1.14 trigger lacks validate_sentinel_commit")
    try:
        validator(ROOT, head, expected_parent=parent, require_checked_out_head=True)
    except Exception as exc:
        raise D114ResealError("D1.14 trigger rejected the _014 boundary") from exc
    return head


def _source_head(execution_head: str | None) -> str:
    return _git_text("rev-parse", "HEAD") if execution_head is None else _sentinel_parent(execution_head)


def source_bytes(relative: str, *, source_head: str | None = None) -> bytes:
    selected = (
        _source_head(validate_optional_exec_014_boundary())
        if source_head is None
        else source_head
    )
    raw = git_blob(selected, relative)
    require(_working_bytes(relative) == raw, f"working bytes differ from source blob: {relative}")
    return raw


def verify_changed_path_coverage(source_head: str | None = None) -> tuple[str, ...]:
    selected = (
        _source_head(validate_optional_exec_014_boundary())
        if source_head is None
        else source_head
    )
    require(
        HEX40.fullmatch(selected) is not None
        and selected != D113_EXECUTION_HEAD
        and _is_ancestor(D113_EXECUTION_HEAD, selected),
        "D1.14 source is not a strict descendant of immutable _013",
    )
    completed = git(
        "diff", "--no-ext-diff", "--no-renames", "--name-status", "-z", D113_EXECUTION_HEAD, selected
    )
    raw = completed.stdout
    assert isinstance(raw, bytes)
    pieces = [piece for piece in raw.split(b"\0") if piece]
    require(len(pieces) % 2 == 0, "D1.14 changed-path stream is malformed")
    changes: dict[str, str] = {}
    try:
        for index in range(0, len(pieces), 2):
            status = pieces[index].decode("ascii", errors="strict")
            relative = pieces[index + 1].decode("utf-8", errors="strict")
            require(status in {"A", "M"}, f"D1.14 diff status is forbidden: {status}")
            require(relative not in changes, f"D1.14 path appears twice: {relative}")
            changes[relative] = status
    except UnicodeDecodeError as exc:
        raise D114ResealError("D1.14 changed path is not canonical UTF-8") from exc
    unexpected = sorted(set(changes) - ALLOWED_CHANGED_PATHS)
    require(not unexpected, "D1.14 paths escape the explicit seal: " + ", ".join(unexpected))
    for relative, status in REQUIRED_CHANGED_PATHS.items():
        require(
            changes.get(relative) == status,
            f"required D1.14 change missing or wrong status: {relative}",
        )
    require(
        not _git_lines("log", "--format=%H", selected, "--", D114_REQUEST_PATH),
        "_014 exists in recovery-source history",
    )
    require(
        git_blob(selected, D113_REQUEST_PATH) == git_blob(D113_EXECUTION_HEAD, D113_REQUEST_PATH),
        "D1.14 source rewrites immutable _013",
    )
    tracked = _git_lines("ls-files")
    forbidden = [
        relative
        for relative in tracked
        if relative.endswith((".pyc", ".pyo"))
        or "__pycache__" in PurePosixPath(relative).parts
        or any(
            part in {"build", "dist"} or part.endswith(".egg-info")
            for part in PurePosixPath(relative).parts
        )
    ]
    require(not forbidden, f"tracked build artifacts are forbidden: {forbidden}")
    return tuple(sorted(changes))


def validate_preserved_science(source_head: str) -> dict[str, str]:
    preserved: dict[str, str] = {}
    for relative in PRESERVED_SCIENTIFIC_PATHS:
        historical = git_blob(D113_EXECUTION_HEAD, relative)
        current = git_blob(source_head, relative)
        require(current == historical, f"scientific input changed in D1.14: {relative}")
        preserved[relative] = sha256(current)
    request = _validate_d113_request(git_blob(D113_EXECUTION_HEAD, D113_REQUEST_PATH))
    projection = {
        name: request[name]
        for name in (
            "control_plane", "exact_model", "hard_caps", "phase", "scientific_workload"
        )
    }
    preserved["_013_scientific_projection"] = sha256(canonical_bytes(projection))
    return preserved


def _load_exact_module(name: str, expected_path: Path) -> Any:
    require(
        expected_path.is_file() and not expected_path.is_symlink(),
        f"required D1.14 module is absent or non-regular: {expected_path}",
    )
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        raise D114ResealError(f"cannot import required D1.14 module: {name}") from exc
    module_file = getattr(module, "__file__", None)
    require(
        isinstance(module_file, str) and Path(module_file).resolve() == expected_path.resolve(),
        f"D1.14 module resolved outside repository: {name}",
    )
    return module


def validate_failure_replay() -> dict[str, Any]:
    gate = _load_exact_module("trimem_d114_gate_contract", GATE_CONTRACT_PATH)
    for name, expected in {
        "EXPECTED_SOURCE_HEAD": D113_SOURCE_HEAD,
        "EXPECTED_EXECUTION_HEAD": D113_EXECUTION_HEAD,
        "EXPECTED_RUN_ID": D113_RUN_ID,
        "EXPECTED_RUN_ATTEMPT": D113_RUN_ATTEMPT,
        "EXPECTED_FAILURE_CLASSIFICATION": GATE_FAILURE_CLASSIFICATION,
        "EXPECTED_FAILURE_SUBTYPE": FAILURE_SUBTYPE,
    }.items():
        require(getattr(gate, name, None) == expected, f"D1.14 gate constant differs: {name}")
    try:
        result = gate.validate_fixture(gate.load_fixture(FIXTURE_PATH))
    except Exception as exc:
        raise D114ResealError("D1.14 failure replay rejected its fixture") from exc
    require(isinstance(result, Mapping), "D1.14 failure replay result is not an object")
    normalized = dict(result)
    require(
        normalized.get("status") == "PASS"
        and normalized.get("source_head") == D113_SOURCE_HEAD
        and normalized.get("execution_head") == D113_EXECUTION_HEAD
        and normalized.get("execution_run_id") == D113_RUN_ID
        and normalized.get("execution_run_attempt") == D113_RUN_ATTEMPT
        and normalized.get("protected_environment_entered") is False,
        "D1.14 failure replay identity differs",
    )
    for key in (
        "benchmark_image_pulls",
        "dependency_installations",
        "grader_containers",
        "harness_materializations",
        "model_api_calls",
        "official_grader_runs",
        "paid_model_calls",
        "task_arm_runs",
        "total_usd",
    ):
        require(
            not isinstance(normalized.get(key), bool) and normalized.get(key) == 0,
            "D1.14 failure replay contains nonzero execution actuals",
        )
    return normalized


def validate_active_contract(source_head: str) -> dict[str, Any]:
    trigger = _load_exact_module("trimem_development_trigger_d114", TRIGGER_PATH)
    required_constants = {
        "EXPECTED_BRANCH": EXPECTED_BRANCH,
        "EXPECTED_REF": EXPECTED_REF,
        "EXPECTED_REPOSITORY": EXPECTED_REPOSITORY,
        "EXPECTED_WORKFLOW_PATH": EXPECTED_WORKFLOW_PATH,
        "REQUEST_ID": D114_REQUEST_ID,
        "REQUEST_SCHEMA": D114_REQUEST_SCHEMA,
        "SENTINEL_PATH": D114_REQUEST_PATH,
        "REQUIRED_EXTERNAL_AUTHORIZATION": D114_REQUIRED_EXTERNAL_AUTHORIZATION,
        "EXPECTED_CONCURRENCY_GROUP": EXPECTED_CONCURRENCY_GROUP,
        "REMOTE_GATE_SPECS": EXPECTED_REMOTE_GATE_SPECS,
        "REQUIRED_REMOTE_GATE_WORKFLOWS": EXPECTED_REMOTE_GATE_WORKFLOWS,
        "AMENDMENT_PATH": AMENDMENT_PATH.relative_to(ROOT).as_posix(),
        "AMENDMENT_SCHEMA": AMENDMENT_SCHEMA,
        "INVENTORY_PATH": INVENTORY_PATH.relative_to(ROOT).as_posix(),
        "INVENTORY_SCHEMA": INVENTORY_SCHEMA,
        "AMENDMENT_CLASSIFICATION": CLASSIFICATION,
        "AMENDMENT_STATUS": STATUS,
        "AMENDMENT_ENDPOINT": ENDPOINT,
    }
    for name, expected in required_constants.items():
        require(getattr(trigger, name, None) == expected, f"D1.14 trigger constant differs: {name}")
    require(
        getattr(trigger, "PREVIOUS_SENTINEL_PATH", None) == D113_REQUEST_PATH
        and getattr(trigger, "PREVIOUS_SENTINEL_SHA256", None) == D113_REQUEST_RAW_SHA256
        and getattr(trigger, "PREVIOUS_SOURCE_HEAD", None) == D113_SOURCE_HEAD
        and getattr(trigger, "PREVIOUS_EXECUTION_HEAD", None) == D113_EXECUTION_HEAD
        and getattr(trigger, "PREVIOUS_RUN_ID", None) == D113_RUN_ID
        and getattr(trigger, "PREVIOUS_FAILURE_SUBTYPE", None) == FAILURE_SUBTYPE
        and getattr(trigger, "PREVIOUS_FAILURE_CLASSIFICATION", None)
        == GATE_FAILURE_CLASSIFICATION,
        "D1.14 trigger does not bind exact spent _013 history",
    )
    raw = source_bytes(TRIGGER_PATH.relative_to(ROOT).as_posix(), source_head=source_head)
    try:
        ast.parse(raw.decode("utf-8", errors="strict"), filename=str(TRIGGER_PATH))
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise D114ResealError("D1.14 trigger is not valid UTF-8 Python") from exc

    workflow = git_blob(source_head, EXPECTED_WORKFLOW_PATH).decode("utf-8", errors="strict")
    require("\r" not in workflow, "D1.14 benchmark workflow is not LF-only")
    require(
        workflow.count(f"      - {D114_REQUEST_PATH}\n") == 1
        and f"      - {D113_REQUEST_PATH}\n" not in workflow
        and f"group: {EXPECTED_CONCURRENCY_GROUP}" in workflow
        and "github.run_attempt == 1" in workflow
        and "scripts/trimem_development_trigger_d114.py" in workflow
        and "scripts/trimem_development_trigger_d113.py" not in workflow,
        "D1.14 benchmark workflow route differs",
    )
    # Two pre-setup and five post-setup D1.14 trigger steps each receive the
    # same single exact value.  The strict validator is intentionally unchanged.
    require(
        workflow.count(f"LD_LIBRARY_PATH: {EXACT_PYTHON_LIBRARY_PATH}") == 7,
        "D1.14 explicit Python shared-library bindings differ",
    )
    return {
        "actual_execution_authorized": False,
        "environment_repair": "EXPLICIT_EXACT_STEP_BINDING",
        "pull_request_remote_gate_count": 14,
        "protected_execution_authorized": False,
        "push_remote_gate_count": 6,
        "request_creation_authority_only": True,
        "request_id": D114_REQUEST_ID,
        "request_path": D114_REQUEST_PATH,
        "remote_gate_count": len(EXPECTED_REMOTE_GATE_SPECS),
        "source_validation": "GIT_BLOB_EXACT_AT_CHECK_TIME",
        "strict_ld_library_validator_relaxed": False,
        "unique_remote_gate_workflow_count": len(EXPECTED_REMOTE_GATE_WORKFLOWS),
    }


def current_failure_record() -> dict[str, Any]:
    return {
        "classification": CLASSIFICATION,
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "failure_boundary": {
            "bounded_context_preflight": "FAILED_AFTER_SETUP_BEFORE_INSTALL",
            "branch_trigger_preflight": "PASSED",
            "dependency_install_started": False,
            "frozen_serial_phase": "SKIPPED",
            "harness_materialization_started": False,
            "protected_environment_entered": False,
        },
        "failure_subtype": FAILURE_SUBTYPE,
        "observed_usage": dict(ZERO_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_013_rerun_allowed": False,
            "request_014_execution_authorized": False,
        },
        "request": {
            "id": D113_REQUEST_ID,
            "path": D113_REQUEST_PATH,
            "payload_sha256": D113_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": D113_REQUEST_RAW_SHA256,
            "source_head": D113_SOURCE_HEAD,
        },
        "root_cause": {
            "expected_ld_library_path": EXACT_PYTHON_LIBRARY_PATH,
            "observed_ld_library_path": (
                "/opt/trimem-d112-runners/exec/_work/_tool/Python/3.11.10/x64/lib:"
                + EXACT_PYTHON_LIBRARY_PATH
            ),
            "recovery_rule": (
                "supply the one exact locked LD_LIBRARY_PATH as a step environment "
                "after setup-python; retain exact-equality validation"
            ),
        },
        "schema": "trimem/development-exec-013-post-setup-failure/1.0",
        "scientific_status": "NOT_STARTED_ON_EXEC_013",
        "status": "IMMUTABLE_PUBLIC_GITHUB_EVIDENCE_REPLAYED",
        "workflow_run": {
            "attempt": D113_RUN_ATTEMPT,
            "conclusion": "failure",
            "head_sha": D113_EXECUTION_HEAD,
            "id": D113_RUN_ID,
            "source_head_sha": D113_SOURCE_HEAD,
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
        "request_id": D114_REQUEST_ID,
        "request_path": D114_REQUEST_PATH,
        "request_present_in_recovery_source": False,
        "schema": "trimem/development-exec-014-recovery/1.0",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def validate_readiness() -> None:
    readiness = read_json(READINESS_PATH)
    status = readiness.get("current_status")
    authority = readiness.get("development_authorization_boundary")
    require(
        isinstance(status, Mapping)
        and all(status.get(key) == value for key, value in STATUS_FIELDS.items())
        and status.get("CLASSIFICATION") == CLASSIFICATION
        and status.get("ENDPOINT") == ENDPOINT
        and status.get("FAILURE_SUBTYPE") == FAILURE_SUBTYPE
        and status.get("DEV_APPROVAL_ALLOWED") == "NO"
        and status.get("DEV_EXECUTION_ALLOWED") == "NO"
        and status.get("DEV_SCIENTIFIC_STATUS") == "NOT_STARTED_ON_EXEC_014"
        and status.get("SCIENTIFIC_RESULT") == "NO_DEVELOPMENT_SCIENTIFIC_RESULT",
        "D1.14 current status differs",
    )
    require(
        readiness.get("historical_development_exec_013_post_setup_failure")
        == current_failure_record(),
        "D1.14 historical _013 failure record differs",
    )
    require(
        readiness.get("current_development_activation") == current_recovery_record(),
        "D1.14 current recovery activation differs",
    )
    require(
        isinstance(authority, Mapping)
        and authority.get("active_development_approval") is False
        and authority.get("approval_request_eligible") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_013_created") is True
        and authority.get("request_013_attempt_one_consumed") is True
        and authority.get("request_013_attempt_two_allowed") is False
        and authority.get("request_013_rerun_allowed") is False
        and authority.get("request_014_created") is False
        and authority.get("request_014_allowed_after_exact_remote_gates") is True
        and authority.get("request_014_authorized") is False
        and authority.get("fresh_execution_request_creation_authorized") is True
        and authority.get("required_external_authorization")
        == D114_REQUIRED_EXTERNAL_AUTHORIZATION
        and authority.get("recovery_request_id") == D114_REQUEST_ID
        and authority.get("recovery_request_path") == D114_REQUEST_PATH,
        "D1.14 development authority boundary differs",
    )


def _validate_implementation_sources(source_head: str) -> dict[str, str]:
    implementation: dict[str, str] = {}
    for relative in IMPLEMENTATION_PATHS:
        raw = git_blob(source_head, relative)
        require(_working_bytes(relative) == raw, f"D1.14 implementation is uncommitted: {relative}")
        if relative.endswith(".py"):
            try:
                ast.parse(raw.decode("utf-8", errors="strict"), filename=relative)
            except (UnicodeDecodeError, SyntaxError) as exc:
                raise D114ResealError(f"D1.14 Python source invalid: {relative}") from exc
        implementation[relative] = sha256(raw)
    return implementation


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    execution_head = validate_optional_exec_014_boundary()
    source_head = _source_head(execution_head)
    changed_paths = verify_changed_path_coverage(source_head)
    historical = validate_historical_d113()
    replay = validate_failure_replay()
    science = validate_preserved_science(source_head)
    active = validate_active_contract(source_head)
    validate_readiness()
    implementation = _validate_implementation_sources(source_head)
    authority = {
        "active_development_approval": False,
        "actual_execution_authorized": False,
        "development_execution_authorized": False,
        "external_execution_approval_received": False,
        "request_013_attempt_one_consumed": True,
        "request_013_attempt_two_allowed": False,
        "request_013_rerun_allowed": False,
        "request_014_created": False,
        "request_014_created_in_source": False,
        "request_014_creation_authorized": True,
        "request_014_execution_authorized": False,
        "request_014_request_creation_authorized": True,
        "required_external_authorization": D114_REQUIRED_EXTERNAL_AUTHORIZATION,
        "sentinel_contains_execution_authority": False,
    }
    repair_contract = {
        "post_setup_environment": "EXACT_STEP_LEVEL_LD_LIBRARY_PATH",
        "protected_environment_entered_on_exec_013": False,
        "strict_validator": "UNCHANGED_EXACT_EQUALITY",
        "workflow_steps_covered": [
            "bounded post-setup re-observation",
            "protected post-setup re-observation",
            "protected service start",
            "protected service verification",
            "protected service cleanup",
        ],
    }
    amendment = {
        "active_recovery": active,
        "authority_boundary": authority,
        "classification": CLASSIFICATION,
        "credential_free_failure_replay": replay,
        "endpoint": ENDPOINT,
        "exec_013_failure": current_failure_record(),
        "historical_d113": historical,
        "implementation_sha256": implementation,
        "preserved_scientific_sha256": science,
        "repair_contract": repair_contract,
        "schema": AMENDMENT_SCHEMA,
        "status": STATUS,
        "zero_cost_recovery_actuals": dict(ZERO_ACTUALS),
    }
    inventory = {
        "allowed_changed_paths": sorted(ALLOWED_CHANGED_PATHS),
        "changed_path_policy": "VALIDATED_AT_CHECK_TIME_NOT_EMBEDDED",
        "classification": CLASSIFICATION,
        "documents": {
            "amendment": AMENDMENT_PATH.relative_to(ROOT).as_posix(),
            "failure_fixture": FIXTURE_PATH.relative_to(ROOT).as_posix(),
            "readiness": READINESS_PATH.relative_to(ROOT).as_posix(),
            "report": REPORT_PATH.relative_to(ROOT).as_posix(),
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
        validate_optional_exec_014_boundary() is None,
        "D1.14 source artifacts cannot be rewritten after _014 creation",
    )
    amendment, inventory = build_artifacts()
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    execution_head = validate_optional_exec_014_boundary()
    amendment, inventory = build_artifacts()
    require(read_json(AMENDMENT_PATH) == amendment, "D1.14 amendment is stale")
    require(read_json(INVENTORY_PATH) == inventory, "D1.14 inventory is stale")
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
        "request_013_attempt_one_consumed": True,
        "request_013_rerun_allowed": False,
        "request_014_created": execution_head is not None,
        "request_014_execution_authorized": False,
        "research_freeze_sha256": sha256(
            source_bytes(FREEZE_PATH.relative_to(ROOT).as_posix())
        ),
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the credential-free D1.14 exec-014 recovery seal"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_all()
        result = check_all()
    except (D114ResealError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
