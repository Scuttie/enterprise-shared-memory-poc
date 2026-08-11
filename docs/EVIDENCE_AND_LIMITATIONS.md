# Evidence & limitations

**Fresh domain-scoped renderer intervention; not confirmatory evidence for general coding-memory efficacy.**

## Evidence (M7 pilot, fresh bounded internal_api + cache tasks; 32 world tasks)
- Compact literal execution view (P5): **29/32**; concise summary (P7): **31/32**.
- P5 internal_api **16/16**; P5 cache **13/16**; natural-paraphrase cache (P6) **0/16** (do not paraphrase
  predicates).
- Safety: P5 governed compiler refuses invalid memory -> **8/8** pass, **0/8** old-fix adoption, **0/8**
  invalid injection; directly attaching an invalid full contract -> **0/8** pass, **6/8** old-fix; invalid
  summary -> **0/8** pass, **8/8** old-fix.
- N1 decision accuracy was 32/32 for every renderer, so in this experiment DecisionExecutionConsistency
  numerically **equals** N2 Pass@1 (P5 = 29/32); they are not independent evidence.

## What is NOT claimed
- NOT "Memory Contracts solve coding memory."  NOT "shared memory improves coding generally."
- NOT "M7 outperforms concise summaries" (P7 31 >= P5 29).  NOT "production safety established."
- NOT total efficiency/cost (N1 call token/latency were not logged; see the token-coverage audit).

## Interpretation
Canonical contracts should govern **selection and validity** in the control plane, while a compact
**literal** execution view should be supplied to the coding model.
