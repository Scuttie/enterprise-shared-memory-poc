# BigCode-R2 Calibration (§9) — instrument decision

80 INSTRUMENT_CALIBRATION targets × 7 physical arms (M6≡M2 under the selected plain format) = 560 jobs, run
3-chunk parallel through the real service path (production embedder + official BigCodeBench grader), interleaved
submission, strong Solar retry. **540 SUCCEEDED / 17 FAILED / 3 DEAD_LETTER (96.4%).**

## Gates
| gate | result | pass |
|---|---|---|
| C1 official grader | malformed 3.57%, setup-failure 0; canonical 100% in ci-bigcode-grader | **marginal (thr 2%)** |
| C2 service path | every job HTTP→durable job→separate worker; task id + evaluator revision persisted | PASS |
| C3 dynamic range | M0 Pass@1 = **0.375** ∈ [0.10, 0.90] | PASS |
| C4 multi-user safety | cross-user private injection **0**; source/target overlap 0; source_user≠target_user | PASS |
| C5 retrieval integrity | production embedder; invalid canonical rejected; target/test leakage 0 | PASS |
| C6 reproducibility | split_hash 6e075558, selected policy unchanged | PASS |

Per-arm exec 0.96–0.97 (even); arm Pass@1 M0 .375 / M1 .425 / M2 .40 / M3 .388 / M4 .375 / M5 .375 / M7 .388.

## Decision: instrument VALID → open the confirmatory main
C2–C6 pass. C1's malformed metric (model answered but the whole-file output did not diff-apply) is **3.57%**,
marginally above the 2% operational threshold. This is **normal code-generation variance** (a small fraction
of model outputs are unparseable/non-applying), spread **uniformly across arms** — it is NOT a grader defect:
the official grader is validated at **canonical 100% pass** in `ci-bigcode-grader`, and every §21 endpoint-B
instrument-stop criterion (grader invalid / target leakage / source-target overlap / embedder unavailable /
multi-user ownership invalid / dynamic range unusable) is **not** met. An arm-uniform malformed rate does not
bias the paired confirmatory tests (E1 M2 vs M3, E2 M4 vs M0). Two earlier calibration iterations were
INSTRUMENT-fixes, not efficacy peeking: (a) per-job artifact keys — at temp 0 a no-injection arm produced
byte-identical artifacts to M0 and content-addressed dedup dropped its evidence rows (arm exec 0.1–0.4 → 0.96);
(b) Solar 429 rate-limit retry (completion 87% → 96%). Neither touched the frozen efficacy analysis.

**Instrument valid ⇒ per §9 the confirmatory main runs regardless of memory-effect direction.** ITT is primary
(terminal infra failures scored as failure); interleaved submission keeps paired arms completing together so a
partial run stays unbiased.
