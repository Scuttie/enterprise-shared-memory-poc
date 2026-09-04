"""Fail-closed one-time DEVELOPMENT_TUNING `_006` branch trigger."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trimem_development_trigger_preflight import collect_remote_gate_evidence


EXPECTED_REPOSITORY = "Scuttie/enterprise-shared-memory-poc"
EXPECTED_REF = "refs/heads/codex/trimem-coder-v1"
EXPECTED_WORKFLOW_REF = (
    "Scuttie/enterprise-shared-memory-poc/.github/workflows/"
    "trimem-benchmark.yml@refs/heads/codex/trimem-coder-v1"
)
EXPECTED_PHASE = "DEVELOPMENT_TUNING"
REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_006"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.5"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_006.json"
)
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_005.json"
)
PREVIOUS_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-005/"
    "http-auth-error-receipt.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "97e2ce227418ace0db1edbf816391cdf0fda4f8d29359da4a3f81687f1aa19de"
)
PREVIOUS_RECEIPT_SHA256 = (
    "951f99472bdca153878f48ce1b18b11990e8125c15b47d529df508760939d42d"
)
PREVIOUS_SOURCE_HEAD = "5e80da790db0aa5b7cf1a8ce29020fedad7f6254"
PREVIOUS_EXECUTION_HEAD = "57db1a21fca3b036a64629c439ca196fb1606638"
PREVIOUS_RUN_ID = 33_859_839_836
MODEL_ID = "gpt-5.4-mini-2026-03-17"
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_AUTH_RECOVERY_EXEC_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-006"
REQUIRED_REMOTE_GATE_WORKFLOWS = (
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/ci-trimem-e2e.yml",
    ".github/workflows/ci-trimem-harness-lock.yml",
    ".github/workflows/ci-trimem-multi-swe-contract.yml",
    ".github/workflows/ci-trimem-dev-toolchain.yml",
)
DEVELOPMENT_APPROVAL_FIELDS = [
    "approved_git_commit",
    "approved_source_git_commit",
    "approved_freeze_sha256",
    "approved_phase",
    "approved_task_arm_runs",
    "approved_paid_model_call_cap",
    "approved_input_token_cap",
    "approved_output_token_cap",
    "approved_currency_hard_cap",
    "approved_grader_containers",
    "approved_workflow_run_id",
    "approved_workflow_run_attempt",
    "approved_legal_terms_acceptance",
    "approval_actor",
    "approval_timestamp",
    "approval_nonce",
    "approved_openai_key_commitment",
]
BOUND_PATHS = {
    "credential_control_amendment_sha256": (
        "artifacts/trimem_v1/development_credential_control_plane_amendment.json"
    ),
    "approval_schema_sha256": "scripts/trimem_exec_approval.py",
    "arms_sha256": "configs/trimem_v1/arms.json",
    "benchmark_workflow_sha256": ".github/workflows/trimem-benchmark.yml",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "cost_plan_sha256": "configs/trimem_v1/cost_plan.json",
    "credential_module_sha256": (
        "src/enterprise_memory/providers/openai_credential.py"
    ),
    "development_manifest_sha256": "configs/trimem_v1/development_manifest.json",
    "freeze_sha256": "artifacts/trimem_v1/freeze.json",
    "grader_lock_sha256": "configs/trimem_v1/grader_lock.json",
    "image_lock_sha256": "artifacts/trimem_v1/grader_image_lock.json",
    "m2_candidate_manifest_sha256": "configs/trimem_v1/m2_candidate_bundles.json",
    "model_access_checker_sha256": "scripts/trimem_openai_model_access_check.py",
    "model_lock_sha256": "configs/trimem_v1/model_lock.json",
    "previous_dev_receipt_sha256": PREVIOUS_RECEIPT_PATH,
    "previous_dev_request_sha256": PREVIOUS_SENTINEL_PATH,
    "provider_base_sha256": "src/enterprise_memory/providers/base.py",
    "provider_contract_sha256": (
        "src/enterprise_memory/providers/openai_responses.py"
    ),
    "secret_validator_sha256": "scripts/trimem_validate_openai_credential.py",
    "selection_plan_sha256": "configs/trimem_v1/selection_plan.json",
    "solve_output_budget_contract_sha256": (
        "configs/trimem_v1/solve_output_budget_contract.json"
    ),
    "tool_environment_lock_sha256": "configs/trimem_v1/tool_environment_lock.json",
    "key_binding_checker_sha256": "scripts/trimem_verify_openai_key_binding.py",
}
PRESERVED_SHA256 = {
    "configs/trimem_v1/arms.json": "7ecc15277cc9a9041befd4ae32f99b65da63009383b22701e0aecb407fe3906c",
    "configs/trimem_v1/development_manifest.json": "44e52137dad68618396c15d6b3c2221a683f89988e361efb2966e244ba230900",
    "configs/trimem_v1/grader_lock.json": "853d42e86c2caf1449f28bba9143741e3ccff5e75bbe790115a0d9c746014fbb",
    "artifacts/trimem_v1/grader_image_lock.json": "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb",
    "configs/trimem_v1/m2_candidate_bundles.json": "605accc70fd330ccee70a0a308ccc4a57ab4077875daadb23093c64f7c3e0875",
    "configs/trimem_v1/model_lock.json": "a0a4811590d396c2bea4f0454c18c912d11579858947540a355407009a975922",
    "configs/trimem_v1/selection_plan.json": "dddc421120d16f241a2941afbd67190df4b3be6cefeab99e37437abf7133dcf4",
    "configs/trimem_v1/solve_output_budget_contract.json": "49943aa6527bd8192c051ac72b2798f36976f66fa5aaff0d62525398494156e4",
    "configs/trimem_v1/tool_environment_lock.json": "399b9ab05ee427d17f9b815c96b57a8fafa36a8ad1806953c05a2ee51940b186",
    "src/enterprise_memory/trimem/runtime_lock.py": "77686f1d8b58cbabee85286e1d502495fae28b70b5279ec4dbe7133ea4440ae5",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")


class DevelopmentTriggerD15Error(ValueError):
    pass


# The benchmark runner consumes a stable exception name across trigger revisions.
DevelopmentTriggerError = DevelopmentTriggerD15Error


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DevelopmentTriggerD15Error(message)


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
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(
        raw.decode("utf-8", errors="strict"), object_pairs_hook=reject_duplicates
    )
    require(isinstance(value, dict), "JSON root is not an object")
    return value


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode:
        raise DevelopmentTriggerD15Error("git operation failed")
    return completed.stdout


def commit_bytes(repository: Path, commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise DevelopmentTriggerD15Error(f"missing committed material: {path}")
    return completed.stdout


def _validate_source(repository: Path, source_head: str) -> dict[str, str]:
    require(HEX40.fullmatch(source_head) is not None, "source HEAD is invalid")
    for path, expected in PRESERVED_SHA256.items():
        require(
            hashlib.sha256(commit_bytes(repository, source_head, path)).hexdigest()
            == expected,
            f"frozen scientific input changed: {path}",
        )
    require(
        hashlib.sha256(
            commit_bytes(repository, source_head, PREVIOUS_SENTINEL_PATH)
        ).hexdigest()
        == PREVIOUS_SENTINEL_SHA256,
        "historical _005 sentinel changed",
    )
    require(
        hashlib.sha256(
            commit_bytes(repository, source_head, PREVIOUS_RECEIPT_PATH)
        ).hexdigest()
        == PREVIOUS_RECEIPT_SHA256,
        "historical _005 receipt changed",
    )
    require(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", PREVIOUS_EXECUTION_HEAD, source_head],
            cwd=repository,
            capture_output=True,
            check=False,
        ).returncode
        == 0,
        "source does not descend from immutable _005 execution",
    )
    previous = strict_json(commit_bytes(repository, source_head, PREVIOUS_RECEIPT_PATH))
    require(
        previous.get("workflow_run", {}).get("id") == PREVIOUS_RUN_ID
        and previous.get("workflow_run", {}).get("head_sha")
        == PREVIOUS_EXECUTION_HEAD
        and previous.get("root_cause", {}).get("terminal_classification")
        == "HTTP_AUTH_ERROR"
        and previous.get("execution_accounting", {}).get(
            "completed_task_arm_runs"
        )
        == 0,
        "historical _005 terminal evidence differs",
    )
    freeze_raw = commit_bytes(
        repository, source_head, "artifacts/trimem_v1/freeze.json"
    )
    freeze = strict_json(freeze_raw)
    files = freeze.get("files")
    require(isinstance(files, dict), "research freeze inventory is missing")
    require(SENTINEL_PATH not in files, "_006 entered the source freeze")
    amendment = strict_json(
        commit_bytes(
            repository,
            source_head,
            "artifacts/trimem_v1/development_credential_control_plane_amendment.json",
        )
    )
    implementation = amendment.get("implementation_sha256")
    require(
        amendment.get("schema")
        == "trimem/development-credential-control-plane-amendment/1.0"
        and amendment.get("classification")
        == "NON_SEMANTIC_CREDENTIAL_CONTROL_PLANE_FIX"
        and isinstance(implementation, dict)
        and bool(implementation),
        "D1.5 amendment contract differs",
    )
    for path, expected in implementation.items():
        require(
            isinstance(path, str)
            and isinstance(expected, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
            and hashlib.sha256(commit_bytes(repository, source_head, path)).hexdigest()
            == expected,
            f"D1.5 implementation seal differs: {path}",
        )
    custody = amendment.get("evidence_custody_contract")
    require(
        isinstance(custody, dict)
        and custody.get("artifact_zip_digest_verified") is True
        and custody.get("plaintext_persisted_during_audit") is False
        and custody.get("file_path_type_size_sha256_verified") is True
        and custody.get("delete_secrets_only_after_external_audit") is True,
        "D1.5 evidence-custody contract differs",
    )
    bindings: dict[str, str] = {}
    for name, path in BOUND_PATHS.items():
        raw = commit_bytes(repository, source_head, path)
        require(
            path == "artifacts/trimem_v1/freeze.json"
            or files.get(path)
            == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
            f"research freeze does not bind {path}",
        )
        bindings[name] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return bindings


def _remote_gates(value: Mapping[str, Any], source_head: str) -> dict[str, Any]:
    require(value.get("source_head") == source_head, "remote gates source differs")
    require(value.get("all_required_workflows_passed") is True, "remote gates not green")
    rows = value.get("workflows")
    require(isinstance(rows, list), "remote gate workflow rows missing")
    require(
        tuple(row.get("workflow_path") for row in rows)
        == REQUIRED_REMOTE_GATE_WORKFLOWS,
        "remote gate workflow set/order differs",
    )
    for row in rows:
        require(
            row.get("head_sha") == source_head
            and row.get("status") == "completed"
            and row.get("conclusion") == "success"
            and row.get("run_attempt") == 1,
            "remote gate row is not exact-head success",
        )
    require(
        value.get("scientific_execution")
        == {
            "api_calls": 0,
            "grader_runs": 0,
            "model_calls": 0,
            "paid_model_calls": 0,
            "target_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "remote gates performed scientific work",
    )
    return dict(value)


def build_request(
    repository: Path,
    *,
    source_head: str,
    remote_gate_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    bindings = _validate_source(repository, source_head)
    gates = _remote_gates(remote_gate_evidence, source_head)
    development = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/development_manifest.json")
    )
    cost = strict_json(
        commit_bytes(repository, source_head, "configs/trimem_v1/cost_plan.json")
    )
    targets = [row["instance_id"] for row in development["targets"]]
    hard = cost["phase_hard_caps"]["DEVELOPMENT_TUNING"]
    payload = {
        "actual_execution_authorized": False,
        "amendment_classification": "NON_SEMANTIC_CREDENTIAL_CONTROL_PLANE_FIX",
        "authorization_semantics": (
            "The sentinel creates one run but protected execution requires a distinct "
            "run-bound external approval and matching OpenAI key commitment."
        ),
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "control_plane": {
            "exact_model_metadata_requests": 1,
            "model_generation_requests": 0,
            "model_tokens": 0,
            "precedes_benchmark_image_pull": True,
        },
        "exact_model": {
            "base_url": "https://api.openai.com/v1",
            "model_id": MODEL_ID,
            "reasoning_effort": "medium",
        },
        "hard_caps": hard,
        "phase": EXPECTED_PHASE,
        "pre_execution_actuals": {
            "completed_task_arm_runs": 0,
            "external_provider_requests": 8,
            "known_input_tokens": 54_620,
            "known_cached_input_tokens": 17_664,
            "known_output_tokens": 4_203,
            "known_reasoning_tokens": 1_485,
            "official_grader_runs": 0,
            "provider_usage_unavailable_requests": 2,
            "conservative_total_usd": 0.1016388,
        },
        "prohibited_actions": [
            "DEVELOPMENT_TUNING_EXEC_REQUEST_005_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_007",
            "HELDOUT_BENCHMARK",
            "component_ablation",
            "grader_smoke_rerun",
            "merge_tag_or_release",
            "model_or_reasoning_change",
            "target_or_candidate_change",
        ],
        "recovery_provenance": {
            "failed_execution_head": PREVIOUS_EXECUTION_HEAD,
            "failed_run_attempt": 1,
            "failed_run_id": PREVIOUS_RUN_ID,
            "failure_label": "TRIMEM_DEV_FIRST_DECOMPOSITION_HTTP_AUTH_ERROR",
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_005",
            "previous_request_path": PREVIOUS_SENTINEL_PATH,
            "previous_request_raw_sha256": "sha256:" + PREVIOUS_SENTINEL_SHA256,
            "completed_task_arm_runs": 0,
        },
        "remote_gate_evidence": gates,
        "request_id": REQUEST_ID,
        "request_path": SENTINEL_PATH,
        "required_external_approval_fields": DEVELOPMENT_APPROVAL_FIELDS,
        "required_external_authorization": REQUIRED_EXTERNAL_AUTHORIZATION,
        "requires_external_approval": True,
        "schema": REQUEST_SCHEMA,
        "scientific_workload": {
            "grader_containers": 72,
            "m2_candidate_streams": 4,
            "stream_order": [
                "M2-baseline",
                "M2-precision",
                "M2-recall",
                "M2-balanced",
                "M0",
                "M1",
            ],
            "target_order": targets,
            "task_arm_runs": 72,
        },
        "source_head": source_head,
        "workflow_path": ".github/workflows/trimem-benchmark.yml",
    }
    return {
        **payload,
        "request_sha256": "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest(),
    }


def validate_request(
    repository: Path, raw: bytes, *, source_head: str
) -> dict[str, Any]:
    value = strict_json(raw)
    gates = _remote_gates(value.get("remote_gate_evidence", {}), source_head)
    expected = build_request(
        repository, source_head=source_head, remote_gate_evidence=gates
    )
    require(value == expected, "_006 request content differs")
    require(raw == canonical_bytes(expected, trailing_lf=True), "_006 bytes differ")
    return value


def validate_sentinel_commit(
    repository: Path,
    after: str,
    *,
    expected_parent: str | None = None,
    require_checked_out_head: bool = True,
) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    require(HEX40.fullmatch(after) is not None, "trigger commit SHA is invalid")
    if require_checked_out_head:
        require(git(repository, "rev-parse", "HEAD").strip() == after, "HEAD differs")
    parents = git(repository, "rev-list", "--parents", "-n", "1", after).split()
    require(len(parents) == 2, "trigger must have one parent")
    parent = parents[1]
    if expected_parent is not None:
        require(parent == expected_parent, "trigger parent differs")
    changes = git(
        repository,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        after,
    ).splitlines()
    require(changes == [f"A\t{SENTINEL_PATH}"], "trigger commit is not sentinel-only")
    require(
        not git(repository, "log", "--format=%H", parent, "--", SENTINEL_PATH).strip(),
        "_006 already exists in history",
    )
    return validate_request(
        repository,
        commit_bytes(repository, after, SENTINEL_PATH),
        source_head=parent,
    )


def validate_branch_trigger(
    repository: Path, event_path: Path, *, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    environment = os.environ if environ is None else environ
    event = strict_json(event_path.read_bytes())
    require(environment.get("GITHUB_EVENT_NAME") == "push", "event is not push")
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "attempt must be one")
    require(environment.get("GITHUB_REPOSITORY") == EXPECTED_REPOSITORY, "repository differs")
    require(environment.get("GITHUB_REF") == EXPECTED_REF, "ref differs")
    require(environment.get("GITHUB_WORKFLOW_REF") == EXPECTED_WORKFLOW_REF, "workflow differs")
    require(event.get("forced") is False, "forced push forbidden")
    before, after = event.get("before"), event.get("after")
    require(environment.get("GITHUB_SHA") == after, "event after differs")
    require(environment.get("GITHUB_WORKFLOW_SHA") == after, "workflow SHA differs")
    request = validate_sentinel_commit(
        repository, after, expected_parent=before
    )
    live = collect_remote_gate_evidence(before)
    require(
        request["remote_gate_evidence"]["workflows"] == live["workflows"],
        "embedded remote gates differ from live runs",
    )
    return {
        "status": "PASS",
        "request_id": REQUEST_ID,
        "source_head": before,
        "trigger_commit": after,
        "model_calls": 0,
        "paid_model_calls": 0,
        "task_arm_runs": 0,
        "grader_containers": 0,
        "total_usd": 0.0,
    }


def write_request(repository: Path) -> dict[str, Any]:
    repository = repository.resolve(strict=True)
    require(
        git(repository, "symbolic-ref", "--quiet", "HEAD").strip() == EXPECTED_REF,
        "wrong branch",
    )
    require(
        not git(repository, "status", "--porcelain=v1", "--untracked-files=all").strip(),
        "request rendering requires a clean worktree",
    )
    source_head = git(repository, "rev-parse", "HEAD").strip()
    target = repository / SENTINEL_PATH
    require(not target.exists(), "_006 already exists")
    gates = collect_remote_gate_evidence(source_head)
    document = build_request(
        repository, source_head=source_head, remote_gate_evidence=gates
    )
    raw = canonical_bytes(document, trailing_lf=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "status": "WROTE_ZERO_AUTHORITY_SENTINEL",
        "path": SENTINEL_PATH,
        "source_head": source_head,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--event-path", type=Path)
    group.add_argument("--write-request", action="store_true")
    args = parser.parse_args()
    try:
        result = (
            write_request(args.repository)
            if args.write_request
            else validate_branch_trigger(args.repository, args.event_path)
        )
    except (DevelopmentTriggerD15Error, OSError, ValueError) as exc:
        print(str(exc))
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
