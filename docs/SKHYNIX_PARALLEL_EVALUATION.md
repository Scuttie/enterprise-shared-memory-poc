# Parallel SK hynix evaluation

New evaluation cohorts can run up to four independent native solves concurrently.
The default remains one. Preparation, official grading, quarantine capture,
journal writes, and cleanup stay in the parent process. Training remains serial.
This changes evaluation orchestration, not the model, reasoning effort, per-task
request/time budgets, or frozen memory bank.

The currently running v19 experiment uses its existing frozen source snapshot.
Updating this repository does not activate parallel execution in that process.
Existing frozen configurations, checksums, completed results, and live workspaces
must not be edited to enable this feature.

## Configure a new evaluation

For a **new** `trimem_skhynix_architecture_scale_pipeline.py` configuration, add:

```json
{
  "evaluation_max_workers": 2
}
```

The value must be an integer from 1 through 4. Omitting it preserves the serial
behavior and old serial report format. The same declared limit applies to
development OFF, development ON, and final evaluation; training is unaffected.
The configuration, executing controller, and helper source references must be
frozen normally against the new implementation. Historical continuation
controllers such as v19 do not gain this option automatically.

For a new, already enrolled evaluation cohort created with the updated frozen
cohort helper, the direct entry point is:

```sh
python scripts/trimem_skhynix_architecture_cohort.py run \
  --root /absolute/path/to/new-evaluation/run/cohort \
  --max-workers 2
```

`--cell-limit` optionally bounds how many cells the invocation advances. It does
not change the per-problem tool or time budget. Use the same `--max-workers` on
later invocations of the cohort. Parallel execution records an immutable
`parallel-policy.json` and its hash reference before dispatching work. A started
serial cohort cannot be silently switched to parallel, and an established
parallel limit cannot be changed during resume.

## Isolation and failure behavior

- Each native solve runs in a separate spawned process against its own existing
  cell workspace, broker, session, and output directory. The child verifies the
  pinned runtime source before launching native work.
- The parent alone writes the cohort's ordered, hash-linked journal. Different
  problems can overlap; the OFF and ON arms of the same problem never overlap.
  Task-level cleanup waits for the required arms and evidence.
- The evaluation bank is shared read-only. Evaluation captures remain in their
  separate quarantine and do not update that bank.
- A dispatch receipt is retained before launching a child. A missing or failed
  completion after dispatch is blocked for inspection; it is not treated as an
  untouched problem and automatically launched again.
- On an error, the scheduler stops assigning new cells and drains already
  started work before releasing ownership. Their valid results remain retained,
  and a later successful completion cannot hide the blocked state. Model and
  grading attempts are not retried to improve an outcome.
- The existing disk reserve is checked before preparing another cell. This is
  not a reservation of future image space or a provider quota guarantee. Start
  with two concurrent solves and measure resource use before increasing it.

## Interpret timing and results

The reported limit is the maximum number of in-flight native solves, not a count
of cumulative handoff workers, total processes, or simultaneous grader jobs.
Preparation and grading can overlap other problems' native solves, but only one
parent performs those stages at a time. Two workers therefore do not guarantee
twice the throughput.

Parallel policy references and the declared limit are exposed in cohort status
and opted-in scale evaluation reports. Keep serial and parallel timing cohorts
separate when comparing latency, and use the same concurrency policy for the
OFF/ON comparison. Sequential and parallel runs still use one attempt per
problem and condition; parallel execution does not select the best of several
solutions.

Each child completion receipt records `started_at`, `ended_at`, and
`wall_seconds`, and is hash-bound in the parent journal. Use that receipt to
separate child execution time from the parent's collection delay. In particular,
`SOLVE_COMPLETE.at - SOLVE_STARTED.at` can include waiting while the parent grades
another completed problem; it is not pure native execution time under parallel
scheduling.

## Verification

The tests use synthetic task artifacts and isolated child processes, without
model requests, Docker benchmark execution, or official grading calls:

```sh
PYTHONPATH=scripts:src python -m pytest \
  tests/unit/test_trimem_skhynix_architecture_cohort.py \
  tests/unit/test_trimem_skhynix_architecture_cohort_parallel.py \
  tests/unit/test_trimem_skhynix_architecture_scale_pipeline.py \
  tests/unit/test_trimem_skhynix_parallel_pipeline.py
```

Run the full cohort suite on Linux/WSL: some existing fixtures exercise Linux
file locking and filesystem guarantees. An actual provider concurrency limit or
benchmark speedup must be measured separately when a new parallel evaluation is
activated.
