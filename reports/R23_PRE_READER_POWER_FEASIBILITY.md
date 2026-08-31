# R23-B0 — Preliminary power grid (pre-reader)

No model outcome exists yet, so the final N is **not** claimed. `artifacts/r23/power_grid_pre_reader.json`. Paired
McNemar; Holm 1st-primary α = 0.05/3 = **0.0167**; power **0.80**; **MCID fixed at +0.05 absolute Pass@1** (not
changed for pool size). N is per primary comparison (paired tasks) ≈ `(z_α+z_β)²·discordance/effect²`.

| baseline | discordance | required N (paired) for +0.05 |
|---|---|---|
| 0.30 | 0.15 | ~629 |
| 0.30 | 0.25 | ~1048 |
| 0.30 | 0.35 | ~1467 |

Selected implications (illustrative, honest):
- **Full-500 is the maximum paired N per comparison.** For +0.05 at plausible discordance (0.25) it is **under the
  ~1048 needed → underpowered for the MCID** at the streaming/paired design; +0.07–+0.10 effects (or lower
  discordance) are detectable at N=500. The MCID is **not** lowered to fit the pool.
- **Repository clustering** (django 231/500) inflates the effective N via a repository design effect + demands
  repository-cluster bootstrap CIs; the naive paired N understates the requirement.
- The **R23-X conditional-efficacy N** is bounded by the *confirmed temporally-eligible × semantic-overlap* pool,
  which is **UNKNOWN** until fix-merge timestamps (B0.1) and atoms/graphs (A0/G0) exist — so R23-X viability cannot
  be asserted yet.

This is a preliminary feasibility grid; the binding calibration (real baseline Pass@1 and discordance) is measured
in the reader-band + reproduction-calibration paid stages, not assumed here.
