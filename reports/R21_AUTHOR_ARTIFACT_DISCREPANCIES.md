# R21 Stage A — Discrepancies

- **Coverage shortfall:** released preds 99/99/10/128 vs published successes 116/163/70/86 (of 500). Published > released in 3/4.
- **Baseline mismatch:** released GPT-4o baseline 32.3% vs published 23.2% (non-representative subset).
- **Lift mismatch:** released GPT-4o paired lift +1.0pp vs published +9.4pp.
- **No author labels:** trajectories carry patches, not grades → author-vs-recomputed agreement uncomputable.
- **mini tarballs disjoint:** default(10) ∩ agentic(128) = 0 instances.
All discrepancies point to an incomplete release, hence AUTHOR_ARTIFACT_UNAVAILABLE (not MISMATCH, since the
published table simply cannot be reconstructed from what was released).
