"""Canonical graph-store to active-node retrieval projection checks."""
import pytest

from enterprise_memory.trimem.retrieval import (
    MemoryKind,
    RetrievalSessionState,
    TriMemoryRetriever,
)
from enterprise_memory.trimem.retrieval_store import CanonicalRetrievalStore
from enterprise_memory.trimem.schema import (
    AccessContext,
    EdgeType,
    GraphEdge,
    GraphNode,
    NodeType,
    OrganisationSemanticGraph,
    ReviewAuthority,
    ReviewProvenance,
    TemporalMetadata,
    UserEpisodicGraph,
    UserSemanticGraph,
)
from enterprise_memory.trimem.store import InMemoryTriMemStore
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


NOW = "2026-08-31T00:00:00Z"


def _temporal(*, valid_from=None, valid_until=None):
    return TemporalMetadata(
        ingested_at=NOW,
        event_time="2026-08-30T00:00:00Z",
        source_available_at="2026-08-30T01:00:00Z",
        last_verified_at=NOW,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _review(review_id="review-1"):
    return ReviewProvenance(
        review_id=review_id,
        reviewer_id="reviewer",
        reviewed_at=NOW,
        authority=ReviewAuthority.HUMAN_REVIEW,
        policy_version="shared-v1",
        evidence_hash="sha256:" + "a" * 64,
    )


def _payload(text="Array __radd__ reflected addition", **updates):
    value = {
        "retrieval_text": text,
        "execution_view": "검증된 메모리: reflected operand 순서를 보존한다.",
        "version": "commit-abc",
        "version_valid": True,
        "stale": False,
        "servable": True,
        "verified": True,
        "source_outcome": "passed",
        "quality": 0.9,
        "completeness": 0.75,
        "coverage": ["operation", "verification"],
        "provenance": {"task_id": "source-1", "result_hash": "sha256:result"},
    }
    value.update(updates)
    return value


def _node(graph, node_id, node_type, payload, *, review=None, repository="acme/math"):
    return GraphNode(
        node_id=node_id,
        graph_id=graph.graph_id,
        org_id=graph.org_id,
        graph_kind=graph.kind,
        node_type=node_type,
        temporal=_temporal(valid_from="2026-01-01T00:00:00Z"),
        canonical_payload=payload,
        owner_user_id=graph.owner_user_id,
        repository_id=repository,
        review_provenance=review,
    )


def test_private_episode_projection_is_hash_bound_and_builds_edge_adjacency():
    store = InMemoryTriMemStore()
    context = AccessContext("org-1", "alice")
    graph = UserEpisodicGraph(
        graph_id="episodes-alice",
        org_id=context.org_id,
        owner_user_id=context.user_id,
        repository_id="acme/math",
        temporal=_temporal(),
    )
    episode = _node(graph, "episode-1", NodeType.EPISODE, _payload())
    symbol = _node(
        graph,
        "symbol-1",
        NodeType.SYMBOL,
        {"symbol": "Array.__radd__", "path": "src/array.py"},
    )
    edge = GraphEdge(
        edge_id="episode-symbol",
        graph_id=graph.graph_id,
        org_id=graph.org_id,
        graph_kind=graph.kind,
        edge_type=EdgeType.TOUCHES,
        source_node_id=episode.node_id,
        target_node_id=symbol.node_id,
        temporal=_temporal(),
        owner_user_id=graph.owner_user_id,
        metadata={"weight": 2.5},
    )
    store.put_graph(context, graph)
    store.put_node(context, symbol)
    store.put_node(context, episode)
    store.put_edge(context, edge)

    adapter = CanonicalRetrievalStore(store)
    first = adapter.snapshot(
        MemoryKind.EPISODIC,
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )
    second = adapter.snapshot(
        MemoryKind.EPISODIC,
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert first == second
    assert first.graph_hash.startswith("sha256:")
    assert list(first.records) == ["episode-1"]
    assert list(first.nodes) == ["episode-1", "symbol-1"]
    assert first.adjacency == {"episode-1": {"symbol-1": 2.5}, "symbol-1": {}}
    record = first.records["episode-1"]
    assert record.repository == "acme/math" and record.version == "commit-abc"
    assert record.valid_from == "2026-01-01T00:00:00Z"
    assert record.metadata["canonical_node_hash"] == episode.content_hash
    assert record.metadata["canonical_payload_hash"] == episode.payload_hash
    assert record.metadata["canonical_graph_hash"] == graph.content_hash
    assert record.metadata["provenance"]["result_hash"] == "sha256:result"


def test_private_owner_org_and_repository_queries_are_non_disclosing():
    store = InMemoryTriMemStore()
    alice = AccessContext("org-1", "alice")
    graph = UserSemanticGraph(
        graph_id="alice-rules",
        org_id=alice.org_id,
        owner_user_id=alice.user_id,
        repository_id="acme/math",
        temporal=_temporal(),
    )
    store.put_graph(alice, graph)
    store.put_node(alice, _node(graph, "rule-1", NodeType.SEMANTIC_RULE, _payload()))
    adapter = CanonicalRetrievalStore(store)

    assert adapter.snapshot(
        MemoryKind.USER_SEMANTIC, user_id="bob", org_id="org-1", repository="acme/math"
    ).records == {}
    assert adapter.snapshot(
        MemoryKind.USER_SEMANTIC, user_id="alice", org_id="org-2", repository="acme/math"
    ).records == {}
    assert adapter.snapshot(
        MemoryKind.USER_SEMANTIC, user_id="alice", org_id="org-1", repository="other/repo"
    ).records == {}


def test_reviewed_org_semantic_projects_without_private_owner_and_cross_org_is_zero():
    store = InMemoryTriMemStore()
    publisher = AccessContext("org-1", "alice")
    review = _review()
    graph = OrganisationSemanticGraph(
        graph_id="org-rules",
        org_id="org-1",
        repository_id="acme/math",
        temporal=_temporal(),
        review_provenance=review,
    )
    rule = _node(
        graph,
        "org-rule-1",
        NodeType.SEMANTIC_RULE,
        _payload(completeness=1.0),
        review=review,
    )
    store.put_graph(publisher, graph)
    store.put_node(publisher, rule)
    adapter = CanonicalRetrievalStore(store)

    same_org = adapter.snapshot(
        MemoryKind.ORG_SEMANTIC, user_id="bob", org_id="org-1", repository="acme/math"
    )
    assert list(same_org.records) == ["org-rule-1"]
    record = same_org.records["org-rule-1"]
    assert record.owner_user_id is None and record.reviewed and record.verified
    assert record.metadata["graph_review_provenance_hash"] == review.content_hash
    assert record.metadata["node_review_provenance_hash"] == review.content_hash
    assert adapter.snapshot(
        MemoryKind.ORG_SEMANTIC, user_id="mallory", org_id="org-2", repository="acme/math"
    ).records == {}


def test_version_temporal_and_verification_flags_are_projected_fail_closed():
    store = InMemoryTriMemStore()
    context = AccessContext("org-1", "alice")
    graph = UserSemanticGraph(
        graph_id="rules",
        org_id=context.org_id,
        owner_user_id=context.user_id,
        repository_id="acme/math",
        temporal=_temporal(),
    )
    invalid = _node(
        graph,
        "invalid-rule",
        NodeType.SEMANTIC_RULE,
        _payload(version="commit-old", version_valid=False, stale=True, verified=False,
                 source_outcome="failed"),
    )
    malformed = _node(
        graph,
        "malformed-rule",
        NodeType.SEMANTIC_RULE,
        _payload(coverage="operation", quality="high"),
    )
    store.put_graph(context, graph)
    store.put_node(context, invalid)
    store.put_node(context, malformed)

    snapshot = CanonicalRetrievalStore(store).snapshot(
        MemoryKind.USER_SEMANTIC,
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )
    assert list(snapshot.records) == ["invalid-rule"]
    record = snapshot.records["invalid-rule"]
    assert not record.version_valid and record.stale and not record.verified
    assert record.source_outcome == "failed"
    assert "malformed-rule" not in snapshot.nodes


def test_adapter_refuses_noncanonical_vector_payload_sources():
    with pytest.raises(TypeError, match="InMemoryTriMemStore"):
        CanonicalRetrievalStore({"qdrant_payload": {"retrieval_text": "not authoritative"}})


def test_adapter_implements_retrieval_store_protocol_end_to_end():
    store = InMemoryTriMemStore()
    context = AccessContext("org-1", "alice")
    memory_graph = UserEpisodicGraph(
        graph_id="episodes",
        org_id=context.org_id,
        owner_user_id=context.user_id,
        repository_id="acme/math",
        temporal=_temporal(),
    )
    store.put_graph(context, memory_graph)
    store.put_node(context, _node(
        memory_graph,
        "episode-1",
        NodeType.EPISODE,
        _payload(completeness=1.0, coverage=["operation", "precondition", "verification"]),
    ))

    working = ShortTermWorkingGraph("target-1", "Fix reflected addition", "acme/math")
    subtask = working.add_subtask(SubtaskSpec(
        node_id="reflected-add",
        objective="preserve reflected Array addition operand order",
        operation="PATCH_REFLECTED_OPERATOR",
        symbols=("Array.__radd__",),
    ))
    working.activate(subtask.node_id)
    adapter = CanonicalRetrievalStore(store)
    decision = TriMemoryRetriever(adapter).recall(
        working,
        RetrievalSessionState(working.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
        now=NOW,
    )

    assert [item.memory_id for item in decision.injections] == ["episode-1"]
    assert decision.injections[0].verify()
    assert decision.injections[0].graph_hash == adapter.snapshot(
        MemoryKind.EPISODIC,
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    ).graph_hash
