# Research (synthetic benchmarks)

The synthetic benchmark **generators** used to produce the aggregate tables live in
`src/enterprise_memory/benchmarks/` (kept inside the package so their imports resolve on install):
`gaten_v2/` (paired-world bounded-edit instrument) and `m7pilot/` (renderer-isolation pilot). They are
research-only and are **not** imported by any production module.

Excluded from this release: raw Solar requests/responses, generated patches, experiment ledgers
(`*.jsonl`), and analysis outputs. This snapshot contains code sufficient to regenerate the benchmark
*inputs* deterministically, not the raw run artifacts.
