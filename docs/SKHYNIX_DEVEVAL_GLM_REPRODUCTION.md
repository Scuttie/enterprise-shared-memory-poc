# DevEval: existing Linux container and internal GLM

This handoff runs the fixed DevEval 002 repository experiment in an existing
Linux x86_64 container, without Docker installation, root privileges, PostgreSQL,
or a GPU on the client. A user-provided internal vLLM endpoint supplies GLM.
No GLM endpoint has been called during package preparation.

Use package schema `deveval/offline-package/2`. The earlier `9d4cbf3` bundle is
superseded: its 79-package environment omitted four dependencies materialized by
`setup.py` into `.eggs`, and its driver HTTP tripwire did not cover those child
processes. Its records are retained; their former offline-completeness claim
must not be used as evidence for schema 2. Those records do not establish whether
the subprocesses obtained the dependencies from a network or an existing cache.

The fixed plan has 30 tasks from three repositories: 12 DISCOVERY, 6 VERIFICATION,
6 VALID, and 6 TEST. The 12 held-out tasks each receive OFF, L1_ONLY, NO_L2,
NO_L3, and FULL, giving 78 experimental cells including training (each allows
up to four fresh model sessions). A new GLM run
builds its own training memory. No Luna episodes, procedures, answers, prior
target history, or model results are included in this package.

## What to transfer

Transfer the entire fresh bundle directory, preserving bytes. It contains a
curated `repo/`, the original 916,746,365-byte official source archive, pinned
metadata/evaluator files, and `assets/{driver,native}`. Do not transfer the
preparation machine's whole repository, `.git`, old run folders, or banks.
The manifest lists every file and SHA256; copy its SHA256 through the trusted
handoff record and verify it independently before running the bundled helper.
`DRAFT_UNCOMMITTED_SOURCE` identifies a preparation test bundle; the final handoff
must say `COMMITTED_SOURCE` and record its Git commit.

Two standalone interpreters are included and verified after relocation:

| Role | Python | Packages | Purpose |
| --- | --- | --- | --- |
| driver | 3.10.21 | 43 | manager, memory, repository tools, standard-library HTTP |
| native | 3.9.18 | 79 | official repository dependencies and evaluator |

A separate, hash-pinned setup wheelhouse contains PyYAML 6.0.3, simplejson 4.1.2,
ujson 5.11.0 and warcio 1.8.1 (about 1 MB). These four are not installed into the
native solver environment. Official `setup.py` subprocesses may materialize
their exact bytes into per-project `.eggs` directories during grading.

Use Linux x86_64 with glibc >= 2.28 and a writable filesystem supporting Unix
permissions. Install on the container's Linux filesystem, not a Windows mount.
The helper reserves 10 GiB free space in addition to estimated installation
space. No runtime package download occurs. A host Python >= 3.9 is needed only
to verify and bootstrap the supplied interpreters. No API secret is included.

The source archive contains reference implementations and private tests. It is
grader-only. The preparer constructs solver snapshots by masking all 257
benchmark target bodies and docstrings across the selected repositories before
building AST relations, and removing private tests/fixtures. Original source is
never presented through solver read/search tools. This is experiment tool
isolation, not an operating-system security boundary for arbitrary malicious code.

## Offline installation

Substitute absolute paths for `BUNDLE` and `INSTALL`. Keep the bundle immutable;
create installation, preparation, and experiment outputs outside it.

```bash
sha256sum "$BUNDLE/manifest.json"
python3 -B "$BUNDLE/repo/scripts/deveval_offline_package.py" verify --bundle "$BUNDLE"
python3 -B "$BUNDLE/repo/scripts/deveval_offline_package.py" install-offline \
  --bundle "$BUNDLE" --output "$INSTALL"
```

Installation uses only the supplied wheels with `--no-index --require-hashes`,
then runs both `pip check` commands and import checks. The four setup-support
wheels are separately validated against their supplied manifest and lock. The resulting
`installation.json` binds the package hash, relocated Python versions, package
counts, and verification logs. Installation does not grade or call any model.
The new venvs point to the relocated standalone interpreters; keep the installation
directory at its final path after creation. Reinstall from the bundle if moving it.

## Prepare the unchanged cohort on the company machine

Copy `repo/configs/skhynix_v1/deveval_002_glm_runtime.example.json` outside the
bundle and set `gateway.base_url` and the exact served `gateway.model`.
This file supplies gateway settings; `prepare-company` creates the full local
runtime. Do not pass the example directly to the experiment manager.
The URL ends in `/v1`; the client appends `/chat/completions`. Put an optional
secret in the named environment variable; use `api_key_env: null` if the server
does not require authentication. Do not place credentials in JSON or Git.
The JSON-content action protocol does not require vLLM tool-call parsing or an
OpenAI SDK. Model name, output limit, temperature and request bounds are frozen
with this new runtime. They are a separate GLM condition, not numerical
equivalence to Luna's `low` reasoning setting.

```bash
"$INSTALL/driver/venv/bin/python" -B "$BUNDLE/repo/scripts/deveval_offline_package.py" \
  prepare-company --bundle "$BUNDLE" --installed "$INSTALL" \
  --output "$PREPARATION" --gateway "$GATEWAY_JSON"
```

This command rebuilds three sanitized snapshots, runs official reference and
deliberate assertion-negative controls on all fixed 30 tasks, writes local
absolute-path runtime/mapping files, and invokes only manager `prepare`.
There are zero model calls. All 30 reference and 30 negative controls must pass;
failed environments block the run, without replacing tasks. New controls are
bound directly to the final plan, so no local visibility-amendment bridge is
needed. Private logs stay inside `PREPARATION`; stdout contains metadata only.
Controls begin with no `.eggs` files and a fresh empty `PIP_CACHE_DIR`, without
changing `HOME`. `PIP_NO_INDEX=1`, a hash-verified local-only `PIP_FIND_LINKS`,
disabled cache use, and scoped Python socket/DNS audit guards cover worker,
setup and pip child processes. The guard is a Python reproducibility check,
not an operating-system network namespace or an adversarial native-code sandbox.
Missing guard evidence or any blocked network operation prevents admission.
The model gateway remains separate so the later model run can reach the configured
internal vLLM endpoint. This guard evidence covers dependency setup, controls,
and official grading. Generated-test children using Python `-I` do not inherit
the `sitecustomize` guard automatically; no equivalent network-isolation claim
is made for them. Each project receives an exact control-derived `.eggs`
path/hash allowlist; arbitrary new dependency files are never exempted from the
grader's source-integrity check. Allowlists and support manifests are frozen in
the new local runtime before manager preparation.

After `company-preparation.json` says `PREPARED_NO_MODEL_CALLS`, execute its
`run_command` array as a subprocess argument list (do not join it into a shell
string). For example:

```bash
"$INSTALL/driver/venv/bin/python" -B -c \
 'import json,subprocess,sys; r=json.load(open(sys.argv[1])); raise SystemExit(subprocess.call(r["run_command"]))' \
 "$PREPARATION/company-preparation.json"
```

The manager first builds fresh DISCOVERY/VERIFICATION memory, freezes it, then
collects every VALID/TEST solution before official grading. Budgets remain 600
seconds, 24 actions, four generated-test runs and four sessions per cell, with
two workers. There is no automatic rerun of interrupted model work. Retain its
metadata, source references and infrastructure failures when reporting results.
Generated tests carry model-generated expectations, not official oracle status.
If no L3 procedure qualifies, L2 evaluation still runs; FULL may equal NO_L3 and
an L3-effect claim is unavailable. The pilot shares repository identity across
splits and does not establish generalization to unseen repositories.

After the manager exits with `COMPLETE` or `COMPLETE_WITH_UNRESOLVED`, publish
the metadata-only audit outside the experiment directory:

```bash
"$INSTALL/driver/venv/bin/python" -B "$BUNDLE/repo/scripts/deveval_repository_results.py" publish \
  --run-root "$PREPARATION/experiment" --output "$PREPARATION/results-001.json" \
  --plan "$BUNDLE/repo/configs/skhynix_v1/deveval_002_plan.json" \
  --runtime "$PREPARATION/runtime.local.json"
```

This checks sealed collections, grade provenance, source hashes, bank scope and
paired denominators without model/grader calls. Preserve unresolved cells and
actual layer exposure. It does not turn L3=0 into evidence for an L3 effect.

## Build or refresh the transfer bundle on the preparation machine

Run the helper with the driver environment after the curated sources are
committed. `--draft` is permitted only for a clearly labeled packaging test.
The build takes standalone interpreter directories and prebuilt wheelhouses;
it performs no dependency download or model call itself.

```bash
python -B scripts/deveval_offline_package.py build --bundle NEW_BUNDLE \
  --native-python NATIVE_STANDALONE_DIRECTORY --driver-python DRIVER_STANDALONE_DIRECTORY \
  --native-wheels NATIVE_WHEELHOUSE --driver-wheels DRIVER_WHEELHOUSE \
  --setup-wheels FOUR_PACKAGE_SETUP_WHEELHOUSE
```

The native wheelhouse was prepared from the recorded 79-package environment
with `pip wheel --no-deps`; `func_timeout` and `kinto-redis` were built from
source before handoff. The actual wheel bytes receive a fresh exact hash lock.
Large assets stay outside Git. Where possible the source archive is hardlinked
on the preparation machine to avoid redundant physical copies; never modify
either link. Python/source/package licenses remain attached to their assets;
the dataset card and individual repository terms are not a blanket new license.
