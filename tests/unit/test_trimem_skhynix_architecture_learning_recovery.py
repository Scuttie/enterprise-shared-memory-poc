"""Real public captures and SQLite snapshots; no models, graders or source reruns."""
from pathlib import Path
import fcntl
import sqlite3

import pytest

import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_pipeline as core
import trimem_skhynix_architecture_learning_recovery as recovery
import trimem_skhynix_architecture_run as execution
import enterprise_memory.trimem.skill_memory as skill_memory
import trimem_skhynix_architecture_publisher as publisher
from test_trimem_skhynix_architecture_learning import inputs, captured, proposal, write


def tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def event(root, body):
    value = {"sequence": 1, "previous_sha256": "0" * 64, "at": 1789360000.0,
             "job": None, **body}
    value["sha256"] = memory._hash(value)
    return write(root / "events/00000001.json", value)


@pytest.fixture
def authority(inputs):
    captured(inputs)
    # Retain an actual previous empty reflection/ingestion too. Those pointers
    # must remain valid in the clone without treating [] as a Gate B pass.
    public = learning.export_reflection(inputs.root, inputs.tmp / "old-reflection.json")
    empty = write(inputs.tmp / "old-proposal.json", {"schema": learning.PROPOSALS_SCHEMA,
                  "reflection_sha256": public["sha256"], "proposals": []})
    learning.ingest_proposals(inputs.root, empty, reflection_reference=public)
    source_root = Path(learning.__file__).resolve().parent.parent
    runtime = write(inputs.tmp / "runtime.json", {
        "model": "gpt-6-astra", "reasoning_effort": "high", "authentication": "CHATGPT",
        "codex_binary": "C:/fixed/codex.exe", "windows_python": "C:/Python/python.exe",
        "source_root": str(source_root), "source_sha256": {
            Path(module.__file__).resolve().relative_to(source_root).as_posix(): memory._file_hash(module.__file__)
            for module in (learning, memory, core, execution, skill_memory)}})
    root = inputs.tmp / "pipeline"
    root.mkdir()
    (root / "run.lock").touch()
    pipeline = {"schema": "skhynix/architecture-scale-pipeline/1.0", "pipeline_root": str(root),
                "helper_references": {"publisher": memory._ref(publisher.__file__)},
                "training_experiment_reference": runtime, "training_stages": [
                    {"size": 2, "learning_root": str(inputs.root), "execution_reference": inputs.execution}]}
    pipeline_ref = write(inputs.tmp / "pipeline.json", pipeline, sidecar=True)
    write(root / "pipeline-binding.json", {"schema": pipeline["schema"], "configuration_reference": pipeline_ref})
    tail = event(root, {"stage": "NO_READY_MEMORY_BANK", "details": {
        "gate_b_waived": False, "final_evaluation_cells": 0, "banks": [{"size": 2,
        "status": "NOT_READY", "source_attempts": 2, "bank_reference": None,
        "catalog_reference": memory._ref(inputs.root / "catalog.json")}]}})
    return {"source_root": inputs.root, "destination_root": inputs.tmp / "recovered",
            "predecessor_pipeline_reference": pipeline_ref,
            "predecessor_pipeline_event_tail_reference": tail}


def test_clone_reuses_exact_original_evidence_and_real_gate_b_remains_required(inputs, authority, monkeypatch):
    before = tree(inputs.root)
    monkeypatch.setattr(learning, "capture_cell", lambda *a, **k: pytest.fail("No source recapture is allowed"))
    reference = recovery.clone_learning_authority(**authority)
    receipt = core.check(reference)
    clone = authority["destination_root"]
    assert receipt["counts"] == {"training_sources": 2, "captures": 6,
        "L1_episodes": 6, "L2_nodes": 12, "L2_edges": 6, "L3_skills": 0}
    assert receipt["model_calls"] == receipt["solver_runs"] == receipt["official_grader_runs"] == receipt["source_recaptures"] == 0
    assert receipt["gate_b_waived"] is False
    assert receipt["recovery_helper_reference"] == memory._ref(recovery.__file__)
    assert tree(inputs.root) == before
    assert (clone / "catalog.json").read_bytes() == before["catalog.json"]
    assert (clone / "learning-state.json").read_bytes() == before["learning-state.json"]
    assert memory._read(clone / "learning-enrollment.ref.json") == memory._ref(clone / "learning-enrollment.json")
    with pytest.raises(ValueError, match="Gate B"):
        learning.freeze_published_bank(clone, inputs.tmp / "too-early.json")
    exported = learning.export_reflection(clone, inputs.tmp / "new-reflection.json")
    verified = learning.ingest_proposals(clone, proposal(inputs, exported), reflection_reference=exported)
    assert core.check(verified)["promotions_added"] == 1
    published = learning.freeze_published_bank(clone, inputs.tmp / "recovered-bank.json")
    assert published["layer_counts"]["L3_skills"] == 1
    assert tree(inputs.root) == before
    for ref in receipt["clone_initial_references"].values():
        memory._check_ref(ref)
    for ref in receipt["original_evidence_references"]:
        memory._check_ref(ref)


@pytest.mark.parametrize("kind", ["existing", "same", "nested", "ancestor"])
def test_destination_cannot_overwrite_or_enter_original_authority(inputs, authority, kind):
    if kind == "existing":
        authority["destination_root"].mkdir()
    elif kind == "same":
        authority["destination_root"] = inputs.root
    elif kind == "nested":
        authority["destination_root"] = inputs.root / "bad"
    else:
        authority["destination_root"] = inputs.root.parent
    with pytest.raises(recovery.RecoveryError, match="fresh and separate"):
        recovery.clone_learning_authority(**authority)


def test_predecessor_tail_advancement_rejected_before_clone(inputs, authority):
    root = Path(core.check(authority["predecessor_pipeline_reference"])["pipeline_root"])
    write(root / "events/00000002.json", {"untrusted": "advanced"})
    with pytest.raises(recovery.RecoveryError, match="advanced"):
        recovery.clone_learning_authority(**authority)
    assert not authority["destination_root"].exists()


@pytest.mark.parametrize("filename", ["catalog.json", "captures", "state", "reflection", "proposal"])
def test_changed_original_evidence_rejected(inputs, authority, filename):
    if filename == "captures":
        path = next((inputs.root / "captures").glob("*.json"))
    elif filename == "state":
        registry = memory._read(inputs.root / "learning-state.json")
        cell = core.check(next(iter(registry["cells"].values())))
        path = Path(cell["source_references"]["state.json"]["path"])
    elif filename == "reflection":
        path = inputs.tmp / "old-reflection.json"
    elif filename == "proposal":
        path = inputs.tmp / "old-proposal.json"
    else:
        path = inputs.root / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, RuntimeError)):
        recovery.clone_learning_authority(**authority)
    assert not authority["destination_root"].exists()


@pytest.mark.parametrize("name", ["run", "learning", "operation"])
def test_active_predecessor_lock_rejected_without_waiting(inputs, authority, name):
    root = Path(core.check(authority["predecessor_pipeline_reference"])["pipeline_root"]) if name == "run" else inputs.root
    with (root / (name + ".lock")).open("r+b") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(recovery.RecoveryError, match="still active"):
            recovery.clone_learning_authority(**authority)
    assert not authority["destination_root"].exists()


def test_unpublished_original_required(inputs, authority):
    write(inputs.root / "frozen.json", {"unexpected": True})
    with pytest.raises(recovery.RecoveryError, match="unpublished"):
        recovery.clone_learning_authority(**authority)


def test_corrupt_sqlite_authority_is_not_laundered_by_copy(inputs, authority):
    with sqlite3.connect(inputs.root / "authority.sqlite3") as db:
        db.execute("DELETE FROM memory_records WHERE record_id=(SELECT record_id FROM memory_records LIMIT 1)")
    with pytest.raises(ValueError, match="ungrounded"):
        recovery.clone_learning_authority(**authority)
    assert not authority["destination_root"].exists()


def test_original_mutation_during_copy_prevents_completed_receipt(inputs, authority, monkeypatch):
    original = recovery.shutil.copyfile
    def mutate(source, destination):
        result = original(source, destination)
        path = inputs.root / "learning-state.json"
        path.write_bytes(path.read_bytes() + b" ")
        return result
    monkeypatch.setattr(recovery.shutil, "copyfile", mutate)
    with pytest.raises(ValueError, match="changed"):
        recovery.clone_learning_authority(**authority)
    assert not (authority["destination_root"] / "learning-recovery.json").exists()
    with pytest.raises(recovery.RecoveryError, match="fresh"):
        recovery.clone_learning_authority(**authority)


def test_runtime_hash_binding_rejects_wrong_module(inputs, authority, monkeypatch):
    monkeypatch.setattr(learning, "__file__", str(inputs.tmp / "untrusted.py"))
    with pytest.raises(recovery.RecoveryError, match="escaped"):
        recovery.clone_learning_authority(**authority)
    assert not authority["destination_root"].exists()


def test_missing_captured_source_cannot_be_reclassified_as_complete(inputs, authority):
    path = inputs.root / "learning-state.json"
    state = memory._read(path)
    state["cells"].pop(next(iter(state["cells"])))
    memory._write(path, state)
    with pytest.raises(recovery.RecoveryError, match="every original enrolled source"):
        recovery.clone_learning_authority(**authority)
    assert not authority["destination_root"].exists()


def test_active_database_journal_is_rejected(inputs, authority):
    (inputs.root / "authority.sqlite3-wal").write_bytes(b"active")
    with pytest.raises(ValueError, match="active journal"):
        recovery.clone_learning_authority(**authority)
    assert not authority["destination_root"].exists()


def test_request_receipt_binds_exact_clone_destination(inputs, authority):
    request = write(inputs.tmp / "clone-request.json", {
        key: str(value) if isinstance(value, Path) else value for key, value in authority.items()})
    changed = {**authority, "destination_root": inputs.tmp / "other-destination", "request_reference": request}
    with pytest.raises(recovery.RecoveryError, match="exact immutable arguments"):
        recovery.clone_learning_authority(**changed)
    assert not changed["destination_root"].exists()
