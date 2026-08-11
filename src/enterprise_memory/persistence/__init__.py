"""P1 PostgreSQL persistence (async runtime via asyncpg; migrations via psycopg2). RLS + transaction-
local tenant context are the isolation boundary. No imports from benchmarks/research."""
