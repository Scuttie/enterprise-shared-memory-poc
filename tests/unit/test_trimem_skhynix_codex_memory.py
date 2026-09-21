"""Exercise the local bridge with actual historical source rows and controllers."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import trimem_skhynix_codex_memory as bridge
import trimem_skhynix_source_bank as source
from enterprise_memory.trimem.agent_runtime import CodingTask
from enterprise_memory.trimem.ppr import DeterministicHashEmbedder


@pytest.fixture(scope="module")
def bank():
    return source.load_validated_source_bank(ROOT)


@pytest.fixture
def task(bank):
    cache = json.loads((ROOT / source.historical.CHRONOLOGY_PATH).read_text(encoding="utf-8"))
    row = next(iter(bank.targets_by_id.values()))
    instruction = next(item["public_instruction"] for item in cache["targets"]
                       if item["target_id"] == row["target_id"])
    return CodingTask(task_id=row["target_id"], org_id="codex-pilot-test",
                      user_id="native-solver", repository=row["repository"],
                      commit=row["base_commit"], instruction=instruction,
                      files={}, editable_paths=())


@pytest.fixture(autouse=True)
def test_only_embedding(monkeypatch):
    # The production bridge has no fallback. This explicit fixture exercises
    # the real M2 retriever without requiring Windows to download model weights.
    monkeypatch.setattr(bridge, "_m2_embedder", lambda: DeterministicHashEmbedder(384))


def query(task, node="repair-savepoint"):
    return {"node_id": node, "objective": task.instruction,
            "operation": "repair transaction handling", "symbols": ["transaction"]}


def read_state(cell):
    return bridge._read(cell / "memory-private/checkpoint.json")["state"]


def test_no_memory_never_loads_source_or_embedding(task, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("no-memory must not open a bank or embedder")
    monkeypatch.setattr(bridge, "load_validated_source_bank", forbidden)
    monkeypatch.setattr(bridge, "_m2_embedder", forbidden)
    manifest = bridge.initialize_memory(tmp_path, task, "NO_MEMORY", ROOT)
    result = bridge.recall_memory(tmp_path, task, "NO_MEMORY", query(task), ROOT)
    assert manifest["bank"]["records"] == 0
    assert result["injections"] == [] and result["budget"]["bytes_used"] == 0
    assert result["decisions"][0]["reason"] == "M0_NO_MEMORY"
    assert not manifest["native_context_replacement"] and manifest["model_api_calls"] == 0
    assert set(p.name for p in (tmp_path / "memory-private").iterdir()) == {"checkpoint.json"}


@pytest.mark.parametrize("arm", ["EXISTING_M2", "SKHYNIX"])
def test_actual_source_content_retrieval_and_cross_invocation_persistence(task, bank, tmp_path, arm):
    manifest = bridge.initialize_memory(tmp_path, task, arm, ROOT)
    first = bridge.recall_memory(tmp_path, task, arm, query(task), ROOT)
    assert first["injections"] and first["new_injection_count"] == 1
    item = first["injections"][0]
    content = json.loads(item["exact_text"])["content"] if arm == "SKHYNIX" else item["exact_text"]
    assert content.encode() in source.build_legacy_source_store(task, bank=bank).execution_views.values()
    assert item["byte_count"] == len(item["exact_text"].encode()) <= 12_000
    again = bridge.recall_memory(tmp_path, task, arm, query(task), ROOT)
    assert again["repeat"] and again["new_injection_count"] == 0
    assert again["injections"] == first["injections"] and again["budget"] == first["budget"]
    reinitialized = bridge.initialize_memory(tmp_path, task, arm, ROOT)
    assert reinitialized["binding_sha256"] == manifest["binding_sha256"]
    assert reinitialized["budget"]["injections_used"] == 1
    assert read_state(tmp_path)["calls"] == 2
    assert manifest["seed_episode_count"] == manifest["seed_skill_count"] == 0


@pytest.mark.parametrize("arm", bridge.ARMS)
def test_changed_node_query_is_rejected_and_checkpoint_untouched(task, tmp_path, arm):
    bridge.initialize_memory(tmp_path, task, arm, ROOT)
    original = query(task)
    bridge.recall_memory(tmp_path, task, arm, original, ROOT)
    before = (tmp_path / "memory-private/checkpoint.json").read_bytes()
    with pytest.raises(bridge.MemoryBridgeError, match="different semantic query"):
        bridge.recall_memory(tmp_path, task, arm, {**original, "operation": "inspect a different exception"}, ROOT)
    assert (tmp_path / "memory-private/checkpoint.json").read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"org_id": "another-tenant"}, {"user_id": "another-user"},
    {"repository": "different/repo"}, {"commit": "0" * 40},
    {"instruction": "different public instruction"},
])
def test_no_memory_checkpoint_binds_full_task_scope(task, tmp_path, changes):
    bridge.initialize_memory(tmp_path, task, "NO_MEMORY", ROOT)
    with pytest.raises(bridge.MemoryBridgeError, match="identity"):
        bridge.recall_memory(tmp_path, replace(task, **changes), "NO_MEMORY", query(task), ROOT)


def test_copying_checkpoint_to_another_cell_fails(task, tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    bridge.initialize_memory(first, task, "NO_MEMORY", ROOT)
    shutil.copytree(first, second)
    with pytest.raises(bridge.MemoryBridgeError, match="identity"):
        bridge.recall_memory(second, task, "NO_MEMORY", query(task), ROOT)


@pytest.mark.parametrize("arm", ["EXISTING_M2", "SKHYNIX"])
def test_new_subgoals_cannot_reinject_same_historical_source(task, tmp_path, arm):
    bridge.initialize_memory(tmp_path, task, arm, ROOT)
    first = bridge.recall_memory(tmp_path, task, arm, query(task), ROOT)
    for index in range(4):
        later = bridge.recall_memory(tmp_path, task, arm, query(task, f"next-{index}"), ROOT)
        assert later["injections"] == []
        assert later["budget"] == first["budget"]
    assert first["budget"]["injections_used"] == 1


def test_oversized_real_source_abstains_before_injection(task, tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "MAX_BYTES", 128)
    bridge.initialize_memory(tmp_path, task, "SKHYNIX", ROOT)
    result = bridge.recall_memory(tmp_path, task, "SKHYNIX", query(task), ROOT)
    assert not result["injections"] and result["budget"]["bytes_used"] == 0
    assert any(row["reason"] == "CONTEXT_INJECTION_BUDGET" for row in result["rejections"])


def test_tampered_checkpoint_integrity_is_rejected(task, tmp_path):
    bridge.initialize_memory(tmp_path, task, "NO_MEMORY", ROOT)
    path = tmp_path / "memory-private/checkpoint.json"
    envelope = bridge._read(path)
    envelope["state"]["calls"] = 999
    bridge._write(path, envelope)
    with pytest.raises(bridge.MemoryBridgeError, match="integrity"):
        bridge.recall_memory(tmp_path, task, "NO_MEMORY", query(task), ROOT)


def test_budget_cannot_be_bypassed_by_rehashed_checkpoint(task, tmp_path):
    bridge.initialize_memory(tmp_path, task, "SKHYNIX", ROOT)
    bridge.recall_memory(tmp_path, task, "SKHYNIX", query(task), ROOT)
    state = read_state(tmp_path)
    state["controller"]["ledger"] *= 4
    bridge._save_state(tmp_path / "memory-private", state)
    with pytest.raises(bridge.MemoryBridgeError, match="budget"):
        bridge.recall_memory(tmp_path, task, "SKHYNIX", query(task, "new-node"), ROOT)


def test_changed_private_source_is_rejected(task, tmp_path):
    bridge.initialize_memory(tmp_path, task, "SKHYNIX", ROOT)
    path = tmp_path / "memory-private/historical-source-projection.json"
    value = bridge._read(path)
    value["execution_views"] = {}
    bridge._write(path, value)
    with pytest.raises(bridge.MemoryBridgeError, match="source projection differs"):
        bridge.recall_memory(tmp_path, task, "SKHYNIX", query(task), ROOT)


def test_changed_sqlite_seed_is_rejected_even_before_first_recall(task, tmp_path):
    bridge.initialize_memory(tmp_path, task, "SKHYNIX", ROOT)
    with bridge.SkillMemoryStore(tmp_path / "memory-private/source-memory.sqlite3") as store:
        store.put_repository_knowledge(org_id=task.org_id, repository=task.repository,
                                       title="A new unapproved source", content="not historical evidence",
                                       revision=task.commit, language="python")
    with pytest.raises(bridge.MemoryBridgeError, match="immutable seed"):
        bridge.recall_memory(tmp_path, task, "SKHYNIX", query(task), ROOT)


@pytest.mark.parametrize("changes", [
    {"node_id": "../escape"}, {"node_id": ""}, {"objective": ""},
    {"operation": ""}, {"symbols": "not-a-list"}, {"secret": "unknown field"},
    {"errors": [1]}, {"objective": "x" * 8193},
])
def test_invalid_query_is_rejected_before_writing_state(task, tmp_path, changes):
    with pytest.raises(bridge.MemoryBridgeError):
        bridge.recall_memory(tmp_path, task, "NO_MEMORY", {**query(task), **changes}, ROOT)
    assert not (tmp_path / "memory-private").exists()


def test_recall_requires_initialization(task, tmp_path):
    with pytest.raises(bridge.MemoryBridgeError, match="initialized"):
        bridge.recall_memory(tmp_path, task, "NO_MEMORY", query(task), ROOT)


def test_concurrent_operation_fails_closed(task, tmp_path):
    bridge.initialize_memory(tmp_path, task, "NO_MEMORY", ROOT)
    with bridge._locked(tmp_path):
        with pytest.raises(bridge.MemoryBridgeError, match="another memory operation"):
            bridge.recall_memory(tmp_path, task, "NO_MEMORY", query(task), ROOT)


def test_offline_embedding_flags_are_enforced_and_restored(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    with bridge._offline_embeddings():
        assert bridge.os.environ["HF_HUB_OFFLINE"] == "1"
        assert bridge.os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert bridge.os.environ["HF_HUB_OFFLINE"] == "0"
    assert "TRANSFORMERS_OFFLINE" not in bridge.os.environ
