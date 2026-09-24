"""Canonical domain records for TriMem-Coder graph memory.

PostgreSQL is the authority for durable records.  This module deliberately has
no database, vector-store, model, or clock dependency: callers supply temporal
metadata and every record receives a deterministic content hash.  Qdrant-facing
objects are reference metadata only; canonical payloads are never part of a
vector payload.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields, replace
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, Iterable, Mapping, Optional


SCHEMA_VERSION = "enterprise_memory/trimem-graph/1.0.0"
VECTOR_INDEX_SCHEMA_VERSION = 2
DEFAULT_NAMESPACE = "unit-test"


class GraphKind(str, Enum):
    SHORT_TERM_WORKING = "SHORT_TERM_WORKING"
    USER_EPISODIC = "USER_EPISODIC"
    USER_SEMANTIC = "USER_SEMANTIC"
    ORGANISATION_SEMANTIC = "ORGANISATION_SEMANTIC"


PRIVATE_GRAPH_KINDS = frozenset({
    GraphKind.SHORT_TERM_WORKING,
    GraphKind.USER_EPISODIC,
    GraphKind.USER_SEMANTIC,
})
SEMANTIC_GRAPH_KINDS = frozenset({
    GraphKind.USER_SEMANTIC,
    GraphKind.ORGANISATION_SEMANTIC,
})


class GraphState(str, Enum):
    ACTIVE = "ACTIVE"
    SEALED = "SEALED"
    ARCHIVED = "ARCHIVED"


class LifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    TOMBSTONED = "TOMBSTONED"


class NodeType(str, Enum):
    TASK = "Task"
    SUBTASK = "Subtask"
    EPISODE = "Episode"
    SEMANTIC_RULE = "SemanticRule"
    REPOSITORY = "Repository"
    FILE = "File"
    SYMBOL = "Symbol"
    API = "API"
    ERROR = "Error"
    TEST = "Test"
    OPERATION = "Operation"
    OUTCOME = "Outcome"
    USER = "User"
    VERSION = "Version"


class EdgeType(str, Enum):
    DECOMPOSES_TO = "DECOMPOSES_TO"
    DEPENDS_ON = "DEPENDS_ON"
    TOUCHES = "TOUCHES"
    CALLS = "CALLS"
    OBSERVED = "OBSERVED"
    APPLIED = "APPLIED"
    VERIFIED_BY = "VERIFIED_BY"
    PRODUCED = "PRODUCED"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTRADICTED_BY = "CONTRADICTED_BY"
    DERIVED_FROM = "DERIVED_FROM"
    PROMOTED_TO = "PROMOTED_TO"
    SUPERSEDES = "SUPERSEDES"
    VALID_FOR = "VALID_FOR"


class ReviewAuthority(str, Enum):
    HUMAN_REVIEW = "HUMAN_REVIEW"
    TRUSTED_DOCUMENT = "TRUSTED_DOCUMENT"


class AccessType(str, Enum):
    SEARCHED = "SEARCHED"
    BROWSED = "BROWSED"
    INJECTED = "INJECTED"
    USED = "USED"
    VERIFIED = "VERIFIED"


class PolicyAction(str, Enum):
    FORGET = "FORGET"
    MOVE_TO_EPISODIC = "MOVE_TO_EPISODIC"
    MOVE_TO_SEMANTIC_CANDIDATE = "MOVE_TO_SEMANTIC_CANDIDATE"


class PolicyActor(str, Enum):
    DOUBLE_DQN = "DOUBLE_DQN"
    HEURISTIC = "HEURISTIC"
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "canonical_dict") and callable(value.canonical_dict):
        return value.canonical_dict()
    if hasattr(value, "__dataclass_fields__"):
        return {f.name: _primitive(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_primitive(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def canonical_json(value: Any) -> str:
    """Return the deterministic JSON representation used for content addressing.

    A record's own ``content_hash`` is excluded by its ``canonical_dict`` method;
    hashes embedded inside payload/provenance dictionaries remain intact.
    """
    return json.dumps(
        _primitive(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bytes_hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(bytes(value)).hexdigest()


def _required(value: Optional[str], name: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError("%s is required" % name)
    return str(value)


def _parse_timestamp(value: Optional[str], name: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ValueError("%s is required" % name)
        return None
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except (TypeError, ValueError):
        raise ValueError("%s must be an ISO-8601 timestamp" % name)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("%s must include a timezone" % name)
    return parsed


def _validate_partition(kind: GraphKind, owner_user_id: Optional[str]) -> None:
    if kind in PRIVATE_GRAPH_KINDS:
        _required(owner_user_id, "owner_user_id")
    elif owner_user_id is not None:
        raise ValueError("organisation semantic records cannot have owner_user_id")


class _HashedRecord:
    content_hash: str

    def canonical_dict(self) -> dict:
        return {f.name: _primitive(getattr(self, f.name)) for f in fields(self) if f.name != "content_hash"}

    def computed_hash(self) -> str:
        return canonical_hash(self.canonical_dict())

    def verify_hash(self) -> bool:
        return bool(self.content_hash) and self.content_hash == self.computed_hash()

    def _stamp_or_verify(self) -> None:
        expected = self.computed_hash()
        if self.content_hash and self.content_hash != expected:
            raise ValueError("content_hash mismatch")
        object.__setattr__(self, "content_hash", expected)


@dataclass(frozen=True)
class AccessContext:
    org_id: str
    user_id: str

    def __post_init__(self):
        _required(self.org_id, "org_id")
        _required(self.user_id, "user_id")


@dataclass(frozen=True)
class TemporalMetadata:
    ingested_at: str
    event_time: Optional[str] = None
    source_available_at: Optional[str] = None
    last_accessed_at: Optional[str] = None
    last_used_at: Optional[str] = None
    last_verified_at: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None

    def __post_init__(self):
        values = {
            name: _parse_timestamp(getattr(self, name), name, required=(name == "ingested_at"))
            for name in (
                "ingested_at", "event_time", "source_available_at", "last_accessed_at",
                "last_used_at", "last_verified_at", "valid_from", "valid_until",
            )
        }
        if values["valid_from"] and values["valid_until"] and values["valid_until"] < values["valid_from"]:
            raise ValueError("valid_until precedes valid_from")


@dataclass(frozen=True)
class ReviewProvenance(_HashedRecord):
    review_id: str
    reviewer_id: str
    reviewed_at: str
    authority: ReviewAuthority
    policy_version: str
    evidence_hash: str
    content_hash: str = ""

    def __post_init__(self):
        for name in ("review_id", "reviewer_id", "policy_version", "evidence_hash"):
            _required(getattr(self, name), name)
        _parse_timestamp(self.reviewed_at, "reviewed_at", required=True)
        if not isinstance(self.authority, ReviewAuthority):
            raise ValueError("invalid review authority")
        self._stamp_or_verify()


@dataclass(frozen=True)
class MemoryGraph(_HashedRecord):
    graph_id: str
    org_id: str
    temporal: TemporalMetadata
    namespace: str = DEFAULT_NAMESPACE
    owner_user_id: Optional[str] = None
    repository_id: Optional[str] = None
    solve_job_id: Optional[str] = None
    state: GraphState = GraphState.ACTIVE
    review_provenance: Optional[ReviewProvenance] = None
    schema_version: str = SCHEMA_VERSION
    content_hash: str = ""

    KIND: ClassVar[GraphKind]

    @property
    def kind(self) -> GraphKind:
        return self.KIND

    def canonical_dict(self) -> dict:
        result = super().canonical_dict()
        result["kind"] = self.kind.value
        return result

    def __post_init__(self):
        _required(self.graph_id, "graph_id")
        _required(self.org_id, "org_id")
        _required(self.namespace, "namespace")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version")
        if not isinstance(self.temporal, TemporalMetadata):
            raise ValueError("temporal must be TemporalMetadata")
        if not isinstance(self.state, GraphState):
            raise ValueError("invalid graph state")
        _validate_partition(self.kind, self.owner_user_id)
        if self.kind == GraphKind.SHORT_TERM_WORKING:
            _required(self.solve_job_id, "solve_job_id")
        elif self.solve_job_id is not None and self.kind == GraphKind.ORGANISATION_SEMANTIC:
            raise ValueError("organisation semantic graph cannot be job-owned")
        if self.kind == GraphKind.ORGANISATION_SEMANTIC and self.review_provenance is None:
            raise ValueError("organisation semantic graph requires review provenance")
        self._stamp_or_verify()


@dataclass(frozen=True)
class ShortTermWorkingGraph(MemoryGraph):
    KIND: ClassVar[GraphKind] = GraphKind.SHORT_TERM_WORKING


@dataclass(frozen=True)
class UserEpisodicGraph(MemoryGraph):
    KIND: ClassVar[GraphKind] = GraphKind.USER_EPISODIC


@dataclass(frozen=True)
class UserSemanticGraph(MemoryGraph):
    KIND: ClassVar[GraphKind] = GraphKind.USER_SEMANTIC


@dataclass(frozen=True)
class OrganisationSemanticGraph(MemoryGraph):
    KIND: ClassVar[GraphKind] = GraphKind.ORGANISATION_SEMANTIC


@dataclass(frozen=True)
class GraphNode(_HashedRecord):
    node_id: str
    graph_id: str
    org_id: str
    graph_kind: GraphKind
    node_type: NodeType
    temporal: TemporalMetadata
    canonical_payload: Mapping[str, Any]
    namespace: str = DEFAULT_NAMESPACE
    owner_user_id: Optional[str] = None
    repository_id: Optional[str] = None
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    payload_hash: str = ""
    archived_at: Optional[str] = None
    archive_reason: Optional[str] = None
    archived_from_content_hash: Optional[str] = None
    review_provenance: Optional[ReviewProvenance] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in ("node_id", "graph_id", "org_id", "namespace"):
            _required(getattr(self, name), name)
        if (
            not isinstance(self.graph_kind, GraphKind)
            or not isinstance(self.node_type, NodeType)
            or not isinstance(self.lifecycle_state, LifecycleState)
        ):
            raise ValueError("invalid graph_kind/node_type/lifecycle_state")
        if not isinstance(self.canonical_payload, Mapping):
            raise ValueError("canonical_payload must be a mapping")
        _validate_partition(self.graph_kind, self.owner_user_id)
        if self.graph_kind == GraphKind.USER_EPISODIC and self.node_type == NodeType.SEMANTIC_RULE:
            raise ValueError("episodic graph cannot contain SemanticRule nodes")
        if self.graph_kind in SEMANTIC_GRAPH_KINDS and self.node_type == NodeType.EPISODE:
            raise ValueError("semantic graph cannot contain Episode nodes")
        if self.graph_kind == GraphKind.ORGANISATION_SEMANTIC and self.review_provenance is None:
            raise ValueError("organisation semantic node requires review provenance")
        expected_payload = canonical_hash(dict(self.canonical_payload))
        if self.lifecycle_state == LifecycleState.ACTIVE:
            if (
                self.archived_at is not None
                or self.archive_reason is not None
                or self.archived_from_content_hash is not None
            ):
                raise ValueError("active node cannot carry archive provenance")
            if self.payload_hash and self.payload_hash != expected_payload:
                raise ValueError("payload_hash mismatch")
            object.__setattr__(self, "payload_hash", expected_payload)
        else:
            _required(self.payload_hash, "payload_hash")
            _required(self.archived_at, "archived_at")
            _required(self.archive_reason, "archive_reason")
            _required(self.archived_from_content_hash, "archived_from_content_hash")
            if (
                len(self.archived_from_content_hash) != 71
                or not self.archived_from_content_hash.startswith("sha256:")
                or any(
                    character not in "0123456789abcdef"
                    for character in self.archived_from_content_hash[7:]
                )
            ):
                raise ValueError("archived_from_content_hash is not a canonical sha256 digest")
            _parse_timestamp(self.archived_at, "archived_at", required=True)
        self._stamp_or_verify()

    def archived(self, at: str, reason: str) -> "GraphNode":
        _parse_timestamp(at, "archived_at", required=True)
        _required(reason, "archive_reason")
        return replace(
            self,
            lifecycle_state=LifecycleState.ARCHIVED,
            canonical_payload={},
            archived_at=at,
            archive_reason=reason,
            archived_from_content_hash=self.content_hash,
            content_hash="",
        )


@dataclass(frozen=True)
class GraphEdge(_HashedRecord):
    edge_id: str
    graph_id: str
    org_id: str
    graph_kind: GraphKind
    edge_type: EdgeType
    source_node_id: str
    target_node_id: str
    temporal: TemporalMetadata
    namespace: str = DEFAULT_NAMESPACE
    owner_user_id: Optional[str] = None
    metadata: Mapping[str, Any] = None
    lifecycle_state: LifecycleState = LifecycleState.ACTIVE
    review_provenance: Optional[ReviewProvenance] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in (
            "edge_id", "graph_id", "org_id", "namespace", "source_node_id", "target_node_id"
        ):
            _required(getattr(self, name), name)
        if self.source_node_id == self.target_node_id:
            raise ValueError("self edges are not allowed")
        if (
            not isinstance(self.graph_kind, GraphKind)
            or not isinstance(self.edge_type, EdgeType)
            or not isinstance(self.lifecycle_state, LifecycleState)
        ):
            raise ValueError("invalid graph_kind/edge_type/lifecycle_state")
        _validate_partition(self.graph_kind, self.owner_user_id)
        if self.metadata is None:
            object.__setattr__(self, "metadata", {})
        elif not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        if self.graph_kind == GraphKind.ORGANISATION_SEMANTIC and self.review_provenance is None:
            raise ValueError("organisation semantic edge requires review provenance")
        self._stamp_or_verify()


@dataclass(frozen=True)
class SemanticSupport(_HashedRecord):
    support_id: str
    semantic_graph_id: str
    semantic_node_id: str
    org_id: str
    graph_kind: GraphKind
    source_evidence_hash: str
    temporal: TemporalMetadata
    namespace: str = DEFAULT_NAMESPACE
    owner_user_id: Optional[str] = None
    source_episode_id: Optional[str] = None
    contributor_hash: Optional[str] = None
    review_provenance: Optional[ReviewProvenance] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in (
            "support_id", "semantic_graph_id", "semantic_node_id", "org_id", "namespace",
            "source_evidence_hash",
        ):
            _required(getattr(self, name), name)
        if not isinstance(self.graph_kind, GraphKind):
            raise ValueError("invalid graph_kind")
        if self.graph_kind not in SEMANTIC_GRAPH_KINDS:
            raise ValueError("support target must be semantic")
        _validate_partition(self.graph_kind, self.owner_user_id)
        if self.graph_kind == GraphKind.ORGANISATION_SEMANTIC:
            if self.review_provenance is None:
                raise ValueError("organisation semantic support requires review provenance")
            if self.source_episode_id is not None:
                raise ValueError("organisation support stores an evidence hash, not a private episode id")
        self._stamp_or_verify()


@dataclass(frozen=True)
class MemoryAccessEvent(_HashedRecord):
    event_id: str
    graph_id: str
    node_id: str
    org_id: str
    graph_kind: GraphKind
    actor_user_id: str
    access_type: AccessType
    event_time: str
    namespace: str = DEFAULT_NAMESPACE
    owner_user_id: Optional[str] = None
    injected_byte_count: int = 0
    injected_hash: Optional[str] = None
    evidence_ref: Optional[str] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in ("event_id", "graph_id", "node_id", "org_id", "namespace", "actor_user_id"):
            _required(getattr(self, name), name)
        _parse_timestamp(self.event_time, "event_time", required=True)
        if not isinstance(self.graph_kind, GraphKind) or not isinstance(self.access_type, AccessType):
            raise ValueError("invalid graph_kind/access_type")
        _validate_partition(self.graph_kind, self.owner_user_id)
        if self.injected_byte_count < 0:
            raise ValueError("injected_byte_count must be non-negative")
        if self.access_type == AccessType.INJECTED:
            _required(self.injected_hash, "injected_hash")
        elif self.injected_byte_count or self.injected_hash:
            raise ValueError("injection accounting is valid only for INJECTED events")
        self._stamp_or_verify()

    @classmethod
    def injection(
        cls,
        *,
        event_id: str,
        graph_id: str,
        node_id: str,
        org_id: str,
        graph_kind: GraphKind,
        actor_user_id: str,
        event_time: str,
        injected_bytes: bytes,
        namespace: str = DEFAULT_NAMESPACE,
        owner_user_id: Optional[str] = None,
        evidence_ref: Optional[str] = None,
    ) -> "MemoryAccessEvent":
        blob = bytes(injected_bytes)
        return cls(
            event_id=event_id,
            graph_id=graph_id,
            node_id=node_id,
            org_id=org_id,
            graph_kind=graph_kind,
            actor_user_id=actor_user_id,
            access_type=AccessType.INJECTED,
            event_time=event_time,
            namespace=namespace,
            owner_user_id=owner_user_id,
            injected_byte_count=len(blob),
            injected_hash=bytes_hash(blob),
            evidence_ref=evidence_ref,
        )


@dataclass(frozen=True)
class GraphCheckpoint(_HashedRecord):
    checkpoint_id: str
    graph_id: str
    org_id: str
    owner_user_id: str
    sequence: int
    graph_content_hash: str
    created_at: str
    namespace: str = DEFAULT_NAMESPACE
    active_node_id: Optional[str] = None
    evidence_ref: Optional[str] = None
    evidence_hash: Optional[str] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in (
            "checkpoint_id", "graph_id", "org_id", "namespace", "owner_user_id",
            "graph_content_hash",
        ):
            _required(getattr(self, name), name)
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        _parse_timestamp(self.created_at, "created_at", required=True)
        if (self.evidence_ref is None) != (self.evidence_hash is None):
            raise ValueError("evidence_ref and evidence_hash must be supplied together")
        if self.evidence_ref is not None:
            _required(self.evidence_ref, "evidence_ref")
            _required(self.evidence_hash, "evidence_hash")
        self._stamp_or_verify()


@dataclass(frozen=True)
class PolicyTransition(_HashedRecord):
    transition_id: str
    graph_id: str
    candidate_node_id: str
    org_id: str
    owner_user_id: str
    action: PolicyAction
    actor: PolicyActor
    event_time: str
    namespace: str = DEFAULT_NAMESPACE
    target_graph_kind: Optional[GraphKind] = None
    state_features_hash: Optional[str] = None
    reward: Optional[float] = None
    delayed_credit_ref: Optional[str] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in (
            "transition_id", "graph_id", "candidate_node_id", "org_id", "namespace",
            "owner_user_id",
        ):
            _required(getattr(self, name), name)
        _parse_timestamp(self.event_time, "event_time", required=True)
        if not isinstance(self.action, PolicyAction) or not isinstance(self.actor, PolicyActor):
            raise ValueError("invalid policy action/actor")
        if self.target_graph_kind is not None and not isinstance(self.target_graph_kind, GraphKind):
            raise ValueError("invalid target_graph_kind")
        if self.target_graph_kind == GraphKind.ORGANISATION_SEMANTIC:
            raise ValueError("memory policy cannot publish to organisation semantic memory")
        if self.reward is not None and not math.isfinite(float(self.reward)):
            raise ValueError("reward must be finite")
        if self.action == PolicyAction.MOVE_TO_EPISODIC and self.target_graph_kind != GraphKind.USER_EPISODIC:
            raise ValueError("MOVE_TO_EPISODIC must target USER_EPISODIC")
        if (self.action == PolicyAction.MOVE_TO_SEMANTIC_CANDIDATE
                and self.target_graph_kind != GraphKind.USER_SEMANTIC):
            raise ValueError("semantic candidates must first enter USER_SEMANTIC")
        if self.action == PolicyAction.FORGET and self.target_graph_kind is not None:
            raise ValueError("FORGET has no target graph")
        self._stamp_or_verify()


@dataclass(frozen=True)
class SemanticStrength:
    support: float = 0.0
    successful_reuse: float = 0.0
    independent_user_evidence: float = 0.0
    recent_verification: float = 0.0
    negative_transfer: float = 0.0
    contradiction: float = 0.0
    version_staleness: float = 0.0

    def __post_init__(self):
        for f in fields(self):
            value = float(getattr(self, f.name))
            if not math.isfinite(value) or value < 0:
                raise ValueError("semantic strength components must be finite and non-negative")
            object.__setattr__(self, f.name, value)

    @property
    def score(self) -> float:
        return (
            self.support
            + self.successful_reuse
            + self.independent_user_evidence
            + self.recent_verification
            - self.negative_transfer
            - self.contradiction
            - self.version_staleness
        )


@dataclass(frozen=True)
class SemanticStrengthRecord(_HashedRecord):
    """Canonical, mutable-by-replacement strength state for one semantic rule."""

    strength_id: str
    graph_id: str
    semantic_node_id: str
    org_id: str
    graph_kind: GraphKind
    strength: SemanticStrength
    updated_at: str
    namespace: str = DEFAULT_NAMESPACE
    owner_user_id: Optional[str] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in (
            "strength_id",
            "graph_id",
            "semantic_node_id",
            "org_id",
            "namespace",
        ):
            _required(getattr(self, name), name)
        if self.graph_kind not in SEMANTIC_GRAPH_KINDS:
            raise ValueError("semantic strength target must be a semantic graph")
        if not isinstance(self.strength, SemanticStrength):
            raise ValueError("strength must be SemanticStrength")
        _validate_partition(self.graph_kind, self.owner_user_id)
        _parse_timestamp(self.updated_at, "updated_at", required=True)
        self._stamp_or_verify()


@dataclass(frozen=True)
class VectorIndexMetadata(_HashedRecord):
    graph_id: str
    node_id: str
    org_id: str
    memory_kind: GraphKind
    canonical_content_hash: str
    namespace: str = DEFAULT_NAMESPACE
    owner_user_id: Optional[str] = None
    repository_id: Optional[str] = None
    collection_scope: str = "private"
    index_schema_version: int = VECTOR_INDEX_SCHEMA_VERSION
    embedding_model_id: Optional[str] = None
    embedding_revision: Optional[str] = None
    embedding_dimension: Optional[int] = None
    content_hash: str = ""

    def __post_init__(self):
        for name in ("graph_id", "node_id", "org_id", "namespace", "canonical_content_hash"):
            _required(getattr(self, name), name)
        if not isinstance(self.memory_kind, GraphKind):
            raise ValueError("invalid memory_kind")
        if self.memory_kind == GraphKind.SHORT_TERM_WORKING:
            raise ValueError("working graph is not a durable vector-index kind")
        _validate_partition(self.memory_kind, self.owner_user_id)
        expected_scope = "shared" if self.memory_kind == GraphKind.ORGANISATION_SEMANTIC else "private"
        if self.collection_scope != expected_scope:
            raise ValueError("collection_scope does not match memory_kind")
        if self.index_schema_version != VECTOR_INDEX_SCHEMA_VERSION:
            raise ValueError("unsupported vector index schema")
        if self.embedding_dimension is not None and self.embedding_dimension <= 0:
            raise ValueError("embedding_dimension must be positive")
        self._stamp_or_verify()

    def payload(self) -> dict:
        """Reference-only metadata suitable for Qdrant; contains no canonical text."""
        return {
            "index_schema_version": self.index_schema_version,
            "collection_scope": self.collection_scope,
            "memory_kind": self.memory_kind.value,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "org_id": self.org_id,
            "namespace": self.namespace,
            "owner_user_id": self.owner_user_id,
            "repository_id": self.repository_id,
            "canonical_content_hash": self.canonical_content_hash,
            "embedding_model_id": self.embedding_model_id,
            "embedding_revision": self.embedding_revision,
            "embedding_dimension": self.embedding_dimension,
        }


def require_unique_ids(records: Iterable[Any], attribute: str) -> None:
    seen = set()
    for record in records:
        value = getattr(record, attribute)
        if value in seen:
            raise ValueError("duplicate %s: %s" % (attribute, value))
        seen.add(value)
