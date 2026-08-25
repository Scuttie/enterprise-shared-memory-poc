# R22 paid-oracle preregistration v2 (authoritative)

**No model calls have been made. This is a preregistration for the paid reader-band + P1 + P2 oracle campaign.**
P3 confirmatory main is **withheld** (power-blocked, effective N≈60, +5pp power ≈0.09). Supersedes v1 for execution.

## Reader-band selection (§3, before any memory result)
Frozen candidate order: `deepseek-chat` → `gpt-4o-mini` → `gpt-4o`. Each candidate runs **O0 NO_MEMORY on the
frozen 40-task dev set** only. Select the **first** candidate with resolved rate in **[0.10, 0.70]** (not the
highest). Stop at the first in-band candidate; later candidates are not run. If none is in band →
`R22_READER_BAND_STOP`. The selected reader's 40 O0 cells are **reused** as P2's O0 (never re-called). A DeepSeek
alias run is labelled `MODEL_DRIFT_REPLICATION`. The returned model ID is stored on every call; if it changes
mid-campaign, stop immediately. Losing candidates' O0 results are kept as instrument diagnostics only.

## Cells (§4)
- Reader selection: ≤ 40 O0 runs per candidate; stop at first in-band.
- **P1**: 12 tasks × O0–O6 = **84**.
- **P2**: 40 tasks × O0–O6 = **280 analyzed**; for the selected reader O0 (40) is reused → **240 new** (O1–O6).
- **Selected-reader new total**: 40 (reader O0) + 84 (P1) + 240 (P2 O1–O6) = **364**.

## Arms + primary hypotheses (§6)
O0 NO_MEMORY · O1 COMPUTE_CONTROL · O2 SHUFFLED_STAGE_MEMORY · O3 RELATED_FULL_PRECEDENT ·
O4 RELATED_ISSUE_CARD · O5 RELATED_STAGE_SEMANTIC · O6 RELATED_STAGE_DUAL.
Holm primaries: **Q1 = O5 − O2**, **Q2 = O5 − O4**, **Q3 = O6 − O5**.
Diagnostics: O1−O0, O2−O1, O3−O0, O3−O2, O4−O1, O5−O1, O6−O1.
Product candidates: **O4/O5/O6** (O3 is an oracle upper bound, not selectable). P2 is development method-discovery,
**not** a confirmatory efficacy claim.

## Approval variables (§5, separated)
- `R22_READER_SELECTION_BUDGET_USD` (reader band) ≥ chosen-candidate reader-band hard cap.
- `R22_SMOKE_BUDGET_USD` (P1) ≥ selected-reader P1 hard cap.
- `R22_ORACLE_BUDGET_USD` (P2) ≥ selected-reader P2 total hard cap.
- `RUN_APPROVED` must equal exactly `RUN_APPROVED`.
- **`R22_MAIN_BUDGET_USD` must NOT be set or requested** (P3 withheld).

Hard caps per candidate: `reports/R22_PAID_COST_PLAN_V2.md` / `configs/r22/paid_run_plan_v2.json`.

## Execution order (§7 — not executed in this commit)
A reader-band O0 pilot → B reader lock commit → C P1 12×7 → D P1 integrity PASS → E P2 O1–O6 40×6 (reuse O0) →
F P2 analysis → G method verdict → H P3 NOT RUN. P1 fail ⇒ P2 forbidden. After P2, reader/task/source/arm/threshold
are not changed.

## Endpoint
`R22_PAID_PREREG_READY_FOR_APPROVAL`.
