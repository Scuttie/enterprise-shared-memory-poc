# Security & Privacy

## Tenant isolation
Every tenant-owned table has PostgreSQL **RLS ENABLE + FORCE** with an `org_isolation` policy keyed on
`app.org_id`; composite tenant foreign keys prevent cross-tenant references. Minimum-privilege grants; version
tables are append-only (no UPDATE/DELETE grant → immutable rows).

## Private vs shared
Private episodes and shared contracts/cards are physically and logically separated and never merged before access
control. The offline demo asserts Alice's private memory never enters Bob's context.

## Identity & authorization
OIDC/JWKS bearer verification; scopes `memory:search | browse | feedback | review | admin`. Identity is derived
server-side; clients cannot set `org_id`, tokens, or `policy_mode` in tool payloads (rejected fail-closed).

## Secrets / PII / provenance
Secrets and PII are never logged; the verifier and hidden tests are never placed in a card, retrieval projection,
or execution view. The neutral retrieval projection excludes patch, identity, verdict, and target-specific data
(asserted by the compiler and unit tests).

## Retention / deletion
Immutable versions + deletion requests; the `EXPERIENCE_DELETE` outbox event purges the index. Audit is
append-only and exportable.

## Threat model & known gaps
See [`SECURITY_AND_THREAT_MODEL.md`](SECURITY_AND_THREAT_MODEL.md). Known gaps: not staging-certified; upstream
MemGovern license unresolved (no vendoring); readers tested ≤ gpt-4o.
