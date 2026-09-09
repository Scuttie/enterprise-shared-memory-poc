# TriMem V1 DEVELOPMENT_TUNING `_002` protected EXEC-gate failure

## Classification

- Endpoint: `TRIMEM_V1_DEV_INCOMPLETE`
- Failure label: `TRIMEM_DEV_EXEC_GATE_GH_CLI_MISSING`
- Failure stage: `PROTECTED_EXEC_GATE_BEFORE_RUNTIME_SECRET_CHECK`
- Scientific/evaluator run: no
- Performance measured: no (`NOT_MEASURED`)

The immutable sentinel
`artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_002.json`
has request identity `TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_002`, raw SHA-256
`c81c57a5c93d4be9efdc971147191d8bc2e1bc2f06fe241e38ce36b6a4ee3f98`,
and source HEAD `98dd37fec7c826f6ed5b3b8734f2ca8dcab96e4a`. It was added as the
sole change (`A<TAB>artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_002.json`)
at execution HEAD `c2738cae074351927dde117b628c601b1e296cf2`. The request and execution
commit remain immutable.

That push created GitHub Actions run
[`33739545314`](https://github.com/Scuttie/enterprise-shared-memory-poc/actions/runs/33739545314),
attempt 1, in workflow `349104146`. The run began at
`2026-09-03T09:33:55Z`, ended with conclusion `failure`, and was last updated
at `2026-09-03T10:01:11Z`. Hosted job `branch-trigger-preflight`
(`100597978462`) succeeded. Protected job `frozen-serial-phase`
(`100598063576`) ran on the dedicated ephemeral runner
`trimem-dev-33739545314-a1` from `2026-09-03T09:58:14Z` through
`2026-09-03T10:01:10Z` and failed at exactly `Verify exact phase EXEC gate`.

## Exact failure boundary

The protected environment worked. External approval materialization and the
event/phase checks passed. The gate then failed closed with this blocker:

```text
official grader smoke attestation verification failed: gh CLI is required for cryptographic smoke attestation verification
```

The ephemeral runner did not provide `gh`, which the cryptographic official
grader-smoke attestation verifier required. Step 11, `Verify required protected
runtime secrets before paid work`, was therefore skipped. Steps 12 through 16
were also skipped: migration, target-image materialization, frozen stream
execution, aggregate validation, and public-result construction. This is a
protected control-plane failure before scientific execution, not a DEV result
and not a performance measurement.

The external approval itself was fresh and run-bound. Its 857 canonical bytes
have SHA-256
`a055cf4298049be35f1a3f5d4d7186256a1cfaab7d6ac256b91e0372784dff9f`.
It bound run `33739545314` attempt 1, execution HEAD
`c2738cae074351927dde117b628c601b1e296cf2`, source HEAD
`98dd37fec7c826f6ed5b3b8734f2ca8dcab96e4a`, freeze SHA-256
`dd8e5169acda78e45aaf13a918c0dfe6d566ecd776a9ca8e9190a1fc02fe380f`,
the exact `_002` raw request SHA-256, phase `DEVELOPMENT_TUNING`, and hard caps
of 72 task-arm runs, 72 grader containers, 1,872 paid model calls, 36,000,000
input tokens, 3,796,992 output tokens, and USD 50.00. Approval success does not
turn the subsequent gate failure into scientific execution.

## Zero scientific accounting

The actual scientific accounting is:

```text
task-arm runs             = 0
solve calls               = 0
decomposition calls       = 0
extraction calls          = 0
model calls               = 0
model gateway calls       = 0
paid model calls          = 0
benchmark/API calls       = 0
grader calls              = 0
grader containers         = 0
official grader runs      = 0
target image pulls        = 0
input tokens              = 0
cached input tokens       = 0
output tokens             = 0
reasoning tokens          = 0
total USD                 = 0
```

GitHub control-plane queries used later to preserve evidence are not benchmark
or model API calls and are outside those scientific counters.

The successful job-initialization step did pull and start two support-service
containers: pinned Postgres
`sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412`
and pinned Qdrant
`sha256:241edb9d7778327516ef218f8c74e1bd61b5ea42cd4f193cb8d0896199705636`.
Thus support-service image pulls and containers are both 2; they are neither
target-image pulls nor grader containers.

## Preserved evidence

The post-failure encrypted-evidence steps succeeded. Restricted artifact
`trimem-benchmark-restricted-encrypted` has ID `9888089129`, API/archive digest
`sha256:c1e2e245ffbeedfdd311e509bcb5e5eaceb57d04f418ffdde423c9791fbe7e20`,
and 10,461 ZIP bytes. Its sole ZIP member is the 10,272-byte ciphertext
`trimem-benchmark-restricted.tar.enc`, whose SHA-256 is
`c2ab8141aae6062ae362dcadedde529b1681e095faa2b14db907d82a1256fac3`.

Streaming decryption found only `benchmark_exec/`,
`benchmark_exec/control/`, and the 857-byte
`benchmark_exec/control/restricted-external-approval.json`; the approval member
hash equals
`a055cf4298049be35f1a3f5d4d7186256a1cfaab7d6ac256b91e0372784dff9f`.
No plaintext tar was persisted. There is no public
benchmark artifact because the public-result step was never reached.

The complete workflow log ZIP is 71,392 bytes with SHA-256
`31de05544526d0a9e8d2cde3baf6abd64f027e4b74fe2d6a646b7428684ee488`.
Its exact failed-step member is 3,223 bytes with SHA-256
`60f81c06804c109a13c4c9e4554010f6e78220eaba59c529fab794787e087733`.
An exact-secret scan for `OPENAI_API_KEY`, `TRIMEM_EXEC_APPROVAL_B64`, and
`TRIMEM_EVIDENCE_PASSPHRASE` across the full log set passed with zero hits. The sanitized
pre-job hook receipt is 216 bytes with SHA-256
`73b7aa67cda2be2c083bec43526eae4850e3b5103ef5df24ae030085e8cbfbbf`
and binds the same repository, run, attempt, job, execution HEAD, and source
HEAD.

The machine-readable receipt binds its conclusions to raw GitHub API documents
for the workflow run, jobs, artifact list and metadata, deployment and approval
statuses, pending deployments, and the post-cleanup runner, secret, and fork
policy state. The full raw byte counts and SHA-256 values are recorded there.

## Cleanup and authority boundary

Deployment `6241058439` records the one protected-environment approval. After
evidence verification and cleanup, environment `trimem-benchmark-exec` has zero
secrets, the repository has zero registered runners, and the fork pull-request
approval policy is restored to `first_time_contributors`. The exact dedicated
WSL distribution `TriMemRunner2404` was deleted; the pre-existing `Ubuntu`
distribution was untouched.

There was no rerun or attempt 2, no `_003` sentinel was created, and no future
recovery authority has been received. HELDOUT, component ablation, merge, tag,
and release remain forbidden without new explicit authority.
