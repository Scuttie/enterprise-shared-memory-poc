"""Synthetic public fixtures only: no model, network, official data, or grader."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

import trimem_lcb_memory as memory
from enterprise_memory.trimem.skill_memory import PromotionRejected, ProcedureTemplate
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


def task(identity="train-a", split="train", *, family=None, starter=""):
    sample = {"input_output": json.dumps({"inputs": ["1\n"], "outputs": ["2\n"], "fn_name": None})}
    value = {"schema": memory.PUBLIC_TASK_SCHEMA, "task_id": identity, "question_id": identity,
        "split": split, "family_id": family or "family-" + identity,
        "question_title": "Synthetic increment " + identity,
        "prompt": "Increment an integer using arithmetic. Synthetic task " + identity,
        "starter_code": starter, "public_test_cases": [{"input": "1\n", "output": "2\n", "testtype": "stdin"}],
        "public_evaluation_sample": sample}
    value["instruction_sha256"] = memory._hash({key: value[key] for key in ("question_title", "prompt", "starter_code")})
    value["public_tests_sha256"] = memory.public_tests_sha256(value)
    return value


def graph(row):
    value = ShortTermWorkingGraph(row["task_id"], memory.public_task_instruction(row), memory.REPOSITORY)
    value.add_subtask(SubtaskSpec("Increment an integer using arithmetic", "apply integer arithmetic", node_id="increment"))
    value.activate("increment")
    return value


def event(row, number=1, *, code="print(int(input()) + 1)\n", passed=True, failure_kind="WRONG_ANSWER"):
    request = {"tool": "run_public_tests", "arguments": {"code": code}}
    result = {"schema": memory.PUBLIC_RESULT_SCHEMA, "task_id": row["task_id"],
        "candidate_sha256": memory._sha(code.encode()), "public_tests_sha256": row["public_tests_sha256"],
        "command": ["lcb_public_tests", row["task_id"], row["public_tests_sha256"]],
        "status": "PASS" if passed else "FAIL", "test_count": 1, "passed_count": int(passed),
        "failed_count": int(not passed), "not_run_count": 0, "exit_code": 0 if passed else 1,
        "timed_out": False, "failure_kind": None if passed else failure_kind}
    def reference(value):
        raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return {"task_id": row["task_id"], "arm": "TRAINING", "active_node_id": "increment", "step_no": number,
        "tool": "run_public_tests", "status": "success", "request_payload": request, "result_payload": result,
        "request": reference(request), "result": reference(result)}


def lesson(steps=(1,)):
    return {"summary": "Increment integer arithmetic after checking the public example.",
        "applicability": "Increment integer arithmetic", "procedure": ["Check the public integer example."],
        "trace_steps": list(steps)}


def capture(root, row, *, events=None, code=None, source_lesson=None, **kwargs):
    events = events or [event(row)]
    return memory.capture_training_episode(root, row, events, graph=graph(row),
        final_code=code or events[-1]["request_payload"]["arguments"]["code"],
        source_lesson=source_lesson or lesson([item["step_no"] for item in events]),
        contributor_id=kwargs.pop("contributor_id", "actual-session-a"), model_id="synthetic-model",
        created_at="2026-01-01T00:00:00+00:00", **kwargs)


def initialize(root, tasks=None):
    return memory.initialize_training_memory(root, org_id="synthetic-org", owner_user_id="actual-owner",
        tasks=tasks or [task(), task("valid-a", "valid"), task("test-a", "test")])


def freeze(tmp_path, *, training=None, evaluation=None, code=None):
    training = training or task()
    evaluation = evaluation or task("valid-a", "valid")
    root = tmp_path / "training"
    initialize(root, [training, evaluation, task("train-b")])
    capture(root, training, code=code)
    reference = memory.freeze_training_bank(root, tmp_path / "banks" / "bank.json")
    return root, reference, training, evaluation


def test_public_fingerprints_use_exporter_json_newline_convention():
    row = task()
    raw = (json.dumps(row["public_evaluation_sample"], sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    assert memory.public_tests_sha256(row) == hashlib.sha256(raw).hexdigest()
    assert memory.public_tests_sha256(row["public_evaluation_sample"]) == row["public_tests_sha256"]


@pytest.mark.parametrize("mutation", [
    lambda row: row.update(private_test_cases=[]),
    lambda row: row.update(prompt="Substituted prompt"),
    lambda row: row.update(public_tests_sha256="0" * 64),
    lambda row: row["public_test_cases"][0].update(output="substituted"),
])
def test_rejects_private_or_substituted_public_input(tmp_path, mutation):
    row = task()
    mutation(row)
    with pytest.raises(memory.LCBMemoryError):
        initialize(tmp_path / "train", [row])


def test_split_family_and_identity_isolation(tmp_path):
    with pytest.raises(memory.LCBMemoryError, match="family"):
        initialize(tmp_path / "one", [task(family="shared"), task("valid", "valid", family="shared")])
    with pytest.raises(memory.LCBMemoryError, match="Duplicate"):
        initialize(tmp_path / "two", [task(), task()])
    valid = task("valid", "valid")
    original = task()
    for key in ("prompt", "question_title", "starter_code", "instruction_sha256"):
        valid[key] = original[key]
    with pytest.raises(memory.LCBMemoryError, match="instruction"):
        initialize(tmp_path / "three", [original, valid])


def test_evaluation_never_enters_training_authority(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    with pytest.raises(memory.LCBMemoryError, match="scope"):
        capture(root, task("valid-a", "valid"))
    with sqlite3.connect(root / "authority.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 0


def test_reflection_must_cite_actual_public_steps(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    with pytest.raises(memory.LCBMemoryError, match="trace steps"):
        capture(root, task(), source_lesson=lesson([19]))
    with pytest.raises(memory.LCBMemoryError, match="source_lesson"):
        capture(root, task(), source_lesson={**lesson(), "private_verdict": True})


def test_public_trace_hash_and_candidate_binding_are_enforced(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    row = task()
    altered = event(row)
    altered["result_payload"]["candidate_sha256"] = "0" * 64
    with pytest.raises(memory.LCBMemoryError, match="exact evidence reference"):
        capture(root, row, events=[altered])
    altered.pop("result")
    with pytest.raises(memory.LCBMemoryError, match="bound"):
        capture(root, row, events=[altered])


def test_false_pass_counts_do_not_become_success(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    row = task()
    altered = event(row)
    altered.pop("result")
    altered["result_payload"].update(passed_count=0, not_run_count=1)
    with pytest.raises(memory.LCBMemoryError, match="PASS"):
        capture(root, row, events=[altered])


@pytest.mark.parametrize("extra", [{"passed": False}, {"failure_kind": "WRONG_ANSWER"}, {"assertion_failures": 1}])
def test_disagreeing_public_verdict_fields_are_rejected(tmp_path, extra):
    root = tmp_path / "training"
    initialize(root)
    row = task()
    altered = event(row)
    altered.pop("result")
    altered["result_payload"].update(extra)
    with pytest.raises(memory.LCBMemoryError, match="Public receipt"):
        capture(root, row, events=[altered])


def test_private_payload_cannot_hide_inside_other_public_tool_result(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    row = task()
    value = event(row)
    value.update(tool="revise_subtask_dag", request_payload={"tool": "revise_subtask_dag", "arguments": {}},
        result_payload={"nested": {"private_verdict": True}})
    value.pop("request")
    value.pop("result")
    with pytest.raises(memory.LCBMemoryError, match="Private grader"):
        capture(root, row, events=[value], code="print(2)\n")


def test_failed_and_untested_final_candidates_remain_private_l1(tmp_path):
    root = tmp_path / "training"
    initialize(root, [task(), task("train-b")])
    failed = capture(root, task(), events=[event(task(), passed=False)])
    untested = capture(root, task("train-b"), code="print('untested candidate')\n")
    assert failed["public_examples_passed"] is False
    assert untested["public_examples_passed"] is False
    bank = memory.freeze_training_bank(root, tmp_path / "bank.json")
    assert bank["layer_counts"]["L1_episodes"] == 2
    assert bank["layer_counts"]["L3_skills"] == 0


def test_rejected_public_tool_call_retains_l1_without_fabricating_verdict(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    row = task()
    rejected = event(row)
    rejected.update(status="error", result_payload={"error": "ValueError", "message": "Invalid public candidate"})
    rejected.pop("result")
    receipt = capture(root, row, events=[rejected])
    assert receipt["public_examples_passed"] is False
    observation = memory.observe_available_workflow(root, row["task_id"])
    assert observation["status"] == "NO_ELIGIBLE_PUBLIC_WORKFLOW"
    assert observation["l3_promoted"] is False
    memory.freeze_training_bank(root, tmp_path / "bank.json")


def test_record_resume_is_idempotent_but_cannot_retry_outcome(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    first = capture(root, task())
    assert capture(root, task()) == first
    with pytest.raises(memory.LCBMemoryError, match="replaced or retried"):
        capture(root, task(), code="print('different final candidate')\n")


def test_ast_facts_have_real_symbols_import_edges_and_candidate_scope(tmp_path):
    code = "import math\nclass Counter:\n    def increment(self, number):\n        return number + 1\n"
    root, reference, _, _ = freeze(tmp_path, code=code)
    with memory.load_frozen_bank(reference["path"], reference["sha256"]) as bank:
        snapshot = bank.snapshot(org_id="synthetic-org", user_id="actual-owner", repository=memory.REPOSITORY,
            revision="sha256:" + memory._sha(code.encode()), language="python")
        facts = [json.loads(item.content) for item in snapshot.repository_knowledge]
        assert {item["name"] for item in facts} == {"solution.py", "math", "Counter", "Counter.increment"}
        assert all(item["source_task_id"] == "train-a" for item in facts)
        assert len(snapshot.knowledge_edges) == 4
        assert snapshot.repository_knowledge[0].revision == "sha256:" + memory._sha(code.encode())
        unrelated = bank.snapshot(org_id="synthetic-org", user_id="actual-owner", repository=memory.REPOSITORY,
            revision="sha256:" + "0" * 64, language="python")
        assert unrelated.repository_knowledge == ()


def test_frozen_recall_uses_existing_controller_l1_and_checkpoint(tmp_path):
    _, reference, _, target = freeze(tmp_path)
    with memory.load_frozen_bank(reference["path"], reference["sha256"]) as bank:
        result = bank.recall(target, graph(target))
        assert len(result["injections"]) == 1
        assert result["injections"][0]["kind"] == "EPISODIC"
        assert "MODEL_REFLECTION_WITH_PUBLIC_TRACE_ANCHORS" in result["injections"][0]["exact_text"]
        assert bank.recall(target, graph(target), checkpoint=result["checkpoint"])["injections"] == []
        assert [row["bank"] for row in result["decisions"]] == ["SKILL", "REPOSITORY_SEMANTIC", "EPISODIC"]


def test_current_identical_source_uses_ast_layer_without_revision_retagging(tmp_path):
    code = "def increment(number):\n    return number + 1\n"
    target = task("valid-a", "valid", starter=code)
    _, reference, _, _ = freeze(tmp_path, code=code, evaluation=target)
    with memory.load_frozen_bank(reference["path"], reference["sha256"]) as bank:
        result = bank.recall(target, graph(target))
        assert result["injections"][0]["kind"] == "REPOSITORY_SEMANTIC"
        assert "IDENTICAL_CANDIDATE_SOURCE_ONLY" in result["injections"][0]["exact_text"]


def test_recall_rejects_training_target_and_other_scope(tmp_path):
    _, reference, train, target = freeze(tmp_path)
    with memory.load_frozen_bank(reference["path"], reference["sha256"]) as bank:
        with pytest.raises(memory.LCBMemoryError, match="valid or test"):
            bank.recall(train, graph(train))
        with pytest.raises(memory.LCBMemoryError, match="scope"):
            bank.recall(task("not-enrolled", "valid"), graph(task("not-enrolled", "valid")))
        with pytest.raises(memory.LCBMemoryError, match="owner"):
            bank.snapshot(org_id="synthetic-org", user_id="invented-owner", repository=memory.REPOSITORY)
        with pytest.raises(memory.LCBMemoryError, match="checkpoint"):
            bank.recall(target, graph(target), checkpoint={"binding": {"bank_sha256": "0" * 64}})


def test_snapshot_is_portable_and_independent_of_continued_training(tmp_path):
    root, reference, _, target = freeze(tmp_path)
    original_bytes = Path(reference["path"]).read_bytes()
    capture(root, task("train-b"))
    moved = tmp_path / "moved"
    shutil.copytree(Path(reference["path"]).parent, moved)
    shutil.rmtree(root)
    assert (moved / "bank.json").read_bytes() == original_bytes
    with memory.load_frozen_bank(moved / "bank.json", reference["sha256"]) as bank:
        assert bank.manifest["layer_counts"]["training_tasks"] == 1
        assert bank.recall(target, graph(target))["injections"]


@pytest.mark.parametrize("changed", ["manifest", "capture", "authority"])
def test_changed_frozen_bytes_fail_before_retrieval(tmp_path, changed):
    _, reference, _, target = freeze(tmp_path)
    with memory.load_frozen_bank(reference["path"], reference["sha256"]) as bank:
        if changed == "manifest":
            path = Path(reference["path"])
        elif changed == "authority":
            path = bank.root / "authority.sqlite3"
        else:
            path = bank.root / next(iter(bank.manifest["catalog"]["captures"].values()))["path"]
        with path.open("ab") as stream:
            stream.write(b"changed")
        with pytest.raises(memory.LCBMemoryError, match="changed"):
            bank.recall(target, graph(target))


def test_unproven_extra_memory_records_fail_freeze(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    capture(root, task())
    with memory.SkillMemoryStore(root / "authority.sqlite3") as store:
        store.put_repository_knowledge(org_id="synthetic-org", repository="old-swe-bank", title="unrelated",
            content="Never imported from prior experiments", revision="elsewhere", language="python")
    with pytest.raises(memory.LCBMemoryError, match="provenance"):
        memory.freeze_training_bank(root, tmp_path / "bank.json")


def skill_proposal(events):
    template = ProcedureTemplate(subgoal_signature="Validate a changed candidate using public examples",
        parameters=("initial", "revised", "public_command"),
        preconditions=("Use observed public examples only; correctness on private tests is unknown.",),
        steps=("run_public_tests candidate_sha256={initial} command={public_command}",
               "run_public_tests candidate_sha256={revised} command={public_command}"),
        verification_command="{public_command}", language="python")
    bindings = {"initial": events[0]["result_payload"]["candidate_sha256"],
        "revised": events[-1]["result_payload"]["candidate_sha256"],
        "public_command": json.dumps(events[-1]["result_payload"]["command"], separators=(",", ":"))}
    return template, bindings


def test_l3_observed_red_green_still_cannot_invent_second_user(tmp_path):
    root = tmp_path / "training"
    rows = [task(), task("train-b")]
    initialize(root, rows)
    observations = []
    for index, row in enumerate(rows):
        events = [event(row, 1, code="print(int(input()))\n", passed=False), event(row, 2)]
        capture(root, row, events=events, contributor_id="real-different-session-" + str(index))
        template, bindings = skill_proposal(events)
        observation = memory.verify_skill_observation(root, row["task_id"], template,
            bindings=bindings, red_step=1, green_step=2)
        observations.append(observation["observation_id"])
    with pytest.raises(PromotionRejected, match="distinct tasks, users"):
        memory.promote_verified_skill(root, template, observations)
    reference = memory.freeze_training_bank(root, tmp_path / "bank.json")
    assert reference["layer_counts"]["verified_public_workflows"] == 2
    assert reference["layer_counts"]["L3_skills"] == 0


def test_mechanical_public_workflow_is_idempotent_and_never_a_promoted_skill(tmp_path):
    root = tmp_path / "training"
    initialize(root)
    row = task()
    capture(root, row, events=[event(row, 1, code="print(int(input()))\n", passed=False), event(row, 2)])
    result = memory.observe_available_workflow(root, row["task_id"])
    assert result["status"] == "PUBLIC_WORKFLOW_OBSERVED_NOT_PROMOTED"
    assert result["l3_promoted"] is False
    assert memory.observe_available_workflow(root, row["task_id"]) == result
    reference = memory.freeze_training_bank(root, tmp_path / "bank.json")
    assert reference["layer_counts"]["verified_public_workflows"] == 1
    assert reference["layer_counts"]["L3_skills"] == 0


@pytest.mark.parametrize("invalid", ["runtime", "same-code", "first-green", "different-command", "unobserved-template"])
def test_l3_rejects_unproved_repair_claims(tmp_path, invalid):
    root = tmp_path / "training"
    initialize(root)
    row = task()
    events = [event(row, 1, code="print(int(input()))\n", passed=False), event(row, 2)]
    if invalid == "runtime":
        events[0] = event(row, 1, code="print(int(input()))\n", passed=False, failure_kind="RUNTIME_ERROR")
    elif invalid == "same-code":
        events[0] = event(row, 1, passed=False)
    elif invalid == "first-green":
        events[0] = event(row, 1, code="print(int(input()))\n", passed=True)
    elif invalid == "different-command":
        events[0].pop("result")
        events[0]["result_payload"]["command"] = ["made-up-command"]
        with pytest.raises(memory.LCBMemoryError, match="bound"):
            capture(root, row, events=events)
        return
    capture(root, row, events=events)
    template, bindings = skill_proposal(events)
    if invalid == "unobserved-template":
        bindings["revised"] = "0" * 64
    with pytest.raises(memory.LCBMemoryError, match="L3"):
        memory.verify_skill_observation(root, row["task_id"], template, bindings=bindings, red_step=1, green_step=2)


def test_l0_projection_is_the_existing_shared_projection():
    row = task()
    history = [event(row)]
    assert memory.project_context(graph(row), history) == memory.project_subgoal_context(graph(row), history)


def test_frozen_store_refuses_sql_writes(tmp_path):
    _, reference, _, _ = freeze(tmp_path)
    with memory.load_frozen_bank(reference["path"], reference["sha256"]) as bank:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            bank.store._db.execute("DELETE FROM memory_records")


def test_relative_evidence_reference_cannot_escape_bank(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    reference = {"path": "../outside.json", "sha256": memory._sha(outside.read_bytes())}
    with pytest.raises(memory.LCBMemoryError, match="escaped"):
        memory._check_ref(reference, tmp_path / "bank")
