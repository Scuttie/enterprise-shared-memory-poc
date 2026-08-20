# R14 relevance audit — the "relevance" manipulation was weak; the null tested same-repo-ness, not topical relevance

Post-hoc, no API/Docker. Question: was the M1 source ("same-repo temporally-nearest resolved issue") actually
TOPICALLY relevant to its target, or only same-repo? (Target gold used for AUDIT only, never in any agent context.)

## Finding 1 — M1 was barely relevant
| overlap (source ↔ target) | M1 ("relevant") | M2 (cross-repo control) |
|---|---|---|
| patched-file Jaccard | avg 0.027, median 0 | 0 |
| shares ≥1 patched file with target gold | **7/180 = 3.9%** | 0% |
| problem-text Jaccard | 0.079 | 0.031 |
| patch-text Jaccard | 0.110 | 0.072 |

96% of M1 sources touched entirely different files than the target's fix. M1 vs M2 differed mainly by *same-repo
yes/no*, NOT by *about-the-same-code*. So pooled M1≈M2 is expected and says little about whether *relevant* memory
helps — we never strongly manipulated relevance.

## Finding 2 — where the memory WAS relevant, it moved the needle (n tiny)
Stratify by whether M1 shared ≥1 patched file with the target:
- RELEVANT (n=7): M0=0.000 → **M1=0.143** (M1−M0 = +0.143); M2=0.143 (coincidental, n=7).
- NOT relevant (n=173): M0=0.098 → M1=0.110 (M1−M0 = +0.011).
Suggestive only (n=7), but consistent with "memory helps when it is actually about the same code."

## Finding 3 — a legal retriever can raise relevance ~3× (headroom)
Pick the M1 source by problem-statement text similarity over earlier same-repo issues (target ISSUE TEXT only; no
gold): problem-text Jaccard 0.079→**0.157**, shares-a-gold-file 3.9%→**11.7%**, patched-file Jaccard 0.027→**0.100**.

## Implication
Every prior null (R1/R11/R13/R14) may reflect weak RETRIEVAL, not "memory doesn't help." The next test (R15)
should select M1 by real topical retrieval (BM25/TF-IDF over past same-repo issue text), keep M2 as control, and
re-run — this is the genuine encoding/RETRIEVAL question. `artifacts/swebench_r14/relevance_audit.json`.
