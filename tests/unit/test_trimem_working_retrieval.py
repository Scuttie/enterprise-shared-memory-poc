import hashlib

import pytest

from enterprise_memory.trimem.ppr import (
    DeterministicHashEmbedder, GraphNode, SeedSignal, personalized_pagerank, rank_graph,
)
from enterprise_memory.trimem.retrieval import (
    InMemoryMemoryGraphStore, MemoryGraphSnapshot, MemoryKind, MemoryRecord, RetrievalConfig,
    RecallError, RetrievalSessionState, TriMemoryRetriever,
)
from enterprise_memory.trimem.working_graph import (
    CompletionEvidenceRequired, DependencyError, Evidence, GenericStageOnlyError, ShortTermWorkingGraph,
    SubtaskSpec,
)


def _graph(task_id="task-1"):
    graph = ShortTermWorkingGraph(task_id, "Fix reversed addition under NumPy 2", "acme/math")
    locate = graph.add_subtask(SubtaskSpec(
        node_id="locate-reflected", objective="locate the reflected operator implementation for reversed addition",
        operation="LOCATE_SYMBOL", symbols=("Array.__radd__",), apis=("numpy.add",),
    ))
    change = graph.add_subtask(SubtaskSpec(
        node_id="preserve-order", objective="preserve operand ordering while delegating reflected addition",
        operation="REPLACE_DELEGATION", dependencies=(locate.node_id,), symbols=("Array.__radd__",),
        invariants=("left and right operands retain reflected order",), tests=("test_reversed_add",),
    ))
    return graph, locate, change


def _done(summary="symbol located"):
    return Evidence.capture("tool_result", summary, {"ok": True}, source="read_file",
                            supports_completion=True)


def _record(memory_id, kind, text, *, owner="alice", org="org-1", repository="acme/math", **kw):
    return MemoryRecord(memory_id=memory_id, kind=kind, retrieval_text=text,
                        execution_view=kw.pop("execution_view", text), owner_user_id=owner,
                        org_id=org, repository=repository, **kw)


def _snapshot(kind, records, adjacency=None, nodes=None):
    mapping = {record.memory_id: record for record in records}
    return MemoryGraphSnapshot(kind, mapping, nodes or {}, adjacency or {}, graph_hash="graph-%s" % kind.value)


def test_semantic_dag_rejects_stage_only_and_enforces_dependency_and_completion_evidence():
    with pytest.raises(GenericStageOnlyError):
        SubtaskSpec(objective="ANALYZE TASK", operation="ANALYZE")
    graph, locate, change = _graph()
    with pytest.raises(DependencyError):
        graph.activate(change.node_id)
    assert graph.activate_next().node_id == locate.node_id
    with pytest.raises(CompletionEvidenceRequired):
        graph.complete_active(Evidence.capture("note", "not completion proof", "x"))
    graph.complete_active(_done())
    assert graph.activate_next().node_id == change.node_id
    assert sum(node.status == "ACTIVE" for node in graph.nodes.values()) == 1


def test_evidence_updates_active_semantics_and_can_extend_dag_deterministically():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    evidence = Evidence.capture(
        "test_failure", "public test exposed a NumPy version incompatibility", {"failed": "test_numpy2"},
        attributes={"errors": ["TypeError: reflected operand"], "apis": ["numpy.__version__"],
                    "predicted_operation": "CHECK_VERSION_AND_DISPATCH"},
    )
    added = graph.update_from_evidence(evidence, new_subtasks=[SubtaskSpec(
        node_id="version-guard", objective="identify the incompatible NumPy dispatch version boundary",
        operation="CHECK_VERSION", dependencies=(locate.node_id,), apis=("numpy.__version__",),
        preconditions=("NumPy major version is known",),
    )])
    assert added[0].node_id == "version-guard"
    assert "TypeError: reflected operand" in graph.active_node.errors
    assert graph.active_node.operation == "CHECK_VERSION_AND_DISPATCH"
    snap = graph.snapshot()
    restored = ShortTermWorkingGraph.from_snapshot(snap)
    assert restored.content_hash() == graph.content_hash()


def test_dependency_cycle_is_rejected_without_mutating_graph():
    graph, locate, change = _graph()
    with pytest.raises(DependencyError):
        graph.add_dependency(locate.node_id, change.node_id)
    assert locate.dependencies == ()


def test_hash_embedding_and_ppr_are_stable_under_input_order_and_ties():
    embedder = DeterministicHashEmbedder(32)
    assert embedder.embed("Array reflected add") == embedder.embed("Array reflected add")
    nodes_a = {
        "b": GraphNode("b", "reflected operator Array radd"),
        "a": GraphNode("a", "reflected operator Array radd"),
        "c": GraphNode("c", "unrelated serialization"),
    }
    nodes_b = dict(reversed(list(nodes_a.items())))
    adjacency_a = {"b": {"c": 1, "a": 1}, "a": ["b"], "c": ["b"]}
    adjacency_b = {"c": ["b"], "a": ["b"], "b": {"a": 1, "c": 1}}
    seeds = [SeedSignal("objective", "reflected operator Array radd")]
    first = rank_graph(nodes_a, adjacency_a, seeds, embedder=embedder)
    second = rank_graph(nodes_b, adjacency_b, seeds, embedder=embedder)
    assert first == second
    assert [item.node_id for item in first[:2]] == ["a", "b"]
    scores = personalized_pagerank(adjacency_a, {"a": 0.5, "b": 0.5}, iterations=20)
    assert sum(scores.values()) == pytest.approx(1.0)


def test_production_ppr_embedder_is_immutable_and_lazy():
    from enterprise_memory.trimem.ppr import (
        PinnedSentenceTransformerPPR,
        TRIMEM_PRODUCTION_EMBEDDING_MODEL,
        TRIMEM_PRODUCTION_EMBEDDING_REVISION,
    )

    embedder = PinnedSentenceTransformerPPR()
    provenance = embedder.provenance()
    assert provenance["model_id"] == TRIMEM_PRODUCTION_EMBEDDING_MODEL
    assert provenance["revision"] == TRIMEM_PRODUCTION_EMBEDDING_REVISION
    assert provenance["dimensions"] == 384
    assert provenance["production"] is True
    assert embedder._delegate is None
    with pytest.raises(ValueError, match="revision is frozen"):
        PinnedSentenceTransformerPPR(revision="main")


def test_strong_complete_episode_is_the_only_active_node_injection_and_hashes_exact_utf8():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    episode = _record(
        "ep-good", MemoryKind.EPISODIC, "Array __radd__ reflected operator numpy.add",
        execution_view="검증된 에피소드: reflected operand 순서를 유지한다.", completeness=1.0,
        coverage=("operation", "precondition", "verification"),
    )
    semantic = _record("sem-user", MemoryKind.USER_SEMANTIC,
                       "Array __radd__ reflected operator semantic rule")
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [episode]),
        MemoryKind.USER_SEMANTIC: _snapshot(MemoryKind.USER_SEMANTIC, [semantic]),
    })
    state = RetrievalSessionState(graph.task_id)
    decision = TriMemoryRetriever(store).recall(
        graph, state, user_id="alice", org_id="org-1", repository="acme/math")
    assert [item.memory_id for item in decision.injections] == ["ep-good"]
    injection = decision.injections[0]
    assert injection.byte_count == len(injection.exact_text.encode("utf-8"))
    assert injection.sha256 == hashlib.sha256(injection.exact_utf8).hexdigest()
    assert injection.verify()


def test_strong_incomplete_episode_gets_user_semantic_complement_before_org():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    episode = _record("ep", MemoryKind.EPISODIC, "Array __radd__ reflected operator",
                      completeness=0.3, coverage=("operation",))
    user_sem = _record("user-sem", MemoryKind.USER_SEMANTIC,
                       "Array __radd__ precondition verification", coverage=("precondition", "verification"))
    org_sem = _record("org-sem", MemoryKind.ORG_SEMANTIC,
                      "Array __radd__ precondition verification", owner=None,
                      coverage=("precondition", "verification"))
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [episode]),
        MemoryKind.USER_SEMANTIC: _snapshot(MemoryKind.USER_SEMANTIC, [user_sem]),
        MemoryKind.ORG_SEMANTIC: _snapshot(MemoryKind.ORG_SEMANTIC, [org_sem]),
    })
    decision = TriMemoryRetriever(store).recall(
        graph, RetrievalSessionState(graph.task_id), user_id="alice", org_id="org-1",
        repository="acme/math")
    assert [(item.memory_id, item.kind) for item in decision.injections] == [
        ("ep", MemoryKind.EPISODIC), ("user-sem", MemoryKind.USER_SEMANTIC)]


def test_low_episode_relevance_backs_off_to_org_after_user_semantic_miss():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    episode = _record("ep-unrelated", MemoryKind.EPISODIC, "database migration unrelated topic")
    user_sem = _record("user-unrelated", MemoryKind.USER_SEMANTIC, "css color layout")
    org_sem = _record("org-relevant", MemoryKind.ORG_SEMANTIC,
                      "Array __radd__ reflected operator numpy.add", owner=None)
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [episode]),
        MemoryKind.USER_SEMANTIC: _snapshot(MemoryKind.USER_SEMANTIC, [user_sem]),
        MemoryKind.ORG_SEMANTIC: _snapshot(MemoryKind.ORG_SEMANTIC, [org_sem]),
    })
    decision = TriMemoryRetriever(store).recall(
        graph, RetrievalSessionState(graph.task_id), user_id="alice", org_id="org-1",
        repository="acme/math")
    assert [item.memory_id for item in decision.injections] == ["org-relevant"]
    assert [row["bank"] for row in decision.bank_trace] == [
        MemoryKind.EPISODIC.value, MemoryKind.USER_SEMANTIC.value, MemoryKind.ORG_SEMANTIC.value]


def test_cross_user_stale_and_version_invalid_records_never_inject():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    records = [
        _record("bob", MemoryKind.EPISODIC, "Array __radd__ reflected operator", owner="bob"),
        _record("stale", MemoryKind.EPISODIC, "Array __radd__ reflected operator", stale=True),
        _record("invalid", MemoryKind.EPISODIC, "Array __radd__ reflected operator", version_valid=False),
    ]
    store = InMemoryMemoryGraphStore({MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, records)})
    decision = TriMemoryRetriever(store).recall(
        graph, RetrievalSessionState(graph.task_id), user_id="alice", org_id="org-1",
        repository="acme/math")
    assert decision.injections == ()
    assert {row["reason"] for row in decision.rejections} == {
        "cross_user_private", "stale", "version_invalid"}


def test_per_node_task_and_context_limits_are_enforced():
    with pytest.raises(RecallError):
        RetrievalConfig(max_task_injections=4)
    graph, locate, change = _graph()
    graph.activate(locate.node_id)
    episode = _record("ep-one", MemoryKind.EPISODIC, "Array __radd__ reflected operator",
                      execution_view="12345", completeness=1.0,
                      coverage=("operation", "precondition", "verification"))
    store = InMemoryMemoryGraphStore({MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [episode])})
    retriever = TriMemoryRetriever(store, RetrievalConfig(context_budget_bytes=5, max_task_injections=1))
    state = RetrievalSessionState(graph.task_id)
    first = retriever.recall(graph, state, user_id="alice", org_id="org-1", repository="acme/math")
    second = retriever.recall(graph, state, user_id="alice", org_id="org-1", repository="acme/math")
    assert len(first.injections) == 1 and second.injections == ()
    assert state.total_injections == 1 and state.context_bytes == 5
    graph.complete_active(_done())
    graph.activate(change.node_id)
    third = retriever.recall(graph, state, user_id="alice", org_id="org-1", repository="acme/math")
    assert third.injections == ()
