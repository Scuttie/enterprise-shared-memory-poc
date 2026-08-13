# P5.2 — Static multi-user coding experiment: preregistration

**Status:** frozen before any calibration/main model call. Manifests under `artifacts/experiments/p5_2/` +
`configs/experiments/p5_2_*`. After the freeze no task/prompt/threshold/memory/assignment may be edited with
result data; a required redesign starts a new experiment id. Seals: `tests/unit/test_p5_2_seal.py` (P5.2) and
`tests/unit/test_p5_1_immutable.py` (P5.1 untouched) are independent. Diagnoses the failed frozen P5.1
instrument (`reports/P5_1_CLOSURE_AND_CLAIM_BOUNDARY.md`); no P5.1 number is reused as P5.2 evidence.

## Instrument (`benchmarks/p5_2_static`, generator `p5.2-static/1.0.0`)
Each task = an ordinary CORE `f(n)=base*m(n)` (inferable from the public tests) + an edge-case CONVENTION for
`n>=EDGE` returning `base*K`. Strata: **prior_aligned** (K = natural core continuation → memory-less-solvable),
**context_inferable** (K differs; a weak repo clue), **prior_conflict** (K differs; memory is the
disambiguator). Calibration per domain: 1/1/2 → 12/16 differ from the prior with a nonzero M0 baseline
structurally possible; main 2/2/4. `base` is task-specific (public); memory carries only `K` (no target answer).
Audited in `ci-p5-2-benchmark`.

## Competitive retrieval + frozen abstention (`ci-p5-2-retrieval`)
Every shared query searches a bank: 1 relevant + 3 same-domain near-miss + 4 cross-domain irrelevant (no-match
= 0 relevant among 8 decoys), all passing hard org/repo/path/state gates. Frozen rule: inject top-1 iff
`top1>=tau_abs AND (top1-top2)>=tau_margin`, else abstain. Thresholds selected on the representative,
disjoint `EXP_P5_2_RETRIEVAL_DEV` only (objective: recall≥0.90, no-match specificity≥0.80, max macro-F1,
tie-break larger τ) → **tau_abs=0.80, tau_margin=0.50**, frozen in `retrieval_thresholds.json`.

## Arms (server-assigned; never client)
M0 NO_MEMORY, M1 PRIVATE, M2 SHARED_UNGOVERNED, M3 SHARED_GOVERNED, M4 ORACLE (bypasses similarity, PG-validated).
Safety: S1 IRRELEVANT (relevant absent → abstain), S2 EXPIRED / S3 OUT_OF_SCOPE (relevant present but
validity/scope-gated → not injected), S4 WRONG_PATTERN (wrong K; adoption diagnostic). M2 and M3 share the same
source facts, pool, thresholds, and ranking — only the rendering/governance differs.

## Execution path (no bypass)
HTTP `POST /v1/solve` → durable job → separate worker → server-assigned arm + abstention/oracle → PostgreSQL
canonical reload → Solar (`solar-pro2-251215`, temp 0, one attempt, no repair; `p5_2_model_lock.json`) → patch
validation → controlled sandbox graded on the hidden test → durable evidence + raw/applied patch (`job_patches`).

## Primary endpoint (calibration must pass first)
`CrossUserLift = Pass@1(M3) − Pass@1(M0)`, paired by family. Success: mean paired lift ≥ +0.05 AND
family-cluster bootstrap 95% CI lower bound > 0; exact McNemar reported. Preregistered secondary: the
prior-conflict stratum reported separately. **M3−M0 is not evidence for the contract format when M3−M2 is null.**

## Calibration gates (hard; any fail → STOP-P5.2-CALIBRATION, main not run)
G1 executability (Exec@1 M0,M4 ≥0.95; malformed ≤0.02); G2 dynamic range (≥3/4 domains M0∈[0.15,0.75] and
M4−M0≥0.25); G3 memory necessity (M4−M0≥0.25; ≥12/16 differ); **G4 competitive retrieval** (relevant precision
≥0.90, recall ≥0.90, no-match specificity ≥0.80, relevant-missing ≤0.10, S1 false-injection ≤0.20 — not
singleton "precision"); G5 critical safety (cross-user private / target-hidden / expired / out-of-scope /
no-memory injection = 0; DB injected == payload 100%); G6 instrument consistency (source≠target every cross
arm; calibration/main disjoint); G7 adoption auditability (raw+applied patch for 100% executable S1/S4;
classifier coverage 100%).

## Call budget
instrument_dev 72, calibration 144, main 288 solve jobs.
