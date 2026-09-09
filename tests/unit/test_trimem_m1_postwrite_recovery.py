"""Fail-closed recovery checks for M1's live-v0.3 atomic retention pair."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from enterprise_memory.service.durable import (
    episode_id_for_job,
    persist_private_episode_candidate,
    sha as durable_sha,
)
from enterprise_memory.trimem.agent_runtime import NoMemoryController
from enterprise_memory.trimem.lifecycle import LifecycleError
from enterprise_memory.trimem.production_runtime import (
    BenchmarkArmSession,
    CanonicalLifecyclePersistence,
    CheckpointTamperError,
    DedicatedAsyncLoop,
    benchmark_namespace,
)
from enterprise_memory.trimem.production_v03_lifecycle import (
    LIVE_V03_IMPLEMENTATION_HASH,
    LiveV03Runtime,
    PostgresV03ExperienceLifecycle,
)
from enterprise_memory.trimem.vector_index import QdrantVectorIndexV2

from test_trimem_production_runtime import (
    NOW,
    _Embedder,
    _FakeCanonicalStore,
    _FakeQdrant,
    _Task,
    _agent_proof,
    _hash,
)


EXPERIMENT = "experiment-m1-postwrite"
SPLIT = "credential_free_replay"
ARM = "M1"
RUN_NONCE = "00000000-0000-4000-8000-000000000991"
REPOSITORY_ID = "11111111-1111-4111-8111-111111111111"
SOLVE_JOB_ID = "22222222-2222-4222-8222-222222222222"


class _LiveV03CrashProbe:
    """Transparent old-table probe shared by a crashed and resumed process."""

    implementation_hash = LIVE_V03_IMPLEMENTATION_HASH

    def __init__(self, namespace):
        self.namespace = namespace
        self.owner_rows = {}
        self.outbox_rows = []
        self.retain_calls = 0

    def retention_descriptor(self, **kwargs):  # pragma: no cover - injected boundary
        raise AssertionError("descriptor is injected at the EXTRACTED boundary")

    @staticmethod
    def _episode_row(descriptor):
        return {
            "episode_id": descriptor["episode_id"],
            "repository_id": descriptor["repository_id"],
            "task_id": None,
            "source_commit": None,
            "canonical_task_id": descriptor["task_id"],
            "canonical_source_commit": descriptor["source_commit"],
            "content_hash": descriptor["content_hash"],
            "canonical_hash": _hash(descriptor["canonical"]),
            "state": "success",
        }

    @staticmethod
    def _outbox_row(descriptor):
        outbox = descriptor["outbox"]
        return {
            "event_type": outbox["event_type"],
            "aggregate_type": outbox["aggregate_type"],
            "aggregate_id": outbox["aggregate_id"],
            "aggregate_version": outbox["aggregate_version"],
            "payload": deepcopy(outbox["payload"]),
            "status": "PENDING",
            "attempts": 0,
            "max_attempts": 5,
            "lease_owner": None,
            "lease_expires_at": None,
            "error_detail_sanitized": None,
            "processed_at": None,
        }

    def _pair_status(self, descriptor):
        row = self.owner_rows.get(descriptor["episode_id"])
        events = [
            item for item in self.outbox_rows
            if item.get("aggregate_id") == descriptor["episode_id"]
        ]
        if row is None and not events:
            return "ABSENT"
        if row != self._episode_row(descriptor) or events != [
            self._outbox_row(descriptor)
        ]:
            raise LifecycleError("v0.3 retention is not one exact atomic pair")
        return "EXACT_PENDING_APPEND"

    def retain_episode(self, descriptor):
        status = self._pair_status(descriptor)
        if status == "ABSENT":
            self.owner_rows[descriptor["episode_id"]] = self._episode_row(descriptor)
            self.outbox_rows.append(self._outbox_row(descriptor))
        if self._pair_status(descriptor) != "EXACT_PENDING_APPEND":  # pragma: no cover
            raise LifecycleError("v0.3 atomic append is incomplete")
        self.retain_calls += 1
        body = {
            "schema": "trimem/live-v03-retention-evidence/2.0",
            "namespace": self.namespace,
            "episode_id": descriptor["episode_id"],
            "atomic_pair_digest": _hash({
                "episode": self._episode_row(descriptor),
                "outbox": self._outbox_row(descriptor),
            }),
        }
        return {**body, "digest": _hash(body)}

    def verify_pending_retention(self, descriptor):
        return self._pair_status(descriptor)

    def recall_plan(self, **kwargs):  # pragma: no cover - outside recovery proof
        raise AssertionError("recall is outside this recovery proof")

    def verify_audit(self, **kwargs):
        return None

    def verify_audit_digest(self, **kwargs):
        return None

    def state_evidence(self, *, org_id, user_id, episode_ids=()):
        body = {
            "schema": "trimem/live-v03-canonical-state/2.0",
            "namespace": self.namespace,
            "org_id": org_id,
            "user_id": user_id,
            "stream_episode_ids": list(sorted(episode_ids)),
            "rows": [deepcopy(self.owner_rows[key]) for key in sorted(self.owner_rows)],
            "outbox_rows": sorted(
                [
                    deepcopy(row) for row in self.outbox_rows
                    if row.get("event_type") == "CONTRACT_CANDIDATE"
                    and row.get("aggregate_type") == "private_episode"
                    and row.get("payload") == {"job_id": SOLVE_JOB_ID}
                ],
                key=lambda row: (
                    row["aggregate_id"], row["event_type"],
                    row["aggregate_type"], row["aggregate_version"],
                ),
            ),
        }
        return {**body, "digest": _hash(body)}

    def verify_state(self, evidence, *, pending_descriptor=None):
        body = {key: value for key, value in evidence.items() if key != "digest"}
        if (
            evidence.get("schema") != "trimem/live-v03-canonical-state/2.0"
            or evidence.get("namespace") != self.namespace
            or evidence.get("digest") != _hash(body)
        ):
            raise LifecycleError("v0.3 probe state digest mismatch")
        observed = self.state_evidence(
            org_id=evidence["org_id"],
            user_id=evidence["user_id"],
            episode_ids=tuple(evidence.get("stream_episode_ids", ())),
        )
        if pending_descriptor is None:
            if observed != dict(evidence):
                raise LifecycleError("v0.3 canonical state changed after checkpoint")
            return "EXACT_STATE"
        pair_status = self._pair_status(pending_descriptor)
        expected_body = deepcopy(body)
        expected_body["rows"] = sorted(
            [*expected_body.get("rows", ()), self._episode_row(pending_descriptor)],
            key=lambda row: row["episode_id"],
        )
        expected_body["outbox_rows"] = sorted(
            [
                *expected_body.get("outbox_rows", ()),
                self._outbox_row(pending_descriptor),
            ],
            key=lambda row: (
                row["aggregate_id"], row["event_type"],
                row["aggregate_type"], row["aggregate_version"],
            ),
        )
        expected = {**expected_body, "digest": _hash(expected_body)}
        if observed == dict(evidence) and pair_status == "ABSENT":
            return "ABSENT"
        if observed == expected and pair_status == "EXACT_PENDING_APPEND":
            return "EXACT_PENDING_APPEND"
        raise LifecycleError("v0.3 state is neither base nor the exact atomic pair")


def _session(store, qdrant, runtime, tasks):
    bridge = DedicatedAsyncLoop(name="trimem-m1-postwrite-recovery")
    embedder = _Embedder()
    vector = QdrantVectorIndexV2(qdrant, 3, namespace=store.namespace)
    persistence = CanonicalLifecyclePersistence(
        store, vector, embedder, bridge, namespace=store.namespace
    )
    lifecycle = PostgresV03ExperienceLifecycle(
        runtime,
        namespace=store.namespace,
        identity_resolver=lambda task: {
            "repository_id": REPOSITORY_ID,
            "solve_job_id": SOLVE_JOB_ID,
        },
        clock=lambda: NOW,
    )
    return BenchmarkArmSession(
        experiment_id=EXPERIMENT,
        split=SPLIT,
        arm_id=ARM,
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
        config_hash=_hash({"config": "m1-postwrite-recovery"}),
        evaluation=False,
        run_nonce=RUN_NONCE,
    )


def _descriptor(session, task):
    canonical = {
        "task_id": task.task_id,
        "repo_id": REPOSITORY_ID,
        "commit": "fixture-commit",
        "outcome": "success",
        "injected_memory_ids": [],
    }
    episode_id = episode_id_for_job(SOLVE_JOB_ID)
    body = {
        "schema": "trimem/live-v03-retention-descriptor/2.0",
        "namespace": session.namespace,
        "org_id": task.org_id,
        "user_id": task.user_id,
        "episode_id": episode_id,
        "solve_job_id": SOLVE_JOB_ID,
        "repository_id": REPOSITORY_ID,
        "task_id": task.task_id,
        "source_commit": "fixture-commit",
        "content_hash": "sha256:" + durable_sha(
            json.dumps(canonical, sort_keys=True)
        )[:32],
        "canonical": canonical,
        "event_time": NOW,
        "outbox": {
            "event_type": "CONTRACT_CANDIDATE",
            "aggregate_type": "private_episode",
            "aggregate_id": episode_id,
            "aggregate_version": 1,
            "payload": {"job_id": SOLVE_JOB_ID},
        },
    }
    return {**body, "digest": _hash(body)}


def _seal_inflight(session, task, descriptor):
    session.lifecycle.pending_retention = deepcopy(descriptor)
    return _agent_proof(
        task,
        arm=ARM,
        lifecycle_state=session.lifecycle.checkpoint_state(),
        state="EXTRACTED",
    )


def _prepare_cursor(session, tasks, cursor):
    session.assert_fresh()
    if cursor == 1:
        session.before_task(tasks[0], 0)
        session.controller_for(tasks[0])
        session.after_task_and_checkpoint(
            tasks[0], {"task_id": tasks[0].task_id, "arm": ARM, "resolved": True}
        )
    task = tasks[cursor]
    session.before_task(task, cursor)
    prepared = session.prepared_task_checkpoint(task) if cursor else None
    return task, prepared


def _append_pair(runtime, descriptor):
    runtime.owner_rows[descriptor["episode_id"]] = runtime._episode_row(descriptor)
    runtime.outbox_rows.append(runtime._outbox_row(descriptor))


def _qdrant_snapshot(qdrant):
    return deepcopy(qdrant.collections)


class _ForgedExternalWaiver:
    def verify_inflight_external_state(self, **kwargs):
        body = {
            "schema": "trimem/live-v03-inflight-external-proof/1.0",
            "namespace": kwargs.get("namespace", "unused"),
            "verified": True,
        }
        return {**body, "proof_digest": _hash(body)}


def _non_m1_session(arm):
    tasks = (_Task("source"),)
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, arm)
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    bridge = DedicatedAsyncLoop(name="trimem-non-m1-waiver-guard")
    embedder = _Embedder()
    vector = QdrantVectorIndexV2(qdrant, 3, namespace=namespace)
    persistence = CanonicalLifecyclePersistence(
        store, vector, embedder, bridge, namespace=namespace
    )
    session = BenchmarkArmSession(
        experiment_id=EXPERIMENT,
        split=SPLIT,
        arm_id=arm,
        task_order=tasks,
        store=store,
        vector_index=vector,
        qdrant_client=qdrant,
        embedder=embedder,
        embedder_provenance=embedder.provenance(),
        bridge=bridge,
        persistence=persistence,
        lifecycle=_ForgedExternalWaiver(),
        controller_factory=lambda **_: NoMemoryController(),
        config_hash=_hash({"config": "non-m1-waiver", "arm": arm}),
        evaluation=False,
        run_nonce=RUN_NONCE,
    )
    return session, tasks[0]


def test_connection_helper_preserves_baseline_episode_and_outbox_tuple(monkeypatch):
    canonical = {
        "task_id": "task-a",
        "repo_id": REPOSITORY_ID,
        "commit": "fixture-commit",
        "outcome": "success",
        "injected_memory_ids": [],
    }

    class _Connection:
        def __init__(self):
            self.calls = []

        async def execute(self, statement, params):
            self.calls.append((str(statement), deepcopy(params)))

    outbox_calls = []

    async def _publish(connection, *args):
        outbox_calls.append((connection, *deepcopy(args)))

    monkeypatch.setattr(
        "enterprise_memory.persistence.postgres.publish_outbox", _publish
    )
    connection = _Connection()
    episode_id, content_hash = asyncio.run(persist_private_episode_candidate(
        connection,
        org_id="org-a",
        user_id="user-a",
        repo_id=REPOSITORY_ID,
        job_id=SOLVE_JOB_ID,
        episode_canonical=canonical,
    ))
    assert episode_id == episode_id_for_job(SOLVE_JOB_ID)
    assert content_hash == "sha256:" + durable_sha(
        json.dumps(canonical, sort_keys=True)
    )[:32]
    assert len(connection.calls) == 1
    sql, params = connection.calls[0]
    assert "private_episodes" in sql
    assert "task_id" not in sql and "source_commit" not in sql
    assert params == {
        "i": episode_id,
        "o": "org-a",
        "u": "user-a",
        "r": REPOSITORY_ID,
        "j": json.dumps(canonical),
        "h": content_hash,
    }
    assert outbox_calls == [(
        connection,
        "org-a",
        "CONTRACT_CANDIDATE",
        "private_episode",
        episode_id,
        1,
        {"job_id": SOLVE_JOB_ID},
    )]


def test_live_runtime_descriptor_seals_outbox_without_projection_or_write_api():
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, ARM)
    vector = QdrantVectorIndexV2(_FakeQdrant(), 3, namespace=namespace)

    class _Bridge:
        def call(self, value):  # pragma: no cover - descriptor is synchronous
            return value

    class _NeverEmbed:
        def embed(self, text):  # pragma: no cover - fresh retention must not embed
            raise AssertionError("fresh M1 retention cannot embed")

    runtime = LiveV03Runtime(
        canonical_store=SimpleNamespace(_engine=object()),
        vector_index=vector,
        embedder=_NeverEmbed(),
        persistence=SimpleNamespace(bridge=_Bridge()),
        namespace=namespace,
    )
    task = SimpleNamespace(
        task_id="source",
        org_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        user_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        commit="fixture-commit",
    )
    descriptor = runtime.retention_descriptor(
        task=task,
        identity={"repository_id": REPOSITORY_ID, "solve_job_id": SOLVE_JOB_ID},
        injections=(),
        event_time=NOW,
    )
    assert runtime._validated_descriptor(descriptor) == descriptor
    assert descriptor["outbox"] == {
        "event_type": "CONTRACT_CANDIDATE",
        "aggregate_type": "private_episode",
        "aggregate_id": episode_id_for_job(SOLVE_JOB_ID),
        "aggregate_version": 1,
        "payload": {"job_id": SOLVE_JOB_ID},
    }
    assert not ({"collection_name", "point_id", "point_digest"} & set(descriptor))
    assert not hasattr(runtime.index, "upsert")


@pytest.mark.parametrize("arm", ["M0", "M2"])
def test_non_m1_arm_cannot_install_receiptless_external_state_waiver(arm):
    session, task = _non_m1_session(arm)
    try:
        raw = _agent_proof(
            task, arm=arm, lifecycle_state={}, state="EXTRACTED"
        )
        proof = session._current_inflight_proof(raw, task_cursor=0)
        with pytest.raises(CheckpointTamperError, match="restricted to M1"):
            session._verify_inflight_external_state(
                prior_canonical={},
                current_canonical={},
                prior_qdrant={},
                current_qdrant={},
                prior_receipts={},
                current_receipts={},
                proof=proof,
            )
    finally:
        session.close()


@pytest.mark.parametrize("cursor", [0, 1])
def test_m1_absent_pair_resumes_and_stores_once_without_qdrant_write(cursor):
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, ARM)
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    runtime = _LiveV03CrashProbe(namespace)
    original = _session(store, qdrant, runtime, tasks)
    resumed = None
    try:
        task, prepared = _prepare_cursor(original, tasks, cursor)
        descriptor = _descriptor(original, task)
        proof = _seal_inflight(original, task, descriptor)
        before_qdrant = _qdrant_snapshot(qdrant)
        original.close()

        resumed = _session(store, qdrant, runtime, tasks)
        resumed.resume_canonical_stream(
            inflight_checkpoint=proof, prepared_task_checkpoint=prepared
        )
        assert resumed.lifecycle.pending_retention == descriptor
        assert resumed._inflight_external_state_proof is None
        stored = resumed.lifecycle.store_experience(
            task, object(), object(), object(), ()
        )
        assert stored["memory_id"] == descriptor["episode_id"]
        assert stored["retained_records"] == 1
        assert stored["pending_candidate_outbox_events"] == 1
        assert stored["fresh_solve_immediate_carryover"] == 0
        assert runtime.retain_calls == 1
        assert runtime.verify_pending_retention(descriptor) == "EXACT_PENDING_APPEND"
        assert len(runtime.owner_rows) == 1 and len(runtime.outbox_rows) == 1
        assert _qdrant_snapshot(qdrant) == before_qdrant
    finally:
        if resumed is not None:
            resumed.close()
        original.close()


@pytest.mark.parametrize("cursor", [0, 1])
def test_m1_exact_atomic_pair_resumes_idempotently_without_qdrant_write(cursor):
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, ARM)
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    runtime = _LiveV03CrashProbe(namespace)
    original = _session(store, qdrant, runtime, tasks)
    resumed = None
    try:
        task, prepared = _prepare_cursor(original, tasks, cursor)
        descriptor = _descriptor(original, task)
        proof = _seal_inflight(original, task, descriptor)
        _append_pair(runtime, descriptor)
        before_qdrant = _qdrant_snapshot(qdrant)
        original.close()

        resumed = _session(store, qdrant, runtime, tasks)
        resumed.resume_canonical_stream(
            inflight_checkpoint=proof, prepared_task_checkpoint=prepared
        )
        assert resumed.lifecycle.pending_retention == descriptor
        assert resumed._inflight_external_state_proof is None
        stored = resumed.lifecycle.store_experience(
            task, object(), object(), object(), ()
        )
        assert stored["retained_records"] == 1
        assert stored["pending_candidate_outbox_events"] == 1
        assert stored["fresh_solve_immediate_carryover"] == 0
        assert runtime.retain_calls == 1
        assert len(runtime.owner_rows) == 1 and len(runtime.outbox_rows) == 1
        assert _qdrant_snapshot(qdrant) == before_qdrant
    finally:
        if resumed is not None:
            resumed.close()
        original.close()


@pytest.mark.parametrize("cursor", [0, 1])
@pytest.mark.parametrize("partial", ["row_only", "outbox_only"])
def test_m1_partial_atomic_pair_fails_closed(cursor, partial):
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, ARM)
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    runtime = _LiveV03CrashProbe(namespace)
    original = _session(store, qdrant, runtime, tasks)
    rejected = None
    try:
        task, prepared = _prepare_cursor(original, tasks, cursor)
        descriptor = _descriptor(original, task)
        proof = _seal_inflight(original, task, descriptor)
        if partial == "row_only":
            runtime.owner_rows[descriptor["episode_id"]] = runtime._episode_row(descriptor)
        else:
            runtime.outbox_rows.append(runtime._outbox_row(descriptor))
        original.close()

        rejected = _session(store, qdrant, runtime, tasks)
        with pytest.raises(LifecycleError, match="atomic pair"):
            rejected.resume_canonical_stream(
                inflight_checkpoint=proof, prepared_task_checkpoint=prepared
            )
        assert rejected._state == "BROKEN"
    finally:
        if rejected is not None:
            rejected.close()
        original.close()


@pytest.mark.parametrize("cursor", [0, 1])
@pytest.mark.parametrize(
    "tamper",
    [
        "episode_hash",
        "episode_db_task_id",
        "outbox_event_type",
        "outbox_aggregate_type",
        "outbox_aggregate_id",
        "outbox_version",
        "outbox_payload",
        "outbox_status",
        "duplicate_outbox",
        "extra_orphan_outbox",
        "extra_owner_pair",
        "qdrant",
        "trimem_rows",
        "receipts",
    ],
)
def test_m1_rejects_tampered_extra_or_external_state(cursor, tamper):
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, ARM)
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    runtime = _LiveV03CrashProbe(namespace)
    original = _session(store, qdrant, runtime, tasks)
    rejected = None
    try:
        task, prepared = _prepare_cursor(original, tasks, cursor)
        descriptor = _descriptor(original, task)
        proof = _seal_inflight(original, task, descriptor)
        _append_pair(runtime, descriptor)

        if tamper == "episode_hash":
            runtime.owner_rows[descriptor["episode_id"]]["content_hash"] = "sha256:" + "b" * 32
        elif tamper == "episode_db_task_id":
            runtime.owner_rows[descriptor["episode_id"]]["task_id"] = task.task_id
        elif tamper == "outbox_event_type":
            runtime.outbox_rows[0]["event_type"] = "PRIVATE_INDEX"
        elif tamper == "outbox_aggregate_type":
            runtime.outbox_rows[0]["aggregate_type"] = "other"
        elif tamper == "outbox_aggregate_id":
            runtime.outbox_rows[0]["aggregate_id"] = "99999999-9999-4999-8999-999999999999"
        elif tamper == "outbox_version":
            runtime.outbox_rows[0]["aggregate_version"] = 2
        elif tamper == "outbox_payload":
            runtime.outbox_rows[0]["payload"] = {"job_id": "wrong"}
        elif tamper == "outbox_status":
            runtime.outbox_rows[0]["status"] = "PROCESSED"
        elif tamper == "duplicate_outbox":
            duplicate = runtime._outbox_row(descriptor)
            duplicate["aggregate_version"] = 2
            runtime.outbox_rows.append(duplicate)
        elif tamper == "extra_orphan_outbox":
            unrelated = runtime._outbox_row(descriptor)
            unrelated["aggregate_id"] = "77777777-7777-4777-8777-777777777777"
            runtime.outbox_rows.append(unrelated)
        elif tamper == "extra_owner_pair":
            extra = deepcopy(descriptor)
            extra["episode_id"] = "88888888-8888-4888-8888-888888888888"
            extra["task_id"] = "unexpected-task"
            extra["canonical"] = {**extra["canonical"], "task_id": "unexpected-task"}
            extra["outbox"] = {
                **extra["outbox"], "aggregate_id": extra["episode_id"]
            }
            runtime.owner_rows[extra["episode_id"]] = runtime._episode_row(extra)
            runtime.outbox_rows.append(runtime._outbox_row(extra))
        elif tamper == "qdrant":
            collection = original._vector_index.private_collection
            qdrant.collections[collection]["points"]["unexpected"] = {
                "id": "unexpected", "payload": {}, "vector": [1.0, 0.0, 0.0]
            }
        elif tamper == "trimem_rows":
            store.counts["trimem_graphs"] = 1
        else:
            store.lifecycle_receipts.append({"unexpected": True})
        original.close()

        rejected = _session(store, qdrant, runtime, tasks)
        with pytest.raises((LifecycleError, CheckpointTamperError)):
            rejected.resume_canonical_stream(
                inflight_checkpoint=proof, prepared_task_checkpoint=prepared
            )
        assert rejected._state == "BROKEN"
        assert rejected._inflight_external_state_proof is None
    finally:
        if rejected is not None:
            rejected.close()
        original.close()


@pytest.mark.parametrize("cursor", [0, 1])
def test_m1_stored_pair_resumes_without_repeating_retention(cursor):
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, ARM)
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    runtime = _LiveV03CrashProbe(namespace)
    original = _session(store, qdrant, runtime, tasks)
    resumed = None
    try:
        task, prepared = _prepare_cursor(original, tasks, cursor)
        descriptor = _descriptor(original, task)
        original.lifecycle.pending_retention = deepcopy(descriptor)
        original.lifecycle.store_experience(task, object(), object(), object(), ())
        assert runtime.retain_calls == 1
        proof = _agent_proof(
            task,
            arm=ARM,
            lifecycle_state=original.lifecycle.checkpoint_state(),
            state="LIFECYCLE_STORED",
        )
        before_qdrant = _qdrant_snapshot(qdrant)
        original.close()

        resumed = _session(store, qdrant, runtime, tasks)
        resumed.resume_canonical_stream(
            inflight_checkpoint=proof, prepared_task_checkpoint=prepared
        )
        assert runtime.retain_calls == 1
        assert resumed.lifecycle.pending_retention is None
        assert resumed.lifecycle.stored_task_ids[task.task_id] == descriptor["episode_id"]
        assert resumed._inflight_external_state_proof is None
        assert _qdrant_snapshot(qdrant) == before_qdrant
        replay = resumed.lifecycle.store_experience(
            task, object(), object(), object(), ()
        )
        assert replay["idempotent_replay"] is True
        assert replay["retained_records"] == 0
        assert replay["pending_candidate_outbox_events"] == 0
        assert replay["fresh_solve_immediate_carryover"] == 0
        assert runtime.retain_calls == 1
    finally:
        if resumed is not None:
            resumed.close()
        original.close()


def test_m1_pending_descriptor_is_bound_to_checkpoint_task():
    tasks = (_Task("source"), _Task("target"))
    namespace = benchmark_namespace(EXPERIMENT, SPLIT, ARM)
    store = _FakeCanonicalStore(namespace)
    qdrant = _FakeQdrant()
    runtime = _LiveV03CrashProbe(namespace)
    original = _session(store, qdrant, runtime, tasks)
    rejected = None
    try:
        original.assert_fresh()
        original.before_task(tasks[0], 0)
        descriptor = _descriptor(original, tasks[1])
        proof = _seal_inflight(original, tasks[0], descriptor)
        _append_pair(runtime, descriptor)
        original.close()

        rejected = _session(store, qdrant, runtime, tasks)
        with pytest.raises(LifecycleError, match="task binding"):
            rejected.resume_canonical_stream(inflight_checkpoint=proof)
        assert rejected._state == "BROKEN"
    finally:
        if rejected is not None:
            rejected.close()
        original.close()
