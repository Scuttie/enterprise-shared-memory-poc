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

## Credential-free Multi-SWE seal-layer closure

Fresh exact-head gates on source
`6493305b88fdf95bc41d58c1824288bbd3d20b7f` completed with nine successes and
three failures. Push runs `34115936679` (Multi-SWE contract) and `34115936726`
(static CI), plus pull-request run `34115943067` (general CI), all exposed the
same stale-seal defect. Run `34115936679`, attempt `1`, stopped in the
credential-free `Verify required Git blobs and pinned control flow` step. The
verifier still required the D1.10 byte identity for
`scripts/trimem_benchmark_matrix.py` even though D1.12 had changed only that
validator's active sentinel import and had sealed its new bytes in both the
D1.12 amendment and inventory. The image probe did not execute. Model/API
calls, grader containers, official grader runs, benchmark image pulls,
task-arm runs, tokens, paid calls, and USD remained zero.

The immutable Multi-SWE lock and the D1.8, D1.9, and D1.10 artifacts remain
byte-for-byte historical evidence. The verifier now layers the D1.12 amendment
and inventory as an exact current-generation override only for
`scripts/trimem_benchmark_matrix.py`; the other three executable local
validators remain bound to their D1.10 seals. A missing, mismatched, or extra
D1.12 local-validator override fails closed. This source correction still
requires fresh exact-head credential-free CI before `_012` may be created.

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
- two fresh ephemeral, update-disabled repository runners have the
  repository-specific labels
  `trimem-ubuntu-24.04` and `trimem-benchmark`, distinct names and roots, exact
  Ubuntu/Python/Docker/image observations, zero containers, and no protected
  secret in the preflight environment;
- both `.runner` records must carry exact JSON booleans `ephemeral: true` and
  `disableUpdate: true`;
- every Windows-to-WSL observation uses the explicit unprivileged prefix
  `wsl -d TriMemRunner2404 --user trimem-runner --exec`. The explicit execution
  option preserves all trailing argv entries, including positional parameters
  supplied after a `sh -c` program, across the native Windows transport. An
  absolute `/usr/bin/id` probe must report the exact UID/GID/user tuple
  `1000:1000:trimem-runner`, and the bounded and protected Linux observations
  independently recheck the same process identity;
- Actions Runner is frozen at version `2.337.0`. Its source archive is exactly
  `/opt/trimem-runner-cache/actions-runner-linux-x64-2.337.0.tar.gz`,
  `226430031` bytes, SHA-256
  `70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613`;
- each runner root's `bin/Runner.Listener` must report version `2.337.0` and
  match `72568` bytes plus SHA-256
  `f4584cf5ef53ebc8507e9edfad07973e389ff6488906a1abe5f698aa86b295cf`;
- before `actions/setup-python`, each self-hosted job verifies the direct,
  regular, non-symlink, zero-byte toolcache completion marker
  `/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64.complete`
  with empty-file SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
- in both the pre-setup probe and `actions/setup-python` step, the workflow
  forwards `${{ runner.tool_cache }}` as `RUNNER_TOOL_CACHE`. Its exact string
  must be the active runner root's `_work/_tool` path; that path must be a
  symlink resolving to the direct, non-symlink central directory
  `/opt/trimem-runner-cache/work-ci/_tool`;
- source CI gates and runner observations are embedded before the sentinel is
  written. The hosted branch trigger rechecks current PR, source-workflow, and
  remote runner-registration identity; the bounded self-hosted preflight
  separately rechecks the local runner-host state before protected execution.

The request-creation gate requires two live listeners, one in each frozen
runner root. Once GitHub dispatches the protected serial job, its live
observation instead requires exactly one active listener mapped to the current
runner name and workspace. It permits at most one second listener only when it
is mapped to the other exact root during ephemeral teardown. That protected
observation deliberately supersedes the age of the embedded source snapshot;
it does not waive any identity, binary, environment, image, container, or port
check.

## Protected cache-only runtime

The protected job does not delegate service creation to native Actions job
services. Its initial steps are adjacent and frozen in this order: checkout,
pre-setup toolcache verification, `actions/setup-python`, protected live-runner
re-observation, cache-only service start, cache-only service verification, then
hash-locked dependency installation. The final workflow step is an
`if: always()` exact service cleanup. No other tracked workflow may carry the
complete protected custom-label set.

Docker authority is local and closed:

- client and server are both exact Docker `29.1.3`; the client is the frozen
  root-owned mode-`0755` `/usr/bin/docker` payload, exactly `31369824` bytes
  with SHA-256
  `7ed12b00293d64742419a6601ae97960a367a0ce97c88b06e3278cc0a409557b`,
  and every command selects only `unix:///var/run/docker.sock`;
- the daemon root must be exactly `/var/lib/docker`; every environment name in
  the case-insensitive `DOCKER_*` namespace is rejected rather than inherited;
- there is no registry login, manifest request, image pull, or native job
  service. Container construction uses only `docker create --pull=never` after
  the already-cached digest reference and local image ID agree.

The two service locks and runtime bindings are exact:

- PostgreSQL is
  `postgres@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412`
  on loopback `127.0.0.1:5432`, with database `trimem_benchmark`, user and
  password `postgres`, and health command
  `pg_isready -U postgres -d trimem_benchmark`;
- Qdrant is
  `qdrant/qdrant@sha256:241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636`
  on loopback `127.0.0.1:6333`, with readiness proven only by a bounded HTTP
  `GET /readyz` returning `200`;
- both loopback ports must be free before creation. Readiness has one true
  120-second monotonic wall-clock deadline that includes Docker command and
  HTTP probe time, with a two-second maximum polling interval.

Names and custody are run-bound. Each container name and all object labels bind
the role, workflow run ID, source commit, and sentinel commit. PostgreSQL alone
gets the named volume `trimem-d112-{run_id}-postgres-data`, mounted only at
`/var/lib/postgresql/data`; Qdrant gets no mount. The pre-existing volume set is
recorded as the baseline. The service state is canonical UTF-8 JSON plus one LF,
created exclusively as a direct, single-link, UID/GID `1000:1000` mode-`0600`
file and read with no-follow plus before/open/after inode checks. Partial start
rolls back only exact objects and restores the baseline. Final cleanup is
retry-safe: it accepts only the owned state-bound subset or exact absence,
removes the named volume when present, verifies the original baseline, and then
removes the unchanged state file.

Before request creation, the same verified observer obtains one complete,
paginated, transition-safe snapshot of the benchmark workflow. Every row has a
unique run ID plus the exact workflow path and one recognized status; none may
be `in_progress`, `pending`, `queued`, `requested`, or `waiting`. This five-state
active-consumer check occurs both before remote evidence collection and again
immediately before the exclusive sentinel write.

The `_012` request semantic order separately binds pre-setup cache proof,
protected live-runner re-observation, cache-only service start and verification,
and final always-cleanup around the existing approval, credential, model,
grader, and evidence phases. Creating or probing these two credential-free
service containers is not a grader container, benchmark image pull, task-arm
run, model/API call, token use, paid call, or grant of execution authority; all
activation counters remain zero.

## Cross-platform GitHub observer

The request writer and hosted preflight use the same verified GitHub CLI
transport for current-PR, workflow-run, execution-run, and repository-runner
API observations. There is no unverified `gh` fallback and no version-only
acceptance:

- Linux AMD64 uses the existing exact release-archive and extracted-binary byte
  locks;
- Windows AMD64 uses the exact official `gh_2.97.0_windows_amd64.zip` archive
  hash and byte count, then independently verifies the extracted absolute
  `gh.exe` hash and byte count before any observer API call. The basename
  identity is compared case-insensitively so the normal Windows `gh.EXE`
  spelling resolves to the same canonical executable without weakening the
  absolute-path or byte checks;
- unsupported platforms, renamed or non-absolute Windows executables, byte
  drift, version-output drift, malformed locks, and observer transport
  substitution fail closed;
- the active D1.12 reader requires the amended `trimem/gh-cli-lock/1.1`
  schema. The shared retired `_005` compatibility validator now imports that
  schema identity from the pinned-GitHub-CLI consumer when it inspects the
  current tree. It accepts `trimem/gh-cli-lock/1.0` only for an immutable
  historical Git blob that has no `windows_observer`; this compatibility does
  not reactivate the `_005` request route;
- the D1.12 report itself is explicitly Git-attribute pinned to LF so its
  freeze hash is identical on Windows and Linux checkouts;
- only eventually consistent current-PR head visibility and current `_012`
  workflow-run visibility use bounded polling. Each loop has one true
  30-second monotonic wall-clock deadline starting before its first API
  command, so API command time counts against the bound; the 2-second interval
  is clamped to the remaining time rather than multiplied into a separate
  nominal budget;
- PR-head retry accepts only an explicitly supplied immediate predecessor of
  the expected head. Any other well-formed SHA is contradictory and fails on
  its first observation. Current-run rows with a visible ID other than the
  exact `GITHUB_RUN_ID` likewise fail immediately;
- source-gate and runner-set evidence never poll. Malformed or contradictory
  identity, duplicate or rerun workflows, red gates, and missing, stale, busy,
  or offline runners fail immediately. Deadline exhaustion is a pre-execution
  failure and cannot be converted into success.

The Windows-to-WSL readiness probes for the exact Python version, listener
identity, and per-runner configuration all use `env` with the exact
`LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib`
assignment before the frozen Python executable. The library path is derived
only from the exact Actions tool-cache Python root. The outer WSL launch always
selects `TriMemRunner2404`, explicit user `trimem-runner`, and explicit
`--exec`; it never relies on the distribution's default user or the ambiguous
bare separator transport. There is no host-environment fallback.
Both persisted runner `.env` files and both live `Runner.Listener`
environments must contain exactly one `LD_LIBRARY_PATH` binding with that
value; a missing, duplicate, malformed, or different binding fails closed.

## Public entrypoint and pre-write custody

Every repository-taking public entrypoint requires its argument to resolve to
the exact Git top-level, not merely a nested worktree directory or a path that
contains a `.git` ancestor. Before any sentinel bytes are created, the writer
rechecks all mutable local preconditions after the remote observations:

- exact Git top-level and expected branch;
- unchanged source `HEAD`;
- clean tracked and untracked worktree;
- `_012` absent from both history and filesystem, including a dangling symlink.

If any condition changes during gate or runner observation, the writer exits
without creating the sentinel. The exclusive binary create remains the final
operation, so a concurrent sentinel creation also fails closed.

The observer amendment is credential-free. It performs no benchmark image
pull, grader run, task-arm reservation, model call, token use, or paid action.

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
