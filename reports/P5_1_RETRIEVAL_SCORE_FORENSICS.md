# P5.1 — retrieval-score forensics

## Finding: P5.1 had no competing candidate pool, so no threshold was ever applicable
P5.1 seeded **exactly one memory per experiment cell, each in its own organisation** (`seed_cell` produces a
single index record and injects with `max_injected = 1`, no relevance floor). Consequently, for every governed
arm the vector search returned a **single** candidate, and there was never a second candidate to threshold or
rank against.

Because of this:
- **No score distribution across relevant vs irrelevant hits exists to analyse.** The requested distributions
  for {M3 relevant, S1 irrelevant, M2 ungoverned, M3 governed} degenerate to one score each, per isolated org.
- **No absolute (`tau_abs`) or margin (`top1 − top2`) threshold could have separated relevant from irrelevant
  in P5.1**, because relevant and irrelevant candidates never co-occurred in the same pool. The S1 irrelevant
  memory was injected at rate 1.00 not because it out-scored a relevant memory, but because it was the *only*
  memory present.
- The P5.1 raw per-hit similarity scores were, in any case, not persisted (ephemeral store), so even the
  single-candidate scores are unrecoverable.

This is the exact mechanism behind the **G5 failure** (irrelevant injected 1.00) and the **uninterpretability
of G4** as competitive precision (M4−M3 = 0 followed structurally, since oracle and similarity both had one
candidate).

## Implication for P5.2 (descriptive → design)
P5.2 replaces cell-isolated singletons with a **realistic shared bank**: every target query searches a pool of
1 relevant + 3 same-domain near-miss + 4 cross-technique irrelevant contracts (all passing the hard
org/repo/path/state gates), plus no-match queries with 0 relevant among 8 decoys. A **frozen decision rule** —
inject top-1 only when `top1_score ≥ tau_abs` AND `(top1_score − top2_score) ≥ tau_margin`, else abstain — is
selected on a model-free retrieval-dev split and frozen before any P5.2 model call. Only then are true
precision / recall / no-match specificity / MRR / margin / abstention well-defined and gate-testable (G4/G5).
