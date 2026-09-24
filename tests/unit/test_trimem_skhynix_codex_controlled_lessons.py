"""Controlled transfer contracts with synthetic public evidence and mocked tools."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_skhynix_codex as pilot
import trimem_skhynix_codex_controlled_lessons as controlled
import trimem_skhynix_codex_diagnostic_bank as diagnostic
import trimem_skhynix_codex_learning as learning
from test_trimem_skhynix_codex import cell
from test_trimem_skhynix_codex_diagnostic_bank import components, descriptor, write

QUERY = {"node_id": "start", "objective": "quuxxyzzy", "operation": "plughwombat"}


@pytest.fixture
def frozen(tmp_path):
    prepared = components(tmp_path / "sources")
    spec = {"scenario": "KNOWN_FAILURE_RECOVERY", "retrieval_text_policy": diagnostic.EXACT_TASK_DIAGNOSTIC_ROUTE,
        "evaluation_tasks": [descriptor(task) for task in prepared.tasks], "sources": prepared.sources}
    spec_path = tmp_path / "source-spec.json"
    write(spec_path, spec)
    derived, _, _ = diagnostic._derive(spec["sources"], spec["evaluation_tasks"], spec["scenario"])
    lessons = []
    for index, source in enumerate(derived):
        text = ("Alpha operators need canonical outputs.", "Omega relations need canonical outputs.")[index]
        row, provenance = source["descriptor"], source["source"]["provenance"]
        lessons.append({"lesson_id": f"lesson-{index}", "family": f"family-{index}",
            "source_task_id": row["task_id"], "repository": row["repository"], "source_commit": row["commit"],
            "source_instruction_sha256": row["instruction_sha256"], "source_run_root": source["spec"]["run_root"],
            "source_cell": source["spec"]["cell"], "source_patch_sha256": provenance["patch_sha256"],
            "public_probe_sha256": source["spec"]["public_probe_evidence"]["sha256"],
            "source_lesson_sha256": learning.sha(source["spec"]["lesson_text"].encode()),
            "lesson_text": text, "lesson_sha256": learning.sha(text.encode()),
            "lesson_utf8_bytes": len(text.encode()), "lesson_word_count": len(text.split())})
    document = {"schema": controlled.LESSONS_SCHEMA, "scientific_role": controlled.TIMING,
        "source_spec": {"path": str(spec_path), "sha256": learning.file_sha(spec_path)}, "lessons": lessons,
        "source_official_resolved": False, "analyst_interpretation_verified": False, "verified_skill": False,
        "target_fix_verified": False, "manual_analyst_diagnosis": True, "gate_b_count": 0}
    path = tmp_path / "source-lessons.json"
    write(path, document)
    target = replace(prepared.tasks[0], task_id="disjoint-controlled-target", commit="0" * 40,
        instruction="Fix a different public issue\n")
    assignments = [{"task_id": target.task_id, "relevant_lesson_id": "lesson-0", "unrelated_lesson_id": "lesson-1"}]
    manifest_path = tmp_path / "controlled.json"
    receipt = controlled.freeze_controlled_manifest(manifest_path, lessons_path=path,
        targets=[target], assignments=assignments)
    return SimpleNamespace(prepared=prepared, document=document, lessons_path=path, spec_path=spec_path,
        target=target, assignments=assignments, path=manifest_path, receipt=receipt)


def load(frozen, task=None):
    return controlled.load_controlled_manifest(frozen.path, learning.file_sha(frozen.path), task or frozen.target)


@pytest.fixture
def controlled_cell(cell, frozen):
    cell.plan.update(public_task=frozen.target.public_payload(),
        target={"target_id": frozen.target.task_id, "repository": frozen.target.repository, "base_commit": frozen.target.commit},
        controlled_lesson_manifest=pilot.frozen_input(frozen.path), experimental_arms=dict(controlled.LABELS),
        scientific_role=controlled.ROLE)
    pilot.write(cell.run / "plan.json", cell.plan)
    (cell.run / "plan.sha256").write_text(pilot.sha(pilot.canonical(cell.plan)))
    bank = load(frozen, pilot.task_from_plan(cell.plan))
    for name in pilot.CELLS:
        root = pilot.cell_root(cell.run, name)
        pilot.write(root / "state.json", {"status": "OPEN", "actions": 0, "started_at": None, "tail_sha256": "0" * 64})
        pilot.write(root / "public-task.json", {"task": cell.plan["public_task"]})
        pilot.write(root / "bank-projection.json", controlled.projection(cell.plan, cell.run, name, bank))
    cell.frozen = frozen
    return cell


def action(cell, name, request):
    return pilot.perform_action(cell.plan, cell.run, name, request)


def rewrite_events(cell, name, events):
    root, tail = pilot.cell_root(cell.run, name), "0" * 64
    rows = []
    for sequence, event in enumerate(events, 1):
        event = {**event, "sequence": sequence, "previous_sha256": tail}
        tail = pilot.sha(pilot.canonical(event))
        rows.append({**event, "sha256": tail})
    (root / "tool-events.jsonl").write_bytes(b"".join(pilot.canonical(row) + b"\n" for row in rows))
    state = pilot.read(root / "state.json")
    state.update(actions=len(rows), tail_sha256=tail)
    pilot.write(root / "state.json", state)


def test_builder_accepts_exact_descriptors_and_retrospective_disjoint_sources(frozen, tmp_path):
    bank = load(frozen)
    assert bank.target == controlled.task_descriptor(frozen.target)
    assert bank.manifest["transfer_timing"] == "RETROSPECTIVE_DISJOINT_TRANSFER"
    assert bank.lesson_for("A") is None
    assert bank.lesson_for("B")["lesson_id"] == "lesson-1"
    assert bank.lesson_for("C")["lesson_id"] == "lesson-0"
    assert bank.lesson_for("B")["lesson_utf8_bytes"] == bank.lesson_for("C")["lesson_utf8_bytes"]
    receipt = controlled.freeze_controlled_manifest(tmp_path / "descriptor.json", lessons_path=frozen.lessons_path,
        targets=[controlled.task_descriptor(frozen.target)], assignments=frozen.assignments)
    assert receipt["targets"] == 1
    with pytest.raises(controlled.ControlledLessonError, match="overwrite"):
        controlled.freeze_controlled_manifest(frozen.path, lessons_path=frozen.lessons_path,
            targets=[frozen.target], assignments=frozen.assignments)


@pytest.mark.parametrize("changes", [{"task_id": "another-task"}, {"repository": "other/repo"},
    {"commit": "f" * 40}, {"instruction": "different instruction"}])
def test_target_scope_rejects_task_repository_commit_and_instruction_changes(frozen, changes):
    with pytest.raises(controlled.ControlledLessonError, match="scope"):
        load(frozen, replace(frozen.target, **changes))


@pytest.mark.parametrize("mutation", ["schema", "limits", "policy", "role", "labels", "patch", "hidden", "overlap", "duplicate", "unknown_lesson", "same_lesson", "missing_assignment"])
def test_manifest_rejects_rehashed_contract_violations(frozen, mutation):
    value = learning.read(frozen.path)
    if mutation == "schema":
        value["schema"] = "arbitrary-bank"
    elif mutation == "limits":
        value["context_budget_bytes"] = 12001
    elif mutation == "policy":
        value["delivery_policy"] = "ALWAYS_DELIVER"
    elif mutation == "role":
        value["scientific_role"] = "FULL_PDF_RETRIEVAL"
    elif mutation == "labels":
        value["experimental_arms"]["B"] = "RELEVANT_LESSON"
    elif mutation in ("patch", "hidden"):
        value["target_patch" if mutation == "patch" else "hidden_tests"] = "forbidden"
    elif mutation == "overlap":
        value["targets"].append(controlled.task_descriptor(frozen.prepared.tasks[1]))
    elif mutation == "duplicate":
        value["targets"].append(value["targets"][0])
    elif mutation == "unknown_lesson":
        value["assignments"][0]["relevant_lesson_id"] = "missing"
    elif mutation == "same_lesson":
        value["assignments"][0]["unrelated_lesson_id"] = "lesson-0"
    else:
        value["assignments"] = []
    write(frozen.path, value)
    with pytest.raises(controlled.ControlledLessonError):
        load(frozen)


@pytest.mark.parametrize("mutation", ["source_task_id", "source_commit", "source_patch_sha256", "source_instruction_sha256",
    "public_probe_sha256", "source_lesson_sha256", "padding", "byte_count", "word_count", "lesson_hash", "verified", "patch", "hint", "unequal_utf8"])
def test_source_lessons_reject_rehashed_provenance_content_or_padding_changes(frozen, mutation):
    value = learning.read(frozen.lessons_path)
    lesson = value["lessons"][0]
    if mutation in lesson:
        lesson[mutation] = "changed-provenance"
    elif mutation == "padding":
        lesson["lesson_text"] += " "
    elif mutation == "byte_count":
        lesson["lesson_utf8_bytes"] += 1
    elif mutation == "word_count":
        lesson["lesson_word_count"] += 1
    elif mutation == "lesson_hash":
        lesson["lesson_sha256"] = "f" * 64
    elif mutation == "verified":
        value["verified_skill"] = True
    elif mutation == "patch":
        lesson["target_patch"] = "forbidden patch"
    elif mutation == "hint":
        lesson["lesson_text"] = frozen.target.task_id
        value["lessons"][1]["lesson_text"] = "z" * len(frozen.target.task_id)
    else:
        # Same character count, different UTF-8 byte count is not a matched control.
        lesson["lesson_text"] = "é" + lesson["lesson_text"][1:]
    if mutation in ("padding", "hint", "unequal_utf8"):
        for row in value["lessons"]:
            row.update(lesson_sha256=learning.sha(row["lesson_text"].encode()),
                lesson_utf8_bytes=len(row["lesson_text"].encode()), lesson_word_count=len(row["lesson_text"].split()))
    write(frozen.lessons_path, value)
    manifest = learning.read(frozen.path)
    manifest["lessons_file"]["sha256"] = learning.file_sha(frozen.lessons_path)
    write(frozen.path, manifest)
    with pytest.raises(controlled.ControlledLessonError):
        load(frozen)


@pytest.mark.parametrize("which", ["manifest", "lessons", "spec", "patch"])
def test_every_action_rechecks_frozen_external_bindings_before_state_changes(controlled_cell, which):
    cell, frozen = controlled_cell, controlled_cell.frozen
    path = {"manifest": frozen.path, "lessons": frozen.lessons_path, "spec": frozen.spec_path,
        "patch": Path(frozen.prepared.sources[0]["run_root"]) / "cells/A/submission.diff"}[which]
    before = (cell.root / "state.json").read_bytes()
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError):
        action(cell, "A", {"op": "info"})
    assert (cell.root / "state.json").read_bytes() == before


@pytest.mark.parametrize("name", ["A", "B", "C"])
def test_first_valid_recall_delivers_only_assigned_exact_text_once_then_no_repeat(controlled_cell, name):
    cell = controlled_cell
    forbidden = action(cell, name, {"op": "tool", "name": "read_file", "arguments": {"path": "a.py"}})
    assert not forbidden["ok"] and "valid recall" in forbidden["error"]
    malformed = action(cell, name, {"op": "recall", "query": {**QUERY, "objective": ""}})
    assert not malformed["ok"]
    first = action(cell, name, {"op": "recall", "query": QUERY})
    assert first["ok"], first
    result = first["result"]
    assert result["new_injection_count"] == int(name != "A")
    assert "experimental_arm" not in result
    assert result["budget"]["context_budget_bytes"] == 12000
    assert result["budget"]["max_task_injections"] == 3
    if name != "A":
        item, = result["injections"]
        lesson = load(cell.frozen).lesson_for(name)
        assert item["exact_text"] == lesson["lesson_text"]
        assert item["sha256"] == learning.sha(item["exact_text"].encode())
        assert item["byte_count"] == len(item["exact_text"].encode())
        assert item["confidence"] == 0.0 and item["verified_skill"] is False
        assert item["source_task_id"] != cell.frozen.target.task_id
    for query in (QUERY, {**QUERY, "node_id": "later"}):
        later = action(cell, name, {"op": "recall", "query": query})
        assert later["ok"] and later["result"]["injections"] == []
        assert later["result"]["new_injection_count"] == 0
        assert later["result"]["budget"] == result["budget"]
        assert "exact_text" not in json.dumps(later["result"])
    assert action(cell, name, {"op": "tool", "name": "read_file", "arguments": {"path": "a.py"}})["ok"]
    events = pilot.audit_events(pilot.cell_root(cell.run, name))[0]
    restored = controlled.restore_delivery(cell.plan, cell.run, name, events, pilot.controlled_lessons(cell.plan))
    assert restored["successful_recalls"] == 3
    assert (restored["delivery"] is not None) == (name != "A")


def test_changed_node_query_is_rejected_without_spending_another_delivery(controlled_cell):
    cell = controlled_cell
    first = action(cell, "C", {"op": "recall", "query": QUERY})["result"]
    failed = action(cell, "C", {"op": "recall", "query": {**QUERY, "operation": "changed"}})
    assert not failed["ok"] and "different semantic query" in failed["error"]
    after = action(cell, "C", {"op": "recall", "query": {**QUERY, "node_id": "new"}})
    assert after["ok"] and after["result"]["budget"] == first["budget"]


@pytest.mark.parametrize("mutation", ["text", "missing", "repeat", "failed_valid", "controller", "budget"])
def test_event_derived_restore_rejects_rehashed_delivery_forgery(controlled_cell, mutation):
    cell, name = controlled_cell, "C"
    action(cell, name, {"op": "recall", "query": QUERY})
    action(cell, name, {"op": "recall", "query": {**QUERY, "node_id": "later"}})
    events = pilot.audit_events(pilot.cell_root(cell.run, name))[0]
    first = events[0]["result"]["result"]
    if mutation == "text":
        item = first["injections"][0]
        item["exact_text"] += " forged"
        item.update(sha256=learning.sha(item["exact_text"].encode()), byte_count=len(item["exact_text"].encode()))
    elif mutation == "missing":
        first["injections"] = []
    elif mutation == "repeat":
        events[1]["result"]["result"]["injections"] = deepcopy(first["injections"])
    elif mutation == "failed_valid":
        events[0]["result"] = {"ok": False, "error_type": "ValueError", "error": "temporary failure"}
    elif mutation == "controller":
        first["controller_state"]["delivery"] = None
    else:
        first["budget"]["bytes_used"] = 0
    rewrite_events(cell, name, events)
    with pytest.raises(controlled.ControlledLessonError, match="event-derived"):
        action(cell, name, {"op": "info"})


@pytest.mark.parametrize("mutation", ["experiment", "user", "projection", "copied_cell", "bank", "procedure"])
def test_controlled_cell_rejects_scope_projection_and_exclusivity_changes(controlled_cell, mutation):
    cell = controlled_cell
    if mutation == "experiment":
        cell.plan["experiment_id"] = "another-experiment"
    elif mutation == "user":
        cell.plan["solver_user_id"] = "another-solver"
    elif mutation == "projection":
        value = pilot.read(cell.root / "bank-projection.json")
        value["bank"]["records"] = 1
        pilot.write(cell.root / "bank-projection.json", value)
    elif mutation == "copied_cell":
        pilot.write(cell.root / "bank-projection.json", pilot.read(pilot.cell_root(cell.run, "B") / "bank-projection.json"))
    else:
        cell.plan["frozen_memory_bank" if mutation == "bank" else "procedure_declaration"] = cell.plan["controlled_lesson_manifest"]
    with pytest.raises(ValueError):
        action(cell, "A", {"op": "info"})


def test_mocked_grade_counts_zero_one_one_bytes_and_reports_explicit_experimental_labels(controlled_cell):
    cell = controlled_cell
    expected_bytes = load(cell.frozen).lesson_for("C")["lesson_utf8_bytes"]
    for name in pilot.CELLS:
        action(cell, name, {"op": "recall", "query": QUERY})
        action(cell, name, {"op": "recall", "query": QUERY})
        submitted = action(cell, name, {"op": "submit", "summary": "Public fix tested"})
        assert submitted["ok"]
        result = pilot.grade(cell.plan, cell.run, name)
        assert result["memory_injections"] == int(name != "A")
        assert result["memory_bytes"] == (expected_bytes if name != "A" else 0)
        assert result["experimental_arm"] == controlled.LABELS[name]
        assert pilot.grade(cell.plan, cell.run, name) == result
    report = pilot.report(cell.plan, cell.run)
    assert report["scientific_role"] == "CONTROLLED_CONTENT_TRANSFER"
    assert set(report["controlled_comparison"]) == set(controlled.LABELS.values())
    assert len(cell.calls) == 3  # Local fixture grader only, no official execution.


def test_prepare_creates_empty_projections_and_identical_initial_recall_guidance(frozen, tmp_path, monkeypatch):
    import trimem_skhynix_codex_memory as memory
    import trimem_skhynix_source_bank as source
    target = frozen.target
    args = SimpleNamespace(run_root=tmp_path / "execution", workspace_root=tmp_path / "work",
        dataset_cache_root=tmp_path / "cache", harness_root=tmp_path / "harness", loader_preflight_path=None,
        public_python="/public/python", target_id=target.task_id, experiment_id="controlled-test", solver_user_id="fresh-solver",
        controlled_lesson_manifest=frozen.path)
    runner = SimpleNamespace(image="image@sha256:" + "a" * 64, masked_image_files=(),
        masked_image_directories=(), content_hash="b" * 64)
    env = SimpleNamespace(tasks=(target,), targets_by_id={target.task_id: {"target_id": target.task_id,
        "repository": target.repository, "base_commit": target.commit}},
        prepare_cell=lambda arm, task: SimpleNamespace(workspace_factory=lambda task:
            SimpleNamespace(root=args.workspace_root / arm, command_runner=runner)))
    monkeypatch.setattr(pilot, "source_hashes", lambda: {})
    monkeypatch.setattr(pilot, "environment", lambda *args: env)
    monkeypatch.setattr(pilot.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="a" * 40))
    monkeypatch.setattr(memory, "initialize_memory", lambda *args, **kwargs: pytest.fail("Controlled cells must not open memory stores"))
    monkeypatch.setattr(source, "load_validated_source_bank", lambda *args: pytest.fail("Controlled cells must not load historical memory"))
    pilot.prepare(args)
    plan = pilot.load_plan(args.run_root)
    assert plan["experimental_arms"] == controlled.LABELS
    guidance = []
    for name in pilot.CELLS:
        root = pilot.cell_root(args.run_root, name)
        projection = pilot.read(root / "bank-projection.json")
        assert projection["bank"]["records"] == projection["seed_skill_count"] == projection["seed_episode_count"] == 0
        assert projection["budget"]["injections_used"] == 0
        assert not (root / "memory-private").exists()
        guidance.append(pilot.read(root / "public-task.json")["memory"])
    assert len(set(guidance)) == 1 and guidance[0].startswith("Begin with recall")
