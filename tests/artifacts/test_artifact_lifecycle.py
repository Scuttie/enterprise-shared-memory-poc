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


def test_failed_upload_reconciliation(orgs, store):
    async def body():
        a = orgs["A"]; svc = _svc(store); su = eng("postgres"); e = eng("api")
        # simulate an orphan DB row: PENDING_UPLOAD with no object in the store
        aid = uuid.uuid4(); key = R.content_key(a["org"], CLS, "deadbeef" * 8)
        async with su.begin() as c:
            await c.execute(text(
                "INSERT INTO artifacts(id,org_id,kind,object_key,content_hash,artifact_class,"
                "deletion_state) VALUES(:i,:o,:k,:key,:h,:cls,'PENDING_UPLOAD')"),
                {"i": aid, "o": a["org"], "k": CLS, "key": key, "h": "deadbeef" * 8, "cls": CLS})
        rep = await svc.reconcile(e, a["org"])
        async with su.connect() as c:
            st = (await c.execute(text("SELECT deletion_state FROM artifacts WHERE id=:i"), {"i": aid})).scalar()
        assert st == "UPLOAD_FAILED"                              # no object -> failed upload
        # a PENDING_UPLOAD whose object DOES exist is recovered to AVAILABLE
        data = b"recoverable"; h = R.sha256_hex(data); k2 = R.content_key(a["org"], CLS, h)
        await __import__("asyncio").to_thread(store.put, k2, data, h)
        aid2 = uuid.uuid4()
        async with su.begin() as c:
            await c.execute(text(
                "INSERT INTO artifacts(id,org_id,kind,object_key,content_hash,artifact_class,byte_size,"
                "deletion_state) VALUES(:i,:o,:k,:key,:h,:cls,:sz,'PENDING_UPLOAD')"),
                {"i": aid2, "o": a["org"], "k": CLS, "key": k2, "h": h, "cls": CLS, "sz": len(data)})
        rep2 = await svc.reconcile(e, a["org"])
        assert str(aid2) in rep2["recovered_uploads"]
        await su.dispose(); await e.dispose()
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
