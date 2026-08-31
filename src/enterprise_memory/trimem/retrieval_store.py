"""Authoritative canonical-store adapter for active-node memory retrieval.

The retrieval layer deliberately consumes this projection instead of accepting
vector-database payloads.  PostgreSQL-shaped canonical graph records (represented
by :class:`InMemoryTriMemStore` in credential-free runs) remain authoritative;
embeddings and PPR operate only on a deterministic, hash-bound snapshot of
those records.
"""
from __future__ import annotations

import math
from dataclasses import fields
from typing import Any, Mapping, Optional

from .ppr import GraphNode as PPRGraphNode
from .retrieval import MemoryGraphSnapshot, MemoryKind, MemoryRecord
from .schema import (
    AccessContext,
    GraphKind,
    GraphState,
    LifecycleState,
    MemoryGraph,
    NodeType,
    canonical_hash,
)
from .store import InMemoryTriMemStore


class CanonicalProjectionError(RuntimeError):
    """Canonical storage violated a partition or content-hash invariant."""


_KIND_MAP = {
    MemoryKind.EPISODIC: GraphKind.USER_EPISODIC,
    MemoryKind.USER_SEMANTIC: GraphKind.USER_SEMANTIC,
    MemoryKind.ORG_SEMANTIC: GraphKind.ORGANISATION_SEMANTIC,
}
_NODE_TYPE_MAP = {
    MemoryKind.EPISODIC: NodeType.EPISODE,
    MemoryKind.USER_SEMANTIC: NodeType.SEMANTIC_RULE,
    MemoryKind.ORG_SEMANTIC: NodeType.SEMANTIC_RULE,
}
_PRIVATE_KINDS = {MemoryKind.EPISODIC, MemoryKind.USER_SEMANTIC}
_SEARCH_FIELDS = (
    "retrieval_text", "objective", "repository", "path", "file", "symbol", "api",
    "error", "failing_test", "test", "predicted_operation", "operation", "name", "title",
    "summary", "version",
)
_PROJECTION_SCHEMA = "trimem/canonical-retrieval-snapshot/1.0"


class CanonicalRetrievalStore:
    """Project a canonical :class:`InMemoryTriMemStore` into retrieval snapshots.

    The constructor intentionally accepts no raw vector/Qdrant payload source.
    A different canonical backend can expose the same adapter only after it has
    an equivalent access-controlled record API and integrity checks.
    """

    def __init__(self, store: InMemoryTriMemStore):
        if not isinstance(store, InMemoryTriMemStore):
            raise TypeError("CanonicalRetrievalStore requires InMemoryTriMemStore authority")
        self._store = store

    def snapshot(self, kind: MemoryKind, *, user_id: str, org_id: str,
                 repository: str) -> MemoryGraphSnapshot:
        memory_kind = MemoryKind(kind)
        graph_kind = _KIND_MAP[memory_kind]
        context = AccessContext(org_id=org_id, user_id=user_id)
        graphs = self._store.list_graphs(context, kind=graph_kind)

        records: dict[str, MemoryRecord] = {}
        ppr_nodes: dict[str, PPRGraphNode] = {}
        weighted_edges: dict[str, dict[str, float]] = {}
        graph_seals: list[dict[str, str]] = []
        node_seals: list[dict[str, str]] = []
        edge_seals: list[dict[str, str]] = []

        for graph in sorted(graphs, key=lambda item: item.graph_id):
            if not self._eligible_graph(graph, memory_kind, user_id, org_id, repository):
                continue
            self._verify_record(graph, "graph")
            graph_seals.append({"graph_id": graph.graph_id, "content_hash": graph.content_hash})

            canonical_nodes = self._store.list_nodes(context, graph_id=graph.graph_id)
            included_ids: set[str] = set()
            for node in sorted(canonical_nodes, key=lambda item: item.node_id):
                if not self._eligible_node(node, graph, memory_kind, user_id, org_id, repository):
                    continue
                self._verify_record(node, "node")
                is_memory = node.node_type == _NODE_TYPE_MAP[memory_kind]
                projected = self._project_memory(node, graph, memory_kind) if is_memory else None
                if is_memory and projected is None:
                    # A malformed memory payload is neither a candidate nor a
                    # PPR bridge.  This prevents topology from laundering it.
                    continue
                search_text = projected.retrieval_text if projected else _search_text(node.canonical_payload)
                if not search_text.strip():
                    continue
                included_ids.add(node.node_id)
                node_seals.append({"node_id": node.node_id, "content_hash": node.content_hash})
                metadata = _node_metadata(node, graph)
                ppr_nodes[node.node_id] = PPRGraphNode(node.node_id, search_text, metadata)
                if projected is not None:
                    records[node.node_id] = projected

            for edge in self._store.list_edges(context, graph_id=graph.graph_id):
                if edge.source_node_id not in included_ids or edge.target_node_id not in included_ids:
                    continue
                if (edge.org_id != graph.org_id or edge.graph_kind != graph.kind
                        or edge.owner_user_id != graph.owner_user_id):
                    raise CanonicalProjectionError("edge crosses its canonical graph partition")
                self._verify_record(edge, "edge")
                weight = _edge_weight(edge.metadata)
                if weight is None:
                    continue
                outgoing = weighted_edges.setdefault(edge.source_node_id, {})
                outgoing[edge.target_node_id] = outgoing.get(edge.target_node_id, 0.0) + weight
                edge_seals.append({"edge_id": edge.edge_id, "content_hash": edge.content_hash})

        adjacency = {
            node_id: {target_id: weighted_edges.get(node_id, {})[target_id]
                      for target_id in sorted(weighted_edges.get(node_id, {}))}
            for node_id in sorted(ppr_nodes)
        }
        partition_owner = user_id if memory_kind in _PRIVATE_KINDS else None
        snapshot_hash = canonical_hash({
            "schema": _PROJECTION_SCHEMA,
            "kind": memory_kind.value,
            "org_id": org_id,
            "owner_user_id": partition_owner,
            "repository": repository,
            "graphs": sorted(graph_seals, key=lambda row: row["graph_id"]),
            "nodes": sorted(node_seals, key=lambda row: row["node_id"]),
            "edges": sorted(edge_seals, key=lambda row: row["edge_id"]),
        })
        return MemoryGraphSnapshot(
            kind=memory_kind,
            records={memory_id: records[memory_id] for memory_id in sorted(records)},
            nodes={node_id: ppr_nodes[node_id] for node_id in sorted(ppr_nodes)},
            adjacency=adjacency,
            graph_hash=snapshot_hash,
        )

    @staticmethod
    def _eligible_graph(graph: MemoryGraph, kind: MemoryKind, user_id: str, org_id: str,
                        repository: str) -> bool:
        if graph.org_id != org_id or graph.kind != _KIND_MAP[kind]:
            return False
        if graph.state == GraphState.ARCHIVED:
            return False
        if kind in _PRIVATE_KINDS:
            if graph.owner_user_id != user_id:
                return False
        elif graph.owner_user_id is not None:
            return False
        if graph.repository_id is not None and graph.repository_id != repository:
            return False
        if kind == MemoryKind.EPISODIC and not graph.repository_id:
            return False
        if kind == MemoryKind.ORG_SEMANTIC:
            review = graph.review_provenance
            if review is None or not review.verify_hash():
                return False
        return True

    @staticmethod
    def _eligible_node(node, graph: MemoryGraph, kind: MemoryKind, user_id: str, org_id: str,
                       repository: str) -> bool:
        if node.lifecycle_state != LifecycleState.ACTIVE:
            return False
        if (node.graph_id != graph.graph_id or node.org_id != org_id or node.graph_kind != graph.kind
                or node.owner_user_id != graph.owner_user_id):
            raise CanonicalProjectionError("node crosses its canonical graph partition")
        if kind in _PRIVATE_KINDS and node.owner_user_id != user_id:
            return False
        if node.repository_id is not None and node.repository_id != repository:
            return False
        if graph.repository_id and node.repository_id and graph.repository_id != node.repository_id:
            raise CanonicalProjectionError("node repository conflicts with graph repository")
        if kind == MemoryKind.EPISODIC and not (node.repository_id or graph.repository_id):
            return False
        if kind == MemoryKind.ORG_SEMANTIC:
            review = node.review_provenance
            if review is None or not review.verify_hash():
                return False
        return True

    @staticmethod
    def _verify_record(record, label: str) -> None:
        if not record.verify_hash():
            raise CanonicalProjectionError("canonical %s content hash is invalid" % label)

    @staticmethod
    def _project_memory(node, graph: MemoryGraph, kind: MemoryKind) -> Optional[MemoryRecord]:
        payload = node.canonical_payload
        retrieval_text = payload.get("retrieval_text")
        execution_view = payload.get("execution_view")
        if not isinstance(retrieval_text, str) or not isinstance(execution_view, str):
            return None

        coverage_value = payload.get("coverage", ())
        coverage = _string_tuple(coverage_value)
        if coverage is None:
            return None
        quality = _unit_float(payload.get("quality", 0.0))
        completeness = _unit_float(payload.get("completeness", 0.0))
        if quality is None or completeness is None:
            return None

        repository = node.repository_id or graph.repository_id
        version_value = payload.get("version", payload.get("repository_version", "UNKNOWN"))
        version = version_value if isinstance(version_value, str) and version_value.strip() else "UNKNOWN"
        source_outcome = payload.get("source_outcome", "unknown")
        if not isinstance(source_outcome, str):
            source_outcome = "unknown"
        boolean_fields = {
            key: payload.get(key)
            for key in ("version_valid", "stale", "servable", "verified")
        }
        if any(not isinstance(value, bool) for value in boolean_fields.values()):
            return None
        node_reviewed = node.review_provenance is not None and node.review_provenance.verify_hash()
        graph_reviewed = graph.review_provenance is not None and graph.review_provenance.verify_hash()
        reviewed = node_reviewed and graph_reviewed if kind == MemoryKind.ORG_SEMANTIC else False

        metadata = _node_metadata(node, graph)
        provenance = payload.get("provenance")
        if isinstance(provenance, Mapping):
            metadata["provenance"] = dict(provenance)

        return MemoryRecord(
            memory_id=node.node_id,
            kind=kind,
            retrieval_text=retrieval_text,
            execution_view=execution_view,
            org_id=node.org_id,
            owner_user_id=node.owner_user_id,
            repository=repository,
            version=version,
            version_valid=boolean_fields["version_valid"] and version != "UNKNOWN",
            stale=boolean_fields["stale"],
            valid_from=node.temporal.valid_from,
            valid_until=node.temporal.valid_until,
            servable=(boolean_fields["servable"]
                      and node.lifecycle_state == LifecycleState.ACTIVE
                      and graph.state != GraphState.ARCHIVED),
            verified=boolean_fields["verified"],
            reviewed=reviewed,
            source_outcome=source_outcome,
            quality=quality,
            completeness=completeness,
            coverage=coverage,
            metadata=metadata,
        )


def _unit_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def _string_tuple(value: Any) -> Optional[tuple[str, ...]]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return None
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return None
    return tuple(sorted(set(item.strip() for item in value)))


def _search_text(payload: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in _SEARCH_FIELDS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        elif isinstance(value, (list, tuple)):
            parts.extend(item.strip() for item in value if isinstance(item, str) and item.strip())
    return "\n".join(dict.fromkeys(parts))


def _edge_weight(metadata: Mapping[str, Any]) -> Optional[float]:
    value = metadata.get("weight", 1.0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    weight = float(value)
    return weight if math.isfinite(weight) and weight > 0 else None


def _temporal_dict(temporal) -> dict[str, Any]:
    return {field.name: getattr(temporal, field.name) for field in fields(temporal)}


def _node_metadata(node, graph: MemoryGraph) -> dict[str, Any]:
    return {
        "authority": "canonical_graph_store",
        "namespace": graph.namespace,
        "graph_id": graph.graph_id,
        "graph_kind": graph.kind.value,
        "node_type": node.node_type.value,
        "canonical_graph_hash": graph.content_hash,
        "canonical_node_hash": node.content_hash,
        "canonical_payload_hash": node.payload_hash,
        "graph_review_provenance_hash": (
            graph.review_provenance.content_hash if graph.review_provenance else None),
        "node_review_provenance_hash": (
            node.review_provenance.content_hash if node.review_provenance else None),
        "temporal": _temporal_dict(node.temporal),
    }
