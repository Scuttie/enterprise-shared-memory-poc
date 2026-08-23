# R3 §7 — Canonical Memory Audit

One authoritative `CanonicalActionMemory` per verified source (schema `r3-canon-1`,
`experiments/actionable_memory_r3/schema.py`). Structural fields are AST-derived (deterministic); semantic fields
are one temp-0 Solar abstraction over the SOURCE problem + verified solution only (never the target), constrained
to placeholders and no source-specific constants. The SAME object feeds every renderer B0–B9 (§8); no separate
per-format memories are stored. Manifest: `canonical_memory_manifest.json` (183 records).

## Semantic-field population (of 183)
| field | populated | field | populated |
|---|---|---|---|
| generalized_ast_edit | 175 | verification_procedure | 169 |
| preconditions | 168 | negative_pattern | 134 |
| applicability | 126 | positive_pattern | 99 |
| executable_properties | 70 | (ordered_operations/APIs) | ~all (AST) |

The abstraction is substantive and actionable — e.g. applicability *"When needing circular shift of column
values without losing data"*; ast_edit *"REPLACE df[COL].shift(1) with shift(-1, fill_value=…); WRAP with
.assign(); PRESERVE index"*. This gives the API-card / procedural / edit-schema / property-spec bundles
(B1–B6/B8) genuinely different content to render, which is the premise of the actionability ladder. Sparser
fields (executable_properties 70, positive_pattern 99) mean B6/B7 will be thinner for some sources — recorded so
their discovery lift is interpreted accordingly, not silently.

## Leakage & placeholder controls (§7/§26)
- **No target leakage**: `assert_no_target_leakage(reference_code, code_context)` ran for every record during
  bank formation; 0 violations (any violation would have aborted the record).
- **Source-constant marking**: each record carries `source_constants` (numeric/string literals + non-library
  identifiers from the solution). Renderers redact these to `VAR`/`N` at render time (tested,
  `tests/test_r3_renderers.py`), so no source-specific name/constant reaches a target prompt — verified even for
  the raw-trace bundle B9.
- **Deterministic projection**: every execution view is a pure function of this object + the frozen renderer
  code (`renderer_manifest.json` hashes); no per-format memory is independently authored.

## Provenance
Each record binds `source_task_id`, `source_user_id`, `source_solution_hash`, `source_evaluator_hash` (pinned
DS-1000 commit), `canonical_hash`, `governance_state=promoted_shared`, `validity=verified_source_success`.
