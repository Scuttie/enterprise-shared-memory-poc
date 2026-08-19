# R13 — Memory Representation (Encoding) Study — Result: representation is NOT the lever (here)

Fixed source/relevance/reader/benchmark (reused R11: 109 covered targets, 61 verified sources, relevant+shuffled
mapping); varied ONLY the encoding. Reader gpt-4o-mini (mid-band M0 = 0.367). Distilled encodings (gpt-4o-mini
distils each source problem+solution into 5 formats).

## RelevantLift_F = Pass@1(relevant-F) − Pass@1(shuffled-F), 109 covered
| format | name | RelevantLift | McNemar p | boot95 CI | vs M0 | inject_len |
|---|---|---|---|---|---|---|
| F0 | PLAIN | +0.018 | 0.69 | [−0.028, +0.064] | −0.018 | 600 |
| F1 | API_CARD | −0.028 | 0.25 | [−0.064, 0.00] | −0.055 | 1176 |
| F2 | EXECUTABLE | +0.009 | 1.00 | [−0.018, +0.037] | −0.028 | 1277 |
| F3 | POS_NEG | −0.009 | 1.00 | [−0.046, +0.028] | −0.028 | 1273 |
| F4 | SKELETON | −0.028 | 0.25 | [−0.064, 0.00] | −0.046 | 696 |

## Finding
**No encoding format produces a relevant-lift** (all RelevantLift ≈ 0, none significant), and **every format is
slightly negative vs no-memory** (M0 0.367), with the longer/structured formats (API-card, skeleton) hurting
most. On LiveCodeBench competitive programming with gpt-4o-mini, *how* you encode a distilled memory does not
matter — none helps.

## Interpretation + why R14
Two non-exclusive causes, both addressed by R14: (1) the memory was a gpt-4o-mini **distilled abstraction**
(generic lessons that lose the transferable specifics) rather than a concrete worked example; (2) **competitive
programming is a poor transfer domain** — each problem is a self-contained puzzle, so a "similar" earlier problem
rarely shares the needed technique. R14 fixes both: **raw worked-example memory (a real prior same-repo resolved
issue: problem + actual diff)** on **SWE-bench Verified** (repository-level, where the same codebase/APIs/patterns
recur → collective experience is a-priori plausible). A null there would be a much stronger claim.

`artifacts/repr_r13/main_result.json`. R1–R12 + P6 frozen; PR#1 draft; P6 not resumed.
