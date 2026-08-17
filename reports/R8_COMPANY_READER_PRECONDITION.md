# R8 §0 — Company Reader Band Audit: PRECONDITION BLOCK (company manifest PENDING_CONFIGURATION)

R8's mandated first step is: **"First obtain and freeze the exact company harness/model manifest."** Everything
downstream (rerun the frozen R7 40-task NO_MEMORY pilot through the company harness → gate → PASS/FAIL) is gated
on that manifest existing. It does not exist in this environment, and the milestone forbids guessing the company
model identity. R8 therefore halts at the precondition — this is **not** the pilot FAIL branch (which would
require actually running the pilot and observing a resolved rate outside [4,28]).

## Audit — verified 2026-08-18 (no fabrication)
| check | result |
|---|---|
| Committed real `CompanyManifest` (JSON/YAML, non-example) | **none found** (only `deploy/values-company.example.yaml`) |
| Company API secret in repo secrets | **absent** — only `UPSTAGE_API_KEY` (Solar) exists |
| Company endpoint | **none** — `ci-company-harness` runs a *"fake local harness server only; no credentials, no company endpoint"* |
| `company_harness.canary_status(...)` | **PENDING_CONFIGURATION** (requires manifest + approved endpoint + a set secret env var; none present) |
| Company model identity | **not guessed** — `company_harness.py` explicitly does NOT assume "GLM-5.3"; identity must come from the manifest |

The service-side plumbing is fully built and CI-validated against a fake server: `CompanyManifest` (validated),
three pluggable transports (`anthropic`/`openai`/`jsonrpc`), `CompanyHarnessClient`, and
`ExternalHarnessExecutionBackend`, with forbidden-field governance (credentials / hidden tests / private traces /
final verdict never reach the harness). What is missing is exclusively the **company-supplied inputs**.

## What the company must supply to unblock R8 (freeze target)
Fill `configs/company_reader_r8/company_manifest.REQUIRED.json` (fields from `CompanyManifest`):
`harness_name, harness_version, model_id, model_revision, serving_protocol (anthropic|openai|jsonrpc), endpoint,
context_window, max_output_tokens, tool_schema_hash, repository_mount_mode, sandbox_test_ownership="service",
streaming, timeout_seconds, build_id` — **plus** an endpoint reachable from CI and a **secret env var name** whose
value is set as a GitHub secret (only `UPSTAGE_API_KEY` exists today). No value here is inferred or defaulted to a
guessed identity.

## Plan once the manifest is frozen (unchanged from the R8 spec)
1. Freeze the exact manifest (hash it into `configs/company_reader_r8/`).
2. Rerun **only** the frozen R7 40-task NO_MEMORY pilot (`configs/swe_polybench_r7/g1_targets.json`) through:
   HTTP → durable job → `ExternalHarnessExecutionBackend` → company harness/local model → official SWE-PolyBench
   image/evaluator. No task reselection; no Solar retune; the Solar repository-agent is not touched.
3. Gate: graded ≥ 38/40, evaluator/env failure ≤ 2/40, leakage = 0, **resolved ∈ [4, 28]**.
4. **PASS** → new R8 preregistration; exclude the 40 pilot tasks from main; run M0–M4 on untouched tasks.
   **FAIL** → close the static positive-efficacy benchmark track; do **not** switch benchmark; return an honest
   reader–instrument stop.

## Constraints honored (this step)
No other public benchmark searched; Solar repository-agent not retuned; no R7 memory arm run; company model
identity not guessed; **P6 not started**. Preserved: R1–R7 frozen; `main` `d56d178`; PR#1 draft/OPEN; version
`0.2.0.dev1`; tag `v0.1.0-poc`.

## Status
**R8 = AWAITING_COMPANY_MANIFEST.** The single blocker is the company-supplied manifest + endpoint + secret. As
soon as those are provided, the pilot rerun and gate proceed exactly as specified above. Nothing is fabricated to
manufacture a result.
