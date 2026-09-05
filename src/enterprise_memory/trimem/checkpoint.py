"""Crash-safe checkpoints for the iterative TriMem coding-agent runtime."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping, Optional

from .accounting import canonical_bytes, sha256_bytes, strict_json_loads, utc_now


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
        checkpoint = RuntimeCheckpoint(**payload)
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
