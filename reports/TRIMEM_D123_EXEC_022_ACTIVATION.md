# TRIMEM-CODER V1 — D1.23 EXEC `_022` source activation

## Endpoint

```text
TRIMEM_V1_READY_FOR_EXEC_022_REQUEST
```

```text
STATUS = READY_FOR_EXEC_022_REQUEST
REQUEST_021_ATTEMPT_ONE_CONSUMED = true
REQUEST_021_RERUN_ALLOWED = false
REQUEST_022_CREATION_AUTHORIZED = true
REQUEST_022_CREATED_IN_SOURCE = false
REQUEST_022_EXECUTION_AUTHORIZED = false
EXTERNAL_EXECUTION_APPROVAL_RECEIVED = false
DEVELOPMENT_EXECUTION_AUTHORIZED = false
PERFORMANCE = NOT_MEASURED
PASS_AT_1 = null
```

D1.23 is a credential-free, source-only activation package. It records that
the repaired D1.22 source passed its exact-head gates and is eligible for a
fresh EXEC `_022` *request*. It does not create that sentinel and it does not
authorize or start an execution.

## Immutable D1.22 evidence

The activation is rooted at exact D1.22 source commit:

```text
cfa79b2406f174bd152eb873e98018725947d349
```

The committed PASS receipt is:

```text
tests/fixtures/trimem_d123/d122_remote_ci_evidence.json
sha256:0abfc20181ca47e4ada3e1bb847ff91347d1f8d99844157cbb2e5e7e623b9e6a
bytes:2090
```

All six required credential-free workflows passed on that exact head. The
full no-skip suite passed. No benchmark workflow ran, no credential was read,
and no model/API call was made.

```text
ci-trimem-dev-toolchain       run 34277199448 = success
ci-trimem-e2e                 run 34277199438 = success
ci-trimem-grader-loader       run 34277199392 = success
ci-trimem-harness-lock        run 34277199404 = success
ci-trimem-multi-swe-contract  run 34277199345 = success
ci-trimem                     run 34277199507 = success (full no-skip)
```

The D1.22 Qdrant rehearsal also passed on the exact head:

- 6 stream namespaces;
- 12 private/shared collections;
- 72 payload indexes;
- exact Docker HostConfig and PID 1 `nofile=65535:65535`;
- pinned Qdrant 1.12.4 digest
  `qdrant/qdrant@sha256:241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636`;
- owned-container cleanup confirmed absent;
- one support-service image pull, with zero benchmark image pulls;
- zero graders, model calls, tokens, and USD.

## Scientific boundary

EXEC `_021` remains immutable, spent history. It completed only 24 of 72
cells before the Qdrant file-descriptor portability failure. Those partial
cells are not an aggregate, do not select an M2 candidate, do not establish a
campaign score, and will not be resumed or reused by EXEC `_022`. The 24-cell
partial observation is not a benchmark score.

For custody only, immutable EXEC `_021` recorded 247 scientific generation
calls plus one protocol-canary call (248 total), 24 official grader
containers, and `$1.548175950000` total historical USD. The scientific-only
amount was `$1.546621950000`. These spent values are not D1.23 activity and
are not a budget reservation for EXEC `_022`.

Any later, separately approved EXEC `_022` is a fresh 72-cell campaign from
sequence zero. Its frozen maximum remains:

```text
targets                         = 12
streams                         = 6
task-arm runs                   = 72
scientific generation-call cap = 1872
protocol canary call cap        = 1
paid model-call cap             = 1873
grader-container cap            = 72
model                           = gpt-5.4-mini-2026-03-17
reasoning effort                = medium
expected USD                    = 10.80
hard cap USD                    = 50.00
```

The model, pricing, prompts, tools, parsers, targets and target order, arms
and stream order, task/arm budgets, grader locks, and image locks are
unchanged from D1.22.

## D1.23 activation actuals

```text
benchmark image pulls = 0
task-arm runs          = 0
grader containers      = 0
official grader runs   = 0
model/API calls        = 0
paid model calls       = 0
input tokens           = 0
output tokens          = 0
USD                     = 0
```

In short: `paid/model calls = 0` for D1.23.

The historical EXEC `_021` usage remains recorded separately in its immutable
failure fixture and D1.22 recovery documents. It is not relabeled as D1.23
activation usage and is not combined with a future campaign.

## Authority boundary

The exact `_021` attempt cannot be rerun. This package grants only
request-creation authority/readiness for `_022`. The source contains no `_022` sentinel,
no external approval document, and no execution authority. A later sentinel
must be an exact sentinel-only child of this sealed source, and actual
execution still requires its separately bound external approval:

```text
TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_022_APPROVED_ONCE
```
