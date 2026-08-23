"""P2.1 §10 — outbox lease heartbeat + append-only index audit."""
import uuid
import pytest
from sqlalchemy import text
from conftest import eng, run, tenant_tx
from enterprise_memory.persistence.postgres import (publish_outbox, claim_outbox_event, heartbeat_outbox,
                                                    emit_index_audit)

pytestmark = pytest.mark.postgres


def test_heartbeat_extends_and_enforces_owner(seeded):
    async def body():
        e = eng("api"); idx = eng("index"); su = eng("postgres"); a = seeded["A"]; aid = uuid.uuid4()
        async with tenant_tx(e, a["org"], a["user"]) as c:
            await publish_outbox(c, a["org"], "REINDEX", "contract", aid, 1, {})
        ev = await claim_outbox_event(idx, "hw", lease_seconds=30)
        assert ev
        async with su.connect() as c:
            before = (await c.execute(text("SELECT lease_expires_at FROM outbox_events WHERE id=:i"),
                                      {"i": ev["id"]})).scalar()
        await heartbeat_outbox(idx, ev["id"], "hw", ev["lease_token"], lease_seconds=300)
        async with su.connect() as c:
            after = (await c.execute(text("SELECT lease_expires_at FROM outbox_events WHERE id=:i"),
                                     {"i": ev["id"]})).scalar()
        assert after > before                                  # lease extended
        with pytest.raises(PermissionError):                   # wrong worker
            await heartbeat_outbox(idx, ev["id"], "other", ev["lease_token"], 60)
        with pytest.raises(PermissionError):                   # wrong token
            await heartbeat_outbox(idx, ev["id"], "hw", str(uuid.uuid4()), 60)
        for x in (e, idx, su):
            await x.dispose()
    run(body())


def test_index_audit_append_only(seeded):
    async def body():
        idx = eng("index"); a = seeded["A"]
        await emit_index_audit(idx, a["org"], result="CONTRACT_INDEX:upserted", object_kind="contract_version",
                               canonical_version_id=str(uuid.uuid4()), qdrant_operation="upsert",
                               point_id="p1", collection="enterprise_shared_current")
        with pytest.raises(Exception):                         # UPDATE denied
            async with tenant_tx(idx, a["org"]) as c:
                await c.execute(text("UPDATE index_audit_events SET result='x' WHERE org_id=:o"), {"o": a["org"]})
        with pytest.raises(Exception):                         # DELETE denied
            async with tenant_tx(idx, a["org"]) as c:
                await c.execute(text("DELETE FROM index_audit_events WHERE org_id=:o"), {"o": a["org"]})
        async with tenant_tx(idx, a["org"]) as c:
            n = (await c.execute(text("SELECT count(*) FROM index_audit_events WHERE org_id=:o"),
                                 {"o": a["org"]})).scalar()
        assert n == 1
        await idx.dispose()
    run(body())
