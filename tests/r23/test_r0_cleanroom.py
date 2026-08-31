"""Credential-free tests for the R23-R0 coarse author-method reproduction."""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from experiments.r23 import author_method
from experiments.r23 import r0_runtime
from experiments.r23.author_method import (
    ARMS,
    CATEGORIES,
    PROMPT_HASHES,
    TRANSITIONS,
    CategoryMachine,
    MemoryEntry,
    StreamingState,
    SubtaskIntent,
    TaskInput,
    TrajectoryEvent,
    content_hash,
    parse_extracted_memory,
)
from experiments.r23.r0_runtime import (
    BudgetContract,
    BudgetExceeded,
    BudgetLedger,
    FakeReader,
    IncompleteCallEvidence,
    R0Runner,
    ReplayReader,
    budget_contract_matrix,
)

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "artifacts" / "r23"


def _json(name: str) -> dict:
    return json.loads((ART / name).read_text(encoding="utf-8"))


def _tasks() -> list[TaskInput]:
    return [
        TaskInput("repo__one", "example/repo", "Parser mishandles a repeated option."),
        TaskInput("repo__two", "example/repo", "Parser mishandles another repeated option."),
    ]


def _task_results(output: Path, arm: str) -> list[dict]:
    paths = sorted((output / "streams" / "order0" / arm / "tasks").glob("*/result.json"))
    return [json.loads(path.read_text(encoding="utf-8")) for path in paths]


def test_miniswe_scaffold_is_fully_frozen_not_todo():
    lock = _json("agent_scaffold_lock.json")
    assert lock["commit"] == "25941c89cfbc91eb40b3f8756348c91d9977d57e"
    assert lock["default_step_cap"] == 250
    assert lock["config_sha256"] == "0389e74fe7d730e384b82bbdabf5d58c307299e676f0c6453b9946116708033d"
    assert lock["system_prompt_sha256"] == "06f6dd6ea8671220762ff4a4916bd0aeb4fb2adfb084469a803e2fa841018efe"
    assert lock["instance_prompt_sha256"] == "8826e3fbabc7733ad4d118654bbd392c2a4e0f1931d55f9c62235d33bd494196"
    assert lock["tool_schema_canonical_sha256"] == "fa3f9e719935ffb5dbdccb5f58ed0a413553c7ceb651f8a6afd0ac8f01783cc4"
    assert lock["tool_call_parser_source_sha256"] == "14236747cf9a60fe129ca6579915756c7743000201b60ec9ecdca6afcfb7d502"
    assert lock["patch_parser_source_sha256"] == "b47cd7bf6a7c67342ed2567597e5b520d60c0ef6e01ff65b4833ecbb1ca931d3"
    assert "to_pin_in_R0" not in lock
    assert lock["verification"] == {
        "script": "scripts/r23_r0_verify_scaffold.py",
        "network_required": False,
        "model_calls": 0,
        "docker_calls": 0,
    }


def test_cleanroom_prompt_payload_and_transition_hashes_match_code():
    lock = _json("r0_cleanroom_lock.json")
    assert lock["clean_room_prompt_hashes"] == PROMPT_HASHES
    assert lock["payload_and_transition_hashes"]["arms_canonical_sha256"] == content_hash(ARMS)
    assert lock["payload_and_transition_hashes"]["transitions_canonical_sha256"] == content_hash(TRANSITIONS)
    source_hashes = {
        "solve_payload_builder_source_sha256": hashlib.sha256(
            inspect.getsource(author_method.build_solve_payload).encode()
        ).hexdigest(),
        "extraction_payload_builder_source_sha256": hashlib.sha256(
            inspect.getsource(author_method.build_extraction_payload).encode()
        ).hexdigest(),
        "extraction_parser_source_sha256": hashlib.sha256(
            inspect.getsource(author_method.parse_extracted_memory).encode()
        ).hexdigest(),
    }
    for key, value in source_hashes.items():
        assert lock["payload_and_transition_hashes"][key] == value
    assert lock["retrieval_encoder"]["credential_free_test_encoder_source_sha256"] == hashlib.sha256(
        inspect.getsource(r0_runtime.deterministic_fake_embed).encode()
    ).hexdigest()
    assert lock["accounting"]["token_preflight_estimator_source_sha256"] == hashlib.sha256(
        inspect.getsource(r0_runtime.estimate_tokens).encode()
    ).hexdigest()


def test_all_arms_have_same_solver_and_common_total_hard_envelope():
    lock = _json("r0_budget_lock.json")
    matrix = budget_contract_matrix()
    assert set(matrix) == set(ARMS) == {"AR0", "AR1", "AR2", "AR3", "AR4", "AR5"}
    assert {row["scaffold_step_cap"] for row in matrix.values()} == {250}
    assert {row["solver_calls_hard_cap"] for row in matrix.values()} == {250}
    assert {row["total_calls_hard_cap"] for row in matrix.values()} == {254}
    assert {row["common_total_input_tokens_hard_cap"] for row in matrix.values()} == {1_064_000}
    assert {row["common_total_output_tokens_hard_cap"] for row in matrix.values()} == {108_192}
    assert [matrix[arm]["extraction_calls_hard_cap"] for arm in ARMS] == [0, 0, 1, 4, 4, 4]
    for arm, contract in matrix.items():
        arm_lock = lock["arms"][arm]
        assert arm_lock["contract_sha256"] == BudgetContract.for_arm(arm).contract_sha256
        assert arm_lock["solver_calls_hard_cap"] == contract["solver_calls_hard_cap"]
        assert arm_lock["extraction_calls_hard_cap"] == contract["extraction_calls_hard_cap"]
        assert arm_lock["total_calls_hard_cap"] == contract["total_calls_hard_cap"]
        assert arm_lock["total_input_tokens_hard_cap"] == contract["common_total_input_tokens_hard_cap"]
        assert arm_lock["total_output_tokens_hard_cap"] == contract["common_total_output_tokens_hard_cap"]
        assert arm_lock["solver_input_tokens_hard_cap"] == contract["solver_input_tokens_hard_cap"]
        assert arm_lock["solver_output_tokens_hard_cap"] == contract["solver_output_tokens_hard_cap"]
        assert arm_lock["extraction_input_tokens_hard_cap"] == contract["extraction_input_tokens_hard_cap"]
        assert arm_lock["extraction_output_tokens_hard_cap"] == contract["extraction_output_tokens_hard_cap"]
    assert "cannot be converted" in lock["equality_proof"]["explanation"]


def test_budget_fails_before_disallowed_extraction_call():
    ledger = BudgetLedger(BudgetContract.for_arm("AR0"))
    with pytest.raises(BudgetExceeded, match="extraction call cap"):
        ledger.preflight("extract", {"generation": {"max_output_tokens": 1}})
    assert ledger.total_calls == 0


def test_category_machine_is_explicit_and_fail_closed():
    machine = CategoryMachine()
    assert machine.current == "ANALYZE"
    for signal, expected in [
        ("ANALYSIS_COMPLETE", "REPRODUCE"),
        ("REPRODUCTION_COMPLETE", "EDIT"),
        ("EDIT_COMPLETE", "VERIFY"),
        ("VERIFICATION_PASSED", "COMPLETE"),
    ]:
        assert machine.apply(signal) == expected
    assert machine.finished
    with pytest.raises(ValueError, match="already complete"):
        machine.apply("CONTINUE")
    with pytest.raises(ValueError, match="invalid transition"):
        CategoryMachine().apply("EDIT_COMPLETE")


def test_success_failure_extraction_and_raw_ablation_are_coarse_only():
    task = _tasks()[0]
    intent = SubtaskIntent("VERIFY", "verify change", ("parser",))
    success_event = TrajectoryEvent(
        "VERIFY", "checks pass", ({"command": "pytest"},), "VERIFICATION_PASSED", "SUCCESS", True, True
    )
    failure_event = TrajectoryEvent(
        "VERIFY", "checks fail", ({"command": "pytest"},), "VERIFICATION_FAILED", "FAILURE", True, True
    )
    success = parse_extracted_memory(
        arm="AR3",
        task=task,
        intent=intent,
        events=[success_event],
        local_outcome="SUCCESS",
        extracted={"evaluation": "SUCCESS", "experience": "Re-run the narrow parser checks."},
        injection_token_cap=100,
    )
    failure = parse_extracted_memory(
        arm="AR3",
        task=task,
        intent=intent,
        events=[failure_event],
        local_outcome="FAILURE",
        extracted={"evaluation": "FAILURE", "experience": "Avoid assuming all parser cases pass."},
        injection_token_cap=100,
    )
    raw = parse_extracted_memory(
        arm="AR5",
        task=task,
        intent=intent,
        events=[failure_event],
        local_outcome="FAILURE",
        extracted={"evaluation": "FAILURE", "experience": "this abstraction is intentionally discarded"},
        injection_token_cap=100,
    )
    assert success.kind == "success" and failure.kind == raw.kind == "failure"
    assert "this abstraction" not in raw.e
    for entry in (success, failure, raw):
        assert set(asdict(entry)) == {"z", "d", "e", "source_task_id", "kind"}
    with pytest.raises(ValueError, match="exactly evaluation and experience"):
        parse_extracted_memory(
            arm="AR3",
            task=task,
            intent=intent,
            events=[success_event],
            local_outcome="SUCCESS",
            extracted={"evaluation": "SUCCESS", "experience": "x", "atom_id": "forbidden"},
            injection_token_cap=100,
        )


def test_streaming_state_buffers_and_never_exposes_self_memory():
    entry = MemoryEntry(
        z="ANALYZE",
        d={"objective": "inspect", "keywords": ["parser"]},
        e="inspect the option normalization path",
        source_task_id="repo__one",
    )
    state = StreamingState()
    assert state.visible_for("repo__one") == []
    # Not visible merely because extraction finished; commit is the target-completion boundary.
    assert entry not in state.store
    state.commit("repo__one", [entry])
    assert state.visible_for("repo__one") == []
    assert state.visible_for("repo__two") == [entry]
    with pytest.raises(ValueError, match="already committed"):
        state.commit("repo__one", [entry])


def test_fake_reader_e2e_all_ar0_ar5_payloads_and_call_counts(tmp_path):
    expected = {
        "AR0": (2, 0, 0),
        "AR1": (8, 0, 0),
        "AR2": (2, 2, 2),
        "AR3": (8, 8, 8),
        "AR4": (8, 8, 8),
        "AR5": (8, 8, 8),
    }
    for arm, (solve_calls, extraction_calls, memory_entries) in expected.items():
        reader = FakeReader()
        summary = R0Runner(output_root=tmp_path, reader=reader).run_stream(
            arm=arm, order_id="order0", tasks=_tasks()
        )
        assert summary["complete"] is True
        assert summary["solver_call_slots_accounted"] == solve_calls
        assert summary["extraction_call_slots_accounted"] == extraction_calls
        assert summary["total_call_slots_accounted"] == solve_calls + extraction_calls
        assert summary["memory_entries"] == memory_entries
        assert summary["external_model_calls_now"] == summary["paid_model_calls_now"] == 0
        assert summary["reader_calls_executed_now"] == solve_calls + extraction_calls
        results = _task_results(tmp_path, arm)
        assert results[0]["visible_source_task_ids"] == []
        expected_visible = ["repo__one"] if ARMS[arm]["memory"] else []
        assert results[1]["visible_source_task_ids"] == expected_visible
        assert all(result["self_memory_seen"] is False for result in results)
        if ARMS[arm]["memory"]:
            assert set(results[1]["retrieved_source_task_ids"]) == {"repo__one"}
        for result in results:
            blob = json.dumps(result).lower()
            for key in ("atom_id", "graph_hash", "predecessor_atom_ids"):
                assert key not in blob
            task_root = next(
                path.parent for path in (tmp_path / "streams" / "order0" / arm / "tasks").glob("*/result.json")
                if json.loads(path.read_text())["task_id"] == result["task_id"]
            )
            assert len((task_root / "raw_evidence" / "requests.jsonl").read_text().splitlines()) == result["budget"][
                "total_calls"
            ]
            assert len((task_root / "raw_evidence" / "responses.jsonl").read_text().splitlines()) == result["budget"][
                "total_calls"
            ]


def test_failure_experience_is_extracted_and_committed_after_task(tmp_path):
    task = _tasks()[0]
    summary = R0Runner(output_root=tmp_path, reader=FakeReader([task.task_id])).run_stream(
        arm="AR3", order_id="order0", tasks=[task]
    )
    result = _task_results(tmp_path, "AR3")[0]
    assert result["outcome"] == "FAILURE"
    assert result["budget"]["solver_calls"] == 4
    assert result["budget"]["extraction_calls"] == 4
    assert [entry["kind"] for entry in result["buffered_memory_entries"]] == [
        "success",
        "success",
        "success",
        "failure",
    ]
    assert summary["memory_entries"] == 4


def test_task_checkpoint_resume_skips_completed_prefix(tmp_path):
    first_reader = FakeReader()
    partial = R0Runner(output_root=tmp_path, reader=first_reader).run_stream(
        arm="AR3", order_id="order0", tasks=_tasks(), stop_after_tasks=1
    )
    assert partial["complete"] is False and partial["completed_tasks"] == 1
    assert len(first_reader.invocations) == 8

    second_reader = FakeReader()
    resumed = R0Runner(output_root=tmp_path, reader=second_reader).run_stream(
        arm="AR3", order_id="order0", tasks=_tasks()
    )
    assert resumed["complete"] is True and resumed["completed_tasks"] == 2
    assert len(second_reader.invocations) == 8
    assert resumed["reader_calls_executed_now"] == 8
    assert resumed["total_call_slots_accounted"] == 16
    assert _task_results(tmp_path, "AR3")[1]["visible_source_task_ids"] == ["repo__one"]


def test_call_journal_replays_durable_pairs_without_reader_call(tmp_path):
    task = _tasks()[0]
    task_root = tmp_path / "direct_task"
    first_reader = FakeReader()
    first = R0Runner(output_root=tmp_path, reader=first_reader)._run_task(
        arm="AR3", task=task, state=StreamingState(), task_root=task_root
    )
    assert first.result["invocation_accounting"]["executed_calls_now"] == 8

    second_reader = FakeReader()
    second = R0Runner(output_root=tmp_path, reader=second_reader)._run_task(
        arm="AR3", task=task, state=StreamingState(), task_root=task_root
    )
    assert second_reader.invocations == []
    assert second.result["invocation_accounting"]["executed_calls_now"] == 0
    assert second.result["invocation_accounting"]["replayed_calls"] == 8


def test_replay_reader_e2e_uses_same_payload_hashes_and_zero_external_calls(tmp_path):
    task = _tasks()[0]
    source = tmp_path / "source"
    R0Runner(output_root=source, reader=FakeReader()).run_stream(arm="AR2", order_id="order0", tasks=[task])
    response_path = next((source / "streams" / "order0" / "AR2" / "tasks").glob("*/raw_evidence/responses.jsonl"))
    records = [json.loads(line) for line in response_path.read_text().splitlines()]

    replay = ReplayReader(records)
    target = tmp_path / "target"
    summary = R0Runner(output_root=target, reader=replay).run_stream(arm="AR2", order_id="order0", tasks=[task])
    assert replay.remaining == 0
    assert summary["solver_call_slots_accounted"] == 1
    assert summary["extraction_call_slots_accounted"] == 1
    assert summary["external_model_calls_now"] == summary["paid_model_calls_now"] == 0


def test_orphan_request_fails_closed_instead_of_repeating_reader(tmp_path):
    class ExplodingReader:
        mode = "fake"

        def __init__(self):
            self.calls = 0

        def __call__(self, call_kind, payload):
            self.calls += 1
            raise RuntimeError("simulated interruption after durable request")

    task = _tasks()[0]
    task_root = tmp_path / "orphan"
    first_reader = ExplodingReader()
    with pytest.raises(RuntimeError, match="simulated interruption"):
        R0Runner(output_root=tmp_path, reader=first_reader)._run_task(
            arm="AR0", task=task, state=StreamingState(), task_root=task_root
        )
    assert first_reader.calls == 1

    second_reader = FakeReader()
    with pytest.raises(IncompleteCallEvidence, match="fail closed"):
        R0Runner(output_root=tmp_path, reader=second_reader)._run_task(
            arm="AR0", task=task, state=StreamingState(), task_root=task_root
        )
    assert second_reader.invocations == []


def test_task_input_rejects_answer_and_unknown_fields():
    with pytest.raises(ValueError, match="prohibited answer fields"):
        TaskInput.from_mapping(
            {
                "instance_id": "x",
                "repo": "a/b",
                "problem_statement": "issue",
                "gold_patch": "secret",
            }
        )
    with pytest.raises(ValueError, match="unsupported fields"):
        TaskInput.from_mapping(
            {"instance_id": "x", "repo": "a/b", "problem_statement": "issue", "extra": "field"}
        )


def test_r0_module_does_not_import_proposed_method_schema():
    source = inspect.getsource(author_method)
    assert "from experiments.r23.schema" not in source
    assert "from .schema" not in source
    lock = _json("r0_cleanroom_lock.json")
    assert lock["separation_boundary"]["proposed_method_imported_by_R0"] is False
    assert lock["separation_boundary"]["reproduction_and_proposed_method_may_share_a_sample_mean"] is False


def test_tracked_credential_free_e2e_bundle_is_self_consistent_and_reproducible():
    path = ART / "r0_credential_free_e2e_bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    digest = bundle.pop("bundle_content_sha256")
    assert content_hash(bundle) == digest == "26ab8979a692d476254c0f931e04d6905eec09ec904cb953aa767f3d4750488b"
    assert bundle["status"] == "PASS_CREDENTIAL_FREE_PATH_ONLY"
    assert bundle["calls_now"] == {
        "external_model": 0,
        "paid_model": 0,
        "docker": 0,
        "grader_container": 0,
    }
    expected = {
        "AR0": (2, 0),
        "AR1": (8, 0),
        "AR2": (2, 2),
        "AR3": (8, 8),
        "AR4": (8, 8),
        "AR5": (8, 8),
    }
    for arm, (solve, extract) in expected.items():
        row = bundle["fake_all_arms"][arm]
        assert (row["solver_call_slots_accounted"], row["extraction_call_slots_accounted"]) == (solve, extract)
        assert row["external_model_calls_now"] == row["paid_model_calls_now"] == 0
    assert bundle["checkpoint_resume"]["partial_completed_tasks"] == 1
    assert bundle["checkpoint_resume"]["resumed_completed_tasks"] == 2
    assert bundle["checkpoint_resume"]["calls_executed_during_resume"] == 8
    assert bundle["replay"]["records_consumed"] == 4
    assert bundle["replay"]["records_remaining"] == 0
    for sample_name, sample in bundle["raw_evidence_samples"].items():
        index = bundle["hash_index"][sample_name]
        assert content_hash(sample["checkpoint"]) == index["checkpoint_sha256"]
        assert content_hash(sample["summary"]) == index["summary_sha256"]
        for task in sample["tasks"]:
            task_index = index["tasks"][task["result"]["task_id"]]
            assert content_hash(task["result"]) == task_index["result_sha256"]
            assert content_hash(task["requests"]) == task_index["requests_sha256"]
            assert content_hash(task["responses"]) == task_index["responses_sha256"]
            assert len(task["requests"]) == len(task["responses"]) > 0
    completed = subprocess.run(
        [sys.executable, "scripts/r23_r0_build_e2e_evidence.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
