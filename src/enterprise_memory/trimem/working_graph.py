"""Deterministic short-term working graph for a coding-agent task.

The graph models *semantic* subtasks (for example, "propagate the new timeout
argument to every HTTP call site"), not generic agent stages such as ANALYZE or
EDIT.  It is deliberately independent of a model/provider and can therefore be
checkpointed, replayed, and tested without credentials.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional


PENDING = "PENDING"
ACTIVE = "ACTIVE"
COMPLETED = "COMPLETED"

_GENERIC_STAGE_WORDS = {
    "analyze", "analyse", "analysis", "reproduce", "reproduction", "edit", "modify",
    "modification", "verify", "verification", "validate", "validation", "task", "issue",
    "code", "fix", "solution", "repo", "repository",
}


class WorkingGraphError(ValueError):
    pass


class GenericStageOnlyError(WorkingGraphError):
    pass


class DependencyError(WorkingGraphError):
    pass


class CompletionEvidenceRequired(WorkingGraphError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=str).encode("utf-8")


def _sha256(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = _canonical_bytes(value)
    return hashlib.sha256(raw).hexdigest()


def _tuple(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in (values or ()) if str(value).strip()))


def _is_generic_stage_only(objective: str) -> bool:
    tokens = {token.lower() for token in re.findall(r"[A-Za-z]+", objective or "")}
    return not tokens or tokens <= _GENERIC_STAGE_WORDS


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    kind: str
    summary: str
    payload_hash: str
    source: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    supports_completion: bool = False
    observed_at: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.kind or not self.summary.strip() or not self.payload_hash:
            raise WorkingGraphError("evidence requires id, kind, non-empty summary, and payload_hash")
        object.__setattr__(self, "attributes", dict(self.attributes or {}))

    @classmethod
    def capture(cls, kind: str, summary: str, payload: Any, *, source: str = "",
                attributes: Optional[Mapping[str, Any]] = None, supports_completion: bool = False,
                observed_at: str = "", evidence_id: Optional[str] = None) -> "Evidence":
        payload_hash = _sha256(payload)
        stable_id = evidence_id or "ev_" + _sha256({
            "kind": kind, "summary": summary, "payload_hash": payload_hash,
            "source": source, "observed_at": observed_at,
        })[:20]
        return cls(stable_id, kind, summary, payload_hash, source, dict(attributes or {}),
                   supports_completion, observed_at)

    def canonical_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id, "kind": self.kind, "summary": self.summary,
            "payload_hash": self.payload_hash, "source": self.source,
            "attributes": dict(self.attributes), "supports_completion": self.supports_completion,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class SubtaskSpec:
    objective: str
    operation: str
    node_id: Optional[str] = None
    dependencies: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    apis: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    required_memory_facets: tuple[str, ...] = ("operation", "precondition", "verification")

    def __post_init__(self) -> None:
        objective = self.objective.strip()
        operation = self.operation.strip()
        if not objective or not operation:
            raise WorkingGraphError("semantic subtask requires objective and operation")
        if _is_generic_stage_only(objective):
            raise GenericStageOnlyError(
                "generic ANALYZE/REPRODUCE/EDIT/VERIFY stages are not semantic subtasks")
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "operation", operation)
        for name in ("dependencies", "preconditions", "invariants", "files", "symbols", "apis",
                     "errors", "tests", "required_memory_facets"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))


@dataclass
class SemanticSubtaskNode:
    node_id: str
    objective: str
    operation: str
    dependencies: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    apis: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    required_memory_facets: tuple[str, ...] = ()
    status: str = PENDING
    created_order: int = 0
    evidence: list[Evidence] = field(default_factory=list)
    completion_evidence: list[Evidence] = field(default_factory=list)

    def canonical_dict(self) -> dict:
        return {
            "node_id": self.node_id, "objective": self.objective, "operation": self.operation,
            "dependencies": list(self.dependencies), "preconditions": list(self.preconditions),
            "invariants": list(self.invariants), "files": list(self.files), "symbols": list(self.symbols),
            "apis": list(self.apis), "errors": list(self.errors), "tests": list(self.tests),
            "required_memory_facets": list(self.required_memory_facets), "status": self.status,
            "created_order": self.created_order,
            "evidence": [item.canonical_dict() for item in self.evidence],
            "completion_evidence": [item.canonical_dict() for item in self.completion_evidence],
        }


class ShortTermWorkingGraph:
    """One task-local DAG with exactly zero or one active semantic subtask."""

    schema_version = "trimem/working_graph/1.0"

    def __init__(self, task_id: str, objective: str, repository: str):
        if not task_id or not objective.strip() or not repository:
            raise WorkingGraphError("task_id, objective, and repository are required")
        self.task_id = task_id
        self.objective = objective.strip()
        self.repository = repository
        self.nodes: dict[str, SemanticSubtaskNode] = {}
        self.active_node_id: Optional[str] = None
        self.task_evidence: list[Evidence] = []
        self.revision = 0

    @property
    def active_node(self) -> Optional[SemanticSubtaskNode]:
        return self.nodes.get(self.active_node_id) if self.active_node_id else None

    def add_subtask(self, spec: SubtaskSpec) -> SemanticSubtaskNode:
        node_id = spec.node_id or self._node_id(spec)
        if node_id in self.nodes:
            raise WorkingGraphError("duplicate subtask node_id %r" % node_id)
        missing = sorted(set(spec.dependencies) - set(self.nodes))
        if missing:
            raise DependencyError("unknown dependencies for %s: %s" % (node_id, missing))
        node = SemanticSubtaskNode(
            node_id=node_id, objective=spec.objective, operation=spec.operation,
            dependencies=spec.dependencies, preconditions=spec.preconditions, invariants=spec.invariants,
            files=spec.files, symbols=spec.symbols, apis=spec.apis, errors=spec.errors, tests=spec.tests,
            required_memory_facets=spec.required_memory_facets, created_order=len(self.nodes),
        )
        self.nodes[node_id] = node
        try:
            self._assert_acyclic()
        except Exception:
            del self.nodes[node_id]
            raise
        self.revision += 1
        return node

    def add_dependency(self, node_id: str, dependency_id: str) -> None:
        node = self._require_node(node_id)
        self._require_node(dependency_id)
        if node.status != PENDING:
            raise DependencyError("dependencies may only change while a node is pending")
        previous = node.dependencies
        node.dependencies = _tuple((*previous, dependency_id))
        try:
            self._assert_acyclic()
        except Exception:
            node.dependencies = previous
            raise
        self.revision += 1

    def ready_nodes(self) -> list[SemanticSubtaskNode]:
        ready = [node for node in self.nodes.values() if node.status == PENDING and
                 all(self.nodes[dep].status == COMPLETED for dep in node.dependencies)]
        return sorted(ready, key=lambda node: (node.created_order, node.node_id))

    def activate(self, node_id: str) -> SemanticSubtaskNode:
        node = self._require_node(node_id)
        if self.active_node_id and self.active_node_id != node_id:
            raise WorkingGraphError("another subtask is already active: %s" % self.active_node_id)
        if node.status == COMPLETED:
            raise WorkingGraphError("completed subtask cannot be reactivated")
        blocked = [dep for dep in node.dependencies if self.nodes[dep].status != COMPLETED]
        if blocked:
            raise DependencyError("dependency order violation; incomplete: %s" % sorted(blocked))
        node.status = ACTIVE
        self.active_node_id = node_id
        self.revision += 1
        return node

    def activate_next(self) -> Optional[SemanticSubtaskNode]:
        if self.active_node is not None:
            return self.active_node
        ready = self.ready_nodes()
        return self.activate(ready[0].node_id) if ready else None

    def record_evidence(self, evidence: Evidence, node_id: Optional[str] = None) -> None:
        target_id = node_id if node_id is not None else self.active_node_id
        if target_id is None:
            if any(item.evidence_id == evidence.evidence_id for item in self.task_evidence):
                return
            self.task_evidence.append(evidence)
            self.revision += 1
            return
        node = self._require_node(target_id)
        if any(item.evidence_id == evidence.evidence_id for item in node.evidence):
            return
        node.evidence.append(evidence)
        self._merge_evidence_anchors(node, evidence.attributes)
        self.revision += 1

    def update_from_evidence(self, evidence: Evidence, *, new_subtasks: Iterable[SubtaskSpec] = (),
                             dependency_additions: Iterable[tuple[str, str]] = ()) -> list[SemanticSubtaskNode]:
        """Record an observation, then deterministically revise the DAG because of that observation."""
        if self.active_node is None:
            raise WorkingGraphError("evidence-based DAG update requires one active subtask")
        self.record_evidence(evidence)
        added = [self.add_subtask(spec) for spec in new_subtasks]
        for node_id, dependency_id in dependency_additions:
            self.add_dependency(node_id, dependency_id)
        return added

    def complete_active(self, evidence: Evidence) -> SemanticSubtaskNode:
        node = self.active_node
        if node is None:
            raise WorkingGraphError("no active subtask")
        if not evidence.supports_completion:
            raise CompletionEvidenceRequired("completion requires explicit supporting evidence")
        self.record_evidence(evidence, node.node_id)
        if not any(item.evidence_id == evidence.evidence_id for item in node.completion_evidence):
            node.completion_evidence.append(evidence)
        node.status = COMPLETED
        self.active_node_id = None
        self.revision += 1
        return node

    @property
    def complete(self) -> bool:
        return bool(self.nodes) and all(node.status == COMPLETED for node in self.nodes.values())

    def snapshot(self) -> dict:
        return {
            "schema_version": self.schema_version, "task_id": self.task_id,
            "objective": self.objective, "repository": self.repository,
            "revision": self.revision, "active_node_id": self.active_node_id,
            "task_evidence": [item.canonical_dict() for item in self.task_evidence],
            "nodes": [node.canonical_dict() for node in sorted(
                self.nodes.values(), key=lambda item: (item.created_order, item.node_id))],
        }

    def content_hash(self) -> str:
        return _sha256(self.snapshot())

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "ShortTermWorkingGraph":
        if snapshot.get("schema_version") != cls.schema_version:
            raise WorkingGraphError("unsupported working graph schema")
        graph = cls(str(snapshot["task_id"]), str(snapshot["objective"]), str(snapshot["repository"]))
        for row in sorted(snapshot.get("nodes", []), key=lambda item: (item["created_order"], item["node_id"])):
            node = graph.add_subtask(SubtaskSpec(
                node_id=row["node_id"], objective=row["objective"], operation=row["operation"],
                dependencies=tuple(row.get("dependencies", ())), preconditions=tuple(row.get("preconditions", ())),
                invariants=tuple(row.get("invariants", ())), files=tuple(row.get("files", ())),
                symbols=tuple(row.get("symbols", ())), apis=tuple(row.get("apis", ())),
                errors=tuple(row.get("errors", ())), tests=tuple(row.get("tests", ())),
                required_memory_facets=tuple(row.get("required_memory_facets", ())),
            ))
            node.status = row.get("status", PENDING)
            node.created_order = int(row.get("created_order", node.created_order))
            node.evidence = [cls._evidence_from_dict(item) for item in row.get("evidence", ())]
            node.completion_evidence = [cls._evidence_from_dict(item)
                                        for item in row.get("completion_evidence", ())]
        graph.task_evidence = [cls._evidence_from_dict(item) for item in snapshot.get("task_evidence", ())]
        graph.active_node_id = snapshot.get("active_node_id")
        valid_statuses = {PENDING, ACTIVE, COMPLETED}
        for node in graph.nodes.values():
            if node.status not in valid_statuses:
                raise WorkingGraphError("invalid node status %r" % node.status)
            completion_ids = {item.evidence_id for item in node.completion_evidence}
            evidence_ids = {item.evidence_id for item in node.evidence}
            if not completion_ids <= evidence_ids:
                raise WorkingGraphError("completion evidence must also be recorded as node evidence")
            if any(not item.supports_completion for item in node.completion_evidence):
                raise WorkingGraphError("invalid completion evidence in snapshot")
            if node.status == COMPLETED and not node.completion_evidence:
                raise WorkingGraphError("completed subtask lacks completion evidence")
            if node.status in {ACTIVE, COMPLETED} and any(
                    graph.nodes[dependency_id].status != COMPLETED
                    for dependency_id in node.dependencies):
                raise WorkingGraphError("started subtask has an incomplete dependency")
        if graph.active_node_id:
            active = graph._require_node(graph.active_node_id)
            if active.status != ACTIVE or sum(node.status == ACTIVE for node in graph.nodes.values()) != 1:
                raise WorkingGraphError("invalid active-node state in snapshot")
        elif any(node.status == ACTIVE for node in graph.nodes.values()):
            raise WorkingGraphError("snapshot has an ACTIVE node but no active_node_id")
        graph.revision = int(snapshot.get("revision", 0))
        graph._assert_acyclic()
        return graph

    @staticmethod
    def _evidence_from_dict(row: Mapping[str, Any]) -> Evidence:
        return Evidence(
            evidence_id=row["evidence_id"], kind=row["kind"], summary=row["summary"],
            payload_hash=row["payload_hash"], source=row.get("source", ""),
            attributes=row.get("attributes", {}), supports_completion=bool(row.get("supports_completion")),
            observed_at=row.get("observed_at", ""),
        )

    def _node_id(self, spec: SubtaskSpec) -> str:
        return "st_" + _sha256({
            "task_id": self.task_id, "objective": spec.objective, "operation": spec.operation,
            "dependencies": spec.dependencies, "ordinal": len(self.nodes),
        })[:20]

    def _require_node(self, node_id: str) -> SemanticSubtaskNode:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise WorkingGraphError("unknown subtask %r" % node_id) from None

    @staticmethod
    def _merge_evidence_anchors(node: SemanticSubtaskNode, attributes: Mapping[str, Any]) -> None:
        for field_name in ("files", "symbols", "apis", "errors", "tests", "preconditions", "invariants"):
            values = attributes.get(field_name)
            if values:
                if isinstance(values, str):
                    values = (values,)
                setattr(node, field_name, _tuple((*getattr(node, field_name), *values)))
        operation = attributes.get("predicted_operation")
        if operation:
            node.operation = str(operation).strip()

    def _assert_acyclic(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise DependencyError("subtask dependency cycle detected at %s" % node_id)
            if node_id in visited:
                return
            visiting.add(node_id)
            for dependency_id in sorted(self.nodes[node_id].dependencies):
                if dependency_id not in self.nodes:
                    raise DependencyError("unknown dependency %s" % dependency_id)
                visit(dependency_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in sorted(self.nodes):
            visit(node_id)
