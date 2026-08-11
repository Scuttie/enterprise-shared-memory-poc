# Architecture

Two planes: a **control plane** (authoritative governance) and an **execution plane** (what the coding
model sees).

```
request
  -> private-store retrieval  +  shared-store retrieval      (physically separated)
  -> access & validity gates  (permission / scope / version / expiry / supersession / conflict)
  -> canonical SQLite contract reload   (source of truth)
  -> compact literal execution-view compiler   (deterministic; REFUSES invalid contracts)
  -> prompt injection (<=2 views)
  -> coding LLM
  -> executable sandbox tests
  -> outcome feedback (outcome_observations)
  -> private episode
  -> governed promotion (security scan + replay evidence + state machine)
```

- **Source of truth:** canonical `MemoryContract` in SQLite (never reconstructed from vector text).
- **Retrieval index:** Mem0 (replaceable); embeddings are not authoritative.
- **Execution view:** compact literal render, compiled only after gates pass.
- **Immutable audit trail:** hash-chained append-only ledger.
