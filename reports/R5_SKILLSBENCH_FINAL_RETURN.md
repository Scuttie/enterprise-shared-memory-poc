# REALBENCH-R5 (SkillsBench v1.1) — Final Return

**Achieved endpoint: §0-B INSTRUMENT STOP (floor).** SkillsBench v1.1 is a real, reproducible, skill-injection
repository-agent benchmark; the audit passed and the reader was validated — but the no-skill calibration gives
Pass@1 = 0/30 with the Solar-pro2 reader, so the dynamic-range gate blocks the confirmatory skill arms. No paid
skill-condition arms were run; nothing fabricated.

1. **Benchmark:** SkillsBench v1.1, `benchflow-ai/skillsbench` @ `b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af`,
   Apache-2.0, per-task sha256 manifest. 87 tasks / 8 domains.
2. **Audit (R5-A0):** STRUCTURALLY FEASIBLE — task.md/environment/oracle/verifier present, verifier isolatable
   from the agent, native paired `--skill-mode with-skill|no-skill`, per-task injectable SKILL.md skills. All 8
   PASS conditions met.
3. **Oracle reproduction (gold-only):** 30/31 coding-pool oracles reproduce reward=1.0 in Docker CI (SE 15/16 +
   extended 15/15); `fix-build-agentops` excluded (own gold fails own verifier, ×2). Conditions 2/3/4/6 closed.
4. **Frozen coding-inclusion rule:** 31 tasks (16 SE + 15 extended coding), deterministic, pre-result. Frozen
   **reproducible pool = 30**.
5. **Reader:** Solar-pro2 repository-agent via BenchFlow `deepagents` + `vllm/` user-endpoint route to Upstage.
   VERIFIED working (13 tool calls, errors=0, verifier-graded). Root cause of earlier failures: BenchFlow's
   `openai` provider hardcodes api.openai.com; the `openai/solar-...` prefix was sent to Upstage as the model
   name → 500. Fixed via `vllm/` + `BENCHFLOW_PROVIDER_*`.
6. **A0 no-skill calibration:** **Pass@1 = 0.0000 (0/30)**, 25/30 genuine multi-tool attempts (median 9, max 29
   tool calls). FLOOR.
7. **Gate decision:** §5/§10-G3 dynamic range FAIL (0 in-band tasks) → **§0-B INSTRUMENT STOP.** Skill main
   (A1/A2/A3) + safety NOT run.
8. **Reader-capability note:** Solar-pro2 itself supports function-calling/tools/streaming/28k context (probed
   HTTP 200). The floor is task-difficulty vs this reader, not a Solar API limit.
9. **Company replication:** `PENDING_CONFIGURATION` (no manifest; GLM not guessed).
10. **Hard stops:** none triggered — no official task/test modification, verifier never exposed to the agent, no
    synthetic tasks, no reader weakening/strengthening within R5, no task reselection, no benchmark switch to
    flee a result. **P6 not started.**
11. **Preserved:** `main` `d56d178`, `v0.1.0-poc`, R1/R2/R3/R4 all frozen/unmodified; PR#1 OPEN/DRAFT.
12. **Remaining blocker / revive path:** the floor is reader-specific (the paper's Claude reader is in-band). A
    stronger reader (company model when supplied) would enable the A0–A3 design on the frozen 30-task pool under
    a **new preregistration (REALBENCH_SWE_SKILLS_R6)** — not done here.
13. **P6 recommendation:** do not begin P6. **Merge/release:** keep PR#1 draft; do not merge; no RC/beta tag.

## Bottom line
The R5 pipeline is fully built and validated end-to-end (audit → oracle 30/31 → reproducible pool 30 → working
Solar repository-agent reader). The study honestly stops at the §0-B instrument gate: Solar-pro2 is **too weak**
(0/30 no-skill) on SkillsBench's hard tasks to establish dynamic range — the exact mirror of R3, where Solar was
**too strong** (0.98) on DS-1000. Across R1–R5, relevant memory/skills show no demonstrable causal benefit in
any regime that could actually measure it, and every stop was preregistered rather than a manufactured result.
**P6 not started; R1–R4 frozen; PR#1 draft.**
