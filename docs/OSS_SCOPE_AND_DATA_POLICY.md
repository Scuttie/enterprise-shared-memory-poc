# OSS Scope & Data Policy

## What Apache-2.0 covers
- **Only this project's own original source code** (`src/enterprise_memory/**`), plus its docs/examples/scripts as
  marked. See `LICENSE` and `NOTICE.md`.

## What it does NOT cover
- **Dependencies** retain their own licenses (`THIRD_PARTY_NOTICES.md`).
- **Benchmarks and datasets** (SWE-bench Verified, BigCodeBench, LiveCodeBench, DS-1000, etc.) retain their own
  copyright/licenses and are **not redistributed** here. This repo stores only **derived facts/metadata** (e.g.
  which APIs/operations a task touches) and **our own model-generated outputs** — never benchmark gold solutions
  or hidden tests.
- **Upstream research code with an unresolved license** (e.g. MemGovern) is **not vendored** into the product
  (enforced by `ci-literature-audit`); any exact-reproduction work runs in an isolated checkout, never packaged.

## Product wheel vs research code
The published wheel ships **only** `enterprise_memory`. Research code (`benchmarks*`, `experiments*`) and research
artifacts (`reports/`, `artifacts/`) remain in the repository for reproducibility but are **excluded from the
package** (`scripts/check_wheel_scope.py`, enforced in `ci-oss-release`).

## User / company data
No user or company data is included. All example configs use placeholders; all demo data is fictional. Real
credentials, endpoints, or private repository content must never be committed.
