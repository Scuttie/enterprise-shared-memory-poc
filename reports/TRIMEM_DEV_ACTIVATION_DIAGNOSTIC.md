# TriMem V1 - post-DEV activation diagnostic

## Status

This is a post-outcome mechanism diagnostic prompted by the zero-injection
result of DEV EXEC-022. It is not an M2 selection run, a held-out estimate, or
evidence for a final performance claim.

```text
TRIMEM_DEV_ACTIVATION_DIAGNOSTIC = COMPLETE_36_OF_36_OFFICIAL_CELLS
EXECUTION_HEAD = be0aa3fc567cda91b05df9794d83ff0bfc76a540
WORKFLOW_RUN = 34401179674_ATTEMPT_2_SUCCESS
HISTORICAL_ABSTENTION_ROOT_CAUSE = UNIDENTIFIABLE_FROM_RETAINED_EVIDENCE
SOURCE_BANK = FROZEN_VERIFIED_TARGET_DISJOINT_12_OF_12
MODEL = gpt-5.4-mini-2026-03-17
MODEL_EXECUTION = COMPLETE_36_OF_36
OFFICIAL_GRADER_EXECUTION = COMPLETE_36_OF_36
PAID_MODEL_CALLS_THIS_DIAGNOSTIC = 372
USD_THIS_DIAGNOSTIC = 2.940267450000
VERDICT = FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED
HELDOUT_EXECUTED = NO
COMPONENT_ABLATION_EXECUTED = NO
PROTECTED_ENVIRONMENT_SECRETS_REMAINING = 0
```

## Final diagnostic result

Run [34401179674 attempt 2](https://github.com/Scuttie/enterprise-shared-memory-poc/actions/runs/34401179674)
completed successfully on the exact execution head. All 36 fresh cells reached
a terminal journal state and all 36 were scored by the official grader. The
public aggregate status is `COMPLETE_36_OF_36_OFFICIAL_CELLS`.

| arm | injected tasks | total injections | terminal/12 | partial patch | no-op | solved/12 | Pass@1 | model calls | USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 | 0 | 0 | 12 | 1 | 11 | 1 | 8.33% | 119 | 0.839772300000 |
| C1 | 12 | 12 | 12 | 1 | 11 | 0 | 0.00% | 124 | 1.046211000000 |
| C2 | 12 | 12 | 12 | 1 | 11 | 1 | 8.33% | 129 | 1.054284150000 |

Equal maximum budgets did not produce equal actual compute. Exact accounting
was:

| arm | decomposition | solve | extraction | input tokens | cached input | output tokens | model wall ms | tool wall ms | grader wall ms | task wall ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C0 | 12 | 95 | 12 | 732,130 | 9,984 | 66,092 | 463,344 | 1,446 | 587,720 | 1,217,154 |
| C1 | 12 | 100 | 12 | 935,930 | 16,640 | 78,999 | 621,972 | 1,412 | 586,054 | 1,380,818 |
| C2 | 12 | 105 | 12 | 1,019,431 | 13,312 | 66,377 | 610,093 | 1,853 | 586,677 | 1,392,991 |
| total | 36 | 300 | 36 | 2,687,491 | 39,936 | 211,468 | 1,695,409 | 4,711 | 1,760,451 | 3,990,963 |

There were no C2-minus-C0 target-level flips. C2-minus-C1 had one
fail-to-pass flip, `swebench_verified--django__django-16100`; C1-minus-C0 had
the opposite pass-to-fail flip on that same target. Django was the only
officially solved target in C0 and C2. C1's only partial patch was Bat and did
not pass. The C0 SymPy cell contained one model failure, recorded a canonical
no-op, and was still officially graded; execution continued as required.

The adaptive horizon granted two four-step extensions: C1 Bat and C2 Django.
There were no second extensions, `AGENT_COMPLETED` occurred 0 times, and
`PER_SUBTASK_STEP_CAP_REACHED` occurred 35 times. The remaining terminal cell
was the contained C0 SymPy model failure.

## Abstention diagnosis

The retained EXEC-022 evidence cannot support a fabricated six-way split of
the historical 179 decisions. Fourteen are known intentional M0 no-memory
controls. The other 165 lack candidate funnel, scores, thresholds, Q values,
and stable recall-attempt identities in the historical raw schema, so their
final reason remains `UNKNOWN_NOT_RECORDED_EXEC_022`. The committed 179-row
projection records every requested field as known, not applicable, or unknown;
it does not invent target/subtask attribution. The historical zero-injection
root cause therefore remains unidentifiable from retained evidence.

The fresh C1/C2 telemetry is fully classified:

| requested reason class | count |
| --- | ---: |
| no candidate generated | 50 |
| rejected by permission/tenant/repository/path/version/provenance/leakage gate | 0 |
| below semantic/PPR threshold | 0 |
| DQN selected ABSTAIN despite valid candidate | 0 |
| context/injection budget rejection | 1 |
| other explicit reason | 0 |

The single context/injection-budget rejection is C2 Django's second recall
after the same top candidate had already been injected
(`ALREADY_INJECTED_REJECTION`). C1 recorded 24 `NO_CANDIDATE_GENERATED` and 12
`INJECTED` decisions. C2 recorded 26 `NO_CANDIDATE_GENERATED`, 12 `INJECTED`,
and one `ALREADY_INJECTED_REJECTION`. `Q_USE` and `Q_ABSTAIN` are `null` and
the router policy is `N/A`, because the frozen DQN is a post-grade retention
policy rather than a recall-time USE/ABSTAIN router.

Only `ORG_SEMANTIC` supplied candidates. C1 covered 12/12 targets with 12 safe
candidate observations; C2 covered 12/12 with 13 observations because of the
extra Django recall. `EPISODIC` and `USER_SEMANTIC` coverage was 0/12. Every
accepted ORG candidate had one candidate before and after safety filtering,
embedding score 1.0, PPR score 1.0, minimum confidence 0.1, and minimum margin
0.0. Both C1 and C2 injected the same memory into the matching target, so the
forced-safe bypass did not increase exposure in this frozen bank.

## Injected-memory overlap

The following twelve source memories were each injected once in C1 and once
in C2. All source repositories matched their target repositories; all sources
were independently verified historical PRs and none was target-derived. For
all rows, target-issue path overlap and error overlap were zero. Active-subtask
error overlap was also zero. The table's active-subtask column is the C1
projection; the fixed target-issue overlap columns apply equally to C1 and C2.

| target | injected memory / source PR | C1 active file or symbol overlap | target-issue API overlap | target-issue token overlap |
| --- | --- | --- | ---: | ---: |
| `django__django-16100` | `dev-oracle-pr-cc2b26f26fea85cbc5e74038` / `django__django--7143` | `django/contrib/admin/options.py` | 0 | 7 |
| `sympy__sympy-23262` | `dev-oracle-pr-4812e05cf6aa81c3adb7f0f9` / `sympy__sympy--21546` | none | 0 | 14 |
| `sphinx-doc__sphinx-11445` | `dev-oracle-pr-683fd95f612e2df649b1706b` / `sphinx-doc__sphinx--6746` | `sphinx/transforms/i18n.py`; symbol `rst_prolog` | 0 | 5 |
| `matplotlib__matplotlib-25311` | `dev-oracle-pr-ed4e79f0ae2c09ac44398c33` / `matplotlib__matplotlib--23913` | `lib/matplotlib/tests/test_legend.py` | 2 | 12 |
| `mui__material-ui-29880` | `dev-oracle-pr-3bdfdaaa518355d9e1f9b9d8` / `mui__material-ui--24794` | none | 2 | 26 |
| `ponylang__ponyc-1981` | `dev-oracle-pr-24cbaa00f46b3199d9590a95` / `ponylang__ponyc--1130` | `src/libponyc/expr/lambda.c` | 0 | 1 |
| `clap-rs__clap-3960` | `dev-oracle-pr-c931d65f581b85c01eef7e48` / `clap-rs__clap--3334` | none | 0 | 24 |
| `facebook__zstd-938` | `dev-oracle-pr-7be5cc2797a009597e08cf88` / `facebook__zstd--656` | `programs/util.h` | 1 | 2 |
| `sharkdp__bat-1276` | `dev-oracle-pr-f1e7262f5174a5eea5458477` / `sharkdp__bat--579` | `src/printer.rs` | 0 | 9 |
| `catchorg__Catch2-1616` | `dev-oracle-pr-0859e0498c3f1036248ea022` / `catchorg__Catch2--845` | none | 0 | 15 |
| `clap-rs__clap-3394` | `dev-oracle-pr-e695df4afd5cce205694e452` / `clap-rs__clap--2876` | none | 0 | 10 |
| `cli__cli-869` | `dev-oracle-pr-1b9c47efc4c90f09bc94c418` / `cli__cli--302` | `command/pr.go`, `command/pr_checkout.go`, `command/pr_checkout_test.go` | 2 | 18 |

Across the twelve distinct target-memory pairs, repository overlap was 12/12
in each arm. C1 active declared overlap covered files on 7/12 targets (9 file
entries), symbols on 1/12, APIs on 0/12, and errors on 0/12. C2 covered files
on 5/12 targets (7 entries), symbols on 1/12, APIs on Django only (2 entries:
`router.db_for_write` and `transaction.atomic`), and errors on 0/12. The frozen
target-issue comparison, identical for both arms, had API overlap on 4/12
targets (7 entries), symbol overlap on 1/12, path and error overlap on 0/12,
and positive token overlap on 12/12 (143 tokens per arm).

## Diagnostic verdict

Safe candidate coverage was sufficient at 12/12, but C2 equalled C0 at 1/12.
The frozen primary verdict is therefore:

```text
FORCED_MEMORY_NO_DEV_LIFT_READER_OR_CONTENT_LIMITED
```

C1 did activate and inject on all twelve targets, but it scored 0/12 versus
C0's 1/12, so `CURRENT_ROUTER_ACTIVATED_POSITIVE` does not apply. Because C1
and C2 exposed every target to the same memory, C2-minus-C1 is not a
forced-versus-abstained router contrast in this execution. The result shows no
DEV lift from these safe historical memories under this reader; it does not
measure HELDOUT performance.

## Evidence custody and cleanup

- Public aggregate artifact: ID `10126754892`, raw ZIP SHA-256
  `c289adf462554901ffad0801e9ce40acef8f494a60dfb6c1f0b04f68e4eab906`.
- Encrypted restricted artifact: ID `10126758836`, raw ZIP SHA-256
  `b4d5011dcaa094f84099cb3cb86550db7878ab6b326d5bf3b7975a208a74a17f`.
- Inventory artifact: ID `10126760434`, raw ZIP SHA-256
  `954204416e69b774221d28f99273b23fa5b1ca505f7b6b9d13ef9a5af9296215`.
- Remote-custody artifact: ID `10126763114`, raw ZIP SHA-256
  `7f146587d165b366736e7c31a1e3071be850229fb8bb6c0dd18d8f02a1660ac4`.
- Public aggregate SHA-256:
  `50523d22a49410377eb9234ca324f050229eb1403c53da1d7359a84b29bdd498`.
- Restricted inventory seal:
  `2b06f38e4eee082dcab39a99eb6f63ea9c37dce65ef69c777db19301b2e5fecb`.

The four downloaded raw ZIPs matched GitHub artifact metadata exactly. A
zero-plaintext streaming decrypt matched all 4,095 restricted files and
113,065,654 bytes bidirectionally against the inventory. Recomputed,
restricted, and public aggregate bytes were identical. Workflow custody and
plaintext cleanup passed; the three protected environment secrets were
deleted and the environment is empty; the ephemeral runner was deregistered
and its exact 774 MB local runner directory was removed. The original user
API-key file was not modified or deleted.

## Pre-execution recovery history

Run `34386328359` attempt 2 passed all 36 base-only workspace preflights but
stopped in the first pre-spend solver sandbox: the capability-free
image-default root identity could not enter the owner-only `/testbed` bind.
The separate EXEC-004 report preserves exact failure custody and zero
task/model/grader/token/USD accounting. The runner now uses the frozen
non-root checkout owner `1000:1000`; capabilities remain fully dropped and
permissions remain private. A new workflow stage exercises all 12 exact image
sandboxes, including writeability, history/mask isolation, and effective UID,
before any API-key step.

The current runner/executor bytes passed the exact frozen 12-target rehearsal
twice on the protected WSL/Docker topology with identical report SHA-256
`076c892f481fc246ba538d5fa714809696fbe4550d6056c8ea537cbac6d3b8b0`.
Each pass used 12 masked solver probes plus 8 raw Multi-SWE image probes,
kept all 12 mode-0700 checkouts pristine, and made zero model, grader, token,
or paid calls. The separate non-mutating path used by fresh scientific
execution also passed twice with identical report SHA-256
`5f8f5b98570e444e09bffc27b82a7bd7c18fdb428243ff28ad08d34176c08fe7`.
Across these four local passes the infrastructure totals were 48 image-config
inspections and 80 non-grader probe containers; model/API, official grader,
token, and USD totals remained zero. These hashes were initially non-durable
local observations. Run 34401179674 later preserved the rehearsal evidence on
the exact remote head, after all 22 exact-head credential-free workflows had
passed, and entered execution only with the fresh attempt-2 approval.

The rehearsed byte identities were executor
`b0285478396dc6310f66f0ae9d13921fbf306689b67037160f54021450ca0650`,
Docker runner `18543a9980f36e20ea7489812f7b8a3cbcd65b2cd2c46ad6bfd36a2a35fedd39`,
and tool-environment lock
`3329bd288136dd64dd1e24ecd5140bdd18c59050125f7b38f14584aebcf80111`;
the Windows staged files and executed WSL copies matched exactly.

Run `34379166677` attempt 2 passed the protected approval gate, frozen image
materialization, credential-format check, and run-bound billing-key commitment.
The executor then stopped before paid-client construction because one exact
Git-blob-normalized checkout still appeared modified to porcelain status. Both
the initial invocation and its same-attempt resume retry failed closed. The
separate EXEC-003 report preserves the evidence, 13 image-pull accounting, and
zero task/model/grader/token/USD result. Exact Linux reconstruction identified
one ponyc and 30 zstd committed-CRLF paths whose immutable LF blob bytes were
correct while the mutable index/stat state was stale. Literal-pathspec,
tracked-only hermetic renormalization followed by exact commit-tree and
empty-status checks corrects that portability boundary; the corrected
12-target rehearsal passes.

Run `34372037270` attempt 2 is a second spent, zero-work pre-execution
failure. It proved the corrected preinstall path, dataset checkout, pinned
harnesses, official loader, grader factory, and complete failure-custody path.
The approval gate then repeated the same import error because its own command
still used `-S` after the editable installation. The separate EXEC-002 report
preserves the exact evidence and recovery boundary. No image, OpenAI, executor,
or official grader step was reached.

Run `34359716328` attempt 2 is a spent, zero-work preflight failure, not a
scientific or evaluator run. The frozen-source check passed, after which the
uninstalled source package was absent from the isolated import path. The
separate failure report preserves the exact run, evidence, zero-call
accounting, and recovery boundary. The correction changes only execution and
custody plumbing: the scientific matrix, source bank, model, prompts, tools,
parsers, budgets, images, grader locks, and verdict rules are unchanged.

## EXEC-022 retrospective boundary

The accessible public artifact proves 78 recall events, 179 bank-level
abstentions, and zero injections. The stream totals are:

| stream | recall attempts | bank-level abstentions | injections |
| --- | ---: | ---: | ---: |
| M0 | 14 | 14 | 0 |
| M1 | 13 | 12 | 0 |
| M2-baseline | 13 | 39 | 0 |
| M2-precision | 13 | 39 | 0 |
| M2-recall | 12 | 36 | 0 |
| M2-balanced | 13 | 39 | 0 |

The 14 M0 decisions are the intentional no-memory control and are not recall
failures. The M1 totals also show that one selection did not become an
injection, but the accessible aggregate cannot identify its target, subtask,
or post-selection rejection.

The per-cell `events.jsonl` files are inside the encrypted restricted archive.
The custody copy is intact, but the evidence passphrase is not available in
current local or protected-environment custody. More importantly, the old raw
event schema recorded only task/arm/active-node, injections, bank trace, and
post-selection rejections. It never recorded the requested candidate funnel,
raw embedding/PPR scores, threshold snapshot, or a stable recall-attempt ID.

Consequently the original 179 row-level decisions cannot be reconstructed
without inventing data. A deterministic 179-row aggregate projection is now
committed with every requested field: 14 rows preserve only the known M0
no-memory-control classification, while all decision fields in the remaining
165 rows are explicitly `UNKNOWN_NOT_RECORDED_EXEC_022`. Synthetic
`projection_row_id` values are reporting identities, never recovered recall,
target, or subtask identities. See the recoverability artifact and
`artifacts/trimem_v1/dev_activation_diagnostic/exec_022_abstention_projection.json`.

## DQN correction

The frozen DoubleDQN is a post-grade retention policy. Its actions are
`FORGET`, `MOVE_TO_EPISODIC`, and `MOVE_TO_SEMANTIC_CANDIDATE`. It does not
choose recall-time `USE` versus `ABSTAIN`. Fresh diagnostic telemetry therefore
uses `null` for `Q_USE`/`Q_ABSTAIN` and `N/A` for router policy. Historical M0
control rows say not applicable; the other 165 historical projection rows stay
unknown because their original decision snapshots were not retained.

C2 is implemented as `FORCED_SAFE_TOP1`: it shares C1's candidate generation,
canonical reload, and safety filters, then bypasses only the deterministic
confidence and margin admissions. There is no learned or DQN recall-time
router to bypass; C2 does not add one or change the retention DQN.

## Frozen diagnostic shape

The diagnostic uses the exact ordered 12-target DEV manifest and a 3 by 12
matrix:

- C0 - no memory;
- C1 - M2 recall with the current confidence/margin gate;
- C2 - the highest-ranked safe candidate, at most one per subtask and three
  per task, with confidence/margin bypassed.

All arms use the same opt-in adaptive-horizon rule. The base subtask horizon is
8. A successful tool result can earn a four-step extension when the canonical
Git diff UTF-8 byte high-water strictly increases or a recognized test command
first passes. A fresh progress event can earn one further four-step extension,
for a maximum subtask horizon of 16. The existing global 24 solve-call and
24 agent-step ceilings remain binding. Equal limits do not imply equal actual
compute, so every cell records solve/extraction calls, tokens, wall time, and
USD independently.

Extension eligibility and its two-extension allowance are keyed to the active
subtask/node, never pooled into a task-level extension allowance. The canonical
workspace diff/test high-water remains task-wide so identical progress cannot
be replayed by a later subtask.

The reader protocol is the exact `recall` candidate selected by EXEC-022's
frozen DEV rule, not the generic baseline policy. Its policy-file SHA-256 is
`1985ca2cceaa6ebdc02d4bd320b318a47a8144f64bde5ad0da8367c777d3d85c`;
the historical RuntimeLock hash is
`f38dbb148e7c7e0573bfab87400ebb9c0c4a786f888d4315d214fdca289fb581`.
The only registered runtime change is enabling the same adaptive horizon in
all three arms, producing RuntimeLock hash
`c31840b1413fe045e94bef1949419f72c856eda9abbcc69c52bffc700bbf4652`.

## Source-bank execution boundary

A fresh empty namespace plus twelve targets from eleven repositories cannot
measure a forced-memory upper bound reliably. C1 and C2 therefore require the
same immutable, read-only bank of independently verified, target-disjoint
source fixes before target 0. C0 performs no retrieval and no injection. Bank
coverage is measured from C2's safe candidate pool before its score-admission
bypass.

Before diagnostic outcomes, the frozen source-selection plan maps each target
to one different same-repository public merged PR. This fixed mapping is not an
automatic admission: each PR must still satisfy every chronology, version,
provenance, and safety check, and a rejected PR remains an uncovered target
rather than being replaced post hoc.

The bank must prove, for every source record:

- a canonical public source-PR row and exact source-row hash;
- a different source PR from every DEV target solution PR;
- source-owned issue/fix content only, never target gold, target tests, or
  target-derived memory;
- repository, path, permission/tenant, provenance, quarantine, and leakage
  eligibility;
- a public source-fix time and target-version compatibility/ancestry result;
- immutable canonical payload and index digests;
- at least one independently verified source record overall; a target with no
  safe candidate remains an explicit `NO_SAFE_CANDIDATE` assignment.

The runtime-facing metadata is exact: `PUBLIC_READ`, `BENCHMARK_ISOLATED`,
`EXACT_SOURCE_COMMIT`, and wildcard `**` path scope. Source `changed_paths` are
retained separately for overlap evidence and deterministic ranking.

The dedicated manifest is now frozen at raw SHA-256
`8a0600e8d18f5234bd35d675f8e5cb8eb827aac4e4498547db02fc689a83d309`;
its logical snapshot SHA-256 is
`55fe3c03ef545181986605166247f78896c5fcd2db37535d19f574781c16be1e`.
The pre-execution source-selection plan raw SHA-256 is
`10e9e6937926e148eaedce73aa3f3cfea0538744b594968d91eca13c597763ff`,
and the final public chronology-cache raw SHA-256 is
`44aa296a75fa7e985d825c1439b2724a297a0c3b2138447f0b6b4a1215246a10`.
All 12 targets have exactly one safe frozen assignment, with zero uncovered
targets. Each assignment is hash-bound to the exact runtime public instruction
from its pinned benchmark row and to the true public problem object: eleven
GitHub issues that lack a `pull_request` member and Django Trac ticket #32603.
The instance-ID suffix is treated only as the target solution-PR identity and
is never used as the target issue number. The chronology cache and all 60
public raw responses (59 GitHub plus one Trac page), together with 12 dedicated
payloads, are content-addressed and included in the explicit research freeze.
This pre-execution gate was later satisfied by exact head
`be0aa3fc567cda91b05df9794d83ff0bfc76a540` and run 34401179674 attempt 2.
Partial coverage remains a valid execution shape for future rebuilt banks, but
anything below 12/12 takes verdict precedence as
`RETRIEVAL_BANK_COVERAGE_INSUFFICIENT`.

Every one of the 36 solver workspaces is fetched at its exact base SHA and then
reduced to a single-commit Git object closure before a paid client exists.
Committed CRLF checkout transforms are replaced with immutable Git-blob bytes;
only those transformed tracked paths are then renormalized to refresh index
checkout state, with `write-tree` required to equal the pinned commit tree and
porcelain required to be empty. The credential-free 12-target rehearsal
enforces that status before an execution approval can lead to paid work.
Branches, tags, remotes, reflogs, alternates, promisor state, and unreachable
post-base objects are removed and audited. The production solver runner keeps
networking disabled and exposes only that checkout. For Multi-SWE images it
also masks the baked repository Git database and the evaluator-generated
`fix.patch`, `test.patch`, and five harness scripts. A zero-model disposable
pre-billing rehearsal starts the exact runner for all 12 targets and fails
closed unless the base-only
history, empty masks, secret-free environment, fixed effective UID/GID,
loopback-only network, required toolchain paths, read-only root/Git mounts,
writable HOME tmpfs, host-created mode-0600 file update, nested checkout write,
and post-probe pristine checkout are observed. The workflow performs this
mutating-but-reversible rehearsal before its first API-key-bearing step; the
fresh 36-cell executor repeats the same identity, toolchain, history, masks,
mount-mode, network, and pristine checks without mutating its scientific
checkout before constructing a paid gateway.
Docker/Git subprocesses use fixed non-secret environments, and the OpenAI HTTP
client does not inherit host proxy or TLS environment routing.

The separate execution workflow is now wired without granting that approval:
the exact feature-branch push is a clean, credential-free attempt-1 run/head
handshake, and only a rerun of that same run as exact attempt 2 can enter the
existing protected benchmark environment. This push contract avoids relying
on branch-only `workflow_dispatch`, which GitHub does not expose until a
workflow exists on the default branch. Before the approval
secret is read, that job verifies the frozen contract, DEV dataset/checkouts,
pinned harnesses, official loader, and grader factory. Its ephemeral runner
requires the unique `trimem-dev-activation-diagnostic` label and omits the
historical `trimem-benchmark` label, so the two protected workflow families
cannot select one another's runner. After a fresh exact approval passes, it
verifies digest-only image materialization and completes the pre-billing
sandbox rehearsal before the first local key-format check. It then verifies
the key's HMAC commitment against the diagnostic ID, exact head, source-bank
manifest, run ID, attempt 2, model snapshot, and nonce before any
executor/provider/network use, runs a live image digest reinspection, compiles
all 12 source-store views,
prewarms the pinned 384-dimensional retrieval embedder, and then runs the 36
cells serially. The run-bound approval may live for at most seven
days, covering the 120-hour job ceiling without opening an attempt-3 route. A
single retry stays inside attempt 2 and uses the durable
resume binding when it exists; attempt 3 is not an execution route. Within a
cell, the grader may retry exactly once only after an explicit pre-container
failure and durable authorization/process-start markers. A started or unknown
grader process is never invoked again and consumes one container
conservatively.

The budget ledger must finalize exactly 36 terminal task keys with no
outstanding reservations. The complete aggregate is then recomputed and
byte-compared before publication.
Restricted stdout/stderr, per-cell reports/checkpoints, raw provider/grader
evidence, approval binding, and image evidence are inventoried, encrypted, and
uploaded. Every protected-job shell uses `umask 077`, so intermediate evidence
remains owner-only even when a later custody step fails. Images are removed
through the exact frozen-alias cleanup contract,
and plaintext is removed only after remote artifact custody is verified.

## Frozen execution caps

The 36 scientific cells permit exactly one decomposition and one extraction
call per cell, at most 24 solve calls per cell, and therefore at most 936 model
calls in total. The protocol canary is outside this request and is frozen at
`authorized=false`, cap 0. Aggregate hard caps are 18,000,000 input tokens,
2,359,296 output tokens, 36 official grader containers/runs, an uncached token
ceiling of `$24.116832`, and a total USD cap of `$25.00`.

## Interpretation

This experiment jointly changes memory routing and permits arm-dependent
adaptive extensions after progress. It is a descriptive
`memory-routing + adaptive-horizon` diagnostic, not a pure content effect.
Coverage insufficiency takes precedence over score comparisons. Negative and
offsetting target flips are reported explicitly. For offsetting zero-net flips,
the primary verdict remains the user-specified no-lift label and the mixed
pattern is preserved as a secondary label. The verdict uses the fail-closed
diagnostic outcome: an official grader pass counts only when no solve/runtime
or extraction model failure occurred. The raw official-grader solved count and
Pass@1 are reported separately. `CURRENT_ROUTER_ACTIVATED_POSITIVE` additionally
requires a C1-positive target flip on a target that actually received a C1
injection; an injection and a positive flip on disjoint targets are not treated
as causal activation evidence.

No HELDOUT run, component ablation, model change, or benchmark generation was
performed. The only new official grading was the authorized 36-cell diagnostic
reported above.
