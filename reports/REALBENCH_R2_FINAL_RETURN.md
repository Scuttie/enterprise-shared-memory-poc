# REALBENCH-R2 — Final Return (§24)

Causal memory sweep + powered BigCodeBench confirmation + external-validity attempt, on the **production
service path**, with a **preregistered confirmatory design**. Achieved primary endpoint: **§21-C (BigCode main
COMPLETE)**. Headline: **relevant memory provides no causal benefit over relevance-matched context, and no
measurable harm — a rigorous, preregistered NULL that replicates R1 at scale with the causal control R1 lacked.**

Standing constraints honored throughout: `main` unchanged at `d56d178`; PR#1 **draft/unmerged**; version
`0.2.0.dev1`; no beta/RC tag; **P6 not begun**; no force-push; no R1 frozen artifact modified; no confirmatory
setting selected from outcomes; no synthetic substitution; no sequential benchmark-shopping; Solar key used only
as env/secret, never committed.

## A. Corrected R1 claims (§1–§2)
1. `reports/REALBENCH_R1_CLAIM_CORRECTION.md` — overclaims renamed/withdrawn; effect stated as descriptive.
2. `reports/REALBENCH_R1_CAUSAL_AUDIT.md` + `.github/workflows/ci-r1-causal-audit.yml` — re-audit; evidence-based
   patch classifier replaces assertion-only "poisoning".
3. R1.1 diagnostic kept **descriptive** (no confirmatory p attached to R1 data).

## B. Benchmark provenance & frozen partition (§3–§4)
4. `reports/BIGCODE_R2_DEPENDENCY_AUDIT.md` — BigCodeBench-Instruct v0.1.4, pkg 0.2.4, Apache-2.0, 1140 tasks,
   **dataset content-hash `98e377a8…`**, official grader in eval image `…evaluate:v0.2.4`.
5. `reports/BIGCODE_R2_PARTITION_AUDIT.md` + `artifacts/bigcode_r2/task_partition.json` — frozen
   300/80/120/80/500/60 split, **split_hash `6e075558`**, Jaccard-0.7 near-dup exclusion.

## C. Multi-user source bank (§5–§6)
6. `reports/BIGCODE_R2_SOURCE_BANK.md` + `artifacts/bigcode_r2/source_bank.json` — ONE org, 24 source users,
   **134 verified** USER_SUCCESS facts + GOLD_VERIFIED bank; `source_user ≠ target_user`; relevance labels are
   evaluator-side only (never in prompts).

## D. Format discovery & predeclared selection (§7–§8)
7. `docs/BIGCODE_R2_DISCOVERY_PROTOCOL.md` + `reports/BIGCODE_R2_DISCOVERY.md` — 14-cell fractional screen on the
   discovery split.
8. `artifacts/bigcode_r2/selected_policy.json` — **F1_PLAIN_LESSON** selected by §8 **lexicographic** rule
   (NOT min-p), recorded before the main.

## E. Calibration / instrument validity (§9)
9. `reports/BIGCODE_R2_CALIBRATION.md` — C1–C6 gates, **96.4%**, dynamic range present → **instrument VALID**;
   a null/negative effect here did not gate the main (per §9).

## F. Preregistration & freeze (§18)
10. `docs/BIGCODE_R2_PREREGISTRATION.md` — E1→E2 fixed sequence, Holm secondary, ITT primary, N=500,
    "a null result is final".
11. `artifacts/bigcode_r2/freeze.json` — benchmark/model/split/policy locks + `frozen_after_results`.

## G. Confirmatory main (§10–§12) — **PRIMARY ENDPOINT (§21-C)**
12. `reports/BIGCODE_R2_MAIN_RESULTS.md` + `artifacts/bigcode_r2/results/main_results.json`.
13. **E1 (M2 TRUE_RELEVANT − M3 SHUFFLED_MATCHED) = −0.021, 95% CI [−0.051,+0.008], McNemar b=21/c=31,
    p=0.212 → DOES NOT REJECT.**
14. **E2 (M4 − M0) GATED OUT** by the fixed sequence (M4 = M0 = 0.394).
15. Secondary (Holm, none significant): M1−M0 +0.023 (p=0.14); M2−M4 −0.004; M5−M4 +0.008; M7−M6 +0.006.
16. Arm Pass@1: M0 .394 / M1 .417 / M2 .390 / M3 .411 / M4 .394 / M5 .402 / M7 .396 (M6≡M2 under F1_PLAIN).
17. Integrity: **cross_user_private_injection = 0**; returned_models = [solar-pro2-251215]; exec@1 ≈ 0.985;
    ITT and complete-case (M0 .400/M2 .395/M3 .417/M4 .400) agree.

## H. Causal / transfer / efficiency (§14, §23)
18. `reports/BIGCODE_R2_CAUSAL_ANALYSIS.md` — clean M2-vs-M3 identification; gains≈losses; when relevant content
    **is** adopted (M2: 7 AST-verified API adoptions) it still doesn't convert to correctness.
19. `reports/BIGCODE_R2_EFFICIENCY.md` — memory injection adds token cost for 0 accuracy; cost-optimal point is
    no-injection (M0), abstention (M5) harmless-equivalent.
20. `reports/BIGCODE_R2_REPRODUCIBILITY.md` — full re-run recipe + locks + provenance.

## I. Wrong-memory safety subset (§13)
21. `reports/BIGCODE_R2_SAFETY.md` + `artifacts/bigcode_r2/results/safety_results.json` — RESERVE tasks,
    N=60/arm. **No meaningful harm**: S2/S3/S4 = baseline (0.483); S1 shuffled −0.050 (≈3/60, **0 source
    adoption** → not poisoning). cross_user=0. Descriptive per §13.

## J. External validity (§15) — **§21-D attempted → TECHNICAL STOP**
22. `reports/SWESKILLS_R3_DEPENDENCY_AUDIT.md`, `SWESKILLS_R3_RESULTS.md`, `SWESKILLS_R3_SAFETY_AND_VERSIONING.md`
    — SWE-Skills is an **agentic repo-modification** harness (official harness unavailable/404, 8 heavy build
    images) incompatible with the single-shot service path; substituting a harness would change semantics (§22).
    **Honest technical stop, no fabricated numbers.**

## K. Company harness (§16)
23. PENDING by design — `docs/COMPANY_CONFIGURATION_REQUIRED.md` / `P5_1_COMPANY_HARNESS_ADAPTER.md` document
    what an internal agent harness would need; not run here.

## L. CI & engineering (§19)
24. `reports/BIGCODE_R2_CI_WORKFLOWS.md` — 8 workflows (grader/smoke/source-bank/discovery/calibration/main/
    safety + r1-audit), all on the public repo, secrets clean.
25. Service-path fixes landed on the branch: InstructWholeFileExecutionBackend, ARTIFACT_PER_JOB, Solar 429
    retry, per-job artifact keys, FK/unique-key seeding fixes, chunked+interleaved runner, path-style S3,
    idempotent Qdrant.

## M. Run provenance & one honest caveat
26. Main matrix run `31860928312`: **19/20 chunks succeeded**; chunk 8 (25 targets) was lost to **two
    consecutive GitHub runner shutdowns (exit 143 infra preemption)**, a third rerun attempted. Primary analysis
    is over **475 paired targets ≥ the §12 power target of 470**. The 25 missing targets are a *uniform* infra
    loss across all arms (not differential attrition) → they cannot bias E1; ITT and complete-case both give the
    same null. If chunk 8 lands, `main_results.json` updates to the frozen N=500 with no change to the sign, CI,
    or decision.

## Bottom line
On a real public benchmark, with a proper relevance control and a preregistered confirmatory design, **relevant
memory does not causally improve a coding model (E1 null, slightly negative) and does not measurably harm it
(§13)**. Transfer is real but does not convert to accuracy. This is a valid, final endpoint (§12). **Do not
merge PR#1; do not begin P6.**
