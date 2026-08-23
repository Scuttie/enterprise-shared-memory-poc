# OSS v0.3 — Final release readiness

- Repository: `Scuttie/enterprise-shared-memory-poc` (PUBLIC, default branch `main`)
- PR: **#5** — OPEN / **DRAFT** / base `main`
- Verified head: **`cd666b1`**
- Version: `0.3.0.dev1` (RC bump to `0.3.0rc1` prepared, applied only on merge approval)

## Verdict
**OSS_RELEASE_PR_READY_FOR_APPROVAL** — every gate below is green; no merge and no tag were performed.

## Gate results (all on head `cd666b1`)

| Gate | Requirement | Result |
| --- | --- | --- |
| `ci-oss-release` jobs | 4/4 | **4/4 green** — `acceptance (3.10/3.11/3.12)` + `release-acceptance` |
| Automatic release-required checks | 13/13 | **13/13 green** |
| CodeQL / security | green | **green** (CodeQL + secret scanning + push protection enabled) |
| Manual service-integration workflows | 6/6 | **6/6 green** (dispatched on `cd666b1`) |
| Unexplained red checks | 0 | **0** |
| Fresh clone `make bootstrap` | ok | **ok** (editable install of `.[dev]`) |
| Fresh clone `make company-acceptance` | pass | **COMPANY_ACCEPTANCE_PASS: true** |
| Offline demo | pass | **DEMO_PASS: true** |
| Draft state | preserved | **DRAFT preserved; no merge/tag** |

### 13 automatic release-required checks (all green)
`ci` · `ci-oss-release` · `codeql` · `ci-docs` · `ci-company-demo` · `ci-company-harness` · `ci-company-package` ·
`ci-experience-schema` · `ci-mcp` · `ci-outcome-governance` · `ci-agentic-search` · `ci-utility-router` · `ci-oidc`.

### 6 manual service-integration workflows (dispatched on `cd666b1`, all green)
`ci-postgres` (run 32647474557) · `ci-qdrant` (32647484274) · `ci-qdrant-outage` (32647486492) ·
`ci-mem0` (32647488706) · `ci-artifacts` (32647490890) · `ci-e2e` (32647492884).
Each exercised the shared migration-head guard (`scripts/check_migration_head.py`) against a live DB and passed —
confirming the DB is at the real Alembic head `0014` with no hard-coded revision.

## Fresh-clone acceptance evidence
- Cloned `codex/oss-v0.3-finalize` @ `cd666b1` into a clean directory; `python -m pip install -e ".[dev]"` ok.
- `make company-acceptance` → `overall_pass: true`, `test_count: 60`, handoff manifest **current**, docs-check PASS,
  secret/path scan **CLEAN**.
- Offline demo → `DEMO_PASS: true`.
- Fresh-clone build hashes: wheel `sha256 e7509a0c…f3d0`, sdist `sha256 14ce0cb1…aa194`
  (dev build; recomputed at RC tag time).

## The three real changes (accurately stated)
1. **Workflow trigger cleanup** (`on:` only) — 20 research/paid/service workflows off auto-PR; 13 release-required
   kept auto; `ci-oss-release` canonicalized (`pull_request:[main]` + `push:[main]` + `workflow_dispatch`).
2. **Detector exact-file exemption** — `scripts/oss_release_acceptance.py` added to `release_check.py` `EXEMPT`
   (a detector, like `release_check.py`/`security_scan.py`); scan scope unchanged, no pattern weakened.
3. **Non-semantic path-portability amendment** to frozen R14/R15/R18/R19 — scratch root is now
   `os.environ.get("ESM_SCRATCH")`-driven; research condition/arms/seeds/grader/results unchanged.

Plus a CI-infra correctness swap: the stale `0013.*(head)` guard was replaced by the shared dynamic
`scripts/check_migration_head.py` at **17 call-sites**, leaving **zero** hard-coded head guards. All of the above is
locked in CI by `tests/unit/test_release_hygiene.py`.

**Frozen invariants:** no frozen R1–R21 preregistration/arm/seed/grader/result changed; no protected branch
(`main`, `v0.1.0-poc`, PR #1/#3/#4) or past commit touched; no workflow deleted.

## Remaining, non-blocking
- `licenseInfo` shows once `LICENSE` lands on `main` (after merge). Not a blocker.
- Branch-protection required-check (`ci-oss-release`) is an admin setting to apply after merge.
- RC: keep `0.3.0.dev1` in the PR; on merge approval, a separate small commit bumps to `0.3.0rc1` and proposes tag
  `v0.3.0-rc1` (no tag created now).

## Company inputs still required before staging
model/harness manifest · staging environment + sign-off · OIDC issuer · deployment targets · repository access policy.
