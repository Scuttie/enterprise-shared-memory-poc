# Missing-submission candidate diagnostic

This is an **exploratory diagnostic, separate from the primary Luna/low pilot score**. A primary `MissingSubmission` remains a model protocol failure with `resolved=false` and no private verdict. This helper asks whether the already generated, unsubmitted candidate passes the official evaluator; it does not repair the submission, revise the primary score, or add training memory.

The selection rule below is fixed before this helper evaluates any actual candidate. The helper and its synthetic tests were prepared without reading actual candidate code or private test payloads. Actual execution requires a separate invocation after the pilot finishes.

## Fixed eligibility and candidate selection

1. Require the primary `summary.json` to say `COMPLETE`, private grading authority to be ready, and the primary manager's existing lock to be released. The helper locks the existing byte without rewriting it. An active or incomplete pilot is rejected before any state/candidate/private-data access or output creation.
2. Include only cells whose primary summary identifies `GENERATION_ERROR`, `MissingSubmission`, `MODEL_PROTOCOL_FAILURE`, `resolved=false`, and `passed=null`. Confirm the cell/solve receipts, task and arm, frozen enrollment, runtime/model/budgets, state hash, and original bank association. Other failures, successful submissions, timeouts, and infrastructure errors are excluded.
3. Scan `state.rejected_actions` backward. Select the **last valid, nonempty string** at `finish.arguments.code` that fits the original frozen UTF-8 code-byte limit. Later missing, nonstring, empty, or oversized code values do not displace an earlier valid value. Lesson validity and claimed correctness play no role.
4. If none exists, select the exact `state.candidate` value only when it is a valid nonempty string and agrees with the last recorded successful `run_public_tests` request, the public-result candidate/test hashes, and the immutable trace references. A public runner result may be PASS, FAIL, or INFRA_ERROR; selection does not prefer passing public tests. The native runner writes `state.candidate` before public execution returns, so an uncorroborated fallback is skipped with a null verdict.
5. Preserve the selected string's exact UTF-8 bytes, including whitespace. Do not fix syntax, change signatures, construct a new solution, or retry an alternate candidate. Persist a metadata-only selection receipt for **all** eligible cells before opening private evaluation authority. Record the selected field path, step, candidate hash/byte count, and original state/receipt hashes.

No candidate or solution is selected using hidden results. No model is called. There is one official grading attempt per selected cell and no automatic restart/resume of an existing diagnostic output directory. If interrupted, retain the partial directory for review; do not silently repeat grading or choose another candidate.

## Evaluation and reporting

Use the same frozen runtime and pinned official `trimem_lcb_grade.py` evaluator, one worker, and six seconds per test case. Copy the manifest-bound gzip evaluation envelope as opaque bytes into the diagnostic data directory; only the official grader decodes it. Predictions use the official OpenAIChat wrapper. If official extraction would change the selected candidate, leave its diagnostic verdict null instead of grading a different source string.

The helper verifies prediction/sample hashes, official commit, evaluator settings, question identity, extracted-code hash, and transport/result consistency. `diagnostic_passed` is a Boolean only for an official `GRADED` result; skipped or unresolved cases stay null. The complete eligible denominator is retained, and a complete-cohort diagnostic fraction is null while any eligible cell is unresolved. A graded-subset fraction is explicitly descriptive.

Candidate files, predictions, opaque private samples, evaluator reports, and transport receipts are written only under `data/skhynix_lcb_002/posthoc-001/`. The repository artifact report contains IDs, hashes, selection/provenance metadata, and official grading summaries, with no code, prompts, test inputs/outputs, or raw error messages. Primary summaries, per-cell receipts, captures, and the frozen bank are never rewritten. Hidden diagnostic results are never given to a model or memory system.

## Run only after primary completion

From the repository root, using the same local Python environment as the manager:

```powershell
python artifacts/skhynix_v1/lcb_002/posthoc-submission-source-001.py run `
  --pilot-root data/skhynix_lcb_002/pilot-001 `
  --runtime data/skhynix_lcb_002/runtime.local.json `
  --output data/skhynix_lcb_002/posthoc-001 `
  --report artifacts/skhynix_v1/lcb_002/posthoc-submission-diagnostic-001.json
```

The runtime path must be the exact frozen runtime file for this pilot. The helper refuses preexisting output/report paths. Exit code 0 means every eligible cell received a Boolean official verdict; exit code 2 means a guard rejected execution or the diagnostic contains skipped/unresolved cases. `COMPLETE` with zero eligible cells yields no diagnostic pass fraction.

Synthetic validation, which performs no model or evaluator calls:

```powershell
python artifacts/skhynix_v1/lcb_002/test_posthoc_submission_helper.py
```

The official evaluator executes candidate Python using the existing runner's process model; this diagnostic does not add a security sandbox or a Docker dependency.
