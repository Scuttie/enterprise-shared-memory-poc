# P6 — Contamination / Governance (plan, started 2026-08-18)

Begun on explicit user approval after R11 (LiveCodeBench MAIN COMPLETE = null). Scope per the R11 milestone's
definition of P6 = **contamination / governance work** (distinct from the older PR-gate framing "P6 = K8s
sandbox / reviewed promotion"). If the infra framing was intended instead, this is redirectable at low cost
(a plan + one bounded run so far).

## Motivation (from R11)
R11 showed solar-pro3 at a *ceiling* on early LiveCodeBench problems (smoke: 20/20 on 2023 easy tasks) but a
*floor* on recent ones (M0 = 11.5% on Jan–Apr 2025). LiveCodeBench's central claim is contamination-free
evaluation via release windows. P6 quantifies the contamination signal directly and checks the governance
controls that guard the memory experiment.

## P6-A0 — Contamination gradient (this deliverable)
Frozen, stratified no-memory sweep to measure Pass@1 as a function of `contest_date`.
- **Sample:** `configs/p6_contamination/gradient_sample.json` — 105 tasks, 4 per (year-quarter × difficulty),
  deterministic first-by-`question_id`, spanning 2023Q2–2025Q2; sha256 `108dcc6c…`. Frozen before calls.
- **Run:** M0 (solar-pro3, temp 0, one generation) via the same official extractor + grader as R11.
- **Read-out:** Pass@1 by quarter and by difficulty → the contamination decay curve. A monotone decline from
  older→newer contest dates (especially on EASY/MED where the model otherwise succeeds) is the contamination
  signature; a flat curve would argue against training-set memorization driving early scores.
- **Interpretation guard:** this measures a *temporal* Pass@1 gradient, which is consistent with contamination
  but also confounded by any real difficulty drift across releases; report both and do not overclaim.

## P6-B0 — Governance audit (planned, next)
Re-verify, on the R11 artifacts, the governance invariants already designed in P5/enterprise-memory:
memory injected == backend payload; no target body/tests in any memory or retrieval query; source≠target and
disjoint partitions; client cannot choose arm; ownership/leakage = 0. This is largely a re-attestation over the
committed R11 artifacts (no new paid calls).

## Constraints
No official test modification; no synthetic tasks; no new public benchmark (the static track stays closed —
P6 is analysis/governance on the existing instrument, not a new efficacy search). R1–R11 frozen; `main`
d56d178; PR#1 draft; version 0.2.0.dev1. P6 is now **STARTED** (this plan + P6-A0).
