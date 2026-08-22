# Memory Policy

## Modes (`MEMORY_POLICY_MODE`)
| Mode | Search/Browse | Router | Injects |
| --- | --- | --- | --- |
| `off` | no | no | nothing |
| `static_relevant` | one preselected card | no | that card |
| `agentic_reference` | yes | no (literature-style selection) | approved candidates |
| `utility_gated` | yes | **RuleRouterV1** | only `USE` candidates |
| `shadow` | yes | yes (persisted) | **nothing** |

The server enforces the mode; a client cannot select it or the experiment arm.

## Router reason codes (frozen — [`../artifacts/p6/router_policy.json`](../artifacts/p6/router_policy.json))
**USE:** `USE_DIRECT_SYMBOL_MATCH`, `USE_DIRECT_API_MATCH`, `USE_FAILURE_SIGNATURE_MATCH`,
`USE_VERSION_COMPATIBLE_WORKAROUND`, `USE_NEW_VERIFIED_ACTION`.
**ABSTAIN:** `ABSTAIN_REDUNDANT`, `ABSTAIN_THEME_ONLY`, `ABSTAIN_WRONG_STAGE`, `ABSTAIN_VERSION_MISMATCH`,
`ABSTAIN_NO_ACTIONABLE_DELTA`, `ABSTAIN_LOW_MARGIN`, `ABSTAIN_HIGH_RISK`, `ABSTAIN_ALREADY_TRIED`, `ABSTAIN_SCOPE`,
`ABSTAIN_UNVERIFIED`.

The router uses **public / current-trajectory features only**. Gold patches, hidden tests, final verdicts, the
experiment arm, and future outcomes are rejected fail-closed (`RouterLeakageError`).

## Promotion / quarantine (frozen — [`../artifacts/p6/governance_thresholds.json`](../artifacts/p6/governance_thresholds.json))
`candidate` → (source verified) → `probation` → (≥2 `MEMORY_GAIN`, 0 losses, **manual review**) → `promoted`;
≥2 `MEMORY_LOSS` → `quarantined`; version invalidation → `deprecated`. No force-promote. Outcome stats affect
future targets only (never a card's own target).

## Shadow rollout
Start in `shadow`: decisions and outcome credits are recorded with zero injection risk. Review the audit, then
switch to `utility_gated` with reviewed, promoted cards. Human review always overrides automated promotion.
