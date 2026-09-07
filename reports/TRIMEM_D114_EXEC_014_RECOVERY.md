# TriMem-Coder V1 D1.14 `_014` recovery source

## Current endpoint

The current credential-free endpoint is
`TRIMEM_V1_READY_FOR_EXEC_014_REQUEST`.

`DEVELOPMENT_TUNING_EXEC_REQUEST_013.json` is spent. Its attempt-one workflow
is immutable and must not be rerun. D1.14 permits creation of one new
zero-authority `DEVELOPMENT_TUNING_EXEC_REQUEST_014.json` only after the new
source HEAD passes all 20 exact-head credential-free gates (six push and
fourteen PR checks) and the external writer freshly re-observes the registered
runners. The sentinel is not paid execution authority.

## Immutable `_013` lineage

- D1.13 source: `cb17ceae0fbc951dff34213de977a73b5405fefc`;
- exclusive `_013` child: `35bfa338915d731dab499f2dfee08b38741bfe8d`;
- request blob OID: `899492ee4835394f78699ee1d4a6273c2d26e875`;
- request bytes: `21784`;
- request raw SHA-256:
  `a500568cedfa800bd85e20263b604fa2c1d24f634644d5ef14f517a8330b6417`;
- request self-hash:
  `132c7fc8a7ca166076882a53d3a69db56b4ccc5ab9e41ec1071a196f0618fe26`;
- source freeze SHA-256:
  `ea74940aad297761c62c9f2555eb9aba3819e584082bf68951247e9a39d1f0c6`.

The D1.14 history validator reads those bytes from their exact Git commits.
It verifies the single-parent, sentinel-only graph, regular mode-`100644`
blob, canonical request bytes, D1.13 amendment and inventory, every D1.13
implementation digest, the D1.13 source freeze, and the complete older D1.12
history chain. Historical tests must select `cb17ceae...` or `35bfa338...`
Git blobs; they must not reinterpret the current D1.14 workflow or readiness
document as D1.13 state.

## Exact run boundary

GitHub Actions run `34138918074`, attempt `1`, used source
`cb17ceae0fbc951dff34213de977a73b5405fefc` and execution commit
`35bfa338915d731dab499f2dfee08b38741bfe8d`.

- `branch-trigger-preflight`, job `101796222373`: success;
- `bounded-context-preflight`, job `101796314944`: failure;
- `frozen-serial-phase`, job `101796404674`: skipped.

The bounded job passed checkout, the complete cached-Python pre-setup probe,
and pinned `actions/setup-python`. It then failed at
`Re-observe exact self-hosted runner before any install or materialization`.
The strict error was:

`runner LD_LIBRARY_PATH binding differs: bounded-context preflight process environment`

The required value was exactly:

`/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib`

After `setup-python`, the observed value was exactly:

`/opt/trimem-d112-runners/exec/_work/_tool/Python/3.11.10/x64/lib:/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib`

The failure classification is
`POST_SETUP_PYTHON_DUAL_LD_LIBRARY_PATH_FAIL_CLOSED`; the subtype is
`SETUP_PYTHON_POST_SETUP_LD_LIBRARY_PATH_SHAPE`. This was a self-hosted,
unprotected control-plane failure. It was not a SWE-bench solve, official
grader run, or performance result.

## Zero-work accounting

The run stopped before dependency installation or harness materialization.
The protected environment was neither requested nor entered. Therefore:

- dependency installations: `0`;
- harness materializations: `0`;
- benchmark image pulls: `0`;
- grader containers: `0`;
- official grader runs: `0`;
- task-arm runs: `0`;
- model/API calls: `0`;
- input/output tokens: `0` / `0`;
- paid model calls: `0`;
- total USD: `$0.00`.

`OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH` remains
`NOT_REACHED_ON_EXEC_013`: success of the Actions cached-Python and
`setup-python` control-plane steps is not an official harness/grader child launch.
`OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START` is likewise
`NOT_REACHED_ON_EXEC_013`. `PERFORMANCE` remains `NOT_MEASURED`.

## D1.14 correction

The strict validator remains unchanged: the process, each runner `.env`, and
each live `Runner.Listener` must still expose one exact
`LD_LIBRARY_PATH` value. D1.14 does not accept, normalize, split, deduplicate,
or resolve the two-entry value observed in `_013`.

Instead, each post-setup workflow step that invokes the strict runner or
service-lifecycle validator receives the one frozen value as an explicit step-level environment binding.
The covered steps are:

1. bounded post-setup live runner re-observation;
2. protected post-setup live runner re-observation;
3. protected cache-only service start;
4. protected cache-only service verification;
5. protected cache-only service cleanup.

Both pre-setup checks retain the same exact binding. Dependency installation,
harness materialization, models, prompts, tools, parsers, targets, target
order, arms, M2 candidates, selection policy, token/call caps, grader locks,
image locks, and pricing remain byte-identical to the spent `_013` tree.

The six newly enforced PR-side gates use the exact pull-request head checkout,
full history, disabled credential persistence, and immutable action SHAs. This
closes the difference between merely observing 20 green checks and requiring
all 20 from the exact source HEAD before request creation.

## `_014` authority boundary

The new request ID is `TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014`; the required
external authorization string is
`TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_014_APPROVED_ONCE`.

Request-creation authority can create one sentinel-only child after fresh
all-20 exact-head credential-free CI and runner evidence. It cannot enter the
protected environment, use a key, make a metadata or generation request,
pull a benchmark image, start a grader container, or run a task arm.

Actual DEV execution still requires a distinct external approval bound to the
exact `_014` execution commit, D1.14 source commit, source freeze, request
bytes, workflow run ID and attempt, legal acceptance, actor, timestamp, nonce,
OpenAI-key commitment, and every frozen cap. Paid/model calls remain `0` until
that separate approval is supplied.
