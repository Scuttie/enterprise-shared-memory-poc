Run after the existing final analysis publishes `pilot-results-001.json` with
`status: COMPLETE` and `pilot-paired-results-001.csv`:

```powershell
python -B artifacts/skhynix_v1/lcb_002/pilot-timing-source-001.py
```

The output is `pilot-timing-outcomes-001.json` in this directory. Use `--check-only`
to validate without publishing. Explicit `--results`, `--pairs`, and `--output`
paths support another pair of reports with the same schema. Different existing
outputs are refused. Each report binds both input files and the helper by SHA256.
The helper never follows references inside the JSON or opens run directories.

OFF/ON results are grouped by difficulty, effective outcome, and resolved
`true`/`false`/`null`. Missing submissions/protocol failures, budget exhaustion,
privately graded wrong solutions, and unavailable outcomes stay distinct.
Times are native solve wall seconds. Means and medians use the reported number
of timed attempts; missing times are not zero. The report preserves all-attempt
denominators and provides separate groups for successful and failed attempts.
It cross-checks CSV counts and timing aggregates against the final JSON.

Paired timing includes only tasks solved by **both** arms. It reports selected
IDs, OFF/ON times, per-pair ON-minus-OFF seconds, and joint timing denominators.
Negative differences mean ON was faster for that observed pair. Selection on
success, concurrent activity on the same machine, task order, service latency,
and budget censoring prevent a causal speedup claim. This is descriptive pilot
analysis, not evidence about untouched test performance.

TRAIN aggregate timings/counts are retained from the final JSON. TRAIN
per-difficulty and per-outcome timings remain unavailable because neither
allowed input contains TRAIN per-cell metadata. No additional source is opened
to fill that gap. The existing final publisher refuses unresolved COMPLETE
runs; this supplementary helper nevertheless preserves explicit nulls if they
appear in a mutually consistent report pair.

Synthetic validation (no benchmark payloads or model/grader calls):

```powershell
python -B artifacts/skhynix_v1/lcb_002/test_timing_supplement.py
```
