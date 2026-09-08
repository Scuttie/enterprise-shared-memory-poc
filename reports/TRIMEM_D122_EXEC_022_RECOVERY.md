# TriMem-Coder V1 D1.22 EXEC-021 Qdrant nofile recovery

## Current endpoint

The current endpoint is
`QDRANT_RLIMIT_NOFILE_PORTABILITY_FAILURE`. The source status is
`FROZEN_CREDENTIAL_FREE_EXEC_021_PARTIAL_SCIENTIFIC_FAILURE_RECOVERY_PENDING_REHEARSAL`.
It is not a benchmark score, not an EXEC-022 request, and not execution
authority. `DEVELOPMENT_TUNING_EXEC_REQUEST_022.json` does not exist and must
not be created without separate request-creation authority.

## Immutable EXEC-021 boundary

- source HEAD: `a171bce0b883d4cc93b893a6d47944a84a947897`;
- execution HEAD: `f83eab1e777f803c08e1ed86baac17c97111c546`;
- request bytes/SHA-256: `51376` /
  `986cfe25514a8bf5594a8047f0bc11edd0419813739dbec02da702ab5da71e75`;
- request Git blob: `994bd4058c45a9988d55c5cabc92b823474ddcf9`;
- request payload SHA-256:
  `1c8104c4f535b1f2a0e0e32d452663301c8d6903bf62828be5be4decc9bfc1e9`;
- source freeze SHA-256:
  `ac0d781deb1d01c4b34d5fd61b0e07f3527b42c2bddcb8f0f4a2575e75dc1cae`;
- workflow run/attempt: `34257490991` / `1`;
- run created/updated: `2026-09-08T17:30:17Z` /
  `2026-09-08T18:39:11Z`.

Attempt 1 exited 1 with the observed disposition `UNKNOWN_FAILURE`. It was not
one of the two same-attempt resume-safe dispositions. The attempts manifest
therefore records `resume_eligible=false`,
`resume_reason=FIRST_DISPOSITION_NOT_RESUME_SAFE`, and
`resume_started=false`. A GitHub rerun would be attempt 2, not the internal
same-attempt resume mechanism. Attempt 2 and rerunning EXEC-021 are forbidden.

## Partial scientific evidence, not a campaign result

EXEC-021 committed 24 terminal cells and 24 matching cell journals:

- `M2-baseline`: 12 finalized cells, 1 resolved and 11 unresolved;
- `M2-precision`: 12 finalized cells, 1 resolved and 11 unresolved;
- `M2-recall`: session identity only; 0 reservations and 0 terminal cells;
- `M2-balanced`, `M0`, and `M1`: not started.

There is no aggregate, selected candidate, public campaign result, or
`Pass@1`. `PERFORMANCE = NOT_MEASURED`. These 24 cells remain immutable
historical evidence and cannot be spliced into a future run, used to select a
partial checkpoint, or combined with another run. Any future authorized
campaign must start at sequence zero with all 72 cells.

## Exact consumed accounting

Scientific work consumed 247 paid/model generation calls: 24 decomposition,
199 solve, and 24 extraction calls. It used 1,533,517 input tokens, 31,616
cached input tokens, 92,850 output tokens including 65,956 reasoning tokens,
and `$1.546621950000`.

The protocol canary separately consumed one paid generation call, 950 input
tokens, 187 output tokens including 157 reasoning tokens, and
`$0.001554000000`.

The whole attempt consumed 248 paid/model generation calls, 1,534,467 input
tokens, 31,616 cached input tokens, 93,037 output tokens including 66,113
reasoning tokens, and `$1.548175950000`. It also made one exact-model metadata
control-plane request, pulled 13 benchmark images, and performed 24 task-arm
runs and 24 official grader container attempts. All outstanding call, token,
task, grader, and USD reservations are zero.

## Evidence custody

Failure custody passed. The restricted encrypted artifact is `10071139505`
(digest
`ea9eea6474133eb59a038f65afd951ee059de4924ed2dc478cffb772f578ac83`),
the evidence-inventory artifact is `10071141433` (digest
`cdf33cee76a96c52ee782d76f5527d0e70204446b3efed10a5207fcb34e252b7`),
and the custody artifact is `10071144170` (digest
`51b059a1d90b408b429ee0e88941866fa2aa6ae5c6ecce226916d9d7cc75b9bd`).
The sanitized failure fixture binds these identities, the 2,534-file
restricted inventory, stream checkpoints, finalization bindings, budget
ledger, attempt streams, and exact accounting without containing credentials
or model content.

## Root cause and narrow correction

The protected environment, approval, exact-model metadata, protocol canary,
model work, and first 24 official grading runs succeeded. The shared Qdrant
container was created without an explicit nofile limit. On this runner,
containerd exposed a soft limit of 1024. After two streams retained four
collections and 24 payload indexes, the first private collection of the third
stream failed while opening its sixth payload index with a Qdrant/RocksDB HTTP
500. This is a global memory-backend infrastructure portability failure, not
a scientific, model, target-image, or official-grader result.

D1.22 changes only the Qdrant service contract: Docker create receives exact
`--ulimit nofile=65535:65535`, and state-bound observation plus state-bound and
state-free cleanup reject `HostConfig.Ulimits` drift before mutation. The
credential-free rehearsal additionally requires exact PID1 soft/hard limits,
then exercises six namespaces, two physical collections per namespace, six
payload indexes per collection, and one deterministic 384-dimensional
reference point per collection with `--pull=never`. It must finish with exact
owner cleanup and zero remaining rehearsal containers.

The model snapshot `gpt-5.4-mini-2026-03-17`, reasoning effort `medium`,
pricing, prompts, tools, parsers, 12 targets and order, six arms and stream
order, budgets, grader locks, and image locks remain unchanged. Source sealing
does not claim the runtime rehearsal passed. Only a separate credential-free
run of the exact sealed rehearsal can establish that fact. Until then, and
until a later explicit authority is received, request creation, paid/model
calls, grader runs, DEV/HELDOUT execution, merge, tag, and release remain
unauthorized.
