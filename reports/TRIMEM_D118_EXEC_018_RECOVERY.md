# TriMem-Coder V1 D1.18 `_018` launcher-binding recovery

## Current endpoint

This credential-free source may end only at
`TRIMEM_V1_READY_FOR_EXEC_018_REQUEST`. It is not a benchmark score and does
not authorize protected execution. Run `34200331390`, attempt `1`, and
`DEVELOPMENT_TUNING_EXEC_REQUEST_017.json` are spent and must not be rerun.

## Immutable `_017` execution boundary

- source HEAD: `f1cfcbcbeff9a75bb118c3ee53ad1c3c36f7ff5f`;
- execution HEAD: `63ed76143267b25d9086ed3b33d338bf368aa3fa`;
- `_017` raw SHA-256:
  `bf736089da26a11f5289257e92c11a02e407a53813d6d2fb5d3844864a0b8919`;
- workflow run/attempt: `34200331390` / `1`;
- branch-trigger, bounded-context, protected approval, exact-model metadata,
  protocol canary, migration, and 13 digest-locked image observations: `PASS`;
- first stream/cell: `M2-baseline` /
  `swebench_verified--django__django-16100`;
- aggregate, public result, grader container, and terminal cell: not reached.

The process retained the terminal disposition `GLOBAL_ENVIRONMENT_FAILURE`
and message `official harness loader preflight current exact
loader/environment identity differs`. Attempt 1 is not resume-safe. No Pass@1
or performance result exists.

## Exact observed accounting

The entire `_017` execution used one provider metadata request, one paid
protocol canary, and 17 paid scientific calls: one decomposition, 16 solve,
and zero extraction. Across canary plus scientific work it used 197,498 input,
zero cached-input, 5,068 output, and 3,157 reasoning tokens, costing exactly
`$0.170929500000`. One task-arm reservation was opened, but zero task-arm runs
or terminal cells completed. Grader containers and official grader runs were
both zero.

Encrypted restricted evidence is artifact `10046287381`
(`sha256:d38fdf2db581b08321635b0a619f5053c985ddcf4788257f4a8e91ada1777b8f`).
Inventory artifact `10046288749` and custody artifact `10046290933` verify the
failure evidence. The decrypted inventory independently reproduced 223 files,
10,729,599 bytes, and root SHA-256
`e6b0d12a520b6b6cb2fe593ab021f732fa84900da79895a5f0221a603d97a137`.
All protected-environment secrets were removed after evidence custody.

## Root cause

The protected loader preflight recorded the lexical launcher
`.../bin/python3.11`. The protected driver was invoked using the workflow token
`python`, whose runner-local alias preserves `.../bin/python` as
`sys.executable`. Those two aliases resolve to the same frozen interpreter:
`/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/bin/python3.11`,
17,736 bytes, SHA-256
`930be806841bf98ef6898a7d8c69b0083b68c803c5fcd7a77becefaf84bc25c9`.

The expected `python3.11` lexical path is directly present in the protected
preflight evidence. The later `python` lexical path is an inference from the
committed workflow invocation, committed readiness evidence, and an
independent WSL symlink reproduction; the failed run did not retain the later
`sys.executable` value itself. The loader contract intentionally compares the
complete evidence, including the lexical `python_binary` field, so it correctly
failed closed even though realpath, bytes, loader probe, and environment were
otherwise identical.

This is an official-grader full-loader identity alias-binding defect, not a
model, task, grader, image, or performance outcome.

## Fail-closed correction

D1.18 does not weaken the full loader comparison. The grader factory now uses
the exact lexical launcher recorded by the validated preflight, validates the
complete loader and execution-environment identity before returning, and gives
the same launcher to the terminal grader journal. The protected benchmark
driver is explicitly invoked through `$pythonLocation/bin/python3.11`.

Two credential-free gates exercise the failure boundary before model access:

- the unprotected bounded-context job materializes the real frozen harnesses
  and datasets, then creates and journal-binds grader factories for all 12 DEV
  targets;
- the protected job runs a synthetic three-adapter grader-factory rehearsal
  before approval materialization or OpenAI-key access.

Both rehearsals require zero credentials, provider requests, model calls,
image pulls, grader containers, official grader runs, and task-arm runs.

## Preserved scientific identity and `_018` authority boundary

The D1.18 source preserves exact model `gpt-5.4-mini-2026-03-17`, reasoning
effort `medium`, all 12 targets/order, six streams, prompts, tools, parsers,
memory policies, per-arm budgets, grader/image locks, the `$10.80` expected
budget, and the `$50.00` per-attempt hard cap. The 18 paid calls and
`$0.170929500000` consumed by `_017` are historical actuals; they are not
reused or counted as `_018` pre-execution activity.

Only a sentinel-only `_018` child may be created after exact-source CI, fresh
writer runner readiness, loader and checkout rehearsals, and validation that
the source workflow places both grader-factory rehearsals correctly. After the
child push, the protected synthetic rehearsal must pass before approval
materialization or API access. Protected execution still requires a distinct
external approval bound to that child, source, freeze, request bytes, workflow
run ID/attempt, actor, time, nonce, legal acceptance, caps, and OpenAI-key
commitment.
