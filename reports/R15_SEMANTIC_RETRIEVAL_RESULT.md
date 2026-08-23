# R15 — semantic retrieval for M1 (the product's own embedder) — RESULT: better retrieval did NOT help. NULL.

Addresses the critique that the R14 null reflected a weak RELEVANCE definition (recency ≠ topical). R15 re-selects
the M1 source by SEMANTIC retrieval with the product's own embedder (`multi-qa-MiniLM-L6-cos-v1`, 384-d — the model
`enterprise_memory/backends/mem0_backend.py` uses), ranking earlier same-repo issues by cosine over the target's
ISSUE TEXT only (no gold, no leakage). M0 and M2 from R14 are reused unchanged (independent of M1 source choice);
only the M1 arm was re-run, on the same frozen main-60.

## Retrieval quality really did improve (pre-run audit)
| relevance of M1 source ↔ target | recency (R14) | semantic (R15) |
|---|---|---|
| shares ≥1 patched file with target gold | 5.0% | **15.0%** |
| patched-file Jaccard | 0.025 | **0.108** |
| M1 source changed vs recency | — | 50/60 (83%) |

## Outcome — no benefit at all
| arm (same 60 targets) | Pass@1 |
|---|---|
| M0 (no memory) | 0.083 (5/60) |
| M2 (shuffled cross-repo) | 0.083 (5/60) |
| M1 recency (R14) | 0.150 (9/60) ← non-replicating blip |
| **M1 SEMANTIC (R15)** | **0.083 (5/60)** |

- M1sem − M0 = **+0.000** (discordant 3/3, McNemar p=1.0). M1sem − M2 = +0.000 (3/3, p=1.0).
- M1sem − M1recency = −0.067 (semantic did *worse* than recency; the recency solves were unrelated to relevance).
- Truly-relevant stratum (semantic source shares a gold file, n=9): M0 = 2/9 = 0.222 → **M1sem = 1/9 = 0.111**
  (memory did not help even where it was genuinely about the same code; slight harm, n small).

## Verdict — the "retrieval was the bottleneck" hypothesis is refuted at this reader
Tripling/quadrupling topical relevance (recency → semantic, 5%→15% file overlap) produced **zero** lift; the
semantic M1 sat exactly at the no-memory baseline and below the recency arm. Even in the slice where the memory was
verifiably about the same file, it did not help. So the earlier nulls are **not** explained away by weak retrieval:
with a genuinely relevant real prior fix (product embedder, worked-example content), gpt-4o-mini gains nothing on
SWE-bench Verified. Combined with R14-CONFIRM (N=180 null), the program's finding stands and is now robust to the
two strongest counter-explanations (bad encoding → raw worked-example; bad retrieval → semantic).

## Honest scope
n=60 for M1sem (flat/slightly-negative, so more N would tighten around 0, not reveal a hidden positive). Single
low-band reader (~8%). The remaining open question is a HIGHER-CAPABILITY reader in a mid-band — it stays possible
that relevant memory helps a model strong enough to exploit it; that is a reader-capability question, not a
retrieval or encoding one. `artifacts/swebench_r14/arms/M1sem/`, `sem_relevance_gain.json`.
