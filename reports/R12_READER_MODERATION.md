# R12 §8 — Reader Moderation (OpenAI gpt-4o-mini vs frozen Solar-pro3, difference-of-differences)

Task-paired DiD on the 109 memory-covered targets, holding memory content/retrieval/prompt fixed and changing
only the reader. Diagnostic (no confirmatory p-value).

## Difference-of-differences
| quantity | OpenAI diff | Solar diff | DiD (OpenAI − Solar) | boot95 CI |
|---|---|---|---|---|
| Relevant vs shuffled (M1 − M2) | −0.018 | +0.009 | **−0.028** | [−0.110, +0.055] |
| Memory vs none (M1 − M0) | −0.037 | −0.009 | **−0.028** | [−0.110, +0.046] |

Both DiD confidence intervals **include 0** → **no significant reader moderation of the memory effect.** The
memory contrast (relevant − shuffled) is ~null under *both* readers; swapping to a much stronger reader does not
turn the transferred memory from useless into useful.

## Interpretation (matrix)
- **Reader capability was a major bottleneck for raw accuracy** (M0: 0.147 → 0.367 on covered; band 0.115 →
  0.25–0.74). So a large part of the prior Solar floor was the reader.
- **The transferred memory is the binding limitation for the memory *effect***: relevant ≈ shuffled under both
  readers; a 2.5× stronger baseline does not create a relevance benefit. → milestone interpretation **B**
  (content/relevance, not the reader alone, limits the effect).
- Not **C** (a stronger reader does not merely make memory redundant — memory is already non-helpful for Solar
  too); not **D** (baseline is not low); **E** does not replicate (actionable interference was Solar-specific).

## Bottom line
R12 cleanly separates the two: **reader capability mattered a lot for how many problems get solved, but the
Solar-written, relevance-retrieved memory does not help even a much stronger reader.** The repeated
null/floor "memory" results were therefore driven primarily by (a) a weak reader for raw capability AND (b) a
genuinely non-useful memory channel for the *effect* — the stronger reader fixes (a) but not (b).
