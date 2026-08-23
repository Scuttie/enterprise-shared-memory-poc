# R3 §12/§14 — Representation Discovery Results

Descriptive discovery on the frozen `REPRESENTATION_DISCOVERY` split (120 tasks, `split_hash e16bfb852f7395cb`),
12 arms (D0 no-memory; D1 shuffled-matched baseline; D2–D11 = relevant memory rendered in bundles B0–B9), through
the real service path (oracle-forced rendered views) + official DS-1000 grader. **Definitive run `31897045584`**
(6-chunk matrix). Relevance threshold frozen at 0.1 (coverage-driven; 82/120 targets had a same-library relevant
source).

## CORRECTION — an oracle-injection bug invalidated the first run (integrity note)
The first discovery run (`31894571715`) is **void**: an injection-rate audit found the oracle path was
*filtering* the top-k semantic hits by `oracle_id` rather than force-loading the version, so rendered views
dissimilar to the NL instruction were never retrieved and never injected (**B5 diff-templates: 0/120 injected**;
other arms 5–38/120 — wildly uneven). The "null" it produced was a **no-injection artifact**. Fixed in two
steps: (1) oracle now direct-loads the promoted version, bypassing vector search; (2) the direct-load runs inside
the tenant/RLS transaction (a plain connection is row-level-security-filtered to zero rows). **Post-fix injection
audit: D0 = 0, D1–D11 = 82/82 each** (every target with a relevant source received the memory, in every bundle).
All numbers below are from the corrected run.

## Result — a REAL NULL representation effect (correct injection) at a near-ceiling base rate
| arm | D0 | D1(shuf) | D2 B0 | D3 B1 | D4 B2 | D5 B3 | D6 B4 | D7 B5 | D8 B6 | D9 B7 | D10 B8 | D11 B9 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pass@1 | .925 | .925 | .925 | .925 | .925 | .933 | .925 | .925 | .925 | .917 | .917 | .925 |
| injected | 0 | 82 | 82 | 82 | 82 | 82 | 82 | 82 | 82 | 82 | 82 | 82 |

**RelevantBundleLift (relevant − shuffled) by bundle:** B0 .000, B1 .000, B2 .000, B3 +.008, B4 .000, B5 .000,
B6 .000, B7 −.008, B8 −.008, B9 .000. **Best lift = +0.008 (B3, = 1 task of 82 — noise).** With memory correctly
delivered in *every* representation to all 82 covered targets, **no bundle beats the shuffled-matched baseline.**
This is now a genuine null (not a no-injection artifact) and replicates the R1/R2 pattern across the full
actionability ladder (prose → structured → procedural → executable-constraint → code-edit).

**The completions are genuinely correct** (e.g. `df['category'] = df.idxmax(axis=1)`); failures cluster in
Pytorch/Tensorflow. The base **no-memory Pass@1 = 0.933 is near-ceiling** — solar-pro2 is strong on DS-1000
completion mode (heavy prompt scaffolding). At 93% base there is little headroom for any memory representation
to help, so the null is **confounded with a ceiling** and is not, by itself, strong evidence that actionable
representations cannot help — only that they do not help *here, at this base rate*.

## Predeclared §14 selection (lexicographic — computed, not chosen by us)
1. HARD SAFETY: all 10 bundles pass (views are redacted — renderer-test-verified — so source-identifier copying
   is 0 by construction; target/hidden-test/cross-user/invalid-state all 0).
2. ACTIONABILITY (max lift): best +0.008 (B3); survivors within 0.01 = all bundles (all lifts ≈ 0).
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
