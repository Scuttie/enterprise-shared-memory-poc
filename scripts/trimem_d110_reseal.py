"""Build and verify the credential-free D1.10 research correction seal.

This utility is intentionally local-only.  It performs no network access,
model request, image pull, Docker operation, or official grader execution.
Historical DEVELOPMENT requests and evidence are checked against immutable Git
blobs; the current research seal is built from an explicit path allowlist.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = ROOT / (
    "artifacts/trimem_v1/development_grader_launch_stream_commit_amendment.json"
)
INVENTORY_PATH = ROOT / (
    "artifacts/trimem_v1/development_grader_launch_stream_commit_inventory.json"
)
READINESS_PATH = ROOT / "artifacts/trimem_v1/readiness_requirements.json"
FREEZE_PATH = ROOT / "artifacts/trimem_v1/freeze.json"
COMPANY_MANIFEST_PATH = ROOT / "COMPANY_HANDOFF_MANIFEST.json"

AMENDMENT_SCHEMA = "trimem/development-grader-launch-stream-commit-amendment/1.0"
INVENTORY_SCHEMA = "trimem/development-grader-launch-stream-commit-inventory/1.0"
STATUS = "FROZEN_CREDENTIAL_FREE_READY_FOR_DEV_APPROVAL"
CLASSIFICATION = "PRE_RESULT_GRADER_LAUNCH_AND_STREAM_COMMIT_CORRECTION"
ENDPOINT = "TRIMEM_V1_GRADER_LAUNCH_AND_STREAM_COMMIT_READY_FOR_DEV_APPROVAL"
EXECUTION_HEAD = "ea261f4fa783559d559e0df52800099ca98064f7"
CORRECTION_SOURCE_HEAD = "2d4a4535e68c8bfa923c93ef6d9d191ec579423a"
RUN_ID = 34_008_674_563
REQUEST_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_010.json"
)
REQUEST_SHA256 = "f42389df5a12c8f0d06bcd3eb2c97c69b0fde39667f8c880832e1c01bf998d9f"
TOOL_ENVIRONMENT_LOCK_PATH = "configs/trimem_v1/tool_environment_lock.json"
TOOL_ENVIRONMENT_SOURCE_AMENDMENTS = frozenset(
    {
        "src/enterprise_memory/trimem/git_workspace.py",
        "src/enterprise_memory/trimem/production_runtime.py",
    }
)
PRODUCT_COMPATIBILITY_PATHS = frozenset({"docs/STATUS.yaml"})
EXEC_010_SANITIZED_FIXTURE_PATH = (
    "tests/fixtures/trimem_d110/exec_010_sanitized.json"
)
EXEC_010_REGRESSION_TEST_PATH = "tests/unit/test_trimem_d110_atomic_resume.py"
EXEC_010_SAFE_PATCH_SHA256 = (
    "0513e328793ec2ffe063d5625d299daf635d6c98055b7d0ec0f726e0a076a3a6"
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")

STATUS_FIELDS = {
    "OFFICIAL_GRADER_SEMANTICS_AND_DISCRIMINATION": "ESTABLISHED_BY_P0_1_5",
    "OFFICIAL_GRADER_IMAGE_INTEGRITY": "ESTABLISHED",
    "OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH": "FAILED_ON_D1_9_EXEC_010",
    "OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START": "NOT_YET_ESTABLISHED",
    "PERFORMANCE": "NOT_MEASURED",
}

HISTORICAL_REQUEST_SHA256 = {
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_001.json": "7501c630a05ab0b87b9b510a72a5389f6ea7046dee6153b583e2833fa8e7e1db",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_002.json": "c81c57a5c93d4be9efdc971147191d8bc2e1bc2f06fe241e38ce36b6a4ee3f98",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_003.json": "3d6b4291f7a1ab8b72203e4756a2f7e4614c1139c9f6e0da74a3a949fa78ca56",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_004.json": "20bccf63d7f09e4130e7297bc0b1c07b4d97f15baefa77099b582e105874dd80",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_005.json": "97e2ce227418ace0db1edbf816391cdf0fda4f8d29359da4a3f81687f1aa19de",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_006.json": "9eb67d9b9ca5382a5f120108e12f767cdd51f421e1123f8cc74e18ec309cf01c",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_007.json": "90b7cbcc43a7b1a8ce5df8413ab48d386c500aaee3f167fa3cebc064eaa33ab7",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_008.json": "2eac68069e9a2cc760138eca5b9e6ae1d5438a97cd9e4918a496ab920cc584b7",
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_009.json": "3bf60d8b60ce2c902875593a0c10261c32bb6ed4961cd83703d926c33c5f968f",
    REQUEST_PATH: REQUEST_SHA256,
}

# Scientific inputs that D1.10 is not authorized to change.
PRESERVED_SCIENTIFIC_PATHS = (
    "artifacts/trimem_v1/adapter_failure_envelope_contract.json",
    "artifacts/trimem_v1/credential_free_e2e/dqn_frozen_checkpoint.json",
    "artifacts/trimem_v1/development_bounded_context_amendment.json",
    "artifacts/trimem_v1/development_bounded_context_inventory.json",
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
    "configs/trimem_v1/selected_m2.json",
    "configs/trimem_v1/selection_plan.json",
    "configs/trimem_v1/solve_output_budget_contract.json",
    "scripts/trimem_exec_approval.py",
    "scripts/trimem_context_roundtrip.py",
    "scripts/trimem_d19_reseal.py",
    "scripts/trimem_development_trigger_d19.py",
    "reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_009_BOUNDED_CONTEXT_FAILURE.md",
    "src/enterprise_memory/providers/base.py",
    "src/enterprise_memory/providers/openai_responses.py",
    "src/enterprise_memory/trimem/accounting.py",
    "src/enterprise_memory/trimem/agent_runtime.py",
    "src/enterprise_memory/trimem/arms.py",
    "src/enterprise_memory/trimem/checkpoint.py",
    "src/enterprise_memory/trimem/consolidation.py",
    "src/enterprise_memory/trimem/context_projection.py",
    "src/enterprise_memory/trimem/credential_free.py",
    "src/enterprise_memory/trimem/function_tools.py",
    "src/enterprise_memory/trimem/gateway.py",
    "src/enterprise_memory/trimem/grader.py",
    "src/enterprise_memory/trimem/policy.py",
    "src/enterprise_memory/trimem/ppr.py",
    "src/enterprise_memory/trimem/provider_output_contracts.py",
    "src/enterprise_memory/trimem/retrieval.py",
    "src/enterprise_memory/trimem/schema.py",
    "src/enterprise_memory/trimem/store.py",
    "src/enterprise_memory/trimem/working_graph.py",
    "src/enterprise_memory/trimem/workspace.py",
)

# Explicit and reviewable: no working-tree walk determines research authority.
# Keep this synchronized with trimem_freeze.py when an implementation path is
# deliberately added.
IMPLEMENTATION_PATHS = (
    ".gitattributes",
    ".github/workflows/ci.yml",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
    ".github/workflows/ci-trimem-grader-loader.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json",
    "artifacts/trimem_v1/readiness_requirements.json",
    "configs/trimem_v1/tool_environment_lock.json",
    "docs/TRIMEM_V1_SYSTEM.md",
    "reports/TRIMEM_D110_GRADER_LAUNCH_STREAM_COMMIT_CORRECTION.md",
    "scripts/make_handoff_manifest.py",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_d110_reseal.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_grader_smoke.py",
    "scripts/trimem_harness_lock.py",
    "scripts/trimem_multi_swe_contract.py",
    "scripts/trimem_multi_swe_entrypoint.py",
    "scripts/trimem_official_grader.py",
    "scripts/trimem_official_harness_loader.py",
    "scripts/trimem_official_harness_loader_preflight.py",
    "scripts/trimem_run_with_resume.py",
    "scripts/trimem_verify_ready.py",
    "scripts/trimem_verify_remote_custody.py",
    "src/enterprise_memory/trimem/git_workspace.py",
    "src/enterprise_memory/trimem/production_runtime.py",
    EXEC_010_SANITIZED_FIXTURE_PATH,
    "tests/unit/test_company_handoff_manifest.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_dev_toolchain_workflows.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_d19_trigger.py",
    "tests/unit/test_trimem_d110_official_harness_loader.py",
    "tests/unit/test_trimem_d110_resume_fail_closed.py",
    "tests/unit/test_trimem_d110_atomic_resume.py",
    "tests/unit/test_trimem_d110_checkout_custody.py",
    "tests/unit/test_trimem_d110_status_and_reseal.py",
    "tests/unit/test_trimem_grader_smoke_trigger.py",
    "tests/unit/test_trimem_grader_terminal_evidence.py",
    "tests/unit/test_trimem_harness_lock.py",
    "tests/unit/test_trimem_multi_prebuilt_evaluation.py",
    "tests/unit/test_trimem_multi_swe_probe_request.py",
    "tests/unit/test_trimem_multi_swe_preexec.py",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
    "tests/unit/test_trimem_production_runtime.py",
    "tests/unit/test_trimem_remote_custody.py",
)

CONTRACT_PATHS = {
    "official_grader_adapter_sha256": "scripts/trimem_official_grader.py",
    "loader_environment_contract_sha256": "scripts/trimem_official_harness_loader.py",
    "loader_preflight_sha256": "scripts/trimem_official_harness_loader_preflight.py",
    "multi_swe_loader_self_check_sha256": "scripts/trimem_multi_swe_entrypoint.py",
    "grader_lifecycle_sha256": "scripts/trimem_benchmark_run.py",
    "grader_evidence_envelope_sha256": "scripts/trimem_grader_smoke.py",
    "cell_commit_journal_sha256": "scripts/trimem_benchmark_run.py",
    "checkpoint_proof_schema_sha256": (
        "src/enterprise_memory/trimem/production_runtime.py"
    ),
    "tool_environment_lock_sha256": "configs/trimem_v1/tool_environment_lock.json",
    "resume_disposition_sha256": "scripts/trimem_run_with_resume.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "workflow_sha256": ".github/workflows/trimem-benchmark.yml",
    "loader_workflow_sha256": ".github/workflows/ci-trimem-grader-loader.yml",
    "failure_custody_sha256": "scripts/trimem_verify_remote_custody.py",
    "credential_free_bundle_sha256": (
        "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
    ),
}

D110_GENERATED_PATHS = frozenset(
    {
        AMENDMENT_PATH.relative_to(ROOT).as_posix(),
        INVENTORY_PATH.relative_to(ROOT).as_posix(),
        FREEZE_PATH.relative_to(ROOT).as_posix(),
    }
)


class D110ResealError(ValueError):
    """A D1.10 local reseal invariant failed."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def pretty_bytes(value: Any) -> bytes:
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


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def source_bytes(relative: str) -> bytes:
    target = ROOT / relative
    if target.is_symlink() or not target.is_file():
        raise D110ResealError(f"required regular source file is missing: {relative}")
    return target.read_bytes()


def source_record(relative: str) -> dict[str, Any]:
    raw = source_bytes(relative)
    return {"bytes": len(raw), "sha256": sha256(raw)}


def read_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise D110ResealError(f"duplicate JSON key: {path}:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_bytes().decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D110ResealError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise D110ResealError(f"JSON root is not an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pretty_bytes(value))


def git_blob(commit: str, relative: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise D110ResealError(f"missing immutable Git blob: {commit}:{relative}")
    return completed.stdout


def git_paths(commit: str, prefix: str) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", commit, "--", prefix],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise D110ResealError(f"cannot inventory immutable Git tree: {commit}:{prefix}")
    return tuple(
        token.decode("utf-8") for token in completed.stdout.split(b"\0") if token
    )


def verify_tracked_hygiene() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    )
    forbidden: list[str] = []
    for token in completed.stdout.split(b"\0"):
        if not token:
            continue
        relative = token.decode("utf-8")
        parts = relative.split("/")
        if (
            relative.endswith((".pyc", ".pyo"))
            or "__pycache__" in parts
            or any(part in {"build", "dist"} or part.endswith(".egg-info") for part in parts)
        ):
            forbidden.append(relative)
    if forbidden:
        raise D110ResealError(f"tracked build artifacts are forbidden: {forbidden}")


def verify_changed_path_coverage() -> tuple[str, ...]:
    """Require every committed D1.10 delta to belong to the explicit seal."""

    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LANG": "C",
        "LC_ALL": "C",
    }
    completed = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "diff",
            "--no-ext-diff",
            "--no-renames",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            "-z",
            EXECUTION_HEAD,
            "HEAD",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise D110ResealError("cannot enumerate committed D1.10 paths")
    try:
        changed = tuple(
            sorted(
                token.decode("utf-8")
                for token in completed.stdout.split(b"\0")
                if token
            )
        )
    except UnicodeDecodeError as exc:
        raise D110ResealError("committed D1.10 path is not UTF-8") from exc
    allowed = (
        set(IMPLEMENTATION_PATHS)
        | D110_GENERATED_PATHS
        | PRODUCT_COMPATIBILITY_PATHS
    )
    unexpected = sorted(set(changed) - allowed)
    if unexpected:
        raise D110ResealError(
            "committed D1.10 paths escape the explicit seal: "
            + ", ".join(unexpected)
        )
    return changed


def _immutable_history_tip(environment: Mapping[str, str]) -> str:
    """Use a strictly bound same-repository PR head, never a merge-tree guess."""

    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("GITHUB_EVENT_NAME") != "pull_request"
    ):
        return "HEAD"
    event_path = os.environ.get("GITHUB_EVENT_PATH", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        event = read_json(Path(event_path).resolve(strict=True))
    except (OSError, D110ResealError, ValueError) as exc:
        raise D110ResealError("cannot bind immutable history to PR event") from exc
    pull_request = event.get("pull_request")
    event_repository = event.get("repository")
    head = pull_request.get("head") if isinstance(pull_request, Mapping) else None
    base = pull_request.get("base") if isinstance(pull_request, Mapping) else None
    head_repository = head.get("repo") if isinstance(head, Mapping) else None
    if (
        not isinstance(event_repository, Mapping)
        or event_repository.get("full_name") != repository
        or not isinstance(head, Mapping)
        or not isinstance(base, Mapping)
        or not isinstance(head_repository, Mapping)
        or head_repository.get("full_name") != repository
        or HEX40.fullmatch(str(head.get("sha"))) is None
        or HEX40.fullmatch(str(base.get("sha"))) is None
    ):
        raise D110ResealError("PR history authority is not same-repository and canonical")
    head_sha = str(head["sha"])
    base_sha = str(base["sha"])
    observed = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "rev-list",
            "--parents",
            "-n",
            "1",
            "HEAD",
        ],
        cwd=ROOT,
        env=dict(environment),
        capture_output=True,
        check=False,
        text=True,
    )
    parts = observed.stdout.strip().split() if observed.returncode == 0 else []
    if parts and parts[0] == head_sha:
        return head_sha
    if len(parts) == 3 and set(parts[1:]) == {base_sha, head_sha}:
        return head_sha
    raise D110ResealError("checked-out HEAD is not the bound PR head or merge")


def verify_immutable_history_untouched(paths: tuple[str, ...]) -> None:
    """Reject touch-then-revert commits to immutable historical material."""

    protected = tuple(sorted(set(paths)))
    if not protected:
        raise D110ResealError("immutable history path set is empty")
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_NO_REPLACE_OBJECTS": "1",
        "LANG": "C",
        "LC_ALL": "C",
    }
    history_tip = _immutable_history_tip(environment)
    completed = subprocess.run(
        [
            "git",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "rev-list",
            "--full-history",
            f"{EXECUTION_HEAD}..{history_tip}",
            "--",
            *protected,
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise D110ResealError("cannot audit immutable D1.10 path history")
    if completed.stdout.strip():
        raise D110ResealError(
            "D1.10 commit history touched an immutable historical path"
        )


def verify_tool_environment_lock_amendment() -> None:
    """Permit only source-identity refreshes required by D1.10 hardening."""

    current = read_json(ROOT / TOOL_ENVIRONMENT_LOCK_PATH)
    try:
        historical = json.loads(
            git_blob(EXECUTION_HEAD, TOOL_ENVIRONMENT_LOCK_PATH).decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise D110ResealError("historical tool environment lock is invalid") from exc
    if not isinstance(historical, Mapping):
        raise D110ResealError("historical tool environment lock is not an object")
    current_static = {
        key: value for key, value in current.items() if key != "source_files"
    }
    historical_static = {
        key: value for key, value in historical.items() if key != "source_files"
    }
    current_sources = current.get("source_files")
    historical_sources = historical.get("source_files")
    if (
        current_static != historical_static
        or not isinstance(current_sources, Mapping)
        or not isinstance(historical_sources, Mapping)
        or set(current_sources) != set(historical_sources)
    ):
        raise D110ResealError(
            "D1.10 changed tool/runtime semantics or source inventory"
        )
    changed = {
        relative
        for relative in current_sources
        if current_sources[relative] != historical_sources[relative]
    }
    if changed != TOOL_ENVIRONMENT_SOURCE_AMENDMENTS:
        raise D110ResealError("D1.10 tool source-lock amendment scope differs")
    for relative, record in current_sources.items():
        raw = source_bytes(str(relative))
        if (
            not isinstance(record, Mapping)
            or set(record) != {"bytes", "sha256"}
            or record.get("bytes") != len(raw)
            or record.get("sha256") != sha256(raw)
        ):
            raise D110ResealError(f"tool source lock is stale: {relative}")


def verify_product_status_compatibility() -> None:
    """Allow only the mechanical workflow-count refresh; never research status."""

    historical = git_blob(EXECUTION_HEAD, "docs/STATUS.yaml")
    marker = (
        b"workflow_count: 73                     # structural tree inventory; "
        b"research readiness is separately sealed"
    )
    replacement = marker.replace(b"workflow_count: 73", b"workflow_count: 74")
    if historical.count(marker) != 1:
        raise D110ResealError("historical product workflow count is unexpected")
    expected = historical.replace(marker, replacement)
    observed = source_bytes("docs/STATUS.yaml")
    if b"\r" in observed.replace(b"\r\n", b""):
        raise D110ResealError("product STATUS contains a non-CRLF carriage return")
    if observed.replace(b"\r\n", b"\n") != expected:
        raise D110ResealError("product STATUS changed beyond workflow inventory count")


def verify_historical_boundaries() -> tuple[dict[str, str], dict[str, str]]:
    verify_tracked_hygiene()
    request_011 = ROOT / (
        "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_011.json"
    )
    if request_011.exists() or request_011.is_symlink():
        raise D110ResealError("_011 is prohibited and must not exist")
    ancestry = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", EXECUTION_HEAD],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if (
        ancestry.returncode != 0
        or ancestry.stdout.strip().split()
        != [EXECUTION_HEAD, CORRECTION_SOURCE_HEAD]
    ):
        raise D110ResealError("_010 execution head is not the exact sentinel-only child")
    sentinel_diff = subprocess.run(
        [
            "git",
            "diff-tree",
            "--no-commit-id",
            "--name-status",
            "-r",
            CORRECTION_SOURCE_HEAD,
            EXECUTION_HEAD,
        ],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    if (
        sentinel_diff.returncode != 0
        or sentinel_diff.stdout.splitlines() != [f"A\t{REQUEST_PATH}"]
    ):
        raise D110ResealError("_010 execution commit is not sentinel-only")
    descendant = subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXECUTION_HEAD, "HEAD"], cwd=ROOT
    )
    if descendant.returncode != 0:
        raise D110ResealError("D1.10 tree does not descend from immutable _010 head")
    historical_requests: dict[str, str] = {}
    for relative, expected in HISTORICAL_REQUEST_SHA256.items():
        observed = sha256(source_bytes(relative))
        if observed != expected or source_bytes(relative) != git_blob(EXECUTION_HEAD, relative):
            raise D110ResealError(f"historical request changed: {relative}")
        historical_requests[relative] = observed
    historical_evidence: dict[str, str] = {}
    for relative in git_paths(
        EXECUTION_HEAD, "artifacts/trimem_v1/development_tuning_exec"
    ):
        raw = source_bytes(relative)
        if raw != git_blob(EXECUTION_HEAD, relative):
            raise D110ResealError(f"historical execution evidence changed: {relative}")
        historical_evidence[relative] = sha256(raw)
    verify_immutable_history_untouched(
        tuple(HISTORICAL_REQUEST_SHA256)
        + tuple(historical_evidence)
        + tuple(PRESERVED_SCIENTIFIC_PATHS)
        + ("COMPANY_HANDOFF_MANIFEST.json",)
    )
    if source_bytes("COMPANY_HANDOFF_MANIFEST.json") != git_blob(
        EXECUTION_HEAD, "COMPANY_HANDOFF_MANIFEST.json"
    ):
        raise D110ResealError("product COMPANY_HANDOFF_MANIFEST.json was rewritten")
    verify_tool_environment_lock_amendment()
    verify_product_status_compatibility()
    for relative in PRESERVED_SCIENTIFIC_PATHS:
        if source_bytes(relative) != git_blob(EXECUTION_HEAD, relative):
            raise D110ResealError(f"D1.10 changed frozen scientific input: {relative}")
    return historical_requests, historical_evidence


def build_contracts() -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    contracts: dict[str, str] = {}
    documents: dict[str, dict[str, Any]] = {}
    for name, relative in CONTRACT_PATHS.items():
        record = source_record(relative)
        contracts[name] = record["sha256"]
        documents[name] = {
            "algorithm": "sha256",
            "preimage_kind": "raw-file-bytes",
            "source_path": relative,
            **record,
        }
    return contracts, documents


def current_failure_record() -> dict[str, Any]:
    return {
        "schema": "trimem/development-grader-launch-failure/1.0",
        "status": "IMMUTABLE_EXTERNAL_EVIDENCE_PRESERVED",
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "classification": CLASSIFICATION,
        "scientific_status": "INTERRUPTED_BEFORE_FIRST_TERMINAL_CELL",
        "failure_subtype": "GLOBAL_GRADER_INFRA_FAILURE",
        "grader_state": "GRADER_INFRA_FAILURE_BEFORE_CONTAINER",
        "workflow_run": {
            "id": RUN_ID,
            "attempt": 1,
            "head_sha": EXECUTION_HEAD,
            "source_head_sha": CORRECTION_SOURCE_HEAD,
            "conclusion": "failure",
        },
        "request": {
            "path": REQUEST_PATH,
            "raw_sha256": REQUEST_SHA256,
            "attempt_one_consumed": True,
            "rerun_allowed": False,
            "attempt_two_allowed": False,
        },
        "failure_boundary": {
            "stream": "M2-baseline",
            "target": "swebench_verified--django__django-16100",
            "context_projections_bounded": 8,
            "context_projections_total": 8,
            "decomposition_calls": 1,
            "solve_calls": 8,
            "partial_patch_nonempty": True,
            "per_subtask_step_cap_reached": True,
            "grader_adapter_invoked": True,
            "exact_child_python_exit_code": 127,
            "stderr_class": "LIBPYTHON3_11_SO_1_0_UNAVAILABLE",
            "container_started": False,
            "official_grader_runs": 0,
            "task_arm_cursor": 0,
            "cell_terminal_records": 0,
            "public_aggregate_present": False,
        },
        "process_disposition": {
            "first_disposition": "GLOBAL_GRADER_INFRA_FAILURE",
            "resume_eligible": False,
            "resume_started": False,
        },
        "observed_usage": {
            "scientific_model_calls": 9,
            "decomposition_calls": 1,
            "solve_calls": 8,
            "extraction_calls": 0,
            "protocol_canary_calls": 1,
            "paid_model_calls": 10,
            "terminal_task_arm_runs": 0,
            "official_grader_runs": 0,
            "grader_containers": 0,
            "total_usd": "0.051215550000",
        },
        "evidence_custody": {
            "status": "TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS",
            "public_artifact_present": False,
            "restricted_encrypted": {
                "id": 9_982_016_857,
                "name": "trimem-benchmark-restricted-encrypted",
                "size_in_bytes": 10_079_456,
                "digest": "sha256:7a76d6626206e3174b5c6f0ee8cfdd3bf571b54fe49064a6714ed82ecc1bead8",
            },
            "evidence_inventories": {
                "id": 9_982_017_330,
                "name": "trimem-benchmark-evidence-inventories",
                "size_in_bytes": 7_804,
                "digest": "sha256:3bf1856ffd385dac10daac17d006ed5ef037c75817c1b1fba76cd0f12d8c0433",
            },
            "plaintext_inventory": {
                "root_sha256": "dbecd53c1673a006f90e6350370cb6200b00230e803a6b69aca5fd4d0d7f7132",
                "files": 176,
                "bytes": 9_828_804,
            },
        },
        "performance_measured": False,
        "pass_at_1": None,
    }


def validate_exec_010_sanitized_fixture() -> dict[str, Any]:
    """Validate the non-sensitive regression derivative of restricted _010.

    This fixture does not reproduce or disclose the historical model patch.  It
    binds the public artifact identities and observed boundary to an exact safe
    patch whose bytes are suitable for exercising the production-shaped
    pre-container failure path without credentials, images, or a grader.
    """

    fixture = read_json(ROOT / EXEC_010_SANITIZED_FIXTURE_PATH)
    historical = current_failure_record()
    boundary = historical["failure_boundary"]
    expected_boundary = {
        **boundary,
        "grader_containers": historical["observed_usage"]["grader_containers"],
    }
    expected_provenance = {
        "correction_source_head": CORRECTION_SOURCE_HEAD,
        "execution_head": EXECUTION_HEAD,
        "request_path": REQUEST_PATH,
        "request_raw_sha256": REQUEST_SHA256,
        "repository": "Scuttie/enterprise-shared-memory-poc",
        "workflow_run_attempt": 1,
        "workflow_run_id": RUN_ID,
    }
    expected_custody = {
        key: historical["evidence_custody"][key]
        for key in (
            "status",
            "restricted_encrypted",
            "evidence_inventories",
            "plaintext_inventory",
        )
    }
    if (
        fixture.get("schema")
        != "trimem/d110-exec-010-sanitized-regression-fixture/1.0"
        or fixture.get("status") != "SANITIZED_CREDENTIAL_FREE_REGRESSION_ONLY"
        or fixture.get("provenance") != expected_provenance
        or fixture.get("historical_failure_boundary") != expected_boundary
        or fixture.get("evidence_custody") != expected_custody
        or fixture.get("historical_usage") != historical["observed_usage"]
        or fixture.get("grader_target")
        != {
            "expected_digest": (
                "sha256:768b2dd7ecee6c437c64441966687c4a1597230169c7c929e14374660a2ecdab"
            ),
            "image": (
                "swebench/sweb.eval.x86_64.django_1776_django-16100@"
                "sha256:768b2dd7ecee6c437c64441966687c4a1597230169c7c929e14374660a2ecdab"
            ),
        }
        or fixture.get("credential_free_replay_actuals")
        != {
            "benchmark_image_pulls": 0,
            "model_api_calls": 0,
            "model_generation_calls": 0,
            "official_grader_executions": 0,
            "paid_model_calls": 0,
            "total_usd": 0,
        }
        or fixture.get("sanitization")
        != {
            "historical_patch_content_included": False,
            "purpose": (
                "Deterministic non-sensitive substitute preserving the exact "
                "non-empty partial-patch transport and hash boundary only"
            ),
            "raw_historical_evidence_included": False,
            "source_kind": (
                "SANITIZED_DERIVATIVE_NOT_HISTORICAL_RAW_EVIDENCE"
            ),
        }
    ):
        raise D110ResealError("sanitized _010 provenance fixture differs")

    patch = fixture.get("safe_partial_patch")
    if not isinstance(patch, Mapping):
        raise D110ResealError("sanitized _010 partial patch is absent")
    try:
        encoded = str(patch.get("content_base64")).encode("ascii")
        raw_patch = base64.b64decode(encoded, validate=True)
        text_patch = str(patch.get("utf8_text")).encode("utf-8")
    except (UnicodeEncodeError, ValueError) as exc:
        raise D110ResealError("sanitized _010 partial patch is malformed") from exc
    if (
        not raw_patch
        or raw_patch != text_patch
        or len(raw_patch) != patch.get("bytes")
        or sha256(raw_patch) != EXEC_010_SAFE_PATCH_SHA256
        or patch.get("sha256") != EXEC_010_SAFE_PATCH_SHA256
        or patch.get("path") != "sanitized-inputs/exec-010.partial.patch"
        or patch.get("media_type") != "text/x-diff; charset=utf-8"
        or patch.get("historical_patch_bytes_copied") is not False
    ):
        raise D110ResealError("sanitized _010 partial-patch byte binding differs")

    expected = fixture.get("expected_regression")
    if not isinstance(expected, Mapping) or expected != {
        "banned_legacy_diagnostic": (
            "task-arm cap ledger state does not match the stream cursor"
        ),
        "cell_result_count": 0,
        "first_disposition": "GLOBAL_GRADER_INFRA_FAILURE",
        "grader_delegate_calls": 1,
        "ledger_status": "RESERVED",
        "process_count": 1,
        "process_stderr_utf8": (
            "/opt/trimem-official/python/bin/python: error while loading shared "
            "libraries: libpython3.11.so.1.0: cannot open shared object file: "
            "No such file or directory\n"
        ),
        "process_stdout_utf8": (
            '{"error":"official grader execution failed","process_disposition":'
            '"GLOBAL_GRADER_INFRA_FAILURE","status":"FAIL"}\n'
        ),
        "resume_eligible": False,
        "resume_started": False,
        "task_arm_cursor": 0,
        "terminal_task_arm_runs": 0,
    }:
        raise D110ResealError("sanitized _010 regression expectation differs")
    return fixture


def build_amendment(
    *,
    historical_requests: Mapping[str, str],
    historical_evidence: Mapping[str, str],
    implementation: Mapping[str, str],
    contracts: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema": AMENDMENT_SCHEMA,
        "status": STATUS,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "current_status": dict(STATUS_FIELDS),
        "historical_execution": current_failure_record(),
        "historical_request_sha256": dict(sorted(historical_requests.items())),
        "historical_execution_evidence_sha256": dict(
            sorted(historical_evidence.items())
        ),
        "causal_boundary": {
            "correction_kind": "DETERMINISTIC_PRE_RESULT_INFRASTRUCTURE_CONTRACT",
            "terminal_scientific_cells_before_correction": 0,
            "official_grader_runs_before_correction": 0,
            "pass_at_1_existed_before_correction": False,
            "model_or_reasoning_changed": False,
            "arm_or_memory_policy_changed": False,
            "checkpoint_proof_schema_hardened": True,
            "scientific_runtime_or_memory_policy_changed": False,
        },
        "correction_contracts": {
            "hermetic_exact_python_loader": True,
            "loader_preflight_before_credentials_models_images_and_reservation": True,
            "explicit_grader_lifecycle": True,
            "atomic_cell_commit_journal": "trimem/cell-commit-journal/1.0",
            "failure_aware_resume": True,
            "failed_campaign_public_artifact_optional": True,
            "restricted_and_inventory_remote_custody_required": True,
            "sanitized_exec_010_regression_fixture": (
                "trimem/d110-exec-010-sanitized-regression-fixture/1.0"
            ),
        },
        "scientific_scope_lock": {
            "model_id": "gpt-5.4-mini-2026-03-17",
            "reasoning_effort": "medium",
            "development_targets": 12,
            "heldout_targets": 27,
            "streams": [
                "M2-baseline",
                "M2-precision",
                "M2-recall",
                "M2-balanced",
                "M0",
                "M1",
            ],
            "task_arm_runs": 72,
            "m2_selection_rule_changed": False,
            "memory_parameters_changed": False,
            "output_token_pools_changed": False,
            "development_hard_caps_changed": False,
            "grader_or_image_revision_changed": False,
            "prompt_tool_parser_or_limits_changed": False,
            "runtime_lock_manifest_changed": False,
            "tool_source_identity_amendment": sorted(
                TOOL_ENVIRONMENT_SOURCE_AMENDMENTS
            ),
        },
        "implementation_sha256": dict(sorted(implementation.items())),
        "contracts": dict(sorted(contracts.items())),
        "credential_free_bundle_scope": (
            "REHASHED_BYTE_STABLE_EXISTING_SOURCE_TO_TARGET_EVIDENCE; "
            "NOT_D1_10_LOADER_OR_CELL_COMMIT_REHEARSAL"
        ),
        "credential_free_correction_actuals": {
            "model_api_calls": 0,
            "model_generation_calls": 0,
            "paid_model_calls": 0,
            "benchmark_image_pulls": 0,
            "official_grader_executions": 0,
            "total_usd": 0,
        },
        "authority_boundary": {
            "historical_failed_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_010",
            "historical_failed_request_path": REQUEST_PATH,
            "request_010_rerun_allowed": False,
            "request_010_attempt_two_allowed": False,
            "request_011_created": False,
            "fresh_execution_request": "NOT_CREATED_PENDING_EXPLICIT_APPROVAL",
            "fresh_execution_request_creation_authorized": False,
            "fresh_execution_request_requires_explicit_sentinel_authority": True,
            "fresh_dev_execution_approval_required": True,
            "dev_execution_authorized": False,
            "heldout_authorized": False,
            "ablation_authorized": False,
            "merge_tag_release_authorized": False,
        },
        "research_freeze_binding": (
            "BOUND_BY_RAW_SHA256_OF_artifacts/trimem_v1/freeze.json_"
            "AFTER_NON_RECURSIVE_ALLOWLIST_GENERATION"
        ),
    }


def build_inventory(
    *,
    historical_requests: Mapping[str, str],
    historical_evidence: Mapping[str, str],
    implementation: Mapping[str, str],
    contracts: Mapping[str, str],
    documents: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    company_raw = source_bytes("COMPANY_HANDOFF_MANIFEST.json")
    company = read_json(COMPANY_MANIFEST_PATH)
    fixture_record = source_record(EXEC_010_SANITIZED_FIXTURE_PATH)
    test_record = source_record(EXEC_010_REGRESSION_TEST_PATH)
    return {
        "schema": INVENTORY_SCHEMA,
        "status": STATUS,
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "implementation_sha256": dict(sorted(implementation.items())),
        "contracts": dict(sorted(contracts.items())),
        "contract_documents": dict(sorted(documents.items())),
        "credential_free_bundle_scope": (
            "REHASHED_BYTE_STABLE_EXISTING_SOURCE_TO_TARGET_EVIDENCE; "
            "NOT_D1_10_LOADER_OR_CELL_COMMIT_REHEARSAL"
        ),
        "historical_request_sha256": dict(sorted(historical_requests.items())),
        "historical_execution_evidence_sha256": dict(
            sorted(historical_evidence.items())
        ),
        "exec_010_sanitized_regression": {
            "fixture": {
                "path": EXEC_010_SANITIZED_FIXTURE_PATH,
                "schema": (
                    "trimem/d110-exec-010-sanitized-regression-fixture/1.0"
                ),
                **fixture_record,
            },
            "historical_sensitive_patch_included": False,
            "test": {
                "path": EXEC_010_REGRESSION_TEST_PATH,
                **test_record,
            },
        },
        "company_handoff_inventory": {
            "manifest_rewritten": False,
            "manifest_bytes": len(company_raw),
            "manifest_raw_sha256": sha256(company_raw),
            "manifest_self_hash": company.get("manifest_hash"),
            "product_manifest_authority": company.get("manifest_scope"),
            "product_hash_basis": company.get("hash_basis"),
            "rejected_if_tracked": company.get("rejected_if_tracked"),
            "research_state_authority": "artifacts/trimem_v1/freeze.json",
            "research_hash_basis": "explicit allowlist; no live tree walk",
        },
        "credential_free_gate": {
            "loader_environment_tests_required": True,
            "loader_preflight_required": True,
            "exec_010_regression_required": True,
            "cell_commit_crash_matrix_required": True,
            "resume_disposition_tests_required": True,
            "full_72_cell_fake_campaign_required": True,
            "failure_path_custody_required": True,
            "model_api_calls": 0,
            "paid_model_calls": 0,
            "official_graders": 0,
            "benchmark_images": 0,
            "total_usd": 0,
        },
        "authority_boundary": {
            "historical_failed_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_010",
            "historical_failed_request_path": REQUEST_PATH,
            "request_010_final": True,
            "request_010_rerun_allowed": False,
            "request_010_attempt_two_allowed": False,
            "request_011_created": False,
            "fresh_execution_request": "NOT_CREATED_PENDING_EXPLICIT_APPROVAL",
            "fresh_execution_request_creation_authorized": False,
            "fresh_execution_request_requires_explicit_sentinel_authority": True,
            "fresh_dev_execution_approval_required": True,
            "dev_execution_authorized": False,
        },
    }


def validate_readiness() -> None:
    readiness = read_json(READINESS_PATH)
    status = readiness.get("current_status")
    authority = readiness.get("development_authorization_boundary")
    if not (
        isinstance(status, Mapping)
        and "OFFICIAL_GRADER_VIABILITY" not in status
        and all(status.get(key) == value for key, value in STATUS_FIELDS.items())
        and status.get("ENDPOINT") == ENDPOINT
        and status.get("DEV_APPROVAL_ALLOWED") == "YES"
        and status.get("DEV_EXECUTION_ALLOWED") == "NO"
        and status.get("CLASSIFICATION") == CLASSIFICATION
        and readiness.get("current_development_execution_failure")
        == current_failure_record()
        and isinstance(authority, Mapping)
        and authority.get("amendment_classification") == CLASSIFICATION
        and authority.get("amendment_evidence_path")
        == AMENDMENT_PATH.relative_to(ROOT).as_posix()
        and authority.get("approval_request_eligible") is True
        and authority.get("active_development_approval") is False
        and authority.get("development_execution_authorized") is False
        and authority.get("request_010_attempt_one_consumed") is True
        and authority.get("request_010_rerun_allowed") is False
        and authority.get("request_010_attempt_two_allowed") is False
        and authority.get("request_011_created") is False
        and authority.get("historical_failed_request_id")
        == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_010"
        and authority.get("historical_failed_request_path") == REQUEST_PATH
        and authority.get("fresh_execution_request")
        == "NOT_CREATED_PENDING_EXPLICIT_APPROVAL"
        and authority.get("fresh_execution_request_creation_authorized") is False
        and authority.get(
            "fresh_execution_request_requires_explicit_sentinel_authority"
        )
        is True
        and "recovery_request_id" not in authority
        and "recovery_request_path" not in authority
        and authority.get("fresh_dev_execution_approval_required") is True
    ):
        raise D110ResealError("readiness D1.10 status/authority boundary differs")


def build_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    verify_changed_path_coverage()
    historical_requests, historical_evidence = verify_historical_boundaries()
    validate_readiness()
    validate_exec_010_sanitized_fixture()
    implementation = {
        relative: sha256(source_bytes(relative)) for relative in IMPLEMENTATION_PATHS
    }
    contracts, documents = build_contracts()
    amendment = build_amendment(
        historical_requests=historical_requests,
        historical_evidence=historical_evidence,
        implementation=implementation,
        contracts=contracts,
    )
    inventory = build_inventory(
        historical_requests=historical_requests,
        historical_evidence=historical_evidence,
        implementation=implementation,
        contracts=contracts,
        documents=documents,
    )
    return amendment, inventory


def write_all() -> None:
    amendment, inventory = build_artifacts()
    write_json(AMENDMENT_PATH, amendment)
    write_json(INVENTORY_PATH, inventory)
    import trimem_freeze

    trimem_freeze.write_freeze(ROOT)


def check_all() -> dict[str, Any]:
    amendment, inventory = build_artifacts()
    if read_json(AMENDMENT_PATH) != amendment:
        raise D110ResealError("D1.10 amendment is stale")
    if read_json(INVENTORY_PATH) != inventory:
        raise D110ResealError("D1.10 inventory is stale")
    import trimem_freeze

    trimem_freeze.check_freeze(ROOT)
    freeze_raw = source_bytes("artifacts/trimem_v1/freeze.json")
    return {
        "status": "PASS",
        "classification": CLASSIFICATION,
        "endpoint": ENDPOINT,
        "historical_requests": len(HISTORICAL_REQUEST_SHA256),
        "research_freeze_sha256": sha256(freeze_raw),
        "credential_free_bundle_sha256": amendment["contracts"][
            "credential_free_bundle_sha256"
        ],
        "company_handoff_inventory_sha256": inventory[
            "company_handoff_inventory"
        ]["manifest_raw_sha256"],
        "model_api_calls": 0,
        "paid_model_calls": 0,
        "official_graders": 0,
        "benchmark_images": 0,
        "total_usd": 0,
        "request_011_created": False,
        "fresh_dev_execution_approval_required": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.write:
            write_all()
        result = check_all()
    except (D110ResealError, OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"error": str(exc), "status": "FAIL"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
