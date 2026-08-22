# R20 Interaction Analysis (primary)

Task-level binary DID with repository-cluster bootstrap.

I = (F11 - F10) - (F01 - F00) = **-0.0161**  (n=248)
- cluster 95% CI: [-0.0758, 0.0131]
- cluster 90% CI: [-0.06, 0.0069]

Verdict: **ROUTER_X_RELEVANCE_INTERACTION = NULL / INCONCLUSIVE** — the CI includes 0. Practical equivalence at
+-5pp is **NOT ESTABLISHED** (the 90% CI lower bound -0.06 exceeds -0.05), i.e. **POWER_LIMITED**, exactly as the
pre-run power audit predicted (interaction min detectable ~0.045). No claim of synergy; no claim of exact zero.
The router does not add *more* on relevant memory than on shuffled — largely because it correctly injects nothing
on shuffled (F01 == no-memory), so F01-F00 is the router removing bad memory, not a content effect.
