# R5-A0 — SkillsBench v1.1 Artifact & SWE-Subset Audit Protocol

**Approved scope: ARTIFACT AUDIT ONLY — no paid model runs.** The next candidate benchmark after the R4 §0-A
technical stop is **SkillsBench v1.1** (skillsbench.ai), whose official GitHub repo is reported public with a
per-task `task.md` / `environment/` / `oracle/` / `verifier/` structure, Docker local execution, and 87 native
tasks across 8 domains. Because it mixes domains, the SWE / repository / terminal **subset** must be audited
before any preregistration. This document freezes the audit criteria and the *future* arm design; **no
calibration, no main, no paid agent call is run at R5-A0.**

## PASS conditions (all required to move from R5-A0 audit → an R5 preregistration)
1. Official GitHub release/tag is pinned (frozen commit SHA).
2. Each selected task ships `environment/` + `oracle/` + `verifier/`.
3. The oracle solution passes its own verifier (100%) on the selected tasks.
4. The task is Docker-reproducible locally.
5. License is clear (code + tasks).
6. The target answer / verifier can be isolated from the coding agent (no leakage).
7. There are enough genuine SWE / repository / terminal tasks (not padded with unrelated domains).
8. The same task supports a paired **no-skill vs original-skill** run graded by the same verifier.

If these do not hold for a usable SWE subset → the audit records a NOT-FEASIBLE / PARTIAL determination and
**no R5 main is preregistered** (a new benchmark or the author-released SWE-Skills full corpus would be needed).

## Future arm design (only if the audit PASSES; preregistered separately, still no runs here)
- **A0 NO_SKILL** — no skill/memory; same API/worker/harness/verifier path.
- **A1 OFFICIAL_CURATED_SKILL** — the official skill verbatim.
- **A2 GOVERNED_EXECUTABLE_SKILL** — the *same skill ID* re-rendered as applicability / ordered action /
  verification (deterministic; token-matched).
- **A3 SHUFFLED_MATCHED_SKILL** — a different task's skill, matched on length + domain (frozen derangement),
  same injection indicator.

**Co-primary (Holm across the two):**
- **H1 relevance:** A1 > A3 — does a relevant skill beat matched extra context? (isolates relevance from
  "one more long document").
- **H2 representation:** A2 > A1 — does a governed/executable rendering of the *same* skill beat the original?

This ordering (relevance-vs-matched first, representation second) is deliberate: `memory − no-memory` alone
confounds the effect of *relevant information* with the effect of *appending another long document*.

## Integrity carried over
Server-authoritative identity/policy/verifier; source_user≠target_user; verifier & reference isolated from the
agent; production embedder for retrieval; no synthetic tasks; no p-value-driven selection; a null result is
final. Any redesign after results → a further preregistration. **P6 remains not started.**
