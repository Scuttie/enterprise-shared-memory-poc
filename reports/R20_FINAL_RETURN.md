# R20 — Final Return

1. **New commits**: R20-0 (freeze audit), R20-1/2 (`2cc8997` build+prereg+freeze), R20-5 (this — analysis+reports+arm outputs).
2. **Final branch/head**: `codex/r20-component-factorial` (see PR #3 for head).
3. **PR #3**: https://github.com/Scuttie/enterprise-shared-memory-poc/pull/3 — OPEN / DRAFT.
4. **PR #2 preserved**: OPEN / DRAFT, untouched by R20.
5. **R1–R19 hash audit**: `artifacts/r20/r19_lock.json` (all frozen artifacts unchanged); `main`, `v0.1.0-poc`, PR #1/#2 untouched.
6. **docs/STATUS & README sync**: unchanged on this branch except R20 additions; product status carried from v0.3.
7. **Observed-60 ids/hash**: `configs/p6/r19_small_targets.json` (hash `275e381e`) — DEVELOPMENT_OBSERVED, excluded from primary.
8. **Untouched confirmatory**: 248 tasks, `artifacts/r20/task_manifest.json` (hash `bb401907`).
9. **Model/harness/tool budget**: gpt-4o-mini-2024-07-18, r14 agent, max 40 turns — identical across arms (`model_harness_lock.json`).
10. **Source-pair manifest**: `artifacts/r20/source_pair_manifest.json` (248).
11. **F00/F01 source parity**: same shuffled set (invariant, verified).
12. **F10/F11 source parity**: same relevant top-K (invariant, verified).
13. **Router policy hash**: reused frozen R19 policy (`router_policy.json`, content_hash unchanged).
14. **Card/index snapshot hash**: `card_snapshot.json`, `index_snapshot.json` (frozen).
15. **Per-arm Pass@1**: B0 0.0766 · B1 0.0769 · F00 0.0726 · F10 0.0927 · F01 0.0887 · F11 0.0927.
16. **B1−B0** = +0.0000 (p=1.0).
17. **F10−F00** = +0.0202 (p=0.27).
18. **F11−F01** = +0.0040 (p=1.0).
19. **F01−F00** = +0.0161 (p=0.39).
20. **F11−F10** = +0.0000 (p=1.0).
21. **Interaction DID** = −0.0161 (cluster95 [−0.076, +0.013]).
22. **Product bundle F11−B0** = +0.0161 (p=0.39).
23. **gain/loss/tie**: reported per contrast in `R20_MAIN_RESULTS.md`.
24. **McNemar**: all p ≥ 0.27.
25. **Repository-cluster CI**: all span 0.
26. **Practical-equivalence (interaction)**: NOT ESTABLISHED (90% CI [−0.06, +0.007] exceeds ±5pp) → POWER_LIMITED.
27. **USE/ABSTAIN coverage**: relevant 0.67, shuffled 0.00.
28. **false USE / false ABSTAIN**: not computable without an oracle; risk-side reported via net loss (≈0).
29. **positive/negative transfer**: within noise; no systematic negative transfer.
30. **gain retention / loss avoidance**: router trims injected tokens at equal resolve; net loss ≈ 0.
31. **adoption evidence**: governed execution views (no raw diff); no over-claimed adoption.
32. **token/turn/latency/cost**: `efficiency.json`; total ≈ $6.72 for all six arms.
33. **infra failures/retries**: B1 had 1 task infra failure (ITT unresolved); others 0.
34. **CI workflows**: ci-r20-freeze / factorial-parity / router-shuffled / analysis / docs (+ carried handoff gates).
35. **Six result labels**: BUNDLE / ORCHESTRATION / RELEVANCE / ROUTER_MAIN / INTERACTION = **NULL/INCONCLUSIVE**; PRACTICAL_EQUIVALENCE = **NOT ESTABLISHED (POWER_LIMITED)**.
36. **Company docs claim change**: none required — no new efficacy established; STATUS efficacy stays NOT ESTABLISHED.
37. **merge/release recommendation**: **do not merge, do not tag.** Keep PR #3 DRAFT.

## One-paragraph conclusion
On 248 untouched confirmatory tasks, no component of the system — the full bundle, the planning/orchestration
scaffold, relevant memory content, the utility router, or the router×relevance interaction — produced a
statistically significant effect on task success; every paired contrast is null and the interaction is
power-limited at the ±5pp margin. The R19-SMALL bundle-level signal (A5>A0) did not replicate, and even the earlier
"compute" lift (A1−A0) vanished (B1−B0 = 0.000), indicating both were small-sample noise. The router's only
robust, confirmed property is **safety**: it abstains on 100% of irrelevant cross-repo memory and never adds net
loss. This is consistent with the entire R14–R19 program: transferring another engineer's solved experience does
not reliably improve coding-task success for this reader/benchmark.
