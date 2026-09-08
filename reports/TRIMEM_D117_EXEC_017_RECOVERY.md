# TriMem-Coder V1 D1.17 `_017` checkout-portability recovery

## Current endpoint

This credential-free source may end only at
`TRIMEM_V1_READY_FOR_EXEC_017_REQUEST`. It is not a benchmark score or
permission to enter the protected environment. Run `34185194819`, attempt `1`,
and `DEVELOPMENT_TUNING_EXEC_REQUEST_016.json` are spent and must not be rerun.

## Immutable `_016` execution boundary

- source HEAD: `c39b3dbfcf16ecc938ba7c958b044306f1874ff0`;
- execution HEAD: `0b31ee30abadae4242ce24d5a5821f01c727c6cc`;
- `_016` raw SHA-256:
  `4f423e31e130240d1747647bd05909f244f2d840699e9ff25b6de6711f2f6533`;
- workflow run/attempt: `34185194819` / `1`;
- branch-trigger and bounded-context jobs: `PASS`;
- protected approval, execution gate, credential binding, exact-model metadata,
  native-action canary, migration, and 13 digest-locked image observations:
  `PASS`;
- frozen stream execution: failed while preparing the first stream, before any
  task-arm reservation or official grader.

The process retained the exact terminal message
`new checkout is not exact and clean: multi_swe_bench_mini--ponylang__ponyc-1981`
and the non-resumable disposition `UNKNOWN_FAILURE`.

## Exact observed accounting

The `_016` run made one provider control-plane metadata request and one paid
protocol-canary generation. The canary used 950 input, 0 cached-input, 28
output, and 0 reasoning tokens, costing `$0.000838500000`. It pulled and
digest-verified 12 target images plus one support image. Scientific model
calls, task-arm reservations/runs, terminal cells, grader containers, and
official grader runs were all zero. No Pass@1 or performance result exists.

Encrypted restricted evidence is artifact `10040491733`
(`sha256:36b6f6240b65c7be7b426b19df5339aacd41744dd1dd3c6ae2bf2efe73b7c345`).
Inventory artifact `10040492534` and custody artifact `10040493782` verify the
failed-run evidence. The decrypted evidence inventory independently reproduced
96 files, 104,729 bytes, and root SHA-256
`71c6bf1d778850c94ca808b457165da9307cac19aae00187933cf331ab6b955f`.

## Root cause

The task checkout validator correctly treats immutable Git blob bytes as the
source identity. Ordinary `git checkout` may nevertheless apply a committed
`.gitattributes` work-tree transform. At the frozen Pony commit, `make.bat` is
a 2,064-byte LF blob but `*.bat win` expands to `text eol=crlf`, so Git created
a 2,162-byte CRLF work-tree file while still reporting a clean checkout.

An all-target diagnostic found the same mechanism at exactly two targets:

- Pony: one transformed path, `make.bat`;
- Zstd: 30 transformed `.vcproj`, `.vcxproj`, `.sln`, `.rc`, `.cmd`, and
  `.bat` paths, with 6,401 checkout-only carriage returns;
- the other ten DEV targets: zero transformed paths.

This is a cross-platform checkout-construction defect, not a model, task,
grader, image, or scientific-performance outcome.

## Fail-closed correction

D1.17 keeps the strict raw-blob validator unchanged. Only a checkout created by
the current process is eligible for construction-time normalization. Before a
write, the implementation verifies the exact commit/tree, local Git
configuration, immutable commit attributes, regular/symlink/gitlink modes,
complete inventory, and every observed transformed byte. It accepts only the
narrow committed `text=set,eol=crlf` LF-to-CRLF transform with no filter,
`ident`, or working-tree encoding, then atomically writes the authoritative Git
blob bytes. Existing and resumed checkouts are never repaired.

Checkout evidence binds the origin, commit, tree object, regular-blob count,
sorted normalized paths, path count, and canonical path-set hash. The actual
porcelain status is retained for audit but is not treated as raw-byte custody.
For writer-time rehearsal, the exact clean host HEAD is exported as a Git
bundle and cloned into a WSL-owned temporary source checkout. This preserves
Linux Git's ownership guard: no persistent `safe.directory` exception is
added, and mounted Windows work-tree bytes are not used as rehearsal source.

## Full 12-target rehearsal

The credential-free WSL rehearsal cloned all 12 frozen DEV revisions through
the production construction path and ended `12/12 strict PASS`: 54,544 regular
blobs and exactly 31 normalized paths (Pony 1, Zstd 30, all others 0). It used
no OpenAI credential, provider call, Docker operation, image pull, grader, or
task-arm run. The same exact rehearsal is now an unprotected workflow gate, so
a future canary cannot run unless all 12 checkouts pass first.

## Exact-head gate renewal

Request creation requires all 20 remote gates on the same source commit and on
their first attempts. An empty CI-renewal commit is not usable for this purpose:
the credential-free DEV-toolchain push workflow is intentionally path-filtered,
so GitHub creates no run for a commit with no changed path. The source is
therefore resealed with this recorded D1.17 contract clarification, which is an
explicit trigger path for that workflow. The incomplete 19/20 observation is
not execution evidence and carries zero provider, model, image, grader, and
task-arm activity.

## `_017` authority boundary

The D1.17 source preserves the model, reasoning effort, 12 targets/order, six
streams, prompts, tools, parsers, memory policies, per-arm budgets, grader and
image locks, and the `$50.00` per-attempt hard cap. The historical `_016`
canary is reported separately and is not reused. A fresh `_017` attempt retains
its own approval-bound one-canary-plus-1,872-scientific-call ceiling of 1,873.

Only a sentinel-only `_017` child may be created after exact-source CI, both
fresh runners, loader rehearsal, and the full checkout rehearsal pass. Actual
execution still requires a distinct external approval bound to that child,
source, freeze, request bytes, run ID/attempt, actor, time, nonce, legal
acceptance, caps, and OpenAI-key commitment.
