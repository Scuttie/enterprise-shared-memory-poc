# TriMem DEV activation diagnostic EXEC-001 preflight failure

## Immutable execution boundary

Run `34359716328`, attempt `2`, executed the feature-branch push workflow at
HEAD `e932ac923cfc18f5fb5cace3eb1ee33ba64b6657` on runner
`trimem-devdiag-34359716328-a2`. The run completed with `failure` on
2026-09-09. The hosted `credential-free-contract` job passed before the
protected `diagnostic-execution` job started.

```text
TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_001 = PREFLIGHT_IMPORT_FAILURE
PERFORMANCE = NOT_MEASURED
PUBLIC_AGGREGATE = NOT_PRODUCED
SAME_RUN_ATTEMPT_REUSABLE = NO
```

## Primary failure

The protected runner, checkout, evidence namespace, cached toolchain, exact
Python setup, and 647-file frozen-source check passed. The next pre-install
diagnostic preflight failed closed with the exact public-safe reason:

```text
cannot reconstruct selected recall runtime lock: No module named 'enterprise_memory'
```

The isolated command added `scripts` and the repository root to `sys.path` but
not the uninstalled `src` tree. It therefore could not import the
`enterprise_memory` package before the editable installation step. The
production environment installation and every image, approval-gate, OpenAI,
executor, aggregate, and grader step were skipped.

## Secondary custody-path failure

The always-run evidence inventory, encryption, encrypted upload, and inventory
upload succeeded. Because the primary failure had skipped the earlier pinned
GitHub CLI installation, the subsequent remote-custody verifier failed with:

```text
FileNotFoundError: [Errno 2] No such file or directory: 'gh'
```

This is a secondary evidence-custody path failure, not a model or grader
result. The sanitized custody-result upload was skipped. Cleanup then failed
closed with `image cleanup or external artifact custody failed; preserving
plaintext and ciphertext`; preserved runner evidence must not be deleted until
recovery is complete.

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

No API credential validation, key-binding verification, model request, task
workspace execution, image materialization, or official grading was reached.

## Uploaded artifacts

Exactly two non-expired artifacts exist for the run; no public aggregate or
sanitized custody-result artifact exists.

| Artifact | ID | GitHub digest | Bytes |
| --- | ---: | --- | ---: |
| `trimem-dev-activation-diagnostic-restricted-encrypted` | `10109024709` | `sha256:80e90b7060987b036dd90e1bf50b20ddeae28ac2858ab87c44f5caf39840c9ab` | 22,442,938 |
| `trimem-dev-activation-diagnostic-evidence-inventory` | `10109026452` | `sha256:7d5c8529a1c2fa77a07540b908093fcca376e600017ce072740734af0b35509f` | 3,611 |

The uploaded inventory is
`trimem/restricted-evidence-inventory/1.0`, rooted at
`dev_activation_diagnostic`, with `68` files and `22,317,390` total inventoried
bytes. Its logical `inventory_sha256` is
`aabf1ac0ea1469549aa8bd843bd7049188685bce34387e1ea40b22e07f591c55`.

## External cleanup and recovery boundary

Post-failure external control-plane verification records:

```text
protected-environment secrets = 0
repository runners = 0
pending deployments = 0
```

The exact three temporary protected-environment secrets were removed without
reading their values. The ephemeral runner deregistered. No preserved runner
evidence was removed by this closure.

Run `34359716328` attempt `2` is spent. It must not be rerun, resumed as a new
workflow attempt, or used as scientific evidence. Recovery requires a code
fix on a new exact HEAD, a new feature-branch push run and credential-free
attempt-1 handshake, a whole-run attempt `2`, and a fresh approval bound to
that new HEAD, run ID, attempt, contract hashes, caps, model snapshot, nonce,
and billing-key commitment. Neither this approval nor its temporary secret
material may be reused.
