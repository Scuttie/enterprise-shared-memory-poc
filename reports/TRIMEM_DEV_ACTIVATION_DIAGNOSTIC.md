# TriMem V1 - post-DEV activation diagnostic

## Status

This is a post-outcome mechanism diagnostic prompted by the zero-injection
result of DEV EXEC-022. It is not an M2 selection run, a held-out estimate, or
evidence for a final performance claim.

```text
TRIMEM_DEV_ACTIVATION_DIAGNOSTIC = EXEC_003_ZERO_SCIENTIFIC_WORK_WORKSPACE_STATUS_FAILURE_PRESERVED
HISTORICAL_ABSTENTION_ROOT_CAUSE = UNIDENTIFIABLE_FROM_RETAINED_EVIDENCE
SOURCE_BANK = FROZEN_VERIFIED_TARGET_DISJOINT_12_OF_12
RECOVERY_IMPLEMENTATION = GIT_INDEX_RENORMALIZATION_REHEARSED_AWAITING_NEW_HEAD_CI
MODEL_EXECUTION = NOT_STARTED
OFFICIAL_GRADER_EXECUTION = NOT_STARTED
PAID_MODEL_CALLS_THIS_DIAGNOSTIC = 0
USD_THIS_DIAGNOSTIC = 0
```

Run `34379166677` attempt 2 passed the protected approval gate, frozen image
materialization, credential-format check, and run-bound billing-key commitment.
The executor then stopped before paid-client construction because one exact
Git-blob-normalized checkout still appeared modified to porcelain status. Both
the initial invocation and its same-attempt resume retry failed closed. The
separate EXEC-003 report preserves the evidence, 13 image-pull accounting, and
zero task/model/grader/token/USD result. Exact Linux reconstruction identified
one ponyc and 30 zstd committed-CRLF paths whose immutable LF blob bytes were
correct while the mutable index/stat state was stale. Literal-pathspec,
tracked-only hermetic renormalization followed by exact commit-tree and
empty-status checks corrects that portability boundary; the corrected
12-target rehearsal passes.

Run `34372037270` attempt 2 is a second spent, zero-work pre-execution
failure. It proved the corrected preinstall path, dataset checkout, pinned
harnesses, official loader, grader factory, and complete failure-custody path.
The approval gate then repeated the same import error because its own command
still used `-S` after the editable installation. The separate EXEC-002 report
preserves the exact evidence and recovery boundary. No image, OpenAI, executor,
or official grader step was reached.

Run `34359716328` attempt 2 is a spent, zero-work preflight failure, not a
scientific or evaluator run. The frozen-source check passed, after which the
uninstalled source package was absent from the isolated import path. The
separate failure report preserves the exact run, evidence, zero-call
accounting, and recovery boundary. The correction changes only execution and
custody plumbing: the scientific matrix, source bank, model, prompts, tools,
parsers, budgets, images, grader locks, and verdict rules are unchanged.

## EXEC-022 retrospective boundary

The accessible public artifact proves 78 recall events, 179 bank-level
abstentions, and zero injections. The stream totals are:

| stream | recall attempts | bank-level abstentions | injections |
| --- | ---: | ---: | ---: |
| M0 | 14 | 14 | 0 |
| M1 | 13 | 12 | 0 |
| M2-baseline | 13 | 39 | 0 |
| M2-precision | 13 | 39 | 0 |
| M2-recall | 12 | 36 | 0 |
| M2-balanced | 13 | 39 | 0 |

The 14 M0 decisions are the intentional no-memory control and are not recall
failures. The M1 totals also show that one selection did not become an
injection, but the accessible aggregate cannot identify its target, subtask,
or post-selection rejection.

The per-cell `events.jsonl` files are inside the encrypted restricted archive.
The custody copy is intact, but the evidence passphrase is not available in
current local or protected-environment custody. More importantly, the old raw
event schema recorded only task/arm/active-node, injections, bank trace, and
post-selection rejections. It never recorded the requested candidate funnel,
raw embedding/PPR scores, threshold snapshot, or a stable recall-attempt ID.

Consequently the original 179 row-level decisions cannot be reconstructed
without inventing data. A deterministic 179-row aggregate projection is now
committed with every requested field: 14 rows preserve only the known M0
no-memory-control classification, while all decision fields in the remaining
165 rows are explicitly `UNKNOWN_NOT_RECORDED_EXEC_022`. Synthetic
`projection_row_id` values are reporting identities, never recovered recall,
target, or subtask identities. See the recoverability artifact and
`artifacts/trimem_v1/dev_activation_diagnostic/exec_022_abstention_projection.json`.

## DQN correction

The frozen DoubleDQN is a post-grade retention policy. Its actions are
`FORGET`, `MOVE_TO_EPISODIC`, and `MOVE_TO_SEMANTIC_CANDIDATE`. It does not
choose recall-time `USE` versus `ABSTAIN`. Fresh diagnostic telemetry therefore
uses `null` for `Q_USE`/`Q_ABSTAIN` and `N/A` for router policy. Historical M0
control rows say not applicable; the other 165 historical projection rows stay
unknown because their original decision snapshots were not retained.

C2 is implemented as `FORCED_SAFE_TOP1`: it shares C1's candidate generation,
canonical reload, and safety filters, then bypasses only the deterministic
confidence and margin admissions. There is no learned or DQN recall-time
router to bypass; C2 does not add one or change the retention DQN.

## Frozen diagnostic shape

The diagnostic uses the exact ordered 12-target DEV manifest and a 3 by 12
matrix:

- C0 - no memory;
- C1 - M2 recall with the current confidence/margin gate;
- C2 - the highest-ranked safe candidate, at most one per subtask and three
  per task, with confidence/margin bypassed.

All arms use the same opt-in adaptive-horizon rule. The base subtask horizon is
8. A successful tool result can earn a four-step extension when the canonical
Git diff UTF-8 byte high-water strictly increases or a recognized test command
first passes. A fresh progress event can earn one further four-step extension,
for a maximum subtask horizon of 16. The existing global 24 solve-call and
24 agent-step ceilings remain binding. Equal limits do not imply equal actual
compute, so every cell records solve/extraction calls, tokens, wall time, and
USD independently.

Extension eligibility and its two-extension allowance are keyed to the active
subtask/node, never pooled into a task-level extension allowance. The canonical
workspace diff/test high-water remains task-wide so identical progress cannot
be replayed by a later subtask.

The reader protocol is the exact `recall` candidate selected by EXEC-022's
frozen DEV rule, not the generic baseline policy. Its policy-file SHA-256 is
`1985ca2cceaa6ebdc02d4bd320b318a47a8144f64bde5ad0da8367c777d3d85c`;
the historical RuntimeLock hash is
`f38dbb148e7c7e0573bfab87400ebb9c0c4a786f888d4315d214fdca289fb581`.
The only registered runtime change is enabling the same adaptive horizon in
all three arms, producing RuntimeLock hash
`c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652`.

## Source-bank execution boundary

A fresh empty namespace plus twelve targets from eleven repositories cannot
measure a forced-memory upper bound reliably. C1 and C2 therefore require the
same immutable, read-only bank of independently verified, target-disjoint
source fixes before target 0. C0 performs no retrieval and no injection. Bank
coverage is measured from C2's safe candidate pool before its score-admission
bypass.

Before diagnostic outcomes, the frozen source-selection plan maps each target
to one different same-repository public merged PR. This fixed mapping is not an
automatic admission: each PR must still satisfy every chronology, version,
provenance, and safety check, and a rejected PR remains an uncovered target
rather than being replaced post hoc.

The bank must prove, for every source record:

- a canonical public source-PR row and exact source-row hash;
- a different source PR from every DEV target solution PR;
- source-owned issue/fix content only, never target gold, target tests, or
  target-derived memory;
- repository, path, permission/tenant, provenance, quarantine, and leakage
  eligibility;
- a public source-fix time and target-version compatibility/ancestry result;
- immutable canonical payload and index digests;
- at least one independently verified source record overall; a target with no
  safe candidate remains an explicit `NO_SAFE_CANDIDATE` assignment.

The runtime-facing metadata is exact: `PUBLIC_READ`, `BENCHMARK_ISOLATED`,
`EXACT_SOURCE_COMMIT`, and wildcard `**` path scope. Source `changed_paths` are
retained separately for overlap evidence and deterministic ranking.

The dedicated manifest is now frozen at raw SHA-256
`8a0600e8d18f5234bd35d675f8e5cb8eb827aac4e4498547db02fc689a83d309`;
its logical snapshot SHA-256 is
`55fe3c03ef545181986605166247f78896c5fcd2db37535d19f574781c16be1e`.
The pre-execution source-selection plan raw SHA-256 is
`10e9e6937926e148eaedce73aa3f3cfea0538744b594968d91eca13c597763ff`,
and the final public chronology-cache raw SHA-256 is
`44aa296a75fa7e985d825c1439b2724a297a0c3b2138447f0b6b4a1215246a10`.
All 12 targets have exactly one safe frozen assignment, with zero uncovered
targets. Each assignment is hash-bound to the exact runtime public instruction
from its pinned benchmark row and to the true public problem object: eleven
GitHub issues that lack a `pull_request` member and Django Trac ticket #32603.
The instance-ID suffix is treated only as the target solution-PR identity and
is never used as the target issue number. The chronology cache and all 60
public raw responses (59 GitHub plus one Trac page), together with 12 dedicated
payloads, are content-addressed and included in the explicit research freeze.
Execution remains blocked until the corrected exact head has passed CI and a
fresh exact run-attempt approval passes.
Partial coverage remains a valid execution shape for future rebuilt banks, but
anything below 12/12 takes verdict precedence as
`RETRIEVAL_BANK_COVERAGE_INSUFFICIENT`.

Every one of the 36 solver workspaces is fetched at its exact base SHA and then
reduced to a single-commit Git object closure before a paid client exists.
Committed CRLF checkout transforms are replaced with immutable Git-blob bytes;
only those transformed tracked paths are then renormalized to refresh index
checkout state, with `write-tree` required to equal the pinned commit tree and
porcelain required to be empty. The credential-free 12-target rehearsal
enforces that status before an execution approval can lead to paid work.
Branches, tags, remotes, reflogs, alternates, promisor state, and unreachable
post-base objects are removed and audited. The production solver runner keeps
networking disabled and exposes only that checkout. For Multi-SWE images it
also masks the baked repository Git database and the evaluator-generated
`fix.patch`, `test.patch`, and five harness scripts. A zero-model rehearsal
starts the exact runner for all 12 targets and fails closed unless the base-only
history, empty masks, and secret-free container environment are observed.
Docker/Git subprocesses use fixed non-secret environments, and the OpenAI HTTP
client does not inherit host proxy or TLS environment routing.

The separate execution workflow is now wired without granting that approval:
the exact feature-branch push is a clean, credential-free attempt-1 run/head
handshake, and only a rerun of that same run as exact attempt 2 can enter the
existing protected benchmark environment. This push contract avoids relying
on branch-only `workflow_dispatch`, which GitHub does not expose until a
workflow exists on the default branch. Before the approval
secret is read, that job verifies the frozen contract, DEV dataset/checkouts,
pinned harnesses, official loader, and grader factory. Its ephemeral runner
requires the unique `trimem-dev-activation-diagnostic` label and omits the
historical `trimem-benchmark` label, so the two protected workflow families
cannot select one another's runner. After a fresh exact
approval passes, it verifies digest-only image materialization, exposes the API
key only after its HMAC commitment matches the diagnostic ID, exact head,
source-bank manifest, run ID, attempt 2, model snapshot, and nonce, and then
runs a live image digest reinspection, compiles all 12 source-store views,
prewarms the pinned 384-dimensional retrieval embedder, and then runs the 36
cells serially. The run-bound approval may live for at most seven
days, covering the 120-hour job ceiling without opening an attempt-3 route. A
single retry stays inside attempt 2 and uses the durable
resume binding when it exists; attempt 3 is not an execution route. Within a
cell, the grader may retry exactly once only after an explicit pre-container
failure and durable authorization/process-start markers. A started or unknown
grader process is never invoked again and consumes one container
conservatively.

The budget ledger must finalize exactly 36 terminal task keys with no
outstanding reservations. The complete aggregate is then recomputed and
byte-compared before publication.
Restricted stdout/stderr, per-cell reports/checkpoints, raw provider/grader
evidence, approval binding, and image evidence are inventoried, encrypted, and
uploaded. Every protected-job shell uses `umask 077`, so intermediate evidence
remains owner-only even when a later custody step fails. Images are removed
through the exact frozen-alias cleanup contract,
and plaintext is removed only after remote artifact custody is verified.

## Frozen execution caps

The 36 scientific cells permit exactly one decomposition and one extraction
call per cell, at most 24 solve calls per cell, and therefore at most 936 model
calls in total. The protocol canary is outside this request and is frozen at
`authorized=false`, cap 0. Aggregate hard caps are 18,000,000 input tokens,
2,359,296 output tokens, 36 official grader containers/runs, an uncached token
ceiling of `$24.116832`, and a total USD cap of `$25.00`.

## Interpretation

This experiment jointly changes memory routing and permits arm-dependent
adaptive extensions after progress. It is a descriptive
`memory-routing + adaptive-horizon` diagnostic, not a pure content effect.
Coverage insufficiency takes precedence over score comparisons. Negative and
offsetting target flips are reported explicitly. For offsetting zero-net flips,
the primary verdict remains the user-specified no-lift label and the mixed
pattern is preserved as a secondary label. The verdict uses the fail-closed
diagnostic outcome: an official grader pass counts only when no solve/runtime
or extraction model failure occurred. The raw official-grader solved count and
Pass@1 are reported separately. `CURRENT_ROUTER_ACTIVATED_POSITIVE` additionally
requires a C1-positive target flip on a target that actually received a C1
injection; an injection and a positive flip on disjoint targets are not treated
as causal activation evidence.

No HELDOUT run, component ablation, model change, benchmark generation, or
official grading has been performed during this implementation stage.
