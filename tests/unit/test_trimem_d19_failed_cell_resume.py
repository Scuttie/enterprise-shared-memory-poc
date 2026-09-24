from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enterprise_memory.trimem.accounting import RawEvidenceLedger, canonical_bytes
from enterprise_memory.trimem.agent_runtime import (
    CANONICAL_FAILED_CELL_NOOP,
    InjectedCrash,
    CodingTask,
    NoMemoryController,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.checkpoint import (
    CheckpointMismatch,
    FileCheckpointStore,
)
from enterprise_memory.trimem.gateway import (
    GatewayRequest,
    GatewayResponse,
    ModelPreflightFailure,
    gateway_request_sha256,
)
from enterprise_memory.trimem.grader import GradeResult
from enterprise_memory.trimem.runtime_lock import RuntimeLock


class _ContainedFailureModel:
    """Credential-free gateway: decompose fails locally, extraction succeeds."""

    def __init__(self) -> None:
        self.preflight_calls: list[str] = []
        self.provider_calls: list[str] = []
        self.crash_before_extraction_provider_once = False

    def preview_reservation(self, request: GatewayRequest):
        self.preflight_calls.append(request.logical_call_id)
        if request.call_kind == "decompose":
            raise ModelPreflightFailure(
                "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
                request_sha256=gateway_request_sha256(request),
                logical_call_id=request.logical_call_id,
            )
        return None

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        if (
            request.call_kind == "extract"
            and self.crash_before_extraction_provider_once
        ):
            self.crash_before_extraction_provider_once = False
            raise InjectedCrash(
                "after durable extraction request before provider send"
            )
        self.provider_calls.append(request.logical_call_id)
        assert request.call_kind == "extract"
        return GatewayResponse(
            text=json.dumps({
                "episode": {
                    "summary": "The local preflight failure was contained.",
                    "action": "Grade the canonical failed-cell patch.",
                    "outcome": "failed",
                },
                "semantic_candidate": None,
            }),
            provider="credential-free-d19-fixture",
            model="d19-fixture-v1",
            input_tokens=7,
            output_tokens=5,
            cached_input_tokens=0,
            reasoning_tokens=0,
            wall_time_ms=0,
            paid=False,
        )

    def replay_terminal(self, request: GatewayRequest):
        return None

    def request_lifecycle(self, request: GatewayRequest):
        return {
            "state": "NOT_PREPARED",
            "request_sha256": gateway_request_sha256(request),
            "journal_present": False,
            "ledger_reservation_present": False,
            "provider_send_started": False,
        }


class _CountingGrader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def grade(self, request) -> GradeResult:
        self.calls.append(request.task_id)
        return GradeResult(
            task_id=request.task_id,
            resolved=False,
            exit_code=0,
            stdout="credential-free grader fixture\n",
            stderr="",
            report={"task_id": request.task_id, "resolved": False},
            grader_id="d19-failed-cell-resume-fixture",
            container_digest="fixture@sha256:" + "b" * 64,
            official=False,
            wall_time_ms=0,
            container_started=False,
            status="success",
        )


def _task() -> CodingTask:
    return CodingTask(
        task_id="d19-failed-cell-resume",
        org_id="org",
        user_id="fixture",
        repository="example/repo",
        commit="c" * 40,
        instruction="Contain a local preflight failure without external calls.",
        files={"value.py": "VALUE = 1\n"},
        editable_paths=("value.py",),
    )


def _runtime(root: Path, model, grader) -> TriMemAgentRuntime:
    return TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=model,
        grader_gateway=grader,
        memory_controller=NoMemoryController(),
        evidence=RawEvidenceLedger(root / "evidence"),
        checkpoint_store=FileCheckpointStore(root / "checkpoints"),
    )


def _events(root: Path) -> list[dict]:
    path = root / "evidence" / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    ("control", "message", "intermediate_state"),
    [
        (
            "crash_after_failed_cell_marker",
            "failed-cell marker",
            "CELL_FAILURE_PREPARED",
        ),
        (
            "crash_after_failed_grader_request",
            "failed-cell grader request",
            "CELL_FAILURE_MARKED",
        ),
        (
            "crash_after_grader_result",
            "failed-cell grader result",
            "CELL_FAILURE_MARKED",
        ),
        (
            "crash_after_extraction_model_response",
            "extraction model response",
            "CELL_FAILURE_GRADED",
        ),
        (
            "crash_after_extraction_evidence",
            "failed-cell extraction evidence",
            "CELL_FAILURE_GRADED",
        ),
        (
            "crash_after_finished_evidence",
            "failed-cell terminal evidence",
            "CELL_FAILURE_LIFECYCLE_CREDITED",
        ),
    ],
)
def test_failed_cell_crash_windows_resume_once(
    tmp_path, control, message, intermediate_state
):
    model = _ContainedFailureModel()
    grader = _CountingGrader()
    task = _task()
    first = _runtime(tmp_path, model, grader)

    with pytest.raises(InjectedCrash, match=message):
        first.run(task, arm="M2", run_id="stream-00-M2", **{control: True})

    checkpoint = first.checkpoints.load(
        "stream-00-M2", required_config_hashes=None
    )
    assert checkpoint.state == intermediate_state

    resumed = _runtime(tmp_path, model, grader)
    result = resumed.run(
        task, arm="M2", run_id="stream-00-M2", resume=True
    )

    terminal = resumed.checkpoints.load(
        "stream-00-M2", required_config_hashes=None
    )
    assert terminal.state == "DONE"
    assert result.cell_status == "CELL_SCIENTIFIC_FAILURE"
    assert result.model_failure_class == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    assert result.failure_metadata == {
        "stage": "PREFLIGHT",
        "call_kind": "decompose",
        "provider_request_started": False,
        "ledger_reservation_created": False,
    }
    assert result.patch == CANONICAL_FAILED_CELL_NOOP
    assert result.accounting["summary"]["grader_calls"] == 1
    assert result.accounting["summary"]["model_gateway_calls"] == 1
    assert grader.calls == [task.task_id]
    assert model.provider_calls == [f"{task.task_id}:M2:extract:0001"]
    rows = _events(tmp_path)
    assert sum(row["event_type"] == "cell_scientific_failure" for row in rows) == 1
    assert sum(row["event_type"] == "grader_request" for row in rows) == 1
    assert sum(row["event_type"] == "grader_result" for row in rows) == 1
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("call_kind") == "extract"
        for row in rows
    ) == 1
    assert sum(
        row["event_type"] == "model_response"
        and row["payload"].get("logical_call_id")
        == f"{task.task_id}:M2:extract:0001"
        for row in rows
    ) == 1
    assert sum(row["event_type"] == "experience_extracted" for row in rows) == 1
    assert sum(row["event_type"] == "agent_run_finished" for row in rows) == 1


def test_failed_cell_contract_corruption_is_global_and_has_no_retry(tmp_path):
    model = _ContainedFailureModel()
    grader = _CountingGrader()
    task = _task()
    runtime = _runtime(tmp_path, model, grader)
    with pytest.raises(InjectedCrash, match="failed-cell marker"):
        runtime.run(
            task,
            arm="M2",
            run_id="stream-00-M2",
            crash_after_failed_cell_marker=True,
        )

    checkpoint_path = tmp_path / "checkpoints" / "stream-00-M2.json"
    digest_path = tmp_path / "checkpoints" / "stream-00-M2.sha256"
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    payload["terminal_payload"]["failed_cell_contract"]["failure_class"] = (
        "TAMPERED_FAILURE"
    )
    raw = canonical_bytes(payload)
    checkpoint_path.write_bytes(raw)
    digest_path.write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii")

    resumed = _runtime(tmp_path, model, grader)
    with pytest.raises(CheckpointMismatch, match="contract"):
        resumed.run(task, arm="M2", run_id="stream-00-M2", resume=True)
    assert grader.calls == []
    assert model.provider_calls == []


def test_failed_cell_extraction_request_only_rule_a_sends_once(tmp_path):
    model = _ContainedFailureModel()
    model.crash_before_extraction_provider_once = True
    grader = _CountingGrader()
    task = _task()
    first = _runtime(tmp_path, model, grader)

    with pytest.raises(InjectedCrash, match="before provider send"):
        first.run(task, arm="M2", run_id="stream-00-M2")

    checkpoint = first.checkpoints.load(
        "stream-00-M2", required_config_hashes=None
    )
    assert checkpoint.state == "CELL_FAILURE_GRADED"
    before = _events(tmp_path)
    assert [row["event_type"] for row in before[-1:]] == ["model_request"]
    assert model.provider_calls == []

    resumed = _runtime(tmp_path, model, grader)
    result = resumed.run(
        task, arm="M2", run_id="stream-00-M2", resume=True
    )

    assert result.cell_status == "CELL_SCIENTIFIC_FAILURE"
    assert result.extraction_status == "SUCCESS"
    assert model.provider_calls == [f"{task.task_id}:M2:extract:0001"]
    after = _events(tmp_path)
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("call_kind") == "extract"
        for row in after
    ) == 1
    assert sum(
        row["event_type"] == "model_response"
        and row["payload"].get("logical_call_id")
        == f"{task.task_id}:M2:extract:0001"
        for row in after
    ) == 1
