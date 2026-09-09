# TriMem DEV activation diagnostic contract

## Current endpoint

`POST_DEV_ACTIVATION_DIAGNOSTIC_PRE_EXEC_READY_AWAITING_EXTERNAL_APPROVAL`

This is a post-DEV diagnostic contract, not a development-selection rerun, a
HELDOUT result, or a performance claim. No model, image, grader, or benchmark
executor is authorized by this change.

The historical `_022` sentinel at the selected-recall execution head is now
selection evidence only. This diagnostic commit is its descendant, so the old
DEV request remains fail-closed for approval and execution and cannot authorize
the new 36-cell diagnostic. Static readiness verifies the immutable historical
sentinel as an unchanged ancestor; production requires the separate diagnostic
approval bound to this new exact head/run/attempt.

The production path is nevertheless connected and fail closed. The exact
feature-branch push run's attempt 1 is a credential-free handshake that
publishes only the run/head coordinates and reports zero calls. Only an exact
rerun of that same run as attempt 2 may enter the existing protected
`trimem-benchmark-exec` environment on the benchmark self-hosted runner. This
does not depend on branch-only `workflow_dispatch`, which is unavailable before
the workflow exists on the default branch. It installs the hash-locked environment, rehearses the exact DEV
dataset/checkouts, materializes the pinned harnesses, and verifies the official
loader and grader factory before reading an approval secret. The strict gate
then writes the byte-identical validated approval to a mode-restricted temporary
file. The approval contains only an HMAC commitment to the billing key, bound to
the diagnostic ID, exact head, source-bank manifest, run ID, attempt 2, model
snapshot, and nonce; the protected key must verify that commitment before use.
Its maximum lifetime is seven days, long enough for the 120-hour job ceiling but
still bound to this one head/run/attempt. Digest-locked images are pulled and
observed before the API credential is made available, and the production
executor runs the exact serial 36-cell matrix. One same-attempt retry may resume
only the bound durable checkpoint;
attempt 3 and later remain unauthorized.

Before constructing a paid model gateway, the executor materializes all 36
fresh workspaces as exact base-only, one-commit Git object closures. It then
runs the production solver sandbox once for each target. The rehearsal proves
that no target-history refs, remotes, reflogs, or unreachable objects are
available; for Multi-SWE images it additionally masks the baked repository
`.git`, `fix.patch`, `test.patch`, and the five evaluator scripts. Host secrets
are removed from every Docker/Git child-process environment, and the paid HTTP
transport is pinned to `trust_env=false` so proxy/TLS environment variables
cannot silently redirect credential-bearing traffic.

The external approval is produced by the pure
`trimem_dev_activation_approval.build_approval_document` helper, not assembled
by hand. It computes the commitment with the existing OpenAI credential helper
and returns a self-validated document. The operator writes only its canonical
UTF-8 JSON and strict base64 bytes with Python `Path.write_bytes`; neither form
contains a BOM, whitespace, or trailing newline.

The executor's aggregate is independently recomputed and byte-compared. Cell
stdout/stderr, reports, checkpoints, raw provider/grader evidence, approval
binding, image pull/inspection, and image-cleanup evidence are inventoried and
encrypted. Every protected-job shell applies `umask 077`, including failure
paths, so intermediate evidence is owner-only before encryption. Public output
is limited to the complete aggregate. Plaintext is
removed only after artifact upload and remote-custody verification succeed;
otherwise cleanup fails closed and preserves the recovery material.
An explicit `container_started=false` grader failure authorizes one inline
retry only after `PRECONTAINER_RETRY_AUTHORIZED` and
`GRADER_RETRY_PROCESS_STARTED` are durably journaled. Unknown or
container-started failures are conservatively charged once and never retried;
a second explicit pre-container failure is terminal with zero containers used.
The ephemeral runner requires the unique
`trimem-dev-activation-diagnostic` label and deliberately lacks the historical
`trimem-benchmark` label, preventing either workflow family from selecting the
other family's protected runner.

## Frozen comparison

The exact existing 12-target DEV set and order are reused in three arm-major
streams (36 cells):

- C0: `NO_MEMORY`
- C1: `M2_RECALL_CURRENT_GATE`
- C2: `M2_RECALL_FORCED_SAFE_TOP1`

C1 and C2 must begin with fresh writable overlays and the same deterministic,
read-only source-bank preload. C2 preserves leakage, permission, tenant,
repository, path, version, provenance, quarantine, self-task, context-budget,
and task-injection gates. It bypasses only the two frozen score-admission
checks. There is no learned or DQN recall-time router hook in this
implementation. The current DoubleDQN controls retention, not recall;
therefore `Q_USE` and `Q_ABSTAIN` are truthfully `null` and `router_policy` is
`N/A`.

All arms use the same adaptive horizon: 8 base steps per subtask, a four-step
extension after new durable patch/test high-water evidence, at most two
extensions per subtask, and a 16-step per-subtask ceiling. The global 24 solve
call ceiling remains binding. Equal maximum budgets are not described as equal
actual compute; calls, tokens, USD, and wall times are recorded for every cell.
Extension eligibility and its two-extension allowance are keyed to the active
subtask/node, never pooled into a task-level extension allowance. The canonical
workspace diff/test high-water remains task-wide so identical progress cannot
be replayed by a later subtask.

The common reader is explicitly the `recall` policy selected by EXEC-022's
frozen development rule. The retained public result is bound by SHA-256
`a983bcd807d80520349942d296d8b4910bf7c5eb4f1079185aca1937adacd9a1`;
the selected policy-file hash is `1985ca2cceaa6ebdc02d4bd320b318a47a8144f64bde5ad0da8367c777d3d85c`.
Its historical RuntimeLock hash is `f38dbb148e7c7e0573bfab87400ebb9c0c4a786f888d4315d214fdca289fb581`;
enabling only the identical diagnostic adaptive-horizon rule yields
`c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652`.
No candidate was reselected for this post-outcome diagnostic.

## Fail-closed evidence and verdict boundary

Aggregation requires exactly one known official-grader result for every frozen
cell. Missing, duplicate, unknown, nonterminal, ungraded, or unbound cells stop
aggregation. Individual model/runtime failures remain unresolved, are graded
using their partial patch or canonical no-op, and do not stop later cells.

Candidate coverage has verdict precedence and is sufficient only if all 12 C2
targets have at least one candidate after the preserved safe filters. The
frozen verdicts distinguish current-router lift, forced-memory positive lift,
negative transfer, no lift, and insufficient coverage. When opposite target-level
flips cancel to a zero net score, the primary verdict remains
`FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED`; the report retains
`FORCED_MEMORY_MIXED_ZERO_NET` only as a secondary label.
Verdicts use the fail-closed diagnostic outcome, while official grader solved
counts and Pass@1 are shown separately. The current-router-positive label also
requires at least one C1-positive target flip on a target with an actual C1
injection, preventing attribution from disjoint injection and outcome events.
One or more verified source records are enough to execute; uncovered targets
run with `NO_SAFE_CANDIDATE`, and coverage below 12/12 forces the insufficient-
coverage verdict rather than aborting the 36-cell matrix.

Every compiled record must also match the runtime safe-pool metadata exactly:
`permission_scope=PUBLIC_READ`, `tenant_scope=BENCHMARK_ISOLATED`,
`version_scope=EXACT_SOURCE_COMMIT`, and `path_scope=**`. Canonical
`changed_paths` stay a separate evidence feature; they are not substituted for
the runtime path-scope field.

## Historical and source-bank findings

The retained public EXEC-022 evidence preserves the aggregate 179 abstentions,
but the encrypted row-level archive is not decryptable under current custody.
The deterministic 179-row historical projection carries every requested field
without inventing row identities: 14 rows preserve only the known M0 control
classification and all requested decision fields for the remaining 165 rows
are `UNKNOWN_NOT_RECORDED_EXEC_022`. Synthetic projection row IDs are not
recovered recall, target, or subtask IDs. M0 no-memory abstentions are
intentional controls, and the retention-only DQN cannot truthfully be labeled
as selecting recall abstention.

No committed existing source-bank artifact is directly admissible. The P6
manifest is only a summary whose record payloads depend on an external parquet.
The richer actionable-memory artifact contains 183 verified DS-1000 Python
facts with zero exact DEV target-ID overlap, but lacks repository/commit/time
and safety-scope bindings and cannot cover the non-Python DEV targets. It is
conversion/audit input, not an execution-ready bank.

The pre-execution source-selection plan now fixes one same-repository public
merged PR for each of the 12 DEV targets before any diagnostic result exists.
That mapping is only a candidate universe: each PR still must pass public
chronology, merge-diff, version, provenance, and runtime safe-pool validation.
An ineligible or unavailable PR produces an explicit zero-candidate assignment;
it is never replaced after results are observed.

The dedicated source bank is now materialized with 12/12 target coverage and
zero uncovered assignments. The manifest raw SHA-256 is
`8a0600e8d18f5234bd35d675f8e5cb8eb827aac4e4498547db02fc689a83d309`;
the logical snapshot SHA-256 is
`55fe3c03ef545181986605166247f78896c5fcd2db37535d19f574781c16be1e`.
The frozen source-selection plan raw SHA-256 is
`10e9e6937926e148eaedce73aa3f3cfea0538744b594968d91eca13c597763ff`,
and the final chronology-cache raw SHA-256 is
`44aa296a75fa7e985d825c1439b2724a297a0c3b2138447f0b6b4a1215246a10`.
Each assignment is hash-bound to the exact pinned-row runtime public
instruction and the true problem publication: eleven non-PR GitHub issue
objects and Django Trac ticket #32603. Benchmark instance suffixes remain
solution-PR identities only; they are not used as issue numbers. Its chronology
cache, 59 content-addressed raw public GitHub responses, one Trac page, and 12
dedicated immutable payloads are included in the explicit freeze allowlist.
Full execution remains fail closed until an attempt-1 credential-free handshake
has established the run ID and a fresh attempt-2, run/head/hash/cap-bound
external approval is installed.

## Frozen execution budget

The only authorized scientific ceiling is 936 model calls across 36 cells:
36 decomposition calls, at most 864 solve calls, and 36 extraction calls.
Each cell has the same maximum 26-call, 500,000-input-token, and
65,536-output-token limits, but actual compute remains separately recorded.
Aggregate caps are 18,000,000 input tokens, 2,359,296 output tokens, 36 official
grader containers/runs, an uncached price ceiling of `$24.116832`, and a hard
USD cap of `$25.00`. No canary is authorized; its cap is 0.

## Credential-free accounting

- Model/API calls: 0
- Official grader runs: 0
- Paid model calls: 0
- USD: 0
