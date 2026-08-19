# R12 §7/§8/§14 — R11 Reader-Swap Diagnostic Protocol (frozen)

Reuse EXACTLY the frozen R11 instrument; change ONLY the reader (selected OpenAI reader). Solar remains the
WRITER; OpenAI is only the replacement READER. This is a reader-sensitivity DIAGNOSTIC, never independent
confirmation, never contamination-free (R11 tasks predate the GPT-5.6 cutoff).

## Reused verbatim (no regeneration)
182 target IDs; source bank; verified source memories (memory_M1/M2/M3.json); source-target assignments;
relevance + shuffled mappings; memory strings + hashes; prompt templates; injection positions; token limits
(4096); extraction code; official LiveCodeBench grader; arm definitions M0/M1/M2/M3.

## Path (per task)
HTTP → durable job → separate worker → frozen memory policy → OpenAIResponsesProvider → existing extraction →
official grader → durable evidence. No direct benchmark-side OpenAI call.

## Analysis (diagnostic)
Pass@1 by M0–M3; Exec@1; M1−M2; M1−M0; M3−M1; positive/negative transfer; tokens/latency/cost. Reader moderation
(difference-of-differences vs frozen Solar R11): ReaderModerationRelevant = (M1−M2)_OpenAI − (M1−M2)_Solar;
ReaderModerationMemory = (M1−M0)_OpenAI − (M1−M0)_Solar; task-paired bootstrap CI + per-task DiD table.
Interpretation matrix A–E per milestone §8. No diagnostic p-value is called confirmatory.

## Outputs
`reports/R12_R11_OPENAI_RESULTS.md`, `reports/R12_READER_MODERATION.md`, `reports/R12_COST_AND_LATENCY.md`.
status: BLOCKED_pending_OPENAI_API_KEY.
