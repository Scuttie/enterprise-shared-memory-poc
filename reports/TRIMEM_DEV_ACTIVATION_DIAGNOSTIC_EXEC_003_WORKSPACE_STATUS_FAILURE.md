# TriMem DEV activation diagnostic EXEC-003 workspace-status failure

## Immutable execution boundary

Run `34379166677`, attempt `2`, executed the feature-branch push workflow at
HEAD `bac7844191b1ea3c5faebc7f71abe1c2cf561135` on runner
`trimem-devdiag-34379166677-a2`. The run started on 2026-09-09 at
17:01:34 UTC and completed with `failure` at 17:11:20 UTC.

```text
TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_003 = WORKSPACE_GIT_STATUS_PORTABILITY_FAILURE
PERFORMANCE = NOT_MEASURED
PUBLIC_AGGREGATE = NOT_PRODUCED
SAME_RUN_ATTEMPT_REUSABLE = NO
```

## What passed

The attempt-2 hosted credential-free contract passed. On the protected runner,
all workflow stages through the following boundaries passed:

- exact source checkout, fresh restricted namespace, and cached toolchain;
- Python 3.11.10, the git-tracked freeze, pinned GitHub CLI, and hash-locked
  production dependencies;
- exact 12-target DEV dataset/checkout rehearsal;
- all three pinned harnesses, the official loader, and grader-factory
  rehearsal;
- the corrected isolated approval gate and byte-identical fresh approval;
- evidence-passphrase validation;
- 13 digest-pinned image pulls and observed-digest verification; and
- local OpenAI credential-format and run-bound HMAC commitment checks.

The credential checks performed no HTTP request. These successes are
infrastructure evidence only, not a benchmark or grader result.

## Exact failure

Both the initial executor invocation and its authorized same-attempt
`--resume` invocation failed closed with:

```text
DiagnosticExecutorError: pre-execution diagnostic checkout is not pristine
```

The first invocation returned status 2 and created only the durable execution
binding. The workflow therefore selected `--resume` for the one allowed retry;
the retry returned the same error. No workspace-preflight document, budget
ledger, cell result, grader result, or aggregate was produced.

The executor deliberately constructs and validates all 36 isolated task
workspaces before it constructs a paid model gateway. The failure occurred in
that workspace-preflight loop. Consequently no model client or scientific
ledger was created and no official grader was started.

## Root-cause reproduction

The frozen checkout construction correctly replaces only a committed
`text eol=crlf` checkout transform with the immutable LF Git-blob bytes. Its
raw byte and full-inventory validator accepted those exact bytes. A later,
independent `git status --porcelain=v2 --untracked-files=all` check nevertheless
reported the LF work tree as modified because the mutable index/stat state
still described the CRLF checkout form.

An exact Linux reconstruction of all 12 frozen DEV checkouts found:

| Target | Raw Git-blob-normalized paths | Porcelain false-dirty paths |
| --- | ---: | ---: |
| `multi_swe_bench_mini--ponylang__ponyc-1981` | 1 | 1 |
| `multi_swe_bench_mini--facebook__zstd-938` | 30 | 30 |
| other 10 targets | 0 | 0 |

The run's public-safe failure message did not retain a target identity. Given
the frozen arm-major order, ponyc is the first affected target; that target
attribution is a deterministic postmortem inference, not a field emitted by
the failed executor.

Refreshing only those transformed tracked paths with hermetic
`git add --renormalize` made porcelain empty while `git write-tree` remained
byte-identical to the pinned commit tree. The immutable work-tree files
continued to equal their Git blobs.

## Exact scientific accounting

| Counter | Actual |
| --- | ---: |
| task-arm runs | 0 |
| decomposition / solve / extraction calls | 0 / 0 / 0 |
| model API / generation / paid calls | 0 / 0 / 0 |
| input / cached-input / output / reasoning tokens | 0 / 0 / 0 / 0 |
| grader containers | 0 |
| official grader runs | 0 |
| total USD | `0.000000000000` |

Image materialization is accounted separately: 13 digest-pinned pulls passed,
fresh and resume live reinspection each covered all 13 images, and exact alias
cleanup passed. Those image operations are not model or grader execution.

## Failure evidence custody

Public aggregate upload was correctly skipped. The encrypted restricted
evidence, its inventory, and sanitized custody result were uploaded and
remotely verified before plaintext cleanup.

| Artifact | ID | GitHub digest | GitHub bytes |
| --- | ---: | --- | ---: |
| `trimem-dev-activation-diagnostic-restricted-encrypted` | `10115952919` | `sha256:303e9b2b6b4534fc20c5f6cf99f0facfc79dfaeded1f69a4a8f2b248c7214875` | 22,893,633 |
| `trimem-dev-activation-diagnostic-evidence-inventory` | `10115954530` | `sha256:4caccf233fc41ad4817e2b6ca6c25a8fc15bc13b23a6bd636cb79574e760aca2` | 10,176 |
| `trimem-dev-activation-diagnostic-remote-custody` | `10115957242` | `sha256:8fbae83ae6f5b697c91836e4ea2cc6acae1b9107d822bacf5f2bbbaa4b6f10f4` | 696 |

The logical inventory covers 301 files and 22,475,971 bytes with inventory
SHA-256
`8fe58ad9ad23d8b060fd1c40f76afe1518ea36f8495645bf8bcc3618236bd3ba`.
An independent streaming decryption retained no plaintext and matched every
inventory path, size, and SHA-256 in both directions. The custody endpoint is
`TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS`; the public artifact is
`ABSENT_EXPECTED`.

## Cleanup and correction boundary

Post-terminal control-plane verification records:

```text
protected-environment secrets = 0
repository runners = 0
pending deployments = 0
```

The original API-key file was not altered or deleted. The new correction keeps
raw Git-blob and complete-inventory validation, performs literal-pathspec,
tracked-only hermetic index renormalization for the exact transformed paths,
then requires `write-tree` to equal the pinned commit tree and porcelain status
to be empty. The credential-free 12-target rehearsal now also rejects any
non-empty `initial_status` instead of checking only raw blob identity. A Linux
reproduction of that corrected path passed all 12 targets, including all 31
normalized files, with zero model, image, or grader work.

Run `34379166677` attempt `2` and its approval are spent. Recovery requires a
new exact-head push run, its clean attempt-1 handshake, a whole-run attempt 2,
and fresh approval, nonce, passphrase, runner, and temporary secret set. No
target, source bank, model, prompt, tool, parser, budget, image, grader, or
verdict rule is changed.
