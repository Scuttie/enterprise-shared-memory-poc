# R6 §1 — R5 Reward Forensics (offline, no model calls)

Forensic re-analysis of the R5 A0 NO_SKILL calibration (Solar-pro2 repository-agent, 30 reproducible tasks) to
test whether the 0/30 was a *binary* floor or a hidden partial-progress signal. Source: the persisted R5
artifacts (`artifacts/swe_skills_r5/A0_calibration_results.json` + `A0_batch{1,2,3}.json`). No new model calls;
R5 evidence is immutable.

## Result — a clean BINARY floor
| classification | count |
|---|---|
| BINARY_TOTAL_FAILURE (verifier ran, reward = 0) | 27 |
| TOOL_OR_ENV_FAILURE (agent error, reward = None) | 3 |
| PARTIAL_OFFICIAL_REWARD / other | 0 |

- **Raw reward > 0: 0 / 27.** Mean = median = **0.0**.
- **The official SkillsBench verifier is strictly binary** — the only reward value observed anywhere in the 30
  trajectories is `0.0` (verifiers emit `reward ∈ {0,1}`, no fractional subcriteria). There is therefore no
  partial-credit signal to recover, and (per §3) **exact success remains the KPI** — we do not invent a custom
  partial score.
- **Tool-calls vs reward:** tool calls ranged 0–29 (median 9); **reward was 0 for every task regardless of tool
  count.** The agent explored/edited actively yet produced no passing solution — a genuine capability floor, not
  under-attempting.

## What is NOT recoverable offline (honest limitation)
The finer §1 classes (WRONG_OUTPUT_CONTENT / MISSING_REQUIRED_FILE / WRONG_PATH_OR_FORMAT) require the per-task
verifier subcriteria and the agent's final files. SkillsBench verifiers do not emit subcriteria (binary reward),
and the R5 upload persisted only the run summary + trajectory tails, not each job's `jobs/*/` final workspace.
So these classes cannot be populated from the frozen R5 artifacts without re-running — which R6 does NOT do
(R5 is preserved; the 2×2 diagnostic in §2 captures final-file/verifier detail going forward).

## Implication for R6
The 0/30 no-skill floor is **binary and real** — but a binary floor at NO_SKILL is exactly what a
*skill-essential* ("necessity regime") task set would produce. It does **not** show the official skill cannot
help. R6 §2 therefore tests the missing condition: **A1 OFFICIAL_ORIGINAL_SKILL** across readers (Solar-pro2 and
Solar-pro3), to see whether the skill moves any reader off the floor (≥3/30 exact successes, ≥3 net gains over
A0) — the reader-skill viability question R5 never asked.
