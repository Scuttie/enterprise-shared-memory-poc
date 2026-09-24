"""Production-shaped PG/Qdrant/canonical-PPR/access path without credentials."""
from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.agent_runtime import CodingTask, ExperienceExtraction
from enterprise_memory.trimem.agent_runtime import NoMemoryController
from enterprise_memory.trimem.arms import ActiveNodeTriMemController
from enterprise_memory.trimem.grader import GradeResult
from enterprise_memory.trimem.policy import MemoryAction, PolicyDecision
from enterprise_memory.trimem.postgres_retrieval import (
    AsyncPostgresQdrantRetrievalStore,
    PostgresInjectionAuditor,
    SyncPostgresQdrantRetrievalStore,
)
from enterprise_memory.trimem.postgres_store import (
    AppendReceipt,
    CanonicalReloadRows,
    IndexOutboxIntent,
    PostgresTriMemStore,
    PromotionEvidence,
)
from enterprise_memory.trimem.production_lifecycle import production_dqn_lifecycle_factory
from enterprise_memory.trimem.production_promotion import (
    PostgresReviewedPromotionService,
    PromotionError,
    promotion_review_evidence_hash,
)
from enterprise_memory.trimem.production_v03_lifecycle import (
    LIVE_V03_IMPLEMENTATION_HASH,
    LiveV03Runtime,
    PostgresV03ExperienceLifecycle,
)
from enterprise_memory.trimem.postgres_retrieval import production_v03_controller_factory
from enterprise_memory.trimem.production_runtime import CanonicalLifecyclePersistence, DedicatedAsyncLoop
from enterprise_memory.trimem.retrieval import RetrievalConfig, TriMemoryRetriever
from enterprise_memory.trimem.schema import (
    AccessContext,
    EdgeType,
    GraphKind,
    NodeType,
    ReviewAuthority,
    ReviewProvenance,
    canonical_hash,
)
from enterprise_memory.trimem.vector_index import QdrantVectorIndexV2
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "configs/trimem_v1/m2_policy.json").read_text(encoding="utf-8"))
MANIFEST_HASH = "sha256:" + sha256_bytes(canonical_bytes(MANIFEST))
NAMESPACE = "trimem:production-shaped:credential_free_replay:M2"
REPOSITORY_ID = "11111111-1111-4111-8111-111111111111"
SOLVE_JOB_ID = "22222222-2222-4222-8222-222222222222"
NOW = "2026-09-01T00:00:00Z"


class _ProductionEncoder:
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


def _matches(payload, condition):
    if "is_null" in condition:
        return payload.get(condition["is_null"]["key"]) is None
    return payload.get(condition["key"]) == condition["match"]["value"]


class _Qdrant:
    def __init__(self, events):
        self.collections = {}
        self.events = events

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, *, vectors_config):
        self.collections[collection_name] = {
            "vectors_config": dict(vectors_config), "points": {}
        }

    def get_collection(self, collection_name):
        return {"vectors_config": self.collections[collection_name]["vectors_config"]}

    def create_payload_index(self, collection_name, *, field_name, field_schema, wait):
        assert wait is True

    def upsert(self, collection_name, *, points, wait):
        assert wait is True
        self.events.append("qdrant_upsert")
        for point in points:
            self.collections[collection_name]["points"][str(point["id"])] = dict(point)

    def delete(self, collection_name, *, points_selector, wait):
        assert wait is True
        for point_id in points_selector["points"]:
            self.collections[collection_name]["points"].pop(str(point_id), None)

    def query_points(self, collection_name, *, query, query_filter, limit,
                     with_payload, with_vectors):
        assert with_payload and not with_vectors
        self.events.append("qdrant_search")
        rows = []
        for point in self.collections[collection_name]["points"].values():
            payload = point["payload"]
            if not all(_matches(payload, item) for item in query_filter["must"]):
                continue
            minimum = query_filter.get("min_should")
            if minimum and sum(
                _matches(payload, item) for item in minimum["conditions"]
            ) < minimum["min_count"]:
                continue
            numerator = sum(a * b for a, b in zip(query, point["vector"]))
            denominator = math.sqrt(sum(a * a for a in query)) * math.sqrt(
                sum(b * b for b in point["vector"])
            )
            rows.append({
                "id": point["id"],
                "score": numerator / denominator if denominator else 0.0,
                "payload": dict(payload),
            })
        rows.sort(key=lambda row: (-row["score"], str(row["id"])))
        return {"points": rows[:limit]}


class _ProductionShapedPostgres(PostgresTriMemStore):
    """Protocol-accurate async repository fake; no InMemory product fallback."""

    def __init__(self, namespace, events):
        super().__init__(object(), namespace=namespace)
        self.events = events
        self.graphs = {}
        self.nodes = {}
        self.edges = {}
        self.outbox = {}
        self.access_events = []
        self.supports = []
        self.strengths = {}
        self.promotion_evidence = {}
        self.last_reload = None

    async def append_lifecycle_bundle(self, ctx, bundle):
        self.events.append("postgres_commit")
        for graph in bundle.graphs:
            assert graph.verify_hash() and graph.namespace == self.namespace
            self.graphs[graph.graph_id] = graph
        for node in bundle.nodes:
            assert node.verify_hash() and node.namespace == self.namespace
            self.nodes[node.node_id] = node
        for edge in bundle.edges:
            assert edge.verify_hash() and edge.namespace == self.namespace
            self.edges[edge.edge_id] = edge
        self.supports.extend(bundle.supports)
        for strength in bundle.strengths:
            assert strength.verify_hash() and strength.namespace == self.namespace
            self.strengths[strength.semantic_node_id] = strength
        index_nodes = tuple(self.nodes[node_id] for node_id in bundle.index_node_ids)
        intents = []
        for ordinal, node in enumerate(index_nodes):
            intent = IndexOutboxIntent(
                intent_id="intent-%04d" % (len(self.outbox) + ordinal),
                org_id=node.org_id,
                namespace=node.namespace,
                graph_id=node.graph_id,
                graph_kind=node.graph_kind,
                owner_user_id=node.owner_user_id,
                node_id=node.node_id,
                operation="UPSERT",
                canonical_content_hash=node.content_hash,
                prior_content_hash=None,
                status="PENDING",
                attempts=0,
                last_error=None,
                created_at=NOW,
                updated_at=NOW,
                indexed_at=None,
            )
            self.outbox[intent.intent_id] = intent
            intents.append(intent)
        return AppendReceipt(
            namespace=self.namespace,
            graph_hashes=tuple((item.graph_id, item.content_hash) for item in bundle.graphs),
            node_hashes=tuple((item.node_id, item.content_hash) for item in bundle.nodes),
            index_nodes=index_nodes,
            strength_hashes=tuple(
                (item.strength_id, item.content_hash) for item in bundle.strengths
            ),
            index_intents=tuple(intents),
        )

    async def resolve_task_identity(self, ctx, *, repository_slug, task_id):
        return {
            "repository_id": REPOSITORY_ID,
            "solve_job_id": SOLVE_JOB_ID,
            "repository_slug": repository_slug,
            "task_id": task_id,
        }

    async def get_node(self, ctx, node_id):
        node = self.nodes[node_id]
        assert node.org_id == ctx.org_id
        assert node.owner_user_id is None or node.owner_user_id == ctx.user_id
        return node

    async def verify_promotion_evidence(self, ctx, evidence_hashes):
        return tuple(self.promotion_evidence[item] for item in evidence_hashes)

    async def mark_index_outbox_indexed(self, ctx, *, intent_id, canonical_content_hash):
        intent = self.outbox[intent_id]
        assert intent.canonical_content_hash == canonical_content_hash
        intent = replace(intent, status="INDEXED", indexed_at=NOW, updated_at=NOW)
        self.outbox[intent_id] = intent
        return intent

    async def mark_index_outbox_failed(self, ctx, *, intent_id, canonical_content_hash, error_code):
        intent = self.outbox[intent_id]
        intent = replace(intent, attempts=intent.attempts + 1, last_error=error_code)
        self.outbox[intent_id] = intent
        return intent

    async def append_access_batch(
        self, ctx, events, *, operation_id=None, operation_scope=None
    ):
        assert operation_id and operation_scope["kind"] == "ACCESS"
        self.events.append("postgres_access_commit")
        self.access_events.extend(events)
        return tuple(events)

    async def load_policy_feature_rows(self, ctx, *, limit):
        body = {
            "schema": "trimem/canonical-policy-feature-rows/1.0",
            "namespace": self.namespace,
            "history_limit": limit,
            "rows": [],
        }
        return {**body, "digest": canonical_hash(body)}

    async def load_retrieval_rows(self, ctx, *, kind, repository_id, references=None):
        shortlisted = references is not None
        refs = tuple(references or ())
        candidate_ids = tuple(item.node_id for item in refs)
        for ref in refs:
            assert ref.namespace == self.namespace and ref.org_id == ctx.org_id
            assert ref.memory_kind == kind
            assert ref.repository_id in {repository_id, None}
            assert self.nodes[ref.node_id].content_hash == ref.content_hash
        if shortlisted:
            graph_ids = sorted({self.nodes[node_id].graph_id for node_id in candidate_ids})
        else:
            graph_ids = sorted(
                item.graph_id
                for item in self.graphs.values()
                if item.kind == kind
                and item.org_id == ctx.org_id
                and (item.owner_user_id is None or item.owner_user_id == ctx.user_id)
                and item.repository_id in {repository_id, None}
            )
        graphs = tuple(self.graphs[item] for item in graph_ids)
        nodes = tuple(sorted(
            (item for item in self.nodes.values() if item.graph_id in graph_ids),
            key=lambda item: item.node_id,
        ))
        edges = tuple(sorted(
            (item for item in self.edges.values() if item.graph_id in graph_ids),
            key=lambda item: item.edge_id,
        ))
        if not shortlisted:
            memory_type = (
                NodeType.EPISODE
                if kind == GraphKind.USER_EPISODIC else NodeType.SEMANTIC_RULE
            )
            candidate_ids = tuple(
                item.node_id for item in nodes if item.node_type == memory_type
            )
        rows = CanonicalReloadRows(
            namespace=self.namespace,
            graph_kind=kind,
            graphs=graphs,
            nodes=nodes,
            edges=edges,
            candidate_node_ids=candidate_ids,
            digest=canonical_hash({
                "kind": kind.value,
                "graphs": [(item.graph_id, item.content_hash) for item in graphs],
                "nodes": [(item.node_id, item.content_hash) for item in nodes],
                "edges": [(item.edge_id, item.content_hash) for item in edges],
                "candidates": candidate_ids,
            }),
        )
        self.last_reload = rows
        self.events.append("postgres_canonical_reload")
        return rows


def _task(task_id, repository):
    return CodingTask(
        task_id=task_id,
        org_id="org-a",
        user_id="alice",
        repository=repository,
        commit="commit-" + task_id,
        instruction="Normalize uppercase file suffixes while rejecting unknown formats.",
        files={"src/loader.py": "pass\n"},
        editable_paths=("src/loader.py",),
    )


def _graph(task):
    graph = ShortTermWorkingGraph(task.task_id, task.instruction, task.repository)
    graph.add_subtask(SubtaskSpec(
        node_id="normalize-suffix",
        objective="normalize suffix before allowlist validation",
        operation="casefold suffix before comparison",
        preconditions=("allowlist is case insensitive",),
        invariants=("unknown formats remain rejected",),
        tests=("uppercase suffix", "unknown suffix"),
    ))
    graph.activate("normalize-suffix")
    return graph


def test_source_to_cross_repository_target_is_durable_ref_only_ppr_and_audited():
    events = []
    store = _ProductionShapedPostgres(NAMESPACE, events)
    client = _Qdrant(events)
    encoder = _ProductionEncoder()
    index = QdrantVectorIndexV2(client, 384, namespace=NAMESPACE)
    bridge = DedicatedAsyncLoop(name="trimem-production-shaped-e2e")
    persistence = CanonicalLifecyclePersistence(
        store, index, encoder, bridge, namespace=NAMESPACE
    )
    try:
        factory = production_dqn_lifecycle_factory(
            lambda task: {"repository_id": REPOSITORY_ID, "solve_job_id": SOLVE_JOB_ID},
            policy_manifest=MANIFEST,
            expected_policy_manifest_hash=MANIFEST_HASH,
        )
        lifecycle = factory(
            policy=None,
            persistence=persistence,
            namespace=NAMESPACE,
            split="credential_free_replay",
            evaluation=False,
            embedder=encoder,
        )
        lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
            MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
            (0.0, 0.0, 1.0),
            mask.as_tuple(),
            0.0,
            evaluation,
        )
        source = _task("source", "source/repository")
        extraction = ExperienceExtraction(
            episode={"summary": "Suffix handling was repaired.", "action": "casefold suffix"},
            semantic_candidate={
                "applicability_scope": "CROSS_REPOSITORY",
                "preconditions": "An extension allowlist is case insensitive.",
                "operation": "Normalize the suffix before allowlist comparison.",
                "invariant": "Unknown formats remain rejected.",
                "non_applicability": "Do not alter case-sensitive protocols.",
                "verification": "Test an uppercase allowed suffix and unknown suffix.",
            },
            response_hash="a" * 64,
            patch_hash="b" * 64,
            public_evidence_hash="c" * 64,
        )
        grade = GradeResult(
            task_id=source.task_id,
            resolved=True,
            exit_code=0,
            stdout="ok",
            stderr="",
            report={"public": "pass"},
            grader_id="credential-free",
            container_digest="fixture",
            official=False,
            wall_time_ms=1,
        )
        stored = lifecycle.store_experience(source, _graph(source), extraction, grade, ())
        assert stored["memory_id"]
        assert events[:2] == ["postgres_commit", "qdrant_upsert"]
        assert all(intent.status == "INDEXED" for intent in store.outbox.values())

        indexed_points = [
            point
            for collection in client.collections.values()
            for point in collection["points"].values()
        ]
        assert len(indexed_points) == 1
        assert set(indexed_points[0]["payload"]) == {
            "index_schema_version", "collection_scope", "memory_kind", "org_id",
            "owner_user_id", "repository_id", "graph_id", "node_id", "content_hash",
        }
        assert indexed_points[0]["payload"]["repository_id"] is None
        assert not ({"canonical_payload", "execution_view", "retrieval_text"}
                    & set(indexed_points[0]["payload"]))

        target = _task("target", "different/repository")
        async_store = AsyncPostgresQdrantRetrievalStore(
            store, index, encoder, excluded_source_task_id=target.task_id
        )
        sync_store = SyncPostgresQdrantRetrievalStore(async_store, bridge)
        auditor = PostgresInjectionAuditor(
            persistence,
            ctx=AccessContext(target.org_id, target.user_id),
            namespace=NAMESPACE,
            task_id=target.task_id,
            clock=lambda: NOW,
        )
        retriever = TriMemoryRetriever(
            sync_store,
            RetrievalConfig(
                min_confidence=0.0,
                min_margin=0.0,
                embedding_dimensions=384,
                ppr_iterations=16,
            ),
            embedder=encoder,
            injection_auditor=auditor,
        )
        controller = ActiveNodeTriMemController(retriever, task_id=target.task_id)
        decision = controller.recall(_graph(target), target)
        assert len(decision.injections) == 1
        injection = decision.injections[0]
        assert injection.memory_id == stored["memory_id"]
        assert injection.namespace == NAMESPACE and injection.canonical_node_hash
        assert store.last_reload is not None
        assert len(store.last_reload.nodes) > 8 and len(store.last_reload.edges) > 8
        assert len(store.access_events) == 1
        assert store.access_events[0].node_id == injection.memory_id
        assert events.index("qdrant_search") < events.index("postgres_canonical_reload")
        assert events.index("postgres_canonical_reload") < events.index("postgres_access_commit")
    finally:
        bridge.close()


def test_m1_online_v03_retention_is_not_the_m0_no_memory_path():
    events = []
    store = _ProductionShapedPostgres(
        "trimem:production-shaped:credential_free_replay:M1", events
    )
    client = _Qdrant(events)
    encoder = _ProductionEncoder()
    index = QdrantVectorIndexV2(client, 384, namespace=store.namespace)
    bridge = DedicatedAsyncLoop(name="trimem-v03-production-shaped-e2e")
    persistence = CanonicalLifecyclePersistence(
        store, index, encoder, bridge, namespace=store.namespace
    )

    class _LiveRuntimeFixture(LiveV03Runtime):
        implementation_hash = LIVE_V03_IMPLEMENTATION_HASH

        def __init__(self):
            self.namespace = store.namespace
            self.rows = {}
            self.audit_digest = canonical_hash({"audit": "m1-live"})

        def retention_descriptor(self, *, task, identity, injections, event_time):
            body = {
                "schema": "trimem/live-v03-retention-descriptor/1.0",
                "namespace": self.namespace,
                "org_id": task.org_id,
                "user_id": task.user_id,
                "episode_id": "33333333-3333-4333-8333-333333333333",
                "solve_job_id": identity["solve_job_id"],
                "repository_id": identity["repository_id"],
                "task_id": task.task_id,
                "source_commit": getattr(task, "commit", "fixture-commit"),
                "content_hash": "sha256:" + "a" * 32,
                "canonical": {
                    "task_id": task.task_id,
                    "repo_id": identity["repository_id"],
                    "commit": getattr(task, "commit", "fixture-commit"),
                    "outcome": "success",
                    "injected_memory_ids": [row["memory_id"] for row in injections],
                },
                "event_time": event_time,
                "collection_name": "fixture-private",
                "point_id": "fixture-point",
                "point_digest": canonical_hash({"point": "fixture"}),
            }
            return {**body, "digest": canonical_hash(body)}

        def retain_episode(self, descriptor):
            self.rows[descriptor["episode_id"]] = dict(descriptor)
            body = {
                "schema": "trimem/live-v03-retention-evidence/1.0",
                "namespace": store.namespace,
                "episode_id": descriptor["episode_id"],
            }
            return {**body, "digest": canonical_hash(body)}

        def verify_pending_retention(self, descriptor):
            observed = self.rows.get(descriptor["episode_id"])
            if observed is not None and observed != dict(descriptor):
                raise AssertionError("pending retention mismatch")
            return "EXACT_PENDING_APPEND" if observed else "ABSENT"

        def recall_plan(self, **kwargs):
            from types import SimpleNamespace

            candidate = SimpleNamespace(
                scope="private",
                canonical_id="33333333-3333-4333-8333-333333333333",
                canonical_version_id="33333333-3333-4333-8333-333333333333",
                content_hash="sha256:" + "a" * 32,
                canonical_owner_id=kwargs["task"].user_id,
                index_owner_id=kwargs["task"].user_id,
                accepted=True,
                rejection_reason=None,
                injected=True,
                injected_position=0,
                injected_view_hash="b" * 64,
                view_text=(
                    "Your prior verified note: casefold suffix values before "
                    "comparing the allowlist"
                ),
                score=0.91,
            )
            plan = SimpleNamespace(candidates=[candidate], memory_views=[candidate.view_text])
            return {
                "plan": plan,
                "audit": {"digest": self.audit_digest},
                "private_hits": 1,
                "shared_hits": 0,
                "rejected_candidates": 0,
            }

        def verify_audit(self, **kwargs):
            assert kwargs["evidence"]["digest"] == self.audit_digest

        def verify_audit_digest(self, **kwargs):
            assert kwargs["expected_digest"] == self.audit_digest

        def state_evidence(self, *, org_id, user_id, episode_ids=()):
            body = {
                "schema": "trimem/live-v03-canonical-state/1.0",
                "namespace": store.namespace,
                "org_id": org_id,
                "user_id": user_id,
                "stream_episode_ids": list(sorted(episode_ids)),
                "rows": [
                    {"episode_id": item, "digest": self.rows[item]["digest"]}
                    for item in sorted(self.rows)
                ],
            }
            return {**body, "digest": canonical_hash(body)}

        def verify_state(self, evidence, *, pending_descriptor=None):
            return "ABSENT" if pending_descriptor is not None else "EXACT_STATE"

    runtime = _LiveRuntimeFixture()
    try:
        lifecycle = PostgresV03ExperienceLifecycle(
            runtime,
            namespace=store.namespace,
            identity_resolver=lambda task: {
                "repository_id": REPOSITORY_ID,
                "solve_job_id": SOLVE_JOB_ID,
            },
            clock=lambda: NOW,
        )
        source = _task("m1-source", "same/repository")
        lifecycle.before_task(task=source, sequence_index=0)
        extraction = ExperienceExtraction(
            episode={"summary": "Suffix handling was repaired.", "action": "casefold suffix"},
            semantic_candidate=None,
            response_hash="d" * 64,
            patch_hash="e" * 64,
            public_evidence_hash="f" * 64,
        )
        grade = GradeResult(
            task_id=source.task_id,
            resolved=True,
            exit_code=0,
            stdout="ok",
            stderr="",
            report={"public": "pass"},
            grader_id="credential-free",
            container_digest="fixture",
            official=False,
            wall_time_ms=1,
        )
        lifecycle.store_experience(source, _graph(source), extraction, grade, ())

        target = _task("m1-target", "same/repository")
        m1 = production_v03_controller_factory(
            task=target,
            canonical_store=store,
            persistence=persistence,
            namespace=store.namespace,
            lifecycle=lifecycle,
            identity_resolver=lifecycle.identity_resolver,
        )
        graph = _graph(target)
        m1_result = m1.recall(graph, target)
        m0_result = NoMemoryController().recall(graph, target)
        assert len(m1_result.injections) == 1
        assert m1_result.injections[0].kind.value == "EPISODIC"
        assert m0_result.injections == ()
        assert m1.implementation_manifest["search_path"].endswith(
            "validated_search.validated_search"
        )
    finally:
        bridge.close()


def test_reviewed_multi_user_promotion_commits_shared_graph_before_shared_index(monkeypatch):
    events = []
    store = _ProductionShapedPostgres(NAMESPACE, events)
    client = _Qdrant(events)
    encoder = _ProductionEncoder()
    index = QdrantVectorIndexV2(client, 384, namespace=NAMESPACE)
    bridge = DedicatedAsyncLoop(name="trimem-reviewed-promotion-e2e")
    persistence = CanonicalLifecyclePersistence(
        store, index, encoder, bridge, namespace=NAMESPACE
    )
    try:
        lifecycle = production_dqn_lifecycle_factory(
            lambda task: {"repository_id": REPOSITORY_ID, "solve_job_id": SOLVE_JOB_ID},
            policy_manifest=MANIFEST,
            expected_policy_manifest_hash=MANIFEST_HASH,
        )(
            policy=None,
            persistence=persistence,
            namespace=NAMESPACE,
            split="credential_free_replay",
            evaluation=False,
            embedder=encoder,
        )
        lifecycle.policy.decide = lambda state, mask, evaluation=False: PolicyDecision(
            MemoryAction.MOVE_TO_SEMANTIC_CANDIDATE,
            (0.0, 0.0, 1.0),
            mask.as_tuple(),
            0.0,
            evaluation,
        )
        task = _task("promotion-source", "source/repository")
        extraction = ExperienceExtraction(
            episode={"summary": "Suffix handling was repaired.", "action": "casefold suffix"},
            semantic_candidate={
                "applicability_scope": "CROSS_REPOSITORY",
                "preconditions": "An extension allowlist is case insensitive.",
                "operation": "Normalize the suffix before allowlist comparison.",
                "invariant": "Unknown formats remain rejected.",
                "non_applicability": "Do not alter case-sensitive protocols.",
                "verification": "Test uppercase allowed and unknown suffixes.",
            },
            response_hash="1" * 64,
            patch_hash="2" * 64,
            public_evidence_hash="3" * 64,
        )
        grade = GradeResult(
            task_id=task.task_id,
            resolved=True,
            exit_code=0,
            stdout="ok",
            stderr="",
            report={"public": "pass"},
            grader_id="credential-free",
            container_digest="fixture",
            official=False,
            wall_time_ms=1,
        )
        stored = lifecycle.store_experience(task, _graph(task), extraction, grade, ())

        evidence = tuple(
            PromotionEvidence(
                evidence_id="evidence-%d" % ordinal,
                org_id=task.org_id,
                namespace=NAMESPACE,
                evidence_hash="sha256:" + character * 64,
                contributor_hash="sha256:" + contributor * 64,
                source_kind="VERIFIED_EPISODE",
                source_outcome="passed",
                verified=True,
                public_evidence_hash="sha256:" + str(ordinal + 4) * 64,
                verifier_hash="sha256:" + str(ordinal + 6) * 64,
                extraction_hash="sha256:" + str(ordinal + 8) * 64,
                attestation_hash="sha256:" + attestation * 64,
                verified_at=NOW,
                created_at=NOW,
            )
            for ordinal, (character, contributor, attestation) in enumerate(
                (("a", "b", "c"), ("d", "e", "f"))
            )
        )
        store.promotion_evidence = {item.evidence_hash: item for item in evidence}
        review = ReviewProvenance(
            review_id="review-1",
            reviewer_id="human-reviewer",
            reviewed_at=NOW,
            authority=ReviewAuthority.HUMAN_REVIEW,
            policy_version="trimem-org-promotion-v1",
            evidence_hash=promotion_review_evidence_hash(evidence),
        )
        service = PostgresReviewedPromotionService(
            store, persistence, namespace=NAMESPACE, clock=lambda: NOW
        )
        before = len(events)
        promoted = service.promote(
            AccessContext(task.org_id, task.user_id),
            source_semantic_node_id=stored["memory_id"],
            review=review,
            evidence_hashes=tuple(item.evidence_hash for item in evidence),
        )
        assert promoted["authority"] == "HUMAN_REVIEW"
        assert promoted["dqn_authority"] is False
        assert events[before:before + 2] == ["postgres_commit", "qdrant_upsert"]
        shared = store.nodes[promoted["node_id"]]
        assert shared.graph_kind == GraphKind.ORGANISATION_SEMANTIC
        assert shared.owner_user_id is None and shared.review_provenance == review
        assert "source_episode_id" not in json.dumps(shared.canonical_payload)
        org_edges = [
            item.edge_type for item in store.edges.values()
            if item.graph_id == promoted["graph_id"]
        ]
        assert EdgeType.PROMOTED_TO in org_edges
        assert EdgeType.DERIVED_FROM in org_edges
        assert org_edges.count(EdgeType.SUPPORTED_BY) == 2
        org_supports = [
            item for item in store.supports
            if item.semantic_graph_id == promoted["graph_id"]
        ]
        assert len(org_supports) == 2
        assert all(item.source_episode_id is None for item in org_supports)
        shared_strength = store.strengths[promoted["node_id"]].strength
        assert shared_strength.support == 2.0
        assert shared_strength.independent_user_evidence == 2.0
        assert shared_strength.recent_verification == 1.0
        shared_points = client.collections[index.shared_collection]["points"]
        assert len(shared_points) == 1
        assert all(
            "execution_view" not in point["payload"]
            for point in shared_points.values()
        )

        trusted_document_hash = "sha256:" + "9" * 64
        trusted_review = ReviewProvenance(
            review_id="review-trusted-document",
            reviewer_id="trusted-document-curator",
            reviewed_at=NOW,
            authority=ReviewAuthority.TRUSTED_DOCUMENT,
            policy_version="trimem-org-promotion-v1",
            evidence_hash=trusted_document_hash,
        )
        before = len(events)
        trusted = service.promote(
            AccessContext(task.org_id, task.user_id),
            source_semantic_node_id=stored["memory_id"],
            review=trusted_review,
            trusted_document_hash=trusted_document_hash,
        )
        assert trusted["authority"] == "TRUSTED_DOCUMENT"
        assert trusted["dqn_authority"] is False
        assert events[before:before + 2] == ["postgres_commit", "qdrant_upsert"]
        trusted_supports = [
            item for item in store.supports
            if item.semantic_graph_id == trusted["graph_id"]
        ]
        assert len(trusted_supports) == 1
        assert trusted_supports[0].source_episode_id is None
        trusted_strength = store.strengths[trusted["node_id"]].strength
        assert trusted_strength.support == 1.0
        assert trusted_strength.independent_user_evidence == 0.0

        # Publication re-runs the shared deterministic scanner even when a
        # canonical private record and an authorised review already exist.
        monkeypatch.setattr(
            "enterprise_memory.trimem.production_promotion.promotion_security.scan",
            lambda text: {
                "result": "BLOCK_SECRET",
                "findings": (("BLOCK_SECRET", "credential"),),
                "blocking": True,
            },
        )
        before_events = tuple(events)
        before_graphs = len(store.graphs)
        with pytest.raises(PromotionError, match="deterministic security scan"):
            service.promote(
                AccessContext(task.org_id, task.user_id),
                source_semantic_node_id=stored["memory_id"],
                review=trusted_review,
                trusted_document_hash=trusted_document_hash,
            )
        assert tuple(events) == before_events
        assert len(store.graphs) == before_graphs
    finally:
        bridge.close()
