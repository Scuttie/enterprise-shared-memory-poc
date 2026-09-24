# TriMem DEV activation diagnostic EXEC-004 solver-sandbox mount failure

## Immutable execution boundary

Run `34386328359`, attempt `2`, executed the feature-branch push workflow at
HEAD `1e7c2710732178ff96194ff3269d75070de9e216` on runner
`trimem-devdiag-34386328359-a2`. The protected job ran from 2026-09-09
18:24:23 UTC through 18:40:42 UTC and concluded `failure`.

```text
TRIMEM_DEV_ACTIVATION_DIAGNOSTIC_EXEC_004 = SOLVER_SANDBOX_MOUNT_IDENTITY_FAILURE
PERFORMANCE = NOT_MEASURED
PUBLIC_AGGREGATE = NOT_PRODUCED
SAME_RUN_ATTEMPT_REUSABLE = NO
```

## What passed

The exact-head credential-free job passed. The protected job then passed:

- source checkout, fresh restricted evidence namespace, and pinned runner
  toolchain;
- Python 3.11.10, source freeze, pinned GitHub CLI, and hash-locked
  dependencies;
- exact 12-target DEV checkout rehearsal, including the prior Git index/EOL
  portability correction;
- all pinned harnesses, official loader preflight, and grader-factory
  rehearsal;
- fresh attempt-2 approval, evidence passphrase, 13 digest-pinned image pulls,
  and observed image digests; and
- local credential-format and run-bound key-commitment checks.

All 36 base-only workspace namespaces were materialized and recorded before
the solver-sandbox rehearsal. These are infrastructure checks, not model or
grader results.

## Exact failure and first cell

Both the fresh executor call and its authorized same-attempt `--resume` call
stopped in the first of the 12 pre-spend solver probes:

```text
fatal: cannot change to '/testbed': Permission denied
DiagnosticExecutorError: production solver sandbox mask rehearsal failed
```

The two stderr files are byte-identical: 54 bytes with SHA-256
`479b059e5dbd9e5159c253c1909109681accb2855133e2c266fd588f1851959f`.
Their stdout files are empty. The two public-safe executor
failure documents are also byte-identical and both returned status 2.

The retained workspace preflight identifies the first cell exactly as
`C0--swebench_verified--django__django-16100`, base commit
`c6350d594c359151ee17b0c4f354bb44f28ff69e`, using the frozen Django image
digest `sha256:768b2dd7ecee6c437c64441966687c4a1597230169c7c929e14374660a2ecdab`.
This identity is emitted evidence, not a target-order inference.

The executor places the 12-target solver rehearsal before construction of the
budget ledger, retrieval runtime, paid model gateway, and official cell
grader. No result, aggregate, or ledger exists.

## Root cause and correction

Every protected shell uses `umask 077`. The checkout mount is therefore owned
by the frozen runner service identity `1000:1000` and can contain owner-only
directories. The Docker command dropped every capability but did not set
`--user`, leaving execution to the image's OCI default.

A credential-free postmortem inspection of all 12 immutable target digests
found a null or empty `Config.User` for every image, which means default UID 0.
Capability-free UID 0 has neither `CAP_DAC_OVERRIDE` nor
`CAP_DAC_READ_SEARCH`, so it cannot traverse an owner-only UID-1000 bind mount.
The retained archive did not record `Config.User` or numeric mount ownership;
this conclusion combines its exact command/mount/error evidence with the
subsequent immutable-image inspection and same-host reproduction.

The same protected WSL/Docker host reproduced both sides using the first
frozen image and a mode-0700, UID/GID-1000 bind mounted at `/probe`. This
controlled postmortem pair was observed credential-free but was not retained
as a durable execution artifact; `/testbed` is the separately retained path
from run `34386328359`:

| command identity | Git/read result | checkout write result |
| --- | --- | --- |
| image-default UID 0 + `--cap-drop=ALL` | `/probe` permission denied | not reached |
| explicit `--user 1000:1000` + `--cap-drop=ALL` | pass | create/remove probe pass |

The correction does not relax permissions and does not add a capability. It:

- freezes the non-root numeric container identity as `1000:1000` in runner
  schema 1.2 and its content hash;
- rejects malformed, named, root, or out-of-range identities;
- fails closed unless both checkout and nested Git bind roots are owned by the
  exact frozen identity and have owner read/write/execute mode;
- records image-default user, effective user, mount UID/GID/mode, history
  isolation, masks, and a reversible checkout write probe in rehearsal
  evidence; and
- makes the workflow assert host UID/GID `1000:1000` and run all 12 exact
  image sandboxes before the `OPENAI_API_KEY` is exposed to any step.

Fresh 36-cell execution repeats the non-mutating 12-target
sandbox/history/mask/mount validation before constructing any paid gateway.
The reversible mode-0600 and nested-write mutation probes remain confined to
the disposable pre-billing checkout rehearsal.

## Exact scientific accounting

| Counter | Actual |
| --- | ---: |
| terminal cells / task-arm runs | 0 / 0 |
| decomposition / solve / extraction calls | 0 / 0 / 0 |
| model API / generation / paid calls | 0 / 0 / 0 |
| input / cached-input / output / reasoning tokens | 0 / 0 / 0 / 0 |
| grader containers / official grader runs | 0 / 0 |
| total USD | `0.000000000000` |

Infrastructure accounting is separate from the scientific table: 13 exact
image pulls, 13 materialization observations, and 26 live reinspections (13
fresh plus 13 resume) passed. The failed fresh and resume executor invocations
each completed one image-config inspection and started one masked solver probe
before stopping: 2 inspections, 2 non-grader solver containers, and 0 raw
Multi-SWE probe containers total. Exact image alias cleanup passed. None of
these infrastructure operations is a task-arm or official grader execution.

## Failure evidence custody

Public aggregate upload was correctly absent. Remote custody completed before
plaintext cleanup:

| Artifact | ID | GitHub digest | GitHub bytes |
| --- | ---: | --- | ---: |
| `trimem-dev-activation-diagnostic-restricted-encrypted` | `10119394864` | `sha256:523f877fcbf8a3c21cc2143e43b1ba7f770da4fea19f37c093ad9ec1536fba9d` | 22,944,853 |
| `trimem-dev-activation-diagnostic-evidence-inventory` | `10119396408` | `sha256:7a874679498ef896c6cbd4eae54534bc79b348d3141a2df9a4eabf28842148af` | 10,423 |
| `trimem-dev-activation-diagnostic-remote-custody` | `10119399177` | `sha256:ca6a537a1db09ab795f23f2bdf076f1cefd1026398b11da9eb0db7448e868b0d` | 694 |

The logical inventory covers 310 regular files and 22,513,771 bytes with seal
SHA-256
`9bb66530ac5d9d512a9edbb081ed9c0bfa9bad24375c9692067677d45cf742b7`.
Independent streaming decryption returned success, retained no plaintext, and
matched all 310 paths, sizes, and hashes in both directions with zero unsafe,
missing, extra, duplicate, non-regular, or mismatched members. The custody
endpoint is `TRIMEM_FAILURE_EVIDENCE_CUSTODY_PASS`; public custody is
`ABSENT_EXPECTED`.

## Recovery boundary

Run `34386328359` attempt 2 and approval SHA-256
`4fbc279419c7e8a49c68cf45afa137748b8cbe1c0cce8c8052b11a95ec9c9572`
are spent. They must not be rerun or reused. The correction changes no target,
target order, source bank, model snapshot, model-visible prompt/tool/parser schema,
adaptive-horizon rule, token/call cap, grader/image digest, or verdict rule.

A subsequent execution requires a new exact-head push run, a clean attempt-1
handshake, a fresh attempt-2 approval/nonce/passphrase, and a unique ephemeral
runner. HELDOUT, component ablation, grader-smoke rerun, and model changes
remain prohibited.
