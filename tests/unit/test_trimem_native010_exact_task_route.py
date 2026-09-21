"""Native010 same-task recovery routing; synthetic evidence, no model or grader."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.agent_runtime import RuntimeFailure
from enterprise_memory.trimem.skill_memory import SkillMemoryStore
from enterprise_memory.trimem import skill_runtime
from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController, SkillLayer
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec
from enterprise_memory.trimem.ppr import DeterministicHashEmbedder
import trimem_skhynix_codex_diagnostic_bank as diagnostic
import trimem_skhynix_codex_learning as learning
import trimem_skhynix_codex_memory as bridge
from test_trimem_skhynix_codex_diagnostic_bank import components, freeze, write
from test_trimem_skill_runtime import task


ROOT = Path(__file__).resolve().parents[2]
POLICY = diagnostic.EXACT_TASK_DIAGNOSTIC_ROUTE
ZERO_QUERY = {"node_id": "resume", "objective": "quuxxyzzy", "operation": "plughwombat"}


def working(value=None, node="resume"):
    value = value or task()
    graph = ShortTermWorkingGraph(value.task_id, value.instruction, value.repository)
    graph.add_subtask(SubtaskSpec(ZERO_QUERY["objective"], ZERO_QUERY["operation"], node_id=node))
    graph.activate(node)
    return graph


def put(store, **changes):
    return store.put_repository_knowledge(**{
        "org_id": "org", "repository": "repo", "revision": "rev1", "language": "python",
        "title": "Retained public diagnostic", "content": '{"source_official_resolved": false, "analyst_lesson": "Inspect parser"}',
        **changes})


@pytest.fixture
def prepared(tmp_path):
    prepared = components(tmp_path)
    prepared.receipt = freeze(prepared, retrieval_text_policy=POLICY)
    prepared.bank = learning.load_frozen_bank(prepared.path, prepared.receipt["sha256"], prepared.tasks[0])
    return prepared


def test_route_delivers_zero_lexical_overlap_without_score_inflation_or_wire_changes(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        row = put(store)
        normal = SkillFirstMemoryController(store, task_id="target")
        assert not normal.recall(working(), task()).injections
        controller = SkillFirstMemoryController(store, task_id="target",
            repository_exact_task_routes={row.knowledge_id: "target"})
        decision = controller.recall(working(), task())
        item, = decision.injections
        assert item.confidence == 0.0 and item.margin == 0.0
        assert item.kind == SkillLayer.REPOSITORY_SEMANTIC
        assert item.exact_text == normal._execution_view(row, SkillLayer.REPOSITORY_SEMANTIC)
        assert item.exact_utf8 == item.exact_text.encode() and item.verify()
        assert json.loads(item.exact_text)["content"] == row.content
        trace = decision.bank_trace[-1]
        assert trace["policy"] == POLICY
        assert trace["exact_task_route"] == {"policy": POLICY, "task_id": "target",
            "candidate_ids": [row.knowledge_id], "selected": True}
        assert not controller.recall(working(), task()).injections
        assert controller.context_for("resume") == (item,)
        assert not controller.recall(working(node="later"), task()).injections


def test_route_precedes_lexical_candidate_without_seeding_unrelated_graph_neighbors(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        routed = put(store)
        lexical = put(store, title="quuxxyzzy", content="plughwombat")
        neighbor = put(store, title="Bicycle", content="Sprocket")
        store.link_repository_knowledge(routed.knowledge_id, neighbor.knowledge_id, "uses",
            org_id="org", repository="repo")
        controller = SkillFirstMemoryController(store, task_id="target",
            repository_exact_task_routes={routed.knowledge_id: "target"})
        assert controller.recall(working(), task()).injections[0].memory_id == routed.knowledge_id
        second = controller.recall(working(node="later"), task())
        assert second.injections[0].memory_id == lexical.knowledge_id
        assert second.bank_trace[-1]["policy"] == "SKILL_REPO_EPISODE"
        assert second.bank_trace[-1]["eligible_count"] == 2
        assert not controller.recall(working(node="last"), task()).injections


def test_routes_are_copied_immutable_and_checkpoint_hash_bound(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        row = put(store)
        routes = {row.knowledge_id: "target"}
        controller = SkillFirstMemoryController(store, task_id="target", repository_exact_task_routes=routes)
        digest = controller.content_hash
        routes[row.knowledge_id] = "other-task"
        assert controller.content_hash == digest
        with pytest.raises(TypeError):
            controller._repository_exact_task_routes[row.knowledge_id] = "other-task"
        original = controller.recall(working(), task()).injections
        checkpoint = json.loads(json.dumps(controller.checkpoint_state()))
        restored = SkillFirstMemoryController(store, task_id="target",
            repository_exact_task_routes={row.knowledge_id: "target"})
        restored.restore(checkpoint)
        assert restored.context_for("resume") == original
        assert not restored.recall(working(), task()).injections
        for changed in (None, {}, routes):
            with pytest.raises(RuntimeFailure, match="configuration"):
                SkillFirstMemoryController(store, task_id="target",
                    repository_exact_task_routes=changed).restore(checkpoint)
        default = SkillFirstMemoryController(store, task_id="target")
        assert default.content_hash != digest
        assert default.content_hash == SkillFirstMemoryController(store, task_id="target",
            repository_exact_task_routes=None).content_hash
        lesson = SkillFirstMemoryController(store, task_id="target", repository_retrieval_texts={row.knowledge_id: "parser"})
        assert lesson.content_hash == SkillFirstMemoryController(store, task_id="target",
            repository_retrieval_texts={row.knowledge_id: "parser"}, repository_exact_task_routes=None).content_hash


@pytest.mark.parametrize("routes", [[], "EXACT_TASK_DIAGNOSTIC_ROUTE", {"skill:abc": "target"},
    {"knowledge:abc": ""}, {"knowledge:abc": False}, {1: "target"}])
def test_route_mapping_rejects_malformed_input(tmp_path, routes):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        with pytest.raises(ValueError, match="exact-task routes"):
            SkillFirstMemoryController(store, task_id="target", repository_exact_task_routes=routes)


@pytest.mark.parametrize("changes", [{"org_id": "other"}, {"repository": "other"},
    {"revision": "rev2"}, {"language": "java"}])
def test_route_cannot_import_an_out_of_scope_record(tmp_path, changes):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        row = put(store, **changes)
        controller = SkillFirstMemoryController(store, task_id="target",
            repository_exact_task_routes={row.knowledge_id: "target"})
        with pytest.raises(RuntimeFailure, match="scope"):
            controller.recall(working(), task())
        assert controller.checkpoint_state()["ledger"] == []


def test_route_target_must_match_bound_task_and_unknown_id_is_rejected(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        row = put(store)
        for routes in ({row.knowledge_id: "other-task"}, {"knowledge:absent": "target"}):
            controller = SkillFirstMemoryController(store, task_id="target", repository_exact_task_routes=routes)
            with pytest.raises(RuntimeFailure, match="scope"):
                controller.recall(working(), task())
        controller = SkillFirstMemoryController(store, task_id="target",
            repository_exact_task_routes={row.knowledge_id: "target"})
        controller.recall(working(), task())
        for changed in (replace(task(), task_id="other-task"), replace(task(), commit="rev2"),
                replace(task(), repository="other-repo")):
            with pytest.raises(RuntimeFailure, match="scope"):
                controller.recall(working(changed), changed)


@pytest.mark.parametrize("before_delivery", [True, False])
def test_routes_obey_revocation_on_recall_context_and_checkpoint_restore(tmp_path, before_delivery):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        row = put(store)
        kwargs = {"task_id": "target", "repository_exact_task_routes": {row.knowledge_id: "target"}}
        controller = SkillFirstMemoryController(store, **kwargs)
        if not before_delivery:
            controller.recall(working(), task())
        else:
            controller._bind(task())
        checkpoint = json.loads(json.dumps(controller.checkpoint_state()))
        store.invalidate_repository(org_id="org", repository="repo", current_revision="rev2")
        with pytest.raises(RuntimeFailure, match="revoked|scope"):
            controller.recall(working(), task())
        with pytest.raises(RuntimeFailure, match="revoked|scope"):
            controller.context_for("resume")
        with pytest.raises(RuntimeFailure, match="checkpoint"):
            SkillFirstMemoryController(store, **kwargs).restore(checkpoint)


@pytest.mark.parametrize("offset", [-1, 0])
def test_exact_route_respects_full_wire_byte_budget_boundary(tmp_path, offset):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        row = put(store, content="진단" * 200)
        default = SkillFirstMemoryController(store, task_id="target")
        size = len(default._execution_view(row, SkillLayer.REPOSITORY_SEMANTIC).encode())
        controller = SkillFirstMemoryController(store, task_id="target", context_budget_bytes=size + offset,
            repository_exact_task_routes={row.knowledge_id: "target"})
        result = controller.recall(working(), task())
        assert len(result.injections) == int(offset == 0)
        if offset < 0:
            assert result.rejections[-1]["reason"] == "CONTEXT_INJECTION_BUDGET"
            trace = next(row for row in result.bank_trace if row["bank"] == "REPOSITORY_SEMANTIC")
            assert trace["exact_task_route"]["selected"] is False
        else:
            assert result.injections[0].byte_count == size


def test_exact_route_preserves_default_three_injection_limit_and_restore_budget(tmp_path):
    with SkillMemoryStore(tmp_path / "memory.sqlite") as store:
        routes = {put(store, title=f"Retained diagnostic {index}").knowledge_id: "target" for index in range(4)}
        kwargs = {"task_id": "target", "repository_exact_task_routes": routes}
        controller = SkillFirstMemoryController(store, **kwargs)
        assert controller.max_injections_per_task == 3 and controller.context_budget_bytes == 12000
        for index in range(4):
            result = controller.recall(working(node=f"step{index}"), task())
            assert len(result.injections) == int(index < 3)
        assert any(row["reason"] == "CONTEXT_INJECTION_BUDGET" for row in result.rejections)
        checkpoint = deepcopy(controller.checkpoint_state())
        restored = SkillFirstMemoryController(store, **kwargs)
        restored.restore(checkpoint)
        assert len(restored.checkpoint_state()["ledger"]) == 3
        with pytest.raises(RuntimeFailure, match="configuration"):
            SkillFirstMemoryController(store, **kwargs, max_injections_per_task=4).restore(checkpoint)
        checkpoint["ledger"].append(deepcopy(checkpoint["ledger"][0]))
        with pytest.raises(RuntimeFailure, match="checkpoint"):
            restored.restore(checkpoint)


@pytest.mark.parametrize("arm", ["NO_MEMORY", "EXISTING_M2", "SKHYNIX"])
def test_real_bridge_routes_first_recall_and_replays_full_failed_wire(prepared, tmp_path, monkeypatch, arm):
    task = prepared.tasks[0]
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))
    kwargs = {"frozen_bank_path": prepared.path, "frozen_bank_sha256": prepared.receipt["sha256"]}
    cell = tmp_path / arm
    manifest = bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)
    result = bridge.recall_memory(cell, task, arm, ZERO_QUERY, ROOT, **kwargs)
    assert result["new_injection_count"] == int(arm == "SKHYNIX")
    assert manifest["verified_skill_payload_count"] == manifest["seed_skill_count"] == 0
    assert result["budget"]["max_task_injections"] == 3
    assert result["budget"]["context_budget_bytes"] == 12000
    assert result["model_api_calls"] == 0
    if arm == "SKHYNIX":
        item, = result["injections"]
        content = json.loads(item["exact_text"])["content"]
        assert content == prepared.bank.records[0]["content"]
        assert not skill_runtime._tokens("quuxxyzzy plughwombat") & skill_runtime._tokens(item["exact_text"])
        assert item["confidence"] == 0.0
        assert result["decisions"][-1]["policy"] == POLICY
        payload = json.loads(content)
        for key in ("source_official_resolved", "analyst_interpretation_verified", "target_fix_verified", "verified_skill"):
            assert payload[key] is False
        assert payload["source_task_id"] == task.task_id and payload["source_revision"] == task.commit
        assert payload["source_evidence_label"] == diagnostic.LABEL
        assert result["budget"]["bytes_used"] == len(item["exact_text"].encode())
    replay = bridge.recall_memory(cell, task, arm, ZERO_QUERY, ROOT, **kwargs)
    assert replay["repeat"] and replay["new_injection_count"] == 0
    assert replay["injections"] == result["injections"] and replay["budget"] == result["budget"]
    later = bridge.recall_memory(cell, task, arm, {**ZERO_QUERY, "node_id": "later"}, ROOT, **kwargs)
    assert later["injections"] == [] and later["budget"] == result["budget"]
    assert bridge.initialize_memory(cell, task, arm, ROOT, **kwargs)["binding_sha256"] == manifest["binding_sha256"]


@pytest.mark.parametrize("changes", [{"task_id": "unknown"}, {"commit": "f" * 40},
    {"repository": "other/repo"}, {"instruction": "different public instruction"}])
def test_exact_policy_load_rejects_wrong_full_target_identity(prepared, changes):
    with pytest.raises(diagnostic.DiagnosticBankError, match="scope"):
        learning.load_frozen_bank(prepared.path, prepared.receipt["sha256"], replace(prepared.tasks[0], **changes))


def test_each_task_gets_only_its_own_exact_source_from_multi_task_bank(prepared):
    seen = set()
    for task in prepared.tasks:
        bank = learning.load_frozen_bank(prepared.path, prepared.receipt["sha256"], task)
        store, report = learning.build_learned_seeded_store(":memory:", task, bank)
        try:
            routes = bridge._repository_exact_task_routes(bank, report, task)
            assert bridge._repository_retrieval_texts(bank, report) is None
            assert len(routes) == len(bank.records) == 1
            assert set(routes.values()) == {task.task_id}
            controller = SkillFirstMemoryController(store, task_id=task.task_id, repository_exact_task_routes=routes)
            result = controller.recall(working(task), task)
            item, = result.injections
            assert json.loads(json.loads(item.exact_text)["content"])["source_task_id"] == task.task_id
            seen.add(item.memory_id)
        finally:
            store.close()
    assert len(seen) == 2


@pytest.mark.parametrize("policy", [None, diagnostic.DIAGNOSTIC_LESSON_CONTENT])
def test_existing_policies_cannot_implicitly_enable_exact_task_route(tmp_path, policy):
    prepared = components(tmp_path)
    receipt = freeze(prepared, retrieval_text_policy=policy)
    bank = learning.load_frozen_bank(prepared.path, receipt["sha256"], prepared.tasks[0])
    store, report = learning.build_learned_seeded_store(":memory:", prepared.tasks[0], bank)
    try:
        assert bridge._repository_exact_task_routes(bank, report, prepared.tasks[0]) is None
        controller = SkillFirstMemoryController(store, task_id=prepared.tasks[0].task_id,
            repository_retrieval_texts=bridge._repository_retrieval_texts(bank, report))
        assert not controller.recall(working(prepared.tasks[0]), prepared.tasks[0]).injections
    finally:
        store.close()


def test_new_policy_changes_only_optional_manifest_field_and_retains_gate_and_record_bytes(tmp_path):
    prepared = components(tmp_path)
    receipt = freeze(prepared)
    old = learning.load_frozen_bank(prepared.path, receipt["sha256"], prepared.tasks[0])
    original = prepared.path.read_bytes()
    write(prepared.path, {**old.manifest, "retrieval_text_policy": POLICY})
    enabled = learning.load_frozen_bank(prepared.path, learning.file_sha(prepared.path), prepared.tasks[0])
    assert enabled.records == old.records and enabled.manifest["gate_a"] == old.manifest["gate_a"]
    manifest = deepcopy(enabled.manifest)
    manifest.pop("retrieval_text_policy")
    assert learning.canonical(manifest) + b"\n" == original
    assert enabled.promoted_skill is None and enabled.report["verified_skill_count"] == 0


@pytest.mark.parametrize("scenario", ["DISJOINT_TRANSFER", None, "UNKNOWN"])
def test_exact_policy_freeze_rejects_other_scenarios_before_writing(tmp_path, scenario):
    prepared = components(tmp_path)
    target = replace(prepared.tasks[0], task_id="disjoint-target")
    with pytest.raises(diagnostic.DiagnosticBankError, match="KNOWN_FAILURE_RECOVERY"):
        freeze(prepared, retrieval_text_policy=POLICY, scenario=scenario, tasks=[target])
    assert not prepared.path.exists() and not prepared.path.with_name("bank.gate-a-private.sqlite3").exists()


def test_transfer_cannot_opt_in_by_rehashing_its_manifest(tmp_path):
    prepared = components(tmp_path)
    target = replace(prepared.tasks[0], task_id="disjoint-target")
    freeze(prepared, scenario="DISJOINT_TRANSFER", tasks=[target])
    manifest = learning.read(prepared.path)
    write(prepared.path, {**manifest, "retrieval_text_policy": POLICY})
    with pytest.raises(diagnostic.DiagnosticBankError, match="KNOWN_FAILURE_RECOVERY"):
        learning.load_frozen_bank(prepared.path, learning.file_sha(prepared.path), target)


@pytest.mark.parametrize("mutation", ["fake_bank", "policy", "scenario", "manifest", "target", "entry_id",
    "knowledge_id", "entry_hash", "entry_revision", "snapshot", "language", "other_task"])
def test_bridge_route_requires_validated_bank_exact_task_and_actual_seed_projection(prepared, mutation):
    bank, task = prepared.bank, prepared.tasks[0]
    store, report = learning.build_learned_seeded_store(":memory:", task, bank)
    store.close()
    if mutation == "fake_bank":
        bank = SimpleNamespace(manifest=bank.manifest, records=bank.records)
    elif mutation == "policy":
        bank.manifest["retrieval_text_policy"] = "UNVALIDATED_ROUTE"
    elif mutation == "scenario":
        bank.manifest["scenario"] = "DISJOINT_TRANSFER"
    elif mutation == "manifest":
        bank.records[0]["content"] += " "
    elif mutation == "target":
        bank.target["commit"] = "f" * 40
    elif mutation == "entry_id":
        report["entries"][0]["memory_id"] = "another-record"
    elif mutation == "knowledge_id":
        report["entries"][0]["knowledge_id"] = "knowledge:unseeded"
    elif mutation == "entry_hash":
        report["entries"][0]["shared_source_content_sha256"] = "f" * 64
    elif mutation == "entry_revision":
        report["entries"][0]["transfer_view_revision"] = "f" * 40
    elif mutation == "snapshot":
        report["seed_snapshot_sha256"] = "f" * 64
    elif mutation == "language":
        report["language"] = "java"
    else:
        task = prepared.tasks[1]
    with pytest.raises((bridge.MemoryBridgeError, diagnostic.DiagnosticBankError)):
        bridge._repository_exact_task_routes(bank, report, task)


@pytest.mark.parametrize("source", ["probe", "patch", "authority"])
def test_exact_policy_still_revalidates_external_source_hashes(prepared, source):
    path = {"probe": prepared.probe,
        "patch": Path(prepared.sources[0]["run_root"]) / "cells/A/submission.diff",
        "authority": prepared.path.with_name(prepared.bank.manifest["gate_a"]["private_store_filename"])}[source]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(learning.LearnedBankError, match="hash"):
        learning.load_frozen_bank(prepared.path, prepared.receipt["sha256"], prepared.tasks[0])
