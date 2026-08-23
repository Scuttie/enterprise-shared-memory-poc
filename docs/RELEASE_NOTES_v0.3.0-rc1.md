# Enterprise Shared Memory v0.3.0-rc1 (DRAFT — not tagged)

> Company-handoff-ready OSS release candidate.
> Not company-staging-certified, not production-certified,
> and no general coding-performance-lift claim is made.

**Status: PREPARED, not applied.** The PR keeps version `0.3.0.dev1`. On explicit maintainer approval to merge,
a separate small commit bumps the version to `0.3.0rc1` and the tag `v0.3.0-rc1` is proposed. No tag or release is
created before that approval.

## Highlights
- Apache-2.0 licensed public OSS release (`LICENSE`, `NOTICE.md`, `THIRD_PARTY_NOTICES.md`; SPDX in `pyproject`).
- Product wheel ships **only** the `enterprise_memory` package plus license files — research code, benchmarks,
  artifacts, and reports stay in the repository for reproducibility but are excluded from the wheel
  (`scripts/check_wheel_scope.py` enforces this in CI).
- One-command company acceptance: `make company-acceptance` (offline, no credentials) writes
  `reports/company_acceptance_result.json`.
- Korean Quick Start (`docs/COMPANY_QUICKSTART_KO.md`) and full onboarding guide
  (`docs/COMPANY_IMPLEMENTATION_GUIDE_KO.md`).
- OSS community docs: `SECURITY.md`, `CONTRIBUTING.md` (DCO), `CODE_OF_CONDUCT.md`, `CITATION.cff`,
  issue/PR templates, release-notes config.
- `ci-oss-release` acceptance workflow: fresh clone × Python 3.10/3.11/3.12, wheel/sdist build + clean-install,
  license inclusion, secret/path scan, docs links, MCP + HTTP smoke, SBOM/license report, source-tree-clean.

## Explicitly NOT claimed
- Shared memory does **not** reliably improve coding-task success in our controlled study (REALBENCH R14–R18 null).
- Not production-certified and not company-staging-certified.
- Benchmark/research results are a separate claim axis and must not be presented as product performance.

## Planned release artifacts (produced at tag time)
wheel · sdist · OCI image · SBOM · dependency license report · OpenAPI snapshot · MCP schema bundle ·
Korean Quick Start (PDF/Word) · checksums · release notes.

## Company inputs still required before staging
model/harness manifest · staging environment + sign-off · OIDC issuer · deployment targets · repository access policy.
