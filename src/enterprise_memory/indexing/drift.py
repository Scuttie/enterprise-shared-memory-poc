"""Index drift detector (P2). PostgreSQL is authoritative, so the index is correct only if it mirrors the
canonical CURRENT set exactly. Drift is reported in three buckets:
  missing_in_index  canonical object with no matching index point (under-indexed)
  stale_in_index    index point whose content_hash != the canonical hash (stale projection)
  orphan_in_index   index point with no canonical current object (over-indexed / not cleaned up)
A non-empty report means retrieval could surface a stale/absent reference — validated_search would still
reject it against PostgreSQL, but drift indicates the projection pipeline is behind and should be replayed."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from .models import PRIVATE, SHARED
from . import canonical_loaders as cl


@dataclass
class DriftReport:
    scope: str
    org_id: str
    canonical_count: int = 0
    index_count: int = 0
    missing_in_index: List[str] = field(default_factory=list)
    stale_in_index: List[str] = field(default_factory=list)
    orphan_in_index: List[str] = field(default_factory=list)

    @property
    def has_drift(self) -> bool:
        return bool(self.missing_in_index or self.stale_in_index or self.orphan_in_index)

    def to_dict(self) -> dict:
        return {"scope": self.scope, "org_id": self.org_id, "canonical_count": self.canonical_count,
                "index_count": self.index_count, "missing_in_index": self.missing_in_index,
                "stale_in_index": self.stale_in_index, "orphan_in_index": self.orphan_in_index,
                "has_drift": self.has_drift}


async def _index_map(index, scope, org_id, owner_user_id=None):
    """canonical_version_id -> content_hash for this org's (and owner's) points in the scope collection."""
    pts = await index.scroll(scope)
    m = {}
    for p in pts:
        pl = p["payload"]
        if str(pl.get("org_id")) != str(org_id):
            continue
        if owner_user_id is not None and str(pl.get("owner_user_id")) != str(owner_user_id):
            continue
        m[str(pl.get("canonical_version_id"))] = str(pl.get("canonical_content_hash"))
    return m


async def check_shared(engine, index, org_id) -> DriftReport:
    rep = DriftReport(scope=SHARED, org_id=str(org_id))
    canon = {r["object_id"]: str(r["content_hash"]) for r in
             await cl.enumerate_current_contract_versions(engine, org_id)}
    idx = await _index_map(index, SHARED, org_id)
    rep.canonical_count, rep.index_count = len(canon), len(idx)
    for oid, h in canon.items():
        if oid not in idx:
            rep.missing_in_index.append(oid)
        elif idx[oid] != h:
            rep.stale_in_index.append(oid)
    for oid in idx:
        if oid not in canon:
            rep.orphan_in_index.append(oid)
    return rep


async def check_private(engine, index, org_id, user_id) -> DriftReport:
    rep = DriftReport(scope=PRIVATE, org_id=str(org_id))
    canon = {r["object_id"]: str(r["content_hash"]) for r in
             await cl.enumerate_private(engine, org_id, user_id)}
    idx = await _index_map(index, PRIVATE, org_id, owner_user_id=user_id)
    rep.canonical_count, rep.index_count = len(canon), len(idx)
    for oid, h in canon.items():
        if oid not in idx:
            rep.missing_in_index.append(oid)
        elif idx[oid] != h:
            rep.stale_in_index.append(oid)
    for oid in idx:
        if oid not in canon:
            rep.orphan_in_index.append(oid)
    return rep
