# R12-E §12 — Repository Memory Main: Cost Estimate (written BEFORE any Phase-E memory-arm call)

## Basis (from D0, gpt-5.6-terra, agentic repo tasks)
Per task: input ≈ 77,500 tok, output ≈ 1,960 tok, reasoning ≈ 920 tok (reasoning billed as output), 182 s.
The large input is the multi-turn agent loop (repo file contents + accumulated tool observations).

## Rate assumption (gpt-5.6-terra — recorded, not authoritative; refine from the live usage)
Conservative reasoning-tier estimate: ~$1.25 / 1M input, ~$10 / 1M output (reasoning incl.). With Responses
`previous_response_id` chaining, later turns' input may bill as cached (cheaper); estimate ignores caching (upper
bound). → per task ≈ 77.5k/1e6·$1.25 + ~2.9k/1e6·$10 ≈ **$0.097 + $0.029 ≈ $0.13 / task** (upper bound).

## Phase-E plan + estimated calls
- **Main targets (frozen):** N = 60 untouched SWE-PolyBench Verified tasks (the 40 pilot excluded).
- **Source bank:** historical instances resolved by their own gold patch (evaluator-verified, no reader solve
  needed); memory derived offline → ~0 extra terra calls for the bank itself (lesson text derived from
  source problem + gold, evaluator-side, distilled; the agent never sees gold).
- **Arms:** M0/M1/M2/M3/M4 × 60 = **300 target-arm terra calls** (+ retries).
- **Estimated cost:** 300 × $0.13 ≈ **$39** (upper bound; likely lower with caching). Plus M4 deployable
  retrieval embeds public issue text with the pinned embedder (no terra cost).

## Controls (§12)
Persist estimated vs actual cost separately; do not retry successful calls; stable task-arm idempotency keys;
resume only incomplete calls. Phase-E does not begin until this file is committed (it is).
