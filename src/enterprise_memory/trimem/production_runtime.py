"""Fail-closed production wiring for one streaming TriMem benchmark arm.

This module is intentionally a composition boundary.  PostgreSQL remains the
canonical authority, Qdrant receives reference-only candidate points after a
canonical transaction commits, and the synchronous benchmark driver talks to
the asynchronous repository through one long-lived event-loop thread.

The factory does not silently substitute any in-memory product backend.  Unit
tests may inject production-shaped fakes through the explicit factory hooks.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
import inspect
import json
import math
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse
import uuid

from .accounting import canonical_bytes, sha256_bytes, strict_json_loads
from .agent_runtime import NoMemoryController, NullExperienceLifecycle
from .arms import ActiveNodeTriMemController
from .checkpoint import RuntimeCheckpoint
from .policy import CheckpointError, DoubleDQNMemoryPolicy
from .postgres_retrieval import (
    AsyncPostgresQdrantRetrievalStore,
    PostgresInjectionAuditor,
    SyncPostgresQdrantRetrievalStore,
    production_v03_controller_factory,
)
from .postgres_store import LifecycleAppendBundle, PostgresTriMemStore
from .production_v03_lifecycle import production_v03_lifecycle_factory
from .ppr import PinnedSentenceTransformerPPR
from .retrieval import RetrievalConfig, TriMemoryRetriever
from .schema import (
    AccessContext,
    DEFAULT_NAMESPACE,
    GraphKind,
    LifecycleState,
    VectorIndexMetadata,
)
from .store import NotFound
from .vector_index import Qdrant112ClientAdapter, QdrantVectorIndexV2
from .working_graph import ShortTermWorkingGraph


_ARM_IDS = frozenset({"M0", "M1", "M2"})
_SPLITS = frozenset({"development", "heldout", "credential_free_replay"})
_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_CHECKPOINT_SCHEMA = "trimem/benchmark-arm-checkpoint/1.0"
_PREPARED_TASK_SCHEMA = "trimem/benchmark-prepared-task-checkpoint/1.0"
_RECEIPT_TABLE = "trimem_lifecycle_operation_receipts"
_AGENT_CHECKPOINT_STATES = frozenset({
    "DECOMPOSED",
    "RUNNING",
    "AGENT_COMPLETE",
    "PATCH_FINALIZED",
    "GRADED",
    "GRADER_FAILED",
    "EXTRACTED",
    "LIFECYCLE_STORED",
    "LIFECYCLE_CREDITED",
    "DONE",
})


class ProductionRuntimeError(RuntimeError):
    """Base error for a production arm that cannot prove a safe state."""


class ProductionDependencyError(ProductionRuntimeError):
    """A required production dependency is unavailable or invalid."""


class FreshnessViolation(ProductionRuntimeError):
    """An arm namespace contains data or cannot be proven empty."""


class SessionStateError(ProductionRuntimeError):
    """The benchmark driver called the arm session out of order."""


class CheckpointTamperError(ProductionRuntimeError):
    """A session checkpoint is malformed, mismatched, or stale."""


def _sha256(value: Any) -> str:
    return "sha256:" + sha256_bytes(canonical_bytes(value))


def _required_component(value: object, name: str) -> str:
    if not isinstance(value, str) or not _COMPONENT.fullmatch(value):
        raise ValueError(
            "%s must match %s" % (name, _COMPONENT.pattern)
        )
    return value


def benchmark_namespace(experiment_id: str, split: str, arm_id: str) -> str:
    """Return the only namespace form accepted by the benchmark factory."""

    experiment = _required_component(experiment_id, "experiment_id")
    selected_split = _required_component(split, "split")
    selected_arm = _required_component(arm_id, "arm_id")
    if selected_split not in _SPLITS:
        raise ValueError("unsupported benchmark split")
    if selected_arm not in _ARM_IDS:
        raise ValueError("arm_id must be M0, M1, or M2")
    namespace = "trimem:%s:%s:%s" % (experiment, selected_split, selected_arm)
    if namespace == DEFAULT_NAMESPACE:
        raise ValueError("benchmark namespace cannot be the unit-test namespace")
    return namespace


def _task_value(task: object, name: str) -> Optional[str]:
    value = task.get(name) if isinstance(task, Mapping) else getattr(task, name, None)
    if value is None:
        return None
    result = str(value)
    return result if result.strip() else None


def _task_id(task: object) -> str:
    value = _task_value(task, "task_id")
    if value is None and isinstance(task, str):
        value = task
    if value is None:
        raise ValueError("every task_order entry must expose a non-empty task_id")
    return value


def _task_context(task: object) -> AccessContext:
    org_id = _task_value(task, "org_id")
    user_id = _task_value(task, "user_id")
    if org_id is None or user_id is None:
        raise ValueError("every task_order entry must expose org_id and user_id")
    return AccessContext(org_id=org_id, user_id=user_id)


def _normalize_task_order(task_order: Sequence[object]) -> tuple[tuple[object, ...], tuple[str, ...], AccessContext]:
    if isinstance(task_order, (str, bytes, bytearray)):
        raise ValueError("task_order must be a sequence of task objects")
    tasks = tuple(task_order)
    if not tasks:
        raise ValueError("task_order cannot be empty")
    ids = tuple(_task_id(task) for task in tasks)
    if len(set(ids)) != len(ids):
        raise ValueError("task_order contains duplicate task_id values")
    contexts = tuple(_task_context(task) for task in tasks)
    if any(context != contexts[0] for context in contexts[1:]):
        # namespace_evidence is evaluated under PostgreSQL RLS.  A mixed-user
        # stream would not prove that every private row in the namespace is
        # empty, so the production boundary refuses it.
        raise ValueError("one benchmark arm namespace requires one org/user access context")
    return tasks, ids, contexts[0]


def _task_order_payload(task: object) -> Mapping[str, Any]:
    """Canonical public identity of one frozen task, not merely its display id."""

    public = getattr(task, "public_payload", None)
    if callable(public):
        value = public()
        if not isinstance(value, Mapping):
            raise ValueError("task public_payload must return a mapping")
        return _json_value(value)
    fields = (
        "task_id",
        "org_id",
        "user_id",
        "repository",
        "commit",
        "instruction",
        "editable_paths",
    )
    payload = {
        name: _json_value(value)
        for name in fields
        if (value := _task_value(task, name)) is not None
    }
    if not {"task_id", "org_id", "user_id"} <= set(payload):
        raise ValueError("task order entry lacks a canonical public identity")
    return payload


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
        return value.value
    raise TypeError("value is not canonically JSON serializable: %s" % type(value).__name__)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        result = asdict(value)
        if isinstance(result, Mapping):
            return result
    raise ProductionRuntimeError("%s must be a mapping or dataclass" % label)


def _verified_receipt_suffix(
    previous: object,
    current: object,
    *,
    namespace: str,
    owner_user_id: str,
) -> tuple[Mapping[str, Any], ...]:
    """Return only an append-only, hash-sealed canonical receipt suffix."""

    normalized: list[Mapping[str, Any]] = []
    for label, value in (("checkpoint", previous), ("current", current)):
        data = _mapping(value, "%s lifecycle receipt evidence" % label)
        digest = data.get("digest")
        body = {key: item for key, item in data.items() if key != "digest"}
        rows = body.get("rows")
        if (
            body.get("schema") != "trimem/lifecycle-receipt-evidence/1.0"
            or body.get("namespace") != namespace
            or body.get("owner_user_id") != owner_user_id
            or not isinstance(rows, list)
            or _sha256(body) != digest
            or any(not isinstance(row, Mapping) for row in rows)
        ):
            raise CheckpointTamperError(
                "%s lifecycle receipt evidence is invalid" % label
            )
        normalized.append(data)
    for label, data in zip(("checkpoint", "current"), normalized):
        rows = list(data["rows"])
        operation_ids: set[str] = set()
        ordering: list[tuple[str, str]] = []
        for row in rows:
            expected_fields = {
                "operation_id",
                "bundle_digest",
                "receipt_payload_digest",
                "index_node_ids",
                "index_intent_ids",
                "delete_node_ids",
                "delete_intent_ids",
                "access_event_ids",
                "canonical_row_deltas",
                "operation_scope",
                "created_at",
            }
            if set(row) != expected_fields:
                raise CheckpointTamperError(
                    "%s lifecycle receipt row has an invalid shape" % label
                )
            operation_id = row.get("operation_id")
            try:
                canonical_operation_id = str(uuid.UUID(str(operation_id)))
            except (AttributeError, TypeError, ValueError) as exc:
                raise CheckpointTamperError(
                    "%s lifecycle receipt operation ID is invalid" % label
                ) from exc
            if canonical_operation_id != operation_id or operation_id in operation_ids:
                raise CheckpointTamperError(
                    "%s lifecycle receipt operation ID is duplicate/noncanonical" % label
                )
            operation_ids.add(operation_id)
            if any(
                not isinstance(row.get(name), str)
                or not _SHA256.fullmatch(str(row.get(name)))
                for name in ("bundle_digest", "receipt_payload_digest")
            ):
                raise CheckpointTamperError(
                    "%s lifecycle receipt digest is invalid" % label
                )
            for name in (
                "index_node_ids",
                "index_intent_ids",
                "delete_node_ids",
                "delete_intent_ids",
                "access_event_ids",
            ):
                identifiers = row.get(name)
                if (
                    not isinstance(identifiers, list)
                    or any(not isinstance(item, str) or not item for item in identifiers)
                    or len(set(identifiers)) != len(identifiers)
                ):
                    raise CheckpointTamperError(
                        "%s lifecycle receipt identifiers are invalid" % label
                    )
            scope = row.get("operation_scope")
            if not isinstance(scope, Mapping) or set(scope) != {
                "kind", "task_id", "active_node_ids"
            }:
                raise CheckpointTamperError(
                    "%s lifecycle receipt scope is invalid" % label
                )
            active = scope.get("active_node_ids")
            if (
                scope.get("kind") not in {
                    "LIFECYCLE_STORE", "CREDIT", "FINALIZE", "ACCESS"
                }
                or not isinstance(scope.get("task_id"), str)
                or not scope.get("task_id")
                or not isinstance(active, list)
                or any(not isinstance(item, str) or not item for item in active)
                or active != sorted(set(active))
            ):
                raise CheckpointTamperError(
                    "%s lifecycle receipt scope is invalid" % label
                )
            created_at = row.get("created_at")
            if not isinstance(created_at, str) or not created_at:
                raise CheckpointTamperError(
                    "%s lifecycle receipt timestamp is invalid" % label
                )
            ordering.append((created_at, operation_id))
        if ordering != sorted(ordering):
            raise CheckpointTamperError(
                "%s lifecycle receipt ordering is invalid" % label
            )

    before_rows = list(normalized[0]["rows"])
    after_rows = list(normalized[1]["rows"])
    if len(after_rows) < len(before_rows) or after_rows[: len(before_rows)] != before_rows:
        raise CheckpointTamperError(
            "canonical lifecycle receipt ledger is not append-only"
        )
    return tuple(dict(row) for row in after_rows[len(before_rows) :])


def _canonical_counts(value: object) -> dict[str, int]:
    data = _mapping(value, "canonical namespace evidence")
    rows = data.get("row_counts")
    if not isinstance(rows, (list, tuple)):
        raise CheckpointTamperError("canonical row-count evidence is malformed")
    result: dict[str, int] = {}
    for row in rows:
        if (
            not isinstance(row, (list, tuple))
            or len(row) != 2
            or not isinstance(row[0], str)
            or type(row[1]) is not int
            or row[1] < 0
            or row[0] in result
        ):
            raise CheckpointTamperError("canonical row-count evidence is malformed")
        result[row[0]] = row[1]
    return result


def _verified_canonical_receipt_delta(
    previous: object,
    current: object,
    suffix: Sequence[Mapping[str, Any]],
) -> None:
    """Require every canonical count change to be transaction-receipt bound."""

    before = _canonical_counts(previous)
    after = _canonical_counts(current)
    if set(before) != set(after) or _RECEIPT_TABLE not in before:
        raise CheckpointTamperError("canonical namespace table set changed during resume")
    totals = {
        table: {"inserted": 0, "updated": 0, "deleted": 0}
        for table in before
    }
    for row in suffix:
        deltas = row.get("canonical_row_deltas")
        if not isinstance(deltas, Mapping) or set(deltas) != set(before):
            raise CheckpointTamperError("receipt canonical row delta table set is invalid")
        for table, raw in deltas.items():
            if not isinstance(raw, Mapping) or set(raw) != {
                "inserted", "updated", "deleted"
            }:
                raise CheckpointTamperError("receipt canonical row delta is malformed")
            values = {name: raw.get(name) for name in ("inserted", "updated", "deleted")}
            if any(type(value) is not int or value < 0 for value in values.values()):
                raise CheckpointTamperError("receipt canonical row delta is invalid")
            if values["deleted"] != 0:
                raise CheckpointTamperError("receipt physically deleted canonical rows")
            for name, value in values.items():
                totals[table][name] += int(value)
        receipt_delta = deltas[_RECEIPT_TABLE]
        if (
            receipt_delta.get("inserted") != 1
            or receipt_delta.get("deleted") != 0
        ):
            raise CheckpointTamperError("receipt row delta is not append-only")
    for table in before:
        expected = before[table] + totals[table]["inserted"] - totals[table]["deleted"]
        if after[table] != expected:
            raise CheckpointTamperError(
                "canonical namespace delta is not explained by operation receipts"
            )


def _qdrant_point_digest_maps(value: object) -> dict[str, dict[str, str]]:
    data = _mapping(value, "Qdrant namespace evidence")
    collections = data.get("collections")
    if not isinstance(collections, Mapping):
        raise CheckpointTamperError("Qdrant collection evidence is malformed")
    result: dict[str, dict[str, str]] = {}
    for collection_name, raw in collections.items():
        collection = _mapping(raw, "Qdrant collection evidence")
        rows = collection.get("point_digests")
        if not isinstance(collection_name, str) or not isinstance(rows, list):
            raise CheckpointTamperError("Qdrant point digest evidence is malformed")
        points: dict[str, str] = {}
        for row in rows:
            if (
                not isinstance(row, (list, tuple))
                or len(row) != 2
                or not isinstance(row[0], str)
                or not isinstance(row[1], str)
                or not _SHA256.fullmatch(row[1])
                or row[0] in points
            ):
                raise CheckpointTamperError("Qdrant point digest evidence is malformed")
            points[row[0]] = row[1]
        if collection.get("points") != len(points):
            raise CheckpointTamperError("Qdrant point digest count mismatch")
        result[collection_name] = points
    return result


def _qdrant_changed_point_ids(previous: object, current: object) -> set[str]:
    before = _qdrant_point_digest_maps(previous)
    after = _qdrant_point_digest_maps(current)
    if set(before) != set(after):
        raise CheckpointTamperError("Qdrant collection set changed during resume")
    changed: set[str] = set()
    for name in before:
        for point_id in set(before[name]) | set(after[name]):
            if before[name].get(point_id) != after[name].get(point_id):
                changed.add(point_id)
    return changed


def _validated_runtime_checkpoint_proof(
    value: object,
) -> tuple[RuntimeCheckpoint, ShortTermWorkingGraph, tuple[Mapping[str, Any], ...]]:
    if not isinstance(value, RuntimeCheckpoint):
        raise CheckpointTamperError("in-flight proof is not a RuntimeCheckpoint")
    checkpoint = value
    if checkpoint.state not in _AGENT_CHECKPOINT_STATES:
        raise CheckpointTamperError("in-flight checkpoint state is invalid")
    if set(checkpoint.config_hashes) != {
        "runtime",
        "task",
        "model",
        "memory_controller",
        "grader",
        "workspace",
        "lifecycle",
    }:
        raise CheckpointTamperError("in-flight checkpoint configuration binding is incomplete")
    try:
        graph = ShortTermWorkingGraph.from_snapshot(checkpoint.graph_snapshot)
    except Exception as exc:
        raise CheckpointTamperError("in-flight working graph is invalid") from exc
    if (
        graph.task_id != checkpoint.task_id
        or graph.active_node_id != checkpoint.active_node_id
    ):
        raise CheckpointTamperError("in-flight working graph identity mismatch")
    terminal_phases = _AGENT_CHECKPOINT_STATES - {"DECOMPOSED", "RUNNING"}
    if (
        (checkpoint.state == "DECOMPOSED" and (graph.complete or graph.active_node_id))
        or (checkpoint.state == "RUNNING" and graph.complete)
        or (
            checkpoint.state in terminal_phases
            and (not graph.complete or graph.active_node_id is not None)
        )
    ):
        raise CheckpointTamperError(
            "in-flight checkpoint phase disagrees with the working graph"
        )
    state = checkpoint.memory_controller_state
    if not isinstance(state, Mapping):
        raise CheckpointTamperError("in-flight memory controller state is invalid")
    raw_ledger = state.get("ledger", ())
    if not isinstance(raw_ledger, (list, tuple)) or any(
        not isinstance(row, Mapping) for row in raw_ledger
    ):
        raise CheckpointTamperError("in-flight injection ledger is invalid")
    ledger = tuple(dict(row) for row in raw_ledger)
    if _json_value(ledger) != _json_value(checkpoint.injection_ledger):
        raise CheckpointTamperError("in-flight injection ledgers disagree")
    memory_ids = tuple(sorted(str(row.get("memory_id", "")) for row in ledger))
    byte_counts = [row.get("byte_count") for row in ledger]
    if (
        any(not memory_id for memory_id in memory_ids)
        or any(type(count) is not int or count < 0 for count in byte_counts)
        or memory_ids != tuple(checkpoint.injected_memory_ids)
        or sum(byte_counts) != checkpoint.injected_bytes
    ):
        raise CheckpointTamperError("in-flight injection accounting is invalid")
    return checkpoint, graph, ledger


def _empty_receipt_evidence(namespace: str, owner_user_id: str) -> Mapping[str, Any]:
    body = {
        "schema": "trimem/lifecycle-receipt-evidence/1.0",
        "namespace": namespace,
        "owner_user_id": owner_user_id,
        "rows": [],
    }
    return {**body, "digest": _sha256(body)}


def _empty_canonical_evidence_like(value: object) -> Mapping[str, Any]:
    counts = _canonical_counts(value)
    rows = [[table, 0] for table in counts]
    body = {"namespace": _mapping(value, "canonical evidence").get("namespace"), "row_counts": rows}
    return {**body, "digest": _sha256(body)}


def _empty_qdrant_evidence_like(value: object) -> Mapping[str, Any]:
    data = _mapping(value, "Qdrant evidence")
    points = _qdrant_point_digest_maps(data)
    rows = {
        name: {
            "exists": bool(_mapping(data["collections"][name], "Qdrant collection").get("exists")),
            "points": 0,
            "point_digests": [],
            "content_digest": _sha256([]),
        }
        for name in points
    }
    return {"collections": rows, "digest": _sha256(rows)}


class DedicatedAsyncLoop:
    """A single daemon-thread event loop shared by all async calls in a session."""

    def __init__(self, *, name: str = "trimem-production-async") -> None:
        self._ready = threading.Event()
        self._closed = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread_id: Optional[int] = None
        self._thread = threading.Thread(target=self._serve, name=name, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise ProductionDependencyError("dedicated async event loop did not start")

    def _serve(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._thread_id = threading.get_ident()
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    @property
    def thread_id(self) -> int:
        if self._thread_id is None:
            raise ProductionRuntimeError("dedicated async event loop is unavailable")
        return self._thread_id

    def call(self, awaitable: Any) -> Any:
        if self._closed or self._loop is None:
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise SessionStateError("dedicated async event loop is closed")
        if threading.get_ident() == self._thread_id:
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            raise SessionStateError("blocking bridge call from its own event-loop thread")
        if not inspect.isawaitable(awaitable):
            raise TypeError("DedicatedAsyncLoop.call requires an awaitable")
        future = asyncio.run_coroutine_threadsafe(awaitable, self._loop)
        return future.result()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        self._thread.join(timeout=10)
        if self._thread.is_alive():
            raise ProductionRuntimeError("dedicated async event loop did not stop")


def _embedder_provenance(embedder: object) -> dict[str, Any]:
    method = getattr(embedder, "provenance", None)
    if not callable(method):
        raise ProductionDependencyError("embedder must expose provenance()")
    provenance = dict(_mapping(method(), "embedder provenance"))
    model_id = provenance.get("model_id")
    revision = provenance.get("revision")
    dimensions = provenance.get("dimensions", provenance.get("dimension"))
    if not isinstance(model_id, str) or not model_id.strip():
        raise ProductionDependencyError("embedder provenance has no model_id")
    if not isinstance(revision, str) or not revision.strip():
        raise ProductionDependencyError("embedder provenance has no immutable revision")
    if type(dimensions) is not int or dimensions <= 0:
        raise ProductionDependencyError("embedder provenance has no positive dimensions")
    provenance["dimensions"] = dimensions
    provenance.pop("dimension", None)
    return _json_value(provenance)


def _normalized_embedder_lock(lock: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(lock)
    # Accept the committed model-lock's `retrieval_embedding.production` object
    # as well as the already-selected inner mapping.
    if isinstance(raw.get("retrieval_embedding"), Mapping):
        raw = dict(raw["retrieval_embedding"])
    if isinstance(raw.get("production"), Mapping):
        raw = dict(raw["production"])
    dimensions = raw.get("dimensions", raw.get("dimension"))
    result = {
        "model_id": raw.get("model_id"),
        "revision": raw.get("revision"),
        "dimensions": dimensions,
    }
    if not isinstance(result["model_id"], str) or not result["model_id"]:
        raise ValueError("embedder_lock.model_id is required")
    if not isinstance(result["revision"], str) or not result["revision"]:
        raise ValueError("embedder_lock.revision is required")
    if type(result["dimensions"]) is not int or result["dimensions"] <= 0:
        raise ValueError("embedder_lock.dimension(s) must be positive")
    return result


def _verify_embedder_lock(embedder: object, lock: Mapping[str, Any]) -> dict[str, Any]:
    provenance = _embedder_provenance(embedder)
    expected = _normalized_embedder_lock(lock)
    observed = {name: provenance.get(name) for name in expected}
    if observed != expected:
        raise ProductionDependencyError("embedder provenance does not match the frozen lock")
    return provenance


def _is_known_in_memory(value: object, *, seen: Optional[set[int]] = None) -> bool:
    if value is None:
        return False
    visited = seen if seen is not None else set()
    marker = id(value)
    if marker in visited:
        return False
    visited.add(marker)
    cls = type(value)
    qualified = "%s.%s" % (cls.__module__, cls.__name__)
    if cls.__name__.startswith("InMemory") and qualified.startswith("enterprise_memory."):
        return True
    for name in (
        "store",
        "memory_index",
        "workspace",
        "workspace_factory",
        "canonical_store",
        "delegate",
        "retriever",
        "_store",
        "_client",
    ):
        nested = getattr(value, name, None)
        if nested is not None and _is_known_in_memory(nested, seen=visited):
            return True
    return False


def _reject_in_memory(value: object, label: str) -> None:
    if _is_known_in_memory(value):
        raise ProductionDependencyError("%s cannot use an in-memory product backend" % label)


class CanonicalLifecyclePersistence:
    """Commit a lifecycle bundle, then index only canonical reloaded nodes."""

    def __init__(
        self,
        store: object,
        vector_index: QdrantVectorIndexV2,
        embedder: object,
        bridge: DedicatedAsyncLoop,
        *,
        namespace: str,
        embedder_provenance: Optional[Mapping[str, Any]] = None,
    ) -> None:
        _reject_in_memory(store, "canonical lifecycle store")
        _reject_in_memory(vector_index, "vector index")
        if getattr(store, "namespace", None) != namespace:
            raise ProductionDependencyError("canonical store namespace mismatch")
        if getattr(vector_index, "namespace", None) != namespace:
            raise ProductionDependencyError("vector index namespace mismatch")
        self.store = store
        self.vector_index = vector_index
        self.embedder = embedder
        self.bridge = bridge
        self.namespace = namespace
        self.embedder_provenance = dict(
            embedder_provenance or _embedder_provenance(embedder)
        )
        if self.embedder_provenance["dimensions"] != vector_index.dimension:
            raise ProductionDependencyError("embedder/vector dimension mismatch")
        self._receipt_digests: list[str] = []

    @property
    def persisted_bundle_count(self) -> int:
        return len(self._receipt_digests)

    def persist_bundle(self, ctx: AccessContext, bundle: LifecycleAppendBundle) -> Mapping[str, Any]:
        """Persist atomically; Qdrant is never called before PostgreSQL commits."""

        append = getattr(self.store, "append_lifecycle_bundle", None)
        if not callable(append):
            raise ProductionDependencyError("canonical store lacks append_lifecycle_bundle")
        # The await completes only after the repository transaction has committed
        # and every requested index node has been canonically reloaded.
        receipt = self.bridge.call(append(ctx, bundle))
        data = _mapping(receipt, "append receipt")
        if data.get("namespace") != self.namespace:
            raise ProductionRuntimeError("append receipt namespace mismatch")
        index_nodes = tuple(getattr(receipt, "index_nodes", data.get("index_nodes", ())))
        index_intents = tuple(
            getattr(receipt, "index_intents", data.get("index_intents", ()))
        )
        if len(index_nodes) != len(index_intents):
            raise ProductionRuntimeError(
                "every canonical index node requires one durable PostgreSQL outbox intent"
            )
        indexed: list[dict[str, str]] = []
        for node, intent in zip(index_nodes, index_intents):
            intent_status = self._intent_field(intent, "status")
            self._validate_intent_node(
                ctx, intent, node, allowed_statuses={"PENDING", "INDEXED"}
            )
            if self._intent_field(intent, "operation") != "UPSERT":
                raise ProductionRuntimeError("index receipt contains a non-UPSERT intent")
            try:
                # Reapply even an INDEXED receipt.  Qdrant upsert is
                # idempotent and this repairs external point loss/tampering
                # before a recovered task can seal a new checkpoint.
                self._index_canonical_node(node)
            except BaseException as exc:
                if intent_status == "PENDING":
                    self._record_index_failure(ctx, intent, exc, prefix="qdrant")
                raise
            if intent_status == "PENDING":
                marked = self._mark_indexed(ctx, intent)
                marked_data = _mapping(marked, "indexed outbox intent")
                if marked_data.get("status") != "INDEXED":
                    raise ProductionRuntimeError("outbox intent was not marked INDEXED")
            indexed.append(
                {
                    "intent_id": str(self._intent_field(intent, "intent_id", "id")),
                    "node_id": str(node.node_id),
                    "content_hash": str(node.content_hash),
                }
            )
        delete_nodes = tuple(
            getattr(receipt, "delete_nodes", data.get("delete_nodes", ()))
        )
        delete_intents = tuple(
            getattr(receipt, "delete_intents", data.get("delete_intents", ()))
        )
        if len(delete_nodes) != len(delete_intents):
            raise ProductionRuntimeError(
                "every archived vector node requires one durable DELETE intent"
            )
        deleted: list[dict[str, str]] = []
        for node, intent in zip(delete_nodes, delete_intents):
            intent_status = self._intent_field(intent, "status")
            self._validate_intent_node(
                ctx, intent, node, allowed_statuses={"PENDING", "INDEXED"}
            )
            if self._intent_field(intent, "operation") != "DELETE":
                raise ProductionRuntimeError("delete receipt contains a non-DELETE intent")
            try:
                # DELETE is likewise idempotent; reapply a completed receipt
                # so a resurrected external point cannot survive recovery.
                self._delete_canonical_node(node, intent)
            except BaseException as exc:
                if intent_status == "PENDING":
                    self._record_index_failure(ctx, intent, exc, prefix="qdrant_delete")
                raise
            if intent_status == "PENDING":
                marked = self._mark_indexed(ctx, intent)
                marked_data = _mapping(marked, "completed delete outbox intent")
                if marked_data.get("status") != "INDEXED":
                    raise ProductionRuntimeError("delete outbox intent was not completed")
            deleted.append(
                {
                    "intent_id": str(self._intent_field(intent, "intent_id", "id")),
                    "node_id": str(node.node_id),
                    "content_hash": str(node.content_hash),
                }
            )

        digest = _sha256(
            {
                "namespace": self.namespace,
                "graph_hashes": _json_value(data.get("graph_hashes", ())),
                "node_hashes": _json_value(data.get("node_hashes", ())),
                "strength_hashes": _json_value(data.get("strength_hashes", ())),
                "canonical_row_deltas": _json_value(
                    data.get("canonical_row_deltas", {})
                ),
                "indexed": indexed,
                "deleted": deleted,
            }
        )
        self._receipt_digests.append(digest)
        return {
            "namespace": self.namespace,
            "receipt_digest": digest,
            "indexed": tuple(indexed),
            "deleted": tuple(deleted),
            "canonical_row_deltas": _json_value(
                data.get("canonical_row_deltas", {})
            ),
        }

    @staticmethod
    def _intent_field(intent: object, name: str, fallback: Optional[str] = None) -> Any:
        value = getattr(intent, name, None)
        if value is None:
            data = _mapping(intent, "vector index outbox intent")
            value = data.get(name)
            if value is None and fallback is not None:
                value = data.get(fallback)
        return value

    def _validate_intent_node(
        self,
        ctx: AccessContext,
        intent: object,
        node: object,
        *,
        allowed_statuses: set[str] | frozenset[str] = frozenset({"PENDING"}),
    ) -> None:
        expected = {
            "org_id": str(ctx.org_id),
            "namespace": self.namespace,
            "graph_id": str(getattr(node, "graph_id", "")),
            "graph_kind": getattr(node, "graph_kind", None),
            "owner_user_id": getattr(node, "owner_user_id", None),
            "node_id": str(getattr(node, "node_id", "")),
            "canonical_content_hash": str(getattr(node, "content_hash", "")),
        }
        for name, wanted in expected.items():
            observed = self._intent_field(intent, name)
            if name == "graph_kind" and isinstance(observed, str):
                try:
                    observed = GraphKind(observed)
                except ValueError as exc:
                    raise ProductionRuntimeError("outbox intent graph kind is invalid") from exc
            if observed != wanted:
                raise ProductionRuntimeError(
                    "outbox intent does not match its canonical node: %s" % name
                )
        if self._intent_field(intent, "status") not in allowed_statuses:
            raise ProductionRuntimeError(
                "outbox intent does not match its canonical node: status"
            )
        intent_id = self._intent_field(intent, "intent_id", "id")
        if not isinstance(intent_id, str) or not intent_id:
            raise ProductionRuntimeError("outbox intent identifier is missing")

    @staticmethod
    def _index_error_code(prefix: str, exc: BaseException) -> str:
        return "%s:%s" % (prefix, type(exc).__name__)

    def _record_index_failure(
        self, ctx: AccessContext, intent: object, exc: BaseException, *, prefix: str
    ) -> None:
        mark = getattr(self.store, "mark_index_outbox_failed", None)
        if not callable(mark):
            raise ProductionDependencyError(
                "canonical store lacks durable outbox failure recording"
            ) from exc
        try:
            self.bridge.call(
                mark(
                    ctx,
                    intent_id=str(self._intent_field(intent, "intent_id", "id")),
                    canonical_content_hash=str(
                        self._intent_field(intent, "canonical_content_hash")
                    ),
                    error_code=self._index_error_code(prefix, exc),
                )
            )
        except BaseException as update_exc:
            raise ProductionRuntimeError(
                "Qdrant failed and PostgreSQL outbox failure accounting also failed"
            ) from update_exc

    def _mark_indexed(self, ctx: AccessContext, intent: object) -> object:
        mark = getattr(self.store, "mark_index_outbox_indexed", None)
        if not callable(mark):
            raise ProductionDependencyError(
                "canonical store lacks durable outbox completion"
            )
        return self.bridge.call(
            mark(
                ctx,
                intent_id=str(self._intent_field(intent, "intent_id", "id")),
                canonical_content_hash=str(
                    self._intent_field(intent, "canonical_content_hash")
                ),
            )
        )

    def reconcile_index_outbox(
        self, ctx: AccessContext, *, limit: int = 100
    ) -> tuple[Mapping[str, str], ...]:
        """Replay committed PENDING intents after canonical reload/hash checks."""

        list_pending = getattr(self.store, "list_index_outbox", None)
        get_node = getattr(self.store, "get_node", None)
        if not callable(list_pending) or not callable(get_node):
            raise ProductionDependencyError("canonical store lacks outbox reconciliation APIs")
        intents = tuple(self.bridge.call(list_pending(ctx, status="PENDING", limit=limit)))
        reconciled: list[Mapping[str, str]] = []
        for intent in intents:
            if (
                self._intent_field(intent, "namespace") != self.namespace
                or str(self._intent_field(intent, "org_id")) != str(ctx.org_id)
            ):
                raise ProductionRuntimeError("outbox reconciliation scope mismatch")
            try:
                node = self.bridge.call(
                    get_node(ctx, str(self._intent_field(intent, "node_id")))
                )
                self._validate_intent_node(ctx, intent, node)
                operation = self._intent_field(intent, "operation")
                if operation == "UPSERT":
                    self._index_canonical_node(node)
                elif operation == "DELETE":
                    self._delete_canonical_node(node, intent)
                else:
                    raise ProductionRuntimeError("outbox intent operation is invalid")
            except BaseException as exc:
                self._record_index_failure(ctx, intent, exc, prefix="reconcile")
                raise
            marked = self._mark_indexed(ctx, intent)
            marked_data = _mapping(marked, "indexed outbox intent")
            if marked_data.get("status") != "INDEXED":
                raise ProductionRuntimeError("outbox reconciliation did not close intent")
            reconciled.append(
                {
                    "intent_id": str(self._intent_field(intent, "intent_id", "id")),
                    "node_id": str(self._intent_field(intent, "node_id")),
                    "content_hash": str(
                        self._intent_field(intent, "canonical_content_hash")
                    ),
                }
            )
        return tuple(reconciled)

    def persist_access_events(
        self,
        ctx: AccessContext,
        events: Sequence[object],
        *,
        operation_id: str,
        operation_scope: Mapping[str, Any],
    ) -> tuple[object, ...]:
        append = getattr(self.store, "append_access_batch", None)
        if not callable(append):
            raise ProductionDependencyError("canonical store lacks append_access_batch")
        return tuple(self.bridge.call(append(
            ctx,
            tuple(events),
            operation_id=operation_id,
            operation_scope=operation_scope,
        )))

    def load_policy_feature_rows(
        self, ctx: AccessContext, *, limit: int
    ) -> Mapping[str, Any]:
        load = getattr(self.store, "load_policy_feature_rows", None)
        if not callable(load):
            raise ProductionDependencyError(
                "canonical store lacks policy feature history"
            )
        value = self.bridge.call(load(ctx, limit=limit))
        return dict(_mapping(value, "canonical policy feature rows"))

    def lifecycle_receipt_evidence(self, ctx: AccessContext) -> Mapping[str, Any]:
        load = getattr(self.store, "lifecycle_receipt_evidence", None)
        if not callable(load):
            raise ProductionDependencyError(
                "canonical store lacks lifecycle receipt evidence"
            )
        value = dict(
            _mapping(
                self.bridge.call(load(ctx)),
                "canonical lifecycle receipt evidence",
            )
        )
        digest = value.get("digest")
        body = {key: item for key, item in value.items() if key != "digest"}
        if (
            body.get("schema") != "trimem/lifecycle-receipt-evidence/1.0"
            or body.get("namespace") != self.namespace
            or body.get("owner_user_id") != ctx.user_id
            or not isinstance(body.get("rows"), list)
            or _sha256(body) != digest
        ):
            raise ProductionRuntimeError(
                "canonical lifecycle receipt evidence failed its seal"
            )
        return {**body, "digest": digest}

    def replay_receipt_index_effects(
        self,
        ctx: AccessContext,
        receipts: Sequence[Mapping[str, Any]],
    ) -> frozenset[str]:
        """Repair only Qdrant points named by sealed canonical receipts.

        The task-local checkpoint may have been written after PostgreSQL and
        Qdrant committed but before the arm-boundary checkpoint.  Conversely,
        PostgreSQL may have committed before Qdrant.  Reapplying the receipt's
        canonical UPSERT/DELETE effects is idempotent in both cases and also
        repairs loss or mutation of a touched external point.  No unrelated
        point identifier is accepted by the caller's evidence comparison.
        """

        get_node = getattr(self.store, "get_node", None)
        get_intent = getattr(self.store, "get_index_outbox_intent", None)
        if not callable(get_node) or not callable(get_intent):
            raise ProductionDependencyError(
                "canonical store lacks receipt index recovery APIs"
            )
        touched: set[str] = set()
        for raw in receipts:
            row = _mapping(raw, "lifecycle receipt recovery row")
            index_nodes = row.get("index_node_ids")
            index_intents = row.get("index_intent_ids")
            delete_nodes = row.get("delete_node_ids")
            delete_intents = row.get("delete_intent_ids")
            if (
                not isinstance(index_nodes, list)
                or not isinstance(index_intents, list)
                or not isinstance(delete_nodes, list)
                or not isinstance(delete_intents, list)
                or len(index_nodes) != len(index_intents)
                or len(delete_nodes) != len(delete_intents)
            ):
                raise CheckpointTamperError(
                    "receipt index recovery identifiers are malformed"
                )
            for node_id, intent_id in zip(index_nodes, index_intents):
                node = self.bridge.call(get_node(ctx, str(node_id)))
                intent = self.bridge.call(
                    get_intent(ctx, str(intent_id))
                )
                self._validate_intent_node(
                    ctx, intent, node, allowed_statuses={"PENDING", "INDEXED"}
                )
                if self._intent_field(intent, "operation") != "UPSERT":
                    raise CheckpointTamperError(
                        "receipt index intent is not an UPSERT"
                    )
                self._index_canonical_node(node)
                touched.add(str(node_id))
            for node_id, intent_id in zip(delete_nodes, delete_intents):
                node = self.bridge.call(get_node(ctx, str(node_id)))
                intent = self.bridge.call(
                    get_intent(ctx, str(intent_id))
                )
                self._validate_intent_node(
                    ctx, intent, node, allowed_statuses={"PENDING", "INDEXED"}
                )
                if self._intent_field(intent, "operation") != "DELETE":
                    raise CheckpointTamperError(
                        "receipt delete intent is not a DELETE"
                    )
                self._delete_canonical_node(node, intent)
                touched.add(str(node_id))
        return frozenset(touched)

    def _index_canonical_node(self, node: object) -> None:
        if getattr(node, "namespace", None) != self.namespace:
            raise ProductionRuntimeError("canonical index node namespace mismatch")
        verify = getattr(node, "verify_hash", None)
        if not callable(verify) or not verify():
            raise ProductionRuntimeError("canonical index node hash verification failed")
        kind = getattr(node, "graph_kind", None)
        if kind == GraphKind.SHORT_TERM_WORKING:
            raise ProductionRuntimeError("working graph nodes cannot enter the durable vector index")
        if getattr(node, "lifecycle_state", None) != LifecycleState.ACTIVE:
            raise ProductionRuntimeError("archived node cannot enter the active vector index")
        payload = getattr(node, "canonical_payload", None)
        if not isinstance(payload, Mapping):
            raise ProductionRuntimeError("canonical index node payload is unavailable")
        retrieval_text = payload.get("retrieval_text")
        if not isinstance(retrieval_text, str) or not retrieval_text.strip():
            raise ProductionRuntimeError("canonical index node has no retrieval_text")
        vector = tuple(float(value) for value in self.embedder.embed(retrieval_text))
        if len(vector) != self.vector_index.dimension:
            raise ProductionRuntimeError("embedder returned an unlocked vector dimension")
        scope = "shared" if kind == GraphKind.ORGANISATION_SEMANTIC else "private"
        metadata = VectorIndexMetadata(
            graph_id=str(node.graph_id),
            node_id=str(node.node_id),
            org_id=str(node.org_id),
            namespace=self.namespace,
            memory_kind=kind,
            canonical_content_hash=str(node.content_hash),
            owner_user_id=getattr(node, "owner_user_id", None),
            repository_id=getattr(node, "repository_id", None),
            collection_scope=scope,
            embedding_model_id=str(self.embedder_provenance["model_id"]),
            embedding_revision=str(self.embedder_provenance["revision"]),
            embedding_dimension=int(self.embedder_provenance["dimensions"]),
        )
        self.vector_index.upsert(metadata, vector)

    def _delete_canonical_node(self, node: object, intent: object) -> None:
        if getattr(node, "namespace", None) != self.namespace:
            raise ProductionRuntimeError("canonical delete node namespace mismatch")
        verify = getattr(node, "verify_hash", None)
        if not callable(verify) or not verify():
            raise ProductionRuntimeError("canonical delete node hash verification failed")
        if getattr(node, "lifecycle_state", None) == LifecycleState.ACTIVE:
            raise ProductionRuntimeError("active node cannot satisfy a vector DELETE intent")
        prior_hash = self._intent_field(intent, "prior_content_hash")
        if (
            not isinstance(prior_hash, str)
            or getattr(node, "archived_from_content_hash", None) != prior_hash
        ):
            raise ProductionRuntimeError("vector DELETE archive provenance mismatch")
        kind = getattr(node, "graph_kind", None)
        scope = "shared" if kind == GraphKind.ORGANISATION_SEMANTIC else "private"
        metadata = VectorIndexMetadata(
            graph_id=str(node.graph_id),
            node_id=str(node.node_id),
            org_id=str(node.org_id),
            namespace=self.namespace,
            memory_kind=kind,
            canonical_content_hash=prior_hash,
            owner_user_id=getattr(node, "owner_user_id", None),
            repository_id=getattr(node, "repository_id", None),
            collection_scope=scope,
            embedding_model_id=str(self.embedder_provenance["model_id"]),
            embedding_revision=str(self.embedder_provenance["revision"]),
            embedding_dimension=int(self.embedder_provenance["dimensions"]),
        )
        self.vector_index.delete(metadata)

    def checkpoint_state(self) -> Mapping[str, Any]:
        return {
            "schema": "trimem/canonical-lifecycle-persistence/1.0",
            "namespace": self.namespace,
            "persisted_bundle_count": len(self._receipt_digests),
            "receipt_digests": list(self._receipt_digests),
        }

    def restore_state(self, value: Mapping[str, Any]) -> None:
        if value.get("schema") != "trimem/canonical-lifecycle-persistence/1.0":
            raise CheckpointTamperError("lifecycle persistence checkpoint schema mismatch")
        if value.get("namespace") != self.namespace:
            raise CheckpointTamperError("lifecycle persistence namespace mismatch")
        digests = value.get("receipt_digests")
        if not isinstance(digests, list) or any(
            not isinstance(item, str) or not _SHA256.fullmatch(item) for item in digests
        ):
            raise CheckpointTamperError("invalid lifecycle receipt digest ledger")
        if value.get("persisted_bundle_count") != len(digests):
            raise CheckpointTamperError("lifecycle persisted bundle count mismatch")
        self._receipt_digests = list(digests)


def _qdrant_collection_evidence(client: object, name: str) -> dict[str, Any]:
    exists_method = getattr(client, "collection_exists", None)
    if not callable(exists_method):
        raise FreshnessViolation("Qdrant client cannot prove collection existence")
    exists = bool(exists_method(collection_name=name))
    if not exists:
        return {
            "exists": False,
            "points": 0,
            "point_digests": [],
            "content_digest": _sha256([]),
        }

    exact_count: Optional[int] = None
    count_method = getattr(client, "count", None)
    if callable(count_method):
        response = count_method(collection_name=name, exact=True)
        if isinstance(response, Mapping):
            count = response.get("count")
        else:
            count = getattr(response, "count", None)
        if type(count) is not int or count < 0:
            raise FreshnessViolation("Qdrant returned an invalid exact point count")
        exact_count = count

    def point_row(point: object) -> dict[str, Any]:
        if isinstance(point, Mapping):
            point_id = point.get("id")
            payload = point.get("payload")
            vector = point.get("vector")
        else:
            point_id = getattr(point, "id", None)
            payload = getattr(point, "payload", None)
            vector = getattr(point, "vector", None)
        if not isinstance(point_id, (str, int)) or isinstance(point_id, bool):
            raise FreshnessViolation("Qdrant point has an invalid identifier")
        if not isinstance(payload, Mapping):
            raise FreshnessViolation("Qdrant point has no reference payload")
        if not isinstance(vector, (list, tuple)) or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            for item in vector
        ):
            raise FreshnessViolation("Qdrant point has an invalid vector")
        return {
            "id": str(point_id),
            "payload": _json_value(payload),
            "vector": _json_value(vector),
        }

    rows: list[dict[str, Any]] = []
    scroll = getattr(client, "scroll", None)
    if callable(scroll):
        offset: object = None
        seen_offsets: set[str] = set()
        while True:
            response = scroll(
                collection_name=name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            if isinstance(response, (tuple, list)) and len(response) == 2:
                points, next_offset = response
            else:
                points = getattr(response, "points", None)
                next_offset = getattr(response, "next_page_offset", None)
            if not isinstance(points, (tuple, list)):
                raise FreshnessViolation("Qdrant scroll returned malformed points")
            rows.extend(point_row(point) for point in points)
            if next_offset is None:
                break
            offset_key = repr(next_offset)
            if offset_key in seen_offsets:
                raise FreshnessViolation("Qdrant scroll pagination repeated an offset")
            seen_offsets.add(offset_key)
            offset = next_offset

    else:
        # Credential-free Qdrant fakes use this deliberately transparent shape.
        collections = getattr(client, "collections", None)
        collection = collections.get(name) if isinstance(collections, Mapping) else None
        points = collection.get("points") if isinstance(collection, Mapping) else None
        if not isinstance(points, Mapping):
            raise FreshnessViolation("existing Qdrant collection content cannot be proven")
        rows = [point_row(point) for point in points.values()]

    rows.sort(key=lambda row: row["id"])
    if len({row["id"] for row in rows}) != len(rows):
        raise FreshnessViolation("Qdrant collection contains duplicate point identifiers")
    if exact_count is not None and exact_count != len(rows):
        raise FreshnessViolation("Qdrant count/scroll evidence mismatch")
    return {
        "exists": True,
        "points": len(rows),
        "point_digests": [
            [row["id"], _sha256(row)] for row in rows
        ],
        "content_digest": _sha256(rows),
    }


class BenchmarkArmSession:
    """Synchronous, ordered lifecycle for one physically isolated arm stream."""

    canonical_backend = "postgresql"
    vector_backend = "qdrant"

    def __init__(
        self,
        *,
        experiment_id: str,
        split: str,
        arm_id: str,
        task_order: Sequence[object],
        store: object,
        vector_index: QdrantVectorIndexV2,
        qdrant_client: object,
        embedder: object,
        embedder_provenance: Mapping[str, Any],
        bridge: DedicatedAsyncLoop,
        persistence: CanonicalLifecyclePersistence,
        lifecycle: object,
        controller_factory: Optional[Callable[..., object]],
        config_hash: str,
        evaluation: bool,
        run_nonce: Optional[str] = None,
        engine: Optional[object] = None,
    ) -> None:
        self.arm_id = _required_component(arm_id, "arm_id")
        self.namespace = benchmark_namespace(experiment_id, split, arm_id)
        if getattr(store, "namespace", None) != self.namespace:
            raise ProductionDependencyError("PostgreSQL store namespace mismatch")
        if getattr(vector_index, "namespace", None) != self.namespace:
            raise ProductionDependencyError("Qdrant index namespace mismatch")
        _reject_in_memory(store, "canonical store")
        _reject_in_memory(lifecycle, "lifecycle")
        self.experiment_id = experiment_id
        self.split = split
        self.evaluation = bool(evaluation)
        self._tasks, self._task_ids, self._ctx = _normalize_task_order(task_order)
        self.task_order_hash = _sha256(
            [_task_order_payload(task) for task in self._tasks]
        )
        if not isinstance(config_hash, str) or not _SHA256.fullmatch(config_hash):
            raise ValueError("config_hash must be a canonical sha256 digest")
        if not config_hash.startswith("sha256:"):
            config_hash = "sha256:" + config_hash
        self.config_hash = config_hash
        self.embedder_provenance = MappingProxyType(dict(embedder_provenance))
        self.lifecycle = lifecycle
        self.persistence = persistence
        self._controller_factory = controller_factory
        self._store = store
        self._vector_index = vector_index
        self._qdrant_client = qdrant_client
        self._embedder = embedder
        self._bridge = bridge
        self._engine = engine
        # The canonical namespace table stores this value as PostgreSQL UUID.
        self._run_nonce = run_nonce or str(uuid.uuid4())
        try:
            canonical_run_nonce = str(uuid.UUID(self._run_nonce))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError("run_nonce must be a canonical UUID") from exc
        if self._run_nonce != canonical_run_nonce:
            raise ValueError("run_nonce must be a canonical UUID")
        self._state = "CREATED"
        self._next_sequence_index = 0
        self._active_sequence_index: Optional[int] = None
        self._active_task: Optional[object] = None
        self._active_controller: Optional[object] = None
        self._completed_task_digests: list[str] = []
        self._final_policy_checkpoint: Optional[Mapping[str, Any]] = None
        self._latest_checkpoint_envelope: Optional[Mapping[str, Any]] = None
        self._inflight_external_state_proof: Optional[Mapping[str, Any]] = None
        self._claim_established = False
        self._closed = False

    @property
    def run_nonce(self) -> str:
        return self._run_nonce

    @property
    def next_sequence_index(self) -> int:
        return self._next_sequence_index

    @property
    def task_cursor(self) -> int:
        """Number of benchmark tasks durably completed by this stream."""

        return min(self._next_sequence_index, len(self._tasks))

    @property
    def development_finalized(self) -> bool:
        return self._state == "DEVELOPMENT_FINALIZED"

    @property
    def final_policy_checkpoint(self) -> Optional[Mapping[str, Any]]:
        if self._final_policy_checkpoint is None:
            return None
        return _json_value(self._final_policy_checkpoint)

    @property
    def latest_checkpoint_envelope(self) -> Optional[Mapping[str, Any]]:
        if self._latest_checkpoint_envelope is None:
            return None
        return _json_value(self._latest_checkpoint_envelope)

    def run_coroutine(self, awaitable):
        """Run provider async work on the session-owned long-lived event loop."""
        if self._closed:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise SessionStateError("session is closed")
        return self._bridge.call(awaitable)

    @property
    def coroutine_runner(self):
        """Callable passed to AsyncProviderModelGateway without loop-per-call churn."""
        return self.run_coroutine

    def _claim(self, *, resume: bool, next_sequence_index: int = 0) -> object:
        kwargs = {
            "experiment_id": self.experiment_id,
            "split": self.split,
            "arm_id": self.arm_id,
            "task_order_hash": self.task_order_hash,
            "config_hash": self.config_hash,
            "run_nonce": self._run_nonce,
        }
        if resume:
            method = getattr(self._store, "resume_namespace", None)
            if not callable(method):
                raise SessionStateError(
                    "canonical store cannot resume an existing namespace claim"
                )
            kwargs["expected_next_sequence_index"] = next_sequence_index
        else:
            method = getattr(self._store, "claim_namespace", None)
            if not callable(method):
                raise ProductionDependencyError("canonical store lacks claim_namespace")
        claim = self._bridge.call(method(self._ctx, **kwargs))
        data = _mapping(claim, "namespace claim")
        expected = {
            "namespace": self.namespace,
            "experiment_id": self.experiment_id,
            "split": self.split,
            "arm_id": self.arm_id,
            "task_order_hash": self.task_order_hash,
            "config_hash": self.config_hash,
            "run_nonce": self._run_nonce,
        }
        if any(data.get(name) != value for name, value in expected.items()):
            raise ProductionRuntimeError("canonical namespace claim identity mismatch")
        if int(data.get("next_sequence_index", -1)) != next_sequence_index:
            raise ProductionRuntimeError("canonical namespace sequence mismatch")
        if data.get("claim_status") != "ACTIVE":
            raise ProductionRuntimeError("canonical namespace claim is not active")
        self._claim_established = True
        return claim

    def _canonical_evidence(self) -> Mapping[str, Any]:
        method = getattr(self._store, "namespace_evidence", None)
        if not callable(method):
            raise ProductionDependencyError("canonical store lacks namespace_evidence")
        evidence = self._bridge.call(method(self._ctx))
        data = dict(_mapping(evidence, "namespace evidence"))
        if data.get("namespace") != self.namespace:
            raise ProductionRuntimeError("canonical namespace evidence mismatch")
        row_counts = data.get("row_counts")
        if not isinstance(row_counts, (tuple, list)):
            raise ProductionRuntimeError("canonical namespace evidence has no row counts")
        normalized = []
        for item in row_counts:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ProductionRuntimeError("canonical namespace row count is malformed")
            table, count = item
            if not isinstance(table, str) or type(count) is not int or count < 0:
                raise ProductionRuntimeError("canonical namespace row count is invalid")
            normalized.append((table, count))
        calculated = _sha256({"namespace": self.namespace, "row_counts": normalized})
        if data.get("digest") != calculated:
            raise ProductionRuntimeError("canonical namespace evidence digest mismatch")
        return {"namespace": self.namespace, "row_counts": normalized, "digest": calculated}

    def _qdrant_evidence(self) -> Mapping[str, Any]:
        rows = {
            self._vector_index.private_collection: _qdrant_collection_evidence(
                self._qdrant_client, self._vector_index.private_collection
            ),
            self._vector_index.shared_collection: _qdrant_collection_evidence(
                self._qdrant_client, self._vector_index.shared_collection
            ),
        }
        return {"collections": rows, "digest": _sha256(rows)}

    def assert_fresh(self) -> Mapping[str, Any]:
        if self._state != "CREATED":
            raise SessionStateError("freshness can be asserted only once on a new session")
        try:
            claim = self._claim(resume=False, next_sequence_index=0)
            canonical = self._canonical_evidence()
            if any(count != 0 for _, count in canonical["row_counts"]):
                raise FreshnessViolation("canonical namespace is not empty")
            qdrant = self._qdrant_evidence()
            if any(row["points"] != 0 for row in qdrant["collections"].values()):
                raise FreshnessViolation("Qdrant arm collections are not empty")
            self._vector_index.ensure_ready()
            self._state = "READY"
            result = {
                "namespace": self.namespace,
                "claim": _json_value(_mapping(claim, "namespace claim")),
                "canonical": canonical,
                "qdrant_before_initialization": qdrant,
            }
            return {**result, "digest": _sha256(result)}
        except BaseException:
            self._state = "BROKEN"
            raise

    def before_task(self, task: object, sequence_index: int) -> None:
        if self._state != "READY":
            raise SessionStateError("session is not ready for a task")
        if type(sequence_index) is not int or sequence_index != self._next_sequence_index:
            raise SessionStateError("task sequence index is not the next frozen position")
        if sequence_index >= len(self._tasks):
            raise SessionStateError("task sequence is exhausted")
        if _task_id(task) != self._task_ids[sequence_index]:
            raise SessionStateError("task does not match the frozen task order")
        if _task_context(task) != self._ctx:
            raise SessionStateError("task access context changed")
        hook = getattr(self.lifecycle, "before_task", None)
        if callable(hook):
            result = hook(task=task, sequence_index=sequence_index)
            if inspect.isawaitable(result):
                self._bridge.call(result)
        self._active_task = task
        self._active_sequence_index = sequence_index
        self._active_controller = None
        self._state = "TASK_ACTIVE"

    def prepared_task_checkpoint(self, task: object) -> Mapping[str, Any]:
        """Seal lifecycle preparation before the first external task call.

        Production lifecycle adapters capture the task's event timestamp and,
        for M2, the immutable feature-history snapshot in ``before_task``.  The
        agent's first checkpoint is necessarily later than decomposition, so
        the driver must durably write this envelope immediately after
        ``before_task`` and before model/controller execution.
        """

        if (
            self._state != "TASK_ACTIVE"
            or self._active_task is None
            or self._active_sequence_index is None
            or _task_id(task) != _task_id(self._active_task)
        ):
            raise SessionStateError("prepared-task checkpoint requires the active task")
        lifecycle_state: Mapping[str, Any] = {}
        hook = getattr(self.lifecycle, "checkpoint_state", None)
        if callable(hook):
            lifecycle_state = _mapping(hook(), "prepared lifecycle state")
        payload = _json_value({
            "schema": _PREPARED_TASK_SCHEMA,
            "namespace": self.namespace,
            "experiment_id": self.experiment_id,
            "split": self.split,
            "arm_id": self.arm_id,
            "task_order_hash": self.task_order_hash,
            "config_hash": self.config_hash,
            "run_nonce": self._run_nonce,
            "sequence_index": self._active_sequence_index,
            "task_id": _task_id(task),
            "canonical_evidence": self._canonical_evidence(),
            "qdrant_evidence": self._qdrant_evidence(),
            "lifecycle_receipt_evidence": self.persistence.lifecycle_receipt_evidence(
                self._ctx
            ),
            "lifecycle_state": lifecycle_state,
        })
        return {"payload": payload, "digest": _sha256(payload)}

    def controller_for(self, task: object):
        if self._state != "TASK_ACTIVE" or self._active_task is None:
            raise SessionStateError("no task is active")
        if _task_id(task) != _task_id(self._active_task):
            raise SessionStateError("controller requested for a different task")
        if self._active_controller is not None:
            return self._active_controller
        task_event_time: Optional[str] = None
        if self.arm_id != "M0":
            prepared_time = getattr(self.lifecycle, "prepared_event_time", None)
            if not callable(prepared_time):
                raise ProductionDependencyError(
                    "%s lifecycle cannot expose its prepared task time" % self.arm_id
                )
            task_event_time = prepared_time(task)
            if not isinstance(task_event_time, str) or not task_event_time:
                raise ProductionDependencyError("prepared task time is invalid")
        if self.arm_id == "M0" and self._controller_factory is None:
            controller = NoMemoryController()
        elif self.arm_id == "M2" and self._controller_factory is None:
            resolver = getattr(self.lifecycle, "identity_resolver", None)
            if not callable(resolver):
                raise ProductionDependencyError(
                    "M2 lifecycle has no canonical task identity resolver"
                )
            identity = _mapping(resolver(task), "canonical task identity")
            repository_id = identity.get("repository_id")
            if not isinstance(repository_id, str) or not repository_id:
                raise ProductionDependencyError(
                    "canonical task identity has no repository UUID"
                )
            async_store = AsyncPostgresQdrantRetrievalStore(
                self._store,
                self._vector_index,
                self._embedder,
                excluded_source_task_id=_task_id(task),
                repository_id=repository_id,
                repository_alias=str(getattr(task, "repository", "")),
            )
            sync_store = SyncPostgresQdrantRetrievalStore(async_store, self._bridge)
            auditor = PostgresInjectionAuditor(
                self.persistence,
                ctx=_task_context(task),
                namespace=self.namespace,
                task_id=_task_id(task),
                clock=lambda: str(task_event_time),
            )
            raw_retrieval = getattr(self.lifecycle, "retrieval_config", None)
            if not isinstance(raw_retrieval, Mapping):
                raise ProductionDependencyError(
                    "M2 lifecycle lacks the frozen retrieval contract"
                )
            retriever = TriMemoryRetriever(
                sync_store,
                RetrievalConfig(
                    min_confidence=float(raw_retrieval["min_confidence"]),
                    min_margin=float(raw_retrieval["min_margin"]),
                    episode_complete_threshold=float(
                        raw_retrieval["episode_complete_threshold"]
                    ),
                    max_episodic_per_node=int(
                        raw_retrieval["max_episodic_per_active_node"]
                    ),
                    max_semantic_per_node=int(
                        raw_retrieval["max_semantic_per_active_node"]
                    ),
                    max_task_injections=int(raw_retrieval["max_task_injections"]),
                    context_budget_bytes=int(raw_retrieval["context_budget_bytes"]),
                    embedding_dimensions=int(raw_retrieval["embedding_dimensions"]),
                    embedding_weight=float(raw_retrieval["embedding_weight"]),
                    lexical_weight=float(raw_retrieval["lexical_weight"]),
                    ppr_damping=float(raw_retrieval["ppr_damping"]),
                    ppr_iterations=int(raw_retrieval["ppr_iterations"]),
                ),
                embedder=self._embedder,
                injection_auditor=auditor,
            )
            controller = ActiveNodeTriMemController(
                retriever, task_id=_task_id(task)
            )
        else:
            if not callable(self._controller_factory):
                raise ProductionDependencyError(
                    "%s requires an explicit production controller_factory" % self.arm_id
                )
            controller = self._controller_factory(
                arm_id=self.arm_id,
                task=task,
                namespace=self.namespace,
                canonical_store=self._store,
                vector_index=self._vector_index,
                embedder=self._embedder,
                persistence=self.persistence,
                excluded_source_task_id=_task_id(task),
                task_event_time=task_event_time,
                identity_resolver=getattr(self.lifecycle, "identity_resolver", None),
                lifecycle=self.lifecycle,
            )
        _reject_in_memory(controller, "memory controller")
        for method in ("recall", "context_for", "checkpoint_state", "restore"):
            if not callable(getattr(controller, method, None)):
                raise ProductionDependencyError("memory controller lacks %s" % method)
        content_hash = getattr(controller, "content_hash", None)
        if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            raise ProductionDependencyError("memory controller has no canonical content hash")
        self._active_controller = controller
        return controller

    def _checkpoint_envelope(
        self,
        *,
        next_sequence_index: int,
        completed_task_digests: Sequence[str],
        canonical_evidence: Optional[Mapping[str, Any]] = None,
        qdrant_evidence: Optional[Mapping[str, Any]] = None,
        stream_state: str = "TASK_STREAM",
        task_cursor: Optional[int] = None,
        final_policy_checkpoint: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        """Build the exact recovery envelope persisted with a cursor advance."""

        canonical = (
            dict(canonical_evidence)
            if canonical_evidence is not None
            else self._canonical_evidence()
        )
        qdrant = (
            dict(qdrant_evidence)
            if qdrant_evidence is not None
            else self._qdrant_evidence()
        )
        receipt_evidence = self.persistence.lifecycle_receipt_evidence(self._ctx)
        lifecycle_state = self.persistence.checkpoint_state()
        hook = getattr(self.lifecycle, "checkpoint_state", None)
        if callable(hook) and self.lifecycle is not self.persistence:
            lifecycle_state = {
                "persistence": lifecycle_state,
                "lifecycle": _json_value(hook()),
            }
        payload = {
            "schema": _CHECKPOINT_SCHEMA,
            "namespace": self.namespace,
            "experiment_id": self.experiment_id,
            "split": self.split,
            "arm_id": self.arm_id,
            "task_order_hash": self.task_order_hash,
            "config_hash": self.config_hash,
            "run_nonce": self._run_nonce,
            "next_sequence_index": next_sequence_index,
            "task_cursor": next_sequence_index if task_cursor is None else task_cursor,
            "stream_state": stream_state,
            "canonical_evidence": canonical,
            "qdrant_evidence": qdrant,
            "lifecycle_receipt_evidence": receipt_evidence,
            "completed_task_digests": list(completed_task_digests),
            "lifecycle_state": _json_value(lifecycle_state),
        }
        if final_policy_checkpoint is not None:
            payload["final_policy_checkpoint"] = _json_value(final_policy_checkpoint)
        # PostgreSQL stores this envelope as JSONB.  Freeze the same list/map
        # representation before hashing so an immediate return and a later
        # canonical reload are byte-for-byte equivalent.
        payload = _json_value(payload)
        return {"payload": payload, "digest": _sha256(payload)}

    def _advance_with_checkpoint(
        self, *, current: int, envelope: Mapping[str, Any]
    ) -> None:
        """CAS-advance and verify the canonical checkpoint returned by PostgreSQL."""

        payload = _mapping(envelope.get("payload"), "checkpoint payload")
        digest = envelope.get("digest")
        next_index = payload.get("next_sequence_index")
        if type(next_index) is not int or next_index != current + 1:
            raise ProductionRuntimeError("checkpoint cursor does not advance exactly once")
        if not isinstance(digest, str) or _sha256(payload) != digest:
            raise CheckpointTamperError("checkpoint envelope digest mismatch")
        advance = getattr(self._store, "advance_namespace_with_checkpoint", None)
        if not callable(advance):
            raise ProductionDependencyError(
                "canonical store lacks atomic cursor/checkpoint journaling"
            )
        advanced = self._bridge.call(
            advance(
                self._ctx,
                run_nonce=self._run_nonce,
                expected_current=current,
                next_sequence_index=next_index,
                checkpoint_payload=payload,
                checkpoint_digest=digest,
            )
        )
        if not isinstance(advanced, (tuple, list)) or len(advanced) != 2:
            raise ProductionRuntimeError("atomic cursor/checkpoint result is malformed")
        claim, journal = advanced
        claim_data = _mapping(claim, "advanced namespace claim")
        if (
            claim_data.get("namespace") != self.namespace
            or claim_data.get("run_nonce") != self._run_nonce
            or claim_data.get("next_sequence_index") != next_index
            or claim_data.get("claim_status") != "ACTIVE"
        ):
            raise ProductionRuntimeError("advanced namespace claim mismatch")
        journal_data = _mapping(journal, "canonical session checkpoint")
        expected_journal = {
            "org_id": self._ctx.org_id,
            "namespace": self.namespace,
            "owner_user_id": self._ctx.user_id,
            "run_nonce": self._run_nonce,
            "next_sequence_index": next_index,
            "checkpoint_schema": _CHECKPOINT_SCHEMA,
            "checkpoint_digest": digest,
        }
        if any(
            journal_data.get(name) != value for name, value in expected_journal.items()
        ):
            raise ProductionRuntimeError("canonical session checkpoint identity mismatch")
        if _json_value(journal_data.get("checkpoint_payload")) != _json_value(payload):
            raise ProductionRuntimeError("canonical session checkpoint payload mismatch")

    def after_task_and_checkpoint(
        self, task: object, result: object
    ) -> Mapping[str, Any]:
        """Durably finish one task and journal its exact recovery checkpoint.

        Canonical lifecycle writes and reference-only Qdrant reconciliation are
        completed before this method seals their evidence.  PostgreSQL then
        advances the frozen stream cursor and inserts that recovery envelope in
        one transaction.  Local state is advanced only after the canonical
        checkpoint has been reloaded and verified.
        """

        if self._state != "TASK_ACTIVE" or self._active_task is None:
            raise SessionStateError("no task is active")
        task_id = _task_id(task)
        if task_id != _task_id(self._active_task):
            raise SessionStateError("task completion does not match the active task")
        result_task_id = _task_value(result, "task_id")
        if result_task_id is not None and result_task_id != task_id:
            raise SessionStateError("result task_id does not match the active task")
        result_arm = _task_value(result, "arm")
        if result_arm is not None and result_arm != self.arm_id:
            raise SessionStateError("result arm does not match the session arm")
        if self._active_controller is None:
            raise SessionStateError("active task never acquired its memory controller")
        try:
            hook = getattr(self.lifecycle, "after_task", None)
            if callable(hook):
                hooked = hook(task=task, result=result)
                if inspect.isawaitable(hooked):
                    self._bridge.call(hooked)

            # Any corrupt canonical row, incomplete outbox reconciliation, or
            # unexpected vector mutation is fatal before the arm advances.
            canonical = self._canonical_evidence()
            qdrant = self._qdrant_evidence()
            summary = {
                "task_id": task_id,
                "arm": self.arm_id,
                "sequence_index": self._active_sequence_index,
                "result": _json_value(result),
                "controller_state": _json_value(
                    self._active_controller.checkpoint_state()
                ),
            }
            completed_digest = _sha256(summary)
            current = int(self._active_sequence_index)
            completed = [*self._completed_task_digests, completed_digest]
            envelope = self._checkpoint_envelope(
                next_sequence_index=current + 1,
                completed_task_digests=completed,
                canonical_evidence=canonical,
                qdrant_evidence=qdrant,
            )
            self._advance_with_checkpoint(current=current, envelope=envelope)
        except BaseException:
            self._state = "BROKEN"
            raise
        self._completed_task_digests = completed
        self._next_sequence_index = current + 1
        self._active_task = None
        self._active_sequence_index = None
        self._active_controller = None
        self._state = "READY"
        self._latest_checkpoint_envelope = _json_value(envelope)
        return envelope

    def after_task(self, task: object, result: object) -> None:
        """Compatibility wrapper; completion is always canonically checkpointed."""

        self.after_task_and_checkpoint(task, result)

    def finalize_development(self, expected_resume_cursor: int) -> Mapping[str, Any]:
        """Finalize no-reuse credit and return the sole immutable M2 checkpoint."""

        if self._state != "READY":
            raise SessionStateError("development finalization requires an idle ready session")
        if self.arm_id != "M2" or self.split != "development" or self.evaluation:
            raise SessionStateError("only the mutable M2 development stream can be finalized")
        if type(expected_resume_cursor) is not int or expected_resume_cursor <= 0:
            raise ValueError("expected_resume_cursor must be positive")
        if self._next_sequence_index != expected_resume_cursor:
            raise SessionStateError("development stream cursor is incomplete")
        hook = getattr(self.lifecycle, "finalize_development_and_freeze", None)
        if not callable(hook):
            raise ProductionDependencyError("M2 lifecycle has no development finalizer")
        checkpoint = hook(
            completed_cursor=self._next_sequence_index,
            expected_cursor=expected_resume_cursor,
        )
        try:
            restored = DoubleDQNMemoryPolicy.from_frozen_checkpoint(checkpoint)
        except (CheckpointError, KeyError, TypeError, ValueError) as exc:
            raise ProductionRuntimeError(
                "development finalizer returned an invalid frozen checkpoint"
            ) from exc
        if not restored.frozen:
            raise ProductionRuntimeError("development checkpoint is not frozen")
        frozen = _json_value(checkpoint)
        try:
            canonical = self._canonical_evidence()
            qdrant = self._qdrant_evidence()
            envelope = self._checkpoint_envelope(
                next_sequence_index=self._next_sequence_index + 1,
                task_cursor=self._next_sequence_index,
                stream_state="DEVELOPMENT_FINALIZED",
                completed_task_digests=self._completed_task_digests,
                canonical_evidence=canonical,
                qdrant_evidence=qdrant,
                final_policy_checkpoint=frozen,
            )
            self._advance_with_checkpoint(
                current=self._next_sequence_index, envelope=envelope
            )
        except BaseException:
            self._state = "BROKEN"
            raise
        self._next_sequence_index += 1
        self._final_policy_checkpoint = frozen
        self._latest_checkpoint_envelope = _json_value(envelope)
        self._state = "DEVELOPMENT_FINALIZED"
        return frozen

    def checkpoint(self, next_sequence_index: int) -> Mapping[str, Any]:
        if self._state != "READY":
            raise SessionStateError("checkpoint requires an idle ready session")
        if next_sequence_index != self._next_sequence_index:
            raise SessionStateError("checkpoint next_sequence_index mismatch")
        return self._checkpoint_envelope(
            next_sequence_index=next_sequence_index,
            completed_task_digests=self._completed_task_digests,
        )

    def _validated_prepared_task_checkpoint(
        self, value: Optional[Mapping[str, Any]]
    ) -> Optional[Mapping[str, Any]]:
        if value is None:
            return None
        if not isinstance(value, Mapping) or set(value) != {"payload", "digest"}:
            raise CheckpointTamperError("prepared-task checkpoint is malformed")
        payload = value.get("payload")
        digest = value.get("digest")
        if not isinstance(payload, Mapping) or not isinstance(digest, str):
            raise CheckpointTamperError("prepared-task checkpoint is malformed")
        if _sha256(payload) != digest:
            raise CheckpointTamperError("prepared-task checkpoint digest mismatch")
        expected = {
            "schema": _PREPARED_TASK_SCHEMA,
            "namespace": self.namespace,
            "experiment_id": self.experiment_id,
            "split": self.split,
            "arm_id": self.arm_id,
            "task_order_hash": self.task_order_hash,
            "config_hash": self.config_hash,
            "run_nonce": self._run_nonce,
        }
        if any(payload.get(name) != item for name, item in expected.items()):
            raise CheckpointTamperError("prepared-task checkpoint identity mismatch")
        sequence_index = payload.get("sequence_index")
        task_id = payload.get("task_id")
        if (
            type(sequence_index) is not int
            or not 0 <= sequence_index < len(self._tasks)
            or task_id != self._task_ids[sequence_index]
            or not isinstance(payload.get("lifecycle_state"), Mapping)
        ):
            raise CheckpointTamperError("prepared-task checkpoint cursor is invalid")
        _canonical_counts(payload.get("canonical_evidence"))
        _qdrant_point_digest_maps(payload.get("qdrant_evidence"))
        _verified_receipt_suffix(
            payload.get("lifecycle_receipt_evidence"),
            payload.get("lifecycle_receipt_evidence"),
            namespace=self.namespace,
            owner_user_id=self._ctx.user_id,
        )
        return _json_value(payload)

    def _current_inflight_proof(
        self,
        value: Optional[RuntimeCheckpoint],
        *,
        task_cursor: int,
    ) -> Optional[tuple[RuntimeCheckpoint, ShortTermWorkingGraph, tuple[Mapping[str, Any], ...]]]:
        if value is None:
            return None
        checkpoint, graph, ledger = _validated_runtime_checkpoint_proof(value)
        if checkpoint.arm != self.arm_id:
            raise CheckpointTamperError("in-flight checkpoint arm mismatch")
        try:
            proof_index = self._task_ids.index(checkpoint.task_id)
        except ValueError as exc:
            raise CheckpointTamperError("in-flight checkpoint task is not frozen") from exc
        if proof_index < task_cursor:
            if proof_index == task_cursor - 1 and checkpoint.state == "DONE":
                return None
            raise CheckpointTamperError("in-flight checkpoint is stale")
        if proof_index != task_cursor or task_cursor >= len(self._tasks):
            raise CheckpointTamperError("in-flight checkpoint cursor mismatch")
        if graph.repository != _task_value(self._tasks[task_cursor], "repository"):
            raise CheckpointTamperError("in-flight working graph repository mismatch")
        return checkpoint, graph, ledger

    @staticmethod
    def _prepared_event_time(
        lifecycle_state: Mapping[str, Any], task_id: str
    ) -> Optional[str]:
        payload = lifecycle_state.get("payload")
        if not isinstance(payload, Mapping):
            return None
        prepared = payload.get("prepared_task_times")
        row = prepared.get(task_id) if isinstance(prepared, Mapping) else None
        event_time = row.get("event_time") if isinstance(row, Mapping) else None
        return event_time if isinstance(event_time, str) and event_time else None

    def _validate_task_receipt_suffix(
        self,
        suffix: Sequence[Mapping[str, Any]],
        proof: tuple[RuntimeCheckpoint, ShortTermWorkingGraph, tuple[Mapping[str, Any], ...]],
    ) -> frozenset[str]:
        checkpoint, graph, ledger = proof
        allowed_by_phase = {
            "DECOMPOSED": {"ACCESS"},
            "RUNNING": {"ACCESS"},
            "AGENT_COMPLETE": {"ACCESS"},
            "PATCH_FINALIZED": {"ACCESS"},
            "GRADED": {"ACCESS"},
            "GRADER_FAILED": {"ACCESS"},
            "EXTRACTED": {"ACCESS", "LIFECYCLE_STORE"},
            "LIFECYCLE_STORED": {"ACCESS", "LIFECYCLE_STORE", "CREDIT"},
            "LIFECYCLE_CREDITED": {"ACCESS", "LIFECYCLE_STORE", "CREDIT"},
            "DONE": {"ACCESS", "LIFECYCLE_STORE", "CREDIT"},
        }
        ledger_active: set[str] = set()
        for row in ledger:
            active_node_id = row.get("active_node_id")
            if not isinstance(active_node_id, str) or not active_node_id:
                raise CheckpointTamperError("in-flight injection has no active node")
            if row.get("namespace") not in {None, "", self.namespace}:
                raise CheckpointTamperError("in-flight injection namespace mismatch")
            ledger_active.add(active_node_id)
        next_active: Optional[str] = None
        if checkpoint.state in {"DECOMPOSED", "RUNNING"} and not graph.complete:
            if graph.active_node is not None:
                next_active = graph.active_node.node_id
            else:
                ready = graph.ready_nodes()
                if not ready:
                    raise CheckpointTamperError("in-flight graph has no ready active node")
                next_active = ready[0].node_id
        access_scopes: set[tuple[str, ...]] = set()
        store_count = 0
        touched: set[str] = set()
        for row in suffix:
            scope = _mapping(row.get("operation_scope"), "receipt operation scope")
            kind = str(scope.get("kind"))
            active = tuple(scope.get("active_node_ids", ()))
            if (
                scope.get("task_id") != checkpoint.task_id
                or kind not in allowed_by_phase[checkpoint.state]
            ):
                raise CheckpointTamperError(
                    "receipt suffix is not bound to the in-flight task phase"
                )
            if kind == "ACCESS":
                if (
                    not row.get("access_event_ids")
                    or row.get("index_node_ids")
                    or row.get("index_intent_ids")
                    or row.get("delete_node_ids")
                    or row.get("delete_intent_ids")
                ):
                    raise CheckpointTamperError("access receipt has invalid side effects")
                if self.arm_id == "M1":
                    valid_active = active == ("__TASK__",)
                elif self.arm_id == "M2":
                    allowed_nodes = set(ledger_active)
                    if next_active is not None:
                        allowed_nodes.add(next_active)
                    valid_active = len(active) == 1 and active[0] in allowed_nodes
                else:
                    valid_active = False
                if not valid_active or active in access_scopes:
                    raise CheckpointTamperError(
                        "access receipt is not bound to one resumable active node"
                    )
                access_scopes.add(active)
                access_delta = row["canonical_row_deltas"]
                if (
                    access_delta["trimem_memory_access_events"]["inserted"]
                    != len(row["access_event_ids"])
                    or any(
                        delta["inserted"]
                        for table, delta in access_delta.items()
                        if table not in {
                            "trimem_memory_access_events", _RECEIPT_TABLE
                        }
                    )
                ):
                    raise CheckpointTamperError(
                        "access receipt canonical delta is not exact"
                    )
            elif kind == "LIFECYCLE_STORE":
                store_count += 1
                if (
                    self.arm_id not in {"M1", "M2"}
                    or store_count != 1
                    or active
                    or row.get("access_event_ids")
                ):
                    raise CheckpointTamperError("lifecycle store receipt scope is invalid")
            elif kind == "CREDIT":
                if (
                    self.arm_id != "M2"
                    or active != tuple(sorted(ledger_active))
                    or row.get("access_event_ids")
                ):
                    raise CheckpointTamperError("credit receipt scope is invalid")
            else:
                raise CheckpointTamperError("finalizer receipt appeared inside a task")
            touched.update(str(item) for item in row.get("index_node_ids", ()))
            touched.update(str(item) for item in row.get("delete_node_ids", ()))
        return frozenset(touched)

    def _validate_finalizer_receipt_suffix(
        self,
        suffix: Sequence[Mapping[str, Any]],
        checkpoint_payload: Mapping[str, Any],
        *,
        allow_development_finalization: bool,
    ) -> frozenset[str]:
        if (
            not allow_development_finalization
            or self.arm_id != "M2"
            or self.split != "development"
            or self.evaluation
            or checkpoint_payload.get("task_cursor") != len(self._tasks)
            or checkpoint_payload.get("stream_state", "TASK_STREAM") != "TASK_STREAM"
        ):
            raise CheckpointTamperError("receipt suffix has no in-flight task proof")
        lifecycle_state = checkpoint_payload.get("lifecycle_state")
        own = lifecycle_state.get("lifecycle") if isinstance(lifecycle_state, Mapping) else None
        own_payload = own.get("payload") if isinstance(own, Mapping) else None
        if (
            not isinstance(own_payload, Mapping)
            or _sha256(own_payload) != own.get("digest")
        ):
            raise CheckpointTamperError("finalizer lifecycle checkpoint is invalid")
        pending = own_payload.get("pending_by_memory_id")
        if not isinstance(pending, Mapping):
            raise CheckpointTamperError("finalizer pending ledger is missing")
        remaining_task_ids = [
            str(row.get("source_task_id", ""))
            for row in pending.values()
            if isinstance(row, Mapping)
        ]
        if len(remaining_task_ids) != len(pending) or any(
            not task_id for task_id in remaining_task_ids
        ):
            raise CheckpointTamperError("finalizer pending ledger is invalid")
        for row in suffix:
            scope = _mapping(row.get("operation_scope"), "finalizer operation scope")
            task_id = scope.get("task_id")
            if (
                scope.get("kind") != "FINALIZE"
                or scope.get("active_node_ids") != []
                or task_id not in remaining_task_ids
                or row.get("access_event_ids")
                or row.get("index_node_ids")
                or row.get("index_intent_ids")
                or row.get("delete_node_ids")
                or row.get("delete_intent_ids")
            ):
                raise CheckpointTamperError("finalizer receipt scope is invalid")
            remaining_task_ids.remove(str(task_id))
        return frozenset()

    def _restore_inflight_lifecycle(
        self,
        *,
        proof: Optional[tuple[RuntimeCheckpoint, ShortTermWorkingGraph, tuple[Mapping[str, Any], ...]]],
        prepared: Optional[Mapping[str, Any]],
    ) -> None:
        state: Optional[Mapping[str, Any]] = None
        if prepared is not None:
            state = _mapping(prepared.get("lifecycle_state"), "prepared lifecycle state")
        if proof is not None:
            checkpoint = proof[0]
            if prepared is not None:
                prepared_time = self._prepared_event_time(
                    _mapping(prepared.get("lifecycle_state"), "prepared lifecycle state"),
                    checkpoint.task_id,
                )
                proof_time = self._prepared_event_time(
                    checkpoint.lifecycle_state, checkpoint.task_id
                )
                if prepared_time != proof_time:
                    raise CheckpointTamperError(
                        "prepared task time differs from the agent checkpoint"
                    )
            state = checkpoint.lifecycle_state
        if state:
            hook = getattr(self.lifecycle, "restore_state", None)
            if not callable(hook):
                raise CheckpointTamperError(
                    "in-flight lifecycle checkpoint cannot be restored"
                )
            hook(state)

    def _recover_receipt_bound_suffix(
        self,
        *,
        checkpoint_payload: Mapping[str, Any],
        prior_canonical: Mapping[str, Any],
        prior_qdrant: Mapping[str, Any],
        prior_receipts: Mapping[str, Any],
        current_canonical: Mapping[str, Any],
        current_qdrant: Mapping[str, Any],
        current_receipts: Mapping[str, Any],
        proof: Optional[tuple[RuntimeCheckpoint, ShortTermWorkingGraph, tuple[Mapping[str, Any], ...]]],
        allow_development_finalization: bool,
    ) -> Mapping[str, Any]:
        suffix = _verified_receipt_suffix(
            prior_receipts,
            current_receipts,
            namespace=self.namespace,
            owner_user_id=self._ctx.user_id,
        )
        if not suffix:
            raise CheckpointTamperError(
                "Qdrant namespace changed or canonical state drifted without an operation-receipt suffix"
            )
        _verified_canonical_receipt_delta(
            prior_canonical, current_canonical, suffix
        )
        if proof is not None:
            expected_touched = self._validate_task_receipt_suffix(suffix, proof)
        else:
            expected_touched = self._validate_finalizer_receipt_suffix(
                suffix,
                checkpoint_payload,
                allow_development_finalization=allow_development_finalization,
            )
        replayed_touched = self.persistence.replay_receipt_index_effects(
            self._ctx, suffix
        )
        if replayed_touched != expected_touched:
            raise CheckpointTamperError(
                "receipt Qdrant recovery identifiers disagree"
            )
        repaired_qdrant = self._qdrant_evidence()
        changed = _qdrant_changed_point_ids(prior_qdrant, repaired_qdrant)
        if not changed <= set(expected_touched):
            raise CheckpointTamperError(
                "Qdrant drift is not explained by operation receipts"
            )
        return repaired_qdrant

    def _verify_inflight_external_state(
        self,
        *,
        prior_canonical: Mapping[str, Any],
        prior_qdrant: Mapping[str, Any],
        prior_receipts: Mapping[str, Any],
        current_canonical: Mapping[str, Any],
        current_qdrant: Mapping[str, Any],
        current_receipts: Mapping[str, Any],
        proof: Optional[
            tuple[RuntimeCheckpoint, ShortTermWorkingGraph, tuple[Mapping[str, Any], ...]]
        ],
    ) -> bool:
        """Let a lifecycle prove a non-0015 in-flight append exactly once.

        M1's frozen live-v0.3 comparator writes the ``private_episodes`` row
        and matching ``CONTRACT_CANDIDATE`` outbox event atomically outside the
        TriMem 0015 receipt tables.  Current main performs no direct Qdrant
        write for that solve side effect.  Only a task-local agent checkpoint
        containing its prepared descriptor may authorize the exact row/outbox
        pair while Qdrant remains byte-identical; all other arms/deltas continue
        through the canonical receipt verifier below.
        """
        hook = getattr(self.lifecycle, "verify_inflight_external_state", None)
        if proof is None or not callable(hook):
            return False
        if self.arm_id != "M1":
            raise CheckpointTamperError(
                "non-receipt external-state recovery is restricted to M1"
            )
        result = hook(
            prior_canonical=prior_canonical,
            current_canonical=current_canonical,
            prior_qdrant=prior_qdrant,
            current_qdrant=current_qdrant,
            prior_receipts=prior_receipts,
            current_receipts=current_receipts,
            checkpoint_state=proof[0].lifecycle_state,
            checkpoint_phase=proof[0].state,
            checkpoint_task_id=proof[0].task_id,
        )
        data = _mapping(result, "in-flight external-state proof")
        body = {key: value for key, value in data.items() if key != "proof_digest"}
        if (
            data.get("schema") != "trimem/live-v03-inflight-external-proof/1.0"
            or data.get("namespace") != self.namespace
            or data.get("verified") is not True
            or data.get("proof_digest") != _sha256(body)
        ):
            raise CheckpointTamperError(
                "in-flight external-state proof is invalid"
            )
        self._inflight_external_state_proof = _json_value(data)
        return True

    def restore_latest_canonical_checkpoint(
        self,
        *,
        inflight_checkpoint: Optional[RuntimeCheckpoint] = None,
        prepared_task_checkpoint: Optional[Mapping[str, Any]] = None,
        allow_development_finalization: bool = False,
    ) -> Mapping[str, Any]:
        """Reload and restore the newest PostgreSQL recovery envelope.

        The caller must reopen the arm with the original ``run_nonce``.  A
        random/new nonce cannot discover or take over another run's journal.
        """

        if self._state not in {"CREATED", "READY"}:
            raise SessionStateError(
                "canonical checkpoint restore requires an idle session"
            )
        load = getattr(self._store, "load_latest_session_checkpoint", None)
        if not callable(load):
            raise ProductionDependencyError(
                "canonical store lacks session checkpoint recovery"
            )
        try:
            journal = self._bridge.call(
                load(self._ctx, run_nonce=self._run_nonce)
            )
            data = _mapping(journal, "canonical session checkpoint")
            if (
                data.get("org_id") != self._ctx.org_id
                or data.get("namespace") != self.namespace
                or data.get("owner_user_id") != self._ctx.user_id
                or data.get("run_nonce") != self._run_nonce
            ):
                raise CheckpointTamperError(
                    "canonical session checkpoint partition mismatch"
                )
            envelope = {
                "payload": _json_value(data.get("checkpoint_payload")),
                "digest": data.get("checkpoint_digest"),
            }
            self.restore(
                envelope,
                inflight_checkpoint=inflight_checkpoint,
                prepared_task_checkpoint=prepared_task_checkpoint,
                allow_development_finalization=allow_development_finalization,
            )
            return envelope
        except BaseException:
            self._state = "BROKEN"
            raise

    def _resume_cursor_zero_without_journal(
        self,
        *,
        inflight_checkpoint: Optional[RuntimeCheckpoint],
        prepared: Optional[Mapping[str, Any]],
    ) -> None:
        """Recover an exact cursor-zero claim under the caller's BROKEN guard."""
        proof = self._current_inflight_proof(inflight_checkpoint, task_cursor=0)
        if prepared is not None and prepared.get("sequence_index") != 0:
            raise CheckpointTamperError("cursor-zero prepared task is stale")
        try:
            self._claim(resume=True, next_sequence_index=0)
            existing_claim = True
        except NotFound:
            existing_claim = False
        if existing_claim:
            self._vector_index.ensure_ready()
            canonical = self._canonical_evidence()
            qdrant = self._qdrant_evidence()
            receipts = self.persistence.lifecycle_receipt_evidence(self._ctx)
            if prepared is not None:
                prior_canonical = _mapping(
                    prepared.get("canonical_evidence"), "prepared canonical evidence"
                )
                prior_qdrant = _mapping(
                    prepared.get("qdrant_evidence"), "prepared Qdrant evidence"
                )
                prior_receipts = _mapping(
                    prepared.get("lifecycle_receipt_evidence"),
                    "prepared receipt evidence",
                )
            else:
                prior_canonical = _empty_canonical_evidence_like(canonical)
                prior_qdrant = _empty_qdrant_evidence_like(qdrant)
                prior_receipts = _empty_receipt_evidence(
                    self.namespace, self._ctx.user_id
                )
            drift = any((
                _json_value(prior_canonical) != _json_value(canonical),
                _json_value(prior_qdrant) != _json_value(qdrant),
                _json_value(prior_receipts) != _json_value(receipts),
            ))
            if drift and proof is None:
                raise FreshnessViolation(
                    "cursor-zero resume has state without an agent checkpoint "
                    "(task-local proof required)"
                )
            if drift:
                externally_verified = self._verify_inflight_external_state(
                    prior_canonical=prior_canonical,
                    prior_qdrant=prior_qdrant,
                    prior_receipts=prior_receipts,
                    current_canonical=canonical,
                    current_qdrant=qdrant,
                    current_receipts=receipts,
                    proof=proof,
                )
                if not externally_verified:
                    self._recover_receipt_bound_suffix(
                        checkpoint_payload={
                            "task_cursor": 0,
                            "stream_state": "TASK_STREAM",
                            "lifecycle_state": {},
                        },
                        prior_canonical=prior_canonical,
                        prior_qdrant=prior_qdrant,
                        prior_receipts=prior_receipts,
                        current_canonical=canonical,
                        current_qdrant=qdrant,
                        current_receipts=receipts,
                        proof=proof,
                        allow_development_finalization=False,
                    )
            self._restore_inflight_lifecycle(proof=proof, prepared=prepared)
        else:
            # The identity artifact can precede the PostgreSQL claim. The store
            # accepts this creation only if no conflicting claim exists.
            if proof is not None or prepared is not None:
                raise CheckpointTamperError(
                    "task-local checkpoint exists without a canonical claim"
                )
            self._claim(resume=False, next_sequence_index=0)
            canonical = self._canonical_evidence()
            if any(count != 0 for _, count in canonical["row_counts"]):
                raise FreshnessViolation("new canonical namespace is not empty")
            qdrant = self._qdrant_evidence()
            if any(row["points"] != 0 for row in qdrant["collections"].values()):
                raise FreshnessViolation("new Qdrant arm collections are not empty")
        self._vector_index.ensure_ready()
        self._state = "READY"
        return None

    def resume_canonical_stream(
        self,
        *,
        inflight_checkpoint: Optional[RuntimeCheckpoint] = None,
        prepared_task_checkpoint: Optional[Mapping[str, Any]] = None,
        allow_development_finalization: bool = False,
    ) -> Optional[Mapping[str, Any]]:
        """Resume the latest task boundary or an exact cursor-zero claim.

        The run nonce is persisted by the driver *before* the first claim.  If a
        process dies during the first task there is intentionally no arm-level
        checkpoint yet, so recovery binds the exact active cursor-zero claim.
        Non-empty canonical/vector state is accepted only when the driver has a
        task-local AgentRuntime checkpoint proving an in-flight first task.
        A truly pre-claim crash uses the store's exact-idempotent claim path.
        """

        if type(allow_development_finalization) is not bool:
            raise ValueError("allow_development_finalization must be boolean")
        if self._state != "CREATED":
            raise SessionStateError("canonical stream resume requires a new session")
        prepared = self._validated_prepared_task_checkpoint(
            prepared_task_checkpoint
        )
        load = getattr(self._store, "load_latest_session_checkpoint", None)
        if not callable(load):
            raise ProductionDependencyError(
                "canonical store lacks session checkpoint recovery"
            )
        try:
            journal = self._bridge.call(load(self._ctx, run_nonce=self._run_nonce))
        except NotFound:
            try:
                return self._resume_cursor_zero_without_journal(
                    inflight_checkpoint=inflight_checkpoint,
                    prepared=prepared,
                )
            except BaseException:
                self._state = "BROKEN"
                raise
        except BaseException:
            self._state = "BROKEN"
            raise

        try:
            data = _mapping(journal, "canonical session checkpoint")
            envelope = {
                "payload": _json_value(data.get("checkpoint_payload")),
                "digest": data.get("checkpoint_digest"),
            }
            self.restore(
                envelope,
                inflight_checkpoint=inflight_checkpoint,
                prepared_task_checkpoint=prepared_task_checkpoint,
                allow_development_finalization=allow_development_finalization,
            )
            return envelope
        except BaseException:
            self._state = "BROKEN"
            raise

    def restore(
        self,
        checkpoint: Mapping[str, Any],
        *,
        inflight_checkpoint: Optional[RuntimeCheckpoint] = None,
        prepared_task_checkpoint: Optional[Mapping[str, Any]] = None,
        allow_development_finalization: bool = False,
    ) -> None:
        if self._state not in {"CREATED", "READY"}:
            raise SessionStateError("checkpoint restore requires an idle session")
        if not isinstance(checkpoint, Mapping) or set(checkpoint) != {"payload", "digest"}:
            raise CheckpointTamperError("checkpoint envelope is malformed")
        payload = checkpoint.get("payload")
        digest = checkpoint.get("digest")
        if not isinstance(payload, Mapping) or not isinstance(digest, str):
            raise CheckpointTamperError("checkpoint envelope is malformed")
        if _sha256(payload) != digest:
            raise CheckpointTamperError("checkpoint digest mismatch")
        identity = {
            "schema": _CHECKPOINT_SCHEMA,
            "namespace": self.namespace,
            "experiment_id": self.experiment_id,
            "split": self.split,
            "arm_id": self.arm_id,
            "task_order_hash": self.task_order_hash,
            "config_hash": self.config_hash,
        }
        if any(payload.get(name) != value for name, value in identity.items()):
            raise CheckpointTamperError("checkpoint identity mismatch")
        run_nonce = payload.get("run_nonce")
        next_index = payload.get("next_sequence_index")
        if not isinstance(run_nonce, str) or not run_nonce:
            raise CheckpointTamperError("checkpoint run_nonce is invalid")
        if run_nonce != self._run_nonce:
            raise CheckpointTamperError(
                "checkpoint run_nonce does not match this session"
            )
        stream_state = payload.get("stream_state", "TASK_STREAM")
        task_cursor = payload.get("task_cursor", next_index)
        if type(next_index) is not int or type(task_cursor) is not int:
            raise CheckpointTamperError("checkpoint sequence index is invalid")
        if stream_state == "TASK_STREAM":
            if not 0 <= next_index <= len(self._tasks) or task_cursor != next_index:
                raise CheckpointTamperError("checkpoint task cursor is invalid")
            final_policy_checkpoint = None
        elif stream_state == "DEVELOPMENT_FINALIZED":
            if (
                self.arm_id != "M2"
                or self.split != "development"
                or self.evaluation
                or task_cursor != len(self._tasks)
                or next_index != task_cursor + 1
            ):
                raise CheckpointTamperError("finalized development cursor is invalid")
            final_policy_checkpoint = payload.get("final_policy_checkpoint")
            if not isinstance(final_policy_checkpoint, Mapping):
                raise CheckpointTamperError("final policy checkpoint is missing")
            try:
                frozen_policy = DoubleDQNMemoryPolicy.from_frozen_checkpoint(
                    final_policy_checkpoint
                )
            except (CheckpointError, KeyError, TypeError, ValueError) as exc:
                raise CheckpointTamperError("final policy checkpoint is invalid") from exc
            if not frozen_policy.frozen:
                raise CheckpointTamperError("final policy checkpoint is not frozen")
        else:
            raise CheckpointTamperError("checkpoint stream state is invalid")
        completed = payload.get("completed_task_digests")
        if not isinstance(completed, list) or len(completed) != task_cursor or any(
            not isinstance(item, str) or not _SHA256.fullmatch(item) for item in completed
        ):
            raise CheckpointTamperError("checkpoint completed-task ledger is invalid")

        prepared = self._validated_prepared_task_checkpoint(
            prepared_task_checkpoint
        )
        if prepared is not None:
            prepared_index = int(prepared["sequence_index"])
            if prepared_index < task_cursor:
                if prepared_index != task_cursor - 1:
                    raise CheckpointTamperError("prepared-task checkpoint is stale")
                prepared = None
            elif prepared_index != task_cursor or task_cursor >= len(self._tasks):
                raise CheckpointTamperError("prepared-task checkpoint cursor mismatch")
        proof = self._current_inflight_proof(
            inflight_checkpoint, task_cursor=task_cursor
        )
        if proof is not None and prepared is not None:
            if prepared.get("task_id") != proof[0].task_id:
                raise CheckpointTamperError(
                    "prepared task and agent checkpoint disagree"
                )

        if self._state == "CREATED":
            self._claim(resume=True, next_sequence_index=next_index)
            self._vector_index.ensure_ready()

        prior_canonical = _mapping(
            payload.get("canonical_evidence"), "checkpoint canonical evidence"
        )
        prior_qdrant = _mapping(
            payload.get("qdrant_evidence"), "checkpoint Qdrant evidence"
        )
        prior_receipts = _mapping(
            payload.get("lifecycle_receipt_evidence"),
            "checkpoint lifecycle receipt evidence",
        )
        if prepared is not None and any((
            _json_value(prepared.get("canonical_evidence"))
            != _json_value(prior_canonical),
            _json_value(prepared.get("qdrant_evidence"))
            != _json_value(prior_qdrant),
            _json_value(prepared.get("lifecycle_receipt_evidence"))
            != _json_value(prior_receipts),
        )):
            raise CheckpointTamperError(
                "prepared-task checkpoint is not based on the arm boundary"
            )
        canonical = self._canonical_evidence()
        qdrant = self._qdrant_evidence()
        receipts = self.persistence.lifecycle_receipt_evidence(self._ctx)
        drift = any((
            _json_value(prior_canonical) != _json_value(canonical),
            _json_value(prior_qdrant) != _json_value(qdrant),
            _json_value(prior_receipts) != _json_value(receipts),
        ))
        if drift:
            externally_verified = self._verify_inflight_external_state(
                prior_canonical=prior_canonical,
                prior_qdrant=prior_qdrant,
                prior_receipts=prior_receipts,
                current_canonical=canonical,
                current_qdrant=qdrant,
                current_receipts=receipts,
                proof=proof,
            )
            if not externally_verified:
                self._recover_receipt_bound_suffix(
                    checkpoint_payload=payload,
                    prior_canonical=prior_canonical,
                    prior_qdrant=prior_qdrant,
                    prior_receipts=prior_receipts,
                    current_canonical=canonical,
                    current_qdrant=qdrant,
                    current_receipts=receipts,
                    proof=proof,
                    allow_development_finalization=allow_development_finalization,
                )
        else:
            _verified_receipt_suffix(
                prior_receipts,
                receipts,
                namespace=self.namespace,
                owner_user_id=self._ctx.user_id,
            )

        lifecycle_state = payload.get("lifecycle_state")
        if not isinstance(lifecycle_state, Mapping):
            raise CheckpointTamperError("checkpoint lifecycle state is malformed")
        persistence_state = lifecycle_state.get("persistence", lifecycle_state)
        if not isinstance(persistence_state, Mapping):
            raise CheckpointTamperError("checkpoint persistence state is malformed")
        self.persistence.restore_state(persistence_state)
        hook = getattr(self.lifecycle, "restore_state", None)
        if (
            stream_state == "TASK_STREAM"
            and callable(hook)
            and self.lifecycle is not self.persistence
            and proof is None
            and prepared is None
        ):
            own_state = lifecycle_state.get("lifecycle")
            if not isinstance(own_state, Mapping):
                raise CheckpointTamperError("checkpoint lifecycle adapter state is missing")
            hook(own_state)
        self._restore_inflight_lifecycle(proof=proof, prepared=prepared)
        self._completed_task_digests = list(completed)
        self._next_sequence_index = next_index
        self._final_policy_checkpoint = (
            _json_value(final_policy_checkpoint)
            if final_policy_checkpoint is not None
            else None
        )
        self._latest_checkpoint_envelope = {
            "payload": _json_value(payload),
            "digest": digest,
        }
        self._state = stream_state if stream_state == "DEVELOPMENT_FINALIZED" else "READY"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Optional[BaseException] = None
        for target in (self.lifecycle, self._qdrant_client):
            method = getattr(target, "close", None)
            if callable(method):
                try:
                    result = method()
                    if inspect.isawaitable(result):
                        self._bridge.call(result)
                except BaseException as exc:  # close every owned resource
                    first_error = first_error or exc
        dispose = getattr(self._engine, "dispose", None)
        if callable(dispose):
            try:
                result = dispose()
                if inspect.isawaitable(result):
                    self._bridge.call(result)
            except BaseException as exc:
                first_error = first_error or exc
        try:
            self._bridge.close()
        except BaseException as exc:
            first_error = first_error or exc
        self._state = "CLOSED"
        if first_error is not None:
            raise ProductionRuntimeError("failed to close production arm resources") from first_error


def _validate_database_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("database_url is required")
    scheme = urlparse(value).scheme.casefold()
    if not scheme.startswith("postgresql"):
        raise ProductionDependencyError("benchmark canonical backend must be PostgreSQL")
    return value


def _validate_qdrant_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("qdrant_url is required")
    if urlparse(value).scheme.casefold() not in {"http", "https"}:
        raise ProductionDependencyError("benchmark vector backend must be a Qdrant HTTP endpoint")
    return value


def _service_endpoint_hash(value: str) -> str:
    """Bind a backend identity without retaining credentials in checkpoints."""

    parsed = urlparse(value)
    try:
        port = parsed.port
        hostname = parsed.hostname
    except ValueError as exc:
        raise ProductionDependencyError("service endpoint has an invalid port") from exc
    if not hostname:
        raise ProductionDependencyError("service endpoint has no hostname")
    return _sha256(
        {
            "scheme": parsed.scheme.casefold(),
            "hostname": hostname.casefold(),
            "port": port,
            "path": parsed.path or "/",
        }
    )


def _load_frozen_policy(path: Optional[str | Path], *, required: bool):
    if path is None:
        if required:
            raise ProductionDependencyError("frozen DQN checkpoint is required for M2 evaluation")
        return None, "not-applicable"
    target = Path(path)
    if not target.is_file():
        raise ProductionDependencyError("DQN checkpoint path does not exist")
    try:
        raw = target.read_bytes()
        value = strict_json_loads(raw)
        policy = DoubleDQNMemoryPolicy.from_frozen_checkpoint(value)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        CheckpointError,
        KeyError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProductionDependencyError("DQN checkpoint is not a valid frozen checkpoint") from exc
    return policy, "sha256:" + sha256_bytes(raw)


def _default_engine_factory(database_url: str):
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        return create_async_engine(database_url, future=True)
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - deployment extras
        raise ProductionDependencyError("SQLAlchemy async support is not installed") from exc


def _default_qdrant_client_factory(qdrant_url: str):
    try:
        from qdrant_client import QdrantClient
        return Qdrant112ClientAdapter(QdrantClient(url=qdrant_url))
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - deployment extras
        raise ProductionDependencyError("qdrant-client is not installed") from exc


def open_benchmark_arm(
    *,
    database_url: str,
    qdrant_url: str,
    experiment_id: str,
    split: str,
    arm_id: str,
    task_order: Sequence[object],
    dqn_checkpoint_path: Optional[str | Path],
    embedder_lock: Mapping[str, Any],
    evaluation: bool,
    engine_factory: Optional[Callable[[str], object]] = None,
    qdrant_client_factory: Optional[Callable[[str], object]] = None,
    embedder: Optional[object] = None,
    controller_factory: Optional[Callable[..., object]] = None,
    lifecycle_factory: Optional[Callable[..., object]] = None,
    run_nonce: Optional[str] = None,
    execution_lock_hash: Optional[str] = None,
) -> BenchmarkArmSession:
    """Open one fail-closed production benchmark arm.

    The first nine keyword arguments form the benchmark-facing contract.  The
    remaining hooks exist solely for dependency composition and credential-free
    tests; they never select an in-memory product implementation implicitly.
    """

    database = _validate_database_url(database_url)
    qdrant_endpoint = _validate_qdrant_url(qdrant_url)
    namespace = benchmark_namespace(experiment_id, split, arm_id)
    _, task_ids, _ = _normalize_task_order(task_order)
    if split == "heldout" and not evaluation:
        raise ProductionRuntimeError("heldout benchmark must run in frozen evaluation mode")
    if not isinstance(embedder_lock, Mapping):
        raise ValueError("embedder_lock must be a mapping")
    if split != "credential_free_replay" and (
        not isinstance(execution_lock_hash, str)
        or not _SHA256.fullmatch(execution_lock_hash)
    ):
        raise ProductionDependencyError(
            "benchmark execution requires a canonical full execution lock hash"
        )
    if execution_lock_hash is None:
        execution_lock_hash = _sha256(
            {"schema": "trimem/credential-free-execution-lock/1.0"}
        )
    elif not execution_lock_hash.startswith("sha256:"):
        execution_lock_hash = "sha256:" + execution_lock_hash

    selected_embedder = embedder or PinnedSentenceTransformerPPR()
    provenance = _verify_embedder_lock(selected_embedder, embedder_lock)
    if split != "credential_free_replay" and provenance.get("production") is not True:
        raise ProductionDependencyError("benchmark execution requires the frozen production embedder")
    policy, checkpoint_hash = _load_frozen_policy(
        dqn_checkpoint_path, required=(arm_id == "M2" and bool(evaluation))
    )
    if arm_id != "M2":
        # A supplied file is still verified above, but it cannot alter M0/M1.
        policy = None

    bridge = DedicatedAsyncLoop(name="trimem-%s-%s" % (experiment_id, arm_id))
    engine = qdrant_client = None
    try:
        engine = (engine_factory or _default_engine_factory)(database)
        _reject_in_memory(engine, "database engine")
        qdrant_client = (qdrant_client_factory or _default_qdrant_client_factory)(
            qdrant_endpoint
        )
        _reject_in_memory(qdrant_client, "Qdrant client")
        store = PostgresTriMemStore(engine, namespace=namespace)
        vector_index = QdrantVectorIndexV2(
            qdrant_client,
            int(provenance["dimensions"]),
            namespace=namespace,
        )
        persistence = CanonicalLifecyclePersistence(
            store,
            vector_index,
            selected_embedder,
            bridge,
            namespace=namespace,
            embedder_provenance=provenance,
        )

        if lifecycle_factory is None:
            if arm_id == "M0":
                lifecycle = NullExperienceLifecycle()
            elif arm_id == "M1":
                lifecycle = production_v03_lifecycle_factory(
                    arm_id=arm_id,
                    namespace=namespace,
                    split=split,
                    evaluation=bool(evaluation),
                    policy=policy,
                    canonical_store=store,
                    vector_index=vector_index,
                    embedder=selected_embedder,
                    persistence=persistence,
                )
            else:
                raise ProductionDependencyError(
                    "%s requires an explicit production lifecycle_factory" % arm_id
                )
        else:
            lifecycle = lifecycle_factory(
                arm_id=arm_id,
                namespace=namespace,
                split=split,
                evaluation=bool(evaluation),
                policy=policy,
                canonical_store=store,
                vector_index=vector_index,
                embedder=selected_embedder,
                persistence=persistence,
            )
        _reject_in_memory(lifecycle, "lifecycle")
        lifecycle_configuration_hash = getattr(lifecycle, "configuration_hash", None)
        if arm_id == "M0":
            lifecycle_configuration_hash = _sha256({"lifecycle": "NONE"})
        if not isinstance(lifecycle_configuration_hash, str) or not _SHA256.fullmatch(
            lifecycle_configuration_hash
        ):
            raise ProductionDependencyError(
                "lifecycle has no hash-bound production configuration"
            )
        if not lifecycle_configuration_hash.startswith("sha256:"):
            lifecycle_configuration_hash = "sha256:" + lifecycle_configuration_hash
        if arm_id == "M1" and controller_factory is None:
            controller_factory = production_v03_controller_factory

        config_hash = _sha256(
            {
                "schema": "trimem/production-arm-config/1.0",
                "namespace": namespace,
                "arm_id": arm_id,
                "split": split,
                "evaluation": bool(evaluation),
                "task_order_hash": _sha256(
                    [_task_order_payload(task) for task in task_order]
                ),
                "execution_lock_hash": execution_lock_hash,
                "database_endpoint_hash": _service_endpoint_hash(database),
                "qdrant_endpoint_hash": _service_endpoint_hash(qdrant_endpoint),
                "dqn_checkpoint_hash": checkpoint_hash,
                "lifecycle_configuration_hash": lifecycle_configuration_hash,
                "embedder_provenance": provenance,
                "canonical_backend": "postgresql",
                "vector_backend": "qdrant",
            }
        )
        return BenchmarkArmSession(
            experiment_id=experiment_id,
            split=split,
            arm_id=arm_id,
            task_order=task_order,
            store=store,
            vector_index=vector_index,
            qdrant_client=qdrant_client,
            embedder=selected_embedder,
            embedder_provenance=provenance,
            bridge=bridge,
            persistence=persistence,
            lifecycle=lifecycle,
            controller_factory=controller_factory,
            config_hash=config_hash,
            evaluation=bool(evaluation),
            run_nonce=run_nonce,
            engine=engine,
        )
    except BaseException:
        close = getattr(qdrant_client, "close", None)
        if callable(close):
            try:
                result = close()
                if inspect.isawaitable(result):
                    bridge.call(result)
            except BaseException:
                pass
        dispose = getattr(engine, "dispose", None)
        if callable(dispose):
            try:
                result = dispose()
                if inspect.isawaitable(result):
                    bridge.call(result)
            except BaseException:
                pass
        bridge.close()
        raise


__all__ = [
    "BenchmarkArmSession",
    "CanonicalLifecyclePersistence",
    "CheckpointTamperError",
    "DedicatedAsyncLoop",
    "FreshnessViolation",
    "ProductionDependencyError",
    "ProductionRuntimeError",
    "SessionStateError",
    "benchmark_namespace",
    "open_benchmark_arm",
]
