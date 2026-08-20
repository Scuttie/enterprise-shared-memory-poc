# R18 — collective intelligence as a SET (K=5) — RESULT: NULL. The unit was not the problem either.

Reader gpt-4o-2024-08-06, frozen main-60. Injected TOP-5 semantically-retrieved same-repo prior fixes (M1multi)
vs 5 cross-repo (M2multi). Injection verified (inject_len median 7703, 0 empty, 0 non-ok terminal). The 5-set
raised gold-file coverage to 35% (vs 15% single).

| arm | Pass@1 |
|---|---|
| M0 (no memory) | 0.233 (14/60) |
| M2multi (5 irrelevant) | 0.250 (15/60) |
| M1multi (5 relevant) | 0.233 (14/60) |

- **Primary M1multi − M2multi = −0.017** (disc 3/4, McNemar **p = 1.0**): a relevant SET is indistinguishable from
  (slightly worse than) an irrelevant SET. M1multi − M0 = +0.000 (p=1.0).
- Covered stratum (5-set contains ≥1 gold-file source, n=21): M0 3 → **M2multi 5 = M1multi 5** — the irrelevant set
  matched the relevant set, so relevant CONTENT added nothing even where it structurally covered the target.
- More memory trended slightly negative (context dilution / distraction), not positive.

## Five levers now closed (SWE-bench Verified, ITT, preregistered)
| lever | fix | result |
|---|---|---|
| encoding | raw worked-example (R14) | null (N=180) |
| retrieval / relevance | semantic, product embedder (R15) | null |
| reader capability | gpt-4o mid-band (R16) | null |
| decoding / adaptation | adapt-to-target + matched control (R17) | null |
| aggregation / unit | 5-example relevant SET vs irrelevant SET (R18) | null |

Transferring other engineers' solved issues gives no reliable benefit — invariant to how it is encoded, retrieved,
who reads it, whether it is adapted to the target, and whether it is one example or a set. `arms_r18/`.
