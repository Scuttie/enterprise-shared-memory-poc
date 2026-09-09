"""Strict, reference-only Qdrant adapter for the TriMem vector-index v2 protocol.

The adapter deliberately does not import :mod:`qdrant_client`.  Production code
may supply a Qdrant client (or a thin transport around one), while unit tests can
provide a small fake implementing :class:`QdrantClientProtocol`.

Qdrant is a replaceable retrieval index, never the canonical memory store.  A
point payload therefore contains only canonical references and the metadata
needed to enforce a scoped lookup.  In particular, canonical/retrieval text and
arbitrary metadata are rejected rather than persisted or returned.
"""
from __future__ import annotations

import math
import re
import uuid
from hashlib import sha256
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from .schema import DEFAULT_NAMESPACE, GraphKind, VECTOR_INDEX_SCHEMA_VERSION, VectorIndexMetadata


INDEX_SCHEMA_VERSION = VECTOR_INDEX_SCHEMA_VERSION
PRIVATE_SCOPE = "private"
SHARED_SCOPE = "shared"

# The schema version is part of each physical collection name.  A v1 reader can
# never accidentally query a v2 collection merely because an alias was reused.
PRIVATE_COLLECTION = "trimem_private_v2"
SHARED_COLLECTION = "trimem_shared_v2"

_POINT_NAMESPACE = uuid.UUID("f771bd7f-26f7-4d31-8da8-c732575f92ac")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_INDEXABLE_KINDS = frozenset(
    {
        GraphKind.USER_EPISODIC,
        GraphKind.USER_SEMANTIC,
        GraphKind.ORGANISATION_SEMANTIC,
    }
)
_PRIVATE_KINDS = frozenset({GraphKind.USER_EPISODIC, GraphKind.USER_SEMANTIC})
_KIND_ALIASES = {
    "EPISODIC": GraphKind.USER_EPISODIC,
    "ORG_SEMANTIC": GraphKind.ORGANISATION_SEMANTIC,
}

# This exact allow-list is also the privacy boundary.  Adding a field requires
# a protocol version bump and a new physical collection.
PAYLOAD_FIELDS = frozenset(
    {
        "index_schema_version",
        "collection_scope",
        "memory_kind",
        "org_id",
        "owner_user_id",
        "repository_id",
        "graph_id",
        "node_id",
        "content_hash",
    }
)

# All four tenant/retrieval dimensions are payload-indexed and are mandatory in
# every query.  The version and physical-scope filters prevent mixed-protocol
# points from being considered even if a collection is manually corrupted.
PAYLOAD_INDEXES = (
    ("index_schema_version", "integer"),
    ("collection_scope", "keyword"),
    ("memory_kind", "keyword"),
    ("org_id", "keyword"),
    ("owner_user_id", "keyword"),
    ("repository_id", "keyword"),
)


class VectorIndexError(RuntimeError):
    """Base class for TriMem vector-index protocol failures."""


class VectorSchemaMismatch(VectorIndexError):
    """The configured collection/vector schema does not match v2."""


class InvalidVectorPayload(VectorIndexError, ValueError):
    """A point payload is not the exact reference-only v2 shape."""


class InvalidVectorQuery(VectorIndexError, ValueError):
    """A query is missing or violates a mandatory scope dimension."""


def _required_identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidVectorPayload("%s must be a non-empty string" % name)
    return value


def _optional_identifier(value: object, name: str) -> Optional[str]:
    if value is None:
        return None
    return _required_identifier(value, name)


def _required_content_hash(value: object) -> str:
    digest = _required_identifier(value, "content_hash")
    if _SHA256_RE.fullmatch(digest) is None:
        raise InvalidVectorPayload("content_hash must be a canonical sha256 digest")
    return digest


def _normalize_kind(value: GraphKind | str | Enum) -> GraphKind:
    raw = value.value if isinstance(value, Enum) else value
    if not isinstance(raw, str) or not raw.strip():
        raise InvalidVectorQuery("memory_kind is required")
    canonical = raw.strip().upper()
    kind = _KIND_ALIASES.get(canonical)
    if kind is None:
        try:
            kind = GraphKind(canonical)
        except ValueError as exc:
            raise InvalidVectorQuery("unsupported memory_kind %r" % raw) from exc
    if kind not in _INDEXABLE_KINDS:
        raise InvalidVectorQuery("memory_kind %s is not durable/indexable" % kind.value)
    return kind


def collection_scope_for(memory_kind: GraphKind | str | Enum) -> str:
    kind = _normalize_kind(memory_kind)
    return PRIVATE_SCOPE if kind in _PRIVATE_KINDS else SHARED_SCOPE


def collection_for(memory_kind: GraphKind | str | Enum) -> str:
    return PRIVATE_COLLECTION if collection_scope_for(memory_kind) == PRIVATE_SCOPE else SHARED_COLLECTION


def point_id_for(graph_id: str, node_id: str) -> str:
    """Return the stable Qdrant point id for one canonical graph node."""
    graph = _required_identifier(graph_id, "graph_id")
    node = _required_identifier(node_id, "node_id")
    return str(uuid.uuid5(_POINT_NAMESPACE, "%s:%s" % (graph, node)))


@dataclass(frozen=True)
class VectorReference:
    """The complete and only payload permitted in the v2 vector index."""

    graph_id: str
    node_id: str
    content_hash: str
    org_id: str
    memory_kind: GraphKind | str
    owner_user_id: Optional[str]
    repository_id: Optional[str]
    namespace: str = DEFAULT_NAMESPACE
    index_schema_version: int = INDEX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_id", _required_identifier(self.graph_id, "graph_id"))
        object.__setattr__(self, "node_id", _required_identifier(self.node_id, "node_id"))
        object.__setattr__(self, "content_hash", _required_content_hash(self.content_hash))
        object.__setattr__(self, "org_id", _required_identifier(self.org_id, "org_id"))
        object.__setattr__(self, "namespace", _required_identifier(self.namespace, "namespace"))
        try:
            kind = _normalize_kind(self.memory_kind)
        except InvalidVectorQuery as exc:
            raise InvalidVectorPayload(str(exc)) from exc
        object.__setattr__(self, "memory_kind", kind)
        object.__setattr__(
            self, "owner_user_id", _optional_identifier(self.owner_user_id, "owner_user_id")
        )
        object.__setattr__(
            self, "repository_id", _optional_identifier(self.repository_id, "repository_id")
        )
        if type(self.index_schema_version) is not int or self.index_schema_version != INDEX_SCHEMA_VERSION:
            raise InvalidVectorPayload("unsupported index_schema_version")
        if kind in _PRIVATE_KINDS and self.owner_user_id is None:
            raise InvalidVectorPayload("private memory requires owner_user_id")
        if kind == GraphKind.ORGANISATION_SEMANTIC and self.owner_user_id is not None:
            raise InvalidVectorPayload("organisation semantic memory cannot have owner_user_id")

    @property
    def collection_scope(self) -> str:
        return collection_scope_for(self.memory_kind)

    @property
    def point_id(self) -> str:
        return point_id_for(self.graph_id, self.node_id)

    def payload(self) -> dict[str, object]:
        """Return a new strict payload mapping; no canonical content is present."""
        return {
            "index_schema_version": self.index_schema_version,
            "collection_scope": self.collection_scope,
            "memory_kind": self.memory_kind.value,
            "org_id": self.org_id,
            "owner_user_id": self.owner_user_id,
            "repository_id": self.repository_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_metadata(cls, metadata: VectorIndexMetadata) -> "VectorReference":
        if not isinstance(metadata, VectorIndexMetadata):
            raise TypeError("metadata must be VectorIndexMetadata")
        return cls(
            graph_id=metadata.graph_id,
            node_id=metadata.node_id,
            content_hash=metadata.canonical_content_hash,
            org_id=metadata.org_id,
            memory_kind=metadata.memory_kind,
            owner_user_id=metadata.owner_user_id,
            repository_id=metadata.repository_id,
            namespace=metadata.namespace,
            index_schema_version=metadata.index_schema_version,
        )

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, object], *, namespace: str = DEFAULT_NAMESPACE
    ) -> "VectorReference":
        if not isinstance(payload, Mapping):
            raise InvalidVectorPayload("payload must be a mapping")
        keys = frozenset(payload)
        if keys != PAYLOAD_FIELDS:
            missing = sorted(PAYLOAD_FIELDS - keys)
            extra = sorted(keys - PAYLOAD_FIELDS)
            raise InvalidVectorPayload("payload fields differ (missing=%r, extra=%r)" % (missing, extra))

        # Aliases are useful at the Python API boundary, but not inside a v2
        # payload: there is exactly one on-disk spelling for each kind.
        raw_kind = payload["memory_kind"]
        canonical_kinds = {kind.value for kind in _INDEXABLE_KINDS}
        if not isinstance(raw_kind, str) or raw_kind not in canonical_kinds:
            raise InvalidVectorPayload("payload memory_kind is not canonical")
        reference = cls(
            graph_id=payload["graph_id"],
            node_id=payload["node_id"],
            content_hash=payload["content_hash"],
            org_id=payload["org_id"],
            memory_kind=raw_kind,
            owner_user_id=payload["owner_user_id"],
            repository_id=payload["repository_id"],
            namespace=namespace,
            index_schema_version=payload["index_schema_version"],
        )
        if payload["collection_scope"] != reference.collection_scope:
            raise InvalidVectorPayload("collection_scope does not match memory_kind")
        return reference


class RejectionReason(str, Enum):
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    FILTER_MISMATCH = "FILTER_MISMATCH"
    INVALID_SCORE = "INVALID_SCORE"


@dataclass(frozen=True)
class RejectedVectorPoint:
    point_id: str
    reason: RejectionReason
    detail: str


@dataclass(frozen=True)
class VectorHit:
    point_id: str
    score: float
    reference: VectorReference

    @property
    def payload(self) -> dict[str, object]:
        return self.reference.payload()


@dataclass(frozen=True)
class VectorSearchResult(Sequence[VectorHit]):
    """Accepted hits plus fail-closed rejections from an untrusted index."""

    hits: tuple[VectorHit, ...] = ()
    rejections: tuple[RejectedVectorPoint, ...] = ()

    def __len__(self) -> int:
        return len(self.hits)

    def __iter__(self) -> Iterator[VectorHit]:
        return iter(self.hits)

    def __getitem__(self, index):
        return self.hits[index]


@runtime_checkable
class QdrantClientProtocol(Protocol):
    """Dependency-free subset of the synchronous Qdrant client surface."""

    def collection_exists(self, collection_name: str) -> bool: ...

    def create_collection(self, collection_name: str, *, vectors_config: Mapping[str, object]) -> Any: ...

    def get_collection(self, collection_name: str) -> Any: ...

    def create_payload_index(
        self,
        collection_name: str,
        *,
        field_name: str,
        field_schema: str,
        wait: bool,
    ) -> Any: ...

    def upsert(
        self,
        collection_name: str,
        *,
        points: Sequence[Mapping[str, object]],
        wait: bool,
    ) -> Any: ...

    def delete(
        self,
        collection_name: str,
        *,
        points_selector: Mapping[str, Sequence[str]],
        wait: bool,
    ) -> Any: ...

    def query_points(
        self,
        collection_name: str,
        *,
        query: Sequence[float],
        query_filter: Mapping[str, object],
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ) -> Any: ...


class Qdrant112ClientAdapter:
    """Translate the dependency-free wire shape to qdrant-client 1.12 models.

    ``QdrantVectorIndexV2`` deliberately speaks only primitive Python values so
    importing the base TriMem package does not require the optional Qdrant
    dependency.  The real 1.12 client, however, requires model objects on paths
    that are shared by its local, REST, and gRPC transports.  In particular,
    raw mappings are not a portable substitute for ``VectorParams``,
    ``PointStruct``, ``Filter``, or ``PointIdsList``.

    Production construction leaves ``model_api`` unset and imports
    :mod:`qdrant_client.models` lazily.  Tests can inject a small model namespace
    and therefore exercise every conversion without installing qdrant-client.
    Attributes outside this narrow conversion surface are delegated to the raw
    client (including collection inspection APIs).
    """

    _MODEL_NAMES = (
        "Distance",
        "Filter",
        "PayloadSchemaType",
        "PointIdsList",
        "PointStruct",
        "VectorParams",
    )

    def __init__(self, raw_client: object, model_api: Optional[object] = None) -> None:
        if raw_client is None:
            raise TypeError("raw_client is required")
        if model_api is None:
            try:
                from qdrant_client import models as model_api
            except (ImportError, ModuleNotFoundError) as exc:
                raise VectorIndexError(
                    "qdrant-client 1.12 models are required for the production adapter"
                ) from exc
        missing = [name for name in self._MODEL_NAMES if not hasattr(model_api, name)]
        if missing:
            raise VectorIndexError(
                "Qdrant model API is incomplete (missing=%r)" % sorted(missing)
            )
        self._raw_client = raw_client
        self._models = model_api

    @property
    def raw_client(self) -> object:
        return self._raw_client

    def __getattr__(self, name: str) -> object:
        # Keep count/get_collection/collection_exists and future inspection
        # calls transparent without broadening the conversion protocol.
        return getattr(self._raw_client, name)

    def close(self, *args: object, **kwargs: object) -> Any:
        return self._raw_client.close(*args, **kwargs)

    def count(self, *args: object, **kwargs: object) -> Any:
        return self._raw_client.count(*args, **kwargs)

    def create_collection(
        self, collection_name: str, *, vectors_config: Mapping[str, object]
    ) -> Any:
        if not isinstance(vectors_config, Mapping):
            raise TypeError("vectors_config must be a mapping")
        try:
            size = vectors_config["size"]
            raw_distance = vectors_config["distance"]
        except KeyError as exc:
            raise VectorSchemaMismatch("unnamed vector configuration is incomplete") from exc
        distance = self._models.Distance(raw_distance)
        params = self._models.VectorParams(size=size, distance=distance)
        return self._raw_client.create_collection(
            collection_name=collection_name,
            vectors_config=params,
        )

    def create_payload_index(
        self,
        collection_name: str,
        *,
        field_name: str,
        field_schema: str,
        wait: bool,
    ) -> Any:
        schema = self._models.PayloadSchemaType(field_schema)
        return self._raw_client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=schema,
            wait=wait,
        )

    def upsert(
        self,
        collection_name: str,
        *,
        points: Sequence[Mapping[str, object]],
        wait: bool,
    ) -> Any:
        converted = [self._models.PointStruct(**dict(point)) for point in points]
        return self._raw_client.upsert(
            collection_name=collection_name,
            points=converted,
            wait=wait,
        )

    def delete(
        self,
        collection_name: str,
        *,
        points_selector: Mapping[str, Sequence[str]],
        wait: bool,
    ) -> Any:
        if not isinstance(points_selector, Mapping) or set(points_selector) != {"points"}:
            raise TypeError("points_selector must contain only a points sequence")
        selector = self._models.PointIdsList(points=list(points_selector["points"]))
        return self._raw_client.delete(
            collection_name=collection_name,
            points_selector=selector,
            wait=wait,
        )

    def query_points(
        self,
        collection_name: str,
        *,
        query: Sequence[float],
        query_filter: Mapping[str, object],
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ) -> Any:
        if not isinstance(query_filter, Mapping):
            raise TypeError("query_filter must be a mapping")
        qdrant_filter = self._models.Filter(**dict(query_filter))
        return self._raw_client.query_points(
            collection_name=collection_name,
            query=list(query),
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=with_payload,
            with_vectors=with_vectors,
        )


@runtime_checkable
class VectorIndexProtocol(Protocol):
    def ensure_ready(self) -> None: ...

    def upsert(
        self,
        reference: VectorReference | VectorIndexMetadata | Mapping[str, object],
        vector: Sequence[float],
        *,
        point_id: Optional[str] = None,
    ) -> str: ...

    def delete(
        self,
        reference: VectorReference | VectorIndexMetadata | Mapping[str, object],
        *,
        point_id: Optional[str] = None,
    ) -> str: ...

    def search(
        self,
        vector: Sequence[float],
        *,
        org_id: str,
        owner_user_id: Optional[str],
        memory_kind: GraphKind | str | Enum,
        repository_id: Optional[str],
        limit: int = 10,
    ) -> VectorSearchResult: ...


class QdrantVectorIndexV2:
    """Qdrant v2 adapter with physical scope separation and strict payloads."""

    def __init__(
        self,
        client: QdrantClientProtocol,
        dimension: int,
        *,
        index_schema_version: int = INDEX_SCHEMA_VERSION,
        namespace: str = DEFAULT_NAMESPACE,
        private_collection: Optional[str] = None,
        shared_collection: Optional[str] = None,
    ) -> None:
        if type(dimension) is not int or dimension <= 0:
            raise VectorSchemaMismatch("dimension must be a positive integer")
        if type(index_schema_version) is not int or index_schema_version != INDEX_SCHEMA_VERSION:
            raise VectorSchemaMismatch("only vector index schema v2 is supported")
        self.namespace = _required_collection_name(namespace, "namespace")
        namespace_suffix = ""
        if self.namespace != DEFAULT_NAMESPACE:
            namespace_suffix = "_" + sha256(self.namespace.encode("utf-8")).hexdigest()[:16]
        private_name = _required_collection_name(
            private_collection or PRIVATE_COLLECTION + namespace_suffix, "private_collection"
        )
        shared_name = _required_collection_name(
            shared_collection or SHARED_COLLECTION + namespace_suffix, "shared_collection"
        )
        if private_name == shared_name:
            raise VectorSchemaMismatch("private and shared collections must be physically distinct")
        self._client = client
        self.dimension = dimension
        self.dim = dimension
        self.index_schema_version = index_schema_version
        self.private_collection = private_name
        self.shared_collection = shared_name
        self._ready = False

    def collection_for(self, memory_kind: GraphKind | str | Enum) -> str:
        scope = collection_scope_for(memory_kind)
        return self.private_collection if scope == PRIVATE_SCOPE else self.shared_collection

    def ensure_ready(self) -> None:
        """Create missing collections, then enforce their immutable vector schema."""
        for name in (self.private_collection, self.shared_collection):
            if not bool(self._client.collection_exists(collection_name=name)):
                self._client.create_collection(
                    collection_name=name,
                    vectors_config={"size": self.dimension, "distance": "Cosine"},
                )
            self._assert_collection_schema(name)
            for field_name, field_schema in PAYLOAD_INDEXES:
                self._client.create_payload_index(
                    collection_name=name,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
                )
        self._ready = True

    def upsert(
        self,
        reference: VectorReference | VectorIndexMetadata | Mapping[str, object],
        vector: Sequence[float],
        *,
        point_id: Optional[str] = None,
    ) -> str:
        metadata = reference if isinstance(reference, VectorIndexMetadata) else None
        ref = _coerce_reference(reference, namespace=self.namespace)
        if ref.namespace != self.namespace:
            raise InvalidVectorPayload("reference namespace does not match physical collection namespace")
        if metadata is not None and metadata.embedding_dimension is not None:
            if metadata.embedding_dimension != self.dimension:
                raise VectorSchemaMismatch(
                    "metadata embedding_dimension %d does not match collection dimension %d"
                    % (metadata.embedding_dimension, self.dimension)
                )
        values = self._vector(vector)
        collection = self.collection_for(ref.memory_kind)
        self._ensure_operational(collection)
        pid = ref.point_id if point_id is None else _required_point_id(point_id)
        payload = ref.payload()
        # Validate the generated projection too.  This makes a future accidental
        # payload expansion fail at the adapter boundary until v3 is deliberate.
        VectorReference.from_payload(payload, namespace=self.namespace)
        self._client.upsert(
            collection_name=collection,
            points=({"id": pid, "vector": list(values), "payload": payload},),
            wait=True,
        )
        return pid

    def delete(
        self,
        reference: VectorReference | VectorIndexMetadata | Mapping[str, object],
        *,
        point_id: Optional[str] = None,
    ) -> str:
        """Idempotently remove one canonical reference from its physical scope."""

        ref = _coerce_reference(reference, namespace=self.namespace)
        if ref.namespace != self.namespace:
            raise InvalidVectorPayload(
                "reference namespace does not match physical collection namespace"
            )
        collection = self.collection_for(ref.memory_kind)
        self._ensure_operational(collection)
        pid = ref.point_id if point_id is None else _required_point_id(point_id)
        self._client.delete(
            collection_name=collection,
            points_selector={"points": [pid]},
            wait=True,
        )
        return pid

    def search(
        self,
        vector: Sequence[float],
        *,
        org_id: str,
        owner_user_id: Optional[str],
        memory_kind: GraphKind | str | Enum,
        repository_id: Optional[str],
        limit: int = 10,
    ) -> VectorSearchResult:
        values = self._vector(vector)
        kind = _normalize_kind(memory_kind)
        org = _required_query_identifier(org_id, "org_id")
        owner = _optional_query_identifier(owner_user_id, "owner_user_id")
        repository = _optional_query_identifier(repository_id, "repository_id")
        if kind in _PRIVATE_KINDS and owner is None:
            raise InvalidVectorQuery("private search requires owner_user_id")
        if kind == GraphKind.ORGANISATION_SEMANTIC and owner is not None:
            raise InvalidVectorQuery("organisation semantic search requires owner_user_id=None")
        if type(limit) is not int or limit <= 0:
            raise InvalidVectorQuery("limit must be a positive integer")

        collection = self.collection_for(kind)
        self._ensure_operational(collection)
        expected_scope = collection_scope_for(kind)
        conditions = (
            _match_condition("index_schema_version", self.index_schema_version),
            _match_condition("collection_scope", expected_scope),
            _match_condition("memory_kind", kind.value),
            _match_condition("org_id", org),
            _match_condition("owner_user_id", owner),
        )
        query_filter: dict[str, object] = {"must": list(conditions)}
        if kind == GraphKind.USER_EPISODIC:
            if repository is None:
                raise InvalidVectorQuery("episodic search requires repository_id")
            query_filter["must"].append(_match_condition("repository_id", repository))
            allowed_repositories = {repository}
        elif repository is None:
            query_filter["must"].append(_match_condition("repository_id", None))
            allowed_repositories = {None}
        else:
            # Semantic applicability is either target-repository exact or a
            # canonically reviewed/validated generalized NULL record.  This is
            # still a mandatory repository dimension: at least one branch must
            # match, and returned payloads are checked again below.
            query_filter["min_should"] = {
                "conditions": [
                    _match_condition("repository_id", repository),
                    _match_condition("repository_id", None),
                ],
                "min_count": 1,
            }
            allowed_repositories = {repository, None}
        response = self._client.query_points(
            collection_name=collection,
            query=list(values),
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        hits: list[VectorHit] = []
        rejections: list[RejectedVectorPoint] = []
        for raw in _response_points(response):
            raw_id = _point_value(raw, "id", "<unknown>")
            pid = str(raw_id) if raw_id not in (None, "") else "<unknown>"
            payload = _point_value(raw, "payload", None)
            try:
                reference = VectorReference.from_payload(payload, namespace=self.namespace)
            except (InvalidVectorPayload, TypeError, ValueError) as exc:
                rejections.append(
                    RejectedVectorPoint(pid, RejectionReason.INVALID_PAYLOAD, str(exc))
                )
                continue
            if (
                reference.index_schema_version != self.index_schema_version
                or reference.namespace != self.namespace
                or reference.collection_scope != expected_scope
                or reference.memory_kind != kind
                or reference.org_id != org
                or reference.owner_user_id != owner
                or reference.repository_id not in allowed_repositories
            ):
                rejections.append(
                    RejectedVectorPoint(
                        pid,
                        RejectionReason.FILTER_MISMATCH,
                        "returned payload does not match every mandatory query filter",
                    )
                )
                continue
            raw_score = _point_value(raw, "score", None)
            try:
                if isinstance(raw_score, bool):
                    raise ValueError
                score = float(raw_score)
                if not math.isfinite(score):
                    raise ValueError
            except (TypeError, ValueError):
                rejections.append(
                    RejectedVectorPoint(pid, RejectionReason.INVALID_SCORE, "score is not finite")
                )
                continue
            hits.append(VectorHit(pid, score, reference))
        return VectorSearchResult(tuple(hits), tuple(rejections))

    def _vector(self, vector: Sequence[float]) -> tuple[float, ...]:
        if isinstance(vector, (str, bytes, bytearray, Mapping)):
            raise VectorSchemaMismatch("vector must be a numeric sequence")
        try:
            raw_values = tuple(vector)
        except TypeError as exc:
            raise VectorSchemaMismatch("vector must be a numeric sequence") from exc
        if len(raw_values) != self.dimension:
            raise VectorSchemaMismatch(
                "vector dimension %d does not match locked dimension %d"
                % (len(raw_values), self.dimension)
            )
        values = []
        for value in raw_values:
            if isinstance(value, bool):
                raise VectorSchemaMismatch("vector entries must be finite numbers")
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise VectorSchemaMismatch("vector entries must be finite numbers") from exc
            if not math.isfinite(number):
                raise VectorSchemaMismatch("vector entries must be finite numbers")
            values.append(number)
        return tuple(values)

    def _ensure_operational(self, collection: str) -> None:
        if not self._ready:
            self.ensure_ready()
        # Re-read on every operation.  An operator replacing a collection with
        # the wrong dimension must fail closed even after this object was ready.
        self._assert_collection_schema(collection)

    def _assert_collection_schema(self, collection: str) -> None:
        info = self._client.get_collection(collection_name=collection)
        size, distance = _collection_vector_schema(info)
        if size != self.dimension:
            raise VectorSchemaMismatch(
                "collection %s has vector dimension %r; expected %d"
                % (collection, size, self.dimension)
            )
        if distance != "cosine":
            raise VectorSchemaMismatch(
                "collection %s has distance %r; expected Cosine" % (collection, distance)
            )


# Concise aliases for callers that do not need the version in the local name.
QdrantVectorIndex = QdrantVectorIndexV2
QdrantV2VectorIndex = QdrantVectorIndexV2


def _coerce_reference(
    value: VectorReference | VectorIndexMetadata | Mapping[str, object],
    *,
    namespace: str = DEFAULT_NAMESPACE,
) -> VectorReference:
    if isinstance(value, VectorReference):
        return value
    if isinstance(value, VectorIndexMetadata):
        return VectorReference.from_metadata(value)
    if isinstance(value, Mapping):
        return VectorReference.from_payload(value, namespace=namespace)
    raise TypeError("reference must be VectorReference, VectorIndexMetadata, or a v2 payload mapping")


def _required_query_identifier(value: object, name: str) -> str:
    try:
        return _required_identifier(value, name)
    except InvalidVectorPayload as exc:
        raise InvalidVectorQuery(str(exc)) from exc


def _optional_query_identifier(value: object, name: str) -> Optional[str]:
    try:
        return _optional_identifier(value, name)
    except InvalidVectorPayload as exc:
        raise InvalidVectorQuery(str(exc)) from exc


def _required_collection_name(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VectorSchemaMismatch("%s must be a non-empty string" % name)
    return value


def _required_point_id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidVectorPayload("point_id must be a non-empty string")
    return value


def _match_condition(key: str, value: object) -> dict[str, object]:
    # Qdrant represents NULL filtering with IsNullCondition, not MatchValue.
    if value is None:
        return {"is_null": {"key": key}}
    return {"key": key, "match": {"value": value}}


def _response_points(response: object) -> Sequence[object]:
    points = response.get("points") if isinstance(response, Mapping) else getattr(response, "points", None)
    if points is None or isinstance(points, (str, bytes, bytearray, Mapping)):
        raise VectorIndexError("Qdrant query response has no point sequence")
    try:
        return tuple(points)
    except TypeError as exc:
        raise VectorIndexError("Qdrant query response has no point sequence") from exc


def _point_value(point: object, name: str, default: object) -> object:
    return point.get(name, default) if isinstance(point, Mapping) else getattr(point, name, default)


def _collection_vector_schema(info: object) -> tuple[int, str]:
    """Extract the unnamed vector schema from mapping or qdrant-client objects."""
    vectors: object = None
    if isinstance(info, Mapping):
        vectors = info.get("vectors_config", info.get("vectors"))
        if vectors is None:
            config = info.get("config")
            if isinstance(config, Mapping):
                params = config.get("params")
                if isinstance(params, Mapping):
                    vectors = params.get("vectors")
    else:
        config = getattr(info, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", None)
        if vectors is None:
            vectors = getattr(info, "vectors_config", None)

    if isinstance(vectors, Mapping):
        if "size" not in vectors or "distance" not in vectors:
            raise VectorSchemaMismatch("named or malformed vector configuration is unsupported")
        size = vectors["size"]
        distance = vectors["distance"]
    else:
        size = getattr(vectors, "size", None)
        distance = getattr(vectors, "distance", None)
    if type(size) is not int or size <= 0:
        raise VectorSchemaMismatch("collection vector size is missing or invalid")
    if isinstance(distance, Enum):
        distance = distance.value
    normalized = str(distance).split(".")[-1].strip().lower() if distance is not None else ""
    return size, normalized


__all__ = [
    "INDEX_SCHEMA_VERSION",
    "PRIVATE_COLLECTION",
    "PRIVATE_SCOPE",
    "PAYLOAD_FIELDS",
    "PAYLOAD_INDEXES",
    "SHARED_COLLECTION",
    "SHARED_SCOPE",
    "InvalidVectorPayload",
    "InvalidVectorQuery",
    "Qdrant112ClientAdapter",
    "QdrantClientProtocol",
    "QdrantV2VectorIndex",
    "QdrantVectorIndex",
    "QdrantVectorIndexV2",
    "RejectedVectorPoint",
    "RejectionReason",
    "VectorHit",
    "VectorIndexError",
    "VectorIndexProtocol",
    "VectorReference",
    "VectorSchemaMismatch",
    "VectorSearchResult",
    "collection_for",
    "collection_scope_for",
    "point_id_for",
]
