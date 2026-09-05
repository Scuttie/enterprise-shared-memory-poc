from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from enterprise_memory.providers.base import SINGLE_FUNCTION_CALL
from enterprise_memory.trimem.accounting import RawEvidenceLedger, sha256_bytes
from enterprise_memory.trimem.agent_runtime import (
    CANONICAL_FAILED_CELL_NOOP,
    CodingTask,
    InjectedCrash,
    NoMemoryController,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.checkpoint import FileCheckpointStore
from enterprise_memory.trimem.gateway import (
    GatewayInvocationFailure,
    GatewayResponse,
    ReplayModelGateway,
)
from enterprise_memory.trimem.grader import ReplayGraderGateway
from enterprise_memory.trimem.runtime_lock import RuntimeLock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from trimem_benchmark_run import (  # noqa: E402
    scientific_caps_after_protocol_canary,
    validate_global_phase_accounting,
)


def task(task_id="d16-cell"):
    return CodingTask(
        task_id=task_id,
        org_id="org",
        user_id="alice",
        repository="example/repo",
        commit="frozen",
        instruction="Replace the obsolete value with the required value.",
        files={"value.py": "VALUE = 1\n"},
        editable_paths=("value.py",),
    )


def decompose():
    return json.dumps({"subtasks": [{
        "id": "replace-value",
        "objective": "replace the obsolete exported value",
        "predicted_operation": "replace one value literal",
        "depends_on": [],
    }]})


def extraction(outcome):
    return json.dumps({
        "episode": {
            "summary": "Observed the terminal cell outcome.",
            "action": "Attempted the frozen value repair.",
            "outcome": outcome,
        },
        "semantic_candidate": None,
    })


def runtime(tmp_path, gateway, *, grader_pass=False, lifecycle=None):
    return TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=gateway,
        grader_gateway=ReplayGraderGateway(
            lambda files: (
                grader_pass or files.get("value.py") == "VALUE = 2\n",
                "graded",
                "",
            ),
            fixture_digest=sha256_bytes(b"d16-grader"),
        ),
        memory_controller=NoMemoryController(),
        evidence=RawEvidenceLedger(tmp_path / "evidence"),
        checkpoint_store=FileCheckpointStore(tmp_path / "checkpoints"),
        lifecycle=lifecycle,
    )


class FailingSolveGateway:
    def __init__(self, status="RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS"):
        self.status = status
        self.calls = []

    def invoke(self, request):
        self.calls.append(request)
        if request.call_kind == "decompose":
            text = decompose()
        elif request.call_kind == "extract":
            text = extraction("failed")
        else:
            raise GatewayInvocationFailure(
                provider="fixture",
                model="fixture",
                status=self.status,
                attempt=1,
                input_tokens=4,
                output_tokens=2,
                cached_input_tokens=0,
                reasoning_tokens=1,
                wall_time_ms=1,
                provider_reported_usage_available=True,
            )
        return GatewayResponse(
            text=text,
            provider="fixture",
            model="fixture",
            input_tokens=4,
            output_tokens=2,
            wall_time_ms=1,
            paid=False,
        )


def test_cell_action_failure_is_graded_with_canonical_noop_and_terminal(tmp_path):
    gateway = FailingSolveGateway()
    result = runtime(tmp_path, gateway).run(task(), arm="M0")
    assert result.cell_status == "CELL_SCIENTIFIC_FAILURE"
    assert result.grader_patch_source == "CANONICAL_FAILED_CELL_NOOP"
    assert result.patch == CANONICAL_FAILED_CELL_NOOP
    assert result.resolved is False
    assert result.accounting["summary"]["grader_calls"] == 1
    assert result.accounting["summary"]["by_call_kind"]["extract"]["calls"] == 1


def test_partial_model_patch_is_graded_and_may_resolve(tmp_path):
    def response(request):
        if request.call_kind == "decompose":
            return decompose()
        if request.call_kind == "extract":
            return extraction("passed")
        if request.step_no == 1:
            return json.dumps({
                "tool": "write_file",
                "arguments": {"path": "value.py", "content": "VALUE = 2\n"},
            })
        raise GatewayInvocationFailure(
            provider="fixture", model="fixture",
            status="SOLVE_EXPECTED_FUNCTION_CALL", attempt=1,
            input_tokens=3, output_tokens=1, cached_input_tokens=0,
            reasoning_tokens=0, wall_time_ms=1,
        )

    result = runtime(tmp_path, ReplayModelGateway(response)).run(task(), arm="M1")
    assert result.grader_patch_source == "MODEL_PARTIAL_PATCH"
    assert result.resolved is True
    assert "VALUE = 2" in result.patch


class ExtractionFailureGateway:
    def invoke(self, request):
        if request.call_kind == "decompose":
            text = decompose()
        elif request.call_kind == "solve":
            text = json.dumps({
                "tool": "complete_subtask", "arguments": {"evidence": "done"}
            })
        else:
            raise GatewayInvocationFailure(
                provider="fixture", model="fixture", status="RESPONSE_REFUSAL",
                attempt=1, input_tokens=3, output_tokens=1,
                cached_input_tokens=0, reasoning_tokens=0, wall_time_ms=1,
            )
        return GatewayResponse(
            text=text, provider="fixture", model="fixture",
            input_tokens=3, output_tokens=1, wall_time_ms=1, paid=False,
        )


class CountingLifecycle:
    def __init__(self):
        self.stores = 0
        self.credits = 0

    def store_experience(self, *args, **kwargs):
        self.stores += 1
        return {}

    def credit_outcome(self, *args, **kwargs):
        self.credits += 1
        return {}


def test_extraction_failure_preserves_grade_and_performs_no_memory_update(tmp_path):
    lifecycle = CountingLifecycle()
    result = runtime(
        tmp_path, ExtractionFailureGateway(), grader_pass=True, lifecycle=lifecycle
    ).run(task(), arm="M2")
    assert result.resolved is True
    assert result.cell_status == "MEMORY_EXTRACTION_FAILED"
    assert result.extraction_status == "MEMORY_EXTRACTION_FAILED"
    assert lifecycle.stores == lifecycle.credits == 0


def test_global_auth_failure_is_not_contained(tmp_path):
    gateway = FailingSolveGateway("HTTP_401")
    with pytest.raises(GatewayInvocationFailure, match="HTTP_401"):
        runtime(tmp_path, gateway).run(task(), arm="M0")


class ActionContractGateway:
    def __init__(self):
        self.solve_calls = 0

    def invoke(self, request):
        if request.call_kind == "decompose":
            return GatewayResponse(
                decompose(), "fixture", "fixture", 3, 1, 1, False
            )
        if request.call_kind == "extract":
            return GatewayResponse(
                extraction("failed"), "fixture", "fixture", 3, 1, 1, False
            )
        self.solve_calls += 1
        assert request.response_mode == SINGLE_FUNCTION_CALL
        raise GatewayInvocationFailure(
            provider="fixture", model="fixture",
            status="SOLVE_MULTIPLE_FUNCTION_CALLS", attempt=1,
            input_tokens=3, output_tokens=2, cached_input_tokens=0,
            reasoning_tokens=1, wall_time_ms=1,
            provider_response_envelope={
                "response_id": "response-1",
                "output_items": [],
            },
        )


def test_action_contract_failure_resume_uses_zero_new_provider_calls(tmp_path):
    gateway = ActionContractGateway()
    runner = runtime(tmp_path, gateway)
    with pytest.raises(InjectedCrash, match="action-contract"):
        runner.run(
            task(), arm="M0", crash_after_action_contract_failure=True
        )
    assert gateway.solve_calls == 1
    result = runner.run(task(), arm="M0", resume=True)
    assert result.model_failure_class == "SOLVE_MULTIPLE_FUNCTION_CALLS"
    assert gateway.solve_calls == 1
    events = [
        json.loads(line)["event_type"]
        for line in runner.evidence.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events.count("model_request") == 3
    assert events.count("action_contract_failure") == 1


def test_secret_looking_source_is_not_mutated_and_public_events_hide_it(tmp_path):
    code = "VALUE = 'sk-proj-NOT-A-REAL-KEY-1234567890'\n"

    def response(request):
        if request.call_kind == "decompose":
            return decompose()
        if request.call_kind == "extract":
            return extraction("passed")
        if request.step_no == 1:
            return json.dumps({
                "tool": "write_file",
                "arguments": {"path": "value.py", "content": code},
            })
        assert "result_payload" in request.prompt
        assert sha256_bytes(code.encode("utf-8")) in request.prompt
        return json.dumps({
            "tool": "complete_subtask", "arguments": {"evidence": "exact code written"}
        })

    runner = runtime(tmp_path, ReplayModelGateway(response), grader_pass=True)
    result = runner.run(task(), arm="M0")
    assert code.strip() in result.patch
    public_events = runner.evidence.events_path.read_text(encoding="utf-8")
    assert code.strip() not in public_events
    assert "function_arguments_sha256" in public_events


def test_cell_failure_does_not_stop_the_next_cell(tmp_path):
    first = runtime(tmp_path / "first", FailingSolveGateway()).run(
        task("first"), arm="M0"
    )
    second = runtime(tmp_path / "second", FailingSolveGateway()).run(
        task("second"), arm="M0"
    )
    assert [first.cell_status, second.cell_status] == [
        "CELL_SCIENTIFIC_FAILURE",
        "CELL_SCIENTIFIC_FAILURE",
    ]
    assert first.accounting["summary"]["grader_calls"] == 1
    assert second.accounting["summary"]["grader_calls"] == 1


def test_protocol_canary_and_scientific_cap_arithmetic_is_exact():
    phase = {
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
    canary = {
        "status": "PASS",
        "scientific_result": False,
        "generation_calls": 1,
        "input_token_cap": 4_096,
        "output_token_cap": 2_048,
        "model": "gpt-5.4-mini-2026-03-17",
        "approval_sha256": "a" * 64,
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 10,
        "actual_usd": "0.000120000000",
    }
    scientific_cap = scientific_caps_after_protocol_canary(
        phase, canary, expected_approval_sha256="a" * 64
    )
    assert scientific_cap["paid_model_calls"] == 1_872
    assert scientific_cap["input_tokens"] == 36_000_000
    assert scientific_cap["output_tokens"] == 4_718_592
    combined = validate_global_phase_accounting(
        phase,
        canary,
        {
            "paid_model_calls": 1_872,
            "input_tokens": 36_000_000,
            "cached_input_tokens": 0,
            "output_tokens": 4_718_592,
            "total_usd": "48.233664000000",
        },
    )
    assert combined["model_calls"] == 1_873
    assert combined["input_tokens"] == 36_000_100
    assert combined["output_tokens"] == 4_718_602


def test_workflow_orders_canary_before_images_and_scientific_runner():
    workflow = (ROOT / ".github/workflows/trimem-benchmark.yml").read_text(
        encoding="utf-8"
    )
    canary = workflow.index("Execute one native-action protocol canary before benchmark images")
    image_pull = workflow.index("Pull committed images by digest and verify local observations")
    scientific = workflow.index("Execute frozen serial streams with one atomic phase ledger")
    assert canary < image_pull < scientific
    assert "DEVELOPMENT_TUNING_EXEC_REQUEST_008.json" in workflow
    assert "protocol-action-canary.json" in workflow
