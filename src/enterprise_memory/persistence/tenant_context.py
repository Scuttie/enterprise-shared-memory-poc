"""Transaction-local tenant context (§8). set_config(..., true) makes app.org_id/app.user_id local to the
transaction, so no value leaks to the next pooled borrower."""
from __future__ import annotations
from contextlib import asynccontextmanager
from sqlalchemy import text


@asynccontextmanager
async def tenant_tx(engine, org_id, user_id=None):
    async with engine.connect() as conn:
        trans = await conn.begin()
        await conn.execute(text("SELECT set_config('app.org_id', :o, true)"), {"o": str(org_id) if org_id is not None else ""})
        await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id) if user_id is not None else ""})
        try:
            yield conn
            await trans.commit()
        except BaseException:
            await trans.rollback()
            raise
