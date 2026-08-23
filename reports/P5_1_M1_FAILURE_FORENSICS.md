# P5.1 — M1 failure forensics (offline; no new model calls)

## Scope of available evidence
The P5.1 per-job raw model requests/responses and patches were held only in the ephemeral CI PostgreSQL +
MinIO and were **not persisted** beyond the calibration run. Only the aggregate
`artifacts/experiments/p5_1/results/calibration_results.json` survives. Therefore the request/response/patch
and the "first failing hidden assertion" cannot be recovered, and no Solar rerun is permitted. The task, tests,
memory, and compiled views ARE deterministically reconstructable offline and are analysed below.

## The single M1 failure
M1 (PRIVATE_ONLY, own-source) Pass@1 = 0.938 = 15/16. The one failure is **`fam_calibration_schema_2`**
(domain `schema`), C = 7, D = 1. Hidden test: `scale_89b162(4) == 16384` (= 4⁷). Gold: `return value ** 7`.

## Reconstructed views (deterministic)
- **M1 private execution view:** `"Your prior verified note: Field normalization raises the raw value to a
  fixed power (normalized = value ** power); the power for this codebase is 7."` — the operator is present but
  the constant is rendered as prose (`the power ... is 7`), requiring the model to substitute power→7.
- **M2/M3/M4 views** expose the constant more explicitly: the governed contract carries the literal
  `return value ** 7`; the ungoverned summary carries a discrete `convention_constant: 7` field.

## Classification
**Primary cause: `P1_VIEW_INFORMATION_LOSS`.** Evidence (from persisted + reconstructable data): M1 is the only
arm that failed this family, and it failed exactly where M2, M3, and M4 — all of which render the constant more
explicitly (discrete field / literal formula) — succeeded (M2=M3=M4=1, M1=0). The failure therefore correlates
with the least-explicit view rendering (bounded prose requiring operator inference + constant substitution),
which is the P1 signature.

**Caveat (honesty):** because the raw response/patch was not persisted, this is *design-inferred*, not
artifact-verified. The alternative that cannot be strictly excluded is `P3_MODEL_EXECUTION_FAILURE` (a single
1/16 mis-execution of a high exponent despite an adequate view). It is **not** P4/P5 (M1 Exec@1 = 1.00, so the
patch applied, compiled, and the grader ran) and **not** a leakage/consistency defect (G5 critical signals and
G6 consistency were clean).

## Implication for P5.2
Make every execution view expose the convention explicitly (literal formula + discrete constant) across all
memory forms, so a view-rendering gap cannot drive an arm difference; and persist raw + applied patches for
every executable cell so any future failure is artifact-verifiable (P5.2 gate G7).
