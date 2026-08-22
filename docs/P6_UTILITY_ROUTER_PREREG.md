# P6 / R19 — Utility-Router Held-Out Main — Preregistration (FROZEN)

Frozen before any live model call (§20). Reader **gpt-4o-mini-2024-07-18**, fixed across all arms (amended from
the GPT-4o R16 baseline at the user's direction; no per-arm swap, no reader selection). Benchmark SWE-bench
Verified, official grader, ITT.

## Task split (frozen — `artifacts/p6/task_manifest.json`, hash `bf4effca…`)
- **Development-observed (181):** all R14–R18 tasks — router debugging / thresholds only; no new confirmatory claim.
- **Held-out (319; memory-eligible 308):** every remaining untouched official task with ≥1 earlier same-repo
  source. No difficulty filter, no outcome-based exclusion, repository-clustered analysis. No convenient-N
  cherry-pick; if precision is limited it is stated, not narrowed.

## Arms (identical model / harness / tool budget; §10.3)
- **A0** no memory · **A1** compute-matched planning (no historical content) · **A2** shuffled agentic memory
  (matched candidates/browse/tokens/timing) · **A3** static relevant (one card, no progressive search) ·
  **A4** agentic reference (search→browse, no router) · **A5** utility-gated (search→browse + RuleRouterV1).
- Parity hard rules (§22): A1 compute == A4; A2 browse/tokens == A4; no arm gets a stronger model or larger
  context; client cannot select the arm.

## Endpoints (fixed sequence; §10.5–10.6)
`L1=A4−A0` (does agentic memory help at all) · `L2=A4−A1` (content beyond compute) · `L3=A4−A2` (relevance
beyond shuffled) · **`H1=A5−A0` (primary product endpoint)** · `H4=A5−A4` (router vs reference). Secondary
`H2=A5−A1`, `H3=A5−A2`. Exact McNemar + repository-cluster bootstrap 95% CI; Holm for secondary superiority.
No optional stopping; no post-result N expansion.

## Router / governance (frozen)
`artifacts/p6/router_policy.json` (`4daff133…`), `governance_thresholds.json` (`f4370407…`). Dev coverage floor
0.15 (a router that abstains from ~everything fails the nontrivial-use requirement, §8.4). Router uses public /
current-trajectory features only; gold/tests/verdict/arm/future are rejected fail-closed.

## Method claim gate (§10.7)
Claim the method works only if **A5 > A0** on held-out success, coverage nontrivial, target/test leakage = 0,
cross-user private leakage = 0, negative transfer not increased, gains not explained by A1 compute nor reproduced
by A2 shuffled. Otherwise report the null/negative honestly; keep the system as an auditable governance platform.

## Result label
One of `UTILITY_ROUTER_POSITIVE | UTILITY_ROUTER_NULL | UTILITY_ROUTER_NEGATIVE | UTILITY_ROUTER_NOT_RUN`
(`utility_router_result` in `STATUS.yaml`). No ambiguous "promising" verdict. A redesign requires a new experiment ID.
