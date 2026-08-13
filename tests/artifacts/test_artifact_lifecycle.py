"""Artifact lifecycle (P4 §10) — runs against a local store and, when MINIO_ENDPOINT is set, S3/MinIO."""
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from conftest import eng, run, orgs, store
from enterprise_memory.artifacts.service import (ArtifactService, ArtifactBlocked, ArtifactNotAvailable,
                                                 ArtifactCorrupt)
from enterprise_memory.artifacts import records as R

pytestmark = pytest.mark.artifacts
CLS = R.SANITIZED_MODEL_RESPONSE


def _svc(store):
    return ArtifactService(store)


def test_put_get_and_idempotent_upload(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); e = eng("api")
        data = b"hello artifact world"
        ref1 = await svc.put(e, a["org"], CLS, data, content_type="text/plain", created_by=a["user"])
        assert ref1.deletion_state == "AVAILABLE" and ref1.byte_size == len(data)
        got = await svc.get(e, a["org"], ref1.artifact_id)
        assert got == data
        ref2 = await svc.put(e, a["org"], CLS, data, created_by=a["user"])   # same content -> idempotent
        assert ref2.artifact_id == ref1.artifact_id and ref2.object_key == ref1.object_key
        await e.dispose()
    run(body())


def test_cross_tenant_read_and_delete_denied(orgs, store):
    async def body():
        a = orgs["A"]; b = orgs["B"]; svc = _svc(store); e = eng("api")
        ref = await svc.put(e, a["org"], CLS, b"tenant A secret", created_by=a["user"])
        with pytest.raises(ArtifactNotAvailable):                 # org B cannot read A's artifact
            await svc.get(e, b["org"], ref.artifact_id)
        with pytest.raises(Exception):                            # org B cannot delete A's artifact
            await svc.request_delete(e, b["org"], ref.artifact_id)
        assert (await svc.get(e, a["org"], ref.artifact_id)) == b"tenant A secret"   # A still intact
        await e.dispose()
    run(body())


def test_hash_corruption_detected(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); e = eng("api")
        ref = await svc.put(e, a["org"], CLS, b"original bytes", created_by=a["user"])
        # tamper the stored object out-of-band
        await __import__("asyncio").to_thread(store.delete, ref.object_key)
        await __import__("asyncio").to_thread(store.put, ref.object_key, b"tampered bytes longer",
                                              R.sha256_hex(b"tampered bytes longer"))
        with pytest.raises(ArtifactCorrupt):
            await svc.get(e, a["org"], ref.artifact_id)
        await e.dispose()
    run(body())


def test_retention_and_legal_hold_block_delete(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); e = eng("api")
        future = (datetime.now(timezone.utc) + timedelta(days=1))
        r1 = await svc.put(e, a["org"], CLS, b"retained", created_by=a["user"], retain_until=future)
        with pytest.raises(ArtifactBlocked) as ex:
            await svc.request_delete(e, a["org"], r1.artifact_id)
        assert ex.value.reason == "retention"
        r2 = await svc.put(e, a["org"], CLS, b"held", created_by=a["user"], legal_hold=True)
        with pytest.raises(ArtifactBlocked) as ex2:
            await svc.request_delete(e, a["org"], r2.artifact_id)
        assert ex2.value.reason == "legal_hold"
        await e.dispose()
    run(body())


def test_logical_then_physical_deletion_confirmed(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); e = eng("api")
        ref = await svc.put(e, a["org"], CLS, b"to be deleted", created_by=a["user"])
        key = ref.object_key
        await svc.request_delete(e, a["org"], ref.artifact_id)
        with pytest.raises(ArtifactNotAvailable):                 # hidden from serving immediately
            await svc.get(e, a["org"], ref.artifact_id)
        res = await svc.run_physical_deletions(e, a["org"])
        assert (str(ref.artifact_id), "PHYSICALLY_CONFIRMED") in [(i, s) for i, s in res]
        assert not await __import__("asyncio").to_thread(store.exists, key)   # object gone, verified
        head = await svc.head(e, a["org"], ref.artifact_id)
        assert head.deletion_state == "PHYSICALLY_CONFIRMED"
        # deleted object does not reappear on a re-run
        assert await svc.run_physical_deletions(e, a["org"]) == []
        await e.dispose()
    run(body())


def test_repair_reconciles_failed_and_recoverable_uploads(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); su = eng("postgres"); e = eng("api")
        # orphan DB row: PENDING_UPLOAD with no object -> repair marks UPLOAD_FAILED
        aid = uuid.uuid4(); key = R.content_key(a["org"], CLS, "deadbeef" * 8)
        async with su.begin() as c:
            await c.execute(text(
                "INSERT INTO artifacts(id,org_id,kind,object_key,content_hash,artifact_class,"
                "deletion_state) VALUES(:i,:o,:k,:key,:h,:cls,'PENDING_UPLOAD')"),
                {"i": aid, "o": a["org"], "k": CLS, "key": key, "h": "deadbeef" * 8, "cls": CLS})
        # a PENDING_UPLOAD whose object DOES exist -> repair recovers to AVAILABLE
        data = b"recoverable"; h = R.sha256_hex(data); k2 = R.content_key(a["org"], CLS, h)
        await __import__("asyncio").to_thread(store.put, k2, data, h)
        aid2 = uuid.uuid4()
        async with su.begin() as c:
            await c.execute(text(
                "INSERT INTO artifacts(id,org_id,kind,object_key,content_hash,artifact_class,byte_size,"
                "deletion_state) VALUES(:i,:o,:k,:key,:h,:cls,:sz,'PENDING_UPLOAD')"),
                {"i": aid2, "o": a["org"], "k": k2 and CLS, "key": k2, "h": h, "cls": CLS, "sz": len(data)})
        # reconcile is READ-ONLY: it reports pending-with-object but changes nothing
        ro = await svc.reconcile(e, a["org"])
        assert str(aid2) in ro["pending_with_object"]
        async with su.connect() as c:
            st_before = (await c.execute(text("SELECT deletion_state FROM artifacts WHERE id=:i"),
                                         {"i": aid2})).scalar()
        assert st_before == "PENDING_UPLOAD"
        # explicit repair mutates
        rep = await svc.repair(e, a["org"])
        assert str(aid2) in rep["recovered_uploads"] and str(aid) in rep["failed_uploads"]
        async with su.connect() as c:
            st = (await c.execute(text("SELECT deletion_state FROM artifacts WHERE id=:i"), {"i": aid})).scalar()
        assert st == "UPLOAD_FAILED"
        await su.dispose(); await e.dispose()
    run(body())


def test_reconcile_readonly_detects_orphans(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); e = eng("api")
        ref = await svc.put(e, a["org"], CLS, b"present then gone", created_by=a["user"])
        # object deleted out-of-band -> AVAILABLE DB row missing its object
        await __import__("asyncio").to_thread(store.delete, ref.object_key)
        # an object with no DB row at all
        stray_key = R.content_key(a["org"], CLS, R.sha256_hex(b"stray"))
        await __import__("asyncio").to_thread(store.put, stray_key, b"stray", R.sha256_hex(b"stray"))
        rep = await svc.reconcile(e, a["org"])
        assert ref.artifact_id in rep["db_row_missing_object"]
        assert stray_key in rep["object_missing_db_row"] and rep["has_drift"]
        await e.dispose()
    run(body())


def test_chained_artifact_audit(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); su = eng("postgres"); e = eng("api")
        ref = await svc.put(e, a["org"], CLS, b"audited", created_by=a["user"])
        await svc.request_delete(e, a["org"], ref.artifact_id, actor=a["user"])
        async with su.connect() as c:
            rows = (await c.execute(text(
                "SELECT previous_hash, event_hash, detail_json->>'new_state' FROM audit_events"
                " WHERE org_id=:o AND event_type='ARTIFACT_LIFECYCLE' ORDER BY created_at"),
                {"o": a["org"]})).fetchall()
        await su.dispose(); await e.dispose()
        states = [r[2] for r in rows]
        assert "AVAILABLE" in states and "DELETE_REQUESTED" in states
        # the chain links: some later row's previous_hash equals an earlier row's event_hash
        hashes = {r[1] for r in rows}
        assert any(r[0] in hashes for r in rows if r[0])          # chained (non-empty previous_hash links)
    run(body())


def test_presigned_get_available_only(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); e = eng("api")
        ref = await svc.put(e, a["org"], CLS, b"presign me", created_by=a["user"])
        url = await svc.presigned_get(e, a["org"], ref.artifact_id, ttl_seconds=60)
        assert isinstance(url, str) and url
        await svc.request_delete(e, a["org"], ref.artifact_id)
        with pytest.raises(ArtifactNotAvailable):                 # no presign for a hidden artifact
            await svc.presigned_get(e, a["org"], ref.artifact_id)
        await e.dispose()
    run(body())
