# REALBENCH-R7 (SWE-PolyBench Verified) — Final Return

**Achieved endpoint: R7-G1 INSTRUMENT STOP (floor).** The instrument is fully validated (G0 exact freeze + G0
multi-language execution smoke both PASS), the corrected causal memory design is preregistered, but the pinned
reader's no-memory pilot resolved rate is **1/40 = 0.025**, below the [0.10, 0.70] dynamic-range band. Per the
frozen protocol the memory arms and the main are NOT run. Nothing fabricated; R1–R6 frozen; P6 not started.

1. **Commits/HEAD/PR.** Branch `codex/production-service-v0.2`; R7 work committed atop `6650a13`
   (§0→G1). PR **#1 OPEN / DRAFT / unmerged**, base `main`; `main` unchanged at `d56d178`; tag `v0.1.0-poc`
   unchanged; version `0.2.0.dev1`.
2. **Corrected PR body.** Top section updated (R1–R6 complete / R7-G0 pass / R7-G1 stop) and read back; stale
   "docs synced at 4eeea22" replaced.
3. **Official revisions (pinned).** Code+evaluator `github.com/amazon-science/SWE-PolyBench` @
   `9c836c5d7f3cb991934132b77d29e6941d912a07`; dataset `AmazonScience/SWE-PolyBench_Verified` @ HF revision
   `b3fca77b637379f0c01ad86d18753a7ac1998b53`; `test.csv` sha256 `0c8138e73c34fa29a5276b675b146b72d78ce001fcc4560d76302c908b4808a5`.
4. **Verified count + manifest.** len == **382** (Java 69 / JS 100 / Python 113 / TS 100), IDs unique,
   base_commit len 40, patch/test_patch/F2P/P2P present, created_at 382/382. Card-text "394" recorded as stale.
   `artifacts/swe_polybench_r7/official_manifest.json` holds all 382 IDs + per-instance content sha256. **License:
   top-level LICENSE/GitHub/dataset = MIT, but `src/*.py` SPDX headers = CC-BY-NC-4.0 — flagged for commercial
   use.**
5. **Per-language GHCR smoke.** 8 tasks (2/language) — image pull 8/8, clean baseline (F2P fail) 8/8, gold patch
   resolved 8/8, evaluator setup failures 0. 8 image digests pinned (`g0_smoke_summary.json`).
6. **Gold/base evaluator reproduction.** Confirmed via the smoke (gold `patch` → all official tests pass) and in
   G1 (`prettier__prettier-3515` resolved=True). Java grader validated via the imported-DockerManager path.
7. **Pinned reader/harness/tool budget.** `solar-pro3-260323` (single primary; pro2 not run; unchanged after G1),
   temperature 0, 1 trajectory, no result-conditioned repair; 40 tool turns / 28k in / 8k out / 1800s wall /
   300s per-command; harness `scripts/r7_repo_agent.py` @ frozen commit; tools list/read/search/edit/replace_lines/
   create/submit; agent never sees F2P/P2P/test_patch/gold. `reader_lock.json`.
8. **G1 target IDs + result.** 40 frozen (`g1_targets.json`). Run `32046661844`: graded 40/40, failures 0,
   leakage 0, **resolved 1/40** (`prettier__prettier-3515`); valid patches 5/40. Per-language resolved 0/0/1/0
   (Java/Python/JS/TS).
9. **G1 gate decision.** G1a PASS (40≥38), G1b PASS (0≤2), G1c PASS (0), **G1d FAIL (1 ∉ [4,28]) → R7-G1
   INSTRUMENT STOP.** `reports/R7_G1_DECISION.md`.
10. **Source-bank size + chronology audit.** **NOT RUN** (gated on G1 pass).
11. **Same-repo/cross-repo relevance coverage.** **NOT RUN.**
12. **User/provenance assignment.** **NOT RUN** (design fixed in prereg: source_user ≠ target_user; target never
    its own source).
13. **Main target IDs/hash.** **NOT RUN** (main not opened).
14. **M0–M4 exact results.** **NOT RUN.**
15. **H1 relevance effect (M1−M2).** **NOT RUN.**
16. **H2 representation effect (M3−M1).** **NOT RUN.**
17. **H3 deployable retrieval effect (M4−M0).** **NOT RUN.**
18. **Repo-cluster CI + McNemar.** **NOT RUN.**
19. **Per-language/per-repo results.** G1 per-language above; memory-arm per-repo **NOT RUN.**
20. **Positive/negative transfer.** **NOT RUN.**
21. **Leakage/ownership audit.** G1c = 0 (agent context contained only the public problem_statement + the repo at
    base_commit; F2P/P2P/test_patch/gold were evaluator-side only). Memory-arm ownership audit **NOT RUN.**
22. **Token/latency/tool-call metrics (G1).** 10,604,175 prompt + 102,627 completion tokens; 24,165 agent-seconds;
    1,487 tool turns over 40 tasks (avg 37.2 turns, 604 s/task). Grading Docker time additional.
23. **Preempted/replayed tasks.** None in the definitive run (per-task isolation = idempotent unit; earlier
    rate-limited runs discarded and re-run wholesale, retained for the record).
24. **Hard-stop decisions.** No §11 hard stop triggered (no dataset/ID drift, no test modification, no image
    digest drift, no gold/verifier in agent context, no chronology/self-source/owner violation — none applicable
    pre-main). The milestone endpoint reached is the **G1 dynamic-range instrument stop** (a valid endpoint, not a
    hard stop). Two earlier full runs were **rejected as infrastructure-invalid** (HTTP-429 rate-limit storms /
    Java grader build bug) rather than misread as reader floors — the correct call per §11.
25. **Company-harness status.** `PENDING_CONFIGURATION` — GLM not guessed; a stronger/company reader is the
    documented revive path under a new preregistration.
26. **P6 recommendation.** **Do not begin P6.** Not started.
27. **Merge/release recommendation.** Keep **PR#1 draft**; do not merge; no RC/beta tag.

## Bottom line
R7 built and *validated* a genuinely reproducible, execution-based, MIT instrument (SWE-PolyBench Verified: 382
tasks pinned + hashed; GHCR images + official evaluator reproduce baseline→gold across all four languages) and a
faithful no-memory repository-agent path (the reader really resolved a task end-to-end). The corrected causal
memory design (H1 = M1−M2, with the non-deployable gold-localization arm removed and a genuine
HISTORICAL_VERIFIED_BANK) is preregistered and ready. But the pinned reader, `solar-pro3`, sits at a **floor
(1/40 = 2.5%)** — out of the measurable band — driven by weak agentic behavior (degenerate repetition, unreliable
editing), so the dynamic-range gate correctly stops before any paid memory arm. This completes the R3→R5/R6→R7
Goldilocks arc: across DS-1000 (ceiling), SkillsBench (floor), and SWE-PolyBench (floor), the available Solar
readers cannot be placed in a band where a memory/skill effect is measurable. The instrument and design now
await a sufficiently capable reader (company harness, PENDING) to run the main under this same preregistration.
**R1–R6 frozen; PR#1 draft; P6 not started.**
