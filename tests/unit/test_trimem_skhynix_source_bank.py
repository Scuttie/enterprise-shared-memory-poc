"""Check real historical content parity and provenance rejection boundaries."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_skhynix_source_bank as importer
from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.skill_runtime import SkillFirstMemoryController
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


@pytest.fixture(scope="module")
def validated():
    return importer.load_validated_source_bank(ROOT)


@pytest.fixture(scope="module")
def tasks(validated):
    cache = json.loads((ROOT / importer.historical.CHRONOLOGY_PATH).read_text(encoding="utf-8"))
    instructions = {row["target_id"]: row["public_instruction"] for row in cache["targets"]}
    return [CodingTask(
        task_id=row["target_id"], org_id="new-pilot-org", user_id="pilot-reader",
        repository=row["repository"], commit=row["base_commit"],
        instruction=instructions[row["target_id"]], files={}, editable_paths=(),
    ) for row in validated.targets_by_id.values()]


def test_all_real_dev_sources_preserve_content_without_fabricating_skills(validated, tasks, tmp_path):
    assert validated.report["covered_target_count"] == 12
    assert validated.report["source_ci_results_observed"] is False
    for index, task in enumerate(tasks):
        old = importer.build_legacy_source_store(task, bank=validated)
        store, report = importer.build_seeded_store(tmp_path / f"{index}.sqlite3", task, bank=validated)
        with store:
            target = validated.targets_by_id[task.task_id]
            snap = store.snapshot(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
                                  revision=task.commit, language=target["language"])
            assert {entry.content.encode("utf-8") for entry in snap.repository_knowledge} == set(old.execution_views.values())
            assert report["repository_knowledge_count"] == 1
            assert report["verified_skill_count"] == report["imported_episode_count"] == 0
            assert not snap.skills and not snap.episodes
            assert report["l3_effect_claim_allowed"] is False


def test_imported_historical_knowledge_is_retrievable_and_revision_scoped(validated, tasks):
    task = tasks[0]
    store, _ = importer.build_seeded_store(":memory:", task, bank=validated)
    with store:
        controller = SkillFirstMemoryController(store, task_id=task.task_id, language="python")
        graph = ShortTermWorkingGraph(task.task_id, task.instruction, task.repository)
        node = graph.add_subtask(SubtaskSpec(node_id="S1", objective=task.instruction,
                                           operation="repair transaction handling", files=()))
        graph.activate(node.node_id)
        decision = controller.recall(graph, task)
        assert len(decision.injections) == 1
        injected = decision.injections[0]
        assert injected.kind.value == "REPOSITORY_SEMANTIC"
        assert injected.byte_count <= 12_000
        view = json.loads(injected.exact_text)
        assert view["content"].encode("utf-8") in importer.build_legacy_source_store(task, bank=validated).execution_views.values()
        assert not store.snapshot(org_id=task.org_id, user_id=task.user_id, repository=task.repository,
                                  revision="different-revision", language="python").repository_knowledge
        assert not store.snapshot(org_id="different-org", user_id=task.user_id, repository=task.repository,
                                  revision=task.commit, language="python").repository_knowledge


@pytest.mark.parametrize("changes", [
    {"commit": "0" * 40}, {"repository": "different/repository"},
    {"instruction": "A different public problem"}, {"task_id": "unregistered-task"},
])
def test_scope_and_public_instruction_drift_are_rejected(validated, tasks, changes):
    with pytest.raises(importer.SourceBankImportError):
        importer.build_legacy_source_store(replace(tasks[0], **changes), bank=validated)


def test_existing_evidence_is_not_overwritten(validated, tasks, tmp_path):
    path = tmp_path / "existing.sqlite3"
    path.write_bytes(b"prior evidence")
    with pytest.raises(FileExistsError):
        importer.build_seeded_store(path, tasks[0], bank=validated)
    assert path.read_bytes() == b"prior evidence"


def test_chronology_rebuild_drift_is_rejected(monkeypatch):
    original = importer.historical.build_oracle_source_bank

    def changed(*args, **kwargs):
        bank, payloads = original(*args, **kwargs)
        bank["records"][0]["source_commit"] = "0" * 40
        return bank, payloads

    monkeypatch.setattr(importer.historical, "build_oracle_source_bank", changed)
    with pytest.raises(importer.SourceBankImportError, match="differs from frozen"):
        importer.load_validated_source_bank(ROOT)
