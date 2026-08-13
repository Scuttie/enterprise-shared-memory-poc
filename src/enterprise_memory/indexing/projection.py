"""Deterministic canonical -> index projection (P2.1). Builds the reference IndexRecord that gets embedded
and stored. There is exactly one projection function per scope so the worker and the full-reindex path
produce identical points (idempotent by deterministic point id)."""
from __future__ import annotations
from datetime import datetime, timezone
from .models import IndexRecord, PRIVATE, SHARED, ObjectType
from .canonical_loaders import embed_text, path_scope_of
from ..contracts import codec


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(v):
    if v is None:
        return None
    return v if isinstance(v, str) else v.isoformat()


def build_record(scope: str, row: dict, indexed_at: str = None) -> IndexRecord:
    # Shared contracts embed the SAFE, target-free retrieval projection (via the codec) — never the full
    # canonical JSON. Private episodes are owner-isolated and use the compact canonical text.
    if scope == SHARED:
        text, path_scope = codec.retrieval_text_and_path_scope(row["canonical"])
    else:
        text = embed_text(row["canonical"])
        path_scope = row.get("path_scope") or path_scope_of(row.get("canonical"))
    stamp = indexed_at or now_iso()
    if scope == SHARED:
        return IndexRecord(
            scope=SHARED, object_kind=ObjectType.CONTRACT_VERSION.value,
            canonical_id=str(row["contract_id"]), canonical_version_id=str(row["object_id"]),
            canonical_version_number=int(row["version_number"]), canonical_content_hash=row["content_hash"],
            org_id=str(row["org_id"]), text=text, repository_id=row.get("repository_id"),
            contract_id=str(row["contract_id"]), governance_state=row.get("governance_state"),
            valid_from=_iso(row.get("valid_from")), valid_until=_iso(row.get("valid_until")),
            path_scope=path_scope, indexed_at=stamp)
    return IndexRecord(
        scope=PRIVATE, object_kind=ObjectType.PRIVATE_EPISODE.value,
        canonical_id=str(row["object_id"]), canonical_version_id=str(row["object_id"]),
        canonical_version_number=1, canonical_content_hash=row["content_hash"],
        org_id=str(row["org_id"]), text=text, owner_user_id=str(row["owner_user_id"]),
        repository_id=row.get("repository_id"), governance_state=row.get("state"),
        path_scope=path_scope, indexed_at=stamp)
