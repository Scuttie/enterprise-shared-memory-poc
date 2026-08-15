# R3 §6 — Multi-User Source Bank

Built through the real service path inside the official DS-1000 conda env (run `31892562338`): each SOURCE_POOL
task assigned to a source user, solved NO-MEMORY, graded by the official evaluator; only verified successes enter
the deployable bank; each verified solve is abstracted into one canonical memory (§7). One org (`r3-acme`),
**24 source users**, source_user ≠ target_user by construction.

## USER_SUCCESS_BANK (deployable)
- **verified 183 / 200 (91.5%)** — ≥150 required (§6). `distinct_source_users = 24` (every source user
  contributed).
- Library coverage: Pandas 56, Numpy 44, Matplotlib 31, Sklearn 23, Scipy 20, Tensorflow 9, **Pytorch 0**.
- Only successful, model-generated source solutions entered; source failures were never converted into positive
  memories; raw source solutions are kept as evidence only, never in a target prompt.

## GOLD_VERIFIED_BANK (diagnostic upper bound)
- 200 facts (one per SOURCE task, from the official reference solution). Used only as a verified-fact oracle /
  relevance anchor and for the M6/C5 diagnostic arms — never presented as deployable user memory.

## Honest coverage note — Pytorch stratum
All 14 Pytorch source tasks failed to solve NO-MEMORY (0/14 verified), so the deployable bank has no Pytorch
memories (the Pytorch reference facts still exist in the GOLD bank). Consequence: for Pytorch **targets** in
discovery/main, the relevance labeller finds no relevant deployable source, so the relevant arms inject nothing
for those targets (they behave as NO_MEMORY). Pytorch is 6.8% of DS-1000 (8/120 discovery, 31/450 main); the
other six libraries are well covered. This dilutes (does not bias) the Pytorch slice of any memory effect —
conservative for H1/H2 — and is reported rather than patched (no synthetic sources, §22/§26). The primary
≥150-verified gate is met at 183.

## Integrity
- `source_user ≠ target_user` for all shared conditions (disjoint 24+24 user sets).
- cross-user private injection = 0 during bank formation.
- Canonical objects carry no target values/names/tests (`assert_no_target_leakage` enforced per record).
- Artifacts: `source_bank_manifest.json` (183 USER_SUCCESS), `gold_bank_manifest.json` (200 GOLD),
  `canonical_memory_manifest.json` (183 canonical), `user_assignment.json`.
