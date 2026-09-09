"""Durable online retention for the frozen current-v0.3 comparator arm."""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import text

from enterprise_memory.indexing.canonical_loaders import load_private_episode
from enterprise_memory.indexing.models import PRIVATE, SHARED
from enterprise_memory.indexing.projection import build_record
from enterprise_memory.indexing.qdrant_indexes import QdrantIndex
from enterprise_memory.indexing.validated_search import validated_search
from enterprise_memory.persistence.postgres import publish_outbox
from enterprise_memory.persistence.tenant_context import tenant_tx
from enterprise_memory.service.durable import (
    episode_id_for_job,
    finalize_success_atomic,
    persist_private_episode_candidate,
    persist_retrieval_candidate,
    sha as v03_sha,
)
from enterprise_memory.service.injection import plan_injection

from .accounting import canonical_bytes, sha256_bytes
from .lifecycle import LifecycleError
from .schema import AccessContext


_ID_NAMESPACE = uuid.UUID("69f56747-d4f5-44d0-864e-82bf3f1f2eb5")
V03_LIFECYCLE_SCHEMA = "trimem/live-main-v03-lifecycle/3.0"
V03_BASELINE_COMMIT = "ce10ab49586db7a859fbe5cca93051b93f9f5b55"


def _digest(value: object) -> str:
    return "sha256:" + sha256_bytes(canonical_bytes(value))


def _canonical_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise LifecycleError("%s is required" % name)
    result = value if value.startswith("sha256:") else "sha256:" + value
    if len(result) != 71:
        raise LifecycleError("%s must be a canonical sha256 digest" % name)
    try:
        int(result[7:], 16)
    except ValueError as exc:
        raise LifecycleError("%s must be a canonical sha256 digest" % name) from exc
    return result


def _callable_sha256(value: object) -> str:
    return sha256_bytes(inspect.getsource(value).encode("utf-8"))


LIVE_V03_IMPLEMENTATION_MANIFEST = {
    "source_commit": V03_BASELINE_COMMIT,
    "baseline_durable_git_blob_sha1": "6b572783aa752ebc9cf06488c6d0d29793eb3646",
    "baseline_durable_blob_sha256": "2164a2e94db776f0c1a94660ef1e24f3e566d87d03bb1c4c5e7072df67a2ce83",
    "baseline_finalize_success_atomic_ast_sha256": "7b9cc744897a2be6f70dfc0131b81c3f95a8f32f6dbc53f1fa98abca7077d69b",
    "retention_helper_sha256": _callable_sha256(persist_private_episode_candidate),
    "current_finalize_success_atomic_sha256": _callable_sha256(finalize_success_atomic),
    "publish_outbox_sha256": _callable_sha256(publish_outbox),
    "validated_search_sha256": _callable_sha256(validated_search),
    "plan_injection_sha256": _callable_sha256(plan_injection),
    "projection_sha256": _callable_sha256(build_record),
    "projection_role": "PREEXISTING_INDEX_FORMAT_ONLY_NO_FRESH_SOLVE_WRITE",
    "retrieval_audit_sha256": _callable_sha256(persist_retrieval_candidate),
    "canonical_loader_sha256": _callable_sha256(load_private_episode),
    "canonical_tables": [
        "private_episodes",
        "memory_contracts",
        "memory_contract_versions",
        "retrieval_candidates",
        "outbox_events",
    ],
    "search_path": "indexing.validated_search.validated_search",
    "injection_path": "service.injection.plan_injection",
    "retention_path": "service.durable.persist_private_episode_candidate(connection)",
    "fresh_solve_immediate_carryover": False,
    "shared_publication": False,
    "physical_index_isolation": "benchmark-namespace collections",
}
LIVE_V03_IMPLEMENTATION_HASH = _digest(LIVE_V03_IMPLEMENTATION_MANIFEST)


class _BatchEmbedder:
    """Adapt the common single-text production embedder to live-v0.3."""

    def __init__(self, delegate: object):
        if not callable(getattr(delegate, "embed", None)):
            raise TypeError("v0.3 embedder is unavailable")
        self.delegate = delegate

    def embed(self, texts):
        if not isinstance(texts, (list, tuple)):
            raise TypeError("v0.3 embedder requires a text sequence")
        return [list(self.delegate.embed(str(value))) for value in texts]


class _PhysicalV03Index:
    """Current v0.3 Qdrant semantics on an arm-isolated physical pair.

    The live product routes through global aliases.  Benchmark arms instead
    bind those exact payload/search operations to the already-fresh physical
    collections owned by the arm namespace, preventing cross-arm state while
    retaining the current ``IndexRecord`` and ``QdrantIndex`` behavior.
    """

    def __init__(self, vector_index: object):
        client = getattr(vector_index, "_client", None)
        raw_client = getattr(client, "raw_client", client)
        dimension = getattr(vector_index, "dimension", None)
        private = getattr(vector_index, "private_collection", None)
        shared = getattr(vector_index, "shared_collection", None)
        if (
            raw_client is None
            or type(dimension) is not int
            or dimension <= 0
            or not isinstance(private, str)
            or not isinstance(shared, str)
            or private == shared
        ):
            raise TypeError("arm-isolated v0.3 vector dependencies are unavailable")
        self._reader = QdrantIndex(raw_client, dimension, server=True)
        self.collections = {PRIVATE: private, SHARED: shared}

    async def search(
        self, scope, vector, org_id, owner_user_id=None, limit=10, collection=None
    ):
        if collection is not None:
            raise ValueError("v0.3 benchmark search cannot override its arm collection")
        return await asyncio.to_thread(
            self._reader._search,
            scope,
            list(vector),
            str(org_id),
            str(owner_user_id) if owner_user_id is not None else None,
            int(limit),
            self.collections[scope],
        )

def _audit_row(candidate: object) -> dict[str, Any]:
    return {
        "scope": str(getattr(candidate, "scope", "")),
        "canonical_id": getattr(candidate, "canonical_id", None),
        "canonical_version_id": getattr(candidate, "canonical_version_id", None),
        "content_hash": getattr(candidate, "content_hash", None),
        "private_owner_id": (
            getattr(candidate, "canonical_owner_id", None)
            if getattr(candidate, "scope", None) == PRIVATE
            else None
        ),
        "accepted": bool(getattr(candidate, "accepted", False)),
        "rejection_reason": getattr(candidate, "rejection_reason", None),
        "injected": bool(getattr(candidate, "injected", False)),
        "index_owner_id": getattr(candidate, "index_owner_id", None),
        "canonical_owner_id": getattr(candidate, "canonical_owner_id", None),
        "injected_view_hash": getattr(candidate, "injected_view_hash", None),
        "injected_position": getattr(candidate, "injected_position", None),
    }


def _normalized_audit_db_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scope": str(row["scope"]),
        "canonical_id": row.get("canonical_id"),
        "canonical_version_id": row.get("canonical_version_id"),
        "content_hash": row.get("content_hash"),
        "private_owner_id": (
            str(row["private_owner_id"]) if row.get("private_owner_id") else None
        ),
        "accepted": bool(row["accepted"]),
        "rejection_reason": row.get("rejection_reason"),
        "injected": bool(row["injected"]),
        "index_owner_id": (
            str(row["index_owner_id"]) if row.get("index_owner_id") else None
        ),
        "canonical_owner_id": (
            str(row["canonical_owner_id"])
            if row.get("canonical_owner_id")
            else None
        ),
        "injected_view_hash": row.get("injected_view_hash"),
        "injected_position": row.get("injected_position"),
    }


def _audit_sort_key(row: Mapping[str, Any]) -> bytes:
    return canonical_bytes(dict(row))


class LiveV03Runtime:
    """Exact current-v0.3 canonical/search/injection adapter for one arm."""

    implementation_manifest = LIVE_V03_IMPLEMENTATION_MANIFEST
    implementation_hash = LIVE_V03_IMPLEMENTATION_HASH

    def __init__(
        self,
        *,
        canonical_store: object,
        vector_index: object,
        embedder: object,
        persistence: object,
        namespace: str,
    ) -> None:
        engine = getattr(canonical_store, "_engine", None)
        bridge = getattr(persistence, "bridge", None)
        if engine is None or not callable(getattr(bridge, "call", None)):
            raise TypeError("live v0.3 PostgreSQL/async bridge is unavailable")
        self.engine = engine
        self.bridge = bridge
        self.index = _PhysicalV03Index(vector_index)
        self.embedder = _BatchEmbedder(embedder)
        self.namespace = str(namespace)

    def retention_descriptor(
        self,
        *,
        task: object,
        identity: Mapping[str, str],
        injections: tuple[Mapping[str, Any], ...],
        event_time: str,
    ) -> Mapping[str, Any]:
        repository_id = str(identity.get("repository_id", ""))
        solve_job_id = str(identity.get("solve_job_id", ""))
        try:
            uuid.UUID(repository_id)
            uuid.UUID(solve_job_id)
        except (ValueError, AttributeError) as exc:
            raise LifecycleError("v0.3 repository/solve-job identity must be UUIDs") from exc
        if not isinstance(event_time, str) or not event_time:
            raise LifecycleError("v0.3 retention event time is required")
        injected_memory_ids: list[str] = []
        for item in injections:
            if not isinstance(item, Mapping):
                raise LifecycleError("v0.3 injected-memory ledger is invalid")
            memory_id = item.get("memory_id")
            if not isinstance(memory_id, str) or not memory_id:
                raise LifecycleError("v0.3 injected memory_id is invalid")
            if memory_id in injected_memory_ids:
                raise LifecycleError("v0.3 injected memory_id is duplicated")
            injected_memory_ids.append(memory_id)
        if len(injected_memory_ids) > 2:
            raise LifecycleError("v0.3 baseline cannot retain more than two injections")

        # This is deliberately byte-for-byte the object assembled by the live
        # v0.3 solve finalizer.  The common extractor still runs for matched
        # compute, but its output must not improve or otherwise alter M1.
        canonical = {
            "task_id": str(task.task_id),
            "repo_id": repository_id,
            "commit": str(task.commit),
            "outcome": "success",
            "injected_memory_ids": injected_memory_ids,
        }
        episode_id = episode_id_for_job(solve_job_id)
        content_hash = "sha256:" + v03_sha(
            json.dumps(canonical, sort_keys=True)
        )[:32]
        outbox = {
            "event_type": "CONTRACT_CANDIDATE",
            "aggregate_type": "private_episode",
            "aggregate_id": episode_id,
            "aggregate_version": 1,
            "payload": {"job_id": solve_job_id},
        }
        body = {
            "schema": "trimem/live-v03-retention-descriptor/2.0",
            "namespace": self.namespace,
            "org_id": str(task.org_id),
            "user_id": str(task.user_id),
            "episode_id": episode_id,
            "solve_job_id": solve_job_id,
            "repository_id": repository_id,
            "task_id": str(task.task_id),
            "source_commit": str(task.commit),
            "content_hash": content_hash,
            "canonical": canonical,
            "event_time": event_time,
            "outbox": outbox,
        }
        return {**body, "digest": _digest(body)}

    def _validated_descriptor(self, value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LifecycleError("v0.3 retention descriptor is invalid")
        body = {key: deepcopy(item) for key, item in value.items() if key != "digest"}
        required = {
            "schema", "namespace", "org_id", "user_id", "episode_id",
            "solve_job_id", "repository_id", "task_id", "source_commit",
            "content_hash", "canonical", "event_time", "outbox",
        }
        if (
            set(body) != required
            or body.get("schema") != "trimem/live-v03-retention-descriptor/2.0"
            or body.get("namespace") != self.namespace
            or value.get("digest") != _digest(body)
        ):
            raise LifecycleError("v0.3 retention descriptor lock mismatch")
        canonical = body.get("canonical")
        if not isinstance(canonical, Mapping) or set(canonical) != {
            "task_id", "repo_id", "commit", "outcome", "injected_memory_ids"
        }:
            raise LifecycleError("v0.3 canonical solve episode shape mismatch")
        if (
            canonical.get("task_id") != body["task_id"]
            or canonical.get("repo_id") != body["repository_id"]
            or canonical.get("commit") != body["source_commit"]
            or canonical.get("outcome") != "success"
            or episode_id_for_job(str(body["solve_job_id"])) != body["episode_id"]
            or "sha256:" + v03_sha(json.dumps(canonical, sort_keys=True))[:32]
            != body["content_hash"]
        ):
            raise LifecycleError("v0.3 canonical solve episode identity mismatch")
        injected = canonical.get("injected_memory_ids")
        if (
            not isinstance(injected, list)
            or len(injected) > 2
            or len(set(injected)) != len(injected)
            or any(not isinstance(item, str) or not item for item in injected)
        ):
            raise LifecycleError("v0.3 canonical injection ledger is invalid")
        for field in (
            "org_id", "user_id", "episode_id", "solve_job_id", "repository_id",
            "task_id", "source_commit", "content_hash", "event_time",
        ):
            if not isinstance(body[field], str) or not body[field]:
                raise LifecycleError("v0.3 retention descriptor field is invalid")
        for field in ("org_id", "user_id", "episode_id", "solve_job_id", "repository_id"):
            try:
                uuid.UUID(body[field])
            except (ValueError, AttributeError) as exc:
                raise LifecycleError("v0.3 retention UUID field is invalid") from exc
        expected_outbox = {
            "event_type": "CONTRACT_CANDIDATE",
            "aggregate_type": "private_episode",
            "aggregate_id": body["episode_id"],
            "aggregate_version": 1,
            "payload": {"job_id": body["solve_job_id"]},
        }
        if body.get("outbox") != expected_outbox:
            raise LifecycleError("v0.3 retention outbox lock mismatch")
        return {**body, "digest": str(value["digest"])}

    def retain_episode(self, descriptor: Mapping[str, Any]) -> Mapping[str, Any]:
        locked = self._validated_descriptor(descriptor)
        return self.bridge.call(self._retain_episode(locked))

    @staticmethod
    def _expected_episode_row(descriptor: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "episode_id": str(descriptor["episode_id"]),
            "org_id": str(descriptor["org_id"]),
            "owner_user_id": str(descriptor["user_id"]),
            "repository_id": str(descriptor["repository_id"]),
            "task_id": None,
            "source_commit": None,
            "canonical": deepcopy(dict(descriptor["canonical"])),
            "content_hash": str(descriptor["content_hash"]),
            "state": "success",
        }

    @staticmethod
    def _expected_outbox_row(descriptor: Mapping[str, Any]) -> dict[str, Any]:
        outbox = descriptor["outbox"]
        return {
            "event_type": str(outbox["event_type"]),
            "aggregate_type": str(outbox["aggregate_type"]),
            "aggregate_id": str(outbox["aggregate_id"]),
            "aggregate_version": int(outbox["aggregate_version"]),
            "payload": deepcopy(dict(outbox["payload"])),
            "status": "PENDING",
            "attempts": 0,
            "max_attempts": 5,
            "lease_owner": None,
            "lease_expires_at": None,
            "error_detail_sanitized": None,
            "processed_at": None,
        }

    async def _retention_pair_state_in_tx(
        self, connection: object, descriptor: Mapping[str, Any]
    ) -> str:
        episode_result = await connection.execute(
            text(
                "SELECT id,org_id,owner_user_id,repository_id,task_id,source_commit,"
                "canonical_json,content_hash,state FROM private_episodes "
                "WHERE org_id=CAST(:org AS uuid) AND id=CAST(:episode AS uuid)"
            ),
            {"org": descriptor["org_id"], "episode": descriptor["episode_id"]},
        )
        raw_episode = episode_result.mappings().first()
        outbox_result = await connection.execute(
            text(
                "SELECT event_type,aggregate_type,aggregate_id,aggregate_version,"
                "payload_json,status,attempts,max_attempts,lease_owner,lease_expires_at,"
                "error_detail_sanitized,processed_at FROM outbox_events "
                "WHERE org_id=CAST(:org AS uuid) AND aggregate_id=CAST(:episode AS uuid) "
                "ORDER BY event_type,aggregate_type,aggregate_version,id"
            ),
            {"org": descriptor["org_id"], "episode": descriptor["episode_id"]},
        )
        raw_outbox = outbox_result.mappings().all()
        if raw_episode is None and not raw_outbox:
            return "ABSENT"
        if raw_episode is None or len(raw_outbox) != 1:
            raise LifecycleError(
                "v0.3 retention is not one atomic episode/outbox pair"
            )
        episode = dict(raw_episode)
        canonical = episode["canonical_json"]
        if isinstance(canonical, str):
            canonical = json.loads(canonical)
        observed_episode = {
            "episode_id": str(episode["id"]),
            "org_id": str(episode["org_id"]),
            "owner_user_id": str(episode["owner_user_id"]),
            "repository_id": (
                str(episode["repository_id"])
                if episode.get("repository_id") is not None
                else None
            ),
            "task_id": episode.get("task_id"),
            "source_commit": episode.get("source_commit"),
            "canonical": canonical,
            "content_hash": episode["content_hash"],
            "state": episode["state"],
        }
        event = dict(raw_outbox[0])
        payload = event["payload_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        observed_outbox = {
            "event_type": event["event_type"],
            "aggregate_type": event["aggregate_type"],
            "aggregate_id": str(event["aggregate_id"]),
            "aggregate_version": event["aggregate_version"],
            "payload": payload,
            "status": event["status"],
            "attempts": event["attempts"],
            "max_attempts": event["max_attempts"],
            "lease_owner": event.get("lease_owner"),
            "lease_expires_at": event.get("lease_expires_at"),
            "error_detail_sanitized": event.get("error_detail_sanitized"),
            "processed_at": event.get("processed_at"),
        }
        if observed_episode != self._expected_episode_row(descriptor):
            raise LifecycleError("v0.3 pending episode differs from checkpoint")
        if observed_outbox != self._expected_outbox_row(descriptor):
            raise LifecycleError("v0.3 pending outbox differs from checkpoint")
        return "EXACT_PENDING_APPEND"

    async def _retain_episode(self, descriptor: Mapping[str, Any]):
        canonical = dict(descriptor["canonical"])
        episode_id = str(descriptor["episode_id"])
        repository_id = str(descriptor["repository_id"])
        solve_job_id = str(descriptor["solve_job_id"])
        content_hash = str(descriptor["content_hash"])
        ctx = AccessContext(str(descriptor["org_id"]), str(descriptor["user_id"]))
        async with tenant_tx(self.engine, ctx.org_id, ctx.user_id) as connection:
            before = await self._retention_pair_state_in_tx(connection, descriptor)
            if before == "ABSENT":
                appended_id, appended_hash = await persist_private_episode_candidate(
                    connection,
                    org_id=ctx.org_id,
                    user_id=ctx.user_id,
                    repo_id=repository_id,
                    job_id=solve_job_id,
                    episode_canonical=canonical,
                )
                if appended_id != episode_id or appended_hash != content_hash:
                    raise LifecycleError("v0.3 durable retention identity changed")
            after = await self._retention_pair_state_in_tx(connection, descriptor)
            if after != "EXACT_PENDING_APPEND":
                raise LifecycleError("v0.3 atomic retention append is incomplete")
        pair = {
            "episode": self._expected_episode_row(descriptor),
            "outbox": self._expected_outbox_row(descriptor),
        }
        evidence = {
            "schema": "trimem/live-v03-retention-evidence/2.0",
            "namespace": self.namespace,
            "episode_id": episode_id,
            "solve_job_id": solve_job_id,
            "repository_id": repository_id,
            "content_hash": content_hash,
            "atomic_pair_digest": _digest(pair),
        }
        return {**evidence, "digest": _digest(evidence)}

    def verify_pending_retention(
        self, descriptor: Mapping[str, Any]
    ) -> str:
        """Allow only absence or the exact one prepared live-v0.3 append.

        A process can die after the atomic episode/outbox transaction and before
        the agent writes its LIFECYCLE_STORED checkpoint.  The EXTRACTED
        checkpoint seals this descriptor, so resume may accept precisely this
        one pair.  Row-only, outbox-only, duplicate, or altered state remains a
        hard failure.
        """
        locked = self._validated_descriptor(descriptor)
        return self.bridge.call(self._verify_pending_retention(locked))

    async def _verify_pending_retention(self, descriptor: Mapping[str, Any]) -> str:
        async with tenant_tx(
            self.engine,
            str(descriptor["org_id"]),
            str(descriptor["user_id"]),
        ) as connection:
            return await self._retention_pair_state_in_tx(connection, descriptor)

    def recall_plan(
        self, *, task: object, identity: Mapping[str, str]
    ) -> Mapping[str, Any]:
        return self.bridge.call(self._recall_plan(task=task, identity=identity))

    async def _recall_plan(self, *, task, identity):
        org_id = str(task.org_id)
        user_id = str(task.user_id)
        solve_job_id = str(identity.get("solve_job_id", ""))
        try:
            uuid.UUID(solve_job_id)
        except (ValueError, AttributeError) as exc:
            raise LifecycleError("v0.3 solve_job_id must be a UUID") from exc
        private = await validated_search(
            self.engine,
            self.index,
            self.embedder,
            PRIVATE,
            org_id,
            str(task.instruction),
            user_id=user_id,
            limit=5,
        )
        shared = await validated_search(
            self.engine,
            self.index,
            self.embedder,
            SHARED,
            org_id,
            str(task.instruction),
            user_id=user_id,
            limit=5,
        )
        rejected = [
            row for row in (*private.audit, *shared.audit) if not row.get("accepted")
        ]
        plan = plan_injection(
            private.hits,
            shared.hits,
            requester_id=user_id,
            repo_id=str(identity.get("repository_id", "")),
            rejected_audit=rejected,
            max_injected=2,
        )
        planned = [_audit_row(candidate) for candidate in plan.candidates]
        await self._persist_audit(
            org_id=org_id, solve_job_id=solve_job_id, planned=planned
        )
        audit = await self._audit_evidence(org_id, solve_job_id)
        return {
            "plan": plan,
            "audit": audit,
            "private_hits": len(private.hits),
            "shared_hits": len(shared.hits),
            "rejected_candidates": len(rejected),
        }

    async def _audit_rows(self, org_id: str, solve_job_id: str):
        async with tenant_tx(self.engine, org_id) as connection:
            result = await connection.execute(
                text(
                    "SELECT scope,canonical_id,canonical_version_id,content_hash,"
                    "private_owner_id,accepted,rejection_reason,injected,index_owner_id,"
                    "canonical_owner_id,injected_view_hash,injected_position "
                    "FROM retrieval_candidates WHERE job_id=CAST(:job AS uuid)"
                ),
                {"job": solve_job_id},
            )
            rows = result.mappings().all()
        return [_normalized_audit_db_row(dict(row)) for row in rows]

    async def _persist_audit(self, *, org_id, solve_job_id, planned):
        existing = await self._audit_rows(org_id, solve_job_id)
        unmatched = list(existing)
        missing = []
        for expected in planned:
            try:
                index = unmatched.index(expected)
            except ValueError:
                missing.append(expected)
            else:
                unmatched.pop(index)
        if unmatched:
            raise LifecycleError("v0.3 retrieval audit contains unexpected rows")
        for row in missing:
            await persist_retrieval_candidate(
                self.engine,
                org_id,
                solve_job_id,
                **row,
            )
        observed = await self._audit_rows(org_id, solve_job_id)
        if sorted(observed, key=_audit_sort_key) != sorted(planned, key=_audit_sort_key):
            raise LifecycleError("v0.3 retrieval audit reload mismatch")

    async def _audit_evidence(self, org_id: str, solve_job_id: str):
        rows = sorted(
            await self._audit_rows(org_id, solve_job_id), key=_audit_sort_key
        )
        body = {
            "schema": "trimem/live-v03-retrieval-audit/1.0",
            "namespace": self.namespace,
            "solve_job_id": solve_job_id,
            "rows": rows,
        }
        return {**body, "digest": _digest(body)}

    def verify_audit(self, *, org_id: str, evidence: Mapping[str, Any]) -> None:
        body = {key: value for key, value in evidence.items() if key != "digest"}
        if (
            evidence.get("schema") != "trimem/live-v03-retrieval-audit/1.0"
            or evidence.get("namespace") != self.namespace
            or evidence.get("digest") != _digest(body)
        ):
            raise LifecycleError("v0.3 retrieval audit evidence is invalid")
        observed = self.bridge.call(
            self._audit_evidence(org_id, str(evidence.get("solve_job_id", "")))
        )
        if observed != dict(evidence):
            raise LifecycleError("v0.3 retrieval audit changed after checkpoint")

    def verify_audit_digest(
        self, *, org_id: str, solve_job_id: str, expected_digest: str
    ) -> None:
        observed = self.bridge.call(self._audit_evidence(org_id, solve_job_id))
        if observed.get("digest") != expected_digest:
            raise LifecycleError("v0.3 retrieval audit digest changed after checkpoint")

    def state_evidence(
        self, *, org_id: str, user_id: str, episode_ids: tuple[str, ...] = ()
    ) -> Mapping[str, Any]:
        return self.bridge.call(self._state_evidence(org_id, user_id, episode_ids))

    async def _state_evidence(
        self, org_id: str, user_id: str, episode_ids: tuple[str, ...]
    ):
        if (
            not isinstance(episode_ids, tuple)
            or len(set(episode_ids)) != len(episode_ids)
        ):
            raise LifecycleError("v0.3 canonical episode-id ledger is invalid")
        for episode_id in episode_ids:
            try:
                uuid.UUID(episode_id)
            except (ValueError, AttributeError) as exc:
                raise LifecycleError("v0.3 canonical episode-id is invalid") from exc
        async with tenant_tx(self.engine, org_id, user_id) as connection:
            result = await connection.execute(
                text(
                    "SELECT id,repository_id,task_id,source_commit,content_hash,"
                    "canonical_json,state "
                    "FROM private_episodes "
                    "WHERE org_id=CAST(:org AS uuid) "
                    "AND owner_user_id=CAST(:owner AS uuid) ORDER BY id"
                ),
                {"org": org_id, "owner": user_id},
            )
            raw_rows = result.mappings().all()
            outbox_result = await connection.execute(
                text(
                    "SELECT o.event_type,o.aggregate_type,o.aggregate_id,"
                    "o.aggregate_version,o.payload_json,o.status,o.attempts,"
                    "o.max_attempts,o.lease_owner,o.lease_expires_at,"
                    "o.error_detail_sanitized,o.processed_at "
                    "FROM outbox_events o JOIN solve_jobs j "
                    "ON j.org_id=o.org_id "
                    "AND j.id::text=o.payload_json->>'job_id' "
                    "WHERE o.org_id=CAST(:org AS uuid) "
                    "AND j.submitter_user_id=CAST(:owner AS uuid) "
                    "AND o.event_type='CONTRACT_CANDIDATE' "
                    "AND o.aggregate_type='private_episode' "
                    "ORDER BY o.aggregate_id,o.event_type,o.aggregate_type,"
                    "o.aggregate_version,o.id"
                ),
                {"org": org_id, "owner": user_id},
            )
            raw_outbox_rows = outbox_result.mappings().all()
        rows = []
        for raw in raw_rows:
            row = dict(raw)
            canonical = row["canonical_json"]
            if isinstance(canonical, str):
                canonical = json.loads(canonical)
            rows.append(
                {
                    "episode_id": str(row["id"]),
                    "repository_id": (
                        str(row["repository_id"])
                        if row.get("repository_id")
                        else None
                    ),
                    "task_id": row.get("task_id"),
                    "source_commit": row.get("source_commit"),
                    "canonical_task_id": canonical.get("task_id"),
                    "canonical_source_commit": canonical.get("commit"),
                    "content_hash": row["content_hash"],
                    "canonical_hash": _digest(canonical),
                    "state": row["state"],
                }
            )
        outbox_rows = []
        for raw in raw_outbox_rows:
            row = dict(raw)
            payload = row["payload_json"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            outbox_rows.append({
                "event_type": row["event_type"],
                "aggregate_type": row["aggregate_type"],
                "aggregate_id": str(row["aggregate_id"]),
                "aggregate_version": row["aggregate_version"],
                "payload": payload,
                "status": row["status"],
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
                "lease_owner": row.get("lease_owner"),
                "lease_expires_at": (
                    row["lease_expires_at"].isoformat()
                    if row.get("lease_expires_at") is not None
                    else None
                ),
                "error_detail_sanitized": row.get("error_detail_sanitized"),
                "processed_at": (
                    row["processed_at"].isoformat()
                    if row.get("processed_at") is not None
                    else None
                ),
            })
        observed_ids = {row["episode_id"] for row in rows}
        if not set(episode_ids) <= observed_ids:
            raise LifecycleError("v0.3 checkpoint stream episode is missing")
        body = {
            "schema": "trimem/live-v03-canonical-state/2.0",
            "namespace": self.namespace,
            "org_id": org_id,
            "user_id": user_id,
            "stream_episode_ids": list(sorted(episode_ids)),
            "rows": rows,
            "outbox_rows": outbox_rows,
        }
        return {**body, "digest": _digest(body)}

    def verify_state(
        self,
        evidence: Mapping[str, Any],
        *,
        pending_descriptor: Optional[Mapping[str, Any]] = None,
    ) -> str:
        body = {key: value for key, value in evidence.items() if key != "digest"}
        if (
            evidence.get("schema") != "trimem/live-v03-canonical-state/2.0"
            or evidence.get("namespace") != self.namespace
            or evidence.get("digest") != _digest(body)
        ):
            raise LifecycleError("v0.3 canonical state evidence is invalid")
        observed = self.state_evidence(
            org_id=str(evidence.get("org_id", "")),
            user_id=str(evidence.get("user_id", "")),
            episode_ids=tuple(evidence.get("stream_episode_ids", ())),
        )
        if pending_descriptor is None:
            if observed != dict(evidence):
                raise LifecycleError("v0.3 canonical state changed after checkpoint")
            return "EXACT_STATE"
        descriptor = self._validated_descriptor(pending_descriptor)
        pending_status = self.verify_pending_retention(descriptor)
        if (
            descriptor["org_id"] != evidence.get("org_id")
            or descriptor["user_id"] != evidence.get("user_id")
            or descriptor["episode_id"] in {
                row.get("episode_id") for row in evidence.get("rows", ())
                if isinstance(row, Mapping)
            }
            or descriptor["episode_id"] in {
                row.get("aggregate_id")
                for row in evidence.get("outbox_rows", ())
                if isinstance(row, Mapping)
            }
        ):
            raise LifecycleError("v0.3 pending canonical-state identity is invalid")
        expected_body = {
            key: deepcopy(value)
            for key, value in evidence.items()
            if key != "digest"
        }
        expected_body["rows"] = sorted(
            [
                *list(expected_body.get("rows", ())),
                {
                    "episode_id": descriptor["episode_id"],
                    "repository_id": descriptor["repository_id"],
                    "task_id": None,
                    "source_commit": None,
                    "canonical_task_id": descriptor["task_id"],
                    "canonical_source_commit": descriptor["source_commit"],
                    "content_hash": descriptor["content_hash"],
                    "canonical_hash": _digest(descriptor["canonical"]),
                    "state": "success",
                },
            ],
            key=lambda row: row["episode_id"],
        )
        expected_body["outbox_rows"] = sorted(
            [
                *list(expected_body.get("outbox_rows", ())),
                self._expected_outbox_row(descriptor),
            ],
            key=lambda row: (
                row["aggregate_id"],
                row["event_type"],
                row["aggregate_type"],
                row["aggregate_version"],
            ),
        )
        expected = {**expected_body, "digest": _digest(expected_body)}
        if observed == dict(evidence) and pending_status == "ABSENT":
            return "ABSENT"
        if observed == expected and pending_status == "EXACT_PENDING_APPEND":
            return "EXACT_PENDING_APPEND"
        raise LifecycleError(
            "v0.3 canonical state is neither base nor the exact pending append"
        )


class PostgresTaskIdentityResolver:
    """Synchronous facade over the canonical DB resolver on the session loop."""

    def __init__(self, canonical_store: object, persistence: object):
        method = getattr(canonical_store, "resolve_task_identity", None)
        bridge = getattr(persistence, "bridge", None)
        if not callable(method) or not callable(getattr(bridge, "call", None)):
            raise TypeError("canonical task identity resolver dependencies are unavailable")
        self.store = canonical_store
        self.bridge = bridge

    def __call__(self, task: object) -> Mapping[str, str]:
        return self.bridge.call(
            self.store.resolve_task_identity(
                AccessContext(str(task.org_id), str(task.user_id)),
                repository_slug=str(task.repository),
                task_id=str(task.task_id),
            )
        )


class PostgresV03ExperienceLifecycle:
    """Retain completed solves in the exact live-main v0.3 private path.

    This comparator intentionally does not apply TriMem's verified-semantic or
    extractor secret gates.  Current v0.3 finalizes a five-field private solve
    episode for a completed pipeline even when the external benchmark grade is
    unsuccessful; that grade remains separate benchmark evidence.
    """

    configuration_hash = _digest({
        "schema": V03_LIFECYCLE_SCHEMA,
        "implementation_hash": LIVE_V03_IMPLEMENTATION_HASH,
        "retention": "exact-solve-worker-episode-plus-candidate-outbox",
        "retrieval": "validated_search-plus-plan_injection-whole-task-once",
        "fresh_solve_private_view": "not-indexed-by-current-solve-path",
        "shared_publication": False,
    })

    def __init__(
        self,
        runtime: object,
        *,
        namespace: str,
        identity_resolver: object,
        clock: Optional[object] = None,
    ) -> None:
        if not namespace or namespace == "unit-test":
            raise LifecycleError("production v0.3 lifecycle requires an exact namespace")
        for method in (
            "retention_descriptor",
            "retain_episode",
            "verify_pending_retention",
            "recall_plan",
            "verify_audit",
            "verify_audit_digest",
            "state_evidence",
            "verify_state",
        ):
            if not callable(getattr(runtime, method, None)):
                raise TypeError("live v0.3 runtime lacks %s" % method)
        if getattr(runtime, "implementation_hash", None) != LIVE_V03_IMPLEMENTATION_HASH:
            raise TypeError("live v0.3 runtime implementation lock mismatch")
        if not callable(identity_resolver):
            raise TypeError("identity_resolver is required")
        self.runtime = runtime
        self.namespace = namespace
        self.identity_resolver = identity_resolver
        self.clock = clock or (
            lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        self.stored_task_ids: dict[str, str] = {}
        self.stored_retention_descriptors: dict[str, dict[str, Any]] = {}
        self.prepared_task_times: dict[str, dict[str, Any]] = {}
        self.pending_retention: Optional[dict[str, Any]] = None
        self._ctx: Optional[AccessContext] = None

    def _uuid(self, label: str) -> str:
        return str(uuid.uuid5(_ID_NAMESPACE, self.namespace + "|" + label))

    def before_task(self, *, task: object, sequence_index: int) -> None:
        if type(sequence_index) is not int or sequence_index < 0:
            raise LifecycleError("sequence_index must be non-negative")
        task_id = str(getattr(task, "task_id", ""))
        if not task_id:
            raise LifecycleError("task_id is required")
        ctx = AccessContext(str(task.org_id), str(task.user_id))
        if self._ctx is not None and self._ctx != ctx:
            raise LifecycleError("v0.3 stream access context changed")
        self._ctx = ctx
        existing = self.prepared_task_times.get(task_id)
        if existing is not None:
            if existing.get("sequence_index") != sequence_index:
                raise LifecycleError("task event-time sequence mismatch")
            return
        self.prepared_task_times[task_id] = {
            "sequence_index": sequence_index,
            "event_time": self.clock(),
        }

    def after_task(self, *, task: object, result: object) -> None:
        return None

    def prepared_event_time(self, task: object) -> str:
        task_id = str(getattr(task, "task_id", ""))
        prepared = self.prepared_task_times.get(task_id)
        if prepared is None or not isinstance(prepared.get("event_time"), str):
            raise LifecycleError("v0.3 task event time was not prepared")
        return str(prepared["event_time"])

    def prepare_store_experience(self, task, extraction, grade, injections) -> None:
        """Seal the exact next canonical append into the EXTRACTED checkpoint."""
        task_id = str(getattr(task, "task_id", ""))
        if not task_id:
            raise LifecycleError("v0.3 retention task_id is required")
        if task_id in self.stored_task_ids:
            if self.pending_retention is not None:
                raise LifecycleError("v0.3 stored task also has pending retention")
            return
        identity = dict(self.identity_resolver(task))
        prepared = self.prepared_task_times.get(task_id)
        if prepared is None:
            now = self.clock()
            self.prepared_task_times[task_id] = {
                "sequence_index": None,
                "event_time": now,
            }
        else:
            now = str(prepared["event_time"])
        descriptor = dict(
            self.runtime.retention_descriptor(
                task=task,
                identity=identity,
                injections=tuple(injections),
                event_time=now,
            )
        )
        if self.pending_retention is not None:
            if self.pending_retention != descriptor:
                raise LifecycleError("v0.3 has a different pending retention")
            return
        self.pending_retention = descriptor

    def store_experience(self, task, graph, extraction, grade, injections):
        task_id = str(task.task_id)
        if task_id in self.stored_task_ids:
            memory_id = self.stored_task_ids[task_id]
            return {
                "storage_action": "V03_RETAIN_PRIVATE_EPISODE",
                "memory_id": memory_id,
                "paid_model_calls": 0,
                "retained_records": 0,
                "archived_records": 0,
                "net_memory_growth": 0,
                "pending_candidate_outbox_events": 0,
                "fresh_solve_immediate_carryover": 0,
                "idempotent_replay": True,
            }
        if self.pending_retention is None:
            self.prepare_store_experience(task, extraction, grade, injections)
        descriptor = self.pending_retention
        if descriptor is None or descriptor.get("task_id") != task_id:
            raise LifecycleError("v0.3 pending retention task mismatch")
        receipt = self.runtime.retain_episode(descriptor)
        memory_id = str(receipt.get("episode_id", ""))
        if (
            not memory_id
            or memory_id != descriptor.get("episode_id")
            or receipt.get("namespace") != self.namespace
        ):
            raise LifecycleError("live v0.3 retention receipt is invalid")
        self.stored_task_ids[task_id] = memory_id
        self.stored_retention_descriptors[task_id] = deepcopy(dict(descriptor))
        self.pending_retention = None
        return {
            "storage_action": "V03_RETAIN_PRIVATE_EPISODE",
            "memory_id": memory_id,
            "receipt_digest": receipt["digest"],
            "paid_model_calls": 0,
            "retained_records": 1,
            "archived_records": 0,
            "net_memory_growth": 1,
            "pending_candidate_outbox_events": 1,
            "fresh_solve_immediate_carryover": 0,
        }

    def credit_outcome(self, task, grade, injections, *, outcome_metrics=None):
        return {"credited": 0, "baseline": "v0.3-no-learned-credit"}

    def verify_inflight_external_state(
        self,
        *,
        prior_canonical: Mapping[str, Any],
        current_canonical: Mapping[str, Any],
        prior_qdrant: Mapping[str, Any],
        current_qdrant: Mapping[str, Any],
        prior_receipts: Mapping[str, Any],
        current_receipts: Mapping[str, Any],
        checkpoint_state: Mapping[str, Any],
        checkpoint_phase: str,
        checkpoint_task_id: str,
    ) -> Mapping[str, Any]:
        """Verify M1's old-table pair without waiving any external drift.

        A live-v0.3 solve writes only its private episode and candidate event.
        TriMem canonical rows, TriMem receipts, and Qdrant must therefore be
        byte-identical across the crash window.
        """
        payload = checkpoint_state.get("payload")
        if (
            not isinstance(payload, Mapping)
            or checkpoint_state.get("digest") != _digest(payload)
            or payload.get("schema") != V03_LIFECYCLE_SCHEMA
            or payload.get("namespace") != self.namespace
            or payload.get("configuration_hash") != self.configuration_hash
            or payload.get("implementation_hash") != LIVE_V03_IMPLEMENTATION_HASH
        ):
            raise LifecycleError("v0.3 in-flight lifecycle proof is invalid")
        if checkpoint_phase == "EXTRACTED":
            descriptor = payload.get("pending_retention")
            if not isinstance(descriptor, Mapping):
                raise LifecycleError("v0.3 EXTRACTED proof has no pending retention")
        elif checkpoint_phase in {
            "LIFECYCLE_STORED", "LIFECYCLE_CREDITED", "DONE"
        }:
            descriptors = payload.get("stored_retention_descriptors")
            if not isinstance(descriptors, Mapping):
                raise LifecycleError("v0.3 stored proof has no retention ledger")
            descriptor = descriptors.get(checkpoint_task_id)
            if not isinstance(descriptor, Mapping):
                raise LifecycleError("v0.3 stored proof has no task retention")
            stored_ids = payload.get("stored_task_ids")
            if (
                not isinstance(stored_ids, Mapping)
                or stored_ids.get(checkpoint_task_id) != descriptor.get("episode_id")
                or payload.get("pending_retention") is not None
            ):
                raise LifecycleError("v0.3 stored retention ledger is inconsistent")
        else:
            raise LifecycleError("v0.3 checkpoint phase cannot contain retention drift")
        access = payload.get("access_context")
        if (
            not isinstance(access, Mapping)
            or set(access) != {"org_id", "user_id"}
            or descriptor.get("org_id") != access.get("org_id")
            or descriptor.get("user_id") != access.get("user_id")
            or descriptor.get("task_id") != checkpoint_task_id
        ):
            raise LifecycleError("v0.3 retention proof task/access context mismatch")
        canonical_v03_state = payload.get("canonical_v03_state")
        if not isinstance(canonical_v03_state, Mapping):
            raise LifecycleError("v0.3 in-flight proof has no owner-wide state seal")
        state_status = self.runtime.verify_state(
            canonical_v03_state,
            pending_descriptor=(
                descriptor if checkpoint_phase == "EXTRACTED" else None
            ),
        )
        expected_state_status = (
            "EXACT_PENDING_APPEND"
            if checkpoint_phase == "EXTRACTED"
            else "EXACT_STATE"
        )
        if state_status != expected_state_status:
            raise LifecycleError("v0.3 crash state has no exact atomic append")
        if self.runtime.verify_pending_retention(descriptor) != "EXACT_PENDING_APPEND":
            raise LifecycleError("v0.3 pending pair proof changed during recovery")
        if canonical_bytes(prior_canonical) != canonical_bytes(current_canonical):
            raise LifecycleError("v0.3 in-flight append changed TriMem canonical rows")
        if canonical_bytes(prior_receipts) != canonical_bytes(current_receipts):
            raise LifecycleError("v0.3 in-flight append changed TriMem receipts")
        if canonical_bytes(prior_qdrant) != canonical_bytes(current_qdrant):
            raise LifecycleError("v0.3 in-flight append changed Qdrant")
        body = {
            "schema": "trimem/live-v03-inflight-external-proof/1.0",
            "namespace": self.namespace,
            "checkpoint_phase": checkpoint_phase,
            "checkpoint_task_id": checkpoint_task_id,
            "retention_descriptor_digest": descriptor.get("digest"),
            "episode_id": descriptor.get("episode_id"),
            "retention_pair_status": "EXACT_PENDING_APPEND",
            "canonical_evidence_digest": _digest(prior_canonical),
            "receipt_evidence_digest": _digest(prior_receipts),
            "qdrant_evidence_digest": _digest(prior_qdrant),
            "verified": True,
        }
        return {**body, "proof_digest": _digest(body)}

    def checkpoint_state(self) -> Mapping[str, Any]:
        canonical_state = None
        if self._ctx is not None:
            canonical_state = self.runtime.state_evidence(
                org_id=self._ctx.org_id,
                user_id=self._ctx.user_id,
                episode_ids=tuple(sorted(self.stored_task_ids.values())),
            )
        payload = {
            "schema": V03_LIFECYCLE_SCHEMA,
            "namespace": self.namespace,
            "configuration_hash": self.configuration_hash,
            "implementation_hash": LIVE_V03_IMPLEMENTATION_HASH,
            "stored_task_ids": dict(sorted(self.stored_task_ids.items())),
            "stored_retention_descriptors": {
                key: deepcopy(self.stored_retention_descriptors[key])
                for key in sorted(self.stored_retention_descriptors)
            },
            "prepared_task_times": self.prepared_task_times,
            "pending_retention": deepcopy(self.pending_retention),
            "access_context": (
                {"org_id": self._ctx.org_id, "user_id": self._ctx.user_id}
                if self._ctx is not None
                else None
            ),
            "canonical_v03_state": canonical_state,
        }
        frozen = deepcopy(payload)
        return {"payload": frozen, "digest": _digest(frozen)}

    def restore_state(self, value: Mapping[str, Any]) -> None:
        payload = value.get("payload")
        if not isinstance(payload, Mapping) or _digest(payload) != value.get("digest"):
            raise LifecycleError("v0.3 lifecycle checkpoint digest mismatch")
        if (
            payload.get("schema") != V03_LIFECYCLE_SCHEMA
            or payload.get("namespace") != self.namespace
            or payload.get("configuration_hash") != self.configuration_hash
        ):
            raise LifecycleError("v0.3 lifecycle checkpoint identity mismatch")
        if payload.get("implementation_hash") != LIVE_V03_IMPLEMENTATION_HASH:
            raise LifecycleError("v0.3 implementation checkpoint mismatch")
        rows = payload.get("stored_task_ids")
        if not isinstance(rows, Mapping) or any(
            not isinstance(key, str) or not isinstance(item, str)
            for key, item in rows.items()
        ):
            raise LifecycleError("v0.3 lifecycle checkpoint ledger is invalid")
        stored_task_ids = {str(key): str(item) for key, item in rows.items()}
        raw_descriptors = payload.get("stored_retention_descriptors")
        if not isinstance(raw_descriptors, Mapping) or set(raw_descriptors) != set(
            stored_task_ids
        ) or any(not isinstance(item, Mapping) for item in raw_descriptors.values()):
            raise LifecycleError("v0.3 stored retention descriptor ledger is invalid")
        stored_descriptors = {
            str(key): deepcopy(dict(item)) for key, item in raw_descriptors.items()
        }
        if any(
            stored_task_ids[key] != item.get("episode_id")
            for key, item in stored_descriptors.items()
        ):
            raise LifecycleError("v0.3 stored retention descriptor identity mismatch")
        pending = payload.get("pending_retention")
        if pending is not None and not isinstance(pending, Mapping):
            raise LifecycleError("v0.3 pending retention checkpoint is invalid")
        raw_ctx = payload.get("access_context")
        canonical_state = payload.get("canonical_v03_state")
        if raw_ctx is None:
            if canonical_state is not None or pending is not None or stored_task_ids:
                raise LifecycleError("v0.3 checkpoint state has no access context")
            self._ctx = None
        else:
            if not isinstance(raw_ctx, Mapping) or set(raw_ctx) != {"org_id", "user_id"}:
                raise LifecycleError("v0.3 checkpoint access context is invalid")
            self._ctx = AccessContext(str(raw_ctx["org_id"]), str(raw_ctx["user_id"]))
            if not isinstance(canonical_state, Mapping):
                raise LifecycleError("v0.3 canonical checkpoint evidence is missing")
            pending_state_status = self.runtime.verify_state(
                canonical_state,
                pending_descriptor=pending if pending is not None else None,
            )
            if (
                pending is None and pending_state_status != "EXACT_STATE"
            ) or (
                pending is not None
                and pending_state_status not in {"ABSENT", "EXACT_PENDING_APPEND"}
            ):
                raise LifecycleError("v0.3 checkpoint state status is invalid")
            if pending is not None and (
                self.runtime.verify_pending_retention(pending)
                != pending_state_status
            ):
                raise LifecycleError(
                    "v0.3 pending episode/outbox proof changed during recovery"
                )
            if tuple(canonical_state.get("stream_episode_ids", ())) != tuple(
                sorted(stored_task_ids.values())
            ):
                raise LifecycleError("v0.3 checkpoint episode ledger mismatch")
            for descriptor in stored_descriptors.values():
                if self.runtime.verify_pending_retention(descriptor) != (
                    "EXACT_PENDING_APPEND"
                ):
                    raise LifecycleError("v0.3 stored retention episode is missing")
            if pending is not None:
                if pending.get("org_id") != self._ctx.org_id or pending.get(
                    "user_id"
                ) != self._ctx.user_id:
                    raise LifecycleError("v0.3 pending retention context mismatch")
        prepared = payload.get("prepared_task_times", {})
        if not isinstance(prepared, Mapping) or any(
            not isinstance(key, str)
            or not isinstance(item, Mapping)
            or not isinstance(item.get("event_time"), str)
            or item.get("sequence_index") is not None
            and (type(item.get("sequence_index")) is not int or item["sequence_index"] < 0)
            for key, item in prepared.items()
        ):
            raise LifecycleError("v0.3 prepared task event-time ledger is invalid")
        if any(
            descriptor.get("task_id") != task_id
            for task_id, descriptor in stored_descriptors.items()
        ):
            raise LifecycleError("v0.3 stored descriptor task binding is invalid")
        if pending is not None and (
            pending.get("task_id") not in prepared
            or pending.get("task_id") in stored_task_ids
        ):
            raise LifecycleError("v0.3 pending descriptor task binding is invalid")
        self.stored_task_ids = stored_task_ids
        self.stored_retention_descriptors = stored_descriptors
        self.pending_retention = deepcopy(dict(pending)) if pending is not None else None
        self.prepared_task_times = {
            str(key): dict(item) for key, item in prepared.items()
        }


def production_v03_lifecycle_factory(
    *,
    identity_resolver: Optional[object] = None,
    **kwargs: object,
):
    """Build or bind the durable M1 lifecycle.

    Benchmark streams seed one solve-job identity per arm.  Looking the job up
    later by only ``(org, user, repository, task_id)`` is therefore ambiguous
    once multiple arms coexist.  Passing an exact stream-bound resolver returns
    a normal ``open_benchmark_arm`` lifecycle factory; the direct keyword form
    is retained for the default single-stream composition.
    """

    if not kwargs:
        if not callable(identity_resolver):
            raise TypeError("identity_resolver is required when binding M1")

        def bound_factory(**build_kwargs: object) -> PostgresV03ExperienceLifecycle:
            return production_v03_lifecycle_factory(
                identity_resolver=identity_resolver,
                **build_kwargs,
            )

        bound_factory.configuration_hash = (  # type: ignore[attr-defined]
            PostgresV03ExperienceLifecycle.configuration_hash
        )
        bound_factory.identity_resolver = identity_resolver  # type: ignore[attr-defined]
        return bound_factory

    persistence = kwargs.get("persistence")
    if identity_resolver is None:
        identity_resolver = PostgresTaskIdentityResolver(
            kwargs.get("canonical_store"), persistence
        )
    if not callable(identity_resolver):
        raise TypeError("identity_resolver is required")
    runtime = LiveV03Runtime(
        canonical_store=kwargs.get("canonical_store"),
        vector_index=kwargs.get("vector_index"),
        embedder=kwargs.get("embedder"),
        persistence=persistence,
        namespace=str(kwargs["namespace"]),
    )
    return PostgresV03ExperienceLifecycle(
        runtime,
        namespace=str(kwargs["namespace"]),
        identity_resolver=identity_resolver,
    )


production_v03_lifecycle_factory.configuration_hash = (
    PostgresV03ExperienceLifecycle.configuration_hash
)


__all__ = [
    "LIVE_V03_IMPLEMENTATION_HASH",
    "LIVE_V03_IMPLEMENTATION_MANIFEST",
    "LiveV03Runtime",
    "PostgresTaskIdentityResolver",
    "PostgresV03ExperienceLifecycle",
    "V03_LIFECYCLE_SCHEMA",
    "production_v03_lifecycle_factory",
]
