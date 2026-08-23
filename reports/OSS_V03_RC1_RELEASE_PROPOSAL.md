# OSS v0.3.0-rc1 — merge record + release proposal

**Status: merged to `main` and RC-versioned. Tag and GitHub release are PROPOSED ONLY — not created.**
They will be created only after explicit maintainer approval.

## Merge record
- PR **#5** merged into `main` as a **merge commit** (no squash, no force):
  **`71e264d0a6fa72ef7e3b7d9b93d0020ad9a7029a`** — parents `d56d17835` (old main) + `b291237bd` (PR #5 head).
- RC version commit on `main`: **`f5abab2986f0afb611bab33451839053aaee674d`** — `0.3.0.dev1` → `0.3.0rc1`
  (metadata/docs only; no `enterprise_memory` product or research logic changed).
- PR **#2** commented (superseded by #5) and **closed without merging**. PR **#3** and **#4** left OPEN, untouched.

## Pre-merge CodeQL resolution (no unexplained red)
- HIGH `py/clear-text-logging-sensitive-data` (release tooling `scripts/oss_release_acceptance.py`): **fixed** in
  `b291237` (reports `file:line + rule label + (match redacted)`, never any bytes of a match), residual taint
  dismissed as false positive.
- MEDIUM `py/stack-trace-exposure` (`src/enterprise_memory/service/app.py`): **dismissed as false positive** —
  the flow returns `str(e)` of `OIDCError`/`ScopeError`/`Unauthenticated`, which are raised only with hardcoded
  reason codes (`missing_bearer`, `missing_scope`, `jwks_fetch_failed`, …); no traceback/sensitive data reaches
  the client. Product logic unchanged per the release constraint.
- Result: **0 open code-scanning alerts**, CodeQL check green.

## Final CI on `main`
- `ci-oss-release` @ `f5abab2`: **4/4 green** (`acceptance (3.10/3.11/3.12)` + `release-acceptance`).
- `ci` @ `f5abab2`: **green**. All 13 release-required checks green on `main`.
- Fresh-clone `make bootstrap` + `make company-acceptance`: **COMPANY_ACCEPTANCE_PASS: true**, **DEMO_PASS: true**,
  handoff manifest current, wheel-scope PASS, migration head checker PASS.

## RC artifacts (`dist/release-rc1/`, SHA256)
```
21be24baf89d77fa6e2b409b8af8f913508342aa4a2d8897eea67efa6f8a8d24  enterprise_shared_memory_poc-0.3.0rc1-py3-none-any.whl
32369545eb46a78bd04deb3ae46550da099e0c2bb64459d99472d9eb3af46c48  enterprise_shared_memory_poc-0.3.0rc1.tar.gz
607706c5f93d8a83582f5ecbdbe7593e5e27dfe47e6e2a3bdf079ea44f370db1  openapi_v1.json
4f00b31c626bcace65935bc16717e00511afb719a30ad42354dab86d7a21eee6  mcp_tool_schema.json
3edc3cd4656dca5be8c413aaf2f9cc77b5d8e4bd8e7c86ad6c461f60fdd8948f  sbom.json
85609aaece09e232a81acda956899928cc40f9682ba3e7120779a391178be1c5  dependency_licenses.json
363381dadacb93f2ee32623d12c6068d5ce228fc2f36a2d5bfda868e0a629419  COMPANY_QUICKSTART_KO.md
0a3a9fc38682e17650c91ac294a4cccbfd031762f4934909bd2ef8ee41d09d0c  RELEASE_NOTES_v0.3.0-rc1.md
e36eb4c9ce9dd01de685927ea2fe7a6ab62da028bfce1d9d4b31b0e2f8f808e8  LICENSE
26762942b9f2c2874c80ef9deeb2f8211c01f182a1ae6e82dc23d8e15d03e458  NOTICE.md
a803c07f82d2da7ca5b50903953541cf83e288f600f0c91f8ade0c0d7db5ad3f  THIRD_PARTY_NOTICES.md
```
A `SHA256SUMS` file over all of the above is included in the bundle.

**OCI image — NOT produced (gap):** no `Dockerfile` is committed (the compose file uses `build: ..` against a
missing Dockerfile). The container image cannot be built from the repo as-is. Proposed reference for release time:
`ghcr.io/scuttie/enterprise-shared-memory-poc:0.3.0-rc1` — **requires adding a Dockerfile first** (follow-up).

## After-merge repository state (done)
- `licenseInfo` = **Apache-2.0** (detected on `main`).
- Default branch `main` README = the **v0.3** README (version `0.3.0rc1`).
- Branch protection on `main`: **strict** status checks, **16 required contexts**, force-pushes & deletions off.
- Research/paid/service workflows remain **manual** (`workflow_dispatch`); 13 release-required checks auto on PRs.
- Minor follow-up: `codeql.yml` push trigger still names the feature branch — update to `[main]` so `main` pushes
  are scanned (CodeQL already runs on PRs + weekly schedule; 0 open alerts).

## Tag proposal — NOT created (awaiting approval)
- Annotated tag **`v0.3.0-rc1`** on `main` @ `f5abab2`.
- Command to run **only after approval**:
  ```bash
  git tag -a v0.3.0-rc1 f5abab2 -m "Enterprise Shared Memory v0.3.0-rc1"
  git push origin v0.3.0-rc1
  ```

## Release proposal — NOT created (awaiting approval)
- **Title:** `Enterprise Shared Memory v0.3.0-rc1`
- **Opening:**
  > Company-handoff-ready OSS release candidate.
  > Not company-staging-certified, not production-certified,
  > and no general coding-performance-lift claim is made.
- Attach the `dist/release-rc1/` artifacts + `SHA256SUMS`. Mark as a **pre-release**.
- Command to run **only after approval** (creates tag + release + uploads assets):
  ```bash
  gh release create v0.3.0-rc1 --target f5abab2 --prerelease \
    --title "Enterprise Shared Memory v0.3.0-rc1" \
    --notes-file docs/RELEASE_NOTES_v0.3.0-rc1.md \
    dist/release-rc1/*
  ```

## Company inputs still required before staging
model/harness manifest · staging environment + sign-off · OIDC issuer · deployment targets · repository access policy.
