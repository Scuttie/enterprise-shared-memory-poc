# R5 — Calibration Decision: §0-B INSTRUMENT STOP (floor)

## Decision
**INSTRUMENT STOP.** The A0 no-skill calibration on the 30-task reproducible pool gives **no-skill Pass@1 =
0.0000 (0/30)** — a **floor**. The §5 / §10-G3 dynamic-range gate requires the no-skill baseline to be in-band
(≈[0.10, 0.90], ≥8 in-band skills); with 0 in-band tasks the instrument cannot measure a skill effect. Per the
frozen protocol, the **skill-condition main (A1/A2/A3) and the version-mismatch safety subset are NOT run.**

## Why this is correct and honest
- The reader genuinely attempts the tasks (25/30 with multi-tool trajectories, median 9 / up to 29 tool calls;
  clean runs). It is not a harness failure — Solar-pro2 simply cannot solve these hard, skill-requiring
  repository tasks unaided.
- Running A1–A3 anyway would be uninterpretable: if the reader fails ~all tasks with no skill, and (per the
  SkillsBench paper) most tasks show ~0 improvement even *with* skills, there is no measurable signal — a skill
  effect cannot be distinguished from floor noise.
- The gate did its job before the paid confirmatory arms, exactly as designed (§0-B).

## Cross-milestone finding (R3 ↔ R5): the Goldilocks requirement
Measuring whether memory/skills help requires a reader in a **measurable band** — solving *some but not all*
tasks unaided:
- **R3 (DS-1000 + Solar-pro2): CEILING** — no-skill/no-memory Pass@1 = 0.93–0.98 (too easy) → §0-C calibration
  stop.
- **R5 (SkillsBench v1.1 + Solar-pro2): FLOOR** — no-skill Pass@1 = 0.00 (too hard) → §0-B instrument stop.
Same reader, opposite failure of dynamic range. Across R1 (small n.s.), R2 (powered null), R3 (ceiling), R5
(floor), the honest through-line is: **the effect of relevant memory/skills is small and hard to demonstrate,
and is measurable only in a benchmark/reader regime that is neither saturated nor out of reach.** No milestone
manufactured a positive by weakening/strengthening the reader or reselecting tasks.

## What would make R5 runnable (a future study, not now)
The SkillsBench paper's own reader (Claude Code) solves *some* tasks no-skill, i.e. it is in-band; so the floor
here is **reader-specific to Solar-pro2**, not intrinsic to SkillsBench. A **stronger reader** — the company
harness/model (`COMPANY_REPLICATION = PENDING_CONFIGURATION`; GLM not guessed) or another sufficiently capable
coding agent — would likely put the no-skill baseline in-band and enable the A0–A3 confirmatory design on the
frozen 30-task pool. That is a **new preregistration (REALBENCH_SWE_SKILLS_R6)** with the reader swapped; it is
**not** done here, and this R5 instrument stop stands as the honest record for the Solar reader.

## Frozen / not run
- Frozen: SkillsBench v1.1 lock (`b63b7b2`), coding-inclusion rule (31), reproducible pool (30), A0 results.
- **Not run:** §11 confirmatory main (A1/A2/A3), §13 patch/safety, §14 company replication (PENDING).
- **No synthetic tasks; no reader change; no task reselection; no fabricated results. P6 not started; R1–R4 frozen.**
