# P5.2 — private-memory (M1) forensics (offline)

M1 (private own-source) = 0.250 < M0 = 0.375 (M1−M0 = −0.125): private memory HARMED. From persisted per-cell
data, the two families where M0 solved but M1 failed are internal_api/context_inferable and
schema/context_inferable.

## Available evidence
Per-cell arm/pass1/injected are persisted; raw/applied patches were ephemeral (`job_patches` in the CI DB), so
this is a rendering-level diagnosis, not a patch-level one. The private execution view is deterministically
reconstructable: `compile_private_view` produces a bounded, secret-scrubbed PROSE note
("Your prior verified note: …") — strictly less explicit than the structured shared views, and (like the P5.1
schema_2 M1 failure, `reports/P5_1_M1_FAILURE_FORENSICS.md`) it renders the convention as prose the model must
re-parse.

## Primary cause
**R3_INFORMATION_LOSS.** The private prose view both (a) is less explicit than the shared renderings and (b) on
context_inferable families competes with the stub's own repository clue, and the resulting note appears to have
displaced or muddied the model's core inference on 2 families where M0 (no memory) succeeded. Private-memory
advantage is **NOT OBSERVED** in P5.2 and M1 is retained only as a secondary arm in REALBENCH-R1 (R1
PRIVATE_ONLY), never the primary. Patch-level confirmation is deferred to R1, which persists raw+applied patches
for its transfer analysis.
