# R20 Power Analysis (from R19 development data; NOT primary inference)

Estimated from the R19 60-task dev arms (`artifacts/r20/power_lock.json`).

| contrast (R19 analog) | discordant rate |
| --- | --- |
| F11−F10 (A5−A4) | 0.050 |
| F10−F00 (A4−A2) | 0.033 |
| B1−B0 (A1−A0) | 0.067 |
| (A5−A0) | 0.100 |

- Mean discordant rate ≈ 0.062 → ~16 discordant pairs at **N = 248**.
- Approx min detectable paired difference ≈ **0.032**.
- Interaction I is a difference of two paired diffs → CI ~√2 wider → min detectable ≈ **0.045**, essentially at the
  preregistered ±5pp practical margin.

**Consequence (stated before running):** the study can detect ~3pp paired effects but the **interaction may end
`POWER_LIMITED`** (CI wider than ±5pp). We still use ALL 248 untouched tasks; no N expansion, no task replacement,
no seed padding. A `POWER_LIMITED` verdict is a valid endpoint (§16-C).
