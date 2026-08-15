# R3 §9/§10 — Renderer & Decoder Audit

Ten representation bundles B0–B9 (`experiments/actionable_memory_r3/renderers.py`) + matched decoders
(`decoders.py`), each a deterministic projection of the ONE canonical object (§7/§8). Frozen manifests:
`renderer_manifest.json`, `decoder_manifest.json`. Integrity tests: `tests/test_r3_renderers.py` (CI
`ci-r3-renderers`, green).

## Bundles (actionability ladder)
B0 PLAIN_LESSON · B1 API_OPERATION_CARD · B2 CONDITION_ACTION_TABLE · B3 PROCEDURAL_PSEUDOCODE ·
B4 AST_EDIT_SCHEMA · B5 GENERALIZED_DIFF_TEMPLATE · B6 EXECUTABLE_PROPERTY_SPEC · B7 POSITIVE_NEGATIVE_CONTRAST ·
B8 HYBRID_ACTIONABLE · B9 RAW_VERIFIED_TRACE_220 (diagnostic). Each bundle = representation renderer + matched
reader decoder; the bundle is the experimental unit (§9).

## §10 token control (verified)
- Exact budget **220 tokens** under ONE frozen tokenizer (`tiktoken cl100k_base`); the matched decoder is always
  included; higher-priority segments are added until the budget, lower-priority whole segments dropped (never
  mid-field), and omitted fields recorded. Test asserts every bundle ≤ 220 on a fully-populated canonical object
  (measured 73–133 tokens).
- Same target + same selected source ID + different renderer for every comparison (§8); enforced by the
  discovery/main seeding (one relevant source id per target, rendered per arm).

## Source-constant redaction (safety, §26)
Every marked `source_constant` (identifiers ≥2 chars → `VAR`; numeric literals → `N`) is redacted from every
view, so **no source-specific identifier is presented to the model** — verified in `test_no_source_constant_leakage`
even for the raw-trace bundle B9 (`result = df.groupby(mycol)…` → `VAR = VAR.groupby(VAR)…`). This makes the §14
source-identifier-copy hard-safety violation **0 by construction**.

## Decoder ablation hooks
The renderer accepts a `decoder=` override so the §13 ablation can swap the matched decoder for the GENERIC
decoder on the same representation; decoder hashes are frozen in `decoder_manifest.json`.
