"""Append-only, content-addressed evidence and exact compute accounting for TriMem.

The benchmark reports distinguish gateway calls from paid calls.  A credential-free
replay still traverses the same call boundary and is therefore counted as a replay
call, while ``paid`` remains false.  Token counts are actual values reported by the
gateway (or measured by a deterministic replay), never budget ceilings.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable, Mapping, Optional


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def strict_json_loads(value: str | bytes | bytearray) -> Any:
    """Decode JSON while rejecting duplicate object keys at every depth."""

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: %s" % key)
            result[key] = item
        return result

    return json.loads(value, object_pairs_hook=reject_duplicates)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CallRecord:
    task_id: str
    arm: str
    step_no: int
    call_kind: str
    logical_call_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    wall_time_ms: int
    prompt_hash: str
    response_hash: str
    active_node_id: Optional[str] = None
    paid: bool = False
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    attempt: int = 1
    status: str = "success"

    def __post_init__(self) -> None:
        if self.call_kind not in {"solve", "decompose", "extract", "consolidate"}:
            raise ValueError("unsupported call_kind")
        for name in (
            "step_no",
            "input_tokens",
            "output_tokens",
            "wall_time_ms",
            "cached_input_tokens",
            "reasoning_tokens",
            "attempt",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.attempt < 1:
            raise ValueError("attempt must be >= 1")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens cannot exceed output_tokens")
        for name in ("prompt_hash", "response_hash"):
            value = getattr(self, name)
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise ValueError(f"{name} must be a lowercase sha256 digest")


@dataclass(frozen=True)
class ToolRecord:
    task_id: str
    arm: str
    step_no: int
    active_node_id: str
    tool_name: str
    request_hash: str
    result_hash: str
    wall_time_ms: int
    status: str


@dataclass(frozen=True)
class GraderRecord:
    task_id: str
    arm: str
    grader_id: str
    container_digest: str
    exit_code: int
    resolved: bool
    wall_time_ms: int
    stdout_hash: str
    stderr_hash: str
    report_hash: str
    official: bool = False
    container_started: bool = False
    status: str = "success"


@dataclass
class RunAccounting:
    """In-memory accounting that serializes without conflating limits and use."""

    calls: list[CallRecord] = field(default_factory=list)
    tools: list[ToolRecord] = field(default_factory=list)
    graders: list[GraderRecord] = field(default_factory=list)

    def add_call(self, record: CallRecord) -> None:
        if any(r.logical_call_id == record.logical_call_id and r.attempt == record.attempt for r in self.calls):
            raise ValueError("duplicate logical call attempt")
        self.calls.append(record)

    def add_tool(self, record: ToolRecord) -> None:
        self.tools.append(record)

    def add_grader(self, record: GraderRecord) -> None:
        self.graders.append(record)

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, dict[str, int]] = {}
        for rec in self.calls:
            bucket = by_kind.setdefault(
                rec.call_kind,
                {
                    "calls": 0,
                    "paid_calls": 0,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                    "wall_time_ms": 0,
                },
            )
            bucket["calls"] += 1
            bucket["paid_calls"] += int(rec.paid)
            bucket["input_tokens"] += rec.input_tokens
            bucket["cached_input_tokens"] += rec.cached_input_tokens
            bucket["output_tokens"] += rec.output_tokens
            bucket["reasoning_tokens"] += rec.reasoning_tokens
            bucket["wall_time_ms"] += rec.wall_time_ms
        return {
            "model_gateway_calls": len(self.calls),
            "paid_model_calls": sum(int(r.paid) for r in self.calls),
            "tool_calls": len(self.tools),
            "grader_calls": len(self.graders),
            "grader_containers": sum(int(r.container_started) for r in self.graders),
            "official_grader_runs": sum(int(r.official and r.container_started) for r in self.graders),
            "by_call_kind": by_kind,
            "actual_input_tokens": sum(r.input_tokens for r in self.calls),
            "actual_cached_input_tokens": sum(r.cached_input_tokens for r in self.calls),
            "actual_output_tokens": sum(r.output_tokens for r in self.calls),
            "actual_reasoning_tokens": sum(r.reasoning_tokens for r in self.calls),
            "actual_model_wall_time_ms": sum(r.wall_time_ms for r in self.calls),
            "actual_tool_wall_time_ms": sum(r.wall_time_ms for r in self.tools),
            "actual_grader_wall_time_ms": sum(r.wall_time_ms for r in self.graders),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": [asdict(x) for x in self.calls],
            "tools": [asdict(x) for x in self.tools],
            "graders": [asdict(x) for x in self.graders],
            "summary": self.summary(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RunAccounting":
        return cls(
            calls=[CallRecord(**x) for x in value.get("calls", [])],
            tools=[ToolRecord(**x) for x in value.get("tools", [])],
            graders=[GraderRecord(**x) for x in value.get("graders", [])],
        )


class RawEvidenceLedger:
    """Hash-chained event ledger plus content-addressed raw blobs.

    Events are flushed and fsynced before control returns.  This makes a checkpoint
    safe to reference the last event hash even when the process crashes later.
    """

    def __init__(
        self,
        root: os.PathLike[str] | str,
        *,
        clock: Callable[[], str] = utc_now,
        events_name: str = "events.jsonl",
    ):
        self.root = Path(root)
        self.blob_dir = self.root / "blobs"
        if Path(events_name).name != events_name or not events_name:
            raise ValueError("events_name must be a basename")
        self.events_path = self.root / events_name
        self._clock = clock
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self._last_hash, self._next_seq = self._inspect_existing()

    def _inspect_existing(self) -> tuple[str, int]:
        if not self.events_path.exists():
            return "0" * 64, 1
        prev = "0" * 64
        seq = 0
        with self.events_path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                envelope = strict_json_loads(line)
                if envelope["sequence"] != seq + 1 or envelope["previous_event_hash"] != prev:
                    raise ValueError("evidence ledger chain is broken")
                body = {k: v for k, v in envelope.items() if k != "event_hash"}
                actual = sha256_bytes(canonical_bytes(body))
                if actual != envelope["event_hash"]:
                    raise ValueError("evidence event hash mismatch")
                prev, seq = actual, envelope["sequence"]
        return prev, seq + 1

    @property
    def last_event_hash(self) -> str:
        return self._last_hash

    @property
    def next_sequence(self) -> int:
        return self._next_seq

    def verified_suffix(self, previous_event_hash: str) -> tuple[Mapping[str, Any], ...]:
        """Return the verified events written after ``previous_event_hash``.

        A runtime checkpoint and the append-only evidence ledger are deliberately
        separate durability domains.  A real process can therefore die after an
        evidence event is fsynced but before the next checkpoint is replaced.
        Exact tail equality would make that valid, hash-linked suffix impossible
        to resume.  This method accepts only a *proven* ancestor (including the
        all-zero root), verifies the whole on-disk chain again, and returns the
        suffix for recovery/audit.  An unrelated or stale hash fails closed.
        """

        if (
            not isinstance(previous_event_hash, str)
            or len(previous_event_hash) != 64
            or any(character not in "0123456789abcdef" for character in previous_event_hash)
        ):
            raise ValueError("evidence prefix hash is not a sha256 digest")

        previous = "0" * 64
        found = previous_event_hash == previous
        suffix: list[Mapping[str, Any]] = []
        sequence = 0
        if self.events_path.exists():
            with self.events_path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    try:
                        envelope = strict_json_loads(line)
                    except json.JSONDecodeError as exc:
                        raise ValueError("evidence ledger contains a partial event") from exc
                    if (
                        not isinstance(envelope, Mapping)
                        or envelope.get("sequence") != sequence + 1
                        or envelope.get("previous_event_hash") != previous
                    ):
                        raise ValueError("evidence ledger chain is broken")
                    body = {key: value for key, value in envelope.items() if key != "event_hash"}
                    actual = sha256_bytes(canonical_bytes(body))
                    if actual != envelope.get("event_hash"):
                        raise ValueError("evidence event hash mismatch")
                    if found:
                        suffix.append(dict(envelope))
                    if actual == previous_event_hash:
                        found = True
                        suffix = []
                    previous = actual
                    sequence += 1

        if not found:
            raise ValueError("checkpoint evidence hash is not an ancestor of the current ledger")
        if previous != self._last_hash or sequence + 1 != self._next_seq:
            raise ValueError("evidence ledger changed outside this runtime")
        return tuple(suffix)

    def put_blob(self, value: bytes | str | Mapping[str, Any] | list[Any]) -> dict[str, Any]:
        if isinstance(value, str):
            raw = value.encode("utf-8")
            media_type = "text/plain; charset=utf-8"
        elif isinstance(value, bytes):
            raw = value
            media_type = "application/octet-stream"
        else:
            raw = canonical_bytes(value)
            media_type = "application/json"
        digest = sha256_bytes(raw)
        target = self.blob_dir / digest
        if target.exists():
            if target.read_bytes() != raw:
                raise RuntimeError("content-address collision")
        else:
            self._atomic_write(target, raw)
        return {"sha256": digest, "bytes": len(raw), "media_type": media_type}

    def append(self, event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not event_type or not isinstance(payload, Mapping):
            raise ValueError("event_type and mapping payload are required")
        body = {
            "sequence": self._next_seq,
            "recorded_at": self._clock(),
            "event_type": event_type,
            "payload": dict(payload),
            "previous_event_hash": self._last_hash,
        }
        event_hash = sha256_bytes(canonical_bytes(body))
        envelope = {**body, "event_hash": event_hash}
        self.root.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_bytes(envelope).decode("utf-8") + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._last_hash = event_hash
        self._next_seq += 1
        return envelope

    def verify(self, required_blob_hashes: Iterable[str] = ()) -> dict[str, Any]:
        last, next_seq = self._inspect_existing()
        required = set(required_blob_hashes)
        if self.events_path.exists():
            with self.events_path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    if line.strip():
                        required.update(
                            _blob_references(strict_json_loads(line).get("payload", {}))
                        )
        invalid_names = sorted(
            digest for digest in required
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)
        )
        if invalid_names:
            raise ValueError(f"invalid evidence blob digests: {invalid_names}")
        missing = sorted(h for h in required if not (self.blob_dir / h).is_file())
        if missing:
            raise ValueError(f"missing evidence blobs: {missing}")
        corrupted = sorted(
            digest for digest in required
            if sha256_bytes((self.blob_dir / digest).read_bytes()) != digest
        )
        if corrupted:
            raise ValueError(f"evidence blob hash mismatch: {corrupted}")
        return {
            "events": next_seq - 1,
            "last_event_hash": last,
            "referenced_blobs": len(required),
            "missing_blobs": [],
            "corrupted_blobs": [],
        }

    @staticmethod
    def _atomic_write(target: Path, raw: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
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


def _blob_references(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        digest = value.get("sha256")
        if (
            isinstance(digest, str)
            and "bytes" in value
            and "media_type" in value
        ):
            found.add(digest)
        for nested in value.values():
            found.update(_blob_references(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(_blob_references(nested))
    return found
