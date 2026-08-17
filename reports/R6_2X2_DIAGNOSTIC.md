# R6 §2 — Frozen 2×2 Reader × Skill-Band Diagnostic

Tests the question R5 never asked: **can a reader USE the official skill to leave the no-skill floor?** A no-skill
zero alone does not prove a skill benchmark is unusable — for skill-essential ("necessity regime") tasks a zero
no-skill baseline can be the *intended* regime. So R6 runs the missing **A1 OFFICIAL_ORIGINAL_SKILL** condition
across two readers on the *same* frozen 30 R5 tasks, and asks whether the official skill moves either reader off 0.

## Design (frozen — `configs/skills_reader_r6/diagnostic_2x2_lock.json`)
- **Readers:** P2 = `solar-pro2-251215`, P3 = `solar-pro3-260323` (both repository-agents via BenchFlow
  `deepagents` + `vllm/` user-endpoint route to Upstage; Docker sandbox).
- **Conditions:** A0 = `--skill-mode no-skill`; A1 = `--skill-mode with-skill` (task's own official SKILL).
- **Tasks:** the frozen R5 reproducible pool (30). **Benchmark/verifier immutable:** SkillsBench v1.1 @
  `b63b7b2`, benchflow 0.6.3, official binary verifiers, never exposed to the agent.
- **P2-A0 reused verbatim from R5 (not rerun).** New paid cells: P2-A1, P3-A0, P3-A1 (3 × 30, batched 15+15).
  Runs: P2-A1 = 31998085150/…092699; P3-A0 = 31998100421/…109386; P3-A1 = 31997942660/…949923.

## Result — the official skill changes behavior but not outcomes
| cell | reader | condition | exact success | verifier ran | env-err |
|---|---|---|---|---|---|
| P2-A0 | solar-pro2 | no-skill | **0 / 30** | 27 | 3 |
| P2-A1 | solar-pro2 | **official skill** | **0 / 30** | 27 | 3 |
| P3-A0 | solar-pro3 | no-skill | **0 / 30** | 27 | 3 |
| P3-A1 | solar-pro3 | **official skill** | **0 / 30** | 27 | 3 |

- **Exact success = 0 in every cell.** Reward is binary `{0,1}`; the only non-error value observed anywhere is
  `0.0`. Net gain of A1 over A0 = **0** for both readers; regressions = 0.
- **The skill WAS genuinely injected — verified, not assumed.** A1-vs-A0 tool counts differ on **24/30** pro3
  tasks, with A1 systematically higher (3d-scan-calc 4→43, exam-block-sequencing 2→40, flink-query 14→41,
  fix-visual-stability 13→36, civ6 2→13, python-scala-translation 1→13). The official skill measurably changed
  the agent's trajectory — it simply did not produce a single passing solution.
- **The 3 env-errors are task-intrinsic, not harness flakiness.** The *same* 3 tasks
  (`gravitational-wave-detection`, `parallel-tfidf-search`, `setup-fuzzing-py`) error with `reward=None` in R5-A0
  **and** all three new cells — invariant to reader and to skill. Verifier ran cleanly on the other 27 in every
  cell; exact success there is still 0/27.

## Reading
This is a stronger and more honest result than R5's no-skill floor. R5 left open that we simply hadn't given the
reader the skill. R6 gives both Solar readers — including the newer, more active `solar-pro3` (up to 43 tool
calls) — the **task's own official skill**, and both still score **0/30**. The necessity-regime rescue does not
happen: on SkillsBench's hard repository tasks, the official skill guides these readers' behavior but cannot lift
them to a single pass. The bottleneck is reader capability on these tasks, not the absence of a skill.

**No confirmatory claim is drawn from this diagnostic** (it is a viability probe, not the S1−S3 skill-effect
test). Exact success — not a p-value, not a custom partial score — is the sole KPI, per protocol.
