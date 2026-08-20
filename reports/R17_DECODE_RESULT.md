# R17 — decoding (adapting) memory to the target — RESULT: NULL, and the matched control localizes why.

Reader gpt-4o-2024-08-06, frozen main-60. A gpt-4o-mini DECODE step rewrote the retrieved relevant prior fix into
guidance adapted to the target issue (files/functions/conditions), injected instead of the raw diff. Injection
verified: inject_len median ~1300, zero empty; decode fields correct. Decoder never saw target gold/tests.

## Result
| arm | Pass@1 |
|---|---|
| M0 (no memory, no decode) | 0.233 (14/60) |
| D0 (decode issue-only planning; NO memory) | 0.217 (13/60) |
| M1dec (decode issue + relevant prior fix) | 0.233 (14/60) |

- **Primary H = M1dec − D0 = +0.017** (discordant 5/4, McNemar **p = 1.0**) → null. Decoded relevant memory does
  NOT beat equal-compute planning.
- M1dec − M0 = +0.000 (p=1.0). D0 − M0 = −0.017 (planning alone slightly hurt).
- Truly-relevant slice (n=9): M0 2/9 → **D0 3/9 = M1dec 3/9** — the memory-bearing arm equals the memory-free
  planning arm, so even the +1 there is planning compute, not memory content.
- Churn: M1dec gained 5 / lost 4 vs D0 (net +1, noise); it even LOST the R16 flagship near-dup sphinx-8595.

## Reading
The matched control is the point: giving the model an ADAPTED, target-localized version of a genuinely relevant
prior fix adds nothing over having it write a plan from the issue alone. So the residual movement in earlier arms
was "think-first" compute, not transfer of the memory's content. Decoding/adaptation does not unlock transfer.

## Four levers now closed against the memory-helps hypothesis (SWE-bench Verified)
| lever | fix tried | result |
|---|---|---|
| encoding | RAW worked-example (real prior issue + gold diff) — R14 | null (N=180) |
| retrieval / relevance | SEMANTIC retrieval, product embedder, 3–4× relevance — R15 | null |
| reader capability | gpt-4o mid-band (0.233) — R16 | null |
| decoding / adaptation | adapt memory to target + matched planning control — R17 | null (M1dec−D0 p=1.0) |

## Bottom line
Transferring another engineer's solved issue gives no reliable benefit on SWE-bench Verified — robust to encoding,
retrieval, reader strength, and an active decode step, with a control showing the tiny residual is generic planning
compute, not memory. Genuinely near-duplicate cases can flip individually (e.g. R16 sphinx-8595) but do not
aggregate. `artifacts/swebench_r14/arms_r17/`.

## Honest scope
Per-arm n=60; single reader family ≤ gpt-4o; single-shot injection; the decoder is gpt-4o-mini (a stronger decoder
might differ, but it would be doing the solving, not the memory). Untested: agent-initiated mid-trajectory
retrieval, many-memory context, readers ≫ gpt-4o.
