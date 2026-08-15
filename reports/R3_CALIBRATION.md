# R3 §16 — Instrument Calibration

Technical calibration of the R3 instrument on the frozen `INSTRUMENT_CALIBRATION` split (100 tasks), 6 arms
(C0 no-memory; C1 selected-relevant=M2; C2 shuffled=M3; C3 production-retrieval=M4; C4 plain-relevant=M1;
C5 gold=M6), selected bundle **B5**. Real service path + official DS-1000 grader + oracle direct-load injection
(the fixed path — discovery injection audit confirmed D1–D11 = 82/82). Run `31898317604` (3-chunk). Gates are
technical; a null/negative memory effect does NOT block the main — only technical failures do (§16).

## Arm Pass@1
| C0 no-mem | C1 relevant(B5) | C2 shuffled | C3 retrieval | C4 plain | C5 gold |
|---|---|---|---|---|---|
| **0.98** | 0.97 | 0.99 | 0.99 | 0.99 | 0.99 |

## Gate results
| gate | result |
|---|---|
| G1 malformed ≤ 0.02 | **PASS** |
| **G3 dynamic range: C0 ∈ [0.10, 0.90]** | **FAIL — C0 = 0.98 (near-ceiling)** |
| G4 cross-user private injection = 0 | PASS |
| G4 C0 injects no memory | PASS |
| G6 production embedder (all-MiniLM-L6-v2) | PASS |

(G2 service-path, G5 representation-integrity, G7 reproducibility are structural/by-construction — every task
went HTTP→durable job→worker; same source ID for selected-vs-plain; token budget enforced by the renderer;
freeze hashes committed. They are satisfied; G3 is the binding gate.)

## Decision — §0-C CALIBRATION STOP
**G3 fails: no-memory Pass@1 = 0.98 is far above the 0.90 ceiling.** solar-pro2 already solves ~98% of the
calibration tasks (and 92.5% of the discovery split) with no memory, so the instrument has **no dynamic range**
in which a memory representation could demonstrably help. Per the frozen §16 rule, **the confirmatory main is
NOT run.** Result recorded in `artifacts/actionable_memory_r3/results/calibration_results.json`; full rationale
in `reports/R3_CALIBRATION_DECISION.md`.

This is the honest, preregistered endpoint the gate is designed to enforce — running the confirmatory main at a
0.98 base rate would violate the §16 gate and could only produce a ceiling-confounded (uninterpretable) result.
