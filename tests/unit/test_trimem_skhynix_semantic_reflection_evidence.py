"""Independent evidence binding and tool-free native adapter checks.

No native worker, solver, grader, or memory publisher runs in these tests.
"""
import copy
import json
from pathlib import Path

import pytest

import trimem_skhynix_architecture_semantic_reflection as grouping


def retain(path, value):
    path.write_bytes(grouping.canonical(value))
    return {"path": str(path), "sha256": grouping.digest(path.read_bytes())}


@pytest.fixture
def inventory(tmp_path):
    items, sources = [], []
    for number in (1, 2):
        task, owner, identity = f"task-{number}", f"owner-{number}", str(number) * 64
        argv = ["python", "-m", "pytest", "test_public.py", "-q"]
        def row(step, tool, arguments, result):
            value = {"step_no": step, "tool": tool, "status": "success", "arm": "PDF_MEMORY",
                    "active_node_id": "repair", "task_id": task,
                    "request_payload": {"tool": tool, "arguments": arguments},
                    "result_payload": result}
            for field in ("request", "result"):
                raw = grouping.canonical(value[field + "_payload"])
                value[field] = {"bytes": len(raw), "sha256": grouping.digest(raw)}
            return value
        edits = [row(2, "replace_text", {"path": "package/code.py",
                 "old_text": "value = narrow\n", "new_text": "value = float(narrow)\n"}, {}),
                 row(3, "replace_text", {"path": "package/code.py",
                 "old_text": "return value\n", "new_text": "return value / count\n"}, {})]
        history = [row(1, "run_command", {"argv": argv, "timeout_seconds": 120},
                   {"exit_code": 1, "timed_out": False, "output_truncated": False,
                    "stdout": "AssertionError: wrong value\n1 failed", "stderr": ""}),
                   *edits, row(4, "run_command", {"argv": argv, "timeout_seconds": 120},
                   {"exit_code": 0, "timed_out": False, "output_truncated": False,
                    "stdout": "1 passed", "stderr": ""})]
        capture = {"schema": "skhynix/native-architecture-training-trace/1.0",
                   "active_node_id": "repair", "owner_user_id": owner,
                   "subgoal": "Promote the narrow operand before arithmetic.",
                   "task": {"task_id": task, "repository": "example/project"},
                   "receipt": {"capture_id": identity, "phase": "TRAINING"},
                   "verification_step": 4, "history": history}
        reference = retain(tmp_path / f"capture-{number}.json", capture)
        sources.append(capture)
        items.append({"capture_id": identity, "capture_reference": reference,
                      "task_id": task, "owner": owner, "repository": "example/project",
                      "subgoal": capture["subgoal"], "red_step": 1, "green_step": 4,
                      "selection_status": "SELECTED", "jobs": [1],
                      "edits": [{"step_no": r["step_no"], "tool": r["tool"],
                                 "status": r["status"], "arguments": r["request_payload"]["arguments"],
                                 "result": r["result_payload"]} for r in edits]})
    plan = {"schema": "skhynix/architecture-scale-reflection-plan/1.0",
            "official_outcomes_used": False,
            "jobs": [{"ordinal": 1, "capture_ids": [r["capture_id"] for r in items]}],
            "skipped_candidates": [],
            "binding": {"source_capture_references": {r["capture_id"]: r["capture_reference"] for r in items}}}
    index = {"schema": "skhynix/public-semantic-edit-diagnostic/1.0",
             "official_outcomes_used": False, "representative_count": 2,
             "plan_reference": retain(tmp_path / "plan.json", plan), "items": items}
    return index, sources, tmp_path / "index.json"


def build(case):
    index, _, path = case
    return grouping.build_input(retain(path, index))


def refresh_capture(case, number=0):
    """Bind deliberate fixture source changes all the way through the plan."""
    index, sources, _ = case
    item, source = index["items"][number], sources[number]
    for row in source["history"]:
        for field in ("request", "result"):
            raw = grouping.canonical(row[field + "_payload"])
            row[field] = {"bytes": len(raw), "sha256": grouping.digest(raw)}
    item["capture_reference"] = retain(Path(item["capture_reference"]["path"]), source)
    plan_path = Path(index["plan_reference"]["path"])
    plan = json.loads(plan_path.read_bytes())
    plan["binding"]["source_capture_references"][item["capture_id"]] = item["capture_reference"]
    index["plan_reference"] = retain(plan_path, plan)


def test_real_requests_are_preserved_as_diffs_without_certification(inventory):
    public, mapping = build(inventory)
    assert len(public["candidates"]) == len(mapping["candidates"]) == 2
    assert public["official_outcomes_used"] is False
    assert "NOT_VERIFICATION_AUTHORITY" in public["projection_scope"]
    for candidate in public["candidates"]:
        assert len(candidate["edits"]) == 2
        assert "-value = narrow" in candidate["edits"][0]["change_unified_diff"]
        assert "+value = float(narrow)" in candidate["edits"][0]["change_unified_diff"]
        assert candidate["edits"][0]["status"] == "success"
        assert candidate["edits"][0]["result_evidence"] == {"sha256": grouping.digest(b"{}"), "bytes": 2}
        assert candidate["edits"][0]["after_sha256"] == grouping.digest(b"value = float(narrow)\n")
    reversed_case = copy.deepcopy(inventory)
    reversed_case[0]["items"].reverse()
    assert build(reversed_case)[0] == public


@pytest.mark.parametrize("target", ["index", "capture", "plan"])
def test_changed_referenced_bytes_are_rejected(inventory, target):
    index, _, path = inventory
    ref = retain(path, index)
    changed = path if target == "index" else Path(index["plan_reference"]["path"] if target == "plan"
                   else index["items"][0]["capture_reference"]["path"])
    changed.write_bytes(changed.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="changed"):
        grouping.build_input(ref)


@pytest.mark.parametrize("field", ["task_id", "owner", "subgoal"])
def test_index_cannot_override_source_metadata(inventory, field):
    inventory[0]["items"][0][field] = "forged"
    with pytest.raises(ValueError, match="metadata differs"):
        build(inventory)


@pytest.mark.parametrize("change", ["tool", "arguments", "phase", "command", "official"])
def test_existing_source_guards_fail_closed(inventory, change):
    index, sources, _ = inventory
    item = index["items"][0]
    if change == "tool": item["edits"][0]["tool"] = "write_file"
    if change == "arguments": item["edits"][0]["arguments"] = {"path": "other.py"}
    if change == "official": index["official_outcomes_used"] = True
    if change in {"phase", "command"}:
        if change == "phase": sources[0]["receipt"]["phase"] = "EVALUATION"
        else: sources[0]["history"][-1]["request_payload"]["arguments"]["timeout_seconds"] = 60
        refresh_capture(inventory)
    with pytest.raises(ValueError):
        build(inventory)


@pytest.mark.parametrize("change", ["missing_candidate", "missing_edit", "reordered_edits", "duplicate_edit",
                                  "repository", "capture_id", "not_red", "not_green", "duplicate_candidate",
                                  "declared_count", "edit_status", "edit_result"])
def test_complete_plan_and_observed_window_must_be_proven(inventory, change):
    index, sources, _ = inventory
    item = index["items"][0]
    if change == "missing_candidate": index["items"].pop()
    if change == "missing_edit": item["edits"].pop()
    if change == "reordered_edits": item["edits"].reverse()
    if change == "duplicate_edit": item["edits"].append(copy.deepcopy(item["edits"][0]))
    if change == "repository": item["repository"] = "forged/project"
    if change == "capture_id": item["capture_id"] = "f" * 64
    if change == "duplicate_candidate": index["items"].append(copy.deepcopy(item))
    if change == "declared_count": index["representative_count"] = 1
    if change == "edit_status": item["edits"][0]["status"] = "error"
    if change == "edit_result": item["edits"][0]["result"] = {"forged": True}
    if change in {"not_red", "not_green"}:
        outcome = sources[0]["history"][0 if change == "not_red" else -1]["result_payload"]
        outcome.update(exit_code=0 if change == "not_red" else 1,
                       stdout="0 tests collected")
        refresh_capture(inventory)
    with pytest.raises(ValueError):
        build(inventory)


@pytest.mark.parametrize("change", ["test_edit", "wrong_node", "later_mutation", "intervening_command",
                                  "duplicate_step", "payload_hash"])
def test_rebound_source_still_needs_a_valid_complete_checkpoint(inventory, change):
    index, sources, _ = inventory
    item, source = index["items"][0], sources[0]
    if change == "test_edit": source["history"][1]["request_payload"]["arguments"]["path"] = "tests/test_public.py"
    if change == "wrong_node": source["history"][1]["active_node_id"] = "other-subgoal"
    if change == "later_mutation":
        later = copy.deepcopy(source["history"][1])
        later["step_no"] = 5
        source["history"].append(later)
    if change == "intervening_command":
        command = copy.deepcopy(source["history"][0])
        command["step_no"] = 4
        source["history"][-1]["step_no"] = item["green_step"] = 5
        source["history"].insert(-1, command)
    if change == "duplicate_step": source["history"][1]["step_no"] = 1
    refresh_capture(inventory)
    if change == "payload_hash":
        source["history"][1]["request"]["sha256"] = "f" * 64
        item["capture_reference"] = retain(Path(item["capture_reference"]["path"]), source)
        plan_path = Path(index["plan_reference"]["path"])
        plan = json.loads(plan_path.read_bytes())
        plan["binding"]["source_capture_references"][item["capture_id"]] = item["capture_reference"]
        index["plan_reference"] = retain(plan_path, plan)
    with pytest.raises(ValueError):
        build(inventory)


def test_failed_attempt_is_retained_with_its_error_not_presented_as_success(inventory):
    index, sources, _ = inventory
    attempt = sources[0]["history"][1]
    attempt["status"] = "error"
    attempt["result_payload"] = {"error": "ToolExecutionError", "message": "Malformed expected hash"}
    index["items"][0]["edits"][0]["status"] = "error"
    index["items"][0]["edits"][0]["result"] = attempt["result_payload"]
    refresh_capture(inventory)
    public, _ = build(inventory)
    edits = public["candidates"][0]["edits"]
    assert [edit["status"] for edit in edits] == ["error", "success"]
    assert edits[0]["error"] == attempt["result_payload"]
    assert edits[0]["result_evidence"] == attempt["result"]
    assert "error" not in edits[1]
    assert "failed attempt, not evidence" in grouping.PROMPT


@pytest.fixture
def fake_native(inventory, tmp_path, monkeypatch):
    public, _ = build(inventory)
    input_ref = retain(tmp_path / "input.json", public)
    output = tmp_path / "output"
    config = {"authentication": "CHATGPT", "model": "gpt-6-astra", "reasoning_effort": "high",
              "codex_binary": "not-executed", "windows_python": "not-executed",
              "input_reference": input_ref, "worker_output": str(output), "worker_cwd": str(tmp_path / "cwd")}
    path = tmp_path / "config.json"
    retain(path, config)
    response = {"schema": grouping.SCHEMA, "input_sha256": input_ref["sha256"], "groups": [],
                "ungrouped": [{"candidate_id": row["candidate_id"], "reason_code": "NO_SEMANTIC_PARTNER",
                               "evidence_note": "No demonstrated common whole repair."} for row in public["candidates"]]}
    record = {"response": response, "saved_response": None, "extra_event": None}
    class Process:
        returncode = 0
        def __init__(self, command, *, stdin, stdout, stderr, env):
            record.update(command=command, env=env)
            self.stdout = stdout
        def communicate(self, prompt, timeout):
            record["prompt"] = prompt
            final = json.dumps(record["response"])
            events = [{"type": "thread.started", "thread_id": "synthetic-thread"},
                      {"type": "turn.started"}]
            if record["extra_event"]: events.append(record["extra_event"])
            events.extend([{"type": "item.completed", "item": {"type": "agent_message", "text": final}},
                           {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}])
            self.stdout.write(b"\n".join(grouping.canonical(row) for row in events))
            self.stdout.flush()
            retain(output / "groups.json", record["saved_response"] or record["response"])
    monkeypatch.setattr(grouping.subprocess, "Popen", Process)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")
    monkeypatch.setenv("CODEX_API_KEY", "synthetic-secret")
    return path, output, record


def test_native_adapter_binds_actual_final_and_leaves_publication_to_verifier(fake_native):
    path, output, record = fake_native
    receipt = grouping.run(path)
    assert receipt["summary"]["verified_skills"] == 0
    assert receipt["validation_required"] is True
    assert receipt["official_grader_runs"] == receipt["memory_writes"] == 0
    assert not {"OPENAI_API_KEY", "CODEX_API_KEY"}.intersection(record["env"])
    assert "--ephemeral" in record["command"] and "--ignore-user-config" in record["command"]
    assert not any(str(arg).startswith("mcp_servers.") for arg in record["command"])
    assert "--output-schema" in record["command"]
    launch = json.loads((output / "launch.json").read_text())
    assert launch["prompt_sha256"] == grouping.digest(record["prompt"])
    assert receipt["response_reference"]["sha256"] == grouping.digest((output / "groups.json").read_bytes())


@pytest.mark.parametrize("change", ["saved_final", "input_binding", "tool_event"])
def test_native_adapter_rejects_unbound_or_tool_using_response(fake_native, change):
    path, output, record = fake_native
    if change == "saved_final":
        record["saved_response"] = copy.deepcopy(record["response"])
        record["saved_response"]["ungrouped"][0]["evidence_note"] = "A different saved reply."
    if change == "input_binding": record["response"]["input_sha256"] = "f" * 64
    if change == "tool_event":
        record["extra_event"] = {"type": "item.completed", "item": {"type": "command_execution"}}
    with pytest.raises(ValueError):
        grouping.run(path)
    assert not (output / "completion.json").exists()
