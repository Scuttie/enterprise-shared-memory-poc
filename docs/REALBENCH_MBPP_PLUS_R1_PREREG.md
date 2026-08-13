# REALBENCH-R1 — MBPP+ preregistration

Frozen before any calibration/main model call. The **official EvalPlus MBPP+** (v0.2.0, evalplus 0.3.1,
content hash `bbaa3bec…`; `configs/realbench_r1/evalplus_lock.json`) is run through the production service
path: HTTP `POST /v1/solve` → durable job → separate worker → memory retrieval + frozen abstention → PostgreSQL
canonical reload → Solar coding backend → **official evalplus grader** (base + augmented `plus` tests) →
durable evidence + raw/applied patch. Grading is Linux-only and runs in CI.

## Split (frozen; `artifacts/realbench_r1/*` ; split_hash `c3cbf496…`)
Deterministic disjoint partition of the 378 official tasks in id order: retrieval-dev 40, verified-source pool
150, calibration targets 48, held-out main targets 120. Audited: source∩target=0, calibration∩main=0, dev∩all=0,
source/target function-name overlap=0, near-duplicate (prompt Jaccard ≥0.6) source/target pairs excluded. No
reference solution or augmented test enters a source memory.

## Verified source memory (§7)
Each source memory derives from a VERIFIED source task (its official canonical passes base+plus, proven in
`ci-realbench-grader`). M2 (ungoverned summary) and M3 (governed contract) render the SAME source fact
(description + approach + keywords). R4 oracle = same governed rendering, always inject the most-similar source.
R1 private = the target user's own nearest source memory.

## Retrieval (§8; `retrieval_config.json`)
Shared bank of all 150 source memories (org-global). Query = target public prompt + function name. Rule: inject
top-1 iff `top1_sim ≥ tau_abs` (margins between diverse MBPP sources are ~0.02, so no margin gate). **tau_abs =
0.43**, selected as the median top-1 similarity on the disjoint retrieval-dev split; index_dim 256; frozen.

## Arms (server-assigned; client cannot select)
R0 NO_MEMORY, R2 SHARED_UNGOVERNED, R3 SHARED_GOVERNED, R4 ORACLE_GOVERNED (always inject top-1), R1
PRIVATE_ONLY (secondary). Same tasks/backend/model/grader/timeout for all; only memory policy differs.

## Model lock (`model_lock.json`)
solar-pro2-251215, temperature 0, top_p 1.0, max_output_tokens 1200, one generation, no repair in primary,
whole-file extraction, controlled_local → official evalplus grader.

## Primary endpoint (calibration must pass first)
`Pass@1(R3) − Pass@1(R0)` paired by official target task; success = mean paired lift ≥ +0.05 AND family-cluster
(here task) bootstrap 95% CI lower bound > 0; exact McNemar reported. **R3−R0 is not evidence for the contract
format when R3−R2 is null.** Do not require the result to be positive — an honest actual MBPP+ result is valid.

## Calibration gates (INSTRUMENT gates, not efficacy; §12)
C1 grader validity (reference 100% pass [ci-realbench-grader]; setup failure 0; malformed ≤0.02); C2 service
validity (HTTP→worker; DB injected==payload; cross-user private = 0); C3 usable dynamic range (R0 Pass@1 ∈
[0.10, 0.85]); C4 retrieval (no invalid canonical injected; no target/test leakage; abstention logged); C5
reproducibility (manifests==freeze; calibration∩main = 0). A null or negative memory effect is NOT an
instrument failure; if C1–C5 pass, the held-out main runs regardless of which arm looks best.

## Call budget
calibration 48×5 = 240 solve jobs; main 120×5 = 600.
