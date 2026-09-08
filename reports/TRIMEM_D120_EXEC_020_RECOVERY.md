# TriMem-Coder V1 D1.20 `_020` harness-runtime isolation recovery

## Current endpoint

This credential-free source may end only at
`TRIMEM_V1_READY_FOR_EXEC_020_REQUEST`. It is not a benchmark score and does
not authorize protected execution. Run `34223706155`, attempt `1`, and
`DEVELOPMENT_TUNING_EXEC_REQUEST_019.json` are spent. They must not be rerun,
resumed, or reused as approval for another attempt.

## Immutable `_019` execution boundary

- source HEAD: `df93cdbcf0d8e30014035e79cf5d7d52848d5072`;
- execution HEAD: `f3053cddc6b32c2b51ef7de5a6ccf0d95ea578c2`;
- `_019` raw SHA-256:
  `534d8500073ae414fa7839b6af7c88bdcc88dbb28997066826ba18ebe8868c4e`;
- `_019` Git blob: `87b89e72c9000f3d61ab37fac8320b459ecee21c`;
- `_019` payload SHA-256:
  `458acf0633b3f8ff09787a7f29609d09247ee800296d00988aa914fd05b2c06c`;
- source freeze SHA-256:
  `481edaacfba349335c6c5d24315508a36ee07ba1aa8a5c38413fe229032709a2`;
- workflow run/attempt: `34223706155` / `1`;
- run created/updated: `2026-09-08T12:00:42Z` /
  `2026-09-08T12:18:45Z`.

The branch preflight (`102052608047`) and bounded-context preflight
(`102052722704`) succeeded. The frozen serial job (`102054185453`) failed.
Approval materialization, the protected environment, EXEC gate, exact-model
metadata, protocol canary, all 13 frozen image pulls, and the protected
three-adapter grader-factory rehearsal passed.

The first Django `M2-baseline` cell was terminal. It used 18 scientific calls
(one decomposition, 16 solves, one extraction), 177,547 input tokens, 1,664
cached-input tokens, 5,084 output tokens, 2,853 reasoning tokens, and
`$0.154915050000`. Its official grader container exited zero and marked the
partial patch resolved, but the agent itself ended on the per-subtask step
cap. Accordingly the cell is `CELL_SCIENTIFIC_FAILURE`, not a successful
campaign observation.

The next SymPy cell was reserved only. Before any model call or container
start, the grader-factory preflight revalidated the pinned SWE-bench checkout
and failed closed. It consumed zero model calls, tokens, grader containers,
and USD.

## Exact observed accounting

The whole `_019` attempt, including the protocol canary, consumed:

- 19 paid generation calls: one canary plus 18 scientific calls;
- one decomposition, 16 solve, and one extraction call;
- 178,497 input, 1,664 cached-input, 5,112 output, and 2,853 reasoning tokens;
- 13 image pulls, two task-arm reservations, one task-arm run, one terminal
  cell, one grader container, and one official grader run;
- exact USD: `$0.155753550000`.

This is one partial cell out of the frozen 72-cell campaign. Aggregation was
never entered, Pass@1 is `null`, performance is `NOT_MEASURED`, and no
campaign result or selected M2 checkpoint exists.

## Root cause and evidence custody

The root cause is
`OFFICIAL_HARNESS_RUNTIME_OUTPUT_ISOLATION_FAILURE`, subtype
`SHARED_SWE_HARNESS_RUNTIME_OUTPUT_CONTAMINATION`. The SWE-bench official
evaluator ran with the shared pinned harness checkout as its current working
directory and wrote `logs/run_evaluation/...` below that checkout. The next
cell's strict `validate_pristine_checkout` correctly rejected the new
untracked runtime output. Git-blob pinning and pristine validation both worked
as designed; they are not weakened by D1.20.

The process stdout is 152 bytes with SHA-256
`a78bc491d88a3a7dcf9d3ff7109642bd3b71bf09162d664f994c7971ce7d3184`.
Stderr is 440 bytes with SHA-256
`2bdb74770e41a560af98ce265b46837de05e3a95791efba67b3ee07ba3424cee`.
The frozen failure fixture contains no secret or model content.

Failure custody recovered 249 files totaling 20,201,702 bytes with inventory
SHA-256
`6b13fd8fab63db8408e927d1be078c59c3f17a196b15264bb10e3ea55d477995`.
The restricted encrypted, inventory, and custody artifacts have GitHub
artifact digests
`1ab6b73601be6aad81b7b5b84d4f2991a88c1555e714e41159d88c922418ff65`,
`4306f9432491d12ee6fce48fadceac3ff056bd3f334cfd9101dd7402d85428c4`,
and `46429579cc0a4a941c4c44bce71481a1177c908b799b2f8f95b824ca8fc743ff`.

## Fail-closed correction

D1.20 preserves the frozen harness as the import and Git-object verification
root, but never uses it as evaluator runtime cwd. Each task-arm cell receives
a unique task-local runtime directory outside every pinned checkout, with
exact task input and report paths beneath that directory. The SWE-bench
entrypoint runs there with the pinned checkout on the module search path and
performs a pristine-checkout postflight after every returned upstream exit,
including nonzero exits. The parent official grader performs a full pristine
postflight after a subprocess timeout, and every subsequent grader-factory
construction always rechecks the pinned checkout before any cell proceeds.

The D1.20 loader rehearsal uses schema `1.20` and exercises two sequential
SWE-bench cells. It proves that runtime output from the first cell cannot
contaminate the pinned checkout or prevent the second cell's strict preflight.
The correction retains exact Git-blob locks, revision locks, image locks,
dependency locks, full stdout/stderr/evidence custody, and fail-closed
subprocess semantics.

## Preserved science and `_020` authority boundary

D1.20 does not change model `gpt-5.4-mini-2026-03-17`, reasoning effort
`medium`, pricing, all 12 targets and their order, six streams, prompts, tools,
parsers, memory policies, per-arm budgets, grader/image locks, the `$10.80`
expected budget, or the `$50.00` hard cap. No result-dependent scientific
choice was made.

Only a sentinel-only `_020` child may be created after exact-source
credential-free CI and fresh writer/runner, loader, sequential-cell,
grader-factory, and checkout rehearsals pass. D1.20 reuses the strict D1.19
Python byte-only approval producer; it does not reuse any prior approval
artifact. Protected execution requires a new external approval bound to the
exact `_020` sentinel child, workflow run ID, attempt `1`, source freeze,
request bytes, actor, timestamp, nonce, legal acceptance, caps, and key
commitment. Until that separate approval exists, model/API calls for the new
attempt remain zero and performance remains `NOT_MEASURED`.
