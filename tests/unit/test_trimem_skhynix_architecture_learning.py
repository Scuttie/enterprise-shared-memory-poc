"""Public broker fixtures only; no model, repository command, or grader execution."""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.skill_memory import ProcedureTemplate
import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
from trimem_skhynix_architecture_broker import ArchitectureBroker

SOURCE = "def normalize_filename_extension(path):\n    return path.upper()\n"
HELPER = "def filename_extension(path):\n    return path.rsplit('.', 1)[-1]\n"
ARGV = ["python", "-m", "pytest", "tests/test_extension.py"]


def write(path, value, *, sidecar=False):
    memory._write(path, value, fresh=True)
    if sidecar:
        path.with_suffix(".sha256").write_text(memory._hash(value) + "\n")
    return memory._ref(path)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    targets, rows = [], {}
    for index, role in ((1, "TRAINING"), (2, "TRAINING"), (3, "EVALUATION")):
        instance = "example__project-" + str(index)
        instruction = "normalize filename extension for source " + str(index)
        targets.append({"role": role, "target_id": ("swebench--" if role == "TRAINING" else "swebench_verified--") + instance,
            "instance_id": instance, "repository": "example/project", "base_commit": "a" * 40,
            "instruction_sha256": sha256_bytes(instruction.encode())})
        rows[instance] = {"problem_statement": "  " + instruction + "  "}
    dataset = write(tmp_path / "dataset.json", {"public_fixture": True})
    calls = []
    def public_rows(path, *, expected_sha256):
        assert {"path": path, "sha256": expected_sha256} == dataset
        memory._check_ref(dataset)
        calls.append(path)
        return deepcopy(targets), deepcopy(rows), {"training_count": 2, "evaluation_count": 1}
    monkeypatch.setattr(learning, "load_architecture_rows", public_rows)
    monkeypatch.setattr(learning, "TRAINING_COUNT", 2)
    monkeypatch.setattr(learning, "EVALUATION_COUNT", 1)
    import trimem_skhynix_architecture_dataset as dataset_module
    monkeypatch.setattr(dataset_module, "_private_grader_row", lambda *args: pytest.fail("Private grader row must never be read"))
    image = write(tmp_path / "images.json", {"public_image_fixture": True})
    preflight = write(tmp_path / "preflight.json", {"public_loader_fixture": True})
    config = {"schema": "skhynix/pdf-architecture-execution/1.0", "phase": "TRAINING_RUNTIME",
        "training_memory_policy": "COLD_START_NATIVE_TRACES_THEN_OFFLINE_GATE_A_AND_GATE_B",
        "org_id": "fixture-learning-org", "dataset_manifest": dataset, "image_index": image,
        "loader_preflight_path": preflight["path"], "loader_preflight_sha256": preflight["sha256"],
        "source_root": str(tmp_path), "source_sha256": {}, "run_root": str(tmp_path / "run"),
        "training_owner_by_instance": {"example__project-1": 1, "example__project-2": 2}}
    execution = write(tmp_path / "execution.json", config, sidecar=True)
    root = tmp_path / "memory"
    learning.initialize_learning(root, execution_references=[execution])
    return SimpleNamespace(root=root, tmp=tmp_path, targets=targets, rows=rows, config=config,
        execution=execution, public_calls=calls)


def cell(ctx, index, *, complete=True, green=True, no_attempt=False, sealed=True,
        later_subgoal=False, before_complete_command=False, read_padding=0, command_override=None):
    target = ctx.targets[index - 1]
    public = {"task_id": target["target_id"], "repository": target["repository"], "commit": target["base_commit"],
        "instruction": ctx.rows[target["instance_id"]]["problem_statement"].strip()}
    directory = Path(ctx.config["run_root"]) / "cells" / "TRAINING" / public["task_id"] / "PDF_MEMORY"
    directory.mkdir(parents=True)
    state = {"commands": 0}
    def execute(tool, arguments):
        if tool == "read_file":
            content = (SOURCE if arguments["path"] == "source.py" else HELPER) + ("# unrelated read output " + "x" * read_padding + "\n" if read_padding else "")
            return {"path": arguments["path"], "content": content, "total_file_bytes": len(content.encode()),
                "full_file_sha256": sha256_bytes(content.encode()), "returned_start_line": 1, "truncated": False}
        if tool == "run_command":
            state["commands"] += 1
            if command_override is not None:
                return deepcopy(command_override)
            passed = green and state["commands"] == 2
            return {"stdout": "1 passed in 0.2s" if passed else "AssertionError: extension differs\n1 failed in 0.2s",
                "stderr": "", "exit_code": 0 if passed else 1, "timed_out": False, "output_truncated": False}
        if tool == "replace_text":
            return {"path": arguments["path"], "prior_sha256": sha256_bytes(SOURCE.encode()),
                "new_sha256": sha256_bytes(SOURCE.replace("upper", "lower").encode()), "old_bytes": 5, "new_bytes": 5, "replacements": 1}
        raise AssertionError(tool)
    broker = ArchitectureBroker.create(directory / "broker", task_public=public, arm="PDF_MEMORY",
        workspace=SimpleNamespace(execute=execute, patch=lambda: "PUBLIC_WORKER_PATCH"),
        configuration_sha256=memory._hash(ctx.config), bank_sha256=learning.EMPTY_BANK_SHA,
        tool_schema={"public_tools": ["read_file", "run_command", "replace_text"]},
        memory_callback=lambda task, graph, query, checkpoint: {"injections": [], "checkpoint": checkpoint, "decisions": []},
        clock=lambda: 1789360000.0)
    value = {"schema": ctx.config["schema"], "phase": "TRAINING", "arm": "PDF_MEMORY",
        "task_public": public, "org_id": ctx.config["org_id"], "owner_user_id": "architecture-contributor-" + str(ctx.config["training_owner_by_instance"][target["instance_id"]]),
        "bank_sha256": learning.EMPTY_BANK_SHA, "bank_reference": None,
        "broker_root": str(directory / "broker"), "experiment_config": ctx.execution["path"]}
    path = directory / "cell.json"
    write(path, value, sidecar=True)
    if no_attempt is True:
        broker.seal_partial(reason="COMMISSIONING_NO_PUBLIC_ACTIONS")
        return path
    def launch(worker):
        issued = broker.issue_handoff(worker)
        return broker.admit_worker(worker, issued["packet_sha256"], {"thread_id": f"fixture-thread-{index}-{worker}",
            "fork_turns": "none", "fresh_session": True, "requested_model": "gpt-6-astra", "launch_evidence_sha256": "e" * 64})["admission_token"]
    token = launch("planner")
    if no_attempt == "native":
        assert broker.action("planner", token, {"request_id": "submit-empty", "op": "submit", "summary": "No justified repository action was available"})["ok"]
        return path
    subgoals = [{"node_id": "normalize", "objective": "normalize filename extension", "operation": "normalize filename extension"}]
    if later_subgoal:
        subgoals.append({"node_id": "cleanup", "objective": "independent later cleanup", "operation": "cleanup", "dependencies": ["normalize"]})
    assert broker.action("planner", token, {"request_id": "plan", "op": "plan_subgoals", "subgoals": subgoals})["ok"]
    assert broker.action("planner", token, {"request_id": "activate", "op": "activate_subgoal", "node_id": "normalize"})["ok"]
    token = launch("solver")
    if no_attempt == "active":
        assert broker.action("solver", token, {"request_id": "submit-active-empty", "op": "submit", "summary": "Active subgoal had no public tool attempt"})["ok"]
        return path
    operations = [("read_file", {"path": "source.py"}), ("read_file", {"path": "helper.py"}),
        ("run_command", {"argv": ARGV}), ("replace_text", {"path": "source.py", "expected_file_sha256": sha256_bytes(SOURCE.encode()),
            "old_text": "upper", "new_text": "lower"}), ("run_command", {"argv": ARGV})]
    for number, (tool, arguments) in enumerate(operations, 3):
        response = broker.action("solver", token, {"request_id": "tool-" + str(number), "op": "tool", "name": tool, "arguments": arguments})
        assert response["ok"] and response["step_no"] == number
    if before_complete_command:
        assert broker.action("solver", token, {"request_id": "later-command", "op": "tool", "name": "run_command",
            "arguments": {"argv": ["python", "-c", "print('unverified public inspection')"]}})["ok"]
    if complete:
        assert broker.action("solver", token, {"request_id": "complete", "op": "complete_subgoal",
            "summary": "Observed public extension normalization and test output", "evidence_steps": [7]})["ok"]
    if later_subgoal:
        token = launch("cleanup")
        assert broker.action("cleanup", token, {"request_id": "later-test-edit", "op": "tool", "name": "replace_text",
            "arguments": {"path": "tests/test_extension.py", "expected_file_sha256": sha256_bytes(SOURCE.encode()),
                "old_text": "upper", "new_text": "lower"}})["ok"]
        response = broker.action("cleanup", token, {"request_id": "later-cleanup", "op": "tool", "name": "run_command",
            "arguments": {"argv": ["python", "-c", "print('unverified cleanup')"]}})
        assert response["ok"]
        if later_subgoal == "complete":
            assert broker.action("cleanup", token, {"request_id": "complete-cleanup", "op": "complete_subgoal",
                "summary": "Future cleanup summary", "evidence_steps": [response["step_no"]]})["ok"]
    if sealed:
        assert broker.action("cleanup" if later_subgoal else "solver", token, {"request_id": "submit", "op": "submit", "summary": "Public normalization attempt and honest test results"})["ok"]
    # Grader-only files are unrelated artifacts, never read by the helper.
    (directory / "grader-private.json").write_text("THIS IS NOT JSON AND MUST NEVER BE OPENED")
    return path


def captured(ctx, *, second_green=True):
    paths = [cell(ctx, 1), cell(ctx, 2, green=second_green)]
    return paths, [learning.capture_cell(ctx.root, path) for path in paths]


def proposal(ctx, reflection, *, mutate=None):
    exported = memory._read(reflection["path"])
    template = ProcedureTemplate("normalize filename extension", ("path", "test_argv"), (memory.PRECONDITION,),
        ("read_file {path}", "replace_text {path}\nold_text: upper\nnew_text: lower", "run_command {test_argv}"), "{test_argv}", "python")
    value = {"schema": learning.PROPOSALS_SCHEMA, "reflection_sha256": reflection["sha256"], "proposals": [{"template": asdict(template),
        "observations": [{"source_alias": source["source_alias"], "bindings": {"path": "source.py", "test_argv": canonical_bytes(ARGV).decode()},
            "step_numbers": [3, 6, 7], "red_step": 5} for source in exported["sources"]
            if source["checkpoint"]["kind"] == "COMPLETED_SUBGOAL" and source["active_node_id"] == "normalize"]}]}
    if mutate: mutate(value)
    return write(ctx.tmp / "proposals.json", value)


def test_full_public_capture_reflection_real_gate_b_and_publication(inputs):
    _, references = captured(inputs)
    assert all(memory._read(ref["path"])["status"] == "CAPTURED" for ref in references)
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    result_ref = learning.ingest_proposals(inputs.root, proposal(inputs, reflection), reflection_reference=reflection)
    result = memory._read(result_ref["path"])
    assert result["promotions_added"] == 1 and result["outcomes"][0]["status"] == "PROMOTED"
    published = learning.freeze_published_bank(inputs.root, inputs.tmp / "bank.json")
    assert published["layer_counts"] == {"L1_episodes": 8, "L2_nodes": 12, "L2_edges": 6, "L3_skills": 1}
    bank = memory.load_frozen_bank(published["path"], published["sha256"])
    bank.close()
    receipt = memory._read(published["publication_reference"]["path"])
    assert receipt["actual_training_sources"] == 2 and receipt["official_grader_payloads_read"] == 0
    with pytest.raises(learning.LearningError, match="immutable"):
        learning.export_reflection(inputs.root, inputs.tmp / "later.json")


@pytest.mark.parametrize("complete,green", [(True, True), (True, False), (False, True), (False, False)])
def test_completed_partial_and_failed_attempts_have_actual_gate_a_labels(inputs, complete, green):
    path = cell(inputs, 1, complete=complete, green=green)
    reference = learning.capture_cell(inputs.root, path)
    receipt = memory._read(reference["path"])
    assert receipt["status"] == "CAPTURED" and len(receipt["captures"]) == 3
    capture = receipt["captures"][-1]
    assert capture["semantic_completion"] == complete
    assert capture["receipt"]["succeeded"] == green
    assert capture["verification_step"] == 7 and receipt["gate_b_promotions"] == 0
    assert learning.capture_cell(inputs.root, path) == reference
    assert len(memory._read(inputs.root / "catalog.json")["captures"]) == 3
    if not complete:
        raw = memory._read(memory._read(inputs.root / "catalog.json")["captures"][capture["receipt"]["capture_id"]]["path"])
        assert "not completed" in raw["summary"]


def test_empty_commissioning_source_is_not_a_training_capture(inputs):
    receipt = memory._read(learning.capture_cell(inputs.root, cell(inputs, 1, no_attempt=True))["path"])
    assert receipt["status"] == "NO_PUBLIC_ATTEMPTS" and receipt["captures"] == []
    assert receipt["public_tool_rows"] == 0
    assert not receipt["source_execution_observed"]
    assert not memory._read(inputs.root / "catalog.json")["captures"]


@pytest.mark.parametrize("change", ["unsealed", "checkpoint", "event", "pending", "owner", "instruction", "phase", "scopepath"])
def test_source_binding_failures_are_durable_and_do_not_fake_gate_counts(inputs, change):
    path = cell(inputs, 1, sealed=change != "unsealed")
    root = path.parent / "broker"
    if change == "checkpoint":
        value = memory._read(root / "state.json")
        value["actions"] += 1
        memory._write(root / "state.json", value)
    if change == "event":
        with (root / "events.jsonl").open("ab") as stream: stream.write(b"{}\n")
    if change == "pending": memory._write(root / "pending.json", {"phase": "FINISHED"}, fresh=True)
    if change in ("owner", "instruction", "phase"):
        value = memory._read(path)
        if change == "owner": value["owner_user_id"] = "someone-else"
        if change == "instruction": value["task_public"]["instruction"] = "another issue"
        if change == "phase": value["phase"] = "EVALUATION"
        memory._write(path, value)
        path.with_suffix(".sha256").write_text(memory._hash(value) + "\n")
    if change == "scopepath": path = inputs.tmp / "grader-private.json"
    reference = learning.capture_cell(inputs.root, path)
    value = memory._read(reference["path"])
    assert value["status"] == "INVALID_SOURCE" and value["failures"]
    assert value["captures"] == [] and value["gate_b_promotions"] == 0
    assert not memory._read(inputs.root / "catalog.json")["captures"]


def test_hook_ignores_even_unreadable_grader_outcome_and_recovers_durable_receipt(inputs):
    class NeverInspect:
        def __getattribute__(self, name):
            raise AssertionError("Official outcome must not control learning")
    path = cell(inputs, 1, green=False)
    hook = learning.make_capture_hook(inputs.root)
    reference = hook(path, NeverInspect(), inputs.tmp / "cohort-receipt")
    assert hook(path, NeverInspect(), inputs.tmp / "cohort-receipt") == reference
    registry = memory._read(inputs.root / "learning-state.json")
    registry["cells"] = {}
    memory._write(inputs.root / "learning-state.json", registry)
    assert hook(path, NeverInspect(), inputs.tmp / "cohort-receipt") == reference
    assert len(memory._read(inputs.root / "catalog.json")["captures"]) == 3


def test_reflection_export_sanitizes_identity_but_preserves_exact_public_payloads(inputs):
    _, refs = captured(inputs)
    result = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    public = memory._read(result["path"])
    text = Path(result["path"]).read_text()
    assert "architecture-contributor-" not in text and str(inputs.tmp) not in text
    assert "admission_token" not in text and "PUBLIC_WORKER_PATCH" not in text and "grader-private" not in text
    assert {row["contributor_group"] for row in public["sources"]} == {"contributor-1", "contributor-2"}
    catalog = memory._read(inputs.root / "catalog.json")
    originals = [memory._read(reference["path"]) for reference in catalog["captures"].values()]
    for source in public["sources"]:
        rows = [public["trace_rows"][index] for index in source["history_row_indices"]]
        assert all(row["task_id"] == source["task_group"] for row in rows)
        assert any([row["request_payload"] for row in rows] == [row["request_payload"] for row in original["history"]] for original in originals)
        for row in rows:
            if "result_payload" in row:
                assert memory._hash(row["result_payload"]) == row["result"]["sha256"]
            else:
                assert row["tool"] == "read_file"
                assert row["result_payload_omission"]["sha256"] == row["result"]["sha256"]
    assert learning.export_reflection(inputs.root, inputs.tmp / "reflection.json") == result


def test_reflection_cap_rejects_instead_of_truncating_actual_evidence(inputs):
    captured(inputs)
    with pytest.raises(learning.LearningError, match="never truncate"):
        learning.export_reflection(inputs.root, inputs.tmp / "too-small.json", max_bytes=1024)
    assert not (inputs.tmp / "too-small.json").exists()


@pytest.mark.parametrize("change", ["unknownsource", "sametask", "inventedsteps", "wrongred", "manualverified", "hidden", "wrongbinding", "empty"])
def test_untrusted_reflection_proposals_cannot_bypass_actual_gate_b(inputs, change):
    captured(inputs)
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    def mutate(value):
        if change == "unknownsource": value["proposals"][0]["observations"][0]["source_alias"] = "target-leak"
        if change == "sametask": value["proposals"][0]["observations"][1] = deepcopy(value["proposals"][0]["observations"][0])
        if change == "inventedsteps": value["proposals"][0]["observations"][0]["step_numbers"] = [101, 102, 103]
        if change == "wrongred": value["proposals"][0]["observations"][0]["red_step"] = 7
        if change == "manualverified": value["proposals"][0]["verified"] = True
        if change == "hidden": value["test_patch"] = "forbidden"
        if change == "wrongbinding": value["reflection_sha256"] = "f" * 64
        if change == "empty": value["proposals"] = []
    proposal_ref = proposal(inputs, reflection, mutate=mutate)
    result_ref = learning.ingest_proposals(inputs.root, proposal_ref, reflection_reference=reflection)
    receipt = memory._read(result_ref["path"])
    assert receipt["promotions_added"] == 0
    assert not memory._read(inputs.root / "catalog.json")["skills"]
    assert learning.ingest_proposals(inputs.root, proposal_ref, reflection_reference=reflection) == result_ref
    if change != "empty": assert receipt["failures"] or receipt["outcomes"][0]["status"] == "REJECTED"
    with pytest.raises((learning.LearningError, memory.ArchitectureMemoryError), match="Gate B"):
        learning.freeze_published_bank(inputs.root, inputs.tmp / "bank.json")


def test_actual_failed_source_rejects_promotion_without_erasing_gate_a(inputs):
    captured(inputs, second_green=False)
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    result = memory._read(learning.ingest_proposals(inputs.root, proposal(inputs, reflection), reflection_reference=reflection)["path"])
    assert result["promotions_added"] == 0 and result["outcomes"][0]["status"] == "REJECTED"
    catalog = memory._read(inputs.root / "catalog.json")
    assert len(catalog["captures"]) == 6 and len(catalog["knowledge"]) == 12 and not catalog["skills"]


def test_changed_public_broker_evidence_cannot_enter_reflection(inputs):
    paths, _ = captured(inputs)
    with (paths[0].parent / "broker" / "events.jsonl").open("ab") as stream: stream.write(b"changed")
    with pytest.raises(memory.ArchitectureMemoryError, match="changed"):
        learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")


def test_candidate_or_incomplete_enrollment_is_not_initialized(inputs, monkeypatch):
    monkeypatch.setattr(learning, "TRAINING_COUNT", 24)
    monkeypatch.setattr(learning, "EVALUATION_COUNT", 500)
    with pytest.raises(learning.LearningError, match="24 sources"):
        learning.initialize_learning(inputs.tmp / "wrong-count", execution_references=[inputs.execution])
    assert not (inputs.tmp / "wrong-count").exists()


def test_owner_mapping_and_enrollment_cannot_change(inputs):
    config = {**inputs.config, "training_owner_by_instance": {"example__project-1": 2, "example__project-2": 1}}
    second = write(inputs.tmp / "other-execution.json", config, sidecar=True)
    with pytest.raises(learning.LearningError, match="stable owners"):
        learning.initialize_learning(inputs.tmp / "another", execution_references=[inputs.execution, second])
    with pytest.raises(learning.LearningError, match="immutable"):
        learning.initialize_learning(inputs.root, execution_references=[second])


def test_publication_requires_every_enrolled_actual_source(inputs):
    learning.capture_cell(inputs.root, cell(inputs, 1))
    with pytest.raises(learning.LearningError, match="all enrolled"):
        learning.freeze_published_bank(inputs.root, inputs.tmp / "bank.json")
    assert not (inputs.tmp / "bank.json").exists()


def test_legitimate_zero_tool_source_is_accounted_without_fabricated_memory(inputs, monkeypatch):
    monkeypatch.setattr(learning, "TRAINING_COUNT", 3)
    instruction = "normalize filename extension for another source"
    target = {**inputs.targets[0], "instance_id": "example__project-4", "target_id": "swebench--example__project-4",
        "instruction_sha256": sha256_bytes(instruction.encode())}
    inputs.targets.append(target)
    inputs.rows[target["instance_id"]] = {"problem_statement": instruction}
    inputs.config = {**inputs.config, "training_owner_by_instance": {**inputs.config["training_owner_by_instance"], "example__project-4": 1}}
    inputs.execution = write(inputs.tmp / "three-execution.json", inputs.config, sidecar=True)
    inputs.root = inputs.tmp / "three-memory"
    learning.initialize_learning(inputs.root, execution_references=[inputs.execution])
    captured(inputs)
    empty = memory._read(learning.capture_cell(inputs.root, cell(inputs, 4, no_attempt="native"))["path"])
    assert empty["status"] == "NO_PUBLIC_ATTEMPTS" and empty["source_execution_observed"]
    assert empty["captures"] == []
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    learning.ingest_proposals(inputs.root, proposal(inputs, reflection), reflection_reference=reflection)
    result = learning.freeze_published_bank(inputs.root, inputs.tmp / "bank.json")
    published = memory._read(result["publication_reference"]["path"])
    assert published["actual_training_sources"] == 3 and published["sources_with_captures"] == 2
    assert published["sources_without_public_tool_evidence"] == 1
    assert result["layer_counts"]["L1_episodes"] == 8 and result["layer_counts"]["L3_skills"] == 1


def checkpoint_captures(ctx, path):
    reference = learning.capture_cell(ctx.root, path)
    receipt = memory._read(reference["path"])
    assert receipt["status"] == "CAPTURED", receipt["failures"]
    catalog = memory._read(ctx.root / "catalog.json")
    return reference, receipt, {item["receipt"]["capture_id"]: memory._read(catalog["captures"][item["receipt"]["capture_id"]]["path"])
        for item in receipt["captures"]}


@pytest.mark.parametrize("later", ["active", "complete"])
def test_every_test_completion_and_terminal_checkpoint_retains_global_prefix_and_future_disclosure(inputs, later):
    path = cell(inputs, 1, later_subgoal=later)
    _, receipt, captures = checkpoint_captures(inputs, path)
    history = memory._read(path.parent / "broker" / "state.json")["history"]
    assert [item["checkpoint"]["kind"] for item in receipt["captures"]] == [
        "PUBLIC_TEST_OBSERVATION", "PUBLIC_TEST_OBSERVATION", "COMPLETED_SUBGOAL",
        "COMPLETED_SUBGOAL" if later == "complete" else "TERMINAL_ACTIVE"]
    assert [item["checkpoint"]["public_test_outcome"] for item in receipt["captures"]] == ["RED", "GREEN", None, None]
    assert len(captures) == 4
    for item in receipt["captures"]:
        checkpoint = item["checkpoint"]
        raw = captures[item["receipt"]["capture_id"]]
        prefix = [row for row in history if row["step_no"] <= checkpoint["cutoff_step"]]
        assert raw["history"] == prefix
        assert checkpoint["prefix_sha256"] == memory._hash(prefix)
        assert checkpoint["full_history_sha256"] == memory._hash(history)
        assert checkpoint["later_row_count"] == len(history) - len(prefix)
        assert "NOT_FINAL" in checkpoint["claim_scope"]
    first = receipt["captures"][0]
    assert not first["receipt"]["succeeded"] and not first["semantic_completion"]
    assert [row["step_no"] for row in first["checkpoint"]["later_mutating_steps"]] == [6, 7, 9, 10]
    assert "Future cleanup summary" not in captures[first["receipt"]["capture_id"]]["summary"]
    terminal = receipt["captures"][-1]
    assert terminal["verification_step"] is None and not terminal["receipt"]["succeeded"]


def test_later_other_subgoal_test_edit_does_not_erase_then_verified_completion(inputs):
    for index in (1, 2):
        checkpoint_captures(inputs, cell(inputs, index, later_subgoal="active"))
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    result = memory._read(learning.ingest_proposals(inputs.root, proposal(inputs, reflection), reflection_reference=reflection)["path"])
    assert result["promotions_added"] == 1
    assert len(memory._read(inputs.root / "catalog.json")["captures"]) == 8
    public = memory._read(reflection["path"])
    assert any(row["tool"] == "replace_text" and row["step_no"] == 9 for row in public["later_mutations"])


def test_command_before_completion_rejects_completion_but_all_test_observations_remain_eligible(inputs):
    for index in (1, 2):
        _, receipt, _ = checkpoint_captures(inputs, cell(inputs, index, before_complete_command=True, later_subgoal="active"))
        completed = next(row for row in receipt["captures"] if row["semantic_completion"])
        assert completed["verification_step"] is None
        assert completed["checkpoint"]["cutoff_step"] == 9
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    rejected_ref = proposal(inputs, reflection)
    result = memory._read(learning.ingest_proposals(inputs.root, rejected_ref, reflection_reference=reflection)["path"])
    assert result["promotions_added"] == 0 and result["outcomes"][0]["status"] == "REJECTED"
    public = memory._read(reflection["path"])
    green = [row for row in public["sources"] if row["checkpoint"]["kind"] == "PUBLIC_TEST_OBSERVATION" and
        row["checkpoint"]["public_test_outcome"] == "GREEN"]
    assert len(green) == 2 and all(not row["semantic_completion"] for row in green)
    value = memory._read(rejected_ref["path"])
    for observation, source in zip(value["proposals"][0]["observations"], green):
        observation["source_alias"] = source["source_alias"]
    accepted_ref = write(inputs.tmp / "checkpoint-proposals.json", value)
    accepted = memory._read(learning.ingest_proposals(inputs.root, accepted_ref, reflection_reference=reflection)["path"])
    assert accepted["promotions_added"] == 1
    assert {row["checkpoint"]["public_test_outcome"] for row in public["sources"]} == {"RED", "GREEN", None}


def test_many_checkpoints_from_one_task_never_supply_independent_gate_b_sources(inputs):
    checkpoint_captures(inputs, cell(inputs, 1))
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    value = memory._read(proposal(inputs, reflection)["path"])
    green = next(row for row in memory._read(reflection["path"])["sources"] if row["checkpoint"]["public_test_outcome"] == "GREEN")
    value["proposals"][0]["observations"].append({**value["proposals"][0]["observations"][0], "source_alias": green["source_alias"]})
    ref = write(inputs.tmp / "same-task-checkpoints.json", value)
    result = memory._read(learning.ingest_proposals(inputs.root, ref, reflection_reference=reflection)["path"])
    assert result["promotions_added"] == 0
    assert "different captured source tasks" in result["outcomes"][0]["reason"]


@pytest.mark.parametrize("response", [
    {"stdout": "2 passed in 0.1s", "stderr": "", "exit_code": 0, "timed_out": False, "output_truncated": True},
    {"stdout": "2 passed in 0.1s", "stderr": "", "exit_code": 0, "timed_out": True, "output_truncated": False},
    {"stdout": "collection error", "stderr": "", "exit_code": 2, "timed_out": False, "output_truncated": False},
])
def test_unverified_commands_never_become_test_observations_and_projection_preserves_their_flags(inputs, response):
    _, receipt, _ = checkpoint_captures(inputs, cell(inputs, 1, complete=False, command_override=response))
    assert len(receipt["captures"]) == 1
    assert receipt["captures"][0]["checkpoint"]["kind"] == "TERMINAL_ACTIVE"
    assert receipt["captures"][0]["verification_step"] is None
    public = memory._read(learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")["path"])
    commands = [row for row in public["trace_rows"] if row["tool"] == "run_command"]
    assert len(commands) == 2 and all(row["result_payload"] == response for row in commands)


def test_projection_fits_large_originals_deduplicates_prefixes_and_verifies_original_read_actions(inputs):
    originals = []
    for index in (1, 2):
        _, _, captures = checkpoint_captures(inputs, cell(inputs, index, read_padding=90000))
        originals.extend(captures.values())
    assert sum(len(canonical_bytes(row["history"])) for row in originals) > 1000000
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    assert Path(reflection["path"]).stat().st_size < learning.MAX_REFLECTION_BYTES
    public = memory._read(reflection["path"])
    assert len(public["trace_rows"]) == 12
    assert sum(len(row["history_row_indices"]) for row in public["sources"]) > len(public["trace_rows"])
    assert all(row["omitted_read_outputs"]["count"] == 2 and row["omitted_read_outputs"]["bytes"] > 180000 for row in public["sources"])
    for row in public["trace_rows"]:
        original = next(item for capture in originals for item in capture["history"] if memory._hash(item) == row["original_row_sha256"])
        assert row["request_payload"] == original["request_payload"]
        if row["tool"] in memory.MUTATING:
            assert row["result_payload"] == original["result_payload"]
    result = memory._read(learning.ingest_proposals(inputs.root, proposal(inputs, reflection), reflection_reference=reflection)["path"])
    assert result["promotions_added"] == 1


@pytest.mark.parametrize("change", ["omit_red", "cutoff", "later_disclosure", "captured_prefix"])
def test_replay_rederives_entire_checkpoint_set_and_original_prefix_despite_resigned_local_metadata(inputs, change):
    ref, receipt, _ = checkpoint_captures(inputs, cell(inputs, 1, later_subgoal="active"))
    if change == "omit_red": receipt["captures"].pop(0)
    if change == "cutoff": receipt["captures"][1]["checkpoint"]["cutoff_step"] = 6
    if change == "later_disclosure": receipt["captures"][1]["checkpoint"]["later_mutating_steps"] = []
    if change == "captured_prefix":
        catalog = memory._read(inputs.root / "catalog.json")
        identity = receipt["captures"][1]["receipt"]["capture_id"]
        capture_path = catalog["captures"][identity]["path"]
        value = memory._read(capture_path)
        value["history"] = value["history"][1:]
        memory._write(capture_path, value)
        catalog["captures"][identity] = memory._ref(capture_path)
        memory._write(inputs.root / "catalog.json", catalog)
    memory._write(ref["path"], receipt)
    registry = memory._read(inputs.root / "learning-state.json")
    registry["cells"][next(iter(registry["cells"]))] = memory._ref(ref["path"])
    memory._write(inputs.root / "learning-state.json", registry)
    with pytest.raises(learning.LearningError, match="checkpoint"):
        learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    assert not (inputs.tmp / "reflection.json").exists()


def test_idempotent_ingest_still_rechecks_original_sealed_sources(inputs):
    paths, _ = captured(inputs)
    reflection = learning.export_reflection(inputs.root, inputs.tmp / "reflection.json")
    proposed = proposal(inputs, reflection)
    learning.ingest_proposals(inputs.root, proposed, reflection_reference=reflection)
    with (paths[0].parent / "broker" / "events.jsonl").open("ab") as stream:
        stream.write(b"changed after ingestion")
    with pytest.raises(memory.ArchitectureMemoryError, match="changed"):
        learning.ingest_proposals(inputs.root, proposed, reflection_reference=reflection)


def test_v2_enrollment_uses_separate_authority_with_same_configs_without_rewriting_previous_files(inputs):
    previous = {path.relative_to(inputs.root): path.read_bytes() for path in inputs.root.rglob("*") if path.is_file()}
    ref = learning.initialize_learning(inputs.tmp / "learning-v2", execution_references=[inputs.execution])
    enrollment = memory._read(ref["path"])
    assert enrollment["learning_version"] == 2 and enrollment["capture_policy"] == learning.CAPTURE_POLICY
    assert enrollment["reflection_projection_policy"] == learning.PROJECTION_POLICY
    assert {path.relative_to(inputs.root): path.read_bytes() for path in inputs.root.rglob("*") if path.is_file()} == previous


@pytest.mark.parametrize("change", ["missing", "duplicate", "event_operation", "event_result", "evidence_steps", "graph_evidence", "same_node_after"])
def test_completion_checkpoint_requires_exact_semantic_event_and_original_evidence(inputs, change):
    path = cell(inputs, 1)
    state = memory._read(path.parent / "broker" / "state.json")
    graph = learning.ShortTermWorkingGraph.from_snapshot(state["graph"])
    history = state["history"]
    events = [learning.broker_module.strict_json_loads(line) for line in (path.parent / "broker" / "events.jsonl").read_bytes().splitlines()]
    completion = history[-1]
    event = next(row for row in events if row.get("history_row") == completion)
    if change == "missing": history.pop()
    if change == "duplicate": history.append({**completion, "step_no": 99})
    if change == "event_operation": event["request"]["request"]["op"] = "tool"
    if change == "event_result": event["response"]["result"]["completed"] = False
    if change == "evidence_steps": event["request"]["request"]["evidence_steps"] = [99]
    if change == "graph_evidence":
        graph.nodes["normalize"].completion_evidence[0] = replace(graph.nodes["normalize"].completion_evidence[0], payload_hash="f" * 64)
    if change == "same_node_after": history.append({**history[0], "step_no": 99})
    with pytest.raises(learning.LearningError, match="completion"):
        learning._checkpoint_specs(graph, history, events, state["submission"])


def test_terminal_active_without_public_rows_is_explicitly_accounted_without_invented_episode(inputs):
    path = cell(inputs, 1, no_attempt="active")
    receipt = memory._read(learning.capture_cell(inputs.root, path)["path"])
    assert receipt["status"] == "NO_PUBLIC_ATTEMPTS" and receipt["source_execution_observed"]
    assert receipt["captures"] == []
    assert receipt["empty_checkpoints"] == [{"node_id": "normalize", "kind": "TERMINAL_ACTIVE", "status": "NO_PUBLIC_ATTEMPTS"}]
    assert not memory._read(inputs.root / "catalog.json")["captures"]


def test_projection_never_truncates_command_results_to_fit_context(inputs):
    command = {"stdout": "1 passed in 0.1s\n" + "x" * 110000, "stderr": "", "exit_code": 0,
        "timed_out": False, "output_truncated": False}
    checkpoint_captures(inputs, cell(inputs, 1, command_override=command))
    with pytest.raises(learning.LearningError, match="never truncate certifying"):
        learning.export_reflection(inputs.root, inputs.tmp / "overflow.json")
    assert not (inputs.tmp / "overflow.json").exists()


def test_existing_v1_authority_cannot_be_upgraded_in_place(inputs):
    root = inputs.tmp / "frozen-v1"
    value = memory._read(inputs.root / "learning-enrollment.json")
    for name in ("learning_version", "capture_policy", "reflection_projection_policy", "claim_scope"):
        value.pop(name)
    path = root / "learning-enrollment.json"
    write(path, value)
    original = path.read_bytes()
    with pytest.raises(learning.LearningError, match="immutable"):
        learning.initialize_learning(root, execution_references=[inputs.execution])
    assert path.read_bytes() == original and list(root.iterdir()) == [path]
