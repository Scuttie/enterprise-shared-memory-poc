# REALBENCH-R12 (OpenAI reader-swap) — Final Return

**Achieved endpoint: A — PRECONDITION BLOCK.** `OPENAI_API_KEY` is absent, so no live OpenAI call is possible and
the fake server must not be presented as a live result. The credential-free R12-A0 instrument is complete and
one-secret-ready; all live/paid phases (A1 smoke, B0 band, C0 R11 diagnostic, D0 repository, E main) are blocked
pending the key. Nothing fabricated; R1–R11 + P6 frozen; P6 not resumed; company model not guessed.

1. **New commits:** `bfaec76` (R12-A0 + block) + this freeze commit. Branch `codex/production-service-v0.2`.
2. **Final head/PR:** HEAD as pushed; PR **#1 OPEN/DRAFT/unmerged**, base `main`; `main` `d56d178`; tag
   `v0.1.0-poc`; version `0.2.0.dev1`.
3. **Preserved hashes:** R1–R11 artifacts/reports + P6-A0/B0 unchanged; R11 partition sha256 `352d156f`, memory
   maps + `main_result.json` untouched; P6 gradient sha256 `108dcc6c`, governance attestation intact.
4. **OpenAI SDK version + wheel hashes:** PENDING — pinned at the first live CI run (the credential-free provider
   uses the Responses API contract via injectable HTTP client; `provider_lock.json` records the reference).
5. **Requested/returned model IDs:** requested `gpt-4o-mini-2024-07-18` (O0), `gpt-5.6-luna` (O1),
   `gpt-5.6-terra` (O2); **returned IDs PENDING** (needs live model-list). No substitution; gpt-5-nano/aliases/
   preview/guessed-replacements forbidden (`model_lock.json`).
6. **Provider smoke:** not run (needs key). Instead: **8 fake-server contract tests PASS** locally and in
   **ci-openai-provider (GREEN)** — per-family schema (5.6 reasoning/no-temp; 4o-mini temp/no-reasoning),
   429/5xx retry, no-retry-4xx, key-never-leaks, empty→ParserError, unknown-family rejected.
7. **Band-audit task IDs/hash:** frozen 61 tasks, sha256 `8d4ff626…` (`artifacts/openai_reader_r12/band_tasks.json`),
   hash-stratified over (difficulty × platform) of the 182 R11 targets, no-memory only.
8–18. **No-memory Pass@1 by reader / exec rates / cost / selected reader / R11 M0–M3 / M1−M2 / M1−M0 / M3−M1 /
   Solar-vs-OpenAI DiD / transfer / token-latency-cost / diagnostic claim boundary:** **NOT RUN** (blocked). The
   claim boundary is preregistered: any R12-on-R11 result is a reader-sensitivity DIAGNOSTIC, not independent
   confirmation, not contamination-free.
19. **R11 diagnostic claim boundary:** frozen in `reports/R12_READER_SWAP_RATIONALE.md` +
    `docs/R12_R11_READER_SWAP_PROTOCOL.md`.
20–25. **Repository pilot / 40-task result / gate / main / M0–M4 / H1–H3:** **NOT RUN** (downstream of the block).
26. **Leakage/ownership audit:** provider carries no key in exceptions/logs; redaction on output; identical
    prompt/memory/extraction across readers enforced by design (prompt-rewrite prohibited).
27. **Retries/preemptions/resume:** none (no live calls); idempotency + resume are wired in the provider/runner
    design for when live phases run.
28. **Workflows:** `ci-openai-provider` GREEN (credential-free); `openai-integration` present but exits with an
    explicit PRECONDITION message when the key is absent. Existing R1–R11/P6 workflows unchanged.
29. **Hard-stop decisions:** the §0-A / §3 precondition (missing `OPENAI_API_KEY`) fired; no §16 hard stop
    triggered (no frozen-artifact mutation, no silent substitution, no prompt rewrite, no memory regeneration).
30. **Further P6 recommendation:** remain paused (do not resume during R12); existing P6 results preserved.
31. **Merge/release:** keep PR#1 **draft**; do not merge; no RC/beta tag.

## To unblock (single dependency)
Provision the GitHub secret **`OPENAI_API_KEY`** (optionally `OPENAI_ORG_ID` / `OPENAI_PROJECT_ID`). Then, in
order: A1 live provider smoke (3 fictional prompts/model + model-list) → B0 61-task no-memory band audit + reader
selection → C0 full frozen R11 M0–M3 reader-swap diagnostic + reader moderation → D0 gpt-5.6-terra R7 40-task
repository band audit → conditional E SWE-PolyBench memory main under a new reader-specific preregistration. All
protocols/tasks/locks are already frozen (`docs/R12_*`, `configs/openai_reader_r12/*`).

## Bottom line
R12 cannot answer its causal question (reader vs memory) without a live OpenAI credential, which is absent. Rather
than fabricate or misuse the fake server, R12 stops honestly at the **PRECONDITION BLOCK** with the entire
credential-free instrument built, tested (CI green), and frozen — reader candidates, band set, R11 reuse, provider
contract, and all protocols preregistered — so the study runs end-to-end the moment `OPENAI_API_KEY` is supplied.
**R1–R11 + P6 frozen; PR#1 draft; P6 not resumed; P6/P7/P8 not otherwise started.**
