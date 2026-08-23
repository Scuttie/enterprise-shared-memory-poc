# R7 §6 — SWE-PolyBench Instrument Audit (live, date-anchored 2026-08-17)

Opened by R6 §6 (Endpoint B: both available Solar readers out of reach on SkillsBench even with the official
skill). This audit establishes whether **SWE-PolyBench** is a reproducible, execution-based instrument with a
plausible in-band reader — the property R3 (DS-1000 ceiling 0.98) and R5/R6 (SkillsBench floor 0.00) both lacked.
All facts are from **live HTTP as of 2026-08-17**, not cached memory; each is sourced.

## Findings
1. **Identity/provenance (LIVE).** SWE-PolyBench — Amazon Science; multi-language (Python/Java/JS/TS),
   repository-level, bug-fix/feature/refactor. Code: `github.com/amazon-science/SWE-PolyBench` (active, MIT).
   Dataset: `huggingface.co/datasets/AmazonScience/SWE-PolyBench` (MIT). Paper: arXiv 2504.08703. Leaderboard:
   `amazon-science.github.io/SWE-PolyBench/` (maintained into 2026 — lists GPT-5, Claude Opus 4.8, Rovo Dev).
2. **License (LIVE).** Code **MIT**, dataset **MIT** — no divergence, no redistribution blocker.
3. **Sets/counts (LIVE, one documented inconsistency).** Full = **2,110** (JS 1,017 / TS 729 / Py 199 / Java
   165) from 21 repos. Stratified **PB500** (125/lang). **Verified** = `AmazonScience/SWE-PolyBench_Verified`:
   **live viewer 382** (Java 69 / JS 100 / Py 113 / TS 100), GitHub README also 382, **but the HF card text says
   394** → **must resolve programmatically** (`len(load_dataset(...))`) before gating on N.
4. **Task structure (LIVE) — execution-based.** Each instance: `instance_id, repo, base_commit, patch` (gold),
   `test_patch, problem_statement, F2P, P2P, language, Dockerfile, test_command` + structural metadata
   (`is_func_only, num_func_changes, …`). Eval = `run_evaluation.py` applies model patch, runs tests, checks F2P
   transition. Docker harness with **pre-built frozen instance images on GHCR**.
5. **Resolved rates vs [0.10, 0.70] (LIVE leaderboard) — strongly in-band.**
   - Verified (382): HMigBot/Opus-4.8 **51.31%** · Rovo Dev 48.95% · Prometheus+GPT-5 33.77% · Amazon Q 28.8% ·
     Kodah/gpt-5-mini 28.27% · Aider/Sonnet-3.5 16.23% · SWE-agent 14.4% · Agentless 13.35% · Aider/Haiku 13.09%.
   - Full (2,110): Amazon Q 22.61% · Aider/Sonnet 14.08% · SWE-agent 10.19% · Agentless 7.82% · open-weight 5–6%.
   - **Ceiling ~51% (no saturation); accessible mid-band readers exist.** Only weakest open configs fall <0.10.
6. **Reproducibility (LIVE) — reproducible, minor caveats.** Dataset + harness + GHCR images all public, MIT,
   runnable today. **Caveats to clear before any paid run:** (a) smoke-test that a GHCR instance image actually
   pulls + evaluates (README-asserted, not pulled in this audit); (b) resolve Verified N 382-vs-394; (c) usual
   JS/TS toolchain flakiness (mitigated by frozen images).

## Bottom line
**PASS.** SWE-PolyBench is a genuinely reproducible, execution-based, MIT-licensed repository-level instrument
with a **well-populated in-band [0.10, 0.70] resolved-rate profile** — the measurable dynamic range absent in R3
and R5/R6. It is a valid instrument to carry the memory question. **Open caveat that R7 must settle empirically:**
the leaderboard's in-band readers are Sonnet/GPT-5/Amazon Q, **not Solar** — so R7's first gated action is a
**no-memory pilot to confirm our available reader lands in [0.10, 0.70]** (R7 preregistration). The audit
authorizes building the instrument; it does **not** by itself authorize confirmatory memory arms — the pilot gate
does. No paid SWE-PolyBench runs were executed in this audit.

Sources: github.com/amazon-science/SWE-PolyBench · huggingface.co/datasets/AmazonScience/SWE-PolyBench ·
…/SWE-PolyBench_Verified · amazon-science.github.io/SWE-PolyBench/ · arXiv 2504.08703 · OpenReview n577FC6CKk.
