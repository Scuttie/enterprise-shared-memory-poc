"""Memory-only arm adapters for the common TriMem coding-agent runtime."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Callable, Mapping

from .accounting import canonical_bytes, sha256_bytes
from .agent_runtime import CodingTask, RuntimeFailure
from .retrieval import (
    MemoryGraphStore,
    MemoryInjection,
    MemoryKind,
    RecallDecision,
    RetrievalSessionState,
    TriMemoryRetriever,
)
from .working_graph import ShortTermWorkingGraph


V03_BASELINE_COMMIT = "ce10ab49586db7a859fbe5cca93051b93f9f5b55"


def _injection_row(item: MemoryInjection) -> dict[str, Any]:
    return {
        "memory_id": item.memory_id,
        "kind": item.kind.value,
        "active_node_id": item.active_node_id,
        "exact_text": item.exact_text,
        "byte_count": item.byte_count,
        "sha256": item.sha256,
        "confidence": item.confidence,
        "margin": item.margin,
        "graph_hash": item.graph_hash,
        "memory_version": item.memory_version,
        "namespace": item.namespace,
        "canonical_graph_id": item.canonical_graph_id,
        "canonical_node_hash": item.canonical_node_hash,
    }


def _injection_from_row(row: Mapping[str, Any]) -> MemoryInjection:
    text = str(row["exact_text"])
    return MemoryInjection(
        memory_id=str(row["memory_id"]),
        kind=MemoryKind(row["kind"]),
        active_node_id=str(row["active_node_id"]),
        exact_text=text,
        exact_utf8=text.encode("utf-8"),
        byte_count=int(row["byte_count"]),
        sha256=str(row["sha256"]),
        confidence=float(row["confidence"]),
        margin=float(row["margin"]),
        graph_hash=str(row.get("graph_hash", "")),
        memory_version=str(row.get("memory_version", "1")),
        namespace=str(row.get("namespace", "")),
        canonical_graph_id=str(row.get("canonical_graph_id", "")),
        canonical_node_hash=str(row.get("canonical_node_hash", "")),
    )


class ActiveNodeTriMemController:
    """M2: retrieve exactly when each semantic node becomes active."""

    def __init__(self, retriever: TriMemoryRetriever, *, task_id: str):
        self.retriever = retriever
        self.session = RetrievalSessionState(task_id)
        self.recalled_nodes: set[str] = set()
        self._context: dict[str, tuple[MemoryInjection, ...]] = {}

    @property
    def content_hash(self) -> str:
        return sha256_bytes(
            canonical_bytes(
                {
                    "name": "M2_FULL_TRIMEM_CODER",
                    "retrieval": self.retriever.manifest(),
                    "policy": "episodic-first/user-semantic/org-semantic-backoff/active-node-only",
                }
            )
        )

    def recall(self, graph: ShortTermWorkingGraph, task: CodingTask) -> RecallDecision:
        node = graph.active_node
        if node is None:
            raise RuntimeFailure("M2 recall requires active node")
        if node.node_id in self.recalled_nodes:
            return RecallDecision(
                node.node_id,
                (),
                ({"bank": "ALL", "decision": "RESUME", "reason": "node_already_recalled"},),
                (),
            )
        decision = self.retriever.recall(
            graph,
            self.session,
            user_id=task.user_id,
            org_id=task.org_id,
            repository=task.repository,
            now=datetime.now(timezone.utc),
        )
        self.recalled_nodes.add(node.node_id)
        self._context[node.node_id] = decision.injections
        return decision

    def context_for(self, active_node_id: str) -> tuple[MemoryInjection, ...]:
        return self._context.get(active_node_id, ())

    def checkpoint_state(self) -> Mapping[str, Any]:
        return {
            "mode": "M2",
            "task_id": self.session.task_id,
            "recalled_nodes": sorted(self.recalled_nodes),
            "ledger": [_injection_row(item) for item in self.session.ledger],
        }

    def restore(self, value: Mapping[str, Any]) -> None:
        if value.get("mode") != "M2" or value.get("task_id") != self.session.task_id:
            raise RuntimeFailure("M2 memory checkpoint mismatch")
        ledger = [_injection_from_row(row) for row in value.get("ledger", ())]
        self.session = RetrievalSessionState(self.session.task_id)
        self._context = {}
        for item in ledger:
            if not item.verify():
                raise RuntimeFailure("checkpoint injection hash mismatch")
            self.session.record(item)
            self._context.setdefault(item.active_node_id, tuple())
            self._context[item.active_node_id] = (*self._context[item.active_node_id], item)
        self.recalled_nodes = {str(x) for x in value.get("recalled_nodes", ())}


class StaticV03MemoryController:
    """Credential-free compatibility fixture; never a production M1 backend.

    It performs one whole-task search before the first solve step, jointly ranks
    private episodes and reviewed shared records, injects at most two, and keeps
    those initial views in the common agent context.  It intentionally has no
    PPR, semantic-subtask query, semantic backoff, or online recall.
    """

    def __init__(self, store: MemoryGraphStore, *, context_budget_bytes: int = 12_000):
        self.store = store
        self.context_budget_bytes = context_budget_bytes
        self._selected: tuple[MemoryInjection, ...] = ()
        self._prepared = False

    @property
    def content_hash(self) -> str:
        return sha256_bytes(
            canonical_bytes(
                {
                    "name": "M1_V03_JACCARD_FIXTURE_NOT_FOR_BENCHMARK",
                    "source_commit": V03_BASELINE_COMMIT,
                    "query": "whole_task_instruction_once",
                    "banks": ["private_episode", "shared_semantic"],
                    "joint_rank": "score_desc_private_tie_then_id",
                    "max_injected": 2,
                    "context_budget_bytes": self.context_budget_bytes,
                    "ppr": False,
                    "active_node_recall": False,
                }
            )
        )

    def recall(self, graph: ShortTermWorkingGraph, task: CodingTask) -> RecallDecision:
        node = graph.active_node
        if node is None:
            raise RuntimeFailure("M1 recall requires active node")
        if self._prepared:
            return RecallDecision(
                node.node_id,
                (),
                ({"bank": "V03_STATIC", "decision": "NO_NEW_RECALL", "reason": "whole_task_search_already_run"},),
                (),
            )
        self._prepared = True
        query = _tokens(task.instruction)
        candidates: list[tuple[float, int, str, Any, str]] = []
        rejections: list[dict] = []
        for kind, tie in ((MemoryKind.EPISODIC, 0), (MemoryKind.ORG_SEMANTIC, 1)):
            snapshot = self.store.snapshot(
                kind, user_id=task.user_id, org_id=task.org_id, repository=task.repository
            )
            for memory_id in sorted(snapshot.records):
                record = snapshot.records[memory_id]
                reason = _v03_rejection(record, kind, task)
                if reason:
                    rejections.append({"bank": kind.value, "memory_id": memory_id, "reason": reason})
                    continue
                score = _jaccard(query, _tokens(record.retrieval_text)) * float(record.quality)
                candidates.append((score, tie, memory_id, record, snapshot.graph_hash))
        candidates.sort(key=lambda row: (-row[0], row[1], row[2]))
        selected: list[MemoryInjection] = []
        used = 0
        for rank, (score, _, memory_id, record, graph_hash) in enumerate(candidates):
            if len(selected) >= 2:
                break
            raw = record.execution_view.encode("utf-8")
            if not raw or used + len(raw) > self.context_budget_bytes:
                rejections.append({"bank": record.kind.value, "memory_id": memory_id, "reason": "context_budget"})
                continue
            next_score = candidates[rank + 1][0] if rank + 1 < len(candidates) else 0.0
            selected.append(
                MemoryInjection(
                    memory_id=memory_id,
                    kind=record.kind,
                    active_node_id="__TASK__",
                    exact_text=record.execution_view,
                    exact_utf8=raw,
                    byte_count=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    confidence=score,
                    margin=score - next_score,
                    graph_hash=graph_hash,
                    memory_version=record.version,
                    namespace=str(record.metadata.get("namespace", "")),
                    canonical_graph_id=str(record.metadata.get("graph_id", "")),
                    canonical_node_hash=str(record.metadata.get("canonical_node_hash", "")),
                )
            )
            used += len(raw)
        self._selected = tuple(selected)
        trace = ({
            "bank": "V03_STATIC",
            "decision": "USE" if selected else "ABSTAIN",
            "source_commit": V03_BASELINE_COMMIT,
            "candidate_count": len(candidates),
            "injected_count": len(selected),
        },)
        return RecallDecision(node.node_id, self._selected, trace, tuple(rejections))

    def context_for(self, active_node_id: str) -> tuple[MemoryInjection, ...]:
        return self._selected

    def checkpoint_state(self) -> Mapping[str, Any]:
        return {
            "mode": "M1",
            "source_commit": V03_BASELINE_COMMIT,
            "prepared": self._prepared,
            "ledger": [_injection_row(item) for item in self._selected],
        }

    def restore(self, value: Mapping[str, Any]) -> None:
        if value.get("mode") != "M1" or value.get("source_commit") != V03_BASELINE_COMMIT:
            raise RuntimeFailure("M1 memory checkpoint mismatch")
        selected = tuple(_injection_from_row(row) for row in value.get("ledger", ()))
        if len(selected) > 2 or any(not item.verify() for item in selected):
            raise RuntimeFailure("invalid M1 checkpoint injection ledger")
        self._selected = selected
        self._prepared = bool(value.get("prepared"))


class CurrentV03MemoryController:
    """M1 controller over the exact live-main validated-search/injection path.

    ``recall_once`` owns the async-to-sync bridge and returns a decision whose
    exact model-facing bytes have already passed ``validated_search``,
    ``plan_injection`` and the current retrieval-candidate audit.  Keeping the
    common controller deliberately small prevents a second ranking or view
    compiler from silently becoming the benchmark baseline.
    """

    def __init__(
        self,
        recall_once: Callable[[CodingTask, str], RecallDecision],
        verify_audit: Callable[[str], None],
        *,
        task_id: str,
        implementation_manifest: Mapping[str, Any],
        context_budget_bytes: int = 12_000,
    ) -> None:
        if not callable(recall_once) or not callable(verify_audit):
            raise TypeError("live v0.3 recall/audit callables are required")
        if not task_id:
            raise ValueError("task_id is required")
        if context_budget_bytes <= 0:
            raise ValueError("context budget must be positive")
        required = {
            "source_commit",
            "validated_search_sha256",
            "plan_injection_sha256",
            "projection_sha256",
            "canonical_tables",
        }
        if not required <= set(implementation_manifest):
            raise ValueError("live v0.3 implementation manifest is incomplete")
        if (
            implementation_manifest.get("projection_role")
            != "PREEXISTING_INDEX_FORMAT_ONLY_NO_FRESH_SOLVE_WRITE"
            or implementation_manifest.get("fresh_solve_immediate_carryover") is not False
            or implementation_manifest.get("retention_path")
            != "service.durable.persist_private_episode_candidate(connection)"
        ):
            raise ValueError("live v0.3 retention/index boundary is not frozen")
        self._recall_once = recall_once
        self._verify_audit = verify_audit
        self.task_id = task_id
        self.implementation_manifest = dict(implementation_manifest)
        self.context_budget_bytes = int(context_budget_bytes)
        self._selected: tuple[MemoryInjection, ...] = ()
        self._prepared = False
        self._audit_digest: str | None = None

    @property
    def content_hash(self) -> str:
        return sha256_bytes(
            canonical_bytes(
                {
                    "name": "M1_CURRENT_V03_MEMORY_LIVE_MAIN",
                    "implementation": self.implementation_manifest,
                    "query": "whole_task_instruction_once",
                    "max_injected": 2,
                    "context_budget_bytes": self.context_budget_bytes,
                    "ppr": False,
                    "active_node_recall": False,
                }
            )
        )

    def recall(self, graph: ShortTermWorkingGraph, task: CodingTask) -> RecallDecision:
        node = graph.active_node
        if node is None:
            raise RuntimeFailure("M1 recall requires active node")
        if task.task_id != self.task_id:
            raise RuntimeFailure("M1 task identity changed")
        if self._prepared:
            return RecallDecision(
                node.node_id,
                (),
                ({
                    "bank": "V03_LIVE_MAIN",
                    "decision": "NO_NEW_RECALL",
                    "reason": "whole_task_search_already_run",
                },),
                (),
            )
        decision = self._recall_once(task, node.node_id)
        if not isinstance(decision, RecallDecision):
            raise RuntimeFailure("live v0.3 recall returned an invalid decision")
        selected = tuple(decision.injections)
        if (
            len(selected) > 2
            or sum(item.byte_count for item in selected) > self.context_budget_bytes
            or any(not item.verify() for item in selected)
        ):
            raise RuntimeFailure("live v0.3 injection budget/hash boundary failed")
        audit_rows = [
            row for row in decision.bank_trace
            if row.get("bank") == "V03_LIVE_MAIN" and row.get("audit_digest")
        ]
        if len(audit_rows) != 1:
            raise RuntimeFailure("live v0.3 recall has no canonical audit digest")
        audit_digest = str(audit_rows[0]["audit_digest"])
        self._verify_audit(audit_digest)
        self._selected = selected
        self._audit_digest = audit_digest
        self._prepared = True
        return decision

    def context_for(self, active_node_id: str) -> tuple[MemoryInjection, ...]:
        return self._selected

    def checkpoint_state(self) -> Mapping[str, Any]:
        return {
            "mode": "M1_LIVE_V03",
            "task_id": self.task_id,
            "implementation_hash": sha256_bytes(
                canonical_bytes(self.implementation_manifest)
            ),
            "prepared": self._prepared,
            "audit_digest": self._audit_digest,
            "ledger": [_injection_row(item) for item in self._selected],
        }

    def restore(self, value: Mapping[str, Any]) -> None:
        expected_hash = sha256_bytes(canonical_bytes(self.implementation_manifest))
        if (
            value.get("mode") != "M1_LIVE_V03"
            or value.get("task_id") != self.task_id
            or value.get("implementation_hash") != expected_hash
        ):
            raise RuntimeFailure("M1 live-main memory checkpoint mismatch")
        selected = tuple(_injection_from_row(row) for row in value.get("ledger", ()))
        if (
            len(selected) > 2
            or sum(item.byte_count for item in selected) > self.context_budget_bytes
            or any(not item.verify() for item in selected)
        ):
            raise RuntimeFailure("invalid M1 live-main checkpoint injection ledger")
        prepared = bool(value.get("prepared"))
        audit_digest = value.get("audit_digest")
        if prepared:
            if not isinstance(audit_digest, str) or not audit_digest.startswith("sha256:"):
                raise RuntimeFailure("M1 live-main checkpoint audit is missing")
            self._verify_audit(audit_digest)
        elif selected or audit_digest is not None:
            raise RuntimeFailure("unprepared M1 checkpoint contains recall state")
        self._selected = selected
        self._audit_digest = str(audit_digest) if audit_digest is not None else None
        self._prepared = prepared


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z_][a-zA-Z_0-9]{1,}", (value or "").lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left or right else 0.0


def _v03_rejection(record, kind: MemoryKind, task: CodingTask) -> str | None:
    if record.kind != kind:
        return "wrong_bank"
    if str(record.org_id) != str(task.org_id):
        return "wrong_org"
    if record.repository and record.repository != task.repository:
        return "wrong_repository"
    if not record.servable or record.stale or not record.version_valid:
        return "invalid_or_stale"
    if kind == MemoryKind.EPISODIC and str(record.owner_user_id) != str(task.user_id):
        return "cross_user_private"
    if kind == MemoryKind.ORG_SEMANTIC and (not record.reviewed or not record.verified):
        return "unreviewed_shared"
    if not record.execution_view:
        return "empty_execution_view"
    return None
