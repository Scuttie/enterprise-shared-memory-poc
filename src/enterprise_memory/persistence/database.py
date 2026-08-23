"""Async engine/session factory. Runtime uses postgresql+asyncpg; migrations use postgresql+psycopg2."""
from __future__ import annotations
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine


def async_dsn(base: str | None = None, user: str | None = None, password: str | None = None) -> str:
    base = base or os.environ["DATABASE_URL"]           # e.g. postgresql://host:5432/db
    host = base.split("://", 1)[1]
    if "@" in host:                                     # strip any embedded creds; caller supplies role creds
        host = host.split("@", 1)[1]
    cred = "%s:%s@" % (user, password) if user else ""
    return "postgresql+asyncpg://%s%s" % (cred, host)


def make_engine(user: str | None = None, password: str | None = None, base: str | None = None) -> AsyncEngine:
    return create_async_engine(async_dsn(base, user, password), pool_size=3, max_overflow=0, future=True)
