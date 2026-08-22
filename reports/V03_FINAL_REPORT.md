# P6 / R19 — Utility-Aware Shared Memory + Company Handoff — Final Report

Branch `codex/utility-router-v0.3` (worktree), PR **#2** DRAFT → base `codex/production-service-v0.2`.
`main`, `v0.1.0-poc`, PR **#1**, and frozen R1–R18 are **untouched** (see `V03_FROZEN_R_HASH_AUDIT.json`,
`all_frozen_unchanged: true`). No squash / force-push / merge / tag / release.

## Endpoint status (§0)
- **Endpoint A (external reproduction):** MemGovern exact reproduction **BLOCKED** by unresolved license — native
  clean-room build continued (mandated).
- **Endpoint E (company handoff):** software complete and gated — fresh-clone install + offline demo `DEMO_PASS`
  pass in CI (`ci-company-package`, `ci-company-demo`). Label: **COMPANY-HANDOFF-READY — NOT
  COMPANY-STAGING-CERTIFIED**, production **NOT CLAIMED**.
- **Endpoints B/C/D (literature reproduction / causal attribution / router held-out):** harness + preregistration
  scaffolding in place; the live A0–A5 run is preregistered to gpt-4o-mini and reported as
  `utility_router_result` in `docs/STATUS.yaml` (currently **NOT_RUN** — see below).

## Commits (no squash)
H0 git-safety + truth audit + STATUS.yaml + ci-docs · L0 literature/license audit + ci-literature-audit ·
M0 experience schema (0014, 13 tables, RLS, immutable, integrity FKs) + compiler + ci-experience-schema ·
U0 RuleRouterV1 + frozen policy + ci-utility-router · S0 search/browse + gated injection + ci-agentic-search ·
G0 outcome credit + governance + ci-outcome-governance · D0(demo) offline demo + ci-company-demo ·
I0 MCP + adapters + examples + ci-mcp · D0(docs) README + company docs · R0 Makefile + examples + handoff manifest.

## What a reviewer can verify (§23)
Relevant memory selected · irrelevant abstained · harmful quarantined · private never crosses users · every
decision audited · every injected view maps to a canonical version · works on a fake/local backend · company
harness integrates via HTTP or MCP. Proven by 60 passing V03 tests + `DEMO_PASS: true`.

## Router / research result
`utility_router_result: NOT_RUN` until the preregistered A0–A5 held-out run executes (reader **gpt-4o-mini**, fixed
across all arms per §10.4). The result will be reported as one of
`UTILITY_ROUTER_POSITIVE | NULL | NEGATIVE | NOT_RUN` with no ambiguous "promising" verdict. Given R14–R18, a null
is a valid final outcome; the company system stands as an auditable governance/attribution platform regardless.

## Remaining company inputs / production blockers
Model/harness manifest · OIDC issuer/JWKS · PostgreSQL+Qdrant targets · repository access policy · company staging
env + written sign-off. MemGovern license remains a vendoring blocker (clean-room unaffected).

## Recommendation
Do **not** merge PR #2 or cut a release tag without explicit approval. Recommended next: run the preregistered
A0–A5 study on gpt-4o-mini (cheap), record `utility_router_result`, then a company staging pilot in `shadow` mode.
