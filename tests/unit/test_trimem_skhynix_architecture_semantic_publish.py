"""Offline orchestration tests; native calls and learning authority are fakes."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

import trimem_skhynix_architecture_pipeline as core
import trimem_skhynix_architecture_semantic_publish as publish
from trimem_skhynix_architecture_publisher import validate_events


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    # Test filesystem is portable; production uses the unchanged C-mount mapper.
    monkeypatch.setattr(core, "windows_path", lambda path: str(Path(path)))
    monkeypatch.setattr(core, "linux_path", lambda path: Path(path))
    output, root, old = tmp_path / "publisher", tmp_path / "clone", tmp_path / "original"
    root.mkdir(); old.mkdir()
    previous_ref = core.retain(tmp_path / "previous.json", {"frozen_configuration": True})
    producer_ref = core.retain(tmp_path / "producer.json", {"frozen_producer": True})
    available, mapped, candidates, captures, groups = {}, {}, [], {}, []
    for number in range(8):
        identity, capture_id = f"candidate-{number:03d}", f"capture-{number:03d}"
        capture = {"task": {"task_id": f"task-{number}"}, "owner_user_id": "owner-" + str(number % 2)}
        reference = core.retain(old / (capture_id + ".json"), capture)
        captures[capture_id] = reference
        available[capture_id] = (reference, capture, {}, {})
        mapped[identity] = {"capture_id": capture_id, "capture_reference": reference,
            "task_id": capture["task"]["task_id"], "owner_user_id": capture["owner_user_id"], "red_step": 1, "green_step": 3}
        candidates.append({"candidate_id": identity, "task_group": capture["task"]["task_id"],
                           "contributor_group": capture["owner_user_id"]})
        if number % 2:
            groups.append({"candidate_ids": [f"candidate-{number-1:03d}", identity],
                           "shared_transformation": "Native proposed transformation " + str(number),
                           "applicability": "Native bounded applicability"})
    original_catalog = core.retain(old / "catalog.json", {"captures": captures, "skills": {}})
    initial = core.retain(root / "initial-catalog.json", {"captures": captures, "skills": {}})
    core.retain(root / "catalog.json", {"captures": captures, "skills": {}})
    enrollment = core.retain(root / "learning-enrollment.json", {"frozen_scope": True})
    clone = {"schema": "skhynix/learning-authority-recovery/1.0", "operation": "CLONE_COMPLETED_PUBLIC_LEARNING_FOR_REFLECTION",
        "predecessor_pipeline_reference": previous_ref, "original_evidence_paths_preserved": True,
        "gate_b_waived": False, "counts": {"training_sources": 240, "L3_skills": 0},
        "model_calls": 0, "solver_runs": 0, "official_grader_runs": 0, "source_recaptures": 0,
        "destination_root": str(root), "source_root": str(old), "source_snapshot_references": {"catalog.json": original_catalog},
        "clone_initial_references": {"catalog.json": initial}, "implementation_references": {"producer": producer_ref},
        "learning_enrollment_reference": enrollment}
    clone_ref = core.retain(root / "learning-recovery.json", clone)
    input_ref = core.retain(tmp_path / "input.json", {"schema": "skhynix/public-repair-grouping-input/1.0",
        "all_representative_candidates_included": True, "official_outcomes_used": False, "candidates": candidates})
    mapping = {"schema": "skhynix/semantic-repair-grouping-map/1.0", "candidates": mapped,
               "index_reference": core.retain(tmp_path / "index.json", {"all_public_candidates": True})}
    mapping_ref = core.retain(tmp_path / "mapping.json", mapping)
    response = {"schema": "skhynix/semantic-repair-grouping/1.0", "input_sha256": input_ref["sha256"],
                "groups": groups, "ungrouped": []}
    response_ref = core.retain(tmp_path / "groups.json", response)
    launch_ref = core.retain(tmp_path / "launch.json", {"schema": "skhynix/semantic-grouping-launch/1.0",
        "fresh_session": True, "requested_model": "gpt-6-astra", "reasoning_effort": "high", "input_reference": input_ref})
    event_path = tmp_path / "events.jsonl"
    text = core.canonical_bytes(response).decode()
    events = [{"type": "thread.started", "thread_id": "grouping-thread"}, {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": text}}, {"type": "turn.completed"}]
    event_path.write_bytes(b"\n".join(core.canonical_bytes(row) for row in events) + b"\n")
    completion_ref = core.retain(tmp_path / "completion.json", {"schema": "skhynix/semantic-grouping-completion/1.0",
        "input_reference": input_ref, "response_reference": response_ref, "launch_reference": launch_ref,
        "memory_writes": 0, "official_grader_runs": 0, "separate_model_api_client_calls": 0,
        "events_sha256": core.ref(event_path)["sha256"], "validation_required": True,
        "thread_id": "grouping-thread", "response_text_sha256": core.digest(text.encode()),
        "summary": {"groups": 4, "grouped_candidates": 8, "ungrouped_candidates": 0, "verified_skills": 0}})
    request = {"schema": publish.REQUEST_SCHEMA, "predecessor_pipeline_reference": previous_ref,
        "clone_reference": clone_ref, "grouping_input_reference": input_ref, "grouping_map_reference": mapping_ref,
        "grouping_completion_reference": completion_ref, "projection_producer_reference": producer_ref,
        "output_root": str(output), "expected_group_count": 4}
    request_ref = core.retain(tmp_path / "request.json", request)

    class Learning:
        loads = 0
        freezes = 0
        registry = {}

        @contextmanager
        def _session(self, learning_root):
            assert learning_root == root
            yield root, {}, self.registry, {}

        def _available_captures(self, learning_root, registry):
            self.loads += 1
            return available

        def _retain_reflection(self, learning_root, registry, public, private, path, cap):
            assert len(core.canonical_bytes(public)) + 1 <= cap
            return core.retain(path, public)

        def freeze_published_bank(self, learning_root, path):
            self.freezes += 1
            bank_ref = core.retain(path, {"actually_promoted_test_skill": True})
            reference = core.retain(root / "publication.json", {"operation": "PUBLISH_TRAINED_BANK", "bank": bank_ref})
            core.retain(root / "learning-frozen.json", reference)
            return {"publication_reference": reference}

    class Operations:
        def __init__(self):
            self.modules = {"learning": Learning(), "publisher": SimpleNamespace(validate_events=validate_events)}
            self.training = {"model": "gpt-6-astra", "authentication": "CHATGPT", "reasoning_effort": "high",
                             "codex_binary": "C:/frozen/codex.exe", "windows_python": "C:/frozen/python.exe"}
            self.launches, self.ingests = [], []
            self.promote_ordinal = 2
            self.fail_launch = None
            self.fail_ingest = None
            self.ingestion_failures = False

        def launch_publisher(self, configuration_reference, launcher_path):
            self.launches.append(configuration_reference)
            if self.fail_launch:
                raise self.fail_launch("simulated interrupted launch")
            config = core.check(configuration_reference)
            native = Path(config["worker_output"])
            proposal = core.retain(native / "proposals.json", {"proposals": [], "reflection_sha256": config["reflection_reference"]["sha256"]})
            core.retain(native / "completion.json", {"proposal_reference": proposal, "thread_id": "thread-" + str(len(self.launches))})
            core.retain(launcher_path, {"status": "COMPLETE", "returncode": 0, "configuration_reference": configuration_reference})

        def validate_publisher(self, config_ref, completion_ref, launcher_ref, reflection_ref):
            completion = core.check(completion_ref)
            return {"thread_id": completion["thread_id"], "configuration_reference": config_ref,
                "completion_reference": completion_ref, "launcher_reference": launcher_ref,
                "proposal_reference": completion["proposal_reference"], "reflection_reference": reflection_ref}

        def ingest(self, learning_root, proposal_ref, reflection_ref):
            self.ingests.append(proposal_ref)
            if self.fail_ingest:
                raise self.fail_ingest("simulated interrupted ingestion")
            ordinal = len(self.ingests)
            promoted = ordinal == self.promote_ordinal
            if promoted:
                catalog = core.read(root / "catalog.json")
                catalog["skills"]["test-skill"] = {"verified": True}
                (root / "catalog.json").write_bytes(core.canonical_bytes(catalog) + b"\n")
            identity = core.digest(core.canonical_bytes({"proposal": proposal_ref, "reflection": reflection_ref}))
            return core.retain(root / "learning-ingestions" / (identity + ".json"), {
                "proposal_reference": proposal_ref, "reflection_reference": reflection_ref,
                "status": "VALIDATION_FAILURE" if self.ingestion_failures and ordinal == 1 else "PROCESSED",
                "failures": ["invalid proposal envelope"] if self.ingestion_failures and ordinal == 1 else [],
                "outcomes": [{"status": "PROMOTED" if promoted else "REJECTED"}], "promotions_added": int(promoted)})

    class Producer:
        @staticmethod
        def build_public_repair_windows(learning_root, enrollment, source, selected):
            return ({"schema": "skhynix/native-architecture-public-reflection/2.0", "capture_ids": selected},
                    {"sources": {"source-" + str(i): {"capture_id": identity} for i, identity in enumerate(selected)}})

    operations = Operations()
    def execute():
        return publish.execute(core, request, request_ref, operations, Producer(), clone, mapping, response, response_ref)
    return SimpleNamespace(request=request, request_ref=request_ref, operations=operations, clone=clone, mapping=mapping,
        response=response, response_ref=response_ref, root=root, output=output, execute=execute, previous=previous_ref)


def test_input_binding_accepts_exact_complete_native_discovery(experiment):
    previous, clone, mapping, response, reference = publish.validate_inputs(core, experiment.request)
    assert clone == experiment.clone and mapping == experiment.mapping and response == experiment.response
    assert reference == experiment.response_ref


def test_all_four_groups_processed_even_after_rejection_with_one_actual_skill(experiment):
    reference = experiment.execute()
    result = core.check(reference)
    assert result["status"] == "READY" and result["proposed_group_count"] == 4
    assert len(experiment.operations.launches) == len(experiment.operations.ingests) == len(result["jobs"]) == 4
    assert experiment.operations.modules["learning"].loads == 1
    assert experiment.operations.modules["learning"].freezes == 1
    assert result["L3_skills"] == 1 and result["gate_b_waived"] is False
    assert result["native_solver_runtime_unchanged"] is True and result["official_grader_runs"] == 0
    for group, job in zip(experiment.response["groups"], result["jobs"]):
        assert job["capture_ids"] == sorted(experiment.mapping["candidates"][key]["capture_id"] for key in group["candidate_ids"])
        projected = core.check(job["reflection_reference"])
        assert projected["native_semantic_grouping"]["group"] == group
        assert "NOT_GATE_B_EVIDENCE" in projected["native_semantic_grouping"]["role"]


def test_all_empty_or_rejected_groups_return_honest_not_ready(experiment):
    experiment.operations.promote_ordinal = None
    result = core.check(experiment.execute())
    assert result["status"] == "NOT_READY" and result["reason"] == "NO_VERIFIED_GATE_B_SKILL"
    assert result["publication_reference"] is None
    assert len(experiment.operations.launches) == 4
    assert experiment.operations.modules["learning"].freezes == 0


def test_top_level_ingestion_failure_retained_but_remaining_groups_processed(experiment):
    experiment.operations.ingestion_failures = True
    result = core.check(experiment.execute())
    assert result["reason"] == "INGESTION_VALIDATION_FAILURE" and result["status"] == "NOT_READY"
    assert len(experiment.operations.ingests) == 4
    assert experiment.operations.modules["learning"].freezes == 0


def test_completed_reentry_never_relaunches_or_reingests(experiment):
    first = experiment.execute()
    assert experiment.execute() == first
    assert len(experiment.operations.launches) == len(experiment.operations.ingests) == 4
    assert experiment.operations.modules["learning"].loads == 1


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt])
def test_uncertain_native_start_is_never_retried(experiment, failure):
    experiment.operations.fail_launch = failure
    with pytest.raises(failure):
        experiment.execute()
    experiment.operations.fail_launch = None
    with pytest.raises(core.PipelineError, match="no automatic"):
        experiment.execute()
    assert len(experiment.operations.launches) == 1
    assert (experiment.output / "group-01/publish-started.json").exists()
    assert (experiment.output / "failure.json").exists()


def test_uncertain_ingestion_is_never_replayed(experiment):
    experiment.operations.fail_ingest = KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        experiment.execute()
    experiment.operations.fail_ingest = None
    with pytest.raises(core.PipelineError, match="no automatic replay"):
        experiment.execute()
    assert len(experiment.operations.launches) == len(experiment.operations.ingests) == 1


def test_model_setting_change_fails_before_native_launch(experiment):
    experiment.operations.training["reasoning_effort"] = "ultra"
    with pytest.raises(core.PipelineError, match="Astra/high"):
        experiment.execute()
    assert experiment.operations.launches == []


@pytest.mark.parametrize("change", ["response", "thread", "hash"])
def test_native_grouping_response_requires_actual_final_message_binding(experiment, change):
    response = deepcopy(experiment.response)
    request = deepcopy(experiment.request)
    if change == "response":
        response["groups"][0]["applicability"] = "not the actual native final output"
    else:
        completion = core.check(request["grouping_completion_reference"])
        completion["thread_id" if change == "thread" else "response_text_sha256"] = "changed"
        request["grouping_completion_reference"] = core.retain(experiment.output.parent / "native-changed.json", completion)
    with pytest.raises(core.PipelineError, match="actual completed fresh native response"):
        publish.validate_grouping_native(core, request, response, experiment.operations)


def test_frozen_operations_are_initialized_before_new_projection_import(experiment, monkeypatch):
    order = []
    def operations(config):
        order.append("frozen-runtime")
        return experiment.operations
    def projection(runtime, reference):
        assert order == ["frozen-runtime"]
        order.append("offline-projection")
        return object()
    monkeypatch.setattr(core, "FrozenOperations", operations)
    monkeypatch.setattr(publish, "import_projection", projection)
    monkeypatch.setattr(publish, "execute", lambda *args, **kwargs: {"prepared": True})
    assert publish.run(experiment.request_ref["path"]) == {"prepared": True}
    assert order == ["frozen-runtime", "offline-projection"]


def test_changed_request_cannot_reuse_existing_output(experiment):
    experiment.execute()
    experiment.request["expected_group_count"] = 3
    with pytest.raises(core.PipelineError):
        # Existing request hash is deliberately not forged to match this edit.
        publish.validate_inputs(core, experiment.request)


@pytest.mark.parametrize("mutation", ["group_count", "input_sha", "unknown_candidate", "same_owner", "excluded_candidate"])
def test_discovery_mismatch_fails_before_native_execution(experiment, mutation):
    request = deepcopy(experiment.request)
    response = deepcopy(experiment.response)
    mapping = deepcopy(experiment.mapping)
    completion = core.check(request["grouping_completion_reference"])
    if mutation == "group_count":
        response["groups"].pop()
    elif mutation == "input_sha":
        response["input_sha256"] = "0" * 64
    elif mutation == "unknown_candidate":
        response["groups"][0]["candidate_ids"][0] = "unknown"
    elif mutation == "same_owner":
        for item in mapping["candidates"].values():
            item["owner_user_id"] = "same"
        request["grouping_map_reference"] = core.retain(experiment.output.parent / "changed-map.json", mapping)
    else:
        response["groups"][0]["candidate_ids"] = response["groups"][1]["candidate_ids"]
    completion["response_reference"] = core.retain(experiment.output.parent / "changed-groups.json", response)
    request["grouping_completion_reference"] = core.retain(experiment.output.parent / "changed-completion.json", completion)
    with pytest.raises(core.PipelineError):
        publish.validate_inputs(core, request)
    assert experiment.operations.launches == []
