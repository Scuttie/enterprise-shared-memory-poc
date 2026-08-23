# R3 Actionable Memory — Preregistration (§16–§18, frozen before calibration/main calls)

Confirmatory test of whether the discovery-selected memory-representation bundle converts a fixed, verified,
relevant source into correct DS-1000 code, on a fully held-out split. Frozen before any calibration/main model
call. Benchmark: official DS-1000 (evaluator reproduced 100%, lock `configs/actionable_memory_r3/ds1000_lock.json`).
Split: `split_hash e16bfb852f7395cb`. Selected bundle: recorded in `selected_policy.json` (§14, discovery-only).

## Instrument calibration (§16) — technical gates, run on the 100 INSTRUMENT_CALIBRATION tasks
Arms C0 NO_MEMORY · C1 SELECTED_RELEVANT_FIXED_SOURCE · C2 SELECTED_SHUFFLED_MATCHED · C3 SELECTED_PRODUCTION_
RETRIEVAL · C4 PLAIN_RELEVANT_SAME_SOURCE · C5 GOLD_VERIFIED_SELECTED_RELEVANT. Gates (technical; a null/negative
memory effect does NOT block the main):
- **G1 evaluator**: official reference pass 100%; setup failure 0; evaluator mismatch 0; malformed ≤0.02.
- **G2 service path**: every task HTTP→durable job→separate worker; no direct provider; task-id/evaluator
  revision persisted; DB-injected == backend payload 100%.
- **G3 dynamic range**: no-memory Pass@1 ∈ [0.10, 0.90]; no catastrophic floor/ceiling in predeclared strata.
- **G4 ownership/leakage**: source_user≠target_user (shared arms); cross-user private injection 0; source/target
  overlap 0; target/test leakage 0.
- **G5 representation integrity**: same source ID for selected-vs-plain; same injection indicator; same context
  position; token budget enforced; canonical/view hashes match manifests.
- **G6 retrieval**: production embedder; invalid-canonical injection 0; abstentions/retrievals logged;
  thresholds match the frozen file.
- **G7 reproducibility**: freeze hashes match; discovery/calibration/main overlap 0; selected policy unchanged;
  model/backend/compiler/evaluator hashes match.
Any technical gate fail ⇒ **§0-C CALIBRATION STOP** (main not run). Outputs `reports/R3_CALIBRATION.md`,
`reports/R3_CALIBRATION_DECISION.md`.

## Confirmatory main (§17) — 450 held-out CONFIRMATORY_MAIN tasks (use 500 only if splits stay disjoint; here 450)
Arms M0 NO_MEMORY · M1 PLAIN_RELEVANT (B0, frozen relevant source) · M2 SELECTED_RELEVANT (same source IDs as
M1, selected bundle) · M3 SELECTED_SHUFFLED_MATCHED (frozen derangement, same bundle, same injection
indicator/position as M2) · M4 SELECTED_PRODUCTION_RETRIEVAL · M5 SELECTED_PRIVATE (own verified source,
secondary) · M6 GOLD_SELECTED_RELEVANT (diagnostic upper bound). One generation, temperature 0, no primary
repair, fixed token budget, official evaluator.

## Co-primary hypotheses (§18) — Holm across H1 and H2
- **H1 representation effect: M2 > M1** — same target, same selected source ID, same injection indicator, same
  prompt location, same token ceiling; only the representation+matched-decoder bundle differs.
- **H2 relevance effect: M2 > M3** — same selected bundle, same injection indicator; length/domain/source-use
  matched.
Report per hypothesis: exact success counts, paired difference, task-cluster bootstrap 95% CI, exact McNemar,
Holm-adjusted p, positive/negative transfer.
Secondary (not Holm-primary): M4−M0 (deployable), M5−M0 (private), M6−M2 (user-success vs gold headroom);
matched-decoder ablation is descriptive.

## Frozen commitments
- **A null result is final.** No tasks/formats/benchmarks added after inspecting results; N not changed after
  results; no benchmark switch on a null; no arm selected by the client; adoption never claimed without
  API/AST/property evidence (§19). Seal tests fail on post-result mutation (§23). A redesign ⇒
  REALBENCH_ACTIONABLE_MEMORY_R4.
- Model: `solar-pro2-251215` (requested+returned strings frozen). Optional pro3 robustness subset is descriptive
  and cannot rescue a null pro2 primary (§21). Company harness PENDING_CONFIGURATION.
