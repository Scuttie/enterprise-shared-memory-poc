from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_grader_smoke as grader_smoke  # noqa: E402
import trimem_official_grader as official_grader  # noqa: E402
from enterprise_memory.trimem.grader import GradeRequest, GradeResult  # noqa: E402
from enterprise_memory.trimem.workspace import WorkspaceGraderContext  # noqa: E402


PATCH = "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-old\n+new\n"
DIGEST = "d" * 64


def _fixture(tmp_path: Path) -> tuple[
    official_grader.OfficialHarnessGraderGateway,
    GradeRequest,
    dict[str, object],
    Path,
]:
    task_dir = tmp_path / "cell"
    grader_root = task_dir / "official-grader"
    grader_root.mkdir(parents=True)
    frozen = official_grader.FrozenOfficialTarget(
        target_id="multi_swe_bench_mini--vuejs__core-8911--noop",
        benchmark_id="multi_swe_bench_mini",
        instance_id="vuejs__core-8911",
        repository="vuejs/core",
        base_commit="a" * 40,
        dataset_revision="b" * 40,
        source_row_sha256="c" * 64,
        image=f"mswebench/vuejs_m_core@sha256:{DIGEST}",
        harness_image_tag="mswebench/vuejs_m_core:pr-8911",
        harness_revision=official_grader.MULTI_HARNESS_REVISION,
    )
    gateway = object.__new__(official_grader.OfficialHarnessGraderGateway)
    gateway.target = frozen
    gateway.output_root = grader_root.resolve()
    gateway._restricted_root = gateway.output_root / "restricted-evidence"
    gateway._secret_values = ()
    request = GradeRequest(
        task_id=frozen.target_id,
        repository=frozen.repository,
        base_commit=frozen.base_commit,
        patch=PATCH,
        workspace=WorkspaceGraderContext(
            kind="test", repository_files={}, base_commit=frozen.base_commit
        ),
    )
    target: dict[str, object] = {
        "target_id": frozen.target_id,
        "benchmark_id": frozen.benchmark_id,
        "instance_id": frozen.instance_id,
        "repository": frozen.repository,
        "base_commit": frozen.base_commit,
        "dataset_revision": frozen.dataset_revision,
        "source_row_sha256": frozen.source_row_sha256,
        "order_index": 5,
        "probe": "NOOP_BASELINE",
        "expected_resolved": False,
    }
    return gateway, request, target, task_dir


def _private_inputs(target: dict[str, object], patch_raw: bytes) -> list[dict[str, object]]:
    prediction = grader_smoke._prediction_input_bytes(target, patch_raw)
    result = []
    for name in ("dataset.jsonl", "prediction.jsonl", "config.json"):
        raw = prediction if name == "prediction.jsonl" else (name + "\n").encode()
        result.append({
            "name": name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "retention": "PURGED_AFTER_HASH_BOUND_GRADING",
        })
    return result


def _failure_result(
    tmp_path: Path, *, official_final_report_resolved: bool = False
) -> tuple[GradeResult, dict[str, object], Path]:
    gateway, request, target, task_dir = _fixture(tmp_path)
    patch_raw = PATCH.encode()
    restricted_patch = gateway._restricted_blob(
        "submitted-patch", "materialized", patch_raw
    )
    materialized_patch = {
        "schema": "trimem/materialized-submitted-patch-evidence/1.0",
        "host_path": (
            f"{request.task_id}/work/vuejs/core/evals/pr-8911/fix.patch"
        ),
        "container_destination": "/home/fix.patch",
        "mode": "rw",
        "bytes": len(patch_raw),
        "sha256": hashlib.sha256(patch_raw).hexdigest(),
        "request_identity_match": True,
        "restricted_materialized_patch": restricted_patch,
        "purged_after_capture": True,
    }
    image_evidence = [{
        "image": gateway.target.image,
        "expected": f"sha256:{DIGEST}",
        "observed": [f"sha256:{DIGEST}"],
    }]
    test_output = gateway._restricted_blob(
        "official-tests", "test_output", b"captured test output\n"
    )
    test_status = gateway._restricted_blob(
        "official-tests", "official_test_status", b"{}\n"
    )
    exit_status = gateway._restricted_blob(
        "official-tests", "container_exit_status", b"{}\n"
    )
    failure = gateway._failure(
        request,
        time.perf_counter_ns(),
        stage="adapter_semantic_normalization",
        status="adapter_contract_failed",
        reason="Multi-SWE official per-instance status identity/result mismatch",
        container_started=True,
        evidence=image_evidence,
        extra={
            "invocation_argv": ["python", "pinned-entrypoint.py"],
            "harness_invocation_status": "SUCCESS",
            "report_invocation_argv": ["python", "-m", "pinned-report"],
            "report_invocation_status": "SUCCESS",
            "test_output": test_output,
            "official_test_status": test_status,
            "container_exit_status": exit_status,
            "materialized_private_inputs": _private_inputs(target, patch_raw),
            "materialized_patch_evidence": materialized_patch,
            "official_final_report_resolved": official_final_report_resolved,
        },
    )
    return failure.result, target, task_dir


def _terminal_from_failure(
    tmp_path: Path, *, official_final_report_resolved: bool
) -> dict[str, object]:
    grade, target, task_dir = _failure_result(
        tmp_path, official_final_report_resolved=official_final_report_resolved
    )
    stdout = task_dir / "stdout.txt"
    stderr = task_dir / "stderr.txt"
    report = task_dir / "report.json"
    stdout.write_text(grade.stdout, encoding="utf-8")
    stderr.write_text(grade.stderr, encoding="utf-8")
    report.write_text(json.dumps(grade.report), encoding="utf-8")
    applied = task_dir / "restricted-input" / "applied.patch"
    applied.parent.mkdir()
    applied.write_text(PATCH, encoding="utf-8", newline="")
    applied_ref = grader_smoke.evidence_reference(task_dir, applied)
    return grader_smoke._failure_terminal_record(
        target=target,
        grade=grade,
        patch_raw=PATCH.encode(),
        task_dir=task_dir,
        grader_root=task_dir / "official-grader",
        applied_patch_ref=applied_ref,
        stdout_path=stdout,
        stderr_path=stderr,
        report_path=report,
        expected_image_digest=f"sha256:{DIGEST}",
    )


def test_failure_envelope_contains_all_captured_private_and_patch_evidence(
    tmp_path: Path,
) -> None:
    grade, target, _ = _failure_result(tmp_path)
    envelope = grader_smoke.validate_adapter_evidence_envelope(
        grade, target=target
    )

    assert set(envelope) == set(official_grader.OFFICIAL_EVIDENCE_FIELDS)
    assert envelope["materialized_private_inputs"] == grade.report["_trimem"][
        "materialized_private_inputs"
    ]
    assert envelope["materialized_patch_evidence"] == grade.report["_trimem"][
        "materialized_patch_evidence"
    ]
    assert set(grade.report) == {
        "task_id", "status", "failure_stage", "reason", "_trimem"
    }


def test_primary_error_survives_secondary_private_input_failure(tmp_path: Path) -> None:
    grade, _target, _task_dir = _failure_result(tmp_path)
    grade.report["_trimem"]["materialized_private_inputs"][1]["sha256"] = "0" * 64
    terminal = _terminal_from_failure_with_grade(tmp_path, grade)

    assert terminal["primary_failure"]["reason"] == (
        "Multi-SWE official per-instance status identity/result mismatch"
    )
    assert any(
        "prediction input" in reason or "private-input" in reason
        for reason in terminal["secondary_evidence_failures"]
    )


def test_malformed_failure_envelope_is_sanitized_without_masking_primary(
    tmp_path: Path,
) -> None:
    grade, _target, _task_dir = _failure_result(
        tmp_path, official_final_report_resolved=True
    )
    envelope = grade.report["_trimem"]
    envelope["adapter_normalized"] = True
    envelope["scientific_resolved"] = True
    envelope["unexpected_split_root"] = {"raw_test_name": "must-not-escape"}

    terminal = _terminal_from_failure_with_grade(tmp_path, grade)

    assert terminal["primary_failure"] == {
        "stage": "adapter_semantic_normalization",
        "status": "adapter_contract_failed",
        "reason": "Multi-SWE official per-instance status identity/result mismatch",
    }
    assert terminal["adapter_normalized"] is False
    assert terminal["scientific_resolved"] is None
    assert terminal["official_final_report_resolved"] is True
    assert terminal["authoritative_cell"] is False
    assert any(
        "total evidence envelope field set drift" in reason
        for reason in terminal["secondary_evidence_failures"]
    )


def _terminal_from_failure_with_grade(
    tmp_path: Path, grade: GradeResult
) -> dict[str, object]:
    _gateway, _request, target, task_dir = _fixture(tmp_path / "terminal")
    grader_root = task_dir / "official-grader"
    # Retained restricted evidence belongs to the original grade root.
    source_root = Path(tmp_path) / "cell" / "official-grader" / "restricted-evidence"
    target_root = grader_root / "restricted-evidence"
    target_root.mkdir(parents=True, exist_ok=True)
    for source in source_root.glob("*.bin"):
        (target_root / source.name).write_bytes(source.read_bytes())
    stdout = task_dir / "stdout.txt"
    stderr = task_dir / "stderr.txt"
    report = task_dir / "report.json"
    stdout.write_text(grade.stdout, encoding="utf-8")
    stderr.write_text(grade.stderr, encoding="utf-8")
    report.write_text(json.dumps(grade.report), encoding="utf-8")
    applied = task_dir / "restricted-input" / "applied.patch"
    applied.parent.mkdir()
    applied.write_text(PATCH, encoding="utf-8", newline="")
    return grader_smoke._failure_terminal_record(
        target=target,
        grade=grade,
        patch_raw=PATCH.encode(),
        task_dir=task_dir,
        grader_root=grader_root,
        applied_patch_ref=grader_smoke.evidence_reference(task_dir, applied),
        stdout_path=stdout,
        stderr_path=stderr,
        report_path=report,
        expected_image_digest=f"sha256:{DIGEST}",
    )


def test_post_adapter_validation_failure_writes_exactly_one_non_authoritative_terminal(
    tmp_path: Path,
) -> None:
    grade, target, task_dir = _failure_result(
        tmp_path, official_final_report_resolved=True
    )
    envelope = grade.report["_trimem"]
    envelope["adapter_status"] = "SUCCESS"
    envelope["adapter_failure_stage"] = None
    envelope["adapter_primary_error"] = None
    envelope["adapter_normalized"] = True
    envelope["scientific_resolved"] = True
    report = {
        "task_id": grade.task_id,
        "status": "success",
        "failure_stage": None,
        "reason": None,
        "_trimem": envelope,
    }
    grade = GradeResult(**{
        **grade.__dict__,
        "resolved": True,
        "exit_code": 0,
        "status": "success",
        "report": report,
    })
    stdout = task_dir / "stdout.txt"
    stderr = task_dir / "stderr.txt"
    report_path = task_dir / "report.json"
    stdout.write_text(grade.stdout, encoding="utf-8")
    stderr.write_text(grade.stderr, encoding="utf-8")
    report_path.write_text(json.dumps(grade.report), encoding="utf-8")
    applied = task_dir / "restricted-input" / "applied.patch"
    applied.parent.mkdir()
    applied.write_text(PATCH, encoding="utf-8", newline="")
    result_path = task_dir / "post-adapter.result.json"
    context = {
        "target": target,
        "grade": grade,
        "patch_raw": PATCH.encode(),
        "task_dir": task_dir,
        "grader_root": task_dir / "official-grader",
        "applied_patch_ref": grader_smoke.evidence_reference(task_dir, applied),
        "stdout_path": stdout,
        "stderr_path": stderr,
        "report_path": report_path,
        "expected_image_digest": f"sha256:{DIGEST}",
        "result_path": result_path,
        "post_adapter_failure_stage": "image_digest_validation",
    }
    primary = grader_smoke.BenchmarkExecutionError(
        "official grader image digest differs"
    )

    terminal = grader_smoke._write_post_adapter_failure_terminal(context, primary)
    first_bytes = result_path.read_bytes()
    assert terminal is not None
    assert terminal["primary_failure"] == {
        "stage": "image_digest_validation",
        "status": "image_digest_validation_failed",
        "reason": "official grader image digest differs",
    }
    assert terminal["adapter_normalized"] is True
    assert terminal["official_final_report_resolved"] is True
    assert terminal["scientific_resolved"] is None
    assert terminal["authoritative_cell"] is False
    assert grader_smoke._write_post_adapter_failure_terminal(context, primary) is None
    assert result_path.read_bytes() == first_bytes
    assert list(task_dir.glob("*.result.json")) == [result_path]
    taxonomy = grader_smoke.failure_taxonomy([terminal])
    assert taxonomy["image_lifecycle_failures"] == 1
    assert sum(taxonomy.values()) == 1


def test_underlying_true_is_retained_but_scientific_result_is_null_and_rejected(
    tmp_path: Path,
) -> None:
    terminal = _terminal_from_failure(
        tmp_path, official_final_report_resolved=True
    )
    assert terminal["official_final_report_resolved"] is True
    assert terminal["adapter_normalized"] is False
    assert terminal["scientific_resolved"] is None
    assert terminal["authoritative_cell"] is False
    with pytest.raises(benchmark_matrix.MatrixError, match="not authoritative"):
        benchmark_matrix.validate_authoritative_smoke_terminal_record(terminal)


def _built_terminal(index: int, *, normalized: bool) -> dict[str, object]:
    resolved = index % 2 == 0
    grade = GradeResult(
        task_id=f"target-{index}",
        resolved=resolved if normalized else False,
        exit_code=0,
        stdout="",
        stderr="",
        report={},
        grader_id="fixture",
        container_digest=f"fixture@sha256:{DIGEST}",
        official=True,
        wall_time_ms=1,
        container_started=True,
        status="success" if normalized else "adapter_contract_failed",
    )
    primary = None if normalized else {
        "stage": "adapter_semantic_normalization",
        "status": "adapter_contract_failed",
        "reason": "semantic mismatch",
    }
    envelope = {
        "invocation_argv": ["pinned"],
        "harness_invocation_status": "SUCCESS",
        "harness_restricted_raw_streams": {},
        "restricted_raw_report": {},
        "test_output": {},
        "official_test_status": {},
        "adapter_normalized": normalized,
        "official_final_report_resolved": resolved,
        "scientific_resolved": resolved if normalized else None,
    }
    return grader_smoke.build_terminal_cell_record(
        target={"target_id": f"target-{index}", "order_index": index, "probe": "GOLD"},
        grade=grade,
        envelope=envelope,
        execution_status="SUCCESS" if normalized else "FAILURE",
        primary_failure=primary,
        secondary_evidence_failures=[],
        submitted_patch_identity_verified=True,
        digest_verified=True,
        evidence={},
        execution_evidence={},
        actual_accounting={},
        extra={"resolved": resolved if normalized else False},
    )


def test_one_invocation_one_terminal_and_six_attempted_five_normalized() -> None:
    one = [_built_terminal(0, normalized=True)]
    assert grader_smoke.summarize_terminal_records(one, expected_count=1)[
        "attempted_cell_count"
    ] == 1
    with pytest.raises(grader_smoke.BenchmarkExecutionError, match="duplicated"):
        grader_smoke.summarize_terminal_records([one[0], one[0]], expected_count=2)

    records = [_built_terminal(index, normalized=index < 5) for index in range(6)]
    summary = grader_smoke.summarize_terminal_records(records, expected_count=12)
    assert summary == {
        "attempted_cell_count": 6,
        "terminal_record_count": 6,
        "official_execution_count": 6,
        "complete_execution_evidence_count": 6,
        "adapter_normalized_count": 5,
        "authoritative_cell_count": 0,
        "unattempted_cell_count": 6,
        "environment_failures": 0,
        "infrastructure_failures": 0,
        "image_lifecycle_failures": 0,
        "official_harness_failures": 0,
        "official_report_failures": 0,
        "adapter_contract_failures": 1,
        "aggregate_failures": 0,
    }

    twelve_normalized_but_unsealed = [
        _built_terminal(index, normalized=True) for index in range(12)
    ]
    unsealed_summary = grader_smoke.summarize_terminal_records(
        twelve_normalized_but_unsealed, expected_count=12
    )
    assert unsealed_summary["attempted_cell_count"] == 12
    assert unsealed_summary["adapter_normalized_count"] == 12
    assert unsealed_summary["authoritative_cell_count"] == 0


def test_production_smoke_loop_writes_one_terminal_for_unhandled_invocation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = {
        "target_id": "multi_swe_bench_mini--vuejs__core-8911--noop",
        "benchmark_id": "multi_swe_bench_mini",
        "instance_id": "vuejs__core-8911",
        "repository": "vuejs/core",
        "base_commit": "a" * 40,
        "dataset_revision": "b" * 40,
        "source_row_sha256": "c" * 64,
        "order_index": 0,
        "probe": "NOOP_BASELINE",
        "expected_resolved": False,
    }
    approval_path = tmp_path / "approval.json"
    approval_raw = b"{}"
    approval_path.write_bytes(approval_raw)
    approval = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": "d" * 64,
        "approved_workflow_run_id": 1,
        "approved_workflow_run_attempt": 1,
        "freeze_sha256": "e" * 64,
        "git_head": "f" * 40,
        "phase": "GRADER_SMOKE",
    }
    calls = {"grader": 0, "abort": 0, "provisional": 0}

    class FakeLifecycle:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def before_target(self, _index: int, _target: object) -> None:
            pass

        def abort(self, _error: BaseException) -> None:
            calls["abort"] += 1

    class FakeGrader:
        def grade(self, _request: GradeRequest) -> GradeResult:
            provisional_paths = list(output_root.rglob("*.result.json"))
            assert len(provisional_paths) == 1
            provisional = json.loads(
                provisional_paths[0].read_text(encoding="utf-8")
            )
            assert provisional["primary_failure"]["status"] == (
                grader_smoke.INVOCATION_INCOMPLETE_STATUS
            )
            assert provisional["evidence"] == {
                "applied_patch": provisional["evidence"]["applied_patch"],
                "restricted_grader_raw": [],
            }
            calls["provisional"] += 1
            calls["grader"] += 1
            raise RuntimeError("unhandled gateway failure")

    monkeypatch.setattr(grader_smoke, "validate_benchmark_environment", lambda: None)
    monkeypatch.setattr(
        grader_smoke, "validate_exec_approval", lambda *_args, **_kwargs: approval
    )
    monkeypatch.setattr(grader_smoke, "read_json", lambda _path: {})
    monkeypatch.setattr(grader_smoke, "_smoke_targets", lambda _manifest: [target])
    monkeypatch.setattr(
        grader_smoke,
        "_rows_for_targets",
        lambda _targets, _root: {
            (target["benchmark_id"], target["instance_id"]): {"row": "frozen"}
        },
    )
    monkeypatch.setattr(
        grader_smoke,
        "image_entries",
        lambda **_kwargs: (
            {
                target["instance_id"]: {
                    "expected_digest": f"sha256:{DIGEST}"
                }
            },
            (),
        ),
    )
    monkeypatch.setattr(grader_smoke, "prepare_harnesses", lambda _root: object())
    monkeypatch.setattr(grader_smoke, "_SerialImageLifecycle", FakeLifecycle)
    monkeypatch.setattr(grader_smoke, "_patch_for_target", lambda *_args: PATCH)
    monkeypatch.setattr(grader_smoke, "grader_factory", lambda *_args: FakeGrader())

    output_root = tmp_path / "output"
    with pytest.raises(RuntimeError, match="unhandled gateway failure"):
        grader_smoke.run_smoke(approval_path, output_root, tmp_path / "images")

    records = list(output_root.rglob("*.result.json"))
    assert calls == {"grader": 1, "abort": 1, "provisional": 1}
    assert len(records) == 1
    terminal = json.loads(records[0].read_text(encoding="utf-8"))
    assert terminal["grader_invoked"] is True
    assert terminal["container_started"] is False
    assert terminal["primary_failure"] == {
        "stage": "official_grader_invocation",
        "status": "grader_invocation_unhandled",
        "reason": "unhandled gateway failure",
    }
    summary = grader_smoke.summarize_terminal_records([terminal], expected_count=1)
    assert summary["attempted_cell_count"] == 1
    assert summary["terminal_record_count"] == 1
    assert summary["official_execution_count"] == 0


def _configure_non_result_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    grader: object,
) -> tuple[Path, Path]:
    target = {
        "target_id": "multi_swe_bench_mini--vuejs__core-8911--noop",
        "benchmark_id": "multi_swe_bench_mini",
        "instance_id": "vuejs__core-8911",
        "repository": "vuejs/core",
        "base_commit": "a" * 40,
        "dataset_revision": "b" * 40,
        "source_row_sha256": "c" * 64,
        "order_index": 0,
        "probe": "NOOP_BASELINE",
        "expected_resolved": False,
    }
    approval_path = tmp_path / "approval.json"
    approval_raw = b"{}"
    approval_path.write_bytes(approval_raw)
    approval = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": "d" * 64,
        "approved_workflow_run_id": 1,
        "approved_workflow_run_attempt": 1,
        "freeze_sha256": "e" * 64,
        "git_head": "f" * 40,
        "phase": "GRADER_SMOKE",
    }

    class FakeLifecycle:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def before_target(self, _index: int, _target: object) -> None:
            pass

        def abort(self, _error: BaseException) -> None:
            pass

    monkeypatch.setattr(grader_smoke, "validate_benchmark_environment", lambda: None)
    monkeypatch.setattr(
        grader_smoke, "validate_exec_approval", lambda *_args, **_kwargs: approval
    )
    monkeypatch.setattr(grader_smoke, "read_json", lambda _path: {})
    monkeypatch.setattr(grader_smoke, "_smoke_targets", lambda _manifest: [target])
    monkeypatch.setattr(
        grader_smoke,
        "_rows_for_targets",
        lambda _targets, _root: {
            (target["benchmark_id"], target["instance_id"]): {"row": "frozen"}
        },
    )
    monkeypatch.setattr(
        grader_smoke,
        "image_entries",
        lambda **_kwargs: (
            {target["instance_id"]: {"expected_digest": f"sha256:{DIGEST}"}},
            (),
        ),
    )
    monkeypatch.setattr(grader_smoke, "prepare_harnesses", lambda _root: object())
    monkeypatch.setattr(grader_smoke, "_SerialImageLifecycle", FakeLifecycle)
    monkeypatch.setattr(grader_smoke, "_patch_for_target", lambda *_args: PATCH)
    monkeypatch.setattr(grader_smoke, "grader_factory", lambda *_args: grader)
    return approval_path, tmp_path / "output"


@pytest.mark.parametrize("mode", ["none", "mapping", "failure_none"])
def test_production_smoke_loop_terminalizes_non_grade_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    class NonResultGrader:
        def grade(self, _request: GradeRequest) -> object:
            if mode == "none":
                return None
            if mode == "mapping":
                return {"not": "a GradeResult"}
            raise grader_smoke.GraderInvocationFailure(None)  # type: ignore[arg-type]

    approval_path, output_root = _configure_non_result_smoke(
        tmp_path, monkeypatch, NonResultGrader()
    )
    with pytest.raises(
        grader_smoke.BenchmarkExecutionError,
        match="returned a non-GradeResult value",
    ):
        grader_smoke.run_smoke(approval_path, output_root, tmp_path / "images")

    records = list(output_root.rglob("*.result.json"))
    assert len(records) == 1
    terminal = json.loads(records[0].read_text(encoding="utf-8"))
    assert terminal["primary_failure"] == {
        "stage": "official_grader_invocation",
        "status": "grader_invocation_unhandled",
        "reason": "official grader gateway returned a non-GradeResult value",
    }
    assert terminal["grader_invoked"] is True
    assert terminal["container_started"] is False
    assert terminal["actual_accounting"]["grader_calls"] == 1
    assert terminal["actual_accounting"]["grader_containers"] == 0


def test_production_smoke_loop_retries_secondary_report_write_without_masking_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_reason = "Multi-SWE official per-instance status identity/result mismatch"
    grade, target, _source_task_dir = _failure_result(tmp_path / "adapter")
    approval_path = tmp_path / "approval.json"
    approval_raw = b"{}"
    approval_path.write_bytes(approval_raw)
    approval = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": "d" * 64,
        "approved_workflow_run_id": 1,
        "approved_workflow_run_attempt": 1,
        "freeze_sha256": "e" * 64,
        "git_head": "f" * 40,
        "phase": "GRADER_SMOKE",
    }
    calls = {"grader": 0, "abort": 0, "report_writes": 0}

    class FakeLifecycle:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def before_target(self, _index: int, _target: object) -> None:
            pass

        def abort(self, _error: BaseException) -> None:
            calls["abort"] += 1

    class FakeGrader:
        def grade(self, _request: GradeRequest) -> GradeResult:
            calls["grader"] += 1
            raise official_grader.GraderInvocationFailure(grade)

    monkeypatch.setattr(grader_smoke, "validate_benchmark_environment", lambda: None)
    monkeypatch.setattr(
        grader_smoke, "validate_exec_approval", lambda *_args, **_kwargs: approval
    )
    monkeypatch.setattr(grader_smoke, "read_json", lambda _path: {})
    monkeypatch.setattr(grader_smoke, "_smoke_targets", lambda _manifest: [target])
    monkeypatch.setattr(
        grader_smoke,
        "_rows_for_targets",
        lambda _targets, _root: {
            (target["benchmark_id"], target["instance_id"]): {"row": "frozen"}
        },
    )
    monkeypatch.setattr(
        grader_smoke,
        "image_entries",
        lambda **_kwargs: (
            {
                target["instance_id"]: {
                    "expected_digest": f"sha256:{DIGEST}"
                }
            },
            (),
        ),
    )
    monkeypatch.setattr(grader_smoke, "prepare_harnesses", lambda _root: object())
    monkeypatch.setattr(grader_smoke, "_SerialImageLifecycle", FakeLifecycle)
    monkeypatch.setattr(grader_smoke, "_patch_for_target", lambda *_args: PATCH)
    monkeypatch.setattr(grader_smoke, "grader_factory", lambda *_args: FakeGrader())
    production_write_json = grader_smoke.write_json

    def fail_first_report_write(path: Path, value: object) -> None:
        if path.name == "report.json":
            calls["report_writes"] += 1
            if calls["report_writes"] == 1:
                raise OSError("injected one-time report persistence failure")
        production_write_json(path, value)

    monkeypatch.setattr(grader_smoke, "write_json", fail_first_report_write)

    output_root = tmp_path / "output"
    with pytest.raises(grader_smoke.BenchmarkExecutionError) as caught:
        grader_smoke.run_smoke(approval_path, output_root, tmp_path / "images")

    surfaced = str(caught.value)
    assert surfaced.startswith(primary_reason)
    assert "secondary_evidence_failures=" in surfaced
    assert "injected one-time report persistence failure" in surfaced
    records = list(output_root.rglob("*.result.json"))
    assert calls == {"grader": 1, "abort": 1, "report_writes": 2}
    assert len(records) == 1
    terminal = json.loads(records[0].read_text(encoding="utf-8"))
    assert terminal["authoritative_cell"] is False
    assert terminal["primary_failure"] == {
        "stage": "adapter_semantic_normalization",
        "status": "adapter_contract_failed",
        "reason": primary_reason,
    }
    assert any(
        "injected one-time report persistence failure" in secondary
        for secondary in terminal["secondary_evidence_failures"]
    )


@pytest.mark.parametrize("missing_name", ["stdout", "stderr", "report"])
def test_failure_terminal_survives_permanently_unavailable_persisted_evidence(
    tmp_path: Path,
    missing_name: str,
) -> None:
    grade, target, task_dir = _failure_result(tmp_path)
    paths = {
        "stdout": task_dir / "stdout.txt",
        "stderr": task_dir / "stderr.txt",
        "report": task_dir / "report.json",
    }
    # A directory at the final evidence path models a persistent write/read
    # failure rather than the recoverable one-shot failure covered above.
    paths[missing_name].mkdir()
    applied = task_dir / "restricted-input" / "applied.patch"
    applied.parent.mkdir()
    applied.write_text(PATCH, encoding="utf-8", newline="")
    result_path = task_dir / "missing-evidence.result.json"
    context = {
        "target": target,
        "grade": grade,
        "patch_raw": PATCH.encode(),
        "task_dir": task_dir,
        "grader_root": task_dir / "official-grader",
        "applied_patch_ref": grader_smoke.evidence_reference(task_dir, applied),
        "stdout_path": paths["stdout"],
        "stderr_path": paths["stderr"],
        "report_path": paths["report"],
        "expected_image_digest": f"sha256:{DIGEST}",
        "result_path": result_path,
        "preserve_grade_primary": True,
        "post_adapter_failure_stage": "terminal_evidence_persistence",
    }

    terminal = grader_smoke._write_post_adapter_failure_terminal(
        context, OSError(f"persistent {missing_name} failure")
    )

    assert terminal is not None
    assert list(task_dir.glob("*.result.json")) == [result_path]
    assert missing_name not in terminal["evidence"]
    assert terminal["primary_failure"] == grade.report["_trimem"][
        "adapter_primary_error"
    ]
    assert any(
        f"{missing_name} evidence is unavailable" in reason
        for reason in terminal["secondary_evidence_failures"]
    )
    assert terminal["execution_evidence"]["patch_applied"] is False
    assert terminal["execution_evidence"]["tests_executed"] is False
    if missing_name == "report":
        assert terminal["container_started"] is False
        assert terminal["final_report_generated"] is False
        assert terminal["raw_test_evidence_captured"] is False
        assert terminal["official_final_report_resolved"] is None
        assert terminal["scientific_resolved"] is None
        assert terminal["actual_accounting"]["grader_containers"] == 0


def test_purge_failure_is_secondary_to_existing_harness_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, request, _target, _task_dir = _fixture(tmp_path)
    harness_root = tmp_path / "harness"
    harness_root.mkdir()
    gateway.harness_root = harness_root.resolve()
    gateway.source_row = {"row": "frozen"}
    gateway.model_name = "test-model"
    gateway.support_images = ()
    gateway.python_binary = sys.executable
    gateway.timeout_seconds = 60

    task_root = gateway.output_root / gateway.target.target_id.replace("/", "_")
    task_root.mkdir(parents=True, exist_ok=True)
    private_path = task_root / "dataset.jsonl"
    private_path.write_bytes(b"private\n")
    invocation = official_grader.HarnessInvocation(
        argv=("frozen-harness",),
        cwd=harness_root,
        report_path=task_root / "final_report.json",
        private_input_paths=(private_path,),
        test_output_path=task_root / "test-output.txt",
        test_status_path=task_root / "status.json",
        container_exit_status_path=task_root / "exit-status.txt",
    )
    monkeypatch.setattr(
        official_grader, "build_harness_invocation", lambda *_args, **_kwargs: invocation
    )
    monkeypatch.setattr(
        gateway,
        "_verify_and_tag",
        lambda *_args, **_kwargs: {
            "image": gateway.target.image,
            "expected": f"sha256:{DIGEST}",
            "observed": [f"sha256:{DIGEST}"],
        },
    )
    monkeypatch.setattr(
        gateway,
        "_run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["frozen-harness"], returncode=1, stdout="", stderr="primary"
        ),
    )
    retained = [{
        "name": private_path.name,
        "sha256": hashlib.sha256(private_path.read_bytes()).hexdigest(),
        "bytes": len(private_path.read_bytes()),
        "retention": "PURGED_AFTER_HASH_BOUND_GRADING",
    }]

    def fail_purge(_paths: object) -> list[dict[str, object]]:
        raise official_grader._PrivateInputPurgeError("locked file", retained)

    monkeypatch.setattr(gateway, "_purge_private_inputs", fail_purge)

    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway.grade(request)
    envelope = caught.value.result.report["_trimem"]
    assert envelope["adapter_primary_error"] == {
        "stage": "official_harness",
        "status": "harness_exit_nonzero",
        "reason": "nonzero_exit",
    }
    assert envelope["materialized_private_inputs"] == retained
    assert len(envelope["adapter_secondary_evidence_failures"]) == 1
    assert envelope["adapter_secondary_evidence_failures"][0].startswith(
        "private_input_purge: _PrivateInputPurgeError: locked file"
    )


def test_actual_test_failure_retains_every_available_raw_reference(
    tmp_path: Path,
) -> None:
    gateway, _request, _target, task_dir = _fixture(tmp_path)
    harness_root = tmp_path / "harness"
    harness_root.mkdir()
    gateway.harness_root = harness_root.resolve()
    gateway.source_row = {}
    output = task_dir / "official-grader"
    test_output = output / "test-output.txt"
    test_status = output / "status.json"
    exit_status = output / "exit-status.txt"
    test_output.write_bytes(b"captured test output")
    test_status.write_bytes(b"{malformed-status")
    exit_status.write_bytes(b"captured exit status")
    invocation = official_grader.HarnessInvocation(
        argv=("frozen-harness",),
        cwd=harness_root,
        report_path=output / "final_report.json",
        private_input_paths=(),
        test_output_path=test_output,
        test_status_path=test_status,
        container_exit_status_path=exit_status,
    )

    with pytest.raises(official_grader._ActualTestEvidenceError) as caught:
        gateway._actual_test_evidence(
            invocation,
            resolved=False,
            final_report={"resolved": [], "unresolved": [gateway.target.instance_id]},
            expected_patch=PATCH,
        )

    assert set(caught.value.evidence) == {
        "test_output", "official_test_status", "container_exit_status"
    }
    for reference in caught.value.evidence.values():
        retained = output / reference["path"]
        assert retained.is_file()
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == reference["sha256"]


@pytest.mark.parametrize(
    ("failure_status", "expected_completed"),
    [("harness_timeout", False), ("harness_launch_failed", False), ("harness_exit_nonzero", True)],
)
def test_harness_completion_is_not_inferred_from_timeout_streams(
    failure_status: str, expected_completed: bool
) -> None:
    grade = GradeResult(
        task_id="target",
        resolved=False,
        exit_code=-1,
        stdout="partial",
        stderr="partial",
        report={},
        grader_id="fixture",
        container_digest=f"fixture@sha256:{DIGEST}",
        official=True,
        wall_time_ms=1,
        container_started=failure_status != "harness_launch_failed",
        status=failure_status,
    )
    primary = {
        "stage": "official_harness",
        "status": failure_status,
        "reason": "primary",
    }
    record = grader_smoke.build_terminal_cell_record(
        target={"target_id": "target", "order_index": 0, "probe": "GOLD"},
        grade=grade,
        envelope={
            "invocation_argv": ["frozen-harness"],
            "harness_invocation_status": {
                "harness_timeout": "TIMEOUT",
                "harness_launch_failed": "LAUNCH_FAILED",
                "harness_exit_nonzero": "EXIT_NONZERO",
            }[failure_status],
            "harness_restricted_raw_streams": {"stdout": {}, "stderr": {}},
            "restricted_raw_report": None,
            "test_output": None,
            "official_test_status": None,
            "adapter_primary_error": primary,
            "adapter_normalized": False,
            "official_final_report_resolved": None,
            "scientific_resolved": None,
        },
        execution_status="FAILURE",
        primary_failure=primary,
        secondary_evidence_failures=[],
        submitted_patch_identity_verified=False,
        digest_verified=False,
        evidence={},
        execution_evidence={},
        actual_accounting={},
    )
    assert record["harness_completed"] is expected_completed


def test_scientific_mismatch_never_persists_authoritative_cells(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result_path = tmp_path / "cell.result.json"
    record = _built_terminal(0, normalized=True)
    grader_smoke.write_json(result_path, record)

    def summary(
        _targets: object,
        _evidence: object,
        *,
        failures: list[str],
        terminal_records: list[dict[str, object]],
    ) -> dict[str, object]:
        assert failures == ["target-0"]
        return {
            "failures": [
                "target-0",
                *(
                    []
                    if terminal_records[0]["authoritative_cell"] is True
                    else ["AUTHORITATIVE_CELL_COUNT"]
                ),
            ],
            "status": "FAIL",
        }

    monkeypatch.setattr(grader_smoke, "_smoke_execution_summary", summary)
    journal_calls: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        grader_smoke,
        "write_finalization_journal",
        lambda _root, *, status, failures=(): journal_calls.append(
            (status, tuple(failures))
        ),
    )
    with pytest.raises(grader_smoke.BenchmarkExecutionError, match="target-0"):
        grader_smoke._finalize_smoke_campaign(
            targets=[{"target_id": "target-0"}],
            cell_evidence=[{"target_id": "target-0"}],
            failures=["target-0"],
            terminal_records=[(result_path, record)],
            output_root=tmp_path,
        )

    persisted = json.loads(result_path.read_text(encoding="utf-8"))
    assert persisted["authoritative_cell"] is False
    assert record["authoritative_cell"] is False
    assert journal_calls == [
        (grader_smoke.SCIENTIFIC_AGGREGATE_REJECTED, ("target-0",))
    ]


def test_failure_construction_does_not_mislabel_adapter_streams_as_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, request, _target, _task_dir = _fixture(tmp_path)

    def fail_streams(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise OSError("restricted volume full")

    monkeypatch.setattr(gateway, "_restricted_streams", fail_streams)
    failure = gateway._failure(
        request,
        time.perf_counter_ns(),
        stage="adapter_semantic_normalization",
        status="adapter_contract_failed",
        reason="Multi-SWE official per-instance status identity/result mismatch",
        container_started=True,
    )

    envelope = failure.result.report["_trimem"]
    assert str(failure).startswith(
        "Multi-SWE official per-instance status identity/result mismatch"
    )
    assert envelope["adapter_primary_error"]["reason"] == (
        "Multi-SWE official per-instance status identity/result mismatch"
    )
    assert envelope["harness_restricted_raw_streams"] is None
    assert envelope["adapter_secondary_evidence_failures"] == []
    assert set(envelope) == set(official_grader.OFFICIAL_EVIDENCE_FIELDS)


def test_image_inspect_failure_keeps_exact_stage_raw_and_no_harness_alias(
    tmp_path: Path,
) -> None:
    gateway, request, _target, _task_dir = _fixture(tmp_path)
    gateway.docker_binary = "docker"
    invalid_raw = b'{"RepoDigests":["forged"]}\xff\x00'
    gateway._run = lambda *_args, **_kwargs: subprocess.CompletedProcess(
        args=["docker", "image", "inspect"],
        returncode=0,
        stdout=invalid_raw,
        stderr=b"inspect-only stderr\xfe",
    )

    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway._verify_and_tag(
            request,
            time.perf_counter_ns(),
            gateway.target.image,
            gateway.target.harness_image_tag,
            [],
            role="TARGET",
        )

    envelope = caught.value.result.report["_trimem"]
    assert envelope["adapter_primary_error"] == {
        "stage": "image_inspect",
        "status": "image_inspect_invalid",
        "reason": "invalid_repo_digests",
    }
    assert envelope["harness_restricted_raw_streams"] is None
    assert len(envelope["image_evidence"]) == 1
    image = envelope["image_evidence"][0]
    assert set(image) == set(official_grader.OFFICIAL_IMAGE_EVIDENCE_FIELDS)
    assert image["inspect_invocation_status"] == "SUCCESS"
    assert image["inspect_exit_code"] == 0
    refs = image["inspect_restricted_raw_streams"]
    assert refs is not None, envelope["adapter_secondary_evidence_failures"]
    assert (gateway.output_root / refs["stdout"]["path"]).read_bytes() == invalid_raw
    assert (gateway.output_root / refs["stderr"]["path"]).read_bytes() == b"inspect-only stderr\xfe"


def test_image_inspect_rejects_non_list_repo_digests(tmp_path: Path) -> None:
    gateway, request, _target, _task_dir = _fixture(tmp_path)
    gateway.docker_binary = "docker"
    gateway._run = lambda *_args, **_kwargs: subprocess.CompletedProcess(
        args=["docker", "image", "inspect"],
        returncode=0,
        stdout=b'{"RepoDigests":["repo@sha256:' + DIGEST.encode() + b'"]}',
        stderr=b"",
    )

    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway._verify_and_tag(
            request,
            time.perf_counter_ns(),
            gateway.target.image,
            gateway.target.harness_image_tag,
            [],
            role="TARGET",
        )

    assert caught.value.result.report["_trimem"]["adapter_primary_error"][
        "reason"
    ] == "invalid_repo_digests"


def test_failure_construction_uses_total_v2_fallback_without_masking_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, request, _target, _task_dir = _fixture(tmp_path)

    def fail_envelope(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("injected envelope failure")

    monkeypatch.setattr(gateway, "_evidence_envelope", fail_envelope)
    failure = gateway._failure(
        request,
        time.perf_counter_ns(),
        stage="official_report",
        status="report_schema_mismatch",
        reason="primary report mismatch",
        container_started=True,
        extra={
            "invocation_argv": ["frozen-harness"],
            "official_final_report_resolved": True,
        },
    )

    envelope = failure.result.report["_trimem"]
    assert str(failure).startswith("primary report mismatch")
    assert set(envelope) == set(official_grader.OFFICIAL_EVIDENCE_FIELDS)
    assert envelope["execution_contract"] is None
    assert envelope["execution_control_evidence"] is None
    assert envelope["invocation_argv"] == ["frozen-harness"]
    assert envelope["official_final_report_resolved"] is True
    assert envelope["scientific_resolved"] is None
    assert envelope["adapter_secondary_evidence_failures"] == [
        "adapter_evidence_construction: AssertionError: injected envelope failure"
    ]


def test_post_harness_purge_failure_retains_every_available_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, request, _target, task_dir = _fixture(tmp_path)
    harness_root = tmp_path / "harness"
    harness_root.mkdir()
    gateway.harness_root = harness_root.resolve()
    gateway.source_row = {"row": "frozen"}
    gateway.model_name = "test-model"
    gateway.support_images = ()
    gateway.python_binary = sys.executable
    gateway.timeout_seconds = 60

    task_root = gateway.output_root / gateway.target.target_id.replace("/", "_")
    task_root.mkdir(parents=True, exist_ok=True)
    private_path = task_root / "dataset.jsonl"
    patch_path = task_root / "fix.patch"
    report_path = task_root / "final_report.json"
    test_output = task_root / "test-output.txt"
    test_status = task_root / "status.json"
    exit_status = task_root / "exit-status.txt"
    private_path.write_bytes(b"private row\n")
    patch_path.write_bytes(PATCH.encode())
    invocation = official_grader.HarnessInvocation(
        argv=("frozen-harness", "--instance", gateway.target.instance_id),
        cwd=harness_root,
        report_path=report_path,
        private_input_paths=(private_path,),
        test_output_path=test_output,
        test_status_path=test_status,
        report_argv=("frozen-report", "--evaluation"),
        materialized_patch_path=patch_path,
        container_exit_status_path=exit_status,
    )
    monkeypatch.setattr(
        official_grader, "build_harness_invocation", lambda *_args, **_kwargs: invocation
    )
    monkeypatch.setattr(
        gateway,
        "_verify_and_tag",
        lambda *_args, **_kwargs: {
            "image": gateway.target.image,
            "expected": f"sha256:{DIGEST}",
            "observed": [f"sha256:{DIGEST}"],
        },
    )
    calls = iter(
        [
            subprocess.CompletedProcess(
                args=list(invocation.argv), returncode=0, stdout="harness-out", stderr="harness-err"
            ),
            subprocess.CompletedProcess(
                args=list(invocation.report_argv), returncode=0, stdout="report-out", stderr="report-err"
            ),
        ]
    )

    def run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        completed = next(calls)
        if completed.args == list(invocation.argv):
            report_path.write_text(
                json.dumps(
                    _unresolved_multi_final_report(gateway.target.instance_id),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            test_output.write_bytes(b"raw tests")
            test_status.write_bytes(b"{}")
            exit_status.write_bytes(b"0")
        return completed

    monkeypatch.setattr(gateway, "_run", run)
    retained = [{
        "name": private_path.name,
        "sha256": hashlib.sha256(private_path.read_bytes()).hexdigest(),
        "bytes": len(private_path.read_bytes()),
        "retention": "PURGED_AFTER_HASH_BOUND_GRADING",
    }]

    def fail_purge(_paths: object) -> list[dict[str, object]]:
        raise official_grader._PrivateInputPurgeError("locked file", retained)

    monkeypatch.setattr(gateway, "_purge_private_inputs", fail_purge)

    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway.grade(request)
    envelope = caught.value.result.report["_trimem"]
    assert envelope["adapter_failure_stage"] == "private_input_purge"
    assert envelope["invocation_argv"] == list(invocation.argv)
    assert envelope["report_invocation_argv"] == list(invocation.report_argv)
    assert envelope["report_invocation_status"] == "SUCCESS"
    assert envelope["harness_restricted_raw_streams"] is not None
    assert envelope["report_restricted_raw_streams"] is not None
    assert envelope["materialized_private_inputs"] == retained
    assert envelope["materialized_patch_evidence"]["request_identity_match"] is True
    assert envelope["test_output"] is not None
    assert envelope["official_test_status"] is not None
    assert envelope["container_exit_status"] is not None
    assert envelope["restricted_raw_report"] is not None
    assert envelope["official_final_report_resolved"] is False
    assert envelope["scientific_resolved"] is None


def test_available_test_capture_failure_retains_completed_commands_and_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, request, invocation = _configured_failure_path_gateway(
        tmp_path, monkeypatch, report_argv=("frozen-report", "--evaluation")
    )
    report_raw = (
        json.dumps(
            _unresolved_multi_final_report(gateway.target.instance_id),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    calls = 0

    def run_stage(
        argv: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            invocation.report_path.write_bytes(report_raw)
            return subprocess.CompletedProcess(
                argv, 0, stdout="harness stdout", stderr="harness stderr"
            )
        return subprocess.CompletedProcess(
            argv, 0, stdout="report stdout", stderr="report stderr"
        )

    monkeypatch.setattr(gateway, "_run", run_stage)

    def fail_available(
        _invocation: object,
        *,
        secondary_evidence_failures: list[str] | None = None,
    ) -> dict[str, object]:
        assert secondary_evidence_failures is not None
        secondary_evidence_failures.append(
            "available_official_test_status_capture: OSError: injected"
        )
        return {}

    monkeypatch.setattr(gateway, "_capture_available_test_references", fail_available)

    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway.grade(request)

    envelope = caught.value.result.report["_trimem"]
    assert envelope["adapter_primary_error"] == {
        "stage": "adapter_evidence_capture",
        "status": "adapter_evidence_capture_failed",
        "reason": "available_test_evidence_capture_failed",
    }
    assert envelope["harness_invocation_status"] == "SUCCESS"
    assert envelope["report_invocation_status"] == "SUCCESS"
    assert envelope["harness_restricted_raw_streams"] is not None
    assert envelope["report_restricted_raw_streams"] is not None
    assert envelope["restricted_raw_report"] is not None
    assert envelope["official_final_report_resolved"] is False
    assert envelope["scientific_resolved"] is None
    assert envelope["adapter_normalized"] is False


@pytest.mark.parametrize(
    ("stage", "status", "expected"),
    [
        ("protected_environment", "environment_failed", "environment_failures"),
        ("official_grader_invocation", "launch_failed", "infrastructure_failures"),
        ("image_pull", "image_pull_timeout", "image_lifecycle_failures"),
        ("official_harness", "harness_timeout", "official_harness_failures"),
        ("official_report", "report_timeout", "official_report_failures"),
        ("adapter_semantic_normalization", "adapter_contract_failed", "adapter_contract_failures"),
        ("scientific_aggregate", "aggregate_failed", "aggregate_failures"),
    ],
)
def test_failure_taxonomy_uses_stage_before_generic_timeout_or_launch_status(
    stage: str, status: str, expected: str
) -> None:
    primary = {"stage": stage, "status": status, "reason": "fixture"}
    counts = grader_smoke.failure_taxonomy([{"primary_failure": primary}])
    assert counts[expected] == 1
    assert sum(counts.values()) == 1


def test_subprocess_non_utf8_streams_are_retained_byte_exact(
    tmp_path: Path,
) -> None:
    gateway, _request, _target, _task_dir = _fixture(tmp_path)
    stdout_raw = b"stdout-valid\ninvalid:\xff\xfe\x80\x00"
    stderr_raw = b"stderr-invalid:\x81\xf5\r\n"
    observed_kwargs: dict[str, object] = {}

    def runner(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        observed_kwargs.update(kwargs)
        return subprocess.CompletedProcess(
            argv, 0, stdout=stdout_raw, stderr=stderr_raw
        )

    gateway.runner = runner
    gateway.execution_env = {}
    completed = gateway._run(["fixture-subprocess"])
    references = gateway._restricted_streams(
        "non-utf8-subprocess", completed.stdout, completed.stderr
    )

    assert observed_kwargs["text"] is False
    assert "\ufffd" in completed.stdout
    assert "\ufffd" in completed.stderr
    for name, expected in (("stdout", stdout_raw), ("stderr", stderr_raw)):
        reference = references[name]
        retained = gateway.output_root / reference["path"]
        assert retained.read_bytes() == expected
        assert reference["bytes"] == len(expected)
        assert reference["sha256"] == hashlib.sha256(expected).hexdigest()


def _configured_failure_path_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    report_argv: tuple[str, ...] = (),
) -> tuple[
    official_grader.OfficialHarnessGraderGateway,
    GradeRequest,
    official_grader.HarnessInvocation,
]:
    gateway, request, _target, _task_dir = _fixture(tmp_path)
    harness_root = tmp_path / "harness"
    harness_root.mkdir()
    gateway.harness_root = harness_root.resolve()
    gateway.source_row = {"row": "frozen"}
    gateway.model_name = "test-model"
    gateway.support_images = ()
    gateway.python_binary = sys.executable
    gateway.timeout_seconds = 60
    task_root = gateway.output_root / gateway.target.target_id.replace("/", "_")
    task_root.mkdir(parents=True, exist_ok=True)
    invocation = official_grader.HarnessInvocation(
        argv=("frozen-harness",),
        cwd=harness_root,
        report_path=task_root / "final_report.json",
        private_input_paths=(),
        test_output_path=task_root / "test-output.txt",
        test_status_path=task_root / "status.json",
        report_argv=report_argv,
        container_exit_status_path=task_root / "exit-status.txt",
    )
    monkeypatch.setattr(
        official_grader,
        "build_harness_invocation",
        lambda *_args, **_kwargs: invocation,
    )
    monkeypatch.setattr(
        gateway,
        "_verify_and_tag",
        lambda *_args, **_kwargs: {
            "image": gateway.target.image,
            "expected": f"sha256:{DIGEST}",
            "observed": [f"sha256:{DIGEST}"],
        },
    )
    return gateway, request, invocation


@pytest.mark.parametrize("failure_kind", ["timeout", "nonzero"])
@pytest.mark.parametrize("post_start_artifact", [False, True])
def test_harness_failure_counts_container_only_from_post_start_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    post_start_artifact: bool,
) -> None:
    gateway, request, invocation = _configured_failure_path_gateway(
        tmp_path, monkeypatch
    )

    def fail_harness(
        *_args: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        if post_start_artifact:
            invocation.test_output_path.write_bytes(b"post-start evidence\n")
        if failure_kind == "timeout":
            raise subprocess.TimeoutExpired(
                invocation.argv,
                gateway.timeout_seconds,
                output="partial stdout",
                stderr="partial stderr",
            )
        return subprocess.CompletedProcess(
            invocation.argv,
            17,
            stdout="failed stdout",
            stderr="failed stderr",
        )

    monkeypatch.setattr(gateway, "_run", fail_harness)
    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway.grade(request)

    result = caught.value.result
    expected_status = (
        "harness_timeout" if failure_kind == "timeout" else "harness_exit_nonzero"
    )
    assert result.status == expected_status
    assert result.container_started is post_start_artifact
    assert result.report["_trimem"]["adapter_primary_error"] == {
        "stage": "official_harness",
        "status": expected_status,
        "reason": "timeout" if failure_kind == "timeout" else "nonzero_exit",
    }
    assert (
        result.report["_trimem"]["test_output"] is not None
    ) is post_start_artifact


def _unresolved_multi_final_report(instance_id: str) -> dict[str, object]:
    repository, number = instance_id.rsplit("-", 1)
    org, repo = repository.split("__", 1)
    canonical_id = f"{org}/{repo}:pr-{number}"
    return {
        "total_instances": 1,
        "submitted_instances": 1,
        "completed_instances": 1,
        "incomplete_instances": 0,
        "resolved_instances": 0,
        "unresolved_instances": 1,
        "empty_patch_instances": 0,
        "error_instances": 0,
        "submitted_ids": [canonical_id],
        "completed_ids": [canonical_id],
        "incomplete_ids": [],
        "resolved_ids": [],
        "unresolved_ids": [canonical_id],
        "empty_patch_ids": [],
        "error_ids": [],
    }


@pytest.mark.parametrize("failure_kind", ["timeout", "nonzero"])
def test_report_failure_retains_generated_report_and_official_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    gateway, request, invocation = _configured_failure_path_gateway(
        tmp_path, monkeypatch, report_argv=("frozen-report", "--evaluation")
    )
    report_raw = (
        json.dumps(
            _unresolved_multi_final_report(gateway.target.instance_id),
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    calls = 0

    def run_stage(
        argv: object, **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            invocation.test_output_path.write_bytes(b"post-start test output\n")
            invocation.test_status_path.write_bytes(b"{}\n")
            assert invocation.container_exit_status_path is not None
            invocation.container_exit_status_path.write_bytes(b"{}\n")
            invocation.report_path.write_bytes(report_raw)
            return subprocess.CompletedProcess(
                argv, 0, stdout="harness stdout", stderr="harness stderr"
            )
        if failure_kind == "timeout":
            raise subprocess.TimeoutExpired(
                argv, gateway.timeout_seconds, output="report partial", stderr="report timeout"
            )
        return subprocess.CompletedProcess(
            argv, 23, stdout="report failed", stderr="report error"
        )

    monkeypatch.setattr(gateway, "_run", run_stage)
    with pytest.raises(official_grader.GraderInvocationFailure) as caught:
        gateway.grade(request)

    result = caught.value.result
    expected_status = (
        "report_timeout" if failure_kind == "timeout" else "report_exit_nonzero"
    )
    envelope = result.report["_trimem"]
    assert str(caught.value).startswith(
        "timeout" if failure_kind == "timeout" else "nonzero_exit"
    )
    assert result.status == expected_status
    assert envelope["adapter_primary_error"] == {
        "stage": "official_report",
        "status": expected_status,
        "reason": "timeout" if failure_kind == "timeout" else "nonzero_exit",
    }
    assert envelope["adapter_normalized"] is False
    assert envelope["official_final_report_resolved"] is False
    assert envelope["scientific_resolved"] is None
    restricted = envelope["restricted_raw_report"]
    assert restricted is not None
    assert (gateway.output_root / restricted["path"]).read_bytes() == report_raw


def test_scientific_mismatch_stops_after_one_terminal_and_uses_fail_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance_id = "vuejs__core-8911"
    targets = [
        {
            "target_id": (
                f"multi_swe_bench_mini--{instance_id}--"
                + ("gold" if index == 0 else "noop")
            ),
            "benchmark_id": "multi_swe_bench_mini",
            "instance_id": instance_id,
            "repository": "vuejs/core",
            "base_commit": "a" * 40,
            "dataset_revision": "b" * 40,
            "source_row_sha256": "c" * 64,
            "order_index": index,
            "probe": "GOLD" if index == 0 else "NOOP_BASELINE",
            "expected_resolved": index == 0,
        }
        for index in range(2)
    ]
    approval_path = tmp_path / "approval.json"
    approval_raw = b"{}"
    approval_path.write_bytes(approval_raw)
    approval = {
        "approval_artifact_sha256": hashlib.sha256(approval_raw).hexdigest(),
        "approved_request_sha256": "d" * 64,
        "approved_workflow_run_id": 1,
        "approved_workflow_run_attempt": 1,
        "freeze_sha256": "e" * 64,
        "git_head": "f" * 40,
        "phase": "GRADER_SMOKE",
    }
    calls: dict[str, list[int]] = {"before": [], "after": [], "grade": []}

    class FakeLifecycle:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def before_target(self, index: int, _target: object) -> None:
            calls["before"].append(index)

        def after_target(self, index: int, _target: object) -> None:
            calls["after"].append(index)
            raise RuntimeError("synthetic post-mismatch cleanup failure")

        def abort(self, _error: BaseException) -> None:
            pass

    class FakeGrader:
        def __init__(self, target: dict[str, object]) -> None:
            self.target = official_grader.FrozenOfficialTarget(
                target_id=str(target["target_id"]),
                benchmark_id=str(target["benchmark_id"]),
                instance_id=str(target["instance_id"]),
                repository=str(target["repository"]),
                base_commit=str(target["base_commit"]),
                dataset_revision=str(target["dataset_revision"]),
                source_row_sha256=str(target["source_row_sha256"]),
                image=f"mswebench/vuejs_m_core@sha256:{DIGEST}",
                harness_image_tag="mswebench/vuejs_m_core:pr-8911",
                harness_revision=official_grader.MULTI_HARNESS_REVISION,
            )

        def grade(self, request: GradeRequest) -> GradeResult:
            calls["grade"].append(int(request.task_id.endswith("noop")))
            return GradeResult(
                task_id=request.task_id,
                resolved=False,
                exit_code=0,
                stdout="",
                stderr="",
                report={"_trimem": {}},
                grader_id="official-fixture",
                container_digest=f"fixture@sha256:{DIGEST}",
                official=True,
                wall_time_ms=1,
                container_started=True,
                status="success",
            )

    monkeypatch.setattr(grader_smoke, "validate_benchmark_environment", lambda: None)
    monkeypatch.setattr(
        grader_smoke, "validate_exec_approval", lambda *_args, **_kwargs: approval
    )
    monkeypatch.setattr(grader_smoke, "read_json", lambda _path: {})
    monkeypatch.setattr(grader_smoke, "_smoke_targets", lambda _manifest: targets)
    monkeypatch.setattr(
        grader_smoke,
        "_rows_for_targets",
        lambda *_args: {
            (target["benchmark_id"], target["instance_id"]): {"row": "frozen"}
            for target in targets
        },
    )
    monkeypatch.setattr(
        grader_smoke,
        "image_entries",
        lambda **_kwargs: (
            {
                instance_id: {
                    "image": f"mswebench/vuejs_m_core@sha256:{DIGEST}",
                    "harness_image_tag": "mswebench/vuejs_m_core:pr-8911",
                    "expected_digest": f"sha256:{DIGEST}",
                }
            },
            (),
        ),
    )
    monkeypatch.setattr(grader_smoke, "prepare_harnesses", lambda _root: object())
    monkeypatch.setattr(grader_smoke, "_SerialImageLifecycle", FakeLifecycle)
    monkeypatch.setattr(grader_smoke, "_patch_for_target", lambda *_args: PATCH)
    monkeypatch.setattr(
        grader_smoke,
        "grader_factory",
        lambda target, *_args: FakeGrader(target),
    )
    envelope = {
        "adapter_normalized": True,
        "official_final_report_resolved": False,
        "scientific_resolved": False,
        "harness_invocation_status": "SUCCESS",
        "restricted_raw_report": {"path": "restricted/report.bin"},
        "container_exit_status": {"path": "restricted/exit.bin"},
        "test_output": {"path": "restricted/output.bin"},
        "official_test_status": {"path": "restricted/status.bin"},
    }
    monkeypatch.setattr(
        grader_smoke,
        "validate_adapter_evidence_envelope",
        lambda *_args, **_kwargs: dict(envelope),
    )
    monkeypatch.setattr(
        grader_smoke,
        "_validated_execution_contract",
        lambda *_args, **_kwargs: {"api_calls": 0},
    )
    monkeypatch.setattr(
        grader_smoke,
        "_validated_execution_control",
        lambda *_args, **_kwargs: {
            "host_prepare_script_reads": 0,
            "source_image_build_calls": 0,
        },
    )
    monkeypatch.setattr(
        grader_smoke,
        "_validated_submitted_patch_identity",
        lambda *_args, **_kwargs: {"submitted_patch_identity": True},
    )
    monkeypatch.setattr(
        grader_smoke, "observed_target_digest", lambda _grade: f"sha256:{DIGEST}"
    )
    raw_ref = {
        "path": "restricted/fixture.bin",
        "bytes": 1,
        "sha256": hashlib.sha256(b"x").hexdigest(),
    }
    monkeypatch.setattr(
        grader_smoke,
        "_grader_test_evidence",
        lambda *_args, **_kwargs: (
            raw_ref,
            raw_ref,
            {"resolved": False},
            {"patch_applied": True, "tests_executed": True},
            raw_ref,
            {"status_code": 0, "acceptance": "ZERO_EXIT"},
        ),
    )
    monkeypatch.setattr(
        grader_smoke,
        "_smoke_execution_summary",
        lambda *_args, **_kwargs: {"status": "FAIL", "failures": [targets[0]["target_id"]]},
    )

    output_root = tmp_path / "output"
    with pytest.raises(grader_smoke.BenchmarkExecutionError) as caught:
        grader_smoke.run_smoke(approval_path, output_root, tmp_path / "images")

    assert str(caught.value).startswith(
        "TRIMEM_V1_GRADER_SMOKE_FAIL: frozen GOLD/NOOP outcome mismatch:"
    )
    assert any(
        "post-mismatch image cleanup also failed" in note
        for note in getattr(caught.value, "__notes__", ())
    )
    assert calls == {"before": [0], "after": [0], "grade": [0]}
    records = list(output_root.rglob("*.result.json"))
    assert len(records) == 1
    terminal = json.loads(records[0].read_text(encoding="utf-8"))
    assert terminal["primary_failure"]["stage"] == "scientific_outcome"
    assert terminal["authoritative_cell"] is False
    assert terminal["official_final_report_resolved"] is False
    assert terminal["scientific_resolved"] is False
    assert any(
        "post-mismatch image cleanup also failed" in reason
        for reason in terminal["secondary_evidence_failures"]
    )


def _authority_promotion_fixture(
    root: Path,
) -> tuple[list[tuple[Path, dict[str, object]]], list[dict[str, object]]]:
    terminal_records: list[tuple[Path, dict[str, object]]] = []
    candidates: list[dict[str, object]] = []
    for index in range(12):
        task_dir = root / f"{index:03d}-target-{index}"
        task_dir.mkdir(parents=True)
        record = _built_terminal(index, normalized=True)
        path = task_dir / f"target-{index}.result.json"
        grader_smoke.write_json(path, record)
        terminal_records.append((path, record))
        candidates.append({**record, "authoritative_cell": True})
    return terminal_records, candidates


def test_authority_promotion_staging_write_failure_keeps_all_false_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "official-smoke"
    terminal_records, candidates = _authority_promotion_fixture(output_root)
    production_write_json = grader_smoke.write_json
    staged_writes = 0

    def fail_mid_staging(path: Path, value: object) -> None:
        nonlocal staged_writes
        if ".authority-promotion." in path.as_posix() and path.name.endswith(
            ".result.json"
        ):
            staged_writes += 1
            if staged_writes == 6:
                raise OSError("injected authority staging write failure")
        production_write_json(path, value)

    monkeypatch.setattr(grader_smoke, "write_json", fail_mid_staging)
    with pytest.raises(
        grader_smoke.BenchmarkExecutionError,
        match="atomic terminal authority promotion failed",
    ):
        grader_smoke._commit_authoritative_campaign(
            output_root=output_root,
            terminal_records=terminal_records,
            authority_candidates=candidates,
            report={"status": "PASS"},
        )

    persisted = [
        json.loads(path.read_text(encoding="utf-8"))
        for path, _record in terminal_records
    ]
    assert staged_writes == 6
    assert all(record["authoritative_cell"] is False for record in persisted)


def test_authority_promotion_commits_twelve_all_true_records_atomically(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "official-smoke"
    terminal_records, candidates = _authority_promotion_fixture(output_root)

    grader_smoke._commit_authoritative_campaign(
        output_root=output_root,
        terminal_records=terminal_records,
        authority_candidates=candidates,
        report={"status": "PASS"},
    )

    persisted = [
        json.loads((output_root / path.relative_to(output_root)).read_text(encoding="utf-8"))
        for path, _record in terminal_records
    ]
    assert len(persisted) == 12
    assert all(record["authoritative_cell"] is True for record in persisted)


def test_authority_promotion_retains_only_backup_when_swap_and_restore_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "official-smoke"
    terminal_records, candidates = _authority_promotion_fixture(output_root)
    production_replace = grader_smoke.os.replace

    def fail_final_swaps(source: object, destination: object) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path == output_root and source_path.name in {
            "replacement",
            "original",
        }:
            raise OSError("injected final swap/restoration failure")
        production_replace(source, destination)

    monkeypatch.setattr(grader_smoke.os, "replace", fail_final_swaps)
    with pytest.raises(
        grader_smoke.BenchmarkExecutionError,
        match="atomic terminal authority promotion failed",
    ):
        grader_smoke._commit_authoritative_campaign(
            output_root=output_root,
            terminal_records=terminal_records,
            authority_candidates=candidates,
            report={"status": "PASS"},
        )

    recovery_roots = list(
        tmp_path.glob(".official-smoke.authority-promotion.*")
    )
    assert len(recovery_roots) == 1
    backup_records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((recovery_roots[0] / "original").rglob("*.result.json"))
    ]
    assert len(backup_records) == 12
    assert all(record["authoritative_cell"] is False for record in backup_records)
