# BigCode-R2 — Efficiency & Abstention (§10 M5, cost)

Pass@1 per 1k output tokens and injection rate per arm (from the frozen main; production service path, temp 0).

| Arm | Pass@1 | mean out-tok | **pass / 1k-tok** | injection rate |
|---|---|---|---|---|
| M0 NO_MEMORY | 0.394 | 469 | 0.839 | 0.00 |
| M1 PRIVATE | 0.417 | 455 | **0.916** | 1.00 |
| M2 RELEVANT | 0.390 | 466 | 0.836 | 0.41 |
| M3 SHUFFLED | 0.411 | 432 | **0.950** | 0.03 |
| M4 DEPLOYABLE | 0.394 | 476 | 0.827 | 0.996 |
| M5 ALWAYS_TOP1 | 0.402 | 470 | 0.856 | 1.00 |
| M7 GOVERNED | 0.396 | 469 | 0.844 | 0.49 |

## Findings
1. **Relevant-memory injection buys no efficiency.** M2 (0.836 pass/1k-tok) is essentially identical to M0
   (0.839) despite injecting a retrieved lesson 41% of the time — the extra prompt tokens and retrieval cost
   return nothing.
2. **The abstaining/rarely-injecting arms are the most token-efficient**, purely because they inject little and
   still match baseline accuracy: M3 (injects 3%) 0.950 and M1 0.916 top the table. This is *not* evidence that
   their memory helps — M3 is the irrelevant control — it reflects that not-injecting costs nothing and accuracy
   is flat regardless.
3. **Abstention (M5 threshold vs M4 always-retrieve):** M5 − M4 = +0.008 Pass@1 (Holm p=0.61, n.s.). The
   abstention gate neither helps nor hurts accuracy; its only effect is marginal token savings when it declines
   to inject. There is no accuracy/cost frontier to exploit because the accuracy axis is flat.
4. **Deployable arm is the *least* efficient** (M4 0.827): it injects almost always (99.6%) for zero accuracy
   gain over M0, so it strictly adds cost. In production terms, on this benchmark the memory feature would raise
   token spend without moving Pass@1.

**Bottom line:** the efficiency picture reinforces the null — memory injection adds prompt/retrieval cost and
returns no accuracy, so the cost-effective operating point on BigCodeBench is *no injection* (M0), with
abstention (M5) as a harmless equivalent.
