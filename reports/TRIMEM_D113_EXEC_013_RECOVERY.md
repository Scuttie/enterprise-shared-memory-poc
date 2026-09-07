# TriMem-Coder V1 D1.13 `_013` recovery source

## Outcome

GitHub Actions run `34128541859`, attempt `1`, is spent and immutable. It
failed in the hosted `branch-trigger-preflight` job before either self-hosted
job was assigned and before the protected environment was requested or
entered. The bounded-context and frozen serial jobs were skipped.

The observed execution counts are all zero: benchmark-image pulls, grader
containers, official grader runs, task-arm runs, model/API calls, input and
output tokens, terminal cells, paid calls, and USD. No development performance
result exists, and Pass@1 remains undefined.

The current recovery endpoint is:

`TRIMEM_V1_READY_FOR_EXEC_013_REQUEST`

This endpoint permits only the later creation of one zero-authority
`DEVELOPMENT_TUNING_EXEC_REQUEST_013.json` sentinel after fresh exact-head CI
and runner-readiness checks. It is not protected execution approval and is not
a benchmark result.

## Immutable `_012` boundary

D1.13 preserves the previous request from Git objects, not from a rewritten
working-tree copy:

- source commit: `9db94e2a4abfaad0bb27079738b77836d68fa2e4`;
- execution commit: `491d1022fe079d182d7b453c48083c486936dcb2`;
- execution parent: the exact source commit above;
- only execution-commit change:
  `artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_012.json`;
- Git mode and blob: `100644` and
  `f4111cfd1a26b4099f0b0fdc4dd840d4de21764f`;
- raw byte count and SHA-256: `20561` and
  `6691a24bf488a79b4e1843a129d3d8773090fe2654828534c35eeecc22cc9d38`;
- embedded request self-hash:
  `efa99c554fbae9bbeb8a87536365fcfc6afa54e6ee48de17ef9ffdb0eb72132b`;
- source-freeze SHA-256:
  `3bbafc53504b45c20996094d96a6abfa5fd9e90c5b078eb2f1dc3f1f6d7ad5b4`;
- workflow run: `34128541859`, attempt `1`.

The raw-file digest and embedded request self-hash are distinct identities and
remain recorded separately. D1.13 does not edit `_012`, create attempt `2`, or
rerun its workflow SHA. The old execution approval, if any was prepared, is
not valid for another commit, request, run ID, or attempt.

## Frozen failure evidence

The sanitized offline fixture freezes the allowlisted workflow-run, job,
step, and normalized error evidence. Its exact failed step is `Verify one-time
zero-authority DEV trigger`; the normalized direct error is `runner readiness
command failed: GitHub repository runners`. The failure classification is
`HOSTED_GITHUB_TOKEN_REPOSITORY_RUNNER_LIST_COMMAND_FAILURE`, under the D1.13
recovery subtype `HOSTED_GITHUB_TOKEN_RUNNER_LIST_AUTHORIZATION`.

The fixture contains no raw log, authorization header, environment block, or
credential. The fail-closed gate validator checks exact run, job, step,
timestamp, conclusion, head, source, sanitization, and projection digests.
Changing a field without changing code fails; changing code requires a new
reseal and fresh exact-head CI.

## Hosted-token observation boundary

The hosted branch job's `GITHUB_TOKEN` is not repository-runner inventory
authority. Workflow `permissions: actions: read` is not a grant of the
repository-administration authority required to list repository self-hosted
runners. The `_012` branch reader attempted that observation and the command
failed. D1.13 does not convert a 401, 403, 404, empty response, or command
failure into a valid runner set, and it does not broaden workflow token
permissions.

The corrected custody split is:

1. Before the sentinel is written, the external credential-free request
   writer observes the exact repository runner registrations and the local
   host. It freezes that writer-time snapshot, observation time, source HEAD,
   runner names, IDs, labels, roots, listener identities, and zero-activity
   state into the request.
2. The hosted branch preflight validates the immutable request, source-to-
   sentinel Git edge, source gates, current PR, workflow run identity, and the
   embedded snapshot. It does not call the repository-runners endpoint with
   `GITHUB_TOKEN`.
3. The bounded self-hosted job performs a live, event-bound local attestation
   of its actual runner name, root, listener, UID/GID, Python/tool cache,
   Docker endpoint, cached image identities, empty container set, ports, and
   forbidden-secret absence before dependency or harness materialization.
4. The protected serial job independently re-observes the live assigned runner
   before cache-only service creation. It still requires the distinct exact
   external execution approval before any model, image, grader, or task work.

The writer-time snapshot is provenance, not a permanent liveness claim. The
bounded and protected observations are the live checks. Conversely, a local
live observation does not replace the writer-time repository registration
snapshot. Both layers are required, and an unknown or contradictory value
fails closed.

## `_013` zero-authority contract

The new identity is:

- request ID: `TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013`;
- request path:
  `artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_013.json`;
- schema: `trimem/development-tuning-branch-trigger/1.13`;
- concurrency group: `trimem-v1-development-tuning-exec-013`;
- required later approval:
  `TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_013_APPROVED_ONCE`.

The branch trigger remains `github.run_attempt == 1`. The recovery source and
its seal exclude `_013`. After all twelve fresh exact-head workflow gates pass
and the writer freshly re-observes the two exact, unused D1.12 runner
registrations and roots, it may add `_013` in one single-parent commit whose
sole change is one regular,
non-executable `100644` JSON file. The push creates one workflow run only.

Protected execution then requires a newly generated external approval bound
to the exact `_013` commit, recovery source, source freeze, request bytes,
workflow run ID and attempt, phase, task/call/token/container/USD caps, actor,
UTC timestamp, nonce, legal acceptance, and OpenAI-key commitment. The
sentinel contains no approval and no credential.

## Scientific invariants

D1.13 is an activation-transport correction. It changes no model snapshot,
reasoning effort, prompt, tool, parser, target, target order, M0/M1/M2
definition, M2 candidate, selection rule, memory policy, PPR/DQN setting,
token/call/container/USD cap, grader revision, image digest, or frozen harness
input. The exact model remains `gpt-5.4-mini-2026-03-17`, with the same snapshot
for decomposition, solving, and experience extraction.

The resealer compares every frozen scientific file with its Git blob at the
immutable `_012` execution commit and records an exact hash of the `_012`
scientific request projection. The future `_013` writer must reproduce that
projection; control-plane identities may change only where required for the
new source, request, workflow, evidence, and runner generation.

## Convergent source and seal construction

The first local D1.13 commit contains the complete allowlisted source change,
including tracked placeholder amendment/inventory files and the changed
freeze path. The resealer validates that committed diff, computes the expected
amendment and inventory, and rewrites those documents and the freeze in a
second local seal commit. Both commits are pushed together so only the final
sealed HEAD supplies remote-gate evidence.

Generated documents never embed that mutable source-commit SHA. They record
`GIT_BLOB_EXACT_AT_CHECK_TIME`, the fixed historical commits, exact
implementation hashes, and the stable changed-path set. Consequently the
second commit converges instead of invalidating its own amendment. `_013`
remains absent from both source commits and the source freeze.

## Prohibited operations

D1.13 does not authorize `_012` attempt `2`, a rerun of run `34128541859`, an
edit of `_012`, creation of `_014`, HELDOUT, component ablation, grader-smoke
rerun, a model call, an image pull, a grader container, merge, tag, or release.
Paid/model calls remain `0` until a separate exact `_013` execution approval is
materialized and accepted inside the protected environment.
