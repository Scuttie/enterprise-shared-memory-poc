"""Credential-free unit tests for the strict TriMem Qdrant v2 adapter."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import Enum

import pytest

from enterprise_memory.trimem.schema import GraphKind, VectorIndexMetadata
from enterprise_memory.trimem.vector_index import (
    INDEX_SCHEMA_VERSION,
    PAYLOAD_FIELDS,
    PAYLOAD_INDEXES,
    PRIVATE_COLLECTION,
    SHARED_COLLECTION,
    InvalidVectorPayload,
    InvalidVectorQuery,
    Qdrant112ClientAdapter,
    QdrantClientProtocol,
    QdrantVectorIndexV2,
    RejectionReason,
    VectorIndexError,
    VectorReference,
    VectorSchemaMismatch,
)


class FakeQdrantClient:
    """Primitive Qdrant double; deliberately imports no qdrant-client types."""

    def __init__(self):
        self.collections = {}
        self.payload_indexes = {}
        self.query_calls = []
        self.ignore_filters = False

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, *, vectors_config):
        if collection_name in self.collections:
            raise AssertionError("collection already exists")
        self.collections[collection_name] = {
            "vectors_config": dict(vectors_config),
            "points": {},
        }

    def get_collection(self, collection_name):
        row = self.collections[collection_name]
        return {"vectors_config": dict(row["vectors_config"])}

    def create_payload_index(
        self, collection_name, *, field_name, field_schema, wait
    ):
        assert wait is True
        self.payload_indexes.setdefault(collection_name, set()).add(
            (field_name, field_schema)
        )

    def upsert(self, collection_name, *, points, wait):
        assert wait is True
        collection = self.collections[collection_name]
        for point in points:
            collection["points"][str(point["id"])] = {
                "id": str(point["id"]),
                "vector": list(point["vector"]),
                "payload": dict(point["payload"]),
            }

    def delete(self, collection_name, *, points_selector, wait):
        assert wait is True
        for point_id in points_selector["points"]:
            self.collections[collection_name]["points"].pop(str(point_id), None)

    def query_points(
        self,
        collection_name,
        *,
        query,
        query_filter,
        limit,
        with_payload,
        with_vectors,
    ):
        assert with_payload is True and with_vectors is False
        self.query_calls.append(
            {
                "collection_name": collection_name,
                "query": list(query),
                "query_filter": query_filter,
                "limit": limit,
            }
        )
        rows = []
        for point in self.collections[collection_name]["points"].values():
            if not self.ignore_filters and not _matches_filter(
                point["payload"], query_filter
            ):
                continue
            rows.append(
                {
                    "id": point["id"],
                    "score": _cosine(query, point["vector"]),
                    "payload": dict(point["payload"]),
                }
            )
        rows.sort(key=lambda row: (-row["score"], row["id"]))
        return {"points": rows[:limit]}

    def seed_raw(self, collection_name, point_id, vector, payload):
        self.collections[collection_name]["points"][point_id] = {
            "id": point_id,
            "vector": list(vector),
            "payload": dict(payload),
        }


class _FakeDistance(str, Enum):
    COSINE = "Cosine"


class _FakePayloadSchemaType(str, Enum):
    INTEGER = "integer"
    KEYWORD = "keyword"


@dataclass(frozen=True)
class _FakeVectorParams:
    size: int
    distance: _FakeDistance


@dataclass(frozen=True)
class _FakePointStruct:
    id: str
    vector: list[float]
    payload: dict[str, object]


@dataclass(frozen=True)
class _FakePointIdsList:
    points: list[str]


class _FakeFilter:
    def __init__(self, **fields):
        self.fields = fields


class _FakeQdrantModels:
    Distance = _FakeDistance
    Filter = _FakeFilter
    PayloadSchemaType = _FakePayloadSchemaType
    PointIdsList = _FakePointIdsList
    PointStruct = _FakePointStruct
    VectorParams = _FakeVectorParams


class _RawQdrantRecorder:
    def __init__(self):
        self.calls = []
        self.marker = object()
        self.closed = False

    def create_collection(self, **kwargs):
        self.calls.append(("create_collection", kwargs))
        return "created"

    def create_payload_index(self, **kwargs):
        self.calls.append(("create_payload_index", kwargs))
        return "indexed"

    def upsert(self, **kwargs):
        self.calls.append(("upsert", kwargs))
        return "upserted"

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return "deleted"

    def query_points(self, **kwargs):
        self.calls.append(("query_points", kwargs))
        return {"points": []}

    def count(self, **kwargs):
        self.calls.append(("count", kwargs))
        return {"count": 7}

    def close(self):
        self.closed = True
        return "closed"


def test_qdrant_112_adapter_converts_every_transport_sensitive_model():
    raw = _RawQdrantRecorder()
    client = Qdrant112ClientAdapter(raw, model_api=_FakeQdrantModels)

    assert client.marker is raw.marker  # unknown attributes are transparent
    assert client.create_collection(
        "collection", vectors_config={"size": 3, "distance": "Cosine"}
    ) == "created"
    create = raw.calls[-1][1]
    assert create["vectors_config"] == _FakeVectorParams(
        size=3, distance=_FakeDistance.COSINE
    )

    assert client.create_payload_index(
        "collection", field_name="repository_id", field_schema="keyword", wait=True
    ) == "indexed"
    payload_index = raw.calls[-1][1]
    assert payload_index["field_schema"] == _FakePayloadSchemaType.KEYWORD

    point = {
        "id": "point-a",
        "vector": [1.0, 0.0, 0.0],
        "payload": {"graph_id": "graph-a"},
    }
    assert client.upsert("collection", points=(point,), wait=True) == "upserted"
    upsert = raw.calls[-1][1]
    assert upsert["points"] == [_FakePointStruct(**point)]
    assert isinstance(upsert["points"], list)

    assert client.delete(
        "collection", points_selector={"points": ["point-a"]}, wait=True
    ) == "deleted"
    deleted = raw.calls[-1][1]
    assert deleted["points_selector"] == _FakePointIdsList(points=["point-a"])

    query_filter = {
        "must": [{"key": "org_id", "match": {"value": "org-a"}}],
        "min_should": {
            "conditions": [
                {"key": "repository_id", "match": {"value": "repo-a"}},
                {"is_null": {"key": "repository_id"}},
            ],
            "min_count": 1,
        },
    }
    assert client.query_points(
        "collection",
        query=(1.0, 0.0, 0.0),
        query_filter=query_filter,
        limit=2,
        with_payload=True,
        with_vectors=False,
    ) == {"points": []}
    query = raw.calls[-1][1]
    assert query["query"] == [1.0, 0.0, 0.0]
    assert isinstance(query["query_filter"], _FakeFilter)
    assert query["query_filter"].fields == query_filter

    assert client.count(collection_name="collection", exact=True) == {"count": 7}
    assert client.close() == "closed"
    assert raw.closed is True


def test_qdrant_112_adapter_is_import_free_with_injected_model_api(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def reject_qdrant(name, *args, **kwargs):
        if name == "qdrant_client" or name.startswith("qdrant_client."):
            raise AssertionError("injected adapter must not import qdrant-client")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_qdrant)
    client = Qdrant112ClientAdapter(
        _RawQdrantRecorder(), model_api=_FakeQdrantModels
    )
    assert client.create_collection(
        "collection", vectors_config={"size": 3, "distance": "Cosine"}
    ) == "created"


def test_qdrant_112_adapter_fails_closed_when_optional_dependency_is_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def missing_qdrant(name, *args, **kwargs):
        if name == "qdrant_client" or name.startswith("qdrant_client."):
            raise ModuleNotFoundError("simulated missing qdrant-client")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_qdrant)
    with pytest.raises(VectorIndexError, match="qdrant-client 1.12 models"):
        Qdrant112ClientAdapter(_RawQdrantRecorder())


def _matches(payload, conditions):
    for condition in conditions:
        if "is_null" in condition:
            if payload.get(condition["is_null"]["key"]) is not None:
                return False
        else:
            key = condition["key"]
            if payload.get(key) != condition["match"]["value"]:
                return False
    return True


def _matches_filter(payload, query_filter):
    if not _matches(payload, query_filter["must"]):
        return False
    minimum = query_filter.get("min_should")
    if minimum:
        conditions = minimum["conditions"]
        matched = sum(1 for condition in conditions if _matches(payload, (condition,)))
        if matched < int(minimum["min_count"]):
            return False
    return True


def _cosine(left, right):
    numerator = sum(a * b for a, b in zip(left, right))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(
        sum(b * b for b in right)
    )
    return numerator / denominator if denominator else 0.0


def _hash(label):
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _reference(
    node_id,
    kind=GraphKind.USER_EPISODIC,
    *,
    org_id="org-a",
    owner_user_id="alice",
    repository_id="repo-a",
    namespace="unit-test",
):
    if kind == GraphKind.ORGANISATION_SEMANTIC:
        owner_user_id = None
    return VectorReference(
        graph_id="graph-" + node_id,
        node_id=node_id,
        content_hash=_hash(node_id[0]),
        org_id=org_id,
        memory_kind=kind,
        owner_user_id=owner_user_id,
        repository_id=repository_id,
        namespace=namespace,
    )


def _filters_by_key(call):
    result = {}
    for condition in call["query_filter"]["must"]:
        if "is_null" in condition:
            result[condition["is_null"]["key"]] = None
        else:
            result[condition["key"]] = condition["match"]["value"]
    return result


def test_private_kinds_share_one_physical_collection_and_org_semantic_is_separate():
    client = FakeQdrantClient()
    index = QdrantVectorIndexV2(client, 3)
    assert isinstance(client, QdrantClientProtocol)

    index.ensure_ready()
    assert set(client.collections) == {PRIVATE_COLLECTION, SHARED_COLLECTION}
    assert PRIVATE_COLLECTION != SHARED_COLLECTION
    for collection in (PRIVATE_COLLECTION, SHARED_COLLECTION):
        assert client.collections[collection]["vectors_config"] == {
            "size": 3,
            "distance": "Cosine",
        }
        assert client.payload_indexes[collection] == set(PAYLOAD_INDEXES)

    episode = _reference("episode", GraphKind.USER_EPISODIC)
    user_rule = _reference("user-rule", GraphKind.USER_SEMANTIC)
    org_rule = _reference("org-rule", GraphKind.ORGANISATION_SEMANTIC)
    index.upsert(episode, [1, 0, 0])
    index.upsert(user_rule, [0, 1, 0])
    index.upsert(org_rule, [0, 0, 1])

    private_payloads = [
        point["payload"] for point in client.collections[PRIVATE_COLLECTION]["points"].values()
    ]
    shared_payloads = [
        point["payload"] for point in client.collections[SHARED_COLLECTION]["points"].values()
    ]
    assert {row["memory_kind"] for row in private_payloads} == {
        "USER_EPISODIC",
        "USER_SEMANTIC",
    }
    assert [row["memory_kind"] for row in shared_payloads] == [
        "ORGANISATION_SEMANTIC"
    ]


def test_delete_is_scope_routed_stable_and_idempotent():
    client = FakeQdrantClient()
    index = QdrantVectorIndexV2(client, 3)
    index.ensure_ready()
    private = _reference("delete-private", GraphKind.USER_SEMANTIC)
    shared = _reference("delete-shared", GraphKind.ORGANISATION_SEMANTIC)
    private_id = index.upsert(private, [1, 0, 0])
    shared_id = index.upsert(shared, [0, 1, 0])

    assert index.delete(private) == private_id
    assert private_id not in client.collections[PRIVATE_COLLECTION]["points"]
    assert shared_id in client.collections[SHARED_COLLECTION]["points"]
    assert index.delete(private) == private_id
    assert index.delete(shared) == shared_id
    assert shared_id not in client.collections[SHARED_COLLECTION]["points"]


def test_nondefault_namespace_gets_exclusive_physical_collections_and_is_checked():
    namespace = "trimem:experiment-a:dev:m2"
    client = FakeQdrantClient()
    index = QdrantVectorIndexV2(client, 3, namespace=namespace)
    index.ensure_ready()
    assert index.private_collection.startswith(PRIVATE_COLLECTION + "_")
    assert index.shared_collection.startswith(SHARED_COLLECTION + "_")
    assert set(client.collections) == {index.private_collection, index.shared_collection}

    index.upsert(_reference("local", namespace=namespace), [1, 0, 0])
    payload = next(iter(client.collections[index.private_collection]["points"].values()))["payload"]
    assert set(payload) == PAYLOAD_FIELDS
    assert "namespace" not in payload  # v2 isolation is physical, not a silent payload expansion
    with pytest.raises(InvalidVectorPayload, match="namespace"):
        index.upsert(_reference("foreign", namespace="trimem:other:dev:m2"), [1, 0, 0])


def test_payload_is_an_exact_reference_projection_and_metadata_is_supported():
    client = FakeQdrantClient()
    index = QdrantVectorIndexV2(client, 3)
    metadata = VectorIndexMetadata(
        graph_id="graph-a",
        node_id="node-a",
        org_id="org-a",
        memory_kind=GraphKind.USER_SEMANTIC,
        canonical_content_hash=_hash("a"),
        owner_user_id="alice",
        repository_id="repo-a",
        embedding_model_id="frozen-embedder",
        embedding_revision="revision-a",
        embedding_dimension=3,
    )
    index.upsert(metadata, [1, 0, 0])
    payload = next(
        iter(client.collections[PRIVATE_COLLECTION]["points"].values())
    )["payload"]

    assert set(payload) == PAYLOAD_FIELDS
    assert payload["graph_id"] == "graph-a"
    assert payload["node_id"] == "node-a"
    assert payload["content_hash"] == metadata.canonical_content_hash
    assert payload["index_schema_version"] == INDEX_SCHEMA_VERSION
    forbidden = {
        "canonical_payload",
        "canonical_content",
        "retrieval_text",
        "execution_view",
        "text",
        "embedding_model_id",
        "embedding_revision",
        "embedding_dimension",
    }
    assert forbidden.isdisjoint(payload)
    assert "frozen-embedder" not in repr(payload)


def test_every_query_has_org_owner_kind_repository_scope_and_version_filters():
    client = FakeQdrantClient()
    index = QdrantVectorIndexV2(client, 3)
    wanted = _reference("wanted", GraphKind.USER_SEMANTIC)
    index.upsert(wanted, [1, 0, 0])
    index.upsert(
        _reference("other-owner", GraphKind.USER_SEMANTIC, owner_user_id="bob"),
        [1, 0, 0],
    )
    index.upsert(
        _reference("other-org", GraphKind.USER_SEMANTIC, org_id="org-b"),
        [1, 0, 0],
    )
    index.upsert(
        _reference("other-repo", GraphKind.USER_SEMANTIC, repository_id="repo-b"),
        [1, 0, 0],
    )
    index.upsert(
        _reference("generalized", GraphKind.USER_SEMANTIC, repository_id=None),
        [1, 0, 0],
    )
    index.upsert(_reference("episode", GraphKind.USER_EPISODIC), [1, 0, 0])

    result = index.search(
        [1, 0, 0],
        org_id="org-a",
        owner_user_id="alice",
        memory_kind=GraphKind.USER_SEMANTIC,
        repository_id="repo-a",
    )
    assert [hit.reference.node_id for hit in result] == ["generalized", "wanted"]
    assert _filters_by_key(client.query_calls[-1]) == {
        "index_schema_version": 2,
        "collection_scope": "private",
        "memory_kind": "USER_SEMANTIC",
        "org_id": "org-a",
        "owner_user_id": "alice",
    }
    assert client.query_calls[-1]["query_filter"]["min_should"] == {
        "conditions": [
            {"key": "repository_id", "match": {"value": "repo-a"}},
            {"is_null": {"key": "repository_id"}},
        ],
        "min_count": 1,
    }

    org = _reference(
        "global-org-rule",
        GraphKind.ORGANISATION_SEMANTIC,
        repository_id=None,
    )
    index.upsert(org, [0, 1, 0])
    shared = index.search(
        [0, 1, 0],
        org_id="org-a",
        owner_user_id=None,
        memory_kind="ORG_SEMANTIC",
        repository_id=None,
    )
    assert [hit.reference.node_id for hit in shared] == ["global-org-rule"]
    shared_filters = _filters_by_key(client.query_calls[-1])
    assert shared_filters["owner_user_id"] is None
    assert shared_filters["repository_id"] is None
    assert client.query_calls[-1]["collection_name"] == SHARED_COLLECTION

    with pytest.raises(TypeError):
        index.search(  # owner and repository are intentionally not optional arguments
            [0, 1, 0], org_id="org-a", memory_kind="ORG_SEMANTIC"
        )
    with pytest.raises(InvalidVectorQuery, match="owner_user_id"):
        index.search(
            [1, 0, 0],
            org_id="org-a",
            owner_user_id=None,
            memory_kind=GraphKind.USER_EPISODIC,
            repository_id="repo-a",
        )


def test_untrusted_wrong_payloads_are_rejected_after_server_filtering():
    client = FakeQdrantClient()
    index = QdrantVectorIndexV2(client, 3)
    valid = _reference("valid", GraphKind.USER_SEMANTIC)
    index.upsert(valid, [1, 0, 0])

    with_extra_content = valid.payload()
    with_extra_content["canonical_payload"] = {
        "retrieval_text": "must never cross the index boundary"
    }
    client.seed_raw(
        PRIVATE_COLLECTION, "rogue-content", [1, 0, 0], with_extra_content
    )
    wrong_version = valid.payload()
    wrong_version["index_schema_version"] = 1
    client.seed_raw(PRIVATE_COLLECTION, "rogue-version", [1, 0, 0], wrong_version)
    wrong_owner = valid.payload()
    wrong_owner["owner_user_id"] = "mallory"
    client.seed_raw(PRIVATE_COLLECTION, "rogue-owner", [1, 0, 0], wrong_owner)

    # Simulate a server/client bug that ignores the Qdrant filter.  The adapter
    # repeats every check and still exposes only the valid reference.
    client.ignore_filters = True
    result = index.search(
        [1, 0, 0],
        org_id="org-a",
        owner_user_id="alice",
        memory_kind=GraphKind.USER_SEMANTIC,
        repository_id="repo-a",
    )
    assert [hit.reference.node_id for hit in result] == ["valid"]
    assert {rejection.point_id: rejection.reason for rejection in result.rejections} == {
        "rogue-content": RejectionReason.INVALID_PAYLOAD,
        "rogue-owner": RejectionReason.FILTER_MISMATCH,
        "rogue-version": RejectionReason.INVALID_PAYLOAD,
    }
    assert "must never cross" not in repr(result)

    bad_ingress = valid.payload()
    bad_ingress["text"] = "canonical text"
    with pytest.raises(InvalidVectorPayload, match="extra"):
        index.upsert(bad_ingress, [1, 0, 0])


def test_vector_dimension_collection_schema_and_metadata_dimension_are_locked():
    client = FakeQdrantClient()
    index = QdrantVectorIndexV2(client, 3)
    reference = _reference("node")
    with pytest.raises(VectorSchemaMismatch, match="dimension"):
        index.upsert(reference, [1, 0])
    with pytest.raises(VectorSchemaMismatch, match="finite"):
        index.upsert(reference, [1, float("nan"), 0])

    index.ensure_ready()
    client.collections[PRIVATE_COLLECTION]["vectors_config"]["size"] = 4
    with pytest.raises(VectorSchemaMismatch, match="expected 3"):
        index.upsert(reference, [1, 0, 0])

    wrong_client = FakeQdrantClient()
    wrong_client.create_collection(
        PRIVATE_COLLECTION, vectors_config={"size": 3, "distance": "Dot"}
    )
    wrong_client.create_collection(
        SHARED_COLLECTION, vectors_config={"size": 3, "distance": "Cosine"}
    )
    with pytest.raises(VectorSchemaMismatch, match="Cosine"):
        QdrantVectorIndexV2(wrong_client, 3).ensure_ready()

    metadata_client = FakeQdrantClient()
    metadata_index = QdrantVectorIndexV2(metadata_client, 3)
    metadata = VectorIndexMetadata(
        graph_id="graph",
        node_id="node",
        org_id="org-a",
        memory_kind=GraphKind.USER_EPISODIC,
        canonical_content_hash=_hash("m"),
        owner_user_id="alice",
        repository_id="repo-a",
        embedding_dimension=4,
    )
    with pytest.raises(VectorSchemaMismatch, match="embedding_dimension"):
        metadata_index.upsert(metadata, [1, 0, 0])

    with pytest.raises(VectorSchemaMismatch, match="schema v2"):
        QdrantVectorIndexV2(FakeQdrantClient(), 3, index_schema_version=1)


def test_reference_rejects_scope_confusion_and_noncanonical_payload_kind():
    private = _reference("private")
    payload = private.payload()
    payload["collection_scope"] = "shared"
    with pytest.raises(InvalidVectorPayload, match="collection_scope"):
        VectorReference.from_payload(payload)

    org_alias = _reference("org", GraphKind.ORGANISATION_SEMANTIC).payload()
    org_alias["memory_kind"] = "ORG_SEMANTIC"
    with pytest.raises(InvalidVectorPayload, match="canonical"):
        VectorReference.from_payload(org_alias)

    with pytest.raises(InvalidVectorPayload, match="owner_user_id"):
        VectorReference(
            graph_id="g",
            node_id="n",
            content_hash=_hash("x"),
            org_id="o",
            memory_kind=GraphKind.ORGANISATION_SEMANTIC,
            owner_user_id="alice",
            repository_id="r",
        )

    invalid_hash = private.payload()
    invalid_hash["content_hash"] = "not-a-canonical-digest"
    with pytest.raises(InvalidVectorPayload, match="sha256"):
        VectorReference.from_payload(invalid_hash)
