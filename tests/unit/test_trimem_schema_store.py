"""Credential-free correctness checks for TriMem canonical records and store."""
import hashlib

import pytest

from enterprise_memory.trimem.schema import (
    AccessContext,
    AccessType,
    EdgeType,
    GraphEdge,
    GraphKind,
    GraphNode,
    GraphState,
    LifecycleState,
    MemoryAccessEvent,
    NodeType,
    OrganisationSemanticGraph,
    PolicyAction,
    PolicyActor,
    PolicyTransition,
    ReviewAuthority,
    ReviewProvenance,
    SemanticStrength,
    SemanticStrengthRecord,
    ShortTermWorkingGraph,
    TemporalMetadata,
    UserEpisodicGraph,
    UserSemanticGraph,
    canonical_hash,
    canonical_json,
)
from enterprise_memory.trimem.store import (
    InMemoryTriMemStore,
    IntegrityViolation,
    NotFound,
    ScopeViolation,
)


NOW = "2026-08-31T00:00:00Z"


def _temporal(event_time=None, verified=None):
    return TemporalMetadata(
        ingested_at=NOW,
        event_time=event_time,
        last_verified_at=verified,
    )


def _review(review_id="review-1"):
    return ReviewProvenance(
        review_id=review_id,
        reviewer_id="human-reviewer",
        reviewed_at=NOW,
        authority=ReviewAuthority.HUMAN_REVIEW,
        policy_version="shared-promotion-v1",
        evidence_hash="sha256:" + "a" * 64,
    )


def _node(graph, node_id, node_type, payload, event_time=None, review=None):
    return GraphNode(
        node_id=node_id,
        graph_id=graph.graph_id,
        org_id=graph.org_id,
        namespace=graph.namespace,
        graph_kind=graph.kind,
        owner_user_id=graph.owner_user_id,
        repository_id=graph.repository_id,
        node_type=node_type,
        canonical_payload=payload,
        temporal=_temporal(event_time),
        review_provenance=review,
    )


def test_canonical_hash_is_key_order_independent_and_record_hash_is_verified():
    left = {"operation": "rename", "nested": {"z": 1, "a": ["한글", 2]}}
    right = {"nested": {"a": ["한글", 2], "z": 1}, "operation": "rename"}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_hash(left) == canonical_hash(right)
    graph = UserEpisodicGraph(
        graph_id="episodic-a", org_id="org-a", owner_user_id="user-a", temporal=_temporal()
    )
    assert graph.verify_hash()
    assert graph.content_hash.startswith("sha256:")


def test_scope_and_review_invariants_fail_closed_at_construction():
    with pytest.raises(ValueError, match="owner_user_id"):
        UserEpisodicGraph(graph_id="g", org_id="org", temporal=_temporal())
    with pytest.raises(ValueError, match="cannot have owner"):
        OrganisationSemanticGraph(
            graph_id="g", org_id="org", owner_user_id="user", temporal=_temporal(),
            review_provenance=_review(),
        )
    with pytest.raises(ValueError, match="review provenance"):
        OrganisationSemanticGraph(graph_id="g", org_id="org", temporal=_temporal())

    semantic = UserSemanticGraph(
        graph_id="semantic", org_id="org", owner_user_id="user", temporal=_temporal()
    )
    with pytest.raises(ValueError, match="Episode"):
        _node(semantic, "episode", NodeType.EPISODE, {"forbidden": True})


def test_semantic_strength_record_is_canonical_and_owner_partitioned():
    record = SemanticStrengthRecord(
        strength_id="strength-a",
        graph_id="semantic-a",
        semantic_node_id="rule-a",
        org_id="org-a",
        graph_kind=GraphKind.USER_SEMANTIC,
        owner_user_id="alice",
        strength=SemanticStrength(
            support=1,
            successful_reuse=2,
            negative_transfer=0.5,
        ),
        updated_at=NOW,
    )
    assert record.verify_hash()
    assert record.strength.score == 2.5
    with pytest.raises(ValueError, match="owner_user_id"):
        SemanticStrengthRecord(
            strength_id="strength-private",
            graph_id="semantic-a",
            semantic_node_id="rule-a",
            org_id="org-a",
            graph_kind=GraphKind.USER_SEMANTIC,
            owner_user_id=None,
            strength=SemanticStrength(),
            updated_at=NOW,
        )


def test_same_org_cross_user_private_graphs_are_non_disclosing():
    store = InMemoryTriMemStore()
    alice = AccessContext("org-a", "alice")
    bob = AccessContext("org-a", "bob")
    graph = UserEpisodicGraph(
        graph_id="alice-episodes", org_id="org-a", owner_user_id="alice", temporal=_temporal()
    )
    store.put_graph(alice, graph)
    episode = _node(graph, "episode-a", NodeType.EPISODE, {"patch_ref": "blob:private"})
    store.put_node(alice, episode)

    with pytest.raises(NotFound, match="not found"):
        store.get_graph(bob, graph.graph_id)
    with pytest.raises(NotFound, match="not found"):
        store.get_node(bob, episode.node_id)
    assert store.list_graphs(bob) == []
    assert store.list_nodes(bob) == []
    with pytest.raises(ScopeViolation, match="owner boundary"):
        store.put_node(bob, episode)

    semantic = UserSemanticGraph(
        graph_id="alice-semantics", org_id="org-a", owner_user_id="alice", temporal=_temporal()
    )
    rule = _node(semantic, "alice-rule", NodeType.SEMANTIC_RULE, {"rule": "private"})
    store.put_graph(alice, semantic)
    store.put_node(alice, rule)
    with pytest.raises(NotFound):
        store.get_node(bob, rule.node_id)


def test_in_memory_store_rejects_same_owner_records_from_another_namespace():
    ctx = AccessContext("org-a", "alice")
    store = InMemoryTriMemStore(namespace="trimem:run-a:dev:m2")
    foreign = UserEpisodicGraph(
        graph_id="episodes", org_id=ctx.org_id, namespace="trimem:run-b:dev:m2",
        owner_user_id=ctx.user_id, temporal=_temporal(),
    )
    with pytest.raises(ScopeViolation, match="namespace boundary"):
        store.put_graph(ctx, foreign)

    local = UserEpisodicGraph(
        graph_id="episodes", org_id=ctx.org_id, namespace=store.namespace,
        owner_user_id=ctx.user_id, temporal=_temporal(),
    )
    store.put_graph(ctx, local)
    wrong_node = GraphNode(
        node_id="wrong", graph_id=local.graph_id, org_id=local.org_id,
        namespace="trimem:run-b:dev:m2", graph_kind=local.kind,
        owner_user_id=ctx.user_id, node_type=NodeType.EPISODE,
        canonical_payload={"private": True}, temporal=_temporal(),
    )
    with pytest.raises(ScopeViolation, match="namespace boundary"):
        store.put_node(ctx, wrong_node)


def test_reviewed_organisation_semantic_is_same_org_shared_but_cross_org_hidden():
    store = InMemoryTriMemStore()
    alice = AccessContext("org-a", "alice")
    bob = AccessContext("org-a", "bob")
    outsider = AccessContext("org-b", "mallory")
    review = _review()
    graph = OrganisationSemanticGraph(
        graph_id="org-rules", org_id="org-a", temporal=_temporal(), review_provenance=review
    )
    rule = _node(
        graph,
        "rule-a",
        NodeType.SEMANTIC_RULE,
        {"precondition": "API v2", "operation": "pass timeout explicitly"},
        review=review,
    )
    store.put_graph(alice, graph)
    store.put_node(alice, rule)

    assert store.get_node(bob, rule.node_id).payload_hash == rule.payload_hash
    with pytest.raises(NotFound):
        store.get_node(outsider, rule.node_id)


def test_fifo_archival_preserves_event_provenance_and_payload_hash():
    store = InMemoryTriMemStore(clock=lambda: "2026-09-01T00:00:00Z")
    ctx = AccessContext("org-a", "alice")
    graph = UserEpisodicGraph(
        graph_id="episodes", org_id=ctx.org_id, owner_user_id=ctx.user_id, temporal=_temporal()
    )
    store.put_graph(ctx, graph)
    older = _node(graph, "older", NodeType.EPISODE, {"patch_ref": "blob:one"}, "2026-01-01T00:00:00Z")
    newer = _node(graph, "newer", NodeType.EPISODE, {"patch_ref": "blob:two"}, "2026-02-01T00:00:00Z")
    store.put_node(ctx, newer)
    store.put_node(ctx, older)  # insertion order must not override event-time FIFO

    archived = store.archive_episodic_fifo(ctx, capacity=1)
    assert [node.node_id for node in archived] == ["older"]
    retained = store.get_node(ctx, "older")
    assert retained.lifecycle_state == LifecycleState.ARCHIVED
    assert retained.canonical_payload == {}
    assert retained.payload_hash == older.payload_hash
    assert retained.temporal.event_time == older.temporal.event_time
    assert retained.archive_reason == "episodic_fifo_capacity"
    assert retained.archived_from_content_hash == older.content_hash
    assert store.list_nodes(ctx) == [newer]


def test_semantic_archival_uses_strength_formula_and_deterministic_ties():
    store = InMemoryTriMemStore(clock=lambda: "2026-09-01T00:00:00Z")
    ctx = AccessContext("org-a", "alice")
    graph = UserSemanticGraph(
        graph_id="semantics", org_id=ctx.org_id, owner_user_id=ctx.user_id, temporal=_temporal()
    )
    store.put_graph(ctx, graph)
    weak = _node(graph, "weak", NodeType.SEMANTIC_RULE, {"rule": "weak"})
    strong = _node(graph, "strong", NodeType.SEMANTIC_RULE, {"rule": "strong"})
    store.put_node(ctx, weak)
    store.put_node(ctx, strong)
    store.set_semantic_strength(ctx, weak.node_id, SemanticStrength(support=1, contradiction=3))
    store.set_semantic_strength(
        ctx, strong.node_id, SemanticStrength(support=2, successful_reuse=2, contradiction=1)
    )

    archived = store.archive_weakest_semantic(ctx, capacity=1)
    assert [node.node_id for node in archived] == ["weak"]
    assert store.get_node(ctx, "weak").payload_hash == weak.payload_hash
    assert [node.node_id for node in store.list_nodes(ctx)] == ["strong"]


def test_structural_edges_are_partitioned_and_cycle_checked():
    store = InMemoryTriMemStore()
    ctx = AccessContext("org-a", "alice")
    graph = ShortTermWorkingGraph(
        graph_id="work", org_id=ctx.org_id, owner_user_id=ctx.user_id,
        solve_job_id="job-a", temporal=_temporal(),
    )
    store.put_graph(ctx, graph)
    a = _node(graph, "a", NodeType.SUBTASK, {"objective": "first"})
    b = _node(graph, "b", NodeType.SUBTASK, {"objective": "second"})
    store.put_node(ctx, a)
    store.put_node(ctx, b)
    forward = GraphEdge(
        edge_id="a-b", graph_id=graph.graph_id, org_id=graph.org_id,
        graph_kind=graph.kind, owner_user_id=graph.owner_user_id,
        edge_type=EdgeType.DEPENDS_ON, source_node_id="a", target_node_id="b",
        temporal=_temporal(),
    )
    store.put_edge(ctx, forward)
    reverse = GraphEdge(
        edge_id="b-a", graph_id=graph.graph_id, org_id=graph.org_id,
        graph_kind=graph.kind, owner_user_id=graph.owner_user_id,
        edge_type=EdgeType.DECOMPOSES_TO, source_node_id="b", target_node_id="a",
        temporal=_temporal(),
    )
    with pytest.raises(IntegrityViolation, match="cycle"):
        store.put_edge(ctx, reverse)


def test_dqn_transition_cannot_target_shared_and_vector_payload_is_reference_only():
    with pytest.raises(ValueError, match="cannot publish"):
        PolicyTransition(
            transition_id="t", graph_id="g", candidate_node_id="n", org_id="org",
            owner_user_id="user", action=PolicyAction.MOVE_TO_SEMANTIC_CANDIDATE,
            actor=PolicyActor.DOUBLE_DQN, event_time=NOW,
            target_graph_kind=GraphKind.ORGANISATION_SEMANTIC,
        )

    store = InMemoryTriMemStore()
    ctx = AccessContext("org", "user")
    graph = UserSemanticGraph(
        graph_id="semantic", org_id="org", owner_user_id="user", temporal=_temporal()
    )
    node = _node(graph, "rule", NodeType.SEMANTIC_RULE, {"private_text": "never index me"})
    store.put_graph(ctx, graph)
    store.put_node(ctx, node)
    metadata = store.vector_metadata(ctx, node.node_id, embedding_model_id="embed-frozen")
    payload = metadata.payload()
    assert payload["canonical_content_hash"] == node.content_hash
    assert payload["owner_user_id"] == "user"
    assert "canonical_payload" not in payload
    assert "private_text" not in repr(payload)


def test_sealed_memory_remains_readable_and_exact_injection_is_append_only():
    store = InMemoryTriMemStore()
    ctx = AccessContext("org", "user")
    graph = UserSemanticGraph(
        graph_id="semantic", org_id="org", owner_user_id="user", temporal=_temporal()
    )
    node = _node(graph, "rule", NodeType.SEMANTIC_RULE, {"rule": "stable"})
    store.put_graph(ctx, graph)
    store.put_node(ctx, node)
    sealed = store.set_graph_state(ctx, graph.graph_id, GraphState.SEALED)
    assert sealed.state == GraphState.SEALED and sealed.verify_hash()
    with pytest.raises(IntegrityViolation, match="not active"):
        store.put_node(ctx, _node(graph, "late", NodeType.SEMANTIC_RULE, {"rule": "late"}))

    blob = "정확한 memory bytes".encode("utf-8")
    event = MemoryAccessEvent.injection(
        event_id="inject-1",
        graph_id=graph.graph_id,
        node_id=node.node_id,
        org_id=graph.org_id,
        graph_kind=graph.kind,
        actor_user_id=ctx.user_id,
        owner_user_id=ctx.user_id,
        event_time=NOW,
        injected_bytes=blob,
    )
    stored = store.append_access(ctx, event)
    assert stored.access_type == AccessType.INJECTED
    assert stored.injected_byte_count == len(blob)
    assert stored.injected_hash == "sha256:" + hashlib.sha256(blob).hexdigest()
    assert store.append_access(ctx, event).content_hash == event.content_hash  # idempotent replay

    archived = store.set_graph_state(ctx, graph.graph_id, GraphState.ARCHIVED)
    assert archived.state == GraphState.ARCHIVED
    later = MemoryAccessEvent.injection(
        event_id="inject-2",
        graph_id=graph.graph_id,
        node_id=node.node_id,
        org_id=graph.org_id,
        graph_kind=graph.kind,
        actor_user_id=ctx.user_id,
        owner_user_id=ctx.user_id,
        event_time="2026-08-31T00:00:01Z",
        injected_bytes=b"archived audit",
    )
    assert store.append_access(ctx, later) == later
    with pytest.raises(IntegrityViolation, match="not active"):
        store.put_edge(
            ctx,
            GraphEdge(
                edge_id="late-edge", graph_id=graph.graph_id, org_id=graph.org_id,
                graph_kind=graph.kind, owner_user_id=ctx.user_id,
                edge_type=EdgeType.DERIVED_FROM, source_node_id=node.node_id,
                target_node_id="late", temporal=_temporal(),
            ),
        )
