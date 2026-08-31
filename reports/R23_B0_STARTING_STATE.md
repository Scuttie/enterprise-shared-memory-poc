# R23-B0 — Starting state (live-verified)

| item | value |
|---|---|
| R23 branch head | `c36d7b19d21dda87ea94a36a5ff4d21514d40287` |
| PR #17 | OPEN / DRAFT, base `codex/r22-stage-aligned-memory` — R23 changes only |
| R22 branch / PR #16 | unchanged (referenced as coarse baseline + provenance only, not continued) |
| main | `ce10ab49586db7a859fbe5cca93051b93f9f5b55` — unchanged |
| v0.3.0-rc1 tag object | `c1741c6d635bc97e470ea553753c143888a0c0be` — unchanged |
| R1–R22 frozen | preserved |
| paid/model API calls | 0 |

No merge/tag/release/rebase/force-push; no R22 manifest change; no R22 result reuse as R23. Parent lock:
`artifacts/r23/parent_state_lock.json`.

## §1 F0 claim-boundary correction (applied)
`NOVELTY GATE = PROCEED` → **`NOVELTY SCREEN = PROCEED` ; `NOVELTY CLAIM = NOT YET ESTABLISHED`**. One screening pass
does not establish publication-level novelty; it only found the audited literature does not reveal the complete R23
combination. NOT-NOVEL (kept): functional-stage decomposition, category-aligned memory, category hard-filter,
semantic Top-1, online subtask-memory accumulation, abstracted-experience extraction, structured-prompt-only
control. Candidate distinction: operation/precondition/invariant/dependency atoms; source×query factorial;
overlap-conditioned causal analysis; conditional-efficacy vs natural-stream utility; explicit abstention;
structurally-matched known-wrong-atom safety.

### §1.1 Third-party implementation (audited, not author code)
`taeilkim2465/agentic_memory_distillation` @ `2895d10c` (created 2026-06-18) — **`THIRD_PARTY_NONAUTHOR_IMPLEMENTATION`**,
**license NONE**. Has SASM for AppWorld/BFCL/ToolSandbox (not the SWE-bench reproduction; belongs to another 2026
program). Inspect for interface/omission comparison only; no vendoring. Official author code (arXiv:2602.21611)
availability to be re-checked before any paid run. (`artifacts/r23/third_party_implementation_audit.json`)
