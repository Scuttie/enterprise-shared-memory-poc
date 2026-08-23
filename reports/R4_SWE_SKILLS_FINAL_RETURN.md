# REALBENCH-R4 (SWE-Skills-Bench) — Final Return (§20)

**Achieved endpoint: §0-A TECHNICAL STOP.** The official SWE-Skills-Bench is real (arXiv:2603.15401, HF dataset
MIT, Docker images) but **cannot be reproduced without altering benchmark semantics**: the official harness/repo
and account are 404, the public dataset ships only 49 rows (1 instance/skill, not the paper's ~565), and
`repo_commit` is pinned in 1/49. No calibration and no skill-condition main were run; **no synthetic tasks were
created and no numbers were fabricated.** Full audit: `reports/R4_SWE_SKILLS_DEPENDENCY_AUDIT.md`.

1. **New commits:** R4 commits on `codex/production-service-v0.2` (R3 boundary + dependency audit / technical
   stop); head advances from `681aa7a`.
2. **Final branch/head:** `codex/production-service-v0.2`, head = latest R4 commit.
3. **PR state:** PR#1 **OPEN, DRAFT, base=main** (unchanged).
4. **Preserved R1/R2/R3 hashes:** `main` `d56d178` unchanged; `v0.1.0-poc` intact; R1 (MBPP+), R2 (BigCodeBench
   `6e075558`, null), R3 (DS-1000 `e16bfb85`, injection-audited descriptive null + §0-C calibration stop) all
   frozen and unmodified; R3 held-out main remains unexecuted.
5. **Official repo/benchmark commit:** `github.com/GeniusHTX/SWE-Skills-Bench` = **HTTP 404** (repo AND account
   do not exist); no official commit to pin. arXiv:2603.15401 (200); HF `GeniusHTX/SWE-Skills-Bench` public.
6. **Licenses:** dataset MIT (HF). Code/harness license N/A (no repo). Docker images public on Docker Hub.
7. **Task/skill/container/verifier hashes:** public dataset SHA-256 `61637320…` (49 rows); 8 shared Docker base
   images (python ×32, golang ×8, jvm ×2, clojure ×2, ruby ×2, pytorch ×1, bazel ×1, rust ×1); per-task pinned
   commits = 1/49; **official verifier/harness not public** → no verifier hash.
8. **Official evaluator reproduction:** **NOT PERFORMED** — no official harness/verifier and no pinned
   repository states to reproduce (blocked at §2 before §3).
9. **Harness name/version/model:** not built — the repository-agent harness (§4) was not constructed (stop
   precedes §4). Intended reader would have been a pinned Solar-backed harness (solar-pro2-251215), not run.
10. **Tool policy:** N/A (harness not built).
11. **Calibration task IDs:** none (not run).
12. **No-skill calibration by skill/subdomain:** not measured.
13. **In-band selected skills:** none (partition impossible: 1 instance/skill < the §5 requirement of ≥3
    calibration + ≥5 held-out per skill).
14. **Calibration-gate decision:** not reached — blocked upstream at §0-A (artifact reproducibility), before the
    §10 G1–G6 gates.
15. **Held-out main task IDs/hash:** none (no main).
16. **Source-user/target-user assignment:** not created (no tasks/skills to own).
17. **Canonical skill schema:** designed in-spec (`CanonicalSkillMemory`, §7) but not instantiated (no run).
18. **Renderer hashes (original/plain/governed/executable):** not built for R4 (stop before §7 renders).
19. **Retrieval configuration:** not developed (§9 moot without instances).
20. **Pass@1 by arm:** N/A (no arms run).
21. **H1 relevance effect (A4>A5):** not tested.
22. **H2 representation effect (A4>A2):** not tested.
23. **Official original-skill effect (A1−A0):** not tested.
24. **Governed-vs-plain (A3−A2):** not tested.
25. **Deployable retrieval (A6−A0):** not tested.
26. **Version-mismatch harm (A7−A0):** not tested.
27. **Positive/negative transfer:** not measured.
28. **Patch/tool-level adoption:** not measured.
29. **Token/latency/tool-call efficiency:** N/A.
30. **Preempted/replayed jobs:** none (no paid run).
31. **Company replication status:** `COMPANY_REPLICATION = PENDING_CONFIGURATION` (no manifest; GLM not guessed).
32. **Workflow results:** no `ci-r4-*` paid workflows were run (stop before §15 harness/grader CI); existing
    R1/R2/R3 + PR CI remain green. R4 adds the audit + lock + manifest only.
33. **Hard-stop decisions (§18):** none triggered — no official repo/test modification, no verifier exposure, no
    synthetic task substitution, no benchmark switch to flee a null (R4 produced no result), no company-model
    guess, **P6 not begun**. The §0-A technical stop is the recorded endpoint.
34. **Remaining blockers:** (a) official harness/repo/account 404; (b) only 49/≈565 instances public
    (1/skill); (c) repositories not pinned (1/49 commits). All three must be resolved by the benchmark authors
    (or an official mirror with the full instance set + harness + pinned commits) before R4 can run.
35. **P6 recommendation:** **do not begin P6.** R4 ended at a technical stop; nothing here unblocks P6.
36. **Merge/release recommendation:** **keep PR#1 draft; do not merge; no RC/beta tag.** R4 adds only an honest
    dependency audit + provenance lock in an isolated namespace (`experiments/swe_skills_r4/`); it changes no
    production contract and no frozen R1/R2/R3 conclusion.

## Bottom line
SWE-Skills-Bench is a real 2026 benchmark, but its official harness and full ~565-instance task set are not
publicly reproducible (dead repo/account; 49 public rows at 1/skill; unpinned repositories), so a faithful,
semantics-preserving R4 cannot be run — **§0-A TECHNICAL STOP**. Reproducing it would require fabricating the
missing tasks and verifier, which the protocol forbids. A future study on the 49 public instances would be a
distinct design requiring a new preregistration (**REALBENCH_SWE_SKILLS_R5**) and is not run here. **Do not begin
P6; keep PR#1 draft; R1/R2/R3 frozen.**
