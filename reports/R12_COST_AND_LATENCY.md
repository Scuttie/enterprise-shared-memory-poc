# R12 §13 — Cost & Latency

Estimated at public model rates (recorded, not billed here). gpt-4o-mini-2024-07-18: ~$0.15/1M input,
$0.60/1M output.

## R12-B0 no-memory band audit (61 tasks × 3 readers = 183 calls)
| reader | calls | note |
|---|---|---|
| gpt-4o-mini | 61 | exec 1.000 |
| gpt-5.6-luna | 61 | 7 incomplete (reasoning exhausted 4096 budget) |
| gpt-5.6-terra | 61 | 5 incomplete (reasoning exhausted 4096 budget) |
Reasoning tokens on GPT-5.6 reached ~3500–3700/call, consuming most of the frozen 4096 output budget on hard
tasks (this is why GPT-5.6 exec < 0.98). No caching introduced to reduce cost; provider default behaviour kept.

## R12-C0 R11 reader-swap (gpt-4o-mini, 182 × 4 arms = 728 calls)
- input tokens 445,135 · output tokens 312,559 · latency median 5.39 s / mean 5.68 s.
- estimated cost ≈ **$0.25** (input $0.067 + output $0.188).
- cached_input_tokens = 0 across arms (no explicit caching; prompts differ per arm by the injected memory block).

## Accounting completeness
Every call persisted a ModelCallRecord (requested/returned model, response id, tokens incl. reasoning/cached,
latency, retries, finish/redaction/final_status). Key never appears in any exception/log/persisted artifact.
