# R3 §13 — Matched-Decoder Ablation

**Not run as a paid matrix — descriptive, deprioritized (justified).** The §13 ablation asks, for the three best
bundles, whether a representation's gain requires its *matched* decoder (representation + matched vs +
generic vs plain + candidate decoder). It is meaningful only when some bundle shows a RelevantBundleLift to
attribute to a decoder.

In R3 the definitive discovery (with injection audited to 82/82 per arm) found **no bundle beats the
shuffled-matched baseline** (best lift +0.008 = 1 task of 82, noise) at a near-ceiling base rate. There is no
representation lift to decompose, so the ablation cannot distinguish representation value from decoder value —
it would compare noise to noise. Per §13 ("its results do not override the frozen policy-selection rule") the
ablation is not on the critical path, and running it as a paid 40-task × 3-condition matrix would consume budget
for an uninterpretable result under the same ceiling that triggered the §16 CALIBRATION STOP.

The ablation *hooks* are implemented and unit-tested (`renderers.render(bundle, canon, decoder=GENERIC_DECODER)`;
decoder hashes frozen in `decoder_manifest.json`), so the ablation is runnable in a future
`REALBENCH_ACTIONABLE_MEMORY_R4` on a benchmark/model pairing with dynamic range.
