# R19-SMALL — reduced-power held-out amendment (new experiment ID)

Per §20, changing the held-out N from the full 308 to a smaller set requires a NEW experiment ID. This is
**R19-SMALL**: a reduced-power, cost-bounded confirmatory run of the same frozen A0-A5 design.

- **Targets:** 60 repository-stratified held-out tasks, frozen deterministically BEFORE running
  (`configs/p6/r19_small_targets.json`, hash `275e381efe0da06b…`). Drawn only from `held_out_memory_eligible` (untouched
  by R14-R18). This is NOT a convenient-N cherry-pick of outcomes — selection is by hash, before any run.
- **Precision limit (stated up front):** at ~8% base rate, 60 tasks yield few discordant pairs; this run is
  **underpowered** and can only detect a large effect. A null here bounds the effect as small; it does not prove
  exact zero. The full-308 design remains preregistered for a future powered run.
- **Everything else identical to `P6_UTILITY_ROUTER_PREREG.md`:** reader gpt-4o-mini (fixed across arms), arms
  A0-A5 with parity, endpoints L1=A4-A0 / L2=A4-A1 / L3=A4-A2 / H1=A5-A0 (primary) / H4=A5-A4, ITT, exact McNemar,
  repository-cluster bootstrap, method claim gate §10.7, result label domain.
- **Parity caveat (honest):** arm injection payloads are precomputed offline by the real compiler/service/router;
  the SAME r14 agent runs all arms (only injected memory text differs). A1 (neutral scaffold) mean length undershoots
  A4; reported alongside results so a token-budget explanation of any A4>A1 gap is visible.
- **Governed content:** cards are compiled to execution views (no raw diff), i.e. what the product actually injects
  — a stricter test than R14's raw-diff injection.
