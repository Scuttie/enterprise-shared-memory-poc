# R20 — Component-Factorial Main Results

248 untouched confirmatory tasks (held_out_memory_eligible − R19_small_60), reader gpt-4o-mini fixed across all
arms, same r14 agent (only injected text differs), official grader, ITT (B1's 1 infra failure = unresolved). Total
compute cost across all 6 arms ≈ **$6.72**.

## Resolved rate by arm
| arm | injects | n | resolved | Pass@1 |
| --- | --- | --- | --- | --- |
| B0 | nothing | 248 | 19 | 0.0766 |
| B1 | neutral scaffold (len-matched to F10) | 247 | 19 | 0.0769 |
| F00 | shuffled, router OFF | 248 | 18 | 0.0726 |
| F10 | relevant, router OFF | 248 | 23 | 0.0927 |
| F01 | shuffled, router ON | 248 | 22 | 0.0887 |
| F11 | relevant, router ON | 248 | 23 | 0.0927 |

Note: the router **abstained on 100% of cross-repo shuffled memory**, so F01's mean injected length = 0 (F01 is
mechanically a no-memory arm). That F01 (0.089) and B0 (0.077) — two effectively-identical no-injection conditions
— differ by 0.012 sets the run-to-run **noise floor**; all "effects" below sit inside it.

## Preregistered estimands (task-level DID / paired McNemar + repository-cluster bootstrap)
| estimand | value | McNemar p | cluster 95% CI |
| --- | --- | --- | --- |
| **Interaction I = (F11−F10)−(F01−F00)** | **−0.0161** | — | [−0.076, +0.013] |
| Relevance R_avg = ½[(F10−F00)+(F11−F01)] | +0.0121 | — | — |
| Router G_avg = ½[(F01−F00)+(F11−F10)] | +0.0080 | — | — |
| Bundle P = F11−B0 | +0.0161 | 0.39 | [0.00, 0.028] |
| Orchestration O = B1−B0 | +0.0000 | 1.0 | [−0.011, +0.031] |
| Relevance-off F10−F00 | +0.0202 | 0.27 | [−0.009, +0.036] |
| Relevance-on F11−F01 | +0.0040 | 1.0 | [−0.046, +0.020] |
| Router-shuffled F01−F00 | +0.0161 | 0.39 | [+0.005, +0.032] |
| Router-relevant F11−F10 | +0.0000 | 1.0 | [−0.046, +0.020] |
| Memory-beyond-planning F10−B1 | +0.0162 | 0.45 | [−0.013, +0.042] |

## Six labels
| label | verdict |
| --- | --- |
| SYSTEM_BUNDLE_EFFECT | **NULL / INCONCLUSIVE** (F11−B0 +0.016, p=0.39) |
| ORCHESTRATION_EFFECT | **NULL** (B1−B0 = 0.000, p=1.0) |
| RELEVANCE_EFFECT | **NULL / INCONCLUSIVE** |
| ROUTER_MAIN_EFFECT | **NULL / INCONCLUSIVE** |
| ROUTER_X_RELEVANCE_INTERACTION | **NULL / INCONCLUSIVE** (I=−0.016, CI includes 0) |
| PRACTICAL_EQUIVALENCE (interaction) | **NOT ESTABLISHED / POWER_LIMITED** (90% CI [−0.06, +0.007] exceeds ±5pp) |

## Reading
On the untouched confirmatory set, **no component — bundle, orchestration, relevant memory content, the router, or
the router×relevance interaction — produces a significant effect.** Every paired contrast has McNemar p ≥ 0.27 and
a cluster CI spanning 0. Critically, **the R19 "compute" lift did NOT replicate**: B1−B0 = 0.000 here (R19 had
A1−A0 ≈ +0.067), so that earlier lift was small-sample noise. The interaction is honestly **POWER_LIMITED**
(±5pp equivalence not established), exactly as the pre-run power audit predicted (min detectable ≈ 0.045).

This is a clean confirmatory null: R19-SMALL's bundle-level A5>A0 does not survive on the untouched population, and
adding the missing F01 cell shows no router×relevance synergy. Consistent with the entire R14–R19 program.
