# TriMem-Coder V1 D1.15 `_015` recovery source

## Current endpoint

The credential-free endpoint of this source is only
`TRIMEM_V1_READY_FOR_EXEC_015_REQUEST`.

`DEVELOPMENT_TUNING_EXEC_REQUEST_014.json` is spent. Run `34147189320`,
attempt `1`, must not be rerun and there is no attempt-two authority. D1.15 may
create one new zero-authority `DEVELOPMENT_TUNING_EXEC_REQUEST_015.json` only
after the exact D1.15 source HEAD passes all 20 frozen exact-head gates and a
fresh full loader rehearsal succeeds on the exact self-hosted execution
surface. The sentinel is not model, grader, protected-environment, or paid
execution authority.

## Immutable `_014` lineage

- D1.14 source: `6e9abe999f2b9d7ebdd3eea23dbbea8f6afad931`;
- exclusive `_014` child: `31234fdd58fd43170764524662c9e51687521761`;
- request blob OID: `f240997fccf2b0ef54d38e093ea21843272c6f5f`;
- request bytes: `25763`;
- request raw SHA-256:
  `7b4ff50e423cd12baea93413bbedcf7c2ee210d031fc20b30ad1c9d9f3c2dbaa`;
- request self-hash:
  `e046c09ac2a40a4f5a819e8dc522074d20157ddd6201233de8c49e209451d353`;
- source freeze SHA-256:
  `19da74e3e4d217354c7b2483bf1a462da10867ebe62c995df72405f273847448`.

The D1.15 reader obtains these identities from exact Git blobs. It preserves
the single-parent sentinel-only graph, the mode-`100644` request blob, the
canonical request self-hash, the D1.14 amendment/inventory/fixture/reader and
reseal bytes, and all older recovery history. The `_014` file is evidence, not
a mutable request template.

## Exact run boundary

GitHub Actions run `34147189320`, attempt `1`, used the D1.14 source and `_014`
execution commits above.

- `branch-trigger-preflight`, job `101821655367`: success;
- `bounded-context-preflight`, job `101821724190`: failure;
- `frozen-serial-phase`, job `101821923240`: skipped.

The bounded job passed exact checkout, cached-Python pre-setup validation,
`actions/setup-python`, live runner re-observation, the hash-locked install,
the bounded-context round trip, the production terminal-cell round trip, and
pinned harness materialization. It then failed at
`Gate protected job on unprotected exact loader preflight` with the public
marker `TRIMEM_OFFICIAL_HARNESS_LOADER_PREFLIGHT_NOT_READY`.

This means the failure happened after one hash-locked dependency installation
and two pinned harness checkout materializations. It happened before protected
environment entry, credentials, provider access, benchmark image pulls,
official graders, or scientific task arms.

## Root cause

The cached interpreter's real prefix was:

`/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64`

Its compiled `sysconfig.LIBDIR` spelling was:

`/opt/hostedtoolcache/Python/3.11.10/x64/lib`

At the failed run boundary that compatibility alias did not exist. The strict
loader therefore rejected the reported directory rather than silently falling
back to `<real-prefix>/lib`. The normalized diagnostic chain is:

1. `candidate libdir does not exist`;
2. `loader probe LIBDIR is not a trusted Python library directory`;
3. `exact Python loader is not ready`;
4. `credential-free official-harness loader preflight failed`.

The classification is
`CACHED_PYTHON_SYSCONFIG_LIBDIR_RELOCATION_FAIL_CLOSED`; the subtype is
`CACHED_PYTHON_SYSCONFIG_LIBDIR_ALIAS_ABSENT`. This is a cached-Python loader
portability failure, not a SWE-bench solve, official grading, or performance
result.

## Exact zero scientific accounting

- benchmark image pulls: `0`;
- grader attempts/containers: `0` / `0`;
- official grader runs: `0`;
- task-arm runs and terminal scientific cells: `0` / `0`;
- model metadata/generation/API calls: `0` / `0` / `0`;
- input/output tokens: `0` / `0`;
- paid model calls: `0`;
- total USD: `$0.00`.

`OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH` remains
`NOT_REACHED_ON_EXEC_014`, and container start remains
`NOT_REACHED_ON_EXEC_014`. `PERFORMANCE` remains `NOT_MEASURED`.

## Bounded diagnostic rehearsal

A credential-free diagnostic rehearsal was subsequently performed on
`TriMemRunner2404` with the exact cached Python and pinned harness clones. It
used the unchanged D1.14 loader and the exact compatibility alias:

`/opt/hostedtoolcache -> /opt/trimem-runner-cache/work-ci/_tool`

The full loader preflight emitted its PASS marker and the benchmark evidence
validator also passed. Rehearsal counters for model metadata/generation, image
pulls, grader attempts/containers, paid calls, and USD were all zero.

This is deliberately recorded as `diagnostic_rehearsal`, not as a production
benchmark result, remote gate result, or future execution guarantee. It
confirms the missing alias as the sole reproduced root cause. The `_015`
writer and workflow must independently revalidate the exact alias and rerun
the full loader-plus-evidence rehearsal on their current exact self-hosted
surface. No timestamp or output digest is asserted here because neither is
part of the supplied diagnostic record.

## `_015` request gate

Before `_015` can be written, all of the following must be true together:

1. the exact new source HEAD is a strict descendant of immutable `_014`;
2. all 20 frozen gates (six push and fourteen PR) pass at that exact HEAD;
3. both required ephemeral self-hosted runners are freshly observed;
4. the exact cached interpreter and pinned harnesses are used;
5. the exact compatibility alias resolves to the frozen tool cache;
6. the full official-harness loader preflight returns PASS;
7. the benchmark loader-evidence validator accepts that exact output;
8. every scientific, model, grader, image, token, and USD actual remains zero.

UNKNOWN, missing, stale, partial, differently rooted, or marker-only rehearsal
evidence fails closed. A unit-test double cannot satisfy the writer boundary.

## `_015` authority boundary

The request ID is `TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015`; the distinct future
approval string is `TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_015_APPROVED_ONCE`.

Request-creation authority may create one sentinel-only child after the gates
above. It cannot enter the protected environment, expose or use a key, call a
model, pull a benchmark image, start a grader container, or run a task arm.
Actual DEV execution would still require a separate explicit approval bound to
the exact `_015` execution commit, exact D1.15 source commit, freeze, request
bytes, workflow run ID/attempt, actor, timestamp, nonce, key commitment, legal
acceptance, and all frozen caps.
