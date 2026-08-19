# REALBENCH-R14 — SWE-bench Verified memory transfer (RAW worked-example) — Preregistration

Redesign after R11–R13 nulls, addressing the critique that distilled abstract memory was the likely cause.
Benchmark: **SWE-bench Verified** (`SWE-bench/SWE-bench_Verified`, 500, most-used repo-level benchmark, license
resolvable: harness MIT + permissive OSS repos). Reader: **gpt-4o-mini** (band-checked: no-memory 2/30 = 6.7% —
low but measurable, not floor). Frozen 60 targets (sha256 `8282f2cb…`).

## Memory = RAW worked example (the fix)
M1 = the **actual prior resolved issue in the SAME repo** (source problem_statement + the real gold unified
diff), injected as a read-only worked example — NOT a gpt-distilled abstraction (that was R11–R13's flaw). This
is genuine "another engineer's fix in this codebase." The agent never sees the TARGET's gold patch/tests.

## Arms + endpoints
- **M0** no memory · **M1** relevant same-repo prior fix (raw) · **M2** shuffled cross-repo prior fix (raw,
  control). Primary **H1 = M1 − M2** (does a *relevant* prior fix beat an *irrelevant* one?). Secondary
  **H2 = M1 − M0** (does the prior fix help at all — key at a low base rate).
- Controls: `created_at(source) < created_at(target)`; `source_user ≠ target_user`; target never its own source;
  same injection position; target gold/tests never in context. ITT; exact McNemar; a null is final.

## Honest limitation
Base rate ~6.7% → limited power for M1−M2; if a raw relevant fix genuinely helps, M1−M0 should still show it. A
clear positive would be the first in this program; a null here (raw examples, famous repo benchmark) is a much
stronger negative than the distilled-memory nulls.
