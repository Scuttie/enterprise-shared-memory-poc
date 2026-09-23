Run these commands from the repository root after the Luna controller reports `COMPLETE`:

```powershell
python -B artifacts/skhynix_v1/lcb_002/pilot-analysis-source-001.py
python -B artifacts/skhynix_v1/lcb_002/exposure-audit-source-001.py --config configs/skhynix_v1/lcb_002_luna_pilot.json --pilot data/skhynix_lcb_002/pilot-001 --output artifacts/skhynix_v1/lcb_002/pilot-exposure-audit-001.json
```

The analysis publishes `pilot-results-001.json`, `pilot-paired-results-001.csv`, and `model-comparison-001.json` here. The comparison includes Astra and Luna TRAIN/OFF/ON metadata with separate model/bank identities and verifies the same ordered enrollment, implementation, budgets, workers, reasoning level, and grader settings. Existing different analysis outputs are refused. `--check-only` validates without writing.

Private-grader `passed` and effective `resolved` are separate. Wrong solutions, known task/session budget exhaustion, missing submission, unexpected tools, and action-budget violations are effective failures. Their unavailable private verdict remains `null`. Transport, grader, interrupted-attempt, and unknown failures remain unresolved `null`; an incomplete run or a claimed complete run containing unresolved outcomes cannot publish final results. CSV encodes these values explicitly as `true`, `false`, or `null`. Private-graded pairs and effective pairs have separate denominators and statistics.

The new exposure audit accepts `--config` explicitly. Its sources must exactly match the current summary's actually captured TRAIN cells, including model, contributor, candidate hash, frozen bank records and capture hashes. Planned training count, actual captures, uncaptured count, and training errors are reported separately. A valid partial training bank is not relabeled as 24 captures. The audit refuses evaluation/test-derived sources and same-family source/target pairs. It never calls retrieval, a model, or a grader.

Both helpers inspect metadata and hash bindings; reports contain no problem, candidate, test, or injected-memory text. New helpers and outputs remain under this directory. The original Astra helpers, outputs, configs, runtime and frozen implementation are unchanged.

After publication, the optional [timing supplement](TIMING_SUPPLEMENT.md) groups the metadata by difficulty/outcome and compares times on the same tasks solved by both arms. The [submission diagnostic](POSTHOC_SUBMISSION_DIAGNOSTIC.md) grades preregistered unsubmitted candidates separately; it never replaces primary scores or writes memory.

Synthetic failure/denominator tests:

```powershell
python -B artifacts/skhynix_v1/lcb_002/test_analysis_helpers.py
```

The earlier Astra exposure helper's `--pilot`/`--output` arguments can select another run, but it hardcodes the Astra config and requires all 24 TRAIN captures. Use this new config-bound helper for Luna, especially if some TRAIN attempts fail.

Exposure records retain the active node at the time of recall. The native runner
may recall on its initial `solution` node before the first successful
`revise_subtask_dag` replaces that node with `subgoal-*`. The audit accepts that
retired initial node only with the frozen implementation, terminal state/solve
hashes, matching checkpoint ledger/source hashes, recalled-node membership,
first successful replacement trace and request/result hashes, expected new
node set, and initial-injection ledger order. It separately counts these
historical initial-node records (nine injections in nine targets in this run).
Arbitrary missing nodes remain errors.
There is no per-injection timestamp; ordering follows the frozen runner's
active-node-only recall and append-only ledger semantics plus the retained
trace. All protected terminal and implementation files are rehashed before
publication. This corrects a final-graph-only audit assumption without changing
retrieval, primary outcomes, or any run artifact.
