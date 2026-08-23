# Production Readiness Report

**Label: COMPANY-HANDOFF-READY (gated on fresh-clone + demo) — NOT COMPANY-STAGING-CERTIFIED — production NOT CLAIMED.**

## Ready (verified in CI)
- Control-plane schema + RLS + immutable versions + integrity FKs (migration 0014).
- Utility router (deterministic, frozen policy, leakage sentinel), search/browse gating, outcome credit +
  governance, MCP + adapters, offline demo `DEMO_PASS`, docs-truth + literature-provenance gates.

## Not yet done for production (company-owned)
- Company-controlled **staging environment** + acceptance sign-off.
- Load/scale testing at company volumes; DB HA/PITR validation; Qdrant sizing.
- Company OIDC issuer wiring + tenant onboarding.
- Live utility-router held-out result (`utility_router_result` currently reflects STATUS; may be `NOT_RUN`).
- Full HTTP endpoint hardening + rate limits in the company deployment.

## Open research caveat
Memory-transfer efficacy is null on the tested public regime (R14–R18). Do not deploy expecting a performance lift
unless the held-out router endpoint `H1 = A5 − A0` passes; otherwise the value is governance/attribution/safety.

## Sign-off
Production certification requires the company acceptance checklist to pass **in the company environment** plus
written sign-off. This repository does not self-certify production.
