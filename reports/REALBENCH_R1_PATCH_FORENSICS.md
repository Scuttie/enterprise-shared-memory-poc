# REALBENCH-R1 Patch Forensics — evidence-based adoption classifier (§1.3)

## Why the R1 "transfer" numbers are not adoption evidence

The R1 analysis (`experiments/realbench_r1/analysis.py::transfer`, now marked SUPERSEDED) counted, per arm,
tasks where the no-memory baseline passed and the memory arm failed ("losses") and the reverse ("gains"). It
then labelled every loss whose applied patch differed from the baseline `PARTIAL_MEMORY_PATTERN_ADOPTION`.

Two problems:
1. **A different failing patch is not adoption.** The model may have written unrelated wrong code that has
   nothing to do with the injected memory. Labelling it "pattern adoption" overstates memory's causal role.
2. **The R1 artifact cannot support reclassification.** The R1 runner excluded `applied_patch` from the
   results JSON (`{k: v for k, v in r.items() if k != "applied_patch"}`), and the patches lived only in the
   ephemeral CI Postgres. So the R1 main losses cannot be re-examined offline at all.

## Replacement: `experiments/patch_forensics.py`

`classify_loss(memory_patch, base_patch, source, injected, exec_ok, grader_ok)` extracts, via `ast`, the
**imports, called APIs, control-flow structures, and algorithmic operations** of the memory-arm patch, the
no-memory patch, and the source memory. It classifies a loss (or gain) as source adoption **only** when the
memory-arm patch contains an element that is (a) **new** vs the no-memory patch and (b) **present in the
source**. Evidence classes:

| Class | Condition (all require the element be NEW vs base AND present in source) |
|---|---|
| `EXACT_SOURCE_OPERATION_ADOPTION` | memory patch adopts the source's full operation set |
| `PARTIAL_SOURCE_OPERATION_ADOPTION` | adopts some (not all) source operations |
| `SOURCE_API_CALL_ADOPTION` | newly calls / imports an API present in the source |
| `SOURCE_CONTROL_FLOW_ADOPTION` | newly uses a control-flow pattern present in the source |
| `UNRELATED_IMPLEMENTATION_ERROR` | different failing patch with **no** new source element (or memory not injected) |
| `PARSER_OR_APPLY_FAILURE` | patch absent or does not parse |
| `GRADER_FAILURE` | evaluator itself errored (not a code defect) |
| `UNCLASSIFIED` | injected + parses but source signature unavailable |

Unit coverage (`tests/realbench/test_patch_forensics.py`, 10 tests) explicitly includes the
`UNRELATED_IMPLEMENTATION_ERROR` path, the "element must be new vs base" guard, non-injected → unrelated,
parser/grader precedence, and each adoption class.

## Where evidence-based forensics are actually computed

Because R1 patches were not persisted, evidence-based adoption is reported on runs that **do** persist raw +
applied patches with a per-source-task signature (imports/apis/control-flow/operations tags):
- **REALBENCH-R1.1 diagnostic** (§2) — reuses the observed 120 MBPP+ targets, persists patches, reports
  AST/API adoption descriptively (mechanism only, no confirmatory p-value).
- **BigCode-R2 main + safety subset** (§13) — the primary evidence-based transfer/adoption report.

`analysis.py::transfer_forensic(by, source_sig_by_tid)` is the shared entry point; it delegates to
`patch_forensics.summarize` and never infers adoption from Pass@1.
