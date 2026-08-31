# R23-R0 author-method clean-room reproducibility

Status: **credential-free fake/replay implementation is complete and tested; live model and official grader
execution are not approved or performed.** This is not a final endpoint. The author code and verbatim prompts for
arXiv:2602.21611v1 are unavailable, so R23-R is an independent clean-room implementation, not an official artifact
reproduction.

## Actual AR0-AR5 execution path

The runnable path is:

1. `scripts/r23_r0_run.py` loads target-visible task rows and accepts only `--reader fake` or `--reader replay`.
2. `experiments/r23/r0_runtime.py:R0Runner.run_stream` restores the arm/order checkpoint and its prefix-only memory.
3. `experiments/r23/author_method.py:build_solve_payload` emits the actual arm payload over the pinned scaffold.
4. Structured arms apply the explicit `ANALYZE -> REPRODUCE -> EDIT -> VERIFY -> COMPLETE` transition contract.
5. `build_extraction_payload` and `parse_extracted_memory` create success-pattern or failure-avoidance `m=(z,d,e)`
   entries. Entries remain buffered and invisible until the current target completes.
6. Every request and response is written before the task checkpoint advances; resume reuses matching durable call
   pairs. A durable request without a response fails closed so a possibly paid call is not silently repeated.

Arm payloads are now concrete: AR0 is the unextended pinned Mini-SWE-Agent prompt; AR1 adds category transitions;
AR2 injects/extracts one whole-task experience; AR3 uses category-filtered forced Top-1 coarse experience; AR4
removes the category filter; AR5 injects a token-bounded raw coarse trajectory after the same success/failure
classification call. Full contracts are in `artifacts/r23/author_method_spec.json`.

## Mini-SWE-Agent lock

Public source commit: `25941c89cfbc91eb40b3f8756348c91d9977d57e`.

| Frozen object | SHA-256 |
|---|---|
| SWE-bench config bytes | `0389e74fe7d730e384b82bbdabf5d58c307299e676f0c6453b9946116708033d` |
| system prompt | `06f6dd6ea8671220762ff4a4916bd0aeb4fb2adfb084469a803e2fa841018efe` |
| instance prompt | `8826e3fbabc7733ad4d118654bbd392c2a4e0f1931d55f9c62235d33bd494196` |
| canonical bash tool schema | `fa3f9e719935ffb5dbdccb5f58ed0a413553c7ceb651f8a6afd0ac8f01783cc4` |
| tool-call parser source | `14236747cf9a60fe129ca6579915756c7743000201b60ec9ecdca6afcfb7d502` |
| patch submission parser source | `b47cd7bf6a7c67342ed2567597e5b520d60c0ef6e01ff65b4833ecbb1ca931d3` |

The exact upstream default is 250 steps, `/testbed`, a 60-second command timeout, and the pinned Docker submission
parser. `scripts/r23_r0_verify_scaffold.py --checkout <detached-checkout>` recomputes every prompt/tool/parser/file
hash without network, model, or Docker execution. The verified result against the locked checkout was PASS.

## Equal budget proof and extraction accounting

Each target/arm/order receives the same hard envelope: 250 solver steps/calls plus four reserved extraction-call
slots, for 254 total call slots; 1,064,000 total input tokens; 108,192 total output tokens; and a 2,048-token memory
injection cap. The four reserved slots cannot be converted to solver work. AR0/AR1 may spend zero extraction slots,
AR2 one, and AR3-AR5 four. This preserves the same solver cap and total envelope without giving no-memory arms extra
solver work. Expected usage is recorded separately from caps in `artifacts/r23/r0_budget_lock.json`.

The two-target fake E2E produced these accounted protocol calls:

| Arm | solve | extract | memory entries |
|---|---:|---:|---:|
| AR0 | 2 | 0 | 0 |
| AR1 | 8 | 0 | 0 |
| AR2 | 2 | 2 | 2 |
| AR3 | 8 | 8 | 8 |
| AR4 | 8 | 8 | 8 |
| AR5 | 8 | 8 | 8 |

These are fake-reader protocol slots, not external calls. External model calls = 0; paid model calls = 0; Docker
calls = 0; grader-container calls = 0.

## Credential-free evidence and resume

`artifacts/r23/r0_credential_free_e2e_bundle.json` is a tracked, deterministic bundle containing:

- two target-visible fixture tasks and AR0-AR5 summaries;
- an AR3 one-task checkpoint followed by a two-task resume (only the second task executes after resume);
- an AR2 two-task replay that consumes all four captured response records;
- complete request/response evidence, result files, final checkpoints, and a per-object hash index for the resume
  and replay samples.

Bundle content SHA-256: `26ab8979a692d476254c0f931e04d6905eec09ec904cb953aa767f3d4750488b`.
`scripts/r23_r0_build_e2e_evidence.py --check` regenerates the run in a temporary directory and fails on drift.

## Method boundary

R0 stores only the coarse author-method tuple `m=(z,d,e)`. AR3 does not import or emit R23 proposed-method graph or
semantic-atom fields. The final divide-and-conquer method remains a separate A0/G0/F1 implementation, and R23-R
reproduction results must not be pooled with R23-X proposed-method results in one sample mean.

Remaining work includes B0.1 chronology, official grader smoke execution, and A0/G0/O0/F1/S0/CF. Consequently this
credential-free R0 milestone does not establish benchmark/grader viability, an author-method effect, a proposed-
method effect, or the final R23 endpoint.
