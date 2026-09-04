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
`run_and_save_logs()`. Only after a zero wrapper exit following exact terminal
status capture and an exact submitted-patch materialization check does the
gateway invoke pinned
`multi_swe_bench.harness.gen_report --mode evaluation`. The adapter requires a
zero report exit, an exact one-target final report, and non-empty official test
evidence. This section is a source-and-adapter contract, not a grader result.

The pin also exposes two boundaries that the local adapter closes explicitly.
First, upstream `docker_util.run()` starts a detached container through the
Docker SDK without an explicit local-only pull guard. If the supplied mutable
tag is absent, the SDK's `containers.run()` path may fall back to a pull. Its
`output_path` branch streams logs with `follow=true` but neither calls `wait()`
nor observes a `StatusCode`; its other branch calls `wait()` but discards the
returned status.
The local wrapper therefore verifies the frozen immutable RepoDigest before
creating the exact harness alias, forbids pull and source-build operations in
the execution wrapper, and captures one exact integer terminal `StatusCode`
from the container it started. It invokes the image with
`fix_patch_run_cmd=bash -e /home/fix-run.sh`, so patch-application failure exits
before tests rather than masquerading as an ordinary unresolved result. A
resolved GOLD result requires status zero. A nonzero unresolved result is
admissible only when the complete exact frozen test domain was nevertheless
observed and validated.

Second, pinned report generation checks `report.valid` before it checks the
four expected category memberships. Either failure is collected as an invalid
report, and `FinalReport.from_reports()` maps invalid reports to unresolved
IDs. Those upstream category loops prove expected-member coverage but do not
reject extra test names. The local result parser closes that asymmetry by
requiring exact frozen `run_result` and `test_patch_result` classifications and
the exact frozen `fix_patch_result` test-name domain before accepting either a
resolved or unresolved result.

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
| `multi_swe_bench/harness/dataset.py` | `19aeb4370fcfdaeccef99b3a47d06c5a572d468c` | 2,833 | `dd49f55baf63b60fff309b6a5b2a1826697e2b85ad1a9bccff18321dcdc200fc` |
| `multi_swe_bench/harness/gen_report.py` | `251e8b01059a18a9af5ae176c696eb4be8950ae4` | 21,331 | `02ebc8a5414898d12f4f5a9ba0c11a8f57c9f34a0bdc02c2311afac9f654847d` |
| `multi_swe_bench/harness/image.py` | `da1c613d4e7074f46889ffe1c31c0582c3535d2f` | 5,892 | `86074812495b97026efb42c57acbf7738864b1f0167f99e3b9f9309458972ae9` |
| `multi_swe_bench/harness/pull_request.py` | `0c2c99a4602bc6dc127cc0bb3ecaff56a6550d17` | 6,015 | `32b49f48b39124f67727f408898bd96cce91c0a362faa716ac858dcb0b0b47c7` |
| `multi_swe_bench/harness/report.py` | `a0b23ab1bf3c2407e15338fd0e644c0138fd3d90` | 12,942 | `5a025fd496d42c4b7377fc0702d64c6d0e356b117eaf2face47e73a52c29902f` |
| `multi_swe_bench/harness/test_result.py` | `bbdd5dc729582a1d06c79f416058bbc4d7db9c91` | 5,164 | `5411af794920cf4b170fe9dbe8c21c12cc63e2bbe2280d6d82acb850f4808be3` |
| `multi_swe_bench/harness/repos/c/jqlang/jq.py` | `9328e7683d5f269a6247292b388a7c7cb6592420` | 6,431 | `e523664fcf8a1b728f5d4d77caeebc7cecd34c575f295fdb66a441b910e3a8b0` |
| `multi_swe_bench/harness/repos/javascript/expressjs/express.py` | `15a98c72f2218925a31319dbb1a498b020a78f66` | 10,209 | `a673518e3b4d9e9e2396f97aacdc5c803d7e2298ce07dfd748cbb9f67ce36291` |
| `multi_swe_bench/harness/repos/python/django/django.py` | `98dd428523768d4c35ff119cc50dc453675ab5c7` | 4,392 | `9b9fbcfa6e165d42b39c589e2bdd657ec0ab5df1caec8fbace683314e21bd9a8` |
| `multi_swe_bench/harness/repos/typescript/vuejs/core.py` | `8562206faf6eb4fe739932f9a31ec578cc10af96` | 5,967 | `f154469392f1c52a5d8756c8f5332be35347b8b3bf4dd739a443b5ad4a5f3ce5` |
| `multi_swe_bench/harness/run_evaluation.py` | `f2dfa70df095d434cc6e5fd47f9a7a1bb027b824` | 28,647 | `b1a9b45022b9e79a5aa9a21908d9074b1258594c10d95f41938852d84ac38efb` |
| `multi_swe_bench/utils/args_util.py` | `24ed488f3a68927f517dca67a32e8dfbc6dc867a` | 3,277 | `26835412d5093091c771c7f99fe45a4ff141433decae23705b714b0ae2b250af` |
| `multi_swe_bench/utils/docker_util.py` | `f3b89d736a82fbf1dd31e303b0e8fe353380170a` | 3,395 | `dd5929ee952763ec11a22646f2725b306b573ddbc86dc8ffc7a6d9dfa53f493d` |
| `multi_swe_bench/utils/session_util.py` | `3d95889dec9e9a7e630c9b6a9552a4ea0bcdbf64` | 17,230 | `c4050c065520e35e7c0a7ad0f2ab2b124c3c692413f0c09a2591dd7dc30a3e8a` |

The machine-readable lock is
[`artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json`](../artifacts/trimem_v1/multi_swe_evaluation_contract_lock.json).
Its contract projection SHA-256 is
`2ceccbbae2c50ddfa625b82b3fa60d9c53d1854064b78ab0bab5a513da8c6b5a`,
and its self-lock SHA-256 is
`eba4cb2c4d9cec60b2e79a051c3a33833a58e1b2f1cf4dcbd49ddc46a05bbece`.
The raw lock file SHA-256 is
`79e2b399c56269eff1cd23f815156ba4ace259c81e12690d63377a32c107c1ae`.

The production entrypoint itself is 25,035 bytes with SHA-256
`16c021ac3c0eb18bc78376164307b53cfb294ac0f206415d465a1b11f1ec63ac`.
That identity is part of the contract projection and must also be bound
directly by the one-time `_005` request.

Its exact command surface requires `--harness-root <pinned-checkout>`,
`--config <one-row-config>`, `--expected-image <immutable-digest>`,
`--expected-tag <frozen-harness-tag>`, and
`--exit-status-output <exclusive-status-path>`. The official adapter binds all
five values, including the immutable image, its frozen harness tag, and the
exclusive raw status destination, explicitly.

The same projection byte-locks the complete local validation chain:
`scripts/trimem_multi_swe_entrypoint.py`,
`scripts/trimem_official_grader.py`, `scripts/trimem_grader_smoke.py`, and
`scripts/trimem_benchmark_matrix.py`. The first two guard execution and
per-result interpretation; the smoke runner copies and revalidates the raw
container-status sidecar into each cell's evidence; and the aggregate reloads
the committed matrix and frozen source row to validate that raw evidence and
published summary independently. The repository's `.gitattributes` fixes
`scripts/trimem_*.py` to `eol=lf`. Live contract verification requires every
projected file's working bytes to equal its tracked `HEAD` Git blob before it
checks the raw byte length and SHA-256, so checkout newline conversion cannot
silently alter the contract.

The P0.1.5 execution workflow inventories and encrypts available restricted
evidence independently of authority-recovery success. Its failure closure is
stricter and requires recovery success or skip. Plaintext cleanup occurs only
after the encrypted artifact is durably uploaded; otherwise plaintext and
ciphertext are preserved and the workflow fails. A content-bound finalization
journal is mandatory before authority promotion and for scientific-rejection
or false-tree run-smoke failure qualification.

| Local validator | Role | Bytes | Raw SHA-256 |
|---|---|---:|---|
| `scripts/trimem_multi_swe_entrypoint.py` | immutable-image and container-status execution guard | 25,035 | `16c021ac3c0eb18bc78376164307b53cfb294ac0f206415d465a1b11f1ec63ac` |
| `scripts/trimem_official_grader.py` | exact frozen-domain and conditional-status validator | 101,093 | `fbd15718a88b4d733b313af83889aae8ef6ac7837529bba52f0bb4072f57b886` |
| `scripts/trimem_grader_smoke.py` | per-cell evidence producer | 135,285 | `15b1bae4a14ac74f53de016882e20f6962d0b5e2818b6a158ab26373c7fb748a` |
| `scripts/trimem_benchmark_matrix.py` | independent fail-closed aggregate revalidator | 123,286 | `cf05654fa25c643ef9e2573f7e3f70b54236aa545669e353d886e80d9e710767` |

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

### Pinned Docker run boundary and local closure

At
[`docker_util.py` lines 17–19](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/utils/docker_util.py#L17-L19),
the pinned helper creates its Docker client at module import. Its `run()` path
at
[`docker_util.py` lines 71–108](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/utils/docker_util.py#L71-L108)
passes the image string directly to `docker_client.containers.run()` with no
`pull` argument and no helper-owned local digest preflight. In the
`output_path` branch used by evaluation, it drains
`container.logs(stream=true, follow=true)` and returns the text without a
`container.wait()` or `StatusCode` check. The other branch waits but discards
the returned mapping, so neither branch propagates nonzero status.

The byte-locked local wrapper closes both gaps around this unchanged upstream
function. It requires the frozen immutable digest and the generated harness
tag to resolve to the same local image ID, replaces the SDK pull surface with a
fail-closed tripwire during execution, verifies the upstream request uses the
exact frozen harness tag, substitutes the immutable digest into direct
`containers.create()`, and proxies that exact container to retain one integer
terminal status. The status is evidence, not a universal
zero-only gate: resolved GOLD requires zero, while unresolved NOOP may be
nonzero only after exact complete frozen-domain evidence validates. The fixed
command is `bash -e /home/fix-run.sh`; therefore a patch-application error
cannot continue into the test command and fabricate a complete unresolved test
domain.

### Pinned report classification boundary

Within
[`gen_report.py` lines 430–524](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/gen_report.py#L430-L524),
`safe_generate_report()` first rejects `not report.valid`. It then checks the
frozen `p2p_tests`, `f2p_tests`, `s2p_tests`, and `n2p_tests` categories in that
order; any missing expected member also returns `(report, false)`. Both kinds
of rejection enter `invalid_reports`. At
[`report.py` lines 309–347](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/report.py#L309-L347),
`FinalReport.from_reports()` maps `reports` to `resolved_ids` and
`invalid_reports` to `unresolved_ids`. The stored target value is the inherited
[`PullRequestBase.id` at `pull_request.py` lines 77–100](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/pull_request.py#L77-L100),
whose exact format is `{org}/{repo}:pr-{number}`.

This upstream check is expected-member coverage, not exact set equality. The
local official-result parser additionally compares the actual run and
test-patch classifications against the frozen row and requires exact equality
of the fix-stage test-name domain. It applies that check before accepting
either final classification, including a nonzero-status unresolved NOOP.
Likewise, pinned `TestResult.__post_init__` validates already materialized sets
(count-to-set size and pairwise disjointness); it does not unconditionally
detect duplicates in a preceding raw JSON array. The TriMem parser deliberately
adds the stricter fail-closed rule and rejects raw duplicate test IDs before set
construction.

### All frozen Multi-SWE smoke target adapters

The Multi-SWE smoke set is not Vue-only. The pinned repository adapters for
`django/django`, `expressjs/express`, `jqlang/jq`, and `vuejs/core` all expose
the same decisive override: `fix_patch_run(fix_patch_run_cmd)` returns a
non-empty supplied command unchanged before falling back to
`bash /home/fix-run.sh`. Pinned `run_instance()` passes the frozen config's
override into that method. Thus all eight Multi-SWE GOLD/NOOP cells execute
the local contract command `bash -e /home/fix-run.sh`, while their baked
scripts still consume the bind-mounted `/home/fix.patch`:

- Django's adapter is locked at
  [`django.py` lines 9–29](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/repos/python/django/django.py#L9-L29).
  It delegates to the generic `SWEImageDefault` recipe at
  [`image.py` lines 124–198](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/image.py#L124-L198).
  That baked script uses `set -uxo pipefail`, which does not itself enable
  errexit, before `git apply --whitespace=nowarn /home/fix.patch`. The
  adapter-level `bash -e` is therefore mandatory for fail-closed patch
  application.
- Express locks its image script and override at
  [`express.py` lines 67–226](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/repos/javascript/expressjs/express.py#L67-L226).
  Its baked `fix-run.sh` already sets `-e` and applies
  `/home/test.patch /home/fix.patch` together.
- JQ has the equivalent `set -e` and two-patch apply contract at
  [`jq.py` lines 67–237](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/repos/c/jqlang/jq.py#L67-L237).
- Vue Core likewise sets `-e`, applies the test patch and mounted fix patch,
  and accepts the command override at
  [`core.py` lines 60–222](https://github.com/multi-swe-bench/multi-swe-bench/blob/24f493f8a103e72312ded4f6b9c89f081d69cb09/multi_swe_bench/harness/repos/typescript/vuejs/core.py#L60-L222).

The uniform outer command remains intentional even where the baked script has
its own `set -e`: it gives every frozen target one execution contract, and it
closes the Django-specific omission without changing upstream source or image
contents.

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
