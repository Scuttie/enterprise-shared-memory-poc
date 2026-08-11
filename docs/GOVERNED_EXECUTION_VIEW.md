# Governed compact-literal execution view

After all deterministic gates pass, the canonical contract is compiled into a compact view for the coding
model (`enterprise_memory.serving.governed_view`). Default renderer: `compact_literal`.

**Properties:** deterministic (no LLM rewriting) · <=120 words · literal variable/enum/operator names and
policy parameters · one applicability sentence · one direct action rule · exact editable interface · one
verification sentence · no opaque IDs / provenance / audit metadata / registry scores / target answers.

Invalid contracts (out-of-scope / expired / deprecated / quarantined / superseded / unauthorized /
conflicting-unresolved) compile to **REFUSED** — no execution text is produced.

Config: `MEMORY_EXECUTION_VIEW` in {`compact_literal` (default), `full_canonical_diagnostic`,
`concise_summary_diagnostic`}. The full canonical renderer is diagnostic-only.

**Why literal:** in the pilot, rendering applicability predicates as *natural-language paraphrases*
collapsed cache-domain execution to 0/16 while *literal* predicates scored 13/16. Do not paraphrase
predicates in the execution view.
