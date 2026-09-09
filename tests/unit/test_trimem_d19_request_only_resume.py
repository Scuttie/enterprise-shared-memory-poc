from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from enterprise_memory.providers.base import SINGLE_FUNCTION_CALL
from enterprise_memory.trimem.accounting import (
    RawEvidenceLedger,
    canonical_bytes,
    sha256_bytes,
)
from enterprise_memory.trimem.agent_runtime import (
    CodingTask,
    InjectedCrash,
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
from enterprise_memory.trimem.function_tools import (
    FUNCTION_TOOLS_SHA256,
    PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256,
    detached_pre_d19_replay_only_function_tools,
    detached_function_tools,
    validate_function_arguments,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock


ROOT = Path(__file__).resolve().parents[2]
HISTORICAL_BOUNDARY_FIXTURE = (
    ROOT
    / "artifacts/trimem_v1/development_tuning_exec/exec-009/"
    "request-only-boundary-fixture.json"
)


def _captured_boundary() -> dict:
    value = json.loads(HISTORICAL_BOUNDARY_FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


class _ZeroContainerGrader:
    def grade(self, request):
        return GradeResult(
            task_id=request.task_id,
            resolved=False,
            exit_code=1,
            stdout="",
            stderr="fixture unresolved",
            report={"task_id": request.task_id, "resolved": False},
            grader_id="d19-request-only-fixture",
            container_digest="replay@sha256:" + "a" * 64,
            official=False,
            wall_time_ms=0,
            container_started=False,
        )


def _response(request: GatewayRequest, tool: str, arguments: dict) -> GatewayResponse:
    encoded = json.dumps(
        arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return GatewayResponse(
        text="",
        provider="credential-free-d19-fixture",
        model="d19-fixture-v1",
        input_tokens=1,
        output_tokens=1,
        cached_input_tokens=0,
        reasoning_tokens=0,
        wall_time_ms=0,
        paid=False,
        response_mode=SINGLE_FUNCTION_CALL,
        function_call_id="fixture-" + request.logical_call_id,
        function_name=tool,
        function_arguments=encoded,
        function_arguments_sha256=sha256_bytes(encoded.encode("utf-8")),
    )


class _HistoricalRequestOnlyGateway:
    """Credential-free stand-in for the exact `_009` pre-send crash window."""

    def __init__(self, *, lifecycle_state: str | None):
        self.lifecycle_state = lifecycle_state
        if lifecycle_state is None:
            # getattr(..., "request_lifecycle") must truthfully be unavailable.
            self.request_lifecycle = None
        self.stopped_before_provider = False
        self.gateway_entries: list[str] = []
        self.provider_started: list[str] = []
        self.fail_fallback_extraction = False
        self.lifecycle_hash_override: str | None = None
        self.crash_lifecycle_once = False
        self.enforce_context_preflight = False

    def preview_reservation(self, request: GatewayRequest):
        if (
            self.enforce_context_preflight
            and len(request.prompt.encode("utf-8")) + 4_096 > 200_704
        ):
            raise ModelPreflightFailure(
                "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
                request_sha256=gateway_request_sha256(request),
                logical_call_id=request.logical_call_id,
            )
        return None

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        self.gateway_entries.append(request.logical_call_id)
        if request.call_kind == "decompose":
            return GatewayResponse(
                text=json.dumps({
                    "subtasks": [
                        {
                            "id": "inspect-repository",
                            "objective": "inspect the fixture",
                            "predicted_operation": "inspect repository",
                            "depends_on": [],
                            "files": ["src/value.py"],
                        },
                        {
                            "id": "finish-recovery",
                            "objective": "finish after the recovery boundary",
                            "predicted_operation": "complete recovery",
                            "depends_on": ["inspect-repository"],
                            "files": ["src/value.py"],
                        },
                    ]
                }),
                provider="credential-free-d19-fixture",
                model="d19-fixture-v1",
                input_tokens=1,
                output_tokens=1,
                cached_input_tokens=0,
                reasoning_tokens=0,
                wall_time_ms=0,
                paid=False,
            )
        if request.call_kind == "extract":
            if self.fail_fallback_extraction:
                raise ModelPreflightFailure(
                    "TASK_ARM_INPUT_POOL_EXHAUSTED",
                    request_sha256=gateway_request_sha256(request),
                    logical_call_id=request.logical_call_id,
                )
            return GatewayResponse(
                text=json.dumps({
                    "episode": {
                        "summary": "request-only fixture was contained",
                        "action": "retain the partial cell",
                        "outcome": "failed",
                    },
                    "semantic_candidate": None,
                }),
                provider="credential-free-d19-fixture",
                model="d19-fixture-v1",
                input_tokens=1,
                output_tokens=1,
                cached_input_tokens=0,
                reasoning_tokens=0,
                wall_time_ms=0,
                paid=False,
            )
        if request.step_no == 8 and not self.stopped_before_provider:
            self.stopped_before_provider = True
            # RecordingModelGateway has fsynced model_request, but this fake
            # provider boundary has not started and creates no reservation.
            raise InjectedCrash("historical _009 request-only boundary")
        self.provider_started.append(request.logical_call_id)
        if request.step_no < 7:
            return _response(
                request,
                "list_files",
                {"path_prefix": None, "start_after": None, "limit": 1},
            )
        if request.step_no == 7:
            return _response(
                request,
                "complete_subtask",
                {"evidence": "first subtask finished before step 8"},
            )
        return _response(
            request,
            "complete_subtask",
            {"evidence": "request-only recovery issued exactly once"},
        )

    def _request_lifecycle(self, request: GatewayRequest):
        if self.crash_lifecycle_once:
            self.crash_lifecycle_once = False
            raise InjectedCrash("after durable legacy normalization")
        state = str(self.lifecycle_state)
        started = state in {
            "PROVIDER_SEND_STARTED",
            "PROVIDER_TERMINAL_SUCCESS",
            "PROVIDER_TERMINAL_FAILURE",
            "PROVIDER_OUTCOME_UNKNOWN",
        }
        return {
            "state": state,
            "request_sha256": (
                self.lifecycle_hash_override or gateway_request_sha256(request)
            ),
            "journal_present": state not in {"NOT_PREPARED", "NOT_STARTED"},
            "ledger_reservation_present": False,
            "provider_send_started": started,
        }

    # Keep the method definition separate so the instance can shadow it with
    # None for the unavailable-lifecycle fixture.
    request_lifecycle = _request_lifecycle


class _TerminalReplayGateway(_HistoricalRequestOnlyGateway):
    def replay_terminal(self, request: GatewayRequest):
        if (
            request.call_kind != "solve"
            or request.step_no != 8
            or not self.stopped_before_provider
        ):
            return None
        response = _response(
            request,
            "complete_subtask",
            {"evidence": "durable terminal result replayed"},
        )
        return replace(response, terminal_outcome_replayed=True)


class _BrokenStartedReplayGateway(_HistoricalRequestOnlyGateway):
    """Advertises a started request but violates the replay contract."""

    def replay_terminal(self, request: GatewayRequest):
        return None


class _ContradictoryNotStartedGateway(_HistoricalRequestOnlyGateway):
    def _request_lifecycle(self, request: GatewayRequest):
        value = dict(super()._request_lifecycle(request))
        value["ledger_reservation_present"] = True
        return value

    request_lifecycle = _request_lifecycle


def _events(evidence: RawEvidenceLedger) -> list[dict]:
    return [
        json.loads(line)
        for line in evidence.events_path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _historical_step8_fixture(
    tmp_path: Path,
    gateway,
    *,
    lone_request_suffix: bool = False,
    legacy_prompt_bytes: int | None = None,
):
    lock = RuntimeLock()
    captured = _captured_boundary()
    task = CodingTask(
        task_id=captured["cell"]["target_id"],
        org_id="org",
        user_id="fixture",
        repository="django/django",
        commit=captured["cell"]["base_commit"],
        instruction="Exercise the historical request-only resume boundary.",
        files={"src/value.py": "VALUE = 1\n"},
        editable_paths=("src/value.py",),
    )
    evidence = RawEvidenceLedger(tmp_path / "evidence")
    checkpoints = FileCheckpointStore(tmp_path / "new-checkpoints")
    runtime = TriMemAgentRuntime(
        runtime_lock=lock,
        model_gateway=gateway,
        grader_gateway=_ZeroContainerGrader(),
        memory_controller=NoMemoryController(),
        evidence=evidence,
        checkpoint_store=checkpoints,
    )
    with pytest.raises(InjectedCrash, match="historical _009"):
        runtime.run(task, arm="M2")

    current = checkpoints.load(
        task.task_id + "-M2", required_config_hashes=None
    )
    assert current.state == "RECALL_PREPARED"
    assert current.next_step_no == 8
    rows = _events(evidence)
    request = rows[-1]
    recall = rows[-2]
    assert request["event_type"] == "model_request"
    assert recall["event_type"] == "memory_recall"

    # Convert only the last request envelope to its exact pre-D1.9 schema and
    # hash.  The immutable prompt blob and preceding recall chain are reused.
    request_payload = dict(request["payload"])
    request_payload.pop("prompt_projection", None)
    prompt_ref = request_payload["prompt"]
    prompt = (evidence.blob_dir / prompt_ref["sha256"]).read_text(
        encoding="utf-8"
    )
    if legacy_prompt_bytes is not None:
        prompt = "x" * legacy_prompt_bytes
        request_payload["prompt"] = evidence.put_blob(prompt)
    legacy_request = GatewayRequest(
        task_id=task.task_id,
        arm="M2",
        step_no=8,
        call_kind="solve",
        logical_call_id=f"{task.task_id}:M2:solve:0008",
        prompt=prompt,
        max_output_tokens=request_payload["max_output_tokens"],
        org_id=task.org_id,
        active_node_id=current.active_node_id,
        response_mode=SINGLE_FUNCTION_CALL,
        function_tools=detached_pre_d19_replay_only_function_tools(),
        function_tools_sha256=PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256,
        tool_choice="required",
        parallel_tool_calls=False,
        prompt_projection=None,
    )
    request_payload["request_sha256"] = gateway_request_sha256(legacy_request)
    request_payload["function_tools_sha256"] = (
        PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256
    )
    body = {
        key: value for key, value in request.items() if key != "event_hash"
    }
    body["payload"] = request_payload
    rows[-1] = {**body, "event_hash": sha256_bytes(canonical_bytes(body))}
    evidence.events_path.write_bytes(
        b"".join(canonical_bytes(row) + b"\n" for row in rows)
    )
    evidence = RawEvidenceLedger(tmp_path / "evidence")

    # The historical checkpoint predates both recall and request and has no
    # prepared_request member.  Accounting contains seven completed solve
    # calls; step 8 has neither response, paid call, nor ledger reservation.
    legacy = replace(
        current,
        generation=1,
        state="RUNNING",
        prepared_request=None,
        evidence_event_hash=(
            recall["event_hash"]
            if lone_request_suffix
            else recall["previous_event_hash"]
        ),
        previous_checkpoint_hash="0" * 64,
    )
    legacy_store = FileCheckpointStore(tmp_path / "legacy-checkpoint")
    legacy_store.save(legacy)
    runtime.evidence = evidence
    runtime.checkpoints = legacy_store
    return runtime, task, evidence, gateway


def test_pre_d19_function_contract_is_exact_and_replay_only():
    legacy = detached_pre_d19_replay_only_function_tools()
    live = detached_function_tools()

    assert PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256 == (
        "5c035f219b9e023c2fb5c7792a7a51c0c4c783a718a9367d723e26b7253039eb"
    )
    assert PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256 != FUNCTION_TOOLS_SHA256
    assert legacy[0]["name"] == live[0]["name"] == "list_files"
    assert legacy[0]["parameters"]["properties"] == {}
    assert legacy[0]["parameters"]["required"] == []
    assert live[0]["parameters"]["required"] == [
        "path_prefix", "start_after", "limit"
    ]
    with pytest.raises(ValueError, match="SCHEMA_FAILURE"):
        validate_function_arguments("list_files", {})


def test_exact_009_restricted_boundary_identities_are_frozen_without_payload():
    captured = _captured_boundary()
    assert captured["status"] == "EXACT_SANITIZED_CONTENT_ADDRESS_FIXTURE"
    assert captured["workflow_run"] == {
        "id": 33_979_936_824,
        "attempt": 1,
        "head_sha": "db548919f29fd044cce1e066c74d2a7040a28f49",
        "source_head_sha": "ef10493a7352bd6cf914e5e465a9580be6462eb0",
    }
    assert captured["captured_restricted_identities"]["list_files_result_blob"] == {
        "bytes": 319_417,
        "sha256": "29345b6f8ea4540d6678d0886f96a4099668d885f31121b23ea6ce4d6961244f",
    }
    assert captured["captured_restricted_identities"]["step_8_prompt_blob"] == {
        "bytes": 709_714,
        "sha256": "74208572ed213779b9a232b1ecb2a1b986a1db0a29459dd1a51acb2c17dfa894",
    }
    assert captured["cell"]["step_8_provider_call"] is False
    assert captured["cell"]["step_8_ledger_reservation"] is False
    assert captured["custody"]["restricted_payload_committed"] is False
    assert captured["custody"]["restricted_payload_encrypted"] is True


def test_exact_009_request_only_fixture_is_normalized_and_contained(tmp_path):
    gateway = _HistoricalRequestOnlyGateway(lifecycle_state=None)
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path, gateway, lone_request_suffix=True
    )
    gateway.fail_fallback_extraction = True

    result = runtime.run(task, arm="M2", resume=True)

    assert result.cell_status == "CELL_SCIENTIFIC_FAILURE"
    assert result.model_failure_class == "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN"
    assert result.failure_metadata == {
        "stage": "PROVIDER_LIFECYCLE",
        "call_kind": "solve",
        "provider_request_started": True,
        "ledger_reservation_created": False,
    }
    assert result.extraction_status == "MEMORY_EXTRACTION_FAILED"
    assert f"{task.task_id}:M2:solve:0008" not in gateway.provider_started
    assert result.accounting["summary"]["by_call_kind"]["solve"]["calls"] == 7
    events = _events(evidence)
    assert any(
        row["event_type"] == "legacy_request_only_normalized"
        and row["payload"]["from_checkpoint_state"] == "RUNNING"
        and row["payload"]["to_checkpoint_state"] == "RECALL_PREPARED"
        for row in events
    )
    normalization = next(
        row["payload"]
        for row in events
        if row["event_type"] == "legacy_request_only_normalized"
    )
    assert normalization["recall_binding_source"] == (
        "CHECKPOINTED_MEMORY_CONTROLLER_STATE"
    )
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id")
        == f"{task.task_id}:M2:solve:0008"
        for row in events
    ) == 1


def test_exact_009_709714_byte_prompt_fails_preflight_with_zero_step8_call(
    tmp_path,
):
    captured = _captured_boundary()
    gateway = _HistoricalRequestOnlyGateway(lifecycle_state="NOT_STARTED")
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path,
        gateway,
        lone_request_suffix=True,
        legacy_prompt_bytes=captured["captured_restricted_identities"][
            "step_8_prompt_blob"
        ]["bytes"],
    )
    gateway.enforce_context_preflight = True

    result = runtime.run(task, arm="M2", resume=True)

    logical_id = f"{task.task_id}:M2:solve:0008"
    assert result.model_failure_class == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    assert result.failure_metadata == {
        "stage": "PREFLIGHT",
        "call_kind": "solve",
        "provider_request_started": False,
        "ledger_reservation_created": False,
    }
    assert logical_id not in gateway.provider_started
    assert result.accounting["summary"]["by_call_kind"]["solve"]["calls"] == 7
    requests = [
        row for row in _events(evidence)
        if row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id") == logical_id
    ]
    assert len(requests) == 1
    assert requests[0]["payload"]["prompt"]["bytes"] == 709_714
    assert requests[0]["payload"]["function_tools_sha256"] == (
        PRE_D19_REPLAY_ONLY_FUNCTION_TOOLS_SHA256
    )
    assert any(
        row["event_type"] == "model_preflight_failure"
        and row["payload"].get("logical_call_id") == logical_id
        and row["payload"].get("model_calls") == 0
        for row in _events(evidence)
    )


@pytest.mark.parametrize("not_started", ["NOT_PREPARED", "NOT_STARTED"])
def test_legacy_request_only_known_not_started_sends_exactly_once(
    tmp_path, not_started
):
    gateway = _HistoricalRequestOnlyGateway(lifecycle_state=not_started)
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path, gateway
    )

    result = runtime.run(task, arm="M2", resume=True)

    logical_id = f"{task.task_id}:M2:solve:0008"
    assert result.model_failure_class is None
    assert gateway.provider_started.count(logical_id) == 1
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id") == logical_id
        for row in _events(evidence)
    ) == 1


def test_legacy_request_only_terminal_result_replays_without_provider_call(
    tmp_path,
):
    gateway = _TerminalReplayGateway(
        lifecycle_state="PROVIDER_TERMINAL_SUCCESS"
    )
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path, gateway
    )

    result = runtime.run(task, arm="M2", resume=True)

    logical_id = f"{task.task_id}:M2:solve:0008"
    assert result.model_failure_class is None
    assert logical_id not in gateway.provider_started
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id") == logical_id
        for row in _events(evidence)
    ) == 1


def test_legacy_request_only_send_started_without_result_is_never_retried(
    tmp_path,
):
    gateway = _HistoricalRequestOnlyGateway(
        lifecycle_state="PROVIDER_SEND_STARTED"
    )
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path, gateway
    )

    result = runtime.run(task, arm="M2", resume=True)

    logical_id = f"{task.task_id}:M2:solve:0008"
    assert result.model_failure_class == "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN"
    assert result.failure_metadata["provider_request_started"] is True
    assert logical_id not in gateway.provider_started
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id") == logical_id
        for row in _events(evidence)
    ) == 1


def test_started_request_with_broken_replay_contract_fails_global_without_resend(
    tmp_path,
):
    gateway = _BrokenStartedReplayGateway(
        lifecycle_state="PROVIDER_SEND_STARTED"
    )
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path, gateway
    )

    with pytest.raises(RuntimeError, match="did not settle unknown outcome"):
        runtime.run(task, arm="M2", resume=True)

    logical_id = f"{task.task_id}:M2:solve:0008"
    assert logical_id not in gateway.provider_started
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id") == logical_id
        for row in _events(evidence)
    ) == 1


def test_not_started_lifecycle_with_reservation_is_rejected_without_resend(
    tmp_path,
):
    gateway = _ContradictoryNotStartedGateway(lifecycle_state="NOT_STARTED")
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path, gateway
    )

    with pytest.raises(
        CheckpointMismatch, match="not-started request lifecycle"
    ):
        runtime.run(task, arm="M2", resume=True)

    logical_id = f"{task.task_id}:M2:solve:0008"
    assert logical_id not in gateway.provider_started
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id") == logical_id
        for row in _events(evidence)
    ) == 1


def test_legacy_normalization_checkpoint_resumes_after_marker_crash(tmp_path):
    gateway = _HistoricalRequestOnlyGateway(lifecycle_state="NOT_STARTED")
    runtime, task, evidence, gateway = _historical_step8_fixture(
        tmp_path, gateway, lone_request_suffix=True
    )
    gateway.crash_lifecycle_once = True

    with pytest.raises(InjectedCrash, match="durable legacy normalization"):
        runtime.run(task, arm="M2", resume=True)
    normalized = runtime.checkpoints.load(
        task.task_id + "-M2", required_config_hashes=None
    )
    assert normalized.state == "RECALL_PREPARED"
    assert normalized.prepared_request["run_id"] == task.task_id + "-M2"
    assert normalized.prepared_request["projection_record"]["schema"] == (
        "trimem/legacy-request-only-normalization/1.0"
    )

    result = runtime.run(task, arm="M2", resume=True)
    logical_id = f"{task.task_id}:M2:solve:0008"
    assert result.model_failure_class is None
    assert gateway.provider_started.count(logical_id) == 1
    assert sum(
        row["event_type"] == "model_request"
        and row["payload"].get("logical_call_id") == logical_id
        for row in _events(evidence)
    ) == 1


def test_legacy_request_only_lifecycle_identity_corruption_fails_closed(
    tmp_path,
):
    gateway = _HistoricalRequestOnlyGateway(lifecycle_state="NOT_STARTED")
    runtime, task, _, gateway = _historical_step8_fixture(tmp_path, gateway)
    gateway.lifecycle_hash_override = "f" * 64

    with pytest.raises(CheckpointMismatch, match="lifecycle differs"):
        runtime.run(task, arm="M2", resume=True)
    assert f"{task.task_id}:M2:solve:0008" not in gateway.provider_started


def test_prepared_request_run_id_tamper_fails_before_provider_retry(tmp_path):
    gateway = _HistoricalRequestOnlyGateway(lifecycle_state="NOT_STARTED")
    runtime, task, _, gateway = _historical_step8_fixture(
        tmp_path, gateway, lone_request_suffix=True
    )
    gateway.crash_lifecycle_once = True
    with pytest.raises(InjectedCrash, match="durable legacy normalization"):
        runtime.run(task, arm="M2", resume=True)

    run_id = task.task_id + "-M2"
    checkpoint_path = tmp_path / "legacy-checkpoint" / f"{run_id}.json"
    digest_path = tmp_path / "legacy-checkpoint" / f"{run_id}.sha256"
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    payload["prepared_request"]["run_id"] = "different-stream-M2"
    raw = canonical_bytes(payload)
    checkpoint_path.write_bytes(raw)
    digest_path.write_text(
        hashlib.sha256(raw).hexdigest() + "\n", encoding="ascii"
    )

    with pytest.raises(CheckpointMismatch, match="checkpoint payload is invalid"):
        runtime.run(task, arm="M2", resume=True)
    assert f"{task.task_id}:M2:solve:0008" not in gateway.provider_started
