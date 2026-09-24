"""Training evidence validation and real frozen-controller integration; no model calls."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_skhynix_codex_learning as learning
import trimem_skhynix_codex_memory as bridge
from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.ppr import DeterministicHashEmbedder


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(learning.canonical(value) + b"\n")


def training_run(root, index=1, resolved=True, public_passed=True):
    """Synthetic broker-shaped receipts; tests never masquerade as experiment evidence."""
    cell = root / "cells/A"
    cell.mkdir(parents=True)
    public = {"task_id": f"test-training-{index}", "repository": "sympy/sympy",
              "commit": str(index) * 40, "instruction": "Fix lambdify tuple conversion and code generation"}
    plan = {"experiment_id": "fixture-training", "solver_user_id": f"native-session-{index}",
            "cells": {"A": "NO_MEMORY"}, "public_task": public}
    plan_hash = learning.sha(learning.canonical(plan))
    write(root / "plan.json", plan)
    (root / "plan.sha256").write_text(plan_hash)
    patch = b"PRIVATE_TRAINING_PATCH_CONTENT_NOT_EXPORTED"
    (cell / "submission.diff").write_bytes(patch)
    (cell / "grader-private.json").write_bytes(b"PRIVATE_GRADER_TEST_CONTENT_NOT_EXPORTED")
    digest = learning.sha(patch)
    event = {"sequence": 1, "time": 1000, "previous_sha256": "0" * 64,
        "request": {"op": "tool", "name": "read_file", "arguments": {"path": "sympy/utilities/lambdify.py"}},
        "result": {"ok": True, "result": {"content": "PUBLIC_CODE_NOT_EXPORTED"}}}
    events = []
    for request, result in [
        (event["request"], event["result"]),
        ({"op": "tool", "name": "run_command", "arguments": {
            "argv": ["/opt/python", "bin/test", "sympy/utilities/tests/test_lambdify.py"]}},
         {"ok": True, "result": {"exit_code": 0 if public_passed else 1,
                                   "stdout": "64 passed, 54 skipped" if public_passed else "1 failed"}}),
        ({"op": "submit", "summary": "Fixed lambdify tuple conversion"},
         {"ok": True, "result": {"status": "SUBMITTED", "patch_sha256": digest}}),
    ]:
        event = {"sequence": len(events) + 1, "time": 1000 + len(events), "request": request,
                 "result": result, "previous_sha256": events[-1]["sha256"] if events else "0" * 64}
        events.append({**event, "sha256": learning.sha(learning.canonical(event))})
    (cell / "tool-events.jsonl").write_bytes(b"\n".join(learning.canonical(row) for row in events) + b"\n")
    common = {"plan_sha256": plan_hash, "cell": "A", "arm": "NO_MEMORY", "target_id": public["task_id"],
              "patch_sha256": digest, "patch_utf8_bytes": len(patch), "actions": len(events), "agent_completed": True}
    write(cell / "submission.json", {**common, "submitted_at": 1003,
                                     "summary": "Fixed lambdify tuple conversion"})
    write(cell / "public-result.json", {**common, "official": True, "grader_status": "success",
        "resolved": resolved, "separate_model_api_calls": 0, "tool_event_tail_sha256": events[-1]["sha256"],
        "grader_private_sha256": learning.file_sha(cell / "grader-private.json")})
    write(cell / "state.json", {"actions": len(events), "tail_sha256": events[-1]["sha256"], "status": "SUBMITTED"})
    return {"run_root": str(root), "cell": "A"}


@pytest.fixture
def task():
    return CodingTask("test-evaluation-10", "native-evaluation", "eval-contributor", "sympy/sympy",
                      "a" * 40, "Fix lambdify tuple conversion and code generation", {}, ())


def descriptor(task):
    return {"task_id": task.task_id, "repository": task.repository, "commit": task.commit,
            "instruction_sha256": learning.sha(task.instruction.encode()), "language": "python"}


@pytest.fixture
def bank(tmp_path, task):
    source = training_run(tmp_path / "training")
    path = tmp_path / "bank/bank.json"
    receipt = learning.freeze_learned_bank(path, [source], [descriptor(task)])
    return path, receipt, source


def test_gate_a_keeps_actual_owner_and_verifier_but_exports_no_raw_private_content(bank, task):
    path, receipt, source = bank
    manifest = learning.read(path)
    assert receipt["gate_a_episodes"] == 1 and receipt["shared_records"] == 1
    assert manifest["training_task_ids"] == ["test-training-1"]
    assert manifest["evaluation_task_ids"] == [task.task_id]
    assert manifest["gate_b"]["verified_skill_count"] == 0
    assert manifest["evaluation_private_episode_count"] == 0
    text = path.read_text()
    assert "PRIVATE_TRAINING_PATCH_CONTENT" not in text
    assert "PRIVATE_GRADER_TEST_CONTENT" not in text
    assert "PUBLIC_CODE_NOT_EXPORTED" not in text
    episode_id = manifest["gate_a"]["episodes"][0]["episode_id"]
    with learning.SkillMemoryStore(path.parent / manifest["gate_a"]["private_store_filename"]) as store:
        episode = store.get_episode(episode_id, org_id="fixture-training", user_id="native-session-1")
        assert episode.evidence.task_id == "test-training-1" and episode.evidence.revision == "1" * 40
        assert episode.evidence.verification_evidence_hash == "sha256:" + learning.file_sha(
            Path(source["run_root"]) / "cells/A/public-result.json")
        assert store.get_episode(episode_id, org_id=task.org_id, user_id=task.user_id) is None


@pytest.mark.parametrize("arm", ["EXISTING_M2", "SKHYNIX"])
def test_frozen_actual_controllers_inject_same_payload_and_preserve_query_checkpoint(bank, task, tmp_path, monkeypatch, arm):
    path, receipt, _ = bank
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))
    kwargs = {"frozen_bank_path": path, "frozen_bank_sha256": receipt["sha256"]}
    cell = tmp_path / arm
    manifest = bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    query = {"node_id": "lambdify", "objective": task.instruction, "operation": "Fix lambdify tuple conversion"}
    response = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    assert response["new_injection_count"] == 1
    text = response["injections"][0]["exact_text"]
    if arm == "SKHYNIX":
        text = json.loads(text)["content"]
    assert text == learning.read(path)["records"][0]["content"]
    assert manifest["training_gate_a_episode_count"] == 1
    assert manifest["seed_episode_count"] == manifest["seed_skill_count"] == 0
    again = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    assert again["repeat"] and again["injections"] == response["injections"]
    assert again["new_injection_count"] == 0


@pytest.mark.parametrize("arm", bridge.ARMS)
def test_explicit_cold_bank_is_empty_without_historical_bank_loading(task, tmp_path, monkeypatch, arm):
    path = tmp_path / "cold.json"
    receipt = learning.freeze_learned_bank(path, [], [descriptor(task)], cold_start=True)
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))
    monkeypatch.setattr(bridge, "load_validated_source_bank", lambda *a: pytest.fail("No historical import"))
    kwargs = {"frozen_bank_path": path, "frozen_bank_sha256": receipt["sha256"]}
    cell = tmp_path / arm
    manifest = bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    result = bridge.recall_memory(cell, task, arm,
        {"node_id": "cold", "objective": task.instruction, "operation": "repair"}, ROOT, **kwargs)
    assert manifest["training_gate_a_episode_count"] == 0 and not result["injections"]
    assert learning.read(path)["gate_a"]["status"] == "EMPTY_COLD_START"


@pytest.mark.parametrize("resolved,public_passed", [(False, True), (True, False)])
def test_failed_or_no_public_test_training_retains_gate_a_without_passed_shared_knowledge(tmp_path, task, resolved, public_passed):
    source = training_run(tmp_path / "training", resolved=resolved, public_passed=public_passed)
    path = tmp_path / "bank.json"
    receipt = learning.freeze_learned_bank(path, [source], [descriptor(task)])
    assert receipt["gate_a_episodes"] == 1 and receipt["shared_records"] == 0


def test_duplicate_training_tasks_cannot_be_counted_as_independent(bank, task, tmp_path):
    _, _, source = bank
    with pytest.raises(learning.LearnedBankError, match="unique and disjoint"):
        learning.freeze_learned_bank(tmp_path / "duplicate.json", [source, source], [descriptor(task)])
    assert not (tmp_path / "duplicate.gate-a-private.sqlite3").exists()


def test_training_task_cannot_be_evaluation_target(bank, task, tmp_path):
    _, _, source = bank
    with pytest.raises(learning.LearnedBankError, match="disjoint"):
        learning.freeze_learned_bank(tmp_path / "overlap.json", [source],
                                     [{**descriptor(task), "task_id": "test-training-1"}])


@pytest.mark.parametrize("file,field,value", [
    ("public-result.json", "resolved", "true"),
    ("public-result.json", "official", False),
    ("public-result.json", "target_id", "wrong-task"),
    ("public-result.json", "patch_sha256", "b" * 64),
    ("public-result.json", "grader_private_sha256", "b" * 64),
    ("submission.json", "agent_completed", False),
    ("state.json", "pending", "unfinished"),
    ("state.json", "actions", 0),
])
def test_invalid_training_receipts_fail_before_creating_bank(tmp_path, task, file, field, value):
    source = training_run(tmp_path / "training")
    path = Path(source["run_root"]) / "cells/A" / file
    write(path, {**learning.read(path), field: value})
    with pytest.raises(learning.LearnedBankError):
        learning.freeze_learned_bank(tmp_path / "bank.json", [source], [descriptor(task)])
    assert not (tmp_path / "bank.gate-a-private.sqlite3").exists()


def test_modified_event_content_is_rejected_even_with_unchanged_tail(tmp_path, task):
    source = training_run(tmp_path / "training")
    path = Path(source["run_root"]) / "cells/A/tool-events.jsonl"
    path.write_bytes(path.read_bytes().replace(b"64 passed", b"99 passed"))
    with pytest.raises(learning.LearnedBankError, match="event chain"):
        learning.freeze_learned_bank(tmp_path / "bank.json", [source], [descriptor(task)])


@pytest.mark.parametrize("argv,expected", [
    (["/opt/python", "-m", "pytest", "tests/test_public.py"], 1),
    (["pytest", "tests/test_public.py"], 1),
    (["/opt/python", "-m", "echo_fake_passed"], 0),
    (["/opt/python", "-c", "print('64 passed')"], 0),
])
def test_public_command_detection_requires_actual_test_runner_shape(tmp_path, task, argv, expected):
    source = training_run(tmp_path / "training")
    cell = Path(source["run_root"]) / "cells/A"
    path = cell / "tool-events.jsonl"
    events = [json.loads(raw) for raw in path.read_bytes().splitlines()]
    events[1]["request"]["arguments"]["argv"] = argv
    tail = "0" * 64
    for event in events:
        event.pop("sha256")
        event["previous_sha256"] = tail
        tail = learning.sha(learning.canonical(event))
        event["sha256"] = tail
    path.write_bytes(b"\n".join(learning.canonical(row) for row in events) + b"\n")
    write(cell / "state.json", {**learning.read(cell / "state.json"), "tail_sha256": tail})
    write(cell / "public-result.json", {**learning.read(cell / "public-result.json"), "tool_event_tail_sha256": tail})
    receipt = learning.freeze_learned_bank(tmp_path / "bank.json", [source], [descriptor(task)])
    assert receipt["gate_a_episodes"] == 1 and receipt["shared_records"] == expected


@pytest.mark.parametrize("changes", [{"task_id": "test-training-1"}, {"repository": "other/repo"},
    {"commit": "b" * 40}, {"instruction": "different public instruction"}])
def test_bank_is_bound_to_frozen_evaluation_public_identity(bank, task, changes):
    path, receipt, _ = bank
    with pytest.raises(learning.LearnedBankError, match="identity scope"):
        learning.load_frozen_bank(path, receipt["sha256"], replace(task, **changes))


def test_bank_hash_is_checked_again_after_initialization(bank, task, tmp_path):
    path, receipt, _ = bank
    kwargs = {"frozen_bank_path": path, "frozen_bank_sha256": receipt["sha256"]}
    cell = tmp_path / "cell"
    bridge.initialize_memory(cell, task, "NO_MEMORY", ROOT, **kwargs)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(learning.LearnedBankError, match="hash differs"):
        bridge.recall_memory(cell, task, "NO_MEMORY",
            {"node_id": "q", "objective": "repair", "operation": "repair"}, ROOT, **kwargs)


def test_omitted_hash_and_hash_without_path_fail_closed(bank, task, tmp_path):
    path, receipt, _ = bank
    with pytest.raises(learning.LearnedBankError, match="hash differs"):
        bridge.initialize_memory(tmp_path / "a", task, "NO_MEMORY", ROOT, frozen_bank_path=path)
    with pytest.raises(bridge.MemoryBridgeError, match="without a path"):
        bridge.initialize_memory(tmp_path / "b", task, "NO_MEMORY", ROOT, frozen_bank_sha256=receipt["sha256"])


def test_refuses_overwriting_frozen_bank(bank, task):
    path, _, source = bank
    before = path.read_bytes()
    with pytest.raises(learning.LearnedBankError, match="overwrite"):
        learning.freeze_learned_bank(path, [source], [descriptor(task)])
    assert path.read_bytes() == before


def test_empty_training_requires_explicit_cold_start(tmp_path, task):
    with pytest.raises(learning.LearnedBankError, match="unique and disjoint"):
        learning.freeze_learned_bank(tmp_path / "bank.json", [], [descriptor(task)])
