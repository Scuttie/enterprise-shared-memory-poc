# R3 §12/§14 — Representation Discovery Results

Descriptive discovery on the frozen `REPRESENTATION_DISCOVERY` split (120 tasks, `split_hash e16bfb852f7395cb`),
12 arms (D0 no-memory; D1 shuffled-matched baseline; D2–D11 = relevant memory rendered in bundles B0–B9), through
the real service path (oracle-forced rendered views) + official DS-1000 grader. Run `31894571715` (6-chunk
matrix). Relevance threshold frozen at 0.1 (coverage-driven; 82/120 targets had a same-library relevant source).

## Result — NULL representation effect at a near-ceiling base rate
| arm | D0 | D1(shuf) | D2 B0 | D3 B1 | D4 B2 | D5 B3 | D6 B4 | D7 B5 | D8 B6 | D9 B7 | D10 B8 | D11 B9 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pass@1 | .933 | .933 | .917 | .925 | .925 | .933 | .933 | .933 | .925 | .933 | .933 | .933 |

**RelevantBundleLift (relevant − shuffled) by bundle:** B0 −.017, B1 −.008, B2 −.008, B3 .000, B4 .000, B5 .000,
B6 −.008, B7 .000, B8 .000, B9 .000. **Best lift = 0.000.** No representation of relevant memory beats the
shuffled-matched baseline; several are marginally negative. This replicates the R1/R2 pattern (memory does not
beat a matched control) — now across the full actionability ladder (prose → structured → procedural →
executable-constraint → code-edit).

**The completions are genuinely correct** (e.g. `df['category'] = df.idxmax(axis=1)`); failures cluster in
Pytorch/Tensorflow. The base **no-memory Pass@1 = 0.933 is near-ceiling** — solar-pro2 is strong on DS-1000
completion mode (heavy prompt scaffolding). At 93% base there is little headroom for any memory representation
to help, so the null is **confounded with a ceiling** and is not, by itself, strong evidence that actionable
representations cannot help — only that they do not help *here, at this base rate*.

## Predeclared §14 selection (lexicographic — computed, not chosen by us)
1. HARD SAFETY: all 10 bundles pass (views are redacted — renderer-test-verified — so source-identifier copying
   is 0 by construction; target/hidden-test/cross-user/invalid-state all 0).
2. ACTIONABILITY (max lift): best 0.000; survivors within 0.01 = all bundles at ~0.
3. ROBUSTNESS (min memory-induced loss): B1–B9 survive.
4. CODE REALISATION (min parser+realisation): B4, B5, B7, B8 survive.
5. EFFICIENCY (min injected tokens): **B5** alone (fewest tokens).
6. → **SELECTED = B5 (GENERALIZED_DIFF_TEMPLATE)**.

**B5 is selected by the efficiency tie-break among null-lift bundles, NOT because it improves correctness.** The
full calculation is frozen in `artifacts/actionable_memory_r3/selected_policy.json`; once selected it cannot
change (§14).

## §0-B DISCOVERY STOP check
The stop condition is "executable/code-edit bundles do NOT outperform *or even match* the plain representation".
Here all bundles ≈ plain ≈ no-memory (all ~0.93) — they **match** (do not underperform) plain, so this is not a
DISCOVERY STOP; a bundle is selected and the study proceeds to calibration. **However**, the near-ceiling base
rate is a direct **§16 G3 dynamic-range risk** (G3 requires no-memory Pass@1 ∈ [0.10, 0.90]); the calibration
gate will formally decide whether the confirmatory main can run or whether this ends at a §0-C CALIBRATION STOP.

## §13 matched-decoder ablation
Given the null discovery lift at ceiling, the matched-decoder ablation (representation vs generic decoder) is
uninformative here (no representation shows a lift to attribute to a decoder). It is recorded as descriptive and
deprioritized rather than run as a paid matrix; the selection rule does not depend on it (§13).
