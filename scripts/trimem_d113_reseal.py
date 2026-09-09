"""Build and verify the credential-free D1.13 ``_013`` recovery seal.

D1.13 preserves the spent ``_012`` request and its attempt-one failure as
immutable Git history.  It permits creation of one new zero-authority
``_013`` request only after a new source commit, exact-head gates, and fresh
runner evidence exist.  It never treats request-creation authority as model,
grader, protected-environment, or scientific execution authority.

Importing this module is intentionally side-effect free and does not import
the active D1.13 trigger or failure-replay module.  Those dependencies are
loaded only by :func:`build_artifacts`, where absence or drift fails closed.
This module performs no network, Docker, grader, credential, or model action.
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
    "artifacts/trimem_v1/development_exec_013_recovery_amendment.json"
)
INVENTORY_PATH = ROOT / (
    "artifacts/trimem_v1/development_exec_013_recovery_inventory.json"
)
READINESS_PATH = ROOT / "artifacts/trimem_v1/readiness_requirements.json"
FREEZE_PATH = ROOT / "artifacts/trimem_v1/freeze.json"
REPORT_PATH = ROOT / "reports/TRIMEM_D113_EXEC_013_RECOVERY.md"
FIXTURE_PATH = ROOT / (
    "tests/fixtures/trimem_d113/exec_012_preprotected_failure.json"
)
GATE_CONTRACT_PATH = ROOT / "scripts/trimem_d113_gate_contract.py"
TRIGGER_PATH = ROOT / "scripts/trimem_development_trigger_d113.py"

AMENDMENT_SCHEMA = "trimem/development-exec-013-recovery-amendment/1.0"
INVENTORY_SCHEMA = "trimem/development-exec-013-recovery-inventory/1.0"
STATUS = "FROZEN_CREDENTIAL_FREE_EXEC_012_FAILURE_READY_FOR_EXEC_013_REQUEST"
CLASSIFICATION = "POST_EXEC_012_ZERO_MODEL_RUNNER_OBSERVER_RECOVERY"
ENDPOINT = "TRIMEM_V1_READY_FOR_EXEC_013_REQUEST"
FAILURE_SUBTYPE = "HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION"
GATE_FAILURE_CLASSIFICATION = (
    "HOSTED_GITHUB_TOKEN_REPOSITORY_RUNNER_LIST_COMMAND_FAILURE"
)

EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_BRANCH = "codex/trimem-coder-v1"
EXPECTED_REF = f"refs/heads/{EXPECTED_BRANCH}"
EXPECTED_WORKFLOW_PATH = ".github/workflows/trimem-benchmark.yml"
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-013"

D112_SOURCE_HEAD = "9db94e2a4abfaad0bb27079738b77836d68fa2e4"
D112_EXECUTION_HEAD = "491d1022fe079d182d7b453c48083c486936dcb2"
D112_RUN_ID = 34_128_541_859
D112_RUN_ATTEMPT = 1
D112_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_012"
D112_REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_012.json"
)
D112_REQUEST_BLOB_OID = "f4111cfd1a26b4099f0b0fdc4dd840d4de21764f"
D112_REQUEST_BYTES = 20_561
D112_REQUEST_RAW_SHA256 = (
    "6691a24bf488a79b4e1843a129d3d8773090fe2654828534c35eeecc22cc9d38"
)
D112_REQUEST_PAYLOAD_SHA256 = (
    "efa99c554fbae9bbeb8a87536365fcfc6afa54e6ee48de17ef9ffdb0eb72132b"
)
D112_FREEZE_SHA256 = (
    "3bbafc53504b45c20996094d96a6abfa5fd9e90c5b078eb2f1dc3f1f6d7ad5b4"
)
D112_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_exec_012_activation_amendment.json"
)
D112_INVENTORY_PATH = (
    "artifacts/trimem_v1/development_exec_012_activation_inventory.json"
)
D112_FREEZE_PATH = "artifacts/trimem_v1/freeze.json"
D112_AMENDMENT_SHA256 = (
    "ea048e55709ecf2cba498447048f89a48680b208aa21fb7c7915b316e9e63a69"
)
D112_INVENTORY_SHA256 = (
    "2d5e02b01435bce7eee1f831c56f841e67ae84dbcf567e163babf2afb42ff375"
)

D113_REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013"
D113_REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_013.json"
)
D113_REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.13"
D113_REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013_APPROVED_ONCE"
)

HISTORICAL_D112_SHA256 = {
    D112_AMENDMENT_PATH: D112_AMENDMENT_SHA256,
    D112_INVENTORY_PATH: D112_INVENTORY_SHA256,
    D112_FREEZE_PATH: D112_FREEZE_SHA256,
    "reports/TRIMEM_D112_EXEC_012_ACTIVATION.md": (
        "1dc9ea55c4258b2819dc3a0475212d703b72b003ce5c78e67c84ea0c87e32d9f"
    ),
    "scripts/trimem_d112_reseal.py": (
        "efc736469aaaf53829887a75427bae2354a6094b4ad508f71d6b5b8783345e4f"
    ),
    "scripts/trimem_development_trigger_d112.py": (
        "34bd85b208e3b466fec719dbed0805939fbdd7387cb57385b78c4774a8abe593"
    ),
    "tests/unit/test_trimem_d112_e1_trigger.py": (
        "5f0d0de04928c2472f141a6a1d80c7bed9d31306fda27d15fdbe9d041153f00d"
    ),
    "tests/unit/test_trimem_d112_status_and_reseal.py": (
        "f638f3735b1e7a769af5a9c775ce368d8dff8357ec5f81e903a2c22d059650d1"
    ),
}

# These D1.12-only files remain byte-identical in the D1.13 tree.  Active
# integration files are intentionally not listed because D1.13 replaces their
# current-generation route while their old bytes remain available from Git.
IMMUTABLE_D112_CURRENT_PATHS = tuple(
    relative
    for relative in HISTORICAL_D112_SHA256
    if relative
    not in {
        D112_FREEZE_PATH,
        # D1.22 intentionally changes the shared D1.12 service launcher to
        # bind Qdrant's portable nofile limit.  The immutable D1.12 Git blob
        # is still checked above; only current-tree equality is superseded.
        "scripts/trimem_development_trigger_d112.py",
        # D1.13 adapts only the historical tests' source selection.  Their
        # original D1.12 bytes remain verified above from the exact Git blob.
        "tests/unit/test_trimem_d112_e1_trigger.py",
        "tests/unit/test_trimem_d112_status_and_reseal.py",
    }
)

ZERO_ACTUALS: dict[str, int | float] = {
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

STATUS_FIELDS = {
    "OFFICIAL_GRADER_SEMANTICS_AND_DISCRIMINATION": "ESTABLISHED_BY_P0_1_5",
    "OFFICIAL_GRADER_IMAGE_INTEGRITY": "ESTABLISHED",
    "OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH": "NOT_REACHED_ON_EXEC_012",
    "OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START": "NOT_REACHED_ON_EXEC_012",
    "PERFORMANCE": "NOT_MEASURED",
}

# These files define scientific inputs rather than the activation transport.
# Every one must be byte-identical to the immutable `_012` execution tree.
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

# Complete D1.13 source-layer path vocabulary.  No scientific payload path is
# admitted here.  Generated documents are separate because `--write` creates
# them only after the source implementation is committed.
IMPLEMENTATION_PATHS = (
    ".gitattributes",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/readiness_requirements.json",
    "reports/TRIMEM_D113_EXEC_013_RECOVERY.md",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_d113_gate_contract.py",
    "scripts/trimem_d113_reseal.py",
    "scripts/trimem_development_trigger_d113.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_multi_swe_contract.py",
    "scripts/trimem_verify_ready.py",
    "tests/fixtures/trimem_d113/exec_012_preprotected_failure.json",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_d110_status_and_reseal.py",
    "tests/unit/test_trimem_d112_e1_trigger.py",
    "tests/unit/test_trimem_d112_status_and_reseal.py",
    "tests/unit/test_trimem_d113_e1_trigger.py",
    "tests/unit/test_trimem_d113_gate_contract.py",
    "tests/unit/test_trimem_d113_status_and_reseal.py",
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
    ".github/workflows/trimem-benchmark.yml": "M",
    AMENDMENT_PATH.relative_to(ROOT).as_posix(): "A",
    INVENTORY_PATH.relative_to(ROOT).as_posix(): "A",
    FREEZE_PATH.relative_to(ROOT).as_posix(): "M",
    "artifacts/trimem_v1/readiness_requirements.json": "M",
    "reports/TRIMEM_D113_EXEC_013_RECOVERY.md": "A",
    "scripts/trimem_benchmark_matrix.py": "M",
    "scripts/trimem_benchmark_run.py": "M",
    "scripts/trimem_d113_gate_contract.py": "A",
    "scripts/trimem_d113_reseal.py": "A",
    "scripts/trimem_development_trigger_d113.py": "A",
    "scripts/trimem_freeze.py": "M",
    "scripts/trimem_multi_swe_contract.py": "M",
    "scripts/trimem_verify_ready.py": "M",
    "tests/fixtures/trimem_d113/exec_012_preprotected_failure.json": "A",
    "tests/unit/test_trimem_benchmark_readiness.py": "M",
    "tests/unit/test_trimem_d110_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d112_e1_trigger.py": "M",
    "tests/unit/test_trimem_d112_status_and_reseal.py": "M",
    "tests/unit/test_trimem_d113_e1_trigger.py": "A",
    "tests/unit/test_trimem_d113_gate_contract.py": "A",
    "tests/unit/test_trimem_d113_status_and_reseal.py": "A",
    "tests/unit/test_trimem_dev_toolchain_workflows.py": "M",
    "tests/unit/test_trimem_development_trigger.py": "M",
    "tests/unit/test_trimem_d16_native_action.py": "M",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py": "M",
}

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class D113ResealError(ValueError):
    """The D1.13 history, zero-authority boundary, or seal differs."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise D113ResealError(message)


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
        if key in result:
            raise D113ResealError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise D113ResealError(f"non-finite JSON constant is forbidden: {value}")


def _strict_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    require(not raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM is forbidden: {label}")
    require(b"\r" not in raw, f"CR bytes are forbidden: {label}")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D113ResealError(f"invalid strict JSON: {label}") from exc
    require(isinstance(value, dict), f"JSON root is not an object: {label}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise D113ResealError(f"cannot read required JSON: {path}") from exc
    return _strict_json_bytes(raw, label=str(path))


def git(*args: str, text: bool = False) -> subprocess.CompletedProcess[Any]:
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=ROOT,
        capture_output=True,
        text=text,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        stderr = completed.stderr
        if isinstance(stderr, bytes):
            rendered = stderr.decode("utf-8", errors="replace")
        else:
            rendered = stderr
        raise D113ResealError(
            f"Git query failed ({' '.join(args)}): {rendered.strip()}"
        )
    return completed


def _git_text(*args: str) -> str:
    completed = git(*args, text=False)
    stdout = completed.stdout
    assert isinstance(stdout, bytes)
    try:
        return stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise D113ResealError("Git returned non-UTF-8 text") from exc


def _git_lines(*args: str) -> list[str]:
    value = _git_text(*args)
    return [] if not value else value.splitlines()


def git_blob(commit: str, relative: str) -> bytes:
    require(HEX40.fullmatch(commit) is not None, "Git blob commit is malformed")
    completed = git("cat-file", "blob", f"{commit}:{relative}", text=False)
    stdout = completed.stdout
    assert isinstance(stdout, bytes)
    return stdout


def _is_ancestor(ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=ROOT,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode not in {0, 1}:
        raise D113ResealError("cannot validate D1.13 ancestry")
    return completed.returncode == 0


def _working_bytes(relative: str) -> bytes:
    path = ROOT.joinpath(*PurePosixPath(relative).parts)
    require(
        path.is_file() and not path.is_symlink(),
        f"required file is not regular: {relative}",
    )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise D113ResealError(f"cannot read required file: {relative}") from exc
    return raw


def source_bytes(relative: str, *, source_head: str | None = None) -> bytes:
    selected = (
        _source_head(validate_optional_exec_013_boundary())
        if source_head is None
        else source_head
    )
    raw = git_blob(selected, relative)
    require(
        _working_bytes(relative) == raw,
        f"working bytes differ from source Git blob: {relative}",
    )
    return raw


def _single_parent(commit: str, *, label: str) -> str:
    row = _git_text("rev-list", "--parents", "-n", "1", commit).split()
    require(len(row) == 2 and row[0] == commit, f"{label} must be single-parent")
    return row[1]


def _validate_regular_blob(
    commit: str,
    relative: str,
    expected_oid: str | None = None,
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
        require(
            fields[2] == expected_oid,
            f"historical Git blob OID differs: {relative}",
        )


def _validate_d112_request(raw: bytes) -> dict[str, Any]:
    require(len(raw) == D112_REQUEST_BYTES, "immutable _012 request byte count differs")
    require(
        sha256(raw) == D112_REQUEST_RAW_SHA256,
        "immutable _012 raw SHA-256 differs",
    )
    request = _strict_json_bytes(raw, label=D112_REQUEST_PATH)
    require(
        raw == canonical_bytes(request),
        "immutable _012 request is not canonical JSON plus LF",
    )
    bindings = request.get("bindings")
    require(
        request.get("schema") == "trimem/development-tuning-branch-trigger/1.12"
        and request.get("request_id") == D112_REQUEST_ID
        and request.get("request_path") == D112_REQUEST_PATH
        and request.get("source_head") == D112_SOURCE_HEAD
        and request.get("request_sha256") == f"sha256:{D112_REQUEST_PAYLOAD_SHA256}"
        and request.get("phase") == "DEVELOPMENT_TUNING"
        and request.get("actual_execution_authorized") is False
        and request.get("external_execution_approval_received") is False
        and isinstance(bindings, Mapping)
        and bindings.get("freeze_sha256") == f"sha256:{D112_FREEZE_SHA256}"
        and bindings.get("d112_amendment_sha256")
        == f"sha256:{D112_AMENDMENT_SHA256}"
        and bindings.get("d112_inventory_sha256")
        == f"sha256:{D112_INVENTORY_SHA256}",
        "immutable _012 request identity or zero-authority binding differs",
    )
    activation_actuals = request.get("activation_actuals")
    pre_execution = request.get("pre_execution_actuals")
    require(
        isinstance(activation_actuals, Mapping)
        and all(value == 0 for value in activation_actuals.values())
        and isinstance(pre_execution, Mapping)
        and all(value == 0 for value in pre_execution.values()),
        "immutable _012 request contains nonzero pre-execution actuals",
    )
    return request


def validate_historical_d112() -> dict[str, Any]:
    """Verify D1.12 source, `_012`, and its frozen source from Git blobs."""

    require(
        _git_text("cat-file", "-t", D112_SOURCE_HEAD) == "commit"
        and _git_text("cat-file", "-t", D112_EXECUTION_HEAD) == "commit",
        "immutable D1.12 source or execution commit is unavailable",
    )
    require(
        _single_parent(D112_EXECUTION_HEAD, label="_012 execution") == D112_SOURCE_HEAD,
        "_012 execution is not the exact child of its frozen source",
    )
    changes = _git_lines(
        "diff-tree",
        "--no-ext-diff",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        D112_EXECUTION_HEAD,
    )
    require(changes == [f"A\t{D112_REQUEST_PATH}"], "_012 commit is not sentinel-only")
    _validate_regular_blob(
        D112_EXECUTION_HEAD,
        D112_REQUEST_PATH,
        expected_oid=D112_REQUEST_BLOB_OID,
    )
    require(
        not _git_lines("log", "--format=%H", D112_SOURCE_HEAD, "--", D112_REQUEST_PATH),
        "_012 existed in its activation-source history",
    )
    require(
        _git_lines(
            "log",
            "--format=%H",
            "--diff-filter=A",
            D112_EXECUTION_HEAD,
            "--",
            D112_REQUEST_PATH,
        )
        == [D112_EXECUTION_HEAD],
        "_012 does not have one immutable addition commit",
    )
    request_raw = git_blob(D112_EXECUTION_HEAD, D112_REQUEST_PATH)
    request = _validate_d112_request(request_raw)

    amendment_raw = git_blob(D112_SOURCE_HEAD, D112_AMENDMENT_PATH)
    inventory_raw = git_blob(D112_SOURCE_HEAD, D112_INVENTORY_PATH)
    freeze_raw = git_blob(D112_SOURCE_HEAD, D112_FREEZE_PATH)
    require(
        sha256(amendment_raw) == D112_AMENDMENT_SHA256
        and sha256(inventory_raw) == D112_INVENTORY_SHA256
        and sha256(freeze_raw) == D112_FREEZE_SHA256,
        "immutable D1.12 seal identity differs",
    )
    amendment = _strict_json_bytes(amendment_raw, label=D112_AMENDMENT_PATH)
    inventory = _strict_json_bytes(inventory_raw, label=D112_INVENTORY_PATH)
    freeze = _strict_json_bytes(freeze_raw, label=D112_FREEZE_PATH)
    require(
        amendment_raw == canonical_bytes(amendment)
        and inventory_raw == canonical_bytes(inventory)
        and freeze_raw == canonical_indented_bytes(freeze),
        "immutable D1.12 seal JSON is not canonical",
    )
    implementation = inventory.get("implementation_sha256")
    freeze_files = freeze.get("files")
    require(
        amendment.get("schema")
        == "trimem/development-exec-012-activation-amendment/1.0"
        and inventory.get("schema")
        == "trimem/development-exec-012-activation-inventory/1.0"
        and amendment.get("status")
        == "FROZEN_CREDENTIAL_FREE_READY_FOR_EXEC_012_REQUEST"
        and inventory.get("status")
        == "FROZEN_CREDENTIAL_FREE_READY_FOR_EXEC_012_REQUEST"
        and amendment.get("implementation_sha256") == implementation
        and isinstance(implementation, Mapping)
        and isinstance(freeze_files, Mapping),
        "immutable D1.12 artifact structure differs",
    )
    for relative, digest in implementation.items():
        require(
            isinstance(relative, str)
            and isinstance(digest, str)
            and HEX64.fullmatch(digest) is not None,
            "immutable D1.12 implementation hash is malformed",
        )
        raw = git_blob(D112_SOURCE_HEAD, relative)
        require(sha256(raw) == digest, f"D1.12 implementation blob differs: {relative}")
        require(
            freeze_files.get(relative) == {"bytes": len(raw), "sha256": digest},
            f"D1.12 freeze omits implementation blob: {relative}",
        )
    require(
        D112_REQUEST_PATH not in freeze_files,
        "active _012 request improperly entered its source freeze",
    )

    head = _git_text("rev-parse", "HEAD")
    require(
        HEX40.fullmatch(head) is not None and _is_ancestor(D112_EXECUTION_HEAD, head),
        "current D1.13 tree is not a descendant of immutable _012",
    )
    require(
        git_blob(head, D112_REQUEST_PATH) == request_raw
        and _working_bytes(D112_REQUEST_PATH) == request_raw,
        "current-tree _012 differs from its immutable execution blob",
    )
    for relative, expected_digest in HISTORICAL_D112_SHA256.items():
        historical = git_blob(D112_EXECUTION_HEAD, relative)
        require(
            sha256(historical) == expected_digest,
            f"immutable D1.12 historical blob differs: {relative}",
        )
        if relative in IMMUTABLE_D112_CURRENT_PATHS:
            require(
                _working_bytes(relative) == historical,
                f"immutable D1.12 current-tree file differs: {relative}",
            )

    return {
        "amendment_sha256": D112_AMENDMENT_SHA256,
        "execution_head": D112_EXECUTION_HEAD,
        "execution_parent": D112_SOURCE_HEAD,
        "freeze_sha256": D112_FREEZE_SHA256,
        "inventory_sha256": D112_INVENTORY_SHA256,
        "request_blob_oid": D112_REQUEST_BLOB_OID,
        "request_bytes": D112_REQUEST_BYTES,
        "request_id": D112_REQUEST_ID,
        "request_payload_sha256": D112_REQUEST_PAYLOAD_SHA256,
        "request_raw_sha256": D112_REQUEST_RAW_SHA256,
        "run_attempt": D112_RUN_ATTEMPT,
        "run_id": D112_RUN_ID,
        "sentinel_only": True,
        "source_head": request["source_head"],
        "status": "PASS",
    }


def _sentinel_parent(execution_head: str) -> str:
    return _single_parent(execution_head, label="_013 execution")


def validate_optional_exec_013_boundary() -> str | None:
    """Return the exact `_013` execution HEAD, or ``None`` at its source."""

    head = _git_text("rev-parse", "HEAD")
    require(HEX40.fullmatch(head) is not None, "current HEAD is malformed")
    additions = _git_lines(
        "log", "--format=%H", "--diff-filter=A", head, "--", D113_REQUEST_PATH
    )
    target = ROOT.joinpath(*PurePosixPath(D113_REQUEST_PATH).parts)
    if not additions:
        require(
            not target.exists() and not target.is_symlink(),
            "uncommitted or non-historical _013 request is forbidden",
        )
        return None
    require(additions == [head], "_013 must have exactly one addition at current HEAD")
    parent = _sentinel_parent(head)
    changes = _git_lines(
        "diff-tree",
        "--no-ext-diff",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        head,
    )
    require(changes == [f"A\t{D113_REQUEST_PATH}"], "_013 commit is not sentinel-only")
    _validate_regular_blob(head, D113_REQUEST_PATH)
    require(
        not _git_lines("log", "--format=%H", parent, "--", D113_REQUEST_PATH),
        "_013 exists in recovery-source history",
    )
    require(
        target.is_file() and not target.is_symlink(),
        "checked-out _013 is not regular",
    )
    trigger = _load_exact_module("trimem_development_trigger_d113", TRIGGER_PATH)
    validator = getattr(trigger, "validate_sentinel_commit", None)
    require(callable(validator), "D1.13 trigger lacks validate_sentinel_commit")
    try:
        validator(
            ROOT,
            head,
            expected_parent=parent,
            require_checked_out_head=True,
        )
    except Exception as exc:
        raise D113ResealError("D1.13 trigger rejected the _013 boundary") from exc
    return head


def _source_head(execution_head: str | None) -> str:
    return (
        _git_text("rev-parse", "HEAD")
        if execution_head is None
        else _sentinel_parent(execution_head)
    )


def verify_changed_path_coverage(source_head: str | None = None) -> tuple[str, ...]:
    selected = (
        _source_head(validate_optional_exec_013_boundary())
        if source_head is None
        else source_head
    )
    require(
        HEX40.fullmatch(selected) is not None
        and selected != D112_EXECUTION_HEAD
        and _is_ancestor(D112_EXECUTION_HEAD, selected),
        "D1.13 source is not a strict descendant of immutable _012",
    )
    completed = git(
        "diff",
        "--no-ext-diff",
        "--no-renames",
        "--name-status",
        "-z",
        D112_EXECUTION_HEAD,
        selected,
        text=False,
    )
    stdout = completed.stdout
    assert isinstance(stdout, bytes)
    pieces = [piece for piece in stdout.split(b"\0") if piece]
    require(len(pieces) % 2 == 0, "D1.13 changed-path stream is malformed")
    changes: dict[str, str] = {}
    try:
        for index in range(0, len(pieces), 2):
            status = pieces[index].decode("ascii", errors="strict")
            relative = pieces[index + 1].decode("utf-8", errors="strict")
            require(status in {"A", "M"}, f"D1.13 diff status is forbidden: {status}")
            require(relative not in changes, f"D1.13 path appears twice: {relative}")
            changes[relative] = status
    except UnicodeDecodeError as exc:
        raise D113ResealError("D1.13 changed path is not canonical UTF-8") from exc
    unexpected = sorted(set(changes) - ALLOWED_CHANGED_PATHS)
    require(
        not unexpected,
        "D1.13 paths escape the explicit seal: " + ", ".join(unexpected),
    )
    for relative, status in REQUIRED_CHANGED_PATHS.items():
        require(
            changes.get(relative) == status,
            f"required D1.13 change is missing or has wrong status: {relative}",
        )
    require(
        not _git_lines("log", "--format=%H", selected, "--", D113_REQUEST_PATH),
        "_013 exists in recovery-source history",
    )
    require(
        git_blob(selected, D112_REQUEST_PATH)
        == git_blob(D112_EXECUTION_HEAD, D112_REQUEST_PATH),
        "D1.13 source rewrites immutable _012",
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
        historical = git_blob(D112_EXECUTION_HEAD, relative)
        current = git_blob(source_head, relative)
        require(current == historical, f"D1.13 changed scientific payload: {relative}")
        require(
            _working_bytes(relative) == current,
            f"working scientific bytes differ: {relative}",
        )
        preserved[relative] = sha256(current)

    previous_request = _validate_d112_request(
        git_blob(D112_EXECUTION_HEAD, D112_REQUEST_PATH)
    )
    projection = {
        key: previous_request[key]
        for key in (
            "control_plane",
            "exact_model",
            "hard_caps",
            "phase",
            "scientific_workload",
        )
    }
    preserved["_012_scientific_projection"] = sha256(canonical_bytes(projection))
    return preserved


def _load_exact_module(name: str, expected_path: Path) -> Any:
    require(
        expected_path.is_file() and not expected_path.is_symlink(),
        f"required D1.13 module is absent or non-regular: {expected_path}",
    )
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        raise D113ResealError(f"cannot import required D1.13 module: {name}") from exc
    module_file = getattr(module, "__file__", None)
    require(
        isinstance(module_file, str)
        and Path(module_file).resolve() == expected_path.resolve(),
        f"D1.13 module resolved outside the repository: {name}",
    )
    return module


def validate_failure_replay() -> dict[str, Any]:
    """Delegate fixture shape to its gate module, then recheck authority facts."""

    gate = _load_exact_module("trimem_d113_gate_contract", GATE_CONTRACT_PATH)
    load_fixture = getattr(gate, "load_fixture", None)
    validate_fixture = getattr(gate, "validate_fixture", None)
    require(
        callable(load_fixture) and callable(validate_fixture),
        "D1.13 gate replay API differs",
    )
    expected_constants = {
        "EXPECTED_SOURCE_HEAD": D112_SOURCE_HEAD,
        "EXPECTED_EXECUTION_HEAD": D112_EXECUTION_HEAD,
        "EXPECTED_RUN_ID": D112_RUN_ID,
        "EXPECTED_RUN_ATTEMPT": D112_RUN_ATTEMPT,
    }
    for name, expected in expected_constants.items():
        require(
            getattr(gate, name, None) == expected,
            f"D1.13 gate constant differs: {name}",
        )
    require(
        getattr(gate, "EXPECTED_FAILURE_CLASSIFICATION", None)
        == GATE_FAILURE_CLASSIFICATION,
        "D1.13 direct failure classification differs",
    )
    try:
        result = validate_fixture(load_fixture(FIXTURE_PATH))
    except Exception as exc:
        raise D113ResealError("D1.13 failure replay rejected its fixture") from exc
    require(isinstance(result, Mapping), "D1.13 failure replay result is not an object")
    normalized = dict(result)
    # Canonical serialization also rejects non-string keys and non-finite values.
    canonical_bytes(normalized)
    require(
        normalized.get("source_head") == D112_SOURCE_HEAD
        and normalized.get("execution_head") == D112_EXECUTION_HEAD
        and type(normalized.get("execution_run_id")) is int
        and normalized.get("execution_run_id") == D112_RUN_ID
        and type(normalized.get("execution_run_attempt")) is int
        and normalized.get("execution_run_attempt") == D112_RUN_ATTEMPT
        and normalized.get("status") == "PASS",
        "D1.13 failure replay identity differs",
    )
    required_zero = {
        "model_api_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }
    require(
        all(normalized.get(key) == value for key, value in required_zero.items()),
        "D1.13 failure replay contains nonzero execution actuals",
    )
    protected = normalized.get(
        "protected_environment_entered",
        getattr(gate, "EXPECTED_PROTECTED_ENVIRONMENT_ENTERED", None),
    )
    require(
        protected is False,
        "D1.13 replay does not prove protected environment absence",
    )
    return normalized


def validate_active_contract(source_head: str) -> dict[str, Any]:
    trigger = _load_exact_module("trimem_development_trigger_d113", TRIGGER_PATH)
    required_constants = {
        "EXPECTED_BRANCH": EXPECTED_BRANCH,
        "EXPECTED_REF": EXPECTED_REF,
        "EXPECTED_REPOSITORY": EXPECTED_REPOSITORY,
        "EXPECTED_WORKFLOW_PATH": EXPECTED_WORKFLOW_PATH,
        "REQUEST_ID": D113_REQUEST_ID,
        "REQUEST_SCHEMA": D113_REQUEST_SCHEMA,
        "SENTINEL_PATH": D113_REQUEST_PATH,
        "REQUIRED_EXTERNAL_AUTHORIZATION": D113_REQUIRED_EXTERNAL_AUTHORIZATION,
        "EXPECTED_CONCURRENCY_GROUP": EXPECTED_CONCURRENCY_GROUP,
        "AMENDMENT_PATH": AMENDMENT_PATH.relative_to(ROOT).as_posix(),
        "AMENDMENT_SCHEMA": AMENDMENT_SCHEMA,
        "INVENTORY_PATH": INVENTORY_PATH.relative_to(ROOT).as_posix(),
        "INVENTORY_SCHEMA": INVENTORY_SCHEMA,
        "AMENDMENT_CLASSIFICATION": CLASSIFICATION,
        "AMENDMENT_STATUS": STATUS,
        "AMENDMENT_ENDPOINT": ENDPOINT,
    }
    for name, expected in required_constants.items():
        require(
            getattr(trigger, name, None) == expected,
            f"D1.13 trigger constant differs: {name}",
        )
    require(
        getattr(trigger, "PREVIOUS_SENTINEL_PATH", None) == D112_REQUEST_PATH
        and getattr(trigger, "PREVIOUS_SENTINEL_SHA256", None)
        == D112_REQUEST_RAW_SHA256
        and getattr(trigger, "PREVIOUS_SOURCE_HEAD", None) == D112_SOURCE_HEAD
        and getattr(trigger, "PREVIOUS_EXECUTION_HEAD", None) == D112_EXECUTION_HEAD
        and getattr(trigger, "PREVIOUS_RUN_ID", None) == D112_RUN_ID
        and getattr(trigger, "PREVIOUS_FAILURE_SUBTYPE", None) == FAILURE_SUBTYPE
        and getattr(trigger, "PREVIOUS_FAILURE_CLASSIFICATION", None)
        == GATE_FAILURE_CLASSIFICATION,
        "D1.13 trigger does not bind the exact spent _012 history",
    )
    trigger_raw = source_bytes(
        TRIGGER_PATH.relative_to(ROOT).as_posix(), source_head=source_head
    )
    try:
        ast.parse(
            trigger_raw.decode("utf-8", errors="strict"),
            filename=str(TRIGGER_PATH),
        )
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise D113ResealError("D1.13 trigger is not valid UTF-8 Python") from exc

    workflow = git_blob(source_head, EXPECTED_WORKFLOW_PATH).decode(
        "utf-8", errors="strict"
    )
    require("\r" not in workflow, "D1.13 benchmark workflow is not LF-only")
    require(
        workflow.count(f"      - {D113_REQUEST_PATH}\n") == 1
        and f"      - {D112_REQUEST_PATH}\n" not in workflow
        and f"group: {EXPECTED_CONCURRENCY_GROUP}" in workflow
        and "github.run_attempt == 1" in workflow
        and "scripts/trimem_development_trigger_d113.py" in workflow,
        "D1.13 benchmark workflow route differs",
    )
    return {
        "hosted_branch_runner_list_authority": "NOT_ASSUMED",
        "protected_execution_authorized": False,
        "request_creation_authority_only": True,
        "request_id": D113_REQUEST_ID,
        "request_path": D113_REQUEST_PATH,
        "source_validation": "GIT_BLOB_EXACT_AT_CHECK_TIME",
        "writer_time_runner_snapshot": "FROZEN_IN_REQUEST_BEFORE_SENTINEL",
        "bounded_self_hosted_attestation": "LIVE_BEFORE_MATERIALIZATION",
    }


def current_failure_record() -> dict[str, Any]:
    return {
        "classification": CLASSIFICATION,
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "failure_boundary": {
            "bounded_context_preflight": "SKIPPED",
            "branch_trigger_preflight": "FAILED",
            "frozen_serial_phase": "SKIPPED",
            "protected_environment_entered": False,
        },
        "failure_subtype": FAILURE_SUBTYPE,
        "observed_usage": dict(ZERO_ACTUALS),
        "pass_at_1": None,
        "performance_measured": False,
        "process_disposition": {
            "attempt_one_consumed": True,
            "attempt_two_allowed": False,
            "request_012_rerun_allowed": False,
            "request_013_execution_authorized": False,
        },
        "request": {
            "id": D112_REQUEST_ID,
            "path": D112_REQUEST_PATH,
            "payload_sha256": D112_REQUEST_PAYLOAD_SHA256,
            "raw_sha256": D112_REQUEST_RAW_SHA256,
            "source_head": D112_SOURCE_HEAD,
        },
        "root_cause": {
            "hosted_github_token_repository_runner_list_authorized": False,
            "recovery_rule": (
                "freeze runner readiness in the external writer before the sentinel; "
                "do not refresh repository runners with hosted GITHUB_TOKEN; require "
                "bounded live self-hosted and protected live attestations"
            ),
        },
        "schema": "trimem/development-exec-012-preprotected-failure/1.0",
        "scientific_status": "NOT_STARTED_ON_EXEC_012",
        "status": "IMMUTABLE_PUBLIC_GITHUB_EVIDENCE_REPLAYED",
        "workflow_run": {
            "attempt": D112_RUN_ATTEMPT,
            "conclusion": "failure",
            "head_sha": D112_EXECUTION_HEAD,
            "id": D112_RUN_ID,
            "source_head_sha": D112_SOURCE_HEAD,
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
        "request_id": D113_REQUEST_ID,
        "request_path": D113_REQUEST_PATH,
        "request_present_in_recovery_source": False,
        "schema": "trimem/development-exec-013-recovery/1.0",
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
        and status.get("DEV_SCIENTIFIC_STATUS") == "NOT_STARTED_ON_EXEC_013"
        and status.get("SCIENTIFIC_RESULT") == "NO_DEVELOPMENT_SCIENTIFIC_RESULT",
        "D1.13 current status differs",
    )
    require(
        readiness.get("historical_development_exec_012_preprotected_failure")
        == current_failure_record(),
        "D1.13 historical _012 failure record differs",
    )
    require(
        readiness.get("current_development_activation") == current_recovery_record(),
        "D1.13 current recovery activation differs",
    )
    require(
        isinstance(authority, Mapping)
        and authority.get("active_development_approval") is False
        and authority.get("approval_request_eligible") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("external_execution_approval_received") is False
        and authority.get("request_012_created") is True
        and authority.get("request_012_attempt_one_consumed") is True
        and authority.get("request_012_attempt_two_allowed") is False
        and authority.get("request_012_rerun_allowed") is False
        and authority.get("request_013_created") is False
        and authority.get("request_013_allowed_after_exact_remote_gates") is True
        and authority.get("request_013_authorized") is False
        and authority.get("fresh_execution_request_creation_authorized") is True
        and authority.get("required_external_authorization")
        == D113_REQUIRED_EXTERNAL_AUTHORIZATION
        and authority.get("recovery_request_id") == D113_REQUEST_ID
        and authority.get("recovery_request_path") == D113_REQUEST_PATH,
        "D1.13 development authority boundary differs",
    )


def _validate_implementation_sources(source_head: str) -> dict[str, str]:
    implementation: dict[str, str] = {}
    for relative in IMPLEMENTATION_PATHS:
        raw = git_blob(source_head, relative)
        require(
            _working_bytes(relative) == raw,
            f"D1.13 implementation is uncommitted: {relative}",
        )
        if relative.endswith(".py"):
            try:
                ast.parse(raw.decode("utf-8", errors="strict"), filename=relative)
            except (UnicodeDecodeError, SyntaxError) as exc:
                raise D113ResealError(
                    f"D1.13 Python source is invalid: {relative}"
                ) from exc
        implementation[relative] = sha256(raw)
    return implementation


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    execution_head = validate_optional_exec_013_boundary()
    source_head = _source_head(execution_head)
    changed_paths = verify_changed_path_coverage(source_head)
    historical = validate_historical_d112()
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
        "request_012_attempt_one_consumed": True,
        "request_012_attempt_two_allowed": False,
        "request_012_rerun_allowed": False,
        "request_013_created": False,
        "request_013_created_in_source": False,
        "request_013_creation_authorized": True,
        "request_013_execution_authorized": False,
        "request_013_request_creation_authorized": True,
        "required_external_authorization": D113_REQUIRED_EXTERNAL_AUTHORIZATION,
        "sentinel_contains_execution_authority": False,
    }
    recovery_contract = {
        "bounded_self_hosted_live_attestation": (
            "required before dependency or harness materialization"
        ),
        "hosted_github_token_repository_runner_list": "FORBIDDEN_AS_AUTHORITY",
        "protected_live_attestation": "required before cache-only service creation",
        "writer_time_runner_snapshot": (
            "collected before sentinel, embedded in request, and source-bound"
        ),
    }
    amendment = {
        "active_recovery": active,
        "authority_boundary": authority,
        "classification": CLASSIFICATION,
        "credential_free_failure_replay": replay,
        "endpoint": ENDPOINT,
        "exec_012_failure": current_failure_record(),
        "historical_d112": historical,
        "implementation_sha256": implementation,
        "preserved_scientific_sha256": science,
        "recovery_contract": recovery_contract,
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
    # Prove the expected documents are strict, finite, canonical JSON values.
    canonical_bytes(amendment)
    canonical_bytes(inventory)
    return amendment, inventory


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(value)
    fd, temp_name = tempfile.mkstemp(prefix=".trimem-d113-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def write_all() -> None:
    require(
        validate_optional_exec_013_boundary() is None,
        "D1.13 source artifacts cannot be rewritten after _013 creation",
    )
    amendment, inventory = build_artifacts()
    _write_json(AMENDMENT_PATH, amendment)
    _write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    execution_head = validate_optional_exec_013_boundary()
    amendment, inventory = build_artifacts()
    require(read_json(AMENDMENT_PATH) == amendment, "D1.13 amendment is stale")
    require(read_json(INVENTORY_PATH) == inventory, "D1.13 inventory is stale")
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
        "request_012_attempt_one_consumed": True,
        "request_012_rerun_allowed": False,
        "request_013_created": execution_head is not None,
        "request_013_execution_authorized": False,
        "research_freeze_sha256": sha256(
            source_bytes(FREEZE_PATH.relative_to(ROOT).as_posix())
        ),
        "status": "PASS",
        "task_arm_runs": 0,
        "total_usd": 0.0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build or verify the credential-free D1.13 exec-013 recovery seal"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            write_all()
        result = check_all()
    except (D113ResealError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
