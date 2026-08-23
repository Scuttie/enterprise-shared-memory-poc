# OSS v0.3 — CI classification, required release checks, GitHub settings

## CI workflow classification (§8)

Every workflow on this branch classified as **A** (OSS/product regression), **B** (research reproduction only),
**C** (needs external secret / paid API / large image / service, manual or gated), or **D** (real regression /
broken — must fix before release). No failures are hidden and no `continue-on-error` is used to fake green.

| Class | Meaning | Workflows |
| --- | --- | --- |
| **A** | OSS / company-product acceptance | `ci-oss-release`, `ci-company-demo`, `ci-company-harness`, `ci-company-package`, `ci-experience-schema`, `ci-utility-router`, `ci-agentic-search`, `ci-outcome-governance`, `ci-mcp`, `ci-docs`, `ci` |
| **A (service, needs container service)** | product regression requiring a DB/index service in CI | `ci-postgres`, `ci-qdrant`, `ci-qdrant-outage`, `ci-artifacts`, `ci-oidc`, `ci-e2e` |
| **B** | research reproduction only (frozen) | `ci-r1-…`, `ci-r3-…`, `ci-r5-…`, `ci-r6-…`, `ci-r7-…`, `ci-r11-…`, `ci-r12-…`, `ci-r13-…`, `ci-r14-…`, `ci-realbench-*`, `ci-bigcode-*`, `ci-p5-2-*`, `ci-literature-audit`, `ci-experiment-*` |
| **C** | needs external secret / paid API / fake-provider server (gated/manual) | `ci-solar`, `solar-integration`, `ci-openai-provider`, `openai-integration`, `ci-r5-solar-probe`, `ci-r12-*`, `resolve-digest` |
| **D** | broken / real regression | **none found** |

Scope-limiting rule applied: B and C workflows are constrained by `branches` / `paths` / `workflow_dispatch`
conditions so the OSS release does not turn them red. They are **not** part of the release required-checks set.

## Release required checks (`ci-oss-release`)

The release PR's required acceptance is `ci-oss-release`, which runs (all real, none `continue-on-error`):

1. Fresh clone × Python **3.10 / 3.11 / 3.12**
2. `make company-acceptance` (offline, no credentials)
3. Build **wheel + sdist**
4. **Wheel scope** — `enterprise_memory` only + LICENSE/NOTICE/THIRD_PARTY, no research code (`check_wheel_scope.py`)
5. **Clean-install the wheel** in an isolated venv and import `enterprise_memory` + MCP server
6. **LICENSE/NOTICE present** in sdist
7. **MCP smoke** (`make mcp-check`) and **HTTP smoke** (`examples/company_harness/http_adapter.py`)
8. Offline demo → `DEMO_PASS`
9. Docs consistency
10. **Secret/path scan, docs links, SBOM + dependency license report, source-tree-clean** (`oss_release_acceptance.py`)

Required status block emitted on success:

```text
OSS release acceptance: PASS
Research workflows: separate scope
Company staging: PENDING
Production: NOT CLAIMED
```

> Note: `ci-oss-release` runs on the canonical release trigger — `pull_request: [main]` + `push: [main]` +
> `workflow_dispatch`. On PR #5 the `pull_request` event runs it from the PR head (`workflow_dispatch` registers
> once the file lands on the default branch after merge). The README does **not** claim "all CI green".

## Migration-head guard (shared, dynamic)
`scripts/check_migration_head.py` replaced every hard-coded `alembic current | grep -E "0013.*(head)"` guard: it
compares the real Alembic **script head** to the **DB applied head** with no revision baked in, so it cannot go
stale on the next migration. **17** call-sites across all migration-aware workflows; **zero** `0013.*(head)` guards
remain. Enforced by `tests/unit/test_release_hygiene.py` (runs inside `ci`).

## Three real changes this finalization made (not "triggers only")
1. **Workflow trigger cleanup** (`on:` only) — 20 research/paid/service workflows moved off auto-PR; 13
   release-required kept auto; `ci-oss-release` canonicalized.
2. **Detector exact-file exemption** — `scripts/oss_release_acceptance.py` added to `release_check.py`'s `EXEMPT`
   (a detector, like `release_check.py`/`security_scan.py`); no scan scope narrowed, no pattern weakened.
3. **Non-semantic path-portability amendment** to frozen R14/R15/R18/R19 — scratch root now
   `os.environ.get("ESM_SCRATCH")`-driven; research condition/arms/results unchanged.
Plus the migration-head guard swap above (a CI-infra correctness change, called out explicitly). No frozen R1–R21
condition or result was altered; no protected branch or past commit was touched; no workflow deleted.

## GitHub settings applied (§9)

| Setting | Status |
| --- | --- |
| Repository description → current product description | **applied** |
| Topics (`apache-2-0`, `memory`, `mcp`, `governance`, `vector-search`, `rag`, …) | **applied** |
| Issues enabled | **applied** |
| Discussions enabled | **applied** |
| Dependabot vulnerability alerts | **applied** |
| Dependabot automated security fixes | **applied** |
| Secret scanning + push protection | **applied** |
| Private vulnerability reporting | **applied** |
| Dependabot version updates (`.github/dependabot.yml`) | **committed** (activates on merge to default branch) |
| CodeQL / default code scanning (`.github/workflows/codeql.yml`) | **committed** |
| Issue templates + PR template + `release.yml` + CODEOWNERS | **committed** |
| License recognized by GitHub (`licenseInfo`) | **pending merge** — GitHub only detects `LICENSE` once it lands on the default branch (`main`); appears after PR #5 merges. Not a blocker. |
| Branch protection / required-checks enforcement | **needs admin** — set the required check to `ci-oss-release` after the first green run; not changed here (avoids touching `main`). |

Nothing was faked: settings that require admin/plan privileges or a merge to `main` are reported as pending, not
marked done.
