import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.accounting import (
    CallRecord,
    RawEvidenceLedger,
    RunAccounting,
    sha256_bytes,
)
from enterprise_memory.trimem.agent_runtime import (
    CodingTask,
    NoMemoryController,
    TriMemAgentRuntime,
    _outcome_metrics,
)
from enterprise_memory.trimem.arms import ActiveNodeTriMemController, StaticV03MemoryController
from enterprise_memory.trimem.checkpoint import FileCheckpointStore
from enterprise_memory.trimem.gateway import (
    AsyncProviderModelGateway,
    GatewayInvocationFailure,
    GatewayRequest,
    RecordingModelGateway,
    ReplayModelGateway,
    parse_tool_action,
    strict_json_object,
)
from enterprise_memory.providers.base import ModelCallRecord, ModelResponse, ProviderError
from enterprise_memory.trimem.grader import (
    DockerOfficialGraderGateway,
    GradeRequest,
    GradeResult,
    GraderInvocationFailure,
    FrozenDockerGraderTarget,
    RecordingGraderGateway,
    ReplayGraderGateway,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock, assert_equal_arm_limits
from enterprise_memory.trimem.retrieval import InMemoryMemoryGraphStore, TriMemoryRetriever
from enterprise_memory.trimem.workspace import (
    InMemoryRepositoryWorkspace,
    PublicTestResult,
    RecordingToolExecutor,
)
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph


def test_all_arms_have_byte_identical_prompt_tool_parser_and_step_limits():
    locks = {arm: RuntimeLock() for arm in ("M0", "M1", "M2")}
    assert_equal_arm_limits(locks)
    assert len({lock.content_hash for lock in locks.values()}) == 1
    assert len(locks["M0"].prompt_hashes) == 3


def test_arm_lock_drift_is_rejected():
    from enterprise_memory.trimem.runtime_lock import RuntimeLimits

    locks = {arm: RuntimeLock() for arm in ("M0", "M1", "M2")}
    locks["M2"] = RuntimeLock(limits=RuntimeLimits(max_agent_steps=25))
    with pytest.raises(ValueError, match="mismatch"):
        assert_equal_arm_limits(locks)


def test_outcome_metrics_do_not_double_count_reasoning_and_require_post_use_marker():
    accounting = RunAccounting()
    accounting.add_call(CallRecord(
        task_id="target",
        arm="M2",
        step_no=1,
        call_kind="solve",
        logical_call_id="target:M2:solve:0001",
        provider="fixture",
        model="fixture",
        input_tokens=10,
        output_tokens=7,
        reasoning_tokens=3,
        wall_time_ms=11,
        prompt_hash="a" * 64,
        response_hash="b" * 64,
    ))
    graph = ShortTermWorkingGraph("target", "repair a concrete parser", "owner/repo")
    injections = (
        {"memory_id": "injected-conflict", "byte_count": 8},
        {"memory_id": "injected-clean", "byte_count": 4},
    )
    rejections = [{"memory_id": "rejected-stale", "reason": "stale"}]
    grade = GradeResult(
        task_id="target",
        resolved=False,
        exit_code=1,
        stdout="",
        stderr="failed",
        report={"post_use_memory_feedback": [{
            "memory_id": "injected-conflict",
            "disposition": "CONFLICT",
            "evidence_hash": "c" * 64,
        }]},
        grader_id="fixture",
        container_digest="fixture",
        official=False,
        wall_time_ms=5,
    )
    observed = _outcome_metrics(graph, accounting, injections, rejections, grade)
    assert observed["actual_total_tokens"] == 17
    assert observed["actual_reasoning_tokens"] == 3
    assert observed["stale_conflict_reuse_count"] == 1
    assert observed["stale_conflict_memory_ids"] == ["injected-conflict"]

    rejected_only = _outcome_metrics(
        graph,
        accounting,
        injections,
        rejections,
        GradeResult(**{**grade.__dict__, "report": {}}),
    )
    assert rejected_only["stale_conflict_reuse_count"] == 0
    assert rejected_only["stale_conflict_memory_ids"] == []


@pytest.mark.parametrize(
    "overrides",
    (
        {"input_tokens": 4, "cached_input_tokens": 5},
        {"output_tokens": 4, "reasoning_tokens": 5},
    ),
)
def test_call_record_rejects_impossible_usage_subsets(overrides):
    values = {
        "task_id": "t", "arm": "M0", "step_no": 1, "call_kind": "solve",
        "logical_call_id": "call", "provider": "fixture", "model": "fixture",
        "input_tokens": 4, "cached_input_tokens": 0,
        "output_tokens": 4, "reasoning_tokens": 0, "wall_time_ms": 0,
        "prompt_hash": "a" * 64, "response_hash": "b" * 64,
    }
    with pytest.raises(ValueError, match="cannot exceed"):
        CallRecord(**{**values, **overrides})


def test_strict_parser_rejects_duplicate_unknown_and_extra_fields():
    with pytest.raises(ValueError, match="duplicate"):
        strict_json_object('{"tool":"list_files","tool":"read_file","arguments":{}}')
    with pytest.raises(ValueError, match="unknown tool"):
        parse_tool_action('{"tool":"shell","arguments":{}}', {"list_files"})
    with pytest.raises(ValueError, match="exactly"):
        parse_tool_action('{"tool":"list_files","arguments":{},"note":"x"}', {"list_files"})


def test_replay_gateway_records_full_raw_payload_and_paid_zero(tmp_path):
    accounting = RunAccounting()
    evidence = RawEvidenceLedger(tmp_path / "evidence", clock=lambda: "2026-08-31T00:00:00Z")
    reply = '{"tool":"list_files","arguments":{}}'
    gateway = RecordingModelGateway(ReplayModelGateway({"t:solve:1": reply}), accounting, evidence)
    response = gateway.invoke(
        GatewayRequest(
            task_id="t",
            arm="M2",
            step_no=1,
            call_kind="solve",
            logical_call_id="t:solve:1",
            prompt="full prompt",
            max_output_tokens=50,
            active_node_id="node-1",
        )
    )
    assert response.text == reply
    assert accounting.summary()["model_gateway_calls"] == 1
    assert accounting.summary()["paid_model_calls"] == 0
    assert evidence.verify()["events"] == 2


def test_async_paid_provider_bridge_requires_scope_exact_model_and_usage():
    class Provider:
        async def generate(self, request, *, logical_request_id, org_id):
            response = ModelResponse(
                text='{"tool":"list_files","arguments":{}}',
                finish_reason="completed",
                returned_model="gpt-5.4-mini-2026-03-17",
                provider_request_id="req-fixture",
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
            )
            record = ModelCallRecord(
                logical_request_id=logical_request_id,
                attempts=2,
                provider_request_id="req-fixture",
                requested_model="gpt-5.4-mini-2026-03-17",
                returned_model="gpt-5.4-mini-2026-03-17",
                prompt_hash="a" * 64,
                response_hash="b" * 64,
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
                first_byte_latency=None,
                total_latency=0.125,
            )
            record.cached_input_tokens = 3
            record.reasoning_tokens = 2
            return response, record

    gateway = AsyncProviderModelGateway(
        Provider(), asyncio.run, expected_model="gpt-5.4-mini-2026-03-17"
    )
    request = GatewayRequest(
        task_id="t", arm="M0", step_no=1, call_kind="solve", logical_call_id="call-1",
        prompt="prompt", max_output_tokens=100, org_id="org",
    )
    result = gateway.invoke(request)
    assert result.paid is True and result.attempt == 2
    assert (result.input_tokens, result.cached_input_tokens, result.output_tokens) == (11, 3, 7)
    assert result.reasoning_tokens == 2 and result.wall_time_ms == 125
    with pytest.raises(ValueError, match="org_id"):
        gateway.invoke(GatewayRequest(
            task_id="t", arm="M0", step_no=1, call_kind="solve", logical_call_id="call-2",
            prompt="prompt", max_output_tokens=100,
        ))


@pytest.mark.parametrize(
    ("cached_input_tokens", "reasoning_tokens"),
    ((12, 2), (3, 8)),
)
def test_async_paid_provider_bridge_rejects_impossible_usage_subsets(
    cached_input_tokens, reasoning_tokens
):
    class Provider:
        async def generate(self, request, *, logical_request_id, org_id):
            response = ModelResponse(
                text='{"tool":"list_files","arguments":{}}',
                finish_reason="completed",
                returned_model="gpt-5.4-mini-2026-03-17",
                provider_request_id="req-impossible-usage",
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
            )
            record = ModelCallRecord(
                logical_request_id=logical_request_id,
                attempts=1,
                provider_request_id="req-impossible-usage",
                requested_model="gpt-5.4-mini-2026-03-17",
                returned_model="gpt-5.4-mini-2026-03-17",
                prompt_hash="a" * 64,
                response_hash="b" * 64,
                input_tokens=11,
                output_tokens=7,
                total_tokens=18,
                first_byte_latency=None,
                total_latency=0.01,
            )
            record.cached_input_tokens = cached_input_tokens
            record.reasoning_tokens = reasoning_tokens
            return response, record

    gateway = AsyncProviderModelGateway(
        Provider(), asyncio.run, expected_model="gpt-5.4-mini-2026-03-17"
    )
    with pytest.raises(Exception, match="invalid_token_usage"):
        gateway.invoke(GatewayRequest(
            task_id="t", arm="M0", step_no=1, call_kind="solve",
            logical_call_id="impossible-usage", prompt="prompt",
            max_output_tokens=100, org_id="org",
        ))


def test_failed_provider_invalid_usage_is_explicit_and_consumes_unknown_usage_shape():
    class Provider:
        async def generate(self, request, *, logical_request_id, org_id):
            record = ModelCallRecord(
                logical_request_id=logical_request_id, attempts=1,
                provider_request_id="req-invalid", requested_model="gpt-5.4-mini-2026-03-17",
                returned_model="gpt-5.4-mini-2026-03-17", prompt_hash="a" * 64,
                response_hash=None, input_tokens=4, output_tokens=2, total_tokens=6,
                first_byte_latency=None, total_latency=0.1, final_status="failed",
            )
            record.cached_input_tokens = 5
            record.reasoning_tokens = 3
            raise ProviderError("invalid provider usage", record=record)

    gateway = AsyncProviderModelGateway(
        Provider(), asyncio.run, expected_model="gpt-5.4-mini-2026-03-17"
    )
    with pytest.raises(GatewayInvocationFailure) as captured:
        gateway.invoke(GatewayRequest(
            task_id="t", arm="M0", step_no=1, call_kind="solve",
            logical_call_id="invalid-failure-usage", prompt="prompt",
            max_output_tokens=100, org_id="org",
        ))
    failure = captured.value
    assert failure.status == "invalid_token_usage"
    assert (failure.input_tokens, failure.cached_input_tokens) == (None, None)
    assert (failure.output_tokens, failure.reasoning_tokens) == (None, None)
    assert failure.provider_reported_usage_available is False


def test_failed_paid_provider_call_is_still_accounted_and_evidenced(tmp_path):
    class FailingProvider:
        async def generate(self, request, *, logical_request_id, org_id):
            record = ModelCallRecord(
                logical_request_id=logical_request_id,
                attempts=3,
                provider_request_id=None,
                requested_model="gpt-5.4-mini-2026-03-17",
                returned_model=None,
                prompt_hash="a" * 64,
                response_hash=None,
                input_tokens=13,
                output_tokens=0,
                total_tokens=13,
                first_byte_latency=None,
                total_latency=1.25,
                final_status="exhausted",
            )
            record.cached_input_tokens = 2
            record.reasoning_tokens = 0
            raise ProviderError("sensitive upstream body is not propagated", record=record)

    accounting = RunAccounting()
    evidence = RawEvidenceLedger(tmp_path / "failure-evidence", clock=lambda: "2026-08-31T00:00:00Z")
    gateway = RecordingModelGateway(
        AsyncProviderModelGateway(
            FailingProvider(), asyncio.run, expected_model="gpt-5.4-mini-2026-03-17"
        ),
        accounting,
        evidence,
    )
    with pytest.raises(Exception, match="exhausted"):
        gateway.invoke(GatewayRequest(
            task_id="t", arm="M2", step_no=1, call_kind="solve", logical_call_id="failed-call",
            prompt="prompt", max_output_tokens=100, org_id="org",
        ))
    summary = accounting.summary()
    assert summary["model_gateway_calls"] == 1 and summary["paid_model_calls"] == 1
    assert summary["actual_input_tokens"] == 13 and summary["actual_cached_input_tokens"] == 2
    assert accounting.calls[0].attempt == 3 and accounting.calls[0].status == "exhausted"
    assert evidence.verify()["events"] == 2
    assert "sensitive upstream" not in evidence.events_path.read_text(encoding="utf-8")


def test_paid_response_validation_failure_preserves_returned_body_and_usage(tmp_path):
    class WrongModelProvider:
        async def generate(self, request, *, logical_request_id, org_id):
            return (
                ModelResponse(
                    text='{"tool":"list_files","arguments":{}}',
                    finish_reason="completed",
                    returned_model="unexpected-model",
                    provider_request_id="req-wrong-model",
                    input_tokens=19,
                    output_tokens=5,
                    total_tokens=24,
                ),
                ModelCallRecord(
                    logical_request_id=logical_request_id,
                    attempts=1,
                    provider_request_id="req-wrong-model",
                    requested_model="gpt-5.4-mini-2026-03-17",
                    returned_model="unexpected-model",
                    prompt_hash="a" * 64,
                    response_hash="b" * 64,
                    input_tokens=19,
                    output_tokens=5,
                    total_tokens=24,
                    first_byte_latency=None,
                    total_latency=0.2,
                ),
            )

    accounting = RunAccounting()
    evidence = RawEvidenceLedger(tmp_path / "wrong-model", clock=lambda: "2026-08-31T00:00:00Z")
    gateway = RecordingModelGateway(
        AsyncProviderModelGateway(
            WrongModelProvider(), asyncio.run, expected_model="gpt-5.4-mini-2026-03-17"
        ),
        accounting,
        evidence,
    )
    with pytest.raises(Exception, match="returned_model_mismatch"):
        gateway.invoke(GatewayRequest(
            task_id="t", arm="M2", step_no=1, call_kind="solve",
            logical_call_id="wrong-model-call", prompt="prompt", max_output_tokens=100,
            org_id="org",
        ))
    record = accounting.calls[0]
    assert record.paid is True and record.status == "returned_model_mismatch"
    assert (record.input_tokens, record.output_tokens) == (19, 5)
    assert (evidence.blob_dir / record.response_hash).read_text(encoding="utf-8") == (
        '{"tool":"list_files","arguments":{}}'
    )


def test_workspace_supports_multifile_edit_and_never_exposes_hidden_grader(tmp_path):
    def public(files):
        return PublicTestResult(files["src/a.py"] == "value = 2\n", "public ok")

    workspace = InMemoryRepositoryWorkspace(
        {"src/a.py": "value = 1\n", "src/b.py": "from .a import value\n"},
        editable_paths=("src/a.py", "src/b.py"),
        public_test=public,
    )
    accounting = RunAccounting()
    evidence = RawEvidenceLedger(tmp_path / "evidence", clock=lambda: "2026-08-31T00:00:00Z")
    tools = RecordingToolExecutor(workspace, accounting, evidence, task_id="t", arm="M2")
    files = tools.execute(1, "n", "list_files", {})
    assert files == {"files": ["src/a.py", "src/b.py"]}
    tools.execute(2, "n", "write_file", {"path": "src/a.py", "content": "value = 2\n"})
    result = tools.execute(3, "n", "run_public_tests", {})
    assert result["passed"] is True
    assert tools.history[0]["result_payload"]["files"] == ["src/a.py", "src/b.py"]
    assert tools.history[1]["request_payload"]["arguments"]["content"] == "value = 2\n"
    assert tools.history[2]["result_payload"]["stdout"] == "public ok"
    assert "hidden" not in json.dumps(tools.history).lower()
    assert "--- a/src/a.py" in workspace.patch()


def test_replay_grader_uses_same_boundary_and_preserves_streams(tmp_path):
    fixture_digest = sha256_bytes(b"private fixture")
    grader = ReplayGraderGateway(
        lambda files: (files["src/a.py"] == "value = 2\n", "all passed", "warning"),
        fixture_digest=fixture_digest,
    )
    accounting = RunAccounting()
    evidence = RawEvidenceLedger(tmp_path / "evidence", clock=lambda: "2026-08-31T00:00:00Z")
    recording = RecordingGraderGateway(grader, accounting, evidence, "M2")
    workspace = InMemoryRepositoryWorkspace(
        {"src/a.py": "value = 2\n"}, editable_paths=("src/a.py",)
    )
    result = recording.grade(GradeRequest(
        task_id="t",
        repository="example/repo",
        base_commit="base",
        patch="patch",
        workspace=workspace.grader_context(base_commit="base"),
    ))
    assert result.resolved is True
    assert result.official is False
    assert accounting.summary()["grader_calls"] == 1
    assert accounting.summary()["grader_containers"] == 0
    assert evidence.verify()["events"] == 2


def test_official_grader_target_requires_frozen_image_digest():
    with pytest.raises(ValueError, match="pinned"):
        FrozenDockerGraderTarget(task_id="x", image="grader:latest", command=("grade",))
    valid = FrozenDockerGraderTarget(
        task_id="x", image="registry/grader@sha256:" + "a" * 64, command=("grade", "--report", "/output/report.json")
    )
    assert valid.image.endswith("a" * 64)


def test_official_grader_refuses_observed_image_digest_drift_before_run(monkeypatch):
    target = FrozenDockerGraderTarget(
        task_id="x", image="registry/grader@sha256:" + "a" * 64,
        command=("grade", "--report", "/output/report.json"),
    )
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(["registry/grader@sha256:" + "b" * 64]),
            stderr="",
        )

    monkeypatch.setattr("enterprise_memory.trimem.grader.subprocess.run", fake_run)
    workspace = InMemoryRepositoryWorkspace({"a.py": "x = 1\n"}, editable_paths=("a.py",))
    request = GradeRequest(
        task_id="x", repository="example/repo", base_commit="base", patch="",
        workspace=workspace.grader_context(base_commit="base"),
    )
    with pytest.raises(GraderInvocationFailure) as failure:
        DockerOfficialGraderGateway(target).grade(request)
    assert failure.value.result.status == "image_digest_mismatch"
    assert failure.value.result.container_started is False
    assert failure.value.result.report["observed_digests"] == ["sha256:" + "b" * 64]
    assert len(calls) == 1 and calls[0][1:3] == ["image", "inspect"]


def test_official_grader_image_inspect_timeout_preserves_partial_streams(monkeypatch):
    target = FrozenDockerGraderTarget(
        task_id="x", image="registry/grader@sha256:" + "a" * 64,
        command=("grade", "--report", "/output/report.json"),
    )

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 60, output=b"partial stdout", stderr=b"partial stderr")

    monkeypatch.setattr("enterprise_memory.trimem.grader.subprocess.run", fake_run)
    workspace = InMemoryRepositoryWorkspace({"a.py": "x = 1\n"}, editable_paths=("a.py",))
    request = GradeRequest(
        task_id="x", repository="example/repo", base_commit="base", patch="",
        workspace=workspace.grader_context(base_commit="base"),
    )
    with pytest.raises(GraderInvocationFailure) as failure:
        DockerOfficialGraderGateway(target).grade(request)
    assert failure.value.result.status == "image_inspect_timeout"
    assert failure.value.result.stdout == "partial stdout"
    assert failure.value.result.stderr == "partial stderr"
    assert failure.value.result.container_started is False


def test_failed_official_grader_attempt_preserves_streams_report_and_accounting(tmp_path):
    result = GradeResult(
        task_id="x",
        resolved=False,
        exit_code=23,
        stdout="complete stdout",
        stderr="complete stderr",
        report={"task_id": "x", "resolved": False, "failure_stage": "container"},
        grader_id="official-container-v1",
        container_digest="registry/grader@sha256:" + "a" * 64,
        official=True,
        wall_time_ms=17,
        container_started=True,
        status="container_exit_nonzero",
    )

    class FailingOfficialGateway:
        def grade(self, request):
            raise GraderInvocationFailure(result)

    accounting = RunAccounting()
    evidence = RawEvidenceLedger(tmp_path / "failed-grader", clock=lambda: "2026-08-31T00:00:00Z")
    recording = RecordingGraderGateway(FailingOfficialGateway(), accounting, evidence, "M2")
    workspace = InMemoryRepositoryWorkspace({"a.py": "x = 1\n"}, editable_paths=("a.py",))
    request = GradeRequest(
        task_id="x", repository="example/repo", base_commit="base", patch="patch",
        workspace=workspace.grader_context(base_commit="base"),
    )
    with pytest.raises(GraderInvocationFailure):
        recording.grade(request)

    summary = accounting.summary()
    assert summary["grader_calls"] == 1
    assert summary["grader_containers"] == 1
    assert summary["official_grader_runs"] == 1
    record = accounting.graders[0]
    assert record.status == "container_exit_nonzero"
    assert (evidence.blob_dir / record.stdout_hash).read_text(encoding="utf-8") == "complete stdout"
    assert (evidence.blob_dir / record.stderr_hash).read_text(encoding="utf-8") == "complete stderr"
    assert evidence.verify(
        (record.stdout_hash, record.stderr_hash, record.report_hash)
    )["events"] == 2


def test_m0_m1_m2_execute_the_same_full_agent_loop_and_record_actual_compute(tmp_path):
    def response(request):
        if request.call_kind == "decompose":
            return json.dumps({"subtasks": [{
                "id": "replace-value",
                "objective": "replace the obsolete module value while preserving its type",
                "predicted_operation": "replace integer literal",
                "depends_on": [],
                "files": ["src/value.py"],
            }]})
        if request.call_kind == "extract":
            return json.dumps({
                "episode": {"summary": "Updated value", "action": "replace literal", "outcome": "passed"},
                "semantic_candidate": {
                    "preconditions": "The literal is obsolete.",
                    "operation": "Replace the literal.",
                    "invariant": "The value remains an integer.",
                    "non_applicability": "Do not change dynamic values.",
                    "verification": "Run the public value check.",
                    "applicability_scope": "EXACT_REPOSITORY",
                },
            })
        if request.step_no == 1:
            return json.dumps({"tool": "write_file", "arguments": {
                "path": "src/value.py", "content": "VALUE = 2\n",
            }})
        return json.dumps({"tool": "complete_subtask", "arguments": {
            "evidence": "The public value contract is ready for grading.",
        }})

    def public(files):
        return PublicTestResult(files["src/value.py"] == "VALUE = 2\n", "value check")

    summaries = {}
    runtime_hashes = set()
    for arm in ("M0", "M1", "M2"):
        task = CodingTask(
            task_id=f"common-loop-{arm.lower()}",
            org_id="org-1",
            user_id="alice",
            repository="example/common-loop",
            commit="frozen-source",
            instruction="Set the module value to two without changing its type.",
            files={"src/value.py": "VALUE = 1\n"},
            editable_paths=("src/value.py",),
            public_test=public,
        )
        store = InMemoryMemoryGraphStore()
        if arm == "M0":
            controller = NoMemoryController()
        elif arm == "M1":
            controller = StaticV03MemoryController(store)
        else:
            controller = ActiveNodeTriMemController(TriMemoryRetriever(store), task_id=task.task_id)
        lock = RuntimeLock()
        runtime_hashes.add(lock.content_hash)
        runtime = TriMemAgentRuntime(
            runtime_lock=lock,
            model_gateway=ReplayModelGateway(response),
            grader_gateway=ReplayGraderGateway(
                lambda files: (files["src/value.py"] == "VALUE = 2\n", "passed", ""),
                fixture_digest=sha256_bytes((arm + ":fixture").encode()),
            ),
            memory_controller=controller,
            evidence=RawEvidenceLedger(tmp_path / arm / "evidence"),
            checkpoint_store=FileCheckpointStore(tmp_path / arm / "checkpoints"),
        )
        outcome = runtime.run(task, arm=arm)
        assert outcome.resolved is True
        assert outcome.grade.official is False
        summaries[arm] = outcome.accounting["summary"]

    assert runtime_hashes == {RuntimeLock().content_hash}
    for summary in summaries.values():
        assert summary["model_gateway_calls"] == 4
        assert summary["by_call_kind"]["decompose"]["calls"] == 1
        assert summary["by_call_kind"]["solve"]["calls"] == 2
        assert summary["by_call_kind"]["extract"]["calls"] == 1
        assert summary["grader_calls"] == 1
        assert summary["grader_containers"] == 0
        assert summary["paid_model_calls"] == 0
        assert summary["actual_input_tokens"] > 0
        assert summary["actual_output_tokens"] > 0


def test_runtime_can_revise_semantic_dag_after_new_test_evidence(tmp_path):
    def response(request):
        if request.call_kind == "decompose":
            return json.dumps({"subtasks": [{
                "id": "locate-contract",
                "objective": "locate the obsolete value contract in the module",
                "predicted_operation": "inspect the value and its public test",
                "depends_on": [],
                "files": ["src/value.py"],
            }]})
        if request.call_kind == "extract":
            return json.dumps({
                "episode": {"summary": "Updated value", "action": "replace literal", "outcome": "passed"},
                "semantic_candidate": {
                    "preconditions": "A public contract establishes the replacement value.",
                    "operation": "Replace the literal after locating its invariant.",
                    "invariant": "The exported value remains an integer.",
                    "non_applicability": "Do not rewrite dynamically computed values.",
                    "verification": "Run the public value check.",
                    "applicability_scope": "EXACT_REPOSITORY",
                },
            })
        actions = {
            1: {"tool": "run_public_tests", "arguments": {}},
            2: {"tool": "revise_subtask_dag", "arguments": {
                "reason": "The failing public test establishes a separate replacement invariant.",
                "new_subtasks": [{
                    "id": "replace-value",
                    "objective": "replace the obsolete value while preserving its integer invariant",
                    "predicted_operation": "replace the integer literal",
                    "depends_on": ["locate-contract"],
                    "files": ["src/value.py"],
                    "tests": ["public value contract"],
                }],
                "dependency_additions": [],
            }},
            3: {"tool": "complete_subtask", "arguments": {
                "evidence": "The failing public test isolated the required value contract.",
            }},
            4: {"tool": "write_file", "arguments": {
                "path": "src/value.py", "content": "VALUE = 2\n",
            }},
            5: {"tool": "complete_subtask", "arguments": {
                "evidence": "The integer literal now implements the isolated contract.",
            }},
        }
        return json.dumps(actions[request.step_no])

    task = CodingTask(
        task_id="dynamic-dag", org_id="org-1", user_id="alice",
        repository="example/dynamic-dag", commit="frozen-source",
        instruction="Update the exported value to two while preserving its type.",
        files={"src/value.py": "VALUE = 1\n"}, editable_paths=("src/value.py",),
        public_test=lambda files: PublicTestResult(
            files["src/value.py"] == "VALUE = 2\n", "value check",
            "expected two" if files["src/value.py"] != "VALUE = 2\n" else "",
            0 if files["src/value.py"] == "VALUE = 2\n" else 1,
        ),
    )
    runtime = TriMemAgentRuntime(
        runtime_lock=RuntimeLock(), model_gateway=ReplayModelGateway(response),
        grader_gateway=ReplayGraderGateway(
            lambda files: (files["src/value.py"] == "VALUE = 2\n", "passed", ""),
            fixture_digest=sha256_bytes(b"dynamic-dag-fixture"),
        ),
        memory_controller=NoMemoryController(),
        evidence=RawEvidenceLedger(tmp_path / "evidence"),
        checkpoint_store=FileCheckpointStore(tmp_path / "checkpoints"),
    )

    outcome = runtime.run(task, arm="M0")

    assert outcome.resolved is True
    assert [row["node_id"] for row in outcome.graph_snapshot["nodes"]] == [
        "locate-contract", "replace-value",
    ]
    replacement = outcome.graph_snapshot["nodes"][1]
    assert replacement["dependencies"] == ["locate-contract"]
    assert replacement["tests"] == ["public value contract"]
    assert outcome.accounting["summary"]["by_call_kind"]["solve"]["calls"] == 5
