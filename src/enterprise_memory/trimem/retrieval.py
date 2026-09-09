"""Active-semantic-subtask TriMem recall policy.

Recall is episodic-first.  A low-confidence episodic search backs off to the
user semantic graph and then the reviewed organisation semantic graph.  A
strong but incomplete episode may receive one complementary semantic record.
All access, validity, count, and byte-budget checks are repeated here even if a
store already filtered its snapshot.
"""
from __future__ import annotations

import fnmatch
import hashlib
import math
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Mapping, Optional, Protocol

from .ppr import DeterministicHashEmbedder, GraphNode, RankedNode, SeedSignal, TextEmbedder, rank_graph
from .working_graph import SemanticSubtaskNode, ShortTermWorkingGraph


class MemoryKind(str, Enum):
    EPISODIC = "EPISODIC"
    USER_SEMANTIC = "USER_SEMANTIC"
    ORG_SEMANTIC = "ORG_SEMANTIC"


class RecallSelectionMode(str, Enum):
    """Frozen retrieval choices used by the DEV activation diagnostic.

    ``FORCED_SAFE_TOP1`` is not a new learned router.  It keeps the ordinary
    store/canonical and local eligibility filters, then bypasses only the two
    utility gates (confidence and margin) and admits at most one candidate for
    an active subtask.
    """

    CURRENT_GATE = "CURRENT_GATE"
    FORCED_SAFE_TOP1 = "FORCED_SAFE_TOP1"


class RecallReasonCode(str, Enum):
    """Stable machine-readable outcomes for one bank-level recall attempt."""

    NO_CANDIDATE_GENERATED = "NO_CANDIDATE_GENERATED"
    NO_SAFE_CANDIDATE = "NO_SAFE_CANDIDATE"
    NO_COMPLEMENTARY_CANDIDATE = "NO_COMPLEMENTARY_CANDIDATE"
    NO_SEED_MATCH = "NO_SEED_MATCH"
    BELOW_CONFIDENCE_THRESHOLD = "BELOW_CONFIDENCE_THRESHOLD"
    BELOW_MARGIN_THRESHOLD = "BELOW_MARGIN_THRESHOLD"
    CANDIDATE_SELECTED = "CANDIDATE_SELECTED"
    FORCED_SAFE_TOP1_LIMIT_REJECTION = "FORCED_SAFE_TOP1_LIMIT_REJECTION"
    PERMISSION_GATE_REJECTED = "PERMISSION_GATE_REJECTED"
    TENANT_GATE_REJECTED = "TENANT_GATE_REJECTED"
    REPOSITORY_GATE_REJECTED = "REPOSITORY_GATE_REJECTED"
    PATH_GATE_REJECTED = "PATH_GATE_REJECTED"
    VERSION_GATE_REJECTED = "VERSION_GATE_REJECTED"
    PROVENANCE_GATE_REJECTED = "PROVENANCE_GATE_REJECTED"
    LEAKAGE_GATE_REJECTED = "LEAKAGE_GATE_REJECTED"
    QUARANTINE_GATE_REJECTED = "QUARANTINE_GATE_REJECTED"
    CANONICAL_GATE_REJECTED = "CANONICAL_GATE_REJECTED"
    INJECTED = "INJECTED"
    PER_NODE_INJECTION_LIMIT_REJECTION = "PER_NODE_INJECTION_LIMIT_REJECTION"
    SUBTASK_INJECTION_LIMIT_REJECTION = "SUBTASK_INJECTION_LIMIT_REJECTION"
    ALREADY_INJECTED_REJECTION = "ALREADY_INJECTED_REJECTION"
    TASK_INJECTION_LIMIT_REJECTION = "TASK_INJECTION_LIMIT_REJECTION"
    EMPTY_EXECUTION_VIEW_REJECTION = "EMPTY_EXECUTION_VIEW_REJECTION"
    CONTEXT_INJECTION_BUDGET_REJECTION = "CONTEXT_INJECTION_BUDGET_REJECTION"


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
    # Optional query-boundary evidence.  It is deliberately excluded from the
    # canonical graph hash and ranking inputs, so observing diagnostics cannot
    # alter CURRENT_GATE selection.
    query_telemetry: Mapping[str, object] = field(default_factory=dict, compare=False)

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


_RECALL_TELEMETRY_SCHEMA = "trimem/recall-decision-telemetry/1.0"
RECALL_DECISION_TELEMETRY_FIELDS = (
    "recall_attempt_id",
    "target_id",
    "subtask_id",
    "bank_type",
    "candidate_count_before_filter",
    "candidate_count_after_filter",
    "top_candidate_id",
    "top_embedding_score",
    "top_ppr_score",
    "threshold",
    "Q_USE",
    "Q_ABSTAIN",
    "router_policy",
    "final_reason_code",
)


@dataclass(frozen=True)
class RecallDecisionTelemetry:
    """One deterministic, JSON-ready row for one attempted memory bank.

    There is no recall DQN in TriMem V1.  The storage/consolidation DQN has a
    different action space, so its Q-values must never be relabelled as recall
    ``USE``/``ABSTAIN`` values.  The two Q fields are consequently always null
    and ``router_policy`` is explicitly ``N/A``.
    """

    recall_attempt_id: str
    target_id: str
    subtask_id: str
    bank_type: str
    candidate_count_before_filter: int
    candidate_count_after_filter: int
    top_candidate_id: Optional[str]
    top_embedding_score: Optional[float]
    top_ppr_score: Optional[float]
    threshold: Mapping[str, float]
    final_reason_code: str
    selection_mode: str
    top_seed_score: Optional[float] = None
    score_source: Optional[str] = None
    filter_reason_codes: tuple[str, ...] = ()
    Q_USE: None = None
    Q_ABSTAIN: None = None
    router_policy: str = "N/A"

    def as_row(self) -> dict[str, object]:
        # This exact field set is the persisted diagnostic contract.  Internal
        # score provenance/filter details stay on the typed object and query
        # snapshot rather than silently expanding the evidence schema.
        return {
            "recall_attempt_id": self.recall_attempt_id,
            "target_id": self.target_id,
            "subtask_id": self.subtask_id,
            "bank_type": self.bank_type,
            "candidate_count_before_filter": self.candidate_count_before_filter,
            "candidate_count_after_filter": self.candidate_count_after_filter,
            "top_candidate_id": self.top_candidate_id,
            "top_embedding_score": self.top_embedding_score,
            "top_ppr_score": self.top_ppr_score,
            "threshold": dict(self.threshold),
            "Q_USE": None,
            "Q_ABSTAIN": None,
            "router_policy": self.router_policy,
            "final_reason_code": self.final_reason_code,
        }


def normalize_recall_decision_telemetry(
    value: object,
    *,
    expected_target_id: Optional[str] = None,
) -> dict[str, object]:
    """Validate and canonicalize one persisted diagnostic telemetry row."""

    if not isinstance(value, Mapping) or set(value) != set(
        RECALL_DECISION_TELEMETRY_FIELDS
    ):
        raise RecallError("recall decision telemetry field-set drift")
    row = {key: value[key] for key in RECALL_DECISION_TELEMETRY_FIELDS}
    attempt_id = row["recall_attempt_id"]
    if (
        not isinstance(attempt_id, str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", attempt_id)
    ):
        raise RecallError("invalid recall_attempt_id")
    for key in ("target_id", "subtask_id", "bank_type"):
        if not isinstance(row[key], str) or not row[key]:
            raise RecallError("recall telemetry identity is incomplete")
    if expected_target_id is not None and row["target_id"] != expected_target_id:
        raise RecallError("recall telemetry target identity mismatch")
    before = row["candidate_count_before_filter"]
    after = row["candidate_count_after_filter"]
    if (
        type(before) is not int
        or type(after) is not int
        or before < 0
        or after < 0
        or after > before
    ):
        raise RecallError("recall telemetry candidate counts are invalid")
    top_id = row["top_candidate_id"]
    if (after == 0 and top_id is not None) or (
        after > 0 and (not isinstance(top_id, str) or not top_id)
    ):
        raise RecallError("recall telemetry top candidate/count mismatch")
    for key in ("top_embedding_score", "top_ppr_score"):
        score = row[key]
        if score is not None and (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            raise RecallError("recall telemetry score is invalid")
    threshold = row["threshold"]
    if not isinstance(threshold, Mapping) or set(threshold) != {
        "min_confidence", "min_margin"
    }:
        raise RecallError("recall telemetry threshold snapshot is invalid")
    for number in threshold.values():
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(float(number))
            or float(number) < 0
        ):
            raise RecallError("recall telemetry threshold is invalid")
    row["threshold"] = {
        "min_confidence": threshold["min_confidence"],
        "min_margin": threshold["min_margin"],
    }
    if row["Q_USE"] is not None or row["Q_ABSTAIN"] is not None:
        raise RecallError("recall DQN Q-values are not implemented")
    if row["router_policy"] != "N/A":
        raise RecallError("recall router policy must be N/A")
    try:
        reason = RecallReasonCode(str(row["final_reason_code"]))
    except ValueError as exc:
        raise RecallError("unknown recall telemetry reason") from exc
    if reason == RecallReasonCode.CANDIDATE_SELECTED:
        raise RecallError("recall telemetry contains an unfinalized candidate")
    if reason == RecallReasonCode.INJECTED and after == 0:
        raise RecallError("injected recall telemetry has no safe candidate")
    return row


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
    # Kept separate from the legacy bank trace so CURRENT_GATE evidence and
    # selection remain byte-compatible until a diagnostic runner explicitly
    # opts into persisting these rows.
    decision_telemetry: tuple[dict, ...] = field(default_factory=tuple, compare=False)

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
    recall_attempt_id: str
    embedding_score: float


class TriMemoryRetriever:
    def __init__(self, store: MemoryGraphStore, config: RetrievalConfig | None = None, *,
                 embedder: TextEmbedder | None = None,
                 injection_auditor: Optional[Callable[[tuple[MemoryInjection, ...]], None]] = None,
                 selection_mode: RecallSelectionMode | str = RecallSelectionMode.CURRENT_GATE,
                 diagnostic_telemetry: bool = False,
                 require_safe_pool_metadata: bool = False):
        if type(diagnostic_telemetry) is not bool:
            raise RecallError("diagnostic_telemetry must be boolean")
        if type(require_safe_pool_metadata) is not bool:
            raise RecallError("require_safe_pool_metadata must be boolean")
        if require_safe_pool_metadata and not diagnostic_telemetry:
            raise RecallError("safe-pool validation requires diagnostic telemetry")
        self.store = store
        self.config = config or RetrievalConfig()
        self.embedder = embedder or DeterministicHashEmbedder(self.config.embedding_dimensions)
        self.injection_auditor = injection_auditor
        self.selection_mode = _selection_mode(selection_mode)
        self.diagnostic_telemetry = diagnostic_telemetry
        self.require_safe_pool_metadata = require_safe_pool_metadata

    def manifest(self) -> Mapping[str, object]:
        from dataclasses import asdict

        manifest = {
            "config": asdict(self.config),
            "embedder": dict(self.embedder.provenance()),
            "algorithm": "embedding-and-lexical-seeded-personalized-pagerank",
        }
        # Do not perturb the frozen CURRENT_GATE manifest/content hash.  A
        # forced diagnostic composition is, however, explicitly identifiable.
        if self.selection_mode != RecallSelectionMode.CURRENT_GATE:
            manifest["selection_mode"] = self.selection_mode.value
        if (
            self.diagnostic_telemetry
            or self.selection_mode == RecallSelectionMode.FORCED_SAFE_TOP1
        ):
            manifest["diagnostic_telemetry_schema"] = _RECALL_TELEMETRY_SCHEMA
        if self.require_safe_pool_metadata:
            manifest["safe_pool_metadata_contract"] = "trimem/dev-activation-safe-pool/1.0"
        return manifest

    def recall(self, graph: ShortTermWorkingGraph, session: RetrievalSessionState, *, user_id: str,
               org_id: str, repository: str, now: datetime | str | None = None,
               selection_mode: RecallSelectionMode | str | None = None) -> RecallDecision:
        node = graph.active_node
        if node is None:
            raise NoActiveSubtask("memory retrieval is allowed only for the active semantic subtask")
        if session.task_id != graph.task_id:
            raise RecallError("retrieval session belongs to another task")
        clock = _parse_now(now)
        mode = self.selection_mode if selection_mode is None else _selection_mode(selection_mode)
        if mode != self.selection_mode:
            raise RecallError("recall selection mode is not manifest-bound")
        emit_telemetry = (
            self.diagnostic_telemetry
            or mode == RecallSelectionMode.FORCED_SAFE_TOP1
        )
        traces: list[dict] = []
        rejections: list[dict] = []
        telemetry: list[RecallDecisionTelemetry] = []
        working_session = deepcopy(session) if self.injection_auditor is not None else session

        if working_session.total_injections >= self.config.max_task_injections:
            traces.append({"bank": "ALL", "decision": "ABSTAIN", "reason": "task_injection_limit"})
            telemetry.append(self._empty_telemetry(
                session.task_id, node.node_id, "ALL", mode,
                RecallReasonCode.TASK_INJECTION_LIMIT_REJECTION,
            ))
            return RecallDecision(
                node.node_id, (), tuple(traces), (),
                _telemetry_rows(telemetry) if emit_telemetry else (),
            )

        if (
            mode == RecallSelectionMode.FORCED_SAFE_TOP1
            and sum(working_session.per_node_counts.get(node.node_id, {}).values()) >= 1
        ):
            traces.append({
                "bank": "ALL", "decision": "ABSTAIN",
                "reason": "subtask_injection_limit",
            })
            telemetry.append(self._empty_telemetry(
                session.task_id, node.node_id, "ALL", mode,
                RecallReasonCode.SUBTASK_INJECTION_LIMIT_REJECTION,
            ))
            return RecallDecision(
                node.node_id, (), tuple(traces), (),
                _telemetry_rows(telemetry) if emit_telemetry else (),
            )

        selected: list[_Candidate]
        if mode == RecallSelectionMode.CURRENT_GATE:
            episode = self._select(
                MemoryKind.EPISODIC, node, session.task_id, user_id, org_id,
                repository, clock, mode, traces, rejections, telemetry,
            )
            selected = []
            if episode is not None:
                selected.append(episode)
                missing = set(node.required_memory_facets) - set(episode.record.coverage)
                incomplete = (
                    episode.record.completeness < self.config.episode_complete_threshold
                    or bool(missing)
                )
                if incomplete:
                    semantic = self._semantic_backoff(
                        node, session.task_id, user_id, org_id, repository, clock,
                        mode, traces, rejections, telemetry, required_coverage=missing,
                    )
                    if semantic is not None:
                        selected.append(semantic)
            else:
                semantic = self._semantic_backoff(
                    node, session.task_id, user_id, org_id, repository, clock,
                    mode, traces, rejections, telemetry, required_coverage=set(),
                )
                if semantic is not None:
                    selected.append(semantic)
        else:
            forced_candidates = [
                candidate
                for kind in (
                    MemoryKind.EPISODIC,
                    MemoryKind.USER_SEMANTIC,
                    MemoryKind.ORG_SEMANTIC,
                )
                if (
                    candidate := self._select(
                        kind, node, session.task_id, user_id, org_id, repository,
                        clock, mode, traces, rejections, telemetry,
                    )
                ) is not None
            ]
            memory_ids = [candidate.record.memory_id for candidate in forced_candidates]
            if len(set(memory_ids)) != len(memory_ids):
                raise RecallError("safe-pool memory_id crosses memory banks")
            forced_candidates.sort(key=lambda candidate: (
                -candidate.confidence,
                -candidate.embedding_score,
                -candidate.ranked.ppr_score,
                candidate.record.memory_id,
            ))
            selected = forced_candidates[:1]
            for candidate in forced_candidates[1:]:
                _replace_telemetry_reason(
                    telemetry,
                    candidate.recall_attempt_id,
                    RecallReasonCode.FORCED_SAFE_TOP1_LIMIT_REJECTION,
                )
                _replace_forced_trace_with_abstention(traces, candidate)

        injections: list[MemoryInjection] = []
        for candidate in selected:
            category = "episodic" if candidate.record.kind == MemoryKind.EPISODIC else "semantic"
            limit = (self.config.max_episodic_per_node if category == "episodic"
                     else self.config.max_semantic_per_node)
            if working_session.count(node.node_id, category) >= limit:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "per_node_limit"})
                _replace_telemetry_reason(
                    telemetry, candidate.recall_attempt_id,
                    RecallReasonCode.PER_NODE_INJECTION_LIMIT_REJECTION,
                )
                continue
            if candidate.record.memory_id in working_session.injected_memory_ids:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "already_injected"})
                _replace_telemetry_reason(
                    telemetry, candidate.recall_attempt_id,
                    RecallReasonCode.ALREADY_INJECTED_REJECTION,
                )
                continue
            if working_session.total_injections >= self.config.max_task_injections:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "task_injection_limit"})
                _replace_telemetry_reason(
                    telemetry, candidate.recall_attempt_id,
                    RecallReasonCode.TASK_INJECTION_LIMIT_REJECTION,
                )
                break
            payload = candidate.record.execution_view
            raw = payload.encode("utf-8")
            if not raw:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "empty_execution_view"})
                _replace_telemetry_reason(
                    telemetry, candidate.recall_attempt_id,
                    RecallReasonCode.EMPTY_EXECUTION_VIEW_REJECTION,
                )
                continue
            if working_session.context_bytes + len(raw) > self.config.context_budget_bytes:
                rejections.append({"memory_id": candidate.record.memory_id, "reason": "context_budget"})
                _replace_telemetry_reason(
                    telemetry, candidate.recall_attempt_id,
                    RecallReasonCode.CONTEXT_INJECTION_BUDGET_REJECTION,
                )
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
            _replace_telemetry_reason(
                telemetry, candidate.recall_attempt_id, RecallReasonCode.INJECTED,
            )
        if self.injection_auditor is not None and injections:
            # No caller-visible session state is mutated until the exact-byte
            # PostgreSQL access audit commits successfully.
            self.injection_auditor(tuple(injections))
            for injection in injections:
                session.record(injection)
        return RecallDecision(
            node.node_id,
            tuple(injections),
            tuple(traces),
            tuple(rejections),
            _telemetry_rows(telemetry) if emit_telemetry else (),
        )

    def _semantic_backoff(
        self,
        node: SemanticSubtaskNode,
        target_id: str,
        user_id: str,
        org_id: str,
        repository: str,
        now: Optional[datetime],
        mode: RecallSelectionMode,
        traces: list[dict],
        rejections: list[dict],
        telemetry: list[RecallDecisionTelemetry],
        *,
        required_coverage: set[str],
    ) -> Optional[_Candidate]:
        for kind in (MemoryKind.USER_SEMANTIC, MemoryKind.ORG_SEMANTIC):
            candidate = self._select(
                kind, node, target_id, user_id, org_id, repository, now, mode,
                traces, rejections, telemetry, required_coverage=required_coverage,
            )
            if candidate is not None:
                return candidate
        return None

    def _select(
        self,
        kind: MemoryKind,
        node: SemanticSubtaskNode,
        target_id: str,
        user_id: str,
        org_id: str,
        repository: str,
        now: Optional[datetime],
        mode: RecallSelectionMode,
        traces: list[dict],
        rejections: list[dict],
        telemetry: list[RecallDecisionTelemetry],
        *,
        required_coverage: set[str] | None = None,
    ) -> Optional[_Candidate]:
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
        query_telemetry = dict(snapshot.query_telemetry or {})
        before_count = query_telemetry.get(
            "candidate_count_before_filter", len(snapshot.records)
        )
        if (
            type(before_count) is not int
            or before_count < 0
            or before_count < len(snapshot.records)
        ):
            before_count = len(snapshot.records)
        upstream_filter_reasons = query_telemetry.get("filter_reason_codes", ())
        if not isinstance(upstream_filter_reasons, (list, tuple, set, frozenset)):
            upstream_filter_reasons = ()
        filter_reasons = {str(reason) for reason in upstream_filter_reasons if str(reason)}
        eligible: dict[str, MemoryRecord] = {}
        for memory_id in sorted(snapshot.records):
            record = snapshot.records[memory_id]
            reason = _rejection_reason(record, kind, user_id, org_id, repository, now)
            if reason is None and self.require_safe_pool_metadata:
                reason = _safe_pool_rejection_reason(
                    record,
                    target_id=target_id,
                    active_node=node,
                )
            if reason is None and required_coverage and not (set(record.coverage) & required_coverage):
                reason = "not_complementary"
            if reason:
                rejections.append({"bank": kind.value, "memory_id": memory_id, "reason": reason})
                filter_reasons.add(reason)
            else:
                eligible[memory_id] = record
        if not eligible:
            traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "no_eligible"})
            reason_code = _no_eligible_reason(before_count, filter_reasons)
            telemetry.append(self._telemetry(
                target_id=target_id,
                node=node,
                kind=kind,
                mode=mode,
                candidate_count_before_filter=before_count,
                candidate_count_after_filter=0,
                reason=reason_code,
                filter_reason_codes=filter_reasons,
            ))
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
            embedding_scores = query_telemetry.get("embedding_scores", {})
            if not isinstance(embedding_scores, Mapping):
                embedding_scores = {}

            def fallback_embedding(memory_id: str) -> float:
                value = embedding_scores.get(memory_id)
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    return 0.0
                return round(float(value), 15)

            fallback_id = min(
                eligible,
                key=lambda memory_id: (
                    -fallback_embedding(memory_id), memory_id,
                ),
            )
            if mode == RecallSelectionMode.CURRENT_GATE:
                traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "no_seed_match"})
                telemetry.append(self._telemetry(
                    target_id=target_id,
                    node=node,
                    kind=kind,
                    mode=mode,
                    candidate_count_before_filter=before_count,
                    candidate_count_after_filter=len(eligible),
                    reason=RecallReasonCode.NO_SEED_MATCH,
                    top_candidate_id=fallback_id,
                    top_embedding_score=fallback_embedding(fallback_id),
                    top_ppr_score=0.0,
                    top_seed_score=0.0,
                    score_source=(
                        "VECTOR_INDEX_EMBEDDING_SCORE"
                        if fallback_id in embedding_scores
                        else "ZERO_NO_POSITIVE_SEED"
                    ),
                    filter_reason_codes=filter_reasons,
                ))
                return None
            # A zero utility score is still a safe candidate in C2.  The arm
            # bypasses utility admission, not eligibility, and therefore must
            # choose a deterministic zero-score record rather than relabel it
            # as absent.
            ranked_memories = [RankedNode(fallback_id, 0.0, 0.0, 0.0)]
        first = ranked_memories[0]
        confidence = round(first.score * eligible[first.node_id].quality, 15)
        second = (ranked_memories[1].score * eligible[ranked_memories[1].node_id].quality
                  if len(ranked_memories) > 1 else 0.0)
        margin = round(confidence - second, 15)
        attempt_id = _recall_attempt_id(target_id, node.node_id, kind.value, mode)
        embedding_scores = query_telemetry.get("embedding_scores", {})
        if isinstance(embedding_scores, Mapping):
            raw_embedding_score = embedding_scores.get(first.node_id)
        else:
            raw_embedding_score = None
        if isinstance(raw_embedding_score, bool) or not isinstance(
            raw_embedding_score, (int, float)
        ):
            embedding_score = first.seed_score
            score_source = "NORMALIZED_COMBINED_EMBEDDING_LEXICAL_SEED"
        else:
            embedding_score = round(float(raw_embedding_score), 15)
            score_source = "VECTOR_INDEX_EMBEDDING_SCORE"
        base_telemetry = self._telemetry(
            target_id=target_id,
            node=node,
            kind=kind,
            mode=mode,
            candidate_count_before_filter=before_count,
            candidate_count_after_filter=len(eligible),
            reason=RecallReasonCode.CANDIDATE_SELECTED,
            top_candidate_id=first.node_id,
            top_embedding_score=embedding_score,
            top_ppr_score=first.ppr_score,
            top_seed_score=first.seed_score,
            score_source=score_source,
            filter_reason_codes=filter_reasons,
        )
        if (
            mode == RecallSelectionMode.CURRENT_GATE
            and confidence < self.config.min_confidence
        ):
            traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "low_confidence",
                           "confidence": confidence, "margin": margin})
            telemetry.append(replace(
                base_telemetry,
                final_reason_code=RecallReasonCode.BELOW_CONFIDENCE_THRESHOLD.value,
            ))
            return None
        if mode == RecallSelectionMode.CURRENT_GATE and margin < self.config.min_margin:
            traces.append({"bank": kind.value, "decision": "ABSTAIN", "reason": "low_margin",
                           "confidence": confidence, "margin": margin})
            telemetry.append(replace(
                base_telemetry,
                final_reason_code=RecallReasonCode.BELOW_MARGIN_THRESHOLD.value,
            ))
            return None
        traces.append({"bank": kind.value, "decision": "USE", "memory_id": first.node_id,
                       "confidence": confidence, "margin": margin, "graph_hash": snapshot.graph_hash})
        telemetry.append(base_telemetry)
        return _Candidate(
            eligible[first.node_id], confidence, margin, first, snapshot.graph_hash,
            attempt_id, embedding_score,
        )

    def _empty_telemetry(
        self,
        target_id: str,
        subtask_id: str,
        bank_type: str,
        mode: RecallSelectionMode,
        reason: RecallReasonCode,
    ) -> RecallDecisionTelemetry:
        return RecallDecisionTelemetry(
            recall_attempt_id=_recall_attempt_id(
                target_id, subtask_id, bank_type, mode
            ),
            target_id=target_id,
            subtask_id=subtask_id,
            bank_type=bank_type,
            candidate_count_before_filter=0,
            candidate_count_after_filter=0,
            top_candidate_id=None,
            top_embedding_score=None,
            top_ppr_score=None,
            threshold=self._thresholds(),
            final_reason_code=reason.value,
            selection_mode=mode.value,
        )

    def _telemetry(
        self,
        *,
        target_id: str,
        node: SemanticSubtaskNode,
        kind: MemoryKind,
        mode: RecallSelectionMode,
        candidate_count_before_filter: int,
        candidate_count_after_filter: int,
        reason: RecallReasonCode,
        top_candidate_id: Optional[str] = None,
        top_embedding_score: Optional[float] = None,
        top_ppr_score: Optional[float] = None,
        top_seed_score: Optional[float] = None,
        score_source: Optional[str] = None,
        filter_reason_codes: set[str] | None = None,
    ) -> RecallDecisionTelemetry:
        return RecallDecisionTelemetry(
            recall_attempt_id=_recall_attempt_id(
                target_id, node.node_id, kind.value, mode
            ),
            target_id=target_id,
            subtask_id=node.node_id,
            bank_type=kind.value,
            candidate_count_before_filter=candidate_count_before_filter,
            candidate_count_after_filter=candidate_count_after_filter,
            top_candidate_id=top_candidate_id,
            top_embedding_score=top_embedding_score,
            top_ppr_score=top_ppr_score,
            threshold=self._thresholds(),
            final_reason_code=reason.value,
            selection_mode=mode.value,
            top_seed_score=top_seed_score,
            score_source=score_source,
            filter_reason_codes=tuple(sorted(filter_reason_codes or ())),
        )

    def _thresholds(self) -> dict[str, float]:
        return {
            "min_confidence": self.config.min_confidence,
            "min_margin": self.config.min_margin,
        }


def _selection_mode(value: RecallSelectionMode | str) -> RecallSelectionMode:
    try:
        return RecallSelectionMode(value)
    except (TypeError, ValueError) as exc:
        raise RecallError("unsupported recall selection mode") from exc


_FILTER_REASON_TO_FINAL_REASON = {
    "cross_user_private": RecallReasonCode.PERMISSION_GATE_REJECTED,
    "wrong_org": RecallReasonCode.TENANT_GATE_REJECTED,
    "wrong_repository": RecallReasonCode.REPOSITORY_GATE_REJECTED,
    "path_not_allowed": RecallReasonCode.PATH_GATE_REJECTED,
    "version_invalid": RecallReasonCode.VERSION_GATE_REJECTED,
    "stale": RecallReasonCode.VERSION_GATE_REJECTED,
    "validity_time_unknown": RecallReasonCode.VERSION_GATE_REJECTED,
    "not_valid_yet": RecallReasonCode.VERSION_GATE_REJECTED,
    "expired": RecallReasonCode.VERSION_GATE_REJECTED,
    "unverified_semantic": RecallReasonCode.PROVENANCE_GATE_REJECTED,
    "unreviewed_shared_semantic": RecallReasonCode.PROVENANCE_GATE_REJECTED,
    "source_provenance_invalid": RecallReasonCode.PROVENANCE_GATE_REJECTED,
    "target_derived_memory": RecallReasonCode.LEAKAGE_GATE_REJECTED,
    "not_servable": RecallReasonCode.QUARANTINE_GATE_REJECTED,
    "quarantined": RecallReasonCode.QUARANTINE_GATE_REJECTED,
    "CANONICAL_OR_SELF_EXCLUSION": RecallReasonCode.CANONICAL_GATE_REJECTED,
    "CANONICAL_GATE_REJECTED": RecallReasonCode.CANONICAL_GATE_REJECTED,
    "LEAKAGE_GATE_REJECTED": RecallReasonCode.LEAKAGE_GATE_REJECTED,
    "safe_pool_permission_invalid": RecallReasonCode.PERMISSION_GATE_REJECTED,
    "safe_pool_tenant_invalid": RecallReasonCode.TENANT_GATE_REJECTED,
    "safe_pool_repository_invalid": RecallReasonCode.REPOSITORY_GATE_REJECTED,
    "safe_pool_path_invalid": RecallReasonCode.PATH_GATE_REJECTED,
    "safe_pool_path_mismatch": RecallReasonCode.PATH_GATE_REJECTED,
    "safe_pool_target_path_unknown": RecallReasonCode.PATH_GATE_REJECTED,
    "safe_pool_version_invalid": RecallReasonCode.VERSION_GATE_REJECTED,
    "safe_pool_provenance_invalid": RecallReasonCode.PROVENANCE_GATE_REJECTED,
    "safe_pool_leakage_metadata_invalid": RecallReasonCode.LEAKAGE_GATE_REJECTED,
    "safe_pool_target_derived": RecallReasonCode.LEAKAGE_GATE_REJECTED,
    "safe_pool_quarantine_invalid": RecallReasonCode.QUARANTINE_GATE_REJECTED,
    "safe_pool_payload_hash_invalid": RecallReasonCode.CANONICAL_GATE_REJECTED,
}


def _no_eligible_reason(
    candidate_count_before_filter: int,
    filter_reason_codes: set[str],
) -> RecallReasonCode:
    if candidate_count_before_filter == 0:
        return RecallReasonCode.NO_CANDIDATE_GENERATED
    if filter_reason_codes == {"not_complementary"}:
        return RecallReasonCode.NO_COMPLEMENTARY_CANDIDATE
    mapped = {
        _FILTER_REASON_TO_FINAL_REASON[reason]
        for reason in filter_reason_codes
        if reason in _FILTER_REASON_TO_FINAL_REASON
    }
    if len(mapped) == 1 and all(
        reason in _FILTER_REASON_TO_FINAL_REASON for reason in filter_reason_codes
    ):
        return next(iter(mapped))
    return RecallReasonCode.NO_SAFE_CANDIDATE


def _recall_attempt_id(
    target_id: str,
    subtask_id: str,
    bank_type: str,
    mode: RecallSelectionMode,
) -> str:
    material = "\x1f".join((
        _RECALL_TELEMETRY_SCHEMA,
        str(target_id),
        str(subtask_id),
        str(bank_type),
        mode.value,
    )).encode("utf-8")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _telemetry_rows(
    telemetry: list[RecallDecisionTelemetry],
) -> tuple[dict, ...]:
    if any(
        row.final_reason_code == RecallReasonCode.CANDIDATE_SELECTED.value
        for row in telemetry
    ):
        raise RecallError("recall telemetry contains an unfinalized candidate")
    return tuple(
        normalize_recall_decision_telemetry(
            item.as_row(), expected_target_id=item.target_id
        )
        for item in telemetry
    )


def _replace_telemetry_reason(
    telemetry: list[RecallDecisionTelemetry],
    recall_attempt_id: str,
    reason: RecallReasonCode,
) -> None:
    matches = [
        index
        for index, row in enumerate(telemetry)
        if row.recall_attempt_id == recall_attempt_id
    ]
    if len(matches) != 1:
        raise RecallError("recall telemetry attempt identity is not unique")
    index = matches[0]
    telemetry[index] = replace(
        telemetry[index], final_reason_code=reason.value
    )


def _replace_forced_trace_with_abstention(
    traces: list[dict], candidate: _Candidate
) -> None:
    matches = [
        index
        for index, row in enumerate(traces)
        if row.get("bank") == candidate.record.kind.value
        and row.get("decision") == "USE"
        and row.get("memory_id") == candidate.record.memory_id
    ]
    if len(matches) != 1:
        raise RecallError("forced-safe candidate has no unique bank trace")
    index = matches[0]
    row = dict(traces[index])
    row["decision"] = "ABSTAIN"
    row["reason"] = "forced_safe_not_global_top1"
    traces[index] = row


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


_SAFE_POOL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_POOL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_POOL_UTC = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


def _safe_pool_rejection_reason(
    record: MemoryRecord,
    *,
    target_id: str,
    active_node: SemanticSubtaskNode,
) -> Optional[str]:
    """Validate the dedicated diagnostic source-pool contract fail closed.

    These fields are not inferred from retrieval scores or filled with
    defaults.  They must already be bound to the canonical source record by
    the frozen source-bank loader.  This gate is opt-in and therefore cannot
    alter the legacy/current production reader.
    """

    metadata = record.metadata
    target_derived = metadata.get("target_derived")
    source_task_id = metadata.get("source_task_id")
    if (
        target_derived is not False
        or not isinstance(source_task_id, str)
        or not source_task_id
    ):
        return "safe_pool_leakage_metadata_invalid"
    if source_task_id == target_id:
        return "safe_pool_target_derived"

    if metadata.get("permission_scope") != "PUBLIC_READ":
        return "safe_pool_permission_invalid"
    if metadata.get("tenant_scope") != "BENCHMARK_ISOLATED":
        return "safe_pool_tenant_invalid"

    source_repository = metadata.get("source_repository")
    if not isinstance(source_repository, str) or not source_repository.strip():
        return "safe_pool_repository_invalid"

    path_scope = metadata.get("path_scope")
    if not isinstance(path_scope, str) or not path_scope.strip():
        return "safe_pool_path_invalid"
    normalized_scope = path_scope.strip().replace("\\", "/")
    if (
        normalized_scope.startswith("/")
        or any(part == ".." for part in normalized_scope.split("/"))
    ):
        return "safe_pool_path_invalid"
    # The frozen source-bank contract uses the exact repository-wide scope
    # ``**``.  It is independently validated as part of the canonical source
    # record, so optional decomposer file hints cannot narrow or invalidate it.
    # Every narrower scope remains fail-closed when the active node has no
    # canonical path or when no path matches.
    if normalized_scope != "**":
        if not active_node.files:
            return "safe_pool_target_path_unknown"
        normalized_files = tuple(
            path.strip().replace("\\", "/") for path in active_node.files
        )
        if any(
            not path
            or path.startswith("/")
            or any(part == ".." for part in path.split("/"))
            for path in normalized_files
        ):
            return "safe_pool_target_path_unknown"
        if normalized_scope.endswith("/"):
            path_matches = any(
                path.startswith(normalized_scope) for path in normalized_files
            )
        elif any(character in normalized_scope for character in "*?["):
            path_matches = any(
                fnmatch.fnmatchcase(path, normalized_scope)
                for path in normalized_files
            )
        else:
            path_matches = any(
                path == normalized_scope or path.startswith(normalized_scope + "/")
                for path in normalized_files
            )
        if not path_matches:
            return "safe_pool_path_mismatch"

    source_commit = metadata.get("source_commit")
    if (
        metadata.get("version_scope") != "EXACT_SOURCE_COMMIT"
        or not isinstance(source_commit, str)
        or not _SAFE_POOL_COMMIT.fullmatch(source_commit)
        or record.version != source_commit
        or not record.version_valid
    ):
        return "safe_pool_version_invalid"

    required_strings = (
        "source_dataset_id",
        "bank_type",
        "source_timestamp",
        "verification_evidence_sha256",
        "provenance_sha256",
    )
    if any(
        not isinstance(metadata.get(key), str) or not str(metadata[key]).strip()
        for key in required_strings
    ):
        return "safe_pool_provenance_invalid"
    if (
        not _SAFE_POOL_UTC.fullmatch(str(metadata["source_timestamp"]))
        or any(
            not _SAFE_POOL_SHA256.fullmatch(str(metadata[key]))
            for key in ("verification_evidence_sha256", "provenance_sha256")
        )
        or record.verified is not True
        or record.source_outcome != "passed"
    ):
        return "safe_pool_provenance_invalid"
    try:
        _parse_time(str(metadata["source_timestamp"]))
    except (TypeError, ValueError):
        return "safe_pool_provenance_invalid"

    payload_sha256 = metadata.get("payload_sha256")
    if (
        not isinstance(payload_sha256, str)
        or not _SAFE_POOL_SHA256.fullmatch(payload_sha256)
    ):
        return "safe_pool_payload_hash_invalid"

    if metadata.get("quarantined") is not False:
        return "safe_pool_quarantine_invalid"
    return None


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
