# P5.2 — M2 / M3 / M4 forensics (offline; no new Solar calls)

Diagnoses why the plain shared summary (M2 = 0.875) beat the governed contract (M3 = 0.688) and oracle-governed
(M4 = 0.750). Uses only persisted artifacts: the committed `calibration_results.json` (per-cell arm, pass1,
injected, **relevant_injected**, stratum). The P5.2 per-job raw/applied patches were written to `job_patches`
in the ephemeral CI database and were not exported to the committed results, so patch-text and
first-failing-assertion recovery is unavailable and no Solar rerun is permitted; the memory RENDERINGS are
deterministically reconstructable and are the basis below.

## A. M2 succeeded where M3 failed — 4 families
cache/context_inferable, config/prior_conflict (×2), schema/context_inferable. **In every one,
`relevant_injected = 1`** for M3 — the correct governed memory was retrieved, PG-validated, and injected. So
the loss is not retrieval (not R1) and not a scope/validity rejection (not R2).

## B. M2 succeeded where M4 (oracle) failed — 4 families, ALL config
config × {prior_aligned, context_inferable, prior_conflict, prior_conflict}. M4 injects the correct governed
memory by oracle (bypassing similarity), yet failed — `relevant_injected = 1` throughout. This isolates the
cause to the **governed rendering / execution view**, not retrieval: config M4 = 0.00 is fully explained by the
governed view, not by any retrieval miss.

## Primary cause
**R3_INFORMATION_LOSS / R4_SERIALIZATION_OR_PROMPT_POSITION.** The governed contract's execution view is the
codec's typed retrieval projection — a verbose JSON object (applies_when / does_not_apply_when / ordered_steps /
verification …) — whereas M2's ungoverned view is a compact summary string. Reconstructing both offline for the
affected families confirms the governed view buries the operative edge rule inside a larger serialized
structure, which the model follows less reliably than the compact summary. The oracle arm (M4) removing all
retrieval uncertainty and still trailing M2 is the decisive evidence that the deficit is representational, not
retrieval (M4−M3 = +0.062 is small).

This is a real, artifact-consistent finding: **governed formatting, as rendered, loses information relative to
a plain summary.** It is diagnostic only and does not gate REALBENCH-R1.
