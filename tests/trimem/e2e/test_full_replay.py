import json
from dataclasses import replace

import pytest

from enterprise_memory.trimem.accounting import RawEvidenceLedger, sha256_bytes
from enterprise_memory.trimem.agent_runtime import CodingTask, InjectedCrash, TriMemAgentRuntime
from enterprise_memory.trimem.arms import ActiveNodeTriMemController
from enterprise_memory.trimem.checkpoint import CheckpointMismatch, FileCheckpointStore
from enterprise_memory.trimem.consolidation import ConsolidationService
from enterprise_memory.trimem.gateway import ReplayModelGateway
from enterprise_memory.trimem.grader import ReplayGraderGateway
from enterprise_memory.trimem.lifecycle import DQNExperienceLifecycle
from enterprise_memory.trimem.policy import DoubleDQNConfig, DoubleDQNMemoryPolicy, FeatureSchema
from enterprise_memory.trimem.retrieval import (
    InMemoryMemoryGraphStore,
    RetrievalConfig,
    TriMemoryRetriever,
)
from enterprise_memory.trimem.runtime_lock import RuntimeLock
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph


def _decomposition(task_id):
    if task_id == "source-json-extension":
        return {
            "subtasks": [
                {
                    "id": "locate-normalization",
                    "objective": "identify case-sensitive extension validation in load_document",
                    "predicted_operation": "locate extension comparison",
                    "depends_on": [],
                    "files": ["src/loader.py"],
                    "symbols": ["load_document"],
                    "apis": ["str.endswith"],
                },
                {
                    "id": "normalize-before-validation",
                    "objective": "normalize the file extension before validating JSON inputs",
                    "predicted_operation": "casefold extension before comparison",
                    "depends_on": ["locate-normalization"],
                    "preconditions": ["extension matching is intended to be case insensitive"],
                    "invariants": ["non-JSON inputs remain rejected"],
                    "tests": ["uppercase JSON extension"],
                },
            ]
        }
    return {
        "subtasks": [
            {
                "id": "apply-extension-normalization",
                "objective": "apply case-insensitive extension normalization to YAML config loading",
                "predicted_operation": "casefold extension before comparison",
                "depends_on": [],
                "files": ["src/config.py"],
                "symbols": ["load_config"],
                "apis": ["str.endswith"],
                "required_memory_facets": ["operation", "precondition", "verification"],
            },
            {
                "id": "preserve-rejection-invariant",
                "objective": "preserve rejection of non-YAML configuration files and verify uppercase YAML",
                "predicted_operation": "run public regression checks",
                "depends_on": ["apply-extension-normalization"],
                "invariants": ["non-YAML inputs remain rejected"],
                "tests": ["uppercase YAML extension", "TXT rejection"],
            },
        ]
    }


def _replay_resolver(request):
    if request.call_kind == "decompose":
        return json.dumps(_decomposition(request.task_id))
    if request.call_kind == "extract":
        if request.task_id == "source-json-extension":
            assert "def load_document(name)" in request.prompt
            assert "source public checks" in request.prompt
            assert "official-shaped source replay passed" not in request.prompt
            return json.dumps(
                {
                    "episode": {
                        "summary": "Case-insensitive JSON extension validation was repaired.",
                        "action": "casefold the filename before checking the extension",
                        "outcome": "passed",
                    },
                    "semantic_candidate": {
                        "preconditions": "A file extension allowlist is specified as case insensitive.",
                        "operation": "Normalize or casefold the candidate filename before extension comparison.",
                        "invariant": "Extensions outside the allowlist remain rejected.",
                        "non_applicability": "Do not apply when the format contract is deliberately case sensitive.",
                        "verification": "Test an uppercase allowed extension and a disallowed extension.",
                        "applicability_scope": "CROSS_REPOSITORY",
                    },
                }
            )
        assert "def load_config(name)" in request.prompt
        assert "target public checks" in request.prompt
        assert "official-shaped target replay passed" not in request.prompt
        return json.dumps(
            {
                "episode": {
                    "summary": "Case-insensitive YAML extension validation was repaired.",
                    "action": "casefold the filename before checking YAML extensions",
                    "outcome": "passed",
                },
                "semantic_candidate": {
                    "preconditions": "YAML suffix matching is case insensitive.",
                    "operation": "Normalize the filename before extension comparison.",
                    "invariant": "Non-YAML inputs remain rejected.",
                    "non_applicability": "Case-sensitive protocols are excluded.",
                    "verification": "Test uppercase YAML and a disallowed suffix.",
                    "applicability_scope": "CROSS_REPOSITORY",
                },
            }
        )

    step = request.step_no
    if request.task_id == "source-json-extension":
        if step == 2:
            assert "def load_document(name)" in request.prompt
            assert "name.endswith('.json')" in request.prompt
        if step == 5:
            assert "source public checks" in request.prompt
        actions = {
            1: {"tool": "read_file", "arguments": {"path": "src/loader.py"}},
            2: {"tool": "complete_subtask", "arguments": {"evidence": "Located direct .endswith('.json') comparison."}},
            3: {
                "tool": "write_file",
                "arguments": {
                    "path": "src/loader.py",
                    "content": "def load_document(name):\n    if not name.casefold().endswith('.json'):\n        raise ValueError('json required')\n    return 'loaded'\n",
                },
            },
            4: {"tool": "run_public_tests", "arguments": {}},
            5: {"tool": "complete_subtask", "arguments": {"evidence": "Public uppercase JSON and rejection checks pass."}},
        }
    else:
        if step == 1:
            # This assertion proves retrieval happened at activation and that
            # the exact memory was placed in the solve request, not merely logged.
            assert '"memory_for_active_subtask_only": [{"' in request.prompt
            assert "casefold" in request.prompt
        if step == 2:
            assert "def load_config(name)" in request.prompt
            assert "name.endswith" in request.prompt
        actions = {
            1: {"tool": "read_file", "arguments": {"path": "src/config.py"}},
            2: {
                "tool": "write_file",
                "arguments": {
                    "path": "src/config.py",
                    "content": "def load_config(name):\n    folded = name.casefold()\n    if not folded.endswith(('.yaml', '.yml')):\n        raise ValueError('yaml required')\n    return 'loaded'\n",
                },
            },
            3: {"tool": "complete_subtask", "arguments": {"evidence": "Applied casefold before YAML suffix comparison."}},
            4: {"tool": "run_public_tests", "arguments": {}},
            5: {"tool": "complete_subtask", "arguments": {"evidence": "Uppercase YAML passes and TXT remains rejected."}},
        }
    return json.dumps(actions[step])


def _source_task():
    def public(files):
        namespace = {}
        exec(files["src/loader.py"], namespace)
        ok = namespace["load_document"]("DATA.JSON") == "loaded"
        try:
            namespace["load_document"]("DATA.TXT")
            ok = False
        except ValueError:
            pass
        from enterprise_memory.trimem.workspace import PublicTestResult
        return PublicTestResult(ok, "source public checks")

    return CodingTask(
        task_id="source-json-extension",
        org_id="org-1",
        user_id="alice",
        repository="example/loaders",
        commit="source-commit",
        instruction="Make JSON extension validation case insensitive while rejecting other formats.",
        files={
            "src/loader.py": "def load_document(name):\n    if not name.endswith('.json'):\n        raise ValueError('json required')\n    return 'loaded'\n"
        },
        editable_paths=("src/loader.py",),
        public_test=public,
    )


def _target_task():
    def public(files):
        namespace = {}
        exec(files["src/config.py"], namespace)
        ok = namespace["load_config"]("SETTINGS.YAML") == "loaded"
        try:
            namespace["load_config"]("SETTINGS.TXT")
            ok = False
        except ValueError:
            pass
        from enterprise_memory.trimem.workspace import PublicTestResult
        return PublicTestResult(ok, "target public checks")

    return CodingTask(
        task_id="target-yaml-extension",
        org_id="org-1",
        user_id="alice",
        repository="example/loaders",
        commit="target-commit",
        instruction="Accept uppercase YAML extensions while continuing to reject non-YAML config files.",
        files={
            "src/config.py": "def load_config(name):\n    if not name.endswith(('.yaml', '.yml')):\n        raise ValueError('yaml required')\n    return 'loaded'\n"
        },
        editable_paths=("src/config.py",),
        public_test=public,
    )


def _runtime(tmp_path, task, policy, lifecycle, index, model, evaluator):
    retrieval = TriMemoryRetriever(
        index,
        RetrievalConfig(min_confidence=0.0, min_margin=0.0, ppr_iterations=24),
    )
    controller = ActiveNodeTriMemController(retrieval, task_id=task.task_id)
    evidence = RawEvidenceLedger(tmp_path / task.task_id / "evidence")
    grader = ReplayGraderGateway(
        evaluator,
        fixture_digest=sha256_bytes((task.task_id + ":private-grader-fixture").encode()),
    )
    return TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=model,
        grader_gateway=grader,
        memory_controller=controller,
        evidence=evidence,
        checkpoint_store=FileCheckpointStore(tmp_path / task.task_id / "checkpoints"),
        lifecycle=lifecycle,
    )


def test_source_to_target_full_replay_traverses_dqn_storage_ppr_grader_and_credit(tmp_path):
    schema = FeatureSchema(8, 8, 8, 3)
    policy = DoubleDQNMemoryPolicy(
        DoubleDQNConfig(
            schema,
            hidden_dim=8,
            replay_capacity=32,
            batch_size=1,
            min_replay_size=1,
            target_sync_interval=1,
            epsilon_start=0.0,
            epsilon_end=0.0,
            seed=7,
        )
    )
    index = InMemoryMemoryGraphStore()
    lifecycle = DQNExperienceLifecycle(
        policy,
        ConsolidationService(episodic_capacity=8, user_semantic_capacity=8, organisation_capacity=8),
        index,
        split="credential_free_replay",
        evaluation=False,
        clock=iter(["2026-08-31T00:00:00Z", "2026-08-31T00:01:00Z"]).__next__,
    )
    model = ReplayModelGateway(_replay_resolver)

    source = _source_task()
    source_runtime = _runtime(
        tmp_path,
        source,
        policy,
        lifecycle,
        index,
        model,
        lambda files: ("casefold" in files["src/loader.py"], "official-shaped source replay passed", ""),
    )
    source_result = source_runtime.run(source, arm="M2")
    assert source_result.resolved is True
    assert source_result.extraction.patch_hash == sha256_bytes(source_result.patch.encode("utf-8"))
    assert source_result.lifecycle_result["storage"]["storage_action"] in {
        "MOVE_TO_EPISODIC",
        "MOVE_TO_SEMANTIC_CANDIDATE",
    }
    source_memory_id = source_result.lifecycle_result["storage"]["memory_id"]
    assert source_memory_id
    stored_source_episode = lifecycle.consolidation.episodes.active(source.user_id)[0]
    assert stored_source_episode.payload["patch_hash"] == source_result.extraction.patch_hash
    assert stored_source_episode.payload["public_evidence_hash"] == (
        source_result.extraction.public_evidence_hash
    )

    target = _target_task()
    target_runtime = _runtime(
        tmp_path,
        target,
        policy,
        lifecycle,
        index,
        model,
        lambda files: (
            "casefold" in files["src/config.py"] and "('.yaml', '.yml')" in files["src/config.py"],
            "official-shaped target replay passed",
            "",
        ),
    )
    target_result = target_runtime.run(target, arm="M2")
    assert target_result.resolved is True
    assert source_memory_id in {row["memory_id"] for row in target_result.injections}
    assert target_result.lifecycle_result["credit"]["credited"] == 1
    assert policy.replay_size >= 1
    assert policy.training_steps >= 1

    for result in (source_result, target_result):
        summary = result.accounting["summary"]
        assert summary["paid_model_calls"] == 0
        assert summary["by_call_kind"]["decompose"]["calls"] == 1
        assert summary["by_call_kind"]["extract"]["calls"] == 1
        assert summary["by_call_kind"]["solve"]["calls"] == 5
        assert summary["grader_calls"] == 1
        assert summary["grader_containers"] == 0
        assert summary["official_grader_runs"] == 0
        assert result.grade.official is False
        assert result.patch
    assert all(row["active_node_id"] != "" for row in target_result.injections)

    lifecycle.resolve_unreused(next_task_succeeded=True)
    checkpoint = policy.freeze_checkpoint()
    assert checkpoint.payload["evaluation_exploration"] is False
    assert len(checkpoint.digest.removeprefix("sha256:")) == 64


def test_checkpoint_resume_does_not_repeat_completed_model_calls(tmp_path):
    schema = FeatureSchema(8, 8, 8, 3)
    policy = DoubleDQNMemoryPolicy(
        DoubleDQNConfig(schema, hidden_dim=4, replay_capacity=8, batch_size=1, min_replay_size=1, seed=7)
    )
    index = InMemoryMemoryGraphStore()
    lifecycle = DQNExperienceLifecycle(
        policy,
        ConsolidationService(8, 8, 8),
        index,
        split="credential_free_replay",
        evaluation=False,
        clock=lambda: "2026-08-31T00:00:00Z",
    )
    task = _source_task()
    model = ReplayModelGateway(_replay_resolver)
    runtime = _runtime(
        tmp_path,
        task,
        policy,
        lifecycle,
        index,
        model,
        lambda files: ("casefold" in files["src/loader.py"], "passed", ""),
    )
    with pytest.raises(InjectedCrash):
        runtime.run(task, arm="M2", run_id="resume-run", crash_after_checkpoints=3)
    before = tuple(model.invocations)
    checkpoint = FileCheckpointStore(tmp_path / task.task_id / "checkpoints").load(
        "resume-run", required_config_hashes=None
    )
    graph = ShortTermWorkingGraph.from_snapshot(checkpoint.graph_snapshot)
    if graph.active_node is None:
        graph.activate_next()
    runtime.memory.restore(checkpoint.memory_controller_state)
    # Record the exact deterministic controller decision.  A fabricated empty
    # recall is not a legal crash suffix because it could silently discard a
    # real injection, rejection, or bank trace after a restart.
    runtime._record_recall(task, "M2", runtime.memory.recall(graph, task))
    assert runtime.evidence.last_event_hash != checkpoint.evidence_event_hash

    # A fsynced evidence suffix is legal when the checkpoint tail is its
    # verified ancestor.  Resume must not require exact tail equality.
    resumed = runtime.run(task, arm="M2", run_id="resume-run", resume=True)
    assert resumed.resolved is True
    after = tuple(model.invocations)
    assert len(after) == len(set(after))
    assert set(before) < set(after)
    assert resumed.accounting["summary"]["paid_model_calls"] == 0

    runtime.evidence.append(
        "process_crash_observed",
        {"checkpoint_evidence_hash": resumed.evidence_tail_hash},
    )
    with pytest.raises(CheckpointMismatch, match="permits no evidence suffix"):
        runtime.run(task, arm="M2", run_id="resume-run", resume=True)

    changed_task = replace(task, instruction=task.instruction + " changed")
    with pytest.raises(CheckpointMismatch, match="runtime lock changed"):
        runtime.run(changed_task, arm="M2", run_id="resume-run", resume=True)

    runtime.model_config_hash = sha256_bytes(b"changed-model-configuration")
    with pytest.raises(CheckpointMismatch, match="runtime lock changed"):
        runtime.run(task, arm="M2", run_id="resume-run", resume=True)


@pytest.mark.parametrize("terminal_checkpoint", [7, 8, 9, 10, 11, 12])
def test_terminal_phase_checkpoint_resume_is_idempotent(tmp_path, terminal_checkpoint):
    root = tmp_path / ("phase-%02d" % terminal_checkpoint)
    schema = FeatureSchema(8, 8, 8, 3)
    policy = DoubleDQNMemoryPolicy(
        DoubleDQNConfig(schema, hidden_dim=4, replay_capacity=8, batch_size=1, min_replay_size=1, seed=7)
    )
    index = InMemoryMemoryGraphStore()
    lifecycle = DQNExperienceLifecycle(
        policy,
        ConsolidationService(8, 8, 8),
        index,
        split="credential_free_replay",
        evaluation=False,
        clock=lambda: "2026-08-31T00:00:00Z",
    )
    task = _source_task()
    model = ReplayModelGateway(_replay_resolver)
    grader_calls = []

    def evaluator(files):
        grader_calls.append(sha256_bytes(files["src/loader.py"].encode("utf-8")))
        return "casefold" in files["src/loader.py"], "passed", ""

    runtime = _runtime(root, task, policy, lifecycle, index, model, evaluator)
    with pytest.raises(InjectedCrash):
        runtime.run(
            task,
            arm="M2",
            run_id="terminal-resume",
            crash_after_checkpoints=terminal_checkpoint,
        )
    before = tuple(model.invocations)
    resumed = runtime.run(task, arm="M2", run_id="terminal-resume", resume=True)
    assert resumed.resolved is True
    assert len(model.invocations) == len(set(model.invocations))
    assert set(before) <= set(model.invocations)
    assert len(grader_calls) == 1
    assert resumed.accounting["summary"]["grader_calls"] == 1
    assert resumed.accounting["summary"]["by_call_kind"]["extract"]["calls"] == 1
    checkpoint = FileCheckpointStore(root / task.task_id / "checkpoints").load(
        "terminal-resume",
        required_config_hashes=None,
        required_evidence_hash=resumed.evidence_tail_hash,
    )
    assert checkpoint.state == "DONE"


def test_packaged_replay_crosses_reviewed_org_semantic_boundary(tmp_path):
    from enterprise_memory.trimem.credential_free import run_credential_free_e2e

    report = run_credential_free_e2e(tmp_path / "packaged")
    assert report["status"] == "PASS"
    assert report["source"]["shared_promotion"]["supporting_user_ids"] == ["alice", "bob"]
    assert report["target"]["user_id"] == "charlie"
    assert report["target"]["user_id"] not in report["source"]["shared_promotion"][
        "supporting_user_ids"
    ]
    assert report["source"]["shared_promotion"]["dqn_controlled_publication"] is False
    assert report["target"]["cross_user_transfer_bank"] == "ORG_SEMANTIC"
    assert {row["kind"] for row in report["target"]["injections"]} == {"ORG_SEMANTIC"}
    assert report["correctness"]["private_episode_identifiers_exposed_cross_user"] is False
    assert report["target"]["credit"]["credited"] == 1
    assert report["correctness"]["public_tool_observations_present_in_extraction_prompts"] is True
    assert report["paid_model_calls"] == 0
    assert report["official_grader_execution"] is False
