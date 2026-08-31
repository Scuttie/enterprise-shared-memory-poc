"""Active-semantic-subtask TriMem recall policy.

Recall is episodic-first.  A low-confidence episodic search backs off to the
user semantic graph and then the reviewed organisation semantic graph.  A
strong but incomplete episode may receive one complementary semantic record.
All access, validity, count, and byte-budget checks are repeated here even if a
store already filtered its snapshot.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Mapping, Optional, Protocol

from .ppr import DeterministicHashEmbedder, GraphNode, RankedNode, SeedSignal, TextEmbedder, rank_graph
from .working_graph import SemanticSubtaskNode, ShortTermWorkingGraph


class MemoryKind(str, Enum):
    EPISODIC = "EPISODIC"
    USER_SEMANTIC = "USER_SEMANTIC"
    ORG_SEMANTIC = "ORG_SEMANTIC"


class RecallError(ValueError):
    pass


class NoActiveSubtask(RecallError):
    pass


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    kind: MemoryKind
    retrieval_text: str
    execution_view: str
    org_id: str
    owner_user_id: Optional[str] = None
    repository: Optional[str] = None
    version: str = "1"
    version_valid: bool = True
    stale: bool = False
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    servable: bool = True
    verified: bool = True
    reviewed: bool = True
    source_outcome: str = "passed"
    quality: float = 1.0
    completeness: float = 1.0
    coverage: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.memory_id or not self.org_id:
            raise RecallError("memory_id and org_id are required")
        object.__setattr__(self, "kind", MemoryKind(self.kind))
        object.__setattr__(self, "coverage", tuple(sorted(set(self.coverage))))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        if not 0.0 <= float(self.quality) <= 1.0 or not 0.0 <= float(self.completeness) <= 1.0:
            raise RecallError("quality and completeness must be in [0, 1]")


@dataclass(frozen=True)
class MemoryGraphSnapshot:
    kind: MemoryKind
    records: Mapping[str, MemoryRecord]
    nodes: Mapping[str, GraphNode] = field(default_factory=dict)
    adjacency: Mapping[str, object] = field(default_factory=dict)
    graph_hash: str = ""

    def normalized_nodes(self) -> dict[str, GraphNode]:
        nodes = dict(self.nodes)
        for memory_id, record in self.records.items():
            nodes.setdefault(memory_id, GraphNode(memory_id, record.retrieval_text, record.metadata))
        return nodes


class MemoryGraphStore(Protocol):
    def snapshot(self, kind: MemoryKind, *, user_id: str, org_id: str,
                 repository: str) -> MemoryGraphSnapshot: ...


class InMemoryMemoryGraphStore:
    """Small deterministic store for credential-free replay/tests."""

    def __init__(self, snapshots: Mapping[MemoryKind | str, MemoryGraphSnapshot] | None = None):
        self._snapshots = {MemoryKind(kind): value for kind, value in (snapshots or {}).items()}

    def put(self, snapshot: MemoryGraphSnapshot) -> None:
        self._snapshots[MemoryKind(snapshot.kind)] = snapshot

    def snapshot(self, kind: MemoryKind, *, user_id: str, org_id: str,
                 repository: str) -> MemoryGraphSnapshot:
        return self._snapshots.get(MemoryKind(kind), MemoryGraphSnapshot(MemoryKind(kind), {}))


@dataclass(frozen=True)
class RetrievalConfig:
    min_confidence: float = 0.25
    min_margin: float = 0.0
    episode_complete_threshold: float = 0.8
    max_episodic_per_node: int = 1
    max_semantic_per_node: int = 1
    max_task_injections: int = 3
    context_budget_bytes: int = 12_000
    embedding_dimensions: int = 128
    embedding_weight: float = 0.65
    lexical_weight: float = 0.35
    ppr_damping: float = 0.85
    ppr_iterations: int = 32

    def __post_init__(self) -> None:
        if not 0 <= self.min_confidence <= 1 or self.min_margin < 0:
            raise RecallError("invalid confidence/margin")
        if self.max_episodic_per_node != 1 or self.max_semantic_per_node != 1:
            raise RecallError("TriMem V1 fixes per-node episodic and semantic maxima at one")
        if not 1 <= self.max_task_injections <= 3 or self.context_budget_bytes <= 0:
            raise RecallError("task injection maximum must be in [1, 3] and context budget positive")


@dataclass(frozen=True)
class MemoryInjection:
    memory_id: str
    kind: MemoryKind
    active_node_id: str
    exact_text: str
    exact_utf8: bytes
    byte_count: int
    sha256: str
    confidence: float
    margin: float
    graph_hash: str
    memory_version: str
    namespace: str = ""
    canonical_graph_id: str = ""
    canonical_node_hash: str = ""

    def verify(self) -> bool:
        encoded = self.exact_text.encode("utf-8")
        return (encoded == self.exact_utf8 and len(encoded) == self.byte_count and
                hashlib.sha256(encoded).hexdigest() == self.sha256)


@dataclass
class RetrievalSessionState:
    task_id: str
    total_injections: int = 0
    context_bytes: int = 0
    injected_memory_ids: set[str] = field(default_factory=set)
    per_node_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    ledger: list[MemoryInjection] = field(default_factory=list)

    def count(self, node_id: str, category: str) -> int:
        return int(self.per_node_counts.get(node_id, {}).get(category, 0))

    def record(self, injection: MemoryInjection) -> None:
        category = "episodic" if injection.kind == MemoryKind.EPISODIC else "semantic"
        self.total_injections += 1
        self.context_bytes += injection.byte_count
        self.injected_memory_ids.add(injection.memory_id)
        counts = self.per_node_counts.setdefault(injection.active_node_id, {"episodic": 0, "semantic": 0})
        counts[category] = counts.get(category, 0) + 1
        self.ledger.append(injection)


@dataclass(frozen=True)
class RecallDecision:
    active_node_id: str
    injections: tuple[MemoryInjection, ...]
    bank_trace: tuple[dict, ...]
    rejections: tuple[dict, ...]

    @property
    def injected_texts(self) -> tuple[str, ...]:
        return tuple(item.exact_text for item in self.injections)


@dataclass(frozen=True)
class _Candidate:
    record: MemoryRecord
    confidence: float
    margin: float
    ranked: RankedNode
    graph_hash: str


class TriMemoryRetriever:
    def __init__(self, store: MemoryGraphStore, config: RetrievalConfig | None = None, *,
                 embedder: TextEmbedder | None = None,
                 injection_auditor: Optional[Callable[[tuple[MemoryInjection, ...]], None]] = None):
        self.store = store
        self.config = config or RetrievalConfig()
        self.embedder = embedder or DeterministicHashEmbedder(self.config.embedding_dimensions)
        self.injection_auditor = injection_auditor

    def manifest(self) -> Mapping[str, object]:
        from dataclasses import asdict

        return {
            "config": asdict(self.config),
            "embedder": dict(self.embedder.provenance()),
            "algorithm": "embedding-and-lexical-seeded-personalized-pagerank",
        }

    def recall(self, graph: ShortTermWorkingGraph, session: RetrievalSessionState, *, user_id: str,
               org_id: str, repository: str, now: datetime | str | None = None) -> RecallDecision:
        node = graph.active_node
        if node is None:
            raise NoActiveSubtask("memory retrieval is allowed only for the active semantic subtask")
        if session.task_id != graph.task_id:
            raise RecallError("retrieval session belongs to another task")
        clock = _parse_now(now)
        traces: list[dict] = []
        rejections: list[dict] = []
        working_session = deepcopy(session) if self.injection_auditor is not None else session

        if working_session.total_injections >= self.config.max_task_injections:
            traces.append({"bank": "ALL", "decision": "ABSTAIN", "reason": "task_injection_limit"})
            return RecallDecision(node.node_id, (), tuple(traces), ())

        episode = self._select(MemoryKind.EPISODIC, node, user_id, org_id, repository, clock,
                               traces, rejections)
        selected: list[_Candidate] = []
        if episode is not None:
            selected.append(episode)
            missing = set(node.required_memory_facets) - set(episode.record.coverage)
            incomplete = (episode.record.completeness < self.config.episode_complete_threshold or bool(missing))
            if incomplete:
                semantic = self._semantic_backoff(node, user_id, org_id, repository, clock, traces, rejections,
                                                  required_coverage=missing)
                if semantic is not None:
                    selected.append(semantic)
        else:
            semantic = self._semantic_backoff(node, user_id, org_id, repository, clock, traces, rejections,
                                              required_coverage=set())
            if semantic is not None:
                selected.append(semantic)

        injections: list[MemoryInjection] = []
        for candidate in selected:
            category = "episodic" if candidate.record.kind == MemoryKind.EPISODIC else "semantic"
            limit = (self.config.max_episodic_per_node if category == "episodic"
                     else self.config.max_semantic_per_node)
            if working_session.count(node.node_id, category) >= limit:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "per_node_limit"})
                continue
            if candidate.record.memory_id in working_session.injected_memory_ids:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "already_injected"})
                continue
            if working_session.total_injections >= self.config.max_task_injections:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "task_injection_limit"})
                break
            payload = candidate.record.execution_view
            raw = payload.encode("utf-8")
            if not raw:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "empty_execution_view"})
                continue
            if working_session.context_bytes + len(raw) > self.config.context_budget_bytes:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "context_budget"})
                continue
            injection = MemoryInjection(
                memory_id=candidate.record.memory_id, kind=candidate.record.kind,
                active_node_id=node.node_id, exact_text=payload, exact_utf8=raw, byte_count=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(), confidence=candidate.confidence,
                margin=candidate.margin, graph_hash=candidate.graph_hash,
                memory_version=candidate.record.version,
                namespace=str(candidate.record.metadata.get("namespace", "")),
                canonical_graph_id=str(candidate.record.metadata.get("graph_id", "")),
                canonical_node_hash=str(candidate.record.metadata.get("canonical_node_hash", "")),
            )
            if not injection.verify():  # defensive; should be impossible
                raise RecallError("injection evidence failed its own byte/hash verification")
            working_session.record(injection)
            injections.append(injection)
        if self.injection_auditor is not None and injections:
            # No caller-visible session state is mutated until the exact-byte
            # PostgreSQL access audit commits successfully.
            self.injection_auditor(tuple(injections))
            for injection in injections:
                session.record(injection)
        return RecallDecision(node.node_id, tuple(injections), tuple(traces), tuple(rejections))

    def _semantic_backoff(self, node: SemanticSubtaskNode, user_id: str, org_id: str, repository: str,
                          now: Optional[datetime], traces: list[dict], rejections: list[dict], *,
                          required_coverage: set[str]) -> Optional[_Candidate]:
        for kind in (MemoryKind.USER_SEMANTIC, MemoryKind.ORG_SEMANTIC):
            candidate = self._select(kind, node, user_id, org_id, repository, now, traces, rejections,
                                     required_coverage=required_coverage)
            if candidate is not None:
                return candidate
        return None

    def _select(self, kind: MemoryKind, node: SemanticSubtaskNode, user_id: str, org_id: str,
                repository: str, now: Optional[datetime], traces: list[dict], rejections: list[dict], *,
                required_coverage: set[str] | None = None) -> Optional[_Candidate]:
        seeds = list(_seeds(node, repository))
        query_text = "\n".join(seed.text for seed in seeds)
        query_snapshot = getattr(self.store, "snapshot_for_query", None)
        if callable(query_snapshot):
            snapshot = query_snapshot(
                kind,
                user_id=user_id,
                org_id=org_id,
                repository=repository,
                query_text=query_text,
            )
        else:
            snapshot = self.store.snapshot(
                kind, user_id=user_id, org_id=org_id, repository=repository
            )
        if MemoryKind(snapshot.kind) != kind:
            raise RecallError("store returned the wrong memory bank")
        eligible: dict[str, MemoryRecord] = {}
        for memory_id in sorted(snapshot.records):
            record = snapshot.records[memory_id]
            reason = _rejection_reason(record, kind, user_id, org_id, repository, now)
            if reason is None and required_coverage and not (set(record.coverage) & required_coverage):
                reason = "not_complementary"
            if reason:
                rejections.append({"bank": kind.value, "memory_id": memory_id, "reason": reason})
            else:
                eligible[memory_id] = record
        if not eligible:
            traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "no_eligible"})
            return None

        nodes = snapshot.normalized_nodes()
        excluded_record_ids = set(snapshot.records) - set(eligible)
        nodes = {node_id: graph_node for node_id, graph_node in nodes.items()
                 if node_id not in excluded_record_ids}
        adjacency = {node_id: _filter_edges(snapshot.adjacency.get(node_id, ()), set(nodes))
                     for node_id in nodes}
        # Complement retrieval is about the facets proved missing from the
        # selected episode.  Include those facets explicitly rather than
        # expecting a generic semantic record to repeat task-specific symbols.
        seeds.extend(SeedSignal("missing_facet:%04d" % index, facet, 1.0)
                     for index, facet in enumerate(sorted(required_coverage or ())))
        ranked = rank_graph(
            nodes, adjacency, seeds, embedder=self.embedder,
            embedding_weight=self.config.embedding_weight, lexical_weight=self.config.lexical_weight,
            damping=self.config.ppr_damping, iterations=self.config.ppr_iterations,
        )
        ranked_memories = [item for item in ranked if item.node_id in eligible]
        if not ranked_memories:
            traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "no_seed_match"})
            return None
        first = ranked_memories[0]
        confidence = round(first.score * eligible[first.node_id].quality, 15)
        second = (ranked_memories[1].score * eligible[ranked_memories[1].node_id].quality
                  if len(ranked_memories) > 1 else 0.0)
        margin = round(confidence - second, 15)
        if confidence < self.config.min_confidence:
            traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "low_confidence",
                           "confidence": confidence, "margin": margin})
            return None
        if margin < self.config.min_margin:
            traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "low_margin",
                           "confidence": confidence, "margin": margin})
            return None
        traces.append({"bank": kind.value, "decision": "USE", "memory_id": first.node_id,
                       "confidence": confidence, "margin": margin, "graph_hash": snapshot.graph_hash})
        return _Candidate(eligible[first.node_id], confidence, margin, first, snapshot.graph_hash)


def _seeds(node: SemanticSubtaskNode, repository: str) -> tuple[SeedSignal, ...]:
    signals = [SeedSignal("objective", node.objective, 1.0),
               SeedSignal("operation", node.operation, 0.9),
               SeedSignal("repository", repository, 0.35)]
    for category, values, weight in (
        ("file", node.files, 0.8), ("symbol", node.symbols, 1.0), ("api", node.apis, 1.0),
        ("error", node.errors, 1.0), ("test", node.tests, 0.9),
        ("precondition", node.preconditions, 0.6), ("invariant", node.invariants, 0.7),
    ):
        signals.extend(SeedSignal("%s:%04d" % (category, index), text, weight)
                       for index, text in enumerate(values))
    return tuple(signals)


def _filter_edges(edges: object, allowed: set[str]) -> object:
    if isinstance(edges, Mapping):
        return {str(node_id): float(weight) for node_id, weight in sorted(edges.items())
                if str(node_id) in allowed and float(weight) > 0}
    return tuple(sorted(str(node_id) for node_id in (edges or ()) if str(node_id) in allowed))


def _parse_now(value: datetime | str | None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _rejection_reason(record: MemoryRecord, expected_kind: MemoryKind, user_id: str, org_id: str,
                      repository: str, now: Optional[datetime]) -> Optional[str]:
    if record.kind != expected_kind:
        return "wrong_bank"
    if str(record.org_id) != str(org_id):
        return "wrong_org"
    if record.repository and record.repository != repository:
        return "wrong_repository"
    if not record.servable:
        return "not_servable"
    if not record.version_valid:
        return "version_invalid"
    if record.stale:
        return "stale"
    if record.valid_from or record.valid_until:
        if now is None:
            return "validity_time_unknown"
        if record.valid_from and now < _parse_time(record.valid_from):
            return "not_valid_yet"
        if record.valid_until and now >= _parse_time(record.valid_until):
            return "expired"
    if expected_kind in (MemoryKind.EPISODIC, MemoryKind.USER_SEMANTIC):
        if not record.owner_user_id or str(record.owner_user_id) != str(user_id):
            return "cross_user_private"
    if expected_kind != MemoryKind.EPISODIC:
        if not record.verified or record.source_outcome != "passed":
            return "unverified_semantic"
    if expected_kind == MemoryKind.ORG_SEMANTIC and not record.reviewed:
        return "unreviewed_shared_semantic"
    if not record.retrieval_text.strip():
        return "empty_retrieval_text"
    if not record.execution_view:
        return "empty_execution_view"
    return None
