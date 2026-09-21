"""Real Gate A/B over synthetic broker fixtures; no solver, grader or command execution."""
from copy import deepcopy
import difflib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import trimem_skhynix_codex_procedures as procedures


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(procedures.canonical(value) + b"\n")


@pytest.fixture
def declaration(tmp_path):
    path = tmp_path / "declaration.json"
    receipt = procedures.declare_procedure(path, "training-authority", ["fixture-task-one", "fixture-task-two"])
    return path, receipt


def make_training(tmp_path, declaration, index=1, *, source_paths=None, repaired_paths=None):
    declaration_path, reference = declaration
    declared = procedures.load_declaration(declaration_path, reference["sha256"])
    profile = procedures.procedure_profile(declared["procedure_id"])
    multi_source = declared["procedure_id"] == procedures.MULTI_SOURCE_PROCEDURE_ID
    named = declared["procedure_id"] in (procedures.NAMED_PROCEDURE_ID, procedures.MULTI_SOURCE_PROCEDURE_ID)
    root = tmp_path / f"run-{index}"
    cell = root / "cells/A"
    checkout = tmp_path / f"checkout-{index}"
    source_path, test_path = "pkg/logic.py", "pkg/tests/test_logic.py"
    base_source = "def scaled(x):\n    return x\n"
    base_test = "from pkg.logic import scaled\n\ndef test_existing():\n    assert scaled(0) == 0\n"
    files = {source_path: base_source, test_path: base_test, "bin/test": "# public test runner\n"}
    source_paths = source_paths or ([source_path, "pkg/other.py"] if multi_source else [source_path])
    repaired_paths = source_paths if repaired_paths is None else repaired_paths
    for relative in source_paths:
        files.setdefault(relative, "def other(x):\n    return x\n")
    for relative, content in files.items():
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def patch():
        value = []
        for relative, base in sorted(files.items()):
            current = (checkout / relative).read_text()
            if current != base:
                value.append(f"diff --git a/{relative} b/{relative}\n")
                value.extend(difflib.unified_diff(base.splitlines(keepends=True), current.splitlines(keepends=True),
                                                fromfile="a/" + relative, tofile="b/" + relative))
        return "".join(value)

    workspace = SimpleNamespace(root=checkout, patch=patch)
    argv = ["/opt/python", "bin/test", test_path, "--no-colors", "--no-subprocess"]
    if named:
        argv.extend(("-k", "test_scaling_regression"))
    bindings = {"source_path": source_path, "test_path": test_path,
                "test_argv": procedures.canonical(argv).decode()}
    if named:
        bindings["test_name"] = "test_scaling_regression"
    if multi_source:
        bindings.pop("source_path")
        bindings["source_paths"] = procedures.canonical(source_paths).decode()
    task_id = "fixture-task-one" if index == 1 else "fixture-task-two"
    plan = {"experiment_id": "training-authority", "solver_user_id": f"native-session-{index}",
        "public_task": {"task_id": task_id, "repository": "example/repository", "commit": str(index) * 40,
                        "instruction": "Fix public integer scaling regression"},
        "public_python": "/opt/python", "cells": {"A": "NO_MEMORY"},
        "procedure_declaration": {"path": str(declaration_path.resolve()), "sha256": reference["sha256"]}}
    write(root / "plan.json", plan)
    plan_hash = procedures.sha(procedures.canonical(plan))
    (root / "plan.sha256").write_text(plan_hash)
    events = []

    def event(request, result):
        sequence = len(events) + 1
        events.append({"sequence": sequence, "time": 1000 + sequence, "request": request,
                       "result": {"ok": True, "result": result}})

    for relative in (*source_paths, test_path):
        event({"op": "tool", "name": "read_file", "arguments": {"path": relative}}, {"content": files[relative]})
    receipt = {"declaration_sha256": reference["sha256"], "template_hash": profile["template"].content_hash,
               "bindings": bindings, "sequence": len(events) + 1,
               "workspace_snapshot": procedures.capture_workspace(workspace, bindings)}
    event({"op": "begin_procedure", "bindings": bindings}, receipt)
    write(cell / "procedure-binding.json", receipt)
    regression = "\ndef test_scaling_regression():\n    assert scaled(1) == 2\n"
    (checkout / test_path).write_text(base_test + regression)
    event({"op": "tool", "name": "replace_text", "arguments": {"path": test_path,
        "old_text": base_test, "new_text": base_test + regression}},
        {"path": test_path, "procedure_snapshot": procedures.capture_workspace(workspace, bindings)})
    red_snapshot = procedures.capture_workspace(workspace, bindings)
    red_result = {"exit_code": 1, "stdout": "test_scaling_regression\nAssertionError: assert scaled(1) == 2\n1 passed, 1 failed",
                  "procedure_snapshot_before": red_snapshot, "procedure_snapshot": red_snapshot}
    if named:
        line = red_snapshot["named_regression"]["matching_definitions"][0]["direct_assert_lines"][0]
        red_result.update(named_result(argv, red=True, line=line))
    event({"op": "tool", "name": "run_command", "arguments": {"argv": argv}}, red_result)
    for relative in repaired_paths:
        repaired = files[relative].replace("return x", "return 2*x")
        (checkout / relative).write_text(repaired)
        event({"op": "tool", "name": "replace_text", "arguments": {"path": relative,
            "old_text": files[relative], "new_text": repaired}},
            {"path": relative, "procedure_snapshot": procedures.capture_workspace(workspace, bindings)})
    green_snapshot = procedures.capture_workspace(workspace, bindings)
    green_result = {"exit_code": 0, "stdout": "2 passed", "procedure_snapshot_before": green_snapshot,
                    "procedure_snapshot": green_snapshot}
    if named:
        green_result.update(named_result(argv))
    event({"op": "tool", "name": "run_command", "arguments": {"argv": argv}}, green_result)
    patch_bytes = workspace.patch().encode()
    patch_hash = procedures.sha(patch_bytes)
    event({"op": "submit", "summary": "Fixed scaling and verified regression"},
        {"status": "SUBMITTED", "patch_sha256": patch_hash, "procedure_snapshot": green_snapshot})
    common = {"cell": "A", "arm": "NO_MEMORY", "target_id": task_id, "plan_sha256": plan_hash,
              "patch_sha256": patch_hash, "patch_utf8_bytes": len(patch_bytes), "actions": len(events),
              "agent_completed": True}
    (cell / "submission.diff").write_bytes(patch_bytes)
    (cell / "grader-private.json").write_bytes(b"RESTRICTED_GRADER_CONTENT_NOT_EXPORTED")
    write(cell / "submission.json", {**common, "submitted_at": 1010,
                                      "summary": "Fixed scaling and verified regression"})
    write(cell / "public-result.json", {**common, "official": True, "grader_status": "success", "resolved": True,
        "separate_model_api_calls": 0, "grader_private_sha256": procedures.file_sha(cell / "grader-private.json")})
    fixture = SimpleNamespace(root=root, cell=cell, checkout=checkout, workspace=workspace, bindings=bindings,
                              events=events, declaration_path=declaration_path, declaration_sha256=reference["sha256"])
    rechain(fixture)
    return fixture


def named_result(argv, *, red=False, line=7):
    """Synthetic complete public-runner result; never executes a command."""
    if red:
        text = (f"{argv[2]}[1] F                                      [FAIL]\n"
            f'Traceback (most recent call last):\n  File "/testbed/{argv[2]}", line {line}, in {argv[-1]}\n'
            "    assert scaled(1) == 2\nAssertionError\n"
            "================== tests finished: 1 failed, in 0.01 seconds ===================\nDO *NOT* COMMIT!\n")
    else:
        text = (f"{argv[2]}[1] .                                      [OK]\n"
            "================== tests finished: 1 passed, in 0.01 seconds ===================\n")
    return {"argv": argv, "cwd": ".", "exit_code": int(red), "stdout": text, "stderr": "",
            "timed_out": False, "output_truncated": False}


def rechain(fixture):
    tail, rows = "0" * 64, []
    for sequence, event in enumerate(fixture.events, 1):
        event["sequence"] = sequence
        event["previous_sha256"] = tail
        tail = procedures.sha(procedures.canonical(event))
        rows.append({**event, "sha256": tail})
    (fixture.cell / "tool-events.jsonl").write_bytes(b"\n".join(procedures.canonical(row) for row in rows) + b"\n")
    for name in ("public-result.json", "submission.json"):
        value = procedures.read(fixture.cell / name)
        value["actions"] = len(rows)
        if name == "public-result.json":
            value["tool_event_tail_sha256"] = tail
        write(fixture.cell / name, value)
    write(fixture.cell / "state.json", {"status": "SUBMITTED", "actions": len(rows), "tail_sha256": tail})


@pytest.fixture
def training(tmp_path, declaration):
    return make_training(tmp_path, declaration)


def attest(training):
    return procedures.attest_procedure(training.root, "A", training.declaration_path, training.declaration_sha256)


def result(training, sequence):
    return training.events[sequence - 1]["result"]["result"]


def test_actual_gate_a_and_gate_b_promote_verified_stages_from_two_sessions(tmp_path, declaration):
    first, second = make_training(tmp_path, declaration, 1), make_training(tmp_path, declaration, 2)
    first_attestation = attest(first)
    stages = first_attestation["attestation"]["stages"]
    assert [row["broker_sequences"] for row in stages] == [[1, 2], [4], [5], [6], [7]]
    assert first_attestation["episode_evidence"]["procedure_hash"] == procedures.TEMPLATE.content_hash
    assert first_attestation["episode_evidence"]["revision"] == "1" * 40
    output = procedures.promote_and_export(declaration[0], declaration[1]["sha256"],
        [{"run_root": str(first.root), "cell": "A"}, {"run_root": str(second.root), "cell": "A"}], tmp_path / "authority")
    export = procedures.read(Path(output["path"]))
    assert output["support_count"] == output["contributor_count"] == 2
    assert export["status"] == "ACTUALLY_PROMOTED_BY_GATE_B"
    assert procedures.sha(export["public_execution_view"].encode()) == export["public_execution_view_sha256"]
    assert "native-session-1" not in export["public_execution_view"]
    assert "fixture-task-one" not in export["public_execution_view"]
    assert "pkg/logic.py" not in export["public_execution_view"]
    assert "episode_evidence" not in export and "RESTRICTED_GRADER_CONTENT" not in json.dumps(export)
    assert export["target_fix_validated"] is False and export["source_revisions_rebound"] is False
    with procedures.SkillMemoryStore(export["authority_db"]["path"]) as store:
        original = store.snapshot(org_id="training-authority", user_id="nobody", repository="example/repository", revision="", language="python")
        assert len(original.skills) == 1 and original.skills[0].content_hash == export["promoted_skill"]["content_hash"]
        # The existing core version gate is unchanged; portability needs the separate new adapter.
        target = store.snapshot(org_id="training-authority", user_id="nobody", repository="example/repository", revision="a" * 40, language="python")
        assert not target.skills


@pytest.mark.parametrize("mutation,match", [
    ("no_assertion", "no genuine"), ("infra_error", "no genuine"), ("wrong_regression", "no genuine"),
    ("red_no_failure_count", "no genuine"), ("red_source_changed", "no genuine"),
    ("red_extra_path", "no genuine"), ("red_decorated", "no genuine"),
    ("red_old_test", "no genuine"), ("red_command_mutates", "RED command"),
    ("green_command_mutates", "GREEN command"), ("green_test_changed", "no identical"),
    ("green_argv_changed", "no identical"), ("green_has_failures", "no identical"),
    ("green_no_passed", "no identical"), ("no_inspection", "not inspected"),
    ("final_patch_changed", "GREEN workspace"),
])
def test_outcome_labels_cannot_replace_required_broker_evidence(training, mutation, match):
    red, green, final = result(training, 5), result(training, 7), result(training, 8)
    if mutation == "no_assertion":
        red["stdout"] = "test_scaling_regression\n1 failed"
    elif mutation == "infra_error":
        red["stdout"] += "\nModuleNotFoundError: missing optional package"
    elif mutation == "wrong_regression":
        red["stdout"] = "test_existing\nAssertionError\n1 failed"
    elif mutation == "red_no_failure_count":
        red["stdout"] = "test_scaling_regression\nAssertionError"
    elif mutation == "red_source_changed":
        red["procedure_snapshot"]["source_sha256"] = "e" * 64
    elif mutation == "red_extra_path":
        red["procedure_snapshot"]["changed_paths"].append("pkg/other.py")
    elif mutation == "red_decorated":
        next(row for row in red["procedure_snapshot"]["test_functions"] if row["name"] == "test_scaling_regression")["decorator_count"] = 1
    elif mutation == "red_old_test":
        next(row for row in red["procedure_snapshot"]["test_functions"] if row["name"] == "test_scaling_regression")["name"] = "test_existing"
    elif mutation == "red_command_mutates":
        red["procedure_snapshot_before"] = {**red["procedure_snapshot"], "patch_sha256": "e" * 64}
    elif mutation == "green_command_mutates":
        green["procedure_snapshot_before"] = {**green["procedure_snapshot"], "patch_sha256": "e" * 64}
    elif mutation == "green_test_changed":
        green["procedure_snapshot"]["test_sha256"] = "e" * 64
    elif mutation == "green_argv_changed":
        training.events[6]["request"]["arguments"]["argv"] = ["/opt/python", "-c", "print('2 passed')"]
    elif mutation == "green_has_failures":
        green["stdout"] += ", 1 failed"
    elif mutation == "green_no_passed":
        green["stdout"] = "success"
    elif mutation == "no_inspection":
        training.events[0]["request"]["name"] = "search"
    elif mutation == "final_patch_changed":
        final["procedure_snapshot"] = {**green["procedure_snapshot"], "patch_sha256": "e" * 64}
    rechain(training)
    with pytest.raises(procedures.ProcedureEvidenceError, match=match):
        attest(training)


def test_binding_must_precede_first_command_even_if_failed(training):
    training.events[0]["request"] = {"op": "tool", "name": "run_command", "arguments": {"argv": ["false"]}}
    training.events[0]["result"] = {"ok": False, "error": "rejected"}
    rechain(training)
    with pytest.raises(procedures.ProcedureEvidenceError, match="preceded"):
        attest(training)


def test_binding_is_joined_to_exact_persistent_and_original_journal_receipt(training):
    path = training.cell / "procedure-binding.json"
    value = procedures.read(path)
    value["bindings"]["source_path"] = "pkg/other.py"
    write(path, value)
    with pytest.raises(procedures.ProcedureEvidenceError, match="binding journal"):
        attest(training)


@pytest.mark.parametrize("which", ["same_task", "same_session"])
def test_independence_requires_real_distinct_task_and_native_session_ids(tmp_path, declaration, which):
    first, second = make_training(tmp_path, declaration, 1), make_training(tmp_path, declaration, 2)
    if which == "same_task":
        second = first
    else:
        plan = procedures.read(second.root / "plan.json")
        plan["solver_user_id"] = "native-session-1"
        write(second.root / "plan.json", plan)
        digest = procedures.sha(procedures.canonical(plan))
        (second.root / "plan.sha256").write_text(digest)
        for name in ("submission.json", "public-result.json"):
            write(second.cell / name, {**procedures.read(second.cell / name), "plan_sha256": digest})
    with pytest.raises(procedures.ProcedureEvidenceError, match="distinct tasks"):
        procedures.promote_and_export(declaration[0], declaration[1]["sha256"],
            [{"run_root": str(first.root), "cell": "A"}, {"run_root": str(second.root), "cell": "A"}], tmp_path / "authority")
    assert not (tmp_path / "authority").exists()


@pytest.mark.parametrize("changes", [{"source_path": "../escape.py"}, {"source_path": "/abs.py"},
    {"source_path": "pkg/tests/test_logic.py"}, {"test_path": "pkg/not_a_test.py"},
    {"extra": "not-a-parameter"}, {"test_argv": "[]"}])
def test_binding_refuses_wrong_scope_or_runner(declaration, changes):
    value = procedures.load_declaration(declaration[0], declaration[1]["sha256"])
    bindings = {"source_path": "pkg/logic.py", "test_path": "pkg/tests/test_logic.py", "test_argv":
        procedures.canonical(["/opt/python", "bin/test", "pkg/tests/test_logic.py", "--no-colors", "--no-subprocess"]).decode()}
    with pytest.raises(procedures.ProcedureEvidenceError):
        procedures.validate_bindings(value, {**bindings, **changes}, "/opt/python")


def test_declaration_cannot_be_rewritten_after_binding(declaration):
    declaration[0].write_bytes(declaration[0].read_bytes() + b"\n")
    with pytest.raises(procedures.ProcedureEvidenceError, match="hash differs"):
        procedures.load_declaration(declaration[0], declaration[1]["sha256"])


def test_capture_reads_full_public_files_without_exporting_source_or_test_text(training):
    snapshot = procedures.capture_workspace(training.workspace, training.bindings)
    assert snapshot["test_sha256"] == procedures.file_sha(training.checkout / training.bindings["test_path"])
    assert "scaled(1)" not in json.dumps(snapshot)
    assert "return 2*x" not in json.dumps(snapshot)
    regression = next(row for row in snapshot["test_functions"] if row["name"] == "test_scaling_regression")
    assert regression["assertion_count"] == 1 and regression["decorator_count"] == 0


def test_missing_command_snapshot_fails_closed(training):
    result(training, 5).pop("procedure_snapshot")
    rechain(training)
    with pytest.raises(procedures.ProcedureEvidenceError, match="lacks actual workspace"):
        attest(training)


@pytest.fixture
def named_declaration(tmp_path):
    path = tmp_path / "named-declaration.json"
    receipt = procedures.declare_procedure(path, "training-authority",
        ["fixture-task-one", "fixture-task-two"], procedure_version="2")
    return path, receipt


@pytest.fixture
def named_training(tmp_path, named_declaration):
    return make_training(tmp_path, named_declaration)


def test_default_v1_declaration_preserves_historical_canonical_bytes(tmp_path):
    path = tmp_path / "historical-contract.json"
    receipt = procedures.declare_procedure(path, "skhynix-native-codex-005-training",
        ["swebench_verified--sympy__sympy-19637", "swebench_verified--sympy__sympy-19783"])
    assert receipt["sha256"] == "33a2a7641f77cf8b93afe003d59c1c1e88d1749ff70fb28cdd6b07fcdc06e687"
    assert procedures.TEMPLATE.content_hash == "sha256:fbd4d54981d3b80e328fe8665a0706364a035a7c5d00953b8840436736701b03"


def test_named_contract_is_separately_versioned_and_not_a_v1_filter_override(named_training, declaration):
    value = procedures.load_declaration(named_training.declaration_path, named_training.declaration_sha256)
    assert value["schema"] == procedures.NAMED_SCHEMA
    assert value["template_hash"] == procedures.NAMED_TEMPLATE.content_hash != procedures.TEMPLATE.content_hash
    assert procedures.validate_bindings(value, named_training.bindings, "/opt/python") == named_training.bindings
    old = procedures.load_declaration(declaration[0], declaration[1]["sha256"])
    with pytest.raises(procedures.ProcedureEvidenceError):
        procedures.validate_bindings(old, named_training.bindings, "/opt/python")
    with pytest.raises(procedures.ProcedureEvidenceError):
        procedures.validate_bindings(old, {key: value for key, value in named_training.bindings.items()
            if key != "test_name"}, "/opt/python")


@pytest.mark.parametrize("field,value", [("schema", procedures.SCHEMA),
    ("procedure_id", "unknown-v3"), ("template_hash", procedures.TEMPLATE.content_hash),
    ("observation_contract", {})])
def test_named_declaration_cannot_downgrade_or_change_contract(named_declaration, field, value):
    path, _ = named_declaration
    document = procedures.read(path)
    document[field] = value
    write(path, document)
    with pytest.raises(procedures.ProcedureEvidenceError):
        procedures.load_declaration(path, procedures.file_sha(path))


def test_actual_named_gate_a_b_requires_two_observed_officially_successful_tasks(tmp_path, named_declaration):
    first, second = make_training(tmp_path, named_declaration), make_training(tmp_path, named_declaration, 2)
    verified = attest(first)["attestation"]
    assert verified["schema"] == procedures.NAMED_ATTESTATION_SCHEMA
    assert verified["regression_names"] == ["test_scaling_regression"]
    assert verified["public_test_passed_counts"] == [1]
    receipt = procedures.promote_and_export(named_declaration[0], named_declaration[1]["sha256"],
        [{"run_root": str(item.root), "cell": "A"} for item in (first, second)], tmp_path / "named-authority")
    export = procedures.read(Path(receipt["path"]))
    assert export["schema"] == procedures.NAMED_EXPORT_SCHEMA
    assert export["procedure_id"] == procedures.NAMED_PROCEDURE_ID
    assert export["promoted_skill"]["template"]["parameters"] == list(procedures.NAMED_TEMPLATE.parameters)
    assert receipt["support_count"] == receipt["contributor_count"] == 2
    assert "test_scaling_regression" not in export["public_execution_view"]


@pytest.mark.parametrize("suffix", [
    "def test_new(*args):\n    assert False\n",
    "def test_new(**kwargs):\n    assert False\n",
    "async def test_new():\n    assert False\n",
    "def test_new():\n    assert False\n    yield 1\n",
    "def test_new():\n    def helper():\n        assert False\n",
    "@skip\ndef test_new():\n    assert False\n",
    "def test_new():\n    assert False\ndef test_new():\n    assert True\n",
    "def test_new():\n    assert False\ndef test_new_extra():\n    assert True\n",
    "import os\ndef test_new():\n    assert False\n",
])
def test_named_selection_rejects_unexecuted_ambiguous_or_extra_module_nodes(suffix):
    original = b"def test_existing():\n    assert True\n\n"
    base = {"named_regression": procedures._named_module(original, "test_new")}
    current = {"named_regression": procedures._named_module(original + suffix.encode(), "test_new")}
    assert procedures._named_addition(base, current, "test_new") is None


@pytest.mark.parametrize("original", [b"test_new = 1\n", b"import os as test_new\n",
    b"def test_new_extra():\n    assert True\n", b"class test_new:\n    pass\n"])
def test_named_binding_rejects_existing_bindings_aliases_and_substring_collisions(original):
    with pytest.raises(procedures.ProcedureEvidenceError, match="fresh"):
        procedures.validate_named_base({"named_regression": procedures._named_module(original, "test_new")}, "test_new")


def test_named_regression_cannot_delete_or_suppress_existing_public_tests():
    base = {"named_regression": procedures._named_module(b"def test_old():\n    assert False\n", "test_new")}
    current = {"named_regression": procedures._named_module(
        b"def test_old():\n    assert True\ndef test_new():\n    assert False\n", "test_new")}
    assert procedures._named_addition(base, current, "test_new") is None


@pytest.mark.parametrize("stage,mutation", [
    (5, "wrong_assert_line"), (5, "wrong_assert_function"), (5, "helper_assertion"),
    (5, "raised_instead_of_assert"), (5, "no_collection"), (5, "extra_exception"),
    (7, "two_tests"), (7, "loose_pass_text"), (7, "contradictory_summary"),
    (7, "skipped"), (7, "xfail"), (7, "wrong_result_argv"), (7, "wrong_result_cwd"),
    (7, "timeout"), (7, "truncated"), (7, "missing_flag"),
])
def test_named_attestation_rejects_incomplete_or_unattributed_command_evidence(named_training, stage, mutation):
    response = result(named_training, stage)
    if mutation in ("wrong_assert_line", "raised_instead_of_assert"):
        response["stdout"] = response["stdout"].replace("line 7,", "line 8,")
    elif mutation == "wrong_assert_function":
        response["stdout"] = response["stdout"].replace("in test_scaling_regression", "in test_existing")
    elif mutation == "helper_assertion":
        response["stdout"] = response["stdout"].replace('File "/testbed/pkg/tests/test_logic.py"', 'File "/testbed/pkg/logic.py"')
    elif mutation == "no_collection":
        response["stdout"] = response["stdout"].split("\n", 1)[1]
    elif mutation == "extra_exception":
        response["stdout"] += "\nTypeError: unexpected failure\n"
    elif mutation == "two_tests":
        response["stdout"] = response["stdout"].replace("[1] .", "[2] ..").replace("1 passed", "2 passed")
    elif mutation == "loose_pass_text":
        response["stdout"] = "1 passed"
    elif mutation == "contradictory_summary":
        response["stdout"] += "\ntests finished: 1 failed, in 0.01 seconds\n"
    elif mutation in ("skipped", "xfail"):
        response["stdout"] = response["stdout"].replace("1 passed", "1 skipped" if mutation == "skipped" else "1 expected to fail")
    elif mutation == "wrong_result_argv":
        response["argv"] = ["echo", "1 passed"]
    elif mutation == "wrong_result_cwd":
        response["cwd"] = "elsewhere"
    elif mutation == "timeout":
        response["timed_out"] = True
    elif mutation == "truncated":
        response["output_truncated"] = True
    else:
        response.pop("output_truncated")
    rechain(named_training)
    with pytest.raises(procedures.ProcedureEvidenceError):
        attest(named_training)


def test_named_green_never_substitutes_for_official_resolution(named_training):
    path = named_training.cell / "public-result.json"
    public = procedures.read(path)
    public["resolved"] = False
    write(path, public)
    with pytest.raises(ValueError, match="official resolution"):
        attest(named_training)


@pytest.mark.parametrize("diagnostic", ["ValueError or TypeError", "ImportError", "SyntaxError"])
def test_direct_assertion_message_may_describe_a_caught_bug_exception(named_training, diagnostic):
    red = result(named_training, 5)
    red["stdout"] = red["stdout"].replace("AssertionError\n", f"AssertionError: unexpected {diagnostic}\n")
    rechain(named_training)
    assert attest(named_training)["attestation"]["status"] == "VERIFIED"


def test_source_can_be_repaired_after_earlier_green_and_verified_again(named_training):
    training = named_training
    second_write = deepcopy(training.events[5])
    second_green = deepcopy(training.events[6])
    training.events[-1:-1] = [second_write, second_green]
    rechain(training)
    verified = attest(training)["attestation"]
    assert verified["stages"][-1]["broker_sequences"] == [9]
    assert verified["stages"][-2]["broker_sequences"] == [6, 8]


def actual_public_named_result(*, red):
    """Exact public output projection from native006/19637-a2; no execution.

    RED event 10: ff69983a69f25591839817ac98812ae352e81d9c5fbae4ef0774cd084697ba6e
    GREEN event 16: cd4b5a35f4e143f2aa3a4bee491b1f490a0f5b433ad834b99c8f70655e001927
    These are observer bugfix fixtures, never retrospective training admission.
    """
    test = "sympy/core/tests/test_sympify.py"
    name = "test_kernS_parenthesized_without_kernel_19637_regression"
    argv = ["/opt/miniconda3/envs/testbed/bin/python", "bin/test", test,
        "--no-colors", "--no-subprocess", "-k", name]
    text = (
        "============================= test process starts ==============================\n"
        "executable:         /opt/miniconda3/envs/testbed/bin/python  (3.9.20-final-0) [CPython]\n"
        "architecture:       64-bit\ncache:              yes\nground types:       python \n"
        "numpy:              None\nrandom seed:        " + ("13690073" if red else "77361771") +
        "\nhash randomization: off\n\n")
    if red:
        text += (
            "sympy/core/tests/test_sympify.py[1] F                                     [FAIL]\n\n"
            "________________________________________________________________________________\n"
            f" {test}:{name} \nTraceback (most recent call last):\n"
            f'  File "/testbed/{test}", line 773, in {name}\n'
            "    assert result == 2*x/(x - 1)\nAssertionError\n\n"
            "============= tests finished: 0 passed, 1 failed, in 0.06 seconds ==============\n"
            "DO *NOT* COMMIT!\n")
    else:
        text += (
            "sympy/core/tests/test_sympify.py[1] .                                       [OK]\n\n"
            "================== tests finished: 1 passed, in 0.06 seconds ===================\n")
    return {"argv": argv, "cwd": ".", "exit_code": int(red), "stdout": text, "stderr": "",
            "timed_out": False, "output_truncated": False}


@pytest.mark.parametrize("red,digest", [
    (True, "4063442577b5e7e9a7d312749e4b96b9616dd44551eb0ea1e7a9a09a030271d3"),
    (False, "25c24fb0e94ba494e65c1c7d29c837a31323a604e6791b0788e1ec43368d67c9"),
])
def test_real_public_red_green_receipt_projection_is_recognized_without_rewriting(red, digest):
    response = actual_public_named_result(red=red)
    assert procedures.sha(procedures.canonical(response)) == digest
    assert procedures.named_runner_outcome(response, response["argv"], red=red,
        test_name=response["argv"][-1], assertion_lines=[773, 774, 775, 776, 777, 778])


@pytest.mark.parametrize("summary", [
    "0 passed, 0 failed", "1 passed, 1 failed", "0 passed, 2 failed", "1 failed, 0 passed",
    "0 passed, 1 failed, 0 passed", "0 passed, 1 failed, 0 skipped",
    "0 passed, 1 failed, 0 exceptions", "0 passed, 1 failed, 0 expected to fail",
])
def test_real_red_footer_rejects_wrong_repeated_or_extra_outcomes(summary):
    response = actual_public_named_result(red=True)
    response["stdout"] = response["stdout"].replace("0 passed, 1 failed", summary)
    assert not procedures.named_runner_outcome(response, response["argv"], red=True,
        test_name=response["argv"][-1], assertion_lines=[773])


@pytest.mark.parametrize("extra", [
    "0 passed\n", "1 failed\n", "tests finished: 1 failed, in 0.01 seconds\n",
    "tests finished: incomplete output\n", "pkg/tests/test_other.py[1] . [OK]\n",
    "sympy/core/tests/test_sympify.py[1] F [FAIL]\n",
])
def test_real_red_footer_rejects_stray_counts_and_multiple_collections(extra):
    response = actual_public_named_result(red=True)
    response["stdout"] += extra
    assert not procedures.named_runner_outcome(response, response["argv"], red=True,
        test_name=response["argv"][-1], assertion_lines=[773])


def insert_binding_attempt(training, *, after=False, response=None):
    begin = next(event for event in training.events if event["request"]["op"] == "begin_procedure")
    attempt = {"request": {"op": "begin_procedure", "bindings": {}},
        "result": response if response is not None else {"ok": False,
            "error_type": "ProcedureEvidenceError",
            "error": "bindings must contain exactly the declared procedure parameters"}}
    training.events.insert(training.events.index(begin) + int(after), attempt)
    begin["result"]["result"]["sequence"] = training.events.index(begin) + 1
    write(training.cell / "procedure-binding.json", begin["result"]["result"])
    rechain(training)


def test_named_binding_allows_only_noop_validation_retry_before_the_success(named_training):
    insert_binding_attempt(named_training)
    verified = attest(named_training)["attestation"]
    assert verified["status"] == "VERIFIED"
    assert verified["stages"][2]["broker_sequences"] == [6]


def test_v1_does_not_reinterpret_historical_multiple_binding_events(training):
    insert_binding_attempt(training)
    with pytest.raises(procedures.ProcedureEvidenceError, match="exactly one"):
        attest(training)


@pytest.mark.parametrize("response", [
    {"ok": False, "error_type": "ValueError", "error": "not a validation failure"},
    {"ok": False, "error": "missing type"},
    {"ok": 0, "error_type": "ProcedureEvidenceError", "error": "ambiguous flag"},
    {"ok": 1, "result": {}}, {"ok": True, "result": {}},
    {"ok": False, "error_type": "ProcedureEvidenceError", "error": ""},
    {"ok": False, "error_type": "ProcedureEvidenceError", "error": 123},
    {"ok": False, "error_type": "ProcedureEvidenceError", "error": "bad", "result": {}},
    {"ok": False, "error_type": "ProcedureEvidenceError", "error": "bad", "result": None},
])
def test_named_binding_does_not_ignore_ambiguous_or_state_bearing_failures(named_training, response):
    insert_binding_attempt(named_training, response=response)
    with pytest.raises(procedures.ProcedureEvidenceError):
        attest(named_training)


def test_named_binding_rejects_even_validation_failures_after_success(named_training):
    insert_binding_attempt(named_training, after=True)
    with pytest.raises(procedures.ProcedureEvidenceError, match="before the successful"):
        attest(named_training)


@pytest.mark.parametrize("tool", ["run_command", "write_file", "replace_text"])
def test_named_binding_retry_cannot_hide_any_prior_attempted_command_or_write(named_training, tool):
    named_training.events[0]["request"] = {"op": "tool", "name": tool, "arguments": {}}
    named_training.events[0]["result"] = {"ok": False, "error": "rejected"}
    insert_binding_attempt(named_training)
    with pytest.raises(procedures.ProcedureEvidenceError, match="preceded"):
        attest(named_training)


@pytest.fixture
def multi_source_declaration(tmp_path):
    path = tmp_path / "multi-source-declaration.json"
    receipt = procedures.declare_procedure(path, "training-authority",
        ["fixture-task-one", "fixture-task-two"], procedure_version="3")
    return path, receipt


@pytest.fixture
def multi_source_training(tmp_path, multi_source_declaration):
    return make_training(tmp_path, multi_source_declaration)


def test_v2_declaration_and_template_preserve_original_native006_bytes(tmp_path):
    receipt = procedures.declare_procedure(tmp_path / "historical-v2.json", "skhynix-native-codex-006-training",
        ["swebench_verified--sympy__sympy-19637", "swebench_verified--sympy__sympy-19783"], "2")
    assert receipt["sha256"] == "70437a961574d980293c8cbce99fdc871d788606da590513a5c71cae76868c94"
    assert procedures.NAMED_TEMPLATE.content_hash == "sha256:000c8c3d3b8d19d23cd1dfa7eccc328aa4d3929bf10254141225dc2b7b07fab2"


def test_multisource_actual_gate_a_b_covers_two_files_and_two_distinct_sessions(tmp_path, multi_source_declaration):
    first, second = make_training(tmp_path, multi_source_declaration), make_training(tmp_path, multi_source_declaration, 2)
    verified = attest(first)["attestation"]
    assert verified["schema"] == procedures.MULTI_SOURCE_ATTESTATION_SCHEMA
    assert verified["base_workspace"]["schema"] == "skhynix/public-procedure-workspace/3.0"
    original = verified["base_workspace"]["source_file_sha256"]
    assert set(original) == {"pkg/logic.py", "pkg/other.py"}
    assert original == verified["red_workspace"]["source_file_sha256"]
    assert all(value != verified["green_workspace"]["source_file_sha256"][path] for path, value in original.items())
    assert verified["stages"][0]["broker_sequences"] == [1, 2, 3]
    receipt = procedures.promote_and_export(multi_source_declaration[0], multi_source_declaration[1]["sha256"],
        [{"run_root": str(item.root), "cell": "A"} for item in (first, second)], tmp_path / "multi-authority")
    export = procedures.read(Path(receipt["path"]))
    assert export["schema"] == procedures.MULTI_SOURCE_EXPORT_SCHEMA
    assert export["procedure_id"] == procedures.MULTI_SOURCE_PROCEDURE_ID
    assert receipt["support_count"] == receipt["contributor_count"] == 2


@pytest.mark.parametrize("source_paths,repaired_paths", [
    (["pkg/logic.py"], ["pkg/logic.py"]),
    (["pkg/logic.py", "pkg/other.py"], ["pkg/logic.py"]),
    (["pkg/logic.py", "pkg/other.py", "pkg/third.py"], ["pkg/logic.py", "pkg/third.py"]),
])
def test_multisource_accepts_a_nonempty_changed_subset_of_one_to_three_prebound_paths(
        tmp_path, multi_source_declaration, source_paths, repaired_paths):
    training = make_training(tmp_path, multi_source_declaration, source_paths=source_paths, repaired_paths=repaired_paths)
    assert attest(training)["attestation"]["green_workspace"]["changed_paths"] == sorted(
        [*repaired_paths, "pkg/tests/test_logic.py"])


@pytest.mark.parametrize("paths", [
    "[]", '["pkg/logic.py","pkg/other.py","pkg/third.py","pkg/z.py"]',
    '["pkg/other.py","pkg/logic.py"]', '["pkg/logic.py","pkg/logic.py"]',
    '["pkg/logic.py", "pkg/other.py"]', '["../logic.py"]', '["pkg/test_logic.py"]',
    '["pkg/tests/logic.py"]', '["pkg/logic.txt"]', '["pkg/tests/test_logic.py"]',
    '["pkg/logic.py",null]', ["pkg/logic.py"], "not JSON",
])
def test_multisource_bindings_are_canonical_bounded_implementation_paths(multi_source_training, paths):
    declared = procedures.read(multi_source_training.declaration_path)
    with pytest.raises(procedures.ProcedureEvidenceError):
        procedures.validate_bindings(declared, {**multi_source_training.bindings, "source_paths": paths}, "/opt/python")


def test_multisource_binding_cannot_include_nonexistent_implementation_file(multi_source_training):
    bindings = {**multi_source_training.bindings, "source_paths": '["pkg/missing.py"]'}
    with pytest.raises(procedures.ProcedureEvidenceError, match="absent"):
        procedures.capture_workspace(multi_source_training.workspace, bindings)


@pytest.mark.parametrize("mutation", [
    "missing_map", "extra_map_path", "map_digest", "red_source_changed", "no_green_source_changed",
    "uninspected_source", "outside_write", "undeclared_changed_path", "test_changed_after_red",
])
def test_multisource_verifier_rejects_scope_and_state_gaps(multi_source_training, mutation):
    training = multi_source_training
    begin = next(event for event in training.events if event["request"]["op"] == "begin_procedure")
    commands = [event for event in training.events if event["request"].get("name") == "run_command"]
    red, green = [event["result"]["result"]["procedure_snapshot"] for event in commands]
    if mutation == "missing_map":
        red.pop("source_file_sha256")
    elif mutation == "extra_map_path":
        red["source_file_sha256"]["pkg/unknown.py"] = "a" * 64
        red["source_sha256"] = procedures.sha(procedures.canonical(red["source_file_sha256"]))
    elif mutation == "map_digest":
        red["source_sha256"] = "a" * 64
    elif mutation == "red_source_changed":
        red["source_file_sha256"]["pkg/other.py"] = "a" * 64
        red["source_sha256"] = procedures.sha(procedures.canonical(red["source_file_sha256"]))
    elif mutation == "no_green_source_changed":
        base = begin["result"]["result"]["workspace_snapshot"]
        green["source_file_sha256"] = deepcopy(base["source_file_sha256"])
        green["source_sha256"] = base["source_sha256"]
        green["changed_paths"] = [training.bindings["test_path"]]
    elif mutation == "uninspected_source":
        training.events[1]["request"]["name"] = "search"
    elif mutation == "outside_write":
        training.events[7]["request"]["arguments"]["path"] = "pkg/unknown.py"
    elif mutation == "undeclared_changed_path":
        green["changed_paths"].append("pkg/unknown.py")
    else:
        edit = deepcopy(training.events[4])
        training.events.insert(-1, edit)
    rechain(training)
    with pytest.raises(procedures.ProcedureEvidenceError):
        attest(training)


@pytest.mark.parametrize("stage,mutation", [
    ("before_red", "implementation"), ("before_red", "outside"),
    ("after_red", "test"), ("after_red", "outside"),
])
def test_multisource_checks_intermediate_command_changes_even_when_restored_before_verification(
        multi_source_training, stage, mutation):
    training = multi_source_training
    red_index = next(index for index, event in enumerate(training.events)
        if event["request"].get("name") == "run_command")
    original_command = training.events[red_index]
    before = deepcopy(original_command["result"]["result"]["procedure_snapshot"])
    changed = deepcopy(before)
    if mutation == "implementation":
        changed["source_file_sha256"]["pkg/other.py"] = "a" * 64
        changed["source_sha256"] = procedures.sha(procedures.canonical(changed["source_file_sha256"]))
        changed["changed_paths"] = sorted([*changed["changed_paths"], "pkg/other.py"])
    elif mutation == "test":
        changed["test_sha256"] = "a" * 64
    else:
        changed["changed_paths"] = sorted([*changed["changed_paths"], "pkg/unknown.py"])
    commands = []
    for previous, current in ((before, changed), (changed, before)):
        commands.append({"request": {"op": "tool", "name": "run_command",
                "arguments": {"argv": ["/opt/python", "-c", "public command"]}},
            "result": {"ok": True, "result": {"exit_code": 0, "stdout": "", "stderr": "",
                "procedure_snapshot_before": previous, "procedure_snapshot": current}}})
    position = red_index + int(stage == "after_red")
    training.events[position:position] = commands
    rechain(training)
    with pytest.raises(procedures.ProcedureEvidenceError, match="before the RED|after RED|outside its declared scope"):
        attest(training)


def test_multisource_requires_intermediate_command_before_capture(multi_source_training):
    training = multi_source_training
    command = deepcopy(next(event for event in training.events if event["request"].get("name") == "run_command"))
    command["request"]["arguments"]["argv"] = ["/opt/python", "--version"]
    command["result"]["result"].pop("procedure_snapshot_before")
    training.events.insert(5, command)
    rechain(training)
    with pytest.raises(procedures.ProcedureEvidenceError, match="preceding workspace capture"):
        attest(training)
