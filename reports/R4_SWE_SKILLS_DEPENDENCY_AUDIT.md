# R4 §2/§3 — SWE-Skills-Bench Dependency Audit → §0-A TECHNICAL STOP

Determination of whether the **official SWE-Skills-Bench** can be reproduced without altering benchmark
semantics. All facts below were verified against primary sources (arXiv, Hugging Face API, GitHub API, Docker
Hub registry) on 2026-08-16. Lock: `configs/swe_skills_r4/benchmark_lock.json`; public manifest:
`artifacts/swe_skills_r4/official_manifest.json`.

## The benchmark is REAL
- **Paper:** arXiv:2603.15401 — *"SWE-Skills-Bench: Do Agent Skills Actually Help in Real-World Software
  Engineering?"* (Han, Zhang, Song, Fang, Chen, Sun, Hu, 2026). arXiv abstract returns HTTP 200.
- **Dataset:** Hugging Face `GeniusHTX/SWE-Skills-Bench`, public, **MIT**. Each row carries `task_prompt`,
  `skill_document` (SKILL.md-style), `test_code` (pytest), `docker_image`, `repo_url`, `type`.
- **Containers:** Docker Hub `zhangyiiiiii/swe-skills-bench-{python,golang,jvm,clojure,ruby,pytorch,bazel,rust}`
  exist and are pullable (registry returns 200).

## But it is NOT REPRODUCIBLE as the R4 design requires — three independently verified blockers
1. **Official harness/repo is gone.** `github.com/GeniusHTX/SWE-Skills-Bench` → **HTTP 404**, and the GitHub
   **account `GeniusHTX` itself → 404** (does not exist). No official evaluation harness, task registry, or
   reference-patch set is public. GitHub search surfaces no matching official repo.
2. **The public dataset is 49 rows = exactly 1 task instance per skill** (max == min == 1), **not** the paper's
   ~565 instances (49 skills × ~11). SHA-256 `61637320…`. The full paired-evaluation instance set is not public.
3. **Repositories are not pinned.** `repo_commit` is filled in **1/49** rows; some `repo_url` are empty; the 8
   `docker_image` values are **shared language base images** (python ×32, golang ×8, …), not per-task pinned
   repository states at a fixed commit.

## Why this forces a §0-A TECHNICAL STOP (not an instrument stop, not a benchmark switch)
The R4 protocol is structurally impossible on the reproducible artifacts:
- **§5 partition** needs, per skill, the first **3 instances = calibration** and the **rest = held-out main**;
  the main-open condition needs **≥8 in-band skills, ≥80 held-out instances, ≥4 subdomains**. With **1 instance
  per skill**, there are zero remaining instances for any held-out main and zero for calibration-of-3 — the
  partition cannot be formed at all.
- **§3 evaluator reproduction** needs each task's **pinned repository commit + official deterministic verifier**,
  and a ≥12-instance adapter validation with **reference/gold pass = 100%**. The pinned commits (1/49) and the
  official verifier/harness (404) do not exist publicly.
- Reproducing the paper would require **reconstructing ~516 missing task instances and the verification
  harness, and pinning repository commits the data omits** — every one of which *alters benchmark semantics* and
  is explicitly forbidden (§2 "do not silently copy tasks from a mirror / do not alter requirements or
  acceptance tests"; NOT APPROVED "replace failed official tasks with synthetic ones"; §18 hard stops "official
  repository/test modification", "task replacement").

Per §0-A: *"The official repository, containers, requirements, or deterministic verifiers cannot be reproduced
without altering benchmark semantics."* → **TECHNICAL STOP.** No calibration and no skill-condition main are
run. **No synthetic tasks are created; no numbers are fabricated.**

## What IS reproducible (recorded honestly, not run)
The 49 public skill-representative instances each ship a `skill_document`, a `test_code`, and a language base
image — enough to build a *different, smaller* study (49 skills × 1 instance). But that is **not**
SWE-Skills-Bench as the paper/§5 define it (which needs multiple instances per skill for the calibration/
held-out split and ≥80 held-out instances), and running it would be an **unpreregistered redesign** — which §16
states *"a redesign requires REALBENCH_SWE_SKILLS_R5."* It is therefore **not** run here.

## Honest note on repetition
REALBENCH-R2 previously reached a technical stop on SWE-Skills for the single-shot service path. This R4 audit
re-investigated freshly and at the repository-agent level, and reaches the same conclusion for a **more precise,
now-documented reason**: the benchmark is real, but its harness and full instance set are not public and its
repositories are not pinned. This is a genuine artifact-availability failure (§0-A), not benchmark-shopping
(R4 produced no result to flee).
