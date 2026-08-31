"""Async PostgreSQL repository for the canonical TriMem 0015 tables.

Every operation enters :func:`tenant_tx` with both organisation and user
context.  PostgreSQL FORCE RLS is the primary boundary; the explicit scope
predicate below is defence in depth and makes an absent ID indistinguishable
from another user's private ID.  Returned rows are rebuilt as canonical schema
objects and their deterministic content hashes are verified before release.
"""
from __future__ import annotations

import json
import math
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Sequence

from sqlalchemy import text

from ..persistence.tenant_context import tenant_tx
from .schema import (
    AccessContext,
    AccessType,
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
    OrganisationSemanticGraph,
    PolicyAction,
    PolicyActor,
    PolicyTransition,
    PRIVATE_GRAPH_KINDS,
    ReviewAuthority,
    ReviewProvenance,
    SEMANTIC_GRAPH_KINDS,
    SemanticStrength,
    SemanticStrengthRecord,
    SemanticSupport,
    ShortTermWorkingGraph,
    TemporalMetadata,
    UserEpisodicGraph,
    UserSemanticGraph,
    canonical_hash,
)
from .store import IntegrityViolation, NotFound, ScopeViolation
from .vector_index import VectorReference


class CanonicalReloadError(IntegrityViolation):
    """A PostgreSQL row failed canonical schema or hash verification."""


_CANONICAL_TABLES = (
    "trimem_graphs",
    "trimem_graph_nodes",
    "trimem_graph_edges",
    "trimem_semantic_supports",
    "trimem_memory_access_events",
    "trimem_graph_checkpoints",
    "trimem_policy_transitions",
    "trimem_semantic_strengths",
    "trimem_vector_index_outbox",
    "trimem_promotion_evidence",
    "trimem_lifecycle_operation_receipts",
)

_OUTBOX_ID_NAMESPACE = uuid.UUID("55fca334-1f48-4c56-88a2-6e40a4b9ea70")


@dataclass(frozen=True)
class LifecycleAppendBundle:
    operation_id: Optional[str] = None
    operation_scope: Optional[Mapping[str, Any]] = None
    graphs: tuple[MemoryGraph, ...] = ()
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    supports: tuple[SemanticSupport, ...] = ()
    transitions: tuple[PolicyTransition, ...] = ()
    checkpoints: tuple[GraphCheckpoint, ...] = ()
    strengths: tuple[SemanticStrengthRecord, ...] = ()
    strength_increments: tuple["SemanticStrengthIncrement", ...] = ()
    index_node_ids: tuple[str, ...] = ()
    capacity_limits: Optional["CapacityLimits"] = None
    capacity_archived_at: Optional[str] = None


@dataclass(frozen=True)
class SemanticStrengthIncrement:
    """One atomic, canonical downstream-reuse increment."""

    graph_id: str
    semantic_node_id: str
    org_id: str
    namespace: str
    graph_kind: GraphKind
    owner_user_id: Optional[str]
    successful_reuse: float = 0.0
    recent_verification: float = 0.0
    negative_transfer: float = 0.0
    contradiction: float = 0.0
    version_staleness: float = 0.0
    updated_at: str = ""

    def __post_init__(self) -> None:
        for name in ("graph_id", "semantic_node_id", "org_id", "namespace", "updated_at"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError("%s is required" % name)
        if self.graph_kind not in SEMANTIC_GRAPH_KINDS:
            raise ValueError("strength increments require a semantic graph")
        if self.graph_kind == GraphKind.USER_SEMANTIC and not self.owner_user_id:
            raise ValueError("user semantic strength increments require an owner")
        if self.graph_kind == GraphKind.ORGANISATION_SEMANTIC and self.owner_user_id is not None:
            raise ValueError("organisation semantic strength increments cannot have an owner")
        deltas = (
            self.successful_reuse,
            self.recent_verification,
            self.negative_transfer,
            self.contradiction,
            self.version_staleness,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
            for value in deltas
        ):
            raise ValueError("semantic strength increments must be finite and non-negative")


@dataclass(frozen=True)
class CapacityLimits:
    episodic_per_user: int = 100
    user_semantic_per_user: int = 100
    organisation_semantic: int = 1000

    def __post_init__(self) -> None:
        for name in (
            "episodic_per_user",
            "user_semantic_per_user",
            "organisation_semantic",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError("%s capacity must be a positive integer" % name)


@dataclass(frozen=True)
class AppendReceipt:
    namespace: str
    graph_hashes: tuple[tuple[str, str], ...]
    node_hashes: tuple[tuple[str, str], ...]
    index_nodes: tuple[GraphNode, ...]
    strength_hashes: tuple[tuple[str, str], ...] = ()
    index_intents: tuple["IndexOutboxIntent", ...] = ()
    delete_nodes: tuple[GraphNode, ...] = ()
    delete_intents: tuple["IndexOutboxIntent", ...] = ()
    archived_nodes: tuple[GraphNode, ...] = ()
    promotion_evidence: tuple["PromotionEvidence", ...] = ()
    canonical_row_deltas: Mapping[str, Mapping[str, int]] = field(
        default_factory=dict
    )
    replayed: bool = False


@dataclass(frozen=True)
class IndexOutboxIntent:
    intent_id: str
    org_id: str
    namespace: str
    graph_id: str
    graph_kind: GraphKind
    owner_user_id: Optional[str]
    node_id: str
    operation: str
    canonical_content_hash: str
    prior_content_hash: Optional[str]
    status: str
    attempts: int
    last_error: Optional[str]
    created_at: str
    updated_at: str
    indexed_at: Optional[str]


@dataclass(frozen=True)
class SessionCheckpoint:
    checkpoint_id: str
    org_id: str
    namespace: str
    owner_user_id: str
    run_nonce: str
    next_sequence_index: int
    checkpoint_schema: str
    checkpoint_payload: Mapping[str, Any]
    checkpoint_digest: str
    created_at: str


@dataclass(frozen=True)
class PromotionEvidence:
    evidence_id: str
    org_id: str
    namespace: str
    evidence_hash: str
    contributor_hash: str
    source_kind: str
    source_outcome: str
    verified: bool
    public_evidence_hash: str
    verifier_hash: str
    extraction_hash: str
    attestation_hash: str
    verified_at: str
    created_at: str


@dataclass(frozen=True)
class NamespaceClaim:
    namespace: str
    experiment_id: str
    split: str
    arm_id: str
    task_order_hash: str
    config_hash: str
    run_nonce: str
    next_sequence_index: int
    claim_status: str


@dataclass(frozen=True)
class NamespaceEvidence:
    namespace: str
    row_counts: tuple[tuple[str, int], ...]
    digest: str

    @property
    def is_empty(self) -> bool:
        return all(count == 0 for _, count in self.row_counts)


@dataclass(frozen=True)
class CanonicalReloadRows:
    namespace: str
    graph_kind: GraphKind
    graphs: tuple[MemoryGraph, ...]
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    candidate_node_ids: tuple[str, ...]
    digest: str


_SCOPE = (
    "org_id=:org_id AND namespace=:namespace AND "
    "(graph_kind='ORGANISATION_SEMANTIC' OR owner_user_id=:owner_user_id)"
)

_GRAPH_COLUMNS = """
id, org_id, namespace, graph_kind, owner_user_id, repository_id, solve_job_id,
graph_state, schema_version, ingested_at, event_time, source_available_at,
last_accessed_at, last_used_at, last_verified_at, valid_from, valid_until,
review_id, reviewer_id, reviewed_at, review_authority, review_policy_version,
review_evidence_hash, content_hash
""".strip()

_NODE_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, repository_id, node_type,
lifecycle_state, canonical_payload, payload_hash, archived_at, archive_reason,
archived_from_content_hash,
ingested_at, event_time, source_available_at, last_accessed_at, last_used_at,
last_verified_at, valid_from, valid_until, review_id, reviewer_id, reviewed_at,
review_authority, review_policy_version, review_evidence_hash, content_hash
""".strip()

_EDGE_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, edge_type, source_node_id,
target_node_id, lifecycle_state, metadata, ingested_at, event_time,
source_available_at, last_accessed_at, last_used_at, last_verified_at,
valid_from, valid_until, review_id, reviewer_id, reviewed_at, review_authority,
review_policy_version, review_evidence_hash, content_hash
""".strip()

_SUPPORT_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, semantic_node_id,
source_episode_id, source_evidence_hash, contributor_hash, ingested_at,
event_time, source_available_at, last_accessed_at, last_used_at,
last_verified_at, valid_from, valid_until, review_id, reviewer_id, reviewed_at,
review_authority, review_policy_version, review_evidence_hash, content_hash
""".strip()

_ACCESS_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, node_id, actor_user_id,
access_type, event_time, injected_byte_count, injected_hash, evidence_ref,
content_hash
""".strip()

_CHECKPOINT_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, sequence_no,
graph_content_hash, active_node_id, evidence_ref, evidence_hash, created_at,
content_hash
""".strip()

_TRANSITION_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, candidate_node_id, action,
actor, target_graph_kind, state_features_hash, reward, delayed_credit_ref,
event_time, content_hash
""".strip()

_STRENGTH_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, semantic_node_id,
support, successful_reuse, independent_user_evidence, recent_verification,
negative_transfer, contradiction, version_staleness, strength_score,
updated_at, content_hash
""".strip()

_CLAIM_COLUMNS = """
namespace, experiment_id, split, arm_id, task_order_hash, config_hash, run_nonce,
next_sequence_index, claim_status
""".strip()

_OUTBOX_COLUMNS = """
id, org_id, namespace, graph_id, graph_kind, owner_user_id, node_id,
operation, canonical_content_hash, prior_content_hash, status, attempts,
last_error, created_at, updated_at, indexed_at
""".strip()

_SESSION_CHECKPOINT_COLUMNS = """
id, org_id, namespace, owner_user_id, run_nonce, next_sequence_index,
checkpoint_schema, checkpoint_payload, checkpoint_digest, created_at
""".strip()

_PROMOTION_EVIDENCE_COLUMNS = """
id, org_id, namespace, evidence_hash, contributor_hash, source_kind,
source_outcome, verified, public_evidence_hash, verifier_hash, extraction_hash,
attestation_hash, verified_at, created_at
""".strip()


def _identifier(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _uuid_identifier(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError("%s must be a canonical UUID" % name)
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, ValueError) as exc:
        raise ValueError("%s must be a canonical UUID" % name) from exc
    canonical = str(parsed)
    if value != canonical:
        raise ValueError("%s must be a canonical UUID" % name)
    return canonical


def _timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        result = value.isoformat()
        if value.tzinfo is not None and value.utcoffset() == timezone.utc.utcoffset(value):
            result = result.replace("+00:00", "Z")
        return result
    raise ValueError("timestamp has unsupported representation")


def _postgres_timestamp(value: Any, name: str) -> Optional[datetime]:
    """Return an aware UTC ``datetime`` suitable for asyncpg TIMESTAMPTZ binds."""

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(
                value[:-1] + "+00:00" if value.endswith("Z") else value
            )
        except ValueError as exc:
            raise ValueError("%s must be an ISO-8601 timestamp" % name) from exc
    else:
        raise ValueError("%s has unsupported timestamp representation" % name)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("%s must include a timezone" % name)
    return parsed.astimezone(timezone.utc)


def _json_object(value: Any) -> Mapping[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("canonical JSON must be an object")
    return dict(value)


def _mapping(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    candidate = getattr(row, "_mapping", None)
    if isinstance(candidate, Mapping):
        return candidate
    raise ValueError("database row is not a mapping")


def _temporal(row: Mapping[str, Any]) -> TemporalMetadata:
    return TemporalMetadata(
        ingested_at=_timestamp(row["ingested_at"]),
        event_time=_timestamp(row.get("event_time")),
        source_available_at=_timestamp(row.get("source_available_at")),
        last_accessed_at=_timestamp(row.get("last_accessed_at")),
        last_used_at=_timestamp(row.get("last_used_at")),
        last_verified_at=_timestamp(row.get("last_verified_at")),
        valid_from=_timestamp(row.get("valid_from")),
        valid_until=_timestamp(row.get("valid_until")),
    )


def _review(row: Mapping[str, Any]) -> Optional[ReviewProvenance]:
    values = (
        row.get("review_id"),
        row.get("reviewer_id"),
        row.get("reviewed_at"),
        row.get("review_authority"),
        row.get("review_policy_version"),
        row.get("review_evidence_hash"),
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("partial review provenance")
    return ReviewProvenance(
        review_id=str(values[0]),
        reviewer_id=str(values[1]),
        reviewed_at=_timestamp(values[2]),
        authority=ReviewAuthority(values[3]),
        policy_version=str(values[4]),
        evidence_hash=str(values[5]),
    )


def _graph(row: Mapping[str, Any]) -> MemoryGraph:
    kind = GraphKind(row["graph_kind"])
    cls = {
        GraphKind.SHORT_TERM_WORKING: ShortTermWorkingGraph,
        GraphKind.USER_EPISODIC: UserEpisodicGraph,
        GraphKind.USER_SEMANTIC: UserSemanticGraph,
        GraphKind.ORGANISATION_SEMANTIC: OrganisationSemanticGraph,
    }[kind]
    return cls(
        graph_id=str(row["id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        owner_user_id=_identifier(row.get("owner_user_id")),
        repository_id=_identifier(row.get("repository_id")),
        solve_job_id=_identifier(row.get("solve_job_id")),
        state=GraphState(row["graph_state"]),
        schema_version=str(row["schema_version"]),
        temporal=_temporal(row),
        review_provenance=_review(row),
        content_hash=str(row["content_hash"]),
    )


def _node(row: Mapping[str, Any]) -> GraphNode:
    return GraphNode(
        node_id=str(row["id"]),
        graph_id=str(row["graph_id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        graph_kind=GraphKind(row["graph_kind"]),
        owner_user_id=_identifier(row.get("owner_user_id")),
        repository_id=_identifier(row.get("repository_id")),
        node_type=NodeType(row["node_type"]),
        lifecycle_state=LifecycleState(row["lifecycle_state"]),
        canonical_payload=_json_object(row["canonical_payload"]),
        payload_hash=str(row["payload_hash"]),
        archived_at=_timestamp(row.get("archived_at")),
        archive_reason=row.get("archive_reason"),
        archived_from_content_hash=row.get("archived_from_content_hash"),
        temporal=_temporal(row),
        review_provenance=_review(row),
        content_hash=str(row["content_hash"]),
    )


def _edge(row: Mapping[str, Any]) -> GraphEdge:
    return GraphEdge(
        edge_id=str(row["id"]),
        graph_id=str(row["graph_id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        graph_kind=GraphKind(row["graph_kind"]),
        owner_user_id=_identifier(row.get("owner_user_id")),
        edge_type=EdgeType(row["edge_type"]),
        source_node_id=str(row["source_node_id"]),
        target_node_id=str(row["target_node_id"]),
        lifecycle_state=LifecycleState(row["lifecycle_state"]),
        metadata=_json_object(row["metadata"]),
        temporal=_temporal(row),
        review_provenance=_review(row),
        content_hash=str(row["content_hash"]),
    )


def _support(row: Mapping[str, Any]) -> SemanticSupport:
    return SemanticSupport(
        support_id=str(row["id"]),
        semantic_graph_id=str(row["graph_id"]),
        semantic_node_id=str(row["semantic_node_id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        graph_kind=GraphKind(row["graph_kind"]),
        owner_user_id=_identifier(row.get("owner_user_id")),
        source_episode_id=_identifier(row.get("source_episode_id")),
        source_evidence_hash=str(row["source_evidence_hash"]),
        contributor_hash=row.get("contributor_hash"),
        temporal=_temporal(row),
        review_provenance=_review(row),
        content_hash=str(row["content_hash"]),
    )


def _access(row: Mapping[str, Any]) -> MemoryAccessEvent:
    return MemoryAccessEvent(
        event_id=str(row["id"]),
        graph_id=str(row["graph_id"]),
        node_id=str(row["node_id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        graph_kind=GraphKind(row["graph_kind"]),
        owner_user_id=_identifier(row.get("owner_user_id")),
        actor_user_id=str(row["actor_user_id"]),
        access_type=AccessType(row["access_type"]),
        event_time=_timestamp(row["event_time"]),
        injected_byte_count=int(row["injected_byte_count"]),
        injected_hash=row.get("injected_hash"),
        evidence_ref=row.get("evidence_ref"),
        content_hash=str(row["content_hash"]),
    )


def _checkpoint(row: Mapping[str, Any]) -> GraphCheckpoint:
    if GraphKind(row["graph_kind"]) != GraphKind.SHORT_TERM_WORKING:
        raise ValueError("checkpoint is not in a working graph")
    return GraphCheckpoint(
        checkpoint_id=str(row["id"]),
        graph_id=str(row["graph_id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        owner_user_id=str(row["owner_user_id"]),
        sequence=int(row["sequence_no"]),
        graph_content_hash=str(row["graph_content_hash"]),
        active_node_id=_identifier(row.get("active_node_id")),
        evidence_ref=row.get("evidence_ref"),
        evidence_hash=row.get("evidence_hash"),
        created_at=_timestamp(row["created_at"]),
        content_hash=str(row["content_hash"]),
    )


def _transition(row: Mapping[str, Any]) -> PolicyTransition:
    if GraphKind(row["graph_kind"]) != GraphKind.SHORT_TERM_WORKING:
        raise ValueError("policy transition is not in a working graph")
    target = row.get("target_graph_kind")
    return PolicyTransition(
        transition_id=str(row["id"]),
        graph_id=str(row["graph_id"]),
        candidate_node_id=str(row["candidate_node_id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        owner_user_id=str(row["owner_user_id"]),
        action=PolicyAction(row["action"]),
        actor=PolicyActor(row["actor"]),
        target_graph_kind=GraphKind(target) if target is not None else None,
        state_features_hash=row.get("state_features_hash"),
        reward=float(row["reward"]) if row.get("reward") is not None else None,
        delayed_credit_ref=row.get("delayed_credit_ref"),
        event_time=_timestamp(row["event_time"]),
        content_hash=str(row["content_hash"]),
    )


def _strength(row: Mapping[str, Any]) -> SemanticStrengthRecord:
    record = SemanticStrengthRecord(
        strength_id=str(row["id"]),
        graph_id=str(row["graph_id"]),
        semantic_node_id=str(row["semantic_node_id"]),
        org_id=str(row["org_id"]),
        namespace=str(row["namespace"]),
        graph_kind=GraphKind(row["graph_kind"]),
        owner_user_id=_identifier(row.get("owner_user_id")),
        strength=SemanticStrength(
            support=float(row["support"]),
            successful_reuse=float(row["successful_reuse"]),
            independent_user_evidence=float(row["independent_user_evidence"]),
            recent_verification=float(row["recent_verification"]),
            negative_transfer=float(row["negative_transfer"]),
            contradiction=float(row["contradiction"]),
            version_staleness=float(row["version_staleness"]),
        ),
        updated_at=_timestamp(row["updated_at"]),
        content_hash=str(row["content_hash"]),
    )
    stored_score = float(row["strength_score"])
    if not math.isclose(
        stored_score, record.strength.score, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError("semantic strength generated score mismatch")
    return record


def _namespace_claim(row: Any) -> NamespaceClaim:
    data = _mapping(row)
    return NamespaceClaim(
        namespace=str(data["namespace"]),
        experiment_id=str(data["experiment_id"]),
        split=str(data["split"]),
        arm_id=str(data["arm_id"]),
        task_order_hash=str(data["task_order_hash"]),
        config_hash=str(data["config_hash"]),
        run_nonce=str(data["run_nonce"]),
        next_sequence_index=int(data["next_sequence_index"]),
        claim_status=str(data["claim_status"]),
    )


def _outbox_intent(row: Any) -> IndexOutboxIntent:
    data = _mapping(row)
    status = str(data["status"])
    operation = str(data["operation"])
    attempts = int(data["attempts"])
    indexed_at = _timestamp(data.get("indexed_at"))
    last_error = data.get("last_error")
    if operation not in {"UPSERT", "DELETE"}:
        raise ValueError("invalid vector index outbox operation")
    if status not in {"PENDING", "INDEXED", "CANCELLED"} or attempts < 0:
        raise ValueError("invalid vector index outbox state")
    if (status == "PENDING" and indexed_at is not None) or (
        status == "INDEXED" and (indexed_at is None or last_error is not None)
    ) or (
        status == "CANCELLED" and (indexed_at is not None or last_error is not None)
    ):
        raise ValueError("invalid vector index outbox status shape")
    content_hash = str(data["canonical_content_hash"])
    if not (
        content_hash.startswith("sha256:")
        and len(content_hash) == 71
        and all(character in "0123456789abcdef" for character in content_hash[7:])
    ):
        raise ValueError("invalid vector index outbox content hash")
    prior_content_hash = data.get("prior_content_hash")
    if prior_content_hash is not None:
        prior_content_hash = str(prior_content_hash)
        if not (
            prior_content_hash.startswith("sha256:")
            and len(prior_content_hash) == 71
            and all(
                character in "0123456789abcdef"
                for character in prior_content_hash[7:]
            )
        ):
            raise ValueError("invalid vector index outbox prior content hash")
    if (operation == "UPSERT") != (prior_content_hash is None):
        raise ValueError("invalid vector index outbox operation shape")
    return IndexOutboxIntent(
        intent_id=str(data["id"]),
        org_id=str(data["org_id"]),
        namespace=str(data["namespace"]),
        graph_id=str(data["graph_id"]),
        graph_kind=GraphKind(data["graph_kind"]),
        owner_user_id=_identifier(data.get("owner_user_id")),
        node_id=str(data["node_id"]),
        operation=operation,
        canonical_content_hash=content_hash,
        prior_content_hash=prior_content_hash,
        status=status,
        attempts=attempts,
        last_error=None if last_error is None else str(last_error),
        created_at=str(_timestamp(data["created_at"])),
        updated_at=str(_timestamp(data["updated_at"])),
        indexed_at=indexed_at,
    )


def _session_checkpoint(row: Any) -> SessionCheckpoint:
    data = _mapping(row)
    payload = _json_object(data["checkpoint_payload"])
    digest = str(data["checkpoint_digest"])
    if canonical_hash(payload) != digest:
        raise ValueError("session checkpoint digest mismatch")
    namespace = str(data["namespace"])
    run_nonce = str(data["run_nonce"])
    checkpoint_schema = str(data["checkpoint_schema"])
    next_index = int(data["next_sequence_index"])
    if next_index < 0:
        raise ValueError("session checkpoint sequence is invalid")
    if (
        payload.get("schema") != checkpoint_schema
        or payload.get("namespace") != namespace
        or payload.get("run_nonce") != run_nonce
        or type(payload.get("next_sequence_index")) is not int
        or payload.get("next_sequence_index") != next_index
    ):
        raise ValueError("session checkpoint envelope identity mismatch")
    return SessionCheckpoint(
        checkpoint_id=str(data["id"]),
        org_id=str(data["org_id"]),
        namespace=namespace,
        owner_user_id=str(data["owner_user_id"]),
        run_nonce=run_nonce,
        next_sequence_index=next_index,
        checkpoint_schema=checkpoint_schema,
        checkpoint_payload=payload,
        checkpoint_digest=digest,
        created_at=str(_timestamp(data["created_at"])),
    )


def _promotion_evidence(row: Any) -> PromotionEvidence:
    data = _mapping(row)
    hashes = {
        name: str(data[name])
        for name in (
            "evidence_hash",
            "contributor_hash",
            "public_evidence_hash",
            "verifier_hash",
            "extraction_hash",
            "attestation_hash",
        )
    }
    if any(
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
        for value in hashes.values()
    ):
        raise ValueError("promotion evidence contains an invalid digest")
    if (
        data["source_kind"] != "VERIFIED_EPISODE"
        or data["source_outcome"] != "passed"
        or data["verified"] is not True
    ):
        raise ValueError("promotion evidence is not a verified episode")
    namespace = str(data["namespace"])
    verified_at = str(_timestamp(data["verified_at"]))
    expected_attestation_hash = canonical_hash(
        {
            "schema": "trimem/promotion-evidence/1.0",
            "namespace": namespace,
            "evidence_hash": hashes["evidence_hash"],
            "contributor_hash": hashes["contributor_hash"],
            "source_kind": "VERIFIED_EPISODE",
            "source_outcome": "passed",
            "verified": True,
            "public_evidence_hash": hashes["public_evidence_hash"],
            "verifier_hash": hashes["verifier_hash"],
            "extraction_hash": hashes["extraction_hash"],
            "verified_at": verified_at,
        }
    )
    if hashes["attestation_hash"] != expected_attestation_hash:
        raise ValueError("promotion evidence attestation mismatch")
    return PromotionEvidence(
        evidence_id=str(data["id"]),
        org_id=str(data["org_id"]),
        namespace=namespace,
        evidence_hash=hashes["evidence_hash"],
        contributor_hash=hashes["contributor_hash"],
        source_kind="VERIFIED_EPISODE",
        source_outcome="passed",
        verified=True,
        public_evidence_hash=hashes["public_evidence_hash"],
        verifier_hash=hashes["verifier_hash"],
        extraction_hash=hashes["extraction_hash"],
        attestation_hash=hashes["attestation_hash"],
        verified_at=verified_at,
        created_at=str(_timestamp(data["created_at"])),
    )


def _checked(loader: Callable[[Mapping[str, Any]], Any], row: Any, label: str):
    try:
        record = loader(_mapping(row))
        if not record.verify_hash():
            raise ValueError("hash mismatch")
        return record
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalReloadError("canonical %s reload failed" % label) from exc


def _review_params(review: Optional[ReviewProvenance]) -> dict[str, Any]:
    if review is None:
        return {
            "review_id": None,
            "reviewer_id": None,
            "reviewed_at": None,
            "review_authority": None,
            "review_policy_version": None,
            "review_evidence_hash": None,
        }
    if not review.verify_hash():
        raise IntegrityViolation("review provenance hash is invalid")
    return {
        "review_id": review.review_id,
        "reviewer_id": review.reviewer_id,
        "reviewed_at": _postgres_timestamp(review.reviewed_at, "reviewed_at"),
        "review_authority": review.authority.value,
        "review_policy_version": review.policy_version,
        "review_evidence_hash": review.evidence_hash,
    }


def _temporal_params(temporal: TemporalMetadata) -> dict[str, Any]:
    return {
        name: _postgres_timestamp(getattr(temporal, name), name)
        for name in (
            "ingested_at",
            "event_time",
            "source_available_at",
            "last_accessed_at",
            "last_used_at",
            "last_verified_at",
            "valid_from",
            "valid_until",
        )
    }


def _scope_params(ctx: AccessContext, namespace: str) -> dict[str, Any]:
    return {"org_id": ctx.org_id, "namespace": namespace, "owner_user_id": ctx.user_id}


def _require_partition(ctx: AccessContext, *, org_id: str, namespace: str,
                       expected_namespace: str, graph_kind: GraphKind,
                       owner_user_id: Optional[str]) -> None:
    if org_id != ctx.org_id:
        raise ScopeViolation("organisation boundary violation")
    if namespace != expected_namespace:
        raise ScopeViolation("memory namespace boundary violation")
    if graph_kind in PRIVATE_GRAPH_KINDS and owner_user_id != ctx.user_id:
        raise ScopeViolation("private memory owner boundary violation")
    if graph_kind == GraphKind.ORGANISATION_SEMANTIC and owner_user_id is not None:
        raise ScopeViolation("organisation semantic memory cannot have a private owner")


class PostgresTriMemStore:
    """Production async repository over the additive 0015 canonical tables."""

    def __init__(self, engine, *, namespace: str = DEFAULT_NAMESPACE):
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("namespace is required")
        self._engine = engine
        self.namespace = namespace
        self._active_tx = ContextVar(
            "trimem_active_tx_%x" % id(self), default=None
        )

    @asynccontextmanager
    async def _tenant_tx(self, ctx: AccessContext):
        active = self._active_tx.get()
        if active is not None:
            conn, org_id, user_id = active
            if org_id != ctx.org_id or user_id != ctx.user_id:
                raise ScopeViolation("nested tenant context boundary violation")
            yield conn
            return
        async with tenant_tx(self._engine, ctx.org_id, ctx.user_id) as conn:
            await conn.execute(
                text("SELECT set_config('app.trimem_namespace', :namespace, true)"),
                {"namespace": self.namespace},
            )
            token = self._active_tx.set((conn, ctx.org_id, ctx.user_id))
            try:
                yield conn
            finally:
                self._active_tx.reset(token)

    async def _one(self, conn, *, table: str, columns: str, record_id: str,
                   ctx: AccessContext, loader: Callable, label: str):
        result = await conn.execute(
            text("SELECT %s FROM %s WHERE id=:id AND %s" % (columns, table, _SCOPE)),
            {"id": record_id, **_scope_params(ctx, self.namespace)},
        )
        row = result.mappings().first()
        if row is None:
            raise NotFound("%s not found" % label)
        return _checked(loader, row, label)

    async def _many(self, conn, *, table: str, columns: str, ctx: AccessContext,
                    loader: Callable, label: str, clauses: Sequence[str] = (),
                    params: Optional[dict[str, Any]] = None, order: str = "id"):
        where = [_SCOPE, *clauses]
        result = await conn.execute(
            text("SELECT %s FROM %s WHERE %s ORDER BY %s" % (
                columns, table, " AND ".join(where), order
            )),
            {**_scope_params(ctx, self.namespace), **(params or {})},
        )
        return [_checked(loader, row, label) for row in result.mappings().all()]

    @staticmethod
    def _verify(record, label: str) -> None:
        if not record.verify_hash():
            raise IntegrityViolation("%s content hash is invalid" % label)

    async def put_graph(self, ctx: AccessContext, graph: MemoryGraph) -> MemoryGraph:
        _require_partition(ctx, org_id=graph.org_id, namespace=graph.namespace,
                           expected_namespace=self.namespace, graph_kind=graph.kind,
                           owner_user_id=graph.owner_user_id)
        self._verify(graph, "graph")
        params = {
            "id": graph.graph_id,
            "org_id": graph.org_id,
            "namespace": graph.namespace,
            "graph_kind": graph.kind.value,
            "owner_user_id": graph.owner_user_id,
            "repository_id": graph.repository_id,
            "solve_job_id": graph.solve_job_id,
            "graph_state": graph.state.value,
            "schema_version": graph.schema_version,
            "content_hash": graph.content_hash,
            **_temporal_params(graph.temporal),
            **_review_params(graph.review_provenance),
        }
        async with self._tenant_tx(ctx) as conn:
            await conn.execute(text("""
                INSERT INTO trimem_graphs(
                  id,org_id,namespace,graph_kind,owner_user_id,repository_id,solve_job_id,
                  graph_state,schema_version,ingested_at,event_time,source_available_at,
                  last_accessed_at,last_used_at,last_verified_at,valid_from,valid_until,
                  review_id,reviewer_id,reviewed_at,review_authority,review_policy_version,
                  review_evidence_hash,content_hash)
                VALUES(
                  :id,:org_id,:namespace,:graph_kind,:owner_user_id,:repository_id,:solve_job_id,
                  :graph_state,:schema_version,:ingested_at,:event_time,:source_available_at,
                  :last_accessed_at,:last_used_at,:last_verified_at,:valid_from,:valid_until,
                  :review_id,:reviewer_id,:reviewed_at,:review_authority,:review_policy_version,
                  :review_evidence_hash,:content_hash)
                ON CONFLICT (id) DO NOTHING
            """), params)
            try:
                loaded = await self._one(
                    conn, table="trimem_graphs", columns=_GRAPH_COLUMNS,
                    record_id=graph.graph_id, ctx=ctx, loader=_graph, label="graph",
                )
            except NotFound as exc:
                raise IntegrityViolation("graph identifier is unavailable") from exc
        if loaded.content_hash != graph.content_hash:
            raise IntegrityViolation("graph identifier is already bound")
        return loaded

    async def get_graph(self, ctx: AccessContext, graph_id: str) -> MemoryGraph:
        async with self._tenant_tx(ctx) as conn:
            return await self._one(
                conn, table="trimem_graphs", columns=_GRAPH_COLUMNS, record_id=graph_id,
                ctx=ctx, loader=_graph, label="graph",
            )

    async def list_graphs(
        self, ctx: AccessContext, *, kind: Optional[GraphKind] = None
    ) -> list[MemoryGraph]:
        clauses, params = [], {}
        if kind is not None:
            if not isinstance(kind, GraphKind):
                raise ValueError("invalid graph kind")
            clauses.append("graph_kind=:kind")
            params["kind"] = kind.value
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn, table="trimem_graphs", columns=_GRAPH_COLUMNS, ctx=ctx,
                loader=_graph, label="graph", clauses=clauses, params=params,
                order="ingested_at,id",
            )

    async def resolve_task_identity(
        self, ctx: AccessContext, *, repository_slug: str, task_id: str
    ) -> Mapping[str, str]:
        """Resolve an external task identity to one canonical repo/job pair.

        Resolution is deliberately exact and ambiguity is fatal.  A solve job
        must bind the same repository, submitter, task-policy key, and task ID
        recorded in ``spec_json``; callers cannot synthesize database UUIDs from
        benchmark slugs.
        """

        if not isinstance(repository_slug, str) or not repository_slug.strip():
            raise ValueError("repository_slug is required")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id is required")
        if repository_slug != repository_slug.strip() or task_id != task_id.strip():
            raise ValueError("repository_slug and task_id must be exact canonical values")
        async with self._tenant_tx(ctx) as conn:
            repositories = (
                await conn.execute(
                    text("""
                        SELECT id, external_repo_id
                        FROM repositories
                        WHERE org_id=:org_id AND external_repo_id=:repository_slug
                        ORDER BY id
                        LIMIT 2
                    """),
                    {"org_id": ctx.org_id, "repository_slug": repository_slug},
                )
            ).mappings().all()
            if len(repositories) != 1:
                raise NotFound("task identity is unavailable")
            repository_id = str(_mapping(repositories[0])["id"])
            jobs = (
                await conn.execute(
                    text("""
                        SELECT j.id, j.repository_id, j.submitter_user_id,
                               j.spec_json->>'task_id' AS task_id
                        FROM solve_jobs j
                        JOIN task_execution_policies p
                          ON p.id=j.task_policy_id AND p.org_id=j.org_id
                         AND p.repository_id=j.repository_id
                        WHERE j.org_id=:org_id
                          AND j.repository_id=:repository_id
                          AND j.submitter_user_id=:owner_user_id
                          AND p.task_key=:task_id
                          AND j.spec_json->>'task_id'=:task_id
                        ORDER BY j.id
                        LIMIT 2
                    """),
                    {
                        "org_id": ctx.org_id,
                        "repository_id": repository_id,
                        "owner_user_id": ctx.user_id,
                        "task_id": task_id,
                    },
                )
            ).mappings().all()
            if len(jobs) != 1:
                raise NotFound("task identity is unavailable")
            job = _mapping(jobs[0])
            if (
                str(job["repository_id"]) != repository_id
                or str(job["submitter_user_id"]) != ctx.user_id
                or str(job["task_id"]) != task_id
            ):
                raise CanonicalReloadError("resolved task identity is inconsistent")
        return {
            "repository_id": repository_id,
            "solve_job_id": str(job["id"]),
            "repository_slug": repository_slug,
            "task_id": task_id,
        }

    async def put_node(self, ctx: AccessContext, node: GraphNode) -> GraphNode:
        _require_partition(ctx, org_id=node.org_id, namespace=node.namespace,
                           expected_namespace=self.namespace, graph_kind=node.graph_kind,
                           owner_user_id=node.owner_user_id)
        self._verify(node, "node")
        params = {
            "id": node.node_id,
            "org_id": node.org_id,
            "namespace": node.namespace,
            "graph_id": node.graph_id,
            "graph_kind": node.graph_kind.value,
            "owner_user_id": node.owner_user_id,
            "repository_id": node.repository_id,
            "node_type": node.node_type.value,
            "lifecycle_state": node.lifecycle_state.value,
            "canonical_payload": json.dumps(
                dict(node.canonical_payload), sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False,
            ),
            "payload_hash": node.payload_hash,
            "archived_at": _postgres_timestamp(node.archived_at, "archived_at"),
            "archive_reason": node.archive_reason,
            "archived_from_content_hash": node.archived_from_content_hash,
            "content_hash": node.content_hash,
            **_temporal_params(node.temporal),
            **_review_params(node.review_provenance),
        }
        async with self._tenant_tx(ctx) as conn:
            await conn.execute(text("""
                INSERT INTO trimem_graph_nodes(
                  id,org_id,namespace,graph_id,graph_kind,owner_user_id,repository_id,node_type,
                  lifecycle_state,canonical_payload,payload_hash,archived_at,archive_reason,
                  archived_from_content_hash,
                  ingested_at,event_time,source_available_at,last_accessed_at,last_used_at,
                  last_verified_at,valid_from,valid_until,review_id,reviewer_id,reviewed_at,
                  review_authority,review_policy_version,review_evidence_hash,content_hash)
                VALUES(
                  :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,:repository_id,:node_type,
                  :lifecycle_state,cast(:canonical_payload as jsonb),:payload_hash,:archived_at,
                  :archive_reason,:archived_from_content_hash,:ingested_at,:event_time,
                  :source_available_at,:last_accessed_at,
                  :last_used_at,:last_verified_at,:valid_from,:valid_until,:review_id,:reviewer_id,
                  :reviewed_at,:review_authority,:review_policy_version,:review_evidence_hash,
                  :content_hash)
                ON CONFLICT (id) DO NOTHING
            """), params)
            try:
                loaded = await self._one(
                    conn, table="trimem_graph_nodes", columns=_NODE_COLUMNS,
                    record_id=node.node_id, ctx=ctx, loader=_node, label="node",
                )
            except NotFound as exc:
                raise IntegrityViolation("node identifier is unavailable") from exc
        if loaded.content_hash != node.content_hash:
            raise IntegrityViolation("node identifier is already bound")
        return loaded

    async def get_node(self, ctx: AccessContext, node_id: str) -> GraphNode:
        async with self._tenant_tx(ctx) as conn:
            return await self._one(
                conn, table="trimem_graph_nodes", columns=_NODE_COLUMNS, record_id=node_id,
                ctx=ctx, loader=_node, label="node",
            )

    async def list_nodes(
        self, ctx: AccessContext, *, graph_id: Optional[str] = None,
        include_archived: bool = False
    ) -> list[GraphNode]:
        clauses, params = [], {}
        if graph_id is not None:
            clauses.append("graph_id=:graph_id")
            params["graph_id"] = graph_id
        if not include_archived:
            clauses.append("lifecycle_state='ACTIVE'")
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn, table="trimem_graph_nodes", columns=_NODE_COLUMNS, ctx=ctx,
                loader=_node, label="node", clauses=clauses, params=params,
                order="ingested_at,id",
            )

    async def put_edge(self, ctx: AccessContext, edge: GraphEdge) -> GraphEdge:
        _require_partition(ctx, org_id=edge.org_id, namespace=edge.namespace,
                           expected_namespace=self.namespace, graph_kind=edge.graph_kind,
                           owner_user_id=edge.owner_user_id)
        self._verify(edge, "edge")
        params = {
            "id": edge.edge_id, "org_id": edge.org_id, "namespace": edge.namespace,
            "graph_id": edge.graph_id,
            "graph_kind": edge.graph_kind.value, "owner_user_id": edge.owner_user_id,
            "edge_type": edge.edge_type.value, "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id, "lifecycle_state": edge.lifecycle_state.value,
            "metadata": json.dumps(dict(edge.metadata), sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False),
            "content_hash": edge.content_hash,
            **_temporal_params(edge.temporal), **_review_params(edge.review_provenance),
        }
        async with self._tenant_tx(ctx) as conn:
            await conn.execute(text("""
                INSERT INTO trimem_graph_edges(
                  id,org_id,namespace,graph_id,graph_kind,owner_user_id,edge_type,source_node_id,
                  target_node_id,lifecycle_state,metadata,ingested_at,event_time,
                  source_available_at,last_accessed_at,last_used_at,last_verified_at,
                  valid_from,valid_until,review_id,reviewer_id,reviewed_at,review_authority,
                  review_policy_version,review_evidence_hash,content_hash)
                VALUES(
                  :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,:edge_type,:source_node_id,
                  :target_node_id,:lifecycle_state,cast(:metadata as jsonb),:ingested_at,
                  :event_time,:source_available_at,:last_accessed_at,:last_used_at,
                  :last_verified_at,:valid_from,:valid_until,:review_id,:reviewer_id,
                  :reviewed_at,:review_authority,:review_policy_version,:review_evidence_hash,
                  :content_hash) ON CONFLICT (id) DO NOTHING
            """), params)
            try:
                loaded = await self._one(
                    conn, table="trimem_graph_edges", columns=_EDGE_COLUMNS,
                    record_id=edge.edge_id, ctx=ctx, loader=_edge, label="edge",
                )
            except NotFound as exc:
                raise IntegrityViolation("edge identifier is unavailable") from exc
        if loaded.content_hash != edge.content_hash:
            raise IntegrityViolation("edge identifier is already bound")
        return loaded

    async def get_edge(self, ctx: AccessContext, edge_id: str) -> GraphEdge:
        async with self._tenant_tx(ctx) as conn:
            return await self._one(
                conn, table="trimem_graph_edges", columns=_EDGE_COLUMNS, record_id=edge_id,
                ctx=ctx, loader=_edge, label="edge",
            )

    async def list_edges(self, ctx: AccessContext, *, graph_id: str) -> list[GraphEdge]:
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn, table="trimem_graph_edges", columns=_EDGE_COLUMNS, ctx=ctx,
                loader=_edge, label="edge",
                clauses=("graph_id=:graph_id", "lifecycle_state='ACTIVE'"),
                params={"graph_id": graph_id}, order="ingested_at,id",
            )

    async def put_support(self, ctx: AccessContext, support: SemanticSupport) -> SemanticSupport:
        _require_partition(ctx, org_id=support.org_id, namespace=support.namespace,
                           expected_namespace=self.namespace, graph_kind=support.graph_kind,
                           owner_user_id=support.owner_user_id)
        self._verify(support, "support")
        params = {
            "id": support.support_id, "org_id": support.org_id,
            "namespace": support.namespace,
            "graph_id": support.semantic_graph_id, "graph_kind": support.graph_kind.value,
            "owner_user_id": support.owner_user_id,
            "semantic_node_id": support.semantic_node_id,
            "source_episode_id": support.source_episode_id,
            "source_evidence_hash": support.source_evidence_hash,
            "contributor_hash": support.contributor_hash,
            "content_hash": support.content_hash,
            **_temporal_params(support.temporal), **_review_params(support.review_provenance),
        }
        return await self._append_record(
            ctx, table="trimem_semantic_supports", columns=_SUPPORT_COLUMNS, params=params,
            insert="""
              INSERT INTO trimem_semantic_supports(
                id,org_id,namespace,graph_id,graph_kind,owner_user_id,semantic_node_id,
                source_episode_id,source_evidence_hash,contributor_hash,ingested_at,event_time,
                source_available_at,last_accessed_at,last_used_at,last_verified_at,valid_from,
                valid_until,review_id,reviewer_id,reviewed_at,review_authority,
                review_policy_version,review_evidence_hash,content_hash)
              VALUES(
                :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,:semantic_node_id,
                :source_episode_id,:source_evidence_hash,:contributor_hash,:ingested_at,
                :event_time,:source_available_at,:last_accessed_at,:last_used_at,
                :last_verified_at,:valid_from,:valid_until,:review_id,:reviewer_id,:reviewed_at,
                :review_authority,:review_policy_version,:review_evidence_hash,:content_hash)
              ON CONFLICT (id) DO NOTHING
            """,
            loader=_support, label="support", expected_hash=support.content_hash,
        )

    async def get_support(self, ctx: AccessContext, support_id: str) -> SemanticSupport:
        return await self._get(ctx, "trimem_semantic_supports", _SUPPORT_COLUMNS,
                               support_id, _support, "support")

    async def list_supports(
        self, ctx: AccessContext, *, semantic_node_id: Optional[str] = None
    ) -> list[SemanticSupport]:
        clauses, params = [], {}
        if semantic_node_id is not None:
            clauses.append("semantic_node_id=:semantic_node_id")
            params["semantic_node_id"] = semantic_node_id
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn, table="trimem_semantic_supports", columns=_SUPPORT_COLUMNS, ctx=ctx,
                loader=_support, label="support", clauses=clauses, params=params,
                order="ingested_at,id",
            )

    async def append_access(
        self, ctx: AccessContext, event: MemoryAccessEvent
    ) -> MemoryAccessEvent:
        _require_partition(ctx, org_id=event.org_id, namespace=event.namespace,
                           expected_namespace=self.namespace, graph_kind=event.graph_kind,
                           owner_user_id=event.owner_user_id)
        if event.actor_user_id != ctx.user_id:
            raise ScopeViolation("access actor must match tenant context")
        self._verify(event, "access event")
        params = {
            "id": event.event_id, "org_id": event.org_id, "namespace": event.namespace,
            "graph_id": event.graph_id,
            "graph_kind": event.graph_kind.value, "owner_user_id": event.owner_user_id,
            "node_id": event.node_id, "actor_user_id": event.actor_user_id,
            "access_type": event.access_type.value,
            "event_time": _postgres_timestamp(event.event_time, "event_time"),
            "injected_byte_count": event.injected_byte_count,
            "injected_hash": event.injected_hash, "evidence_ref": event.evidence_ref,
            "content_hash": event.content_hash,
        }
        return await self._append_record(
            ctx, table="trimem_memory_access_events", columns=_ACCESS_COLUMNS, params=params,
            insert="""
              INSERT INTO trimem_memory_access_events(
                id,org_id,namespace,graph_id,graph_kind,owner_user_id,node_id,actor_user_id,
                access_type,event_time,injected_byte_count,injected_hash,evidence_ref,content_hash)
              VALUES(
                :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,:node_id,:actor_user_id,
                :access_type,:event_time,:injected_byte_count,:injected_hash,:evidence_ref,
                :content_hash) ON CONFLICT (id) DO NOTHING
            """, loader=_access, label="access event", expected_hash=event.content_hash,
        )

    async def get_access_event(
        self, ctx: AccessContext, event_id: str
    ) -> MemoryAccessEvent:
        return await self._get(ctx, "trimem_memory_access_events", _ACCESS_COLUMNS,
                               event_id, _access, "access event")

    async def list_access_events(
        self, ctx: AccessContext, *, graph_id: Optional[str] = None
    ) -> list[MemoryAccessEvent]:
        clauses, params = [], {}
        if graph_id is not None:
            clauses.append("graph_id=:graph_id")
            params["graph_id"] = graph_id
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn, table="trimem_memory_access_events", columns=_ACCESS_COLUMNS, ctx=ctx,
                loader=_access, label="access event", clauses=clauses, params=params,
                order="event_time,id",
            )

    async def load_policy_feature_rows(
        self, ctx: AccessContext, *, limit: int
    ) -> Mapping[str, Any]:
        """Reload the bounded canonical history used by M2 scalar features.

        Content is read from PostgreSQL under the same owner/org/namespace RLS
        context as lifecycle writes.  Every constituent object is rebuilt and
        hash-verified before this compact, deterministic projection is returned.
        """

        if type(limit) is not int or limit <= 0:
            raise ValueError("policy feature history limit must be positive")
        async with self._tenant_tx(ctx):
            graphs = {
                graph.graph_id: graph
                for kind in (
                    GraphKind.USER_EPISODIC,
                    GraphKind.USER_SEMANTIC,
                    GraphKind.ORGANISATION_SEMANTIC,
                )
                for graph in await self.list_graphs(ctx, kind=kind)
                if graph.state != GraphState.ARCHIVED
            }
            nodes = [
                node
                for node in await self.list_nodes(ctx, include_archived=False)
                if node.graph_id in graphs
                and (
                    (node.graph_kind == GraphKind.USER_EPISODIC and node.node_type == NodeType.EPISODE)
                    or (
                        node.graph_kind in SEMANTIC_GRAPH_KINDS
                        and node.node_type == NodeType.SEMANTIC_RULE
                    )
                )
            ]
            strengths = {
                item.semantic_node_id: item
                for item in await self.list_semantic_strengths(ctx)
            }
            access_by_node: dict[str, list[MemoryAccessEvent]] = {}
            for event in await self.list_access_events(ctx):
                access_by_node.setdefault(event.node_id, []).append(event)

        rows: list[dict[str, Any]] = []
        for node in nodes:
            graph = graphs[node.graph_id]
            payload = node.canonical_payload
            retrieval_text = payload.get("retrieval_text")
            if not isinstance(retrieval_text, str) or not retrieval_text.strip():
                continue
            events = access_by_node.get(node.node_id, ())
            strength = strengths.get(node.node_id)
            timestamps = [
                value
                for value in (
                    node.temporal.last_used_at,
                    node.temporal.last_accessed_at,
                    node.temporal.event_time,
                    node.temporal.ingested_at,
                    *(item.event_time for item in events),
                )
                if isinstance(value, str) and value
            ]
            rows.append({
                "node_id": node.node_id,
                "graph_id": node.graph_id,
                "graph_kind": node.graph_kind.value,
                "repository_id": node.repository_id,
                "retrieval_text": retrieval_text,
                "version": str(payload.get("version", "UNKNOWN")),
                "version_valid": bool(payload.get("version_valid")),
                "stale": bool(payload.get("stale")),
                "last_activity_at": max(timestamps),
                "reuse_count": sum(
                    item.access_type in {AccessType.INJECTED, AccessType.USED}
                    for item in events
                ),
                "strength": (
                    {
                        "support": strength.strength.support,
                        "successful_reuse": strength.strength.successful_reuse,
                        "independent_user_evidence": strength.strength.independent_user_evidence,
                        "recent_verification": strength.strength.recent_verification,
                        "negative_transfer": strength.strength.negative_transfer,
                        "contradiction": strength.strength.contradiction,
                        "version_staleness": strength.strength.version_staleness,
                    }
                    if strength is not None
                    else None
                ),
                "node_content_hash": node.content_hash,
                "graph_content_hash": graph.content_hash,
            })
        rows.sort(
            key=lambda item: (str(item["last_activity_at"]), str(item["node_id"])),
            reverse=True,
        )
        rows = sorted(rows[:limit], key=lambda item: str(item["node_id"]))
        payload = {
            "schema": "trimem/canonical-policy-feature-rows/1.0",
            "namespace": self.namespace,
            "history_limit": limit,
            "rows": rows,
        }
        return {**payload, "digest": canonical_hash(payload)}

    async def save_checkpoint(
        self, ctx: AccessContext, checkpoint: GraphCheckpoint
    ) -> GraphCheckpoint:
        if (checkpoint.org_id != ctx.org_id or checkpoint.namespace != self.namespace
                or checkpoint.owner_user_id != ctx.user_id):
            raise ScopeViolation("checkpoint owner boundary violation")
        self._verify(checkpoint, "checkpoint")
        params = {
            "id": checkpoint.checkpoint_id, "org_id": checkpoint.org_id,
            "namespace": checkpoint.namespace,
            "graph_id": checkpoint.graph_id,
            "graph_kind": GraphKind.SHORT_TERM_WORKING.value,
            "owner_user_id": checkpoint.owner_user_id, "sequence_no": checkpoint.sequence,
            "graph_content_hash": checkpoint.graph_content_hash,
            "active_node_id": checkpoint.active_node_id, "evidence_ref": checkpoint.evidence_ref,
            "evidence_hash": checkpoint.evidence_hash,
            "created_at": _postgres_timestamp(checkpoint.created_at, "created_at"),
            "content_hash": checkpoint.content_hash,
        }
        return await self._append_record(
            ctx, table="trimem_graph_checkpoints", columns=_CHECKPOINT_COLUMNS, params=params,
            insert="""
              INSERT INTO trimem_graph_checkpoints(
                id,org_id,namespace,graph_id,graph_kind,owner_user_id,sequence_no,graph_content_hash,
                active_node_id,evidence_ref,evidence_hash,created_at,content_hash)
              VALUES(
                :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,:sequence_no,
                :graph_content_hash,:active_node_id,:evidence_ref,:evidence_hash,:created_at,
                :content_hash) ON CONFLICT (id) DO NOTHING
            """, loader=_checkpoint, label="checkpoint", expected_hash=checkpoint.content_hash,
        )

    async def get_checkpoint(
        self, ctx: AccessContext, checkpoint_id: str
    ) -> GraphCheckpoint:
        return await self._get(ctx, "trimem_graph_checkpoints", _CHECKPOINT_COLUMNS,
                               checkpoint_id, _checkpoint, "checkpoint")

    async def list_checkpoints(
        self, ctx: AccessContext, *, graph_id: str
    ) -> list[GraphCheckpoint]:
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn, table="trimem_graph_checkpoints", columns=_CHECKPOINT_COLUMNS, ctx=ctx,
                loader=_checkpoint, label="checkpoint", clauses=("graph_id=:graph_id",),
                params={"graph_id": graph_id}, order="sequence_no,id",
            )

    async def record_policy_transition(
        self, ctx: AccessContext, transition: PolicyTransition
    ) -> PolicyTransition:
        if (transition.org_id != ctx.org_id or transition.namespace != self.namespace
                or transition.owner_user_id != ctx.user_id):
            raise ScopeViolation("policy transition owner boundary violation")
        self._verify(transition, "policy transition")
        params = {
            "id": transition.transition_id, "org_id": transition.org_id,
            "namespace": transition.namespace,
            "graph_id": transition.graph_id,
            "graph_kind": GraphKind.SHORT_TERM_WORKING.value,
            "owner_user_id": transition.owner_user_id,
            "candidate_node_id": transition.candidate_node_id,
            "action": transition.action.value, "actor": transition.actor.value,
            "target_graph_kind": (
                transition.target_graph_kind.value if transition.target_graph_kind else None
            ),
            "state_features_hash": transition.state_features_hash,
            "reward": transition.reward, "delayed_credit_ref": transition.delayed_credit_ref,
            "event_time": _postgres_timestamp(transition.event_time, "event_time"),
            "content_hash": transition.content_hash,
        }
        return await self._append_record(
            ctx, table="trimem_policy_transitions", columns=_TRANSITION_COLUMNS, params=params,
            insert="""
              INSERT INTO trimem_policy_transitions(
                id,org_id,namespace,graph_id,graph_kind,owner_user_id,candidate_node_id,action,actor,
                target_graph_kind,state_features_hash,reward,delayed_credit_ref,event_time,
                content_hash)
              VALUES(
                :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,:candidate_node_id,:action,
                :actor,:target_graph_kind,:state_features_hash,:reward,:delayed_credit_ref,
                :event_time,:content_hash) ON CONFLICT (id) DO NOTHING
            """, loader=_transition, label="policy transition",
            expected_hash=transition.content_hash,
        )

    async def get_policy_transition(
        self, ctx: AccessContext, transition_id: str
    ) -> PolicyTransition:
        return await self._get(ctx, "trimem_policy_transitions", _TRANSITION_COLUMNS,
                               transition_id, _transition, "policy transition")

    async def list_policy_transitions(
        self, ctx: AccessContext, *, graph_id: Optional[str] = None
    ) -> list[PolicyTransition]:
        clauses, params = [], {}
        if graph_id is not None:
            clauses.append("graph_id=:graph_id")
            params["graph_id"] = graph_id
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn, table="trimem_policy_transitions", columns=_TRANSITION_COLUMNS,
                ctx=ctx, loader=_transition, label="policy transition", clauses=clauses,
                params=params, order="event_time,id",
            )

    async def put_semantic_strength(
        self, ctx: AccessContext, record: SemanticStrengthRecord
    ) -> SemanticStrengthRecord:
        """Insert or monotonically replace one canonical semantic strength row."""

        _require_partition(
            ctx,
            org_id=record.org_id,
            namespace=record.namespace,
            expected_namespace=self.namespace,
            graph_kind=record.graph_kind,
            owner_user_id=record.owner_user_id,
        )
        self._verify(record, "semantic strength")
        strength = record.strength
        params = {
            "id": record.strength_id,
            "org_id": record.org_id,
            "namespace": record.namespace,
            "graph_id": record.graph_id,
            "graph_kind": record.graph_kind.value,
            "owner_user_id": record.owner_user_id,
            "semantic_node_id": record.semantic_node_id,
            "support": strength.support,
            "successful_reuse": strength.successful_reuse,
            "independent_user_evidence": strength.independent_user_evidence,
            "recent_verification": strength.recent_verification,
            "negative_transfer": strength.negative_transfer,
            "contradiction": strength.contradiction,
            "version_staleness": strength.version_staleness,
            "updated_at": _postgres_timestamp(record.updated_at, "updated_at"),
            "content_hash": record.content_hash,
        }
        return await self._append_record(
            ctx,
            table="trimem_semantic_strengths",
            columns=_STRENGTH_COLUMNS,
            params=params,
            insert="""
              INSERT INTO trimem_semantic_strengths(
                id,org_id,namespace,graph_id,graph_kind,owner_user_id,semantic_node_id,
                support,successful_reuse,independent_user_evidence,recent_verification,
                negative_transfer,contradiction,version_staleness,updated_at,content_hash)
              VALUES(
                :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,
                :semantic_node_id,:support,:successful_reuse,:independent_user_evidence,
                :recent_verification,:negative_transfer,:contradiction,:version_staleness,
                :updated_at,:content_hash)
              ON CONFLICT (org_id,namespace,graph_id,semantic_node_id) DO UPDATE SET
                support=EXCLUDED.support,
                successful_reuse=EXCLUDED.successful_reuse,
                independent_user_evidence=EXCLUDED.independent_user_evidence,
                recent_verification=EXCLUDED.recent_verification,
                negative_transfer=EXCLUDED.negative_transfer,
                contradiction=EXCLUDED.contradiction,
                version_staleness=EXCLUDED.version_staleness,
                updated_at=EXCLUDED.updated_at,
                content_hash=EXCLUDED.content_hash
              WHERE trimem_semantic_strengths.id=EXCLUDED.id
                AND EXCLUDED.updated_at >= trimem_semantic_strengths.updated_at
                AND EXCLUDED.support >= trimem_semantic_strengths.support
                AND EXCLUDED.successful_reuse >= trimem_semantic_strengths.successful_reuse
                AND EXCLUDED.independent_user_evidence >=
                    trimem_semantic_strengths.independent_user_evidence
                AND EXCLUDED.recent_verification >=
                    trimem_semantic_strengths.recent_verification
                AND EXCLUDED.negative_transfer >= trimem_semantic_strengths.negative_transfer
                AND EXCLUDED.contradiction >= trimem_semantic_strengths.contradiction
                AND EXCLUDED.version_staleness >= trimem_semantic_strengths.version_staleness
            """,
            loader=_strength,
            label="semantic strength",
            expected_hash=record.content_hash,
        )

    async def get_semantic_strength(
        self, ctx: AccessContext, strength_id: str
    ) -> SemanticStrengthRecord:
        return await self._get(
            ctx,
            "trimem_semantic_strengths",
            _STRENGTH_COLUMNS,
            strength_id,
            _strength,
            "semantic strength",
        )

    async def list_semantic_strengths(
        self, ctx: AccessContext, *, graph_id: Optional[str] = None
    ) -> list[SemanticStrengthRecord]:
        clauses, params = [], {}
        if graph_id is not None:
            clauses.append("graph_id=:graph_id")
            params["graph_id"] = graph_id
        async with self._tenant_tx(ctx) as conn:
            return await self._many(
                conn,
                table="trimem_semantic_strengths",
                columns=_STRENGTH_COLUMNS,
                ctx=ctx,
                loader=_strength,
                label="semantic strength",
                clauses=clauses,
                params=params,
                order="updated_at,id",
            )

    async def increment_semantic_strength(
        self, ctx: AccessContext, increment: SemanticStrengthIncrement
    ) -> SemanticStrengthRecord:
        """Lock and increment a semantic-strength row without lost updates."""

        _require_partition(
            ctx,
            org_id=increment.org_id,
            namespace=increment.namespace,
            expected_namespace=self.namespace,
            graph_kind=increment.graph_kind,
            owner_user_id=increment.owner_user_id,
        )
        params = {
            "org_id": increment.org_id,
            "namespace": increment.namespace,
            "graph_id": increment.graph_id,
            "graph_kind": increment.graph_kind.value,
            "owner_user_id": increment.owner_user_id,
            "semantic_node_id": increment.semantic_node_id,
        }
        async with self._tenant_tx(ctx) as conn:
            owner_predicate = (
                "owner_user_id IS NULL"
                if increment.graph_kind == GraphKind.ORGANISATION_SEMANTIC
                else "owner_user_id=:owner_user_id"
            )
            result = await conn.execute(
                text(
                    "SELECT %s FROM trimem_semantic_strengths "
                    "WHERE org_id=:org_id AND namespace=:namespace "
                    "AND graph_id=:graph_id AND graph_kind=:graph_kind "
                    "AND %s AND semantic_node_id=:semantic_node_id FOR UPDATE"
                    % (_STRENGTH_COLUMNS, owner_predicate)
                ),
                params,
            )
            rows = result.mappings().all()
            if len(rows) != 1:
                raise NotFound("semantic strength unavailable")
            current = _strength(rows[0])
            value = current.strength
            replacement = SemanticStrengthRecord(
                strength_id=current.strength_id,
                graph_id=current.graph_id,
                semantic_node_id=current.semantic_node_id,
                org_id=current.org_id,
                namespace=current.namespace,
                graph_kind=current.graph_kind,
                owner_user_id=current.owner_user_id,
                strength=SemanticStrength(
                    support=value.support,
                    successful_reuse=(
                        value.successful_reuse + float(increment.successful_reuse)
                    ),
                    independent_user_evidence=value.independent_user_evidence,
                    recent_verification=(
                        value.recent_verification + float(increment.recent_verification)
                    ),
                    negative_transfer=(
                        value.negative_transfer + float(increment.negative_transfer)
                    ),
                    contradiction=value.contradiction + float(increment.contradiction),
                    version_staleness=(
                        value.version_staleness + float(increment.version_staleness)
                    ),
                ),
                updated_at=increment.updated_at,
            )
            return await self.put_semantic_strength(ctx, replacement)

    async def claim_namespace(
        self,
        ctx: AccessContext,
        *,
        experiment_id: str,
        split: str,
        arm_id: str,
        task_order_hash: str,
        config_hash: str,
        run_nonce: str,
    ) -> NamespaceClaim:
        """Atomically claim, or reload the exact same untouched claim.

        The cursor-zero reload closes the crash window between the PostgreSQL
        commit and the caller's first local freshness receipt.  Any identity,
        nonce, state, or cursor mismatch remains non-disclosing and fatal.
        """
        values = {
            "experiment_id": experiment_id,
            "split": split,
            "arm_id": arm_id,
            "task_order_hash": task_order_hash,
            "config_hash": config_hash,
            "run_nonce": run_nonce,
        }
        for name, value in values.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError("%s is required" % name)
        for name in ("task_order_hash", "config_hash"):
            value = values[name]
            if len(value) != 71 or not value.startswith("sha256:"):
                raise ValueError("%s must be a canonical sha256 digest" % name)
        values["run_nonce"] = _uuid_identifier(run_nonce, "run_nonce")
        params = {
            "org_id": ctx.org_id,
            "namespace": self.namespace,
            "owner_user_id": ctx.user_id,
            "next_sequence_index": 0,
            **values,
        }
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(text("""
                INSERT INTO trimem_namespace_claims(
                  org_id,namespace,owner_user_id,experiment_id,split,arm_id,
                  task_order_hash,config_hash,run_nonce)
                VALUES(
                  :org_id,:namespace,:owner_user_id,:experiment_id,:split,:arm_id,
                  :task_order_hash,:config_hash,:run_nonce)
                ON CONFLICT (org_id,namespace) DO NOTHING
                RETURNING namespace,experiment_id,split,arm_id,task_order_hash,config_hash,
                          run_nonce,next_sequence_index,claim_status
            """), params)
            row = result.mappings().first()
            if row is None:
                result = await conn.execute(text("""
                    SELECT namespace,experiment_id,split,arm_id,task_order_hash,config_hash,
                           run_nonce,next_sequence_index,claim_status
                    FROM trimem_namespace_claims
                    WHERE org_id=:org_id AND namespace=:namespace
                      AND owner_user_id=:owner_user_id AND experiment_id=:experiment_id
                      AND split=:split AND arm_id=:arm_id
                      AND task_order_hash=:task_order_hash AND config_hash=:config_hash
                      AND run_nonce=:run_nonce AND next_sequence_index=0
                      AND claim_status='ACTIVE'
                """), params)
                row = result.mappings().first()
                if row is None:
                    raise IntegrityViolation("memory namespace is already claimed")
        return _namespace_claim(row)

    async def resume_namespace(
        self,
        ctx: AccessContext,
        *,
        experiment_id: str,
        split: str,
        arm_id: str,
        task_order_hash: str,
        config_hash: str,
        run_nonce: str,
        expected_next_sequence_index: int,
    ) -> NamespaceClaim:
        """Reload an exact active claim without disclosing mismatched claims."""
        if type(expected_next_sequence_index) is not int or expected_next_sequence_index < 0:
            raise ValueError("expected_next_sequence_index must be non-negative")
        run_nonce = _uuid_identifier(run_nonce, "run_nonce")
        params = {
            "org_id": ctx.org_id,
            "namespace": self.namespace,
            "owner_user_id": ctx.user_id,
            "experiment_id": experiment_id,
            "split": split,
            "arm_id": arm_id,
            "task_order_hash": task_order_hash,
            "config_hash": config_hash,
            "run_nonce": run_nonce,
            "next_sequence_index": expected_next_sequence_index,
        }
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(text("""
                SELECT namespace,experiment_id,split,arm_id,task_order_hash,config_hash,
                       run_nonce,next_sequence_index,claim_status
                FROM trimem_namespace_claims
                WHERE org_id=:org_id AND namespace=:namespace
                  AND owner_user_id=:owner_user_id AND experiment_id=:experiment_id
                  AND split=:split AND arm_id=:arm_id AND task_order_hash=:task_order_hash
                  AND config_hash=:config_hash AND run_nonce=:run_nonce
                  AND next_sequence_index=:next_sequence_index AND claim_status='ACTIVE'
            """), params)
            row = result.mappings().first()
            if row is None:
                raise NotFound("active memory namespace claim not found")
        return _namespace_claim(row)

    async def advance_namespace(
        self,
        ctx: AccessContext,
        *,
        run_nonce: str,
        expected_current: int,
        next_sequence_index: int,
    ) -> NamespaceClaim:
        """CAS-advance the frozen stream after a durable task commit."""
        run_nonce = _uuid_identifier(run_nonce, "run_nonce")
        if (
            type(expected_current) is not int
            or type(next_sequence_index) is not int
            or expected_current < 0
            or next_sequence_index != expected_current + 1
        ):
            raise ValueError("namespace sequence must advance by exactly one")
        params = {
            "org_id": ctx.org_id,
            "namespace": self.namespace,
            "owner_user_id": ctx.user_id,
            "run_nonce": run_nonce,
            "expected_current": expected_current,
            "next_sequence_index": next_sequence_index,
        }
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(text("""
                UPDATE trimem_namespace_claims
                SET next_sequence_index=:next_sequence_index, updated_at=now()
                WHERE org_id=:org_id AND namespace=:namespace
                  AND owner_user_id=:owner_user_id AND run_nonce=:run_nonce
                  AND next_sequence_index=:expected_current AND claim_status='ACTIVE'
                RETURNING namespace,experiment_id,split,arm_id,task_order_hash,config_hash,
                          run_nonce,next_sequence_index,claim_status
            """), params)
            row = result.mappings().first()
            if row is None:
                raise IntegrityViolation("memory namespace sequence advance conflict")
        return _namespace_claim(row)

    async def advance_namespace_with_checkpoint(
        self,
        ctx: AccessContext,
        *,
        run_nonce: str,
        expected_current: int,
        next_sequence_index: int,
        checkpoint_payload: Mapping[str, Any],
        checkpoint_digest: str,
    ) -> tuple[NamespaceClaim, SessionCheckpoint]:
        """CAS-advance and journal the exact recovery envelope atomically."""

        run_nonce = _uuid_identifier(run_nonce, "run_nonce")
        if not isinstance(checkpoint_payload, Mapping):
            raise TypeError("checkpoint_payload must be a mapping")
        if (
            type(expected_current) is not int
            or type(next_sequence_index) is not int
            or expected_current < 0
            or next_sequence_index != expected_current + 1
        ):
            raise ValueError("namespace sequence must advance by exactly one")
        payload = dict(checkpoint_payload)
        checkpoint_schema = payload.get("schema")
        if not isinstance(checkpoint_schema, str) or not checkpoint_schema:
            raise ValueError("checkpoint payload schema is required")
        if (
            payload.get("namespace") != self.namespace
            or payload.get("run_nonce") != run_nonce
            or payload.get("next_sequence_index") != next_sequence_index
        ):
            raise IntegrityViolation("checkpoint payload identity mismatch")
        if canonical_hash(payload) != checkpoint_digest:
            raise IntegrityViolation("checkpoint payload digest mismatch")
        checkpoint_id = str(
            uuid.uuid5(
                _OUTBOX_ID_NAMESPACE,
                "session-checkpoint|%s|%s|%s|%d"
                % (ctx.org_id, self.namespace, run_nonce, next_sequence_index),
            )
        )
        params = {
            "id": checkpoint_id,
            "org_id": ctx.org_id,
            "namespace": self.namespace,
            "owner_user_id": ctx.user_id,
            "run_nonce": run_nonce,
            "next_sequence_index": next_sequence_index,
            "checkpoint_schema": checkpoint_schema,
            "checkpoint_payload": json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ),
            "checkpoint_digest": checkpoint_digest,
        }
        async with self._tenant_tx(ctx) as conn:
            claim_result = await conn.execute(
                text("""
                    UPDATE trimem_namespace_claims
                    SET next_sequence_index=:next_sequence_index, updated_at=now()
                    WHERE org_id=:org_id AND namespace=:namespace
                      AND owner_user_id=:owner_user_id AND run_nonce=:run_nonce
                      AND next_sequence_index=:expected_current AND claim_status='ACTIVE'
                    RETURNING namespace,experiment_id,split,arm_id,task_order_hash,
                              config_hash,run_nonce,next_sequence_index,claim_status
                """),
                {
                    "org_id": ctx.org_id,
                    "namespace": self.namespace,
                    "owner_user_id": ctx.user_id,
                    "run_nonce": run_nonce,
                    "expected_current": expected_current,
                    "next_sequence_index": next_sequence_index,
                },
            )
            claim_row = claim_result.mappings().first()
            if claim_row is None:
                raise IntegrityViolation("memory namespace sequence advance conflict")
            claim = _namespace_claim(claim_row)
            result = await conn.execute(
                text("""
                    INSERT INTO trimem_session_checkpoints(
                      id,org_id,namespace,owner_user_id,run_nonce,next_sequence_index,
                      checkpoint_schema,checkpoint_payload,checkpoint_digest)
                    VALUES(
                      :id,:org_id,:namespace,:owner_user_id,:run_nonce,:next_sequence_index,
                      :checkpoint_schema,cast(:checkpoint_payload as jsonb),:checkpoint_digest)
                    RETURNING %s
                """ % _SESSION_CHECKPOINT_COLUMNS),
                params,
            )
            row = result.mappings().first()
            if row is None:
                raise IntegrityViolation("session checkpoint insert failed")
        try:
            checkpoint = _session_checkpoint(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("session checkpoint reload failed") from exc
        if (
            checkpoint.checkpoint_id != checkpoint_id
            or checkpoint.org_id != ctx.org_id
            or checkpoint.namespace != self.namespace
            or checkpoint.owner_user_id != ctx.user_id
            or checkpoint.run_nonce != run_nonce
            or checkpoint.next_sequence_index != next_sequence_index
        ):
            raise CanonicalReloadError("session checkpoint partition mismatch")
        return claim, checkpoint

    async def load_latest_session_checkpoint(
        self, ctx: AccessContext, *, run_nonce: str
    ) -> SessionCheckpoint:
        run_nonce = _uuid_identifier(run_nonce, "run_nonce")
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("SELECT %s FROM trimem_session_checkpoints "
                     "WHERE org_id=:org_id AND namespace=:namespace "
                     "AND owner_user_id=:owner_user_id AND run_nonce=:run_nonce "
                     "ORDER BY next_sequence_index DESC LIMIT 1"
                     % _SESSION_CHECKPOINT_COLUMNS),
                {
                    "org_id": ctx.org_id,
                    "namespace": self.namespace,
                    "owner_user_id": ctx.user_id,
                    "run_nonce": run_nonce,
                },
            )
            row = result.mappings().first()
        if row is None:
            raise NotFound("session checkpoint not found")
        try:
            return _session_checkpoint(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("session checkpoint reload failed") from exc

    async def namespace_evidence(self, ctx: AccessContext) -> NamespaceEvidence:
        """Return deterministic exact-namespace canonical row counts."""
        counts = await self._canonical_row_counts(ctx)
        frozen = tuple((table, counts[table]) for table in _CANONICAL_TABLES)
        return NamespaceEvidence(
            namespace=self.namespace,
            row_counts=frozen,
            digest=canonical_hash({"namespace": self.namespace, "row_counts": frozen}),
        )

    async def _lock_canonical_operation(self, ctx: AccessContext) -> None:
        """Serialize namespace mutations while an operation receipt is measured."""

        async with self._tenant_tx(ctx) as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key,0))"),
                {
                    "lock_key": "trimem-canonical-operation|%s|%s"
                    % (ctx.org_id, self.namespace)
                },
            )

    async def _canonical_row_counts(self, ctx: AccessContext) -> dict[str, int]:
        counts: dict[str, int] = {}
        async with self._tenant_tx(ctx) as conn:
            for table in _CANONICAL_TABLES:
                result = await conn.execute(
                    text("SELECT count(*) AS row_count FROM %s WHERE org_id=:org_id "
                         "AND namespace=:namespace" % table),
                    {"org_id": ctx.org_id, "namespace": self.namespace},
                )
                row = result.mappings().first()
                if row is None:
                    raise CanonicalReloadError("namespace count reload failed")
                count = int(_mapping(row)["row_count"])
                if count < 0:
                    raise CanonicalReloadError("namespace count cannot be negative")
                counts[table] = count
        return counts

    async def _canonical_mutable_tokens(
        self, ctx: AccessContext
    ) -> dict[str, dict[str, str]]:
        """Snapshot mutable canonical rows for exact update attribution.

        Lifecycle transactions never physically delete canonical rows.  Only
        node archival, semantic-strength replacement, and outbox status
        transitions mutate existing rows; all other 0015 operation rows are
        append-only or insert-once.  Stable content/status tokens therefore
        distinguish an inserted row from an actually changed existing row.
        """

        specs = {
            "trimem_graph_nodes": "id,content_hash",
            "trimem_semantic_strengths": "id,content_hash",
            "trimem_vector_index_outbox": (
                "id,status,attempts,last_error,indexed_at,updated_at"
            ),
        }
        snapshots: dict[str, dict[str, str]] = {}
        async with self._tenant_tx(ctx) as conn:
            for table, columns in specs.items():
                result = await conn.execute(
                    text(
                        "SELECT %s FROM %s WHERE org_id=:org_id AND namespace=:namespace "
                        "ORDER BY id" % (columns, table)
                    ),
                    {"org_id": ctx.org_id, "namespace": self.namespace},
                )
                rows: dict[str, str] = {}
                for raw in result.mappings().all():
                    item = _mapping(raw)
                    row_id = str(item.get("id", ""))
                    if not row_id:
                        raise CanonicalReloadError("canonical mutable row lacks identity")
                    if table == "trimem_vector_index_outbox":
                        token = canonical_hash(
                            {
                                name: (
                                    None
                                    if item.get(name) is None
                                    else str(item.get(name))
                                )
                                for name in (
                                    "status",
                                    "attempts",
                                    "last_error",
                                    "indexed_at",
                                    "updated_at",
                                )
                            }
                        )
                    else:
                        token = str(item.get("content_hash", ""))
                        if not token:
                            raise CanonicalReloadError(
                                "canonical mutable row lacks content hash"
                            )
                    rows[row_id] = token
                snapshots[table] = rows
        return snapshots

    @staticmethod
    def _build_canonical_row_deltas(
        *,
        before_counts: Mapping[str, int],
        after_counts: Mapping[str, int],
        before_tokens: Mapping[str, Mapping[str, str]],
        after_tokens: Mapping[str, Mapping[str, str]],
        receipt_inserted: bool,
    ) -> dict[str, dict[str, int]]:
        if set(before_counts) != set(_CANONICAL_TABLES) or set(after_counts) != set(
            _CANONICAL_TABLES
        ):
            raise CanonicalReloadError("canonical row-count snapshot shape mismatch")
        deltas: dict[str, dict[str, int]] = {}
        for table in _CANONICAL_TABLES:
            inserted = int(after_counts[table]) - int(before_counts[table])
            if table == "trimem_lifecycle_operation_receipts" and receipt_inserted:
                inserted += 1
            if inserted < 0:
                raise CanonicalReloadError(
                    "canonical lifecycle transaction physically deleted a row"
                )
            prior = before_tokens.get(table, {})
            current = after_tokens.get(table, {})
            deleted_ids = set(prior) - set(current)
            if deleted_ids:
                raise CanonicalReloadError(
                    "canonical lifecycle transaction physically deleted mutable rows"
                )
            updated = sum(
                1
                for row_id in set(prior) & set(current)
                if prior[row_id] != current[row_id]
            )
            deltas[table] = {
                "inserted": inserted,
                "updated": updated,
                "deleted": 0,
            }
        return deltas

    @staticmethod
    def _validate_canonical_row_deltas(
        value: object,
    ) -> dict[str, dict[str, int]]:
        if not isinstance(value, Mapping) or set(value) != set(_CANONICAL_TABLES):
            raise CanonicalReloadError("canonical row deltas have an invalid table set")
        normalized: dict[str, dict[str, int]] = {}
        for table in _CANONICAL_TABLES:
            delta = value.get(table)
            if not isinstance(delta, Mapping) or set(delta) != {
                "inserted",
                "updated",
                "deleted",
            }:
                raise CanonicalReloadError("canonical row delta has an invalid shape")
            values = {name: delta.get(name) for name in ("inserted", "updated", "deleted")}
            if any(type(item) is not int or item < 0 for item in values.values()):
                raise CanonicalReloadError("canonical row delta must be non-negative integers")
            normalized[table] = {name: int(item) for name, item in values.items()}
        if normalized["trimem_lifecycle_operation_receipts"]["inserted"] != 1:
            raise CanonicalReloadError("operation receipt delta must append exactly one row")
        if any(delta["deleted"] for delta in normalized.values()):
            raise CanonicalReloadError("lifecycle operations cannot physically delete rows")
        return normalized

    async def _insert_vector_outbox_intent(
        self,
        ctx: AccessContext,
        node: GraphNode,
        *,
        operation: str,
        prior_content_hash: Optional[str] = None,
    ) -> IndexOutboxIntent:
        _require_partition(
            ctx,
            org_id=node.org_id,
            namespace=node.namespace,
            expected_namespace=self.namespace,
            graph_kind=node.graph_kind,
            owner_user_id=node.owner_user_id,
        )
        if node.graph_kind == GraphKind.SHORT_TERM_WORKING:
            raise IntegrityViolation("working graph node cannot be indexed")
        if operation not in {"UPSERT", "DELETE"}:
            raise ValueError("invalid vector index operation")
        if not node.verify_hash():
            raise CanonicalReloadError("vector intent requires a canonical node")
        if operation == "UPSERT":
            if node.lifecycle_state != LifecycleState.ACTIVE or prior_content_hash is not None:
                raise CanonicalReloadError("upsert intent requires an active canonical node")
        elif (
            node.lifecycle_state == LifecycleState.ACTIVE
            or prior_content_hash is None
            or node.archived_from_content_hash != prior_content_hash
        ):
            raise CanonicalReloadError("delete intent requires archived-node provenance")
        stable_key = "|".join(
            (
                node.org_id,
                node.namespace,
                node.graph_id,
                node.node_id,
                operation,
                node.content_hash,
            )
        )
        params = {
            "id": str(uuid.uuid5(_OUTBOX_ID_NAMESPACE, stable_key)),
            "org_id": node.org_id,
            "namespace": node.namespace,
            "graph_id": node.graph_id,
            "graph_kind": node.graph_kind.value,
            "owner_user_id": node.owner_user_id,
            "node_id": node.node_id,
            "operation": operation,
            "canonical_content_hash": node.content_hash,
            "prior_content_hash": prior_content_hash,
        }
        async with self._tenant_tx(ctx) as conn:
            await conn.execute(
                text("""
                    INSERT INTO trimem_vector_index_outbox(
                      id,org_id,namespace,graph_id,graph_kind,owner_user_id,node_id,
                      operation,canonical_content_hash,prior_content_hash)
                    VALUES(
                      :id,:org_id,:namespace,:graph_id,:graph_kind,:owner_user_id,:node_id,
                      :operation,:canonical_content_hash,:prior_content_hash)
                    ON CONFLICT (id) DO NOTHING
                """),
                params,
            )
            result = await conn.execute(
                text("SELECT %s FROM trimem_vector_index_outbox "
                     "WHERE id=:id AND %s" % (_OUTBOX_COLUMNS, _SCOPE)),
                {**params, **_scope_params(ctx, self.namespace)},
            )
            row = result.mappings().first()
            if row is None:
                raise IntegrityViolation("vector index intent identifier is unavailable")
        try:
            intent = _outbox_intent(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("vector index outbox reload failed") from exc
        expected = (
            params["id"],
            node.org_id,
            node.namespace,
            node.graph_id,
            node.graph_kind,
            node.owner_user_id,
            node.node_id,
            operation,
            node.content_hash,
            prior_content_hash,
        )
        observed = (
            intent.intent_id,
            intent.org_id,
            intent.namespace,
            intent.graph_id,
            intent.graph_kind,
            intent.owner_user_id,
            intent.node_id,
            intent.operation,
            intent.canonical_content_hash,
            intent.prior_content_hash,
        )
        if observed != expected:
            raise IntegrityViolation("vector index intent identifier is already bound")
        return intent

    async def _insert_index_outbox_intent(
        self, ctx: AccessContext, node: GraphNode
    ) -> IndexOutboxIntent:
        return await self._insert_vector_outbox_intent(
            ctx, node, operation="UPSERT"
        )

    async def get_index_outbox_intent(
        self, ctx: AccessContext, intent_id: str
    ) -> IndexOutboxIntent:
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("SELECT %s FROM trimem_vector_index_outbox "
                     "WHERE id=:id AND %s" % (_OUTBOX_COLUMNS, _SCOPE)),
                {
                    "id": intent_id,
                    **_scope_params(ctx, self.namespace),
                },
            )
            row = result.mappings().first()
        if row is None:
            raise NotFound("vector index intent not found")
        try:
            return _outbox_intent(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("vector index outbox reload failed") from exc

    async def list_index_outbox(
        self, ctx: AccessContext, *, status: str = "PENDING", limit: int = 100
    ) -> tuple[IndexOutboxIntent, ...]:
        if status not in {"PENDING", "INDEXED", "CANCELLED"}:
            raise ValueError("invalid vector index outbox status")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("outbox limit must be between 1 and 1000")
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("SELECT %s FROM trimem_vector_index_outbox "
                     "WHERE %s AND status=:status ORDER BY created_at,id LIMIT :limit"
                     % (_OUTBOX_COLUMNS, _SCOPE)),
                {
                    **_scope_params(ctx, self.namespace),
                    "status": status,
                    "limit": limit,
                },
            )
            rows = result.mappings().all()
        try:
            return tuple(_outbox_intent(row) for row in rows)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("vector index outbox reload failed") from exc

    async def _cancel_pending_upsert_intents(
        self, ctx: AccessContext, *, node: GraphNode, prior_content_hash: str
    ) -> tuple[IndexOutboxIntent, ...]:
        params = {
            "node_id": node.node_id,
            "canonical_content_hash": prior_content_hash,
            **_scope_params(ctx, self.namespace),
        }
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("UPDATE trimem_vector_index_outbox "
                     "SET status='CANCELLED',last_error=NULL,updated_at=now() "
                     "WHERE node_id=:node_id AND operation='UPSERT' "
                     "AND canonical_content_hash=:canonical_content_hash "
                     "AND status='PENDING' AND %s RETURNING %s"
                     % (_SCOPE, _OUTBOX_COLUMNS)),
                params,
            )
            rows = result.mappings().all()
        try:
            return tuple(_outbox_intent(row) for row in rows)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("cancelled vector outbox reload failed") from exc

    async def mark_index_outbox_indexed(
        self, ctx: AccessContext, *, intent_id: str, canonical_content_hash: str
    ) -> IndexOutboxIntent:
        params = {
            "id": intent_id,
            "canonical_content_hash": canonical_content_hash,
            **_scope_params(ctx, self.namespace),
        }
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("UPDATE trimem_vector_index_outbox "
                     "SET status='INDEXED',attempts=attempts+1,last_error=NULL,"
                     "indexed_at=now(),updated_at=now() "
                     "WHERE id=:id AND canonical_content_hash=:canonical_content_hash "
                     "AND status='PENDING' AND %s RETURNING %s" % (_SCOPE, _OUTBOX_COLUMNS)),
                params,
            )
            row = result.mappings().first()
        if row is None:
            existing = await self.get_index_outbox_intent(ctx, intent_id)
            if (
                existing.status == "INDEXED"
                and existing.canonical_content_hash == canonical_content_hash
            ):
                return existing
            raise IntegrityViolation("vector index intent completion conflict")
        try:
            return _outbox_intent(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("vector index outbox reload failed") from exc

    async def mark_index_outbox_failed(
        self,
        ctx: AccessContext,
        *,
        intent_id: str,
        canonical_content_hash: str,
        error_code: str,
    ) -> IndexOutboxIntent:
        if (
            not isinstance(error_code, str)
            or not 1 <= len(error_code) <= 160
            or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
                   for character in error_code)
        ):
            raise ValueError("error_code must be a sanitized stable code")
        params = {
            "id": intent_id,
            "canonical_content_hash": canonical_content_hash,
            "last_error": error_code,
            **_scope_params(ctx, self.namespace),
        }
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("UPDATE trimem_vector_index_outbox "
                     "SET attempts=attempts+1,last_error=:last_error,updated_at=now() "
                     "WHERE id=:id AND canonical_content_hash=:canonical_content_hash "
                     "AND status='PENDING' AND %s RETURNING %s" % (_SCOPE, _OUTBOX_COLUMNS)),
                params,
            )
            row = result.mappings().first()
        if row is None:
            raise IntegrityViolation("vector index intent failure update conflict")
        try:
            return _outbox_intent(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("vector index outbox reload failed") from exc

    async def _archive_canonical_node(
        self,
        ctx: AccessContext,
        node: GraphNode,
        *,
        archived_at: str,
        reason: str,
    ) -> tuple[GraphNode, IndexOutboxIntent]:
        prior_content_hash = node.content_hash
        archived = node.archived(archived_at, reason)
        params = {
            "id": node.node_id,
            "org_id": node.org_id,
            "namespace": node.namespace,
            "owner_user_id": node.owner_user_id,
            "graph_kind": node.graph_kind.value,
            "prior_content_hash": prior_content_hash,
            "payload_hash": archived.payload_hash,
            "archived_at": _postgres_timestamp(archived.archived_at, "archived_at"),
            "archive_reason": archived.archive_reason,
            "archived_from_content_hash": archived.archived_from_content_hash,
            "content_hash": archived.content_hash,
        }
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("""
                    UPDATE trimem_graph_nodes
                    SET lifecycle_state='ARCHIVED',canonical_payload='{}'::jsonb,
                        payload_hash=:payload_hash,archived_at=:archived_at,
                        archive_reason=:archive_reason,
                        archived_from_content_hash=:archived_from_content_hash,
                        content_hash=:content_hash
                    WHERE id=:id AND lifecycle_state='ACTIVE'
                      AND content_hash=:prior_content_hash AND %s
                    RETURNING %s
                """ % (_SCOPE, _NODE_COLUMNS)),
                params,
            )
            row = result.mappings().first()
            if row is None:
                raise IntegrityViolation("capacity archive conflict")
        loaded = _checked(_node, row, "archived node")
        if loaded != archived:
            raise CanonicalReloadError("capacity archive canonical reload mismatch")
        await self._cancel_pending_upsert_intents(
            ctx, node=loaded, prior_content_hash=prior_content_hash
        )
        delete_intent = await self._insert_vector_outbox_intent(
            ctx,
            loaded,
            operation="DELETE",
            prior_content_hash=prior_content_hash,
        )
        return loaded, delete_intent

    async def enforce_capacity(
        self,
        ctx: AccessContext,
        *,
        limits: CapacityLimits,
        archived_at: str,
    ) -> tuple[tuple[GraphNode, ...], tuple[IndexOutboxIntent, ...]]:
        """Atomically archive deterministic overflow and enqueue Qdrant deletes."""

        if not isinstance(limits, CapacityLimits):
            raise TypeError("limits must be CapacityLimits")
        if not isinstance(archived_at, str) or not archived_at:
            raise ValueError("capacity archived_at is required")
        try:
            parsed = datetime.fromisoformat(
                archived_at[:-1] + "+00:00" if archived_at.endswith("Z") else archived_at
            )
        except ValueError as exc:
            raise ValueError("capacity archived_at must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("capacity archived_at must include a timezone")
        canonical_archived_at = (
            parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )

        partitions = (
            (
                GraphKind.USER_EPISODIC,
                limits.episodic_per_user,
                "episodic_fifo_capacity",
                "COALESCE(n.event_time,n.ingested_at),n.id",
            ),
            (
                GraphKind.USER_SEMANTIC,
                limits.user_semantic_per_user,
                "semantic_strength_capacity",
                "COALESCE(s.strength_score,0),n.id",
            ),
            (
                GraphKind.ORGANISATION_SEMANTIC,
                limits.organisation_semantic,
                "semantic_strength_capacity",
                "COALESCE(s.strength_score,0),n.id",
            ),
        )
        archived_nodes: list[GraphNode] = []
        delete_intents: list[IndexOutboxIntent] = []
        async with self._tenant_tx(ctx) as conn:
            for kind, capacity, reason, ordering in partitions:
                lock_owner = ctx.user_id if kind in PRIVATE_GRAPH_KINDS else "shared"
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key,0))"),
                    {
                        "lock_key": "|".join(
                            (ctx.org_id, self.namespace, kind.value, lock_owner)
                        )
                    },
                )
                join = ""
                if kind in SEMANTIC_GRAPH_KINDS:
                    join = (
                        " LEFT JOIN trimem_semantic_strengths s"
                        " ON s.org_id=n.org_id AND s.namespace=n.namespace"
                        " AND s.graph_id=n.graph_id AND s.semantic_node_id=n.id"
                    )
                owner = " AND n.owner_user_id=:owner_user_id" if kind in PRIVATE_GRAPH_KINDS else ""
                result = await conn.execute(
                    text(
                        "SELECT n.id FROM trimem_graph_nodes n%s "
                        "WHERE n.org_id=:org_id AND n.namespace=:namespace "
                        "AND n.graph_kind=:graph_kind%s AND n.lifecycle_state='ACTIVE' "
                        "AND n.node_type=:node_type ORDER BY %s FOR UPDATE OF n"
                        % (join, owner, ordering)
                    ),
                    {
                        "org_id": ctx.org_id,
                        "namespace": self.namespace,
                        "owner_user_id": ctx.user_id,
                        "graph_kind": kind.value,
                        "node_type": (
                            NodeType.EPISODE.value
                            if kind == GraphKind.USER_EPISODIC
                            else NodeType.SEMANTIC_RULE.value
                        ),
                    },
                )
                ordered_ids = [str(_mapping(row)["id"]) for row in result.mappings().all()]
                victim_ids = ordered_ids[: max(0, len(ordered_ids) - capacity)]
                for node_id in victim_ids:
                    node = await self.get_node(ctx, node_id)
                    archived, intent = await self._archive_canonical_node(
                        ctx, node, archived_at=canonical_archived_at, reason=reason
                    )
                    archived_nodes.append(archived)
                    delete_intents.append(intent)
        return tuple(archived_nodes), tuple(delete_intents)

    async def _append_promotion_evidence_for_node(
        self, ctx: AccessContext, node: GraphNode
    ) -> Optional[PromotionEvidence]:
        if (
            node.graph_kind != GraphKind.USER_EPISODIC
            or node.node_type != NodeType.EPISODE
            or node.lifecycle_state != LifecycleState.ACTIVE
        ):
            return None
        payload = node.canonical_payload
        if payload.get("verified") is not True or payload.get("source_outcome") != "passed":
            return None
        provenance = payload.get("provenance")
        if not isinstance(provenance, Mapping):
            raise IntegrityViolation("verified episode lacks promotion provenance")
        digests = {
            "contributor_hash": provenance.get("contributor_hash"),
            "public_evidence_hash": provenance.get("public_evidence_hash"),
            "verifier_hash": provenance.get("verifier_hash"),
            "extraction_hash": provenance.get("extraction_hash"),
        }
        for name, value in digests.items():
            if (
                not isinstance(value, str)
                or len(value) != 71
                or not value.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                raise IntegrityViolation("verified episode has invalid %s" % name)
        verified_at = node.temporal.last_verified_at
        if not isinstance(verified_at, str) or not verified_at:
            raise IntegrityViolation("verified episode lacks verification time")
        try:
            parsed_verified_at = datetime.fromisoformat(
                verified_at[:-1] + "+00:00"
                if verified_at.endswith("Z")
                else verified_at
            )
        except ValueError as exc:
            raise IntegrityViolation("verified episode has invalid verification time") from exc
        if parsed_verified_at.tzinfo is None or parsed_verified_at.utcoffset() is None:
            raise IntegrityViolation("verified episode verification time lacks timezone")
        verified_at = (
            parsed_verified_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
        expected_contributor_hash = canonical_hash(
            {
                "schema": "trimem/promotion-contributor/1.0",
                "org_id": ctx.org_id,
                "user_id": ctx.user_id,
            }
        )
        contributor_hash = str(digests.pop("contributor_hash"))
        if contributor_hash != expected_contributor_hash:
            raise IntegrityViolation("verified episode contributor attestation mismatch")
        attestation = {
            "schema": "trimem/promotion-evidence/1.0",
            "namespace": self.namespace,
            "evidence_hash": node.payload_hash,
            "contributor_hash": contributor_hash,
            "source_kind": "VERIFIED_EPISODE",
            "source_outcome": "passed",
            "verified": True,
            **digests,
            "verified_at": verified_at,
        }
        attestation_hash = canonical_hash(attestation)
        evidence_id = str(
            uuid.uuid5(
                _OUTBOX_ID_NAMESPACE,
                "promotion-evidence|%s|%s|%s"
                % (ctx.org_id, self.namespace, attestation_hash),
            )
        )
        params = {
            "id": evidence_id,
            "org_id": ctx.org_id,
            "namespace": self.namespace,
            "evidence_hash": node.payload_hash,
            "contributor_hash": contributor_hash,
            "source_kind": "VERIFIED_EPISODE",
            "source_outcome": "passed",
            "verified": True,
            **digests,
            "attestation_hash": attestation_hash,
            "verified_at": _postgres_timestamp(verified_at, "verified_at"),
        }
        async with self._tenant_tx(ctx) as conn:
            await conn.execute(
                text("""
                    INSERT INTO trimem_promotion_evidence(
                      id,org_id,namespace,evidence_hash,contributor_hash,source_kind,
                      source_outcome,verified,public_evidence_hash,verifier_hash,
                      extraction_hash,attestation_hash,verified_at)
                    VALUES(
                      :id,:org_id,:namespace,:evidence_hash,:contributor_hash,:source_kind,
                      :source_outcome,:verified,:public_evidence_hash,:verifier_hash,
                      :extraction_hash,:attestation_hash,:verified_at)
                    ON CONFLICT (id) DO NOTHING
                """),
                params,
            )
            result = await conn.execute(
                text("SELECT %s FROM trimem_promotion_evidence "
                     "WHERE id=:id AND org_id=:org_id AND namespace=:namespace"
                     % _PROMOTION_EVIDENCE_COLUMNS),
                params,
            )
            row = result.mappings().first()
            if row is None:
                raise IntegrityViolation("promotion evidence identifier is unavailable")
        try:
            evidence = _promotion_evidence(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("promotion evidence reload failed") from exc
        if evidence.attestation_hash != attestation_hash:
            raise IntegrityViolation("promotion evidence identifier is already bound")
        return evidence

    async def verify_promotion_evidence(
        self, ctx: AccessContext, evidence_hashes: Sequence[str]
    ) -> tuple[PromotionEvidence, ...]:
        requested = tuple(evidence_hashes)
        if not requested or len(set(requested)) != len(requested):
            raise ValueError("promotion evidence hashes must be non-empty and unique")
        for value in requested:
            if (
                not isinstance(value, str)
                or len(value) != 71
                or not value.startswith("sha256:")
                or any(character not in "0123456789abcdef" for character in value[7:])
            ):
                raise ValueError("promotion evidence hash is invalid")
        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text("SELECT %s FROM trimem_promotion_evidence "
                     "WHERE org_id=:org_id AND namespace=:namespace "
                     "AND evidence_hash = ANY(:evidence_hashes) "
                     "ORDER BY evidence_hash,contributor_hash,id"
                     % _PROMOTION_EVIDENCE_COLUMNS),
                {
                    "org_id": ctx.org_id,
                    "namespace": self.namespace,
                    "evidence_hashes": list(requested),
                },
            )
            rows = result.mappings().all()
        try:
            evidence = tuple(_promotion_evidence(row) for row in rows)
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("promotion evidence reload failed") from exc
        if {item.evidence_hash for item in evidence} != set(requested):
            raise NotFound("promotion evidence is unavailable")
        return evidence

    async def load_retrieval_rows(
        self,
        ctx: AccessContext,
        *,
        kind: GraphKind,
        repository_id: Optional[str],
        references: Optional[Sequence[VectorReference]] = None,
    ) -> CanonicalReloadRows:
        """Reload a Qdrant shortlist from canonical PostgreSQL in one transaction."""
        if not isinstance(kind, GraphKind) or kind == GraphKind.SHORT_TERM_WORKING:
            raise ValueError("retrieval kind must be a durable graph kind")
        if not isinstance(repository_id, str) or not repository_id.strip():
            raise ValueError("target repository_id is required")

        def repository_is_eligible(value: Optional[str]) -> bool:
            if kind == GraphKind.USER_EPISODIC:
                return value == repository_id
            return value is None or value == repository_id

        shortlisted = references is not None
        refs = tuple(references or ())
        if len({ref.node_id for ref in refs}) != len(refs):
            raise IntegrityViolation("retrieval references contain duplicate node ids")
        for ref in refs:
            if not isinstance(ref, VectorReference):
                raise TypeError("references must be VectorReference records")
            if (
                ref.namespace != self.namespace
                or ref.org_id != ctx.org_id
                or ref.memory_kind != kind
                or (kind in PRIVATE_GRAPH_KINDS and ref.owner_user_id != ctx.user_id)
                or (kind == GraphKind.ORGANISATION_SEMANTIC and ref.owner_user_id is not None)
                or not repository_is_eligible(ref.repository_id)
            ):
                raise ScopeViolation("vector reference crosses canonical retrieval partition")

        async with self._tenant_tx(ctx):
            if shortlisted and refs:
                candidates = tuple([await self.get_node(ctx, ref.node_id) for ref in refs])
                for ref, node in zip(refs, candidates):
                    if (
                        node.content_hash != ref.content_hash
                        or node.graph_kind != kind
                        or node.repository_id != ref.repository_id
                        or not repository_is_eligible(node.repository_id)
                    ):
                        raise CanonicalReloadError("vector reference does not match canonical node")
                graph_ids = tuple(sorted({node.graph_id for node in candidates}))
                graphs = tuple([await self.get_graph(ctx, graph_id) for graph_id in graph_ids])
            elif shortlisted:
                graphs = ()
                graph_ids = ()
                candidates = ()
            else:
                graphs = tuple(
                    graph
                    for graph in await self.list_graphs(ctx, kind=kind)
                    if repository_is_eligible(graph.repository_id)
                )
                graph_ids = tuple(graph.graph_id for graph in graphs)
                candidates = ()

            for graph in graphs:
                if graph.kind != kind:
                    raise CanonicalReloadError("canonical graph kind mismatch")
                if not repository_is_eligible(graph.repository_id):
                    raise ScopeViolation("canonical graph repository mismatch")
            graph_by_id = {graph.graph_id: graph for graph in graphs}
            nodes_list = []
            edges_list = []
            for graph_id in graph_ids:
                nodes_list.extend(await self.list_nodes(ctx, graph_id=graph_id, include_archived=False))
                edges_list.extend(await self.list_edges(ctx, graph_id=graph_id))
            nodes = tuple(sorted(nodes_list, key=lambda item: item.node_id))
            edges = tuple(sorted(edges_list, key=lambda item: item.edge_id))
            for node in nodes:
                graph = graph_by_id.get(node.graph_id)
                if graph is None or node.repository_id != graph.repository_id:
                    raise CanonicalReloadError("canonical node repository partition mismatch")

        candidate_ids = (
            tuple(ref.node_id for ref in refs)
            if shortlisted
            else tuple(node.node_id for node in nodes)
        )
        seal = {
            "namespace": self.namespace,
            "kind": kind.value,
            "graphs": [(item.graph_id, item.content_hash) for item in graphs],
            "nodes": [(item.node_id, item.content_hash) for item in nodes],
            "edges": [(item.edge_id, item.content_hash) for item in edges],
            "candidate_node_ids": candidate_ids,
        }
        return CanonicalReloadRows(
            namespace=self.namespace,
            graph_kind=kind,
            graphs=tuple(sorted(graphs, key=lambda item: item.graph_id)),
            nodes=nodes,
            edges=edges,
            candidate_node_ids=candidate_ids,
            digest=canonical_hash(seal),
        )

    async def append_lifecycle_bundle(
        self, ctx: AccessContext, bundle: LifecycleAppendBundle
    ) -> AppendReceipt:
        """Commit one lifecycle decision and canonically reload it in one transaction."""
        if not isinstance(bundle, LifecycleAppendBundle):
            raise TypeError("bundle must be LifecycleAppendBundle")
        if len(set(bundle.index_node_ids)) != len(bundle.index_node_ids):
            raise IntegrityViolation("index_node_ids contains duplicates")
        if bundle.capacity_limits is None and bundle.capacity_archived_at is not None:
            raise ValueError("capacity_archived_at requires capacity_limits")
        operation_id = None
        bundle_digest = None
        if bundle.operation_id is not None:
            operation_id = _uuid_identifier(bundle.operation_id, "operation_id")
            self._validate_operation_scope(bundle.operation_scope)
            bundle_digest = canonical_hash(bundle)
        elif bundle.operation_scope is not None:
            raise ValueError("operation_scope requires operation_id")
        async with self._tenant_tx(ctx):
            before_counts: Mapping[str, int] = {}
            before_tokens: Mapping[str, Mapping[str, str]] = {}
            if operation_id is not None:
                await self._lock_canonical_operation(ctx)
                replay = await self._load_lifecycle_operation_receipt(
                    ctx, operation_id=operation_id, bundle_digest=str(bundle_digest)
                )
                if replay is not None:
                    return replay
                before_counts = await self._canonical_row_counts(ctx)
                before_tokens = await self._canonical_mutable_tokens(ctx)
            graphs = tuple([await self.put_graph(ctx, item) for item in bundle.graphs])
            nodes = tuple([await self.put_node(ctx, item) for item in bundle.nodes])
            promotion_evidence = tuple(
                evidence
                for evidence in [
                    await self._append_promotion_evidence_for_node(ctx, node)
                    for node in nodes
                ]
                if evidence is not None
            )
            for item in bundle.edges:
                await self.put_edge(ctx, item)
            for item in bundle.supports:
                await self.put_support(ctx, item)
            for item in bundle.transitions:
                await self.record_policy_transition(ctx, item)
            for item in bundle.checkpoints:
                await self.save_checkpoint(ctx, item)
            strengths = tuple(
                [await self.put_semantic_strength(ctx, item) for item in bundle.strengths]
            )
            incremented_strengths = tuple(
                [
                    await self.increment_semantic_strength(ctx, item)
                    for item in bundle.strength_increments
                ]
            )
            node_by_id = {node.node_id: node for node in nodes}
            index_nodes = []
            index_intents = []
            for node_id in bundle.index_node_ids:
                node = node_by_id.get(node_id)
                if node is None:
                    node = await self.get_node(ctx, node_id)
                if not node.verify_hash():
                    raise CanonicalReloadError("index node hash reload failed")
                index_nodes.append(node)
                index_intents.append(await self._insert_index_outbox_intent(ctx, node))
            archived_nodes: tuple[GraphNode, ...] = ()
            delete_intents: tuple[IndexOutboxIntent, ...] = ()
            if bundle.capacity_limits is not None:
                if bundle.capacity_archived_at is None:
                    raise ValueError("capacity limits require an exact archived_at")
                archived_nodes, delete_intents = await self.enforce_capacity(
                    ctx,
                    limits=bundle.capacity_limits,
                    archived_at=bundle.capacity_archived_at,
                )
                archived_ids = {node.node_id for node in archived_nodes}
                surviving = [
                    (node, intent)
                    for node, intent in zip(index_nodes, index_intents)
                    if node.node_id not in archived_ids
                ]
                index_nodes = [item[0] for item in surviving]
                index_intents = [item[1] for item in surviving]
            receipt_values = {
                "namespace": self.namespace,
                "graph_hashes": tuple(
                    (item.graph_id, item.content_hash) for item in graphs
                ),
                "node_hashes": tuple((item.node_id, item.content_hash) for item in nodes),
                "index_nodes": tuple(index_nodes),
                "strength_hashes": tuple(
                    (item.strength_id, item.content_hash)
                    for item in (*strengths, *incremented_strengths)
                ),
                "index_intents": tuple(index_intents),
                "delete_nodes": tuple(archived_nodes),
                "delete_intents": tuple(delete_intents),
                "archived_nodes": tuple(archived_nodes),
                "promotion_evidence": promotion_evidence,
            }
            canonical_row_deltas: Mapping[str, Mapping[str, int]] = {}
            if operation_id is not None:
                after_counts = await self._canonical_row_counts(ctx)
                after_tokens = await self._canonical_mutable_tokens(ctx)
                canonical_row_deltas = self._build_canonical_row_deltas(
                    before_counts=before_counts,
                    after_counts=after_counts,
                    before_tokens=before_tokens,
                    after_tokens=after_tokens,
                    receipt_inserted=True,
                )
            receipt = AppendReceipt(
                **receipt_values,
                canonical_row_deltas=canonical_row_deltas,
            )
            if operation_id is not None:
                await self._save_lifecycle_operation_receipt(
                    ctx,
                    operation_id=operation_id,
                    bundle_digest=str(bundle_digest),
                    receipt=receipt,
                    operation_scope=dict(bundle.operation_scope or {}),
                )
        return receipt

    async def _load_lifecycle_operation_receipt(
        self,
        ctx: AccessContext,
        *,
        operation_id: str,
        bundle_digest: str,
    ) -> Optional[AppendReceipt]:
        """Lock and reload a prior exact append, if one exists."""

        async with self._tenant_tx(ctx) as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:operation_id,0))"),
                {"operation_id": operation_id},
            )
            result = await conn.execute(
                text(
                    "SELECT bundle_digest,receipt_payload "
                    "FROM trimem_lifecycle_operation_receipts "
                    "WHERE id=:id AND org_id=:org_id AND namespace=:namespace "
                    "AND owner_user_id=:owner_user_id"
                ),
                {
                    "id": operation_id,
                    "org_id": ctx.org_id,
                    "namespace": self.namespace,
                    "owner_user_id": ctx.user_id,
                },
            )
            row = result.mappings().first()
        if row is None:
            return None
        data = _mapping(row)
        if data.get("bundle_digest") != bundle_digest:
            raise IntegrityViolation("lifecycle operation identifier is already bound")
        payload = data.get("receipt_payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload = _mapping(payload)
        if (
            payload.get("operation_id") != operation_id
            or payload.get("bundle_digest") != bundle_digest
            or payload.get("namespace") != self.namespace
        ):
            raise CanonicalReloadError("lifecycle operation receipt identity mismatch")
        self._validate_operation_scope(payload.get("operation_scope"))
        canonical_row_deltas = self._validate_canonical_row_deltas(
            payload.get("canonical_row_deltas")
        )
        index_nodes = tuple(
            [await self.get_node(ctx, str(node_id)) for node_id in payload["index_node_ids"]]
        )
        index_intents = tuple(
            [
                await self.get_index_outbox_intent(ctx, str(intent_id))
                for intent_id in payload["index_intent_ids"]
            ]
        )
        delete_nodes = tuple(
            [await self.get_node(ctx, str(node_id)) for node_id in payload["delete_node_ids"]]
        )
        delete_intents = tuple(
            [
                await self.get_index_outbox_intent(ctx, str(intent_id))
                for intent_id in payload["delete_intent_ids"]
            ]
        )
        try:
            return AppendReceipt(
                namespace=self.namespace,
                graph_hashes=tuple(tuple(item) for item in payload["graph_hashes"]),
                node_hashes=tuple(tuple(item) for item in payload["node_hashes"]),
                index_nodes=index_nodes,
                strength_hashes=tuple(tuple(item) for item in payload["strength_hashes"]),
                index_intents=index_intents,
                delete_nodes=delete_nodes,
                delete_intents=delete_intents,
                archived_nodes=delete_nodes,
                promotion_evidence=tuple(
                    _promotion_evidence(item)
                    for item in payload.get("promotion_evidence", ())
                ),
                canonical_row_deltas=canonical_row_deltas,
                replayed=True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CanonicalReloadError("lifecycle operation receipt reload failed") from exc

    async def _save_lifecycle_operation_receipt(
        self,
        ctx: AccessContext,
        *,
        operation_id: str,
        bundle_digest: str,
        receipt: AppendReceipt,
        operation_scope: Mapping[str, Any],
    ) -> None:
        promotion = [
            {
                "id": item.evidence_id,
                "org_id": item.org_id,
                "namespace": item.namespace,
                "evidence_hash": item.evidence_hash,
                "contributor_hash": item.contributor_hash,
                "source_kind": item.source_kind,
                "source_outcome": item.source_outcome,
                "verified": item.verified,
                "public_evidence_hash": item.public_evidence_hash,
                "verifier_hash": item.verifier_hash,
                "extraction_hash": item.extraction_hash,
                "attestation_hash": item.attestation_hash,
                "verified_at": item.verified_at,
                "created_at": item.created_at,
            }
            for item in receipt.promotion_evidence
        ]
        payload = {
            "operation_id": operation_id,
            "bundle_digest": bundle_digest,
            "namespace": self.namespace,
            "operation_scope": dict(operation_scope),
            "canonical_row_deltas": self._validate_canonical_row_deltas(
                receipt.canonical_row_deltas
            ),
            "graph_hashes": list(receipt.graph_hashes),
            "node_hashes": list(receipt.node_hashes),
            "index_node_ids": [item.node_id for item in receipt.index_nodes],
            "strength_hashes": list(receipt.strength_hashes),
            "index_intent_ids": [item.intent_id for item in receipt.index_intents],
            "delete_node_ids": [item.node_id for item in receipt.delete_nodes],
            "delete_intent_ids": [item.intent_id for item in receipt.delete_intents],
            "promotion_evidence": promotion,
        }
        async with self._tenant_tx(ctx) as conn:
            await conn.execute(
                text(
                    "INSERT INTO trimem_lifecycle_operation_receipts("
                    "id,org_id,namespace,owner_user_id,bundle_digest,receipt_payload) "
                    "VALUES(:id,:org_id,:namespace,:owner_user_id,:bundle_digest,"
                    "CAST(:receipt_payload AS jsonb))"
                ),
                {
                    "id": operation_id,
                    "org_id": ctx.org_id,
                    "namespace": self.namespace,
                    "owner_user_id": ctx.user_id,
                    "bundle_digest": bundle_digest,
                    "receipt_payload": json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                },
            )

    async def lifecycle_receipt_evidence(
        self, ctx: AccessContext
    ) -> Mapping[str, Any]:
        """Return a sealed, owner-private receipt ledger for crash recovery."""

        async with self._tenant_tx(ctx) as conn:
            result = await conn.execute(
                text(
                    "SELECT id,bundle_digest,receipt_payload,created_at "
                    "FROM trimem_lifecycle_operation_receipts "
                    "WHERE org_id=:org_id AND namespace=:namespace "
                    "AND owner_user_id=:owner_user_id ORDER BY created_at,id"
                ),
                {
                    "org_id": ctx.org_id,
                    "namespace": self.namespace,
                    "owner_user_id": ctx.user_id,
                },
            )
            raw_rows = result.mappings().all()
        rows = []
        for raw in raw_rows:
            item = _mapping(raw)
            payload = item.get("receipt_payload")
            if isinstance(payload, str):
                payload = json.loads(payload)
            payload = _mapping(payload)
            operation_id = str(item.get("id", ""))
            bundle_digest = str(item.get("bundle_digest", ""))
            if (
                payload.get("operation_id") != operation_id
                or payload.get("bundle_digest") != bundle_digest
                or payload.get("namespace") != self.namespace
            ):
                raise CanonicalReloadError("lifecycle receipt evidence identity mismatch")
            rows.append({
                "operation_id": operation_id,
                "bundle_digest": bundle_digest,
                "receipt_payload_digest": canonical_hash(payload),
                "index_node_ids": list(payload.get("index_node_ids", ())),
                "index_intent_ids": list(payload.get("index_intent_ids", ())),
                "delete_node_ids": list(payload.get("delete_node_ids", ())),
                "delete_intent_ids": list(payload.get("delete_intent_ids", ())),
                "access_event_ids": list(payload.get("access_event_ids", ())),
                "canonical_row_deltas": self._validate_canonical_row_deltas(
                    payload.get("canonical_row_deltas")
                ),
                "operation_scope": dict(
                    self._validate_operation_scope(payload.get("operation_scope"))
                ),
                "created_at": str(item.get("created_at", "")),
            })
        body = {
            "schema": "trimem/lifecycle-receipt-evidence/1.0",
            "namespace": self.namespace,
            "owner_user_id": ctx.user_id,
            "rows": rows,
        }
        return {**body, "digest": canonical_hash(body)}

    @staticmethod
    def _validate_operation_scope(value: object) -> Mapping[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {
            "kind", "task_id", "active_node_ids"
        }:
            raise ValueError("operation_scope has an invalid shape")
        kind = value.get("kind")
        task_id = value.get("task_id")
        active = value.get("active_node_ids")
        if kind not in {"LIFECYCLE_STORE", "CREDIT", "FINALIZE", "ACCESS"}:
            raise ValueError("operation_scope kind is invalid")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("operation_scope task_id is required")
        if (
            not isinstance(active, (list, tuple))
            or any(not isinstance(item, str) or not item for item in active)
            or tuple(active) != tuple(sorted(set(active)))
        ):
            raise ValueError("operation_scope active_node_ids must be sorted and unique")
        return {
            "kind": str(kind),
            "task_id": task_id,
            "active_node_ids": list(active),
        }

    async def append_access_batch(
        self,
        ctx: AccessContext,
        events: Sequence[MemoryAccessEvent],
        *,
        operation_id: Optional[str] = None,
        operation_scope: Optional[Mapping[str, Any]] = None,
    ) -> tuple[MemoryAccessEvent, ...]:
        """Persist injection audit facts exactly once before exposing memory."""

        frozen = tuple(events)
        if len({item.event_id for item in frozen}) != len(frozen):
            raise IntegrityViolation("access batch contains duplicate event identifiers")
        operation_digest = None
        if operation_id is not None:
            operation_id = _uuid_identifier(operation_id, "operation_id")
            normalized_scope = dict(self._validate_operation_scope(operation_scope))
            if normalized_scope["kind"] != "ACCESS":
                raise ValueError("access receipt requires ACCESS operation_scope")
            operation_digest = canonical_hash({
                "operation_id": operation_id,
                "namespace": self.namespace,
                "operation_scope": normalized_scope,
                "access_events": [
                    (item.event_id, item.content_hash) for item in frozen
                ],
            })
        elif operation_scope is not None:
            raise ValueError("operation_scope requires operation_id")
        async with self._tenant_tx(ctx) as conn:
            before_counts: Mapping[str, int] = {}
            before_tokens: Mapping[str, Mapping[str, str]] = {}
            if operation_id is not None:
                await self._lock_canonical_operation(ctx)
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:operation_id,0))"),
                    {"operation_id": operation_id},
                )
                result = await conn.execute(
                    text(
                        "SELECT bundle_digest,receipt_payload "
                        "FROM trimem_lifecycle_operation_receipts "
                        "WHERE id=:id AND org_id=:org_id AND namespace=:namespace "
                        "AND owner_user_id=:owner_user_id"
                    ),
                    {
                        "id": operation_id,
                        "org_id": ctx.org_id,
                        "namespace": self.namespace,
                        "owner_user_id": ctx.user_id,
                    },
                )
                existing = result.mappings().first()
                if existing is not None:
                    data = _mapping(existing)
                    payload = data.get("receipt_payload")
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    payload = _mapping(payload)
                    expected_ids = [item.event_id for item in frozen]
                    if (
                        data.get("bundle_digest") != operation_digest
                        or payload.get("operation_id") != operation_id
                        or payload.get("bundle_digest") != operation_digest
                        or payload.get("namespace") != self.namespace
                        or payload.get("access_event_ids") != expected_ids
                        or payload.get("operation_scope") != normalized_scope
                    ):
                        raise IntegrityViolation(
                            "access operation identifier is already bound"
                        )
                    self._validate_canonical_row_deltas(
                        payload.get("canonical_row_deltas")
                    )
                    return tuple(
                        [await self.get_access_event(ctx, event_id) for event_id in expected_ids]
                    )
                before_counts = await self._canonical_row_counts(ctx)
                before_tokens = await self._canonical_mutable_tokens(ctx)
            stored = tuple([await self.append_access(ctx, event) for event in frozen])
            if operation_id is not None:
                after_counts = await self._canonical_row_counts(ctx)
                after_tokens = await self._canonical_mutable_tokens(ctx)
                canonical_row_deltas = self._build_canonical_row_deltas(
                    before_counts=before_counts,
                    after_counts=after_counts,
                    before_tokens=before_tokens,
                    after_tokens=after_tokens,
                    receipt_inserted=True,
                )
                payload = {
                    "operation_id": operation_id,
                    "bundle_digest": operation_digest,
                    "namespace": self.namespace,
                    "operation_scope": normalized_scope,
                    "canonical_row_deltas": canonical_row_deltas,
                    "access_event_ids": [item.event_id for item in stored],
                    "access_event_hashes": [item.content_hash for item in stored],
                    "index_node_ids": [],
                    "index_intent_ids": [],
                    "delete_node_ids": [],
                    "delete_intent_ids": [],
                }
                await conn.execute(
                    text(
                        "INSERT INTO trimem_lifecycle_operation_receipts("
                        "id,org_id,namespace,owner_user_id,bundle_digest,receipt_payload) "
                        "VALUES(:id,:org_id,:namespace,:owner_user_id,:bundle_digest,"
                        "CAST(:receipt_payload AS jsonb))"
                    ),
                    {
                        "id": operation_id,
                        "org_id": ctx.org_id,
                        "namespace": self.namespace,
                        "owner_user_id": ctx.user_id,
                        "bundle_digest": operation_digest,
                        "receipt_payload": json.dumps(
                            payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                            allow_nan=False,
                        ),
                    },
                )
            return stored

    async def _get(self, ctx: AccessContext, table: str, columns: str, record_id: str,
                   loader: Callable, label: str):
        async with self._tenant_tx(ctx) as conn:
            return await self._one(
                conn, table=table, columns=columns, record_id=record_id, ctx=ctx,
                loader=loader, label=label,
            )

    async def _append_record(
        self, ctx: AccessContext, *, table: str, columns: str, params: dict[str, Any],
        insert: str, loader: Callable, label: str, expected_hash: str,
    ):
        async with self._tenant_tx(ctx) as conn:
            await conn.execute(text(insert), params)
            try:
                loaded = await self._one(
                    conn, table=table, columns=columns, record_id=params["id"], ctx=ctx,
                    loader=loader, label=label,
                )
            except NotFound as exc:
                raise IntegrityViolation("%s identifier is unavailable" % label) from exc
        if loaded.content_hash != expected_hash:
            raise IntegrityViolation("%s identifier is already bound" % label)
        return loaded
