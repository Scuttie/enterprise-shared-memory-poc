from __future__ import annotations

from dataclasses import asdict
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from enterprise_memory.trimem.accounting import (
    RawEvidenceLedger,
    RunAccounting,
    canonical_bytes,
    sha256_bytes,
)
from enterprise_memory.trimem.agent_runtime import (
    CANONICAL_FAILED_CELL_NOOP,
    CodingTask,
    NoMemoryController,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.checkpoint import FileCheckpointStore
from enterprise_memory.trimem.context_projection import (
    ContextProjectionError,
    MAX_EXTRACTION_PROMPT_UTF8_BYTES,
    MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES,
    MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES,
    MAX_ORDINARY_INPUT_BOUND,
    MAX_SOLVE_PROMPT_UTF8_BYTES,
    project_legacy_tool_history_for_model_replay,
    project_tool_history_for_model,
)
from enterprise_memory.trimem.gateway import (
    GatewayRequest,
    GatewayResponse,
    ModelPreflightFailure,
    ReplayModelGateway,
    gateway_request_sha256,
)
from enterprise_memory.trimem.grader import GradeResult
from enterprise_memory.trimem.runtime_lock import RuntimeLock
from enterprise_memory.trimem.scientific_terminal import (
    SCIENTIFIC_EXECUTION_STATUS,
    SCIENTIFIC_LEDGER_TERMINAL_STATUS,
)
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec
from enterprise_memory.trimem.workspace import (
    InMemoryRepositoryWorkspace,
    RecordingToolExecutor,
    list_files_page,
)


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_development_trigger_d19 as development_trigger  # noqa: E402

_TERMINAL_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "_trimem_d18_terminal_fixture",
    ROOT / "tests/unit/test_trimem_d18_terminal_contract_integration.py",
)
if _TERMINAL_FIXTURE_SPEC is None or _TERMINAL_FIXTURE_SPEC.loader is None:
    raise RuntimeError("D1.8 terminal fixture module cannot be loaded")
terminal_fixture = importlib.util.module_from_spec(_TERMINAL_FIXTURE_SPEC)
sys.modules[_TERMINAL_FIXTURE_SPEC.name] = terminal_fixture
_TERMINAL_FIXTURE_SPEC.loader.exec_module(terminal_fixture)


def _history_row(step: int, node: str, tool: str, arguments: dict, result: dict) -> dict:
    request = {"tool": tool, "arguments": arguments}
    request_raw, result_raw = canonical_bytes(request), canonical_bytes(result)
    return {
        "task_id": "task",
        "arm": "M0",
        "step_no": step,
        "active_node_id": node,
        "tool": tool,
        "request": {
            "sha256": sha256_bytes(request_raw),
            "bytes": len(request_raw),
            "media_type": "application/json",
        },
        "result": {
            "sha256": sha256_bytes(result_raw),
            "bytes": len(result_raw),
            "media_type": "application/json",
        },
        "wall_time_ms": 0,
        "status": "success",
        "request_payload": request,
        "result_payload": result,
    }


def _large_paths() -> list[str]:
    paths = [
        "src/package_%05d/%s_module_%05d.py" % (index, "x" * 28, index)
        for index in range(10_000)
    ]
    paths.extend(["README.md", "src/new_untracked.py"])
    assert len(canonical_bytes(sorted(paths))) >= 319_417
    return paths


def _history() -> list[dict]:
    paths = _large_paths()
    listing = list_files_page(
        paths, {"path_prefix": None, "start_after": None, "limit": 200}
    )
    rows = [_history_row(1, "S1", "list_files", {
        "path_prefix": None, "start_after": None, "limit": 200,
    }, listing)]
    rows.append(_history_row(2, "S1", "read_file", {
        "path": "src/value.py", "start_line": 1, "max_lines": 2000,
    }, {
        "path": "src/value.py", "content": ("value = 1\n" * 12_000),
        "start_line": 1, "end_line": 12_000, "returned_start_line": 1,
        "returned_end_line": 12_000, "total_file_bytes": 120_000,
        "full_file_sha256": "1" * 64, "total_lines": 12_000,
        "truncated": False,
    }))
    rows.append(_history_row(3, "S1", "write_file", {
        "path": "src/new.py", "content": "PRIVATE-WRITE-BODY\n" * 10_000,
    }, {"path": "src/new.py", "content_hash": "2" * 64, "bytes": 190_000}))
    rows.append(_history_row(4, "S1", "replace_text", {
        "path": "src/value.py", "expected_file_sha256": "3" * 64,
        "old_text": "PRIVATE-OLD" * 2_000, "new_text": "PRIVATE-NEW" * 2_000,
    }, {
        "path": "src/value.py", "prior_sha256": "3" * 64,
        "new_sha256": "4" * 64, "old_bytes": 22_000,
        "new_bytes": 22_000, "replacements": 1,
    }))
    rows.append(_history_row(5, "S2", "search", {
        "query": "needle", "path": None,
    }, {"query": "needle", "hits": [
        {"path": f"src/f{i}.py", "line": i + 1, "text": "z" * 1_000}
        for i in range(100)
    ], "truncated": True}))
    rows.append(_history_row(6, "S2", "run_command", {
        "argv": ["python", "-m", "pytest"], "cwd": None,
        "timeout_seconds": 120,
    }, {
        "argv": ["python", "-m", "pytest"], "cwd": ".", "exit_code": 1,
        "stdout": "stdout-line\n" * 20_000,
        "stderr": "stderr-line\n" * 20_000,
        "timed_out": False, "output_truncated": False,
    }))
    rows.append(_history_row(7, "S1", "run_public_tests", {}, {
        "passed": False, "exit_code": 1,
        "stdout": "failed\n" * 20_000, "stderr": "trace\n" * 20_000,
    }))
    return rows


def _runtime_graph():
    runtime = object.__new__(TriMemAgentRuntime)
    runtime.lock = RuntimeLock()
    task = CodingTask(
        task_id="task", org_id="org", user_id="user",
        repository="example/repo", commit="a" * 40,
        instruction="Correct the value while preserving the public API.",
        files={}, editable_paths=(),
    )
    graph = ShortTermWorkingGraph(task.task_id, task.instruction, task.repository)
    graph.add_subtask(SubtaskSpec(
        node_id="S1", objective="Correct the stale value literal",
        operation="replace the stale integer literal", files=("src/value.py",),
    ))
    graph.activate("S1")
    return runtime, task, graph


def test_large_fixture_and_page_are_bounded():
    paths = _large_paths()
    page = list_files_page(
        paths, {"path_prefix": None, "start_after": None, "limit": 200}
    )
    assert len(paths) >= 10_000
    assert len(canonical_bytes(page)) <= 32_768
    assert page["truncated"] is True


def test_raw_exact_tool_evidence_remains_recoverable(tmp_path):
    evidence = RawEvidenceLedger(tmp_path / "evidence")
    accounting = RunAccounting()
    workspace = InMemoryRepositoryWorkspace(
        {"src/value.py": "value = 1\n", "README.md": "readme\n"},
        editable_paths=("src/value.py",),
    )
    executor = RecordingToolExecutor(
        workspace, accounting, evidence, task_id="task", arm="M0"
    )
    result = executor.execute(1, "S1", "list_files", {
        "path_prefix": None, "start_after": None, "limit": 1,
    })
    row = executor.history[0]
    assert row["result_payload"] == result
    assert strict_blob(evidence, row["result"]) == canonical_bytes(result)


def strict_blob(evidence: RawEvidenceLedger, reference: dict) -> bytes:
    raw = (evidence.blob_dir / reference["sha256"]).read_bytes()
    assert len(raw) == reference["bytes"]
    assert sha256_bytes(raw) == reference["sha256"]
    return raw


def test_projection_is_bounded_and_omits_edit_bodies():
    projection = project_tool_history_for_model(_history(), active_node_id="S1")
    raw = canonical_bytes(projection.model_value())
    assert len(raw) <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES
    assert projection.raw_history_bytes > projection.projected_history_bytes
    text = raw.decode("utf-8")
    assert "PRIVATE-WRITE-BODY" not in text
    assert "PRIVATE-OLD" not in text and "PRIVATE-NEW" not in text


def test_command_and_read_projection_use_hash_bound_bounded_text():
    history = _history()
    read = project_tool_history_for_model(
        [history[1]], active_node_id="S1"
    ).observations[0].result_summary
    command = project_tool_history_for_model(
        [history[5]], active_node_id="S2"
    ).observations[0].result_summary
    assert len(read["content"].encode("utf-8")) <= 65_536
    assert len(canonical_bytes(read)) <= 65_536
    assert read["next_start_line"] == (
        read["returned_start_line"] + len(read["content"].splitlines())
    )
    assert command["stdout_sha256"] and command["stderr_sha256"]
    assert len(canonical_bytes(command)) <= 65_536
    visible = sum(
        len(part.encode("utf-8"))
        for stream in (command["stdout"], command["stderr"])
        for part in (stream.get("text", ""), stream.get("head", ""), stream.get("tail", ""))
    )
    assert visible <= 65_536


def test_tool_error_projection_caps_the_complete_serialized_result():
    row = _history_row(
        1,
        "S1",
        "read_file",
        {"path": "src/value.py", "start_line": 1, "max_lines": 1},
        {"error": "ToolExecutionError", "message": "failure-" * 20_000},
    )

    projection = project_tool_history_for_model([row], active_node_id="S1")
    result = projection.observations[0].result_summary

    assert len(canonical_bytes(result)) <= MAX_MODEL_VISIBLE_TOOL_RESULT_BYTES
    assert result["message"]["truncated"] is True
    assert projection.observations[0].omission_reason == (
        "TOOL_ERROR_VISIBLE_RESULT_CAP"
    )


def test_read_projection_keeps_complete_cursor_addressable_lines_or_fails_closed():
    lines = [(str(index) + "-" + "x" * 998 + "\n") for index in range(100)]
    result = {
        "path": "large.txt",
        "content": "".join(lines),
        "start_line": 11,
        "end_line": 110,
        "returned_start_line": 11,
        "returned_end_line": 110,
        "total_file_bytes": 100_000,
        "full_file_sha256": "a" * 64,
        "total_lines": 200,
        "truncated": True,
    }
    row = _history_row(1, "S1", "read_file", {
        "path": "large.txt", "start_line": 11, "max_lines": 100,
    }, result)
    summary = project_tool_history_for_model(
        [row], active_node_id="S1"
    ).observations[0].result_summary
    visible_lines = summary["content"].splitlines(keepends=True)
    assert visible_lines == lines[:len(visible_lines)]
    assert summary["next_start_line"] == 11 + len(visible_lines)
    assert len(canonical_bytes(summary)) <= 65_536

    oversized_line = dict(result, content="z" * 70_000, truncated=False)
    oversized = _history_row(1, "S1", "read_file", {
        "path": "large.txt", "start_line": 11, "max_lines": 1,
    }, oversized_line)
    with pytest.raises(ContextProjectionError, match="one read_file line"):
        project_tool_history_for_model([oversized], active_node_id="S1")


def test_search_projection_complete_serialized_result_including_cursor_is_bounded():
    search = project_tool_history_for_model(
        [_history()[4]], active_node_id="S2"
    ).observations[0].result_summary
    assert len(canonical_bytes(search)) <= 65_536
    assert search["hit_count"] == 100
    assert search["visible_hit_count"] < search["hit_count"]
    assert search["next_hit_index"] == search["visible_hit_count"]
    assert search["projection_truncated"] is True


def test_active_subtask_observations_are_selected_first():
    projection = project_tool_history_for_model(
        _history(), active_node_id="S1", max_bytes=8_000
    )
    assert projection.observations
    assert projection.observations[0].active_node_id == "S1"
    assert any(row.active_node_id == "S1" for row in projection.observations)


@pytest.mark.parametrize("arm", ["M0", "M1", "M2"])
def test_projection_is_arm_independent(arm):
    del arm
    projection = project_tool_history_for_model(_history(), active_node_id="S1")
    assert projection.projection_sha256 == project_tool_history_for_model(
        _history(), active_node_id="S1"
    ).projection_sha256


def test_seven_observations_produce_bounded_solve_prompt_without_text_schema():
    runtime, task, graph = _runtime_graph()
    prompt, record = runtime._solve_prompt_projection(task, graph, _history(), ())
    assert len(prompt.encode("utf-8")) <= MAX_SOLVE_PROMPT_UTF8_BYTES
    assert len(prompt.encode("utf-8")) + 4_096 <= MAX_ORDINARY_INPUT_BOUND
    state = json.loads(prompt.split("\n\nSTATE:\n", 1)[1])
    assert "tool_schema" not in state
    assert state["function_tool_schema_sha256"] == runtime.lock.function_tools_sha256
    assert record["final_prompt_bytes"] == len(prompt.encode("utf-8"))


def test_native_function_schema_remains_on_gateway_request():
    runtime, task, graph = _runtime_graph()
    request, _ = runtime._build_solve_request(
        task, "M0", graph, _history(), (), RunAccounting(), 1
    )
    assert request.function_tools
    assert request.function_tools_sha256 == runtime.lock.function_tools_sha256
    assert request.prompt_projection is not None


def test_large_patch_and_history_produce_bounded_extraction_prompt():
    runtime, task, graph = _runtime_graph()
    grade = GradeResult(
        task_id=task.task_id, resolved=True, exit_code=0,
        stdout="hidden-not-used", stderr="", report={}, grader_id="replay",
        container_digest="replay@sha256:" + "f" * 64,
        official=False, wall_time_ms=0,
    )
    patch = "diff --git a/a b/a\n" + ("+changed line\n" * 50_000)
    prompt, public, record = runtime._extraction_prompt_projection(
        task, graph, _history(), patch, grade
    )
    assert len(prompt.encode("utf-8")) <= MAX_EXTRACTION_PROMPT_UTF8_BYTES
    assert public["schema"] == "trimem/model-visible-tool-history/1.0"
    assert record["final_prompt_bytes"] == len(prompt.encode("utf-8"))
    assert "hidden-not-used" not in prompt


def test_legacy_unpaginated_listing_requires_explicit_adapter():
    paths = _large_paths()
    row = _history_row(1, "S1", "list_files", {}, {"files": paths})
    with pytest.raises(Exception, match="live paginated shape"):
        project_tool_history_for_model([row], active_node_id="S1")
    projection = project_legacy_tool_history_for_model_replay(
        [row], active_node_id="S1"
    )
    assert projection.projected_history_bytes <= MAX_MODEL_VISIBLE_TOOL_HISTORY_BYTES
    assert projection.observations[0].result_summary["truncated"] is True


def test_projection_record_is_byte_stable():
    left = project_tool_history_for_model(_history(), active_node_id="S1")
    right = project_tool_history_for_model(_history(), active_node_id="S1")
    assert canonical_bytes(left.model_value()) == canonical_bytes(right.model_value())
    assert asdict(left) == asdict(right)


class _LocalTerminalGrader:
    """Official-shaped, credential-free grader used only for containment tests."""

    def __init__(self) -> None:
        self.task_ids: list[str] = []

    def grade(self, request) -> GradeResult:
        self.task_ids.append(request.task_id)
        resolved = request.task_id.endswith("cell-2")
        return GradeResult(
            task_id=request.task_id,
            resolved=resolved,
            exit_code=0,
            stdout="credential-free fixture\n",
            stderr="",
            report={"task_id": request.task_id, "resolved": resolved},
            grader_id="d19-local-terminal-fixture",
            container_digest="fixture@sha256:" + "a" * 64,
            official=True,
            wall_time_ms=0,
            container_started=True,
        )


class _FirstCellContextPreflightGateway:
    """Reject cell 1 locally, then serve cell 2 without network access."""

    def __init__(self) -> None:
        self.replay = ReplayModelGateway(self._response)
        self.preflight_failures: list[str] = []

    def preview_reservation(self, request: GatewayRequest):
        if request.task_id.endswith("cell-1") and request.call_kind == "decompose":
            self.preflight_failures.append(request.logical_call_id)
            raise ModelPreflightFailure(
                "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
                request_sha256=gateway_request_sha256(request),
                logical_call_id=request.logical_call_id,
            )
        return None

    @staticmethod
    def _response(request: GatewayRequest) -> str:
        if request.call_kind == "decompose":
            return json.dumps({
                "subtasks": [{
                    "id": "finish-cell",
                    "objective": "finish the credential-free fixture",
                    "predicted_operation": "complete the active subtask",
                    "depends_on": [],
                }]
            })
        if request.call_kind == "extract":
            return json.dumps({
                "episode": {
                    "summary": "The cell reached a terminal grader result.",
                    "action": "Used the credential-free fixture.",
                    "outcome": "passed" if request.task_id.endswith("cell-2") else "failed",
                },
                "semantic_candidate": None,
            })
        return json.dumps({
            "tool": "complete_subtask",
            "arguments": {"evidence": "fixture subtask complete"},
        })

    def invoke(self, request: GatewayRequest) -> GatewayResponse:
        return self.replay.invoke(request)


def _continuation_task(task_id: str) -> CodingTask:
    return CodingTask(
        task_id=task_id,
        org_id="org",
        user_id="fixture",
        repository="example/repo",
        commit="f" * 40,
        instruction="Reach a terminal cell without external side effects.",
        files={"value.py": "VALUE = 1\n"},
        editable_paths=("value.py",),
    )


def test_one_context_overflow_cell_is_terminal_and_does_not_stop_cell_two(tmp_path):
    gateway = _FirstCellContextPreflightGateway()
    grader = _LocalTerminalGrader()
    results = []
    for index in (1, 2):
        root = tmp_path / f"cell-{index}"
        runtime = TriMemAgentRuntime(
            runtime_lock=RuntimeLock(),
            model_gateway=gateway,
            grader_gateway=grader,
            memory_controller=NoMemoryController(),
            evidence=RawEvidenceLedger(root / "evidence"),
            checkpoint_store=FileCheckpointStore(root / "checkpoints"),
        )
        results.append(runtime.run(_continuation_task(f"d19-cell-{index}"), arm="M0"))

    assert results[0].cell_status == "CELL_SCIENTIFIC_FAILURE"
    assert results[0].model_failure_class == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    assert results[0].grader_patch_source == "CANONICAL_FAILED_CELL_NOOP"
    assert results[0].patch == CANONICAL_FAILED_CELL_NOOP
    assert results[0].resolved is False
    assert results[0].accounting["summary"]["by_call_kind"].get(
        "decompose", {"calls": 0}
    )["calls"] == 0
    assert results[1].cell_status == "AGENT_COMPLETED"
    assert results[1].resolved is True
    assert grader.task_ids == ["d19-cell-1", "d19-cell-2"]
    assert len(gateway.preflight_failures) == 1
    assert any(
        logical_id.startswith("d19-cell-2:M0:")
        for logical_id in gateway.replay.invocations
    )


def _d19_mixed_semantics(stream: str, sequence_index: int) -> dict:
    if stream == "M2-baseline" and sequence_index == 10:
        return {
            "cell_status": "CELL_SCIENTIFIC_FAILURE",
            "model_failure_class": "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED",
            "failure_metadata": {
                "stage": "PREFLIGHT",
                "call_kind": "decompose",
                "provider_request_started": False,
                "ledger_reservation_created": False,
            },
            "agent_completed": False,
            "grader_patch_source": "CANONICAL_FAILED_CELL_NOOP",
            "extraction_status": "MEMORY_EXTRACTION_FAILED",
        }
    return terminal_fixture._semantics(sequence_index)


def test_mixed_72_cell_aggregate_public_and_terminal_ledger_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifacts = terminal_fixture.run_production_shaped_72_cell_terminal_round_trip(
        monkeypatch,
        tmp_path,
        semantics_factory=_d19_mixed_semantics,
    )

    results_dir = artifacts["results_dir"]
    result_path = results_dir / "M2-baseline" / "10" / "cell.result.json"
    ledger_path = results_dir / "budget-ledger.json"
    assert result_path.is_file()
    assert ledger_path.is_file()
    assert artifacts["aggregate_path"].is_file()
    assert artifacts["public_path"].is_file()

    record = json.loads(result_path.read_text(encoding="utf-8"))
    assert record["execution_status"] == SCIENTIFIC_EXECUTION_STATUS
    assert record["cell_status"] == "CELL_SCIENTIFIC_FAILURE"
    assert record["model_failure_class"] == "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    assert record["failure_metadata"] == {
        "stage": "PREFLIGHT",
        "call_kind": "decompose",
        "provider_request_started": False,
        "ledger_reservation_created": False,
    }
    assert record["grader_patch_source"] == "CANONICAL_FAILED_CELL_NOOP"
    assert record["extraction_status"] == "MEMORY_EXTRACTION_FAILED"
    assert record["official_grader"] is True
    assert record["actual_accounting"]["model_gateway_calls"] == 0
    assert record["actual_accounting"]["paid_model_calls"] == 0
    assert record["actual_accounting"]["input_tokens"] == 0
    assert record["actual_accounting"]["output_tokens"] == 0
    assert record["provider_outcomes"]["provider_reported_usage"]["available_calls"] == 0
    assert record["provider_outcomes"]["ledger_reservation"]["calls"] == 0

    task_arm_key = f"M2-baseline:M2:{record['target_id']}"
    ledger_state = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_row = ledger_state["task_arms"][task_arm_key]
    assert ledger_row["status"] == SCIENTIFIC_LEDGER_TERMINAL_STATUS
    assert ledger_row["actual_model_calls"] == 0
    assert ledger_row["actual_input_tokens"] == 0
    assert ledger_row["actual_output_tokens"] == 0
    assert ledger_row["container_started"] is True
    assert all(value == 0 for value in ledger_state["outstanding"].values())

    aggregate = artifacts["aggregate"]
    public = artifacts["public"]
    assert aggregate["status"] == "PASS"
    assert aggregate["expected_task_arm_count"] == 72
    assert aggregate["observed_task_arm_count"] == 72
    assert aggregate["scientific_terminal_summary"]["terminal_result_count"] == 72
    assert aggregate["scientific_terminal_summary"]["model_failure_class_counts"][
        "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    ] == 1
    assert public["status"] == "PASS"
    assert len(public["outcomes"]) == 72
    assert public["scientific_terminal_summary"]["terminal_result_count"] == 72
    assert public["scientific_terminal_summary"]["model_failure_class_counts"][
        "TASK_INPUT_CONTEXT_BUDGET_EXCEEDED"
    ] == 1


def _git_blob(commit: str, path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return completed.stdout


def test_historical_001_through_009_requests_and_execution_artifacts_are_immutable():
    completed = subprocess.run(
        [
            "git", "ls-tree", "-r", "--name-only",
            development_trigger.PREVIOUS_EXECUTION_HEAD,
            "--", "artifacts/trimem_v1/exec_requests",
            "artifacts/trimem_v1/development_tuning_exec", "reports",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        text=True,
        encoding="utf-8",
    )
    tracked = completed.stdout.splitlines()
    requests = [
        path for path in tracked
        if re.fullmatch(
            r"artifacts/trimem_v1/exec_requests/"
            r"DEVELOPMENT_TUNING_EXEC_REQUEST_00[1-9]\.json",
            path,
        )
    ]
    execution_artifacts = [
        path for path in tracked
        if re.match(
            r"artifacts/trimem_v1/development_tuning_exec/exec-00[1-9]/",
            path,
        )
        or re.match(
            r"reports/TRIMEM_DEVELOPMENT_TUNING_EXEC_00[1-9]",
            path,
        )
    ]
    assert len(requests) == 9
    assert execution_artifacts
    for path in sorted(requests + execution_artifacts):
        assert _git_blob("HEAD", path) == _git_blob(
            development_trigger.PREVIOUS_EXECUTION_HEAD, path
        ), path
