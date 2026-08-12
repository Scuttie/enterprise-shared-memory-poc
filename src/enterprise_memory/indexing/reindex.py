"""Full reindex with atomic alias swap + rollback (P2). A rebuild NEVER mutates the live collection: it
builds a brand-new physical collection from the canonical PostgreSQL set, and only when the build succeeds
does it repoint the scope's *_current alias (and the adapter's active pointer) to the new collection. If
anything downstream looks wrong, rollback() repoints back to the previous collection — the old data was
never touched, so rollback is instantaneous and lossless."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from .models import PRIVATE, SHARED, BASE_COLLECTION
from . import canonical_loaders as cl
from .projection import build_record


@dataclass
class ReindexReport:
    scope: str
    new_collection: str
    previous_collection: str
    indexed: int = 0
    targets: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"scope": self.scope, "new_collection": self.new_collection,
                "previous_collection": self.previous_collection, "indexed": self.indexed,
                "targets": self.targets}


async def _build_shared(engine, index, embedder, org_id, new_collection) -> int:
    rows = await cl.enumerate_current_contract_versions(engine, org_id)
    recs, vecs = [], []
    for r in rows:
        r = dict(r); r["org_id"] = str(org_id)
        rec = build_record(SHARED, r)
        recs.append(rec); vecs.append(embedder.embed([rec.text])[0])
    if recs:
        await index.upsert(recs, vecs, collection=new_collection)
    return len(recs)


async def _build_private(engine, index, embedder, org_id, user_id, new_collection) -> int:
    rows = await cl.enumerate_private(engine, org_id, user_id)
    recs, vecs = [], []
    for r in rows:
        r = dict(r); r["org_id"] = str(org_id); r["owner_user_id"] = str(user_id)
        rec = build_record(PRIVATE, r)
        recs.append(rec); vecs.append(embedder.embed([rec.text])[0])
    if recs:
        await index.upsert(recs, vecs, collection=new_collection)
    return len(recs)


async def full_reindex(engine, index, embedder, scope, targets, suffix) -> ReindexReport:
    """targets: list of {"org_id":..., "user_id":...?}. suffix names the new collection deterministically
    (caller supplies it, e.g. a build id) so reindex is reproducible and never depends on wall-clock."""
    if scope not in (PRIVATE, SHARED):
        raise ValueError("unknown scope %r" % (scope,))
    previous = await index.resolve(scope)
    new_collection = "%s_%s" % (BASE_COLLECTION[scope], suffix)
    await index.create_collection(new_collection)
    total = 0
    seen = []
    for t in targets:
        org = t["org_id"]
        if scope == SHARED:
            total += await _build_shared(engine, index, embedder, org, new_collection)
            seen.append(str(org))
        else:
            total += await _build_private(engine, index, embedder, org, t["user_id"], new_collection)
            seen.append("%s/%s" % (org, t["user_id"]))
    await index.swap(scope, new_collection)             # atomic pointer flip to the freshly built collection
    return ReindexReport(scope=scope, new_collection=new_collection, previous_collection=previous,
                         indexed=total, targets=seen)


async def rollback(index, scope, report: ReindexReport):
    """Repoint the alias/active pointer back to the collection that was live before the reindex."""
    await index.swap(scope, report.previous_collection)
