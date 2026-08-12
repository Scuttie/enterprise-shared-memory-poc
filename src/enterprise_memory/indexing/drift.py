"""Index drift detector (P2 / P2.1). PostgreSQL is authoritative, so the index is correct only if it
mirrors the canonical CURRENT set exactly AND contains nothing that should not be searchable. Read-only:
it never repairs. Categories:
  missing_in_index        canonical current object with no matching index point
  stale_in_index          index point whose content_hash != the canonical hash
  orphan_in_index         index point with no canonical object (deleted / never existed)
  invalid_schema          index point with an unsupported index_schema_version
  wrong_collection        index point whose scope/object_kind does not match its collection
  deprecated_searchable   index point whose canonical is not promoted / not servable
  superseded_searchable   index point for a version another version supersedes
  expired_searchable      index point whose canonical validity window has closed
  duplicate               more than one index point for the same canonical_version_id
  alias_error             the scope alias does not resolve to exactly one collection
A non-empty report means retrieval could surface a stale/absent/withdrawn reference — validated_search would
still reject it against PostgreSQL, but drift means the projection pipeline is behind and should be replayed."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional
from .models import PRIVATE, SHARED, ObjectType, INDEX_SCHEMA_VERSION
from . import canonical_loaders as cl

_PRIVATE_UNSERVABLE = ("deleted", "quarantined", "tombstoned")


def _expired(vu) -> bool:
    if vu is None:
        return False
    if vu.tzinfo is None:
        vu = vu.replace(tzinfo=timezone.utc)
    return vu <= datetime.now(timezone.utc)


@dataclass
class DriftReport:
    scope: str
    org_id: str
    canonical_count: int = 0
    index_count: int = 0
    missing_in_index: List[str] = field(default_factory=list)
    stale_in_index: List[str] = field(default_factory=list)
    orphan_in_index: List[str] = field(default_factory=list)
    invalid_schema: List[str] = field(default_factory=list)
    wrong_collection: List[str] = field(default_factory=list)
    deprecated_searchable: List[str] = field(default_factory=list)
    superseded_searchable: List[str] = field(default_factory=list)
    expired_searchable: List[str] = field(default_factory=list)
    duplicate: List[str] = field(default_factory=list)
    alias_error: Optional[str] = None

    _BUCKETS = ("missing_in_index", "stale_in_index", "orphan_in_index", "invalid_schema",
                "wrong_collection", "deprecated_searchable", "superseded_searchable",
                "expired_searchable", "duplicate")

    @property
    def has_drift(self) -> bool:
        return bool(self.alias_error) or any(getattr(self, b) for b in self._BUCKETS)

    def to_dict(self) -> dict:
        d = {"scope": self.scope, "org_id": self.org_id, "canonical_count": self.canonical_count,
             "index_count": self.index_count, "alias_error": self.alias_error, "has_drift": self.has_drift}
        for b in self._BUCKETS:
            d[b] = getattr(self, b)
        return d


async def _points(index, scope, org_id, owner_user_id=None):
    pts = await index.scroll(scope)
    out = []
    for p in pts:
        pl = p["payload"]
        if str(pl.get("org_id")) != str(org_id):
            continue
        if owner_user_id is not None and str(pl.get("owner_user_id")) != str(owner_user_id):
            continue
        out.append(pl)
    return out


async def _alias_health(index, scope, rep):
    try:
        await index.resolve(scope)
    except Exception as e:  # noqa: BLE001 - report, never raise from a read-only scan
        rep.alias_error = str(e)


async def check_shared(engine, index, org_id) -> DriftReport:
    rep = DriftReport(scope=SHARED, org_id=str(org_id))
    await _alias_health(index, SHARED, rep)
    canon = {r["object_id"]: str(r["content_hash"]) for r in
             await cl.enumerate_current_contract_versions(engine, org_id)}
    pts = await _points(index, SHARED, org_id)
    seen = {}
    for pl in pts:
        vid = str(pl.get("canonical_version_id"))
        seen[vid] = seen.get(vid, 0) + 1
        if int(pl.get("index_schema_version", -1)) != INDEX_SCHEMA_VERSION:
            rep.invalid_schema.append(vid)
        if pl.get("scope") != SHARED or pl.get("object_kind") != ObjectType.CONTRACT_VERSION.value:
            rep.wrong_collection.append(vid)
            continue
        row = await cl.load_contract_version(engine, org_id, vid)
        if row is None:
            rep.orphan_in_index.append(vid)
            continue
        if str(pl.get("canonical_content_hash")) != str(row["content_hash"]):
            rep.stale_in_index.append(vid)
        if not row["is_current"]:
            (rep.superseded_searchable if row.get("superseded_by") else rep.orphan_in_index).append(vid)
        if row.get("governance_state") != "promoted":
            rep.deprecated_searchable.append(vid)
        if _expired(row.get("valid_until")):
            rep.expired_searchable.append(vid)
    rep.duplicate = [v for v, n in seen.items() if n > 1]
    rep.index_count = len(seen)
    rep.canonical_count = len(canon)
    rep.missing_in_index = [oid for oid in canon if oid not in seen]
    return rep


async def check_private(engine, index, org_id, user_id) -> DriftReport:
    rep = DriftReport(scope=PRIVATE, org_id=str(org_id))
    await _alias_health(index, PRIVATE, rep)
    canon = {r["object_id"]: str(r["content_hash"]) for r in
             await cl.enumerate_private(engine, org_id, user_id)}
    pts = await _points(index, PRIVATE, org_id, owner_user_id=user_id)
    seen = {}
    for pl in pts:
        vid = str(pl.get("canonical_version_id"))
        seen[vid] = seen.get(vid, 0) + 1
        if int(pl.get("index_schema_version", -1)) != INDEX_SCHEMA_VERSION:
            rep.invalid_schema.append(vid)
        if pl.get("scope") != PRIVATE or pl.get("object_kind") != ObjectType.PRIVATE_EPISODE.value:
            rep.wrong_collection.append(vid)
            continue
        row = await cl.load_private_episode(engine, org_id, user_id, vid)
        if row is None:
            rep.orphan_in_index.append(vid)
            continue
        if str(pl.get("canonical_content_hash")) != str(row["content_hash"]):
            rep.stale_in_index.append(vid)
        if (row.get("state") or "") in _PRIVATE_UNSERVABLE:
            rep.deprecated_searchable.append(vid)
    rep.duplicate = [v for v, n in seen.items() if n > 1]
    rep.index_count = len(seen)
    rep.canonical_count = len(canon)
    rep.missing_in_index = [oid for oid in canon if oid not in seen]
    return rep
