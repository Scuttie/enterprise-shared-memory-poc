"""Native broker limits and submission integrity, with no API or Docker execution."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import trimem_skhynix_codex as pilot


PATCH = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"


@pytest.fixture
def cell(tmp_path, monkeypatch):
    plan = {
        "schema": pilot.SCHEMA, "experiment_id": "native-test", "cells": dict(pilot.CELLS),
        "source_hashes": {"source.py": "1" * 64},
        "public_task": {"task_id": pilot.TARGET, "repository": "sympy/sympy",
                        "commit": "a" * 40, "instruction": "Fix a public issue"},
        "target": {"target_id": pilot.TARGET, "repository": "sympy/sympy", "base_commit": "a" * 40},
        "limits": {"repository_actions": 120, "wall_seconds": 1200,
                   "memory_injections": 3, "memory_bytes": 12000},
        "requested_solver_model": "gpt-6-astra", "scope": "pilot", "l0_projection": "native",
        "host_isolation": "protocol", "memory_learning": "immutable", "paths": {},
    }
    run = tmp_path / "run"
    root = pilot.cell_root(run, "A")
    root.mkdir(parents=True)
    pilot.write(run / "plan.json", plan)
    (run / "plan.sha256").write_text(pilot.sha(pilot.canonical(plan)) + "\n", encoding="ascii")
    pilot.write(root / "state.json", {"status": "OPEN", "actions": 0, "started_at": None,
                                      "tail_sha256": "0" * 64})
    pilot.write(root / "public-task.json", {"task": plan["public_task"]})
    now = [1000.0]
    calls = []
    workspace = SimpleNamespace(patch=lambda: PATCH,
        execute=lambda name, arguments: {"exit_code": 0, "stdout": "public test passed"},
        grader_context=lambda **kwargs: SimpleNamespace(base_commit=plan["public_task"]["commit"]))
    outcome = SimpleNamespace(official=True, container_started=True, status="success", resolved=True,
        report={"resolved": True}, stdout="tests passed", stderr="", grader_id="mock-official",
        container_digest="image@sha256:" + "a" * 64, wall_time_ms=5)

    def fake_grade(request):
        calls.append(request)
        return outcome

    prepared = SimpleNamespace(grader=SimpleNamespace(grade=fake_grade),
                               workspace_factory=lambda task: workspace)
    env = SimpleNamespace(tasks=(), prepare_cell=lambda *args, **kwargs: prepared)
    monkeypatch.setattr(pilot, "locked", lambda path: nullcontext())
    monkeypatch.setattr(pilot.time, "time", lambda: now[0])
    monkeypatch.setattr(pilot, "source_hashes", lambda: {"source.py": "1" * 64})
    monkeypatch.setattr(pilot, "workspace_for", lambda *args: workspace)
    monkeypatch.setattr(pilot, "environment", lambda *args: env)

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not execute Docker, a model client, or subprocesses")

    monkeypatch.setattr(pilot.subprocess, "run", forbidden)
    return SimpleNamespace(plan=plan, run=run, root=root, now=now, workspace=workspace,
                           calls=calls, outcome=outcome)


def submit(cell):
    response = pilot.perform_action(cell.plan, cell.run, "A", {"op": "submit", "summary": "Fix tested"})
    assert response["ok"], response
    return response


@pytest.fixture
def procedure_cell(cell, monkeypatch):
    """Exercise broker journaling with an offline procedure API stand-in."""
    declaration = {"template": {
        "subgoal_signature": "repair public behavior with regression coverage",
        "parameters": ["source_file", "test_file"],
        "preconditions": ["Inspect {source_file} and {test_file}"],
        "steps": ["Repair {source_file}", "Add regression to {test_file}"],
        "verification_command": "python -m pytest {test_file}",
        "language": "python",
    }}
    declaration_path = cell.run / "procedure.json"
    pilot.write(declaration_path, declaration)
    cell.plan["procedure_declaration"] = pilot.frozen_input(declaration_path)
    cell.plan["public_python"] = "/public/python"
    cell.workspace.patch = lambda: ""
    bindings = {"source_file": "source.py", "test_file": "tests/test_source.py"}
    captures = []

    def load_declaration(path, digest, target_id):
        assert target_id == cell.plan["public_task"]["task_id"]
        assert pilot.sha(path.read_bytes()) == digest
        return pilot.read(path)

    def validate_bindings(value, requested, public_python):
        assert value == declaration and public_python == "/public/python"
        assert requested == bindings
        return dict(requested)

    def capture_workspace(workspace, bound):
        assert bound == bindings
        snapshot = {"patch_sha256": pilot.sha(workspace.patch().encode()),
                    "files": {path: pilot.sha(path.encode()) for path in bound.values()}}
        captures.append(deepcopy(snapshot))
        return snapshot

    module = SimpleNamespace(load_declaration=load_declaration,
                             validate_bindings=validate_bindings,
                             capture_workspace=capture_workspace)
    monkeypatch.setitem(sys.modules, "trimem_skhynix_codex_procedures", module)
    cell.procedure = module
    cell.bindings = bindings
    cell.captures = captures
    cell.declaration_path = declaration_path
    return cell


def bind_procedure(cell):
    return pilot.perform_action(cell.plan, cell.run, "A",
                                {"op": "begin_procedure", "bindings": cell.bindings})


def test_procedure_begin_after_inspection_has_auditable_binding(procedure_cell):
    cell = procedure_cell
    assert pilot.perform_action(cell.plan, cell.run, "A", {"op": "info"})["ok"]
    assert pilot.perform_action(cell.plan, cell.run, "A", {
        "op": "tool", "name": "read_file", "arguments": {"path": "source.py"}})["ok"]
    response = bind_procedure(cell)
    assert response["ok"], response
    binding = pilot.read(cell.root / "procedure-binding.json")
    events, _ = pilot.audit_events(cell.root)
    assert binding == events[-1]["result"]["result"] == response["result"]
    assert binding["sequence"] == 3
    assert binding["bindings"] == cell.bindings
    assert binding["declaration_sha256"] == cell.plan["procedure_declaration"]["sha256"]
    original = (cell.root / "procedure-binding.json").read_bytes()
    repeated = bind_procedure(cell)
    assert not repeated["ok"] and "already frozen" in repeated["error"]
    assert (cell.root / "procedure-binding.json").read_bytes() == original
    assert len(pilot.audit_events(cell.root)[0]) == 4


@pytest.mark.parametrize("name", ["write_file", "replace_text", "run_command"])
def test_procedure_cannot_bind_after_mutating_tools_even_if_clean(procedure_cell, name):
    cell = procedure_cell
    assert pilot.perform_action(cell.plan, cell.run, "A", {
        "op": "tool", "name": name, "arguments": {}})["ok"]
    assert cell.workspace.patch() == ""
    response = bind_procedure(cell)
    assert not response["ok"] and "before the first edit or command" in response["error"]
    assert not (cell.root / "procedure-binding.json").exists()
    assert len(pilot.audit_events(cell.root)[0]) == 2


def test_procedure_cannot_bind_dirty_checkout(procedure_cell):
    cell = procedure_cell
    cell.workspace.patch = lambda: PATCH
    response = bind_procedure(cell)
    assert not response["ok"] and "clean initial checkout" in response["error"]
    assert not (cell.root / "procedure-binding.json").exists()


def test_procedure_rejects_binding_file_changed_after_journal(procedure_cell):
    cell = procedure_cell
    assert bind_procedure(cell)["ok"]
    path = cell.root / "procedure-binding.json"
    binding = pilot.read(path)
    binding["bindings"]["source_file"] = "different.py"
    pilot.write(path, binding)
    executed = []
    cell.workspace.execute = lambda *args: executed.append(args) or {"exit_code": 0}
    response = pilot.perform_action(cell.plan, cell.run, "A", {
        "op": "tool", "name": "run_command", "arguments": {"argv": ["/public/python"]}})
    assert not response["ok"] and "original journal receipt" in response["error"]
    assert executed == []
    assert len(pilot.audit_events(cell.root)[0]) == 2


def test_procedure_declaration_tamper_fails_before_binding(procedure_cell):
    cell = procedure_cell
    cell.declaration_path.write_text("{}", encoding="utf-8")
    response = bind_procedure(cell)
    assert not response["ok"] and "Frozen input bytes changed" in response["error"]
    assert not (cell.root / "procedure-binding.json").exists()


@pytest.fixture(params=["2", "3"])
def actual_named_cell(cell, tmp_path, request):
    import difflib
    import trimem_skhynix_codex_procedures as procedures
    declaration = cell.run / "named-procedure.json"
    procedures.declare_procedure(declaration, cell.plan["experiment_id"],
        [cell.plan["public_task"]["task_id"], "fixture-other-training-task"], request.param)
    cell.procedure_version = request.param
    cell.plan["procedure_declaration"] = pilot.frozen_input(declaration)
    cell.plan["public_python"] = "/public/python"
    checkout = tmp_path / "public-checkout"
    originals = {"pkg/logic.py": "def scaled(x):\n    return x\n",
        "pkg/tests/test_logic.py": "def test_existing():\n    assert True\n",
        "bin/test": "# synthetic public runner\n"}
    if request.param == "3":
        originals["pkg/other.py"] = "def other(x):\n    return x\n"
    for relative, content in originals.items():
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def patch():
        lines = []
        for relative, content in sorted(originals.items()):
            current = (checkout / relative).read_text(encoding="utf-8")
            if current != content:
                lines.append(f"diff --git a/{relative} b/{relative}\n")
                lines.extend(difflib.unified_diff(content.splitlines(keepends=True), current.splitlines(keepends=True),
                    fromfile="a/" + relative, tofile="b/" + relative))
        return "".join(lines)

    cell.workspace.root = checkout
    cell.workspace.patch = patch
    cell.originals = originals
    cell.bindings = {"source_path": "pkg/logic.py", "test_path": "pkg/tests/test_logic.py",
        "test_name": "test_fresh", "test_argv": pilot.canonical([
            "/public/python", "bin/test", "pkg/tests/test_logic.py", "--no-colors", "--no-subprocess",
            "-k", "test_fresh"]).decode()}
    if request.param == "3":
        cell.bindings.pop("source_path")
        cell.bindings["source_paths"] = '["pkg/logic.py","pkg/other.py"]'
    return cell


def test_broker_real_named_binding_records_fresh_ast_and_prebound_sources_before_commands(actual_named_cell):
    response = bind_procedure(actual_named_cell)
    assert response["ok"], response
    snapshot = response["result"]["workspace_snapshot"]
    assert snapshot["schema"] == f"skhynix/public-procedure-workspace/{actual_named_cell.procedure_version}.0"
    assert snapshot["named_regression"]["bound_name_present"] is False
    assert snapshot["named_regression"]["matching_definitions"] == []
    assert response["result"]["bindings"] == actual_named_cell.bindings
    if actual_named_cell.procedure_version == "3":
        assert set(snapshot["source_file_sha256"]) == {"pkg/logic.py", "pkg/other.py"}
        assert snapshot["source_sha256"] == pilot.sha(pilot.canonical(snapshot["source_file_sha256"]))


def test_failed_named_binding_validation_is_journaled_without_freezing_a_receipt(actual_named_cell):
    cell = actual_named_cell
    original = dict(cell.bindings)
    cell.bindings.pop("test_name")
    response = bind_procedure(cell)
    assert response["ok"] is False
    assert response["error_type"] == "ProcedureEvidenceError"
    assert "result" not in response
    assert not (cell.root / "procedure-binding.json").exists()
    assert cell.workspace.patch() == ""
    cell.bindings = original
    response = bind_procedure(cell)
    assert response["ok"] is True
    assert response["result"]["sequence"] == 2
    assert pilot.read(cell.root / "state.json")["actions"] == 2
    assert pilot.read(cell.root / "procedure-binding.json") == response["result"]


@pytest.mark.parametrize("base", ["test_fresh = 1\n", "import os as test_fresh\n",
    "def test_fresh_extra():\n    assert True\n"])
def test_broker_rejects_colliding_named_binding_before_receipt_creation(actual_named_cell, base):
    cell = actual_named_cell
    path = cell.bindings["test_path"]
    cell.originals[path] = base
    (cell.workspace.root / path).write_text(base, encoding="utf-8")
    assert cell.workspace.patch() == ""
    response = bind_procedure(cell)
    assert not response["ok"] and "fresh" in response["error"]
    assert not (cell.root / "procedure-binding.json").exists()


def test_named_binding_cannot_be_added_after_any_public_command(actual_named_cell):
    cell = actual_named_cell
    response = pilot.perform_action(cell.plan, cell.run, "A", {"op": "tool", "name": "run_command",
        "arguments": {"argv": ["/public/python", "--version"]}})
    assert response["ok"]
    response = bind_procedure(cell)
    assert not response["ok"] and "before the first edit or command" in response["error"]


def test_procedure_snapshot_failure_does_not_seal_submission(procedure_cell):
    cell = procedure_cell
    assert bind_procedure(cell)["ok"]

    def fail_capture(*args):
        raise ValueError("Cannot capture procedure evidence")

    cell.procedure.capture_workspace = fail_capture
    response = pilot.perform_action(cell.plan, cell.run, "A", {"op": "submit", "summary": "Done"})
    assert not response["ok"] and "Cannot capture" in response["error"]
    assert pilot.read(cell.root / "state.json")["status"] == "OPEN"
    assert not (cell.root / "submission.json").exists()
    assert not (cell.root / "submission.diff").exists()
    assert len(pilot.audit_events(cell.root)[0]) == 2


def test_procedure_command_receipt_captures_before_and_after_execution(procedure_cell):
    cell = procedure_cell
    assert bind_procedure(cell)["ok"]
    capture_counts = []

    def execute(name, arguments):
        capture_counts.append(len(cell.captures))
        return {"exit_code": 0, "stdout": "public test passed"}

    cell.workspace.execute = execute
    response = pilot.perform_action(cell.plan, cell.run, "A", {
        "op": "tool", "name": "run_command",
        "arguments": {"argv": ["/public/python", "-m", "pytest", cell.bindings["test_file"]]}})
    assert response["ok"], response
    assert capture_counts == [2] and len(cell.captures) == 3
    result = response["result"]
    assert result["procedure_snapshot_before"] == cell.captures[1]
    assert result["procedure_snapshot"] == cell.captures[2]
    assert result["procedure_snapshot_before"] == result["procedure_snapshot"]
    assert pilot.audit_events(cell.root)[0][-1]["result"] == response


def test_procedure_missing_bound_file_cannot_disable_submission_snapshot(procedure_cell):
    cell = procedure_cell
    assert bind_procedure(cell)["ok"]
    (cell.root / "procedure-binding.json").unlink()
    response = pilot.perform_action(cell.plan, cell.run, "A", {"op": "submit", "summary": "Done"})
    assert not response["ok"] and "binding file is missing" in response["error"]
    assert pilot.read(cell.root / "state.json")["status"] == "OPEN"
    assert not (cell.root / "submission.json").exists()
    assert not (cell.root / "submission.diff").exists()
    assert len(pilot.audit_events(cell.root)[0]) == 2


def test_procedure_patch_change_between_capture_and_seal_leaves_cell_open(procedure_cell):
    cell = procedure_cell
    assert bind_procedure(cell)["ok"]
    capture = cell.procedure.capture_workspace

    def capture_then_change(workspace, bindings):
        snapshot = capture(workspace, bindings)
        workspace.patch = lambda: PATCH
        return snapshot

    cell.procedure.capture_workspace = capture_then_change
    response = pilot.perform_action(cell.plan, cell.run, "A", {"op": "submit", "summary": "Done"})
    assert not response["ok"] and "snapshot and submitted patch differ" in response["error"]
    assert pilot.read(cell.root / "state.json")["status"] == "OPEN"
    assert not (cell.root / "submission.json").exists()
    assert not (cell.root / "submission.diff").exists()
    assert len(pilot.audit_events(cell.root)[0]) == 2
    # The failed seal did not consume the one allowed submission.
    cell.procedure.capture_workspace = capture
    response = submit(cell)
    assert response["result"]["patch_sha256"] == pilot.sha(PATCH.encode())
    assert pilot.read(cell.root / "state.json")["status"] == "SUBMITTED"


def test_submit_counts_as_final_allowed_action_and_seals(cell):
    for _ in range(119):
        assert pilot.perform_action(cell.plan, cell.run, "A", {"op": "info"})["ok"]
    response = submit(cell)
    assert response["budget"]["actions_remaining"] == 0
    state = pilot.read(cell.root / "state.json")
    assert state["actions"] == 120 and state["status"] == "SUBMITTED"
    assert pilot.read(cell.root / "submission.json")["actions"] == 120
    assert len(pilot.audit_events(cell.root)[0]) == 120
    before = (cell.root / "submission.diff").read_bytes()
    with pytest.raises(ValueError, match="sealed"):
        pilot.perform_action(cell.plan, cell.run, "A", {"op": "submit", "summary": "again"})
    assert (cell.root / "submission.diff").read_bytes() == before


@pytest.mark.parametrize("action", [{"op": "info"}, {"op": "submit", "summary": "late"}])
def test_exhausted_action_budget_rejects_without_receipt_or_submission(cell, action):
    for _ in range(120):
        pilot.perform_action(cell.plan, cell.run, "A", {"op": "info"})
    before = (cell.root / "state.json").read_bytes()
    with pytest.raises(ValueError, match="LIMIT"):
        pilot.perform_action(cell.plan, cell.run, "A", action)
    assert (cell.root / "state.json").read_bytes() == before
    assert not (cell.root / "submission.json").exists()


@pytest.mark.parametrize("op", ["info", "submit"])
def test_wall_limit_also_blocks_submit(cell, op):
    pilot.perform_action(cell.plan, cell.run, "A", {"op": "info"})
    cell.now[0] += 1200
    with pytest.raises(ValueError, match="LIMIT"):
        pilot.perform_action(cell.plan, cell.run, "A", {"op": op, "summary": "late"})
    assert pilot.read(cell.root / "state.json")["actions"] == 1
    assert not (cell.root / "submission.json").exists()


def test_command_timeout_is_capped_to_remaining_wall_budget(cell):
    pilot.perform_action(cell.plan, cell.run, "A", {"op": "info"})
    cell.now[0] += 1195
    seen = []
    cell.workspace.execute = lambda name, args: seen.append(args) or {"exit_code": 0}
    result = pilot.perform_action(cell.plan, cell.run, "A", {
        "op": "tool", "name": "run_command",
        "arguments": {"argv": ["python", "test.py"], "timeout_seconds": 120},
    })
    assert result["ok"] and seen[0]["timeout_seconds"] == 5
    assert result["result"]["effective_timeout_seconds"] == 5


def test_failed_tool_consumes_budget_and_has_auditable_receipt(cell):
    result = pilot.perform_action(cell.plan, cell.run, "A",
        {"op": "tool", "name": "official_grader", "arguments": {}})
    assert not result["ok"] and result["budget"]["actions_remaining"] == 119
    events, _ = pilot.audit_events(cell.root)
    assert len(events) == 1 and not events[0]["result"]["ok"]
    assert not cell.calls


def test_pending_action_cannot_be_silently_resumed(cell):
    state = pilot.read(cell.root / "state.json")
    state["pending"] = "unreceipted-mutation"
    pilot.write(cell.root / "state.json", state)
    with pytest.raises(ValueError, match="receipt|receipts|pending"):
        pilot.perform_action(cell.plan, cell.run, "A", {"op": "info"})
    assert pilot.read(cell.root / "state.json") == state


@pytest.mark.parametrize("field,value", [
    ("schema", "wrong"), ("source_hashes", {"source.py": "changed"}),
    ("cells", {"A": "SKHYNIX"}),
])
def test_load_plan_rejects_changed_source_and_identity(cell, field, value):
    changed = deepcopy(cell.plan)
    changed[field] = value
    pilot.write(cell.run / "plan.json", changed)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(changed)), encoding="ascii")
    with pytest.raises(ValueError):
        pilot.load_plan(cell.run)


@pytest.mark.parametrize("field,value", [
    ("repository_actions", 121), ("wall_seconds", 1201),
    ("memory_injections", 4), ("memory_bytes", 12001),
])
def test_load_plan_rejects_relaxed_frozen_limits(cell, field, value):
    changed = deepcopy(cell.plan)
    changed["limits"][field] = value
    pilot.write(cell.run / "plan.json", changed)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(changed)), encoding="ascii")
    with pytest.raises(ValueError):
        pilot.load_plan(cell.run)


def test_plan_digest_detects_changed_task_instruction(cell):
    assert pilot.load_plan(cell.run) == cell.plan
    changed = deepcopy(cell.plan)
    changed["public_task"]["instruction"] = "A different issue"
    pilot.write(cell.run / "plan.json", changed)
    with pytest.raises(ValueError, match="plan changed"):
        pilot.load_plan(cell.run)


def test_nondefault_target_and_experiment_roundtrip_through_grade(cell):
    target_id = "swebench_verified--django__django-16100"
    cell.plan["experiment_id"] = "skhynix-native-codex-002-django"
    cell.plan["solver_user_id"] = "native-training:django-16100"
    cell.plan["public_task"].update(task_id=target_id, repository="django/django")
    cell.plan["target"].update(target_id=target_id, repository="django/django")
    pilot.write(cell.run / "plan.json", cell.plan)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(cell.plan)), encoding="ascii")
    assert pilot.load_plan(cell.run) == cell.plan
    task = pilot.task_from_plan(cell.plan)
    assert task.user_id == "native-training:django-16100"
    assert task.org_id == cell.plan["experiment_id"]
    submit(cell)
    result = pilot.grade(cell.plan, cell.run, "A")
    assert cell.calls[0].task_id == target_id
    assert result["target_id"] == target_id
    assert result["experiment_id"] == cell.plan["experiment_id"]
    report = pilot.report(cell.plan, cell.run)
    assert report["target_id"] == target_id
    assert report["experiment_id"] == cell.plan["experiment_id"]


@pytest.mark.parametrize("field,value", [
    ("target_id", "swebench_verified--another-target"),
    ("repository", "another/repository"), ("base_commit", "b" * 40),
])
def test_plan_rejects_public_task_mismatching_frozen_target(cell, field, value):
    cell.plan["target"][field] = value
    pilot.write(cell.run / "plan.json", cell.plan)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(cell.plan)), encoding="ascii")
    with pytest.raises(ValueError, match="target.*identity"):
        pilot.load_plan(cell.run)


@pytest.mark.parametrize("key,prefix", [
    ("frozen_memory_bank", "frozen_bank"), ("supplemental_manifest", "supplemental_manifest"),
])
def test_frozen_input_file_change_invalidates_plan_before_actions(cell, key, prefix):
    path = cell.run / f"{key}.json"
    path.write_text('{"frozen":true}', encoding="utf-8")
    cell.plan[key] = pilot.frozen_input(path)
    pilot.write(cell.run / "plan.json", cell.plan)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(cell.plan)), encoding="ascii")
    assert pilot.load_plan(cell.run) == cell.plan
    kwargs = pilot.frozen_input_kwargs(cell.plan, key, prefix)
    assert kwargs[f"{prefix}_path"] == path.resolve()
    assert kwargs[f"{prefix}_sha256"] == cell.plan[key]["sha256"]
    path.write_text('{"frozen":false}', encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen input bytes changed"):
        pilot.load_plan(cell.run)
    assert pilot.read(cell.root / "state.json")["actions"] == 0


def test_recall_passes_frozen_bank_and_solver_scope_to_bridge(cell, monkeypatch):
    bank = cell.run / "learned-bank.json"
    bank.write_text('{"bank":"training"}', encoding="utf-8")
    cell.plan["frozen_memory_bank"] = pilot.frozen_input(bank)
    cell.plan["solver_user_id"] = "native-contributor-002"
    calls = []
    bridge = SimpleNamespace(recall_memory=lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    monkeypatch.setitem(sys.modules, "trimem_skhynix_codex_memory", bridge)
    query = {"node_id": "fix", "objective": "Repair behavior", "operation": "edit"}
    response = pilot.perform_action(cell.plan, cell.run, "A", {"op": "recall", "query": query})
    assert response["ok"]
    args, kwargs = calls[0]
    assert args[1].user_id == "native-contributor-002" and args[3] == query
    assert kwargs == {"frozen_bank_path": bank.resolve(), "frozen_bank_sha256": pilot.sha(bank.read_bytes())}


def test_prepare_rejects_unknown_target_before_workspace_or_memory_creation(tmp_path, monkeypatch):
    import trimem_skhynix_codex_memory as memory
    import trimem_skhynix_source_bank as source_bank
    calls = []
    monkeypatch.setattr(pilot.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="a" * 40))
    monkeypatch.setattr(pilot, "source_hashes", lambda: {})
    monkeypatch.setattr(pilot, "environment", lambda *args: SimpleNamespace(
        tasks=(), targets_by_id={}, prepare_cell=lambda *a, **kw: calls.append("workspace")))
    monkeypatch.setattr(memory, "initialize_memory", lambda *a, **kw: calls.append("memory"))
    monkeypatch.setattr(source_bank, "load_validated_source_bank", lambda: calls.append("bank"))
    args = SimpleNamespace(run_root=tmp_path / "run", workspace_root=tmp_path / "work",
        dataset_cache_root=tmp_path / "datasets", harness_root=tmp_path / "harnesses",
        loader_preflight_path=None, public_python="python", target_id="unknown-target",
        experiment_id="native-new-experiment", solver_user_id="native-training-user")
    with pytest.raises(ValueError, match="known prepared dataset task"):
        pilot.prepare(args)
    assert calls == []
    assert not (args.run_root / "plan.json").exists()


@pytest.mark.parametrize("cold_start", [False, True])
@pytest.mark.parametrize("runtime", [None, "matching", "wrong_image"])
@pytest.mark.parametrize("procedure_version", [None, "1", "2", "3"])
def test_prepare_selects_one_known_target_and_binds_bank_to_all_cells(tmp_path, monkeypatch, cold_start, runtime, procedure_version):
    from enterprise_memory.trimem.agent_runtime import CodingTask
    target_id = "swebench_verified--sympy__sympy-23534"
    selected = CodingTask(target_id, "old-org", "old-user", "sympy/sympy", "b" * 40,
                          "A new public issue", {}, ())
    unrelated = CodingTask(pilot.TARGET, "old-org", "old-user", "sympy/sympy", "a" * 40,
                           "The original issue", {}, ())
    args = SimpleNamespace(run_root=tmp_path / "run", workspace_root=tmp_path / "work",
        dataset_cache_root=tmp_path / "datasets", harness_root=tmp_path / "harnesses",
        loader_preflight_path=None, public_python="/environment/python",
        target_id=target_id, experiment_id="native-learned-002", solver_user_id="training-contributor-2",
        frozen_memory_bank=tmp_path / "bank.json", supplemental_manifest=tmp_path / "manifest.json")
    pilot.write(args.frozen_memory_bank, {"cold_start": cold_start})
    args.supplemental_manifest.write_text('{"targets":["23534"]}', encoding="utf-8")
    if procedure_version is not None:
        import trimem_skhynix_codex_procedures as procedures
        args.procedure_declaration = tmp_path / "declared-procedure.json"
        procedures.declare_procedure(args.procedure_declaration, args.experiment_id,
            [target_id, "fixture-other-training-task"], procedure_version)
    calls = []
    runner = SimpleNamespace(image="image@sha256:" + "a" * 64, masked_image_files=(),
                             masked_image_directories=(), content_hash="b" * 64)

    def prepare_cell(arm, task):
        calls.append(("prepare", arm, task))
        workspace = SimpleNamespace(root=args.workspace_root / arm, command_runner=runner)
        return SimpleNamespace(workspace_factory=lambda task: workspace)

    def initialize_memory(root, task, arm, repository_root, **kwargs):
        calls.append(("memory", arm, task, kwargs))
        return {"status": "READY"}

    env = SimpleNamespace(tasks=(unrelated, selected), prepare_cell=prepare_cell,
        targets_by_id={target_id: {"target_id": target_id, "repository": "sympy/sympy",
                                   "base_commit": selected.commit}})
    monkeypatch.setattr(pilot.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="a" * 40))
    monkeypatch.setattr(pilot, "source_hashes", lambda: {})
    monkeypatch.setattr(pilot, "environment", lambda *args: env)
    monkeypatch.setitem(sys.modules, "trimem_skhynix_codex_memory",
                        SimpleNamespace(initialize_memory=initialize_memory))
    monkeypatch.setitem(sys.modules, "trimem_skhynix_source_bank", SimpleNamespace(
        load_validated_source_bank=lambda: pytest.fail("Learned bank must not be described as historical")))
    if runtime is not None:
        certificate = {"source_image": runner.image if runtime == "matching" else "another-image"}
        monkeypatch.setattr(pilot, "workflow_runtime_certificate", lambda plan: certificate)
    if runtime == "wrong_image":
        with pytest.raises(ValueError, match="certificate differs from the prepared image"):
            pilot.prepare(args)
        assert [call[0] for call in calls] == ["prepare"]
        assert not (args.run_root / "plan.json").exists()
        assert not (pilot.cell_root(args.run_root, "A") / "workspace.json").exists()
        return
    pilot.prepare(args)
    plan = pilot.load_plan(args.run_root)
    assert plan["public_task"] == selected.public_payload()
    assert plan["experiment_id"] == args.experiment_id
    assert plan["solver_user_id"] == args.solver_user_id
    assert plan["source_bank"]["kind"] == ("FROZEN_COLD_START_EMPTY_BANK" if cold_start else "FROZEN_LEARNED_BANK")
    assert ("no learned records" in plan["memory_learning"]) is cold_start
    assert env.tasks[0] == unrelated
    assert env.tasks[1].org_id == args.experiment_id and env.tasks[1].user_id == args.solver_user_id
    assert [call[1] for call in calls if call[0] == "prepare"] == list(pilot.CELLS.values())
    expected_kwargs = {"frozen_bank_path": args.frozen_memory_bank.resolve(),
                       "frozen_bank_sha256": pilot.sha(args.frozen_memory_bank.read_bytes())}
    for call in calls:
        assert call[2].task_id == target_id and call[2].user_id == args.solver_user_id
        if call[0] == "memory":
            assert call[3] == expected_kwargs
    for cell_name in pilot.CELLS:
        root = pilot.cell_root(args.run_root, cell_name)
        packet = pilot.read(root / "public-task.json")
        assert packet["target_id"] == target_id and packet["solver_user_id"] == args.solver_user_id
        if procedure_version == "3":
            assert packet["procedure_guidance"] == procedures.MULTI_SOURCE_PUBLIC_INSTRUCTIONS
            assert packet["training_procedure"]["template_hash"] == procedures.MULTI_SOURCE_TEMPLATE.content_hash
        elif procedure_version == "2":
            assert packet["procedure_guidance"] == procedures.NAMED_PUBLIC_INSTRUCTIONS
            assert packet["training_procedure"]["template_hash"] == procedures.NAMED_TEMPLATE.content_hash
        elif procedure_version == "1":
            assert "source_path, test_path and canonical JSON test_argv" in packet["procedure_guidance"]
            assert packet["training_procedure"]["template_hash"] == procedures.TEMPLATE.content_hash
        assert packet["public_python"] == "/environment/python"
        assert "sympy" not in packet["test_guidance"].lower()
        assert pilot.read(root / "workspace.json")["plan_sha256"] == pilot.sha(pilot.canonical(plan))


@pytest.fixture
def runtime_cell(cell, monkeypatch):
    bank_path = cell.run / "runtime-bank.json"
    pilot.write(bank_path, {"schema": "skhynix/native-learned-bank/2.0"})
    cell.plan["frozen_memory_bank"] = pilot.frozen_input(bank_path)
    cell.plan["public_python"] = "/verified/python"
    certificate = {"python_executable": "/verified/python", "source_image": "image@sha256:" + "c" * 64}
    validated_bank = object()
    calls = []

    def load_bank(path, digest, task):
        assert path == bank_path and digest == pilot.sha(path.read_bytes())
        assert task.task_id == cell.plan["public_task"]["task_id"]
        calls.append("validated_bank")
        return validated_bank

    def runtime_certificate(bank):
        assert bank is validated_bank
        calls.append("certificate")
        return certificate

    monkeypatch.setitem(sys.modules, "trimem_skhynix_codex_learning",
                        SimpleNamespace(load_frozen_bank=load_bank))
    monkeypatch.setitem(sys.modules, "trimem_skhynix_codex_skill_bank",
                        SimpleNamespace(runtime_certificate_for_bank=runtime_certificate))
    pilot.write(cell.run / "plan.json", cell.plan)
    digest = pilot.sha(pilot.canonical(cell.plan))
    (cell.run / "plan.sha256").write_text(digest, encoding="ascii")
    for name in pilot.CELLS:
        pilot.write(pilot.cell_root(cell.run, name) / "workspace.json",
                    {"plan_sha256": digest, "image": certificate["source_image"]})
    cell.certificate = certificate
    cell.runtime_calls = calls
    return cell


def test_runtime_certificate_uses_validated_bank_and_all_cell_identity(runtime_cell):
    cell = runtime_cell
    assert pilot.workflow_runtime_certificate(cell.plan) == cell.certificate
    assert cell.runtime_calls == ["validated_bank", "certificate"]
    assert pilot.load_plan(cell.run) == cell.plan
    assert cell.runtime_calls == ["validated_bank", "certificate"] * 2


@pytest.mark.parametrize("name", list(pilot.CELLS))
@pytest.mark.parametrize("field", ["image", "plan_sha256"])
def test_runtime_certificate_rejects_changed_cell_config_before_workspace_access(runtime_cell, monkeypatch, name, field):
    cell = runtime_cell
    path = pilot.cell_root(cell.run, name) / "workspace.json"
    config = pilot.read(path)
    config[field] = "changed"
    pilot.write(path, config)
    monkeypatch.setattr(pilot, "workspace_for", lambda *args: pytest.fail("No tools before runtime validation"))
    with pytest.raises(ValueError, match="certificate differs from the frozen cell runtime"):
        pilot.load_plan(cell.run)


def test_runtime_certificate_rejects_changed_public_python(runtime_cell):
    cell = runtime_cell
    cell.plan["public_python"] = "/different/python"
    pilot.write(cell.run / "plan.json", cell.plan)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(cell.plan)), encoding="ascii")
    with pytest.raises(ValueError, match="declared public Python"):
        pilot.load_plan(cell.run)


@pytest.mark.parametrize("schema", [None, "skhynix/native-learned-bank/1.0"])
def test_runtime_certificate_preserves_no_bank_and_legacy_plans(cell, monkeypatch, schema):
    if schema:
        path = cell.run / "legacy-bank.json"
        pilot.write(path, {"schema": schema})
        cell.plan["frozen_memory_bank"] = pilot.frozen_input(path)
    pilot.write(cell.run / "plan.json", cell.plan)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(cell.plan)), encoding="ascii")
    monkeypatch.setitem(sys.modules, "trimem_skhynix_codex_learning", SimpleNamespace(
        load_frozen_bank=lambda *args: pytest.fail("Legacy plan must not require runtime certificate")))
    assert pilot.workflow_runtime_certificate(cell.plan) is None
    assert pilot.load_plan(cell.run) == cell.plan


def test_environment_passes_bound_supplemental_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "supplemental.json"
    manifest.write_text('{"schema":"supplemental"}', encoding="utf-8")
    plan = {"supplemental_manifest": pilot.frozen_input(manifest),
            "paths": {"workspace_root": "work", "dataset_cache_root": "datasets", "harness_root": "harness"}}
    calls = []
    monkeypatch.setitem(sys.modules, "trimem_skhynix_environment", SimpleNamespace(
        prepare_local_environment=lambda **kwargs: calls.append(kwargs) or "prepared"))
    assert pilot.environment(plan, tmp_path / "run") == "prepared"
    assert calls[0]["supplemental_manifest_path"] == manifest.resolve()
    assert calls[0]["supplemental_manifest_sha256"] == pilot.sha(manifest.read_bytes())


@pytest.mark.parametrize("value", ["", "../outside", "a/b", "a" * 129, None])
def test_invalid_experiment_id_is_rejected(value):
    with pytest.raises(ValueError, match="Experiment ID"):
        pilot.validate_experiment_id(value)


@pytest.mark.parametrize("mutation", ["content", "truncate", "state_tail", "pending"])
def test_event_audit_detects_tampering(cell, mutation):
    pilot.perform_action(cell.plan, cell.run, "A", {"op": "info"})
    events = cell.root / "tool-events.jsonl"
    if mutation == "content":
        events.write_bytes(events.read_bytes().replace(b'"op":"info"', b'"op":"diff"'))
    elif mutation == "truncate":
        events.write_bytes(b"")
    else:
        state = pilot.read(cell.root / "state.json")
        state["tail_sha256" if mutation == "state_tail" else "pending"] = "bad"
        pilot.write(cell.root / "state.json", state)
    with pytest.raises(ValueError):
        pilot.audit_events(cell.root)


def test_grade_uses_sealed_patch_and_is_idempotent(cell):
    submit(cell)
    first = pilot.grade(cell.plan, cell.run, "A")
    assert first["official"] and first["agent_completed"]
    assert cell.calls[0].patch == PATCH and len(cell.calls) == 1
    assert pilot.grade(cell.plan, cell.run, "A") == first
    assert len(cell.calls) == 1


@pytest.mark.parametrize("tamper", ["plan", "patch", "checkout", "cell", "state"])
def test_grade_rejects_changed_submission_before_invoking_grader(cell, tamper):
    submit(cell)
    if tamper == "patch":
        (cell.root / "submission.diff").write_text(PATCH + "changed", encoding="utf-8")
    elif tamper == "checkout":
        cell.workspace.patch = lambda: PATCH + "changed"
    elif tamper == "state":
        state = pilot.read(cell.root / "state.json")
        state["status"] = "OPEN"
        pilot.write(cell.root / "state.json", state)
    else:
        submission = pilot.read(cell.root / "submission.json")
        submission["plan_sha256" if tamper == "plan" else "cell"] = "changed"
        pilot.write(cell.root / "submission.json", submission)
    with pytest.raises(ValueError):
        pilot.grade(cell.plan, cell.run, "A")
    assert not cell.calls


def test_existing_grade_result_still_requires_plan_binding(cell):
    submit(cell)
    pilot.grade(cell.plan, cell.run, "A")
    result = pilot.read(cell.root / "public-result.json")
    result["plan_sha256"] = "changed"
    pilot.write(cell.root / "public-result.json", result)
    with pytest.raises(ValueError):
        pilot.grade(cell.plan, cell.run, "A")
    assert len(cell.calls) == 1


def test_failed_grade_cannot_be_automatically_retried(cell):
    submit(cell)
    cell.outcome.status = "harness_failure"
    with pytest.raises(RuntimeError):
        pilot.grade(cell.plan, cell.run, "A")
    assert not (cell.root / "public-result.json").exists()
    with pytest.raises(ValueError, match="recovery|duplicate"):
        pilot.grade(cell.plan, cell.run, "A")
    assert len(cell.calls) == 1


def test_manager_sealed_empty_partial_is_explicitly_labeled(cell):
    from enterprise_memory.trimem.agent_runtime import CANONICAL_FAILED_CELL_NOOP
    cell.workspace.patch = lambda: ""
    state = pilot.read(cell.root / "state.json")
    pilot.seal_submission(cell.plan, cell.run, "A", state, summary="Partial", agent_completed=False)
    pilot.write(cell.root / "state.json", state)
    result = pilot.grade(cell.plan, cell.run, "A")
    assert result["agent_completed"] is False
    assert result["patch_utf8_bytes"] == 0
    assert result["grader_patch_source"] == "CANONICAL_FAILED_CELL_NOOP"
    assert cell.calls[0].patch == CANONICAL_FAILED_CELL_NOOP


def test_report_excludes_unpaired_results_from_comparison(cell):
    submit(cell)
    pilot.grade(cell.plan, cell.run, "A")
    result = pilot.report(cell.plan, cell.run)
    assert result["completed_cells"] == 1 and result["status"] == "INCOMPLETE"
    assert result["fully_paired_targets"] == 0 and result["comparison"] is None


def test_report_rejects_result_from_another_plan(cell):
    submit(cell)
    pilot.grade(cell.plan, cell.run, "A")
    result = pilot.read(cell.root / "public-result.json")
    result["plan_sha256"] = "wrong-plan"
    pilot.write(cell.root / "public-result.json", result)
    with pytest.raises(ValueError):
        pilot.report(cell.plan, cell.run)


@pytest.mark.parametrize("field", ["target_id", "experiment_id"])
def test_report_rejects_result_from_another_target_or_experiment(cell, field):
    submit(cell)
    pilot.grade(cell.plan, cell.run, "A")
    result = pilot.read(cell.root / "public-result.json")
    result[field] = "different"
    pilot.write(cell.root / "public-result.json", result)
    with pytest.raises(ValueError):
        pilot.report(cell.plan, cell.run)


def test_native_guard_disables_paid_gateway_without_constructing_client(monkeypatch):
    calls = []
    fake = SimpleNamespace(build_paid_model_gateway=lambda *a, **k: calls.append("paid"))
    monkeypatch.setitem(sys.modules, "trimem_benchmark_run", fake)
    # Synthetic sentinel only; this test never reads or uses an actual credential.
    monkeypatch.setenv("OPENAI_API_KEY", "test-sentinel-unused")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")
    pilot.block_model_client()
    assert "OPENAI_API_KEY" not in pilot.os.environ
    with pytest.raises(RuntimeError, match="DIRECT_MODEL_API_DISABLED"):
        fake.build_paid_model_gateway()
    assert calls == []
