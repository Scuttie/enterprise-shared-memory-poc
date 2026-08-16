# R4 §2/§3 — SWE-Skills-Bench Dependency Audit → §0-A TECHNICAL STOP

**Precise scope of this finding:** *As of 2026-08-16, the publicly released artifacts do not permit reproducing
the ~565-instance SWE-Skills-Bench evaluation reported in the paper. The public Hugging Face release provides
only 49 skill-level rows, and the full instance corpus and the official harness repository are inaccessible.*
This is **not** a claim that the benchmark is fake or unreproducible in principle — the paper (a preliminary
work-in-progress preprint) states it generated ~565 instances, and a repo/artifacts release could reappear
later. The determination is anchored to **live HTTP/API results on 2026-08-16**, not cached search snippets:
GitHub API returned 404 for both `repos/GeniusHTX/SWE-Skills-Bench` and `users/GeniusHTX`; the HF dataset API
returned a public MIT dataset of 49 rows; the arXiv abstract returned 200. (A stale GitHub README may still be
search-cached, but the current live fetch/API is 404.)

Verification method: primary-source live checks (arXiv, HF API, GitHub REST API, Docker Hub registry) on
2026-08-16. Lock: `configs/swe_skills_r4/benchmark_lock.json`; public manifest:
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

## Do NOT inflate 49 → 565 by repetition
Running the same 49 instances under multiple seeds/trajectories does **not** reconstruct the paper's ~565
instances: **10 trajectories are not 10 task instances.** Treating repeated runs of one problem as ten distinct
repository requirements would fabricate effective sample size and skill-clustering variance. Likewise, writing
the missing requirements/verifiers ourselves would make it **our own benchmark**, not a reproduction of
SWE-Skills-Bench — reporting that under the official name is forbidden and would not survive review.

## Honest note on repetition
REALBENCH-R2 previously reached a technical stop on SWE-Skills for the single-shot service path. This R4 audit
re-investigated freshly and at the repository-agent level, and reaches the same conclusion for a **more precise,
now-documented reason**: as of 2026-08-16 the publicly released artifacts (49 skill-level rows, no official
harness, 1/49 pinned commits) do not permit reproducing the ~565-instance evaluation. This is a genuine
artifact-availability failure at the gate **before the first model call** (§0-A) — basic reproducibility
hygiene, not benchmark-shopping (R4 produced no result to flee). If the authors later release the full
instance corpus + harness, a fresh study under a new experiment ID (`REALBENCH_SWE_SKILLS_R5_FULL_RELEASE`) and
a new freeze would revive it; this R4 stop remains the honest historical record of the release state on
2026-08-16.
