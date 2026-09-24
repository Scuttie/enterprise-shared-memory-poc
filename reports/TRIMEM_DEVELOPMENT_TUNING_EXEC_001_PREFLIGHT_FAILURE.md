# TriMem V1 DEVELOPMENT_TUNING `_001` preflight failure

## Classification

- Endpoint: `TRIMEM_V1_DEV_INCOMPLETE`
- Failure label: `TRIMEM_DEV_TRIGGER_PREFLIGHT_DEPENDENCY_IMPORT_FAILURE`
- Scientific/evaluator run: no
- Performance measured: no

The immutable zero-authority request
`artifacts/trimem_v1/exec_requests/DEVELOPMENT_TUNING_EXEC_REQUEST_001.json`
was added alone at `6eba1b0f9462c3b29323a9ade290470551bfd0ed` from parent
`0fe4cd70604d381f5a8d7d0a384724817c6e3a42`. Its raw SHA-256 is
`7501c630a05ab0b87b9b510a72a5389f6ea7046dee6153b583e2833fa8e7e1db`.

That commit created GitHub Actions run
[`33727051040`](https://github.com/Scuttie/enterprise-shared-memory-poc/actions/runs/33727051040),
attempt 1. Hosted job `branch-trigger-preflight` (`100558327302`) failed in
`Verify one-time zero-authority DEV trigger`. The first command imported
`trimem_freeze.py`, whose constant-only dependency on the grader failure
closure transitively loaded `postgres_store.py` and then SQLAlchemy. The
dependency-free hosted job correctly had not installed SQLAlchemy, so it ended
with `ModuleNotFoundError` before the DEV request validator ran.

Protected job `frozen-serial-phase` (`100558404140`) was skipped with no runner
and zero steps. There was no protected deployment, environment approval,
external run-bound approval, approval materialization, target/support image
pull, task-arm run, official grader run, model/API call, or token expenditure.
All corresponding counters and USD are zero. The temporary environment-level
OpenAI key and evidence passphrase were removed; `TRIMEM_EXEC_APPROVAL_B64`
was never installed.

The exact failed HEAD subsequently completed all 17 credential-free workflow
runs successfully. Those green runs do not convert the benchmark preflight
failure into a DEV result.

The receipt distinguishes evidence classes. Run, job, deployment, and artifact
facts are bound to raw GitHub API response hashes. The import-chain root cause
is operator-derived from the failed-step log. The 17/17 CI tally, secret cleanup,
absence of a registered repository runner, and absence of an external approval
are explicitly operator-verified control-plane observations rather than claims
derived from the listed API response set.

## Recovery boundary

The `_001` request, commit, and run remain immutable. Attempt 2, request
mutation/recreation, force push, or approval reuse is forbidden. The approved
recovery uses a new `DEVELOPMENT_TUNING_EXEC_REQUEST_002.json`, request identity
`TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_002`, concurrency identity `_002`, and a
fresh attempt-1 workflow run. Its source freeze binds this report, the
machine-readable failure receipt, and the exact historical `_001` bytes.
The preflight also verifies that `_001` is the exact single-parent,
sentinel-only Git commit and an ancestor of the recovered source; copied or
rebased recovery material without that immutable history fails closed.
The received `TRIMEM_V1_DEV_PREFLIGHT_RECOVERY_002_APPROVED_ONCE` authority
ends at correction plus dispatch. It is not the distinct
`TRIMEM_V1_DEVELOPMENT_TUNING_EXEC_APPROVED_ONCE` authority that a fresh,
run-bound external document must provide before protected DEV execution.

The hosted path retains both full freeze validation and DEV request validation,
but executes them with `python -I -S`. `trimem_freeze.py` owns immutable path
literals directly instead of importing runtime/grader modules merely to obtain
those constants. Static CI rehearses the full freeze check before installing
dependencies, and unit tests exercise both the successful isolated CLI and the
attempt-2 fail-closed path.

No model, target, arm, prompt, tool, parser, runtime, grader, image, selection,
or budget contract is changed by this recovery. It authorizes neither HELDOUT,
component ablation, grader-smoke rerun, merge, tag, nor release.
