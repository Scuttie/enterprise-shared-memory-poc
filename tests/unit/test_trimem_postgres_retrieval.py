"""Credential-free production retrieval and access-audit boundary tests."""
import asyncio

import pytest

from enterprise_memory.trimem.ppr import DeterministicHashEmbedder
from enterprise_memory.trimem.postgres_retrieval import (
    AsyncPostgresQdrantRetrievalStore,
    PostgresInjectionAuditor,
    project_canonical_rows,
)
from enterprise_memory.trimem.postgres_store import CanonicalReloadRows, PostgresTriMemStore
from enterprise_memory.trimem.retrieval import (
    InMemoryMemoryGraphStore,
    MemoryGraphSnapshot,
    MemoryKind,
    MemoryRecord,
    RetrievalConfig,
    RetrievalSessionState,
    TriMemoryRetriever,
)
from enterprise_memory.trimem.schema import (
    AccessContext,
    GraphKind,
    GraphNode,
    NodeType,
    TemporalMetadata,
    UserEpisodicGraph,
    canonical_hash,
)
from enterprise_memory.trimem.vector_index import (
    QdrantVectorIndexV2,
    VectorHit,
    VectorReference,
    VectorSearchResult,
)
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


NOW = "2026-08-31T00:00:00Z"
NAMESPACE = "trimem:exp:dev:M2"


def _rows(source_task_id="source-task"):
    temporal = TemporalMetadata(ingested_at=NOW, event_time=NOW, source_available_at=NOW)
    graph = UserEpisodicGraph(
        graph_id="00000000-0000-4000-8000-000000000010",
        org_id="org-a",
        namespace=NAMESPACE,
        owner_user_id="alice",
        repository_id="repo-a",
        temporal=temporal,
    )
    node = GraphNode(
        node_id="00000000-0000-4000-8000-000000000011",
        graph_id=graph.graph_id,
        org_id=graph.org_id,
        namespace=NAMESPACE,
        graph_kind=graph.kind,
        owner_user_id=graph.owner_user_id,
        repository_id=graph.repository_id,
        node_type=NodeType.EPISODE,
        canonical_payload={
            "retrieval_text": "locate reflected operator and preserve operand order",
            "execution_view": "Apply the reflected-order patch and run the focused test.",
            "version": "v1",
            "version_valid": True,
            "stale": False,
            "servable": True,
            "verified": True,
            "source_outcome": "passed",
            "quality": 1.0,
            "completeness": 1.0,
            "coverage": ["operation", "verification"],
            "provenance": {"source_task_id": source_task_id},
        },
        temporal=temporal,
    )
    digest = canonical_hash({"graph": graph.content_hash, "node": node.content_hash})
    return graph, node, CanonicalReloadRows(
        namespace=NAMESPACE,
        graph_kind=GraphKind.USER_EPISODIC,
        graphs=(graph,),
        nodes=(node,),
        edges=(),
        candidate_node_ids=(node.node_id,),
        digest=digest,
    )


def test_projector_accepts_only_shortlisted_canonical_nodes_and_excludes_self_memory():
    graph, node, rows = _rows()
    snapshot = project_canonical_rows(
        rows, MemoryKind.EPISODIC, user_id="alice", org_id="org-a", repository="repo-a"
    )
    assert tuple(snapshot.records) == (node.node_id,)
    record = snapshot.records[node.node_id]
    assert record.metadata["namespace"] == NAMESPACE
    assert record.metadata["canonical_node_hash"] == node.content_hash
    assert record.metadata["graph_id"] == graph.graph_id

    excluded = project_canonical_rows(
        rows, MemoryKind.EPISODIC, user_id="alice", org_id="org-a",
        repository="repo-a", excluded_source_task_id="source-task",
    )
    assert excluded.records == {}


class _StubPostgres(PostgresTriMemStore):
    def __init__(self, rows, order):
        self.namespace = rows.namespace
        self.rows = rows
        self.order = order

    async def load_retrieval_rows(self, ctx, **kwargs):
        self.order.append("postgres_reload")
        assert kwargs["references"][0].content_hash == self.rows.nodes[0].content_hash
        return self.rows


class _StubIndex(QdrantVectorIndexV2):
    def __init__(self, reference, order):
        self.namespace = reference.namespace
        self.dimension = 8
        self.reference = reference
        self.order = order

    def search(self, vector, **kwargs):
        self.order.append("qdrant_search")
        return VectorSearchResult((VectorHit(self.reference.point_id, 0.9, self.reference),), ())


def test_qdrant_shortlist_precedes_postgres_canonical_reload():
    graph, node, rows = _rows()
    order = []
    reference = VectorReference(
        graph_id=graph.graph_id, node_id=node.node_id, content_hash=node.content_hash,
        org_id=graph.org_id, namespace=NAMESPACE, memory_kind=graph.kind,
        owner_user_id=graph.owner_user_id, repository_id=graph.repository_id,
    )
    store = AsyncPostgresQdrantRetrievalStore(
        _StubPostgres(rows, order), _StubIndex(reference, order),
        DeterministicHashEmbedder(8),
    )
    snapshot = asyncio.run(store.snapshot_for_query(
        MemoryKind.EPISODIC, user_id="alice", org_id="org-a",
        repository="repo-a", query_text="reflected operator",
    ))
    assert order == ["qdrant_search", "postgres_reload"]
    assert tuple(snapshot.records) == (node.node_id,)


def _working_graph():
    graph = ShortTermWorkingGraph("target-task", "fix reflected operator", "repo-a")
    node = graph.add_subtask(SubtaskSpec(
        node_id="active", objective="locate reflected operator and preserve operand order",
        operation="LOCATE_SYMBOL", symbols=("Array.__radd__",),
    ))
    graph.activate(node.node_id)
    return graph


class _Persistence:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.events = ()

    def persist_access_events(self, ctx, events, *, operation_id, operation_scope):
        assert operation_id and operation_scope["kind"] == "ACCESS"
        if self.fail:
            raise RuntimeError("audit unavailable")
        self.events = tuple(events)
        return self.events


def _retrieval_store(graph, node):
    record = MemoryRecord(
        memory_id=node.node_id,
        kind=MemoryKind.EPISODIC,
        retrieval_text="locate reflected operator and preserve operand order",
        execution_view="Apply exact patch bytes.",
        org_id="org-a",
        owner_user_id="alice",
        repository="repo-a",
        coverage=("operation", "verification"),
        metadata={
            "namespace": NAMESPACE,
            "graph_id": graph.graph_id,
            "canonical_node_hash": node.content_hash,
        },
    )
    return InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: MemoryGraphSnapshot(
            MemoryKind.EPISODIC, {record.memory_id: record}, graph_hash="canonical-snapshot"
        )
    })


def test_access_audit_commits_before_retrieval_session_mutation():
    canonical_graph, canonical_node, _ = _rows()
    working = _working_graph()
    ctx = AccessContext("org-a", "alice")
    failed_persistence = _Persistence(fail=True)
    failed_auditor = PostgresInjectionAuditor(
        failed_persistence, ctx=ctx, namespace=NAMESPACE, task_id=working.task_id,
        clock=lambda: NOW,
    )
    session = RetrievalSessionState(working.task_id)
    retriever = TriMemoryRetriever(
        _retrieval_store(canonical_graph, canonical_node),
        RetrievalConfig(min_confidence=0.0),
        injection_auditor=failed_auditor,
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        retriever.recall(
            working, session, user_id="alice", org_id="org-a", repository="repo-a"
        )
    assert session.ledger == []
    assert session.total_injections == 0

    persistence = _Persistence()
    retriever.injection_auditor = PostgresInjectionAuditor(
        persistence, ctx=ctx, namespace=NAMESPACE, task_id=working.task_id,
        clock=lambda: NOW,
    )
    decision = retriever.recall(
        working, session, user_id="alice", org_id="org-a", repository="repo-a"
    )
    assert len(decision.injections) == len(persistence.events) == 1
    assert session.ledger == list(decision.injections)
    event = persistence.events[0]
    assert event.node_id == canonical_node.node_id
    assert event.graph_id == canonical_graph.graph_id
    assert event.injected_byte_count == decision.injections[0].byte_count
    assert event.injected_hash.startswith("sha256:")
