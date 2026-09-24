"""Fail-closed authority rollback/recovery for a grader-smoke campaign.

The grader-smoke runner owns the initial authority commit.  This module only
revokes that authority when a downstream step fails.  It deliberately cannot
turn authority on.

All twelve terminal records are prepared in a sibling shadow tree.  A recovery
entry point also understands the private promotion/rollback transaction trees
left by an interrupted process.  It restores a complete false-authority tree
and records the exact recovery decision; it can never manufacture authority.
The workflow may still inventory and encrypt raw forensic evidence if recovery
itself fails, but it withholds normalized failure closure in that case.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
from typing import Any, Mapping, Sequence

try:  # Support both direct-script and package-style unit-test imports.
    from trimem_grader_smoke_finalization import (
        AUTHORITY_PROMOTION_COMMITTED,
        AUTHORITY_PROMOTION_STARTED,
        FinalizationJournalError,
        RELATIVE_PATH as FINALIZATION_JOURNAL_RELATIVE_PATH,
        SCIENTIFIC_AGGREGATE_REJECTED,
        read_finalization_journal,
    )
except ModuleNotFoundError:  # pragma: no cover - import mode is environment-specific
    from scripts.trimem_grader_smoke_finalization import (
        AUTHORITY_PROMOTION_COMMITTED,
        AUTHORITY_PROMOTION_STARTED,
        FinalizationJournalError,
        RELATIVE_PATH as FINALIZATION_JOURNAL_RELATIVE_PATH,
        SCIENTIFIC_AGGREGATE_REJECTED,
        read_finalization_journal,
    )
try:  # Support both direct-script and package-style unit-test imports.
    from trimem_atomic_evidence import atomic_write_bytes
except ModuleNotFoundError:  # pragma: no cover - import mode is environment-specific
    from scripts.trimem_atomic_evidence import atomic_write_bytes


TERMINAL_CELL_SCHEMA = "trimem/grader-smoke-terminal-cell/2.0"
ROLLBACK_EVIDENCE_SCHEMA = "trimem/grader-smoke-authority-rollback/1.0"
RECOVERY_EVIDENCE_SCHEMA = "trimem/grader-smoke-authority-recovery/1.0"
EXPECTED_TERMINAL_RECORD_COUNT = 12
DEFAULT_EVIDENCE_RELATIVE_PATH = PurePosixPath(
    "restricted-evidence/authority-rollback-evidence.json"
)
DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH = PurePosixPath(
    "restricted-evidence/authority-recovery-evidence.json"
)

PROMOTION_TRANSACTION_MARKER = ".authority-promotion."
ROLLBACK_TRANSACTION_MARKER = ".authority-rollback."

CAUSE_TAXONOMY = {
    "aggregate": "aggregate_failures",
    "artifact_upload": "infrastructure_failures",
    "attestation": "aggregate_failures",
    "evidence_encryption": "infrastructure_failures",
    "evidence_inventory": "infrastructure_failures",
    "external_aggregate": "aggregate_failures",
    "scientific_aggregate": "aggregate_failures",
    "public_artifact": "aggregate_failures",
    "image_cleanup": "image_lifecycle_failures",
    "authority_finalization": "infrastructure_failures",
}

_TERMINAL_REQUIRED_FIELDS = frozenset({
    "schema",
    "target_id",
    "order_index",
    "probe",
    "grader_invoked",
    "container_started",
    "harness_completed",
    "final_report_generated",
    "official_tests_executed",
    "raw_test_evidence_captured",
    "submitted_patch_identity_verified",
    "digest_verified",
    "adapter_normalized",
    "authoritative_cell",
    "official_final_report_resolved",
    "scientific_resolved",
    "primary_failure",
    "secondary_evidence_failures",
    "execution_status",
    "actual_accounting",
    "execution_evidence",
    "evidence",
})
_SUCCESS_LIFECYCLE_FIELDS = frozenset({
    "grader_invoked",
    "container_started",
    "harness_completed",
    "final_report_generated",
    "official_tests_executed",
    "raw_test_evidence_captured",
    "submitted_patch_identity_verified",
    "digest_verified",
    "adapter_normalized",
})
_HEX64 = frozenset("0123456789abcdef")


class AuthorityRollbackError(RuntimeError):
    """The authority set could not be safely and totally revoked."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AuthorityRollbackError(message)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_payload_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuthorityRollbackError("rollback payload is not canonical JSON") from exc


def _canonical_file_bytes(value: Any) -> bytes:
    return _canonical_payload_bytes(value) + b"\n"


def _terminal_file_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuthorityRollbackError("terminal record is not canonical JSON") from exc


def _strict_object(raw: bytes, *, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise AuthorityRollbackError(
                    f"duplicate JSON key in {label}: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
        )
    except AuthorityRollbackError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityRollbackError(f"invalid UTF-8 JSON: {label}") from exc
    _require(isinstance(value, dict), f"JSON root is not an object: {label}")
    return value


def _is_hex64(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _HEX64 for character in value)
    )


def _validated_cause(
    *, cause_stage: str, failure_taxonomy: str, reason: str
) -> dict[str, str]:
    _require(
        isinstance(cause_stage, str) and cause_stage in CAUSE_TAXONOMY,
        "unsupported authority rollback stage",
    )
    _require(
        isinstance(failure_taxonomy, str)
        and failure_taxonomy == CAUSE_TAXONOMY[cause_stage],
        "authority rollback stage/taxonomy mismatch",
    )
    _require(
        isinstance(reason, str)
        and bool(reason)
        and reason.strip() == reason
        and "\x00" not in reason,
        "authority rollback reason is missing or noncanonical",
    )
    return {
        "stage": cause_stage,
        "failure_taxonomy": failure_taxonomy,
        "reason": reason,
    }


def _validate_terminal_record(
    value: Any, *, label: str, expected_authority: bool
) -> dict[str, Any]:
    _require(isinstance(value, dict), f"terminal record is not an object: {label}")
    _require(
        _TERMINAL_REQUIRED_FIELDS.issubset(value),
        f"terminal record required fields differ: {label}",
    )
    _require(
        value.get("schema") == TERMINAL_CELL_SCHEMA,
        f"terminal record schema differs: {label}",
    )
    _require(
        isinstance(value.get("target_id"), str) and bool(value["target_id"]),
        f"terminal target identity is malformed: {label}",
    )
    _require(
        type(value.get("order_index")) is int
        and 0 <= value["order_index"] < EXPECTED_TERMINAL_RECORD_COUNT,
        f"terminal order index is malformed: {label}",
    )
    _require(
        value.get("probe") in {"GOLD", "NOOP_BASELINE"},
        f"terminal probe is malformed: {label}",
    )
    _require(
        all(type(value.get(field)) is bool for field in _SUCCESS_LIFECYCLE_FIELDS),
        f"terminal lifecycle is malformed: {label}",
    )
    _require(
        type(value.get("authoritative_cell")) is bool
        and value["authoritative_cell"] is expected_authority,
        f"terminal authority state differs: {label}",
    )
    _require(
        value.get("execution_status") == "SUCCESS"
        and value.get("primary_failure") is None
        and all(value.get(field) is True for field in _SUCCESS_LIFECYCLE_FIELDS)
        and type(value.get("official_final_report_resolved")) is bool
        and value.get("scientific_resolved")
        is value.get("official_final_report_resolved"),
        f"authoritative terminal lifecycle is incomplete: {label}",
    )
    _require(
        isinstance(value.get("secondary_evidence_failures"), list)
        and not value["secondary_evidence_failures"],
        f"authoritative terminal retained secondary failures: {label}",
    )
    _require(
        all(
            isinstance(value.get(field), Mapping)
            for field in ("actual_accounting", "execution_evidence", "evidence")
        ),
        f"terminal evidence maps are malformed: {label}",
    )
    # This also rejects NaN/Infinity and non-JSON extension values.
    _terminal_file_bytes(value)
    return dict(value)


def _relative_record_path(root: Path, candidate: Path) -> PurePosixPath:
    path = candidate if candidate.is_absolute() else root / candidate
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise AuthorityRollbackError("terminal record is outside output root") from exc
    _require(relative.parts, "terminal record path is empty")
    current = root
    for component in relative.parts:
        current = current / component
        _require(not current.is_symlink(), f"symlinked terminal path: {relative.as_posix()}")
    _require(path.is_file(), f"terminal record is not a regular file: {relative.as_posix()}")
    return PurePosixPath(*relative.parts)


def _discover_record_paths(root: Path) -> list[PurePosixPath]:
    return sorted(
        (
            _relative_record_path(root, candidate)
            for candidate in root.glob("**/*.result.json")
        ),
        key=lambda value: value.as_posix(),
    )


def _load_record_set(
    root: Path,
    relative_paths: Sequence[PurePosixPath],
    *,
    expected_authority: bool,
) -> list[tuple[PurePosixPath, bytes, dict[str, Any]]]:
    _require(
        len(relative_paths) == EXPECTED_TERMINAL_RECORD_COUNT,
        "authority rollback requires exactly 12 terminal records",
    )
    _require(
        len(relative_paths) == len(set(relative_paths)),
        "duplicate terminal record path",
    )
    loaded: list[tuple[PurePosixPath, bytes, dict[str, Any]]] = []
    target_ids: list[str] = []
    order_indexes: list[int] = []
    for relative in relative_paths:
        path = root.joinpath(*relative.parts)
        _relative_record_path(root, path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise AuthorityRollbackError(
                f"cannot read terminal record: {relative.as_posix()}"
            ) from exc
        value = _strict_object(raw, label=relative.as_posix())
        value = _validate_terminal_record(
            value,
            label=relative.as_posix(),
            expected_authority=expected_authority,
        )
        _require(
            raw == _terminal_file_bytes(value),
            f"terminal record bytes are noncanonical: {relative.as_posix()}",
        )
        target_ids.append(value["target_id"])
        order_indexes.append(value["order_index"])
        loaded.append((relative, raw, value))
    _require(
        len(target_ids) == len(set(target_ids)), "duplicate terminal target identity"
    )
    _require(
        sorted(order_indexes) == list(range(EXPECTED_TERMINAL_RECORD_COUNT)),
        "terminal order indexes are missing or duplicated",
    )
    return sorted(loaded, key=lambda item: item[2]["order_index"])


def _build_evidence(
    *,
    cause: Mapping[str, str],
    record_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema": ROLLBACK_EVIDENCE_SCHEMA,
        "status": "AUTHORITY_REVOKED",
        "cause": dict(cause),
        "terminal_record_schema": TERMINAL_CELL_SCHEMA,
        "expected_terminal_record_count": EXPECTED_TERMINAL_RECORD_COUNT,
        "terminal_record_count": len(record_bindings),
        "authority_transition": {"before": True, "after": False},
        "records": record_bindings,
    }
    return {**payload, "payload_sha256": _sha256(_canonical_payload_bytes(payload))}


def validate_authority_rollback_evidence(value: Any) -> dict[str, Any]:
    _require(
        isinstance(value, dict)
        and set(value)
        == {
            "schema",
            "status",
            "cause",
            "terminal_record_schema",
            "expected_terminal_record_count",
            "terminal_record_count",
            "authority_transition",
            "records",
            "payload_sha256",
        },
        "authority rollback evidence fields differ",
    )
    cause = value.get("cause")
    _require(
        isinstance(cause, dict)
        and set(cause) == {"stage", "failure_taxonomy", "reason"},
        "authority rollback cause fields differ",
    )
    validated_cause = _validated_cause(
        cause_stage=cause.get("stage"),
        failure_taxonomy=cause.get("failure_taxonomy"),
        reason=cause.get("reason"),
    )
    records = value.get("records")
    _require(
        value.get("schema") == ROLLBACK_EVIDENCE_SCHEMA
        and value.get("status") == "AUTHORITY_REVOKED"
        and value.get("terminal_record_schema") == TERMINAL_CELL_SCHEMA
        and value.get("expected_terminal_record_count")
        == EXPECTED_TERMINAL_RECORD_COUNT
        and value.get("terminal_record_count") == EXPECTED_TERMINAL_RECORD_COUNT
        and value.get("authority_transition") == {"before": True, "after": False}
        and isinstance(records, list)
        and len(records) == EXPECTED_TERMINAL_RECORD_COUNT,
        "authority rollback evidence state differs",
    )
    expected_fields = {
        "order_index",
        "target_id",
        "relative_path",
        "before_raw_bytes",
        "before_raw_sha256",
        "after_raw_bytes",
        "after_raw_sha256",
    }
    paths: list[str] = []
    targets: list[str] = []
    indexes: list[int] = []
    for index, binding in enumerate(records):
        _require(
            isinstance(binding, dict) and set(binding) == expected_fields,
            f"authority rollback record binding fields differ: {index}",
        )
        relative_path = binding.get("relative_path")
        _require(
            isinstance(relative_path, str)
            and relative_path
            and PurePosixPath(relative_path).as_posix() == relative_path
            and not PurePosixPath(relative_path).is_absolute()
            and ".." not in PurePosixPath(relative_path).parts,
            f"authority rollback record path is malformed: {index}",
        )
        _require(
            type(binding.get("order_index")) is int
            and binding["order_index"] == index
            and isinstance(binding.get("target_id"), str)
            and bool(binding["target_id"])
            and type(binding.get("before_raw_bytes")) is int
            and binding["before_raw_bytes"] > 0
            and type(binding.get("after_raw_bytes")) is int
            and binding["after_raw_bytes"] > 0
            and _is_hex64(binding.get("before_raw_sha256"))
            and _is_hex64(binding.get("after_raw_sha256"))
            and binding["before_raw_sha256"] != binding["after_raw_sha256"],
            f"authority rollback record binding is malformed: {index}",
        )
        paths.append(relative_path)
        targets.append(binding["target_id"])
        indexes.append(binding["order_index"])
    _require(
        len(paths) == len(set(paths))
        and len(targets) == len(set(targets))
        and indexes == list(range(EXPECTED_TERMINAL_RECORD_COUNT)),
        "authority rollback bindings are missing or duplicated",
    )
    payload = {key: child for key, child in value.items() if key != "payload_sha256"}
    _require(
        _is_hex64(value.get("payload_sha256"))
        and value["payload_sha256"] == _sha256(_canonical_payload_bytes(payload)),
        "authority rollback evidence seal differs",
    )
    return {**value, "cause": validated_cause}


def read_authority_rollback_evidence(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AuthorityRollbackError("cannot read authority rollback evidence") from exc
    value = validate_authority_rollback_evidence(
        _strict_object(raw, label="authority rollback evidence")
    )
    _require(
        raw == _canonical_file_bytes(value),
        "authority rollback evidence bytes are noncanonical",
    )
    return value


def _build_recovery_evidence(
    *,
    cause: Mapping[str, str],
    canonical_state_before: str,
    recovery_source: str,
    promotion_transaction_count: int,
    rollback_transaction_count: int,
    loaded: Sequence[tuple[PurePosixPath, bytes, Mapping[str, Any]]],
    finalization_journal: Mapping[str, Any] | None,
) -> dict[str, Any]:
    record_bindings = [
        {
            "order_index": value["order_index"],
            "target_id": value["target_id"],
            "relative_path": relative.as_posix(),
            "raw_bytes": len(raw),
            "raw_sha256": _sha256(raw),
        }
        for relative, raw, value in loaded
    ]
    payload = {
        "schema": RECOVERY_EVIDENCE_SCHEMA,
        "status": "FALSE_AUTHORITY_RESTORED",
        "cause": dict(cause),
        "terminal_record_schema": TERMINAL_CELL_SCHEMA,
        "expected_terminal_record_count": EXPECTED_TERMINAL_RECORD_COUNT,
        "terminal_record_count": len(record_bindings),
        "canonical_state_before": canonical_state_before,
        "canonical_state_after": "FALSE",
        "recovery_source": recovery_source,
        "promotion_transaction_count": promotion_transaction_count,
        "rollback_transaction_count": rollback_transaction_count,
        "finalization_journal": (
            None if finalization_journal is None else dict(finalization_journal)
        ),
        "records": record_bindings,
    }
    return {**payload, "payload_sha256": _sha256(_canonical_payload_bytes(payload))}


def validate_authority_recovery_evidence(value: Any) -> dict[str, Any]:
    expected_fields = {
        "schema",
        "status",
        "cause",
        "terminal_record_schema",
        "expected_terminal_record_count",
        "terminal_record_count",
        "canonical_state_before",
        "canonical_state_after",
        "recovery_source",
        "promotion_transaction_count",
        "rollback_transaction_count",
        "finalization_journal",
        "records",
        "payload_sha256",
    }
    _require(
        isinstance(value, dict) and set(value) == expected_fields,
        "authority recovery evidence fields differ",
    )
    cause = value.get("cause")
    _require(
        isinstance(cause, dict)
        and set(cause) == {"stage", "failure_taxonomy", "reason"},
        "authority recovery cause fields differ",
    )
    validated_cause = _validated_cause(
        cause_stage=cause.get("stage"),
        failure_taxonomy=cause.get("failure_taxonomy"),
        reason=cause.get("reason"),
    )
    promotion_count = value.get("promotion_transaction_count")
    rollback_count = value.get("rollback_transaction_count")
    records = value.get("records")
    finalization_journal = value.get("finalization_journal")
    _require(
        value.get("schema") == RECOVERY_EVIDENCE_SCHEMA
        and value.get("status") == "FALSE_AUTHORITY_RESTORED"
        and value.get("terminal_record_schema") == TERMINAL_CELL_SCHEMA
        and value.get("expected_terminal_record_count")
        == EXPECTED_TERMINAL_RECORD_COUNT
        and value.get("terminal_record_count") == EXPECTED_TERMINAL_RECORD_COUNT
        and value.get("canonical_state_before")
        in {"ABSENT", "FALSE", "INCOMPLETE", "MIXED", "TRUE"}
        and value.get("canonical_state_after") == "FALSE"
        and value.get("recovery_source")
        in {
            "canonical_false",
            "promotion_original",
            "rollback_replacement",
        }
        and type(promotion_count) is int
        and promotion_count in {0, 1}
        and type(rollback_count) is int
        and rollback_count in {0, 1}
        and promotion_count + rollback_count <= 1
        and isinstance(records, list)
        and len(records) == EXPECTED_TERMINAL_RECORD_COUNT,
        "authority recovery evidence state differs",
    )
    if finalization_journal is not None:
        _require(
            isinstance(finalization_journal, dict)
            and set(finalization_journal)
            == {"bytes", "path", "payload_sha256", "sha256", "status"}
            and finalization_journal.get("path")
            == FINALIZATION_JOURNAL_RELATIVE_PATH.as_posix()
            and type(finalization_journal.get("bytes")) is int
            and finalization_journal["bytes"] > 0
            and _is_hex64(finalization_journal.get("sha256"))
            and _is_hex64(finalization_journal.get("payload_sha256"))
            and finalization_journal.get("status")
            in {
                SCIENTIFIC_AGGREGATE_REJECTED,
                AUTHORITY_PROMOTION_STARTED,
            },
            "authority recovery finalization-journal binding is malformed",
        )
    _require(
        validated_cause["stage"] != "scientific_aggregate"
        or (
            isinstance(finalization_journal, dict)
            and finalization_journal["status"]
            == SCIENTIFIC_AGGREGATE_REJECTED
        ),
        "scientific authority recovery lacks its finalization journal",
    )
    record_fields = {
        "order_index",
        "target_id",
        "relative_path",
        "raw_bytes",
        "raw_sha256",
    }
    paths: list[str] = []
    targets: list[str] = []
    for index, binding in enumerate(records):
        _require(
            isinstance(binding, dict)
            and set(binding) == record_fields
            and binding.get("order_index") == index
            and isinstance(binding.get("target_id"), str)
            and bool(binding["target_id"])
            and isinstance(binding.get("relative_path"), str)
            and bool(binding["relative_path"])
            and PurePosixPath(binding["relative_path"]).as_posix()
            == binding["relative_path"]
            and not PurePosixPath(binding["relative_path"]).is_absolute()
            and ".." not in PurePosixPath(binding["relative_path"]).parts
            and type(binding.get("raw_bytes")) is int
            and binding["raw_bytes"] > 0
            and _is_hex64(binding.get("raw_sha256")),
            f"authority recovery record binding is malformed: {index}",
        )
        paths.append(binding["relative_path"])
        targets.append(binding["target_id"])
    _require(
        len(paths) == len(set(paths)) and len(targets) == len(set(targets)),
        "authority recovery bindings are missing or duplicated",
    )
    payload = {key: child for key, child in value.items() if key != "payload_sha256"}
    _require(
        _is_hex64(value.get("payload_sha256"))
        and value["payload_sha256"] == _sha256(_canonical_payload_bytes(payload)),
        "authority recovery evidence seal differs",
    )
    return {**value, "cause": validated_cause}


def read_authority_recovery_evidence(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AuthorityRollbackError("cannot read authority recovery evidence") from exc
    value = validate_authority_recovery_evidence(
        _strict_object(raw, label="authority recovery evidence")
    )
    _require(
        raw == _canonical_file_bytes(value),
        "authority recovery evidence bytes are noncanonical",
    )
    return value


def _write_fsynced(path: Path, raw: bytes, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "xb" if exclusive else "wb"
    try:
        with path.open(mode) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise AuthorityRollbackError(f"cannot write rollback transaction file: {path.name}") from exc


def _atomic_write_fsynced(path: Path, raw: bytes, *, exclusive: bool) -> None:
    """Publish one complete file in its destination directory."""
    try:
        atomic_write_bytes(path, raw, replace_existing=not exclusive)
    except OSError as exc:
        raise AuthorityRollbackError(
            f"cannot publish authority transaction file: {path.name}"
        ) from exc


def _tree_state(
    candidate: Path,
) -> tuple[str, list[tuple[PurePosixPath, bytes, dict[str, Any]]] | None]:
    if not candidate.exists():
        return "ABSENT", None
    _require(
        candidate.is_dir() and not candidate.is_symlink(),
        f"authority transaction tree is not a regular directory: {candidate.name}",
    )
    relative_paths = _discover_record_paths(candidate)
    if len(relative_paths) != EXPECTED_TERMINAL_RECORD_COUNT:
        return "INCOMPLETE", None
    authority_states: list[bool] = []
    for relative in relative_paths:
        raw = candidate.joinpath(*relative.parts).read_bytes()
        value = _strict_object(raw, label=relative.as_posix())
        state = value.get("authoritative_cell")
        _require(
            type(state) is bool,
            f"terminal authority state is malformed: {relative.as_posix()}",
        )
        authority_states.append(state)
    if len(set(authority_states)) != 1:
        return "MIXED", None
    authority = authority_states[0]
    try:
        loaded = _load_record_set(
            candidate, relative_paths, expected_authority=authority,
        )
    except AuthorityRollbackError:
        # A false-authority terminal set may legitimately contain a scientific,
        # adapter, or harness failure.  Such a campaign is not an authority
        # transaction and its own terminal primary failure must drive closure.
        # A true-authority malformed/incomplete set is never tolerated.
        if not authority:
            return "NONAUTHORITATIVE_FAILURE", None
        raise
    return ("TRUE" if authority else "FALSE"), loaded


def _transaction_directories(root: Path) -> tuple[list[Path], list[Path]]:
    parent = root.parent
    promotion_prefix = f".{root.name}{PROMOTION_TRANSACTION_MARKER}"
    rollback_prefix = f".{root.name}{ROLLBACK_TRANSACTION_MARKER}"
    promotion: list[Path] = []
    rollback: list[Path] = []
    try:
        children = list(parent.iterdir())
    except OSError as exc:
        raise AuthorityRollbackError("cannot inspect authority transaction directory") from exc
    for child in children:
        if child.name.startswith(promotion_prefix):
            _require(
                child.is_dir() and not child.is_symlink(),
                "promotion transaction path is not a regular directory",
            )
            promotion.append(child)
        elif child.name.startswith(rollback_prefix) and child.name != (
            f".{root.name}.authority-rollback.lock"
        ):
            _require(
                child.is_dir() and not child.is_symlink(),
                "rollback transaction path is not a regular directory",
            )
            rollback.append(child)
    promotion.sort(key=lambda value: value.name)
    rollback.sort(key=lambda value: value.name)
    _require(
        len(promotion) <= 1 and len(rollback) <= 1
        and len(promotion) + len(rollback) <= 1,
        "ambiguous authority transaction set",
    )
    return promotion, rollback


def _validate_transaction_components(
    promotion: Sequence[Path], rollback: Sequence[Path]
) -> list[tuple[str, Path, list[tuple[PurePosixPath, bytes, dict[str, Any]]]]]:
    false_candidates: list[
        tuple[str, Path, list[tuple[PurePosixPath, bytes, dict[str, Any]]]]
    ] = []
    for transaction, components in (
        (
            promotion[0] if promotion else None,
            (("promotion_original", "original", "FALSE"), ("", "replacement", "TRUE")),
        ),
        (
            rollback[0] if rollback else None,
            (("", "original", "TRUE"), ("rollback_replacement", "replacement", "FALSE")),
        ),
    ):
        if transaction is None:
            continue
        for source, component_name, expected_state in components:
            component = transaction / component_name
            state, loaded = _tree_state(component)
            if state in {"TRUE", "FALSE"}:
                _require(
                    state == expected_state,
                    f"authority transaction {component_name} state differs",
                )
                if state == "FALSE":
                    assert loaded is not None
                    false_candidates.append((source, component, loaded))
    return false_candidates


def _bind_recovery_to_canonical(
    root: Path,
    evidence: Mapping[str, Any],
) -> list[tuple[PurePosixPath, bytes, dict[str, Any]]]:
    state, loaded = _tree_state(root)
    _require(
        state == "FALSE" and loaded is not None,
        "authority recovery did not commit a complete false-authority tree",
    )
    for (_relative, raw, value), binding in zip(
        loaded, evidence["records"], strict=True
    ):
        _require(
            value["order_index"] == binding["order_index"]
            and value["target_id"] == binding["target_id"]
            and len(raw) == binding["raw_bytes"]
            and _sha256(raw) == binding["raw_sha256"],
            "canonical false-authority record differs from recovery evidence",
        )
    return loaded


def _remove_recovered_transaction_state(
    root: Path, promotion: Sequence[Path], rollback: Sequence[Path]
) -> None:
    for transaction in [*promotion, *rollback]:
        if transaction.exists():
            shutil.rmtree(transaction)
    stale_rollback_lock = root.parent / f".{root.name}.authority-rollback.lock"
    stale_rollback_lock.unlink(missing_ok=True)


def _journal_qualified_recovery_cause(
    selected_root: Path,
    supplied: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Use the sealed finalization stage only for a failed run-smoke step."""

    journal_path = selected_root.joinpath(*FINALIZATION_JOURNAL_RELATIVE_PATH.parts)
    if not journal_path.exists():
        return dict(supplied), None
    try:
        journal = read_finalization_journal(selected_root)
    except FinalizationJournalError as exc:
        raise AuthorityRollbackError(
            f"campaign-finalization journal did not validate: {exc}"
        ) from exc
    raw = journal_path.read_bytes()
    binding = {
        "bytes": len(raw),
        "path": FINALIZATION_JOURNAL_RELATIVE_PATH.as_posix(),
        "payload_sha256": journal["payload_sha256"],
        "sha256": _sha256(raw),
        "status": journal["status"],
    }
    if supplied["stage"] != "authority_finalization":
        return dict(supplied), binding
    status = journal["status"]
    if status == SCIENTIFIC_AGGREGATE_REJECTED:
        return (
            _validated_cause(
                cause_stage="scientific_aggregate",
                failure_taxonomy="aggregate_failures",
                reason="campaign-finalization journal records scientific aggregate rejection",
            ),
            binding,
        )
    if status == AUTHORITY_PROMOTION_STARTED:
        return dict(supplied), binding
    _require(
        status != AUTHORITY_PROMOTION_COMMITTED,
        "committed authority journal cannot bind a false-authority recovery source",
    )
    raise AssertionError("validated finalization journal escaped its status set")


def recover_interrupted_authority_transaction(
    output_root: Path,
    *,
    cause_stage: str,
    failure_taxonomy: str,
    reason: str,
) -> dict[str, Any] | None:
    """Recover an interrupted authority transaction, never promoting authority.

    ``None`` means that no authority transaction/finalization state existed:
    ordinary partial-cell failures remain owned by their terminal records.
    A complete false-authority tree is only treated as interrupted campaign
    finalization when the finalization journal records that transition.  The
    absence of a summary alone is ambiguous: a post-cell image-lifecycle
    failure also leaves twelve successful, false-authority terminals.
    """

    root = output_root.absolute()
    cause = _validated_cause(
        cause_stage=cause_stage,
        failure_taxonomy=failure_taxonomy,
        reason=reason,
    )
    promotion, rollback = _transaction_directories(root)
    state_before, canonical_loaded = _tree_state(root)
    recovery_path = root.joinpath(*DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH.parts)
    rollback_evidence_path = root.joinpath(*DEFAULT_EVIDENCE_RELATIVE_PATH.parts)

    if state_before == "FALSE" and recovery_path.is_file():
        evidence = read_authority_recovery_evidence(recovery_path)
        _bind_recovery_to_canonical(root, evidence)
        _remove_recovered_transaction_state(root, promotion, rollback)
        return evidence
    _require(
        not recovery_path.exists(),
        "authority recovery evidence path is malformed",
    )
    if state_before == "FALSE" and rollback_evidence_path.is_file():
        evidence = read_authority_rollback_evidence(rollback_evidence_path)
        rollback_loaded = _load_record_set(
            root,
            [PurePosixPath(binding["relative_path"]) for binding in evidence["records"]],
            expected_authority=False,
        )
        for (_relative, raw, _value), binding in zip(
            rollback_loaded, evidence["records"], strict=True
        ):
            _require(
                len(raw) == binding["after_raw_bytes"]
                and _sha256(raw) == binding["after_raw_sha256"],
                "canonical false-authority record differs from rollback evidence",
            )
        _remove_recovered_transaction_state(root, promotion, rollback)
        return evidence

    false_candidates = _validate_transaction_components(promotion, rollback)
    if state_before == "FALSE":
        assert canonical_loaded is not None
        false_candidates.insert(0, ("canonical_false", root, canonical_loaded))

    has_transaction = bool(promotion or rollback)
    _require(
        not has_transaction or state_before != "NONAUTHORITATIVE_FAILURE",
        "authority transaction conflicts with terminal-owned failure evidence",
    )
    if not has_transaction:
        if state_before == "TRUE":
            return rollback_authoritative_terminal_records(
                root,
                cause_stage=cause_stage,
                failure_taxonomy=failure_taxonomy,
                reason=reason,
            )
        finalization_journal_path = root.joinpath(
            *FINALIZATION_JOURNAL_RELATIVE_PATH.parts
        )
        if (
            state_before == "FALSE"
            and cause_stage == "authority_finalization"
            and finalization_journal_path.is_file()
            and not finalization_journal_path.is_symlink()
        ):
            pass
        else:
            return None

    _require(
        bool(false_candidates),
        "interrupted authority transaction has no complete false-authority tree",
    )
    # Prefer an already canonical false tree; otherwise the transaction roles
    # make the source unambiguous.  Multiple byte-distinct false candidates are
    # rejected instead of guessing which campaign state should win.
    source, selected_root, selected_loaded = false_candidates[0]
    baseline = [raw for _relative, raw, _value in selected_loaded]
    for _other_source, _other_root, other_loaded in false_candidates[1:]:
        _require(
            [raw for _relative, raw, _value in other_loaded] == baseline,
            "authority transaction contains divergent false-authority trees",
        )

    cause, finalization_journal = _journal_qualified_recovery_cause(
        selected_root, cause
    )

    evidence = validate_authority_recovery_evidence(
        _build_recovery_evidence(
            cause=cause,
            canonical_state_before=state_before,
            recovery_source=source,
            promotion_transaction_count=len(promotion),
            rollback_transaction_count=len(rollback),
            loaded=selected_loaded,
            finalization_journal=finalization_journal,
        )
    )
    selected_evidence_path = selected_root.joinpath(
        *DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH.parts
    )
    if selected_evidence_path.exists():
        _require(
            read_authority_recovery_evidence(selected_evidence_path) == evidence,
            "staged authority recovery evidence differs from this recovery",
        )
    else:
        _atomic_write_fsynced(
            selected_evidence_path,
            _canonical_file_bytes(evidence),
            exclusive=True,
        )
        read_authority_recovery_evidence(selected_evidence_path)

    recovery_required = False
    quarantine: Path | None = None
    if selected_root != root:
        transaction = promotion[0] if promotion else rollback[0]
        quarantine = transaction / "superseded-canonical"
        try:
            if root.exists():
                _require(not quarantine.exists(), "authority recovery quarantine exists")
                os.replace(root, quarantine)
            try:
                os.replace(selected_root, root)
            except BaseException as replacement_exc:
                if quarantine is not None and quarantine.exists() and not root.exists():
                    try:
                        os.replace(quarantine, root)
                    except BaseException as restoration_exc:
                        recovery_required = True
                        raise AuthorityRollbackError(
                            "authority recovery swap and canonical restoration failed; "
                            f"false-authority source retained at {selected_root}"
                        ) from restoration_exc
                raise replacement_exc
        except AuthorityRollbackError:
            raise
        except BaseException as exc:
            raise AuthorityRollbackError("authority recovery directory swap failed") from exc

    committed = read_authority_recovery_evidence(
        root.joinpath(*DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH.parts)
    )
    _bind_recovery_to_canonical(root, committed)
    if not recovery_required:
        _remove_recovered_transaction_state(root, promotion, rollback)
    return committed


def _replace_staged_hardlink(path: Path, raw: bytes) -> None:
    """Break one staged hardlink before writing its replacement bytes."""

    try:
        path.unlink()
    except OSError as exc:
        raise AuthorityRollbackError(
            f"cannot detach staged terminal hardlink: {path.name}"
        ) from exc
    _write_fsynced(path, raw, exclusive=True)


def _safe_evidence_relative_path(value: PurePosixPath) -> PurePosixPath:
    _require(
        not value.is_absolute()
        and bool(value.parts)
        and ".." not in value.parts
        and value.suffix == ".json",
        "authority rollback evidence path is unsafe",
    )
    return value


def _assert_source_unchanged(
    root: Path,
    loaded: Sequence[tuple[PurePosixPath, bytes, Mapping[str, Any]]],
) -> None:
    discovered = _discover_record_paths(root)
    expected = sorted((item[0] for item in loaded), key=lambda value: value.as_posix())
    _require(discovered == expected, "terminal record set changed during rollback staging")
    for relative, before_raw, _ in loaded:
        try:
            current = root.joinpath(*relative.parts).read_bytes()
        except OSError as exc:
            raise AuthorityRollbackError(
                f"terminal record disappeared during rollback: {relative.as_posix()}"
            ) from exc
        _require(current == before_raw, "terminal record changed during rollback staging")


def rollback_authoritative_terminal_records(
    output_root: Path,
    *,
    cause_stage: str,
    failure_taxonomy: str,
    reason: str,
    evidence_relative_path: PurePosixPath = DEFAULT_EVIDENCE_RELATIVE_PATH,
) -> dict[str, Any]:
    """Atomically revoke one complete twelve-cell authority set.

    The function rejects already-revoked, mixed, partial, duplicated, malformed,
    or noncanonical inputs.  It has no code path that writes ``True`` into a
    terminal record.
    """

    unresolved_root = output_root.absolute()
    _require(
        unresolved_root.is_dir() and not unresolved_root.is_symlink(),
        "output root is not a regular directory",
    )
    root = unresolved_root.resolve()
    cause = _validated_cause(
        cause_stage=cause_stage,
        failure_taxonomy=failure_taxonomy,
        reason=reason,
    )
    evidence_relative = _safe_evidence_relative_path(evidence_relative_path)
    evidence_path = root.joinpath(*evidence_relative.parts)
    _require(not evidence_path.exists(), "authority rollback evidence already exists")

    lock_path = root.parent / f".{root.name}.authority-rollback.lock"
    lock_fd: int | None = None
    transaction_parent: Path | None = None
    recovery_required = False
    try:
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(lock_fd, b"trimem-authority-rollback-v1\n")
            os.fsync(lock_fd)
        except OSError as exc:
            raise AuthorityRollbackError("authority rollback transaction is already active") from exc

        relative_paths = _discover_record_paths(root)
        loaded = _load_record_set(root, relative_paths, expected_authority=True)

        transaction_parent = Path(
            tempfile.mkdtemp(prefix=f".{root.name}.authority-rollback.", dir=root.parent)
        )
        staged_root = transaction_parent / "replacement"
        backup_root = transaction_parent / "original"
        try:
            # The smoke tree contains large restricted raw evidence.  A normal
            # copy would temporarily double bounded-disk usage.  Both trees
            # live on the same filesystem, so immutable files are hardlinked;
            # each of the twelve records is explicitly detached below before
            # its new bytes are written.
            shutil.copytree(root, staged_root, symlinks=True, copy_function=os.link)
        except OSError as exc:
            raise AuthorityRollbackError(
                "cannot stage authority rollback tree with same-filesystem hardlinks"
            ) from exc

        bindings: list[dict[str, Any]] = []
        for relative, before_raw, before_value in loaded:
            after_value = dict(before_value)
            # This assignment is intentionally the module's sole authority
            # mutation.  There is no inverse/promoting operation.
            after_value["authoritative_cell"] = False
            after_raw = _terminal_file_bytes(after_value)
            staged_path = staged_root.joinpath(*relative.parts)
            _replace_staged_hardlink(staged_path, after_raw)
            bindings.append({
                "order_index": before_value["order_index"],
                "target_id": before_value["target_id"],
                "relative_path": relative.as_posix(),
                "before_raw_bytes": len(before_raw),
                "before_raw_sha256": _sha256(before_raw),
                "after_raw_bytes": len(after_raw),
                "after_raw_sha256": _sha256(after_raw),
            })

        evidence = validate_authority_rollback_evidence(
            _build_evidence(cause=cause, record_bindings=bindings)
        )
        staged_evidence_path = staged_root.joinpath(*evidence_relative.parts)
        _write_fsynced(
            staged_evidence_path, _canonical_file_bytes(evidence), exclusive=True,
        )
        try:
            staged_evidence_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            raise AuthorityRollbackError("cannot restrict authority rollback evidence") from exc

        staged_loaded = _load_record_set(
            staged_root, relative_paths, expected_authority=False,
        )
        for (relative, _before_raw, _before_value), (
            staged_relative,
            after_raw,
            _after_value,
        ), binding in zip(loaded, staged_loaded, bindings, strict=True):
            _require(relative == staged_relative, "staged terminal record order differs")
            _require(
                _sha256(after_raw) == binding["after_raw_sha256"]
                and len(after_raw) == binding["after_raw_bytes"],
                "staged terminal record hash differs",
            )
        read_authority_rollback_evidence(staged_evidence_path)
        _assert_source_unchanged(root, loaded)
        _require(not evidence_path.exists(), "authority rollback evidence appeared concurrently")

        try:
            os.replace(root, backup_root)
            try:
                os.replace(staged_root, root)
            except BaseException as replacement_exc:
                # The canonical path is absent here, so restoring the complete
                # old tree cannot create a mixed authority set.
                try:
                    os.replace(backup_root, root)
                except BaseException as restore_exc:
                    recovery_required = True
                    raise AuthorityRollbackError(
                        "authority rollback swap and complete-tree restoration failed; "
                        f"recovery tree retained at {backup_root}"
                    ) from restore_exc
                raise replacement_exc
        except AuthorityRollbackError:
            raise
        except BaseException as exc:
            raise AuthorityRollbackError("atomic authority rollback directory swap failed") from exc

        # Do not restore/promote authority after the replacement became
        # canonical.  Any post-commit validation error is fail-closed with the
        # all-false tree left in place.
        final_loaded = _load_record_set(root, relative_paths, expected_authority=False)
        final_evidence = read_authority_rollback_evidence(
            root.joinpath(*evidence_relative.parts)
        )
        for (_relative, raw, _value), binding in zip(
            final_loaded, final_evidence["records"], strict=True
        ):
            _require(
                _sha256(raw) == binding["after_raw_sha256"]
                and len(raw) == binding["after_raw_bytes"],
                "committed terminal record hash differs from rollback evidence",
            )
        return final_evidence
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError:
                pass
        cleanup_failed = False
        if (
            not recovery_required
            and transaction_parent is not None
            and transaction_parent.exists()
        ):
            try:
                shutil.rmtree(transaction_parent)
            except OSError:
                cleanup_failed = True
                # Once committed, never swap the authoritative backup back in.
                # Leaving a private sibling transaction tree is fail-closed and
                # does not change the canonical output root.
        if not recovery_required and not cleanup_failed:
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                # A stale lock fails subsequent calls closed; it is safer than
                # silently admitting a concurrent transaction.
                pass


def _read_reason(path: Path) -> str:
    try:
        raw = path.read_bytes()
        _require(not raw.startswith(b"\xef\xbb\xbf"), "rollback reason has a UTF-8 BOM")
        reason = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AuthorityRollbackError("cannot read UTF-8 rollback reason") from exc
    if reason.endswith("\r\n"):
        reason = reason[:-2]
    elif reason.endswith("\n"):
        reason = reason[:-1]
    return reason


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Revoke or recover grader-smoke terminal authority fail closed",
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cause-stage", choices=sorted(CAUSE_TAXONOMY), required=True)
    parser.add_argument(
        "--failure-taxonomy",
        choices=sorted(set(CAUSE_TAXONOMY.values())),
        required=True,
    )
    parser.add_argument("--reason-file", type=Path, required=True)
    parser.add_argument(
        "--recover-interrupted",
        action="store_true",
        help=(
            "recover private promotion/rollback transactions and otherwise "
            "revoke only a complete authoritative campaign"
        ),
    )
    args = parser.parse_args(argv)
    reason = _read_reason(args.reason_file)
    if args.recover_interrupted:
        evidence = recover_interrupted_authority_transaction(
            args.output_root,
            cause_stage=args.cause_stage,
            failure_taxonomy=args.failure_taxonomy,
            reason=reason,
        )
    else:
        evidence = rollback_authoritative_terminal_records(
            args.output_root,
            cause_stage=args.cause_stage,
            failure_taxonomy=args.failure_taxonomy,
            reason=reason,
        )
    if evidence is None:
        public = {
            "schema": RECOVERY_EVIDENCE_SCHEMA,
            "status": "NO_AUTHORITY_ACTION",
            "terminal_record_count": len(_discover_record_paths(args.output_root)),
            "evidence_relative_path": None,
            "payload_sha256": None,
        }
    else:
        evidence_relative = (
            DEFAULT_RECOVERY_EVIDENCE_RELATIVE_PATH
            if evidence["schema"] == RECOVERY_EVIDENCE_SCHEMA
            else DEFAULT_EVIDENCE_RELATIVE_PATH
        )
        public = {
            "schema": evidence["schema"],
            "status": evidence["status"],
            "terminal_record_count": evidence["terminal_record_count"],
            "evidence_relative_path": evidence_relative.as_posix(),
            "payload_sha256": evidence["payload_sha256"],
        }
    print(json.dumps(public, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
