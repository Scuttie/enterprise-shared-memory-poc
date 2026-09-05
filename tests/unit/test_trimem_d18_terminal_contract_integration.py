from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace
from typing import Any, Mapping

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_benchmark_run as benchmark_run  # noqa: E402
import trimem_development_trigger_d18 as development_trigger  # noqa: E402
import trimem_public_artifact as public_artifact  # noqa: E402
from trimem_exec_approval import (  # noqa: E402
    build_external_approval_document,
)
from enterprise_memory.trimem.scientific_terminal import (  # noqa: E402
    SCIENTIFIC_EXECUTION_STATUS,
    SCIENTIFIC_LEDGER_TERMINAL_STATUS,
    ScientificTerminalContractError,
    validate_result_ledger_pair,
    validate_result_request_statuses,
    validate_scientific_terminal_ledger_row,
    validate_scientific_terminal_result,
)


RESOLVED_COUNTS = {
    "M2-baseline": 3,
    "M2-precision": 4,
    "M2-recall": 5,
    "M2-balanced": 5,
    "M0": 2,
    "M1": 3,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def _copy_repository_input(repository: Path, relative: str) -> None:
    source = ROOT / relative
    target = repository / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _initialize_disposable_execution_repository(
    repository: Path,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Create a real full-history D1.8 source and sentinel in a temp clone."""

    common_git_dir = _git(
        ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    completed = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--shared",
            "--no-checkout",
            common_git_dir,
            str(repository),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    _git(repository, "config", "core.autocrlf", "false")
    _git(repository, "config", "user.email", "trimem-fixture@example.invalid")
    _git(repository, "config", "user.name", "TriMem credential-free fixture")
    _git(
        repository,
        "checkout",
        "--quiet",
        "--detach",
        development_trigger.PREVIOUS_EXECUTION_HEAD,
    )

    # Overlay the sealed D1.8 implementation and evidence bytes on top of
    # immutable _008 history. A disposable freeze is generated below, so the
    # real correction-source and sentinel validators can run unchanged.
    for relative in sorted(development_trigger.D18_REQUIRED_IMPLEMENTATION_PATHS):
        if relative == development_trigger.INVENTORY_PATH:
            continue
        assert relative != development_trigger.AMENDMENT_PATH
        _copy_repository_input(repository, relative)
    for relative in (
        development_trigger.AMENDMENT_PATH,
        development_trigger.INVENTORY_PATH,
        development_trigger.PREVIOUS_RECEIPT_PATH,
        development_trigger.PREVIOUS_REPORT_PATH,
    ):
        _copy_repository_input(repository, relative)

    freeze_path = repository / "artifacts/trimem_v1/freeze.json"
    freeze_members = set(development_trigger.BOUND_PATHS.values()) - {
        "artifacts/trimem_v1/freeze.json",
        development_trigger.PREVIOUS_SENTINEL_PATH,
    }
    freeze = {"files": {}}
    for relative in sorted(freeze_members):
        raw = (repository / relative).read_bytes()
        freeze["files"][relative] = {
            "bytes": len(raw),
            "sha256": _sha256(raw),
        }
    benchmark_run.write_json(freeze_path, freeze)

    _git(repository, "add", "--all")
    _git(repository, "commit", "--quiet", "-m", "fixture correction source")
    source_head = _git(repository, "rev-parse", "HEAD")
    remote_gates = {
        "source_head": source_head,
        "all_required_workflows_passed": True,
        "workflows": [
            {
                "workflow_path": workflow_path,
                "head_sha": source_head,
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            }
            for workflow_path in development_trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
        ],
        "scientific_execution": {
            "api_calls": 0,
            "grader_runs": 0,
            "model_calls": 0,
            "paid_model_calls": 0,
            "target_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
    }
    request = development_trigger.build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=remote_gates,
    )
    request_path = repository / benchmark_matrix.DEVELOPMENT_SENTINEL_PATH
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_bytes(
        development_trigger.canonical_bytes(request, trailing_lf=True)
    )
    _git(repository, "add", "--", benchmark_matrix.DEVELOPMENT_SENTINEL_PATH)
    _git(repository, "commit", "--quiet", "-m", "fixture sentinel only")
    execution_head = _git(repository, "rev-parse", "HEAD")
    request_sha256 = _sha256(request_path.read_bytes())
    freeze_sha256 = _sha256(freeze_path.read_bytes())
    cost = _read_json(repository / "configs/trimem_v1/cost_plan.json")
    hard_cap = cost["phase_hard_caps"]["DEVELOPMENT_TUNING"]
    approval_document = build_external_approval_document(
        request_id=request["request_id"],
        request_sha256=request_sha256,
        git_commit=execution_head,
        freeze_sha256=freeze_sha256,
        phase="DEVELOPMENT_TUNING",
        task_arm_runs=hard_cap["task_arm_runs"],
        paid_model_call_cap=hard_cap["paid_model_calls"],
        input_token_cap=hard_cap["input_tokens"],
        output_token_cap=hard_cap["output_tokens"],
        currency_hard_cap=hard_cap["total_usd"],
        grader_containers=hard_cap["benchmark_grader_containers"],
        workflow_run_id=90_000_000_001,
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="credential-free-fixture",
        approval_timestamp="2026-01-01T00:00:00Z",
        source_git_commit=source_head,
        openai_api_key="credential-free-placeholder-key",
        approval_nonce="credential-free-fixture-nonce",
        model_id="gpt-5.4-mini-2026-03-17",
    )
    approval_raw = _canonical(approval_document)
    approval_binding = {
        "approval_artifact_sha256": _sha256(approval_raw),
        "approved_request_sha256": request_sha256,
        "approved_workflow_run_id": "90000000001",
        "approved_workflow_run_attempt": "1",
        "freeze_sha256": freeze_sha256,
        "git_head": execution_head,
        "phase": "DEVELOPMENT_TUNING",
        "source_head": source_head,
    }
    return {
        "approval_raw": approval_raw,
        "request": request,
        "request_path": request_path,
    }, approval_binding


def _write_evidence(
    task_dir: Path,
    *,
    target: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    task_dir.mkdir(parents=True, exist_ok=True)
    target_id = str(target["target_id"])
    tail_hash = _sha256(f"terminal-evidence:{target_id}")
    checkout = {"schema": "trimem/d18-fixture-checkout/1.0", "target_id": target_id}

    lock = _read_json(ROOT / "artifacts/trimem_v1/grader_image_lock.json")
    lock_rows = [
        *lock["targets"],
        *lock["benchmark_target_images"]["targets"],
    ]
    target_rows = [
        row for row in lock_rows if row.get("instance_id") == target["instance_id"]
    ]
    assert len(target_rows) == 1
    image_rows = [("TARGET", target_rows[0])]
    if str(target["benchmark_id"]).startswith("multi_swe_bench"):
        assert len(lock["support_images"]) == 1
        image_rows.append(("SUPPORT", lock["support_images"][0]))

    restricted_root = task_dir / "official-grader" / "restricted-evidence"
    restricted_root.mkdir(parents=True)
    restricted_references: list[dict[str, Any]] = []

    def raw_reference(name: str, raw: bytes) -> dict[str, Any]:
        path = restricted_root / f"{name}.bin"
        path.write_bytes(raw)
        outer = benchmark_run.evidence_reference(task_dir, path)
        restricted_references.append(outer)
        return {
            "path": str(outer["path"]).removeprefix("official-grader/"),
            "sha256": outer["sha256"],
            "bytes": outer["bytes"],
            "access": "RESTRICTED_RAW_NOT_FOR_PUBLIC_LOGS",
        }

    harness_streams = {
        "stdout": raw_reference("harness-stdout", b"fixture harness stdout\n"),
        "stderr": raw_reference("harness-stderr", b""),
    }
    report_streams = None
    report_argv: list[str] = []
    report_status = "NOT_APPLICABLE"
    if str(target["benchmark_id"]).startswith("multi_swe_bench"):
        report_streams = {
            "stdout": raw_reference("report-stdout", b"fixture report stdout\n"),
            "stderr": raw_reference("report-stderr", b""),
        }
        report_argv = ["python", "fixture-report.py"]
        report_status = "SUCCESS"

    official_images = []
    for index, (role, locked_row) in enumerate(image_rows):
        image = str(locked_row["image"])
        tag = str(locked_row["harness_image_tag"])
        expected = str(locked_row["expected_digest"])
        inspect_streams = {
            "stdout": raw_reference(
                f"image-{index}-inspect-stdout", _canonical([image])
            ),
            "stderr": raw_reference(f"image-{index}-inspect-stderr", b""),
        }
        tag_streams = {
            "stdout": raw_reference(f"image-{index}-tag-stdout", b""),
            "stderr": raw_reference(f"image-{index}-tag-stderr", b""),
        }
        official_images.append(
            {
                "schema": benchmark_matrix.OFFICIAL_IMAGE_EVIDENCE_SCHEMA,
                "role": role,
                "image": image,
                "tag": tag,
                "expected": expected,
                "observed": [expected],
                "inspect_argv": [
                    "docker", "image", "inspect", "--format",
                    "{{json .RepoDigests}}", image,
                ],
                "inspect_invocation_status": "SUCCESS",
                "inspect_exit_code": 0,
                "inspect_restricted_raw_streams": inspect_streams,
                "tag_argv": ["docker", "image", "tag", image, tag],
                "tag_invocation_status": "SUCCESS",
                "tag_exit_code": 0,
                "tag_restricted_raw_streams": tag_streams,
            }
        )
    report = {
        "_trimem": {
            "harness_invocation_status": "SUCCESS",
            "invocation_argv": ["python", "fixture-harness.py"],
            "harness_restricted_raw_streams": harness_streams,
            "report_invocation_status": report_status,
            "report_invocation_argv": report_argv,
            "report_restricted_raw_streams": report_streams,
            "image_evidence": official_images,
        }
    }
    checkpoint = {
        "schema": "trimem/d18-fixture-checkpoint/1.0",
        "state": "DONE",
        "evidence_event_hash": tail_hash,
    }
    paths = {
        "stdout": task_dir / "stdout.txt",
        "stderr": task_dir / "stderr.txt",
        "raw_events": task_dir / "events.jsonl",
        "checkout": task_dir / "checkout-evidence.json",
        "report": task_dir / "report.json",
        "terminal_checkpoint": task_dir / "terminal-checkpoint.json",
    }
    paths["stdout"].write_bytes(b"fixture stdout\n")
    paths["stderr"].write_bytes(b"")
    paths["raw_events"].write_bytes(b'{"event_type":"fixture"}\n')
    benchmark_run.write_json(paths["checkout"], checkout)
    benchmark_run.write_json(paths["report"], report)
    benchmark_run.write_json(paths["terminal_checkpoint"], checkpoint)
    evidence = {
        name: benchmark_run.evidence_reference(task_dir, path)
        for name, path in paths.items()
    }
    evidence["restricted_grader_raw"] = sorted(
        restricted_references, key=lambda row: str(row["path"])
    )
    return evidence, {
        "checkout": _sha256(_canonical(checkout)),
        "tail": tail_hash,
        "checkpoint": _sha256(_canonical(checkpoint)),
    }


def _accounting() -> dict[str, int]:
    value = {field: 0 for field in benchmark_matrix.ACCOUNTING_FIELDS}
    value.update(
        {
            "solve_calls": 1,
            "decomposition_calls": 1,
            "extraction_calls": 1,
            "input_tokens": 31,
            "cached_input_tokens": 3,
            "output_tokens": 9,
            "reasoning_tokens": 1,
            "actual_decomposition_output_tokens": 2,
            "actual_solve_output_tokens": 3,
            "actual_extraction_output_tokens": 4,
            "solve_output_pool_capacity": 49_152,
            "remaining_solve_output_tokens": 49_149,
            "replace_text_calls": 1,
            "model_gateway_calls": 3,
            "paid_model_calls": 3,
            "grader_calls": 1,
            "grader_containers": 1,
            "official_grader_runs": 1,
        }
    )
    return value


def _memory_metrics(runtime_arm: str, sequence_index: int) -> dict[str, int]:
    value = {field: 0 for field in benchmark_matrix.MEMORY_FIELDS}
    if runtime_arm != "M0":
        value["recall_attempts"] = 1
        if sequence_index % 2 == 0:
            value.update(
                {
                    "injected_records": 1,
                    "episodic_injections": 1,
                    "retained_records": 1,
                    "net_memory_growth": 1,
                }
            )
        else:
            value["abstention_decisions"] = 1
    return value


def _semantics(sequence_index: int) -> dict[str, Any]:
    if sequence_index == 4:
        return {
            "cell_status": "MEMORY_EXTRACTION_FAILED",
            "model_failure_class": "STRUCTURED_OUTPUT_SCHEMA_FAILURE",
            "agent_completed": True,
            "grader_patch_source": "MODEL_PATCH",
            "extraction_status": "MEMORY_EXTRACTION_FAILED",
        }
    if sequence_index in {2, 5}:
        return {
            "cell_status": "CELL_SCIENTIFIC_FAILURE",
            "model_failure_class": "SOLVE_MULTIPLE_FUNCTION_CALLS",
            "agent_completed": False,
            "grader_patch_source": "MODEL_PARTIAL_PATCH",
            "extraction_status": "SUCCESS",
        }
    if sequence_index == 10:
        return {
            "cell_status": "CELL_SCIENTIFIC_FAILURE",
            "model_failure_class": "SOLVE_TRUNCATED_WRITE_FILE_CONTENT",
            "agent_completed": False,
            "grader_patch_source": "CANONICAL_FAILED_CELL_NOOP",
            "extraction_status": "SUCCESS",
        }
    return {
        "cell_status": "AGENT_COMPLETED",
        "model_failure_class": None,
        "agent_completed": True,
        "grader_patch_source": "MODEL_PATCH",
        "extraction_status": "SUCCESS",
    }


def _provider_outcomes(
    accounting: Mapping[str, int], semantics: Mapping[str, Any]
) -> dict[str, Any]:
    if semantics["cell_status"] in {
        "MEMORY_EXTRACTION_FAILED",
        "CELL_SCIENTIFIC_FAILURE",
    }:
        distribution = {str(semantics["model_failure_class"]): 1, "SUCCESS": 2}
    else:
        distribution = {"SUCCESS": 3}
    return {
        "provider_status_distribution": distribution,
        "incomplete_count": distribution.get(
            "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS", 0
        ),
        "refusal_count": distribution.get("RESPONSE_REFUSAL", 0),
        "structured_output_schema_failure_count": distribution.get(
            "STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0
        ),
        "provider_reported_usage": {
            "available_calls": 3,
            "unavailable_calls": 0,
            "complete": True,
            "input_tokens": accounting["input_tokens"],
            "cached_input_tokens": accounting["cached_input_tokens"],
            "output_tokens": accounting["output_tokens"],
            "reasoning_tokens": accounting["reasoning_tokens"],
        },
        "ledger_reservation": {
            "calls": 3,
            "input_upper_bound": 46,
            "output_cap": 32_768,
            "conservatively_charged_calls": 0,
        },
    }


def _fake_result(*, resolved: bool, semantics: Mapping[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        resolved=resolved,
        grade=SimpleNamespace(
            exit_code=0,
            status="success",
            container_started=True,
            official=True,
        ),
        **dict(semantics),
    )


def _reserve_and_reconcile_cell(
    ledger: benchmark_run.AtomicBudgetLedger,
    *,
    task_arm_key: str,
    logical_prefix: str,
    semantics: Mapping[str, Any],
) -> None:
    task_reservation = ledger.reserve_task_arm(task_arm_key)
    calls = (
        ("decompose", 7, 1, 2),
        ("solve", 11, 2, 3),
        ("extract", 13, 0, 4),
    )
    for call_kind, input_tokens, cached_tokens, output_tokens in calls:
        logical_id = f"{logical_prefix}:{call_kind}"
        reservation = ledger.reserve(
            logical_id,
            task_arm_key=task_arm_key,
            call_kind=call_kind,
            input_upper_bound=input_tokens + 5,
            output_cap=benchmark_run.MAX_LEDGER_OUTPUT_CAP_BY_CALL_KIND[call_kind],
        )
        contained_call = (
            semantics["cell_status"] == "CELL_SCIENTIFIC_FAILURE"
            and call_kind == "solve"
        ) or (
            semantics["cell_status"] == "MEMORY_EXTRACTION_FAILED"
            and call_kind == "extract"
        )
        ledger.reconcile(
            logical_id,
            reservation,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            status="PROVIDER_FAILURE" if contained_call else "SUCCESS",
        )
    ledger.complete_task_arm(
        task_arm_key,
        task_reservation,
        status=SCIENTIFIC_LEDGER_TERMINAL_STATUS,
        container_started=True,
    )


def _sum_fields(
    records: list[dict[str, Any]], field_name: str, fields: tuple[str, ...]
) -> dict[str, int]:
    return {
        field: sum(int(record[field_name][field]) for record in records)
        for field in fields
    }


def _write_stream(
    *,
    fixture_repository: Path,
    results_dir: Path,
    stream: str,
    selected_candidate_id: str,
    targets: list[dict[str, Any]],
    sequence_digest: str,
    locked_images: Mapping[str, str],
    pricing: Mapping[str, Any],
    ledger: benchmark_run.AtomicBudgetLedger,
    approval_binding: Mapping[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    runtime_arm = "M2" if stream.startswith("M2-") else stream
    prompt_candidate = (
        stream.removeprefix("M2-")
        if stream.startswith("M2-")
        else selected_candidate_id
    )
    runtime_lock_sha256 = (
        "sha256:" + benchmark_run.runtime_lock_for(prompt_candidate).content_hash
    )
    policy_sha256 = (
        "sha256:"
        + _sha256(_canonical(benchmark_run.load_candidate_policy(prompt_candidate)))
        if runtime_arm == "M2"
        else None
    )
    execution_lock_hash = "sha256:" + _sha256(f"execution-lock:{stream}")
    namespace = "trimem-d18-" + re.sub(r"[^a-z0-9-]", "-", stream.lower())
    identity_seed_digest = "sha256:" + _sha256(f"identity-seed:{stream}")
    workspace_factory_hash = _sha256("credential-free-fixture-workspace")
    records: list[dict[str, Any]] = []
    for target in targets:
        index = int(target["order_index"])
        semantics = _semantics(index)
        resolved = index < RESOLVED_COUNTS[stream]
        if semantics["grader_patch_source"] == "CANONICAL_FAILED_CELL_NOOP":
            resolved = False
        accounting = _accounting()
        memory = _memory_metrics(runtime_arm, index)
        provider_outcomes = _provider_outcomes(accounting, semantics)
        task_arm_key = f"{stream}:{runtime_arm}:{target['target_id']}"
        _reserve_and_reconcile_cell(
            ledger,
            task_arm_key=task_arm_key,
            logical_prefix=f"{stream}:{index:03d}",
            semantics=semantics,
        )
        # Keep fixture paths short enough for Windows' non-long-path temp-file
        # API. Identity remains in the serialized record, never the directory.
        task_dir = results_dir / stream / f"{index:02d}"
        locked_image = locked_images[str(target["instance_id"])]
        evidence, evidence_hashes = _write_evidence(
            task_dir,
            target=target,
        )
        digest = locked_image.rsplit("@", 1)[1]
        record = benchmark_run.build_terminal_result_record(
            result=_fake_result(resolved=resolved, semantics=semantics),
            actual_accounting=accounting,
            actual_memory_metrics=memory,
            provider_outcomes=provider_outcomes,
            actual_usd=benchmark_run.actual_usd_for_accounting(
                accounting, pricing
            ),
            static_fields={
                "arm": stream,
                "runtime_arm": runtime_arm,
                "benchmark_id": target["benchmark_id"],
                "checkout_evidence_sha256": evidence_hashes["checkout"],
                "execution_lock_hash": execution_lock_hash,
                "evidence_tail_hash": evidence_hashes["tail"],
                "namespace": namespace,
                "expected_image_digest": digest,
                "identity_seed_digest": identity_seed_digest,
                "observed_image_digest": digest,
                "sequence_index": index,
                "sequence_sha256": sequence_digest,
                "target_id": target["target_id"],
                "terminal_checkpoint_sha256": evidence_hashes["checkpoint"],
                "terminal_state": "DONE",
                "runtime_lock_sha256": runtime_lock_sha256,
                "m2_policy_manifest_sha256": policy_sha256,
                "selected_prompt_candidate_id": prompt_candidate,
                "workspace_factory_hash": workspace_factory_hash,
            },
            evidence=evidence,
        )
        benchmark_run.write_json(task_dir / "cell.result.json", record)
        records.append(record)

    checkpoint = None
    checkpoint_path = None
    candidate_id = stream.removeprefix("M2-") if runtime_arm == "M2" else None
    if runtime_arm == "M2":
        payload = {"candidate_id": candidate_id, "final_resume_cursor": len(targets)}
        checkpoint = {
            "payload": payload,
            "digest": "sha256:" + _sha256(_canonical(payload)),
        }
        path = results_dir / f"{stream}.post-development-frozen-checkpoint.json"
        benchmark_run.write_json(path, checkpoint)
        checkpoint_path = path.relative_to(fixture_repository).as_posix()

    total_accounting = _sum_fields(
        records, "actual_accounting", benchmark_matrix.ACCOUNTING_FIELDS
    )
    total_memory = _sum_fields(
        records, "actual_memory_metrics", benchmark_matrix.MEMORY_FIELDS
    )
    provider_outcomes = benchmark_run.combine_provider_outcomes(
        [record["provider_outcomes"] for record in records]
    )
    terminal = benchmark_matrix.scientific_terminal_summary(records)
    summary = {
        "arm": stream,
        "runtime_arm": runtime_arm,
        "final_resume_cursor": len(targets),
        "completed_target_count": len(targets),
        "canonical_stream_cursor": len(targets),
        "execution_lock_hash": execution_lock_hash,
        "namespace": namespace,
        "identity_seed_digest": identity_seed_digest,
        "sequence_sha256": sequence_digest,
        "selected_checkpoint": checkpoint,
        "selected_checkpoint_path": checkpoint_path,
        "candidate_id": candidate_id,
        "selected_prompt_candidate_id": prompt_candidate,
        "runtime_lock_sha256": runtime_lock_sha256,
        "m2_policy_manifest_sha256": policy_sha256,
        "actual_accounting": total_accounting,
        "actual_memory_metrics": total_memory,
        "provider_outcomes": provider_outcomes,
        "actual_total_tokens": (
            total_accounting["input_tokens"] + total_accounting["output_tokens"]
        ),
        "actual_usd": benchmark_run.actual_usd_for_accounting(
            total_accounting, pricing
        ),
        "resolved_count": sum(record["resolved"] is True for record in records),
        "cell_status_counts": terminal["cell_status_counts"],
        "contained_failure_count": terminal["contained_failure_count"],
        "model_failure_count": sum(
            record["model_failure_class"] is not None for record in records
        ),
        "model_failure_distribution": {
            failure: sum(record["model_failure_class"] == failure for record in records)
            for failure in sorted(
                {
                    str(record["model_failure_class"])
                    for record in records
                    if record["model_failure_class"] is not None
                }
            )
        },
        "model_failure_class_counts": terminal["model_failure_class_counts"],
        "partial_patch_count": sum(
            record["grader_patch_source"] == "MODEL_PARTIAL_PATCH"
            for record in records
        ),
        "canonical_noop_count": sum(
            record["grader_patch_source"] == "CANONICAL_FAILED_CELL_NOOP"
            for record in records
        ),
        "extraction_failure_count": terminal["extraction_failure_count"],
        "status": "PASS",
        "workspace_factory_hash": workspace_factory_hash,
    }
    benchmark_run.write_json(results_dir / f"{stream}.arm-summary.json", summary)
    benchmark_run.prepare_arm_identity(
        results_dir,
        arm=stream,
        split="development",
        experiment_id=(
            "trimemv1-"
            + approval_binding["git_head"][:12]
            + "-"
            + re.sub(r"[^a-z0-9-]", "-", stream.lower())
        ),
        execution_lock_hash=execution_lock_hash,
        resume=False,
    )
    return summary, records


def _canary(approval_digest: str) -> dict[str, Any]:
    return {
        "status": "PASS",
        "scientific_result": False,
        "generation_calls": 1,
        "input_token_cap": 4_096,
        "output_token_cap": 2_048,
        "model": "gpt-5.4-mini-2026-03-17",
        "approval_sha256": approval_digest,
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 10,
        "reasoning_tokens": 0,
        "actual_usd": "0.000106500000",
    }


def test_production_shaped_72_cell_terminal_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture_repository = tmp_path / "repository"
    fixture_material, approval_binding = (
        _initialize_disposable_execution_repository(fixture_repository)
    )
    results_dir = (
        fixture_repository
        / "artifacts"
        / "trimem_v1"
        / "benchmark_exec"
        / "development"
    )
    results_dir.mkdir(parents=True)
    benchmark_run.write_json(
        results_dir / "external-approval-evidence.json", approval_binding
    )
    (results_dir / "restricted-external-approval.json").write_bytes(
        fixture_material["approval_raw"]
    )

    cost_plan = _read_json(
        fixture_repository / "configs/trimem_v1/cost_plan.json"
    )
    pricing = cost_plan["model_pricing"]
    approval_digest = approval_binding["approval_artifact_sha256"]
    canary = _canary(approval_digest)
    benchmark_run.write_json(results_dir / "control" / "protocol-action-canary.json", canary)
    scientific_cap = benchmark_run.scientific_caps_after_protocol_canary(
        cost_plan["phase_hard_caps"]["DEVELOPMENT_TUNING"],
        canary,
        expected_approval_sha256=approval_digest,
    )
    ledger = benchmark_run.AtomicBudgetLedger(
        results_dir / "budget-ledger.json",
        approval_digest=approval_digest,
        caps=scientific_cap,
        pricing=pricing,
    )

    manifest = _read_json(
        fixture_repository / "configs/trimem_v1/development_manifest.json"
    )
    targets = manifest["targets"]
    assert len(targets) == 12
    assert tuple(benchmark_matrix.DEVELOPMENT_STREAMS) == (
        "M2-baseline",
        "M2-precision",
        "M2-recall",
        "M2-balanced",
        "M0",
        "M1",
    )
    side_effect_calls = {"provider": 0, "images": 0, "grader": 0}

    def forbidden_side_effect(kind: str):
        def fail(*_args: Any, **_kwargs: Any) -> None:
            side_effect_calls[kind] += 1
            raise AssertionError(f"D1.8 fixture invoked real {kind}")

        return fail

    monkeypatch.setattr(
        benchmark_run, "OpenAIResponsesProvider", forbidden_side_effect("provider")
    )
    monkeypatch.setattr(
        benchmark_run, "prepare_harnesses", forbidden_side_effect("images")
    )
    monkeypatch.setattr(
        benchmark_run,
        "OfficialHarnessGraderGateway",
        forbidden_side_effect("grader"),
    )
    monkeypatch.setattr(benchmark_run, "ROOT", fixture_repository)
    monkeypatch.setattr(benchmark_matrix, "ROOT", fixture_repository)
    monkeypatch.setattr(public_artifact, "ROOT", fixture_repository)
    monkeypatch.setenv("GITHUB_RUN_ID", approval_binding["approved_workflow_run_id"])
    monkeypatch.setenv(
        "GITHUB_RUN_ATTEMPT", approval_binding["approved_workflow_run_attempt"]
    )

    # Exercise the named production consumers after ROOT points at the
    # disposable repository. None of these calls is mocked.
    assert benchmark_matrix.manifest_path("development").is_file()
    locked_images = benchmark_matrix._locked_images(benchmark=True)
    assert benchmark_matrix._frozen_file_hash(
        "src/enterprise_memory/trimem/scientific_terminal.py"
    ) == _sha256(
        (fixture_repository / "src/enterprise_memory/trimem/scientific_terminal.py")
        .read_bytes()
    )
    sequence_digest = benchmark_matrix.sequence_sha256(targets)
    summaries: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    candidate_summaries: list[dict[str, Any]] = []
    for stream in benchmark_matrix.DEVELOPMENT_STREAMS[:4]:
        summary, stream_records = _write_stream(
            fixture_repository=fixture_repository,
            results_dir=results_dir,
            stream=stream,
            selected_candidate_id="baseline",
            targets=targets,
            sequence_digest=sequence_digest,
            locked_images=locked_images,
            pricing=pricing,
            ledger=ledger,
            approval_binding=approval_binding,
        )
        summaries.append(summary)
        candidate_summaries.append(summary)
        records.extend(stream_records)
    proposal, _selected_lock, _selected_policy = (
        benchmark_run.write_development_selection_artifacts(
            candidate_summaries, output_root=results_dir
        )
    )
    selected_candidate_id = str(proposal["selected_candidate_id"])
    assert selected_candidate_id == "balanced"
    for stream in benchmark_matrix.DEVELOPMENT_STREAMS[4:]:
        summary, stream_records = _write_stream(
            fixture_repository=fixture_repository,
            results_dir=results_dir,
            stream=stream,
            selected_candidate_id=selected_candidate_id,
            targets=targets,
            sequence_digest=sequence_digest,
            locked_images=locked_images,
            pricing=pricing,
            ledger=ledger,
            approval_binding=approval_binding,
        )
        summaries.append(summary)
        records.extend(stream_records)

    benchmark_matrix._restricted_evidence(
        results_dir / "M2-baseline" / "00" / "cell.result.json",
        records[0],
        targets[0],
    )

    completion = benchmark_run.validate_phase_completion(
        results_dir,
        split="development",
        summaries=summaries,
        ledger=ledger,
        hard_cap=scientific_cap,
        pricing=pricing,
    )
    ledger_state = _read_json(ledger.path)
    assert len(records) == completion["task_arm_runs"] == 72
    assert completion["actual_accounting"]["grader_containers"] == 72
    assert completion["actual_accounting"]["official_grader_runs"] == 72
    assert {
        record["execution_status"] for record in records
    } == {SCIENTIFIC_EXECUTION_STATUS}
    assert len(ledger_state["task_arms"]) == 72
    assert ledger_state["actual"]["task_arm_runs"] == 72
    assert ledger_state["actual"]["grader_containers"] == 72
    assert {
        row["status"] for row in ledger_state["task_arms"].values()
    } == {SCIENTIFIC_LEDGER_TERMINAL_STATUS}
    assert all(value == 0 for value in ledger_state["outstanding"].values())

    aggregate = benchmark_matrix.aggregate("development", results_dir)
    assert aggregate["status"] == "PASS"
    assert aggregate["expected_task_arm_count"] == 72
    assert aggregate["observed_task_arm_count"] == 72
    assert len(aggregate["outcomes"]) == 72
    assert aggregate["schema"] == "trimem/verified-aggregate/1.1"
    assert aggregate["budget_ledger_evidence"]["terminal_task_arm_count"] == 72
    assert all(
        value == 0
        for value in aggregate["budget_ledger_evidence"]["outstanding"].values()
    )
    assert aggregate["scientific_terminal_summary"]["terminal_result_count"] == 72
    assert aggregate["scientific_terminal_summary"]["contained_failure_count"] > 0
    assert {row["arm"] for row in aggregate["stream_totals"]} == set(
        benchmark_matrix.DEVELOPMENT_STREAMS
    )
    assert aggregate["selected_candidate_id"] == selected_candidate_id
    assert {
        row["arm"]: row["resolved_count"] for row in aggregate["stream_totals"]
    } == RESOLVED_COUNTS

    # Pass@1 consumes the official resolved bit, including a resolved partial
    # patch and a resolved extraction-failure cell; cell_status is not a score.
    resolved_contained = [
        record
        for record in records
        if record["resolved"] is True
        and record["cell_status"] != "AGENT_COMPLETED"
    ]
    assert resolved_contained
    assert any(
        record["cell_status"] == "MEMORY_EXTRACTION_FAILED"
        for record in resolved_contained
    )
    assert any(
        record["grader_patch_source"] == "MODEL_PARTIAL_PATCH"
        for record in resolved_contained
    )
    assert any(
        record["cell_status"] == "AGENT_COMPLETED" and record["resolved"] is False
        for record in records
    )
    contained_count = sum(
        record["cell_status"] != "AGENT_COMPLETED" for record in records
    )
    assert contained_count > 0
    assert (
        aggregate["scientific_terminal_summary"]["contained_failure_count"]
        == contained_count
    )
    assert sum(row["n"] for row in aggregate["benchmark_totals"]) == 72
    assert all(row["n"] == 4 for row in aggregate["benchmark_totals"])

    stream_resolved = {
        row["arm"]: int(row["resolved_count"])
        for row in aggregate["stream_totals"]
    }
    assert stream_resolved[f"M2-{selected_candidate_id}"] - stream_resolved["M0"] == 3
    assert stream_resolved["M2-balanced"] - stream_resolved["M1"] == 2
    assert {row["arm"] for row in aggregate["benchmark_totals"]} >= {"M0", "M1"}

    aggregate_path = tmp_path / "verified-development-aggregate.json"
    benchmark_run.write_json(aggregate_path, aggregate)
    public_path = tmp_path / "public-development.json"
    packaged = public_artifact.package(aggregate_path, public_path)
    public = _read_json(public_path)
    assert packaged["records"] == 72
    assert public["status"] == "PASS"
    assert public["schema"] == "trimem/public-benchmark-artifact/1.1"
    assert public["manifest"] == "development"
    assert len(public["outcomes"]) == 72
    assert public["scientific_terminal_summary"]["terminal_result_count"] == 72
    assert public["selected_candidate_id"] == "balanced"
    assert side_effect_calls == {"provider": 0, "images": 0, "grader": 0}

    malformed_totals = deepcopy(aggregate)
    malformed_totals["stream_totals"][0]["terminal_result_count"] -= 1
    malformed_totals["aggregate_sha256"] = _sha256(
        _canonical(
            {
                key: value
                for key, value in malformed_totals.items()
                if key != "aggregate_sha256"
            }
        )
    )
    malformed_totals_path = tmp_path / "malformed-stream-totals.json"
    benchmark_run.write_json(malformed_totals_path, malformed_totals)
    with pytest.raises(
        public_artifact.PublicArtifactError,
        match="stream terminal arithmetic|stream/global terminal totals",
    ):
        public_artifact.package(malformed_totals_path, tmp_path / "must-not-exist.json")

    wrong_contract = deepcopy(aggregate)
    wrong_contract["scientific_terminal_contract"]["sha256"] = "0" * 64
    wrong_contract["aggregate_sha256"] = _sha256(
        _canonical(
            {
                key: value
                for key, value in wrong_contract.items()
                if key != "aggregate_sha256"
            }
        )
    )
    wrong_contract_path = tmp_path / "wrong-terminal-contract.json"
    benchmark_run.write_json(wrong_contract_path, wrong_contract)
    with pytest.raises(
        public_artifact.PublicArtifactError, match="terminal contract binding"
    ):
        public_artifact.package(wrong_contract_path, tmp_path / "must-not-exist-2.json")


def _contract_record(
    *,
    cell_status: str = "AGENT_COMPLETED",
    resolved: bool = False,
) -> dict[str, Any]:
    semantics = {
        "AGENT_COMPLETED": {
            "cell_status": "AGENT_COMPLETED",
            "model_failure_class": None,
            "agent_completed": True,
            "grader_patch_source": "MODEL_PATCH",
            "extraction_status": "SUCCESS",
        },
        "CELL_SCIENTIFIC_FAILURE": {
            "cell_status": "CELL_SCIENTIFIC_FAILURE",
            "model_failure_class": "SOLVE_TRUNCATED_WRITE_FILE_CONTENT",
            "agent_completed": False,
            "grader_patch_source": "CANONICAL_FAILED_CELL_NOOP",
            "extraction_status": "SUCCESS",
        },
        "MEMORY_EXTRACTION_FAILED": {
            "cell_status": "MEMORY_EXTRACTION_FAILED",
            "model_failure_class": "STRUCTURED_OUTPUT_SCHEMA_FAILURE",
            "agent_completed": True,
            "grader_patch_source": "MODEL_PATCH",
            "extraction_status": "MEMORY_EXTRACTION_FAILED",
        },
    }[cell_status]
    accounting = _accounting()
    pricing = _read_json(ROOT / "configs" / "trimem_v1" / "cost_plan.json")[
        "model_pricing"
    ]
    return benchmark_run.build_terminal_result_record(
        result=_fake_result(resolved=resolved, semantics=semantics),
        actual_accounting=accounting,
        actual_memory_metrics=_memory_metrics("M0", 0),
        provider_outcomes=_provider_outcomes(accounting, semantics),
        actual_usd=benchmark_run.actual_usd_for_accounting(accounting, pricing),
        static_fields={"arm": "M0", "runtime_arm": "M0", "target_id": "target-001"},
        evidence={},
    )


def _contract_ledger_row() -> dict[str, Any]:
    return {
        "reservation_id": "f" * 64,
        "status": SCIENTIFIC_LEDGER_TERMINAL_STATUS,
        "actual_input_tokens": 31,
        "outstanding_input_tokens": 0,
        "actual_model_calls": 3,
        "outstanding_model_calls": 0,
        "actual_output_tokens": 9,
        "outstanding_output_tokens": 0,
        "actual_decomposition_output_tokens": 2,
        "actual_solve_output_tokens": 3,
        "actual_extraction_output_tokens": 4,
        "remaining_decomposition_output_tokens": 8_190,
        "remaining_solve_output_tokens": 49_149,
        "remaining_extraction_output_tokens": 8_188,
        "container_started": True,
    }


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda record: record.__setitem__("execution_status", "SUCCESS"), "CELL_TERMINAL"),
        (lambda record: record.pop("resolved"), "fields are missing"),
        (lambda record: record.__setitem__("resolved", 1), "resolved value"),
        (lambda record: record.__setitem__("official_grader", False), "official grader"),
        (lambda record: record.__setitem__("grader_exit_code", 1), "grader exit"),
        (lambda record: record.__setitem__("grader_exit_code", False), "grader exit"),
        (lambda record: record.__setitem__("grader_status", "failure"), "grader status"),
        (lambda record: record.__setitem__("cell_status", "UNKNOWN"), "cell status"),
    ),
)
def test_scientific_result_contract_rejects_nonterminal_or_malformed_cells(
    mutation: Any, message: str
) -> None:
    record = _contract_record()
    mutation(record)
    with pytest.raises(ScientificTerminalContractError, match=message):
        validate_scientific_terminal_result(record)


@pytest.mark.parametrize(
    "mutation",
    (
        lambda row: row.__setitem__("status", "SUCCESS"),
        lambda row: row.__setitem__("status", "RESERVED"),
        lambda row: row.__setitem__("outstanding_input_tokens", 1),
        lambda row: row.__setitem__("outstanding_model_calls", 1),
        lambda row: row.__setitem__("outstanding_output_tokens", 1),
    ),
)
def test_scientific_ledger_contract_rejects_legacy_or_outstanding_rows(
    mutation: Any,
) -> None:
    row = _contract_ledger_row()
    mutation(row)
    with pytest.raises(ScientificTerminalContractError):
        validate_scientific_terminal_ledger_row(row)


def test_result_ledger_pair_rejects_identity_drift() -> None:
    with pytest.raises(ScientificTerminalContractError, match="identity mismatch"):
        validate_result_ledger_pair(
            _contract_record(),
            _contract_ledger_row(),
            ledger_task_arm_key="M1:M1:target-001",
        )


def test_canonical_noop_and_post_grade_extraction_failure_are_terminal() -> None:
    canonical_noop = _contract_record(
        cell_status="CELL_SCIENTIFIC_FAILURE", resolved=False
    )
    extraction_failure = _contract_record(
        cell_status="MEMORY_EXTRACTION_FAILED", resolved=True
    )
    assert validate_scientific_terminal_result(canonical_noop)["resolved"] is False
    assert (
        validate_scientific_terminal_result(extraction_failure)["resolved"] is True
    )
    for record in (canonical_noop, extraction_failure):
        validate_result_ledger_pair(
            record,
            deepcopy(_contract_ledger_row()),
            ledger_task_arm_key="M0:M0:target-001",
        )


def test_empty_patch_post_grade_extraction_failure_remains_terminal() -> None:
    record = _contract_record()
    record.update(
        {
            "cell_status": "MEMORY_EXTRACTION_FAILED",
            "model_failure_class": "MEMORY_EXTRACTION_SCHEMA_FAILURE",
            "agent_completed": True,
            "grader_patch_source": "CANONICAL_FAILED_CELL_NOOP",
            "extraction_status": "MEMORY_EXTRACTION_FAILED",
        }
    )
    assert validate_scientific_terminal_result(record)["execution_status"] == (
        SCIENTIFIC_EXECUTION_STATUS
    )


@pytest.mark.parametrize(
    "updates",
    (
        {
            "cell_status": "CELL_SCIENTIFIC_FAILURE",
            "model_failure_class": "DAG has no ready node",
            "agent_completed": True,
            "grader_patch_source": "MODEL_PATCH",
            "extraction_status": "SUCCESS",
        },
        {
            "cell_status": "CELL_SCIENTIFIC_FAILURE",
            "model_failure_class": "invalid extraction response",
            "agent_completed": False,
            "grader_patch_source": "MODEL_PARTIAL_PATCH",
            "extraction_status": "MEMORY_EXTRACTION_FAILED",
        },
    ),
)
def test_impossible_runtime_stage_combinations_fail_closed(
    updates: dict[str, Any],
) -> None:
    record = _contract_record()
    record.update(updates)
    with pytest.raises(ScientificTerminalContractError, match="impossible"):
        validate_scientific_terminal_result(record)


def _terminal_request_rows(*, failed_role: str | None = None) -> list[dict[str, str]]:
    return [
        {
            "call_kind": role,
            "status": "PROVIDER_FAILURE" if role == failed_role else "SUCCESS",
        }
        for role in ("decompose", "solve", "extract")
    ]


def _set_provider_distribution(
    record: dict[str, Any], distribution: Mapping[str, int]
) -> None:
    outcomes = record["provider_outcomes"]
    outcomes["provider_status_distribution"] = dict(distribution)
    outcomes["incomplete_count"] = sum(
        count
        for status, count in distribution.items()
        if status.startswith("RESPONSE_INCOMPLETE")
    )
    outcomes["refusal_count"] = distribution.get("RESPONSE_REFUSAL", 0)
    outcomes["structured_output_schema_failure_count"] = distribution.get(
        "STRUCTURED_OUTPUT_SCHEMA_FAILURE", 0
    )


def test_request_terminal_statuses_are_bound_to_result_semantics() -> None:
    clean = _contract_record()
    _set_provider_distribution(
        clean, {"SOLVE_MULTIPLE_FUNCTION_CALLS": 1, "SUCCESS": 2}
    )
    with pytest.raises(ScientificTerminalContractError, match="clean scientific"):
        validate_result_request_statuses(
            clean, _terminal_request_rows(failed_role="solve")
        )

    extraction_failure = _contract_record(cell_status="MEMORY_EXTRACTION_FAILED")
    validate_result_request_statuses(
        extraction_failure, _terminal_request_rows(failed_role="extract")
    )
    missing_solve = [
        {"call_kind": "decompose", "status": "SUCCESS"},
        {"call_kind": "extract", "status": "PROVIDER_FAILURE"},
    ]
    with pytest.raises(ScientificTerminalContractError, match="request roles"):
        validate_result_request_statuses(extraction_failure, missing_solve)

    extraction_status_drift = deepcopy(extraction_failure)
    extraction_status_drift["cell_status"] = "CELL_SCIENTIFIC_FAILURE"
    extraction_status_drift["agent_completed"] = False
    extraction_status_drift["grader_patch_source"] = "MODEL_PARTIAL_PATCH"
    extraction_status_drift["model_failure_class"] = "DAG has no ready node"
    extraction_status_drift["extraction_status"] = "SUCCESS"
    with pytest.raises(ScientificTerminalContractError, match="extraction model"):
        validate_result_request_statuses(
            extraction_status_drift,
            _terminal_request_rows(failed_role="extract"),
        )


def test_provider_only_solve_failure_rejects_all_success_requests() -> None:
    record = _contract_record(cell_status="CELL_SCIENTIFIC_FAILURE")
    _set_provider_distribution(record, {"SUCCESS": 3})
    with pytest.raises(
        ScientificTerminalContractError,
        match="gateway failure class contradicts request outcomes",
    ):
        validate_result_request_statuses(record, _terminal_request_rows())


def test_two_failed_solve_requests_are_impossible() -> None:
    record = _contract_record(cell_status="CELL_SCIENTIFIC_FAILURE")
    requests = [
        {"call_kind": "decompose", "status": "SUCCESS"},
        {"call_kind": "solve", "status": "PROVIDER_FAILURE"},
        {"call_kind": "solve", "status": "PROVIDER_FAILURE"},
        {"call_kind": "extract", "status": "SUCCESS"},
    ]
    _set_provider_distribution(
        record, {"SOLVE_TRUNCATED_WRITE_FILE_CONTENT": 2, "SUCCESS": 2}
    )
    record["provider_outcomes"]["provider_reported_usage"].update(
        {"available_calls": 4, "input_tokens": 42, "output_tokens": 12}
    )
    record["provider_outcomes"]["ledger_reservation"].update(
        {"calls": 4, "input_upper_bound": 64, "output_cap": 49_152}
    )
    with pytest.raises(
        ScientificTerminalContractError, match="multiple provider failures"
    ):
        validate_result_request_statuses(record, requests)


def test_extraction_failure_rejects_solve_only_failure_class() -> None:
    record = _contract_record(cell_status="MEMORY_EXTRACTION_FAILED")
    record["model_failure_class"] = "SOLVE_MULTIPLE_FUNCTION_CALLS"
    _set_provider_distribution(
        record, {"SOLVE_MULTIPLE_FUNCTION_CALLS": 1, "SUCCESS": 2}
    )
    with pytest.raises(
        ScientificTerminalContractError,
        match="extraction gateway failure class contradicts request outcomes",
    ):
        validate_result_request_statuses(
            record, _terminal_request_rows(failed_role="extract")
        )


def test_structured_decomposition_failure_rejects_solve_request_role() -> None:
    record = _contract_record(cell_status="CELL_SCIENTIFIC_FAILURE")
    record["model_failure_class"] = "STRUCTURED_OUTPUT_SCHEMA_FAILURE"
    _set_provider_distribution(
        record, {"STRUCTURED_OUTPUT_SCHEMA_FAILURE": 1, "SUCCESS": 2}
    )
    with pytest.raises(
        ScientificTerminalContractError,
        match="gateway failure class contradicts request outcomes",
    ):
        validate_result_request_statuses(
            record, _terminal_request_rows(failed_role="solve")
        )


def test_grader_smoke_success_contract_remains_independent() -> None:
    # Supply the scientific fields too, so rejection below is specifically the
    # current scientific status boundary rather than an unrelated missing key.
    smoke_record = {
        **_contract_record(),
        "schema": "trimem/grader-smoke-terminal-cell/2.0",
        "execution_status": "SUCCESS",
        "grader_invoked": True,
        "container_started": True,
        "harness_completed": True,
        "final_report_generated": True,
        "official_tests_executed": True,
        "raw_test_evidence_captured": True,
        "submitted_patch_identity_verified": True,
        "digest_verified": True,
        "adapter_normalized": True,
        "authoritative_cell": True,
        "resolved": False,
        "official_final_report_resolved": False,
        "scientific_resolved": False,
        "primary_failure": None,
        "secondary_evidence_failures": [],
    }
    assert benchmark_matrix.validate_authoritative_smoke_terminal_record(
        smoke_record
    ) is None
    with pytest.raises(ScientificTerminalContractError, match="CELL_TERMINAL"):
        validate_scientific_terminal_result(smoke_record)


def test_production_serializer_owns_terminal_semantics() -> None:
    record = _contract_record()
    assert record["execution_status"] == SCIENTIFIC_EXECUTION_STATUS
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError,
        match="static fields override producer fields",
    ):
        benchmark_run.build_terminal_result_record(
            result=_fake_result(
                resolved=False, semantics=_semantics(0)
            ),
            actual_accounting=_accounting(),
            actual_memory_metrics=_memory_metrics("M0", 0),
            provider_outcomes=_provider_outcomes(_accounting(), _semantics(0)),
            actual_usd=record["actual_usd"],
            static_fields={
                "arm": "M0",
                "runtime_arm": "M0",
                "target_id": "target-001",
                "execution_status": "SUCCESS",
            },
            evidence={},
        )
