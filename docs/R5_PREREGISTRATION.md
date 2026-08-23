# R5 — SkillsBench v1.1 Skill-Memory Confirmatory Study (PREREGISTRATION DRAFT — awaiting approval)

**Status: DRAFT. No paid agent run is executed until this is approved.** The R5-A0 audit passed: SkillsBench
v1.1 is public/Apache-2.0/pinned (`b63b7b2`), with per-task oracle+verifier, isolatable answers, per-task
injectable SKILL.md skills, and native paired skill/no-skill grading; **15/16 SE oracles reproduce reward=1.0**
in gold-only CI (conditions 1–6, 8 PASS; 7 addressed by the frozen 31-task coding-inclusion rule).

## Benchmark & pool (frozen)
- SkillsBench v1.1 @ commit `b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af`, BenchFlow `==0.6.3`, official verifiers.
- **Reproducible pool:** the 15 SE tasks whose oracle reproduces (fix-build-agentops excluded) + the extended
  coding tasks from `coding_inclusion_rule.json` **that pass their own gold-only oracle sweep** (a pre-main step;
  any task failing oracle reproduction is excluded — never grade a non-deterministic task). Expected pool ≈
  15–29 tasks. **This is a pilot-scale N; conclusions will be reported as such** (per-skill-clustered, honest
  about power), not as a large confirmatory main.

## Harness (SWESkillsHarnessAdapter through ExternalHarnessExecutionBackend)
Repository-agent reader over the SkillsBench Docker sandbox: repo exploration, file read/search, bounded edits,
public-test execution, iterative tool use, final diff, full sanitized transcript + token/latency/tool-call
accounting. **Reader:** pinned Solar-backed repository-agent harness (requested `solar-pro2-251215`, returned
model recorded, temp 0, fixed max tool turns, fixed token + wall-clock budget, one primary trajectory, no
post-verdict repair) — labelled a *custom harness*, not the benchmark paper's original Claude-Code config.
Company harness = PENDING_CONFIGURATION (no GLM guess). Server stays authoritative for identity, pinned commit,
editable paths, budgets, skill selection, hidden verifier, final pass/fail, durable persistence. The agent
never sees `verifier/`, `oracle/`, the reference solution, the arm, or the relevance label.

## Arms (on reproducible-pool tasks)
- **A0 NO_SKILL** — no skill injected; same API→worker→harness→verifier path.
- **A1 OFFICIAL_CURATED_SKILL** — the task's official `environment/skills/` SKILL.md verbatim.
- **A2 GOVERNED_EXECUTABLE_SKILL** — the SAME skill id, re-rendered (deterministic) as applicability /
  ordered action / verification; token-matched to A1.
- **A3 SHUFFLED_MATCHED_SKILL** — a different task's skill (frozen derangement), matched on length + domain,
  same injection indicator.

## Co-primary hypotheses (Holm across the two)
- **H1 relevance:** A1 > A3 — a relevant skill beats matched extra context (isolates relevance from
  "one more long document").
- **H2 representation:** A2 > A1 — a governed/executable rendering of the *same* skill beats the original.

Secondary (not promoted post-hoc): A1−A0 (official-skill effect), A2−A0, A3−A0.

## Analysis
ITT (infra dead-letter = failure); complete-case sensitivity separate. Report per arm: exact pass counts, paired
Pass@1 difference, **skill/task-clustered bootstrap 95% CI**, exact McNemar, Holm-adjusted p for H1/H2,
per-task effects, positive/negative transfer, token/latency/tool-call cost. **A null result is final; no early
stop; no N increase after p-values; no benchmark switch on null.**

## Calibration gate (before the main)
A0 NO_SKILL on the reproducible pool; require dynamic range (not floor/ceiling) — if the reader already solves
~all tasks with no skill (as DS-1000 did), **INSTRUMENT STOP** (do not weaken the reader). Ownership: one org,
source_user≠target_user for shared arms, cross-user private injection = 0.

## Freeze & integrity (before the first paid call)
benchmark_lock, reproducible_pool, coding_inclusion_rule, task partition, user assignment, canonical skill
manifest, renderer hashes, harness/model lock, analysis plan — all frozen; seal fails on post-result mutation.
No official task/test modification; verifier/reference isolated from the agent; no synthetic tasks; **P6 not
started.** A redesign after results → REALBENCH_SWE_SKILLS_R6.

## Decision requested
Approve running the **paid R5 main** (repository-agent arms A0–A3 on the reproducible pool, plus the extended
coding oracle sweep + A0 calibration first)? Until approved, R5 remains at the completed **artifact-audit +
oracle-reproduction** stage with no paid runs.
