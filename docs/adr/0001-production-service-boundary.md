# ADR 0001 -- production-service boundary

**Status:** accepted (v0.2 increment).

**Context:** v0.1.0-poc implemented and tested components but did NOT wire them end-to-end through
`/v1/solve`, and had no production auth, persistence, isolation, or operations.

**Decision:** introduce a dependency-injected service architecture (interfaces + settings + container)
so the same orchestration runs with local fakes (testable now) or production adapters (added as company
infrastructure becomes available). `ENVIRONMENT=production` refuses dev backends at startup -- a hard,
non-bypassable gate. The canonical contract (Postgres in production) remains the source of truth;
Mem0/Qdrant is a replaceable index; the model-facing view is a compact literal render compiled only
after gates pass; invalid contracts never produce model-facing text.

**Consequences:** production readiness (Gates A-G) can only be certified in a company-controlled staging
environment with real Postgres/OIDC/Qdrant/K8s/S3 and external security review. This increment does not
claim that certification.
