# R8 — Closure: NO_COMPANY_READER / PRECONDITION_UNAVAILABLE

R8 (Company Reader Band Audit) is **closed**, not left AWAITING. Its mandated first step — obtain and freeze the
exact company harness/model manifest — cannot be satisfied in this environment, and the milestone forbids guessing
the company model identity.

## Findings (verified 2026-08-18, `reports/R8_COMPANY_READER_PRECONDITION.md`)
- **No company reader/harness exists** to call: no reachable company endpoint; `ci-company-harness` runs a *fake
  local harness server only, with no credentials and no company endpoint*.
- **No exact model identity, endpoint, build, tool schema, or credential exists.** There is no committed
  `CompanyManifest` (only `deploy/values-company.example.yaml`); the sole repository secret is `UPSTAGE_API_KEY`
  (Solar), not a company key. `company_harness.canary_status(...)` = `PENDING_CONFIGURATION`.
- **No company pilot was executed.** The frozen R7 40-task no-memory pilot was **not** run through any company
  path — there was nothing real to run it against.
- **The fake CI harness was not misrepresented as a company reader.** The adapter/transports are validated only
  against a fake server; no fabricated manifest or result was produced. The code explicitly does not assume the
  company model is "GLM-5.3".
- **Company replication remains UNAVAILABLE, not pending execution.** There is no execution queued or in flight;
  the blocker is the absence of company-supplied inputs, which are outside this environment.

## Resolution
The public-benchmark efficacy track **resumes under R9** (primary: official DevEval; predeclared fallback:
official ExecRepoBench, only on a DevEval technical/instrument stop). R8's service-side plumbing
(`ExternalHarnessExecutionBackend`, `CompanyManifest`, three transports, forbidden-field governance) stays intact
and ready to run the identical frozen R7 pilot **if and when** a real company manifest + endpoint + secret are
ever supplied — that is a future activation, not an open R8.

## Preserved
R1–R7 frozen; `main` `d56d178`; `v0.1.0-poc`; PR#1 OPEN/DRAFT; version `0.2.0.dev1`; **P6 not started.**
