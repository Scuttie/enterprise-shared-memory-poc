# Enterprise Shared Memory PoC v0.1.0-poc

**Demo-complete, not production-ready.**

## What is included
Canonical SQLite contract registry, Mem0 private/shared retrieval adapters (governed infer=False +
infer=True baseline), permission/scope/version/expiry/supersession gates, security scanner, promotion state
machine, audit ledger, FastAPI serving + OpenAPI, controlled sandbox, compact-literal execution-view
compiler, deterministic offline Alice/Bob demo, unit/integration/security tests, and reproducibility
benchmark generators.

## Architecture
Control plane (authoritative governed contract) + execution plane (compact literal view). See
docs/ARCHITECTURE.md.

## Quickstart
See README.md (offline demo needs no credentials).

## Tested status
Offline demo + unit/security/API tests pass with no Solar, Mem0, or network.

## Evidence summary
- compact literal view: **29/32** on fresh bounded tasks
- concise summary: **31/32**
- invalid-memory refusal: **8/8**
- no general coding-efficacy claim
- **preregistered acceptance suite not fully passed (3/5 gates)**

## Known limitations
No production hardening (see docs/PRODUCTIONIZATION_CHECKLIST.md). Natural-language predicate paraphrase
collapses cache execution (use literal predicates). N1 call token/latency not logged (partial usage only).

## Excluded data/artifacts
Raw Solar requests/responses, generated patches, experiment ledgers, live SQLite/Qdrant state, model
caches, virtual environments, wheels, logs, and all unrelated durable-memory research.

## Dependency provenance
mem0ai 2.0.17 (Apache-2.0; wheel sha256 1521209f…); embedding multi-qa-MiniLM-L6-cos-v1 (dims 384,
trust_remote_code=False). See DEPENDENCY_PROVENANCE.json / THIRD_PARTY_NOTICES.md.
