# R16 — stronger reader (gpt-4o) × relevant memory — RESULT: still NULL. Closes the last counter-explanation.

Tests the only open question after R14/R15: does a MID-BAND reader exploit genuinely-relevant memory that the
low-band gpt-4o-mini could not? Reader gpt-4o-2024-08-06 on the same frozen main-60; M0 (no memory) vs M1sem (the
semantic-retrieved relevant prior fix reused verbatim from R15). Identical harness/memory/controls.

## Result
| arm (gpt-4o, same 60) | Pass@1 |
|---|---|
| M0 (no memory) | 0.233 (14/60) |
| M1sem (relevant real prior fix) | 0.233 (14/60) |

- gpt-4o is solidly mid-band (0.233, ~3× mini's 0.083) — not ceiling/floor, memory effect is measurable.
- **M1sem − M0 = +0.000**, discordant 4 (M1-only) / 4 (M0-only), McNemar **p = 1.0**. Memory *churned* solves
  (gained matplotlib-24570, pytest-5631, sphinx-8595, sympy-13877; lost astropy-8707, django-11555, sklearn-13135,
  sklearn-13779) for **zero net effect** — the signature of distraction/noise, not transfer.
- Truly-relevant slice (semantic source shares a gold file, n=9): M0 2/9 → M1sem 3/9 (+1, within noise). The
  flagship near-duplicate sphinx-8595 (cos 0.87, same file `autodoc/__init__.py`) flipped fail→pass WITH memory —
  concrete evidence that genuinely-relevant memory *can* help individual cases, but such wins are cancelled by
  equal distraction losses, so there is no aggregate benefit.

## The three counter-explanations are now all closed
| critique | fix tried | result |
|---|---|---|
| memory encoded badly (distilled abstraction) | RAW worked-example: real prior same-repo issue + actual gold diff (R14) | null (N=180 confirmed) |
| relevance defined badly (recency ≠ topical) | SEMANTIC retrieval with the product's own embedder, 3–4× more relevant (R15) | null |
| reader too weak to use memory | gpt-4o mid-band, 3× the band (R16) | null |

## Bottom line
Across two readers spanning an 8%→23% band, with genuinely-relevant (often near-duplicate) real prior fixes
retrieved by the production embedder and injected as raw worked examples, transferring another engineer's solved
issue gives **no reliable benefit** on SWE-bench Verified. Individual near-duplicate cases can help, but on average
the help is offset by distraction. This is the program's robust final negative: the null is not an artifact of
weak encoding, weak retrieval, or a weak reader.

## Honest residual scope
Per-reader n=60 (churn/near-zero, so more N tightens around 0). Two readers, one benchmark family (repo-level Python
bug-fix). Single-shot injection of one memory; not tested: multi-memory context, an agent that CHOOSES to retrieve
mid-trajectory, or readers far stronger than gpt-4o. The near-duplicate wins (e.g. sphinx-8595) suggest the ceiling
of the effect is real-but-small and swamped by noise at this scale. `artifacts/swebench_r14/arms_r16/`.
