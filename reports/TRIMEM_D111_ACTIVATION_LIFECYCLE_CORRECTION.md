# TriMem V1 D1.11 activation-lifecycle correction

## Outcome

`DEVELOPMENT_TUNING_EXEC_REQUEST_011` is spent and immutable. GitHub Actions
run 34047573548 attempt 1 failed in `branch-trigger-preflight`; both
self-hosted jobs were skipped. The protected environment was not entered and
there were zero model/API calls, tokens, benchmark-image pulls, grader
containers, official grader runs, task-arm runs, terminal cells, and USD.

The current endpoint is `TRIMEM_V1_DEV_INCOMPLETE`. No Pass@1 or other
performance result exists. Attempt 2, rerunning `_011`, creating `_012`, and
any protected or paid operation remain unauthorized.

## Reproduced root cause

The `_011` request froze twelve successful source-gate runs at source HEAD
`155fe314631ef74828ea98b562036bdb0adca495`. After the sentinel-only child
advanced PR #18 to `e54d04b0af9e738d311c389dc89cfd510fd7065b`, GitHub kept
each historical run's top-level `head_sha` at the source commit but rewrote
the nested `workflow_run.pull_requests[0].head.sha` relationship to the new PR
head. D1.10 incorrectly required that mutable nested value to equal the old
source, so it filtered every historical pull-request gate out and reported
the first one as missing.

D1.11 freezes the correct separation:

- historical runs are matched by frozen run ID, workflow path, event,
  top-level `head_sha`, head branch, attempt, terminal status/conclusion, and
  canonical run URL;
- the entire historical `pull_requests` relationship is non-authoritative and
  ignored;
- the current PR is queried and bound separately to the expected current
  execution head; and
- the source-to-execution edge remains one parent and one regular-file
  sentinel addition.

The committed replay fixture reproduces the actual post-push API shape. Its
fail-closed tests cover missing, duplicate, rerun, top-level identity drift,
current-PR drift, ancestry/diff drift, and nonzero execution counters.

## Runner isolation correction

The two temporary self-hosted runners also exposed a separate scheduling
hazard before `_011`: the custom `ubuntu-24.04` label was identical to the
scalar label used by ordinary GitHub-hosted jobs. GitHub consequently assigned
ordinary CI jobs to both benchmark runners. This was not the terminal `_011`
failure—the runners were replaced before the sentinel push—but it could recur.

Protected benchmark jobs now require the repository-specific custom label
`trimem-ubuntu-24.04`. Ordinary hosted jobs retain `runs-on: ubuntu-24.04`.
The live host probe still independently requires `/etc/os-release` values
`ID=ubuntu` and `VERSION_ID=24.04`; the custom scheduler label does not replace
OS verification.

## Preserved scientific boundary

D1.11 changes no model, reasoning effort, prompt, tool, parser, task/target,
target order, M0/M1/M2 definition, M2 candidate, selection rule, memory policy,
PPR/DQN setting, token/call/USD cap, grader revision, or image digest. D1.10
source, seal, `_011` bytes, and run evidence remain available at exact Git
commit `e54d04b0af9e738d311c389dc89cfd510fd7065b`.

The correction is credential-free. It does not read or install an OpenAI key,
create an execution request, provision a runner, pull an image, start a
container, invoke a grader, or call a model.
