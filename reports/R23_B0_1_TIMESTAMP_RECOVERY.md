# R23-B0.1 — Credential-free GitHub timestamp recovery

Status: **`R23_X_CHRONOLOGY = PENDING_B0_1`**. This is a partial, fail-closed checkpoint, not benchmark/grader
viability and not a source-target pair freeze.

## Current evidence checkpoint

| field | coverage / value |
|---|---:|
| benchmark rows | 500 |
| fix PR identity confirmed | 98 / 500 |
| fix PR merged_at known | 98 / 500 |
| conservative fix-commit public bound known | 5 / 500 |
| linked issue closed_at known | 4 / 500 |
| linked issue created_at usable as target start | 4 / 500 |
| source_available_at known | 98 / 500 |
| confirmed chronological candidate edges | 8 |
| PR-created proxy ordered edges (not eligibility) | 38,592 |
| source-target pairs selected | 0 |
| paid/model calls | 0 |
| Docker/grader executions | 0 |

The last run stopped automatically at the unauthenticated core-rate reserve (`remaining=2`). A deterministic
oldest-first per-PR queue and a repository page-batch queue are both resumable from the committed cache. Eight bulk
page requests added 38 exact fix PRs (60 to 98 coverage); each accepted list item still passed the same repo, PR
number, base SHA, and created_at identity checks as a single-PR response.

## Load-bearing correction

The pinned parquet `created_at`, stored under the historical audit key `issue_created_at`, exactly matched the fix
PR's `created_at` in every confirmed pull response. It is therefore not proof of when target work began. The 38,592
PR-created-relative orderings are diagnostic only. A chronological candidate edge is emitted only when:

1. the source fix PR is identity-confirmed and has a conservative `source_available_at`;
2. the target has a same-repository issue identified by closing-keyword syntax and its public `created_at` is known;
3. source and target differ; and
4. `source_available_at < target linked-issue created_at` strictly.

UNKNOWN on either side emits no edge. The eight current edges satisfy this predicate, but the graph remains partial
and R23-X source-target selection remains prohibited.

## Provenance and conservative fallbacks

- Script: `scripts/r23_b01_timestamp_recovery.py`.
- Cache: `artifacts/r23/timestamp_cache.json`.
- Raw bodies: `artifacts/r23/timestamp_raw/`; 98 responses are stored as deterministic gzip (level 9, mtime 0),
  reducing 37,774,746 response bytes to 2,209,674 bytes. Every query records URL, UTC query time, selected response
  headers, and both compressed and uncompressed byte counts/SHA-256. No Authorization header or credential
  environment variable is used.
- Graph: `artifacts/r23/chronological_eligibility_graph.json` with canonical edge evidence in
  `artifacts/r23/chronological_eligibility_edges.ndjson`.
- Report data: `artifacts/r23/timestamp_recovery_report.json`.
- Source availability precedence: PR `merged_at`; otherwise
  `max(last fix-commit committer date, validated PR created_at)`; otherwise the latest close among fully validated
  linked issues. The first commit is retained for provenance but cannot establish completion of a multi-commit fix.
  Raw Git author/committer dates alone are not historical-publication proof.

To continue after the public quota resets, rerun the bulk or per-PR phase. Successful responses are replayed from
hash-checked raw bodies, not fetched again. Commit and linked-issue phases run only after pull provenance is known.
