"""Durable campaign-finalization journal for the official grader smoke.

The journal distinguishes a scientific aggregate rejection from an authority
promotion failure before any result can become campaign-authoritative.  It is
restricted evidence: public failure closure exposes only its recovery-derived
taxonomy and content digests.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

try:  # Support both direct-script and package-style unit-test imports.
    from trimem_atomic_evidence import atomic_write_bytes
except ModuleNotFoundError:  # pragma: no cover - import mode is environment-specific
    from scripts.trimem_atomic_evidence import atomic_write_bytes


SCHEMA = "trimem/grader-smoke-campaign-finalization/1.0"
RELATIVE_PATH = PurePosixPath(
    "restricted-evidence/campaign-finalization-journal.json"
)
EXPECTED_TERMINAL_RECORD_COUNT = 12
SCIENTIFIC_AGGREGATE_REJECTED = "SCIENTIFIC_AGGREGATE_REJECTED"
AUTHORITY_PROMOTION_STARTED = "AUTHORITY_PROMOTION_STARTED"
AUTHORITY_PROMOTION_COMMITTED = "AUTHORITY_PROMOTION_COMMITTED"
STATUSES = frozenset({
    SCIENTIFIC_AGGREGATE_REJECTED,
    AUTHORITY_PROMOTION_STARTED,
    AUTHORITY_PROMOTION_COMMITTED,
})
_HEX64 = frozenset("0123456789abcdef")


class FinalizationJournalError(ValueError):
    """The campaign-finalization journal is malformed or stale."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FinalizationJournalError(message)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FinalizationJournalError("finalization journal is not canonical JSON") from exc


def _file_bytes(value: Any) -> bytes:
    return _canonical(value) + b"\n"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_hex64(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX64 for character in value)
    )


def _strict_object(raw: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise FinalizationJournalError(
                    f"duplicate finalization journal JSON key: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except FinalizationJournalError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalizationJournalError("invalid finalization journal JSON") from exc
    _require(isinstance(value, dict), "finalization journal root is not an object")
    return value


def _terminal_bindings(output_root: Path) -> list[dict[str, Any]]:
    root = output_root.resolve(strict=True)
    _require(root.is_dir() and not root.is_symlink(), "finalization root is not regular")
    paths = sorted(root.glob("**/*.result.json"), key=lambda value: value.as_posix())
    _require(
        len(paths) == EXPECTED_TERMINAL_RECORD_COUNT,
        "finalization journal requires exactly 12 terminal records",
    )
    bindings: list[dict[str, Any]] = []
    targets: list[str] = []
    indexes: list[int] = []
    authorities: list[bool] = []
    for path in paths:
        resolved = path.resolve(strict=True)
        _require(
            root in resolved.parents and resolved.is_file() and not resolved.is_symlink(),
            "finalization terminal path escaped its root",
        )
        relative = PurePosixPath(resolved.relative_to(root).as_posix())
        raw = resolved.read_bytes()
        value = _strict_object(raw)
        target_id = value.get("target_id")
        order_index = value.get("order_index")
        authority = value.get("authoritative_cell")
        _require(
            isinstance(target_id, str)
            and bool(target_id)
            and type(order_index) is int
            and 0 <= order_index < EXPECTED_TERMINAL_RECORD_COUNT
            and type(authority) is bool,
            "finalization terminal identity/authority is malformed",
        )
        targets.append(target_id)
        indexes.append(order_index)
        authorities.append(authority)
        bindings.append({
            "order_index": order_index,
            "target_id": target_id,
            "relative_path": relative.as_posix(),
            "raw_bytes": len(raw),
            "raw_sha256": _sha256(raw),
        })
    bindings.sort(key=lambda value: value["order_index"])
    _require(
        len(targets) == len(set(targets))
        and sorted(indexes) == list(range(EXPECTED_TERMINAL_RECORD_COUNT))
        and len(set(authorities)) == 1,
        "finalization terminal set is duplicated, missing, or mixed-authority",
    )
    return bindings


def _status_contract(status: str) -> tuple[bool, str | None]:
    _require(status in STATUSES, "unknown finalization journal status")
    if status == SCIENTIFIC_AGGREGATE_REJECTED:
        return False, "aggregate_failures"
    if status == AUTHORITY_PROMOTION_STARTED:
        return False, "infrastructure_failures"
    return True, None


def build_finalization_journal(
    output_root: Path,
    *,
    status: str,
    failures: Sequence[str] = (),
) -> dict[str, Any]:
    expected_authority, taxonomy = _status_contract(status)
    _require(
        all(isinstance(value, str) and bool(value) for value in failures),
        "finalization failure list is malformed",
    )
    if status == SCIENTIFIC_AGGREGATE_REJECTED:
        _require(bool(failures), "scientific rejection requires failures")
    else:
        _require(not failures, "authority promotion journal cannot contain failures")
    bindings = _terminal_bindings(output_root)
    observed_authorities: list[bool] = []
    root = output_root.resolve(strict=True)
    for binding in bindings:
        raw = root.joinpath(*PurePosixPath(binding["relative_path"]).parts).read_bytes()
        observed_authorities.append(
            bool(_strict_object(raw)["authoritative_cell"])
        )
    _require(
        all(value is expected_authority for value in observed_authorities),
        "finalization journal status/terminal authority mismatch",
    )
    failure_digest = _sha256(_canonical(list(failures))) if failures else None
    payload = {
        "schema": SCHEMA,
        "status": status,
        "failure_taxonomy": taxonomy,
        "failure_count": len(failures),
        "failure_set_sha256": failure_digest,
        "terminal_authority": expected_authority,
        "expected_terminal_record_count": EXPECTED_TERMINAL_RECORD_COUNT,
        "terminal_record_count": len(bindings),
        "records": bindings,
    }
    return {**payload, "payload_sha256": _sha256(_canonical(payload))}


def validate_finalization_journal(
    value: Any,
    *,
    output_root: Path | None = None,
) -> dict[str, Any]:
    fields = {
        "schema",
        "status",
        "failure_taxonomy",
        "failure_count",
        "failure_set_sha256",
        "terminal_authority",
        "expected_terminal_record_count",
        "terminal_record_count",
        "records",
        "payload_sha256",
    }
    _require(
        isinstance(value, dict) and set(value) == fields,
        "finalization journal fields differ",
    )
    status = value.get("status")
    expected_authority, taxonomy = _status_contract(status)
    failure_count = value.get("failure_count")
    records = value.get("records")
    _require(
        value.get("schema") == SCHEMA
        and value.get("failure_taxonomy") == taxonomy
        and type(failure_count) is int
        and failure_count >= 0
        and (
            (failure_count > 0 and _is_hex64(value.get("failure_set_sha256")))
            or (failure_count == 0 and value.get("failure_set_sha256") is None)
        )
        and value.get("terminal_authority") is expected_authority
        and value.get("expected_terminal_record_count")
        == EXPECTED_TERMINAL_RECORD_COUNT
        and value.get("terminal_record_count") == EXPECTED_TERMINAL_RECORD_COUNT
        and isinstance(records, list)
        and len(records) == EXPECTED_TERMINAL_RECORD_COUNT,
        "finalization journal state differs",
    )
    _require(
        (status == SCIENTIFIC_AGGREGATE_REJECTED and failure_count > 0)
        or (status != SCIENTIFIC_AGGREGATE_REJECTED and failure_count == 0),
        "finalization journal failure count/status differs",
    )
    record_fields = {
        "order_index",
        "target_id",
        "relative_path",
        "raw_bytes",
        "raw_sha256",
    }
    for index, binding in enumerate(records):
        relative = binding.get("relative_path") if isinstance(binding, dict) else None
        _require(
            isinstance(binding, dict)
            and set(binding) == record_fields
            and binding.get("order_index") == index
            and isinstance(binding.get("target_id"), str)
            and bool(binding["target_id"])
            and isinstance(relative, str)
            and bool(relative)
            and PurePosixPath(relative).as_posix() == relative
            and not PurePosixPath(relative).is_absolute()
            and ".." not in PurePosixPath(relative).parts
            and type(binding.get("raw_bytes")) is int
            and binding["raw_bytes"] > 0
            and _is_hex64(binding.get("raw_sha256")),
            f"finalization journal terminal binding is malformed: {index}",
        )
    payload = {key: child for key, child in value.items() if key != "payload_sha256"}
    _require(
        _is_hex64(value.get("payload_sha256"))
        and value["payload_sha256"] == _sha256(_canonical(payload)),
        "finalization journal seal differs",
    )
    if output_root is not None:
        observed = _terminal_bindings(output_root)
        _require(observed == records, "finalization journal terminal bytes differ")
        root = output_root.resolve(strict=True)
        for binding in observed:
            raw = root.joinpath(*PurePosixPath(binding["relative_path"]).parts).read_bytes()
            _require(
                _strict_object(raw).get("authoritative_cell") is expected_authority,
                "finalization journal terminal authority differs",
            )
    return dict(value)


def read_finalization_journal(
    output_root: Path,
    *,
    bind_terminal_bytes: bool = True,
) -> dict[str, Any]:
    path = output_root.joinpath(*RELATIVE_PATH.parts)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FinalizationJournalError("cannot read campaign-finalization journal") from exc
    value = validate_finalization_journal(
        _strict_object(raw),
        output_root=output_root if bind_terminal_bytes else None,
    )
    _require(raw == _file_bytes(value), "finalization journal bytes are noncanonical")
    return value


def write_finalization_journal(
    output_root: Path,
    *,
    status: str,
    failures: Sequence[str] = (),
) -> dict[str, Any]:
    path = output_root.joinpath(*RELATIVE_PATH.parts)
    if path.exists():
        previous = read_finalization_journal(output_root, bind_terminal_bytes=False)
        _require(
            previous["status"] == AUTHORITY_PROMOTION_STARTED
            and status == AUTHORITY_PROMOTION_COMMITTED,
            "finalization journal transition is not STARTED -> COMMITTED",
        )
    else:
        _require(
            status != AUTHORITY_PROMOTION_COMMITTED,
            "committed finalization journal has no started predecessor",
        )
    value = validate_finalization_journal(
        build_finalization_journal(
            output_root,
            status=status,
            failures=failures,
        ),
        output_root=output_root,
    )
    atomic_write_bytes(path, _file_bytes(value), replace_existing=path.exists())
    return read_finalization_journal(output_root)


__all__ = [
    "AUTHORITY_PROMOTION_COMMITTED",
    "AUTHORITY_PROMOTION_STARTED",
    "EXPECTED_TERMINAL_RECORD_COUNT",
    "FinalizationJournalError",
    "RELATIVE_PATH",
    "SCHEMA",
    "SCIENTIFIC_AGGREGATE_REJECTED",
    "build_finalization_journal",
    "read_finalization_journal",
    "validate_finalization_journal",
    "write_finalization_journal",
]
