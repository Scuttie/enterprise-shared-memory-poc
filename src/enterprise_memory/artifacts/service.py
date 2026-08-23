"""Artifact service (P4 §8-§10 + P4.1 §2). PostgreSQL is the authoritative metadata + lifecycle state
machine; the object store holds content-addressed, SHA-256-verified bytes. The object write and the DB row
are not one distributed transaction, so the service drives a durable state machine, verifies integrity on
write (read-back hash + tenant-prefixed key), keeps a CHAINED append-only audit, and offers a read-only
bidirectional reconciliation with a separate explicit repair. Retention and legal hold block physical
deletion; physical deletion is confirmed only after the object is verified absent."""
from __future__ import annotations
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from ..persistence.tenant_context import tenant_tx
from . import records as R
from .store import ArtifactStoreError


class ArtifactError(Exception):
    pass


class ArtifactBlocked(ArtifactError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class ArtifactNotAvailable(ArtifactError):
    pass


class ArtifactCorrupt(ArtifactError):
    pass


_COLS = ("id", "org_id", "object_key", "content_hash", "byte_size", "content_type", "artifact_class",
         "deletion_state", "retention_class", "retain_until", "legal_hold", "created_by", "created_at")
_SEL = ("SELECT id,org_id,object_key,content_hash,byte_size,content_type,artifact_class,deletion_state,"
        "retention_class,retain_until,legal_hold,created_by,created_at FROM artifacts")


def _ref(row) -> R.ArtifactRef:
    d = dict(zip(_COLS, row))
    return R.ArtifactRef(
        artifact_id=str(d["id"]), org_id=str(d["org_id"]), object_key=d["object_key"],
        content_hash=d["content_hash"], byte_size=d["byte_size"], content_type=d["content_type"],
        artifact_class=d["artifact_class"], deletion_state=d["deletion_state"],
        retention_class=d["retention_class"],
        retain_until=(d["retain_until"].isoformat() if d["retain_until"] else None),
        legal_hold=bool(d["legal_hold"]), created_by=(str(d["created_by"]) if d["created_by"] else None),
        created_at=(d["created_at"].isoformat() if d["created_at"] else None))


class ArtifactService:
    def __init__(self, store):
        self._store = store

    async def _t(self, fn, *a):
        return await asyncio.to_thread(fn, *a)

    # ---------------------------------------------------------------- chained append-only audit
    async def _audit(self, conn, org_id, artifact_id, prior_state, new_state, *, object_hash=None,
                     result="ok", actor=None, request_id=None):
        # §1.2: serialize the per-org audit chain so two concurrent transitions cannot read the same
        # previous_hash and fork the ledger. The advisory lock is transaction-scoped.
        await conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:o), 0)"), {"o": str(org_id)})
        prev = (await conn.execute(text(
            "SELECT event_hash FROM audit_events WHERE org_id=:o ORDER BY created_at DESC LIMIT 1"),
            {"o": org_id})).scalar() or ""
        detail = {"artifact_id": str(artifact_id), "prior_state": prior_state, "new_state": new_state,
                  "object_hash": object_hash, "result": result,
                  "actor": (str(actor) if actor else None), "request_id": request_id}
        payload = json.dumps(detail, sort_keys=True)
        ev_hash = R.sha256_hex(("%s|%s" % (prev, payload)).encode())
        await conn.execute(text(
            "INSERT INTO audit_events(org_id,actor_user_id,request_id,event_type,subject_type,subject_id,"
            "detail_json,previous_hash,event_hash) VALUES(:o,:a,:rq,'ARTIFACT_LIFECYCLE','artifact',:s,"
            "cast(:d as jsonb),:p,:h)"),
            {"o": org_id, "a": actor, "rq": request_id, "s": str(artifact_id), "d": payload,
             "p": prev, "h": ev_hash})

    # ---------------------------------------------------------------- write
    async def put(self, engine, org_id, artifact_class, data: bytes, *, content_type=None, created_by=None,
                  retention_class="default", retain_until=None, legal_hold=False, metadata=None,
                  job_id=None, request_id=None) -> R.ArtifactRef:
        if artifact_class not in R.ARTIFACT_CLASSES:
            raise ArtifactError("unknown artifact_class %r" % (artifact_class,))
        h = R.sha256_hex(data)
        key = R.content_key(org_id, artifact_class, h)
        # Per-job evidence (ARTIFACT_PER_JOB): a multi-arm experiment in ONE org (§5) produces byte-identical
        # artifacts across arms at temperature 0 (e.g. a no-injection arm == the no-memory arm for the same
        # task); content-addressed dedup would then drop the later arm's per-job artifact rows and fail the
        # terminal evidence gate. Appending the job id keeps dedup WITHIN a job but gives each job its own
        # evidence. Off by default (other workflows keep pure content addressing).
        if job_id is not None and os.environ.get("ARTIFACT_PER_JOB"):
            key = "%s/%s" % (key, job_id)
        if not key.startswith("org/%s/" % org_id):                # tenant-prefixed key (defence)
            raise ArtifactError("key not tenant-prefixed")
        aid = str(uuid.uuid4())
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE org_id=:o AND object_key=:k"),
                                   {"o": org_id, "k": key})).first()
            if row is not None and row[7] == R.AVAILABLE:
                existing_ref = _ref(row)                          # verify integrity before returning (§1.1)
            else:
                existing_ref = None
        if existing_ref is not None:
            head = await self._t(self._store.head, existing_ref.object_key)
            ok = bool(head) and int(head.get("size", -1)) == len(data)
            if ok and head.get("sha256") is not None:
                ok = head.get("sha256") == h
            if ok:
                ok = await self._t(self._store.verify, existing_ref.object_key, h)
            if not ok:
                async with tenant_tx(engine, org_id) as c:
                    await c.execute(text("UPDATE artifacts SET deletion_state='DELETE_FAILED',"
                                         " optimistic_version=optimistic_version+1 WHERE id=:i"),
                                    {"i": existing_ref.artifact_id})
                    await self._audit(c, org_id, existing_ref.artifact_id, R.AVAILABLE, "DELETE_FAILED",
                                      object_hash=h, result="integrity_failure", request_id=request_id)
                raise ArtifactCorrupt("existing AVAILABLE artifact failed integrity verification")
            return existing_ref                                   # idempotent upload, integrity confirmed
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE org_id=:o AND object_key=:k"),
                                   {"o": org_id, "k": key})).first()
            if row is None:
                await c.execute(text(
                    "INSERT INTO artifacts(id,org_id,job_id,kind,object_key,content_hash,artifact_class,"
                    "content_type,retention_class,retain_until,legal_hold,created_by,deletion_state,"
                    "metadata_json) VALUES(:i,:o,:j,:kind,:k,:h,:cls,:ct,:rc,:ru,:lh,:cb,'PENDING_UPLOAD',"
                    "cast(:md as jsonb)) ON CONFLICT (org_id,object_key) DO NOTHING"),
                    {"i": aid, "o": org_id, "j": job_id, "kind": artifact_class, "k": key, "h": h,
                     "cls": artifact_class, "ct": content_type, "rc": retention_class, "ru": retain_until,
                     "lh": legal_hold, "cb": created_by, "md": json.dumps(metadata or {})})
                aid = str((await c.execute(text("SELECT id FROM artifacts WHERE org_id=:o AND object_key=:k"),
                                           {"o": org_id, "k": key})).scalar())
            else:
                aid = str(row[0])
        try:
            await self._t(self._store.put, key, data, h)
            head = await self._t(self._store.head, key)           # exists + size (+ sha metadata if present)
            if not head or int(head.get("size", -1)) != len(data):
                raise ArtifactStoreError("post-write size mismatch")
            if head.get("sha256") is not None and head.get("sha256") != h:
                raise ArtifactStoreError("post-write hash-metadata mismatch")
            if not await self._t(self._store.verify, key, h):     # read-back hash — strongest check
                raise ArtifactStoreError("post-write read-back hash mismatch")
        except Exception:
            async with tenant_tx(engine, org_id) as c:
                await c.execute(text("UPDATE artifacts SET deletion_state='UPLOAD_FAILED',"
                                     " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                await self._audit(c, org_id, aid, "PENDING_UPLOAD", "UPLOAD_FAILED", object_hash=h,
                                  result="failed", actor=created_by, request_id=request_id)
            raise
        async with tenant_tx(engine, org_id) as c:
            await c.execute(text("UPDATE artifacts SET deletion_state='AVAILABLE', byte_size=:sz,"
                                 " optimistic_version=optimistic_version+1 WHERE id=:i"),
                            {"sz": len(data), "i": aid})
            await self._audit(c, org_id, aid, "PENDING_UPLOAD", "AVAILABLE", object_hash=h,
                              actor=created_by, request_id=request_id)
            row = (await c.execute(text(_SEL + " WHERE id=:i"), {"i": aid})).first()
        return _ref(row)

    # ---------------------------------------------------------------- read
    async def get(self, engine, org_id, artifact_id) -> bytes:
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE id=:i"), {"i": artifact_id})).first()
        if row is None or row[7] not in R.SERVABLE_STATES:
            raise ArtifactNotAvailable("not available")
        data = await self._t(self._store.get, row[2])
        if R.sha256_hex(data) != row[3]:
            raise ArtifactCorrupt("stored content hash mismatch")
        return data

    async def head(self, engine, org_id, artifact_id):
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE id=:i"), {"i": artifact_id})).first()
        return None if row is None else _ref(row)

    async def list_metadata(self, engine, org_id, artifact_class=None):
        q = _SEL + " WHERE org_id=:o"
        params = {"o": org_id}
        if artifact_class:
            q += " AND artifact_class=:c"; params["c"] = artifact_class
        q += " ORDER BY created_at DESC"
        async with tenant_tx(engine, org_id) as c:
            rows = (await c.execute(text(q), params)).fetchall()
        return [_ref(r) for r in rows]

    async def presigned_get(self, engine, org_id, artifact_id, ttl_seconds=300) -> str:
        ref = await self.head(engine, org_id, artifact_id)
        if ref is None or ref.deletion_state not in R.SERVABLE_STATES:
            raise ArtifactNotAvailable("not available")
        return await self._t(self._store.create_presigned_get, ref.object_key, ttl_seconds)

    # ---------------------------------------------------------------- deletion lifecycle
    async def request_delete(self, engine, org_id, artifact_id, actor=None, request_id=None):
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE id=:i"), {"i": artifact_id})).first()
            if row is None:
                raise ArtifactError("not found")
            if bool(row[10]):
                raise ArtifactBlocked("legal_hold")
            if row[9] is not None and row[9] > datetime.now(timezone.utc):
                raise ArtifactBlocked("retention")
            await c.execute(text("UPDATE artifacts SET deletion_state='DELETE_REQUESTED',"
                                 " optimistic_version=optimistic_version+1"
                                 " WHERE id=:i AND deletion_state='AVAILABLE'"), {"i": artifact_id})
            await self._audit(c, org_id, artifact_id, "AVAILABLE", "DELETE_REQUESTED", actor=actor,
                              request_id=request_id)

    async def run_physical_deletions(self, engine, org_id) -> list:
        async with tenant_tx(engine, org_id) as c:
            rows = (await c.execute(text(
                "SELECT id, object_key, content_hash, deletion_state FROM artifacts WHERE org_id=:o"
                " AND deletion_state IN ('DELETE_REQUESTED','LOGICALLY_DELETED')"
                " AND legal_hold=false AND (retain_until IS NULL OR retain_until<=now())"),
                {"o": org_id})).fetchall()
        results = []
        for aid, key, chash, state in rows:
            if state == "DELETE_REQUESTED":                       # advance through LOGICALLY_DELETED
                async with tenant_tx(engine, org_id) as c:
                    await c.execute(text("UPDATE artifacts SET deletion_state='LOGICALLY_DELETED',"
                                         " logical_deletion_at=now(), optimistic_version=optimistic_version+1"
                                         " WHERE id=:i"), {"i": aid})
                    await self._audit(c, org_id, aid, "DELETE_REQUESTED", "LOGICALLY_DELETED")
            async with tenant_tx(engine, org_id) as c:
                await c.execute(text("UPDATE artifacts SET deletion_state='PHYSICAL_DELETE_PENDING',"
                                     " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                await self._audit(c, org_id, aid, "LOGICALLY_DELETED", "PHYSICAL_DELETE_PENDING")
            try:
                await self._t(self._store.delete, key)
                if await self._t(self._store.exists, key):        # verify absent BEFORE confirming
                    raise ArtifactStoreError("object still present after delete")
                async with tenant_tx(engine, org_id) as c:
                    await c.execute(text("UPDATE artifacts SET deletion_state='PHYSICALLY_CONFIRMED',"
                                         " physical_deletion_at=now(), optimistic_version=optimistic_version+1"
                                         " WHERE id=:i"), {"i": aid})
                    await self._audit(c, org_id, aid, "PHYSICAL_DELETE_PENDING", "PHYSICALLY_CONFIRMED",
                                      object_hash=chash)
                results.append((str(aid), "PHYSICALLY_CONFIRMED"))
            except Exception:
                async with tenant_tx(engine, org_id) as c:
                    await c.execute(text("UPDATE artifacts SET deletion_state='DELETE_FAILED',"
                                         " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                    await self._audit(c, org_id, aid, "PHYSICAL_DELETE_PENDING", "DELETE_FAILED",
                                      result="failed")
                results.append((str(aid), "DELETE_FAILED"))
        return results

    # ---------------------------------------------------------------- bidirectional reconciliation (read-only)
    async def reconcile(self, engine, org_id) -> dict:
        async with tenant_tx(engine, org_id) as c:
            rows = (await c.execute(text("SELECT id, object_key, content_hash, deletion_state FROM artifacts"
                                         " WHERE org_id=:o"), {"o": org_id})).fetchall()
        db = {key: (str(aid), chash, state) for aid, key, chash, state in rows}
        store_keys = set(await self._t(self._store.list_keys, "org/%s/" % org_id))
        rep = {"db_row_missing_object": [], "object_missing_db_row": [], "available_corrupted": [],
               "pending_with_object": [], "confirmed_object_reappeared": [], "wrong_tenant_prefix": []}
        for key, (aid, chash, state) in db.items():
            if not key.startswith("org/%s/" % org_id):
                rep["wrong_tenant_prefix"].append(aid); continue
            exists = key in store_keys
            if state == R.AVAILABLE:
                if not exists:
                    rep["db_row_missing_object"].append(aid)
                elif not await self._t(self._store.verify, key, chash):
                    rep["available_corrupted"].append(aid)
            elif state == R.PENDING_UPLOAD and exists:
                rep["pending_with_object"].append(aid)
            elif state == R.PHYSICALLY_CONFIRMED and exists:
                rep["confirmed_object_reappeared"].append(aid)
        for key in store_keys:
            if key not in db:
                rep["object_missing_db_row"].append(key)
        rep["has_drift"] = any(v for k, v in rep.items() if k != "has_drift")
        return rep

    async def repair(self, engine, org_id) -> dict:
        """Explicit (non-default) repair of the low-risk classes discovered by reconcile()."""
        async with tenant_tx(engine, org_id) as c:
            rows = (await c.execute(text("SELECT id, object_key, content_hash, deletion_state FROM artifacts"
                                         " WHERE org_id=:o AND deletion_state IN ('PENDING_UPLOAD','AVAILABLE')"),
                                    {"o": org_id})).fetchall()
        recovered, failed, orphan_db = [], [], []
        for aid, key, chash, state in rows:
            exists = await self._t(self._store.exists, key)
            async with tenant_tx(engine, org_id) as c:
                if state == R.PENDING_UPLOAD:
                    if exists and await self._t(self._store.verify, key, chash):
                        await c.execute(text("UPDATE artifacts SET deletion_state='AVAILABLE',"
                                             " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                        await self._audit(c, org_id, aid, "PENDING_UPLOAD", "AVAILABLE", object_hash=chash)
                        recovered.append(str(aid))
                    else:
                        await c.execute(text("UPDATE artifacts SET deletion_state='UPLOAD_FAILED',"
                                             " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                        await self._audit(c, org_id, aid, "PENDING_UPLOAD", "UPLOAD_FAILED", result="failed")
                        failed.append(str(aid))
                elif state == R.AVAILABLE and not exists:
                    await c.execute(text("UPDATE artifacts SET deletion_state='DELETE_FAILED',"
                                         " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                    await self._audit(c, org_id, aid, "AVAILABLE", "DELETE_FAILED", result="orphan_db")
                    orphan_db.append(str(aid))
        return {"recovered_uploads": recovered, "failed_uploads": failed, "orphan_db_rows": orphan_db}
