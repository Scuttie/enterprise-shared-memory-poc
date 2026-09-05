"""Credential-free TriMem E2E against real PostgreSQL and pinned Qdrant.

CI applies Alembic head before invoking this file with both environment
variables set.  A local invocation without those explicit endpoints skips;
the dedicated no-skip CI wrapper turns any such skip into a failure.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest

from enterprise_memory.trimem.accounting import (
    RawEvidenceLedger,
    canonical_bytes,
    sha256_bytes,
)
from enterprise_memory.trimem.agent_runtime import (
    CodingTask,
    ExperienceExtraction,
    TriMemAgentRuntime,
)
from enterprise_memory.trimem.arms import (
    ActiveNodeTriMemController,
    CurrentV03MemoryController,
)
from enterprise_memory.indexing.canonical_loaders import load_private_episode
from enterprise_memory.indexing.models import PRIVATE
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex
from enterprise_memory.service.durable import persist_private_episode
from enterprise_memory.trimem.benchmark_seed import seed_benchmark_identities
from enterprise_memory.trimem.checkpoint import FileCheckpointStore
from enterprise_memory.trimem.credential_free import (
    ScenarioReplayModel,
    source_task,
    target_task,
)
from enterprise_memory.trimem.gateway import ReplayModelGateway
from enterprise_memory.trimem.grader import GradeResult, ReplayGraderGateway
from enterprise_memory.trimem.postgres_retrieval import (
    AsyncPostgresQdrantRetrievalStore,
    PostgresInjectionAuditor,
    SyncPostgresQdrantRetrievalStore,
    production_v03_controller_factory,
)
from enterprise_memory.trimem.postgres_store import (
    LifecycleAppendBundle,
    PostgresTriMemStore,
)
from enterprise_memory.trimem.production_runtime import (
    CanonicalLifecyclePersistence,
    DedicatedAsyncLoop,
    benchmark_namespace,
    open_benchmark_arm,
)
from enterprise_memory.trimem.production_lifecycle import (
    production_dqn_lifecycle_factory,
)
from enterprise_memory.trimem.production_v03_lifecycle import (
    production_v03_lifecycle_factory,
)
from enterprise_memory.trimem.retrieval import RetrievalConfig, TriMemoryRetriever
from enterprise_memory.trimem.runtime_lock import RuntimeLock
from enterprise_memory.trimem.schema import (
    AccessContext,
    EdgeType,
    GraphEdge,
    GraphKind,
    GraphNode,
    NodeType,
    SemanticStrength,
    SemanticStrengthRecord,
    TemporalMetadata,
    UserSemanticGraph,
)
from enterprise_memory.trimem.store import NotFound
from enterprise_memory.trimem.vector_index import (
    Qdrant112ClientAdapter,
    QdrantVectorIndexV2,
)
from enterprise_memory.trimem.working_graph import ShortTermWorkingGraph, SubtaskSpec


DATABASE_ENV = "TRIMEM_TEST_DATABASE_URL"
ADMIN_DATABASE_ENV = "TRIMEM_TEST_ADMIN_DATABASE_URL"
QDRANT_ENV = "TRIMEM_TEST_QDRANT_URL"
NOW = "2026-09-01T00:00:00Z"
ROOT = Path(__file__).resolve().parents[2]


class _LockedEncoder:
    dimensions = 8

    def embed(self, text):
        seed = str(text).casefold()
        if "normalize" in seed or "suffix" in seed:
            return (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        return (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def provenance(self):
        return {
            "model_id": "trimem-real-service-fixture-encoder",
            "revision": "sha256:" + sha256_bytes(b"trimem-real-service-fixture-encoder-v1"),
            "dimensions": self.dimensions,
            "normalized": True,
            "production": True,
            "credential_free": True,
        }


class _M2CredentialFreeEncoder:
    """384-dimension fixture explicitly barred from DEV/HELDOUT execution."""

    dimensions = 384
    model_id = "trimem-real-service-fixture-encoder-v1"
    revision = "sha256:" + sha256_bytes(
        b"trimem-real-service-fixture-encoder-v1"
    )

    def embed(self, text):
        if not isinstance(text, str) or not text:
            raise ValueError("fixture encoder requires non-empty text")
        # One normalized direction deliberately makes the service test about
        # canonical/ACL/PPR composition rather than an external model download.
        return (1.0,) + (0.0,) * (self.dimensions - 1)

    def provenance(self):
        return {
            "model_id": self.model_id,
            "revision": self.revision,
            "dimensions": self.dimensions,
            "normalized": True,
            "production": False,
            "credential_free_fixture": True,
        }


def _temporal() -> TemporalMetadata:
    return TemporalMetadata(
        ingested_at=NOW,
        event_time=NOW,
        source_available_at=NOW,
        last_verified_at=NOW,
    )


def _memory_payload(label: str) -> dict[str, object]:
    return {
        "retrieval_text": label,
        "execution_view": (
            '{"kind":"user_semantic","operation":"normalize suffix before comparison"}'
        ),
        "version": "fixture-commit",
        "version_valid": True,
        "stale": False,
        "servable": True,
        "verified": True,
        "source_outcome": "passed",
        "quality": 1.0,
        "completeness": 1.0,
        "coverage": ["operation", "precondition", "verification"],
        "provenance": {"source_task_id": "real-source"},
    }


def _uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.UUID("236e0ac0-f8c1-4edc-b011-e6544995c279"), seed))


async def _runtime_role_evidence(engine) -> dict[str, object]:
    from sqlalchemy import text

    async with engine.connect() as connection:
        row = (
            await connection.execute(
                text(
                    "SELECT current_user AS role_name,rolbypassrls "
                    "FROM pg_roles WHERE rolname=current_user"
                )
            )
        ).mappings().one()
    return {"role_name": str(row["role_name"]), "rolbypassrls": row["rolbypassrls"]}


def test_real_postgres_qdrant_outbox_canonical_ppr_and_access():
    database_url = os.getenv(DATABASE_ENV)
    admin_database_url = os.getenv(ADMIN_DATABASE_ENV)
    qdrant_url = os.getenv(QDRANT_ENV)
    if not database_url or not admin_database_url or not qdrant_url:
        pytest.skip("real TriMem service endpoints are not configured")

    from qdrant_client import QdrantClient
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    run = uuid.uuid4().hex
    org_id = _uuid("org|" + run)
    user_id = _uuid("user|" + run)
    repository_id = _uuid("repository|" + run)
    namespace = "trimem:real-services:%s:M2" % run
    ctx = AccessContext(org_id, user_id)
    engine = create_async_engine(database_url, future=True)
    admin_engine = create_async_engine(admin_database_url, future=True)
    raw_qdrant = QdrantClient(url=qdrant_url, timeout=15)
    vector = QdrantVectorIndexV2(
        Qdrant112ClientAdapter(raw_qdrant),
        _LockedEncoder.dimensions,
        namespace=namespace,
    )
    bridge = DedicatedAsyncLoop(name="trimem-real-services-e2e")
    store = PostgresTriMemStore(engine, namespace=namespace)
    persistence = CanonicalLifecyclePersistence(
        store,
        vector,
        _LockedEncoder(),
        bridge,
        namespace=namespace,
    )

    async def seed_identity() -> None:
        async with admin_engine.begin() as connection:
            await connection.execute(text(
                "INSERT INTO organisations(id,external_key) VALUES(:id,:key)"
            ), {"id": org_id, "key": "trimem-real-" + run})
            await connection.execute(text(
                "INSERT INTO users(id,org_id,external_subject) VALUES(:id,:org,:subject)"
            ), {"id": user_id, "org": org_id, "subject": "alice-" + run})
            await connection.execute(text(
                "INSERT INTO repositories(id,org_id,external_repo_id) "
                "VALUES(:id,:org,:repo)"
            ), {"id": repository_id, "org": org_id, "repo": "owner/repo-" + run})

    try:
        bridge.call(seed_identity())
        assert bridge.call(_runtime_role_evidence(engine)) == {
            "role_name": "api_service",
            "rolbypassrls": False,
        }
        graph = UserSemanticGraph(
            graph_id=_uuid("graph|" + run),
            org_id=org_id,
            namespace=namespace,
            owner_user_id=user_id,
            repository_id=repository_id,
            temporal=_temporal(),
        )
        rule = GraphNode(
            node_id=_uuid("rule|" + run),
            graph_id=graph.graph_id,
            org_id=org_id,
            namespace=namespace,
            graph_kind=GraphKind.USER_SEMANTIC,
            owner_user_id=user_id,
            repository_id=repository_id,
            node_type=NodeType.SEMANTIC_RULE,
            canonical_payload=_memory_payload("normalize suffix before allowlist comparison"),
            temporal=_temporal(),
        )
        operation = GraphNode(
            node_id=_uuid("operation|" + run),
            graph_id=graph.graph_id,
            org_id=org_id,
            namespace=namespace,
            graph_kind=GraphKind.USER_SEMANTIC,
            owner_user_id=user_id,
            repository_id=repository_id,
            node_type=NodeType.OPERATION,
            canonical_payload={"operation": "normalize suffix", "retrieval_text": "normalize suffix"},
            temporal=_temporal(),
        )
        edge = GraphEdge(
            edge_id=_uuid("edge|" + run),
            graph_id=graph.graph_id,
            org_id=org_id,
            namespace=namespace,
            graph_kind=GraphKind.USER_SEMANTIC,
            owner_user_id=user_id,
            edge_type=EdgeType.APPLIED,
            source_node_id=rule.node_id,
            target_node_id=operation.node_id,
            metadata={"weight": 1.4},
            temporal=_temporal(),
        )
        strength = SemanticStrengthRecord(
            strength_id=_uuid("strength|" + run),
            graph_id=graph.graph_id,
            semantic_node_id=rule.node_id,
            org_id=org_id,
            namespace=namespace,
            graph_kind=GraphKind.USER_SEMANTIC,
            owner_user_id=user_id,
            strength=SemanticStrength(support=1, recent_verification=1),
            updated_at=NOW,
        )
        bundle = LifecycleAppendBundle(
            operation_id=_uuid("operation-receipt|" + run),
            operation_scope={
                "kind": "LIFECYCLE_STORE",
                "task_id": "real-source",
                "active_node_ids": [],
            },
            graphs=(graph,),
            nodes=(rule, operation),
            edges=(edge,),
            strengths=(strength,),
            index_node_ids=(rule.node_id,),
        )
        first = persistence.persist_bundle(ctx, bundle)
        replay = persistence.persist_bundle(ctx, bundle)
        assert replay["receipt_digest"] == first["receipt_digest"]
        assert replay["canonical_row_deltas"] == first["canonical_row_deltas"]
        assert first["canonical_row_deltas"]["trimem_graphs"]["inserted"] == 1
        assert (
            first["canonical_row_deltas"][
                "trimem_lifecycle_operation_receipts"
            ]["inserted"]
            == 1
        )

        pending_graph = UserSemanticGraph(
            graph_id=_uuid("pending-graph|" + run),
            org_id=org_id,
            namespace=namespace,
            owner_user_id=user_id,
            repository_id=repository_id,
            temporal=_temporal(),
        )
        pending_node = GraphNode(
            node_id=_uuid("pending-node|" + run),
            graph_id=pending_graph.graph_id,
            org_id=org_id,
            namespace=namespace,
            graph_kind=GraphKind.USER_SEMANTIC,
            owner_user_id=user_id,
            repository_id=repository_id,
            node_type=NodeType.SEMANTIC_RULE,
            canonical_payload=_memory_payload("retry outbox sentinel"),
            temporal=_temporal(),
        )
        pending_receipt = bridge.call(store.append_lifecycle_bundle(
            ctx,
            LifecycleAppendBundle(
                operation_id=_uuid("pending-operation|" + run),
                operation_scope={
                    "kind": "LIFECYCLE_STORE",
                    "task_id": "outbox-reconcile-source",
                    "active_node_ids": [],
                },
                graphs=(pending_graph,),
                nodes=(pending_node,),
                index_node_ids=(pending_node.node_id,),
            ),
        ))
        assert pending_receipt.index_intents[0].status == "PENDING"
        assert (
            pending_receipt.canonical_row_deltas[
                "trimem_vector_index_outbox"
            ]["inserted"]
            == 1
        )
        reconciled = persistence.reconcile_index_outbox(ctx)
        assert {row["node_id"] for row in reconciled} == {pending_node.node_id}

        async_store = AsyncPostgresQdrantRetrievalStore(
            store,
            vector,
            _LockedEncoder(),
            repository_id=repository_id,
            repository_alias="owner/repo",
        )
        sync_store = SyncPostgresQdrantRetrievalStore(async_store, bridge)
        auditor = PostgresInjectionAuditor(
            persistence,
            ctx=ctx,
            namespace=namespace,
            task_id="real-target",
            clock=lambda: NOW,
        )
        retriever = TriMemoryRetriever(
            sync_store,
            RetrievalConfig(
                min_confidence=0.0,
                min_margin=0.0,
                embedding_dimensions=_LockedEncoder.dimensions,
                ppr_iterations=16,
            ),
            embedder=_LockedEncoder(),
            injection_auditor=auditor,
        )
        task = CodingTask(
            task_id="real-target",
            org_id=org_id,
            user_id=user_id,
            repository="owner/repo",
            commit="fixture-target",
            instruction="Normalize a suffix before allowlist comparison.",
            files={},
            editable_paths=(),
        )
        working = ShortTermWorkingGraph(task.task_id, task.instruction, task.repository)
        working.add_subtask(SubtaskSpec(
            node_id="normalize-target",
            objective="normalize suffix before allowlist comparison",
            operation="normalize suffix",
            preconditions=("allowlist is case insensitive",),
            tests=("uppercase suffix",),
        ))
        working.activate("normalize-target")
        decision = ActiveNodeTriMemController(
            retriever, task_id=task.task_id
        ).recall(working, task)
        assert decision.injections
        assert any(item.memory_id == rule.node_id for item in decision.injections)
        access = bridge.call(store.list_access_events(ctx, graph_id=graph.graph_id))
        assert any(item.node_id == rule.node_id for item in access)
        receipt_evidence = bridge.call(store.lifecycle_receipt_evidence(ctx))
        access_receipts = [
            row for row in receipt_evidence["rows"]
            if row["operation_scope"]["kind"] == "ACCESS"
        ]
        assert len(access_receipts) == 1
        assert (
            access_receipts[0]["canonical_row_deltas"]
            ["trimem_memory_access_events"]["inserted"]
            == len(decision.injections)
        )
        rows = bridge.call(store.load_retrieval_rows(
            ctx,
            kind=GraphKind.USER_SEMANTIC,
            repository_id=repository_id,
        ))
        assert edge.edge_id in {item.edge_id for item in rows.edges}
        assert rule.content_hash in {item.content_hash for item in rows.nodes}
    finally:
        for collection in (vector.private_collection, vector.shared_collection):
            try:
                if raw_qdrant.collection_exists(collection):
                    raw_qdrant.delete_collection(collection_name=collection)
            except Exception:
                pass
        bridge.call(engine.dispose())
        bridge.call(admin_engine.dispose())
        bridge.close()
        raw_qdrant.close()


def test_real_services_compose_production_m2_source_to_later_target(tmp_path):
    """Run the common agent over the production PG/Qdrant lifecycle wiring."""

    database_url = os.getenv(DATABASE_ENV)
    admin_database_url = os.getenv(ADMIN_DATABASE_ENV)
    qdrant_url = os.getenv(QDRANT_ENV)
    if not database_url or not admin_database_url or not qdrant_url:
        pytest.skip("real TriMem service endpoints are not configured")

    run = uuid.uuid4().hex
    org_id = _uuid("full-org|" + run)
    user_id = _uuid("full-user|" + run)
    source = replace(
        source_task(),
        org_id=org_id,
        user_id=user_id,
        repository="fixture/source-loaders",
    )
    target = replace(
        target_task(),
        org_id=org_id,
        user_id=user_id,
        repository="fixture/target-configs",
    )
    tasks = (source, target)
    repository_ids = {
        task.task_id: _uuid("full-repository|%s|%s" % (run, task.repository))
        for task in tasks
    }
    solve_job_ids = {
        task.task_id: _uuid("full-solve-job|%s|%s" % (run, task.task_id))
        for task in tasks
    }

    encoder = _M2CredentialFreeEncoder()
    manifest = json.loads(
        (ROOT / "configs/trimem_v1/m2_policy.json").read_text(encoding="utf-8")
    )
    manifest["double_dqn"]["feature_encoder"] = {
        "model_id": encoder.model_id,
        "revision": encoder.revision,
        "projection": "NONE",
    }
    manifest_hash = "sha256:" + sha256_bytes(canonical_bytes(manifest))

    def identity_resolver(task):
        return {
            "repository_id": repository_ids[str(task.task_id)],
            "solve_job_id": solve_job_ids[str(task.task_id)],
        }

    experiment_id = "real-full-" + run
    seed_evidence = seed_benchmark_identities(
        admin_database_url=admin_database_url,
        experiment_id=experiment_id,
        stream_id="M2",
        tasks=tasks,
        identity_resolver=identity_resolver,
    )
    assert seed_evidence["admin_bypassrls"] is True
    assert len(seed_evidence["rows"]) == len(tasks)
    assert "postgres:postgres" not in json.dumps(seed_evidence)

    lifecycle_factory = production_dqn_lifecycle_factory(
        identity_resolver,
        policy_manifest=manifest,
        expected_policy_manifest_hash=manifest_hash,
    )
    session = open_benchmark_arm(
        database_url=database_url,
        qdrant_url=qdrant_url,
        experiment_id=experiment_id,
        split="credential_free_replay",
        arm_id="M2",
        task_order=tasks,
        dqn_checkpoint_path=None,
        embedder_lock={
            "model_id": encoder.model_id,
            "revision": encoder.revision,
            "dimension": encoder.dimensions,
        },
        evaluation=False,
        embedder=encoder,
        lifecycle_factory=lifecycle_factory,
        run_nonce=_uuid("full-run-nonce|" + run),
    )
    model_scenario = ScenarioReplayModel()
    model = ReplayModelGateway(model_scenario)

    def run_task(task, index, evaluator):
        session.before_task(task, index)
        controller = session.controller_for(task)
        task_root = tmp_path / ("%02d-%s" % (index, task.task_id))
        runtime = TriMemAgentRuntime(
            runtime_lock=RuntimeLock(),
            model_gateway=model,
            grader_gateway=ReplayGraderGateway(
                evaluator,
                fixture_digest=sha256_bytes(
                    (task.task_id + ":real-service-replay-grader").encode()
                ),
            ),
            memory_controller=controller,
            evidence=RawEvidenceLedger(task_root / "evidence"),
            checkpoint_store=FileCheckpointStore(task_root / "checkpoints"),
            lifecycle=session.lifecycle,
        )
        result = runtime.run(
            task,
            arm="M2",
            run_id="real-service-%s" % task.task_id,
        )
        session.after_task_and_checkpoint(task, result)
        return result

    try:
        freshness = session.assert_fresh()
        assert session.run_coroutine(_runtime_role_evidence(session._engine)) == {
            "role_name": "api_service",
            "rolbypassrls": False,
        }
        assert freshness["namespace"] == benchmark_namespace(
            experiment_id, "credential_free_replay", "M2"
        )
        source_result = run_task(
            source,
            0,
            lambda files: (
                "casefold" in files["src/loader.py"],
                "source replay passed",
                "",
            ),
        )
        source_storage = source_result.lifecycle_result["storage"]
        assert source_storage["storage_action"] == "MOVE_TO_SEMANTIC_CANDIDATE"
        assert source_storage["memory_kind"] == "USER_SEMANTIC"
        assert source_storage["retained_records"] == 2
        source_memory_id = source_storage["memory_id"]

        target_result = run_task(
            target,
            1,
            lambda files: (
                "casefold" in files["src/config.py"]
                and "('.yaml', '.yml')" in files["src/config.py"],
                "target replay passed",
                "",
            ),
        )
        assert source_result.resolved is True
        assert target_result.resolved is True
        assert model_scenario.target_memory_seen is True
        assert source_memory_id in {
            str(row["memory_id"]) for row in target_result.injections
        }
        assert {str(row["kind"]) for row in target_result.injections} == {
            "USER_SEMANTIC"
        }
        assert target_result.lifecycle_result["credit"]["credited"] == 1
        assert session.task_cursor == 2
        assert session.latest_checkpoint_envelope is not None
        for result in (source_result, target_result):
            summary = result.accounting["summary"]
            assert summary["paid_model_calls"] == 0
            assert summary["official_grader_runs"] == 0
            assert summary["grader_containers"] == 0

        ctx = AccessContext(org_id, user_id)
        receipts = session.persistence.lifecycle_receipt_evidence(ctx)
        assert {
            row["operation_scope"]["task_id"] for row in receipts["rows"]
        } >= {source.task_id, target.task_id}
        assert any(
            row["operation_scope"]["kind"] == "ACCESS"
            and row["operation_scope"]["task_id"] == target.task_id
            for row in receipts["rows"]
        )
        semantic_rows = session.run_coroutine(
            session._store.load_retrieval_rows(
                ctx,
                kind=GraphKind.USER_SEMANTIC,
                repository_id=repository_ids[target.task_id],
            )
        )
        source_rule = next(
            node for node in semantic_rows.nodes if node.node_id == source_memory_id
        )
        assert source_rule.repository_id is None
        assert semantic_rows.edges
    finally:
        raw_client = getattr(session._qdrant_client, "raw_client", None)
        if raw_client is not None:
            for collection in (
                session._vector_index.private_collection,
                session._vector_index.shared_collection,
            ):
                try:
                    if raw_client.collection_exists(collection_name=collection):
                        raw_client.delete_collection(collection_name=collection)
                except Exception:
                    pass
        session.close()


def test_real_services_m1_uses_exact_stream_identity_with_multi_arm_jobs():
    """Keep M1 executable after another arm seeds the same task/job join keys."""

    database_url = os.getenv(DATABASE_ENV)
    admin_database_url = os.getenv(ADMIN_DATABASE_ENV)
    qdrant_url = os.getenv(QDRANT_ENV)
    if not database_url or not admin_database_url or not qdrant_url:
        pytest.skip("real TriMem service endpoints are not configured")

    run = uuid.uuid4().hex
    org_id = _uuid("m1-multi-org|" + run)
    user_id = _uuid("m1-multi-user|" + run)
    source = replace(
        source_task(),
        org_id=org_id,
        user_id=user_id,
        repository="fixture/m1-multi-stream",
    )
    target = replace(
        target_task(),
        task_id=source.task_id + "-later-target",
        org_id=org_id,
        user_id=user_id,
        repository=source.repository,
        instruction="Use the prior case-insensitive suffix validation technique.",
    )
    repository_id = _uuid("m1-multi-repository|" + run)

    def resolver_for(stream_id):
        def resolve(observed):
            assert observed.task_id in {source.task_id, target.task_id}
            return {
                "repository_id": repository_id,
                "solve_job_id": _uuid(
                    "m1-multi-solve-job|%s|%s|%s"
                    % (run, stream_id, observed.task_id)
                ),
            }

        return resolve

    m1_resolver = resolver_for("M1")
    for stream_id in ("M1", "M2-shadow"):
        evidence = seed_benchmark_identities(
            admin_database_url=admin_database_url,
            experiment_id="real-m1-multi-" + run + "-" + stream_id.casefold(),
            stream_id=stream_id,
            tasks=(source, target),
            identity_resolver=resolver_for(stream_id),
        )
        assert evidence["admin_bypassrls"] is True

    encoder = _M2CredentialFreeEncoder()
    session = open_benchmark_arm(
        database_url=database_url,
        qdrant_url=qdrant_url,
        experiment_id="real-m1-multi-" + run,
        split="credential_free_replay",
        arm_id="M1",
        task_order=(source, target),
        dqn_checkpoint_path=None,
        embedder_lock={
            "model_id": encoder.model_id,
            "revision": encoder.revision,
            "dimension": encoder.dimensions,
        },
        evaluation=False,
        embedder=encoder,
        lifecycle_factory=production_v03_lifecycle_factory(
            identity_resolver=m1_resolver
        ),
        run_nonce=_uuid("m1-multi-run-nonce|" + run),
    )
    try:
        session.assert_fresh()
        ctx = AccessContext(org_id, user_id)
        with pytest.raises(NotFound, match="task identity is unavailable"):
            session.run_coroutine(
                session._store.resolve_task_identity(
                    ctx,
                    repository_slug=source.repository,
                    task_id=source.task_id,
                )
            )

        session.lifecycle.before_task(task=source, sequence_index=0)
        fresh_solve_qdrant_before = session._qdrant_evidence()
        stored = session.lifecycle.store_experience(
            source,
            ShortTermWorkingGraph(source.task_id, source.instruction, source.repository),
            ExperienceExtraction(
                episode={
                    "summary": "Case-insensitive suffix validation passed.",
                    "action": "casefold the suffix before comparison",
                },
                semantic_candidate=None,
                response_hash="a" * 64,
                patch_hash="b" * 64,
                public_evidence_hash="c" * 64,
            ),
            GradeResult(
                task_id=source.task_id,
                resolved=True,
                exit_code=0,
                stdout="passed",
                stderr="",
                report={"status": "passed"},
                grader_id="credential-free-m1",
                container_digest="credential-free",
                official=False,
                wall_time_ms=1,
            ),
            (),
        )
        assert stored["storage_action"] == "V03_RETAIN_PRIVATE_EPISODE"
        assert stored["retained_records"] == 1
        assert stored["pending_candidate_outbox_events"] == 1
        assert stored["fresh_solve_immediate_carryover"] == 0
        assert session._qdrant_evidence() == fresh_solve_qdrant_before
        canonical_episode = session.run_coroutine(
            load_private_episode(
                session._engine,
                org_id,
                user_id,
                stored["memory_id"],
            )
        )
        assert canonical_episode["canonical"] == {
            "task_id": source.task_id,
            "repo_id": repository_id,
            "commit": source.commit,
            "outcome": "success",
            "injected_memory_ids": [],
        }
        assert set(canonical_episode["canonical"]) == {
            "task_id", "repo_id", "commit", "outcome", "injected_memory_ids"
        }

        async def load_atomic_pair():
            from sqlalchemy import text
            from enterprise_memory.persistence.tenant_context import tenant_tx

            async with tenant_tx(session._engine, org_id, user_id) as connection:
                episode = (
                    await connection.execute(
                        text(
                            "SELECT id,org_id,owner_user_id,repository_id,task_id,"
                            "source_commit,canonical_json,content_hash,state "
                            "FROM private_episodes WHERE id=CAST(:id AS uuid)"
                        ),
                        {"id": stored["memory_id"]},
                    )
                ).mappings().one()
                events = (
                    await connection.execute(
                        text(
                            "SELECT event_type,aggregate_type,aggregate_id,"
                            "aggregate_version,payload_json,status,attempts,"
                            "max_attempts,lease_owner,lease_expires_at,"
                            "error_detail_sanitized,processed_at "
                            "FROM outbox_events "
                            "WHERE aggregate_id=CAST(:id AS uuid) ORDER BY id"
                        ),
                        {"id": stored["memory_id"]},
                    )
                ).mappings().all()
            return dict(episode), [dict(row) for row in events]

        episode_row, candidate_events = session.run_coroutine(load_atomic_pair())
        assert str(episode_row["id"]) == stored["memory_id"]
        assert str(episode_row["org_id"]) == org_id
        assert str(episode_row["owner_user_id"]) == user_id
        assert str(episode_row["repository_id"]) == repository_id
        assert episode_row["task_id"] is None
        assert episode_row["source_commit"] is None
        assert episode_row["state"] == "success"
        assert candidate_events == [{
            "event_type": "CONTRACT_CANDIDATE",
            "aggregate_type": "private_episode",
            "aggregate_id": uuid.UUID(stored["memory_id"]),
            "aggregate_version": 1,
            "payload_json": {"job_id": m1_resolver(source)["solve_job_id"]},
            "status": "PENDING",
            "attempts": 0,
            "max_attempts": 5,
            "lease_owner": None,
            "lease_expires_at": None,
            "error_detail_sanitized": None,
            "processed_at": None,
        }]

        # Current v0.3 also has legitimate older private-note episodes.  Seed
        # one through its canonical API and index it through the exact current
        # projection.  This is intentionally separate from the fresh solve
        # episode above: the current solve path emitted no PRIVATE_INDEX event,
        # so validated_search never sees that five-field row at all.
        note_canonical = {
            "private_note": (
                "Normalize suffix values with casefold before comparing the "
                "case-insensitive allowlist."
            )
        }
        note_id = session.run_coroutine(
            persist_private_episode(
                session._engine,
                org_id,
                user_id,
                repository_id,
                note_canonical,
            )
        )
        note_row = session.run_coroutine(
            load_private_episode(
                session._engine, org_id, user_id, note_id
            )
        )
        note_record = build_record(PRIVATE, note_row, indexed_at=NOW)
        note_vectors = session.lifecycle.runtime.embedder.embed([note_record.text])
        raw_v03_client = getattr(
            session._qdrant_client,
            "raw_client",
            session._qdrant_client,
        )
        fixture_index = QdrantIndex(
            raw_v03_client, encoder.dimensions, server=True
        )
        fixture_index._upsert(
            [note_record],
            [list(note_vectors[0])],
            session.lifecycle.runtime.index.collections[PRIVATE],
        )

        session.lifecycle.before_task(task=target, sequence_index=1)
        controller = production_v03_controller_factory(
            task=target,
            canonical_store=session._store,
            persistence=session.persistence,
            namespace=session.namespace,
            lifecycle=session.lifecycle,
            identity_resolver=m1_resolver,
        )
        assert isinstance(controller, CurrentV03MemoryController)
        working = ShortTermWorkingGraph(
            target.task_id, target.instruction, target.repository
        )
        working.add_subtask(SubtaskSpec(
            node_id="later-target",
            objective="reuse suffix validation technique",
            operation="validate suffix",
        ))
        working.activate("later-target")
        recalled = controller.recall(working, target)
        assert [item.memory_id for item in recalled.injections] == [note_id]
        assert recalled.bank_trace[0]["bank"] == "V03_LIVE_MAIN"
        source_rejections = [
            row for row in recalled.rejections
            if row.get("memory_id") == stored["memory_id"]
        ]
        assert source_rejections == []
        assert recalled.injections[0].exact_text.startswith(
            "Your prior verified note: Normalize suffix values"
        )
    finally:
        raw_client = getattr(session._qdrant_client, "raw_client", None)
        if raw_client is not None:
            for collection in (
                session._vector_index.private_collection,
                session._vector_index.shared_collection,
            ):
                try:
                    if raw_client.collection_exists(collection_name=collection):
                        raw_client.delete_collection(collection_name=collection)
                except Exception:
                    pass
        session.close()
