# TriMem-Coder V1 system and benchmark contract

TriMem-Coder V1 is an online coding-agent memory system with four graph types:
a task-local working graph, a private per-user episodic graph, a private
per-user semantic graph, and a reviewed organisation semantic graph.
PostgreSQL is canonical. Qdrant contains only hash-bound vector references that
must resolve back to canonical PostgreSQL records before use.

This document describes the frozen execution boundary. It is not a benchmark
result. Official grader execution and paid model calls remain separately gated.

## Common coding path

Every causal M0/M1/M2 comparison uses the same selected `RuntimeLock`, model
snapshot, prompts, strict JSON parser, tool surface, step ceilings,
output-token ceilings, checkout factory, and official-grader interface. The
four preregistered development tuning bundles intentionally vary the M2
decomposition prompt and joint memory policy; those runs are tuning evidence,
not arm-comparison observations. The runtime:

1. decomposes the public task into semantic subtask nodes and dependencies;
2. activates exactly one dependency-ready node;
3. recalls memory only for that active node;
4. records byte-exact prompts, responses, public tool observations, edits, and
   memory injections in a hash-chained evidence ledger;
5. may revise the DAG topology when new error, test, symbol, API, or invariant
   evidence reveals additional semantic work;
6. edits a disposable checkout and executes public commands inside the
   target's digest-pinned, network-disabled image;
7. finalizes the patch, crosses the separately gated official-grader boundary,
   extracts success or failure experience without grader payload leakage, and
   stores/credits the outcome; and
8. checkpoints every terminal phase so completed model/grader/lifecycle side
   effects are not silently repeated after restart.

The target gold patch and test patch are never included in the model task,
memory extractor input, or command checkout. Only the final resolved boolean is
available to experience extraction; canonical grader streams and reports are
retained as restricted evidence.

## Memory arms

- **M0 / NO_MEMORY:** explicit abstention; no retrieval or retention.
- **M1 / CURRENT_V03_MEMORY:** the exact live-main v0.3 whole-task search and
  injection path (`validated_search` then `plan_injection`), frozen to the
  live-main base commit. Completed tasks retain the same five-field
  `private_episodes` object as `solve_worker` (`task_id`, `repo_id`, `commit`,
  `outcome`, `injected_memory_ids`) and the same `CONTRACT_CANDIDATE` outbox
  event in one tenant transaction. Current main has no solve-path producer for
  `PRIVATE_INDEX` and no consumer that turns that candidate event into a
  private Qdrant point. A newly completed solve is therefore not immediately
  searchable by the next serial target; the comparator does not repair or
  accelerate that behavior. The matched extraction call still runs, but its
  text and the external benchmark grade do not alter M1 retention. A legitimate
  pre-existing indexed v0.3 `private_note` may be injected through the exact
  current `validated_search`/`plan_injection` path. M1 creates no new shared
  publication and can only read already promoted current shared records present
  in its isolated index.
- **M2 / FULL_TRIMEM_CODER:** private episodic-first recall, private semantic
  then reviewed organisation-semantic backoff, embedding/lexical seeds, and
  deterministic personalised PageRank for each active semantic subtask.

The arms have equal *maximum* compute ceilings, not necessarily equal actual
compute. Every task-arm result records decomposition, solve, and extraction
calls separately, input/cached/output/reasoning tokens, model/tool/grader wall
time, grader calls, containers, and image-digest evidence.

## Retention, consolidation, and isolation

The Double-DQN action space is limited to `FORGET`, `MOVE_TO_EPISODIC`, and
`MOVE_TO_SEMANTIC_CANDIDATE`. Tenant boundaries, ACLs, secret rejection, and
private-to-shared promotion are deterministic server controls outside the
policy. Training and exploration are development-only. Held-out execution
requires the sole post-development frozen checkpoint and uses greedy,
mutation-free policy evaluation.

M2 calls the product deterministic security/privacy scanner before opening any
storage action mask. A blocking finding forces `FORGET`, irrespective of DQN
scores. Reviewed organisation publication runs the same scanner again on the
exact shared view immediately before its canonical write; review authority
cannot bypass a blocking secret or PII finding.

Private episodic and user-semantic queries require the exact organisation,
namespace, and owner scope. Episodes are repository-exact; a semantic record
may cross repositories only when its canonical applicability scope is general
and its repository binding is null. Cross-user transfer is possible only
through reviewed organisation-semantic records. Promotion requires either two
verified supporting episodes from two independent contributors or explicit
trusted-document evidence. Episodic capacity is FIFO. Semantic capacity
archives the lowest canonical strength, including support, successful reuse,
independent-user evidence, recent verification, negative transfer,
contradiction, and version staleness. PostgreSQL changes and Qdrant UPSERT or
DELETE intents use a durable outbox and reconciliation path.

M1 uses the current v0.3 memory-side transaction rather than the TriMem graph
outbox. Its EXTRACTED checkpoint seals the exact pending episode and matching
`CONTRACT_CANDIDATE` event. Restart accepts only a wholly absent pair or an
exact match on every deterministic episode/outbox field from the single atomic
append, while requiring Qdrant and all TriMem
0015 receipt tables to remain unchanged. Row-only, outbox-only, duplicate,
unrelated, or tampered changes fail closed. A post-store agent checkpoint
carries the exact stored descriptor.
The comparator freezes the live-main base commit, its `durable.py` Git blob and
baseline finalizer source hashes separately from the refactored helper,
current finalizer, and `publish_outbox` hashes. The shared connection-level
helper is a behavior-preserving extraction of the current-v0.3 memory side
effects; the common benchmark runtime does not claim to execute the complete
live product finalization pipeline.

## Frozen benchmark plan

The committed selector uses one public seed and deterministic public-identity ranking;
there are no per-slot salts or result-dependent overrides. The development,
held-out, and GOLD/NOOP_BASELINE smoke target sets are disjoint and are generated only
from the exact dataset revisions in the committed source audit.

- development tuning: four preregistered joint M2 bundles, each over the same
  12-task serial stream in a fresh namespace (48 physical runs), followed by
  M0 and M1 over the same 12 targets with the selected prompt (24 physical
  runs); selection is resolved count descending, actual tokens ascending,
  actual USD ascending, then candidate ID ascending. Actual tokens are input
  plus output; Responses reasoning tokens remain separately reported because
  they are a subset of output tokens and must not be double-counted. This is a
  preregistered pooled joint-tuning score over the fixed mixed 12-task DEV set
  (4 SWE-bench Verified and 8 Multi-SWE-bench tasks), not the held-out primary
  endpoint;
- held-out: 27 untouched tasks, one serial online stream per arm;
- official grader smoke: 6 repository-stratified instances, each paired as
  GOLD and the deterministic file-only NOOP_BASELINE, frozen before any result;
- comparison: M0, M1, M2 only; component ablations begin only after the frozen
  full-system held-out result exists.

The selected full policy, byte-exact RuntimeLock, and final selected Double-DQN
checkpoint are emitted after development, reviewed, then committed in a new
research freeze. Held-out execution requires a separate external approval
bound to that new Git commit and freeze. A development approval never carries
over to held-out execution. Held-out M0/M1/M2 all use the selected prompt;
development candidate comparisons must not be reported as component ablations.

The benchmark executor has no free-form instance input. It loads the committed
matrix, validates exact source-row hashes and base commits, pulls only frozen
image digests in the manual workflow, independently inspects observed digests,
and preserves stdout, stderr, reports, raw events, patches, and checkout
evidence. Full dataset rows containing gold/test fields are ephemeral grader
inputs only and are deleted after hash-bound grading; they are excluded from
public artifacts. Raw evidence stays available through aggregation and is then
uploaded only as an encrypted restricted artifact; an always-run scoped cleanup
removes plaintext datasets, harnesses, checkouts, approval material, and raw
results from the runner. Each phase runs serially under one atomic budget ledger;
stream order is not counted as an additional task sample. The plan contains 72
development and 81 held-out physical task-arm runs (153 total), plus 12 grader
smoke containers.

The exact expected cost and independent hard cap are in
`configs/trimem_v1/cost_plan.json`. The dated model snapshot, request envelope,
decoding policy, and retrieval embedder revision are in
`configs/trimem_v1/model_lock.json`. A benchmark run additionally requires an
external immutable approval artifact bound to the committed request bytes, Git
HEAD, research freeze digest, phase, task-arm count, call/token ceilings, and
USD cap. The approval also binds the exact GitHub workflow run ID and run
attempt, so it cannot authorize another dispatch or rerun. The manual benchmark
entrypoint records one normal process attempt and, only on nonzero exit, one
same-run/same-attempt `--resume` attempt; both streams and statuses are retained
and the second failure is propagated.

Before any benchmark model call or task-arm result existed, the common reader
was amended from the full GPT-5.4 snapshot to
`gpt-5.4-mini-2026-03-17` as a cost/performance choice. Decomposition, solving,
and experience extraction all use that one exact Mini snapshot; Nano is not
mixed in. The DEV planning estimate is USD 10.80 and its independent hard cap
is USD 50.00. Target identities/order, M0/M1/M2 and the four joint M2
candidates, prompts/tools/parsers, runtime ceilings, selection, datasets,
grader contracts, and image locks are unchanged. This frozen amendment is
eligibility to request a new external DEV approval, not execution authority;
grader smoke is not rerun.

Every task-arm result records solve/decomposition/extraction/provider/grader
calls, input/cached-input/output/reasoning tokens, model/tool/grader and total
task wall time, frozen-price USD, retrieval and bank-specific injections,
abstentions, retained/archive counts, and net memory growth.
The fail-closed aggregate preserves each target's validated `benchmark_id` and
computes arm-by-benchmark `n`, resolved count, and Pass@1. SWE-bench Verified is
the preregistered primary endpoint; Multi-SWE-bench mini and flash are separate
secondary endpoints. Any all-benchmark stream total is descriptive pooled
accounting and is never reported as the primary result.

## Readiness versus execution

Credential-free CI proves implementation, migration, PostgreSQL/Qdrant
integration, replay E2E, privacy, deterministic PPR, accounting, checkpoint,
freeze, and fail-closed workflow contracts. It does not claim official-grader
viability or benchmark performance. Official grader smoke, development tuning,
post-development checkpoint selection, held-out evaluation, and paid calls all
remain execution-time states and require the separate approved gate.

Automatic pre-EXEC credential-free CI may run only the digest-pinned PostgreSQL
and Qdrant support services needed for real-service integration tests. This is
infrastructure validation, not official grading or benchmark execution. The
approval prohibition applies specifically to official grader/benchmark target
image pull or run, official grader invocation, benchmark task execution, and
paid model calls.

The historical branch-local P0.1.1 grader-smoke trigger admitted only a commit
on `codex/trimem-coder-v1` that changed exactly
`artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_002.json`. The job
was held at the protected `trimem-grader-smoke-exec` environment before any
secret or execution step was available. Its external approval was bound to that
exact commit, freeze, request bytes, workflow run ID and attempt, and zero-model
caps. Ordinary source, configuration, documentation, or workflow pushes could
not start the grader. The retained `workflow_dispatch` path was disabled for
this feature branch and was eligible only on `refs/heads/main` after a later
merge; it was not an alternate P0.1 trigger.

The `_002` recovery amendment is classified
`NON_SEMANTIC_EXECUTION_CONTROL_FIX`: GitHub Actions omits commit
`added`/`modified`/`removed` arrays from its push-event payload, so changed-path
authorization is proven exclusively from the checked-out commit's exact
one-parent graph and `git diff-tree` result. Run `33470431940` and the original
`GRADER_SMOKE_EXEC_REQUEST.json` remain immutable historical evidence. No
benchmark result existed when this event-contract amendment was made, and the
six identities, twelve GOLD/NOOP_BASELINE rows, image digests, target-set hash,
and NOOP patch are unchanged.

P0.1.3 historically reserved the one-time path
`artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_003.json`, schema
`trimem/grader-smoke-branch-trigger/1.2`, and concurrency group
`trimem-v1-grader-smoke-exec-003`. Both earlier request files are immutable
historical inputs. That authorization and path are no longer active; the
corresponding historical trigger and execution evidence remain immutable.

The six-instance smoke is also storage-bounded: for each frozen identity it
pulls and inspects one target digest, executes GOLD then NOOP_BASELINE, and
removes only that exact digest and harness tag before advancing. The frozen
Multi-SWE support image may remain resident only across the contiguous Multi
pairs and is then removed. This preserves one serial campaign while avoiding a
pull-all image cache as an execution prerequisite.

Run `33480195643` attempt 2 proved that approval materialisation, the protected
environment, and the EXEC gate worked. It then stopped in `prepare_harnesses`
before any target image pull or grader execution. The dependency declaration
locks had been computed from a Windows CRLF checkout, while GitHub's Linux
checkout exposed the upstream LF bytes. This is classified as
`TRIMEM_GRADER_SMOKE_HARNESS_LOCK_PORTABILITY_FAILURE`, not as an evaluator,
scientific, grader-viability, or performance result. The P0.1.2 approval
encoding recovery remains valid; strict Base64 decoding remains fail closed.

P0.1.3 locks every upstream harness dependency declaration to the bytes of its
regular Git blob at the exact pinned revision. The single shared reader resolves
the requested path with Git and reads the object database; it never hashes the
platform-dependent working-tree file. A generic declaration list covers all
locked dependency files rather than special-casing the three declarations that
exposed the fault. Production harness preparation and the credential-free
rehearsal call the same validation path.

The exact Linux pre-execution rehearsal uses fresh full checkouts of the pinned
upstream repositories and invokes the production `prepare_harnesses` path to
validate repository origin, commit, cleanliness, Git-blob identity, blob byte
count, and the portable aggregate lock. The Windows row validates the identical
committed objects without materialising Multi-SWE-bench's case-colliding full
tree, which NTFS cannot represent. This object-only row specifically proves the
lock is independent of Windows checkout line-ending conversion; it is not
described as a runnable Windows harness. Both boundaries end before dataset
materialisation, target selection, target-image pull, container creation,
official grading, GOLD/NOOP execution, or any model/API call. Passing them is
portability evidence only; it does not establish official-grader viability and
cannot authorize a grader run.

The immutable P0.1.4 diagnostic campaign is run `33630256522` attempt 1 at
`0e9ed55196da922dcebf1fb33b73940873007180`: six cells were attempted, six
official containers ran, six complete execution-evidence rows were captured,
five cells were adapter-normalized, zero cells became authoritative, and six
cells remained unattempted. Its four target-image pulls (three target plus one
support), six grader calls/runs, and one adapter-contract failure belong only to
that historical window; all model/API/token/USD and task-arm counters were zero.

P0.1.5 freezes Multi-SWE result interpretation as two distinct stages:
`REPORT_VALID=LOCAL_TRANSITION_PREDICATE`, followed by
`FINAL_RESOLVED=REPORT_VALID AND ALL_FROZEN_EXPECTED_TRANSITION_KEYS_COVERED`.
Thus a valid local report with incomplete expected-category coverage is a legal
final unresolved result, and NOOP is defined by that final result rather than
by local validity. Success and failure now use one restricted `_trimem`
evidence envelope; any observed official outcome survives a later adapter
failure while `scientific_resolved` remains null. Each invoked cell gets one
terminal record. Campaign authority is finalized through a content-bound
journal, and an interrupted promotion or rollback is recovered to a canonical
non-authoritative tree. Inventory and encryption are independent of the
authority-recovery outcome, while failure closure requires recovery success or
skip. Plaintext is deleted only after encrypted evidence uploads successfully;
an upload failure preserves plaintext and ciphertext and fails the workflow.

At the P0.1.5 correction source HEAD, the pre-`_005` status was
`TRIMEM_SYSTEM_IMPLEMENTATION=CREDENTIAL_FREE_GREEN`,
`GRADER_EXEC_PACKAGE=CORRECTION_READY_FOR_EXECUTION`,
`ENDPOINT=TRIMEM_GRADER_SMOKE_REPORT_SEMANTICS_RECOVERY_READY`,
`OFFICIAL_GRADER_VIABILITY=NOT_YET_ESTABLISHED`, and
`PERFORMANCE=NOT_MEASURED`, with `DEV_APPROVAL_ALLOWED=NO`. In this distinct
P0.1.5 correction window, target/support image pulls, grader containers,
official grader runs, GOLD/NOOP cells, task-arm runs, model/API calls,
input/output tokens, and USD are all zero. Credential-free green and
correction-ready status do not establish official-grader viability or a
benchmark result. Only the exact later `_005` sentinel-only child and a fresh
run/attempt-bound protected approval may start the one authorized smoke.
`TRIMEM_GRADER_SMOKE_REPORT_SEMANTICS_RECOVERY_READY` is a non-terminal
pre-execution state and becomes accurate only after every local and affected
remote credential-free correction gate is green. The user authorization
identity for the subsequent one-time approval is exactly
`TRIMEM_GRADER_SMOKE_REPORT_SEMANTICS_RECOVERY_EXEC_APPROVED_ONCE`. It permits
only the sentinel-only `_005` child, one protected attempt-1 workflow run, one
manual environment approval, and the twelve frozen zero-model GOLD/NOOP cells.
It does not permit a rerun, `_006`, a model/API call, DEV, HELDOUT, ablation,
target replacement, merge, tag, or release.

That one-time authorization was consumed by workflow run `33674784590`,
attempt `1`, at sentinel-only execution HEAD
`cc001245b8c26373b5467a0dbdcbbbda0a9542be`. The run completed successfully:
all 12 frozen GOLD/NOOP rows were attempted, terminal, official,
evidence-complete, adapter-normalized, and authoritative. GOLD resolved 6/6;
NOOP_BASELINE was unresolved 6/6. Patch application, actual-test execution,
digest matching, and submitted-patch identity were each 12/12. Host
`prepare.sh` reads and source-image builds were zero, and all seven independent
failure-taxonomy counters were zero. The campaign used 12 grader containers,
six target-image pulls, and one support-image pull, while task-arm, model, API,
paid-model, token, and USD counters remained zero.

The current endpoint is
`TRIMEM_V1_GRADER_SMOKE_PASS_READY_FOR_DEVELOPMENT_APPROVAL`, with
`GRADER_EXEC_PACKAGE=PASS`, `OFFICIAL_GRADER_VIABILITY=ESTABLISHED`,
`PERFORMANCE=NOT_MEASURED`, and `DEV_APPROVAL_ALLOWED=YES`. The last field
means only that a separate development approval may now be considered;
`DEV_EXECUTION_ALLOWED=NO` remained the execution boundary at that snapshot.

The first later DEV trigger, `_001`, produced run `33727051040` attempt 1 at
`6eba1b0f9462c3b29323a9ade290470551bfd0ed`, but it was not a scientific or
evaluator run. The secret-free hosted preflight imported the grader/runtime
dependency graph through `trimem_freeze.py` and stopped on missing SQLAlchemy
before the DEV request validator. The protected job was skipped. Deployment,
approval materialization, target/support image pulls, task-arm and grader runs,
model/API calls, input/output tokens, and USD were all zero. Its exact endpoint
is `TRIMEM_V1_DEV_INCOMPLETE`; `_001`, its commit, and its run are immutable.

Recovery identity `_002` is distinct. The hosted job now retains the complete
freeze and request checks while executing both under `python -I -S`; constant
paths in the freeze module no longer import runtime modules. The recovery
freeze binds the `_001` bytes and a sanitized GitHub-evidence failure receipt.
The validator additionally requires the exact `_001` commit and parent, its
sentinel-only tree change, and ancestry into the recovered source.
Only one new `_002` sentinel-only child, one fresh attempt-1 run, and a fresh
run-bound external approval may enter the protected job. A rerun of `_001`, an
attempt 2, an additional DEV execution, HELDOUT, ablation, grader-smoke rerun,
merge, tag, or release remains forbidden.
