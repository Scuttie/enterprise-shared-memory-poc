"""Full reindex with pre-swap validation, atomic alias swap, and rollback (P2 / P2.1). A rebuild NEVER
mutates the live collection: it builds a brand-new physical collection from the canonical PostgreSQL set,
VALIDATES the shadow collection against the authoritative set (counts, exact id-set, hashes, tenant/owner,
scope/kind, schema version, and a representative search), and only on a FULL PASS atomically repoints the
scope's *_current alias to it. Any validation failure leaves the live aliases unchanged. Rollback repoints
the alias back to the previous collection — the old data was never touched, so rollback is instantaneous."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from .models import PRIVATE, SHARED, BASE_COLLECTION, ObjectType, INDEX_SCHEMA_VERSION
from . import canonical_loaders as cl
from .projection import build_record


class ReindexValidationError(RuntimeError):
    def __init__(self, validation):
        self.validation = validation
        super().__init__("reindex validation failed: %r" % (validation.to_dict(),))


@dataclass
class ReindexValidation:
    scope: str
    expected: int = 0
    actual: int = 0
    missing: List[str] = field(default_factory=list)
    extra: List[str] = field(default_factory=list)
    wrong_hash: List[str] = field(default_factory=list)
    wrong_tenant: List[str] = field(default_factory=list)
    wrong_owner: List[str] = field(default_factory=list)
    wrong_scope: List[str] = field(default_factory=list)
    wrong_schema: List[str] = field(default_factory=list)
    representative_search_ok: bool = True

    @property
    def ok(self) -> bool:
        return (not (self.missing or self.extra or self.wrong_hash or self.wrong_tenant
                     or self.wrong_owner or self.wrong_scope or self.wrong_schema)
                and self.representative_search_ok)

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in ("scope", "expected", "actual", "missing", "extra", "wrong_hash",
                                           "wrong_tenant", "wrong_owner", "wrong_scope", "wrong_schema",
                                           "representative_search_ok")}
        d["ok"] = self.ok
        return d


@dataclass
class ReindexReport:
    scope: str
    new_collection: str
    previous_collection: str
    indexed: int = 0
    targets: List[str] = field(default_factory=list)
    validation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"scope": self.scope, "new_collection": self.new_collection,
                "previous_collection": self.previous_collection, "indexed": self.indexed,
                "targets": self.targets, "validation": self.validation}


async def _build(engine, index, embedder, scope, target, new_collection):
    """Index one target's canonical set into new_collection; return the built records."""
    org = target["org_id"]
    if scope == SHARED:
        rows = await cl.enumerate_current_contract_versions(engine, org)
    else:
        rows = await cl.enumerate_private(engine, org, target["user_id"])
    recs, vecs = [], []
    for r in rows:
        r = dict(r); r["org_id"] = str(org)
        if scope == PRIVATE:
            r["owner_user_id"] = str(target["user_id"])
        rec = build_record(scope, r)
        recs.append(rec); vecs.append(embedder.embed([rec.text])[0])
    if recs:
        await index.upsert(recs, vecs, collection=new_collection)
    return recs


async def validate_shadow(index, embedder, scope, collection, recs) -> ReindexValidation:
    want_kind = ObjectType.CONTRACT_VERSION.value if scope == SHARED else ObjectType.PRIVATE_EPISODE.value
    expected = {r.canonical_version_id: r for r in recs}
    v = ReindexValidation(scope=scope, expected=len(expected))
    pts = await index.scroll(scope, collection=collection)
    actual = {}
    for p in pts:
        pl = p["payload"]; vid = str(pl.get("canonical_version_id")); actual[vid] = pl
        if pl.get("scope") != scope or pl.get("object_kind") != want_kind:
            v.wrong_scope.append(vid)
        if int(pl.get("index_schema_version", -1)) != INDEX_SCHEMA_VERSION:
            v.wrong_schema.append(vid)
        exp = expected.get(vid)
        if exp is not None:
            if str(pl.get("canonical_content_hash")) != str(exp.canonical_content_hash):
                v.wrong_hash.append(vid)
            if str(pl.get("org_id")) != str(exp.org_id):
                v.wrong_tenant.append(vid)
            if scope == PRIVATE and str(pl.get("owner_user_id")) != str(exp.owner_user_id):
                v.wrong_owner.append(vid)
    v.actual = len(actual)
    v.missing = [vid for vid in expected if vid not in actual]
    v.extra = [vid for vid in actual if vid not in expected]
    # representative search against the shadow collection
    if recs:
        s = recs[0]
        hits = await index.search(scope, embedder.embed([s.text])[0], s.org_id,
                                  owner_user_id=(s.owner_user_id if scope == PRIVATE else None),
                                  limit=64, collection=collection)
        v.representative_search_ok = any(c.pid == s.pid for c in hits)
    return v


async def full_reindex(engine, index, embedder, scope, targets, suffix, after_build=None) -> ReindexReport:
    """targets: list of {"org_id":..., "user_id":...?}. suffix names the new collection deterministically
    (caller supplies it, e.g. a build id) so reindex is reproducible and never depends on wall-clock.
    after_build (async, optional) runs against the shadow before validation — used by tests to inject
    corruption and prove a bad shadow never swaps the live alias."""
    if scope not in (PRIVATE, SHARED):
        raise ValueError("unknown scope %r" % (scope,))
    previous = await index.resolve(scope)
    new_collection = "%s_%s" % (BASE_COLLECTION[scope], suffix)
    await index.create_collection(new_collection)
    all_recs, seen = [], []
    for t in targets:
        recs = await _build(engine, index, embedder, scope, t, new_collection)
        all_recs.extend(recs)
        seen.append(str(t["org_id"]) if scope == SHARED else "%s/%s" % (t["org_id"], t["user_id"]))
    if after_build is not None:
        await after_build(index, new_collection)
    validation = await validate_shadow(index, embedder, scope, new_collection, all_recs)
    if not validation.ok:
        raise ReindexValidationError(validation)          # aliases left UNCHANGED
    await index.swap(scope, new_collection)               # atomic pointer flip on full pass only
    return ReindexReport(scope=scope, new_collection=new_collection, previous_collection=previous,
                         indexed=len(all_recs), targets=seen, validation=validation.to_dict())


async def rollback(index, scope, report: ReindexReport):
    """Repoint the alias back to the collection that was live before the reindex."""
    await index.swap(scope, report.previous_collection)
