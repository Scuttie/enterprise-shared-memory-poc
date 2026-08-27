# R22 §1.5 — power feasibility (paired McNemar, deterministic)

Computed by `experiments/r22/data_orientation.py`; grid in `artifacts/r22/power_grid.json`. Primary uses the
Holm-most-stringent level for 3 primary hypotheses: `alpha = 0.05/3 ≈ 0.0167`; power target 0.80.

## Held-out main size
- main pairs (CLEAN_RELATED, v2): **N = 68**
- repository clusters: 18; avg cluster size ≈ 3.8; design effect (ρ=0.05) ≈ 1.14 → **effective N ≈ 59.7**

## Detectable effect at N=68 (power at current N)
| Effect \ discordant | 0.10 | 0.15 | 0.20 | 0.30 |
| --- | ---: | ---: | ---: | ---: |
| +3pp | very low | very low | low | low |
| **+5pp** | — | **~0.09** | **~0.09** | low |
| +7pp | low | low–mod | mod | mod |
| +10pp | mod | mod | mod–high | high |

Median power for a **+5pp** effect at the current main N is **≈ 0.09** — far below 0.80. Required N for +5pp at
80% power is in the several-hundreds range (see grid), i.e. the current public related-target held-out pool is too
small for a confirmatory +3–5pp claim.

## Verdict: `POWER_LIMITED_BUT_ORACLE_FEASIBLE`
- A confirmatory held-out **main** claim of +3–5pp is **underpowered** at N≈68 (effective ≈60).
- The **oracle** mechanism test (O6−O2 on the 58-pair dev split) targets a *larger* information-value effect and
  is an interpretable mechanism contrast, so it remains feasible and worth running first.
- **MCID is NOT inflated** to compensate: the preregistered practical-equivalence / MCID stays as set; we report
  the underpowered main honestly rather than raising the threshold to manufacture significance.

## Implication for approval
Request the **oracle** budget (P1 smoke + P2 oracle) first. Do **not** request the main confirmatory budget until
a larger chronologically-valid task pool exists (e.g. precise merge-time reorientation, or additional
related-target curation) — otherwise a null/positive main would be uninterpretable for lack of power.
