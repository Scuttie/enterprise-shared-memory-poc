# REALBENCH-R13 — Memory Representation (Encoding/Decoding) Study — Preregistration

The core research question: **which ENCODING and DECODING of transferred memory actually helps?** Everything
except the encoding is held FIXED (reused from R11): the 109 covered targets, each target's relevant source and
matched shuffled source, the reader, the benchmark, the injection position, the token budget, the extraction, and
the official grader. Opened after R12 established (a) reader capability was a raw-accuracy bottleneck and (b) the
single plain memory format did not beat matched stuffing — so the representation dimension is the live question,
and a mid-band reader (gpt-4o-mini) now makes representation lift measurable.

## Discovery (primary)
- **Benchmark/reader:** LiveCodeBench (fast, cheap) + **gpt-4o-mini** (mid-band ~0.37 on the covered set → good
  dynamic range for detecting representation lift; terra is near-ceiling here and would mask differences).
- **Encoding axis (same source ID within each target):** F0 PLAIN_LESSON · F1 DEPENDENCY_API_CARD ·
  F2 EXECUTABLE_PROCEDURE · F3 POS_NEG_CONTRAST · F4 MINIMAL_CODE_SKELETON.
- **Arms:** M0 (no memory) + for each F: relevant-F and shuffled-F (matched injection indicator/position/length).
- **Primary metric — RelevantLift_F = Pass@1(relevant-F) − Pass@1(shuffled-F)**, per format. Select the encoding
  that maximises RelevantLift (leakage/violations = 0 first; ties by min negative transfer, then min injected
  tokens; NOT by p-value). Report exact McNemar + repository/task bootstrap per format.

## Decoding (secondary)
Retrieval/injection variants for the selected encoding: (a) oracle-selected source, (b) deployable retrieval +
abstention, (c) top-k multi-view, (d) injection position / token-budget variants.

## Confirmation
The single winning encoding (if any beats shuffled) is re-tested on **SWE-PolyBench + gpt-5.6-terra** (agentic,
faithful to the enterprise repo-memory use case, mid-band 0.375) under a fresh freeze.

## Rules
Source/relevance/targets reused verbatim from R11 (no new pairing); encodings target-free, no gold/target
solution or tests in memory; same source ID across a target's F0-F4; matched shuffled per format. A null (no
encoding beats shuffled) is a valid final result. R1-R12 + P6 frozen; PR#1 draft; P6 not resumed.
