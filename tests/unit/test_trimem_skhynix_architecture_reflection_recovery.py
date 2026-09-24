"""Real verified clone publication, synthetic native receipts and no execution."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import time
import sys

import pytest

import trimem_skhynix_architecture_learning as learning
import trimem_skhynix_architecture_memory as memory
import trimem_skhynix_architecture_pipeline as core
import trimem_skhynix_architecture_publisher as publisher
import trimem_skhynix_architecture_scale_pipeline as scale
import trimem_skhynix_architecture_learning_recovery as cloning
import trimem_skhynix_architecture_reflection_recovery as recovery
from test_trimem_skhynix_architecture_learning import inputs, proposal, write
from test_trimem_skhynix_architecture_learning_recovery import authority


@pytest.fixture
def publication(inputs, authority, monkeypatch):
    monkeypatch.setattr(recovery, "RECOVERED_SIZE", 2)
    clone_ref = cloning.clone_learning_authority(**authority)
    clone = authority["destination_root"]
    with learning._session(clone, mutable=False) as (_, _, registry, _):
        available = learning._available_captures(clone, registry)
    chosen = {key: value for key, value in available.items() if value[2]["checkpoint"]["kind"] == "COMPLETED_SUBGOAL"}
    assert len(chosen) == 2
    mapping = {"schema": "skhynix/semantic-repair-grouping-map/1.0",
               "index_reference": write(inputs.tmp / "index.json", {"public": True}), "candidates": {}}
    public = {"all_representative_candidates_included": True, "official_outcomes_used": False, "candidates": []}
    for index, (identity, (ref, capture, item, _)) in enumerate(sorted(chosen.items()), 1):
        name = "candidate-" + str(index)
        public["candidates"].append({"candidate_id": name})
        mapping["candidates"][name] = {"capture_id": identity, "capture_reference": ref,
            "task_id": capture["task"]["task_id"], "owner_user_id": capture["owner_user_id"]}
    input_ref = write(inputs.tmp / "grouping/input.json", public)
    map_ref = write(inputs.tmp / "grouping/map.json", mapping)
    response = write(inputs.tmp / "grouping/groups.json", {"schema": "skhynix/semantic-repair-grouping/1.0",
        "input_sha256": input_ref["sha256"], "groups": [{"candidate_ids": list(mapping["candidates"])}], "ungrouped": []})
    events = inputs.tmp / "grouping/events.jsonl"
    native_text = core.canonical_bytes(core.check(response)).decode()
    native_events = [{"type": "thread.started", "thread_id": "fixture-discovery"}, {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": native_text}}, {"type": "turn.completed"}]
    events.write_bytes(b"".join(core.canonical_bytes(row) + b"\n" for row in native_events))
    launch_ref = write(inputs.tmp / "grouping/launch.json", {"fresh_session": True,
        "requested_model": "gpt-6-astra", "reasoning_effort": "high", "input_reference": input_ref})
    completion = write(inputs.tmp / "grouping/completion.json", {"schema": "skhynix/semantic-grouping-completion/1.0",
        "input_reference": input_ref, "launch_reference": launch_ref, "response_reference": response,
        "events_sha256": memory._file_hash(events), "thread_id": "fixture-discovery",
        "response_text_sha256": core.digest(native_text.encode())})
    reflection = learning.export_reflection(clone, inputs.tmp / "new-reflection.json", capture_ids=sorted(chosen))
    proposal_ref = proposal(inputs, reflection)
    ingestion = learning.ingest_proposals(clone, proposal_ref, reflection_reference=reflection)
    assert core.check(ingestion)["promotions_added"] == 1
    frozen = learning.freeze_published_bank(clone, inputs.tmp / "recovered-bank.json")
    template = {"model": "gpt-6-astra", "reasoning_effort": "high", "authentication": "CHATGPT",
                "codex_binary": "C:/fixed/codex.exe", "windows_python": "C:/Python/python.exe"}
    template_ref = write(inputs.tmp / "publisher-template.json", template)
    native_config = write(inputs.tmp / "native/config.json", {**template, "reflection_reference": reflection})
    native_completion = write(inputs.tmp / "native/completion.json", {"thread_id": "fixture-publisher", "proposal_reference": proposal_ref})
    launcher = write(inputs.tmp / "native/outer.json", {"configuration_reference": native_config})
    def native_proof(config_ref, completion_ref, launcher_ref, reflection_ref):
        value = core.check(completion_ref)
        assert core.check(launcher_ref)["configuration_reference"] == config_ref
        return {"thread_id": value["thread_id"], "proposal_reference": value["proposal_reference"],
                "configuration_reference": config_ref, "completion_reference": completion_ref,
                "launcher_reference": launcher_ref, "reflection_reference": reflection_ref}
    def validate_bank(ref):
        bank = memory.load_frozen_bank(ref["path"], ref["sha256"])
        try:
            counts = bank.manifest["layer_counts"]
            if any(value <= 0 for value in counts.values()):
                raise ValueError("empty layer")
            return counts
        finally:
            bank.close()
    proof = native_proof(native_config, native_completion, launcher, reflection)
    manifest = {"schema": recovery.RECOVERY_SCHEMA, "outcome_retries": False,
        "official_outcomes_used": False, "gate_b_waived": False, "proposed_group_count": 1,
        "clone_reference": clone_ref, "publication_reference": frozen["publication_reference"],
        "grouping_completion_reference": completion, "grouping_input_reference": input_ref,
        "grouping_map_reference": map_ref, "projection_producer_reference": memory._ref(cloning.__file__),
        "jobs": [{"capture_ids": sorted(chosen), "reflection_reference": reflection,
            "configuration_reference": native_config, "completion_reference": native_completion,
            "launcher_reference": launcher, "native_proof": proof, "ingestion_reference": ingestion}]}
    manifest_ref = write(inputs.tmp / "reflection-recovery.json", manifest)
    config = {"supersedes_configuration_reference": authority["predecessor_pipeline_reference"],
        "predecessor_pipeline_event_tail_reference": authority["predecessor_pipeline_event_tail_reference"],
        "reflection_recovery_reference": manifest_ref, "training_experiment_reference": template_ref}
    previous = core.check(authority["predecessor_pipeline_reference"])
    return SimpleNamespace(config=config, previous=previous, manifest=manifest, inputs=inputs,
        operations=SimpleNamespace(validate_publisher=native_proof, validate_bank=validate_bank, modules={"publisher": publisher}))


def revise_manifest(ctx, value):
    ctx.config["reflection_recovery_reference"] = write(ctx.inputs.tmp / "amended-manifest.json", value)


def test_real_clone_publication_and_native_proposal_provenance_are_all_required(publication):
    value = recovery.validate_recovered_bank(publication.config, publication.previous, publication.operations)
    assert value["status"] == "READY" and value["layer_counts"]["L3_skills"] == 1
    assert value["source_attempts"] == 2


@pytest.mark.parametrize("mutation", ["omitted_group", "wrong_capture", "native_proof", "official_outcomes", "waive_gate", "retry", "count"])
def test_recovery_rejects_omitted_groups_or_altered_provenance(publication, mutation):
    changed = deepcopy(publication.manifest)
    if mutation == "omitted_group":
        changed["jobs"] = []
    elif mutation == "wrong_capture":
        changed["jobs"][0]["capture_ids"][0] = "f" * 64
    elif mutation == "native_proof":
        changed["jobs"][0]["native_proof"]["thread_id"] = "forged"
    elif mutation == "official_outcomes":
        changed["official_outcomes_used"] = True
    elif mutation == "waive_gate":
        changed["gate_b_waived"] = True
    elif mutation == "retry":
        changed["outcome_retries"] = True
    else:
        changed["proposed_group_count"] = 2
    revise_manifest(publication, changed)
    with pytest.raises(core.PipelineError):
        recovery.validate_recovered_bank(publication.config, publication.previous, publication.operations)


def test_changed_original_catalog_invalidates_recovery(publication):
    clone = core.check(publication.manifest["clone_reference"])
    path = Path(clone["source_snapshot_references"]["catalog.json"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(core.PipelineError, match="changed"):
        recovery.validate_recovered_bank(publication.config, publication.previous, publication.operations)


def test_changed_discovery_events_invalidates_grouping(publication):
    path = Path(publication.manifest["grouping_completion_reference"]["path"]).parent / "events.jsonl"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(core.PipelineError, match="event evidence changed"):
        recovery.validate_recovered_bank(publication.config, publication.previous, publication.operations)


def test_publisher_effort_cannot_change_under_valid_new_reference(publication):
    changed = deepcopy(publication.manifest)
    job = changed["jobs"][0]
    publisher = {**core.check(job["configuration_reference"]), "reasoning_effort": "ultra"}
    job["configuration_reference"] = write(publication.inputs.tmp / "wrong-publisher.json", publisher)
    revise_manifest(publication, changed)
    with pytest.raises(core.PipelineError, match="original model/high"):
        recovery.validate_recovered_bank(publication.config, publication.previous, publication.operations)


def fake_controller(tmp_path, monkeypatch, *, fail_validation=False):
    p = recovery.ReflectionRecoveryPipeline.__new__(recovery.ReflectionRecoveryPipeline)
    p.root, p.clock = tmp_path / "controller", time.time
    p.root.mkdir()
    p.config = {"training_stages": [{"size": n} for n in scale.SIZES], "protocol_reference": {"path": "/protocol", "sha256": "p"},
                "reflection_recovery_reference": {"path": "/recovery", "sha256": "r"}}
    p.reference = core.retain(p.root / "config.json", p.config)
    p.previous, p.operations, p.calls = {}, None, []
    p.scale = scale
    p._controller_locks, p.progress = lambda: nullcontext(), lambda: None
    p._bank = p._runner = p._learning = lambda *a: pytest.fail("Recovered evaluation must never rerun training or reflection")
    def validate(*args):
        if fail_validation:
            raise core.PipelineError("Gate B unavailable")
        return {"size": 240, "bank_reference": {"path": "/verified-bank", "sha256": "b"}}
    monkeypatch.setattr(recovery, "validate_recovered_bank", validate)
    def evaluate(purpose, stage, bank, name):
        p.calls.append((purpose, stage["size"], bank))
        result = {"scope": "DEVELOPMENT", "planned": 60, "completed": 60, "size": stage["size"],
            "resolved": 40 if purpose == "DEVELOPMENT_BASELINE" else 39,
            "task_ids": ["task-" + str(i) for i in range(60)], "status": "COMPLETE", "bank_reference": bank}
        return result, core.retain(p.root / (name + ".json"), result)
    p._evaluation = evaluate
    return p


def test_evaluation_only_flow_retains_dev_then_paired_final_even_when_memory_hurts(tmp_path, monkeypatch):
    p = fake_controller(tmp_path, monkeypatch)
    assert p.run()["status"] == "COMPLETE"
    assert [(a, b) for a, b, _ in p.calls] == [("DEVELOPMENT_BASELINE", 24), ("DEVELOPMENT_BANK", 240), ("FINAL_EVALUATION", 240)]
    assert p.calls[0][2] is None
    assert core.read(p.root / "bank-selection.json")["development_delta_percentage_points"] < 0
    assert p.latest("PIPELINE_COMPLETE")["details"]["new_training_solves"] == 0
    p.run()
    assert len(p.calls) == 3


def test_no_evaluation_action_when_gate_b_or_recovery_provenance_fails(tmp_path, monkeypatch):
    p = fake_controller(tmp_path, monkeypatch, fail_validation=True)
    with pytest.raises(core.PipelineError, match="Gate B"):
        p.run()
    assert p.calls == [] and p.status()["status"] == "BLOCKED"


@pytest.mark.parametrize("key", ["selection_policy", "training_stages", "helper_references", "training_experiment_reference", "grading_continuation_reference"])
def test_recovery_configuration_cannot_change_solver_or_experimental_authority(tmp_path, key):
    old = {"pipeline_root": str(tmp_path / "old"), "selection_policy": "original", "training_stages": [],
           "helper_references": {}, "training_experiment_reference": {}, "grading_continuation_reference": {}}
    reference = write(tmp_path / "original.json", old)
    config = {**old, "schema": recovery.SCHEMA, "supersedes_configuration_reference": reference, key: "changed"}
    with pytest.raises(core.PipelineError, match="cannot change"):
        recovery.validate_config(config)


def test_previous_controller_is_explicitly_bound_without_replacing_solver_module():
    reference = core.ref(scale.__file__)
    module = recovery._load_predecessor_controller({"pipeline_source_reference": reference})
    assert core.ref(module.__file__) == reference
    assert module.__name__ == "skhynix_bound_scale_controller_" + reference["sha256"]
    assert sys.modules[scale.__name__] is scale
    assert module.validate_grading_continuation is not None


def test_unbound_or_incompatible_previous_controller_is_rejected(tmp_path):
    path = tmp_path / "untrusted-controller.py"
    path.write_text("X = 1\n")
    reference = core.ref(path)
    with pytest.raises(core.PipelineError, match="lacks"):
        recovery._load_predecessor_controller({"pipeline_source_reference": reference})
    assert "skhynix_bound_scale_controller_" + reference["sha256"] not in sys.modules
    path.write_text("X = 2\n")
    with pytest.raises(core.PipelineError, match="changed"):
        recovery._load_predecessor_controller({"pipeline_source_reference": reference})


def test_clone_cannot_claim_another_source_root(publication):
    changed = deepcopy(publication.manifest)
    clone = core.check(changed["clone_reference"])
    clone["source_root"] = str(publication.inputs.tmp / "other-source")
    changed["clone_reference"] = write(publication.inputs.tmp / "wrong-clone.json", clone)
    revise_manifest(publication, changed)
    with pytest.raises(core.PipelineError, match="original training authority"):
        recovery.validate_recovered_bank(publication.config, publication.previous, publication.operations)


@pytest.mark.parametrize("purpose", ["DEVELOPMENT_BASELINE", "DEVELOPMENT_BANK", "FINAL_EVALUATION"])
def test_bound_previous_evaluator_keeps_common_solver_runtime_and_removes_training_hold(tmp_path, monkeypatch, purpose):
    p = recovery.ReflectionRecoveryPipeline.__new__(recovery.ReflectionRecoveryPipeline)
    p.scale = recovery._load_predecessor_controller({"pipeline_source_reference": core.ref(scale.__file__)})
    p.root = tmp_path / "new-evaluation"
    runtime = {"source_root": "/frozen-source-v6", "source_sha256": {"runtime": "hash"},
        "loader_preflight_path": "/original-loader-v6", "loader_preflight_sha256": "l" * 64,
        "codex_binary": "C:/frozen-codex.exe", "model": "gpt-6-astra", "reasoning_effort": "high",
        "limits": {"task_requests": 120, "task_seconds": 1200}}
    old = {**runtime, "source_root": "/frozen-source-v1", "source_sha256": {"old": "hash"},
        "dataset_manifest": {"path": "/unchanged-stage-dataset", "sha256": "d" * 64},
        "training_grade_hold_policy": scale.TRAINING_GRADE_HOLD_POLICY}
    runtime_ref, stage_ref = write(tmp_path / "runtime.json", runtime), write(tmp_path / "old-stage.json", old)
    p.reference = runtime_ref
    p.config = {"grading_continuation_reference": runtime_ref, "training_experiment_reference": runtime_ref,
                "evaluation_native_root": str(tmp_path / "native")}
    p.operations = SimpleNamespace(modules={"cohort": SimpleNamespace(execution=SimpleNamespace(
        create_execution_enrollment=lambda *a, **k: {"path": "/authority", "sha256": "a" * 64}))})
    class Configured(Exception):
        pass
    def captured(path, value):
        assert value["source_root"] == runtime["source_root"]
        assert value["source_sha256"] == runtime["source_sha256"]
        assert value["loader_preflight_path"] == runtime["loader_preflight_path"]
        assert value["codex_binary"] == runtime["codex_binary"]
        assert value["model"] == "gpt-6-astra" and value["reasoning_effort"] == "high"
        assert value["limits"] == runtime["limits"]
        assert value["dataset_manifest"] == old["dataset_manifest"]
        assert value["phase"] == "EVALUATION_RUNTIME" and "training_grade_hold_policy" not in value
        raise Configured()
    monkeypatch.setattr(p.scale, "write_execution", captured)
    with pytest.raises(Configured):
        p._evaluation(purpose, {"size": 24, "execution_reference": stage_ref}, None, "baseline")


@pytest.mark.parametrize("mutation", ["undeclared_tool", "response", "thread"])
def test_discovery_requires_authentic_tool_free_final_response_even_with_new_hashes(publication, mutation):
    changed = deepcopy(publication.manifest)
    completion = core.check(changed["grouping_completion_reference"])
    path = Path(changed["grouping_completion_reference"]["path"]).parent / "events.jsonl"
    events = [core.strict_json_loads(line) for line in path.read_bytes().splitlines()]
    if mutation == "undeclared_tool":
        events.insert(2, {"type": "item.completed", "item": {"type": "command_execution"}})
    elif mutation == "response":
        events[2]["item"]["text"] = '{"forged":true}'
        completion["response_text_sha256"] = core.digest(events[2]["item"]["text"].encode())
    else:
        completion["thread_id"] = "wrong-thread"
    path.write_bytes(b"".join(core.canonical_bytes(row) + b"\n" for row in events))
    completion["events_sha256"] = memory._file_hash(path)
    changed["grouping_completion_reference"] = write(path.parent / "amended-completion.json", completion)
    revise_manifest(publication, changed)
    with pytest.raises((core.PipelineError, ValueError)):
        recovery.validate_recovered_bank(publication.config, publication.previous, publication.operations)
