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
held-out, and GOLD/NOOP smoke target sets are disjoint and are generated only
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
  GOLD and NOOP, frozen before any result;
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
