"""Failed-source evidence and real controller tests; no model, grader or probe execution."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
import trimem_skhynix_codex_diagnostic_bank as diagnostic
import trimem_skhynix_codex_learning as learning
import trimem_skhynix_codex_memory as bridge
from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.ppr import DeterministicHashEmbedder
from enterprise_memory.trimem.retrieval import MemoryKind
from test_trimem_skhynix_codex_learning import descriptor, training_run, write


def components(tmp_path):
    sources, tasks, protected, results = [], [], {}, []
    for index in (1, 2):
        spec = training_run(tmp_path / f"failed-{index}", index=index, resolved=False)
        run = Path(spec["run_root"])
        plan = learning.read(run / "plan.json")
        plan["public_python"] = "/opt/python"
        write(run / "plan.json", plan)
        plan_hash = learning.sha(learning.canonical(plan))
        (run / "plan.sha256").write_text(plan_hash)
        for filename in ("submission.json", "public-result.json"):
            path = run / "cells/A" / filename
            write(path, {**learning.read(path), "plan_sha256": plan_hash})
        image = f"public/synthetic-{index}@sha256:" + str(index) * 64
        write(run / "cells/A/workspace.json", {"plan_sha256": plan_hash, "image": image})
        for path in [run / "plan.json", *[run / "cells/A" / name for name in
                ("public-result.json", "state.json", "submission.diff", "tool-events.jsonl", "workspace.json")]]:
            protected[str(path)] = learning.file_sha(path)
        source_code = "# analyst-authored synthetic public observations; never executed\n"
        public = plan["public_task"]
        observations = []
        for cell in ("BASE", "A"):
            cases = [{"case": "public_tuple_example", "actual": "tuple" if cell == "A" else "list",
                "expected": "tuple", "passed": cell == "A", "exception": None},
                {"case": "nested_tuple_still_wrong", "actual": "list", "expected": "tuple", "passed": False,
                 "exception": None}]
            output = {"observations": cases, "passed": sum(row["passed"] for row in cases), "total": len(cases)}
            observations.append({"cell": cell,
                "submission_patch_sha256": None if cell == "BASE" else learning.file_sha(run / "cells/A/submission.diff"),
                "public_probe": {"argv": ["/opt/python", "-c", source_code], "cwd": ".", "exit_code": 0,
                    "timed_out": False, "output_truncated": False, "stdout": learning.canonical(output).decode() + "\n",
                    "stderr": ""}})
        results.append({"task_id": public["task_id"], "base_commit": public["commit"], "image": image,
            "public_task_sha256": learning.sha(json.dumps(public, sort_keys=True).encode()),
            "probe_source": source_code, "probe_sha256": learning.sha(source_code.encode()),
            "observations": observations})
        tasks.append(CodingTask(public["task_id"], "native-recovery", "new-session", public["repository"],
            public["commit"], public["instruction"], {}, ()))
        sources.append({**spec, "title": "lambdify tuple conversion and code generation",
            "lesson_text": "Public lambdify tuple conversion improves the simple tuple case, but nested tuple conversion remains wrong. Reproduce nested code generation before generalizing the patch."})
    probe = tmp_path / "public-diagnostic.json"
    write(probe, {"schema": diagnostic.PROBE_SCHEMA, "created_utc": "2026-09-13T02:23:52+00:00",
        "hidden_test_text_or_names_accessed": False, "originals_unchanged": True, "model_calls": 0,
        "official_grader_calls": 0, "protected_original_sha256": protected, "results": results})
    for source in sources:
        source["public_probe_evidence"] = {"path": str(probe), "sha256": learning.file_sha(probe)}
    return SimpleNamespace(sources=sources, tasks=tasks, probe=probe, path=tmp_path / "bank.json")


@pytest.fixture
def prepared(tmp_path):
    return components(tmp_path)


def freeze(prepared, *, scenario="KNOWN_FAILURE_RECOVERY", tasks=None, retrieval_text_policy=None):
    return diagnostic.freeze_diagnostic_bank(prepared.path, prepared.sources,
        [descriptor(task) for task in (prepared.tasks if tasks is None else tasks)], scenario=scenario,
        retrieval_text_policy=retrieval_text_policy)


@pytest.fixture
def bank(prepared):
    prepared.receipt = freeze(prepared)
    return prepared


def refresh_probe(prepared, value):
    write(prepared.probe, value)
    for source in prepared.sources:
        source["public_probe_evidence"]["sha256"] = learning.file_sha(prepared.probe)


def test_failed_gate_a_and_unverified_diagnostic_are_separate_and_original_records_unchanged(bank):
    task = bank.tasks[0]
    value = learning.load_frozen_bank(bank.path, bank.receipt["sha256"], task)
    assert isinstance(value, diagnostic.FrozenDiagnosticBank)
    assert value.promoted_skill is None
    assert value.manifest["gate_a"]["episode_count"] == 2
    assert value.manifest["gate_b"]["verified_skill_count"] == 0
    assert value.report["source_evidence_label"] == diagnostic.LABEL
    assert value.report["source_official_resolved"] is False
    assert value.report["analyst_interpretations_verified"] is False
    assert value.report["target_fix_verified"] is False
    assert value.report["online_learning"] is False
    assert value.report["knowledge_relation_count"] == 0
    assert len(value.manifest["records"]) == 2 and len(value.records) == 1
    assert value.records[0]["source"]["task_id"] == task.task_id
    assert value.report["record_selection_policy"] == "EXACT_RETAINED_FAILURE_TASK"
    with learning.SkillMemoryStore(bank.path.with_name(value.manifest["gate_a"]["private_store_filename"])) as store:
        for index, row in enumerate(value.manifest["gate_a"]["episodes"], 1):
            episode = store.get_episode(row["episode_id"], org_id="fixture-training", user_id=f"native-session-{index}")
            assert episode.evidence.succeeded is False
            assert episode.evidence.task_id == f"test-training-{index}"
            assert episode.evidence.verification_evidence_hash == "sha256:" + row["source"]["public_result_sha256"]
    payload = json.loads(value.records[0]["content"])
    assert payload["source_official_resolved"] is False
    assert payload["verified_skill"] is False and payload["target_fix_verified"] is False
    assert payload["public_probe"]["submitted_passed"] == 1
    assert payload["public_probe"]["residual_public_cases"] == ["nested_tuple_still_wrong"]
    text = bank.path.read_text()
    assert "PRIVATE_TRAINING_PATCH_CONTENT" not in text and "PRIVATE_GRADER_TEST_CONTENT" not in text
    for original, digest in learning.read(bank.probe)["protected_original_sha256"].items():
        assert learning.file_sha(Path(original)) == digest


def test_transfer_is_disjoint_and_retains_same_repository_candidate_records(prepared):
    target = replace(prepared.tasks[0], task_id="new-unexecuted-transfer", commit="c" * 40)
    receipt = freeze(prepared, scenario="DISJOINT_TRANSFER", tasks=[target])
    value = learning.load_frozen_bank(prepared.path, receipt["sha256"], target)
    assert len(value.records) == 2
    assert value.manifest["source_target_overlap_task_ids"] == []
    assert value.report["record_selection_policy"] == "SAME_REPOSITORY_DISJOINT_SOURCE_TASKS"


def test_transfer_never_implicitly_allows_same_problem(prepared):
    with pytest.raises(diagnostic.DiagnosticBankError, match="disjoint"):
        freeze(prepared, scenario="DISJOINT_TRANSFER")
    assert not prepared.path.exists()
    assert not prepared.path.with_suffix(".gate-a-private.sqlite3").exists()


@pytest.mark.parametrize("scenario", [None, "", "recovery", "UNKNOWN"])
def test_scenario_must_be_explicit_allowlisted_value(prepared, scenario):
    with pytest.raises(diagnostic.DiagnosticBankError, match="explicit"):
        freeze(prepared, scenario=scenario)


@pytest.mark.parametrize("changes", [{"commit": "b" * 40}, {"repository": "other/repo"},
    {"instruction": "different issue"}, {"task_id": "unknown-recovery-target"}])
def test_recovery_requires_exact_retained_problem_identity(prepared, changes):
    with pytest.raises(diagnostic.DiagnosticBankError, match="retained|differs"):
        freeze(prepared, tasks=[replace(prepared.tasks[0], **changes)])


@pytest.mark.parametrize("arm", ["NO_MEMORY", "EXISTING_M2", "SKHYNIX"])
def test_real_recovery_controllers_preserve_payload_but_m2_rejects_failed_same_task_source(bank, tmp_path, monkeypatch, arm):
    task = bank.tasks[0]
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))
    kwargs = {"frozen_bank_path": bank.path, "frozen_bank_sha256": bank.receipt["sha256"]}
    target_bank = learning.load_frozen_bank(bank.path, bank.receipt["sha256"], task)
    graph = learning.LearnedGraphStore(task, target_bank)
    assert list(graph.execution_views.values()) == [target_bank.records[0]["content"].encode()]
    snapshot = graph.snapshot(MemoryKind.ORG_SEMANTIC, org_id=task.org_id, user_id=task.user_id, repository=task.repository)
    candidate = next(iter(snapshot.records.values()))
    assert candidate.verified is False and candidate.source_outcome == "failed"
    assert candidate.metadata["target_derived"] is True
    assert candidate.metadata["source_official_resolved"] is False
    cell = tmp_path / arm
    manifest = bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    binding = learning.read(cell / "memory-private/checkpoint.json")["state"]["binding"]
    assert binding["diagnostic_scenario"] == "KNOWN_FAILURE_RECOVERY"
    assert binding["source_scope"] == diagnostic.LABEL
    assert manifest["verified_skill_payload_count"] == 0
    query = {"node_id": "lambdify", "objective": task.instruction, "operation": "Fix lambdify tuple conversion"}
    result = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    assert result["new_injection_count"] == int(arm == "SKHYNIX")
    if arm == "SKHYNIX":
        assert json.loads(result["injections"][0]["exact_text"])["content"] == target_bank.records[0]["content"]
    else:
        assert not result["injections"]
    repeated = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    assert repeated["repeat"] and repeated["new_injection_count"] == 0
    assert repeated["injections"] == result["injections"]


def test_seeded_pdf_store_and_m2_graph_receive_identical_diagnostic_bytes_without_episodes_or_skills(bank):
    task = bank.tasks[0]
    value = learning.load_frozen_bank(bank.path, bank.receipt["sha256"], task)
    store, report = learning.build_learned_seeded_store(":memory:", task, value)
    try:
        snapshot = store.snapshot(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
            revision=task.commit, language="python")
        assert not snapshot.episodes and not snapshot.skills
        assert len(snapshot.repository_knowledge) == 1
        knowledge = snapshot.repository_knowledge[0]
        assert knowledge.content == value.records[0]["content"]
        assert list(learning.LearnedGraphStore(task, value).execution_views.values()) == [knowledge.content.encode()]
        assert report["same_shared_payload_between_memory_arms"] is True
    finally:
        store.close()


@pytest.mark.parametrize("file,field,new_value", [
    ("public-result.json", "resolved", True), ("public-result.json", "official", False),
    ("public-result.json", "resolved", 0), ("state.json", "pending", "unfinished"),
    ("submission.json", "agent_completed", False),
])
def test_completed_failure_cannot_be_invented_from_bad_or_successful_source(prepared, file, field, new_value):
    path = Path(prepared.sources[0]["run_root"]) / "cells/A" / file
    write(path, {**learning.read(path), field: new_value})
    with pytest.raises(learning.LearnedBankError):
        freeze(prepared)
    assert not prepared.path.exists()


@pytest.mark.parametrize("mutation", [
    "revision", "public_task_hash", "image", "probe_hash", "argv", "selected_patch", "missing_base",
    "duplicate_cell", "duplicate_task", "duplicate_case", "exit_bool", "count_bool", "summary", "timeout",
    "truncated", "no_residual", "changed_expectation", "before_submission", "hidden_input", "protected_source",
])
def test_probe_identity_process_and_case_accounting_cannot_be_fabricated(prepared, mutation):
    value = learning.read(prepared.probe)
    row = value["results"][0]
    result = row["observations"][1]["public_probe"]
    if mutation == "revision":
        row["base_commit"] = "f" * 40
    elif mutation == "public_task_hash":
        row["public_task_sha256"] = "f" * 64
    elif mutation == "image":
        row["image"] = "public/wrong@sha256:" + "f" * 64
    elif mutation == "probe_hash":
        row["probe_source"] += "changed"
    elif mutation == "argv":
        result["argv"] = ["echo", "passed"]
    elif mutation == "selected_patch":
        row["observations"][1]["submission_patch_sha256"] = "f" * 64
    elif mutation == "missing_base":
        row["observations"].pop(0)
    elif mutation == "duplicate_cell":
        row["observations"].append(deepcopy(row["observations"][1]))
    elif mutation == "duplicate_task":
        value["results"].append(deepcopy(row))
    elif mutation in ("duplicate_case", "count_bool", "summary", "no_residual", "changed_expectation"):
        output = json.loads(result["stdout"])
        if mutation == "duplicate_case":
            output["observations"][1]["case"] = output["observations"][0]["case"]
        elif mutation == "count_bool":
            output["passed"] = True
        elif mutation == "summary":
            output["passed"] += 1
        elif mutation == "no_residual":
            for case in output["observations"]:
                case["passed"] = True
            output["passed"] = output["total"]
        else:
            output["observations"][1]["expected"] = "changed oracle expectation"
        result["stdout"] = learning.canonical(output).decode()
    elif mutation == "exit_bool":
        result["exit_code"] = False
    elif mutation == "timeout":
        result["timed_out"] = True
    elif mutation == "truncated":
        result["output_truncated"] = True
    elif mutation == "before_submission":
        value["created_utc"] = "1970-01-01T00:00:00Z"
    elif mutation == "hidden_input":
        value["hidden_test_text_or_names_accessed"] = True
    else:
        value["protected_original_sha256"].pop(str(Path(prepared.sources[0]["run_root"]) / "cells/A/submission.diff"))
    refresh_probe(prepared, value)
    with pytest.raises(diagnostic.DiagnosticBankError):
        freeze(prepared)


@pytest.mark.parametrize("mutation", ["payload", "success", "skill", "scope", "source_reference", "scenario", "relation"])
def test_rehashed_manifest_still_must_equal_regenerated_source_contract(bank, mutation):
    value = learning.read(bank.path)
    if mutation == "payload":
        record = value["records"][0]
        payload = json.loads(record["content"])
        payload["analyst_lesson"] = "silently substituted explanation"
        record["content"] = learning.canonical(payload).decode()
        record["content_sha256"] = learning.sha(record["content"].encode())
        record["content_bytes"] = len(record["content"].encode())
    elif mutation == "success":
        value["records"][0]["source"]["resolved"] = True
    elif mutation == "skill":
        value["gate_b"]["verified_skill_count"] = 1
    elif mutation == "scope":
        value["source_target_overlap_task_ids"] = []
    elif mutation == "source_reference":
        value["source_evidence_references"][0]["cells/A/submission.diff"]["sha256"] = "f" * 64
    elif mutation == "scenario":
        value["scenario"] = "DISJOINT_TRANSFER"
    else:
        value["knowledge_relation_count"] = 1
    write(bank.path, value)
    with pytest.raises(diagnostic.DiagnosticBankError):
        learning.load_frozen_bank(bank.path, learning.file_sha(bank.path), bank.tasks[0])


@pytest.mark.parametrize("which", ["probe", "original_patch", "authority"])
def test_load_rejects_changed_or_revoked_external_evidence(bank, which):
    value = learning.read(bank.path)
    path = {"probe": bank.probe, "original_patch": Path(bank.sources[0]["run_root"]) / "cells/A/submission.diff",
        "authority": bank.path.with_name(value["gate_a"]["private_store_filename"])}[which]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(learning.LearnedBankError, match="hash"):
        learning.load_frozen_bank(bank.path, bank.receipt["sha256"], bank.tasks[0])


def test_revoked_failed_episode_is_rejected_even_if_authority_and_manifest_are_rehashed(bank):
    value = learning.read(bank.path)
    path = bank.path.with_name(value["gate_a"]["private_store_filename"])
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE memory_records SET revoked=1")
    value["gate_a"]["private_store_sha256"] = learning.file_sha(path)
    write(bank.path, value)
    with pytest.raises(diagnostic.DiagnosticBankError, match="Gate A episode"):
        learning.load_frozen_bank(bank.path, learning.file_sha(bank.path), bank.tasks[0])


def test_prose_is_bounded_but_never_automatically_validated_as_truth(prepared):
    prepared.sources[0]["lesson_text"] = "This prose says every bug is solved. That statement has not been validated."
    receipt = freeze(prepared)
    value = learning.load_frozen_bank(prepared.path, receipt["sha256"], prepared.tasks[0])
    payload = json.loads(value.records[0]["content"])
    assert payload["analyst_lesson"] == prepared.sources[0]["lesson_text"]
    assert payload["analyst_interpretation_verified"] is False
    assert payload["source_official_resolved"] is False and payload["target_fix_verified"] is False


@pytest.mark.parametrize("lesson", ["", "x" * 3501, "가" * 1167, False])
def test_lesson_limit_is_utf8_bytes_and_nonempty_text(prepared, lesson):
    prepared.sources[0]["lesson_text"] = lesson
    with pytest.raises(diagnostic.DiagnosticBankError, match="analyst lesson"):
        freeze(prepared)


def test_nonfinite_and_duplicate_json_are_rejected_even_with_updated_probe_hash(prepared):
    raw = prepared.probe.read_bytes().replace(b'"model_calls":0', b'"model_calls":NaN')
    prepared.probe.write_bytes(raw)
    for source in prepared.sources:
        source["public_probe_evidence"]["sha256"] = learning.file_sha(prepared.probe)
    with pytest.raises(diagnostic.DiagnosticBankError, match="nonfinite"):
        freeze(prepared)
    with pytest.raises(diagnostic.DiagnosticBankError, match="duplicate"):
        diagnostic._json('{"scenario":"KNOWN_FAILURE_RECOVERY","scenario":"DISJOINT_TRANSFER"}')


def test_symlink_bank_or_probe_is_rejected_before_resolving_away_link_identity(bank, tmp_path):
    linked = tmp_path / "linked-bank.json"
    try:
        linked.symlink_to(bank.path)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create symbolic links")
    with pytest.raises(diagnostic.DiagnosticBankError, match="linked"):
        learning.load_frozen_bank(linked, bank.receipt["sha256"], bank.tasks[0])


def test_refuses_overwriting_complete_or_partial_bank(bank):
    before = bank.path.read_bytes()
    with pytest.raises(diagnostic.DiagnosticBankError, match="overwrite"):
        freeze(bank)
    assert bank.path.read_bytes() == before
    bank.path.unlink()
    with pytest.raises(diagnostic.DiagnosticBankError, match="overwrite"):
        freeze(bank)


def test_existing_success_bank_still_rejects_overlap_and_does_not_share_failed_knowledge(prepared, tmp_path):
    source = {key: prepared.sources[0][key] for key in ("run_root", "cell")}
    with pytest.raises(learning.LearnedBankError, match="disjoint"):
        learning.freeze_learned_bank(tmp_path / "old-overlap.json", [source], [descriptor(prepared.tasks[0])])
    disjoint = replace(prepared.tasks[0], task_id="old-disjoint-target", commit="f" * 40)
    receipt = learning.freeze_learned_bank(tmp_path / "old-bank.json", [source], [descriptor(disjoint)])
    assert receipt["gate_a_episodes"] == 1 and receipt["shared_records"] == 0


@pytest.mark.parametrize("policy", ["", "FULL_CONTENT", False, 1, [], {}, "DIAGNOSTIC_LESSON_CONTENT "])
def test_freeze_rejects_unknown_retrieval_policy_before_writing(prepared, policy):
    with pytest.raises(diagnostic.DiagnosticBankError, match="retrieval text policy"):
        freeze(prepared, retrieval_text_policy=policy)
    assert not prepared.path.exists()
    assert not prepared.path.with_name("bank.gate-a-private.sqlite3").exists()


@pytest.mark.parametrize("policy", [None, "", "FULL_CONTENT", False, [], {}])
def test_load_rejects_malformed_explicit_retrieval_policy_even_with_rehashed_manifest(bank, policy):
    manifest = learning.read(bank.path)
    manifest["retrieval_text_policy"] = policy
    write(bank.path, manifest)
    with pytest.raises(diagnostic.DiagnosticBankError, match="retrieval text policy"):
        learning.load_frozen_bank(bank.path, learning.file_sha(bank.path), bank.tasks[0])


def test_default_bank_omits_policy_and_explicit_optin_changes_only_manifest_policy(bank):
    original = bank.path.read_bytes()
    old = learning.load_frozen_bank(bank.path, bank.receipt["sha256"], bank.tasks[0])
    assert "retrieval_text_policy" not in old.manifest and "retrieval_text_policy" not in old.report
    assert bridge._repository_retrieval_texts(old, {}) is None
    # A test-only rehashed copy isolates the one optional manifest field. Source,
    # authority and full record bytes stay unchanged and are revalidated on load.
    manifest = {**old.manifest, "retrieval_text_policy": diagnostic.DIAGNOSTIC_LESSON_CONTENT}
    write(bank.path, manifest)
    enabled = learning.load_frozen_bank(bank.path, learning.file_sha(bank.path), bank.tasks[0])
    assert enabled.records == old.records
    assert enabled.report["retrieval_text_policy"] == diagnostic.DIAGNOSTIC_LESSON_CONTENT
    manifest.pop("retrieval_text_policy")
    assert learning.canonical(manifest) + b"\n" == original


@pytest.mark.parametrize("arm", ["NO_MEMORY", "EXISTING_M2", "SKHYNIX"])
def test_optin_bridge_uses_validated_lesson_with_identical_execution_content(prepared, tmp_path, monkeypatch, arm):
    receipt = freeze(prepared, retrieval_text_policy=diagnostic.DIAGNOSTIC_LESSON_CONTENT)
    task = prepared.tasks[0]
    enabled = learning.load_frozen_bank(prepared.path, receipt["sha256"], task)
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))
    kwargs = {"frozen_bank_path": prepared.path, "frozen_bank_sha256": receipt["sha256"]}
    cell = tmp_path / arm
    manifest = bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    assert manifest["verified_skill_payload_count"] == 0
    query = {"node_id": "lambdify", "objective": task.instruction, "operation": "Fix lambdify tuple conversion"}
    result = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    assert result["new_injection_count"] == int(arm == "SKHYNIX")
    if arm == "SKHYNIX":
        injected = result["injections"][0]
        wrapped = json.loads(injected["exact_text"])
        assert wrapped["content"] == enabled.records[0]["content"]
        assert wrapped["title"] == enabled.records[0]["title"]
        assert wrapped["layer"] == "REPOSITORY_SEMANTIC"
        controller, store, report = bridge._controller(cell / "memory-private", task, arm, ROOT,
            create=False, frozen_bank=enabled)
        try:
            texts = bridge._repository_retrieval_texts(enabled, report)
            assert texts == {injected["memory_id"]: enabled.records[0]["title"] + " " +
                json.loads(enabled.records[0]["content"])["analyst_lesson"]}
            assert report["retrieval_text_policy"] == diagnostic.DIAGNOSTIC_LESSON_CONTENT
            from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController
            default = SkillFirstMemoryController(store, task_id=task.task_id)
            assert default.content_hash != controller.content_hash
            assert list(learning.LearnedGraphStore(task, enabled).execution_views.values()) == [wrapped["content"].encode()]
        finally:
            store.close()
    repeated = bridge.recall_memory(cell, task, arm, query, ROOT, **kwargs)
    assert repeated["repeat"] and repeated["injections"] == result["injections"]


@pytest.mark.parametrize("mutation", ["other_bank", "other_schema", "policy", "kind", "lesson", "entry_id", "entry_hash"])
def test_bridge_rejects_non_diagnostic_policy_or_malformed_projection(prepared, mutation):
    receipt = freeze(prepared, retrieval_text_policy=diagnostic.DIAGNOSTIC_LESSON_CONTENT)
    task = prepared.tasks[0]
    bank = learning.load_frozen_bank(prepared.path, receipt["sha256"], task)
    store, report = learning.build_learned_seeded_store(":memory:", task, bank)
    store.close()
    if mutation == "other_bank":
        bank = SimpleNamespace(manifest=bank.manifest, records=bank.records)
    elif mutation == "other_schema":
        bank.manifest["schema"] = learning.SCHEMA
    elif mutation == "policy":
        bank.manifest["retrieval_text_policy"] = "FULL_CONTENT"
    elif mutation in ("kind", "lesson"):
        row = bank.records[0]
        payload = json.loads(row["content"])
        payload["kind" if mutation == "kind" else "analyst_lesson"] = "unrelated_kind" if mutation == "kind" else []
        row["content"] = learning.canonical(payload).decode()
        report["entries"][0]["shared_source_content_sha256"] = learning.sha(row["content"].encode())
    elif mutation == "entry_id":
        report["entries"][0]["memory_id"] = "another-diagnostic"
    else:
        report["entries"][0]["shared_source_content_sha256"] = "0" * 64
    with pytest.raises((bridge.MemoryBridgeError, diagnostic.DiagnosticBankError)):
        bridge._repository_retrieval_texts(bank, report)
