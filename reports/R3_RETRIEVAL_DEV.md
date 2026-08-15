# R3 §15 — Retrieval Development

**Not run — superseded by the §0-C CALIBRATION STOP.** §15 develops the production-retrieval thresholds (top-k,
absolute threshold, top1–top2 margin, max injected) for the **M4 SELECTED_PRODUCTION_RETRIEVAL** confirmatory arm
on the `RETRIEVAL_DEV` split. Since the §16 G3 gate failed (no-memory Pass@1 = 0.98, near-ceiling) and the
confirmatory main (incl. M4) is therefore not run, the retrieval-threshold development that only feeds M4 is moot
and was not executed as a paid run.

The retrieval infrastructure itself IS validated: the calibration **C3 SELECTED_PRODUCTION_RETRIEVAL** arm ran
the production embedder (all-MiniLM-L6-v2, 384-d) + production Qdrant/validated_search path with a default
inject-top-1 abstention, and injected correctly (C3 Pass@1 0.99, no invalid-canonical injection, cross-user
private injection = 0). Only the *threshold tuning* is deferred. A future `REALBENCH_ACTIONABLE_MEMORY_R4` on an
in-band benchmark/model would run §15 to freeze M4's thresholds before its confirmatory main.
