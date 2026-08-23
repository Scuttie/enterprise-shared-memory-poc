# REALBENCH_SWE_POLYBENCH_R7 — Preregistration (CORRECTED v2)

Opened by R6 §6 (Endpoint B). Instrument = **SWE-PolyBench Verified** (Amazon Science, MIT), audited PASS
(`reports/R7_SWE_POLYBENCH_AUDIT.md`, live 2026-08-17). **This v2 supersedes v1 and MUST be in force before the
first paid R7 call.** Exact **resolved rate** (binary F2P→pass on the official verifier) is the sole KPI — no
custom partial score, no p-value-based reader selection, no optional stopping.

## Why v2 — six corrections to v1 (all applied below)
1. **M3 localization was target-gold-derived → not deployable memory.** The `is_func_only`/`num_func_changes`/
   modified-nodes localization arm is **removed** from every efficacy endpoint. If ever kept for debugging it is
   renamed `NON_DEPLOYABLE_GOLD_LOCALIZATION` and excluded from all H-tests.
2. **`(M1 ∪ M2) − M4` is not a well-defined paired endpoint.** Primary is now **H1 = M1 − M2**, one M1 outcome
   and one M2 outcome per target (paired McNemar), no union, no duplicated target rows.
3. **Same-language is not relevance.** Relevance is defined by evaluator-only technique overlap labels (§6), not
   language; a relevant source must be technique-matched.
4. **Reader was not pinned.** The **single primary reader is `solar-pro3-260323`** (§3); pro2 is not run as an
   alternative; the reader/harness/tool-budget are frozen and never changed after G1.
5. **One-image GHCR smoke is insufficient.** G0 smoke covers **8 tasks (2 each Java/Python/JS/TS)** with full
   gold-patch reproduction (§2).
6. **Gold-derived memory ≠ user memory.** The source bank is `HISTORICAL_VERIFIED_BANK` (evaluator-verified
   upper-bound bank from genuine prior *resolved* issues), **not** a model-generated `USER_SUCCESS_BANK`. Target
   gold labels are used **only evaluator-side to select the source ID**, never placed in agent context.

## G0 — Exact official freeze (§1)
Pin: official repo commit, evaluator commit, `AmazonScience/SWE-PolyBench_Verified` HF revision, dataset file
hashes, **all 382 instance IDs**, license, Python/dependency lock, GHCR image tag→resolved immutable digest per
selected task. On the pinned revision assert: `len==382`, Java 69 / JS 100 / Python 113 / TS 100, IDs unique,
`base_commit` length 40, patch/test_patch/F2P/P2P present where required. Record the stale card-text "394" as
documentation only; pinned rows/IDs are authoritative. Outputs `reports/R7_G0_OFFICIAL_FREEZE.md`,
`artifacts/swe_polybench_r7/official_manifest.json`, `configs/swe_polybench_r7/instrument_lock.json`. The
official F2P/P2P verifier and gold `patch`/`test_patch` are **never exposed to the agent**. Any mismatch →
**R7-G0 TECHNICAL STOP** (do not repair official tests).

## G0 smoke — multi-language image + grader (§2)
Deterministically select 2 Java + 2 Python + 2 JS + 2 TS before execution. Per task: pull official GHCR image →
resolve+persist digest → verify repo/base_commit → clean baseline → verify expected F2P failure → verify P2P
preservation → apply gold patch evaluator-side → all official tests pass → **remove gold patch before any agent
run**. Required: image pull 8/8, clean baseline 8/8, gold pass 8/8, evaluator setup failure 0, no verifier/gold
content in agent-visible artifacts. Any mismatch → **R7-G0 TECHNICAL STOP**.

## Reader freeze (§3)
Primary reader requested model = `solar-pro3-260323` (record returned model string). Freeze: repository-agent
harness commit, tool schema, max tool turns, max input/output tokens, wall-clock + per-command deadlines,
allowed tools, patch extraction, **temperature = 0**, **one primary trajectory, no result-conditioned repair.**
Do not run pro2 and pick whichever lands in-band. Do not change the reader after G1. Company reader remains
`PENDING_CONFIGURATION` (GLM not guessed).

## G1 — No-memory pilot / dynamic-range GATE (§4)
Freeze 40 targets before model calls: 10 Java + 10 Python + 10 JS + 10 TS. Exclude only tasks failing G0-style
technical checks — never on model output. Path: HTTP → durable solve job → separate repository worker → **no
memory** → official instance image → official evaluator → durable evidence. **Gate:**
- G1a technical terminal rate ≥ 38/40
- G1b evaluator/environment failures ≤ 2/40
- G1c target/verifier leakage = 0
- G1d no-memory resolved count ∈ **[4, 28]** (rate ∈ [0.10, 0.70]).

Report exact per-language results. **G1 fail → R7-G1 INSTRUMENT STOP** (do not try another Solar model, reselect
tasks, change tool budget, or switch benchmarks). **G1 pass → continue directly** to source-bank + frozen main
(no further approval checkpoint).

## Source bank — chronology & provenance (§5)
`HISTORICAL_VERIFIED_BANK` from official instances that are: disjoint from G1 + main targets; resolved by their
official source patch; **source timestamp strictly earlier than target** (conservative rule: source `created_at`
≤ target `created_at` − 30 days unless a more authoritative issue/PR timestamp exists); not the target issue;
not a near-duplicate; evaluator-verified in their official image. Each memory stores **target-free source-derived
content only**: public source issue pattern, root-cause category, relevant API/library, changed-operation
abstraction, repo convention, preconditions, non-applicability, verification procedure, source
repo/version/timestamp, source evidence hash. **Never** include target patch/test_patch/F2P/P2P identities,
target modified nodes, target expected files/functions, or target verdict. Assign immutable source-owner
identity from source provenance; for every target **`source_user ≠ target_user`**.

## Relevance labels (§6)
Evaluator-only source/target relevance from: API/library overlap, operation overlap, failure-category overlap,
migration/version pattern, concurrency/cache/schema pattern, same-repo convention, AST change category. Target
gold-derived labels may be used **only** to freeze the EVALUATOR_RELEVANT source ID — never in target prompt,
memory text, retrieval query, or agent context. One relevant source per eligible target via frozen hierarchy:
(1) earlier same-repo + technique-matched; (2) else earlier cross-repo + same-language + technique-matched;
(3) else target ineligible → **excluded before the main freeze**. Persist stratum `same_repo` /
`cross_repo_same_technique`; report the two strata separately.

## Corrected memory arms (§7)
| arm | content |
|---|---|
| **M0** NO_MEMORY | none (= G1 baseline) |
| **M1** EVALUATOR_RELEVANT_PRIOR | one frozen relevant prior issue; concise plain verified memory; **non-deployable source-selection upper bound** (target gold labels used only evaluator-side to choose the source ID) |
| **M2** SHUFFLED_MATCHED_PRIOR | frozen derangement of M1 sources; technique-mismatched; matched on language, same/cross-repo stratum, source age, change-size bin, memory length, injection indicator, source-use frequency |
| **M3** EXECUTABLE_SAME_SOURCE | **exact same source ID as M1**; action/API/precondition/verification rendering; same prompt position + token ceiling (representation diagnostic) |
| **M4** DEPLOYABLE_RETRIEVAL | complete historical verified bank; **public target issue text + public repo metadata only**; production pinned embedder; canonical PostgreSQL validation; frozen abstention; **no target gold labels** |

The v1 target-derived LOCALIZATION_HINT arm is **removed** (see correction 1).

## Endpoints (§8) — frozen pre-result
- **Primary H1 = M1 − M2** (relevant prior vs matched context-stuffing). One M1 + one M2 per target; no union;
  no duplicated rows.
- **Secondary H2 = M3 − M1** (executable representation effect, exact same source IDs).
- **Product H3 = M4 − M0** (deployable retrieval effect).
- Stratified descriptive: same-repo / cross-repo-same-technique / Java / Python / JS / TS / bugfix / feature /
  refactoring. **Do not pool M1 and M3 as "relevant memory." Do not promote a secondary after seeing results.**

## Sample size & statistics (§9)
After G1, before any memory-arm call: choose a minimum detectable paired lift; conservative discordant-pair
assumption; compute fixed N; freeze main task IDs; **no expansion after p-value inspection.** **ITT** (every
submitted target counts; dead-letter/infra terminal failure = failure) + complete-case sensitivity separately.
Report: exact resolved counts, paired difference, exact McNemar, **repository-cluster bootstrap 95% CI**,
language-stratified estimates, positive/negative transfer, per-target outcomes. Task-level bootstrap alone is
insufficient (targets cluster by repo and may reuse source memories). **A null or negative result is a valid
final endpoint.**

## Checkpointing (§10)
Persist after every task-arm: logical job ID, target instance ID, source ID, image digest, model/harness
identity, memory/view hash, patch artifact, official test result, tool transcript, latency/tokens, terminal
state. Idempotent resume; a preempted runner replays only incomplete task-arms.

## Hard stops (§11)
Stop immediately on: dataset revision drift; Verified ID count ≠ pinned manifest; official test modification;
image digest drift; gold/reference patch entering agent context; target-derived localization injected; source
timestamp after target; target used as its own memory; `source_user == target_user`; M1 and M3 using different
source IDs; M2 injection indicator differing from M1; client-selected arm; cross-user private injection; main
task reselection after outcomes; reader/tool-budget change after G1; optional stopping; benchmark switch after a
null; P6 begun before an R7 endpoint.

## Standing constraints
R1–R6 frozen/immutable; verifier & gold never exposed; no synthetic instances; no benchmark switch to flee a
null; resolved rate (binary) the only KPI; company harness PENDING (no GLM guess); **P6 not started**; PR#1
draft/OPEN; `main` `d56d178`; version `0.2.0.dev1`. Valid endpoints: **R7-G0 TECHNICAL STOP**, **R7-G1 INSTRUMENT
STOP**, **R7 MAIN COMPLETE** (honest positive/null/negative). Adapter-only completion is not valid.
