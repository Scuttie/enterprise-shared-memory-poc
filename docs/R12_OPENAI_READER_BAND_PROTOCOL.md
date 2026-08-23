# R12 §6/§14 — No-Memory Reader-Band Audit Protocol (frozen)

Frozen BEFORE any live call. Selects one OpenAI reader by NO-MEMORY behaviour only; memory is never used in
selection.

## Frozen set
- 61 tasks (`artifacts/openai_reader_r12/band_tasks.json`, sha256 `8d4ff626…`), hash-stratified over
  (difficulty × platform) of the 182 R11 targets, deterministic by sha256(question_id). No-memory only.

## Candidates (no substitution; §2 model_lock)
O0 gpt-4o-mini-2024-07-18 (temp 0, no reasoning) · O1 gpt-5.6-luna/medium · O2 gpt-5.6-terra/medium.
Same system+task prompt, memory placement (none), extraction, grader, stop policy, output budget (frozen R11
4096) across all three.

## Eligibility (per reader)
E1 terminal exec ≥ 0.98 · E2 evaluator/infra failure ≤ 0.02 · E3 malformed/extraction failure ≤ 0.02 ·
E4 no-memory Pass@1 ∈ [0.20, 0.70] · E5 target/test leakage = 0.

## Selection (among eligible)
1. minimise |Pass@1 − 0.45|; 2. if within 0.03, lower observed cost; 3. else gpt-5.6-luna; 4. gpt-4o-mini only if
no GPT-5.6 candidate is eligible. NEVER select by memory lift, p-value, style, or preference.

## Outputs
`artifacts/openai_reader_r12/{band_tasks,band_results,selected_reader}.json`, `reports/R12_READER_BAND_AUDIT.md`.
If no reader eligible → **NO ELIGIBLE DIRECT-CODE READER** (endpoint B).
