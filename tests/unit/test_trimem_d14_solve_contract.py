import hashlib
import importlib.util
import json
from decimal import Decimal
from pathlib import Path
import subprocess

import pytest

from enterprise_memory.trimem.accounting import CallRecord, RunAccounting
from enterprise_memory.trimem.agent_runtime import RuntimeFailure, solve_output_request_cap
from enterprise_memory.trimem.gateway import parse_tool_action
from enterprise_memory.trimem.git_workspace import GitCheckoutWorkspace
from enterprise_memory.trimem.runtime_lock import RuntimeLock
from enterprise_memory.trimem.solve_forensics import classify_incomplete_action
from enterprise_memory.trimem.workspace import InMemoryRepositoryWorkspace, ToolExecutionError


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "trimem_benchmark_run_d14_test", ROOT / "scripts" / "trimem_benchmark_run.py"
)
assert SPEC is not None and SPEC.loader is not None
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


def _caps():
    return {
        "task_arm_runs": 72,
        "benchmark_grader_containers": 72,
        "model_calls": 1872,
        "paid_model_calls": 1872,
        "solve_calls": 1728,
        "decomposition_calls": 72,
        "extraction_calls": 72,
        "input_tokens": 36_000_000,
        "output_tokens": 4_718_592,
        "total_usd": 50.0,
        "max_input_tokens_per_task_arm": 500_000,
        "max_model_calls_per_task_arm": 26,
        "uncached_token_cost_ceiling_usd": 48.233664,
    }


def _ledger(tmp_path):
    return BENCHMARK.AtomicBudgetLedger(
        tmp_path / "ledger.json",
        approval_digest="a" * 64,
        caps=_caps(),
        pricing={
            "input_per_million_tokens_usd": 0.75,
            "cached_input_per_million_tokens_usd": 0.075,
            "output_per_million_tokens_usd": 4.5,
        },
    )


def _call(index: int, output_tokens: int) -> CallRecord:
    return CallRecord(
        task_id="task", arm="M0", step_no=index, call_kind="solve",
        logical_call_id=f"task:M0:solve:{index:04d}", provider="fixture",
        model="fixture", input_tokens=1, output_tokens=output_tokens,
        cached_input_tokens=0, reasoning_tokens=0, wall_time_ms=0,
        prompt_hash="a" * 64, response_hash="b" * 64,
        active_node_id="s1", paid=False,
    )


def test_exact_sanitized_incomplete_fixture_is_class_a_and_never_executed():
    prefix = '{"tool":"write_file","arguments":{"path":"django/contrib/admin/options.py","content":"'
    visible = prefix + "x" * (8271 - len(prefix.encode("utf-8")))
    fixture = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "usage": {"output_tokens": 2048, "output_tokens_details": {"reasoning_tokens": 212}},
        "output": [
            {"type": "reasoning"},
            {"type": "message", "content": [{"type": "output_text", "text": visible}]},
        ],
    }
    assert len(visible.encode("utf-8")) == 8271
    assert fixture["usage"]["output_tokens_details"]["reasoning_tokens"] == 212
    result = classify_incomplete_action(visible, frozen_tools={"write_file", "read_file"})
    assert result["classification"] == "SOLVE_TRUNCATED_WRITE_FILE_CONTENT"
    assert result["open_argument"] == "content"
    assert "content" not in result and "x" * 32 not in json.dumps(result)
    workspace = InMemoryRepositoryWorkspace(
        {"django/contrib/admin/options.py": "ORIGINAL\n"},
        editable_paths=("django/contrib/admin/options.py",),
    )
    with pytest.raises(ValueError, match="invalid strict JSON"):
        parse_tool_action(visible, set(workspace.tool_names))
    assert workspace.files["django/contrib/admin/options.py"] == "ORIGINAL\n"


@pytest.mark.parametrize(
    ("visible", "classification"),
    [
        ('{"tool":"read_file","arguments":{"path":"src/unfinished', "SOLVE_TRUNCATED_OTHER_TOOL_ARGUMENT"),
        ("I cannot complete this edit in one action", "SOLVE_TRUNCATED_NON_ACTION_TEXT"),
    ],
)
def test_structural_forensic_distinguishes_b_and_c_without_plaintext_return(visible, classification):
    result = classify_incomplete_action(visible, frozen_tools={"write_file", "read_file"})
    assert result["classification"] == classification
    assert visible not in json.dumps(result)


def test_d14_frozen_forensic_rejects_reasoning_exhaustion_label():
    artifact = json.loads((
        ROOT / "artifacts/trimem_v1/development_tuning_exec/exec-004/solve-0005-output-shape-forensics.json"
    ).read_text(encoding="utf-8"))
    assert artifact["provider_terminal"] == {
        "api_terminal_cause": "RESPONSE_INCOMPLETE_MAX_OUTPUT_TOKENS",
        "content_item_types": ["output_text"],
        "incomplete_reason": "max_output_tokens",
        "output_item_types": ["reasoning", "message"],
        "output_tokens": 2048,
        "reasoning_exhaustion_primary_explanation": "REJECTED",
        "reasoning_tokens": 212,
        "response_status": "incomplete",
    }


def test_solve_request_cap_and_serial_small_calls_use_task_pool_not_cap_times_calls():
    lock = RuntimeLock()
    accounting = RunAccounting()
    assert solve_output_request_cap(accounting, lock) == 16_384
    for index in range(1, 25):
        accounting.add_call(_call(index, 1))
        assert solve_output_request_cap(accounting, lock) == 16_384
    assert len(accounting.calls) == lock.limits.max_solve_calls == 24


def test_three_full_solve_calls_exhaust_pool_and_next_rejects_before_provider():
    accounting = RunAccounting()
    for index in range(1, 4):
        accounting.add_call(_call(index, 16_384))
    with pytest.raises(RuntimeFailure, match="TASK_SOLVE_OUTPUT_POOL_EXHAUSTED"):
        solve_output_request_cap(accounting, RuntimeLock())


def test_runtime_and_phase_output_caps_and_uncached_envelope_are_exact():
    limits = RuntimeLock().limits
    assert (
        limits.max_output_tokens_decomposition,
        limits.max_total_solve_output_tokens_per_task_arm,
        limits.max_output_tokens_extraction,
        limits.max_total_output_tokens_per_task_arm,
    ) == (8192, 49152, 8192, 65536)
    assert 72 * limits.max_total_output_tokens_per_task_arm == 4_718_592
    cost = (
        Decimal(36_000_000) * Decimal("0.75")
        + Decimal(4_718_592) * Decimal("4.5")
    ) / Decimal(1_000_000)
    assert cost == Decimal("48.233664")


def test_every_frozen_m2_candidate_has_identical_limits_and_edit_tool_schema():
    reference = RuntimeLock().to_manifest()
    bundle = json.loads((
        ROOT / "configs/trimem_v1/m2_candidate_bundles.json"
    ).read_text(encoding="utf-8"))
    assert len(bundle["candidates"]) == 4
    for candidate in bundle["candidates"]:
        manifest = candidate["runtime_lock_manifest"]
        assert manifest["limits"] == reference["limits"]
        assert manifest["tool_hash"] == reference["tool_hash"]
        assert manifest["parser_hash"] == reference["parser_hash"]
        assert manifest["prompt_hashes"]["solve_prompt"] == reference["prompt_hashes"]["solve_prompt"]
        assert manifest["prompt_hashes"]["extraction_prompt"] == reference["prompt_hashes"]["extraction_prompt"]


def test_per_task_public_accounting_exposes_role_pool_and_edit_tool_counts():
    accounting = RunAccounting()
    accounting.add_call(_call(1, 321))
    value = accounting.to_dict()
    value["tools"] = [
        {"tool_name": "replace_text"},
        {"tool_name": "write_file"},
    ]
    projection = BENCHMARK.actual_accounting(value)
    assert projection["actual_solve_output_tokens"] == 321
    assert projection["solve_output_pool_capacity"] == 49_152
    assert projection["remaining_solve_output_tokens"] == 49_152 - 321
    assert projection["replace_text_calls"] == 1
    assert projection["write_file_calls"] == 1


def test_atomic_ledger_tracks_task_role_reservation_without_double_count(tmp_path):
    ledger = _ledger(tmp_path)
    key = "M2-baseline:M2:task"
    ledger.reserve_task_arm(key)
    reservation = ledger.reserve(
        "solve-1", task_arm_key=key, call_kind="solve",
        input_upper_bound=10, output_cap=16_384,
    )
    state = BENCHMARK.read_json(ledger.path)
    task = state["task_arms"][key]
    assert state["outstanding"]["output_tokens"] == 16_384
    assert task["outstanding_output_tokens"] == 16_384
    assert task["remaining_solve_output_tokens"] == 32_768
    assert state["actual"]["output_tokens"] == task["actual_output_tokens"] == 0
    ledger.reconcile(
        "solve-1", reservation, input_tokens=7, cached_input_tokens=2,
        output_tokens=123, status="SUCCESS",
    )
    state = BENCHMARK.read_json(ledger.path)
    task = state["task_arms"][key]
    assert state["outstanding"]["output_tokens"] == task["outstanding_output_tokens"] == 0
    assert task["actual_output_tokens"] == task["actual_solve_output_tokens"] == 123
    assert task["remaining_solve_output_tokens"] == 49_152 - 123
    with pytest.raises(BENCHMARK.BenchmarkExecutionError, match="already reconciled"):
        ledger.reconcile(
            "solve-1", reservation, input_tokens=7, cached_input_tokens=2,
            output_tokens=123, status="SUCCESS",
        )


def test_atomic_ledger_three_full_solves_exhaust_role_pool(tmp_path):
    ledger = _ledger(tmp_path)
    key = "M2-baseline:M2:task"
    ledger.reserve_task_arm(key)
    for index in range(3):
        logical = f"solve-{index}"
        reservation = ledger.reserve(
            logical, task_arm_key=key, call_kind="solve",
            input_upper_bound=10, output_cap=16_384,
        )
        ledger.reconcile(
            logical, reservation, input_tokens=10, cached_input_tokens=0,
            output_tokens=16_384, status="SUCCESS",
        )
    before = ledger.path.read_bytes()
    with pytest.raises(BENCHMARK.BenchmarkExecutionError, match="task-arm role output pool"):
        ledger.reserve(
            "solve-four", task_arm_key=key, call_kind="solve",
            input_upper_bound=10, output_cap=1,
        )
    assert ledger.path.read_bytes() == before


def test_atomic_ledger_allows_twenty_four_serial_tiny_solve_calls(tmp_path):
    ledger = _ledger(tmp_path)
    key = "M2-baseline:M2:task"
    ledger.reserve_task_arm(key)
    for index in range(24):
        logical = f"tiny-{index}"
        reservation = ledger.reserve(
            logical, task_arm_key=key, call_kind="solve",
            input_upper_bound=10, output_cap=16_384,
        )
        ledger.reconcile(
            logical, reservation, input_tokens=1, cached_input_tokens=0,
            output_tokens=1, status="SUCCESS",
        )
    task = BENCHMARK.read_json(ledger.path)["task_arms"][key]
    assert task["actual_model_calls"] == 24
    assert task["actual_solve_output_tokens"] == 24


def _git_repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
    (root / "value.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "fixture"], check=True)
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout.strip()
    return root, commit


def test_replace_text_success_read_metadata_and_workspace_equivalence(tmp_path):
    original = "alpha\nbeta\ngamma\n"
    digest = hashlib.sha256(original.encode()).hexdigest()
    arguments = {
        "path": "value.txt", "expected_file_sha256": digest,
        "old_text": "beta", "new_text": "delta",
    }
    memory = InMemoryRepositoryWorkspace({"value.txt": original}, editable_paths=("value.txt",))
    memory_result = memory.execute("replace_text", dict(arguments))
    root, commit = _git_repository(tmp_path)
    checkout = GitCheckoutWorkspace(root, base_commit=commit)
    git_result = checkout.execute("replace_text", dict(arguments))
    assert git_result == memory_result
    assert (root / "value.txt").read_text(encoding="utf-8") == memory.files["value.txt"]
    window = checkout.execute("read_file", {"path": "value.txt", "start_line": 2, "max_lines": 1})
    assert window["returned_start_line"] == window["returned_end_line"] == 2
    assert window["total_file_bytes"] == len(memory.files["value.txt"].encode())
    assert window["full_file_sha256"] == git_result["new_sha256"]


def test_replace_text_rejects_stale_occurrence_path_and_oversize():
    workspace = InMemoryRepositoryWorkspace(
        {"value.txt": "same same", "large.txt": "x" * 20_000},
        editable_paths=("value.txt", "large.txt"),
    )
    with pytest.raises(ToolExecutionError, match="stale"):
        workspace.execute("replace_text", {
            "path": "value.txt", "expected_file_sha256": "0" * 64,
            "old_text": "same", "new_text": "new",
        })
    digest = hashlib.sha256(b"same same").hexdigest()
    for old in ("", "same"):
        with pytest.raises(ToolExecutionError, match="non-empty|exactly once"):
            workspace.execute("replace_text", {
                "path": "value.txt", "expected_file_sha256": digest,
                "old_text": old, "new_text": "new",
            })
    with pytest.raises(ToolExecutionError, match="path traversal"):
        workspace.execute("replace_text", {
            "path": "../value.txt", "expected_file_sha256": digest,
            "old_text": "same", "new_text": "new",
        })
    with pytest.raises(ToolExecutionError, match="48000"):
        workspace.execute("replace_text", {
            "path": "value.txt", "expected_file_sha256": digest,
            "old_text": "same same", "new_text": "y" * 48_001,
        })
    with pytest.raises(ToolExecutionError, match="FULL_FILE_REWRITE_TOO_LARGE_USE_REPLACE_TEXT"):
        workspace.execute("write_file", {"path": "large.txt", "content": "small"})


def test_checkpoint_restore_preserves_replace_text_content_and_hash():
    original = "alpha beta"
    workspace = InMemoryRepositoryWorkspace({"value.txt": original}, editable_paths=("value.txt",))
    result = workspace.execute("replace_text", {
        "path": "value.txt", "expected_file_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "old_text": "beta", "new_text": "gamma",
    })
    state = workspace.checkpoint_state()
    restored = InMemoryRepositoryWorkspace({"value.txt": original}, editable_paths=("value.txt",))
    restored.restore_checkpoint(state)
    assert restored.files == workspace.files
    assert hashlib.sha256(restored.files["value.txt"].encode()).hexdigest() == result["new_sha256"]
