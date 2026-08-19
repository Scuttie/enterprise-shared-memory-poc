# REALBENCH_SWE_POLYBENCH_R12_OPENAI — Preregistration (frozen before any memory-arm call)

Opened by R12-D0 GATE PASS (gpt-5.6-terra 15/40 in-band on the frozen R7 pilot). Reader = **gpt-5.6-terra**
(reasoning medium, Responses API) through the frozen R7 repository-agent harness. The 40 R7 pilot tasks are
**excluded**. A null result is final.

## Frozen partition
`artifacts/swe_polybench_r12_openai/main_partition.json` (sha256 `1287595116…`): **60 targets** (Java 10 /
Python 18 / TS 16 / JS 16), hash-stratified by language from the 342 non-pilot Verified instances that have ≥1
earlier same-repo source. Frozen before any memory-arm call.

## Source assignment (per target)
- **M1/M3 source** = the most-recent **same-repo** instance with `created_at` **strictly earlier** than the
  target (tier-1 relevance: shared codebase/APIs). Never the target; never a pilot/other-target.
- **M2 source** = a **cross-repo, same-language**, earlier instance (technique-mismatched by construction),
  deterministic pick.
- Synthetic 24-user org: `source_user ≠ target_user` (enforced). `created_at(source) < created_at(target)`
  (enforced). Target never its own source (enforced).

## Corrected arms (§11)
- **M0** NO_MEMORY.
- **M1** EVALUATOR_RELEVANT_PRIOR — a plain lesson distilled from the frozen relevant same-repo source (problem +
  its gold patch), **target-free, no gold patch verbatim**; the agent never sees any gold patch/test.
- **M2** SHUFFLED_MATCHED_PRIOR — plain lesson from the matched cross-repo source; same injection indicator/
  position as M1; technique-mismatched.
- **M3** EXECUTABLE_SAME_SOURCE — **exact same source ID as M1**, executable/procedural rendering (representation
  contrast).
- **M4** DEPLOYABLE_RETRIEVAL — retrieve a source using ONLY the target's **public** problem statement + repo
  metadata via a pinned embedder, with a frozen abstention threshold (no memory if below); canonical validation;
  no evaluator-relevant frozen label used.

## Endpoints
Primary **H1 = M1 − M2**; secondary **H2 = M3 − M1**, **H3 = M4 − M0**. Exact McNemar + repository-cluster
bootstrap. ITT (infra terminal failure = unresolved). No p-value selection; a null is final.

## Hard rules
gold patch/test never in agent context; target-derived localization (`modified_nodes`/`is_func_only`) never in
context; M1 and M3 identical source ID; M1/M2 matched injection indicator; no tool-budget/effort/prompt change
after D0; frozen sample + tasks before the first memory-arm call. R1–R11 + P6 frozen; PR#1 draft; P6 not resumed.
