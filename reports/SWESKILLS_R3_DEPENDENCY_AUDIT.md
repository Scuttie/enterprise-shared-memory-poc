# SWE-Skills-Bench Dependency & Provenance Audit (§15)

Feasibility scoped now (during the BigCode pipeline); the integration itself runs only **after the
BigCodeBench main completes** (§15/§20). This is a separate EXTERNAL-VALIDITY experiment — it does NOT rescue
a null BigCodeBench result and its p-value is never pooled with BigCodeBench.

## Official source (confirmed reproducible)

| | |
|---|---|
| Paper | SWE-Skills-Bench (arXiv 2603.15401) — "Do Agent Skills Actually Help in Real-World Software Engineering?" |
| Dataset | HuggingFace **`GeniusHTX/SWE-Skills-Bench`** (JSON + Parquet). *(The paper's GitHub `GeniusHTX/SWE-Skills-Bench` currently 404s; the dataset + Docker images are the reproducible artifacts.)* |
| License | **MIT** |
| Scale | **49 skills / ~565 task instances** across 6 domains (Dev Tools, Security & Testing, API Dev, Data Science & ML, Deploy & DevOps, Analytics & Monitoring) |
| Fields | `skill_id, name, description, type, task_prompt, skill_document, test_code (pytest), repo_url, repo_commit, docker_image` |
| Eval | run the task's `test_code` (pytest) inside the task's `docker_image` against the agent's change to `repo_url@repo_commit` |
| Docker images | official, e.g. `zhangyiiiiii/swe-skills-bench-python`, `zhangyiiiiii/swe-skills-bench-jvm` |

## Endpoint-A analysis — UPDATED after inspecting the release: TECHNICAL STOP
Initial scoping assumed a function-style benchmark. Inspecting the actual HF release (49 tasks) shows the
DATASET is public/MIT, BUT the OFFICIAL EVALUATION cannot be faithfully reproduced here: the tasks are
**agentic repo modifications** (42 `feature` / edit-multiple-files, e.g. modify PyTorch `aten/…/BinaryOps.cpp`),
the repos are baked into **8 heavy per-language build images** (13/49 need compilation), and the official
**agent harness** (the paper's GitHub repo) is **404/unavailable** — so how changes are applied and `test_code`
is run is unknown. Our single-shot whole-file DirectModel backend cannot perform multi-file repository edits,
and reverse-engineering a substitute harness would change benchmark semantics (§22 hard stop). **See
SWESKILLS_R3_RESULTS.md — endpoint A TECHNICAL STOP for the external-validity leg.** (Original "reproducible"
note below is superseded.)

## Integration plan (built after the BigCode main, §20 SWESKILLS-R3)
Arms Q0 NO_SKILL / Q1 ORIGINAL_SKILL_DOCUMENT / Q2 GOVERNED_COMPACT_SKILL (governed rendering of the SAME
skill_id) / Q3 SHUFFLED_MATCHED_SKILL (frozen derangement) / Q4 DEPLOYABLE_RETRIEVED_SKILL (production
retrieval over the skill bank) / Q5 VERSION_MISMATCHED_SKILL (predeclared subset). Path: HTTP → durable job →
DirectModel backend (solar-pro2; the paper's Claude-Code+Haiku harness is a separate company-harness track) →
official repo snapshot/container → official pytest acceptance tests → durable evidence.

**Cost note (§15 requires all official pairs):** 565 tasks × 6 arms = ~3,390 runs, each = docker pull + repo
clone@commit + model change + pytest-in-container. This is heavier than BigCodeBench (per-task multi-image
Docker). It is DESCRIPTIVE external validity (no confirmatory power claim unless a separate power analysis is
added). Executed on the (now public) repo's unlimited-minutes Actions after the BigCode main; if a specific
per-task image or repo checkout cannot be provisioned in CI, that subset is logged (no silent truncation).

## Company-harness note (§16)
COMPANY_REPLICATION = PENDING_CONFIGURATION. The paper's own harness is Claude Code + Claude Haiku 4.5; we do
NOT guess the company model. If an exact company manifest is later supplied, a 100-task company replication of
the frozen BigCode main subset (M0/M3/M4) is the preferred replication — not a re-run of SWE-Skills.
