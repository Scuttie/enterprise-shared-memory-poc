# REALBENCH-R3 — Final Return (§28)

Actionable-memory representation study on the **official DS-1000** benchmark, production service path,
preregistered. **Achieved endpoint: §0-C CALIBRATION STOP** — the instrument (DS-1000 + solar-pro2) is
near-ceiling (no-memory Pass@1 = 0.98), so the §16 G3 dynamic-range gate fails and the confirmatory main is not
run. The discovery phase (with injection audited correct) found a **real null representation effect**. Standing
constraints honored: R1/R2 frozen artifacts untouched; `main` = `d56d178` unchanged; PR#1 draft/open; version
0.2.0.dev1; no P6; no merge/RC tag; no benchmark test altered; Solar key secret-only.

1. **New commits:** 34 R3 commits on `codex/production-service-v0.2` (F0→A0→M0→R0→D0→EXP), head `ed0fa0c`.
2. **Final head / PR state:** HEAD `ed0fa0c`; PR#1 **isDraft=true, OPEN** (unchanged status).
3. **Preserved R1/R2 hashes:** `main` `d56d178` (unchanged); `v0.1.0-poc` tag intact; R1 (MBPP+) & R2
   (BigCodeBench split_hash `6e075558`, null E1) artifacts unmodified; R2 frozen null stands.
4. **Actionability forensics (§3):** dominant R1/R2 memory failure = *adopt-but-don't-realise* (M2 52 / M7 59
   AST-verified adoptions that still failed); plain≈governed. Motivated the B0–B9 ladder. `R3_ACTIONABILITY_FORENSICS.md`.
5. **Benchmark provenance:** DS-1000, GitHub `xlang-ai/DS-1000@b39aab71`, HF `xlangai/DS-1000@4416080`,
   CC-BY-SA-4.0, 1000 tasks, data sha256 `e8c6daa9…`; **official evaluator reproduced 100% (1000/1000)**.
6. **Task-partition hashes:** `split_hash e16bfb852f7395cb`; SOURCE 200 / DEV 79 / DISCOVERY 120 / CALIB 100 /
   MAIN 451 / RESERVE 50; near-dup rule = atomic perturbation-family assignment (0 span violations).
7. **Source-bank coverage:** USER_SUCCESS 183/200 verified (91.5%), 24 source users; GOLD 200. Pytorch 0/14
   (documented; conservative dilution, no synthetic sources).
8. **User assignment:** one org `r3-acme`, 24 source + 24 target users (disjoint → source_user≠target_user by
   construction); `user_assignment.json`.
9. **Canonical memory schema:** `CanonicalActionMemory` v `r3-canon-1`; 183 objects; semantic fields populated
   (ast_edit 175, preconditions 168, verification 169); no target leakage (asserted per record).
10. **Renderer/decoder hashes:** frozen in `renderer_manifest.json` / `decoder_manifest.json` (tokenizer
    cl100k_base, budget 220); CI `ci-r3-renderers` green.
11. **Representation bundles:** B0 plain · B1 API card · B2 condition-action · B3 procedural · B4 AST-edit ·
    B5 diff-template · B6 property-spec · B7 pos/neg contrast · B8 hybrid · B9 raw-trace(220, diagnostic).
12. **Token-budget compliance:** every bundle ≤ 220 tokens (measured 73–133), matched decoder always included,
    priority-segment dropping, source constants redacted (verified).
13. **Discovery Pass@1 by bundle** (n=120, injection D1–D11 = 82/82 each): D0 .925, B0 .925, B1 .925, B2 .925,
    B3 .933, B4 .925, B5 .925, B6 .925, B7 .917, B8 .917, B9 .925; shuffled baseline .925.
14. **RelevantBundleLift (relevant − shuffled) by bundle:** B0 .000, B1 .000, B2 .000, B3 +.008, B4 .000,
    B5 .000, B6 .000, B7 −.008, B8 −.008, B9 .000. **Best +0.008 (noise) — NULL.**
15. **Negative transfer by bundle:** minimal; B7/B8 −.008 (1 task each of 82); no bundle systematically harms.
16. **Mechanism/adoption by bundle:** at ceiling with a null lift, adoption is not attributable to a lift; no
    adoption claim is made without evidence (§26). Deferred (uninterpretable at 0.925 base).
17. **Matched-decoder ablation (§13):** not run as a paid matrix — no lift to decompose; hooks implemented +
    unit-tested. `R3_MATCHED_DECODER_ABLATION.md`.
18. **Selected-policy calculation (§14):** hard-safety (all 10 pass; redaction ⇒ copy-violation 0) →
    actionability (best +.008, all within .01) → robustness → code-realisation (B4,B5,B7,B8) → efficiency (B5,
    fewest tokens) → **B5**. Full calc frozen in `selected_policy.json`.
19. **Selected representation:** **B5 GENERALIZED_DIFF_TEMPLATE** — chosen by the efficiency tie-break among
    null-lift bundles, NOT because it improves correctness.
20. **Production embedder:** SentenceTransformer `all-MiniLM-L6-v2`, 384-d (EMBEDDER=st), used in source-bank,
    discovery, calibration.
21. **Retrieval thresholds/metrics (§15):** not developed — moot for the un-run M4 arm (CALIBRATION STOP). C3
    retrieval path validated (inject-top-1, 0 invalid injection). `R3_RETRIEVAL_DEV.md`.
22. **Calibration task IDs/results (§16):** 100 INSTRUMENT_CALIBRATION tasks; C0 .98, C1 .97, C2 .99, C3 .99,
    C4 .99, C5 .99; `calibration_results.json`.
23. **Calibration gate decision:** **CALIBRATION STOP** — G3 dynamic-range FAIL (C0 0.98 > 0.90); G1/G4/G6 pass.
24. **Main task IDs/hash:** **not run** (blocked by the §16 gate).
25. **H1 representation effect (M2>M1):** not tested (main not run).
26. **H2 relevance effect (M2>M3):** not tested (main not run).
27. **Holm-adjusted results:** none (no primary tests run).
28. **Deployable retrieval effect (M4−M0):** not tested.
29. **Private-memory effect (M5−M0):** not tested.
30. **Positive/negative transfer (main):** not measured (main not run); discovery transfer is null (item 14–15).
31. **Safety-subset results (§20):** not run (main-path; also uninterpretable at ceiling).
32. **Patch-level mechanism (§19):** not run for the main; discovery shows no lift to attribute.
33. **Token/latency/storage metrics:** injected views 73–133 tokens/bundle; source-bank 183 canonical objects;
    per-job artifacts (ARTIFACT_PER_JOB) — full efficiency table deferred with the un-run main.
34. **Reader-robustness (§21):** not run (pro3 subset is post-main; main not run). solar-pro2-251215 frozen.
35. **Company-harness status:** PENDING_CONFIGURATION (unchanged; no GLM guess).
36. **Workflow results:** `ci-r3-official-grader` (100% reproduce, green), `ci-r3-renderers` (green),
    `ci-r3-source-bank` (183 verified, green), `ci-r3-discovery` (null, green), `ci-r3-calibration` (chunks green;
    combine gate = STOP). All existing R1/R2/PR CI remain green.
37. **Hard-stop decisions (§26):** none triggered — no R1/R2 mutation, no benchmark-test change, no
    target/hidden-test leakage, no source/target overlap, source_user≠target_user, cross-user private = 0, no
    client-selected arm, same source ID selected-vs-plain, no DeterministicTestEmbedder in paid runs, no source
    constants in views, no p-value selection, no post-result task/N change, no company-model guess, **P6 not
    begun**. The oracle-injection bug was caught by the injection audit and fixed *before* any confirmatory claim.
38. **Remaining blockers:** the instrument lacks dynamic range (solar-pro2 near-ceiling on DS-1000). A
    confirmatory main requires a benchmark/model pairing with in-band no-memory Pass@1 — a **new preregistration
    (REALBENCH_ACTIONABLE_MEMORY_R4)**; changing task selection now is forbidden (§22/§26).
39. **P6 recommendation:** **do not begin P6.** R3 ended at a calibration stop; P6 is out of scope and unblocked
    by nothing here.
40. **Merge/release recommendation:** **keep PR#1 draft; do not merge; no RC/beta tag.** R3 adds an isolated,
    fully-namespaced experiment (`experiments/actionable_memory_r3/`, `ci-r3-*`) with a null discovery + honest
    calibration stop; nothing changes the production service contract or the R1/R2 frozen conclusions.

## Bottom line
On the official DS-1000, with correct memory injection (audited) across a full actionability ladder of
representations, **no representation of relevant memory beats a matched control** (discovery null), and the
instrument is **too near-ceiling for a valid confirmatory test** (G3 fail → §0-C CALIBRATION STOP). The result
is honest and preregistered: the gate stopped an uninterpretable main rather than manufacturing a p-value. This
is consistent with R1 (small/n.s.) and R2 (confirmatory null). **Do not begin P6; keep PR#1 draft.**
