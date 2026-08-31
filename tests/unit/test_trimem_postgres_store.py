"""Credential-free fake-connection tests for the async 0015 repository."""
import asyncio
import json
import re
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from enterprise_memory.trimem.benchmark_seed import (
    BenchmarkIdentitySeedError,
    seed_benchmark_identities,
)
from enterprise_memory.trimem.postgres_store import (
    CapacityLimits,
    CanonicalReloadError,
    LifecycleAppendBundle,
    PostgresTriMemStore,
    SemanticStrengthIncrement,
    _postgres_timestamp,
)
from enterprise_memory.trimem.schema import (
    AccessContext,
    EdgeType,
    GraphCheckpoint,
    GraphEdge,
    GraphKind,
    GraphNode,
    MemoryAccessEvent,
    NodeType,
    OrganisationSemanticGraph,
    PolicyAction,
    PolicyActor,
    PolicyTransition,
    ReviewAuthority,
    ReviewProvenance,
    SemanticStrength,
    SemanticStrengthRecord,
    SemanticSupport,
    ShortTermWorkingGraph,
    TemporalMetadata,
    UserEpisodicGraph,
    UserSemanticGraph,
    canonical_hash,
)
from enterprise_memory.trimem.store import IntegrityViolation, NotFound, ScopeViolation
from enterprise_memory.trimem.vector_index import VectorReference


NOW = "2026-08-31T00:00:00Z"
_TIMESTAMPTZ_BIND_KEYS = {
    "archived_at",
    "claimed_at",
    "created_at",
    "event_time",
    "indexed_at",
    "ingested_at",
    "last_accessed_at",
    "last_used_at",
    "last_verified_at",
    "reviewed_at",
    "source_available_at",
    "updated_at",
    "valid_from",
    "valid_until",
    "verified_at",
}


class _FakeResult:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeTransaction:
    def __init__(self, engine):
        self.engine = engine
        self.before = deepcopy(engine.tables)

    async def commit(self):
        self.engine.commits += 1

    async def rollback(self):
        self.engine.tables = self.before
        self.engine.rollbacks += 1


class _FakeConnection:
    def __init__(self, engine):
        self.engine = engine
        self.org_id = None
        self.user_id = None
        self.namespace = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def begin(self):
        self.engine.transactions += 1
        return _FakeTransaction(self.engine)

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = dict(params or {})
        for name in _TIMESTAMPTZ_BIND_KEYS.intersection(params):
            value = params[name]
            if value is not None:
                assert isinstance(value, datetime), (sql, name, value)
                assert value.tzinfo is not None and value.utcoffset() is not None
        self.engine.calls.append((sql, params))
        if "set_config('app.org_id'" in sql:
            self.org_id = params["o"]
            self.engine.contexts.append(("org", self.org_id))
            return _FakeResult()
        if "set_config('app.user_id'" in sql:
            self.user_id = params["u"]
            self.engine.contexts.append(("user", self.user_id))
            return _FakeResult()
        if "set_config('app.trimem_namespace'" in sql:
            self.namespace = params["namespace"]
            self.engine.contexts.append(("namespace", self.namespace))
            return _FakeResult()
        if "pg_advisory_xact_lock" in sql:
            return _FakeResult(({"locked": True},))

        if "FROM repositories" in sql:
            rows = [
                dict(row)
                for row in self.engine.repositories
                if str(row["org_id"]) == str(self.org_id)
                and row["external_repo_id"] == params["repository_slug"]
            ]
            return _FakeResult(rows[:2])
        if "FROM solve_jobs j" in sql:
            rows = [
                dict(row)
                for row in self.engine.solve_jobs
                if str(row["org_id"]) == str(self.org_id)
                and str(row["repository_id"]) == str(params["repository_id"])
                and str(row["submitter_user_id"]) == str(self.user_id)
                and row["task_id"] == params["task_id"]
            ]
            return _FakeResult(rows[:2])

        insert = re.search(r"INSERT INTO (trimem_[a-z_]+)", sql, re.I)
        if insert:
            table = insert.group(1).lower()
            if (
                table == "trimem_session_checkpoints"
                and self.engine.fail_session_checkpoint_insert
            ):
                raise RuntimeError("simulated checkpoint insert failure")
            key = str(params.get("id", params.get("namespace")))
            rows = self.engine.tables.setdefault(table, {})
            if table == "trimem_semantic_strengths":
                existing_key = next(
                    (
                        item_key
                        for item_key, item in rows.items()
                        if str(item.get("org_id")) == str(params.get("org_id"))
                        and str(item.get("namespace")) == str(params.get("namespace"))
                        and str(item.get("graph_id")) == str(params.get("graph_id"))
                        and str(item.get("semantic_node_id"))
                        == str(params.get("semantic_node_id"))
                    ),
                    None,
                )
                components = (
                    "support",
                    "successful_reuse",
                    "independent_user_evidence",
                    "recent_verification",
                    "negative_transfer",
                    "contradiction",
                    "version_staleness",
                )
                if existing_key is not None:
                    current = rows[existing_key]
                    monotonic = (
                        str(existing_key) == key
                        and str(params["updated_at"]) >= str(current["updated_at"])
                        and all(
                            float(params[name]) >= float(current[name])
                            for name in components
                        )
                    )
                    if monotonic:
                        current.update(params)
                        current["strength_score"] = (
                            float(current["support"])
                            + float(current["successful_reuse"])
                            + float(current["independent_user_evidence"])
                            + float(current["recent_verification"])
                            - float(current["negative_transfer"])
                            - float(current["contradiction"])
                            - float(current["version_staleness"])
                        )
                    return _FakeResult()
            if key in rows:
                return _FakeResult()
            row = dict(params)
            if table == "trimem_namespace_claims":
                row.update(next_sequence_index=0, claim_status="ACTIVE")
            elif table == "trimem_vector_index_outbox":
                row.update(
                    status="PENDING",
                    attempts=0,
                    last_error=None,
                    created_at=NOW,
                    updated_at=NOW,
                    indexed_at=None,
                )
            elif table == "trimem_session_checkpoints":
                row.update(created_at=NOW)
            elif table == "trimem_promotion_evidence":
                row.update(created_at=NOW)
            elif table == "trimem_lifecycle_operation_receipts":
                row.update(created_at=NOW)
            elif table == "trimem_semantic_strengths":
                row["strength_score"] = (
                    float(row["support"])
                    + float(row["successful_reuse"])
                    + float(row["independent_user_evidence"])
                    + float(row["recent_verification"])
                    - float(row["negative_transfer"])
                    - float(row["contradiction"])
                    - float(row["version_staleness"])
                )
            rows[key] = row
            return _FakeResult((row,)) if " RETURNING " in sql else _FakeResult()

        update = re.search(r"UPDATE (trimem_[a-z_]+)", sql, re.I)
        if update:
            table = update.group(1).lower()
            rows = self.engine.tables.get(table, {})
            if table == "trimem_graph_nodes" and "SET lifecycle_state='ARCHIVED'" in sql:
                row = rows.get(str(params.get("id")))
                if (
                    row is None
                    or row.get("lifecycle_state") != "ACTIVE"
                    or row.get("content_hash") != params.get("prior_content_hash")
                    or str(row.get("org_id")) != str(self.org_id)
                    or str(row.get("namespace")) != str(self.namespace)
                ):
                    return _FakeResult()
                row.update(
                    lifecycle_state="ARCHIVED",
                    canonical_payload={},
                    payload_hash=params["payload_hash"],
                    archived_at=params["archived_at"],
                    archive_reason=params["archive_reason"],
                    archived_from_content_hash=params["archived_from_content_hash"],
                    content_hash=params["content_hash"],
                )
                return _FakeResult((dict(row),))
            if table == "trimem_vector_index_outbox":
                if "SET status='CANCELLED'" in sql:
                    updated = []
                    for row in rows.values():
                        if (
                            str(row.get("node_id")) == str(params.get("node_id"))
                            and row.get("operation") == "UPSERT"
                            and row.get("canonical_content_hash")
                            == params.get("canonical_content_hash")
                            and row.get("status") == "PENDING"
                        ):
                            row.update(status="CANCELLED", last_error=None, updated_at=NOW)
                            updated.append(dict(row))
                    return _FakeResult(updated)
                row = rows.get(str(params.get("id")))
                if (
                    row is None
                    or str(row.get("org_id")) != str(self.org_id)
                    or str(row.get("namespace")) != str(self.namespace)
                    or (
                        row.get("graph_kind") != GraphKind.ORGANISATION_SEMANTIC.value
                        and str(row.get("owner_user_id")) != str(self.user_id)
                    )
                    or row.get("canonical_content_hash")
                    != params.get("canonical_content_hash")
                    or row.get("status") != "PENDING"
                ):
                    return _FakeResult()
                row["attempts"] += 1
                row["updated_at"] = NOW
                if "SET status='INDEXED'" in sql:
                    row.update(status="INDEXED", last_error=None, indexed_at=NOW)
                else:
                    row["last_error"] = params["last_error"]
                return _FakeResult((dict(row),))
            row = rows.get(str(params.get("namespace")))
            if (
                row is None
                or str(row.get("org_id")) != str(self.org_id)
                or str(row.get("owner_user_id")) != str(self.user_id)
                or str(row.get("run_nonce")) != str(params.get("run_nonce"))
                or row.get("next_sequence_index") != params.get("expected_current")
            ):
                return _FakeResult()
            row["next_sequence_index"] = params["next_sequence_index"]
            return _FakeResult((dict(row),))

        select = re.search(r"FROM (trimem_[a-z_]+)", sql, re.I)
        if select:
            table = select.group(1).lower()
            rows = list(self.engine.tables.get(table, {}).values())
            if table == "trimem_graph_nodes" and "FROM trimem_graph_nodes n" in sql:
                visible = [
                    dict(row)
                    for row in rows
                    if str(row.get("org_id")) == str(self.org_id)
                    and str(row.get("namespace")) == str(self.namespace)
                    and row.get("graph_kind") == params.get("graph_kind")
                    and row.get("node_type") == params.get("node_type")
                    and row.get("lifecycle_state") == "ACTIVE"
                    and (
                        "n.owner_user_id=:owner_user_id" not in sql
                        or str(row.get("owner_user_id")) == str(self.user_id)
                    )
                ]
                if "COALESCE(n.event_time,n.ingested_at)" in sql:
                    visible.sort(
                        key=lambda row: (
                            str(row.get("event_time") or row.get("ingested_at")),
                            str(row["id"]),
                        )
                    )
                else:
                    strengths = self.engine.tables.get("trimem_semantic_strengths", {})
                    by_node = {
                        str(item.get("semantic_node_id", key)): item
                        for key, item in strengths.items()
                    }
                    visible.sort(
                        key=lambda row: (
                            float(by_node.get(str(row["id"]), {}).get("strength_score", 0)),
                            str(row["id"]),
                        )
                    )
                return _FakeResult(({"id": row["id"]} for row in visible))
            if "count(*) AS row_count" in sql:
                count = sum(
                    1 for row in rows
                    if str(row["org_id"]) == str(self.org_id)
                    and str(row["namespace"]) == str(self.namespace)
                )
                return _FakeResult(({"row_count": count},))
            if table == "trimem_namespace_claims":
                visible = []
                for row in rows:
                    if any(
                        str(row.get(name)) != str(params[name])
                        for name in (
                            "org_id", "namespace", "owner_user_id", "experiment_id",
                            "split", "arm_id", "task_order_hash", "config_hash",
                            "run_nonce", "next_sequence_index",
                        )
                    ):
                        continue
                    if row.get("claim_status") != "ACTIVE":
                        continue
                    visible.append(dict(row))
                return _FakeResult(visible)
            if table == "trimem_session_checkpoints":
                visible = [
                    dict(row)
                    for row in rows
                    if str(row.get("org_id")) == str(self.org_id)
                    and str(row.get("namespace")) == str(self.namespace)
                    and str(row.get("owner_user_id")) == str(self.user_id)
                    and (
                        "run_nonce" not in params
                        or str(row.get("run_nonce")) == str(params["run_nonce"])
                    )
                ]
                visible.sort(
                    key=lambda row: int(row["next_sequence_index"]), reverse=True
                )
                return _FakeResult(visible[:1] if "LIMIT 1" in sql else visible)
            if table == "trimem_promotion_evidence":
                requested = set(params.get("evidence_hashes", ()))
                visible = [
                    dict(row)
                    for row in rows
                    if str(row.get("org_id")) == str(self.org_id)
                    and str(row.get("namespace")) == str(self.namespace)
                    and ("id" not in params or str(row.get("id")) == str(params["id"]))
                    and (not requested or row.get("evidence_hash") in requested)
                ]
                visible.sort(
                    key=lambda row: (
                        row["evidence_hash"], row["contributor_hash"], row["id"]
                    )
                )
                return _FakeResult(visible)
            if table == "trimem_lifecycle_operation_receipts":
                visible = [
                    dict(row)
                    for row in rows
                    if str(row.get("org_id")) == str(self.org_id)
                    and str(row.get("namespace")) == str(self.namespace)
                    and str(row.get("owner_user_id")) == str(self.user_id)
                    and ("id" not in params or str(row.get("id")) == str(params["id"]))
                ]
                return _FakeResult(visible)
            visible = []
            for row in rows:
                if str(row["org_id"]) != str(self.org_id):
                    continue
                if str(row["namespace"]) != str(self.namespace):
                    continue
                if (
                    row["graph_kind"] != GraphKind.ORGANISATION_SEMANTIC.value
                    and str(row.get("owner_user_id")) != str(self.user_id)
                ):
                    continue
                if "id" in params and str(row["id"]) != str(params["id"]):
                    continue
                if "kind" in params and row["graph_kind"] != params["kind"]:
                    continue
                if "graph_id" in params and str(row["graph_id"]) != str(params["graph_id"]):
                    continue
                if "status" in params and row.get("status") != params["status"]:
                    continue
                if (
                    "semantic_node_id" in params
                    and str(row["semantic_node_id"]) != str(params["semantic_node_id"])
                ):
                    continue
                if "lifecycle_state='ACTIVE'" in sql and row["lifecycle_state"] != "ACTIVE":
                    continue
                visible.append(dict(row))
            visible.sort(key=lambda row: str(row["id"]))
            return _FakeResult(visible)
        raise AssertionError("unexpected SQL: %s" % sql)


class _FakeEngine:
    def __init__(self):
        self.tables = {}
        self.repositories = []
        self.solve_jobs = []
        self.calls = []
        self.contexts = []
        self.transactions = 0
        self.commits = 0
        self.rollbacks = 0
        self.fail_session_checkpoint_insert = False
        self.connection = _FakeConnection(self)

    def connect(self):
        return self.connection


class _SeedFakeConnection:
    def __init__(self, engine):
        self.engine = engine

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        params = dict(params or {})
        self.engine.calls.append((sql, params))
        if "FROM pg_roles WHERE rolname=current_user" in sql:
            return _FakeResult(
                ({"role_name": "postgres", "rolsuper": True, "rolbypassrls": True},)
            )

        insert = re.search(r"INSERT INTO ([a-z_]+)", sql, re.I)
        if insert:
            table = insert.group(1).lower()
            rows = self.engine.tables.setdefault(table, {})
            key = str(params["id"])
            if key not in rows:
                if table == "organisations":
                    row = {
                        "id": uuid.UUID(key),
                        "external_key": params["external_key"],
                    }
                elif table == "users":
                    row = {
                        "id": uuid.UUID(key),
                        "org_id": uuid.UUID(str(params["org_id"])),
                        "external_subject": params["external_subject"],
                    }
                elif table == "repositories":
                    row = {
                        "id": uuid.UUID(key),
                        "org_id": uuid.UUID(str(params["org_id"])),
                        "external_repo_id": params["external_repo_id"],
                        "provider": "github",
                        "default_branch": "main",
                    }
                elif table == "repository_permissions":
                    row = {
                        "id": uuid.UUID(key),
                        "org_id": uuid.UUID(str(params["org_id"])),
                        "repository_id": uuid.UUID(str(params["repository_id"])),
                        "subject_type": "user",
                        "subject_id": uuid.UUID(str(params["subject_id"])),
                        "can_read": True,
                        "can_modify": False,
                        "path_globs": [],
                        "branch_globs": [],
                        "version": 1,
                    }
                elif table == "task_execution_policies":
                    row = {
                        **params,
                        "id": uuid.UUID(key),
                        "org_id": uuid.UUID(str(params["org_id"])),
                        "repository_id": uuid.UUID(str(params["repository_id"])),
                        "editable_paths": list(params["editable_paths"]),
                    }
                elif table == "solve_jobs":
                    row = {
                        **params,
                        "id": uuid.UUID(key),
                        "org_id": uuid.UUID(str(params["org_id"])),
                        "submitter_user_id": uuid.UUID(
                            str(params["submitter_user_id"])
                        ),
                        "repository_id": uuid.UUID(str(params["repository_id"])),
                        "task_policy_id": uuid.UUID(str(params["task_policy_id"])),
                        "spec_json": json.loads(params["spec_json"]),
                    }
                else:
                    raise AssertionError("unexpected seed insert: %s" % table)
                rows[key] = row
            return _FakeResult()

        select = re.search(r"FROM ([a-z_]+) WHERE id=:id", sql, re.I)
        if select:
            table = select.group(1).lower()
            row = self.engine.tables.get(table, {}).get(str(params["id"]))
            return _FakeResult((dict(row),) if row is not None else ())
        raise AssertionError("unexpected seed SQL: %s" % sql)


class _SeedFakeEngine:
    def __init__(self):
        self.tables = {}
        self.calls = []
        self.disposals = 0
        self.connection = _SeedFakeConnection(self)

    def begin(self):
        return self.connection

    async def dispose(self):
        self.disposals += 1


def _run(awaitable):
    return asyncio.run(awaitable)


def _temporal(event_time=NOW):
    return TemporalMetadata(
        ingested_at=NOW,
        event_time=event_time,
        source_available_at=NOW,
        last_verified_at=NOW,
    )


def _review():
    return ReviewProvenance(
        review_id="review-1",
        reviewer_id="reviewer-1",
        reviewed_at=NOW,
        authority=ReviewAuthority.HUMAN_REVIEW,
        policy_version="shared-v1",
        evidence_hash="sha256:" + "a" * 64,
    )


def _node(graph, node_id, node_type, payload, review=None, event_time=NOW):
    return GraphNode(
        node_id=node_id,
        graph_id=graph.graph_id,
        org_id=graph.org_id,
        namespace=graph.namespace,
        graph_kind=graph.kind,
        owner_user_id=graph.owner_user_id,
        repository_id=graph.repository_id,
        node_type=node_type,
        canonical_payload=payload,
        temporal=_temporal(event_time),
        review_provenance=review,
    )


def test_graph_roundtrip_uses_transaction_local_org_and_user_context():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine)
    ctx = AccessContext("org-a", "alice")
    graph = UserEpisodicGraph(
        graph_id="episodes-a",
        org_id=ctx.org_id,
        owner_user_id=ctx.user_id,
        repository_id="repo-a",
        temporal=_temporal(),
    )

    assert _run(store.put_graph(ctx, graph)) == graph
    assert _run(store.get_graph(ctx, graph.graph_id)) == graph
    assert _run(store.list_graphs(ctx, kind=GraphKind.USER_EPISODIC)) == [graph]
    assert engine.transactions == engine.commits == 3
    assert engine.rollbacks == 0
    assert ("org", "org-a") in engine.contexts and ("user", "alice") in engine.contexts
    reads = [sql for sql, _ in engine.calls if sql.startswith("SELECT id, org_id, namespace")]
    assert reads
    assert all("org_id=:org_id" in sql and "owner_user_id=:owner_user_id" in sql for sql in reads)
    assert all("namespace=:namespace" in sql for sql in reads)
    assert ("namespace", "unit-test") in engine.contexts


def test_iso_z_timestamps_bind_as_aware_utc_datetimes():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine)
    ctx = AccessContext("org-a", "alice")
    temporal = TemporalMetadata(
        ingested_at="2026-08-31T00:00:00Z",
        event_time="2026-08-31T00:00:01Z",
        source_available_at="2026-08-31T00:00:02Z",
        last_accessed_at="2026-08-31T00:00:03Z",
        last_used_at="2026-08-31T00:00:04Z",
        last_verified_at="2026-08-31T00:00:05Z",
        valid_from="2026-08-31T00:00:06Z",
        valid_until="2026-09-01T00:00:00Z",
    )
    review = ReviewProvenance(
        review_id="review-bind",
        reviewer_id="reviewer-bind",
        reviewed_at="2026-08-31T00:00:07Z",
        authority=ReviewAuthority.HUMAN_REVIEW,
        policy_version="shared-v1",
        evidence_hash="sha256:" + "b" * 64,
    )
    graph = OrganisationSemanticGraph(
        graph_id="org-bind-times",
        org_id=ctx.org_id,
        temporal=temporal,
        review_provenance=review,
    )

    assert _run(store.put_graph(ctx, graph)) == graph
    _, params = next(
        (sql, params)
        for sql, params in engine.calls
        if sql.startswith("INSERT INTO trimem_graphs")
    )
    timestamp_names = {
        "ingested_at",
        "event_time",
        "source_available_at",
        "last_accessed_at",
        "last_used_at",
        "last_verified_at",
        "valid_from",
        "valid_until",
        "reviewed_at",
    }
    assert all(isinstance(params[name], datetime) for name in timestamp_names)
    assert all(params[name].tzinfo is timezone.utc for name in timestamp_names)


def test_postgres_timestamp_normalizes_offsets_and_rejects_naive_values():
    assert _postgres_timestamp(
        "2026-08-31T09:30:00+09:00", "event_time"
    ) == datetime(2026, 8, 31, 0, 30, tzinfo=timezone.utc)
    assert _postgres_timestamp(None, "event_time") is None
    with pytest.raises(ValueError, match="include a timezone"):
        _postgres_timestamp("2026-08-31T00:00:00", "event_time")
    with pytest.raises(ValueError, match="ISO-8601"):
        _postgres_timestamp("not-a-timestamp", "event_time")


def test_same_org_owner_other_namespace_is_indistinguishable_from_absent():
    engine = _FakeEngine()
    ctx = AccessContext("org-a", "alice")
    first = PostgresTriMemStore(engine, namespace="run:a")
    second = PostgresTriMemStore(engine, namespace="run:b")
    graph = UserSemanticGraph(
        graph_id="namespaced-rule-bank", org_id=ctx.org_id, namespace="run:a",
        owner_user_id=ctx.user_id, temporal=_temporal(),
    )
    assert _run(first.put_graph(ctx, graph)) == graph
    with pytest.raises(NotFound, match="graph not found"):
        _run(second.get_graph(ctx, graph.graph_id))
    assert _run(second.list_graphs(ctx, kind=GraphKind.USER_SEMANTIC)) == []


def test_same_org_other_owner_is_indistinguishable_from_absent():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine)
    alice = AccessContext("org-a", "alice")
    bob = AccessContext("org-a", "bob")
    graph = UserSemanticGraph(
        graph_id="alice-rules", org_id="org-a", owner_user_id="alice", temporal=_temporal()
    )
    _run(store.put_graph(alice, graph))

    with pytest.raises(NotFound, match="graph not found"):
        _run(store.get_graph(bob, graph.graph_id))
    with pytest.raises(NotFound, match="graph not found"):
        _run(store.get_graph(bob, "does-not-exist"))
    assert _run(store.list_graphs(bob, kind=GraphKind.USER_SEMANTIC)) == []
    with pytest.raises(ScopeViolation, match="owner boundary"):
        _run(store.put_graph(bob, graph))


def test_reviewed_org_semantic_is_visible_to_same_org_only():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine)
    review = _review()
    graph = OrganisationSemanticGraph(
        graph_id="org-rules", org_id="org-a", temporal=_temporal(),
        review_provenance=review,
    )
    _run(store.put_graph(AccessContext("org-a", "publisher"), graph))
    assert _run(store.get_graph(AccessContext("org-a", "reader"), graph.graph_id)) == graph
    with pytest.raises(NotFound):
        _run(store.get_graph(AccessContext("org-b", "outsider"), graph.graph_id))


def test_all_required_record_families_roundtrip_through_canonical_reload():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine)
    ctx = AccessContext("org-a", "alice")
    work = ShortTermWorkingGraph(
        graph_id="work", org_id=ctx.org_id, owner_user_id=ctx.user_id,
        solve_job_id="job-a", repository_id="repo-a", temporal=_temporal(),
    )
    _run(store.put_graph(ctx, work))
    first = _node(work, "first", NodeType.SUBTASK, {"objective": "locate API"})
    second = _node(work, "second", NodeType.SUBTASK, {"objective": "update caller"})
    assert _run(store.put_node(ctx, first)) == first
    assert _run(store.put_node(ctx, second)) == second
    edge = GraphEdge(
        edge_id="edge-1", graph_id=work.graph_id, org_id=work.org_id,
        graph_kind=work.kind, owner_user_id=work.owner_user_id,
        edge_type=EdgeType.DEPENDS_ON, source_node_id=first.node_id,
        target_node_id=second.node_id, metadata={"weight": 2.0}, temporal=_temporal(),
    )
    assert _run(store.put_edge(ctx, edge)) == edge
    checkpoint = GraphCheckpoint(
        checkpoint_id="checkpoint-1", graph_id=work.graph_id, org_id=work.org_id,
        owner_user_id=ctx.user_id, sequence=1, graph_content_hash=work.content_hash,
        active_node_id=first.node_id, created_at=NOW,
    )
    assert _run(store.save_checkpoint(ctx, checkpoint)) == checkpoint
    transition = PolicyTransition(
        transition_id="transition-1", graph_id=work.graph_id,
        candidate_node_id=first.node_id, org_id=work.org_id, owner_user_id=ctx.user_id,
        action=PolicyAction.MOVE_TO_EPISODIC, actor=PolicyActor.DOUBLE_DQN,
        target_graph_kind=GraphKind.USER_EPISODIC, event_time=NOW, reward=1.25,
    )
    assert _run(store.record_policy_transition(ctx, transition)) == transition

    semantic = UserSemanticGraph(
        graph_id="semantic", org_id=ctx.org_id, owner_user_id=ctx.user_id,
        repository_id="repo-a", temporal=_temporal(),
    )
    _run(store.put_graph(ctx, semantic))
    rule = _node(
        semantic, "rule-1", NodeType.SEMANTIC_RULE,
        {
            "retrieval_text": "pass timeout and verify test_timeout",
            "operation": "pass timeout",
            "verification": "test_timeout",
            "version": "abc123",
            "version_valid": True,
            "stale": False,
        },
    )
    _run(store.put_node(ctx, rule))
    support = SemanticSupport(
        support_id="support-1", semantic_graph_id=semantic.graph_id,
        semantic_node_id=rule.node_id, org_id=ctx.org_id,
        graph_kind=semantic.kind, owner_user_id=ctx.user_id,
        source_evidence_hash="sha256:" + "b" * 64, temporal=_temporal(),
    )
    assert _run(store.put_support(ctx, support)) == support
    strength = SemanticStrengthRecord(
        strength_id="strength-1",
        graph_id=semantic.graph_id,
        semantic_node_id=rule.node_id,
        org_id=ctx.org_id,
        graph_kind=semantic.kind,
        owner_user_id=ctx.user_id,
        strength=SemanticStrength(support=1, recent_verification=1),
        updated_at=NOW,
    )
    assert _run(store.put_semantic_strength(ctx, strength)) == strength
    strengthened = replace(
        strength,
        strength=SemanticStrength(
            support=1,
            successful_reuse=1,
            recent_verification=1,
        ),
        updated_at="2026-09-01T00:00:00Z",
        content_hash="",
    )
    assert _run(store.put_semantic_strength(ctx, strengthened)) == strengthened
    with pytest.raises(IntegrityViolation, match="already bound"):
        _run(store.put_semantic_strength(ctx, strength))
    access = MemoryAccessEvent.injection(
        event_id="access-1", graph_id=semantic.graph_id, node_id=rule.node_id,
        org_id=ctx.org_id, graph_kind=semantic.kind, owner_user_id=ctx.user_id,
        actor_user_id=ctx.user_id, event_time=NOW, injected_bytes=b"exact bytes",
    )
    access_operation = "00000000-0000-4000-8000-000000000099"
    access_scope = {
        "kind": "ACCESS",
        "task_id": "target-task",
        "active_node_ids": ["active"],
    }
    assert _run(store.append_access_batch(
        ctx,
        (access,),
        operation_id=access_operation,
        operation_scope=access_scope,
    )) == (access,)
    access_receipts = _run(store.lifecycle_receipt_evidence(ctx))
    access_row = next(
        item for item in access_receipts["rows"]
        if item["operation_id"] == access_operation
    )
    assert access_row["operation_scope"] == access_scope
    assert access_row["access_event_ids"] == [access.event_id]
    access_deltas = access_row["canonical_row_deltas"]
    assert access_deltas["trimem_memory_access_events"] == {
        "inserted": 1,
        "updated": 0,
        "deleted": 0,
    }
    assert access_deltas["trimem_lifecycle_operation_receipts"]["inserted"] == 1
    assert _run(store.append_access_batch(
        ctx,
        (access,),
        operation_id=access_operation,
        operation_scope=access_scope,
    )) == (access,)

    assert _run(store.list_nodes(ctx, graph_id=work.graph_id)) == [first, second]
    assert _run(store.list_edges(ctx, graph_id=work.graph_id)) == [edge]
    assert _run(store.list_checkpoints(ctx, graph_id=work.graph_id)) == [checkpoint]
    assert _run(store.list_policy_transitions(ctx, graph_id=work.graph_id)) == [transition]
    assert _run(store.list_supports(ctx, semantic_node_id=rule.node_id)) == [support]
    assert _run(store.get_semantic_strength(ctx, strength.strength_id)) == strengthened
    assert _run(store.list_semantic_strengths(ctx, graph_id=semantic.graph_id)) == [
        strengthened
    ]
    assert _run(store.list_access_events(ctx, graph_id=semantic.graph_id)) == [access]
    feature_rows = _run(store.load_policy_feature_rows(ctx, limit=100))
    assert feature_rows["digest"] == canonical_hash(
        {key: value for key, value in feature_rows.items() if key != "digest"}
    )
    assert len(feature_rows["rows"]) == 1
    feature = feature_rows["rows"][0]
    assert feature["node_id"] == rule.node_id
    assert feature["reuse_count"] == 1
    assert feature["strength"]["successful_reuse"] == 1.0
    assert feature["node_content_hash"] == rule.content_hash


def test_semantic_strength_reuse_increments_are_atomic_and_cumulative():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    ctx = AccessContext("org-a", "alice")
    graph = UserSemanticGraph(
        graph_id="semantic-cumulative",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        temporal=_temporal(),
    )
    node = _node(
        graph,
        "rule-cumulative",
        NodeType.SEMANTIC_RULE,
        {"retrieval_text": "cumulative semantic rule"},
    )
    initial = SemanticStrengthRecord(
        strength_id="strength-cumulative",
        graph_id=graph.graph_id,
        semantic_node_id=node.node_id,
        org_id=ctx.org_id,
        namespace=namespace,
        graph_kind=graph.kind,
        owner_user_id=ctx.user_id,
        strength=SemanticStrength(support=1, recent_verification=1),
        updated_at=NOW,
    )
    _run(store.append_lifecycle_bundle(
        ctx,
        LifecycleAppendBundle(graphs=(graph,), nodes=(node,), strengths=(initial,)),
    ))
    for index, resolved in enumerate((True, True, False), start=1):
        increment = SemanticStrengthIncrement(
            graph_id=graph.graph_id,
            semantic_node_id=node.node_id,
            org_id=ctx.org_id,
            namespace=namespace,
            graph_kind=graph.kind,
            owner_user_id=ctx.user_id,
            successful_reuse=1 if resolved else 0,
            recent_verification=1 if resolved else 0,
            negative_transfer=0 if resolved else 1,
            updated_at="2026-09-0%dT00:00:00Z" % (index + 1),
        )
        bundle = LifecycleAppendBundle(
            operation_id="00000000-0000-4000-8000-%012d" % index,
            operation_scope={
                "kind": "CREDIT",
                "task_id": "target-%d" % index,
                "active_node_ids": ["active-node"],
            },
            strength_increments=(increment,),
        )
        receipt = _run(store.append_lifecycle_bundle(ctx, bundle))
        assert len(receipt.strength_hashes) == 1
        assert receipt.canonical_row_deltas["trimem_semantic_strengths"] == {
            "inserted": 0,
            "updated": 1,
            "deleted": 0,
        }
        assert (
            receipt.canonical_row_deltas[
                "trimem_lifecycle_operation_receipts"
            ]["inserted"]
            == 1
        )
        replay = _run(store.append_lifecycle_bundle(ctx, bundle))
        assert replay.replayed is True
        assert replay.strength_hashes == receipt.strength_hashes
        assert replay.canonical_row_deltas == receipt.canonical_row_deltas

    observed = _run(store.get_semantic_strength(ctx, initial.strength_id))
    assert observed.strength.support == 1.0
    assert observed.strength.successful_reuse == 2.0
    assert observed.strength.recent_verification == 3.0
    assert observed.strength.negative_transfer == 1.0
    evidence = _run(store.lifecycle_receipt_evidence(ctx))
    assert evidence["digest"] == canonical_hash(
        {key: value for key, value in evidence.items() if key != "digest"}
    )
    assert len(evidence["rows"]) == 3
    assert len({row["operation_id"] for row in evidence["rows"]}) == 3
    first_receipt = next(
        iter(engine.tables["trimem_lifecycle_operation_receipts"].values())
    )
    tampered = json.loads(first_receipt["receipt_payload"])
    tampered["canonical_row_deltas"]["trimem_graphs"]["inserted"] = -1
    first_receipt["receipt_payload"] = json.dumps(tampered)
    with pytest.raises(CanonicalReloadError, match="row delta"):
        _run(store.lifecycle_receipt_evidence(ctx))


def test_tampered_canonical_reload_fails_closed_and_rolls_back():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine)
    ctx = AccessContext("org-a", "alice")
    graph = UserSemanticGraph(
        graph_id="semantic", org_id=ctx.org_id, owner_user_id=ctx.user_id,
        temporal=_temporal(),
    )
    node = _node(graph, "rule", NodeType.SEMANTIC_RULE, {"rule": "safe"})
    _run(store.put_graph(ctx, graph))
    _run(store.put_node(ctx, node))
    engine.tables["trimem_graph_nodes"][node.node_id]["canonical_payload"] = '{"rule":"tampered"}'

    with pytest.raises(CanonicalReloadError, match="canonical node reload failed"):
        _run(store.get_node(ctx, node.node_id))
    assert engine.rollbacks == 1


def test_append_only_idempotency_refuses_same_identifier_with_other_hash():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine)
    ctx = AccessContext("org-a", "alice")
    graph = UserEpisodicGraph(
        graph_id="episodes", org_id=ctx.org_id, owner_user_id=ctx.user_id,
        temporal=_temporal(),
    )
    _run(store.put_graph(ctx, graph))
    first = _node(graph, "episode", NodeType.EPISODE, {"outcome": "passed"})
    conflicting = _node(graph, "episode", NodeType.EPISODE, {"outcome": "failed"})
    _run(store.put_node(ctx, first))
    with pytest.raises(IntegrityViolation, match="identifier is already bound"):
        _run(store.put_node(ctx, conflicting))


def test_namespace_claim_is_atomic_and_freshness_counts_exact_namespace():
    engine = _FakeEngine()
    store = PostgresTriMemStore(engine, namespace="trimem:exp:dev:m2")
    ctx = AccessContext("org-a", "alice")
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValueError, match="canonical UUID"):
        _run(store.claim_namespace(
            ctx, experiment_id="exp", split="dev", arm_id="m2",
            task_order_hash=digest, config_hash=digest, run_nonce="not-a-uuid",
        ))
    claim = _run(store.claim_namespace(
        ctx, experiment_id="exp", split="dev", arm_id="m2",
        task_order_hash=digest, config_hash=digest,
        run_nonce="00000000-0000-4000-8000-000000000001",
    ))
    assert claim.namespace == store.namespace
    assert claim.next_sequence_index == 0
    assert _run(store.claim_namespace(
        ctx, experiment_id="exp", split="dev", arm_id="m2",
        task_order_hash=digest, config_hash=digest, run_nonce=claim.run_nonce,
    )) == claim
    evidence = _run(store.namespace_evidence(ctx))
    assert evidence.is_empty
    assert evidence.digest.startswith("sha256:")
    advanced = _run(store.advance_namespace(
        ctx, run_nonce=claim.run_nonce, expected_current=0, next_sequence_index=1,
    ))
    assert advanced.next_sequence_index == 1
    resumed = _run(store.resume_namespace(
        ctx, experiment_id="exp", split="dev", arm_id="m2",
        task_order_hash=digest, config_hash=digest, run_nonce=claim.run_nonce,
        expected_next_sequence_index=1,
    ))
    assert resumed == advanced
    with pytest.raises(IntegrityViolation, match="advance conflict"):
        _run(store.advance_namespace(
            ctx, run_nonce=claim.run_nonce, expected_current=0, next_sequence_index=1,
        ))
    with pytest.raises(IntegrityViolation, match="already claimed"):
        _run(store.claim_namespace(
            ctx, experiment_id="exp", split="dev", arm_id="m2",
            task_order_hash=digest, config_hash=digest,
            run_nonce="00000000-0000-4000-8000-000000000002",
        ))


def test_lifecycle_bundle_is_one_transaction_and_rolls_back_on_hash_failure():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    ctx = AccessContext("org-a", "alice")
    graph = UserEpisodicGraph(
        graph_id="episodes", org_id=ctx.org_id, namespace=namespace,
        owner_user_id=ctx.user_id, temporal=_temporal(),
    )
    node = _node(graph, "episode", NodeType.EPISODE, {"retrieval_text": "safe"})
    receipt = _run(store.append_lifecycle_bundle(
        ctx, LifecycleAppendBundle(graphs=(graph,), nodes=(node,), index_node_ids=(node.node_id,))
    ))
    assert receipt.namespace == namespace
    assert receipt.index_nodes == (node,)
    assert engine.transactions == engine.commits == 1

    other = UserEpisodicGraph(
        graph_id="rollback-graph", org_id=ctx.org_id, namespace=namespace,
        owner_user_id=ctx.user_id, temporal=_temporal(),
    )
    bad = _node(other, "bad", NodeType.EPISODE, {"x": 1})
    object.__setattr__(bad, "content_hash", "sha256:" + "0" * 64)
    with pytest.raises(IntegrityViolation, match="content hash"):
        _run(store.append_lifecycle_bundle(
            ctx, LifecycleAppendBundle(graphs=(other,), nodes=(bad,))
        ))
    assert "rollback-graph" not in engine.tables["trimem_graphs"]
    assert engine.rollbacks == 1


def test_qdrant_reference_is_canonically_reloaded_and_hash_bound():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    ctx = AccessContext("org-a", "alice")
    graph = UserEpisodicGraph(
        graph_id="episodes", org_id=ctx.org_id, namespace=namespace,
        owner_user_id=ctx.user_id, repository_id="repo-a", temporal=_temporal(),
    )
    node = _node(graph, "episode", NodeType.EPISODE, {"retrieval_text": "fix timeout"})
    _run(store.append_lifecycle_bundle(
        ctx, LifecycleAppendBundle(graphs=(graph,), nodes=(node,), index_node_ids=(node.node_id,))
    ))
    reference = VectorReference(
        graph_id=graph.graph_id, node_id=node.node_id, content_hash=node.content_hash,
        org_id=ctx.org_id, namespace=namespace, memory_kind=graph.kind,
        owner_user_id=ctx.user_id, repository_id=graph.repository_id,
    )
    rows = _run(store.load_retrieval_rows(
        ctx, kind=GraphKind.USER_EPISODIC, repository_id="repo-a", references=(reference,),
    ))
    assert rows.graphs == (graph,)
    assert rows.nodes == (node,)
    assert rows.candidate_node_ids == (node.node_id,)
    assert rows.digest.startswith("sha256:")

    stale = VectorReference(
        graph_id=graph.graph_id, node_id=node.node_id,
        content_hash="sha256:" + "f" * 64, org_id=ctx.org_id, namespace=namespace,
        memory_kind=graph.kind, owner_user_id=ctx.user_id, repository_id="repo-a",
    )
    with pytest.raises(CanonicalReloadError, match="does not match"):
        _run(store.load_retrieval_rows(
            ctx, kind=GraphKind.USER_EPISODIC, repository_id="repo-a", references=(stale,),
        ))


def test_outbox_intent_is_atomic_pending_and_hash_bound_through_completion():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    ctx = AccessContext("org-a", "alice")
    graph = UserEpisodicGraph(
        graph_id="episodes-outbox",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        temporal=_temporal(),
    )
    node = _node(
        graph, "episode-outbox", NodeType.EPISODE, {"retrieval_text": "durable intent"}
    )
    receipt = _run(
        store.append_lifecycle_bundle(
            ctx,
            LifecycleAppendBundle(
                graphs=(graph,), nodes=(node,), index_node_ids=(node.node_id,)
            ),
        )
    )
    assert len(receipt.index_intents) == 1
    intent = receipt.index_intents[0]
    assert intent.node_id == node.node_id
    assert intent.canonical_content_hash == node.content_hash
    assert intent.status == "PENDING"
    assert _run(store.list_index_outbox(ctx)) == (intent,)

    failed = _run(
        store.mark_index_outbox_failed(
            ctx,
            intent_id=intent.intent_id,
            canonical_content_hash=node.content_hash,
            error_code="qdrant:RuntimeError",
        )
    )
    assert failed.status == "PENDING"
    assert failed.attempts == 1
    assert failed.last_error == "qdrant:RuntimeError"
    with pytest.raises(IntegrityViolation, match="completion conflict"):
        _run(
            store.mark_index_outbox_indexed(
                ctx,
                intent_id=intent.intent_id,
                canonical_content_hash="sha256:" + "f" * 64,
            )
        )
    indexed = _run(
        store.mark_index_outbox_indexed(
            ctx,
            intent_id=intent.intent_id,
            canonical_content_hash=node.content_hash,
        )
    )
    assert indexed.status == "INDEXED"
    assert indexed.attempts == 2
    assert indexed.last_error is None
    assert _run(store.list_index_outbox(ctx)) == ()


def test_task_identity_resolution_is_exact_unique_and_fail_closed():
    engine = _FakeEngine()
    repository_id = "00000000-0000-4000-8000-000000000010"
    solve_job_id = "00000000-0000-4000-8000-000000000011"
    engine.repositories.append(
        {
            "id": repository_id,
            "org_id": "org-a",
            "external_repo_id": "owner/repo",
        }
    )
    engine.solve_jobs.append(
        {
            "id": solve_job_id,
            "org_id": "org-a",
            "repository_id": repository_id,
            "submitter_user_id": "alice",
            "task_id": "task-1",
        }
    )
    store = PostgresTriMemStore(engine, namespace="trimem:exp:dev:m2")
    ctx = AccessContext("org-a", "alice")
    resolved = _run(
        store.resolve_task_identity(
            ctx, repository_slug="owner/repo", task_id="task-1"
        )
    )
    assert resolved == {
        "repository_id": repository_id,
        "solve_job_id": solve_job_id,
        "repository_slug": "owner/repo",
        "task_id": "task-1",
    }
    with pytest.raises(NotFound, match="unavailable"):
        _run(
            store.resolve_task_identity(
                ctx, repository_slug="OWNER/REPO", task_id="task-1"
            )
        )
    engine.solve_jobs.append(
        {
            **engine.solve_jobs[0],
            "id": "00000000-0000-4000-8000-000000000012",
        }
    )
    with pytest.raises(NotFound, match="unavailable"):
        _run(
            store.resolve_task_identity(
                ctx, repository_slug="owner/repo", task_id="task-1"
            )
        )


def test_retrieval_keeps_episodes_repo_exact_but_allows_general_semantic_null():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    ctx = AccessContext("org-a", "alice")
    semantic_general = UserSemanticGraph(
        graph_id="semantic-general",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        repository_id=None,
        temporal=_temporal(),
    )
    semantic_exact = UserSemanticGraph(
        graph_id="semantic-exact",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        repository_id="repo-a",
        temporal=_temporal(),
    )
    semantic_other = UserSemanticGraph(
        graph_id="semantic-other",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        repository_id="repo-b",
        temporal=_temporal(),
    )
    general_node = _node(
        semantic_general,
        "semantic-general-node",
        NodeType.SEMANTIC_RULE,
        {"retrieval_text": "general invariant"},
    )
    exact_node = _node(
        semantic_exact,
        "semantic-exact-node",
        NodeType.SEMANTIC_RULE,
        {"retrieval_text": "repo invariant"},
    )
    other_node = _node(
        semantic_other,
        "semantic-other-node",
        NodeType.SEMANTIC_RULE,
        {"retrieval_text": "other invariant"},
    )
    _run(
        store.append_lifecycle_bundle(
            ctx,
            LifecycleAppendBundle(
                graphs=(semantic_general, semantic_exact, semantic_other),
                nodes=(general_node, exact_node, other_node),
            ),
        )
    )
    rows = _run(
        store.load_retrieval_rows(
            ctx, kind=GraphKind.USER_SEMANTIC, repository_id="repo-a"
        )
    )
    assert {graph.graph_id for graph in rows.graphs} == {
        semantic_general.graph_id,
        semantic_exact.graph_id,
    }
    assert {node.node_id for node in rows.nodes} == {
        general_node.node_id,
        exact_node.node_id,
    }
    reference = VectorReference(
        graph_id=semantic_general.graph_id,
        node_id=general_node.node_id,
        content_hash=general_node.content_hash,
        org_id=ctx.org_id,
        namespace=namespace,
        memory_kind=GraphKind.USER_SEMANTIC,
        owner_user_id=ctx.user_id,
        repository_id=None,
    )
    shortlisted = _run(
        store.load_retrieval_rows(
            ctx,
            kind=GraphKind.USER_SEMANTIC,
            repository_id="repo-a",
            references=(reference,),
        )
    )
    assert shortlisted.nodes == (general_node,)

    episode_general = UserEpisodicGraph(
        graph_id="episode-general",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        repository_id=None,
        temporal=_temporal(),
    )
    episode_exact = UserEpisodicGraph(
        graph_id="episode-exact",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        repository_id="repo-a",
        temporal=_temporal(),
    )
    episode_general_node = _node(
        episode_general, "episode-general-node", NodeType.EPISODE, {"retrieval_text": "g"}
    )
    episode_exact_node = _node(
        episode_exact, "episode-exact-node", NodeType.EPISODE, {"retrieval_text": "e"}
    )
    _run(
        store.append_lifecycle_bundle(
            ctx,
            LifecycleAppendBundle(
                graphs=(episode_general, episode_exact),
                nodes=(episode_general_node, episode_exact_node),
            ),
        )
    )
    episodes = _run(
        store.load_retrieval_rows(
            ctx, kind=GraphKind.USER_EPISODIC, repository_id="repo-a"
        )
    )
    assert episodes.graphs == (episode_exact,)
    assert episodes.nodes == (episode_exact_node,)


def test_capacity_archives_fifo_and_strength_victims_with_delete_outbox():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    ctx = AccessContext("org-a", "alice")
    limits = CapacityLimits(
        episodic_per_user=1,
        user_semantic_per_user=1,
        organisation_semantic=1,
    )
    old_graph = UserEpisodicGraph(
        graph_id="episode-old-graph",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        temporal=_temporal("2026-01-01T00:00:00Z"),
    )
    old = _node(
        old_graph,
        "episode-old",
        NodeType.EPISODE,
        {"retrieval_text": "old"},
        event_time="2026-01-01T00:00:00Z",
    )
    first = _run(
        store.append_lifecycle_bundle(
            ctx,
            LifecycleAppendBundle(
                graphs=(old_graph,), nodes=(old,), index_node_ids=(old.node_id,)
            ),
        )
    )
    _run(
        store.mark_index_outbox_indexed(
            ctx,
            intent_id=first.index_intents[0].intent_id,
            canonical_content_hash=old.content_hash,
        )
    )
    new_graph = UserEpisodicGraph(
        graph_id="episode-new-graph",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        temporal=_temporal("2026-02-01T00:00:00Z"),
    )
    new = _node(
        new_graph,
        "episode-new",
        NodeType.EPISODE,
        {"retrieval_text": "new"},
        event_time="2026-02-01T00:00:00Z",
    )
    second = _run(
        store.append_lifecycle_bundle(
            ctx,
            LifecycleAppendBundle(
                graphs=(new_graph,),
                nodes=(new,),
                index_node_ids=(new.node_id,),
                capacity_limits=limits,
                capacity_archived_at="2026-09-01T00:00:00Z",
            ),
        )
    )
    assert second.index_nodes == (new,)
    assert [node.node_id for node in second.archived_nodes] == [old.node_id]
    archived_old = second.archived_nodes[0]
    assert archived_old.canonical_payload == {}
    assert archived_old.payload_hash == old.payload_hash
    assert archived_old.archived_from_content_hash == old.content_hash
    assert archived_old.archive_reason == "episodic_fifo_capacity"
    delete = second.delete_intents[0]
    assert delete.operation == "DELETE"
    assert delete.node_id == old.node_id
    assert delete.canonical_content_hash == archived_old.content_hash
    assert delete.prior_content_hash == old.content_hash

    semantic_graph = UserSemanticGraph(
        graph_id="semantic-capacity",
        org_id=ctx.org_id,
        namespace=namespace,
        owner_user_id=ctx.user_id,
        temporal=_temporal(),
    )
    weak = _node(
        semantic_graph,
        "semantic-weak",
        NodeType.SEMANTIC_RULE,
        {"retrieval_text": "weak"},
    )
    strong = _node(
        semantic_graph,
        "semantic-strong",
        NodeType.SEMANTIC_RULE,
        {"retrieval_text": "strong"},
    )
    weak_strength = SemanticStrengthRecord(
        strength_id="strength-weak",
        graph_id=semantic_graph.graph_id,
        semantic_node_id=weak.node_id,
        org_id=ctx.org_id,
        namespace=namespace,
        graph_kind=semantic_graph.kind,
        owner_user_id=ctx.user_id,
        strength=SemanticStrength(support=1, contradiction=2),
        updated_at=NOW,
    )
    strong_strength = SemanticStrengthRecord(
        strength_id="strength-strong",
        graph_id=semantic_graph.graph_id,
        semantic_node_id=strong.node_id,
        org_id=ctx.org_id,
        namespace=namespace,
        graph_kind=semantic_graph.kind,
        owner_user_id=ctx.user_id,
        strength=SemanticStrength(support=2),
        updated_at=NOW,
    )
    semantic_receipt = _run(
        store.append_lifecycle_bundle(
            ctx,
            LifecycleAppendBundle(
                graphs=(semantic_graph,),
                nodes=(weak, strong),
                strengths=(weak_strength, strong_strength),
            ),
        )
    )
    assert semantic_receipt.strength_hashes == (
        (weak_strength.strength_id, weak_strength.content_hash),
        (strong_strength.strength_id, strong_strength.content_hash),
    )
    archived, delete_intents = _run(
        store.enforce_capacity(
            ctx,
            limits=limits,
            archived_at="2026-09-01T00:00:01Z",
        )
    )
    assert [node.node_id for node in archived] == [weak.node_id]
    assert archived[0].archive_reason == "semantic_strength_capacity"
    assert delete_intents[0].operation == "DELETE"


def test_namespace_advance_and_recovery_checkpoint_are_one_transaction():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    ctx = AccessContext("org-a", "alice")
    digest = "sha256:" + "a" * 64
    claim = _run(
        store.claim_namespace(
            ctx,
            experiment_id="exp",
            split="dev",
            arm_id="m2",
            task_order_hash=digest,
            config_hash=digest,
            run_nonce="00000000-0000-4000-8000-000000000201",
        )
    )
    payload = {
        "schema": "trimem/session-recovery/1.0",
        "namespace": namespace,
        "run_nonce": claim.run_nonce,
        "next_sequence_index": 1,
        "completed_task_digests": [digest],
        "lifecycle_state": {"policy": "sealed"},
    }
    advanced, checkpoint = _run(
        store.advance_namespace_with_checkpoint(
            ctx,
            run_nonce=claim.run_nonce,
            expected_current=0,
            next_sequence_index=1,
            checkpoint_payload=payload,
            checkpoint_digest=canonical_hash(payload),
        )
    )
    assert advanced.next_sequence_index == checkpoint.next_sequence_index == 1
    assert checkpoint.checkpoint_payload == payload
    assert _run(
        store.load_latest_session_checkpoint(ctx, run_nonce=claim.run_nonce)
    ) == checkpoint

    checkpoint_row = engine.tables["trimem_session_checkpoints"][
        checkpoint.checkpoint_id
    ]
    wrong_identity_payload = {
        **payload,
        "namespace": "trimem:wrong:namespace",
    }
    checkpoint_row["checkpoint_payload"] = wrong_identity_payload
    checkpoint_row["checkpoint_digest"] = canonical_hash(wrong_identity_payload)
    with pytest.raises(CanonicalReloadError, match="session checkpoint reload failed"):
        _run(store.load_latest_session_checkpoint(ctx, run_nonce=claim.run_nonce))
    checkpoint_row["checkpoint_payload"] = payload
    checkpoint_row["checkpoint_digest"] = canonical_hash(payload)

    tampered = {**payload, "next_sequence_index": 2}
    with pytest.raises(IntegrityViolation, match="digest mismatch"):
        _run(
            store.advance_namespace_with_checkpoint(
                ctx,
                run_nonce=claim.run_nonce,
                expected_current=1,
                next_sequence_index=2,
                checkpoint_payload=tampered,
                checkpoint_digest=canonical_hash(payload),
            )
        )
    assert engine.tables["trimem_namespace_claims"][namespace][
        "next_sequence_index"
    ] == 1

    rollback_engine = _FakeEngine()
    rollback_store = PostgresTriMemStore(rollback_engine, namespace=namespace)
    rollback_claim = _run(
        rollback_store.claim_namespace(
            ctx,
            experiment_id="exp",
            split="dev",
            arm_id="m2",
            task_order_hash=digest,
            config_hash=digest,
            run_nonce="00000000-0000-4000-8000-000000000202",
        )
    )
    rollback_payload = {
        **payload,
        "run_nonce": rollback_claim.run_nonce,
    }
    rollback_engine.fail_session_checkpoint_insert = True
    with pytest.raises(RuntimeError, match="checkpoint insert failure"):
        _run(
            rollback_store.advance_namespace_with_checkpoint(
                ctx,
                run_nonce=rollback_claim.run_nonce,
                expected_current=0,
                next_sequence_index=1,
                checkpoint_payload=rollback_payload,
                checkpoint_digest=canonical_hash(rollback_payload),
            )
        )
    assert rollback_engine.tables["trimem_namespace_claims"][namespace][
        "next_sequence_index"
    ] == 0
    assert rollback_engine.tables.get("trimem_session_checkpoints", {}) == {}
    assert rollback_engine.rollbacks == 1


def test_verified_episode_appends_org_visible_sanitized_promotion_evidence():
    engine = _FakeEngine()
    namespace = "trimem:exp:dev:m2"
    store = PostgresTriMemStore(engine, namespace=namespace)
    alice = AccessContext("org-a", "alice")
    graph = UserEpisodicGraph(
        graph_id="verified-episode-graph",
        org_id=alice.org_id,
        namespace=namespace,
        owner_user_id=alice.user_id,
        temporal=_temporal(),
    )
    episode = _node(
        graph,
        "verified-episode",
        NodeType.EPISODE,
        {
            "retrieval_text": "verified private content never copied to ledger",
            "verified": True,
            "source_outcome": "passed",
            "provenance": {
                "source_task_id": "private-task-id",
                "contributor_hash": canonical_hash({
                    "schema": "trimem/promotion-contributor/1.0",
                    "org_id": alice.org_id,
                    "user_id": alice.user_id,
                }),
                "public_evidence_hash": "sha256:" + "b" * 64,
                "verifier_hash": "sha256:" + "c" * 64,
                "extraction_hash": "sha256:" + "d" * 64,
            },
        },
    )
    receipt = _run(
        store.append_lifecycle_bundle(
            alice, LifecycleAppendBundle(graphs=(graph,), nodes=(episode,))
        )
    )
    assert len(receipt.promotion_evidence) == 1
    evidence = receipt.promotion_evidence[0]
    assert evidence.evidence_hash == episode.payload_hash
    raw = next(iter(engine.tables["trimem_promotion_evidence"].values()))
    assert "owner_user_id" not in raw
    assert "node_id" not in raw
    assert "source_task_id" not in raw
    assert "retrieval_text" not in repr(raw)

    visible_to_bob = _run(
        store.verify_promotion_evidence(
            AccessContext("org-a", "bob"), (episode.payload_hash,)
        )
    )
    assert visible_to_bob == (evidence,)
    raw["attestation_hash"] = "sha256:" + "e" * 64
    with pytest.raises(CanonicalReloadError, match="promotion evidence reload failed"):
        _run(
            store.verify_promotion_evidence(
                AccessContext("org-a", "bob"), (episode.payload_hash,)
            )
        )
    raw["attestation_hash"] = evidence.attestation_hash
    with pytest.raises(NotFound, match="unavailable"):
        _run(
            store.verify_promotion_evidence(
                alice, ("sha256:" + "f" * 64,)
            )
        )


def test_benchmark_identity_seed_is_idempotent_exact_and_secret_free():
    engine = _SeedFakeEngine()
    org_id = "00000000-0000-4000-8000-000000000301"
    user_id = "00000000-0000-4000-8000-000000000302"
    repository_id = "00000000-0000-4000-8000-000000000303"
    solve_job_id = "00000000-0000-4000-8000-000000000304"
    task = SimpleNamespace(
        task_id="repo__issue-1",
        org_id=org_id,
        user_id=user_id,
        repository="example/repository",
        commit="a" * 40,
        editable_paths=("src/example.py",),
    )

    def identity_resolver(observed):
        assert observed is task
        return {
            "repository_id": repository_id,
            "solve_job_id": solve_job_id,
        }

    kwargs = {
        "admin_database_url": (
            "postgresql+asyncpg://postgres:super-secret@localhost/trimem"
        ),
        "experiment_id": "experiment-1",
        "stream_id": "M2",
        "tasks": (task,),
        "identity_resolver": identity_resolver,
        "engine_factory": lambda _: engine,
    }
    first = seed_benchmark_identities(**kwargs)
    second = seed_benchmark_identities(**kwargs)

    assert first == second
    assert first["schema"] == "trimem/benchmark-identity-seed-evidence/1.0"
    assert first["admin_role"] == "postgres"
    assert first["admin_bypassrls"] is True
    assert first["rows"][0]["repository_id"] == repository_id
    permission_id = first["rows"][0]["repository_permission_id"]
    assert engine.tables["repository_permissions"][permission_id]["can_read"] is True
    assert engine.tables["repository_permissions"][permission_id]["can_modify"] is False
    assert first["rows"][0]["solve_job_id"] == solve_job_id
    assert first["digest"] == canonical_hash(
        {key: value for key, value in first.items() if key != "digest"}
    )
    assert "super-secret" not in json.dumps(first, sort_keys=True)
    assert engine.disposals == 2
    assert all(len(rows) == 1 for rows in engine.tables.values())

    engine.tables["repositories"][repository_id]["external_repo_id"] = (
        "attacker/rebound"
    )
    with pytest.raises(
        BenchmarkIdentitySeedError, match="repository identity is already bound"
    ):
        seed_benchmark_identities(**kwargs)
    assert engine.disposals == 3

    engine.tables["repositories"][repository_id]["external_repo_id"] = (
        "example/repository"
    )
    engine.tables["repository_permissions"][permission_id]["can_read"] = False
    with pytest.raises(
        BenchmarkIdentitySeedError, match="repository permission is already bound"
    ):
        seed_benchmark_identities(**kwargs)
    assert engine.disposals == 4


def test_benchmark_identity_seed_rejects_runtime_service_dsn_before_connecting():
    called = False

    def engine_factory(_):
        nonlocal called
        called = True
        return _SeedFakeEngine()

    task = SimpleNamespace(
        task_id="repo__issue-1",
        org_id="00000000-0000-4000-8000-000000000311",
        user_id="00000000-0000-4000-8000-000000000312",
        repository="example/repository",
        commit="b" * 40,
        editable_paths=(),
    )
    with pytest.raises(ValueError, match="runtime service roles cannot seed"):
        seed_benchmark_identities(
            admin_database_url=(
                "postgresql+asyncpg://api_service:api_pw@localhost/trimem"
            ),
            experiment_id="experiment-1",
            stream_id="M2",
            tasks=(task,),
            identity_resolver=lambda _: {
                "repository_id": "00000000-0000-4000-8000-000000000313",
                "solve_job_id": "00000000-0000-4000-8000-000000000314",
            },
            engine_factory=engine_factory,
        )
    assert called is False
