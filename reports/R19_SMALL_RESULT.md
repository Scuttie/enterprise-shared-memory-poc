# R19-SMALL — held-out utility-router result: UTILITY_ROUTER_NULL

Reduced-power confirmatory run (60 repo-stratified held-out tasks, frozen by hash before running; reader
gpt-4o-mini, fixed across arms; official grader; ITT). Same r14 agent for every arm — only the injected memory
text differs (parity by construction). Cards compiled to governed **execution views (no raw diff)** — what the
product actually injects.

## Resolved rate by arm
| arm | what it injects | Pass@1 |
| --- | --- | --- |
| A0 | nothing | 0.083 (5/60) |
| A1 | neutral planning scaffold (no history) | 0.150 (9/60) |
| A2 | shuffled cross-repo execution views | 0.167 (10/60) |
| A3 | one static relevant execution view | 0.117 (7/60) |
| A4 | agentic-reference selected (no router) | 0.167 (10/60) |
| **A5** | **utility-router gated** | **0.183 (11/60)** |

## Preregistered contrasts (exact McNemar + repository-cluster bootstrap)
| contrast | diff | discordant | McNemar p | cluster CI |
| --- | --- | --- | --- | --- |
| **H1 = A5 − A0** (primary) | **+0.100** | 6 / 0 | **0.031** | [0.042, 0.140] |
| L1 = A4 − A0 | +0.083 | 5 / 0 | 0.063 | [0.035, 0.106] |
| **L2 = A4 − A1** (content vs compute) | +0.017 | 3 / 2 | 1.0 | [0.0, 0.028] |
| **L3 = A4 − A2** (relevance vs shuffled) | 0.000 | 1 / 1 | 1.0 | [0.0, 0.0] |
| **H2 = A5 − A1** (vs compute) | +0.033 | 2 / 0 | 0.5 | [0.0, 0.061] |
| **H3 = A5 − A2** (vs shuffled) | +0.017 | 2 / 1 | 1.0 | [0.0, 0.06] |
| H4 = A5 − A4 (router vs reference) | +0.017 | 2 / 1 | 1.0 | [0.0, 0.06] |

## Verdict — NULL (fails the §10.7 method claim gate)
The primary endpoint A5 − A0 is significant (p = 0.031), and the utility-gated arm is the single highest and
**never causes a loss** (every A5-vs-X discordant count is 0 on the harm side). **But the gain does not survive the
controls:** A5 does not beat A1 (a neutral planning scaffold, p = 0.5) or A2 (shuffled memory, p = 1.0), and A4
(relevant agentic memory) equals A2 (shuffled) exactly. So the ~8%→~17% lift is attributable to **injected
compute / "think-first" tokens, not to memory content or the router's selection.** Per §10.7 — which requires the
gain to be *not explained by A1 compute* and *not reproduced by A2 shuffled* — this is **UTILITY_ROUTER_NULL**.

This is fully consistent with R14–R18 and the R17 D0 control: relevant memory content does not add reliable value
over matched compute for this reader/benchmark.

## What is nonetheless true (honest positives)
- The router is **safe**: zero memory-induced losses across all contrasts; nontrivial coverage (0.63 on dev).
- Agentic (A4/A5) ≥ static single-card (A3); the router arm is numerically best. These are within noise here.

## Honest limitation
Reduced power (n=60, ~8% base): only large effects are detectable; a null bounds the memory-content effect as
small, not exactly zero. The full-308 held-out design remains preregistered for a powered run. Parity caveat: A1's
neutral scaffold underran A4/A5 in length, yet A4/A5 still failed to beat it — strengthening, not weakening, the
null.
