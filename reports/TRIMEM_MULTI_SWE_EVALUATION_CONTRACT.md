# TriMem Multi-SWE-bench evaluation contract lock

## Result

The Multi-SWE-bench evaluation contract is statically locked to upstream commit
`24f493f8a103e72312ded4f6b9c89f081d69cb09`. At that revision,
`human_mode` defaults to `true`, while `force_build` defaults to `false`. When
`build_image()` is called for an already-present image with `force_build=false`,
that one call returns before creating a build workdir, Dockerfile, or recipe
file. This per-image short circuit does **not** make full `mode=evaluation`
prebuilt-only: the image phase walks the dependency graph and may build a
missing repository base image before it reaches the already-present PR image.
The two `human_mode` branches also have materially different input contracts:

- `human_mode=false` calls `session_util.run_and_save_logs()` and requires a
  host-side `images/pr-{number}/prepare.sh`.
- `human_mode=true` calls `docker_util.run()` and bind-mounts the host
  `fix.patch` at `/home/fix.patch` with read-write mode.

Consequently, the corrected prebuilt-only adapter uses a two-phase official
route. Its byte-locked production entrypoint,
`scripts/trimem_multi_swe_entrypoint.py`, imports the pinned
`run_evaluation` module as a library, creates the upstream `CliArgs` through
the upstream `get_parser()` config route, and calls `CliArgs.run()` with
explicit `mode=instance_only`, `force_build=false`, `human_mode=true`, and
`need_clone=false`. It does not execute the upstream module's `__main__`
block. The resulting dispatch goes directly to `run_mode_instance_only()` and
structurally excludes the `nix_swe` support-container bootstrap,
`run_mode_image()`, `check_commit_hashes()`, `build_image()`, and
`run_and_save_logs()`. Only after a zero exit and an exact submitted-patch
materialization check does it invoke pinned
`multi_swe_bench.harness.gen_report --mode evaluation`. The adapter requires a
zero report exit, an exact one-target final report, and non-empty official test
evidence. This section is a source-and-adapter contract, not a grader result.

The historical run `33594270929`, attempt 1, used full `mode=evaluation` and
`human_mode=false`. Its retained diagnostic evidence records one source build
of the missing `mswebench/vuejs_m_core:base`, a skip of the already-present
`mswebench/vuejs_m_core:pr-8911`, and then a failed read of the absent host
`images/pr-8911/prepare.sh`. It remains diagnostic only and is not part of an
authoritative campaign. The exact root cause is
`MULTI_SWE_PREBUILT_IMAGE_EVALUATION_MODE_MISMATCH`.

## Pinned provenance and byte locks

The audit used the Git object database, not checked-out working-tree bytes. The
repository origin was verified as
`https://github.com/multi-swe-bench/multi-swe-bench`; `git cat-file -t` verified
the revision as a commit; its tree object is
`741ce10a4ec220fec713112502850b381a6226b9`. Each regular `100644` blob was read
with `git cat-file blob <revision>:<path>` and hashed without newline
normalization.

| Pinned path | Git blob object | Bytes | SHA-256 |
|---|---:|---:|---|
| `multi_swe_bench/harness/gen_report.py` | `251e8b01059a18a9af5ae176c696eb4be8950ae4` | 21,331 | `02ebc8a5414898d12f4f5a9ba0c11a8f57c9f34a0bdc02c2311afac9f654847d` |
| `multi_swe_bench/harness/run_evaluation.py` | `f2dfa70df095d434cc6e5fd47f9a7a1bb027b824` | 28,647 | `b1a9b45022b9e79a5aa9a21908d9074b1258594c10d95f41938852d84ac38efb` |
| `multi_swe_bench/utils/args_util.py` | `24ed488f3a68927f517dca67a32e8dfbc6dc867a` | 3,277 | `26835412d5093091c771c7f99fe45a4ff141433decae23705b714b0ae2b250af` |
| `multi_swe_bench/utils/session_util.py` | `3d95889dec9e9a7e630c9b6a9552a4ea0bcdbf64` | 17,230 | `c4050c065520e35e7c0a7ad0f2ab2b124c3c692413f0c09a2591dd7dc30a3e8a` |
| `multi_swe_bench/harness/image.py` | `da1c613d4e7074f46889ffe1c31c0582c3535d2f` | 5,892 | `86074812495b97026efb42c57acbf7738864b1f0167f99e3b9f9309458972ae9` |
| `multi_swe_bench/harness/repos/typescript/vuejs/core.py` | `8562206faf6eb4fe739932f9a31ec578cc10af96` | 5,967 | `f154469392f1c52a5d8756c8f5332be35347b8b3bf4dd739a443b5ad4a5f3ce5` |

The machine-readable lock is
[`artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json`](../artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json).
Its contract projection SHA-256 is
`44e96161278e7030565ecb035fdbd90fc578a906fbcffd8d6fd054b07fe012ed`,
and its self-lock SHA-256 is
`539abc2394a60dc006297c949b71eb9c594ad94fa4eb8ccc830ea8da6062eee6`.

The production entrypoint itself is 8,114 bytes with SHA-256
`34554ec6fc39d9f1697244fa278fe37bc51cfe9991ba3950ef6fffff8a467866`.
That identity is part of the contract projection and must also be bound
directly by the one-time `_004` request.

## Exact control-flow evidence

### Pinned config-parser calling convention

At
[`args_util.py` lines 25–47](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/utils/args_util.py#L25-L47),
the upstream `ArgumentParser` signature is
`parse_args(self, use_config=True, *args, **kwargs)`. Therefore an argv list
passed as the first positional argument binds to `use_config`; the delegated
`argparse.ArgumentParser.parse_args()` receives no argv and consumes process
arguments instead. The production wrapper must call
`parser.parse_args(args=["--config", str(config_path)])`. The verifier locks
both the upstream signature/config-loading order and the wrapper AST call
shape, and the regression test demonstrates that the former positional form
fails while the named-`args` form loads the pinned config.

### Defaults and image short circuit

The pinned argument parser sets `force_build=false` at
[`run_evaluation.py` lines 79–85](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/run_evaluation.py#L79-L85).
It sets `human_mode=true` at
[`run_evaluation.py` lines 189–195](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/run_evaluation.py#L189-L195),
and the `CliArgs` dataclass independently retains the same default at lines
218–239.

At
[`run_evaluation.py` lines 573–610](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/run_evaluation.py#L573-L610),
`build_image()` first checks both `force_build` and whether the full image name
already exists. The matching branch returns at line 578. Workdir creation begins
only at line 580, recipe-file writes only at lines 592–596, and
`docker_util.build()` only at lines 598–609. Thus the early return has no prior
file-materialization side effect.

This early return applies only when `build_image()` has already been selected
for that exact image. Full `mode=evaluation` calls `run_mode_image()` first at
lines 784-813. Lines 612-683 construct the complete dependency graph and seed
builds from children of external images. For Vue Core, the PR image depends on
`CoreImageBase`; therefore an absent `mswebench/vuejs_m_core:base` can be built
even if `mswebench/vuejs_m_core:pr-8911` is already present. The correction does
not depend on the short circuit: `mode=instance_only` bypasses the entire image
phase.

### `human_mode=false`: host preparation script

At
[`run_evaluation.py` lines 726–748](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/run_evaluation.py#L726-L748),
the false branch constructs the host path
`{workdir}/{org}/{repo}/images/pr-{number}/prepare.sh` and passes it to
`run_and_save_logs()`.

At
[`session_util.py` lines 177–256](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/utils/session_util.py#L177-L256),
that helper starts the already-present image with pull policy `never`, opens the
host preparation path, separates actions on `###ACTION_DELIMITER###`, replays
them in the container session, and only then runs the requested command. The
host file is therefore a required input of this path, not an optional artifact.

### `human_mode=true`: direct run and patch volume

At
[`run_evaluation.py` lines 706–754](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/run_evaluation.py#L706-L754),
the true branch uses `docker_util.run()`. It binds the per-evaluation host
`fix.patch` to the dependency image's patch path in `rw` mode. The common
`Image` contract fixes that container path at `/home/fix.patch` and fixes image
identity as `{image_name}:{image_tag}` in
[`image.py` lines 89–121](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/image.py#L89-L121).
This default path does not read a host-side `prepare.sh`.

### Safe production dispatch and separate report

The pinned module's lines 818-833 are not a safe CLI entrypoint for the
12-container cap: its `__main__` block calls `docker.from_env()`, looks up a
container named `nix_swe`, and may create
`mswebench/nix_swe:v1.0` before it parses any arguments. The production
wrapper therefore imports the module without executing that block and calls
the pinned parser and `CliArgs` explicitly. Static wrapper verification and
the exact pre-exec rehearsal require `upstream_module_main_executed=false` and
`support_container_bootstrap_calls=0`.

At `run_evaluation.py` lines 756-815, `mode=instance_only` dispatches directly
to `run_mode_instance_only()`. That method submits only `run_instance()` work;
it does not call the image or commit-check functions. With `human_mode=true`,
the per-instance host patch is mounted over `/home/fix.patch`, so the different
patch baked into the immutable image is not treated as the submitted patch.

The report phase is independently pinned by the `gen_report.py` Git blob above.
Its evaluation path (lines 430-542) collects only evaluation workdirs, combines
the frozen dataset's run/test baselines with the new `fix-patch-run.log`, and
writes `output_dir/final_report.json`. Its dispatch is fixed at lines 572-582.
This reporting phase contains no Docker execution path.

## Vue `core` image recipe

The pinned Vue recipe has two layers:

1. `CoreImageBase` depends on `node:20`, uses the `base` tag, installs Git and
   global `pnpm`, and clones or copies the repository according to
   `need_clone`. See
   [`core.py` lines 9–57](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/repos/typescript/vuejs/core.py#L9-L57).
2. `CoreImageDefault` depends on that base, uses `pr-{number}`, and generates
   seven recipe components: the fix and test patches, a cleanliness checker,
   `prepare.sh`, and the run, test-run, and fix-run scripts. Its Dockerfile
   copies those components into `/home` and executes `/home/prepare.sh` while
   building the instance image. The preparation resets the repository, checks
   cleanliness before and after checking out the pinned base commit, and runs
   `pnpm install` with installation failure tolerated. See
   [`core.py` lines 60–189](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/repos/typescript/vuejs/core.py#L60-L189).

The registered `vuejs/core` instance depends on `CoreImageDefault`; its default
fix command applies both the test patch and fix patch before invoking the unit
test command. That binding is at
[`core.py` lines 192–222](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/repos/typescript/vuejs/core.py#L192-L222).

## Boundary

This artifact records a pinned static source contract for a correction that
does modify the TriMem adapter and credential-free contract workflow. Creating
this lock did not run Docker or either grader and made zero model or paid-model
calls. It did not modify an execution sentinel. No upstream source file or
source payload was copied into the product repository. Only provenance,
hashes, byte counts, symbol/line references, historical diagnostic facts, and
derived control-flow facts are retained.
