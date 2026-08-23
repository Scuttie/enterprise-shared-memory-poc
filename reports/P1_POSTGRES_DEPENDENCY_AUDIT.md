# P1 PostgreSQL dependency audit

Added under the `postgres` optional group (runtime uses asyncpg; migrations use psycopg2):

| package | pin | license | purpose |
|---|---|---|---|
| SQLAlchemy[asyncio] | >=2.0.30,<2.1 | MIT | async engine/core queries |
| asyncpg | >=0.29,<0.31 | Apache-2.0 | async PostgreSQL driver (runtime) |
| alembic | >=1.13,<1.14 | MIT | schema migrations |
| psycopg2-binary | >=2.9,<3.0 | LGPL-3.0-with-exceptions | sync driver for Alembic multi-statement DDL (migrations only) |

Resolved in CI: SQLAlchemy 2.0.51, Alembic 1.13.3 (from local install of the same pins). CI pins the PostgreSQL server image by **immutable digest**: `postgres:16.4@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412` (amd64), resolved on the GitHub ubuntu-latest runner. No dependency imports benchmarks/research.
