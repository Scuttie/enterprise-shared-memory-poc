# TriMem V1 D1.10 — grader launch and stream-commit correction

## Classification and endpoint

`PRE_RESULT_GRADER_LAUNCH_AND_STREAM_COMMIT_CORRECTION`

Credential-free endpoint:

`TRIMEM_V1_GRADER_LAUNCH_AND_STREAM_COMMIT_READY_FOR_DEV_APPROVAL`

This endpoint does not authorize execution. A fresh, explicit DEV execution
approval remains required. Request `_010` and run 34008674563 attempt 1 are
final and immutable; they may not be rerun. `_010` is recorded only as the
historical failed request, not as a recovery request. No fresh execution request
exists and no `_011` request was created; separate explicit sentinel-creation
authority is required before any later execution approval can bind a new request.

## Correct status boundary

- `OFFICIAL_GRADER_SEMANTICS_AND_DISCRIMINATION = ESTABLISHED_BY_P0_1_5`
- `OFFICIAL_GRADER_IMAGE_INTEGRITY = ESTABLISHED`
- `OFFICIAL_GRADER_DEV_RUNNER_PYTHON_LAUNCH = FAILED_ON_D1_9_EXEC_010`
- `OFFICIAL_GRADER_DEV_RUNNER_CONTAINER_START = NOT_YET_ESTABLISHED`
- `PERFORMANCE = NOT_MEASURED`

The broad `OFFICIAL_GRADER_VIABILITY` label is not a current-state field. The
P0.1.5 result established official grader semantics and discrimination, but the
first DEV runner never launched its exact child Python and never started a
grader container.

## Immutable `_010` observation

Run 34008674563 attempt 1 reached one M2-baseline cell. Eight bounded context
projections, one decomposition, and eight solve calls produced a non-empty
partial patch. The exact grader child Python exited 127 because
`libpython3.11.so.1.0` was unavailable in the sanitized loader environment.
The grader adapter was invoked, but no container started, no official grader
run occurred, no `CELL_TERMINAL` result existed, and the canonical cursor stayed
at zero. The correct process disposition is `GLOBAL_GRADER_INFRA_FAILURE`, so a
same-attempt resume is prohibited.

Encrypted restricted evidence and the inventory were verified in external
custody. A public performance artifact is correctly absent because no
scientific terminal cell exists.

## Credential-free correction

D1.10 binds the exact setup-python interpreter to one verified lib directory,
runs the exact harness loader preflight before credentials or images, separates
grader infrastructure state from scientific results, and commits validated cell
result, ledger terminal, and stream cursor through the hash-bound
`trimem/cell-commit-journal/1.0` protocol. Same-attempt resume is permitted only
for explicit durable-suffix or cell-journal recovery dispositions.

The production-runtime checkpoint validator now also requires and verifies the
hash-bound `inventory_sha256` proof field. This is checkpoint-proof schema
hardening only: scientific runtime behavior, model behavior, and every memory
policy remain unchanged.

The correction does not alter model, reasoning effort, targets, target order,
arms, M2 candidates, memory policies, PPR/DQN parameters, output-token pools,
phase caps, grader revisions, or image digests. The amendment and inventory hold
the exact raw-file contract hashes; `artifacts/trimem_v1/freeze.json` remains the
research-state authority. `COMPANY_HANDOFF_MANIFEST.json` remains a separate
product-only inventory and is not used as research status.

Adding the dedicated loader workflow mechanically changes the product
`docs/STATUS.yaml` workflow inventory count from 73 to 74. D1.10 validates that
single-field compatibility change exactly but excludes product STATUS from the
research implementation hash and authority. The company handoff manifest is
not regenerated on this research branch.

The tool-environment lock changes only the raw source identities for
`git_workspace.py` and `production_runtime.py`, reflecting checkout-inventory
and checkpoint-proof hardening. Its prompt, parser, tool, step/token limits,
container policy, runtime-lock manifest, and authority boundary remain
byte-for-byte equal to the immutable `_010` lock.

The credential-free source-to-target E2E bundle is rehashed as byte-stable
preserved evidence; it is not represented as a D1.10 loader or cell-commit
rehearsal. A separately sealed, provenance-bound sanitized `_010` fixture keeps
the external artifact IDs/digests and public failure boundary while replacing
restricted historical patch content with exact safe bytes. Dedicated loader,
that fixture's production-shaped pre-container/wrapper regression, atomic crash-matrix,
resume-disposition, 72-cell fake-campaign, custody, and CI checks gate D1.10;
their observed result is reported only after the final committed remote HEAD
passes those checks.

## Execution counters for this correction

- model/API calls: 0
- paid model calls: 0
- benchmark image pulls: 0
- official grader executions: 0
- USD: 0

No HELDOUT, ablation, merge, tag, or release action is authorized by this
correction.
