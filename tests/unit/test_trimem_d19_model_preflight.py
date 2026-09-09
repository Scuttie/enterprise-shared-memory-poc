from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_benchmark_run as benchmark  # noqa: E402
from enterprise_memory.trimem.accounting import RawEvidenceLedger, RunAccounting  # noqa: E402
from enterprise_memory.trimem.agent_runtime import (  # noqa: E402
    CodingTask,
    NoMemoryController,
    TriMemAgentRuntime,
    _validated_model_preflight_failure,
)
from enterprise_memory.trimem.checkpoint import (  # noqa: E402
    CheckpointMismatch,
    FileCheckpointStore,
)
from enterprise_memory.trimem.gateway import (  # noqa: E402
    AsyncProviderModelGateway,
    GatewayInvocationFailure,
    GatewayRequest,
    GatewayResponse,
    ModelPreflightFailure,
    RecordingModelGateway,
    ReplayModelGateway,
    ReservationPreflight,
    gateway_request_sha256,
)
from enterprise_memory.trimem.grader import GradeResult  # noqa: E402
from enterprise_memory.trimem.runtime_lock import RuntimeLock  # noqa: E402


def _caps(**overrides: int | float | str) -> dict[str, int | float | str]:
    value: dict[str, int | float | str] = {
        "model_calls": 50,
        "paid_model_calls": 50,
        "solve_calls": 48,
        "decomposition_calls": 1,
        "extraction_calls": 1,
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "total_usd": "10.000000000000",
        "task_arm_runs": 1,
        "benchmark_grader_containers": 1,
        "max_input_tokens_per_task_arm": 500_000,
        "max_model_calls_per_task_arm": 50,
    }
    value.update(overrides)
    if any(
        name in overrides
        for name in ("solve_calls", "decomposition_calls", "extraction_calls")
    ):
        value["model_calls"] = sum(
            int(value[name])
            for name in ("solve_calls", "decomposition_calls", "extraction_calls")
        )
        value["paid_model_calls"] = value["model_calls"]
    value["uncached_token_cost_ceiling_usd"] = format(
        (
            Decimal(int(value["input_tokens"])) * Decimal("0.75")
            + Decimal(int(value["output_tokens"])) * Decimal("4.5")
        )
        / Decimal(1_000_000),
        ".12f",
    )
    return value


def _ledger(tmp_path: Path, **overrides: int | float | str) -> benchmark.AtomicBudgetLedger:
    return benchmark.AtomicBudgetLedger(
        tmp_path / "budget-ledger.json",
        approval_digest="a" * 64,
        caps=_caps(**overrides),
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
    )


def _request(
    *, prompt: str = "bounded prompt", logical_call_id: str = "task:M0:solve:0001"
) -> GatewayRequest:
    return GatewayRequest(
        task_id="task",
        arm="M0",
        step_no=1,
        call_kind="solve",
        logical_call_id=logical_call_id,
        prompt=prompt,
        max_output_tokens=1,
        org_id="benchmark",
        active_node_id="S1",
    )


def _paid_gateway(
    ledger: benchmark.AtomicBudgetLedger,
    calls: list[str],
    *,
    response: GatewayResponse | None = None,
) -> benchmark.BudgetedModelGateway:
    bridge = AsyncProviderModelGateway(object(), lambda coroutine: coroutine, expected_model="fixture-model")

    def invoke(request: GatewayRequest) -> GatewayResponse:
        calls.append(request.logical_call_id)
        return response or GatewayResponse(
            text="ok",
            provider="fixture",
            model="fixture-model",
            input_tokens=3,
            cached_input_tokens=0,
            output_tokens=1,
            reasoning_tokens=0,
            wall_time_ms=1,
            paid=True,
        )

    bridge.invoke = invoke  # type: ignore[method-assign]
    return benchmark.BudgetedModelGateway(bridge, ledger, stream_id="stream")


def _reserve_task(ledger: benchmark.AtomicBudgetLedger) -> None:
    ledger.reserve_task_arm("stream:M0:task")


def _settle_request(
    ledger: benchmark.AtomicBudgetLedger,
    logical_id: str,
    *,
    call_kind: str = "solve",
    input_upper_bound: int = 10,
    input_tokens: int = 1,
    output_cap: int = 1,
    output_tokens: int = 1,
    conservative_unknown: bool = False,
) -> None:
    reservation = ledger.reserve(
        logical_id,
        task_arm_key="stream:M0:task",
        call_kind=call_kind,
        input_upper_bound=input_upper_bound,
        output_cap=output_cap,
    )
    ledger.reconcile(
        logical_id,
        reservation,
        input_tokens=input_tokens,
        cached_input_tokens=0,
        output_tokens=output_tokens,
        status=(
            "PROVIDER_FAILURE_CONSERVATIVE"
            if conservative_unknown else "SUCCESS"
        ),
        conservative_unknown=conservative_unknown,
    )


def _record_request_only(
    evidence: RawEvidenceLedger, request: GatewayRequest
) -> None:
    prompt = evidence.put_blob(request.prompt)
    evidence.append("model_request", {
        "task_id": request.task_id,
        "arm": request.arm,
        "step_no": request.step_no,
        "call_kind": request.call_kind,
        "logical_call_id": request.logical_call_id,
        "request_sha256": gateway_request_sha256(request),
        "active_node_id": request.active_node_id,
        "org_id": request.org_id,
        "prompt": prompt,
        "prompt_projection": None,
        "max_output_tokens": request.max_output_tokens,
        "output_schema_name": request.output_schema_name,
        "output_schema_sha256": request.output_schema_sha256,
        "strict_structured_output": request.strict_structured_output,
        "response_mode": request.response_mode,
        "function_tools_sha256": request.function_tools_sha256,
        "tool_choice": request.tool_choice,
        "parallel_tool_calls": request.parallel_tool_calls,
    })


def _event_types(evidence: RawEvidenceLedger) -> list[str]:
    return [
        json.loads(line)["event_type"]
        for line in evidence.events_path.read_text(encoding="utf-8").splitlines()
    ]


def _canonical_preflight_failure_payload(
    request: GatewayRequest,
    *,
    classification: str = "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
) -> dict[str, object]:
    failure = ModelPreflightFailure(classification)
    prompt_raw = request.prompt.encode("utf-8")
    return {
        "task_id": request.task_id,
        "arm": request.arm,
        "step_no": request.step_no,
        "call_kind": request.call_kind,
        "logical_call_id": request.logical_call_id,
        "request_sha256": gateway_request_sha256(request),
        "prompt_sha256": benchmark.sha256_bytes(prompt_raw),
        "prompt_bytes": len(prompt_raw),
        "prompt_projection": request.prompt_projection,
        "classification": failure.classification,
        "scope": failure.scope,
        "details": {},
        "model_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_usd": 0,
    }


def test_canonical_preflight_evidence_rejects_global_class_with_cell_scope() -> None:
    request = _request()
    payload = _canonical_preflight_failure_payload(
        request,
        classification="PHASE_MODEL_CALL_CAP_EXHAUSTED",
    )
    payload["scope"] = "CELL"

    with pytest.raises(
        CheckpointMismatch,
        match="scope or zero-charge proof differs",
    ):
        _validated_model_preflight_failure(payload, request=request)


@pytest.mark.parametrize(
    "charged_field",
    ("model_calls", "input_tokens", "output_tokens", "total_usd"),
)
def test_canonical_preflight_evidence_rejects_nonzero_charge(
    charged_field: str,
) -> None:
    request = _request()
    payload = _canonical_preflight_failure_payload(request)
    payload[charged_field] = 1

    with pytest.raises(
        CheckpointMismatch,
        match="scope or zero-charge proof differs",
    ):
        _validated_model_preflight_failure(payload, request=request)


def test_gateway_request_binds_sanitized_prompt_projection() -> None:
    prompt = "prompt"
    digest = benchmark.sha256_bytes(prompt.encode("utf-8"))
    request = GatewayRequest(
        task_id="task", arm="M0", step_no=1, call_kind="solve",
        logical_call_id="call", prompt=prompt, max_output_tokens=1,
        prompt_projection={"final_prompt_sha256": digest, "status": "BOUNDED"},
    )
    assert request.prompt_projection["final_prompt_sha256"] == digest
    with pytest.raises(ValueError, match="final prompt hash differs"):
        GatewayRequest(
            task_id="task", arm="M0", step_no=1, call_kind="solve",
            logical_call_id="call", prompt=prompt, max_output_tokens=1,
            prompt_projection={"final_prompt_sha256": "0" * 64},
        )


def test_absent_projection_preserves_pre_d19_request_identity() -> None:
    request = _request()
    historical = asdict(request)
    historical.pop("prompt_projection")
    assert gateway_request_sha256(request) == benchmark.sha256_bytes(
        benchmark.canonical_bytes(historical)
    )


def test_read_only_preview_is_hash_bound_and_does_not_mutate(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    request = _request()
    gateway = _paid_gateway(ledger, [])
    before = ledger.path.read_bytes()
    preview = gateway.preview_reservation(request)
    assert isinstance(preview, ReservationPreflight)
    assert preview.status == "PREFLIGHT_PASSED"
    assert preview.request_sha256 == gateway_request_sha256(request)
    assert ledger.path.read_bytes() == before
    assert ledger.request_row(preview.ledger_logical_call_id) is None


def test_preflight_context_failure_precedes_all_request_side_effects(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    before = ledger.path.read_bytes()
    calls: list[str] = []
    journal = benchmark.TerminalInvocationJournal(tmp_path / "journal")
    evidence = RawEvidenceLedger(tmp_path / "evidence")
    recording = RecordingModelGateway(
        benchmark.JournaledModelGateway(_paid_gateway(ledger, calls), journal),
        RunAccounting(),
        evidence,
    )
    request = _request(prompt="x" * 258_000)
    with pytest.raises(ModelPreflightFailure) as captured:
        recording.invoke(request)
    assert captured.value.classification == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    assert captured.value.scope == "CELL"
    assert _event_types(evidence) == ["model_preflight_failure"]
    assert list(evidence.blob_dir.iterdir()) == []
    assert not (journal.root / "model").exists()
    assert ledger.path.read_bytes() == before
    assert calls == []


def test_atomic_reservation_disagreement_is_global_integrity_failure(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    gateway = _paid_gateway(ledger, [])
    request = _request()
    preview = gateway.preview_reservation(request)
    ledger.reserve(
        "unrelated",
        task_arm_key="stream:M0:task",
        call_kind="solve",
        input_upper_bound=10,
        output_cap=1,
    )
    with pytest.raises(ModelPreflightFailure) as captured:
        gateway.reserve_preflighted(request, preview)
    assert captured.value.classification == "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE"
    assert captured.value.scope == "GLOBAL"


@pytest.mark.parametrize(
    "field",
    (
        "paid_model_calls",
        "solve_calls",
        "input_tokens",
        "output_tokens",
        "total_usd",
    ),
)
def test_unbacked_phase_counter_cannot_masquerade_as_cap_exhaustion(
    tmp_path: Path, field: str
) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    state = benchmark.read_json(ledger.path)
    state["actual"][field] = ledger.caps[field]
    benchmark.write_json(ledger.path, state)
    before = ledger.path.read_bytes()
    with pytest.raises(ModelPreflightFailure) as captured:
        _paid_gateway(ledger, []).preview_reservation(_request())
    assert captured.value.classification == "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE"
    assert captured.value.scope == "GLOBAL"
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize(
    "mutation",
    (
        "input",
        "calls",
        "role_output",
        "total_output",
    ),
)
def test_unbacked_task_counter_is_global_integrity_not_cell_exhaustion(
    tmp_path: Path, mutation: str
) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    state = benchmark.read_json(ledger.path)
    task = state["task_arms"]["stream:M0:task"]
    if mutation == "input":
        task["actual_input_tokens"] = ledger.caps["max_input_tokens_per_task_arm"]
    elif mutation == "calls":
        task["actual_model_calls"] = ledger.caps["max_model_calls_per_task_arm"]
    elif mutation == "role_output":
        task["actual_solve_output_tokens"] = benchmark.TASK_OUTPUT_POOL_BY_CALL_KIND["solve"]
    else:
        # This deliberately exercises the independent total-pool guard.  Normal
        # role accounting reaches a role guard first because the pools sum to
        # the total, but corrupted/stale task projections must still fail closed.
        task["actual_output_tokens"] = benchmark.TASK_TOTAL_OUTPUT_POOL
    benchmark.write_json(ledger.path, state)
    before = ledger.path.read_bytes()
    with pytest.raises(ModelPreflightFailure) as captured:
        _paid_gateway(ledger, []).preview_reservation(_request())
    assert captured.value.classification == "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE"
    assert captured.value.scope == "GLOBAL"
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize(
    ("caps", "settled", "classification"),
    (
        (
            {"solve_calls": 1},
            {"input_upper_bound": 10, "input_tokens": 1,
             "output_cap": 1, "output_tokens": 1},
            "PHASE_MODEL_CALL_CAP_EXHAUSTED",
        ),
        (
            {"input_tokens": 5_000},
            {"input_upper_bound": 5_000, "input_tokens": 5_000,
             "output_cap": 1, "output_tokens": 1},
            "PHASE_INPUT_CAP_EXHAUSTED",
        ),
        (
            {"output_tokens": 1},
            {"input_upper_bound": 10, "input_tokens": 1,
             "output_cap": 1, "output_tokens": 1},
            "PHASE_OUTPUT_CAP_EXHAUSTED",
        ),
        (
            {"total_usd": "0.000005250000"},
            {"input_upper_bound": 1, "input_tokens": 1,
             "output_cap": 1, "output_tokens": 1},
            "PHASE_USD_CAP_EXHAUSTED",
        ),
    ),
)
def test_coherently_reconstructed_phase_exhaustion_keeps_global_classification(
    tmp_path: Path,
    caps: dict[str, int | str],
    settled: dict[str, int],
    classification: str,
) -> None:
    ledger = _ledger(tmp_path, **caps)
    _reserve_task(ledger)
    _settle_request(ledger, "settled", **settled)
    before = ledger.path.read_bytes()
    with pytest.raises(ModelPreflightFailure) as captured:
        _paid_gateway(ledger, []).preview_reservation(_request())
    assert captured.value.classification == classification
    assert captured.value.scope == "GLOBAL"
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize(
    ("caps", "settled_calls", "classification"),
    (
        (
            {"max_input_tokens_per_task_arm": 10},
            (("solve", 10, 10, 1, 1),),
            "TASK_ARM_INPUT_POOL_EXHAUSTED",
        ),
        (
            {"max_model_calls_per_task_arm": 1},
            (("solve", 10, 1, 1, 1),),
            "TASK_ARM_MODEL_CALL_POOL_EXHAUSTED",
        ),
        (
            {},
            (
                ("solve", 10, 1, 16_384, 16_384),
                ("solve", 10, 1, 16_384, 16_384),
                ("solve", 10, 1, 16_384, 16_384),
            ),
            "TASK_ROLE_OUTPUT_POOL_EXHAUSTED",
        ),
    ),
)
def test_coherently_reconstructed_task_exhaustion_is_cell_scoped(
    tmp_path: Path,
    caps: dict[str, int],
    settled_calls: tuple[tuple[str, int, int, int, int], ...],
    classification: str,
) -> None:
    ledger = _ledger(tmp_path, **caps)
    _reserve_task(ledger)
    for index, (
        call_kind, input_upper_bound, input_tokens, output_cap, output_tokens
    ) in enumerate(settled_calls):
        _settle_request(
            ledger,
            f"settled-{index}",
            call_kind=call_kind,
            input_upper_bound=input_upper_bound,
            input_tokens=input_tokens,
            output_cap=output_cap,
            output_tokens=output_tokens,
        )
    before = ledger.path.read_bytes()
    with pytest.raises(ModelPreflightFailure) as captured:
        _paid_gateway(ledger, []).preview_reservation(_request())
    assert captured.value.classification == classification
    assert captured.value.scope == "CELL"
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize(
    ("corruption", "reason_fragment"),
    (
        ("phase_outstanding", "outstanding input_tokens disagrees"),
        ("task_outstanding", "task-arm outstanding_input_tokens disagrees"),
        ("reserved_with_terminal_usage", "reserved request shape differs"),
        ("terminal_task_with_live_request", "reserved request belongs to a terminal"),
        ("orphan_request", "request has no task-arm reservation"),
        ("nonconservative_conservative_status", "not cap-charged"),
        ("malformed_task_status", "task-arm lifecycle status is malformed"),
        ("malformed_request_status", "request lifecycle status is malformed"),
        ("malformed_call_kind", "request role binding differs"),
    ),
)
def test_impossible_counter_and_request_lifecycle_states_fail_global_before_caps(
    tmp_path: Path, corruption: str, reason_fragment: str
) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    reservation = ledger.reserve(
        "inflight",
        task_arm_key="stream:M0:task",
        call_kind="solve",
        input_upper_bound=10,
        output_cap=1,
    )
    if corruption == "nonconservative_conservative_status":
        ledger.reconcile(
            "inflight",
            reservation,
            input_tokens=1,
            cached_input_tokens=0,
            output_tokens=1,
            status="PROVIDER_FAILURE_CONSERVATIVE",
            conservative_unknown=True,
        )
    state = benchmark.read_json(ledger.path)
    request_row = state["requests"]["inflight"]
    task_row = state["task_arms"]["stream:M0:task"]
    if corruption == "phase_outstanding":
        state["outstanding"]["input_tokens"] += 1
    elif corruption == "task_outstanding":
        task_row["outstanding_input_tokens"] += 1
    elif corruption == "reserved_with_terminal_usage":
        request_row.update({
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "actual_usd": 0.0,
        })
    elif corruption == "terminal_task_with_live_request":
        task_row.update({"status": "CELL_TERMINAL", "container_started": True})
        state["outstanding"]["task_arm_runs"] = 0
        state["outstanding"]["grader_containers"] = 0
        state["actual"]["task_arm_runs"] = 1
        state["actual"]["grader_containers"] = 1
    elif corruption == "orphan_request":
        request_row["task_arm_key"] = "stream:M0:missing"
    elif corruption == "nonconservative_conservative_status":
        request_row["input_tokens"] = 1
    elif corruption == "malformed_task_status":
        task_row["status"] = []
    elif corruption == "malformed_request_status":
        request_row["status"] = []
    elif corruption == "malformed_call_kind":
        request_row["call_kind"] = []
    else:  # pragma: no cover - exhaustive parameter guard
        raise AssertionError(corruption)
    benchmark.write_json(ledger.path, state)
    before = ledger.path.read_bytes()

    with pytest.raises(ModelPreflightFailure) as captured:
        _paid_gateway(ledger, []).preview_reservation(
            _request(logical_call_id="task:M0:solve:0002")
        )
    assert captured.value.classification == "LEDGER_IDENTITY_OR_INTEGRITY_FAILURE"
    assert captured.value.scope == "GLOBAL"
    assert reason_fragment in str(captured.value.details.get("reason"))
    assert ledger.path.read_bytes() == before


def test_recording_persists_projection_only_after_preflight_passes(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    calls: list[str] = []
    journal = benchmark.TerminalInvocationJournal(tmp_path / "journal")
    evidence = RawEvidenceLedger(tmp_path / "evidence")
    prompt = "bounded prompt"
    projection = {
        "status": "BOUNDED",
        "final_prompt_sha256": benchmark.sha256_bytes(prompt.encode("utf-8")),
    }
    request = GatewayRequest(
        task_id="task", arm="M0", step_no=1, call_kind="solve",
        logical_call_id="task:M0:solve:0001", prompt=prompt,
        max_output_tokens=1, org_id="benchmark", active_node_id="S1",
        prompt_projection=projection,
    )
    recording = RecordingModelGateway(
        benchmark.JournaledModelGateway(_paid_gateway(ledger, calls), journal),
        RunAccounting(),
        evidence,
    )
    recording.invoke(request)
    rows = [json.loads(line) for line in evidence.events_path.read_text().splitlines()]
    request_row = next(row for row in rows if row["event_type"] == "model_request")
    assert request_row["payload"]["prompt_projection"] == projection
    journal_path = journal._path("model", request.logical_call_id)
    assert benchmark.read_json(journal_path)["status"] == "PROVIDER_TERMINAL_SUCCESS"
    assert calls == [request.logical_call_id]


def test_provider_send_and_terminal_reconciliation_have_exact_durable_order(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    calls: list[str] = []
    budgeted = _paid_gateway(ledger, calls)
    journal = benchmark.TerminalInvocationJournal(tmp_path / "journal")
    evidence = RawEvidenceLedger(tmp_path / "evidence")
    request = _request()
    journal_path = journal._path("model", request.logical_call_id)

    def provider(request_value: GatewayRequest) -> GatewayResponse:
        assert request_value is request
        assert _event_types(evidence) == ["model_request"]
        assert benchmark.read_json(journal_path)["status"] == "PROVIDER_SEND_STARTED"
        ledger_row = budgeted.request_row(request)
        assert ledger_row is not None and ledger_row["status"] == "RESERVED"
        calls.append(request.logical_call_id)
        return GatewayResponse(
            text="ok", provider="fixture", model="fixture-model",
            input_tokens=3, cached_input_tokens=0, output_tokens=1,
            reasoning_tokens=0, wall_time_ms=1, paid=True,
        )

    budgeted.delegate.invoke = provider  # type: ignore[method-assign]
    original_reconcile = ledger.reconcile_or_verify

    def reconcile(*args, **kwargs) -> None:
        assert benchmark.read_json(journal_path)["status"] == "PROVIDER_TERMINAL_SUCCESS"
        original_reconcile(*args, **kwargs)

    ledger.reconcile_or_verify = reconcile  # type: ignore[method-assign]
    recording = RecordingModelGateway(
        benchmark.JournaledModelGateway(budgeted, journal),
        RunAccounting(),
        evidence,
    )
    assert recording.invoke(request).text == "ok"
    assert _event_types(evidence) == ["model_request", "model_response"]
    assert calls == [request.logical_call_id]


def test_request_only_resume_reuses_event_and_safely_upgrades_exact_legacy_window(
    tmp_path: Path,
) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    calls: list[str] = []
    journal = benchmark.TerminalInvocationJournal(tmp_path / "journal")
    evidence = RawEvidenceLedger(tmp_path / "evidence")
    request = _request()
    _record_request_only(evidence, request)
    legacy_path = journal.begin(
        "model", request.logical_call_id, gateway_request_sha256(request)
    )
    benchmark.write_json(
        legacy_path,
        {**benchmark.read_json(legacy_path), "delegate_started": True},
    )
    journaled = benchmark.JournaledModelGateway(_paid_gateway(ledger, calls), journal)
    assert journaled.request_lifecycle(request) == {
        "state": "REQUEST_RECORDED",
        "request_sha256": gateway_request_sha256(request),
        "journal_present": True,
        "ledger_reservation_present": False,
        "provider_send_started": False,
    }
    recording = RecordingModelGateway(journaled, RunAccounting(), evidence)
    assert recording.invoke(
        request,
        request_already_recorded=True,
        required_request_lifecycle_state="REQUEST_RECORDED",
    ).text == "ok"
    assert calls == [request.logical_call_id]
    assert _event_types(evidence).count("model_request") == 1
    assert _event_types(evidence).count("model_response") == 1
    assert benchmark.read_json(legacy_path)["status"] == "PROVIDER_TERMINAL_SUCCESS"


def test_send_started_without_outcome_is_settled_and_never_retried(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    _reserve_task(ledger)
    calls: list[str] = []
    budgeted = _paid_gateway(ledger, calls)
    journal = benchmark.TerminalInvocationJournal(tmp_path / "journal")
    journaled = benchmark.JournaledModelGateway(budgeted, journal)
    evidence = RawEvidenceLedger(tmp_path / "evidence")
    accounting = RunAccounting()
    request = _request()
    _record_request_only(evidence, request)
    preflight = budgeted.preview_reservation(request)
    path = journal.begin_model_request(
        request.logical_call_id, gateway_request_sha256(request), preflight
    )
    budgeted.reserve_preflighted(request, preflight)
    journal.transition_model(
        path,
        expected=("REQUEST_RECORDED",),
        status="PROVIDER_SEND_STARTED",
        values={"provider_send_started": True},
    )
    recording = RecordingModelGateway(journaled, accounting, evidence)
    with pytest.raises(GatewayInvocationFailure) as captured:
        recording.invoke(
            request,
            request_already_recorded=True,
            required_request_lifecycle_state="PROVIDER_SEND_STARTED",
        )
    assert captured.value.status == "MODEL_REQUEST_TERMINAL_OUTCOME_UNKNOWN"
    assert captured.value.terminal_outcome_replayed is True
    assert calls == []
    assert benchmark.read_json(path)["status"] == "PROVIDER_OUTCOME_UNKNOWN"
    state = benchmark.read_json(ledger.path)
    row = state["requests"][preflight.ledger_logical_call_id]
    assert row["status"] == "PROVIDER_FAILURE_CONSERVATIVE"
    assert state["actual"]["paid_model_calls"] == 1
    assert state["actual"]["input_tokens"] == preflight.input_upper_bound
    assert state["actual"]["output_tokens"] == preflight.output_cap
    assert _event_types(evidence).count("model_failure") == 1
    charged = benchmark.actual_accounting(accounting.to_dict())
    assert charged["model_gateway_calls"] == 1
    assert charged["input_tokens"] == preflight.input_upper_bound
    assert charged["output_tokens"] == preflight.output_cap
    assert charged["cached_input_tokens"] == charged["reasoning_tokens"] == 0

    with pytest.raises(GatewayInvocationFailure):
        recording.invoke(
            request,
            request_already_recorded=True,
            required_request_lifecycle_state="PROVIDER_OUTCOME_UNKNOWN",
        )
    assert calls == []
    assert _event_types(evidence).count("model_failure") == 1
    assert _event_types(evidence).count("model_terminal_outcome_replayed") == 1


class _SuccessfulCellExtractionPreflightModel:
    """Credential-free model whose extraction fails before any provider send."""

    def __init__(self) -> None:
        self.preflight_calls: list[str] = []
        self.provider_calls: list[str] = []
        self.replay = ReplayModelGateway(self._reply, model="d19-preflight-fixture-v1")

    @staticmethod
    def _reply(request: GatewayRequest) -> str:
        if request.call_kind == "decompose":
            return json.dumps({
                "subtasks": [{
                    "id": "verify-value",
                    "objective": "verify the public value invariant",
                    "predicted_operation": "confirm the value remains one",
                    "depends_on": [],
                    "files": ["value.py"],
                }],
            })
        if request.call_kind == "solve":
            return json.dumps({
                "tool": "complete_subtask",
                "arguments": {"evidence": "the public value is already correct"},
            })
        raise AssertionError("extraction must be rejected before provider invocation")

    def preview_reservation(self, request: GatewayRequest):
        self.preflight_calls.append(request.logical_call_id)
        if request.call_kind == "extract":
            raise ModelPreflightFailure(
                "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
                request_sha256=gateway_request_sha256(request),
                logical_call_id=request.logical_call_id,
            )
        return None

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        self.provider_calls.append(request.logical_call_id)
        return self.replay.invoke(request)


class _SuccessfulCellGrader:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def grade(self, request) -> GradeResult:
        self.calls.append(request.task_id)
        return GradeResult(
            task_id=request.task_id,
            resolved=True,
            exit_code=0,
            stdout="credential-free success fixture\n",
            stderr="",
            report={"task_id": request.task_id, "resolved": True},
            grader_id="d19-preflight-success-fixture",
            container_digest="fixture@sha256:" + "b" * 64,
            official=False,
            wall_time_ms=0,
            container_started=False,
            status="success",
        )


def _successful_cell_preflight_runtime(
    root: Path,
    model: _SuccessfulCellExtractionPreflightModel,
    grader: _SuccessfulCellGrader,
) -> TriMemAgentRuntime:
    return TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=model,
        grader_gateway=grader,
        memory_controller=NoMemoryController(),
        evidence=RawEvidenceLedger(root / "successful-cell-evidence"),
        checkpoint_store=FileCheckpointStore(root / "successful-cell-checkpoints"),
    )


def test_graded_extraction_preflight_crash_window_resumes_without_provider_send(
    tmp_path: Path,
) -> None:
    task = CodingTask(
        task_id="d19-successful-cell-extraction-preflight",
        org_id="org",
        user_id="fixture",
        repository="example/repo",
        commit="c" * 40,
        instruction="Verify that VALUE remains one.",
        files={"value.py": "VALUE = 1\n"},
        editable_paths=("value.py",),
    )
    model = _SuccessfulCellExtractionPreflightModel()
    grader = _SuccessfulCellGrader()
    run_id = "stream-00-M0"
    first = _successful_cell_preflight_runtime(tmp_path, model, grader)

    # Calling the strict core simulates a process crash after the recorder has
    # fsynced the local preflight failure but before the public runner contains
    # it.  The last committed phase is the otherwise successful GRADED cell.
    with pytest.raises(ModelPreflightFailure) as captured:
        first._run_strict(task, arm="M0", run_id=run_id)
    assert captured.value.classification == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    interrupted = first.checkpoints.load(run_id, required_config_hashes=None)
    assert interrupted.state == "GRADED"
    assert _event_types(first.evidence)[-1] == "model_preflight_failure"
    provider_calls_at_crash = tuple(model.provider_calls)
    preflight_calls_at_crash = tuple(model.preflight_calls)
    assert f"{task.task_id}:M0:extract:0001" not in provider_calls_at_crash

    resumed = _successful_cell_preflight_runtime(tmp_path, model, grader)
    result = resumed.run(task, arm="M0", run_id=run_id, resume=True)

    assert result.resolved is True
    assert result.agent_completed is True
    assert result.extraction_status == "MEMORY_EXTRACTION_FAILED"
    assert result.model_failure_class == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    assert tuple(model.provider_calls) == provider_calls_at_crash
    assert tuple(model.preflight_calls) == preflight_calls_at_crash
    assert grader.calls == [task.task_id]
    events = [
        json.loads(line)
        for line in resumed.evidence.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert sum(
        row["event_type"] == "model_preflight_failure"
        and row["payload"].get("call_kind") == "extract"
        for row in events
    ) == 1
    assert not any(
        row["event_type"] == "model_request"
        and row["payload"].get("call_kind") == "extract"
        for row in events
    )
    assert result.accounting["summary"]["by_call_kind"].get(
        "extract", {"calls": 0}
    )["calls"] == 0


def test_legacy_empty_list_files_fixture_is_adapted_only_in_replay() -> None:
    assert benchmark is not None
    from enterprise_memory.trimem.gateway import _complete_legacy_nullable_arguments

    assert _complete_legacy_nullable_arguments("list_files", {}) == {}
    assert _complete_legacy_nullable_arguments(
        "list_files",
        {},
        allow_pre_d19_unpaginated_list_files=True,
    ) == {
        "path_prefix": None,
        "start_after": None,
        "limit": 100,
    }
