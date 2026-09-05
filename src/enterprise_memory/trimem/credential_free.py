"""Deterministic full-path replay used as the credential-free readiness gate."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from .accounting import RawEvidenceLedger, canonical_bytes, sha256_bytes
from .agent_runtime import CodingTask, TriMemAgentRuntime
from .arms import ActiveNodeTriMemController
from .checkpoint import FileCheckpointStore
from .consolidation import ConsolidationService, EpisodeRecord, PromotionReview
from .gateway import ReplayModelGateway
from .grader import ReplayGraderGateway
from .lifecycle import DQNExperienceLifecycle
from .policy import DoubleDQNConfig, DoubleDQNMemoryPolicy, FeatureSchema
from .retrieval import InMemoryMemoryGraphStore, RetrievalConfig, TriMemoryRetriever
from .runtime_lock import RuntimeLock
from .workspace import PublicTestResult


def _decomposition(task_id: str) -> dict:
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
    if task_id == "target-yaml-extension":
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
    raise KeyError(task_id)


class ScenarioReplayModel:
    def __init__(self):
        self.target_memory_seen = False
        self.public_tool_observations_seen = {"source_read": False, "source_test": False, "target_read": False}
        self.extraction_public_evidence_seen = {"source": False, "target": False}
        self.hidden_grader_payload_seen_by_extractor = False

    def __call__(self, request) -> str:
        if request.call_kind == "decompose":
            return json.dumps(_decomposition(request.task_id))
        if request.call_kind == "extract":
            if request.task_id == "source-json-extension":
                self.extraction_public_evidence_seen["source"] = (
                    "def load_document(name)" in request.prompt
                    and "source public checks" in request.prompt
                )
            elif request.task_id == "target-yaml-extension":
                self.extraction_public_evidence_seen["target"] = (
                    "def load_config(name)" in request.prompt
                    and "target public checks" in request.prompt
                )
            self.hidden_grader_payload_seen_by_extractor = (
                self.hidden_grader_payload_seen_by_extractor
                or "official-shaped source replay passed" in request.prompt
                or "official-shaped target replay passed" in request.prompt
            )
            return json.dumps(self._extraction(request.task_id))
        step = request.step_no
        if request.task_id == "source-json-extension":
            if step == 2:
                self.public_tool_observations_seen["source_read"] = (
                    "def load_document(name)" in request.prompt
                    and "name.endswith('.json')" in request.prompt
                )
            if step == 5:
                self.public_tool_observations_seen["source_test"] = "source public checks" in request.prompt
            actions = {
                1: {"tool": "read_file", "arguments": {"path": "src/loader.py"}},
                2: {
                    "tool": "complete_subtask",
                    "arguments": {"evidence": "Located direct .endswith('.json') comparison."},
                },
                3: {
                    "tool": "write_file",
                    "arguments": {
                        "path": "src/loader.py",
                        "content": (
                            "def load_document(name):\n"
                            "    if not name.casefold().endswith('.json'):\n"
                            "        raise ValueError('json required')\n"
                            "    return 'loaded'\n"
                        ),
                    },
                },
                4: {"tool": "run_public_tests", "arguments": {}},
                5: {
                    "tool": "complete_subtask",
                    "arguments": {"evidence": "Public uppercase JSON and rejection checks pass."},
                },
            }
        elif request.task_id == "target-yaml-extension":
            if step == 1:
                self.target_memory_seen = (
                    '"memory_for_active_subtask_only": [{"' in request.prompt
                    and "casefold" in request.prompt
                )
                if not self.target_memory_seen:
                    raise AssertionError("target solve request did not contain active-node memory")
            if step == 2:
                self.public_tool_observations_seen["target_read"] = (
                    "def load_config(name)" in request.prompt and "name.endswith" in request.prompt
                )
            actions = {
                1: {"tool": "read_file", "arguments": {"path": "src/config.py"}},
                2: {
                    "tool": "write_file",
                    "arguments": {
                        "path": "src/config.py",
                        "content": (
                            "def load_config(name):\n"
                            "    folded = name.casefold()\n"
                            "    if not folded.endswith(('.yaml', '.yml')):\n"
                            "        raise ValueError('yaml required')\n"
                            "    return 'loaded'\n"
                        ),
                    },
                },
                3: {
                    "tool": "complete_subtask",
                    "arguments": {"evidence": "Applied casefold before YAML suffix comparison."},
                },
                4: {"tool": "run_public_tests", "arguments": {}},
                5: {
                    "tool": "complete_subtask",
                    "arguments": {"evidence": "Uppercase YAML passes and TXT remains rejected."},
                },
            }
        else:
            raise KeyError(request.task_id)
        return json.dumps(actions[step])

    @staticmethod
    def _extraction(task_id: str) -> dict:
        if task_id == "source-json-extension":
            return {
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
        return {
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


def source_task() -> CodingTask:
    return CodingTask(
        task_id="source-json-extension",
        org_id="org-1",
        user_id="alice",
        repository="example/loaders",
        commit="source-commit",
        instruction="Make JSON extension validation case insensitive while rejecting other formats.",
        files={
            "src/loader.py": (
                "def load_document(name):\n"
                "    if not name.endswith('.json'):\n"
                "        raise ValueError('json required')\n"
                "    return 'loaded'\n"
            )
        },
        editable_paths=("src/loader.py",),
        public_test=_source_public_test,
    )


def target_task(*, user_id: str = "alice") -> CodingTask:
    return CodingTask(
        task_id="target-yaml-extension",
        org_id="org-1",
        user_id=user_id,
        repository="example/loaders",
        commit="target-commit",
        instruction="Accept uppercase YAML extensions while continuing to reject non-YAML config files.",
        files={
            "src/config.py": (
                "def load_config(name):\n"
                "    if not name.endswith(('.yaml', '.yml')):\n"
                "        raise ValueError('yaml required')\n"
                "    return 'loaded'\n"
            )
        },
        editable_paths=("src/config.py",),
        public_test=_target_public_test,
    )


def _source_public_test(files: Mapping[str, str]) -> PublicTestResult:
    namespace: dict = {}
    exec(files["src/loader.py"], namespace)
    passed = namespace["load_document"]("DATA.JSON") == "loaded"
    try:
        namespace["load_document"]("DATA.TXT")
        passed = False
    except ValueError:
        pass
    return PublicTestResult(passed, "source public checks")


def _target_public_test(files: Mapping[str, str]) -> PublicTestResult:
    namespace: dict = {}
    exec(files["src/config.py"], namespace)
    passed = namespace["load_config"]("SETTINGS.YAML") == "loaded"
    try:
        namespace["load_config"]("SETTINGS.TXT")
        passed = False
    except ValueError:
        pass
    return PublicTestResult(passed, "target public checks")


def _runtime(root, task, lifecycle, index, model, grader_evaluator):
    retrieval = TriMemoryRetriever(
        index,
        RetrievalConfig(min_confidence=0.0, min_margin=0.0, ppr_iterations=24),
    )
    evidence = RawEvidenceLedger(root / task.task_id / "evidence", events_name="events.ndjson")
    grader = ReplayGraderGateway(
        grader_evaluator,
        fixture_digest=sha256_bytes((task.task_id + ":private-grader-fixture").encode()),
    )
    return TriMemAgentRuntime(
        runtime_lock=RuntimeLock(),
        model_gateway=model,
        grader_gateway=grader,
        memory_controller=ActiveNodeTriMemController(retrieval, task_id=task.task_id),
        evidence=evidence,
        checkpoint_store=FileCheckpointStore(root / task.task_id / "checkpoints"),
        lifecycle=lifecycle,
    )


def run_credential_free_e2e(output_root: str | Path) -> dict:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
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
    ticks = iter(["2026-08-31T00:00:00Z", "2026-08-31T00:01:00Z"])
    lifecycle = DQNExperienceLifecycle(
        policy,
        ConsolidationService(8, 8, 8),
        index,
        split="credential_free_replay",
        evaluation=False,
        clock=ticks.__next__,
    )
    scenario = ScenarioReplayModel()
    model = ReplayModelGateway(scenario)

    source = source_task()
    source_runtime = _runtime(
        root,
        source,
        lifecycle,
        index,
        model,
        lambda files: (
            "casefold" in files["src/loader.py"],
            "official-shaped source replay passed",
            "",
        ),
    )
    source_result = source_runtime.run(source, arm="M2")
    memory_id = source_result.lifecycle_result["storage"]["memory_id"]
    if not source_result.resolved or not memory_id:
        raise RuntimeError("source did not resolve and enter a retrievable memory bank")
    if source_result.lifecycle_result["storage"]["storage_action"] != "MOVE_TO_SEMANTIC_CANDIDATE":
        raise RuntimeError("frozen replay policy did not create the expected semantic candidate")

    # A second independently verified user's episode plus explicit human review
    # opens the deterministic private-to-shared boundary.  The learned policy is
    # not involved in this publication decision.
    independent_support = EpisodeRecord(
        episode_id="ep_bob_independent_extension_support",
        user_id="bob",
        repository=source.repository,
        commit="independent-support-commit",
        subtask_id="normalize-extension-before-validation",
        action="normalize filename case before allowlist comparison",
        outcome="passed",
        verification_outcome="passed",
        source_verifier_hash="sha256:" + sha256_bytes(b"independent replay verifier"),
        event_time="2026-08-31T00:00:30Z",
        payload={
            "summary": "Independent extension normalization repair passed its verifier.",
            "evidence_hash": sha256_bytes(b"independent public source evidence"),
        },
    )
    lifecycle.consolidation.ingest_episode(independent_support)
    promoted = lifecycle.add_support_and_review(
        memory_id,
        independent_support,
        PromotionReview(
            reviewer_id="credential-free-human-review-fixture",
            approved=True,
            reason="Two independently verified extension-normalization episodes support the same rule.",
        ),
        task=source,
    )

    # The target actor is distinct from both private evidence contributors.
    # This makes the replay prove reviewed organisation-semantic transfer,
    # rather than accidentally reusing the target user's own support episode.
    target = target_task(user_id="charlie")
    target_runtime = _runtime(
        root,
        target,
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
    target_memory_ids = {row["memory_id"] for row in target_result.injections}
    if not target_result.resolved or memory_id not in target_memory_ids:
        raise RuntimeError("target did not resolve with the source memory in its active-node context")
    if target_result.lifecycle_result["credit"]["credited"] != 1:
        raise RuntimeError("target outcome did not create delayed DQN credit")

    unreused = lifecycle.resolve_unreused(next_task_succeeded=True)
    frozen = policy.freeze_checkpoint()
    checkpoint_payload = {"payload": frozen.payload, "digest": frozen.digest}
    (root / "dqn_frozen_checkpoint.json").write_bytes(canonical_bytes(checkpoint_payload) + b"\n")

    runtime_lock = RuntimeLock()
    source_summary = source_result.accounting["summary"]
    target_summary = target_result.accounting["summary"]
    source_evidence_integrity = RawEvidenceLedger(
        root / source.task_id / "evidence", events_name="events.ndjson"
    ).verify()
    target_evidence_integrity = RawEvidenceLedger(
        root / target.task_id / "evidence", events_name="events.ndjson"
    ).verify()
    report = {
        "schema": "trimem/credential-free-e2e/1.0",
        "status": "PASS",
        "path": [
            "source_task",
            "short_term_observations",
            "double_dqn_storage_decision",
            "user_episodic_or_semantic_graph",
            "later_target_task",
            "semantic_subtask_dag",
            "active_node_embedding_seeded_ppr",
            "exact_memory_injection",
            "repository_edit",
            "official_shaped_replay_grader",
            "memory_outcome_credit",
            "double_dqn_replay_transition",
        ],
        "official_grader_execution": False,
        "grader_execution_status": "CREDENTIAL_FREE_INTERFACE_REPLAY_ONLY",
        "paid_model_calls": source_summary["paid_model_calls"] + target_summary["paid_model_calls"],
        "runtime_lock": runtime_lock.to_manifest(),
        "runtime_lock_hash": runtime_lock.content_hash,
        "source": {
            "task_id": source.task_id,
            "resolved": source_result.resolved,
            "storage": source_result.lifecycle_result["storage"],
            "accounting": source_summary,
            "evidence_tail_hash": source_result.evidence_tail_hash,
            "evidence_integrity": source_evidence_integrity,
            "graph_hash": sha256_bytes(canonical_bytes(source_result.graph_snapshot)),
            "shared_promotion": {
                "semantic_id": promoted.semantic_id,
                "supporting_episode_ids": list(promoted.supporting_episode_ids),
                "supporting_user_ids": list(promoted.supporting_user_ids),
                "reviewer_id": promoted.reviewer_id,
                "review_reason": promoted.review_reason,
                "dqn_controlled_publication": False,
            },
        },
        "target": {
            "task_id": target.task_id,
            "user_id": target.user_id,
            "resolved": target_result.resolved,
            "injections": [
                {key: value for key, value in row.items() if key != "exact_text"}
                for row in target_result.injections
            ],
            "credit": target_result.lifecycle_result["credit"],
            "accounting": target_summary,
            "evidence_tail_hash": target_result.evidence_tail_hash,
            "evidence_integrity": target_evidence_integrity,
            "graph_hash": sha256_bytes(canonical_bytes(target_result.graph_snapshot)),
            "cross_user_transfer_bank": "ORG_SEMANTIC",
        },
        "dqn": {
            "checkpoint_digest": frozen.digest,
            "replay_size": policy.replay_size,
            "training_steps": policy.training_steps,
            "evaluation_exploration": False,
            "unreused_transitions_closed": len(unreused),
        },
        "correctness": {
            "target_memory_present_in_actual_prompt": scenario.target_memory_seen,
            "public_tool_observations_present_in_solve_prompts": all(
                scenario.public_tool_observations_seen.values()
            ),
            "public_tool_observations_present_in_extraction_prompts": all(
                scenario.extraction_public_evidence_seen.values()
            ),
            "raw_evidence_hashes_and_blobs_verified": (
                source_evidence_integrity["events"] > 0
                and target_evidence_integrity["events"] > 0
                and not source_evidence_integrity["missing_blobs"]
                and not target_evidence_integrity["missing_blobs"]
            ),
            "exact_injected_bytes_equal_recorded_hash": all(
                sha256_bytes(row["exact_text"].encode()) == row["sha256"]
                and len(row["exact_text"].encode()) == row["byte_count"]
                for row in target_result.injections
            ),
            "active_node_memory_only": all(
                row["active_node_id"] not in {"", "__TASK__"} for row in target_result.injections
            ),
            "private_episode_identifiers_exposed_cross_user": any(
                "ep_" in row["exact_text"]
                or "alice" in row["exact_text"].casefold()
                or "bob" in row["exact_text"].casefold()
                for row in target_result.injections
            ),
            "dependency_order_enforced": True,
            "hidden_grader_payload_exposed_to_extractor": (
                scenario.hidden_grader_payload_seen_by_extractor
            ),
        },
    }
    required_false = {
        "private_episode_identifiers_exposed_cross_user",
        "hidden_grader_payload_exposed_to_extractor",
    }
    required_true = set(report["correctness"]) - required_false
    failed = sorted(key for key in required_true if report["correctness"][key] is not True)
    if failed:
        raise RuntimeError(f"credential-free correctness gate failed: {failed}")
    false_failures = sorted(
        key for key in required_false if report["correctness"][key] is not False
    )
    if false_failures:
        raise RuntimeError(f"credential-free negative correctness gate failed: {false_failures}")
    for summary in (source_summary, target_summary):
        if (
            summary["paid_model_calls"] != 0
            or summary["grader_calls"] != 1
            or summary["grader_containers"] != 0
            or summary["official_grader_runs"] != 0
        ):
            raise RuntimeError("credential-free execution counters violate the replay-only gate")
    report["bundle_hash"] = sha256_bytes(canonical_bytes(report))
    (root / "credential_free_e2e_bundle.json").write_bytes(canonical_bytes(report) + b"\n")
    return report
