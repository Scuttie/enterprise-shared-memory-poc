"""Credential-free checks for production M1/M2 canonical retention lifecycles."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.agent_runtime import (
    CodingTask,
    ExperienceExtraction,
    NullExperienceLifecycle,
)
from enterprise_memory.trimem.grader import GradeResult
from enterprise_memory.trimem.lifecycle import LifecycleError
from enterprise_memory.trimem.policy import (
    DoubleDQNMemoryPolicy,
    MemoryAction,
    PolicyDecision,
)
from enterprise_memory.trimem.production_lifecycle import (
    production_dqn_lifecycle_factory,
)
from enterprise_memory.trimem.postgres_retrieval import project_canonical_rows
from enterprise_memory.trimem.postgres_store import CanonicalReloadRows
from enterprise_memory.trimem.production_v03_lifecycle import (
    LIVE_V03_IMPLEMENTATION_HASH,
    PostgresV03ExperienceLifecycle,
)
from enterprise_memory.trimem.schema import EdgeType, GraphKind, NodeType, canonical_hash
from enterprise_memory.trimem.ppr import SeedSignal, rank_graph
from enterprise_memory.trimem.retrieval import MemoryKind
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "configs/trimem_v1/m2_policy.json").read_text(encoding="utf-8"))
MANIFEST_HASH = "sha256:" + sha256_bytes(canonical_bytes(MANIFEST))
NAMESPACE = "trimem:lifecycle:development:M2"
REPOSITORY_ID = "11111111-1111-4111-8111-111111111111"
SOLVE_JOB_ID = "22222222-2222-4222-8222-222222222222"


class _LiveV03RuntimeFixture:
    implementation_hash = LIVE_V03_IMPLEMENTATION_HASH

    def __init__(self):
        self.retained = []
        self.rows = {}

    def retention_descriptor(self, *, task, identity, injections, event_time):
        body = {
            "schema": "trimem/live-v03-retention-descriptor/1.0",
            "namespace": "trimem:lifecycle:development:M1",
            "org_id": task.org_id,
            "user_id": task.user_id,
            "episode_id": str(
                uuid.uuid5(uuid.UUID(identity["solve_job_id"]), "fixture-episode")
            ),
            "solve_job_id": identity["solve_job_id"],
            "repository_id": identity["repository_id"],
            "task_id": task.task_id,
            "source_commit": task.commit,
            "content_hash": "sha256:" + "3" * 32,
            "canonical": {
                "task_id": task.task_id,
                "repo_id": identity["repository_id"],
                "commit": task.commit,
                "outcome": "success",
                "injected_memory_ids": [item["memory_id"] for item in injections],
            },
            "event_time": event_time,
        }
        return {**body, "digest": canonical_hash(body)}

    def retain_episode(self, descriptor):
        row = {
            "schema": "trimem/live-v03-retention-evidence/1.0",
            "namespace": "trimem:lifecycle:development:M1",
            "episode_id": descriptor["episode_id"],
        }
        row["digest"] = canonical_hash(row)
        self.rows[descriptor["episode_id"]] = dict(descriptor)
        self.retained.append((descriptor["task_id"], descriptor["solve_job_id"]))
        return row

    def verify_pending_retention(self, descriptor):
        observed = self.rows.get(descriptor["episode_id"])
        if observed is not None and observed != dict(descriptor):
            raise LifecycleError("pending mismatch")
        return "EXACT_PENDING_APPEND" if observed is not None else "ABSENT"

    def recall_plan(self, **kwargs):
        raise AssertionError("retention test must not recall")

    def verify_audit(self, **kwargs):
        return None

    def verify_audit_digest(self, **kwargs):
        return None

    def state_evidence(self, *, org_id, user_id, episode_ids=()):
        body = {
            "schema": "trimem/live-v03-canonical-state/1.0",
            "namespace": "trimem:lifecycle:development:M1",
            "org_id": org_id,
            "user_id": user_id,
            "stream_episode_ids": list(sorted(episode_ids)),
            "rows": [
                {
                    "episode_id": episode_id,
                    "descriptor_digest": canonical_hash({
                        key: value
                        for key, value in self.rows[episode_id].items()
                        if key != "digest"
                    }),
                }
                for episode_id in sorted(self.rows)
            ],
        }
        return {**body, "digest": canonical_hash(body)}

    def verify_state(self, evidence, *, pending_descriptor=None):
        observed = self.state_evidence(
            org_id=evidence["org_id"],
            user_id=evidence["user_id"],
            episode_ids=tuple(evidence["stream_episode_ids"]),
        )
        if pending_descriptor is not None:
            expected = dict(evidence)
            body = {key: value for key, value in expected.items() if key != "digest"}
            body["rows"] = sorted(
                [
                    *body["rows"],
                    {
                        "episode_id": pending_descriptor["episode_id"],
                        "descriptor_digest": pending_descriptor["digest"],
                    },
                ],
                key=lambda row: row["episode_id"],
            )
            expected = {**body, "digest": canonical_hash(body)}
        if observed != dict(evidence):
            if pending_descriptor is None or observed != expected:
                raise LifecycleError("state mismatch")
            return "EXACT_PENDING_APPEND"
        return "ABSENT" if pending_descriptor is not None else "EXACT_STATE"


class _Encoder:
    def embed(self, text):
        assert isinstance(text, str) and text
        return (1.0,) + (0.0,) * 383

    def provenance(self):
        lock = MANIFEST["double_dqn"]["feature_encoder"]
        return {
            "model_id": lock["model_id"],
            "revision": lock["revision"],
            "dimensions": 384,
            "normalized": True,
            "production": True,
            "credential_free": True,
        }


class _CredentialFreeFixtureEncoder(_Encoder):
    def provenance(self):
        value = dict(super().provenance())
        value["production"] = False
        value["credential_free_fixture"] = True
        return value


class _Persistence:
    def __init__(self):
        self.bundles = []
        self.fail = False
        self.feature_rows = []

    def persist_bundle(self, ctx, bundle):
        if self.fail:
            raise RuntimeError("canonical transaction failed")
        self.bundles.append((ctx, bundle))
        return {
            "receipt_digest": "sha256:" + "9" * 64,
            "indexed": tuple({"node_id": item} for item in bundle.index_node_ids),
        }

    def load_policy_feature_rows(self, ctx, *, limit):
        body = {
            "schema": "trimem/canonical-policy-feature-rows/1.0",
            "namespace": NAMESPACE,
            "history_limit": limit,
            "rows": list(self.feature_rows),
        }
        return {**body, "digest": canonical_hash(body)}

    def checkpoint_state(self):
        return {"schema": "fixture-persistence/1", "bundle_count": len(self.bundles)}

    def restore_state(self, value):
        if value.get("schema") != "fixture-persistence/1":
            raise ValueError("fixture persistence state mismatch")


def _identity(task):
    solve_job_id = (
        SOLVE_JOB_ID
        if task.task_id == "source"
        else str(uuid.uuid5(uuid.UUID(SOLVE_JOB_ID), task.task_id))
    )
    return {"repository_id": REPOSITORY_ID, "solve_job_id": solve_job_id}


def _task(task_id="source"):
    return CodingTask(
        task_id=task_id,
        org_id="org-a",
        user_id="alice",
        repository="example/loaders",
        commit="abc123",
        instruction="Normalize an allowed extension without accepting other formats.",
        files={"src/loader.py": "pass\n"},
        editable_paths=("src/loader.py",),
    )


def _graph():
    graph = ShortTermWorkingGraph("source", "repair extension validation", "example/loaders")
    graph.add_subtask(SubtaskSpec(
        node_id="locate",
        objective="locate extension validation",
        operation="inspect suffix allowlist",
        files=("src/loader.py",),
        symbols=("load_document",),
        apis=("str.endswith",),
        errors=("ValueError",),
    ))
    graph.add_subtask(SubtaskSpec(
        node_id="repair",
        objective="normalize extension before validation",
        operation="casefold suffix before allowlist comparison",
        dependencies=("locate",),
        files=("src/loader.py",),
        symbols=("load_document",),
        tests=("uppercase allowed suffix", "reject other formats"),
    ))
    return graph


def _extraction(scope="CROSS_REPOSITORY"):
    return ExperienceExtraction(
        episode={"summary": "Extension validation was repaired.", "action": "casefold suffix"},
        semantic_candidate={
            "applicability_scope": scope,
            "preconditions": "An extension allowlist is documented as case insensitive.",
            "operation": "Normalize the candidate suffix before comparing with the allowlist.",
            "invariant": "Values outside the allowlist remain rejected.",
            "non_applicability": "Do not apply to deliberately case-sensitive protocols.",
            "verification": "Test one uppercase allowed suffix and one disallowed suffix.",
        },
        response_hash="a" * 64,
        patch_hash="b" * 64,
        public_evidence_hash="c" * 64,
    )


def _grade(resolved=True):
    return GradeResult(
        task_id="source",
        resolved=resolved,
        exit_code=0 if resolved else 1,
        stdout="ok" if resolved else "",
        stderr="" if resolved else "failed",
        report={"public_tests": resolved},
        grader_id="credential-free",
        container_digest="fixture",
        official=False,
        wall_time_ms=1,
    )


def _outcome_metrics(**overrides):
    value = {
        "schema": "trimem/outcome-metrics/1.0",
        "subtask_completion": 1.0,
        "actual_total_tokens": 1000,
        "actual_reasoning_tokens": 100,
        "actual_wall_time_ms": 2000,
        "injected_context_bytes": 600,
        "stale_conflict_reuse_count": 0,
        "stale_conflict_memory_ids": [],
    }
    value.update(overrides)
    return value


def _factory():
    return production_dqn_lifecycle_factory(
        _identity,
        policy_manifest=MANIFEST,
        expected_policy_manifest_hash=MANIFEST_HASH,
    )


def _lifecycle(persistence=None):
    persistence = persistence or _Persistence()
    lifecycle = _factory()(
        policy=None,
        persistence=persistence,
        namespace=NAMESPACE,
        split="development",
        evaluation=False,
        embedder=_Encoder(),
    )
    return lifecycle, persistence


def test_full_manifest_and_encoder_are_hash_bound_before_development():
    assert _factory().configuration_hash == MANIFEST_HASH
    changed = json.loads(json.dumps(MANIFEST))
    changed["reward"]["successful_reuse"] = 0.5
    with pytest.raises(LifecycleError, match="manifest hash"):
        production_dqn_lifecycle_factory(
            _identity,
            policy_manifest=changed,
            expected_policy_manifest_hash=MANIFEST_HASH,
        )

    lifecycle, _ = _lifecycle()
    assert lifecycle.policy.frozen is False
    assert lifecycle.feature_projection == "NONE"
    assert lifecycle.feature_encoder_provenance["production"] is True
    assert lifecycle.retrieval_config == MANIFEST["retrieval"]
    assert lifecycle.capacity_config == MANIFEST["consolidation"]["capacities"]


def test_fixture_encoder_is_confined_to_explicit_credential_free_replay_split():
    factory = _factory()
    fixture = _CredentialFreeFixtureEncoder()
    replay = factory(
        policy=None,
        persistence=_Persistence(),
        namespace="trimem:lifecycle:credential-free:M2",
        split="credential_free_replay",
        evaluation=False,
        embedder=fixture,
    )
    assert replay.feature_encoder_provenance["credential_free_fixture"] is True
    with pytest.raises(LifecycleError, match="production feature encoder"):
        factory(
            policy=None,
            persistence=_Persistence(),
            namespace=NAMESPACE,
            split="development",
            evaluation=False,
            embedder=fixture,
        )


def test_state_features_use_sealed_canonical_similarity_access_strength_and_recency():
    persistence = _Persistence()
    persistence.feature_rows = [{
        "node_id": "prior-semantic",
        "graph_id": "prior-graph",
        "graph_kind": "USER_SEMANTIC",
        "repository_id": REPOSITORY_ID,
        "retrieval_text": "prior normalized extension rule",
        "version": "abc123",
        "version_valid": True,
        "stale": False,
        "last_activity_at": "2026-08-31T00:00:00Z",
        "reuse_count": 5,
        "strength": {
            "support": 2.0,
            "successful_reuse": 3.0,
            "independent_user_evidence": 0.0,
            "recent_verification": 1.0,
            "negative_transfer": 1.0,
            "contradiction": 0.0,
            "version_staleness": 0.0,
        },
        "node_content_hash": "sha256:" + "1" * 64,
        "graph_content_hash": "sha256:" + "2" * 64,
    }]
    lifecycle, _ = _lifecycle(persistence)
    lifecycle.clock = lambda: "2026-09-01T00:00:00Z"
    lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
        MemoryAction.MOVE_TO_EPISODIC,
        (0.0, 1.0, 0.0),
        mask.as_tuple(),
        0.0,
        evaluation,
    )
    stored = lifecycle.store_experience(
        _task(), _graph(), _extraction(), _grade(), ()
    )
    state = next(iter(lifecycle.pending_by_memory_id.values()))["state"]
    assert state["novelty"] == 0.0
    assert state["redundancy"] == 1.0
    assert state["recency"] == pytest.approx(0.5 ** (86400 / 2592000))
    assert state["reuse_frequency"] == 0.5
    assert state["past_gain_loss"] == pytest.approx(2.0 / 7.0)
    assert state["version_validity"] == 1.0
    assert state["memory_occupancy"] == pytest.approx(1 / 1200)
    provenance = stored["state_feature_provenance"]
    assert provenance["history_status"] == "MATCHED"
    assert provenance["nearest_node_id"] == "prior-semantic"
    assert provenance["canonical_history_count"] == 1


def test_reward_binds_every_frozen_success_compute_storage_and_safety_component():
    lifecycle, _ = _lifecycle()
    lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
        MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
        (0.0, 0.0, 1.0),
        mask.as_tuple(),
        0.0,
        evaluation,
    )
    stored = lifecycle.store_experience(
        _task(), _graph(), _extraction(), _grade(), ()
    )
    credited = lifecycle.credit_outcome(
        _task("reward-target"),
        _grade(True),
        ({
            "memory_id": stored["memory_id"],
            "kind": stored["memory_kind"],
            "canonical_graph_id": stored["canonical_graph_id"],
            "namespace": stored["namespace"],
        },),
        outcome_metrics=_outcome_metrics(
            subtask_completion=0.5,
            actual_total_tokens=100000,
            actual_wall_time_ms=600000,
            injected_context_bytes=12000,
            stale_conflict_reuse_count=1,
            stale_conflict_memory_ids=[stored["memory_id"]],
        ),
    )
    row = credited["transitions"][0]
    components = row["reward_components"]
    assert set(components) == {
        "outcome", "reuse", "subtask_completion", "context_cost",
        "token_cost", "latency_cost", "storage_cost", "stale_conflict",
    }
    assert components["outcome"] == 1.0
    assert components["reuse"] == 0.25
    assert components["subtask_completion"] == 0.1
    assert components["context_cost"] == -0.05
    assert components["token_cost"] == -0.05
    assert components["latency_cost"] == -0.02
    assert components["storage_cost"] < 0.0
    assert components["stale_conflict"] == -0.5
    assert row["reward"] == pytest.approx(sum(components.values()))


def test_semantic_store_builds_multi_node_edges_and_generalization_provenance():
    lifecycle, persistence = _lifecycle()
    lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
        MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
        (0.0, 0.0, 1.0),
        mask.as_tuple(),
        0.0,
        evaluation,
    )
    result = lifecycle.store_experience(
        _task(), _graph(), _extraction(), _grade(), ()
    )
    assert result["storage_action"] == "MOVE_TO_SEMANTIC_CANDIDATE"
    assert result["retained_records"] == 2
    assert result["archived_records"] == 0
    assert result["net_memory_growth"] == 2
    bundle = persistence.bundles[0][1]
    assert len(bundle.graphs) == 3
    assert len(bundle.nodes) > 20
    assert len(bundle.edges) > 20
    assert set(item.edge_type for item in bundle.edges) >= {
        EdgeType.DECOMPOSES_TO,
        EdgeType.DEPENDS_ON,
        EdgeType.TOUCHES,
        EdgeType.CALLS,
        EdgeType.OBSERVED,
        EdgeType.APPLIED,
        EdgeType.VERIFIED_BY,
        EdgeType.PRODUCED,
        EdgeType.DERIVED_FROM,
        EdgeType.VALID_FOR,
    }
    assert set(item.node_type for item in bundle.nodes) >= {
        NodeType.TASK,
        NodeType.SUBTASK,
        NodeType.EPISODE,
        NodeType.SEMANTIC_RULE,
        NodeType.REPOSITORY,
        NodeType.FILE,
        NodeType.SYMBOL,
        NodeType.API,
        NodeType.ERROR,
        NodeType.TEST,
        NodeType.OPERATION,
        NodeType.OUTCOME,
        NodeType.USER,
        NodeType.VERSION,
    }
    semantic = next(
        item for item in bundle.nodes if item.node_type == NodeType.SEMANTIC_RULE
    )
    episode = next(item for item in bundle.nodes if item.node_type == NodeType.EPISODE)
    assert semantic.repository_id is None
    assert semantic.canonical_payload["provenance"]["generalized_repository"] is True
    assert semantic.canonical_payload["provenance"]["applicability_decision_reason"] == (
        "EXPLICIT_CROSS_REPOSITORY_IDENTIFIER_FREE"
    )
    assert bundle.supports[0].source_evidence_hash == episode.payload_hash
    assert bundle.index_node_ids == (semantic.node_id,)
    assert len(bundle.strengths) == 1
    assert bundle.strengths[0].semantic_node_id == semantic.node_id
    assert bundle.strengths[0].strength.support == 1.0
    assert bundle.strengths[0].strength.recent_verification == 1.0
    assert bundle.strengths[0].strength.score == 2.0

    semantic_graph = next(item for item in bundle.graphs if item.kind == GraphKind.USER_SEMANTIC)
    semantic_nodes = tuple(item for item in bundle.nodes if item.graph_id == semantic_graph.graph_id)
    semantic_edges = tuple(item for item in bundle.edges if item.graph_id == semantic_graph.graph_id)
    reload_rows = CanonicalReloadRows(
        namespace=NAMESPACE,
        graph_kind=GraphKind.USER_SEMANTIC,
        graphs=(semantic_graph,),
        nodes=semantic_nodes,
        edges=semantic_edges,
        candidate_node_ids=(semantic.node_id,),
        digest="sha256:" + "d" * 64,
    )
    snapshot = project_canonical_rows(
        reload_rows,
        MemoryKind.USER_SEMANTIC,
        user_id="alice",
        org_id="org-a",
        repository="different/repository",
    )
    assert len(snapshot.nodes) > 8 and any(snapshot.adjacency.values())
    ranked = rank_graph(
        snapshot.nodes,
        snapshot.adjacency,
        (SeedSignal("active_operation", "normalize uppercase suffix allowlist"),),
        embedder=_Encoder(),
        iterations=16,
    )
    assert semantic.node_id in {item.node_id for item in ranked}
    assert any(item.node_id != semantic.node_id for item in ranked)


@pytest.mark.parametrize(
    ("resolved", "successful_reuse", "negative_transfer"),
    ((True, 1.0, 0.0), (False, 0.0, 1.0)),
)
def test_semantic_reuse_updates_canonical_strength_in_credit_transaction(
    resolved, successful_reuse, negative_transfer
):
    lifecycle, persistence = _lifecycle()
    lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
        MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
        (0.0, 0.0, 1.0),
        mask.as_tuple(),
        0.0,
        evaluation,
    )
    stored = lifecycle.store_experience(
        _task(), _graph(), _extraction(), _grade(), ()
    )
    credited = lifecycle.credit_outcome(
        _task("later-target"),
        _grade(resolved),
        ({
            "memory_id": stored["memory_id"],
            "kind": stored["memory_kind"],
            "canonical_graph_id": stored["canonical_graph_id"],
            "namespace": stored["namespace"],
        },),
        outcome_metrics=_outcome_metrics(),
    )
    assert credited["credited"] == 1
    bundle = persistence.bundles[-1][1]
    assert len(bundle.transitions) == 1
    assert len(bundle.strength_increments) == 1
    increment = bundle.strength_increments[0]
    assert increment.recent_verification == successful_reuse
    assert increment.successful_reuse == successful_reuse
    assert increment.negative_transfer == negative_transfer


def test_semantic_strength_keeps_accumulating_after_delayed_credit_is_consumed():
    lifecycle, persistence = _lifecycle()
    lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
        MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
        (0.0, 0.0, 1.0),
        mask.as_tuple(),
        0.0,
        evaluation,
    )
    stored = lifecycle.store_experience(
        _task(), _graph(), _extraction(), _grade(), ()
    )
    injection = ({
        "memory_id": stored["memory_id"],
        "kind": stored["memory_kind"],
        "canonical_graph_id": stored["canonical_graph_id"],
        "namespace": stored["namespace"],
    },)
    first = lifecycle.credit_outcome(
        _task("target-one"), _grade(True), injection,
        outcome_metrics=_outcome_metrics(),
    )
    second = lifecycle.credit_outcome(
        _task("target-two"), _grade(False), injection,
        outcome_metrics=_outcome_metrics(),
    )
    assert first["credited"] == 1 and second["credited"] == 0
    assert len(first["strength_updates"]) == 1
    assert len(second["strength_updates"]) == 1
    increments = [
        bundle.strength_increments[0]
        for _, bundle in persistence.bundles
        if bundle.strength_increments
    ]
    assert [item.successful_reuse for item in increments] == [1.0, 0.0]
    assert [item.negative_transfer for item in increments] == [0.0, 1.0]


def test_persistence_failure_restores_mutable_policy_exactly():
    lifecycle, persistence = _lifecycle()
    before = lifecycle.policy.runtime_state()
    persistence.fail = True
    with pytest.raises(RuntimeError, match="canonical transaction"):
        lifecycle.store_experience(_task(), _graph(), _extraction(), _grade(), ())
    assert lifecycle.policy.runtime_state() == before
    assert lifecycle.pending_by_memory_id == {}


def test_prepared_event_and_feature_snapshot_recreate_exact_bundle_after_commit_crash():
    first_persistence = _Persistence()
    first, _ = _lifecycle(first_persistence)
    first.clock = lambda: "2026-09-01T01:02:03Z"
    decision = lambda state, mask, evaluation=False: PolicyDecision(
        MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
        (0.0, 0.0, 1.0),
        mask.as_tuple(),
        0.0,
        evaluation,
    )
    first.policy.decide = decision
    task = _task()
    first.before_task(task=task, sequence_index=0)
    prepared_checkpoint = first.checkpoint_state()
    first_result = first.store_experience(
        task, _graph(), _extraction(), _grade(), ()
    )
    first_bundle = first_persistence.bundles[-1][1]
    first_policy_state = first.policy.runtime_state()

    drifted_persistence = _Persistence()
    drifted_persistence.feature_rows = [{"this": "must not be reloaded"}]
    resumed, _ = _lifecycle(drifted_persistence)
    resumed.clock = lambda: (_ for _ in ()).throw(AssertionError("clock drift"))
    resumed.policy.decide = decision
    resumed.restore_state(prepared_checkpoint)
    resumed_result = resumed.store_experience(
        task, _graph(), _extraction(), _grade(), ()
    )
    resumed_bundle = drifted_persistence.bundles[-1][1]

    assert canonical_hash(resumed_bundle) == canonical_hash(first_bundle)
    assert resumed_bundle.operation_id == first_bundle.operation_id
    assert resumed_result["memory_id"] == first_result["memory_id"]
    assert resumed.policy.runtime_state() == first_policy_state


def test_checkpoint_restore_tamper_and_stream_finalization_close_every_pending_credit():
    lifecycle, persistence = _lifecycle()
    lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
        MemoryAction.FORGET, (1.0, 0.0, 0.0), mask.as_tuple(), 0.0, evaluation
    )
    lifecycle.store_experience(_task(), _graph(), _extraction(), _grade(), ())
    assert lifecycle.policy.pending_credit_count == 1
    saved = lifecycle.checkpoint_state()
    restored, _ = _lifecycle()
    restored.restore_state(saved)
    assert restored.pending_by_memory_id == lifecycle.pending_by_memory_id
    tampered = {"payload": dict(saved["payload"]), "digest": saved["digest"]}
    tampered["payload"]["persisted_memory_count"] = 99
    with pytest.raises(LifecycleError, match="digest"):
        restored.restore_state(tampered)
    with pytest.raises(LifecycleError, match="not complete"):
        lifecycle.finalize_development_and_freeze(completed_cursor=11)
    checkpoint = lifecycle.finalize_development_and_freeze(completed_cursor=12)
    assert lifecycle.pending_by_memory_id == {}
    assert lifecycle.policy.pending_credit_count == 0
    assert lifecycle.policy.frozen is True
    assert DoubleDQNMemoryPolicy.from_frozen_checkpoint(checkpoint).frozen is True
    final_bundle = persistence.bundles[-1][1]
    assert len(final_bundle.transitions) == 1
    assert final_bundle.transitions[0].reward <= 0.0

    heldout = _factory()(
        policy=DoubleDQNMemoryPolicy.from_frozen_checkpoint(checkpoint),
        persistence=_Persistence(),
        namespace="trimem:lifecycle:heldout:M2",
        split="heldout",
        evaluation=True,
        embedder=_Encoder(),
    )
    assert heldout.policy.frozen and heldout.evaluation


@pytest.mark.parametrize(
    "blocked_value",
    (
        "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "Bear" + "er " + "abcdefghijklmnopqrstuvwxyz1234",
        "e" + "yJabcdefghijk.abcdefghijk.abcdefghijk",
    ),
)
def test_product_security_scanner_forces_m2_forget_before_dqn(blocked_value):
    lifecycle, persistence = _lifecycle()
    base = _extraction()
    semantic = dict(base.semantic_candidate)
    semantic["operation"] = blocked_value
    extraction = ExperienceExtraction(
        episode=base.episode,
        semantic_candidate=semantic,
        response_hash=base.response_hash,
        patch_hash=base.patch_hash,
        public_evidence_hash=base.public_evidence_hash,
    )

    def decide(state, mask, evaluation=False):
        assert mask.as_tuple() == (True, False, False)
        return PolicyDecision(
            MemoryAction.FORGET,
            (1.0, 100.0, 100.0),
            mask.as_tuple(),
            0.0,
            evaluation,
        )

    lifecycle.policy.decide = decide
    result = lifecycle.store_experience(
        _task(), _graph(), extraction, _grade(), ()
    )
    assert result["storage_action"] == "FORGET"
    assert result["deterministic_gate"] == "SECRET_FILTER"
    assert result["secret_free"] is False
    assert result["security_scan_result"] == "BLOCK_SECRET"
    bundle = persistence.bundles[-1][1]
    assert all(item.kind == GraphKind.SHORT_TERM_WORKING for item in bundle.graphs)
    assert not bundle.index_node_ids


def test_v03_lifecycle_retains_exact_completed_solve_episode_independent_of_grade():
    runtime = _LiveV03RuntimeFixture()
    lifecycle = PostgresV03ExperienceLifecycle(
        runtime,
        namespace="trimem:lifecycle:development:M1",
        identity_resolver=_identity,
        clock=lambda: "2026-09-01T00:00:00Z",
    )
    kept = lifecycle.store_experience(_task(), _graph(), _extraction(), _grade(), ())
    assert kept["storage_action"] == "V03_RETAIN_PRIVATE_EPISODE"
    assert (kept["retained_records"], kept["archived_records"], kept["net_memory_growth"]) == (
        1,
        0,
        1,
    )
    assert runtime.retained == [("source", SOLVE_JOB_ID)]
    secret_extractor_output = ExperienceExtraction(
        episode={
            "summary": "Extractor-only untrusted text that must never affect retention",
            "action": "must not affect the v0.3 canonical solve episode",
        },
        semantic_candidate=None,
        response_hash="d" * 64,
        patch_hash="e" * 64,
        public_evidence_hash="f" * 64,
    )
    retained_failure = lifecycle.store_experience(
        _task("failed"), _graph(), secret_extractor_output, _grade(False), ()
    )
    assert retained_failure["storage_action"] == "V03_RETAIN_PRIVATE_EPISODE"
    assert (
        retained_failure["retained_records"],
        retained_failure["archived_records"],
        retained_failure["net_memory_growth"],
    ) == (1, 0, 1)
    assert len(runtime.retained) == 2


def test_v03_lifecycle_recovers_only_exact_prepared_append_after_store_crash():
    runtime = _LiveV03RuntimeFixture()
    first = PostgresV03ExperienceLifecycle(
        runtime,
        namespace="trimem:lifecycle:development:M1",
        identity_resolver=_identity,
        clock=lambda: "2026-09-01T00:00:00Z",
    )
    task = _task()
    first.before_task(task=task, sequence_index=0)
    first.prepare_store_experience(task, _extraction(), _grade(), ())
    extracted_checkpoint = first.checkpoint_state()

    # Simulate the exact crash window: canonical DB/index commit succeeded,
    # but no LIFECYCLE_STORED checkpoint was written.
    pending = dict(first.pending_retention)
    runtime.retain_episode(pending)

    resumed = PostgresV03ExperienceLifecycle(
        runtime,
        namespace="trimem:lifecycle:development:M1",
        identity_resolver=_identity,
        clock=lambda: (_ for _ in ()).throw(AssertionError("clock drift")),
    )
    resumed.restore_state(extracted_checkpoint)
    replayed = resumed.store_experience(
        task, _graph(), _extraction(), _grade(), ()
    )
    assert replayed["memory_id"] == pending["episode_id"]
    assert resumed.pending_retention is None
    assert resumed.stored_task_ids == {task.task_id: pending["episode_id"]}

    tampered_runtime = _LiveV03RuntimeFixture()
    tampered_runtime.rows[pending["episode_id"]] = {**pending, "task_id": "other"}
    rejected = PostgresV03ExperienceLifecycle(
        tampered_runtime,
        namespace="trimem:lifecycle:development:M1",
        identity_resolver=_identity,
    )
    with pytest.raises(LifecycleError, match="(?:state|pending) mismatch"):
        rejected.restore_state(extracted_checkpoint)


def test_m0_null_lifecycle_reports_exact_zero_storage_accounting():
    result = NullExperienceLifecycle().store_experience(
        _task(), _graph(), _extraction(), _grade(), ()
    )
    assert result == {
        "storage_action": "NONE",
        "retained_records": 0,
        "archived_records": 0,
        "net_memory_growth": 0,
    }
