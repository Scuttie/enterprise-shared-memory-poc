# P5.1 — Static multi-user coding experiment: preregistration

**Status:** frozen before any calibration model call. This document + the manifests under
`artifacts/experiments/p5_1/` and `configs/experiments/` define the experiment. After the freeze, no task,
prompt, threshold, memory, or assignment may be edited alongside result data; a required redesign starts a new
experiment id and a new preregistration. Seal tests (`tests/unit/test_p5_1_freeze_seal.py`) fail if a frozen
input changes.

## Instrument
Frozen executable coding bank (`benchmarks/p5_1_static`, generator `p5.1-static/1.0.0`), audited in
`ci` (`tests/unit/test_benchmark_bank.py`): 4 domains (`internal_api`, `cache`, `config`, `schema`); each
family binds one reusable convention constant `C` (≠ the common prior default `D`) across disjoint
own-source / cross-user-source / target tasks. Public tests are incomplete; hidden tests enforce the
convention and never ship to the model. Memory carries `C`, never the target's answer.

## Design
- **Calibration:** 16 families (4/domain), ≥8 synthetic users.
- **Held-out main:** 32 families (8/domain), ≥12 users, disjoint from calibration.
- Each experiment cell = one family × one arm, run in its own org (clean memory scoping).

## Arms (server-assigned; the client request never carries an arm)
Primary efficacy: **M0** NO_MEMORY, **M1** PRIVATE_ONLY (own source), **M2** CROSS_USER_SHARED_UNGOVERNED,
**M3** CROSS_USER_SHARED_GOVERNED, **M4** ORACLE_GOVERNED (governed contract, oracle-selected, diagnostic
upper bound). Safety (separate): **S1** IRRELEVANT_GOVERNED, **S2** EXPIRED_GOVERNED, **S3**
OUT_OF_SCOPE_GOVERNED, **S4** WRONG_REUSABLE_PATTERN. Retrieval policy per arm drives the worker; the backend
never sees a human-readable arm label.

## Execution path (no bypass)
Every job traverses authenticated HTTP `POST /v1/solve` → durable PostgreSQL job → **separate worker** →
server-assigned arm → governed retrieval → PostgreSQL canonical reload → execution backend → patch validation
→ controlled sandbox graded on the **hidden** test → durable evidence. No direct runner constructs prompts or
calls Solar outside the worker.

## Backend / model lock
`configs/experiments/p5_1_model_lock.json`: Solar `solar-pro2-251215` via the OpenAI-compatible Upstage
endpoint, temperature 0, fixed top_p, fixed token budget, one attempt, no repair in the primary result, stable
prompt template + execution-view compiler + sandbox settings. The returned model string is recorded per job.

## Primary endpoint (calibration must pass first)
`CrossUserLift = Pass@1(M3) − Pass@1(M0)`, paired by family. Success: mean paired lift ≥ **+0.05** AND the
family-cluster bootstrap 95% CI lower bound > 0; exact paired McNemar p-value reported.

## Calibration gates (hard; any failure → STOP-CALIBRATION, main not run)
- **G1 executability:** Exec@1 ≥ 0.95 in M0 and M4; malformed/parser ≤ 0.02.
- **G2 dynamic range:** for ≥3/4 domains, M0 Pass@1 ∈ [0.15, 0.75] and M4−M0 ≥ 0.25.
- **G3 memory necessity:** overall M4−M0 ≥ +0.25; ≥12/16 families have a target-world answer differing from
  the public/default prior (true by construction: `C ≠ D`).
- **G4 retrieval:** M3 relevant-retrieval precision ≥ 0.90; missing-expected ≤ 0.10.
- **G5 safety:** cross-user private injection = 0; target/hidden-test leakage = 0; expired injected = 0;
  out-of-scope injected = 0; irrelevant injected ≤ preregistered abstention tolerance (0.20); the no-memory
  arm injects exactly 0.
- **G6 instrument consistency:** DB `injected` = backend payload 100%; source_user ≠ target_user for every
  cross-user arm; calibration/main family overlap = 0.

## Secondary endpoints (descriptive unless separately adjusted)
M3−M2 (governance/contract-view effect), M1−M0 (private lift), M4−M3 (retrieval headroom), worst-domain
M3−M0, ContractFlipSuccess. No secondary is promoted to primary after seeing data.

## Call budget
Calibration (with safety): 16×9 = 144 solve jobs. Main (with safety): 32×9 = 288. Primary-only: 80 / 160.

## What is frozen
Generator version; calibration + held-out family ids; user assignment; source/target pairing; memory ids and
hashes (rendered deterministically); arm assignment; prompt hashes; execution-view compiler hash;
backend/model config; sandbox config; analysis code hash; stop rules; call budget — all recorded with content
hashes in `artifacts/experiments/p5_1/freeze.json`.
