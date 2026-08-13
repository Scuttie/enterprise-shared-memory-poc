"""Artifact service (P4 §8-§10). PostgreSQL is the authoritative metadata + lifecycle state machine; the
object store holds content-addressed, SHA-256-verified bytes. The object write and the DB row are not one
distributed transaction, so the service drives a durable state machine and offers reconciliation. All DB
access is RLS-scoped by org; keys are tenant-prefixed and content-addressed — a caller never supplies a key.
Retention and legal hold block physical deletion; physical deletion is only confirmed after the object is
verified absent."""
from __future__ import annotations
import asyncio
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from ..persistence.tenant_context import tenant_tx
from . import records as R
from .store import HashMismatch, ArtifactStoreError


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


_SEL = ("SELECT id,org_id,object_key,content_hash,byte_size,content_type,artifact_class,deletion_state,"
        "retention_class,retain_until,legal_hold,created_by,created_at FROM artifacts")


class ArtifactService:
    def __init__(self, store):
        self._store = store

    async def _to_thread(self, fn, *a):
        return await asyncio.to_thread(fn, *a)

    async def put(self, engine, org_id, artifact_class, data: bytes, *, content_type=None, created_by=None,
                  retention_class="default", retain_until=None, legal_hold=False, metadata=None,
                  job_id=None) -> R.ArtifactRef:
        if artifact_class not in R.ARTIFACT_CLASSES:
            raise ArtifactError("unknown artifact_class %r" % (artifact_class,))
        h = R.sha256_hex(data)
        key = R.content_key(org_id, artifact_class, h)
        aid = str(uuid.uuid4())
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE org_id=:o AND object_key=:k"),
                                   {"o": org_id, "k": key})).first()
            if row is not None and row[7] == R.AVAILABLE:
                return _ref(row)                              # idempotent upload
            if row is None:
                await c.execute(text(
                    "INSERT INTO artifacts(id,org_id,job_id,kind,object_key,content_hash,artifact_class,"
                    "content_type,retention_class,retain_until,legal_hold,created_by,deletion_state,"
                    "metadata_json) VALUES(:i,:o,:j,:kind,:k,:h,:cls,:ct,:rc,:ru,:lh,:cb,'PENDING_UPLOAD',"
                    "cast(:md as jsonb)) ON CONFLICT (org_id,object_key) DO NOTHING"),
                    {"i": aid, "o": org_id, "j": job_id, "kind": artifact_class, "k": key, "h": h,
                     "cls": artifact_class, "ct": content_type, "rc": retention_class, "ru": retain_until,
                     "lh": legal_hold, "cb": created_by, "md": json.dumps(metadata or {})})
                got = (await c.execute(text("SELECT id FROM artifacts WHERE org_id=:o AND object_key=:k"),
                                       {"o": org_id, "k": key})).scalar()
                aid = str(got)
            else:
                aid = str(row[0])
        try:
            await self._to_thread(self._store.put, key, data, h)
            head = await self._to_thread(self._store.head, key)
            if not head or int(head.get("size", -1)) != len(data):
                raise ArtifactStoreError("post-write head mismatch")
        except Exception:
            async with tenant_tx(engine, org_id) as c:
                await c.execute(text("UPDATE artifacts SET deletion_state='UPLOAD_FAILED',"
                                     " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
            raise
        async with tenant_tx(engine, org_id) as c:
            await c.execute(text("UPDATE artifacts SET deletion_state='AVAILABLE', byte_size=:sz,"
                                 " optimistic_version=optimistic_version+1 WHERE id=:i"),
                            {"sz": len(data), "i": aid})
            row = (await c.execute(text(_SEL + " WHERE id=:i"), {"i": aid})).first()
        return _ref(row)

    async def get(self, engine, org_id, artifact_id) -> bytes:
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE id=:i"), {"i": artifact_id})).first()
        if row is None or row[7] not in R.SERVABLE_STATES:
            raise ArtifactNotAvailable("not available")
        data = await self._to_thread(self._store.get, row[2])
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
        return await self._to_thread(self._store.create_presigned_get, ref.object_key, ttl_seconds)

    async def request_delete(self, engine, org_id, artifact_id, actor=None):
        async with tenant_tx(engine, org_id) as c:
            row = (await c.execute(text(_SEL + " WHERE id=:i"), {"i": artifact_id})).first()
            if row is None:
                raise ArtifactError("not found")
            if bool(row[10]):
                raise ArtifactBlocked("legal_hold")
            if row[9] is not None and row[9] > datetime.now(timezone.utc):
                raise ArtifactBlocked("retention")
            # hide from serving immediately (logical deletion)
            await c.execute(text("UPDATE artifacts SET deletion_state='LOGICALLY_DELETED',"
                                 " logical_deletion_at=now(), optimistic_version=optimistic_version+1"
                                 " WHERE id=:i AND deletion_state='AVAILABLE'"), {"i": artifact_id})

    async def run_physical_deletions(self, engine, org_id) -> list:
        async with tenant_tx(engine, org_id) as c:
            rows = (await c.execute(text(
                "SELECT id, object_key FROM artifacts WHERE org_id=:o AND deletion_state='LOGICALLY_DELETED'"
                " AND legal_hold=false AND (retain_until IS NULL OR retain_until<=now())"),
                {"o": org_id})).fetchall()
        results = []
        for aid, key in rows:
            async with tenant_tx(engine, org_id) as c:
                await c.execute(text("UPDATE artifacts SET deletion_state='PHYSICAL_DELETE_PENDING',"
                                     " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
            try:
                await self._to_thread(self._store.delete, key)
                if await self._to_thread(self._store.exists, key):   # verify absent BEFORE confirming
                    raise ArtifactStoreError("object still present after delete")
                async with tenant_tx(engine, org_id) as c:
                    await c.execute(text("UPDATE artifacts SET deletion_state='PHYSICALLY_CONFIRMED',"
                                         " physical_deletion_at=now(), optimistic_version=optimistic_version+1"
                                         " WHERE id=:i"), {"i": aid})
                    await self._audit(c, org_id, aid, "ARTIFACT_PHYSICAL_DELETE")
                results.append((str(aid), "PHYSICALLY_CONFIRMED"))
            except Exception:
                async with tenant_tx(engine, org_id) as c:
                    await c.execute(text("UPDATE artifacts SET deletion_state='DELETE_FAILED',"
                                         " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                results.append((str(aid), "DELETE_FAILED"))
        return results

    async def reconcile(self, engine, org_id) -> dict:
        async with tenant_tx(engine, org_id) as c:
            rows = (await c.execute(text("SELECT id, object_key, deletion_state FROM artifacts"
                                         " WHERE org_id=:o"), {"o": org_id})).fetchall()
        recovered, orphan_db = [], []
        for aid, key, state in rows:
            exists = await self._to_thread(self._store.exists, key)
            if state == R.PENDING_UPLOAD:
                async with tenant_tx(engine, org_id) as c:
                    if exists:
                        await c.execute(text("UPDATE artifacts SET deletion_state='AVAILABLE',"
                                             " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                        recovered.append(str(aid))
                    else:
                        await c.execute(text("UPDATE artifacts SET deletion_state='UPLOAD_FAILED',"
                                             " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
            elif state == R.AVAILABLE and not exists:
                async with tenant_tx(engine, org_id) as c:
                    await c.execute(text("UPDATE artifacts SET deletion_state='DELETE_FAILED',"
                                         " optimistic_version=optimistic_version+1 WHERE id=:i"), {"i": aid})
                orphan_db.append(str(aid))
        return {"recovered_uploads": recovered, "orphan_db_rows": orphan_db}

    async def _audit(self, conn, org_id, subject_id, event_type):
        ev_hash = R.sha256_hex(("%s|%s|%s" % (org_id, subject_id, event_type)).encode())
        await conn.execute(text(
            "INSERT INTO audit_events(org_id,event_type,subject_type,subject_id,detail_json,previous_hash,"
            "event_hash) VALUES(:o,:t,'artifact',:s,'{}',:p,:h)"),
            {"o": org_id, "t": event_type, "s": str(subject_id), "p": "", "h": ev_hash})
