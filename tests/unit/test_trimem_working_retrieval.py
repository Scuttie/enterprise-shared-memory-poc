import hashlib
from dataclasses import replace

import pytest

from enterprise_memory.trimem.ppr import (
    DeterministicHashEmbedder, GraphNode, SeedSignal, personalized_pagerank, rank_graph,
)
from enterprise_memory.trimem.retrieval import (
    InMemoryMemoryGraphStore, MemoryGraphSnapshot, MemoryKind, MemoryRecord, RetrievalConfig,
    RecallError, RecallSelectionMode, RetrievalSessionState, TriMemoryRetriever,
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


def _path_graph(task_id="target-task"):
    graph = ShortTermWorkingGraph(task_id, "Fix reflected addition", "acme/math")
    node = graph.add_subtask(SubtaskSpec(
        node_id="edit-reflected",
        objective="fix the reflected addition implementation",
        operation="REPLACE_DELEGATION",
        files=("src/array.py",),
        symbols=("Array.__radd__",),
    ))
    graph.activate(node.node_id)
    return graph, node


def _safe_pool_metadata(**overrides):
    values = {
        "source_task_id": "historical-task",
        "source_dataset_id": "public-dataset@revision",
        "source_repository": "source/repository",
        "source_commit": "b" * 40,
        "source_timestamp": "2025-01-02T03:04:05Z",
        "bank_type": "HISTORICAL_VERIFIED",
        "verification_evidence_sha256": "c" * 64,
        "provenance_sha256": "d" * 64,
        "payload_sha256": "e" * 64,
        "permission_scope": "PUBLIC_READ",
        "tenant_scope": "BENCHMARK_ISOLATED",
        "version_scope": "EXACT_SOURCE_COMMIT",
        "path_scope": "src/",
        "quarantined": False,
        "target_derived": False,
    }
    values.update(overrides)
    return values


def _record(memory_id, kind, text, *, owner="alice", org="org-1", repository="acme/math", **kw):
    return MemoryRecord(memory_id=memory_id, kind=kind, retrieval_text=text,
                        execution_view=kw.pop("execution_view", text), owner_user_id=owner,
                        org_id=org, repository=repository, **kw)


def _snapshot(kind, records, adjacency=None, nodes=None):
    mapping = {record.memory_id: record for record in records}
    return MemoryGraphSnapshot(kind, mapping, nodes or {}, adjacency or {}, graph_hash="graph-%s" % kind.value)


class _ZeroEmbedder:
    def embed(self, text):
        return (0.0,) * 8

    def provenance(self):
        return {"model_id": "zero-test-embedder", "dimensions": 8}


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


def test_current_gate_keeps_legacy_trace_and_emits_fixed_no_dqn_telemetry():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    low_quality = _record(
        "ep-low",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected operator numpy.add",
        quality=0.1,
    )
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [low_quality]),
    })
    retriever = TriMemoryRetriever(
        store,
        RetrievalConfig(min_confidence=0.9),
        diagnostic_telemetry=True,
    )

    decision = retriever.recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    # The pre-diagnostic bank trace remains the exact CURRENT_GATE shape.
    assert decision.bank_trace == (
        {
            "bank": "EPISODIC",
            "decision": "ABSTAIN",
            "reason": "low_confidence",
            "confidence": decision.bank_trace[0]["confidence"],
            "margin": decision.bank_trace[0]["margin"],
        },
        {"bank": "USER_SEMANTIC", "decision": "ABSTAIN", "reason": "no_eligible"},
        {"bank": "ORG_SEMANTIC", "decision": "ABSTAIN", "reason": "no_eligible"},
    )
    first = decision.decision_telemetry[0]
    assert first == {
        "recall_attempt_id": first["recall_attempt_id"],
        "target_id": graph.task_id,
        "subtask_id": locate.node_id,
        "bank_type": "EPISODIC",
        "candidate_count_before_filter": 1,
        "candidate_count_after_filter": 1,
        "top_candidate_id": "ep-low",
        "top_embedding_score": first["top_embedding_score"],
        "top_ppr_score": first["top_ppr_score"],
        "threshold": {"min_confidence": 0.9, "min_margin": 0.0},
        "Q_USE": None,
        "Q_ABSTAIN": None,
        "router_policy": "N/A",
        "final_reason_code": "BELOW_CONFIDENCE_THRESHOLD",
    }
    assert first["recall_attempt_id"].startswith("sha256:")
    assert len(first["recall_attempt_id"]) == len("sha256:") + 64

    repeated = retriever.recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )
    assert repeated.decision_telemetry == decision.decision_telemetry


def test_forced_safe_top1_bypasses_only_utility_gate_and_injects_one_per_subtask():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    low_quality = _record(
        "ep-low",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected operator numpy.add",
        quality=0.1,
        completeness=0.1,
    )
    semantic = _record(
        "sem-top",
        MemoryKind.USER_SEMANTIC,
        "Array __radd__ reflected operator numpy.add",
        quality=0.2,
    )
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [low_quality]),
        MemoryKind.USER_SEMANTIC: _snapshot(MemoryKind.USER_SEMANTIC, [semantic]),
    })
    state = RetrievalSessionState(graph.task_id)
    retriever = TriMemoryRetriever(
        store,
        RetrievalConfig(min_confidence=0.9, min_margin=0.5),
        selection_mode=RecallSelectionMode.FORCED_SAFE_TOP1,
    )

    decision = retriever.recall(
        graph,
        state,
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert [item.memory_id for item in decision.injections] == ["sem-top"]
    assert state.total_injections == 1
    by_bank = {row["bank_type"]: row for row in decision.decision_telemetry}
    assert by_bank["EPISODIC"]["final_reason_code"] == (
        "FORCED_SAFE_TOP1_LIMIT_REJECTION"
    )
    assert by_bank["USER_SEMANTIC"]["final_reason_code"] == "INJECTED"
    assert by_bank["ORG_SEMANTIC"]["final_reason_code"] == "NO_CANDIDATE_GENERATED"
    assert all(row["Q_USE"] is None and row["Q_ABSTAIN"] is None
               for row in decision.decision_telemetry)
    assert [row["decision"] for row in decision.bank_trace] == [
        "ABSTAIN", "USE", "ABSTAIN",
    ]

    again = retriever.recall(
        graph,
        state,
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )
    assert again.injections == ()
    assert again.bank_trace == ({
        "bank": "ALL",
        "decision": "ABSTAIN",
        "reason": "subtask_injection_limit",
    },)
    assert again.decision_telemetry[0]["final_reason_code"] == (
        "SUBTASK_INJECTION_LIMIT_REJECTION"
    )


def test_forced_safe_top1_selects_zero_score_candidate_but_current_gate_does_not():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    record = _record(
        "zero-score-safe",
        MemoryKind.EPISODIC,
        "text with no positive seed",
    )
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [record]),
    })
    current = TriMemoryRetriever(
        store, embedder=_ZeroEmbedder(), diagnostic_telemetry=True
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )
    forced = TriMemoryRetriever(
        store,
        embedder=_ZeroEmbedder(),
        selection_mode="FORCED_SAFE_TOP1",
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert current.injections == ()
    assert current.decision_telemetry[0]["final_reason_code"] == "NO_SEED_MATCH"
    assert [item.memory_id for item in forced.injections] == ["zero-score-safe"]
    assert forced.decision_telemetry[0]["top_embedding_score"] == 0.0
    assert forced.decision_telemetry[0]["top_ppr_score"] == 0.0


def test_forced_safe_cross_bank_tie_break_uses_embedding_then_memory_id():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    episode = _record(
        "a-episode",
        MemoryKind.EPISODIC,
        "zero episodic",
    )
    semantic = _record(
        "z-semantic",
        MemoryKind.USER_SEMANTIC,
        "zero semantic",
    )
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: MemoryGraphSnapshot(
            MemoryKind.EPISODIC,
            {episode.memory_id: episode},
            graph_hash="episode",
            query_telemetry={
                "candidate_count_before_filter": 1,
                "embedding_scores": {episode.memory_id: 0.2},
            },
        ),
        MemoryKind.USER_SEMANTIC: MemoryGraphSnapshot(
            MemoryKind.USER_SEMANTIC,
            {semantic.memory_id: semantic},
            graph_hash="semantic",
            query_telemetry={
                "candidate_count_before_filter": 1,
                "embedding_scores": {semantic.memory_id: 0.8},
            },
        ),
    })
    decision = TriMemoryRetriever(
        store,
        embedder=_ZeroEmbedder(),
        selection_mode="FORCED_SAFE_TOP1",
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )
    assert [item.memory_id for item in decision.injections] == ["z-semantic"]

    tied_store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: replace(
            store.snapshot(
                MemoryKind.EPISODIC,
                user_id="alice",
                org_id="org-1",
                repository="acme/math",
            ),
            query_telemetry={
                "candidate_count_before_filter": 1,
                "embedding_scores": {episode.memory_id: 0.8},
            },
        ),
        MemoryKind.USER_SEMANTIC: store.snapshot(
            MemoryKind.USER_SEMANTIC,
            user_id="alice",
            org_id="org-1",
            repository="acme/math",
        ),
    })
    tied = TriMemoryRetriever(
        tied_store,
        embedder=_ZeroEmbedder(),
        selection_mode="FORCED_SAFE_TOP1",
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )
    assert [item.memory_id for item in tied.injections] == ["a-episode"]


def test_forced_safe_top1_never_bypasses_safety_or_context_budget():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    unsafe = _record(
        "ep-cross-user",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected operator numpy.add",
        owner="mallory",
        quality=1.0,
    )
    safe = _record(
        "ep-safe",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected operator numpy.add",
        execution_view="too large",
        quality=0.1,
    )
    store = InMemoryMemoryGraphStore({
        MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [unsafe, safe]),
    })
    retriever = TriMemoryRetriever(
        store,
        RetrievalConfig(min_confidence=0.9, context_budget_bytes=2),
        selection_mode="FORCED_SAFE_TOP1",
    )

    decision = retriever.recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert decision.injections == ()
    assert {row["memory_id"]: row["reason"] for row in decision.rejections} == {
        "ep-cross-user": "cross_user_private",
        "ep-safe": "context_budget",
    }
    episode = decision.decision_telemetry[0]
    assert episode["candidate_count_before_filter"] == 2
    assert episode["candidate_count_after_filter"] == 1
    assert episode["top_candidate_id"] == "ep-safe"
    assert episode["final_reason_code"] == "CONTEXT_INJECTION_BUDGET_REJECTION"


@pytest.mark.parametrize(
    ("record_kwargs", "expected_reason"),
    [
        ({"owner": "mallory"}, "PERMISSION_GATE_REJECTED"),
        ({"org": "org-other"}, "TENANT_GATE_REJECTED"),
        ({"repository": "acme/other"}, "REPOSITORY_GATE_REJECTED"),
        ({"version_valid": False}, "VERSION_GATE_REJECTED"),
        ({"servable": False}, "QUARANTINE_GATE_REJECTED"),
    ],
)
def test_single_safety_gate_failure_has_an_explicit_final_reason(
    record_kwargs, expected_reason
):
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    record = _record(
        "unsafe",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected operator numpy.add",
        **record_kwargs,
    )
    decision = TriMemoryRetriever(
        InMemoryMemoryGraphStore({
            MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [record]),
        }),
        selection_mode="FORCED_SAFE_TOP1",
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert decision.injections == ()
    assert decision.decision_telemetry[0]["final_reason_code"] == expected_reason


def test_semantic_provenance_gate_failure_has_an_explicit_final_reason():
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)
    record = _record(
        "unverified",
        MemoryKind.USER_SEMANTIC,
        "Array __radd__ reflected operator numpy.add",
        verified=False,
    )
    decision = TriMemoryRetriever(
        InMemoryMemoryGraphStore({
            MemoryKind.USER_SEMANTIC: _snapshot(MemoryKind.USER_SEMANTIC, [record]),
        }),
        selection_mode="FORCED_SAFE_TOP1",
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    row = next(
        item for item in decision.decision_telemetry
        if item["bank_type"] == "USER_SEMANTIC"
    )
    assert row["final_reason_code"] == "PROVENANCE_GATE_REJECTED"


def test_diagnostic_safe_pool_accepts_only_complete_canonical_metadata():
    graph, node = _path_graph()
    record = _record(
        "safe-history",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected addition",
        version="b" * 40,
        metadata=_safe_pool_metadata(),
    )
    decision = TriMemoryRetriever(
        InMemoryMemoryGraphStore({
            MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [record]),
        }),
        embedder=_ZeroEmbedder(),
        selection_mode="FORCED_SAFE_TOP1",
        diagnostic_telemetry=True,
        require_safe_pool_metadata=True,
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert [item.memory_id for item in decision.injections] == ["safe-history"]
    assert decision.decision_telemetry[0]["final_reason_code"] == "INJECTED"
    assert decision.decision_telemetry[0]["subtask_id"] == node.node_id


@pytest.mark.parametrize(
    ("path_scope", "expected_reason", "expected_injections"),
    [
        ("**", "INJECTED", 1),
        ("src/", "PATH_GATE_REJECTED", 0),
    ],
)
def test_diagnostic_repository_wide_path_scope_does_not_require_optional_file_hints(
    path_scope, expected_reason, expected_injections
):
    graph = ShortTermWorkingGraph(
        "target-task", "Fix reflected addition", "acme/math"
    )
    node = graph.add_subtask(
        SubtaskSpec(
            node_id="edit-reflected",
            objective="fix the reflected addition implementation",
            operation="REPLACE_DELEGATION",
            symbols=("Array.__radd__",),
        )
    )
    graph.activate(node.node_id)
    record = _record(
        "safe-history",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected addition",
        version="b" * 40,
        metadata=_safe_pool_metadata(path_scope=path_scope),
    )
    decision = TriMemoryRetriever(
        InMemoryMemoryGraphStore(
            {MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [record])}
        ),
        embedder=_ZeroEmbedder(),
        selection_mode="FORCED_SAFE_TOP1",
        diagnostic_telemetry=True,
        require_safe_pool_metadata=True,
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert len(decision.injections) == expected_injections
    assert decision.decision_telemetry[0]["final_reason_code"] == expected_reason


@pytest.mark.parametrize(
    ("metadata_override", "record_override", "expected_reason"),
    [
        ({"permission_scope": None}, {}, "PERMISSION_GATE_REJECTED"),
        ({"tenant_scope": None}, {}, "TENANT_GATE_REJECTED"),
        ({"source_repository": ""}, {}, "REPOSITORY_GATE_REJECTED"),
        ({"path_scope": "tests/"}, {}, "PATH_GATE_REJECTED"),
        ({"source_commit": "c" * 40}, {}, "VERSION_GATE_REJECTED"),
        ({"provenance_sha256": None}, {}, "PROVENANCE_GATE_REJECTED"),
        ({"payload_sha256": None}, {}, "CANONICAL_GATE_REJECTED"),
        ({"quarantined": True}, {}, "QUARANTINE_GATE_REJECTED"),
        ({"target_derived": True}, {}, "LEAKAGE_GATE_REJECTED"),
        ({"source_task_id": "target-task"}, {}, "LEAKAGE_GATE_REJECTED"),
    ],
)
def test_diagnostic_safe_pool_gates_fail_closed_with_explicit_reason(
    metadata_override, record_override, expected_reason
):
    graph, _ = _path_graph()
    record = _record(
        "unsafe-history",
        MemoryKind.EPISODIC,
        "Array __radd__ reflected addition",
        version="b" * 40,
        metadata=_safe_pool_metadata(**metadata_override),
        **record_override,
    )
    decision = TriMemoryRetriever(
        InMemoryMemoryGraphStore({
            MemoryKind.EPISODIC: _snapshot(MemoryKind.EPISODIC, [record]),
        }),
        selection_mode="FORCED_SAFE_TOP1",
        diagnostic_telemetry=True,
        require_safe_pool_metadata=True,
    ).recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    )

    assert decision.injections == ()
    assert decision.decision_telemetry[0]["final_reason_code"] == expected_reason


def test_diagnostic_safe_pool_mode_requires_explicit_telemetry_opt_in():
    with pytest.raises(RecallError, match="requires diagnostic telemetry"):
        TriMemoryRetriever(
            InMemoryMemoryGraphStore(), require_safe_pool_metadata=True
        )


def test_current_manifest_is_unchanged_and_forced_manifest_names_the_mode():
    store = InMemoryMemoryGraphStore()
    current = TriMemoryRetriever(store)
    forced = TriMemoryRetriever(store, selection_mode="FORCED_SAFE_TOP1")
    graph, locate, _ = _graph()
    graph.activate(locate.node_id)

    assert set(current.manifest()) == {"config", "embedder", "algorithm"}
    assert current.recall(
        graph,
        RetrievalSessionState(graph.task_id),
        user_id="alice",
        org_id="org-1",
        repository="acme/math",
    ).decision_telemetry == ()
    assert forced.manifest()["selection_mode"] == "FORCED_SAFE_TOP1"
    assert forced.manifest()["diagnostic_telemetry_schema"] == (
        "trimem/recall-decision-telemetry/1.0"
    )
    with pytest.raises(RecallError, match="unsupported recall selection mode"):
        TriMemoryRetriever(store, selection_mode="DQN_USE")
    with pytest.raises(RecallError, match="not manifest-bound"):
        current.recall(
            graph,
            RetrievalSessionState(graph.task_id),
            user_id="alice",
            org_id="org-1",
            repository="acme/math",
            selection_mode="FORCED_SAFE_TOP1",
        )
