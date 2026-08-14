# BigCode-R2 Preregistration (§10–§12, §18)

Committed BEFORE any calibration/main model call. Fixes the arms, hypotheses, analysis, and stopping rule.
The discovery-selected memory representation is frozen in `artifacts/bigcode_r2/selected_policy.json` (chosen
by the predeclared §8 rule in `experiments/bigcode_r2/discovery.py`, committed before discovery ran) and is
NOT changed after seeing any confirmatory outcome.

## Benchmark & model (frozen)
- BigCodeBench-Instruct v0.1.4 (pkg 0.2.4), content-hash `98e377a8…`, official grader in the eval image.
- `solar-pro2-251215`, temperature 0, one generation, **no primary repair**, fixed output budget (2048).
- Production embedder `sentence-transformers/all-MiniLM-L6-v2` (384-d). Frozen partition `6e075558`.

## Arms (§10) — one org, 24 source + 24 target users; source_user ≠ target_user for shared arms
| Arm | Memory |
|---|---|
| M0 | NO_MEMORY |
| M1 | PRIVATE_SELECTED — target user's own prior verified source, selected format |
| M2 | TRUE_RELEVANT_SELECTED — evaluator-relevant source (over verified bank), cross-user, selected format, oracle-forced |
| M3 | SHUFFLED_MATCHED_SELECTED — frozen derangement, same injection indicator as M2, selected format |
| M4 | DEPLOYABLE_RETRIEVED_SELECTED — production embedder top-1 + abstention, selected format |
| M5 | ALWAYS_INJECT_TOP1_SELECTED — production top-1, threshold off (diagnostic; NOT an oracle) |
| M6 | RELEVANT_PLAIN_SAME_SOURCE — same source as M2, F1 plain |
| M7 | RELEVANT_GOVERNED_SAME_SOURCE — same source as M2, F3 governed, same injection/position/budget as M6 |

If the selected representation is plain (F1) or governed (F3), the matching same-source arm is a logical alias
of M2 (one physical arm; no duplicate calls).

## Hypotheses (§11) — fixed sequence, α=.05, two-sided paired
- **E1 (primary): M2 > M3** — does relevant memory help beyond generic matched extra context?
- **E2 (only if E1 rejects): M4 > M0** — does the deployable retrieved memory help over no memory?
- **Secondary (Holm-corrected):** M7−M6 (governed vs plain, same source), M2−M4 (retrieval headroom),
  M1−M0 (private effect), M5−M4 (threshold/abstention effect). "Significant in one but not the other" is NOT
  taken as evidence the effects differ.

## Sample size & analysis (§12)
- **N = 500** paired CONFIRMATORY_MAIN targets (frozen, disjoint from source/dev/discovery/calibration).
- Rationale: MBPP+ discordance ~0.15 at a 0.05 paired effect ⇒ ~470 pairs for 80% power at two-sided .05.
- **Intention-to-treat is primary**: every submitted target counted; terminal infrastructure failures scored
  as failure. **Complete-case is a separate sensitivity** (never substituted as primary).
- Reporting: exact counts, paired difference, task-cluster bootstrap 95% CI, exact McNemar, positive/negative
  transfer (§14, evidence-based patch adoption), per-arm efficiency. **A null result is final.** No task/
  setting/benchmark is added after inspecting a p-value; no early stop for significance/futility.

## Calibration gates (§9) — instrument, not efficacy
C1 official grader (setup 0, malformed ≤0.02; canonical 100% in ci-bigcode-grader) · C2 service path · C3
no-memory Pass@1 ∈ [0.10, 0.90] · C4 multi-user safety (cross-user private injection 0; source/target overlap
0) · C5 retrieval integrity (production embedder; leakage 0) · C6 reproducibility (hashes match freeze,
selected policy unchanged). **A null/negative memory effect does NOT close the main run** — if C1–C6 pass, the
main runs regardless of discovery direction.

## Frozen-after-results (§18)
No task replacement, no policy replacement, no threshold adjustment, no arm addition, no endpoint change, no
sample-size increase. A redesign requires BIGCODE_R3.
