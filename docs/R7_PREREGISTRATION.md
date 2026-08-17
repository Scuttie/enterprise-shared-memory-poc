# REALBENCH_SWE_POLYBENCH_R7 — Preregistration

Opened by R6 §6 (Endpoint B). Instrument = **SWE-PolyBench Verified** (Amazon Science, MIT), audited PASS
(`reports/R7_SWE_POLYBENCH_AUDIT.md`, live 2026-08-17). This preregistration fixes the design **before** any paid
run. Nothing here executes under R6; R6 only *opens* R7. Exact **resolved rate** (binary F2P→pass on the official
verifier) is the sole KPI — no custom partial score, no p-value-based reader selection.

## G0 — Instrument freeze (pre-run)
Pin dataset revision + `run_evaluation.py` commit + GHCR image digests; resolve **Verified N** programmatically
(`len(load_dataset("AmazonScience/SWE-PolyBench_Verified"))`; live viewer=382 vs card=394). Smoke-test that ≥1
GHCR instance image pulls and evaluates end-to-end. Record all in `configs/swe_polybench_r7/instrument_lock.json`.
The official F2P/P2P verifier and the gold `patch`/`test_patch` are **never exposed to the agent**.

## G1 — No-memory calibration pilot (the dynamic-range GATE)
Run the **available reader** (Solar-pro2/pro3 via a SWE-PolyBench-compatible agent; company reader when supplied —
`COMPANY_REPLICATION = PENDING_CONFIGURATION`, GLM not guessed) with **no memory** on a frozen stratified pilot
(≥ 40 Verified instances, language-balanced). **Gate:** no-memory resolved rate ∈ **[0.10, 0.70]**.
- **In-band → proceed** to the M0–M4 memory arms below.
- **< 0.10 (floor) or > 0.70 (ceiling) → STOP** (mirror of R3/R5/R6): the reader lacks dynamic range on this
  instrument; do not run confirmatory arms; record as an instrument/reader stop. Do **not** switch benchmarks to
  chase a band, and do **not** weaken/strengthen the reader or reselect instances to force in-band.

## §7 — Memory design (M0–M4), run only if G1 is in-band
Retrieval-augmented memory over prior *resolved* SWE-PolyBench instances; memory injected into the agent context,
never the verifier. **Hard leakage rules (invariant):** the **target instance is never its own source memory**;
**`source_user ≠ target_user`**; the gold `patch`/`test_patch`/F2P identity of the target is never present in any
memory; retrieval is blind to the target's solution. Same binary KPI.

| arm | memory content | tests |
|---|---|---|
| **M0** NO_MEMORY | none (= G1 baseline) | floor/ceiling reference |
| **M1** CROSS_ISSUE_SAME_REPO | distilled fixes from *other* resolved issues in the **same repo** (different issue/author) | does same-project experience transfer? |
| **M2** CROSS_REPO_SAME_LANG | distilled fixes from *other* repos in the **same language** | does broader same-language experience help? |
| **M3** LOCALIZATION_HINT (governed) | structural pointer to the files/functions to change (derived from `is_func_only`/`num_func_changes`), **patch withheld** | does non-leaking localization memory help? |
| **M4** SHUFFLED_MATCHED (control) | M1/M2-format memory from a **mismatched** instance, matched on language + change-size | isolates *relevance* from mere context-stuffing |

## Primary & secondary endpoints (prereg, run only post-gate)
- **Primary:** relevant-memory − shuffled-matched control on in-band instances: **(M1 ∪ M2) − M4** resolved-rate
  difference (paired McNemar / bootstrap CI). This is the analogue of SkillsBench's S1−S3 — it controls for
  context volume so a positive cannot be a stuffing artifact.
- **Secondary:** M1−M0 (same-repo lift), M2−M0 (cross-repo lift), M3−M0 (localization lift). Report per-language.
- **Powered N** fixed pre-result from the pilot's in-band rate; report leakage audit + retrieval provenance for
  every hit. No arm is added/dropped after seeing outcomes.

## Standing constraints
R1–R6 frozen/immutable; no official task/test/verifier modification; verifier & gold never exposed; no synthetic
instances; no benchmark switch to flee a null; resolved rate (binary) is the only KPI; company harness PENDING
(no GLM guess); **P6 not started**; PR#1 draft/OPEN; `main` `d56d178`; version `0.2.0.dev1`.
