# R21 — License & Distribution Boundary

- MemGovern (`QuantaAlpha/MemGovern` @ a8456580) has **no LICENSE file** (README MIT badge only). Treated as
  all-rights-reserved → **REPRODUCTION_BLOCKED** for redistribution/vendoring (§3, §15).
- This repository will NOT contain: MemGovern source, the 135K `experience_data.json`, the Chroma DB, author
  trajectory tarballs, or any upstream artifact. The upstream checkout lives only in an isolated sibling workspace.
- `UPSTREAM_RESEARCH_USE_APPROVED` is **unset** → live exact reproduction and upstream-DB execution are NOT started.
- Permitted now: provenance audit, artifact listing, public-grader recomputation of already-published trajectories
  (Stage A) — with only RESULT SUMMARIES (counts) committed here, never the upstream patches/data.
- To lift the block for Stages B–D: set `UPSTREAM_RESEARCH_USE_APPROVED=1` (legal/policy sign-off) and
  `MAX_LIVE_REPRO_BUDGET_USD`, and recover the exact GPT-4o snapshot/temperature from trajectory metadata.
