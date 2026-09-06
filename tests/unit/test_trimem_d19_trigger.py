from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d19 as trigger  # noqa: E402
import trimem_development_trigger_preflight as preflight  # noqa: E402


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--quiet")
    _git(repository, "config", "user.email", "d19-trigger@example.invalid")
    _git(repository, "config", "user.name", "D1.9 trigger fixture")
    (repository / "base.txt").write_bytes(b"immutable base\n")
    return repository, _commit(repository, "fixture: immutable base")


def _remote_gates(source_head: str) -> dict[str, object]:
    return {
        "source_head": source_head,
        "all_required_workflows_passed": True,
        "workflows": [
            {
                "workflow_path": path,
                "head_sha": source_head,
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            }
            for path in trigger.REQUIRED_REMOTE_GATE_WORKFLOWS
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


def _previous_receipt() -> dict[str, object]:
    return {
        "schema": trigger.PREVIOUS_RECEIPT_SCHEMA,
        "status": "TERMINAL_PRESERVED",
        "endpoint": "TRIMEM_V1_DEV_INCOMPLETE",
        "primary_failure": trigger.PREVIOUS_FAILURE_SUBTYPE,
        "classification": trigger.AMENDMENT_CLASSIFICATION,
        "scientific_status": "INTERRUPTED_BEFORE_FIRST_TERMINAL_CELL",
        "workflow_run": {
            "id": trigger.PREVIOUS_RUN_ID,
            "attempt": 1,
            "head_sha": trigger.PREVIOUS_EXECUTION_HEAD,
            "source_head_sha": trigger.PREVIOUS_SOURCE_HEAD,
            "conclusion": "failure",
        },
        "scientific_usage": {
            "decomposition_calls": 1,
            "solve_calls": 7,
            "extraction_calls": 0,
            "paid_model_calls": 8,
            "input_tokens": 60_546,
            "cached_input_tokens": 0,
            "output_tokens": 7_448,
            "reasoning_tokens": 1_597,
            "total_usd": "0.078925500000",
        },
        "canary_usage": {
            "paid_model_calls": 1,
            "input_tokens": 880,
            "cached_input_tokens": 0,
            "output_tokens": 51,
            "reasoning_tokens": 35,
            "total_usd": "0.000889500000",
        },
        "total_usage": {
            "paid_model_calls": 9,
            "input_tokens": 61_426,
            "cached_input_tokens": 0,
            "output_tokens": 7_499,
            "reasoning_tokens": 1_632,
            "total_usd": "0.079815000000",
        },
        "terminal_cells": 0,
        "planned_cells": 72,
        "official_grader_runs": 0,
        "performance_measured": False,
    }


def test_d19_contract_selects_only_fresh_010_authority() -> None:
    assert trigger.REQUEST_ID == "TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_010"
    assert trigger.SENTINEL_PATH.endswith("DEVELOPMENT_TUNING_EXEC_REQUEST_010.json")
    assert trigger.PREVIOUS_SENTINEL_PATH.endswith(
        "DEVELOPMENT_TUNING_EXEC_REQUEST_009.json"
    )
    assert trigger.REQUIRED_EXTERNAL_AUTHORIZATION == (
        "TRIMEM_V1_DEVELOPMENT_TUNING_CONTEXT_RECOVERY_EXEC_APPROVED_ONCE"
    )
    assert trigger.EXPECTED_CONCURRENCY_GROUP.endswith("exec-010")
    assert trigger.MODEL_ID == "gpt-5.4-mini-2026-03-17"


def test_d19_preserves_history_across_source_and_exact_010_trigger_phases() -> None:
    head = _git(
        ROOT,
        "log",
        "-1",
        "--diff-filter=A",
        "--format=%H",
        "--",
        trigger.SENTINEL_PATH,
    )
    assert head
    assert _git(ROOT, "merge-base", "--is-ancestor", head, "HEAD") == ""
    assert len(trigger.HISTORICAL_REQUEST_SHA256) == 9
    for path, expected in trigger.HISTORICAL_REQUEST_SHA256.items():
        assert hashlib.sha256(trigger.commit_bytes(ROOT, head, path)).hexdigest() == expected
    sentinel = ROOT / trigger.SENTINEL_PATH
    if sentinel.exists():
        validated = trigger.validate_sentinel_commit(
            ROOT,
            head,
            require_checked_out_head=False,
        )
        assert validated["request_id"] == trigger.REQUEST_ID
        assert validated["source_head"] == _git(ROOT, "rev-parse", f"{head}^")
    else:
        assert _git(ROOT, "log", "--format=%H", "HEAD", "--", trigger.SENTINEL_PATH) == ""


def test_d19_previous_failure_receipt_is_exact_and_not_a_result() -> None:
    receipt = _previous_receipt()
    assert trigger.validate_previous_execution_receipt(
        trigger.canonical_bytes(receipt)
    ) == receipt
    receipt["terminal_cells"] = 1
    with pytest.raises(trigger.DevelopmentTriggerD19Error, match="scientific boundary"):
        trigger.validate_previous_execution_receipt(trigger.canonical_bytes(receipt))


def test_d19_remote_gates_require_all_exact_head_first_attempts() -> None:
    source = "a" * 40
    gates = _remote_gates(source)
    assert trigger._remote_gates(gates, source) == gates
    gates["workflows"][2]["run_attempt"] = 2  # type: ignore[index]
    with pytest.raises(trigger.DevelopmentTriggerD19Error, match="exact-head success"):
        trigger._remote_gates(gates, source)


def test_d19_request_has_zero_pre_execution_actuals_and_unchanged_caps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = "a" * 40
    gates = _remote_gates(source)
    bindings = {name: "sha256:" + "b" * 64 for name in trigger.BOUND_PATHS}
    development = {
        "targets": [{"instance_id": f"target-{index:02d}"} for index in range(12)]
    }
    hard_caps = {
        "benchmark_grader_containers": 72,
        "decomposition_calls": 72,
        "extraction_calls": 72,
        "input_tokens": 36_004_096,
        "max_input_tokens_per_task_arm": 500_000,
        "max_model_calls_per_task_arm": 26,
        "model_calls": 1_873,
        "output_tokens": 4_720_640,
        "paid_model_calls": 1_873,
        "protocol_canary_calls": 1,
        "scientific_generation_calls": 1_872,
        "solve_calls": 1_728,
        "task_arm_runs": 72,
        "total_usd": 50.0,
        "uncached_token_cost_ceiling_usd": 48.245952,
    }
    monkeypatch.setattr(trigger, "_validate_source", lambda *_args: bindings)
    monkeypatch.setattr(trigger, "_remote_gates", lambda value, _source: dict(value))

    def fake_commit_bytes(_repository: Path, _commit: str, path: str) -> bytes:
        value = (
            development
            if path == "configs/trimem_v1/development_manifest.json"
            else {"phase_hard_caps": {trigger.EXPECTED_PHASE: hard_caps}}
        )
        return trigger.canonical_bytes(value)

    monkeypatch.setattr(trigger, "commit_bytes", fake_commit_bytes)
    request = trigger.build_request(
        tmp_path, source_head=source, remote_gate_evidence=gates
    )
    assert request["hard_caps"] == hard_caps
    assert request["scientific_workload"]["task_arm_runs"] == 72
    assert request["scientific_workload"]["grader_containers"] == 72
    assert len(request["scientific_workload"]["target_order"]) == 12
    assert request["pre_execution_actuals"] == {
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
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_009_rerun_or_attempt_2" in request[
        "prohibited_actions"
    ]
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_011" in request["prohibited_actions"]


def test_d19_correction_source_validation_does_not_require_sentinel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = "a" * 40
    monkeypatch.setattr(
        trigger,
        "git",
        lambda _repository, *arguments: source + "\n"
        if arguments == ("rev-parse", "HEAD")
        else pytest.fail(f"unexpected git arguments: {arguments!r}"),
    )
    monkeypatch.setattr(
        trigger,
        "_validate_source",
        lambda _repository, selected: {"freeze_sha256": "sha256:" + "b" * 64}
        if selected == source
        else pytest.fail("wrong correction source"),
    )
    result = trigger.validate_correction_source(tmp_path, source)
    assert result["status"] == "PASS"
    assert result["sentinel_present"] is False
    assert result["model_calls"] == result["grader_containers"] == 0


def test_d19_sentinel_commit_must_add_only_010(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, parent = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"fixture":true}\n')
    after = _commit(repository, "control: add D1.9 sentinel only")
    monkeypatch.setattr(
        trigger,
        "validate_request",
        lambda _repository, raw, *, source_head: {
            "raw": raw.decode("utf-8"),
            "source_head": source_head,
        },
    )
    validated = trigger.validate_sentinel_commit(
        repository, after, expected_parent=parent
    )
    assert validated["source_head"] == parent


def test_d19_sentinel_commit_rejects_any_second_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repository, parent = _repository(tmp_path)
    sentinel = repository / trigger.SENTINEL_PATH
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b'{"fixture":true}\n')
    (repository / "unexpected.txt").write_bytes(b"not sentinel-only\n")
    after = _commit(repository, "control: invalid multi-file trigger")
    monkeypatch.setattr(trigger, "validate_request", pytest.fail)
    with pytest.raises(trigger.DevelopmentTriggerD19Error, match="sentinel-only"):
        trigger.validate_sentinel_commit(
            repository, after, expected_parent=parent
        )


def test_d19_branch_trigger_requires_exact_push_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    before, after = "a" * 40, "b" * 40
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"before": before, "after": after, "forced": False}),
        encoding="utf-8",
    )
    gates = _remote_gates(before)
    monkeypatch.setattr(
        trigger,
        "validate_sentinel_commit",
        lambda _repository, selected, *, expected_parent: {
            "remote_gate_evidence": gates,
            "source_head": expected_parent,
            "after": selected,
        },
    )
    monkeypatch.setattr(trigger, "collect_remote_gate_evidence", lambda _head: gates)
    monkeypatch.setattr(
        trigger, "validate_secret_free_preflight", lambda *_args: None
    )
    environment = {
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": trigger.EXPECTED_REPOSITORY,
        "GITHUB_REF": trigger.EXPECTED_REF,
        "GITHUB_WORKFLOW_REF": trigger.EXPECTED_WORKFLOW_REF,
        "GITHUB_SHA": after,
        "GITHUB_WORKFLOW_SHA": after,
    }
    result = trigger.validate_branch_trigger(ROOT, event, environ=environment)
    assert result["status"] == "PASS"
    assert result["source_head"] == before
    environment["GITHUB_RUN_ATTEMPT"] = "2"
    with pytest.raises(trigger.DevelopmentTriggerD19Error, match="attempt"):
        trigger.validate_branch_trigger(ROOT, event, environ=environment)


def test_shared_secret_free_preflight_recognizes_active_d19_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = (ROOT / preflight.WORKFLOW_PATH).read_bytes()
    monkeypatch.setattr(
        preflight,
        "_commit_bytes",
        lambda _repository, _commit, path: workflow
        if path == preflight.WORKFLOW_PATH
        else pytest.fail(f"unexpected path: {path}"),
    )
    preflight._validate_secret_free_preflight(ROOT, "a" * 40, {})
