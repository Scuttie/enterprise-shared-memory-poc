# R12 §2 — OpenAI Dependency + Model Audit → PRECONDITION BLOCK (endpoint A)

R12 requires a live OpenAI credential. **`OPENAI_API_KEY` is absent** from the repository secrets (only
`UPSTAGE_API_KEY` exists, verified via `gh secret list` on 2026-08-19). Per §0-A / §3, this is a **PRECONDITION
BLOCK**: no live OpenAI call is possible, and the milestone forbids using a fake server as a live OpenAI result.

## What is blocked (needs the key)
- Live model-list / model availability for `gpt-4o-mini-2024-07-18`, `gpt-5.6-luna`, `gpt-5.6-terra` (cannot
  confirm the GPT-5.6 candidates exist to this project — **returned model IDs = PENDING**).
- Provider live smoke (§5), the 60-task no-memory reader-band audit (§6), the R11 reader-swap diagnostic (§7),
  and the repository-agent band audit (§10). All paid/live phases are blocked.
- Wheel hashes / exact installed OpenAI SDK version at run time, Responses endpoint reachability, org/project
  config, per-response accounting from real usage — all deferred to the first live run.

## What was built now (credential-free R12-A0 — ready to activate)
- **`OpenAIResponsesProvider`** (`src/enterprise_memory/providers/openai_responses.py`) implementing the same
  production `CodingModelProvider` interface as `SolarProvider`, using the Responses API, with the frozen
  per-family rules: GPT-5.6 → `reasoning.effort` + **no temperature**; GPT-4o mini → `temperature=0` + **no
  reasoning**; one response, no repair, `max_output_tokens` = frozen budget. Bounded retries (429/5xx/transport;
  ordinary 4xx terminal); full `ModelCallRecord` accounting (input/cached-input/output/reasoning/total tokens,
  latency, retries, finish/redaction/final-status); the API key is never placed in exceptions/logs.
- **`tests/openai/test_openai_provider.py`** — 8 contract tests against a **fake** Responses server (no
  credentials): per-family schema (reasoning-not-temperature for 5.6; temperature-not-reasoning for 4o mini),
  429/5xx retry, no-retry-on-4xx, auth-error-never-leaks-key, empty→ParserError, unknown-family rejected. **All
  pass locally.**
- **`ci-openai-provider.yml`** (credential-free CI) + **`openai-integration.yml`** (manual, secret-gated; exits
  with an explicit PRECONDITION message when the key is absent).
- Locks: `configs/openai_reader_r12/model_lock.json` (requested IDs + forbidden substitutions + availability
  rule; returned IDs PENDING), `configs/openai_reader_r12/provider_lock.json`.

## Candidates (requested; not substituted)
`O0 gpt-4o-mini-2024-07-18` (control), `O1 gpt-5.6-luna` / medium, `O2 gpt-5.6-terra` / medium. Forbidden
substitutions: gpt-5-nano, any other alias, preview models, guessed replacements. If a candidate is unavailable,
mark only it; continue only if ≥1 GPT-5.6 candidate is available.

## Decision
**PRECONDITION BLOCK (endpoint A).** R12's live/paid science cannot proceed without `OPENAI_API_KEY`. The
credential-free instrument is complete and one secret away from running: provisioning `OPENAI_API_KEY` (optionally
`OPENAI_ORG_ID` / `OPENAI_PROJECT_ID`) unblocks R12-A1 (live smoke) → B0 (band audit) → C0 (R11 diagnostic) → D0
(repository audit) → conditional E. No fabricated results; the fake server is not presented as live OpenAI.

**Preserved:** R1–R11 + P6-A0/B0 frozen; `main` d56d178; PR#1 draft/OPEN; version 0.2.0.dev1; P6 paused (not
extended, not deleted); company model identity not guessed; **P6 execution not resumed**.
