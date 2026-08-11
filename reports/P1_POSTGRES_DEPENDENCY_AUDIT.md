# P1 PostgreSQL dependency audit

Added under the `postgres` optional group (runtime uses asyncpg; migrations use psycopg2):

| package | pin | license | purpose |
|---|---|---|---|
| SQLAlchemy[asyncio] | >=2.0.30,<2.1 | MIT | async engine/core queries |
| asyncpg | >=0.29,<0.31 | Apache-2.0 | async PostgreSQL driver (runtime) |
| alembic | >=1.13,<1.14 | MIT | schema migrations |
| psycopg2-binary | >=2.9,<3.0 | LGPL-3.0-with-exceptions | sync driver for Alembic multi-statement DDL (migrations only) |

Resolved in CI: SQLAlchemy 2.0.51, Alembic 1.13.3 (from local install of the same pins). CI pins the
PostgreSQL server image (`postgres:16.4`); a digest pin should replace the tag once fetched from a trusted
registry (recorded as a follow-up in the readiness report). No dependency imports benchmarks/research.
