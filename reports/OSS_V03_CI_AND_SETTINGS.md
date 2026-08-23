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

> Note: because the default branch (`main`) is off-limits before merge, a brand-new `workflow_dispatch` workflow
> cannot register there. `ci-oss-release` and `codeql` are therefore driven by `push` on the release branch and by
> `pull_request`, both of which run from the PR head. The README does **not** claim "all CI green".

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
