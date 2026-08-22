# Company Handoff (30-minute onboarding)

**Status: COMPANY-HANDOFF-READY is gated on a fresh-clone + offline-demo pass (see `STATUS.yaml`). This is NOT
COMPANY-STAGING-CERTIFIED and NOT production-certified.**

## 0. What this is
A governed shared-memory service for coding agents: canonical experience in **PostgreSQL**, a replaceable
**Qdrant/Mem0** retrieval index, a **utility-aware router** gating injection, and full audit. Efficacy of memory
transfer is **not** claimed (R14–R18 null); value is governance, attribution, safety, and utility selection.

## 1. Clone & verify (≈10 min)
```bash
git clone <repo> && cd enterprise-shared-memory-poc
git checkout <exact-commit>          # from COMPANY_HANDOFF_MANIFEST.json
make bootstrap
make test
make demo                            # -> DEMO_PASS: true
```

## 2. What the company must configure
- **Model/harness manifest** (`configs/company.example.yaml`): protocol + model id (+ endpoint). Do not let the
  system guess your model identity.
- **OIDC issuer / JWKS** + tenant/org identifiers.
- **PostgreSQL + Qdrant** deployment targets (or the bundled compose for a pilot).
- **Repository access policy** for source/target scoping.
Credentials come from your secret store; none are committed.

## 3. Pilot rollout
1. Deploy with `MEMORY_POLICY_MODE=shadow` (decisions recorded, nothing injected).
2. Review router decisions + outcome credits in the audit.
3. Switch to `utility_gated` with reviewed, promoted cards.

## 4. Responsibility matrix
| Area | Company | This service |
| --- | --- | --- |
| Coding agent + sandbox | owns | — |
| Model credentials | owns (secret store) | never stores |
| Governed memory + router + audit | consumes | owns |
| Staging env + sign-off | owns | provides acceptance checklist |

## 5. Acceptance, rollback, support
- Acceptance: [`COMPANY_ACCEPTANCE_CHECKLIST.md`](COMPANY_ACCEPTANCE_CHECKLIST.md).
- Rollback: `MEMORY_POLICY_MODE=off`; quarantine suspect cards; reindex.
- Support: `<support-contact-placeholder>` / `<escalation-placeholder>`.

## 6. Known blockers to production
No company staging env/sign-off yet; MemGovern license unresolved (no vendoring); memory efficacy null on the
public regime. See [`EVIDENCE_AND_LIMITATIONS.md`](EVIDENCE_AND_LIMITATIONS.md).
