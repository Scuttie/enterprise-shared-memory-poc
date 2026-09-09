"""Crash-safe checkpoints for the iterative TriMem coding-agent runtime."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional

from .accounting import (
    RunAccounting,
    canonical_bytes,
    sha256_bytes,
    strict_json_loads,
    utc_now,
)
from .retrieval import RecallError, normalize_recall_decision_telemetry


@dataclass(frozen=True)
class RuntimeCheckpoint:
    run_id: str
    task_id: str
    arm: str
    generation: int
    next_step_no: int
    state: str
    active_node_id: Optional[str]
    graph_snapshot: Mapping[str, Any]
    workspace_state: Mapping[str, Any]
    injected_memory_ids: tuple[str, ...]
    injected_bytes: int
    injection_ledger: tuple[Mapping[str, Any], ...]
    tool_history: tuple[Mapping[str, Any], ...]
    completed_call_ids: tuple[str, ...]
    accounting: Mapping[str, Any]
    config_hashes: Mapping[str, str]
    evidence_event_hash: str
    memory_controller_state: Mapping[str, Any] = field(default_factory=dict)
    lifecycle_state: Mapping[str, Any] = field(default_factory=dict)
    terminal_payload: Mapping[str, Any] = field(default_factory=dict)
    pending_policy_transition: Optional[Mapping[str, Any]] = None
    prepared_request: Optional[Mapping[str, Any]] = None
    previous_checkpoint_hash: str = "0" * 64
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.generation < 1 or self.next_step_no < 1:
            raise ValueError("checkpoint generation and next step must be positive")
        if self.injected_bytes < 0 or len(self.injected_memory_ids) > 3:
            raise ValueError("invalid injection state")
        for name, value in {
            "evidence_event_hash": self.evidence_event_hash,
            "previous_checkpoint_hash": self.previous_checkpoint_hash,
            **dict(self.config_hashes),
        }.items():
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} is not a sha256 digest")
        terminal_recall_decisions = self.terminal_payload.get("recall_decisions")
        normalized_terminal_decisions: dict[str, Mapping[str, Any]] = {}
        if terminal_recall_decisions is not None:
            if not isinstance(terminal_recall_decisions, list):
                raise ValueError("checkpoint recall telemetry is malformed")
            try:
                for raw in terminal_recall_decisions:
                    row = normalize_recall_decision_telemetry(
                        raw, expected_target_id=self.task_id
                    )
                    attempt_id = str(row["recall_attempt_id"])
                    if attempt_id in normalized_terminal_decisions:
                        raise RecallError("duplicate recall_attempt_id")
                    normalized_terminal_decisions[attempt_id] = row
            except RecallError as exc:
                raise ValueError("checkpoint recall telemetry is malformed") from exc
        if self.state == "DECOMPOSE_PREPARED":
            if not isinstance(self.prepared_request, Mapping):
                raise ValueError(
                    "DECOMPOSE_PREPARED requires a prepared request binding"
                )
            if (
                self.generation != 1
                or self.next_step_no != 1
                or self.previous_checkpoint_hash != "0" * 64
                or self.evidence_event_hash == "0" * 64
                or self.active_node_id is not None
                or self.injected_memory_ids
                or self.injected_bytes != 0
                or self.injection_ledger
                or self.tool_history
                or self.completed_call_ids
                or canonical_bytes(self.accounting)
                != canonical_bytes(RunAccounting().to_dict())
                or self.terminal_payload
                or self.pending_policy_transition is not None
            ):
                raise ValueError(
                    "DECOMPOSE_PREPARED requires pristine pre-model state"
                )
            required = {
                "schema", "run_id", "task_id", "arm", "active_node_id",
                "next_step_no", "request_step_no", "logical_call_id", "prompt_sha256",
                "request_sha256", "max_output_tokens",
            }
            if set(self.prepared_request) != required:
                raise ValueError("decomposition request binding shape differs")
            if (
                self.prepared_request.get("schema")
                != "trimem/decompose-prepared-request/1.0"
                or self.prepared_request.get("run_id") != self.run_id
                or self.prepared_request.get("task_id") != self.task_id
                or self.prepared_request.get("arm") != self.arm
                or self.prepared_request.get("active_node_id") is not None
                or self.active_node_id is not None
                or self.prepared_request.get("next_step_no") != self.next_step_no
                or self.prepared_request.get("request_step_no") != 0
                or self.prepared_request.get("logical_call_id")
                != f"{self.task_id}:{self.arm}:decompose:0001"
                or type(self.prepared_request.get("max_output_tokens")) is not int
                or self.prepared_request["max_output_tokens"] <= 0
            ):
                raise ValueError(
                    "decomposition request identity differs from checkpoint"
                )
            for name in ("prompt_sha256", "request_sha256"):
                value = self.prepared_request.get(name)
                if (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(ch not in "0123456789abcdef" for ch in value)
                ):
                    raise ValueError(
                        f"decomposition request {name} is not a sha256 digest"
                    )
        elif self.state == "RECALL_PREPARED":
            if not isinstance(self.prepared_request, Mapping):
                raise ValueError("RECALL_PREPARED requires a prepared request binding")
            required = {
                "run_id", "task_id", "arm", "active_node_id", "next_step_no",
                "logical_call_id", "recall_decision", "recall_decision_sha256",
                "memory_injection_sha256", "projection_sha256",
                "prompt_sha256", "request_sha256", "projection_record",
            }
            if set(self.prepared_request) != required:
                raise ValueError("prepared request binding shape differs")
            if (
                self.prepared_request.get("run_id") != self.run_id
                or self.prepared_request.get("task_id") != self.task_id
                or self.prepared_request.get("arm") != self.arm
                or self.prepared_request.get("active_node_id") != self.active_node_id
                or self.prepared_request.get("next_step_no") != self.next_step_no
            ):
                raise ValueError("prepared request identity differs from checkpoint")
            for name in (
                "recall_decision_sha256", "memory_injection_sha256",
                "projection_sha256", "prompt_sha256", "request_sha256",
            ):
                value = self.prepared_request.get(name)
                if (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(ch not in "0123456789abcdef" for ch in value)
                ):
                    raise ValueError(f"prepared request {name} is not a sha256 digest")
            recall_decision = self.prepared_request.get("recall_decision")
            if (
                not isinstance(recall_decision, Mapping)
                or recall_decision.get("task_id") != self.task_id
                or recall_decision.get("arm") != self.arm
                or recall_decision.get("active_node_id") != self.active_node_id
                or not isinstance(recall_decision.get("injections"), list)
                or not isinstance(recall_decision.get("bank_trace"), list)
                or not isinstance(recall_decision.get("rejections"), list)
                or sha256_bytes(canonical_bytes(recall_decision))
                != self.prepared_request.get("recall_decision_sha256")
                or sha256_bytes(canonical_bytes(recall_decision["injections"]))
                != self.prepared_request.get("memory_injection_sha256")
            ):
                raise ValueError("prepared request recall decision differs")
            telemetry = recall_decision.get("decision_telemetry")
            if telemetry is not None:
                if not isinstance(telemetry, list):
                    raise ValueError("prepared recall telemetry is malformed")
                attempts: set[str] = set()
                try:
                    for raw in telemetry:
                        row = normalize_recall_decision_telemetry(
                            raw, expected_target_id=self.task_id
                        )
                        attempt_id = str(row["recall_attempt_id"])
                        if attempt_id in attempts:
                            raise RecallError("duplicate recall_attempt_id")
                        attempts.add(attempt_id)
                        if (
                            attempt_id not in normalized_terminal_decisions
                            or canonical_bytes(normalized_terminal_decisions[attempt_id])
                            != canonical_bytes(row)
                        ):
                            raise RecallError(
                                "prepared recall telemetry is not terminal-bound"
                            )
                except RecallError as exc:
                    raise ValueError(
                        "prepared recall telemetry is malformed"
                    ) from exc
            projection_record = self.prepared_request.get("projection_record")
            if (
                not isinstance(projection_record, Mapping)
                or projection_record.get("projection_sha256")
                != self.prepared_request.get("projection_sha256")
                or projection_record.get("final_prompt_sha256")
                != self.prepared_request.get("prompt_sha256")
            ):
                raise ValueError("prepared request projection record differs")
        elif self.prepared_request is not None:
            raise ValueError(
                "prepared request binding is only valid in a prepared phase"
            )

    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def content_hash(self) -> str:
        return sha256_bytes(canonical_bytes(self.payload()))


class CheckpointMismatch(RuntimeError):
    pass


class FileCheckpointStore:
    """One atomically replaced latest checkpoint with a verified hash sidecar."""

    def __init__(self, directory: os.PathLike[str] | str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _paths(self, run_id: str) -> tuple[Path, Path]:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
        if not safe or safe != run_id:
            raise ValueError("run_id must be a filesystem-safe identifier")
        return self.directory / f"{safe}.json", self.directory / f"{safe}.sha256"

    def save(self, checkpoint: RuntimeCheckpoint) -> str:
        target, digest_path = self._paths(checkpoint.run_id)
        previous = self.load(checkpoint.run_id, required_config_hashes=None) if target.exists() else None
        if previous is not None:
            if checkpoint.generation != previous.generation + 1:
                raise CheckpointMismatch("checkpoint generation must advance exactly once")
            if checkpoint.previous_checkpoint_hash != previous.content_hash:
                raise CheckpointMismatch("checkpoint chain mismatch")
            if checkpoint.next_step_no < previous.next_step_no:
                raise CheckpointMismatch("checkpoint step rollback refused")
        elif checkpoint.previous_checkpoint_hash != "0" * 64:
            raise CheckpointMismatch("first checkpoint has a non-root predecessor")

        raw = canonical_bytes(checkpoint.payload())
        digest = sha256_bytes(raw)
        self._atomic_write(target, raw)
        self._atomic_write(digest_path, (digest + "\n").encode("ascii"))
        return digest

    def load(
        self,
        run_id: str,
        *,
        required_config_hashes: Optional[Mapping[str, str]],
        required_evidence_hash: Optional[str] = None,
    ) -> RuntimeCheckpoint:
        target, digest_path = self._paths(run_id)
        if not target.is_file() or not digest_path.is_file():
            raise FileNotFoundError(run_id)
        raw = target.read_bytes()
        observed = sha256_bytes(raw)
        expected = digest_path.read_text(encoding="ascii").strip()
        if observed != expected:
            raise CheckpointMismatch("checkpoint digest mismatch")
        try:
            payload = strict_json_loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise CheckpointMismatch("checkpoint JSON is not strict/canonical") from exc
        # JSON turns tuples into lists.  Convert fields whose immutability is part of
        # the runtime contract before constructing the dataclass.
        for name in (
            "injected_memory_ids",
            "injection_ledger",
            "tool_history",
            "completed_call_ids",
        ):
            payload[name] = tuple(payload.get(name, ()))
        try:
            checkpoint = RuntimeCheckpoint(**payload)
        except (TypeError, ValueError) as exc:
            raise CheckpointMismatch("checkpoint payload is invalid") from exc
        if required_config_hashes is not None and dict(checkpoint.config_hashes) != dict(required_config_hashes):
            raise CheckpointMismatch("runtime lock changed; resume refused")
        if required_evidence_hash is not None and checkpoint.evidence_event_hash != required_evidence_hash:
            raise CheckpointMismatch("checkpoint does not reference the current evidence tail")
        return checkpoint

    @staticmethod
    def _atomic_write(target: Path, raw: bytes) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
