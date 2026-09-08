# TriMem-Coder V1 D1.19 `_019` approval-secret transport recovery

## Current endpoint

This credential-free source may end only at
`TRIMEM_V1_READY_FOR_EXEC_019_REQUEST`. It is not a benchmark score and does
not authorize protected execution. Run `34211486542`, attempt `1`, and
`DEVELOPMENT_TUNING_EXEC_REQUEST_018.json` are spent and must not be rerun or
resumed.

## Immutable `_018` execution boundary

- source HEAD: `3236bd546ff581e396ca6123bb1655bad5294ce4`;
- execution HEAD: `5cce6502a61c81c2e0490578dc5a2a3045f8c179`;
- `_018` raw SHA-256:
  `9264a90a8ace461f515e4725d4058e5ee486fa7304364cf75d65dfba6be603a0`;
- workflow run/attempt: `34211486542` / `1`;
- branch-trigger and bounded-context preflights: `PASS`;
- protected environment and protected three-adapter grader-factory rehearsal:
  `PASS`;
- approval materialization: `FAIL_CLOSED`;
- EXEC gate, OpenAI credential validation, exact-model metadata, protocol
  canary, image materialization, task-arm reservation, model generation, and
  official grading: not reached.

The frozen protected-job log is 140,761 bytes with SHA-256
`fb32b0d75e9d8732d7437dde095681e11ae89b2312882782697dca3286ec97ad`.
It records a leading `U+FEFF` at position zero in
`TRIMEM_EXEC_APPROVAL_B64`; the workflow's strict decoder rejected the
non-ASCII string before it could materialize approval JSON.

## Exact observed accounting

Run `_018` made zero provider control-plane requests, exact-model metadata
requests, protocol-canary calls, scientific model calls, paid model calls,
image pulls, task-arm reservations/runs, grader containers, and official
grader runs. Input, cached-input, output, reasoning, and total tokens are all
zero. Exact USD is `$0.000000000000`. No Pass@1 or performance result exists.

The failed run uploaded no artifacts because it stopped before approval
materialization. No plaintext approval document was created by that step. The
three protected-environment secrets and both ephemeral runners were removed
afterward. This no-artifact pre-execution boundary is distinct from D1.17's
encrypted partial scientific evidence, which remains immutable history.

## Root cause

The intended approval JSON was 1,027 bytes with SHA-256
`7d737413fcb3a0ff179f49016f7a71aa1c90a841238f71df2f9c1af9b821e6d5`.
Its intended Base64 was 1,372 ASCII bytes with SHA-256
`f84f47603ec73e8a443a01ead6c58b286878514c1bd8d551442ea47f19049417`;
it had no BOM, CR, LF, or spaces and passed strict round-trip decoding. The
external PowerShell stdin upload path converted that clean byte sequence into
text with a leading BOM. This is an external approval-secret production
transport encoding failure, not an approval-document producer, workflow
decoder, model, image, task, grader, or
performance outcome.

## Fail-closed correction

D1.19 keeps `base64.b64decode(value, validate=True)` unchanged. The correction
uses a dedicated external producer that accepts the approval document as
bytes, emits canonical UTF-8 and Base64 with Python byte APIs only, and rejects
BOM, NUL, CR, LF, spaces, non-ASCII output, invalid padding, or a failed strict
round trip. It does not use PowerShell `Out-File`, `Set-Content`, an editor,
clipboard transfer, UTF-8-SIG, UTF-16, shell `echo` redirection, or arbitrary
Unicode stripping.

The `_018` approval artifact and Base64 payload are not reusable. After exact
source CI and fresh runner rehearsals, `_019` requires a newly built external
approval bound to the new sentinel child, source freeze, request bytes,
workflow run ID, attempt `1`, actor, timestamp, nonce, legal acceptance, caps,
and exact OpenAI-key commitment.

## Pre-request loader-wrapper correction

Before `_019` existed, the local writer collected fresh D1.19 runner readiness
and then failed closed in the exact full-loader rehearsal. The host produced a
`trimem/self-hosted-runner-readiness/1.19` record, but the separate WSL process
still entered through the inherited D1.18 wrapper and rebound the validator to
schema `1.18`. It therefore rejected the record with `runner readiness identity
differs`. This was a credential-free request-construction rehearsal, not a DEV
execution attempt: no sentinel or secret existed, and provider, model, image,
task-arm, grader-container, official-grader, token, and USD actuals were all
zero. D1.19 now has its own subprocess wrapper, which binds the existing strict
D1.15 collector to the complete D1.19 runtime context without weakening any
readiness validator.

## Preserved scientific identity and `_019` authority boundary

D1.19 preserves exact model `gpt-5.4-mini-2026-03-17`, reasoning effort
`medium`, all 12 targets/order, six streams, prompts, tools, parsers, memory
policies, per-arm budgets, grader/image locks, the `$10.80` expected budget,
and the `$50.00` per-attempt hard cap. No result-dependent scientific choice
is changed.

Only a sentinel-only `_019` child may be created after exact-source CI, fresh
writer-runner readiness, loader, grader-factory, and checkout rehearsals.
The loader rehearsal enters through the D1.19 subprocess wrapper so the
separate WSL process validates the D1.19 runner-readiness schema and identity.
Protected execution still requires a separate external approval. Until that
execution completes, performance remains `NOT_MEASURED` and this recovery is
not a final endpoint.
