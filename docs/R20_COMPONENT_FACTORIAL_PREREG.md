# R20 — Component-Factorial Confirmation — Preregistration (FROZEN)

Frozen before any R20 model call. Adds the missing **F01 (router ON + shuffled)** cell so router×relevance
interaction is identifiable, on the untouched confirmatory population. R19 is permanently frozen; the R19 60 tasks
are DEVELOPMENT_OBSERVED (power planning + implementation verification only, never in R20 primary inference).

## Population (frozen — `artifacts/r20/task_manifest.json`, hash `bb401907…`)
`held_out_memory_eligible (308) − R19_small_60 = 248` untouched tasks. No difficulty/repository filter, no
outcome-based exclusion. Repository-clustered analysis.

## Design — 6 arms (reader gpt-4o-mini fixed; identical harness/prompt/tool budget; same r14 agent, only injected text differs)
| arm | plan/orch | memory | router | maps to |
|---|---|---|---|---|
| B0 | – | – | – | A0 |
| B1 | scaffold (length-matched to F10) | – | – | A1 |
| F00 | agentic | shuffled | OFF | A2 |
| F10 | agentic | relevant | OFF | A4 |
| **F01** | agentic | shuffled | **ON** | **NEW** |
| F11 | agentic | relevant | ON | A5 |

**Invariants (asserted, `source_pair_manifest.json`):** `F10.src == F11.src` (same relevant top-K),
`F00.src == F01.src` (same shuffled set). Only relevance and router vary.

## Estimands (frozen)
- **Primary I = (F11−F10) − (F01−F00)** — task-level binary DID, repository-cluster bootstrap 95% CI.
- Relevance `R_avg = ½[(F10−F00)+(F11−F01)]`; Router `G_avg = ½[(F01−F00)+(F11−F10)]`; Bundle `P = F11−B0`;
  Orchestration `O = B1−B0`; Memory-beyond-planning `F00−B1`, `F10−B1`.

## Statistics
ITT (terminal infra failure = failure); exact McNemar per paired contrast (gain/loss/tie); repository-cluster
bootstrap 95% CI; interaction via task-level DID + repo-cluster bootstrap; GEE/clustered-logistic as sensitivity
(secondary). Multiplicity order I → R_avg → G_avg → P → O, Holm on secondary superiority. **Practical equivalence:
±5pp; only claim "practically small" if the cluster 90% CI ⊆ [−0.05, +0.05]; else INCONCLUSIVE / POWER_LIMITED.**

## Power (frozen — `power_lock.json`)
From R19 dev: mean discordant ~0.062 → ~16 discordant pairs at N=248, min detectable paired diff ~0.032,
interaction min detectable ~0.045 (≈ the ±5pp margin). The interaction may end **POWER_LIMITED**; stated up front.
Use ALL untouched; no N expansion; no task replacement.

## Governance frozen during main
Outcome credit recorded but promote/quarantine/confidence/deprecate/rank updates applied only AFTER all task-arms
finish. Card/index snapshots frozen (`card_snapshot.json`, `index_snapshot.json`).

## Claim rules
Interaction only if I>0, cluster 95% CI excludes 0, F11−F10 > F01−F00, gates pass, not driven by 1–2 repos.
Bundle-only positive ⇒ "workflow > baseline but not attributable to content/router/interaction". Planning-only
positive ⇒ "lift matches orchestration scaffold, not memory content". Router reduces loss without raising success
⇒ report as risk-control, not performance.

## Result labels (six, separate)
`SYSTEM_BUNDLE_EFFECT`, `ORCHESTRATION_EFFECT`, `RELEVANCE_EFFECT`, `ROUTER_MAIN_EFFECT`,
`ROUTER_X_RELEVANCE_INTERACTION` ∈ {POSITIVE, NULL, NEGATIVE, INCONCLUSIVE}; `PRACTICAL_EQUIVALENCE` ∈ {PASS, FAIL,
NOT_ESTABLISHED}. No single "system works" verdict. A redesign requires experiment ID R21.
