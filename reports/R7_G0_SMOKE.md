# R7 §2 — G0 Multi-Language GHCR + Grader Smoke (PASS 8/8)

Execution-side half of G0. Deterministically selected 2 tasks per language (before execution) and, for each,
pulled the official per-instance GHCR image, resolved its immutable digest, reproduced the clean baseline (bug
present / F2P not passing), and applied the gold patch evaluator-side to confirm all official tests pass. The
driver **imports** (never copies) the pinned harness's `DockerManager`, repo-specific parser
(`REPO_TO_PARSER_CLASS`), and `instance_level_scoring` — so the smoke is graded by the official logic.
Run `32010457972`. Results: `artifacts/swe_polybench_r7/g0_smoke/` + `g0_smoke_summary.json`.

## Result
| requirement | target | observed |
|---|---|---|
| image pull | 8/8 | **8/8** |
| clean baseline reproduction (bug present) | 8/8 | **8/8** |
| gold patch → all tests pass (resolved) | 8/8 | **8/8** |
| evaluator/environment setup failure | 0 | **0** |
| verifier/gold content in agent-visible artifacts | 0 | **0** (no agent runs; gold/test_patch evaluator-side only) |

Per language (all PASS): Java `apache__dubbo-3093`, `apache__dubbo-3317`; Python
`Significant-Gravitas__AutoGPT-4652`, `huggingface__transformers-12981`; JavaScript `mrdoob__three.js-14836`,
`mrdoob__three.js-18648`; TypeScript `angular__angular-37561`, `coder__code-server-3277`. All 8 image digests
resolved and persisted (e.g. dubbo-3093 `@sha256:73eb26f5a9236aa21c6bd5c19fc7c03cc692cf40265e35947dba9d65405a98a5`).

## Mechanics confirmed (from the pinned harness @ 9c836c5)
- Image: `ghcr.io/timesler/swe-polybench.eval.x86_64.<instance_id_lower>:latest` (public, anonymous pull; the
  namespace is `timesler`, not `amazon-science`).
- `resolved = (F2P ⊆ passed_tests) ∧ (P2P ∩ failed_tests = ∅)` via `scoring.instance_level_scoring`.
- Baseline (test_patch only, no fix): for Java the new F2P test references not-yet-added code → compile failure
  → F2P not in passed → correctly "bug present"; gold (test_patch + gold `patch`) flips F2P to pass → resolved.
- One fixed driver defect (mine, not the instrument): `apply_patch_to_container` returns int `0`==success and
  *raises* on real failure; the initial run inverted that check. Corrected → 8/8.

## Verdict
**G0 smoke PASS.** Both halves of G0 are green — dataset freeze (§1: 382 rows pinned + hashed) and execution
smoke (§2: images + evaluator reproduce baseline→gold across all four languages). No official test was modified;
gold/verifier never entered any agent-visible artifact. The instrument is validated for the **§4 G1 no-memory
pilot**, which reuses the identical pull → container → official-evaluator path with a solar-pro3 repository
agent (no memory) producing the candidate patch.
