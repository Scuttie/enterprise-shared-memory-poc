"""Credential-free checks for the fail-closed production arm composition."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import inspect
import threading
import uuid

import pytest

from enterprise_memory.trimem.accounting import canonical_bytes, sha256_bytes
from enterprise_memory.trimem.agent_runtime import NoMemoryController
from enterprise_memory.trimem.arms import (
    ActiveNodeTriMemController,
    CurrentV03MemoryController,
)
from enterprise_memory.trimem.checkpoint import RuntimeCheckpoint
from enterprise_memory.trimem.policy import (
    DoubleDQNConfig,
    DoubleDQNMemoryPolicy,
    FeatureSchema,
)
from enterprise_memory.trimem.postgres_retrieval import (
    AuditedMemoryController,
    SyncPostgresQdrantRetrievalStore,
)
from enterprise_memory.trimem.postgres_store import (
    AppendReceipt,
    IndexOutboxIntent,
    LifecycleAppendBundle,
)
from enterprise_memory.trimem.production_runtime import (
    BenchmarkArmSession,
    CanonicalLifecyclePersistence,
    CheckpointTamperError,
    DedicatedAsyncLoop,
    FreshnessViolation,
    ProductionDependencyError,
    ProductionRuntimeError,
    SessionStateError,
    benchmark_namespace,
    open_benchmark_arm,
)
from enterprise_memory.trimem.production_v03_lifecycle import (
    production_v03_lifecycle_factory,
)
from enterprise_memory.trimem.schema import (
    AccessContext,
    GraphKind,
    GraphNode,
    NodeType,
    TemporalMetadata,
    canonical_hash,
)
from enterprise_memory.trimem.store import InMemoryTriMemStore, NotFound
from enterprise_memory.trimem.vector_index import QdrantVectorIndexV2
from enterprise_memory.trimem.working_graph import Evidence, ShortTermWorkingGraph, SubtaskSpec


NOW = "2026-08-31T00:00:00Z"
UNIT_RUN_NONCE = "00000000-0000-4000-8000-000000000001"


def _hash(value):
    return "sha256:" + sha256_bytes(canonical_bytes(value))


def _pending_intent(
    node,
    intent_id="00000000-0000-4000-8000-000000000099",
    *,
    operation="UPSERT",
    prior_content_hash=None,
):
    return IndexOutboxIntent(
        intent_id=intent_id,
        org_id=node.org_id,
        namespace=node.namespace,
        graph_id=node.graph_id,
        graph_kind=node.graph_kind,
        owner_user_id=node.owner_user_id,
        node_id=node.node_id,
        operation=operation,
        canonical_content_hash=node.content_hash,
        prior_content_hash=prior_content_hash,
        status="PENDING",
        attempts=0,
        last_error=None,
        created_at=NOW,
        updated_at=NOW,
        indexed_at=None,
    )


@dataclass(frozen=True)
class _Task:
    task_id: str
    org_id: str = "org-a"
    user_id: str = "alice"
    repository: str = "owner/repository"


class _Embedder:
    def __init__(self, dimensions=3, *, production=False):
        self.dimensions = dimensions
        self.production = production

    def embed(self, text):
        assert isinstance(text, str) and text
        return tuple([1.0] + [0.0] * (self.dimensions - 1))

    def provenance(self):
        return {
            "model_id": "credential-free-embedder",
            "revision": "frozen-test-revision",
            "dimensions": self.dimensions,
            "production": self.production,
            "credential_free": not self.production,
        }


class _FakeQdrant:
    def __init__(self, events=None):
        self.collections = {}
        self.payload_indexes = {}
        self.events = events if events is not None else []
        self.closed = False
        self.fail_upsert = False

    def collection_exists(self, collection_name):
        return collection_name in self.collections

    def create_collection(self, collection_name, *, vectors_config):
        self.events.append("qdrant_create")
        self.collections[collection_name] = {
            "vectors_config": dict(vectors_config),
            "points": {},
        }

    def get_collection(self, collection_name):
        return {"vectors_config": dict(self.collections[collection_name]["vectors_config"])}

    def create_payload_index(self, collection_name, *, field_name, field_schema, wait):
        assert wait is True
        self.payload_indexes.setdefault(collection_name, set()).add((field_name, field_schema))

    def upsert(self, collection_name, *, points, wait):
        assert wait is True
        self.events.append("qdrant_upsert")
        if self.fail_upsert:
            raise RuntimeError("simulated qdrant outage")
        for point in points:
            self.collections[collection_name]["points"][str(point["id"])] = dict(point)

    def delete(self, collection_name, *, points_selector, wait):
        assert wait is True
        self.events.append("qdrant_delete")
        for point_id in points_selector["points"]:
            self.collections[collection_name]["points"].pop(str(point_id), None)

    def query_points(self, **kwargs):
        return {"points": []}

    def close(self):
        self.closed = True


class _FakeCanonicalStore:
    TABLES = (
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

    def __init__(self, namespace, *, events=None):
        self.namespace = namespace
        self.events = events if events is not None else []
        self.counts = {name: 0 for name in self.TABLES}
        self.claim = None
        self.fail_append = False
        self.receipt = AppendReceipt(namespace, (), (), ())
        self.nodes = {}
        self.outbox = {}
        self.checkpoints = {}
        self.lifecycle_receipts = []

    async def claim_namespace(self, ctx, **kwargs):
        await asyncio.sleep(0)
        if self.claim is not None:
            raise RuntimeError("already claimed")
        self.claim = {
            "namespace": self.namespace,
            **kwargs,
            "next_sequence_index": 0,
            "claim_status": "ACTIVE",
        }
        return dict(self.claim)

    async def resume_namespace(self, ctx, *, expected_next_sequence_index, **kwargs):
        await asyncio.sleep(0)
        expected = {
            "namespace": self.namespace,
            **kwargs,
            "next_sequence_index": expected_next_sequence_index,
            "claim_status": "ACTIVE",
        }
        if self.claim != expected:
            raise NotFound("resume mismatch")
        return dict(self.claim)

    async def advance_namespace(self, ctx, *, run_nonce, expected_current, next_sequence_index):
        await asyncio.sleep(0)
        if (
            self.claim is None
            or self.claim["run_nonce"] != run_nonce
            or self.claim["next_sequence_index"] != expected_current
            or next_sequence_index != expected_current + 1
        ):
            raise RuntimeError("advance conflict")
        self.claim["next_sequence_index"] = next_sequence_index
        return dict(self.claim)

    async def advance_namespace_with_checkpoint(
        self,
        ctx,
        *,
        run_nonce,
        expected_current,
        next_sequence_index,
        checkpoint_payload,
        checkpoint_digest,
    ):
        claim = await self.advance_namespace(
            ctx,
            run_nonce=run_nonce,
            expected_current=expected_current,
            next_sequence_index=next_sequence_index,
        )
        checkpoint = {
            "checkpoint_id": "checkpoint-%d" % next_sequence_index,
            "org_id": ctx.org_id,
            "namespace": self.namespace,
            "owner_user_id": ctx.user_id,
            "run_nonce": run_nonce,
            "next_sequence_index": next_sequence_index,
            "checkpoint_schema": checkpoint_payload["schema"],
            "checkpoint_payload": dict(checkpoint_payload),
            "checkpoint_digest": checkpoint_digest,
            "created_at": NOW,
        }
        self.checkpoints[(run_nonce, next_sequence_index)] = checkpoint
        return claim, dict(checkpoint)

    async def load_latest_session_checkpoint(self, ctx, *, run_nonce):
        rows = [
            value
            for (candidate_nonce, _), value in self.checkpoints.items()
            if candidate_nonce == run_nonce
        ]
        if not rows:
            raise NotFound("session checkpoint not found")
        return dict(max(rows, key=lambda item: item["next_sequence_index"]))

    async def namespace_evidence(self, ctx):
        await asyncio.sleep(0)
        rows = tuple((name, self.counts[name]) for name in self.TABLES)
        return {
            "namespace": self.namespace,
            "row_counts": rows,
            "digest": canonical_hash({"namespace": self.namespace, "row_counts": rows}),
        }

    async def lifecycle_receipt_evidence(self, ctx):
        body = {
            "schema": "trimem/lifecycle-receipt-evidence/1.0",
            "namespace": self.namespace,
            "owner_user_id": ctx.user_id,
            "rows": list(self.lifecycle_receipts),
        }
        return {**body, "digest": canonical_hash(body)}

    async def append_lifecycle_bundle(self, ctx, bundle):
        await asyncio.sleep(0)
        if self.fail_append:
            raise RuntimeError("postgres transaction failed")
        self.events.append("postgres_commit")
        self.nodes.update(
            {
                node.node_id: node
                for node in (*self.receipt.index_nodes, *self.receipt.delete_nodes)
            }
        )
        self.outbox.update(
            {
                intent.intent_id: intent
                for intent in (*self.receipt.index_intents, *self.receipt.delete_intents)
            }
        )
        return self.receipt

    async def get_node(self, ctx, node_id):
        await asyncio.sleep(0)
        return self.nodes[node_id]

    async def get_index_outbox_intent(self, ctx, intent_id):
        await asyncio.sleep(0)
        return self.outbox[intent_id]

    async def list_index_outbox(self, ctx, *, status="PENDING", limit=100):
        await asyncio.sleep(0)
        return tuple(
            intent
            for intent in self.outbox.values()
            if intent.status == status
        )[:limit]

    async def mark_index_outbox_failed(
        self, ctx, *, intent_id, canonical_content_hash, error_code
    ):
        await asyncio.sleep(0)
        intent = self.outbox[intent_id]
        assert intent.canonical_content_hash == canonical_content_hash
        updated = replace(
            intent,
            attempts=intent.attempts + 1,
            last_error=error_code,
            updated_at=NOW,
        )
        self.outbox[intent_id] = updated
        return updated

    async def mark_index_outbox_indexed(
        self, ctx, *, intent_id, canonical_content_hash
    ):
        await asyncio.sleep(0)
        intent = self.outbox[intent_id]
        assert intent.canonical_content_hash == canonical_content_hash
        updated = replace(
            intent,
            status="INDEXED",
            attempts=intent.attempts + 1,
            last_error=None,
            updated_at=NOW,
            indexed_at=NOW,
        )
        self.outbox[intent_id] = updated
        return updated

    async def append_access_batch(
        self, ctx, events, *, operation_id=None, operation_scope=None
    ):
        assert operation_id and operation_scope["kind"] == "ACCESS"
        await asyncio.sleep(0)
        self.events.append("postgres_access_commit")
        return tuple(events)


class _FakeEngine:
    def __init__(self):
        self.disposed_on = None

    async def dispose(self):
        self.disposed_on = threading.get_ident()


def _session(tasks=(_Task("source"), _Task("target"))):
    namespace = benchmark_namespace("experiment-a", "credential_free_replay", "M0")
    events = []
    store = _FakeCanonicalStore(namespace, events=events)
    qdrant = _FakeQdrant(events)
    embedder = _Embedder()
    vector = QdrantVectorIndexV2(qdrant, 3, namespace=namespace)
    bridge = DedicatedAsyncLoop(name="trimem-unit-session")
    persistence = CanonicalLifecyclePersistence(
        store,
        vector,
        embedder,
        bridge,
        namespace=namespace,
    )
    session = BenchmarkArmSession(
        experiment_id="experiment-a",
        split="credential_free_replay",
        arm_id="M0",
        task_order=tasks,
        store=store,
        vector_index=vector,
        qdrant_client=qdrant,
        embedder=embedder,
        embedder_provenance=embedder.provenance(),
        bridge=bridge,
        persistence=persistence,
        lifecycle=object(),
        controller_factory=None,
        config_hash=_hash({"config": 1}),
        evaluation=False,
        run_nonce=UNIT_RUN_NONCE,
    )
    return session, store, qdrant, events


class _PreparedLifecycle:
    configuration_hash = _hash({"lifecycle": "prepared-unit"})

    def __init__(self, namespace):
        self.namespace = namespace
        self.prepared_task_times = {}
        self.pending_by_memory_id = {}

    def before_task(self, *, task, sequence_index):
        self.prepared_task_times.setdefault(
            task.task_id,
            {
                "sequence_index": sequence_index,
                "event_time": "2026-08-31T00:00:%02dZ" % sequence_index,
            },
        )

    def prepared_event_time(self, task):
        return self.prepared_task_times[task.task_id]["event_time"]

    def after_task(self, *, task, result):
        return None

    def checkpoint_state(self):
        payload = {
            "schema": "trimem/unit-prepared-lifecycle/1.0",
            "namespace": self.namespace,
            "prepared_task_times": self.prepared_task_times,
            "pending_by_memory_id": self.pending_by_memory_id,
        }
        return {"payload": payload, "digest": _hash(payload)}

    def restore_state(self, value):
        payload = value.get("payload")
        if (
            not isinstance(payload, dict)
            or value.get("digest") != _hash(payload)
            or payload.get("schema") != "trimem/unit-prepared-lifecycle/1.0"
            or payload.get("namespace") != self.namespace
        ):
            raise ValueError("bad prepared lifecycle checkpoint")
        self.prepared_task_times = {
            str(key): dict(row)
            for key, row in payload.get("prepared_task_times", {}).items()
        }
        self.pending_by_memory_id = {
            str(key): dict(row)
            for key, row in payload.get("pending_by_memory_id", {}).items()
        }


def _memory_session(store, qdrant, *, tasks, arm="M1", split="credential_free_replay"):
    namespace = benchmark_namespace("experiment-recovery", split, arm)
    assert store.namespace == namespace
    bridge = DedicatedAsyncLoop(name="trimem-receipt-recovery")
    embedder = _Embedder()
    vector = QdrantVectorIndexV2(qdrant, 3, namespace=namespace)
    persistence = CanonicalLifecyclePersistence(
        store, vector, embedder, bridge, namespace=namespace
    )
    lifecycle = _PreparedLifecycle(namespace)
    session = BenchmarkArmSession(
        experiment_id="experiment-recovery",
        split=split,
        arm_id=arm,
        task_order=tasks,
        store=store,
        vector_index=vector,
        qdrant_client=qdrant,
        embedder=embedder,
        embedder_provenance=embedder.provenance(),
        bridge=bridge,
        persistence=persistence,
        lifecycle=lifecycle,
        controller_factory=lambda **_: NoMemoryController(),
        config_hash=_hash({"config": "receipt-recovery", "arm": arm, "split": split}),
        evaluation=False,
        run_nonce="00000000-0000-4000-8000-000000000777",
    )
    return session


def _agent_proof(task, *, arm, lifecycle_state, state="DECOMPOSED", ledger=()):
    graph = ShortTermWorkingGraph(task.task_id, "repair exact parser behavior", task.repository)
    graph.add_subtask(
        SubtaskSpec(
            node_id="node-a",
            objective="repair exact parser behavior",
            operation="update parser branch",
        )
    )
    if state not in {"DECOMPOSED", "RUNNING"}:
        graph.activate("node-a")
        graph.complete_active(
            Evidence.capture(
                "tool_result",
                "parser behavior was repaired and verified",
                {"task_id": task.task_id, "resolved": True},
                supports_completion=True,
            )
        )
    rows = tuple(dict(row) for row in ledger)
    return RuntimeCheckpoint(
        run_id="proof-%s" % task.task_id,
        task_id=task.task_id,
        arm=arm,
        generation=1,
        next_step_no=1,
        state=state,
        active_node_id=None,
        graph_snapshot=graph.snapshot(),
        workspace_state={},
        injected_memory_ids=tuple(sorted(str(row["memory_id"]) for row in rows)),
        injected_bytes=sum(int(row["byte_count"]) for row in rows),
        injection_ledger=rows,
        tool_history=(),
        completed_call_ids=(),
        accounting={"calls": [], "tools": [], "graders": []},
        config_hashes={
            name: sha256_bytes(name.encode("utf-8"))
            for name in (
                "runtime", "task", "model", "memory_controller",
                "grader", "workspace", "lifecycle",
            )
        },
        evidence_event_hash="0" * 64,
        memory_controller_state={"mode": arm, "ledger": list(rows)},
        lifecycle_state=lifecycle_state,
        created_at=NOW,
    )


def _receipt_row(
    store,
    *,
    kind,
    task_id,
    active_node_ids,
    inserted,
    created_at=NOW,
):
    deltas = {
        table: {"inserted": 0, "updated": 0, "deleted": 0}
        for table in store.TABLES
    }
    for table, count in inserted.items():
        deltas[table]["inserted"] = count
    deltas["trimem_lifecycle_operation_receipts"]["inserted"] = 1
    return {
        "operation_id": str(uuid.uuid4()),
        "bundle_digest": _hash({"bundle": kind, "task": task_id}),
        "receipt_payload_digest": _hash({"receipt": kind, "task": task_id}),
        "index_node_ids": [],
        "index_intent_ids": [],
        "delete_node_ids": [],
        "delete_intent_ids": [],
        "access_event_ids": (
            [str(uuid.uuid4())] if kind == "ACCESS" else []
        ),
        "canonical_row_deltas": deltas,
        "operation_scope": {
            "kind": kind,
            "task_id": task_id,
            "active_node_ids": list(active_node_ids),
        },
        "created_at": created_at,
    }


def _append_receipts(store, *rows):
    store.lifecycle_receipts.extend(rows)
    for row in rows:
        for table, delta in row["canonical_row_deltas"].items():
            store.counts[table] += delta["inserted"] - delta["deleted"]


def test_dedicated_loop_reuses_one_thread_and_never_uses_per_call_runner():
    bridge = DedicatedAsyncLoop(name="trimem-thread-proof")

    async def thread_id():
        await asyncio.sleep(0)
        return threading.get_ident()

    try:
        assert bridge.call(thread_id()) == bridge.thread_id
        assert bridge.call(thread_id()) == bridge.thread_id
        source = inspect.getsource(DedicatedAsyncLoop)
        assert "asyncio.run(" not in source
        assert "run_coroutine_threadsafe" in source
    finally:
        bridge.close()


def test_namespace_is_exact_and_mixed_access_context_is_refused():
    assert benchmark_namespace("exp-23", "heldout", "M2") == "trimem:exp-23:heldout:M2"
    with pytest.raises(ValueError, match="one org/user"):
        session, *_ = _session((_Task("a", user_id="alice"), _Task("b", user_id="bob")))
        session.close()
    with pytest.raises(ValueError, match="unsupported benchmark split"):
        benchmark_namespace("exp", "default", "M2")


def test_session_freshness_order_cas_checkpoint_and_cross_process_restore():
    session, store, qdrant, _ = _session()
    restored = None
    try:
        evidence = session.assert_fresh()
        assert evidence["namespace"] == session.namespace
        assert all(
            row["points"] == 0
            for row in evidence["qdrant_before_initialization"]["collections"].values()
        )
        assert set(qdrant.collections) == {
            session._vector_index.private_collection,
            session._vector_index.shared_collection,
        }
        with pytest.raises(SessionStateError, match="frozen task order"):
            session.before_task(_Task("target"), 0)

        session.before_task(_Task("source"), 0)
        controller = session.controller_for(_Task("source"))
        assert controller is session.controller_for(_Task("source"))
        checkpoint = session.after_task_and_checkpoint(
            _Task("source"),
            {"task_id": "source", "arm": "M0", "resolved": True},
        )
        assert store.claim["next_sequence_index"] == 1
        assert checkpoint == session.checkpoint(1)

        tampered = {"payload": dict(checkpoint["payload"]), "digest": checkpoint["digest"]}
        tampered["payload"]["next_sequence_index"] = 2
        with pytest.raises(CheckpointTamperError, match="digest"):
            session.restore(tampered)

        wrong_run = {"payload": dict(checkpoint["payload"])}
        wrong_run["payload"]["run_nonce"] = (
            "00000000-0000-4000-8000-000000000002"
        )
        wrong_run["digest"] = _hash(wrong_run["payload"])
        with pytest.raises(CheckpointTamperError, match="run_nonce"):
            session.restore(wrong_run)

        # A second process/session can bind only the exact claim and evidence.
        vector = QdrantVectorIndexV2(qdrant, 3, namespace=session.namespace)
        bridge = DedicatedAsyncLoop(name="trimem-unit-restore")
        persistence = CanonicalLifecyclePersistence(
            store, vector, _Embedder(), bridge, namespace=session.namespace
        )
        restored = BenchmarkArmSession(
            experiment_id="experiment-a",
            split="credential_free_replay",
            arm_id="M0",
            task_order=(_Task("source"), _Task("target")),
            store=store,
            vector_index=vector,
            qdrant_client=qdrant,
            embedder=_Embedder(),
            embedder_provenance=_Embedder().provenance(),
            bridge=bridge,
            persistence=persistence,
            lifecycle=object(),
            controller_factory=None,
            config_hash=session.config_hash,
            evaluation=False,
            run_nonce=UNIT_RUN_NONCE,
        )
        assert restored.restore_latest_canonical_checkpoint() == checkpoint
        assert restored.run_nonce == UNIT_RUN_NONCE
        assert restored.next_sequence_index == 1
    finally:
        if restored is not None:
            restored.close()
        session.close()


def test_cursor_zero_claim_resumes_before_the_first_arm_checkpoint():
    session, store, qdrant, _ = _session(tasks=(_Task("source"),))
    resumed = None
    try:
        session.assert_fresh()
        nonce = session.run_nonce
        session.close()

        vector = QdrantVectorIndexV2(qdrant, 3, namespace=session.namespace)
        bridge = DedicatedAsyncLoop(name="trimem-unit-zero-cursor")
        persistence = CanonicalLifecyclePersistence(
            store, vector, _Embedder(), bridge, namespace=session.namespace
        )
        resumed = BenchmarkArmSession(
            experiment_id="experiment-a",
            split="credential_free_replay",
            arm_id="M0",
            task_order=(_Task("source"),),
            store=store,
            vector_index=vector,
            qdrant_client=qdrant,
            embedder=_Embedder(),
            embedder_provenance=_Embedder().provenance(),
            bridge=bridge,
            persistence=persistence,
            lifecycle=object(),
            controller_factory=None,
            config_hash=session.config_hash,
            evaluation=False,
            run_nonce=nonce,
        )
        assert resumed.resume_canonical_stream() is None
        assert resumed.task_cursor == 0
        resumed.before_task(_Task("source"), 0)
    finally:
        if resumed is not None:
            resumed.close()


def test_cursor_zero_resume_cannot_bypass_freshness_without_agent_checkpoint():
    session, store, qdrant, _ = _session(tasks=(_Task("source"),))
    resumed = None
    try:
        session.assert_fresh()
        collection = session._vector_index.private_collection
        qdrant.collections[collection]["points"]["unexpected"] = {
            "id": "unexpected",
            "payload": {"content_hash": "sha256:" + "1" * 64},
            "vector": [1.0, 0.0, 0.0],
        }
        session.close()

        vector = QdrantVectorIndexV2(qdrant, 3, namespace=session.namespace)
        bridge = DedicatedAsyncLoop(name="trimem-unit-zero-cursor-dirty")
        persistence = CanonicalLifecyclePersistence(
            store, vector, _Embedder(), bridge, namespace=session.namespace
        )
        resumed = BenchmarkArmSession(
            experiment_id="experiment-a",
            split="credential_free_replay",
            arm_id="M0",
            task_order=(_Task("source"),),
            store=store,
            vector_index=vector,
            qdrant_client=qdrant,
            embedder=_Embedder(),
            embedder_provenance=_Embedder().provenance(),
            bridge=bridge,
            persistence=persistence,
            lifecycle=object(),
            controller_factory=None,
            config_hash=session.config_hash,
            evaluation=False,
            run_nonce=session.run_nonce,
        )
        with pytest.raises(FreshnessViolation, match="without an agent checkpoint"):
            resumed.resume_canonical_stream()
    finally:
        if resumed is not None:
            resumed.close()
        session.close()


def test_task_order_hash_binds_public_payload_not_only_task_id():
    first, *_ = _session(tasks=(_Task("same", repository="owner/one"),))
    second, *_ = _session(tasks=(_Task("same", repository="owner/two"),))
    try:
        assert first.task_order_hash != second.task_order_hash
    finally:
        first.close()
        second.close()


def test_restore_rejects_same_count_qdrant_content_mutation():
    session, store, qdrant, _ = _session(tasks=(_Task("source"),))
    restored = None
    try:
        session.assert_fresh()
        collection = session._vector_index.private_collection
        qdrant.collections[collection]["points"]["point-a"] = {
            "id": "point-a",
            "payload": {"content_hash": "sha256:" + "1" * 64},
            "vector": [1.0, 0.0, 0.0],
        }
        session.before_task(_Task("source"), 0)
        session.controller_for(_Task("source"))
        session.after_task_and_checkpoint(
            _Task("source"),
            {"task_id": "source", "arm": "M0", "resolved": True},
        )

        qdrant.collections[collection]["points"]["point-a"]["vector"] = [0.0, 1.0, 0.0]
        vector = QdrantVectorIndexV2(qdrant, 3, namespace=session.namespace)
        bridge = DedicatedAsyncLoop(name="trimem-unit-qdrant-digest")
        persistence = CanonicalLifecyclePersistence(
            store, vector, _Embedder(), bridge, namespace=session.namespace
        )
        restored = BenchmarkArmSession(
            experiment_id="experiment-a",
            split="credential_free_replay",
            arm_id="M0",
            task_order=(_Task("source"),),
            store=store,
            vector_index=vector,
            qdrant_client=qdrant,
            embedder=_Embedder(),
            embedder_provenance=_Embedder().provenance(),
            bridge=bridge,
            persistence=persistence,
            lifecycle=object(),
            controller_factory=None,
            config_hash=session.config_hash,
            evaluation=False,
            run_nonce=session.run_nonce,
        )
        with pytest.raises(CheckpointTamperError, match="Qdrant namespace changed"):
            restored.restore_latest_canonical_checkpoint()
    finally:
        if restored is not None:
            restored.close()
        session.close()


def test_receipt_bound_access_crash_resume_restores_pre_call_task_time():
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(
        "experiment-recovery", "credential_free_replay", "M1"
    )
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    original = _memory_session(store, qdrant, tasks=tasks)
    rejected = None
    resumed = None
    try:
        original.assert_fresh()
        original.before_task(tasks[0], 0)
        original.controller_for(tasks[0])
        original.after_task_and_checkpoint(
            tasks[0], {"task_id": "source", "arm": "M1", "resolved": True}
        )
        original.before_task(tasks[1], 1)
        prepared = original.prepared_task_checkpoint(tasks[1])
        prepared_time = original.lifecycle.prepared_event_time(tasks[1])
        lifecycle_state = prepared["payload"]["lifecycle_state"]
        original.close()
        receipt = _receipt_row(
            store,
            kind="ACCESS",
            task_id="target",
            active_node_ids=["wrong-node"],
            inserted={"trimem_memory_access_events": 1},
        )
        _append_receipts(store, receipt)
        proof = _agent_proof(
            tasks[1], arm="M1", lifecycle_state=lifecycle_state
        )

        rejected = _memory_session(store, qdrant, tasks=tasks)
        with pytest.raises(CheckpointTamperError, match="resumable active node"):
            rejected.resume_canonical_stream(
                inflight_checkpoint=proof,
                prepared_task_checkpoint=prepared,
            )
        rejected.close()
        rejected = None

        receipt["operation_scope"]["active_node_ids"] = ["__TASK__"]
        resumed = _memory_session(store, qdrant, tasks=tasks)
        resumed.resume_canonical_stream(
            inflight_checkpoint=proof,
            prepared_task_checkpoint=prepared,
        )
        assert resumed.task_cursor == 1
        resumed.before_task(tasks[1], 1)
        assert resumed.lifecycle.prepared_event_time(tasks[1]) == prepared_time
        resumed.controller_for(tasks[1])
    finally:
        if rejected is not None:
            rejected.close()
        if resumed is not None:
            resumed.close()
        original.close()


def test_pre_agent_checkpoint_resume_restores_the_durable_task_time():
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(
        "experiment-recovery", "credential_free_replay", "M1"
    )
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    original = _memory_session(store, qdrant, tasks=tasks)
    resumed = None
    try:
        original.assert_fresh()
        original.before_task(tasks[0], 0)
        original.controller_for(tasks[0])
        original.after_task_and_checkpoint(
            tasks[0], {"task_id": "source", "arm": "M1", "resolved": True}
        )
        original.before_task(tasks[1], 1)
        prepared = original.prepared_task_checkpoint(tasks[1])
        original_time = original.lifecycle.prepared_event_time(tasks[1])
        original.close()

        resumed = _memory_session(store, qdrant, tasks=tasks)
        resumed.resume_canonical_stream(prepared_task_checkpoint=prepared)
        resumed.before_task(tasks[1], 1)
        assert resumed.lifecycle.prepared_event_time(tasks[1]) == original_time
        resumed.controller_for(tasks[1])
    finally:
        if resumed is not None:
            resumed.close()
        original.close()


def test_store_and_credit_receipts_require_exact_task_and_active_node_scope():
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(
        "experiment-recovery", "credential_free_replay", "M2"
    )
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    original = _memory_session(store, qdrant, tasks=tasks, arm="M2")
    rejected = None
    resumed = None
    try:
        original.assert_fresh()
        original.before_task(tasks[0], 0)
        original.controller_for(tasks[0])
        original.after_task_and_checkpoint(
            tasks[0], {"task_id": "source", "arm": "M2", "resolved": True}
        )
        original.before_task(tasks[1], 1)
        prepared = original.prepared_task_checkpoint(tasks[1])
        lifecycle_state = prepared["payload"]["lifecycle_state"]
        original.close()

        rows = (
            _receipt_row(
                store,
                kind="ACCESS",
                task_id="target",
                active_node_ids=["node-a"],
                inserted={"trimem_memory_access_events": 1},
                created_at="2026-08-31T00:00:01Z",
            ),
            _receipt_row(
                store,
                kind="LIFECYCLE_STORE",
                task_id="target",
                active_node_ids=[],
                inserted={"trimem_graphs": 1},
                created_at="2026-08-31T00:00:02Z",
            ),
            _receipt_row(
                store,
                kind="CREDIT",
                task_id="target",
                active_node_ids=["wrong-node"],
                inserted={"trimem_policy_transitions": 1},
                created_at="2026-08-31T00:00:03Z",
            ),
        )
        _append_receipts(store, *rows)
        ledger = ({
            "memory_id": "memory-a",
            "byte_count": 17,
            "active_node_id": "node-a",
            "namespace": namespace,
        },)
        proof = _agent_proof(
            tasks[1],
            arm="M2",
            lifecycle_state=lifecycle_state,
            state="LIFECYCLE_CREDITED",
            ledger=ledger,
        )

        rejected = _memory_session(store, qdrant, tasks=tasks, arm="M2")
        with pytest.raises(CheckpointTamperError, match="credit receipt scope"):
            rejected.resume_canonical_stream(
                inflight_checkpoint=proof,
                prepared_task_checkpoint=prepared,
            )
        rejected.close()
        rejected = None

        rows[-1]["operation_scope"]["active_node_ids"] = ["node-a"]
        resumed = _memory_session(store, qdrant, tasks=tasks, arm="M2")
        resumed.resume_canonical_stream(
            inflight_checkpoint=proof,
            prepared_task_checkpoint=prepared,
        )
        assert resumed.task_cursor == 1
    finally:
        if rejected is not None:
            rejected.close()
        if resumed is not None:
            resumed.close()
        original.close()


def test_finalizer_receipt_suffix_needs_explicit_development_recovery_proof():
    tasks = (_Task("source"),)
    namespace = benchmark_namespace("experiment-recovery", "development", "M2")
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    original = _memory_session(
        store, qdrant, tasks=tasks, arm="M2", split="development"
    )
    rejected = None
    resumed = None
    try:
        original.assert_fresh()
        original.before_task(tasks[0], 0)
        original.controller_for(tasks[0])
        original.lifecycle.pending_by_memory_id = {
            "memory-a": {"source_task_id": "source"}
        }
        original.after_task_and_checkpoint(
            tasks[0], {"task_id": "source", "arm": "M2", "resolved": True}
        )
        original.close()

        receipt = _receipt_row(
            store,
            kind="FINALIZE",
            task_id="source",
            active_node_ids=[],
            inserted={"trimem_policy_transitions": 1},
        )
        _append_receipts(store, receipt)

        rejected = _memory_session(
            store, qdrant, tasks=tasks, arm="M2", split="development"
        )
        with pytest.raises(CheckpointTamperError, match="no in-flight task proof"):
            rejected.resume_canonical_stream()
        rejected.close()
        rejected = None

        resumed = _memory_session(
            store, qdrant, tasks=tasks, arm="M2", split="development"
        )
        resumed.resume_canonical_stream(allow_development_finalization=True)
        assert resumed.task_cursor == 1
        assert resumed.lifecycle.pending_by_memory_id == {
            "memory-a": {"source_task_id": "source"}
        }
    finally:
        if rejected is not None:
            rejected.close()
        if resumed is not None:
            resumed.close()
        original.close()


def test_development_finalizer_is_canonically_checkpointed_and_resumable():
    class _FinalizingLifecycle:
        configuration_hash = _hash({"lifecycle": "finalizer-test"})

        def __init__(self):
            self.policy = DoubleDQNMemoryPolicy(
                DoubleDQNConfig(
                    FeatureSchema(1, 1, 1, 1),
                    hidden_dim=2,
                    replay_capacity=2,
                    batch_size=1,
                    min_replay_size=1,
                    seed=7,
                )
            )

        def after_task(self, *, task, result):
            return None

        def before_task(self, *, task, sequence_index):
            self.task_event_time = "2026-08-31T00:00:00Z"

        def prepared_event_time(self, task):
            return self.task_event_time

        def checkpoint_state(self):
            return {
                "schema": "trimem/unit-finalizer-lifecycle/1.0",
                "frozen": self.policy.frozen,
            }

        def restore_state(self, value):
            if value.get("schema") != "trimem/unit-finalizer-lifecycle/1.0":
                raise ValueError("bad lifecycle state")

        def finalize_development_and_freeze(self, *, completed_cursor, expected_cursor):
            assert completed_cursor == expected_cursor == 1
            frozen = self.policy.freeze_checkpoint()
            return {"payload": dict(frozen.payload), "digest": frozen.digest}

    namespace = benchmark_namespace("experiment-final", "development", "M2")
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    embedder = _Embedder()

    def build_session(lifecycle, bridge):
        vector = QdrantVectorIndexV2(qdrant, 3, namespace=namespace)
        persistence = CanonicalLifecyclePersistence(
            store, vector, embedder, bridge, namespace=namespace
        )
        return BenchmarkArmSession(
            experiment_id="experiment-final",
            split="development",
            arm_id="M2",
            task_order=(_Task("source"),),
            store=store,
            vector_index=vector,
            qdrant_client=qdrant,
            embedder=embedder,
            embedder_provenance=embedder.provenance(),
            bridge=bridge,
            persistence=persistence,
            lifecycle=lifecycle,
            controller_factory=lambda **_: NoMemoryController(),
            config_hash=_hash({"config": "finalizer"}),
            evaluation=False,
            run_nonce="00000000-0000-4000-8000-000000000123",
        )

    session = build_session(
        _FinalizingLifecycle(), DedicatedAsyncLoop(name="trimem-finalize-original")
    )
    restored = None
    try:
        session.assert_fresh()
        session.before_task(_Task("source"), 0)
        session.controller_for(_Task("source"))
        session.after_task_and_checkpoint(
            _Task("source"),
            {"task_id": "source", "arm": "M2", "resolved": True},
        )
        frozen = session.finalize_development(expected_resume_cursor=1)
        assert session.development_finalized is True
        assert session.task_cursor == 1
        assert session.next_sequence_index == 2
        assert store.claim["next_sequence_index"] == 2

        restored = build_session(
            _FinalizingLifecycle(), DedicatedAsyncLoop(name="trimem-finalize-restored")
        )
        restored.restore_latest_canonical_checkpoint()
        assert restored.development_finalized is True
        assert restored.task_cursor == 1
        assert restored.final_policy_checkpoint == frozen
        with pytest.raises(SessionStateError, match="idle ready"):
            restored.finalize_development(expected_resume_cursor=1)
    finally:
        if restored is not None:
            restored.close()
        session.close()


def test_lifecycle_commits_before_vector_upsert_and_pg_failure_never_calls_qdrant():
    namespace = benchmark_namespace("experiment-b", "credential_free_replay", "M2")
    events = []
    store = _FakeCanonicalStore(namespace, events=events)
    client = _FakeQdrant(events)
    embedder = _Embedder()
    vector = QdrantVectorIndexV2(client, 3, namespace=namespace)
    bridge = DedicatedAsyncLoop(name="trimem-persist-order")
    persistence = CanonicalLifecyclePersistence(
        store, vector, embedder, bridge, namespace=namespace
    )
    node = GraphNode(
        node_id="episode-a",
        graph_id="episode-graph-a",
        org_id="org-a",
        namespace=namespace,
        graph_kind=GraphKind.USER_EPISODIC,
        owner_user_id="alice",
        repository_id="repo-a",
        node_type=NodeType.EPISODE,
        temporal=TemporalMetadata(ingested_at=NOW, event_time=NOW),
        canonical_payload={"retrieval_text": "normalize a file extension"},
    )
    bundle = LifecycleAppendBundle(nodes=(node,), index_node_ids=(node.node_id,))
    store.receipt = AppendReceipt(
        namespace=namespace,
        graph_hashes=(),
        node_hashes=((node.node_id, node.content_hash),),
        index_nodes=(node,),
        index_intents=(_pending_intent(node),),
    )
    try:
        receipt = persistence.persist_bundle(AccessContext("org-a", "alice"), bundle)
        assert receipt["indexed"][0]["node_id"] == node.node_id
        assert events[0] == "postgres_commit"
        assert events.index("postgres_commit") < events.index("qdrant_upsert")
        point = next(iter(client.collections[vector.private_collection]["points"].values()))
        assert "retrieval_text" not in point["payload"]
        assert point["payload"]["node_id"] == node.node_id

        before = list(events)
        store.fail_append = True
        with pytest.raises(RuntimeError, match="postgres transaction failed"):
            persistence.persist_bundle(AccessContext("org-a", "alice"), bundle)
        assert events == before
    finally:
        bridge.close()


def test_indexed_lifecycle_receipt_replays_idempotent_qdrant_repair():
    namespace = benchmark_namespace(
        "experiment-indexed-replay", "credential_free_replay", "M2"
    )
    events = []
    store = _FakeCanonicalStore(namespace, events=events)
    client = _FakeQdrant(events)
    embedder = _Embedder()
    vector = QdrantVectorIndexV2(client, 3, namespace=namespace)
    bridge = DedicatedAsyncLoop(name="trimem-indexed-receipt-repair")
    persistence = CanonicalLifecyclePersistence(
        store, vector, embedder, bridge, namespace=namespace
    )
    node = GraphNode(
        node_id="episode-indexed-replay",
        graph_id="episode-graph-indexed-replay",
        org_id="org-a",
        namespace=namespace,
        graph_kind=GraphKind.USER_EPISODIC,
        owner_user_id="alice",
        repository_id="repo-a",
        node_type=NodeType.EPISODE,
        temporal=TemporalMetadata(ingested_at=NOW, event_time=NOW),
        canonical_payload={"retrieval_text": "repair an indexed receipt after crash"},
    )
    intent = _pending_intent(node)
    bundle = LifecycleAppendBundle(nodes=(node,), index_node_ids=(node.node_id,))
    store.receipt = AppendReceipt(
        namespace=namespace,
        graph_hashes=(),
        node_hashes=((node.node_id, node.content_hash),),
        index_nodes=(node,),
        index_intents=(intent,),
    )
    ctx = AccessContext("org-a", "alice")
    try:
        persistence.persist_bundle(ctx, bundle)
        indexed = store.outbox[intent.intent_id]
        assert indexed.status == "INDEXED"
        assert indexed.attempts == 1
        collection = vector.private_collection
        assert client.collections[collection]["points"]
        client.collections[collection]["points"].clear()
        assert client.collections[collection]["points"] == {}

        # Exact receipt replay can expose an already-INDEXED intent after the
        # PostgreSQL commit but before a local checkpoint.  The external point
        # must still be re-applied; only the PENDING -> INDEXED mark is skipped.
        store.receipt = replace(store.receipt, index_intents=(indexed,))
        persistence.persist_bundle(ctx, bundle)
        assert len(client.collections[collection]["points"]) == 1
        repaired = next(iter(client.collections[collection]["points"].values()))
        assert repaired["payload"]["node_id"] == node.node_id
        assert store.outbox[intent.intent_id].status == "INDEXED"
        assert store.outbox[intent.intent_id].attempts == 1
        assert events.count("qdrant_upsert") == 2
    finally:
        bridge.close()


def test_qdrant_failure_leaves_pending_intent_and_reconciliation_closes_it():
    namespace = benchmark_namespace("experiment-outbox", "credential_free_replay", "M2")
    events = []
    store = _FakeCanonicalStore(namespace, events=events)
    client = _FakeQdrant(events)
    embedder = _Embedder()
    vector = QdrantVectorIndexV2(client, 3, namespace=namespace)
    vector.ensure_ready()
    bridge = DedicatedAsyncLoop(name="trimem-outbox-reconcile")
    persistence = CanonicalLifecyclePersistence(
        store, vector, embedder, bridge, namespace=namespace
    )
    node = GraphNode(
        node_id="episode-outbox",
        graph_id="episode-graph-outbox",
        org_id="org-a",
        namespace=namespace,
        graph_kind=GraphKind.USER_EPISODIC,
        owner_user_id="alice",
        repository_id="repo-a",
        node_type=NodeType.EPISODE,
        temporal=TemporalMetadata(ingested_at=NOW, event_time=NOW),
        canonical_payload={"retrieval_text": "recover a durable vector write"},
    )
    intent = _pending_intent(node)
    store.receipt = AppendReceipt(
        namespace=namespace,
        graph_hashes=(),
        node_hashes=((node.node_id, node.content_hash),),
        index_nodes=(node,),
        index_intents=(intent,),
    )
    ctx = AccessContext("org-a", "alice")
    try:
        client.fail_upsert = True
        with pytest.raises(RuntimeError, match="simulated qdrant outage"):
            persistence.persist_bundle(
                ctx,
                LifecycleAppendBundle(nodes=(node,), index_node_ids=(node.node_id,)),
            )
        pending = store.outbox[intent.intent_id]
        assert pending.status == "PENDING"
        assert pending.attempts == 1
        assert pending.last_error == "qdrant:RuntimeError"
        assert events.index("postgres_commit") < events.index("qdrant_upsert")

        client.fail_upsert = False
        reconciled = persistence.reconcile_index_outbox(ctx)
        assert reconciled == ({
            "intent_id": intent.intent_id,
            "node_id": node.node_id,
            "content_hash": node.content_hash,
        },)
        closed = store.outbox[intent.intent_id]
        assert closed.status == "INDEXED"
        assert closed.attempts == 2
        assert closed.last_error is None
    finally:
        bridge.close()


def test_outbox_reconciliation_rejects_wrong_hash_before_qdrant():
    namespace = benchmark_namespace("experiment-corrupt", "credential_free_replay", "M2")
    events = []
    store = _FakeCanonicalStore(namespace, events=events)
    client = _FakeQdrant(events)
    vector = QdrantVectorIndexV2(client, 3, namespace=namespace)
    vector.ensure_ready()
    bridge = DedicatedAsyncLoop(name="trimem-outbox-corrupt")
    persistence = CanonicalLifecyclePersistence(
        store, vector, _Embedder(), bridge, namespace=namespace
    )
    node = GraphNode(
        node_id="episode-corrupt",
        graph_id="episode-graph-corrupt",
        org_id="org-a",
        namespace=namespace,
        graph_kind=GraphKind.USER_EPISODIC,
        owner_user_id="alice",
        node_type=NodeType.EPISODE,
        temporal=TemporalMetadata(ingested_at=NOW, event_time=NOW),
        canonical_payload={"retrieval_text": "do not index corrupt metadata"},
    )
    intent = replace(
        _pending_intent(node), canonical_content_hash="sha256:" + "f" * 64
    )
    store.nodes[node.node_id] = node
    store.outbox[intent.intent_id] = intent
    try:
        before = events.count("qdrant_upsert")
        with pytest.raises(ProductionRuntimeError, match="canonical_content_hash"):
            persistence.reconcile_index_outbox(AccessContext("org-a", "alice"))
        assert events.count("qdrant_upsert") == before
        pending = store.outbox[intent.intent_id]
        assert pending.status == "PENDING"
        assert pending.last_error == "reconcile:ProductionRuntimeError"
    finally:
        bridge.close()


def test_archived_delete_intent_removes_active_qdrant_point_and_closes():
    namespace = benchmark_namespace("experiment-delete", "credential_free_replay", "M2")
    events = []
    store = _FakeCanonicalStore(namespace, events=events)
    client = _FakeQdrant(events)
    vector = QdrantVectorIndexV2(client, 3, namespace=namespace)
    vector.ensure_ready()
    bridge = DedicatedAsyncLoop(name="trimem-outbox-delete")
    persistence = CanonicalLifecyclePersistence(
        store, vector, _Embedder(), bridge, namespace=namespace
    )
    active = GraphNode(
        node_id="episode-delete",
        graph_id="episode-graph-delete",
        org_id="org-a",
        namespace=namespace,
        graph_kind=GraphKind.USER_EPISODIC,
        owner_user_id="alice",
        node_type=NodeType.EPISODE,
        temporal=TemporalMetadata(ingested_at=NOW, event_time=NOW),
        canonical_payload={"retrieval_text": "remove archived episode"},
    )
    archived = active.archived("2026-09-01T00:00:01Z", "episodic_fifo_capacity")
    intent = _pending_intent(
        archived,
        "00000000-0000-4000-8000-000000000100",
        operation="DELETE",
        prior_content_hash=active.content_hash,
    )
    store.receipt = AppendReceipt(
        namespace=namespace,
        graph_hashes=(),
        node_hashes=((archived.node_id, archived.content_hash),),
        index_nodes=(),
        delete_nodes=(archived,),
        delete_intents=(intent,),
        archived_nodes=(archived,),
    )
    try:
        persistence._index_canonical_node(active)
        collection = vector.private_collection
        assert client.collections[collection]["points"]
        receipt = persistence.persist_bundle(
            AccessContext("org-a", "alice"), LifecycleAppendBundle()
        )
        assert receipt["deleted"][0]["node_id"] == active.node_id
        assert client.collections[collection]["points"] == {}
        assert store.outbox[intent.intent_id].status == "INDEXED"
        assert "qdrant_delete" in events
    finally:
        bridge.close()


def test_factory_injection_builds_nondefault_physical_backends_and_closes_on_loop():
    engine = _FakeEngine()
    client = _FakeQdrant()
    embedder = _Embedder()
    session = open_benchmark_arm(
        database_url="postgresql+asyncpg://unit.invalid/trimem",
        qdrant_url="http://unit.invalid:6333",
        experiment_id="factory-exp",
        split="credential_free_replay",
        arm_id="M0",
        task_order=(_Task("one"),),
        dqn_checkpoint_path=None,
        embedder_lock={
            "model_id": "credential-free-embedder",
            "revision": "frozen-test-revision",
            "dimensions": 3,
        },
        evaluation=False,
        engine_factory=lambda url: engine,
        qdrant_client_factory=lambda url: client,
        embedder=embedder,
    )
    loop_thread = session._bridge.thread_id
    assert session.namespace == "trimem:factory-exp:credential_free_replay:M0"
    assert session.canonical_backend == "postgresql"
    assert session.vector_backend == "qdrant"
    assert session.arm_id == "M0"
    assert str(uuid.UUID(session.run_nonce)) == session.run_nonce
    assert session.lifecycle is not None
    session.close()
    assert client.closed is True
    assert engine.disposed_on == loop_thread


def test_factory_configuration_hash_binds_backend_endpoints_without_credentials():
    embedder = _Embedder()

    def build(database_url, qdrant_url):
        return open_benchmark_arm(
            database_url=database_url,
            qdrant_url=qdrant_url,
            experiment_id="factory-endpoint-binding",
            split="credential_free_replay",
            arm_id="M0",
            task_order=(_Task("one"),),
            dqn_checkpoint_path=None,
            embedder_lock={
                "model_id": "credential-free-embedder",
                "revision": "frozen-test-revision",
                "dimensions": 3,
            },
            evaluation=False,
            engine_factory=lambda url: _FakeEngine(),
            qdrant_client_factory=lambda url: _FakeQdrant(),
            embedder=embedder,
        )

    first = build(
        "postgresql+asyncpg://user:secret@db-one.invalid/trimem",
        "http://token-one@qdrant.invalid:6333",
    )
    credentials_only = build(
        "postgresql+asyncpg://other:rotated@db-one.invalid/trimem",
        "http://token-two@qdrant.invalid:6333",
    )
    other_database = build(
        "postgresql+asyncpg://user:secret@db-two.invalid/trimem",
        "http://token-one@qdrant.invalid:6333",
    )
    try:
        assert first.config_hash == credentials_only.config_hash
        assert first.config_hash != other_database.config_hash
    finally:
        first.close()
        credentials_only.close()
        other_database.close()


def test_factory_rejects_product_in_memory_backend_and_non_postgres_url():
    embedder = _Embedder()
    common = dict(
        qdrant_url="http://unit.invalid:6333",
        experiment_id="factory-exp",
        split="credential_free_replay",
        arm_id="M0",
        task_order=(_Task("one"),),
        dqn_checkpoint_path=None,
        embedder_lock={
            "model_id": "credential-free-embedder",
            "revision": "frozen-test-revision",
            "dimensions": 3,
        },
        evaluation=False,
        qdrant_client_factory=lambda url: _FakeQdrant(),
        embedder=embedder,
    )
    with pytest.raises(ProductionDependencyError, match="PostgreSQL"):
        open_benchmark_arm(database_url="sqlite:///:memory:", **common)
    with pytest.raises(ProductionDependencyError, match="in-memory"):
        open_benchmark_arm(
            database_url="postgresql+asyncpg://unit.invalid/trimem",
            engine_factory=lambda url: InMemoryTriMemStore(),
            **common,
        )


def test_m2_never_silently_falls_back_to_a_nonproduction_lifecycle():
    engine = _FakeEngine()
    embedder = _Embedder()
    with pytest.raises(ProductionDependencyError, match="lifecycle_factory"):
        open_benchmark_arm(
            database_url="postgresql+asyncpg://unit.invalid/trimem",
            qdrant_url="http://unit.invalid:6333",
            experiment_id="factory-exp",
            split="credential_free_replay",
            arm_id="M2",
            task_order=(_Task("one"),),
            dqn_checkpoint_path=None,
            embedder_lock={
                "model_id": "credential-free-embedder",
                "revision": "frozen-test-revision",
                "dimensions": 3,
            },
            evaluation=False,
            engine_factory=lambda url: engine,
            qdrant_client_factory=lambda url: _FakeQdrant(),
            embedder=embedder,
        )


def test_m1_default_is_frozen_canonical_v03_reader_with_audited_injections():
    engine = _FakeEngine()
    embedder = _Embedder()
    session = open_benchmark_arm(
        database_url="postgresql+asyncpg://unit.invalid/trimem",
        qdrant_url="http://unit.invalid:6333",
        experiment_id="factory-m1",
        split="credential_free_replay",
        arm_id="M1",
        task_order=(_Task("one"),),
        dqn_checkpoint_path=None,
        embedder_lock={
            "model_id": "credential-free-embedder",
            "revision": "frozen-test-revision",
            "dimensions": 3,
        },
        evaluation=False,
        engine_factory=lambda url: engine,
        qdrant_client_factory=lambda url: _FakeQdrant(),
        embedder=embedder,
    )
    try:
        async def resolve_identity(ctx, *, repository_slug, task_id):
            return {
                "repository_id": "00000000-0000-4000-8000-000000000001",
                "solve_job_id": "00000000-0000-4000-8000-000000000002",
                "repository_slug": repository_slug,
                "task_id": task_id,
            }

        session._store.resolve_task_identity = resolve_identity
        session._state = "READY"
        session.before_task(_Task("one"), 0)
        controller = session.controller_for(_Task("one"))
        assert isinstance(controller, CurrentV03MemoryController)
        assert controller.implementation_manifest["search_path"].endswith(
            "validated_search.validated_search"
        )
        assert controller.implementation_manifest["injection_path"].endswith(
            "injection.plan_injection"
        )
        assert type(session.lifecycle).__name__ == "PostgresV03ExperienceLifecycle"
    finally:
        session.close()


def test_m1_bound_stream_identity_is_shared_by_storage_and_reader():
    engine = _FakeEngine()
    embedder = _Embedder()
    repository_id = "00000000-0000-4000-8000-000000000021"
    solve_job_id = "00000000-0000-4000-8000-000000000022"
    resolver_calls = []

    def exact_stream_identity(task):
        resolver_calls.append(task.task_id)
        return {
            "repository_id": repository_id,
            "solve_job_id": solve_job_id,
        }

    session = open_benchmark_arm(
        database_url="postgresql+asyncpg://unit.invalid/trimem",
        qdrant_url="http://unit.invalid:6333",
        experiment_id="factory-m1-exact-stream",
        split="credential_free_replay",
        arm_id="M1",
        task_order=(_Task("one"),),
        dqn_checkpoint_path=None,
        embedder_lock={
            "model_id": "credential-free-embedder",
            "revision": "frozen-test-revision",
            "dimensions": 3,
        },
        evaluation=False,
        engine_factory=lambda url: engine,
        qdrant_client_factory=lambda url: _FakeQdrant(),
        embedder=embedder,
        lifecycle_factory=production_v03_lifecycle_factory(
            identity_resolver=exact_stream_identity
        ),
    )
    try:
        async def ambiguous_database_lookup(*args, **kwargs):
            raise AssertionError("M1 must not fall back to an ambiguous solve-job query")

        session._store.resolve_task_identity = ambiguous_database_lookup
        session._state = "READY"
        task = _Task("one")
        session.before_task(task, 0)
        controller = session.controller_for(task)
        assert isinstance(controller, CurrentV03MemoryController)
        assert controller.implementation_manifest["canonical_tables"][0] == "private_episodes"
        assert session.lifecycle.identity_resolver is exact_stream_identity
        assert resolver_calls == ["one"]
    finally:
        session.close()


def test_m2_default_controller_is_postgres_qdrant_and_audits_before_exposure():
    engine = _FakeEngine()
    embedder = _Embedder()
    class _Lifecycle:
        configuration_hash = _hash({"lifecycle": "unit-m2"})
        retrieval_config = {
            "min_confidence": 0.72,
            "min_margin": 0.08,
            "episode_complete_threshold": 0.8,
            "max_episodic_per_active_node": 1,
            "max_semantic_per_active_node": 1,
            "max_task_injections": 3,
            "context_budget_bytes": 4096,
            "embedding_dimensions": 3,
            "embedding_weight": 0.6,
            "lexical_weight": 0.4,
            "ppr_damping": 0.85,
            "ppr_iterations": 20,
        }

        def identity_resolver(self, task):
            return {"repository_id": "00000000-0000-4000-8000-000000000001"}

        def before_task(self, *, task, sequence_index):
            self.task_event_time = "2026-08-31T00:00:00Z"

        def prepared_event_time(self, task):
            return self.task_event_time

    session = open_benchmark_arm(
        database_url="postgresql+asyncpg://unit.invalid/trimem",
        qdrant_url="http://unit.invalid:6333",
        experiment_id="factory-m2",
        split="credential_free_replay",
        arm_id="M2",
        task_order=(_Task("one"),),
        dqn_checkpoint_path=None,
        embedder_lock={
            "model_id": "credential-free-embedder",
            "revision": "frozen-test-revision",
            "dimensions": 3,
        },
        evaluation=False,
        engine_factory=lambda url: engine,
        qdrant_client_factory=lambda url: _FakeQdrant(),
        embedder=embedder,
        lifecycle_factory=lambda **kwargs: _Lifecycle(),
    )
    try:
        # The fake engine deliberately has no SQL surface.  Freshness itself is
        # covered with the production-shaped canonical store above; here we
        # isolate construction of the default M2 controller composition.
        session._state = "READY"
        session.before_task(_Task("one"), 0)
        controller = session.controller_for(_Task("one"))
        assert isinstance(controller, ActiveNodeTriMemController)
        assert isinstance(controller.retriever.store, SyncPostgresQdrantRetrievalStore)
        assert controller.retriever.injection_auditor.persistence is session.persistence
        assert (
            controller.retriever.store._store.excluded_source_task_id
            == "one"
        )
    finally:
        session.close()
