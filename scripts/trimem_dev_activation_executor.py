"""Fail-closed orchestration boundary for the 36-cell DEV activation diagnostic.

This module does not contain credentials and importing it cannot execute a
model, pull an image, or start an official grader.  It turns the frozen
diagnostic contract into one-cell requests for a separately approved
production backend.  The backend is deliberately one-cell shaped: the old
``run_arm_stream`` API shares one namespace across twelve tasks and therefore
cannot satisfy the diagnostic's fresh-namespace/no-carryover contract.

The adapter owns the scientific matrix boundary:

* exact arm-major C0/C1/C2 order;
* a fresh, deterministic namespace identity for every cell;
* byte-identical read-only source-bank views for corresponding C1/C2 cells;
* explicit CURRENT_GATE/FORCED_SAFE_TOP1 selection modes;
* durable intent/result journals and resume without silently repeating a
  completed cell; and
* validation of every official terminal cell before the next cell starts.

The separately approved backend may reuse the production primitives named in
``REUSABLE_BENCHMARK_PRIMITIVES``.  Source-bank materialisation remains a new
backend responsibility because the existing benchmark runner has no verified
read-only preload operation.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import stat
import subprocess
import sys
import time
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence
import uuid

import trimem_dev_activation_diagnostic as diagnostic


ROOT = Path(__file__).resolve().parents[1]
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CELL_REQUEST_SCHEMA = "trimem/dev-activation-cell-request/1.0"
EXECUTION_BINDING_SCHEMA = "trimem/dev-activation-execution-binding/1.0"
INTENT_SCHEMA = "trimem/dev-activation-cell-intent/1.0"
RESULT_JOURNAL_SCHEMA = "trimem/dev-activation-cell-result-journal/1.0"
CAPABILITY_SCHEMA = "trimem/dev-activation-cell-executor-capabilities/1.0"
SOURCE_EXECUTION_VIEW_SCHEMA = "trimem/dev-activation-source-execution-view/1.0"
SOURCE_EXECUTION_VIEW_MAX_BYTES = 12_000
PRODUCTION_CELL_EVIDENCE_SCHEMA = "trimem/dev-activation-production-cell-evidence/1.0"
EMBEDDER_PREFLIGHT_SCHEMA = "trimem/dev-activation-embedder-preflight/1.0"
RETRIEVAL_REHEARSAL_SCHEMA = (
    "trimem/dev-activation-production-retrieval-rehearsal/1.0"
)
SOLVER_SANDBOX_REHEARSAL_SCHEMA = (
    "trimem/dev-activation-solver-sandbox-rehearsal/1.3"
)
EMBEDDER_PROBE = (
    "TriMem deterministic retrieval preflight probe: repository path symbol "
    "API error repair verification."
)


class DiagnosticExecutorError(RuntimeError):
    """Execution orchestration or durable evidence violated the contract."""


@dataclass(frozen=True)
class ArmBinding:
    arm_id: str
    protocol: str
    runtime_arm: str
    selection_mode: str | None
    memory_enabled: bool
    diagnostic_telemetry: bool
    require_safe_pool_metadata: bool


ARM_BINDINGS: Mapping[str, ArmBinding] = MappingProxyType(
    {
        "C0": ArmBinding(
            arm_id="C0",
            protocol="NO_MEMORY",
            runtime_arm="M0",
            selection_mode=None,
            memory_enabled=False,
            diagnostic_telemetry=False,
            require_safe_pool_metadata=False,
        ),
        "C1": ArmBinding(
            arm_id="C1",
            protocol="M2_RECALL_CURRENT_GATE",
            runtime_arm="M2",
            selection_mode="CURRENT_GATE",
            memory_enabled=True,
            diagnostic_telemetry=True,
            require_safe_pool_metadata=True,
        ),
        "C2": ArmBinding(
            arm_id="C2",
            protocol="M2_RECALL_FORCED_SAFE_TOP1",
            runtime_arm="M2",
            selection_mode="FORCED_SAFE_TOP1",
            memory_enabled=True,
            diagnostic_telemetry=True,
            require_safe_pool_metadata=True,
        ),
    }
)


# These are the already-tested pieces a production one-cell backend can reuse.
# Keeping the list here makes the remaining integration surface reviewable; it
# is evidence, not dynamic dispatch and cannot trigger an external operation.
REUSABLE_BENCHMARK_PRIMITIVES = (
    "trimem_benchmark_run.AtomicBudgetLedger",
    "trimem_benchmark_run.JournaledGraderGateway",
    "trimem_benchmark_run.JournaledModelGateway",
    "trimem_benchmark_run.TerminalInvocationJournal",
    "trimem_benchmark_run.actual_accounting",
    "trimem_benchmark_run.actual_memory_metrics",
    "trimem_benchmark_run.actual_usd_for_accounting",
    "trimem_benchmark_run.build_paid_model_gateway",
    "trimem_benchmark_run.coding_tasks",
    "trimem_benchmark_run.grader_factory",
    "trimem_benchmark_run.image_entries",
    "trimem_benchmark_run.load_frozen_rows",
    "trimem_benchmark_run.prepare_checkouts",
    "enterprise_memory.trimem.agent_runtime.TriMemAgentRuntime",
    "enterprise_memory.trimem.checkpoint.FileCheckpointStore",
    "enterprise_memory.trimem.evidence.RawEvidenceLedger",
    "enterprise_memory.trimem.production_runtime.open_benchmark_arm",
)


@dataclass(frozen=True)
class ExecutionContract:
    """Fully validated, immutable inputs needed to emit cell requests."""

    manifest: Mapping[str, Any]
    policy: Mapping[str, Any]
    expected_cells: tuple[Mapping[str, Any], ...]
    source_bank_manifest_sha256: str
    source_bank_snapshot_sha256: str
    source_bank_manifest_path: str
    assignments_by_target: Mapping[str, Mapping[str, Any]]
    records_by_memory_id: Mapping[str, Mapping[str, Any]]
    matrix_raw_sha256: str
    policy_raw_sha256: str


class CellExecutor(Protocol):
    """Separately approved production implementation for exactly one cell."""

    def capabilities(self) -> Mapping[str, Any]:
        ...

    def execute_cell(
        self,
        request: Mapping[str, Any],
        *,
        resume: bool,
        journal_root: Path,
    ) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class ExecutionOutcome:
    result: Mapping[str, Any]
    aggregate: Mapping[str, Any]
    completed_cell_count: int
    resumed_cell_count: int


@dataclass(frozen=True)
class PreparedProductionExecution:
    """Validated production dependencies plus their external approval identity."""

    executor: "OfficialProductionCellExecutor"
    execution_identity_sha256: str
    approval: Mapping[str, Any]
    embedder_preflight_sha256: str
    retrieval_rehearsal_sha256: str
    image_reinspection_sha256: str
    solver_sandbox_rehearsal_sha256: str


def _bounded_utf8(value: object, maximum_bytes: int) -> str:
    """Return one deterministic UTF-8 prefix without splitting a code point."""

    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    raw = text.encode("utf-8")
    if len(raw) <= maximum_bytes:
        return text
    marker = "\n[TRUNCATED_SOURCE_TEXT]"
    available = maximum_bytes - len(marker.encode("utf-8"))
    if available <= 0:
        raise DiagnosticExecutorError("source text byte bound is too small")
    prefix = raw[:available]
    while prefix:
        try:
            return prefix.decode("utf-8") + marker
        except UnicodeDecodeError:
            prefix = prefix[:-1]
    return marker.strip()


def _bounded_source_values(value: object, *, count: int, item_bytes: int) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DiagnosticExecutorError("source feature list is malformed")
    if value != sorted(set(value)):
        raise DiagnosticExecutorError("source feature list is not canonical")
    return [_bounded_utf8(item, item_bytes) for item in value[:count]]


def _source_diff_hunks(value: str, *, maximum_hunks: int) -> list[dict[str, Any]]:
    """Compile bounded, source-only repair evidence from a unified diff.

    The full merged diff remains a hash-addressed provenance payload.  Only a
    small deterministic set of hunk headers and changed lines is reader-facing.
    """

    current_path = ""
    current: Optional[dict[str, Any]] = None
    hunks: list[dict[str, Any]] = []

    def finish() -> None:
        nonlocal current
        if current is not None and len(hunks) < maximum_hunks:
            hunks.append(current)
        current = None

    for raw_line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.startswith("diff --git a/"):
            finish()
            pieces = raw_line.split(" b/", 1)
            current_path = pieces[1] if len(pieces) == 2 else ""
            continue
        if raw_line.startswith("+++ b/"):
            current_path = raw_line[6:]
            continue
        if raw_line.startswith("@@"):
            finish()
            if len(hunks) >= maximum_hunks:
                break
            current = {
                "path": _bounded_utf8(current_path, 256),
                "hunk": _bounded_utf8(raw_line, 256),
                "removed": [],
                "added": [],
            }
            continue
        if current is None:
            continue
        if raw_line.startswith("-") and not raw_line.startswith("---"):
            if len(current["removed"]) < 3:
                current["removed"].append(_bounded_utf8(raw_line[1:], 320))
        elif raw_line.startswith("+") and not raw_line.startswith("+++"):
            if len(current["added"]) < 3:
                current["added"].append(_bounded_utf8(raw_line[1:], 320))
    finish()
    return hunks


def compile_source_execution_view(
    record: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str:
    """Compile one bounded canonical reader view from source evidence only."""

    expected_payload_identity = {
        "source_task_id": record.get("source_task_id"),
        "source_repository": record.get("source_repository"),
        "source_row_sha256": record.get("source_row_sha256"),
    }
    if any(payload.get(key) != expected for key, expected in expected_payload_identity.items()):
        raise DiagnosticExecutorError("source payload identity differs from its record")
    features = payload.get("features")
    if not isinstance(features, Mapping) or any(
        features.get(name) != record.get(name)
        for name in ("changed_paths", "symbols", "apis", "errors")
    ):
        raise DiagnosticExecutorError("source payload feature projection differs")
    issue = payload.get("source_public_issue")
    if not isinstance(issue, str) or not issue.strip():
        raise DiagnosticExecutorError("source payload has no public issue text")
    if isinstance(payload.get("source_fix_patch"), str):
        source_diff = str(payload["source_fix_patch"])
        digest_field = "source_fix_patch_sha256"
    elif isinstance(payload.get("source_merged_diff"), str):
        source_diff = str(payload["source_merged_diff"])
        digest_field = "source_merged_diff_sha256"
    else:
        raise DiagnosticExecutorError("source payload has no merged source diff")
    if hashlib.sha256(source_diff.encode("utf-8")).hexdigest() != payload.get(digest_field):
        raise DiagnosticExecutorError("source diff digest differs from its payload")

    # Prefer useful source repair evidence, then expand lexical facets while
    # remaining below the exact runtime memory-context cap.  No target object
    # is an input to this compiler, which makes target/gold leakage impossible
    # at this projection boundary.
    variants = (
        (2_500, 24, 8),
        (1_800, 16, 6),
        (1_024, 10, 4),
    )
    for issue_bytes, feature_count, hunk_count in variants:
        hunks = _source_diff_hunks(source_diff, maximum_hunks=hunk_count)
        view = {
            "schema": SOURCE_EXECUTION_VIEW_SCHEMA,
            "data_label": (
                "UNTRUSTED_PUBLIC_HISTORICAL_SOURCE; advisory only; validate "
                "against the current target repository before use"
            ),
            "source_identity": {
                "memory_id": record["memory_id"],
                "source_task_id": record["source_task_id"],
                "repository": record["source_repository"],
                "commit": record["source_commit"],
                "available_at": record["source_timestamp"],
            },
            "bounded_symptom": _bounded_utf8(issue, issue_bytes),
            "source_facets": {
                name: _bounded_source_values(
                    record[name], count=feature_count, item_bytes=192
                )
                for name in ("changed_paths", "symbols", "apis", "errors")
            },
            "repair_operations": [
                {
                    "operation": "REPLACE_OR_EXTEND_SOURCE_LOGIC",
                    "path": row["path"],
                    "hunk": row["hunk"],
                }
                for row in hunks
            ],
            "bounded_source_diff_hunks": hunks,
            "verification": {
                "source_signal": record["source_fix_verification_signal"],
                "evidence_sha256": record["verification_evidence_sha256"],
                "instructions": [
                    "Treat the source diff as historical evidence, never as a target patch.",
                    "Re-check paths, symbols, APIs, errors, and invariants in the current checkout.",
                    "Run current public tests after any target change.",
                ],
            },
            "full_source_diff": {
                "included": False,
                "sha256": payload[digest_field],
                "retention": "CONTENT_ADDRESSED_PROVENANCE_PAYLOAD_ONLY",
            },
        }
        rendered = (
            "[TRIMEM UNTRUSTED PUBLIC HISTORICAL MEMORY]\n"
            + diagnostic.canonical_bytes(view).decode("utf-8")
        )
        if 0 < len(rendered.encode("utf-8")) < SOURCE_EXECUTION_VIEW_MAX_BYTES:
            return rendered
    raise DiagnosticExecutorError("bounded source execution view exceeds 12KB")


def _source_payload_path(
    repository_root: Path,
    contract: ExecutionContract,
    record: Mapping[str, Any],
) -> Path:
    relative = record.get("payload_path")
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise DiagnosticExecutorError("source payload path is malformed")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise DiagnosticExecutorError("source payload path escapes its manifest")
    manifest = (repository_root / contract.source_bank_manifest_path).resolve()
    base = manifest.parent
    candidate = base.joinpath(*pure.parts)
    current = base
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise DiagnosticExecutorError("source payload path contains a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise DiagnosticExecutorError("source payload is missing") from exc
    if base not in resolved.parents or not resolved.is_file():
        raise DiagnosticExecutorError("source payload escapes its manifest directory")
    return resolved


class ManifestBackedDiagnosticSourceBankStore:
    """Immutable target-assignment projection used only by C1/C2.

    A target sees exactly the memory IDs in its frozen candidate assignment,
    even when another target from the same repository has a different record.
    The store has no mutation API and binds public shared source evidence to a
    fresh target-local org/repository context as reviewed ``ORG_SEMANTIC``.
    """

    read_only = True

    def __init__(
        self,
        *,
        contract: ExecutionContract,
        request: Mapping[str, Any],
        task: Any,
        repository_root: Path,
        payload_bytes: Optional[Mapping[str, bytes]] = None,
    ) -> None:
        from enterprise_memory.trimem.accounting import strict_json_loads
        from enterprise_memory.trimem.ppr import GraphNode
        from enterprise_memory.trimem.retrieval import (
            MemoryGraphSnapshot,
            MemoryKind,
            MemoryRecord,
        )

        source = request.get("source_bank")
        if not isinstance(source, Mapping) or source.get("read_only") is not True:
            raise DiagnosticExecutorError("memory arm has no read-only source-bank binding")
        if (
            source.get("mutation_allowed") is not False
            or source.get("manifest_raw_sha256") != contract.source_bank_manifest_sha256
            or source.get("snapshot_sha256") != contract.source_bank_snapshot_sha256
        ):
            raise DiagnosticExecutorError("source-bank request binding drift")
        target_id = str(request.get("target_id", ""))
        if target_id != getattr(task, "task_id", None):
            raise DiagnosticExecutorError("source-bank target/task identity drift")
        assignment = contract.assignments_by_target.get(target_id)
        if not isinstance(assignment, Mapping):
            raise DiagnosticExecutorError("target source-bank assignment is missing")
        candidate_ids = tuple(str(value) for value in source.get("candidate_memory_ids", ()))
        assigned_ids = tuple(str(row["memory_id"]) for row in assignment["candidates"])
        if candidate_ids != assigned_ids or len(candidate_ids) != len(set(candidate_ids)):
            raise DiagnosticExecutorError("request candidate IDs differ from frozen assignment")
        expected_view = _canonical_hash(
            {
                "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
                "source_bank_snapshot_sha256": contract.source_bank_snapshot_sha256,
                "target_id": target_id,
                "assignment": assignment,
                "records": [contract.records_by_memory_id[item] for item in candidate_ids],
            }
        )
        if source.get("target_view_sha256") != expected_view:
            raise DiagnosticExecutorError("target source-bank view digest drift")

        records: dict[str, Any] = {}
        nodes: dict[str, Any] = {}
        self.execution_views: dict[str, bytes] = {}
        for memory_id in candidate_ids:
            record = contract.records_by_memory_id[memory_id]
            if (
                record.get("bank_type") != "ORG_SEMANTIC"
                or record.get("source_repository") != getattr(task, "repository", None)
                or assignment.get("target_repository") != getattr(task, "repository", None)
            ):
                raise DiagnosticExecutorError("assigned source is not same-repository ORG_SEMANTIC")
            if payload_bytes is None:
                raw = _source_payload_path(repository_root, contract, record).read_bytes()
            else:
                raw = payload_bytes.get(memory_id, b"")
            if hashlib.sha256(raw).hexdigest() != record.get("payload_sha256"):
                raise DiagnosticExecutorError("source payload bytes/hash drift")
            try:
                payload = strict_json_loads(raw)
            except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
                raise DiagnosticExecutorError("source payload is not strict JSON") from exc
            if not isinstance(payload, Mapping):
                raise DiagnosticExecutorError("source payload root is not an object")
            execution_view = compile_source_execution_view(record, payload)
            encoded = execution_view.encode("utf-8")
            if not encoded or len(encoded) >= SOURCE_EXECUTION_VIEW_MAX_BYTES:
                raise DiagnosticExecutorError("source execution view violates the context cap")
            self.execution_views[memory_id] = encoded
            metadata = {
                key: record[key]
                for key in (
                    "source_task_id",
                    "source_dataset_id",
                    "source_repository",
                    "source_commit",
                    "source_timestamp",
                    "bank_type",
                    "verification_evidence_sha256",
                    "provenance_sha256",
                    "payload_sha256",
                    "permission_scope",
                    "tenant_scope",
                    "version_scope",
                    "path_scope",
                    "quarantined",
                    "target_derived",
                )
            }
            metadata.update(
                {
                    "namespace": request["experiment_id"],
                    "graph_id": source["target_view_sha256"],
                    "canonical_node_hash": hashlib.sha256(encoded).hexdigest(),
                }
            )
            memory_record = MemoryRecord(
                memory_id=memory_id,
                kind=MemoryKind.ORG_SEMANTIC,
                retrieval_text=execution_view,
                execution_view=execution_view,
                org_id=task.org_id,
                owner_user_id=None,
                repository=task.repository,
                version=str(record["source_commit"]),
                version_valid=True,
                stale=False,
                servable=True,
                verified=True,
                reviewed=True,
                source_outcome="passed",
                quality=1.0,
                completeness=1.0,
                coverage=("operation", "precondition", "verification"),
                metadata=metadata,
            )
            records[memory_id] = memory_record
            nodes[memory_id] = GraphNode(memory_id, execution_view, metadata)
        self._target_id = target_id
        self._repository = task.repository
        self._org_id = task.org_id
        self._user_id = task.user_id
        self._snapshot = MemoryGraphSnapshot(
            MemoryKind.ORG_SEMANTIC,
            records,
            nodes=nodes,
            adjacency={},
            graph_hash=str(source["target_view_sha256"]),
            query_telemetry={"candidate_count_before_filter": len(candidate_ids)},
        )
        self._empty = {
            kind: MemoryGraphSnapshot(
                kind,
                {},
                graph_hash=hashlib.sha256(
                    f"{source['target_view_sha256']}:{kind.value}:empty".encode("utf-8")
                ).hexdigest(),
                query_telemetry={"candidate_count_before_filter": 0},
            )
            for kind in (MemoryKind.EPISODIC, MemoryKind.USER_SEMANTIC)
        }
        self.content_hash = _canonical_hash(
            {
                "target_view_sha256": source["target_view_sha256"],
                "candidate_memory_ids": list(candidate_ids),
                "execution_view_sha256": {
                    key: hashlib.sha256(value).hexdigest()
                    for key, value in sorted(self.execution_views.items())
                },
            }
        )

    def snapshot(
        self,
        kind: Any,
        *,
        user_id: str,
        org_id: str,
        repository: str,
    ) -> Any:
        from enterprise_memory.trimem.retrieval import MemoryKind

        selected = MemoryKind(kind)
        if (
            user_id != self._user_id
            or org_id != self._org_id
            or repository != self._repository
        ):
            raise DiagnosticExecutorError("source-bank query context drift")
        if selected == MemoryKind.ORG_SEMANTIC:
            return self._snapshot
        return self._empty[selected]


@dataclass(frozen=True)
class ManagedModelGateway:
    """One cell's model delegate and its mandatory resource closer."""

    gateway: Any
    close: Callable[[], None] = lambda: None


class _DiagnosticCapMapping(Mapping[str, Any]):
    """Expose runner compatibility aliases without changing approved bytes.

    ``dict(mapping)`` intentionally contains only the externally approved
    diagnostic fields.  The benchmark ledger can nevertheless query its two
    historical names through ``__getitem__`` while retaining the original cap
    document and its canonical hash in durable state.
    """

    _ALIASES = {
        "benchmark_grader_containers": "grader_containers",
        "max_model_calls_per_task_arm": "model_calls_per_task_arm",
    }

    def __init__(self, approved: Mapping[str, Any]) -> None:
        self._approved = MappingProxyType(_json_copy(approved))

    def __getitem__(self, key: str) -> Any:
        return self._approved[self._ALIASES.get(key, key)]

    def __iter__(self):
        return iter(self._approved)

    def __len__(self) -> int:
        return len(self._approved)


class DiagnosticAtomicBudgetLedger:
    """Diagnostic reconciliation facade over the frozen benchmark ledger."""

    def __init__(
        self,
        delegate: Any,
        *,
        approved_hard_caps: Mapping[str, Any],
    ) -> None:
        self.delegate = delegate
        self.approved_hard_caps = MappingProxyType(
            _json_copy(approved_hard_caps)
        )
        self.approved_hard_caps_sha256 = _canonical_hash(
            self.approved_hard_caps
        )
        if (
            getattr(delegate, "approved_hard_cap", None)
            != dict(self.approved_hard_caps)
        ):
            raise DiagnosticExecutorError(
                "ledger did not preserve the external diagnostic hard caps"
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    @staticmethod
    def _money(value: object, label: str) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise DiagnosticExecutorError(f"{label} is not valid money") from exc
        if not amount.is_finite() or amount < 0:
            raise DiagnosticExecutorError(f"{label} is not finite non-negative money")
        return amount

    def finalize_diagnostic(
        self,
        *,
        requests: Sequence[Mapping[str, Any]],
        cells: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Reconcile every terminal cell to the atomic request/task graph."""

        state = self.delegate._read()  # noqa: SLF001 - validated ledger snapshot
        if (
            state.get("approved_hard_cap") != dict(self.approved_hard_caps)
            or state.get("approved_hard_cap_sha256")
            != self.approved_hard_caps_sha256
        ):
            raise DiagnosticExecutorError("ledger approved hard-cap identity drift")
        if len(requests) != 36 or len(cells) != 36:
            raise DiagnosticExecutorError("ledger finalization requires exactly 36 cells")
        expected_task_keys = {
            str(request["cell_id"]): (
                f"{request['experiment_id']}:{request['runtime_arm']}:"
                f"{request['target_id']}"
            )
            for request in requests
        }
        if len(expected_task_keys) != 36 or len(set(expected_task_keys.values())) != 36:
            raise DiagnosticExecutorError("diagnostic task-arm keys are not unique")
        task_arms = state.get("task_arms")
        if not isinstance(task_arms, Mapping) or set(task_arms) != set(
            expected_task_keys.values()
        ):
            raise DiagnosticExecutorError("ledger task-arm set differs from 36 cells")
        import trimem_benchmark_run as benchmark

        for task_key, row in task_arms.items():
            if (
                not isinstance(row, Mapping)
                or row.get("status")
                != benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS
                or row.get("container_started") is not True
            ):
                raise DiagnosticExecutorError(
                    f"ledger task-arm is not terminal with a container: {task_key}"
                )
        outstanding = state.get("outstanding")
        if not isinstance(outstanding, Mapping) or any(
            self._money(value, f"outstanding {field}") != 0
            for field, value in outstanding.items()
        ):
            raise DiagnosticExecutorError("diagnostic ledger retains outstanding capacity")

        by_cell = {str(cell["cell_id"]): cell for cell in cells}
        if set(by_cell) != set(expected_task_keys):
            raise DiagnosticExecutorError("ledger result cell identities differ")
        role_field = {
            "decompose": "decomposition_calls",
            "solve": "solve_calls",
            "extract": "extraction_calls",
        }
        request_rows = state.get("requests")
        if not isinstance(request_rows, Mapping):
            raise DiagnosticExecutorError("ledger request inventory is malformed")
        requests_by_task: dict[str, list[Mapping[str, Any]]] = {
            key: [] for key in expected_task_keys.values()
        }
        for logical_id, row in request_rows.items():
            if not isinstance(logical_id, str) or not isinstance(row, Mapping):
                raise DiagnosticExecutorError("ledger request row is malformed")
            task_key = row.get("task_arm_key")
            if task_key not in requests_by_task or row.get("call_kind") not in role_field:
                raise DiagnosticExecutorError("ledger request task/role binding differs")
            if row.get("status") not in benchmark.SCIENTIFIC_MODEL_RESERVATION_TERMINAL_STATUSES:
                raise DiagnosticExecutorError("ledger contains a non-terminal model request")
            requests_by_task[str(task_key)].append(row)

        total_projection = {
            "paid_model_calls": 0,
            "solve_calls": 0,
            "decomposition_calls": 0,
            "extraction_calls": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "task_arm_runs": 36,
            "grader_containers": 36,
        }
        total_usd = Decimal(0)
        for cell_id, task_key in expected_task_keys.items():
            accounting = by_cell[cell_id]["accounting"]
            rows = requests_by_task[task_key]
            role_counts = {
                field: sum(row.get("call_kind") == kind for row in rows)
                for kind, field in role_field.items()
            }
            for field, count in role_counts.items():
                if accounting[field] != count:
                    raise DiagnosticExecutorError(
                        f"ledger/cell {field} differs: {cell_id}"
                    )
            row_paid = len(rows)
            row_input = sum(int(row["input_tokens"]) for row in rows)
            row_cached = sum(int(row["cached_input_tokens"]) for row in rows)
            row_output = sum(int(row["output_tokens"]) for row in rows)
            row_usd = sum(
                (self._money(row["actual_usd"], "request actual_usd") for row in rows),
                Decimal(0),
            )
            if (
                accounting["paid_model_calls"] != row_paid
                or accounting["input_tokens"] != row_input
                or accounting["cached_input_tokens"] != row_cached
                or accounting["output_tokens"] != row_output
                or abs(
                    self._money(accounting["total_usd"], "cell total_usd")
                    - row_usd
                )
                > Decimal("0.000000000001")
            ):
                raise DiagnosticExecutorError(
                    f"ledger/cell token, call, or USD totals differ: {cell_id}"
                )
            for field in (
                "paid_model_calls",
                "solve_calls",
                "decomposition_calls",
                "extraction_calls",
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
            ):
                total_projection[field] += int(accounting[field])
            total_usd += self._money(accounting["total_usd"], "cell total_usd")

        actual = state.get("actual")
        if not isinstance(actual, Mapping):
            raise DiagnosticExecutorError("ledger actual totals are malformed")
        for field, expected in total_projection.items():
            if actual.get(field) != expected:
                raise DiagnosticExecutorError(
                    f"ledger actual {field} differs from 36 cells"
                )
        if abs(self._money(actual.get("total_usd"), "ledger total_usd") - total_usd) > Decimal(
            "0.000000000001"
        ):
            raise DiagnosticExecutorError("ledger actual total_usd differs from 36 cells")
        if actual.get("grader_containers") != 36:
            raise DiagnosticExecutorError("ledger does not contain exactly 36 graders")
        return {
            "schema": "trimem/dev-activation-ledger-finalization/1.0",
            "status": "PASS_EXACT_36_TERMINAL_RECONCILED",
            "approved_hard_caps_sha256": self.approved_hard_caps_sha256,
            "task_arm_count": 36,
            "request_count": len(request_rows),
            "actual": _json_copy(actual),
            "outstanding": _json_copy(outstanding),
            "task_arm_keys_sha256": _canonical_hash(sorted(task_arms)),
        }


def _atomic_write_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _evidence_reference(root: Path, path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise DiagnosticExecutorError("cell evidence escapes its journal root") from exc
    return {
        "path": relative,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def _adaptive_horizon_projection(
    state: object,
    *,
    agent_completed: bool,
    per_subtask_cap_reached: bool,
) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        if agent_completed or per_subtask_cap_reached:
            raise DiagnosticExecutorError(
                "terminal adaptive-horizon evidence is missing"
            )
        # A decomposition/preflight failure occurs before any subtask horizon
        # exists.  Preserve that truthful empty state instead of turning the
        # contained coding failure into an infrastructure stop.
        return {
            "extensions_granted": 0,
            "progress_event_ids": [],
            "per_subtask_extensions": {},
            "agent_completed_count": 0,
            "per_subtask_step_cap_reached_count": 0,
        }
    extensions = state.get("extension_events")
    progress = state.get("progress_events")
    nodes = state.get("nodes")
    if not isinstance(extensions, list) or not isinstance(progress, list) or not isinstance(nodes, Mapping):
        raise DiagnosticExecutorError("terminal adaptive-horizon evidence is malformed")
    event_ids: list[str] = []
    for extension in extensions:
        if not isinstance(extension, Mapping):
            raise DiagnosticExecutorError("adaptive extension evidence is malformed")
        ordinal = extension.get("trigger_progress_ordinal")
        if type(ordinal) is not int or ordinal < 1 or ordinal > len(progress):
            raise DiagnosticExecutorError("adaptive extension trigger is missing")
        trigger = progress[ordinal - 1]
        event_ids.append(
            hashlib.sha256(
                diagnostic.canonical_bytes(
                    {"extension": extension, "trigger_progress": trigger}
                )
            ).hexdigest()
        )
    if len(event_ids) != len(set(event_ids)):
        raise DiagnosticExecutorError("adaptive extension evidence is duplicated")
    per_subtask: dict[str, int] = {}
    for node_id, row in sorted(nodes.items()):
        if not isinstance(node_id, str) or not isinstance(row, Mapping):
            raise DiagnosticExecutorError("adaptive per-subtask evidence is malformed")
        count = row.get("extension_count")
        if type(count) is not int or count < 0:
            raise DiagnosticExecutorError("adaptive extension count is malformed")
        per_subtask[node_id] = count
    return {
        "extensions_granted": len(extensions),
        "progress_event_ids": event_ids,
        "per_subtask_extensions": per_subtask,
        "agent_completed_count": int(agent_completed),
        "per_subtask_step_cap_reached_count": int(per_subtask_cap_reached),
    }


def _terminal_reason_and_failure(result: Any) -> tuple[str, Optional[str]]:
    failure = getattr(result, "model_failure_class", None)
    if failure == "per-subtask step cap reached":
        return "PER_SUBTASK_STEP_CAP_REACHED", None
    extraction_failed = (
        getattr(result, "extraction_status", "SUCCESS")
        == "MEMORY_EXTRACTION_FAILED"
    )
    if (
        extraction_failed
        and getattr(result, "cell_status", None) == "MEMORY_EXTRACTION_FAILED"
        and getattr(result, "agent_completed", False) is True
    ):
        return "EXTRACTION_FAILURE_AFTER_OFFICIAL_GRADE", None
    if failure is not None:
        return "MODEL_FAILURE_CONTINUED_TO_GRADER", str(failure)
    if getattr(result, "agent_completed", False) is True:
        return "AGENT_COMPLETED", None
    return "CONTAINED_RUNTIME_FAILURE_CONTINUED_TO_GRADER", str(
        getattr(result, "cell_status", "CONTAINED_RUNTIME_FAILURE")
    )


def _patch_class(result: Any) -> str:
    return {
        "MODEL_PATCH": "MODEL_PATCH",
        "MODEL_PARTIAL_PATCH": "PARTIAL_PATCH",
        "CANONICAL_FAILED_CELL_NOOP": "CANONICAL_NOOP",
    }.get(str(getattr(result, "grader_patch_source", "")), "")


def _facet_overlap(source: object, target: object) -> list[str]:
    if not isinstance(source, list) or not isinstance(target, (list, tuple)):
        return []
    target_values = {str(value).casefold() for value in target}
    return sorted(
        value for value in source
        if isinstance(value, str) and value.casefold() in target_values
    )


class OfficialProductionCellExecutor:
    """Concrete one-cell runtime/official-grader backend.

    Production construction supplies the same paid gateway, official grader,
    Git checkout and atomic ledger primitives as ``trimem_benchmark_run``.
    The credential-free mode exists solely to exercise this composition with
    deterministic fakes; it cannot advertise production capabilities.
    """

    def __init__(
        self,
        *,
        contract: ExecutionContract,
        runtime_lock: Any,
        tasks_by_target_id: Mapping[str, Any],
        repository_root: Path,
        workspace_factory: Callable[[Mapping[str, Any], Any, Path, bool], tuple[Any, Mapping[str, Any]]],
        model_gateway_factory: Callable[[Mapping[str, Any], Any, Path], ManagedModelGateway],
        grader_gateway_factory: Callable[[Mapping[str, Any], Any, Path], Any],
        retrieval_config: Any,
        embedder_factory: Callable[[], Any],
        pricing: Mapping[str, Any],
        model_config_hash: str,
        grader_config_hash: Callable[[Mapping[str, Any]], str],
        expected_image_digest: Callable[[Mapping[str, Any]], Optional[str]],
        ledger: Any = None,
        payload_bytes: Optional[Mapping[str, bytes]] = None,
        official_grader_preflight: Optional[Mapping[str, Any]] = None,
        embedder_preflight_sha256: Optional[str] = None,
        retrieval_rehearsal_sha256: Optional[str] = None,
        image_reinspection_sha256: Optional[str] = None,
        solver_sandbox_rehearsal_sha256: Optional[str] = None,
        workspace_root: Optional[Path] = None,
        credential_free_test_mode: bool = False,
    ) -> None:
        self.contract = contract
        self.runtime_lock = runtime_lock
        self.tasks = dict(tasks_by_target_id)
        self.repository_root = repository_root.resolve()
        self.workspace_factory = workspace_factory
        self.model_gateway_factory = model_gateway_factory
        self.grader_gateway_factory = grader_gateway_factory
        self.retrieval_config = retrieval_config
        self.embedder_factory = embedder_factory
        self.pricing = dict(pricing)
        self.model_config_hash = _require_sha256(model_config_hash, "model config hash")
        self.grader_config_hash = grader_config_hash
        self.expected_image_digest = expected_image_digest
        self.ledger = ledger
        self.payload_bytes = dict(payload_bytes) if payload_bytes is not None else None
        self.official_grader_preflight = (
            dict(official_grader_preflight)
            if official_grader_preflight is not None else None
        )
        self.embedder_preflight_sha256 = (
            _require_sha256(embedder_preflight_sha256, "embedder preflight hash")
            if embedder_preflight_sha256 is not None
            else None
        )
        self.retrieval_rehearsal_sha256 = (
            _require_sha256(
                retrieval_rehearsal_sha256, "retrieval rehearsal hash"
            )
            if retrieval_rehearsal_sha256 is not None
            else None
        )
        self.image_reinspection_sha256 = (
            _require_sha256(image_reinspection_sha256, "image reinspection hash")
            if image_reinspection_sha256 is not None
            else None
        )
        self.solver_sandbox_rehearsal_sha256 = (
            _require_sha256(
                solver_sandbox_rehearsal_sha256,
                "solver sandbox rehearsal hash",
            )
            if solver_sandbox_rehearsal_sha256 is not None
            else None
        )
        self.workspace_root = workspace_root.resolve() if workspace_root else None
        self.credential_free_test_mode = bool(credential_free_test_mode)
        self.executed_cells: list[str] = []
        _validate_contract_object(contract)
        if set(self.tasks) != {
            str(target["target_id"]) for target in contract.manifest["targets"]
        }:
            raise DiagnosticExecutorError("production task set differs from frozen DEV")
        adaptive = getattr(runtime_lock, "adaptive_horizon", None)
        limits = getattr(runtime_lock, "limits", None)
        if (
            getattr(adaptive, "enabled", None) is not True
            or getattr(adaptive, "extension_steps", None) != 4
            or getattr(adaptive, "maximum_steps_per_subtask", None) != 16
            or getattr(adaptive, "maximum_extensions_per_subtask", None) != 2
            or getattr(limits, "max_steps_per_subtask", None) != 8
            or getattr(limits, "max_solve_calls", None) != 24
            or getattr(limits, "max_agent_steps", None) != 24
        ):
            raise DiagnosticExecutorError("runtime lock does not implement the frozen adaptive horizon")
        if not self.credential_free_test_mode and ledger is None:
            raise DiagnosticExecutorError("production executor requires the atomic budget ledger")
        if not self.credential_free_test_mode and self.embedder_preflight_sha256 is None:
            raise DiagnosticExecutorError("production executor requires embedder preflight evidence")
        if (
            not self.credential_free_test_mode
            and self.retrieval_rehearsal_sha256 is None
        ):
            raise DiagnosticExecutorError(
                "production executor requires retrieval rehearsal evidence"
            )
        if not self.credential_free_test_mode and self.image_reinspection_sha256 is None:
            raise DiagnosticExecutorError("production executor requires live image evidence")
        if (
            not self.credential_free_test_mode
            and self.solver_sandbox_rehearsal_sha256 is None
        ):
            raise DiagnosticExecutorError(
                "production executor requires solver sandbox rehearsal evidence"
            )
        if not self.credential_free_test_mode:
            protocol = contract.policy.get("development_protocol_binding", {})
            if (
                getattr(runtime_lock, "content_hash", None)
                != protocol.get("adaptive_runtime_lock_sha256")
            ):
                raise DiagnosticExecutorError(
                    "production runtime is not the frozen adaptive recall lock"
                )
            selected = contract.policy.get("frozen_inputs", {}).get(
                "selected_recall_policy", {}
            )
            selected_path = self.repository_root / str(selected.get("path", ""))
            if (
                not selected_path.is_file()
                or diagnostic.file_sha256(selected_path)
                != selected.get("raw_sha256")
            ):
                raise DiagnosticExecutorError("selected recall policy binding differs")
            selected_document = diagnostic.strict_json_load(selected_path)
            expected_retrieval = selected_document.get("retrieval")
            actual_retrieval = {
                "min_confidence": retrieval_config.min_confidence,
                "min_margin": retrieval_config.min_margin,
                "episode_complete_threshold": (
                    retrieval_config.episode_complete_threshold
                ),
                "max_episodic_per_active_node": (
                    retrieval_config.max_episodic_per_node
                ),
                "max_semantic_per_active_node": (
                    retrieval_config.max_semantic_per_node
                ),
                "max_task_injections": retrieval_config.max_task_injections,
                "context_budget_bytes": retrieval_config.context_budget_bytes,
                "embedding_dimensions": retrieval_config.embedding_dimensions,
                "embedding_weight": retrieval_config.embedding_weight,
                "lexical_weight": retrieval_config.lexical_weight,
                "ppr_damping": retrieval_config.ppr_damping,
                "ppr_iterations": retrieval_config.ppr_iterations,
            }
            if not isinstance(expected_retrieval, Mapping) or any(
                expected_retrieval.get(key) != value
                for key, value in actual_retrieval.items()
            ):
                raise DiagnosticExecutorError(
                    "production retrieval is not the selected recall policy"
                )

    def capabilities(self) -> Mapping[str, Any]:
        if self.credential_free_test_mode:
            return {
                "schema": CAPABILITY_SCHEMA,
                "executor_id": "credential-free-production-wiring-fixture-v1",
                "executor_kind": "CREDENTIAL_FREE_TEST_DOUBLE",
                "one_cell_per_invocation": True,
                "durable_resume": True,
                "fresh_namespace_per_cell": True,
                "read_only_source_bank": True,
                "contained_failure_to_official_grader": True,
                "official_grader_required": True,
                "reused_benchmark_primitives": [],
            }
        return production_capabilities("trimem-dev-activation-official-cell-v1")

    def finalize_matrix(
        self,
        *,
        requests: Sequence[Mapping[str, Any]],
        cells: Sequence[Mapping[str, Any]],
        output_root: Path,
        resume: bool,
    ) -> Mapping[str, Any]:
        if self.credential_free_test_mode:
            raise DiagnosticExecutorError(
                "credential-free fixture cannot finalize a production ledger"
            )
        if not isinstance(self.ledger, DiagnosticAtomicBudgetLedger):
            raise DiagnosticExecutorError(
                "production diagnostic ledger facade is absent"
            )
        report = self.ledger.finalize_diagnostic(
            requests=requests, cells=cells
        )
        report["embedder_preflight_sha256"] = self.embedder_preflight_sha256
        report["retrieval_rehearsal_sha256"] = (
            self.retrieval_rehearsal_sha256
        )
        report["image_reinspection_sha256"] = self.image_reinspection_sha256
        report["solver_sandbox_rehearsal_sha256"] = (
            self.solver_sandbox_rehearsal_sha256
        )
        path = output_root / "control" / "ledger-finalization.json"
        if path.exists():
            if not resume:
                raise DiagnosticExecutorError(
                    "ledger finalization exists without --resume"
                )
            if diagnostic.canonical_bytes(
                _read_exact_json(path, "ledger finalization")
            ) != diagnostic.canonical_bytes(report):
                raise DiagnosticExecutorError(
                    "ledger finalization resume evidence drift"
                )
        else:
            _atomic_write_json(path, report)
        return MappingProxyType(
            {
                "report": report,
                "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    def _memory_controller(
        self,
        request: Mapping[str, Any],
        task: Any,
    ) -> tuple[Any, Optional[ManifestBackedDiagnosticSourceBankStore]]:
        from enterprise_memory.trimem.agent_runtime import NoMemoryController
        from enterprise_memory.trimem.arms import ActiveNodeTriMemController
        from enterprise_memory.trimem.retrieval import TriMemoryRetriever

        if request["arm_id"] == "C0":
            return NoMemoryController(), None
        source_store = ManifestBackedDiagnosticSourceBankStore(
            contract=self.contract,
            request=request,
            task=task,
            repository_root=self.repository_root,
            payload_bytes=self.payload_bytes,
        )
        retriever = TriMemoryRetriever(
            source_store,
            self.retrieval_config,
            embedder=self.embedder_factory(),
            selection_mode=request["retrieval"]["selection_mode"],
            diagnostic_telemetry=True,
            require_safe_pool_metadata=True,
        )
        return ActiveNodeTriMemController(retriever, task_id=task.task_id), source_store

    @staticmethod
    def _verified_recall_rows(evidence: Any, checkpoint: Any, target_id: str) -> list[dict[str, Any]]:
        event_rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for event in evidence.verified_suffix("0" * 64):
            if event.get("event_type") != "memory_recall":
                continue
            payload = event.get("payload")
            rows = (
                payload.get("decision_telemetry", [])
                if isinstance(payload, Mapping)
                else None
            )
            if not isinstance(rows, list):
                raise DiagnosticExecutorError("memory_recall telemetry is malformed")
            for raw in rows:
                if not isinstance(raw, Mapping):
                    raise DiagnosticExecutorError("memory_recall telemetry row is malformed")
                row = _json_copy(raw)
                diagnostic.validate_recall_decision(row, target_id)
                attempt = str(row["recall_attempt_id"])
                if attempt in seen:
                    raise DiagnosticExecutorError("recall telemetry was persisted more than once")
                seen.add(attempt)
                event_rows.append(row)
        terminal = checkpoint.terminal_payload.get("recall_decisions", [])
        if not isinstance(terminal, list):
            raise DiagnosticExecutorError("terminal recall telemetry is malformed")
        terminal_rows = [_json_copy(row) for row in terminal]
        if diagnostic.canonical_bytes(event_rows) != diagnostic.canonical_bytes(terminal_rows):
            raise DiagnosticExecutorError("raw and checkpoint recall telemetry differ")
        return event_rows

    def _injection_rows(
        self,
        result: Any,
        source_store: Optional[ManifestBackedDiagnosticSourceBankStore],
        evidence: Any,
        target_id: str,
        target_repository: str,
    ) -> list[dict[str, Any]]:
        if source_store is None:
            if result.injections:
                raise DiagnosticExecutorError("C0 runtime injected memory")
            return []
        nodes = {
            str(row.get("node_id")): row
            for row in result.graph_snapshot.get("nodes", ())
            if isinstance(row, Mapping)
        }
        rows: list[dict[str, Any]] = []
        for injection in result.injections:
            if not isinstance(injection, Mapping):
                raise DiagnosticExecutorError("runtime injection ledger is malformed")
            memory_id = str(injection.get("memory_id", ""))
            if memory_id not in source_store.execution_views:
                raise DiagnosticExecutorError("runtime injected a non-assigned memory")
            exact = str(injection.get("exact_text", "")).encode("utf-8")
            if (
                exact != source_store.execution_views[memory_id]
                or hashlib.sha256(exact).hexdigest() != injection.get("sha256")
                or not (evidence.blob_dir / str(injection.get("sha256"))).is_file()
                or (evidence.blob_dir / str(injection.get("sha256"))).read_bytes() != exact
            ):
                raise DiagnosticExecutorError("exact injected memory bytes lack raw evidence")
            node_id = str(injection.get("active_node_id", ""))
            node = nodes.get(node_id)
            if not isinstance(node, Mapping):
                raise DiagnosticExecutorError("injection active subtask is absent from the DAG")
            record = self.contract.records_by_memory_id[memory_id]
            assignment = self.contract.assignments_by_target[target_id]
            assigned = next(
                (
                    row for row in assignment["candidates"]
                    if row.get("memory_id") == memory_id
                ),
                None,
            )
            if not isinstance(assigned, Mapping) or not isinstance(
                assigned.get("score"), Mapping
            ):
                raise DiagnosticExecutorError(
                    "injected memory lacks its frozen target assignment score"
                )
            active_projection = {
                "node_id": node_id,
                "files": list(node.get("files", ())),
                "symbols": list(node.get("symbols", ())),
                "apis": list(node.get("apis", ())),
                "errors": list(node.get("errors", ())),
            }
            rows.append(
                {
                    "memory_id": memory_id,
                    "source_task_id": record["source_task_id"],
                    "source_repository": record["source_repository"],
                    "target_repository": target_repository,
                    "bank_type": "ORG_SEMANTIC",
                    "subtask_id": node_id,
                    "repo_overlap": record["source_repository"] == target_repository,
                    "active_subtask_projection_sha256": _canonical_hash(
                        active_projection
                    ),
                    "active_subtask_declared_file_overlap": _facet_overlap(
                        record["changed_paths"], node.get("files")
                    ),
                    "active_subtask_declared_symbol_overlap": _facet_overlap(
                        record["symbols"], node.get("symbols")
                    ),
                    "active_subtask_declared_api_overlap": _facet_overlap(
                        record["apis"], node.get("apis")
                    ),
                    "active_subtask_declared_error_overlap": _facet_overlap(
                        record["errors"], node.get("errors")
                    ),
                    "pre_execution_target_issue_overlap": _json_copy(
                        assigned["score"]
                    ),
                }
            )
        return rows

    @staticmethod
    def _extraction_failure_code(result: Any, evidence: Any) -> Optional[str]:
        status = str(getattr(result, "extraction_status", "SUCCESS"))
        if status == "SUCCESS":
            return None
        if status != "MEMORY_EXTRACTION_FAILED":
            raise DiagnosticExecutorError("runtime returned an unknown extraction status")
        failures: list[str] = []
        for event in evidence.verified_suffix("0" * 64):
            if event.get("event_type") != "memory_extraction_failed":
                continue
            payload = event.get("payload")
            code = payload.get("failure_class") if isinstance(payload, Mapping) else None
            if not isinstance(code, str) or not code:
                raise DiagnosticExecutorError("extraction failure evidence has no class")
            failures.append(code)
        if not failures:
            raise DiagnosticExecutorError("extraction failed without raw failure evidence")
        if len(set(failures)) != 1:
            raise DiagnosticExecutorError("extraction failure evidence is inconsistent")
        return failures[0]

    def _cell_from_result(
        self,
        *,
        request: Mapping[str, Any],
        result: Any,
        evidence: Any,
        checkpoint: Any,
        source_store: Optional[ManifestBackedDiagnosticSourceBankStore],
        journal_root: Path,
        task_wall_time_ms: int,
        checkout_evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        import trimem_benchmark_run as benchmark

        if (
            result.grade.official is not True
            or result.grade.container_started is not True
            or type(result.grade.resolved) is not bool
        ):
            raise DiagnosticExecutorError("grader did not return an authoritative official cell")
        if checkpoint.state != "DONE" or checkpoint.evidence_event_hash != result.evidence_tail_hash:
            raise DiagnosticExecutorError("runtime did not return an evidence-bound DONE checkpoint")
        extraction_status = str(getattr(result, "extraction_status", "SUCCESS"))
        extraction_failure = self._extraction_failure_code(result, evidence)
        successful_lifecycle = {
            "storage": {
                "storage_action": "NONE",
                "retained_records": 0,
                "archived_records": 0,
                "net_memory_growth": 0,
            },
            "credit": {"credited": 0},
        }
        failed_extraction_lifecycle = {
            "storage": {
                "storage_action": "NONE",
                "reason": "MEMORY_EXTRACTION_FAILED",
            },
            "credit": {"credited": 0, "reason": "MEMORY_EXTRACTION_FAILED"},
        }
        expected_lifecycle = (
            successful_lifecycle
            if extraction_status == "SUCCESS"
            else failed_extraction_lifecycle
        )
        if result.lifecycle_result != expected_lifecycle:
            raise DiagnosticExecutorError("diagnostic runtime attempted a lifecycle bank write")

        stdout_path = journal_root / "stdout.txt"
        stderr_path = journal_root / "stderr.txt"
        report_path = journal_root / "report.json"
        checkout_path = journal_root / "checkout-evidence.json"
        _atomic_write_bytes(stdout_path, result.grade.stdout.encode("utf-8"))
        _atomic_write_bytes(stderr_path, result.grade.stderr.encode("utf-8"))
        _atomic_write_json(report_path, result.grade.report)
        _atomic_write_json(checkout_path, checkout_evidence)
        events_path = evidence.events_path
        checkpoint_path = journal_root / "agent-checkpoints" / f"{result.run_id}.json"
        evidence.verify()
        references = {
            "stdout": _evidence_reference(journal_root, stdout_path),
            "stderr": _evidence_reference(journal_root, stderr_path),
            "report": _evidence_reference(journal_root, report_path),
            "raw_events": _evidence_reference(journal_root, events_path),
            "terminal_checkpoint": _evidence_reference(journal_root, checkpoint_path),
            "checkout": _evidence_reference(journal_root, checkout_path),
        }
        expected_digest = self.expected_image_digest(request)
        if not self.credential_free_test_mode:
            observed = benchmark.observed_target_digest(result.grade)
            if not isinstance(expected_digest, str) or observed != expected_digest:
                raise DiagnosticExecutorError("official grader image digest binding differs")
        evidence_document = {
            "schema": PRODUCTION_CELL_EVIDENCE_SCHEMA,
            "cell_id": request["cell_id"],
            "run_id": result.run_id,
            "official": True,
            "container_started": True,
            "grader_id": result.grade.grader_id,
            "container_digest": result.grade.container_digest,
            "expected_image_digest": expected_digest,
            "embedder_preflight_sha256": self.embedder_preflight_sha256,
            "retrieval_rehearsal_sha256": self.retrieval_rehearsal_sha256,
            "image_reinspection_sha256": self.image_reinspection_sha256,
            "solver_sandbox_rehearsal_sha256": (
                self.solver_sandbox_rehearsal_sha256
            ),
            "references": references,
        }
        evidence_path = journal_root / "official-grader-evidence.json"
        _atomic_write_json(evidence_path, evidence_document)
        reason, failure = _terminal_reason_and_failure(result)
        accounting = benchmark.actual_accounting(
            result.accounting, task_wall_time_ms=task_wall_time_ms
        )
        if (
            accounting["grader_calls"] != 1
            or accounting["grader_containers"] != 1
            or accounting["official_grader_runs"] != 1
        ):
            raise DiagnosticExecutorError("runtime accounting lacks one official grader lifecycle")
        cell_accounting = {
            field: accounting[field]
            for field in (
                "decomposition_calls",
                "solve_calls",
                "extraction_calls",
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "paid_model_calls",
                "model_wall_time_ms",
                "tool_wall_time_ms",
                "grader_wall_time_ms",
                "grader_calls",
                "grader_containers",
                "official_grader_runs",
                "task_wall_time_ms",
            )
        }
        cell_accounting["total_usd"] = benchmark.actual_usd_for_accounting(
            accounting, self.pricing
        )
        recall_rows = self._verified_recall_rows(
            evidence, checkpoint, str(request["target_id"])
        )
        if request["arm_id"] == "C0" and recall_rows:
            raise DiagnosticExecutorError("C0 produced diagnostic recall telemetry")
        horizon_state = checkpoint.terminal_payload.get("adaptive_horizon")
        cell = {
            "schema": "trimem/dev-activation-cell/1.0",
            "diagnostic_id": request["diagnostic_id"],
            "cell_id": request["cell_id"],
            "cell_index": request["cell_index"],
            "arm_id": request["arm_id"],
            "target_id": request["target_id"],
            "target_order_index": request["target_order_index"],
            "source_bank_manifest_sha256": (
                None
                if request["source_bank"] is None
                else request["source_bank"]["manifest_raw_sha256"]
            ),
            "official_grader_evidence_sha256": hashlib.sha256(
                evidence_path.read_bytes()
            ).hexdigest(),
            "terminal": True,
            "terminal_reason_code": reason,
            "official_grader_resolved": result.grade.resolved,
            "diagnostic_resolved": bool(
                result.grade.resolved
                and failure is None
                and extraction_status == "SUCCESS"
            ),
            "patch_class": _patch_class(result),
            "model_failure_code": failure,
            "extraction_status": extraction_status,
            "extraction_failure_code": extraction_failure,
            "injections": self._injection_rows(
                result,
                source_store,
                evidence,
                str(request["target_id"]),
                str(request["target"]["repository"]),
            ),
            "recall_decisions": recall_rows,
            "adaptive_horizon": _adaptive_horizon_projection(
                horizon_state,
                agent_completed=result.agent_completed,
                per_subtask_cap_reached=(
                    result.model_failure_class == "per-subtask step cap reached"
                ),
            ),
            "accounting": cell_accounting,
        }
        if not cell["patch_class"]:
            raise DiagnosticExecutorError("runtime grader patch source is unknown")
        return cell

    def execute_cell(
        self,
        request: Mapping[str, Any],
        *,
        resume: bool,
        journal_root: Path,
    ) -> Mapping[str, Any]:
        from enterprise_memory.trimem.accounting import RawEvidenceLedger
        from enterprise_memory.trimem.agent_runtime import (
            NullExperienceLifecycle,
            TriMemAgentRuntime,
        )
        from enterprise_memory.trimem.checkpoint import FileCheckpointStore
        import trimem_benchmark_run as benchmark

        _validate_contract_object(self.contract)
        requests = build_cell_requests(
            self.contract,
            execution_identity_sha256=str(request["execution_identity_sha256"]),
        )
        index = int(request.get("cell_index", -1))
        if index < 0 or index >= len(requests) or diagnostic.canonical_bytes(
            _plain_json(request)
        ) != diagnostic.canonical_bytes(_plain_json(requests[index])):
            raise DiagnosticExecutorError("production backend request differs from frozen plan")
        task = self.tasks[str(request["target_id"])]
        if (
            task.task_id != request["target_id"]
            or task.repository != request["target"]["repository"]
            or task.commit != request["target"]["base_commit"]
        ):
            raise DiagnosticExecutorError("production task differs from cell target")
        started = time.perf_counter_ns()
        journal_root.mkdir(parents=True, exist_ok=True)
        backend_result_path = journal_root / "production-cell-result.json"
        task_arm_key = f"{request['experiment_id']}:{request['runtime_arm']}:{task.task_id}"
        task_reservation: Optional[str] = None
        if self.ledger is not None:
            status = self.ledger.task_arm_status(task_arm_key)
            if status is None:
                task_reservation = self.ledger.reserve_task_arm(task_arm_key)
            elif resume and status == "RESERVED":
                task_reservation = self.ledger.resume_task_arm(task_arm_key)
            elif resume and status == benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS:
                task_reservation = str(self.ledger.task_arm_row(task_arm_key)["reservation_id"])
            else:
                raise DiagnosticExecutorError("cell atomic-budget reservation state differs")

        if backend_result_path.exists():
            if not resume:
                raise DiagnosticExecutorError("production cell result exists without resume")
            cell = _read_exact_json(backend_result_path, "production cell result")
            _validate_cell_result(
                cell,
                request,
                source_bank_sha256=self.contract.source_bank_manifest_sha256,
            )
            if self.ledger is not None:
                status = self.ledger.task_arm_status(task_arm_key)
                if status == "RESERVED":
                    assert task_reservation is not None
                    self.ledger.complete_task_arm(
                        task_arm_key,
                        task_reservation,
                        status=benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                        container_started=True,
                    )
                elif status != benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS:
                    raise DiagnosticExecutorError("terminal cell ledger state differs")
            return cell

        workspace_path = (
            self.workspace_root
            / f"{int(request['cell_index']):02d}-{_safe_workspace_name(task.task_id)}"
            if self.workspace_root is not None
            else journal_root / "workspace"
        )
        workspace_factory, checkout_evidence = self.workspace_factory(
            request, task, workspace_path, resume
        )
        if (
            not self.credential_free_test_mode
            and getattr(workspace_factory, "production_capable", None) is not True
        ):
            raise DiagnosticExecutorError("production cell has no production-capable workspace")
        journal = benchmark.TerminalInvocationJournal(journal_root / "terminal-journal")
        managed_model = self.model_gateway_factory(
            request, task, journal_root / "restricted-provider-responses"
        )
        model_gateway = benchmark.JournaledModelGateway(managed_model.gateway, journal)
        grader_delegate = self.grader_gateway_factory(
            request, task, journal_root / "official-grader"
        )
        if self.credential_free_test_mode:
            grader_gateway = grader_delegate
        else:
            preflight = self.official_grader_preflight
            if not isinstance(preflight, Mapping):
                raise DiagnosticExecutorError("official grader preflight evidence is absent")
            grader_gateway = benchmark.JournaledGraderGateway(
                grader_delegate,
                journal,
                preflight_evidence=preflight,
                python_binary=str(preflight["python_loader"]["python_binary"]),
            )
        memory_controller, source_store = self._memory_controller(request, task)
        evidence = RawEvidenceLedger(journal_root / "evidence")
        checkpoints = FileCheckpointStore(journal_root / "agent-checkpoints")
        runtime = TriMemAgentRuntime(
            runtime_lock=self.runtime_lock,
            model_gateway=model_gateway,
            grader_gateway=grader_gateway,
            memory_controller=memory_controller,
            evidence=evidence,
            checkpoint_store=checkpoints,
            lifecycle=NullExperienceLifecycle(),
            workspace_factory=workspace_factory,
            model_config_hash=self.model_config_hash,
            grader_config_hash=_require_sha256(
                self.grader_config_hash(request), "grader config hash"
            ),
        )
        run_id = str(request["experiment_id"])
        checkpoint_path = journal_root / "agent-checkpoints" / f"{run_id}.json"
        try:
            result = runtime.run(
                task,
                arm=str(request["runtime_arm"]),
                run_id=run_id,
                resume=checkpoint_path.is_file(),
            )
        finally:
            managed_model.close()
        task_wall_time_ms = max(0, (time.perf_counter_ns() - started) // 1_000_000)
        checkpoint = checkpoints.load(
            run_id,
            required_config_hashes=None,
            required_evidence_hash=result.evidence_tail_hash,
        )
        cell = self._cell_from_result(
            request=request,
            result=result,
            evidence=evidence,
            checkpoint=checkpoint,
            source_store=source_store,
            journal_root=journal_root,
            task_wall_time_ms=task_wall_time_ms,
            checkout_evidence=checkout_evidence,
        )
        _validate_cell_result(
            cell,
            request,
            source_bank_sha256=self.contract.source_bank_manifest_sha256,
        )
        _atomic_write_json(backend_result_path, cell)
        if self.ledger is not None:
            assert task_reservation is not None
            self.ledger.complete_task_arm(
                task_arm_key,
                task_reservation,
                status=benchmark.SCIENTIFIC_LEDGER_TERMINAL_STATUS,
                container_started=True,
            )
        self.executed_cells.append(str(request["cell_id"]))
        return cell


class _StandaloneProviderSession:
    """One-cell owner for the async provider bridge used by the benchmark."""

    def __init__(self, name: str) -> None:
        from enterprise_memory.trimem.production_runtime import DedicatedAsyncLoop

        self._loop = DedicatedAsyncLoop(name=name)
        self._closed = False

    def run_coroutine(self, awaitable: Any) -> Any:
        if self._closed:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            raise DiagnosticExecutorError("one-cell provider session is closed")
        return self._loop.call(awaitable)

    @property
    def coroutine_runner(self) -> Callable[[Any], Any]:
        return self.run_coroutine

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._loop.close()


def _safe_workspace_name(value: object) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(value))
    if not safe or safe in {".", ".."}:
        raise DiagnosticExecutorError("task workspace identity is unsafe")
    return safe


def _require_repository_subpath(root: Path, path: Path, label: str) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise DiagnosticExecutorError(f"{label} must stay inside the repository")
    if path.is_symlink():
        raise DiagnosticExecutorError(f"{label} cannot be a symbolic link")
    return resolved


def load_and_validate_materialized_approval(
    *,
    contract: ExecutionContract,
    approval_path: Path,
    repository: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    workflow_event: str,
    now: Optional[datetime] = None,
    verify_openai_credential: bool = False,
) -> tuple[dict[str, Any], str]:
    """Revalidate gate material at the production boundary without a secret."""

    import trimem_dev_activation_gate as gate

    if approval_path.is_symlink():
        raise DiagnosticExecutorError("materialized approval cannot be a symbolic link")
    try:
        raw = approval_path.read_bytes()
        document = diagnostic.strict_json_load(approval_path)
    except (OSError, diagnostic.DiagnosticContractError) as exc:
        raise DiagnosticExecutorError(f"materialized approval is unreadable: {exc}") from exc
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise DiagnosticExecutorError("materialized approval contains BOM/NUL bytes")
    if raw != gate.canonical_approval_bytes(document):
        raise DiagnosticExecutorError("materialized approval bytes are not canonical")
    approval = gate.validate_approval_document(
        document,
        now=now or datetime.now(timezone.utc),
        diagnostic_id=str(contract.manifest["diagnostic_id"]),
        repository=repository,
        git_head=gate._git_head(ROOT),  # noqa: SLF001 - exact shared gate primitive
        workflow_run_id=workflow_run_id,
        workflow_run_attempt=workflow_run_attempt,
        workflow_event=workflow_event,
        matrix_raw_sha256=contract.matrix_raw_sha256,
        policy_raw_sha256=contract.policy_raw_sha256,
        source_bank_manifest_sha256=contract.source_bank_manifest_sha256,
        model_id=str(
            contract.policy["frozen_inputs"]["model_lock"]["model_id"]
        ),
        hard_caps=contract.policy["hard_caps"],
    )
    if verify_openai_credential:
        from trimem_openai_model_access_check import (
            verify_approval_credential_binding,
        )

        if not verify_approval_credential_binding(
            os.environ.get("OPENAI_API_KEY"), document
        ):
            raise DiagnosticExecutorError(
                "current OpenAI credential does not match the approved commitment"
            )
    return approval, hashlib.sha256(raw).hexdigest()


def _expected_diagnostic_images(
    contract: ExecutionContract,
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str]], list[str]]:
    import trimem_benchmark_run as benchmark

    images, support = benchmark.image_entries(require_benchmark=True)
    selected: list[str] = []
    has_multi = False
    for target in contract.manifest["targets"]:
        instance_id = str(target["instance_id"])
        row = images.get(instance_id)
        if (
            not isinstance(row, Mapping)
            or row.get("target_id") != target["target_id"]
            or row.get("benchmark_id") != target["benchmark_id"]
            or not isinstance(row.get("image"), str)
            or row["image"].rsplit("@", 1)[-1] != row.get("expected_digest")
        ):
            raise DiagnosticExecutorError(
                f"frozen diagnostic image binding differs: {target['target_id']}"
            )
        selected.append(str(row["image"]))
        has_multi = has_multi or str(target["benchmark_id"]).startswith(
            "multi_swe_bench"
        )
    if has_multi:
        selected.extend(image for image, _tag in support)
    unique = list(dict.fromkeys(selected))
    if any("@sha256:" not in image for image in unique):
        raise DiagnosticExecutorError("diagnostic image set contains an unpinned image")
    return images, support, unique


def _diagnostic_tags_by_image(
    contract: ExecutionContract,
    images: Mapping[str, Mapping[str, Any]],
    support: Sequence[tuple[str, str]],
    selected: Sequence[str],
) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {image: [] for image in selected}
    for target in contract.manifest["targets"]:
        row = images[str(target["instance_id"])]
        tags[str(row["image"])].append(str(row["harness_image_tag"]))
    for image, tag in support:
        if image in tags:
            tags[image].append(tag)
    return {image: list(dict.fromkeys(values)) for image, values in tags.items()}


def reinspect_diagnostic_images(
    *,
    contract: ExecutionContract,
    approval_artifact_sha256: str,
    evidence_root: Path,
) -> str:
    """Re-observe every already-pulled digest without another pull."""

    import trimem_pull_locked_images as puller
    from enterprise_memory.trimem.accounting import strict_json_loads

    _images, _support, selected = _expected_diagnostic_images(contract)
    rows: list[dict[str, Any]] = []
    for index, image in enumerate(selected):
        completed, references = puller._run(  # noqa: SLF001 - exact pull evidence primitive
            [
                "docker", "image", "inspect", "--format",
                "{{json .RepoDigests}}", image,
            ],
            evidence_root,
            index,
            "live-reinspect",
        )
        if completed.returncode != 0:
            raise DiagnosticExecutorError(
                f"live diagnostic image is absent: {image}"
            )
        try:
            values = strict_json_loads(
                getattr(completed.stdout, "raw_bytes", None)
                or str(completed.stdout).encode("utf-8")
            )
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise DiagnosticExecutorError(
                f"live diagnostic image inspect is malformed: {image}"
            ) from exc
        expected = image.rsplit("@", 1)[-1]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or "@sha256:" not in value for value in values)
        ):
            raise DiagnosticExecutorError(
                f"live diagnostic image inspect has no exact digests: {image}"
            )
        observed = sorted({value.rsplit("@", 1)[-1] for value in values})
        if expected not in observed:
            raise DiagnosticExecutorError(
                f"live diagnostic image digest drift: {image}"
            )
        rows.append(
            {
                "image": image,
                "expected_digest": expected,
                "observed_digests": observed,
                "inspect": references,
            }
        )
    report = {
        "schema": "trimem/dev-activation-image-live-reinspection/1.0",
        "status": "PASS_ALL_FROZEN_DIGESTS_PRESENT",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "approval_artifact_sha256": _require_sha256(
            approval_artifact_sha256, "approval artifact hash"
        ),
        "image_count": len(rows),
        "images": rows,
        "model_calls": 0,
        "paid_model_calls": 0,
        "official_grader_runs": 0,
    }
    report_path = evidence_root / "report.json"
    _atomic_write_json(report_path, report)
    return hashlib.sha256(report_path.read_bytes()).hexdigest()


def _solver_image_environment(entries: object, *, target_id: str) -> dict[str, Any]:
    if entries is None:
        values: list[str] = []
    elif isinstance(entries, list) and all(isinstance(item, str) for item in entries):
        values = list(entries)
    else:
        raise DiagnosticExecutorError("solver image Config.Env is malformed")
    if len(values) > 256 or any(len(item.encode("utf-8")) > 8192 for item in values):
        raise DiagnosticExecutorError("solver image Config.Env is unbounded")
    parsed: dict[str, str] = {}
    for item in values:
        name, separator, value = item.partition("=")
        if (
            not separator
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
            or name in parsed
        ):
            raise DiagnosticExecutorError("solver image Config.Env entry is malformed")
        upper = name.upper()
        if (
            upper in {
                "OPENAI_API_KEY",
                "GITHUB_TOKEN",
                "GH_TOKEN",
                "AWS_ACCESS_KEY_ID",
                "AWS_SECRET_ACCESS_KEY",
                "AZURE_CLIENT_SECRET",
            }
            or upper.endswith(("_PASSWORD", "_SECRET", "_TOKEN"))
            or any(
                marker in value.casefold()
                for marker in (
                    "test.patch",
                    "fix.patch",
                    "fail_to_pass",
                    "pass_to_pass",
                    "gold_patch",
                    "target_gold",
                    "-----begin private key-----",
                )
            )
        ):
            raise DiagnosticExecutorError(
                f"solver image Config.Env exposes evaluator material: {target_id}"
            )
        parsed[name] = value
    return {
        "variable_names": sorted(parsed),
        "entry_count": len(values),
        "canonical_sha256": _canonical_hash(values),
        "forbidden_evaluator_or_secret_values": 0,
    }


def _run_docker_sandbox_probe(
    argv: Sequence[str],
    *,
    evidence_root: Path,
    stem: str,
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, Any]]:
    from enterprise_memory.trimem.git_workspace import _docker_cli_environment

    try:
        completed = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=False,
            check=False,
            timeout=180,
            env=_docker_cli_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DiagnosticExecutorError("solver sandbox Docker probe could not complete") from exc
    stdout_path = evidence_root / f"{stem}.stdout"
    stderr_path = evidence_root / f"{stem}.stderr"
    _atomic_write_bytes(stdout_path, completed.stdout)
    _atomic_write_bytes(stderr_path, completed.stderr)
    return completed, {
        "stdout": _evidence_reference(evidence_root, stdout_path),
        "stderr": _evidence_reference(evidence_root, stderr_path),
        "returncode": completed.returncode,
    }


def rehearse_production_solver_sandbox(
    *,
    contract: ExecutionContract,
    requests: Sequence[Mapping[str, Any]],
    tasks_by_target_id: Mapping[str, Any],
    targets_by_id: Mapping[str, Mapping[str, Any]],
    prepared_workspaces: Mapping[str, tuple[Any, Mapping[str, Any]]],
    evidence_root: Path,
    mutate_checkout: bool = False,
) -> str:
    """Prove target history and evaluator files are inaccessible before spend."""

    import trimem_benchmark_run as benchmark
    from enterprise_memory.trimem.accounting import strict_json_loads
    from enterprise_memory.trimem.git_workspace import DEFAULT_CONTAINER_USER

    report_path = evidence_root / "report.json"
    prior_report = (
        _read_exact_json(report_path, "solver sandbox rehearsal")
        if report_path.exists()
        else None
    )
    allowed_names = {"progress.json", "report.json"}
    for order_index, target in enumerate(contract.manifest["targets"]):
        allowed_names.update(
            {
                f"{order_index:02d}-config-env.stdout",
                f"{order_index:02d}-config-env.stderr",
                f"{order_index:02d}-masked.stdout",
                f"{order_index:02d}-masked.stderr",
            }
        )
        if target.get("benchmark_id") in {
            "multi_swe_bench_mini",
            "multi_swe_bench_flash",
        }:
            allowed_names.update(
                {
                    f"{order_index:02d}-raw-image.stdout",
                    f"{order_index:02d}-raw-image.stderr",
                }
            )
    if evidence_root.exists() and any(
        child.name not in allowed_names or not child.is_file()
        for child in evidence_root.iterdir()
    ):
        raise DiagnosticExecutorError("solver sandbox rehearsal root has unknown evidence")
    evidence_root.mkdir(parents=True, exist_ok=True)
    first_request_by_target: dict[str, Mapping[str, Any]] = {}
    for request in requests:
        first_request_by_target.setdefault(str(request["target_id"]), request)
    expected_order = [str(row["target_id"]) for row in contract.manifest["targets"]]
    if list(first_request_by_target) != expected_order:
        raise DiagnosticExecutorError("solver sandbox rehearsal target order differs")

    rows: list[dict[str, Any]] = []
    image_config_inspection_attempts = 0
    image_config_inspections = 0
    raw_image_probe_attempts = 0
    raw_image_probe_containers = 0
    masked_solver_probe_attempts = 0
    masked_solver_probe_containers = 0
    progress_path = evidence_root / "progress.json"

    def write_progress(
        stage: str,
        *,
        current_target_id: str | None,
        current_order_index: int | None,
    ) -> None:
        _atomic_write_json(
            progress_path,
            {
                "schema": "trimem/dev-activation-solver-sandbox-progress/1.0",
                "diagnostic_id": contract.manifest["diagnostic_id"],
                "stage": stage,
                "current_target_id": current_target_id,
                "current_order_index": current_order_index,
                "completed_target_ids": [row["target_id"] for row in rows],
                "completed_target_count": len(rows),
                "image_config_inspection_attempts": image_config_inspection_attempts,
                "image_config_inspections": image_config_inspections,
                "raw_image_probe_attempts": raw_image_probe_attempts,
                "raw_image_probe_containers": raw_image_probe_containers,
                "masked_solver_probe_attempts": masked_solver_probe_attempts,
                "masked_solver_probe_containers": masked_solver_probe_containers,
                "non_grader_probe_containers": (
                    raw_image_probe_containers + masked_solver_probe_containers
                ),
                "task_arm_runs": 0,
                "terminal_cells": 0,
                "model_api_calls": 0,
                "model_generation_calls": 0,
                "model_calls": 0,
                "paid_model_calls": 0,
                "decomposition_calls": 0,
                "solve_calls": 0,
                "extraction_calls": 0,
                "grader_calls": 0,
                "grader_containers": 0,
                "official_grader_runs": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "total_usd": "0.000000000000",
            },
        )

    write_progress("STARTED", current_target_id=None, current_order_index=None)
    toolchain_probes_by_repository = {
        "django/django": ("python --version",),
        "sympy/sympy": ("python --version",),
        "sphinx-doc/sphinx": ("python --version",),
        "matplotlib/matplotlib": ("python --version",),
        "mui/material-ui": ("node --version", "npm --version"),
        "ponylang/ponyc": ("cmake --version", "make --version", "cc --version"),
        "clap-rs/clap": ("cargo --version", "rustc --version"),
        "facebook/zstd": ("make --version", "cc --version"),
        "sharkdp/bat": ("cargo --version", "rustc --version"),
        "catchorg/Catch2": ("cmake --version", "make --version", "c++ --version"),
        "cli/cli": ("go version",),
    }
    for order_index, target_id in enumerate(expected_order):
        write_progress(
            "TARGET_STARTED",
            current_target_id=target_id,
            current_order_index=order_index,
        )
        request = first_request_by_target[target_id]
        target = targets_by_id[target_id]
        task = tasks_by_target_id[target_id]
        prepared = prepared_workspaces.get(str(request["cell_id"]))
        if prepared is None:
            raise DiagnosticExecutorError("solver sandbox rehearsal workspace is missing")
        factory, checkout_attestation = prepared
        runner = factory.command_runners.get(task.task_id)
        checkout = factory.checkout_roots.get(task.task_id)
        if runner is None or checkout is None:
            raise DiagnosticExecutorError("solver sandbox rehearsal runner is missing")
        expected_files, expected_directories = benchmark.solver_image_masks(task, target)
        if (
            tuple(getattr(runner, "masked_image_files", ())) != tuple(sorted(expected_files))
            or tuple(getattr(runner, "masked_image_directories", ()))
            != tuple(sorted(expected_directories))
            or getattr(runner, "content_hash", None)
            != checkout_attestation.get("command_sandbox_content_hash")
        ):
            raise DiagnosticExecutorError("solver sandbox mask binding differs")
        image = str(runner.image)

        image_config_inspection_attempts += 1
        write_progress(
            "IMAGE_CONFIG_INSPECTION_STARTED",
            current_target_id=target_id,
            current_order_index=order_index,
        )
        inspect, inspect_evidence = _run_docker_sandbox_probe(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                (
                    '{"environment":{{json .Config.Env}},'
                    '"image_default_user":{{json .Config.User}}}'
                ),
                image,
            ],
            evidence_root=evidence_root,
            stem=f"{order_index:02d}-config-env",
        )
        image_config_inspections += 1
        write_progress(
            "IMAGE_CONFIG_INSPECTION_COMPLETED",
            current_target_id=target_id,
            current_order_index=order_index,
        )
        if inspect.returncode != 0:
            raise DiagnosticExecutorError("solver image Config.Env inspection failed")
        try:
            image_config = strict_json_loads(inspect.stdout.strip())
        except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise DiagnosticExecutorError(
                "solver image config projection is not strict JSON"
            ) from exc
        if (
            not isinstance(image_config, Mapping)
            or set(image_config) != {"environment", "image_default_user"}
            or image_config.get("image_default_user") is not None
            and not isinstance(image_config.get("image_default_user"), str)
        ):
            raise DiagnosticExecutorError("solver image config projection is malformed")
        environment = _solver_image_environment(
            image_config.get("environment"), target_id=target_id
        )

        checkout_path = Path(checkout)
        git_metadata_path = checkout_path / ".git"
        checkout_stat = checkout_path.stat()
        git_metadata_stat = git_metadata_path.stat()
        expected_container_user = DEFAULT_CONTAINER_USER
        if (
            getattr(runner, "container_user", None) != expected_container_user
            or (checkout_stat.st_uid, checkout_stat.st_gid) != (1000, 1000)
            or (git_metadata_stat.st_uid, git_metadata_stat.st_gid) != (1000, 1000)
        ):
            raise DiagnosticExecutorError(
                "solver checkout owner differs from frozen container identity"
            )

        raw_probe_evidence: Mapping[str, Any] | None = None
        if expected_files:
            repository_path = expected_directories[0].rsplit("/.git", 1)[0]
            quoted_files = " ".join(expected_files)
            raw_script = (
                "set -eu; "
                f"for path in {quoted_files}; do test -f \"$path\"; done; "
                f"test -d {repository_path}/.git; "
                f"test \"$(git -C {repository_path} rev-parse HEAD)\" = \"$1\"; "
                f"test -z \"$(git -C {repository_path} status --porcelain=v1 "
                "--untracked-files=all)\"; printf '%s\\n' \"$1\""
            )
            raw_image_probe_attempts += 1
            write_progress(
                "RAW_IMAGE_PROBE_STARTED",
                current_target_id=target_id,
                current_order_index=order_index,
            )
            raw_probe, raw_probe_evidence = _run_docker_sandbox_probe(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=64",
                    "--entrypoint",
                    "/bin/sh",
                    image,
                    "-ceu",
                    raw_script,
                    "trimem-solver-image-probe",
                    task.commit,
                ],
                evidence_root=evidence_root,
                stem=f"{order_index:02d}-raw-image",
            )
            raw_image_probe_containers += 1
            write_progress(
                "RAW_IMAGE_PROBE_COMPLETED",
                current_target_id=target_id,
                current_order_index=order_index,
            )
            if raw_probe.returncode != 0 or raw_probe.stdout != (task.commit + "\n").encode(
                "ascii"
            ):
                raise DiagnosticExecutorError(
                    "Multi-SWE baked repository is not a pristine target base"
                )

        masked_checks = [
            "set -eu",
            'test "$(id -u)" = 1000',
            'test "$(id -g)" = 1000',
            'test "$(id -G)" = 1000',
            "git --version >/dev/null 2>&1",
            "test -x /bin/sh",
            "test \"$(git -C /testbed rev-parse HEAD)\" = \"$1\"",
            "test \"$(git -C /testbed rev-list --count HEAD)\" = 1",
            "test -z \"$(git -C /testbed for-each-ref --format='%(refname)')\"",
            "test -z \"$(git -C /testbed remote)\"",
            "test -z \"$(env | grep -E '^(OPENAI_API_KEY|GH_TOKEN|GITHUB_TOKEN|TRIMEM_)=' || true)\"",
        ]
        if expected_files:
            masked_git_directory = expected_directories[0]
            masked_checks.extend(
                [
                    "for path in "
                    + " ".join(expected_files)
                    + '; do test -e "$path"; test ! -s "$path"; '
                    + 'test "$(wc -c < "$path")" = 0; done',
                    f"test -d {masked_git_directory}",
                    f"test -z \"$(find {masked_git_directory} -mindepth 1 "
                    "-print -quit)\"",
                ]
            )
        toolchain_probes = toolchain_probes_by_repository.get(task.repository)
        if toolchain_probes is None:
            raise DiagnosticExecutorError(
                "solver rehearsal toolchain repository is not frozen"
            )
        masked_checks.extend(
            [
                *(probe + " >/dev/null 2>&1" for probe in toolchain_probes),
                "set -- /sys/class/net/*",
                'test "$#" = 1',
                'test "${1##*/}" = lo',
                "mkdir -p /tmp/trimem-home",
                "test -d /tmp/trimem-home",
                ': > /tmp/trimem-home/write-probe',
                "rm /tmp/trimem-home/write-probe",
                "awk '$5 == \"/\" && $6 ~ /(^|,)ro(,|$)/ { found=1 } "
                "END { exit(found ? 0 : 1) }' /proc/self/mountinfo",
                "awk '$5 == \"/testbed\" && $6 ~ /(^|,)rw(,|$)/ { found=1 } "
                "END { exit(found ? 0 : 1) }' /proc/self/mountinfo",
                "awk '$5 == \"/testbed/.git\" && $6 ~ /(^|,)ro(,|$)/ "
                "{ found=1 } END { exit(found ? 0 : 1) }' /proc/self/mountinfo",
                "awk '$5 == \"/tmp\" && $6 ~ /(^|,)rw(,|$)/ { found=1 } "
                "END { exit(found ? 0 : 1) }' /proc/self/mountinfo",
            ]
        )
        if mutate_checkout:
            masked_checks.extend(
                [
                    "if touch /.trimem-rootfs-write-probe 2>/dev/null; then "
                    "rm -f /.trimem-rootfs-write-probe; exit 91; fi",
                    "if touch /testbed/.git/trimem-write-probe 2>/dev/null; then "
                    "rm -f /testbed/.git/trimem-write-probe; exit 92; fi",
                    "probe=/testbed/.trimem-solver-sandbox-write-probe",
                    'test -f "$probe"',
                    'printf \'CONTAINER_UPDATED\\n\' > "$probe"',
                    "mkdir /testbed/.trimem-solver-sandbox-write-directory",
                    "printf 'NESTED_WRITE\\n' > "
                    "/testbed/.trimem-solver-sandbox-write-directory/probe",
                ]
            )
        else:
            masked_checks.append("test -w /testbed")
        masked_checks.append("printf 'PASS_SOLVER_SANDBOX\\n'")
        masked_script = "; ".join(masked_checks)
        host_probe = checkout_path / ".trimem-solver-sandbox-write-probe"
        host_probe_directory = (
            checkout_path / ".trimem-solver-sandbox-write-directory"
        )
        host_nested_probe = host_probe_directory / "probe"
        if mutate_checkout:
            if (
                host_probe.exists()
                or host_probe.is_symlink()
                or host_probe_directory.exists()
                or host_probe_directory.is_symlink()
            ):
                raise DiagnosticExecutorError("solver write probe path already exists")
            _atomic_write_bytes(host_probe, b"HOST_PREPARED\n")
            host_probe.chmod(0o600)
        host_write_verified = not mutate_checkout
        try:
            masked_solver_probe_attempts += 1
            write_progress(
                "MASKED_SOLVER_PROBE_STARTED",
                current_target_id=target_id,
                current_order_index=order_index,
            )
            masked_probe = runner.run(
                checkout_path,
                (
                    "/bin/sh",
                    "-ceu",
                    masked_script,
                    "trimem-solver-mask-probe",
                    task.commit,
                ),
                cwd=None,
                timeout_seconds=120,
            )
            masked_solver_probe_containers += 1
            write_progress(
                "MASKED_SOLVER_PROBE_COMPLETED",
                current_target_id=target_id,
                current_order_index=order_index,
            )
            masked_stdout_path = evidence_root / f"{order_index:02d}-masked.stdout"
            masked_stderr_path = evidence_root / f"{order_index:02d}-masked.stderr"
            _atomic_write_bytes(masked_stdout_path, masked_probe.stdout.encode("utf-8"))
            _atomic_write_bytes(masked_stderr_path, masked_probe.stderr.encode("utf-8"))
            probe_terminal_pass = (
                masked_probe.exit_code == 0
                and not masked_probe.timed_out
                and not masked_probe.output_truncated
                and masked_probe.stdout == "PASS_SOLVER_SANDBOX\n"
            )
            if mutate_checkout and probe_terminal_pass:
                probe_stat = os.lstat(host_probe)
                directory_stat = os.lstat(host_probe_directory)
                nested_stat = os.lstat(host_nested_probe)
                if (
                    not stat.S_ISREG(probe_stat.st_mode)
                    or probe_stat.st_nlink != 1
                    or (probe_stat.st_uid, probe_stat.st_gid) != (1000, 1000)
                    or not stat.S_ISDIR(directory_stat.st_mode)
                    or (directory_stat.st_uid, directory_stat.st_gid) != (1000, 1000)
                    or not stat.S_ISREG(nested_stat.st_mode)
                    or nested_stat.st_nlink != 1
                    or (nested_stat.st_uid, nested_stat.st_gid) != (1000, 1000)
                ):
                    raise DiagnosticExecutorError(
                        f"solver write probe node identity differs: {target_id}"
                    )
                # The container has exited before runner.run returns, so these
                # lstat-then-read checks have no concurrent container writer.
                host_write_verified = (
                    host_probe.read_bytes() == b"CONTAINER_UPDATED\n"
                    and host_nested_probe.read_bytes() == b"NESTED_WRITE\n"
                )
        finally:
            if mutate_checkout:
                if host_probe_directory.is_symlink():
                    raise DiagnosticExecutorError(
                        "solver write probe directory became a symlink"
                    )
                if host_nested_probe.exists() or host_nested_probe.is_symlink():
                    host_nested_probe.unlink()
                if host_probe_directory.exists():
                    host_probe_directory.rmdir()
                if host_probe.exists() or host_probe.is_symlink():
                    host_probe.unlink()
        try:
            benchmark.validate_pristine_checkout(checkout_path, task.commit)
        except Exception as exc:
            raise DiagnosticExecutorError(
                "solver rehearsal did not restore a pristine checkout"
            ) from exc
        if (
            not probe_terminal_pass
            or not host_write_verified
        ):
            raise DiagnosticExecutorError(
                f"production solver sandbox mask rehearsal failed: {target_id}"
            )
        rows.append(
            {
                "order_index": order_index,
                "target_id": target_id,
                "benchmark_id": target["benchmark_id"],
                "base_commit": task.commit,
                "image": image,
                "runner_content_hash": runner.content_hash,
                "history_isolation_sha256": hashlib.sha256(
                    diagnostic.canonical_bytes(checkout_attestation["history_isolation"])
                ).hexdigest(),
                "masked_image_files": list(expected_files),
                "masked_image_directories": list(expected_directories),
                "image_environment": environment,
                "image_default_user": image_config.get("image_default_user"),
                "effective_container_user": expected_container_user,
                "required_toolchain_commands": list(toolchain_probes),
                "checkout_write_probe": (
                    "PASS_HOST_0600_AND_NESTED_WRITE"
                    if mutate_checkout
                    else "PASS_OWNER_WRITE_ACCESS_WITHOUT_MUTATION"
                ),
                "home_tmpfs_write_probe": "PASS",
                "root_filesystem_write_probe": (
                    "PASS_READ_ONLY_MOUNT_AND_ACTIVE_DENIAL"
                    if mutate_checkout
                    else "PASS_READ_ONLY_MOUNT"
                ),
                "git_metadata_write_probe": (
                    "PASS_READ_ONLY_MOUNT_AND_ACTIVE_DENIAL"
                    if mutate_checkout
                    else "PASS_READ_ONLY_MOUNT"
                ),
                "network_interface_probe": "LOOPBACK_ONLY",
                "post_probe_checkout": "PRISTINE_AT_BASE_COMMIT",
                "checkout_mount_identity": {
                    "uid": checkout_stat.st_uid,
                    "gid": checkout_stat.st_gid,
                    "mode": f"{stat.S_IMODE(checkout_stat.st_mode):04o}",
                },
                "git_metadata_mount_identity": {
                    "uid": git_metadata_stat.st_uid,
                    "gid": git_metadata_stat.st_gid,
                    "mode": f"{stat.S_IMODE(git_metadata_stat.st_mode):04o}",
                },
                "config_env_evidence": inspect_evidence,
                "raw_image_probe_evidence": raw_probe_evidence,
                "masked_probe_evidence": {
                    "stdout": _evidence_reference(evidence_root, masked_stdout_path),
                    "stderr": _evidence_reference(evidence_root, masked_stderr_path),
                    "returncode": masked_probe.exit_code,
                },
                "raw_probe_script_sha256": hashlib.sha256(
                    (raw_script if expected_files else "").encode("utf-8")
                ).hexdigest(),
                "masked_probe_script_sha256": hashlib.sha256(
                    masked_script.encode("utf-8")
                ).hexdigest(),
                "status": "PASS_NO_TARGET_HISTORY_OR_EVALUATOR_FILES_VISIBLE",
            }
        )
        write_progress(
            "TARGET_COMPLETED",
            current_target_id=target_id,
            current_order_index=order_index,
        )
    report = {
        "schema": SOLVER_SANDBOX_REHEARSAL_SCHEMA,
        "status": "PASS_ALL_12_PRODUCTION_SOLVER_SANDBOXES",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "target_count": 12,
        "checkout_mutation_probe": mutate_checkout,
        "image_config_inspection_attempts": image_config_inspection_attempts,
        "image_config_inspections": image_config_inspections,
        "raw_image_probe_attempts": raw_image_probe_attempts,
        "raw_image_probe_containers": raw_image_probe_containers,
        "masked_solver_probe_attempts": masked_solver_probe_attempts,
        "masked_solver_probe_containers": masked_solver_probe_containers,
        "non_grader_probe_containers": (
            raw_image_probe_containers + masked_solver_probe_containers
        ),
        "task_arm_runs": 0,
        "terminal_cells": 0,
        "model_api_calls": 0,
        "model_generation_calls": 0,
        "decomposition_calls": 0,
        "solve_calls": 0,
        "extraction_calls": 0,
        "grader_calls": 0,
        "grader_containers": 0,
        "official_grader_runs": 0,
        "model_calls": 0,
        "paid_model_calls": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "total_usd": "0.000000000000",
        "rows": rows,
    }
    if prior_report is not None and diagnostic.canonical_bytes(
        prior_report
    ) != diagnostic.canonical_bytes(report):
        raise DiagnosticExecutorError("solver sandbox resume evidence drift")
    _atomic_write_json(report_path, report)
    write_progress("COMPLETE", current_target_id=None, current_order_index=None)
    return hashlib.sha256(report_path.read_bytes()).hexdigest()


def rehearse_existing_dev_solver_sandboxes(
    *,
    contract: ExecutionContract,
    checkout_root: Path,
    dataset_cache_root: Path,
    evidence_root: Path,
) -> str:
    """Run the exact 12 production solver probes without approval or secrets."""

    import trimem_benchmark_run as benchmark

    targets, rows = benchmark.load_frozen_rows("development", dataset_cache_root)
    if diagnostic.canonical_bytes(targets) != diagnostic.canonical_bytes(
        contract.manifest["targets"]
    ):
        raise DiagnosticExecutorError("rehearsal DEV target set/order differs")
    tasks = benchmark.coding_tasks(targets, rows)
    if len(tasks) != 12:
        raise DiagnosticExecutorError("rehearsal DEV task set is not exact")
    images, _support = benchmark.image_entries(require_benchmark=True)
    factory, attestations = benchmark.prepare_checkouts(
        tasks,
        targets,
        images,
        checkout_root,
        resume=True,
    )
    requests: list[dict[str, str]] = []
    prepared: dict[str, tuple[Any, Mapping[str, Any]]] = {}
    for task in tasks:
        cell_id = "PRE_BILLING_REHEARSAL--" + task.task_id
        requests.append({"cell_id": cell_id, "target_id": task.task_id})
        prepared[cell_id] = (factory, attestations[task.task_id])
    return rehearse_production_solver_sandbox(
        contract=contract,
        requests=requests,
        tasks_by_target_id={task.task_id: task for task in tasks},
        targets_by_id={str(row["target_id"]): row for row in targets},
        prepared_workspaces=prepared,
        evidence_root=evidence_root,
        mutate_checkout=True,
    )


def materialize_diagnostic_images(
    *,
    contract: ExecutionContract,
    approval_artifact_sha256: str,
    evidence_root: Path,
) -> Mapping[str, Any]:
    """Pull the exact DEV target/support images after diagnostic approval."""

    import trimem_pull_locked_images as puller

    approval_digest = _require_sha256(
        approval_artifact_sha256, "approval artifact hash"
    )
    images, support, selected = _expected_diagnostic_images(contract)
    evidence_root = _require_repository_subpath(
        ROOT, evidence_root, "image evidence root"
    )
    report_path = evidence_root / "report.json"
    if evidence_root.exists() and any(evidence_root.iterdir()):
        raise DiagnosticExecutorError("fresh image evidence root is not empty")
    tags_by_image = _diagnostic_tags_by_image(
        contract, images, support, selected
    )
    rows: list[Mapping[str, Any]] = []
    attempted: list[str] = []
    try:
        for index, image in enumerate(selected):
            attempted.append(image)
            rows.append(
                puller.pull_and_observe_image(image, evidence_root, index)
            )
    except BaseException as exc:
        rollback_rows: list[Mapping[str, Any]] = []
        rollback_errors: list[dict[str, str]] = []
        rollback_root = evidence_root / "rollback"
        for index, image in enumerate(reversed(attempted)):
            try:
                references = list(dict.fromkeys([*tags_by_image[image], image]))
                cleanup_rows = [
                    puller._cleanup_reference(  # noqa: SLF001 - absent-safe exact cleanup
                        reference,
                        rollback_root,
                        index * 100 + reference_index,
                    )
                    for reference_index, reference in enumerate(references)
                ]
                rollback_rows.append(
                    {
                        "image": image,
                        "references": cleanup_rows,
                        "status": "PASS_EXACT_REFERENCES_ABSENT_OR_REMOVED",
                    }
                )
            except BaseException as rollback_exc:
                rollback_errors.append(
                    {
                        "image": image,
                        "failure": (
                            f"{type(rollback_exc).__name__}: {rollback_exc}"
                        ),
                    }
                )
        failure_report = {
            "schema": "trimem/dev-activation-image-materialization-failure/1.0",
            "status": (
                "ROLLED_BACK_EXACT_ATTEMPTED_SET"
                if not rollback_errors
                else "ROLLBACK_INCOMPLETE_FAIL_CLOSED"
            ),
            "diagnostic_id": contract.manifest["diagnostic_id"],
            "approval_artifact_sha256": approval_digest,
            "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
            "attempted_images": attempted,
            "completed_pull_rows": rows,
            "rollback_images": rollback_rows,
            "rollback_errors": rollback_errors,
            "pull_failure": f"{type(exc).__name__}: {exc}",
            "model_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "total_usd": "0.000000000000",
        }
        _atomic_write_json(evidence_root / "failure-report.json", failure_report)
        raise DiagnosticExecutorError(
            "diagnostic image materialization failed; "
            + (
                "attempted images were rolled back"
                if not rollback_errors
                else "image rollback was incomplete"
            )
        ) from exc
    report = {
        "schema": "trimem/dev-activation-image-materialization/1.0",
        "status": "PASS",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "approval_artifact_sha256": approval_digest,
        "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
        "target_set_sha256": contract.manifest["development_manifest"][
            "target_set_sha256"
        ],
        "image_count": len(rows),
        "images": rows,
        "model_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "total_usd": "0.000000000000",
    }
    _atomic_write_json(report_path, report)
    return MappingProxyType(report)


def validate_diagnostic_image_materialization(
    *,
    contract: ExecutionContract,
    approval_artifact_sha256: str,
    report_path: Path,
) -> dict[str, Any]:
    """Require exact successful pull/inspect evidence before model construction."""

    report = _read_exact_json(report_path, "diagnostic image materialization")
    _images, _support, selected = _expected_diagnostic_images(contract)
    rows = report.get("images")
    exact = {
        "schema": "trimem/dev-activation-image-materialization/1.0",
        "status": "PASS",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "approval_artifact_sha256": _require_sha256(
            approval_artifact_sha256, "approval artifact hash"
        ),
        "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
        "target_set_sha256": contract.manifest["development_manifest"][
            "target_set_sha256"
        ],
        "image_count": len(selected),
        "model_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "total_usd": "0.000000000000",
    }
    if not isinstance(rows, list) or any(report.get(key) != value for key, value in exact.items()):
        raise DiagnosticExecutorError("diagnostic image materialization binding differs")
    if [row.get("image") for row in rows if isinstance(row, Mapping)] != selected:
        raise DiagnosticExecutorError("diagnostic image materialization set/order differs")
    for expected, row in zip(selected, rows):
        digest = expected.rsplit("@", 1)[-1]
        if (
            not isinstance(row, Mapping)
            or row.get("expected_digest") != digest
            or digest not in row.get("observed_digests", ())
            or not isinstance(row.get("pull"), Mapping)
            or not isinstance(row.get("inspect"), Mapping)
        ):
            raise DiagnosticExecutorError("diagnostic image observation is incomplete")
    return report


def cleanup_diagnostic_images(
    *,
    contract: ExecutionContract,
    image_materialization_report: Path,
    evidence_root: Path,
) -> Mapping[str, Any]:
    """Remove only aliases proven by a completed diagnostic pull report."""

    import trimem_pull_locked_images as puller

    failure_path = image_materialization_report.with_name("failure-report.json")
    if not image_materialization_report.is_file() and failure_path.is_file():
        failure = _read_exact_json(
            failure_path, "diagnostic image materialization failure"
        )
        _images, _support, selected = _expected_diagnostic_images(contract)
        attempted = failure.get("attempted_images")
        if (
            failure.get("schema")
            != "trimem/dev-activation-image-materialization-failure/1.0"
            or failure.get("status") != "ROLLED_BACK_EXACT_ATTEMPTED_SET"
            or failure.get("diagnostic_id") != contract.manifest["diagnostic_id"]
            or failure.get("source_bank_manifest_sha256")
            != contract.source_bank_manifest_sha256
            or not isinstance(attempted, list)
            or attempted != selected[: len(attempted)]
            or failure.get("rollback_errors") != []
        ):
            raise DiagnosticExecutorError(
                "failed materialization has no complete rollback proof"
            )
        evidence_root = _require_repository_subpath(
            ROOT, evidence_root, "image cleanup evidence root"
        )
        if evidence_root.exists() and any(evidence_root.iterdir()):
            raise DiagnosticExecutorError(
                "fresh image cleanup evidence root is not empty"
            )
        report = {
            "schema": "trimem/dev-activation-image-cleanup/1.0",
            "status": "PASS_ALREADY_ROLLED_BACK",
            "diagnostic_id": contract.manifest["diagnostic_id"],
            "approval_artifact_sha256": _require_sha256(
                failure.get("approval_artifact_sha256"),
                "failed materialization approval hash",
            ),
            "materialization_failure_report_sha256": hashlib.sha256(
                failure_path.read_bytes()
            ).hexdigest(),
            "image_count": len(attempted),
            "images": failure.get("rollback_images"),
            "model_calls": 0,
            "official_grader_runs": 0,
            "paid_model_calls": 0,
            "total_usd": "0.000000000000",
        }
        _atomic_write_json(evidence_root / "report.json", report)
        return MappingProxyType(report)
    materialization = _read_exact_json(
        image_materialization_report, "diagnostic image materialization"
    )
    approval_digest = _require_sha256(
        materialization.get("approval_artifact_sha256"),
        "materialization approval artifact hash",
    )
    validate_diagnostic_image_materialization(
        contract=contract,
        approval_artifact_sha256=approval_digest,
        report_path=image_materialization_report,
    )
    images, support, selected = _expected_diagnostic_images(contract)
    tags_by_image = _diagnostic_tags_by_image(
        contract, images, support, selected
    )
    evidence_root = _require_repository_subpath(
        ROOT, evidence_root, "image cleanup evidence root"
    )
    if evidence_root.exists() and any(evidence_root.iterdir()):
        raise DiagnosticExecutorError("fresh image cleanup evidence root is not empty")
    rows = [
        puller.remove_materialized_image(
            image,
            tags_by_image[image],
            evidence_root,
            index,
        )
        for index, image in enumerate(reversed(selected))
    ]
    report = {
        "schema": "trimem/dev-activation-image-cleanup/1.0",
        "status": "PASS",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "approval_artifact_sha256": approval_digest,
        "materialization_report_sha256": hashlib.sha256(
            image_materialization_report.read_bytes()
        ).hexdigest(),
        "image_count": len(rows),
        "images": rows,
        "model_calls": 0,
        "official_grader_runs": 0,
        "paid_model_calls": 0,
        "total_usd": "0.000000000000",
    }
    _atomic_write_json(evidence_root / "report.json", report)
    return MappingProxyType(report)


def prepare_official_production_execution(
    *,
    contract: ExecutionContract,
    approval: Mapping[str, Any],
    approval_artifact_sha256: str,
    output_root: Path,
    dataset_cache_root: Path,
    harness_root: Path,
    loader_preflight_path: Path,
    image_materialization_report: Path,
    workspace_root: Path,
    resume: bool,
) -> PreparedProductionExecution:
    """Build the real one-cell backend from existing benchmark primitives.

    This function is deliberately called only by the approval-gated CLI.  It
    may materialize pinned datasets/harnesses, but it does not call a model or
    grader.  Those calls occur serially inside ``execute_diagnostic``.
    """

    import trimem_benchmark_run as benchmark
    from enterprise_memory.trimem.adaptive_horizon import AdaptiveHorizonPolicy
    from enterprise_memory.trimem.ppr import PinnedSentenceTransformerPPR
    from enterprise_memory.trimem.retrieval import RetrievalConfig
    from trimem_harness_lock import prepare_harnesses
    from trimem_m2_candidates import runtime_lock_for

    _validate_contract_object(contract)
    digest = _require_sha256(
        approval_artifact_sha256, "approval artifact hash"
    )
    if approval.get("hard_caps") != contract.policy["hard_caps"]:
        raise DiagnosticExecutorError("approval hard caps differ from diagnostic policy")
    if not os.environ.get("OPENAI_API_KEY"):
        raise DiagnosticExecutorError("OPENAI_API_KEY is absent at approved execution")
    from trimem_dev_activation_gate import APPROVAL_SCHEMA
    from trimem_openai_model_access_check import verify_approval_credential_binding

    if not verify_approval_credential_binding(
        os.environ.get("OPENAI_API_KEY"),
        {"schema": APPROVAL_SCHEMA, "approval": dict(approval)},
    ):
        raise DiagnosticExecutorError(
            "current OpenAI credential does not match production approval"
        )
    output_root = _require_repository_subpath(ROOT, output_root, "output root")
    dataset_cache_root = _require_repository_subpath(
        ROOT, dataset_cache_root, "dataset cache root"
    )
    harness_root = _require_repository_subpath(ROOT, harness_root, "harness root")
    loader_preflight_path = _require_repository_subpath(
        ROOT, loader_preflight_path, "loader preflight"
    )
    image_materialization_report = _require_repository_subpath(
        ROOT, image_materialization_report, "image materialization report"
    )
    workspace_root = _require_repository_subpath(
        ROOT, workspace_root, "diagnostic workspace root"
    )

    requests = build_cell_requests(
        contract, execution_identity_sha256=digest
    )
    binding = _execution_binding(
        contract=contract,
        capabilities=production_capabilities(
            "trimem-dev-activation-official-cell-v1"
        ),
        execution_identity_sha256=digest,
        requests=requests,
    )
    binding_path = output_root / "execution-binding.json"
    if not binding_path.is_file() or diagnostic.canonical_bytes(
        _read_exact_json(binding_path, "execution binding")
    ) != diagnostic.canonical_bytes(binding):
        raise DiagnosticExecutorError(
            "execution binding must be established before production preparation"
        )

    benchmark.validate_benchmark_environment()
    validate_diagnostic_image_materialization(
        contract=contract,
        approval_artifact_sha256=digest,
        report_path=image_materialization_report,
    )
    image_reinspection_sha256 = reinspect_diagnostic_images(
        contract=contract,
        approval_artifact_sha256=digest,
        evidence_root=(
            output_root
            / "control"
            / "image-live-reinspection"
            / ("resume" if resume else "fresh")
        ),
    )
    targets, rows = benchmark.load_frozen_rows("development", dataset_cache_root)
    if diagnostic.canonical_bytes(targets) != diagnostic.canonical_bytes(
        contract.manifest["targets"]
    ):
        raise DiagnosticExecutorError("loaded DEV target set/order differs from diagnostic")
    tasks = benchmark.coding_tasks(targets, rows)
    tasks_by_id = {task.task_id: task for task in tasks}
    if len(tasks_by_id) != 12:
        raise DiagnosticExecutorError("loaded DEV coding task set is not exact")
    for task in tasks:
        assignment = contract.assignments_by_target.get(task.task_id)
        if assignment is None:
            raise DiagnosticExecutorError(
                "source-bank assignment is absent for loaded DEV task"
            )
        expected_instruction_sha = _require_sha256(
            assignment.get("target_public_instruction_sha256"),
            "target runtime public-instruction hash",
        )
        if hashlib.sha256(task.instruction.encode("utf-8")).hexdigest() != (
            expected_instruction_sha
        ):
            raise DiagnosticExecutorError(
                "source-bank target projection differs from runtime public instruction"
            )

    harnesses = prepare_harnesses(harness_root)
    preflight = benchmark.load_official_harness_loader_preflight(
        loader_preflight_path
    )
    benchmark.validate_preflight_harness_root_binding(preflight, harnesses)
    images, support, _selected = _expected_diagnostic_images(contract)
    targets_by_id = {str(row["target_id"]): dict(row) for row in targets}

    # Materialize every fresh cell checkout before a paid gateway can be
    # constructed.  The repositories live outside the evidence/artifact tree;
    # only bounded checkout attestations are copied into each cell journal.
    workspace_preflight_path = output_root / "control" / "workspace-preflight.json"
    expected_workspace_names = {
        f"{int(request['cell_index']):02d}-{_safe_workspace_name(request['target_id'])}"
        for request in requests
    }
    if workspace_root.exists():
        observed_workspace_names = {child.name for child in workspace_root.iterdir()}
        if not observed_workspace_names.issubset(expected_workspace_names):
            raise DiagnosticExecutorError("diagnostic workspace root contains unknown cells")
        if observed_workspace_names and not resume:
            raise DiagnosticExecutorError("fresh diagnostic workspace root is not empty")
    prepared_workspaces: dict[str, tuple[Any, Mapping[str, Any]]] = {}
    workspace_rows: list[dict[str, Any]] = []
    prior_workspace_preflight = (
        _read_exact_json(workspace_preflight_path, "workspace preflight")
        if workspace_preflight_path.exists()
        else None
    )
    if prior_workspace_preflight is not None and not resume:
        raise DiagnosticExecutorError("workspace preflight exists without --resume")
    for request in requests:
        task = tasks_by_id[str(request["target_id"])]
        target = targets_by_id[str(request["target_id"])]
        name = f"{int(request['cell_index']):02d}-{_safe_workspace_name(task.task_id)}"
        checkout_root = workspace_root / name / "checkouts"
        checkout = checkout_root / _safe_workspace_name(task.task_id)
        exists = checkout.exists()
        factory, checkout_rows = benchmark.prepare_checkouts(
            [task], [target], images, checkout_root, resume=exists
        )
        attestation = checkout_rows[task.task_id]
        if prior_workspace_preflight is None and attestation.get("initial_status") != "":
            raise DiagnosticExecutorError(
                "pre-execution diagnostic checkout is not pristine"
            )
        if not benchmark._valid_history_isolation_evidence(  # noqa: SLF001
            attestation.get("history_isolation"), expected_commit=task.commit
        ):
            raise DiagnosticExecutorError(
                "pre-execution diagnostic checkout history is not base-only"
            )
        prepared_workspaces[str(request["cell_id"])] = (factory, attestation)
        workspace_rows.append(
            {
                "cell_id": request["cell_id"],
                "cell_index": request["cell_index"],
                "target_id": request["target_id"],
                "workspace_relative_path": str(
                    workspace_root.relative_to(ROOT) / name
                ).replace("\\", "/"),
                "head": attestation["head"],
                "initial_status_sha256": hashlib.sha256(
                    str(attestation["initial_status"]).encode("utf-8")
                ).hexdigest(),
                "history_isolation_sha256": hashlib.sha256(
                    diagnostic.canonical_bytes(attestation["history_isolation"])
                ).hexdigest(),
                "command_sandbox_content_hash": attestation[
                    "command_sandbox_content_hash"
                ],
                "masked_image_files": attestation["masked_image_files"],
                "masked_image_directories": attestation[
                    "masked_image_directories"
                ],
            }
        )
    workspace_preflight = {
        "schema": "trimem/dev-activation-workspace-preflight/1.1",
        "status": "PASS_36_BASE_ONLY_NAMESPACES_PREMATERIALIZED",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "execution_identity_sha256": digest,
        "cell_count": 36,
        "cells": workspace_rows,
        "model_calls": 0,
        "paid_model_calls": 0,
        "official_grader_runs": 0,
    }
    if prior_workspace_preflight is None:
        _atomic_write_json(workspace_preflight_path, workspace_preflight)
    elif diagnostic.canonical_bytes(prior_workspace_preflight) != diagnostic.canonical_bytes(
        workspace_preflight
    ):
        # Current status can differ after an interrupted/completed cell.  The
        # durable pre-spend attestation remains authoritative; identities and
        # immutable HEAD bindings must still match exactly.
        prior_rows = prior_workspace_preflight.get("cells")
        immutable = lambda rows: [
            {
                key: row[key]
                for key in (
                    "cell_id", "cell_index", "target_id",
                    "workspace_relative_path", "head",
                    "history_isolation_sha256", "command_sandbox_content_hash",
                    "masked_image_files", "masked_image_directories",
                )
            }
            for row in rows
        ] if isinstance(rows, list) else None
        if (
            prior_workspace_preflight.get("schema")
            != workspace_preflight["schema"]
            or prior_workspace_preflight.get("status")
            != workspace_preflight["status"]
            or prior_workspace_preflight.get("diagnostic_id")
            != workspace_preflight["diagnostic_id"]
            or prior_workspace_preflight.get("execution_identity_sha256") != digest
            or prior_workspace_preflight.get("cell_count") != 36
            or immutable(prior_rows) != immutable(workspace_rows)
        ):
            raise DiagnosticExecutorError("workspace preflight resume identity drift")

    solver_sandbox_rehearsal_sha256 = rehearse_production_solver_sandbox(
        contract=contract,
        requests=requests,
        tasks_by_target_id=tasks_by_id,
        targets_by_id=targets_by_id,
        prepared_workspaces=prepared_workspaces,
        evidence_root=(
            output_root
            / "control"
            / "solver-sandbox-rehearsal"
            / ("resume" if resume else "fresh")
        ),
    )

    # Construct every distinct official target grader now, before OpenAI
    # client construction, to catch loader/source-row/image incompatibilities.
    grader_preflight_rows: list[dict[str, Any]] = []
    for target in targets:
        task = tasks_by_id[str(target["target_id"])]
        probe = benchmark.grader_factory(
            target,
            rows[target["instance_id"]],
            images[target["instance_id"]],
            harnesses,
            workspace_root.parent
            / "devdiag-grader-preflight"
            / _safe_workspace_name(task.task_id),
            "PRECHECK",
            support,
            loader_preflight_evidence=preflight,
        )
        grader_preflight_rows.append(
            {
                "target_id": target["target_id"],
                "grader_type": type(probe).__name__,
                "image": images[target["instance_id"]]["image"],
                "source_row_sha256": target["source_row_sha256"],
            }
        )
    grader_preflight_document = {
        "schema": "trimem/dev-activation-grader-construction-preflight/1.0",
        "status": "PASS_ALL_12_OFFICIAL_GRADER_FACTORIES",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "targets": grader_preflight_rows,
        "model_calls": 0,
        "paid_model_calls": 0,
        "official_grader_runs": 0,
    }
    grader_preflight_path = output_root / "control" / "grader-construction-preflight.json"
    if grader_preflight_path.exists():
        if not resume or diagnostic.canonical_bytes(
            _read_exact_json(grader_preflight_path, "grader construction preflight")
        ) != diagnostic.canonical_bytes(grader_preflight_document):
            raise DiagnosticExecutorError("grader construction preflight resume drift")
    else:
        _atomic_write_json(grader_preflight_path, grader_preflight_document)

    model_lock_path = ROOT / "configs/trimem_v1/model_lock.json"
    model_lock = benchmark.read_json(model_lock_path)
    model_binding = contract.policy["frozen_inputs"]["model_lock"]
    if (
        diagnostic.file_sha256(model_lock_path) != model_binding["raw_sha256"]
        or model_lock.get("primary_model", {}).get("model_id")
        != model_binding["model_id"]
    ):
        raise DiagnosticExecutorError("frozen diagnostic model lock differs")
    cost = benchmark.read_json(ROOT / "configs/trimem_v1/cost_plan.json")
    pricing = cost.get("model_pricing")
    primary = model_lock.get("primary_model", {})
    if not isinstance(pricing, Mapping) or {
        "model_id": pricing.get("model_id"),
        "input": pricing.get("input_per_million_tokens_usd"),
        "cached": pricing.get("cached_input_per_million_tokens_usd"),
        "output": pricing.get("output_per_million_tokens_usd"),
    } != {
        "model_id": primary.get("model_id"),
        "input": primary.get("input_price_per_million_tokens_usd"),
        "cached": primary.get("cached_input_price_per_million_tokens_usd"),
        "output": primary.get("output_price_per_million_tokens_usd"),
    }:
        raise DiagnosticExecutorError("model pricing differs from frozen model lock")

    base_m2_path = (
        ROOT / contract.policy["frozen_inputs"]["current_m2_policy"]["path"]
    )
    if diagnostic.file_sha256(base_m2_path) != contract.policy["frozen_inputs"][
        "current_m2_policy"
    ]["raw_sha256"]:
        raise DiagnosticExecutorError("current M2 policy raw hash differs")
    selected_binding = contract.policy["frozen_inputs"]["selected_recall_policy"]
    m2_path = ROOT / selected_binding["path"]
    if diagnostic.file_sha256(m2_path) != selected_binding["raw_sha256"]:
        raise DiagnosticExecutorError("selected recall policy raw hash differs")
    m2_policy = benchmark.read_json(m2_path)
    retrieval = m2_policy.get("retrieval")
    if not isinstance(retrieval, Mapping):
        raise DiagnosticExecutorError("current M2 retrieval policy is missing")
    retrieval_config = RetrievalConfig(
        min_confidence=float(retrieval["min_confidence"]),
        min_margin=float(retrieval["min_margin"]),
        episode_complete_threshold=float(retrieval["episode_complete_threshold"]),
        max_episodic_per_node=int(retrieval["max_episodic_per_active_node"]),
        max_semantic_per_node=int(retrieval["max_semantic_per_active_node"]),
        max_task_injections=int(retrieval["max_task_injections"]),
        context_budget_bytes=int(retrieval["context_budget_bytes"]),
        embedding_dimensions=int(retrieval["embedding_dimensions"]),
        embedding_weight=float(retrieval["embedding_weight"]),
        lexical_weight=float(retrieval["lexical_weight"]),
        ppr_damping=float(retrieval["ppr_damping"]),
        ppr_iterations=int(retrieval["ppr_iterations"]),
    )

    # Freeze payload bytes in memory and exercise the exact shared safe-pool
    # predicate for all target assignments before any paid client exists.
    from enterprise_memory.trimem.retrieval import _safe_pool_rejection_reason
    from enterprise_memory.trimem.working_graph import SemanticSubtaskNode

    preloaded_payload_bytes: dict[str, bytes] = {}
    for memory_id, record in contract.records_by_memory_id.items():
        raw = _source_payload_path(ROOT, contract, record).read_bytes()
        if hashlib.sha256(raw).hexdigest() != record["payload_sha256"]:
            raise DiagnosticExecutorError("source-bank preflight payload hash drift")
        preloaded_payload_bytes[memory_id] = raw
    source_runtime_rows: list[dict[str, Any]] = []
    for offset, target in enumerate(targets):
        c1_request = requests[12 + offset]
        c2_request = requests[24 + offset]
        task = tasks_by_id[str(target["target_id"])]
        c1_store = ManifestBackedDiagnosticSourceBankStore(
            contract=contract,
            request=c1_request,
            task=task,
            repository_root=ROOT,
            payload_bytes=preloaded_payload_bytes,
        )
        c2_store = ManifestBackedDiagnosticSourceBankStore(
            contract=contract,
            request=c2_request,
            task=task,
            repository_root=ROOT,
            payload_bytes=preloaded_payload_bytes,
        )
        if (
            c1_store.content_hash != c2_store.content_hash
            or c1_store.execution_views != c2_store.execution_views
            or not c2_store.execution_views
        ):
            raise DiagnosticExecutorError(
                "C1/C2 source-bank runtime views differ or are empty"
            )
        pathless = SemanticSubtaskNode(
            node_id="SOURCE_BANK_PREFLIGHT",
            objective="apply a verified historical repository repair",
            operation="validate source repair evidence",
            files=(),
        )
        for record in c2_store._snapshot.records.values():  # noqa: SLF001
            reason = _safe_pool_rejection_reason(
                record, target_id=task.task_id, active_node=pathless
            )
            if reason is not None:
                raise DiagnosticExecutorError(
                    f"source-bank candidate fails safe preflight: {reason}"
                )
        view_sizes = {
            memory_id: len(raw)
            for memory_id, raw in sorted(c2_store.execution_views.items())
        }
        if not view_sizes or max(view_sizes.values()) >= min(
            SOURCE_EXECUTION_VIEW_MAX_BYTES,
            retrieval_config.context_budget_bytes,
        ):
            raise DiagnosticExecutorError(
                "source-bank forced-safe view exceeds the frozen context budget"
            )
        source_runtime_rows.append(
            {
                "target_id": task.task_id,
                "candidate_memory_ids": sorted(c2_store.execution_views),
                "content_hash": c2_store.content_hash,
                "execution_view_sha256": {
                    key: hashlib.sha256(value).hexdigest()
                    for key, value in sorted(c2_store.execution_views.items())
                },
                "execution_view_bytes": view_sizes,
                "safe_pathless_wildcard_gate": "PASS",
                "c1_c2_byte_identical": True,
            }
        )
    source_runtime_preflight = {
        "schema": "trimem/dev-activation-source-runtime-preflight/1.0",
        "status": "PASS_ALL_12_SAFE_C1_C2_IDENTICAL",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
        "source_bank_snapshot_sha256": contract.source_bank_snapshot_sha256,
        "target_count": 12,
        "targets": source_runtime_rows,
        "model_calls": 0,
        "paid_model_calls": 0,
        "official_grader_runs": 0,
    }
    source_runtime_path = output_root / "control" / "source-runtime-preflight.json"
    if source_runtime_path.exists():
        if not resume or diagnostic.canonical_bytes(
            _read_exact_json(source_runtime_path, "source runtime preflight")
        ) != diagnostic.canonical_bytes(source_runtime_preflight):
            raise DiagnosticExecutorError("source runtime preflight resume drift")
    else:
        _atomic_write_json(source_runtime_path, source_runtime_preflight)
    source_runtime_preflight_sha256 = hashlib.sha256(
        source_runtime_path.read_bytes()
    ).hexdigest()
    selected_runtime_lock = runtime_lock_for("recall")
    if selected_runtime_lock.content_hash != (
        "f38dbb148e7c7e0573bfab87400ebb9c0c4a786f888d4315d214fdca289fb581"
    ) or diagnostic.file_sha256(
        ROOT / "configs/trimem_v1/m2_candidates/recall.json"
    ) != "1985ca2cceaa6ebdc02d4bd320b318a47a8144f64bde5ad0da8367c777d3d85c":
        raise DiagnosticExecutorError("EXEC-022 selected recall runtime lock differs")
    runtime_lock = replace(
        selected_runtime_lock,
        adaptive_horizon=AdaptiveHorizonPolicy(enabled=True),
    )
    if runtime_lock.content_hash != (
        "c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652"
    ):
        raise DiagnosticExecutorError("adaptive recall runtime lock differs")
    adaptive_policy = contract.policy["adaptive_horizon"]
    if {
        "base_steps_per_subtask": runtime_lock.limits.max_steps_per_subtask,
        "extension_steps": runtime_lock.adaptive_horizon.extension_steps,
        "max_extensions_per_subtask": (
            runtime_lock.adaptive_horizon.maximum_extensions_per_subtask
        ),
        "max_steps_per_subtask": (
            runtime_lock.adaptive_horizon.maximum_steps_per_subtask
        ),
        "max_solve_calls_per_task_arm": runtime_lock.limits.max_solve_calls,
    } != {
        key: adaptive_policy[key]
        for key in (
            "base_steps_per_subtask",
            "extension_steps",
            "max_extensions_per_subtask",
            "max_steps_per_subtask",
            "max_solve_calls_per_task_arm",
        )
    }:
        raise DiagnosticExecutorError("runtime adaptive horizon differs from policy")
    embedder = PinnedSentenceTransformerPPR()
    embedder_lock = model_lock["retrieval_embedding"]["production"]
    embedder_preflight_sha256 = prewarm_production_embedder(
        embedder,
        evidence_path=output_root / "control" / "embedder-preflight.json",
        expected_lock=embedder_lock,
        resume=resume,
    )
    retrieval_rehearsal_sha256 = rehearse_production_retrieval(
        contract=contract,
        requests=requests,
        tasks_by_target_id=tasks_by_id,
        repository_root=ROOT,
        payload_bytes=preloaded_payload_bytes,
        retrieval_config=retrieval_config,
        embedder=embedder,
        embedder_preflight_sha256=embedder_preflight_sha256,
        retrieval_policy_raw_sha256=diagnostic.file_sha256(m2_path),
        evidence_path=(
            output_root / "control" / "production-retrieval-rehearsal.json"
        ),
        resume=resume,
    )

    approved_caps = dict(approval["hard_caps"])
    raw_ledger = benchmark.AtomicBudgetLedger(
        output_root / "budget-ledger.json",
        approval_digest=digest,
        caps=_DiagnosticCapMapping(approved_caps),
        pricing=pricing,
    )
    ledger = DiagnosticAtomicBudgetLedger(
        raw_ledger, approved_hard_caps=approved_caps
    )
    def workspace_factory(
        request: Mapping[str, Any], task: Any, root: Path, resume: bool
    ) -> tuple[Any, Mapping[str, Any]]:
        expected_root = workspace_root / (
            f"{int(request['cell_index']):02d}-{_safe_workspace_name(task.task_id)}"
        )
        if root.resolve() != expected_root.resolve():
            raise DiagnosticExecutorError("cell workspace root differs from preflight")
        prepared = prepared_workspaces.get(str(request["cell_id"]))
        if prepared is None:
            raise DiagnosticExecutorError("cell has no prematerialized workspace")
        return prepared

    def model_gateway_factory(
        request: Mapping[str, Any], _task: Any, restricted_root: Path
    ) -> ManagedModelGateway:
        session = _StandaloneProviderSession(
            "trimem-devdiag-" + str(request["cell_index"])
        )
        try:
            gateway, client = benchmark.build_paid_model_gateway(
                session,
                ledger,
                model_lock,
                stream_id=str(request["experiment_id"]),
                restricted_response_root=restricted_root,
            )
        except BaseException:
            session.close()
            raise

        def close() -> None:
            try:
                benchmark.close_paid_model_client(session, client)
            finally:
                session.close()

        return ManagedModelGateway(gateway=gateway, close=close)

    def grader_gateway_factory(
        request: Mapping[str, Any], _task: Any, grader_root: Path
    ) -> Any:
        target = targets_by_id[str(request["target_id"])]
        return benchmark.grader_factory(
            target,
            rows[target["instance_id"]],
            images[target["instance_id"]],
            harnesses,
            grader_root,
            str(request["arm_id"]),
            support,
            loader_preflight_evidence=preflight,
        )

    model_config_hash = _canonical_hash(
        {
            "diagnostic_id": contract.manifest["diagnostic_id"],
            "approval_artifact_sha256": digest,
            "model_lock": model_lock,
            "runtime_lock": runtime_lock.to_manifest(),
            "retrieval_policy_raw_sha256": diagnostic.file_sha256(m2_path),
            "embedder_preflight_sha256": embedder_preflight_sha256,
            "retrieval_rehearsal_sha256": retrieval_rehearsal_sha256,
            "source_runtime_preflight_sha256": source_runtime_preflight_sha256,
            "image_reinspection_sha256": image_reinspection_sha256,
            "solver_sandbox_rehearsal_sha256": (
                solver_sandbox_rehearsal_sha256
            ),
        }
    )
    preflight_hash = _canonical_hash(preflight)

    def grader_config_hash(request: Mapping[str, Any]) -> str:
        target = targets_by_id[str(request["target_id"])]
        return _canonical_hash(
            {
                "diagnostic_id": contract.manifest["diagnostic_id"],
                "approval_artifact_sha256": digest,
                "target": target,
                "source_row_sha256": target["source_row_sha256"],
                "grader_image": images[target["instance_id"]],
                "loader_preflight_sha256": preflight_hash,
            }
        )

    def expected_image_digest(request: Mapping[str, Any]) -> str:
        target = targets_by_id[str(request["target_id"])]
        return str(images[target["instance_id"]]["expected_digest"])

    backend = OfficialProductionCellExecutor(
        contract=contract,
        runtime_lock=runtime_lock,
        tasks_by_target_id=tasks_by_id,
        repository_root=ROOT,
        workspace_factory=workspace_factory,
        model_gateway_factory=model_gateway_factory,
        grader_gateway_factory=grader_gateway_factory,
        retrieval_config=retrieval_config,
        embedder_factory=lambda: embedder,
        pricing=pricing,
        model_config_hash=model_config_hash,
        grader_config_hash=grader_config_hash,
        expected_image_digest=expected_image_digest,
        ledger=ledger,
        payload_bytes=preloaded_payload_bytes,
        official_grader_preflight=preflight,
        embedder_preflight_sha256=embedder_preflight_sha256,
        retrieval_rehearsal_sha256=retrieval_rehearsal_sha256,
        image_reinspection_sha256=image_reinspection_sha256,
        solver_sandbox_rehearsal_sha256=solver_sandbox_rehearsal_sha256,
        workspace_root=workspace_root,
    )
    return PreparedProductionExecution(
        executor=backend,
        execution_identity_sha256=digest,
        approval=MappingProxyType(_json_copy(approval)),
        embedder_preflight_sha256=embedder_preflight_sha256,
        retrieval_rehearsal_sha256=retrieval_rehearsal_sha256,
        image_reinspection_sha256=image_reinspection_sha256,
        solver_sandbox_rehearsal_sha256=solver_sandbox_rehearsal_sha256,
    )


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(child) for child in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise DiagnosticExecutorError(
        f"execution contract contains a non-JSON value: {type(value).__name__}"
    )


def _json_copy(value: Any) -> Any:
    return json.loads(diagnostic.canonical_bytes(_plain_json(value)))


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(diagnostic.canonical_bytes(_plain_json(value))).hexdigest()


def _require_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise DiagnosticExecutorError(f"{label} must be a lowercase sha256")
    return value


def _safe_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DiagnosticExecutorError(f"{label} is malformed")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DiagnosticExecutorError(f"{label} is not repository-relative")
    return value


def load_execution_contract(
    root: Path = ROOT,
    *,
    require_tracked: bool = True,
) -> ExecutionContract:
    """Load the complete source-bank-ready contract without external calls."""

    manifest, policy, cells, bank_hash = diagnostic.load_and_validate_contract(
        root,
        require_source_bank=True,
        require_tracked=require_tracked,
    )
    if bank_hash is None:
        raise DiagnosticExecutorError("validated source bank has no raw digest")
    bank_relative = _safe_relative_path(
        policy["source_bank"]["manifest_path"], "source-bank manifest path"
    )
    bank = diagnostic.strict_json_load(root / bank_relative)
    snapshot_hash = _require_sha256(
        bank.get("snapshot_sha256"), "source-bank snapshot digest"
    )
    assignments = bank.get("candidate_assignments")
    records = bank.get("records")
    if not isinstance(assignments, list) or not isinstance(records, list):
        raise DiagnosticExecutorError("validated source bank has no execution inventory")
    target_order = [row["target_id"] for row in manifest["targets"]]
    if [row.get("target_id") for row in assignments if isinstance(row, Mapping)] != target_order:
        raise DiagnosticExecutorError("source-bank assignment order differs from DEV")
    assignments_by_target = {
        str(row["target_id"]): MappingProxyType(_json_copy(row)) for row in assignments
    }
    records_by_memory_id = {
        str(row["memory_id"]): MappingProxyType(_json_copy(row)) for row in records
    }
    if len(assignments_by_target) != len(assignments) or len(records_by_memory_id) != len(records):
        raise DiagnosticExecutorError("source-bank execution inventory is duplicated")
    return ExecutionContract(
        manifest=MappingProxyType(_json_copy(manifest)),
        policy=MappingProxyType(_json_copy(policy)),
        expected_cells=tuple(MappingProxyType(_json_copy(row)) for row in cells),
        source_bank_manifest_sha256=_require_sha256(bank_hash, "source-bank raw digest"),
        source_bank_snapshot_sha256=snapshot_hash,
        source_bank_manifest_path=bank_relative,
        assignments_by_target=MappingProxyType(assignments_by_target),
        records_by_memory_id=MappingProxyType(records_by_memory_id),
        matrix_raw_sha256=diagnostic.file_sha256(root / diagnostic.MATRIX_PATH),
        policy_raw_sha256=diagnostic.file_sha256(root / diagnostic.POLICY_PATH),
    )


def _validate_contract_object(contract: ExecutionContract) -> None:
    _require_sha256(contract.source_bank_manifest_sha256, "source-bank raw digest")
    _require_sha256(contract.source_bank_snapshot_sha256, "source-bank snapshot digest")
    _require_sha256(contract.matrix_raw_sha256, "matrix raw digest")
    _require_sha256(contract.policy_raw_sha256, "policy raw digest")
    _safe_relative_path(contract.source_bank_manifest_path, "source-bank manifest path")
    expected = diagnostic.expected_cells(contract.manifest)
    if diagnostic.canonical_bytes(expected) != diagnostic.canonical_bytes(
        _plain_json(list(contract.expected_cells))
    ):
        raise DiagnosticExecutorError("execution contract cell plan drift")
    if len(expected) != 36 or [row["cell_index"] for row in expected] != list(range(36)):
        raise DiagnosticExecutorError("execution contract is not the exact 36-cell plan")
    manifest_arms = {
        str(row["arm_id"]): str(row["protocol"])
        for row in contract.manifest.get("arms", ())
        if isinstance(row, Mapping)
    }
    if manifest_arms != {
        arm: binding.protocol for arm, binding in ARM_BINDINGS.items()
    }:
        raise DiagnosticExecutorError("diagnostic arm-to-protocol binding drift")
    target_ids = [str(row["target_id"]) for row in contract.manifest["targets"]]
    if set(contract.assignments_by_target) != set(target_ids):
        raise DiagnosticExecutorError("source-bank assignment target set drift")
    for target_id, assignment in contract.assignments_by_target.items():
        if assignment.get("target_id") != target_id:
            raise DiagnosticExecutorError("source-bank assignment identity drift")
        _require_sha256(
            assignment.get("target_problem_provenance_sha256"),
            "target problem provenance",
        )
        _require_sha256(
            assignment.get("target_public_instruction_sha256"),
            "target runtime public-instruction hash",
        )
        candidates = assignment.get("candidates")
        if not isinstance(candidates, list):
            raise DiagnosticExecutorError("source-bank assignment candidates are missing")
        ids = [row.get("memory_id") for row in candidates if isinstance(row, Mapping)]
        if len(ids) != len(candidates) or len(ids) != len(set(ids)):
            raise DiagnosticExecutorError("source-bank candidate list is malformed")
        if any(memory_id not in contract.records_by_memory_id for memory_id in ids):
            raise DiagnosticExecutorError("source-bank assignment references unknown memory")


def build_cell_requests(
    contract: ExecutionContract,
    *,
    execution_identity_sha256: str,
) -> tuple[Mapping[str, Any], ...]:
    """Project one validated contract into the only accepted execution plan."""

    _validate_contract_object(contract)
    identity = _require_sha256(execution_identity_sha256, "execution identity")
    targets = {row["target_id"]: row for row in contract.manifest["targets"]}
    requests: list[Mapping[str, Any]] = []
    for expected in contract.expected_cells:
        arm_id = str(expected["arm_id"])
        binding = ARM_BINDINGS[arm_id]
        target_id = str(expected["target_id"])
        target = _json_copy(targets[target_id])
        assignment = contract.assignments_by_target[target_id]
        candidate_ids = [str(row["memory_id"]) for row in assignment["candidates"]]
        records = [contract.records_by_memory_id[memory_id] for memory_id in candidate_ids]
        source_view_hash: str | None = None
        source_bank: dict[str, Any] | None = None
        if binding.memory_enabled:
            source_view_hash = _canonical_hash(
                {
                    "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
                    "source_bank_snapshot_sha256": contract.source_bank_snapshot_sha256,
                    "target_id": target_id,
                    "assignment": assignment,
                    "records": records,
                }
            )
            source_bank = {
                "manifest_path": contract.source_bank_manifest_path,
                "manifest_raw_sha256": contract.source_bank_manifest_sha256,
                "snapshot_sha256": contract.source_bank_snapshot_sha256,
                "target_view_sha256": source_view_hash,
                "candidate_memory_ids": candidate_ids,
                "read_only": True,
                "mutation_allowed": False,
                "preload_before_first_model_call": True,
            }
        experiment_id = (
            f"trimem-devdiag-{identity[:12]}-{int(expected['cell_index']):02d}"
        )
        request = {
            "schema": CELL_REQUEST_SCHEMA,
            "diagnostic_id": contract.manifest["diagnostic_id"],
            **_json_copy(expected),
            "execution_identity_sha256": identity,
            "matrix_raw_sha256": contract.matrix_raw_sha256,
            "policy_raw_sha256": contract.policy_raw_sha256,
            "protocol": binding.protocol,
            "runtime_arm": binding.runtime_arm,
            "production_split": "development",
            "evaluation_mode": True,
            "experiment_id": experiment_id,
            "fresh_namespace_required": True,
            "cross_cell_carryover_allowed": False,
            "target": target,
            "source_bank": source_bank,
            "retrieval": {
                "selection_mode": binding.selection_mode,
                "diagnostic_telemetry": binding.diagnostic_telemetry,
                "require_safe_pool_metadata": binding.require_safe_pool_metadata,
                "q_use": None,
                "q_abstain": None,
                "router_policy": "N/A" if binding.memory_enabled else None,
            },
            "memory_result_persistence": "EVIDENCE_ONLY_NO_BANK_WRITE",
            "contained_model_failure_policy": "GRADE_PARTIAL_OR_CANONICAL_NOOP_AND_CONTINUE",
            "official_grader_required": True,
            "hard_caps": {
                "model_calls": contract.policy["hard_caps"]["model_calls_per_task_arm"],
                "paid_model_calls": contract.policy["hard_caps"][
                    "model_calls_per_task_arm"
                ],
                "decomposition_calls": 1,
                "solve_calls": contract.policy["adaptive_horizon"][
                    "max_solve_calls_per_task_arm"
                ],
                "extraction_calls": 1,
                "input_tokens": contract.policy["hard_caps"][
                    "max_input_tokens_per_task_arm"
                ],
                "output_tokens": contract.policy["hard_caps"][
                    "max_output_tokens_per_task_arm"
                ],
                "grader_calls": 1,
                "grader_containers": 1,
                "official_grader_runs": 1,
                "protocol_canary_calls": 0,
            },
        }
        requests.append(MappingProxyType(request))

    # C1 and C2 must receive the same logical source view for each target.
    by_key = {(row["arm_id"], row["target_id"]): row for row in requests}
    for target_id in targets:
        left = by_key[("C1", target_id)]["source_bank"]
        right = by_key[("C2", target_id)]["source_bank"]
        if (
            not isinstance(left, Mapping)
            or not isinstance(right, Mapping)
            or left["target_view_sha256"] != right["target_view_sha256"]
            or diagnostic.canonical_bytes(left) != diagnostic.canonical_bytes(right)
        ):
            raise DiagnosticExecutorError("C1/C2 source-bank views differ")
    return tuple(requests)


def _validate_capabilities(value: Mapping[str, Any], *, allow_test_executor: bool) -> dict[str, Any]:
    fields = {
        "schema",
        "executor_id",
        "executor_kind",
        "one_cell_per_invocation",
        "durable_resume",
        "fresh_namespace_per_cell",
        "read_only_source_bank",
        "contained_failure_to_official_grader",
        "official_grader_required",
        "reused_benchmark_primitives",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise DiagnosticExecutorError("cell executor capability field-set drift")
    if value.get("schema") != CAPABILITY_SCHEMA:
        raise DiagnosticExecutorError("cell executor capability schema drift")
    kind = value.get("executor_kind")
    allowed = {"OFFICIAL_PRODUCTION_CELL"}
    if allow_test_executor:
        allowed.add("CREDENTIAL_FREE_TEST_DOUBLE")
    if kind not in allowed:
        raise DiagnosticExecutorError("non-production cell executor is not authorized")
    if not isinstance(value.get("executor_id"), str) or not value["executor_id"]:
        raise DiagnosticExecutorError("cell executor identity is missing")
    for field in (
        "one_cell_per_invocation",
        "durable_resume",
        "fresh_namespace_per_cell",
        "read_only_source_bank",
        "contained_failure_to_official_grader",
        "official_grader_required",
    ):
        if value.get(field) is not True:
            raise DiagnosticExecutorError(f"cell executor lacks required capability: {field}")
    primitives = value.get("reused_benchmark_primitives")
    if kind == "OFFICIAL_PRODUCTION_CELL" and (
        not isinstance(primitives, list)
        or tuple(primitives) != REUSABLE_BENCHMARK_PRIMITIVES
    ):
        raise DiagnosticExecutorError("production backend primitive binding drift")
    if kind == "CREDENTIAL_FREE_TEST_DOUBLE" and primitives != []:
        raise DiagnosticExecutorError("test executor cannot claim production primitives")
    return _json_copy(value)


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = diagnostic.canonical_bytes(value) + b"\n"
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def prewarm_production_embedder(
    embedder: Any,
    *,
    evidence_path: Path,
    expected_lock: Mapping[str, Any],
    resume: bool,
) -> str:
    """Eagerly prove the pinned embedder works before a paid gateway exists."""

    provenance = _json_copy(embedder.provenance())
    if (
        provenance.get("model_id") != expected_lock.get("model_id")
        or provenance.get("revision") != expected_lock.get("revision")
        or provenance.get("dimensions") != expected_lock.get("dimension")
        or provenance.get("production") is not True
        or provenance.get("normalized") is not True
    ):
        raise DiagnosticExecutorError("production retrieval embedder lock differs")
    try:
        vector = tuple(float(value) for value in embedder.embed(EMBEDDER_PROBE))
    except BaseException as exc:
        raise DiagnosticExecutorError(
            f"production retrieval embedder prewarm failed: {type(exc).__name__}: {exc}"
        ) from exc
    if len(vector) != 384 or any(not math.isfinite(value) for value in vector):
        raise DiagnosticExecutorError("embedder prewarm vector is not finite 384-D")
    norm = math.sqrt(math.fsum(value * value for value in vector))
    if not math.isfinite(norm) or abs(norm - 1.0) > 0.00001:
        raise DiagnosticExecutorError("embedder prewarm vector is not normalized")
    document = {
        "schema": EMBEDDER_PREFLIGHT_SCHEMA,
        "status": "PASS_PINNED_FINITE_NORMALIZED_384D",
        "probe_sha256": hashlib.sha256(EMBEDDER_PROBE.encode("utf-8")).hexdigest(),
        "dimensions": len(vector),
        "l2_norm": format(norm, ".12f"),
        "vector_sha256": _canonical_hash([format(value, ".17g") for value in vector]),
        "provenance": provenance,
        "model_calls": 0,
        "paid_model_calls": 0,
        "official_grader_runs": 0,
    }
    if evidence_path.exists():
        if not resume:
            raise DiagnosticExecutorError(
                "embedder preflight evidence exists without --resume"
            )
        if diagnostic.canonical_bytes(
            _read_exact_json(evidence_path, "embedder preflight")
        ) != diagnostic.canonical_bytes(document):
            raise DiagnosticExecutorError("embedder preflight resume evidence drift")
    else:
        _atomic_write_json(evidence_path, document)
    return hashlib.sha256(evidence_path.read_bytes()).hexdigest()


def rehearse_production_retrieval(
    *,
    contract: ExecutionContract,
    requests: Sequence[Mapping[str, Any]],
    tasks_by_target_id: Mapping[str, Any],
    repository_root: Path,
    payload_bytes: Mapping[str, bytes],
    retrieval_config: Any,
    embedder: Any,
    embedder_preflight_sha256: str,
    retrieval_policy_raw_sha256: str,
    evidence_path: Path,
    resume: bool,
    retriever_factory: Optional[Callable[..., Any]] = None,
) -> str:
    """Exercise the exact diagnostic reader route before any paid gateway.

    The constant embedder probe proves that the pinned model can load, but it
    cannot prove that the committed source-bank projection, safe-pool gates,
    selected retrieval configuration, graph ranker and injection serializer
    compose successfully.  This rehearsal executes that complete route for
    every frozen target using a disposable pathless node.  It never invokes a
    coding model or grader and never mutates a lifecycle memory bank.
    """

    from enterprise_memory.trimem.retrieval import (
        RetrievalSessionState,
        TriMemoryRetriever,
    )
    from enterprise_memory.trimem.working_graph import (
        ShortTermWorkingGraph,
        SubtaskSpec,
    )

    _validate_contract_object(contract)
    embedder_digest = _require_sha256(
        embedder_preflight_sha256, "embedder preflight hash"
    )
    policy_digest = _require_sha256(
        retrieval_policy_raw_sha256, "retrieval policy raw hash"
    )
    if len(requests) != 36:
        raise DiagnosticExecutorError(
            "production retrieval rehearsal requires the exact 36-cell plan"
        )
    targets = list(contract.manifest["targets"])
    if len(targets) != 12 or set(tasks_by_target_id) != {
        str(target["target_id"]) for target in targets
    }:
        raise DiagnosticExecutorError(
            "production retrieval rehearsal task set differs from frozen DEV"
        )
    factory = retriever_factory or TriMemoryRetriever
    current_manifest: Optional[dict[str, Any]] = None
    forced_manifest: Optional[dict[str, Any]] = None
    target_rows: list[dict[str, Any]] = []

    def active_graph(task: Any) -> Any:
        objective = "apply a verified historical repository repair safely"
        graph = ShortTermWorkingGraph(
            task.task_id, objective, task.repository
        )
        node = graph.add_subtask(
            SubtaskSpec(
                node_id="SOURCE_BANK_RETRIEVAL_REHEARSAL",
                objective=objective,
                operation="validate source repair evidence against current code",
                files=(),
                required_memory_facets=(),
            )
        )
        graph.activate(node.node_id)
        return graph

    try:
        for offset, target in enumerate(targets):
            target_id = str(target["target_id"])
            task = tasks_by_target_id[target_id]
            c1_request = requests[12 + offset]
            c2_request = requests[24 + offset]
            if (
                c1_request.get("target_id") != target_id
                or c1_request.get("arm_id") != "C1"
                or c2_request.get("target_id") != target_id
                or c2_request.get("arm_id") != "C2"
            ):
                raise DiagnosticExecutorError(
                    "production retrieval rehearsal request order drift"
                )
            c1_store = ManifestBackedDiagnosticSourceBankStore(
                contract=contract,
                request=c1_request,
                task=task,
                repository_root=repository_root,
                payload_bytes=payload_bytes,
            )
            c2_store = ManifestBackedDiagnosticSourceBankStore(
                contract=contract,
                request=c2_request,
                task=task,
                repository_root=repository_root,
                payload_bytes=payload_bytes,
            )
            if (
                c1_store.content_hash != c2_store.content_hash
                or c1_store.execution_views != c2_store.execution_views
                or len(c2_store.execution_views) != 1
            ):
                raise DiagnosticExecutorError(
                    "production retrieval rehearsal source projection drift"
                )
            expected_memory_id = next(iter(c2_store.execution_views))
            expected_bytes = c2_store.execution_views[expected_memory_id]

            c1_retriever = factory(
                c1_store,
                retrieval_config,
                embedder=embedder,
                selection_mode="CURRENT_GATE",
                diagnostic_telemetry=True,
                require_safe_pool_metadata=True,
            )
            c2_retriever = factory(
                c2_store,
                retrieval_config,
                embedder=embedder,
                selection_mode="FORCED_SAFE_TOP1",
                diagnostic_telemetry=True,
                require_safe_pool_metadata=True,
            )
            observed_current_manifest = _json_copy(c1_retriever.manifest())
            observed_forced_manifest = _json_copy(c2_retriever.manifest())
            if current_manifest is None:
                current_manifest = observed_current_manifest
                forced_manifest = observed_forced_manifest
            elif (
                diagnostic.canonical_bytes(current_manifest)
                != diagnostic.canonical_bytes(observed_current_manifest)
                or diagnostic.canonical_bytes(forced_manifest)
                != diagnostic.canonical_bytes(observed_forced_manifest)
            ):
                raise DiagnosticExecutorError(
                    "production retrieval rehearsal reader manifest drift"
                )

            c1_decision = c1_retriever.recall(
                active_graph(task),
                RetrievalSessionState(task.task_id),
                user_id=task.user_id,
                org_id=task.org_id,
                repository=task.repository,
                now=None,
            )
            c2_decision = c2_retriever.recall(
                active_graph(task),
                RetrievalSessionState(task.task_id),
                user_id=task.user_id,
                org_id=task.org_id,
                repository=task.repository,
                now=None,
            )
            c1_rows = [
                dict(row)
                for row in c1_decision.decision_telemetry
                if row.get("bank_type") == "ORG_SEMANTIC"
            ]
            c2_rows = [
                dict(row)
                for row in c2_decision.decision_telemetry
                if row.get("bank_type") == "ORG_SEMANTIC"
            ]
            if len(c1_rows) != 1 or len(c2_rows) != 1:
                raise DiagnosticExecutorError(
                    "production retrieval rehearsal lacks one ORG_SEMANTIC decision"
                )
            c1_row, c2_row = c1_rows[0], c2_rows[0]
            if (
                c1_row.get("candidate_count_before_filter") != 1
                or c1_row.get("candidate_count_after_filter") != 1
                or c1_row.get("top_candidate_id") != expected_memory_id
                or c1_row.get("final_reason_code")
                not in {
                    "INJECTED",
                    "BELOW_CONFIDENCE_THRESHOLD",
                    "BELOW_MARGIN_THRESHOLD",
                    "NO_SEED_MATCH",
                }
            ):
                raise DiagnosticExecutorError(
                    "CURRENT_GATE production retrieval rehearsal is not a known outcome"
                )
            if (
                c2_row.get("candidate_count_before_filter") != 1
                or c2_row.get("candidate_count_after_filter") != 1
                or c2_row.get("top_candidate_id") != expected_memory_id
                or c2_row.get("final_reason_code") != "INJECTED"
                or len(c2_decision.injections) != 1
            ):
                raise DiagnosticExecutorError(
                    "FORCED_SAFE_TOP1 production retrieval rehearsal did not inject"
                )
            injection = c2_decision.injections[0]
            if (
                injection.memory_id != expected_memory_id
                or injection.exact_utf8 != expected_bytes
                or injection.exact_text.encode("utf-8") != expected_bytes
                or injection.byte_count != len(expected_bytes)
                or injection.sha256 != hashlib.sha256(expected_bytes).hexdigest()
                or not injection.verify()
            ):
                raise DiagnosticExecutorError(
                    "production retrieval rehearsal injection bytes/hash drift"
                )
            if c1_decision.injections:
                if (
                    len(c1_decision.injections) != 1
                    or c1_decision.injections[0].exact_utf8 != expected_bytes
                ):
                    raise DiagnosticExecutorError(
                        "CURRENT_GATE production rehearsal injection bytes differ"
                    )
            target_rows.append(
                {
                    "target_id": target_id,
                    "candidate_memory_id": expected_memory_id,
                    "source_store_content_hash": c2_store.content_hash,
                    "execution_view_sha256": hashlib.sha256(
                        expected_bytes
                    ).hexdigest(),
                    "execution_view_bytes": len(expected_bytes),
                    "current_gate": c1_row,
                    "forced_safe_top1": c2_row,
                    "forced_injection_sha256": injection.sha256,
                    "forced_injection_bytes": injection.byte_count,
                    "c1_c2_source_bytes_identical": True,
                }
            )
    except DiagnosticExecutorError:
        raise
    except Exception as exc:
        raise DiagnosticExecutorError(
            "production retrieval rehearsal failed before spend: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    document = {
        "schema": RETRIEVAL_REHEARSAL_SCHEMA,
        "status": "PASS_ALL_12_EXACT_READER_ROUTES",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
        "source_bank_snapshot_sha256": contract.source_bank_snapshot_sha256,
        "retrieval_policy_raw_sha256": policy_digest,
        "embedder_preflight_sha256": embedder_digest,
        "embedder_provenance": _json_copy(embedder.provenance()),
        "current_gate_retriever_manifest": current_manifest,
        "forced_safe_top1_retriever_manifest": forced_manifest,
        "target_count": len(target_rows),
        "targets": target_rows,
        "model_calls": 0,
        "paid_model_calls": 0,
        "official_grader_runs": 0,
    }
    if evidence_path.exists():
        if not resume:
            raise DiagnosticExecutorError(
                "retrieval rehearsal evidence exists without --resume"
            )
        if diagnostic.canonical_bytes(
            _read_exact_json(evidence_path, "retrieval rehearsal")
        ) != diagnostic.canonical_bytes(document):
            raise DiagnosticExecutorError(
                "retrieval rehearsal resume evidence drift"
            )
    else:
        _atomic_write_json(evidence_path, document)
    return hashlib.sha256(evidence_path.read_bytes()).hexdigest()


def _read_exact_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return diagnostic.strict_json_load(path)
    except (diagnostic.DiagnosticContractError, OSError) as exc:
        raise DiagnosticExecutorError(f"{label} is unreadable: {exc}") from exc


def _cell_paths(output_root: Path, cell_index: int) -> tuple[Path, Path, Path]:
    directory = output_root / "cells" / f"{cell_index:02d}"
    return directory, directory / "intent.json", directory / "result.json"


def _execution_binding(
    *,
    contract: ExecutionContract,
    capabilities: Mapping[str, Any],
    execution_identity_sha256: str,
    requests: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": EXECUTION_BINDING_SCHEMA,
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "execution_identity_sha256": execution_identity_sha256,
        "matrix_raw_sha256": contract.matrix_raw_sha256,
        "policy_raw_sha256": contract.policy_raw_sha256,
        "source_bank_manifest_sha256": contract.source_bank_manifest_sha256,
        "source_bank_snapshot_sha256": contract.source_bank_snapshot_sha256,
        "approved_hard_caps_sha256": _canonical_hash(
            contract.policy["hard_caps"]
        ),
        "cell_request_sequence_sha256": _canonical_hash(list(requests)),
        "cell_count": 36,
        "serial_execution": True,
        "executor_capabilities": _json_copy(capabilities),
        "executor_capabilities_sha256": _canonical_hash(capabilities),
    }


def initialize_execution_binding(
    *,
    contract: ExecutionContract,
    capabilities: Mapping[str, Any],
    output_root: Path,
    execution_identity_sha256: str,
    resume: bool,
    allow_test_executor: bool = False,
) -> Mapping[str, Any]:
    """Atomically establish approval/plan identity before any preparation."""

    identity = _require_sha256(execution_identity_sha256, "execution identity")
    accepted = _validate_capabilities(
        capabilities, allow_test_executor=allow_test_executor
    )
    requests = build_cell_requests(
        contract, execution_identity_sha256=identity
    )
    binding = _execution_binding(
        contract=contract,
        capabilities=accepted,
        execution_identity_sha256=identity,
        requests=requests,
    )
    path = output_root / "execution-binding.json"
    if path.exists():
        if not resume:
            raise DiagnosticExecutorError(
                "execution binding already exists without --resume"
            )
        observed = _read_exact_json(path, "execution binding")
        if diagnostic.canonical_bytes(observed) != diagnostic.canonical_bytes(binding):
            raise DiagnosticExecutorError("resume execution binding drift")
    else:
        if resume:
            raise DiagnosticExecutorError(
                "resume requested without an execution binding"
            )
        if output_root.exists() and any(output_root.iterdir()):
            raise DiagnosticExecutorError(
                "fresh execution output directory is not empty"
            )
        _atomic_write_json(path, binding)
    return MappingProxyType(binding)


def _validate_cell_result(
    cell: Mapping[str, Any],
    request: Mapping[str, Any],
    *,
    source_bank_sha256: str,
) -> dict[str, Any]:
    if not isinstance(cell, Mapping):
        raise DiagnosticExecutorError("cell executor did not return an object")
    result = _json_copy(cell)
    expected = {
        key: request[key]
        for key in (
            "arm_id",
            "cell_id",
            "cell_index",
            "target_id",
            "target_order_index",
        )
    }
    try:
        diagnostic._validate_cell(  # noqa: SLF001 - same-script contract boundary
            result,
            expected,
            source_bank_sha256=source_bank_sha256,
        )
    except diagnostic.DiagnosticContractError as exc:
        raise DiagnosticExecutorError(f"cell result failed diagnostic contract: {exc}") from exc
    if result.get("diagnostic_id") != request.get("diagnostic_id"):
        raise DiagnosticExecutorError("cell result diagnostic identity drift")
    if result["accounting"]["grader_calls"] != 1:
        raise DiagnosticExecutorError("cell has no authoritative grader lifecycle")
    return result


def execute_diagnostic(
    *,
    contract: ExecutionContract,
    executor: CellExecutor,
    output_root: Path,
    execution_identity_sha256: str,
    resume: bool = False,
    allow_test_executor: bool = False,
    preinitialized_binding: bool = False,
) -> ExecutionOutcome:
    """Execute/continue an exact serial matrix through a one-cell backend.

    A backend exception is an infrastructure stop, not an unresolved scientific
    cell.  To continue after an individual model failure the backend must still
    return a complete cell containing the partial/no-op official grader result.
    """

    requests = build_cell_requests(
        contract, execution_identity_sha256=execution_identity_sha256
    )
    capabilities = _validate_capabilities(
        executor.capabilities(), allow_test_executor=allow_test_executor
    )
    binding = _execution_binding(
        contract=contract,
        capabilities=capabilities,
        execution_identity_sha256=execution_identity_sha256,
        requests=requests,
    )
    binding_path = output_root / "execution-binding.json"
    if preinitialized_binding:
        if not binding_path.is_file() or diagnostic.canonical_bytes(
            _read_exact_json(binding_path, "execution binding")
        ) != diagnostic.canonical_bytes(binding):
            raise DiagnosticExecutorError("preinitialized execution binding differs")
    else:
        initialize_execution_binding(
            contract=contract,
            capabilities=capabilities,
            output_root=output_root,
            execution_identity_sha256=execution_identity_sha256,
            resume=resume,
            allow_test_executor=allow_test_executor,
        )

    cells: list[dict[str, Any]] = []
    resumed_cells = 0
    for request in requests:
        cell_index = int(request["cell_index"])
        cell_root, intent_path, result_path = _cell_paths(output_root, cell_index)
        request_hash = _canonical_hash(request)
        intent = {
            "schema": INTENT_SCHEMA,
            "cell_id": request["cell_id"],
            "cell_index": cell_index,
            "request_sha256": request_hash,
            "request": _json_copy(request),
        }
        existing_intent = intent_path.exists()
        if existing_intent:
            if not resume:
                raise DiagnosticExecutorError("cell intent exists without --resume")
            if diagnostic.canonical_bytes(_read_exact_json(intent_path, "cell intent")) != diagnostic.canonical_bytes(intent):
                raise DiagnosticExecutorError("cell intent/request binding drift")
        else:
            if result_path.exists():
                raise DiagnosticExecutorError("cell result exists without its intent")
            _atomic_write_json(intent_path, intent)

        if result_path.exists():
            if not resume:
                raise DiagnosticExecutorError("cell result exists without --resume")
            journal = _read_exact_json(result_path, "cell result journal")
            if set(journal) != {
                "schema", "cell_id", "cell_index", "request_sha256",
                "cell_sha256", "cell",
            } or journal.get("schema") != RESULT_JOURNAL_SCHEMA:
                raise DiagnosticExecutorError("cell result journal field-set drift")
            if (
                journal.get("cell_id") != request["cell_id"]
                or journal.get("cell_index") != cell_index
                or journal.get("request_sha256") != request_hash
                or journal.get("cell_sha256") != _canonical_hash(journal.get("cell"))
            ):
                raise DiagnosticExecutorError("cell result journal binding drift")
            cell = _validate_cell_result(
                journal["cell"],
                request,
                source_bank_sha256=contract.source_bank_manifest_sha256,
            )
            resumed_cells += 1
        else:
            try:
                produced = executor.execute_cell(
                    MappingProxyType(_json_copy(request)),
                    resume=existing_intent,
                    journal_root=cell_root / "backend",
                )
            except BaseException as exc:
                raise DiagnosticExecutorError(
                    f"cell backend stopped before an official terminal result: {request['cell_id']}: {exc}"
                ) from exc
            cell = _validate_cell_result(
                produced,
                request,
                source_bank_sha256=contract.source_bank_manifest_sha256,
            )
            journal = {
                "schema": RESULT_JOURNAL_SCHEMA,
                "cell_id": request["cell_id"],
                "cell_index": cell_index,
                "request_sha256": request_hash,
                "cell_sha256": _canonical_hash(cell),
                "cell": cell,
            }
            _atomic_write_json(result_path, journal)
        cells.append(cell)

    result = {
        "schema": "trimem/dev-activation-results/1.0",
        "diagnostic_id": contract.manifest["diagnostic_id"],
        "cells": cells,
    }
    ledger_finalization_sha256: Optional[str] = None
    if capabilities["executor_kind"] == "OFFICIAL_PRODUCTION_CELL":
        finalizer = getattr(executor, "finalize_matrix", None)
        if not callable(finalizer):
            raise DiagnosticExecutorError(
                "production executor has no atomic-ledger finalizer"
            )
        finalization = finalizer(
            requests=requests,
            cells=cells,
            output_root=output_root,
            resume=resume,
        )
        ledger_finalization_sha256 = _require_sha256(
            finalization.get("evidence_sha256")
            if isinstance(finalization, Mapping)
            else None,
            "ledger finalization evidence hash",
        )
        result["atomic_budget_ledger_finalization_sha256"] = (
            ledger_finalization_sha256
        )
    try:
        aggregate = diagnostic.aggregate_results(
            result,
            contract.manifest,
            contract.policy,
            source_bank_sha256=contract.source_bank_manifest_sha256,
        )
    except diagnostic.DiagnosticContractError as exc:
        raise DiagnosticExecutorError(f"complete matrix aggregate failed: {exc}") from exc
    _atomic_write_json(output_root / "results.json", result)
    _atomic_write_json(output_root / "aggregate.json", aggregate)
    return ExecutionOutcome(
        result=MappingProxyType(result),
        aggregate=MappingProxyType(aggregate),
        completed_cell_count=len(cells),
        resumed_cell_count=resumed_cells,
    )


def production_capabilities(executor_id: str) -> dict[str, Any]:
    """Return the exact capability declaration for a reviewed backend."""

    if not isinstance(executor_id, str) or not executor_id:
        raise DiagnosticExecutorError("executor_id is required")
    return {
        "schema": CAPABILITY_SCHEMA,
        "executor_id": executor_id,
        "executor_kind": "OFFICIAL_PRODUCTION_CELL",
        "one_cell_per_invocation": True,
        "durable_resume": True,
        "fresh_namespace_per_cell": True,
        "read_only_source_bank": True,
        "contained_failure_to_official_grader": True,
        "official_grader_required": True,
        "reused_benchmark_primitives": list(REUSABLE_BENCHMARK_PRIMITIVES),
    }


def _add_approval_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--approval-file", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--workflow-event", required=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Approval-gated image preparation and serial production execution CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare-images", help="pull and inspect only frozen diagnostic images"
    )
    _add_approval_cli_arguments(prepare)
    prepare.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(
            "artifacts/trimem_v1/dev_activation_diagnostic/image-materialization"
        ),
    )
    cleanup = commands.add_parser(
        "cleanup-images",
        help="remove only image aliases proven by the materialization report",
    )
    cleanup.add_argument(
        "--image-materialization-report",
        type=Path,
        default=Path(
            "artifacts/trimem_v1/dev_activation_diagnostic/"
            "image-materialization/report.json"
        ),
    )
    rehearse = commands.add_parser(
        "rehearse-solver-sandboxes",
        help="run exact 12 already-materialized solver sandboxes without secrets",
    )
    rehearse.add_argument("--checkout-root", type=Path, required=True)
    rehearse.add_argument("--dataset-cache-root", type=Path, required=True)
    rehearse.add_argument("--evidence-root", type=Path, required=True)
    cleanup.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(
            "artifacts/trimem_v1/dev_activation_diagnostic/image-cleanup"
        ),
    )
    execute = commands.add_parser(
        "execute", help="run the exact 36-cell model/grader diagnostic"
    )
    _add_approval_cli_arguments(execute)
    execute.add_argument("--output-root", type=Path, required=True)
    execute.add_argument(
        "--dataset-cache-root", type=Path, default=Path(".trimem-exec/datasets")
    )
    execute.add_argument(
        "--harness-root", type=Path, default=Path(".trimem-exec/harnesses")
    )
    execute.add_argument(
        "--workspace-root",
        type=Path,
        default=Path(".trimem-exec/devdiag-workspaces"),
    )
    execute.add_argument(
        "--loader-preflight",
        type=Path,
        default=Path(
            "artifacts/trimem_v1/benchmark_exec/control/"
            "official-harness-loader-preflight.json"
        ),
    )
    execute.add_argument(
        "--image-materialization-report",
        type=Path,
        default=Path(
            "artifacts/trimem_v1/dev_activation_diagnostic/"
            "image-materialization/report.json"
        ),
    )
    execute.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        contract = load_execution_contract(ROOT, require_tracked=True)
        if args.command == "rehearse-solver-sandboxes":
            report_sha256 = rehearse_existing_dev_solver_sandboxes(
                contract=contract,
                checkout_root=args.checkout_root,
                dataset_cache_root=args.dataset_cache_root,
                evidence_root=args.evidence_root,
            )
            rehearsal_report = _read_exact_json(
                args.evidence_root / "report.json",
                "pre-billing solver sandbox rehearsal",
            )
            raw_image_probe_containers = int(
                rehearsal_report["raw_image_probe_containers"]
            )
            masked_solver_probe_containers = int(
                rehearsal_report["masked_solver_probe_containers"]
            )
            print(
                json.dumps(
                    {
                        "status": "PASS_ALL_12_PRE_BILLING_SOLVER_SANDBOXES",
                        "report_sha256": report_sha256,
                        "image_config_inspection_attempts": int(
                            rehearsal_report["image_config_inspection_attempts"]
                        ),
                        "image_config_inspections": int(
                            rehearsal_report["image_config_inspections"]
                        ),
                        "raw_image_probe_attempts": int(
                            rehearsal_report["raw_image_probe_attempts"]
                        ),
                        "raw_image_probe_containers": raw_image_probe_containers,
                        "masked_solver_probe_attempts": int(
                            rehearsal_report["masked_solver_probe_attempts"]
                        ),
                        "masked_solver_probe_containers": (
                            masked_solver_probe_containers
                        ),
                        "non_grader_probe_containers": (
                            raw_image_probe_containers
                            + masked_solver_probe_containers
                        ),
                        "model_calls": 0,
                        "paid_model_calls": 0,
                        "official_grader_runs": 0,
                        "total_usd": "0.000000000000",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "cleanup-images":
            report = cleanup_diagnostic_images(
                contract=contract,
                image_materialization_report=args.image_materialization_report,
                evidence_root=args.evidence_root,
            )
            print(
                json.dumps(
                    {
                        "status": "DIAGNOSTIC_IMAGE_CLEANUP_PASS",
                        "images": report["image_count"],
                        "model_calls": 0,
                        "official_grader_runs": 0,
                        "paid_model_calls": 0,
                        "total_usd": "0.000000000000",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        approval, approval_digest = load_and_validate_materialized_approval(
            contract=contract,
            approval_path=args.approval_file,
            repository=args.repository,
            workflow_run_id=args.workflow_run_id,
            workflow_run_attempt=args.workflow_run_attempt,
            workflow_event=args.workflow_event,
            verify_openai_credential=args.command == "execute",
        )
        if args.command == "prepare-images":
            report = materialize_diagnostic_images(
                contract=contract,
                approval_artifact_sha256=approval_digest,
                evidence_root=args.evidence_root,
            )
            output = {
                "status": "DIAGNOSTIC_IMAGE_MATERIALIZATION_PASS",
                "approval_artifact_sha256": approval_digest,
                "images": report["image_count"],
                "model_calls": 0,
                "official_grader_runs": 0,
                "paid_model_calls": 0,
                "total_usd": "0.000000000000",
            }
        else:
            production_identity = production_capabilities(
                "trimem-dev-activation-official-cell-v1"
            )
            initialize_execution_binding(
                contract=contract,
                capabilities=production_identity,
                output_root=_require_repository_subpath(
                    ROOT, args.output_root, "output root"
                ),
                execution_identity_sha256=approval_digest,
                resume=args.resume,
            )
            prepared = prepare_official_production_execution(
                contract=contract,
                approval=approval,
                approval_artifact_sha256=approval_digest,
                output_root=args.output_root,
                dataset_cache_root=args.dataset_cache_root,
                harness_root=args.harness_root,
                loader_preflight_path=args.loader_preflight,
                image_materialization_report=args.image_materialization_report,
                workspace_root=args.workspace_root,
                resume=args.resume,
            )
            outcome = execute_diagnostic(
                contract=contract,
                executor=prepared.executor,
                output_root=_require_repository_subpath(
                    ROOT, args.output_root, "output root"
                ),
                execution_identity_sha256=prepared.execution_identity_sha256,
                resume=args.resume,
                preinitialized_binding=True,
            )
            output = {
                "status": outcome.aggregate["status"],
                "approval_artifact_sha256": approval_digest,
                "completed_cells": outcome.completed_cell_count,
                "resumed_cells": outcome.resumed_cell_count,
                "results_path": str(
                    args.output_root / "results.json"
                ).replace("\\", "/"),
                "aggregate_path": str(
                    args.output_root / "aggregate.json"
                ).replace("\\", "/"),
            }
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED",
                    "reason": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


__all__ = [
    "ARM_BINDINGS",
    "CAPABILITY_SCHEMA",
    "CellExecutor",
    "DiagnosticExecutorError",
    "DiagnosticAtomicBudgetLedger",
    "ExecutionContract",
    "ExecutionOutcome",
    "OfficialProductionCellExecutor",
    "PreparedProductionExecution",
    "REUSABLE_BENCHMARK_PRIMITIVES",
    "build_cell_requests",
    "cleanup_diagnostic_images",
    "execute_diagnostic",
    "initialize_execution_binding",
    "load_and_validate_materialized_approval",
    "load_execution_contract",
    "materialize_diagnostic_images",
    "prewarm_production_embedder",
    "prepare_official_production_execution",
    "production_capabilities",
    "rehearse_production_retrieval",
    "rehearse_production_solver_sandbox",
    "rehearse_existing_dev_solver_sandboxes",
    "reinspect_diagnostic_images",
    "validate_diagnostic_image_materialization",
]


if __name__ == "__main__":
    raise SystemExit(main())
