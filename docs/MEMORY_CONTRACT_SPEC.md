# Memory Contract spec

Canonical typed contract fields (SQLite authoritative): scope (org/team/repo/path/lang/framework/version),
applicability & non-applicability predicates, dependency/version constraints, expiry/invalidation,
conflict & supersession, provenance (source episodes, pseudonymized contributors, evidence hashes),
verification evidence, promotion state, and audit history. Content hashes are immutable; canonical JSON is
deterministic; optimistic versioning rejects stale writers; the supersession graph is acyclic. See
`enterprise_memory/contracts/{schema,registry}.py`.
