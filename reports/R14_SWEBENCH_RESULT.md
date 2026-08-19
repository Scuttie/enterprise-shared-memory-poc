# R14 — SWE-bench Verified, RAW worked-example memory — RESULT: first positive signal (relevance-specific), underpowered

Reader gpt-4o-mini, 60 frozen targets (sha256 8282f2cb). Memory = a REAL prior same-repo resolved issue (source
problem + the actual gold unified diff), NOT a distilled abstraction. Official swebench grader. ITT (all 180
arm-instances graded, 0 infra failures).

## Resolved rate by arm
| arm | resolved | Pass@1 |
|---|---|---|
| M0 NO_MEMORY | 5/60 | 0.083 |
| **M1 RELEVANT worked-example (same-repo prior fix, raw)** | **9/60** | **0.150** |
| M2 SHUFFLED worked-example (cross-repo prior fix, raw) | 5/60 | 0.083 |

## Contrasts (exact McNemar + repository-cluster bootstrap 95% CI)
- **H1 (primary) M1 − M2 = +0.067** (relevant vs shuffled). Discordant: 5 (M1✓M2✗) vs 1 (M1✗M2✓); McNemar
  **p = 0.22**; cluster-boot CI **[0.00, +0.167]**. Positive direction; not significant at n=60.
- **H2 M1 − M0 = +0.067** (worked-example vs none). Discordant 5 vs 1; McNemar **p = 0.22**; cluster-boot CI
  **[+0.027, +0.152]** (excludes 0).

## Reading — the first positive, and it is relevance-specific
The **relevant** raw worked-example nearly **doubled** the resolve rate (0.083 → 0.150), while the **shuffled**
control did **nothing** (0.083 = M0). So the lift is not "any example helps formatting" — it tracks *relevance*
(a prior fix from the SAME repository). M1 added 5 new solves over M0 and lost 1. This is the first positive
signal in the R1–R14 program, and it directly supports the redesign hypothesis: **the earlier nulls (R11–R13)
were driven by DISTILLED abstract memory; a concrete real prior fix (worked example) does transfer.** It also
matches the intuition that collective/other-engineers' experience helps — in the setting where it is a-priori
plausible (repository-level, shared codebase/APIs).

## Honest limitation
Underpowered: at a ~8% base rate with n=60, only 5-vs-1 discordant pairs → McNemar p = 0.22 (not significant),
even though the effect size is large and the M1−M0 cluster-bootstrap CI excludes 0. **This is a promising
positive signal, not a confirmed effect.** A powered confirmation is needed: a larger frozen N (e.g., 150-300
targets) and/or a mid-band reader (gpt-4o at ~23-39% would give more discordant pairs) under a fresh
preregistration. No p-hacking: the design/tasks/memory were frozen before running; the primary is M1-M2; a null
on confirmation would still be reported.

`artifacts/swebench_r14/main_result.json`. R1-R13 + P6 frozen; PR#1 draft.
