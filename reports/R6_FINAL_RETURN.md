# REALBENCH-R6 — Final Return (Reader × Skill-Band Audit → conditional repository-bench transition)

**Achieved endpoint: B — available readers out of reach**, and (via §6) **C-readiness — SWE-PolyBench instrument
audited PASS and R7 preregistered.** No confirmatory claim was drawn from the diagnostic; no paid confirmatory arm
was run; R5 was preserved and **not** reinterpreted.

1. **Experiment:** `REALBENCH_SKILLS_READER_R6_DIAGNOSTIC` (new ID). R5 preserved verbatim and immutable; R6 did
   **not** reinterpret R5's 0/30 as proof official skills cannot help.
2. **§1 R5 reward forensics (offline, no model calls):** the R5 no-skill 0/30 is a **clean binary floor** — 27
   BINARY_TOTAL_FAILURE + 3 task-intrinsic env-errors; raw reward>0 in 0/27; verifier strictly binary; tool
   calls 0–29 uncorrelated with reward. Finer partial classes are not recoverable offline (verifiers emit no
   subcriteria) — stated honestly, not invented.
3. **§2 design:** frozen 2×2 — readers P2 `solar-pro2-251215`, P3 `solar-pro3-260323` × conditions A0 no-skill,
   A1 **official-original-skill** — on the *same* frozen 30 R5 tasks. Benchmark/verifier immutable (SkillsBench
   v1.1 `b63b7b2`, benchflow 0.6.3, binary verifier never exposed). **P2-A0 reused from R5 (not rerun).**
4. **§2 result:** **all four cells = 0/30 exact success.** P2-A0 0/30, P2-A1 0/30, P3-A0 0/30, P3-A1 0/30. Net
   gain of official skill over no-skill = **0** for both readers; regressions = 0.
5. **Skill injection verified (not assumed):** A1-vs-A0 tool counts differ on **24/30** pro3 tasks, A1
   systematically higher (e.g. 3d-scan-calc 4→43, exam-block-sequencing 2→40, flink-query 14→41). The official
   skill measurably changed agent behavior yet produced no pass — the reader is out of reach, not un-skilled.
6. **Env-errors are task-intrinsic:** the same 3 tasks (`gravitational-wave-detection`, `parallel-tfidf-search`,
   `setup-fuzzing-py`) error in R5-A0 **and** all three new cells — invariant to reader and skill; verifier ran
   cleanly on the other 27 in every cell (0/27 there too).
7. **§3 viability verdict:** **neither reader is skill-viable.** Both fail the capability gates — official-skill
   exact success 0 < 3 and net gain 0 < 3. Selection would have been by **exact success, never p-value**; none
   qualifies. The KPI stayed exact success throughout; no custom partial score was invented.
8. **Endpoint: B (available readers out of reach).** This **retires** the "we never gave it the skill"
   alternative left open by R5, without reinterpreting R5 and without claiming official skills are useless in
   general — only that these two Solar readers cannot pass SkillsBench's hard tasks even with the skill.
9. **§5 NOT opened:** the SkillsBench follow-up (S0–S3 on unseen tasks) requires a viable reader; there is none.
10. **§6 opened `REALBENCH_SWE_POLYBENCH_R7`.** SWE-PolyBench audited **live (2026-08-17)**: Amazon Science,
    **MIT** (code + dataset), execution-based (repo + `base_commit` + F2P/P2P + gold patch + Dockerfile + GHCR
    frozen images), reproducible today.
11. **Dynamic range PASS:** SWE-PolyBench Verified resolved-rate profile is **in-band [0.10, 0.70]** — ceiling
    ~51% (no saturation), accessible mid-band readers (Aider/SWE-agent+Sonnet ≈14–16%, Amazon Q ≈22–29%). The
    Goldilocks band R3 (0.98 ceiling) and R5/R6 (0.00 floor) both missed.
12. **R7 preregistration (`docs/R7_PREREGISTRATION.md`):** G0 instrument freeze (resolve Verified N 382-vs-394;
    GHCR pull smoke-test) → **G1 no-memory pilot gated on resolved rate ∈ [0.10, 0.70]** (our reader is not yet
    on the leaderboard — Solar band must be confirmed, else STOP like R3/R5/R6) → memory arms only if in-band.
13. **§7 memory design (M0–M4):** M0 none · M1 cross-issue same-repo · M2 cross-repo same-lang · M3 non-leaking
    localization hint · M4 shuffled-matched control. **Primary = (M1∪M2) − M4** (relevance vs context-stuffing;
    analogue of SkillsBench S1−S3). Leakage rules invariant: target instance never its own source;
    `source_user ≠ target_user`; gold patch/test never in memory or exposed to the verifier.
14. **Hard stops honored:** no official task/test/verifier modification; verifier & gold never exposed to the
    agent; no synthetic tasks/instances; no reader weakening/strengthening within R6; no task reselection; no
    benchmark switch to flee a null (the transition is gated on an audited in-band instrument, not a null-flight).
15. **Company replication:** `PENDING_CONFIGURATION` — GLM **not** guessed; a stronger/company reader remains the
    documented revive path and a candidate G1 reader for R7.
16. **Preserved / not started:** R1–R5 frozen and immutable; R6 diagnostic frozen
    (`configs/skills_reader_r6/diagnostic_2x2_lock.json`); `main` `d56d178`; `v0.1.0-poc`; PR#1 **draft/OPEN**,
    unmerged, no RC/beta tag; version `0.2.0.dev1`; **P6 not started.** No paid SWE-PolyBench run executed under
    R6 — R7's first action is the gated G1 pilot.

## Bottom line
R6 asked the one question R5 left open — *can a reader use the official skill to leave the floor?* — and answered
it cleanly: **no.** Both Solar readers, given each task's own official skill (verified injected, behavior changed
on 24/30), still score **0/30**. That closes the SkillsBench line for available readers (Endpoint B) rather than
manufacturing a signal. The milestone then transitions on principle, not on null-flight: SWE-PolyBench is a live,
MIT, execution-based instrument with a genuine in-band [0.10, 0.70] profile, now audited and preregistered
(R7) with a no-memory dynamic-range gate before any memory arm. Across R1–R6 the honest through-line holds — the
effect of relevant memory/skills is small and demonstrable only in a reader/benchmark regime that is neither
saturated nor out of reach — and every stop was preregistered. **R1–R5 frozen; PR#1 draft; P6 not started.**
