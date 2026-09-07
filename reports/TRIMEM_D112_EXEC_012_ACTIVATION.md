# TriMem-Coder V1 D1.12 — `_012` activation source

## Scope

D1.12 is a credential-free activation correction for one new zero-authority
`DEVELOPMENT_TUNING_EXEC_REQUEST_012.json` sentinel. It does not authorize a
model request, an official grader, an image pull, a task-arm run, protected
environment approval, HELDOUT, merge, tag, or release.

The user authorized creation of the `_012` sentinel after the source commit has
passed fresh exact-head CI and exactly two isolated repository runners have been
registered and observed. A distinct external approval must then bind the exact
sentinel commit, source commit, source freeze, request bytes, workflow run ID and
attempt, cost and call caps, actor, UTC timestamp, nonce, legal acceptance, and
OpenAI-key commitment before the protected job may execute.

## Immutable history

- D1.11 baseline: `fa1af529a2af4f8ba606b01410434412881f3d27`
- D1.11 freeze SHA-256: `e2964255c9c214f29c04bc8df2a5fe275601d43a40f8cad6b1fc926b8cf73739`
- `_011` execution: `e54d04b0af9e738d311c389dc89cfd510fd7065b`
- `_011` run: `34047573548`, attempt `1`, final and not reusable
- `_011` observed model/API calls, graders, images, task arms, tokens, and USD: all zero

D1.12 reads D1.11 artifacts from immutable Git blobs. It does not rebuild or
rewrite the spent D1.10/D1.11 contracts.

## Corrected activation contract

- historical workflow gates are selected from immutable top-level run identity;
  mutable nested `pull_requests` entries are ignored;
- the current PR is queried and bound independently to the execution head;
- the source is a strict descendant of D1.11 with an explicit closed path set;
- `_012` is absent from the source and all source history;
- its execution commit is exactly one single-parent child adding only one regular
  non-executable `100644` `_012` JSON blob;
- the request is canonical UTF-8 JSON plus one LF and contains no secret or
  execution authority;
- two fresh ephemeral runners have the repository-specific labels
  `trimem-ubuntu-24.04` and `trimem-benchmark`, distinct names and roots, exact
  Ubuntu/Python/Docker/image observations, zero containers, and no protected
  secret in the preflight environment;
- source CI gates and runner observations are embedded before the sentinel is
  written, and are rechecked by the hosted branch trigger.

## Scientific invariants

The exact model `gpt-5.4-mini-2026-03-17`, reasoning effort, prompts, tools,
parsers, target order, M0/M1/M2 definitions, four M2 candidates, 72 task-arm
runs, call/token/container limits, grader/image locks, and selection rule remain
unchanged. D1.12 performs no result-dependent tuning.

## Current endpoint

`TRIMEM_V1_READY_FOR_EXEC_012_REQUEST`

This endpoint means only that credential-free request creation may proceed after
its live gates. It is not a benchmark result and not DEV execution approval.
Performance remains unmeasured.
