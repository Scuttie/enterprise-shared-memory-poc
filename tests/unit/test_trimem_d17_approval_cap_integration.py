"""Credential-free D1.7 approval-consumer and phase-cap integration tests."""
from __future__ import annotations

import ast
from copy import deepcopy
from decimal import Decimal
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_action_canary as action_canary  # noqa: E402
import trimem_benchmark_matrix as benchmark_matrix  # noqa: E402
import trimem_benchmark_run as benchmark_run  # noqa: E402
import trimem_development_trigger_d15 as trigger  # noqa: E402
from trimem_development_phase_cap import (  # noqa: E402
    DevelopmentPhaseCapError,
    validate_development_phase_hard_cap,
)
from trimem_exec_approval import (  # noqa: E402
    DEVELOPMENT_APPROVAL_FIELDS,
    TOP_LEVEL_FIELDS,
    build_external_approval_document,
)


DUMMY_KEY = "DUMMY-VISIBLE-ASCII-CREDENTIAL-00000001"
RUN_ID = 246_813_579
D17_SOURCE_HEAD = "f5f6b8d0c6bef4aa704e25d8e67c526d437e967b"
D17_EXECUTION_HEAD = "8002847d0db8975dfd957a1322d31a7768fc098f"


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _strict_read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _remote_gates(source_head: str) -> dict[str, Any]:
    return {
        "schema": "trimem/development-remote-gate-evidence/1.0",
        "repository": trigger.EXPECTED_REPOSITORY,
        "source_ref": trigger.EXPECTED_REF,
        "source_head": source_head,
        "observed_at_utc": "2026-09-05T00:00:00Z",
        "all_required_workflows_passed": True,
        "scientific_execution": {
            "api_calls": 0,
            "grader_runs": 0,
            "model_calls": 0,
            "paid_model_calls": 0,
            "target_image_pulls": 0,
            "task_arm_runs": 0,
            "total_usd": 0.0,
        },
        "workflows": [
            {
                "workflow_path": workflow,
                "head_sha": source_head,
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "run_id": 900_000 + index,
            }
            for index, workflow in enumerate(trigger.REQUIRED_REMOTE_GATE_WORKFLOWS)
        ],
    }


@pytest.fixture(scope="module")
def exact_execution_fixture(tmp_path_factory):
    fixture_root = tmp_path_factory.mktemp("d17-exact-execution")
    repository = fixture_root / "repository"
    source_head = D17_SOURCE_HEAD
    assert _git(ROOT, "rev-parse", D17_EXECUTION_HEAD + "^") == source_head
    assert _git(
        ROOT,
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        "--no-renames",
        D17_EXECUTION_HEAD,
    ).splitlines() == [f"A\t{trigger.SENTINEL_PATH}"]
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", str(ROOT), str(repository)],
        check=True,
    )
    _git(repository, "checkout", "--quiet", source_head)
    request = trigger.build_request(
        repository,
        source_head=source_head,
        remote_gate_evidence=_remote_gates(source_head),
    )
    request_path = repository / trigger.SENTINEL_PATH
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_raw = trigger.canonical_bytes(request, trailing_lf=True)
    request_path.write_bytes(request_raw)
    _git(repository, "config", "user.email", "credential-free@example.invalid")
    _git(repository, "config", "user.name", "Credential-Free Fixture")
    _git(repository, "add", "--", trigger.SENTINEL_PATH)
    _git(repository, "commit", "--quiet", "-m", "fixture: exact sentinel-only commit")
    execution_head = _git(repository, "rev-parse", "HEAD")
    assert trigger.validate_sentinel_commit(repository, execution_head) == request

    hard = _strict_read(repository / "configs/trimem_v1/cost_plan.json")[
        "phase_hard_caps"
    ]["DEVELOPMENT_TUNING"]
    freeze_raw = (repository / "artifacts/trimem_v1/freeze.json").read_bytes()
    approval = build_external_approval_document(
        request_id=request["request_id"],
        request_sha256=hashlib.sha256(request_raw).hexdigest(),
        git_commit=execution_head,
        source_git_commit=source_head,
        freeze_sha256=hashlib.sha256(freeze_raw).hexdigest(),
        phase="DEVELOPMENT_TUNING",
        task_arm_runs=hard["task_arm_runs"],
        paid_model_call_cap=hard["paid_model_calls"],
        input_token_cap=hard["input_tokens"],
        output_token_cap=hard["output_tokens"],
        currency_hard_cap=hard["total_usd"],
        grader_containers=hard["benchmark_grader_containers"],
        workflow_run_id=RUN_ID,
        workflow_run_attempt=1,
        legal_terms_acceptance=True,
        approval_actor="credential-free-regression",
        approval_timestamp="2026-09-05T00:00:00Z",
        openai_api_key=DUMMY_KEY,
        approval_nonce="credential-free-regression-0001",
        model_id=action_canary.MODEL,
    )
    return {
        "repository": repository,
        "request": request,
        "hard_cap": hard,
        "execution_head": execution_head,
        "source_head": source_head,
        "approval": approval,
    }


class FakeResponse:
    def __init__(self):
        body = {
            "id": "resp-canary",
            "status": "completed",
            "model": action_canary.MODEL,
            "output": [{
                "id": "fc-canary",
                "type": "function_call",
                "call_id": "call-canary",
                "name": "list_files",
                "arguments": "{}",
            }],
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 20},
                "output_tokens": 10,
                "output_tokens_details": {"reasoning_tokens": 3},
                "total_tokens": 110,
            },
        }
        self.content = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.status_code = 200
        self.headers = {"x-request-id": "credential-free-request"}


class FakeAsyncClient:
    def __init__(self, calls: list[dict[str, Any]]):
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, *, json, headers, timeout):
        self.calls.append({
            "url": url,
            "body": json,
            "authorization_present": "Authorization" in headers,
            "timeout": timeout,
        })
        return FakeResponse()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _approval_file(tmp_path: Path, value: dict[str, Any], *, raw: bytes | None = None) -> Path:
    path = tmp_path / "external-approval.json"
    path.write_bytes(_canonical(value) if raw is None else raw)
    return path


def _prepare_runtime(monkeypatch, fixture, calls):
    monkeypatch.setattr(benchmark_run, "ROOT", fixture["repository"])
    # D1.7 is immutable historical evidence.  The production runner now imports
    # the active D1.8 `_009` reader, while this fixture deliberately creates the
    # frozen D1.7 `_008` sentinel-only commit.  Rebind only the injected trigger
    # dependency so these tests continue exercising the original D1.7 contract.
    monkeypatch.setattr(
        benchmark_run, "DEVELOPMENT_EXEC_REQUEST", Path(trigger.SENTINEL_PATH)
    )
    monkeypatch.setattr(
        benchmark_run, "DEVELOPMENT_WORKFLOW_REF", trigger.EXPECTED_WORKFLOW_REF
    )
    monkeypatch.setattr(
        benchmark_run,
        "validate_development_sentinel_commit",
        trigger.validate_sentinel_commit,
    )
    monkeypatch.setattr(
        benchmark_run, "DevelopmentTriggerError", trigger.DevelopmentTriggerError
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("GITHUB_RUN_ID", str(RUN_ID))
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", trigger.EXPECTED_WORKFLOW_REF)
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", fixture["execution_head"])
    monkeypatch.setenv("OPENAI_API_KEY", DUMMY_KEY)
    monkeypatch.setattr(
        action_canary.httpx,
        "AsyncClient",
        lambda: FakeAsyncClient(calls),
    )


def _output_path(tmp_path: Path, name: str = "protocol-action-canary.json") -> Path:
    return (
        tmp_path
        / "artifacts/trimem_v1/benchmark_exec/development/control"
        / name
    )


def test_a_k_exact_approval_production_canary_and_aggregate_path_pass(
    tmp_path, monkeypatch, exact_execution_fixture
):
    fixture = exact_execution_fixture
    calls: list[dict[str, Any]] = []
    _prepare_runtime(monkeypatch, fixture, calls)
    approval_path = _approval_file(tmp_path, fixture["approval"])

    validated = benchmark_run.validate_exec_approval("development", approval_path)
    assert validated["phase"] == "DEVELOPMENT_TUNING"
    assert validated["hard_cap"] == validate_development_phase_hard_cap(
        fixture["hard_cap"]
    )
    assert set(fixture["approval"]) == TOP_LEVEL_FIELDS
    assert set(fixture["approval"]["approval"]) == set(DEVELOPMENT_APPROVAL_FIELDS)
    assert "hard_cap" not in fixture["approval"]
    output = _output_path(tmp_path)
    result = action_canary._run_strict(output, approval_path)

    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.openai.com/v1/responses"
    assert calls[0]["body"]["model"] == action_canary.MODEL
    assert calls[0]["body"]["max_output_tokens"] == 2_048
    assert calls[0]["body"]["reasoning"] == {"effort": "medium"}
    assert len(calls[0]["body"]["tools"]) == 9
    assert calls[0]["body"]["tool_choice"] == {
        "type": "function", "name": "list_files"
    }
    assert calls[0]["body"]["parallel_tool_calls"] is False
    assert result["status"] == "PASS"
    assert result["function_name"] == "list_files"
    assert result["input_tokens"] == 100
    assert result["cached_input_tokens"] == 20
    assert result["output_tokens"] == 10
    assert result["reasoning_tokens"] == 3
    assert result["actual_usd"] == "0.000106500000"
    assert result["approval_sha256"] == hashlib.sha256(
        approval_path.read_bytes()
    ).hexdigest()
    scientific = benchmark_run.scientific_caps_after_protocol_canary(
        fixture["hard_cap"],
        result,
        expected_approval_sha256=result["approval_sha256"],
    )
    assert scientific["model_calls"] == 1_872
    assert scientific["paid_model_calls"] == 1_872
    assert scientific["input_tokens"] == 36_000_000
    assert scientific["output_tokens"] == 4_718_592
    assert scientific["benchmark_grader_containers"] == 72
    assert scientific["task_arm_runs"] == 72
    assert Decimal(str(scientific["total_usd"])) == Decimal("49.9998935")
    assert Decimal(str(scientific["uncached_token_cost_ceiling_usd"])) == Decimal(
        "48.233664"
    )
    aggregate_cap = benchmark_matrix._scientific_hard_cap_for_aggregate(
        "development",
        output.parents[1],
        cost_plan={"phase_hard_caps": {"DEVELOPMENT_TUNING": fixture["hard_cap"]}},
        approval_binding={"approval_artifact_sha256": result["approval_sha256"]},
    )
    assert aggregate_cap == scientific
    assert not (tmp_path / "benchmark-images").exists()
    assert not list(tmp_path.rglob("*.grader.json"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("top_level_hard_cap", "external approval field set differs"),
        (
            "wrong_paid_cap",
            "approval cap does not equal frozen proposed cap: "
            "approved_paid_model_call_cap",
        ),
        ("missing_field", "approval binding fields are missing"),
    ],
)
def test_b_c_h_malformed_approval_fails_before_provider(
    mutation, message, tmp_path, monkeypatch, exact_execution_fixture
):
    fixture = exact_execution_fixture
    approval = deepcopy(fixture["approval"])
    if mutation == "top_level_hard_cap":
        approval["hard_cap"] = deepcopy(fixture["hard_cap"])
    elif mutation == "wrong_paid_cap":
        approval["approval"]["approved_paid_model_call_cap"] -= 1
    else:
        approval["approval"].pop("approved_output_token_cap")
    calls: list[dict[str, Any]] = []
    _prepare_runtime(monkeypatch, fixture, calls)
    with pytest.raises(benchmark_run.BenchmarkExecutionError, match=message):
        action_canary._run_strict(
            _output_path(tmp_path), _approval_file(tmp_path, approval)
        )
    assert calls == []


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("protocol_canary_calls", 2, "DEV protocol-canary call cap differs"),
        ("model_calls", 1_872, "DEV global model-call arithmetic differs"),
    ],
)
def test_d_e_cost_plan_cap_drift_fails_before_provider(
    field, value, message, tmp_path, monkeypatch, exact_execution_fixture
):
    fixture = exact_execution_fixture
    cost_path = fixture["repository"] / "configs/trimem_v1/cost_plan.json"
    original = cost_path.read_bytes()
    cost = json.loads(original)
    cost["phase_hard_caps"]["DEVELOPMENT_TUNING"][field] = value
    cost_path.write_bytes(json.dumps(cost, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    calls: list[dict[str, Any]] = []
    try:
        _prepare_runtime(monkeypatch, fixture, calls)
        with pytest.raises(benchmark_run.BenchmarkExecutionError, match=message):
            action_canary._run_strict(
                _output_path(tmp_path), _approval_file(tmp_path, fixture["approval"])
            )
    finally:
        cost_path.write_bytes(original)
    assert calls == []


@pytest.mark.parametrize(("field", "value"), [("INPUT_CAP", 4_095), ("OUTPUT_CAP", 2_047)])
def test_f_canary_reservation_drift_fails_before_provider(
    field, value, tmp_path, monkeypatch, exact_execution_fixture
):
    fixture = exact_execution_fixture
    calls: list[dict[str, Any]] = []
    _prepare_runtime(monkeypatch, fixture, calls)
    monkeypatch.setattr(action_canary, field, value)
    with pytest.raises(DevelopmentPhaseCapError, match="reservation differs"):
        action_canary._run_strict(
            _output_path(tmp_path), _approval_file(tmp_path, fixture["approval"])
        )
    assert calls == []


def test_g_duplicate_approval_json_key_fails_before_provider(
    tmp_path, monkeypatch, exact_execution_fixture
):
    fixture = exact_execution_fixture
    canonical = _canonical(fixture["approval"])
    duplicate = b'{"schema":"trimem/external-exec-approval/1.2",' + canonical[1:]
    calls: list[dict[str, Any]] = []
    _prepare_runtime(monkeypatch, fixture, calls)
    with pytest.raises(
        benchmark_run.BenchmarkExecutionError, match="invalid JSON"
    ) as exc_info:
        action_canary._run_strict(
            _output_path(tmp_path),
            _approval_file(tmp_path, fixture["approval"], raw=duplicate),
        )
    assert exc_info.value.__cause__ is not None
    assert "duplicate JSON key" in str(exc_info.value.__cause__)
    assert calls == []


def test_i_j_canary_has_no_independent_raw_approval_interpretation():
    strict_source = inspect.getsource(action_canary._run_strict)
    module_source = inspect.getsource(action_canary)
    strict_tree = ast.parse(strict_source)
    module_tree = ast.parse(module_source)
    assert "approval_path.read_bytes" not in strict_source
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
        and node.func.attr == "loads"
        for node in ast.walk(strict_tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "hard_cap"
        for node in ast.walk(module_tree)
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("total_usd", "50.0"), ("uncached_token_cost_ceiling_usd", "48.245952")],
)
def test_complete_cap_rejects_non_exact_monetary_scalar_types(
    field, value, exact_execution_fixture
):
    hard = deepcopy(exact_execution_fixture["hard_cap"])
    hard[field] = value
    with pytest.raises(DevelopmentPhaseCapError, match="scalar type differs"):
        validate_development_phase_hard_cap(hard)


def test_stale_canary_approval_binding_is_rejected_by_aggregate(
    tmp_path, exact_execution_fixture
):
    fixture = exact_execution_fixture
    canary = {
        "status": "PASS",
        "scientific_result": False,
        "generation_calls": 1,
        "input_token_cap": 4_096,
        "output_token_cap": 2_048,
        "model": action_canary.MODEL,
        "approval_sha256": "a" * 64,
        "input_tokens": 100,
        "cached_input_tokens": 20,
        "output_tokens": 10,
        "actual_usd": "0.000120000000",
    }
    path = _output_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(canary))
    with pytest.raises(benchmark_matrix.MatrixError, match="approval binding differs"):
        benchmark_matrix._scientific_hard_cap_for_aggregate(
            "development",
            path.parents[1],
            cost_plan={
                "phase_hard_caps": {
                    "DEVELOPMENT_TUNING": fixture["hard_cap"]
                }
            },
            approval_binding={"approval_artifact_sha256": "b" * 64},
        )
