"""Credential-free reference store for the canonical TriMem graph schema.

This store is intentionally small and strict.  It mirrors the PostgreSQL
partition invariants closely enough for deterministic replay/E2E tests, but it
is not a substitute for the PostgreSQL repository used in production.  In
particular, a missing record and a record owned by another user are reported in
the same way so callers cannot use this API as an ownership oracle.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Dict, List, Optional, Tuple

from .schema import (
    AccessContext,
    DEFAULT_NAMESPACE,
    EdgeType,
    GraphCheckpoint,
    GraphEdge,
    GraphKind,
    GraphNode,
    GraphState,
    LifecycleState,
    MemoryAccessEvent,
    MemoryGraph,
    NodeType,
    PolicyTransition,
    PRIVATE_GRAPH_KINDS,
    SEMANTIC_GRAPH_KINDS,
    SemanticStrength,
    SemanticSupport,
    VectorIndexMetadata,
)


class TriMemStoreError(RuntimeError):
    """Base class for store failures."""


class ScopeViolation(TriMemStoreError):
    """A write attempted to cross an organisation or private-owner boundary."""


class IntegrityViolation(TriMemStoreError):
    """A record conflicts with canonical graph integrity."""


class NotFound(TriMemStoreError):
    """A record is absent or is deliberately hidden by its scope."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class InMemoryTriMemStore:
    """Deterministic, thread-safe in-memory implementation of graph storage.

    All public operations require an :class:`AccessContext`.  Private working,
    episodic, and user-semantic records are visible only to their owner even
    when another caller belongs to the same organisation.  Reviewed
    organisation-semantic records are visible throughout that organisation.
    """

    _STRUCTURAL_EDGE_TYPES = frozenset({EdgeType.DECOMPOSES_TO, EdgeType.DEPENDS_ON})

    def __init__(
        self, *, namespace: str = DEFAULT_NAMESPACE, clock: Callable[[], str] = _utc_now
    ):
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("namespace is required")
        self.namespace = namespace
        self._clock = clock
        self._lock = RLock()
        self._graphs: Dict[Tuple[str, str], MemoryGraph] = {}
        self._nodes: Dict[Tuple[str, str], GraphNode] = {}
        self._edges: Dict[Tuple[str, str], GraphEdge] = {}
        self._supports: Dict[Tuple[str, str], SemanticSupport] = {}
        self._access_events: Dict[Tuple[str, str], MemoryAccessEvent] = {}
        self._checkpoints: Dict[Tuple[str, str], GraphCheckpoint] = {}
        self._transitions: Dict[Tuple[str, str], PolicyTransition] = {}
        self._strengths: Dict[Tuple[str, str], SemanticStrength] = {}

    def _visible(self, ctx: AccessContext, *, org_id: str, namespace: str,
                 graph_kind: GraphKind, owner_user_id: Optional[str]) -> bool:
        if org_id != ctx.org_id or namespace != self.namespace:
            return False
        return graph_kind not in PRIVATE_GRAPH_KINDS or owner_user_id == ctx.user_id

    def _require_write_scope(self, ctx: AccessContext, *, org_id: str, namespace: str,
                             graph_kind: GraphKind, owner_user_id: Optional[str]) -> None:
        if org_id != ctx.org_id:
            raise ScopeViolation("organisation boundary violation")
        if namespace != self.namespace:
            raise ScopeViolation("memory namespace boundary violation")
        if graph_kind in PRIVATE_GRAPH_KINDS and owner_user_id != ctx.user_id:
            raise ScopeViolation("private memory owner boundary violation")
        if graph_kind == GraphKind.ORGANISATION_SEMANTIC and owner_user_id is not None:
            raise ScopeViolation("organisation semantic memory cannot have a private owner")

    @staticmethod
    def _same_partition(record, graph: MemoryGraph) -> bool:
        return (
            record.graph_id == graph.graph_id
            and record.org_id == graph.org_id
            and record.namespace == graph.namespace
            and record.graph_kind == graph.kind
            and record.owner_user_id == graph.owner_user_id
        )

    @staticmethod
    def _put_immutable(mapping: Dict, key, value, *, label: str):
        existing = mapping.get(key)
        if existing is not None:
            if existing.content_hash != value.content_hash:
                raise IntegrityViolation("%s identifier is already bound" % label)
            return deepcopy(existing)
        mapping[key] = deepcopy(value)
        return deepcopy(value)

    def _graph_for_access(self, ctx: AccessContext, graph_id: str) -> MemoryGraph:
        graph = self._graphs.get((ctx.org_id, graph_id))
        if graph is None or not self._visible(
            ctx,
            org_id=graph.org_id,
            namespace=graph.namespace,
            graph_kind=graph.kind,
            owner_user_id=graph.owner_user_id,
        ):
            raise NotFound("graph not found")
        return graph

    def _graph_for_write(self, ctx: AccessContext, graph_id: str) -> MemoryGraph:
        graph = self._graph_for_access(ctx, graph_id)
        if graph.state != GraphState.ACTIVE:
            raise IntegrityViolation("graph is not active")
        return graph

    def put_graph(self, ctx: AccessContext, graph: MemoryGraph) -> MemoryGraph:
        self._require_write_scope(
            ctx, org_id=graph.org_id, namespace=graph.namespace,
            graph_kind=graph.kind, owner_user_id=graph.owner_user_id
        )
        if not graph.verify_hash():
            raise IntegrityViolation("graph content hash is invalid")
        with self._lock:
            return self._put_immutable(
                self._graphs, (graph.org_id, graph.graph_id), graph, label="graph"
            )

    def get_graph(self, ctx: AccessContext, graph_id: str) -> MemoryGraph:
        with self._lock:
            graph = self._graphs.get((ctx.org_id, graph_id))
            if graph is None or not self._visible(
                ctx,
                org_id=graph.org_id,
                namespace=graph.namespace,
                graph_kind=graph.kind,
                owner_user_id=graph.owner_user_id,
            ):
                raise NotFound("graph not found")
            return deepcopy(graph)

    def list_graphs(self, ctx: AccessContext, *, kind: Optional[GraphKind] = None) -> List[MemoryGraph]:
        with self._lock:
            result = [
                deepcopy(graph)
                for graph in self._graphs.values()
                if (kind is None or graph.kind == kind)
                and self._visible(
                    ctx,
                    org_id=graph.org_id,
                    namespace=graph.namespace,
                    graph_kind=graph.kind,
                    owner_user_id=graph.owner_user_id,
                )
            ]
        return sorted(result, key=lambda graph: (graph.temporal.ingested_at, graph.graph_id))

    def set_graph_state(
        self, ctx: AccessContext, graph_id: str, state: GraphState
    ) -> MemoryGraph:
        """Advance graph lifecycle without permitting partition or hash rewrites."""
        if not isinstance(state, GraphState):
            raise ValueError("invalid graph state")
        allowed = {
            GraphState.ACTIVE: {GraphState.SEALED, GraphState.ARCHIVED},
            GraphState.SEALED: {GraphState.ARCHIVED},
            GraphState.ARCHIVED: set(),
        }
        with self._lock:
            graph = self._graph_for_access(ctx, graph_id)
            self._require_write_scope(
                ctx,
                org_id=graph.org_id,
                namespace=graph.namespace,
                graph_kind=graph.kind,
                owner_user_id=graph.owner_user_id,
            )
            if state == graph.state:
                return deepcopy(graph)
            if state not in allowed[graph.state]:
                raise IntegrityViolation("graph lifecycle cannot move backwards")
            replacement = replace(graph, state=state, content_hash="")
            self._graphs[(graph.org_id, graph.graph_id)] = replacement
            return deepcopy(replacement)

    def put_node(self, ctx: AccessContext, node: GraphNode) -> GraphNode:
        self._require_write_scope(
            ctx, org_id=node.org_id, namespace=node.namespace,
            graph_kind=node.graph_kind, owner_user_id=node.owner_user_id
        )
        if not node.verify_hash():
            raise IntegrityViolation("node content hash is invalid")
        with self._lock:
            graph = self._graph_for_write(ctx, node.graph_id)
            if not self._same_partition(node, graph):
                raise IntegrityViolation("node partition does not match graph header")
            return self._put_immutable(self._nodes, (node.org_id, node.node_id), node, label="node")

    def get_node(self, ctx: AccessContext, node_id: str) -> GraphNode:
        with self._lock:
            node = self._nodes.get((ctx.org_id, node_id))
            if node is None or not self._visible(
                ctx,
                org_id=node.org_id,
                namespace=node.namespace,
                graph_kind=node.graph_kind,
                owner_user_id=node.owner_user_id,
            ):
                raise NotFound("node not found")
            return deepcopy(node)

    def list_nodes(
        self,
        ctx: AccessContext,
        *,
        graph_id: Optional[str] = None,
        node_type: Optional[NodeType] = None,
        include_archived: bool = False,
    ) -> List[GraphNode]:
        with self._lock:
            result = [
                deepcopy(node)
                for node in self._nodes.values()
                if (graph_id is None or node.graph_id == graph_id)
                and (node_type is None or node.node_type == node_type)
                and (include_archived or node.lifecycle_state == LifecycleState.ACTIVE)
                and self._visible(
                    ctx,
                    org_id=node.org_id,
                    namespace=node.namespace,
                    graph_kind=node.graph_kind,
                    owner_user_id=node.owner_user_id,
                )
            ]
        return sorted(result, key=lambda node: (node.temporal.ingested_at, node.node_id))

    def _would_create_cycle(self, candidate: GraphEdge) -> bool:
        if candidate.edge_type not in self._STRUCTURAL_EDGE_TYPES:
            return False
        adjacency: Dict[str, List[str]] = {}
        for edge in self._edges.values():
            if (
                edge.org_id == candidate.org_id
                and edge.graph_id == candidate.graph_id
                and edge.lifecycle_state == LifecycleState.ACTIVE
                and edge.edge_type in self._STRUCTURAL_EDGE_TYPES
            ):
                adjacency.setdefault(edge.source_node_id, []).append(edge.target_node_id)
        adjacency.setdefault(candidate.source_node_id, []).append(candidate.target_node_id)
        frontier = [candidate.target_node_id]
        visited = set()
        while frontier:
            current = frontier.pop()
            if current == candidate.source_node_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            frontier.extend(adjacency.get(current, ()))
        return False

    def put_edge(self, ctx: AccessContext, edge: GraphEdge) -> GraphEdge:
        self._require_write_scope(
            ctx, org_id=edge.org_id, namespace=edge.namespace,
            graph_kind=edge.graph_kind, owner_user_id=edge.owner_user_id
        )
        if not edge.verify_hash():
            raise IntegrityViolation("edge content hash is invalid")
        with self._lock:
            graph = self._graph_for_write(ctx, edge.graph_id)
            if not self._same_partition(edge, graph):
                raise IntegrityViolation("edge partition does not match graph header")
            source = self._nodes.get((edge.org_id, edge.source_node_id))
            target = self._nodes.get((edge.org_id, edge.target_node_id))
            if source is None or target is None:
                raise IntegrityViolation("edge endpoint does not exist")
            if not self._same_partition(source, graph) or not self._same_partition(target, graph):
                raise IntegrityViolation("edge endpoint crosses a graph partition")
            existing = self._edges.get((edge.org_id, edge.edge_id))
            if existing is None and self._would_create_cycle(edge):
                raise IntegrityViolation("structural edge would create a cycle")
            return self._put_immutable(self._edges, (edge.org_id, edge.edge_id), edge, label="edge")

    def list_edges(self, ctx: AccessContext, *, graph_id: Optional[str] = None) -> List[GraphEdge]:
        with self._lock:
            result = [
                deepcopy(edge)
                for edge in self._edges.values()
                if (graph_id is None or edge.graph_id == graph_id)
                and edge.lifecycle_state == LifecycleState.ACTIVE
                and self._visible(
                    ctx,
                    org_id=edge.org_id,
                    namespace=edge.namespace,
                    graph_kind=edge.graph_kind,
                    owner_user_id=edge.owner_user_id,
                )
            ]
        return sorted(result, key=lambda edge: (edge.temporal.ingested_at, edge.edge_id))

    def put_support(self, ctx: AccessContext, support: SemanticSupport) -> SemanticSupport:
        self._require_write_scope(
            ctx,
            org_id=support.org_id,
            namespace=support.namespace,
            graph_kind=support.graph_kind,
            owner_user_id=support.owner_user_id,
        )
        if not support.verify_hash():
            raise IntegrityViolation("support content hash is invalid")
        with self._lock:
            graph = self._graph_for_write(ctx, support.semantic_graph_id)
            if (
                graph.kind not in SEMANTIC_GRAPH_KINDS
                or support.org_id != graph.org_id
                or support.namespace != graph.namespace
                or support.graph_kind != graph.kind
                or support.owner_user_id != graph.owner_user_id
            ):
                raise IntegrityViolation("support partition does not match semantic graph")
            node = self._nodes.get((support.org_id, support.semantic_node_id))
            if node is None or node.graph_id != graph.graph_id or node.node_type != NodeType.SEMANTIC_RULE:
                raise IntegrityViolation("support target must be a SemanticRule in its graph")
            if support.source_episode_id is not None:
                episode = self._nodes.get((support.org_id, support.source_episode_id))
                if (
                    episode is None
                    or episode.namespace != self.namespace
                    or episode.graph_kind != GraphKind.USER_EPISODIC
                    or episode.node_type != NodeType.EPISODE
                    or episode.owner_user_id != ctx.user_id
                ):
                    raise IntegrityViolation("support source episode is unavailable")
                if episode.payload_hash != support.source_evidence_hash:
                    raise IntegrityViolation("support evidence hash does not match source episode")
            return self._put_immutable(
                self._supports, (support.org_id, support.support_id), support, label="support"
            )

    def list_supports(
        self, ctx: AccessContext, *, semantic_node_id: Optional[str] = None
    ) -> List[SemanticSupport]:
        with self._lock:
            result = [
                deepcopy(support)
                for support in self._supports.values()
                if (semantic_node_id is None or support.semantic_node_id == semantic_node_id)
                and self._visible(
                    ctx,
                    org_id=support.org_id,
                    namespace=support.namespace,
                    graph_kind=support.graph_kind,
                    owner_user_id=support.owner_user_id,
                )
            ]
        return sorted(result, key=lambda support: (support.temporal.ingested_at, support.support_id))

    def append_access(self, ctx: AccessContext, event: MemoryAccessEvent) -> MemoryAccessEvent:
        if event.actor_user_id != ctx.user_id:
            raise ScopeViolation("access actor must match the access context")
        self._require_write_scope(
            ctx, org_id=event.org_id, namespace=event.namespace,
            graph_kind=event.graph_kind, owner_user_id=event.owner_user_id
        )
        if not event.verify_hash():
            raise IntegrityViolation("access event content hash is invalid")
        with self._lock:
            # Reading/injecting a reviewed sealed graph still needs an audit event;
            # only canonical graph mutation is restricted to ACTIVE graphs.
            graph = self._graph_for_access(ctx, event.graph_id)
            if not self._same_partition(event, graph):
                raise IntegrityViolation("access event partition does not match graph")
            node = self._nodes.get((event.org_id, event.node_id))
            if node is None or not self._same_partition(node, graph):
                raise IntegrityViolation("access event node does not exist in graph")
            return self._put_immutable(
                self._access_events, (event.org_id, event.event_id), event, label="access event"
            )

    def list_access_events(
        self, ctx: AccessContext, *, graph_id: Optional[str] = None, node_id: Optional[str] = None
    ) -> List[MemoryAccessEvent]:
        with self._lock:
            result = [
                deepcopy(event)
                for event in self._access_events.values()
                if (graph_id is None or event.graph_id == graph_id)
                and (node_id is None or event.node_id == node_id)
                and self._visible(
                    ctx,
                    org_id=event.org_id,
                    namespace=event.namespace,
                    graph_kind=event.graph_kind,
                    owner_user_id=event.owner_user_id,
                )
            ]
        return sorted(result, key=lambda event: (event.event_time, event.event_id))

    def save_checkpoint(self, ctx: AccessContext, checkpoint: GraphCheckpoint) -> GraphCheckpoint:
        if (
            checkpoint.org_id != ctx.org_id
            or checkpoint.namespace != self.namespace
            or checkpoint.owner_user_id != ctx.user_id
        ):
            raise ScopeViolation("checkpoint owner boundary violation")
        if not checkpoint.verify_hash():
            raise IntegrityViolation("checkpoint content hash is invalid")
        with self._lock:
            graph = self._graph_for_write(ctx, checkpoint.graph_id)
            if graph.kind != GraphKind.SHORT_TERM_WORKING:
                raise IntegrityViolation("checkpoints belong only to working graphs")
            prior = [
                item
                for item in self._checkpoints.values()
                if item.org_id == checkpoint.org_id
                and item.namespace == self.namespace
                and item.graph_id == checkpoint.graph_id
            ]
            if prior and checkpoint.sequence <= max(item.sequence for item in prior):
                existing = self._checkpoints.get((checkpoint.org_id, checkpoint.checkpoint_id))
                if existing is None or existing.content_hash != checkpoint.content_hash:
                    raise IntegrityViolation("checkpoint sequence must increase")
            return self._put_immutable(
                self._checkpoints,
                (checkpoint.org_id, checkpoint.checkpoint_id),
                checkpoint,
                label="checkpoint",
            )

    def list_checkpoints(self, ctx: AccessContext, *, graph_id: str) -> List[GraphCheckpoint]:
        # Authorize against the graph first; this also keeps hidden graphs non-disclosing.
        self.get_graph(ctx, graph_id)
        with self._lock:
            result = [
                deepcopy(item)
                for item in self._checkpoints.values()
                if item.org_id == ctx.org_id
                and item.namespace == self.namespace
                and item.graph_id == graph_id
                and item.owner_user_id == ctx.user_id
            ]
        return sorted(result, key=lambda item: (item.sequence, item.checkpoint_id))

    def record_policy_transition(
        self, ctx: AccessContext, transition: PolicyTransition
    ) -> PolicyTransition:
        if (
            transition.org_id != ctx.org_id
            or transition.namespace != self.namespace
            or transition.owner_user_id != ctx.user_id
        ):
            raise ScopeViolation("policy transition owner boundary violation")
        if not transition.verify_hash():
            raise IntegrityViolation("policy transition content hash is invalid")
        with self._lock:
            graph = self._graph_for_write(ctx, transition.graph_id)
            if graph.kind != GraphKind.SHORT_TERM_WORKING:
                raise IntegrityViolation("memory-policy transitions originate in a working graph")
            node = self._nodes.get((transition.org_id, transition.candidate_node_id))
            if node is None or not self._same_partition(node, graph):
                raise IntegrityViolation("policy candidate does not exist in working graph")
            return self._put_immutable(
                self._transitions,
                (transition.org_id, transition.transition_id),
                transition,
                label="policy transition",
            )

    def list_policy_transitions(
        self, ctx: AccessContext, *, graph_id: Optional[str] = None
    ) -> List[PolicyTransition]:
        with self._lock:
            result = [
                deepcopy(item)
                for item in self._transitions.values()
                if item.org_id == ctx.org_id
                and item.namespace == self.namespace
                and item.owner_user_id == ctx.user_id
                and (graph_id is None or item.graph_id == graph_id)
            ]
        return sorted(result, key=lambda item: (item.event_time, item.transition_id))

    def archive_episodic_fifo(
        self,
        ctx: AccessContext,
        *,
        capacity: int,
        graph_id: Optional[str] = None,
        archived_at: Optional[str] = None,
    ) -> List[GraphNode]:
        """Archive oldest private Episode nodes while retaining provenance hashes."""
        if capacity < 0:
            raise ValueError("capacity must be non-negative")
        at = archived_at or self._clock()
        with self._lock:
            eligible = [
                node
                for node in self._nodes.values()
                if node.org_id == ctx.org_id
                and node.namespace == self.namespace
                and node.owner_user_id == ctx.user_id
                and node.graph_kind == GraphKind.USER_EPISODIC
                and node.node_type == NodeType.EPISODE
                and node.lifecycle_state == LifecycleState.ACTIVE
                and (graph_id is None or node.graph_id == graph_id)
            ]
            eligible.sort(
                key=lambda node: (node.temporal.event_time or node.temporal.ingested_at, node.node_id)
            )
            archived = []
            for node in eligible[:max(0, len(eligible) - capacity)]:
                replacement = node.archived(at, "episodic_fifo_capacity")
                self._nodes[(node.org_id, node.node_id)] = replacement
                archived.append(deepcopy(replacement))
            return archived

    def set_semantic_strength(
        self, ctx: AccessContext, node_id: str, strength: SemanticStrength
    ) -> SemanticStrength:
        if not isinstance(strength, SemanticStrength):
            raise TypeError("strength must be SemanticStrength")
        with self._lock:
            node = self._nodes.get((ctx.org_id, node_id))
            if node is None or not self._visible(
                ctx,
                org_id=node.org_id,
                namespace=node.namespace,
                graph_kind=node.graph_kind,
                owner_user_id=node.owner_user_id,
            ):
                raise NotFound("node not found")
            if node.graph_kind not in SEMANTIC_GRAPH_KINDS or node.node_type != NodeType.SEMANTIC_RULE:
                raise IntegrityViolation("semantic strength applies only to SemanticRule nodes")
            self._strengths[(node.org_id, node.node_id)] = deepcopy(strength)
            return deepcopy(strength)

    def archive_weakest_semantic(
        self,
        ctx: AccessContext,
        *,
        capacity: int,
        graph_id: Optional[str] = None,
        archived_at: Optional[str] = None,
    ) -> List[GraphNode]:
        """Archive lowest-strength semantic rules with deterministic tie-breaking."""
        if capacity < 0:
            raise ValueError("capacity must be non-negative")
        at = archived_at or self._clock()
        with self._lock:
            eligible = [
                node
                for node in self._nodes.values()
                if node.org_id == ctx.org_id
                and node.namespace == self.namespace
                # Automatic strength eviction is private-only.  Shared semantic
                # lifecycle changes remain on the reviewed governance path.
                and node.graph_kind == GraphKind.USER_SEMANTIC
                and node.node_type == NodeType.SEMANTIC_RULE
                and node.lifecycle_state == LifecycleState.ACTIVE
                and (graph_id is None or node.graph_id == graph_id)
                and self._visible(
                    ctx,
                    org_id=node.org_id,
                    namespace=node.namespace,
                    graph_kind=node.graph_kind,
                    owner_user_id=node.owner_user_id,
                )
            ]
            eligible.sort(
                key=lambda node: (
                    self._strengths.get((node.org_id, node.node_id), SemanticStrength()).score,
                    node.temporal.last_verified_at or node.temporal.ingested_at,
                    node.node_id,
                )
            )
            archived = []
            for node in eligible[:max(0, len(eligible) - capacity)]:
                replacement = node.archived(at, "semantic_strength_capacity")
                self._nodes[(node.org_id, node.node_id)] = replacement
                archived.append(deepcopy(replacement))
            return archived

    def vector_metadata(
        self,
        ctx: AccessContext,
        node_id: str,
        *,
        embedding_model_id: Optional[str] = None,
        embedding_revision: Optional[str] = None,
        embedding_dimension: Optional[int] = None,
    ) -> VectorIndexMetadata:
        node = self.get_node(ctx, node_id)
        if node.lifecycle_state != LifecycleState.ACTIVE:
            raise IntegrityViolation("archived nodes are not indexable")
        if node.graph_kind == GraphKind.USER_EPISODIC and node.node_type != NodeType.EPISODE:
            raise IntegrityViolation("only Episode nodes are indexable from episodic memory")
        if node.graph_kind in SEMANTIC_GRAPH_KINDS and node.node_type != NodeType.SEMANTIC_RULE:
            raise IntegrityViolation("only SemanticRule nodes are indexable from semantic memory")
        return VectorIndexMetadata(
            graph_id=node.graph_id,
            node_id=node.node_id,
            org_id=node.org_id,
            namespace=node.namespace,
            memory_kind=node.graph_kind,
            canonical_content_hash=node.content_hash,
            owner_user_id=node.owner_user_id,
            repository_id=node.repository_id,
            collection_scope=(
                "shared" if node.graph_kind == GraphKind.ORGANISATION_SEMANTIC else "private"
            ),
            embedding_model_id=embedding_model_id,
            embedding_revision=embedding_revision,
            embedding_dimension=embedding_dimension,
        )
