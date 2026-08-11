# Source provenance

- source branch: `codex/enterprise-shared-memory-m7-pilot`
- source commit: `4487ea6`
- release version: `v0.1.0-poc`

This release is an **intentionally sanitised snapshot**, not the full research monorepo. Git history is
squashed to a single initial commit. Excluded: raw Solar requests/responses, generated patches,
experiment ledgers (`*.jsonl`), live SQLite/Qdrant state, model caches, virtual environments, wheels,
background logs, and all unrelated durable-memory research artifacts. Only the product implementation,
production tests, an offline demo, and reproducibility-relevant benchmark generators are included.

**Structural note:** the synthetic benchmark *generators* live in `src/enterprise_memory/benchmarks/`
(so their imports resolve when the package is installed); benchmark *analysis* pointers are described in
`research/README.md`. Production modules never import the benchmarks package.
