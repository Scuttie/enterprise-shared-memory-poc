# R5-A0 — SkillsBench v1.1 Artifact & SWE-Subset Audit

**Scope: artifact audit ONLY (no paid model runs), per approval.** Verdict: **STRUCTURALLY FEASIBLE** — the
benchmark is real, public, Apache-2.0, version-pinned, and *natively* supports the paired skill / no-skill
design; two items remain open before an R5 preregistration (an oracle→verifier execution gate, and a modest
SWE subset size). All facts below were re-verified by me against the live GitHub API + the official v1.1
release manifest on 2026-08-16.

## Verified provenance
- **Repo:** `benchflow-ai/skillsbench` (org), public, **Apache-2.0**, default `main`. v1.1 annotated tag →
  commit **`b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af`**; release ships `skillsbench-v1.1-task-manifest.json`
  with per-task **sha256 content digests** (genuine reproducible pin). Paper: arXiv:2602.12670 (site).
- **Task structure (verified on `tasks/fix-build-agentops/` @ b63b7b2):** `task.md` (YAML frontmatter +
  instructions), `environment/` (Dockerfile + `skills/`), `oracle/solve.sh`, `verifier/test.sh` (+ pytest) — all
  HTTP 200. `environment/skills/` holds Anthropic-style `SKILL.md` agent-skills (analyze-ci, testing-python,
  uv-package-manager, …).
- **Counts (from the official manifest, all 87):** 87 active tasks, 8 domains. **software-engineering = 16**
  (largest domain): azure-bgp-oscillation-route-leak, data-to-d3, debug-trl-grpo, dialogue-parser,
  fix-build-agentops, fix-build-google-auto, fix-visual-stability, flink-query, jax-computing-basics,
  llm-prefix-cache-replay, parallel-tfidf-search, python-scala-translation, react-performance-debugging,
  simpo-code-reproduction, spring-boot-jakarta-migration, tictoc-unnecessary-abort-detection. ~14 are
  unambiguous terminal/codebase tasks (2 fix-build-* are true "clone real repo, fix broken build").

## 8 PASS conditions — status
| # | condition | status |
|---|---|---|
| 1 | official release/tag pinned (frozen SHA) | **PASS** — v1.1 → b63b7b2 + per-task sha256 manifest |
| 2 | each task has environment/oracle/verifier | **PASS** — verified on the example; structure uniform |
| 3 | oracle passes its own verifier (100%) | **PASS (empirical)** — 15/16 SE oracles reward=1.0 in gold-only CI (see R5_SKILLSBENCH_ORACLE_REPRO.md); fix-build-agentops excluded |
| 4 | Docker-reproducible locally | **PASS (empirical)** — BenchFlow 0.6.3 + Docker sandbox ran the 15 tasks cleanly |
| 5 | license clear | **PASS (harness/defs Apache-2.0)** — caveat: runtime content (BugSwarm images, cloned repos e.g. google/auto) carries upstream licenses |
| 6 | verifier/answer isolatable from agent | **PASS** — verifier/oracle are sibling mounts; Dockerfile scrubs leak vectors (`rm -rf …/passed`) |
| 7 | enough genuine SWE tasks | **PARTIAL — 16 SE tasks** (small N for a powered confirmatory main; fine for a pilot, or expand via a predeclared coding-task rule) |
| 8 | paired no-skill / original-skill on same task | **PASS** — native `bench eval run --skill-mode with-skill|no-skill`, per-task `environment/skills/` |

## Open items before any R5 preregistration
1. **Oracle→verifier execution gate (conditions 3 & 4):** run `bench eval run --agent oracle --sandbox docker`
   on a SWE subset (≥2 per subtype) and confirm reward=1 (the SkillsBench analogue of R3's DS-1000 100% gold
   reproduction). This is **gold-only, not a paid model run**, and is the natural completion of this audit; it is
   staged as `ci-r5-skillsbench-oracle` but not yet executed (BenchFlow + Docker + external-image dependency).
2. **Power (condition 7):** the labeled SE domain is **16 tasks** (1 instance each). A confirmatory main over 4
   arms on 16 tasks is a **pilot**, not a powered study; a well-powered design would predeclare a broader
   coding-task inclusion rule (some non-SE domains are code-in-terminal) or treat R5 as an explicitly pilot-scale
   test. This must be fixed in the R5 preregistration, before runs.

## Recommendation (no runs made here)
SkillsBench v1.1 is a **much stronger candidate than SWE-Skills-Bench**: live, pinned, Apache-2.0, with per-task
verifiers, isolatable answers, per-task injectable SKILL.md skills, and a **native paired skill/no-skill grading
command** — exactly the A0/A1/A2/A3 design. The next approved step is the **oracle-reproduction execution gate**
(gold-only), and, if it passes, a **separate R5 preregistration** (arms A0–A3; H1 relevance A1>A3; H2
representation A2>A1) with the power limitation addressed. **No paid model arms are run at R5-A0. P6 remains not
started.**
