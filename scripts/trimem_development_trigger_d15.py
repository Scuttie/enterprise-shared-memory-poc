"""Fail-closed one-time DEVELOPMENT_TUNING `_008` approval-cap trigger."""
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
REQUEST_ID = "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_008"
REQUEST_SCHEMA = "trimem/development-tuning-branch-trigger/1.7"
SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_008.json"
)
PREVIOUS_SENTINEL_PATH = (
    "artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_007.json"
)
PREVIOUS_RECEIPT_PATH = (
    "artifacts/trimem_v1/development_tuning_exec/exec-007/"
    "approval-schema-mismatch-receipt.json"
)
PREVIOUS_SENTINEL_SHA256 = (
    "90b7cbcc43a7b1a8ce5df8413ab48d386c500aaee3f167fa3cebc064eaa33ab7"
)
PREVIOUS_RECEIPT_SHA256 = (
    "43b7dc4470cfa7142253586d85eecf27b2191898c981dacc82cd51c74d01f5de"
)
PREVIOUS_SOURCE_HEAD = "553f7b44f4ab2762103ed06dbb87981c32ba2052"
PREVIOUS_EXECUTION_HEAD = "d9c8560087e681b619a4ea5313451fe64257a77e"
PREVIOUS_RUN_ID = 33_914_304_167
MODEL_ID = "gpt-5.4-mini-2026-03-17"
REQUIRED_EXTERNAL_AUTHORIZATION = (
    "TRIMEM_V1_DEVELOPMENT_TUNING_CANARY_CAP_RECOVERY_EXEC_APPROVED_ONCE"
)
EXPECTED_CONCURRENCY_GROUP = "trimem-v1-development-tuning-exec-008"
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
    "action_protocol_amendment_sha256": (
        "artifacts/trimem_v1/development_action_protocol_amendment.json"
    ),
    "approval_schema_sha256": "scripts/trimem_exec_approval.py",
    "approval_consumer_contract_sha256": (
        "artifacts/trimem_v1/development_approval_consumer_contract_fix.json"
    ),
    "arms_sha256": "configs/trimem_v1/arms.json",
    "benchmark_workflow_sha256": ".github/workflows/trimem-benchmark.yml",
    "benchmark_matrix_sha256": "scripts/trimem_benchmark_matrix.py",
    "benchmark_runner_sha256": "scripts/trimem_benchmark_run.py",
    "cost_plan_sha256": "configs/trimem_v1/cost_plan.json",
    "credential_module_sha256": (
        "src/enterprise_memory/providers/openai_credential.py"
    ),
    "credential_free_bundle_sha256": (
        "artifacts/trimem_v1/credential_free_e2e/credential_free_e2e_bundle.json"
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
    "function_tools_sha256": "src/enterprise_memory/trimem/function_tools.py",
    "gateway_contract_sha256": "src/enterprise_memory/trimem/gateway.py",
    "agent_runtime_sha256": "src/enterprise_memory/trimem/agent_runtime.py",
    "protocol_canary_sha256": "scripts/trimem_action_canary.py",
    "shared_phase_cap_validator_sha256": (
        "scripts/trimem_development_phase_cap.py"
    ),
    "secret_validator_sha256": "scripts/trimem_validate_openai_credential.py",
    "selection_plan_sha256": "configs/trimem_v1/selection_plan.json",
    "solve_output_budget_contract_sha256": (
        "configs/trimem_v1/solve_output_budget_contract.json"
    ),
    "tool_environment_lock_sha256": "configs/trimem_v1/tool_environment_lock.json",
    "key_binding_checker_sha256": "scripts/trimem_verify_openai_key_binding.py",
}
FREEZE_MEMBERSHIP_EXEMPT_PATHS = {
    "artifacts/trimem_v1/freeze.json",
    PREVIOUS_SENTINEL_PATH,
}
PRESERVED_SHA256 = {
    "configs/trimem_v1/arms.json": "7ecc15277cc9a9041befd4ae32f99b65da63009383b22701e0aecb407fe3906c",
    "configs/trimem_v1/development_manifest.json": "44e52137dad68618396c15d6b3c2221a683f89988e361efb2966e244ba230900",
    "configs/trimem_v1/grader_lock.json": "853d42e86c2caf1449f28bba9143741e3ccff5e75bbe790115a0d9c746014fbb",
    "artifacts/trimem_v1/grader_image_lock.json": "12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb",
    "configs/trimem_v1/model_lock.json": "a0a4811590d396c2bea4f0454c18c912d11579858947540a355407009a975922",
    "configs/trimem_v1/selection_plan.json": "dddc421120d16f241a2941afbd67190df4b3be6cefeab99e37437abf7133dcf4",
}
D17_AMENDMENT_PATH = (
    "artifacts/trimem_v1/development_approval_consumer_contract_fix.json"
)
D17_AMENDED_D16_PATHS = {
    ".github/workflows/trimem-benchmark.yml",
    "scripts/trimem_action_canary.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_development_trigger_d15.py",
}
D17_IMPLEMENTATION_PATHS = {
    ".github/workflows/ci-trimem.yml",
    ".github/workflows/trimem-benchmark.yml",
    "artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json",
    "artifacts/trimem_v1/readiness_requirements.json",
    "docs/TRIMEM_V1_SYSTEM.md",
    "reports/TRIMEM_MULTI_SWE_EVALUATION_CONTRACT.md",
    "reports/TRIMEM_MULTI_SWE_REPORT_SEMANTICS.md",
    "scripts/trimem_action_canary.py",
    "scripts/trimem_benchmark_matrix.py",
    "scripts/trimem_benchmark_run.py",
    "scripts/trimem_development_phase_cap.py",
    "scripts/trimem_development_trigger_d15.py",
    "scripts/trimem_development_trigger_preflight.py",
    "scripts/trimem_freeze.py",
    "scripts/trimem_verify_ready.py",
    "tests/unit/test_trimem_benchmark_readiness.py",
    "tests/unit/test_trimem_d15_credential_control.py",
    "tests/unit/test_trimem_d16_native_action.py",
    "tests/unit/test_trimem_d17_approval_cap_integration.py",
    "tests/unit/test_trimem_development_trigger.py",
    "tests/unit/test_trimem_multi_swe_evaluation_contract_lock.py",
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
        "historical _007 sentinel changed",
    )
    require(
        hashlib.sha256(
            commit_bytes(repository, source_head, PREVIOUS_RECEIPT_PATH)
        ).hexdigest()
        == PREVIOUS_RECEIPT_SHA256,
        "historical _007 receipt changed",
    )
    require(
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", PREVIOUS_EXECUTION_HEAD, source_head],
            cwd=repository,
            capture_output=True,
            check=False,
        ).returncode
        == 0,
        "source does not descend from immutable _007 execution",
    )
    previous = strict_json(commit_bytes(repository, source_head, PREVIOUS_RECEIPT_PATH))
    require(
        previous.get("workflow_run", {}).get("id") == PREVIOUS_RUN_ID
        and previous.get("workflow_run", {}).get("head_sha")
        == PREVIOUS_EXECUTION_HEAD
        and previous.get("failure_subtype")
        == "TRIMEM_DEV_PROTOCOL_CANARY_APPROVAL_SCHEMA_MISMATCH"
        and previous.get("scientific_status") == "NOT_STARTED"
        and previous.get("execution_accounting", {}).get(
            "model_generation_calls"
        )
        == 0
        and previous.get("execution_accounting", {}).get(
            "completed_task_arm_runs"
        )
        == 0,
        "historical _007 terminal evidence differs",
    )
    freeze_raw = commit_bytes(
        repository, source_head, "artifacts/trimem_v1/freeze.json"
    )
    freeze = strict_json(freeze_raw)
    files = freeze.get("files")
    require(isinstance(files, dict), "research freeze inventory is missing")
    require(SENTINEL_PATH not in files, "_008 entered the source freeze")
    amendment = strict_json(
        commit_bytes(
            repository,
            source_head,
            "artifacts/trimem_v1/development_action_protocol_amendment.json",
        )
    )
    implementation = amendment.get("implementation_sha256")
    require(
        amendment.get("schema")
        == "trimem/development-action-protocol-amendment/1.0"
        and amendment.get("classification")
        == "PRE_RESULT_ACTION_PROTOCOL_AND_CELL_CONTAINMENT_FIX"
        and isinstance(implementation, dict)
        and bool(implementation),
        "D1.6 amendment contract differs",
    )
    for path, expected in implementation.items():
        material_head = (
            PREVIOUS_EXECUTION_HEAD if path in D17_AMENDED_D16_PATHS else source_head
        )
        require(
            isinstance(path, str)
            and isinstance(expected, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
            and hashlib.sha256(commit_bytes(repository, material_head, path)).hexdigest()
            == expected,
            f"D1.6 implementation seal differs: {path}",
        )
    require(amendment.get("completed_scientific_cells_before_amendment") == 0,
            "D1.6 pre-result boundary differs")
    d17 = strict_json(commit_bytes(repository, source_head, D17_AMENDMENT_PATH))
    d17_implementation = d17.get("implementation_sha256")
    require(
        d17.get("schema")
        == "trimem/development-approval-consumer-contract-fix/1.0"
        and d17.get("classification")
        == "NON_SEMANTIC_APPROVAL_CONSUMER_CONTRACT_FIX"
        and d17.get("completed_scientific_cells_before_amendment") == 0
        and d17.get("historical_run", {}).get("id") == PREVIOUS_RUN_ID
        and d17.get("historical_run", {}).get("head_sha")
        == PREVIOUS_EXECUTION_HEAD
        and isinstance(d17_implementation, dict)
        and set(d17_implementation) == D17_IMPLEMENTATION_PATHS,
        "D1.7 approval-consumer amendment contract differs",
    )
    for path, expected in d17_implementation.items():
        require(
            isinstance(expected, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected) is not None
            and hashlib.sha256(commit_bytes(repository, source_head, path)).hexdigest()
            == expected,
            f"D1.7 implementation seal differs: {path}",
        )
    bindings: dict[str, str] = {}
    for name, path in BOUND_PATHS.items():
        raw = commit_bytes(repository, source_head, path)
        require(
            path in FREEZE_MEMBERSHIP_EXEMPT_PATHS
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
        "amendment_classification": "NON_SEMANTIC_APPROVAL_CONSUMER_CONTRACT_FIX",
        "authorization_semantics": (
            "The sentinel creates one run but protected execution requires a distinct "
            "run-bound external approval and matching OpenAI key commitment."
        ),
        "bindings": bindings,
        "branch_ref": EXPECTED_REF,
        "control_plane": {
            "exact_model_metadata_requests": 1,
            "protocol_canary_generation_requests": 1,
            "scientific_generation_request_cap": 1872,
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
            "exact_model_metadata_requests": 1,
            "model_generation_calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "official_grader_runs": 0,
            "benchmark_target_image_pulls": 0,
            "total_usd": 0.0,
        },
        "prohibited_actions": [
            "DEVELOPMENT_TUNING_EXEC_REQUEST_007_rerun_or_attempt_2",
            "DEVELOPMENT_TUNING_EXEC_REQUEST_009",
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
            "failure_label": "TRIMEM_DEV_PROTOCOL_CANARY_APPROVAL_SCHEMA_MISMATCH",
            "previous_request_id": "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_007",
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
            "protocol_canary_generation_calls": 1,
            "scientific_generation_call_cap": 1872,
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
    require(value == expected, "_008 request content differs")
    require(raw == canonical_bytes(expected, trailing_lf=True), "_008 bytes differ")
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
        "_008 already exists in history",
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
    require(not target.exists(), "_008 already exists")
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
