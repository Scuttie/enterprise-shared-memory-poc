# TriMem DEV activation diagnostic EXEC-002 approval-gate failure

## Immutable execution boundary

Run `34372037270`, attempt `2`, executed the feature-branch push workflow at
HEAD `3de7ae85fc81bb991544a9c12d4602cbdee1dbc5` on runner
`trimem-devdiag-34372037270-a2`. The run started on 2026-09-09 at
15:57:36 UTC and completed with `failure` at 16:08:14 UTC.

```text
TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_002 = APPROVAL_GATE_IMPORT_FAILURE
PERFORMANCE = NOT_MEASURED
PUBLIC_AGGREGATE = NOT_PRODUCED
SAME_RUN_ATTEMPT_REUSABLE = NO
```

## What passed

The attempt-2 hosted credential-free contract passed. On the protected runner,
all steps through the following pre-execution boundary passed:

- exact source checkout and fresh evidence namespace;
- cached runner toolchain and Python 3.11.10;
- 648-file git-tracked frozen-source check;
- exact pinned GitHub CLI installation and verification;
- hash-locked production dependencies;
- corrected isolated preinstall diagnostic and later editable installation;
- exact 12-target DEV dataset and checkout rehearsal;
- all three pinned harness materializations;
- exact official harness-loader preflight; and
- official grader-factory rehearsal.

These successes are infrastructure evidence only. They are not a benchmark or
grader result.

## Exact failure

The approval gate was the sole remaining diagnostic command still launched as
`python -I -S`. Although the project had been installed, `-S` suppressed site
initialization and therefore hid the editable package. The gate failed after
strict approval decoding but before frozen-contract reconstruction or approval
validation, with the exact public-safe reason:

```text
cannot reconstruct selected recall runtime lock: No module named 'enterprise_memory'
```

The approval material itself was not the cause. In the preserved exact runner
checkout, changing only the interpreter boundary to `python -I` made the same
run-bound approval pass with status
`APPROVAL_GATE_PASS_READY_FOR_BOUND_EXECUTOR`, 36 cells, and approval SHA-256
`9e954f699d71fc4f53bdf25a846a346e089cad01f60d21af1717d3ff00f42d2e`.
The corresponding `python -I -S` import remained deterministically failing.
That rehearsal performed no network, image, model, executor, or grader work.

## Exact zero-work accounting

| Counter | Actual |
| --- | ---: |
| image pulls | 0 |
| model metadata requests | 0 |
| model generation calls | 0 |
| paid model calls | 0 |
| task-arm runs | 0 |
| input / cached-input / output / reasoning tokens | 0 / 0 / 0 / 0 |
| grader containers | 0 |
| official grader runs | 0 |
| total USD | `0.000000000000` |

The evidence-passphrase, image, OpenAI credential-validation, billing-key
binding, executor, aggregate, and grader steps were all skipped.

## Failure evidence custody

The new `always()` pinned-CLI recovery and every subsequent custody step
passed. Public aggregate upload was correctly skipped. Encrypted restricted
evidence, its inventory, and the sanitized remote-custody result were uploaded
and remotely verified before workflow plaintext cleanup.

| Artifact | ID | GitHub digest | GitHub bytes |
| --- | ---: | --- | ---: |
| `trimem-dev-activation-diagnostic-restricted-encrypted` | `10113368913` | `sha256:280a20b9b24adb06c3c801d8c7056187476db1a4858a730374b8c0967cdda414` | 22,524,883 |
| `trimem-dev-activation-diagnostic-evidence-inventory` | `10113370553` | `sha256:0fc756cc03da18baa93560fad106255d5d1661e7884ebde23c0d6adf4cc352b8` | 4,192 |
| `trimem-dev-activation-diagnostic-remote-custody` | `10113373532` | `sha256:7b78c47664c5a08a99feac56bf124c39a86689e561bdb15aa61ba89c1037ba2e` | 696 |

The uploaded logical inventory covers 87 files and 22,382,135 bytes with
inventory SHA-256
`b55ed0611099b5d0f622a8dd83c063beb5084aaad0469a8eb86faed6f8ad5dc4`.
The sanitized result is
`TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS`, with the public artifact recorded as
`ABSENT_EXPECTED`.

## External cleanup and recovery boundary

Post-terminal control-plane verification records:

```text
protected-environment secrets = 0
repository runners = 0
pending deployments = 0
```

The exact three temporary protected-environment secrets were deleted without
reading their remote values. The ephemeral runner deregistered. The original
user API-key file was not altered or deleted. Downloaded encrypted evidence,
inventory, sanitized custody evidence, and the preserved runner root remain
available for audit.

Run `34372037270` attempt `2` is spent. It must not be rerun or used as
scientific evidence. Recovery requires this one-line interpreter-boundary fix
on a new exact HEAD, a new feature-branch push run and credential-free
attempt-1 handshake, a whole-run attempt `2`, and a fresh approval, nonce,
passphrase, runner, and temporary secret set. No target, source-bank, model,
prompt, tool, parser, budget, image, grader, or verdict rule is changed.
