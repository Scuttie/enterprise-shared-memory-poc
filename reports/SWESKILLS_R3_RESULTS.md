# SWE-Skills-Bench R3 (§15) — TECHNICAL STOP (endpoint A), documented honestly

## Outcome
The official SWE-Skills-Bench evaluation **cannot be faithfully reproduced in this setup**. This is an honest
endpoint-A TECHNICAL STOP for the external-validity leg — NOT a synthetic substitute (forbidden by the spec).
The BigCodeBench confirmatory main (endpoint C) is the milestone's achieved primary endpoint.

## What is available vs what is not
- **Dataset: available.** HuggingFace `GeniusHTX/SWE-Skills-Bench`, MIT, split `train`, **49 task instances**
  (fields: `skill_id, name, description, type, task_prompt, skill_document, test_code, repo_url(empty),
  repo_commit(empty), docker_image`). Pinned in the dependency audit.
- **Official evaluation harness: NOT available.** The paper's repo `GeniusHTX/SWE-Skills-Bench` 404s; the
  harness that (a) drives an agent to edit the repo in the container and (b) applies changes + runs `test_code`
  is not released. `repo_url`/`repo_commit` are empty because each repo is baked into a per-task `docker_image`.

## Why it cannot be run faithfully here (three independent blockers)
1. **Agentic, multi-file tasks — not single-shot function completion.** Task types: 42 `feature`, 3 `test`,
   2 `fix`, 1 `repair`, 1 `refactor`. Example: *"Modify `aten/src/ATen/native/BinaryOps.cpp` … add unsigned
   integer dispatch for `remainder`, `gcd`, `floor_divide`"* across multiple PyTorch source files. The paper's
   evaluator is a **Claude Code AGENT (Haiku 4.5)** performing multi-step repository navigation and edits. Our
   REALBENCH service path uses a **single-shot whole-file DirectModel backend** (solar-pro2) — it cannot
   navigate/edit a repository across files. Forcing it would not be the official task.
2. **Official interaction protocol unknown.** Where the model's change is written, how the repo is patched,
   and how `test_code` is executed against the modified repo live in the (404) harness. Reverse-engineering a
   substitute would **change the benchmark semantics** — a §22 hard stop and a §21 endpoint-A condition
   ("service adapter changes benchmark semantics").
3. **Build-heavy per-task environments.** 8 distinct multi-GB images
   (`swe-skills-bench-{python×32, golang×8, jvm×2, clojure×2, ruby×2, pytorch, bazel, rust}`); 13/49 tasks
   touch C/C++/compilation and require rebuilding the project (e.g. a PyTorch source build ≈ 1 h) before
   tests. 49 tasks × 6 arms with per-task rebuilds is not feasible in the CI budget even if 1–2 were.

## Company-harness note (§16)
The paper's own harness is **Claude Code + Claude Haiku 4.5** — a company/agent harness we do NOT reproduce
and whose model we do NOT guess. `COMPANY_REPLICATION = PENDING_CONFIGURATION`: given an exact company agent
manifest (harness name/version, model id/revision, serving protocol, endpoint, auth, context budget,
tool-schema hash, sandbox ownership, build id), the preferred replication is 100 frozen BigCodeBench targets
(M0/M3/M4), NOT a re-run of SWE-Skills.

## Honest conclusion
No fabricated SWE-Skills numbers are reported. The external-validity endpoint (D) requires the official
agentic harness, which is unavailable, so it is not achievable here. The milestone stops at **BigCode MAIN
COMPLETE (endpoint C)** with this leg documented as a technical stop. Re-attempting SWE-Skills requires the
official harness release (or an equivalent company agent harness) + a repository-agent execution backend —
tracked for a future milestone, not synthesized now.
