"""Canonical PostgreSQL projection and Qdrant-shortlisted retrieval.

Qdrant supplies only untrusted references.  Every returned memory and topology
record is rebuilt from the canonical PostgreSQL rows before it can become a
retrieval snapshot.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Protocol

from .arms import CurrentV03MemoryController
from .ppr import GraphNode as PPRGraphNode, TextEmbedder
from .postgres_store import CanonicalReloadRows, PostgresTriMemStore
from .retrieval import (
    MemoryGraphSnapshot,
    MemoryInjection,
    MemoryKind,
    MemoryRecord,
    RecallDecision,
)
from .retrieval_store import (
    CanonicalProjectionError,
    CanonicalRetrievalStore,
    _edge_weight,
    _node_metadata,
    _search_text,
)
from .schema import AccessContext, GraphKind, MemoryAccessEvent, NodeType, canonical_hash
from .vector_index import QdrantVectorIndexV2, VectorSearchResult


_KIND_TO_GRAPH = {
    MemoryKind.EPISODIC: GraphKind.USER_EPISODIC,
    MemoryKind.USER_SEMANTIC: GraphKind.USER_SEMANTIC,
    MemoryKind.ORG_SEMANTIC: GraphKind.ORGANISATION_SEMANTIC,
}
_MEMORY_NODE = {
    MemoryKind.EPISODIC: NodeType.EPISODE,
    MemoryKind.USER_SEMANTIC: NodeType.SEMANTIC_RULE,
    MemoryKind.ORG_SEMANTIC: NodeType.SEMANTIC_RULE,
}
_ACCESS_EVENT_NAMESPACE = uuid.UUID("19a9ceca-9b89-44d3-b25a-5a40129cbc5a")


class AsyncBridge(Protocol):
    def call(self, awaitable): ...


def project_canonical_rows(
    rows: CanonicalReloadRows,
    kind: MemoryKind,
    *,
    user_id: str,
    org_id: str,
    repository: str,
    excluded_source_task_id: Optional[str] = None,
) -> MemoryGraphSnapshot:
    """Project hash-verified rows, retaining only Qdrant-shortlisted memories."""
    memory_kind = MemoryKind(kind)
    if rows.graph_kind != _KIND_TO_GRAPH[memory_kind]:
        raise CanonicalProjectionError("canonical reload returned the wrong memory bank")
    graphs = {item.graph_id: item for item in rows.graphs}
    candidate_ids = set(rows.candidate_node_ids)
    records: dict[str, MemoryRecord] = {}
    ppr_nodes: dict[str, PPRGraphNode] = {}
    weighted: dict[str, dict[str, float]] = {}
    included: set[str] = set()

    for graph in rows.graphs:
        if graph.namespace != rows.namespace:
            raise CanonicalProjectionError("graph crosses namespace partition")
        if not CanonicalRetrievalStore._eligible_graph(
            graph, memory_kind, user_id, org_id, repository
        ):
            continue
        CanonicalRetrievalStore._verify_record(graph, "graph")
        for node in sorted(
            (item for item in rows.nodes if item.graph_id == graph.graph_id),
            key=lambda item: item.node_id,
        ):
            if node.namespace != rows.namespace:
                raise CanonicalProjectionError("node crosses namespace partition")
            if not CanonicalRetrievalStore._eligible_node(
                node, graph, memory_kind, user_id, org_id, repository
            ):
                continue
            CanonicalRetrievalStore._verify_record(node, "node")
            is_memory = node.node_type == _MEMORY_NODE[memory_kind]
            if is_memory and node.node_id not in candidate_ids:
                continue
            projected = (
                CanonicalRetrievalStore._project_memory(node, graph, memory_kind)
                if is_memory else None
            )
            if is_memory and projected is None:
                continue
            if projected is not None and excluded_source_task_id:
                provenance = projected.metadata.get("provenance", {})
                if (
                    isinstance(provenance, Mapping)
                    and str(provenance.get("source_task_id", "")) == excluded_source_task_id
                ):
                    continue
            search_text = projected.retrieval_text if projected else _search_text(node.canonical_payload)
            if not search_text.strip():
                continue
            included.add(node.node_id)
            ppr_nodes[node.node_id] = PPRGraphNode(
                node.node_id, search_text, _node_metadata(node, graph)
            )
            if projected is not None:
                records[node.node_id] = projected

    for edge in rows.edges:
        graph = graphs.get(edge.graph_id)
        if graph is None or edge.namespace != rows.namespace:
            raise CanonicalProjectionError("edge crosses namespace partition")
        if edge.source_node_id not in included or edge.target_node_id not in included:
            continue
        if (
            edge.org_id != graph.org_id
            or edge.graph_kind != graph.kind
            or edge.owner_user_id != graph.owner_user_id
        ):
            raise CanonicalProjectionError("edge crosses canonical graph partition")
        CanonicalRetrievalStore._verify_record(edge, "edge")
        weight = _edge_weight(edge.metadata)
        if weight is not None:
            weighted.setdefault(edge.source_node_id, {})[edge.target_node_id] = weight

    adjacency: Mapping[str, Mapping[str, float]] = {
        node_id: {target: weight for target, weight in sorted(weighted.get(node_id, {}).items())}
        for node_id in sorted(ppr_nodes)
    }
    return MemoryGraphSnapshot(
        kind=memory_kind,
        records={key: records[key] for key in sorted(records)},
        nodes={key: ppr_nodes[key] for key in sorted(ppr_nodes)},
        adjacency=adjacency,
        graph_hash=canonical_hash({
            "schema": "trimem/postgres-qdrant-canonical-snapshot/1.0",
            "reload_digest": rows.digest,
            "candidate_node_ids": sorted(candidate_ids),
            "kind": memory_kind.value,
            "org_id": org_id,
            "user_id": user_id if memory_kind != MemoryKind.ORG_SEMANTIC else None,
            "repository": repository,
        }),
    )


class AsyncPostgresQdrantRetrievalStore:
    """Async candidate index → canonical reload → projection path."""

    def __init__(
        self,
        postgres: PostgresTriMemStore,
        vector_index: QdrantVectorIndexV2,
        embedder: TextEmbedder,
        *,
        candidate_limit: int = 64,
        excluded_source_task_id: Optional[str] = None,
        repository_id: Optional[str] = None,
        repository_alias: Optional[str] = None,
    ) -> None:
        if not isinstance(postgres, PostgresTriMemStore):
            raise TypeError("production retrieval requires PostgresTriMemStore")
        if not isinstance(vector_index, QdrantVectorIndexV2):
            raise TypeError("production retrieval requires QdrantVectorIndexV2")
        if postgres.namespace != vector_index.namespace:
            raise ValueError("canonical and vector namespaces differ")
        if type(candidate_limit) is not int or candidate_limit <= 0:
            raise ValueError("candidate_limit must be positive")
        self.postgres = postgres
        self.vector_index = vector_index
        self.embedder = embedder
        self.candidate_limit = candidate_limit
        self.excluded_source_task_id = excluded_source_task_id
        self.repository_id = repository_id
        self.repository_alias = repository_alias
        self.last_vector_result: Optional[VectorSearchResult] = None

    async def snapshot_for_query(
        self,
        kind: MemoryKind,
        *,
        user_id: str,
        org_id: str,
        repository: str,
        query_text: str,
    ) -> MemoryGraphSnapshot:
        memory_kind = MemoryKind(kind)
        graph_kind = _KIND_TO_GRAPH[memory_kind]
        owner = None if memory_kind == MemoryKind.ORG_SEMANTIC else user_id
        vector = self.embedder.embed(query_text)
        canonical_repository = self.repository_id or repository
        if self.repository_alias is not None and repository != self.repository_alias:
            raise ValueError("repository query does not match its canonical alias")
        result = self.vector_index.search(
            vector,
            org_id=org_id,
            owner_user_id=owner,
            memory_kind=graph_kind,
            repository_id=canonical_repository,
            limit=self.candidate_limit,
        )
        self.last_vector_result = result
        rows = await self.postgres.load_retrieval_rows(
            AccessContext(org_id=org_id, user_id=user_id),
            kind=graph_kind,
            repository_id=canonical_repository,
            references=tuple(hit.reference for hit in result.hits),
        )
        snapshot = project_canonical_rows(
            rows,
            memory_kind,
            user_id=user_id,
            org_id=org_id,
            repository=canonical_repository,
            excluded_source_task_id=self.excluded_source_task_id,
        )
        return _repository_alias(snapshot, canonical_repository, repository)


class AsyncPostgresCanonicalFullStore:
    """M1 canonical PostgreSQL reader; it deliberately performs no Qdrant/PPR lookup."""

    def __init__(
        self,
        postgres: PostgresTriMemStore,
        *,
        repository_id: Optional[str] = None,
        repository_alias: Optional[str] = None,
    ):
        if not isinstance(postgres, PostgresTriMemStore):
            raise TypeError("production retrieval requires PostgresTriMemStore")
        self.postgres = postgres
        self.namespace = postgres.namespace
        self.repository_id = repository_id
        self.repository_alias = repository_alias

    async def snapshot(
        self, kind: MemoryKind, *, user_id: str, org_id: str, repository: str
    ) -> MemoryGraphSnapshot:
        memory_kind = MemoryKind(kind)
        canonical_repository = self.repository_id or repository
        if self.repository_alias is not None and repository != self.repository_alias:
            raise ValueError("repository query does not match its canonical alias")
        rows = await self.postgres.load_retrieval_rows(
            AccessContext(org_id=org_id, user_id=user_id),
            kind=_KIND_TO_GRAPH[memory_kind],
            repository_id=canonical_repository,
            references=None,
        )
        snapshot = project_canonical_rows(
            rows, memory_kind, user_id=user_id, org_id=org_id,
            repository=canonical_repository,
        )
        return _repository_alias(snapshot, canonical_repository, repository)


def _repository_alias(
    snapshot: MemoryGraphSnapshot, canonical_repository: str, external_repository: str
) -> MemoryGraphSnapshot:
    if canonical_repository == external_repository:
        return snapshot
    records = {
        key: replace(item, repository=external_repository)
        if item.repository == canonical_repository else item
        for key, item in snapshot.records.items()
    }
    return replace(snapshot, records=records)


class SyncPostgresQdrantRetrievalStore:
    """Synchronous MemoryGraphStore facade using the session-owned loop."""

    def __init__(self, store: AsyncPostgresQdrantRetrievalStore, bridge: AsyncBridge):
        if not isinstance(store, AsyncPostgresQdrantRetrievalStore):
            raise TypeError("store must be AsyncPostgresQdrantRetrievalStore")
        if not callable(getattr(bridge, "call", None)):
            raise TypeError("bridge must expose call(awaitable)")
        self._store = store
        self._bridge = bridge
        self.namespace = store.postgres.namespace

    def snapshot_for_query(self, kind: MemoryKind, **kwargs) -> MemoryGraphSnapshot:
        return self._bridge.call(self._store.snapshot_for_query(kind, **kwargs))

    def snapshot(self, kind: MemoryKind, **kwargs) -> MemoryGraphSnapshot:
        raise RuntimeError("production retrieval requires an explicit active-subtask query")


class SyncPostgresCanonicalFullStore:
    def __init__(self, store: AsyncPostgresCanonicalFullStore, bridge: AsyncBridge):
        if not isinstance(store, AsyncPostgresCanonicalFullStore):
            raise TypeError("store must be AsyncPostgresCanonicalFullStore")
        if not callable(getattr(bridge, "call", None)):
            raise TypeError("bridge must expose call(awaitable)")
        self._store = store
        self._bridge = bridge
        self.namespace = store.namespace

    def snapshot(self, kind: MemoryKind, **kwargs) -> MemoryGraphSnapshot:
        return self._bridge.call(self._store.snapshot(kind, **kwargs))


class PostgresInjectionAuditor:
    """Persist exact injection bytes before a retrieval session can expose them."""

    def __init__(
        self,
        persistence: object,
        *,
        ctx: AccessContext,
        namespace: str,
        task_id: str,
        clock: Optional[Callable[[], str]] = None,
    ) -> None:
        method = getattr(persistence, "persist_access_events", None)
        if not callable(method):
            raise TypeError("persistence must expose persist_access_events")
        if not namespace or namespace == "unit-test":
            raise ValueError("production injection audit requires an exact namespace")
        if not task_id:
            raise ValueError("task_id is required")
        self.persistence = persistence
        self.ctx = ctx
        self.namespace = namespace
        self.task_id = task_id
        self.clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )

    def __call__(self, injections: tuple[MemoryInjection, ...]) -> None:
        events = []
        event_time = self.clock()
        for injection in injections:
            if not injection.verify():
                raise ValueError("injection byte evidence is invalid")
            if (
                injection.namespace != self.namespace
                or not injection.canonical_graph_id
                or not injection.canonical_node_hash.startswith("sha256:")
            ):
                raise ValueError("injection lacks canonical namespace/hash provenance")
            graph_kind = _KIND_TO_GRAPH[injection.kind]
            owner = None if graph_kind == GraphKind.ORGANISATION_SEMANTIC else self.ctx.user_id
            event_id = str(uuid.uuid5(
                _ACCESS_EVENT_NAMESPACE,
                "|".join((
                    self.namespace, self.task_id, injection.active_node_id,
                    injection.memory_id, injection.sha256,
                )),
            ))
            events.append(MemoryAccessEvent.injection(
                event_id=event_id,
                graph_id=injection.canonical_graph_id,
                node_id=injection.memory_id,
                org_id=self.ctx.org_id,
                namespace=self.namespace,
                graph_kind=graph_kind,
                owner_user_id=owner,
                actor_user_id=self.ctx.user_id,
                event_time=event_time,
                injected_bytes=injection.exact_utf8,
                evidence_ref="task:%s:active:%s:node-hash:%s" % (
                    self.task_id, injection.active_node_id, injection.canonical_node_hash
                ),
            ))
        active_node_ids = sorted({item.active_node_id for item in injections})
        operation_id = str(uuid.uuid5(
            _ACCESS_EVENT_NAMESPACE,
            "access-batch|%s|%s|%s" % (
                self.namespace,
                self.task_id,
                canonical_hash({
                    "event_ids": [item.event_id for item in events],
                    "event_hashes": [item.content_hash for item in events],
                }),
            ),
        ))
        stored = tuple(self.persistence.persist_access_events(
            self.ctx,
            tuple(events),
            operation_id=operation_id,
            operation_scope={
                "kind": "ACCESS",
                "task_id": self.task_id,
                "active_node_ids": active_node_ids,
            },
        ))
        if len(stored) != len(events):
            raise RuntimeError("canonical access audit did not persist every injection")


class AuditedMemoryController:
    """Rollback controller state when its PostgreSQL access audit cannot commit."""

    def __init__(self, delegate: object, auditor: PostgresInjectionAuditor):
        for method in ("recall", "context_for", "checkpoint_state", "restore"):
            if not callable(getattr(delegate, method, None)):
                raise TypeError("delegate lacks %s" % method)
        self.delegate = delegate
        self.auditor = auditor

    @property
    def content_hash(self) -> str:
        return self.delegate.content_hash

    def recall(self, graph, task):
        before = self.delegate.checkpoint_state()
        decision = self.delegate.recall(graph, task)
        try:
            if decision.injections:
                self.auditor(tuple(decision.injections))
        except BaseException:
            self.delegate.restore(before)
            raise
        return decision

    def context_for(self, active_node_id):
        return self.delegate.context_for(active_node_id)

    def checkpoint_state(self):
        return self.delegate.checkpoint_state()

    def restore(self, value):
        return self.delegate.restore(value)


def production_v03_controller_factory(
    *, task: object, canonical_store: PostgresTriMemStore,
    persistence: object, namespace: str, task_event_time: Optional[str] = None,
    identity_resolver: Optional[object] = None, lifecycle: Optional[object] = None,
    **_: object
) -> CurrentV03MemoryController:
    """Build M1 on the exact live-main validated-search/injection functions."""
    if identity_resolver is None:
        from .production_v03_lifecycle import PostgresTaskIdentityResolver

        identity_resolver = PostgresTaskIdentityResolver(canonical_store, persistence)
    if not callable(identity_resolver):
        raise TypeError("v0.3 identity_resolver is unavailable")
    identity = dict(identity_resolver(task))
    repository_id = str(identity.get("repository_id", ""))
    solve_job_id = str(identity.get("solve_job_id", ""))
    try:
        uuid.UUID(repository_id)
        uuid.UUID(solve_job_id)
    except (ValueError, AttributeError) as exc:
        raise TypeError("v0.3 stream identity requires repository/solve-job UUIDs") from exc
    runtime = getattr(lifecycle, "runtime", None)
    from .production_v03_lifecycle import (
        LIVE_V03_IMPLEMENTATION_MANIFEST,
        LiveV03Runtime,
    )

    if not isinstance(runtime, LiveV03Runtime):
        raise TypeError("M1 lifecycle has no exact live-v0.3 runtime")

    audit_evidence: dict[str, Mapping[str, object]] = {}

    def recall_once(observed_task, active_node_id: str) -> RecallDecision:
        if observed_task.task_id != task.task_id:
            raise ValueError("v0.3 recall task changed")
        result = runtime.recall_plan(task=observed_task, identity=identity)
        plan = result["plan"]
        audit = dict(result["audit"])
        audit_evidence["value"] = audit
        selected_candidates = sorted(
            (candidate for candidate in plan.candidates if candidate.injected),
            key=lambda candidate: int(candidate.injected_position),
        )
        injections = []
        for index, candidate in enumerate(selected_candidates):
            view = str(candidate.view_text)
            raw = view.encode("utf-8")
            next_score = (
                float(selected_candidates[index + 1].score)
                if index + 1 < len(selected_candidates)
                else 0.0
            )
            injections.append(
                MemoryInjection(
                    memory_id=str(candidate.canonical_version_id),
                    kind=(
                        MemoryKind.EPISODIC
                        if candidate.scope == "private"
                        else MemoryKind.ORG_SEMANTIC
                    ),
                    active_node_id="__TASK__",
                    exact_text=view,
                    exact_utf8=raw,
                    byte_count=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    confidence=float(candidate.score),
                    margin=float(candidate.score) - next_score,
                    graph_hash=str(audit["digest"]),
                    memory_version="1",
                    namespace=namespace,
                    canonical_graph_id="v03:%s:%s" % (
                        candidate.scope,
                        candidate.canonical_id,
                    ),
                    canonical_node_hash=str(candidate.content_hash),
                )
            )
        rejections = tuple(
            {
                "bank": "V03_%s" % str(candidate.scope).upper(),
                "memory_id": candidate.canonical_version_id,
                "reason": candidate.rejection_reason or "joint_rank_not_selected",
            }
            for candidate in plan.candidates
            if not candidate.injected
        )
        trace = ({
            "bank": "V03_LIVE_MAIN",
            "decision": "USE" if injections else "ABSTAIN",
            "source_commit": LIVE_V03_IMPLEMENTATION_MANIFEST["source_commit"],
            "validated_search_sha256": LIVE_V03_IMPLEMENTATION_MANIFEST[
                "validated_search_sha256"
            ],
            "plan_injection_sha256": LIVE_V03_IMPLEMENTATION_MANIFEST[
                "plan_injection_sha256"
            ],
            "candidate_count": len(plan.candidates),
            "injected_count": len(injections),
            "audit_digest": audit["digest"],
        },)
        return RecallDecision(
            active_node_id, tuple(injections), trace, rejections
        )

    def verify_audit(expected_digest: str) -> None:
        current = audit_evidence.get("value")
        if current is not None and current.get("digest") == expected_digest:
            runtime.verify_audit(org_id=str(task.org_id), evidence=current)
            return
        runtime.verify_audit_digest(
            org_id=str(task.org_id),
            solve_job_id=solve_job_id,
            expected_digest=expected_digest,
        )

    return CurrentV03MemoryController(
        recall_once,
        verify_audit,
        task_id=str(task.task_id),
        implementation_manifest=LIVE_V03_IMPLEMENTATION_MANIFEST,
    )


__all__ = [
    "AsyncPostgresQdrantRetrievalStore",
    "AsyncPostgresCanonicalFullStore",
    "AuditedMemoryController",
    "PostgresInjectionAuditor",
    "SyncPostgresQdrantRetrievalStore",
    "SyncPostgresCanonicalFullStore",
    "production_v03_controller_factory",
    "project_canonical_rows",
]
